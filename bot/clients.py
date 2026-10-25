"""The two HTTP clients the bot needs, on the standard library only: the Telegram Bot API and the Satyapan engine.

The bot token is part of every Telegram URL, so no URL, request or urllib exception object from here is ever logged
or re-raised as is: errors are re-raised as TelegramError / NetworkError with the method name and Telegram's own
description only.
"""
from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

TELEGRAM_API = "https://api.telegram.org"


class NetworkError(Exception):
    """The server could not be reached, or the connection broke. Worth retrying after a pause."""


class TelegramError(Exception):
    def __init__(self, method: str, code: int, description: str, retry_after: Optional[float] = None):
        super().__init__(f"Telegram {method}: {code} {description}")
        self.method, self.code, self.description, self.retry_after = method, code, description, retry_after


class TooBig(Exception):
    pass


# What a dropped or slow connection raises, while connecting or while reading the answer.
BROKEN = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, OSError)


def _open(req: urllib.request.Request, timeout: float):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except BROKEN as e:
        raise NetworkError(f"{type(e).__name__}: {getattr(e, 'reason', '')}") from None


def _read(r) -> bytes:
    try:
        return r.read()
    except BROKEN as e:
        raise NetworkError(f"reading the answer: {type(e).__name__}") from None


class TelegramClient:
    def __init__(self, token: str, base: str = TELEGRAM_API, timeout: float = 30.0):
        self._token = token
        self.base = base.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:   # never the token
        return f"TelegramClient(base={self.base!r})"

    def call(self, method: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
        body = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/bot{self._token}/{method}", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with _open(req, timeout or self.timeout) as r:
                data = json.loads(_read(r).decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode("utf-8"))
            except (ValueError, OSError):
                data = {"ok": False, "error_code": e.code, "description": "no description"}
            finally:
                e.close()
        except ValueError:
            raise NetworkError(f"Telegram {method}: the answer was not JSON") from None
        if not data.get("ok"):
            params_ = data.get("parameters") or {}
            raise TelegramError(method, int(data.get("error_code") or 0), str(data.get("description") or ""),
                                params_.get("retry_after"))
        return data.get("result")

    def get_updates(self, offset: Optional[int], timeout: int) -> list[dict]:
        params: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", params, timeout=timeout + 15) or []

    def send_message(self, chat_id: int, text: str, reply_markup: Optional[dict] = None,
                     reply_to: Optional[int] = None) -> dict:
        params: dict = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            params["reply_markup"] = reply_markup
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return self.call("sendMessage", params)

    def edit_message_text(self, chat_id: int, message_id: int, text: str, reply_markup: Optional[dict] = None) -> Any:
        params: dict = {"chat_id": chat_id, "message_id": message_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self.call("editMessageText", params)

    def answer_callback_query(self, callback_id: str, text: Optional[str] = None) -> Any:
        params: dict = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
        return self.call("answerCallbackQuery", params)

    def get_file(self, file_id: str) -> dict:
        return self.call("getFile", {"file_id": file_id})

    def download(self, file_path: str, dest: Path, max_bytes: int, timeout: float = 120.0) -> int:
        """Stream a file Telegram holds to `dest`, refusing anything over `max_bytes`."""
        req = urllib.request.Request(f"{self.base}/file/bot{self._token}/{file_path}")
        written = 0
        try:
            with _open(req, timeout) as r, open(dest, "wb") as f:
                while chunk := r.read(1 << 16):
                    written += len(chunk)
                    if written > max_bytes:
                        raise TooBig()
                    f.write(chunk)
        except urllib.error.HTTPError as e:
            e.close()
            raise TelegramError("download", e.code, "the file could not be downloaded") from None
        except (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException) as e:
            raise NetworkError(f"download: {type(e).__name__}") from None
        return written


class EngineError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"engine {status}: {detail[:200]}")
        self.status, self.detail = status, detail


class EngineClient:
    """The Satyapan engine's HTTP API (prototype/satyapan/api.py)."""

    FLAG_REASON = "Forwarded by a citizen on Telegram"

    def __init__(self, base: str, timeout: float = 300.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _send(self, method: str, path: str, body: Optional[bytes] = None, content_type: str = "application/json",
              timeout: Optional[float] = None) -> Any:
        req = urllib.request.Request(f"{self.base}{path}", data=body, method=method,
                                     headers={"Content-Type": content_type} if body is not None else {})
        try:
            with _open(req, timeout or self.timeout) as r:
                return json.loads(_read(r).decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", errors="replace")
                detail = json.loads(raw).get("detail", raw)
            except (ValueError, OSError, AttributeError):
                detail = ""
            finally:
                e.close()
            raise EngineError(e.code, detail if isinstance(detail, str) else json.dumps(detail)) from None
        except ValueError:
            raise EngineError(502, "the engine's answer was not JSON") from None

    def _json(self, path: str, payload: dict) -> Any:
        return self._send("POST", path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def health(self) -> bool:
        try:
            return bool(self._send("GET", "/api/health", timeout=5).get("ok"))
        except (EngineError, NetworkError, AttributeError):
            return False

    def open_case(self) -> str:
        view = self._json("/api/cases", {"flag": {"reason": self.FLAG_REASON, "amount_inr": 0,
                                                  "customer_ref": "telegram-citizen"}})
        return view["case"]["id"]

    def consent(self, case_id: str, lang: str) -> dict:
        return self._json(f"/api/cases/{case_id}/consent", {"check": True, "report": False, "memory": False,
                                                            "lang": lang})

    def add_text(self, case_id: str, text: str) -> dict:
        return self._json(f"/api/cases/{case_id}/text", {"text": text, "source": "text"})

    def add_media(self, case_id: str, path: Path, filename: str, content_type: str, language: str,
                  derived_text: Optional[str] = None) -> dict:
        boundary = "satyapan-" + uuid.uuid4().hex
        fields = [("language", language)] + ([("derived_text", derived_text)] if derived_text is not None else [])
        out = bytearray()
        for name, value in fields:
            out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n").encode()
            out += value.encode("utf-8") + b"\r\n"
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n").encode()
        out += Path(path).read_bytes() + b"\r\n" + f"--{boundary}--\r\n".encode()
        return self._send("POST", f"/api/cases/{case_id}/media", bytes(out),
                          content_type=f"multipart/form-data; boundary={boundary}")

    def run(self, case_id: str) -> dict:
        return self._send("POST", f"/api/cases/{case_id}/run", b"{}")
