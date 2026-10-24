"""A small local HTTP service that keeps the detectors loaded, so each case does not reload 3 GB of model.

  .venv/bin/python -m forensics.service              # http://127.0.0.1:8765

  GET  /health   -> {"ok": true, "video": {...}, "audio": {...}}   model names and calibrated cells
  POST /analyse  {"path": "/abs/path/to/file"}  -> {"results": [ForensicResult as dict, ...], "seconds": 12.3}

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

from .analyse import analyse
from .common import Calibration
from .video import MODEL_NAME, GenDVideoForensics

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 64 * 1024


class Service:
    def __init__(self, calibration_path: Path = ROOT / "calibration" / "video.json", warm: bool = True):
        cal = Calibration.load(calibration_path) if calibration_path.exists() else None
        self.video = GenDVideoForensics(calibration=cal)
        self.audio = self._audio_detector()
        self.lock = threading.Lock()
        if warm:                                         # load models now, not on the first case
            _ = self.video.detector, self.video.scorer
            if self.audio is not None and hasattr(type(self.audio), "scorer"):
                try:                                     # the voice model too (otherwise ~1 min on the first voice note)
                    _ = self.audio.scorer
                except Exception as e:  # noqa: BLE001 - a missing voice model must not stop the face check
                    print(f"[forensics] voice model not loaded ({type(e).__name__}); the voice check will abstain")

    @staticmethod
    def _audio_detector():
        try:
            from .audio import default_detector          # Bhawna's module, once it is ready
            return default_detector()
        except ImportError:
            return None

    def health(self) -> dict:
        cells = sorted(self.video.calibration.cells)
        return {"ok": True,
                "video": {"model": MODEL_NAME, "calibrated_cells": cells},
                "audio": {"installed": self.audio is not None,
                          "model": getattr(self.audio, "model_name", None) if self.audio else None}}

    def run(self, path: str) -> dict:
        p = Path(path)
        if not p.is_absolute():
            raise ValueError("path must be absolute")
        t = time.perf_counter()
        with self.lock:
            results = analyse(p, video=self.video, audio=self.audio)
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
                path = json.loads(self.rfile.read(n))["path"]
                return self._send(200, svc.run(path))
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {"error": str(e) or type(e).__name__})
            except Exception as e:  # noqa: BLE001 - answer with an error rather than dropping the connection
                return self._send(500, {"error": type(e).__name__})

        def log_message(self, fmt, *args):            # quiet: one line per request
            print(f"[forensics] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    svc = Service()
    print(f"[forensics] ready on http://127.0.0.1:{a.port}  {json.dumps(svc.health())}")
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(svc)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
