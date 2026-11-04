from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from http_support import StudioHTTPTestCase
from studio.chats import ChatStore
from studio.edit_session import EditSession
from studio.openrouter import OpenRouter
from studio.operations.retrieval import read_resource, validate_read_request
from studio.project import Project, tree_digest


class WorkspaceDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = Project(root / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.router = OpenRouter(root / 'config')
        self.chats = ChatStore(root / 'config')
        self.pid = self.project.create_presentation('Demo')
        self.project.save()

    def test_list_and_read_saved_and_previous_diffs(self) -> None:
        original = self.project.sources(self.pid)[0]
        self.project.update_source(self.pid, 'pt-BR', original.replace('## Demo', '## Modified'))
        self.project.set_fact('Statistics', 'count', '25', None, 'Updated value')
        saved = read_resource(self.project, 'read_workspace_diff', {})
        self.assertEqual(saved['against'], 'saved')
        self.assertEqual(set(saved['changed_files']), {'facts.json', f'presentations/{self.pid}/pt-BR.qmd'})
        self.assertNotIn('Modified', str(saved))
        filename = f'presentations/{self.pid}/pt-BR.qmd'
        detail = read_resource(self.project, 'read_workspace_diff', {'against':'saved', 'path': filename})
        self.assertEqual([item['path'] for item in detail['diffs']], [filename])
        self.assertIn('+## Modified', detail['diffs'][0]['diff'])
        previous = read_resource(self.project, 'read_workspace_diff', {'against':'previous'})
        self.assertEqual(previous['changed_files'], ['facts.json'])
        folder = read_resource(self.project, 'read_workspace_diff', {'against':'saved', 'path':f'presentations/{self.pid}'})
        self.assertEqual(len(folder['diffs']), 1)
        self.assertEqual(read_resource(self.project, 'read_workspace_diff', {'path':'unmodified'})['diffs'], [])

    def test_invalid_and_unregistered_paths_rejected(self) -> None:
        for path in ('/tmp/file', '../secret', 'presentations/../secret', 'a//b', 'a\\b', './a', ''):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_read_request('read_workspace_diff', {'path':path})
        with self.assertRaises(ValueError):
            validate_read_request('read_workspace_diff', {'against':'unsupported'})
        with self.assertRaises(ValueError):
            validate_read_request('read_workspace_diff', {'unknown':'value'})

    def test_provisional_state_uses_original_saved_and_previous_baselines(self) -> None:
        self.project.set_fact('Statistics', 'count', '1', None, 'First')
        self.project.save()
        self.project.set_fact('Statistics', 'count', '2', None, 'Second')
        self.project.set_fact('Statistics', 'count', '2.5', None, 'Intermediate')
        with EditSession(self.project, 'fact_table', tree_digest(self.project.current), target='Statistics') as session:
            session.apply_provisional({'edits':[{'op':'set_fact','table':'Statistics','key':'count','value':'3'}]}, Event())
            staged = session.current()
            saved = read_resource(staged, 'read_workspace_diff', {'path':'facts.json'}, baseline_project=self.project)
            previous = read_resource(staged, 'read_workspace_diff', {'against':'previous', 'path':'facts.json'}, baseline_project=self.project)
            self.assertIn('"value": "1"', saved['diffs'][0]['diff'])
            self.assertIn('"value": "2"', previous['diffs'][0]['diff'])
            self.assertIn('"value": "3"', saved['diffs'][0]['diff'])
            self.assertIn('"value": "3"', previous['diffs'][0]['diff'])
            self.assertEqual(self.project.facts()['categories']['Statistics']['count']['value'], '2.5')

    def test_ai_chat_can_retrieve_diffs_on_demand(self) -> None:
        original = self.project.sources(self.pid)[0]
        self.project.update_source(self.pid, 'pt-BR', original.replace('## Demo', '## Edited'))
        calls: list[dict] = []

        def complete(payload: dict, cancelled: Event) -> dict:
            calls.append(copy.deepcopy(payload))
            if len(calls) == 1:
                return {'choices':[{'message':{'content':'', 'tool_calls':[{'id':'diff1','type':'function','function':{'name':'read_workspace_diff','arguments':json.dumps({'path':f'presentations/{self.pid}/pt-BR.qmd'})}}]}}]}
            return {'choices':[{'message':{'content':'One source file was edited.'}}]}

        with patch.object(self.router, 'completion', side_effect=complete):
            answer = self.router.chat(self.project, self.chats, {'messages':[], 'draft_id':'temporary'}, 'What changed?', Event(), model='provider/model')
        self.assertEqual(answer['answer'], 'One source file was edited.')
        self.assertNotIn('diff_since_save', str(calls[0]['messages']))
        self.assertEqual(calls[1]['messages'][-1]['role'], 'tool')
        self.assertIn('+## Edited', json.loads(calls[1]['messages'][-1]['content'])['diffs'][0]['diff'])
        self.assertIn('read_workspace_diff', [item['function']['name'] for item in calls[0]['tools']])


class SourceBaselineHTTPTests(StudioHTTPTestCase):
    def test_editor_reads_saved_source_without_overwriting_draft(self) -> None:
        pid = self.request('/api/presentations', 'POST', {'name':'Example'})['id']
        saved_path = f'/api/source/saved?presentation={pid}&language=pt-BR'
        initial = self.server.project.sources(pid)[0]
        self.assertEqual(self.request(saved_path)['source'], '')
        self.request('/api/save', 'POST', {})
        self.assertEqual(self.request(saved_path)['source'], initial)
        revised = initial.replace('## Example', '## Updated')
        self.request('/api/source','POST',{'presentation':pid,'language':'pt-BR','source':revised})
        self.assertEqual(self.request(saved_path)['source'], initial)
        self.assertEqual(self.request('/api/state?presentation=' + pid)['sources']['pt-BR'], revised)
        self.request('/api/save','POST',{})
        self.assertEqual(self.request(saved_path)['source'], revised)


if __name__ == '__main__':
    unittest.main()
