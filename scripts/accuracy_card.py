"""Measured accuracy of the face and voice checks, counted the way the officer sees their results.

For each calibration cell: what the genuine and the fake clips got (flagged / unsure / no signs / declined to judge),
and the false-alarm rate on genuine clips that did not help set the threshold (5-fold cross-validation, 20 shuffles).
Writes calibration/accuracy.json (shown on the console's Evaluation page through GET /api/accuracy) and
docs/accuracy.md. Every number comes from calibration/*_runs.csv and calibration/*.json; nothing is re-scored.

  .venv/bin/python scripts/accuracy_card.py
"""
import csv
import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from forensics.common import threshold_at_fpr  # noqa: E402 - the same threshold rule the detectors are calibrated with

CAL = ROOT / "calibration"
DETECTORS = [("face", "video_runs.csv", "video.json"), ("voice", "audio_runs.csv", "audio.json")]

FAILURE_CASES = [
    ("face", "WhatsApp-size video (480 px or less): compression makes some genuine faces score like fakes, so the "
             "5% false-alarm line sits at 0.97 and none of the 6 face swaps cleared it. On a WhatsApp forward the "
             "face check rarely flags; it says no signs or unsure."),
    ("face", "Real-world footage is often declined: 66 of 138 clips were not judged (frames disagree 24, face under "
             "80 px 21, a usable face in too few frames 21). It says unsure rather than guess."),
    ("face", "Only 2 HD face swaps (one vendor sample), so the HD catch rate is an anecdote, not a measurement."),
    ("face", "Still images are not face-checked; they get the document check only."),
    ("face", "A video re-filmed with a camera pointed at a screen is not calibrated: the face check says unsure."),
    ("voice", "Less than 2 s of speech, or parts of a recording that disagree, and the voice check says unsure."),
    ("voice", "Voice conversion (FreeVC) is harder than text-to-speech (XTTS): on phone and WhatsApp-style Hindi audio "
              "it caught 20 and 23 of 31 FreeVC clones, against 29 of 29 XTTS clones."),
    ("voice", "A voice replayed through a speaker (recorded at the counter) hides traces of cloning: a clean result "
              "becomes unsure."),
    ("voice", "Genuine Hindi voices often score 0.99 or more on the raw model, so the Hindi lines sit at 0.9996 and "
              "above; a genuine video's sound track at 0.9986 landed in the grey band (unsure) in our live check."),
    ("both", "No public Indian scam-call audio or video exists to test on. Our fakes are lab-made (IndicSynth Hindi, "
             "In-the-Wild English celebrity speech, one face-swap vendor sample). Open detectors lose about half their "
             "accuracy on deepfakes circulated in 2024 (Deepfake-Eval-2024), so real-world catch rates may be lower."),
]


def outcome(score: float, t20: float, t5: float) -> str:
    """What the officer would see for a clip the detector judged."""
    if score >= t5:
        return "flagged"
    return "unsure" if score >= t20 else "no_signs"


def cv_false_alarm(real: list[float], folds: int = 5, repeats: int = 20) -> float:
    """Threshold set on 4/5 of the genuine clips, false alarms counted on the other 1/5, which never saw it."""
    flagged = total = 0
    for r in range(repeats):
        xs = real[:]
        random.Random(r).shuffle(xs)
        for k in range(folds):
            test = xs[k::folds]
            train = [x for i, x in enumerate(xs) if i % folds != k]
            t5 = threshold_at_fpr(train, 0.05)
            flagged += sum(s >= t5 for s in test)
            total += len(test)
    return flagged / total if total else float("nan")


def card(kind: str, runs: list[dict], cal: dict) -> list[dict]:
    out = []
    for cell, c in sorted(cal["cells"].items()):
        mine = [r for r in runs if r["cell"] == cell]
        if not mine:
            continue                                  # an aggregate cell (en/any, hi/any) the detector never picks
        t20, t5 = c["t_fpr20"], c["t_fpr5"]
        row = {"check": kind, "cell": cell, "t_fpr5": round(t5, 6), "t_fpr20": round(t20, 6)}
        for label in ("real", "fake"):
            judged = [float(r["median"]) for r in mine if r["label"] == label and r["usable"] == "True"]
            counts = {"flagged": 0, "unsure": 0, "no_signs": 0}
            for s in judged:
                counts[outcome(s, t20, t5)] += 1
            row["genuine" if label == "real" else "fake"] = {
                "n": len(judged) + sum(r["usable"] != "True" for r in mine if r["label"] == label),
                "judged": len(judged), **counts,
                "declined": sum(r["usable"] != "True" for r in mine if r["label"] == label),
                "sources": sorted({r["source"].split(":")[0] + (" (simulated)" if r.get("simulated") == "True" else "")
                                   for r in mine if r["label"] == label}),
            }
            if label == "real" and judged:
                row["genuine"]["false_alarm_heldout_pct"] = round(100 * cv_false_alarm(judged), 1)
        out.append(row)
    return out


def main() -> int:
    cells = []
    for kind, runs_name, cal_name in DETECTORS:
        with open(CAL / runs_name, newline="") as f:
            runs = list(csv.DictReader(f))
        cal = json.loads((CAL / cal_name).read_text())
        cells += card(kind, runs, cal)
    doc = {
        "_note": "Measured on public clips, never on customer data. We did not train or fine-tune either model; the "
                 "thresholds were set on the genuine clips only. 'Held-out false alarms' counts genuine clips that did "
                 "not help set the threshold (5-fold cross-validation). Fakes never set a threshold.",
        "made": date.today().isoformat(),
        "models": {"face": json.loads((CAL / "video.json").read_text()).get("model"),
                   "voice": json.loads((CAL / "audio.json").read_text()).get("model")},
        "cells": cells,
        "failure_cases": [{"check": k, "text": t} for k, t in FAILURE_CASES],
    }
    (CAL / "accuracy.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

    lines = ["# Measured accuracy of the face and voice checks", "", doc["_note"], "",
             "Outcomes are what the officer sees: flagged (counts in the score), unsure (not counted), no signs. "
             "Generated by `scripts/accuracy_card.py` from `calibration/*_runs.csv`.", "",
             "| Check | Cell | Genuine judged | False alarms (on threshold clips) | False alarms, held out | Genuine unsure | "
             "Fakes judged | Caught | Unsure | Missed | Declined (genuine / fake) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        g, f = c["genuine"], c["fake"]
        lines.append(f"| {c['check']} | {c['cell']} | {g['judged']} | {g['flagged']} | {g.get('false_alarm_heldout_pct', '-')}% | "
                     f"{g['unsure']} | {f['judged']} | {f['flagged']} | {f['unsure']} | {f['no_signs']} | "
                     f"{g['declined']} / {f['declined']} |")
    lines += ["", "## Where it fails (named)", ""] + [f"- **{k}:** {t}" for k, t in FAILURE_CASES]
    (ROOT / "docs" / "accuracy.md").write_text("\n".join(lines) + "\n")
    for c in cells:
        g, f = c["genuine"], c["fake"]
        print(f"{c['check']:5} {c['cell']:17} genuine {g['judged']:3} judged: {g['flagged']} flagged "
              f"(held-out {g.get('false_alarm_heldout_pct')}%), {g['unsure']} unsure | fakes {f['judged']:3} judged: "
              f"{f['flagged']} caught, {f['unsure']} unsure, {f['no_signs']} missed | declined {g['declined']}/{f['declined']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
