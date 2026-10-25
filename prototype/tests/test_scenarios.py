"""End-to-end: every demo scenario produces its expected verdict."""
import pytest

from satyapan.models import Family, Issuer, Outcome, Severity
from tests.conftest import SCENARIOS, run_scenario_id, signal


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_scenario_outcome(engine, sid):
    case = run_scenario_id(engine, sid)
    assert case.verdict.outcome.value == SCENARIOS[sid]["expect"], case.verdict.explanation


def test_forensics_abstaining_does_not_move_the_verdict(engine):
    sc = SCENARIOS["S1-rm-voice-note"]
    case = run_scenario_id(engine, sc["id"])
    before = (case.verdict.outcome, case.verdict.anchor_rule, case.verdict.second_family)
    f3 = [s for s in case.verdict.signals if s.family == Family.F3]
    assert f3 and f3[0].severity == Severity.SOFT and f3[0].detail["simulated"] is True
    engine.simulate_forensics(case, sc["then_forensics"])
    engine.run(case)
    f3 = [s for s in case.verdict.signals if s.family == Family.F3]
    assert f3 and f3[0].severity == Severity.ABSTAIN
    assert (case.verdict.outcome, case.verdict.anchor_rule, case.verdict.second_family) == before


def test_prompt_injection_changes_nothing(engine):
    a = run_scenario_id(engine, "S3-ed-summons").verdict
    b = run_scenario_id(engine, "S5d-injection").verdict
    assert (a.outcome, a.anchor_rule, a.second_family) == (b.outcome, b.anchor_rule, b.second_family)


def test_claim_only_is_fast_and_red(engine):
    import time
    t = time.perf_counter()
    case = run_scenario_id(engine, "S4-claim-only")
    assert time.perf_counter() - t < 2.0
    assert case.verdict.outcome == Outcome.RED
    assert signal(case, "R-BANK-SELF") is None, "claim-only mode never consults the outbound log"


def test_negative_controls_do_not_alarm(engine):
    expected = {"S5e-genuine-sms-1600": Outcome.MATCHES, "S5f-court-hearing-notice": Outcome.GREY,
                "S5g-it-refund-processed": Outcome.GREY, "S5h-it-refund-probe": Outcome.GREY}
    for sid, want in expected.items():
        case = run_scenario_id(engine, sid)
        assert case.verdict.outcome == want, (sid, case.verdict.explanation)


def test_it_refund_probe_is_not_a_bank_claim(engine):
    case = run_scenario_id(engine, "S5h-it-refund-probe")
    assert case.claim.claimed_issuer == Issuer.NONE, "'your bank account' must not read as the bank claiming to speak"
    assert signal(case, "R-BANK-SELF") is None and signal(case, "R-CALLER-1600") is None
    assert case.verdict.outcome == Outcome.GREY


def test_lone_hard_rule_gives_amber_never_red(engine):
    case = run_scenario_id(engine, "S8-rbi-bond-no-payee")
    v = case.verdict
    assert v.outcome == Outcome.AMBER
    assert v.anchor_rule == "R-RBI-INV"
    assert v.second_family is None
    assert "One rule alone never gives RED" in v.explanation
    # What makes this the lone-hard-rule branch and not something weaker: every other signal on the case is F5,
    # the one family that can never second. The same-family soft pairs (hard+soft and soft+soft on F1) are
    # unit-tested in tests/test_fusion.py; no scenario carries one since R-CALLER-1600 stopped being a sentence
    # about regulators.
    others = [s for s in v.signals if s.rule_id != v.anchor_rule]
    assert others and all(s.family == Family.F5 for s in others), [s.rule_id for s in others]


def test_red_always_rests_on_two_families(engine):
    for sid, sc in SCENARIOS.items():
        case = run_scenario_id(engine, sid)
        if case.verdict.outcome == Outcome.RED:
            a = signal(case, case.verdict.anchor_rule)
            b = signal(case, case.verdict.second_family)
            assert a.family != b.family and a.evidence_key != b.evidence_key and b.family != Family.F5
