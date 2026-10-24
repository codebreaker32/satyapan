"""Who the message says it is: the self-claim frame, the bank-role tokens, and the open-set bodies.

Three defects the 19 Oct pass-1 judge found, all in `claimed_issuer`, all with the same shape — the engine read
the wrong sender out of a message that says in plain words who it claims to be:

1. A self-claim frame could not see past a rank and a personal name. "This is Inspector R. Mehra, CBI Cyber
   Crime Branch, New Delhi" is how a digital-arrest call actually opens, and the CBI in it reached a frame only
   by accident of the unit name; with no unit noun ("This is Inspector R. Mehra, CBI.") it anchored nothing.
2. "branch manager" was a BANK_SELF token on its own, so a CBI script ending "do not inform the branch manager
   of the reason" claimed to be the bank. The customer card for a CBI impersonation then said "Demo Bank never
   asks you to break an FD" and named the bank three times as the claimed sender.
3. A body the Issuer enum does not hold anchored nothing at all. "IRDAI Enforcement Cell, Mumbai" and
   "Narcotics Control Bureau" are letterheads, and the whole class landed on GREY with the officer's band saying
   no authority was read out of a message that spells one out.

The three probes are at the bottom, end to end through the real pipeline, because the extractor reading right is
only half of it: the point of each fix is which sentence the officer and the customer end up reading.
"""
from __future__ import annotations

import pytest

from satyapan.extract import RulesExtractor
from satyapan.models import Instruction, Issuer
from tests.conftest import run_text

X = RulesExtractor(bank_names=("Demo Bank",))


# ---- 1. a rank and a personal name between the opener and the body -----------------------------------------

RANK_AND_NAME = [
    ("This is Inspector R. Mehra, CBI Cyber Crime Branch, New Delhi.", Issuer.CBI),
    ("This is Inspector R. Mehra, CBI.", Issuer.CBI),
    ("I am Officer S. Khan, Narcotics Control Bureau.", Issuer.OTHER),
    ("This is the Inspector, CBI Cyber Cell.", Issuer.CBI),
    ("I am Deputy Director A. Raghavan, Enforcement Directorate.", Issuer.ED),
    ("Main Inspector Rakesh Verma, CBI se baat kar raha hoon.", Issuer.CBI),
    ("मैं निरीक्षक आर. मेहरा, सीबीआई से बोल रहा हूँ।", Issuer.CBI),
]

# Each of these would be matched by the LOOSE form of the bridge ("this is <anything> the $"), and each would put
# a false "claims to be X" sentence on an officer's band. What stops them is the three things the bridge
# requires: a rank word straight after the opener, a capitalised personal name, and a separator immediately in
# front of the body. The pair is (text, the body the bridge must NOT reach) — "This is Inspector R. Mehra" does
# claim to be a police officer and always has, which is why these say which claim must not appear rather than
# that nothing may.
RANK_AND_NAME_DECOYS = [
    # no rank: the bridge may not cross ordinary prose
    ("This is a copy of the letter my cousin sent, who said the CBI visited him.", Issuer.CBI),
    ("This is the second reminder about the arrears, not about the CBI inquiry at all.", Issuer.CBI),
    # a rank and a name, but the body is in the next sentence
    ("This is Inspector R. Mehra. Please report the matter to the CBI yourself.", Issuer.CBI),
    ("This is Officer Khan of the housing society committee, and the CBI was never involved in it.", Issuer.CBI),
    # lowercase prose where the name should be: not a name
    ("This is officer training material about the CBI and how it works.", Issuer.CBI),
]


@pytest.mark.parametrize("text,issuer", RANK_AND_NAME, ids=[t[:34] for t, _ in RANK_AND_NAME])
def test_a_rank_and_a_name_do_not_break_the_self_claim(text, issuer):
    c = X.extract(text)
    assert c.claimed_issuer == issuer, text
    assert c.text[c.issuer_span.start:c.issuer_span.end] == c.issuer_span.text


@pytest.mark.parametrize("text,body", RANK_AND_NAME_DECOYS, ids=[t[:34] for t, _ in RANK_AND_NAME_DECOYS])
def test_the_rank_bridge_does_not_manufacture_a_claim(text, body):
    c = X.extract(text)
    assert c.claimed_issuer != body, (
        f"a sentence that claims nothing of the kind was read as a self-claim: {text!r} -> "
        f"{c.claimed_issuer.value} from {c.issuer_span.text if c.issuer_span else None!r}")


def test_the_rank_bridge_is_not_a_tautology():
    """The loose bridge matches every decoy above; the shipped one must not.

    Without this the test above proves only that the decoys do not anchor for some other reason. It rebuilds the
    bridge the lazy way — any text between the opener and the body — shows it firing on the decoys, and asserts
    the extractor still does not read the body as the sender.
    """
    import re

    from satyapan import extract as EX

    loose = re.compile(r"\b(?:this|that|it)\s+is\b[^.;!?]{0,70}?\b(?:the\s+)?(?=CBI)", re.I)
    at_risk = [t for t, _ in RANK_AND_NAME_DECOYS if loose.search(t)]
    assert len(at_risk) >= 3, f"the decoys have to be at risk of the loose bridge, else they prove nothing: {at_risk}"
    assert any(EX._RANK in p for p in EX.ANCHOR_LEFT), "the rank bridge left ANCHOR_LEFT; this test is stale"
    for text in at_risk:
        assert X.extract(text).claimed_issuer != Issuer.CBI, text


# ---- 2. a bank role is not a bank self-claim ---------------------------------------------------------------

def test_the_branch_manager_is_not_the_bank_claiming_to_be_itself():
    """The judge's span. Telling the customer to keep a bank officer out of it is not claiming to BE one."""
    c = X.extract("You may not inform the branch manager of the reason.")
    assert c.claimed_issuer != Issuer.BANK_SELF, (
        f"'branch manager' claimed BANK_SELF again, from {c.issuer_span.text if c.issuer_span else None!r}")
    assert c.claimed_issuer == Issuer.NONE


# The two load-bearing BANK_SELF frames (decisions.md, 17 Oct pass 2). If either of these stops reading, the
# bank's own-record rules stop being asked about the scripts they exist for.
BANK_SELF_KEEPS = [
    "I am calling from your bank",
    "aapke bank se bol raha hoon",
    "This is your bank. Your account has been compromised.",
    "आपके बैंक से बोल रहा हूँ।",
    "Main Demo Bank se aapka relationship manager Rohit bol raha hoon.",
]

BANK_ROLE_NOT_A_CLAIM = [
    "You may not inform the branch manager of the reason.",
    "Do not tell the branch manager or any bank staff about this case.",
    "The branch manager will be informed by the court, not by you.",
    "Custody of the records stays with the branch manager.",
    "A copy was marked to the head office for information.",
    "शाखा प्रबंधक को कुछ न बताएँ।",
]

# The same role words inside a frame that does claim to be that person, which is what keeps the fix from being a
# plain deletion: a letter from a bank's head-office recovery cell really is the bank writing.
BANK_ROLE_IS_A_CLAIM = [
    "This is the branch manager of your Demo Bank branch.",
    "I am your branch manager and your FD matures next week.",
    "This letter is sent from the head office of your bank.",
    "Branch manager speaking. Please come in with your passbook.",
]


@pytest.mark.parametrize("text", BANK_SELF_KEEPS, ids=[t[:30] for t in BANK_SELF_KEEPS])
def test_the_load_bearing_bank_self_frames_still_read(text):
    assert X.extract(text).claimed_issuer == Issuer.BANK_SELF, text


@pytest.mark.parametrize("text", BANK_ROLE_NOT_A_CLAIM, ids=[t[:30] for t in BANK_ROLE_NOT_A_CLAIM])
def test_a_bare_bank_role_claims_nothing(text):
    c = X.extract(text)
    assert c.claimed_issuer != Issuer.BANK_SELF, (
        f"{text!r} -> BANK_SELF from {c.issuer_span.text if c.issuer_span else None!r}")


@pytest.mark.parametrize("text", BANK_ROLE_IS_A_CLAIM, ids=[t[:30] for t in BANK_ROLE_IS_A_CLAIM])
def test_a_framed_bank_role_still_claims_the_bank(text):
    assert X.extract(text).claimed_issuer == Issuer.BANK_SELF, text


# ---- 3. open-set authorities --------------------------------------------------------------------------------

OPEN_SET = [
    "IRDAI Enforcement Cell, Mumbai.",
    "Narcotics Control Bureau",
    "NARCOTICS CONTROL BUREAU\nGovernment of India",
    "Central Vigilance Commission",
    "Income Tax Department: your return has been selected for scrutiny.",
    "This is the Cyber Crime Coordination Cell.",
    "I am writing on behalf of the National Investigation Authority.",
    "स्वापक नियंत्रण ब्यूरो, मुंबई।",
    "केंद्रीय अपराध अन्वेषण प्रकोष्ठ।",
]

# The same wide net, pointed at bodies that are not the state. Every one of these is multi-word, capitalised and
# ends in one of the eight head nouns, so each is at risk of exactly this pattern; what drops them is the state
# vocabulary gate (and, for the bank's own units, the bank-name guard in `extract`).
OPEN_SET_DECOYS = [
    "Demo Bank Loan Recovery Cell, Head Office.",
    "Demo Bank Customer Grievance Cell",
    "Please contact our Customer Service Unit for help.",
    "PLEASE CONTACT OUR CUSTOMER CARE UNIT ON THE NUMBER BELOW.",
    "Acme Logistics Billing Department",
    "The Housing Society Managing Board met on Tuesday.",
    "report this message to the enforcement cell yourself",      # lowercase: not a name
    "Your complaint has been forwarded to the Grievance Redressal Cell.",   # a referral
]


@pytest.mark.parametrize("text", OPEN_SET, ids=[t[:34] for t in OPEN_SET])
def test_an_open_set_body_anchors_as_a_claimed_state_authority(text):
    c = X.extract(text)
    assert c.claimed_issuer == Issuer.OTHER, f"{text!r} -> {c.claimed_issuer.value}"
    assert c.text[c.issuer_span.start:c.issuer_span.end] == c.issuer_span.text
    assert len(c.issuer_span.text.split()) >= 2, "the span has to quote the body's own name"


@pytest.mark.parametrize("text", OPEN_SET_DECOYS, ids=[t[:34] for t in OPEN_SET_DECOYS])
def test_a_private_or_referred_unit_is_not_a_state_authority(text):
    c = X.extract(text)
    assert c.claimed_issuer != Issuer.OTHER, (
        f"{text!r} read as a government body, from {c.issuer_span.text if c.issuer_span else None!r}")


# ---- 3b. a body that names itself a company is not the state ------------------------------------------------
# Gate 3, added 19 Oct by this pass's own adversarial gate. Each of these clears gate 1 (multi-word, title-cased)
# and gate 2 (a state head noun, or a shared head noun plus a state-vocabulary marker: "intelligence", "crime",
# "investigation"), and all three were AMBER anchored on a rule titled "A state authority demands a payment"
# before the suffix was read. The Hindi card then told a frightened customer that an insurer's claims department
# was claiming to be a government body.
CORPORATE_MASTHEADS = [
    "Business Intelligence Department, Acme Retail Private Limited. Your vendor invoice is unpaid.",
    "Claims Investigation Department, Acme General Insurance Company Limited. Your policy has lapsed.",
    "Credit Information Bureau (India) Limited has recorded a default on your loan.",
    "Fraud Investigation Unit\nAcme Payments Pvt Ltd\n\nYour merchant account is under review.",
    "Crime Analytics Cell, Acme Risk Analytics LLP",
    "Revenue Assurance Directorate, Acme Telecom Ltd.",
    "जाँच विभाग, एक्मे रिटेल प्राइवेट लिमिटेड। आपका बिल बाकी है।",
]

# The other side of gate 3, and the reason it is bounded to the masthead run: a company named somewhere ELSE in
# the message says nothing about the body on the letterhead. Without the bound, one mention of any bank's legal
# name would silence the open-set net on a real digital-arrest script.
STATE_MASTHEAD_WITH_A_COMPANY_ELSEWHERE = [
    "Narcotics Control Bureau. Remit the entire amount to our collection account at HDFC Bank Limited.",
    "Central Vigilance Commission; the contractor is Acme Infra Private Limited.",
    "Cyber Crime Coordination Cell, Ministry of Home Affairs. The complaint names Acme Retail Pvt Ltd.",
]


@pytest.mark.parametrize("text", CORPORATE_MASTHEADS, ids=[t[:34] for t in CORPORATE_MASTHEADS])
def test_a_body_that_names_itself_a_company_is_not_a_state_authority(text):
    c = X.extract(text)
    assert c.claimed_issuer != Issuer.OTHER, (
        f"{text!r} read as a government body, from {c.issuer_span.text if c.issuer_span else None!r}")


@pytest.mark.parametrize("text", STATE_MASTHEAD_WITH_A_COMPANY_ELSEWHERE,
                         ids=[t[:34] for t in STATE_MASTHEAD_WITH_A_COMPANY_ELSEWHERE])
def test_a_company_named_in_another_sentence_does_not_disqualify_the_masthead(text):
    c = X.extract(text)
    assert c.claimed_issuer == Issuer.OTHER, (
        f"{text!r} lost its masthead to a company name in another sentence "
        f"({c.claimed_issuer.value} from {c.issuer_span.text if c.issuer_span else None!r})")


def test_the_corporate_suffix_gate_is_what_drops_the_masthead():
    """Not a tautology: each probe above passes the first two gates and only gate 3 stops it.

    `_names_a_state_body` is the pair of gates that shipped before this one. If it already rejected these names
    the test above would prove nothing about the suffix, and a later pass could delete gate 3 and still be green.
    """
    from satyapan.extract import RE_OPEN_BODY, RE_OPEN_BODY_HI, _names_a_company, _names_a_state_body

    for text in CORPORATE_MASTHEADS:
        m = RE_OPEN_BODY.search(text) or RE_OPEN_BODY_HI.search(text)
        assert m is not None, f"{text!r}: gate 1 already rejected the name, so gate 3 proves nothing"
        assert _names_a_state_body(m.group(0)), \
            f"{text!r}: gate 2 already rejected {m.group(0)!r}, so gate 3 proves nothing"
        assert _names_a_company(text, m), f"{text!r}: gate 3 did not read the suffix out of {m.group(0)!r}"


def test_the_banks_own_recovery_cell_is_still_the_bank():
    """The pass-5 judge's benign letter. Reading it as a government body silenced the bank's own record rule.

    This is the regression the open-set net created on its first draft and the reason for the two gates: the
    letterhead "Demo Bank Loan Recovery Cell, Head Office" is multi-word, capitalised and ends in "Cell", and
    nothing about its FORM says it is not a state body. What says so is that it names no state vocabulary and
    carries the bank's own name.
    """
    text = ("Demo Bank Loan Recovery Cell, Head Office. Your home loan account is overdue by Rs 2,84,000. "
            "You may pay at any branch counter.")
    c = X.extract(text)
    assert c.claimed_issuer == Issuer.BANK_SELF, c.issuer_span.text if c.issuer_span else None


def test_a_devanagari_masthead_anchors_at_the_same_tier_as_its_english_equivalent():
    """`सीबीआई साइबर अपराध शाखा` ≡ `CBI Cyber Crime Branch`, including the tier, not just the issuer.

    The Devanagari half of the unit-noun table was unreachable for a second reason as well, and it had been
    since the table was written: `\\b` cannot close a Devanagari noun, because a vowel sign is a nonspacing mark
    and `'ा'.isalnum()` is False. So `शाखा\\b` and `थाना\\b` matched nothing, and `पुलिस थाना` / `पुलिस चौकी`
    were dead entries.
    """
    from satyapan.extract import TIER_CLAIM, authority_hits

    pairs = [
        ("CBI Cyber Crime Branch, New Delhi", "सीबीआई साइबर अपराध शाखा, नई दिल्ली", Issuer.CBI),
        ("I am calling from the Cyber Crime Police Station, Chennai.", "मैं साइबर पुलिस थाना, चेन्नई से बोल रहा हूँ।",
         Issuer.POLICE),
    ]
    for en, hi, issuer in pairs:
        for text in (en, hi):
            c = X.extract(text)
            assert c.claimed_issuer == issuer, text
            hit = next(h for h in authority_hits(text) if h.issuer == issuer)
            assert hit.tier == TIER_CLAIM, f"{text!r} anchored at tier {hit.tier}, not a self-claim"


def test_one_unit_name_is_one_body():
    """"CBI Cyber Crime Branch" is the CBI, not the CBI plus a police crime branch.

    Both tokens used to anchor at TIER_CLAIM off the same characters, `select_issuer` saw two law-enforcement
    personas and returned None, and the judge's script then fell through to BANK_SELF on the words "branch
    manager" at the end of it. The second token must not even reach `other_issuers`: the record would be saying
    the message names two bodies when it names one.
    """
    c = X.extract("This is Inspector R. Mehra, CBI Cyber Crime Branch, New Delhi. Transfer Rs 5,00,000 to the "
                  "designated RBI supervision account 30011223344556.")
    assert c.claimed_issuer == Issuer.CBI
    assert {g.value for g in c.other_issuers} == {"RBI"}, [g.value for g in c.other_issuers]


def test_the_new_patterns_keep_their_spans_in_the_original_text_and_stay_fast():
    """The non-negotiable constraint, re-proved on the paths this pass added.

    Matching runs on a normalised copy (zero-widths dropped, confusables folded), so a pattern that stores a
    normalised offset points every quote and leader line in the console at the wrong characters. The probe is
    written with a zero-width space, a Cyrillic i and two Cyrillic o's, so every new pattern here — the rank
    bridge, the open-set name and the "wire" verb — matches only through normalisation.

    The timing assertion is there because the rank bridge and the open-set scan both backtrack; an 11 kB paste
    is an ordinary OCR'd notice and has to stay interactive.
    """
    import time

    zwsp, cyr_i, cyr_o, cyr_e = "​", "і", "о", "е"
    text = (f"This is Inspector R. Mehra, CBI{zwsp} Cyber Crime Branch. "
            f"W{cyr_i}re Rs 6,50,000 to the designated cl{cyr_e}arance acc{cyr_o}unt 39920114477.")
    c = X.extract(text)
    assert c.claimed_issuer == Issuer.CBI
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT
    spans = [c.issuer_span, c.instruction_span, c.channel_span, c.payee.claimed_owner_span]
    spans += [g.span for g in c.other_issuers] + [a.span for a in c.amounts] + list(c.pressure_cues.values())
    if c.payee.account:
        spans.append(c.payee.account.span)
    kept = [s for s in spans if s]
    assert len(kept) >= 4
    for sp in kept:
        assert c.text[sp.start:sp.end] == sp.text, sp

    big = ("This is Inspector R. Mehra, CBI Cyber Crime Branch, New Delhi. IRDAI Enforcement Cell, Mumbai. "
           "Wire Rs 6,50,000 to the designated clearance account 39920114477. ") * 70
    started = time.monotonic()
    assert X.extract(big).instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert time.monotonic() - started < 5.0, "the new patterns made an 11 kB paste too slow to be interactive"


# ---- the three probes, end to end ---------------------------------------------------------------------------

P1_IRDAI = ("IRDAI Enforcement Cell, Mumbai. Your lapsed policy is under money-laundering investigation. "
            "Deposit Rs 2,85,000 into IRDAI Verification Account 50100239847721 today or a PMLA arrest warrant "
            "will be issued. Do not discuss this with any bank staff.")
P2_CUSTOMS = ("Customs ani NCB kadun kalavnyat yete ki tumchya navavar aalela parcel madhe drugs sapadle aahet. "
              "CBI chi joint inquiry suru aahe. Rs 6,50,000 tya Customs Clearance Account 39920114477 var wire "
              "kara, nahitar udya arrest hoil. He koonala sangu naka.")
P3_CBI = ("This is Inspector R. Mehra, CBI Cyber Crime Branch, New Delhi. Your holdings must be parked in the "
          "designated RBI supervision account 30011223344556 while the case is open. Keep this video call "
          "connected and do not inform the branch manager of the reason.")


def test_p1_an_open_set_body_demanding_money_is_no_longer_grey(engine):
    """Was GREY with claimed_issuer NONE: a letterhead body the enum has no row for read as no sender at all.

    The anchor moved from R-AGENCY-PAY to R-STATE-NAME-PAY on 19 Oct and the verdict did not: the open-set class
    keeps its hard F1 rule and its AMBER, with a sentence that does not say who the sender is.
    """
    case = run_text(engine, P1_IRDAI, amount=285000)
    assert case.claim.claimed_issuer == Issuer.OTHER
    assert case.claim.issuer_span.text == "IRDAI Enforcement Cell"
    assert case.claim.instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert case.verdict.anchor_rule == "R-STATE-NAME-PAY"
    assert case.verdict.outcome.value == "AMBER", "a lone hard rule is AMBER, and that is the invariant"


# ---- the benign class the open set caught, end to end --------------------------------------------------------

BENIGN_CORPORATE = [
    ("Business Intelligence Department, Acme Retail Private Limited. Your vendor invoice is unpaid.\n"
     "You must transfer Rs 3,00,000 to account 20098765432109 by Friday.", 300000),
    ("Claims Investigation Department, Acme General Insurance Company Limited. Your policy has lapsed.\n"
     "Please credit this account with Rs 25,000 to reinstate cover. Account 20098765432109.", 25000),
    ("Credit Information Bureau (India) Limited has recorded a default on your loan. You must transfer\n"
     "Rs 2,00,000 to account 20098765432109 within seven days.", 200000),
]
# What a card may never say about a sender who may be an ordinary company, in either language.
ACCUSING = ["claims to be", "दावा करता है", "a government body", "सरकारी संस्था", "government-sounding",
            "सरकारी दफ़्तर जैसा"]


@pytest.mark.parametrize("text,amount", BENIGN_CORPORATE, ids=[t[:34] for t, _ in BENIGN_CORPORATE])
def test_a_corporate_department_gets_no_card_that_accuses_its_sender(engine, text, amount):
    """The whole point of gate 3, measured where it is paid: on the card the officer reads aloud.

    Each of these was AMBER anchored on a rule titled "A state authority demands a payment", and the Hindi card
    read "यह संदेश कोई सरकारी संस्था होने का दावा करता है" — a false statement of fact about the sender, read to
    a frightened customer, with the matching title on the officer's band and in the signed evidence pack.
    """
    case = run_text(engine, text, amount=amount)
    assert case.claim.claimed_issuer != Issuer.OTHER, case.claim.issuer_span
    fired = {s.rule_id for s in case.verdict.signals}
    assert "R-AGENCY-PAY" not in fired and "R-STATE-NAME-PAY" not in fired
    for lang in ("hi", "en"):
        card = engine.card(case, lang)
        aloud = card.read_aloud
        for phrase in ACCUSING:
            assert phrase not in aloud, f"{lang}: the card said {phrase!r}\n{aloud}"


def test_p2_the_romanised_marathi_wire_demand_is_read(engine):
    """Was GREY with instruction NONE: "var wire kara" was not in the verb family, so nothing asked for money."""
    case = run_text(engine, P2_CUSTOMS, amount=650000)
    assert case.claim.instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert "wire" in case.claim.instruction_span.text
    assert case.claim.claimed_issuer == Issuer.CUSTOMS
    assert case.verdict.anchor_rule == "R-AGENCY-PAY"
    assert case.verdict.outcome.value == "AMBER"


def test_p3_the_cbi_script_is_not_attributed_to_the_bank(engine):
    """Was RED for the wrong reason: claimed_issuer BANK_SELF, off the words "branch manager".

    The verdict was already right. What was wrong is everything the customer reads: the card said "Demo Bank
    never asks you to break an FD" about a CBI impersonation and named the bank three times as the claimed
    sender. The body the card names now is the one the message says it is, in words.
    """
    case = run_text(engine, P3_CBI, amount=3800000)
    assert case.claim.claimed_issuer == Issuer.CBI
    assert case.claim.instruction == Instruction.TRANSFER_TO_ACCOUNT
    assert case.verdict.outcome.value == "RED"
    fired = {s.rule_id for s in case.verdict.signals}
    assert "R-AGENCY-PAY" in fired
    assert "R-BANK-SELF" not in fired and "R-BANK-NEVER-MOVE-FD" not in fired, \
        "a bank-own-record rule fired on a message that never claimed to be the bank"
    for lang in ("en", "hi"):
        card = engine.card(case, lang)
        prose = " ".join(r.text for r in card.reasons) + card.headline
        assert "Demo Bank" not in prose and "डेमो बैंक" not in prose, prose
