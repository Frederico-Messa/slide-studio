from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.chats import ChatStore
from studio.openrouter import OpenRouter
from studio.operations.catalog import PROVISIONAL_EDIT_TOOL
from studio.project import Project
from studio.recipes import update_recipe


class AIHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = Project(root / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.router = OpenRouter(root / 'config')
        self.presentation = self.project.create_presentation('Example')
        self.chats = ChatStore(root / 'config')

    def assert_efficient_prompt(self, request: dict) -> None:
        system = request['messages'][0]['content']
        self.assertIn('Use tools efficiently; avoid redundant retrievals.', system)
        self.assertNotIn('1000 tool calls', system)
        self.assertNotIn('160 retrieval calls', system)
        self.assertNotIn('48 model rounds', system)

    def test_edit_resource_recipe_and_chat_prompts(self) -> None:
        edits = lambda changes: {'choices': [{'message': {'content': json.dumps({'edits': changes})}}]}
        with patch.object(self.router, 'completion', return_value=edits([{'op':'set_presentation_name','name':'New'}])) as completion:
            self.router.change(self.project, self.presentation, 'presentation', '', 'Rename', 'standard', model='vendor/test')
        self.assert_efficient_prompt(completion.call_args.args[0])
        with patch.object(self.router, 'completion', return_value=edits([{'op':'create_table','table':'NewTable'}])) as completion:
            self.router.change_resource(self.project, 'facts', '', 'Create table', model='vendor/test')
        self.assert_efficient_prompt(completion.call_args.args[0])
        update_recipe(self.project, 'review', {'name':'Review', 'description':''}, 'Review existing information')
        with patch.object(self.router, 'completion', return_value=edits([])) as completion:
            self.router.run_recipe(self.project, 'review', None, 'vendor/test')
        self.assert_efficient_prompt(completion.call_args.args[0])
        response = {'choices':[{'message':{'content':'Answer.'}}]}
        with patch.object(self.router, 'completion', return_value=response) as completion:
            self.router.chat(self.project, self.chats, {'messages':[]}, 'Describe the workspace', Event(), model='vendor/test')
        self.assert_efficient_prompt(completion.call_args.args[0])

    def test_tool_schema_does_not_advertise_edit_size_limit(self) -> None:
        schema = PROVISIONAL_EDIT_TOOL['function']['parameters']['properties']['edits']
        self.assertNotIn('maxItems', schema)
        self.assertEqual(schema['minItems'], 1)


if __name__ == '__main__':
    unittest.main()
