from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from studio.branding import Branding
from studio.project import Project


class BrandingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_stock_defaults_and_configured_appearance(self) -> None:
        stock = Branding.load(self.root)
        self.assertEqual(stock.name, "Slide Studio")
        self.assertEqual(stock.mark, "")
        self.assertEqual(stock.mark_html(), "")
        (self.root / "branding.toml").write_text('name = "Name only"\n')
        self.assertEqual(Branding.load(self.root).mark, "")
        self.assertIn(stock.slide_accent, stock.presentation_stylesheet())
        (self.root / "branding.toml").write_text('name = "Example Studio"\nmark = "XY."\naccent_light = "#224466"\naccent_dark = "#6688aa"\nslide_accent = "#335577"\n')
        configured = Branding.load(self.root)
        self.assertEqual(configured.name, "Example Studio")
        self.assertEqual(configured.mark_html(), 'XY<span>.</span>')
        self.assertIn("#224466", configured.stylesheet())
        self.assertIn("#335577", configured.presentation_stylesheet())

    def test_logo_and_invalid_branding_are_rejected_or_resolved(self) -> None:
        folder = self.root / "branding"
        folder.mkdir()
        (folder / "logo.svg").write_text("<svg></svg>")
        (self.root / "branding.toml").write_text('logo = "branding/logo.svg"\n')
        branding = Branding.load(self.root)
        self.assertEqual(branding.logo_path(self.root), folder / "logo.svg")
        self.assertIn('src="/branding/logo"', branding.mark_html())
        (self.root / "branding.toml").write_text('logo = "../secret.svg"\n')
        with self.assertRaisesRegex(ValueError, "Branding logo"):
            Branding.load(self.root)
        (self.root / "branding.toml").write_text('accent_light = "not-a-color"\n')
        with self.assertRaisesRegex(ValueError, "Branding colors"):
            Branding.load(self.root)


class DuplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name) / "workspace"
        self.project = Project(self.workspace, Branding(slide_accent="#123456"))
        self.addCleanup(self.project.temporary.cleanup)

    def test_default_presentation_uses_branding(self) -> None:
        presentation = self.project.create_presentation("Welcome")
        source = self.project.sources(presentation)[0]
        self.assertIn("css: theme.css", source)
        self.assertIn("#123456", (self.project.presentation_path(presentation) / "theme.css").read_text())

    def test_complete_duplicate_is_independent_undoable_and_savable(self) -> None:
        original = self.project.create_presentation("Overview")
        self.project.update_presentation(original, "Overview", "Presentation description")
        self.project.set_slide_description(original, "opening", "Slide description")
        self.project.update_variant(original, "compact", {"name":"Short", "description":"Short version", "width":1280, "height":720, "hidden_slides":[]}, duplicate_from="standard")
        pt, en = self.project.sources(original)
        self.project.update_source(original, "pt-BR", pt + "\nUnsaved source contents\n")
        self.project.update_source(original, "en", en + "\nUnsaved source contents\n")
        (self.project.presentation_path(original) / "local.css").write_text(".reveal{color:blue}")
        copied = self.project.duplicate_presentation(original, "Overview copy")
        self.assertEqual(copied, "overview-copy")
        self.assertEqual(self.project.sources(original), self.project.sources(copied))
        self.assertEqual(self.project.variants(original), self.project.variants(copied))
        self.assertEqual(self.project.slide_descriptions(copied), {"opening": "Slide description"})
        self.assertEqual(self.project.presentations()[-1]["description"], "Presentation description")
        self.assertEqual((self.project.presentation_path(copied) / "local.css").read_text(), ".reveal{color:blue}")
        self.project.update_presentation(copied, "Copy renamed", "Different description")
        self.assertEqual(self.project.presentations()[0]["name"], "Overview")
        self.project.history_move(-1)
        self.project.history_move(-1)
        self.assertNotIn(copied, [entry["id"] for entry in self.project.presentations()])
        self.project.history_move(1)
        self.assertIn(copied, [entry["id"] for entry in self.project.presentations()])
        self.project.save()
        self.assertTrue((self.workspace / "presentations" / copied / "local.css").is_file())

    def test_duplicate_name_collisions_and_invalid_target(self) -> None:
        original = self.project.create_presentation("Overview")
        self.assertEqual(self.project.duplicate_presentation(original, "Overview"), "overview-2")
        self.assertEqual(self.project.duplicate_presentation(original, "Overview"), "overview-3")
        before = len(self.project.presentations())
        with self.assertRaisesRegex(ValueError, "Provide a presentation name"):
            self.project.duplicate_presentation(original, "  ")
        with self.assertRaisesRegex(ValueError, "Presentation not found"):
            self.project.duplicate_presentation("missing", "Copy")
        self.assertEqual(len(self.project.presentations()), before)


if __name__ == "__main__":
    unittest.main()
