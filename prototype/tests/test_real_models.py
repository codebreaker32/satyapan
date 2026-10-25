"""The real models, end to end, wherever they are installed (`satyapan setup-models`); skipped cleanly elsewhere.

The speech is synthetic: the voice Windows ships (System.Speech) reads a scam sentence aloud. That is the one
source of spoken audio every Windows laptop has, it involves no real person's voice, and it doubles as a known
synthetic clip for the audio detector.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from satyapan.forensics import AASISTAudioForensics, decode_audio, default_audio_forensics
from satyapan.media import WHISPER_DIR, ingest
from satyapan.memory import CampaignMemory, meaning_model
from satyapan.pipeline import DATA_DIR
from tests.conftest import NOW

SENTENCE = "This is the Enforcement Directorate. Transfer the full amount to the verification account today."
windows_only = pytest.mark.skipif(not sys.platform.startswith("win"), reason="System.Speech is a Windows voice")
needs_whisper = pytest.mark.skipif(not any(WHISPER_DIR.glob("**/model.bin")), reason="Whisper is not downloaded")
needs_detector = pytest.mark.skipif(not isinstance(default_audio_forensics(), AASISTAudioForensics),
                                    reason="AASIST-L is not installed and calibrated")


@pytest.fixture(scope="module")
def spoken(tmp_path_factory) -> Path:
    if not sys.platform.startswith("win"):
        pytest.skip("System.Speech is a Windows voice")
    path = tmp_path_factory.mktemp("speech") / "spoken.wav"
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{SENTENCE}'); $s.SetOutputToNull()")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=120, capture_output=True)
    if not path.exists() or path.stat().st_size < 10_000:
        pytest.skip("no Windows voice produced audio")
    return path


@pytest.fixture(scope="module")
def recorded(spoken, tmp_path_factory) -> Path:
    """The same speech as a browser saves a voice recording: Opus in a WebM container, named .weba."""
    import av
    import numpy as np
    wav16, _, _ = decode_audio(spoken)
    out = tmp_path_factory.mktemp("rec") / "recording.weba"
    pcm = (np.clip(wav16, -1, 1) * 32767).astype("int16").reshape(1, -1)
    with av.open(str(out), "w", format="webm") as c:
        s = c.add_stream("libopus", rate=48000, layout="mono")
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = 16000
        for p in s.encode(frame):
            c.mux(p)
        for p in s.encode(None):
            c.mux(p)
    return out


@windows_only
@needs_whisper
def test_whisper_transcribes_a_spoken_instruction(spoken):
    ref = ingest(spoken, language="en")
    text = ref.derived_text.lower()
    assert ref.derived_text_engine.startswith("faster-whisper")
    assert "transfer" in text and "account" in text and "enforcement" in text


@windows_only
@needs_detector
def test_the_audio_detector_flags_a_synthetic_voice(spoken):
    """Six of six Windows-voice clips were flagged at the 5% false-alarm threshold during calibration. This is that
    probe as a test: a sanity check that the real model runs and fires, not a claim about modern voice clones."""
    res = default_audio_forensics().analyse(spoken, "en")
    assert res.model == "AASIST-L" and not res.simulated
    assert res.status == "synthetic", (res.status, res.score, res.reason, res.cell)


@windows_only
@needs_whisper
def test_a_browser_recording_uploads_and_is_read(recorded):
    """A .weba voice recording, as the console's Record voice button saves it, goes through the real upload path:
    accepted as audio, transcribed by Whisper, and heard by the audio detector."""
    from fastapi.testclient import TestClient
    import satyapan.api as api
    client = TestClient(api.app)
    cid = client.post("/api/cases", json={"flag": {"reason": "recorded at the counter", "amount_inr": 0}}).json()["case"]["id"]
    client.post(f"/api/cases/{cid}/consent", json={"check": True, "report": False, "memory": False, "lang": "en"})
    with open(recorded, "rb") as f:
        r = client.post(f"/api/cases/{cid}/media", files={"file": ("recording.weba", f.read(), "audio/webm")},
                        data={"language": "en"})
    assert r.status_code == 200, r.text
    media = r.json()["case"]["media"][0]
    assert media["kind"] == "audio" and media["derived_text_engine"].startswith("faster-whisper")
    assert "transfer" in media["derived_text"].lower()
    case = client.post(f"/api/cases/{cid}/run").json()["case"]
    if isinstance(default_audio_forensics(), AASISTAudioForensics):
        audio = [s for s in case["verdict"]["signals"] if s["evidence_key"] == "media:audio"]
        assert audio and audio[0]["detail"]["model"] == "AASIST-L" and not audio[0]["detail"]["simulated"]
    client.post("/api/demo/reset")


@needs_whisper
def test_a_silent_browser_recording_is_refused_with_a_sentence(tmp_path):
    """What a muted microphone gives the browser: 23 s of noise floor after one click, as a browser recorded it. It used
    to run for 79 s in Whisper and come back as a GREY with no text; now it is refused at once, and says why."""
    import time

    import av
    import numpy as np
    from fastapi.testclient import TestClient
    import satyapan.api as api
    wav = np.random.default_rng(0).normal(0, 0.00003, 48000 * 23)
    wav[2400:2420] = 0.003   # the click as the microphone opens
    out = tmp_path / "recording.weba"
    with av.open(str(out), "w", format="webm") as c:
        s = c.add_stream("libopus", rate=48000, layout="mono")
        frame = av.AudioFrame.from_ndarray(wav.astype("float32").reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = 48000
        for p in s.encode(frame):
            c.mux(p)
        for p in s.encode(None):
            c.mux(p)
    client = TestClient(api.app)
    cid = client.post("/api/cases", json={"flag": {"reason": "recorded at the counter", "amount_inr": 0}}).json()["case"]["id"]
    client.post(f"/api/cases/{cid}/consent", json={"check": True, "report": False, "memory": False, "lang": "en"})
    started = time.monotonic()
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("recording.weba", out.read_bytes(), "audio/webm")},
                    data={"language": "hi"})
    assert r.status_code == 415, r.text
    assert "No voice can be heard in 'recording.weba'" in r.json()["detail"] and "microphone" in r.json()["detail"]
    assert time.monotonic() - started < 30, "silence must not reach Whisper's slow retry path"
    client.post("/api/demo/reset")


@pytest.mark.skipif(meaning_model() is None, reason="the meaning model is not downloaded")
def test_the_meaning_layer_catches_a_translated_copy_of_a_known_campaign():
    """A Hindi translation of the confirmed RBI gold-scheme script shares no words with it. It is caught on meaning,
    and only because it names the same body; the threshold is the calibrated one (data/eval/memory_calibration.json)."""
    from satyapan.extract import RulesExtractor
    mem = CampaignMemory(DATA_DIR / "mocks" / "campaign_memory.json", now=NOW)
    if mem.meaning_threshold is None:
        pytest.skip("campaign memory is not calibrated for meaning")
    pairs = {p["id"]: p for p in json.loads((DATA_DIR / "eval" / "memory_pairs.json").read_text(encoding="utf-8"))["copies"]}
    hit = mem.match(RulesExtractor().extract(pairs["MP-11"]["text"]))
    assert hit and hit["entry"]["id"] == "CM-0002" and hit["how"] == "similar meaning (model)"
    # switched off, the same message is not "seen before" at all: the layer is what caught it
    off = CampaignMemory(DATA_DIR / "mocks" / "campaign_memory.json", now=NOW, meaning=False)
    assert off.match(RulesExtractor().extract(pairs["MP-11"]["text"])) is None
