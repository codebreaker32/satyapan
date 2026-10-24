"""The customer card: what the officer reads aloud, in Hindi or English. Three cited reasons and ONE instruction.
No scores, and never the words "fake", "genuine" or "fraud" (see FORBIDDEN; tests lint every template and output).

Five rules shape the copy below, every one of them from a judge reading the card aloud as a frightened 70-year-old
would hear it. None of them touches a verdict: they are copy and gates, and the outcome words never move.

1. One instruction. The card used to end the call, refuse the payment, verify with the issuer and promise help with
   a report, which is four things to remember under pressure. `do_now` is now a single imperative sentence in both
   languages for every outcome; everything else the officer does moves to `say_next`, which is for the officer's
   eyes and is never part of `read_aloud`.
2. Money wording only when money was asked for. A benign re-KYC SMS that asks for nothing used to get a card
   saying "do not send money now". `fusion.money_in_play` reads the claim, and the no-payment copy talks about
   confirming the message before acting on it. No verdict, outcome word or fusion logic depends on this. The
   headline is NOT chosen here any more: `fuse` sets a payment-neutral AMBER headline from the same predicate,
   so the officer's band and the customer's card say the same words on the same screen.
3. A clause that describes the customer's message must rest on a span (see GROUNDED_CLAUSES below). A judge's
   Customs/NDPS probe got a card that said the message asked her to invest, and an EPFO probe got a promise to
   call her relationship manager. Neither was in her message. A clause with nothing to point at is dropped.
4. The card never asserts something about the situation that the artefact does not carry. "End the call now."
   was on every RED, including an OCR'd scanned notice and a voice note, where there is no call to end. It is
   gated on `_on_a_call` now, which is the gate `rules._call_number` argues for in its own docstring.
5. A technical token does not get read aloud to a frightened 70-year-old. The SIMULATED provenance stamp on a
   rehearsal forensics result stays on the officer's evidence row and leaves the card (SIMULATED_MARKER); where
   the rulebook's wording is written for an officer, the card has its own sentence (CARD_SENTENCES).
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .fusion import money_in_play
from .models import (GOVT_DUES, GOVT_SENDERS, Claim, ClaimedOwner, Family, Instruction, Issuer, Outcome, Severity,
                     Signal, Span, Verdict)
from .rules import CALL_ARTEFACTS, CALL_CHANNELS

FORBIDDEN = {
    "en": [r"\bfake\b", r"\bgenuine\b", r"\bfraud", r"\bscam\b", r"\bcriminal\b", r"\bliar\b"],
    # सही / सच / प्रामाणिक / वैध are the Hindi side of "genuine": they call the message itself true or valid,
    # which no verdict licenses. MATCHES only says the bank's signature and outbound log agree about who sent it.
    # धोख covers धोखा, धोखे and धोखाधड़ी in one pattern: "यह संदेश धोखा है" ("this message is a deception") is a
    # verdict no outcome licenses, and the family was only half banned before. The coaching line's recorded
    # "इस धोखे का हिस्सा" survives through ALLOWED_PHRASES, which is a phrase carve-out, not a free field.
    "hi": [r"नकली", r"असली", r"धोख", r"फ़र्ज़ी", r"फर्जी", r"जाली", r"ठग",
           # narrowed with lookaheads so a legitimate word that merely starts with one of these is not banned:
           # सचेत ("stay alert") is copy we want, and वैधानिक ("statutory") describes a process, not the message.
           # अवैध stays caught on purpose: calling the message invalid is a verdict no outcome licenses.
           r"सही", r"सच(?!ेत)", r"प्रामाणिक", r"वैध(?!ानिक)"],
}
# The only words a `coaching` or `read_aloud` string may carry that the rest of the card may not, written as the
# exact phrase and masked out before the patterns run, so everything around it is still linted. "इस धोखे का
# हिस्सा" ("part of this deception") describes the COACHING the caller gave her — do not trust the bank, say the
# money is for something else — and never the message, the sender or a person. It is the one carve-out this card
# has ever had, argued on 17 Oct (pass 1's adversarial note, then pass 4's Hindi copy pass) and kept on purpose:
# softening it would weaken the only warning on the card that is about the attack rather than about the message.
ALLOWED_PHRASES = ("इस धोखे का हिस्सा",)
# Fields whose text the carve-out applies to. Nothing else: a banned word in a reason, a headline, a stop line, an
# instruction or an officer line raises whatever it sits next to.
ALLOWED_PHRASE_FIELDS = ("coaching", "read_aloud")

# ONE sentence per language per outcome. The stop line above it already says "stop", so RED's instruction is the one
# she has to carry out of the branch: the next call changes nothing. AMBER is the bank's own offer to confirm; GREY
# cannot confirm, so it hands her the route. MATCHES has no payment to stop, so its instruction is the standing rule.
DO_NOW = {
    Outcome.RED: ("Do not send this money to anyone, even if they call you again.",
                  "यह पैसा किसी को न भेजें, चाहे वे दोबारा फ़ोन करें।"),
    Outcome.AMBER: ("Do not send this money until we have confirmed it with them.",
                    "जब तक हम उनसे पुष्टि न कर लें, पैसे न भेजें।"),
    Outcome.GREY: ("Check this here before you send any money: {route}",
                   "पैसे भेजने से पहले इसे यहाँ जाँच लें: {route}"),
    Outcome.MATCHES: ("Remember that we never ask you to move money to another account to keep it safe.",
                      "याद रखें, हम कभी आपसे पैसा सुरक्षित रखने के लिए दूसरे खाते में भेजने को नहीं कहते।"),
}
# Nobody asked her for money, so the card must not tell her to stop paying. Same single instruction, same outcome,
# aimed at the thing she was actually asked to do. MATCHES keeps its standing rule either way, and GREY's stop line
# never mentioned money, so neither needs a second stop line.
DO_NOW_NO_PAYMENT = {
    Outcome.RED: ("Do not act on this message, even if they call you again.",
                  "इस संदेश पर कुछ न करें, चाहे वे दोबारा फ़ोन करें।"),
    Outcome.AMBER: ("Do not act on this message until we have confirmed it with them.",
                    "जब तक हम उनसे पुष्टि न कर लें, इस संदेश पर कुछ न करें।"),
    Outcome.GREY: ("Check this here before you act on it: {route}",
                   "इस पर कुछ करने से पहले इसे यहाँ जाँच लें: {route}"),
}
STOP_LINE = {Outcome.RED: ("Please stop. Do not send this money now.", "रुकिए। अभी यह पैसा न भेजें।"),
             Outcome.AMBER: ("Please wait before paying.", "पैसे भेजने से पहले रुकिए।"),
             Outcome.GREY: ("We could not confirm this.", "हम इसकी पुष्टि नहीं कर सके।"),
             # MATCHES is a provenance finding, so the Hindi says who sent the message and nothing about its content.
             # both sides say only what MATCHES rests on: the bank's own signature and its outbound log agree that
             # the bank sent this. Neither claims the message's contents are true.
             Outcome.MATCHES: ("We sent this message ourselves.", "यह संदेश हमने ही भेजा था।")}
STOP_LINE_NO_PAYMENT = {Outcome.RED: ("Please stop. Do not act on this message.", "रुकिए। इस संदेश पर कुछ न करें।"),
                        Outcome.AMBER: ("Please wait before you act on this.", "इस पर कुछ करने से पहले रुकिए।")}
# The headline is the verdict's, verbatim, in both languages and on both surfaces. There is no card-side override
# any more: the one case that needed one — AMBER over a message that asked for no money, where the band read
# "Verify before paying" and the card read "Confirm this message first" on the same screen — is now decided once,
# in `fusion.HEADLINES_NO_PAYMENT`, from the predicate this file also uses for its own copy.
#
# What the OFFICER does next, in the card's language. Never read aloud, never on the card she takes home: these are
# the three things that used to be crammed into do_now. Still linted, because the officer reads them off the screen
# while she is sitting there.
SAY_NEXT = {
    Outcome.RED: (["Tell her we will help her report the number and the account.",
                   "Check it with them here while she waits: {route}"],
                  ["उन्हें बताएँ कि नंबर और खाते की रिपोर्ट करने में हम मदद करेंगे।",
                   "उनके सामने ही इसे यहाँ जाँचें: {route}"]),
    Outcome.AMBER: (["Offer to check it with them here: {route}",
                     "Tell her nothing has to be decided today."],
                    ["उन्हें बताएँ कि हम इसे यहाँ जाँच सकते हैं: {route}",
                     "उन्हें बताएँ कि आज कुछ तय करने की ज़रूरत नहीं है।"]),
    Outcome.GREY: (["Say plainly that we could not confirm it.",
                    "Walk her through checking it here: {route}",
                    "Tell her she can come back to us with whatever they say."],
                   ["साफ़ बताएँ कि हम इसकी पुष्टि नहीं कर सके।",
                    "उन्हें यहाँ जाँचने का तरीक़ा दिखाएँ: {route}",
                    "उन्हें बताएँ कि वे उनका जवाब लेकर हमारे पास फिर आ सकती हैं।"]),
    Outcome.MATCHES: (["Say that this message is in our own outbound log.",
                       "Tell her to check anything she gets later here: {route}"],
                      ["बताएँ कि यह संदेश हमारे ही भेजे हुए रिकॉर्ड में मिला है।",
                       "आगे कोई संदेश आए तो जाँचने के लिए यही जगह बताएँ: {route}"]),
}
# Said only when a call is actually happening in front of the officer, and prepended to the lines above. "End the
# call now." was the first line of every RED, so it went out over an OCR'd scanned notice (S3, the demo's flagship
# RED) and over a voice note, asserting a call that did not exist. See `_on_a_call`.
SAY_NEXT_ON_A_CALL = {
    Outcome.RED: ("End the call now.", "कॉल अभी काटें।"),
}
COACHING = ("If someone told you to ignore the bank or to say the money is for something else, that is part of the trick.",
            "अगर किसी ने आपसे कहा है कि बैंक की बात मत मानिए, या पैसे की वजह कुछ और बताइए, तो वही इस धोखे का हिस्सा है।")
# COACHING is about the *coaching* she was given, not about the message, and it only appears on RED/AMBER cards. The
# second clause coaches her about a payment story, so it drops out when no payment was asked for; the first clause
# is the part that still applies, because the coaching to distrust the bank comes with every one of these messages.
#
# The English said "part of the scam" until 19 Oct. `FORBIDDEN["en"]` has banned `\bscam\b` since the card existed,
# and `lint_card` did not cover `coaching` — which `make_card` concatenates into `read_aloud` — so a word the
# product bans was read aloud to the customer on every RED and AMBER card in English. "The trick" says the same
# thing about the same behaviour and labels nothing. The Hindi keeps "इस धोखे का हिस्सा" (ALLOWED_PHRASES).
COACHING_NO_PAYMENT = ("If someone told you to ignore the bank, that is part of the trick.",
                       "अगर किसी ने आपसे कहा है कि बैंक की बात मत मानिए, तो वही इस धोखे का हिस्सा है।")
DEFAULT_ROUTE_EN = "the authority's own website or helpline, or your bank's 1600 number"
DEFAULT_ROUTE_HI = "संस्था की अपनी वेबसाइट या हेल्पलाइन, या बैंक का 1600 नंबर"
# A route is read aloud on GREY, so it has to survive being spoken. "enforcementdirectorate.gov.in → Verify Your
# Summon" read out as a domain, a silence and three English words; the menu label itself stays verbatim, because
# it is what she has to find on the page, and the arrow becomes the words around it.
ISSUER_ROUTES = {
    "ED": ("the “Verify Your Summon” page on enforcementdirectorate.gov.in",
           "enforcementdirectorate.gov.in पर “Verify Your Summon” वाला पन्ना"),
    "CBI": ("CBI's ABHAY notice-verification helpbot (abhay.cbi.gov.in)", "CBI का ABHAY नोटिस-जाँच हेल्पबॉट (abhay.cbi.gov.in)"),
    "RBI": ("rbi.org.in, or the bank's 1600 number", "rbi.org.in, या बैंक का 1600 नंबर"),
    "SEBI": ("SEBI Check (sebi.gov.in)", "SEBI Check (sebi.gov.in)"),
    "TRANSPORT": ("the official e-challan website, echallan.parivahan.gov.in",
                  "आधिकारिक ई-चालान वेबसाइट, echallan.parivahan.gov.in"),
    "MUNICIPAL": ("your municipal corporation's own website or office", "आपके नगर निगम की अपनी वेबसाइट या दफ़्तर"),
    "BANK_SELF": ("your bank's 1600 number or your branch", "बैंक का 1600 नंबर या आपकी शाखा"),
}
# A due names its route even when the message names no sender: a challan is checked on the e-challan site and a
# property tax with the municipal body, whoever the message says it is from.
DUE_ROUTES = {Instruction.PAY_CHALLAN: "TRANSPORT", Instruction.PAY_LOCAL_TAX: "MUNICIPAL"}


def _route(claim: Claim) -> tuple[str, str]:
    key = claim.claimed_issuer.value if claim.claimed_issuer.value in ISSUER_ROUTES else DUE_ROUTES.get(claim.instruction)
    return ISSUER_ROUTES.get(key or "", (DEFAULT_ROUTE_EN, DEFAULT_ROUTE_HI))


class Reason(BaseModel):
    text: str
    cite: str
    rule_id: str


class Card(BaseModel):
    lang: str
    outcome: Outcome
    headline: str
    stop_line: str
    reasons: list[Reason]
    do_now: str                            # exactly one instruction, in her language
    say_next: list[str] = Field(default_factory=list)   # the officer's own next lines; never part of read_aloud
    coaching: str | None = None
    read_aloud: str = ""


# ---------------------------------------------------------------- grounding a clause that describes the message
#
# The rule: every clause of a reason that describes the customer's MESSAGE (it claims to be from X, it asks you to
# do Y, the account belongs to Z) may only be read aloud when the claim carries a verbatim span for it. When the
# span is missing the clause is dropped, never guessed, and what is left must still be a sentence in both
# languages. If dropping leaves nothing, the whole reason goes and the next-ranked signal takes its place, so the
# card still carries up to three. Clauses about the BANK's own records ("we have no record of sending this", "the
# account is registered to X") are not message-describing: they rest on a bank lookup, not on the message.
#
# What carries a span is fixed by models.py: issuer_span, instruction_span, payee.claimed_owner_span, and the
# Grounded payee.account / ifsc / vpa. `claim.mentions_summons` is a bare bool with no span, so no clause here
# depends on it; the ED reasons that rest on it also name ED, and that issuer clause is guarded.
E_ISSUER, E_INSTRUCTION, E_OWNER, E_ACCOUNT = "issuer", "instruction", "claimed_owner", "payee_account"

# The one party a reason promises a bank action about. "We will call your relationship manager" needs two things
# the case can actually carry: the bank's RM directory must have named one (the rule puts the name in `detail`),
# and the customer's message must be the one that invoked an RM. The rule fires on a sender-number match against
# the RM directory, which on an EPFO pension notice says only that the number is in the directory, not that the
# message has anything to do with her RM.
RM_IN_MESSAGE = re.compile(r"relationship\s*manager|\bRM\b|रिलेशनशिप\s*मैनेजर|आर\.?एम\.?", re.I)
SENTENCE_BREAK = re.compile(r"(?<=[.?!।])\s+")


def _sentences(text: str) -> list[str]:
    return [p for p in SENTENCE_BREAK.split(text.strip()) if p]


def _quotes_the_message(span: Span | None, text: str) -> bool:
    """A span is support only if it is still a verbatim quote of the message (the models.py rule, re-checked here).

    `extract.ground()` enforces this on the extractor's output; the card checks it again because a card can be
    built from any claim the API or an officer correction hands it, and a stale span supports nothing.
    """
    return span is not None and bool(span.text) and text[span.start:span.end] == span.text


def grounded_entities(claim: Claim) -> set[str]:
    """The things about the message the card is allowed to name, because the claim can point at words for them."""
    out: set[str] = set()
    if claim.claimed_issuer != Issuer.NONE and _quotes_the_message(claim.issuer_span, claim.text):
        out.add(E_ISSUER)
    if claim.instruction != Instruction.NONE and _quotes_the_message(claim.instruction_span, claim.text):
        out.add(E_INSTRUCTION)
    if claim.payee.claimed_owner != ClaimedOwner.UNKNOWN and _quotes_the_message(claim.payee.claimed_owner_span, claim.text):
        out.add(E_OWNER)
    if claim.payee.account and _quotes_the_message(claim.payee.account.span, claim.text):
        out.add(E_ACCOUNT)
    return out


def _agency_pay(text: str, signal: Signal, claim: Claim, hi: bool) -> str | None:
    """"... This message claims to be {issuer} and asks for {instruction}." Each half needs its own span."""
    g = grounded_entities(claim)
    d = signal.detail
    issuer = d.get("issuer_hi" if hi else "issuer_en") if E_ISSUER in g else None
    instruction = d.get("instruction_hi" if hi else "instruction_en") if E_INSTRUCTION in g else None
    if issuer and instruction:
        return text
    law = _sentences(text)[0]          # the law itself, which describes no message
    if issuer and hi:
        return f"{law} यह संदेश {issuer} होने का दावा करता है।"
    if issuer:
        return f"{law} This message claims to be {issuer}."
    if instruction and hi:
        return f"{law} यह संदेश {instruction} कह रहा है।"
    if instruction:
        return f"{law} This message asks for {instruction}."
    return law


def _state_name_pay(text: str, signal: Signal, claim: Claim, hi: bool) -> str | None:
    """Three sentences: the practice, what was read out of the message, and what our own check could not settle.

    Only the middle one describes the message, and it has two halves with a span each — the name (issuer_span)
    and the demand (instruction_span). The first sentence is a fact about government agencies and the third is a
    fact about us, so both survive an ungrounded claim. Dropping the middle one entirely is why this handler is
    here: with neither span the reason is still true and still useful, and it no longer says anything at all
    about the sender.

    Note what is NOT here, by contrast with `_agency_pay`: the body's name. The sentence says the name sounds
    like a government office's, which is what the open-set net read, and never that the sender is or claims to be
    one. "Claims Investigation Department, Acme General Insurance Company Limited" is a real department of a real
    insurer, and this reason has to be honest on it.
    """
    s = _sentences(text)
    practice, read, unconfirmed = s[0], s[1], " ".join(s[2:])
    g = grounded_entities(claim)
    instruction = signal.detail.get("instruction_hi" if hi else "instruction_en") if E_INSTRUCTION in g else None
    if E_ISSUER in g and instruction:
        return text
    if E_ISSUER in g:
        read = ("इस संदेश पर सरकारी दफ़्तर जैसा नाम लिखा है।" if hi
                else "This message carries a government-sounding name.")
    elif instruction:
        read = (f"यह संदेश {instruction} कह रहा है।" if hi else f"This message asks for {instruction}.")
    else:
        read = ""
    return " ".join(p for p in (practice, read, unconfirmed) if p)


def _never_move_fd(text: str, signal: Signal, claim: Claim, hi: bool) -> str | None:
    """"... That instruction does not come from us." — "that instruction" is the message's, so it needs the span."""
    if E_INSTRUCTION in grounded_entities(claim):
        return text
    return _sentences(text)[0]


def _payee_name(text: str, signal: Signal, claim: Claim, hi: bool) -> str | None:
    """"The account you were told belongs to {claimed} is registered to X." Only the first half is the message's."""
    g = grounded_entities(claim)
    if E_ACCOUNT not in g:
        return None                    # no account in the message: the whole reason has nothing to stand on
    if E_OWNER in g:
        return text
    d = signal.detail
    holder, kind = d.get("holder"), d.get("holder_type_hi" if hi else "holder_type_en")
    if not holder or not kind:
        return None
    if hi:
        return f"यह खाता बैंक रिकॉर्ड में “{holder}” ({kind}) के नाम पर है।"
    return f"This account is registered to “{holder}” ({kind})."


def _payee_not_sender(text: str, signal: Signal, claim: Claim, hi: bool) -> str | None:
    """"This message is in the name of {issuer}, but the account it gives is registered to X."

    Two halves describe the message (who it is in the name of, and the account or UPI ID it gives) and one is the
    bank's own record. With no grounded payee the reason has nothing to stand on, as for R-PAYEE-NAME. Without a grounded
    sender it falls back to the due the message asked for, which carries its own span ("this message asks for
    paying property or house tax"), and with neither it keeps only the bank's record, the sentence R-PAYEE-NAME
    falls back to.
    """
    g = grounded_entities(claim)
    d = signal.detail
    on_vpa = d.get("payee_kind") == "vpa"
    if on_vpa:
        if claim.payee.vpa is None or not _quotes_the_message(claim.payee.vpa.span, claim.text):
            return None
    elif E_ACCOUNT not in g:
        return None
    holder, kind = d.get("holder"), d.get("holder_type_hi" if hi else "holder_type_en")
    if not holder or not kind:
        return None
    payee_en, payee_hi = d.get("payee_en", "account"), d.get("payee_hi", "दिया गया खाता")
    if E_ISSUER in g and claim.claimed_issuer in GOVT_SENDERS:
        return text
    instruction = d.get("instruction_hi" if hi else "instruction_en") if E_INSTRUCTION in g else None
    if instruction and claim.instruction in GOVT_DUES:
        if hi:
            return f"यह संदेश {instruction} कह रहा है, लेकिन इसमें {payee_hi} बैंक रिकॉर्ड में “{holder}” ({kind}) के नाम पर है।"
        return f"This message asks for {instruction}, but the {payee_en} it gives is registered to “{holder}” ({kind})."
    if hi:
        return f"यह {'UPI आईडी' if on_vpa else 'खाता'} बैंक रिकॉर्ड में “{holder}” ({kind}) के नाम पर है।"
    return f"This {payee_en} is registered to “{holder}” ({kind})."


def _rm_phone(text: str, signal: Signal, claim: Claim, hi: bool) -> str | None:
    """"... We will call your relationship manager from the bank's own number." Only if the case has that party."""
    if signal.detail.get("rm") and RM_IN_MESSAGE.search(claim.text):
        return text
    return _sentences(text)[0]


# Every rule whose customer-facing reason carries a clause about the message. A rule that is not here says nothing
# about the message, or says it with a value the rule itself could not have read without a span (the payee UPI id,
# the link, the summons number). tests/test_grounded_clauses.py pins both halves of that claim.
GROUNDED_CLAUSES = {
    "R-AGENCY-PAY": _agency_pay,
    "R-STATE-NAME-PAY": _state_name_pay,
    "R-BANK-NEVER-MOVE-FD": _never_move_fd,
    "R-PAYEE-NAME": _payee_name,
    "R-PAYEE-NOT-SENDER": _payee_not_sender,
    "R-BANK-RM-PHONE": _rm_phone,
}


# ---------------------------------------------------------------- what the card may not read aloud
#
# `forensics.to_signal` stamps "(SIMULATED)" into the band a rehearsal forensics result reports, so the rulebook's
# reason comes out as "...(moderate (SIMULATED))" and the Hindi as "...(मध्यम (SIMULATED))" — a Latin technical
# word inside a Devanagari sentence being read to a frightened 70-year-old, in the middle of nested brackets.
# The marker is provenance about the detector, which is the officer's business. It stays, verbatim, on
# `signal.reason_en` / `signal.reason_hi` (the officer's evidence row renders those as they are, next to its own
# "Simulated" tag), on `detail.simulated`, and in the signed pack. Only the card drops it. That is the same move
# pass 5 made with the computed outbound-log coverage: the property stays, the surface changes.
SIMULATED_MARKER = re.compile(r"\s*\(SIMULATED\)")


def _suspect_registry(signal: Signal, hi: bool) -> str | None:
    """The card's own wording for the one reason that rests on a record nobody in the room owns.

    The rulebook says "This phone number is already listed in the national suspect registry run by I4C", which is
    right for the officer's row and wrong on the card twice over. "I4C" is an acronym the customer cannot expand,
    and the sentence asserts what a national registry contains rather than what our check found — so the only
    sentence on the card that claims an outside fact was also the only one with no provenance, while the officer's
    signal row beside it carried the adapter's "Mock lookup" label.

    Attributing it to the check is the move pass 5 made on R-BANK-SELF ("{bank} has no record of sending this
    message", not "the bank did not send it"): what we did and what we found, which is as true over a mock as
    over the production registry feed, and the holder of the list named in words instead of initials. Rejected
    alternative: stamping "mock" on the customer's card. Every reason on every card in this build rests on a
    mocked adapter, so that rule would turn the card into a rehearsal artefact; the mock labels belong on the
    officer's surface and in the pack, which is where this repo has always put them.
    """
    what = signal.detail.get("what_hi" if hi else "what")
    if not what:
        return None
    if hi:
        # "हमने जाँचा और ..." is reported direct speech, which is the register pass 4 settled on for this card;
        # "पहले से दर्ज है" keeps the rulebook's "already", which is the part that matters to her — the number was
        # known before her case. "ठगी" would be the natural word for the list's subject and is deliberately not
        # used: it is one letter from ठग, which FORBIDDEN bans, and the lint would stop it anyway.
        return f"हमने जाँचा और यह {what} सरकार की साइबर अपराध संदिग्ध सूची में पहले से दर्ज है।"
    return f"We checked, and this {what} is already on the government's cyber-crime suspect list."


# A rule whose rulebook reason is written for the officer and needs the card's own sentence instead. Nothing here
# overlaps GROUNDED_CLAUSES: these rules describe a lookup, not the message, so there is no span to point at.
CARD_SENTENCES = {
    "R-SUSPECT": _suspect_registry,
}


def ground_reason(signal: Signal, claim: Claim, hi: bool) -> str | None:
    """The reason as it may be read aloud: the card's own sentence where it has one, ungrounded clauses dropped,
    technical markers taken out, or None if nothing honest is left."""
    own = CARD_SENTENCES.get(signal.rule_id)
    text = own(signal, hi) if own else (signal.reason_hi if hi else signal.reason_en)
    handler = GROUNDED_CLAUSES.get(signal.rule_id)
    if text is not None and handler is not None:
        text = handler(text, signal, claim, hi)
    if not text:
        return None
    text = SIMULATED_MARKER.sub("", text).strip()
    return text or None


def _rank(s: Signal) -> tuple:
    # Hard first, then softs that mean "verify first", then other softs, then forensics; F5 and info never show.
    sev = {Severity.HARD: 0, Severity.SOFT: 1, Severity.MATCH: 0}.get(s.severity, 9)
    fam = {Family.F1: 0, Family.F2: 0, Family.F4: 1, Family.F3: 2, Family.F5: 9}[s.family]
    return (sev, 0 if s.escalate_alone else 1, fam)


def _on_a_call(claim: Claim) -> bool:
    """Is a call happening in front of the officer right now? "End the call now." needs this to be true.

    Both halves, for the reasons `rules._call_number` sets out at length and which apply here word for word. The
    ARTEFACT has to be one that can carry a call — a transcript of one, or the officer's own picklist saying the
    customer is on one — because a channel read out of a pasted message is a fact about what the message
    DESCRIBES, not about what is in front of her: an SMS reading "call our helpline" sets `channel` to
    PHONE_CALL off its own words. And the CHANNEL has to say the call is a call rather than a voice note, which
    is a recording of somebody who is not there any more.

    The cost is the same cost that gate paid: a scam call pasted in as plain text loses the line, and the officer
    has to say it is a call by uploading the recording or ticking the channel. For a line that orders her to cut a
    call off, erring towards saying nothing is the right side.
    """
    return claim.source in CALL_ARTEFACTS and claim.channel in CALL_CHANNELS


def build_card(verdict: Verdict, claim: Claim, lang: str = "hi") -> Card:
    hi = lang == "hi"
    shown = [s for s in verdict.signals if s.severity in (Severity.HARD, Severity.SOFT, Severity.MATCH) and s.family != Family.F5]
    shown.sort(key=_rank)
    # Three reasons at most, and a reason only counts if what is left of it after grounding still says something.
    # A reason dropped here is not replaced by silence: the next-ranked signal moves up.
    reasons: list[Reason] = []
    for s in shown:
        text = ground_reason(s, claim, hi)
        if text is None:
            continue
        reasons.append(Reason(text=text, cite=s.citation, rule_id=s.rule_id))
        if len(reasons) == 3:
            break

    route_en, route_hi = _route(claim)
    route = route_hi if hi else route_en
    pays = money_in_play(claim)
    do_table = DO_NOW if pays else {**DO_NOW, **DO_NOW_NO_PAYMENT}
    stop_table = STOP_LINE if pays else {**STOP_LINE, **STOP_LINE_NO_PAYMENT}
    do_now = do_table[verdict.outcome][1 if hi else 0].format(route=route)
    # The verdict's headline, verbatim: `fuse` already chose the payment-neutral AMBER from `money_in_play`, so
    # overriding it here is what made the band and the card disagree.
    headline = (verdict.headline_hi if hi else verdict.headline_en)
    stop = stop_table[verdict.outcome][1 if hi else 0]
    lines_next = list(SAY_NEXT[verdict.outcome][1 if hi else 0])
    on_call = SAY_NEXT_ON_A_CALL.get(verdict.outcome) if _on_a_call(claim) else None
    if on_call:
        lines_next.insert(0, on_call[1 if hi else 0])
    say_next = [line.format(route=route) for line in lines_next]
    coach = COACHING if pays else COACHING_NO_PAYMENT
    coaching = coach[1 if hi else 0] if verdict.outcome in (Outcome.RED, Outcome.AMBER) else None

    # What she hears is exactly what is on the card: the stop line, the headline, the numbered reasons, one
    # instruction, and the coaching line on RED and AMBER. say_next is the officer's and stays out of this.
    lines = ([stop, headline] + [f"{i + 1}. {r.text}" for i, r in enumerate(reasons)]
             + [do_now] + ([coaching] if coaching else []))
    card = Card(lang=lang, outcome=verdict.outcome, headline=headline, stop_line=stop, reasons=reasons, do_now=do_now,
                say_next=say_next, coaching=coaching, read_aloud="\n".join(lines))
    lint_card(card)
    return card


def lint_card(card: Card) -> None:
    """Customer-facing text must never label the message itself. Raise if a forbidden word slips in.

    Every field, including `coaching` and `read_aloud`. Those two were exempt until 19 Oct, which is how the
    shipped English coaching line ended "...that is part of the scam" while `FORBIDDEN["en"]` banned `\\bscam\\b`
    and `build_card` concatenated the line into `read_aloud`: the card read a banned word out loud on every
    English RED and AMBER, and the suite was green. `read_aloud` is linted even though it is built out of fields
    already checked, because a Card can be handed to this function by the API or an officer correction.

    `say_next` is linted too: the officer reads it off the screen in front of her, so the same words are out.

    ALLOWED_PHRASES is the one exception, and it is a phrase mask rather than a field exemption. The phrase is
    removed from the text and everything left around it is still checked, so the recorded "इस धोखे का हिस्सा"
    carve-out cannot be stretched into a licence to call the message a deception.
    """
    fields = [("headline", card.headline), ("stop_line", card.stop_line), ("do_now", card.do_now)]
    fields += [(f"reasons[{i}]", r.text) for i, r in enumerate(card.reasons)]
    fields += [(f"say_next[{i}]", line) for i, line in enumerate(card.say_next)]
    fields += [("coaching", card.coaching or ""), ("read_aloud", card.read_aloud)]
    for field, text in fields:
        probe = text
        if field in ALLOWED_PHRASE_FIELDS:
            for phrase in ALLOWED_PHRASES:
                probe = probe.replace(phrase, " ")
        for pat in FORBIDDEN["en"] + FORBIDDEN["hi"]:
            if re.search(pat, probe, re.I):
                raise ValueError(f"forbidden word {pat!r} in customer-facing {field}: {text!r}")
