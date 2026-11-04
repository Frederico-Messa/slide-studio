from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import mimetypes
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from studio.openrouter import OpenRouter
from studio.jobs import AIJobs
from studio.project import Project
from studio.render import Renderer
from studio.preferences import Preferences
from studio.chats import ChatStore
from studio.branding import Branding
from studio.scripts import ScriptJobs, get_script, update_script, remove_script
from studio.recipes import get_recipe, update_recipe, remove_recipe

ROOT = Path(__file__).resolve().parent
MAX_REQUEST_SIZE = 19 * 1024 * 1024


class StudioServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], workspace: Path):
        super().__init__(address, StudioHandler)
        self.branding = Branding.load(ROOT)
        self.instance = secrets.token_urlsafe(24)
        self.project = Project(workspace, self.branding)
        self.renderer = Renderer(self.project)
        self.openrouter = OpenRouter(ROOT / "config")
        self.preferences = Preferences(ROOT / "config")
        self.settings_lock = threading.RLock()
        self.csrf = secrets.token_urlsafe(32)
        self.jobs = AIJobs()
        self.chats = ChatStore(ROOT / "config")
        self.scripts = ScriptJobs(self.project)


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def log_error(self, format: str, *args: Any) -> None:
        super().log_message(format, *args)

    def send_data(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        if content_type.startswith("text/html") and not self.path.startswith("/preview/"):
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; frame-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'")
        if content_type.startswith("image/svg+xml"):
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox")
        if self.path.startswith("/preview/"):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            self.send_header("Content-Security-Policy", f"default-src 'none'; script-src 'unsafe-inline' {origin}; style-src 'unsafe-inline' {origin}; img-src data: blob: {origin}; font-src data: {origin}; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, data: Any, status: int = 200) -> None:
        self.send_data(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def send_file(self, path: Path) -> None:
        type_name = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if type_name.startswith("text/") or type_name in ("application/javascript", "application/json", "image/svg+xml"):
            type_name += "; charset=utf-8"
        self.send_data(path.read_bytes(), type_name)

    def read_json(self) -> dict:
        count = int(self.headers.get("Content-Length", 0))
        if count <= 0 or count > MAX_REQUEST_SIZE:
            raise ValueError("Invalid request size")
        data = json.loads(self.rfile.read(count))
        if not isinstance(data, dict):
            raise ValueError("JSON object expected")
        return data

    def check_write_permission(self) -> None:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and urllib.parse.urlparse(origin).netloc != host:
            raise PermissionError("Cross-origin request denied")
        if self.headers.get("X-Studio-Token") != self.server.csrf:
            raise PermissionError("Missing local session token")
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise PermissionError("JSON request required")

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if path == "/":
                page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
                branding = self.server.branding
                page = page.replace("__CSRF_TOKEN__", self.server.csrf)
                page = page.replace("__STUDIO_INSTANCE__", self.server.instance)
                branded = bool(branding.logo or branding.mark)
                header = f'<div class="brand" aria-label="{html.escape(branding.name, quote=True)}"><div class="brand-mark">{branding.mark_html()}</div></div>' if branded else ''
                page = page.replace("__STUDIO_NAME__", html.escape(branding.name, quote=True))
                page = page.replace("__STUDIO_BRAND__", header)
                page = page.replace("__STUDIO_FAVICON__", '<link rel="icon" href="/branding/favicon">' if branded else '<link rel="icon" href="data:,">')
                self.send_data(page.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/static/branding.css":
                self.send_data(self.server.branding.stylesheet().encode("utf-8"), "text/css; charset=utf-8")
            elif path == "/api/health":
                self.json_response({"instance": self.server.instance})
            elif path == "/branding/favicon":
                logo = self.server.branding.logo_path(ROOT)
                if logo is not None:
                    self.send_file(logo)
                elif self.server.branding.mark:
                    self.send_data(self.server.branding.favicon(), "image/svg+xml; charset=utf-8")
                else:
                    self.send_data(b"", "image/svg+xml; charset=utf-8", 204)
            elif path == "/branding/logo":
                logo = self.server.branding.logo_path(ROOT)
                if logo is None:
                    self.json_response({"error": "Not found"}, 404)
                else:
                    self.send_file(logo)
            elif path in ("/static/app.js", "/static/chat.js", "/static/scripts.js", "/static/recipes.js", "/static/explorer.js", "/static/models.js", "/static/navigation.js", "/static/source-diff.js", "/static/style.css", "/static/theme.css"):
                self.send_file(ROOT / path.lstrip("/"))
            elif path == "/api/state":
                self.json_response(self.server.project.state(query.get("presentation", [""])[0]))
            elif path == "/api/session":
                self.json_response(self.server.preferences.read())
            elif path == "/api/chats":
                self.json_response(self.server.chats.list())
            elif path == "/api/chat":
                self.json_response(self.server.chats.get(query.get("id", [""])[0]))
            elif path == "/api/script":
                with self.server.project.lock:
                    self.json_response(get_script(self.server.project, query.get("id", [""])[0]))
            elif path == "/api/recipe":
                with self.server.project.lock:
                    self.json_response(get_recipe(self.server.project, query.get("id", [""])[0]))
            elif path == "/api/scripts/status":
                self.json_response(self.server.scripts.status(query.get("job", [""])[0]))
            elif path == "/api/settings":
                self.json_response(self.server.openrouter.status())
            elif path == "/api/models":
                self.json_response(self.server.openrouter.models())
            elif path == "/api/ai/status":
                self.json_response(self.server.jobs.status(query.get("job", [""])[0]))
            elif path == "/api/source/saved":
                presentation = query.get("presentation", [""])[0]
                language = query.get("language", [""])[0]
                if language not in ("pt-BR", "en"):
                    raise ValueError("Invalid source language")
                with self.server.project.lock:
                    self.server.project.presentation_path(presentation)
                    saved_path = self.server.project.workspace / "presentations" / presentation / f"{language}.qmd"
                    self.json_response({"source": saved_path.read_text(encoding="utf-8") if saved_path.is_file() else ""})
            elif path == "/api/diff":
                self.json_response(self.server.project.diffs())
            elif path == "/api/preview":
                url = self.server.renderer.render(query.get("presentation", [""])[0], query.get("language", [""])[0], query.get("variant", ["standard"])[0], include_hidden=query.get("includeHidden", ["0"])[0] == "1")
                self.json_response({"url": url})
            elif path == "/api/pdf":
                url = self.server.renderer.pdf(query.get("presentation", [""])[0], query.get("language", [""])[0], query.get("variant", ["standard"])[0], f"http://127.0.0.1:{self.server.server_port}")
                self.json_response({"url": url})
            elif path == "/api/slides/resources":
                self.json_response(self.server.project.slide_resources(query.get("presentation", [""])[0], query.get("slide", [""])[0]))
            elif path == "/api/usages":
                self.json_response(self.server.project.usages(query.get("kind", [""])[0], query.get("id", [""])[0]))
            elif path == "/api/asset-image":
                alias = query.get("alias", [""])[0]
                with self.server.project.lock:
                    entry = self.server.project.assets().get("assets", {}).get(alias)
                    if not entry:
                        raise ValueError("Asset not found")
                    file = (self.server.project.current / entry["file"]).resolve()
                    if not file.is_relative_to(self.server.project.current.resolve()):
                        raise ValueError("Invalid asset path")
                    self.send_file(file)
            elif path.startswith("/preview/"):
                _, _, token, relative = path.split("/", 3)
                self.send_file(self.server.renderer.resolve(token, urllib.parse.unquote(relative)))
            else:
                self.json_response({"error": "Not found"}, 404)
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            self.json_response({"error": str(exc)}, 400)
        except Exception:
            self.json_response({"error": "Internal server error"}, 500)
            raise

    def do_POST(self) -> None:
        try:
            self.check_write_permission()
            data = self.read_json()
            path = urllib.parse.urlsplit(self.path).path
            project = self.server.project
            if path == "/api/presentations":
                self.json_response({"id": project.create_presentation(str(data.get("name", "")), data.get("width", 1280), data.get("height", 720))})
            elif path == "/api/presentations/duplicate":
                self.json_response({"id": project.duplicate_presentation(str(data.get("presentation", "")), str(data.get("name", "")))})
            elif path == "/api/presentations/settings":
                project.update_presentation(str(data.get("presentation", "")), str(data.get("name", "")), str(data.get("description", "")))
                self.json_response({"ok": True})
            elif path == "/api/slides/description":
                project.set_slide_description(str(data.get("presentation", "")), str(data.get("slide", "")), str(data.get("description", "")))
                self.json_response({"ok": True})
            elif path == "/api/source":
                project.update_source(str(data.get("presentation", "")), str(data.get("language", "")), data.get("source", ""))
                self.json_response({"ok": True})
            elif path == "/api/scripts":
                update_script(project, str(data.get("id", "")), data.get("metadata", {}), data.get("source", ""), data.get("previous"))
                self.json_response({"ok": True})
            elif path == "/api/recipes":
                update_recipe(project, str(data.get("id", "")), data.get("metadata", {}), data.get("instructions", ""), data.get("previous"))
                self.json_response({"ok": True})
            elif path == "/api/recipes/run":
                identifier = str(data.get("id", ""))
                model = str(data.get("model", ""))
                effort = str(data.get("effort", "default"))
                selection = data.get("selection")
                if not model or len(model) > 256 or (selection is not None and not isinstance(selection, dict)):
                    raise ValueError("Invalid recipe run parameters")
                with project.lock:
                    get_recipe(project, identifier)
                base_url = f"http://127.0.0.1:{self.server.server_port}"
                self.json_response({"job": self.server.jobs.start(lambda cancelled: self.server.openrouter.run_recipe(project, identifier, selection, model, effort, self.server.renderer, base_url, cancelled))})
            elif path == "/api/scripts/run":
                self.json_response({"job": self.server.scripts.start(str(data.get("id", "")), data.get("parameters", {}))})
            elif path == "/api/scripts/stop":
                self.json_response(self.server.scripts.stop(str(data.get("job", ""))))
            elif path == "/api/variants":
                project.update_variant(str(data.get("presentation", "")), str(data.get("id", "")), data.get("variant", {}), data.get("duplicateFrom"))
                self.json_response({"ok": True})
            elif path == "/api/slides/visibility":
                project.set_slide_hidden(str(data.get("presentation", "")), str(data.get("variant", "")), str(data.get("slide", "")), data.get("hidden"))
                self.json_response({"ok": True})
            elif path == "/api/variants/default":
                project.make_default_variant(str(data.get("presentation", "")), str(data.get("id", "")))
                self.json_response({"ok": True})
            elif path == "/api/precompute":
                self.server.renderer.schedule_precompute(f"http://127.0.0.1:{self.server.server_port}")
                self.json_response({"ok": True})
            elif path == "/api/session":
                self.json_response(self.server.preferences.update(data))
            elif path == "/api/facts/batch":
                project.set_facts_batch(str(data.get("category", "")), data.get("changes", []))
                self.json_response({"ok": True})
            elif path == "/api/facts":
                project.set_fact(str(data.get("category", "")), str(data.get("key", "")), str(data.get("value", "")), str(data.get("updated", "")), str(data.get("description", "")))
                self.json_response({"ok": True})
            elif path == "/api/assets":
                try:
                    content = base64.b64decode(data.get("content", ""), validate=True)
                except (ValueError, TypeError) as exc:
                    raise ValueError("Invalid image encoding") from exc
                project.set_asset(str(data.get("alias", "")), str(data.get("filename", "")), content, str(data.get("description", "")), str(data.get("category", "")), data.get("added"))
                self.json_response({"ok": True})
            elif path == "/api/facts/move":
                project.move_facts(data.get("entries"), str(data.get("target", "")))
                self.json_response({"ok": True})
            elif path == "/api/facts/merge":
                project.merge_facts(data.get("entries"), data.get("survivor", {}))
                self.json_response({"ok": True})
            elif path == "/api/assets/merge":
                project.merge_assets(data.get("aliases"), str(data.get("survivor", "")))
                self.json_response({"ok": True})
            elif path == "/api/chats":
                self.json_response(self.server.chats.create(str(data.get("name", "Chat")), data.get("source"), data.get("until"), str(data.get("model", "")), str(data.get("effort", "default"))))
            elif path == "/api/chats/settings":
                self.json_response(self.server.chats.settings(str(data.get("id", "")), str(data.get("model", "")), str(data.get("effort", "default"))))
            elif path == "/api/chats/rename":
                self.json_response(self.server.chats.rename(str(data.get("id", "")), str(data.get("name", ""))))
            elif path == "/api/chats/restore":
                self.json_response(self.server.chats.restore(str(data.get("id", "")), data.get("until")))
            elif path == "/api/chat/message":
                chat_id = str(data.get("id", ""))
                instruction = str(data.get("message", ""))
                if not instruction.strip():
                    raise ValueError("Provide a message")
                from uuid import uuid4
                chat = self.server.chats.get(chat_id) if chat_id else {'id': '', 'draft_id': uuid4().hex, 'messages': [], 'revision': 0}
                model = str(data.get('model') or chat.get('model') or '')
                effort = str(data.get('effort', chat.get('reasoning_effort', 'default')))
                selection = data.get('selection')
                if not model or len(model) > 256:
                    raise ValueError("Choose an OpenRouter model")
                if selection is not None and not isinstance(selection, dict):
                    raise ValueError('Invalid editor selection')
                self.json_response({"job": self.server.jobs.start(lambda cancelled: self.server.openrouter.chat(project, self.server.chats, chat, instruction, cancelled, self.server.renderer, f"http://127.0.0.1:{self.server.server_port}", model, effort, selection))})
            elif path == "/api/assets/edit":
                raw = data.get("content")
                try:
                    content = base64.b64decode(raw, validate=True) if raw is not None else None
                except (TypeError, ValueError) as exc:
                    raise ValueError("Invalid image encoding") from exc
                project.edit_asset(str(data.get("alias", "")), str(data.get("destination", "")), str(data.get("description", "")), data.get("added"), str(data.get("filename", "")), content)
                self.json_response({"ok": True})
            elif path == "/api/assets/duplicate":
                project.duplicate_asset(str(data.get("alias", "")), str(data.get("destination", "")))
                self.json_response({"ok": True})
            elif path == "/api/assets/move":
                project.move_assets(data.get("moves", {}))
                self.json_response({"ok": True})
            elif path == "/api/assets/folders":
                project.create_asset_folder(str(data.get("folder", "")))
                self.json_response({"ok": True})
            elif path == "/api/assets/folders/move":
                project.move_asset_folder(str(data.get("old", "")), str(data.get("new", "")))
                self.json_response({"ok": True})
            elif path == "/api/facts/categories":
                project.create_fact_category(str(data.get("category", "")))
                self.json_response({"ok": True})
            elif path == "/api/facts/categories/rename":
                project.rename_fact_category(str(data.get("old", "")), str(data.get("new", "")))
                self.json_response({"ok": True})
            elif path == "/api/facts/rename":
                project.rename_fact(str(data.get("category", "")), str(data.get("key", "")), str(data.get("newCategory", "")), str(data.get("newKey", "")))
                self.json_response({"ok": True})
            elif path == "/api/assets/description":
                project.set_asset_description(str(data.get("alias", "")), str(data.get("description", "")), data.get("category"), data.get("added"))
                self.json_response({"ok": True})
            elif path == "/api/history":
                direction = data.get("direction")
                if direction not in (-1, 1):
                    raise ValueError("Invalid undo/redo direction")
                self.json_response({"moved": project.history_move(direction)})
            elif path == "/api/save":
                project.save()
                self.json_response({"ok": True})
            elif path == "/api/models":
                self.json_response(self.server.openrouter.models(str(data.get("key", "")) or None))
            elif path == "/api/settings":
                with self.server.settings_lock:
                    self.server.openrouter.update(data.get("key"), bool(data.get("removeKey", False)))
                    self.json_response(self.server.openrouter.status())
            elif path == "/api/ai":
                pid = str(data.get("presentation", ""))
                scope = str(data.get("scope", ""))
                slide = str(data.get("slide", ""))
                instruction = str(data.get("instruction", ""))
                variant = str(data.get("variant", "standard"))
                base_url = f"http://127.0.0.1:{self.server.server_port}"
                chat = self.server.chats.get(str(data["chatId"])) if data.get("chatId") else None
                model = str(data.get('model') or '')
                effort = str(data.get('effort', 'default'))
                selection = data.get('selection')
                if selection is not None and not isinstance(selection, dict):
                    raise ValueError('Invalid editor selection')
                if not model or len(model) > 256:
                    raise ValueError('Choose an OpenRouter model')
                if scope in ("slide", "presentation"):
                    run_edit = lambda cancelled: self.server.openrouter.change(project, pid, scope, slide, instruction, variant, self.server.renderer, base_url, cancelled, chat, model, effort, selection)
                elif scope in ("fact_table", "facts", "asset_folder", "assets", "script", "scripts", "recipe", "recipes"):
                    target = str(data.get("target", ""))
                    run_edit = lambda cancelled: self.server.openrouter.change_resource(project, scope, target, instruction, self.server.renderer, base_url, cancelled, chat, model, effort, selection)
                else:
                    raise ValueError("Invalid edit scope")
                self.json_response({"job": self.server.jobs.start(run_edit)})
            elif path == "/api/ai/cancel":
                self.json_response(self.server.jobs.cancel(str(data.get("job", ""))))
            else:
                self.json_response({"error": "Not found"}, 404)
        except (ValueError, PermissionError, KeyError, OSError, json.JSONDecodeError) as exc:
            self.json_response({"error": str(exc)}, 400)
        except Exception:
            self.json_response({"error": "Internal server error"}, 500)
            raise

    def do_DELETE(self) -> None:
        try:
            self.check_write_permission()
            data = self.read_json()
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/presentations":
                self.server.project.remove_presentation(str(data.get("id", "")))
            elif path == "/api/scripts":
                remove_script(self.server.project, str(data.get("id", "")))
            elif path == "/api/recipes":
                remove_recipe(self.server.project, str(data.get("id", "")))
            elif path == "/api/variants":
                self.server.project.remove_variant(str(data.get("presentation", "")), str(data.get("id", "")))
            elif path == "/api/chats":
                self.server.chats.delete(str(data.get("id", "")))
            elif path == "/api/assets/folders":
                self.server.project.remove_asset_folder(str(data.get("folder", "")))
            elif path == "/api/facts/categories":
                self.server.project.remove_fact_category(str(data.get("category", "")))
            elif path == "/api/facts/bulk":
                self.server.project.remove_facts(data.get("entries"))
            elif path == "/api/assets/bulk":
                self.server.project.remove_assets(data.get("aliases"))
            elif path == "/api/facts":
                self.server.project.remove_fact(str(data.get("category", "")), str(data.get("key", "")))
            elif path == "/api/assets":
                self.server.project.remove_asset(str(data.get("alias", "")))
            else:
                self.json_response({"error": "Not found"}, 404)
                return
            self.json_response({"ok": True})
        except (ValueError, PermissionError, KeyError, OSError) as exc:
            self.json_response({"error": str(exc)}, 400)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Slide Studio")
    parser.add_argument("--workspace", type=Path, default=ROOT / "workspace")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = StudioServer(("127.0.0.1", args.port), args.workspace)
    address = f"http://127.0.0.1:{server.server_port}/"
    print(f"{server.branding.name}: {address}", flush=True)
    if not args.no_browser:
        threading.Timer(0.4, webbrowser.open, args=(address,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
