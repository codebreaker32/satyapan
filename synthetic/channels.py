"""The channel simulations used for calibration, in one place. Thin wrappers only: every encoder setting lives in the
script or module that made the calibration data, and is imported from there (synthetic/README.md lists them).

  whatsapp-opus     a WhatsApp-like voice note file (.ogg)       scripts/prepare_audio_clips.py   whatsapp_opus()
  whatsapp-video    a WhatsApp-size copy of a video (.mp4)       scripts/whatsappify.py           reencode()
  sim-whatsapp-opus the voice detector's in-memory Opus copy     scripts/calibrate_audio.py       through_channel()
  sim-phone-8k      the voice detector's in-memory 8 kHz copy    scripts/calibrate_audio.py       through_channel()
  aasist-clean-16k  the AASIST-L fallback's channel copies       prototype/satyapan/calibrate.py  _encode(), CHANNELS
  aasist-amr-8k
  aasist-whatsapp-opus

  python synthetic/channels.py whatsapp-opus  in.wav  out.ogg
  python synthetic/channels.py whatsapp-video in.mp4  out.mp4
  python synthetic/channels.py sim-phone-8k   in.wav  out.wav      # written back as 16 kHz WAV, as the detector scored it

The first four need the detectors' venv (imageio-ffmpeg, PyAV, soundfile; requirements.txt). The aasist-* channels
import the engine package, so they need the engine's venv (prototype/pyproject.toml). Imports happen inside each
function, so each venv can use the channels it has.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path(p: Path) -> None:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def whatsapp_opus(src: Path, dst: Path) -> Path:
    """Opus in Ogg, 16 kHz mono, 16 kbit/s, with ffmpeg: the hi/whatsapp-opus calibration clips."""
    _path(ROOT / "scripts")
    from prepare_audio_clips import whatsapp_opus as encode
    return encode(Path(src), Path(dst))


def whatsapp_video(src: Path, dst: Path) -> Path:
    """H.264, short side at most 480 px, CRF 30 capped at 900 kbit/s, AAC 64 kbit/s: the video calibration's WhatsApp
    cells. Like the script, it keeps an existing non-empty dst rather than re-encoding it."""
    _path(ROOT / "scripts")
    from whatsappify import reencode
    return reencode(Path(src), Path(dst))


def through_channel(wav, channel: str):
    """16 kHz mono float32 audio as it sounds after `channel` ("whatsapp-opus" or "phone-8k"), back at 16 kHz.

    The voice detector's calibration scores every clean clip this way too (rows marked `simulated`). The Opus path
    writes one scratch file, clips/.channel_tmp.ogg, inside the repo's git-ignored clips/ folder."""
    _path(ROOT)
    _path(ROOT / "scripts")
    from calibrate_audio import through_channel as simulate
    if channel == "whatsapp-opus":
        (ROOT / "clips").mkdir(exist_ok=True)
    return simulate(wav, channel)


def simulated_copy(src: Path, dst: Path, channel: str) -> Path:
    """through_channel() applied to a file: decode to 16 kHz mono, simulate, write a 16 kHz WAV."""
    _path(ROOT)
    import soundfile as sf
    from forensics.audio import SAMPLE_RATE, decode_audio
    wav = decode_audio(Path(src))[0]
    sf.write(str(dst), through_channel(wav, channel), SAMPLE_RATE)
    return Path(dst)


def aasist_channel(src: Path, dst: Path, channel: str) -> Path:
    """One of the AASIST-L calibration channels ("clean-16k", "amr-8k" or "whatsapp-opus"), written with PyAV."""
    _path(ROOT / "prototype")
    from satyapan.calibrate import CHANNELS, _encode
    from satyapan.forensics import decode_audio
    fmt, codec, rate, bit_rate = CHANNELS[channel]
    _encode(decode_audio(Path(src))[0], Path(dst), fmt, codec, rate, bit_rate)
    return Path(dst)


CLI = {
    "whatsapp-opus": whatsapp_opus,
    "whatsapp-video": whatsapp_video,
    "sim-whatsapp-opus": lambda s, d: simulated_copy(s, d, "whatsapp-opus"),
    "sim-phone-8k": lambda s, d: simulated_copy(s, d, "phone-8k"),
    "aasist-clean-16k": lambda s, d: aasist_channel(s, d, "clean-16k"),
    "aasist-amr-8k": lambda s, d: aasist_channel(s, d, "amr-8k"),
    "aasist-whatsapp-opus": lambda s, d: aasist_channel(s, d, "whatsapp-opus"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("channel", choices=sorted(CLI))
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    a = ap.parse_args()
    a.dst.parent.mkdir(parents=True, exist_ok=True)
    print(CLI[a.channel](a.src, a.dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
