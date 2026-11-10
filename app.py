#!/usr/bin/env python3
"""ProofCrew web UI — Python standard library only (http.server).

    TOKENFACTORY_API_KEY=... python3 app.py   # serves on $HOST:$PORT
                                              # (default 127.0.0.1:8080)

One page: submit a task, watch the crew's verdicts, read the deliverable,
download the receipt chain, and see the chain verification result rendered
on the page. State is a single in-memory last run — deliberately tiny so
the app idles in ~50 MB and runs happily on a 1 GB box.

Viewing is public; spending is not. ``POST /run`` drives the crew with
the operator's API key, so it is gated (defect D1): the server binds
loopback by default, and a run is accepted only from a direct local
client — or from anywhere when the request presents the operator token
(``PROOFCREW_RUN_TOKEN``, sent as the ``X-ProofCrew-Token`` header or
the form's token field). A request that arrives through a proxy or
tunnel (forwarding headers present), from a non-loopback client, or
against a server bound beyond loopback is refused with 403 unless a
valid token is presented; if no token is configured, those requests
cannot be authorized at all. Before exposing the demo through any
tunnel or proxy, set ``PROOFCREW_RUN_TOKEN``.
"""
import hmac
import html
import ipaddress
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

# The /run form carries a single task textarea. 64 KiB is far beyond any
# real task description and keeps a hostile or broken client from making
# the handler buffer (or wait for) an unbounded body on a ~50 MB app.
MAX_RUN_BODY_BYTES = 64 * 1024

# --- /run authorization (D1) -------------------------------------------------
# The demo binds loopback unless HOST says otherwise, and /run spends the
# operator's API key, so the run endpoint is authorized separately from
# the (public) viewing endpoints. The policy is a pure function of the
# bind address, the client address, proxy/tunnel forwarding headers, and
# the configured operator token, so tests can pin the whole matrix.
DEFAULT_HOST = "127.0.0.1"
RUN_TOKEN_ENV = "PROOFCREW_RUN_TOKEN"
TOKEN_HEADER = "X-ProofCrew-Token"
FORWARDING_HEADERS = ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded")


def server_host() -> str:
    """Bind address for the demo: loopback unless HOST overrides it."""
    return os.environ.get("HOST") or DEFAULT_HOST


def configured_run_token() -> str | None:
    return os.environ.get(RUN_TOKEN_ENV) or None


def is_loopback_host(host: str) -> bool:
    """True only for addresses that cannot be reached from another host.

    Wildcards (0.0.0.0 / ::), ordinary interface addresses, and names
    that are not literally loopback all count as NOT loopback — the
    local-trust claim fails closed.
    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def request_is_forwarded(headers) -> bool:
    """True when a proxy or tunnel carried this request to us.

    A forwarded request's client address is the proxy's, so a loopback
    client address proves nothing about who originated the request.
    """
    return any((headers.get(name) or "").strip() for name in FORWARDING_HEADERS)


def authorize_run(
    *,
    bind_host: str,
    client_host: str,
    forwarded: bool,
    configured_token: str | None,
    provided_tokens,
) -> tuple[bool, str]:
    """Decide whether a POST /run may spend the operator's API key.

    Returns (allowed, reason); the reason is empty when allowed and a
    short refusal explanation otherwise. A valid operator token (when
    one is configured) authorizes from anywhere. With no token
    configured, only a direct local request — loopback bind, loopback
    client, no forwarding headers — is authorized, and every other
    shape fails closed.
    """
    if configured_token is not None:
        configured = configured_token
        for candidate in provided_tokens:
            if candidate and hmac.compare_digest(
                candidate.encode("utf-8"), configured.encode("utf-8")
            ):
                return True, ""
        return False, "a valid operator token is required to run the crew"
    if forwarded:
        return False, (
            "this request arrived through a proxy or tunnel and no "
            "operator token is configured (set PROOFCREW_RUN_TOKEN "
            "before exposing the demo)"
        )
    if not is_loopback_host(bind_host):
        return False, (
            "the server is bound beyond loopback and no operator token "
            "is configured (set PROOFCREW_RUN_TOKEN or bind HOST=127.0.0.1)"
        )
    if not is_loopback_host(client_host):
        return False, (
            "runs are accepted only from local clients when no operator "
            "token is configured (set PROOFCREW_RUN_TOKEN)"
        )
    return True, ""

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
        "<br><input type='password' name='token' autocomplete='off' "
        "placeholder='Operator token (only when the server requires one)'>"
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


def bind_host_of(handler) -> str:
    # BaseHTTPRequestHandler always sets .server on a live request; the
    # fallback covers synthetic in-process callers (tests), which are
    # inside the operator's trust boundary by construction — a network
    # client cannot make these attributes disappear.
    address = getattr(getattr(handler, "server", None), "server_address", None)
    return address[0] if address else DEFAULT_HOST


def client_host_of(handler) -> str:
    address = getattr(handler, "client_address", None)
    return address[0] if address else "127.0.0.1"


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
        # Guard the Content-Length before trusting it: a non-numeric value
        # must not crash the handler, a negative one would make read()
        # block until EOF while holding RUN_LOCK, and an oversized one
        # must be refused before a single body byte is buffered.
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except ValueError:
            self._send(b"invalid Content-Length", status=400, content_type="text/plain")
            return
        if length < 0:
            self._send(b"invalid Content-Length", status=400, content_type="text/plain")
            return
        if length > MAX_RUN_BODY_BYTES:
            self._send(b"request body too large", status=413, content_type="text/plain")
            return
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        task = (form.get("task") or [""])[0].strip()
        # Authorization comes before any state change or run work: a
        # refused request must not clear the last run or reach the crew.
        allowed, reason = authorize_run(
            bind_host=bind_host_of(self),
            client_host=client_host_of(self),
            forwarded=request_is_forwarded(self.headers),
            configured_token=configured_run_token(),
            provided_tokens=[
                self.headers.get(TOKEN_HEADER),
                (form.get("token") or [None])[0],
            ],
        )
        if not allowed:
            self._send(
                f"run refused: {reason}".encode("utf-8"),
                status=403,
                content_type="text/plain",
            )
            return
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
    host = server_host()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ProofCrew listening on http://{host}:{port}")
    if configured_run_token() is not None:
        print("POST /run requires the operator token (PROOFCREW_RUN_TOKEN).")
    elif is_loopback_host(host):
        print("POST /run accepts direct local requests only "
              "(set PROOFCREW_RUN_TOKEN before using any tunnel or proxy).")
    else:
        print("WARNING: bound beyond loopback with no PROOFCREW_RUN_TOKEN — "
              "POST /run will refuse every request.")
    server.serve_forever()


if __name__ == "__main__":
    main()
