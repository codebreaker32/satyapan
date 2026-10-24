"""What the customer actually hears, and the four ways the card out-ran its own claim.

Every test here comes from a judge reading the card off the screen on 18/19 Oct, as the frightened 70-year-old it is
written for would hear it. Four separate contradictions, one shape: the card asserted something the engine had not
established, or said a word the product bans.

1. The officer's band said "Verify before paying" on an AMBER whose own coverage sentence on the same screen said
   it found no instruction about money. The card hid that with an override of its own, so the two surfaces printed
   different headlines over one verdict. The headline is now chosen once, in `fuse`, from `money_in_play`.
2. The shipped English coaching line ended "...that is part of the scam" while `card.FORBIDDEN["en"]` has banned
   `\\bscam\\b` since the card existed. `lint_card` did not cover `coaching`, and `build_card` concatenates
   `coaching` into `read_aloud`, so the banned word was read out loud on every English RED and AMBER.
3. "End the call now." was the first officer line on every RED, including an OCR'd scanned notice and a voice note.
   Same class as the `R-CALLER-1600` gate, different field.
4. The Hindi S1 card read "(मध्यम (SIMULATED))" aloud, and the one sentence on the card that asserts an outside
   body's record named it "I4C" and carried no sign of whose check it was.

The tests are written to fail if the guard is removed, not to restate it: each one either runs the real pipeline or
turns the guard off and shows the shipped copy breaking without it.
"""
from __future__ import annotations

import re

import pytest

from satyapan import card as card_mod
from satyapan.card import (ALLOWED_PHRASES, COACHING, COACHING_NO_PAYMENT, SAY_NEXT_ON_A_CALL, Card, _on_a_call,
                           build_card, ground_reason, lint_card)
from satyapan.fusion import HEADLINES, HEADLINES_NO_PAYMENT, fuse
from satyapan.models import (Channel, Claim, ClaimedOwner, Family, Grounded, Instruction, Issuer, Outcome, Payee,
                             Severity, Signal, Span, Verdict)
from tests.conftest import SCENARIOS, run_scenario_id, run_text

# "money" in the two registers a 70-year-old hears, kept here rather than imported so this module stands alone.
MONEY = {"en": re.compile(r"\bmoney\b|\bpay\b|\bpays\b|\bpaying\b|\bpayment\b|\brupees?\b", re.I),
         "hi": re.compile(r"पैसा|पैसे|पैसों|भुगतान|रुपये|रक़म|रकम")}

# A benign Demo Bank re-KYC letter: `instruction=NONE`, no payee, and two independent families on it, so the
# verdict is a real AMBER and not a contrived one. This is the judge's own probe text.
REKYC = ("Dear Customer, your Demo Bank KYC is due for re-verification. Please update your KYC records at your "
         "nearest Demo Bank branch within 7 days. - Demo Bank")
# The same shape with money in it, as the control for every no-payment assertion below.
REKYC_WITH_MONEY = REKYC + " A verification fee of Rs 2,500 must be transferred to account 50100248891776."


def _signal(rule_id: str, fam: Family, sev: Severity, key: str, **detail) -> Signal:
    return Signal(rule_id=rule_id, family=fam, severity=sev, evidence_key=key, reason_en="r", reason_hi="र",
                  citation="c", citation_verified=True, escalate_alone=detail.pop("escalate_alone", False),
                  detail={"can_be_second": True} | detail)


def _verdict(outcome: Outcome, signals: list[Signal] | None = None, *, neutral: bool = False) -> Verdict:
    en, hi = (HEADLINES_NO_PAYMENT if neutral else HEADLINES).get(outcome, HEADLINES[outcome])
    return Verdict(outcome=outcome, headline_en=en, headline_hi=hi, explanation="synthetic", policy_version="test",
                   signals=signals or [])


# ---------------------------------------------------------------- 1. one headline, both surfaces

def test_the_card_never_overrides_the_verdicts_headline(engine):
    """The property that replaced `card.HEADLINE_NO_PAYMENT`. If a card-side override comes back, this fails."""
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        for lang, expected in (("en", case.verdict.headline_en), ("hi", case.verdict.headline_hi)):
            assert engine.card(case, lang).headline == expected, f"{sid} ({lang}): the card rewrote the headline"


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_amber_headline_is_payment_neutral_on_both_surfaces_when_nothing_asked_for_money(engine, lang):
    case = run_text(engine, REKYC)
    assert case.verdict.outcome == Outcome.AMBER
    assert case.claim.instruction == Instruction.NONE
    assert not (case.claim.payee.account or case.claim.payee.ifsc or case.claim.payee.vpa)
    band = case.verdict.headline_hi if lang == "hi" else case.verdict.headline_en
    card = engine.card(case, lang)
    assert not MONEY[lang].search(band), f"the officer's band still says it: {band!r}"
    assert card.headline == band
    assert band == HEADLINES_NO_PAYMENT[Outcome.AMBER][1 if lang == "hi" else 0]


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_an_amber_that_did_ask_for_money_keeps_the_paying_headline(engine, lang):
    """The control. Without it the test above would pass just as well on a headline that never mentions paying."""
    case = run_text(engine, REKYC_WITH_MONEY)
    assert case.verdict.outcome == Outcome.AMBER
    band = case.verdict.headline_hi if lang == "hi" else case.verdict.headline_en
    assert band == HEADLINES[Outcome.AMBER][1 if lang == "hi" else 0]
    assert MONEY[lang].search(band)
    assert engine.card(case, lang).headline == band


def test_no_scenario_band_mentions_paying_when_no_money_was_read(engine):
    """The sweep, with its own guard against passing vacuously."""
    exercised = []
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        c = case.claim
        if c.instruction != Instruction.NONE or c.payee.account or c.payee.ifsc or c.payee.vpa:
            continue
        if c.payee.claimed_owner != ClaimedOwner.UNKNOWN:
            continue
        exercised.append(sid)
        for lang, band in (("en", case.verdict.headline_en), ("hi", case.verdict.headline_hi)):
            assert not MONEY[lang].search(band), f"{sid} ({lang}): band headline says paying: {band!r}"
    assert exercised, "no scenario has a message with nothing about money in it; this test proved nothing"


def test_the_capped_amber_headline_agrees_with_its_own_explanation():
    """The corner the backlog named, and the reason the cap forces neutrality instead of trusting `money_in_play`.

    A claimed payee owner with no account behind it ("deposit it into the RBI account") is money to the copy
    predicate and is NOT a payee to the RED gate. So this is the one shape where the two disagree: the verdict is
    a capped AMBER whose explanation says nothing in the message asked for money, and the headline above it used
    to read "Verify before paying".
    """
    claim = Claim(source="text", text="Deposit it into the RBI account.", claimed_issuer=Issuer.BANK_SELF,
                  instruction=Instruction.NONE, payee=Payee(claimed_owner=ClaimedOwner.RBI))
    pair = [_signal("R-BANK-SELF", Family.F2, Severity.HARD, "bank:outbound_log"),
            _signal("R-DOMAIN-BANKIN", Family.F1, Severity.SOFT, "claim")]
    v = fuse(claim, pair)
    assert v.outcome == Outcome.AMBER and v.second_family is None
    assert "asked for money" in v.explanation
    assert (v.headline_en, v.headline_hi) == HEADLINES_NO_PAYMENT[Outcome.AMBER]
    # and the explanation quotes the words actually on the band, so the two cannot drift apart
    assert f"stops at “{v.headline_en.lower()}”" in v.explanation


def test_the_escalate_alone_amber_explanation_follows_the_same_predicate():
    """S5c's branch. The band used to tell the officer the customer "should verify before paying" about a summons
    that asked for nothing, directly under a coverage sentence saying no instruction about money was read."""
    soft = [_signal("R-ED-WINDOW", Family.F1, Severity.SOFT, "claim", escalate_alone=True)]
    nothing = Claim(source="ocr", text="x", claimed_issuer=Issuer.ED, instruction=Instruction.NONE)
    asked = Claim(source="ocr", text="x", claimed_issuer=Issuer.ED, instruction=Instruction.TRANSFER_TO_ACCOUNT)
    assert "confirm this message before acting on it" in fuse(nothing, soft).explanation
    assert "verify before paying" not in fuse(nothing, soft).explanation
    assert "verify before paying" in fuse(asked, soft).explanation


# ---------------------------------------------------------------- 2. coaching and read_aloud are linted

BANNED_EN = ["fake", "genuine", "fraud", "scam"]
BANNED_HI = ["नकली", "असली", "धोखाधड़ी", "फ़र्ज़ी"]


def test_the_shipped_coaching_lines_pass_the_lint_they_are_now_bound_by():
    for pair in (COACHING, COACHING_NO_PAYMENT):
        for lang, text in (("en", pair[0]), ("hi", pair[1])):
            lint_card(Card(lang=lang, outcome=Outcome.RED, headline="h", stop_line="s", reasons=[], do_now="d",
                           coaching=text, read_aloud=f"s\nh\nd\n{text}"))


def test_the_english_coaching_line_stopped_using_a_word_the_product_bans():
    assert "scam" not in COACHING[0].lower() and "scam" not in COACHING_NO_PAYMENT[0].lower()
    assert "part of the trick" in COACHING[0] and "part of the trick" in COACHING_NO_PAYMENT[0]


@pytest.mark.parametrize("word", BANNED_EN)
@pytest.mark.parametrize("pays", [True, False])
def test_a_banned_english_word_in_the_coaching_constant_fails_the_build(monkeypatch, word, pays):
    """The behavioural guard the backlog asked for: put the word back in the constant and the card refuses to build.

    Both constants and both payment paths, because `build_card` picks between them off the claim, and the bug that
    shipped lived in exactly one of the four cells.
    """
    line = f"If someone told you to ignore the bank, that is part of the {word}."
    monkeypatch.setattr(card_mod, "COACHING", (line, COACHING[1]))
    monkeypatch.setattr(card_mod, "COACHING_NO_PAYMENT", (line, COACHING_NO_PAYMENT[1]))
    claim = Claim(source="text", text="x", claimed_issuer=Issuer.BANK_SELF,
                  instruction=Instruction.MOVE_FD if pays else Instruction.NONE)
    with pytest.raises(ValueError, match="coaching|read_aloud"):
        build_card(_verdict(Outcome.RED), claim, "en")


@pytest.mark.parametrize("word", BANNED_HI)
def test_a_banned_hindi_word_in_the_coaching_constant_fails_the_build(monkeypatch, word):
    line = f"अगर किसी ने आपसे कहा है कि बैंक की बात मत मानिए, तो यह संदेश {word} है।"
    monkeypatch.setattr(card_mod, "COACHING", (COACHING[0], line))
    monkeypatch.setattr(card_mod, "COACHING_NO_PAYMENT", (COACHING_NO_PAYMENT[0], line))
    claim = Claim(source="text", text="x", claimed_issuer=Issuer.BANK_SELF, instruction=Instruction.MOVE_FD)
    with pytest.raises(ValueError, match="coaching|read_aloud"):
        build_card(_verdict(Outcome.RED), claim, "hi")


def test_the_lint_reaches_read_aloud_on_its_own():
    """`read_aloud` is built from fields that are already checked, so the lint on it only earns its place on a Card
    somebody else assembled — the API, an officer correction, a future caller. Here is that Card."""
    clean = Card(lang="en", outcome=Outcome.RED, headline="h", stop_line="s", reasons=[], do_now="d",
                 read_aloud="s\nh\nd\nThis notice is fake.")
    with pytest.raises(ValueError, match="read_aloud"):
        lint_card(clean)


def test_the_hindi_carve_out_is_one_phrase_and_not_a_free_field():
    """The recorded exception is "इस धोखे का हिस्सा" and nothing else. Calling the message a deception still raises,
    and so does a banned word sitting beside the allowed phrase."""
    assert ALLOWED_PHRASES == ("इस धोखे का हिस्सा",)
    ok = f"अगर किसी ने आपसे कहा है कि बैंक की बात मत मानिए, तो वही {ALLOWED_PHRASES[0]} है।"
    lint_card(Card(lang="hi", outcome=Outcome.AMBER, headline="h", stop_line="s", reasons=[], do_now="d",
                   coaching=ok, read_aloud=ok))
    for bad in ("यह संदेश धोखा है।", "यह सूचना धोखाधड़ी है।", f"वही {ALLOWED_PHRASES[0]} है, और यह संदेश नकली है।"):
        with pytest.raises(ValueError):
            lint_card(Card(lang="hi", outcome=Outcome.AMBER, headline="h", stop_line="s", reasons=[], do_now="d",
                           coaching=bad, read_aloud=bad))


def test_the_carve_out_is_load_bearing_and_the_dhokha_family_is_really_banned(monkeypatch):
    """Turn the allow-list off and the shipped Hindi coaching line fails, which is what makes the entry a decision
    rather than dead code. Without this, `FORBIDDEN["hi"]` could stop covering धोख and nothing would notice."""
    monkeypatch.setattr(card_mod, "ALLOWED_PHRASES", ())
    with pytest.raises(ValueError):
        lint_card(Card(lang="hi", outcome=Outcome.RED, headline="h", stop_line="s", reasons=[], do_now="d",
                       coaching=COACHING[1], read_aloud=COACHING[1]))


def test_every_scenario_card_passes_the_widened_lint(engine):
    """`build_card` lints what it builds, so this is the end-to-end statement: nothing the demo prints trips it."""
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        for lang in ("hi", "en"):
            lint_card(engine.card(case, lang))


# ---------------------------------------------------------------- 3. no call is asserted that did not happen

CALL_LINE_EN, CALL_LINE_HI = SAY_NEXT_ON_A_CALL[Outcome.RED]


@pytest.mark.parametrize("source, channel, on_call", [
    ("transcript", Channel.PHONE_CALL, True),       # a recording of the call itself
    ("officer_picklist", Channel.VIDEO_CALL, True),  # the officer says the customer is on one
    ("text", Channel.PHONE_CALL, False),             # a pasted message whose own words say "call our helpline"
    ("ocr", Channel.PHONE_CALL, False),              # a scanned notice with a helpline printed at the foot
    ("transcript", Channel.WHATSAPP, False),         # a voice note: nobody is on the line any more
    ("transcript", Channel.UNKNOWN, False),
])
def test_end_the_call_is_said_only_when_a_call_is_in_front_of_the_officer(source, channel, on_call):
    """Both halves of the gate, varied one at a time. The two False rows with PHONE_CALL are the whole point: the
    channel read out of a pasted message is a fact about what the message describes."""
    claim = Claim(source=source, text="Transfer Rs 5,00,000 to account 50100248891776 now.", channel=channel,
                  claimed_issuer=Issuer.CBI, instruction=Instruction.TRANSFER_TO_ACCOUNT)
    assert _on_a_call(claim) is on_call
    for lang, line in (("en", CALL_LINE_EN), ("hi", CALL_LINE_HI)):
        card = build_card(_verdict(Outcome.RED), claim, lang)
        assert (line in card.say_next) is on_call, f"{source}/{channel.value} ({lang}): {card.say_next}"
        assert card.say_next, "the officer is left with no lines at all"
        assert line not in card.read_aloud


def test_no_scenario_claims_a_call_it_does_not_have(engine):
    """On the shipped demo: S4 is a live video call and keeps the line; S3, the flagship RED, is a scanned notice
    and loses it. Both directions are asserted, so the gate cannot be satisfied by silence everywhere.

    The line only exists for RED. S8 is a live phone call that lands on AMBER, and AMBER's officer lines have
    never told her to cut the customer off: AMBER is "confirm this first", and the call may be a real one.
    """
    said, silent = [], []
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        expected = _on_a_call(case.claim) and case.verdict.outcome in SAY_NEXT_ON_A_CALL
        for lang, line in (("en", CALL_LINE_EN), ("hi", CALL_LINE_HI)):
            card = engine.card(case, lang)
            assert (line in card.say_next) is expected, f"{sid} ({lang}): {card.say_next}"
        (said if expected else silent).append(sid)
    assert "S4-claim-only" in said, "the one scenario that really is a call must still say it"
    assert "S3-ed-summons" in silent and "S1-rm-voice-note" in silent
    assert "S8-rbi-bond-no-payee" in silent, "a call on an AMBER has never carried the line"


def test_the_call_line_is_bound_by_the_forbidden_word_lint():
    for lines in SAY_NEXT_ON_A_CALL.values():
        for line in lines:
            for pat in card_mod.FORBIDDEN["en"] + card_mod.FORBIDDEN["hi"]:
                assert not re.search(pat, line, re.I), f"forbidden {pat!r} in officer line {line!r}"


# ---------------------------------------------------------------- 4. no technical token in the spoken card
#
# Each entry is a token a judge found being read aloud, or one that would read the same way if it reached the card.
# The officer's evidence row, the citation and the signed pack carry all of them; the card carries none.
NEVER_SPOKEN = {
    "SIMULATED": "provenance about the detector, stamped by forensics.to_signal",
    "I4C": "an acronym the customer cannot expand",
    "outbound": "the outbound-log coverage, moved to the officer's row in pass 5",
    "IVR": "a channel name from the same coverage sentence",
    "HMAC": "how the demo signs, not what the signature means",
    "C2PA": "the production signing standard",
    "rules-1.0": "an extractor version string",
}


def test_no_card_reads_a_technical_token_aloud(engine):
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        for lang in ("hi", "en"):
            spoken = engine.card(case, lang).read_aloud
            for token, why in NEVER_SPOKEN.items():
                assert token not in spoken, f"{sid} ({lang}): {token!r} is read aloud ({why})"


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_simulated_marker_stays_on_the_officers_row_and_leaves_the_card(engine, lang):
    """The pass-5 move, applied to the forensics stamp: the property stays, the surface changes.

    The assertion on the signal is what stops this becoming a test about nothing. If forensics ever stops stamping
    the marker, this fails instead of quietly proving that the card does not carry a marker nobody produced.
    """
    case = run_scenario_id(engine, "S1-rm-voice-note")
    audio = next(s for s in case.verdict.signals if s.rule_id == "R-AUDIO-SYNTH")
    assert "(SIMULATED)" in audio.reason_en and "(SIMULATED)" in audio.reason_hi
    assert audio.detail["simulated"] is True
    card = engine.card(case, lang)
    reason = next(r for r in card.reasons if r.rule_id == "R-AUDIO-SYNTH")
    assert "SIMULATED" not in reason.text
    # the band it was stapled to is a plain word and survives, so the customer still hears how strong the signal is
    assert ("मध्यम" if lang == "hi" else "moderate") in reason.text
    assert "SIMULATED" not in card.read_aloud


def test_the_marker_is_stripped_by_the_card_and_not_by_luck():
    """Hand the card a reason carrying the marker directly. Nothing else in the pipeline is involved."""
    sig = _signal("R-AUDIO-SYNTH", Family.F3, Severity.SOFT, "media:audio", simulated=True)
    sig.reason_en = "This voice shows signs of being computer-generated (moderate (SIMULATED))."
    sig.reason_hi = "इस आवाज़ में कंप्यूटर से बनी होने के संकेत मिले हैं (मध्यम (SIMULATED))।"
    claim = Claim(source="transcript", text="x")
    assert ground_reason(sig, claim, hi=False) == "This voice shows signs of being computer-generated (moderate)."
    assert ground_reason(sig, claim, hi=True) == "इस आवाज़ में कंप्यूटर से बनी होने के संकेत मिले हैं (मध्यम)।"


# ---------------------------------------------------------------- 6. the one sentence about an outside record

def _suspect_signal(what: str, what_hi: str) -> Signal:
    return _signal("R-SUSPECT", Family.F1, Severity.SOFT, "registry:suspect", what=what, what_hi=what_hi)


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_suspect_registry_reason_names_our_check_and_not_an_acronym(engine, lang):
    case = run_scenario_id(engine, "S4-claim-only")
    signal = next(s for s in case.verdict.signals if s.rule_id == "R-SUSPECT")
    # the officer's row and the signed pack keep the rulebook's sentence, I4C and all
    assert "I4C" in signal.reason_en and "I4C" in signal.reason_hi
    assert "suspect registry run by I4C" in signal.reason_en
    reason = next(r for r in engine.card(case, lang).reasons if r.rule_id == "R-SUSPECT")
    assert "I4C" not in reason.text
    assert ("हमने जाँचा" if lang == "hi" else "We checked") in reason.text
    assert ("सरकार की" if lang == "hi" else "government's") in reason.text


@pytest.mark.parametrize("what, what_hi", [("account", "खाता"), ("UPI ID", "UPI आईडी"), ("phone number", "फ़ोन नंबर")])
def test_the_card_sentence_covers_every_identifier_the_registry_can_return(what, what_hi):
    """`adapters.MockSuspectRegistry.check` returns one of three strings. All three have to read as a sentence."""
    claim = Claim(source="text", text="x")
    en = ground_reason(_suspect_signal(what, what_hi), claim, hi=False)
    hi = ground_reason(_suspect_signal(what, what_hi), claim, hi=True)
    assert en == f"We checked, and this {what} is already on the government's cyber-crime suspect list."
    assert hi == f"हमने जाँचा और यह {what_hi} सरकार की साइबर अपराध संदिग्ध सूची में पहले से दर्ज है।"
    for text in (en, hi):
        assert "I4C" not in text
        assert len(re.findall(r"[.।]", text)) == 1, f"more than one sentence: {text!r}"


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_a_suspect_signal_with_no_identifier_drops_the_reason_rather_than_guessing(lang):
    """Same rule as the grounded clauses: with nothing to name, the reason goes and the next signal moves up."""
    bare = _signal("R-SUSPECT", Family.F1, Severity.SOFT, "registry:suspect")
    assert ground_reason(bare, Claim(source="text", text="x"), hi=(lang == "hi")) is None
    claim = Claim(source="text", text="Pay into account 50100248891776.", instruction=Instruction.TRANSFER_TO_ACCOUNT,
                  payee=Payee(account=Grounded(value="50100248891776",
                                               span=Span(text="50100248891776", start=17, end=31))))
    card = build_card(_verdict(Outcome.AMBER, [bare]), claim, lang)
    assert [r.rule_id for r in card.reasons] == []
