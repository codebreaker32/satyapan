"""STT provenance parity with the OCR path: transcribe() returns (text, engine) and ingest() records the engine on
MediaRef.derived_text_engine for audio/video. faster-whisper is not installed on this box, so the happy path injects
a fake faster_whisper module; the no-STT error path runs for real."""
import importlib.util
import sys
import types
import wave

import pytest

from satyapan.media import MediaUnreadable, ingest


def _install_fake_whisper(monkeypatch, segment_texts):
    """A stand-in faster_whisper module whose model yields the given segment texts."""

    class FakeWhisperModel:
        def __init__(self, model_name, device, compute_type):
            assert device == "cpu"

        def transcribe(self, path, language=None, **options):   # the real one also takes vad_filter and others
            segments = iter(types.SimpleNamespace(text=t) for t in segment_texts)
            return segments, None

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)


@pytest.mark.parametrize("filename,kind", [("voice-note.ogg", "audio"), ("deepfake-clip.mp4", "video")])
def test_ingest_records_stt_engine_for_audio_and_video(tmp_path, monkeypatch, filename, kind):
    _install_fake_whisper(monkeypatch, [" RBI supervision account ", "mein paise bhejo. "])
    monkeypatch.setenv("SATYAPAN_WHISPER_MODEL", "tiny")   # the engine string names the actual model that ran
    path = tmp_path / filename
    path.write_bytes(b"\x00fake media bytes\x00")
    ref = ingest(path, language="hi")
    assert ref.kind == kind
    assert ref.derived_text == "RBI supervision account mein paise bhejo."
    assert ref.derived_text_engine == "faster-whisper tiny"


def test_a_recording_with_no_words_is_refused_with_a_sentence(tmp_path, monkeypatch):
    """No speech found is a refusal the officer can act on, never a case run on no text (that came back GREY)."""
    _install_fake_whisper(monkeypatch, [" ", ""])
    path = tmp_path / "recording.weba"
    path.write_bytes(b"\x00fake media bytes\x00")
    with pytest.raises(MediaUnreadable, match=r"No words could be made out in 'recording.weba'.*transcript box"):
        ingest(path)


@pytest.mark.parametrize("level", [0.0, 0.00003])
def test_a_silent_recording_says_to_check_the_microphone(tmp_path, monkeypatch, level):
    """A muted microphone records its noise floor: 23 s at about 0.00003 is what the browser sent on 23 Oct."""
    pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    _install_fake_whisper(monkeypatch, [])
    path = tmp_path / "recording.wav"
    noise = np.random.default_rng(0).normal(0, level, 16000 * 4) if level else np.zeros(16000 * 4)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((noise * 32767).astype("<i2").tobytes())
    with pytest.raises(MediaUnreadable, match=r"No voice can be heard in 'recording.wav'.*right microphone"):
        ingest(path)


def test_caller_supplied_derived_text_keeps_engine_none(tmp_path, monkeypatch):
    # the demo scenarios pass derived_text themselves; no engine ran, so none is claimed
    _install_fake_whisper(monkeypatch, ["must not be consulted"])
    path = tmp_path / "voice-note.ogg"
    path.write_bytes(b"\x00fake media bytes\x00")
    ref = ingest(path, derived_text="pre-written transcript")
    assert ref.derived_text == "pre-written transcript"
    assert ref.derived_text_engine is None


def test_no_stt_installed_raises_with_install_hint(tmp_path):
    if importlib.util.find_spec("faster_whisper") is not None:
        pytest.skip("faster-whisper is installed; the no-STT path cannot run here")
    path = tmp_path / "voice-note.ogg"
    path.write_bytes(b"\x00fake media bytes\x00")
    with pytest.raises(RuntimeError, match=r"satyapan\[stt\]"):
        ingest(path)


def _video(tmp_path, name, with_sound):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    import subprocess
    silent = tmp_path / f"silent_{name}"
    vw = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), 25, (160, 120))
    for i in range(50):
        vw.write(np.full((120, 160, 3), i * 5 % 255, np.uint8))
    vw.release()
    if not with_sound:
        return silent
    out = tmp_path / name
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(silent), "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=2", "-shortest", "-c:v", "copy", "-c:a", "aac", str(out)], check=True)
    return out


def test_a_video_with_no_speech_is_accepted_so_its_face_is_still_checked(tmp_path, monkeypatch):
    """A face swap with no clear speech used to be refused at upload, so the face check never ran on it."""
    _install_fake_whisper(monkeypatch, [" ", ""])
    ref = ingest(_video(tmp_path, "swap.mp4", with_sound=True))
    assert ref.kind == "video" and ref.derived_text == "" and "picture is still checked" in ref.derived_text_engine


def test_a_video_with_no_sound_track_is_accepted(tmp_path, monkeypatch):
    _install_fake_whisper(monkeypatch, ["must not be consulted"])
    ref = ingest(_video(tmp_path, "mute.mp4", with_sound=False))
    assert ref.kind == "video" and ref.derived_text == "" and ref.derived_text_engine.startswith("no sound track")


def test_a_voice_note_with_no_speech_is_still_refused(tmp_path, monkeypatch):
    _install_fake_whisper(monkeypatch, [" ", ""])
    path = tmp_path / "note.ogg"
    path.write_bytes(b"\x00fake media bytes\x00")
    with pytest.raises(MediaUnreadable, match=r"No words could be made out"):
        ingest(path)


def test_a_webm_with_no_picture_is_a_voice_note(tmp_path):
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    from satyapan.media import kind_of
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
    assert kind_of(p) == "audio"
    assert kind_of(_video(tmp_path, "v.mp4", with_sound=False)) == "video"
