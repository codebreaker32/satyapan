"""Signed evidence pack: a canonical JSON manifest (hashes, claim, signals, verdict, versions, consent, decisions)
plus a detached signature. Flip one byte and `verify_pack` fails.

Demo signer: a local Ed25519 key under evidence/keys/. Production: AWS KMS asymmetric key (Sign/Verify), with the
pack stored in S3 Object Lock for escalated cases. The manifest records SHA-256 of every media file so it can
support a Bharatiya Sakshya Adhiniyam s.63(4) certificate (the schedule fields are for counsel to confirm).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .adapters import Label

FORMAT = "satyapan-evidence/1"


def _normalise(obj):
    """JSON has one number type. A float with an integral value (3800000.0) is re-serialised as 3800000 by every
    JavaScript JSON library, so the canonical form uses the integer, or the same pack would fail verification after
    a round trip through a browser or a case system."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _normalise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalise(v) for v in obj]
    return obj


def canonical(obj) -> bytes:
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalSigner:
    label = Label("Evidence signer", "AWS KMS asymmetric key (ECC_NIST_P256, Sign/Verify); S3 Object Lock for escalated cases",
                  "Bank InfoSec", "KMS Sign API; the demo uses a local Ed25519 key pair")
    alg = "Ed25519"

    def __init__(self, key_dir: Path):
        key_dir.mkdir(parents=True, exist_ok=True)
        priv = key_dir / "evidence-signing.key"
        if priv.exists():
            self._key = serialization.load_pem_private_key(priv.read_bytes(), password=None)
        else:
            self._key = Ed25519PrivateKey.generate()
            priv.write_bytes(self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()))
            os.chmod(priv, 0o600)
        (key_dir / "evidence-signing.pub").write_bytes(
            self._key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))

    def public_key_b64(self) -> str:
        raw = self._key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    def sign(self, data: bytes) -> dict:
        return {"alg": self.alg, "value": base64.b64encode(self._key.sign(data)).decode(),
                "public_key": self.public_key_b64(), "signer": self.label.as_dict()}


class KMSSigner:
    """Production signer. Needs boto3 and a KMS key id; verification uses the key's DER public key."""
    label = Label("Evidence signer", "AWS KMS asymmetric key (ECC_NIST_P256)", "Bank InfoSec", "KMS Sign API", mock=False)
    alg = "ECDSA_SHA_256"

    def __init__(self, key_id: str, region: str = "ap-south-1"):
        import boto3  # optional dependency
        self.kms = boto3.client("kms", region_name=region)
        self.key_id = key_id

    def sign(self, data: bytes) -> dict:
        r = self.kms.sign(KeyId=self.key_id, Message=data, MessageType="RAW", SigningAlgorithm=self.alg)
        pub = self.kms.get_public_key(KeyId=self.key_id)["PublicKey"]
        return {"alg": self.alg, "value": base64.b64encode(r["Signature"]).decode(), "public_key": base64.b64encode(pub).decode(),
                "signer": self.label.as_dict(), "kms_key_id": self.key_id}

    def public_key_b64(self) -> str:
        """The key's DER public key, the one verification trusts (fetched once)."""
        if not hasattr(self, "_pub_b64"):
            self._pub_b64 = base64.b64encode(self.kms.get_public_key(KeyId=self.key_id)["PublicKey"]).decode()
        return self._pub_b64


def make_pack(manifest: dict, signer) -> dict:
    digest = sha256_hex(canonical(manifest))
    return {"format": FORMAT, "signed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "manifest": manifest, "manifest_sha256": digest, "signature": signer.sign(digest.encode())}


def verify_pack(pack: dict, trusted_public_key: str | None = None) -> tuple[bool, str]:
    """Return (ok, reason): the manifest hash must match, then the signature over that hash must verify.

    `trusted_public_key` is the bank's own evidence key (base64, as the signer writes it). A pack carries its signer's
    public key, so without this check anyone could alter a pack, re-sign it with a key of their own and have it
    verify; the API and the command line always pass the bank's key. It is optional only for callers that check a
    pack's internal consistency and nothing more.

    The reason is read by an officer, on screen, after the words "Verifies." or "Does not verify.", so every one
    of them is a plain sentence that says what was checked or what is wrong with the file in hand.
    """
    if not isinstance(pack, dict) or "format" not in pack:
        return False, "This file is not a Satyapan evidence pack. A pack is the JSON file downloaded from a case."
    if pack.get("format") != FORMAT:
        return False, (f"This pack was written in a format this build cannot check. It says {pack.get('format')!r} "
                       f"and this build checks {FORMAT!r}.")
    if not isinstance(pack.get("manifest"), dict):
        return False, "This pack has no manifest in it, so there is nothing to check the signature against."
    digest = sha256_hex(canonical(pack["manifest"]))
    if digest != pack.get("manifest_sha256"):
        return False, "The manifest was altered after signing. What is in the pack no longer matches the hash that was signed."
    sig = pack.get("signature")
    if not isinstance(sig, dict) or not sig.get("value"):
        return False, "This pack has no signature in it, so nothing shows who wrote it or that it is unchanged."
    if trusted_public_key is not None and not _same_key(sig.get("public_key"), trusted_public_key):
        return False, ("This pack was signed with a key that is not this bank's evidence key, so it cannot be "
                       "trusted, even though its manifest and signature agree with each other.")
    try:
        if sig.get("alg") == "Ed25519":
            Ed25519PublicKey.from_public_bytes(base64.b64decode(sig["public_key"])).verify(base64.b64decode(sig["value"]), digest.encode())
            return True, "The manifest matches its hash, and the Ed25519 signature over that hash is good."
        if sig.get("alg") == "ECDSA_SHA_256":
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec
            pub = serialization.load_der_public_key(base64.b64decode(sig["public_key"]))
            pub.verify(base64.b64decode(sig["value"]), digest.encode(), ec.ECDSA(hashes.SHA256()))
            return True, "The manifest matches its hash, and the ECDSA signature over that hash is good."
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False, "The signature does not match this manifest. The pack was signed by a different key, or it was changed after signing."
    if not sig.get("alg"):
        return False, "This pack's signature does not say how it was made, so this build cannot check it."
    return False, (f"This pack is signed with {sig.get('alg')!r}, which this build cannot check. "
                   "Satyapan signs with Ed25519 on the demo laptop and ECDSA P-256 through AWS KMS in the bank.")


def _same_key(given, trusted: str) -> bool:
    try:
        return isinstance(given, str) and base64.b64decode(given, validate=True) == base64.b64decode(trusted)
    except (ValueError, TypeError):
        return False


def load_pack(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_pack(pack: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
