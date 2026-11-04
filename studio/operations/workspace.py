from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..project import Project, copy_content, replace_content
from .catalog import OPERATIONS


def apply_workspace_edits(project: Project, changes: dict[str, Any]) -> None:
    if not isinstance(changes, dict) or set(changes) != {'edits'} or not isinstance(changes['edits'], list) or not 1 <= len(changes['edits']) <= 1000:
        raise ValueError('Expected 1–1000 edit operations')
    from ..edits import apply_edits
    from ..resource_edits import apply_resource_edits

    with project.lock, tempfile.TemporaryDirectory(prefix='studio-recipe-edits-') as directory:
        working_directory = Path(directory) / 'workspace'
        copy_content(project.current, working_directory)
        temporary = Project(working_directory, branding=project.branding)
        try:
            groups: list[tuple[str, str, list[dict[str, Any]]]] = []
            for index, edit in enumerate(changes['edits'], 1):
                if not isinstance(edit, dict):
                    raise ValueError(f'Edit {index} must be an object')
                name = edit.get('op')
                specification = OPERATIONS.get(name)
                if specification is None:
                    raise ValueError(f'Unknown edit operation: {name}')
                scopes = specification['scopes']
                if 'presentation' in scopes or 'slide' in scopes:
                    pid = edit.get('presentation')
                    if not isinstance(pid, str) or not pid:
                        raise ValueError(f'Edit {index} must identify its presentation')
                    scope, target = 'presentation', pid
                else:
                    scope = next((kind for kind in ('facts', 'assets', 'scripts', 'recipes') if kind in scopes), None)
                    if scope is None:
                        raise ValueError(f'Unsupported recipe operation: {name}')
                    target = ''
                if groups and groups[-1][0:2] == (scope, target):
                    groups[-1][2].append(edit)
                else:
                    groups.append((scope, target, [edit]))
            for scope, target, edits in groups:
                if scope == 'presentation':
                    apply_edits(temporary, target, scope, '', {'edits': edits})
                else:
                    apply_resource_edits(temporary, scope, '', {'edits': edits})
            project._mutate(lambda: replace_content(temporary.current, project.current))
        finally:
            temporary.temporary.cleanup()
