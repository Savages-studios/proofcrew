"""Run and authenticate a completed crew result before exposing success."""
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .attestation import sign_attestation, verify_attestation
from .crew import run_crew


def load_signing_key(path):
    if not path:
        raise ValueError("PROOFCREW_SIGNING_KEY is not set to an Ed25519 private key PEM path")
    private = Path(path).read_bytes()
    key = serialization.load_pem_private_key(private, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("PROOFCREW_SIGNING_KEY must be an Ed25519 private key")
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public


def run_signed_crew(task, transport, config, tavily, keys):
    result = run_crew(task, transport, config, tavily)
    private, public = keys
    data = result.deliverable.encode("utf-8")
    attestation = sign_attestation(result.chain.receipts, data, private)
    problems = verify_attestation(result.chain.receipts, data, attestation, public)
    if problems:
        raise ValueError("attestation self-check failed: " + "; ".join(problems))
    return result, attestation
