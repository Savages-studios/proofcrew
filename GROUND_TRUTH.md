# proofcrew — Ground Truth

**Last verified:** 2026-11-03 (Tonight Sprint merge train — Tights first-hand local verification: diff read in full, pytest run on exact PR head + baseline control, post-merge tree proof; earlier sections carry their own dates)
**Canonical branch:** main @ 3db2fc19b19b8a5e6d7cde050acf212d4ae58035

## What this repo is

ProofCrew: a multi-model verification pipeline — a planner model
drafts, two worker models execute in parallel (one web-grounded),
a screener model cross-checks, and an adjudicator resolves only
disagreements — emitting a SHA-256 hash-chained receipt file that
anyone can re-verify with a stdlib-only script. Built for the
Nebius × NVIDIA Global AI Hackathon (Devpost), entered by Savage
individually. Public, MIT licensed. This repo postdates the
2026-10-29 estate audit and was not covered by it.

## Verified current state

- **Head:** `3db2fc19b19b8a5e6d7cde050acf212d4ae58035` — squash merge of PR #4. Tree = 23 blobs. (PR #3, the screener sources fix, was merged earlier; pre-train main was `7dfe2741`.)
- **Open PRs:** none (PR #4 merged 2026-11-03).
- **Tests (Tights local run, 2026-11-03, `pytest tests/ -q`):** **PR #4 head: 33 passed; baseline control on `7dfe2741`: 26 passed.** Zero regressions. (Earlier record: 15/15 at the 2026-10-30/31 build state; the suite has grown since.)
  after the Tavily transport patch.
- **Live runs:** two full runs against the Nebius Token Factory API
  (2026-10-30), each producing 8 receipts with a VALID hash chain;
  run #2 was web-grounded (Tavily) and adjudicated, with real
  citations.
- A public demo (recorded run #2, chain re-verified on every page
  load) and a public 88-second demo video exist and were verified
  live on 2026-10-30.

## Known defects / honest gaps

- **ProofCrew was never submitted to the hackathon** — verified
  first-hand 2026-10-30 (Devpost portfolio shows 0 projects; no
  confirmation mail exists). The submission task failed silently.
  A late-entry request was emailed to the hackathon manager on
  2026-10-31; no reply yet. The deadline (2026-10-30 10:00 AM PT)
  has passed.
- The demo URL rides a Cloudflare quick tunnel to the Oracle box;
  if the box or tunnel dies, the demo dies with it.
- Model-ID casing matters: the live API's exact IDs differ in case
  from the code defaults and must be passed via environment.

## Merged in the 2026-11-03 Tonight Sprint train

- **#4** — squash-merged at `3db2fc19b19b8a5e6d7cde050acf212d4ae58035` (tree proof PASS, 18 → 23 blobs). Independently verifiable signed evidence packages: domain-separated Ed25519 attestation over the exact receipt chain and deliverable digest, verified against a caller-pinned public key (embedded keys are never trusted), plus a clean-room checker CLI and JSON schema. Honest scope, stated in the code and docs: the signature authenticates the designated key and the exact bytes — not model claims, source truth, or settlement. New declared dependency: `cryptography>=42` (verification CLI itself remains stdlib-only). No production signing key exists or is claimed; fixtures are test-only.

## Parked PRs

None open.


## Where it is going

No direction ruled beyond the pending late-entry request. The repo,
demo, and video stand as portfolio proof of the estate's "proof is
what we do" thesis either way.

## Estate rule

Update this file after any significant repo change. No claims without verification.
