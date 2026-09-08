import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import _start9_proxy_authenticated


class Start9ProxyAuthTest(unittest.TestCase):
    def test_requires_start9_trusted_https_user_header_and_password(self):
        with tempfile.TemporaryDirectory() as directory:
            password_file = Path(directory) / ".satsage-password"
            password_file.write_text("hash\\n", encoding="utf-8")
            state = SimpleNamespace(
                managed_by="start9",
                env_path=Path(directory) / ".env",
            )
            with mock.patch.dict(os.environ, {"SATSAGE_TRUST_PROXY": "1"}):
                headers = {"X-Forwarded-Proto": "https", "X-Forwarded-User": "admin"}
                self.assertTrue(_start9_proxy_authenticated(state, headers))
                self.assertFalse(_start9_proxy_authenticated(state, {"X-Forwarded-Proto": "https"}))
                self.assertFalse(_start9_proxy_authenticated(state, {"X-Forwarded-Proto": "https", "X-Forwarded-User": ""}))
                self.assertFalse(_start9_proxy_authenticated(state, {"X-Forwarded-User": "admin"}))


if __name__ == "__main__":
    unittest.main()
