"""The synthetic-data generators in synthetic/: each one that can run on a Linux box without a TTS engine runs here,
into a temporary folder, and its output is checked for the format the README promises. The TTS step itself
(PowerShell System.Speech or espeak-ng) is only checked for the command it would run."""
import csv
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "synthetic"))

import channels  # noqa: E402
import make_format_sweep  # noqa: E402
import make_notice_image  # noqa: E402
import make_test_voice_note  # noqa: E402
import validate_fixtures  # noqa: E402


def ffmpeg(*args):
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", *args], check=True)


def opus_head(path: Path) -> tuple[int, int]:
    """(channels, input sample rate) from the OpusHead packet of an Ogg Opus file."""
    b = path.read_bytes()
    i = b.index(b"OpusHead")
    _, ch, _, rate = struct.unpack("<BBHI", b[i + 8:i + 16])
    return ch, rate


def streams(path: Path) -> list[str]:
    import av
    with av.open(str(path)) as c:
        return [s.type for s in c.streams]


@pytest.fixture(scope="module")
def tone(tmp_path_factory) -> Path:
    wav = tmp_path_factory.mktemp("tone") / "tone.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=22050:duration=4", str(wav))
    return wav


def test_notice_image_is_the_demo_file_shape(tmp_path):
    from PIL import Image
    try:
        made = make_notice_image.make(tmp_path, ["S3-ed-summons"])
    except make_notice_image.renderer().NoFont:
        pytest.skip("no DejaVu or Arial font on this box")
    assert [p.name for p in made] == ["ED_summons_synthetic.png"]
    assert Image.open(made[0]).size == (1200, 544)     # 8 wrapped lines, as the demo's file


def test_every_ocr_scenario_gets_a_notice():
    ocr = [s for s, v in make_notice_image.scenarios().items() if v.get("source") == "ocr"]
    assert "S3-ed-summons" in ocr and len(ocr) >= 2


def test_voice_note_text_is_the_one_the_team_recorded():
    t = make_test_voice_note.TEXT
    assert t.startswith("Listen carefully. You are digitally arrested.")
    assert "3 0 0 1 1 2 2 3 3 4 4 5 5 6" in t and "D E M O 0 0 0 1 2 3 4" in t
    assert t.endswith("Send the money now, or you will be arrested.")


def test_voice_note_encodes_to_16k_mono_opus(tmp_path, tone):
    ogg = make_test_voice_note.encode(tone, tmp_path / "note.ogg")
    assert ogg.read_bytes()[:4] == b"OggS"
    assert opus_head(ogg) == (1, 16000)


def test_voice_note_asks_windows_for_david(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(make_test_voice_note, "powershell", lambda: "powershell.exe")
    monkeypatch.setattr(make_test_voice_note, "windows_path", lambda p: f"C:\\x\\{Path(p).name}")
    monkeypatch.setattr(make_test_voice_note.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert make_test_voice_note.speak("hello", tmp_path / "a.wav") == "System.Speech (Microsoft David Desktop)"
    script = calls[0][-1]
    assert calls[0][0] == "powershell.exe" and "SelectVoice('Microsoft David Desktop')" in script
    assert "System.Speech" in script and "hello" not in script          # the text travels in a file


def test_voice_note_says_so_when_no_tts_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(make_test_voice_note.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="no text-to-speech engine"):
        make_test_voice_note.speak("hello", tmp_path / "a.wav")


def test_whatsapp_opus_copy(tmp_path, tone):
    ogg = channels.whatsapp_opus(tone, tmp_path / "wa.ogg")
    assert opus_head(ogg) == (1, 16000)


def test_simulated_phone_band_keeps_length_at_16k(tone):
    from forensics.audio import decode_audio
    wav = decode_audio(tone)[0]
    out = channels.through_channel(wav, "phone-8k")
    assert out.dtype == np.float32 and abs(len(out) - len(wav)) < 1600     # within 0.1 s of the original


def test_whatsapp_video_copy_is_480p(tmp_path):
    src = tmp_path / "hd.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=1", "-pix_fmt", "yuv420p", str(src))
    out = channels.whatsapp_video(src, tmp_path / "wa.mp4")
    import av
    with av.open(str(out)) as c:
        v = c.streams.video[0]
        assert min(v.codec_context.width, v.codec_context.height) == 480


def test_aasist_phone_channel_is_8k(tmp_path, tone):
    pytest.importorskip("pydantic", reason="the aasist-* channels import the engine package (engine venv)")
    out = channels.aasist_channel(tone, tmp_path / "phone.wav", "amr-8k")
    import soundfile as sf
    assert sf.info(str(out)).samplerate == 8000


def test_format_sweep_makes_the_ten_files(tmp_path):
    import soundfile as sf
    try:
        made = make_format_sweep.make(tmp_path, make_format_sweep.TONE)
    except make_notice_image.renderer().NoFont:
        pytest.skip("no DejaVu or Arial font on this box")
    assert len(made) == 10 and all(p.stat().st_size > 0 for p in made)
    head = {p.name: p.read_bytes()[:12] for p in made}
    assert head["renamed_clip.jpg"][4:8] == b"ftyp"                 # an MP4 under an image name
    assert head["notice.jpg"][:3] == b"\xff\xd8\xff" and head["notice.webp"][8:12] == b"WEBP"
    assert head["voice.mp3"][:3] == b"ID3" and head["voice.m4a"][4:8] == b"ftyp"
    assert sf.info(str(tmp_path / "voice_8k.wav")).samplerate == 8000
    assert sorted(streams(tmp_path / "clip.mov")) == ["audio", "video"]
    assert sorted(streams(tmp_path / "clip.webm")) == ["audio", "video"]
    assert streams(tmp_path / "clip_no_audio.mp4") == ["video"]
    assert "Demo Bank" in (tmp_path / "message.txt").read_text(encoding="utf-8")
    rows = list(csv.DictReader((tmp_path / "manifest.csv").open()))
    assert [r["file"] for r in rows] == [p.name for p in made]


def test_identifier_rules():
    assert validate_fixtures.synthetic_ifsc("DEMO0001234") and not validate_fixtures.synthetic_ifsc("HDFC0000213")
    for n in ("30011223344556", "50100234567891", "919876500011", "16001234567"):
        assert validate_fixtures.invented_number(n), n
    assert not validate_fixtures.invented_number("9354209849")
    found = validate_fixtures.findings("pay A/c 7319482056, IFSC SBIN0000123, UPI 8163527094@ybl, call +91 98765 00011")
    assert ("IFSC", "SBIN0000123") in found and ("UPI ID", "8163527094@ybl") in found
    assert ("number", "7319482056") in found and not any(v == "+91 98765 00011" for _, v in found)


# What the validator reports on the corpora today, and why each one is there (synthetic/README.md). A new
# identifier that breaks a rule fails this test; it is reported, never "fixed" by editing a fixture.
KNOWN = {
    ("IFSC", "SBIN0004321"),     # real bank prefix with an invented branch code (S2 scenario)
    ("IFSC", "HDFC0000213"),     # real bank prefix (S3, S5d, S9, S9b control, labelled set, campaign memory)
    ("IFSC", "SBIN0000691"),     # real bank prefix (S7 court order)
    ("UPI ID", "9354209849@slc"),  # a team member's own test ID, added at her request (name_lookup.json _note)
    ("number", "9354209849"),
}


def test_every_fixture_parses_and_only_the_known_exceptions_break_a_rule():
    broken, bad = validate_fixtures.validate()
    assert broken == []
    assert {(kind, value) for _, kind, value in bad} == KNOWN
