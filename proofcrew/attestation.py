"""Offline independently pinned Ed25519 attestations for ProofCrew runs.

Signature authenticates designated signing key and exact chain/deliverable;
it does not certify model claims, source truth or financial settlement.
"""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from .receipts import verify_receipts

DOMAIN = b"proofcrew:attestation:ed25519:v1\x00"


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _key_id(key: Ed25519PublicKey) -> str:
    der = key.public_bytes(encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()


def _statement(receipts: list[dict], deliverable: bytes, key: Ed25519PublicKey) -> dict:
    if not receipts:
        raise ValueError("cannot attest an empty receipt chain")
    failures = verify_receipts(receipts)
    if failures:
        raise ValueError("receipt chain invalid: " + "; ".join(failures))
    final = receipts[-1]
    if final.get("kind") != "final" or final.get("actor") != "crew":
        raise ValueError("last receipt is not a crew final receipt")
    digest = hashlib.sha256(deliverable).hexdigest()
    if final.get("payload", {}).get("deliverable_sha256") != digest:
        raise ValueError("deliverable does not match final receipt")
    return {
        "version": 1,
        "algorithm": "Ed25519",
        "key_id_sha256_spki": _key_id(key),
        "receipt_count": len(receipts),
        "terminal_receipt_hash": final["hash"],
        "deliverable_sha256": digest,
    }


def sign_attestation(receipts: list[dict], deliverable: bytes, private_key_pem: bytes) -> dict:
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("an Ed25519 private key is required")
    statement = _statement(receipts, deliverable, key.public_key())
    signature = key.sign(DOMAIN + _canonical(statement))
    return {"statement": statement, "signature_base64": base64.b64encode(signature).decode("ascii")}


def verify_attestation(receipts: list[dict], deliverable: bytes, attestation: dict, trusted_public_key_pem: bytes) -> list[str]:
    """Never trust an embedded key; the caller supplies a pinned public key."""
    try:
        key = serialization.load_pem_public_key(trusted_public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            return ["trusted public key is not Ed25519"]
        expected = _statement(receipts, deliverable, key)
        if not isinstance(attestation, dict) or set(attestation) != {"statement", "signature_base64"}:
            return ["attestation has unexpected fields"]
        if attestation["statement"] != expected:
            return ["attestation statement does not match trusted key, chain, or deliverable"]
        encoded = attestation["signature_base64"]
        if not isinstance(encoded, str):
            return ["signature must be base64 text"]
        signature = base64.b64decode(encoded, validate=True)
        if len(signature) != 64:
            return ["invalid Ed25519 signature length"]
        key.verify(signature, DOMAIN + _canonical(expected))
        return []
    except (ValueError, TypeError, KeyError, InvalidSignature) as exc:
        return ["attestation verification failed: " + type(exc).__name__]


def load_attestation(path: str | Path) -> dict:
    """Reject ambiguous duplicate keys and nonfinite JSON values."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate attestation key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("nonfinite JSON value: " + value)

    with open(path, encoding="utf-8") as fh:
        return json.load(fh, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
