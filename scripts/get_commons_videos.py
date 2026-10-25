"""Download genuine, openly licensed videos of people speaking from Wikimedia Commons, for setting thresholds.

Thresholds are set on REAL videos only (forensics/common.py), so genuine face video with a clear licence is required.
Safeguards:
  - licence must be CC BY, CC BY-SA, CC0 or public domain (read from each file's Commons metadata);
  - uploaded before 2021, so it is very unlikely to be AI-generated;
  - titles mentioning deepfakes, AI, synthetic media, animation or cartoons are skipped;
  - 2 to 150 MB, at least 240 px tall.
Every file's title, author, licence and page link go to calibration/sources_commons.csv for attribution.

  .venv/bin/python scripts/get_commons_videos.py --max 90

Writes clips/commons/*.mp4 (converted with the bundled ffmpeg if OpenCV cannot read the original) and
clips/commons/manifest.csv. The clips are never committed.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "clips" / "commons"
SOURCES = ROOT / "calibration" / "sources_commons.csv"
UA = {"User-Agent": "Satyapan-calibration/0.1 (https://github.com/codebreaker32/satyapan)"}
QUERIES = ["filetype:video interview", "filetype:video hindi interview", "filetype:video speech india",
           "filetype:video vlog", "filetype:video interview india", "filetype:video talk wikimedia",
           "filetype:video lecture speaker", "filetype:video oral history"]
OPEN = ("CC BY", "CC-BY", "CC0", "Public domain", "PD")
SKIP = re.compile(r"deep ?fake|\bAI\b|artificial intelligence|synthetic|animation|animated|cartoon|avatar|cgi", re.I)


def api(params: dict) -> dict:
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    req = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=60))


def plain(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def candidates(per_query: int) -> list[dict]:
    seen, out = set(), []
    for s in QUERIES:
        r = api({"action": "query", "generator": "search", "gsrsearch": s, "gsrnamespace": 6, "gsrlimit": per_query,
                 "prop": "imageinfo", "iiprop": "size|mime|extmetadata|url|timestamp"})
        for p in r.get("query", {}).get("pages", []):
            t = p["title"]
            if t in seen:
                continue
            seen.add(t)
            ii = (p.get("imageinfo") or [{}])[0]
            em = ii.get("extmetadata", {})
            lic = plain(em.get("LicenseShortName", {}).get("value", ""))
            item = {"title": t, "url": ii.get("url", ""), "page": ii.get("descriptionurl", ""), "licence": lic,
                    "author": plain(em.get("Artist", {}).get("value", ""))[:200], "uploaded": ii.get("timestamp", ""),
                    "size": ii.get("size", 0), "height": ii.get("height") or 0, "mime": ii.get("mime", "")}
            if not lic.startswith(OPEN) or "NC" in lic or "ND" in lic:
                continue
            if not item["uploaded"] or item["uploaded"] >= "2021-01-01":
                continue
            if SKIP.search(t) or not (2e6 <= item["size"] <= 150e6) or item["height"] < 240:
                continue
            out.append(item)
        time.sleep(0.5)
    return out


def readable(path: Path) -> bool:
    cap = cv2.VideoCapture(str(path))
    ok = cap.isOpened() and cap.read()[0]
    cap.release()
    return bool(ok)


def fetch(item: dict, idx: int) -> Path | None:
    stem = f"c{idx:03d}"
    mp4 = OUT / f"{stem}.mp4"
    if mp4.exists() and mp4.stat().st_size > 0:
        return mp4
    raw = OUT / f"{stem}.src"
    req = urllib.request.Request(item["url"], headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(raw, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    # Always convert to H.264 mp4 at the source resolution, near-lossless (crf 16), so OpenCV reads it reliably.
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(raw), "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-t", "60", str(mp4)],
                   check=False)
    raw.unlink(missing_ok=True)
    return mp4 if mp4.exists() and readable(mp4) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--per-query", type=int, default=50)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCES.parent.mkdir(parents=True, exist_ok=True)
    items = candidates(a.per_query)
    print(f"{len(items)} candidates pass the licence/date/size filters; downloading up to {a.max}")
    kept = []
    for i, it in enumerate(items[:a.max], 1):
        try:
            p = fetch(it, i)
        except Exception as e:                       # one bad file must not stop the run
            print(f"  [{i}] skip {it['title'][:60]}: {type(e).__name__}")
            continue
        if p is None:
            print(f"  [{i}] skip {it['title'][:60]}: unreadable after conversion")
            continue
        kept.append((p.name, it))
        print(f"  [{i}] ok {p.name} <- {it['title'][:60]} ({it['licence']})")
        time.sleep(0.3)
    with (OUT / "manifest.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "label", "source"])
        for name, _ in kept:
            w.writerow([name, "real", "wikimedia-commons"])
    with SOURCES.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clip", "title", "author", "licence", "uploaded", "page"])
        for name, it in kept:
            w.writerow([name, it["title"], it["author"], it["licence"], it["uploaded"], it["page"]])
    print(f"kept {len(kept)} videos; manifest {OUT / 'manifest.csv'}; attribution {SOURCES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
