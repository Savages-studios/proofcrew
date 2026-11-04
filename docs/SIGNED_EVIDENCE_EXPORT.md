# ProofCrew signed evidence and real-run preparation

This capability makes the final hash-chain root and exact deliverable bytes independently verifiable against a **trusted, separately distributed Ed25519 public key**. The original `verify_receipts.py` stays standard-library-only and continues to verify unkeyed hash-chain consistency. It cannot authenticate the producer by itself. The new signer/verifier requires `cryptography>=42` and runs offline.

Normal CLI and web runs require `PROOFCREW_SIGNING_KEY`, sign and self-check the result before reporting success, and expose `attestation.json` alongside the deliverable and receipt chain. The public key must be independently pinned. An operator can also manually sign existing `receipts.jsonl` and `deliverable.md` with a separately managed Ed25519 PKCS#8 PEM private key:

```bash
python attest_receipts.py sign proofcrew-out/receipts.jsonl proofcrew-out/deliverable.md /private/operator-ed25519.pem proofcrew-out/attestation.json
python attest_receipts.py verify proofcrew-out/receipts.jsonl proofcrew-out/deliverable.md proofcrew-out/attestation.json /trusted/operator-ed25519-public.pem
```

The verifier **never accepts a public key supplied by the attestation**. The trusted key must be acquired through an independently authenticated channel. The statement binds a domain-separated Ed25519 signature to the receipt count, terminal chain hash, final deliverable SHA-256, and SHA-256 of the signing key's DER SPKI. It rejects altered outputs, fully rehashed chains, incorrect keys, and malformed signatures. It does not authenticate factual correctness, provider settlement, identity of a legal entity, or the integrity of the signing machine. No secrets, provider calls, external spend, or real customer receipts are included in the tests. This is not yet a deployed multi-tenant service, key rotation system, or enterprise contract.

## Prepare one live run

Install `requirements.txt` on the machine that will run it. Create and securely store an operator-managed Ed25519 key pair (do not commit the private key):

```bash
umask 077
openssl genpkey -algorithm Ed25519 -out "$HOME/proofcrew-ed25519.pem"
openssl pkey -in "$HOME/proofcrew-ed25519.pem" -pubout -out "$HOME/proofcrew-ed25519-public.pem"
export PROOFCREW_SIGNING_KEY="$HOME/proofcrew-ed25519.pem"
export TOKENFACTORY_API_KEY="your-token-factory-key"
python3 run.py "Write a short brief on Nebius Token Factory and how it serves NVIDIA models." --out proofcrew-out
python3 attest_receipts.py verify proofcrew-out/receipts.jsonl proofcrew-out/deliverable.md proofcrew-out/attestation.json "$HOME/proofcrew-ed25519-public.pem"
```

Obtain and export the real API key securely; the text above is an instruction, not a working credential. Set `TAVILY_API_KEY` separately for live grounding. The live call can incur provider charges and is not executed by the offline tests. Confirm the exact model IDs against the provider before running; IDs are case-sensitive. The verifier only authenticates the expected operator if its public key was pinned through an independent channel. Do not share the private key.
