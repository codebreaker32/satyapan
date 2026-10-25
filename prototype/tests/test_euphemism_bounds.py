"""The widened instruction verbs, held to both edges by adversarial probes.

TRANSFER_TO_ACCOUNT was widened to the euphemism family (park, place, move, remit, route, consolidate, shift,
deposit and the Hinglish and Devanagari equivalents), because a textbook digital-arrest script that said "park your
entire liquid holdings" instead of "transfer" fell to GREY. Adversarial review then found both edges of that change:

1. The gap between a verb and its context excluded newlines, so the whole family died on a wrapped paste. A PDF, an
   OCR'd notice and a WhatsApp forward all arrive wrapped, which is most of what an officer actually sees.
2. The destination only had to be mentioned, not pointed at, so ordinary bank sentences ("you can move funds
   between your own accounts in the app") read as payment instructions and the officer's band printed that reading
   back as if the message had said it.

Both edges are now in the patterns, and both are pinned here. A false positive matters more than a false negative:
a wrong instruction puts money wording on a benign customer card.
"""
from __future__ import annotations

import pytest

from satyapan.extract import RulesExtractor
from satyapan.models import Instruction

# A line break is how real messages arrive. The continuation-starts-lowercase rule is the repo's existing OCR-wrap
# condition, so a header line still cannot pair up with an unrelated verb below it.
WRAPPED = [
    "You must park your entire liquid holdings in the designated verification\naccount 50100248891776.",
    "You are directed to remit the entire\nbalance of your savings to the designated account 50100248891776.",
    "10 lakh court registry akount me\njama karo.",
    "Shift the funds of Rs 9,00,000 into this\nescrow account today.",
]

# The scam always points at the account it wants: this one, the designated one, the authority's one, or a number.
POINTED = [
    "Park the entire amount of Rs 12,00,000 in the designated verification account.",
    "Shift the funds of Rs 9,00,000 into this escrow account.",
    "Move your full balance to account 50100248891776 right now.",
    "Remit the entire amount to the custody account mentioned below.",
    "Pura paisa daal do is account me abhi.",
    "is account me bhej dein pura paisa.",
    "पूरी राशि इस खाते में जमा करें।",
    "यह रकम इस खाते में भेजें।",
]

# Ordinary bank sentences. Each one carries a money word, a destination word and a widened verb, and each one must
# still read as nothing: the account they name is the customer's own, not one the sender is pointing at.
BENIGN = [
    "You can move funds between your own accounts in the app.",
    "Please move your savings to the new account at our branch for a better rate.",
    "To close your account, please move the balance out first.",
    "We can consolidate your two savings accounts into one account.",
    "We will shift your account and its balance to the Andheri branch next month.",
    "My father wants to move his savings into my account; is that allowed?",
    "Collect the deposit slip from counter 3 at the branch.",
    "Please park the car in the visitor bay before 9 am.",
    "फॉर्म जमा करें और रसीद ले लें।",
]


@pytest.fixture(scope="module")
def ex() -> RulesExtractor:
    return RulesExtractor()


@pytest.mark.parametrize("text", WRAPPED)
def test_a_line_break_does_not_kill_the_instruction(ex, text):
    """The widened family used to work only on unwrapped text."""
    claim = ex.extract(text)
    assert claim.instruction == Instruction.TRANSFER_TO_ACCOUNT, f"a wrapped paste lost its instruction: {text!r}"
    assert claim.instruction_span is not None
    assert claim.text[claim.instruction_span.start:claim.instruction_span.end] == claim.instruction_span.text


@pytest.mark.parametrize("text", POINTED)
def test_an_account_the_sender_points_at_is_read_as_an_instruction(ex, text):
    claim = ex.extract(text)
    assert claim.instruction == Instruction.TRANSFER_TO_ACCOUNT, f"missed a pointed destination: {text!r}"


@pytest.mark.parametrize("text", BENIGN)
def test_an_ordinary_bank_sentence_is_not_a_payment_instruction(ex, text):
    claim = ex.extract(text)
    assert claim.instruction == Instruction.NONE, (
        f"a benign sentence was read as an instruction to pay: {text!r} -> "
        f"{claim.instruction.value} from {claim.instruction_span.text if claim.instruction_span else None!r}"
    )


# ---- the second set of added verbs -------------------------------------------------------------------------
# A romanised-Marathi probe ("Rs 6,50,000 tya Customs Clearance Account 39920114477 var wire kara")
# returned instruction NONE and scored GREY, because "wire" was not in the family. "push", "credit this account
# with" and "arrange the settlement of" were on the same backlog line (decisions.md). Two of the four were
# removed again; see DROPPED_19_OCT below.
#
# Each one keeps the euphemism family's discipline: bounded on BOTH sides of the verb, gated on a money word AND a
# POINTED-AT destination, and carrying a negative probe that was genuinely at risk. Two of them needed a fourth
# gate of their own and the negative probes below are the reason:
#   - "wire" is also a noun, and the noun runs the other way ("the incoming wire of Rs 4,20,000 has been
#     credited to this account" is an inward-remittance advice carrying all three context words), so a
#     determiner or an arrival adjective in front of it means it is not the verb.
#   - "credit ... with" and "arrange the settlement of" must head a clause. "We will credit this account with
#     the full amount of Rs 4,20,000 on maturity" carries every other gate; what separates it from the demand is
#     that it has a subject in front of the verb.
NEW_VERBS = [
    ("wire", "Wire Rs 6,50,000 to the designated clearance account 39920114477 today.",
     "The incoming wire of Rs 4,20,000 has been credited to this account."),
    ("wire (romanised Marathi, verb last)",
     "Rs 6,50,000 tya Customs Clearance Account 39920114477 var wire kara, nahitar udya arrest hoil.",
     "A wire of Rs 2,00,000 arrived in this account yesterday from your employer."),
    ("arrange the settlement of",
     "You are directed to arrange the settlement of Rs 6,50,000 in the designated clearance account.",
     "We will arrange the settlement of your claim for Rs 4,20,000 in this account by Friday."),
]

# ---- the two forms that came out again, and the probes that took them out -----------------------------------
# The order-head gate above discriminates ORDER from REPORT, which is what the two negative probes it was
# written against are ("We will credit this account with...", "The app will push a notification..."). It does
# not discriminate scam from benign, and a bank's own recovery letter is a polite order. These two sentences are
# the benign twins, and they are not separable by form from the demands the gate was built to read:
#     benign  "Kindly credit this account with Rs 2,50,000 before 30 November to regularise your loan."
#     demand  "Credit this account with Rs 6,50,000 before 4 pm."
# On a message that claims to be the bank, reading either one takes the verdict to RED by construction, and the
# card then says "Please stop. Do not send this money now" on the bank's own letter.
#
# So BOTH columns are asserted silent. The demand column is a deliberate false negative, recorded here rather
# than hidden: the engine is deliberately narrower here, and a later change that re-adds either form has to
# come past the benign twin to do it. The demands still reach the officer through everything else the message
# says (an account the beneficiary look-up can check, a claimed owner, pressure cues, the flag itself).
DROPPED_19_OCT = [
    ("push", "Push the entire balance of Rs 9,00,000 into this escrow account now.",
     "Demo Bank: You must push Rs 12,000 into the designated EMI collection account 50100234567891 "
     "before 25 November."),
    ("credit this account with", "Credit this account with Rs 6,50,000 before 4 pm.",
     "Demo Bank Loan Recovery Cell: Kindly credit this account with Rs 2,50,000 before 30 November to "
     "regularise your loan. Account 3001122334455."),
]


@pytest.mark.parametrize("verb,demand,benign", DROPPED_19_OCT, ids=[v for v, _, _ in DROPPED_19_OCT])
def test_a_dropped_form_reads_nothing_in_either_direction(ex, verb, demand, benign):
    for text in (demand, benign):
        c = ex.extract(text)
        assert c.instruction == Instruction.NONE, (
            f"{verb} is back in the family: {text!r} -> {c.instruction.value} from "
            f"{c.instruction_span.text if c.instruction_span else None!r}. Its benign twin is the other half of "
            f"this pair, and on a bank-claimed message reading it is RED.")


def test_the_dropped_forms_were_live_and_the_drop_is_what_silences_them():
    """Not a tautology: rebuild each dropped form and show it matching the benign bank order it took out.

    Without this, deleting the forms from MOVE_EUPHEMISM and deleting the test above would both be green, and
    the record of why the engine is narrower would be a comment nobody has to keep true.
    """
    import re

    from satyapan import extract as X

    for pattern in X._DROPPED_ORDER_FORMS:
        hits = [b for _v, _d, b in DROPPED_19_OCT if re.search(pattern, b, re.I)]
        assert hits, f"the dropped form {pattern[:40]!r} no longer matches any benign bank order"
    assert all(p not in X.MOVE_EUPHEMISM for p in X._DROPPED_ORDER_FORMS), "a dropped form is back in the family"
    assert X._PUSH_VERB not in X._MOVE_VERB, "push is back in the verb list"


@pytest.mark.parametrize("verb,scam,benign", NEW_VERBS, ids=[v for v, _, _ in NEW_VERBS])
def test_a_new_verb_reads_the_demand(ex, verb, scam, benign):
    c = ex.extract(scam)
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT, f"{verb}: {scam!r}"
    assert c.text[c.instruction_span.start:c.instruction_span.end] == c.instruction_span.text


@pytest.mark.parametrize("verb,scam,benign", NEW_VERBS, ids=[v for v, _, _ in NEW_VERBS])
def test_a_new_verb_stays_silent_on_an_ordinary_bank_sentence(ex, verb, benign, scam):
    c = ex.extract(benign)
    assert c.instruction == Instruction.NONE, (
        f"{verb}: a benign sentence was read as an instruction to pay: {benign!r} -> {c.instruction.value} "
        f"from {c.instruction_span.text if c.instruction_span else None!r}")


def test_the_new_verbs_negative_probes_were_genuinely_at_risk():
    """Not a tautology: each negative probe carries the verb, a money word and the word "account".

    A negative probe that was never at risk proves nothing, as recorded in decisions.md ("park the car in the
    visitor bay" has neither context word). This asserts the probes above are
    the other kind: every one of them would match the family with its extra gate removed.
    """
    import re

    from satyapan import extract as X

    for verb, _scam, benign in NEW_VERBS:
        assert re.search(X._MONEY, benign, re.I), f"{verb}: no money word in the negative probe"
        assert re.search(X._DEST, benign, re.I), f"{verb}: no destination word in the negative probe"
    # the two the noun/order gates exist for: without the gate, the loose family matches the benign sentence
    loose_wire = rf"(?<![\w])wires?(?![a-z]){X._GAP}{X._BOTH_CTX}|{X._BOTH_CTX}{X._GAP}(?<![\w])wires?(?![a-z])"
    assert re.search(loose_wire, "The incoming wire of Rs 4,20,000 has been credited to this account.", re.I), \
        "the loose wire pattern should match the advice, otherwise the determiner gate proves nothing"
    loose_settle = rf"{X._SETTLE_DEMAND}{X._GAP}{X._BOTH_CTX}"
    assert re.search(loose_settle, "We will arrange the settlement of your claim for Rs 4,20,000 in this account "
                                   "by Friday.", re.I), \
        "the loose settlement phrase should match the report, otherwise the order-head gate proves nothing"


def test_the_pointer_requirement_is_what_drops_the_benign_sentence():
    """Not a tautology: without the pointed-destination requirement the benign sentence reads as an instruction.

    Rebuilds the family the way it was before the pointed-destination fix (bare destination) and shows it firing, so a
    future edit that drops the requirement fails here instead of shipping money wording onto a benign card.
    """
    import re

    from satyapan import extract as X

    loose = rf"{X._DEST}{X._GAP}{X._MOVE_VERB}{X._GAP}{X._MONEY}"
    benign = "To close your account, please move the balance out first."
    assert re.search(loose, benign, re.I), "the loose pattern should match — otherwise this test proves nothing"
    assert RulesExtractor().extract(benign).instruction == Instruction.NONE
