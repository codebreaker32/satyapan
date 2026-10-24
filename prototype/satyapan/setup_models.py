"""`satyapan setup-models`: fetch every model and language file the engine can use, once, so the finale needs no Wi-Fi.

Nothing in the engine downloads anything while a case is being checked. A model that is not on disk is a missing
install, reported as one (the console then asks for a transcript, or the detector abstains). This command is the
one place that touches the network, and every step is idempotent: a file already present is left alone.

What it fetches, and from where (all recorded in docs/disclosure.md with their licences):
- Whisper "small" for speech-to-text (faster-whisper / CTranslate2 conversion, MIT), into vendor/models/whisper
- AASIST-L code, config and weights for audio anti-spoofing (clovaai/aasist, MIT), into vendor/aasist
- Tesseract language data for English and Hindi (tessdata_fast, Apache-2.0), into vendor/tessdata
- paraphrase-multilingual-MiniLM-L12-v2 for meaning-level campaign memory (Apache-2.0, ONNX via fastembed),
  into vendor/models/fastembed
The Tesseract program itself is a system install (winget install UB-Mannheim.TesseractOCR on Windows).
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

from .forensics import AASIST_DIR
from .media import TESSDATA, VENDOR, tesseract_cmd, whisper_model

AASIST_RAW = "https://raw.githubusercontent.com/clovaai/aasist/main"
AASIST_FILES = ("models/AASIST.py", "config/AASIST-L.conf", "models/weights/AASIST-L.pth", "LICENSE")
TESSDATA_RAW = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main"
TESSDATA_FILES = ("eng.traineddata", "hin.traineddata", "osd.traineddata", "LICENSE")
MEANING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FASTEMBED_DIR = VENDOR / "models" / "fastembed"


def _fetch(url: str, dest: Path) -> str:
    if dest.exists() and dest.stat().st_size > 0:
        return f"present  {dest.relative_to(VENDOR.parent)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    return f"fetched  {dest.relative_to(VENDOR.parent)} ({dest.stat().st_size:,} bytes)"


def setup_models(log=print) -> int:
    failures = 0

    def step(name: str, fn) -> None:
        nonlocal failures
        try:
            for line in fn() or []:
                log(f"  {line}")
            log(f"ok    {name}")
        except Exception as e:  # noqa: BLE001 - report every step, keep going, fail at the end
            failures += 1
            log(f"FAIL  {name}: {type(e).__name__}: {e}")

    step("AASIST-L (audio anti-spoofing)", lambda: [_fetch(f"{AASIST_RAW}/{p}", AASIST_DIR / p) for p in AASIST_FILES])
    step("Tesseract language data (eng, hin)", lambda: [_fetch(f"{TESSDATA_RAW}/{p}", TESSDATA / p) for p in TESSDATA_FILES])
    def tesseract():
        cmd = tesseract_cmd()
        if not cmd:
            raise RuntimeError("not installed: winget install -e --id UB-Mannheim.TesseractOCR")
        return [f"found {cmd}"]
    step("Tesseract program", tesseract)

    def whisper():
        _, name = whisper_model(download=True)
        return [f"Whisper '{name}' ready under {Path('vendor/models/whisper')}"]
    step("Whisper speech-to-text", whisper)

    def meaning():
        from fastembed import TextEmbedding
        model = TextEmbedding(MEANING_MODEL, cache_dir=str(FASTEMBED_DIR))
        vec = next(iter(model.embed(["जाँच के लिए पूरी राशि इस खाते में भेजें"])))
        return [f"{MEANING_MODEL} ready ({len(vec)} dimensions)"]
    step("meaning model for campaign memory", meaning)

    log("\nall models ready" if not failures else f"\n{failures} step(s) failed")
    return 1 if failures else 0
