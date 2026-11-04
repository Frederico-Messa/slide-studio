from __future__ import annotations

import copy
import re
from typing import Any

from .project import SLUG


def canvas_size(source: str) -> tuple[int, int]:
    width = re.search(r"(?m)^    width:\s*(\d+)", source)
    height = re.search(r"(?m)^    height:\s*(\d+)", source)
    return int(width.group(1)) if width else 1280, int(height.group(1)) if height else 720


def default_variants(width: int = 1280, height: int = 720) -> dict[str, Any]:
    return {"default": "standard", "variants": {"standard": {"name": "Standard", "description": "", "width": width, "height": height, "hidden_slides": []}}}


def normalize_variants(data: dict[str, Any], slide_ids: list[str]) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("variants"), dict) or not data["variants"]:
        raise ValueError("A presentation requires at least one variant")
    variants = data["variants"]
    if len(variants) > 200:
        raise ValueError("Maximum 30 variants per presentation")
    if data.get("default") not in variants:
        raise ValueError("Default variant does not exist")
    result = copy.deepcopy(data)
    for key, variant in variants.items():
        if not isinstance(key, str) or not SLUG.fullmatch(key) or not isinstance(variant, dict):
            raise ValueError("Invalid variant identifier")
        if not isinstance(variant.get("name"), str) or not 1 <= len(variant["name"].strip()) <= 80:
            raise ValueError("Variant name must have 1–80 characters")
        if not isinstance(variant.get("description"), str) or len(variant["description"]) > 2000:
            raise ValueError("Invalid variant description")
        for dimension in ("width", "height"):
            value = variant.get(dimension)
            if type(value) is not int or not 320 <= value <= 8192:
                raise ValueError("Variant dimensions must be between 320 and 8192 pixels")
        hidden = variant.get("hidden_slides", [])
        if not isinstance(hidden, list) or any(not isinstance(item, str) for item in hidden):
            raise ValueError("Invalid hidden slide list")
        result["variants"][key]["hidden_slides"] = [item for item in slide_ids if item in hidden]
        if len(result["variants"][key]["hidden_slides"]) == len(slide_ids):
            raise ValueError("At least one slide must be visible")
    return result


def displayed_slides(slide_ids: list[str], data: dict[str, Any], variant_id: str) -> list[str]:
    if variant_id not in data["variants"]:
        raise ValueError("Variant not found")
    hidden = set(data["variants"][variant_id]["hidden_slides"])
    return [slide_id for slide_id in slide_ids if slide_id not in hidden]
