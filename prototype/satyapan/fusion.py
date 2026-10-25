"""Ordered fusion policy. With no judged media it is not a weighted score: a RED needs a cited hard rule plus a
signal from a different family that rests on different evidence. F5 (context) and anything marked can_be_second=False
never count as the second.

Outcomes, in order of evaluation:
  MATCHES  the bank's own signed message, found in its outbound log, and no hard rule fired
  RED      >= 1 hard rule (verified citation) AND an independent second signal (other family, other evidence),
           AND a money demand was read out of the message
  AMBER    a hard rule with no second family; or a RED pair with no money demand read; or >= 2 independent soft
           signals; or one soft marked escalate_alone
  GREY     nothing above; "could not confirm" is never presented as "safe"

That ladder runs on the instruction checks only (every family but F3). When media was attached and the detector could
judge it, the combined score at the end of this module decides instead: 50% instruction + 50% deepfake, RED at 40% or
more, AMBER from 15%, GREY below. Media the detector could not judge counts as no media.

No RED when the engine read no money demand. A judge pasted a genuine overdue-loan letter: no payee, no
instruction, `instruction=NONE`, and the card told a real customer to stop. "Verify the instruction, not just
the pixels" is the product's own sentence, so a verdict that stops a payment while the extractor read no instruction
and no payee contradicts it. When `instruction` is NONE and no payee account, IFSC or VPA was read, a RED pair
falls back to AMBER and the explanation says so, naming both rules. This guard may only ever make a verdict less
severe, never more: it is the last thing checked before a RED is returned and it has no other effect.

No payment wording when no payment was read. The verdict headline is the one string both surfaces show: the
officer's band prints it and the customer's card takes it verbatim. `HEADLINES[AMBER]` said "Verify before paying"
on every AMBER, including a benign re-KYC letter whose coverage sentence on the same screen said the engine found
no instruction about money, and the only thing keeping that wording off the customer's card was a card-side
override. `HEADLINES_NO_PAYMENT` now holds the neutral AMBER, `money_in_play` decides which table is used, and
`card.build_card` reads the same predicate for its own copy, so the band and the card cannot disagree.

The explanation is prose a person reads: the officer's band, `satyapan demo`, the CLI and the evidence pack all print
it. It therefore names a rule by its rulebook title, never by its id. The id stays the audit surface: `anchor_rule`,
`second_family` and every `signals[].rule_id` carry it verbatim into the case record and the signed pack.
"""
from __future__ import annotations

from functools import lru_cache

from . import POLICY_VERSION
from .models import (GOVT_DUES, GOVT_SENDERS, OFFICIAL_OWNERS, PAYMENT_INSTRUCTIONS, Claim, ClaimedOwner, Family,
                     Instruction, Issuer, Outcome, Severity, Signal, Verdict)
from .rulebook import load_rulebook

HEADLINES = {
    Outcome.RED: ("Stop and verify through the official channel", "रुकिए। आधिकारिक माध्यम से जाँच करें"),
    Outcome.AMBER: ("Verify before paying", "भुगतान से पहले पुष्टि करें"),
    Outcome.GREY: ("Could not confirm. Check via the official channel", "पुष्टि नहीं हो सकी। आधिकारिक माध्यम से जाँच करें"),
    Outcome.MATCHES: ("Matches our records", "हमारे रिकॉर्ड से मेल खाता है"),
}
# The same outcome, worded for a message that asked for no money. AMBER is the only headline that mentions paying:
# RED, GREY and MATCHES already say "verify", "could not confirm" and "matches our records", which hold either way.
# The wording is the one the card used to apply on its own, promoted to the verdict so both surfaces say it.
HEADLINES_NO_PAYMENT = {
    Outcome.AMBER: ("Confirm this message first", "पहले इस संदेश की पुष्टि करें"),
}

# What a family and an evidence key are, in words. The explanation used to print "F2, evidence: bank:outbound_log",
# which is a schema key, not a sentence. The codes stay in the signal rows the officer can expand.
FAMILY_WORDS = {Family.F1: "the issuer rulebook", Family.F2: "the bank's own records", Family.F3: "media forensics",
                Family.F4: "campaign memory", Family.F5: "bank context"}
EVIDENCE_WORDS = {
    "claim": "the message itself",
    "issuer:ed_portal": "ED's own verification service",
    "registry:suspect": "the I4C suspect registry",
    "bank:outbound_log": "the bank's outbound log",
    "bank:name_lookup": "the bank's beneficiary name look-up",
    "bank:ledger": "the bank's ledger",
    "bank:signature": "the bank's content signature",
    "bank:paused_payment": "the bank's record of the paused payment",
    "web:registry": "the domain registry's record of the website",
    "memory:template": "campaign memory",
    "flag": "the bank's own flag",
}


@lru_cache(maxsize=1)
def _shipped_titles() -> dict[str, str]:
    """Rule titles from the shipped rulebook, for prose only.

    A Signal carries its id, family, reason and citation but not the rule's title, and `fuse` is called by the
    pipeline with signals alone, so the title is read from the rulebook here. Callers that already hold a loaded
    book (a test, or an engine running on a copy of `data/`) can pass `titles=` instead.
    """
    try:
        return {rid: m.title for rid, m in load_rulebook().rules.items()}
    except Exception:       # a missing or unreadable book must never take the verdict down with it
        return {}


def _named(rule_id: str, titles: dict[str, str]) -> str:
    """A rule as a person reads it. Unknown ids (signals built outside the rulebook) fall back to the id itself,
    and `tests/test_no_rule_ids_in_prose.py` proves every shipped rule has a title, so no id can reach the prose.

    One shipped title already quotes a phrase (a “safe account”), so a title that carries a double quote is
    wrapped in single quotes instead of nesting the same mark twice.
    """
    title = titles.get(rule_id)
    if not title:
        return rule_id
    return f"‘{title}’" if "“" in title or "”" in title or '"' in title else f"“{title}”"


def _evidence_words(key: str) -> str:
    return EVIDENCE_WORDS.get(key, key.replace(":", " ").replace("_", " "))


def _can_second(s: Signal) -> bool:
    return s.family != Family.F5 and s.detail.get("can_be_second", True) and s.severity in (Severity.HARD, Severity.SOFT)


def _join(parts: list[str]) -> str:
    """'a', 'a and b', 'a, b and c' — the way the officer would read it out."""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _quoted(span) -> str:
    """The words the extractor matched on, so the officer can catch it reading something that is not there.

    The adversarial pass found the extractor taking INVEST_FOR_RETURNS out of "RBI does not give any such financial
    investment advice" — a negation. Showing the matched words does not fix the extractor, but it stops the band
    asserting an instruction the officer cannot find in the message in front of her.
    """
    if span is None or not getattr(span, "text", ""):
        return ""
    text = " ".join(span.text.split())
    if len(text) > 40:
        text = text[:37].rstrip() + "…"
    return f" (read from “{text}”)"


def _what_was_read(claim: Claim) -> list[str]:
    """What the extractor actually took out of the message, in the officer's words.

    Only facts the claim itself carries: no inference, no severity, no judgement. This is what makes a GREY
    honest — it names what was seen, quotes the words it rests on, and then says what could and could not check it.
    """
    read: list[str] = []
    if claim.claimed_issuer != Issuer.NONE:
        read.append(f"a message claiming to be from {claim.claimed_issuer.value.replace('_', ' ')}"
                    f"{_quoted(claim.issuer_span)}")
    if claim.instruction != Instruction.NONE:
        read.append(f"an instruction to {claim.instruction.value.replace('_', ' ').lower()}"
                    f"{_quoted(claim.instruction_span)}")
    if claim.payee.account or claim.payee.ifsc or claim.payee.vpa:
        read.append("a payee to send money to")
    if claim.pressure_cues:
        cues = _join(sorted(c.replace("_", " ") for c in claim.pressure_cues))
        read.append(f"pressure on the customer ({cues}), which never counts toward a verdict")
    return read


# Below this many characters of visible text, "too little content to check" is literally true. Above it, the
# sentence was a lie: a judge pasted a 350-character consumer-commission notice that names a Commission twice
# and the band said there was too little content, when what had actually happened is that a substantial message
# was read in full and nothing in it could be tied to a claim. The threshold is a plain length, not a word
# count, because an OCR'd Devanagari notice is the same amount of reading in fewer words.
_SUBSTANTIAL = 140


def _nothing_could_be_anchored(claim: Claim) -> str:
    """The GREY sentence for a message the extractor read and took nothing out of.

    Two different facts need two different sentences. A one-line or empty artefact really does carry too little
    to check. A full-page notice does not: it was read, all of it, and the honest answer is that nothing in it
    named a body as the SENDER, asked for money, or gave a payee - and that a body Satyapan holds no rule for
    reads exactly like no body at all, which is a limit of the engine and not a finding about the message.
    """
    body = " ".join(claim.text.split())
    if len(body) < _SUBSTANTIAL:
        return "Too little content to check: no authority claimed and no instruction found."
    return (f"All {len(body)} characters of this message were read and nothing in them could be tied to a claim: "
            "nothing names a body as the sender of the message, nothing asks for money, and there is no payee "
            "account, IFSC or UPI ID. A body Satyapan holds no rule for reads here exactly like no body at all, "
            "so this says where its checks stop and nothing about the message.")


def _read_a_money_demand(claim: Claim) -> bool:
    """Did the engine read anything about money out of this message? The gate on RED.

    True when the extractor read a payment instruction, or a payee to send money to (an account, an IFSC or a VPA).
    `PAYMENT_INSTRUCTIONS` is every Instruction except NONE today, so this is the plain test "the instruction is
    not NONE", written as the thing it means so that adding a non-payment instruction later cannot silently
    license a RED.

    Deliberately narrower than `money_in_play`, which also counts a claimed payee owner with no account behind it.
    That one chooses customer-facing wording and may be generous; this one gates a verdict and may not. The two
    stay separate functions on purpose, so widening the copy predicate can never widen the licence for a RED.
    """
    if claim.instruction in PAYMENT_INSTRUCTIONS:
        return True
    p = claim.payee
    return bool(p.account or p.ifsc or p.vpa)


def money_in_play(claim: Claim) -> bool:
    """Is money anywhere in this message at all? The COPY predicate, read by the band and by the card.

    True when the extractor read a payment instruction, or a payee: an account, an IFSC, a UPI id, or a statement
    of whose account the money is to go to. The last of those is why this is wider than `_read_a_money_demand`:
    "deposit it into the RBI account" with no number read is not a payee a verdict may rest on, but it is a
    message about money, and copy that refuses to say so reads as evasion.

    One function, used by two surfaces. `fuse` picks the headline with it; `card.build_card` picks the stop line,
    the single instruction and the coaching line with it. They used to decide separately, and on a benign re-KYC
    letter the officer's band said "Verify before paying" while the card said "Confirm this message first" and the
    coverage sentence between them said no instruction about money had been read.
    """
    if claim.instruction in PAYMENT_INSTRUCTIONS:
        return True
    p = claim.payee
    return bool(p.account or p.ifsc or p.vpa) or p.claimed_owner != ClaimedOwner.UNKNOWN


def _bank_record_could_check(claim: Claim) -> bool:
    """Is there anything in the bank's own records that could be checked against this message?

    The F2 rules each need a door into a bank record: the outbound log and the RM directory open on a message that
    claims to be the bank, the beneficiary name look-up on an account the message says belongs to an authority, the
    ledger on a message that says money was credited by mistake. With none of those, "no bank record could check
    it" is the plain truth; with one of them, the records ran and found nothing, which is a different sentence.
    """
    if claim.claimed_issuer == Issuer.BANK_SELF:
        return True
    if claim.payee.claimed_owner in OFFICIAL_OWNERS and claim.payee.account is not None:
        return True
    # an account in a message in a government body's name, or asking for a government due (R-PAYEE-NOT-SENDER)
    if claim.payee.account is not None and (claim.claimed_issuer in GOVT_SENDERS or claim.instruction in GOVT_DUES):
        return True
    return claim.instruction == Instruction.RETURN_EXCESS_CREDIT


def _why_nothing_fired(claim: Claim) -> str:
    """One clause saying WHY nothing fired, read off the claim rather than written per scenario.

    "We saw a payee and an arrest threat and nothing fired" is an admission. The rules key on a pair (which
    authority the message claims to be, what it asks you to do), so the usual answer is that one half of that pair
    was never read out of the message. When both halves were read, the answer is that the pair alone is not a rule
    (every rule needs a payee, a document id or a bank record as well) plus whatever the bank's records could do.

    What this must never say is which rules exist. The real-RBI-advisory control reads as RBI plus an investment
    instruction, and the rulebook does carry a rule for that pair; it did not fire because it also needs a payee or
    a promise of returns. "The rulebook has no rule for this" would have been a new false sentence on the band.
    """
    no_issuer = claim.claimed_issuer == Issuer.NONE
    no_instruction = claim.instruction == Instruction.NONE
    short = "what was read was not enough for a rule to match"
    if no_issuer and no_instruction:
        return f"no authority and no instruction about money were read out of it, and {short}"
    if no_issuer:
        return f"no authority was read out of it, and {short}"
    if no_instruction:
        return f"no instruction about money was read out of it, and {short}"
    # Both halves of the pair were read, and the sentence before this one has just named them, so the gap is
    # elsewhere: no rule matched on the pair alone (each one needs more, or none covers that pair), and either the
    # bank had no record to check against or the records it could check found nothing.
    pair = "the authority and the instruction it read are not enough for a rule on their own"
    # The outbound log and the ledger always answer, so "found nothing wrong" is true of them. The name look-up may
    # not hold the account at all (status UNKNOWN), and any account a judge types is one it does not hold, so for
    # the account door the sentence says only what is true either way.
    if claim.claimed_issuer == Issuer.BANK_SELF or claim.instruction == Instruction.RETURN_EXCESS_CREDIT:
        return pair + ", and the bank's own records found nothing wrong"
    if _bank_record_could_check(claim):
        return pair + ", and the bank's name look-up raised nothing about this account"
    return pair + ", and the bank has no record that could check it"


def _what_ran(claim: Claim, signals: list[Signal], titles: dict[str, str], *, explain: bool = True,
              media_counts: bool = False) -> str:
    """What actually fired on a GREY, so the band never claims "no rule fired" over a rule that did.

    A GREY can still carry signals: `R-ED-FOUND` is an F1 informational match saying ED's own system recognised
    the summons. Nothing informational moves a verdict, but saying nothing ran while the panel below lists one is
    the contradiction this whole change exists to remove. F5 is context and never counts, so it stays out.
    """
    # A media check that found nothing or abstained is not a rule that fired: its rule title ("Signs of face
    # manipulation") reads like a finding. Name such checks by what they did instead.
    # A flagged media check is not listed here either: with judged media the combined score decides, and fuse() says
    # "The media shows ..." itself. Listed here it read "Nothing there is strong enough to move the verdict" next to
    # the AMBER or RED that check had just produced.
    quiet_media = [s for s in signals if s.family == Family.F3 and s.severity in (Severity.ABSTAIN, Severity.INFO)]
    flagged_media = {s.evidence_key for s in signals if s.family == Family.F3 and s not in quiet_media}
    fired = sorted({s.rule_id for s in signals if s.family not in (Family.F5, Family.F3)})
    media = _media_checks(quiet_media, flagged_media)
    if not fired:
        # The why-clause now carries what "nothing to corroborate" used to say, and this sentence is set on the
        # verdict band where every extra line costs. One idea, once.
        why = f", because {_why_nothing_fired(claim)}" if explain else ". There is nothing to corroborate it either way"
        return f"No rule fired on it{why}.{media}"
    if media_counts:
        # quoted after "Instruction checks:" in a verdict the combined score made, so it speaks for the message only
        return (f"What did run on the message: {_join([_named(r, titles) for r in fired])}. On its own that is not "
                f"enough for a warning.{media}")
    return (f"What did run: {_join([_named(r, titles) for r in fired])}. Nothing there is strong enough to move the "
            f"verdict, so there is nothing to corroborate either way.{media}")


MEDIA_CHECK_WORDS = {"media:video": "the face check", "media:audio": "the voice check", "media:document": "the document check"}


def _media_checks(quiet: list[Signal], flagged: set[str] = frozenset()) -> str:
    """' Media checks: the face check found no signs and the voice check abstained.' A check that found no signs counts
    0% in the combined score; one that abstained is not counted, and when every check abstained the sentence says so.

    With two files of the same kind each result is named, and a quiet one beside a flagged one of the same kind is
    "another" check: "The media shows signs of synthetic speech ... the voice check found no signs" read as one voice
    check saying both things (bug hunt raw finding 32)."""
    parts: list[str] = []
    seen: dict[str, int] = {}
    for s in quiet:
        what = MEDIA_CHECK_WORDS.get(s.evidence_key, "a media check")
        did = "found no signs" if (s.detail or {}).get("status") == "clean" else "abstained"
        n = seen.get(what, 0) + (1 if s.evidence_key in flagged else 0)
        seen[what] = seen.get(what, 0) + 1
        label = what if n == 0 else what.replace("the ", "another ", 1)
        part = f"{label} {did}"
        if part not in parts:
            parts.append(part)
    if not parts:
        return ""
    judged = any((s.detail or {}).get("status") == "clean" for s in quiet)
    return f" Media checks: {_join(parts)}{'' if judged else '; a check that is unsure is not counted'}."


def _fuse_rules(claim: Claim, signals: list[Signal], names: dict[str, str], shown: list[Signal], *,
                media_counts: bool = False) -> Verdict:
    """The instruction checks' own verdict: `signals` holds every family except F3 (media), and `shown` is the full
    list the verdict carries, so a GREY still names a detector that ran and abstained. `media_counts` is set when judged
    media will count half: the sentences then speak for the message alone, because fuse() quotes them after
    "Instruction checks:" in a verdict the media may have moved."""
    hard = [s for s in signals if s.severity == Severity.HARD and s.citation_verified]
    soft = [s for s in signals if s.severity == Severity.SOFT]
    match = [s for s in signals if s.severity == Severity.MATCH]

    # Nothing in the message was about money, so no headline this call returns may mention paying. The one
    # explanation that still has to is the capped AMBER, which says so as an absence ("nothing asked for money").
    neutral = not money_in_play(claim)

    def verdict(outcome: Outcome, explanation: str, anchor: str | None = None, second: str | None = None,
                *, payment_neutral: bool = False, no_money_cap: bool = False) -> Verdict:
        en, hi = HEADLINES[outcome]
        if neutral or payment_neutral:
            en, hi = HEADLINES_NO_PAYMENT.get(outcome, (en, hi))
        return Verdict(outcome=outcome, headline_en=en, headline_hi=hi, anchor_rule=anchor, second_family=second,
                       explanation=explanation, policy_version=POLICY_VERSION, signals=shown, no_money_cap=no_money_cap)

    if match and not hard:
        return verdict(Outcome.MATCHES, "The message carries the bank's own signature and is in its outbound log. "
                       "Still remind the customer: we never ask you to move money to another account.")

    if hard:
        for h in hard:
            for s in signals:
                if s is h or not _can_second(s):
                    continue
                if s.family != h.family and s.evidence_key != h.evidence_key:
                    pair = (f"{_named(h.rule_id, names)} ({FAMILY_WORDS[h.family]}, from {_evidence_words(h.evidence_key)}) "
                            f"plus an independent {_named(s.rule_id, names)} ({FAMILY_WORDS[s.family]}, from "
                            f"{_evidence_words(s.evidence_key)})")
                    if not _read_a_money_demand(claim):
                        # Two families agree about this message, but nothing in it asked for money. A RED tells a
                        # customer to stop a payment, and there is no payment here to stop, so the verdict is
                        # capped at AMBER. `second_family` stays empty because nothing made this a RED.
                        #
                        # `payment_neutral` is forced rather than left to `money_in_play`, because this branch's
                        # own sentence says nothing asked for money. A claimed payee owner with no account behind
                        # it ("deposit it into the RBI account") passes `money_in_play` and fails the RED gate, so
                        # without this the band would print "Verify before paying" directly above an explanation
                        # saying no payment was read. The headline is quoted from the table it comes from, so the
                        # sentence cannot drift away from the words actually on the band.
                        stops_at = HEADLINES_NO_PAYMENT[Outcome.AMBER][0].lower()
                        return verdict(Outcome.AMBER, f"{pair}. Nothing in this message asked for money, though: no "
                                       "instruction to pay and no payee account, IFSC or UPI ID were read out of it. "
                                       "Satyapan verifies the instruction, so with no instruction to verify this stops "
                                       f"at “{stops_at}”.", anchor=h.rule_id, payment_neutral=True,
                                       no_money_cap=True)   # the band must not say "one hard rule fired" here
                    return verdict(Outcome.RED, pair + ".", anchor=h.rule_id, second=s.rule_id)
        h = hard[0]
        if media_counts:
            return verdict(Outcome.AMBER, f"{_named(h.rule_id, names)} fired, and no independent check on the message "
                           "confirmed it.", anchor=h.rule_id)
        return verdict(Outcome.AMBER, f"{_named(h.rule_id, names)} fired but no independent signal from another family "
                       "confirmed it. One rule alone never gives RED.", anchor=h.rule_id)

    independent = {(s.family, s.evidence_key) for s in soft if _can_second(s)}
    if len(independent) >= 2:
        # name only the signals that counted toward independence, not context cues that never count
        counted = sorted({s.rule_id for s in soft if _can_second(s)})
        return verdict(Outcome.AMBER, "Two or more independent soft signals: "
                       + ", ".join(_named(r, names) for r in counted) + ".")
    if any(s.escalate_alone for s in soft):
        s = next(s for s in soft if s.escalate_alone)
        # Same sentence, aimed at what she was actually asked to do. This branch is where the benign no-money
        # AMBERs land (a one-hour-old ED summons, a court hearing notice), so "verify before paying" here was the
        # band contradicting its own coverage sentence as plainly as the headline above it did.
        if neutral:
            return verdict(Outcome.AMBER, f"{_named(s.rule_id, names)} means the customer should confirm this "
                           "message before acting on it.")
        return verdict(Outcome.AMBER, f"{_named(s.rule_id, names)} means the customer should verify before paying.")

    # GREY says what kind of GREY this is, because "no warning signs" is a lie whenever the extractor did read an
    # authority, an instruction, a payee or a pressure cue out of the message and nothing could check it. A judge
    # pasting a leetspeak arrest threat that the patterns miss must not be told the message looks clean.
    read = _what_was_read(claim)
    never_safe = "This is not a confirmation that the message is safe."
    if read:
        ran = _what_ran(claim, shown, names, media_counts=media_counts)
        return verdict(Outcome.GREY, f"Read from the message: {_join(read)}. {ran} {never_safe}")
    if not claim.has_content():
        # this branch already says why nothing matched, so the clause would only repeat it
        ran = _what_ran(claim, shown, names, explain=False, media_counts=media_counts)
        return verdict(Outcome.GREY, f"{_nothing_could_be_anchored(claim)} {ran} {never_safe}")
    ran = _what_ran(claim, shown, names, media_counts=media_counts)
    return verdict(Outcome.GREY, f"Nothing was read out of this message. {ran} {never_safe}")


# ---------------------------------------------------------------- the combined score (Bhawna, 24 Oct 2026)
#
# Lane 1 has two tests: the instruction checks (Comparisons 1-4) and the deepfake check on the media (voice, the sound
# of a video, a document). With no media, or none the detector could judge, the instruction checks decide alone,
# exactly as above. With judged media the two count half each, and 40% or more is RED.
#
# Instruction %: what the instruction checks found, on the same ladder `_fuse_rules` climbs.
# Deepfake %: the calibrated result (forensics.to_signal sets it), never the raw model number: the 500M voice model
# gives many real Hindi voices a raw 0.99, so a raw number would make real voices look fake.

INSTRUCTION_WEIGHT = 0.5
RED_LINE_PCT = 40
AMBER_LINE_PCT = 15
DEEPFAKE_PCT_BY_BAND = {"high": 100, "moderate": 70, "low": 30}
MATCHES_OVERRIDE_PCT = 70     # the bank's own signed message stays MATCHES unless the media is at least this fake


def deepfake_pct(s: Signal) -> int | None:
    """How fake the media looks, 0-100, or None when the detector could not judge it (unsure, too short, blurry,
    not calibrated): an unjudged file counts as no media at all."""
    if s.family != Family.F3:
        return None
    if s.detail.get("deepfake_pct") is not None:
        return int(s.detail["deepfake_pct"])
    if s.severity in (Severity.HARD, Severity.SOFT):
        band = str(s.detail.get("band", "")).split(" ")[0]
        return DEEPFAKE_PCT_BY_BAND.get(band, DEEPFAKE_PCT_BY_BAND["moderate"])
    return 0 if s.detail.get("status") == "clean" else None


def instruction_pct(rules: list[Signal]) -> int:
    """What the instruction checks found, 0-100. A RED pair is 90, so on its own it already reaches the RED line
    (Bhawna's example: 80% instruction, 0% deepfake, 40% combined, RED). A rule whose citation is not verified
    counts 0, so it can never help the combined score to a RED either (docs/finale-qa.md, Q6)."""
    rules = [s for s in rules if s.citation_verified]
    hard = [s for s in rules if s.severity == Severity.HARD and s.citation_verified]
    soft = [s for s in rules if s.severity == Severity.SOFT]
    for h in hard:
        if any(s is not h and _can_second(s) and s.family != h.family and s.evidence_key != h.evidence_key for s in rules):
            return 90
    if hard:
        return 70
    if len({(s.family, s.evidence_key) for s in soft if _can_second(s)}) >= 2 or any(s.escalate_alone for s in soft):
        return 50
    return 20 if any(s.family != Family.F5 for s in soft) else 0


def fuse(claim: Claim, signals: list[Signal], *, titles: dict[str, str] | None = None) -> Verdict:
    names = _shipped_titles() if titles is None else titles
    rules = [s for s in signals if s.family != Family.F3]
    judged = [(p, s) for s in signals if (p := deepfake_pct(s)) is not None]
    base = _fuse_rules(claim, rules, names, signals, media_counts=bool(judged))
    if not judged:
        return base
    d, media = max(judged, key=lambda x: x[0])
    i = instruction_pct(rules)
    c = INSTRUCTION_WEIGHT * i + (1 - INSTRUCTION_WEIGHT) * d
    # deepfake_simulated: the rehearsal scenarios script their media result (SimulatedForensics), and the band must say
    # so next to the number, as every other place that shows a scripted result does
    scores = {"instruction_pct": i, "deepfake_pct": d, "combined_pct": round(c, 1),
              "red_line_pct": RED_LINE_PCT, "amber_line_pct": AMBER_LINE_PCT,
              "deepfake_simulated": bool((media.detail or {}).get("simulated"))}
    head = f"Instruction checks {i}%, deepfake check {d}%, half each: combined {c:g}%"
    found = (f"The media shows {_named(media.rule_id, names)}." if d > 0
             else "The media was checked and shows no signs of a deepfake.")

    def out(outcome: Outcome, line: str, anchor: str | None, second: str | None, *, payment_neutral: bool = False,
            explanation: str | None = None) -> Verdict:
        en, hi = HEADLINES[outcome]
        if payment_neutral or not money_in_play(claim):
            en, hi = HEADLINES_NO_PAYMENT.get(outcome, (en, hi))
        text = explanation or f"{head}, {line}. {found} Instruction checks: {base.explanation}"
        return Verdict(outcome=outcome, headline_en=en, headline_hi=hi, anchor_rule=anchor, second_family=second,
                       explanation=text, policy_version=POLICY_VERSION, signals=signals, scores=scores)

    if base.outcome == Outcome.MATCHES:
        if d < MATCHES_OVERRIDE_PCT:
            return out(Outcome.MATCHES, "", None, None, explanation=f"{base.explanation} {found} ({head}.)")
        return out(Outcome.AMBER, "", media.rule_id, None, explanation=(
            f"The message matches the bank's own records, but {found[0].lower() + found[1:]} Confirm with the customer "
            f"how the media reached them before acting. ({head}.)"))
    if c >= RED_LINE_PCT:
        anchor = base.anchor_rule or media.rule_id
        second = base.second_family if base.outcome == Outcome.RED else (media.rule_id if anchor != media.rule_id else None)
        if not _read_a_money_demand(claim):
            # the same guard as the RED pair above: no payment was read, so there is no payment to stop
            return out(Outcome.AMBER, f"at or above the {RED_LINE_PCT}% line for RED, but nothing in this message "
                       "asked for money, so this stops at AMBER", anchor, None, payment_neutral=True)
        return out(Outcome.RED, f"at or above the {RED_LINE_PCT}% line for RED", anchor, second)
    if c >= AMBER_LINE_PCT:
        return out(Outcome.AMBER, f"between the {AMBER_LINE_PCT}% and {RED_LINE_PCT}% lines", base.anchor_rule, None)
    return out(Outcome.GREY, f"below the {AMBER_LINE_PCT}% line", None, None)
