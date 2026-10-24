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
    # a scam posing as the bank says "your Demo Bank account" too, and must keep its bank claim
    "Aapke Demo Bank account par fraud hua hai. Apna paisa is safe account 30011223344 mein turant bhejiye.",
    "Your Demo Bank account KYC expired. Pay Rs 10 at demobank-kyc.com to avoid blocking.",
    "Your Demo Bank account has been credited with Rs 25,000 by mistake. Please return it to account 30011223344 today.",
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


WRONG_TRANSFER_SCAMS = [
    "I have paid Rs 10,000 to your Demo Bank account by mistake, please transfer it back to this account "
    "30011223344 today. Urgent.",
    "Sir I have transferred Rs 5,000 to your Demo Bank account wrongly. Kindly return it to account 30011223344 "
    "immediately.",
]


@pytest.mark.parametrize("text", WRONG_TRANSFER_SCAMS)
def test_a_wrong_transfer_scam_that_asks_for_money_back_stays_flagged(engine, text):
    """Found by an independent probe of tonight's changes: with the possessive rule these went from RED / AMBER to
    GREY. A message that asks for money keeps its bank claim, as it did before the rule existed."""
    assert run_text(engine, text).verdict.outcome is not Outcome.GREY


def test_the_bank_name_in_devanagari_is_read(engine):
    """A Hindi scam posing as the bank writes 'डेमो बैंक'; with only the Latin name it read no bank claim (GREY)."""
    case = run_text(engine, "आपके डेमो बैंक खाते से 40,000 रुपये कट गए हैं। रिफंड के लिए तुरंत इस खाते 30011223344 में 1 रुपया भेजें।")
    assert case.claim.claimed_issuer is Issuer.BANK_SELF and case.verdict.outcome is Outcome.RED


def test_a_relatives_hindi_message_about_my_devanagari_bank_account_is_not_the_bank(engine):
    case = run_text(engine, "मैंने आपके डेमो बैंक खाते में 5,000 रुपये भेज दिए हैं, देख लेना।")
    assert case.claim.claimed_issuer is not Issuer.BANK_SELF and case.verdict.outcome is Outcome.GREY
