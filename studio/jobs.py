from __future__ import annotations

import logging
import time
from threading import Event, RLock, Thread
from uuid import uuid4
from typing import Any, Callable

from .openrouter import EditCancelled

LOGGER = logging.getLogger("studio.ai")


class AIJobs:
    def __init__(self) -> None:
        self.lock = RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active: str | None = None

    def start(self, operation: Callable[[Event], dict[str, Any]]) -> str:
        with self.lock:
            if self.active is not None:
                raise ValueError("An AI request is already running")
            job_id = uuid4().hex
            cancelled = Event()
            job: dict[str, Any] = {"id": job_id, "status": "running", "error": "", "result": {}, "cancelled": cancelled}
            self.jobs[job_id] = job
            self.active = job_id

            def run() -> None:
                started = time.monotonic()
                try:
                    result = operation(cancelled)
                    with self.lock:
                        job["status"] = "cancelled" if cancelled.is_set() else "complete"
                        job["result"] = {} if cancelled.is_set() else result
                    LOGGER.info("AI request finished: job=%s, status=%s, elapsed=%.1fs", job_id[:8], job["status"], time.monotonic() - started)
                except EditCancelled:
                    with self.lock:
                        job["status"] = "cancelled"
                    LOGGER.info("AI request cancelled: job=%s, elapsed=%.1fs", job_id[:8], time.monotonic() - started)
                except Exception as exc:
                    LOGGER.error("AI request failed: job=%s, elapsed=%.1fs, error_type=%s, message=%s", job_id[:8], time.monotonic() - started, type(exc).__name__, str(exc))
                    LOGGER.debug("AI edit failure traceback", exc_info=True)
                    with self.lock:
                        job["status"] = "cancelled" if cancelled.is_set() else "failed"
                        job["error"] = "" if cancelled.is_set() else str(exc)
                finally:
                    with self.lock:
                        if self.active == job_id:
                            self.active = None

            Thread(target=run, name="studio-ai-request", daemon=True).start()
            if len(self.jobs) > 30:
                for stale in list(self.jobs):
                    if stale != self.active and self.jobs[stale]["status"] not in ("running", "stopping"):
                        del self.jobs[stale]
                    if len(self.jobs) <= 20:
                        break
            return job_id

    def status(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("Unknown AI request")
            job = self.jobs[job_id]
            return {key: job[key] for key in ("id", "status", "error", "result")}

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("Unknown AI request")
            job = self.jobs[job_id]
            if job["status"] == "running":
                job["status"] = "stopping"
                job["cancelled"].set()
            return self.status(job_id)
