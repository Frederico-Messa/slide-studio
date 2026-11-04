from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.chats import ChatStore
from studio.openrouter import EditCancelled, OpenRouter
from studio.operations.retrieval import READ_TOOLS, read_resource, workspace_index
from studio.project import Project


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Example')
        self.router = OpenRouter(Path(self.temp.name) / 'config')
        self.chats = ChatStore(Path(self.temp.name) / 'config')

    @staticmethod
    def completion_with_tool(name: str, args: dict[str, str]) -> dict:
        return {'choices':[{'message':{'content':'', 'tool_calls':[{'id':'call1','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]}

    def test_read_tools_are_bilingual_and_restricted(self) -> None:
        definitions = {entry['function']['name']:entry['function']['parameters'] for entry in READ_TOOLS}
        self.assertEqual(len(definitions), 13)
        self.assertEqual(set(definitions['read_slide_source']['required']), {'presentation','slide'})
        self.assertEqual(set(definitions['read_presentation_source']['required']), {'presentation'})
        self.assertNotIn('language', definitions['read_slide_images']['properties'])
        self.assertNotIn('language', definitions['read_stylesheet']['properties'])
        self.assertIn('prefix', definitions['read_facts_metadata']['properties'])
        self.assertIn('prefix', definitions['read_assets_metadata']['properties'])
        self.assertTrue(all(entry['function']['parameters']['additionalProperties'] is False for entry in READ_TOOLS))

    def test_metadata_prefix_semantics(self) -> None:
        self.project.set_fact('Students', 'total', '300', None, 'All enrolled')
        self.project.set_fact('Students', 'graduates', '100', None, 'Graduates')
        self.project.set_fact('Faculty', 'total', '70', None, 'Professors')
        self.project.set_asset('Faculty/ana','ana.png',b'png-ana', 'Portrait',category='Faculty')
        self.project.set_asset('Faculty/Staff/bruno','bruno.png',b'png-bruno','Portrait',category='Faculty/Staff')
        self.project.set_asset('campus','campus.png',b'png-campus','Building')
        full_facts = read_resource(self.project,'read_facts_metadata',{})['facts']
        self.assertEqual(set(full_facts), {'Students','Faculty'})
        self.assertEqual(set(read_resource(self.project,'read_facts_metadata',{'prefix':'Students'})['facts']['Students']),{'total','graduates'})
        self.assertEqual(set(read_resource(self.project,'read_facts_metadata',{'prefix':'Students.total'})['facts']['Students']),{'total'})
        full_assets = read_resource(self.project,'read_assets_metadata',{})['assets']
        self.assertIn('campus',full_assets)
        self.assertEqual(set(read_resource(self.project,'read_assets_metadata',{'prefix':'Faculty'})['assets']),{'Faculty/ana','Faculty/Staff/bruno'})
        self.assertEqual(set(read_resource(self.project,'read_assets_metadata',{'prefix':'Faculty/Staff/bruno'})['assets']),{'Faculty/Staff/bruno'})
        self.assertEqual(full_assets['campus']['bytes'],10)
        with self.assertRaises(ValueError):
            read_resource(self.project,'read_facts_metadata',{'prefix':'Students.unknown'})
        with self.assertRaises(ValueError):
            read_resource(self.project,'read_assets_metadata',{'prefix':'/etc/passwd'})

    def test_overview_only_contains_navigation_index(self) -> None:
        self.project.set_fact('Statistics','students','42',None,'Students in program')
        self.project.set_asset('campus','campus.png',b'png-campus','x'*350)
        pt = self.project.sources(self.pid)[0]
        self.project.update_source(self.pid, 'pt-BR', pt + '\n<svg><text>' + 'A'*5100 + '</text><path d="M100Z"/></svg>')
        overview = workspace_index(self.project)
        self.assertEqual(overview['presentations'][0]['slides'][0]['titles']['en'], 'Example')
        self.assertEqual(overview['presentations'][0]['variants'][0]['id'], 'standard')
        self.assertNotIn('A'*5100, str(overview))
        self.assertNotIn('x'*350, str(overview))
        self.assertNotIn('Statistics', str(overview))
        self.assertNotIn('assets', overview)
        self.assertNotIn('facts', overview)

    def test_bilingual_source_retrieved_through_chat(self) -> None:
        self.project.update_source(self.pid,'pt-BR',self.project.sources(self.pid)[0]+'\nPortuguese marker')
        chat = self.chats.create('Review')
        calls = []
        def complete(payload: dict, cancelled: Event) -> dict:
            import copy
            calls.append(copy.deepcopy(payload))
            if len(calls) == 1:
                return self.completion_with_tool('read_slide_source',{'presentation':self.pid,'slide':'opening'})
            return {'choices':[{'message':{'content':'Checked both languages'}}]}
        with patch.object(self.router,'completion',side_effect=complete):
            result = self.router.chat(self.project,self.chats,chat,'Read this slide',Event(),model='test/model')
        self.assertEqual(result['answer'],'Checked both languages')
        data = json.loads(calls[1]['messages'][-1]['content'])
        self.assertIn('Portuguese marker',data['sources']['pt-BR'])
        self.assertIn('en',data['sources'])
        self.assertNotIn('xmlns=',calls[0]['messages'][1]['content'])

    def test_slide_images_are_requested_not_sent_upfront(self) -> None:
        chat = self.chats.create('Images')
        calls = []
        renders = []
        def render(*args):
            renders.append(args)
            return [('pt-BR','opening',b'pt-image'),('en','opening',b'en-image')]
        renderer = type('Renderer',(),{'slide_images':staticmethod(render)})()
        def complete(payload: dict, cancelled: Event) -> dict:
            import copy
            calls.append(copy.deepcopy(payload))
            if len(calls)==1:
                return self.completion_with_tool('read_slide_images',{'presentation':self.pid,'slide':'opening'})
            return {'choices':[{'message':{'content':'The pictures are visible.'}}]}
        with patch.object(self.router,'completion',side_effect=complete),patch.object(self.router,'model_accepts_images',return_value=True):
            result = self.router.chat(self.project,self.chats,chat,'Inspect the cover',Event(),renderer,'http://127.0.0.1:1234',model='test/vision')
        self.assertEqual(result['images'],2)
        self.assertEqual(renders[0][2:4],('slide','opening'))
        self.assertEqual(calls[0]['messages'][-1]['content'],'Inspect the cover')
        parts = calls[1]['messages'][-1]['content']
        self.assertEqual(len([part for part in parts if part['type']=='image_url']),2)
        self.assertEqual([entry['role'] for entry in calls[1]['messages'][-3:]],['assistant','tool','user'])

    def test_retrieval_does_not_expand_edit_scope(self) -> None:
        self.project.apply_structured_edits(self.pid,'presentation','',{'edits':[{'op':'insert_slide','slide_id':'second','position':'end','sources':{'pt-BR':'## Second {#second}','en':'## Second {#second}'}}]})
        initial = self.project.sources(self.pid)
        calls = []
        def complete(payload: dict, cancelled: Event) -> dict:
            import copy
            calls.append(copy.deepcopy(payload))
            if len(calls)==1:
                return self.completion_with_tool('read_presentation_source',{'presentation':self.pid})
            return {'choices':[{'message':{'content':json.dumps({'edits':[{'op':'delete_slide','slide_id':'second'}]})}}]}
        with patch.object(self.router,'completion',side_effect=complete):
            with self.assertRaises(ValueError):
                self.router.change(self.project,self.pid,'slide','opening','Remove second','standard',model='test/model')
        self.assertEqual(self.project.sources(self.pid),initial)
        self.assertIn('sources',json.loads(calls[1]['messages'][-1]['content']))

    def test_cancel_after_retrieval_prevents_application(self) -> None:
        cancel = Event()
        initial = self.project.sources(self.pid)
        def complete(payload: dict, cancelled: Event) -> dict:
            cancel.set()
            return self.completion_with_tool('read_slide_source',{'presentation':self.pid,'slide':'opening'})
        with patch.object(self.router,'completion',side_effect=complete):
            with self.assertRaises(EditCancelled):
                self.router.change(self.project,self.pid,'slide','opening','Change','standard',cancelled=cancel,model='test/model')
        self.assertEqual(self.project.sources(self.pid),initial)


if __name__=='__main__':
    unittest.main()
