import base64
import copy

from satyapan.evidence import load_pack, save_pack, verify_pack
from tests.conftest import run_scenario_id


def test_pack_verifies_and_carries_the_case(engine):
    case = run_scenario_id(engine, "S3-ed-summons")
    pack = engine.evidence_pack(case)
    ok, reason = verify_pack(pack)
    assert ok, reason
    m = pack["manifest"]
    assert m["case"]["verdict"]["outcome"] == "RED"
    assert m["rulebook"]["sha256"] and m["policy_version"]
    assert any(a["mock"] for a in m["adapters"]), "mocked integrations are labelled in the pack"
    assert m["case"]["media"][0]["sha256"]


def test_tampered_manifest_fails(engine):
    pack = engine.evidence_pack(run_scenario_id(engine, "S3-ed-summons"))
    bad = copy.deepcopy(pack)
    bad["manifest"]["case"]["verdict"]["outcome"] = "MATCHES"
    ok, reason = verify_pack(bad)
    assert not ok and "altered" in reason


def test_one_flipped_signature_byte_fails(engine):
    pack = engine.evidence_pack(run_scenario_id(engine, "S1-rm-voice-note"))
    raw = bytearray(base64.b64decode(pack["signature"]["value"]))
    raw[0] ^= 0x01
    bad = copy.deepcopy(pack)
    bad["signature"]["value"] = base64.b64encode(bytes(raw)).decode()
    ok, reason = verify_pack(bad)
    assert not ok and "signature" in reason


def test_save_load_roundtrip(engine, tmp_path):
    pack = engine.evidence_pack(run_scenario_id(engine, "S4-claim-only"))
    p = tmp_path / "pack.json"
    save_pack(pack, p)
    assert verify_pack(load_pack(p))[0]


def test_release_of_red_needs_co_sign(engine):
    import pytest
    case = run_scenario_id(engine, "S3-ed-summons")
    with pytest.raises(PermissionError):
        engine.decide(case, actor="officer.1", action="release")
    engine.decide(case, actor="officer.1", action="release", co_signer="manager.2")
    assert case.status == "released" and "co-signed" in case.decisions[-1].note
    assert "officer released a RED case" in engine.review_triggers(case)


def test_pack_survives_a_javascript_json_round_trip(engine):
    """Browsers and case systems re-serialise 3800000.0 as 3800000; verification must not depend on that."""
    import json
    case = run_scenario_id(engine, "S3-ed-summons")
    pack = engine.evidence_pack(case)
    assert float(case.flag.amount_inr).is_integer()
    text = json.dumps(pack).replace("3800000.0", "3800000")
    assert "3800000.0" not in text
    ok, reason = verify_pack(json.loads(text))
    assert ok, reason
    tampered = json.loads(text)
    tampered["manifest"]["case"]["flag"]["amount_inr"] += 1
    assert verify_pack(tampered)[0] is False
