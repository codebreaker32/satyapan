"""Nobody is nobody, whatever it is spelled with.

The pass-4 adversarial gate signed a decision as U+200B and, worse, released a RED case with a zero-width space
as the co-signer: one officer defeating the four-eyes rule alone, which is a stated design invariant.
`"​".isspace()` is False, so it survived `str.strip()` and satisfied every check the engine had.

`models.visible_name` is the one answer: a name with no visible glyph is nobody. These tests pin it at the three
places it has to hold — the co-sign, the decision actor, and the two-person campaign-memory rule. The probes are
written as escapes on purpose, because a reviewer has to be able to see what is being tried.
"""
from __future__ import annotations

import pytest

from satyapan.models import visible_name
from tests.conftest import run_scenario_id

INVISIBLE = [
    "​",              # zero-width space — the one that released a RED case alone
    "﻿",              # byte order mark
    "⁠",              # word joiner
    "‎",              # left-to-right mark
    "‍",              # zero-width joiner
    "­",              # soft hyphen
    "​ ﻿",       # and in company
    "\x01",                # a control character
]
BLANK = ["", "   ", "\t", "\n", " ", None]


@pytest.mark.parametrize("value", INVISIBLE + BLANK)
def test_a_name_with_no_visible_glyph_is_nobody(value):
    assert visible_name(value) is None


@pytest.mark.parametrize("value, want", [
    ("officer.bhawna", "officer.bhawna"),
    ("  officer.bhawna  ", "officer.bhawna"),
    ("अधिकारी.भावना", "अधिकारी.भावना"),
    ("officer​.bhawna", "officer.bhawna"),   # an invisible inside a real name goes, the name survives
    ("A", "A"),
])
def test_a_real_name_survives(value, want):
    assert visible_name(value) == want


@pytest.mark.parametrize("ghost", INVISIBLE)
def test_an_invisible_co_signer_cannot_release_a_red_alone(engine, ghost):
    """The gate's worst finding: four eyes satisfied by one officer and a zero-width space."""
    case = run_scenario_id(engine, "S3-ed-summons")
    assert case.verdict.outcome.value == "RED"
    with pytest.raises(PermissionError, match="co-sign"):
        engine.decide(case, actor="officer.bhawna", action="release", note="", co_signer=ghost)
    assert case.status != "released"
    assert not any(d.action == "release" for d in case.decisions)


def test_a_real_co_signer_still_releases(engine):
    """The guard must not break the control it protects."""
    case = run_scenario_id(engine, "S3-ed-summons")
    engine.decide(case, actor="officer.bhawna", action="release", note="", co_signer="manager.rekha")
    assert case.status == "released"
    assert "manager.rekha" in case.decisions[-1].note


def _client():
    from fastapi.testclient import TestClient

    from satyapan.api import app
    return TestClient(app)


def _open_case(c) -> str:
    flag = {"reason": "probe", "amount_inr": 0, "customer_ref": "cust-demo", "channel": "branch"}
    return c.post("/api/cases", json={"flag": flag}).json()["case"]["id"]


@pytest.mark.parametrize("ghost", INVISIBLE)
def test_an_invisible_actor_cannot_record_a_decision_through_the_api(ghost):
    c = _client()
    cid = _open_case(c)
    r = c.post(f"/api/cases/{cid}/decide", json={"actor": ghost, "action": "hold", "note": ""})
    assert r.status_code == 422, r.text
    assert "staff id" in r.json()["detail"]
    assert c.get(f"/api/cases/{cid}").json()["case"]["decisions"] == []


def test_an_invisible_analyst_cannot_propose_to_campaign_memory():
    """A campaign-memory entry reached `confirmed` under the two-person rule with two invisible analysts."""
    c = _client()
    cid = c.post("/api/scenarios/S3-ed-summons/run").json()["case"]["id"]   # propose needs a case that has run
    r = c.post("/api/memory/propose", json={"case_id": cid, "analyst": "​", "note": ""})
    assert r.status_code == 422, r.text
    assert "staff id" in r.json()["detail"]


def test_an_invisible_analyst_cannot_approve_a_memory_entry():
    c = _client()
    r = c.post("/api/memory/CM-0001/approve", json={"analyst": "﻿"})
    assert r.status_code == 422, r.text
    assert "staff id" in r.json()["detail"]
