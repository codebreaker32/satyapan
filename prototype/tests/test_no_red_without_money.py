"""The fourth fusion invariant: no RED when the engine read no money demand.

A hackathon judge pasted a genuine, benign bank letter — a head-office recovery cell writing about an overdue home
loan, no payee account, no money instruction, `instruction=NONE` — and the customer card told a real customer to
stop. That is the worst defect this product can ship, because "verify the instruction, not just the pixels" is its own
sentence: a verdict that fires when nothing about money was read contradicts the thing we claim to do.

The invariant lives in `fusion.fuse`, next to the two-families rule, and is the last thing checked before a RED is
returned. Two halves, and both matter:

1. It really caps a RED. Not a tautology: the same signals with a money demand in the claim still give RED, and a
   real pasted message that two independent families agree on is shown going through the pipeline to AMBER.
2. It only ever softens. It touches nothing but the RED branch, so AMBER, GREY and MATCHES come out unchanged
   whether or not money was read, and nothing in the rulebook can be made MORE severe by it.
"""
from __future__ import annotations

import pytest

from satyapan.fusion import fuse
from satyapan.models import (Claim, ClaimedOwner, Family, Grounded, Instruction, Issuer, Outcome, Payee, Severity,
                             Signal, Span)
from tests.conftest import run_text


def sig(rule, fam, sev, key, **detail):
    d = {"can_be_second": True} | detail
    return Signal(rule_id=rule, family=fam, severity=sev, evidence_key=key, reason_en="r", reason_hi="र", citation="c",
                  citation_verified=True, escalate_alone=detail.get("escalate_alone", False), detail=d)


def claim(instruction=Instruction.NONE, **payee):
    """A claim that is a RED pair's worth of message, varying only the money half."""
    return Claim(source="text", text="x", claimed_issuer=Issuer.BANK_SELF, instruction=instruction,
                 payee=Payee(**payee))


def grounded(value: str) -> Grounded:
    return Grounded(value=value, span=Span(text=value, start=0, end=len(value)))


# The pair that would be a RED on any claim: a cited hard F2 plus an independent F1 soft on different evidence.
PAIR = [sig("R-BANK-SELF", Family.F2, Severity.HARD, "bank:outbound_log"),
        sig("R-DOMAIN-BANKIN", Family.F1, Severity.SOFT, "claim")]


def test_red_needs_a_money_demand_as_well_as_two_families():
    """The invariant itself, and its own control: the only thing that changes is the money half of the claim."""
    assert fuse(claim(), PAIR).outcome == Outcome.AMBER
    assert fuse(claim(instruction=Instruction.TRANSFER_TO_ACCOUNT), PAIR).outcome == Outcome.RED


@pytest.mark.parametrize("instruction", [i for i in Instruction if i != Instruction.NONE])
def test_any_payment_instruction_lets_the_red_through(instruction):
    """Not a tautology in the other direction either: every instruction the model has is a money demand, so the
    cap must apply to exactly one value of the field, NONE, and to no other."""
    v = fuse(claim(instruction=instruction), PAIR)
    assert v.outcome == Outcome.RED, f"{instruction.value} was treated as no money demand"
    assert (v.anchor_rule, v.second_family) == ("R-BANK-SELF", "R-DOMAIN-BANKIN")


@pytest.mark.parametrize("field", ["account", "ifsc", "vpa"])
def test_a_payee_read_without_an_instruction_still_lets_the_red_through(field):
    """The backstop half of the invariant: the extractor can miss the instruction phrasing and still have read
    somewhere to send money. An account, an IFSC or a UPI ID is a money demand on its own."""
    value = {"account": "50100248891776", "ifsc": "DEMO0001234", "vpa": "payme@upi"}[field]
    assert fuse(claim(**{field: grounded(value)}), PAIR).outcome == Outcome.RED


def test_a_claimed_payee_owner_alone_is_not_enough_to_license_a_red():
    """`fusion.money_in_play`, which picks the wording on both surfaces, counts a claimed owner with no account
    behind it, because copy may be generous. This gate holds a verdict and may not: "the account below belongs to
    RBI" with no account read is not a payee, so the cap stays on. Pinned so the two are never quietly wired
    together; `tests/test_card_reads_aloud.py` holds the other side, where a capped AMBER still gets a
    payment-neutral headline even though the copy predicate says money is in play."""
    c = claim()
    c.payee.claimed_owner = ClaimedOwner.RBI
    assert fuse(c, PAIR).outcome == Outcome.AMBER


def test_the_capped_amber_says_why_and_still_names_both_rules():
    v = fuse(claim(), PAIR)
    assert v.outcome == Outcome.AMBER
    assert "Not in our outbound record" in v.explanation, "the anchor must still be named"
    assert "Bank link not on" in v.explanation, "the second signal must still be named"
    assert "asked for money" in v.explanation
    # The audit surface: the anchor is kept, and nothing is recorded as having made this a RED.
    assert v.anchor_rule == "R-BANK-SELF"
    assert v.second_family is None


def test_the_cap_never_makes_a_verdict_more_severe():
    """The invariant may only soften. Every other branch of `fuse` must land on the same outcome whether or not a
    money demand was read, so nothing can be escalated by the absence of one."""
    cases = {
        "lone hard": [PAIR[0]],
        "two independent softs": [sig("A", Family.F1, Severity.SOFT, "claim"),
                                  sig("B", Family.F2, Severity.SOFT, "bank:ledger")],
        "escalate alone": [sig("E", Family.F1, Severity.SOFT, "claim", escalate_alone=True)],
        "forensics alone": [sig("F", Family.F3, Severity.SOFT, "media:audio")],
        "match": [sig("M", Family.F2, Severity.MATCH, "bank:signature")],
        "nothing": [],
    }
    order = {Outcome.MATCHES: 0, Outcome.GREY: 1, Outcome.AMBER: 2, Outcome.RED: 3}
    for name, signals in cases.items():
        without = fuse(claim(), signals).outcome
        with_money = fuse(claim(instruction=Instruction.TRANSFER_TO_ACCOUNT), signals).outcome
        assert without == with_money, f"{name}: money demand changed a non-RED branch"
    # and on the one branch it does touch, it moves strictly downward
    assert order[fuse(claim(), PAIR).outcome] < order[fuse(claim(instruction=Instruction.MOVE_FD), PAIR).outcome]


# ---------------------------------------------------------------- end to end, through the real pipeline
#
# The unit tests above hand `fuse` its signals. These two run pasted text through the extractor, the rulebook and
# the mock adapters, so the invariant is proved on the path the judge actually used rather than on a constructed
# signal list.

JUDGE_LETTER = ("Demo Bank Loan Recovery Cell, Head Office. Your home loan account is overdue by Rs 2,84,000. "
                "Recovery proceedings before the Debts Recovery Tribunal may follow and the property may be "
                "auctioned under the SARFAESI Act. You may pay at any branch counter.")
# Two independent families fire on this one and nothing in it asks for money: R-BANK-SELF (F2, the bank's outbound
# log) and R-DOMAIN-BANKIN (F1, the message itself). Before this pass it was a RED.
TWO_FAMILIES_NO_MONEY = ("Demo Bank: your KYC is due for re-verification. Update your records at demobank-kyc.com "
                         "within 7 days.")


def test_the_judges_letter_is_not_red(engine):
    case = run_text(engine, JUDGE_LETTER, sender="+919812345670", amount=284000)
    assert case.claim.instruction == Instruction.NONE
    assert not (case.claim.payee.account or case.claim.payee.ifsc or case.claim.payee.vpa)
    assert case.verdict.outcome == Outcome.AMBER
    for lang in ("en", "hi"):
        card = engine.card(case, lang)
        assert card.outcome == Outcome.AMBER


def test_two_families_with_no_money_demand_reach_amber_through_the_pipeline(engine):
    case = run_text(engine, TWO_FAMILIES_NO_MONEY)
    fired = {s.rule_id for s in case.verdict.signals}
    assert {"R-BANK-SELF", "R-DOMAIN-BANKIN"} <= fired, "probe no longer raises two independent families"
    anchor = next(s for s in case.verdict.signals if s.rule_id == "R-BANK-SELF")
    second = next(s for s in case.verdict.signals if s.rule_id == "R-DOMAIN-BANKIN")
    # the RED pair test is satisfied: cited hard rule, different family, different evidence
    assert anchor.severity == Severity.HARD and anchor.citation_verified
    assert anchor.family != second.family and anchor.evidence_key != second.evidence_key
    assert case.claim.instruction == Instruction.NONE
    assert case.verdict.outcome == Outcome.AMBER, "a RED pair with no money demand must be capped"


def test_the_same_message_with_a_money_demand_is_still_red(engine):
    """The control for the test above, on the same path: add a payee and an instruction and the RED comes back."""
    case = run_text(engine, TWO_FAMILIES_NO_MONEY + " Transfer Rs 50,000 to account 50100248891776 to complete it.")
    assert case.claim.instruction != Instruction.NONE
    assert case.verdict.outcome == Outcome.RED
