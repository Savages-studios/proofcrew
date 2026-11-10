# ProofCrew

**A Nemotron crew on Nebius Token Factory where no agent grades its own homework — and every run leaves proof.**

Give ProofCrew a task. A planner splits it in two, two workers execute in
parallel, an independent screener checks their work, the workers
cross-verify *each other*, and the planner adjudicates **only** if they
disagree. What you get back is the deliverable **plus a SHA-256 hash-chained
receipt file and an Ed25519 signed attestation**. Verify the chain offline
with the standard library, and verify the signature using `cryptography` and
an independently trusted public key.

Built for the **Nebius × NVIDIA Global AI Hackathon** (Track: Best Apps and
Agents).

## Why

Multi-agent systems have a quiet credibility problem: the same model that
produced an answer usually ends up vouching for it, and the run leaves no
evidence anyone else could check. ProofCrew is built around the opposite
discipline:

- **Separation of duties.** The planner never writes the work. The workers
  never review their own output — each verifies the *other's*. The screener
  produced none of it. The adjudicator is invoked only on disagreement, so
  its judgment is spent exactly where the crew actually split.
- **Conservative escalation.** An unparseable or missing peer review counts
  as disagreement and escalates. Silence never counts as agreement.
- **Proof, not promises.** Every stage appends a receipt to a hash chain:
  each receipt contains the SHA-256 of the previous one, so altering any
  stage after the fact breaks the chain detectably. The final receipt pins
  the SHA-256 of the deliverable itself. Stated plainly: the chain is
  **unkeyed** SHA-256 — tamper-evident, **not signed**. It proves a record
  wasn't altered after the fact relative to itself; it does not prove
  *who* produced it. The separate Ed25519 attestation authenticates the chain and
  deliverable against an independently trusted operator public key.
- **Honest grounding.** Worker B grounds its part with a Tavily web search
  *when a Tavily key is configured*. When it isn't, the receipts record
  `grounded: false`. The crew never fakes a research call.

## How it works

```
                 task
                  │
        ┌─────────▼──────────┐
        │ PLAN — Nemotron 3  │  splits the task into two complementary
        │ Ultra (550B-A55B)  │  parts + a web search query
        └─────────┬──────────┘
          ┌───────┴────────┐
          ▼                ▼
   ┌─────────────┐  ┌─────────────┐
   │ WORK A      │  │ WORK B      │  two Nemotron 3 Super (120B-A12B)
   │ Nemotron 3  │  │ Nemotron 3  │  workers in parallel; B grounds its
   │ Super       │  │ Super       │  part via Tavily (receipts say if not)
   └──────┬──────┘  └──────┬──────┘
          └───────┬────────┘
        ┌─────────▼──────────┐
        │ SCREEN — Nemotron  │  independent screen of both outputs;
        │ 3 Nano (30B-A3B)   │  Nano produced none of the work
        └─────────┬──────────┘
        ┌─────────▼──────────┐
        │ CROSS-VERIFY       │  worker A verifies B's output,
        │ Super ⇄ Super      │  worker B verifies A's — never their own
        └─────────┬──────────┘
            agree │ disagree
        ┌─────────┴──────────┐
        ▼                    ▼
   assemble parts      ADJUDICATE — Ultra returns,
   untouched           resolves the dispute,
                       writes the final deliverable
                  │
                  ▼
   deliverable + receipts.jsonl (hash-chained)
```

Per run that's 6 inference calls, 7 on disagreement — three Nemotron tiers,
each doing the job its size suits: Ultra for planning/adjudication, Super
for execution and peer review, Nano for fast screening.

## How Nebius Token Factory and Nemotron are used

All inference is a **runtime call to the Nebius Token Factory API**
(`https://api.tokenfactory.nebius.com/v1/`, OpenAI-compatible chat
completions) — that is what makes ProofCrew run on Nebius. Models (IDs
configurable via environment, see `.env.example`):

| Role | Default model | Job |
|---|---|---|
| Planner / adjudicator | `nvidia/Nemotron-3-Ultra-550b-a55b` | Split the task; resolve cross-verification disputes |
| Workers / cross-verifiers | `nvidia/nemotron-3-super-120b-a12b` | Execute the two parts in parallel; verify each other's output |
| Screener | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Fast independent screen of both outputs |

## How Tavily is used

The planner emits a search query with its plan. When `TAVILY_API_KEY` is
set, worker B's prompt includes live Tavily results for that query (title,
URL, content) with instructions to cite URLs it relies on, and its work
receipt records `grounded: true`. This is a real runtime call to the Tavily
API (`https://api.tavily.com/search`). Without a key, no call is made and
the receipt records `grounded: false` — check it yourself in the receipts.

Citations are first-class, not just text a worker happened to write. The
sources Tavily actually returned are carried as structured data (title +
URL): they are recorded in worker B's work receipt, listed in the final
receipt's `citations`, handed to the adjudicator when it runs (with
instructions to cite only those URLs), and rendered as a deterministic
**Sources** section at the end of the final deliverable — on both the
assembly path and the adjudication path, so source links survive into the
final answer. The section is built only from retrieved URLs; on an
ungrounded run there is no Sources section at all.

## Setup

Requirements: Python 3.10+. One dependency: the `openai` SDK (used only to
talk to Token Factory). The web UI, Tavily client, and receipt verifier are
standard library only.

```bash
git clone https://github.com/sa6ag9/proofcrew.git
cd proofcrew
pip install -r requirements.txt

cp .env.example .env   # reference only: export values below; .env is not loaded automatically
export TOKENFACTORY_API_KEY=<your Nebius Token Factory key>
export PROOFCREW_SIGNING_KEY=/secure/path/operator-ed25519.pem  # optional; enables signed attestation
export TAVILY_API_KEY=<optional, enables grounded worker B>
```

Get a Token Factory key at <https://tokenfactory.nebius.com> (billing setup
with a bank card is required to complete onboarding). A full demo run costs
well under a dollar at published Nemotron tier prices.

## Run it

Command line:

```bash
python3 run.py "Write a launch brief for a fictional coffee subscription for remote workers"
# -> prints the deliverable and writes deliverable.md and receipts.jsonl
#    attestation.json is also written when PROOFCREW_SIGNING_KEY is configured
```

Web UI (stdlib `http.server`, idles in ~50 MB — happy on a 1 GB box):

```bash
python3 app.py            # http://localhost:8080  (PORT env to change)
```

Submit a task, read the deliverable, see the stage list, the grounding and
adjudication flags, the chain verdict, and download the receipts.

The page is public to view, but `POST /run` spends your API key, so it is
gated: `app.py` binds `127.0.0.1` by default (`HOST` to change), and a run
is accepted only from a direct local client — or from anywhere when the
request presents the operator token (`PROOFCREW_RUN_TOKEN`, via the form's
token field or the `X-ProofCrew-Token` header). If you expose the demo
through a tunnel or proxy, set `PROOFCREW_RUN_TOKEN` first: forwarded
requests without a valid token are refused.

## Verify the receipts — don't trust, check

Every run writes `receipts.jsonl`: one JSON receipt per stage, each with
`seq`, `actor`, `kind`, `payload`, `prev_hash`, and `hash` (SHA-256 over the
canonical receipt). Verify any run, anywhere, with only Python's standard
library:

```bash
python3 verify_receipts.py proofcrew-out/receipts.jsonl
# 8 receipts: planner/plan -> worker_a/work -> worker_b/work -> ...
# worker_b grounded via Tavily: True
# CHAIN VALID — every receipt hashes to the next; nothing was altered.
```

Edit one byte of any receipt and re-run: it reports `CHAIN INVALID` and
names the broken receipt. The unit tests prove this, including the case
where an attacker recomputes the tampered receipt's own hash (the next
link still breaks). One honest limit, again: the chain is unkeyed
SHA-256 — it detects alteration, it does not authenticate the author. Verify the signed attestation separately:

```bash
python3 attest_receipts.py verify proofcrew-out/receipts.jsonl proofcrew-out/deliverable.md proofcrew-out/attestation.json /trusted/operator-ed25519-public.pem
```

Pin the public key through an independent trusted channel. See
[Signed evidence](docs/SIGNED_EVIDENCE_EXPORT.md) for key preparation and the live-run checklist.

## A worked research trace

*Written for the ODSC × Nebius Hackathon ("build a research agent that
brings its sources"), which ProofCrew is also entered in. The
architecture is the pipeline diagrammed above; what follows is one real
run through it, taken from its own receipt file — nothing reconstructed.*

**The question** (live run, Oct 30, 2026; Nebius Token Factory + Tavily,
both called at runtime):

> Write a short brief on Nebius Token Factory: what it is, which NVIDIA
> models it serves, and what makes it different from calling a model
> provider directly. Base it on current public sources and cite them.
> Under 300 words.

**Plan — Nemotron 3 Ultra.** Split the brief in two: worker A drafts the
structural skeleton (definition, role, differentiation logic) with
placeholders and *no* citations; worker B fills the placeholders from
current public sources, with inline citations. The plan's search query
targeted which NVIDIA models Token Factory supports, across 2024–2025
sources.

**Grounded work — two Nemotron 3 Super workers in parallel.** Worker A's
receipt records `grounded: false` — it never does the research, by
design; its output is a skeleton with `[MODEL LIST]`,
`[DIFFERENTIATOR 1]` placeholders. Worker B ran grounded
(`grounded: true`): its output cited three sources inline — Nebius's own
launch article on nebius.com, a SaturnCloud inference-provider
comparison report, and a rywalker.com research page on Nebius.

**Screen — Nemotron 3 Nano**, which produced none of the work, passed
*neither* worker: A drew "Vague placeholders, no concrete model list or
citations"; B drew "Some claims not directly supported by cited
sources"; cross-cutting flags: "Unsupported claims", "Missing
citations". The screen is recorded in the chain; it informs, it does
not gate.

**Cross-verify — each Super checks the other.** Worker B agreed with
A's skeleton (no issues). Worker A **disagreed** with B, on four
concrete grounds: B's citations used 【…】 brackets instead of the
requested […] style; the claim that Token Factory serves the Nemotron
family lacked a direct confirming source; the SaturnCloud report does
not discuss Token Factory's features specifically; and rywalker.com is
not an authoritative source.

**Adjudication — Ultra, invoked only because they disagreed.** The
final brief is 139 words, and the adjudicator resolved the
citation dispute by narrowing, not defending: the shipped answer cites
only the Nebius newsroom source, re-anchoring the per-token pricing,
unified token budget, and no-lock-in claims to it, and dropping the
SaturnCloud and rywalker citations entirely.

**The proof.** Eight receipts — plan → work → work → screen → verify →
verify → adjudication → final. The final receipt pins the deliverable's
SHA-256 (`ac3b3b3b…e0463d`), and the chain re-verifies as VALID with the
stdlib-only script above. The receipts are unkeyed SHA-256: they prove
this record wasn't altered after the run, relative to itself — they do
not prove who ran it. This historical trace predates automatic signing and does not claim an attestation.

One timing note: this run predates the structured-citations change
described under "How Tavily is used" — in this record the citations
live in worker B's text and the adjudicator's answer. Current runs
additionally carry the retrieved sources as structured data in the
receipts and end the deliverable with the deterministic Sources
section.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The offline tests require no network or API key: the hash chain (valid chain passes;
tampered payload, tampered hash, rehashed tamper, and dropped receipt all
fail), the shipped `verify_receipts.py` against real files (accepts valid,
rejects tampered), the adjudication gate (adjudicator fires only on
disagreement; unparseable reviews escalate), grounding honesty
(`grounded: false` without a Tavily key; research text reaches worker B
with one), and citations (a grounded run's Sources section carries exactly
the retrieved URLs into the final deliverable on both the assembly and
adjudication paths and records them in the receipts; an ungrounded run
emits no Sources section and no links). Test doubles live in `tests/`
only — never in the shipped path.

## Project layout

```
proofcrew/
  config.py     environment configuration (keys, model IDs, base URL)
  transport.py  Token Factory transport (OpenAI-compatible)
  crew.py       the five-stage orchestration + adjudication gate
  tavily.py     Tavily search client (httpx)
  receipts.py   hash-chain receipts + verification (stdlib only)
run.py          CLI entry point
app.py          web UI entry point (stdlib http.server)
verify_receipts.py  standalone chain verifier (stdlib only)
tests/          unit tests with fake transports
```

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Nicholas Savage / Savage AI Studios.
