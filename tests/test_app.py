"""Content-Length guard on the demo's POST /run endpoint.

The handler used to feed the raw header straight into int() and read():
a non-numeric value crashed the request, a negative one made read()
block until EOF while holding the run lock, and an oversized one was
buffered without bound. These tests pin the guarded behavior over real
HTTP against the real handler.
"""
import http.client
import os
import socket
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as webapp


class TestRunContentLengthGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        webapp.STATE.update(result=None, attestation=None, error=None)
        # No API key: an accepted request stops at the config check and
        # redirects (303), never touching the network or the crew.
        env = {k: v for k, v in os.environ.items() if k != "TOKENFACTORY_API_KEY"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def raw_post(self, headers: bytes, body: bytes = b"") -> bytes:
        """Send a hand-built POST /run and return the raw response head."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(
                b"POST /run HTTP/1.1\r\nHost: 127.0.0.1\r\n" + headers + b"\r\n" + body
            )
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            return response

    def status_of(self, response: bytes) -> int:
        return int(response.split(b" ", 2)[1])

    def test_oversized_content_length_refused_before_reading(self):
        # Declare ~100 MB and send no body at all: the guard must answer
        # 413 immediately instead of blocking on read() for the body.
        response = self.raw_post(b"Content-Length: 99999999\r\n")
        self.assertEqual(self.status_of(response), 413)
        self.assertIsNone(webapp.STATE["result"])
        self.assertIsNone(webapp.STATE["error"])

    def test_one_byte_over_cap_refused(self):
        response = self.raw_post(
            f"Content-Length: {webapp.MAX_RUN_BODY_BYTES + 1}\r\n".encode()
        )
        self.assertEqual(self.status_of(response), 413)

    def test_malformed_content_length_is_400_not_a_crash(self):
        response = self.raw_post(b"Content-Length: banana\r\n")
        self.assertEqual(self.status_of(response), 400)

    def test_negative_content_length_is_400_not_a_hang(self):
        # read(-1) reads until EOF; with the socket held open the old
        # code blocked forever under RUN_LOCK. The guard answers 400.
        response = self.raw_post(b"Content-Length: -5\r\n")
        self.assertEqual(self.status_of(response), 400)

    def test_body_at_cap_is_accepted(self):
        task = "x" * (webapp.MAX_RUN_BODY_BYTES - len("task="))
        body = f"task={task}".encode()
        self.assertEqual(len(body), webapp.MAX_RUN_BODY_BYTES)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/run", body=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = conn.getresponse()
        response.read()
        conn.close()
        self.assertEqual(response.status, 303)
        # The request reached the normal run path (stopped only by the
        # deliberately absent API key).
        self.assertIn("TOKENFACTORY_API_KEY", webapp.STATE["error"] or "")

    def test_ordinary_post_still_works(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/run", body=b"task=hello+crew",
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = conn.getresponse()
        response.read()
        conn.close()
        self.assertEqual(response.status, 303)
        self.assertIn("TOKENFACTORY_API_KEY", webapp.STATE["error"] or "")

    def test_missing_content_length_treated_as_empty_form(self):
        response = self.raw_post(b"")
        self.assertEqual(self.status_of(response), 303)
        self.assertEqual(webapp.STATE["error"], "Please enter a task.")


if __name__ == "__main__":
    unittest.main()
