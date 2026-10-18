import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_frontend


class FrontendBuildCspTests(unittest.TestCase):
    def test_build_generates_admin_csp_with_only_configured_app_and_clerk_hosts(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.dict(os.environ, {
                "PROJECT_GUARD_API_BASE_URL": "https://api.example.edu",
                "PROJECT_GUARD_CLERK_FAPI_HOST": "clerk.example.edu",
            }), patch.object(sys, "argv", ["build_frontend.py", output_dir]):
                build_frontend.main()

            headers = (Path(output_dir) / "_headers").read_text(encoding="utf-8")
            self.assertTrue(headers.startswith("/admin.html\n  Content-Security-Policy: "))
            self.assertIn("https://api.example.edu", headers)
            self.assertIn("https://clerk.example.edu", headers)
            self.assertIn("script-src-attr 'none'", headers)
            self.assertIn("object-src 'none'", headers)
            self.assertIn("frame-ancestors 'none'", headers)
            self.assertNotIn("'unsafe-eval'", headers)
            self.assertNotIn("'unsafe-inline'", headers.split("script-src ", 1)[1].split(";", 1)[0])
            self.assertNotIn("https:;", headers)
            self.assertTrue((Path(output_dir) / "admin.html").is_file())

    def test_build_rejects_missing_or_wildcard_clerk_host(self):
        with tempfile.TemporaryDirectory() as output_dir:
            for clerk_host in ("", "*.clerk.accounts.dev", "https://clerk.example.edu/path"):
                with self.subTest(clerk_host=clerk_host):
                    with patch.dict(os.environ, {
                        "PROJECT_GUARD_API_BASE_URL": "https://api.example.edu",
                        "PROJECT_GUARD_CLERK_FAPI_HOST": clerk_host,
                    }), patch.object(sys, "argv", ["build_frontend.py", output_dir]):
                        with self.assertRaises(SystemExit):
                            build_frontend.main()


if __name__ == "__main__":
    unittest.main()
