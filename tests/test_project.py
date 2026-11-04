from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from studio.project import Project
from studio.render import Renderer


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name) / "workspace"
        self.project = Project(self.workspace)
        self.addCleanup(self.project.temporary.cleanup)

    def test_initial_workspace_is_empty(self) -> None:
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertEqual(self.project.state()["presentations"], [])
        self.assertFalse(self.project.state()["dirty"])

    def test_bilingual_edit_and_save(self) -> None:
        pid = self.project.create_presentation("Visitor reception")
        self.assertEqual(self.project.state(pid)["slides"], ["opening"])
        self.assertFalse(list(self.workspace.iterdir()))
        self.project.apply_structured_edits(pid, "slide", "opening", {"edits": [{"op": "replace_slide", "slide_id": "opening", "sources": {"pt-BR": "## Boas-vindas {#opening}", "en": "## Welcome {#opening}"}}]})
        self.assertTrue(self.project.state()["dirty"])
        self.project.history_move(-1)
        self.assertIn("Visitor reception", self.project.sources(pid)[0])
        self.project.history_move(1)
        self.assertIn("Boas-vindas", self.project.sources(pid)[0])
        self.project.save()
        self.assertFalse(self.project.state()["dirty"])
        self.assertIn("Boas-vindas", (self.workspace / "presentations" / pid / "pt-BR.qmd").read_text())

    def test_pairing_validation_and_undo(self) -> None:
        pid = self.project.create_presentation("Example")
        with self.assertRaisesRegex(ValueError, "identical slide identifiers"):
            self.project.apply_structured_edits(pid, "presentation", "", {"edits": [{"op": "replace_text", "target": "slide", "slide_ids": ["opening"], "languages": ["pt-BR"], "find": "{#opening}", "replace": "{#one}"}]})
        self.assertEqual(self.project.state(pid)["slides"], ["opening"])
        with self.assertRaisesRegex(ValueError, "Executable"):
            self.project.apply_structured_edits(pid, "slide", "opening", {"edits": [{"op": "replace_text", "target": "slide", "slide_ids": ["opening"], "languages": ["pt-BR"], "find": "{#opening}", "replace": "{#opening}\n<script>x</script>"}]})
        self.project.remove_presentation(pid)
        self.assertEqual(self.project.presentations(), [])
        self.project.history_move(-1)
        self.assertEqual(len(self.project.presentations()), 1)

    def test_managed_fact_and_asset(self) -> None:
        self.project.set_fact("Students", "current_total", "2000", "2026-10-21", "Portal")
        self.project.set_asset("auditorium", "example.png", b"fakeimage", "Main auditorium")
        self.assertEqual(self.project.facts()["categories"]["Students"]["current_total"]["value"], "2000")
        self.project.set_asset_description("auditorium", "North auditorium")
        self.assertEqual(self.project.assets()["assets"]["auditorium"]["description"], "North auditorium")
        self.project.remove_asset("auditorium")
        self.assertEqual(self.project.assets()["assets"], {})
        self.project.history_move(-1)
        self.assertIn("auditorium", self.project.assets()["assets"])

    def test_preserves_git_directory(self) -> None:
        git = self.workspace / ".git"
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/main")
        self.project.create_presentation("Overview")
        self.project.save()
        self.assertEqual((git / "HEAD").read_text(), "ref: refs/heads/main")

    def test_render_preprocessing_only_in_copy(self) -> None:
        pid = self.project.create_presentation("Overview")
        self.project.set_fact("Students", "count", "4200", "2026-10-21", "")
        self.project.set_asset("auditorium", "example.png", b"fakeimage", "")
        self.project.apply_structured_edits(pid, "slide", "opening", {"edits": [{"op": "replace_slide", "slide_id": "opening", "sources": {"pt-BR": "## Olá {#opening}\n\n{{fact:Students.count}}\n\n![]({{asset:auditorium}})", "en": "## Hi {#opening}\n\n{{fact:Students.count}}\n\n![]({{asset:auditorium}})"}}]})
        renderer = Renderer(self.project)
        self.addCleanup(renderer.temp.cleanup)

        def fake_render(command: list[str], cwd: Path, **kwargs) -> SimpleNamespace:
            content = (Path(cwd) / "pt-BR.qmd").read_text()
            self.assertIn("4200", content)
            self.assertIn("../../assets/", content)
            (Path(cwd) / "pt-BR.html").write_text("<html><body>Slide</body></html>")
            return SimpleNamespace(returncode=0)

        with patch("studio.render.shutil.which", return_value="quarto"), patch("studio.render.subprocess.run", side_effect=fake_render):
            url = renderer.render(pid, "pt-BR", "standard")
            self.assertIn("/preview/", url)
            self.assertIn("studio-slide", renderer.resolve(url.split("/")[2], f"presentations/{pid}/pt-BR.html").read_text())
        self.assertIn("{{fact:Students.count}}", self.project.sources(pid)[0])


if __name__ == "__main__":
    unittest.main()
