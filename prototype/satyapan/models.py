"""Data model shared by every stage. Pydantic so the API, the evidence pack and the tests use one schema."""
from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- what the message claims ----------

class Issuer(str, Enum):
    ED = "ED"                 # Enforcement Directorate
    CBI = "CBI"
    POLICE = "POLICE"         # state police, cyber cell, crime branch
    COURT = "COURT"
    RBI = "RBI"
    SEBI = "SEBI"
    CUSTOMS = "CUSTOMS"
    TRAI_DOT = "TRAI_DOT"     # telecom regulator / department
    TRANSPORT = "TRANSPORT"   # traffic police, RTO, the transport department and its e-challan service
    MUNICIPAL = "MUNICIPAL"   # municipal corporation / nagar nigam / nagar palika (property and house tax)
    BANK_SELF = "BANK_SELF"   # claims to be this bank or its relationship manager
    OTHER = "OTHER"
    NONE = "NONE"


LAW_ENFORCEMENT = {Issuer.ED, Issuer.CBI, Issuer.POLICE, Issuer.CUSTOMS, Issuer.TRAI_DOT}
# The two bodies that DO legitimately ask a citizen for money by message: a traffic challan and a property or house
# tax bill are real demands, paid on the body's own website or at its office. They are deliberately not
# LAW_ENFORCEMENT, because R-AGENCY-PAY's sentence ("no government agency demands money on a call") is false about
# them, and a copied challan or tax notice is a real message with only its payment details swapped.
CIVIC_DUE_ISSUERS = {Issuer.TRANSPORT, Issuer.MUNICIPAL}
# Who a payment demanded in the name of the state has to reach. When a message is in the name of one of these
# bodies, the money it asks for belongs in that body's own account, so the bank's name look-up has something to
# check even when the message never says "government account". The open-set body (OTHER) is left out on purpose:
# its name was read on its FORM and may be an ordinary company's (see CLAIMED_STATE_AUTHORITY below), and saying
# "the account is not the government's" about a company's own collection account would accuse it.
GOVT_SENDERS = LAW_ENFORCEMENT | CIVIC_DUE_ISSUERS | {Issuer.COURT, Issuer.RBI, Issuer.SEBI}

# Every persona a payment can be demanded in the name of the state under. OTHER is the open-set body: a name the
# message spells out on a letterhead or in a self-claim and the enum has no row for ("IRDAI Enforcement Cell,
# Mumbai", "Narcotics Control Bureau"). Without it, that whole class of digital-arrest script lands on GREY,
# because the rule asking whether a state body is demanding money could only be asked about eight named bodies.
# A court and a regulator are deliberately NOT in here: each has its own rule with its own citation
# (R-COURT-PAY, R-RBI-INV), and folding them in would put a second, differently-sourced sentence on the same
# facts.
#
# The set is PARTITIONED between two rules, and the partition is the point. "This message claims to be a
# government body" is a statement of fact about the sender, and for an enumerated body the message names it in
# so many words. For an open-set body it is a reading of the NAME's form, and the form cannot tell "Narcotics
# Control Bureau" from "Credit Information Bureau (India) Limited" or from "Acme Recovery and Fraud
# Investigation Unit". So LAW_ENFORCEMENT keeps R-AGENCY-PAY, which says what the message claims to be, and
# OTHER gets R-STATE-NAME-PAY, which says only what was read: a government-sounding name, a demand for money,
# and a sender that could not be confirmed. Same family, same severity, same citation; a different sentence.
CLAIMED_STATE_AUTHORITY = LAW_ENFORCEMENT | {Issuer.OTHER}
# The open-set half of that partition. A set rather than `is Issuer.OTHER` so the two rules are written as one
# partition of one class and a third persona cannot be added to only one of them by accident.
OPEN_SET_AUTHORITY = CLAIMED_STATE_AUTHORITY - LAW_ENFORCEMENT


def visible_name(value: Optional[str]) -> Optional[str]:
    """A person's name for the record, or None if nobody is there.

    `str.strip()` is not enough. Without this, a decision could be signed as U+200B and a RED case released
    alone by passing a zero-width space as the co-signer: `"\\u200b".isspace()` is False, so it survives strip()
    and satisfies the four-eyes check. Anything with no visible glyph is nobody — format characters (Cf: ZWSP,
    BOM, word joiner, the bidi marks), control characters (Cc) and every separator (Zs, Zl, Zp).
    """
    if not value:
        return None
    kept = "".join(ch for ch in value if unicodedata.category(ch) not in ("Cf", "Cc", "Zl", "Zp") and ch not in _BLANKS)
    kept = kept.strip()
    # Some blanks are letters to Unicode (the Hangul fillers are Lo) or symbols (the Braille blank is So), and a lone
    # combining mark or variation selector has no glyph of its own. A name needs at least one letter or digit.
    if not any(ch.isalnum() and ch not in _BLANKS for ch in kept):
        return None
    return kept


# Characters that render as nothing but are not format characters: Hangul fillers (U+115F, U+1160, U+3164, U+FFA0)
# and the Braille blank (U+2800). Each of them, as the co-signer, could otherwise release a RED.
_BLANKS = frozenset("\u115f\u1160\u3164\uffa0\u2800")

# Letters from other scripts that look like Latin ones in a staff id: "оfficer.demo" with a Cyrillic о could
# co-sign officer.demo's own release. Only lookalikes of Latin letters; nothing else is folded.
_CONFUSABLES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h", "ӏ": "l",
    "ԛ": "q", "ԝ": "w", "ү": "y", "ɡ": "g", "ı": "i",
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "ω": "w",
})


def identity_key(value: Optional[str]) -> Optional[str]:
    """Who a name refers to, for "is this a different person" checks (the RED co-sign, the memory two-person rule).

    The record keeps the name as typed (visible_name); this key only compares. Full-width letters fold through NFKC,
    case through casefold, combining marks and variation selectors are dropped, and Cyrillic or Greek lookalikes fold
    to Latin. Without it "OFFICER.DEMO" is caught but "оfficer.demo" (Cyrillic о), "ｏｆｆｉｃｅｒ.ｄｅｍｏ" and
    "officer.demo" plus an invisible mark each pass as a second person."""
    name = visible_name(value)
    if name is None:
        return None
    folded = unicodedata.normalize("NFKC", name).casefold()
    folded = "".join(ch for ch in unicodedata.normalize("NFD", folded) if unicodedata.category(ch) not in ("Mn", "Me"))
    return folded.translate(_CONFUSABLES)


class Channel(str, Enum):
    WHATSAPP = "WHATSAPP"
    VIDEO_CALL = "VIDEO_CALL"
    PHONE_CALL = "PHONE_CALL"
    SMS = "SMS"
    EMAIL = "EMAIL"
    POST = "POST"
    IN_APP = "IN_APP"
    UNKNOWN = "UNKNOWN"


class Instruction(str, Enum):
    TRANSFER_TO_ACCOUNT = "TRANSFER_TO_ACCOUNT"
    MOVE_FD = "MOVE_FD"                      # break an FD / move savings to a "safe account"
    INVEST_FOR_RETURNS = "INVEST_FOR_RETURNS"
    RETURN_EXCESS_CREDIT = "RETURN_EXCESS_CREDIT"
    PAY_FEE_TO_VERIFY = "PAY_FEE_TO_VERIFY"
    PAY_CHALLAN = "PAY_CHALLAN"              # pay a traffic challan (e-challan)
    PAY_LOCAL_TAX = "PAY_LOCAL_TAX"          # pay property, house or water tax to the municipal body
    NONE = "NONE"


PAYMENT_INSTRUCTIONS = {
    Instruction.TRANSFER_TO_ACCOUNT, Instruction.MOVE_FD, Instruction.INVEST_FOR_RETURNS,
    Instruction.RETURN_EXCESS_CREDIT, Instruction.PAY_FEE_TO_VERIFY, Instruction.PAY_CHALLAN, Instruction.PAY_LOCAL_TAX,
}
# A government due: a demand that is real when the body itself sends it, and paid to that body. Asking for one is
# a claim that the money goes to the government, whoever the message names as its sender.
GOVT_DUES = {Instruction.PAY_CHALLAN, Instruction.PAY_LOCAL_TAX}


class ClaimedOwner(str, Enum):
    """Who the message says the payee account belongs to."""
    RBI = "RBI"
    GOVT = "GOVT"
    COURT = "COURT"
    AGENCY = "AGENCY"
    BANK = "BANK"
    PRIVATE = "PRIVATE"
    UNKNOWN = "UNKNOWN"


OFFICIAL_OWNERS = {ClaimedOwner.RBI, ClaimedOwner.GOVT, ClaimedOwner.COURT, ClaimedOwner.AGENCY}


class Span(BaseModel):
    """A verbatim quote from the source text. Every extracted field must carry one (quote-grounding)."""
    text: str
    start: int
    end: int


class Grounded(BaseModel):
    value: str
    span: Span


class Payee(BaseModel):
    account: Optional[Grounded] = None
    ifsc: Optional[Grounded] = None
    vpa: Optional[Grounded] = None
    claimed_owner: ClaimedOwner = ClaimedOwner.UNKNOWN
    claimed_owner_span: Optional[Span] = None


class DocumentIds(BaseModel):
    summons_no: Optional[Grounded] = None
    passcode: Optional[Grounded] = None
    issue_date: Optional[Grounded] = None
    case_no: Optional[Grounded] = None


class Claim(BaseModel):
    source: str                       # "transcript" | "ocr" | "officer_picklist" | "text"
    text: str
    claimed_issuer: Issuer = Issuer.NONE
    issuer_span: Optional[Span] = None
    # Every OTHER authority the message names, with the span it was read from. A genuine official communication
    # almost never speaks for two bodies at once; a scam script often does, and an injected prefix always does.
    # Nothing in the rulebook reads this yet: it exists so the record is true about what the message named, and
    # so the console can say "this message names two different authorities" without re-reading the text.
    other_issuers: list[Grounded] = Field(default_factory=list)
    channel: Channel = Channel.UNKNOWN
    channel_span: Optional[Span] = None
    instruction: Instruction = Instruction.NONE
    instruction_span: Optional[Span] = None
    payee: Payee = Field(default_factory=Payee)
    document_ids: DocumentIds = Field(default_factory=DocumentIds)
    mentions_summons: bool = False
    amounts: list[Grounded] = Field(default_factory=list)
    pressure_cues: dict[str, Span] = Field(default_factory=dict)
    caller_number: Optional[Grounded] = None
    urls: list[Grounded] = Field(default_factory=list)
    language_hint: str = "en"
    extractor: str = "rules-1.0"
    # The message tells the customer she is under "digital arrest" (extract.digital_arrest_to_you, or the offline
    # reader when its quote passes the same warning check). R-DIGITAL-ARREST-PAY reads it.
    digital_arrest_span: Optional[Span] = None
    # Claim fields the offline helper reader (llm_reader.py) filled because the rules left them empty. Each still
    # quotes the message; the console can say which words a model read rather than a pattern.
    read_by_llm: list[str] = Field(default_factory=list)

    def has_content(self) -> bool:
        return self.claimed_issuer != Issuer.NONE or self.instruction != Instruction.NONE


# ---------- what the checks say ----------

class Family(str, Enum):
    F1 = "F1"   # issuer rulebook
    F2 = "F2"   # bank-truth provenance
    F3 = "F3"   # media forensics (corroborate only)
    F4 = "F4"   # campaign memory
    F5 = "F5"   # bank context / pressure cues (never the second family)


class Severity(str, Enum):
    HARD = "hard"       # can anchor a RED (needs a verified citation and a second family)
    SOFT = "soft"       # flag; two independent softs, or one with escalate_alone, give AMBER
    INFO = "info"       # shown to the officer, never changes the verdict
    MATCH = "match"     # positive provenance (the bank's own signed message)
    ABSTAIN = "abstain"


class Signal(BaseModel):
    rule_id: str
    family: Family
    severity: Severity
    evidence_key: str                 # what the signal rests on; two signals on one key never count twice
    reason_en: str
    reason_hi: str
    citation: str = ""
    citation_url: str = ""
    citation_verified: bool = False
    escalate_alone: bool = False      # a single soft that still means "verify before paying"
    rule_version: str = ""
    detail: dict = Field(default_factory=dict)


class Outcome(str, Enum):
    RED = "RED"
    AMBER = "AMBER"
    GREY = "GREY"
    MATCHES = "MATCHES"


class Verdict(BaseModel):
    outcome: Outcome
    headline_en: str
    headline_hi: str
    anchor_rule: Optional[str] = None       # the hard rule a RED rests on
    second_family: Optional[str] = None     # the independent signal that made it RED
    explanation: str
    policy_version: str
    signals: list[Signal]
    scores: Optional[dict] = None           # instruction %, deepfake %, combined % when media was judged
    no_money_cap: bool = False              # two families agreed, but no money demand was read, so AMBER not RED


# ---------- the case ----------

class Flag(BaseModel):
    """What the bank's own monitoring passed to Satyapan when it paused the transfer."""
    reason: str
    amount_inr: float = 0
    customer_ref: str = "cust-demo"
    payee_account: Optional[str] = None
    payee_ifsc: Optional[str] = None
    payee_vpa: Optional[str] = None
    channel: str = "branch"            # branch | callback


class Consent(BaseModel):
    check: bool = False          # C1: check this message for you
    report: bool = False         # C2: include it in a report (Chakshu / 1930)
    memory: bool = False         # C3: add its fingerprint to campaign memory
    recorded_at: Optional[str] = None
    read_aloud_lang: str = "hi"


class MediaRef(BaseModel):
    filename: str
    kind: str                    # audio | image | pdf | video | text
    sha256: str
    bytes: int
    perceptual_hash: Optional[str] = None
    derived_text: Optional[str] = None     # transcript or OCR text
    derived_text_engine: Optional[str] = None  # what produced derived_text (e.g. "tesseract 5.3.4"); None if supplied by the caller


class Decision(BaseModel):
    at: str = Field(default_factory=now_iso)
    actor: str                   # officer id or analyst id
    action: str                  # release | hold | escalate | strike_field | approve_hold | help_report
    note: str = ""


class Case(BaseModel):
    id: str = Field(default_factory=lambda: "SP-" + uuid.uuid4().hex[:8].upper())
    created_at: str = Field(default_factory=now_iso)
    flag: Flag
    consent: Consent = Field(default_factory=Consent)
    media: list[MediaRef] = Field(default_factory=list)
    claim: Optional[Claim] = None
    verdict: Optional[Verdict] = None
    decisions: list[Decision] = Field(default_factory=list)
    status: str = "open"         # open | held | released | escalated | closed
