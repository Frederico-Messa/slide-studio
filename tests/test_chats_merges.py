from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.chats import ChatStore
from studio.openrouter import OpenRouter
from studio.project import Project


class ChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'config'
        self.chats = ChatStore(self.config)

    def test_create_branch_restore_and_persist(self) -> None:
        chat = self.chats.create('First')
        complete = self.chats.append_exchange(chat['id'], 0, 'Question', 'Answer')
        self.assertEqual(len(complete['messages']), 2)
        branch = self.chats.create('Branch', chat['id'], 2)
        self.chats.append_exchange(branch['id'], 0, 'Other', 'Response')
        self.assertEqual(len(self.chats.get(branch['id'])['messages']), 4)
        self.assertEqual(len(self.chats.get(chat['id'])['messages']), 2)
        self.chats.restore(branch['id'], 2)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.chats.append_exchange(branch['id'], 0, 'Stale', 'Reply')
        self.assertEqual(len(ChatStore(self.config).get(branch['id'])['messages']), 2)
        self.assertEqual(self.chats.list()[0]['count'], 2)
        self.assertEqual(self.config.joinpath('chats.json').stat().st_mode & 0o777, 0o600)

    def test_chat_has_all_presentation_context_and_no_edit(self) -> None:
        project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(project.temporary.cleanup)
        first = project.create_presentation('First')
        second = project.create_presentation('Second')
        project.set_fact('Students', 'count', '100', None, '')
        chat = self.chats.create('Review')
        router = OpenRouter(self.config)
        router.update(key='test-key')
        with patch.object(router, 'completion', return_value={'choices':[{'message':{'content':'I see both presentations.'}}]}) as completion:
            output = router.chat(project, self.chats, chat, 'What is in the workspace?', Event(), model='vendor/example')
        self.assertIn('both presentations', output['answer'])
        context = completion.call_args.args[0]['messages'][1]['content']
        self.assertIn(first, context)
        self.assertIn(second, context)
        self.assertNotIn('Students', context)
        self.assertIn('list_all_facts', [entry['function']['name'] for entry in completion.call_args.args[0]['tools']])
        self.assertIn('chat-', completion.call_args.args[0]['session_id'])
        self.assertEqual(project.state()['canUndo'], True)
        self.assertEqual(len(self.chats.get(chat['id'])['messages']), 2)
        self.assertEqual(len(project.presentations()), 2)


class MergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Examples')

    def test_merge_facts_updates_all_references_and_undo(self) -> None:
        self.project.set_fact('Students','total','120',None,'')
        self.project.set_fact('Staff','count','50',None,'')
        pt, en = self.project.sources(self.pid)
        self.project.update_source(self.pid,'pt-BR',pt+'\n{{fact:Students.total}} {{fact:Staff.count}}')
        self.project.update_source(self.pid,'en',en+'\n{{fact:Staff.count}}')
        self.project.merge_facts([{'category':'Staff','key':'count'},{'category':'Students','key':'total'}],{'category':'Students','key':'total'})
        pt, en = self.project.sources(self.pid)
        self.assertNotIn('{{fact:Staff.count}}',pt+en)
        self.assertEqual(pt.count('{{fact:Students.total}}'),2)
        self.assertNotIn('count',self.project.facts()['categories']['Staff'])
        self.project.history_move(-1)
        self.assertIn('{{fact:Staff.count}}',self.project.sources(self.pid)[0])
        with self.assertRaisesRegex(ValueError, 'Fact not found'):
            self.project.merge_facts([{'category':'Staff','key':'none'},{'category':'Students','key':'total'}],{'category':'Students','key':'total'})

    def test_merge_assets_keeps_selected_file_and_updates_sources(self) -> None:
        self.project.set_asset('Buildings/first','first.png',b'aaa','First','Buildings')
        self.project.set_asset('Buildings/second','second.png',b'bbb','Second','Buildings')
        pt, en = self.project.sources(self.pid)
        self.project.update_source(self.pid,'pt-BR',pt+'\n![]({{asset:Buildings/first}})')
        self.project.update_source(self.pid,'en',en+'\n![]({{asset:Buildings/second}})')
        survivor = self.project.assets()['assets']['Buildings/second']['file']
        old = self.project.assets()['assets']['Buildings/first']['file']
        self.project.merge_assets(['Buildings/first','Buildings/second'],'Buildings/second')
        self.assertNotIn('Buildings/first',self.project.sources(self.pid)[0])
        self.assertIn('Buildings/second',self.project.sources(self.pid)[0])
        self.assertEqual(list(self.project.assets()['assets']),['Buildings/second'])
        self.assertTrue((self.project.current/survivor).is_file())
        self.assertFalse((self.project.current/old).exists())
        self.assertEqual(self.project.state()['assetSizes']['Buildings/second'],3)
        self.project.history_move(-1)
        self.assertEqual(len(self.project.assets()['assets']),2)


if __name__ == '__main__':
    unittest.main()
