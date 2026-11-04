"""Real local Ed25519 signing, rehash attacks and pinned-key verification."""
import base64
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from proofcrew.attestation import sign_attestation, verify_attestation, load_attestation
from proofcrew.receipts import ReceiptChain, receipt_hash

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    deliverable = b"real locally generated test deliverable\n"
    chain = ReceiptChain()
    chain.append("planner", "plan", {"task": "offline local signature regression"})
    chain.append("crew", "final", {"deliverable_sha256": hashlib.sha256(deliverable).hexdigest()})
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return chain.receipts, deliverable, private, public


class TestAttestation(unittest.TestCase):
    def test_signed_package_accepts_with_pinned_public_key(self):
        receipts, deliverable, private, public = fixture()
        self.assertEqual(verify_attestation(receipts, deliverable, sign_attestation(receipts, deliverable, private), public), [])

    def test_rehashed_entire_chain_still_fails_signed_root(self):
        receipts, deliverable, private, public = fixture()
        signed = sign_attestation(receipts, deliverable, private)
        forged = copy.deepcopy(receipts)
        forged[0]["payload"]["task"] = "forged"
        forged[0]["hash"] = receipt_hash(forged[0])
        forged[1]["prev_hash"] = forged[0]["hash"]
        forged[1]["hash"] = receipt_hash(forged[1])
        self.assertTrue(verify_attestation(forged, deliverable, signed, public))

    def test_wrong_trusted_key_and_deliverable_rejected(self):
        receipts, deliverable, private, public = fixture()
        signed = sign_attestation(receipts, deliverable, private)
        wrong = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.assertTrue(verify_attestation(receipts, deliverable, signed, wrong))
        self.assertTrue(verify_attestation(receipts, b"modified", signed, public))

    def test_corrupt_signature_and_malformed_package_rejected(self):
        receipts, deliverable, private, public = fixture()
        signed = sign_attestation(receipts, deliverable, private)
        forged = copy.deepcopy(signed)
        forged["signature_base64"] = base64.b64encode(bytes(64)).decode("ascii")
        self.assertTrue(verify_attestation(receipts, deliverable, forged, public))
        forged["signature_base64"] = "not base64!"
        self.assertTrue(verify_attestation(receipts, deliverable, forged, public))
        forged["extra"] = "unexpected"
        self.assertTrue(verify_attestation(receipts, deliverable, forged, public))

    def test_refuses_empty_chain_and_wrong_final_digest(self):
        receipts, deliverable, private, public = fixture()
        with self.assertRaises(ValueError):
            sign_attestation([], deliverable, private)
        with self.assertRaises(ValueError):
            sign_attestation(receipts, b"wrong", private)

    def test_cli_sign_verify_and_tamper(self):
        receipts, deliverable, private, public = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            chain_path, doc, priv, pub, sig = [p / name for name in ("receipts.jsonl", "deliverable.md", "private.pem", "public.pem", "signed.json")]
            chain_path.write_text("".join(json.dumps(r) + "\n" for r in receipts), encoding="utf-8")
            doc.write_bytes(deliverable)
            priv.write_bytes(private)
            pub.write_bytes(public)
            def call(*args):
                return subprocess.run([sys.executable, str(ROOT / "attest_receipts.py"), *map(str, args)], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(call("sign", chain_path, doc, priv, sig).returncode, 0)
            self.assertEqual(call("verify", chain_path, doc, sig, pub).returncode, 0)
            self.assertNotEqual(call("sign", chain_path, doc, priv, sig).returncode, 0)
            doc.write_bytes(b"modified")
            self.assertNotEqual(call("verify", chain_path, doc, sig, pub).returncode, 0)

    def test_duplicate_attestation_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"statement":{},"statement":{},"signature_base64":""}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_attestation(path)


if __name__ == "__main__":
    unittest.main()
