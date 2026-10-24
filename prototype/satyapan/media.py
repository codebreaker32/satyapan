"""Media intake: hashes, perceptual hash, and the derived text (speech-to-text or OCR).

Production uses Amazon Transcribe (hi-IN / en-IN) and Textract (English) or Tesseract (Hindi). Offline fallbacks:
faster-whisper for speech, pytesseract for OCR. If neither is installed, callers pass `derived_text` themselves.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional

from .models import MediaRef

# Models and language data fetched by `satyapan setup-models`, kept out of git (see .gitignore). Nothing here is
# downloaded while a case is being checked: a model that is not on disk is a missing install, never a network call.
VENDOR = Path(__file__).resolve().parent.parent / "vendor"
WHISPER_DIR = VENDOR / "models" / "whisper"
TESSDATA = VENDOR / "tessdata"
# The Windows installer for Tesseract does not put it on PATH; these are where it goes.
TESSERACT_PATHS = (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")

# .weba is what a browser's own audio recording is saved as (WebM holding only an Opus voice track).
AUDIO = {".wav", ".mp3", ".ogg", ".opus", ".m4a", ".aac", ".amr", ".flac", ".weba"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".3gp"}

KIND_WORDS = {"image": "an image", "pdf": "a PDF", "audio": "a voice note or audio file",
              "video": "a video", "text": "plain text"}

# What an officer should do when a file cannot be read. Claim-only mode is the designed route: the media was
# deleted or never shown, so the officer ticks what the customer says she was told.
CLAIM_ONLY_HINT = ("Check that you uploaded the original file. If the media was deleted or was never shown, "
                   "use claim-only mode and tick what the customer says she was told.")


class MediaUnreadable(Exception):
    """The file arrived whole but nothing inside it could be opened as the kind of media it is named for.

    Raised instead of letting a decoder exception (PIL.UnidentifiedImageError, a PDF parse error, a decoder
    failure in speech-to-text) reach the caller, so the API can answer 415 with a sentence an officer can act on.
    Deliberately not a RuntimeError: a missing OCR or speech-to-text install is a different answer (422).
    """


class NoSpeech(MediaUnreadable):
    """The file opened, but no speech could be made out in it. A voice note is refused for this; a video is not,
    because its picture is evidence on its own (the face check)."""


def unreadable_message(name: str, kind: str) -> str:
    word = KIND_WORDS.get(kind, "media")
    return f"We could not read '{name}'. It is named like {word}, and nothing inside it opens as {word}. {CLAIM_ONLY_HINT}"


def empty_message(name: str) -> str:
    return f"'{name}' arrived with no content in it at all. {CLAIM_ONLY_HINT}"


# Below this, at the 99.9th percentile of the samples, a recording with no speech in it is described as almost
# silent. It chooses the wording and never refuses anything by itself: the quietest genuine FLEURS speech sits at
# 0.0016, the same level as a muted microphone's noise floor plus one click (measured 23 Oct), so loudness cannot
# tell the two apart. The speech detector in `transcribe` can, and it decides.
NEAR_SILENT = 0.003
TRANSCRIPT_HINT = "You can also type what was said in the transcript box and run the check again."


def no_speech_message(name: str, near_silent: bool) -> str:
    if near_silent:
        return (f"No voice can be heard in '{name}': it is almost silent from start to end. If you recorded it here, "
                f"check that the right microphone is chosen and not muted, then record again. {TRANSCRIPT_HINT}")
    return (f"No words could be made out in '{name}': there is sound in it, but no speech that speech-to-text could "
            f"recognise. Record again closer to the speaker. {TRANSCRIPT_HINT}")


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in AUDIO:
        return "audio"
    if ext in IMAGE:
        return "image"
    if ext in VIDEO:
        # a browser's voice recording is often saved as .webm with no picture; it is a voice note, not a video
        return "audio" if ext in (".webm", ".mkv") and _has_picture(path) is False else "video"
    if ext == ".pdf":
        return "pdf"
    return "text"


def _has_picture(path: Path) -> Optional[bool]:
    """Does the container hold a video stream? None when it cannot be opened (the name then decides)."""
    try:
        import av
        with av.open(str(path)) as c:
            return any(st.type == "video" for st in c.streams)
    except Exception:  # noqa: BLE001
        return None


# Magic bytes, cheapest first. Every image, PDF and container format we accept carries a mandatory signature,
# so the first few bytes are enough to tell a renamed file from a real one.
MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),                 # JPEG (checked before the MPEG-audio frame sync below)
    (b"GIF87a", "image"), (b"GIF89a", "image"),
    (b"BM", "image"),
    (b"II*\x00", "image"), (b"MM\x00*", "image"),   # TIFF, both byte orders
    (b"%PDF", "pdf"),
    (b"OggS", "audio"),                         # ogg / opus
    (b"ID3", "audio"),                          # mp3 with a tag
    (b"fLaC", "audio"),
    (b"#!AMR", "audio"),
    (b"\x1a\x45\xdf\xa3", "video"),             # EBML: matroska / webm
)
SNIFFABLE_KINDS = {"image", "pdf"}              # named one of these and carrying no known signature means renamed


def sniff(head: bytes) -> Optional[str]:
    """The media family the first bytes actually describe, or None when they describe nothing we know.

    Used as a reason to reject a file whose contents contradict its name, never as a reason to accept one:
    some browsers send a voice note with no declared type and no signature we recognise, and those still pass.
    """
    if len(head) >= 12 and head[:4] == b"RIFF":
        return {b"WEBP": "image", b"WAVE": "audio", b"AVI ": "video"}.get(head[8:12])
    if len(head) >= 12 and head[4:8] == b"ftyp":                      # ISO base media: mp4, m4a, mov, 3gp
        return "audio" if head[8:11] in (b"M4A", b"M4B") else "video"
    for magic, family in MAGIC:
        if head.startswith(magic):
            return family
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:  # MPEG audio frame sync (mp3, no tag)
        return "audio"
    return None


def contents_contradict_name(kind: str, head: bytes) -> bool:
    """True when the bytes say this file is not what its name claims, so there is no point decoding it.

    Text is never sniffed. Plain text has no signature to contradict, it is read with errors="ignore" so there is
    no decoder to protect, and the short magic strings here collide with ordinary words: the pass-4 gate rejected
    a real note beginning "BMW loan recovery notice" as a bitmap and one beginning "ID3 card verification" as an
    mp3, told the officer the file "does not open as plain text" when it opened perfectly, and pushed her off the
    media path. Sniffing stays a reason to reject, never a new reason to accept.
    """
    if kind == "text":
        return False
    sniffed = sniff(head)
    # A WebM (EBML) container holds a voice track on its own as often as a video: it is what a browser records
    # audio into. So a WebM named as audio does not contradict its name.
    if sniffed == "video" and kind == "audio" and head.startswith(b"\x1a\x45\xdf\xa3"):
        return False
    if sniffed is not None:
        return sniffed != kind
    return kind in SNIFFABLE_KINDS


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def perceptual_hash(path: Path) -> Optional[str]:
    """pHash via imagehash (stand-in for Meta's PDQ, the production choice)."""
    try:
        import imagehash
        from PIL import Image
        return str(imagehash.phash(Image.open(path), hash_size=16))
    except Exception:  # noqa: BLE001
        return None


# One loaded model per (implementation, name): loading Whisper takes seconds, and the officer is waiting at the
# counter. Keyed by the class as well, so a test's stand-in module never hands back a model another test loaded.
_WHISPER: dict[tuple[int, str], object] = {}


def whisper_model(name: Optional[str] = None, *, download: bool = False):
    """The faster-whisper model, loaded once. Off disk only, unless `download` (used by `satyapan setup-models`)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("no speech-to-text available: pip install 'satyapan[stt]' or pass derived_text") from e
    name = name or os.environ.get("SATYAPAN_WHISPER_MODEL", "small")
    key = (id(WhisperModel), name)
    if key not in _WHISPER:
        try:
            _WHISPER[key] = WhisperModel(name, device="cpu", compute_type="int8", download_root=str(WHISPER_DIR),
                                         local_files_only=not download)
        except TypeError:          # a stand-in or an older faster-whisper without these keywords
            _WHISPER[key] = WhisperModel(name, device="cpu", compute_type="int8")
        except Exception as e:     # noqa: BLE001 - not under vendor/: try the standard Hugging Face cache, offline
            try:                   # (scripts/fetch_models.sh and earlier runs put large-v3-turbo there)
                _WHISPER[key] = WhisperModel(name, device="cpu", compute_type="int8", local_files_only=True)
            except Exception:      # noqa: BLE001 - not on disk anywhere: the console asks for a transcript
                raise RuntimeError(f"the speech-to-text model '{name}' is not downloaded: run `satyapan setup-models`, "
                                   "or pass derived_text") from e
    return _WHISPER[key], name


def _whisper(name: str):
    """Load (once) and return the model; the server's start-up preload calls this."""
    return whisper_model(name)[0]


SAMPLE_RATE = 16000


def decode_audio(path: Path, rate: int = SAMPLE_RATE):
    """The first audio track of any file PyAV can open, as mono float32 at `rate`, plus the source sample rate and
    codec. One decoder for a WAV, a WhatsApp Opus note, an MP3, a browser's WebM recording and a video's soundtrack,
    shared by speech-to-text and the audio detector so both hear the same samples. Raises when there is no audio."""
    import av
    import numpy as np
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError("no audio track")
        source_rate = int(stream.codec_context.sample_rate or stream.rate or 0)
        codec = stream.codec_context.name
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        chunks = []
        for frame in container.decode(stream):
            chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    wav = np.concatenate(chunks).astype("float32") if chunks else np.zeros(0, dtype="float32")
    return wav, source_rate, codec


def transcribe(path: Path, language: str = "hi") -> tuple[str, str]:
    """Returns (text, engine), like ocr(): the engine string names what actually transcribed the speech
    ("faster-whisper <model>"), so the console's media row and the evidence pack can state it truthfully.

    Speech-to-text with faster-whisper on CPU. The audio is decoded here, with the decoder the audio detector uses,
    and handed over as 16 kHz samples: faster-whisper 1.2.1's own decoder passes an option PyAV 19 removed, and one
    decoder for both models means they hear the same thing. A video's soundtrack and a browser recording are read the
    same way. Amazon Transcribe is the named production route; it is not wired here.

    The speech detector inside faster-whisper (Silero VAD, `vad_filter`) runs first, so only speech reaches Whisper.
    On a 23 s browser recording from a muted microphone, Whisper alone ran for 79 s and heard nothing (or "You", in
    English); with the detector the same file takes 0.1 s. It still passed the speech in the five quietest of 300
    genuine FLEURS clips (23 Oct). A recording with no speech in it is refused with a sentence that says so, never
    run as a message with no text, which used to come back as a GREY that named nothing it had read."""
    model, model_name = whisper_model()
    try:
        audio = decode_audio(path)[0]
    except Exception:  # noqa: BLE001 - let the speech model try the path itself; it refuses what we could not open
        audio = str(path)
    if not isinstance(audio, str) and len(audio) == 0:
        raise NoSpeech(no_speech_message(path.name, near_silent=True))
    try:
        beam = int(os.environ.get("SATYAPAN_WHISPER_BEAM", "5"))   # 1 = greedy: about 2x faster on CPU, slightly less accurate
        segments, _ = model.transcribe(audio, language=language if language in ("hi", "en") else None, vad_filter=True,
                                       beam_size=beam)
        text = " ".join(t for t in (s.text.strip() for s in segments) if t)
    except Exception as e:  # noqa: BLE001 - any decoder failure means the same thing to the officer
        raise MediaUnreadable(unreadable_message(path.name, kind_of(path))) from e
    if not text:
        raise NoSpeech(no_speech_message(path.name, near_silent=_near_silent(audio)))
    return text, f"faster-whisper {model_name}"


def _near_silent(audio) -> bool:
    """Is a decoded recording this quiet throughout? Only its wording depends on this (see NEAR_SILENT)."""
    if isinstance(audio, str):   # we could not decode it ourselves, so we cannot say how loud it is
        return False
    import numpy as np
    return float(np.percentile(np.abs(audio), 99.9)) < NEAR_SILENT


def tesseract_cmd() -> Optional[str]:
    """Where the tesseract binary is: SATYAPAN_TESSERACT, then PATH, then the Windows install folders."""
    cmd = os.environ.get("SATYAPAN_TESSERACT") or shutil.which("tesseract")
    return cmd or next((p for p in TESSERACT_PATHS if Path(p).exists()), None)


def _pytesseract():
    """pytesseract pointed at the binary and at the vendored Hindi + English language data, or a RuntimeError."""
    try:
        import pytesseract
    except ImportError as e:
        raise RuntimeError("no OCR available: pip install 'satyapan[ocr]' plus the tesseract binary, or pass derived_text") from e
    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    # The installer ships English only; `setup-models` puts eng + hin in vendor/tessdata, and tesseract reads
    # TESSDATA_PREFIX as that folder. Set only when the caller has not chosen one.
    if (TESSDATA / "hin.traineddata").exists() and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA)
    try:
        version = pytesseract.get_tesseract_version()
    except EnvironmentError as e:   # pytesseract.TesseractNotFoundError: the install is missing, not the file
        raise RuntimeError("no OCR available: pip install 'satyapan[ocr]' plus the tesseract binary, or pass derived_text") from e
    return pytesseract, f"tesseract {version}"


def ocr(path: Path, language: str = "hi") -> tuple[str, str]:
    """Returns (text, engine). The engine string names what actually read the text — "tesseract <version>" or
    "pdf text layer (pymupdf)" — so the console's media row and the evidence pack can state it truthfully.

    A PDF's own text layer is read first and needs no OCR install at all; tesseract is asked for only by a page
    that has no text on it (a scanned notice)."""
    lang = "hin+eng" if language == "hi" else "eng"
    if path.suffix.lower() == ".pdf":
        try:
            import pymupdf
        except ImportError as e:
            raise RuntimeError("no PDF reader available: pip install 'satyapan[ocr]', or pass derived_text") from e
        try:
            doc = pymupdf.open(path)
            texts, engine = [], "pdf text layer (pymupdf)"
            for page in doc:
                t = page.get_text().strip()
                if not t:
                    from PIL import Image
                    pytesseract, engine = _pytesseract()
                    pix = page.get_pixmap(dpi=200)
                    t = pytesseract.image_to_string(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), lang=lang)
                texts.append(t)
            return "\n".join(texts), engine
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001 - a PDF parse error reads the same as any unreadable file
            raise MediaUnreadable(unreadable_message(path.name, kind_of(path))) from e
    pytesseract, engine = _pytesseract()
    try:
        from PIL import Image
        return pytesseract.image_to_string(Image.open(path), lang=lang), engine
    except Exception as e:  # noqa: BLE001 - UnidentifiedImageError and a truncated file read the same
        raise MediaUnreadable(unreadable_message(path.name, kind_of(path))) from e


def _has_sound(path: Path) -> bool:
    """Does the file hold an audio stream? True when PyAV cannot tell, so speech-to-text still gets to try."""
    try:
        import av
        with av.open(str(path)) as c:
            return any(st.type == "audio" for st in c.streams)
    except Exception:  # noqa: BLE001 - unreadable here: let transcribe() refuse it with its own sentence
        return True


def ingest(path: Path, derived_text: Optional[str] = None, language: str = "hi") -> MediaRef:
    kind = kind_of(path)
    ref = MediaRef(filename=path.name, kind=kind, sha256=sha256_file(path), bytes=path.stat().st_size)
    if kind == "image":
        ref.perceptual_hash = perceptual_hash(path)
    if derived_text is not None:
        ref.derived_text = derived_text
    elif kind == "video":
        # A video's picture is evidence by itself: a face swap with no clear speech, or no sound at all, must still
        # reach the face check, so "no speech" here is an empty transcript, not a refusal. A video that will not open
        # at all is still refused (MediaUnreadable from the decoder).
        if not _has_sound(path):
            ref.derived_text, ref.derived_text_engine = "", "no sound track (the picture is still checked)"
        else:
            try:
                ref.derived_text, ref.derived_text_engine = transcribe(path, language)
            except NoSpeech:
                ref.derived_text, ref.derived_text_engine = "", "no speech made out (the picture is still checked)"
    elif kind == "audio":
        ref.derived_text, ref.derived_text_engine = transcribe(path, language)
    elif kind in ("image", "pdf"):
        ref.derived_text, ref.derived_text_engine = ocr(path, language)
    elif kind == "text":
        ref.derived_text = path.read_text(encoding="utf-8", errors="ignore")
    return ref
