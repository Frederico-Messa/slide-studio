from __future__ import annotations

import tempfile
import contextlib
import io
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from studio.jobs import AIJobs
from studio.openrouter import OpenRouter


class LoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.router = OpenRouter(Path(self.temporary.name))
        self.router.update(key="my-example-api-key")

    def test_streaming_has_no_overall_timeout_and_redacts_key_from_logs(self) -> None:
        receiver = Mock()
        receiver.poll.return_value = True
        receiver.recv.side_effect = [("reasoning", "Working"), ("content", 5), ("complete", {"choices": [{"message": {"content": "hello"}}]})]
        worker = Mock()
        worker.is_alive.return_value = True
        context = Mock()
        context.Pipe.return_value = (receiver, Mock())
        context.Process.return_value = worker
        payload = {"model": "provider/test", "messages": [{"role": "system", "content": "hello"}, {"role": "user", "content": "hello world"}]}
        with patch("studio.openrouter.multiprocessing.get_context", return_value=context):
            with self.assertLogs("studio.openrouter", level="INFO") as log, contextlib.redirect_stdout(io.StringIO()) as stream:
                result = self.router.completion(payload, Event())
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")
        self.assertIn("Working", stream.getvalue())
        self.assertIn("OpenRouter streaming request", "\n".join(log.output))
        self.assertNotIn("my-example-api-key", "\n".join(log.output))
        receiver.close.assert_called_once()

    def test_job_failure_is_logged_with_elapsed_time(self) -> None:
        jobs = AIJobs()

        def fail(cancelled: Event) -> dict[str, object]:
            raise ValueError("The provider declined the request")

        with self.assertLogs("studio.ai", level="ERROR") as log:
            job_id = jobs.start(fail)
            for attempt in range(100):
                if jobs.status(job_id)["status"] == "failed":
                    break
                time.sleep(0.01)
        self.assertEqual(jobs.status(job_id)["status"], "failed")
        self.assertIn("ValueError", "\n".join(log.output))
        self.assertIn("elapsed=", "\n".join(log.output))


if __name__ == "__main__":
    unittest.main()
