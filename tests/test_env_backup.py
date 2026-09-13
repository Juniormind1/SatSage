"""Start-Rotation .env.backup0 … .env.backup9 — keine Laufzeit-Zyklen."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from core.config import (
    ENV_BACKUP_SLOTS,
    EnvFile,
    env_backup_path,
    rotate_env_backups_at_start,
)


class TestEnvBackupRotation(unittest.TestCase):
    def test_rotation_schiebt_aeltere_zurueck(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("A=1\n", encoding="utf-8")
            for i in range(3):
                env_backup_path(env, i).write_text(f"OLD={i}\n", encoding="utf-8")

            ziel = rotate_env_backups_at_start(env, slots=4)
            self.assertEqual(ziel, env_backup_path(env, 0))
            self.assertEqual(env_backup_path(env, 0).read_text(encoding="utf-8"), "A=1\n")
            self.assertEqual(env_backup_path(env, 1).read_text(encoding="utf-8"), "OLD=0\n")
            self.assertEqual(env_backup_path(env, 2).read_text(encoding="utf-8"), "OLD=1\n")
            self.assertEqual(env_backup_path(env, 3).read_text(encoding="utf-8"), "OLD=2\n")
            # Original unverändert (Kopie, kein Move)
            self.assertEqual(env.read_text(encoding="utf-8"), "A=1\n")

    def test_ohne_env_keine_sicherung(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            self.assertIsNone(rotate_env_backups_at_start(env))

    def test_save_legt_kein_backup_an(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("A=1\n", encoding="utf-8")
            datei = EnvFile.load(env)
            datei.set("B", "2")
            self.assertIsNone(datei.save(backup=True))
            self.assertFalse(env_backup_path(env, 0).exists())
            self.assertFalse((Path(tmp) / ".env.bak").exists())
            self.assertIn("B=2", env.read_text(encoding="utf-8"))

    def test_slots_konstante(self):
        self.assertEqual(ENV_BACKUP_SLOTS, 10)


class TestEnvModusBackupSlots(unittest.TestCase):
    def test_chmod_auch_fuer_backup_slots(self):
        import sys

        if sys.platform == "win32":
            self.skipTest("chmod 0600 greift unter Windows nicht zuverlässig")
        import server

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("NETWORK=regtest\n", encoding="utf-8")
            b0 = env_backup_path(env, 0)
            b0.write_text("NETWORK=regtest\n", encoding="utf-8")
            os.chmod(env, 0o644)
            os.chmod(b0, 0o644)
            server._pruefe_env_modus(env)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(b0.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
