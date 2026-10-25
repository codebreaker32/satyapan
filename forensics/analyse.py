"""One entry point for both detectors.

  analyse(path) -> list[ForensicResult]

- an audio file runs the audio detector;
- a video runs the video detector on its frames AND the audio detector on its sound track;
- anything else returns no results (the instruction checks still run on it elsewhere).

The caller may say what the upload is (`kind`): "audio" never runs the face check, so a browser voice recording in a
WebM container gets no face result. A recording made with a camera pointed at a screen (`channel="live-replay"`) gets
no face verdict either: the face check is calibrated on original video files only.

The audio detector is `forensics/audio.py` (same contract). When it is not installed, the audio half of a check
abstains with a plain reason instead of failing.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Protocol

from .common import ForensicResult

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp"}
AUDIO_EXT = {".ogg", ".opus", ".oga", ".weba", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".amr"}
LIVE_REPLAY = "live-replay"      # forensics/audio.py: recorded by pointing a microphone or camera at another device
REPLAY_FACE_REASON = "the face check is calibrated on original video files, not on a camera pointed at a screen"


class Detector(Protocol):
    def analyse(self, path: Path | str) -> ForensicResult: ...


def kind_of(path: Path) -> Optional[str]:
    """Video or audio by extension, confirmed by the first bytes where the container is unambiguous."""
    ext = path.suffix.lower()
    try:
        head = path.read_bytes()[:16] if path.stat().st_size < 64 else path.open("rb").read(16)
    except OSError:
        return None
    if head[4:8] == b"ftyp":                        # MP4 family: .m4a is audio; the rest by their streams, because a
        # call recorder's .3gp, or an .mp4 holding only sound, has no picture to face-check
        return "audio" if ext in (".m4a", ".aac") or head[8:11] in (b"M4A", b"M4B") else _webm_kind(path, ext)
    if head[:4] == b"\x1a\x45\xdf\xa3":             # Matroska / WebM: a browser's voice recording is WebM too
        return _webm_kind(path, ext)
    if head[:4] == b"OggS" or head[:3] == b"ID3" or head[:4] in (b"RIFF", b"fLaC") or head[:6] == b"#!AMR\n":
        return "video" if head[:4] == b"RIFF" and head[8:12] == b"AVI " else "audio"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return None


def _webm_kind(path: Path, ext: str) -> str:
    """WebM (and an MP4-family file) holds video or only sound; look at its streams (a cheap header read), else go by
    the extension."""
    try:
        import av
        with av.open(str(path)) as container:
            return "video" if any(s.type == "video" for s in container.streams) else "audio"
    except Exception:  # noqa: BLE001 - an unreadable file is judged by its name; the detectors then abstain on it
        return "audio" if ext in (".weba", ".oga", ".ogg", ".opus") else "video"


def sound_track_format(path: Path) -> Optional[tuple[str, int]]:
    """(codec, sample rate) of a file's first audio stream, or None. The voice check's calibration cell depends on how
    the sound arrived (Opus, 8 kHz phone audio, or clean), so it is read from the original file, not from the
    16 kHz WAV the sound track is extracted to."""
    try:
        import av
        with av.open(str(path)) as container:
            a = next((s for s in container.streams if s.type == "audio"), None)
            return None if a is None else (a.codec_context.name, int(a.codec_context.sample_rate or a.rate or 0))
    except Exception:  # noqa: BLE001 - no format means the voice detector falls back to the WAV it is given
        return None


def has_no_audio_stream(path: Path) -> bool:
    """True only when the container opens and holds no audio stream."""
    try:
        import av
        with av.open(str(path)) as container:
            return not any(s.type == "audio" for s in container.streams)
    except Exception:  # noqa: BLE001 - a file that will not open is not known to have no sound
        return False


def _sha256(path: Path) -> Optional[str]:
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
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


def analyse(path: Path | str, video: Optional[Detector] = None, audio: Optional[Detector] = None, language: str = "hi",
            channel: Optional[str] = None, kind: Optional[str] = None) -> list[ForensicResult]:
    """`language` and `channel` reach the voice detector, whose thresholds are calibrated per language and channel.
    `kind` is the caller's own reading of the upload: "audio" skips the face check even when the container could hold
    video; "video" (or nothing) goes by what the file is."""
    path = Path(path)
    found = kind_of(path) if path.is_file() else None
    if found is None:
        return []
    kind = "audio" if kind == "audio" else found
    if video is None and kind == "video":
        from .video import GenDVideoForensics

        video = GenDVideoForensics()
    if audio is None:
        try:
            from .audio import default_detector  # provided by forensics/audio.py when installed

            audio = default_detector()
        except ImportError:
            audio = None

    results: list[ForensicResult] = []
    if kind == "audio":
        results.append(_safe(audio, path, "audio", language=language, channel=channel) if audio
                       else _no_audio_detector("the audio detector is not installed yet"))
        return results

    if channel == LIVE_REPLAY:
        # A camera pointed at a phone films a screen: moire, glare and a second compression that no calibration clip
        # had, so neither "no signs" nor a flag would mean what the calibrated thresholds say. The voice half keeps its
        # own replay rule (forensics/audio.py).
        results.append(ForensicResult(kind="video", status="abstain", reason=REPLAY_FACE_REASON, cell="video/live-replay",
                                      model=getattr(video, "model_name", "") or type(video).__name__,
                                      extra={"sha256": _sha256(path)}))
    else:
        results.append(_safe(video, path, "video"))
    with tempfile.TemporaryDirectory() as tmp:
        track = extract_sound_track(path, Path(tmp))
        if track is None:
            # "No sound track" only when the container opens and holds no audio stream, so a truncated or unreadable
            # file with an AAC track is not reported as having none.
            results.append(_no_audio_detector("the video has no sound track" if has_no_audio_stream(path)
                                              else "the sound track could not be read"))
        elif audio is None:
            results.append(_no_audio_detector("the audio detector is not installed yet"))
        else:
            # The WAV is always 16 kHz PCM, which the voice detector would take for the "clean" channel; the cell must
            # come from the sound as it arrived (an Opus WebM, 8 kHz phone audio), as it does for a voice note. A
            # caller's live-replay channel still wins.
            fmt = sound_track_format(path)
            if channel is None and fmt is not None:
                try:
                    from .audio import channel_for
                    channel = channel_for(*fmt)
                except ImportError:
                    pass
            r = _safe(audio, track, "audio", language=language, channel=channel)
            r.extra = {**r.extra, "from_video": str(path.name),
                       **({"sound_track": {"codec": fmt[0], "sample_rate": fmt[1]}} if fmt else {})}
            results.append(r)
    return results


def _safe(detector: Detector, path: Path, kind: str, **options) -> ForensicResult:
    """One detector failing must not throw away the other's finished result: it abstains instead. `options` (language,
    channel) are passed only to a detector whose analyse() accepts them."""
    import inspect
    try:
        params = inspect.signature(detector.analyse).parameters
        accepted = {k: v for k, v in options.items() if k in params and v is not None}
    except (TypeError, ValueError):
        accepted = {}
    try:
        return detector.analyse(path, **accepted)
    except Exception as e:  # noqa: BLE001 - any failure in a detector reads the same to the officer
        return ForensicResult(kind=kind, status="abstain", reason=f"the {'voice' if kind == 'audio' else 'face'} check failed ({type(e).__name__})",
                              model=getattr(detector, "model_name", "") or type(detector).__name__)
