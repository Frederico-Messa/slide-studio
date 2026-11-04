from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..project import LANGUAGES, Project, split_qmd
from ..scripts import get_script, list_scripts
from ..recipes import get_recipe, list_recipes


def workspace_index(project: Project) -> dict[str, Any]:
    with project.lock:
        presentations: list[dict[str, Any]] = []
        for entry in project.presentations():
            identifier = entry['id']
            variants = project.variants(identifier)
            descriptions = project.slide_descriptions(identifier)
            sources = {language: split_qmd(source)[1] for language, source in zip(LANGUAGES, project.sources(identifier))}
            slides = []
            for pt_slide, en_slide in zip(sources['pt-BR'], sources['en']):
                titles = {}
                for language, slide in (('pt-BR', pt_slide), ('en', en_slide)):
                    heading = slide['source'].splitlines()[0]
                    titles[language] = re.sub(r'\s*\{#[^}]+\}\s*$', '', heading[3:]).strip()
                slides.append({'id': pt_slide['id'], 'titles': titles, 'description': descriptions.get(pt_slide['id'], '')})
            presentations.append({
                'id': identifier, 'name': entry['name'], 'description': entry['description'],
                'default_variant': variants['default'],
                'variants': [{'id': key, 'name': variant['name'], 'description': variant['description']} for key, variant in variants['variants'].items()],
                'slides': slides,
            })
        scripts = [{'id': entry['id'], 'name': entry['name'], 'description': entry['description']} for entry in list_scripts(project)]
        recipes = [{'id': entry['id'], 'name': entry['name'], 'description': entry['description']} for entry in list_recipes(project)]
        return {'presentations': presentations, 'scripts': scripts, 'recipes': recipes}


def tool(name: str, description: str, required: dict[str, dict[str, Any]], optional: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': {**required, **(optional or {})}, 'required': list(required), 'additionalProperties': False,
    }}}


IDENTIFIER = {'type': 'string', 'description': 'Registered resource identifier, not an arbitrary filesystem path.'}
READ_TOOLS: list[dict[str, Any]] = [
    tool('list_all_facts', 'List all fact table names and fact identifiers without values or metadata.', {}),
    tool('list_all_assets', 'List all asset aliases organized by virtual folder, without image metadata or content.', {}),
    tool('read_slide_source', 'Complete Quarto source of the identified slide in both Portuguese and English.', {'presentation': IDENTIFIER, 'slide': IDENTIFIER}),
    tool('read_presentation_source', 'Complete Quarto sources of the entire presentation in both Portuguese and English. May be large; prefer individual slides when possible.', {'presentation': IDENTIFIER}),
    tool('read_slide_images', 'Rendered images of one slide in both languages, including hidden slides. Requests local rendering and sends image pixels to the model.', {'presentation': IDENTIFIER, 'slide': IDENTIFIER}, {'variant': IDENTIFIER}),
    tool('read_presentation_images', 'Rendered images of all slides in both languages, including hidden slides. Potentially large and costly.', {'presentation': IDENTIFIER}, {'variant': IDENTIFIER}),
    tool('read_facts_metadata', 'Facts and their values, descriptions and dates. Omit prefix for all; give a table name for its facts or Table.key for one fact.', {}, {'prefix': IDENTIFIER}),
    tool('read_assets_metadata', 'Asset aliases, descriptions, dates, file sizes and dimensions. Omit prefix for all; give a folder path for its descendants or an exact alias for one asset.', {}, {'prefix': IDENTIFIER}),
    tool('read_script', 'Read the complete source and metadata of a script.', {'id': IDENTIFIER}),
    tool('read_recipe', 'Read complete instructions and metadata of a recipe.', {'id': IDENTIFIER}),
    tool('read_variants', 'Read the complete variants configuration for a presentation.', {'presentation': IDENTIFIER}),
    tool('read_stylesheet', 'Read the stylesheets referenced by the presentation in both languages.', {'presentation': IDENTIFIER}),
    tool('read_workspace_diff', 'List changed workspace files, or retrieve unified text diffs for an exact file path or folder. Compares the working state with the last Save or the previous undo/redo state. Omit path to list changes first.', {}, {'against': {'type': 'string', 'enum': ['saved', 'previous'], 'description': 'Comparison baseline (default: saved).'}, 'path': {'type': 'string', 'description': 'Relative workspace file path or folder prefix, never an absolute path.'}}),
]

IMAGE_TOOLS = frozenset({'read_slide_images', 'read_presentation_images'})


def validate_read_request(name: str, args: dict[str, Any]) -> None:
    specification = next((item['function'] for item in READ_TOOLS if item['function']['name'] == name), None)
    if specification is None or not isinstance(args, dict):
        raise ValueError('Unknown retrieval operation')
    schema = specification['parameters']
    if not set(schema['required']).issubset(args) or set(args) - set(schema['properties']):
        raise ValueError('Invalid retrieval arguments')
    if any(not isinstance(value, str) or len(value) > 512 or (not value and key != 'prefix') for key, value in args.items()):
        raise ValueError('Invalid retrieval arguments')
    if name == 'read_workspace_diff':
        if args.get('against', 'saved') not in ('saved', 'previous'):
            raise ValueError('Invalid diff baseline')
        if 'path' in args:
            path = args['path']
            if path.startswith('/') or path.startswith('\\') or '\\' in path or any(component in ('', '.', '..') for component in path.rstrip('/').split('/')):
                raise ValueError('Invalid workspace-relative path')


def read_resource(project: Project, name: str, args: dict[str, Any], baseline_project: Project | None = None) -> dict[str, Any]:
    validate_read_request(name, args)
    if name in IMAGE_TOOLS:
        raise ValueError('Image retrieval requires the rendering service')
    if name == 'read_workspace_diff':
        original = baseline_project or project
        with original.lock, project.lock:
            against = args.get('against', 'saved')
            previous_root = original.workspace if against == 'saved' else original.last_state
            prefix = args.get('path')
            changes = Project.compare_files(previous_root, project.current, path_prefix=prefix, include_diff=prefix is not None) if previous_root is not None else []
            if prefix is None:
                return {'against': against, 'changed_files': [item['path'] for item in changes], 'note': 'Specify path to retrieve diff content.'}
            matches = [item for item in changes if item['path'] == prefix or item['path'].startswith(prefix.rstrip('/') + '/')]
            if not matches:
                return {'against': against, 'path': prefix, 'diffs': [], 'note': 'No changes under this path.'}
            return {'against': against, 'path': prefix, 'diffs': matches}
    with project.lock:
        if name == 'list_all_facts':
            return {'tables': {table: list(entries) for table, entries in project.facts()['categories'].items()}}
        if name == 'list_all_assets':
            registry = project.assets()
            folders: dict[str, list[str]] = {'': []}
            def register_folder(path: str) -> None:
                parts = path.split('/') if path else []
                for index in range(1, len(parts) + 1):
                    folders.setdefault('/'.join(parts[:index]), [])

            for folder in registry.get('folders', []):
                register_folder(folder)
            for alias in registry.get('assets', {}):
                parent = alias.rpartition('/')[0]
                register_folder(parent)
                folders.setdefault(parent, []).append(alias)
            return {'folders': {folder: sorted(aliases) for folder, aliases in sorted(folders.items())}}
        if name in ('read_slide_source', 'read_presentation_source', 'read_stylesheet'):
            pid = args['presentation']
            sources = dict(zip(LANGUAGES, project.sources(pid)))
            if name == 'read_slide_source':
                slides: dict[str, str] = {}
                for language, document in sources.items():
                    slide = next((item for item in split_qmd(document)[1] if item['id'] == args['slide']), None)
                    if slide is None:
                        raise ValueError(f'Slide not found in {language}')
                    slides[language] = slide['source']
                return {'presentation': pid, 'slide': args['slide'], 'sources': slides, 'description': project.slide_descriptions(pid).get(args['slide'], '')}
            if name == 'read_presentation_source':
                return {'presentation': pid, 'sources': sources}
            styles: dict[str, dict[str, str]] = {}
            for language, document in sources.items():
                match = re.search(r'(?m)^    css:\s*([^\n]+)', split_qmd(document)[0])
                path = (project.presentation_path(pid) / match.group(1).strip()).resolve() if match else (project.presentation_path(pid) / 'theme.css').resolve()
                if not path.is_relative_to(project.current.resolve()) or path.suffix != '.css' or not path.is_file():
                    raise ValueError('Stylesheet is unavailable')
                styles[language] = {'path': path.relative_to(project.current).as_posix(), 'source': path.read_text(encoding='utf-8')}
            return {'presentation': pid, 'styles': styles}
        if name == 'read_variants':
            return {'variants': project.variants(args['presentation'])}
        if name == 'read_script':
            return get_script(project, args['id'])
        if name == 'read_recipe':
            return get_recipe(project, args['id'])
        if name == 'read_facts_metadata':
            categories = project.facts()['categories']
            prefix = args.get('prefix', '')
            if not prefix:
                return {'facts': categories}
            if prefix in categories:
                return {'facts': {prefix: categories[prefix]}}
            table, separator, key = prefix.rpartition('.')
            if separator and table in categories and key in categories[table]:
                return {'facts': {table: {key: categories[table][key]}}}
            raise ValueError('Fact table or identifier not found')
        if name == 'read_assets_metadata':
            assets = project.asset_state()['assets']
            prefix = args.get('prefix', '')
            if not prefix:
                return {'assets': assets}
            if prefix in assets:
                return {'assets': {prefix: assets[prefix]}}
            selected = {alias: entry for alias, entry in assets.items() if alias.startswith(prefix.rstrip('/') + '/')}
            if not selected and prefix.rstrip('/') not in project.assets().get('folders', []):
                raise ValueError('Asset folder or identifier not found')
            return {'assets': selected}
    raise ValueError('Unknown retrieval operation')


def retrieval_reference() -> str:
    lines = ['# Read-only retrieval operations', '', 'Tools use registered identifiers except read_workspace_diff, which accepts workspace-relative paths. Slide sources and rendered images always include PT-BR and English. Retrieval does not grant edit permissions.', '']
    for item in READ_TOOLS:
        spec = item['function']
        parameters = spec['parameters']
        required = ', '.join(parameters['required']) or 'none'
        optional = ', '.join(key for key in parameters['properties'] if key not in parameters['required']) or 'none'
        lines.extend([f"## `{spec['name']}`", '', spec['description'], '', f'Required: {required}. Optional: {optional}.', ''])
    return '\n'.join(lines)


if __name__ == '__main__':
    print(retrieval_reference())
