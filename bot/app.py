"""The bot itself: long polling, consent, one check at a time, the reply, and the clean-up afterwards.

A check, in order (docs/architecture.md, section 3):
  1. "Checking..." goes back at once, so the citizen knows the message arrived.
  2. A case is opened on the engine (flag "Forwarded by a citizen on Telegram", amount 0) with consent C1 only.
  3. The file is downloaded into incoming/ and uploaded, or the text is added; then the case is run.
  4. The waiting message is edited into RED, AMBER or GREY with the card's reasons (wording.verdict_reply).
  5. The downloaded file and the engine's kept copy (evidence/uploads/<case id>) are deleted. One log line keeps
     the case id, the sha256 and the verdict; nothing else about the message is written anywhere.

Checks run one at a time on a worker thread (a video takes most of a minute of CPU), so commands and the consent
buttons are answered at once while a check runs.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import math
import os
import queue
import re
import shutil
import signal
import stat
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from . import wording as W
from .clients import EngineClient, EngineError, NetworkError, TelegramClient, TelegramError, TooBig
from .store import ChatStore, PendingCleanup, RateLimiter, private_dir, state_dir

log = logging.getLogger("satyapan.bot")

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TOKEN_FILE = Path("~/.config/satyapan_tg_token")
DEFAULT_API = "http://127.0.0.1:8100"
DEFAULT_UPLOADS = REPO / "prototype" / "evidence" / "uploads"

MAX_MB = 20                      # the most a bot may download through getFile
MAX_BYTES = MAX_MB * 1024 * 1024
MAX_MINUTES = 5                  # longer recordings are refused: speech-to-text would hold the queue for minutes
CHECKS_PER_HOUR = 10
POLL_TIMEOUT = 25                # seconds Telegram holds a getUpdates open
CASE_ID = re.compile(r"^SP-[0-9A-F]{8}$")   # models.Case.id; anything else is never handed to rmtree

SAVE_TOKEN = ('read -rs T && install -m 600 /dev/null ~/.config/satyapan_tg_token && '
              'printf %s "$T" > ~/.config/satyapan_tg_token')

# The engine's accepted extensions (prototype/satyapan/api.py, ALLOWED_EXTENSIONS) with the content type sent for
# each, and what Telegram's mime types map to.
EXT_TYPE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
            ".ogg": "audio/ogg", ".opus": "audio/opus", ".mp3": "audio/mpeg", ".wav": "audio/wav",
            ".m4a": "audio/mp4", ".weba": "audio/webm", ".aac": "audio/aac", ".amr": "audio/amr",
            ".flac": "audio/flac", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
            ".3gp": "video/3gpp", ".mkv": "video/x-matroska", ".pdf": "application/pdf", ".txt": "text/plain"}
MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "audio/ogg": ".ogg",
            "audio/opus": ".opus", "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
            "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/m4a": ".m4a",
            "audio/webm": ".weba", "audio/aac": ".aac", "audio/x-aac": ".aac", "audio/amr": ".amr",
            "audio/3gpp": ".3gp", "audio/flac": ".flac", "audio/x-flac": ".flac", "video/mp4": ".mp4",
            "video/webm": ".webm", "video/quicktime": ".mov", "video/3gpp": ".3gp", "video/x-matroska": ".mkv",
            "application/pdf": ".pdf", "text/plain": ".txt"}
# Message fields that are never checked. An animation (GIF) also carries a `document`, so it is looked at first.
UNSUPPORTED_FIELDS = ("animation", "sticker", "contact", "location", "venue", "poll", "dice", "game", "story",
                      "paid_media", "invoice")


class TokenProblem(Exception):
    pass


def token_file() -> Path:
    return Path(os.environ.get("SATYAPAN_TG_TOKEN_FILE") or DEFAULT_TOKEN_FILE).expanduser()


def load_token(path: Path) -> str:
    """The bot token, or TokenProblem with a sentence that says what to do. The token itself is never printed."""
    if not path.exists():
        raise TokenProblem(f"No Telegram bot token at {path}. Create the bot with @BotFather, then save its token "
                           f"with:\n  {SAVE_TOKEN}\n(see bot/README.md).")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode):
        raise TokenProblem(f"{path} is not a regular file.")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise TokenProblem(f"{path} belongs to another user. Save the token again as this user (bot/README.md).")
    if st.st_mode & 0o077:
        raise TokenProblem(f"{path} can be read by other users (mode {stat.S_IMODE(st.st_mode):03o}). "
                           f"Run: chmod 600 {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        raise TokenProblem(f"{path} does not hold a bot token (BotFather's token looks like 123456789:AA...). "
                           "Save it again (bot/README.md).")
    return token


# ---------------------------------------------------------------- what was sent

@dataclass
class Item:
    """One thing to check: a file on Telegram, or text."""
    kind: str                         # text | audio | video | image | pdf | file
    file_id: Optional[str] = None
    ext: str = ""
    size: Optional[int] = None
    duration: Optional[int] = None
    text: Optional[str] = None


def _ext_for(name: Optional[str], mime: Optional[str]) -> str:
    ext = Path(name or "").suffix.lower()
    if ext in EXT_TYPE:
        return ext
    return MIME_EXT.get((mime or "").split(";")[0].strip().lower(), "")


def item_of(msg: dict) -> Optional[Item]:
    """What in `msg` can be checked; None for something that cannot (a sticker, a contact, a .zip...)."""
    if any(f in msg for f in UNSUPPORTED_FIELDS):
        return None
    if v := msg.get("voice"):
        return Item("audio", v["file_id"], _ext_for(None, v.get("mime_type")) or ".ogg", v.get("file_size"),
                    v.get("duration"))
    if a := msg.get("audio"):
        ext = _ext_for(a.get("file_name"), a.get("mime_type"))
        return Item("audio", a["file_id"], ext, a.get("file_size"), a.get("duration")) if ext else None
    if v := msg.get("video"):
        ext = _ext_for(v.get("file_name"), v.get("mime_type")) or ".mp4"
        return Item("video", v["file_id"], ext, v.get("file_size"), v.get("duration"))
    if v := msg.get("video_note"):
        return Item("video", v["file_id"], ".mp4", v.get("file_size"), v.get("duration"))
    if sizes := msg.get("photo"):
        # The largest size Telegram made that a bot may still download.
        ok = [p for p in sizes if (p.get("file_size") or 0) <= MAX_BYTES] or sizes
        best = max(ok, key=lambda p: (p.get("width", 0) * p.get("height", 0), p.get("file_size") or 0))
        return Item("image", best["file_id"], ".jpg", best.get("file_size"))
    if d := msg.get("document"):
        ext = _ext_for(d.get("file_name"), d.get("mime_type"))
        return Item("file", d["file_id"], ext, d.get("file_size")) if ext else None
    text = msg.get("text")
    if isinstance(text, str) and text.strip():
        return Item("text", text=text)
    return None


@dataclass
class Job:
    chat_id: int
    lang: str
    waiting_id: int
    item: Item


# ---------------------------------------------------------------- the bot

class Bot:
    def __init__(self, tg: TelegramClient, engine: EngineClient, store: ChatStore, limiter: RateLimiter,
                 pending: PendingCleanup, uploads_root: Path, incoming: Path,
                 sleep: Callable[[float], None] = time.sleep):
        self.tg, self.engine, self.store, self.limiter, self.pending = tg, engine, store, limiter, pending
        self.uploads_root = Path(uploads_root)
        self.incoming = private_dir(Path(incoming))
        self.jobs: "queue.Queue[Job]" = queue.Queue()
        self.stopping = threading.Event()
        self.current: Optional[Job] = None
        self.offset: Optional[int] = None
        self._sleep = sleep
        self._worker: Optional[threading.Thread] = None
        self.poll_timeout = POLL_TIMEOUT
        self.backoff = (1.0, 60.0)   # first and longest pause after a failed poll, in seconds

    # ---------------- start-up and clean-up

    def sweep(self) -> None:
        """Delete what an earlier run left behind: files in incoming/ and engine copies of unfinished checks."""
        for p in self.incoming.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        for case_id in self.pending.all():
            self.delete_engine_copy(case_id)

    def delete_engine_copy(self, case_id: Optional[str]) -> None:
        if not case_id or not CASE_ID.match(case_id):
            return
        shutil.rmtree(self.uploads_root / case_id, ignore_errors=True)
        if not (self.uploads_root / case_id).exists():
            self.pending.done(case_id)

    # ---------------- Telegram calls retried after a transient failure

    def _tg(self, fn: Callable, *args, **kw):
        for attempt in range(3):
            try:
                return fn(*args, **kw)
            except NetworkError:
                if attempt == 2:
                    raise
                self._sleep(2 ** attempt)
            except TelegramError as e:
                if e.code == 429 and e.retry_after and attempt < 2:
                    self._sleep(min(float(e.retry_after), 30.0))
                    continue
                raise

    def say(self, chat_id: int, text: str, **kw) -> dict:
        return self._tg(self.tg.send_message, chat_id, text, **kw)

    def show(self, job: Job, text: str) -> None:
        """Turn the waiting message into `text`; send it fresh if the edit is refused (the message was deleted)."""
        try:
            self._tg(self.tg.edit_message_text, job.chat_id, job.waiting_id, text)
        except TelegramError:
            self.say(job.chat_id, text)

    # ---------------- updates

    def lang_for(self, chat_id: int, user: dict) -> str:
        chosen = self.store.lang(chat_id)
        if chosen in W.LANGS:
            return chosen
        return "hi" if str(user.get("language_code") or "").lower().split("-")[0] == "hi" else "en"

    def handle_update(self, update: dict) -> None:
        if cq := update.get("callback_query"):
            self.on_callback(cq)
        elif msg := update.get("message"):
            self.on_message(msg)

    def ask_consent(self, chat_id: int, lang: str) -> None:
        self.say(chat_id, W.consent_text(lang), reply_markup=W.CONSENT_BUTTONS)

    def on_callback(self, cq: dict) -> None:
        data = cq.get("data") or ""
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        self._quietly(self.tg.answer_callback_query, cq.get("id"))   # stops the button's spinner
        if not data.startswith("consent:") or chat.get("type") != "private":
            return
        chat_id, lang = chat["id"], self.lang_for(chat["id"], cq.get("from") or {})
        choice = "yes" if data == "consent:yes" else "no"
        self.store.set_consent(chat_id, choice == "yes")
        answer = f"{W.consent_text(lang)}\n\n{W.pick(lang, 'Your answer:', 'आपका जवाब:')} {W.CONSENT_CHOSEN[choice]}"
        try:   # the buttons go, so an old consent message cannot be pressed again by mistake
            self._tg(self.tg.edit_message_text, chat_id, msg["message_id"], answer)
        except (TelegramError, KeyError):
            pass
        self.say(chat_id, W.pick(lang, *(W.CONSENT_YES if choice == "yes" else W.CONSENT_NO)))

    def on_message(self, msg: dict) -> None:
        chat = msg.get("chat") or {}
        chat_id, user = chat.get("id"), msg.get("from") or {}
        if chat_id is None:
            return
        text = msg.get("text") if isinstance(msg.get("text"), str) else ""
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else None
        lang = self.lang_for(chat_id, user)
        if chat.get("type") != "private":
            # A group gets one sentence, and only when someone asks the bot something.
            if command in ("/start", "/help"):
                self.say(chat_id, W.pick(lang, *W.PRIVATE_ONLY))
            return
        if command:
            return self.on_command(chat_id, command, lang)
        if not self.store.consented(chat_id):
            return self.ask_consent(chat_id, lang)   # nothing is checked, and nothing of the message is kept
        item = item_of(msg)
        if item is None:
            return self.say(chat_id, W.unsupported(lang), reply_to=msg.get("message_id"))
        if item.size and item.size > MAX_BYTES:
            return self.say(chat_id, W.too_big(lang, MAX_MB), reply_to=msg.get("message_id"))
        if item.duration and item.duration > MAX_MINUTES * 60:
            return self.say(chat_id, W.too_long(lang, MAX_MINUTES), reply_to=msg.get("message_id"))
        ok, wait = self.limiter.allow(user.get("id", chat_id))
        if not ok:
            return self.say(chat_id, W.rate_limited(lang, self.limiter.limit, math.ceil(wait / 60)),
                            reply_to=msg.get("message_id"))
        waiting = self.say(chat_id, W.pick(lang, *W.WAITING), reply_to=msg.get("message_id"))
        self.jobs.put(Job(chat_id, lang, waiting["message_id"], item))

    def on_command(self, chat_id: int, command: str, lang: str) -> None:
        if command == "/start":
            if self.store.consented(chat_id):
                return self.say(chat_id, W.pick(lang, *W.ALREADY_AGREED))
            return self.ask_consent(chat_id, lang)
        if command in ("/hindi", "/english"):
            new = "hi" if command == "/hindi" else "en"
            self.store.set_lang(chat_id, new)
            return self.say(chat_id, W.LANG_SET[new])
        if command == "/stop":
            self.store.withdraw(chat_id)
            return self.say(chat_id, W.pick(lang, *W.CONSENT_WITHDRAWN))
        self.say(chat_id, W.pick(lang, *W.HELP))

    # ---------------- a check

    def check(self, job: Job) -> None:
        """Run one check end to end. Whatever happens, the citizen gets a reply and nothing of the file is kept."""
        item, lang = job.item, job.lang
        case_id: Optional[str] = None
        folder: Optional[Path] = None
        digest, outcome = "-", None
        try:
            case_id = self.engine.open_case()
            self.engine.consent(case_id, lang)
            if item.kind == "text":
                digest = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
                self.engine.add_text(case_id, item.text)
            else:
                info = self._tg(self.tg.get_file, item.file_id)
                if (info.get("file_size") or 0) > MAX_BYTES or not info.get("file_path"):
                    # Telegram gives no file_path for a file over the bot download limit.
                    raise TooBig()
                folder = self.incoming / case_id
                folder.mkdir(mode=0o700)
                path = folder / f"telegram{item.ext}"
                self.tg.download(info["file_path"], path, MAX_BYTES)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.pending.add(case_id)   # from here the engine may hold a copy
                self.engine.add_media(case_id, path, path.name, EXT_TYPE[item.ext], language=lang)
            view = self.engine.run(case_id)
            outcome = str(((view.get("case") or {}).get("verdict") or {}).get("outcome") or "GREY")
            reply = W.verdict_reply(view, lang)
        except TooBig:
            reply = W.too_big(lang, MAX_MB)
        except EngineError as e:
            log.warning("check failed case=%s engine=%s", case_id or "-", e.status)
            reply = W.unreadable(lang) if e.status in (413, 415) else W.failed(lang)
        except (NetworkError, TelegramError) as e:
            log.warning("check failed case=%s %s", case_id or "-", type(e).__name__)
            reply = W.failed(lang)
        except Exception as e:  # noqa: BLE001 - one bad check must not stop the bot
            log.error("check failed case=%s %s at %s", case_id or "-", type(e).__name__, _where(e))
            reply = W.failed(lang)
        finally:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
        try:
            self.show(job, reply)
        finally:
            self.delete_engine_copy(case_id)
            if outcome:
                log.info("check case=%s sha256=%s verdict=%s%s", case_id, digest, W.shown_outcome(outcome),
                         "" if W.shown_outcome(outcome) == outcome else f" (engine {outcome})")

    def drain(self) -> None:
        """Run every queued check here and now (the tests; the worker does the same one by one)."""
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            self._run_job(job)

    def _run_job(self, job: Job) -> None:
        self.current = job
        try:
            self.check(job)
        except Exception as e:  # noqa: BLE001
            log.error("reply failed %s at %s", type(e).__name__, _where(e))
        finally:
            self.current = None

    def _work(self) -> None:
        while not self.stopping.is_set():
            try:
                job = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.stopping.is_set():
                self.jobs.put(job)   # left for shutdown() to answer
                return
            self._run_job(job)

    # ---------------- the loop

    def poll_once(self, timeout: Optional[int] = None) -> int:
        updates = self.tg.get_updates(self.offset, self.poll_timeout if timeout is None else timeout)
        for u in updates:
            self.offset = max(self.offset or 0, int(u.get("update_id", 0)) + 1)
            try:
                self.handle_update(u)
            except Exception as e:  # noqa: BLE001 - one bad update never stops the loop
                log.error("update %s skipped: %s at %s", u.get("update_id"), type(e).__name__, _where(e))
        return len(updates)

    def run(self) -> None:
        self.sweep()
        self._worker = threading.Thread(target=self._work, name="checks", daemon=True)
        self._worker.start()
        first, longest = self.backoff
        delay = first
        while not self.stopping.is_set():
            try:
                self.poll_once()
                delay = first
                continue
            except TelegramError as e:
                if e.code in (401, 404):
                    raise TokenProblem("Telegram refused the bot token (it was revoked or mistyped). Save it again "
                                       "(bot/README.md).") from None
                if e.code == 409:
                    log.warning("Telegram says another copy of this bot is polling, or a webhook is set. Stop the "
                                "other copy; retrying in %.0f s", delay)
                elif e.retry_after:
                    delay = max(delay, float(e.retry_after))
                    log.warning("Telegram asked to slow down; waiting %.0f s", delay)
                else:
                    log.warning("Telegram error %s; retrying in %.0f s", e.code, delay)
            except NetworkError as e:
                log.warning("cannot reach Telegram (%s); retrying in %.0f s", str(e)[:80], delay)
            except Exception as e:  # noqa: BLE001
                log.error("polling failed: %s at %s; retrying in %.0f s", type(e).__name__, _where(e), delay)
            self.stopping.wait(delay)
            delay = min(delay * 2, longest)

    def shutdown(self, wait: float = 120.0) -> None:
        """Ctrl-C: stop taking messages, tell everyone still queued, let the check in progress finish (a second
        Ctrl-C cuts it short), and confirm the updates already handled so a restart does not answer them twice."""
        self.stopping.set()
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            self._quietly(self.show, job, W.stopped(job.lang))
        if self._worker and self._worker.is_alive() and self.current:
            log.info("finishing the check in progress (up to %.0f s; Ctrl-C again to quit now)", wait)
            try:
                self._worker.join(wait)
            except KeyboardInterrupt:
                pass
            job = self.current
            if job is not None:   # cut short: its engine copy stays in pending-cleanup.json for the next start
                self._quietly(self.show, job, W.stopped(job.lang))
        for p in self.incoming.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        if self.offset is not None:
            self._quietly(self.tg.get_updates, self.offset, 0)

    @staticmethod
    def _quietly(fn: Callable, *args) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            pass


def _where(e: BaseException) -> str:
    """file:line of the failure, without the exception's message (it can quote the citizen's text)."""
    tb = traceback.extract_tb(e.__traceback__)
    return f"{Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else "?"


# ---------------------------------------------------------------- command line

def setup_logging(log_file: Optional[str]) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.close(fd)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers,
                        force=True)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m bot", description="Satyapan's Telegram bot (bot/README.md).")
    ap.add_argument("--api", default=os.environ.get("SATYAPAN_API", DEFAULT_API),
                    help=f"the bot's own engine (env SATYAPAN_API, default {DEFAULT_API})")
    ap.add_argument("--uploads", default=os.environ.get("SATYAPAN_ENGINE_UPLOADS", str(DEFAULT_UPLOADS)),
                    help="the engine's evidence/uploads folder, where it keeps a copy of each upload "
                         "(env SATYAPAN_ENGINE_UPLOADS)")
    ap.add_argument("--log", help="also append the log to this file")
    ap.add_argument("--check-token", action="store_true", help="check the token file and exit")
    ap.add_argument("--telegram-api", default=os.environ.get("SATYAPAN_TG_API_BASE", "https://api.telegram.org"),
                    help=argparse.SUPPRESS)   # the tests' fake Telegram server
    args = ap.parse_args(argv)
    setup_logging(args.log)

    try:
        token = load_token(token_file())
    except TokenProblem as e:
        print(f"satyapan bot: {e}", file=sys.stderr)
        return 2
    if args.check_token:
        print(f"token file {token_file()} is in place and private")
        return 0
    if urlparse(args.api).port == 8000:
        print("satyapan bot: port 8000 is the demo's engine. The bot uses its own engine (scripts/run_tg_bot.sh "
              "starts one on 8100).", file=sys.stderr)
        return 2

    tg = TelegramClient(token, base=args.telegram_api, timeout=30)
    engine = EngineClient(args.api)
    sd = private_dir(state_dir())
    bot = Bot(tg, engine, ChatStore(sd / "chats.json"), RateLimiter(CHECKS_PER_HOUR, 3600.0),
              PendingCleanup(sd / "pending-cleanup.json"), Path(args.uploads), sd / "incoming")
    try:
        me = tg.call("getMe")
    except TelegramError as e:
        print(f"satyapan bot: Telegram refused the token ({e.code} {e.description}). Save it again "
              "(bot/README.md).", file=sys.stderr)
        return 2
    except NetworkError:
        me = {}
        log.warning("Telegram cannot be reached yet; the bot will keep trying")
    if not engine.health():
        log.warning("no engine answers at %s; checks will fail until it is up", args.api)
    log.info("bot @%s polling; engine %s; uploads %s; state %s", (me or {}).get("username", "?"), args.api,
             args.uploads, sd)

    def on_term(*_):   # `kill PID` (or tmux closing) stops the bot the same way Ctrl-C does
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_term)
    try:
        bot.run()
    except KeyboardInterrupt:
        log.info("stopping")
    except TokenProblem as e:
        print(f"satyapan bot: {e}", file=sys.stderr)
        bot.shutdown(wait=0)
        return 2
    bot.shutdown()
    log.info("stopped")
    return 0
