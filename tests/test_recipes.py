from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.edit_session import EditSession
from studio.openrouter import EditCancelled, OpenRouter
from studio.operations import apply
from studio.operations.retrieval import read_resource, workspace_index
from studio.project import Project, tree_digest
from studio.recipes import get_recipe, list_recipes, remove_recipe, update_recipe


class RecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.first = self.project.create_presentation('First')
        self.second = self.project.create_presentation('Second')
        self.project.set_fact('Administration', 'dean', 'Alice', None, '')
        update_recipe(self.project, 'refresh-dean', {'name': 'Update dean', 'description': 'Use current facts'}, 'Read facts, update both presentations.')
        self.router = OpenRouter(Path(self.temp.name) / 'config')

    def test_recipe_lifecycle_and_retrieval(self) -> None:
        self.assertEqual(list_recipes(self.project)[0]['id'], 'refresh-dean')
        self.assertEqual(get_recipe(self.project, 'refresh-dean')['instructions'], 'Read facts, update both presentations.')
        self.assertEqual(read_resource(self.project, 'read_recipe', {'id': 'refresh-dean'})['name'], 'Update dean')
        self.assertEqual(workspace_index(self.project)['recipes'], [{'id': 'refresh-dean', 'name': 'Update dean', 'description': 'Use current facts'}])
        self.assertNotIn('Read facts, update both presentations.', json.dumps(workspace_index(self.project)))
        update_recipe(self.project, 'refresh-leadership', {'name': 'Update leadership', 'description': ''}, 'Use current data.', previous='refresh-dean')
        self.assertEqual([r['id'] for r in list_recipes(self.project)], ['refresh-leadership'])
        remove_recipe(self.project, 'refresh-leadership')
        self.assertEqual(list_recipes(self.project), [])
        self.assertTrue(self.project.history_move(-1))
        self.assertEqual(get_recipe(self.project, 'refresh-leadership')['instructions'], 'Use current data.')

    def test_ai_can_manage_recipes_under_scopes(self) -> None:
        apply(self.project, 'recipe', 'refresh-dean', {'edits': [{'op':'replace_recipe_text','id':'refresh-dean','find':'update','replace':'review'}]})
        self.assertIn('review both', get_recipe(self.project, 'refresh-dean')['instructions'])
        with self.assertRaises(ValueError):
            apply(self.project, 'recipe', 'refresh-dean', {'edits': [{'op':'create_recipe','id':'another','instructions':'Do this.', 'metadata':{'name':'Another', 'description':''}}]})
        apply(self.project, 'recipes', '', {'edits': [{'op':'create_recipe','id':'another','instructions':'Do this.', 'metadata':{'name':'Another', 'description':''}}]})
        self.assertEqual(get_recipe(self.project, 'another')['instructions'], 'Do this.')

    def test_cross_presentation_and_fact_edits_are_one_atomic_change(self) -> None:
        before = self.project.position
        changes = {'edits': [
            {'op':'set_fact','table':'Administration','key':'dean','value':'Bob'},
            {'op':'set_presentation_name','presentation':self.first,'name':'First revised'},
            {'op':'set_presentation_name','presentation':self.second,'name':'Second revised'},
            {'op':'set_recipe_metadata','id':'refresh-dean','metadata':{'name':'Review leadership','description':'Latest facts'}},
        ]}
        apply(self.project, 'recipe_run', '', changes)
        self.assertEqual(self.project.position, before + 1)
        self.assertEqual(self.project.facts()['categories']['Administration']['dean']['value'], 'Bob')
        self.assertEqual([p['name'] for p in self.project.presentations()], ['First revised','Second revised'])
        self.assertEqual(get_recipe(self.project, 'refresh-dean')['name'], 'Review leadership')
        self.project.history_move(-1)
        self.assertEqual([p['name'] for p in self.project.presentations()], ['First','Second'])
        self.assertEqual(self.project.facts()['categories']['Administration']['dean']['value'], 'Alice')
        self.project.history_move(1)
        self.assertEqual(self.project.facts()['categories']['Administration']['dean']['value'], 'Bob')

    def test_failed_recipe_batch_is_atomic(self) -> None:
        baseline = tree_digest(self.project.current)
        before = self.project.position
        with self.assertRaises(ValueError):
            apply(self.project, 'recipe_run', '', {'edits': [
                {'op':'set_fact','table':'Administration','key':'dean','value':'Carol'},
                {'op':'set_presentation_name','presentation':'does-not-exist','name':'No'},
            ]})
        self.assertEqual(tree_digest(self.project.current), baseline)
        self.assertEqual(self.project.position, before)
        with self.assertRaises(ValueError):
            apply(self.project, 'recipe_run', '', {'edits': [{'op':'set_presentation_name','name':'Missing ID'}]})

    def test_recipe_runner_uses_selection_and_current_recipe_instructions(self) -> None:
        payloads: list[dict] = []
        result = {'edits':[{'op':'set_fact','table':'Administration','key':'dean','value':'Diana'}]}
        def finish(payload: dict, _cancel: Event) -> dict:
            payloads.append(copy.deepcopy(payload))
            return {'choices':[{'message':{'content':json.dumps(result)}}]}
        with patch.object(self.router, 'completion', side_effect=finish):
            self.router.run_recipe(self.project, 'refresh-dean', {'presentation':self.second,'variant':'standard','language':'en','slide':'opening'}, 'model')
        message = json.loads(payloads[0]['messages'][2]['content'])
        self.assertEqual(message['instruction'], 'Read facts, update both presentations.')
        self.assertEqual(message['current_selection'], {'presentation':self.second,'variant':'standard','language':'en','slide':'opening'})
        self.assertNotIn('diff_since_save', message)
        self.assertNotIn('diff_from_previous_state', message)
        self.assertNotIn('Alice', payloads[0]['messages'][1]['content'])
        self.assertIn('set_fact', payloads[0]['messages'][0]['content'])
        self.assertIn('read_recipe', [tool['function']['name'] for tool in payloads[0]['tools']])
        self.assertEqual(self.project.facts()['categories']['Administration']['dean']['value'], 'Diana')

    def test_recipe_can_finish_without_changes(self) -> None:
        baseline = tree_digest(self.project.current)
        position = self.project.position
        with patch.object(self.router, 'completion', return_value={'choices':[{'message':{'content':'{"edits":[]}'}}]}):
            result = self.router.run_recipe(self.project, 'refresh-dean', None, 'model')
        self.assertEqual(result['note'], 'No changes needed')
        self.assertEqual(tree_digest(self.project.current), baseline)
        self.assertEqual(self.project.position, position)

    def test_recipe_provisional_and_cancellation(self) -> None:
        baseline = tree_digest(self.project.current)
        with EditSession(self.project, 'recipe_run', baseline) as session:
            answer = session.apply_provisional({'edits':[{'op':'set_fact','table':'Administration','key':'dean','value':'Eve'}]}, Event())
            self.assertEqual(answer['revision'], 1)
            self.assertEqual(read_resource(session.current(), 'read_facts_metadata', {'prefix':'Administration.dean'})['facts']['Administration']['dean']['value'], 'Eve')
            self.assertEqual(self.project.facts()['categories']['Administration']['dean']['value'], 'Alice')
            with self.assertRaises(EditCancelled):
                cancelled = Event()
                cancelled.set()
                session.finish({'edits': []}, cancelled)
        self.assertEqual(tree_digest(self.project.current), baseline)

    def test_invalid_recipe_instructions_and_ai_selection(self) -> None:
        with self.assertRaises(ValueError):
            update_recipe(self.project, 'empty', {'name':'Empty','description':''}, '   ')
        with self.assertRaises(ValueError):
            apply(self.project, 'recipes', '', {'edits':[{'op':'replace_recipe_instructions','id':'refresh-dean','instructions':'\x00'}]})
        requests: list[dict] = []
        def finish(payload: dict, _cancel: Event) -> dict:
            requests.append(copy.deepcopy(payload))
            return {'choices':[{'message':{'content':'{"edits":[{"op":"set_fact","table":"Administration","key":"dean","value":"Grace"}]}'}}]}
        with patch.object(self.router, 'completion', side_effect=finish):
            self.router.change_resource(self.project, 'facts', '', 'Update', model='model', selection={'presentation':self.first,'variant':'standard','language':'pt-BR','slide':'opening'})
        self.assertEqual(json.loads(requests[0]['messages'][2]['content'])['current_selection']['presentation'], self.first)


if __name__ == '__main__':
    unittest.main()
