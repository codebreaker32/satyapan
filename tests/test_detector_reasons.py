"""Detector reasons say what is true.

- An AV1 video gave no frames to cv2 (no software AV1 decoder in its FFmpeg), so the face check always said
  "the video could not be read"; frames now come from PyAV when cv2 decodes none.
- An unreadable or truncated video was told "the video has no sound track" even when it had one.
- 1.98 s of speech printed "only 2.0 s of voice (needs 2 s to judge)".
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forensics.analyse import analyse, has_no_audio_stream
from forensics.audio import DFArenaAudioForensics
from forensics.video import _frame_count, read_frames
from tests.test_analyse import Fixed, make_video


def _ffmpeg() -> str:
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def _encode(args: list[str], out: Path) -> Path:
    r = subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", *args, str(out)], capture_output=True, text=True,
                       timeout=120)
    if r.returncode != 0:
        pytest.skip(f"ffmpeg could not make the test clip: {r.stderr[-200:]}")
    return out


def test_av1_frames_are_decoded(tmp_path):
    clip = _encode(["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "2", "-c:v", "libaom-av1",
                    "-cpu-used", "8", "-crf", "40"], tmp_path / "av1.mp4")
    n = _frame_count(str(clip))
    got = read_frames(str(clip), range(0, n, 5))
    assert n > 0 and len(got) == len(range(0, n, 5))
    assert next(iter(got.values())).shape == (240, 320, 3)


def test_av1_display_rotation_matches_cv2(tmp_path):
    clip = _encode(["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "1", "-c:v", "libaom-av1",
                    "-cpu-used", "8", "-crf", "40"], tmp_path / "av1.mp4")
    rotated = _encode(["-display_rotation:v:0", "90", "-i", str(clip), "-c", "copy"], tmp_path / "rot.mp4")
    got = read_frames(str(rotated), [0])
    assert got[0].shape == (320, 240, 3)


def test_a_video_with_no_audio_stream_says_so(tmp_path):
    v = make_video(tmp_path / "silent.mp4")
    assert has_no_audio_stream(v)
    reasons = [r.reason for r in analyse(v, video=Fixed("video"), audio=Fixed("audio"))]
    assert "the video has no sound track" in reasons


def test_an_unreadable_video_is_not_told_it_has_no_sound_track(tmp_path):
    v = _encode(["-f", "lavfi", "-i", "testsrc=size=160x120:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
                 "-t", "2", "-c:v", "libx264", "-c:a", "aac", "-shortest"], tmp_path / "with_sound.mp4")
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(v.read_bytes()[:48] + b"\x00" * 64)
    assert not has_no_audio_stream(broken)
    reasons = [r.reason for r in analyse(broken, video=Fixed("video"), audio=Fixed("audio"))]
    assert "the video has no sound track" not in reasons
    assert "the sound track could not be read" in reasons


@pytest.mark.parametrize("speech_s, shown", [(1.98, "only 1.9 s"), (1.5, "only 1.5 s"), (0.4, "only 0.4 s")])
def test_short_voice_reason_never_prints_the_minimum(speech_s, shown):
    reason = DFArenaAudioForensics().gate({"duration_s": 3.0, "speech_s": speech_s, "range": 0.0})
    assert reason.startswith(shown) and "needs 2 s" in reason
