"""Full pipeline check against the running demo (scripts/demo_up.sh): audio and video, end to end.

Each case is uploaded through the engine's API the way the console does it (open case, consent, upload, run), so it
exercises Whisper or OCR, the instruction rules, the face check (GenD) and the voice check (DF Arena) through the
forensics service, the 50/50 combined score and the verdict. Each case states what must hold; the script prints a
table and exits 1 if any case fails.

  .venv/bin/python scripts/pipeline_check.py
  .venv/bin/python scripts/pipeline_check.py --only voice      # cases whose name contains "voice"

Clips come from clips/ (never committed): run scripts/prepare_audio_clips.py and the video calibration downloads
first. Cases whose clip is missing are skipped, not failed. This checks that the pipeline works; it is not an accuracy
measurement (some clips were also used for calibration; see calibration/*_report.md for measured rates).
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_demo_check import call  # noqa: E402  - the same multipart client the e2e check uses

ROOT = Path(__file__).resolve().parent.parent
C = ROOT / "clips"
SCAM = ("Main ED adhikari bol raha hoon. Aap digital arrest mein hain. Aaj hi 38 lakh rupaye is RBI supervision account "
        "mein transfer karein: A/c 30011223344556, IFSC DEMO0001234. Kisi ko mat batana.")
BENIGN = "Namaste, kal shaam paanch baje milte hain. Dhanyavaad."


def make_short_and_silent(tmp: Path) -> tuple[Path, Path, Path]:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    short, silent, weba = tmp / "short_1s.ogg", tmp / "silent_6s.ogg", tmp / "recording.weba"
    src = C / "audio" / "real_opus" / "real_000.ogg"
    if src.exists():
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-t", "1", "-c:a", "libopus", "-b:a", "16k", str(short)], check=True)
        # what the console's Record voice button saves: Opus in a WebM container, named .weba
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-c:a", "libopus", "-b:a", "32k", "-f", "webm", str(weba)], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "6", "-c:a", "libopus",
                    "-b:a", "16k", str(silent)], check=True)
    return short, silent, weba


def media_line(sigs: list, rule: str) -> dict:
    s = next((x for x in sigs if x.get("rule_id") == rule), None)
    if not s:
        return {"status": "-", "text": "-"}
    d = s.get("detail") or {}
    return {"status": d.get("status") or s.get("severity"), "cell": d.get("cell"), "score": d.get("score"),
            "text": s.get("reason_en", "")[:90]}


def run_case(base: str, path: Path, text, language: str, channel=None) -> dict:
    case = call(base, "POST", "/api/cases", {"flag": {"reason": "pipeline check: large transfer to a first-time payee",
                                                      "amount_inr": 3800000, "customer_ref": "cust-demo"}})
    cid = case["case"]["id"]
    call(base, "POST", f"/api/cases/{cid}/consent", {"check": True, "report": False, "memory": False, "lang": "hi"})
    t0 = time.perf_counter()
    form = {"language": language} | ({"derived_text": text} if text else {}) | ({"channel": channel} if channel else {})
    try:
        call(base, "POST", f"/api/cases/{cid}/media", form, files={"file": path})
    except urllib.error.HTTPError as e:
        return {"http": e.code, "detail": json.loads(e.read() or b"{}").get("detail", "")[:120], "secs": time.perf_counter() - t0}
    t1 = time.perf_counter()
    out = call(base, "POST", f"/api/cases/{cid}/run")
    c = out.get("case", out)
    v = c.get("verdict") or {}
    sigs = v.get("signals", [])
    m = (c.get("media") or [{}])[0]
    return {"http": 200, "verdict": v.get("outcome"), "scores": v.get("scores") or {}, "read_by": m.get("derived_text_engine"),
            "text": (m.get("derived_text") or "")[:60], "face": media_line(sigs, "R-VIDEO-SYNTH"),
            "voice": media_line(sigs, "R-AUDIO-SYNTH"), "upload_s": t1 - t0, "run_s": time.perf_counter() - t1}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    base = a.server.rstrip("/")
    tmp = Path(tempfile.mkdtemp())
    short, silent, weba = make_short_and_silent(tmp)
    fake_v = C / "audio" / "fake_opus" / "fake_000.ogg"
    real_v = C / "audio" / "real_opus" / "real_000.ogg"
    # (name, file, message text or None for speech-to-text, language, check[, channel])
    cases = [
        ("voice: cloned Hindi note, Whisper reads it", fake_v, None, "hi",
         lambda r: r["voice"]["status"] in ("synthetic", "abstain") and r["read_by"] and r["read_by"].startswith("faster-whisper")),
        ("voice: cloned Hindi note + ED scam text", fake_v, SCAM, "hi",
         lambda r: r["verdict"] == "RED"),
        ("voice: real Hindi note, benign text", real_v, BENIGN, "hi",
         lambda r: r["voice"]["status"] != "synthetic" and r["verdict"] in ("GREY", "AMBER")),
        ("voice: real Hindi note marked English (language reaches the check)", real_v, BENIGN, "en",
         lambda r: str(r["voice"].get("cell", "")).startswith("en/") or r["voice"]["status"] == "abstain"),
        ("voice: 1 s clip says unsure", short, BENIGN, "hi",
         lambda r: r["voice"]["status"] == "abstain"),
        ("voice: silent clip is refused with a sentence", silent, None, "hi",
         lambda r: r["http"] == 415),
        ("voice: browser recording (.weba, live-replay) gets a voice check and no face check", weba, BENIGN, "hi",
         lambda r: r["face"]["status"] == "-" and r["voice"]["status"] in ("abstain", "synthetic", "clean"), "live-replay"),
        ("video: face swap (HD) + ED scam text", C / "demo" / "officer_faceswap.mp4", SCAM, "hi",
         lambda r: r["verdict"] == "RED" and r["face"]["status"] == "synthetic"),
        ("video: genuine HD video, Whisper reads it", C / "unidata" / "video" / "1.mp4", None, "hi",
         lambda r: r["face"]["status"] == "clean" and r["verdict"] in ("GREY", "AMBER")),
        ("video: face swap, WhatsApp-size copy (honest SD cell)", C / "unidata_wa" / "deepfake__2.mp4", SCAM, "hi",
         lambda r: r["face"].get("cell") == "video/sd" and r["verdict"] == "RED"),
        ("video: genuine WhatsApp-size video", C / "commons_wa" / "c003.mp4", BENIGN, "hi",
         lambda r: r["face"]["status"] != "synthetic"),
        ("video: re-filmed at the counter (live-replay): the face check says unsure", C / "demo" / "officer_faceswap.mp4", SCAM, "hi",
         lambda r: r["face"]["status"] == "abstain" and r["face"].get("cell") == "video/live-replay", "live-replay"),
    ]
    rows, failed = [], 0
    for name, path, text, lang, ok, *chan in cases:
        if a.only and a.only not in name:
            continue
        if not path.exists():
            rows.append((name, "SKIP", f"missing {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}"))
            continue
        try:
            r = run_case(base, path, text, lang, *chan)
            passed = bool(ok(r))
        except Exception as e:  # noqa: BLE001 - one broken case must not hide the rest
            r, passed = {"error": f"{type(e).__name__}: {e}"}, False
        failed += not passed
        if r.get("http") not in (None, 200):
            summary = f"HTTP {r['http']}: {r.get('detail', '')}"
        elif "error" in r:
            summary = r["error"]
        else:
            sc = r["scores"]
            score = f"instr {sc.get('instruction_pct')}% / deepfake {sc.get('deepfake_pct')}% / combined {sc.get('combined_pct')}%" if sc else "rules only"
            summary = (f"{r['verdict']} ({score}) | face: {r['face']['status']} {r['face'].get('cell') or ''} {r['face'].get('score') or ''}"
                       f" | voice: {r['voice']['status']} {r['voice'].get('cell') or ''} {r['voice'].get('score') or ''}"
                       f" | read by {r['read_by'] or 'given text'} | upload {r['upload_s']:.0f}s run {r['run_s']:.0f}s")
        rows.append((name, "PASS" if passed else "FAIL", summary))
        print(f"{'PASS' if passed else 'FAIL'}  {name}\n      {summary}", flush=True)
    print(f"\n{sum(1 for r in rows if r[1] == 'PASS')} pass, {failed} fail, {sum(1 for r in rows if r[1] == 'SKIP')} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
