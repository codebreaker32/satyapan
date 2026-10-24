"""Smoke test: genuine voices the calibration never used. Is any real person called fake, how sure is the detector,
and what do the wrongly flagged clips have in common?

  python scripts/smoke_genuine.py --manifest clips/smoke_manifest.csv

Manifest: `path,label,language,source,channel`, like the calibration one; every row should be `real` and none of them
in calibration/audio_runs.csv (the script checks by sha256 and refuses overlap). A clean clip is also scored after the
simulated WhatsApp Opus, AAC (video sound) and 8 kHz phone channels, as in the calibration.

Writes calibration/smoke_genuine.csv (one row per scored version, with the measurements below) and
calibration/smoke_genuine.md (plain report). Measurements, per clip:
  level_db   loud level: 99th percentile of 30 ms frame energy, dBFS
  floor_db   background: 10th percentile of frame energy, dBFS
  snr_db     level_db - floor_db, a rough signal-to-noise ratio
  clipped    share of samples at full scale (|x| >= 0.99)
"""
import argparse
import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from calibrate_audio import SIMULATED, through_channel  # noqa: E402
from forensics.audio import SAMPLE_RATE, DFArenaAudioForensics, channel_for, decode_audio, sha256_of  # noqa: E402
from forensics.common import Calibration  # noqa: E402


def loudness(wav: np.ndarray) -> dict:
    n = int(SAMPLE_RATE * 0.03)
    frames = wav[: len(wav) // n * n].reshape(-1, n) if len(wav) >= n else wav.reshape(1, -1)
    db = 10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    level, floor = float(np.percentile(db, 99)), float(np.percentile(db, 10))
    return {"level_db": round(level, 1), "floor_db": round(floor, 1), "snr_db": round(level - floor, 1),
            "clipped": round(float(np.mean(np.abs(wav) >= 0.99)), 5)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--calibration", type=Path, default=ROOT / "calibration" / "audio.json")
    ap.add_argument("--used", type=Path, default=ROOT / "calibration" / "audio_runs.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "calibration" / "smoke_genuine")
    a = ap.parse_args()

    rows = list(csv.DictReader(a.manifest.open(encoding="utf-8")))
    if any(r["label"] != "real" for r in rows):
        raise SystemExit("the smoke test is for genuine voices: every label must be 'real'")
    used = {r["sha256"] for r in csv.DictReader(a.used.open(encoding="utf-8")) if r.get("sha256")}
    det = DFArenaAudioForensics(calibration=Calibration.load(a.calibration))
    out = []
    for i, r in enumerate(rows, 1):
        p = Path(r["path"])
        p = p if p.is_absolute() else (a.manifest.parent / p).resolve()
        sha = sha256_of(p)
        if sha in used:
            raise SystemExit(f"{r['path']} was used to set the thresholds; a smoke test must use unseen clips")
        try:
            wav, rate, codec = decode_audio(p)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(rows)}] {r['path']}: could not decode ({type(e).__name__})")
            continue
        native = r.get("channel") or channel_for(codec, rate)
        variants = [(native, wav, False)] + ([(ch, through_channel(wav, ch), True) for ch in SIMULATED]
                                             if native == "clean" else [])
        for ch, w, sim in variants:
            m = det.measure_wave(w, rate if not sim else SAMPLE_RATE, codec)
            status, band, reason, score, cell = det.decide(m, r.get("language") or "hi", ch)
            row = {"path": r["path"], "sha256": sha, "source": r.get("source", ""), "cell": cell, "simulated": sim,
                   "status": status, "band": band, "reason": reason, "score": score, "range": m.get("range"),
                   "windows": " ".join(f"{s:.4f}" for s in m.get("window_scores", [])),
                   "duration_s": m["duration_s"], "speech_s": m["speech_s"]} | loudness(w)
            out.append(row)
            print(f"[{i}/{len(rows)}] {cell:17s} {status:9s} {band:8s} score={score}", flush=True)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    by_cell = defaultdict(list)
    for r in out:
        by_cell[r["cell"]].append(r)
    lines = ["# Smoke test: genuine voices the calibration never used", "",
             f"Calibration: `{a.calibration.name}` ({det.model_name}). Manifest: `{a.manifest.name}`, {len(rows)} genuine "
             f"clips, {len(out)} scored versions. None of these clips was used to set the thresholds.", "",
             "\"Called fake\" = status synthetic. The thresholds were set so that about 5% of the calibration's real clips "
             "are called fake; on unseen clips the share should be similar if the thresholds generalise.", "",
             "| Cell | Versions | Called fake | of which high | moderate | Unsure | No signs |", "|---|---|---|---|---|---|---|"]
    for cell, rs in sorted(by_cell.items()):
        c = Counter(r["status"] for r in rs)
        b = Counter(r["band"] for r in rs if r["status"] == "synthetic")
        lines.append(f"| {cell} | {len(rs)} | {c['synthetic']} ({100 * c['synthetic'] / len(rs):.1f}%) | {b['high']} | "
                     f"{b['moderate']} | {c['abstain']} | {c['clean']} |")
    judged = [r for r in out if r["status"] in ("synthetic", "clean")]
    fake, ok = [r for r in judged if r["status"] == "synthetic"], [r for r in judged if r["status"] == "clean"]
    med = lambda rs, k: "-" if not rs else f"{statistics.median(float(r[k]) for r in rs):.1f}"
    lines += ["", "## What the wrongly flagged genuine clips have in common", "",
              f"Judged versions only ({len(judged)}: {len(fake)} called fake, {len(ok)} no signs). Medians:", "",
              "| Measure | Called fake | No signs |", "|---|---|---|"]
    for k, label in (("speech_s", "seconds of voice"), ("duration_s", "clip length, s"), ("level_db", "loud level, dBFS"),
                     ("floor_db", "background level, dBFS"), ("snr_db", "signal-to-noise, dB")):
        lines.append(f"| {label} | {med(fake, k)} | {med(ok, k)} |")
    srcs = Counter((r["source"].split(":")[0], r["simulated"]) for r in fake)
    lines += ["", "Called fake, by source: " + (", ".join(f"{s}{' (sim)' if sim else ''} {n}" for (s, sim), n in
                                                    srcs.most_common()) or "none") + "."]
    raw = [r["score"] for r in out if r["score"] is not None]
    if raw:
        lines += ["", f"Raw model score on these genuine voices: {sum(s >= 0.99 for s in raw)} of {len(raw)} "
                      f"({100 * sum(s >= 0.99 for s in raw) / len(raw):.0f}%) score 0.99 or more, which is why the "
                      "thresholds sit near 1.0 and why a raw score is never shown as proof."]
    if fake:
        lines += ["", "## Every genuine version called fake", "",
                  "| Clip | Cell | Band | Score | Voice s | SNR dB | Windows |", "|---|---|---|---|---|---|---|"]
        for r in sorted(fake, key=lambda r: -r["score"]):
            lines.append(f"| {Path(r['path']).name} | {r['cell']} | {r['band']} | {r['score']:.6f} | {r['speech_s']} | "
                         f"{r['snr_db']} | {r['windows']} |")
    a.out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
