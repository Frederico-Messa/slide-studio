from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from studio.project import Project, save_json
from studio.preferences import Preferences
from studio.render import Renderer


class VariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Overview', 960, 720)
        self.project.apply_structured_edits(self.pid, 'presentation', '', {'edits': [
            {'op':'replace_slide', 'slide_id':'opening', 'sources':{'pt-BR':'## Entrada {#opening}\n\nSlide A', 'en':'## Entrance {#opening}\n\nSlide A'}},
            {'op':'insert_slide', 'slide_id':'second', 'anchor':'opening', 'position':'after', 'sources':{'pt-BR':'## Extra {#second}\n\nSlide B', 'en':'## Extra {#second}\n\nSlide B'}},
            {'op':'replace_text', 'target':'slide', 'slide_ids':['opening'], 'languages':['pt-BR','en'], 'find':'{#opening}', 'replace':'{#first}'},
        ]})

    def test_variants_and_history(self) -> None:
        self.project.update_variant(self.pid, 'full', {'name': 'Full', 'width': 1280, 'height': 720, 'hidden_slides': []}, 'standard')
        self.project.update_variant(self.pid, 'standard', {'name': 'Standard', 'width': 960, 'height': 720, 'hidden_slides': ['second']})
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], ['second'])
        self.assertEqual(self.project.variants(self.pid)['variants']['full']['width'], 1280)
        self.project.make_default_variant(self.pid, 'full')
        self.assertEqual(self.project.variants(self.pid)['default'], 'full')
        self.project.remove_variant(self.pid, 'full')
        self.assertEqual(self.project.variants(self.pid)['default'], 'standard')
        self.project.history_move(-1)
        self.assertIn('full', self.project.variants(self.pid)['variants'])
        self.project.save()
        self.assertTrue((self.project.workspace / 'presentations' / self.pid / 'variants.json').is_file())

    def test_disallow_all_hidden(self) -> None:
        with self.assertRaisesRegex(ValueError, 'At least one slide'):
            self.project.update_variant(self.pid, 'standard', {'name': 'Standard', 'width': 960, 'height': 720, 'hidden_slides': ['first', 'second']})
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], [])

    def test_ai_updates_selected_variant(self) -> None:
        current = self.project.variants(self.pid)['variants']['standard']
        updated = {**current, 'width': 1440, 'height': 900, 'hidden_slides': ['second']}
        self.project.apply_structured_edits(self.pid, 'presentation', '', {'edits': [{'op': 'set_variant', 'id': 'standard', 'value': updated}]})
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['width'], 1440)
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], ['second'])

    def test_render_filters_hidden_slides(self) -> None:
        self.project.update_variant(self.pid, 'standard', {'name': 'Standard', 'width': 960, 'height': 540, 'hidden_slides': ['second']})
        renderer = Renderer(self.project)
        self.addCleanup(renderer.temp.cleanup)
        def fake_run(command, cwd, **kwargs):
            source = (cwd / 'en.qmd').read_text(encoding='utf-8')
            self.assertIn('height: 540', source)
            self.assertIn('{#first}', source)
            self.assertNotIn('{#second}', source)
            (cwd / 'en.html').write_text('<html><head></head><body></body></html>', encoding='utf-8')
            return SimpleNamespace(returncode=0)
        with patch('studio.render.shutil.which', return_value='quarto'), patch('studio.render.subprocess.run', side_effect=fake_run):
            renderer.render(self.pid, 'en', 'standard')



class ConfigTests(unittest.TestCase):
    def test_selection_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'config'
            first = Preferences(directory)
            values = {'presentation': 'overview', 'variant': 'complete', 'slide': 's014', 'language': 'en', 'scope': 'presentation'}
            first.update(values)
            self.assertEqual(Preferences(directory).read(), values)
            self.assertEqual((directory / 'session.json').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()


class KeySettingsTests(unittest.TestCase):
    def test_key_stored_under_explicit_directory(self) -> None:
        from studio.openrouter import OpenRouter
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'config'
            first = OpenRouter(folder)
            first.update('test_api_key')
            second = OpenRouter(folder)
            self.assertEqual(second.status(), {'hasKey': True})
            self.assertEqual((folder / 'settings.json').stat().st_mode & 0o777, 0o600)
            second.update(remove_key=True)
            self.assertFalse(OpenRouter(folder).status()['hasKey'])
