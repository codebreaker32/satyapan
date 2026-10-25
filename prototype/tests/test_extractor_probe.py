"""A floor under a set of extractor changes: 86 synthetic messages that probe them from both sides.

Written for an independent before/after probe of those changes; that probe found two regressions, which were
fixed, and the set is kept so a later change cannot quietly bring them back. It pins floors, not exact verdicts,
so an improvement never fails it: a genuine message is never RED, and a scam that is flagged today stays flagged.
Scams that are GREY today ('known_gap') are listed in the fixture and not asserted.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from satyapan.models import Outcome
from tests.conftest import run_text

PROBE = json.loads((Path(__file__).parent / "fixtures" / "extractor_probe.json").read_text(encoding="utf-8"))["messages"]


@pytest.mark.parametrize("m", [m for m in PROBE if m["floor"] != "known_gap"], ids=lambda m: m["id"])
def test_extractor_probe_floor(engine, m):
    outcome = run_text(engine, m["text"]).verdict.outcome
    if m["floor"] == "not_red":
        assert outcome is not Outcome.RED, m["text"]
    else:
        assert outcome in (Outcome.AMBER, Outcome.RED), m["text"]
