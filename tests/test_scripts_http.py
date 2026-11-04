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


class ScriptHTTPTests(StudioHTTPTestCase):
    def test_script_routes_and_execution(self) -> None:
        metadata = {'name':'Sample', 'description':'', 'parameters':[]}
        source = 'import os\nfrom pathlib import Path\nPath(os.environ["SLIDE_STUDIO_WORKSPACE"]).joinpath("output.txt").write_text("test")\n'
        self.assertEqual(self.request('/api/state')['scripts'], [])
        self.request('/api/scripts', 'POST', {'id':'sample','metadata':metadata,'source':source})
        self.assertEqual(self.request('/api/state')['scripts'][0]['id'],'sample')
        self.assertEqual(self.request('/api/script?id=sample')['source'],source)
        job = self.request('/api/scripts/run','POST',{'id':'sample','parameters':{}})['job']
        for _ in range(100):
            status = self.request('/api/scripts/status?job=' + job)
            if status['status'] != 'running':
                break
            time.sleep(0.03)
        self.assertEqual(status['status'],'complete',status)
        self.assertIn('output.txt',status['changed'])
        self.assertTrue(self.request('/api/state')['dirty'])
        self.request('/api/history','POST',{'direction':-1})
        self.assertFalse((self.server.project.current / 'output.txt').exists())
        self.request('/api/history','POST',{'direction':1})
        self.request('/api/save','POST',{})
        self.assertTrue((self.server.project.workspace / 'output.txt').is_file())
        self.assertTrue(self.request('/api/diff') == [])
        self.request('/api/scripts','DELETE',{'id':'sample'})
        self.assertEqual(self.request('/api/state')['scripts'], [])

    def test_ai_script_edit_is_scoped_with_retrieval(self) -> None:
        metadata = {'name':'Sample','description':'', 'parameters':[]}
        self.request('/api/scripts','POST',{'id':'sample','metadata':metadata,'source':'print("before")'})
        self.server.openrouter.key = 'test'
        payload = {'edits':[{'op':'replace_script_text','id':'sample','find':'before','replace':'after'}]}
        with patch.object(self.server.openrouter,'completion',return_value={'choices':[{'message':{'content':json.dumps(payload)}}]}) as completion:
            started = self.request('/api/ai','POST',{'scope':'script','target':'sample','instruction':'Change message','model':'vendor/any','effort':'default',})
            for _ in range(100):
                result = self.request('/api/ai/status?job=' + started['job'])
                if result['status'] != 'running':
                    break
                time.sleep(0.03)
        self.assertEqual(result['status'],'complete',result)
        self.assertIn('after', self.request('/api/script?id=sample')['source'])
        sent = json.loads(completion.call_args.args[0]['messages'][1]['content'].split('\n', 1)[1])
        self.assertIn('scripts', sent)
        self.assertNotIn('sources', sent['presentations'][0] if sent['presentations'] else {})


if __name__ == '__main__':
    unittest.main()
