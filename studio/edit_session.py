from __future__ import annotations

import tempfile
from pathlib import Path
from threading import Event
from typing import Any

from .project import Project, copy_content, replace_content, tree_digest


class EditSession:
    def __init__(self, project: Project, scope: str, baseline: str, presentation: str = '', slide: str = '', target: str = ''):
        self.project = project
        self.scope = scope
        self.baseline = baseline
        self.presentation = presentation
        self.slide = slide
        self.target = target
        self.temporary: tempfile.TemporaryDirectory[str] | None = None
        self.staged: Project | None = None
        self.revisions = 0

    def current(self) -> Project:
        return self.staged or self.project

    def verify_baseline(self) -> None:
        if tree_digest(self.project.current) != self.baseline:
            raise ValueError('Workspace changed while the AI request was running. No changes applied')

    def _ensure_staged(self) -> Project:
        if self.staged is None:
            with self.project.lock:
                self.verify_baseline()
                self.temporary = tempfile.TemporaryDirectory(prefix='studio-ai-edit-')
                try:
                    workspace = Path(self.temporary.name) / 'workspace'
                    copy_content(self.project.current, workspace)
                    self.staged = Project(workspace)
                except Exception:
                    self.temporary.cleanup()
                    self.temporary = None
                    raise
        return self.staged

    def _apply(self, destination: Project, changes: dict[str, Any]) -> None:
        from .operations import apply
        apply(destination, self.scope, self.target, changes, presentation=self.presentation, slide=self.slide)

    def apply_provisional(self, changes: dict[str, Any], cancelled: Event) -> dict[str, Any]:
        if cancelled.is_set():
            from .openrouter import EditCancelled
            raise EditCancelled('Edit cancelled')
        staged = self._ensure_staged()
        self._apply(staged, changes)
        self.revisions += 1
        differences = Project.compare_files(self.project.current, staged.current)
        return {'status': 'applied', 'revision': self.revisions, 'changed_files': [item['path'] for item in differences]}

    def finish(self, changes: dict[str, Any], cancelled: Event) -> bool:
        if cancelled.is_set():
            from .openrouter import EditCancelled
            raise EditCancelled('Edit cancelled')
        edits = changes.get('edits') if isinstance(changes, dict) and set(changes) == {'edits'} else None
        if not isinstance(edits, list) or len(edits) > 1000:
            raise ValueError('Expected a JSON object containing edit operations')
        if not edits and self.staged is None:
            raise ValueError('The model returned no edits')
        if edits and self.staged is None:
            with self.project.lock:
                self.verify_baseline()
                if cancelled.is_set():
                    from .openrouter import EditCancelled
                    raise EditCancelled('Edit cancelled')
                self._apply(self.project, changes)
            return True
        staged = self._ensure_staged()
        if edits:
            self._apply(staged, changes)
        if tree_digest(staged.current) == self.baseline:
            raise ValueError('The edit did not change the workspace')
        with self.project.lock:
            self.verify_baseline()
            if cancelled.is_set():
                from .openrouter import EditCancelled
                raise EditCancelled('Edit cancelled')
            self.project._mutate(lambda: replace_content(staged.current, self.project.current))
        return True

    def close(self) -> None:
        if self.staged is not None:
            self.staged.temporary.cleanup()
            self.staged = None
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None

    def __enter__(self) -> EditSession:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()
