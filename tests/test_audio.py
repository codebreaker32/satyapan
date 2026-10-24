"""Voice detector tests. Fast: a stub scorer stands in for DF Arena.
The real-model check runs only with RUN_SLOW=1 (it loads the 1.7 GB DF Arena 500M from the Hugging Face cache)."""
import os
import wave
from pathlib import Path

import numpy as np
import pytest

from forensics.audio import (LIVE_REPLAY, SAMPLE_RATE, WINDOW, AudioSettings, DFArenaAudioForensics, channel_for,
                             speech_mask, speech_windows, spoof_probability)
from forensics.common import Calibration, CellCalibration

CAL = Calibration(model="stub", cells={
    "hi/clean": CellCalibration(t_fpr5=0.8, t_fpr20=0.5, t_fpr1=0.95, n_real=100, n_fake=50),
    "hi/whatsapp-opus": CellCalibration(t_fpr5=0.7, t_fpr20=0.4, n_real=30, n_fake=30),
})


def voice(seconds: float, level: float = 0.1, seed: int = 0) -> np.ndarray:
    """A speech-like signal: a 150 Hz tone with syllable-rate bursts (4 per second) over a quiet noise floor."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    bursts = (np.sin(2 * np.pi * 4 * t) > -0.3).astype(np.float32)
    return (level * bursts * np.sin(2 * np.pi * 150 * t) + rng.normal(0, 1e-4, len(t))).astype(np.float32)


def write_wav(path: Path, wav: np.ndarray, rate: int = SAMPLE_RATE) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def stub(scores):
    """A scorer that returns the given scores in turn, one per window."""
    calls = []

    def score(windows):
        calls.append(len(windows))
        assert all(len(w) == WINDOW for w in windows), "every window must be the model's input length"
        return [scores[i % len(scores)] for i in range(len(windows))]
    score.calls = calls
    return score


def detector(scores, **kw) -> DFArenaAudioForensics:
    return DFArenaAudioForensics(calibration=CAL, scorer=stub(scores), name="stub", **kw)


@pytest.mark.parametrize("score,status,band", [(0.97, "synthetic", "high"), (0.85, "synthetic", "moderate"),
                                               (0.6, "abstain", ""), (0.2, "clean", "")])
def test_each_band_maps_to_the_right_status(tmp_path, score, status, band):
    r = detector([score]).analyse(write_wav(tmp_path / "v.wav", voice(8)), language="hi")
    assert (r.status, r.band, r.cell) == (status, band, "hi/clean")
    assert r.score == score and r.officer_line()


def test_a_short_clip_abstains(tmp_path):
    r = detector([0.99]).analyse(write_wav(tmp_path / "v.wav", voice(1.2)))
    assert r.status == "abstain" and "needs 2 s" in r.reason


def test_a_silent_recording_abstains_without_running_the_model(tmp_path):
    s = stub([0.99])
    det = DFArenaAudioForensics(calibration=CAL, scorer=s, name="stub")
    rng = np.random.default_rng(1)
    r = det.analyse(write_wav(tmp_path / "muted.wav", rng.normal(0, 3e-5, SAMPLE_RATE * 10).astype(np.float32)))
    assert r.status == "abstain" and r.reason == "no voice can be heard in the recording"
    assert s.calls == [], "a muted microphone must never reach the model"


def test_an_uncalibrated_cell_abstains(tmp_path):
    r = detector([0.99]).analyse(write_wav(tmp_path / "v.wav", voice(8)), language="en")
    assert r.status == "abstain" and r.reason == "not calibrated for this kind of input" and r.cell == "en/clean"


def test_windows_that_disagree_abstain(tmp_path):
    r = detector([0.05, 0.95]).analyse(write_wav(tmp_path / "v.wav", voice(12)))
    assert r.status == "abstain" and "disagree" in r.reason


def test_live_replay_never_says_clean_but_still_flags(tmp_path):
    p = write_wav(tmp_path / "v.wav", voice(8))
    low = detector([0.1]).analyse(p, channel=LIVE_REPLAY)
    assert low.status == "abstain" and "replayed through a speaker" in low.reason
    high = detector([0.9]).analyse(p, channel=LIVE_REPLAY)
    assert high.status == "synthetic" and high.cell == "hi/live-replay"   # judged on the Opus thresholds meanwhile


def test_channel_from_codec_and_rate():
    assert channel_for("opus", 48000) == "whatsapp-opus"
    assert channel_for("mp3", 8000) == "phone-8k"
    assert channel_for("amr_nb", 8000) == "phone-8k"
    assert channel_for("pcm_s16le", 16000) == "clean"


def test_windows_cover_the_speech_and_are_capped():
    st = AudioSettings()
    wav = np.concatenate([np.zeros(SAMPLE_RATE * 5, np.float32), voice(30), np.zeros(SAMPLE_RATE * 5, np.float32)])
    ws = speech_windows(wav, speech_mask(wav, st), st)
    assert len(ws) == st.max_windows and all(len(w) == WINDOW for w in ws)
    short = voice(3.5)
    assert [len(w) for w in speech_windows(short, speech_mask(short, st), st)] == [WINDOW]   # tiled, like DF Arena


def test_the_voice_in_a_video_is_checked(tmp_path):
    av = pytest.importorskip("av")
    path = tmp_path / "clip.mp4"
    wav = voice(6)
    with av.open(str(path), "w") as c:
        v = c.add_stream("mpeg4", rate=10)
        v.width, v.height, v.pix_fmt = 64, 64, "yuv420p"
        a = c.add_stream("aac", rate=SAMPLE_RATE, layout="mono")
        for i in range(60):
            for pk in v.encode(av.VideoFrame.from_ndarray(np.full((64, 64, 3), i, np.uint8), format="rgb24")):
                c.mux(pk)
        frame = av.AudioFrame.from_ndarray(wav.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        for pk in a.encode(frame):
            c.mux(pk)
        for s in (v, a):
            for pk in s.encode(None):
                c.mux(pk)
    r = detector([0.9]).analyse(path)
    assert r.status == "synthetic" and r.extra["speech_s"] >= 2


def test_a_missing_or_broken_file_abstains(tmp_path):
    assert detector([0.9]).analyse(tmp_path / "nope.wav").reason == "the file was not found"
    bad = tmp_path / "bad.ogg"
    bad.write_bytes(b"not audio at all")
    r = detector([0.9]).analyse(bad)
    assert r.status == "abstain" and r.reason.startswith("the audio could not be read")


@pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="loads DF Arena 500M; set RUN_SLOW=1")
def test_real_model_scores_a_clip(tmp_path):
    clip = os.environ.get("SMOKE_AUDIO")
    path = Path(clip) if clip else write_wav(tmp_path / "v.wav", voice(6))
    det = DFArenaAudioForensics(calibration=Calibration.load(Path("calibration/audio.json"))
                                if Path("calibration/audio.json").exists() else None)
    r = det.analyse(path)
    assert r.model.startswith("DF_Arena_500M_V_1@")
    assert r.score is None or 0.0 <= r.score <= 1.0


def test_spoof_probability_keeps_apart_what_float32_softmax_ties():
    import math
    assert spoof_probability(2.0, 0.0) == pytest.approx(1 / (1 + math.exp(-2)))
    high, higher = spoof_probability(18.0, 0.0), spoof_probability(22.0, 0.0)
    assert high < higher < 1.0                       # float32 softmax gives exactly 1.0 for both
    assert np.float32(1 / (1 + np.exp(np.float32(-18)))) == np.float32(1.0)
    assert spoof_probability(-800.0, 0.0) == 0.0 and spoof_probability(800.0, 0.0) == 1.0


def test_the_joined_entry_point_finds_the_voice_detector(tmp_path):
    """forensics/analyse.py imports default_detector(); with a stub scorer a voice note gets a real audio result."""
    from forensics import analyse as joined
    from forensics.audio import default_detector
    det = default_detector()
    assert det.calibration.cells, "calibration/audio.json should load"
    det._scorer = stub([0.0, 0.0, 0.0])
    out = joined.analyse(write_wav(tmp_path / "note.wav", voice(6.0)), audio=det)
    assert [r.kind for r in out] == ["audio"] and out[0].status in ("clean", "abstain")
