"""Tests: .env scrambled (SSGB1) oder Klartext — eine Datei."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from core import env_scramble as sc
from core.config import EnvFile
from tests.env_scramble_helpers import (
    TEST_SCRAMBLE_PASSWORD,
    clear_scramble_session,
    read_env_plaintext,
    write_env_scrambled,
)

PW = TEST_SCRAMBLE_PASSWORD
PW_ALT = "tralala-alt-999"
PW_NEU = "tralala-neu-888"
PW_FALSCH = "nicht-tralala"


class TestEnvScramble(unittest.TestCase):
    def setUp(self):
        clear_scramble_session()

    def tearDown(self):
        clear_scramble_session()

    def test_roundtrip_encrypt_decrypt(self):
        plain = "WALLET_0_NAME=Test\nWALLET_0_XPUB=zpubabc\nFOO=bar\n"
        blob, key_enc = sc.encrypt_env_text(plain, PW)
        self.assertTrue(blob.startswith(sc.MAGIC))
        out, key = sc.decrypt_env_blob(blob, PW)
        self.assertTrue(sc.structural_equal(out, plain))
        self.assertEqual(key, key_enc)
        with self.assertRaises(sc.ScrambleError):
            sc.decrypt_env_blob(blob, PW_FALSCH)

    def test_enable_overwrites_env_as_cipher(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            plain = "A=1\nB=two\n"
            env_path.write_text(plain, encoding="utf-8")
            write_env_scrambled(env_path, plain, password=PW)
            self.assertTrue(env_path.is_file())
            self.assertTrue(sc.is_env_scrambled(env_path))
            self.assertFalse(sc.legacy_gobbledigook_path(env_path).is_file())
            gelesen = read_env_plaintext(env_path, password=PW)
            self.assertTrue(sc.structural_equal(gelesen, plain))
            sc.disable_scramble(env_path, PW)
            self.assertTrue(env_path.is_file())
            self.assertFalse(sc.is_env_scrambled(env_path))
            self.assertTrue(
                sc.structural_equal(env_path.read_text(encoding="utf-8"), plain)
            )

    def test_envfile_save_load_scrambled_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env = EnvFile(path=env_path, lines=["NAME=Alice", "X=1"])
            env.save()
            self.assertFalse(sc.is_env_scrambled(env_path))
            write_env_scrambled(env_path, env.render(), password=PW)
            self.assertTrue(sc.is_env_scrambled(env_path))
            env2 = EnvFile.load(env_path)
            self.assertFalse(env2.scramble_locked)
            self.assertEqual(env2.get("NAME"), "Alice")
            env2.set("NAME", "Bob")
            env2.save()
            self.assertTrue(sc.is_env_scrambled(env_path))
            env3 = EnvFile.load(env_path)
            self.assertEqual(env3.get("NAME"), "Bob")
            self.assertIn("NAME=Bob", read_env_plaintext(env_path, password=PW))
            clear_scramble_session()
            locked = EnvFile.load(env_path)
            self.assertTrue(locked.scramble_locked)
            self.assertFalse(bool(locked.get("NAME")))

    def test_session_key_shared_across_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            plain = "K=v\n"
            write_env_scrambled(env_path, plain, password=PW)
            seen: list[str] = []

            def worker():
                seen.append(sc.load_plaintext_or_scramble(env_path))

            t = threading.Thread(target=worker)
            t.start()
            t.join(timeout=5)
            self.assertEqual(len(seen), 1)
            self.assertTrue(sc.structural_equal(seen[0], plain))

    def test_migrate_legacy_gobbledigook(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            plain = "A=1\n"
            # Altes Schema: Klartext .env + Neben-Cipher
            env_path.write_text(plain, encoding="utf-8")
            blob, _ = sc.encrypt_env_text(plain, PW)
            legacy = sc.legacy_gobbledigook_path(env_path)
            legacy.write_bytes(blob)
            clear_scramble_session()
            out = sc.unlock_with_password(env_path, PW)
            self.assertTrue(sc.structural_equal(out, plain))
            self.assertTrue(sc.is_env_scrambled(env_path))
            self.assertFalse(legacy.is_file())

    def test_change_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            plain = "K=v\n"
            write_env_scrambled(env_path, plain, password=PW_ALT)
            sc.change_scramble_password(env_path, PW_ALT, PW_NEU)
            self.assertTrue(sc.is_env_scrambled(env_path))
            with self.assertRaises(sc.ScrambleError):
                sc.read_scrambled(env_path, PW_ALT)
            self.assertTrue(
                sc.structural_equal(
                    read_env_plaintext(env_path, password=PW_NEU), plain
                )
            )

    def test_backups_scramble_and_unscramble(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            plain = "MAIN=1\n"
            env_path.write_text(plain, encoding="utf-8")
            b0 = env_path.with_name(".env.backup0")
            b1 = env_path.with_name(".env.backup1")
            b0.write_text("OLD=a\n", encoding="utf-8")
            b1.write_text("OLD=b\n", encoding="utf-8")
            write_env_scrambled(env_path, plain, password=PW)
            self.assertTrue(sc.is_env_scrambled(env_path))
            self.assertTrue(sc.is_env_scrambled(b0))
            self.assertTrue(sc.is_env_scrambled(b1))
            p0, _ = sc.decrypt_env_blob(b0.read_bytes(), PW)
            p1, _ = sc.decrypt_env_blob(b1.read_bytes(), PW)
            self.assertTrue(sc.structural_equal(p0, "OLD=a\n"))
            self.assertTrue(sc.structural_equal(p1, "OLD=b\n"))
            sc.change_scramble_password(env_path, PW, PW_NEU)
            self.assertTrue(sc.is_env_scrambled(b0))
            with self.assertRaises(sc.ScrambleError):
                sc.decrypt_env_blob(b0.read_bytes(), PW)
            p0b, _ = sc.decrypt_env_blob(b0.read_bytes(), PW_NEU)
            self.assertTrue(sc.structural_equal(p0b, "OLD=a\n"))
            sc.disable_scramble(env_path, PW_NEU)
            self.assertFalse(sc.is_env_scrambled(env_path))
            self.assertFalse(sc.is_env_scrambled(b0))
            self.assertEqual(b0.read_text(encoding="utf-8").strip(), "OLD=a")
            self.assertEqual(b1.read_text(encoding="utf-8").strip(), "OLD=b")

    def test_structural_equal_ignores_order_comments(self):
        a = "# c\nA=1\nB=2\n"
        b = "B=2\nA=1\n"
        self.assertTrue(sc.structural_equal(a, b))
        self.assertFalse(sc.structural_equal(a, "A=1\nB=3\n"))


if __name__ == "__main__":
    unittest.main()
