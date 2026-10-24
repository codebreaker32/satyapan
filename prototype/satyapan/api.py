"""FastAPI service: the officer console talks to this. One engine, in-memory cases (the demo is one laptop).

Run:  satyapan serve            (or: uvicorn satyapan.api:app --reload)
Dev:  the Vite console at :5173 calls http://127.0.0.1:8000/api with CORS allowed.
Prod: `npm run build` in console/ writes console/dist, which this app serves at /.
"""
from __future__ import annotations

import os

import copy
import json
import shutil
import statistics
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from . import POLICY_VERSION, __version__
from .adapters import Adapters
from .cli import MAX_TEXT_CHARS, load_scenarios, run_scenario, text_too_long
from .evidence import verify_pack
from .media import MediaUnreadable, contents_contradict_name, empty_message, kind_of, unreadable_message
from .models import Case, Consent, Flag, Issuer, visible_name
from .pipeline import STATE_DIR, Satyapan
from .rules import ISSUER_EN

app = FastAPI(title="Satyapan", version=__version__, description="Verify the instruction, not the pixels.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])

# The website check asks the domain registries live when the server runs (SATYAPAN_LIVE_WEB=0 turns that off, and
# the test suite does); offline it falls back to the recorded answers, so a dead venue network changes nothing.
engine = Satyapan(adapters=Adapters.mocks(live_web=os.environ.get("SATYAPAN_LIVE_WEB", "1") != "0"))
if os.environ.get("SATYAPAN_WHISPER_PRELOAD"):
    # demo_up.sh sets this: load the speech-to-text model in the background at start-up, so the first voice note of
    # the demo does not also wait 15-60 s for the model to load. Failure here only means the first note loads it.
    import threading

    def _preload_whisper() -> None:
        try:
            from .media import _whisper
            _whisper(os.environ.get("SATYAPAN_WHISPER_MODEL", "small"))
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_preload_whisper, daemon=True).start()

UPLOADS = STATE_DIR / "uploads"

# Upload limits for the demo. The cap bounds what lands on disk under evidence/uploads/; the request body itself
# is still read by the framework first, which is acceptable on 127.0.0.1.
MAX_UPLOAD_MB = 25
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp",                      # images
                      ".ogg", ".opus", ".mp3", ".wav", ".m4a", ".weba",      # audio (.weba: a browser's own recording)
                      ".mp4", ".webm",                                       # video
                      ".pdf",                                                # scanned notices
                      ".txt"}                                                # text
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp",
                         "audio/ogg", "audio/opus", "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
                         "audio/mp4", "audio/x-m4a", "audio/m4a", "audio/webm",
                         "video/mp4", "video/webm", "application/pdf", "text/plain"}
ALLOWED_PLAIN = ("an image (png, jpg, webp), a voice note or audio file (ogg, opus, mp3, wav, m4a, weba), "
                 "a video (mp4, webm), a PDF or plain text (txt)")

# Session state: time-to-verdict per run in this serve process, and the campaign memory as it stood at start-up,
# so /api/demo/reset can put a rehearsal back to a clean slate without touching fixture data.
_verdict_ms: list[float] = []
_memory_at_start: list[dict] = copy.deepcopy(engine.memory.entries)
_memory_file_at_start: Optional[str] = engine.memory.path.read_text(encoding="utf-8") if engine.memory.path.exists() else None


def timed_run(fn):
    """Run one verdict-producing call and record its wall time (session-scoped, for /api/meta)."""
    t0 = time.perf_counter()
    out = fn()
    _verdict_ms.append((time.perf_counter() - t0) * 1000.0)
    return out


# ---------- serialisation ----------

def case_view(case: Case) -> dict:
    out = {"case": case.model_dump(mode="json")}
    if case.verdict:
        out["card"] = {"hi": engine.card(case, "hi").model_dump(mode="json"), "en": engine.card(case, "en").model_dump(mode="json")}
        out["review_triggers"] = engine.review_triggers(case)
    inp = engine._inputs.get(case.id, {})
    out["inputs"] = {"sender_number": inp.get("sender_number"), "bank_signature_present": bool(inp.get("signature")),
                     "forensics_simulated": bool(inp.get("forensics_sim")), "mode": "claim-only" if inp.get("picklist") else "media"}
    if inp.get("scenario"):   # a case opened from a scenario keeps that context when reopened by URL or from the list
        out["scenario"] = inp["scenario"]
    return out


ACTOR_REQUIRED = ("Type your staff id before recording a decision. The evidence pack is signed with the name of "
                  "whoever made the decision, so it cannot be left blank.")
ANALYST_REQUIRED = ("Type your staff id before adding this to campaign memory. Every entry records who proposed it "
                    "and who approved it.")


def require_actor(actor: str, message: str = ACTOR_REQUIRED) -> str:
    """A decision must carry someone's name. Whitespace is nobody, the same way a whitespace-only co-sign is no
    co-sign in `Satyapan.decide`. Returns the trimmed name, which is what the signed evidence pack records."""
    name = visible_name(actor)
    if not name:
        raise HTTPException(422, message)
    return name


def get_case(case_id: str) -> Case:
    case = engine.cases.get(case_id)
    if not case:
        raise HTTPException(404, f"no case {case_id}")
    return case


# ---------- meta ----------

@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/meta")
def meta():
    return {"version": __version__, "policy_version": POLICY_VERSION, "bank_name": engine.book.bank_name,
            "rulebook": {"version": engine.book.version, "sha256": engine.book.sha256, "rules": [
                {"id": m.id, "family": m.family.value, "severity": m.severity.value, "title": m.title, "citation": m.citation.source,
                 "citation_url": m.citation.url, "verified": m.citation.verified, "checked": m.citation.checked} for m in engine.book.rules.values()]},
            "adapters": engine.adapters.labels(),
            "forensics": {"audio": engine.audio.label.as_dict(), "document": engine.document.label.as_dict(),
                          "service": ({**engine.remote.label.as_dict(), "health": engine.remote.health()} if engine.remote else None)},
            "signer": engine.signer.label.as_dict(),
            # honest scope: wall time to verdict in this serve session on this laptop, not a benchmark
            "session_timing": {"count": len(_verdict_ms),
                               "session_p50_verdict_ms": round(statistics.median(_verdict_ms), 1) if _verdict_ms else None,
                               "scope": "this serve session only; cleared by /api/demo/reset"}}


# ---------- scenarios (finale demo) ----------

@app.get("/api/scenarios")
def scenarios():
    return [{"id": s["id"], "title": s["title"], "lang": s.get("lang", "hi"), "flag": s["flag"], "expect": s.get("expect"),
             "mode": "claim-only" if "picklist" in s else "media", "media_kind": s.get("media_kind", "text"),
             "has_rehearsal_forensics": bool(s.get("forensics_sim")), "has_reencode_step": bool(s.get("then_forensics"))}
            for s in load_scenarios()]


@app.post("/api/scenarios/{sid}/run")
def run_scenario_endpoint(sid: str):
    sc = next((s for s in load_scenarios() if s["id"] == sid), None)
    if not sc:
        raise HTTPException(404, f"no scenario {sid}")
    saved = engine._now
    try:
        engine._now = datetime.fromisoformat(sc["now"]) if sc.get("now") else None
        _, case = timed_run(lambda: run_scenario(sc, engine))
    finally:
        engine._now = saved
    engine._inputs[case.id]["scenario"] = {"id": sid, "title": sc["title"], "text": sc.get("text"), "picklist": sc.get("picklist"),
                                           "then_forensics": sc.get("then_forensics"), "expect": sc.get("expect")}
    return case_view(case)


@app.post("/api/scenarios/{sid}/reencode")
def reencode(sid: str, case_id: str = Body(..., embed=True)):
    """Rehearsal step: the same media after WhatsApp / 8 kHz re-encoding, where forensics abstain."""
    sc = next((s for s in load_scenarios() if s["id"] == sid), None)
    if not sc or not sc.get("then_forensics"):
        raise HTTPException(404, "scenario has no re-encode step")
    case = get_case(case_id)
    engine.simulate_forensics(case, sc["then_forensics"])
    saved = engine._now
    try:
        engine._now = datetime.fromisoformat(sc["now"]) if sc.get("now") else None
        timed_run(lambda: engine.run(case))
    finally:
        engine._now = saved
    return case_view(case)


# ---------- cases ----------

class OpenCase(BaseModel):
    flag: Flag
    consent: Optional[Consent] = None


class TextIn(BaseModel):
    text: str
    source: str = "text"
    sender_number: Optional[str] = None
    signed: bool = False          # demo: treat as a notice the bank itself signed
    kind: str = "text"
    filename: str = "message.txt"


class PicklistIn(BaseModel):
    issuer: str
    instruction: str
    channel: str = "UNKNOWN"
    claimed_owner: str = "UNKNOWN"
    account: Optional[str] = None
    ifsc: Optional[str] = None
    vpa: Optional[str] = None
    pressure: list[str] = []
    has_passcode: Optional[bool] = None
    mentions_summons: bool = False


class DecisionIn(BaseModel):
    actor: str
    action: str
    note: str = ""
    co_signer: Optional[str] = None


@app.post("/api/cases")
def open_case(body: OpenCase):
    case = engine.open_case(body.flag, body.consent)
    return case_view(case)


def case_about(c: Case) -> Optional[str]:
    """One line that tells two cases with the same flag apart in the list: the scenario title when the case was
    opened from a scenario, else who the message claimed to be from."""
    sc = engine._inputs.get(c.id, {}).get("scenario")
    if sc:
        return sc["title"]
    if c.claim and c.claim.claimed_issuer.value != "NONE":
        # OTHER is the open-set authority: a body the rulebook holds no rule for. Printing the enum would put
        # "claims OTHER" in the case list, which says nothing; ISSUER_EN is the same phrase the rule's reason
        # uses, and the body's own name stays in the quoted span where it belongs (it is attacker-controlled).
        if c.claim.claimed_issuer == Issuer.OTHER:
            return f"claims to be {ISSUER_EN[Issuer.OTHER]}"
        return f"claims {c.claim.claimed_issuer.value.replace('_', ' ')}"   # BANK_SELF reads "claims BANK SELF"
    return None


@app.get("/api/cases")
def list_cases():
    return [{"id": c.id, "created_at": c.created_at, "status": c.status, "flag": c.flag.model_dump(mode="json"),
             "outcome": c.verdict.outcome.value if c.verdict else None, "about": case_about(c)} for c in engine.cases.values()]


@app.get("/api/cases/{case_id}")
def read_case(case_id: str):
    return case_view(get_case(case_id))


@app.post("/api/cases/{case_id}/consent")
def consent(case_id: str, check: bool = Body(...), report: bool = Body(False), memory: bool = Body(False), lang: str = Body("hi")):
    return case_view(engine.set_consent(get_case(case_id), check=check, report=report, memory=memory, lang=lang))


@app.post("/api/cases/{case_id}/text")
def add_text(case_id: str, body: TextIn):
    case = get_case(case_id)
    if len(body.text) > MAX_TEXT_CHARS:
        raise HTTPException(413, text_too_long(len(body.text)))
    signature = engine.adapters.signature.sign(body.text) if body.signed else None
    engine.add_text(case, body.text, source=body.source, sender_number=body.sender_number, signature=signature, kind=body.kind, filename=body.filename)
    return case_view(case)


@app.post("/api/cases/{case_id}/media")
async def add_media(case_id: str, file: UploadFile = File(...), derived_text: Optional[str] = Form(None),
                    sender_number: Optional[str] = Form(None), language: str = Form("hi"),
                    channel: Optional[str] = Form(None)):
    case = get_case(case_id)
    if channel not in (None, "live-replay"):   # the only channel a caller can assert; the rest is read off the file
        raise HTTPException(422, "channel may only be 'live-replay' (a recording made at the counter)")
    if derived_text is not None and len(derived_text) > MAX_TEXT_CHARS:
        raise HTTPException(413, text_too_long(len(derived_text)))
    name = Path(file.filename or "upload.bin").name
    ext = Path(name).suffix.lower()
    declared = (file.content_type or "").split(";")[0].strip().lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"'{ext or name}' files aren't accepted here. Please upload {ALLOWED_PLAIN}.")
    if declared and declared != "application/octet-stream" and declared not in ALLOWED_CONTENT_TYPES:
        # Some browsers send no type (or a generic one) for voice notes; the extension check above still applies.
        raise HTTPException(415, f"The upload says its type is '{declared}', which isn't accepted here. Please upload {ALLOWED_PLAIN}.")
    # The upload is staged outside evidence/uploads/ and only moved in once it has decoded, so a rejected
    # file leaves nothing behind for the officer (or the evidence pack) to trip over.
    kind = kind_of(Path(name))
    staging = Path(tempfile.mkdtemp(prefix="satyapan-upload-"))
    path = staging / name
    try:
        written, head = 0, b""
        with open(path, "wb") as f:
            while chunk := file.file.read(1 << 20):
                if not head:
                    head = chunk[:16]
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:   # the size cap fires before any decoding work
                    raise HTTPException(413, f"That file is too big. Uploads are limited to {MAX_UPLOAD_MB} MB for the demo.")
                if ext == ".txt" and written > MAX_TEXT_CHARS * 4:   # a text file IS the text; same cap as the paste box (x4 for UTF-8)
                    raise HTTPException(413, text_too_long(written))
                f.write(chunk)
        if written == 0:
            raise HTTPException(415, empty_message(name))
        if contents_contradict_name(kind, head):   # cheap magic-byte check before OCR or speech-to-text
            raise HTTPException(415, unreadable_message(name, kind))
        if engine.remote is not None and kind in ("audio", "video"):
            engine.remote.prefetch(path, kind, language=language, channel=channel)   # start now, alongside speech-to-text
        try:
            # Speech-to-text (Whisper) and OCR take seconds to a minute; run them off the event loop so the console and
            # every other request stay responsive while a voice note or video is read.
            await run_in_threadpool(engine.add_media, case, path, derived_text=derived_text, sender_number=sender_number,
                                    language=language, channel=channel)
        except MediaUnreadable as e:   # a decoder opened it and found nothing readable
            raise HTTPException(415, str(e)) from e
        except RuntimeError as e:      # no STT/OCR installed: ask the console for the transcript
            raise HTTPException(422, str(e)) from e
        kept = UPLOADS / case.id
        kept.mkdir(parents=True, exist_ok=True)
        # One kept file per recorded hash. Two uploads with the same name used to overwrite each other while both
        # sha256 entries stayed in the signed manifest, so a pack that verified asserted a hash for a file that no
        # longer existed — and the manifest is what a Bharatiya Sakshya Adhiniyam s.63(4) certificate would rest on.
        final = kept / f"{max(len(case.media) - 1, 0):02d}-{name}"   # this upload's index; add_media already appended
        shutil.move(str(path), str(final))
        if case.media:   # forensics read the kept file, found by this upload's index (the same one as in its name)
            engine._inputs[case.id]["media_paths"][len(case.media) - 1] = final
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return case_view(case)


@app.post("/api/cases/{case_id}/picklist")
def add_picklist(case_id: str, body: PicklistIn):
    case = get_case(case_id)
    engine.add_picklist(case, **body.model_dump())
    return case_view(case)


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str):
    case = get_case(case_id)
    if case.media:
        # An uploaded voice note or video can wait on the face and voice service for most of a minute. The Scenarios
        # page's timing line says "engine only", so such runs are not recorded there.
        return case_view(engine.run(case))
    return case_view(timed_run(lambda: engine.run(case)))


@app.post("/api/cases/{case_id}/decide")
def decide(case_id: str, body: DecisionIn):
    actor = require_actor(body.actor)
    try:
        return case_view(engine.decide(get_case(case_id), actor=actor, action=body.action, note=body.note, co_signer=body.co_signer))
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/cases/{case_id}/strike")
def strike(case_id: str, field: str = Body(...), actor: str = Body(...)):
    return case_view(engine.strike_field(get_case(case_id), field, require_actor(actor)))


@app.post("/api/cases/{case_id}/forensics/simulate")
def simulate(case_id: str, result: dict = Body(...)):
    """Rehearsal only. The result is labelled SIMULATED in every signal and in the evidence pack."""
    case = get_case(case_id)
    engine.simulate_forensics(case, result)
    return case_view(timed_run(lambda: engine.run(case)))


@app.get("/api/cases/{case_id}/evidence")
def evidence(case_id: str, download: bool = False):
    pack = engine.evidence_pack(get_case(case_id))
    if download:
        return JSONResponse(pack, headers={"Content-Disposition": f'attachment; filename="{case_id}.evidence.json"'})
    return pack


@app.post("/api/evidence/verify")
def verify(pack: dict = Body(...)):
    ok, reason = verify_pack(pack)
    return {"ok": ok, "reason": reason}


# ---------- campaign memory (FRMU) ----------

@app.get("/api/memory")
def memory():
    return {"entries": [{k: v for k, v in e.items() if k != "tokens"} for e in engine.memory.entries]}


EVAL_RESULTS = Path(__file__).resolve().parent.parent / "data" / "eval" / "results.json"


@app.get("/api/evaluation")
def evaluation():
    """The labelled evaluation exactly as `satyapan evaluate` wrote it. Nothing here is computed for the screen, so
    the numbers the console shows are the numbers in data/eval/results.json and docs/evaluation.md."""
    if not EVAL_RESULTS.exists():
        raise HTTPException(404, "No evaluation has been run yet. Run `satyapan evaluate` on this laptop.")
    return json.loads(EVAL_RESULTS.read_text(encoding="utf-8"))


@app.post("/api/memory/propose")
def propose(case_id: str = Body(...), analyst: str = Body(...), note: str = Body("")):
    case = get_case(case_id)
    if not case.claim:
        raise HTTPException(400, "run the case first")
    if not case.consent.memory:
        raise HTTPException(403, "customer did not consent (C3) to adding this to campaign memory")
    e = engine.memory.propose(case.claim, require_actor(analyst, ANALYST_REQUIRED), [m.sha256 for m in case.media],
                              [m.perceptual_hash for m in case.media if m.perceptual_hash], note)
    return {k: v for k, v in e.items() if k != "tokens"}


@app.post("/api/memory/{entry_id}/approve")
def approve(entry_id: str, analyst: str = Body(..., embed=True)):
    e = engine.memory.approve(entry_id, require_actor(analyst, ANALYST_REQUIRED))
    return {k: v for k, v in e.items() if k != "tokens"}


# ---------- demo reset ----------

@app.post("/api/demo/reset")
def demo_reset():
    """Put a rehearsal back to a clean slate without restarting the server: clear the in-memory cases (and their
    uploaded files), drop campaign-memory entries added this session, and clear session timings. Fixture data
    (scenarios, rulebook, the campaign memory shipped in data/mocks) is never touched."""
    cases_cleared = len(engine.cases)
    for cid in list(engine.cases):   # snapshot: a threadpool-concurrent run must not break the iteration
        shutil.rmtree(UPLOADS / cid, ignore_errors=True)
    engine.cases.clear()
    engine._inputs.clear()
    memory_removed = max(len(engine.memory.entries) - len(_memory_at_start), 0)
    if engine.memory.entries != _memory_at_start:
        engine.memory.entries[:] = copy.deepcopy(_memory_at_start)
        if _memory_file_at_start is not None:   # restore the file byte-for-byte as it was at start-up
            engine.memory.path.write_text(_memory_file_at_start, encoding="utf-8")
    _verdict_ms.clear()
    return {"ok": True, "cases_cleared": cases_cleared, "memory_entries_removed": memory_removed, "timings_cleared": True}


# ---------- console (built with `npm run build` in console/) ----------

DIST = Path(__file__).resolve().parent.parent / "console" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path == "api" or path.startswith("api/"):   # a typo'd API call should fail loudly, not parse index.html
            raise HTTPException(404, "no such API endpoint")
        # A null byte is refused here rather than left to resolve(): POSIX raises on it (the except below), but on
        # Windows resolve() accepts it, is_file() is quietly False, and the path fell through to index.html.
        if "\x00" in path:
            raise HTTPException(404, "not found")
        try:
            candidate = (DIST / path).resolve()
        except (ValueError, OSError):            # e.g. an embedded null byte in the path
            raise HTTPException(404, "not found")
        if not candidate.is_relative_to(DIST):   # containment: a "../" path never leaves console/dist
            raise HTTPException(404, "not found")
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
