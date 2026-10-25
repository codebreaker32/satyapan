"""Copy-paste notices: a real government message copied word for word, with only the "where to" detail swapped.

Two shapes: a municipal house-tax notice whose payment account is replaced with a new
scammer's, and an e-challan SMS whose phone number or link is replaced. The words are real, so word matching cannot
tell the copy from the original, and the scammer is new, so no list of known scammers can either. What tells them
apart is where the payment goes, read against official sources: who owns the account (the bank's name look-up),
whether the link is on .gov.in, and who the paused payment is going to. The rules themselves are pinned in
`tests/test_rules.py`; this file pins what the extractor reads and what the card is allowed to say.
"""
from __future__ import annotations

import pytest

from satyapan.card import build_card
from satyapan.extract import RulesExtractor
from satyapan.models import Claim, Grounded, Instruction, Issuer, Outcome, Payee, Span, Verdict
from satyapan.rulebook import load_rulebook, make_signal

X = RulesExtractor(bank_names=("Demo Bank",))
BOOK = load_rulebook()


# ---------------------------------------------------------------- who the message is in the name of

@pytest.mark.parametrize("text, issuer", [
    ("Traffic Police, Gurugram. Your e-challan of Rs 500 is unpaid.", Issuer.TRANSPORT),
    ("यातायात पुलिस विभाग: आपके वाहन DL8CAF1234 का ई-चालान लंबित है। तुरंत भुगतान करें।", Issuer.TRANSPORT),
    ("Municipal Corporation of Delhi. Property tax notice. Pay your house tax of Rs 12,500 today.", Issuer.MUNICIPAL),
    ("नगर निगम, लखनऊ। आपका गृह कर बकाया है, तुरंत जमा करें।", Issuer.MUNICIPAL),
    ("MCD property tax notice: your property tax for 2026-27 is overdue.", Issuer.MUNICIPAL),
])
def test_a_civic_body_is_read_as_itself(text, issuer):
    assert X.extract(text).claimed_issuer == issuer


@pytest.mark.parametrize("text, issuer", [
    # The Hindi officer frame ends on a vowel sign, after which \b never matches, so it used to anchor nothing.
    ("सीबीआई अधिकारी बोल रहा हूँ। अपनी FD तोड़कर पूरा पैसा तुरंत सरकारी सुरक्षित खाते में भेजें।", Issuer.CBI),
    # "<Body> Department" with nothing in between, for parity with the Hindi विभाग.
    ("Customs Department, Mumbai Airport. Pay the clearance fee of Rs 1,50,000 to account 30011223344556.", Issuer.CUSTOMS),
])
def test_a_body_named_with_its_officer_or_department_is_read_as_the_sender(text, issuer):
    assert X.extract(text).claimed_issuer == issuer


def test_a_department_word_after_filler_does_not_move_the_issuer():
    """The guard on the line above: "CBI Income Tax Department" is the CBI's name pasted in front of another body's
    masthead, and reading it as the CBI's own department moved the issuer (tests/test_injection_steering.py)."""
    assert X.extract("CBI Income Tax Department: a refund of Rs 8,450 has been credited.").claimed_issuer != Issuer.CBI
    assert X.extract("If in doubt, contact the police department near you.").claimed_issuer != Issuer.POLICE


def test_traffic_police_is_never_read_as_the_police():
    """"Traffic Police" holds the POLICE token, and a POLICE sender asking for money gets R-AGENCY-PAY's sentence
    "no government agency demands money", which is false about a real challan. TRANSPORT wins the tie in both
    languages, including the Hindi masthead where the police token anchors on विभाग by itself."""
    for text in ("Traffic Police, Gurugram. Your e-challan of Rs 500 is unpaid.",
                 "यातायात पुलिस विभाग: आपके वाहन DL8CAF1234 का ई-चालान लंबित है।"):
        c = X.extract(text)
        assert c.claimed_issuer == Issuer.TRANSPORT
        assert Issuer.POLICE.value not in {g.value for g in c.other_issuers}, "one body, not two"


# ---------------------------------------------------------------- what the message asks for

@pytest.mark.parametrize("text, instruction", [
    ("Traffic Police, Gurugram. Your e-challan of Rs 500 is unpaid.", Instruction.PAY_CHALLAN),
    ("Dear user, your vehicle HR26AB1234 has a pending e-challan of Rs 500. Pay immediately.", Instruction.PAY_CHALLAN),
    ("Challan No. DL1234567890 issued for vehicle DL8CAF1234. Fine Rs 2,000. Pay within 7 days.", Instruction.PAY_CHALLAN),
    ("यातायात पुलिस विभाग: आपके वाहन DL8CAF1234 का ई-चालान लंबित है। तुरंत भुगतान करें।", Instruction.PAY_CHALLAN),
    ("Pay your house tax of Rs 12,500 before 31 Oct.", Instruction.PAY_LOCAL_TAX),
    ("Your property tax for 2026-27 is overdue.", Instruction.PAY_LOCAL_TAX),
    ("नगर निगम, लखनऊ। आपका गृह कर बकाया है, तुरंत जमा करें।", Instruction.PAY_LOCAL_TAX),
    ("Nagar Nigam se suchna: aapka house tax bakaya hai, jaldi jama karein.", Instruction.PAY_LOCAL_TAX),
    # a traffic FINE with no "challan" in it: two messages typed into the console, verbatim
    ("You have broken signal at traffic light, your vehicle number dl04-110 will be charged a fine for 500000, "
     "pay at bhawna.demo@demoupi", Instruction.PAY_CHALLAN),
    ("pay your vehicle driving fine , you passes a red light at traffic signal, \npay at bhawna.demo@demoupi ",
     Instruction.PAY_CHALLAN),
    ("आपके वाहन ने लाल बत्ती पार की है। ₹1,000 का जुर्माना तुरंत भरें।", Instruction.PAY_CHALLAN),
])
def test_a_government_due_is_read(text, instruction):
    assert X.extract(text).instruction == instruction


@pytest.mark.parametrize("text", [
    # a "challan" with no vehicle or traffic word: an income-tax form and a bank deposit slip
    "Use challan ITNS 280 to pay your advance tax before 15 December.",
    "Fill the deposit challan at the counter and pay in cash.",
    # awareness: the official site's own name, a negation and reported speech
    "Beware of e-challan messages. Pay traffic fines only on echallan.parivahan.gov.in.",
    "Never pay a traffic challan through a link sent on WhatsApp.",
    "Fraudsters are sending messages asking you to pay a pending e-challan for your vehicle.",
    # a challan that has already been paid
    "Your vehicle DL8CAF1234 challan has been paid. Thank you.",
    # a fine with no vehicle or traffic word, a negated one, a paid one, and the fine print
    "The library charges a fine for late books, pay at the counter.",
    "Never pay a traffic fine through a link sent on WhatsApp.",
    "Your traffic fine for vehicle DL8CAF1234 has been paid. Thank you.",
    "Read the fine print before you pay for the car insurance.",
    # an ordinary transfer between family members
    "Didi, sending you the money for your books and bus pass. Pay the college fee before Friday.",
])
def test_a_message_that_asks_for_no_due_is_not_read_as_one(text):
    assert X.extract(text).instruction == Instruction.NONE


# ---------------------------------------------------------------- what the card may say about the account

TAX = "Municipal Corporation of Delhi. Pay your house tax of Rs 12,500 to A/c 40920011558866."


def _span(quote: str, text: str) -> Span:
    i = text.index(quote)
    return Span(text=quote, start=i, end=i + len(quote))


def _tax_claim(*, issuer_quote: str | None, instruction_quote: str | None, account: bool = True) -> Claim:
    payee = Payee(account=Grounded(value="40920011558866", span=_span("40920011558866", TAX)) if account else None)
    claim = Claim(source="text", text=TAX, claimed_issuer=Issuer.MUNICIPAL, instruction=Instruction.PAY_LOCAL_TAX,
                  payee=payee)
    if issuer_quote:
        claim.issuer_span = _span(issuer_quote, TAX)
    if instruction_quote:
        claim.instruction_span = _span(instruction_quote, TAX)
    return claim


def _payee_not_sender() -> object:
    return make_signal(BOOK, "R-PAYEE-NOT-SENDER", {
        "evidence_key": "bank:name_lookup", "issuer_en": "the municipal corporation", "issuer_hi": "नगर निगम",
        "instruction_en": "paying property or house tax", "instruction_hi": "प्रॉपर्टी या हाउस टैक्स भरने को",
        "holder": "Sunil Yadav", "holder_type_en": "an individual", "holder_type_hi": "एक व्यक्ति"})


def _amber(signals) -> Verdict:
    return Verdict(outcome=Outcome.AMBER, headline_en="Verify before paying", headline_hi="भुगतान से पहले पुष्टि करें",
                   explanation="built by hand", policy_version="test", signals=signals)


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_the_account_reason_names_the_sender_only_with_a_span_for_it(lang):
    words = {"en": ("the municipal corporation", "paying property or house tax"),
             "hi": ("नगर निगम", "प्रॉपर्टी या हाउस टैक्स भरने")}[lang]
    sender, due = words

    def reason(**kw) -> str:
        return build_card(_amber([_payee_not_sender()]), _tax_claim(**kw), lang).reasons[0].text

    both = reason(issuer_quote="Municipal Corporation", instruction_quote="Pay your house tax")
    assert sender in both and "Sunil Yadav" in both
    # no span for the sender: the due the message asked for, which it does carry a span for, takes its place
    no_sender = reason(issuer_quote=None, instruction_quote="Pay your house tax")
    assert sender not in no_sender and due in no_sender and "Sunil Yadav" in no_sender
    # neither: only the bank's own record is left
    neither = reason(issuer_quote=None, instruction_quote=None)
    assert sender not in neither and due not in neither and "Sunil Yadav" in neither
    for text in (both, no_sender, neither):
        assert text.endswith(".") or text.endswith("।")


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_the_account_reason_is_dropped_without_an_account_in_the_message(lang):
    card = build_card(_amber([_payee_not_sender()]),
                      _tax_claim(issuer_quote="Municipal Corporation", instruction_quote="Pay your house tax",
                                 account=False), lang)
    assert card.reasons == [] and "Sunil Yadav" not in card.read_aloud


def test_the_card_route_for_a_due_names_the_official_place_even_without_a_sender():
    """A challan with no sender read still hands her the e-challan site, never the generic "authority" route."""
    claim = X.extract("Dear user, your vehicle HR26AB1234 has a pending e-challan of Rs 500. Pay immediately.")
    assert claim.claimed_issuer == Issuer.NONE
    grey = Verdict(outcome=Outcome.GREY, headline_en="Could not confirm. Check via the official channel",
                   headline_hi="पुष्टि नहीं हो सकी। आधिकारिक माध्यम से जाँच करें", explanation="built by hand",
                   policy_version="test", signals=[])
    assert "echallan.parivahan.gov.in" in build_card(grey, claim, "en").do_now
    assert "echallan.parivahan.gov.in" in build_card(grey, claim, "hi").do_now
