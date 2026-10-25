"""The Telegram bot (bot/), against a fake Telegram API and a stub engine, both local HTTP servers.

Nothing here talks to api.telegram.org or to a real engine. scripts/tg_bot_e2e.py does the same against a real engine.
"""
import hashlib
import logging
import os
import re
import threading
import time
from pathlib import Path

import pytest

from bot import app, wording as W
from bot.clients import EngineClient, TelegramClient
from bot.store import ChatStore, PendingCleanup, RateLimiter
from fake_telegram import TOKEN, FakeTelegram, StubEngine, stub_view

OFFICIAL_EN = W.OFFICIAL[0]
OFFICIAL_HI = W.OFFICIAL[1]
VOICE = b"OggS" + bytes(range(256)) * 40


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def world(tmp_path):
    tg = FakeTelegram().start()
    eng = StubEngine(tmp_path / "uploads").start()
    clock = Clock()
    state = tmp_path / "state"
    bot = app.Bot(TelegramClient(TOKEN, base=tg.url, timeout=5), EngineClient(eng.url, timeout=10),
                  ChatStore(state / "chats.json"), RateLimiter(10, 3600.0, clock=clock),
                  PendingCleanup(state / "pending-cleanup.json"), tmp_path / "uploads", state / "incoming",
                  sleep=lambda s: None)
    bot.clock = clock
    yield tg, eng, bot
    tg.stop()
    eng.stop()


def step(bot):
    """One poll, then every queued check, as the worker would run them."""
    bot.poll_once(timeout=0)
    bot.drain()


def agree(tg, bot, chat_id=42, user_id=7, lang="en"):
    tg.push_message(chat_id=chat_id, user_id=user_id, lang=lang, text="/start")
    step(bot)
    consent_msg = [m for m in tg.bot_messages(chat_id) if m["reply_markup"]][-1]
    tg.push_callback(consent_msg["message_id"], "consent:yes", chat_id=chat_id, user_id=user_id, lang=lang)
    step(bot)
    return consent_msg


# ---------------------------------------------------------------- consent

def test_nothing_is_checked_before_yes(world):
    tg, eng, bot = world
    tg.push_message(text="CBI officer here, transfer 2 lakh to this account now")
    step(bot)
    msgs = tg.bot_messages()
    assert len(msgs) == 1 and msgs[0]["reply_markup"] == W.CONSENT_BUTTONS
    assert W.CONSENT_EN in msgs[0]["text"] and W.CONSENT_HI in msgs[0]["text"]
    assert not eng.cases, "a message was sent to the engine before consent"
    # what the consent says: what is checked, deletion, hash and verdict kept, no score
    for phrase in ("voice note", "deleted after the check", "fingerprint", "hash", "never a score"):
        assert phrase in msgs[0]["text"]

    tg.push_callback(msgs[0]["message_id"], "consent:no")
    step(bot)
    assert tg.texts()[-1] == W.CONSENT_NO[0]
    assert tg.bot_messages()[0]["reply_markup"] is None, "the buttons stay pressable after an answer"
    tg.push_message(text="CBI officer here, transfer 2 lakh now")
    step(bot)
    assert not eng.cases
    assert tg.bot_messages()[-1]["reply_markup"] == W.CONSENT_BUTTONS   # asked again, nothing checked

    tg.push_callback(tg.bot_messages()[-1]["message_id"], "consent:yes")
    step(bot)
    assert tg.texts()[-1] == W.CONSENT_YES[0]
    tg.push_message(text="CBI officer here, transfer 2 lakh now")
    step(bot)
    assert len(eng.cases) == 1


def test_consent_is_asked_in_the_citizens_language_first(world):
    tg, eng, bot = world
    tg.push_message(text="/start", lang="hi")
    step(bot)
    assert tg.texts()[0].startswith(W.CONSENT_HI)


def test_stop_withdraws_consent(world):
    tg, eng, bot = world
    agree(tg, bot)
    tg.push_message(text="/stop")
    step(bot)
    assert tg.texts()[-1] == W.CONSENT_WITHDRAWN[0]
    tg.push_message(text="pay now")
    step(bot)
    assert not eng.cases


def test_consent_is_kept_in_a_private_file(world, tmp_path):
    tg, eng, bot = world
    agree(tg, bot)
    state = tmp_path / "state"
    assert os.stat(state).st_mode & 0o777 == 0o700
    assert os.stat(state / "chats.json").st_mode & 0o777 == 0o600
    assert ChatStore(state / "chats.json").consented(42)


def test_groups_are_not_checked(world):
    tg, eng, bot = world
    tg.push_message(chat_id=-100, chat_type="group", text="/start")
    tg.push_message(chat_id=-100, chat_type="group", text="transfer money now")
    step(bot)
    assert tg.texts(-100) == [W.PRIVATE_ONLY[0]]
    assert not eng.cases


# ---------------------------------------------------------------- checks

def test_text_check(world):
    tg, eng, bot = world
    agree(tg, bot)
    text = "This is CBI. You are under digital arrest. Transfer Rs 2,00,000 to account 1234567890 now."
    tg.push_message(text=text)
    bot.poll_once(timeout=0)
    waiting = tg.bot_messages()[-1]
    assert waiting["text"] == W.WAITING[0]   # said at once, before the check runs
    bot.drain()
    (cid, case), = eng.cases.items()
    assert case["flag"] == {"reason": "Forwarded by a citizen on Telegram", "amount_inr": 0,
                            "customer_ref": "telegram-citizen"}
    assert case["consent"] == {"check": True, "report": False, "memory": False, "lang": "en"}
    assert case["text"]["text"] == text
    assert case["steps"] == ["consent", "text", "run"]
    reply = tg.bot_messages()[-1]
    assert reply["message_id"] == waiting["message_id"] and reply["edits"] == 1   # the waiting message, edited
    assert reply["text"].startswith("RED\nStop and verify through the official channel")
    assert "1. The message says it is from the police" in reply["text"]
    assert reply["text"].endswith(OFFICIAL_EN)


def test_media_check_uploads_and_deletes(world, tmp_path, caplog):
    tg, eng, bot = world
    agree(tg, bot, lang="hi")
    fid = tg.add_file(VOICE, "voice.ogg")
    caplog.set_level(logging.INFO, logger="satyapan.bot")
    tg.push_message(lang="hi", voice={"file_id": fid, "file_unique_id": "u1", "duration": 9,
                                      "mime_type": "audio/ogg", "file_size": len(VOICE)})
    bot.poll_once(timeout=0)
    assert tg.texts()[-1] == W.WAITING[1]
    bot.drain()
    (cid, case), = eng.cases.items()
    assert case["steps"] == ["consent", "media", "run"]
    assert case["media"]["file"] == VOICE
    assert case["media"]["language"] == b"hi"           # Hindi for language_code "hi"
    assert case["filename"] == "telegram.ogg"            # never the citizen's own file name
    assert "derived_text" not in case["media"]
    reply = tg.texts()[-1]
    assert reply.startswith("RED (लाल)\nरुकिए।") and reply.endswith(OFFICIAL_HI)
    # deleted: the download, the engine's kept copy, and the pending record
    assert not (tmp_path / "uploads" / cid).exists()
    assert list((tmp_path / "state" / "incoming").iterdir()) == []
    assert PendingCleanup(tmp_path / "state" / "pending-cleanup.json").all() == []
    # the one log line: case id, sha256, verdict
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("check ")]
    assert lines == [f"check case={cid} sha256={hashlib.sha256(VOICE).hexdigest()} verdict=RED"]


@pytest.mark.parametrize("field,payload,ext", [
    ("video", {"duration": 20, "mime_type": "video/mp4"}, ".mp4"),
    ("video_note", {"duration": 20, "length": 240}, ".mp4"),
    ("audio", {"duration": 20, "mime_type": "audio/mpeg", "file_name": "call.mp3"}, ".mp3"),
    ("document", {"mime_type": "application/pdf", "file_name": "summons.pdf"}, ".pdf"),
    ("document", {"mime_type": "image/png", "file_name": "notice.png"}, ".png"),
])
def test_each_kind_of_file_goes_to_the_engine(world, field, payload, ext):
    tg, eng, bot = world
    agree(tg, bot)
    fid = tg.add_file(b"x" * 100, "f" + ext)
    tg.push_message(**{field: {"file_id": fid, "file_unique_id": "u", **payload}})
    step(bot)
    (cid, case), = eng.cases.items()
    assert case["filename"] == "telegram" + ext


def test_photo_takes_the_largest_size(world):
    tg, eng, bot = world
    agree(tg, bot)
    small, big = tg.add_file(b"s" * 10, "s.jpg"), tg.add_file(b"b" * 50, "b.jpg")
    tg.push_message(photo=[{"file_id": small, "file_unique_id": "a", "width": 90, "height": 60, "file_size": 10},
                           {"file_id": big, "file_unique_id": "b", "width": 1280, "height": 853, "file_size": 50}])
    step(bot)
    (cid, case), = eng.cases.items()
    assert case["media"]["file"] == b"b" * 50 and case["filename"] == "telegram.jpg"


@pytest.mark.parametrize("fields", [
    {"sticker": {"file_id": "S", "file_unique_id": "s", "type": "regular", "width": 1, "height": 1}},
    {"animation": {"file_id": "A", "file_unique_id": "a"}, "document": {"file_id": "A", "file_unique_id": "a",
                                                                       "mime_type": "video/mp4"}},
    {"document": {"file_id": "Z", "file_unique_id": "z", "mime_type": "application/zip", "file_name": "x.zip"}},
    {"location": {"latitude": 28.5, "longitude": 77.2}},
])
def test_unsupported_types_get_the_list_of_what_works(world, fields):
    tg, eng, bot = world
    agree(tg, bot)
    tg.push_message(**fields)
    step(bot)
    assert tg.texts()[-1] == W.WHAT_WORKS[0]
    for kind in ("voice note", "video", "photo of a notice", "PDF", "text"):
        assert kind in tg.texts()[-1]
    assert not eng.cases


def test_over_20_mb_is_refused_before_download(world):
    tg, eng, bot = world
    agree(tg, bot)
    fid = tg.add_file(b"x", "v.mp4", reported_size=25 * 1024 * 1024)
    tg.push_message(video={"file_id": fid, "file_unique_id": "u", "duration": 30, "file_size": 25 * 1024 * 1024})
    step(bot)
    assert "larger than 20 MB" in tg.texts()[-1] and tg.texts()[-1].endswith(OFFICIAL_EN)
    assert not eng.cases and not tg.calls_to("getFile")


def test_size_unknown_until_get_file(world):
    tg, eng, bot = world
    agree(tg, bot)
    fid = tg.add_file(b"x", "v.mp4", reported_size=25 * 1024 * 1024)
    tg.push_message(video={"file_id": fid, "file_unique_id": "u", "duration": 30})   # no file_size in the message
    step(bot)
    assert "larger than 20 MB" in tg.texts()[-1]
    assert all("media" not in c["steps"] for c in eng.cases.values())


def test_language_commands(world):
    tg, eng, bot = world
    agree(tg, bot, lang="en")
    tg.push_message(text="/hindi")
    step(bot)
    assert tg.texts()[-1] == W.LANG_SET["hi"]
    fid = tg.add_file(VOICE)
    tg.push_message(voice={"file_id": fid, "file_unique_id": "u", "duration": 5}, lang="en")
    step(bot)
    (cid, case), = eng.cases.items()
    assert case["media"]["language"] == b"hi" and tg.texts()[-1].endswith(OFFICIAL_HI)


# ---------------------------------------------------------------- the reply's wording rules

SCORE_OR_NUMBER = re.compile(r"\d+\s*%|\bscore\b|स्कोर|\b0\.\d+|\b\d\.\d+\b", re.I)
WORDS = re.compile(r"\b(safe|fake|fraud|genuine)", re.I)


def reply_for(view, lang):
    text = W.verdict_reply(view, lang)
    assert not SCORE_OR_NUMBER.search(text), text
    assert not WORDS.search(text), text
    assert not W.forbidden_in(text), text
    assert text.endswith(OFFICIAL_HI if lang == "hi" else OFFICIAL_EN)
    assert "1930" in text and "cybercrime.gov.in" in text
    return text


@pytest.mark.parametrize("lang", ["en", "hi"])
@pytest.mark.parametrize("outcome", ["RED", "AMBER", "GREY", "MATCHES"])
def test_reply_rules_hold_for_every_outcome(outcome, lang):
    text = reply_for(stub_view("SP-00000001", outcome), lang)
    assert text.split("\n")[0] == W.pick(lang, *W.LABEL[W.shown_outcome(outcome)])


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_matches_is_shown_with_greys_wording(lang):
    text = reply_for(stub_view("SP-00000001", "MATCHES"), lang)
    grey = reply_for(stub_view("SP-00000001", "GREY", lang_cards={"en": {"reasons": []}, "hi": {"reasons": []}}), lang)
    assert text == grey
    assert "MATCHES" not in text and "Matches our records" not in text and "मेल खाता" not in text
    assert W.pick(lang, *W.GREY_NOTE) in text   # could not be confirmed; not a confirmation it can be trusted
    assert "police" not in text                  # none of a MATCHES card's reasons


def test_grey_says_it_is_not_a_confirmation():
    text = reply_for(stub_view("SP-00000001", "GREY"), "en")
    assert "could not confirm" in text.lower() and "not a confirmation" in text


def test_reasons_that_break_the_rules_are_left_out():
    cards = {"en": {"headline": "Stop and verify through the official channel", "reasons": [
        {"text": "Detector score 0.91 on the voice.", "rule_id": "R-AUDIO-SYNTH"},
        {"text": "This is a fraud, the voice is fake.", "rule_id": "R-VIDEO-SYNTH"},
        {"text": "We have no record of sending this message.", "rule_id": "R-BANK-SELF"},
        {"text": "The police never ask for money on a call.", "rule_id": "R-DIGITAL-ARREST-PAY"},
        {"text": "It asks you to move money to a safe account.", "rule_id": "R-AGENCY-PAY"},
        {"text": "The payee is a new account.", "rule_id": "R-RBI-INV"},
        {"text": "The website was registered last week.", "rule_id": "R-WEBSITE-NEW"},
        {"text": "A fourth clean reason.", "rule_id": "R-CAMPAIGN-MATCH"}]}}
    signals = [{"rule_id": "R-BANK-SELF", "family": "F2", "severity": "hard"}]
    text = reply_for(stub_view("SP-00000001", "RED", lang_cards=cards, signals=signals), "en")
    assert "1. The police never ask" in text and "2. The payee is a new account." in text
    assert "3. The website was registered" in text and "fourth" not in text   # three at most
    assert "no record" not in text   # the bank's own records are not the citizen's


def test_mock_lookups_are_not_shown_and_a_detector_fills_the_slot():
    """The voice note of the end-to-end run: the card's three were digital arrest, the suspect registry (a labelled
    mock) and the payee look-up (bank records). The citizen sees the first and what the voice check found."""
    cards = {"en": {"headline": "Stop and verify through the official channel", "reasons": [
        {"text": "There is no digital arrest in Indian law.", "rule_id": "R-DIGITAL-ARREST-PAY"},
        {"text": "We checked, and this account is already on the government's cyber-crime suspect list.",
         "rule_id": "R-SUSPECT"},
        {"text": "The account belongs to someone else.", "rule_id": "R-PAYEE-NAME"}]}}
    signals = [{"rule_id": "R-DIGITAL-ARREST-PAY", "family": "F1", "severity": "hard"},
               {"rule_id": "R-SUSPECT", "family": "F1", "severity": "hard"},
               {"rule_id": "R-PAYEE-NAME", "family": "F2", "severity": "hard"},
               {"rule_id": "R-PRESSURE-CUES", "family": "F5", "severity": "soft", "reason_en": "Pressure."},
               {"rule_id": "R-AUDIO-SYNTH", "family": "F3", "severity": "soft",
                "reason_en": "This voice shows signs of being computer-generated (high). It is one of the checks, "
                             "not proof on its own.", "detail": {"score": 0.97, "simulated": False}}]
    text = reply_for(stub_view("SP-00000001", "RED", lang_cards=cards, signals=signals), "en")
    assert "1. There is no digital arrest" in text
    assert "2. This voice shows signs of being computer-generated (high)." in text
    assert "suspect list" not in text and "belongs to" not in text and "Pressure" not in text and "3." not in text


def test_a_simulated_detector_result_is_never_shown():
    cards = {"en": {"headline": "Verify before paying", "reasons": []}}
    signals = [{"rule_id": "R-AUDIO-SYNTH", "family": "F3", "severity": "soft",
                "reason_en": "This voice shows signs of being computer-generated (high) (SIMULATED).",
                "detail": {"simulated": True}},
               {"rule_id": "R-VIDEO-SYNTH", "family": "F3", "severity": "soft",
                "reason_en": "The face shows signs of manipulation (moderate) (SIMULATED).", "detail": {}}]
    text = reply_for(stub_view("SP-00000001", "AMBER", lang_cards=cards, signals=signals), "en")
    assert "voice" not in text and "face" not in text and W.NO_SHOWN_REASON[0] in text


def test_red_with_no_reason_left_still_says_why():
    cards = {"en": {"headline": "Stop and verify through the official channel",
                    "reasons": [{"text": "We have no record of sending this.", "rule_id": "R-BANK-SELF"}]}}
    text = reply_for(stub_view("SP-00000001", "RED", lang_cards=cards), "en")
    assert W.NO_SHOWN_REASON[0] in text


def test_every_message_the_bot_sent_keeps_the_rules(world):
    tg, eng, bot = world
    agree(tg, bot)
    for outcome in ("RED", "AMBER", "GREY", "MATCHES"):
        eng.view = lambda cid, o=outcome: stub_view(cid, o)
        tg.push_message(text=f"message for {outcome}")
        step(bot)
    for text in tg.texts():
        if text.startswith(W.CONSENT_EN):
            continue   # the consent names "score" to say there is none
        assert not SCORE_OR_NUMBER.search(text) and not WORDS.search(text) and not W.forbidden_in(text), text
    replies = tg.texts()[-4:]
    assert [r.split("\n")[0] for r in replies] == ["RED", "AMBER", "GREY", "GREY"]
    assert all(r.endswith(OFFICIAL_EN) for r in replies)


# ---------------------------------------------------------------- limits and failures

def test_rate_limit_ten_an_hour(world):
    tg, eng, bot = world
    agree(tg, bot)
    for i in range(11):
        tg.push_message(text=f"pay now {i}")
    step(bot)
    assert len(eng.cases) == 10
    last = tg.texts()[-1]
    assert "10 messages for checking in the last hour" in last and "about 60 minutes" in last
    assert "Thank you" in last and last.endswith(OFFICIAL_EN)
    bot.clock.t += 3600
    tg.push_message(text="pay now again")
    step(bot)
    assert len(eng.cases) == 11


def test_rate_limit_is_per_user(world):
    tg, eng, bot = world
    agree(tg, bot, chat_id=42, user_id=7)
    agree(tg, bot, chat_id=43, user_id=8)
    for i in range(10):
        tg.push_message(chat_id=42, user_id=7, text=f"pay {i}")
    tg.push_message(chat_id=43, user_id=8, text="pay")
    step(bot)
    assert len(eng.cases) == 11


def test_engine_failure_still_replies_and_deletes(world, tmp_path):
    tg, eng, bot = world
    agree(tg, bot)
    eng.fail["run"] = 500
    fid = tg.add_file(VOICE)
    tg.push_message(voice={"file_id": fid, "file_unique_id": "u", "duration": 5})
    step(bot)
    (cid, case), = eng.cases.items()
    assert tg.texts()[-1] == W.failed("en")
    assert not (tmp_path / "uploads" / cid).exists()
    assert list((tmp_path / "state" / "incoming").iterdir()) == []


def test_unreadable_file(world):
    tg, eng, bot = world
    agree(tg, bot)
    eng.fail["media"] = 415
    fid = tg.add_file(b"not audio")
    tg.push_message(voice={"file_id": fid, "file_unique_id": "u", "duration": 5})
    step(bot)
    assert tg.texts()[-1] == W.unreadable("en")


def test_engine_down(world):
    tg, eng, bot = world
    agree(tg, bot)
    bot.engine = EngineClient("http://127.0.0.1:9", timeout=2)
    tg.push_message(text="pay now")
    step(bot)
    assert tg.texts()[-1] == W.failed("en")


def test_leftovers_are_deleted_at_start(world, tmp_path):
    tg, eng, bot = world
    left = tmp_path / "uploads" / "SP-0000ABCD"
    left.mkdir(parents=True)
    (left / "00-telegram.ogg").write_bytes(b"x")
    other = tmp_path / "uploads" / "SP-0000FFFF"   # not ours: never touched
    other.mkdir()
    bot.pending.add("SP-0000ABCD")
    bot.pending.add("../../etc")                    # not a case id: never handed to rmtree
    (bot.incoming / "SP-00000009").mkdir()
    bot.sweep()
    assert not left.exists() and other.exists()
    assert list(bot.incoming.iterdir()) == []


def test_one_bad_update_does_not_stop_the_rest(world):
    tg, eng, bot = world
    agree(tg, bot)
    tg.push_message(voice={"duration": 3})              # no file_id: handling it raises
    tg.push({"message": "not a dict"})
    tg.push({"edited_message": {"text": "x"}})
    tg.push_message(text="pay now")
    step(bot)
    assert len(eng.cases) == 1 and tg.texts()[-1].startswith("RED")


def test_network_errors_back_off_and_retry(world):
    tg, eng, bot = world
    agree(tg, bot)
    tg.fail["getUpdates"] = [502, 502, 429]
    bot.poll_timeout = 1
    bot.backoff = (0.05, 0.2)
    t = threading.Thread(target=bot.run, daemon=True)
    t.start()
    tg.push_message(text="pay now")
    assert tg.wait_for(lambda: tg.texts()[-1].startswith("RED"), timeout=20)
    bot.stopping.set()
    t.join(5)
    assert not t.is_alive()
    assert len(tg.calls_to("getUpdates")) >= 4


def test_shutdown_answers_what_is_still_queued(world):
    tg, eng, bot = world
    agree(tg, bot)
    tg.push_message(text="one")
    tg.push_message(text="two")
    bot.poll_once(timeout=0)
    bot.shutdown(wait=0)
    assert tg.texts()[-2:] == [W.stopped("en")] * 2
    assert not eng.cases
    assert tg.calls_to("getUpdates")[-1]["offset"] == bot.offset   # handled updates confirmed to Telegram


# ---------------------------------------------------------------- the token file

def test_missing_token_file(tmp_path):
    with pytest.raises(app.TokenProblem) as e:
        app.load_token(tmp_path / "nope")
    assert "BotFather" in str(e.value) and "install -m 600" in str(e.value)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660])
def test_token_file_readable_by_others_is_refused(tmp_path, mode):
    p = tmp_path / "tok"
    p.write_text(TOKEN)
    p.chmod(mode)
    with pytest.raises(app.TokenProblem) as e:
        app.load_token(p)
    assert "chmod 600" in str(e.value) and TOKEN not in str(e.value)


def test_token_file_that_is_not_a_token(tmp_path):
    p = tmp_path / "tok"
    p.write_text("hello")
    p.chmod(0o600)
    with pytest.raises(app.TokenProblem):
        app.load_token(p)


def test_private_token_file_is_read(tmp_path):
    p = tmp_path / "tok"
    p.write_text(TOKEN + "\n")
    p.chmod(0o600)
    assert app.load_token(p) == TOKEN


def test_main_refuses_and_never_prints_the_token(tmp_path, monkeypatch, capsys):
    p = tmp_path / "tok"
    p.write_text(TOKEN)
    p.chmod(0o644)
    monkeypatch.setenv("SATYAPAN_TG_TOKEN_FILE", str(p))
    monkeypatch.setenv("SATYAPAN_TG_STATE_DIR", str(tmp_path / "state"))
    assert app.main(["--check-token"]) == 2
    out = capsys.readouterr()
    assert "can be read by other users" in out.err and TOKEN not in out.out + out.err
    monkeypatch.setenv("SATYAPAN_TG_TOKEN_FILE", str(tmp_path / "missing"))
    assert app.main([]) == 2
    assert "No Telegram bot token" in capsys.readouterr().err


def test_main_refuses_the_demo_engine(tmp_path, monkeypatch, capsys):
    p = tmp_path / "tok"
    p.write_text(TOKEN)
    p.chmod(0o600)
    monkeypatch.setenv("SATYAPAN_TG_TOKEN_FILE", str(p))
    assert app.main(["--api", "http://127.0.0.1:8000"]) == 2
    assert "demo's engine" in capsys.readouterr().err


def test_main_runs_and_stops_on_sigterm(tmp_path, monkeypatch):
    """The real entry point against the fake servers: consent, a check, then SIGTERM stops it cleanly."""
    import signal
    import subprocess
    import sys
    tg = FakeTelegram().start()
    eng = StubEngine(tmp_path / "uploads").start()
    try:
        p = tmp_path / "tok"
        p.write_text(TOKEN)
        p.chmod(0o600)
        env = {**os.environ, "SATYAPAN_TG_TOKEN_FILE": str(p), "SATYAPAN_TG_STATE_DIR": str(tmp_path / "state"),
               "PYTHONPATH": str(Path(app.__file__).resolve().parent.parent)}
        proc = subprocess.Popen([sys.executable, "-m", "bot", "--api", eng.url, "--uploads", str(tmp_path / "uploads"),
                                 "--telegram-api", tg.url, "--log", str(tmp_path / "bot.log")],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tg.push_message(text="/start")
        assert tg.wait_for(lambda: any(m["reply_markup"] for m in tg.bot_messages()), timeout=20)
        tg.push_callback(tg.bot_messages()[0]["message_id"], "consent:yes")
        tg.push_message(text="pay now")
        assert tg.wait_for(lambda: tg.texts()[-1].startswith("RED"), timeout=20)
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=60)
        assert proc.returncode == 0, out
        assert "stopped" in out and TOKEN not in out
        log = (tmp_path / "bot.log").read_text()
        assert TOKEN not in log and "pay now" not in log and re.search(r"check case=SP-\w+ sha256=\w{64} verdict=RED", log)
        assert os.stat(tmp_path / "bot.log").st_mode & 0o077 == 0
    finally:
        tg.stop()
        eng.stop()
