from __future__ import annotations

import json
import tempfile
import threading
import time
from unittest.mock import patch
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from http_support import StudioHTTPTestCase


class HttpTests(StudioHTTPTestCase):
    def test_health_branding_and_presentation_duplication(self) -> None:
        import urllib.request
        health = self.request("/api/health")
        self.assertEqual(health, {"instance": self.server.instance})
        with urllib.request.urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        self.assertIn(f'content="{self.server.instance}"', page)
        self.assertIn(self.server.branding.name, page)
        with urllib.request.urlopen(self.base + "/static/branding.css") as response:
            css = response.read().decode("utf-8")
        self.assertIn(self.server.branding.accent_light, css)
        with urllib.request.urlopen(self.base + "/static/navigation.js") as response:
            self.assertIn(b"function resolveNavigableSlide", response.read())
        created = self.request("/api/presentations", "POST", {"name": "Overview"})["id"]
        copied = self.request("/api/presentations/duplicate", "POST", {"presentation": created, "name": "Overview copy"})["id"]
        self.assertEqual(copied, "overview-copy")
        self.assertEqual(self.request("/api/state?presentation=" + copied)["slides"], ["opening"])
        self.request("/api/history", "POST", {"direction": -1})
        self.assertNotIn(copied, [entry["id"] for entry in self.request("/api/state")["presentations"]])

    def test_default_branding_does_not_render_mark_or_favicon(self) -> None:
        from studio.branding import Branding
        original = self.server.branding
        self.server.branding = Branding()
        try:
            with urllib.request.urlopen(self.base + '/') as response:
                page = response.read().decode('utf-8')
            self.assertIn('<title>Slide Studio</title>', page)
            self.assertNotIn('class="brand"', page)
            self.assertIn('<link rel="icon" href="data:,">', page)
            self.assertNotIn('__STUDIO_BRAND__', page)
            self.assertNotIn('__STUDIO_FAVICON__', page)
            with urllib.request.urlopen(self.base + '/branding/favicon') as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(response.read(), b'')
        finally:
            self.server.branding = original

    def test_configured_mark_is_visible_in_header_and_favicon(self) -> None:
        from studio.branding import Branding
        original = self.server.branding
        self.server.branding = Branding(name="Example Studio", mark="EX.")
        try:
            with urllib.request.urlopen(self.base + '/') as response:
                page = response.read().decode('utf-8')
            self.assertIn('class="brand"', page)
            self.assertIn('EX<span>.</span>', page)
            self.assertIn('<link rel="icon" href="/branding/favicon">', page)
            with urllib.request.urlopen(self.base + '/branding/favicon') as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'<svg', response.read())
        finally:
            self.server.branding = original

    def test_library_management_and_slide_references(self) -> None:
        import urllib.request
        pid = self.request('/api/presentations', 'POST', {'name':'Overview'})['id']
        self.request('/api/facts/categories', 'POST', {'category':'People'})
        self.request('/api/facts/categories', 'POST', {'category':'Former'})
        self.request('/api/facts', 'POST', {'category':'People', 'key':'dean', 'value':'Ada'})
        self.request('/api/assets', 'POST', {'alias':'Portraits/dean', 'filename':'dean.png', 'content':'aW1hZ2U=', 'category':'Portraits'})
        src = self.server.project.sources(pid)[0]
        self.server.project.update_source(pid, 'pt-BR', src + '\n{{fact:People.dean}} {{asset:Portraits/dean}}')
        import urllib.parse
        resources = self.request('/api/slides/resources?' + urllib.parse.urlencode({'presentation':pid, 'slide':'opening'}))
        self.assertEqual(resources['facts'][0]['metadata']['value'], 'Ada')
        self.assertEqual(resources['assets'][0]['id'], 'Portraits/dean')
        self.request('/api/facts/move', 'POST', {'entries':[{'category':'People','key':'dean'}], 'target':'Former'})
        self.assertIn('{{fact:Former.dean}}', self.server.project.sources(pid)[0])
        self.request('/api/assets/duplicate', 'POST', {'alias':'Portraits/dean', 'destination':'Portraits/dean-copy'})
        self.assertIn('Portraits/dean-copy', self.request('/api/state')['assets']['assets'])
        self.request('/api/assets/folders', 'POST', {'folder':'Archive'})
        self.request('/api/assets/folders/move', 'POST', {'old':'Portraits','new':'Archive/Portraits'})
        self.assertIn('Archive/Portraits/dean', self.request('/api/state')['assets']['assets'])

    def test_create_and_save(self) -> None:
        self.assertEqual(self.request("/api/state")["presentations"], [])
        created = self.request("/api/presentations", "POST", {"name": "Overview"})
        state = self.request("/api/state?presentation=" + created["id"])
        self.assertEqual(state["slides"], ["opening"])
        self.assertTrue(state["dirty"])
        self.assertFalse(list(self.workspace.iterdir()))
        self.request("/api/save", "POST", {})
        self.assertFalse(self.request("/api/state")["dirty"])
        self.assertTrue((self.workspace / "presentations" / "overview" / "en.qmd").exists())

    def test_write_requires_session_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/presentations", "POST", {"name": "Denied"}, with_token=False)
        self.assertEqual(context.exception.code, 400)
        self.assertFalse(self.request("/api/state")["presentations"])

    def test_fact_and_undo(self) -> None:
        self.request("/api/facts", "POST", {"category": "Students", "key": "total", "value": "2000", "updated": "2026-10-21", "source": ""})
        self.assertEqual(self.request("/api/state")["facts"]["categories"]["Students"]["total"]["value"], "2000")
        self.request("/api/history", "POST", {"direction": -1})
        self.assertEqual(self.request("/api/state")["facts"]["categories"], {})

    def test_ai_job_cancellation_endpoint(self) -> None:
        def fake_edit(*args):
            cancelled = args[8]
            while not cancelled.is_set():
                time.sleep(0.01)
            from studio.openrouter import EditCancelled
            raise EditCancelled()
        with patch.object(self.server.openrouter, "change", side_effect=fake_edit):
            job = self.request("/api/ai", "POST", {"presentation": "example", "scope": "slide", "slide": "opening", "instruction": "Test", "variant": "standard", "visualContext": False, "model": "vendor/test", "effort": "default"})["job"]
            self.assertEqual(self.request("/api/ai/status?job=" + job)["status"], "running")
            self.request("/api/ai/cancel", "POST", {"job": job})
            for _ in range(50):
                status = self.request("/api/ai/status?job=" + job)
                if status["status"] == "cancelled":
                    break
                time.sleep(0.02)
            self.assertEqual(status["status"], "cancelled")

    def test_chat_receives_current_interface_selection(self) -> None:
        pid = self.request('/api/presentations', 'POST', {'name':'Welcome'})['id']
        received: list[dict] = []
        def fake_chat(*args):
            received.append(args[-1])
            return {'chat': 'temporary', 'answer': 'Okay.'}
        with patch.object(self.server.openrouter, 'chat', side_effect=fake_chat):
            job = self.request('/api/chat/message', 'POST', {'message':'What is this slide?', 'model':'test/model', 'selection':{'presentation':pid,'variant':'standard','language':'en','slide':'opening'}})['job']
            for _ in range(70):
                status = self.request('/api/ai/status?job=' + job)
                if status['status'] != 'running':
                    break
                time.sleep(0.02)
        self.assertEqual(status['status'],'complete',status)
        self.assertEqual(received, [{'presentation':pid,'variant':'standard','language':'en','slide':'opening'}])

    def test_temporary_api_key_for_model_browser(self) -> None:
        with patch.object(self.server.openrouter, "models", return_value=[{"id": "vendor/vision", "name": "Vision", "imageInput": True}]) as models:
            result = self.request("/api/models", "POST", {"key": "unsaved-secret"})
            self.assertEqual(result[0]["id"], "vendor/vision")
            models.assert_called_once_with("unsaved-secret")
        self.assertFalse(self.server.openrouter.status()["hasKey"])


if __name__ == "__main__":
    unittest.main()
