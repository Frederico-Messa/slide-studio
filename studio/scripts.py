from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any

from .project import Project, SLUG, copy_content, replace_content, save_json, tree_digest

MAX_SOURCE = 2_000_000


def validate_script_id(identifier: str) -> str:
    if not isinstance(identifier, str) or not SLUG.fullmatch(identifier):
        raise ValueError("Script identifier must start with a lowercase letter and contain only lowercase letters, digits, _ or -")
    return identifier


def validate_script_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError("Script metadata must be an object")
    if set(metadata) - {"name", "description", "parameters"}:
        raise ValueError("Unknown script metadata field")
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    parameters = metadata.get("parameters", [])
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("Invalid script name")
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError("Invalid script description")
    if not isinstance(parameters, list) or len(parameters) > 30:
        raise ValueError("Invalid script settings")
    seen: set[str] = set()
    normalized = []
    for item in parameters:
        if not isinstance(item, dict) or set(item) - {"name", "label", "type", "default", "required"}:
            raise ValueError("Invalid script parameter")
        identifier = validate_script_id(item.get("name"))
        if identifier in seen or item.get("type", "text") not in ("text", "number", "boolean"):
            raise ValueError("Duplicate or unsupported script parameter")
        seen.add(identifier)
        label = item.get("label", identifier)
        if not isinstance(label, str) or len(label) > 100 or type(item.get("required", False)) is not bool:
            raise ValueError("Invalid script parameter label or requirement")
        default = item.get("default")
        if default is not None and not isinstance(default, (str, int, float, bool)):
            raise ValueError("Invalid parameter default")
        normalized.append({"name": identifier, "label": label, "type": item.get("type", "text"), "default": default, "required": item.get("required", False)})
    return {"name": name.strip(), "description": description, "parameters": normalized}


def list_scripts(project: Project) -> list[dict[str, Any]]:
    directory = project.current / "scripts"
    result = []
    if not directory.exists():
        return result
    for path in sorted(directory.iterdir()):
        if not path.is_dir() or not SLUG.fullmatch(path.name) or not (path / "script.json").is_file() or not (path / "main.py").is_file():
            continue
        metadata = json.loads((path / "script.json").read_text(encoding="utf-8"))
        result.append({"id": path.name, **validate_script_metadata(metadata)})
    return result


def get_script(project: Project, identifier: str) -> dict[str, Any]:
    validate_script_id(identifier)
    folder = project.current / "scripts" / identifier
    if not (folder / "script.json").is_file() or not (folder / "main.py").is_file():
        raise ValueError("Script not found")
    metadata = validate_script_metadata(json.loads((folder / "script.json").read_text(encoding="utf-8")))
    return {"id": identifier, **metadata, "source": (folder / "main.py").read_text(encoding="utf-8")}


def update_script(project: Project, identifier: str, metadata: dict[str, Any], source: str, previous: str | None = None) -> None:
    validate_script_id(identifier)
    if previous is not None:
        validate_script_id(previous)
    metadata = validate_script_metadata(metadata)
    if not isinstance(source, str) or len(source) > MAX_SOURCE or "\x00" in source:
        raise ValueError("Invalid script source")
    with project.lock:
        def operation() -> None:
            directory = project.current / "scripts"
            directory.mkdir(exist_ok=True)
            destination = directory / identifier
            if previous and previous != identifier:
                old = directory / previous
                if not old.is_dir() or destination.exists():
                    raise ValueError("Script not found or destination already exists")
                old.rename(destination)
            elif not previous and destination.exists():
                raise ValueError("Script already exists")
            elif previous and not destination.is_dir():
                raise ValueError("Script not found")
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "main.py").write_text(source, encoding="utf-8")
            save_json(destination / "script.json", metadata)
        project._mutate(operation)


def remove_script(project: Project, identifier: str) -> None:
    validate_script_id(identifier)
    with project.lock:
        def operation() -> None:
            folder = project.current / "scripts" / identifier
            if not (folder / "script.json").is_file():
                raise ValueError("Script not found")
            import shutil
            shutil.rmtree(folder)
        project._mutate(operation)


def validate_parameters(metadata: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ValueError("Script parameters must be an object")
    definitions = {item["name"]: item for item in metadata["parameters"]}
    if set(values) - set(definitions):
        raise ValueError("Unknown script parameter")
    result = {}
    for name, item in definitions.items():
        value = values.get(name, item["default"])
        if item["required"] and value in (None, ""):
            raise ValueError(f"Required parameter: {name}")
        if value is None:
            continue
        kind = item["type"]
        if kind == "boolean" and type(value) is not bool:
            raise ValueError(f"Expected a boolean for {name}")
        if kind == "number" and (type(value) not in (int, float) or not -1e100 < value < 1e100):
            raise ValueError(f"Expected a finite number for {name}")
        if kind == "text" and (not isinstance(value, str) or len(value) > 10000):
            raise ValueError(f"Invalid text parameter {name}")
        result[name] = value
    return result


class ScriptJobs:
    def __init__(self, project: Project):
        self.project = project
        self.lock = RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active: str | None = None

    def start(self, identifier: str, parameters: dict[str, Any]) -> str:
        from uuid import uuid4
        with self.lock, self.project.lock:
            if self.active is not None:
                raise ValueError("A script is already running")
            script = get_script(self.project, identifier)
            values = validate_parameters(script, parameters)
            baseline = tree_digest(self.project.current)
            job_id = uuid4().hex
            job: dict[str, Any] = {"id": job_id, "status": "running", "output": "", "error": "", "changed": [], "cancel": Event()}
            self.jobs[job_id] = job
            self.active = job_id

        def worker() -> None:
            import shutil
            temporary = Path(tempfile.mkdtemp(prefix="studio-script-"))
            process: subprocess.Popen[bytes] | None = None
            try:
                sandbox = temporary / "workspace"
                with self.project.lock:
                    if tree_digest(self.project.current) != baseline:
                        raise ValueError("Workspace changed before script execution")
                    copy_content(self.project.current, sandbox)
                log_path = temporary / "output.log"
                environment = {**os.environ, "SLIDE_STUDIO_WORKSPACE": str(sandbox), "SLIDE_STUDIO_PARAMETERS": json.dumps(values, ensure_ascii=False), "PYTHONDONTWRITEBYTECODE": "1"}
                environment.pop("OPENROUTER_API_KEY", None)
                with log_path.open("wb") as output:
                    process = subprocess.Popen([sys.executable, "-u", str(sandbox / "scripts" / identifier / "main.py")], cwd=sandbox, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, start_new_session=(os.name == "posix"))
                    while process.poll() is None:
                        if job["cancel"].is_set():
                            if os.name == "posix":
                                os.killpg(process.pid, signal.SIGTERM)
                            else:
                                process.terminate()
                            try:
                                process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                if os.name == "posix":
                                    os.killpg(process.pid, signal.SIGKILL)
                                else:
                                    process.kill()
                            break
                        with self.lock:
                            job["output"] = log_path.read_bytes()[-100_000:].decode("utf-8", "replace")
                        time.sleep(0.15)
                with self.lock:
                    job["output"] = log_path.read_bytes()[-100_000:].decode("utf-8", "replace")
                if job["cancel"].is_set():
                    job["status"] = "cancelled"
                    return
                if process.returncode != 0:
                    raise ValueError(f"Script exited with code {process.returncode}")
                with self.project.lock:
                    if tree_digest(self.project.current) != baseline:
                        raise ValueError("Workspace changed while the script was running; no changes applied")
                    before = Project.compare_files(self.project.current, sandbox)
                    if before:
                        self.project._mutate(lambda: replace_content(sandbox, self.project.current))
                    with self.lock:
                        job["changed"] = [item["path"] for item in before]
                with self.lock:
                    job["status"] = "complete"
            except Exception as exc:
                with self.lock:
                    job["status"] = "cancelled" if job["cancel"].is_set() else "failed"
                    job["error"] = "" if job["cancel"].is_set() else str(exc)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
                with self.lock:
                    if self.active == job_id:
                        self.active = None

        Thread(target=worker, name="studio-script", daemon=True).start()
        return job_id

    def status(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(identifier)
            if not job:
                raise ValueError("Unknown script execution")
            return {key: job[key] for key in ("id", "status", "output", "error", "changed")}

    def stop(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(identifier)
            if not job:
                raise ValueError("Unknown script execution")
            if job["status"] == "running":
                job["cancel"].set()
            return self.status(identifier)
