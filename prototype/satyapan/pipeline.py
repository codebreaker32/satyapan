"""The pipeline: open a case from the bank's flag, take in text or media, run the five families, fuse, and produce
the card and the signed evidence pack. This is the one object the API, the CLI and the tests all drive.
"""
from __future__ import annotations

import os

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import POLICY_VERSION, __version__
from . import rules as _rules  # noqa: F401  (importing registers the rule functions)
from .adapters import Adapters
from .card import Card, build_card
from .evidence import LocalSigner, make_pack
from .extract import RulesExtractor, claim_from_picklist, ground
from .forensics import DocumentForensics, RemoteForensics, SimulatedForensics, default_audio_forensics, to_signal
from .fusion import fuse
from .media import ingest, sha256_file
from .memory import CampaignMemory
from .models import (Case, Channel, Claim, ClaimedOwner, Consent, Family, Flag, Instruction, Issuer, MediaRef, Outcome,
                     Severity, Signal, now_iso, visible_name)
from .rulebook import RuleContext, evaluate, load_rulebook, make_signal

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_DIR = Path(__file__).resolve().parent.parent / "evidence"

LARGE_AMOUNT_INR = 10_00_000  # ₹10 lakh: above this, FRMU review is mandatory

# What a campaign-memory match adds to its sentence: the receiver it shares with the confirmed case, or the payment
# detail that changed since. The second is the case Bhawna raised on 23 Oct: a script already confirmed, now with a
# new account, which is a receiver nobody has reported yet. The officer can then help her report it.
_SLOT_EN = {"account": "the account", "vpa": "the UPI ID", "phone": "the phone number", "host": "the link"}
_SLOT_HI = {"account": "खाता", "vpa": "UPI आईडी", "phone": "फ़ोन नंबर", "host": "लिंक"}


def _memory_also(hit: dict) -> tuple[str, str]:
    same = hit.get("same")
    if same:
        kind = same["what"]
        return (f" It uses the same {_SLOT_EN[kind].removeprefix('the ')} as those cases.",
                f" इसमें वही {_SLOT_HI[kind]} है जो उन मामलों में था।")
    changed = [c["what"] for c in hit.get("changed", [])]
    if not changed:
        return "", ""
    en = " and ".join(_SLOT_EN[k] for k in changed)
    hi = " और ".join(_SLOT_HI[k] for k in changed)
    verb, verb_hi = ("is", "है") if len(changed) == 1 else ("are", "हैं")
    return f" This time {en} {verb} different.", f" इस बार इसमें {hi} अलग {verb_hi}।"


class Satyapan:
    def __init__(self, data_dir: Path = DATA_DIR, *, adapters: Optional[Adapters] = None, extractor=None, audio=None,
                 document=None, memory: Optional[CampaignMemory] = None, signer=None,
                 now: Optional[datetime | Callable[[], datetime]] = None, state_dir: Path = STATE_DIR,
                 forensics_service: Optional[str] = None):
        self.data_dir = Path(data_dir)
        self.book = load_rulebook(self.data_dir / "rules" / "rulebook.yaml")
        self.adapters = adapters or Adapters.mocks(self.data_dir / "mocks")
        self.extractor = extractor or RulesExtractor(bank_names=(self.book.bank_name,))
        self.audio = audio or default_audio_forensics()
        self.document = document or DocumentForensics()
        # Finale detectors run as a local service (satyapan-finale). Off unless a URL is given, so tests and the
        # terminal fallback behave exactly as before.
        url = forensics_service if forensics_service is not None else os.environ.get("SATYAPAN_FORENSICS_URL", "")
        self.remote = RemoteForensics(url) if url else None
        self._now = now
        self.memory = memory or CampaignMemory(self.data_dir / "mocks" / "campaign_memory.json", now=self.clock())
        self.signer = signer or LocalSigner(Path(state_dir) / "keys")
        self.cases: dict[str, Case] = {}
        self._inputs: dict[str, dict] = {}

    def clock(self) -> datetime:
        if callable(self._now):
            return self._now()
        return self._now or datetime.now(timezone.utc)

    def _official_details(self, claim: Claim) -> set[str]:
        """The message's account or UPI ID, when the bank's look-up lists it as an official collection account."""
        out: set[str] = set()
        p = claim.payee
        if p.account and self.adapters.name_lookup.lookup(p.account.value, p.ifsc.value if p.ifsc else None)["allow_listed"]:
            out.add(p.account.value)
        lookup_vpa = getattr(self.adapters.name_lookup, "lookup_vpa", None)
        if p.vpa and lookup_vpa and lookup_vpa(p.vpa.value)["allow_listed"]:
            out.add(p.vpa.value.lower())
        return out

    # ---------- intake ----------

    def open_case(self, flag: Flag, consent: Optional[Consent] = None) -> Case:
        case = Case(flag=flag, consent=consent or Consent())
        self.cases[case.id] = case
        self._inputs[case.id] = {"texts": [], "sender_number": None, "signature": None, "media_paths": {}, "forensics_sim": None, "picklist": None}
        return case

    def set_consent(self, case: Case, *, check: bool, report: bool = False, memory: bool = False, lang: str = "hi") -> Case:
        case.consent = Consent(check=check, report=report, memory=memory, recorded_at=now_iso(), read_aloud_lang=lang)
        return case

    def add_text(self, case: Case, text: str, *, source: str = "text", sender_number: Optional[str] = None,
                 signature: Optional[str] = None, kind: str = "text", filename: str = "message.txt") -> Case:
        """Text that already exists (a transcript, OCR output, a pasted SMS). `signature` is the bank's own content
        signature when the customer shows a notice the bank itself sent."""
        inp = self._inputs[case.id]
        inp["texts"].append((source, text))
        inp["sender_number"] = sender_number or inp["sender_number"]
        inp["signature"] = signature or inp["signature"]
        import hashlib
        case.media.append(MediaRef(filename=filename, kind=kind, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                                   bytes=len(text.encode("utf-8")), derived_text=text))
        return case

    def add_media(self, case: Case, path: Path, *, derived_text: Optional[str] = None, sender_number: Optional[str] = None,
                  signature: Optional[str] = None, language: str = "hi", channel: Optional[str] = None) -> Case:
        """A file the customer showed. Speech-to-text / OCR run unless `derived_text` is supplied. `channel` says how
        the audio reached the bank when the file cannot say it itself: "live-replay" for a recording made at the
        counter by playing the customer's phone into the console's microphone."""
        ref = ingest(Path(path), derived_text=derived_text, language=language)
        case.media.append(ref)
        inp = self._inputs[case.id]
        inp["media_paths"][ref.filename] = Path(path)
        if channel:
            inp.setdefault("media_channels", {})[ref.filename] = channel
        inp["sender_number"] = sender_number or inp["sender_number"]
        inp["signature"] = signature or inp["signature"]
        if ref.derived_text:
            inp["texts"].append(("transcript" if ref.kind in ("audio", "video") else "ocr", ref.derived_text))
        return case

    def add_picklist(self, case: Case, **fields) -> Case:
        """Claim-only mode: the officer ticks what the customer says she was told."""
        self._inputs[case.id]["picklist"] = fields
        return case

    def simulate_forensics(self, case: Case, result: dict) -> Case:
        """Rehearsal only: script the forensic result for this case. Labelled SIMULATED on every surface."""
        self._inputs[case.id]["forensics_sim"] = result
        return case

    # ---------- run ----------

    def build_claim(self, case: Case) -> Claim:
        inp = self._inputs[case.id]
        if inp["picklist"]:
            f = inp["picklist"]
            return claim_from_picklist(issuer=Issuer(f["issuer"]), instruction=Instruction(f["instruction"]),
                                       channel=Channel(f.get("channel", "UNKNOWN")), claimed_owner=ClaimedOwner(f.get("claimed_owner", "UNKNOWN")),
                                       account=f.get("account"), ifsc=f.get("ifsc"), vpa=f.get("vpa"), pressure=f.get("pressure"),
                                       has_passcode=f.get("has_passcode"), mentions_summons=bool(f.get("mentions_summons", False)))
        if not inp["texts"]:
            return Claim(source="none", text="")
        source = inp["texts"][0][0]
        text = "\n".join(t for _, t in inp["texts"])
        return ground(self.extractor.extract(text, source=source))

    def run(self, case: Case, claim: Optional[Claim] = None) -> Case:
        inp = self._inputs[case.id]
        claim = claim if claim is not None else self.build_claim(case)
        now = self.clock()
        sig_valid = self.adapters.signature.verify(claim.text, inp["signature"]) if inp["signature"] else None
        ctx = RuleContext(adapters=self.adapters, now=now, bank_name=self.book.bank_name, sender_number=inp["sender_number"],
                          media_signature_valid=sig_valid, media_hashes=[m.sha256 for m in case.media],
                          customer_ref=case.flag.customer_ref, flag_amount=case.flag.amount_inr,
                          flag_payee_account=case.flag.payee_account, flag_payee_ifsc=case.flag.payee_ifsc,
                          flag_payee_vpa=case.flag.payee_vpa)
        signals: list[Signal] = evaluate(self.book, claim, ctx)

        # F3: forensics on each media file (or the scripted rehearsal result)
        for m in case.media:
            path = inp["media_paths"].get(m.filename)
            if inp["forensics_sim"] and m.kind in ("audio", "video", "image", "pdf"):
                signals.append(to_signal(self.book, SimulatedForensics(inp["forensics_sim"]).analyse(path or Path(m.filename), claim.language_hint)))
            elif path and m.kind in ("audio", "video") and self.remote is not None:
                # finale detectors: a video gets a face check and a voice check, each its own F3 signal
                signals.extend(to_signal(self.book, r) for r in self.remote.analyse_all(path, m.kind))
            elif path and m.kind in ("audio", "video"):
                channel = inp.get("media_channels", {}).get(m.filename)
                if channel and getattr(self.audio, "accepts_channel", False):
                    signals.append(to_signal(self.book, self.audio.analyse(path, claim.language_hint, channel=channel)))
                else:
                    signals.append(to_signal(self.book, self.audio.analyse(path, claim.language_hint)))
            elif path and m.kind in ("image", "pdf"):
                signals.append(to_signal(self.book, self.document.analyse(path)))

        # F4: campaign memory
        hit = self.memory.match(claim, [m.sha256 for m in case.media], [m.perceptual_hash for m in case.media if m.perceptual_hash],
                                official=self._official_details(claim))
        if hit:
            also_en, also_hi = _memory_also(hit)
            signals.append(make_signal(self.book, "R-CAMPAIGN-MATCH", {"evidence_key": "memory:template", "n": hit["entry"]["count"],
                                                                     "entry_id": hit["entry"]["id"], "how": hit["how"], "score": hit["score"],
                                                                     "changed": hit.get("changed", []), "same": hit.get("same"),
                                                                     "also_en": also_en, "also_hi": also_hi}))

        # F5: the bank's own flag, as context
        signals.append(Signal(rule_id="R-BANK-FLAG", family=Family.F5, severity=Severity.INFO, evidence_key="flag",
                              reason_en=f"Bank flag: {case.flag.reason}", reason_hi=f"बैंक फ़्लैग: {case.flag.reason}",
                              citation="bank EWS / FRM rule", citation_verified=True, rule_version=f"rulebook-{self.book.version}",
                              detail={"can_be_second": False, "amount_inr": case.flag.amount_inr}))

        case.claim = claim
        case.verdict = fuse(claim, signals)
        return case

    # ---------- outputs ----------

    def card(self, case: Case, lang: str = "hi") -> Card:
        if case.verdict is None or case.claim is None:
            raise ValueError("run the case first")
        return build_card(case.verdict, case.claim, lang)

    def review_triggers(self, case: Case) -> list[str]:
        """Conditions that make FRMU review mandatory before any high-impact action."""
        t = []
        if case.flag.amount_inr >= LARGE_AMOUNT_INR:
            t.append("amount above the bank's limit")
        if case.claim and case.claim.source == "officer_picklist" and case.flag.amount_inr >= LARGE_AMOUNT_INR / 2:
            t.append("claim-only mode on a large amount")
        if case.verdict:
            fam = {s.family for s in case.verdict.signals if s.severity in (Severity.HARD, Severity.SOFT)}
            f3 = [s for s in case.verdict.signals if s.family == Family.F3 and s.severity == Severity.SOFT]
            if f3 and not (fam - {Family.F3, Family.F5}):
                t.append("forensics flagged but no rule fired (conflicting signals)")
        if any(d.action == "release" and case.verdict and case.verdict.outcome == Outcome.RED for d in case.decisions):
            t.append("officer released a RED case")
        return t

    def decide(self, case: Case, *, actor: str, action: str, note: str = "", co_signer: Optional[str] = None) -> Case:
        """Record a human decision. Releasing a RED needs a second person's co-sign; nothing here acts on its own."""
        from .models import Decision
        if action not in ("release", "hold", "escalate", "help_report", "strike_field"):
            raise ValueError(f"'{action}' is not a decision this system records")
        co_signer = visible_name(co_signer)   # whitespace, and anything invisible, is no co-sign
        if action == "release" and case.verdict and case.verdict.outcome == Outcome.RED:
            if not co_signer:
                raise PermissionError("releasing a RED case needs a manager co-sign")
            if co_signer.casefold() == actor.strip().casefold():
                raise PermissionError("a RED release needs a second person: the co-signer must be someone other than the deciding officer")
        case.decisions.append(Decision(actor=actor, action=action, note=(note + (f" (co-signed by {co_signer})" if co_signer else "")).strip()))
        case.status = {"release": "released", "hold": "held", "escalate": "escalated", "help_report": case.status, "strike_field": case.status}.get(action, case.status)
        return case

    def strike_field(self, case: Case, field: str, actor: str) -> Case:
        """Officer marks an extracted field as wrong; the rules that depended on it drop out and the case re-runs."""
        c = case.claim
        if c is None:
            return case
        if field == "issuer":
            c.claimed_issuer, c.issuer_span = Issuer.NONE, None
        elif field == "instruction":
            c.instruction, c.instruction_span = Instruction.NONE, None
        elif field in ("account", "ifsc", "vpa"):
            setattr(c.payee, field, None)
        elif field == "claimed_owner":
            c.payee.claimed_owner, c.payee.claimed_owner_span = ClaimedOwner.UNKNOWN, None
        self.decide(case, actor=actor, action="strike_field", note=f"struck {field}")
        inp = self._inputs[case.id]
        inp["picklist"] = None
        # Re-run on the corrected claim, passed explicitly. It used to be patched onto the shared engine for the length
        # of the re-run; with the finale forensics call in run() that window lasts seconds, and another case run in it
        # would have been judged on this case's claim.
        return self.run(case, claim=c)

    def evidence_pack(self, case: Case) -> dict:
        inp = self._inputs.get(case.id, {})
        manifest = {
            "satyapan_version": __version__,
            "generated_at": now_iso(),
            "case": case.model_dump(mode="json"),
            "rulebook": {"version": self.book.version, "sha256": self.book.sha256, "path": Path(self.book.path).name},
            "policy_version": POLICY_VERSION,
            "extractor": getattr(self.extractor, "name", type(self.extractor).__name__),
            "forensics": {"audio": self.audio.label.as_dict(), "document": self.document.label.as_dict()},
            "adapters": self.adapters.labels(),
            "inputs": {"sender_number": inp.get("sender_number"), "bank_signature_present": bool(inp.get("signature")),
                       "forensics_simulated": bool(inp.get("forensics_sim"))},
            "review_triggers": self.review_triggers(case),
        }
        return make_pack(manifest, self.signer)
