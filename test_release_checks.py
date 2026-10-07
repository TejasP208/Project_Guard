"""Real JWT verification, production configuration and worker transport checks."""
import io
import asyncio
import json
import os
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.requests import Request

import clerk_auth
import main
from nlp import plagiarism_worker


class ClerkVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def setUp(self):
        self.env = patch.dict(os.environ, {"APP_ENV": "development", "RENDER": "false", "CLERK_SECRET_KEY": "sk_test_fixture",
                                          "CLERK_JWT_KEY": self.public_key, "CLERK_AUTHORIZED_PARTIES": "http://localhost:5500"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def token(self, **claims):
        now = int(time.time())
        payload = {"sub": "user_verified", "sid": "sess_fixture", "iss": "https://fixture.clerk.accounts.dev",
                   "iat": now - 1, "nbf": now - 1, "exp": now + 120, "azp": "http://localhost:5500"}
        payload.update(claims)
        return jwt.encode(payload, self.key, algorithm="RS256")

    def verify(self, token=None):
        headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
        request = Request({"type": "http", "method": "GET", "scheme": "http", "path": "/api/me", "query_string": b"",
                           "headers": headers, "server": ("localhost", 8000)})
        return clerk_auth.require_clerk_user_id(request)

    def test_signed_session_is_verified_without_network(self):
        self.assertEqual(self.verify(self.token()), "user_verified")

    def test_missing_expired_wrong_origin_and_invalid_signature_are_rejected(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        decoded = jwt.decode(self.token(), options={"verify_signature": False})
        forged = jwt.encode(decoded, other_key, algorithm="RS256")
        for token in (None, self.token(exp=int(time.time()) - 60), self.token(azp="https://evil.example"), forged):
            with self.subTest(token_kind="missing" if token is None else "invalid"):
                with self.assertRaises(HTTPException) as failure:
                    self.verify(token)
                self.assertEqual(failure.exception.status_code, 401)

    def test_production_rejects_development_keys_http_wildcards_and_credentials(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            with self.assertRaises(RuntimeError):
                clerk_auth.validate_production_clerk_config()
            for origin in ("http://localhost:5500", "https://*.example.com", "https://user:password@example.com"):
                with patch.dict(os.environ, {"CLERK_AUTHORIZED_PARTIES": origin, "CORS_ALLOWED_ORIGINS": origin}):
                    with self.assertRaises(HTTPException):
                        clerk_auth._authorized_parties()
                    with self.assertRaises(RuntimeError):
                        main._configured_origins()
            with patch.dict(os.environ, {"CLERK_AUTHORIZED_PARTIES": "https://portal.example.com", "CORS_ALLOWED_ORIGINS": "https://portal.example.com"}):
                self.assertEqual(main._configured_origins(), ["https://portal.example.com"])


class WorkerTransportTests(unittest.TestCase):
    def test_worker_exceeding_deadline_is_killed(self):
        process = MagicMock(returncode=None)
        async def communicate():
            await asyncio.sleep(60)
        process.communicate = communicate
        process.wait = AsyncMock(return_value=-9)
        with patch.object(main.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)), patch.object(main, "MAX_PLAGIARISM_RUNTIME_SECONDS", 0.01):
            with self.assertRaises(HTTPException) as failure:
                asyncio.run(main.run_plagiarism_check_with_deadline("Idea", "Abstract", b"text", "test.txt"))
        self.assertEqual(failure.exception.status_code, 504)
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()

    def test_checker_diagnostics_do_not_corrupt_worker_json(self):
        checker = types.ModuleType("nlp.checker")
        def noisy_check(*args):
            print("[Checker] Running lexical and vector layers...")
            return {"plagiarism_percent": 5, "risk_level": "Low"}
        checker.run_plagiarism_check = noisy_check
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "request.json"
            upload = Path(folder) / "upload.txt"
            upload.write_bytes(b"Our academic project")
            path.write_text(json.dumps({"title": "Idea", "description": "Abstract", "filename": "upload.txt", "file_path": str(upload)}))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(sys.modules, {"nlp.checker": checker}), patch.object(sys, "argv", ["worker", str(path)]), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(plagiarism_worker.main(), 0)
            self.assertEqual(json.loads(stdout.getvalue()), {"plagiarism_percent": 5, "risk_level": "Low"})
            self.assertIn("[Checker]", stderr.getvalue())


class RateLimitTests(unittest.TestCase):
    def test_assignment_quota_is_shared_across_project_ids(self):
        with patch.object(main, "SessionLocal") as sessions, patch.object(main, "_last_rate_cleanup", 10000), patch.object(main.time, "time", return_value=10000):
            db = sessions.return_value.__enter__.return_value
            db.execute.return_value.scalar_one.return_value = 1
            for project_id in (1, 2):
                self.assertIsNone(main.rate_limit_retry_after("user_fixture", "127.0.0.1", "PATCH", f"/api/projects/{project_id}/assign"))
            keys = [call.args[0].compile().params["bucket_key"] for call in db.execute.call_args_list]
            self.assertEqual(keys[:2], keys[2:])


if __name__ == "__main__":
    unittest.main()
