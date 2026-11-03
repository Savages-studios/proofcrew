# ProofCrew signed evidence export (review-only)

This independent opt-in capability makes the final hash-chain root and exact deliverable bytes independently verifiable against a **trusted, separately distributed Ed25519 public key**. The original `verify_receipts.py` stays standard-library-only and continues to verify unkeyed hash-chain consistency. It cannot authenticate the producer by itself. The new signer/verifier requires `cryptography>=42` and runs offline.

After a real ProofCrew run, an operator may sign existing `receipts.jsonl` and `deliverable.md` with a separately managed Ed25519 PKCS#8 PEM private key:

```bash
python attest_receipts.py sign proofcrew-out/receipts.jsonl proofcrew-out/deliverable.md /private/operator-ed25519.pem proofcrew-out/attestation.json
python attest_receipts.py verify proofcrew-out/receipts.jsonl proofcrew-out/deliverable.md proofcrew-out/attestation.json /trusted/operator-ed25519-public.pem
```

The verifier **never accepts a public key supplied by the attestation**. The trusted key must be acquired through an independently authenticated channel. The statement binds a domain-separated Ed25519 signature to the receipt count, terminal chain hash, final deliverable SHA-256, and SHA-256 of the signing key's DER SPKI. It rejects altered outputs, fully rehashed chains, incorrect keys, and malformed signatures. It does not authenticate factual correctness, provider settlement, identity of a legal entity, or the integrity of the signing machine. No secrets, provider calls, external spend, or real customer receipts are included in the tests. This is not yet a deployed multi-tenant service, key rotation system, or enterprise contract.

This is an independent evidence-export capability in ProofCrew, **not** the still-pending Tights-approved AgentPay OEM architecture. Keep draft unmerged pending review and acceptance.
