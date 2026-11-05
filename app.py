#!/usr/bin/env python3
"""ProofCrew web UI — Python standard library only (http.server).

    TOKENFACTORY_API_KEY=... python3 app.py   # serves on $PORT (default 8080)

One page: submit a task, watch the crew's verdicts, read the deliverable,
download the receipt chain, and see the chain verification result rendered
on the page. State is a single in-memory last run — deliberately tiny so
the app idles in ~50 MB and runs happily on a 1 GB box.
"""
import html
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proofcrew.config import Config
from proofcrew.signed_run import load_signing_key, run_signed_crew
from proofcrew.receipts import verify_receipts
from proofcrew.tavily import TavilyClient
from proofcrew.transport import TokenFactoryTransport

STATE: dict = {"result": None, "attestation": None, "error": None}
RUN_LOCK = threading.Lock()

CSS = (
    "body{font-family:system-ui,sans-serif;max-width:840px;margin:2rem auto;"
    "padding:0 1rem;line-height:1.5}textarea{width:100%;box-sizing:border-box}"
    "pre{white-space:pre-wrap;background:#f4f4f4;padding:1rem;border-radius:8px}"
    ".ok{color:#137333;font-weight:600}.bad{color:#b3261e;font-weight:600}"
    "button{padding:.5rem 1.2rem;font-size:1rem}"
)


def render_page(state=None) -> bytes:
    state = STATE.copy() if state is None else state
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>ProofCrew</title><style>{CSS}</style></head><body>",
        "<h1>ProofCrew</h1>",
        "<p>A Nemotron crew on <b>Nebius Token Factory</b> where "
        "<b>no agent grades its own homework</b>: Nemotron 3 Ultra plans, two "
        "Nemotron 3 Super workers execute (one grounds its work with Tavily), "
        "Nemotron 3 Nano screens, the workers cross-verify <i>each other</i>, "
        "and Ultra adjudicates only on disagreement. Every run leaves a "
        "SHA-256 hash-chained receipt file anyone can re-verify.</p>",
        "<form method='post' action='/run'>"
        "<textarea name='task' rows='4' placeholder='Describe the task for the crew...'></textarea>"
        "<br><button type='submit'>Run the crew</button></form>",
    ]
    if state["error"]:
        parts.append(f"<p class='bad'>{html.escape(state['error'])}</p>")
    result = state["result"]
    if result is not None:
        problems = verify_receipts(result.chain.receipts)
        verdict = (
            "<span class='ok'>Receipt chain: VALID</span>"
            if not problems
            else f"<span class='bad'>Receipt chain: INVALID — {html.escape('; '.join(problems))}</span>"
        )
        stages = " → ".join(
            f"{r['actor']}/{r['kind']}" for r in result.chain.receipts
        )
        parts += [
            "<h2>Deliverable</h2>",
            f"<pre>{html.escape(result.deliverable)}</pre>",
            "<h2>Run receipts</h2>",
            f"<p>Stages: {html.escape(stages)}</p>",
            f"<p>Worker B grounded via Tavily: <b>{result.grounded_worker_b}</b> · "
            f"Planner adjudicated: <b>{result.adjudicated}</b></p>",
            f"<p>{verdict}</p>",
            "<p><a href='/receipts'>Download receipts.jsonl</a> — re-verify "
            "anywhere with <code>python3 verify_receipts.py receipts.jsonl</code> "
            "(standard library only).</p>",
            "<p><a href='/deliverable'>Download deliverable.md</a></p>",
        ]
        if state["attestation"] is None:
            parts.append(
                "<p class='bad'>Package is UNSIGNED "
                "(PROOFCREW_SIGNING_KEY is not configured).</p>"
            )
        else:
            parts.append("<p><a href='/attestation'>Download attestation.json</a></p>")
    parts.append("</body></html>")
    return "".join(parts).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status=200, content_type="text/html; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        state = STATE.copy()
        if self.path == "/attestation" and state["attestation"] is not None:
            self._send((json.dumps(state["attestation"], sort_keys=True, indent=2) + "\n").encode(), content_type="application/json")
            return
        if self.path == "/deliverable" and state["result"] is not None:
            self._send(state["result"].deliverable.encode("utf-8"), content_type="text/plain; charset=utf-8")
            return
        if self.path == "/receipts" and state["result"] is not None:
            data = state["result"].chain.to_jsonl().encode("utf-8")
            self._send(
                data,
                content_type="application/json",
                extra={"Content-Disposition": "attachment; filename=receipts.jsonl"},
            )
            return
        self._send(render_page(state))

    def do_POST(self):
        # A single last-run state must never combine concurrent runs.
        with RUN_LOCK:
            self._run_post()

    def _run_post(self):
        if self.path != "/run":
            self._send(b"not found", status=404, content_type="text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        task = (form.get("task") or [""])[0].strip()
        STATE.update(error=None, result=None, attestation=None)
        if not task:
            STATE["error"] = "Please enter a task."
        else:
            config = Config.from_env()
            if not config.api_key:
                STATE["error"] = (
                    "TOKENFACTORY_API_KEY is not set on the server. See .env.example."
                )
            else:
                try:
                    signing_key = os.environ.get("PROOFCREW_SIGNING_KEY")
                    keys = load_signing_key(signing_key) if signing_key else None
                    transport = TokenFactoryTransport(config.api_key, config.base_url)
                    tavily = (
                        TavilyClient(config.tavily_api_key)
                        if config.tavily_api_key
                        else None
                    )
                    result, attestation = run_signed_crew(task, transport, config, tavily, keys)
                    STATE.update(attestation=attestation, result=result)
                except Exception as exc:  # surface, don't crash the demo
                    STATE["error"] = f"Run failed: {exc}"
        self._send(b"", status=303, extra={"Location": "/"})

    def log_message(self, *args):  # keep logs quiet
        pass


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"ProofCrew listening on http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
