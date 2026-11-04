from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.openrouter import EditCancelled, OpenRouter
from studio.project import Project, tree_digest


class ProvisionalEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Project(Path(self.temporary.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.presentation = self.project.create_presentation('Example')
        self.router = OpenRouter(Path(self.temporary.name) / 'config')
        self.original = self.project.sources(self.presentation)
        self.history_position = self.project.position

    def operation(self, find: str = 'Example', replace: str = 'Previewed', slide: str = 'opening') -> dict:
        return {'edits': [{'op': 'replace_text', 'target': 'slide', 'slide_ids': [slide], 'find': find, 'replace': replace}]}

    @staticmethod
    def tool(name: str, arguments: dict, call_id: str = 'call-1') -> dict:
        return {'choices': [{'message': {'content': None, 'tool_calls': [{'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}]}

    @staticmethod
    def done(edits: list[dict] | None = None) -> dict:
        return {'choices': [{'message': {'content': json.dumps({'edits': edits if edits is not None else []})}}]}

    def test_provisional_edit_can_be_inspected_and_committed_once(self) -> None:
        prompts: list[dict] = []
        def complete(payload: dict, cancelled: Event) -> dict:
            import copy
            prompts.append(copy.deepcopy(payload))
            if len(prompts) == 1:
                return self.tool('apply_provisional_edits', self.operation())
            if len(prompts) == 2:
                self.assertEqual(self.project.sources(self.presentation), self.original)
                return self.tool('read_slide_source', {'presentation': self.presentation, 'slide': 'opening'}, 'call-2')
            return self.done()
        with patch.object(self.router, 'completion', side_effect=complete):
            self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename slide', 'standard', model='model')
        self.assertEqual(len(prompts), 3)
        self.assertIn('Previewed', json.loads(prompts[2]['messages'][-1]['content'])['sources']['pt-BR'])
        self.assertEqual(self.project.position, self.history_position + 1)
        self.assertIn('Previewed', self.project.sources(self.presentation)[0])
        self.assertTrue(self.project.history_move(-1))
        self.assertEqual(self.project.sources(self.presentation), self.original)
        self.assertTrue(self.project.history_move(1))
        self.assertIn('Previewed', self.project.sources(self.presentation)[1])

    def test_rendered_images_come_from_provisional_project(self) -> None:
        incoming: list[dict] = []
        renders: list[str] = []
        class FakeRenderer:
            def slide_images(self, pid: str, variant: str, scope: str, slide: str, base_url: str, cancelled: Event, source_project: Project | None = None) -> list[tuple[str, str, bytes]]:
                assert source_project is not None
                source = source_project.sources(pid)[0]
                renders.append(source)
                return [('pt-BR', 'opening', b'pt-image'), ('en', 'opening', b'en-image')]
        def complete(payload: dict, cancelled: Event) -> dict:
            import copy
            incoming.append(copy.deepcopy(payload))
            if len(incoming) == 1:
                return self.tool('apply_provisional_edits', self.operation())
            if len(incoming) == 2:
                return self.tool('read_slide_images', {'presentation': self.presentation, 'slide': 'opening'}, 'call-2')
            return self.done()
        with patch.object(self.router, 'completion', side_effect=complete), patch.object(self.router, 'model_accepts_images', return_value=True):
            result = self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename', 'standard', FakeRenderer(), 'http://127.0.0.1:12345', model='model')
        self.assertEqual(result['images'], 2)
        self.assertIn('Previewed', renders[0])
        self.assertEqual(sum(part['type'] == 'image_url' for part in incoming[2]['messages'][-1]['content']), 2)
        self.assertIn('Previewed', self.project.sources(self.presentation)[0])

    def test_invalid_provisional_operation_returns_error_and_can_be_corrected(self) -> None:
        requests: list[dict] = []
        def complete(payload: dict, cancelled: Event) -> dict:
            import copy
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return self.tool('apply_provisional_edits', self.operation(slide='other'))
            if len(requests) == 2:
                self.assertIn('error', json.loads(requests[1]['messages'][-1]['content']))
                self.assertEqual(self.project.sources(self.presentation), self.original)
                return self.tool('apply_provisional_edits', self.operation(), 'call-2')
            return self.done()
        with patch.object(self.router, 'completion', side_effect=complete):
            self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename', 'standard', model='model')
        self.assertEqual(self.project.position, self.history_position + 1)

    def test_cancel_after_provisional_changes_discards_everything(self) -> None:
        cancel = Event()
        calls = 0
        def complete(payload: dict, cancelled: Event) -> dict:
            nonlocal calls
            calls += 1
            if calls == 1:
                return self.tool('apply_provisional_edits', self.operation())
            cancel.set()
            return self.done()
        with patch.object(self.router, 'completion', side_effect=complete):
            with self.assertRaises(EditCancelled):
                self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename', 'standard', cancelled=cancel, model='model')
        self.assertEqual(self.project.sources(self.presentation), self.original)
        self.assertEqual(self.project.position, self.history_position)

    def test_exceeding_scope_does_not_change_provisional_state(self) -> None:
        attempts: list[dict] = []
        def complete(payload: dict, cancelled: Event) -> dict:
            attempts.append(payload)
            if len(attempts) == 1:
                return self.tool('apply_provisional_edits', {'edits': [{'op': 'set_presentation_name', 'name': 'Other'}]})
            return self.done([self.operation()['edits'][0]])
        with patch.object(self.router, 'completion', side_effect=complete):
            self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename', 'standard', model='model')
        self.assertIn('Previewed', self.project.sources(self.presentation)[0])
        self.assertEqual(self.project.presentations()[0]['name'], 'Example')

    def test_resource_edits_can_be_provisional_and_discarded(self) -> None:
        self.project.set_fact('Students', 'total', '100', None, 'Number')
        baseline = tree_digest(self.project.current)
        calls = 0
        def complete(payload: dict, cancelled: Event) -> dict:
            nonlocal calls
            calls += 1
            if calls == 1:
                return self.tool('apply_provisional_edits', {'edits': [{'op':'set_fact', 'table':'Students', 'key':'total', 'value':'200'}]})
            if calls == 2:
                self.assertEqual(tree_digest(self.project.current), baseline)
                return self.tool('read_facts_metadata', {'prefix': 'Students.total'}, 'call-2')
            return self.done()
        with patch.object(self.router, 'completion', side_effect=complete):
            self.router.change_resource(self.project,'fact_table','Students','Update count',model='model')
        self.assertEqual(self.project.facts()['categories']['Students']['total']['value'], '200')

    def test_provisional_and_final_edits_share_one_undo_step(self) -> None:
        calls = 0
        def complete(payload: dict, cancelled: Event) -> dict:
            nonlocal calls
            calls += 1
            if calls == 1:
                return self.tool('apply_provisional_edits', self.operation())
            return self.done(self.operation(find='Previewed', replace='Final')['edits'])
        with patch.object(self.router, 'completion', side_effect=complete):
            self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename', 'standard', model='model')
        self.assertEqual(self.project.position, self.history_position + 1)
        self.assertIn('Final', self.project.sources(self.presentation)[0])
        self.assertTrue(self.project.history_move(-1))
        self.assertEqual(self.project.sources(self.presentation), self.original)

    def test_provider_failure_discards_provisional_state(self) -> None:
        calls = 0
        def complete(payload: dict, cancelled: Event) -> dict:
            nonlocal calls
            calls += 1
            if calls == 1:
                return self.tool('apply_provisional_edits', self.operation())
            raise ValueError('Provider unavailable')
        with patch.object(self.router, 'completion', side_effect=complete):
            with self.assertRaisesRegex(ValueError, 'Provider unavailable'):
                self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename', 'standard', model='model')
        self.assertEqual(self.project.sources(self.presentation), self.original)
        self.assertEqual(self.project.position, self.history_position)

    def test_concurrent_workspace_change_rejects_staged_commit(self) -> None:
        calls = 0
        def complete(payload: dict, cancelled: Event) -> dict:
            nonlocal calls
            calls += 1
            if calls == 1:
                return self.tool('apply_provisional_edits', self.operation())
            self.project.set_fact('Students', 'total', '1', None, 'Enrolled')
            return self.done()
        with patch.object(self.router, 'completion', side_effect=complete):
            with self.assertRaisesRegex(ValueError, 'Workspace changed'):
                self.router.change(self.project, self.presentation, 'slide', 'opening', 'Rename', 'standard', model='model')
        self.assertEqual(self.project.sources(self.presentation), self.original)
        self.assertEqual(self.project.facts()['categories']['Students']['total']['value'], '1')

    def test_renderer_uses_provisional_source_without_exposing_it_as_live_preview(self) -> None:
        from types import SimpleNamespace
        from studio.edit_session import EditSession
        from studio.render import Renderer
        renderer = Renderer(self.project)
        self.addCleanup(renderer.temp.cleanup)
        baseline = tree_digest(self.project.current)
        def fake_compile(command: list[str], cwd: Path, **kwargs) -> SimpleNamespace:
            (cwd / command[2].replace('.qmd', '.html')).write_text('<html><head></head><body></body></html>', encoding='utf-8')
            return SimpleNamespace(returncode=0)
        with patch('studio.render.shutil.which', return_value='/usr/bin/quarto'), patch('studio.render.subprocess.run', side_effect=fake_compile):
            normal = renderer.render(self.presentation, 'pt-BR', 'standard')
            with EditSession(self.project, 'slide', baseline, presentation=self.presentation, slide='opening') as session:
                session.apply_provisional(self.operation(), Event())
                preview = renderer.render(self.presentation, 'pt-BR', 'standard', source_project=session.current())
                self.assertNotEqual(normal, preview)
                normal_entry = renderer.locations[normal.split('/')[2]] / 'presentations' / self.presentation / 'pt-BR.qmd'
                preview_entry = renderer.locations[preview.split('/')[2]] / 'presentations' / self.presentation / 'pt-BR.qmd'
                self.assertIn('Example', normal_entry.read_text())
                self.assertIn('Previewed', preview_entry.read_text())
        self.assertEqual(self.project.sources(self.presentation), self.original)

    def test_chat_has_no_editing_tools(self) -> None:
        from studio.chats import ChatStore
        chats = ChatStore(Path(self.temporary.name) / 'config')
        incoming: list[dict] = []
        def complete(payload: dict, cancelled: Event) -> dict:
            incoming.append(payload)
            return {'choices':[{'message':{'content':'Done'}}]}
        with patch.object(self.router, 'completion', side_effect=complete):
            self.router.chat(self.project, chats, {'messages': [], 'draft_id': 'draft'}, 'Hi', Event(), model='model')
        names = [item['function']['name'] for item in incoming[0]['tools']]
        self.assertNotIn('apply_provisional_edits', names)


if __name__ == '__main__':
    unittest.main()
