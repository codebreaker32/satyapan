"""The passive register is blind to direction, and the benign half of it is money arriving for the customer.

The pass-5 gate paid the bill for this one. The pass had just added the passive register so that a forged legal
notice ("the sum is required to be remitted to the account specified herein") would read as a demand. The same
grammar is how a bank announces a maturity, a refund, a salary or an interest credit — and the gate wrote two
sentences that took the bank's own FD-maturity letter all the way to RED, with the customer card saying "Please
stop. Do not send this money now." about her own matured deposit. That is the exact defect the rest of this pass
exists to fix, re-created one layer up.

The verb lexeme cannot separate direction: "credited" was excluded and "remitted" was not, and both run both ways.
The gate is the money itself. When the matched clause names the money as something arriving, the passive does not
read. It is scoped to the passive family, because the active family says "transfer Rs X", which is not how a credit
is announced, and a blanket suppressor would silence a real demand that happens to mention a refund.
"""
from __future__ import annotations

import pytest

from satyapan.extract import RulesExtractor
from satyapan.models import Instruction

# Money arriving for the customer, in the register a bank actually writes. Every one of these carries the money
# word, the destination, the pointed-at account and the passive construction — they are at risk, which is what
# makes them worth testing.
ARRIVING = [
    "Demo Bank: your fixed deposit has matured. The maturity amount of Rs 4,20,000 is required to be remitted to "
    "the account specified herein within three working days.",
    "The refund amount of Rs 18,400 shall be remitted to the account mentioned above.",
    "Your salary of Rs 42,000 is to be credited to the account mentioned above.",
    "The proceeds of Rs 1,10,000 are to be transferred to the account specified herein after maturity.",
    "Interest of Rs 3,250 is to be deposited into the account mentioned above on the first of each month.",
    "The reversal of Rs 900 shall be credited to the account specified herein within 48 hours.",
    "आपकी परिपक्वता राशि ₹2,00,000 नीचे दिए गए खाते में जमा की जानी है।",
]

# A demand, in the same grammar. These must still read, or the suppressor has eaten the feature.
DEMANDED = [
    "This is the CBI Cyber Crime Unit. The sum of Rs 38,00,000 is required to be remitted to the account "
    "specified herein for custodial verification.",
    "The entire balance of Rs 9,00,000 is to be deposited into the designated verification account without delay.",
    "Rs 5,00,000 must be transferred to the escrow account mentioned below before 5 pm.",
    "पूरी राशि ₹10,00,000 इस खाते में जमा की जानी है।",
]


@pytest.fixture(scope="module")
def ex() -> RulesExtractor:
    return RulesExtractor()


@pytest.mark.parametrize("text", ARRIVING)
def test_money_arriving_for_the_customer_is_not_a_demand(ex, text):
    claim = ex.extract(text)
    assert claim.instruction == Instruction.NONE, (
        f"a credit to the customer was read as an instruction to pay: {text!r} -> {claim.instruction.value} "
        f"from {claim.instruction_span.text if claim.instruction_span else None!r}"
    )


@pytest.mark.parametrize("text", DEMANDED)
def test_a_demand_in_the_same_grammar_still_reads(ex, text):
    claim = ex.extract(text)
    assert claim.instruction != Instruction.NONE, f"the suppressor ate a real demand: {text!r}"


def test_the_bank_letter_the_gate_wrote_does_not_reach_red(engine):
    """End to end, through the real rulebook and the mock adapters: the whole point of the fix."""
    from tests.conftest import run_text

    case = run_text(
        engine,
        "Demo Bank: your fixed deposit has matured. The maturity amount of Rs 4,20,000 is required to be remitted "
        "to the account specified herein within three working days.",
        reason="premature FD closure + RTGS to first-time payee",
        amount=420000.0,
    )
    assert case.verdict.outcome.value != "RED", (
        f"a bank's own maturity letter reached {case.verdict.outcome.value}: {case.verdict.explanation}"
    )
    for lang in ("hi", "en"):
        card = engine.card(case, lang)
        assert "Do not send this money" not in card.do_now
        assert "यह पैसा किसी को न भेजें" not in card.do_now


def test_the_suppressor_is_scoped_to_the_passive_family(ex):
    """An active demand that merely mentions a refund must still read, or the gate is too wide."""
    claim = ex.extract("Your refund is stuck. Transfer Rs 50,000 to the designated verification account to release it.")
    assert claim.instruction != Instruction.NONE


def test_the_suppressor_is_what_drops_the_benign_letter(ex, monkeypatch):
    """Not a tautology: with the direction gate neutered, the maturity letter reads as a demand again."""
    import re

    from satyapan import extract as X

    monkeypatch.setattr(X, "RE_CREDIT_TO_CUSTOMER", re.compile(r"(?!x)x"))   # matches nothing
    text = ARRIVING[0]
    assert RulesExtractor().extract(text).instruction == Instruction.TRANSFER_TO_ACCOUNT, (
        "the control did not reproduce the gate's finding, so this test proves nothing"
    )
