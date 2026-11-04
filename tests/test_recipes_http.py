from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from http_support import StudioHTTPTestCase


class RecipeHTTPTests(StudioHTTPTestCase):
    def test_recipe_endpoints_run_and_undo(self) -> None:
        pid = self.server.project.create_presentation('First')
        self.server.project.set_fact('People', 'dean', 'Alice', None, '')
        self.assertEqual(self.request('/api/state')['recipes'], [])
        with urllib.request.urlopen(self.base + '/static/recipes.js', timeout=5) as response:
            self.assertIn(b'openRunRecipe', response.read())
        self.request('/api/recipes', 'POST', {'id':'dean-update', 'metadata':{'name':'Dean update','description':'Use current facts'}, 'instructions':'Check facts and revise presentation text.'})
        self.assertEqual(self.request('/api/recipe?id=dean-update')['instructions'], 'Check facts and revise presentation text.')
        self.assertEqual(self.request('/api/state')['recipes'][0]['id'], 'dean-update')
        self.server.openrouter.key = 'fake'
        result = {'edits':[{'op':'set_fact','table':'People','key':'dean','value':'Bob'}, {'op':'set_presentation_name','presentation':pid,'name':'Revised'}]}
        with patch.object(self.server.openrouter, 'completion', return_value={'choices':[{'message':{'content':json.dumps(result)}}]}) as completion:
            job = self.request('/api/recipes/run', 'POST', {'id':'dean-update','model':'vendor/model','effort':'medium','selection':{'presentation':pid,'variant':'standard','language':'en','slide':'opening'}})['job']
            for _ in range(200):
                status = self.request('/api/ai/status?job=' + job)
                if status['status'] not in ('running', 'stopping'):
                    break
                time.sleep(0.03)
        self.assertEqual(status['status'], 'complete', status)
        self.assertEqual(self.server.project.presentations()[0]['name'], 'Revised')
        self.assertEqual(self.server.project.facts()['categories']['People']['dean']['value'], 'Bob')
        request = completion.call_args.args[0]
        dynamic = json.loads(request['messages'][2]['content'])
        self.assertEqual(dynamic['current_selection']['language'], 'en')
        self.assertEqual(request['reasoning']['effort'], 'medium')
        self.request('/api/history', 'POST', {'direction':-1})
        self.assertEqual(self.server.project.presentations()[0]['name'], 'First')
        self.assertEqual(self.server.project.facts()['categories']['People']['dean']['value'], 'Alice')
        self.request('/api/recipes', 'DELETE', {'id':'dean-update'})
        self.assertEqual(self.request('/api/state')['recipes'], [])


if __name__ == '__main__':
    unittest.main()
