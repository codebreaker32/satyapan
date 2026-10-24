"""Rule logic for F1 (issuer rulebook) and F2 (bank-truth provenance).

Each function returns a detail dict when the rule fires. `evidence_key` says what the signal rests on:
- "claim": the extracted claim text itself (every F1 rule that only reads the message)
- "issuer:ed_portal": a lookup on ED's verification service
- "registry:suspect": the I4C suspect registry
- "bank:outbound_log" / "bank:name_lookup" / "bank:ledger" / "bank:signature": the bank's own records
Two signals on the same key never count as two independent families (see fusion.py).
"""
from __future__ import annotations

import re

from .models import (GOVT_DUES, GOVT_SENDERS, LAW_ENFORCEMENT, OPEN_SET_AUTHORITY, OFFICIAL_OWNERS, PAYMENT_INSTRUCTIONS,
                     Channel, Claim, ClaimedOwner, Instruction, Issuer)
from .rulebook import RuleContext, rule

ISSUER_EN = {
    Issuer.ED: "the Enforcement Directorate (ED)", Issuer.CBI: "the CBI", Issuer.POLICE: "the police", Issuer.COURT: "a court",
    Issuer.RBI: "RBI", Issuer.SEBI: "SEBI", Issuer.CUSTOMS: "Customs", Issuer.TRAI_DOT: "TRAI / the telecom department",
    Issuer.TRANSPORT: "the traffic police or transport department", Issuer.MUNICIPAL: "the municipal corporation",
    # OTHER is the open-set body: a state authority the message names and the enum has no row for. The label is
    # generic on purpose. The body's own name is attacker-controlled text, and the one place it is allowed is the
    # verbatim span the officer reads beside the message, never a sentence read aloud to a customer.
    Issuer.BANK_SELF: "your bank", Issuer.OTHER: "a government body", Issuer.NONE: "an authority",
}
ISSUER_HI = {
    Issuer.ED: "प्रवर्तन निदेशालय (ED)", Issuer.CBI: "सीबीआई", Issuer.POLICE: "पुलिस", Issuer.COURT: "अदालत", Issuer.RBI: "RBI",
    Issuer.SEBI: "SEBI", Issuer.CUSTOMS: "कस्टम विभाग", Issuer.TRAI_DOT: "ट्राई / दूरसंचार विभाग",
    Issuer.TRANSPORT: "यातायात पुलिस या परिवहन विभाग", Issuer.MUNICIPAL: "नगर निगम", Issuer.BANK_SELF: "आपका बैंक",
    Issuer.OTHER: "कोई सरकारी संस्था", Issuer.NONE: "कोई सरकारी संस्था",
}
INSTR_EN = {
    Instruction.TRANSFER_TO_ACCOUNT: "a transfer to an account", Instruction.MOVE_FD: "moving your FD or savings",
    Instruction.INVEST_FOR_RETURNS: "an investment", Instruction.RETURN_EXCESS_CREDIT: "returning money",
    Instruction.PAY_FEE_TO_VERIFY: "a fee to verify or release funds", Instruction.PAY_CHALLAN: "paying a traffic challan",
    Instruction.PAY_LOCAL_TAX: "paying property or house tax", Instruction.NONE: "a payment",
}
INSTR_HI = {
    Instruction.TRANSFER_TO_ACCOUNT: "किसी खाते में पैसे भेजने को", Instruction.MOVE_FD: "FD तोड़कर पैसा भेजने को",
    Instruction.INVEST_FOR_RETURNS: "निवेश करने को", Instruction.RETURN_EXCESS_CREDIT: "पैसे वापस भेजने को",
    Instruction.PAY_FEE_TO_VERIFY: "सत्यापन शुल्क देने को", Instruction.PAY_CHALLAN: "ट्रैफ़िक चालान भरने को",
    Instruction.PAY_LOCAL_TAX: "प्रॉपर्टी या हाउस टैक्स भरने को", Instruction.NONE: "पैसे देने को",
}
OWNER_EN = {ClaimedOwner.RBI: "RBI", ClaimedOwner.GOVT: "the government", ClaimedOwner.COURT: "a court", ClaimedOwner.AGENCY: "a government agency", ClaimedOwner.BANK: "the bank"}
OWNER_HI = {ClaimedOwner.RBI: "RBI", ClaimedOwner.GOVT: "सरकार", ClaimedOwner.COURT: "अदालत", ClaimedOwner.AGENCY: "सरकारी एजेंसी", ClaimedOwner.BANK: "बैंक"}
HOLDER_EN = {"PRIVATE_FIRM": "a private firm", "INDIVIDUAL": "an individual", "GOVT": "a government body", "BANK": "a bank", "UNKNOWN": "unknown"}
HOLDER_HI = {"PRIVATE_FIRM": "एक निजी फ़र्म", "INDIVIDUAL": "एक व्यक्ति", "GOVT": "एक सरकारी संस्था", "BANK": "एक बैंक", "UNKNOWN": "अज्ञात"}
CUE_EN = {"arrest_threat": "a threat of arrest", "secrecy": "a demand for secrecy", "urgency": "urgency", "isolation": "keeping you on the call", "guaranteed_returns": "a promise of guaranteed returns"}
CUE_HI = {"arrest_threat": "गिरफ्तारी की धमकी", "secrecy": "गोपनीयता की माँग", "urgency": "जल्दबाज़ी", "isolation": "कॉल पर बने रहने का दबाव", "guaranteed_returns": "पक्के मुनाफ़े का वादा"}

REMOTE_CHANNELS = {Channel.WHATSAPP, Channel.VIDEO_CALL, Channel.PHONE_CALL}
# A call, as opposed to something that merely arrived with a number attached. See `_call_number`.
CALL_CHANNELS = {Channel.PHONE_CALL, Channel.VIDEO_CALL}
# Artefacts that can carry a call at all. A transcript is the recording of one; the officer's picklist is her
# own statement of what the customer was told on one. A pasted SMS and an OCR'd letter are neither, however
# often the word "call" appears in their text. See `_call_number`.
CALL_ARTEFACTS = {"transcript", "officer_picklist"}
# Who the 1600xx series is a fact ABOUT. RBI/2024-25/105 directs banks and other regulated entities to place
# their transactional and service calls from 1600xx. A REGULATOR is not one of them: RBI and SEBI do not place
# service calls to bank customers at all, so "banks and financial firms place service calls only from numbers
# starting 1600, and this one did not" is not a sentence about a message claiming to be RBI. A judge got that
# sentence on a customer card about a pasted "RBI ALERT" SMS on 18 Oct.
SERVICE_CALL_ISSUERS = {Issuer.BANK_SELF}


def _pays(claim: Claim) -> bool:
    return claim.instruction in PAYMENT_INSTRUCTIONS


# ---------------- F1 ----------------

@rule("R-AGENCY-PAY")
def agency_pay(claim: Claim, ctx: RuleContext):
    """A body the message names as a state authority is demanding a payment.

    Scoped to LAW_ENFORCEMENT, which is the half of CLAIMED_STATE_AUTHORITY whose members the message names in
    so many words, so "this message claims to be X" is a statement of fact we can point at a span for. The
    open-set half goes to `state_name_pay` below with a sentence that claims less. The partition and the reason
    it exists are written out at CLAIMED_STATE_AUTHORITY in models.py.
    """
    if claim.claimed_issuer in LAW_ENFORCEMENT and _pays(claim):
        # A traffic challan is the one money demand the police really do send by message, so "no government agency
        # demands money" is false about it. The challan has its own rule (R-CHALLAN-OFFICIAL) and the payee rules
        # still run; only this sentence stands down, and only for the police. "CBI says pay this challan" is not a
        # thing the CBI sends, and it keeps this rule. Neither does a "fine" that threatens arrest: a traffic
        # challan does not, and a digital-arrest script that says "pay the fine or be arrested" stays one.
        if (claim.claimed_issuer == Issuer.POLICE and claim.instruction == Instruction.PAY_CHALLAN
                and "arrest_threat" not in claim.pressure_cues):
            return None
        return {"evidence_key": "claim", "issuer_en": ISSUER_EN[claim.claimed_issuer], "issuer_hi": ISSUER_HI[claim.claimed_issuer],
                "instruction_en": INSTR_EN[claim.instruction], "instruction_hi": INSTR_HI[claim.instruction]}
    return None


@rule("R-STATE-NAME-PAY")
def state_name_pay(claim: Claim, ctx: RuleContext):
    """A government-sounding name the enum has no row for is demanding a payment.

    The same legal fact as R-AGENCY-PAY, said about the only thing the open-set net actually read. What the net
    reads is a NAME's form — multi-word, capitalised, headed by a state head noun, carrying a state-vocabulary
    marker and not calling itself a company — and that form is shared by bodies that are nothing to do with the
    state: "Credit Information Bureau (India) Limited", "Claims Investigation Department" on an insurer's
    letterhead, "Acme Recovery and Fraud Investigation Unit". The corporate-suffix gate in `extract` takes the
    first two and cannot take the third, because a private firm is free to name its unit anything.

    So this rule never says the sender claims to be the state. It says a government-sounding name was read, a
    payment was asked for, and we could not confirm who sent the message — three things that are true of the
    forged notice and of the private firm alike, and that leave the officer and the customer to do the
    confirming. The body's own name stays where it has always belonged: in the quoted span beside the message,
    never in prose read aloud to a customer.

    No detail carries the name. `issuer_en`/`issuer_hi` are deliberately absent from the template.
    """
    if claim.claimed_issuer in OPEN_SET_AUTHORITY and _pays(claim):
        return {"evidence_key": "claim",
                "instruction_en": INSTR_EN[claim.instruction], "instruction_hi": INSTR_HI[claim.instruction]}
    return None


@rule("R-COURT-PAY")
def court_pay(claim: Claim, ctx: RuleContext):
    if claim.claimed_issuer == Issuer.COURT and _pays(claim):
        return {"evidence_key": "claim"}
    return None


def _ed_doc(claim: Claim) -> bool:
    return claim.claimed_issuer == Issuer.ED and (claim.mentions_summons or claim.document_ids.summons_no is not None)


@rule("R-ED-NO-PASSCODE")
def ed_no_passcode(claim: Claim, ctx: RuleContext):
    if _ed_doc(claim) and claim.document_ids.passcode is None:
        return {"evidence_key": "claim", "summons_no": claim.document_ids.summons_no.value if claim.document_ids.summons_no else "—"}
    return None


def _ed_lookup(claim: Claim, ctx: RuleContext):
    if not _ed_doc(claim) or claim.document_ids.passcode is None or claim.document_ids.summons_no is None:
        return None
    issue = claim.document_ids.issue_date.value if claim.document_ids.issue_date else None
    return ctx.adapters.ed_verify.verify(claim.document_ids.summons_no.value, claim.document_ids.passcode.value, issue, ctx.now)


@rule("R-ED-SUMMONS-NOTFOUND")
def ed_not_found(claim: Claim, ctx: RuleContext):
    res = _ed_lookup(claim, ctx)
    if res and res["status"] == "NOT_FOUND":
        return {"evidence_key": "issuer:ed_portal", "summons_no": claim.document_ids.summons_no.value, "lookup": res}
    return None


@rule("R-ED-WINDOW")
def ed_window(claim: Claim, ctx: RuleContext):
    res = _ed_lookup(claim, ctx)
    if res and res["status"] in ("NOT_YET", "EXPIRED"):
        return {"evidence_key": "issuer:ed_portal", "summons_no": claim.document_ids.summons_no.value, "lookup": res}
    return None


@rule("R-ED-FOUND")
def ed_found(claim: Claim, ctx: RuleContext):
    res = _ed_lookup(claim, ctx)
    if res and res["status"] == "FOUND":
        return {"evidence_key": "issuer:ed_portal", "summons_no": claim.document_ids.summons_no.value, "lookup": res}
    return None


@rule("R-ED-CHANNEL")
def ed_channel(claim: Claim, ctx: RuleContext):
    if claim.claimed_issuer == Issuer.ED and claim.channel in REMOTE_CHANNELS and _pays(claim):
        return {"evidence_key": "claim", "channel": claim.channel.value}
    return None


@rule("R-RBI-INV")
def rbi_inv(claim: Claim, ctx: RuleContext):
    # A real RBI advisory may mention "investment"; the rule needs a payee or a returns promise as well,
    # so genuine RBI text about investment scams does not fire it.
    if claim.claimed_issuer == Issuer.RBI and claim.instruction == Instruction.INVEST_FOR_RETURNS:
        has_payee = any([claim.payee.account, claim.payee.vpa])
        if has_payee or "guaranteed_returns" in claim.pressure_cues:
            return {"evidence_key": "claim"}
    return None


@rule("R-SEBI-VALID")
def sebi_valid(claim: Claim, ctx: RuleContext):
    if claim.instruction == Instruction.INVEST_FOR_RETURNS and claim.payee.vpa and not claim.payee.vpa.value.lower().endswith("@valid"):
        return {"evidence_key": "claim", "vpa": claim.payee.vpa.value}
    return None


def _call_number(claim: Claim, ctx: RuleContext) -> str | None:
    """The number a financial caller reached the customer from, or None when this artefact carries no call.

    The 1600xx series is a fact about calls a bank places (RBI/2024-25/105), so the rule may only be stated about
    an artefact that carries a call. It used to fire on anything with a number attached: a judge pasted a bank
    letter with no call in it, got "Financial call not from the 1600 series" on the customer card, and that
    sentence was one of the two families that made the verdict RED. The reason asserted a channel fact the input
    did not contain.

    `claim.caller_number` alone is not enough to say a call happened: the extractor sets it from the first phone
    number in the text, and a helpline printed at the foot of a letter is not a caller. Pass 5 made the gate the
    CHANNEL, which closed the letter but left a wider path open, and a judge walked straight down it on 18 Oct:
    a pasted "RBI ALERT" SMS reading "For any query call our helpline +911122601000" sets the channel to
    PHONE_CALL off the word "call", and the customer card then read "This call came from +911122601000". There
    was no call. The channel read out of a pasted message is a fact about what the message DESCRIBES; it is not
    a fact about the artefact in front of the officer.

    So the gate is both: the ARTEFACT has to be one that can carry a call (a transcript, or the officer's own
    picklist), and the CHANNEL has to say the call is a call rather than a voice note. The cost is recall: a
    scam-call script pasted into the text box as plain text no longer fires this rule, and the officer has to
    say it was a call - by uploading the recording or by ticking the channel in claim-only mode. That is the
    right side to err on for a rule whose reason names the channel out loud to a customer.
    """
    if claim.source not in CALL_ARTEFACTS:
        return None
    if claim.channel not in CALL_CHANNELS:
        return None
    return claim.caller_number.value if claim.caller_number else ctx.sender_number


@rule("R-CALLER-1600")
def caller_1600(claim: Claim, ctx: RuleContext):
    num = _call_number(claim, ctx)
    if claim.claimed_issuer in SERVICE_CALL_ISSUERS and num and not num.startswith("1600"):
        return {"evidence_key": "claim", "caller": num, "channel": claim.channel.value}
    return None


@rule("R-DOMAIN-BANKIN")
def domain_bankin(claim: Claim, ctx: RuleContext):
    # A bank sending its customer to a government portal (".gov.in", ".nic.in") is not a bank link at all: the
    # 23 Oct evaluation found a Demo Bank warning that named echallan.parivahan.gov.in flagged as a non-bank link.
    if claim.claimed_issuer == Issuer.BANK_SELF:
        for u in claim.urls:
            host = u.value.split("//")[-1].split("/")[0].lower()
            if not host.endswith((".bank.in", ".gov.in", ".nic.in")):
                return {"evidence_key": "claim", "url": u.value}
    return None


# Who a .gov.in link is expected from. RBI is left out on purpose: its own site is rbi.org.in, and the registry's
# guidelines keep banks and financial institutions off .gov.in, so the rule would fire on RBI's real address.
# .nic.in passes as well as .gov.in: it is NIC's own zone, and some civic portals live on it (mcdonline.nic.in).
GOVIN_SENDERS = GOVT_SENDERS - {Issuer.RBI}
GOVIN_SUFFIXES = (".gov.in", ".nic.in")
_PAY_WORD = re.compile(r"\bpay(?:ment|ing)?\b|भुगतान|\bjama\b|जमा|\bbhar\w{0,3}\b|भर", re.I)
_SENTENCE_MARKS = ".;!?।\n"


def _host(url: str) -> str:
    return url.split("//")[-1].split("/")[0].lower()


def _payment_route_off_site(claim: Claim, ctx: RuleContext) -> dict | None:
    """Where the message sends the payment, when that is somewhere other than a .gov.in or .nic.in site.

    Three routes, read off the message itself: a link that is not on those domains, an account or a UPI ID to pay
    into, or a phone number in the same sentence as a word for paying ("for payment call 98..."). A helpline at the
    foot of a real challan SMS is not a route, which is why the number needs the payment word beside it. An account
    or UPI ID that the bank's own directory lists as a government collection account is not off the site either:
    the money it takes is the government's.
    """
    for u in claim.urls:
        if not _host(u.value).endswith(GOVIN_SUFFIXES):
            return {"route_kind": "link", "route": u.value}
    p = claim.payee
    if p.account or p.vpa:
        res = (ctx.adapters.name_lookup.lookup(p.account.value, p.ifsc.value if p.ifsc else None) if p.account
               else ctx.adapters.name_lookup.lookup_vpa(p.vpa.value))
        if not (res["allow_listed"] or res["holder_type"] == "GOVT"):
            g = p.account or p.vpa
            return {"route_kind": "account" if p.account else "UPI ID", "route": g.value}
    if claim.caller_number:
        sp = claim.caller_number.span
        lo = max([claim.text.rfind(c, 0, sp.start) for c in _SENTENCE_MARKS] + [-1]) + 1
        hi_ends = [i for i in (claim.text.find(c, sp.end) for c in _SENTENCE_MARKS) if i != -1]
        sentence = claim.text[lo:min(hi_ends) if hi_ends else len(claim.text)]
        if _PAY_WORD.search(sentence):
            return {"route_kind": "phone number", "route": claim.caller_number.value}
    return None


@rule("R-CHALLAN-OFFICIAL")
def challan_official(claim: Claim, ctx: RuleContext):
    """A traffic challan that asks to be paid somewhere other than the government's own site.

    The e-challan service's own notice says it never asks for payment details through calls, messages or links,
    and to use the portal only. So the rule fires when the message routes the payment elsewhere: a link off
    .gov.in, an account or UPI ID, or "call this number to pay". A real challan SMS that points at the official site
    does not fire it, which is what lets a swapped-link copy and its original come apart at all, since their words
    are the same. Soft and escalating alone: AMBER, never RED, on its own; a payment going to a private person
    (R-RECEIVER-NAME) or an account the look-up names (R-PAYEE-NOT-SENDER) is the independent half of a RED.
    The reason states the service's practice and never describes the message, so it needs no span. A message that
    claims to be the bank is left to the bank's own rules, since a bank may remind a customer that a challan is due.
    """
    if claim.instruction != Instruction.PAY_CHALLAN or claim.claimed_issuer == Issuer.BANK_SELF:
        return None
    route = _payment_route_off_site(claim, ctx)
    if route is None:
        return None
    return {"evidence_key": "claim", **route}


def _in_the_states_name(claim: Claim) -> bool:
    """Is the money in this message asked for in the name of the state?

    Either the message is in the name of a government body (GOVT_SENDERS), or it asks for a government due, which
    can only be owed to one. A message that claims to be the bank is out, and so is a private sender: their
    accounts are allowed to be private, and the checks below would accuse a firm of collecting its own money.
    """
    if claim.claimed_issuer == Issuer.BANK_SELF:
        return False
    return claim.claimed_issuer in GOVT_SENDERS or claim.instruction in GOVT_DUES


# Words that name each body in a domain registry's record of who holds a website. A real civic body on a domain off
# .gov.in (Kolkata Municipal Corporation holds kmcgov.in) is its own registrant, and the registry says so.
BODY_WORDS = {
    Issuer.MUNICIPAL: ("municipal", "nagar nigam", "nagar palika", "corporation of"),
    Issuer.TRANSPORT: ("transport", "traffic", "parivahan", "road transport"),
    Issuer.POLICE: ("police",), Issuer.COURT: ("court",), Issuer.CUSTOMS: ("customs", "indirect taxes"),
    Issuer.SEBI: ("securities and exchange board",), Issuer.ED: ("enforcement directorate", "directorate of enforcement"),
    Issuer.CBI: ("central bureau of investigation",), Issuer.TRAI_DOT: ("telecom",), Issuer.RBI: ("reserve bank of india",),
}
DUE_BODY = {Instruction.PAY_CHALLAN: Issuer.TRANSPORT, Instruction.PAY_LOCAL_TAX: Issuer.MUNICIPAL}


def _registry_record(host: str, ctx: RuleContext) -> dict:
    from .adapters import registrable_domain
    website = getattr(ctx.adapters, "website", None)
    return website.lookup(registrable_domain(host)) if website is not None else {"status": "UNKNOWN"}


def _held_by_the_body(claim: Claim, rec: dict) -> bool:
    """Does the registry name the body this message is in the name of as the website's holder?"""
    body = claim.claimed_issuer if claim.claimed_issuer in BODY_WORDS else DUE_BODY.get(claim.instruction)
    holder = str(rec.get("holder") or "").lower()
    return bool(body and holder and any(w in holder for w in BODY_WORDS[body]))


@rule("R-DOMAIN-GOVIN")
def domain_govin(claim: Claim, ctx: RuleContext):
    """A message in the name of a government body, or asking for a government due, links somewhere that is not on
    .gov.in. The government counterpart of R-DOMAIN-BANKIN and soft like it, and it never anchors. The sentence says
    only what the registry rules out (a .gov.in address is a government body's), never that the link is not the
    body's. A site off .gov.in whose registry record names the body itself as its holder is that body's own site
    (kmcgov.in is held by Kolkata Municipal Corporation), so it is not flagged."""
    if not _in_the_states_name(claim) or (claim.claimed_issuer not in GOVIN_SENDERS
                                          and claim.instruction not in GOVT_DUES):
        return None
    for u in claim.urls:
        host = _host(u.value)
        if not host.endswith(GOVIN_SUFFIXES) and not _held_by_the_body(claim, _registry_record(host, ctx)):
            return {"evidence_key": "claim", "url": u.value}
    return None


WEBSITE_YOUNG_DAYS = 365


def _age_words(days: int) -> tuple[str, str]:
    if days < 60:
        return (f"{days} days", f"{days} दिन")
    if days < 730:
        return (f"{days // 30} months", f"{days // 30} महीने")
    return (f"{days // 365} years", f"{days // 365} साल")


@rule("R-WEBSITE-NEW")
def website_new(claim: Claim, ctx: RuleContext):
    """A link in an official-looking message points at a website the domain registry says is days or months old,
    is suspended, or does not exist.

    Read live from the registry (RDAP) when online, from recorded answers when not, and silent when neither knows,
    so a dead network is never a finding. Only links off .gov.in / .nic.in are looked up, and only for a message in
    a government body's name or asking for a government due. A site the registry says the body itself holds is
    passed over. The sentence states the registry's facts and nothing about who runs the site. Soft: a new or held
    domain is strong, but it is a fact about a website, not about the message, so it never anchors a RED.
    """
    if not _in_the_states_name(claim):
        return None
    from datetime import datetime
    for u in claim.urls:
        host = _host(u.value)
        if host.endswith(GOVIN_SUFFIXES):
            continue
        rec = _registry_record(host, ctx)
        if rec.get("status") == "NOT_FOUND":
            return {"evidence_key": "web:registry", "host": host, "registry": rec,
                    "finding_en": "is not registered with any domain registry",
                    "finding_hi": "किसी भी डोमेन रजिस्ट्री में दर्ज नहीं है"}
        if rec.get("status") != "FOUND" or _held_by_the_body(claim, rec):
            continue
        try:
            registered = datetime.fromisoformat(str(rec.get("registered")).replace("Z", "+00:00"))
            days = max(0, (ctx.now - registered).days)
        except (TypeError, ValueError):
            days = None
        young = days is not None and days < WEBSITE_YOUNG_DAYS
        if not (young or rec.get("held")):
            continue
        parts_en, parts_hi = [], []
        if young:
            age_en, age_hi = _age_words(days)
            parts_en.append(f"was registered only {age_en} ago")
            parts_hi.append(f"सिर्फ़ {age_hi} पहले रजिस्टर हुई है")
        if rec.get("held"):
            parts_en.append("the domain registry has suspended it" if young else "has been suspended by the domain registry")
            parts_hi.append("डोमेन रजिस्ट्री ने इसे निलंबित कर दिया है" if young else "को डोमेन रजिस्ट्री ने निलंबित कर दिया है")
        return {"evidence_key": "web:registry", "host": host, "registry": rec, "days": days,
                "finding_en": ", and ".join(parts_en), "finding_hi": ", और ".join(parts_hi)}
    return None


@rule("R-SUSPECT")
def suspect(claim: Claim, ctx: RuleContext):
    hit = ctx.adapters.suspect_registry.check(
        account=claim.payee.account.value if claim.payee.account else None,
        vpa=claim.payee.vpa.value if claim.payee.vpa else None,
        phone=claim.caller_number.value if claim.caller_number else ctx.sender_number)
    if hit:
        return {"evidence_key": "registry:suspect", "what": hit, "what_hi": {"account": "खाता", "UPI ID": "UPI आईडी", "phone number": "फ़ोन नंबर"}[hit]}
    return None


@rule("R-BANK-NEVER-MOVE-FD")
def bank_never_move_fd(claim: Claim, ctx: RuleContext):
    if claim.claimed_issuer == Issuer.BANK_SELF and claim.instruction in (Instruction.MOVE_FD, Instruction.TRANSFER_TO_ACCOUNT):
        return {"evidence_key": "claim"}
    return None


# ---------------- F2 ----------------

# How the outbound log's channels read on a customer card. Keys are the `channel` values in the log's own records.
# CHANNEL_ORDER is only how the list reads out loud; an unknown channel still gets named, after these, in
# alphabetical order, so a new channel in the log can never be silently left out of the sentence.
LOG_CHANNEL_EN = {"SMS": "SMS", "EMAIL": "e-mail", "IVR": "IVR calls", "WHATSAPP": "our official WhatsApp",
                  "IN_APP": "in-app messages", "PUSH": "app notifications"}
LOG_CHANNEL_HI = {"SMS": "SMS", "EMAIL": "ईमेल", "IVR": "IVR कॉल", "WHATSAPP": "आधिकारिक व्हाट्सऐप",
                  "IN_APP": "ऐप के संदेश", "PUSH": "ऐप सूचनाएँ"}
CHANNEL_ORDER = ["SMS", "EMAIL", "IVR", "WHATSAPP", "IN_APP", "PUSH"]
# The scope clause when the log cannot be inspected (a production adapter need not expose its records). It drops
# the channel list and keeps the boundary clause, which is the half that stops the claim being categorical.
SCOPE_FALLBACK_EN = "holds only the messages the bank sends you centrally on its logged channels"
SCOPE_FALLBACK_HI = "सिर्फ़ वे संदेश दर्ज करता है जो बैंक आपको केंद्र से अपने लॉग किए चैनलों पर भेजता है"


def _join_words(parts: list[str], last: str) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" {last} " + parts[-1]


def _log_coverage(log) -> dict:
    """How far the bank's outbound log actually reaches, read off the log itself rather than asserted here.

    Two separate facts, from two separate places, because they are true for different reasons:

    * The channel list is computed from the `channel` field of the records the log holds. Whatever the customer
      card says the log covers is therefore something the record in `data/mocks/outbound_log.json` contains, and
      an officer or a judge can open that file and count.
    * The boundary — that this log is what the bank sends *centrally*, so a branch letter or a counter
      conversation is outside it — is the adapter's own declared production source ("Bank CRM / messaging gateway
      logs for centrally sent channels"), which `tests/test_docs.py` already pins word for word against
      `docs/deployment-path.md`. It is not a property of today's rows.

    Only `label` and `find` are in the `OutboundLog` protocol, so a production adapter may not expose `records`.
    With nothing to read, the sentence falls back to the channel-free wording and keeps the boundary clause.
    """
    records = [r for r in list(getattr(log, "records", None) or []) if isinstance(r, dict)]
    found = {str(r.get("channel", "")).strip().upper() for r in records if r.get("channel")}
    channels = ([c for c in CHANNEL_ORDER if c in found]
                + sorted(c for c in found if c not in CHANNEL_ORDER))
    retention = [int(r["retention_days"]) for r in records if isinstance(r.get("retention_days"), int)]
    label = getattr(log, "label", None)
    out = {
        "entries": len(records),
        "channels": channels,
        "retention_days_min": min(retention) if retention else None,
        "source": getattr(label, "production_source", ""),
        "is_mock": bool(getattr(label, "mock", False)),
        "scope_en": SCOPE_FALLBACK_EN,
        "scope_hi": SCOPE_FALLBACK_HI,
    }
    if channels:
        en = _join_words([LOG_CHANNEL_EN.get(c, c.replace("_", " ").lower()) for c in channels], "and")
        hi = _join_words([LOG_CHANNEL_HI.get(c, c.replace("_", " ")) for c in channels], "और")
        out["scope_en"] = f"holds only the messages the bank sends you centrally ({en})"
        out["scope_hi"] = f"सिर्फ़ वे संदेश दर्ज करता है जो बैंक आपको केंद्र से भेजता है ({hi})"
    return out


@rule("R-BANK-SELF")
def bank_self(claim: Claim, ctx: RuleContext):
    """The bank has no record of sending this message, said with the reach of that record attached.

    The reason used to end "It did not come from us." That is categorical and the record under it is not: the log
    holds what the bank sends centrally on logged channels and nothing a branch hands over, posts or says at a
    counter. A hackathon judge pasted a genuine overdue-loan letter from a head-office recovery cell and the
    customer card told a real customer the bank had not sent it. The scope now travels with the claim, in the same
    two sentences, so the officer cannot read one without the other.

    The rule stays hard, and can still anchor a RED. The thinness here is coverage breadth, not lookup
    reliability: inside its stated scope the match is an exact content hash against the gateway log and its answer
    is deterministic. Softening the severity would have left the same categorical sentence standing on a softer
    rule, which is the wrong half to fix. What keeps it safe is structural and is now stronger than a severity
    tweak: a RED still needs an independent family on different evidence, and after this pass it also needs a
    money demand to have been read, so "we have no record of sending this" can never on its own stop a payment.
    """
    if claim.claimed_issuer != Issuer.BANK_SELF or claim.source == "officer_picklist":
        return None
    res = ctx.adapters.outbound_log.find(text=claim.text, sender_number=ctx.sender_number, customer_ref=ctx.customer_ref, now=ctx.now)
    if res["found"] or res["rm_personal_phone"]:
        return None
    coverage = _log_coverage(ctx.adapters.outbound_log)
    return {"evidence_key": "bank:outbound_log", "lookup": {"found": False, "coverage": coverage},
            "scope_en": coverage["scope_en"], "scope_hi": coverage["scope_hi"]}


@rule("R-BANK-RM-PHONE")
def bank_rm_phone(claim: Claim, ctx: RuleContext):
    if claim.claimed_issuer != Issuer.BANK_SELF or claim.source == "officer_picklist":
        return None
    res = ctx.adapters.outbound_log.find(text=claim.text, sender_number=ctx.sender_number, customer_ref=ctx.customer_ref, now=ctx.now)
    if not res["found"] and res["rm_personal_phone"]:
        return {"evidence_key": "bank:outbound_log", "rm": res["rm"].get("name", "")}
    return None


@rule("R-PAYEE-NAME")
def payee_name(claim: Claim, ctx: RuleContext):
    if claim.payee.claimed_owner not in OFFICIAL_OWNERS or claim.payee.account is None:
        return None
    res = ctx.adapters.name_lookup.lookup(claim.payee.account.value, claim.payee.ifsc.value if claim.payee.ifsc else None)
    if res["status"] != "FOUND" or res["allow_listed"] or res["holder_type"] in ("GOVT", "BANK"):
        return None
    return {"evidence_key": "bank:name_lookup", "claimed_en": OWNER_EN[claim.payee.claimed_owner], "claimed_hi": OWNER_HI[claim.payee.claimed_owner],
            "holder": res["holder_name"], "holder_type_en": HOLDER_EN.get(res["holder_type"], "unknown"),
            "holder_type_hi": HOLDER_HI.get(res["holder_type"], "अज्ञात"), "lookup": res}


def _not_the_states(res: dict) -> bool:
    """A name look-up that found a private holder who is not on the bank's list of official collection accounts.
    An account the look-up does not hold is UNKNOWN and says nothing either way: it is never read as private."""
    return res["status"] == "FOUND" and not res["allow_listed"] and res["holder_type"] not in ("GOVT", "BANK")


# The body a due is owed to, for the officer's row when the message asked for a due without naming a sender. The
# card never reads this out: its handler falls back to the instruction, which the message carries a span for.
DUE_OWNER_EN = {Instruction.PAY_CHALLAN: "the traffic police or transport department", Instruction.PAY_LOCAL_TAX: "the municipal corporation"}
DUE_OWNER_HI = {Instruction.PAY_CHALLAN: "यातायात पुलिस या परिवहन विभाग", Instruction.PAY_LOCAL_TAX: "नगर निगम"}


def _sender_words(claim: Claim) -> dict:
    if claim.claimed_issuer in GOVT_SENDERS:
        en, hi = ISSUER_EN[claim.claimed_issuer], ISSUER_HI[claim.claimed_issuer]
    else:
        en, hi = DUE_OWNER_EN[claim.instruction], DUE_OWNER_HI[claim.instruction]
    return {"issuer_en": en, "issuer_hi": hi, "instruction_en": INSTR_EN[claim.instruction],
            "instruction_hi": INSTR_HI[claim.instruction]}


# How the payee reads in the reason. The Hindi carries its own participle because खाता and आईडी differ in gender.
PAYEE_EN = {"account": "account", "vpa": "UPI ID"}
PAYEE_HI = {"account": "दिया गया खाता", "vpa": "दी गई UPI आईडी"}


def _same_as_paused_receiver(kind: str, value: str, ctx: RuleContext) -> bool:
    if kind == "vpa":
        return bool(ctx.flag_payee_vpa) and ctx.flag_payee_vpa.strip().lower() == value.strip().lower()
    return bool(ctx.flag_payee_account) and re.sub(r"\D", "", ctx.flag_payee_account) == re.sub(r"\D", "", value)


@rule("R-PAYEE-NOT-SENDER")
def payee_not_sender(claim: Claim, ctx: RuleContext):
    """The message is in the name of a government body, or asks for a government due, and the account or UPI ID it
    gives is registered to a private person or firm.

    R-PAYEE-NAME's sibling for the message that never SAYS whose account it is. A copied tax notice or a forged
    summons rarely writes "government account" beside the number; the number simply sits where the real notice had
    the body's own account. The money is then demanded for the sender the message names, so that is what the
    look-up is checked against. When the message does say whose account it is, R-PAYEE-NAME runs instead and this
    one stands down, so one account never gives two reasons. It needs no list of known scammers: a scammer nobody
    has reported yet still has to receive the money in an account with a name on it.

    A UPI ID is checked the same way as an account, because a fake fine says "pay at 98...@slc" far more often than
    it gives an account number. When the message's payee is also the paused payment's receiver, R-RECEIVER-NAME
    already says where the money goes, so this one stands down rather than say it twice.
    """
    p = claim.payee
    if not _in_the_states_name(claim) or p.claimed_owner in OFFICIAL_OWNERS:
        return None
    if p.account is not None:
        kind, value = "account", p.account.value
        res = ctx.adapters.name_lookup.lookup(value, p.ifsc.value if p.ifsc else None)
    elif p.vpa is not None:
        kind, value = "vpa", p.vpa.value
        res = ctx.adapters.name_lookup.lookup_vpa(value)
    else:
        return None
    if _same_as_paused_receiver(kind, value, ctx) or not _not_the_states(res):
        return None
    return {"evidence_key": "bank:name_lookup", **_sender_words(claim), "holder": res["holder_name"],
            "payee_kind": kind, "payee_en": PAYEE_EN[kind], "payee_hi": PAYEE_HI[kind],
            "holder_type_en": HOLDER_EN.get(res["holder_type"], "unknown"),
            "holder_type_hi": HOLDER_HI.get(res["holder_type"], "अज्ञात"), "lookup": res}


@rule("R-RECEIVER-NAME")
def receiver_name(claim: Claim, ctx: RuleContext):
    """The payment the bank paused goes to a private person or firm, while the message behind it is in the name of
    a government body or asks for a government due.

    This reads the bank's OWN record of the transfer (the flag), not the message, which is what makes it hold up
    against a perfect copy: every word of a real challan or tax notice can be copied, but the money still has to
    land in an account the sender controls, and the bank sees whose it is before it moves. A challan copy that
    gives only a link and a phone number has no account in it at all, and this is the check that still runs.
    """
    if not _in_the_states_name(claim):
        return None
    if ctx.flag_payee_account:
        paid_to = ctx.flag_payee_account
        res = ctx.adapters.name_lookup.lookup(paid_to, ctx.flag_payee_ifsc)
    elif ctx.flag_payee_vpa:
        paid_to = ctx.flag_payee_vpa
        res = ctx.adapters.name_lookup.lookup_vpa(paid_to)
    else:
        return None
    if not _not_the_states(res):
        return None
    return {"evidence_key": "bank:paused_payment", "holder": res["holder_name"], "paid_to": paid_to,
            "holder_type_en": HOLDER_EN.get(res["holder_type"], "unknown"),
            "holder_type_hi": HOLDER_HI.get(res["holder_type"], "अज्ञात"), "lookup": res}


def _amounts_inr(claim: Claim) -> list[float]:
    import re as _re
    out = []
    for a in claim.amounts:
        # a.value, not a.span.text: the span quotes the ORIGINAL message so the officer sees the real characters,
        # which since the normalisation pass may carry zero-width spaces or folded homoglyphs inside the digits.
        # The value is the normalised reading, and it is the number the ledger must be compared against.
        txt = (a.value or a.span.text).lower().replace(",", "")
        m = _re.search(r"(\d+(?:\.\d+)?)", txt)
        if not m:
            continue
        v = float(m.group(1))
        if "crore" in txt or _re.search(r"\bcr\b", txt):
            v *= 1e7
        elif "lakh" in txt or "lac" in txt:
            v *= 1e5
        elif txt.endswith("k"):
            v *= 1e3
        out.append(v)
    return out


@rule("R-LEDGER")
def ledger(claim: Claim, ctx: RuleContext):
    """The message says money was credited; the ledger shows no such credit in the last 72 hours."""
    if claim.instruction != Instruction.RETURN_EXCESS_CREDIT:
        return None
    credits = ctx.adapters.ledger.credits(ctx.customer_ref, ctx.now, hours=72)
    claimed = _amounts_inr(claim)
    if claimed:
        matched = [c for c in credits if any(abs(float(c.get("amount", 0)) - v) <= 0.01 * v for v in claimed)]
    else:
        matched = credits
    if matched:
        return None
    return {"evidence_key": "bank:ledger", "lookup": {"credits_72h": len(credits), "claimed_amounts": claimed}}


@rule("R-OWN-SIGNATURE")
def own_signature(claim: Claim, ctx: RuleContext):
    if claim.claimed_issuer != Issuer.BANK_SELF or ctx.media_signature_valid is not True:
        return None
    res = ctx.adapters.outbound_log.find(text=claim.text, sender_number=ctx.sender_number, customer_ref=ctx.customer_ref, now=ctx.now)
    if res["found"]:
        return {"evidence_key": "bank:signature", "record_id": res["record"].get("message_id", "")}
    return None


# ---------------- F5 ----------------

@rule("R-PRESSURE-CUES")
def pressure_cues(claim: Claim, ctx: RuleContext):
    if claim.pressure_cues:
        cues = list(claim.pressure_cues)
        return {"evidence_key": "claim", "cues": cues, "cues_en": ", ".join(CUE_EN[c] for c in cues), "cues_hi": ", ".join(CUE_HI[c] for c in cues)}
    return None
