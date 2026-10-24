"""How a voice note reached the bank travels with it to the voice detector, and the DF Arena adapter maps the team
repository's result onto this engine's ForensicResult."""
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from satyapan.forensics import TEAM_REPO, ForensicResult
from satyapan.models import Flag
from satyapan.pipeline import Satyapan


class RecordingDetector:
    """Stands in for the voice detector and remembers what it was asked."""
    accepts_channel = True

    def __init__(self):
        self.calls = []

    def analyse(self, path, language="hi", channel=None):
        self.calls.append((Path(path).name, language, channel))
        return ForensicResult(kind="audio", status="abstain", reason="stub", model="stub")


def tone_wav(path: Path, seconds: float = 3.0) -> Path:
    t = np.arange(int(16000 * seconds)) / 16000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes())
    return path


def test_a_counter_recording_reaches_the_detector_as_a_replay(tmp_path):
    det = RecordingDetector()
    engine = Satyapan(audio=det)
    case = engine.open_case(Flag(reason="counter", amount_inr=0))
    engine.add_media(case, tone_wav(tmp_path / "rec.wav"), derived_text="hello", channel="live-replay")
    engine.add_media(case, tone_wav(tmp_path / "note.wav"), derived_text="hello")
    engine.run(case)
    assert ("rec.wav", case.claim.language_hint, "live-replay") in det.calls
    assert ("note.wav", case.claim.language_hint, None) in det.calls


def test_the_api_accepts_only_the_replay_channel(tmp_path):
    import satyapan.api as api
    client = TestClient(api.app)
    cid = client.post("/api/cases", json={"flag": {"reason": "counter", "amount_inr": 0}}).json()["case"]["id"]
    data = tone_wav(tmp_path / "rec.wav").read_bytes()
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("rec.wav", data, "audio/wav")},
                    data={"derived_text": "hello", "channel": "clean"})
    assert r.status_code == 422 and "live-replay" in r.text
    client.post("/api/demo/reset")


@pytest.mark.skipif(not (TEAM_REPO / "forensics" / "audio.py").exists() or not (TEAM_REPO / "calibration" / "audio.json").exists(),
                    reason="the team repository (codebreaker32/satyapan) with its voice calibration is not checked out")
def test_the_dfarena_adapter_maps_the_team_result(tmp_path):
    from satyapan.forensics import DFArenaAudioForensics
    adapter = DFArenaAudioForensics(TEAM_REPO)
    adapter.detector._scorer = lambda windows: [0.99] * len(windows)      # no model load in the suite
    r = adapter.analyse(tone_wav(tmp_path / "v.wav", 6), language="mixed", channel="live-replay")
    assert r.kind == "audio" and r.status in ("synthetic", "abstain", "clean") and r.cell.startswith("hi/")
    assert adapter.label.mock is False and "non-commercial" in adapter.label.production_source
