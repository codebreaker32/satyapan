"""The labelled evaluation (`satyapan evaluate`, satyapan/evaluate.py): the invariant it must hold and the drift it
must not hide. The set is synthetic and the report says so; these tests keep both of those true."""
from __future__ import annotations

import json

import pytest

from satyapan.evaluate import LABELLED, REPORT, RESULTS, SYNTHETIC, run_evaluation

OPTIONAL_LAYERS = ("audio_detector", "meaning_model", "website_registry", "reader")


@pytest.fixture(scope="module")
def result() -> dict:
    return run_evaluation()


def test_no_genuine_message_is_ever_stopped(result):
    """A RED on a genuine message tells a customer to stop her own payment. AMBER (verify first) is allowed and
    counted in the report; a RED is not allowed at all."""
    assert result["summary"]["false_stops"] == []


def test_the_labelled_set_is_well_formed():
    msgs = json.loads(LABELLED.read_text(encoding="utf-8"))["messages"]
    ids = [m["id"] for m in msgs]
    assert len(ids) == len(set(ids)), "duplicate ids in data/eval/labelled.json"
    for m in msgs:
        assert m["label"] in ("scam", "genuine") and m["text"].strip() and m["category"], m["id"]
        if m["label"] == "scam":
            assert isinstance(m.get("in_scope"), bool), f"{m['id']}: a scam must say whether it is in scope"


def test_every_message_is_counted_exactly_once(result):
    rows = result["rows"]
    assert result["summary"]["total"] == len(rows) == len({r["id"] for r in rows})
    s = result["summary"]
    assert s["in_scope_scams"]["n"] + s["genuine"]["n"] + s["out_of_scope_scams"]["n"] == len(rows)


def test_the_committed_report_matches_a_fresh_run(result):
    """The numbers judges read are the numbers the engine gives today. Compared only when the same optional layers
    are installed (an install without the models gives different, equally honest numbers); a rule change that moves
    a verdict fails here until `satyapan evaluate` is run again."""
    if not RESULTS.exists():
        pytest.skip("no committed results yet: run `satyapan evaluate`")
    committed = json.loads(RESULTS.read_text(encoding="utf-8"))
    if any(committed["environment"].get(k) != result["environment"].get(k) for k in OPTIONAL_LAYERS):
        pytest.skip("different optional models installed than when the committed report was made")
    assert committed["summary"] == result["summary"], "the engine's verdicts moved: run `satyapan evaluate`"


def test_the_report_says_it_is_synthetic():
    assert SYNTHETIC in REPORT.read_text(encoding="utf-8")
