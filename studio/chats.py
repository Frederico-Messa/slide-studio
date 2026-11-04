from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


class ChatStore:
    def __init__(self, config_root: Path):
        self.path = config_root / 'chats.json'
        self.lock = RLock()
        self.chats: dict[str, dict[str, Any]] = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and isinstance(data.get('chats'), dict):
                self.chats = data['chats']

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'chats': self.chats}, stream, ensure_ascii=False, indent=2)
        os.replace(temp, self.path)
        self.path.chmod(0o600)

    def _get(self, chat_id: str) -> dict[str, Any]:
        if chat_id not in self.chats:
            raise ValueError('Chat not found')
        return self.chats[chat_id]

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            return sorted([{'id': item['id'], 'name': item['name'], 'updated': item['updated'], 'count': len(item['messages'])} for item in self.chats.values()], key=lambda item: item['updated'], reverse=True)

    def get(self, chat_id: str) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self._get(chat_id))

    def create(self, name: str = 'Chat', source_id: str | None = None, until: int | None = None, model: str = '', effort: str = 'default') -> dict[str, Any]:
        with self.lock:
            messages = []
            if source_id:
                old = self._get(source_id)
                if not isinstance(until, int) or not 0 <= until <= len(old['messages']) or until % 2:
                    raise ValueError('Invalid branch point')
                messages = copy.deepcopy(old['messages'][:until])
                model = old.get('model', model)
                effort = old.get('reasoning_effort', effort)
            if len(name.strip()) > 120 or not name.strip():
                raise ValueError('Provide a chat name (up to 120 characters)')
            stamp = datetime.now(timezone.utc).isoformat()
            item = {'id': uuid4().hex, 'name': name.strip(), 'created': stamp, 'updated': stamp, 'messages': messages, 'revision': 0, 'model': model, 'reasoning_effort': effort}
            self.chats[item['id']] = item
            self._write()
            return copy.deepcopy(item)

    def rename(self, chat_id: str, name: str) -> dict[str, Any]:
        if not name.strip() or len(name.strip()) > 120:
            raise ValueError('Invalid chat name')
        with self.lock:
            item = self._get(chat_id)
            item['name'] = name.strip()
            item['updated'] = datetime.now(timezone.utc).isoformat()
            self._write()
            return copy.deepcopy(item)

    def delete(self, chat_id: str) -> None:
        with self.lock:
            self._get(chat_id)
            del self.chats[chat_id]
            self._write()

    def restore(self, chat_id: str, until: int) -> dict[str, Any]:
        with self.lock:
            item = self._get(chat_id)
            if not isinstance(until, int) or not 0 <= until <= len(item['messages']) or until % 2:
                raise ValueError('Invalid restore point')
            item['messages'] = item['messages'][:until]
            item['revision'] += 1
            item['updated'] = datetime.now(timezone.utc).isoformat()
            self._write()
            return copy.deepcopy(item)

    def settings(self, chat_id: str, model: str, effort: str) -> dict[str, Any]:
        if not isinstance(model, str) or len(model) > 256 or effort not in ('default', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'):
            raise ValueError('Invalid chat model settings')
        with self.lock:
            item = self._get(chat_id)
            item['model'] = model
            item['reasoning_effort'] = effort
            self._write()
            return copy.deepcopy(item)

    def append_new_exchange(self, question: str, answer: str, model: str, effort: str, usage: dict[str, Any] | None = None, chat_id: str | None = None) -> dict[str, Any]:
        if not question.strip() or not answer.strip():
            raise ValueError('Empty chat message')
        with self.lock:
            stamp = datetime.now(timezone.utc).isoformat()
            identifier = chat_id or uuid4().hex
            if identifier in self.chats:
                raise ValueError('Chat identifier already exists')
            item = {'id': identifier, 'name': 'Chat', 'created': stamp, 'updated': stamp, 'messages': [
                {'role':'user','content':question},
                {'role':'assistant','content':answer, **({'usage':usage, 'model':model} if usage else {})}
            ], 'revision':1, 'model':model, 'reasoning_effort':effort}
            self.chats[item['id']] = item
            self._write()
            return copy.deepcopy(item)

    def append_exchange(self, chat_id: str, expected_revision: int, question: str, answer: str, usage: dict[str, Any] | None = None, model: str = '', effort: str = 'default') -> dict[str, Any]:
        if not answer.strip() or not question.strip():
            raise ValueError('Empty chat message')
        with self.lock:
            item = self._get(chat_id)
            if item['revision'] != expected_revision:
                raise ValueError('The chat changed during generation; response was not stored')
            item['messages'].extend([{'role':'user','content':question}, {'role':'assistant','content':answer, **({'usage':usage, 'model':model} if usage else {})}])
            if model:
                item['model'] = model
                item['reasoning_effort'] = effort
            item['revision'] += 1
            item['updated'] = datetime.now(timezone.utc).isoformat()
            self._write()
            return copy.deepcopy(item)
