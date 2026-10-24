"""Labelled Hindi audio for calibrating the audio detector (for Bhawna; same manifest format as the video side).

Real speech: Kathbath (ai4bharat, CC-BY-4.0), read Hindi speech.
Synthetic speech: IndicSynth (vdivyasharma, CC-BY-NC-4.0), Hindi text-to-speech / voice-cloned speech.
For each clip it also makes a WhatsApp-like voice note (Opus, 16 kHz mono, 16 kbps), so the "hi/whatsapp-opus" cell can
be calibrated as well as "hi/wav".

  .venv/bin/python scripts/prepare_audio_clips.py --n 60

Writes clips/audio/{real,fake}/*.wav, clips/audio/{real,fake}_opus/*.ogg and clips/audio/manifest.csv
(path,label,source,cell). Nothing here is committed.
"""
import argparse
import csv
import io
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import pyarrow.parquet as pq
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / "clips" / "audio"
SOURCES = {
    "real": (A / "kathbath" / "hindi" / "valid-00000-of-00002.parquet", "kathbath-hi"),
    "fake": (A / "indicsynth" / "Hindi" / "train-00000-of-00107.parquet", "indicsynth-hi"),
}
FF = imageio_ffmpeg.get_ffmpeg_exe()


def audio_bytes(cell) -> bytes:
    if isinstance(cell, dict):
        return cell.get("bytes") or open(cell["path"], "rb").read()
    return cell


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=60, help="clips per label")
    a = ap.parse_args()
    rows = []
    for label, (parquet, source) in SOURCES.items():
        if not parquet.exists():
            print(f"missing {parquet}; skipping {label}")
            continue
        pf = pq.ParquetFile(parquet)
        audio_col = next(c for c in pf.schema_arrow.names if "audio" in c.lower())
        wav_dir, opus_dir = A / label, A / f"{label}_opus"
        wav_dir.mkdir(parents=True, exist_ok=True)
        opus_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for batch in pf.iter_batches(batch_size=32, columns=[audio_col]):
            for cell in batch.column(0).to_pylist():
                if n >= a.n:
                    break
                try:
                    data, sr = sf.read(io.BytesIO(audio_bytes(cell)))
                except Exception:  # noqa: BLE001 - skip an undecodable row
                    continue
                if len(data) / sr < 3:                    # the detector abstains under 3 s anyway
                    continue
                wav = wav_dir / f"{label}_{n:03d}.wav"
                sf.write(wav, data, sr)
                opus = opus_dir / f"{label}_{n:03d}.ogg"
                subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-ar", "16000", "-c:a", "libopus",
                                "-b:a", "16k", str(opus)], check=True)
                rows.append((wav, label, source, "hi/wav"))
                rows.append((opus, label, source + "+whatsapp-like", "hi/whatsapp-opus"))
                n += 1
            if n >= a.n:
                break
        print(f"{label}: {n} clips from {parquet.name}")
    with (A / "manifest.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "label", "source", "cell"])
        for p, label, source, cell in rows:
            w.writerow([str(p.resolve()), label, source, cell])
    print(f"wrote {A / 'manifest.csv'} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
