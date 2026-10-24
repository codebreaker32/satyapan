"""A small local HTTP service that keeps the detectors loaded, so each case does not reload 3 GB of model.

  .venv/bin/python -m forensics.service              # http://127.0.0.1:8765

  GET  /health   -> {"ok": true, "video": {...}, "audio": {...}}   model names, calibrated cells, whether the voice
                    model actually loaded ("loaded", and "error" when it did not)
  POST /analyse  {"path": "/abs/path/to/file", "language": "hi"|"en", "channel": "live-replay", "kind": "audio"|"video"}
                 -> {"results": [ForensicResult as dict, ...], "seconds": 12.3}   (only "path" is required)

Binds to 127.0.0.1 only: the engine runs on the same laptop. One analysis at a time (CPU-bound). Paths must be
absolute and exist; the service never fetches URLs. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .analyse import analyse
from .common import Calibration
from .video import MODEL_NAME, GenDVideoForensics

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 64 * 1024


class Service:
    audio_error: Optional[str] = None                    # why the voice model did not load at warm-up, if it did not

    def __init__(self, calibration_path: Path = ROOT / "calibration" / "video.json", warm: bool = True):
        cal = Calibration.load(calibration_path) if calibration_path.exists() else None
        self.video = GenDVideoForensics(calibration=cal)
        self.audio = self._audio_detector()
        self.lock = threading.Lock()
        if warm:                                         # load models now, not on the first case
            _ = self.video.detector, self.video.scorer
            self.warm_audio()

    def warm_audio(self) -> None:
        """Load the voice model now (otherwise about a minute on the first voice note), and remember why it failed."""
        if self.audio is None or not hasattr(type(self.audio), "scorer"):
            return
        try:
            _ = self.audio.scorer
            self.audio_error = None
        except Exception as e:  # noqa: BLE001 - a missing voice model must not stop the face check
            self.audio_error = f"{type(e).__name__}: {e}"[:300]
            print(f"[forensics] voice model not loaded ({self.audio_error}); the voice check will abstain", flush=True)

    @staticmethod
    def _audio_detector():
        try:
            from .audio import default_detector          # Bhawna's module, once it is ready
            return default_detector()
        except ImportError:
            return None

    def audio_loaded(self) -> bool:
        """True once the voice model is in memory. A detector whose model loads lazily (`scorer`) counts only after
        that load succeeded, so /health never calls a detector "installed" whose weights are missing from the cache."""
        a = self.audio
        if a is None:
            return False
        if not hasattr(type(a), "scorer"):
            return True
        return getattr(a, "_scorer", None) is not None

    def health(self) -> dict:
        cells = sorted(self.video.calibration.cells)
        loaded = self.audio_loaded()
        return {"ok": True,
                "video": {"model": MODEL_NAME, "calibrated_cells": cells},
                "audio": {"installed": self.audio is not None, "loaded": loaded,
                          "model": getattr(self.audio, "model_name", None) if self.audio else None,
                          "error": None if loaded else self.audio_error}}

    def run(self, path: str, language: str = "hi", channel: Optional[str] = None, kind: Optional[str] = None) -> dict:
        p = Path(path)
        if not p.is_absolute():
            raise ValueError("path must be absolute")
        if language not in ("hi", "en"):
            raise ValueError("language must be 'hi' or 'en'")
        if channel not in (None, "live-replay"):
            raise ValueError("channel may only be 'live-replay'")
        if kind not in (None, "audio", "video"):
            raise ValueError("kind must be 'audio' or 'video'")
        t = time.perf_counter()
        with self.lock:
            results = analyse(p, video=self.video, audio=self.audio, language=language, channel=channel, kind=kind)
        return {"results": [r.to_dict() for r in results], "seconds": round(time.perf_counter() - t, 2)}


def make_handler(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._send(200, svc.health())
            self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/analyse":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._send(400, {"error": "body must be a small JSON object"})
            try:
                body = json.loads(self.rfile.read(n))
                return self._send(200, svc.run(body["path"], body.get("language") or "hi", body.get("channel"),
                                               body.get("kind")))
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {"error": str(e) or type(e).__name__})
            except Exception as e:  # noqa: BLE001 - answer with an error rather than dropping the connection
                return self._send(500, {"error": type(e).__name__})

        def log_message(self, fmt, *args):            # quiet: one line per request
            print(f"[forensics] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}", flush=True)

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    svc = Service()
    print(f"[forensics] ready on http://127.0.0.1:{a.port}  {json.dumps(svc.health())}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(svc)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
