"""Agency money demands are read however they are worded.

- Demands worded with "pay", "payment karo", "bharo", "भुगतान करें", "rupay" or a यूपीआई ID read no instruction,
  so CBI, police and customs demands came out GREY while the same text with "transfer" gave AMBER.
- "This is Delhi Police", "calling from Mumbai Police", a "CBI:" masthead and "ED office se bol" anchored no
  authority, so the band said "no authority was read" about a message that opened with one.

A lone agency rule is AMBER by design; these must reach AMBER, never RED on their own. The benign "pay" controls
stay GREY.
"""
from __future__ import annotations

import pytest

from satyapan.models import Instruction, Issuer, Outcome
from tests.conftest import run_text

PAY_WORDED = [
    "CBI officer: pay Rs 2,00,000 to account 123456789012 to avoid arrest.",
    "Customs Department, IGI Airport: a parcel from Taiwan addressed to you contains contraband. Pay customs "
    "clearance penalty Rs 75,000 to account 33445566778 IFSC ICIC0000123 within 1 hour or a case will be registered.",
    "Delhi Police se bol raha hoon. 50,000 rupay turant is khate me daalo 123456789012",
    "CBI se bol raha hoon, 2 lakh ka payment karo is account me 123456789012",
    "मैं सीबीआई से बोल रहा हूँ। 2 लाख रुपये का भुगतान करें, खाता 123456789012",
    "मैं सीबीआई से बोल रहा हूँ। 2 लाख रुपये इस यूपीआई आईडी पर भेजें cbi.case@okaxis",
]

UNANCHORED_BEFORE = [
    ("This is Delhi Police. Transfer Rs 2 lakh to account 123456789012 or you will be arrested.", Issuer.POLICE),
    ("I am calling from Mumbai Police. Transfer 2 lakh to account 123456789012.", Issuer.POLICE),
    ("CBI: Transfer Rs 50,000 to account 123456789012 today or you will be arrested.", Issuer.CBI),
    ("Mumbai Police: Transfer Rs 50,000 to account 123456789012 today or you will be arrested.", Issuer.POLICE),
    ("सीबीआई: आपके खिलाफ मनी लॉन्ड्रिंग का केस है। गिरफ्तारी से बचने के लिए 3 लाख रुपये इस खाते में ट्रांसफर करें "
     "123456789012", Issuer.CBI),
    ("दिल्ली पुलिस: आपके नाम पर एफआईआर दर्ज है। 50,000 रुपये इस खाते में जमा करें 123456789012 वरना गिरफ्तारी होगी।",
     Issuer.POLICE),
    ("ED office se bol raha hoon. 2 lakh is account mein transfer karo 123456789012", Issuer.ED),
]

BENIGN_PAY = [
    "Please pay your electricity bill of Rs 1,200 at the counter.",
    "I will pay you back the Rs 500 tomorrow.",
    "Your premium of Rs 5,000 is due; pay it through the app to keep your policy active.",
]


@pytest.mark.parametrize("text", PAY_WORDED)
def test_pay_worded_agency_demand_is_read(engine, text):
    case = run_text(engine, text)
    assert case.claim.instruction is not Instruction.NONE
    assert case.verdict.outcome is Outcome.AMBER


@pytest.mark.parametrize("text, issuer", UNANCHORED_BEFORE)
def test_place_named_and_masthead_authority_is_anchored(engine, text, issuer):
    case = run_text(engine, text)
    assert case.claim.claimed_issuer is issuer
    assert case.verdict.outcome is Outcome.AMBER


@pytest.mark.parametrize("text", BENIGN_PAY)
def test_everyday_pay_sentences_stay_grey(engine, text):
    assert run_text(engine, text).verdict.outcome is Outcome.GREY


AWARENESS = [
    "RBI: Never share your OTP or PIN. RBI never asks anyone to transfer money to any account.",
    "Delhi Police: Beware of digital arrest calls. Police never ask you to transfer money to any account.",
    "CBI: There is no such thing as digital arrest. Do not pay anyone who calls claiming to be from CBI.",
    "Mumbai Police: If someone asks you to pay Rs 50,000 to this account 123456789012 to avoid arrest, it is a scam. "
    "Call 1930.",
    "Delhi Police here. If anyone asks you to transfer money to account 123456789012, report it.",
    "दिल्ली पुलिस: डिजिटल अरेस्ट जैसा कुछ नहीं होता। किसी के कहने पर पैसे न भेजें।",
]


@pytest.mark.parametrize("text", AWARENESS)
def test_an_authority_awareness_message_is_not_a_demand(engine, text):
    """The masthead anchor and the pay verbs must not turn a police or RBI warning into the body demanding money; a
    demand put as a condition about someone else ("If someone asks you to pay ...") is not this message asking."""
    case = run_text(engine, text)
    assert case.claim.instruction is Instruction.NONE
    assert case.verdict.outcome is Outcome.GREY


def test_the_messages_own_conditional_demand_still_reads(engine):
    case = run_text(engine, "CBI: If you want to avoid arrest, transfer Rs 50,000 to account 123456789012 today.")
    assert case.claim.instruction is Instruction.TRANSFER_TO_ACCOUNT and case.verdict.outcome is Outcome.AMBER


@pytest.mark.parametrize("text, issuer", [
    ("यह मुंबई पुलिस है। आपके आधार से मनी लॉन्ड्रिंग हुई है। जांच के लिए 75 हज़ार रुपये इस खाते 30011223344 में तुरंत भेजें।",
     Issuer.POLICE),
    ("यह सीबीआई है। 2 लाख रुपये इस खाते 30011223344 में भेजें।", Issuer.CBI),
])
def test_the_hindi_self_introduction_anchors_the_authority(engine, text, issuer):
    case = run_text(engine, text)
    assert case.claim.claimed_issuer is issuer and case.verdict.outcome is Outcome.AMBER


def test_this_is_a_police_matter_is_not_a_police_claim(engine):
    case = run_text(engine, "यह पुलिस का मामला है, आप थाने जाकर शिकायत करें।")
    assert case.claim.claimed_issuer is Issuer.NONE
