"""Integrations. Every adapter has a `label` saying what it mocks, who owns the real one and how it is reached.

In this build the issuer portals and bank systems are mocked from JSON under data/mocks/. The officer console
shows each label, so nobody mistakes a mock for a live lookup.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol

DEFAULT_MOCKS = Path(__file__).resolve().parent.parent / "data" / "mocks"


@dataclass(frozen=True)
class Label:
    name: str
    production_source: str
    owner: str
    route: str
    mock: bool = True

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_date(s: str, default: datetime) -> datetime:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return default


# ---------------- ED verify-summon ----------------

class EDVerify(Protocol):
    label: Label
    def verify(self, summons_no: str, passcode: str, issue_date: Optional[str], now: datetime) -> dict: ...


class MockEDVerify:
    """Mock of enforcementdirectorate.gov.in/verify-summon. The real page has a CAPTCHA and no API, so in
    production this is a guided manual check (about 1-2 minutes) or a bilateral arrangement with ED."""
    label = Label("ED verify-summon", "enforcementdirectorate.gov.in/verify-summon (CAPTCHA, no API)",
                  "Directorate of Enforcement", "guided manual check by the officer; bilateral API if ED agrees")

    def __init__(self, path: Path = DEFAULT_MOCKS / "ed_summons.json"):
        self.records = {r["summons_no"].upper(): r for r in _load(path)}

    def verify(self, summons_no: str, passcode: str, issue_date: Optional[str], now: datetime) -> dict:
        rec = self.records.get(summons_no.upper())
        issued = _parse_date(issue_date, now) if issue_date else (_parse_date(rec["issue_date"], now) if rec else None)
        if issued is not None:
            age = now - issued
            if age < timedelta(hours=24):
                return {"status": "NOT_YET", "hours_old": round(age.total_seconds() / 3600, 1)}
            if age > timedelta(days=180):
                return {"status": "EXPIRED", "days_old": age.days}
        if rec and rec["passcode"].upper() == passcode.upper():
            return {"status": "FOUND", "issued_by": rec.get("office", "")}
        return {"status": "NOT_FOUND"}


# ---------------- beneficiary name lookup ----------------

class NameLookup(Protocol):
    label: Label
    def lookup(self, account: str, ifsc: Optional[str]) -> dict: ...
    def lookup_vpa(self, vpa: str) -> dict: ...


class MockNameLookup:
    label = Label("Beneficiary name lookup", "Bank core banking / NPCI name lookup (RBI/2024-25/99, mandatory for RTGS/NEFT)",
                  "Bank operations", "read-only internal API")

    def __init__(self, path: Path = DEFAULT_MOCKS / "name_lookup.json"):
        d = _load(path)
        self.accounts = {k.replace(" ", ""): v for k, v in d["accounts"].items()}
        self.vpas = {k.strip().lower(): v for k, v in d.get("vpas", {}).items()}
        self.allow_list = {a.replace(" ", "") for a in d.get("official_allow_list", [])}

    def lookup(self, account: str, ifsc: Optional[str]) -> dict:
        acct = re.sub(r"\D", "", account)
        rec = self.accounts.get(acct)
        if rec is None:
            return {"status": "UNKNOWN", "holder_name": None, "holder_type": "UNKNOWN", "allow_listed": False}
        return {"status": "FOUND", "holder_name": rec["holder_name"], "holder_type": rec["holder_type"],
                "allow_listed": acct in self.allow_list}

    def lookup_vpa(self, vpa: str) -> dict:
        """The registered name behind a UPI ID, which a UPI app shows the payer before the money moves. Same shape
        as `lookup`, and the same mock: an ID the file does not hold is UNKNOWN, never guessed."""
        key = vpa.strip().lower()
        rec = self.vpas.get(key)
        if rec is None:
            return {"status": "UNKNOWN", "holder_name": None, "holder_type": "UNKNOWN", "allow_listed": False}
        return {"status": "FOUND", "holder_name": rec["holder_name"], "holder_type": rec["holder_type"],
                "allow_listed": key in self.allow_list}


# ---------------- outbound communications log ----------------

class OutboundLog(Protocol):
    label: Label
    def find(self, *, text: str, sender_number: Optional[str], customer_ref: str, now: datetime) -> dict: ...


class MockOutboundLog:
    """What the bank itself sent on logged channels (SMS, e-mail, IVR, official WhatsApp, in-app)."""
    label = Label("Outbound communications log", "Bank CRM / messaging gateway logs for centrally sent channels",
                  "Bank contact centre + IT", "read-only internal API; match by content hash or message id")

    def __init__(self, path: Path = DEFAULT_MOCKS / "outbound_log.json", rm_path: Path = DEFAULT_MOCKS / "rm_phones.json"):
        self.records = _load(path)
        for r in self.records:   # records may carry the sent text; hash it the same way incoming text is hashed
            r.setdefault("content_hash", self.content_hash(r.get("content_text", "")))
        self.rm_phones = {re.sub(r"\D", "", r["phone"])[-10:]: r for r in _load(rm_path)}

    @staticmethod
    def content_hash(text: str) -> str:
        norm = re.sub(r"\s+", " ", text.strip().lower())
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def find(self, *, text: str, sender_number: Optional[str], customer_ref: str, now: datetime) -> dict:
        h = self.content_hash(text)
        for r in self.records:
            if r.get("content_hash") == h and (not customer_ref or r.get("customer_ref") in (customer_ref, "*")):
                return {"found": True, "record": r, "rm_personal_phone": False}
        rm = self.rm_phones.get(re.sub(r"\D", "", sender_number or "")[-10:]) if sender_number else None
        return {"found": False, "record": None, "rm_personal_phone": rm is not None, "rm": rm}


# ---------------- ledger ----------------

class Ledger(Protocol):
    label: Label
    def credits(self, customer_ref: str, now: datetime, hours: int = 72) -> list[dict]: ...


class MockLedger:
    label = Label("Ledger credits", "Core banking ledger, credits to the customer's account", "Bank operations",
                  "read-only internal API, last 72 hours")

    def __init__(self, path: Path = DEFAULT_MOCKS / "ledger.json"):
        self.data = _load(path)

    def credits(self, customer_ref: str, now: datetime, hours: int = 72) -> list[dict]:
        out = []
        for c in self.data.get(customer_ref, []):
            when = datetime.fromisoformat(c["at"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if now - when <= timedelta(hours=hours):
                out.append(c)
        return out


# ---------------- I4C suspect registry ----------------

class SuspectRegistry(Protocol):
    label: Label
    def check(self, *, account: Optional[str] = None, vpa: Optional[str] = None, phone: Optional[str] = None) -> Optional[str]: ...


class MockSuspectRegistry:
    label = Label("I4C suspect registry", "NCRP 'Report & Check Suspect' / I4C Suspect Registry shared with banks",
                  "I4C (MHA)", "bank's existing registry feed")

    def __init__(self, path: Path = DEFAULT_MOCKS / "suspect_registry.json"):
        d = _load(path)
        self.accounts = {re.sub(r"\D", "", a) for a in d.get("accounts", [])}
        self.vpas = {v.lower() for v in d.get("vpas", [])}
        self.phones = {re.sub(r"\D", "", p)[-10:] for p in d.get("phones", [])}

    def check(self, *, account=None, vpa=None, phone=None) -> Optional[str]:
        if account and re.sub(r"\D", "", account) in self.accounts:
            return "account"
        if vpa and vpa.lower() in self.vpas:
            return "UPI ID"
        if phone and re.sub(r"\D", "", phone)[-10:] in self.phones:
            return "phone number"
        return None


# ---------------- the bank's own content signature ----------------

class BankSignature:
    """Demo stand-in for C2PA content credentials on the bank's own notices: HMAC-SHA256 over the message text.
    Production: the bank signs notices with C2PA and watermarks IVR audio; verification uses the bank's public key."""
    label = Label("Bank content signature", "C2PA content credentials on bank-issued notices (bank signing key)",
                  "Bank InfoSec", "public-key verification; demo uses HMAC with a shared demo key")

    def __init__(self, key: bytes = b"demo-bank-signing-key-not-for-production"):
        self.key = key

    def sign(self, text: str) -> str:
        return hmac.new(self.key, MockOutboundLog.content_hash(text).encode(), hashlib.sha256).hexdigest()

    def verify(self, text: str, signature: Optional[str]) -> Optional[bool]:
        if not signature:
            return None
        return hmac.compare_digest(self.sign(text), signature)


# ---------------- website registration (RDAP) ----------------

# Zones under which the name someone actually registers is the third label from the right: rbi.org.in, sbi.co.in.
_TWO_LEVEL_ZONES = {"co.in", "org.in", "net.in", "gov.in", "nic.in", "ac.in", "edu.in", "res.in", "firm.in", "gen.in",
                    "ind.in", "mil.in", "co.uk", "org.uk", "gov.uk", "com.au"}


def registrable_domain(host: str) -> str:
    """The name a registry holds a record for: 'echallan.parivahan.gov.in' -> 'parivahan.gov.in'."""
    labels = host.lower().strip(".").split(":")[0].split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_LEVEL_ZONES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def parse_rdap(doc: dict) -> dict:
    """The few facts the rules use from an RDAP domain record: when it was registered, who holds it, and whether the
    registry has put it on hold (a registry suspends a domain it has found abusive)."""
    events = {e.get("eventAction"): e.get("eventDate") for e in doc.get("events", [])}
    holder, registrar = "", ""
    for ent in doc.get("entities", []):
        card = (ent.get("vcardArray") or [None, []])[1]
        names = [x[3] for x in card if x and x[0] in ("org", "fn") and isinstance(x[3], str) and x[3].strip()]
        if "registrant" in (ent.get("roles") or []) and names:
            holder = names[0].strip()
        if "registrar" in (ent.get("roles") or []) and names:
            registrar = names[0].strip()
    status = [str(s) for s in doc.get("status", [])]
    return {"status": "FOUND", "registered": events.get("registration"), "holder": holder, "registrar": registrar,
            "held": any("hold" in s.lower() for s in status), "registry_status": status}


class SnapshotWebsiteRegistry:
    """RDAP answers recorded from the live registries, for the tests, the preflight and an offline demo. Each record
    carries the date it was read, so nothing recorded is shown as a live answer."""
    label = Label("Website registration look-up", "Domain registry RDAP records (rdap.org bootstrap to each registry)",
                  "Public internet (domain registries)", "HTTPS query when online; recorded answers when offline")

    def __init__(self, path: Path = DEFAULT_MOCKS / "web_registry.json"):
        d = _load(path) if Path(path).exists() else {}
        self.recorded_on = d.get("recorded_on", "")
        self.records = {k.lower(): v for k, v in d.get("domains", {}).items()}

    def lookup(self, domain: str) -> dict:
        rec = self.records.get(domain.lower())
        if rec is None:
            return {"status": "UNKNOWN", "source": "not recorded, and no live look-up was made"}
        return {**rec, "source": f"registry record read on {self.recorded_on}"}


class LiveWebsiteRegistry(SnapshotWebsiteRegistry):
    """The same look-up made live over HTTPS, with a short timeout and a cache. When the registry cannot be reached
    (no network) it falls back to the recorded answers, and to UNKNOWN beyond those, so a dead network
    never becomes a finding about a website."""
    label = Label(SnapshotWebsiteRegistry.label.name, SnapshotWebsiteRegistry.label.production_source,
                  SnapshotWebsiteRegistry.label.owner, SnapshotWebsiteRegistry.label.route, mock=False)

    def __init__(self, path: Path = DEFAULT_MOCKS / "web_registry.json", timeout: float = 3.0):
        super().__init__(path)
        self.timeout = timeout
        self.cache: dict[str, dict] = {}

    def lookup(self, domain: str) -> dict:
        import urllib.error
        import urllib.request
        domain = domain.lower()
        if domain in self.cache:
            return self.cache[domain]
        req = urllib.request.Request(f"https://rdap.org/domain/{domain}", headers={"Accept": "application/rdap+json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                rec = {**parse_rdap(json.loads(r.read().decode("utf-8"))), "source": "live registry look-up"}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return super().lookup(domain)
            rec = {"status": "NOT_FOUND", "source": "live registry look-up"}
        except Exception:  # noqa: BLE001 - offline or slow: the recorded answer, never a guess
            return super().lookup(domain)
        self.cache[domain] = rec
        return rec


# ---------------- bundle ----------------

@dataclass
class Adapters:
    ed_verify: MockEDVerify
    name_lookup: MockNameLookup
    outbound_log: MockOutboundLog
    ledger: MockLedger
    suspect_registry: MockSuspectRegistry
    signature: BankSignature
    website: SnapshotWebsiteRegistry = field(default_factory=SnapshotWebsiteRegistry)

    @classmethod
    def mocks(cls, mocks_dir: Path = DEFAULT_MOCKS, *, live_web: bool = False) -> "Adapters":
        registry = LiveWebsiteRegistry if live_web else SnapshotWebsiteRegistry
        return cls(
            ed_verify=MockEDVerify(mocks_dir / "ed_summons.json"),
            name_lookup=MockNameLookup(mocks_dir / "name_lookup.json"),
            outbound_log=MockOutboundLog(mocks_dir / "outbound_log.json", mocks_dir / "rm_phones.json"),
            ledger=MockLedger(mocks_dir / "ledger.json"),
            suspect_registry=MockSuspectRegistry(mocks_dir / "suspect_registry.json"),
            signature=BankSignature(),
            website=registry(mocks_dir / "web_registry.json"),
        )

    def labels(self) -> list[dict]:
        return [getattr(self, f).label.as_dict()
                for f in ("ed_verify", "name_lookup", "outbound_log", "ledger", "suspect_registry", "signature", "website")]
