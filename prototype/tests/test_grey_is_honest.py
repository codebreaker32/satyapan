"""GREY must never claim the message looks clean.

The pass-2 judge pasted a leetspeak arrest threat ("transf3r", "arr3st") and a polite "RBI Ombudsman matching
deposit" letter. The patterns missed both, so no rule fired and the verdict was GREY — which is correct, the engine
had nothing to corroborate. What was not correct was the band: it read "No warning signs found" while the engine's
own extraction had taken an authority and a transfer instruction out of the very same message, and while the screen
below listed the pressure cues under "Also noted, never counted".

These tests pin the rule: whenever anything was read from the message, GREY says what was read and says plainly that
nothing could check it. The verdict itself never moves — GREY is still GREY, and it is still never "safe".
"""
from __future__ import annotations

import pytest

from satyapan.fusion import fuse
from satyapan.models import (
    Claim,
    Family,
    Instruction,
    Issuer,
    Outcome,
    Payee,
    Severity,
    Signal,
    Span,
    Grounded,
)

CLEAN = "No rule fired on this message"
NEVER_SAFE = "This is not a confirmation that the message is safe."


def _span(text: str = "x") -> Span:
    return Span(text=text, start=0, end=len(text))


def _claim(**kw) -> Claim:
    return Claim(source="text", text="some message text", **kw)


def _context_signal() -> Signal:
    """An F5 context row: the kind that shows under "Also noted, never counted" and never counts."""
    return Signal(rule_id="R-PRESSURE-CUES", family=Family.F5, severity=Severity.INFO,
                  reason_en="The message uses pressure", reason_hi="संदेश दबाव डालता है",
                  evidence_key="claim", citation="", citation_verified=False)


def test_bare_message_is_grey_and_says_there_was_nothing_to_check():
    v = fuse(_claim(), [])
    assert v.outcome == Outcome.GREY
    assert "Too little content to check" in v.explanation
    assert NEVER_SAFE in v.explanation


@pytest.mark.parametrize(
    "kw, must_name",
    [
        (dict(claimed_issuer=Issuer.RBI), "RBI"),
        (dict(instruction=Instruction.TRANSFER_TO_ACCOUNT), "transfer to account"),
        (dict(payee=Payee(account=Grounded(value="30011223344556", span=_span("30011223344556")))), "payee"),
        (dict(pressure_cues={"arrest_threat": _span()}), "arrest threat"),
    ],
)
def test_grey_names_what_was_read_and_never_claims_a_clean_message(kw, must_name):
    v = fuse(_claim(**kw), [])
    assert v.outcome == Outcome.GREY, "naming what was read must never move the verdict"
    assert CLEAN not in v.explanation, f"GREY claimed a clean message while {must_name!r} had been read"
    assert "Read from the message" in v.explanation
    assert must_name in v.explanation
    assert NEVER_SAFE in v.explanation


def test_pressure_cues_are_named_as_never_counting():
    v = fuse(_claim(pressure_cues={"arrest_threat": _span(), "secrecy": _span()}), [_context_signal()])
    assert v.outcome == Outcome.GREY
    assert "never counts toward a verdict" in v.explanation
    assert "arrest threat and secrecy" in v.explanation


def test_the_judges_probe_shape_cannot_be_called_clean():
    """The RBI-Ombudsman probe: issuer and instruction both extracted, no rule fired."""
    v = fuse(_claim(claimed_issuer=Issuer.RBI, instruction=Instruction.TRANSFER_TO_ACCOUNT), [])
    assert v.outcome == Outcome.GREY
    assert CLEAN not in v.explanation
    assert "RBI" in v.explanation and "transfer to account" in v.explanation


def test_a_truly_empty_check_still_gets_the_plain_sentence():
    """A message with content the extractor read nothing out of: still GREY, still never safe, no false alarm."""
    v = fuse(_claim(claimed_issuer=Issuer.NONE, instruction=Instruction.NONE), [])
    assert v.outcome == Outcome.GREY
    assert NEVER_SAFE in v.explanation


def _info_match() -> Signal:
    """The shape of S5c2: ED's own system recognised the summons. F1, informational, never moves a verdict."""
    return Signal(rule_id="R-ED-FOUND", family=Family.F1, severity=Severity.INFO,
                  reason_en="This summons number and passcode match ED's records",
                  reason_hi="यह समन नंबर और पासकोड ED के रिकॉर्ड से मेल खाते हैं",
                  evidence_key="issuer:ed_portal", citation="", citation_verified=False)


@pytest.mark.parametrize("claim_kw", [dict(claimed_issuer=Issuer.ED), dict()])
def test_grey_never_says_no_rule_fired_when_one_did(claim_kw):
    """The first version of this change threw the signals away and hardcoded "no rule fired".

    On S5c2 that put "No rule fired on it" on the band while the panel one screen below listed R-ED-FOUND, which
    is the same contradiction, inverted. Any non-F5 signal must change the sentence.
    """
    v = fuse(_claim(**claim_kw), [_info_match()])
    assert v.outcome == Outcome.GREY
    assert "No rule fired" not in v.explanation
    # The rule is named by its rulebook title now, not its id (see test_no_rule_ids_in_prose.py); the id is still
    # on the signal row the officer can expand, and in the signed pack.
    assert "Summons found in ED's system" in v.explanation
    assert "R-ED-FOUND" in {s.rule_id for s in v.signals}
    assert NEVER_SAFE in v.explanation


def test_context_signals_alone_do_not_count_as_something_that_ran():
    """F5 is context and never counts, so it must not turn "no rule fired" into "something ran"."""
    v = fuse(_claim(), [_context_signal()])
    assert "No rule fired" in v.explanation


# ---------------------------------------------------------------- why nothing fired
# "We saw a payee to send money to and an arrest threat, and no rule fired on it" is an admission, not an
# explanation. The band now carries one more clause saying why nothing fired, read off the claim.

WHY = "No rule fired on it, because "


def _why(v) -> str:
    """The why clause on its own, so a test can pin its length as well as its words."""
    assert WHY in v.explanation, v.explanation
    return v.explanation.split(WHY, 1)[1].split(". ", 1)[0]


def test_the_digital_arrest_shape_says_why_nothing_fired():
    """The judge's probe: a payee and pressure cues were read, the authority and the instruction were not."""
    v = fuse(_claim(payee=Payee(account=Grounded(value="30011223344556", span=_span("30011223344556"))),
                    pressure_cues={"arrest_threat": _span(), "urgency": _span()}), [])
    assert v.outcome == Outcome.GREY
    assert "a payee to send money to" in v.explanation
    assert _why(v) == ("no authority and no instruction about money were read out of it, and what was read was "
                       "not enough for a rule to match")


@pytest.mark.parametrize(
    "kw, must_say",
    [
        (dict(claimed_issuer=Issuer.COURT), "no instruction about money was read out of it"),
        (dict(instruction=Instruction.TRANSFER_TO_ACCOUNT), "no authority was read out of it"),
    ],
)
def test_the_why_clause_names_the_half_of_the_pair_that_was_missing(kw, must_say):
    v = fuse(_claim(**kw), [])
    assert must_say in _why(v)


def test_a_pair_that_matched_no_rule_says_so_and_says_what_the_bank_could_check():
    """Both halves read (the real-RBI-advisory shape). The rulebook does carry an RBI investment rule, so the
    clause must not claim there is none: it says the pair alone was not enough."""
    v = fuse(_claim(claimed_issuer=Issuer.RBI, instruction=Instruction.INVEST_FOR_RETURNS), [])
    why = _why(v)
    # the pair itself is named in the sentence before, which this one leans on
    assert "a message claiming to be from RBI" in v.explanation and "invest for returns" in v.explanation
    assert "the authority and the instruction it read are not enough for a rule on their own" in why
    assert "the bank has no record that could check it" in why


def test_the_bank_half_follows_what_the_bank_could_actually_check():
    """A message claiming to be the bank opens the outbound log, so the records did run and found nothing wrong.
    Saying "no bank record could check it" there, which the old hardcoded sentence did, was false."""
    v = fuse(_claim(claimed_issuer=Issuer.BANK_SELF, instruction=Instruction.TRANSFER_TO_ACCOUNT), [])
    assert "the bank's own records found nothing wrong" in _why(v)
    assert "no record that could check it" not in _why(v)


def test_the_why_clause_stays_short():
    for kw in (dict(), dict(claimed_issuer=Issuer.ED), dict(instruction=Instruction.MOVE_FD),
               dict(claimed_issuer=Issuer.CBI, instruction=Instruction.MOVE_FD),
               dict(claimed_issuer=Issuer.BANK_SELF, instruction=Instruction.MOVE_FD)):
        claim = _claim(**kw)
        v = fuse(claim, [])
        if WHY not in v.explanation:          # the no-content branch says why in its own words
            continue
        assert len(_why(v).split()) <= 26, _why(v)


def test_the_why_clause_is_derived_from_the_claim_and_not_one_canned_sentence():
    shapes = [dict(claimed_issuer=Issuer.ED), dict(instruction=Instruction.MOVE_FD),
              dict(claimed_issuer=Issuer.ED, instruction=Instruction.MOVE_FD),
              dict(claimed_issuer=Issuer.BANK_SELF, instruction=Instruction.MOVE_FD)]
    whys = {_why(fuse(_claim(**kw), [])) for kw in shapes}
    assert len(whys) == len(shapes), f"shapes collapsed to the same sentence: {whys}"


def test_nothing_is_claimed_about_why_when_a_rule_did_run():
    """The why clause belongs to "nothing fired". When something ran, the band says what ran instead."""
    v = fuse(_claim(claimed_issuer=Issuer.ED), [_info_match()])
    assert WHY not in v.explanation
    assert "What did run" in v.explanation


def test_what_was_read_quotes_the_words_it_rests_on():
    """The extractor reads INVEST_FOR_RETURNS out of a negation on one control. Quoting the matched words does not
    fix that, but it lets the officer see the basis and catch it."""
    span = Span(text="invest", start=10, end=16)
    v = fuse(_claim(instruction=Instruction.INVEST_FOR_RETURNS, instruction_span=span), [])
    assert 'read from “invest”' in v.explanation


def _media(rule: str, key: str, sev: Severity, status: str) -> Signal:
    return Signal(rule_id=rule, family=Family.F3, severity=sev, evidence_key=key, reason_en="r", reason_hi="र",
                  citation="corroboration only", citation_verified=True, detail={"can_be_second": False, "status": status})


def test_quiet_media_checks_are_named_by_what_they_did_never_by_a_finding_title():
    """A face check that found nothing (or never ran) must not read 'What did run: Signs of face manipulation'."""
    signals = [_media("R-VIDEO-SYNTH", "media:video", Severity.INFO, "clean"),
               _media("R-AUDIO-SYNTH", "media:audio", Severity.ABSTAIN, "abstain")]
    v = fuse(_claim(claimed_issuer=Issuer.RBI), signals)
    assert v.outcome == Outcome.GREY
    assert "Signs of face manipulation" not in v.explanation and "Signs of synthetic speech" not in v.explanation
    assert "Media checks: the face check found no signs and the voice check abstained; they only corroborate." in v.explanation
    assert NEVER_SAFE in v.explanation


def test_service_down_reads_as_an_abstaining_check():
    v = fuse(_claim(), [_media("R-VIDEO-SYNTH", "media:video", Severity.ABSTAIN, "abstain")])
    assert v.outcome == Outcome.GREY and "the face check abstained" in v.explanation
    assert "Signs of face manipulation" not in v.explanation
