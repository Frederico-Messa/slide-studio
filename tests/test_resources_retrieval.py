from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from studio.chats import ChatStore
from studio.images import image_dimensions
from studio.openrouter import OpenRouter
from studio.operations import OPERATIONS, apply, operation_instructions
from studio.project import Project, save_json
from studio.operations.retrieval import READ_TOOLS, read_resource, workspace_index
from studio.scripts import update_script


class MetadataAndOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Welcome')

    def test_descriptions_and_undo(self) -> None:
        self.project.update_presentation(self.pid, 'Welcome', 'Visitors and students')
        self.project.update_variant(self.pid, 'standard', {'name':'Standard','description':'Full deck','width':1280,'height':720,'hidden_slides':[]})
        self.project.set_slide_description(self.pid, 'opening', 'Institutional cover')
        self.assertEqual(self.project.presentations()[0]['description'], 'Visitors and students')
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['description'], 'Full deck')
        self.assertEqual(self.project.state(self.pid)['slideDescriptions']['opening'], 'Institutional cover')
        self.project.history_move(-1)
        self.assertEqual(self.project.slide_descriptions(self.pid)['opening'], '')

    def test_merge_operations_share_gui_implementation(self) -> None:
        self.project.set_fact('Students', 'total', '200', None, 'All enrolled students')
        self.project.set_fact('Students', 'previous', '100', None, 'Previous year')
        for language, source in zip(('pt-BR', 'en'), self.project.sources(self.pid)):
            self.project.update_source(self.pid, language, source + '\n{{fact:Students.previous}}')
        apply(self.project, 'fact_table', 'Students', {'edits':[{'op':'merge_facts','entries':[{'category':'Students','key':'total'},{'category':'Students','key':'previous'}],'survivor':{'category':'Students','key':'total'}}]})
        self.assertIn('{{fact:Students.total}}', self.project.sources(self.pid)[0])
        self.assertEqual(self.project.facts()['categories']['Students']['total']['description'], 'All enrolled students')
        self.project.history_move(-1)
        self.assertIn('previous', self.project.facts()['categories']['Students'])
        self.project.set_asset('first', 'a.png', b'a', 'A')
        self.project.set_asset('second', 'b.png', b'b', 'B')
        apply(self.project, 'assets', '', {'edits':[{'op':'merge_assets','aliases':['first','second'],'survivor':'first'}]})
        self.assertEqual(list(self.project.assets()['assets']), ['first'])
        self.project.history_move(-1)
        self.assertIn('second', self.project.assets()['assets'])

    def test_operation_catalog_matches_backend(self) -> None:
        self.assertIn('merge_facts', OPERATIONS)
        self.assertIn('merge_assets', OPERATIONS)
        self.assertIn('set_slide_description', operation_instructions('slide'))
        self.assertNotIn('merge_assets', operation_instructions('facts'))
        with self.assertRaises(ValueError):
            apply(self.project, 'fact_table', 'Students', {'edits':[{'op':'merge_assets','aliases':['a','b'],'survivor':'a'}]})

    def test_usage_details_and_image_properties(self) -> None:
        for language, source in zip(('pt-BR','en'), self.project.sources(self.pid)):
            self.project.update_source(self.pid, language, source + '\n![]({{asset:cover}})')
        png = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + struct.pack('>II', 128, 64) + b'\x08\x02\x00\x00\x00'
        self.project.set_asset('cover', 'cover.png', png, 'Test')
        dimensions = self.project.state()['assetDetails']['cover']
        self.assertEqual((dimensions['width'], dimensions['height']), (128,64))
        references = self.project.usages('assets', 'cover')
        self.assertEqual({item['language'] for item in references}, {'pt-BR','en'})
        self.assertTrue(all(item['slide'] == 'opening' for item in references))
        self.assertEqual(image_dimensions(Path(self.temp.name) / 'missing.png') if False else (128,64), (128,64))

    def test_readonly_retrieval(self) -> None:
        pt = self.project.sources(self.pid)[0]
        self.project.update_source(self.pid, 'pt-BR', pt + '\n<svg><path d="M123 4Z"/><text>Visible heading</text></svg>')
        self.project.set_slide_description(self.pid, 'opening', 'Cover')
        summary = workspace_index(self.project)
        slide = summary['presentations'][0]['slides'][0]
        self.assertEqual(slide['titles']['en'], 'Welcome')
        self.assertNotIn('Visible heading', str(summary))
        self.assertNotIn('M123 4Z', str(summary))
        exact = read_resource(self.project, 'read_slide_source', {'presentation':self.pid,'slide':'opening'})
        self.assertIn('M123 4Z', exact['sources']['pt-BR'])
        self.assertIn('en', exact['sources'])
        self.assertEqual(exact['description'], 'Cover')
        with self.assertRaises(ValueError):
            read_resource(self.project,'read_slide_source',{'presentation':'../other','slide':'opening'})
        with self.assertRaises(ValueError):
            read_resource(self.project,'read_presentation_source',{'presentation':self.pid,'path':'/etc/passwd'})

    def test_chat_retrieval_round_trip(self) -> None:
        pt = self.project.sources(self.pid)[0]
        self.project.update_source(self.pid,'pt-BR',pt+'\n<svg><path d="X11"/><text>Cover</text></svg>')
        config = Path(self.temp.name)/'config'
        router = OpenRouter(config)
        chat = ChatStore(config).create('Review')
        calls: list[dict] = []
        def fake_completion(request: dict, cancelled: Event) -> dict:
            calls.append(request)
            if len(calls) == 1:
                return {'choices':[{'message':{'content':'','tool_calls':[{'id':'call1','type':'function','function':{'name':'read_slide_source','arguments':json.dumps({'presentation':self.pid,'slide':'opening'})}}]}}], 'usage':{'prompt_tokens':2000,'completion_tokens':10}}
            return {'choices':[{'message':{'content':'The SVG contains X11.'}}], 'usage':{'prompt_tokens':3400,'completion_tokens':25}}
        with patch.object(router,'completion',side_effect=fake_completion):
            output = router.chat(self.project, ChatStore(config), chat, 'What is the exact SVG path?', Event(),model='vendor/test')
        self.assertIn('X11',output['answer'])
        self.assertEqual(output['usage']['prompt_tokens'],3400)
        self.assertIn('X11',calls[1]['messages'][-1]['content'])
        self.assertNotIn('X11',calls[0]['messages'][1]['content'])
        self.assertEqual(calls[1]['messages'][-1]['role'],'tool')



if __name__ == '__main__':
    unittest.main()
