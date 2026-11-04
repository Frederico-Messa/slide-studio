from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.chats import ChatStore
from studio.openrouter import OpenRouter
from studio.operations.retrieval import READ_TOOLS, read_resource, workspace_index
from studio.project import Project
from studio.scripts import update_script


class WorkspaceIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = Project(root / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Welcome')
        self.project.update_presentation(self.pid, 'Welcome', 'For incoming students')
        self.project.set_slide_description(self.pid, 'opening', 'Welcome introduction')
        self.project.set_fact('Students', 'count', '345', '2026-11-02', 'Enrollment data')
        self.project.set_asset('Campus/main', 'campus.png', b'12345', 'Campus photograph', 'Campus')
        self.project.set_asset('Campus/Auditoriums/main', 'aud.png', b'6789', 'Main auditorium', 'Campus/Auditoriums')
        self.project.create_asset_folder('Campus/Empty')
        update_script(self.project, 'update-faculty', {'name': 'Faculty photographs', 'description': 'Update portraits', 'parameters': []}, 'print("a unique script secret")')
        self.router = OpenRouter(root / 'config')
        self.chats = ChatStore(root / 'config')

    def test_compact_index_has_labels_but_no_metadata_or_sources(self) -> None:
        index = workspace_index(self.project)
        self.assertEqual(set(index), {'presentations', 'scripts', 'recipes'})
        presentation = index['presentations'][0]
        self.assertEqual(presentation['description'], 'For incoming students')
        self.assertEqual(presentation['variants'][0]['id'], 'standard')
        self.assertEqual(presentation['slides'][0]['id'], 'opening')
        self.assertEqual(presentation['slides'][0]['description'], 'Welcome introduction')
        self.assertEqual(presentation['slides'][0]['titles']['pt-BR'], 'Welcome')
        self.assertEqual(index['scripts'], [{'id':'update-faculty','name':'Faculty photographs','description':'Update portraits'}])
        payload = json.dumps(index)
        for excluded in ('Enrollment data', 'Campus photograph', '345', 'campus.png', 'a unique script secret', 'hidden_slides', 'parameters'):
            self.assertNotIn(excluded, payload)

    def test_registry_listing_separate_from_metadata(self) -> None:
        tools = {entry['function']['name']: entry['function'] for entry in READ_TOOLS}
        self.assertEqual(set(tools['list_all_facts']['parameters']['properties']), set())
        self.assertEqual(set(tools['list_all_assets']['parameters']['properties']), set())
        facts = read_resource(self.project, 'list_all_facts', {})
        self.assertEqual(facts, {'tables': {'Students': ['count']}})
        self.assertNotIn('345', json.dumps(facts))
        assets = read_resource(self.project, 'list_all_assets', {})
        self.assertEqual(assets['folders']['Campus'], ['Campus/main'])
        self.assertEqual(assets['folders']['Campus/Auditoriums'], ['Campus/Auditoriums/main'])
        self.assertEqual(assets['folders']['Campus/Empty'], [])
        self.assertEqual(assets['folders'][''], [])
        self.assertNotIn('Campus photograph', json.dumps(assets))
        with self.assertRaises(ValueError):
            read_resource(self.project, 'list_all_facts', {'prefix': 'Students'})
        self.assertEqual(read_resource(self.project, 'read_facts_metadata', {'prefix': 'Students'})['facts']['Students']['count']['value'], '345')
        self.assertEqual(read_resource(self.project, 'read_assets_metadata', {'prefix': 'Campus/main'})['assets']['Campus/main']['description'], 'Campus photograph')

    def test_chat_knows_interface_selection_without_automatic_source(self) -> None:
        history = self.chats.create('Conversation')
        calls: list[dict] = []
        def finish(payload: dict, _cancel: Event) -> dict:
            calls.append(copy.deepcopy(payload))
            return {'choices': [{'message': {'content': 'Visible.'}}]}
        with patch.object(self.router, 'completion', side_effect=finish):
            self.router.chat(self.project, self.chats, history, 'What is this slide?', Event(), model='test', selection={'presentation': self.pid, 'variant': 'standard', 'language': 'en', 'slide': 'opening'})
        messages = calls[0]['messages']
        selection_text, question = messages[-1]['content'].split('\n\n', 1)
        self.assertEqual(question, 'What is this slide?')
        self.assertEqual(json.loads(selection_text.split(': ', 1)[1]), {'presentation': self.pid, 'language': 'en', 'variant': 'standard', 'slide': 'opening'})
        self.assertNotIn('345', messages[1]['content'])
        self.assertIn('list_all_assets', [tool['function']['name'] for tool in calls[0]['tools']])

    def test_chat_retrieves_fact_identifiers_and_then_values(self) -> None:
        history = self.chats.create('Facts')
        payloads: list[dict] = []
        def tool_reply(name: str, arguments: dict[str, str], number: int) -> dict:
            return {'choices':[{'message':{'content':'','tool_calls':[{'id':f'call{number}','type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]}}]}
        def finish(payload: dict, _cancel: Event) -> dict:
            payloads.append(copy.deepcopy(payload))
            if len(payloads) == 1:
                return tool_reply('list_all_facts', {}, 1)
            if len(payloads) == 2:
                self.assertEqual(json.loads(payloads[1]['messages'][-1]['content'])['tables'], {'Students': ['count']})
                return tool_reply('read_facts_metadata', {'prefix': 'Students.count'}, 2)
            self.assertEqual(json.loads(payloads[2]['messages'][-1]['content'])['facts']['Students']['count']['value'], '345')
            return {'choices':[{'message':{'content':'345 students.'}}]}
        with patch.object(self.router, 'completion', side_effect=finish):
            result = self.router.chat(self.project, self.chats, history, 'How many students?', Event(), model='test')
        self.assertEqual(result['answer'], '345 students.')
        self.assertNotIn('345', payloads[0]['messages'][1]['content'])

    def test_invalid_ui_selection_is_not_forwarded(self) -> None:
        self.assertEqual(self.router.current_selection(self.project, {'presentation': 'not-present'}), {})
        self.assertEqual(self.router.current_selection(self.project, {'presentation': self.pid, 'slide': 'fake', 'variant': 'fake', 'language': 'xx'}), {'presentation': self.pid})
        self.assertEqual(self.router.current_selection(self.project, None), {})

    def test_edit_receives_index_and_target_with_diffs_not_resource_contents(self) -> None:
        requests: list[dict] = []
        def finish(payload: dict, _cancel: Event) -> dict:
            requests.append(copy.deepcopy(payload))
            return {'choices': [{'message': {'content': '{"edits":[{"op":"set_fact","table":"Students","key":"count","value":"346"}]}'}}]}
        with patch.object(self.router, 'completion', side_effect=finish):
            self.router.change_resource(self.project, 'fact_table', 'Students', 'Check current figures', model='test')
        messages = requests[0]['messages']
        self.assertNotIn('Enrollment data', messages[1]['content'])
        edit = json.loads(messages[2]['content'])
        self.assertEqual(edit['target_context']['target'], 'Students')
        self.assertNotIn('selected', edit['target_context'])
        self.assertNotIn('diff_since_save', edit)
        self.assertNotIn('diff_from_previous_state', edit)
        self.assertTrue(any(tool['function']['name'] == 'read_facts_metadata' for tool in requests[0]['tools']))


if __name__ == '__main__':
    unittest.main()
