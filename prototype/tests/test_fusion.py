import pytest

from satyapan.fusion import HEADLINES, HEADLINES_NO_PAYMENT, fuse, money_in_play
from satyapan.models import Claim, ClaimedOwner, Family, Instruction, Issuer, Outcome, Payee, Severity, Signal


def sig(rule, fam, sev, key, **detail):
    d = {"can_be_second": True} | detail
    return Signal(rule_id=rule, family=fam, severity=sev, evidence_key=key, reason_en="r", reason_hi="र", citation="c",
                  citation_verified=True, escalate_alone=detail.get("escalate_alone", False), detail=d)


CLAIM = Claim(source="text", text="x", claimed_issuer=Issuer.CBI, instruction=Instruction.TRANSFER_TO_ACCOUNT)
# The same message with the money half missing: no instruction, no payee. Every RED test above uses CLAIM, which
# carries an instruction, so the money gate is out of their way on purpose.
NO_MONEY = Claim(source="text", text="x", claimed_issuer=Issuer.CBI, instruction=Instruction.NONE)
EMPTY = Claim(source="text", text="")


def test_red_needs_two_families_on_different_evidence():
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.HARD, "claim"), sig("B", Family.F2, Severity.SOFT, "bank:name_lookup")])
    assert v.outcome == Outcome.RED and v.anchor_rule == "A" and v.second_family == "B"


def test_red_needs_a_money_demand_to_have_been_read():
    """Same two families, same evidence, but nothing about money was read: AMBER, not RED.
    Stated here with the other fusion invariants; `tests/test_no_red_without_money.py` holds the full set."""
    pair = [sig("A", Family.F1, Severity.HARD, "claim"), sig("B", Family.F2, Severity.SOFT, "bank:name_lookup")]
    v = fuse(NO_MONEY, pair)
    assert v.outcome == Outcome.AMBER and v.anchor_rule == "A" and v.second_family is None


def test_two_hard_rules_same_family_is_amber():
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.HARD, "claim"), sig("B", Family.F1, Severity.HARD, "issuer:ed_portal")])
    assert v.outcome == Outcome.AMBER


def test_a_soft_rule_from_the_anchor_family_never_seconds_it():
    """A hard rule plus a soft one from the same family, on different evidence, is still one family: AMBER.

    S8 used to carry this shape live (R-RBI-INV hard F1 plus R-CALLER-1600 soft F1) and
    tests/test_scenarios.py asserted it there. The pass-6 build scoped R-CALLER-1600 to messages claiming to be
    a bank, which is correct and left no scenario carrying the shape, so the invariant is pinned here instead.
    """
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.HARD, "claim"), sig("B", Family.F1, Severity.SOFT, "issuer:ed_portal")])
    assert v.outcome == Outcome.AMBER and v.anchor_rule == "A" and v.second_family is None


def test_same_evidence_never_counts_twice():
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.HARD, "bank:name_lookup"), sig("B", Family.F2, Severity.HARD, "bank:name_lookup")])
    assert v.outcome == Outcome.AMBER


def test_f5_is_never_the_second_family():
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.HARD, "claim"), sig("P", Family.F5, Severity.SOFT, "claim2", can_be_second=False)])
    assert v.outcome == Outcome.AMBER


def test_forensics_can_be_second_but_never_anchor():
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.HARD, "claim"), sig("F", Family.F3, Severity.SOFT, "media:audio")])
    assert v.outcome == Outcome.RED


def test_forensics_alone_is_amber():
    assert fuse(CLAIM, [sig("F", Family.F3, Severity.SOFT, "media:audio")]).outcome == Outcome.AMBER


def test_video_forensics_alone_is_amber():
    """R-VIDEO-SYNTH (the GenD face check) is F3 like the voice check: alone it never goes above AMBER."""
    assert fuse(CLAIM, [sig("R-VIDEO-SYNTH", Family.F3, Severity.SOFT, "media:video")]).outcome == Outcome.AMBER


def test_video_forensics_can_second_a_cited_rule():
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.HARD, "claim"), sig("R-VIDEO-SYNTH", Family.F3, Severity.SOFT, "media:video")])
    assert v.outcome == Outcome.RED and v.second_family == "R-VIDEO-SYNTH"


def test_face_and_voice_checks_together_are_still_one_family():
    """A video's face flag and voice flag are both F3: together they are not two independent checks."""
    v = fuse(CLAIM, [sig("R-VIDEO-SYNTH", Family.F3, Severity.SOFT, "media:video"),
                     sig("R-AUDIO-SYNTH", Family.F3, Severity.SOFT, "media:audio")])
    assert v.outcome != Outcome.RED


def test_two_independent_softs_are_amber_but_same_key_is_not():
    assert fuse(CLAIM, [sig("A", Family.F1, Severity.SOFT, "claim"), sig("B", Family.F2, Severity.SOFT, "bank:ledger")]).outcome == Outcome.AMBER
    assert fuse(CLAIM, [sig("A", Family.F1, Severity.SOFT, "claim"), sig("B", Family.F1, Severity.SOFT, "claim")]).outcome == Outcome.GREY


def test_two_soft_amber_explanation_names_only_counting_signals():
    # The two-soft AMBER explanation joins only signals that could count toward independence (_can_second);
    # an F5 signal never counts and must not be named, even though it is soft.
    v = fuse(CLAIM, [sig("A", Family.F1, Severity.SOFT, "claim"),
                     sig("B", Family.F2, Severity.SOFT, "bank:ledger"),
                     sig("P", Family.F5, Severity.SOFT, "flag", can_be_second=False)])
    assert v.outcome == Outcome.AMBER
    assert v.explanation.startswith("Two or more independent soft signals: ")
    assert v.explanation.endswith("A, B.")
    assert "P" not in v.explanation


def test_escalate_alone_soft_is_amber():
    assert fuse(CLAIM, [sig("E", Family.F1, Severity.SOFT, "claim", escalate_alone=True)]).outcome == Outcome.AMBER


def test_unverified_hard_cannot_anchor():
    s = sig("A", Family.F1, Severity.HARD, "claim")
    s.citation_verified = False
    assert fuse(CLAIM, [s, sig("B", Family.F2, Severity.SOFT, "bank:ledger")]).outcome != Outcome.RED


def test_match_only_without_hard():
    m = sig("R-OWN-SIGNATURE", Family.F2, Severity.MATCH, "bank:signature")
    assert fuse(CLAIM, [m]).outcome == Outcome.MATCHES
    assert fuse(CLAIM, [m, sig("A", Family.F1, Severity.HARD, "claim")]).outcome != Outcome.MATCHES


def test_the_payment_neutral_headline_is_copy_and_never_moves_an_outcome():
    """`money_in_play` picks WORDS on both surfaces. Every branch of `fuse` must reach the same outcome with and
    without money in the claim, and only AMBER's headline may differ, because only AMBER's mentions paying."""
    branches = {
        "red pair": [sig("A", Family.F1, Severity.HARD, "claim"), sig("B", Family.F2, Severity.SOFT, "bank:name_lookup")],
        "lone hard": [sig("A", Family.F1, Severity.HARD, "claim")],
        "two softs": [sig("A", Family.F1, Severity.SOFT, "claim"), sig("B", Family.F2, Severity.SOFT, "bank:ledger")],
        "escalate alone": [sig("E", Family.F1, Severity.SOFT, "claim", escalate_alone=True)],
        "forensics alone": [sig("F", Family.F3, Severity.SOFT, "media:audio")],
        "match": [sig("M", Family.F2, Severity.MATCH, "bank:signature")],
        "nothing": [],
    }
    for name, signals in branches.items():
        with_money, without = fuse(CLAIM, signals), fuse(NO_MONEY, signals)
        if name != "red pair":        # the one branch the money gate itself touches, pinned elsewhere
            assert with_money.outcome == without.outcome, f"{name}: the copy predicate moved an outcome"
        for v in (with_money, without):
            table = HEADLINES_NO_PAYMENT if v is without and v.outcome in HEADLINES_NO_PAYMENT else HEADLINES
            assert (v.headline_en, v.headline_hi) == table[v.outcome], f"{name}: {v.headline_en!r}"


@pytest.mark.parametrize("claim, expected", [
    (Claim(source="text", text="x", instruction=Instruction.TRANSFER_TO_ACCOUNT), True),
    (Claim(source="text", text="x", instruction=Instruction.NONE), False),
    (Claim(source="text", text="x", payee=Payee(claimed_owner=ClaimedOwner.RBI)), True),
])
def test_money_in_play_is_the_wider_copy_predicate(claim, expected):
    """It is deliberately wider than the RED gate: a claimed owner with no account is money to the copy and not a
    payee to the verdict. `tests/test_no_red_without_money.py` holds the gate half of that pair."""
    assert money_in_play(claim) is expected


def test_empty_claim_is_grey_and_never_safe():
    v = fuse(EMPTY, [])
    assert v.outcome == Outcome.GREY and "safe" not in v.headline_en.lower()
    v2 = fuse(CLAIM, [])
    assert v2.outcome == Outcome.GREY and "not a confirmation" in v2.explanation
