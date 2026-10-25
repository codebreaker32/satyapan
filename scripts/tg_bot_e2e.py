"""End-to-end check of the Telegram bot: scripts/run_tg_bot.sh for real (its own engine on 8100, the forensics service
if it answers), with a fake Telegram API in place of api.telegram.org. Two citizens: one forwards a voice note from an
English-language phone, the other pastes a scam text from a Hindi-language phone. Prints both replies verbatim,
checks the engine's kept copy is gone, then stops the bot the way Ctrl-C in tmux would and checks the engine stopped.

  python3 scripts/tg_bot_e2e.py VOICE_NOTE.ogg [--out replies.txt]
  (SATYAPAN_ENGINE_VENV picks the engine's environment, as for run_tg_bot.sh)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
from fake_telegram import TOKEN, FakeTelegram  # noqa: E402

from bot import wording as W  # noqa: E402

SCAM_TEXT = ("यह मुंबई पुलिस है। आपके नाम से भेजे गए पार्सल में ड्रग्स मिले हैं और आप डिजिटल अरेस्ट में हैं। "
             "किसी को मत बताइए। जाँच पूरी होने तक ₹2,50,000 तुरंत खाता संख्या 30011223344556, IFSC DEMO0001234 "
             "में भेजें, नहीं तो आज ही गिरफ़्तारी होगी।")


def wait(pred, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.2)
    raise SystemExit(f"timed out waiting for {what}")


def agree(tg, chat_id, user_id, lang):
    tg.push_message(chat_id=chat_id, user_id=user_id, lang=lang, text="/start")
    wait(lambda: any(m["reply_markup"] for m in tg.bot_messages(chat_id)), 30, "the consent message")
    consent = [m for m in tg.bot_messages(chat_id) if m["reply_markup"]][-1]
    tg.push_callback(consent["message_id"], "consent:yes", chat_id=chat_id, user_id=user_id, lang=lang)
    yes = W.CONSENT_YES[1 if lang == "hi" else 0]
    wait(lambda: yes in [m["text"] for m in tg.bot_messages(chat_id)], 30, "the thank-you after Yes")


def check(tg, chat_id, timeout, **send):
    before = len(tg.bot_messages(chat_id))
    t0 = time.time()
    tg.push_message(chat_id=chat_id, **send)
    wait(lambda: len(tg.bot_messages(chat_id)) > before, 30, "the waiting message")
    waiting = tg.bot_messages(chat_id)[before]
    wait(lambda: waiting["edits"] > 0, timeout, "the verdict")
    return waiting, waiting["text"], time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("voice")
    ap.add_argument("--out")
    args = ap.parse_args()
    tg = FakeTelegram().start()
    tmp = Path(tempfile.mkdtemp(prefix="tg-e2e-"))
    tok = tmp / "token"
    tok.write_text(TOKEN)
    tok.chmod(0o600)
    env = {**os.environ, "SATYAPAN_TG_TOKEN_FILE": str(tok), "SATYAPAN_TG_API_BASE": tg.url,
           "SATYAPAN_TG_STATE_DIR": str(tmp / "state")}
    proc = subprocess.Popen(["bash", str(REPO / "scripts" / "run_tg_bot.sh")], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    out: list[str] = []
    threading.Thread(target=lambda: [out.append(line) for line in proc.stdout], daemon=True).start()
    engine_pid = None
    try:
        wait(lambda: tg.calls_to("getUpdates") or proc.poll() is not None, 300, "the bot to start polling")
        if proc.poll() is not None:
            print("".join(out))
            raise SystemExit("run_tg_bot.sh stopped before the bot polled")
        m = next((re.search(r"engine pid (\d+)", line) for line in out if "engine pid" in line), None)
        engine_pid = int(m.group(1)) if m else None
        print("".join(out), end="")

        agree(tg, 501, 9001, "en")
        voice = Path(args.voice).read_bytes()
        fid = tg.add_file(voice, "voice.ogg")
        _, voice_reply, voice_s = check(tg, 501, 300, user_id=9001, lang="en",
                                        voice={"file_id": fid, "file_unique_id": "e2e-voice", "duration": 34,
                                               "mime_type": "audio/ogg", "file_size": len(voice)})
        agree(tg, 502, 9002, "hi")
        _, text_reply, text_s = check(tg, 502, 120, user_id=9002, lang="hi", text=SCAM_TEXT)

        log = (REPO / "clips" / "logs" / "tg-bot.log").read_text(encoding="utf-8")
        cases = re.findall(r"check case=(SP-[0-9A-F]{8}) sha256=(\w{64}) verdict=(\w+)", log)[-2:]
        kept = [c for c, _, _ in cases if (REPO / "prototype" / "evidence" / "uploads" / c).exists()]
        leftovers = list((tmp / "state" / "incoming").iterdir())
        # The officer's side of the same cases on the bot's engine, for the report only (the citizen never sees it).
        engine_side = []
        for c, _, _ in cases:
            with urllib.request.urlopen(f"http://127.0.0.1:8100/api/cases/{c}", timeout=10) as r:
                v = json.loads(r.read())["case"]["verdict"]
            engine_side.append(f"{c}: {v['outcome']}, rules {[s['rule_id'] for s in v['signals']]}, "
                               f"media judged by a detector: {'yes' if v.get('scores') else 'no'}; "
                               f"{v['explanation']}")
    finally:
        os.killpg(proc.pid, signal.SIGINT)        # what Ctrl-C in the tmux window sends
        try:
            proc.wait(150)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(30)
        time.sleep(1)
        engine_alive = False
        if engine_pid:
            try:
                os.kill(engine_pid, 0)
                engine_alive = True
                os.kill(engine_pid, signal.SIGTERM)   # the engine this run started, by its own PID
            except ProcessLookupError:
                pass
        tg.stop()

    report = [f"VOICE NOTE ({len(voice)} bytes, chat language en), reply after {voice_s:.0f} s:", voice_reply, "",
              f"SCAM TEXT (chat language hi), reply after {text_s:.0f} s:", SCAM_TEXT, "---", text_reply, "",
              "log lines: " + "; ".join(f"case={c} sha256={h} verdict={v}" for c, h, v in cases),
              "engine side (officer view): " + " | ".join(engine_side),
              f"engine copies left: {kept or 'none'}; downloads left: {leftovers or 'none'}",
              f"run_tg_bot.sh exit code after Ctrl-C: {proc.returncode}; engine still running: {engine_alive}"]
    tail = "".join(out[-8:])
    text = "\n".join(report) + "\n\nlast lines of run_tg_bot.sh:\n" + tail
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    ok = (len(cases) == 2 and not kept and not leftovers and proc.returncode == 0 and not engine_alive
          and voice_reply.endswith(W.OFFICIAL[0]) and text_reply.endswith(W.OFFICIAL[1]))
    print("E2E", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
