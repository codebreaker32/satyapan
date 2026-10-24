from pathlib import Path

import cv2
import numpy as np

from forensics.analyse import REPLAY_FACE_REASON, analyse, extract_sound_track, kind_of
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
    assert rs[1].extra["from_video"] == "vs.mp4" and rs[1].extra["sound_track"]["codec"] == "aac"
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


class Keen:
    """A voice detector whose analyse() takes language and channel, like forensics/audio.py."""
    def __init__(self):
        self.calls = []

    def analyse(self, path, language="hi", channel=None):
        self.calls.append((Path(path).suffix, language, channel))
        return ForensicResult(kind="audio", status="clean", model="keen")


def test_language_and_channel_reach_a_voice_detector_that_takes_them(tmp_path):
    o = tmp_path / "note.ogg"
    o.write_bytes(b"OggS" + b"\x00" * 60)
    k = Keen()
    analyse(o, video=Fixed("video"), audio=k, language="en", channel="live-replay")
    assert k.calls == [(".ogg", "en", "live-replay")]


def test_a_detector_without_those_options_still_works(tmp_path):
    o = tmp_path / "note.ogg"
    o.write_bytes(b"OggS" + b"\x00" * 60)
    a = Fixed("audio")                                   # analyse(self, path) only
    assert analyse(o, video=Fixed("video"), audio=a, language="en", channel="live-replay")[0].status == "clean"


def with_sound(tmp_path: Path, name: str, *audio_args: str) -> Path:
    """A small video with a 3 s tone as its sound track, encoded with the given ffmpeg audio options."""
    import subprocess

    import imageio_ffmpeg
    src = make_video(tmp_path / f"src_{name}.mp4", n=75)
    out = tmp_path / name
    vcodec = ["-c:v", "libvpx", "-b:v", "200k"] if out.suffix == ".webm" else ["-c:v", "copy"]
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=3", "-shortest", *vcodec, *audio_args, str(out)], check=True)
    return out


def voice_recording(tmp_path: Path, name: str = "recording.weba") -> Path:
    """What the console's Record voice button saves: Opus in a WebM container, no picture."""
    import subprocess

    import imageio_ffmpeg
    out = tmp_path / name
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=3", "-c:a", "libopus", "-f", "webm", str(out)], check=True)
    return out


def test_a_browser_voice_recording_is_audio_and_gets_no_face_check(tmp_path):
    rec = voice_recording(tmp_path)
    assert kind_of(rec) == "audio"
    assert kind_of(voice_recording(tmp_path, "recording.webm")) == "audio"     # the extension does not decide it
    v, a = Fixed("video"), Fixed("audio")
    rs = analyse(rec, video=v, audio=a)
    assert [r.kind for r in rs] == ["audio"] and not v.seen and a.seen == [rec]


def test_a_webm_video_is_still_a_video(tmp_path):
    clip = with_sound(tmp_path, "clip.webm", "-c:a", "libopus")
    assert kind_of(clip) == "video"


def test_the_callers_kind_audio_skips_the_face_check(tmp_path):
    clip = with_sound(tmp_path, "clip.mp4", "-c:a", "aac")
    v, a = Fixed("video"), Fixed("audio")
    rs = analyse(clip, video=v, audio=a, kind="audio")
    assert [r.kind for r in rs] == ["audio"] and not v.seen and a.seen == [clip]
    v2 = Fixed("video")
    assert [r.kind for r in analyse(clip, video=v2, audio=Fixed("audio"), kind="video")] == ["video", "audio"] and v2.seen


def test_the_voice_cell_comes_from_the_sound_as_it_arrived(tmp_path):
    """The sound track is checked as a 16 kHz WAV, but its calibration cell follows the original stream, as it does
    for a voice note: Opus in a WebM is the WhatsApp/browser cell, 8 kHz sound is the phone cell, AAC (a phone or
    WhatsApp video's sound) has its own calibrated cell."""
    for name, args, channel in [("aac.mp4", ("-c:a", "aac"), "aac"),
                                ("phone.mp4", ("-c:a", "aac", "-ar", "8000"), "phone-8k"),
                                ("opus.webm", ("-c:a", "libopus"), "whatsapp-opus")]:
        k = Keen()
        rs = analyse(with_sound(tmp_path, name, *args), video=Fixed("video"), audio=k, language="en")
        assert k.calls == [(".wav", "en", channel)], name
        assert rs[1].extra["from_video"] == name


def test_live_replay_video_gets_no_face_verdict_and_keeps_the_voice_replay_rule(tmp_path):
    clip = with_sound(tmp_path, "filmed.webm", "-c:a", "libopus")
    v, k = Fixed("video", "clean"), Keen()
    rs = analyse(clip, video=v, audio=k, channel="live-replay")
    assert not v.seen, "a camera pointed at a screen is not what the face check was calibrated on"
    assert rs[0].kind == "video" and rs[0].status == "abstain" and rs[0].reason == REPLAY_FACE_REASON
    assert rs[0].cell == "video/live-replay" and rs[0].extra["sha256"]
    assert k.calls == [(".wav", "hi", "live-replay")]
