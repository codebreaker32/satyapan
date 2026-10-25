"""The officer's band says what actually happened.

- A two-family AMBER capped because no money demand was read printed "One hard rule fired. One rule alone
  never gives RED." The verdict now carries `no_money_cap`, and the band branches on it.
- A GREY with an account said "the bank's own records found nothing wrong" when the name look-up did not hold the
  account at all.
"""
from __future__ import annotations

import pytest

from satyapan.models import Outcome
from tests.conftest import run_text

CAPPED = [
    "Demo Bank alert: your debit card has been blocked. Re-activate it at www.demobank-kyc.com today.",
    "Demo Bank: your KYC is due for re-verification. Update your records at demobank-kyc.com within 7 days.",
]


@pytest.mark.parametrize("text", CAPPED)
def test_a_capped_amber_says_so(engine, text):
    v = run_text(engine, text).verdict
    assert v.outcome is Outcome.AMBER and v.anchor_rule and v.second_family is None
    assert v.no_money_cap is True
    assert "Nothing in this message asked for money" in v.explanation


def test_a_lone_hard_rule_amber_is_not_marked_capped(engine):
    v = run_text(engine, "Demo Bank: your FD will be closed today. Move your savings to the new account now.").verdict
    if v.outcome is Outcome.AMBER:
        assert v.no_money_cap is False


def test_a_red_is_never_marked_capped(engine):
    v = run_text(engine, "Demo Bank: transfer Rs 49,000 to safe account 30011223344 today.").verdict
    assert v.outcome is Outcome.RED and v.no_money_cap is False


def test_grey_with_an_unheld_account_does_not_say_the_records_found_nothing_wrong(engine):
    v = run_text(engine, "Municipal Corporation of Delhi: your property tax of Rs 18,500 is overdue. Pay to account "
                         "1234509876 via NEFT today to avoid sealing of your house.").verdict
    assert v.outcome is Outcome.GREY
    assert "found nothing wrong" not in v.explanation
    assert "the bank's name look-up raised nothing about this account" in v.explanation
