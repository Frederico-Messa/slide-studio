from __future__ import annotations

from typing import Any


def merge_fact_entries(project: Any, facts: dict[str, Any], entries: list[dict[str, str]], survivor: dict[str, str]) -> None:
    if not isinstance(entries, list) or not 2 <= len(entries) <= 1000 or not isinstance(survivor, dict):
        raise ValueError("Select at least two facts")
    ids = [(item.get("category"), item.get("key")) for item in entries if isinstance(item, dict)]
    keep = (survivor.get("category"), survivor.get("key"))
    if len(ids) != len(entries) or len(set(ids)) != len(ids) or keep not in ids:
        raise ValueError("Invalid fact selection")
    tables = facts.get("categories", {})
    if any(key not in tables.get(category, {}) for category, key in ids):
        raise ValueError("Fact not found")
    removed = [item for item in ids if item != keep]
    project._rewrite_references({f"{{{{fact:{category}.{key}}}}}": f"{{{{fact:{keep[0]}.{keep[1]}}}}}" for category, key in removed})
    for category, key in removed:
        del tables[category][key]


def merge_asset_entries(project: Any, assets: dict[str, Any], aliases: list[str], survivor: str) -> None:
    if not isinstance(aliases, list) or not 2 <= len(aliases) <= 1000 or len(set(aliases)) != len(aliases) or survivor not in aliases:
        raise ValueError("Select at least two distinct assets and a survivor")
    entries = assets.get("assets", {})
    if any(alias not in entries for alias in aliases):
        raise ValueError("Asset not found")
    removed = [alias for alias in aliases if alias != survivor]
    old_files = [entries[alias]["file"] for alias in removed]
    project._rewrite_references({f"{{{{asset:{alias}}}}}": f"{{{{asset:{survivor}}}}}" for alias in removed})
    for alias in removed:
        del entries[alias]
    for filename in old_files:
        if not any(entry.get("file") == filename for entry in entries.values()):
            path = (project.current / filename).resolve()
            if path.is_relative_to(project.current.resolve()):
                path.unlink(missing_ok=True)
