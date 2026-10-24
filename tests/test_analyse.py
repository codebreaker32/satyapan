from pathlib import Path

import cv2
import numpy as np

from forensics.analyse import analyse, extract_sound_track, kind_of
from forensics.common import ForensicResult


def make_video(path: Path, n=10):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (160, 120))
    for i in range(n):
        vw.write(np.full((120, 160, 3), i * 20 % 255, np.uint8))
    vw.release()
    return path


class Fixed:
    def __init__(self, kind, status="clean"):
        self.kind, self.status, self.seen = kind, status, []

    def analyse(self, path):
        self.seen.append(Path(path))
        return ForensicResult(kind=self.kind, status=self.status, model=f"stub-{self.kind}")


def test_kind_of(tmp_path):
    v = make_video(tmp_path / "a.mp4")
    assert kind_of(v) == "video"
    w = tmp_path / "a.wav"
    w.write_bytes(b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 40)
    assert kind_of(w) == "audio"
    o = tmp_path / "note.ogg"
    o.write_bytes(b"OggS" + b"\x00" * 60)
    assert kind_of(o) == "audio"
    t = tmp_path / "x.txt"
    t.write_text("hello")
    assert kind_of(t) is None


def test_text_file_gets_no_forensics(tmp_path):
    t = tmp_path / "x.txt"
    t.write_text("hello")
    assert analyse(t, video=Fixed("video"), audio=Fixed("audio")) == []


def test_missing_file_gets_no_forensics(tmp_path):
    assert analyse(tmp_path / "nope.mp4", video=Fixed("video"), audio=Fixed("audio")) == []


def test_audio_file_runs_audio_only(tmp_path):
    o = tmp_path / "note.ogg"
    o.write_bytes(b"OggS" + b"\x00" * 60)
    v, a = Fixed("video"), Fixed("audio")
    rs = analyse(o, video=v, audio=a)
    assert [r.kind for r in rs] == ["audio"] and not v.seen and a.seen == [o]


def test_silent_video_runs_video_and_says_no_sound(tmp_path):
    p = make_video(tmp_path / "v.mp4")                    # OpenCV writes no audio stream
    v, a = Fixed("video", "synthetic"), Fixed("audio")
    rs = analyse(p, video=v, audio=a)
    assert [r.kind for r in rs] == ["video", "audio"]
    assert rs[1].status == "abstain" and "no sound track" in rs[1].reason and not a.seen


def test_video_with_sound_sends_its_track_to_the_audio_detector(tmp_path):
    import subprocess

    import imageio_ffmpeg
    src = make_video(tmp_path / "v.mp4", n=50)
    withsound = tmp_path / "vs.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-shortest", "-c:v", "copy", "-c:a", "aac", str(withsound)], check=True)
    v, a = Fixed("video"), Fixed("audio")
    rs = analyse(withsound, video=v, audio=a)
    assert [r.kind for r in rs] == ["video", "audio"] and len(a.seen) == 1 and a.seen[0].suffix == ".wav"
    assert rs[1].extra["from_video"] == "vs.mp4"
    assert extract_sound_track(src, tmp_path) is None


def test_without_audio_detector_the_audio_half_abstains(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "forensics.audio", None)   # simulate "not installed yet"
    o = tmp_path / "note.ogg"
    o.write_bytes(b"OggS" + b"\x00" * 60)
    rs = analyse(o, video=Fixed("video"))
    assert rs[0].status == "abstain" and "not installed" in rs[0].reason


def test_a_failing_voice_check_keeps_the_face_result(tmp_path):
    import subprocess

    import imageio_ffmpeg
    src = make_video(tmp_path / "v.mp4", n=50)
    withsound = tmp_path / "vs.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-shortest", "-c:v", "copy", "-c:a", "aac", str(withsound)], check=True)

    class Boom:
        def analyse(self, path):
            raise RuntimeError("audio model exploded")
    rs = analyse(withsound, video=Fixed("video", "synthetic"), audio=Boom())
    assert rs[0].kind == "video" and rs[0].status == "synthetic"
    assert rs[1].kind == "audio" and rs[1].status == "abstain" and "voice check failed" in rs[1].reason


class Heard:
    """An audio detector that accepts language and channel, and remembers what it was told."""

    def __init__(self):
        self.calls = []

    def analyse(self, path, language="hi", channel=None):
        self.calls.append((Path(path).suffix, language, channel))
        return ForensicResult(kind="audio", status="clean", model="stub-audio")


def _with_aac_sound(tmp_path):
    import subprocess

    import imageio_ffmpeg
    src = make_video(tmp_path / "v.mp4", n=50)
    out = tmp_path / "vs.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "64k", str(out)],
                   check=True)
    return out


def test_a_videos_sound_is_judged_by_its_own_codec_and_the_claims_language(tmp_path):
    """The track is cut out to WAV, which no longer says it was AAC; the detector is told before that happens."""
    a = Heard()
    rs = analyse(_with_aac_sound(tmp_path), video=Fixed("video"), audio=a, language="en")
    assert [r.kind for r in rs] == ["video", "audio"] and a.calls == [(".wav", "en", "aac")]


def test_a_replay_channel_overrides_the_codec_and_reaches_an_audio_file(tmp_path):
    a = Heard()
    analyse(_with_aac_sound(tmp_path), video=Fixed("video"), audio=a, channel="live-replay")
    o = tmp_path / "note.ogg"
    o.write_bytes(b"OggS" + b"\x00" * 60)
    analyse(o, video=Fixed("video"), audio=a, channel="live-replay")
    assert [c[2] for c in a.calls] == ["live-replay", "live-replay"]


def test_a_webm_with_no_picture_is_a_voice_recording(tmp_path):
    """The console's "Record voice" uploads WebM holding only sound; it must not go to the face check."""
    import av
    p = tmp_path / "voice.webm"
    with av.open(str(p), "w", format="webm") as c:
        s = c.add_stream("libopus", rate=48000, layout="mono")
        f = av.AudioFrame.from_ndarray((0.1 * np.sin(np.arange(48000) / 8)).astype(np.float32).reshape(1, -1),
                                       format="flt", layout="mono")
        f.sample_rate = 48000
        for pkt in s.encode(f):
            c.mux(pkt)
        for pkt in s.encode(None):
            c.mux(pkt)
    v, a = Fixed("video"), Heard()
    rs = analyse(p, video=v, audio=a)
    assert kind_of(p) == "audio" and [r.kind for r in rs] == ["audio"] and not v.seen
    assert a.calls == [(".webm", "hi", None)]
