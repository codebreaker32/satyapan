"""API hardening: upload limits, SPA path containment, demo reset, and session timing in /api/meta.

These tests drive the real module-level app (one engine, in-memory cases), so each test starts and
ends with POST /api/demo/reset to leave the shared engine clean.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import satyapan.api as api

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def clean_session():
    client.post("/api/demo/reset")
    yield
    client.post("/api/demo/reset")


def open_case() -> str:
    r = client.post("/api/cases", json={"flag": {"reason": "test flag", "amount_inr": 50000, "customer_ref": "cust-demo"}})
    assert r.status_code == 200
    return r.json()["case"]["id"]


def raw_get(path: str):
    """GET straight into the ASGI app, so the client library can't normalise '../' away before it reaches the server."""
    result = {"status": None, "body": b""}

    async def run():
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                 "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "headers": [], "server": ("testserver", 80), "client": ("testclient", 50000)}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                result["status"] = msg["status"]
            elif msg["type"] == "http.response.body":
                result["body"] += msg.get("body", b"")

        await api.app(scope, receive, send)

    asyncio.run(run())
    return result["status"], result["body"]


# ---------- upload limits ----------

def test_upload_over_size_limit_is_413():
    cid = open_case()
    too_big = b"0" * (api.MAX_UPLOAD_BYTES + 1)
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("note.wav", too_big, "audio/wav")})
    assert r.status_code == 413
    assert f"{api.MAX_UPLOAD_MB} MB" in r.json()["detail"]
    # the partial file must not be left behind
    assert not (api.UPLOADS / cid / "note.wav").exists()


def test_upload_disallowed_extension_is_415():
    cid = open_case()
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("tool.exe", b"MZ....", "application/octet-stream")})
    assert r.status_code == 415
    assert "aren't accepted" in r.json()["detail"]


def test_upload_allowed_extension_but_bad_declared_type_is_415():
    cid = open_case()
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("note.txt", b"hello", "application/x-msdownload")})
    assert r.status_code == 415


def test_upload_small_text_file_is_accepted():
    cid = open_case()
    text = "Demo Bank: aapka KYC update ho gaya hai."
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("note.txt", text.encode("utf-8"), "text/plain")})
    assert r.status_code == 200
    assert r.json()["case"]["media"][0]["filename"] == "note.txt"


def test_upload_pdf_with_text_layer_is_accepted(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    cid = open_case()
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "SUMMONS under Section 50 PMLA. Summon No. ED/DLZO/2026/4471.")
    pdf_bytes = doc.tobytes()
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("summons.pdf", pdf_bytes, "application/pdf")})
    assert r.status_code == 200
    media = r.json()["case"]["media"][0]
    assert media["derived_text_engine"] == "pdf text layer (pymupdf)"
    assert "ED/DLZO/2026/4471" in media["derived_text"]


def test_upload_allowed_extension_with_generic_declared_type_is_accepted():
    # some browsers send application/octet-stream (or nothing) for voice notes; the extension check still applies
    cid = open_case()
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("note.txt", b"Demo Bank: statement ready.", "application/octet-stream")})
    assert r.status_code == 200


def test_pasted_text_over_cap_is_413_with_plain_message():
    cid = open_case()
    client.post(f"/api/cases/{cid}/consent", json={"check": True})
    r = client.post(f"/api/cases/{cid}/text", json={"text": "a" * (api.MAX_TEXT_CHARS + 1)})
    assert r.status_code == 413
    assert "too long" in r.json()["detail"] and f"{api.MAX_TEXT_CHARS:,}" in r.json()["detail"]
    # just under the cap still verdicts (and the extractor over a cap-sized paste stays inside a demo-safe budget)
    import time
    r = client.post(f"/api/cases/{cid}/text", json={"text": "Demo Bank statement ready. " * 900})
    assert r.status_code == 200
    t0 = time.perf_counter()
    assert client.post(f"/api/cases/{cid}/run").status_code == 200
    assert time.perf_counter() - t0 < 10.0, "a near-cap paste must verdict fast enough for a live demo"


def test_media_text_paths_share_the_paste_cap():
    # the transcript field and a .txt upload feed the same extractor as the paste box; they share its cap
    cid = open_case()
    r = client.post(f"/api/cases/{cid}/media",
                    files={"file": ("note.txt", b"short file", "text/plain")},
                    data={"derived_text": "a" * (api.MAX_TEXT_CHARS + 1)})
    assert r.status_code == 413 and "too long" in r.json()["detail"]
    big_txt = b"a" * (api.MAX_TEXT_CHARS * 4 + 1)
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("dump.txt", big_txt, "text/plain")})
    assert r.status_code == 413 and "too long" in r.json()["detail"]
    assert not (api.UPLOADS / cid / "dump.txt").exists()


# ---------- RED release co-sign hygiene ----------

def _red_case() -> str:
    r = client.post("/api/scenarios/S1-rm-voice-note/run")
    assert r.status_code == 200 and r.json()["case"]["verdict"]["outcome"] == "RED"
    return r.json()["case"]["id"]


def test_red_release_self_co_sign_is_refused():
    cid = _red_case()
    for co in ("officer.bhawna", "  officer.bhawna  ", "Officer.Bhawna", "", "   ", None):
        r = client.post(f"/api/cases/{cid}/decide", json={"actor": "officer.bhawna", "action": "release", "note": "", "co_signer": co})
        assert r.status_code == 403, f"co_signer={co!r}"
    case = client.get(f"/api/cases/{cid}").json()["case"]
    assert case["status"] == "open" and case["decisions"] == []


def test_red_release_with_a_second_person_succeeds():
    cid = _red_case()
    r = client.post(f"/api/cases/{cid}/decide", json={"actor": "officer.bhawna", "action": "release", "note": "", "co_signer": "manager.verma"})
    assert r.status_code == 200
    assert r.json()["case"]["status"] == "released"


def test_unknown_decision_action_is_422():
    cid = open_case()
    r = client.post(f"/api/cases/{cid}/decide", json={"actor": "officer.bhawna", "action": "approve_all", "note": "", "co_signer": None})
    assert r.status_code == 422
    assert "not a decision" in r.json()["detail"]
    assert client.get(f"/api/cases/{cid}").json()["case"]["decisions"] == []


# ---------- SPA catch-all containment ----------

needs_dist = pytest.mark.skipif(not api.DIST.exists(), reason="console/dist not built; SPA route not mounted")

PYPROJECT_MARKER = b"[build-system]"   # a string that is in pyproject.toml and in no served console file


@needs_dist
def test_spa_traversal_encoded_slash_is_404():
    r = client.get("/..%2F..%2Fpyproject.toml")
    assert r.status_code == 404
    assert PYPROJECT_MARKER not in r.content


@needs_dist
def test_spa_traversal_plain_dotdot_is_404():
    status, body = raw_get("/../../pyproject.toml")
    assert status == 404
    assert PYPROJECT_MARKER not in body


@needs_dist
def test_spa_null_byte_path_is_404_not_500():
    status, body = raw_get("/\x00")
    assert status == 404
    assert PYPROJECT_MARKER not in body


@needs_dist
def test_spa_still_serves_index_for_app_routes():
    r = client.get("/cases/some-case-id")
    assert r.status_code == 200
    assert b"<!doctype html" in r.content.lower()


@needs_dist
def test_unknown_api_path_is_404_json_not_index_html():
    for path in ("/api/no-such-endpoint", "/api"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert b"<!doctype html" not in r.content.lower()


# ---------- demo reset ----------

def test_demo_reset_clears_cases_but_not_fixture_memory():
    fixture_entries = len(client.get("/api/memory").json()["entries"])
    open_case()
    assert client.get("/api/cases").json() != []
    r = client.post("/api/demo/reset")
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True
    assert out["cases_cleared"] == 1
    assert client.get("/api/cases").json() == []
    # fixture campaign memory survives a reset
    assert len(client.get("/api/memory").json()["entries"]) == fixture_entries


# ---------- case list summary ----------

def test_case_list_summary_carries_about():
    # A case opened from a scenario carries the scenario title, so two cases with the same bank flag read apart.
    r = client.post("/api/scenarios/S1-rm-voice-note/run")
    assert r.status_code == 200
    scenario_case = r.json()["case"]["id"]
    # A hand-opened case falls back to the claimed issuer once the claim exists.
    cid = open_case()
    client.post(f"/api/cases/{cid}/picklist", json={"issuer": "ED", "instruction": "TRANSFER_TO_ACCOUNT"})
    assert client.post(f"/api/cases/{cid}/run").status_code == 200
    rows = {row["id"]: row for row in client.get("/api/cases").json()}
    assert rows[scenario_case]["about"] == "Cloned 'bank RM' voice note (Hindi), from an unknown number"
    assert rows[cid]["about"] == "claims ED"
    # With no scenario and no claim, the field is present and null.
    bare = open_case()
    assert {row["id"]: row for row in client.get("/api/cases").json()}[bare]["about"] is None


# ---------- session timing in /api/meta ----------

def test_meta_session_timing_counts_runs():
    assert client.get("/api/meta").json()["session_timing"]["count"] == 0
    sids = [s["id"] for s in client.get("/api/scenarios").json()][:2]
    assert len(sids) == 2
    for sid in sids:
        assert client.post(f"/api/scenarios/{sid}/run").status_code == 200
    timing = client.get("/api/meta").json()["session_timing"]
    assert timing["count"] == 2
    assert 0 < timing["session_p50_verdict_ms"] < 60_000   # plausible for a local run
