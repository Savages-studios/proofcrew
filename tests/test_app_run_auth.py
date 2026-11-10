"""Authorization on the demo's POST /run endpoint (defect D1).

The demo used to bind 0.0.0.0 with no authentication, so anyone who
could reach the port — including the whole internet whenever the
public demo's tunnel was up — could spend the operator's API key.
These tests pin the gate: a pure policy matrix over the real decision
function, plus real HTTP against the real handler for the loopback,
forwarded, wide-bind, and token shapes.
"""
import http.client
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as webapp

OPERATOR_TOKEN = "test-operator-token"


def authorize(**overrides):
    """authorize_run with the plain local-demo shape as the default."""
    args = {
        "bind_host": "127.0.0.1",
        "client_host": "127.0.0.1",
        "forwarded": False,
        "configured_token": None,
        "provided_tokens": [],
    }
    args.update(overrides)
    return webapp.authorize_run(**args)


class TestAuthorizeRunPolicy(unittest.TestCase):
    def test_direct_local_request_allowed_without_token(self):
        allowed, reason = authorize()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_forwarded_request_refused_without_token(self):
        # A tunnel/proxy client IS loopback; its address proves nothing.
        allowed, reason = authorize(forwarded=True)
        self.assertFalse(allowed)
        self.assertIn("PROOFCREW_RUN_TOKEN", reason)

    def test_wide_bind_refused_without_token(self):
        allowed, reason = authorize(bind_host="0.0.0.0")
        self.assertFalse(allowed)
        self.assertIn("PROOFCREW_RUN_TOKEN", reason)

    def test_remote_client_refused_without_token(self):
        allowed, _ = authorize(client_host="203.0.113.7")
        self.assertFalse(allowed)

    def test_valid_token_authorizes_from_anywhere(self):
        allowed, _ = authorize(
            bind_host="0.0.0.0",
            client_host="203.0.113.7",
            forwarded=True,
            configured_token=OPERATOR_TOKEN,
            provided_tokens=[OPERATOR_TOKEN],
        )
        self.assertTrue(allowed)

    def test_wrong_token_refused(self):
        allowed, _ = authorize(
            configured_token=OPERATOR_TOKEN, provided_tokens=["nope"]
        )
        self.assertFalse(allowed)

    def test_missing_token_refused_when_configured(self):
        # A configured token gates everyone, local clients included.
        allowed, _ = authorize(configured_token=OPERATOR_TOKEN)
        self.assertFalse(allowed)

    def test_empty_token_never_matches(self):
        allowed, _ = authorize(
            configured_token=OPERATOR_TOKEN, provided_tokens=["", None]
        )
        self.assertFalse(allowed)


class TestLoopbackClassification(unittest.TestCase):
    def test_loopback_addresses(self):
        for host in ("127.0.0.1", "127.5.0.9", "::1", "localhost"):
            self.assertTrue(webapp.is_loopback_host(host), host)

    def test_non_loopback_addresses(self):
        for host in ("0.0.0.0", "::", "192.168.1.10", "203.0.113.7",
                     "example.com", ""):
            self.assertFalse(webapp.is_loopback_host(host), host)


class TestServerHost(unittest.TestCase):
    def test_default_is_loopback(self):
        env = {k: v for k, v in os.environ.items() if k != "HOST"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(webapp.server_host(), "127.0.0.1")

    def test_host_env_is_honored(self):
        with mock.patch.dict(os.environ, {"HOST": "0.0.0.0"}):
            self.assertEqual(webapp.server_host(), "0.0.0.0")


class RunServerMixin:
    bind = "127.0.0.1"

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer((cls.bind, 0), webapp.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def set_env(self, **overrides):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("TOKENFACTORY_API_KEY", "PROOFCREW_RUN_TOKEN")
        }
        env.update(overrides)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self):
        webapp.STATE.update(result=None, attestation=None, error=None)

    def post_run(self, body=b"task=hello+crew", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        all_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        all_headers.update(headers or {})
        conn.request("POST", "/run", body=body, headers=all_headers)
        response = conn.getresponse()
        response.read()
        conn.close()
        return response.status


class TestRunGateLoopbackBind(RunServerMixin, unittest.TestCase):
    def test_direct_local_post_still_works(self):
        self.set_env()
        self.assertEqual(self.post_run(), 303)
        # Reached the normal run path (stopped only by the absent key).
        self.assertIn("TOKENFACTORY_API_KEY", webapp.STATE["error"] or "")

    def test_forwarded_post_refused_and_state_untouched(self):
        self.set_env()
        webapp.STATE["error"] = "previous state"
        status = self.post_run(headers={"X-Forwarded-For": "203.0.113.7"})
        self.assertEqual(status, 403)
        self.assertEqual(webapp.STATE["error"], "previous state")
        self.assertIsNone(webapp.STATE["result"])

    def test_cloudflare_forwarded_post_refused(self):
        self.set_env()
        status = self.post_run(headers={"CF-Connecting-IP": "203.0.113.7"})
        self.assertEqual(status, 403)


class TestRunGateWideBind(RunServerMixin, unittest.TestCase):
    bind = "0.0.0.0"

    def test_post_refused_when_bound_wide_without_token(self):
        self.set_env()
        self.assertEqual(self.post_run(), 403)
        # Never reached the run path: no config-check error was recorded.
        self.assertIsNone(webapp.STATE["error"])


class TestRunGateWithToken(RunServerMixin, unittest.TestCase):
    def test_post_without_token_refused(self):
        self.set_env(PROOFCREW_RUN_TOKEN=OPERATOR_TOKEN)
        self.assertEqual(self.post_run(), 403)
        self.assertIsNone(webapp.STATE["error"])

    def test_post_with_wrong_form_token_refused(self):
        self.set_env(PROOFCREW_RUN_TOKEN=OPERATOR_TOKEN)
        self.assertEqual(self.post_run(body=b"task=x&token=wrong"), 403)

    def test_post_with_form_token_accepted(self):
        self.set_env(PROOFCREW_RUN_TOKEN=OPERATOR_TOKEN)
        body = f"task=hello+crew&token={OPERATOR_TOKEN}".encode()
        self.assertEqual(self.post_run(body=body), 303)
        self.assertIn("TOKENFACTORY_API_KEY", webapp.STATE["error"] or "")

    def test_post_with_header_token_accepted(self):
        self.set_env(PROOFCREW_RUN_TOKEN=OPERATOR_TOKEN)
        status = self.post_run(headers={webapp.TOKEN_HEADER: OPERATOR_TOKEN})
        self.assertEqual(status, 303)
        self.assertIn("TOKENFACTORY_API_KEY", webapp.STATE["error"] or "")


if __name__ == "__main__":
    unittest.main()
