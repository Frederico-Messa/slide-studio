from __future__ import annotations

import copy
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from .edits import exact_replace
from .project import Project, SLUG, save_json, validate_asset_alias, validate_folder
from .scripts import MAX_SOURCE, validate_script_id, validate_script_metadata
from .recipes import validate_recipe_id, validate_recipe_metadata, validate_recipe_instructions
from .operations.merge import merge_asset_entries, merge_fact_entries

RESOURCE_SCOPES = ("fact_table", "facts", "asset_folder", "assets", "script", "scripts", "recipe", "recipes")


def apply_resource_edits(project: Project, scope: str, target: str, changes: dict[str, Any]) -> None:
    if scope not in RESOURCE_SCOPES:
        raise ValueError("Unsupported resource scope")
    if not isinstance(changes, dict) or set(changes) != {"edits"} or not isinstance(changes["edits"], list) or not 1 <= len(changes["edits"]) <= 1_000:
        raise ValueError("Expected 1–1000 edit operations")

    def check_target(identifier: str) -> None:
        if scope == "fact_table" and identifier != target:
            raise ValueError("Edit is outside the current table")
        if scope == "asset_folder" and target and identifier != target and not identifier.startswith(target + "/"):
            raise ValueError("Edit is outside the current folder")
        if scope == "script" and identifier != target:
            raise ValueError("Edit is outside the current script")
        if scope == "recipe" and identifier != target:
            raise ValueError("Edit is outside the current recipe")

    def operation() -> None:
        facts = project.facts()
        assets = project.assets()
        facts_changed = False
        assets_changed = False
        scripts_changed = False
        scripts_root = project.current / "scripts"
        recipes_root = project.current / "recipes"
        recipes_changed = False
        for index, edit in enumerate(changes["edits"], 1):
            if not isinstance(edit, dict):
                raise ValueError(f"Edit {index} must be an object")
            op = edit.get("op")
            if scope in ("fact_table", "facts"):
                if op == "merge_facts":
                    entries = edit.get("entries")
                    survivor = edit.get("survivor")
                    if scope == "fact_table" and (not isinstance(entries, list) or any(entry.get("category") != target for entry in entries if isinstance(entry, dict)) or not isinstance(survivor, dict) or survivor.get("category") != target):
                        raise ValueError("Merge is outside the current table")
                    merge_fact_entries(project, facts, entries, survivor)
                    facts_changed = True
                    continue
                category = edit.get("table")
                if not isinstance(category, str) or len(category) > 60 or not category.strip():
                    raise ValueError("Invalid fact table")
                check_target(category)
                tables = facts.setdefault("categories", {})
                if op == "rename_table":
                    destination = edit.get("new_table")
                    if not isinstance(destination, str) or not 1 <= len(destination) <= 60 or destination in tables or category not in tables:
                        raise ValueError("Invalid or existing target table")
                    tables[destination] = tables.pop(category)
                    project._rewrite_references({f"{{{{fact:{category}.{key}}}}}": f"{{{{fact:{destination}.{key}}}}}" for key in tables[destination]})
                elif op == "create_table":
                    if category in tables:
                        raise ValueError("Table already exists")
                    tables[category] = {}
                elif op == "delete_table":
                    if category not in tables:
                        raise ValueError("Table not found")
                    del tables[category]
                elif op in ("set_fact", "rename_fact", "delete_fact"):
                    key = edit.get("key")
                    if not isinstance(key, str) or not SLUG.fullmatch(key):
                        raise ValueError("Invalid fact identifier")
                    if category not in tables:
                        raise ValueError("Table not found")
                    if op == "set_fact":
                        value = edit.get("value", "")
                        description = edit.get("description", "")
                        updated = edit.get("updated")
                        if not isinstance(value, str) or not isinstance(description, str) or not (updated is None or isinstance(updated, str)):
                            raise ValueError("Invalid fact fields")
                        if updated:
                            date.fromisoformat(updated)
                        tables[category][key] = {"value": value, "updated": updated or None, "description": description}
                    elif op == "delete_fact":
                        del tables[category][key]
                    else:
                        destination = edit.get("new_key")
                        if not isinstance(destination, str) or not SLUG.fullmatch(destination) or destination in tables[category]:
                            raise ValueError("Invalid or existing destination fact")
                        tables[category][destination] = tables[category].pop(key)
                        project._rewrite_references({f"{{{{fact:{category}.{key}}}}}": f"{{{{fact:{category}.{destination}}}}}"})
                else:
                    raise ValueError(f"Unsupported fact operation: {op}")
                facts_changed = True
            elif scope in ("asset_folder", "assets"):
                if op == "merge_assets":
                    aliases = edit.get("aliases")
                    survivor = edit.get("survivor")
                    if scope == "asset_folder" and (not isinstance(aliases, list) or any(not isinstance(alias, str) or (target and not alias.startswith(target + "/")) for alias in aliases)):
                        raise ValueError("Merge is outside the current folder")
                    merge_asset_entries(project, assets, aliases, survivor)
                    assets_changed = True
                    continue
                alias = edit.get("alias")
                entries = assets.setdefault("assets", {})
                if op in ("create_folder", "delete_folder"):
                    folder = validate_folder(edit.get("folder"))
                    check_target(folder)
                    if op == "create_folder":
                        if folder in assets.get("folders", []):
                            raise ValueError("Folder already exists")
                        parts = folder.split("/")
                        assets["folders"] = sorted(set(assets.get("folders", [])) | {"/".join(parts[:i]) for i in range(1, len(parts) + 1)})
                    else:
                        if folder not in assets.get("folders", []):
                            raise ValueError("Folder not found")
                        removed = [key for key in entries if key.startswith(folder + "/")]
                        old_files = {entries.pop(key)["file"] for key in removed}
                        assets["folders"] = [item for item in assets["folders"] if item != folder and not item.startswith(folder + "/")]
                        for filename in old_files - {item["file"] for item in entries.values()}:
                            path = (project.current / filename).resolve()
                            if path.is_relative_to(project.current.resolve()):
                                path.unlink(missing_ok=True)
                    assets_changed = True
                    continue
                if op not in ("set_asset_metadata", "move_asset", "delete_asset", "use_asset_image", "copy_asset"):
                    raise ValueError(f"Unsupported asset operation: {op}")
                validate_asset_alias(alias)
                check_target(alias)
                if op == "copy_asset":
                    source_alias = edit.get("from_alias")
                    if source_alias not in entries or alias in entries:
                        raise ValueError("Invalid asset source or destination")
                    entries[alias] = {**entries[source_alias], "description":str(edit.get("description", "")), "category":alias.rpartition("/")[0], "added":date.today().isoformat(), "updated":date.today().isoformat()}
                    folder = entries[alias]["category"]
                    if folder:
                        parts = folder.split("/")
                        assets["folders"] = sorted(set(assets.get("folders", [])) | {"/".join(parts[:i]) for i in range(1,len(parts)+1)})
                    assets_changed = True
                    continue
                if alias not in entries:
                    raise ValueError(f"Asset not found: {alias}")
                if op == "set_asset_metadata":
                    if not any(key in edit for key in ("description", "added")):
                        raise ValueError("No asset metadata provided")
                    if "description" in edit:
                        if not isinstance(edit["description"], str):
                            raise ValueError("Invalid description")
                        entries[alias]["description"] = edit["description"]
                    if "added" in edit:
                        added = edit["added"]
                        if added:
                            date.fromisoformat(added)
                        entries[alias]["added"] = added or None
                elif op == "move_asset":
                    destination = validate_asset_alias(edit.get("destination"))
                    if destination in entries:
                        raise ValueError("Asset destination already exists")
                    entries[destination] = {**entries.pop(alias), "category": destination.rpartition("/")[0]}
                    parts = entries[destination]["category"].split("/") if entries[destination]["category"] else []
                    assets["folders"] = sorted(set(assets.get("folders", [])) | {"/".join(parts[:i]) for i in range(1, len(parts) + 1)})
                    project._rewrite_references({f"{{{{asset:{alias}}}}}": f"{{{{asset:{destination}}}}}"})
                elif op == "delete_asset":
                    old = entries.pop(alias)
                    if not any(item.get("file") == old.get("file") for item in entries.values()):
                        path = (project.current / old["file"]).resolve()
                        if path.is_relative_to(project.current.resolve()):
                            path.unlink(missing_ok=True)
                elif op == "use_asset_image":
                    other = edit.get("from_alias")
                    if other not in entries:
                        raise ValueError("Source image not found")
                    old = entries[alias]["file"]
                    entries[alias]["file"] = entries[other]["file"]
                    entries[alias]["updated"] = date.today().isoformat()
                    if not any(item.get("file") == old for item in entries.values()):
                        path = (project.current / old).resolve()
                        if path.is_relative_to(project.current.resolve()):
                            path.unlink(missing_ok=True)
                assets_changed = True
            elif scope in ("recipe", "recipes"):
                identifier = validate_recipe_id(edit.get("id"))
                check_target(identifier)
                folder = recipes_root / identifier
                if op == "create_recipe":
                    if folder.exists():
                        raise ValueError("Recipe already exists")
                    metadata = validate_recipe_metadata(edit.get("metadata", {}))
                    instructions = validate_recipe_instructions(edit.get("instructions"))
                    folder.mkdir(parents=True)
                    save_json(folder / "recipe.json", metadata)
                    (folder / "instructions.md").write_text(instructions, encoding="utf-8")
                elif op in ("replace_recipe_text", "replace_recipe_instructions", "set_recipe_metadata", "delete_recipe"):
                    if not (folder / "recipe.json").is_file():
                        raise ValueError("Recipe not found")
                    if op == "delete_recipe":
                        shutil.rmtree(folder)
                    elif op == "set_recipe_metadata":
                        save_json(folder / "recipe.json", validate_recipe_metadata(edit.get("metadata", {})))
                    else:
                        path = folder / "instructions.md"
                        if op == "replace_recipe_text":
                            instructions = exact_replace(path.read_text(encoding="utf-8"), edit.get("find"), edit.get("replace"), edit.get("all", False), f"recipe {identifier}")
                        else:
                            instructions = edit.get("instructions")
                        path.write_text(validate_recipe_instructions(instructions), encoding="utf-8")
                else:
                    raise ValueError(f"Unsupported recipe operation: {op}")
                recipes_changed = True
            else:
                identifier = edit.get("id")
                validate_script_id(identifier)
                check_target(identifier)
                folder = scripts_root / identifier
                if op == "create_script":
                    source = edit.get("source")
                    if folder.exists():
                        raise ValueError("Script already exists")
                    description = edit.get("description", "")
                    if not isinstance(description, str) or not isinstance(source, str) or len(source) > MAX_SOURCE or "\x00" in source:
                        raise ValueError("Invalid script source")
                    metadata = validate_script_metadata(edit.get("metadata", {}))
                    folder.mkdir(parents=True)
                    (folder / "main.py").write_text(source, encoding="utf-8")
                    save_json(folder / "script.json", metadata)
                elif op in ("replace_script_text", "replace_script_source", "set_script_metadata", "delete_script"):
                    if not (folder / "script.json").is_file():
                        raise ValueError("Script not found")
                    if op == "delete_script":
                        shutil.rmtree(folder)
                    elif op == "set_script_metadata":
                        save_json(folder / "script.json", validate_script_metadata(edit.get("metadata", {})))
                    else:
                        path = folder / "main.py"
                        source = path.read_text(encoding="utf-8")
                        if op == "replace_script_text":
                            updated = exact_replace(source, edit.get("find"), edit.get("replace"), edit.get("all", False), f"script {identifier}")
                        else:
                            updated = edit.get("source")
                        if not isinstance(updated, str) or len(updated) > MAX_SOURCE or "\x00" in updated:
                            raise ValueError("Invalid script source")
                        path.write_text(updated, encoding="utf-8")
                else:
                    raise ValueError(f"Unsupported script operation: {op}")
                scripts_changed = True
        if facts_changed:
            save_json(project.current / "facts.json", facts)
        if assets_changed:
            save_json(project.current / "assets.json", assets)
        if not any((facts_changed, assets_changed, scripts_changed, recipes_changed)):
            raise ValueError("No changes applied")

    with project.lock:
        project._mutate(operation)
