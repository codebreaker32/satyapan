"""Set the voice detector's thresholds on labelled clips and report how well it does.

Manifest: a CSV with columns `path,label[,language,source,channel]` (scripts/fetch_audio_clips.py writes one), where
label is `real` or `fake`. `channel` is optional; when it is missing it is worked out from the file (clean,
whatsapp-opus or phone-8k).

  .venv/bin/python scripts/calibrate_audio.py --manifest clips/audio_manifest.csv

Simulated channels: a clean clip is also scored after being sent through the two channels a bank officer actually
receives, made here in memory: WhatsApp-style Opus (16 kHz mono, 16 kbit/s) and an 8 kHz phone band. Those rows are
marked `simulated` in the runs file and the report. Clips that already came through a real channel (Gram Vaani phone
calls) are scored as they are.

Writes (only numbers and file lists, never the clips):
  calibration/audio.json         thresholds per cell (language/channel), plus a pooled "<language>/any" cell
  calibration/audio_runs.csv     every scored clip: sha256, label, cell, scores, why it was or wasn't used
  calibration/audio_report.md    plain report: counts, catch rate at each threshold per cell and per fake source, AUC

Thresholds come from REAL clips only (see forensics/common.py), and only from clips that pass the detector's other
abstain gates. t_fpr1 is only set with at least 100 usable real clips.
"""
import argparse
import csv
import io
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forensics.audio import SAMPLE_RATE, DFArenaAudioForensics, channel_for, decode_audio, sha256_of  # noqa: E402
from forensics.common import Calibration, CellCalibration, threshold_at_fpr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MIN_REAL_FOR_CELL = 10
SIMULATED = ("whatsapp-opus", "phone-8k")


def auc(real: list[float], fake: list[float]) -> float | None:
    """Probability a random fake scores above a random real (Mann-Whitney U / (n_r * n_f)); ties count half."""
    if not real or not fake:
        return None
    wins = sum((f > r) + 0.5 * (f == r) for f in fake for r in real)
    return wins / (len(real) * len(fake))


def through_channel(wav: np.ndarray, channel: str) -> np.ndarray:
    """The clip as it sounds after a WhatsApp voice note (Opus 16 kbit/s) or an 8 kHz phone line, back at 16 kHz."""
    import av
    if channel == "phone-8k":
        down = av.AudioResampler(format="flt", layout="mono", rate=8000)
        up = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        frame = av.AudioFrame.from_ndarray(wav.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        narrow = [f for f in down.resample(frame)] + [f for f in down.resample(None)]
        out = []
        for f in narrow:
            out += [g.to_ndarray().reshape(-1) for g in up.resample(f)]
        out += [g.to_ndarray().reshape(-1) for g in up.resample(None)]
        return np.concatenate(out).astype(np.float32)
    if channel == "whatsapp-opus":
        buf = io.BytesIO()
        with av.open(buf, "w", format="ogg") as c:
            s = c.add_stream("libopus", rate=48000, layout="mono")
            s.bit_rate = 16000
            frame = av.AudioFrame.from_ndarray(wav.reshape(1, -1), format="flt", layout="mono")
            frame.sample_rate = SAMPLE_RATE
            for p in s.encode(frame):
                c.mux(p)
            for p in s.encode(None):
                c.mux(p)
        buf.seek(0)
        tmp = ROOT / "clips" / ".channel_tmp.ogg"
        tmp.write_bytes(buf.getvalue())
        return decode_audio(tmp)[0]
    raise ValueError(channel)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--size", choices=["500M", "1B"], default="500M")
    ap.add_argument("--max-per-source", type=int, default=150, help="cap clips per source (fixed seed)")
    ap.add_argument("--no-simulate", action="store_true", help="score clips only as they are")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    stem = "audio" if a.size == "500M" else f"audio_{a.size.lower()}"
    out = a.out or ROOT / "calibration" / f"{stem}.json"
    runs_path, report_path = out.with_name(f"{stem}_runs.csv"), out.with_name(f"{stem}_report.md")

    rows = list(csv.DictReader(a.manifest.open(encoding="utf-8")))
    bad = [r for r in rows if r.get("label") not in ("real", "fake")]
    if bad:
        raise SystemExit(f"labels must be 'real' or 'fake'; bad rows: {bad[:3]}")
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_source[r.get("source", "").split(":")[0]].append(r)
    rng = random.Random(a.seed)
    picked = []
    for src, rs in sorted(by_source.items()):
        rs = sorted(rs, key=lambda r: r["path"])
        rng.shuffle(rs)
        # keep both labels when a source has both (In-the-Wild)
        for label in ("real", "fake"):
            picked += [r for r in rs if r["label"] == label][: a.max_per_source]

    det = DFArenaAudioForensics(calibration=None, size=a.size)
    runs = []
    for i, r in enumerate(picked, 1):
        p = Path(r["path"])
        if not p.is_absolute():
            p = (a.manifest.parent / p).resolve()
        lang = r.get("language") or "hi"
        try:
            wav, rate, codec = decode_audio(p)
        except Exception as e:                                 # unreadable clip: recorded, never used
            runs.append({"path": r["path"], "sha256": "", "label": r["label"], "source": r.get("source", ""),
                         "cell": "", "simulated": False, "median": None, "range": None, "speech_s": None,
                         "usable": False, "why_not": f"could not decode ({type(e).__name__})", "seconds": None})
            continue
        native = r.get("channel") or channel_for(codec, rate)
        variants = [(native, wav, False)]
        if native == "clean" and not a.no_simulate:
            variants += [(ch, through_channel(wav, ch), True) for ch in SIMULATED]
        for ch, w, sim in variants:
            m = det.measure_wave(w, rate if not sim else SAMPLE_RATE, codec)
            status, _, reason, score, cell = det.decide(m, lang, ch)
            gate = det.gate(m)
            usable = gate is None and score is not None
            runs.append({"path": r["path"], "sha256": sha256_of(p), "label": r["label"], "source": r.get("source", ""),
                         "cell": cell, "simulated": sim, "median": score,  # unrounded: rounding made real and fake clips tie
                         "range": round(m["range"], 4) if "range" in m else None, "speech_s": m["speech_s"],
                         "usable": usable, "why_not": "" if usable else (gate or reason),
                         "seconds": (m.get("seconds") or {}).get("score")})
            print(f"[{i}/{len(picked)}] {r['label']:4s} {cell:16s} median={runs[-1]['median']} usable={usable}"
                  f"{'' if usable else ' (' + runs[-1]['why_not'] + ')'}", flush=True)

    runs_path.parent.mkdir(parents=True, exist_ok=True)
    with runs_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0].keys()))
        w.writeheader()
        w.writerows(runs)

    by_cell: dict[str, dict[str, list]] = defaultdict(lambda: {"real": [], "fake": []})
    for r in runs:
        if r["usable"]:
            by_cell[r["cell"]][r["label"]].append(r)
            by_cell[r["cell"].split("/")[0] + "/any"][r["label"]].append(r)

    cal = Calibration(model=det.model_name, cells={})
    f = lambda v: "-" if v is None else f"{v:.3f}"
    ft = lambda v: "-" if v is None else f"{v:.6f}"     # thresholds sit near 1.0, so 3 decimals hide them
    lines = ["# Voice detector calibration report", "",
             f"Model: `{det.model_name}`. Manifest: `{a.manifest.name}`, {len(picked)} clips, {len(runs)} scored versions.", "",
             "Thresholds are set on real clips only. Catch rate = share of fake clips at or above the threshold.",
             "Channels marked simulated were made from clean clips in memory (Opus 16 kbit/s; 8 kHz phone band).", "",
             "| Cell | Usable real | Usable fake | t_fpr20 | t_fpr5 | t_fpr1 | Catch at 5% FPR | Catch at 20% FPR | AUC | Real sources | Fake sources |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    per_source = []
    for cell, d in sorted(by_cell.items()):
        real, fake = [x["median"] for x in d["real"]], [x["median"] for x in d["fake"]]
        srcs = lambda xs: ", ".join(sorted({x["source"].split(":")[0] + (" (sim)" if x["simulated"] else "") for x in xs})) or "-"
        if len(real) < MIN_REAL_FOR_CELL:
            lines.append(f"| {cell} | {len(real)} | {len(fake)} | not set (needs {MIN_REAL_FOR_CELL} real) | | | | | | {srcs(d['real'])} | {srcs(d['fake'])} |")
            continue
        t20, t5 = threshold_at_fpr(real, 0.20), threshold_at_fpr(real, 0.05)
        t1 = threshold_at_fpr(real, 0.01) if len(real) >= 100 else None
        cal.cells[cell] = CellCalibration(t_fpr5=t5, t_fpr20=t20, t_fpr1=t1, n_real=len(real), n_fake=len(fake))
        c5 = sum(s >= t5 for s in fake) / len(fake) if fake else None
        c20 = sum(s >= t20 for s in fake) / len(fake) if fake else None
        lines.append(f"| {cell} | {len(real)} | {len(fake)} | {ft(t20)} | {ft(t5)} | {ft(t1)} | {f(c5)} | {f(c20)} | "
                     f"{f(auc(real, fake))} | {srcs(d['real'])} | {srcs(d['fake'])} |")
        groups: dict[str, list[float]] = defaultdict(list)
        for x in d["fake"]:
            groups[x["source"].split(":")[0] + ":" + (x["source"].split(":")[1] if x["source"].startswith("indicsynth") else "")] .append(x["median"])
        for g, ss in sorted(groups.items()):
            per_source.append(f"| {cell} | {g.rstrip(':')} | {len(ss)} | {sum(s >= t5 for s in ss)} of {len(ss)} |")
    if per_source:
        lines += ["", "## Fakes caught at the 5% false-alarm threshold, by source", "",
                  "| Cell | Fake source | Clips | Caught |", "|---|---|---|---|"] + per_source
    why = Counter(r["why_not"] for r in runs if not r["usable"])
    lines += ["", "## Clips not used for thresholds", ""] + ([f"- {k}: {v}" for k, v in why.most_common()] or ["- none"])
    secs = [r["seconds"] for r in runs if r["seconds"]]
    if secs:
        lines += ["", f"Scoring time per clip on this machine: median {np.median(secs):.1f} s, max {max(secs):.1f} s."]
    lines += ["", "With few real clips these thresholds are coarse; the counts above say how much to trust them.",
              "In-the-Wild is English celebrity speech; IndicSynth is lab-made Hindi; no public Indian scam-call audio exists."]
    cal.save(out)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {out}, {runs_path}, {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
