"""The bot's only state on disk: per chat, whether its consent was given and which language it reads.

One small JSON file in a directory only this user can open (mode 700; the file 600). No message, file, transcript
or verdict is ever written here.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_STATE_DIR = Path("~/.local/share/satyapan-bot")


def state_dir() -> Path:
    return Path(os.environ.get("SATYAPAN_TG_STATE_DIR") or DEFAULT_STATE_DIR).expanduser()


def private_dir(path: Path) -> Path:
    """Create `path` (and its parents) and make sure only this user can open it."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


class ChatStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else state_dir() / "chats.json"
        private_dir(self.path.parent)
        self._lock = threading.Lock()
        self._chats: dict[str, dict] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._chats = {str(k): v for k, v in data.items() if isinstance(v, dict)}
            except (OSError, ValueError, AttributeError):
                # A damaged file means nobody's consent can be read: start empty, so everyone is asked again.
                self._chats = {}

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".chats-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._chats, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get(self, chat_id: int) -> dict:
        with self._lock:
            return dict(self._chats.get(str(chat_id), {}))

    def consented(self, chat_id: int) -> bool:
        return self.get(chat_id).get("consent") is True

    def lang(self, chat_id: int) -> Optional[str]:
        return self.get(chat_id).get("lang")

    def set_consent(self, chat_id: int, agreed: bool) -> None:
        with self._lock:
            rec = self._chats.setdefault(str(chat_id), {})
            rec["consent"] = bool(agreed)
            rec["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._save()

    def set_lang(self, chat_id: int, lang: str) -> None:
        with self._lock:
            self._chats.setdefault(str(chat_id), {})["lang"] = lang
            self._save()

    def withdraw(self, chat_id: int) -> None:
        """Consent withdrawn: the chat's whole record is removed, language choice included."""
        with self._lock:
            self._chats.pop(str(chat_id), None)
            self._save()


class RateLimiter:
    """At most `limit` checks per user in any `window` seconds. In memory: a restart starts everyone afresh."""

    def __init__(self, limit: int = 10, window: float = 3600.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._seen: dict[int, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, user_id: int) -> tuple[bool, float]:
        """(True, 0) and the check is counted, or (False, seconds until the oldest check leaves the window)."""
        now = self.clock()
        with self._lock:
            q = self._seen[user_id]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, self.window - (now - q[0])
            q.append(now)
            return True, 0.0
