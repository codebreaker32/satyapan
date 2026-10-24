"""The officer error paths a judge walks: a file we cannot read, a decision with nobody's name on it, and the
pack verifier's answer on a file that is not a pack.

A rejected upload must say what happened, say what the officer can do instead, and leave nothing on disk. These
tests drive the real module-level app, so each one starts and ends with POST /api/demo/reset.
"""
import glob
import io
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import satyapan.api as api
from satyapan.media import contents_contradict_name, sniff, tesseract_cmd

client = TestClient(api.app)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff\xe0"


@pytest.fixture(autouse=True)
def clean_session():
    client.post("/api/demo/reset")
    yield
    client.post("/api/demo/reset")


def open_case() -> str:
    r = client.post("/api/cases", json={"flag": {"reason": "test flag", "amount_inr": 50000, "customer_ref": "cust-demo"}})
    assert r.status_code == 200
    return r.json()["case"]["id"]


def upload(cid: str, filename: str, data: bytes, content_type: str, **form):
    return client.post(f"/api/cases/{cid}/media", files={"file": (filename, data, content_type)}, data=form)


def nothing_kept(cid: str) -> bool:
    """A rejected upload leaves no artefact: no case directory under evidence/uploads/, and no staging directory."""
    d = api.UPLOADS / cid
    staged = glob.glob(str(Path(tempfile.gettempdir()) / "satyapan-upload-*"))
    return (not d.exists() or not list(d.iterdir())) and not staged


def tiny_png(text: str = "DEMO BANK") -> bytes:
    """A real, small, valid PNG: black text on white, large enough for tesseract. Synthetic, no logos or names."""
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    assert PIL
    img = Image.new("RGB", (420, 90), "white")
    ImageDraw.Draw(img).text((12, 30), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------- a file we cannot read: 415, plain English, nothing kept ----------

def test_text_renamed_as_png_is_415_not_500():
    cid = open_case()
    r = upload(cid, "fake.png", b"this is just plain text, not a png at all\n", "image/png")
    assert r.status_code == 415
    detail = r.json()["detail"]
    assert "could not read 'fake.png'" in detail
    assert "claim-only mode" in detail          # the officer is pointed at the route that works without media
    assert nothing_kept(cid)


def test_empty_upload_is_415_and_says_the_file_is_empty():
    cid = open_case()
    r = upload(cid, "empty.jpg", b"", "image/jpeg")
    assert r.status_code == 415
    detail = r.json()["detail"]
    assert "arrived with no content" in detail and "claim-only mode" in detail
    assert nothing_kept(cid)


def test_oversize_upload_is_413_before_any_decoding_and_keeps_nothing():
    cid = open_case()
    oversize = JPEG_MAGIC + b"\x00" * api.MAX_UPLOAD_BYTES   # valid magic, so only the size cap can reject it
    r = upload(cid, "scan.jpg", oversize, "image/jpeg")
    assert r.status_code == 413
    assert f"{api.MAX_UPLOAD_MB} MB" in r.json()["detail"]
    assert nothing_kept(cid)


def test_a_file_whose_bytes_contradict_its_name_is_415():
    cid = open_case()
    r = upload(cid, "voice-note.mp3", tiny_png(), "audio/mpeg")   # a PNG wearing an audio name
    assert r.status_code == 415
    assert "could not read 'voice-note.mp3'" in r.json()["detail"]
    assert nothing_kept(cid)


@pytest.mark.skipif(tesseract_cmd() is None, reason="tesseract binary not installed")
def test_truncated_image_with_valid_magic_is_415_from_the_decoder():
    """Magic-byte sniffing cannot catch this one; the decoder wrap in media.py has to."""
    cid = open_case()
    r = upload(cid, "notice.png", PNG_MAGIC + b"\x00" * 64, "image/png")
    assert r.status_code == 415
    assert "could not read 'notice.png'" in r.json()["detail"]
    assert nothing_kept(cid)


def test_unrecognised_audio_bytes_are_still_accepted_on_the_extension():
    """Recorded decision: browsers send no type and no signature we know for some voice notes, so an allow-listed
    extension is accepted on the extension alone. Sniffing is a reason to reject, never a new reason to accept.

    What happens next depends on the install, and each answer is asserted exactly. With no speech-to-text the
    answer is the 422 that asks the console for a transcript. With speech-to-text installed (as on the finale
    laptop since 23 Oct) the decoder is what refuses these bytes, so the answer is the 415 that says the file
    could not be read, the same answer a truncated image gets. Either way nothing is kept."""
    cid = open_case()
    r = upload(cid, "voice-note.ogg", b"\x00not a container we know\x00", "")
    assert r.status_code in (422, 415), r.text
    if r.status_code == 422:
        assert "speech-to-text" in r.json()["detail"]
    else:
        assert "could not read 'voice-note.ogg'" in r.json()["detail"]
    assert nothing_kept(cid)


# ---------- a valid file still works, and is kept ----------

def test_valid_small_png_is_accepted_and_kept_on_disk():
    cid = open_case()
    r = upload(cid, "notice.png", tiny_png(), "image/png", derived_text="Demo Bank: your statement is ready.")
    assert r.status_code == 200, r.text
    media = r.json()["case"]["media"][0]
    assert media["kind"] == "image" and media["filename"] == "notice.png" and media["sha256"]
    # The kept name is prefixed with the media index: two uploads called notice.png used to overwrite each other
    # while both sha256 entries stayed in the signed manifest, so a pack that verified asserted a hash for a file
    # that no longer existed. The recorded filename the officer sees is unchanged.
    kept = api.UPLOADS / cid / "00-notice.png"
    assert kept.is_file(), "a file that decoded is kept under evidence/uploads/"
    assert api.engine._inputs[cid]["media_paths"]["notice.png"] == kept   # forensics read the kept file


def test_two_uploads_with_the_same_name_each_keep_their_own_file():
    """The gate's finding: the manifest records a hash per upload, so there must be a file per hash."""
    cid = open_case()
    first = upload(cid, "notice.png", tiny_png(), "image/png", derived_text="first notice")
    assert first.status_code == 200, first.text
    second = upload(cid, "notice.png", tiny_png("SECOND NOTICE"), "image/png", derived_text="second notice")
    assert second.status_code == 200, second.text
    media = second.json()["case"]["media"]
    assert len(media) == 2
    assert media[0]["sha256"] != media[1]["sha256"], "two different files were uploaded"
    kept = sorted(p.name for p in (api.UPLOADS / cid).iterdir())
    assert len(kept) == 2, f"a file per recorded hash, got {kept}"


@pytest.mark.skipif(tesseract_cmd() is None, reason="tesseract binary not installed")
def test_valid_small_png_runs_ocr_for_real():
    cid = open_case()
    r = upload(cid, "notice.png", tiny_png("DEMO BANK"), "image/png")
    assert r.status_code == 200, r.text
    assert r.json()["case"]["media"][0]["derived_text_engine"].startswith("tesseract ")


# ---------- the sniffer itself ----------

@pytest.mark.parametrize("head,family", [
    (PNG_MAGIC, "image"),
    (JPEG_MAGIC, "image"),
    (b"RIFF\x00\x00\x00\x00WEBP", "image"),
    (b"RIFF\x00\x00\x00\x00WAVE", "audio"),
    (b"OggS\x00\x02\x00\x00", "audio"),
    (b"ID3\x04\x00\x00\x00", "audio"),
    (b"\x00\x00\x00 ftypM4A ", "audio"),
    (b"\x00\x00\x00 ftypisom", "video"),
    (b"\x1a\x45\xdf\xa3\x01\x00\x00\x00", "video"),
    (b"%PDF-1.7\n", "pdf"),
    (b"plain text here", None),
    (b"", None),
])
def test_sniff_reads_the_magic_bytes(head, family):
    assert sniff(head) == family


def test_sniffing_never_rejects_a_file_it_cannot_recognise_unless_the_name_promises_magic():
    assert contents_contradict_name("image", b"hello") is True     # png/jpg/webp always carry a signature
    assert contents_contradict_name("pdf", b"hello") is True
    assert contents_contradict_name("audio", b"hello") is False    # some voice notes arrive unrecognisable
    assert contents_contradict_name("video", b"hello") is False
    assert contents_contradict_name("text", b"hello") is False
    assert contents_contradict_name("audio", PNG_MAGIC) is True    # recognised, and not what the name says


# ---------- a decision must carry someone's name ----------

@pytest.mark.parametrize("actor", ["", "   ", "\t\n"])
def test_blank_actor_on_a_decision_is_422(actor):
    cid = open_case()
    r = client.post(f"/api/cases/{cid}/decide", json={"actor": actor, "action": "hold", "note": "", "co_signer": None})
    assert r.status_code == 422
    assert "staff id" in r.json()["detail"]
    assert client.get(f"/api/cases/{cid}").json()["case"]["decisions"] == [], "nothing unsigned reaches the case"


def test_named_actor_still_records_the_decision_and_is_trimmed():
    cid = open_case()
    r = client.post(f"/api/cases/{cid}/decide", json={"actor": "  officer.bhawna  ", "action": "hold", "note": "waiting on the customer"})
    assert r.status_code == 200, r.text
    decisions = r.json()["case"]["decisions"]
    assert len(decisions) == 1 and decisions[0]["actor"] == "officer.bhawna"
    assert r.json()["case"]["status"] == "held"


def test_blank_actor_on_a_struck_field_is_422():
    """Striking a field records a decision too, so it needs a name for the same reason."""
    cid = open_case()
    client.post(f"/api/cases/{cid}/text", json={"text": "RBI supervision account mein paise bhejo", "sender_number": "+919000000001"})
    client.post(f"/api/cases/{cid}/run")
    r = client.post(f"/api/cases/{cid}/strike", json={"field": "issuer", "actor": " "})
    assert r.status_code == 422 and "staff id" in r.json()["detail"]


def test_blank_analyst_cannot_propose_to_campaign_memory():
    cid = open_case()
    client.post(f"/api/cases/{cid}/consent", json={"check": True, "report": False, "memory": True})
    client.post(f"/api/cases/{cid}/text", json={"text": "RBI supervision account mein paise bhejo", "sender_number": "+919000000001"})
    client.post(f"/api/cases/{cid}/run")
    r = client.post("/api/memory/propose", json={"case_id": cid, "analyst": "  ", "note": ""})
    assert r.status_code == 422 and "staff id" in r.json()["detail"]


# ---------- the pack verifier speaks to a person ----------

def test_verify_garbage_payload_keeps_the_shape_and_explains_itself():
    r = client.post("/api/evidence/verify", json={"hello": "world"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ok", "reason"}, "the console renders exactly these two keys"
    assert body["ok"] is False
    assert "not a Satyapan evidence pack" in body["reason"]
    assert "None" not in body["reason"] and "unknown format" not in body["reason"]


def test_verify_pack_with_no_manifest_is_a_sentence_not_a_500():
    r = client.post("/api/evidence/verify", json={"format": "satyapan-evidence/1", "manifest_sha256": "0" * 64})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "no manifest" in r.json()["reason"]


def test_verify_pack_from_another_build_names_both_formats():
    r = client.post("/api/evidence/verify", json={"format": "satyapan-evidence/99", "manifest": {}, "manifest_sha256": "x"})
    assert r.json()["ok"] is False
    assert "satyapan-evidence/99" in r.json()["reason"] and "satyapan-evidence/1" in r.json()["reason"]


def test_verify_reasons_read_as_full_sentences():
    """The console prints "Verifies." or "Does not verify." and then the reason, so each reason starts a sentence."""
    for payload in ({"hello": "world"},
                    {"format": "satyapan-evidence/1", "manifest_sha256": "0" * 64},
                    {"format": "satyapan-evidence/1", "manifest": {}, "manifest_sha256": "0" * 64},
                    {"format": "satyapan-evidence/1", "manifest": {}, "manifest_sha256": None, "signature": {"alg": "rot13"}}):
        reason = client.post("/api/evidence/verify", json=payload).json()["reason"]
        assert reason[:1].isupper() and reason.endswith(".")


def test_a_real_pack_still_verifies_through_the_api():
    r = client.post("/api/scenarios/S1-rm-voice-note/run")
    assert r.status_code == 200, r.text
    cid = r.json()["case"]["id"]
    pack = client.get(f"/api/cases/{cid}/evidence").json()
    good = client.post("/api/evidence/verify", json=pack).json()
    assert good["ok"] is True and "signature" in good["reason"]
    pack["manifest"]["case"]["flag"]["amount_inr"] += 1
    bad = client.post("/api/evidence/verify", json=pack).json()
    assert bad["ok"] is False and "altered after signing" in bad["reason"]


def test_media_ingest_runs_off_the_event_loop(monkeypatch):
    """Whisper takes 15-70 s on a voice note; on the event loop it froze every other request, the console included."""
    import asyncio

    from satyapan import api
    seen = {}

    def fake_add_media(case, path, **kw):
        try:
            asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        api.engine._inputs[case.id]["texts"].append(("transcript", "hello"))
    monkeypatch.setattr(api.engine, "add_media", fake_add_media)
    cid = open_case()
    upload(cid, "voice-note.ogg", b"OggS" + b"\x00" * 60, "audio/ogg")
    assert seen == {"on_loop": False}
