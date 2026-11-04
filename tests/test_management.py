from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from studio.project import Project
from studio.render import Renderer
from studio.preferences import Preferences


class StudioManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "workspace"
        self.project = Project(self.workspace)
        self.addCleanup(self.project.temporary.cleanup)

    def test_asset_categories_and_inclusion_dates(self) -> None:
        self.project.set_asset("hall", "photo.png", b"png1", "The hall", "Buildings", "2022-01-02")
        first = self.project.assets()["assets"]["hall"]
        self.assertEqual(first["category"], "Buildings")
        self.assertEqual(first["added"], "2022-01-02")
        self.project.set_asset("hall", "photo.png", b"png2", "The hall", "Facilities")
        second = self.project.assets()["assets"]["hall"]
        self.assertEqual(second["added"], "2022-01-02")
        self.assertEqual(second["category"], "Facilities")
        self.project.set_asset_description("hall", "Better image", "Rooms", "")
        third = self.project.assets()["assets"]["hall"]
        self.assertEqual(third["added"], None)
        self.assertEqual(third["category"], "Rooms")
        self.project.history_move(-1)
        self.assertEqual(self.project.assets()["assets"]["hall"]["added"], "2022-01-02")

    def test_scan_references_across_languages_and_deleted_values(self) -> None:
        first = self.project.create_presentation("First")
        second = self.project.create_presentation("Second")
        self.project.update_source(first, "pt-BR", self.project.sources(first)[0] + "\n{{fact:People.count}}\n![]({{asset:hall}})\n")
        self.project.update_source(second, "en", self.project.sources(second)[1] + "\n![]({{asset:hall}})\n")
        usage = self.project.state(first)["usage"]
        self.assertEqual(usage["facts"]["People.count"], [first])
        self.assertEqual(set(usage["assets"]["hall"]), {first, second})
        self.project.set_fact("People", "count", "42", "2026-11-01", "")
        self.project.set_asset("hall", "photo.png", b"png", "a hall")
        self.project.remove_facts([{"category": "People", "key": "count"}])
        self.project.remove_assets(["hall"])
        self.assertEqual(self.project.state(first)["usage"], usage)
        renderer = Renderer(self.project)
        self.addCleanup(renderer.temp.cleanup)

        def fake_render(command: list[str], cwd: Path, **kwargs: object) -> SimpleNamespace:
            content = (Path(cwd) / "pt-BR.qmd").read_text()
            self.assertIn("[Missing fact: People.count]", content)
            self.assertIn("_missing_", content)
            self.assertEqual(len(list((Path(cwd) / "../../assets").resolve().glob("_missing_*.svg"))), 1)
            (Path(cwd) / "pt-BR.html").write_text("<html><body>Preview</body></html>")
            return SimpleNamespace(returncode=0)

        with patch("studio.render.shutil.which", return_value="quarto"), patch("studio.render.subprocess.run", side_effect=fake_render):
            self.assertIn("/preview/", renderer.render(first, "pt-BR", "standard"))

    def test_bulk_deletion_is_atomic_and_undoable(self) -> None:
        self.project.set_fact("People", "count", "12", None, "")
        self.project.set_fact("People", "other", "13", None, "")
        self.project.set_asset("photo", "photo.png", b"png", "")
        self.project.set_asset("logo", "logo.png", b"png", "")
        before = self.project.state()
        with self.assertRaisesRegex(ValueError, "Fact not found"):
            self.project.remove_facts([{"category": "People", "key": "count"}, {"category": "People", "key": "missing"}])
        self.assertEqual(before["facts"], self.project.facts())
        with self.assertRaisesRegex(ValueError, "Asset not found"):
            self.project.remove_assets(["photo", "unknown"])
        self.assertEqual(before["assets"], self.project.assets())
        self.project.remove_facts([{"category": "People", "key": "count"}, {"category": "People", "key": "other"}])
        self.assertEqual(self.project.facts()["categories"], {"People": {}})
        self.project.history_move(-1)
        self.assertEqual(self.project.facts(), before["facts"])
        self.project.history_move(1)
        self.project.remove_assets(["photo", "logo"])
        self.assertEqual(self.project.assets()["assets"], {})
        self.assertFalse(self.project.state()["canRedo"])
        self.project.history_move(-1)
        self.assertEqual(self.project.assets(), before["assets"])

    def test_source_edit_and_presentation_settings(self) -> None:
        pid = self.project.create_presentation("Initial")
        self.project.update_presentation(pid, "Renamed", "")
        self.assertEqual(self.project.presentations()[0]["name"], "Renamed")
        pt, en = self.project.sources(pid)
        self.project.update_source(pid, "pt-BR", pt + "\nHello there\n")
        self.assertIn("Hello there", self.project.sources(pid)[0])
        with self.assertRaisesRegex(ValueError, "identical slide identifiers"):
            self.project.update_source(pid, "en", en + "\n## Additional {#second}\n")
        with self.assertRaisesRegex(ValueError, "code execution disabled"):
            self.project.update_source(pid, "pt-BR", pt.replace("enabled: false", "enabled: true"))
        self.assertIn("Hello there", self.project.sources(pid)[0])
        self.project.save()
        self.assertEqual((self.workspace / "presentations" / pid / "presentation.json").read_text().count("Renamed"), 1)

    def test_category_preference_persistence(self) -> None:
        config = Path(self.temporary.name) / "config"
        preferences = Preferences(config)
        preferences.update({"factCategory": "Students", "assetCategory": "Buildings"})
        self.assertEqual(Preferences(config).read()["assetCategory"], "Buildings")


if __name__ == "__main__":
    unittest.main()
