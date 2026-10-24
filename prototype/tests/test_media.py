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
