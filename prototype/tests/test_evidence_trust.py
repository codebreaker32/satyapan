"""Verification trusts the bank's own evidence key, never the key a pack carries inside itself.

Bug hunt, finding 29 (critical): a pack whose verdict was changed to MATCHES, with its decisions replaced, re-signed
with a fresh key and posted to /api/evidence/verify came back "Verifies.", because verify_pack checked the signature
against the public key written in the pack. Finding 35: a null, empty or list signature gave HTTP 500.

The byte-flip moment (beat 8) must keep working: a fresh pack verifies, one flipped manifest byte fails.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from satyapan import api
from satyapan.cli import flip_manifest_byte
from satyapan.evidence import LocalSigner, make_pack, verify_pack
from tests.conftest import run_scenario_id


def forged(engine, tmp_path):
    pack = engine.evidence_pack(run_scenario_id(engine, "S3-ed-summons"))
    manifest = copy.deepcopy(pack["manifest"])
    manifest["case"]["verdict"]["outcome"] = "MATCHES"
    bad = make_pack(manifest, LocalSigner(tmp_path / "attacker"))
    bad["signature"]["signer"] = pack["signature"]["signer"]
    return pack, bad


def test_pack_resigned_with_another_key_is_refused(engine, tmp_path):
    pack, bad = forged(engine, tmp_path)
    key = engine.signer.public_key_b64()
    assert verify_pack(bad)[0], "internally consistent: only the trusted key can catch it"
    ok, reason = verify_pack(bad, key)
    assert not ok and "not this bank's evidence key" in reason
    assert verify_pack(pack, key)[0]


def test_byte_flip_still_fails_and_restore_verifies(engine):
    pack = engine.evidence_pack(run_scenario_id(engine, "S1-rm-voice-note"))
    key = engine.signer.public_key_b64()
    assert verify_pack(pack, key)[0]
    assert not verify_pack(flip_manifest_byte(pack), key)[0]


def test_api_refuses_a_forged_pack_and_accepts_its_own(tmp_path):
    client = TestClient(api.app)
    case = run_scenario_id(api.engine, "S3-ed-summons")
    pack = api.engine.evidence_pack(case)
    assert client.post("/api/evidence/verify", json=pack).json()["ok"] is True
    manifest = copy.deepcopy(pack["manifest"])
    manifest["case"]["verdict"]["outcome"] = "MATCHES"
    bad = make_pack(manifest, LocalSigner(tmp_path / "attacker"))
    body = client.post("/api/evidence/verify", json=bad).json()
    assert body["ok"] is False and "not this bank's evidence key" in body["reason"]


@pytest.mark.parametrize("signature", [None, "", [], {}, {"alg": "Ed25519"}, {"alg": None, "value": "x"}])
def test_missing_or_odd_signature_is_a_sentence_not_a_500(signature):
    client = TestClient(api.app)
    pack = api.engine.evidence_pack(run_scenario_id(api.engine, "S4-claim-only"))
    pack["signature"] = signature
    r = client.post("/api/evidence/verify", json=pack)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "None" not in body["reason"] and body["reason"][0].isupper()
