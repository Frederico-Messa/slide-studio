from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

ALLOWED = {"presentation", "variant", "slide", "language", "scope", "factCategory", "assetCategory", "theme", "chatId", "editModel", "editEffort", "chatModel", "chatEffort", "showHiddenInNavigation"}


class Preferences:
    def __init__(self, directory: Path):
        self.path = directory / "session.json"
        self.lock = RLock()
        self.values: dict[str, str] = {}
        if self.path.exists():
            content = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(content, dict):
                self.values = {key: value for key, value in content.items() if key in ALLOWED and isinstance(value, str)}

    def read(self) -> dict[str, str]:
        with self.lock:
            return self.values.copy()

    def update(self, changes: dict[str, str]) -> dict[str, str]:
        if set(changes) - ALLOWED or any(not isinstance(value, str) or len(value) > 256 for value in changes.values()):
            raise ValueError("Invalid preferences")
        if "language" in changes and changes["language"] not in ("en", "pt-BR"):
            raise ValueError("Invalid language")
        if "scope" in changes and changes["scope"] not in ("slide", "presentation", "fact_table", "facts", "asset_folder", "assets", "script", "scripts"):
            raise ValueError("Invalid scope")
        if "theme" in changes and changes["theme"] not in ("light", "dark"):
            raise ValueError("Invalid appearance")
        if "showHiddenInNavigation" in changes and changes["showHiddenInNavigation"] not in ("true", "false"):
            raise ValueError("Invalid hidden-slide navigation setting")
        if any(changes.get(key, "default") not in ("default", "none", "minimal", "low", "medium", "high", "xhigh", "max") for key in ("editEffort", "chatEffort")):
            raise ValueError("Invalid reasoning effort")
        with self.lock:
            self.values.update(changes)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.values, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
            return self.values.copy()
