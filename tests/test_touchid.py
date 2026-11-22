"""core.touchid: Backend-Protokoll, Marker, Gates — ohne Mac.

Das Swift-Hilfsprogramm wird durch ein kleines Python-Skript ersetzt, das
dasselbe stdin/stdout-JSON spricht. So prüfen die Tests den echten
``MacHelperBackend``-Pfad (subprocess, Timeout, Fehlercodes) auf Linux.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

from core import touchid

_FAKE_HELPER = textwrap.dedent('''\
    #!{python}
    import json, sys, time
    from pathlib import Path
    log = Path({log!r})
    raw = sys.stdin.read()
    req = json.loads(raw)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({{"argv": sys.argv[1:], "req": req}}) + "\\n")
    store = Path({store!r})
    data = json.loads(store.read_text()) if store.exists() else {{}}
    modus = data.get("_modus", "")
    if modus == "sleep":
        time.sleep(5)
    if modus == "garbage":
        print("kein json")
        sys.exit(0)
    if modus.startswith("code:"):
        print(json.dumps({{"ok": False, "code": modus[5:]}}))
        sys.exit(0)
    cmd = req.get("cmd")
    if cmd == "probe":
        print(json.dumps({{"ok": True, "available": data.get("_available", True)}}))
    elif cmd == "enroll":
        data[req["account"]] = req["password"]
        store.write_text(json.dumps(data))
        print(json.dumps({{"ok": True}}))
    elif cmd == "unlock":
        if req["account"] not in data:
            print(json.dumps({{"ok": False, "code": "not_found"}}))
        else:
            print(json.dumps({{"ok": True, "password": data[req["account"]]}}))
    elif cmd == "remove":
        if data.pop(req["account"], None) is None:
            print(json.dumps({{"ok": False, "code": "not_found"}}))
        else:
            store.write_text(json.dumps(data))
            print(json.dumps({{"ok": True}}))
    else:
        print(json.dumps({{"ok": False, "code": "error"}}))
    ''')


class _HelperBasis(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.wurzel = Path(self._tmp.name)
        self.log = self.wurzel / "aufrufe.jsonl"
        self.store = self.wurzel / "store.json"
        self.helper = self.wurzel / touchid.HELPER_NAME
        self.helper.write_text(
            _FAKE_HELPER.format(python=sys.executable, log=str(self.log), store=str(self.store)),
            encoding="utf-8",
        )
        self.helper.chmod(self.helper.stat().st_mode | stat.S_IXUSR)
        self.backend = touchid.MacHelperBackend(self.helper, platform="darwin")
        self.account = touchid.account_for(self.wurzel / ".env")

    def modus(self, wert: str) -> None:
        daten = json.loads(self.store.read_text()) if self.store.exists() else {}
        daten["_modus"] = wert
        self.store.write_text(json.dumps(daten))

    def aufrufe(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(z) for z in self.log.read_text().splitlines()]


class TestAccountUndMarker(unittest.TestCase):
    def test_account_ist_sha256_des_absoluten_pfads(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = touchid.account_for(Path(tmp) / ".env")
            b = touchid.account_for(Path(tmp) / "x" / ".." / ".env")
            c = touchid.account_for(Path(tmp) / "anders" / ".env")
        self.assertEqual(len(a), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in a))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotIn(tmp, a)

    def test_marker_roundtrip_und_fremder_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            self.assertFalse(touchid.is_enrolled(env))
            touchid.write_marker(env)
            self.assertTrue(touchid.is_enrolled(env))
            inhalt = json.loads(touchid.marker_path(env).read_text())
            self.assertNotIn("password", json.dumps(inhalt).lower())
            # Marker aus einem anderen Datenordner zählt nicht.
            inhalt["account"] = "0" * 64
            touchid.marker_path(env).write_text(json.dumps(inhalt))
            self.assertFalse(touchid.is_enrolled(env))
            touchid.remove_marker(env)
            touchid.remove_marker(env)  # zweimal ohne Fehler
            self.assertFalse(touchid.marker_path(env).exists())
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])


class TestPlattformGate(unittest.TestCase):
    def test_nicht_macos_nie_verfuegbar_und_kein_subprocess(self):
        for plattform in ("linux", "win32", "cygwin"):
            backend = touchid.MacHelperBackend(Path(sys.executable), platform=plattform)
            with mock.patch("core.touchid.subprocess.run") as run:
                self.assertFalse(backend.available())
            run.assert_not_called()

    def test_standard_backend_auf_dieser_box(self):
        if sys.platform == "darwin":
            self.skipTest("nur außerhalb macOS")
        touchid.set_backend(None)
        self.addCleanup(touchid.set_backend, None)
        self.assertIsInstance(touchid.get_backend(), touchid.MacHelperBackend)
        self.assertFalse(touchid.get_backend().available())

    def test_fehlendes_hilfsprogramm(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = touchid.MacHelperBackend(Path(tmp) / "fehlt", platform="darwin")
            self.assertFalse(backend.available())
            with self.assertRaises(touchid.TouchIdError) as ctx:
                backend.unlock("a" * 64, "x")
            self.assertEqual(ctx.exception.code, "helper_missing")

    def test_env_override_wird_gefunden(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "h"
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o700)
            with mock.patch.dict(os.environ, {touchid.ENV_HELPER: str(helper)}):
                self.assertEqual(touchid.MacHelperBackend(platform="darwin").helper_path(), helper)


class TestMacHelperBackend(_HelperBasis):
    def test_probe_und_cache(self):
        self.assertTrue(self.backend.available())
        self.assertTrue(self.backend.available())
        self.assertEqual(len(self.aufrufe()), 1, "Probe wird gecacht")
        self.backend.forget_probe()
        self.store.write_text(json.dumps({"_available": False}))
        self.assertFalse(self.backend.available())

    def test_enroll_unlock_remove_passwort_nur_ueber_stdin(self):
        geheim = "touchid-testpasswort-7c1e"
        self.backend.enroll(self.account, geheim, "grund")
        self.assertEqual(self.backend.unlock(self.account, "grund"), geheim)
        self.backend.remove(self.account)
        self.backend.remove(self.account)  # not_found ist beim Entfernen ok
        with self.assertRaises(touchid.TouchIdError) as ctx:
            self.backend.unlock(self.account, "grund")
        self.assertEqual(ctx.exception.code, "not_found")
        for aufruf in self.aufrufe():
            self.assertEqual(aufruf["argv"], [], "argv bleibt leer")
            self.assertEqual(aufruf["req"]["v"], touchid.PROTOCOL_VERSION)
        enroll = [a for a in self.aufrufe() if a["req"]["cmd"] == "enroll"][0]
        self.assertEqual(enroll["req"]["password"], geheim)
        self.assertEqual(enroll["req"]["account"], self.account)

    def test_fehlercodes_werden_durchgereicht(self):
        for code in ("cancelled", "failed", "invalidated", "locked_out", "not_available"):
            self.modus(f"code:{code}")
            with self.assertRaises(touchid.TouchIdError) as ctx:
                self.backend.unlock(self.account, "grund")
            self.assertEqual(ctx.exception.code, code)
        self.modus("code:unbekannt-xyz")
        with self.assertRaises(touchid.TouchIdError) as ctx:
            self.backend.unlock(self.account, "grund")
        self.assertEqual(ctx.exception.code, "error")

    def test_kaputte_antwort(self):
        self.modus("garbage")
        with self.assertRaises(touchid.TouchIdError) as ctx:
            self.backend.unlock(self.account, "grund")
        self.assertEqual(ctx.exception.code, "error")

    def test_timeout_beendet_hilfsprogramm(self):
        self.modus("sleep")
        with mock.patch.object(touchid, "TIMEOUT_DIALOG", 0.5):
            with self.assertRaises(touchid.TouchIdError) as ctx:
                self.backend.unlock(self.account, "grund")
        self.assertEqual(ctx.exception.code, "timeout")

    def test_leeres_passwort_wird_nicht_gespeichert(self):
        with self.assertRaises(touchid.TouchIdError):
            self.backend.enroll(self.account, "", "grund")
        self.assertEqual(self.aufrufe(), [])


class TestDialogUndInvalidierung(unittest.TestCase):
    def setUp(self):
        self.fake = touchid.FakeBackend()
        touchid.set_backend(self.fake)
        self.addCleanup(touchid.set_backend, None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.env = Path(self._tmp.name) / ".env"

    def test_nur_ein_dialog_gleichzeitig(self):
        with touchid.dialog_slot():
            with self.assertRaises(touchid.TouchIdError) as ctx:
                with touchid.dialog_slot():
                    pass
            self.assertEqual(ctx.exception.code, "busy")
        with touchid.dialog_slot():
            pass

    def test_dialog_slot_ueber_threads(self):
        frei = threading.Event()
        belegt = threading.Event()

        def halten():
            with touchid.dialog_slot():
                belegt.set()
                frei.wait(5)

        t = threading.Thread(target=halten)
        t.start()
        belegt.wait(5)
        with self.assertRaises(touchid.TouchIdError):
            with touchid.dialog_slot():
                pass
        frei.set()
        t.join(5)

    def test_invalidate_ohne_marker_ruft_nichts(self):
        self.assertFalse(touchid.invalidate(self.env))
        self.assertEqual(self.fake.calls, [])

    def test_invalidate_mit_marker(self):
        account = touchid.account_for(self.env)
        self.fake.store[account] = "pw"
        touchid.write_marker(self.env)
        self.assertTrue(touchid.invalidate(self.env))
        self.assertFalse(touchid.marker_path(self.env).exists())
        self.assertNotIn(account, self.fake.store)

    def test_remove_entry_auch_ohne_marker(self):
        account = touchid.account_for(self.env)
        self.fake.store[account] = "pw"
        touchid.remove_entry(self.env)
        self.assertNotIn(account, self.fake.store)


if __name__ == "__main__":
    unittest.main()
