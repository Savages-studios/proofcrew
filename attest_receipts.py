#!/usr/bin/env python3
"""Sign or independently verify a completed ProofCrew evidence package.

Sign: python attest_receipts.py sign RECEIPTS DELIVERABLE PRIVATE_KEY OUT
Verify: python attest_receipts.py verify RECEIPTS DELIVERABLE ATTESTATION TRUSTED_PUBLIC_KEY

Key files are operator-managed; no keys are generated or committed here.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from proofcrew.attestation import load_attestation, sign_attestation, verify_attestation
from proofcrew.receipts import load_receipts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("sign", "verify"):
        command = sub.add_parser(operation)
        command.add_argument("receipts")
        command.add_argument("deliverable")
        command.add_argument("evidence_or_key")
        command.add_argument("output_or_key")
    args = parser.parse_args(argv)
    try:
        receipts = load_receipts(args.receipts)
        deliverable = Path(args.deliverable).read_bytes()
        if args.operation == "sign":
            key = Path(args.evidence_or_key).read_bytes()
            attestation = sign_attestation(receipts, deliverable, key)
            with open(args.output_or_key, "x", encoding="utf-8") as fh:
                json.dump(attestation, fh, sort_keys=True, indent=2)
                fh.write("\n")
            print("ATTESTATION SIGNED (key identity must be independently trusted)")
        else:
            attestation = load_attestation(args.evidence_or_key)
            key = Path(args.output_or_key).read_bytes()
            problems = verify_attestation(receipts, deliverable, attestation, key)
            if problems:
                print("ATTESTATION INVALID: " + "; ".join(problems), file=sys.stderr)
                return 1
            print("ATTESTATION VALID (signed bytes and pinned key; not model factuality)")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print("ATTESTATION ERROR: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
