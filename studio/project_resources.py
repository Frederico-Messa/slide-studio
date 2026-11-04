from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from .project_shared import LANGUAGES, SLUG, load_json, save_json, split_qmd, validate_asset_alias, validate_folder


class ResourceMethods:
    def usage(self) -> dict[str, dict[str, list[str]]]:
        from .render import FACT_REF, ASSET_REF
        facts: dict[str, set[str]] = {}
        assets: dict[str, set[str]] = {}
        for presentation in self.presentations():
            pid = presentation["id"]
            for source in self.sources(pid):
                for match in FACT_REF.finditer(source):
                    facts.setdefault(f"{match.group(1)}.{match.group(2)}", set()).add(pid)
                for match in ASSET_REF.finditer(source):
                    assets.setdefault(match.group(1), set()).add(pid)
        return {"facts": {key: sorted(values) for key, values in facts.items()}, "assets": {key: sorted(values) for key, values in assets.items()}}

    def slide_resources(self, pid: str, slide_id: str) -> dict[str, list[dict[str, Any]]]:
        from .render import FACT_REF, ASSET_REF
        with self.lock:
            sources = self.sources(pid)
            facts = self.facts()["categories"]
            assets = self.assets()["assets"]
            references: dict[str, dict[str, set[str]]] = {"facts": {}, "assets": {}}
            for language, source in zip(LANGUAGES, sources):
                slides = {slide["id"]: slide["source"] for slide in split_qmd(source)[1]}
                if slide_id not in slides:
                    raise ValueError("Slide not found")
                text = slides[slide_id]
                for match in FACT_REF.finditer(text):
                    references["facts"].setdefault(f"{match.group(1)}.{match.group(2)}", set()).add(language)
                for match in ASSET_REF.finditer(text):
                    references["assets"].setdefault(match.group(1), set()).add(language)
            result: dict[str, list[dict[str, Any]]] = {"facts": [], "assets": []}
            for identifier, languages in sorted(references["facts"].items()):
                category, key = identifier.rsplit(".", 1)
                result["facts"].append({"id": identifier, "languages": sorted(languages), "metadata": facts.get(category, {}).get(key)})
            for identifier, languages in sorted(references["assets"].items()):
                result["assets"].append({"id": identifier, "languages": sorted(languages), "metadata": assets.get(identifier)})
            return result

    def usages(self, kind: str, identifier: str) -> list[dict[str, str]]:
        from .render import FACT_REF, ASSET_REF
        if kind not in ("facts", "assets"):
            raise ValueError("Unknown resource type")
        references: list[dict[str, str]] = []
        with self.lock:
            for presentation in self.presentations():
                for language, source in zip(LANGUAGES, self.sources(presentation["id"])):
                    for slide in split_qmd(source)[1]:
                        matches = FACT_REF.finditer(slide["source"]) if kind == "facts" else ASSET_REF.finditer(slide["source"])
                        for match in matches:
                            alias = f"{match.group(1)}.{match.group(2)}" if kind == "facts" else match.group(1)
                            if alias == identifier:
                                references.append({"presentation": presentation["id"], "name": presentation["name"], "language": language, "slide": slide["id"]})
        return references

    def facts(self) -> dict[str, Any]:
        return load_json(self.current / "facts.json", {"categories": {}})

    def assets(self) -> dict[str, Any]:
        return load_json(self.current / "assets.json", {"assets": {}, "folders": []})

    def asset_state(self) -> dict[str, Any]:
        data = self.assets()
        for asset in data.get("assets", {}).values():
            file = (self.current / str(asset.get("file", ""))).resolve()
            asset["bytes"] = file.stat().st_size if file.is_relative_to(self.current.resolve()) and file.is_file() else 0
            from .images import image_dimensions
            asset["width"], asset["height"] = image_dimensions(file) if asset["bytes"] else (None, None)
        return data

    def set_fact(self, category: str, key: str, value: str, updated: str | None, description: str) -> None:
        category = category.strip()
        if not 1 <= len(category) <= 60 or not SLUG.fullmatch(key):
            raise ValueError("Provide a category and a lowercase identifier")
        if updated:
            date.fromisoformat(updated)
        def operation() -> None:
            facts = self.facts()
            facts["categories"].setdefault(category, {})[key] = {"value": value, "updated": updated or None, "description": description}
            save_json(self.current / "facts.json", facts)
        with self.lock:
            self._mutate(operation)

    def remove_fact(self, category: str, key: str) -> None:
        def operation() -> None:
            facts = self.facts()
            del facts["categories"][category][key]
            save_json(self.current / "facts.json", facts)
        with self.lock:
            self._mutate(operation)

    def set_asset(self, alias: str, filename: str, content: bytes, description: str, category: str = "General", added: str | None = None) -> None:
        category = category.strip()
        if category:
            validate_folder(category)
        validate_asset_alias(alias)
        if "/" in alias and alias.rpartition("/")[0] != category:
            raise ValueError("Asset category must agree with identifier path")
        if added:
            date.fromisoformat(added)
        extension = Path(filename).suffix.lower()
        if extension not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
            raise ValueError("Supported images: PNG, JPEG, WebP, GIF, SVG")
        if not content or len(content) > 12 * 1024 * 1024:
            raise ValueError("Image must be between 1 byte and 12 MB")

        def operation() -> None:
            data = self.assets()
            old = data["assets"].get(alias)
            relative = f"assets/{uuid4().hex[:16]}{extension}"
            path = self.current / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            data["assets"][alias] = {
                "file": relative, "description": description, "category": category,
                "added": (added or None) if added is not None else (old.get("added") if old else date.today().isoformat()),
                "updated": date.today().isoformat()
            }
            if old and not any(x.get("file") == old["file"] for name, x in data["assets"].items() if name != alias):
                (self.current / old["file"]).unlink(missing_ok=True)
            save_json(self.current / "assets.json", data)
        with self.lock:
            self._mutate(operation)

    def set_asset_description(self, alias: str, description: str, category: str | None = None, added: str | None = None) -> None:
        if category is not None:
            if category.strip():
                validate_folder(category.strip())
        if added:
            date.fromisoformat(added)
        def operation() -> None:
            data = self.assets()
            entry = data["assets"][alias]
            entry["description"] = description
            if category is not None:
                if "/" in alias and alias.rpartition("/")[0] != category.strip():
                    raise ValueError("Use Move to change an asset category")
                entry["category"] = category.strip()
            if added is not None:
                entry["added"] = added or None
            save_json(self.current / "assets.json", data)
        with self.lock:
            self._mutate(operation)

    def _rewrite_references(self, replacements: dict[str, str]) -> None:
        if not replacements:
            return
        pattern = re.compile("|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True)))
        for presentation in self.presentations():
            folder = self.presentation_path(presentation["id"])
            for language in LANGUAGES:
                path = folder / f"{language}.qmd"
                source = path.read_text(encoding="utf-8")
                new_source = pattern.sub(lambda match: replacements[match.group()], source)
                if source != new_source:
                    path.write_text(new_source, encoding="utf-8")

    def set_facts_batch(self, category: str, changes: list[dict[str, str]]) -> None:
        if not isinstance(changes, list) or not changes or len(changes) > 1000:
            raise ValueError("Provide 1–1000 fact edits")
        with self.lock:
            def operation() -> None:
                data = self.facts()
                entries = data["categories"].get(category)
                if entries is None:
                    raise ValueError("Fact category not found")
                edits = dict[str, tuple[str, dict[str, Any]]]()
                for item in changes:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid fact edit")
                    key = item.get("key")
                    new_key = item.get("newKey", key)
                    if not isinstance(key, str) or key not in entries or key in edits:
                        raise ValueError(f"Fact not found or repeated: {key}")
                    if not isinstance(new_key, str) or not SLUG.fullmatch(new_key):
                        raise ValueError(f"Invalid fact identifier: {new_key}")
                    updated = item.get("updated") or None
                    if updated:
                        date.fromisoformat(updated)
                    edits[key] = (new_key, {"value": str(item.get("value", "")), "updated": updated, "description": str(item.get("description", ""))})
                remaining = {key: value for key, value in entries.items() if key not in edits}
                target_keys = [new_key for new_key, _ in edits.values()]
                if len(target_keys) != len(set(target_keys)) or any(key in remaining for key in target_keys):
                    raise ValueError("Duplicate fact identifier")
                for new_key, value in edits.values():
                    remaining[new_key] = value
                references = {f"{{{{fact:{category}.{old}}}}}": f"{{{{fact:{category}.{new}}}}}" for old, (new, _) in edits.items() if old != new}
                self._rewrite_references(references)
                data["categories"][category] = remaining
                save_json(self.current / "facts.json", data)
            self._mutate(operation)

    def create_asset_folder(self, folder: str) -> None:
        validate_folder(folder)
        with self.lock:
            def operation() -> None:
                data = self.assets()
                existing = set(data.get("folders", []))
                parts = folder.split("/")
                for index in range(1, len(parts) + 1):
                    existing.add("/".join(parts[:index]))
                data["folders"] = sorted(existing)
                save_json(self.current / "assets.json", data)
            self._mutate(operation)

    def edit_asset(self, alias: str, destination: str, description: str, added: str | None, filename: str = "", content: bytes | None = None) -> None:
        validate_asset_alias(destination)
        if added:
            date.fromisoformat(added)
        if content is not None:
            extension = Path(filename).suffix.lower()
            if extension not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg") or not 0 < len(content) <= 12 * 1024 * 1024:
                raise ValueError("Invalid image or image size")
        with self.lock:
            def operation() -> None:
                data = self.assets()
                assets = data["assets"]
                if alias not in assets:
                    raise ValueError("Asset not found")
                if destination != alias and destination in assets:
                    raise ValueError("Destination already exists")
                entry = dict(assets[alias])
                old_file = entry["file"]
                entry.update({"category": destination.rpartition("/")[0], "description": description, "added": added or None})
                if content is not None:
                    relative = f"assets/{uuid4().hex[:16]}{Path(filename).suffix.lower()}"
                    file_path = self.current / relative
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(content)
                    entry["file"] = relative
                    entry["updated"] = date.today().isoformat()
                del assets[alias]
                assets[destination] = entry
                parts = entry["category"].split("/") if entry["category"] else []
                folders = set(data.get("folders", []))
                folders.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
                data["folders"] = sorted(folders)
                if alias != destination:
                    self._rewrite_references({f"{{{{asset:{alias}}}}}": f"{{{{asset:{destination}}}}}"})
                if content is not None and not any(item.get("file") == old_file for item in assets.values()):
                    (self.current / old_file).unlink(missing_ok=True)
                save_json(self.current / "assets.json", data)
            self._mutate(operation)

    def move_assets(self, moves: dict[str, str]) -> None:
        if not isinstance(moves, dict) or not moves:
            raise ValueError("Select assets to move or rename")
        if len(moves) > 1000:
            raise ValueError("Too many assets selected")
        for new_alias in moves.values():
            validate_asset_alias(new_alias)
        if len(set(moves.values())) != len(moves):
            raise ValueError("Multiple assets cannot have the same destination")
        with self.lock:
            def operation() -> None:
                data = self.assets()
                assets = data["assets"]
                if any(old not in assets for old in moves):
                    raise ValueError("Asset not found")
                if any(new in assets and new not in moves for new in moves.values()):
                    raise ValueError("Destination asset already exists")
                changed = {new: {**assets[old], "category": new.rpartition("/")[0]} for old, new in moves.items()}
                for old in moves:
                    del assets[old]
                assets.update(changed)
                folders = set(data.get("folders", []))
                for new in moves.values():
                    folder = new.rpartition("/")[0]
                    parts = folder.split("/") if folder else []
                    folders.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
                data["folders"] = sorted(folders)
                self._rewrite_references({f"{{{{asset:{old}}}}}": f"{{{{asset:{new}}}}}" for old, new in moves.items()})
                save_json(self.current / "assets.json", data)
            self._mutate(operation)

    def move_asset_folder(self, old: str, new: str) -> None:
        validate_folder(old)
        validate_folder(new)
        if new == old or new.startswith(old + "/"):
            raise ValueError("Cannot move a folder inside itself")
        with self.lock:
            def operation() -> None:
                data = self.assets()
                folders = set(data.get("folders", []))
                aliases = data["assets"]
                if old not in folders and not any(key.startswith(old + "/") for key in aliases):
                    raise ValueError("Folder not found")
                moving = {alias: new + alias[len(old):] for alias in aliases if alias.startswith(old + "/")}
                if any(target in aliases and target not in moving for target in moving.values()):
                    raise ValueError("Destination already contains an asset with that name")
                if any(folder == new or folder.startswith(new + "/") for folder in folders if not (folder == old or folder.startswith(old + "/"))):
                    raise ValueError("Destination folder already exists")
                relocated = {target: {**aliases[alias], "category": target.rsplit("/", 1)[0]} for alias, target in moving.items()}
                for alias in moving:
                    del aliases[alias]
                aliases.update(relocated)
                folders = {new + folder[len(old):] if folder == old or folder.startswith(old + "/") else folder for folder in folders}
                parts = new.split("/")
                folders.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
                data["folders"] = sorted(folders)
                self._rewrite_references({f"{{{{asset:{alias}}}}}": f"{{{{asset:{target}}}}}" for alias, target in moving.items()})
                save_json(self.current / "assets.json", data)
            self._mutate(operation)

    def duplicate_asset(self, alias: str, destination: str) -> None:
        validate_asset_alias(destination)
        with self.lock:
            def operation() -> None:
                data = self.assets()
                assets = data["assets"]
                if alias not in assets:
                    raise ValueError("Source asset not found")
                if destination in assets:
                    raise ValueError("Destination asset already exists")
                source = assets[alias]
                source_file = (self.current / source["file"]).resolve()
                if not source_file.is_relative_to(self.current.resolve()) or not source_file.is_file():
                    raise ValueError("Invalid source asset file")
                extension = source_file.suffix.lower()
                relative = f"assets/{uuid4().hex[:16]}{extension}"
                target = self.current / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target)
                assets[destination] = {**source, "file": relative, "category": destination.rpartition("/")[0], "added": date.today().isoformat(), "updated": date.today().isoformat()}
                folder = destination.rpartition("/")[0]
                folders = set(data.get("folders", []))
                if folder:
                    parts = folder.split("/")
                    folders.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
                data["folders"] = sorted(folders)
                save_json(self.current / "assets.json", data)
            self._mutate(operation)

    def remove_asset_folder(self, folder: str) -> None:
        validate_folder(folder)
        with self.lock:
            def operation() -> None:
                data = self.assets()
                folders = set(data.get("folders", []))
                if folder not in folders and not any(alias.startswith(folder + "/") for alias in data["assets"]):
                    raise ValueError("Folder not found")
                removed = [alias for alias in data["assets"] if alias.startswith(folder + "/")]
                old_files = [data["assets"].pop(alias).get("file") for alias in removed]
                data["folders"] = sorted(x for x in folders if x != folder and not x.startswith(folder + "/"))
                remaining = {entry["file"] for entry in data["assets"].values()}
                for file in old_files:
                    if file and file not in remaining:
                        (self.current / file).unlink(missing_ok=True)
                save_json(self.current / "assets.json", data)
            self._mutate(operation)

    def create_fact_category(self, category: str) -> None:
        if not 1 <= len(category.strip()) <= 60 or "." in category or "{" in category or "}" in category:
            raise ValueError("Invalid fact category")
        with self.lock:
            def operation() -> None:
                data = self.facts()
                if category in data["categories"]:
                    raise ValueError("Fact category already exists")
                data["categories"][category] = {}
                save_json(self.current / "facts.json", data)
            self._mutate(operation)

    def rename_fact(self, category: str, key: str, new_category: str, new_key: str) -> None:
        if not 1 <= len(new_category) <= 60 or "." in new_category or not SLUG.fullmatch(new_key):
            raise ValueError("Invalid fact identifier")
        with self.lock:
            def operation() -> None:
                data = self.facts()
                if key not in data["categories"].get(category, {}):
                    raise ValueError("Fact not found")
                if (category, key) == (new_category, new_key):
                    return
                if new_key in data["categories"].get(new_category, {}):
                    raise ValueError("Destination fact already exists")
                value = data["categories"][category].pop(key)
                data["categories"].setdefault(new_category, {})[new_key] = value
                self._rewrite_references({f"{{{{fact:{category}.{key}}}}}": f"{{{{fact:{new_category}.{new_key}}}}}"})
                save_json(self.current / "facts.json", data)
            self._mutate(operation)

    def move_facts(self, entries: list[dict[str, str]], target: str) -> None:
        if not isinstance(entries, list) or not 1 <= len(entries) <= 1000:
            raise ValueError("Select facts to move")
        if not isinstance(target, str):
            raise ValueError("Invalid destination table")
        with self.lock:
            def operation() -> None:
                data = self.facts()
                tables = data["categories"]
                if target not in tables:
                    raise ValueError("Destination table does not exist")
                source_keys: set[tuple[str, str]] = set()
                for entry in entries:
                    if not isinstance(entry, dict) or set(entry) != {"category", "key"}:
                        raise ValueError("Invalid fact selection")
                    category, key = entry["category"], entry["key"]
                    if not isinstance(category, str) or not isinstance(key, str):
                        raise ValueError("Invalid fact selection")
                    if category not in tables or key not in tables[category]:
                        raise ValueError("Fact not found")
                    if (category, key) in source_keys:
                        raise ValueError("Duplicate fact selection")
                    source_keys.add((category, key))
                    if category != target and key in tables[target]:
                        raise ValueError(f"Fact already exists in destination table: {key}")
                moved = [(category, key) for category, key in source_keys if category != target]
                destination_keys = [key for category, key in moved]
                if len(set(destination_keys)) != len(destination_keys):
                    raise ValueError("Multiple facts have the same destination key")
                if not moved:
                    raise ValueError("Choose a different table")
                replacements = {}
                for category, key in moved:
                    tables[target][key] = tables[category].pop(key)
                    replacements[f"{{{{fact:{category}.{key}}}}}"] = f"{{{{fact:{target}.{key}}}}}"
                self._rewrite_references(replacements)
                save_json(self.current / "facts.json", data)
            self._mutate(operation)

    def rename_fact_category(self, old: str, new: str) -> None:
        if not 1 <= len(new.strip()) <= 60 or "." in new or "{" in new or "}" in new:
            raise ValueError("Invalid fact category")
        with self.lock:
            def operation() -> None:
                data = self.facts()
                if old not in data["categories"]:
                    raise ValueError("Fact category not found")
                if new in data["categories"]:
                    raise ValueError("Destination category already exists")
                data["categories"][new] = data["categories"].pop(old)
                self._rewrite_references({f"{{{{fact:{old}.{key}}}}}": f"{{{{fact:{new}.{key}}}}}" for key in data["categories"][new]})
                save_json(self.current / "facts.json", data)
            self._mutate(operation)

    def remove_fact_category(self, category: str) -> None:
        with self.lock:
            def operation() -> None:
                data = self.facts()
                if category not in data["categories"]:
                    raise ValueError("Fact category not found")
                del data["categories"][category]
                save_json(self.current / "facts.json", data)
            self._mutate(operation)

    def remove_asset(self, alias: str) -> None:
        def operation() -> None:
            data = self.assets()
            old = data["assets"].pop(alias)
            if not any(entry["file"] == old["file"] for entry in data["assets"].values()):
                (self.current / old["file"]).unlink(missing_ok=True)
            save_json(self.current / "assets.json", data)
        with self.lock:
            self._mutate(operation)

    def remove_facts(self, entries: list[dict[str, str]]) -> None:
        if not isinstance(entries, list) or not entries:
            raise ValueError("Select at least one fact")
        if len(entries) > 1000:
            raise ValueError("Too many selected facts")
        with self.lock:
            def operation() -> None:
                facts = self.facts()
                for entry in entries:
                    if not isinstance(entry, dict) or set(entry) != {"category", "key"}:
                        raise ValueError("Invalid fact selection")
                    if entry["category"] not in facts["categories"] or entry["key"] not in facts["categories"][entry["category"]]:
                        raise ValueError("Fact not found")
                for entry in entries:
                    category, key = entry["category"], entry["key"]
                    facts["categories"][category].pop(key)
                save_json(self.current / "facts.json", facts)
            self._mutate(operation)

    def remove_assets(self, aliases: list[str]) -> None:
        if not isinstance(aliases, list) or not aliases or len(aliases) > 1000 or any(not isinstance(alias, str) for alias in aliases):
            raise ValueError("Invalid asset selection")
        with self.lock:
            def operation() -> None:
                data = self.assets()
                if any(alias not in data["assets"] for alias in aliases):
                    raise ValueError("Asset not found")
                old = [data["assets"].pop(alias) for alias in aliases]
                remaining = {entry["file"] for entry in data["assets"].values()}
                for item in old:
                    if item["file"] not in remaining:
                        (self.current / item["file"]).unlink(missing_ok=True)
                save_json(self.current / "assets.json", data)
            self._mutate(operation)

    def merge_facts(self, entries: list[dict[str, str]], survivor: dict[str, str]) -> None:
        from .operations import merge_fact_entries
        with self.lock:
            def operation() -> None:
                facts = self.facts()
                merge_fact_entries(self, facts, entries, survivor)
                save_json(self.current / "facts.json", facts)
            self._mutate(operation)

    def merge_assets(self, aliases: list[str], survivor: str) -> None:
        from .operations import merge_asset_entries
        with self.lock:
            def operation() -> None:
                assets = self.assets()
                merge_asset_entries(self, assets, aliases, survivor)
                save_json(self.current / "assets.json", assets)
            self._mutate(operation)

