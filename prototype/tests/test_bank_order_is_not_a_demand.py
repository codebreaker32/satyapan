"""A bank's own recovery letter is a polite ORDER, and that is still enough for RED. Recorded, not fixed.

The 19 Oct pass-1 adversarial gate found two benign bank letters going from AMBER to RED on the verbs that pass
added, and the verbs came out again (`tests/test_euphemism_bounds.py::DROPPED_19_OCT`). This file holds the part
that did not close, because closing it is a change to two rules this pass does not own:

    R-BANK-NEVER-MOVE-FD is BANK_SELF + TRANSFER_TO_ACCOUNT with no further condition, and
    R-BANK-SELF (hard, F2) fires on every outbound-log miss.

Two hard rules in two families is RED. So on a message that claims to be the bank, ANY instruction the extractor
reads is RED, and the card then says "Please stop. Do not send this money now." about the bank's own letter. The
verb list is not what does this: the sentences below use `deposit`, `arrange the settlement of` and bare
`transfer`, all of which read before 19 Oct and read today. Dropping verbs one at a time can only ever move
which strings land on it.

What the extractor does here is right, and that is the reason this is not an extractor fix: these letters DO
instruct a payment. "Verify the instruction, not the pixels" is the product's own sentence, and the instruction
is real. What is wrong is a rule that reads "the bank asked for money" as "the bank never asks for money".

The assertions are `xfail(strict=True)`, so the day the structure changes they XPASS, this file fails loudly, and
whoever fixed it deletes the markers. A plain assertion of today's behaviour would do the opposite: it would
make the fix look like a regression.
"""
from __future__ import annotations

import pytest

from satyapan.models import Instruction, Outcome
from tests.conftest import run_text

# Ordinary, polite, imperative letters from a bank to its own borrower, each with the amount and the account the
# bank wants it in. Every one is a sentence a real recovery or EMI letter carries, and every one of the verbs in
# them predates the 19 Oct pass.
BANK_ORDERS = [
    ("deposit", "Demo Bank Loan Recovery Cell: Kindly deposit Rs 2,50,000 in this loan account before "
                "30 November to regularise your loan. Account 3001122334455.", 250000),
    ("transfer", "Demo Bank Loan Recovery Cell: Kindly transfer Rs 2,50,000 to account 3001122334455 before "
                 "30 November to regularise your loan.", 250000),
    ("arrange the settlement of", "Demo Bank: You are requested to arrange the settlement of your outstanding "
                                  "dues of Rs 2,50,000 in this loan account 3001122334455.", 250000),
]


@pytest.mark.parametrize("verb,text,amount", BANK_ORDERS, ids=[v for v, _, _ in BANK_ORDERS])
def test_the_extractor_is_right_about_these_letters(verb, text, amount):
    """The premise, and it must keep passing: the instruction is really there, in the bank's own words.

    If this ever fails, the engine has stopped reading an ordinary payment instruction, and the xfail below has
    turned into a false pass.
    """
    from satyapan.extract import RulesExtractor

    claim = RulesExtractor(bank_names=("Demo Bank",)).extract(text)
    assert claim.instruction == Instruction.TRANSFER_TO_ACCOUNT, f"{verb}: {text!r}"
    assert claim.claimed_issuer.value == "BANK_SELF"


@pytest.mark.parametrize("verb,text,amount", BANK_ORDERS, ids=[v for v, _, _ in BANK_ORDERS])
@pytest.mark.xfail(strict=True, reason="R-BANK-NEVER-MOVE-FD + R-BANK-SELF make any instruction on a "
                                       "bank-claimed message RED; see this file's docstring")
def test_a_banks_own_recovery_letter_is_not_red(engine, verb, text, amount):
    case = run_text(engine, text, amount=amount)
    assert case.verdict.outcome != Outcome.RED


@pytest.mark.parametrize("verb,text,amount", BANK_ORDERS, ids=[v for v, _, _ in BANK_ORDERS])
@pytest.mark.xfail(strict=True, reason="the RED above carries RED's card; same structure, same docstring")
def test_a_banks_own_recovery_letter_does_not_get_the_stop_card(engine, verb, text, amount):
    case = run_text(engine, text, amount=amount)
    for lang, stop in (("en", "Please stop. Do not send this money now."), ("hi", "रुकिए। अभी यह पैसा न भेजें।")):
        assert stop not in engine.card(case, lang).read_aloud, f"{verb}/{lang}"
