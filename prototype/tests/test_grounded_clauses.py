"""A card clause that describes the customer's message must rest on a span.

Two judge probes in pass 3 got cards that said things their messages did not say:

- a Customs/NDPS parcel scam demanding a "case verification charge": the extractor had matched `\\binvest` inside
  "investigation", so the Hindi card read "यह संदेश ... निवेश करने को कह रहा है" — this message is asking you to
  invest. The message demanded a clearance fee.
- an EPFO pension-release notice in Devanagari read as BANK_SELF: the card promised "We will call your relationship
  manager from the bank's own number to confirm", and there is no relationship manager anywhere in that message.

The extractor's misreads are fixed in the extractor. What is fixed here is the card asserting a clause with nothing
to point at. The rule: a clause that describes the message (it claims to be from X, it asks you to do Y, the account
belongs to Z) renders only when the claim carries a verbatim span for it; otherwise it is dropped, never guessed,
and what is left is still a sentence in both languages. A reason that loses everything is dropped whole and the
next-ranked signal moves up, so the card still carries up to three.

Enforced in `card.ground_reason` / `card.GROUNDED_CLAUSES`, called by `build_card` before the reasons are cut to
three. The guard cannot be a tautology: `test_the_guard_is_what_drops_the_clause` renders the same claim through
the handler and with the handler removed, and asserts the two differ.
"""
from __future__ import annotations

import re

import pytest

from satyapan.card import GROUNDED_CLAUSES, RM_IN_MESSAGE, build_card, ground_reason, grounded_entities
from satyapan.models import (Claim, ClaimedOwner, Family, Grounded, Instruction, Issuer, Outcome, Payee, Severity,
                             Signal, Span, Verdict)
from satyapan.rulebook import load_rulebook, make_signal
from tests.conftest import SCENARIOS, run_scenario_id

BOOK = load_rulebook()

# What each message-describing clause says in each language, and the claim field it must rest on. The card may name
# the entity on the left only when the span on the right is a verbatim quote of the message.
ENTITY_WORDS = {
    "issuer": {
        Issuer.CUSTOMS: ["Customs", "कस्टम विभाग"],
        Issuer.ED: ["the Enforcement Directorate", "प्रवर्तन निदेशालय"],
        Issuer.CBI: ["the CBI", "सीबीआई"],
        Issuer.RBI: ["RBI"],
        Issuer.COURT: ["a court", "अदालत"],
        Issuer.TRANSPORT: ["the traffic police or transport department", "यातायात पुलिस या परिवहन विभाग"],
        Issuer.MUNICIPAL: ["the municipal corporation", "नगर निगम"],
        Issuer.BANK_SELF: ["your bank", "आपका बैंक"],
    },
    "instruction": {
        Instruction.INVEST_FOR_RETURNS: ["an investment", "निवेश करने"],
        Instruction.MOVE_FD: ["moving your FD", "FD तोड़कर"],
        Instruction.TRANSFER_TO_ACCOUNT: ["a transfer to an account", "किसी खाते में पैसे भेजने"],
        Instruction.PAY_FEE_TO_VERIFY: ["a fee to verify", "सत्यापन शुल्क देने"],
        Instruction.RETURN_EXCESS_CREDIT: ["returning money", "पैसे वापस भेजने"],
        Instruction.PAY_CHALLAN: ["paying a traffic challan", "ट्रैफ़िक चालान भरने को"],
        Instruction.PAY_LOCAL_TAX: ["paying property or house tax", "प्रॉपर्टी या हाउस टैक्स भरने"],
    },
    "claimed_owner": {
        ClaimedOwner.RBI: ["belongs to RBI", "RBI का खाता"],
        ClaimedOwner.GOVT: ["belongs to the government", "सरकार का खाता"],
        ClaimedOwner.COURT: ["belongs to a court", "अदालत का खाता"],
        ClaimedOwner.AGENCY: ["belongs to a government agency", "सरकारी एजेंसी का खाता"],
        ClaimedOwner.BANK: ["belongs to the bank", "बैंक का खाता"],
    },
}
RM_WORDS = ["relationship manager", "रिलेशनशिप मैनेजर"]


def entities_named_in(card) -> set[str]:
    """Which message-describing entities the card's reasons actually name, in this card's language."""
    text = " ".join(r.text for r in card.reasons)
    named = set()
    for entity, table in ENTITY_WORDS.items():
        for value, words in table.items():
            if any(w in text for w in words):
                named.add(entity)
    if any(w in text for w in RM_WORDS):
        named.add("relationship_manager")
    return named


def allowed_entities(claim: Claim) -> set[str]:
    """What the claim can point at: a grounded span for each field, and for the relationship manager the words in
    the message itself (the party is not a claim field, so the message naming it is the ground truth)."""
    allowed = set(grounded_entities(claim))
    allowed.discard("payee_account")          # an account number is never one of the words above
    if RM_IN_MESSAGE.search(claim.text):
        allowed.add("relationship_manager")
    return allowed


# ---------------------------------------------------------------- the whole demo, every language

@pytest.mark.parametrize("sid", sorted(SCENARIOS))
@pytest.mark.parametrize("lang", ["hi", "en"])
def test_every_scenario_card_only_names_entities_the_claim_can_point_at(engine, sid, lang):
    case = run_scenario_id(engine, sid)
    card = engine.card(case, lang)
    named = entities_named_in(card)
    allowed = allowed_entities(case.claim)
    assert named <= allowed, f"{sid} ({lang}): card names {sorted(named - allowed)} with no span for it"


# ---------------------------------------------------------------- adversarial claims, built by hand

LAW_EN = "There is no “digital arrest” in Indian law, and no government agency demands money on a call."
LAW_HI = "भारतीय क़ानून में “डिजिटल अरेस्ट” जैसा कुछ नहीं है, और कोई सरकारी एजेंसी कॉल पर पैसे नहीं माँगती।"
PROBE_TEXT = ("Customs department here. A parcel in your name was seized under NDPS and an investigation has been "
              "opened. Pay the case verification charge of Rs 2,40,000 immediately.")


def _span(text: str, inside: str) -> Span:
    i = inside.index(text)
    return Span(text=text, start=i, end=i + len(text))


def _claim(*, text: str = PROBE_TEXT, issuer=Issuer.NONE, issuer_quote: str | None = None,
           instruction=Instruction.NONE, instruction_quote: str | None = None,
           owner=ClaimedOwner.UNKNOWN, owner_quote: str | None = None, account: str | None = None) -> Claim:
    payee = Payee(claimed_owner=owner)
    if owner_quote:
        payee.claimed_owner_span = _span(owner_quote, text)
    if account:
        payee.account = Grounded(value=account, span=_span(account, text))
    claim = Claim(source="text", text=text, claimed_issuer=issuer, instruction=instruction, payee=payee)
    if issuer_quote:
        claim.issuer_span = _span(issuer_quote, text)
    if instruction_quote:
        claim.instruction_span = _span(instruction_quote, text)
    return claim


def _agency_signal() -> Signal:
    return make_signal(BOOK, "R-AGENCY-PAY", {"evidence_key": "claim", "issuer_en": "Customs", "issuer_hi": "कस्टम विभाग",
                                              "instruction_en": "an investment", "instruction_hi": "निवेश करने को"})


def _amber(signals: list[Signal]) -> Verdict:
    return Verdict(outcome=Outcome.AMBER, headline_en="Verify before paying", headline_hi="भुगतान से पहले पुष्टि करें",
                   explanation="built by hand", policy_version="test", signals=signals)


@pytest.mark.parametrize("lang, law", [("en", LAW_EN), ("hi", LAW_HI)])
def test_an_instruction_with_no_span_loses_the_instruction_clause(lang, law):
    """The Customs probe once the instruction is not grounded: the authority stays, the demand goes."""
    claim = _claim(issuer=Issuer.CUSTOMS, issuer_quote="Customs", instruction=Instruction.INVEST_FOR_RETURNS)
    card = build_card(_amber([_agency_signal()]), claim, lang)
    text = card.reasons[0].text
    assert text.startswith(law)
    assert "invest" not in text and "निवेश" not in text
    assert "Customs" in text or "कस्टम विभाग" in text
    assert text.endswith("।") or text.endswith(".")


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_an_issuer_with_no_span_loses_the_issuer_clause(lang):
    claim = _claim(issuer=Issuer.CUSTOMS, instruction=Instruction.INVEST_FOR_RETURNS, instruction_quote="invest")
    text = build_card(_amber([_agency_signal()]), claim, lang).reasons[0].text
    assert "Customs" not in text and "कस्टम विभाग" not in text
    assert "an investment" in text or "निवेश करने" in text


@pytest.mark.parametrize("lang, law", [("en", LAW_EN), ("hi", LAW_HI)])
def test_a_claim_with_neither_span_keeps_only_the_clause_about_the_law(lang, law):
    claim = _claim(issuer=Issuer.CUSTOMS, instruction=Instruction.INVEST_FOR_RETURNS)
    card = build_card(_amber([_agency_signal()]), claim, lang)
    assert card.reasons[0].text == law
    assert not entities_named_in(card)


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_a_stale_span_is_not_support(lang):
    """A span that no longer quotes the message (an officer correction, an LLM extractor) supports nothing."""
    claim = _claim(issuer=Issuer.CUSTOMS, instruction=Instruction.INVEST_FOR_RETURNS)
    claim.instruction_span = Span(text="invest in our scheme", start=0, end=20)   # not what the text says there
    assert grounded_entities(claim) == set()
    text = build_card(_amber([_agency_signal()]), claim, lang).reasons[0].text
    assert "invest" not in text and "निवेश" not in text


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_a_reason_that_loses_everything_is_dropped_and_the_next_signal_moves_up(lang):
    """R-PAYEE-NAME is about an account the message carried. With no grounded account the reason has nothing to
    stand on, so it goes whole and the card still fills up to three."""
    text = "Deposit the amount to the account in the notice."
    claim = Claim(source="text", text=text)
    payee_name = make_signal(BOOK, "R-PAYEE-NAME", {"evidence_key": "bank:name_lookup", "claimed_en": "RBI",
                                                    "claimed_hi": "RBI", "holder": "Vikas Traders",
                                                    "holder_type_en": "a private firm", "holder_type_hi": "एक निजी फ़र्म"})
    caller = make_signal(BOOK, "R-CALLER-1600", {"evidence_key": "claim", "caller": "+919812345678"})
    card = build_card(_amber([payee_name, caller]), claim, lang)
    assert [r.rule_id for r in card.reasons] == ["R-CALLER-1600"]
    assert "Vikas Traders" not in card.read_aloud


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_an_ungrounded_owner_keeps_the_bank_record_half_of_the_payee_reason(lang):
    """The bank's name look-up is a record, not a claim about the message, so it still speaks — without the
    "you were told it belongs to RBI" half, which is the part only the message could supply."""
    text = "Deposit to account 50100123456789 today."
    claim = _claim(text=text, account="50100123456789", owner=ClaimedOwner.RBI)
    payee_name = make_signal(BOOK, "R-PAYEE-NAME", {"evidence_key": "bank:name_lookup", "claimed_en": "RBI",
                                                    "claimed_hi": "RBI", "holder": "Vikas Traders",
                                                    "holder_type_en": "a private firm", "holder_type_hi": "एक निजी फ़र्म"})
    text_out = build_card(_amber([payee_name]), claim, lang).reasons[0].text
    assert "Vikas Traders" in text_out
    assert "RBI" not in text_out
    assert len(re.findall(r"[.।]", text_out)) == 1


# ---------------------------------------------------------------- the relationship-manager promise

def _rm_signal(rm: str = "Rohit Verma") -> Signal:
    return make_signal(BOOK, "R-BANK-RM-PHONE", {"evidence_key": "bank:outbound_log", "rm": rm})


RM_MESSAGE = "Main Demo Bank se aapka relationship manager Rohit bol raha hoon. FD tod kar paisa bhej dein."
EPFO_MESSAGE = "EPFO पेंशन विभाग से सूचना। आपका पेंशन खाता बंद कर दिया गया है। सत्यापन शुल्क तुरंत जमा करें।"


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_rm_promise_renders_when_the_case_carries_that_party(lang):
    claim = Claim(source="text", text=RM_MESSAGE, claimed_issuer=Issuer.BANK_SELF,
                  issuer_span=_span("Demo Bank", RM_MESSAGE))
    text = build_card(_amber([_rm_signal()]), claim, lang).reasons[0].text
    assert any(w in text for w in RM_WORDS)
    assert len(text.split(". ")) >= 2 or "।" in text


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_rm_promise_is_dropped_when_the_message_has_no_relationship_manager(lang):
    """The EPFO probe: BANK_SELF came from "खाता बंद", the sender number happened to sit in the bank's RM
    directory, and the card promised a call to a relationship manager this message never mentions."""
    claim = Claim(source="text", text=EPFO_MESSAGE, claimed_issuer=Issuer.BANK_SELF,
                  issuer_span=_span("खाता बंद", EPFO_MESSAGE))
    card = build_card(_amber([_rm_signal()]), claim, lang)
    text = card.reasons[0].text
    assert not any(w in text for w in RM_WORDS)
    assert "relationship_manager" not in entities_named_in(card)
    assert text.endswith("।") or text.endswith(".")


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_rm_promise_is_dropped_when_the_bank_has_no_rm_on_record(lang):
    """The other half: the message does name an RM, but the bank's directory named nobody to call."""
    claim = Claim(source="text", text=RM_MESSAGE, claimed_issuer=Issuer.BANK_SELF,
                  issuer_span=_span("Demo Bank", RM_MESSAGE))
    text = build_card(_amber([_rm_signal(rm="")]), claim, lang).reasons[0].text
    assert not any(w in text for w in RM_WORDS)


# ---------------------------------------------------------------- the open-set body: what was read, not who sent it
#
# R-STATE-NAME-PAY's three sentences are the practice, the reading and our own check, and only the middle one
# describes the message. These assert the shape of all four grounding combinations and, more importantly, that
# nothing in any of them says the sender is or claims to be a government body. That sentence was on the card for
# one pass, anchored on an open-set net that reads the FORM of a name, and it put "this message claims to be a
# government body" on an ordinary corporate department's letter.

OPEN_TEXT = ("Acme Recovery and Fraud Investigation Unit, Mumbai. You are directed to arrange the settlement of "
             "Rs 6,50,000 in the official government verification account 30011223344556 today.")
PRACTICE_EN = "No government agency demands money on a call."
PRACTICE_HI = "कोई सरकारी एजेंसी कॉल पर पैसे नहीं माँगती।"
UNCONFIRMED_EN = "We could not confirm who sent it."
UNCONFIRMED_HI = "यह संदेश किसने भेजा, इसकी पुष्टि हम नहीं कर सके।"
# The sentence this rule exists in order NOT to say, in both languages, plus the near variants of it.
NEVER_SAID = ["claims to be", "दावा करता है", "a government body", "कोई सरकारी संस्था", "सरकारी संस्था होने"]


def _state_name_signal() -> Signal:
    return make_signal(BOOK, "R-STATE-NAME-PAY", {"evidence_key": "claim",
                                                  "instruction_en": "a transfer to an account",
                                                  "instruction_hi": "किसी खाते में पैसे भेजने को"})


def _open_claim(*, issuer_quote: str | None, instruction_quote: str | None) -> Claim:
    return _claim(text=OPEN_TEXT, issuer=Issuer.OTHER, issuer_quote=issuer_quote,
                  instruction=Instruction.TRANSFER_TO_ACCOUNT, instruction_quote=instruction_quote)


@pytest.mark.parametrize("lang", ["hi", "en"])
@pytest.mark.parametrize("issuer_quote", [None, "Fraud Investigation Unit"])
@pytest.mark.parametrize("instruction_quote", [None, "arrange the settlement of"])
def test_the_open_set_reason_never_says_who_the_sender_is(lang, issuer_quote, instruction_quote):
    """Every grounding combination, including both spans present. None of them may accuse the sender."""
    claim = _open_claim(issuer_quote=issuer_quote, instruction_quote=instruction_quote)
    text = build_card(_amber([_state_name_signal()]), claim, lang).reasons[0].text
    for phrase in NEVER_SAID:
        assert phrase not in text, f"{lang}: the open-set reason said {phrase!r}: {text!r}"
    # the two sentences that are not about the message survive every combination
    assert (PRACTICE_HI if lang == "hi" else PRACTICE_EN) in text
    assert (UNCONFIRMED_HI if lang == "hi" else UNCONFIRMED_EN) in text
    assert text == text.strip() and text[-1] in ".।"
    assert not re.search(r"\b(and|to|for)\s*[.।]$", text)
    assert " और ।" not in text and not text.endswith("और।")


@pytest.mark.parametrize("lang,name_clause,instr_words", [("en", "carries a government-sounding name", "a transfer"),
                                                          ("hi", "सरकारी दफ़्तर जैसा नाम", "किसी खाते में पैसे भेजने")])
def test_the_open_set_reason_drops_the_half_it_cannot_point_at(lang, name_clause, instr_words):
    both = build_card(_amber([_state_name_signal()]),
                      _open_claim(issuer_quote="Fraud Investigation Unit",
                                  instruction_quote="arrange the settlement of"), lang).reasons[0].text
    assert name_clause in both and instr_words in both

    no_instr = build_card(_amber([_state_name_signal()]),
                          _open_claim(issuer_quote="Fraud Investigation Unit", instruction_quote=None),
                          lang).reasons[0].text
    assert name_clause in no_instr and instr_words not in no_instr

    no_name = build_card(_amber([_state_name_signal()]),
                         _open_claim(issuer_quote=None, instruction_quote="arrange the settlement of"),
                         lang).reasons[0].text
    assert name_clause not in no_name and instr_words in no_name

    neither = build_card(_amber([_state_name_signal()]),
                         _open_claim(issuer_quote=None, instruction_quote=None), lang).reasons[0].text
    assert name_clause not in neither and instr_words not in neither
    assert neither.count(".") + neither.count("।") == 2, f"only the two non-message sentences survive: {neither!r}"


def test_the_open_set_body_name_never_reaches_the_reason():
    """The name is attacker-controlled text. It lives in the span the officer reads, and nowhere else."""
    claim = _open_claim(issuer_quote="Fraud Investigation Unit", instruction_quote="arrange the settlement of")
    signal = _state_name_signal()
    assert "issuer_en" not in signal.detail and "issuer_hi" not in signal.detail
    for lang in ("hi", "en"):
        text = build_card(_amber([signal]), claim, lang).reasons[0].text
        for word in ("Acme", "Fraud", "Investigation", "Unit", "Recovery"):
            assert word not in text, f"{lang}: the body's own name reached the card: {text!r}"


# ---------------------------------------------------------------- the guard is the thing doing the work

@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_guard_is_what_drops_the_clause(lang, monkeypatch):
    """Delete the guard and the same claim gets the old, false card back. Without this the tests above could pass
    on a rulebook that never carried the clause at all."""
    claim = _claim(issuer=Issuer.CUSTOMS, issuer_quote="Customs", instruction=Instruction.INVEST_FOR_RETURNS)
    verdict = _amber([_agency_signal()])
    guarded = build_card(verdict, claim, lang).reasons[0].text

    monkeypatch.delitem(GROUNDED_CLAUSES, "R-AGENCY-PAY")
    unguarded = build_card(verdict, claim, lang).reasons[0].text

    assert guarded != unguarded, "removing the guard changed nothing: the clause was never being dropped"
    assert ("an investment" in unguarded or "निवेश करने" in unguarded)
    assert "invest" not in guarded and "निवेश" not in guarded


def test_every_guarded_rule_still_carries_the_clause_the_guard_expects():
    """The guard rewrites sentences of copy that Compliance owns in the rulebook. If that copy is reworded, this
    fails loudly instead of the guard silently doing nothing."""
    expected = {
        "R-AGENCY-PAY": ["This message claims to be {issuer_en} and asks for {instruction_en}.",
                         "यह संदेश {issuer_hi} होने का दावा करता है और {instruction_hi} कह रहा है।"],
        "R-STATE-NAME-PAY": ["This message carries a government-sounding name and asks for {instruction_en}.",
                             "इस संदेश पर सरकारी दफ़्तर जैसा नाम लिखा है और यह {instruction_hi} कह रहा है।"],
        "R-BANK-NEVER-MOVE-FD": ["That instruction does not come from us.", "यह निर्देश हमारी ओर से नहीं है।"],
        "R-PAYEE-NAME": ["The account you were told belongs to {claimed_en}", "जिसे {claimed_hi} का खाता बताया गया है"],
        "R-PAYEE-NOT-SENDER": ["This message is in the name of {issuer_en}", "यह संदेश {issuer_hi} के नाम से है"],
        "R-BANK-RM-PHONE": ["We will call your relationship manager", "आपके रिलेशनशिप मैनेजर को"],
    }
    assert set(expected) == set(GROUNDED_CLAUSES), "a guarded rule has no copy check (or the other way round)"
    for rule_id, (en, hi) in expected.items():
        meta = BOOK.meta(rule_id)
        assert en in meta.reason_en, f"{rule_id}: the English clause the guard edits is gone: {en!r}"
        assert hi in meta.reason_hi, f"{rule_id}: the Hindi clause the guard edits is gone: {hi!r}"


def test_an_unguarded_rule_reason_is_passed_through_untouched():
    claim = Claim(source="text", text="x")
    s = make_signal(BOOK, "R-LEDGER", {"evidence_key": "bank:ledger"})
    assert ground_reason(s, claim, hi=False) == s.reason_en
    assert ground_reason(s, claim, hi=True) == s.reason_hi


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_a_dropped_clause_never_leaves_a_half_sentence(lang):
    """Every shape the guard can produce has to end on a sentence mark and carry no dangling conjunction."""
    for issuer_quote in (None, "Customs"):
        for instruction_quote in (None, "invest"):
            claim = _claim(issuer=Issuer.CUSTOMS, issuer_quote=issuer_quote,
                           instruction=Instruction.INVEST_FOR_RETURNS, instruction_quote=instruction_quote)
            text = build_card(_amber([_agency_signal()]), claim, lang).reasons[0].text
            assert text == text.strip() and text[-1] in ".।"
            assert not re.search(r"\b(and|to|for)\s*[.।]$", text)
            assert " और ।" not in text and not text.endswith("और।")


def test_grounded_entities_reads_the_fields_models_says_carry_a_span():
    claim = _claim(issuer=Issuer.CUSTOMS, issuer_quote="Customs", instruction=Instruction.PAY_FEE_TO_VERIFY,
                   instruction_quote="verification charge", owner=ClaimedOwner.AGENCY, owner_quote="Customs")
    assert grounded_entities(claim) == {"issuer", "instruction", "claimed_owner"}
    assert grounded_entities(Claim(source="text", text="")) == set()


def test_the_card_lint_still_runs_over_a_grounded_reason():
    """Dropping a clause must not slip past the forbidden-word lint: it runs on whatever text survives."""
    signal = Signal(rule_id="R-AGENCY-PAY", family=Family.F1, severity=Severity.HARD, evidence_key="claim",
                    reason_en="This notice is fake. This message claims to be Customs.",
                    reason_hi="यह नोटिस नकली है।", citation="c", citation_verified=True,
                    detail={"issuer_en": "Customs", "issuer_hi": "कस्टम विभाग"})
    claim = _claim(issuer=Issuer.CUSTOMS, issuer_quote="Customs")
    with pytest.raises(ValueError):
        build_card(_amber([signal]), claim, "en")
