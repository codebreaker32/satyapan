"""Score one video and print what the officer would see.

  .venv/bin/python scripts/score_video.py clip.mp4
  .venv/bin/python scripts/score_video.py clip.mp4 --calibration calibration/video.json --json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensics.common import Calibration  # noqa: E402
from forensics.video import GenDVideoForensics  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--calibration", type=Path, default=Path(__file__).resolve().parent.parent / "calibration" / "video.json")
    ap.add_argument("--cell", help="override the calibration cell (e.g. video/sd)")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args()
    cal = Calibration.load(a.calibration) if a.calibration.exists() else None
    r = GenDVideoForensics(calibration=cal).analyse(a.video, cell=a.cell)
    if a.json:
        print(json.dumps(r.to_dict(), indent=1))
    else:
        print(r.officer_line())
        secs = r.extra.get("seconds", {})
        print(f"  status={r.status} band={r.band or '-'} score={r.score} cell={r.cell} model={r.model}")
        print(f"  faces scored {r.extra.get('faces_scored')} of {r.extra.get('frames_tried')} frames tried;"
              f" spread {round(r.extra['spread'], 3) if 'spread' in r.extra else '-'};"
              f" {secs.get('total', secs) if isinstance(secs, dict) else secs} s")
        if cal is None:
            print("  (no calibration file: the detector abstains until thresholds are set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
