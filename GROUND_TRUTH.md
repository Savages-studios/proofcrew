# proofcrew — Ground Truth

**Last verified:** 2026-11-09 (Pass 2 + D1 fix pass — full re-verification against the tree below: every component read in code, suite executed on the merged tree, PR state read from the GitHub API; the D1 sections were re-verified against the fixed tree and live server runs the same night)
**Canonical branch:** main @ b082236d3688bb4d9c0384ac3be75a1416fe4583 (post-PR #12 merge; this file's own commit sits on top)

## What this repo is

ProofCrew: a multi-model verification pipeline — a planner model
drafts, two worker models execute in parallel (one web-grounded),
a screener model cross-checks, and an adjudicator resolves only
disagreements — emitting a SHA-256 hash-chained receipt file that
anyone can re-verify, plus an optional Ed25519 attestation over the
chain and deliverable, verified against a caller-pinned public key.
Built for the Nebius × NVIDIA Global AI Hackathon (Devpost), entered
by Savage individually. Public, MIT licensed. Covered by the
2026-11-08 estate audit (`ops-web-cluster.md`): core verified
fail-closed at 44/44 tests; the audit's defects were all on the
demo surface (D1, D2 below).

## Verified current state

- **Head:** `b082236d3688bb4d9c0384ac3be75a1416fe4583` — merge of
  PR #12 (D3 GROUND_TRUTH Pass 2); the D1 fix lands on top of it via
  its own PR. Lineage since the previous GT: `f39bde74` (PR #5) →
  `33f1c67e` (PR #8, optional attestations wired into CLI and web
  runs) → `b5314311` (PR #9, model defaults pinned to live IDs) →
  `a6099ac2` (PR #11, D2 guard) → `b082236d` (PR #12).
- **Open PRs:** exactly one — **PR #10**, "Evolution: Independent
  multi-operator Ed25519 attestation quorum" (branch
  `evolution/proof-bound-20261105`). Unlanded. Its tests prove the
  rejection paths; no positive multi-operator acceptance test exists
  yet, which is the recorded condition for calling the quorum
  verified (fix plan §6.3).
- **Tests (executed 2026-11-09 on this exact tree, post-D1-fix):**
  `python3 -m pytest tests/ -q` → **71 passed**;
  `python3 -m unittest discover -s tests` → **70 tests, OK**.
  (The counts differ by one because pytest and unittest count one
  subtest-bearing test differently; both runners are fully green.
  Pre-D2 baseline on `b5314311` measured the same way: 44 passed;
  pre-D1-fix baseline on `b082236d`: 51 pytest / 50 unittest. The
  D1 fix added 20 tests in `tests/test_app_run_auth.py` and modified
  no existing test.)

## Component-by-component state

- **`proofcrew/crew.py`** — VERIFIED. Planner → two parallel
  workers → screener → cross-verification → adjudicator. A review
  counts as agreement only if it explicitly says "agree"; anything
  else, including an unparseable review, escalates
  (`verdict_of`/`needs_adjudication`). The screener's
  `evidence_sufficient` gates worker B's citations only on an
  explicit `false`. All model calls go through the
  `ChatTransport` protocol — no direct network code here.
- **`proofcrew/receipts.py`** — VERIFIED. SHA-256 hash chain over
  canonical JSON; `verify_receipts` returns the list of problems
  (empty = valid); `load_receipts` parses strictly.
- **`proofcrew/attestation.py`** — VERIFIED, fail-closed.
  Domain-separated Ed25519 signature over the receipt chain, the
  deliverable digest, and the signing key's id. Verification
  recomputes the expected statement from the **caller-pinned**
  public key — a key embedded in the package is never trusted —
  and rejects unexpected fields, bad signature length, and any
  statement mismatch. `load_attestation` rejects duplicate JSON
  keys and nonfinite values.
- **`proofcrew/signed_run.py`** — VERIFIED. Runs the crew, signs,
  then self-verifies the attestation before returning; a failed
  self-check raises. With no signing key configured the run is
  returned unsigned with `attestation=None` — labeled, never
  silently presented as signed (the web UI prints "Package is
  UNSIGNED" in that state).
- **`proofcrew/config.py`** — VERIFIED. Environment-only secrets;
  no key material in code (full-tree grep: no private keys). The
  default model IDs are the exact-case live IDs — planner
  `nvidia/Nemotron-3-Ultra-550b-a55b`, worker
  `nvidia/nemotron-3-super-120b-a12b`, screener
  `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` — and `tests/test_config.py`
  pins the defaults to the IDs documented in `.env.example`.
  Environment variables can still override every model ID.
- **`proofcrew/transport.py`** — VERIFIED. `TokenFactoryTransport`
  is the only model-call path (OpenAI-compatible Nebius Token
  Factory endpoint).
- **`proofcrew/tavily.py`** — VERIFIED. Optional grounding: with
  `TAVILY_API_KEY` unset, worker B runs ungrounded and the run
  reports `grounded_worker_b` accordingly — degradation is
  recorded, not hidden.
- **`run.py`** (CLI) — VERIFIED. Exit 2 with a named error when
  `TOKENFACTORY_API_KEY` is unset or the signing key is bad —
  fail-closed at both entry points. Writes `deliverable.md` +
  `receipts.jsonl` and self-checks the chain before exiting.
- **`verify_receipts.py` / `attest_receipts.py`** — VERIFIED
  standalone checkers. `verify_receipts.py` is standard-library
  only (imports `proofcrew.receipts` only); `attest_receipts.py`
  additionally needs `cryptography` for Ed25519.
- **`app.py`** (demo web UI) — VERIFIED. Single in-memory
  last-run state behind a lock. **D2 FIXED by PR #11:**
  `POST /run` validates `Content-Length` before reading any body
  byte — non-numeric or negative → 400, over 64 KiB
  (`MAX_RUN_BODY_BYTES`) → 413 — where previously a bad value
  crashed the handler, a negative one hung it under the run lock,
  and an oversized one was buffered without bound. **D1 FIXED
  (this pass):** the server now binds loopback by default
  (`HOST` overrides), and `POST /run` is authorized by
  `authorize_run` before any state change or run work. With
  `PROOFCREW_RUN_TOKEN` configured, a valid token (the
  `X-ProofCrew-Token` header or the form's token field,
  constant-time compared) is required from every client. With
  no token configured, only a direct local request — loopback
  bind, loopback client, no proxy/tunnel forwarding headers —
  is accepted; forwarded, remote, and wide-bind requests are
  refused 403 with a named reason, because a tunnel makes a
  remote visitor indistinguishable from a local client at the
  address level. The viewing endpoints (page, deliverable,
  receipts, attestation of the last run) remain public by
  design — D1 was the spend surface, and the spend surface is
  what is gated. Exposure and closure were both proven against
  live servers (before: `0.0.0.0` listen + unauthenticated POST
  drove a real provider API call with the server's key; after:
  loopback listen, forwarded and wide-bind POSTs refused,
  token POSTs accepted, on three configurations).

## Reported, not re-verified this pass

- **Live runs:** two full runs against the Nebius Token Factory
  API (2026-10-30), each producing 8 receipts with a VALID hash
  chain; run #2 was web-grounded (Tavily) and adjudicated, with
  real citations. — REPORTED (2026-10-30 record; not re-executed
  2026-11-09; no spend was authorized for this pass).
- **Demo and video:** a public demo (recorded run #2) and an
  88-second demo video, verified live on 2026-10-30. — REPORTED;
  not re-checked this pass. The demo dies if the Oracle box or
  the tunnel dies.
- **The one live signed run** remains STAGED-ONLY per the PR #5
  filer's disclosure: execution needs an operator key + Nebius
  key + spend authorization. — REPORTED, carried forward.

## Known defects / honest gaps

- **D1 FIXED** — the demo bound `0.0.0.0` with `POST /run`
  unauthenticated (an open spend surface whenever reachable,
  including via the public demo's Cloudflare quick tunnel).
  Closed per the queue target (row 77): localhost bind by
  default + `/run` authenticated by the operator token
  whenever a request is not a direct local one. See the
  `app.py` component entry for the exact policy and proof.
  Operator note: exposing the demo through any tunnel or
  proxy without setting `PROOFCREW_RUN_TOKEN` leaves `/run`
  refusing forwarded requests — deliberately; set the token.
- **ProofCrew was never submitted to the hackathon** — verified
  first-hand 2026-10-30 (Devpost portfolio shows 0 projects; no
  confirmation mail exists). The submission task failed silently.
  A late-entry request was emailed to the hackathon manager on
  2026-10-31; no reply is recorded. The deadline (2026-10-30
  10:00 AM PT) has passed. (Historical record, carried from the
  previous GT; not re-checked this pass.)
- **No production signing key exists** or is claimed anywhere in
  this repo; fixtures are test-only.
- **PR #10's quorum is not verified** — rejection paths only
  (see Open PRs above).

## What is NOT true

- The head is **not** `3db2fc19` (PR #4) and **not** `f39bde74`
  (PR #5). The previous version of this file asserted both in
  different sections — that internal contradiction was defect
  D3. The only head claim is the one at the top of this file.
- Open PRs are **not** none: PR #10 is open.
- Model IDs do **not** have to be passed via environment to be
  correct: the code defaults are the exact-case live IDs (the
  pre-PR #5 gap is closed; overrides remain available). The old
  "casing must be passed via environment" line is retired.
- The suite is **not** 40 tests (previous GT) and not 15: it is
  51 by pytest / 50 by unittest on this tree, both green.
- ProofCrew was **not** submitted to the hackathon (see gaps).
- A valid receipt chain does **not** prove the models' claims
  are true — it proves the recorded bytes were not altered
  afterwards. The attestation authenticates the designated key
  and the exact bytes: not model claims, not source truth, not
  settlement. `docs/SIGNED_EVIDENCE_EXPORT.md` states the same
  scope.
- The demo's spend endpoint is **not** open anymore: the
  pre-fix claim "the demo is not authenticated and not
  localhost-only" described D1 and is retired. What remains
  true: the tunnel URL is **not** a private surface for
  *viewing* (the page and the last run's artifacts are public
  by design), and a tunnel without `PROOFCREW_RUN_TOKEN` set
  cannot run the crew at all — runs are refused, not exposed.

## How to verify

- `python3 -m pytest tests/ -q` (with `requirements.txt`
  installed) → expect 71 passed at this head;
  `python3 -m unittest discover -s tests` → expect OK (70 tests).
- `python3 verify_receipts.py <receipts.jsonl>` → chain check,
  standard library only.
- Head check: `GET /repos/Savages-studios/proofcrew/git/ref/heads/main`.

## Estate rule

Update this file after any significant repo change. No claims without verification.
