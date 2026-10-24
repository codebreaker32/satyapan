"""Calibration, measured on data rather than chosen by hand.

`calibrate_audio` sets AASIST-L's per-cell thresholds from GENUINE speech. A detector's threshold is a statement
about false alarms: "on real people speaking through this channel, the score passes t_fpr5 five times in a hundred".
So the input is genuine speech only, re-encoded the way it reaches a bank: a clean 16 kHz recording, an 8 kHz
phone-band version, and a 48 kHz Opus voice note (a WhatsApp note or a browser recording). The speech is FLEURS
(google/fleurs, CC-BY-4.0), Hindi and English, dev split. PyAV here has no AMR encoder, so the phone cell is 8 kHz
audio, not AMR-coded audio; the calibration file says so. What this does NOT measure is how often the model catches a
modern Indian-language voice clone, because no labelled set of those is available here. A small probe with the
synthetic voices Windows ships (when present) is recorded beside the thresholds, as a sanity check and nothing more.

`calibrate_memory` sets the meaning-match threshold for campaign memory from labelled pairs: reworded and
translated copies of each stored scam (positives) against every other message in the repo (negatives). The
threshold sits just above the highest negative, so no message in the repo that is not a copy can match.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path

from .forensics import AASIST_CALIBRATION, AASIST_DIR, SAMPLE_RATE, AASISTAudioForensics, decode_audio

ROOT = Path(__file__).resolve().parent.parent
FLEURS_DIR = ROOT / "data" / "forensics" / "fleurs"
EVAL_DIR = ROOT / "data" / "eval"
MEMORY_PAIRS = EVAL_DIR / "memory_pairs.json"
MEMORY_CALIBRATION = EVAL_DIR / "memory_calibration.json"
LANGS = {"hi": "hi_in", "en": "en_us"}
CHANNELS = {"clean-16k": ("wav", "pcm_s16le", 16000, None),
            "amr-8k": ("wav", "pcm_s16le", 8000, None),           # phone band; see the module docstring on AMR
            "whatsapp-opus": ("ogg", "libopus", 48000, 16000)}    # 16 kbit/s Opus, as a voice note is sent
PROBE_SENTENCES = [
    "This is the Enforcement Directorate. You are under digital arrest. Transfer the full amount to the verification account today.",
    "I am calling from the Reserve Bank of India. Invest in the new gold scheme for guaranteed returns this week.",
    "Your bank relationship manager here. Break your fixed deposit and move the money to the safe account now.",
    "Your vehicle has a pending traffic challan. Pay the fine immediately at the link in this message.",
    "Your SIM card will be blocked in two hours because of illegal activity. Press nine to speak to the officer.",
    "Do not tell anyone about this call. The amount will be refunded after verification is complete.",
]


def _encode(wav16, out: Path, fmt: str, codec: str, rate: int, bit_rate) -> None:
    """Write 16 kHz mono float audio through one channel (container, codec, sample rate, bit rate) with PyAV."""
    import av
    import numpy as np
    pcm = (np.clip(wav16, -1.0, 1.0) * 32767).astype("int16").reshape(1, -1)
    with av.open(str(out), "w", format=fmt) as c:
        s = c.add_stream(codec, rate=rate, layout="mono")
        if bit_rate:
            s.bit_rate = bit_rate
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        for packet in s.encode(frame):
            c.mux(packet)
        for packet in s.encode(None):
            c.mux(packet)


def _percentile(xs: list[float], q: float) -> float:
    import numpy as np
    return round(float(np.percentile(np.array(xs), q)), 3)


def _genuine_clips(lang: str, n: int):
    """The first `n` FLEURS dev clips for one language, in a stable order, as (name, bytes)."""
    tar_path = FLEURS_DIR / f"{LANGS[lang]}_dev.tar.gz"
    if not tar_path.exists():
        raise FileNotFoundError(f"{tar_path} is missing: download google/fleurs data/{LANGS[lang]}/audio/dev.tar.gz into it")
    with tarfile.open(tar_path, "r:gz") as tar:
        members = sorted((m for m in tar.getmembers() if m.isfile() and m.name.endswith(".wav")), key=lambda m: m.name)
        for m in members[:n]:
            yield m.name, tar.extractfile(m).read()


def _windows_voices(tmp: Path) -> list[tuple[str, Path]]:
    """Synthetic speech from the voices installed with Windows (System.Speech), one clip per voice and sentence."""
    if not sys.platform.startswith("win"):
        return []
    script = tmp / "speak.ps1"
    lines = ["Add-Type -AssemblyName System.Speech", "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
             "$i = 0", "foreach ($v in $s.GetInstalledVoices()) {", "  $s.SelectVoice($v.VoiceInfo.Name)"]
    for k, sentence in enumerate(PROBE_SENTENCES):
        out = str(tmp / f"tts-$i-{k}.wav").replace("'", "''")
        lines += [f"  $s.SetOutputToWaveFile(\"{out}\")", f"  $s.Speak('{sentence}')", "  $s.SetOutputToNull()"]
    lines += ["  Write-Output (\"$i|\" + $v.VoiceInfo.Name)", "  $i++", "}"]
    script.write_text("\n".join(lines), encoding="utf-8")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                             capture_output=True, text=True, timeout=300).stdout
    except Exception:  # noqa: BLE001 - the probe is optional
        return []
    clips = []
    for line in out.splitlines():
        if "|" in line:
            i, name = line.split("|", 1)
            clips += [(name.strip(), p) for p in sorted(tmp.glob(f"tts-{i.strip()}-*.wav"))]
    return clips


def calibrate_audio(per_language: int = 150, log=print) -> int:
    ckpt = AASIST_DIR / "models" / "weights" / "AASIST-L.pth"
    if not ckpt.exists():
        log("AASIST-L is not downloaded: run `satyapan setup-models` first")
        return 1
    det = AASISTAudioForensics(ckpt, None, AASIST_DIR)
    scores: dict[str, list[float]] = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for lang in LANGS:
            count = 0
            for name, data in _genuine_clips(lang, per_language):
                src = tmp / "src.wav"
                src.write_bytes(data)
                wav16, _, _ = decode_audio(src)
                if len(wav16) < 3 * SAMPLE_RATE:
                    continue
                for channel, (fmt, codec, rate, bit_rate) in CHANNELS.items():
                    out = tmp / f"ch.{fmt}"
                    _encode(wav16, out, fmt, codec, rate, bit_rate)
                    heard, source_rate, _ = decode_audio(out)
                    cell = det._cell(source_rate, lang)
                    scores.setdefault(cell, []).append(det.score(heard))
                count += 1
            log(f"{lang}: scored {count} genuine clips through {len(CHANNELS)} channels")
        calib: dict = {
            "_note": ("AASIST-L thresholds at 20%, 5% and 1% false-synthetic rate, measured on GENUINE speech only "
                      "(FLEURS dev, google/fleurs, CC-BY-4.0) re-encoded per channel. 'amr-8k' is 8 kHz phone-band "
                      "audio, not AMR-coded. Detection of modern Indian-language voice clones is not measured here."),
            "_made": date.today().isoformat(), "_model": "AASIST-L (clovaai/aasist, MIT)",
        }
        for cell, xs in sorted(scores.items()):
            calib[cell] = {"t_fpr20": _percentile(xs, 80), "t_fpr5": _percentile(xs, 95), "t_fpr1": _percentile(xs, 99),
                           "n": len(xs), "mean": round(sum(xs) / len(xs), 3), "max": round(max(xs), 3)}
        # The probe: synthetic voices, through the same channels, scored against the thresholds just set.
        probe = {}
        for voice, path in _windows_voices(tmp):
            wav16, _, _ = decode_audio(path)
            for channel, (fmt, codec, rate, bit_rate) in CHANNELS.items():
                out = tmp / f"probe.{fmt}"
                _encode(wav16, out, fmt, codec, rate, bit_rate)
                heard, source_rate, _ = decode_audio(out)
                cell = det._cell(source_rate, "en")
                th = calib.get(cell)
                if th:
                    p = probe.setdefault(cell, {"n": 0, "flagged_at_fpr5": 0, "voices": set()})
                    p["n"] += 1
                    p["flagged_at_fpr5"] += int(det.score(heard) >= th["t_fpr5"])
                    p["voices"].add(voice)
        if probe:
            calib["_probe_windows_tts"] = {cell: {**p, "voices": sorted(p["voices"])} for cell, p in probe.items()}
    AASIST_CALIBRATION.parent.mkdir(parents=True, exist_ok=True)
    AASIST_CALIBRATION.write_text(json.dumps(calib, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {AASIST_CALIBRATION.relative_to(ROOT)}")
    for cell in sorted(k for k in calib if not k.startswith("_")):
        th = calib[cell]
        log(f"  {cell:18s} n={th['n']:4d}  t_fpr20={th['t_fpr20']:7.3f}  t_fpr5={th['t_fpr5']:7.3f}  t_fpr1={th['t_fpr1']:7.3f}")
    for cell, p in sorted(calib.get("_probe_windows_tts", {}).items()):
        log(f"  probe {cell:12s} {p['flagged_at_fpr5']}/{p['n']} synthetic clips flagged at 5% FPR ({', '.join(p['voices'])})")
    return 0


# ---------------------------------------------------------------- campaign memory, meaning level

def _texts_for_negatives() -> list[tuple[str, str]]:
    """Every message in the repo that is not a copy of a stored scam: (source id, text).

    Left out on purpose: the scenarios that ARE the stored campaigns and the variants rewritten from them (they are
    copies of a kind, written as extractor probes, so they belong to neither side), and every labelled evaluation
    message that is a copy (`copy_of`), which `satyapan evaluate` scores and calibration must not have seen."""
    from .cli import load_scenarios
    copies_of = {"S3-ed-summons", "S5d-injection", "S2-rbi-video"}
    out = [(s["id"], s["text"]) for s in load_scenarios() if s.get("text") and s["id"] not in copies_of]
    variants = json.loads((ROOT / "data" / "fixtures" / "variants.json").read_text(encoding="utf-8"))["variants"]
    out += [(v["id"], v["text"]) for v in variants if v["from"] not in copies_of]
    labelled = EVAL_DIR / "labelled.json"
    if labelled.exists():
        out += [(i["id"], i["text"]) for i in json.loads(labelled.read_text(encoding="utf-8"))["messages"]
                if not i.get("copy_of")]
    return out


def _positives() -> list[tuple[str, str, str]]:
    """Reworded and translated copies of each stored scam, written for calibration: (id, entry id, text)."""
    pairs = json.loads(MEMORY_PAIRS.read_text(encoding="utf-8"))["copies"]
    return [(p["id"], p["entry"], p["text"]) for p in pairs]


def calibrate_memory(log=print, margin: float = 0.02) -> int:
    """Set the meaning threshold just above the highest-scoring negative that names the same body as a stored scam:
    only those can reach the meaning layer at all (`memory.same_structure`)."""
    from .extract import RulesExtractor
    from .memory import MEANING_MODEL_NAME, meaning_model, same_structure
    from .pipeline import DATA_DIR
    model = meaning_model()
    if model is None:
        log("the meaning model is not downloaded: run `satyapan setup-models` first")
        return 1
    x = RulesExtractor(bank_names=("Demo Bank",))
    entries = [e for e in json.loads((DATA_DIR / "mocks" / "campaign_memory.json").read_text(encoding="utf-8"))["entries"]
               if e.get("status") == "confirmed"]

    def best(text: str, only: str | None = None) -> float | None:
        claim = x.extract(text)
        scores = [model.cosine(model.vector(text), model.vector(e["template_text"])) for e in entries
                  if same_structure(claim, e) and (only is None or e["id"] == only)]
        return max(scores) if scores else None

    neg = [(sid, s) for sid, t in _texts_for_negatives() if (s := best(t)) is not None]
    pos = [(sid, eid, best(t, eid)) for sid, eid, t in _positives()]
    top_neg = max(neg, key=lambda p: p[1]) if neg else ("none", 0.0)
    threshold = round(max(top_neg[1] + margin, 0.5), 3)
    caught = [p for p in pos if p[2] is not None and p[2] >= threshold]
    result = {"_note": ("Cosine threshold for a meaning-level campaign-memory match. Only a message naming the same body "
                        "as a confirmed case is compared, and the threshold sits just above the highest such message in "
                        "the repo that is not a copy. Synthetic messages, not field data."),
              "_made": date.today().isoformat(), "model": MEANING_MODEL_NAME, "threshold": threshold, "margin": margin,
              "negatives_compared": len(neg), "highest_negative": {"id": top_neg[0], "score": round(top_neg[1], 3)},
              "positives": len(pos), "positives_caught": len(caught),
              "missed": sorted((sid, None if s is None else round(s, 3)) for sid, _, s in pos
                               if s is None or s < threshold)}
    MEMORY_CALIBRATION.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {MEMORY_CALIBRATION.relative_to(ROOT)}: threshold {threshold} "
        f"(highest same-body message that is not a copy: {top_neg[0]} at {top_neg[1]:.3f}); "
        f"{len(caught)}/{len(pos)} reworded or translated copies caught")
    return 0
