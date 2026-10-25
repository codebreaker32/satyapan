"""Campaign memory (F4): fingerprints of analyst-confirmed cases, matched by exact hash, perceptual hash, the money
trail or claim-text similarity. Only entries confirmed by two people count, and entries expire after 90 days, so a
RED from Satyapan can never feed back into itself.

Text is compared the way the extractor reads it: on the normalised copy (`normalize.normalise`), so a look-alike
letter, a zero-width space or leetspeak is the same word, and two ways at once. Word overlap holds up when words are
left out; overlap of four-character runs holds up when words are misspelt. Measured on 23 Oct against the repo's own
data: the seeded ED summons with homoglyphs and zero-width spaces scored 0.21 on raw word overlap and 1.00 folded,
and a misspelt copy scored 0.68 on words and 0.86 on character runs, while no unrelated scenario or variant scored
above 0.21 on either. A reworded or translated copy still scores about 0.25 on both and is missed; that needs a
meaning-level model, which this module does not have.

The money trail is matched separately, and before the text. An account, a UPI ID or a phone number that an earlier
confirmed case paid or called is the same receiver whatever the words around it say. Every number is still left out
of the TEXT comparison, so a copied script with a new account keeps matching, and the match then says what changed.

A reworded or translated copy shares neither words nor character runs with the stored scam, so a third layer
compares MEANING, with a multilingual sentence-embedding model (paraphrase-multilingual-MiniLM-L12-v2, Apache-2.0,
run on CPU through fastembed). It is asked only when the two text layers found nothing, and it counts only above a
threshold that `satyapan calibrate-memory` sets just above the highest score of any message in the repo that is not
a copy (data/eval/memory_calibration.json). With the model or the calibration absent, the layer is skipped.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .extract import DESPACE_LEXICON, RE_ACCOUNT, RE_ACCOUNT_BARE, RE_PHONE, RE_URL, RE_VPA
from .models import Claim, identity_key
from .normalize import normalise

STOP = set("the a an to of and or is are be in on at for this that you your with from by will please our we us it "
           "hai hain ka ki ke ko se aur mein par ye yeh woh aap aapka aapki apni apna kar karein hi bhi ne".split())
TOKEN = re.compile(r"[\wऀ-ॿ]+")
# The parts of a message that change from copy to copy, taken out before the character runs are compared.
_MASK_URL = re.compile(r"\b(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?", re.I)
_MASK_VPA = re.compile(r"\b[a-z0-9._-]+@[a-z][a-z0-9]+\b", re.I)
_MASK_NUM = re.compile(r"\d[\d\s,./-]*")
_MASK_PUNCT = re.compile(r"[^\w#ऀ-ॿ]+")
GRAM = 4
# A money-trail value that identifies nobody: official web addresses and the 1600 series banks call from. A scam
# that copies a bank's real SMS carries its real helpline, and that must not make the bank's next real SMS "seen".
OFFICIAL_HOSTS = (".gov.in", ".nic.in", ".bank.in")
SLOT_WORDS = {"account": ("account", "खाता"), "vpa": ("UPI ID", "UPI आईडी"), "phone": ("phone number", "फ़ोन नंबर"),
              "host": ("link", "लिंक")}


MEANING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_ROOT = Path(__file__).resolve().parent.parent
FASTEMBED_DIR = _ROOT / "vendor" / "models" / "fastembed"
MEANING_CALIBRATION = _ROOT / "data" / "eval" / "memory_calibration.json"


def _fold(text: str) -> str:
    return normalise(text, DESPACE_LEXICON).text


class MeaningModel:
    """Sentence vectors for whole messages, cached by text, compared by cosine similarity."""

    def __init__(self, model):
        self.model = model
        self._vectors: dict[str, object] = {}

    def vector(self, text: str):
        key = _fold(text)
        if key not in self._vectors:
            self._vectors[key] = next(iter(self.model.embed([key])))
        return self._vectors[key]

    @staticmethod
    def cosine(a, b) -> float:
        import numpy as np
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


@lru_cache(maxsize=1)
def meaning_model() -> Optional[MeaningModel]:
    """The meaning model off disk (`satyapan setup-models` fetches it), loaded once per process, or None."""
    if not FASTEMBED_DIR.exists():
        return None
    try:
        from fastembed import TextEmbedding
        return MeaningModel(TextEmbedding(MEANING_MODEL_NAME, cache_dir=str(FASTEMBED_DIR), local_files_only=True))
    except Exception:  # noqa: BLE001 - not installed or not downloaded: the layer is skipped, never a crash
        return None


def same_structure(claim: Claim, entry: dict) -> bool:
    """The message names the same body as the confirmed case, as the extractor reads both. Requiring the same demand
    as well was measured on 23 Oct and only lost copies the extractor read a different instruction out of (8 of 14
    reworded copies caught on the body alone, 6 with the demand too, the same highest negative either way)."""
    issuer = entry.get("issuer")
    return bool(issuer) and issuer != "NONE" and claim.claimed_issuer.value == issuer


def meaning_threshold() -> Optional[float]:
    try:
        return float(json.loads(MEANING_CALIBRATION.read_text(encoding="utf-8"))["threshold"])
    except Exception:  # noqa: BLE001 - not calibrated: the layer is skipped
        return None


def tokens(text: str) -> set[str]:
    out = set()
    for t in TOKEN.findall(text.lower()):
        if len(t) < 3 or any(ch.isdigit() for ch in t) or t in STOP:
            continue
        out.add(t)
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def hamming_hex(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1") if a and b and len(a) == len(b) else 99


def grams(text: str) -> set[str]:
    """Four-character runs of the folded text, with links, UPI IDs and every number masked out."""
    t = _fold(text).lower()
    t = _MASK_VPA.sub(" ", _MASK_URL.sub(" ", t))
    t = _MASK_PUNCT.sub(" ", _MASK_NUM.sub("#", t))
    t = " " + re.sub(r"\s+", " ", t).strip() + " "
    return {t[i:i + GRAM] for i in range(len(t) - GRAM + 1)} if len(t) > GRAM else set()


def _host(url: str) -> str:
    return url.split("//")[-1].split("/")[0].lower()


def _identifies(kind: str, value: str) -> bool:
    if kind == "host":
        return not value.endswith(OFFICIAL_HOSTS)
    if kind == "phone":
        return not value.startswith("1600")
    return True


def slots_of_text(text: str) -> dict[str, list[str]]:
    """The money trail a stored template carries, read with the extractor's own patterns."""
    t = _fold(text)
    accounts = [re.sub(r"[\s-]", "", m.group(1)) for m in RE_ACCOUNT.finditer(t)]
    accounts += [m.group(1) for m in RE_ACCOUNT_BARE.finditer(t) if m.group(1) not in accounts]
    vpas = [m.group(1).lower() for m in RE_VPA.finditer(t) if not re.match(r"\.[a-z]", t[m.end():m.end() + 2], re.I)]
    phones = [m.group(1)[-10:] for m in RE_PHONE.finditer(t)]
    hosts = [_host(m.group(0)) for m in RE_URL.finditer(t) if "@" not in t[max(0, m.start() - 1):m.start()]]
    return {"account": accounts, "vpa": vpas, "phone": phones, "host": hosts}


def slots_of_claim(claim: Claim) -> dict[str, list[str]]:
    """The money trail of the message being checked, from the fields the extractor grounded."""
    p = claim.payee
    return {"account": [p.account.value] if p.account else [], "vpa": [p.vpa.value.lower()] if p.vpa else [],
            "phone": [claim.caller_number.value[-10:]] if claim.caller_number else [],
            "host": [_host(u.value) for u in claim.urls]}


class CampaignMemory:
    def __init__(self, path: Path, now: Optional[datetime] = None, ttl_days: int = 90, text_threshold: float = 0.45,
                 phash_threshold: int = 10, gram_threshold: float = 0.5, meaning: Optional[bool] = None):
        self.path = Path(path)
        self.now = now or datetime.now(timezone.utc)
        self.ttl, self.text_threshold, self.phash_threshold = timedelta(days=ttl_days), text_threshold, phash_threshold
        self.gram_threshold = gram_threshold
        # The meaning layer runs when its calibration exists, unless the caller turns it off (`meaning=False`).
        self.meaning_threshold = None if meaning is False else meaning_threshold()
        self.entries: list[dict] = json.loads(self.path.read_text(encoding="utf-8"))["entries"] if self.path.exists() else []
        for e in self.entries:
            # recomputed rather than trusted from the file, so an entry saved before folding compares like a new one
            e["tokens"] = sorted(tokens(_fold(e.get("template_text", ""))))
            e.setdefault("slots", slots_of_text(e.get("template_text", "")))
        # Kept off the entry so the API and the saved file never carry a few thousand character runs. Keyed by the
        # text, not the id: a demo reset puts the entries back and a later proposal can reuse an id.
        self._grams: dict[str, set[str]] = {}

    def _grams_of(self, e: dict) -> set[str]:
        text = e.get("template_text", "")
        if text not in self._grams:
            self._grams[text] = grams(text)
        return self._grams[text]

    def _live(self) -> list[dict]:
        out = []
        for e in self.entries:
            if e.get("status") != "confirmed":
                continue
            last = datetime.fromisoformat(e.get("last_seen", e["first_seen"]))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if self.now - last <= self.ttl:
                out.append(e)
        return out

    def match(self, claim: Claim, sha256s: list[str] = (), phashes: list[str] = (), *,
              official: frozenset[str] | set[str] = frozenset()) -> Optional[dict]:
        """The confirmed case this message repeats, if any, how it was matched, and what changed since.

        `official` holds the message's own account or UPI ID when the bank's look-up says it is an official
        collection account. A message whose every payment detail is official is the real notice a scam once
        copied, not the copy, so the text alone may not call it "seen before"; see the copy guard below.
        """
        mine = slots_of_claim(claim)
        live = self._live()
        for e in live:
            if set(sha256s) & set(e.get("sha256s", [])):
                return {"entry": e, "how": "exact hash", "score": 1.0, "changed": []}
            for ph in phashes:
                for eph in e.get("phashes", []):
                    if hamming_hex(ph, eph) <= self.phash_threshold:
                        return {"entry": e, "how": "perceptual hash", "score": 1.0, "changed": []}
        # The money trail: the same receiver as a confirmed case, whatever the words say.
        for e in live:
            theirs = e.get("slots") or {}
            for kind in ("account", "vpa", "phone"):
                same = {v for v in mine[kind] if _identifies(kind, v) and v not in official} & set(theirs.get(kind, []))
                if same:
                    return {"entry": e, "how": f"same {SLOT_WORDS[kind][0]}", "score": 1.0, "changed": [],
                            "same": {"what": kind, "value": sorted(same)[0]}}
        # The words: folded word overlap, or overlap of character runs, whichever holds up better.
        ctoks, cgrams = tokens(_fold(claim.text)), grams(claim.text)
        best, best_score, best_how = None, 0.0, ""
        for e in live:
            words = jaccard(ctoks, set(e["tokens"]))
            runs = jaccard(cgrams, self._grams_of(e))
            passed = ([(words, "claim text")] if words >= self.text_threshold else []) + \
                     ([(runs, "similar text")] if runs >= self.gram_threshold else [])
            if not passed:
                continue
            score, how = max(passed, key=lambda p: (p[0], p[1] == "claim text"))
            if score > best_score:
                best, best_score, best_how = e, score, how
        # The meaning: asked only when no text layer matched, only against confirmed cases that name the SAME body
        # and make the SAME demand as this message, and counted only above the calibrated threshold. The structure
        # is what keeps it a "seen before": a sentence model alone scores every digital-arrest script close to every
        # other, and a different CBI script is not the ED campaign the bank confirmed.
        if best is None and self.meaning_threshold is not None:
            same = [e for e in live if same_structure(claim, e)]
            model = meaning_model() if same else None
            if model is not None:
                mine_v = model.vector(claim.text)
                score, e = max(((model.cosine(mine_v, model.vector(e.get("template_text", ""))), e) for e in same),
                               key=lambda p: p[0])
                if score >= self.meaning_threshold:
                    best, best_score, best_how = e, score, "similar meaning (model)"
        if best is None:
            return None
        # The copy guard. A scam that copies a real notice word for word matches the real notice too, and the one
        # thing that separates them is the payment detail. When every detail this message carries is official
        # (an allow-listed account, a .gov.in / .nic.in / .bank.in link, a 1600 number), it is the original.
        details = [(k, v) for k in ("account", "vpa", "phone", "host") for v in mine[k]]
        if details and all(v in official or not _identifies(k, v) for k, v in details):
            return None
        return {"entry": best, "how": best_how, "score": round(best_score, 2), "changed": self._changed(mine, best)}

    @staticmethod
    def _changed(mine: dict[str, list[str]], e: dict) -> list[dict]:
        """Which payment details the message carries in place of the ones the confirmed case had."""
        theirs = e.get("slots") or {}
        out = []
        for kind in ("account", "vpa", "phone", "host"):
            now = [v for v in mine.get(kind, []) if _identifies(kind, v)]
            before = [v for v in theirs.get(kind, []) if _identifies(kind, v)]
            if now and before and not set(now) & set(before):
                out.append({"what": kind, "now": now[0], "before": before[0]})
        return out

    def propose(self, claim: Claim, analyst: str, sha256s: list[str] = (), phashes: list[str] = (), note: str = "") -> dict:
        """Two-person rule: a proposal stays pending until a second analyst approves it."""
        stamp = self.now.isoformat(timespec="seconds")
        e = {"id": f"CM-{len(self.entries) + 1:04d}", "template_text": claim.text[:600],
             "tokens": sorted(tokens(_fold(claim.text))), "slots": slots_of_claim(claim),
             "sha256s": list(sha256s), "phashes": list(phashes), "issuer": claim.claimed_issuer.value,
             "instruction": claim.instruction.value, "count": 1, "first_seen": stamp, "last_seen": stamp,
             "status": "pending", "approvals": [analyst], "note": note}
        self.entries.append(e)
        self.save()
        return e

    def approve(self, entry_id: str, analyst: str) -> dict:
        e = next((x for x in self.entries if x["id"] == entry_id), None)
        if e is None:
            raise KeyError(entry_id)
        # The same analyst under another spelling (different case, a Cyrillic а, an invisible mark) counts once, the
        # way the RED co-sign compares names. A raw-string compare let one person confirm their own entry.
        if identity_key(analyst) not in {identity_key(a) for a in e["approvals"]}:
            e["approvals"].append(analyst)
        if len({identity_key(a) for a in e["approvals"]} - {None}) >= 2:
            e["status"] = "confirmed"
        self.save()
        return e

    def save(self) -> None:
        self.path.write_text(json.dumps({"entries": self.entries}, indent=2, ensure_ascii=False), encoding="utf-8")
