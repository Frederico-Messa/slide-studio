from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.openrouter import OpenRouter
from studio.preferences import Preferences
from studio.project import Project
from studio.resource_edits import apply_resource_edits
from studio.scripts import ScriptJobs, get_script, update_script


class ScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.metadata = {'name':'Update faculty', 'description':'Example', 'parameters':[{'name':'count','label':'Count','type':'number','default':5,'required':False}]}
        update_script(self.project, 'update-faculty', self.metadata, 'import os\nfrom pathlib import Path\nroot = Path(os.environ["SLIDE_STUDIO_WORKSPACE"])\n(root / "result.txt").write_text("done")\n')

    def test_create_edit_undo_and_save(self) -> None:
        self.assertEqual(self.project.state()['scripts'][0]['name'], 'Update faculty')
        original = get_script(self.project, 'update-faculty')
        self.assertIn('result.txt', original['source'])
        update_script(self.project, 'renamed', {**self.metadata,'name':'Other'}, original['source'].replace('done','modified'), 'update-faculty')
        self.assertEqual(self.project.state()['scripts'][0]['id'], 'renamed')
        self.project.history_move(-1)
        self.assertEqual(self.project.state()['scripts'][0]['id'], 'update-faculty')
        self.project.history_move(1)
        self.assertEqual(self.project.state()['scripts'][0]['id'], 'renamed')
        self.project.save()
        self.assertTrue((self.project.workspace / 'scripts' / 'renamed' / 'main.py').is_file())

    def test_script_execution_is_one_undoable_operation(self) -> None:
        jobs = ScriptJobs(self.project)
        job = jobs.start('update-faculty', {'count':7})
        for _ in range(200):
            result = jobs.status(job)
            if result['status'] != 'running':
                break
            time.sleep(0.03)
        self.assertEqual(result['status'], 'complete',result)
        self.assertEqual((self.project.current / 'result.txt').read_text(), 'done')
        self.assertIn('result.txt', result['changed'])
        self.assertFalse((self.project.workspace / 'result.txt').exists())
        self.project.history_move(-1)
        self.assertFalse((self.project.current / 'result.txt').exists())
        self.project.history_move(1)
        self.project.save()
        self.assertEqual((self.project.workspace / 'result.txt').read_text(), 'done')

    def test_failed_script_does_not_change_workspace(self) -> None:
        source = 'import os\nfrom pathlib import Path\nPath(os.environ["SLIDE_STUDIO_WORKSPACE"]).joinpath("result.txt").write_text("temporary")\nraise RuntimeError("failure")\n'
        update_script(self.project, 'update-faculty', self.metadata, source, 'update-faculty')
        jobs = ScriptJobs(self.project)
        job = jobs.start('update-faculty', {})
        for _ in range(200):
            result = jobs.status(job)
            if result['status'] != 'running':
                break
            time.sleep(0.03)
        self.assertEqual(result['status'], 'failed',result)
        self.assertIn('RuntimeError',result['output'])
        self.assertFalse((self.project.current / 'result.txt').exists())

    def test_stop_script(self) -> None:
        update_script(self.project, 'update-faculty', self.metadata, 'import time\ntime.sleep(20)\n', 'update-faculty')
        jobs = ScriptJobs(self.project)
        job = jobs.start('update-faculty', {})
        jobs.stop(job)
        for _ in range(200):
            result = jobs.status(job)
            if result['status'] != 'running':
                break
            time.sleep(0.03)
        self.assertEqual(result['status'], 'cancelled',result)

    def test_script_edits_are_scoped_and_atomic(self) -> None:
        script = get_script(self.project, 'update-faculty')
        apply_resource_edits(self.project,'script','update-faculty',{'edits':[{'op':'replace_script_text','id':'update-faculty','find':'done','replace':'changed'}]})
        self.assertIn('changed', get_script(self.project,'update-faculty')['source'])
        with self.assertRaisesRegex(ValueError,'outside the current script'):
            apply_resource_edits(self.project,'script','update-faculty',{'edits':[{'op':'create_script','id':'other','metadata':self.metadata,'source':'pass'}]})
        self.assertEqual(len(self.project.state()['scripts']),1)
        with self.assertRaises(ValueError):
            apply_resource_edits(self.project,'script','update-faculty',{'edits':[{'op':'replace_script_text','id':'update-faculty','find':'changed','replace':'oops'}, {'op':'replace_script_text','id':'update-faculty','find':'not here','replace':'no'}]})
        self.assertIn('changed', get_script(self.project,'update-faculty')['source'])

    def test_fact_context_and_reference_rewrite(self) -> None:
        pid = self.project.create_presentation('Overview')
        self.project.set_fact('Students','number','120',None,'example')
        self.project.set_fact('Faculty','number','50',None,'')
        for language in ('pt-BR','en'):
            text = self.project.sources(pid)[0 if language == 'pt-BR' else 1]
            self.project.update_source(pid,language,text+'\n{{fact:Students.number}}\n')
        router = OpenRouter(Path(self.temp.name)/'config')
        context,_ = router.resource_context(self.project,'fact_table','Students')
        self.assertEqual(context['scope'], 'fact_table')
        self.assertEqual(context['target'], 'Students')
        self.assertNotIn('Faculty', context)
        self.assertNotIn('workspace',context)
        from studio.operations.retrieval import workspace_index, read_resource
        self.assertNotIn('facts', workspace_index(self.project))
        self.assertIn('Faculty', read_resource(self.project,'list_all_facts',{})['tables'])
        apply_resource_edits(self.project,'fact_table','Students',{'edits':[{'op':'rename_fact','table':'Students','key':'number','new_key':'total'}]})
        self.assertTrue(all('{{fact:Students.total}}' in text for text in self.project.sources(pid)))
        with self.assertRaisesRegex(ValueError,'outside the current table'):
            apply_resource_edits(self.project,'fact_table','Students',{'edits':[{'op':'set_fact','table':'Faculty','key':'number','value':'7'}]})

    def test_asset_metadata_not_attached_as_image(self) -> None:
        self.project.set_asset('Faculty/jane','jane.png',b'image1','',category='Faculty')
        self.project.set_asset('Campus/main','main.png',b'image2','',category='Campus')
        router = OpenRouter(Path(self.temp.name)/'config')
        changes = {'edits':[{'op':'set_asset_metadata','alias':'Faculty/jane','description':'Updated'}]}
        response = {'choices':[{'message':{'content':json.dumps(changes)}}]}
        with patch.object(router,'completion',return_value=response) as completion:
            result = router.change_resource(self.project,'asset_folder','Faculty','Describe portrait',model='vendor/image')
        self.assertEqual(result['images'],0)
        messages = completion.call_args.args[0]['messages']
        self.assertTrue(all(isinstance(message['content'],str) for message in messages))
        context = json.loads(messages[1]['content'].split('\n',1)[1])
        self.assertNotIn('assets', context)
        self.assertNotIn('Campus/main',str(context))
        self.assertEqual(self.project.assets()['assets']['Faculty/jane']['description'],'Updated')

    def test_resource_ai_uses_structured_operations(self) -> None:
        router = OpenRouter(Path(self.temp.name)/'config')
        payload = {'edits':[{'op':'replace_script_text','id':'update-faculty','find':'done','replace':'new'}]}
        with patch.object(router,'completion',return_value={'choices':[{'message':{'content':json.dumps(payload)}}]}) as completion:
            router.change_resource(self.project,'script','update-faculty','Edit output',model='vendor/test')
        self.assertIn('new',get_script(self.project,'update-faculty')['source'])
        messages = completion.call_args.args[0]['messages']
        self.assertIn('scripts',json.loads(messages[1]['content'].split('\n',1)[1]))


if __name__ == '__main__':
    unittest.main()
