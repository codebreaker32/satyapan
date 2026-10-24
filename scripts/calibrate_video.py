"""Set the video detector's thresholds on labelled clips and report how well it does.

Manifest: a CSV with columns `path,label[,cell,source]`, where label is `real` or `fake`. `cell` is optional; when it
is missing the cell is worked out from the video's resolution (video/sd or video/hd). `source` names the dataset.

  .venv/bin/python scripts/calibrate_video.py --manifest clips/video_manifest.csv

Writes (only numbers and file lists, never the clips):
  calibration/video.json         thresholds per cell (no pooled fallback: an uncalibrated cell abstains)
  calibration/video_runs.csv     every clip: sha256, label, cell, measurements, why it was or wasn't used
  calibration/video_report.md    plain report: counts, abstentions, catch rate at each threshold, AUC

Thresholds come from REAL clips only (see forensics/common.py). A clip only counts toward thresholds if it passes the
detector's other abstain gates (face found, big enough, enough frames, frames agree), because only those clips would
ever reach the threshold in use. t_fpr1 is only set with at least 100 usable real clips.
"""
import argparse
import csv
import os
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensics.common import Calibration, CellCalibration, threshold_at_fpr  # noqa: E402
from forensics.video import MODEL_NAME, GenDVideoForensics, sha256_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MIN_REAL_FOR_CELL = 10      # fewer usable real clips than this -> the cell is not calibrated (detector abstains)


def reason_category(reason: str) -> str:
    """Group abstain reasons for the report ("face too small (about 36 px...)" -> "the face is too small to judge")."""
    for key, label in (("too small", "the face is too small to judge (under 80 px)"),
                       ("usable face was visible in only", "a usable face was visible in too few frames"),
                       ("frames disagree", "the frames disagree with each other"),
                       ("no face", "no face was found"), ("could not be read", "the video could not be read")):
        if key in reason:
            return label
    return reason or "unknown"


def auc(real: list[float], fake: list[float]) -> float | None:
    """Probability a random fake scores above a random real (Mann-Whitney U / (n_r * n_f)); ties count half."""
    if not real or not fake:
        return None
    wins = sum((f > r) + 0.5 * (f == r) for f in fake for r in real)
    return wins / (len(real) * len(fake))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "calibration" / "video.json")
    ap.add_argument("--runs", type=Path, default=ROOT / "calibration" / "video_runs.csv")
    ap.add_argument("--report", type=Path, default=ROOT / "calibration" / "video_report.md")
    ap.add_argument("--from-runs", action="store_true", help="rebuild thresholds and report from --runs without re-scoring")
    a = ap.parse_args()
    if a.from_runs:
        runs = []
        for r in csv.DictReader(a.runs.open()):
            r["usable"] = r["usable"] == "True"
            r["median"] = float(r["median"]) if r["median"] not in ("", "None") else None
            runs.append(r)
        return write_outputs(a, runs)

    rows = list(csv.DictReader(a.manifest.open()))
    bad = [r for r in rows if r.get("label") not in ("real", "fake")]
    if bad:
        raise SystemExit(f"labels must be 'real' or 'fake'; bad rows: {bad[:3]}")

    det = GenDVideoForensics(calibration=None)
    runs = []
    for i, r in enumerate(rows, 1):
        p = Path(r["path"])
        if not p.is_absolute():
            p = (a.manifest.parent / p).resolve()
        m = det.measure(p) if p.is_file() else {"frames_total": 0, "frames_tried": 0, "faces_scored": 0, "too_small": 0, "face_px": []}
        _, _, _, score, cell = det.decide(m, r.get("cell") or None)
        gate_reason = det.gate(m) if p.is_file() else "the file was not found"
        usable = gate_reason is None and score is not None
        reason = gate_reason or ""
        runs.append({"path": os.path.relpath(p, ROOT) if p.is_absolute() else r["path"], "sha256": sha256_of(p) if p.is_file() else "", "label": r["label"],
                     "source": r.get("source", ""), "cell": cell, "median": score,
                     "spread": round(m["spread"], 4) if "spread" in m else None, "faces_scored": m.get("faces_scored"),
                     "frames_tried": m.get("frames_tried"), "usable": usable, "why_not": "" if usable else reason,
                     "seconds": (m.get("seconds") or {}).get("total") if isinstance(m.get("seconds"), dict) else m.get("seconds")})
        print(f"[{i}/{len(rows)}] {r['label']:4s} {cell:9s} median={runs[-1]['median']} usable={usable} {'' if usable else '(' + reason + ')'}")

    return write_outputs(a, runs)


def write_outputs(a, runs: list[dict]) -> int:
    a.runs.parent.mkdir(parents=True, exist_ok=True)
    with a.runs.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0].keys()))
        w.writeheader()
        w.writerows(runs)

    by_cell: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"real": [], "fake": []})
    for r in runs:
        if r["usable"]:
            by_cell[r["cell"]][r["label"]].append(r["median"])
    abstained_fakes = Counter(r["cell"] for r in runs if r["label"] == "fake" and not r["usable"])

    cal = Calibration(model=MODEL_NAME, cells={})
    lines = ["# Video detector calibration report", "", f"Model: `{MODEL_NAME}`. Manifest: `{a.manifest.name}`, {len(runs)} clips.", "",
             "Thresholds are set on real clips only. Catch rate = share of fake clips at or above the threshold.", ""]
    lines += ["Each cell is calibrated on its own clips; a kind of video with no cell here makes the detector abstain.",
              "Catch rates count only fakes the detector judged; 'Fakes abstained' are the ones it declined to judge.", "",
              "| Cell | Usable real | Usable fake | Fakes abstained | t_fpr20 | t_fpr5 | t_fpr1 | Catch at 5% FPR | Catch at 20% FPR | AUC |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for cell, d in sorted(by_cell.items()):
        real, fake = d["real"], d["fake"]
        if len(real) < MIN_REAL_FOR_CELL:
            lines.append(f"| {cell} | {len(real)} | {len(fake)} | {abstained_fakes[cell]} | not set (needs {MIN_REAL_FOR_CELL} real) | | | | | |")
            continue
        t20, t5 = threshold_at_fpr(real, 0.20), threshold_at_fpr(real, 0.05)
        t1 = threshold_at_fpr(real, 0.01) if len(real) >= 100 else None
        cal.cells[cell] = CellCalibration(t_fpr5=t5, t_fpr20=t20, t_fpr1=t1, n_real=len(real), n_fake=len(fake))
        c5 = sum(s >= t5 for s in fake) / len(fake) if fake else None
        c20 = sum(s >= t20 for s in fake) / len(fake) if fake else None
        A = auc(real, fake)
        f = lambda v: "-" if v is None else f"{v:.3f}"
        lines.append(f"| {cell} | {len(real)} | {len(fake)} | {abstained_fakes[cell]} | {f(t20)} | {f(t5)} | {f(t1)} | {f(c5)} | {f(c20)} | {f(A)} |")
    why = Counter(reason_category(r["why_not"]) for r in runs if not r["usable"])
    lines += ["", "## Clips the detector declined to judge (not used for thresholds)", ""]
    lines += [f"- {k}: {v}" for k, v in why.most_common()] or ["- none"]
    lines += ["", "With few real clips these thresholds are coarse; the counts above say how much to trust them."]
    cal.save(a.out)
    a.report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {a.out}, {a.runs}, {a.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
