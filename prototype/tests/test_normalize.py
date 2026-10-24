"""The input layer: homoglyphs, zero-width spaces, leetspeak, and the pattern bounds that go with them.

Every message in here is synthetic. They are rewrites of the probes a hackathon judge pasted through the engine
on 18 Oct 2026, which produced two wrong verdicts and two right verdicts for a false reason. No real bank,
customer or official text, no real official's name, no real case number.

The disguised probes are built by escaping the clean text (CY_O, ZWSP), never by pasting invisible characters
into this file, so a reviewer can see exactly what is in each one.
"""
from __future__ import annotations

import pytest

from satyapan.extract import RulesExtractor, ground
from satyapan.models import Instruction, Issuer, Outcome
from satyapan.normalize import fold, normalise
from tests.conftest import run_text

X = RulesExtractor(bank_names=("Demo Bank",))

ZWSP = "​"          # ZERO WIDTH SPACE
CY_O = "о"          # CYRILLIC SMALL LETTER O, the look-alike for Latin "o"

# ---- the judge's P6: Cyrillic "o" and zero-width spaces inside words --------------------------------------
P6 = (f"N{CY_O}tice fr{CY_O}m Enf{CY_O}rcement Direc{ZWSP}torate. Summ{CY_O}ns N{CY_O}. ED/DLZO/2026/4471 in "
      f"case ECIR/DLZO/18/2026. Y{CY_O}u must tra{ZWSP}nsf{ZWSP}er Rs 25,00,000 t{CY_O} the RBI "
      f"sup{ZWSP}ervisi{CY_O}n acc{CY_O}unt 50100248891776 IFSC HDFC0000123 immediately or face "
      f"arr{ZWSP}est under PMLA.")
# The clean-ASCII twin, derived from P6 so the two can never drift apart.
P6B = P6.replace(ZWSP, "").replace(CY_O, "o")

# ---- the judge's P3: a digital-arrest script whose only verb is a euphemism -------------------------------
P3 = ("This is the CBI cyber crime coordination cell. A case under NDPS Act has been registered against you, and "
      "you are under digital custody until the verification is complete. Do not disconnect this video call, and "
      "do not speak to your bank staff or to your family, the investigation is confidential. You must park your entire "
      "liquid holdings of Rs 38,00,000 in the designated verification account 50100248891776 IFSC HDFC0000123 "
      "before the hearing.")
# Same message, ordinary verb. This is the one that already worked, so it is P3's control.
P3_PLAIN = P3.replace("park your entire", "transfer your entire")


def _spans(claim):
    """Every span the extractor stored on this claim, with the field it belongs to."""
    out = [("issuer", claim.issuer_span), ("instruction", claim.instruction_span), ("channel", claim.channel_span),
           ("owner", claim.payee.claimed_owner_span)]
    for f in ("account", "ifsc", "vpa"):
        g = getattr(claim.payee, f)
        out.append((f, g.span if g else None))
    for f in ("summons_no", "passcode", "case_no", "issue_date"):
        g = getattr(claim.document_ids, f)
        out.append((f, g.span if g else None))
    out += [(f"amount[{i}]", a.span) for i, a in enumerate(claim.amounts)]
    out += [(f"url[{i}]", u.span) for i, u in enumerate(claim.urls)]
    out += [(f"cue:{k}", v) for k, v in claim.pressure_cues.items()]
    if claim.caller_number:
        out.append(("caller_number", claim.caller_number.span))
    return [(name, sp) for name, sp in out if sp is not None]


# ---------------- Fix 1: normalise before matching, keep the spans on the original ----------------

def test_every_stored_span_indexes_the_original_text_not_the_normalised_one():
    """The acceptance criterion. Matching runs on a folded copy; every quote must still be the characters that
    are really in the message, at the offsets they really sit at, or every leader line in the console lies."""
    c = X.extract(P6, source="ocr")
    names = _spans(c)
    assert len(names) >= 8, "the probe should fill most of the claim"
    for name, sp in names:
        assert c.text[sp.start:sp.end] == sp.text, name
    # and the mapping is doing real work: the instruction quote carries the zero-width spaces back with it
    assert ZWSP in c.instruction_span.text
    assert c.issuer_span.text.count(CY_O) >= 1
    # ground() is the engine's own check of the same property, and it must keep every field
    g = ground(c)
    assert len(_spans(g)) == len(names)


def test_homoglyph_probe_reads_the_same_as_its_clean_ascii_twin():
    a, b = X.extract(P6, source="ocr"), X.extract(P6B, source="ocr")
    assert (a.claimed_issuer, a.instruction) == (b.claimed_issuer, b.instruction) == (Issuer.ED, Instruction.TRANSFER_TO_ACCOUNT)
    assert a.payee.claimed_owner == b.payee.claimed_owner
    assert a.payee.account.value == b.payee.account.value == "50100248891776"
    assert a.payee.ifsc.value == b.payee.ifsc.value == "HDFC0000123"
    assert a.document_ids.summons_no.value == b.document_ids.summons_no.value
    assert set(a.pressure_cues) == set(b.pressure_cues)
    assert "arrest_threat" in a.pressure_cues


def test_homoglyph_probe_gets_the_same_verdict_as_its_clean_ascii_twin(engine):
    """P6 came back GREY while P6B came back AMBER on hard rules. Same message, same outcome, same rules."""
    disguised = run_text(engine, P6, source="ocr").verdict
    clean = run_text(engine, P6B, source="ocr").verdict
    assert disguised.outcome == clean.outcome
    assert disguised.outcome != Outcome.GREY
    assert [s.rule_id for s in disguised.signals] == [s.rule_id for s in clean.signals]


def test_leetspeak_behaves_like_the_plain_words():
    leet = "ED notice: you must transf3r Rs 25,00,000 to the RBI supervision account 50100248891776 or face arr3st."
    plain = leet.replace("transf3r", "transfer").replace("arr3st", "arrest")
    a, b = X.extract(leet), X.extract(plain)
    assert (a.claimed_issuer, a.instruction) == (b.claimed_issuer, b.instruction)
    assert a.instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert "arrest_threat" in a.pressure_cues
    for _, sp in _spans(a):
        assert a.text[sp.start:sp.end] == sp.text


@pytest.mark.parametrize("text", [
    "Rs 25,00,000", "Rs 1,00,00,000", "50100248891776", "IFSC HDFC0000123", "DEMO0001234",
    "helpline 1600033330", "ED/DLZO/2026/4471", "ECIR/DLZO/18/2026", "14-10-2026", "B2B", "H2O", "A1",
])
def test_the_leet_fold_never_touches_a_number_or_an_identifier(text):
    assert fold(text) == text


def test_numbers_survive_a_disguised_message_intact():
    c = X.extract(P6, source="ocr")
    assert c.payee.account.value == "50100248891776"          # the folded value is clean for a registry lookup
    assert ZWSP not in c.payee.account.value
    assert c.amounts and "25,00,000" in fold(c.amounts[0].span.text)
    assert c.caller_number is None


def test_the_index_map_is_exact_for_every_slice():
    probe = f"tra{ZWSP}nsf{ZWSP}er Rs 5,00,000 t{CY_O} acc{CY_O}unt"
    n = normalise(probe)
    assert len(n.origin) == len(n.text)
    for i in range(len(n.text)):
        s, e = n.map_span(i, i + 1)
        assert 0 <= s < e <= len(probe)
        assert n.quote(i, i + 1).endswith(probe[e - 1])      # the original character, zero-widths and all
    s, e = n.map_span(0, len(n.text))
    assert probe[s:e] == probe                                # a whole-string slice maps to the whole original


def test_devanagari_is_untouched_by_the_fold():
    hi = "नमस्कार, मैं सीबीआई से बोल रहा हूँ। पूरी राशि इस खाते में जमा करें।"
    assert fold(hi) == hi
    c = X.extract(hi)
    assert c.claimed_issuer == Issuer.CBI
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert c.language_hint == "hi"
    assert c.text[c.instruction_span.start:c.instruction_span.end] == c.instruction_span.text


# ---------------- Fix 2: patterns that were matching rubbish ----------------

def test_investigation_is_not_an_invitation_to_invest():
    """The unbounded r"\\binvest" read "the investigation is confidential" as an investment pitch, and the
    customer card then told a frightened customer, in Hindi, that she was being asked to invest."""
    for text in ["Please note that the investigation is confidential.",
                 "The investigating officer will contact your branch.",
                 "An investigator from the cyber cell has the file."]:
        assert X.extract(text).instruction != Instruction.INVEST_FOR_RETURNS, text
    c = X.extract("Invest 2 lakh for guaranteed returns in our gold scheme.")
    assert c.instruction == Instruction.INVEST_FOR_RETURNS
    c2 = X.extract("Your investment of Rs 2,00,000 will double in one month.")
    assert c2.instruction == Instruction.INVEST_FOR_RETURNS


@pytest.mark.parametrize("text", [
    "A case under NDPS Act has been registered against you.",
    "This is the CYBER CRIME COORDINATION CELL calling.",
    "Call the crime helpline for assistance.",
])
def test_a_case_number_needs_a_digit(text):
    """The judge got case_no = "under", "COORDINATION" and "helpline", and the console drew a "Case number"
    mark on each of them. A case or document number contains a digit."""
    d = X.extract(text).document_ids
    assert d.case_no is None, text
    assert d.summons_no is None and d.passcode is None


def test_a_real_case_or_summons_number_is_still_read():
    c = X.extract("Summon No. ED/DLZO/2026/4471 in case ECIR/DLZO/18/2026. Passcode: ZZZZ99.")
    assert c.document_ids.summons_no.value == "ED/DLZO/2026/4471"
    assert c.document_ids.case_no.value == "ECIR/DLZO/18/2026"
    assert c.document_ids.passcode.value == "ZZZZ99"
    c2 = X.extract("FIR no 0123/2026 has been registered at the cyber police station.")
    assert c2.document_ids.case_no.value == "0123/2026"


def test_a_passcode_is_never_an_english_word():
    # "Passcode unavailable" used to store passcode = "unavailable", which swapped the hard rule that fires
    # (R-ED-NO-PASSCODE) for a lookup on a passcode nobody ever wrote.
    assert X.extract("DIRECTORATE OF ENFORCEMENT. Summon No. ED/DLZO/2026/4471. Passcode unavailable.").document_ids.passcode is None


def test_today_is_not_an_instruction_to_break_the_fd():
    # r"tod" unbounded matched "today", so a maturity notice read as "break your FD"
    for text in ["Your fixed deposit matures today and will be renewed automatically.",
                 "Today your deposit interest was credited."]:
        assert X.extract(text).instruction == Instruction.NONE, text
    assert X.extract("FD tod ke pura paisa safe account me daal do.").instruction == Instruction.MOVE_FD


def test_arrest_keeps_its_boundary_but_still_reads_every_form():
    for text in ["You will face arrest tonight.", "He was arrested last week.", "We are arresting you now.",
                 "Aap arest ho jayenge."]:
        assert "arrest_threat" in X.extract(text).pressure_cues, text


# ---------------- Fix 3: the euphemism family, each verb with a positive and a negative probe ----------------

# (verb, a scam phrasing that must be read, a benign sentence with the same word that must NOT be)
VERB_PROBES = [
    ("park", "You must park the entire amount of Rs 12,00,000 in the verification account 50100248891776 today.",
     "Please park the car in the visitor bay before 9 am."),
    ("place", "Kindly place Rs 5,00,000 in the nodal account 50100248891776 before 4 pm.",
     "Place of birth must match the passport exactly."),
    ("move", "Move your full balance to account 50100248891776 right now.",
     "We move house next month, so please update my address."),
    ("shift", "Shift the funds of Rs 9,00,000 into this escrow account 50100248891776 immediately.",
     "The night shift supervisor will open the branch."),
    ("deposit", "Deposit Rs 2,00,000 in the clearance account 50100248891776 within one hour.",
     "Collect the deposit slip from counter 3 at the branch."),
    ("remit", "Remit the entire amount to the custody account 50100248891776 today.",
     "The remittance advice is attached for your records."),
    ("route", "Route your savings through the settlement account 50100248891776 tonight.",
     "The route map to our branch is on the website."),
    ("consolidate", "Consolidate all your funds into the monitoring account 50100248891776 at once.",
     "We consolidate the quarterly figures every Friday."),
    ("transfer under custody", "Transfer under custody Rs 4,00,000 to the designated account 50100248891776.",
     "Custody of the records stays with the branch manager."),
    ("move (not remove)", "Move the whole amount into account 50100248891776 before 6 pm.",
     "Remove the old nominee from the records, the account stays open."),
    ("bhej", "Rs 6,00,000 is account 50100248891776 me bhej do abhi.",
     "Shaadi ki photo bhej do."),
    ("jama kar", "Rs 3,00,000 is khate me jama kar dein aaj hi.",
     "Branch mein form jama kar dijiye."),
    ("daal", "Pura paisa is verification account me daal do.",
     "Chai mein cheeni daal do."),
    ("जमा कर", "पूरी राशि इस खाते में जमा करें।",
     "फॉर्म जमा करें और रसीद ले लें।"),
    ("भेज", "यह रकम इस खाते में भेजें।",
     "फोटो भेज दो।"),
    ("डाल", "सारा पैसा इस खाते में डाल दें।",
     "चाय में चीनी डाल दो।"),
    ("ट्रांसफ़र", "पूरी राशि इस खाते में ट्रांसफ़र करें।",
     "फ़ाइल दूसरी शाखा में ट्रांसफ़र हो गई है।"),
]


@pytest.mark.parametrize("verb,scam,_benign", VERB_PROBES, ids=[v for v, _, _ in VERB_PROBES])
def test_the_euphemism_is_read_as_a_payment_instruction(verb, scam, _benign):
    c = X.extract(scam)
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT, f"{verb}: {scam}"
    assert c.text[c.instruction_span.start:c.instruction_span.end] == c.instruction_span.text


@pytest.mark.parametrize("verb,_scam,benign", VERB_PROBES, ids=[v for v, _, _ in VERB_PROBES])
def test_the_same_verb_in_a_benign_sentence_is_not_an_instruction(verb, _scam, benign):
    """Not optional. A false positive here puts money wording on a benign customer card, and this repo has
    twice shipped a pattern that matched inside an unrelated word."""
    c = X.extract(benign)
    assert c.instruction == Instruction.NONE, f"{verb}: {benign}"


@pytest.mark.parametrize("text", [
    # the gate is a money word AND a destination word, in the same sentence as the verb
    "फॉर्म जमा करें, खाता संख्या वहाँ लिखी है।",
    "Your salary of Rs 42,000 was credited; collect the deposit slip for your account.",
    "Please place the passbook in the drawer and move the chair back.",
])
def test_one_context_word_on_its_own_is_not_enough(text):
    assert X.extract(text).instruction == Instruction.NONE, text


def test_park_probe_gets_the_same_verdict_as_the_transfer_probe(engine):
    """P3 was a textbook digital-arrest script and came back GREY because "park" was not a verb we knew."""
    euphemism = run_text(engine, P3).verdict
    plain = run_text(engine, P3_PLAIN).verdict
    assert euphemism.outcome == plain.outcome
    assert euphemism.outcome != Outcome.GREY
    assert [s.rule_id for s in euphemism.signals] == [s.rule_id for s in plain.signals]


def test_the_park_probe_reads_the_whole_chain():
    c = X.extract(P3)
    assert c.claimed_issuer == Issuer.CBI
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert c.payee.account.value == "50100248891776"
    assert {"arrest_threat", "secrecy", "isolation"} <= set(c.pressure_cues)
    assert c.document_ids.case_no is None, "\"A case under NDPS Act\" holds no case number"
    for _, sp in _spans(c):
        assert c.text[sp.start:sp.end] == sp.text


def test_a_spaced_account_number_is_not_truncated():
    """The pass-5 gate wrote "a c c o u n t  No 3 0 0 1 1 2 2 3 3 4 4 5 5 6" and got back a 12-digit account.

    De-spacing reconstitutes the keyword, which arms the account pattern on spaced digits; that pattern's window
    used to count characters, so the spaces ate the budget and a 14-digit number was silently cut to 12. A wrong
    identifier is worse than no identifier: it is what goes to the beneficiary name look-up, to the I4C suspect
    registry and into the signed evidence pack. The window now counts digits.
    """
    from satyapan.extract import RulesExtractor

    claim = RulesExtractor().extract("Send the money to a c c o u n t  No 3 0 0 1 1 2 2 3 3 4 4 5 5 6 today.")
    assert claim.payee.account is not None
    assert claim.payee.account.value == "30011223344556"
    sp = claim.payee.account.span
    assert claim.text[sp.start:sp.end] == sp.text, "the quote must still index the original characters"
    assert sp.text == "3 0 0 1 1 2 2 3 3 4 4 5 5 6", "and it quotes the spacing the message really has"


def test_grouped_and_plain_account_numbers_are_unchanged():
    from satyapan.extract import RulesExtractor

    ex = RulesExtractor()
    assert ex.extract("Transfer to account 30011223344556 today.").payee.account.value == "30011223344556"
    assert ex.extract("Deposit into A/c No. 5010 0248 8917 76 now.").payee.account.value == "50100248891776"
