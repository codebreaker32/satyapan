"""Live end-to-end check against the running demo (scripts/demo_up.sh): drives the engine's API the way the console does.

  .venv/bin/python scripts/e2e_demo_check.py clips/unidata/deepfake/2.mp4 --text "This is ED. You are under digital arrest..."
  .venv/bin/python scripts/e2e_demo_check.py clips/unidata/video/1.mp4            # Whisper transcribes the sound track

Prints the verdict, the explanation and every media-forensics line, with timings. Standard library only.
"""
import argparse
import json
import mimetypes
import sys
import time
import urllib.request
import uuid
from pathlib import Path


def call(base: str, method: str, route: str, body=None, files=None, timeout=600):
    headers, data = {}, None
    if files is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in (body or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        for name, path in files.items():
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{path.name}\"\r\n"
                         f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + route, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", type=Path)
    ap.add_argument("--text", help="what the message says (skips speech-to-text)")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--amount", type=float, default=3800000)
    ap.add_argument("--language", default="hi", choices=["hi", "en"], help="how OCR / speech-to-text reads the file")
    a = ap.parse_args()
    b = a.server.rstrip("/")
    meta = call(b, "GET", "/api/meta")
    svc = (meta.get("forensics") or {}).get("service")
    print("forensics service:", "connected" if svc else "NOT connected", json.dumps((svc or {}).get("health"))[:200])
    case = call(b, "POST", "/api/cases", {"flag": {"reason": "e2e demo check: large transfer to a first-time payee",
                                                   "amount_inr": a.amount, "customer_ref": "cust-demo"}})
    cid = case["case"]["id"]
    call(b, "POST", f"/api/cases/{cid}/consent", {"check": True, "report": False, "memory": False, "lang": "hi"})
    t0 = time.perf_counter()
    form = {"language": a.language} | ({"derived_text": a.text} if a.text else {})
    call(b, "POST", f"/api/cases/{cid}/media", form, files={"file": a.media})
    t1 = time.perf_counter()
    out = call(b, "POST", f"/api/cases/{cid}/run")
    t2 = time.perf_counter()
    c = out.get("case", out)
    v = c.get("verdict") or {}
    print(f"\nupload + read: {t1 - t0:.1f} s   run (incl. forensics): {t2 - t1:.1f} s")
    print("verdict:", v.get("outcome"), "|", v.get("headline_en"))
    print("explanation:", v.get("explanation"))
    for m in c.get("media", []):
        print("media:", m.get("filename"), m.get("kind"), "| read by:", m.get("derived_text_engine"), "| text:", (m.get("derived_text") or "")[:120])
    for s in v.get("signals", []):
        if s.get("family") == "F3":
            d = s.get("detail") or {}
            print(f"F3 {s.get('rule_id')}: {s.get('severity')} | {s.get('reason_en')} | model={d.get('model')} cell={d.get('cell')} score={d.get('score')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
