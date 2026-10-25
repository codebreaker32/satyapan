import re

import pytest

from satyapan.card import (DO_NOW, DO_NOW_NO_PAYMENT, FORBIDDEN, SAY_NEXT, SAY_NEXT_ON_A_CALL, STOP_LINE,
                           STOP_LINE_NO_PAYMENT, Card, build_card, lint_card)
from satyapan.models import (Claim, ClaimedOwner, Family, Grounded, Instruction, Issuer, Outcome, Payee, Severity,
                             Signal, Span, Verdict)
from satyapan.rulebook import load_rulebook
from tests.conftest import SCENARIOS, run_scenario_id, run_text

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# "money" in the two registers a 70-year-old hears. The card may only use these words when a payment was asked for.
MONEY = {"en": re.compile(r"\bmoney\b|\bpay\b|\bpays\b|\bpaying\b|\bpayment\b|\brupees?\b", re.I),
         "hi": re.compile(r"पैसा|पैसे|पैसों|भुगतान|रुपये|रक़म|रकम")}


def sentences(text: str) -> list[str]:
    """Sentences as the ear hears them: a full stop, danda, question or exclamation mark followed by a break."""
    return [p for p in re.split(r"(?<=[.?!।])\s+", text.strip()) if p]


def test_rulebook_templates_never_label_the_message():
    book = load_rulebook()
    for m in book.rules.values():
        for text in (m.reason_en, m.reason_hi):
            for pat in FORBIDDEN["en"] + FORBIDDEN["hi"]:
                assert not re.search(pat, text, re.I), f"{m.id}: forbidden {pat!r} in {text!r}"


@pytest.mark.parametrize("sid", ["S1-rm-voice-note", "S2-rbi-video", "S3-ed-summons", "S4-claim-only"])
def test_red_card_has_three_cited_reasons_in_both_languages(engine, sid):
    case = run_scenario_id(engine, sid)
    assert case.verdict.outcome == Outcome.RED
    for lang in ("hi", "en"):
        card = engine.card(case, lang)
        assert len(card.reasons) == 3
        assert all(r.cite for r in card.reasons)
        assert card.coaching
        assert card.do_now in card.read_aloud
        if lang == "hi":
            assert DEVANAGARI.search(card.stop_line) and DEVANAGARI.search(card.reasons[0].text)


def test_ed_summons_card_matches_the_deck_cover(engine):
    card = engine.card(run_scenario_id(engine, "S3-ed-summons"), "en")
    ids = [r.rule_id for r in card.reasons]
    assert ids[:2] == ["R-AGENCY-PAY", "R-PAYEE-NAME"] or ids[:2] == ["R-PAYEE-NAME", "R-AGENCY-PAY"]
    assert ids[2] == "R-ED-NO-PASSCODE"


def test_matches_and_grey_cards_have_no_coaching_and_never_say_safe(engine):
    m = engine.card(run_scenario_id(engine, "S5a-genuine-bank-notice"), "en")
    assert m.outcome == Outcome.MATCHES and m.coaching is None and "never ask you to move money" in m.do_now
    g = engine.card(run_scenario_id(engine, "S5b-real-rbi-advisory"), "en")
    assert g.outcome == Outcome.GREY and g.coaching is None and "safe" not in g.headline.lower()


def test_matches_card_hindi_claims_only_provenance(engine):
    """The old Hindi line said "यह संदेश सही है" ("this message is correct"), a claim about the content that
    MATCHES never makes. The replacement names who sent it, which is all the signature and the log show."""
    assert STOP_LINE[Outcome.MATCHES][1] == "यह संदेश हमने ही भेजा था।"
    assert "सही" not in STOP_LINE[Outcome.MATCHES][1]
    card = engine.card(run_scenario_id(engine, "S5a-genuine-bank-notice"), "hi")
    assert card.outcome == Outcome.MATCHES
    assert "यह संदेश सही है" not in card.read_aloud
    assert card.stop_line == "यह संदेश हमने ही भेजा था।"


@pytest.mark.parametrize(
    "bad_hi",
    ["यह संदेश सही है।", "यह सूचना सच है।", "यह नोटिस प्रामाणिक है।", "यह समन वैध है।"],
)
def test_lint_rejects_hindi_claims_that_the_message_is_true(bad_hi):
    card = Card(lang="hi", outcome=Outcome.MATCHES, headline="h", stop_line=bad_hi, reasons=[], do_now="x")
    with pytest.raises(ValueError):
        lint_card(card)


@pytest.mark.parametrize(
    "ok_hi",
    # the narrowed patterns must not ban ordinary copy that merely starts with the same letters
    ["सचेत रहें और पुष्टि करें।", "यह वैधानिक प्रक्रिया है।"],
)
def test_lint_allows_hindi_words_that_only_start_like_a_claim(ok_hi):
    lint_card(Card(lang="hi", outcome=Outcome.GREY, headline="h", stop_line=ok_hi, reasons=[], do_now="x"))


def test_lint_rejects_forbidden_words():
    bad = Card(lang="en", outcome=Outcome.RED, headline="h", stop_line="This notice is fake.", reasons=[], do_now="x")
    with pytest.raises(ValueError):
        lint_card(bad)


def test_no_score_ever_reaches_the_customer(engine):
    for sid in ("S1-rm-voice-note", "S2-rbi-video", "S3-ed-summons"):
        card = engine.card(run_scenario_id(engine, sid), "en")
        assert not re.search(r"\d+(\.\d+)?\s?%|\bscore\b|\bconfidence\b", card.read_aloud, re.I)


# ---------------------------------------------------------------- one instruction
# Read aloud as a frightened 70-year-old would hear it, the card used to give four instructions (cut the call, do not
# send the money, verify with the ED, get help to report it): too many to remember under pressure. It now gives one.

def test_do_now_is_exactly_one_instruction_in_every_scenario_and_language(engine):
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        for lang in ("hi", "en"):
            do_now = engine.card(case, lang).do_now
            parts = sentences(do_now)
            assert len(parts) == 1, f"{sid} ({lang}): do_now carries {len(parts)} sentences: {parts}"
            assert ";" not in do_now, f"{sid} ({lang}): a semicolon chains a second instruction into do_now"
            # one sentence-final mark at most (a dot inside a route like rbi.org.in is not one: look for the break)
            assert len(re.findall(r"[.!?।](\s|$)", do_now)) <= 1, f"{sid} ({lang}): {do_now!r}"


@pytest.mark.parametrize("outcome", list(Outcome))
@pytest.mark.parametrize("lang_index", [0, 1])
def test_do_now_templates_are_single_sentences(outcome, lang_index):
    for table in (DO_NOW, DO_NOW_NO_PAYMENT):
        if outcome not in table:
            continue
        text = table[outcome][lang_index].format(route="X")
        assert len(sentences(text)) == 1, f"{outcome} template: {text!r}"


def test_say_next_carries_the_officer_lines_and_is_never_read_aloud(engine):
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        for lang in ("hi", "en"):
            card = engine.card(case, lang)
            assert card.say_next, f"{sid} ({lang}): no officer lines"
            for line in card.say_next:
                assert line not in card.read_aloud, f"{sid} ({lang}): officer line is read aloud: {line!r}"
            if lang == "hi":
                assert all(DEVANAGARI.search(line) for line in card.say_next)


def test_say_next_is_bound_by_the_forbidden_word_lint():
    tables = list(SAY_NEXT.values()) + [tuple([line] for line in pair) for pair in SAY_NEXT_ON_A_CALL.values()]
    for pair in tables:
        for lines in pair:
            for line in lines:
                for pat in FORBIDDEN["en"] + FORBIDDEN["hi"]:
                    assert not re.search(pat, line, re.I), f"forbidden {pat!r} in officer line {line!r}"
    bad = Card(lang="en", outcome=Outcome.RED, headline="h", stop_line="s", reasons=[], do_now="x",
               say_next=["Tell her this notice is fake."])
    with pytest.raises(ValueError):
        lint_card(bad)


def test_read_aloud_is_the_stop_line_the_reasons_and_one_instruction(engine):
    """The verdict's headline stays on the officer's band. On the card it repeated the stop line above it and the
    instruction below it ("We could not confirm this." / "Could not confirm. Check via the official channel" / "Check
    this here before you act on it")."""
    for sid in sorted(SCENARIOS):
        case = run_scenario_id(engine, sid)
        for lang in ("hi", "en"):
            card = engine.card(case, lang)
            lines = card.read_aloud.splitlines()
            assert lines[0] == card.stop_line, f"{sid} ({lang}): read_aloud does not open on the stop line"
            assert card.headline not in lines, f"{sid} ({lang}): the headline is repeated on the card"
            numbered = [l for l in lines if re.match(r"^\d+\. ", l)]
            assert numbered == [f"{i + 1}. {r.text}" for i, r in enumerate(card.reasons)]
            assert card.do_now in lines, f"{sid} ({lang}): the one instruction is not in read_aloud"


def test_the_ed_passcode_reason_states_only_the_checkable_fact(engine):
    """RED reason 3 used to explain ED's passcode procedure and then tell her to confirm with ED, which is an
    instruction she cannot act on at a counter. The reason is now the fact; the route is in say_next."""
    for lang, must, gone in (("en", "carries a passcode", ("website", "confirm with ED")),
                             ("hi", "पासकोड होता है", ("वेबसाइट", "पुष्टि"))):
        card = engine.card(run_scenario_id(engine, "S3-ed-summons"), lang)
        reason = next(r for r in card.reasons if r.rule_id == "R-ED-NO-PASSCODE")
        assert must in reason.text
        for word in gone:
            assert word not in reason.text, f"{lang}: reason 3 still carries {word!r}"
        assert len(sentences(reason.text)) <= 2
    card = engine.card(run_scenario_id(engine, "S3-ed-summons"), "en")
    assert any("enforcementdirectorate.gov.in" in line for line in card.say_next)


# ---------------------------------------------------------------- money wording only when money was asked for
# A benign Demo Bank re-KYC SMS asked for no money, and the card still said "Do not send money now".

PAYS = ["S1b-rm-own-phone", "S6-fake-credit", "S7-court-order", "S8-rbi-bond-no-payee"]
NO_PAYMENT = ["S5c-ed-summons-1h-old", "S5c2-ed-summons-valid", "S5f-court-hearing-notice", "S5g-it-refund-processed"]


@pytest.mark.parametrize("sid", PAYS)
def test_a_card_for_a_payment_demand_still_talks_about_the_money(engine, sid):
    case = run_scenario_id(engine, sid)
    for lang in ("hi", "en"):
        card = engine.card(case, lang)
        assert card.outcome in (Outcome.RED, Outcome.AMBER)
        assert MONEY[lang].search(card.do_now), f"{sid} ({lang}): money was demanded and do_now does not say so"


@pytest.mark.parametrize("sid", NO_PAYMENT)
def test_a_card_for_a_message_that_asked_for_nothing_never_mentions_money(engine, sid):
    case = run_scenario_id(engine, sid)
    for lang in ("hi", "en"):
        card = engine.card(case, lang)
        assert card.outcome in (Outcome.AMBER, Outcome.GREY)
        spoken = (("stop_line", card.stop_line), ("headline", card.headline), ("do_now", card.do_now),
                  ("coaching", card.coaching or ""))
        for field, text in spoken:
            assert not MONEY[lang].search(text), f"{sid} ({lang}): {field} manufactures payment anxiety: {text!r}"


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_a_grey_card_that_was_asked_for_money_keeps_the_money_wording(engine, lang):
    """A GREY that really does carry a payment demand keeps the money wording.

    This used to use S5b-real-rbi-advisory, which was the wrong fixture and pinned a known extractor bug as
    correct: the extractor reads INVEST_FOR_RETURNS out of "RBI does not give any such financial investment
    advice", a negation, so that advisory looks like a money demand to the engine. The bug is recorded in
    decisions.md and on the backlog; this test now uses a message that genuinely asks for money, so fixing the
    extractor will not break it.
    """
    case = run_text(engine, "Transfer Rs 2,00,000 to account 30011223344556, IFSC HDFC0000213, today.")
    card = engine.card(case, lang)
    assert card.outcome == Outcome.GREY
    assert MONEY[lang].search(card.do_now)


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_the_benign_rekyc_sms_is_amber_without_a_word_about_sending_money(engine, lang):
    """A benign re-KYC SMS: instruction NONE, no payee, R-BANK-SELF on an outbound-log miss. The verdict is right and
    stays AMBER. The copy no longer tells her to stop paying when nobody asked her to pay."""
    case = run_text(engine, "Dear Customer, your Demo Bank KYC is due for re-verification. Please update your KYC "
                            "records at your nearest Demo Bank branch within 7 days. - Demo Bank")
    assert case.verdict.outcome == Outcome.AMBER
    assert case.claim.instruction == Instruction.NONE
    card = engine.card(case, lang)
    assert not MONEY[lang].search(card.stop_line + " " + card.headline + " " + card.do_now)
    assert len(sentences(card.do_now)) == 1


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_an_account_to_pay_into_counts_as_a_money_demand_even_with_no_instruction(lang):
    """The backstop: the extractor missed the instruction phrasing but the message carries an account and says whose
    it is. Money is in play, so the card keeps the money wording."""
    claim = Claim(source="text", text="Deposit to the account below.", instruction=Instruction.NONE,
                  payee=Payee(account=Grounded(value="50100123456789", span=Span(text="50100123456789", start=0, end=14)),
                              claimed_owner=ClaimedOwner.AGENCY))
    verdict = Verdict(outcome=Outcome.GREY, headline_en="Could not confirm. Check via the official channel",
                      headline_hi="पुष्टि नहीं हो सकी। आधिकारिक माध्यम से जाँच करें", explanation="synthetic",
                      policy_version="test", signals=[])
    card = build_card(verdict, claim, lang)
    assert MONEY[lang].search(card.do_now), f"{lang}: a named payee account dropped the money wording"


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_a_red_card_with_nothing_to_pay_also_drops_the_money_wording(engine, lang):
    """The no-payment RED copy, built here directly rather than through `fuse`.

    `fusion` no longer lets a no-money message reach RED at all (tests/test_no_red_without_money.py), so this is
    defence in depth: the card is built from any Verdict the API, an officer correction or a future policy hands
    it, and if a RED ever arrives with nothing to pay, the copy must still not tell her to stop a payment."""
    claim = Claim(source="text", text="Your KYC is due. Visit your branch.", claimed_issuer=Issuer.BANK_SELF,
                  instruction=Instruction.NONE, payee=Payee())
    signals = [Signal(rule_id="R-BANK-SELF", family=Family.F2, severity=Severity.HARD, evidence_key="bank:outbound",
                      reason_en="Demo Bank has no record of sending this message.",
                      reason_hi="Demo Bank के रिकॉर्ड में ऐसा कोई संदेश नहीं है।", citation="log",
                      citation_verified=True)]
    verdict = Verdict(outcome=Outcome.RED, headline_en="Stop and verify through the official channel",
                      headline_hi="रुकिए। आधिकारिक माध्यम से जाँच करें", explanation="synthetic",
                      policy_version="test", signals=signals)
    card = build_card(verdict, claim, lang)
    assert card.outcome == Outcome.RED
    assert card.stop_line == STOP_LINE_NO_PAYMENT[Outcome.RED][1 if lang == "hi" else 0]
    assert not MONEY[lang].search(card.stop_line + " " + card.do_now)
    assert len(sentences(card.do_now)) == 1
