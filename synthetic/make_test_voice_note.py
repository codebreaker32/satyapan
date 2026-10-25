"""The synthetic "digital arrest" test voice note: a fixed scam script read by a text-to-speech voice, then encoded as
a 16 kHz mono Opus voice note (.ogg).

It uses no real person's voice. The voice is "Microsoft David Desktop", the stock English voice of Windows'
System.Speech, called through powershell.exe (on Windows, or from WSL). Where PowerShell is missing it falls back to
espeak-ng (or espeak), a formant synthesiser that models no speaker at all. The account number is invented and the
IFSC uses the DEMO prefix that no bank holds.

  python synthetic/make_test_voice_note.py --out /tmp/voice                  # TTS, then ffmpeg to .ogg
  python synthetic/make_test_voice_note.py --out /tmp/voice --wav mine.wav   # skip TTS, only encode a WAV you made

Writes digital_arrest_test_voice_note.ogg (and the intermediate .wav) to --out (default clips/synthetic/,
git-ignored). Needs imageio-ffmpeg (requirements.txt) for the ffmpeg it bundles.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "digital_arrest_test_voice_note"
VOICE = "Microsoft David Desktop"
TEXT = ("Listen carefully. You are digitally arrested. Do not disconnect this call, and do not tell anyone in your "
        "family. To clear your name, you must send all the money in your bank account today, to the R B I "
        "verification account. Account number: 3 0 0 1 1 2 2 3 3 4 4 5 5 6. I F S C code: D E M O 0 0 0 1 2 3 4. "
        "Send the money now, or you will be arrested.")
# 16 kHz mono Opus in Ogg. 24 kbit/s matches the original test note (85,722 bytes for 34.17 s; re-encoding its own
# audio at 24k gives 85,218 bytes, at 16k 59,350). The calibration's WhatsApp-like copies use 16k (channels.py).
OPUS = ["-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k"]


def powershell() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell")


def windows_path(p: Path) -> str:
    """A path powershell.exe can open: wslpath -w under WSL, the path itself on Windows."""
    if sys.platform.startswith("win"):
        return str(p)
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True, check=True).stdout.strip()


def speak_windows(text: str, wav: Path) -> None:
    """System.Speech with VOICE. The text goes through a UTF-8 file so no quoting can break it."""
    with tempfile.TemporaryDirectory(dir=wav.parent) as tmp:
        txt = Path(tmp) / "text.txt"
        txt.write_text(text, encoding="utf-8")
        script = "; ".join([
            "Add-Type -AssemblyName System.Speech",
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            f"$s.SelectVoice('{VOICE}')",
            f"$s.SetOutputToWaveFile('{windows_path(wav)}')",
            f"$s.Speak((Get-Content -Raw -Encoding UTF8 '{windows_path(txt)}'))",
            "$s.Dispose()",
        ])
        subprocess.run([powershell(), "-NoProfile", "-NonInteractive", "-Command", script], check=True)


def speak_espeak(text: str, wav: Path) -> None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    subprocess.run([exe, "-v", "en-us", "-w", str(wav), text], check=True)


def speak(text: str, wav: Path, engine: str = "auto") -> str:
    """Write `text` as speech to `wav`; return the engine used. Raises RuntimeError when no engine is installed."""
    if engine in ("auto", "windows") and powershell():
        speak_windows(text, wav)
        return f"System.Speech ({VOICE})"
    if engine in ("auto", "espeak") and (shutil.which("espeak-ng") or shutil.which("espeak")):
        speak_espeak(text, wav)
        return "espeak-ng"
    raise RuntimeError("no text-to-speech engine here: needs powershell.exe (Windows or WSL) or espeak-ng")


def encode(wav: Path, ogg: Path) -> Path:
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(wav), *OPUS, str(ogg)],
                   check=True)
    return ogg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "clips" / "synthetic")
    ap.add_argument("--engine", choices=("auto", "windows", "espeak"), default="auto")
    ap.add_argument("--wav", type=Path, help="encode this WAV instead of running text-to-speech")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    wav = a.wav or a.out / f"{NAME}.wav"
    if not a.wav:
        try:
            print(f"spoken by {speak(TEXT, wav, a.engine)}")
        except RuntimeError as e:
            print(e)
            return 1
    print(encode(wav, a.out / f"{NAME}.ogg"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
