"""Demotion-to-soft of rules with unverified citations (the docs/finale-qa.md Q6 safety claim).

`rulebook.load_rulebook` flips a `hard` rule to `soft` at load time when its citation lacks
`verified: true`, so such a rule can never anchor a RED. Every shipped rule is verified, so a
regression in that branch is invisible to the scenario tests; here the engine runs over a copy
of `data/` with exactly one citation flipped to `verified: false`.
"""
import shutil

import pytest
import yaml

from satyapan.models import Flag, Outcome, Severity
from satyapan.pipeline import DATA_DIR, Satyapan
from tests.conftest import NOW, signal

# A voice note whose only hard rule is R-AGENCY-PAY (no payee owner claim, account not in any mock;
# same text tests/test_rules.py::test_agency_pay proves fires the rule), corroborated by a SIMULATED
# synthetic-audio result (F3, independent family and evidence) so the shipped rulebook gives RED.
TEXT = "CBI officer here. You are under digital arrest. Transfer Rs 2,00,000 to account 99887766554433 now."
FORENSICS_SIM = {"kind": "audio", "status": "synthetic", "band": "moderate", "score": 2.1, "cell": "hi/whatsapp-opus"}


def run_voice_note(engine: Satyapan):
    case = engine.open_case(Flag(reason="FD closure + RTGS to first-time payee", amount_inr=500000, customer_ref="cust-demo"))
    engine.set_consent(case, check=True)
    engine.add_text(case, TEXT, source="transcript", kind="audio", filename="voice_note.ogg")
    engine.simulate_forensics(case, FORENSICS_SIM)
    return engine.run(case)


@pytest.fixture
def demoted_data_dir(tmp_path):
    """A copy of the shipped data dir with R-AGENCY-PAY's citation set to verified: false."""
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR, data)
    book_path = data / "rules" / "rulebook.yaml"
    doc = yaml.safe_load(book_path.read_text(encoding="utf-8"))
    r = next(x for x in doc["rules"] if x["id"] == "R-AGENCY-PAY")
    assert r["severity"] == "hard" and r["citation"]["verified"] is True  # the shipped premise
    r["citation"]["verified"] = False
    book_path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return data


def test_shipped_rulebook_anchors_red_on_agency_pay(engine):
    # The premise: with the shipped (all-verified) rulebook this case is RED anchored on R-AGENCY-PAY.
    case = run_voice_note(engine)
    assert case.verdict.outcome == Outcome.RED
    assert case.verdict.anchor_rule == "R-AGENCY-PAY"
    assert signal(case, "R-AGENCY-PAY").severity == Severity.HARD


def test_unverified_citation_is_demoted_to_soft_at_load(demoted_data_dir, tmp_path):
    engine = Satyapan(demoted_data_dir, now=NOW, state_dir=tmp_path / "state")
    meta = engine.book.meta("R-AGENCY-PAY")
    # The marker load_rulebook records: severity flipped hard -> soft; the citation stays unverified.
    assert meta.severity == Severity.SOFT
    assert meta.citation.verified is False
    # Only the edited rule is demoted; the rest of the book is untouched.
    assert engine.book.meta("R-BANK-SELF").severity == Severity.HARD
    assert engine.book.meta("R-BANK-SELF").citation.verified is True


def test_demoted_rule_never_anchors_red(demoted_data_dir, tmp_path):
    engine = Satyapan(demoted_data_dir, now=NOW, state_dir=tmp_path / "state")
    case = run_voice_note(engine)
    v = case.verdict

    # Without the hard anchor, the same case fuses to AMBER on two independent softs, never RED.
    assert v.outcome == Outcome.AMBER
    assert v.anchor_rule is None
    # The explanation is prose, so it names the two rules by their rulebook titles; the ids stay on the signals,
    # which is what the case record and the signed pack carry (tests/test_no_rule_ids_in_prose.py).
    assert "A state authority demands a payment" in v.explanation
    assert "Signs of synthetic speech" in v.explanation
    assert {"R-AGENCY-PAY", "R-AUDIO-SYNTH"} <= {s.rule_id for s in v.signals}

    # Payload level: this Signal is what api.case_view serialises (case.model_dump inside the case view),
    # and console/src/ui/check.tsx renders "citation not yet verified, demoted to soft" whenever a signal
    # arrives with citation_verified false. A TestClient round trip would need api.py's module-level
    # engine (built over the shipped data dir), which this test must not touch, so assert at model level.
    s = signal(case, "R-AGENCY-PAY")
    assert s is not None
    assert s.severity == Severity.SOFT
    assert s.citation_verified is False
