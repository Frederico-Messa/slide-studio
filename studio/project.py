from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from threading import RLock
from uuid import uuid4
from typing import Any, Callable

from .branding import Branding
from .project_shared import SLUG, SLIDE, LANGUAGES, MAX_HISTORY, YAML_HEADER, validate_folder, validate_asset_alias, load_json, save_json, split_qmd, validate_bilingual_sources
from .project_resources import ResourceMethods

def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts or not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def copy_content(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.name == ".git":
            continue
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        elif entry.is_file():
            shutil.copy2(entry, destination)


def snapshot_content(source: Path, target: Path) -> None:
    def copy_file(origin: str, destination: str) -> str:
        if Path(origin).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
            try:
                os.link(origin, destination)
                return destination
            except OSError:
                pass
        return shutil.copy2(origin, destination)

    shutil.copytree(source, target, copy_function=copy_file, dirs_exist_ok=True)


def replace_content(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for entry in target.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        elif entry.is_file():
            entry.unlink()
    copy_content(source, target)


class Project(ResourceMethods):
    def __init__(self, workspace: Path, branding: Branding | None = None):
        self.branding = branding or Branding()
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.temporary = tempfile.TemporaryDirectory(prefix="slide-studio-")
        self.root = Path(self.temporary.name)
        self.current = self.root / "current"
        self.current.mkdir()
        copy_content(self.workspace, self.current)
        self.history = self.root / "history"
        self.history.mkdir()
        self.states: list[Path] = []
        self.position = -1
        self.revision = 0
        self.last_state: Path | None = None
        self.baseline = tree_digest(self.workspace)
        self.saved_digest = tree_digest(self.current)
        self._checkpoint()

    def _checkpoint(self) -> None:
        self.last_state = self.states[self.position] if self.position >= 0 else None
        for old in self.states[self.position + 1:]:
            shutil.rmtree(old)
        self.states = self.states[:self.position + 1]
        snapshot = self.history / uuid4().hex
        snapshot_content(self.current, snapshot)
        self.states.append(snapshot)
        self.position += 1
        if len(self.states) > MAX_HISTORY:
            shutil.rmtree(self.states.pop(0))
            self.position -= 1

    def _mutate(self, fn: Callable[[], None]) -> None:
        before = self.root / ("before-" + uuid4().hex)
        snapshot_content(self.current, before)
        try:
            fn()
            self._validate_all()
            self._checkpoint()
            self.revision += 1
        except Exception:
            replace_content(before, self.current)
            raise
        finally:
            shutil.rmtree(before)

    def _validate_all(self) -> None:
        from .scripts import get_script
        scripts_dir = self.current / "scripts"
        if scripts_dir.is_dir():
            for entry in scripts_dir.iterdir():
                if not entry.is_dir() or not SLUG.fullmatch(entry.name):
                    raise ValueError("Invalid script folder")
                get_script(self, entry.name)
        from .recipes import get_recipe
        recipes_dir = self.current / "recipes"
        if recipes_dir.is_dir():
            for entry in recipes_dir.iterdir():
                if not entry.is_dir() or not SLUG.fullmatch(entry.name):
                    raise ValueError("Invalid recipe folder")
                get_recipe(self, entry.name)
        for item in self.presentations():
            pt, en = self.sources(item["id"])
            validate_bilingual_sources(pt, en)
            self.variants(item["id"])

    def _list_scripts(self) -> list[dict[str, Any]]:
        from .scripts import list_scripts
        return list_scripts(self)

    def _list_recipes(self) -> list[dict[str, str]]:
        from .recipes import list_recipes
        return list_recipes(self)

    def presentations(self) -> list[dict[str, str]]:
        directory = self.current / "presentations"
        if not directory.exists():
            return []
        result = []
        for entry in sorted(directory.iterdir()):
            if entry.is_dir() and SLUG.fullmatch(entry.name) and (entry / "presentation.json").is_file():
                data = load_json(entry / "presentation.json", {})
                result.append({"id": entry.name, "name": str(data.get("name", entry.name)), "description": str(data.get("description", ""))})
        return result

    def presentation_path(self, pid: str) -> Path:
        if not SLUG.fullmatch(pid):
            raise ValueError("Invalid presentation identifier")
        path = self.current / "presentations" / pid
        if not (path / "presentation.json").is_file():
            raise ValueError("Presentation not found")
        return path

    def sources(self, pid: str) -> tuple[str, str]:
        base = self.presentation_path(pid)
        return tuple((base / (language + ".qmd")).read_text(encoding="utf-8") for language in LANGUAGES)

    def _presentation_id(self, name: str) -> str:
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("Provide a presentation name (1–100 characters)")
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:55]
        if not base or not base[0].isalpha():
            base = "presentation"
        candidate = base
        suffix = 2
        while (self.current / "presentations" / candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def create_presentation(self, name: str, width: int = 1280, height: int = 720) -> str:
        name = name.strip()
        if not all(type(value) is int and 320 <= value <= 8192 for value in (width, height)):
            raise ValueError("Invalid presentation dimensions")
        with self.lock:
            pid = self._presentation_id(name)

            def operation() -> None:
                directory = self.current / "presentations" / pid
                directory.mkdir(parents=True)
                from .variants import default_variants
                save_json(directory / "presentation.json", {"name": name, "description": ""})
                save_json(directory / "slides.json", {"descriptions": {"opening": ""}})
                save_json(directory / "variants.json", default_variants(width, height))
                for language in LANGUAGES:
                    (directory / (language + ".qmd")).write_text(YAML_HEADER + f"## {name} {{#opening}}\n", encoding="utf-8")
                (directory / "theme.css").write_text(self.branding.presentation_stylesheet(), encoding="utf-8")

            self._mutate(operation)
            return pid

    def duplicate_presentation(self, source_id: str, name: str) -> str:
        name = name.strip()
        with self.lock:
            source = self.presentation_path(source_id)
            new_id = self._presentation_id(name)

            def operation() -> None:
                destination = self.current / "presentations" / new_id
                shutil.copytree(source, destination)
                metadata_path = destination / "presentation.json"
                metadata = load_json(metadata_path, {})
                metadata["name"] = name
                save_json(metadata_path, metadata)

            self._mutate(operation)
            return new_id

    def variants(self, pid: str) -> dict[str, Any]:
        from .variants import normalize_variants
        directory = self.presentation_path(pid)
        pt, en = self.sources(pid)
        ids = validate_bilingual_sources(pt, en)
        data = load_json(directory / "variants.json", {})
        return normalize_variants(data, ids)

    def update_variant(self, pid: str, key: str, variant: dict[str, Any], duplicate_from: str | None = None) -> None:
        from .variants import normalize_variants
        if not SLUG.fullmatch(key):
            raise ValueError("Invalid variant identifier")
        with self.lock:
            def operation() -> None:
                data = self.variants(pid)
                if duplicate_from is not None:
                    if key in data["variants"]:
                        raise ValueError("Variant already exists")
                    if duplicate_from not in data["variants"]:
                        raise ValueError("Source variant not found")
                elif key not in data["variants"]:
                    raise ValueError("Variant not found")
                data["variants"][key] = {"name": variant.get("name"), "description": variant.get("description", ""), "width": variant.get("width"), "height": variant.get("height"), "hidden_slides": variant.get("hidden_slides", [])}
                ids = validate_bilingual_sources(*self.sources(pid))
                normalized = normalize_variants(data, ids)
                path = self.presentation_path(pid)
                save_json(path / "variants.json", normalized)
            self._mutate(operation)

    def set_slide_hidden(self, pid: str, variant_id: str, slide_id: str, hidden: bool) -> None:
        if type(hidden) is not bool:
            raise ValueError("Invalid visibility value")
        with self.lock:
            def operation() -> None:
                configurations = self.variants(pid)
                if variant_id not in configurations["variants"]:
                    raise ValueError("Variant not found")
                ids = validate_bilingual_sources(*self.sources(pid))
                if slide_id not in ids:
                    raise ValueError("Slide not found")
                variant = configurations["variants"][variant_id]
                omitted = set(variant["hidden_slides"])
                if hidden:
                    omitted.add(slide_id)
                else:
                    omitted.discard(slide_id)
                variant["hidden_slides"] = [id for id in ids if id in omitted]
                from .variants import normalize_variants
                normalized = normalize_variants(configurations, ids)
                directory = self.presentation_path(pid)
                save_json(directory / "variants.json", normalized)
            self._mutate(operation)

    def remove_variant(self, pid: str, key: str) -> None:
        with self.lock:
            def operation() -> None:
                data = self.variants(pid)
                if key not in data["variants"]:
                    raise ValueError("Variant not found")
                if len(data["variants"]) == 1:
                    raise ValueError("Cannot remove the last variant")
                del data["variants"][key]
                if data["default"] == key:
                    data["default"] = next(iter(data["variants"]))
                path = self.presentation_path(pid)
                save_json(path / "variants.json", data)
            self._mutate(operation)

    def make_default_variant(self, pid: str, key: str) -> None:
        with self.lock:
            def operation() -> None:
                data = self.variants(pid)
                if key not in data["variants"]:
                    raise ValueError("Variant not found")
                data["default"] = key
                path = self.presentation_path(pid)
                save_json(path / "variants.json", data)
            self._mutate(operation)

    def update_presentation(self, pid: str, name: str, description: str) -> None:
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("Provide a presentation name (1–100 characters)")
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError("Invalid description")
        with self.lock:
            def operation() -> None:
                path = self.presentation_path(pid) / "presentation.json"
                data = load_json(path, {})
                data["name"] = name
                data["description"] = description
                save_json(path, data)
            self._mutate(operation)

    def slide_descriptions(self, pid: str) -> dict[str, str]:
        data = load_json(self.presentation_path(pid) / "slides.json", {"descriptions": {}})
        return data["descriptions"]

    def set_slide_description(self, pid: str, slide_id: str, description: str) -> None:
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError("Invalid description")
        with self.lock:
            def operation() -> None:
                if slide_id not in validate_bilingual_sources(*self.sources(pid)):
                    raise ValueError("Slide not found")
                data = {"descriptions": self.slide_descriptions(pid)}
                data["descriptions"][slide_id] = description
                save_json(self.presentation_path(pid) / "slides.json", data)
            self._mutate(operation)

    def update_source(self, pid: str, language: str, content: str) -> None:
        if language not in LANGUAGES:
            raise ValueError("Invalid language")
        if not isinstance(content, str) or len(content) > 16_000_000:
            raise ValueError("Invalid source size")
        prefix, _ = split_qmd(content)
        if not re.search(r"(?m)^format:\s*\n  revealjs:\s*$", prefix) or not re.search(r"(?m)^execute:\s*\n  enabled:\s*false\s*$", prefix):
            raise ValueError("Source must use Reveal.js with code execution disabled")
        with self.lock:
            def operation() -> None:
                (self.presentation_path(pid) / f"{language}.qmd").write_text(content, encoding="utf-8")
            self._mutate(operation)

    def remove_presentation(self, pid: str) -> None:
        with self.lock:
            self._mutate(lambda: shutil.rmtree(self.presentation_path(pid)))

    def apply_structured_edits(self, pid: str, scope: str, slide_id: str, changes: dict[str, Any]) -> None:
        from .operations import apply
        apply(self, scope, "", changes, presentation=pid, slide=slide_id)

    def history_move(self, direction: int) -> bool:
        with self.lock:
            next_index = self.position + direction
            if not 0 <= next_index < len(self.states):
                return False
            self.last_state = self.states[self.position]
            self.position = next_index
            replace_content(self.states[self.position], self.current)
            self.revision += 1
            return True

    @staticmethod
    def compare_files(old_root: Path, new_root: Path, path_prefix: str | None = None, include_diff: bool = True) -> list[dict[str, str]]:
        files: set[str] = set()
        for root in (old_root, new_root):
            files.update(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts)
        result: list[dict[str, str]] = []
        for file in sorted(files):
            if path_prefix is not None and file != path_prefix and not file.startswith(path_prefix.rstrip('/') + '/'):
                continue
            old = old_root / file
            new = new_root / file
            if old.is_file() and new.is_file() and old.read_bytes() == new.read_bytes():
                continue
            if not include_diff:
                result.append({"path": file})
                continue
            if Path(file).suffix.lower() not in (".qmd", ".json", ".css", ".md", ".txt", ".yml", ".yaml", ".py"):
                result.append({"path": file, "diff": "Binary asset changed"})
                continue
            before = old.read_text(encoding="utf-8").splitlines(keepends=True) if old.is_file() else []
            after = new.read_text(encoding="utf-8").splitlines(keepends=True) if new.is_file() else []
            diff = "".join(difflib.unified_diff(before, after, fromfile="before/" + file, tofile="current/" + file))
            result.append({"path": file, "diff": diff})
        return result

    def diffs(self) -> list[dict[str, str]]:
        with self.lock:
            return self.compare_files(self.workspace, self.current)

    def preceding_diffs(self) -> list[dict[str, str]]:
        with self.lock:
            if self.last_state is None:
                return []
            return self.compare_files(self.last_state, self.current)

    def save(self) -> None:
        with self.lock:
            if tree_digest(self.workspace) != self.baseline:
                raise ValueError("Workspace changed outside the app. Restart before saving to avoid overwriting those changes")
            replace_content(self.current, self.workspace)
            self.baseline = tree_digest(self.workspace)
            self.saved_digest = tree_digest(self.current)

    def state(self, pid: str | None = None) -> dict[str, Any]:
        with self.lock:
            asset_details = self.asset_state()["assets"]
            result = {
                "revision": self.revision,
                "presentations": self.presentations(),
                "facts": self.facts(),
                "assets": self.assets(),
                "assetDetails": {alias: {"bytes": entry["bytes"], "width": entry["width"], "height": entry["height"]} for alias, entry in asset_details.items()},
                "assetSizes": {alias: entry["bytes"] for alias, entry in asset_details.items()},
                "usage": self.usage(),
                "dirty": tree_digest(self.current) != self.saved_digest,
                "canUndo": self.position > 0,
                "canRedo": self.position < len(self.states) - 1,
                "scripts": self._list_scripts(),
                "recipes": self._list_recipes(),
            }
            if pid and any(item["id"] == pid for item in result["presentations"]):
                pt, en = self.sources(pid)
                slide_parts = split_qmd(pt)[1]
                result["allSlides"] = [slide["id"] for slide in slide_parts]
                result["variants"] = self.variants(pid)
                labels = {slide["id"]: re.sub(r"\s*\{#[^}]+\}\s*$", "", slide["source"].splitlines()[0][3:]) for slide in slide_parts}
                for info in result["variants"].get("migration", {}).get("slides", []):
                    if info.get("source_title") and info.get("id") in labels:
                        labels[info["id"]] = str(info["source_title"])
                result["slideLabels"] = labels
                result["slideDescriptions"] = self.slide_descriptions(pid)
                result["slides"] = result["allSlides"]
                result["sources"] = {"pt-BR": pt, "en": en}
            return result
