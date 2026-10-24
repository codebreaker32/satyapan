"""The bank's bare name is somebody's account, not a claim to be the bank, when a possessive sits in front of it.

Bug hunt, finding 1 (critical): "Beta, please transfer 5000 to my Demo Bank account ... - Mummy" gave RED, with
claimed_issuer BANK_SELF taken from "Demo Bank" in "my Demo Bank account", and the card told the customer that
Demo Bank had no record of sending it. A mother, an employer or a tenant never claimed to be the bank.
"""
from __future__ import annotations

import pytest

from satyapan.extract import RulesExtractor
from satyapan.models import Issuer, Outcome
from tests.conftest import run_text

NOT_THE_BANK = [
    "Beta, please transfer 5000 to my Demo Bank account, I need it for medicines. - Mummy",
    "Papa, maine aapke Demo Bank account me NEFT se 20,000 bhej diye hain, check kar lena.",
    "Acme Corp HR: Your October salary of Rs 85,000 has been transferred by NEFT to your Demo Bank account XX4411.",
    "Hi Sharda ji, I have sent the rent of Rs 15,000 to your Demo Bank account by IMPS. - Ramesh (tenant)",
]

THE_BANK = [
    "Demo Bank: your account is blocked. Transfer Rs 49,000 to safe account 30011223344 today.",
    "Main Demo Bank se bol raha hoon. Apna FD tod kar paisa safe account 30011223344 mein bhejiye.",
    "Your KYC is pending. Update now or your account will be frozen. - Demo Bank",
]


@pytest.mark.parametrize("text", NOT_THE_BANK)
def test_possessive_bank_name_is_not_a_bank_claim(engine, text):
    extractor = RulesExtractor(bank_names=(engine.book.bank_name,))
    assert extractor.extract(text).claimed_issuer is not Issuer.BANK_SELF
    case = run_text(engine, text)
    assert case.verdict.outcome is not Outcome.RED
    assert all(s.rule_id not in ("R-BANK-SELF", "R-BANK-NEVER-MOVE-FD") for s in case.verdict.signals)


@pytest.mark.parametrize("text", THE_BANK)
def test_masthead_sign_off_and_self_introduction_still_claim_the_bank(engine, text):
    extractor = RulesExtractor(bank_names=(engine.book.bank_name,))
    assert extractor.extract(text).claimed_issuer is Issuer.BANK_SELF
