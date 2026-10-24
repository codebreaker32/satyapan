"""Re-encode videos the way a WhatsApp forward roughly looks: H.264, short side at most 480 px, low bitrate.

This is an approximation for calibration, labelled as such. Real forwards (sent between our own phones) are still
the reference; this only lets us build a compressed calibration cell without forwarding dozens of clips by hand.
Uses the ffmpeg bundled with the `imageio-ffmpeg` package (BSD-2).

  .venv/bin/python scripts/whatsappify.py clips/dfdc/manifest.csv      # writes clips/dfdc_wa/ + manifest.csv
"""
import argparse
import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def reencode(src: Path, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    vf = "scale='if(lt(iw,ih),min(480,iw),-2)':'if(lt(iw,ih),-2,min(480,ih))'"      # short side <= 480, keep aspect
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "30", "-maxrate", "900k", "-bufsize", "1800k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
           "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    src_dir = a.manifest.parent
    out_dir = src_dir.parent / (src_dir.name + "_wa")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(a.manifest.open()))
    # Keep sub-folders in the name (video/1.mp4 -> video__1.mp4) so a real and a fake with the same file name never collide.
    out_name = lambda r: str(Path(r["path"]).with_suffix("")).replace("/", "__") + ".mp4"
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(lambda r: reencode(src_dir / r["path"], out_dir / out_name(r)), rows))
    with (out_dir / "manifest.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "label", "source"])
        for r in rows:
            w.writerow([out_name(r), r["label"], (r.get("source") or "") + "+whatsapp-like"])
    print(f"re-encoded {len(rows)} videos into {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
