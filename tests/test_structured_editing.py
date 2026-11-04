from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.openrouter import OpenRouter
from studio.preferences import Preferences
from studio.project import Project


class StructuredEditingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name) / 'workspace'
        self.project = Project(self.workspace)
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Institute Presentation')
        self.project.save()

    def apply(self, edits: list[dict], scope: str = 'presentation', slide: str = '') -> None:
        self.project.apply_structured_edits(self.pid, scope, slide, {'edits': edits})

    def test_compact_multislide_bilingual_replacement(self) -> None:
        edits = [{'op':'replace_slide','slide_id':'opening','sources':{'pt-BR':'## Opening {#opening}\n\nFooter old','en':'## Opening {#opening}\n\nFooter old'}}]
        edits.extend({'op':'insert_slide','slide_id':f's{i:03}','position':'end','sources':{'pt-BR':f'## Slide {i} {{#s{i:03}}}\n\nFooter old','en':f'## Slide {i} {{#s{i:03}}}\n\nFooter old'}} for i in range(2,16))
        self.apply(edits)
        before = self.project.sources(self.pid)
        changes = [{'op':'replace_text', 'target':'slide', 'slide_ids':[f's{i:03}' for i in range(2,16)], 'languages':['pt-BR','en'], 'find':'Footer old', 'replace':'Footer new'}]
        self.apply(changes)
        for original, updated in zip(before, self.project.sources(self.pid)):
            self.assertEqual(updated.count('Footer new'), 14)
            self.assertEqual(updated.count('Footer old'), 1)
            self.assertEqual(len(updated), len(original))
        self.project.history_move(-1)
        self.assertEqual(self.project.sources(self.pid), before)

    def test_atomic_failure_and_ambiguous_match(self) -> None:
        before = self.project.sources(self.pid)
        edits = [
            {'op':'set_presentation_name', 'name':'New name'},
            {'op':'replace_text', 'target':'slide', 'slide_ids':['opening'], 'find':'does not exist', 'replace':'something'},
        ]
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.apply(edits)
        self.assertEqual(self.project.sources(self.pid), before)
        self.assertEqual(self.project.presentations()[0]['name'], 'Institute Presentation')
        content = before[0].replace('Institute Presentation', 'Institute Presentation Institute Presentation')
        self.project.update_source(self.pid, 'pt-BR', content)
        with self.assertRaisesRegex(ValueError, 'appears 2 times'):
            self.apply([{'op':'replace_text', 'target':'slide', 'slide_ids':['opening'], 'languages':['pt-BR'], 'find':'Institute Presentation', 'replace':'Other'}])
        self.assertEqual(self.project.sources(self.pid)[0], content)

    def test_scope_and_unsafe_edits(self) -> None:
        with self.assertRaisesRegex(ValueError, 'entire-presentation scope'):
            self.apply([{'op':'set_presentation_name', 'name':'Other'}], 'slide', 'opening')
        with self.assertRaisesRegex(ValueError, 'selected slide'):
            self.apply([{'op':'replace_text', 'target':'slide', 'slide_ids':['nonexistent'], 'find':'foo', 'replace':'bar'}], 'slide', 'opening')
        with self.assertRaisesRegex(ValueError, 'Executable'):
            self.apply([{'op':'replace_text', 'target':'slide', 'slide_ids':['opening'], 'languages':['en'], 'find':'{#opening}', 'replace':'{#opening}\n<script>bad()</script>'}])
        with self.assertRaisesRegex(ValueError, 'extensions or includes'):
            self.apply([{'op':'replace_text','target':'preamble','languages':['en'],'find':'  revealjs:\n','replace':'  revealjs:\n    include-in-header: secret.html\n'}])
        self.assertFalse(self.project.state()['dirty'])

    def test_slide_insert_delete_renumber_and_variants(self) -> None:
        self.apply([{'op':'insert_slide','slide_id':'research','anchor':'opening','position':'after','sources':{'pt-BR':'## Pesquisa {#research}\n\nConteúdo','en':'## Research {#research}\n\nContent'}}])
        self.assertEqual(self.project.state(self.pid)['slides'], ['opening','research'])
        self.project.update_variant(self.pid, 'standard', {'name':'Standard','description':'', 'width':1280,'height':720,'hidden_slides':['research']})
        self.apply([{'op':'delete_slide','slide_id':'research'}])
        self.assertEqual(self.project.state(self.pid)['slides'], ['opening'])
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], [])
        self.project.history_move(-1)
        self.assertEqual(self.project.state(self.pid)['slides'], ['opening','research'])

    def test_metadata_stylesheet_variants(self) -> None:
        self.apply([
            {'op':'set_presentation_name','name':'Welcome'},
            {'op':'replace_text','target':'css','find':'#171717','replace':'#252525','all':True},
            {'op':'set_variant','id':'standard','value':{'name':'Widescreen','description':'', 'width':1920,'height':1080,'hidden_slides':[]}},
        ])
        self.assertEqual(self.project.presentations()[0]['name'], 'Welcome')
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['width'], 1920)
        folder = self.project.presentation_path(self.pid)
        self.assertTrue((folder/'studio.css').is_file())
        self.assertIn('css: studio.css',self.project.sources(self.pid)[0])
        self.assertIn('#252525',(folder/'studio.css').read_text())
        self.assertIn('#171717',(self.project.presentation_path(self.pid)/'theme.css').read_text())

    def test_multiple_inline_fact_keys_in_one_transaction(self) -> None:
        self.project.set_fact('Students','current','10','2026-10-30','')
        self.project.set_fact('Students','previous','9',None,'')
        for language in ('pt-BR','en'):
            source = self.project.sources(self.pid)[0 if language == 'pt-BR' else 1]
            self.project.update_source(self.pid,language,source+'\n{{fact:Students.current}} {{fact:Students.previous}}\n')
        self.project.set_facts_batch('Students',[
            {'key':'current','newKey':'previous','value':'11','updated':'','description':'a'},
            {'key':'previous','newKey':'current','value':'8','updated':'','description':'b'},
        ])
        values=self.project.facts()['categories']['Students']
        self.assertEqual(values['current']['value'],'8')
        self.assertEqual(values['previous']['value'],'11')
        for source in self.project.sources(self.pid):
            self.assertIn('{{fact:Students.previous}} {{fact:Students.current}}',source)
        with self.assertRaisesRegex(ValueError,'Duplicate fact identifier'):
            self.project.set_facts_batch('Students',[{'key':'previous','newKey':'current','value':'2','updated':'','description':''}])
        self.assertEqual(self.project.facts()['categories']['Students'],values)

    def test_openrouter_uses_edit_operations(self) -> None:
        router = OpenRouter(Path(self.directory.name)/'config')
        router.update('test-key')
        payload = {'edits':[{'op':'replace_text','target':'slide','slide_ids':['opening'],'find':'Institute Presentation','replace':'Welcome'}]}
        with patch.object(router,'completion',return_value={'choices':[{'message':{'content':json.dumps(payload)}}]}) as completion:
            router.change(self.project,self.pid,'slide','opening','Rename this slide','standard',model='example/text')
        self.assertIn('Available operations:',completion.call_args.args[0]['messages'][0]['content'])
        self.assertIn('Welcome',self.project.sources(self.pid)[0])
        with patch.object(router,'completion',return_value={'choices':[{'message':{'content':'{"pt-BR":"...","en":"..."}'}}]}):
            with self.assertRaisesRegex(ValueError,'edit operations'):
                router.change(self.project,self.pid,'slide','opening','Bad protocol','standard',model='example/text')


class ThemePreferencesTests(unittest.TestCase):
    def test_theme_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            preferences=Preferences(Path(directory))
            preferences.update({'theme':'dark'})
            self.assertEqual(Preferences(Path(directory)).read()['theme'],'dark')
            with self.assertRaisesRegex(ValueError,'appearance'):
                preferences.update({'theme':'auto'})
        root = Path(__file__).resolve().parent.parent
        css=(root/'static'/'style.css').read_text()
        self.assertIsNone(re.search(r'#[0-9a-fA-F]{3,8}\b',css))
        palette=(root/'static'/'theme.css').read_text()
        self.assertIn(':root[data-theme="dark"]',palette)
        self.assertIn('--surface:',palette)


if __name__ == '__main__':
    unittest.main()
