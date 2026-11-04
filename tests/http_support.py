from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from typing import Any

from app import StudioServer


class StudioHTTPTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.temp = self.directory
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name) / 'workspace'
        self.server = StudioServer(('127.0.0.1', 0), self.workspace)
        self.addCleanup(self.server.project.temporary.cleanup)
        self.addCleanup(self.server.renderer.temp.cleanup)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, route: str, method: str = 'GET', data: dict[str, Any] | None = None, with_token: bool = True) -> Any:
        headers = {'Content-Type': 'application/json'}
        if with_token:
            headers['X-Studio-Token'] = self.server.csrf
        request = urllib.request.Request(self.base + route, method=method, headers=headers, data=None if data is None else json.dumps(data).encode())
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
