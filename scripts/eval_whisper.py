"""Compare Whisper models for Hindi voice notes: word error rate and speed on real Hindi speech (FLEURS).

Google FLEURS (CC-BY-4.0) ships read Hindi speech with reference transcripts. The script takes N clips, transcribes each
with every candidate model on this laptop's CPU, and reports word error rate (WER, lower is better) and seconds per
clip. Optionally re-encodes the clips the way WhatsApp sends voice notes (Opus, 16 kHz, mono) to see the effect.

  .venv/bin/python scripts/eval_whisper.py --n 20

Writes calibration/whisper_eval.md (numbers only, no audio).
"""
import argparse
import io
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

import imageio_ffmpeg
import pyarrow.parquet as pq
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "clips" / "audio" / "fleurs" / "parquet-data" / "hi_in" / "validation-00000-of-00001.parquet"
MODELS = ["small", "large-v3-turbo"]


def norm(s: str) -> list[str]:
    s = unicodedata.normalize("NFC", s or "").lower()
    s = re.sub(r"[।॥.,!?;:\"'()\[\]{}\-–—…]", " ", s)
    return s.split()


def wer(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    """(edit distance in words, reference length)."""
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev, d[j] = d[j], cur
    return d[len(hyp)], len(ref)


def to_opus_wav(src: Path, dst: Path) -> Path:
    """WhatsApp-like voice note: Opus 16 kHz mono ~16 kbps, decoded back to WAV for the model."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    opus = dst.with_suffix(".ogg")
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "16k", str(opus)], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(opus), "-ac", "1", "-ar", "16000", str(dst)], check=True)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--opus", action="store_true", help="also test WhatsApp-like Opus copies")
    ap.add_argument("--beam", type=int, default=5, help="beam size (1 = greedy, faster)")
    ap.add_argument("--threads", type=int, default=0, help="CPU threads for Whisper (0 = its default)")
    ap.add_argument("--out", type=Path, default=ROOT / "calibration" / "whisper_eval.md")
    a = ap.parse_args()
    from faster_whisper import WhisperModel

    t = pq.read_table(PARQUET)
    cols = t.column_names
    text_col = next(c for c in ("raw_transcription", "transcription", "text", "sentence") if c in cols)
    audio_col = next(c for c in cols if "audio" in c.lower())
    rows = t.slice(0, a.n).to_pylist()
    tmp = Path(tempfile.mkdtemp())
    clips = []
    for i, r in enumerate(rows):
        au = r[audio_col]
        data = au.get("bytes") if isinstance(au, dict) else au
        wav, sr = sf.read(io.BytesIO(data))
        p = tmp / f"k{i:03d}.wav"
        sf.write(p, wav, sr)
        clips.append((p, r[text_col], len(wav) / sr))
    variants = [("original", clips)]
    if a.opus:
        variants.append(("whatsapp-like opus 16 kbps", [(to_opus_wav(p, p.with_name(p.stem + "_opus.wav")), ref, d) for p, ref, d in clips]))

    lines = ["# Whisper on Hindi voice notes: accuracy and speed", "",
             f"{len(clips)} FLEURS Hindi clips (read speech, google/fleurs, CC-BY-4.0), average {sum(c[2] for c in clips)/len(clips):.1f} s each. "
             f"CPU only (this laptop), int8, beam {a.beam}, threads {a.threads or 'default'}. WER = word error rate against FLEURS's reference text (lower is better).", "",
             "| Model | Audio | WER | Seconds per clip | Real-time factor |", "|---|---|---|---|---|"]
    for name in a.models:
        t0 = time.perf_counter()
        model = WhisperModel(name, device="cpu", compute_type="int8", local_files_only=True, cpu_threads=a.threads)
        load = time.perf_counter() - t0
        for vname, vclips in variants:
            errs = refs = 0
            secs = audio = 0.0
            for p, ref, dur in vclips:
                t1 = time.perf_counter()
                segs, _ = model.transcribe(str(p), language="hi", beam_size=a.beam)
                hyp = " ".join(s.text.strip() for s in segs)
                secs += time.perf_counter() - t1
                audio += dur
                e, n = wer(norm(ref), norm(hyp))
                errs, refs = errs + e, refs + n
            row = f"| {name} | {vname} | {errs / refs:.1%} | {secs / len(vclips):.1f} | {secs / audio:.2f} |"
            lines.append(row)
            print(row, f"(load {load:.1f} s)", flush=True)
    lines += ["", "Real-time factor below 1 means faster than the audio plays. Example output for one clip is not stored."]
    out = a.out
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
