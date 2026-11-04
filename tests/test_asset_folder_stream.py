from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from studio.openrouter import OpenRouter, request_stream_worker
from studio.project import Project


class AssetFolderAndFactTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.project = Project(self.workspace)
        self.addCleanup(self.project.temporary.cleanup)

    def test_nested_asset_folders_move_renames_refs_and_supports_undo(self) -> None:
        pid = self.project.create_presentation("Reception")
        self.project.create_asset_folder("Buildings/Auditoriums")
        self.project.set_asset("Buildings/Auditoriums/main", "main.png", b"PNG", "auditorium", "Buildings/Auditoriums")
        self.project.update_source(pid, "pt-BR", self.project.sources(pid)[0] + "\n![]({{asset:Buildings/Auditoriums/main}})\n")
        self.project.update_source(pid, "en", self.project.sources(pid)[1] + "\n![]({{asset:Buildings/Auditoriums/main}})\n")
        self.project.move_asset_folder("Buildings/Auditoriums", "Facilities/Halls")
        self.assertIn("Facilities/Halls/main", self.project.assets()["assets"])
        self.assertIn("Facilities", self.project.assets()["folders"])
        self.assertIn("Facilities/Halls", self.project.assets()["folders"])
        for source in self.project.sources(pid):
            self.assertIn("{{asset:Facilities/Halls/main}}", source)
            self.assertNotIn("{{asset:Buildings/Auditoriums/main}}", source)
        self.project.history_move(-1)
        self.assertIn("Buildings/Auditoriums/main", self.project.assets()["assets"])
        self.project.history_move(1)
        self.project.move_assets({"Facilities/Halls/main": "Facilities/Halls/entrance"})
        self.assertEqual(self.project.usage()["assets"]["Facilities/Halls/entrance"], [pid])
        self.assertFalse(self.project.state()["canRedo"])
        self.project.save()
        self.assertIn("{{asset:Facilities/Halls/entrance}}", (self.workspace / "presentations" / pid / "en.qmd").read_text())

    def test_asset_edit_is_one_undo_step_and_folder_deletion_undoable(self) -> None:
        self.project.set_asset("Rooms/campus", "old.png", b"old", "before", "Rooms")
        old = self.project.assets()["assets"]["Rooms/campus"]
        self.project.edit_asset("Rooms/campus", "Rooms/campus-new", "after", "2026-11-01", "new.jpg", b"new")
        new = self.project.assets()["assets"]["Rooms/campus-new"]
        self.assertEqual(new["description"], "after")
        self.assertEqual((self.project.current / new["file"]).read_bytes(), b"new")
        self.project.history_move(-1)
        self.assertIn("Rooms/campus", self.project.assets()["assets"])
        self.assertEqual((self.project.current / old["file"]).read_bytes(), b"old")
        self.project.history_move(1)
        self.project.remove_asset_folder("Rooms")
        self.assertEqual(self.project.assets()["assets"], {})
        self.project.history_move(-1)
        self.assertIn("Rooms/campus-new", self.project.assets()["assets"])

    def test_atomic_asset_moves_reject_collisions(self) -> None:
        self.project.set_asset("General/photo", "photo.png", b"png", "", "General")
        self.project.set_asset("General/other", "photo.png", b"png", "", "General")
        with self.assertRaisesRegex(ValueError, "Destination asset already exists"):
            self.project.move_assets({"General/photo": "General/other"})
        self.assertEqual(len(self.project.assets()["assets"]), 2)
        self.project.move_assets({"General/photo": "General/other", "General/other": "General/photo"})
        self.assertEqual(len(self.project.assets()["assets"]), 2)

    def test_fact_category_file_and_batch_updates(self) -> None:
        pid = self.project.create_presentation("Facts")
        self.project.create_fact_category("Students")
        self.project.set_fact("Students", "total", "100", "2024-01-01", "example")
        self.project.set_fact("Students", "graduates", "50", None, "")
        self.project.update_source(pid, "pt-BR", self.project.sources(pid)[0] + "\n{{fact:Students.total}}\n")
        self.project.set_facts_batch("Students", [
            {"key": "total", "value": "150", "updated": "2026-11-01", "source": "new"},
            {"key": "graduates", "value": "70", "updated": "", "source": ""},
        ])
        self.assertEqual(self.project.facts()["categories"]["Students"]["total"]["value"], "150")
        self.project.history_move(-1)
        self.assertEqual(self.project.facts()["categories"]["Students"]["total"]["value"], "100")
        self.project.rename_fact("Students", "total", "Students", "enrollment")
        self.assertIn("{{fact:Students.enrollment}}", self.project.sources(pid)[0])
        self.project.rename_fact_category("Students", "People")
        self.assertIn("{{fact:People.enrollment}}", self.project.sources(pid)[0])
        self.project.remove_facts([{"category": "People", "key": "enrollment"}, {"category": "People", "key": "graduates"}])
        self.assertEqual(self.project.facts()["categories"]["People"], {})



class StreamProtocolTests(unittest.TestCase):
    def test_streamed_reasoning_and_content(self) -> None:
        def line(item: dict) -> bytes:
            return ("data: " + json.dumps(item) + "\n").encode()
        class Stream:
            def __enter__(self):
                return iter([
                    b": keep alive\n",
                    line({"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "text": "Thinking..."}]}}]}),
                    line({"choices": [{"delta": {"content": '{"pt-BR":"sample",'}}]}),
                    line({"choices": [{"delta": {"content": '"en":"sample"}'}, "finish_reason": "stop"}]}),
                    b"data: [DONE]\n",
                ])
            def __exit__(self, *args):
                return None
        receiver = Mock()
        with patch("studio.openrouter.urllib.request.urlopen", return_value=Stream()) as urlopen:
            request_stream_worker(receiver, "secret", {"model": "provider/test", "messages": []})
        events = [call.args[0] for call in receiver.send.call_args_list]
        self.assertIn(("reasoning", "Thinking..."), events)
        self.assertEqual(events[-1][0], "complete")
        self.assertEqual(json.loads(events[-1][1]["choices"][0]["message"]["content"]), {"pt-BR": "sample", "en": "sample"})
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertIs(body["stream"], True)
        self.assertNotIn("reasoning", body)
        self.assertIsNone(urlopen.call_args.kwargs["timeout"])

    def test_missing_done_is_an_error_not_partial_edit(self) -> None:
        class Stream:
            def __enter__(self):
                return iter([b'data: {"choices":[{"delta":{"content":"hello"}}]}\n'])
            def __exit__(self, *args):
                return None
        receiver = Mock()
        with patch("studio.openrouter.urllib.request.urlopen", return_value=Stream()):
            request_stream_worker(receiver, "secret", {"model": "test"})
        self.assertEqual(receiver.send.call_args.args[0][0], "error")
        self.assertIn("without [DONE]", receiver.send.call_args.args[0][1])


if __name__ == "__main__":
    unittest.main()
