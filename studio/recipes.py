from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .project import Project, SLUG, save_json

MAX_INSTRUCTIONS = 2_000_000


def validate_recipe_id(identifier: str) -> str:
    if not isinstance(identifier, str) or not SLUG.fullmatch(identifier):
        raise ValueError('Recipe identifier must start with a lowercase letter and contain only lowercase letters, digits, _ or -')
    return identifier


def validate_recipe_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    if not isinstance(metadata, dict) or set(metadata) - {'name', 'description'}:
        raise ValueError('Invalid recipe metadata')
    name = metadata.get('name', '')
    description = metadata.get('description', '')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError('Invalid recipe name')
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError('Invalid recipe description')
    return {'name': name.strip(), 'description': description}


def validate_recipe_instructions(instructions: str) -> str:
    if not isinstance(instructions, str) or not instructions.strip() or len(instructions) > MAX_INSTRUCTIONS or '\x00' in instructions:
        raise ValueError('Invalid recipe instructions')
    return instructions


def list_recipes(project: Project) -> list[dict[str, str]]:
    directory = project.current / 'recipes'
    result: list[dict[str, str]] = []
    if not directory.exists():
        return result
    for path in sorted(directory.iterdir()):
        if not path.is_dir() or not SLUG.fullmatch(path.name) or not (path / 'recipe.json').is_file() or not (path / 'instructions.md').is_file():
            continue
        metadata = validate_recipe_metadata(json.loads((path / 'recipe.json').read_text(encoding='utf-8')))
        result.append({'id': path.name, **metadata})
    return result


def get_recipe(project: Project, identifier: str) -> dict[str, str]:
    validate_recipe_id(identifier)
    directory = project.current / 'recipes' / identifier
    if not (directory / 'recipe.json').is_file() or not (directory / 'instructions.md').is_file():
        raise ValueError('Recipe not found')
    metadata = validate_recipe_metadata(json.loads((directory / 'recipe.json').read_text(encoding='utf-8')))
    instructions = validate_recipe_instructions((directory / 'instructions.md').read_text(encoding='utf-8'))
    return {'id': identifier, **metadata, 'instructions': instructions}


def update_recipe(project: Project, identifier: str, metadata: dict[str, Any], instructions: str, previous: str | None = None) -> None:
    validate_recipe_id(identifier)
    if previous is not None:
        validate_recipe_id(previous)
    validated = validate_recipe_metadata(metadata)
    instructions = validate_recipe_instructions(instructions)
    with project.lock:
        def operation() -> None:
            directory = project.current / 'recipes'
            directory.mkdir(exist_ok=True)
            destination = directory / identifier
            if previous and previous != identifier:
                former = directory / previous
                if not former.is_dir() or destination.exists():
                    raise ValueError('Recipe not found or destination already exists')
                former.rename(destination)
            elif previous and not destination.is_dir():
                raise ValueError('Recipe not found')
            elif not previous and destination.exists():
                raise ValueError('Recipe already exists')
            destination.mkdir(exist_ok=True)
            save_json(destination / 'recipe.json', validated)
            (destination / 'instructions.md').write_text(instructions, encoding='utf-8')
        project._mutate(operation)


def remove_recipe(project: Project, identifier: str) -> None:
    validate_recipe_id(identifier)
    with project.lock:
        def operation() -> None:
            directory = project.current / 'recipes' / identifier
            if not (directory / 'recipe.json').is_file():
                raise ValueError('Recipe not found')
            shutil.rmtree(directory)
        project._mutate(operation)
