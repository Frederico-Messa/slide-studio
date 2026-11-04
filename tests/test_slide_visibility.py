from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import StudioServer
from studio.project import Project
from studio.render import Renderer


class SlideVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Project(Path(self.directory.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Visibility test')
        self.project.apply_structured_edits(self.pid, 'presentation', '', {'edits': [{
            'op': 'insert_slide', 'slide_id': 'closing', 'position': 'end',
            'sources': {'pt-BR': '## Fim {#closing}\n\nText', 'en': '## End {#closing}\n\nText'},
        }]})
        self.project.save()

    def test_hide_unhide_and_undo(self) -> None:
        self.project.set_slide_hidden(self.pid, 'standard', 'closing', True)
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], ['closing'])
        self.assertEqual(self.project.state(self.pid)['slides'], ['opening', 'closing'])
        self.project.history_move(-1)
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], [])
        self.project.history_move(1)
        self.project.set_slide_hidden(self.pid, 'standard', 'closing', False)
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], [])

    def test_cannot_hide_only_visible_slide(self) -> None:
        self.project.set_slide_hidden(self.pid, 'standard', 'closing', True)
        with self.assertRaisesRegex(ValueError, 'At least one'):
            self.project.set_slide_hidden(self.pid, 'standard', 'opening', True)
        self.assertEqual(self.project.variants(self.pid)['variants']['standard']['hidden_slides'], ['closing'])

    def test_unknown_slide_and_variant(self) -> None:
        with self.assertRaisesRegex(ValueError, 'Slide not found'):
            self.project.set_slide_hidden(self.pid, 'standard', 'unknown', True)
        with self.assertRaisesRegex(ValueError, 'Variant not found'):
            self.project.set_slide_hidden(self.pid, 'unknown', 'opening', True)
        with self.assertRaisesRegex(ValueError, 'visibility'):
            self.project.set_slide_hidden(self.pid, 'standard', 'opening', 'true')

    def test_renderer_include_hidden_and_pdf_cache(self) -> None:
        renderer = Renderer(self.project)
        self.addCleanup(renderer.temp.cleanup)
        self.project.set_slide_hidden(self.pid, 'standard', 'closing', True)
        with patch('studio.render.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Quarto'):
                renderer.render(self.pid, 'pt-BR', 'standard', include_hidden=True)
        self.assertIn('studio-ready', __import__('studio.render', fromlist=['BRIDGE']).BRIDGE)
        self.assertIn('studio-layout', __import__('studio.render', fromlist=['BRIDGE']).BRIDGE)

    def test_revision_changes_and_precompute(self) -> None:
        revision = self.project.state(self.pid)['revision']
        self.project.set_fact('Students', 'count', '45', '', '')
        self.assertGreater(self.project.state(self.pid)['revision'], revision)
        self.project.history_move(-1)
        self.assertGreater(self.project.state(self.pid)['revision'], revision)


if __name__ == '__main__':
    unittest.main()
