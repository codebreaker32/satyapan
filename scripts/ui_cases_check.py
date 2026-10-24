"""Every UI test case, run against the live demo (engine on :8000 connected to the forensics service), the way the
console does it: open a case, consent, upload the file with its language, optionally type the transcript, Run.

  python scripts/ui_cases_check.py                 # all cases in clips/ui-test
  python scripts/ui_cases_check.py A1 V3           # only these

Uploads without a typed transcript go through speech-to-text, so the instruction checks run on what was said.
Prints the transcript, each media check (face and voice), the verdict and the scores. Clips stay in clips/ (never
committed). This shows the pipeline working on each kind of upload; it is not an accuracy measurement.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_demo_check import call  # noqa: E402

BASE = "http://127.0.0.1:8000"
T = Path(__file__).resolve().parent.parent / "clips" / "ui-test"
SCAM = ("Main ED adhikari bol raha hoon. Aap digital arrest mein hain. Aaj hi 38 lakh rupaye is RBI supervision account "
        "mein transfer karein: A/c 30011223344556, IFSC DEMO0001234. Kisi ko mat batana.")

# id, file, language of the recording, typed transcript (None = speech-to-text), what the case is
CASES = [
    ("A1", "A1_cloned_hindi_voice.wav", "hi", None, "audio: cloned Hindi voice (IndicSynth XTTS)"),
    ("A1+", "A1_cloned_hindi_voice.wav", "hi", SCAM, "audio: cloned Hindi voice + typed ED scam"),
    ("A2", "A2_real_hindi_voice.wav", "hi", None, "audio: real Hindi voice (FLEURS)"),
    ("A2+", "A2_real_hindi_voice.wav", "hi", SCAM, "audio: real Hindi voice + typed ED scam"),
    ("A3", "A3_cloned_hindi_whatsapp_note.ogg", "hi", None, "audio: cloned voice as a WhatsApp note (Opus)"),
    ("A4", "A4_real_hindi_whatsapp_note.ogg", "hi", None, "audio: real voice as a WhatsApp note (Opus)"),
    ("A5", "A5_real_phone_call.mp3", "hi", None, "audio: real phone call, 8 kHz (Gram Vaani, unseen)"),
    ("A6", "A6_real_browser_voice_recording.webm", "hi", None, "audio: browser voice recording (WebM, no picture)"),
    ("A7", "A7_computer_voice_ED_order.wav", "en", None, "audio: Windows computer voice speaking an ED order"),
    ("V1", "V1_face_swap.mp4", "en", None, "video: face-swapped (UniDataPro)"),
    ("V1+", "V1_face_swap.mp4", "en", SCAM, "video: face-swapped + typed ED scam"),
    ("V2", "V2_genuine_face.mp4", "en", None, "video: genuine face (UniDataPro)"),
    ("V3", "V3_no_face_cloned_voice.mp4", "hi", None, "video: no face, cloned Hindi voice (AAC 64k)"),
    ("V3+", "V3_no_face_cloned_voice.mp4", "hi", SCAM, "video: no face, cloned voice + typed ED scam"),
    ("V4", "V4_no_face_real_voice.mp4", "hi", None, "video: no face, real Hindi voice (AAC 64k)"),
    ("V5", "V5_face_swap_whatsapp.mp4", "en", None, "video: face-swapped, WhatsApp-size (480p, AAC 64k)"),
    ("V6", "V6_genuine_browser_video.webm", "en", None, "video: genuine face, browser recording (WebM VP8 + Opus)"),
]


def main() -> int:
    only = set(sys.argv[1:])
    for cid_, name, lang, text, what in CASES:
        if only and cid_ not in only:
            continue
        path = T / name
        if not path.exists():
            print(f"\n== {cid_} SKIPPED: {path} is missing")
            continue
        case = call(BASE, "POST", "/api/cases", {"flag": {"reason": "large transfer to a first-time payee", "amount_inr": 380000,
                                                          "customer_ref": "cust-demo"}})
        cid = case["case"]["id"]
        call(BASE, "POST", f"/api/cases/{cid}/consent", {"check": True, "report": False, "memory": False, "lang": "hi"})
        t0 = time.perf_counter()
        call(BASE, "POST", f"/api/cases/{cid}/media", {"language": lang} | ({"derived_text": text} if text else {}),
             files={"file": path})
        t1 = time.perf_counter()
        c = call(BASE, "POST", f"/api/cases/{cid}/run")
        t2 = time.perf_counter()
        c = c.get("case", c)
        v = c.get("verdict") or {}
        m = (c.get("media") or [{}])[0]
        print(f"\n== {cid_}  {what}   [upload+read {t1 - t0:.0f} s, run {t2 - t1:.0f} s]")
        print(f"   file kind: {m.get('kind')} | read by: {m.get('derived_text_engine')} | text: {(m.get('derived_text') or '')[:110]}")
        for s in v.get("signals", []):
            if s.get("family") == "F3":
                d = s.get("detail") or {}
                print(f"   {s.get('rule_id'):14s} {str(d.get('status', '')):9s} {str(d.get('band', '')):9s} cell={d.get('cell')} "
                      f"deepfake%={d.get('deepfake_pct')} | {s.get('reason_en', '')[:100]}")
        print(f"   VERDICT {v.get('outcome')}  {v.get('scores')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
