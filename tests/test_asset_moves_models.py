from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.chats import ChatStore
from studio.openrouter import OpenRouter, clean_usage, reasoning_settings, request_stream_worker
from studio.preferences import Preferences
from studio.project import Project, validate_asset_alias


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)

    def test_root_assets_creation_move_and_references(self) -> None:
        presentation = self.project.create_presentation('Example')
        self.project.set_asset('intro', 'intro.png', b'file A', 'Introduction', '')
        self.project.set_asset('Buildings/hall', 'hall.png', b'file B', 'Hall', 'Buildings')
        self.assertEqual(self.project.assets()['assets']['intro']['category'], '')
        self.assertEqual(self.project.asset_state()['assets']['intro']['bytes'], 6)
        for language, source in zip(('pt-BR', 'en'), self.project.sources(presentation)):
            self.project.update_source(presentation, language, source + '\n{{asset:Buildings/hall}} {{asset:intro}}\n')
        self.project.move_assets({'Buildings/hall':'hall'})
        self.assertEqual(self.project.assets()['assets']['hall']['category'], '')
        for source in self.project.sources(presentation):
            self.assertIn('{{asset:hall}}', source)
            self.assertNotIn('{{asset:Buildings/hall}}', source)
        self.project.history_move(-1)
        self.assertIn('Buildings/hall', self.project.assets()['assets'])
        self.project.history_move(1)
        self.project.save()
        self.assertIn('hall', json.loads((self.project.workspace / 'assets.json').read_text())['assets'])

    def test_root_alias_and_move_validation(self) -> None:
        validate_asset_alias('cover')
        validate_asset_alias('Architecture/Photos/cover')
        for invalid in ('', '/cover', 'Architecture/', '../cover', 'image with spaces'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_asset_alias(invalid)
        self.project.set_asset('cover', 'cover.png', b'png', '', '')
        self.project.set_asset('Other/cover', 'cover.png', b'png', '', 'Other')
        with self.assertRaisesRegex(ValueError, 'Destination asset already exists'):
            self.project.move_assets({'Other/cover':'cover'})
        self.project.move_assets({'cover':'Other/swap', 'Other/cover':'cover'})
        self.assertIn('cover', self.project.assets()['assets'])
        self.assertIn('Other/swap', self.project.assets()['assets'])


class AISettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.store = ChatStore(self.root / 'config')
        self.router = OpenRouter(self.root / 'config')
        self.router.update(key='test-key')

    def test_model_metadata_and_effort(self) -> None:
        catalog = {'data': [
            {'id':'vendor/reasoning','name':'Reasoning','context_length':16384,'reasoning':{'supported_efforts':['low','high']},'architecture':{'input_modalities':['text','image'],'output_modalities':['text']}},
            {'id':'vendor/text','name':'Text','context_length':4096,'architecture':{'input_modalities':['text'],'output_modalities':['text']}},
        ]}
        with patch('studio.openrouter.request_http', return_value=catalog) as request:
            models = self.router.models()
            self.assertEqual(self.router.models(), models)
            request.assert_called_once()
        self.assertEqual(models[0]['reasoningEfforts'], ['low', 'high'])
        self.assertEqual(models[0]['contextLength'], 16384)
        self.assertIsNone(models[1]['reasoningEfforts'])
        self.assertEqual(reasoning_settings('default'), {})
        self.assertEqual(reasoning_settings('max'), {'reasoning':{'effort':'max'}})
        with self.assertRaises(ValueError):
            reasoning_settings('infinite')

    def test_chat_only_persists_after_success_and_tracks_real_usage(self) -> None:
        self.project.create_presentation('Example')
        self.router.catalog = [{'id':'vendor/model','name':'Model','imageInput':False,'contextLength':131072,'reasoningEfforts':['low','high']}]
        draft = {'id':'', 'messages':[], 'revision':0}
        usage = {'prompt_tokens':5000,'completion_tokens':120,'prompt_tokens_details':{'cached_tokens':3000}}
        with patch.object(self.router, 'completion', return_value={'choices':[{'message':{'content':'Answer'}}], 'usage':usage}) as completion:
            result = self.router.chat(self.project, self.store, draft, 'Question?', Event(), model='vendor/model', effort='low')
        self.assertEqual(completion.call_args.args[0]['model'], 'vendor/model')
        self.assertEqual(completion.call_args.args[0]['reasoning'], {'effort':'low'})
        self.assertIn('cannot modify files', completion.call_args.args[0]['messages'][0]['content'])
        self.assertEqual(len(self.store.list()), 1)
        current = self.store.get(result['chat'])
        self.assertEqual(current['model'], 'vendor/model')
        self.assertEqual(current['reasoning_effort'], 'low')
        self.assertEqual(current['messages'][-1]['usage']['prompt_tokens'], 5000)
        self.assertEqual(current['messages'][-1]['usage']['completion_tokens'], 120)
        self.assertEqual(current['messages'][-1]['usage']['cached_tokens'], 3000)
        self.assertEqual(current['messages'][-1]['usage']['context_length'], 131072)
        with patch.object(self.router, 'completion', side_effect=ValueError('Network error')):
            with self.assertRaisesRegex(ValueError, 'Network error'):
                self.router.chat(self.project, self.store, draft, 'Unsent', Event(), model='vendor/model', effort='low')
        self.assertEqual(len(self.store.list()), 1)

    def test_chat_settings_branch_and_restore_usage(self) -> None:
        item = self.store.append_new_exchange('One', 'Answer one', 'vendor/first', 'high', {'prompt_tokens':30,'completion_tokens':10})
        self.store.settings(item['id'], 'vendor/second', 'low')
        self.assertEqual(self.store.get(item['id'])['model'], 'vendor/second')
        branch = self.store.create('Branch',item['id'],2)
        self.assertEqual(branch['model'],'vendor/second')
        self.assertEqual(branch['messages'][1]['usage']['prompt_tokens'],30)
        self.store.append_exchange(branch['id'],0,'Two','Answer two',{'prompt_tokens':55,'completion_tokens':30},'vendor/second')
        self.store.restore(branch['id'],2)
        self.assertEqual(len(self.store.get(branch['id'])['messages']),2)
        with patch.object(self.router, 'completion', return_value={'choices':[{'message':{'content':'Answer three'}}]}) as completion:
            self.router.chat(self.project, self.store, self.store.get(item['id']), 'Question three', Event(), model='vendor/second', effort='default')
        previous = completion.call_args.args[0]['messages']
        self.assertFalse(any('usage' in message for message in previous))

    def test_existing_chat_retains_model_and_reasoning_used(self) -> None:
        current = self.store.create('Existing')
        self.router.catalog = [{'id':'vendor/second', 'contextLength':8192, 'imageInput':False}]
        with patch.object(self.router, 'completion', return_value={'choices':[{'message':{'content':'Updated answer'}}], 'usage':{'prompt_tokens':140,'completion_tokens':20}}) as completion:
            self.router.chat(self.project, self.store, current, 'Updated question', Event(), model='vendor/second', effort='medium')
        saved = self.store.get(current['id'])
        self.assertEqual(saved['model'], 'vendor/second')
        self.assertEqual(saved['reasoning_effort'], 'medium')
        self.assertEqual(saved['messages'][-1]['usage']['context_length'],8192)
        self.assertEqual(completion.call_args.args[0]['reasoning'],{'effort':'medium'})

    def test_preferences_store_model_choices(self) -> None:
        preferences = Preferences(self.root / 'config')
        preferences.update({'editModel':'vendor/edit','editEffort':'max','chatModel':'vendor/chat','chatEffort':'low'})
        values = Preferences(self.root / 'config').read()
        self.assertEqual(values['editModel'],'vendor/edit')
        self.assertEqual(values['chatEffort'],'low')
        with self.assertRaisesRegex(ValueError, 'Invalid reasoning'):
            preferences.update({'editEffort':'huge'})

    def test_usage_requires_actual_values(self) -> None:
        self.assertIsNone(clean_usage(None))
        self.assertIsNone(clean_usage({'prompt_tokens':'100','completion_tokens':2}))
        self.assertEqual(clean_usage({'prompt_tokens':123,'completion_tokens':456}),{'prompt_tokens':123,'completion_tokens':456})


if __name__ == '__main__':
    unittest.main()

class APIChatTests(unittest.TestCase):
    def setUp(self) -> None:
        import threading
        from app import StudioServer
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = StudioServer(('127.0.0.1', 0), Path(self.temp.name) / 'workspace')
        self.server.chats = ChatStore(Path(self.temp.name) / 'config')
        self.server.openrouter.key = 'test-key'
        self.addCleanup(self.server.project.temporary.cleanup)
        self.addCleanup(self.server.renderer.temp.cleanup)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path: str, data: dict[str, object] | None = None) -> dict[str, object] | list[dict[str, object]]:
        import urllib.request
        encoded = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(self.base + path, data=encoded, method='POST' if data is not None else 'GET', headers={'Content-Type':'application/json','X-Studio-Token':self.server.csrf})
        with urllib.request.urlopen(request,timeout=5) as response:
            return json.load(response)

    def job_result(self, job_id: str) -> dict[str, object]:
        import time
        for _ in range(100):
            result = self.request('/api/ai/status?job=' + job_id)
            if result['status'] in ('complete','failed','cancelled'):
                return result
            time.sleep(0.01)
        raise AssertionError('Job did not complete')

    def test_first_message_is_the_creation_of_a_chat(self) -> None:
        from threading import Event
        release = Event()
        response = {'choices':[{'message':{'content':'The workspace is empty.'}}], 'usage':{'prompt_tokens':50,'completion_tokens':12}}
        def completion(*args: object) -> dict[str, object]:
            release.wait(2)
            return response
        with patch.object(self.server.openrouter, 'completion', side_effect=completion):
            started = self.request('/api/chat/message', {'id':'','message':'What is here?','images':'none','model':'vendor/test','effort':'high'})
            self.assertEqual(self.request('/api/chats'), [])
            release.set()
            result = self.job_result(started['job'])
        self.assertEqual(result['status'],'complete')
        chat_id = result['result']['chat']
        self.assertEqual(self.request('/api/chat?id=' + chat_id)['messages'][-1]['usage']['prompt_tokens'],50)
        self.assertEqual(self.request('/api/chat?id=' + chat_id)['reasoning_effort'],'high')
        self.assertEqual(len(self.request('/api/chats')),1)
        updated = self.request('/api/chats/settings', {'id':chat_id,'model':'vendor/other','effort':'low'})
        self.assertEqual(updated['model'],'vendor/other')
        self.assertEqual(updated['reasoning_effort'],'low')

    def test_failed_first_message_does_not_create_a_chat(self) -> None:
        with patch.object(self.server.openrouter, 'completion', side_effect=ValueError('Provider failed')):
            started = self.request('/api/chat/message', {'id':'','message':'Hello','images':'none','model':'vendor/test','effort':'default'})
            result = self.job_result(started['job'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.request('/api/chats'),[])
