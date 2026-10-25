"""The demo's synthetic notice images: a scenario's notice TEXT drawn on a plain white page with a diagonal SYNTHETIC
watermark, by prototype/tests/notice_render.py (the same renderer tests/test_ocr.py reads back with Tesseract).
No logo, emblem, seal, signature or real official's name is drawn: only the scenario's invented text.

  python synthetic/make_notice_image.py --out /tmp/notices            # ED_summons_synthetic.png (scenario S3)
  python synthetic/make_notice_image.py --out /tmp/notices --all      # every scenario read by OCR, <id>_synthetic.png

Needs Pillow and the DejaVu Sans font (Arial on Windows). Default output folder: clips/synthetic/ (git-ignored).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "prototype" / "data" / "fixtures" / "scenarios.json"
DEMO = {"S3-ed-summons": "ED_summons_synthetic.png"}     # the file the demo used, under its demo name


def renderer():
    """prototype/tests/notice_render.py, loaded by path (the root tests/ folder would shadow a `tests` import)."""
    spec = importlib.util.spec_from_file_location("notice_render", ROOT / "prototype" / "tests" / "notice_render.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scenarios() -> dict[str, dict]:
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["scenarios"]}


def make(out: Path, ids: list[str]) -> list[Path]:
    render, by_id, made = renderer().render_notice, scenarios(), []
    out.mkdir(parents=True, exist_ok=True)
    for sid in ids:
        path = out / DEMO.get(sid, f"{sid}_synthetic.png")
        render(by_id[sid]["text"], path)
        made.append(path)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "clips" / "synthetic")
    ap.add_argument("--all", action="store_true", help="every scenario whose text arrives by OCR")
    ap.add_argument("ids", nargs="*", help="scenario ids (default: S3-ed-summons)")
    a = ap.parse_args()
    ids = a.ids or ([s for s, v in scenarios().items() if v.get("source") == "ocr"] if a.all else list(DEMO))
    for p in make(a.out, ids):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
