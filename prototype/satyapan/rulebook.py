"""Rulebook: rule metadata lives in YAML (citation, reason text, severity); rule logic lives in rules.py.

Why split them: Compliance and Legal sign off on the YAML, and a rule without a verified citation is demoted to
soft at load time, so it can never anchor a RED no matter what the code says.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from .models import Claim, Family, Severity, Signal

DEFAULT_RULEBOOK = Path(__file__).resolve().parent.parent / "data" / "rules" / "rulebook.yaml"


@dataclass
class Citation:
    source: str
    url: str
    quote: str = ""
    checked: str = ""
    verified: bool = False


@dataclass
class RuleMeta:
    id: str
    family: Family
    severity: Severity
    title: str
    reason_en: str
    reason_hi: str
    citation: Citation
    escalate_alone: bool = False
    can_be_second: bool = True
    sign_off: list[str] = field(default_factory=list)
    test: str = ""


@dataclass
class Rulebook:
    version: str
    bank_name: str
    rules: dict[str, RuleMeta]
    sha256: str
    path: str

    def meta(self, rule_id: str) -> RuleMeta:
        return self.rules[rule_id]


def load_rulebook(path: Path | str = DEFAULT_RULEBOOK) -> Rulebook:
    raw = Path(path).read_bytes()
    doc = yaml.safe_load(raw)
    rules: dict[str, RuleMeta] = {}
    for r in doc["rules"]:
        c = r.get("citation", {})
        cit = Citation(source=c.get("source", ""), url=c.get("url", ""), quote=c.get("quote", ""),
                       checked=str(c.get("checked", "")), verified=bool(c.get("verified", False)))
        sev = Severity(r["severity"])
        # The demotion rule: an unverified citation can flag, but never anchor a RED.
        if sev == Severity.HARD and not cit.verified:
            sev = Severity.SOFT
        rules[r["id"]] = RuleMeta(
            id=r["id"], family=Family(r["family"]), severity=sev, title=r.get("title", r["id"]),
            reason_en=r["reason_en"], reason_hi=r["reason_hi"], citation=cit,
            escalate_alone=bool(r.get("escalate_alone", False)), can_be_second=bool(r.get("can_be_second", True)),
            sign_off=list(r.get("sign_off", [])), test=r.get("test", ""),
        )
    return Rulebook(version=str(doc["version"]), bank_name=doc.get("bank_name", "the bank"), rules=rules,
                    sha256=hashlib.sha256(raw).hexdigest(), path=str(path))


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def make_signal(book: Rulebook, rule_id: str, detail: dict, *, severity: Optional[Severity] = None) -> Signal:
    """Build a Signal from rule metadata plus the detail dict a rule function returned.

    `detail` must contain `evidence_key`; everything else is available to the reason templates.
    """
    m = book.meta(rule_id)
    fmt = _SafeDict(bank=book.bank_name, **{k: v for k, v in detail.items() if k != "evidence_key"})
    return Signal(
        rule_id=rule_id, family=m.family, severity=severity or m.severity, evidence_key=detail["evidence_key"],
        reason_en=m.reason_en.format_map(fmt), reason_hi=m.reason_hi.format_map(fmt),
        citation=m.citation.source, citation_url=m.citation.url, citation_verified=m.citation.verified,
        escalate_alone=m.escalate_alone, rule_version=f"rulebook-{book.version}",
        detail={k: v for k, v in detail.items() if k != "evidence_key"} | {"can_be_second": m.can_be_second},
    )


# Registry of rule functions. Each takes (claim, ctx) and returns a detail dict when it fires, else None.
RuleFn = Callable[[Claim, "RuleContext"], Optional[dict]]
REGISTRY: dict[str, RuleFn] = {}


def rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    def deco(fn: RuleFn) -> RuleFn:
        REGISTRY[rule_id] = fn
        return fn
    return deco


class RuleContext:
    """Everything a rule may consult besides the claim: adapters, media facts, clock. Set by the pipeline."""

    def __init__(self, *, adapters, now, bank_name: str, sender_number: str | None = None,
                 media_signature_valid: bool | None = None, media_hashes: list[str] | None = None,
                 customer_ref: str = "", flag_amount: float = 0.0, flag_payee_account: str | None = None,
                 flag_payee_ifsc: str | None = None, flag_payee_vpa: str | None = None):
        self.adapters = adapters
        self.now = now
        self.bank_name = bank_name
        self.sender_number = sender_number
        self.media_signature_valid = media_signature_valid
        self.media_hashes = media_hashes or []
        self.customer_ref = customer_ref
        self.flag_amount = flag_amount
        # Where the paused payment itself is going, from the bank's own transfer record (the flag), not from the
        # message. The message can be a perfect copy of a real notice; the receiver of the money cannot be copied.
        self.flag_payee_account = flag_payee_account
        self.flag_payee_ifsc = flag_payee_ifsc
        self.flag_payee_vpa = flag_payee_vpa


def evaluate(book: Rulebook, claim: Claim, ctx: RuleContext) -> list[Signal]:
    """Run every registered rule that the rulebook knows about. Unknown rule ids are skipped (and vice versa)."""
    signals: list[Signal] = []
    for rule_id, fn in REGISTRY.items():
        if rule_id not in book.rules:
            continue
        detail = fn(claim, ctx)
        if detail:
            signals.append(make_signal(book, rule_id, detail))
    return signals
