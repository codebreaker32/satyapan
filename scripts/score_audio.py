"""Score one voice note (or the voice in a video) and print what the officer would see.

  .venv/bin/python scripts/score_audio.py note.ogg
  .venv/bin/python scripts/score_audio.py note.ogg --language en --json
  .venv/bin/python scripts/score_audio.py counter_recording.webm --channel live-replay

--channel live-replay is for a recording made by playing the customer's phone into a microphone. Replay hides much of a
clone's traces, so in that channel "no signs" is reported as "unsure"; signs of cloning still count.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensics.audio import DFArenaAudioForensics  # noqa: E402
from forensics.common import Calibration  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path)
    ap.add_argument("--language", default="hi", help="hi or en (sets the calibration cell)")
    ap.add_argument("--channel", help="override the channel: clean, whatsapp-opus, phone-8k or live-replay")
    ap.add_argument("--size", choices=["500M", "1B"], default="500M")
    ap.add_argument("--calibration", type=Path, help="defaults to calibration/audio.json (500M) or audio_1b.json")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args()
    cal_path = a.calibration or ROOT / "calibration" / ("audio.json" if a.size == "500M" else f"audio_{a.size.lower()}.json")
    cal = Calibration.load(cal_path) if cal_path.exists() else None
    r = DFArenaAudioForensics(calibration=cal, size=a.size).analyse(a.audio, language=a.language, channel=a.channel)
    if a.json:
        print(json.dumps(r.to_dict(), indent=1, ensure_ascii=False))
    else:
        print(r.officer_line())
        secs = r.extra.get("seconds") or {}
        print(f"  status={r.status} band={r.band or '-'} score={r.score} cell={r.cell} model={r.model}")
        print(f"  {r.extra.get('speech_s', '-')} s of voice in {r.extra.get('duration_s', '-')} s;"
              f" window scores {r.extra.get('window_scores', [])}; scoring {secs.get('score', '-')} s")
        if cal is None:
            print("  (no calibration file: the detector abstains until thresholds are set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
