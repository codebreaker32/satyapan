"""A video gets two checks: the face check on its frames and the voice check on its sound, judged by the sound's own
codec. An audio file gets the voice check alone. Both results reach the combined score."""
import subprocess
from pathlib import Path

import pytest

from satyapan.forensics import TEAM_REPO, ForensicResult, TeamVideoForensics, _FaceCheckMissing
from satyapan.models import Flag, Outcome
from satyapan.pipeline import Satyapan

cv2 = pytest.importorskip("cv2")
imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
needs_team = pytest.mark.skipif(not (TEAM_REPO / "forensics" / "analyse.py").exists(),
                                reason="the team repository with forensics/analyse.py is not here")


def video_with_sound(tmp_path: Path, name: str = "call.mp4") -> Path:
    import numpy as np
    silent = tmp_path / "silent.mp4"
    vw = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), 25, (160, 120))
    for i in range(50):
        vw.write(np.full((120, 160, 3), i * 5 % 255, np.uint8))
    vw.release()
    out = tmp_path / name
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(silent), "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=2", "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "64k", str(out)],
                   check=True)
    return out


class TwoChecks:
    """Stands in for the video forensics: a scripted face result and voice result, and a record of the calls."""
    from satyapan.adapters import Label
    label = Label("Video forensics (stub)", "stub", "Model risk", "stub", mock=False)

    def __init__(self, face="synthetic", face_band="moderate", voice="clean"):
        self.face, self.face_band, self.voice, self.calls = face, face_band, voice, []

    def analyse(self, path, language="hi", channel=None):
        self.calls.append((Path(path).name, language, channel))
        return [ForensicResult(kind="video", status=self.face, band=self.face_band if self.face == "synthetic" else "",
                               reason="" if self.face != "abstain" else "no face", model="stub"),
                ForensicResult(kind="audio", status=self.voice, model="stub")]


class NoAudio:
    from satyapan.adapters import Label
    label = Label("Audio forensics (stub)", "stub", "Model risk", "stub", mock=False)

    def __init__(self):
        self.calls = []

    def analyse(self, path, language="hi"):
        self.calls.append(Path(path).name)
        return ForensicResult(kind="audio", status="clean", model="stub")


def run(engine, path, text):
    case = engine.open_case(Flag(reason="video call shown at the counter", amount_inr=200000))
    engine.set_consent(case, check=True)
    engine.add_media(case, path, derived_text=text)
    return engine.run(case)


def test_a_video_gets_the_face_check_and_the_voice_check(tmp_path):
    video, audio = TwoChecks(face="synthetic", voice="clean"), NoAudio()
    case = run(Satyapan(audio=audio, video=video, state_dir=tmp_path / "s"), video_with_sound(tmp_path), "hello")
    ids = {s.rule_id for s in case.verdict.signals}
    assert {"R-VIDEO-SYNTH", "R-AUDIO-SYNTH"} <= ids
    assert video.calls and not audio.calls                  # the audio-only check never sees the video
    assert case.verdict.scores["deepfake_pct"] == 70        # the face result counts; the most fake check wins
    assert case.verdict.outcome == Outcome.AMBER            # nothing in "hello" is an instruction: 0 + 70 -> 35%


def test_a_cloned_voice_in_a_video_with_a_real_face_still_counts(tmp_path):
    video = TwoChecks(face="clean", voice="synthetic")
    case = run(Satyapan(audio=NoAudio(), video=video, state_dir=tmp_path / "s"), video_with_sound(tmp_path), "hello")
    assert case.verdict.scores["deepfake_pct"] == 70 and "Signs of synthetic speech" in case.verdict.explanation


def test_an_audio_file_never_goes_to_the_face_check(tmp_path):
    import wave
    w = tmp_path / "note.wav"
    with wave.open(str(w), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00\x10" * 48000)
    video, audio = TwoChecks(), NoAudio()
    run(Satyapan(audio=audio, video=video, state_dir=tmp_path / "s"), w, "hello")
    assert audio.calls == ["note.wav"] and not video.calls


class HeardVoice:
    """A team-style voice detector that remembers the language and channel it was given."""
    def __init__(self):
        self.calls = []

    def analyse(self, path, language="hi", channel=None):
        from forensics.common import ForensicResult as TeamResult
        self.calls.append((Path(path).suffix, language, channel))
        return TeamResult(kind="audio", status="clean", model="stub-voice")


class FaceStub:
    def analyse(self, path):
        from forensics.common import ForensicResult as TeamResult
        return TeamResult(kind="video", status="clean", model="stub-face")


@needs_team
def test_the_team_entry_point_gets_the_language_and_the_sounds_codec(tmp_path):
    voice = HeardVoice()
    v = TeamVideoForensics(TEAM_REPO, voice)
    v._video = FaceStub()
    rs = v.analyse(video_with_sound(tmp_path), language="en")
    assert [r.kind for r in rs] == ["video", "audio"] and voice.calls == [(".wav", "en", "aac")]
    assert rs[1].extra.get("from_video") == "call.mp4"


@needs_team
def test_without_the_face_model_the_voice_in_a_video_is_still_checked(tmp_path):
    voice = HeardVoice()
    v = TeamVideoForensics(TEAM_REPO, voice)
    v._video = _FaceCheckMissing("the face check is not installed on this machine (ImportError)")
    rs = v.analyse(video_with_sound(tmp_path))
    assert rs[0].status == "abstain" and "not installed" in rs[0].reason and rs[1].status == "clean"


@needs_team
def test_the_forensics_service_answers_for_both_checks(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer

    from forensics.service import Service, make_handler
    svc = Service.__new__(Service)                         # skip model loading
    svc.video, svc.audio, svc.lock = FaceStub(), HeardVoice(), threading.Lock()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        v = TeamVideoForensics(TEAM_REPO, None, url=f"http://127.0.0.1:{httpd.server_address[1]}")
        rs = v.analyse(video_with_sound(tmp_path), language="en")
        assert [(r.kind, r.status) for r in rs] == [("video", "clean"), ("audio", "clean")]
        assert svc.audio.calls == [(".wav", "en", "aac")]
    finally:
        httpd.shutdown()
    down = TeamVideoForensics(TEAM_REPO, None, url="http://127.0.0.1:9").analyse(video_with_sound(tmp_path, "b.mp4"))
    assert [r.status for r in down] == ["abstain", "abstain"] and "could not be reached" in down[0].reason
