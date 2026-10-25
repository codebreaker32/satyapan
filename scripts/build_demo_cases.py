"""Build the two live demo cases (the cloned voice note and the face swap) after a demo reset, the way the console
builds them.

Neither case is scripted: neither shows a SIMULATED detector result, and both are built in advance, so opening them
never waits on a model.

  .venv/bin/python scripts/build_demo_cases.py          # about 1-2 minutes; prints each case and its verdict

The cloned RM voice note: a real voice clone uploaded as the customer's WhatsApp voice note, plus the "RM's"
message (the S1 scenario's text, account number and IFSC) as the WhatsApp text that came from the same number. The
clone is IndicSynth Hindi (FreeVC voice conversion, CC-BY-NC-4.0): a lab recording standing in for the RM's cloned
voice, not any real person's voice. Speech-to-text writes down what the voice actually says (a lab sentence); the
voice check assesses the voice; the message checks assess the text.
The face swap: the public face-swap sample (UniDataPro, CC-BY-NC-ND-4.0) with the ED "digital arrest" text.

Exits 1 unless both cases come back RED with the real detector flagging the media. Run it after "Reset the demo"
(the reset clears every case), then open the Scenarios page.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_demo_check import call  # noqa: E402  - the same multipart client the e2e check uses

ROOT = Path(__file__).resolve().parent.parent
VOICE_CLONE = ROOT / "clips" / "audio" / "fake_opus" / "fake_000.ogg"
FACE_SWAP = ROOT / "clips" / "demo" / "officer_faceswap.mp4"
# what a WhatsApp voice note is called on an Android phone; the clip's own file name says "fake"
VOICE_NAME = "PTT-20261024-WA0011.opus"
ED_TEXT = ("Main ED adhikari bol raha hoon. Aap digital arrest mein hain. Aaj hi 38 lakh rupaye is RBI supervision "
           "account mein transfer karein: A/c 30011223344556, IFSC DEMO0001234. Kisi ko mat batana.")
# the console's own defaults for a new case (console/src/views/NewCase.tsx)
CONSOLE_FLAG = {"reason": "premature FD closure + RTGS to first-time payee", "amount_inr": 3800000,
                "customer_ref": "cust-demo", "channel": "branch"}
CONSOLE_CONSENT = {"check": True, "report": True, "memory": False, "lang": "hi"}


def s1() -> dict:
    data = json.loads((ROOT / "prototype" / "data" / "fixtures" / "scenarios.json").read_text(encoding="utf-8"))
    scenarios = data["scenarios"] if isinstance(data, dict) else data
    return next(s for s in scenarios if s["id"] == "S1-rm-voice-note")


def media_signal(verdict: dict, rule: str) -> dict:
    return next((s for s in verdict.get("signals", []) if s.get("rule_id") == rule), {})


def report(name: str, case: dict, rule: str) -> bool:
    v = case.get("verdict") or {}
    sig = media_signal(v, rule)
    d = sig.get("detail") or {}
    ok = (v.get("outcome") == "RED" and d.get("status") == "synthetic" and not d.get("simulated"))
    sc = v.get("scores") or {}
    print(f"{'OK  ' if ok else 'FAIL'} {name}: case {case['id']} -> {v.get('outcome')} "
          f"(instruction {sc.get('instruction_pct')}%, deepfake {sc.get('deepfake_pct')}%, combined {sc.get('combined_pct')}%)"
          f" | {rule}: {d.get('status')} {d.get('band', '')} score {d.get('score')} cell {d.get('cell')}"
          f"{' SIMULATED' if d.get('simulated') else ''}")
    for m in case.get("media", []):
        print(f"      media {m['filename']}: read by {m.get('derived_text_engine') or 'given text'}: {(m.get('derived_text') or '')[:90]}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    base = ap.parse_args().server.rstrip("/")
    svc = (call(base, "GET", "/api/meta").get("forensics") or {}).get("service") or {}
    health = svc.get("health") or {}
    if not health.get("ok") or not (health.get("audio") or {}).get("loaded"):
        print("The face and voice service is not connected or the voice model is not loaded; run scripts/demo_up.sh "
              "and satyapan preflight first.")
        return 1
    for p in (VOICE_CLONE, FACE_SWAP):
        if not p.exists():
            print(f"missing {p}")
            return 1

    sc = s1()
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        # The cloned RM voice note, and the RM's text from the same unknown number
        note = Path(tmp) / VOICE_NAME
        shutil.copyfile(VOICE_CLONE, note)
        cid = call(base, "POST", "/api/cases", {"flag": sc["flag"]})["case"]["id"]
        call(base, "POST", f"/api/cases/{cid}/consent", CONSOLE_CONSENT)
        call(base, "POST", f"/api/cases/{cid}/media", {"language": "hi", "sender_number": sc["sender_number"]},
             files={"file": note})
        call(base, "POST", f"/api/cases/{cid}/text", {"text": sc["text"], "source": "text",
                                                      "sender_number": sc["sender_number"]})
        out = call(base, "POST", f"/api/cases/{cid}/run")
        ok &= report("beat 2, cloned RM voice note + the RM's text", out.get("case", out), "R-AUDIO-SYNTH")

    # The face swap with the ED text, built exactly as it would be in the console
    cid = call(base, "POST", "/api/cases", {"flag": CONSOLE_FLAG})["case"]["id"]
    call(base, "POST", f"/api/cases/{cid}/consent", CONSOLE_CONSENT)
    call(base, "POST", f"/api/cases/{cid}/media", {"language": "hi", "derived_text": ED_TEXT}, files={"file": FACE_SWAP})
    out = call(base, "POST", f"/api/cases/{cid}/run")
    ok &= report("beat 4, face swap + the ED text", out.get("case", out), "R-VIDEO-SYNTH")
    print("Both demo cases are ready: open them from Cases." if ok else "A demo case did not come out as expected; "
          "do not use it on stage.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
