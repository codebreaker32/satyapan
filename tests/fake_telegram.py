"""A fake Telegram Bot API and a stub Satyapan engine, both local HTTP servers, for the bot's tests.

The fake Telegram server speaks the few methods the bot uses (getMe, getUpdates with long polling, sendMessage,
editMessageText, answerCallbackQuery, getFile and the file download URL). The tests and scripts/tg_bot_e2e.py push
updates into it the way a citizen's phone would, and read back what the bot said.
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

TOKEN = "123456789:TEST-token-for-the-fake-server-only"


class _Server:
    def __init__(self, handler_cls):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.httpd.daemon_threads = True
        self.httpd.owner = self
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _reply(h: BaseHTTPRequestHandler, status: int, body, content_type="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", content_type)
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


# ---------------------------------------------------------------- Telegram

class FakeTelegram(_Server):
    def __init__(self, token: str = TOKEN):
        super().__init__(_TelegramHandler)
        self.token = token
        self.cond = threading.Condition()
        self.updates: list[dict] = []
        self.next_update = 1000
        self.next_message = 1
        self.messages: dict[int, dict] = {}     # every message the bot sent, by id, as it reads now
        self.calls: list[tuple[str, dict]] = []
        self.files: dict[str, tuple[str, bytes, Optional[int]]] = {}
        self.fail: dict[str, list[int]] = {}    # method -> HTTP statuses to answer with, one per call

    # what a phone sends
    def push(self, update: dict) -> int:
        with self.cond:
            update = {"update_id": self.next_update, **update}
            self.next_update += 1
            self.updates.append(update)
            self.cond.notify_all()
            return update["update_id"]

    def push_message(self, chat_id: int = 42, user_id: int = 7, lang: str = "en", chat_type: str = "private",
                     **fields) -> int:
        with self.cond:
            mid = self.next_message
            self.next_message += 1
        msg = {"message_id": mid, "date": int(time.time()), "chat": {"id": chat_id, "type": chat_type},
               "from": {"id": user_id, "is_bot": False, "first_name": "Test", "language_code": lang}, **fields}
        return self.push({"message": msg})

    def push_callback(self, message_id: int, data: str, chat_id: int = 42, user_id: int = 7, lang: str = "en") -> int:
        return self.push({"callback_query": {
            "id": f"cb{self.next_update}", "data": data, "from": {"id": user_id, "language_code": lang},
            "message": {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}}}})

    def add_file(self, content: bytes, name: str = "voice.ogg", reported_size: Optional[int] = None) -> str:
        fid = f"FILE{len(self.files) + 1}"
        self.files[fid] = (f"files/{fid}/{name}", content, reported_size)
        return fid

    # what the bot said
    def bot_messages(self, chat_id: int = 42) -> list[dict]:
        with self.cond:
            return [m for m in self.messages.values() if m["chat_id"] == chat_id]

    def texts(self, chat_id: int = 42) -> list[str]:
        return [m["text"] for m in self.bot_messages(chat_id)]

    def wait_for(self, pred: Callable[[], bool], timeout: float = 30.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.05)
        return pred()

    def calls_to(self, method: str) -> list[dict]:
        return [p for m, p in self.calls if m == method]


class _TelegramHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    @property
    def tg(self) -> FakeTelegram:
        return self.server.owner

    def do_GET(self):
        m = re.fullmatch(r"/file/bot([^/]+)/(.+)", self.path)
        if not m or m.group(1) != self.tg.token:
            return _reply(self, 404, {"ok": False, "error_code": 404, "description": "Not Found"})
        for path, content, _ in self.tg.files.values():
            if path == m.group(2):
                return _reply(self, 200, content, "application/octet-stream")
        return _reply(self, 404, {"ok": False, "error_code": 404, "description": "Not Found"})

    def do_POST(self):
        m = re.fullmatch(r"/bot([^/]+)/(\w+)", self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not m or m.group(1) != self.tg.token:
            return _reply(self, 401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
        method = m.group(2)
        params = json.loads(body or b"{}")
        tg = self.tg
        with tg.cond:
            tg.calls.append((method, params))
            fails = tg.fail.get(method)
            status = fails.pop(0) if fails else None
        if status:
            return _reply(self, status, {"ok": False, "error_code": status, "description": "injected failure"})
        handler = getattr(self, f"m_{method}", None)
        if handler is None:
            return _reply(self, 404, {"ok": False, "error_code": 404, "description": "Not Found: method"})
        result = handler(params)
        if isinstance(result, tuple):
            return _reply(self, result[0], {"ok": False, "error_code": result[0], "description": result[1]})
        return _reply(self, 200, {"ok": True, "result": result})

    def m_getMe(self, p):
        return {"id": 1, "is_bot": True, "username": "satyapan_test_bot"}

    def m_getUpdates(self, p):
        tg, offset = self.tg, p.get("offset")
        end = time.time() + min(float(p.get("timeout") or 0), 30.0)
        with tg.cond:
            while True:
                if offset is not None:
                    tg.updates = [u for u in tg.updates if u["update_id"] >= offset]
                if tg.updates or time.time() >= end:
                    return list(tg.updates)
                tg.cond.wait(max(0.0, min(0.2, end - time.time())))

    def m_sendMessage(self, p):
        tg = self.tg
        with tg.cond:
            mid = tg.next_message
            tg.next_message += 1
            tg.messages[mid] = {"message_id": mid, "chat_id": p["chat_id"], "text": p["text"],
                                "reply_markup": p.get("reply_markup"), "edits": 0}
        return {"message_id": mid, "chat": {"id": p["chat_id"], "type": "private"}, "text": p["text"]}

    def m_editMessageText(self, p):
        tg = self.tg
        with tg.cond:
            msg = tg.messages.get(p["message_id"])
            if not msg or msg["chat_id"] != p["chat_id"]:
                return (400, "Bad Request: message to edit not found")
            msg.update(text=p["text"], reply_markup=p.get("reply_markup"), edits=msg["edits"] + 1)
        return {"message_id": msg["message_id"], "text": p["text"]}

    def m_answerCallbackQuery(self, p):
        return True

    def m_getFile(self, p):
        f = self.tg.files.get(p["file_id"])
        if not f:
            return (400, "Bad Request: invalid file_id")
        path, content, reported = f
        size = reported if reported is not None else len(content)
        out = {"file_id": p["file_id"], "file_unique_id": p["file_id"].lower(), "file_size": size}
        if size <= 20 * 1024 * 1024:
            out["file_path"] = path
        return out


# ---------------------------------------------------------------- a stub engine

def stub_view(case_id: str, outcome: str = "RED", lang_cards: Optional[dict] = None, signals: Optional[list] = None):
    reasons = [{"text": "The message says it is from the police and asks for money. The police never ask for "
                        "money on a call.", "cite": "MHA", "rule_id": "R-DIGITAL-ARREST-PAY"},
               {"text": "The account it names is not a government account.", "cite": "RBI",
                "rule_id": "R-AGENCY-PAY"}]
    reasons_hi = [{"text": "संदेश खुद को पुलिस बताता है और पैसे माँगता है।", "cite": "MHA",
                   "rule_id": "R-DIGITAL-ARREST-PAY"}]
    head = {"RED": ("Stop and verify through the official channel", "रुकिए। आधिकारिक माध्यम से जाँच करें"),
            "AMBER": ("Verify before paying", "भुगतान से पहले पुष्टि करें"),
            "GREY": ("Could not confirm. Check via the official channel",
                     "पुष्टि नहीं हो सकी। आधिकारिक माध्यम से जाँच करें"),
            "MATCHES": ("Matches our records", "हमारे रिकॉर्ड से मेल खाता है")}[outcome]
    cards = lang_cards or {"en": {"headline": head[0], "reasons": reasons},
                           "hi": {"headline": head[1], "reasons": reasons_hi}}
    sigs = signals if signals is not None else [
        {"rule_id": "R-DIGITAL-ARREST-PAY", "family": "F1", "severity": "hard"},
        {"rule_id": "R-AGENCY-PAY", "family": "F1", "severity": "hard"}]
    return {"case": {"id": case_id, "verdict": {"outcome": outcome, "headline_en": head[0], "headline_hi": head[1],
                                                 "score": 0.83, "signals": sigs}},
            "card": cards}


class StubEngine(_Server):
    """Records what the bot sent; keeps a copy of each upload under `uploads/<case id>` the way api.py does."""

    def __init__(self, uploads: Path):
        super().__init__(_EngineHandler)
        self.uploads = Path(uploads)
        self.lock = threading.Lock()
        self.cases: dict[str, dict] = {}
        self.view: Callable[[str], dict] = lambda cid: stub_view(cid)
        self.fail: dict[str, int] = {}          # step -> HTTP status, e.g. {"run": 500}
        self.n = 0


def _multipart(body: bytes, content_type: str) -> dict:
    boundary = content_type.split("boundary=")[1].encode()
    out = {}
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, _, value = part.partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head)
        if not name:
            continue
        value = value[:-2] if value.endswith(b"\r\n") else value
        fname = re.search(rb'filename="([^"]*)"', head)
        out[name.group(1).decode()] = {"value": value, "filename": fname.group(1).decode() if fname else None}
    return out


class _EngineHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/health":
            return _reply(self, 200, {"ok": True, "version": "stub"})
        return _reply(self, 404, {"detail": "no"})

    def do_POST(self):
        eng: StubEngine = self.server.owner
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/api/cases":
            if eng.fail.get("open"):
                return _reply(self, eng.fail["open"], {"detail": "injected"})
            with eng.lock:
                eng.n += 1
                cid = f"SP-{eng.n:08X}"
                eng.cases[cid] = {"flag": json.loads(body)["flag"], "steps": []}
            return _reply(self, 200, {"case": {"id": cid}})
        m = re.fullmatch(r"/api/cases/(SP-[0-9A-F]{8})/(\w+)", self.path)
        if not m or m.group(1) not in eng.cases:
            return _reply(self, 404, {"detail": "no case"})
        cid, step = m.groups()
        case = eng.cases[cid]
        case["steps"].append(step)
        if eng.fail.get(step):
            return _reply(self, eng.fail[step], {"detail": "injected failure"})
        if step == "consent":
            case["consent"] = json.loads(body)
        elif step == "text":
            case["text"] = json.loads(body)
        elif step == "media":
            parts = _multipart(body, self.headers["Content-Type"])
            case["media"] = {k: v["value"] for k, v in parts.items()}
            case["filename"] = parts["file"]["filename"]
            kept = eng.uploads / cid
            kept.mkdir(parents=True, exist_ok=True)
            (kept / f"00-{parts['file']['filename']}").write_bytes(parts["file"]["value"])
        elif step == "run":
            return _reply(self, 200, eng.view(cid))
        return _reply(self, 200, {"case": {"id": cid}})
