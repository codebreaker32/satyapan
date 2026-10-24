"""One entry point for both detectors (docs/plan.md, section 4).

  analyse(path) -> list[ForensicResult]

- an audio file runs the audio detector;
- a video runs the video detector on its frames AND the audio detector on its sound track;
- anything else returns no results (the instruction checks still run on it elsewhere).

The audio detector is told how the sound reached us (`channel`) and the claim's language, when it accepts them. For a
video that is the codec of its own sound track (AAC for a phone or WhatsApp video, Opus for a browser recording), read
before the track is cut out to WAV, because the WAV alone no longer says how the sound was compressed.

The audio detector is Bhawna's (`forensics/audio.py`, same contract). Until it is installed, the audio half of a check
abstains with a plain reason instead of failing.
"""
from __future__ import annotations

import inspect
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Protocol

from .common import ForensicResult

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"}
AUDIO_EXT = {".ogg", ".opus", ".oga", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".amr"}


class Detector(Protocol):
    def analyse(self, path: Path | str) -> ForensicResult: ...


def kind_of(path: Path) -> Optional[str]:
    """Video or audio by extension, confirmed by the first bytes where the container is unambiguous."""
    ext = path.suffix.lower()
    try:
        head = path.read_bytes()[:16] if path.stat().st_size < 64 else path.open("rb").read(16)
    except OSError:
        return None
    if head[4:8] == b"ftyp":                        # MP4 family: .m4a is audio, the rest video
        if ext in (".m4a", ".aac") or head[8:11] in (b"M4A", b"M4B"):
            return "audio"
        return "audio" if _has_picture(path) is False else "video"
    if head[:4] == b"\x1a\x45\xdf\xa3":             # Matroska / WebM: a browser voice recording is WebM with no picture
        return "audio" if _has_picture(path) is False else "video"
    if head[:4] == b"OggS" or head[:3] == b"ID3" or head[:4] in (b"RIFF", b"fLaC") or head[:6] == b"#!AMR\n":
        return "video" if head[:4] == b"RIFF" and head[8:12] == b"AVI " else "audio"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return None


def _has_picture(path: Path) -> Optional[bool]:
    """Does the container hold a video stream? None when PyAV cannot tell (then the extension and header decide)."""
    try:
        import av
        with av.open(str(path)) as c:
            return any(s.type == "video" for s in c.streams)
    except Exception:  # noqa: BLE001 - unreadable, or PyAV missing: no opinion
        return None


def sound_channel(path: Path) -> Optional[str]:
    """How a file's own sound was compressed, as the audio detector's channel (clean, aac, whatsapp-opus, phone-8k),
    or None when it cannot be read or the audio detector is not installed."""
    try:
        import av

        from .audio import channel_for
        with av.open(str(path)) as c:
            s = next((s for s in c.streams if s.type == "audio"), None)
            if s is None:
                return None
            return channel_for(s.codec_context.name, int(s.codec_context.sample_rate or s.rate or 0))
    except Exception:  # noqa: BLE001
        return None


def _no_audio_detector(reason: str) -> ForensicResult:
    return ForensicResult(kind="audio", status="abstain", reason=reason, model="none")


def extract_sound_track(video: Path, out_dir: Path) -> Optional[Path]:
    """Sound track as 16 kHz mono WAV, or None if the video has no sound."""
    import imageio_ffmpeg

    out = out_dir / (video.stem + ".wav")
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
                        "-ar", "16000", "-c:a", "pcm_s16le", str(out)], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists() or out.stat().st_size <= 44:      # 44 bytes = an empty WAV header
        return None
    return out


def analyse(path: Path | str, video: Optional[Detector] = None, audio: Optional[Detector] = None, *,
            language: str = "hi", channel: Optional[str] = None) -> list[ForensicResult]:
    """`channel` overrides how the sound is taken to have arrived (e.g. "live-replay"); without it a video's sound is
    judged by its own codec."""
    path = Path(path)
    kind = kind_of(path) if path.is_file() else None
    if kind is None:
        return []
    if video is None and kind == "video":
        from .video import GenDVideoForensics

        video = GenDVideoForensics()
    if audio is None:
        try:
            from .audio import default_detector  # Bhawna's module exposes this once it is ready

            audio = default_detector()
        except ImportError:
            audio = None

    results: list[ForensicResult] = []
    if kind == "audio":
        results.append(_safe(audio, path, "audio", language=language, channel=channel) if audio
                       else _no_audio_detector("the audio detector is not installed yet"))
        return results

    results.append(_safe(video, path, "video"))
    with tempfile.TemporaryDirectory() as tmp:
        track = extract_sound_track(path, Path(tmp))
        if track is None:
            results.append(_no_audio_detector("the video has no sound track"))
        elif audio is None:
            results.append(_no_audio_detector("the audio detector is not installed yet"))
        else:
            r = _safe(audio, track, "audio", language=language, channel=channel or sound_channel(path))
            r.extra = {**r.extra, "from_video": str(path.name)}
            results.append(r)
    return results


def _safe(detector: Detector, path: Path, kind: str, **kw) -> ForensicResult:
    """One detector failing must not throw away the other's finished result: it abstains instead. Keyword arguments
    (language, channel) go only to a detector whose `analyse` accepts them."""
    try:
        params = inspect.signature(detector.analyse).parameters
        return detector.analyse(path, **{k: v for k, v in kw.items() if k in params and v is not None})
    except Exception as e:  # noqa: BLE001 - any failure in a detector reads the same to the officer
        return ForensicResult(kind=kind, status="abstain", reason=f"the {'voice' if kind == 'audio' else 'face'} check failed ({type(e).__name__})",
                              model=getattr(detector, "model_name", "") or type(detector).__name__)
