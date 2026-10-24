"""Agency money demands are read however they are worded (bug hunt findings 2 and 3).

- 2: demands worded with "pay", "payment karo", "bharo", "भुगतान करें", "rupay" or a यूपीआई ID read no instruction,
  so CBI, police and customs demands came out GREY while the same text with "transfer" gave AMBER.
- 3: "This is Delhi Police", "calling from Mumbai Police", a "CBI:" masthead and "ED office se bol" anchored no
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
