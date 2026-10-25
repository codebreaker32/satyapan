"""An offline helper reader: a small LLM on this laptop (Ollama) that reads what the rules-based extractor missed.

It never decides anything and never overrides the rules. It runs after the rules-based extractor and only for the
fields that extractor left empty WITHOUT having seen a candidate for them: where the rules read an authority or a
demand and then set it aside on purpose (a reported claim, a negated instruction, a referral, two bodies at once),
that choice stands and the model is not asked. Every field it proposes must come with the exact words it was read
from; a field whose words are not in the message, or whose value is not one the rules know, is dropped, and each
accepted field quotes the original characters, so `extract.ground()` re-checks it like any other.

What it may fill, and why only that:
- the authority, but only as OTHER ("a government-sounding name"), never a named agency. A named agency switches on
  the bank-record rules that compare the payee with the state body; a model's guess must never be able to reach a
  RED that way. R-STATE-NAME-PAY then says only what was read: a government-sounding name and a demand for money.
- the instruction about money, only beside an unnamed or government-sounding sender and never as a government due,
  with the rules' own guards re-run at the quoted words (negation, reported speech). Beside the bank's own name a
  model-read request paired with the bank-record rules into a RED on a genuine EMI letter in the evaluation set;
- the "you are under digital arrest" words, which must contain the phrase and pass extract.is_warning_about.
It never fills a payee: the rules' own patterns already read every well-formed account, IFSC and UPI ID, and a
model-read payee would start a bank look-up on words no pattern could confirm.

Nothing leaves the machine: Ollama serves the model on 127.0.0.1, and with the model missing or slow the reader steps
aside and the rules-based reading stands alone. The model is Meta's Llama 3.2 3B (Llama 3.2 Community License;
Built with Llama), declared in MODELS.md.

  SATYAPAN_LLM_READER=llama3.2:3b      # turn it on with this model (pass it to scripts/demo_up.sh); off by default
  SATYAPAN_OLLAMA_URL=http://127.0.0.1:11434
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.request
from typing import Optional

from .extract import (DESPACE_LEXICON, INSTRUCTION_KEYWORDS, RE_DA_PHRASE, RE_NEGATION, RE_REPORTED_DEMAND, RE_VEHICLE,
                      _first, _sentence_start, authority_hits, is_warning_about)
from .models import GOVT_DUES, Claim, Instruction, Issuer, Span
from .normalize import normalise

DEFAULT_URL = "http://127.0.0.1:11434"
CALL_SECONDS: list[float] = []          # every model call's wall time in this process (the evaluation reports it)


def _norm(s: str) -> str:
    """Casefold, NFC, and collapse whitespace and quote marks, so a quote matches the message as written."""
    s = unicodedata.normalize("NFC", s or "").casefold()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def quote_in(text: str, quote: str) -> bool:
    """True when `quote` (at least 3 characters) appears in `text`, ignoring case and spacing."""
    q = _norm(quote).strip(" .,:;!?\"'")
    return len(q) >= 3 and q in _norm(text)


def find_span(text: str, quote: str) -> Optional[Span]:
    """The quote as a Span of the ORIGINAL text (its own characters, so ground() accepts it), or None."""
    q = (quote or "").strip().strip(".,:;!?\"'“”‘’").strip()
    if len(q) < 3:
        return None
    pattern = r"\s+".join(re.escape(w) for w in q.split())
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return Span(text=text[m.start():m.end()], start=m.start(), end=m.end()) if m else None


def ollama_json(prompt: str, schema: dict, *, model: str, system: str, url: str = DEFAULT_URL,
                timeout: float = 60.0) -> dict:
    """One structured call to the local model: temperature 0 and a fixed seed, so the same message reads the same."""
    body = {"model": model, "stream": False, "format": schema, "keep_alive": "2h",
            "options": {"temperature": 0, "seed": 7, "num_ctx": 1536, "num_predict": 160},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    return json.loads(out["message"]["content"])


def configured_model() -> Optional[str]:
    """The model name when the helper reader is switched on, else None (the default: rules only)."""
    m = os.environ.get("SATYAPAN_LLM_READER", "").strip()
    return None if m in ("", "0", "off", "none") else m


# The model is asked for exact words and two yes/no answers, never to classify into the engine's enums: a 3B model
# picking from labels it cannot see ("the customer's own bank" for "Main PMO se bol raha hoon") reads worse and
# slower. The reader maps the words itself: a government sender becomes OTHER, and the money request's kind comes
# from its own words (fee, invest, FD, challan, tax), defaulting to a transfer.
SCHEMA = {"type": "object", "properties": {
    "sender_words": {"type": "string"},
    "sender_is_government": {"type": "boolean"},
    "money_request_words": {"type": "string"},
    "digital_arrest": {"type": "boolean"},
    "digital_arrest_words": {"type": "string"}},
    "required": ["sender_words", "sender_is_government", "money_request_words", "digital_arrest", "digital_arrest_words"]}
SYSTEM = ("Read a message a bank customer received (English, Hindi, or Hinglish). Copy exact words from it. "
          "Never guess; use an empty string or false when the message does not say it. A warning about a trick "
          "asks for nothing.")
INSTRUCTION_BY_WORDS = [
    (Instruction.PAY_FEE_TO_VERIFY, r"\b(?:fee|fees|charge|charges|shulk|shulka|penalty|fine|security\s+deposit)\b|शुल्क|जुर्माना|फ़ीस|फीस"),
    (Instruction.INVEST_FOR_RETURNS, r"\b(?:invest\w*|nivesh|returns?|profit|trading)\b|निवेश|मुनाफ़|मुनाफा"),
    (Instruction.MOVE_FD, r"\b(?:fd|fixed\s+deposit)\b|एफडी"),
    (Instruction.PAY_CHALLAN, r"\b(?:e-?challan|challan)\b|चालान"),
    (Instruction.PAY_LOCAL_TAX, r"\b(?:property\s+tax|house\s+tax|water\s+bill|electricity\s+bill|bijli)\b|गृहकर|संपत्ति\s*कर|बिजली"),
]
RE_MONEY_WORDS = re.compile(r"\b(?:pay|send|transfer|deposit|invest|remit|rupay\w*|rupees?|rs\.?|inr|lakh|crore|paise|paisa"
                            r"|bhej\w*|jama|upi|account|a/c)\b|₹|रुपय|रुपए|पैस|भेज|जमा|ट्रांसफर|खात", re.I)


def instruction_for(words: str) -> Instruction:
    for value, pattern in INSTRUCTION_BY_WORDS:
        if re.search(pattern, words, re.I):
            return value
    return Instruction.TRANSFER_TO_ACCOUNT


# Hindi negation the instruction guard's RE_NEGATION cannot see: its `\bनहीं\b` never matches after an anusvara.
RE_HI_NEGATION = re.compile(r"नहीं|मत\b|\bन\s|\bmat\b|\bnahi\b|\bnahin\b|\bna\b", re.I)


def _prompt(text: str) -> str:
    return (f"Message:\n<<<\n{text[:3000]}\n>>>\n"
            "sender_words: exact words naming who the message says it is from or speaks for (an office, title or "
            "organisation), else empty.\n"
            "sender_is_government: true if that is a government office, minister, official, agency, court or police.\n"
            "money_request_words: exact words where the message itself asks the customer to pay, send, transfer, "
            "deposit or invest money, else empty.\n"
            "digital_arrest: true if the message tells the customer they are under \"digital arrest\".\n"
            "digital_arrest_words: those exact words, else empty.")


class LocalLLMReader:
    """Fills the gaps the rules-based reading left, from a local model, one quote-checked field at a time."""

    def __init__(self, model: str, url: Optional[str] = None, timeout: float = 60.0):
        self.model = model
        self.url = url or os.environ.get("SATYAPAN_OLLAMA_URL", DEFAULT_URL)
        self.timeout = timeout
        self.name = f"{model} (offline, quote-checked)"
        self._cache: dict[str, Optional[dict]] = {}

    # ---------------------------------------------------------------- which fields may be asked about
    def gaps(self, claim: Claim) -> set[str]:
        """The fields the rules left empty without having seen any candidate for them."""
        t = normalise(claim.text, DESPACE_LEXICON).text
        out = set()
        if claim.claimed_issuer == Issuer.NONE and not claim.other_issuers and not authority_hits(t):
            out.add("claimed_issuer")
        if (claim.instruction == Instruction.NONE and claim.claimed_issuer in (Issuer.NONE, Issuer.OTHER)
                and not any(_first(p, t) for _, p in INSTRUCTION_KEYWORDS)):
            out.add("instruction")
        if claim.digital_arrest_span is None and RE_DA_PHRASE.search(t):
            out.add("digital_arrest_span")
        return out

    def _ask(self, text: str) -> Optional[dict]:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key not in self._cache:
            t0 = time.perf_counter()
            try:
                self._cache[key] = ollama_json(_prompt(text), SCHEMA, model=self.model, system=SYSTEM, url=self.url,
                                               timeout=self.timeout)
            except Exception:  # noqa: BLE001 - no model, no Ollama, a timeout or bad JSON: the rules' reading stands
                self._cache[key] = None
            CALL_SECONDS.append(time.perf_counter() - t0)
        return self._cache[key]

    # ---------------------------------------------------------------- the checks each proposal must pass
    @staticmethod
    def _instruction_ok(text: str, span: Span, value: Instruction) -> bool:
        before = text[_sentence_start(text, span.start):span.start]
        if RE_NEGATION.search(before) or RE_REPORTED_DEMAND.search(before) or RE_HI_NEGATION.search(span.text):
            return False
        if RE_HI_NEGATION.search(before[-12:]):            # Hindi puts the "don't" just before the verb
            return False
        if value == Instruction.PAY_CHALLAN and not RE_VEHICLE.search(text):
            return False
        return True

    @staticmethod
    def _name_ok(span: Span) -> bool:
        """A name, not a pronoun or a verb: a capital letter or Devanagari, and at least three letters."""
        letters = re.sub(r"[^A-Za-zऀ-ॿ]", "", span.text)
        return len(letters) >= 3 and (any(ch.isupper() for ch in span.text) or bool(re.search(r"[ऀ-ॿ]", span.text)))

    def fill(self, claim: Claim) -> Claim:
        gaps = self.gaps(claim)
        if not gaps or not claim.text.strip():
            return claim
        got = self._ask(claim.text)
        if not got:
            return claim
        text, filled = claim.text, []
        if "claimed_issuer" in gaps and got.get("sender_is_government") is True:
            span = find_span(text, got.get("sender_words", ""))
            if span is not None and self._name_ok(span):
                claim.claimed_issuer, claim.issuer_span = Issuer.OTHER, span
                filled.append("claimed_issuer")
        words = got.get("money_request_words", "")
        # Only beside an unnamed or government-sounding sender, and never as a government due. Beside the bank's own
        # name or a named body, a model-read request pairs with the bank-record rules into a RED: in the evaluation,
        # the genuine EMI letter V73 ("push Rs 12,000 into the designated EMI collection account", an order form the
        # rules deliberately do not read as a demand) went to RED that way. A challan or tax would switch on the
        # receiver-name rule the same way.
        if ("instruction" in gaps and words and RE_MONEY_WORDS.search(words)
                and claim.claimed_issuer in (Issuer.NONE, Issuer.OTHER)):
            span = find_span(text, words)
            value = instruction_for(words)
            if value in GOVT_DUES:
                span = None
            if span is not None and self._instruction_ok(text, span, value):
                claim.instruction, claim.instruction_span = value, span
                filled.append("instruction")
        if "digital_arrest_span" in gaps and got.get("digital_arrest") is True:
            words = find_span(text, got.get("digital_arrest_words", ""))
            m = RE_DA_PHRASE.search(text, words.start, words.end) if words is not None else None
            if m is not None and not is_warning_about(text, m.start(), m.end()):
                claim.digital_arrest_span = Span(text=text[m.start():m.end()], start=m.start(), end=m.end())
                filled.append("digital_arrest_span")
        if filled:
            claim.read_by_llm = filled
            claim.extractor = f"{claim.extractor} + {self.name}"
        return claim
