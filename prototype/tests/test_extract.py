import json

import pytest

from satyapan.extract import RulesExtractor, claim_from_picklist, ground
from satyapan.models import Channel, ClaimedOwner, Instruction, Issuer, Span
from satyapan.pipeline import DATA_DIR
from tests.conftest import SCENARIOS

X = RulesExtractor(bank_names=("Demo Bank",))
VARIANTS = json.loads((DATA_DIR / "fixtures" / "variants.json").read_text(encoding="utf-8"))["variants"]


def test_rm_voice_note_fields():
    c = X.extract(SCENARIOS["S1-rm-voice-note"]["text"], source="transcript")
    assert c.claimed_issuer == Issuer.BANK_SELF
    assert c.instruction == Instruction.MOVE_FD
    assert c.payee.account.value == "50100234567891"
    assert c.payee.ifsc.value == "DEMO0001234"
    assert {"secrecy", "urgency"} <= set(c.pressure_cues)
    assert c.caller_number is None
    assert c.language_hint == "en"  # romanised Hinglish carries no Devanagari


def test_ed_summons_fields():
    c = X.extract(SCENARIOS["S3-ed-summons"]["text"], source="ocr")
    assert c.claimed_issuer == Issuer.ED
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert c.payee.claimed_owner == ClaimedOwner.RBI
    assert c.payee.account.value == "30011223344556"
    assert c.mentions_summons
    assert c.document_ids.summons_no.value == "ED/DLZO/2026/4471"
    assert c.document_ids.passcode is None
    assert c.document_ids.case_no.value == "ECIR/DLZO/18/2026"
    assert c.document_ids.issue_date.value == "14-10-2026"
    assert c.amounts and "38,00,000" in c.amounts[0].span.text
    assert {"arrest_threat", "secrecy"} <= set(c.pressure_cues)


def test_owner_phrase_survives_ocr_line_break():
    # tesseract breaks lines mid-phrase; the owner match must tolerate it and still quote the original verbatim
    c = X.extract("RBI\nsupervision account A/c 30011223344556", source="ocr")
    assert c.payee.claimed_owner == ClaimedOwner.RBI
    assert c.payee.account.value == "30011223344556"
    sp = c.payee.claimed_owner_span
    assert "\n" in sp.text and c.text[sp.start:sp.end] == sp.text  # verbatim, newline included: ground() keeps it
    assert ground(c).payee.claimed_owner == ClaimedOwner.RBI


def test_owner_bridge_never_crosses_into_a_new_header_line():
    # a newline bridges only into a lowercase continuation; a header or new sentence starting uppercase is not
    # a phrase, and bridging it once manufactured an owner claim the customer was never told about
    benign = [
        "Reserve Bank of India\nAccount holder awareness notice\nNever share your OTP.",
        "As per the interest rate set by RBI\nYour account 20098765432109 was credited with Rs 5,000 by NEFT",
        "Your linked account 20098765432109 has been updated for NEFT transfers",  # "linkED account" needs \b
    ]
    for text in benign:
        c = X.extract(text, source="ocr")
        assert c.payee.claimed_owner == ClaimedOwner.UNKNOWN, text.splitlines()[0]


def test_owner_filler_rejects_prepositional_mentions():
    # the filler window is an allow-list of scam-phrasing words; a preposition between the institution and
    # "account" means the text is ABOUT accounts, not naming an institution-owned payee
    benign = [
        "RBI guidelines on account closure",
        "RBI circular on account security",
        "court fees for account maintenance",
    ]
    for text in benign:
        c = X.extract(text)
        assert c.payee.claimed_owner == ClaimedOwner.UNKNOWN, text


def test_owner_possessive_and_scam_fillers_still_claim():
    for text, owner in [("RBI monitoring account", ClaimedOwner.RBI), ("court's registry account", ClaimedOwner.COURT),
                        # ad-lib digital-arrest nouns typed in live must keep claiming an owner
                        ("CBI investigation account", ClaimedOwner.AGENCY), ("ED custody account", ClaimedOwner.AGENCY),
                        ("RBI refund account", ClaimedOwner.RBI), ("court deposit account", ClaimedOwner.COURT),
                        ("police seizure account", ClaimedOwner.AGENCY), ("customs clearance account", ClaimedOwner.AGENCY),
                        ("government relief account", ClaimedOwner.GOVT), ("sarkari suraksha account", ClaimedOwner.GOVT)]:
        c = X.extract(text)
        assert c.payee.claimed_owner == owner, text
        assert c.text[c.payee.claimed_owner_span.start:c.payee.claimed_owner_span.end] == c.payee.claimed_owner_span.text


def test_rbi_video_fields_and_phone_not_inside_account():
    c = X.extract(SCENARIOS["S2-rbi-video"]["text"], source="transcript")
    assert c.claimed_issuer == Issuer.RBI
    assert c.instruction == Instruction.INVEST_FOR_RETURNS
    assert c.payee.claimed_owner == ClaimedOwner.RBI
    assert c.payee.account.value == "20098765432109"
    assert c.payee.vpa.value == "rbi.invest@okaxis"
    assert c.caller_number is None, "digits inside an account number must not be read as a phone number"
    assert "guaranteed_returns" in c.pressure_cues


def test_negated_instruction_is_not_an_instruction():
    c = X.extract(SCENARIOS["S5a-genuine-bank-notice"]["text"])
    assert c.claimed_issuer == Issuer.BANK_SELF
    assert c.instruction == Instruction.NONE
    assert any(u.value.endswith("demobank.bank.in") for u in c.urls)


def test_benign_refund_sms_claims_no_issuer():
    # "your bank account" is the customer's own account, not the bank claiming to speak
    c = X.extract("Income Tax refund of Rs 12,340 has been credited to your bank account ending 4411.")
    assert c.claimed_issuer == Issuer.NONE
    assert c.instruction == Instruction.NONE
    assert c.payee.account is None and c.caller_number is None


def test_stray_rm_token_is_not_a_bank_claim():
    c = X.extract("Kal ki team meeting mein RM sir ne naya duty roster share kiya hai, dekh lena.")
    assert c.claimed_issuer == Issuer.NONE
    assert c.instruction == Instruction.NONE
    # with bank context in the same sentence, "RM" still counts as the bank's relationship manager
    c2 = X.extract("Main aapke bank ka RM bol raha hoon, kal branch aa kar form sign kar dijiye.")
    assert c2.claimed_issuer == Issuer.BANK_SELF


def test_the_customers_own_account_is_not_a_payee():
    """A benign re-KYC letter used to name her own savings account as the payee.

    A payee is an assertion about where money is being sent. That number is what goes to the beneficiary-name
    look-up, to the I4C suspect registry and into the signed evidence pack, and it is what the card calls the
    account she was told to pay. Whose account it is, is something the message says in words.
    """
    c = X.extract("Demo Bank re-KYC notice: your account 3001122334455 will be restricted if the KYC is not "
                  "updated by 30 November.")
    assert c.payee.account is None, c.payee.account
    assert c.instruction == Instruction.NONE
    assert c.claimed_issuer == Issuer.BANK_SELF, "the bank's own name still reads as the bank"


@pytest.mark.parametrize("text", [
    "your account 3001122334455 will be restricted",
    "Your Demo Bank savings account 3001122334455 has been credited with Rs 5,000.",
    "aapke khate 3001122334455 par koi rok nahi hai.",
    "आपके खाते 3001122334455 की KYC लंबित है।",
    "I am writing about my account 3001122334455, which was debited twice.",
])
def test_a_possessive_account_is_never_read_as_a_payee(text):
    assert X.extract(text).payee.account is None, text


@pytest.mark.parametrize("text,expected", [
    # the payee is the OTHER account: the possessive one is skipped, not the whole field
    ("Transfer Rs 5,00,000 from your account 3001122334455 to the RBI supervision account 40900123456789.",
     "40900123456789"),
    ("Deposit Rs 2,00,000 in the clearance account 50100248891776 today.", "50100248891776"),
    # a third party's account is not the customer's own, so the guard must leave it alone
    ("Please settle the invoice in his account 99887766554433 by Friday.", "99887766554433"),
])
def test_the_payee_is_still_read_when_the_message_names_one(text, expected):
    assert X.extract(text).payee.account.value == expected, text


def test_email_address_is_not_a_upi_id():
    c = X.extract("Write to info@demobank.bank.in for help. Pay to shop.owner@okhdfcbank today.")
    assert c.payee.vpa.value == "shop.owner@okhdfcbank"


def test_every_span_is_verbatim():
    for sid in ("S1-rm-voice-note", "S2-rbi-video", "S3-ed-summons", "S7-court-order"):
        c = X.extract(SCENARIOS[sid]["text"])
        for sp in [c.issuer_span, c.instruction_span, c.channel_span, c.payee.claimed_owner_span] + list(c.pressure_cues.values()):
            if sp:
                assert c.text[sp.start:sp.end] == sp.text


def test_ground_drops_fabricated_fields():
    c = X.extract(SCENARIOS["S3-ed-summons"]["text"])
    c.issuer_span = Span(text="FAKE AGENCY", start=0, end=11)   # a quote that is not in the text
    g = ground(c)
    assert g.claimed_issuer == Issuer.NONE


@pytest.mark.parametrize("v", VARIANTS, ids=[v["id"] for v in VARIANTS])
def test_variant_corpus(v):
    """Synthetic Hinglish/Devanagari/WhatsApp variants of S1-S7 plus benign negatives (data/fixtures/variants.json)."""
    c = X.extract(v["text"])
    assert c.claimed_issuer == Issuer(v["expected"]["issuer"])
    assert c.instruction == Instruction(v["expected"]["instruction"])
    for sp in (c.issuer_span, c.instruction_span):
        if sp:
            assert c.text[sp.start:sp.end] == sp.text


def test_picklist_claim():
    c = claim_from_picklist(issuer=Issuer.CBI, instruction=Instruction.TRANSFER_TO_ACCOUNT, channel=Channel.VIDEO_CALL,
                            claimed_owner=ClaimedOwner.RBI, account="30011223344556", pressure=["arrest_threat"])
    assert c.source == "officer_picklist"
    assert c.payee.account.value == "30011223344556"
    assert c.text[c.issuer_span.start:c.issuer_span.end] == "issuer=CBI"
    assert "arrest_threat" in c.pressure_cues
