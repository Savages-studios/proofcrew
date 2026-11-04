import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from proofcrew.attestation import verify_attestation
from proofcrew.config import Config
from proofcrew.signed_run import load_signing_key, run_signed_crew
from tests.test_crew import FakeTransport
import app
import run


class TestSignedRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        key = Ed25519PrivateKey.generate()
        self.keyfile = self.root / 'private.pem'
        self.keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.keys = load_signing_key(self.keyfile)

    def test_case_sensitive_defaults_and_overrides(self):
        c = Config.from_env({})
        self.assertEqual((c.planner_model, c.worker_model, c.screener_model), ('nvidia/Nemotron-3-Ultra-550b-a55b', 'nvidia/nemotron-3-super-120b-a12b', 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'))
        self.assertEqual(Config.from_env({'MODEL_PLANNER':'Mixed/Case'}).planner_model, 'Mixed/Case')
        fake = FakeTransport()
        run_signed_crew('test task', fake, c, None, self.keys)
        self.assertEqual(fake.calls[0][0], c.planner_model)
        self.assertIn(c.screener_model, [call[0] for call in fake.calls])

    def test_cli_writes_independently_verifiable_package(self):
        env = {'TOKENFACTORY_API_KEY':'test-only', 'PROOFCREW_SIGNING_KEY':str(self.keyfile)}
        with patch.dict(os.environ, env, clear=True), patch.object(run, 'TokenFactoryTransport', return_value=FakeTransport()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(['test task', '--out', str(self.root / 'out')]), 0)
        out = self.root / 'out'
        from proofcrew.receipts import load_receipts
        self.assertEqual(verify_attestation(load_receipts(out / 'receipts.jsonl'), (out / 'deliverable.md').read_bytes(), json.loads((out / 'attestation.json').read_text()), self.keys[1]), [])

    def test_signing_failure_prevents_cli_success_and_output(self):
        env = {'TOKENFACTORY_API_KEY':'test-only', 'PROOFCREW_SIGNING_KEY':str(self.keyfile)}
        with patch.dict(os.environ, env, clear=True), patch.object(run, 'TokenFactoryTransport', return_value=FakeTransport()), patch('proofcrew.signed_run.sign_attestation', side_effect=ValueError('sign failed')), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(run.main(['task', '--out', str(self.root / 'out')]), 0)
        self.assertFalse((self.root / 'out').exists())

    def test_missing_key_fails_before_transport(self):
        with patch.dict(os.environ, {'TOKENFACTORY_API_KEY':'test-only'}, clear=True), patch.object(run, 'TokenFactoryTransport') as transport, contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(run.main(['task']), 0)
            transport.assert_not_called()

    def test_web_failure_clears_previous_success(self):
        class Request:
            _run_post = app.Handler._run_post
            path = '/run'
            headers = {'Content-Length':'9'}
            rfile = io.BytesIO(b'task=test')
            def _send(self, *args, **kwargs): pass
        app.STATE.update(result=object(), attestation={'old':True}, error=None)
        env = {'TOKENFACTORY_API_KEY':'test-only', 'PROOFCREW_SIGNING_KEY':str(self.keyfile)}
        with patch.dict(os.environ, env, clear=True), patch.object(app, 'TokenFactoryTransport', return_value=FakeTransport()), patch('proofcrew.signed_run.sign_attestation', side_effect=ValueError('sign failed')):
            app.Handler.do_POST(Request())
        self.assertIsNone(app.STATE['result'])
        self.assertIsNone(app.STATE['attestation'])
        self.assertIn('sign failed', app.STATE['error'])

    def test_web_success_exposes_attestation(self):
        class Request:
            _run_post = app.Handler._run_post
            path = '/run'
            headers = {'Content-Length':'9'}
            rfile = io.BytesIO(b'task=test')
            def _send(self, *args, **kwargs): pass
        env = {'TOKENFACTORY_API_KEY':'test-only', 'PROOFCREW_SIGNING_KEY':str(self.keyfile)}
        with patch.dict(os.environ, env, clear=True), patch.object(app, 'TokenFactoryTransport', return_value=FakeTransport()):
            app.Handler.do_POST(Request())
        result = app.STATE['result']
        self.assertIsNotNone(result)
        self.assertEqual(verify_attestation(result.chain.receipts, result.deliverable.encode(), app.STATE['attestation'], self.keys[1]), [])

    def test_concurrent_web_runs_publish_complete_pairs(self):
        class Request:
            _run_post = app.Handler._run_post
            path = '/run'
            def __init__(self, task):
                data = ('task=' + task).encode()
                self.headers = {'Content-Length': str(len(data))}
                self.rfile = io.BytesIO(data)
            def _send(self, *args, **kwargs): pass

        entered = threading.Event()
        release = threading.Event()
        second_entered = threading.Event()
        original = app.run_signed_crew
        def gated(task, transport, config, tavily, keys):
            if task == 'first':
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('test did not release first run')
            else:
                second_entered.set()
            return original(task, transport, config, tavily, keys)

        env = {'TOKENFACTORY_API_KEY': 'test-only', 'PROOFCREW_SIGNING_KEY': str(self.keyfile)}
        with patch.dict(os.environ, env, clear=True), patch.object(app, 'TokenFactoryTransport', side_effect=lambda *a: FakeTransport()), patch.object(app, 'run_signed_crew', side_effect=gated):
            first = threading.Thread(target=app.Handler.do_POST, args=(Request('first'),))
            second = threading.Thread(target=app.Handler.do_POST, args=(Request('second'),))
            first.start()
            try:
                self.assertTrue(entered.wait(2))
                second.start()
                self.assertFalse(second_entered.wait(0.1))
            finally:
                release.set()
                first.join(3)
                if second.ident is not None:
                    second.join(3)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
        result, attestation = app.STATE['result'], app.STATE['attestation']
        self.assertEqual(result.task, 'second')
        self.assertEqual(verify_attestation(result.chain.receipts, result.deliverable.encode(), attestation, self.keys[1]), [])
