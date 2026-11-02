# proofcrew — Ground Truth

**Last verified:** 2026-11-01 (live API state; build/submission record 2026-10-30/31)
**Canonical branch:** main @ d965bf9f3d

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

- **Head:** `d965bf9f3d`. Tree = 17 blobs.
- **Open PRs:** none.
- **Tests: 15/15 pass** — re-run personally by Tights, including
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

## Merged in the 2026-11-01 train

Nothing.

## Parked PRs

None open.

## Where it is going

No direction ruled beyond the pending late-entry request. The repo,
demo, and video stand as portfolio proof of the estate's "proof is
what we do" thesis either way.

## Estate rule

Update this file after any significant repo change. No claims without verification.
