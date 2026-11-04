from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
SLIDE = re.compile(r"(?m)^## [^\n]*?\{#([a-z][a-z0-9_-]*)\}[ \t]*$")
LANGUAGES = ("pt-BR", "en")
MAX_HISTORY = 100


def validate_folder(name: str) -> str:
    if not isinstance(name, str) or len(name) > 220 or not name or any(not component or component in (".", "..") or len(component) > 60 or any(char in component for char in "\\{}:\r\n") for component in name.split("/")):
        raise ValueError("Invalid category path")
    return name


def validate_asset_alias(alias: str) -> str:
    if not isinstance(alias, str):
        raise ValueError("Invalid asset identifier")
    folder, separator, basename = alias.rpartition("/")
    if separator:
        validate_folder(folder)
    if not SLUG.fullmatch(basename):
        raise ValueError("Asset basename must be a lowercase identifier")
    return alias

YAML_HEADER = """---
format:
  revealjs:
    theme: simple
    css: theme.css
    slide-level: 2
    slide-number: c/t
    transition: none
    controls: false
    hash: true
    pdf-separate-fragments: false
execute:
  enabled: false
---

"""


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(fallback)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid JSON object: {path.name}")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def split_qmd(text: str) -> tuple[str, list[dict[str, str]]]:
    if not text.startswith("---\n"):
        raise ValueError("Presentation is missing its YAML header")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Presentation has an invalid YAML header")
    prefix = text[:end + 5]
    body = text[end + 5:].strip()
    matches = list(SLIDE.finditer(body))
    if not matches or body[:matches[0].start()].strip():
        raise ValueError("Presentation must contain slides with '## Title {#slide-id}' headings")
    slides = []
    for index, match in enumerate(matches):
        finish = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        slides.append({"id": match.group(1), "source": body[match.start():finish].strip()})
    ids = [slide["id"] for slide in slides]
    if len(set(ids)) != len(ids):
        raise ValueError("Slide identifiers must be unique")
    return prefix, slides


def validate_bilingual_sources(pt: str, en: str) -> list[str]:
    _, pt_slides = split_qmd(pt)
    _, en_slides = split_qmd(en)
    pt_ids = [slide["id"] for slide in pt_slides]
    en_ids = [slide["id"] for slide in en_slides]
    if pt_ids != en_ids:
        raise ValueError("PT-BR and EN must have identical slide identifiers in the same order")
    return pt_ids


