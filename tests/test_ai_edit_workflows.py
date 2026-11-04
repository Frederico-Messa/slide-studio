from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.jobs import AIJobs
from studio.openrouter import EditCancelled, OpenRouter
from studio.project import Project


class AIEditWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Visitor Welcome')
        self.project.save()
        self.router = OpenRouter(Path(self.temp.name) / 'config')
        self.router.update('example-key')

    def test_unsaved_and_preceding_diffs(self) -> None:
        self.project.apply_structured_edits(self.pid, 'slide', 'opening', {'edits': [{'op': 'replace_slide', 'slide_id': 'opening', 'sources': {'pt-BR': '## Novo {#opening}', 'en': '## New {#opening}'}}]})
        self.assertTrue(any('Novo' in item['diff'] for item in self.project.diffs()))
        self.assertTrue(any('Novo' in item['diff'] for item in self.project.preceding_diffs()))
        from studio.operations.retrieval import read_resource
        resources = read_resource(self.project, 'read_presentation_source', {'presentation': self.pid})
        self.assertTrue(resources['sources']['en'].startswith('---'))
        from studio.operations.retrieval import read_resource as read
        self.assertIn('variants', read(self.project, 'read_variants', {'presentation': self.pid}))
        response = {'choices': [{'message': {'content': json.dumps({'edits': []})}}]}
        with patch.object(self.router, 'completion', return_value=response) as completion, self.assertRaisesRegex(ValueError, 'no edits'):
            self.router.change(self.project, self.pid, 'presentation', '', 'Inspect changes', 'standard', model='example/text')
        dynamic = json.loads(completion.call_args.args[0]['messages'][2]['content'])
        self.assertNotIn('diff_since_save', dynamic)
        self.assertNotIn('diff_from_previous_state', dynamic)
        self.project.history_move(-1)
        self.assertTrue(any('Novo' in item['diff'] for item in self.project.preceding_diffs()))
        self.project.apply_structured_edits(self.pid, 'slide', 'opening', {'edits': [{'op': 'replace_slide', 'slide_id': 'opening', 'sources': {'pt-BR': '## Outro {#opening}', 'en': '## Other {#opening}'}}]})
        self.assertFalse(self.project.state()['canRedo'])

    def test_bilingual_whole_source_and_presentation_local_styles(self) -> None:
        pt, en = self.project.sources(self.pid)
        edited = self.router.change
        with patch.object(self.router, 'completion', return_value={'choices': [{'message': {'content': json.dumps({'edits': [{'op': 'replace_text', 'target': 'slide', 'slide_ids': ['opening'], 'languages': ['pt-BR'], 'find': 'Visitor Welcome', 'replace': 'Entrada'}, {'op': 'replace_text', 'target': 'slide', 'slide_ids': ['opening'], 'languages': ['en'], 'find': 'Visitor Welcome', 'replace': 'Welcome'}, {'op': 'replace_stylesheet', 'source': '.reveal h2 {color:red}'}, {'op': 'set_presentation_name', 'name': 'New name'}, {'op': 'set_variants', 'value': {'default': 'wide', 'variants': {'wide': {'name': 'Wide', 'description': '', 'width': 1280, 'height': 720, 'hidden_slides': []}}}}]})}}]}):
            result = edited(self.project, self.pid, 'presentation', '', 'Make the title red', 'standard', model='example/vision')
        self.assertEqual(result['images'], 0)
        self.assertEqual(self.project.variants(self.pid)['default'], 'wide')
        folder = self.project.presentation_path(self.pid)
        self.assertEqual((folder / 'studio.css').read_text(), '.reveal h2 {color:red}')
        self.assertIn('css: studio.css', self.project.sources(self.pid)[0])
        self.assertEqual(self.project.presentations()[0]['name'], 'New name')
        self.assertFalse((self.project.current / 'styles' / 'studio.css').exists())
        self.project.history_move(-1)
        self.assertFalse((folder / 'studio.css').exists())
        self.assertEqual(self.project.variants(self.pid)['default'], 'standard')
        self.assertEqual(self.project.presentations()[0]['name'], 'Visitor Welcome')

    def test_model_list_uses_unsaved_key_without_persisting(self) -> None:
        self.router.update(remove_key=True)
        with patch('studio.openrouter.request_http', return_value={'data': [{'id': 'vendor/vision', 'architecture': {'input_modalities': ['text', 'image'], 'output_modalities': ['text']}}, {'id': 'vendor/text', 'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']}}]}) as request:
            models = self.router.models('unsaved-api-key')
        self.assertEqual(request.call_args.args[0], 'unsaved-api-key')
        self.assertTrue(models[1]['imageInput'])
        self.assertFalse(models[0]['imageInput'])
        self.assertFalse(self.router.status()['hasKey'])

    def test_images_require_explicit_tool_request(self) -> None:
        response = {'choices': [{'message': {'content': json.dumps({'edits': [{'op':'replace_slide','slide_id':'opening','sources':{'pt-BR':'## Novo {#opening}','en':'## New {#opening}'}}]})}}]}
        calls = []
        def complete(payload: dict, cancelled: Event) -> dict:
            import copy
            calls.append(copy.deepcopy(payload))
            if len(calls) == 1:
                return {'choices': [{'message': {'content': '', 'tool_calls': [{'id': 'visual', 'type': 'function', 'function': {'name': 'read_slide_images', 'arguments': json.dumps({'presentation': self.pid, 'slide': 'opening'})}}]}}]}
            return response
        fake_renderer = type('FakeRenderer', (), {'slide_images': lambda *args: [('pt-BR', 'opening', b'jpg'), ('en', 'opening', b'jpg')]})()
        with patch.object(self.router, 'model_accepts_images', return_value=True), patch.object(self.router, 'completion', side_effect=complete):
            result = self.router.change(self.project, self.pid, 'slide', 'opening', 'Change the title', 'standard', fake_renderer, 'http://127.0.0.1:1234', model='example/vision')
        self.assertEqual(result['images'], 2)
        self.assertIsInstance(calls[0]['messages'][-1]['content'], str)
        self.assertEqual(len([item for item in calls[1]['messages'][-1]['content'] if item['type'] == 'image_url']), 2)

    def test_cancellation_cannot_apply_model_output(self) -> None:
        cancelled = Event()
        def cancel_before_return(payload: dict, event: Event) -> dict:
            cancelled.set()
            return {'choices': [{'message': {'content': json.dumps({'edits': [{'op':'replace_slide','slide_id':'opening','sources':{'pt-BR':'## Outro {#opening}','en':'## Other {#opening}'}}]})}}]}
        with patch.object(self.router, 'completion', side_effect=cancel_before_return):
            with self.assertRaises(EditCancelled):
                self.router.change(self.project, self.pid, 'slide', 'opening', 'Change the title', 'standard', cancelled=cancelled, model='example/vision')
        self.assertNotIn('Outro', self.project.sources(self.pid)[0])

    def test_job_cancel_and_result(self) -> None:
        jobs = AIJobs()
        def operation(cancelled: Event) -> dict:
            while not cancelled.is_set():
                time.sleep(0.01)
            raise EditCancelled()
        job_id = jobs.start(operation)
        jobs.cancel(job_id)
        for _ in range(100):
            if jobs.status(job_id)['status'] == 'cancelled':
                break
            time.sleep(0.02)
        self.assertEqual(jobs.status(job_id)['status'], 'cancelled')
        self.assertEqual(jobs.active, None)


if __name__ == '__main__':
    unittest.main()
