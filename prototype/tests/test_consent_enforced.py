"""Consent is enforced by the service, not only by the browser (bug hunt raw findings 19 and 31).

C2 (may we include it in a report) was recorded and never read: help_report was accepted and signed next to
consent.report=false. C1 (may we check it) was enforced only by the console's new-case form.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from satyapan import api
from tests.conftest import run_scenario_id

client = TestClient(api.app)
ED = "This is the Enforcement Directorate. Transfer Rs 50,000 to account 50100248891776 IFSC SBIN0001234."


def case_with(check: bool | None, report: bool = False) -> str:
    cid = client.post("/api/cases", json={"flag": {"reason": "t", "amount_inr": 1000, "customer_ref": "x"}}).json()["case"]["id"]
    if check is not None:
        client.post(f"/api/cases/{cid}/consent", json={"check": check, "report": report, "memory": False, "lang": "en"})
    client.post(f"/api/cases/{cid}/text", json={"text": ED})
    return cid


def test_help_report_needs_c2():
    cid = case_with(check=True, report=False)
    assert client.post(f"/api/cases/{cid}/run").status_code == 200
    r = client.post(f"/api/cases/{cid}/decide", json={"actor": "officer.bhawna", "action": "help_report", "note": "x"})
    assert r.status_code == 403 and "C2" in r.json()["detail"]
    assert client.get(f"/api/cases/{cid}").json()["case"]["decisions"] == []


def test_help_report_with_c2_is_recorded():
    cid = case_with(check=True, report=True)
    client.post(f"/api/cases/{cid}/run")
    r = client.post(f"/api/cases/{cid}/decide", json={"actor": "officer.bhawna", "action": "help_report", "note": "x"})
    assert r.status_code == 200


@pytest.mark.parametrize("check", [None, False])
def test_a_run_needs_c1(check):
    cid = case_with(check=check)
    r = client.post(f"/api/cases/{cid}/run")
    assert r.status_code == 403 and "C1" in r.json()["detail"]


def test_engine_refuses_help_report_without_c2(engine):
    case = run_scenario_id(engine, "S3-ed-summons")
    case.consent.report = False
    with pytest.raises(PermissionError):
        engine.decide(case, actor="officer.bhawna", action="help_report")
