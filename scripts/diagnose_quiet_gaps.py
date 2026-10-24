"""Diagnosis, not a fix: are genuine phone calls called fake because the gaps between words are too quiet?

The smoke test (calibration/smoke_genuine.md) found that the genuine Gram Vaani calls DF Arena calls fake have a
quieter background than the ones it passes. Phone networks suppress the noise between words, and synthetic speech has
near-digital silence there too. This adds faint white noise at a fixed level to (1) the genuine clips that were called
fake and (2) the fake IndicSynth clips, as a control, and scores both again. If noise drops the genuine clips' scores,
the quiet gaps are part of the cause. If it also drops the fakes' scores, added noise is a way to hide a clone, so it
must never be used as a fix.

  python scripts/diagnose_quiet_gaps.py --smoke calibration/smoke_genuine.csv --manifest clips/audio_manifest.csv
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forensics.audio import DFArenaAudioForensics, decode_audio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--noise-db", type=float, default=-45.0, help="RMS level of the added noise, dBFS")
    ap.add_argument("--out", type=Path, default=ROOT / "calibration" / "diagnose_quiet_gaps.md")
    a = ap.parse_args()
    clips = a.manifest.parent
    flagged = [r for r in csv.DictReader(a.smoke.open(encoding="utf-8"))
               if r["status"] == "synthetic" and r["simulated"] == "False"]
    fakes = [r for r in csv.DictReader(a.manifest.open(encoding="utf-8")) if r["source"].startswith("indicsynth")]
    det = DFArenaAudioForensics(calibration=None)
    rng = np.random.default_rng(0)
    amp = 10 ** (a.noise_db / 20)

    def score(wav):
        m = det.measure_wave(wav)
        return m.get("median")

    rows = []
    for group, items in (("genuine, called fake", [(r["path"], r["source"]) for r in flagged]),
                         ("fake (IndicSynth)", [(r["path"], r["source"]) for r in fakes])):
        for path, src in items:
            p = Path(path) if Path(path).is_absolute() else (clips / path)
            wav = decode_audio(p)[0]
            before = score(wav)
            after = score((wav + rng.normal(0, amp, len(wav))).astype(np.float32))
            if before is None or after is None:
                continue
            rows.append((group, Path(path).name, before, after))
            print(f"{group:22s} {Path(path).name:28s} {before:.6f} -> {after:.6f}", flush=True)

    lines = ["# Diagnosis: do quiet gaps between words make genuine calls look fake?", "",
             f"White noise at {a.noise_db:.0f} dBFS RMS was added to each clip, which was then scored again (raw DF Arena "
             "score, before any threshold). This is a diagnosis only. Added noise is never a fix: see the control row.", "",
             "| Group | Clips | Median score before | Median after | Clips whose score fell |", "|---|---|---|---|---|"]
    for group in ("genuine, called fake", "fake (IndicSynth)"):
        g = [r for r in rows if r[0] == group]
        if g:
            lines.append(f"| {group} | {len(g)} | {statistics.median(r[2] for r in g):.6f} | "
                         f"{statistics.median(r[3] for r in g):.6f} | {sum(r[3] < r[2] for r in g)} of {len(g)} |")
    a.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
