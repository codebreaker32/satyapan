"""The 10 format-test files for the upload path, made from synthetic inputs only.

Inputs: the synthetic test voice note (make_test_voice_note.py, or --voice for one you made, or --tone for a plain
440 Hz sine with no speech), ffmpeg's testsrc2 colour-bar pattern for the picture (no face, no person), and the S3
notice image (make_notice_image.py). Outputs, with what each one tests:

  voice.mp3              MP3 audio (libmp3lame, 64 kbit/s, 16 kHz mono)
  voice_8k.wav           8 kHz mono 16-bit PCM WAV, phone-band audio
  voice.m4a              AAC in an MP4 container (64 kbit/s, 16 kHz mono)
  clip.mov               QuickTime: H.264 + AAC
  clip.webm              WebM: VP8 + Opus
  clip_no_audio.mp4      H.264 with no audio track (a video in which nobody speaks)
  notice.jpg             the synthetic notice as JPEG (quality 85)
  notice.webp            the synthetic notice as WebP (quality 80)
  renamed_clip.jpg       clip_no_audio.mp4's bytes under an image name: the upload must refuse it as renamed
  message.txt            the S1 scenario's text as UTF-8 plain text

  python synthetic/make_format_sweep.py --out /tmp/sweep --voice /tmp/voice/digital_arrest_test_voice_note.ogg
  python synthetic/make_format_sweep.py --out /tmp/sweep --tone          # no TTS engine needed

Also writes manifest.csv (file, what it tests). Default output folder: clips/synthetic/format_sweep/ (git-ignored).
"""
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_notice_image  # noqa: E402
import make_test_voice_note  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SECONDS = 6
PICTURE = ["-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={SECONDS}"]
TONE = ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=16000:duration={SECONDS}"]
H264 = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
FILES = {   # name: (ffmpeg output options, what it tests); None = made without ffmpeg
    "voice.mp3": (["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k"], "MP3 audio"),
    "voice_8k.wav": (["-vn", "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le"], "8 kHz phone-band WAV"),
    "voice.m4a": (["-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "64k"], "AAC audio in MP4 (m4a)"),
    "clip.mov": ([*H264, "-c:a", "aac", "-b:a", "64k", "-shortest"], "QuickTime video with sound"),
    "clip.webm": (["-c:v", "libvpx", "-b:v", "500k", "-c:a", "libopus", "-b:a", "32k", "-shortest"],
                  "WebM video with sound"),
    "clip_no_audio.mp4": ([*H264, "-an"], "video with no audio track"),
    "notice.jpg": (None, "JPEG image of a notice"),
    "notice.webp": (None, "WebP image of a notice"),
    "renamed_clip.jpg": (None, "an MP4 renamed .jpg: must be refused as renamed"),
    "message.txt": (None, "plain text message"),
}


def ffmpeg(*args: str) -> None:
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", *args], check=True)


def voice_input(a, tmp: Path) -> list[str]:
    """ffmpeg input options for the sound: --voice, --tone, or the test voice note made now."""
    if a.tone:
        return TONE
    if a.voice:
        return ["-i", str(a.voice)]
    wav = tmp / "voice.wav"
    make_test_voice_note.speak(make_test_voice_note.TEXT, wav)
    return ["-i", str(wav)]


def make(out: Path, sound: list[str]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    for name, (opts, _) in FILES.items():
        if opts is None:
            continue
        video = name.startswith("clip")
        inputs = (PICTURE if video else []) + ([] if name == "clip_no_audio.mp4" else sound)
        if video and name != "clip_no_audio.mp4":
            inputs += ["-map", "0:v", "-map", "1:a"]
        ffmpeg(*inputs, *opts, str(out / name))
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        png = make_notice_image.make(Path(tmp), ["S3-ed-summons"])[0]
        img = Image.open(png).convert("RGB")
        img.save(out / "notice.jpg", quality=85)
        img.save(out / "notice.webp", quality=80)
    shutil.copyfile(out / "clip_no_audio.mp4", out / "renamed_clip.jpg")
    (out / "message.txt").write_text(make_notice_image.scenarios()["S1-rm-voice-note"]["text"], encoding="utf-8")
    with (out / "manifest.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "tests"])
        w.writerows((name, tests) for name, (_, tests) in FILES.items())
    return [out / name for name in FILES]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "clips" / "synthetic" / "format_sweep")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--voice", type=Path, help="a synthetic voice note to use as the sound")
    src.add_argument("--tone", action="store_true", help="use a 440 Hz sine instead of speech")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            sound = voice_input(a, Path(tmp))
        except RuntimeError as e:
            print(f"{e}; pass --voice FILE or --tone")
            return 1
        for p in make(a.out, sound):
            print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
