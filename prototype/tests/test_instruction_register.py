"""The two ways an instruction vanished while the issuer was read correctly.

Both wrong verdicts had the same shape: `claimed_issuer` was right, `instruction` was NONE, and the message was
a textbook demand for money. They differ in where the demand hid.

- P4, the PASSIVE AND OBLIGATION REGISTER. "The sum of Rs 38,00,000 is required to be remitted to the account
  specified herein" came back GREY with instruction NONE, while its active control "You must remit Rs 38,00,000
  to the verification account" came back AMBER. "remit" was already a known verb, so the register was the only
  thing between the two readings, and forged summonses are written in exactly the register that was not read.
- P7, INTRA-WORD SPACING. "You must t r a n s f e r Rs 38,00,000 to the verification account 30011223344556"
  came back GREY with instruction NONE. Normalisation folds homoglyphs, zero-widths and leetspeak; spacing has
  no character to fold, so it passed through all of them.

Every message in this file is synthetic: invented text in the shape of a forged notice or an ordinary bank SMS.
No real bank, customer or official data, no real official's name, no real case or account number.

What the tests have to prove, in the repo's own order of importance:
1. each probe now reads as its active / unspaced control reads (the finding is closed);
2. a negative twin that was GENUINELY AT RISK still reads as nothing - it carries the money word, the
   destination word and the construction, and only the gate under test stops it. A negative with no money word
   and no destination ("park the car in the visitor bay") proves nothing;
3. every span still indexes and quotes the ORIGINAL message, including where the match was found in de-spaced
   coordinates (`claim.text[span.start:span.end] == span.text`);
4. neither test is a tautology: with the change reverted in place, each probe fails.
"""
from __future__ import annotations

import pytest

from satyapan.extract import RulesExtractor, ground
from satyapan.models import Instruction, Issuer, Outcome
from satyapan.normalize import fold
from tests.conftest import run_text
from tests.test_normalize import _spans

X = RulesExtractor(bank_names=("Demo Bank",))

# ---- probe P4: the passive register, with the issuer frame of the original probe ---------------------------
P4 = ("This is the CBI Cyber Crime Unit. The sum of Rs 38,00,000 is required to be remitted to the account "
      "specified herein for custodial verification, account 30011223344556. Non-compliance will result in "
      "your arrest.")
# The active control, which already returned AMBER. Same message, imperative mood.
P4_ACTIVE = P4.replace("The sum of Rs 38,00,000 is required to be remitted to",
                       "You must remit Rs 38,00,000 to")

# ---- probe P7: single letters, spaced out -----------------------------------------------------------------
P7 = ("This is the CBI Cyber Crime Unit. You must t r a n s f e r Rs 38,00,000 to the verification account "
      "30011223344556 before the hearing.")
P7_PLAIN = P7.replace("t r a n s f e r", "transfer")


# ============ 1. the passive and obligation register ========================================================

# Each frame is an obligation or a compulsion, which is the register a forged summons is written in. The verb is
# the past participle of a verb the ACTIVE family already carries, and the destination is still POINTED AT.
PASSIVE = [
    ("is required to be", "The sum of Rs 38,00,000 is required to be remitted to the account specified herein."),
    ("is to be", "The entire balance of Rs 5,00,000 is to be deposited in the designated account today."),
    ("shall be", "Rs 10,00,000 shall be remitted to the escrow account mentioned below before 4 pm."),
    ("must be", "Rs 38,00,000 must be transferred to the designated verification account 30011223344556."),
    ("stands to be", "Your balance stands to be moved to the custody account specified herein for clearance."),
    ("needs to be", "The amount of Rs 9,00,000 needs to be placed in this settlement account at once."),
    ("is hereby directed to be", "The entire amount is hereby directed to be routed through the nodal account "
                                 "mentioned above."),
    ("ought to be", "The funds ought to be consolidated into the monitoring account specified herein."),
    ("will have to be", "Rs 4,00,000 will have to be shifted to the clearance account 30011223344556 tonight."),
    # Hindi and Hinglish: the true passive participle, where कर becomes किया.
    ("जमा की जानी है", "यह राशि इस खाते में जमा की जानी है।"),
    ("jama kiya jana hai", "Pura paisa is account me jama kiya jana hai."),
]

# Hindi and Hinglish mostly did NOT need this change: the verb
# stem does not inflect for obligation, so "jama karna hoga", "भेजनी होगी" and "transfer karna padega" were
# already read by the active family, and bare English "transfer" is a banking verb on its own. These four are
# pinned here as regressions, and `test_the_hindi_obligation_forms_were_already_read` asserts that it really is
# the active family and not MOVE_PASSIVE that reads them.
ALREADY_READ = [
    ("ट्रांसफर की जानी चाहिए", "पूरी रकम इस खाते में ट्रांसफर की जानी चाहिए।"),
    ("भेजी जानी है", "पूरी रकम इस खाते में भेजी जानी है।"),
    ("jama karna hoga", "Rs 10,00,000 is account me jama karna hoga."),
    ("transfer kiya jana hai", "Poora amount is designated account me transfer kiya jana hai."),
]

# The negative twins. EVERY ONE of these carries the money word, the destination word and a construction in the
# same family, so each one is genuinely at risk: exactly one bound stops it, and that bound is named. A false
# positive here puts money wording on a benign customer card, which is worse than missing a demand.
PASSIVE_BENIGN = [
    # the verb is not in the family: "credited" is money arriving, not money demanded. The frame, the money word,
    # the destination and the pointer are all present, so only the verb list stops these two.
    ("credited, with a pointer",
     "The sum of Rs 12,000 is to be credited to the account mentioned above within 3 working days."),
    ("credited, to your account",
     "The amount is to be credited to your account within 3 working days."),
    # the verb is not in the family AND "may be" is not an obligation frame
    ("payment may be made",
     "Payment of Rs 4,500 may be made at any branch counter or to the account mentioned above."),
    # the verb is not in the family, and everything else is there, pointer included
    ("maintained",
     "The balance is required to be maintained above Rs 10,000 in this savings account."),
    # the verb IS in the family and the frame IS an obligation: only the pointed-destination rule stops these.
    # Both are a bank talking to a customer about her own account.
    ("deposited into your account",
     "The amount is to be deposited into your account by our branch within 3 working days."),
    ("transferred to your own account",
     "Rs 25,000 is required to be transferred to your own account before the closure request is processed."),
    ("moved to the account you nominated",
     "The maturity proceeds of Rs 50,000 must be moved to the account you nominated at onboarding."),
    # a completed or merely announced action is not an obligation, which is why a bare passive is not a frame
    ("was deposited", "Your salary of Rs 42,000 was deposited in the account you registered with us."),
    ("has been transferred", "Rs 2,000 has been transferred to the account mentioned above by our branch."),
    ("will be remitted", "The maturity amount will be remitted to the account specified in your request."),
    # Hindi: the same sentence a bank sends, in the passive. The account is the customer's own.
    ("आपके खाते में जमा की जानी है", "यह राशि आपके खाते में जमा की जानी है।"),
    # These four FIRED during development and are the reason _POINTER_POST is bounded three ways (see extract.py).
    # "the account mentioned above" is a pointed destination in a forged notice and an ordinary reference in a
    # bank email, and the preposition in front of it is what tells the two apart.
    ("moved out of the account mentioned above",
     "The balance is required to be moved out of the account mentioned above."),
    ("moved between the accounts mentioned above",
     "Funds are required to be moved between the accounts mentioned above."),
    # the two benign sentences from tests/test_euphemism_bounds.py, with "mentioned above" added. Folding the
    # notice pointer into the shared destination rule made both of them read as instructions to pay.
    ("close the account mentioned above",
     "To close the account mentioned above, please move the balance out first."),
    ("funds between the accounts mentioned above",
     "You can move funds between the accounts mentioned above in the app."),
]


@pytest.mark.parametrize("frame,text", PASSIVE, ids=[f for f, _ in PASSIVE])
def test_the_passive_register_is_read_as_a_payment_instruction(frame, text):
    c = X.extract(text)
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT, f"{frame}: {text}"
    assert c.text[c.instruction_span.start:c.instruction_span.end] == c.instruction_span.text


@pytest.mark.parametrize("why,text", PASSIVE_BENIGN, ids=[w for w, _ in PASSIVE_BENIGN])
def test_an_ordinary_bank_sentence_in_the_same_register_is_not_an_instruction(why, text):
    c = X.extract(text)
    assert c.instruction == Instruction.NONE, (
        f"a benign sentence was read as an instruction to pay ({why}): {text!r} -> {c.instruction.value} from "
        f"{c.instruction_span.text if c.instruction_span else None!r}"
    )


def test_the_passive_probe_reads_the_same_claim_as_its_active_control():
    """P4's headline: the register was the only thing between GREY and AMBER."""
    passive, active = X.extract(P4), X.extract(P4_ACTIVE)
    assert (passive.claimed_issuer, passive.instruction) == (active.claimed_issuer, active.instruction)
    assert (passive.claimed_issuer, passive.instruction) == (Issuer.CBI, Instruction.TRANSFER_TO_ACCOUNT)
    assert passive.payee.account.value == active.payee.account.value == "30011223344556"
    assert set(passive.pressure_cues) == set(active.pressure_cues) == {"arrest_threat"}


def test_the_passive_probe_gets_the_same_verdict_as_its_active_control(engine):
    passive = run_text(engine, P4).verdict
    active = run_text(engine, P4_ACTIVE).verdict
    assert passive.outcome == active.outcome
    assert passive.outcome != Outcome.GREY
    assert [s.rule_id for s in passive.signals] == [s.rule_id for s in active.signals]


def test_every_span_on_the_passive_probe_quotes_the_original_text():
    c = X.extract(P4)
    names = _spans(c)
    assert len(names) >= 5, "the probe should fill most of the claim"
    for name, sp in names:
        assert c.text[sp.start:sp.end] == sp.text, name
    assert ground(c) is not None and len(_spans(ground(X.extract(P4)))) == len(names)


def test_a_counter_deposit_notice_reads_the_same_in_both_registers():
    """Found while adding the passive register and deliberately left alone, recorded here rather than hidden.

    "The cash is to be deposited at the counter in this account by the depositor himself" reads as a payment
    instruction. So does its active control, "Deposit the cash at the counter in this account": the euphemism
    family has read that sentence this way since it shipped, because a counter notice and a scam use the same
    words in the same order and nothing lexical separates them. The passive register is meant to match the
    active control, so it inherits the reading rather than inventing a different one. The
    assertion is parity, not the value, so whoever fixes the active family fixes this with it.
    """
    passive = X.extract("The cash is to be deposited at the counter in this account by the depositor himself.")
    active = X.extract("Deposit the cash at the counter in this account, the depositor must come himself.")
    assert passive.instruction == active.instruction


def _without_move_passive(monkeypatch) -> RulesExtractor:
    """The extractor with this change reverted in place: MOVE_PASSIVE dropped back out of the live table."""
    from satyapan import extract as EX

    reverted = [(instr, [p for p in pats if p not in EX.MOVE_PASSIVE]) for instr, pats in EX.INSTRUCTION_KEYWORDS]
    assert sum(len(p) for _, p in reverted) == sum(len(p) for _, p in EX.INSTRUCTION_KEYWORDS) - len(EX.MOVE_PASSIVE)
    monkeypatch.setattr(EX, "INSTRUCTION_KEYWORDS", reverted)
    return RulesExtractor()


def test_the_passive_probe_fails_with_the_change_reverted(monkeypatch):
    """Not a tautology: with the feature it tests removed, the probe must fail."""
    before = _without_move_passive(monkeypatch).extract(P4)
    assert before.claimed_issuer == Issuer.CBI, "the issuer was always read; that was never the bug"
    assert before.instruction == Instruction.NONE, "without MOVE_PASSIVE the probe must fail, or this proves nothing"


@pytest.mark.parametrize("frame,text", PASSIVE, ids=[f for f, _ in PASSIVE])
def test_every_passive_probe_was_genuinely_unread_before(frame, text, monkeypatch):
    """Each probe in PASSIVE is a message the engine could not read before MOVE_PASSIVE, one assertion each."""
    assert _without_move_passive(monkeypatch).extract(text).instruction == Instruction.NONE, f"{frame}: {text}"


@pytest.mark.parametrize("frame,text", ALREADY_READ, ids=[f for f, _ in ALREADY_READ])
def test_the_hindi_obligation_forms_were_already_read(frame, text, monkeypatch):
    """The other half of the check: these read the same with the change reverted, so they are read by the
    active family and not by MOVE_PASSIVE."""
    assert X.extract(text).instruction == Instruction.TRANSFER_TO_ACCOUNT, f"{frame}: {text}"
    assert _without_move_passive(monkeypatch).extract(text).instruction == Instruction.TRANSFER_TO_ACCOUNT


# ============ 2. intra-word spacing =========================================================================

from satyapan.extract import DESPACE_LEXICON  # noqa: E402  (read after the module's own tables are built)

# Runs that must be closed up: five or more single letters whose de-spaced form is a word the extractor's tables
# already match.
SPACED = [
    ("t r a n s f e r", "You must t r a n s f e r Rs 38,00,000 to the verification account 30011223344556."),
    ("r e m i t", "You must r e m i t Rs 38,00,000 to the designated verification account."),
    ("a c c o u n t", "Deposit Rs 2,00,000 in the clearance a c c o u n t 30011223344556 within one hour."),
    ("a r r e s t", "You are under digital a r r e s t until the verification is complete."),
    ("double spacing", "You must  t  r  a  n  s  f  e  r  Rs 38,00,000 to the designated account."),
]

# Runs that must come through UNTOUCHED. These are the ones a wider rule would eat, and the first four are the
# reason the floor is five letters rather than three.
UNTOUCHED = [
    "I N R 5 0",                                  # a spaced money unit, and "inr" is in the money table
    "A/c No 500 100 234",                         # a spaced account number
    "C B I  c y b e r",                           # a spaced acronym ("cbi" is in the issuer table)
    "R B I  S E B I  T R A I  N C R P",           # spaced initialisms
    "Rs 3 8 0 0 0 0 0",                           # spaced digits are not letters, so never a run
    "R A J E S H  K U M A R",                     # five-plus letters, but no lexicon word: a name stays a name
    "P L E A S E  C A L L",                       # five-plus letters, not a word this engine looks for
    "a b c d e f g h",                            # the degenerate case
    "t r a n s\nf e r",                           # a newline is a wrap, not intra-word spacing
    "t\tr\ta\tn\ts\tf\te\tr",                     # nor is a tab
]


@pytest.mark.parametrize("run,text", SPACED, ids=[r for r, _ in SPACED])
def test_a_spaced_word_is_read_as_the_word(run, text):
    c = X.extract(text)
    assert c.instruction != Instruction.NONE or "arrest_threat" in c.pressure_cues, f"{run}: {text}"
    for name, sp in _spans(c):
        assert c.text[sp.start:sp.end] == sp.text, name


@pytest.mark.parametrize("text", UNTOUCHED)
def test_the_despacing_fold_leaves_everything_else_exactly_as_it_was(text):
    assert fold(text, DESPACE_LEXICON) == text


def test_the_spaced_probe_reads_the_same_claim_as_its_unspaced_control():
    spaced, plain = X.extract(P7), X.extract(P7_PLAIN)
    assert (spaced.claimed_issuer, spaced.instruction) == (plain.claimed_issuer, plain.instruction)
    assert (spaced.claimed_issuer, spaced.instruction) == (Issuer.CBI, Instruction.TRANSFER_TO_ACCOUNT)
    assert spaced.payee.account.value == plain.payee.account.value == "30011223344556"


def test_the_spaced_probe_gets_the_same_verdict_as_its_unspaced_control(engine):
    spaced = run_text(engine, P7).verdict
    plain = run_text(engine, P7_PLAIN).verdict
    assert spaced.outcome == plain.outcome
    assert spaced.outcome != Outcome.GREY
    assert [s.rule_id for s in spaced.signals] == [s.rule_id for s in plain.signals]


def test_the_span_found_in_despaced_coordinates_quotes_the_spaced_original():
    """The span contract, at the point where it is easiest to break: the match was found at offsets
    that do not exist in the message. Every stored span must still index and quote the ORIGINAL characters."""
    c = X.extract(P7)
    names = _spans(c)
    assert {n for n, _ in names} >= {"issuer", "instruction", "account", "amount[0]"}
    for name, sp in names:
        assert c.text[sp.start:sp.end] == sp.text, name
    assert c.instruction_span.text == "t r a n s f e r", "the quote must be the characters really in the message"
    assert len(_spans(ground(X.extract(P7)))) == len(names), "ground() must keep every field"


def test_the_despacing_is_not_a_tautology(monkeypatch):
    """Revert the change in place - empty the lexicon, which switches the fold off - and P7 must fail."""
    from satyapan import extract as EX

    monkeypatch.setattr(EX, "DESPACE_LEXICON", frozenset())
    before = RulesExtractor().extract(P7)
    assert before.claimed_issuer == Issuer.CBI, "the issuer was always read; that was never the bug"
    assert before.instruction == Instruction.NONE, "with no lexicon the probe must fail, or this proves nothing"
    assert fold(P7, frozenset()) == P7


def test_the_lexicon_only_holds_words_the_extractor_already_matches():
    """The fold's bound, asserted rather than described. A candidate word reaches the lexicon only if some
    pattern in the extractor's own tables matches it on its own; this test fails if a candidate is dropped,
    so a typo or a renamed pattern shows up here instead of as a silently dead fold."""
    from satyapan import extract as EX

    dropped = [w for w in EX._DESPACE_CANDIDATES if w not in DESPACE_LEXICON]
    assert dropped == [], f"candidates no table matches any more: {dropped}"
    assert "transfer" in DESPACE_LEXICON and "account" in DESPACE_LEXICON
    assert min(len(w) for w in DESPACE_LEXICON) >= 5, "a run shorter than five letters is never folded"
    # and the words that would do damage are not in it
    for w in ("inr", "rs", "a/c", "cbi", "rbi", "ed"):
        assert w not in DESPACE_LEXICON


def test_the_index_map_is_exact_for_every_slice_of_a_despaced_message():
    """The span contract, re-proved character by character on the new transform. A deleted space must not
    shift any surviving character's origin, including when the two folds stack: a zero-width space inside a
    spaced run is dropped by step 1 and the spacing is closed up by step 6, and the quote is still verbatim."""
    from satyapan.normalize import normalise

    zwsp = "​"
    for probe in [f"You must t{zwsp} r a n s f e r Rs 5,00,000 to this account 30011223344556.",
                  "t r a n s f e r Rs 5,00,000 to this account",       # a run at the very start
                  "Rs 5,00,000 to this account: t r a n s f e r",      # and at the very end
                  "a c c o u n t", "", "   "]:
        n = normalise(probe, DESPACE_LEXICON)
        assert len(n.origin) == len(n.text)
        for i in range(len(n.text)):
            s, e = n.map_span(i, i + 1)
            assert 0 <= s < e <= len(probe)
            assert n.quote(i, i + 1).endswith(probe[e - 1])
        if probe:
            s, e = n.map_span(0, len(n.text))
            assert probe[s:e] == probe, "a whole-string slice must map back to the whole original"
        c = X.extract(probe)
        for name, sp in _spans(c):
            assert c.text[sp.start:sp.end] == sp.text, (name, probe)


def test_a_pathological_run_of_single_letters_is_bounded():
    """A user can paste anything. 4,000 single letters is one run, and the fold must still terminate, still
    find the one word that is in it, and still map back exactly."""
    import time

    probe = "x " * 4000 + "a c c o u n t with Rs 5,00,000 to be sent"
    t0 = time.perf_counter()
    folded = fold(probe, DESPACE_LEXICON)
    assert time.perf_counter() - t0 < 2.0
    assert folded.endswith("account with Rs 5,00,000 to be sent")
    assert folded.startswith("x x x x")


def test_a_spaced_word_with_nothing_else_is_still_not_an_instruction():
    """Reading more words is not reading more meaning: the fold on its own never manufactures a demand. Both
    sentences de-space to a real lexicon word and both must stay silent."""
    assert fold("Your a c c o u n t statement for September is ready.", DESPACE_LEXICON) == \
        "Your account statement for September is ready."
    for text in ["Your a c c o u n t statement for September is ready.",
                 "Please m o v e d the chair back after the meeting."]:
        assert X.extract(text).instruction == Instruction.NONE, text
