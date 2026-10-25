"""Download the public audio clips the voice detector is calibrated and measured on, and write a manifest.

  .venv/bin/python scripts/fetch_audio_clips.py               # everything below
  .venv/bin/python scripts/fetch_audio_clips.py --only itw    # one source

Everything lands in clips/audio/ (never committed; see .gitignore) and is listed in clips/audio_manifest.csv with
columns path,label,language,source,channel. Only the calibration numbers and the file lists are ever committed.

Sources (README.md, "Public datasets used to calibrate the detectors"):
  itw         mueller91/In-The-Wild: real and fake speech of public figures that actually circulated online (English).
              The 8.2 GB zip is read with HTTP range requests, so only the sampled clips are downloaded.
  gramvaani   OpenSLR 118 (Gram Vaani): real, spontaneous Hindi phone speech (dev + eval, 160 MB). Academic use.
  indicsynth  vdivyasharma/IndicSynth: lab-made Hindi voice clones and TTS (freevc24, xtts_v2, vits), CC-BY-NC-4.0.
              Fetched clip by clip through the Hugging Face datasets server, spread evenly over the dataset.
  fleurs      google/fleurs hi_in dev: real, read Hindi speech (CC-BY-4.0), clean recordings.

Nothing here is trained on. DF Arena did not train on any of these sets (its card lists ASVspoof 2019/2024, Codecfake,
LibriSeVoc, DFADD, CtrSVDD, SpoofCeleb, MLAAD and EnvSDD), so they are fair tests for it.
"""
import argparse
import csv
import io
import json
import random
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "clips" / "audio"
MANIFEST = ROOT / "clips" / "audio_manifest.csv"

ITW_URL = ("https://huggingface.co/datasets/mueller91/In-The-Wild/resolve/"
           "eee168f92c367f8c82ff2cf42b6f61e362fd6211/release_in_the_wild.zip")
GV_URLS = ["https://openslr.trmal.net/resources/118/GV_Dev_5h.tar.gz",
           "https://openslr.trmal.net/resources/118/GV_Eval_3h.tar.gz"]
INDICSYNTH_ROWS = "https://datasets-server.huggingface.co/rows?dataset=vdivyasharma/IndicSynth&config=Hindi&split=train"
INDICSYNTH_TOTAL = 205_938
FLEURS_URL = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/hi_in/audio/dev.tar.gz"
UA = {"User-Agent": "satyapan-calibration/1.0"}


class HttpRangeFile(io.RawIOBase):
    """A read-only, seekable view of a remote file through HTTP Range requests, enough for zipfile."""

    def __init__(self, url: str):
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.url = r.geturl()                        # the signed CDN URL after redirects
            self.size = int(r.headers["Content-Range"].split("/")[-1])
        self.pos = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = {io.SEEK_SET: offset, io.SEEK_CUR: self.pos + offset, io.SEEK_END: self.size + offset}[whence]
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        req = urllib.request.Request(self.url, headers={**UA, "Range": f"bytes={self.pos}-{end}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def fetch_itw(per_label: int, seed: int) -> list[dict]:
    out_dir = CLIPS / "itw"
    out_dir.mkdir(parents=True, exist_ok=True)
    zf = zipfile.ZipFile(HttpRangeFile(ITW_URL))
    meta_name = next(n for n in zf.namelist() if n.endswith("meta.csv"))
    meta = list(csv.DictReader(io.TextIOWrapper(zf.open(meta_name), encoding="utf-8")))
    prefix = meta_name.rsplit("/", 1)[0] + "/" if "/" in meta_name else ""
    rng = random.Random(seed)
    rows = []
    for label, wanted in (("bona-fide", "real"), ("spoof", "fake")):
        pool = [m for m in meta if m["label"] == label]
        rng.shuffle(pool)
        # spread over speakers: round-robin so no single public figure dominates the sample
        by_spk: dict[str, list[dict]] = {}
        for m in pool:
            by_spk.setdefault(m["speaker"], []).append(m)
        picked: list[dict] = []
        while len(picked) < per_label and any(by_spk.values()):
            for spk in sorted(by_spk):
                if by_spk[spk] and len(picked) < per_label:
                    picked.append(by_spk[spk].pop())
        for m in picked:
            dest = out_dir / m["file"]
            if not dest.exists():
                dest.write_bytes(zf.read(prefix + m["file"]))
            rows.append({"path": str(dest.relative_to(ROOT / "clips")), "label": wanted, "language": "en",
                         "source": f"itw:{m['speaker']}", "channel": ""})
        print(f"itw: {len(picked)} {wanted} clips from {len({m['speaker'] for m in picked})} speakers")
    return rows


def fetch_gramvaani() -> list[dict]:
    out_dir = CLIPS / "gramvaani"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for url in GV_URLS:
        name = url.rsplit("/", 1)[-1]
        tar_path = out_dir / name
        if not tar_path.exists():
            urllib.request.urlretrieve(url, tar_path)
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not (member.isfile() and member.name.lower().endswith((".mp3", ".wav"))):
                    continue
                dest = out_dir / Path(member.name).name
                if not dest.exists():
                    dest.write_bytes(tar.extractfile(member).read())
                rows.append({"path": str(dest.relative_to(ROOT / "clips")), "label": "real", "language": "hi",
                             "source": f"gramvaani:{name.split('_')[1].lower()}", "channel": "phone-8k"})  # real calls
        print(f"gramvaani: {name} -> {sum(r['source'].endswith(name.split('_')[1].lower()) for r in rows)} clips")
    return rows


def fetch_indicsynth(n: int) -> list[dict]:
    out_dir = CLIPS / "indicsynth"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    step = INDICSYNTH_TOTAL // n
    for k in range(n):
        offset = k * step + step // 2
        dest = out_dir / f"indicsynth_hi_{offset:06d}.wav"
        meta_path = dest.with_suffix(".json")
        if not (dest.exists() and meta_path.exists()):
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(urllib.request.Request(f"{INDICSYNTH_ROWS}&offset={offset}&length=1",
                                                                       headers=UA), timeout=60) as r:
                        row = json.load(r)["rows"][0]["row"]
                    audio = row["audio"][0] if isinstance(row["audio"], list) else row["audio"]
                    meta_path.write_text(json.dumps({k2: v for k2, v in row.items() if k2 != "audio"}, ensure_ascii=False),
                                         encoding="utf-8")
                    urllib.request.urlretrieve(audio["src"], dest)
                    break
                except OSError:
                    time.sleep(3 * (attempt + 1))
            time.sleep(0.5)                               # rate-limit requests to the datasets server
        gen = json.loads(meta_path.read_text(encoding="utf-8")).get("Generative Model", "") if meta_path.exists() else ""
        if dest.exists():
            rows.append({"path": str(dest.relative_to(ROOT / "clips")), "label": "fake", "language": "hi",
                         "source": f"indicsynth:{gen}", "channel": ""})
    print(f"indicsynth: {len(rows)} Hindi lab fakes")
    return rows


def fetch_fleurs(n: int, local_tar: Optional[Path]) -> list[dict]:
    """Real, read Hindi speech from google/fleurs (CC-BY-4.0), dev split. DF Arena did not train on FLEURS."""
    out_dir = CLIPS / "fleurs"
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = local_tar if local_tar and local_tar.exists() else out_dir / "hi_in_dev.tar.gz"
    if not tar_path.exists():
        urllib.request.urlretrieve(FLEURS_URL, tar_path)
    rows = []
    with tarfile.open(tar_path, "r:gz") as tar:
        members = sorted((m for m in tar.getmembers() if m.isfile() and m.name.endswith(".wav")), key=lambda m: m.name)
        for m in members[:n]:
            dest = out_dir / Path(m.name).name
            if not dest.exists():
                dest.write_bytes(tar.extractfile(m).read())
            rows.append({"path": str(dest.relative_to(ROOT / "clips")), "label": "real", "language": "hi",
                         "source": "fleurs:hi_in", "channel": ""})
    print(f"fleurs: {len(rows)} real Hindi clips")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["itw", "gramvaani", "indicsynth", "fleurs"])
    ap.add_argument("--itw-per-label", type=int, default=150)
    ap.add_argument("--indicsynth", type=int, default=60)
    ap.add_argument("--fleurs", type=int, default=120)
    ap.add_argument("--fleurs-tar", type=Path, help="a local copy of google/fleurs data/hi_in/audio/dev.tar.gz")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rows: list[dict] = []
    if a.only in (None, "itw"):
        rows += fetch_itw(a.itw_per_label, a.seed)
    if a.only in (None, "gramvaani"):
        rows += fetch_gramvaani()
    if a.only in (None, "indicsynth"):
        rows += fetch_indicsynth(a.indicsynth)
    if a.only in (None, "fleurs"):
        rows += fetch_fleurs(a.fleurs, a.fleurs_tar)
    old = []
    if MANIFEST.exists() and a.only:                     # keep the other sources' rows when fetching one source
        old = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8")) if not r["source"].startswith(a.only + ":")]
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["path", "label", "language", "source", "channel"])
        w.writeheader()
        w.writerows(old + rows)
    print(f"wrote {MANIFEST} ({len(old) + len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
