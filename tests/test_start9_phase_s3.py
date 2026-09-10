"""Regressionen für Start9 Phase S3 (Betrieb/DoS)."""
from __future__ import annotations

import io
import os
import stat
import threading
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import server
from core.import_limits import ImportLimitError, unpack_zip_limited
from core.jobs import JobQuotaExceeded, JobRegistry


class TestStart9PhaseS3(unittest.TestCase):
    def test_schwere_jobs_haben_quota(self):
        registry = JobRegistry(max_parallel_heavy=1)
        block = threading.Event()
        job = registry.start("trace", "Test", lambda _job: block.wait(2))
        self.addCleanup(lambda: (block.set(), job.cancel()))
        with self.assertRaises(JobQuotaExceeded):
            registry.start("rescan", "Noch einer", lambda _job: None)

    def test_query_token_wird_redigiert(self):
        ziel = server._redact_url("/api/config?t=geheim&normal=ok")
        self.assertNotIn("geheim", ziel)
        self.assertIn("redigiert", ziel)
        self.assertIn("normal=ok", ziel)

    def test_zip_kompressionsverhaeltnis_wird_begrenzt(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("bombe.bin", b"A" * 2_000_000)
        with self.assertRaisesRegex(ImportLimitError, "Kompressionsverhältnis"):
            unpack_zip_limited(buffer.getvalue())

    def test_env_und_backup_werden_auf_0600_korrigiert(self):
        import sys

        if sys.platform == "win32":
            self.skipTest("chmod 0600 greift unter Windows nicht zuverlässig")
        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            backup = Path(tmp) / ".env.bak"
            env.write_text("NETWORK=regtest\\n", encoding="utf-8")
            backup.write_text("NETWORK=regtest\\n", encoding="utf-8")
            os.chmod(env, 0o644)
            os.chmod(backup, 0o644)
            server._pruefe_env_modus(env)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
