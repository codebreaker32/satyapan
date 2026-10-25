"""The four-eyes rules hold whatever a name is spelled with, and a strike is not a way around them.

Regressions, each reproduced in-process before the fix:
- Strike a field on a RED case, it re-runs AMBER or GREY, and the same officer releases it alone.
- Blank-looking names (Hangul fillers, the Braille blank, a lone variation selector) passed as a co-signer.
- The officer's own id with a Cyrillic letter, full-width letters or an invisible mark passed as a second person.
- One analyst confirmed their own campaign-memory entry by retyping their id in another case.
- A re-run (re-encode, run again) re-extracted a struck field while the signed log said the strike stood.
- A strike of a field the claim does not have, or of an unknown field, was recorded as if it happened.
- Approving an unknown memory entry gave HTTP 500.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from satyapan import api
from satyapan.memory import CampaignMemory
from satyapan.models import Issuer, Outcome, identity_key, visible_name
from tests.conftest import DATA_DIR, run_scenario_id

BLANK_LOOKING = ["ㅤ", "⠀", "ﾠ", "ᅟ", "️", "͏"]
SAME_PERSON = ["оfficer.bhawna",            # Cyrillic о
               "officer.bhаwna",            # Cyrillic а
               "officer.bhawna️",           # variation selector
               "officer.bhawna͏",           # combining grapheme joiner
               "ｏｆｆｉｃｅｒ.ｂｈａｗｎａ",   # full width
               "OFFICER.BHAWNA", "officer.bhawna"]


@pytest.mark.parametrize("value", BLANK_LOOKING)
def test_blank_looking_names_are_nobody(value):
    assert visible_name(value) is None


@pytest.mark.parametrize("value", ["officer.bhawna", "अधिकारी.भावना", "manager.2", "रेखा"])
def test_real_names_survive(value):
    assert visible_name(value) == value


@pytest.mark.parametrize("value", SAME_PERSON)
def test_the_same_person_written_differently_has_one_identity(value):
    assert identity_key(value) == identity_key("officer.bhawna")


def test_different_people_stay_different():
    assert identity_key("officer.bhawna") != identity_key("manager.rekha")


@pytest.mark.parametrize("co", BLANK_LOOKING + SAME_PERSON)
def test_red_release_refuses_a_blank_or_same_person_co_signer(engine, co):
    case = run_scenario_id(engine, "S3-ed-summons")
    assert case.verdict.outcome is Outcome.RED
    with pytest.raises(PermissionError):
        engine.decide(case, actor="officer.bhawna", action="release", co_signer=co)
    engine.decide(case, actor="officer.bhawna", action="release", co_signer="manager.rekha")
    assert case.status == "released"


@pytest.mark.parametrize("sid, field", [("S4-claim-only", "account"), ("S10b-echallan-paid-to-person", "instruction"),
                                        ("S1-rm-voice-note", "issuer")])
def test_a_strike_does_not_let_one_officer_release_a_red_alone(engine, sid, field):
    case = run_scenario_id(engine, sid)
    assert case.verdict.outcome is Outcome.RED
    engine.strike_field(case, field, "officer.bhawna")
    assert case.verdict.outcome is not Outcome.RED
    assert case.decisions[-1].note == f"struck {field} on a RED case"
    with pytest.raises(PermissionError):
        engine.decide(case, actor="officer.bhawna", action="release")
    engine.decide(case, actor="officer.bhawna", action="release", co_signer="manager.rekha")
    assert "officer released a case that was RED before a field was struck" in engine.review_triggers(case)


def test_a_release_after_a_strike_on_a_non_red_case_needs_no_co_sign(engine):
    case = run_scenario_id(engine, "S5c-ed-summons-1h-old")
    assert case.verdict.outcome is not Outcome.RED
    field = "issuer" if case.claim.claimed_issuer is not Issuer.NONE else "instruction"
    engine.strike_field(case, field, "officer.bhawna")
    engine.decide(case, actor="officer.bhawna", action="release")
    assert case.status == "released"


def test_a_strike_survives_a_later_run(engine):
    case = run_scenario_id(engine, "S1-rm-voice-note")
    engine.strike_field(case, "issuer", "officer.bhawna")
    assert case.claim.claimed_issuer is Issuer.NONE
    engine.run(case)
    assert case.claim.claimed_issuer is Issuer.NONE, "a re-run must not bring a struck field back"


def test_an_absent_or_unknown_field_cannot_be_struck(engine):
    case = run_scenario_id(engine, "S6-fake-credit")
    assert case.claim.claimed_issuer is Issuer.NONE
    before = list(case.decisions)
    for field in ("issuer", "amount_inr"):
        with pytest.raises(ValueError):
            engine.strike_field(case, field, "officer.bhawna")
    assert case.decisions == before


def test_strike_api_refuses_an_absent_field_with_422():
    c = TestClient(api.app)
    cid = c.post("/api/scenarios/S6-fake-credit/run").json()["case"]["id"]
    r = c.post(f"/api/cases/{cid}/strike", json={"field": "issuer", "actor": "officer.bhawna"})
    assert r.status_code == 422 and "no issuer" in r.json()["detail"]


def test_case_view_says_when_a_release_needs_a_co_sign():
    c = TestClient(api.app)
    view = c.post("/api/scenarios/S10b-echallan-paid-to-person/run").json()
    assert view["inputs"]["release_needs_co_sign"] is True
    view = c.post(f"/api/cases/{view['case']['id']}/strike", json={"field": "instruction", "actor": "officer.bhawna"}).json()
    assert view["case"]["verdict"]["outcome"] != "RED"
    assert view["inputs"]["release_needs_co_sign"] is True


@pytest.mark.parametrize("second", ["Analyst.Aman", "ANALYST.AMAN", "аnalyst.aman", "analyst.aman͏"])
def test_one_analyst_cannot_confirm_their_own_memory_entry(engine, tmp_path, second):
    memory = CampaignMemory(tmp_path / "memory.json", now=engine.clock())
    case = run_scenario_id(engine, "S3-ed-summons")
    e = memory.propose(case.claim, "analyst.aman")
    e = memory.approve(e["id"], second)
    assert e["status"] == "pending" and e["approvals"] == ["analyst.aman"]
    e = memory.approve(e["id"], "analyst.bhawna")
    assert e["status"] == "confirmed"


def test_approving_an_unknown_memory_entry_is_404_not_500():
    r = TestClient(api.app).post("/api/memory/CM-9999/approve", json={"analyst": "analyst.aman"})
    assert r.status_code == 404 and "CM-9999" in r.json()["detail"]
