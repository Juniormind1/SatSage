"""Touch-ID-Diagnose: aussagekräftig, aber ohne Geheimnisse.

Der Nutzer testet am Mac, wir sehen nur seine Logs. Diese Tests sichern:

- Ein Testpasswort landet nie im Log, auch nicht bei Timeout, kaputter
  Helper-Antwort, Schlüsselbund-Fehler, falschem oder veraltetem Passwort,
  Ausnahmen beim Entsperren oder wenn der Helper es auf stderr/stdout
  schreibt.
- Der volle Account-Hash steht nie im Log, nur ein 8-Zeichen-Kopf.
- Die Zeilen enthalten Codes, Dauer, Gate-Entscheidung und Rate-Limit.
"""
from __future__ import annotations

import io
import logging
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from core import touchid
from tests.env_scramble_helpers import TEST_SCRAMBLE_PASSWORD
from tests.test_touchid_http import TouchIdHttpBasis

#: Unverwechselbar, mit Umlaut und Sonderzeichen wie ein echtes Passwort.
GEHEIM = "Lk7-Ü§geheim-Touch-9q"
#: Nur Code-Zeichen: würde jeden Zeichen-Filter passieren, darf trotzdem nie rein.
GEHEIM_ASCII = "Zq8LeakProbe-77x"
FALSCH = "falsches-Pw-3k2-Ö"

_HELPER = textwrap.dedent('''\
    #!{python}
    import json, sys, time
    modus = {modus!r}
    req = json.loads(sys.stdin.read())
    pw = req.get("password") or {geheim!r}
    if modus == "laut":
        # Böser Helper: schreibt Daten auf stderr, auch im eigenen Format.
        sys.stderr.write("satsage-touchid: cmd=unlock pw=" + {ascii!r} + "\\n")
        sys.stderr.write("Fatal: " + pw + "\\n")
        print(json.dumps({{"ok": True, "password": pw}}))
    elif modus == "garbage":
        print("kein json " + pw)
    elif modus == "keychain":
        sys.stderr.write("satsage-touchid: cmd=unlock code=keychain osstatus=-25293\\n")
        print(json.dumps({{"ok": False, "code": "keychain", "osstatus": -25293,
                          "message": pw, "la_name": pw, "domain_changed": "x"}}))
    elif modus == "invalidated":
        sys.stderr.write("satsage-touchid: cmd=unlock code=invalidated osstatus=0 domain_changed=ja\\n")
        print(json.dumps({{"ok": False, "code": "invalidated", "osstatus": 0, "domain_changed": True}}))
    elif modus == "cancel":
        print(json.dumps({{"ok": False, "code": "cancelled", "la_name": "userCancel", "la_code": -2}}))
    elif modus == "sleep":
        time.sleep(5)
    elif modus == "probe_aus":
        print(json.dumps({{"ok": True, "available": False, "reason": "not_available",
                          "la_name": "biometryNotEnrolled", "la_code": -7}}))
    else:
        print(json.dumps({{"ok": True, "password": pw, "available": True, "osstatus": 0,
                          "domain_changed": False}}))
    ''')


class _LogFang:
    """Alle Log-Records (alle Logger, DEBUG) plus touchid.log-Datei."""

    def __init__(self, testfall: unittest.TestCase, wurzel: Path) -> None:
        self.datei = wurzel / "logs" / "touchid.log"
        touchid.setze_log_pfad(self.datei)
        testfall.addCleanup(touchid.setze_log_pfad, None)
        self.puffer = io.StringIO()
        handler = logging.StreamHandler(self.puffer)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        wurzel_logger = logging.getLogger()
        alt = wurzel_logger.level
        wurzel_logger.addHandler(handler)
        wurzel_logger.setLevel(logging.DEBUG)

        def aufraeumen():
            wurzel_logger.removeHandler(handler)
            wurzel_logger.setLevel(alt)

        testfall.addCleanup(aufraeumen)

    def text(self) -> str:
        datei = self.datei.read_text(encoding="utf-8") if self.datei.exists() else ""
        return datei + "\n" + self.puffer.getvalue()


def _verboten(text: str, *geheim: str) -> list[str]:
    return [g for g in geheim if g and g in text]


class TestLogEventFilter(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fang = _LogFang(self, Path(tmp.name))

    def test_freitext_und_fremde_felder_werden_gefiltert(self):
        touchid.log_event("test", code=GEHEIM_ASCII + " x", nachricht=GEHEIM_ASCII, route="login")
        text = self.fang.text()
        self.assertNotIn(GEHEIM_ASCII, text)
        self.assertIn("nachricht=<gefiltert>", text)
        self.assertIn("route=login", text)

    def test_konto_kurz_nur_kopf(self):
        account = touchid.account_for("/x/.env")
        self.assertEqual(touchid.konto_kurz(account), account[:8] + "…")
        self.assertEqual(touchid.konto_kurz("kein-hash"), "-")

    def test_ohne_mac_kein_logfile(self):
        touchid.setze_log_pfad(None)
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIsNone(touchid.log_pfad())

    def test_stderr_nur_eigene_codes(self):
        self.assertEqual(
            touchid._stderr_diag(b"satsage-touchid: cmd=unlock code=failed la=authenticationFailed(-1)\n"),
            "cmd=unlock,code=failed,la=authenticationFailed(-1)",
        )
        self.assertEqual(touchid._stderr_diag(f"satsage-touchid: cmd=x pw={GEHEIM_ASCII}".encode()), "-")
        self.assertEqual(touchid._stderr_diag(f"Fatal error {GEHEIM_ASCII}".encode()), "-")


class TestHelperLogOhneGeheimnis(unittest.TestCase):
    """Echter MacHelperBackend-Pfad mit einem Python-Ersatz-Helper."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wurzel = Path(tmp.name)
        self.fang = _LogFang(self, self.wurzel)
        self.account = touchid.account_for(self.wurzel / ".env")

    def backend(self, modus: str) -> touchid.MacHelperBackend:
        helper = self.wurzel / f"helper-{modus}"
        helper.write_text(
            _HELPER.format(python=sys.executable, modus=modus, geheim=GEHEIM, ascii=GEHEIM_ASCII),
            encoding="utf-8",
        )
        helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
        return touchid.MacHelperBackend(helper, platform="darwin")

    def pruefe_sauber(self) -> str:
        text = self.fang.text()
        self.assertEqual(_verboten(text, GEHEIM, GEHEIM_ASCII, self.account), [], text)
        self.assertNotIn(str(Path.home()), text)
        self.assertNotIn(str(self.wurzel), text)
        for wort in ("laenge", "length", "password", "passwort="):
            self.assertNotIn(wort, text.lower())
        return text

    def test_enroll_und_unlock_ok(self):
        b = self.backend("ok")
        b.enroll(self.account, GEHEIM, "r")
        self.assertEqual(b.unlock(self.account, "r"), GEHEIM)
        text = self.pruefe_sauber()
        self.assertIn("cmd=enroll ergebnis=ok", text)
        self.assertIn("cmd=unlock ergebnis=ok", text)
        self.assertIn("domain_changed=nein", text)
        self.assertIn("osstatus=0", text)
        self.assertIn("dauer_ms=", text)
        self.assertIn(f"konto={self.account[:8]}…", text)
        self.assertIn("helper vorhanden=ja quelle=fest", text)

    def test_helper_schreibt_daten_auf_stderr(self):
        self.assertEqual(self.backend("laut").unlock(self.account, "r"), GEHEIM)
        text = self.pruefe_sauber()
        self.assertNotIn("Fatal", text)

    def test_kaputte_antwort(self):
        with self.assertRaises(touchid.TouchIdError) as ctx:
            self.backend("garbage").unlock(self.account, "r")
        self.assertEqual(ctx.exception.code, "error")
        self.assertNotIn(GEHEIM, str(ctx.exception))
        self.assertIn("ergebnis=keine_antwort", self.pruefe_sauber())

    def test_keychain_fehler_mit_daten_in_message(self):
        with self.assertRaises(touchid.TouchIdError) as ctx:
            self.backend("keychain").enroll(self.account, GEHEIM, "r")
        self.assertEqual(ctx.exception.code, "keychain")
        self.assertNotIn(GEHEIM, str(ctx.exception))
        text = self.pruefe_sauber()
        self.assertIn("ergebnis=keychain", text)
        self.assertIn("osstatus=-25293", text)
        self.assertIn("stderr=cmd=unlock,code=keychain,osstatus=-25293", text)
        self.assertNotIn("domain_changed=x", text)

    def test_domainstate_geaendert(self):
        with self.assertRaises(touchid.TouchIdError):
            self.backend("invalidated").unlock(self.account, "r")
        self.assertIn("domain_changed=ja", self.pruefe_sauber())

    def test_abbruch_mit_laerror(self):
        with self.assertRaises(touchid.TouchIdError):
            self.backend("cancel").unlock(self.account, "r")
        text = self.pruefe_sauber()
        self.assertIn("la_name=userCancel", text)
        self.assertIn("la_code=-2", text)

    def test_timeout(self):
        with mock.patch.object(touchid, "TIMEOUT_DIALOG", 0.5):
            with self.assertRaises(touchid.TouchIdError) as ctx:
                self.backend("sleep").enroll(self.account, GEHEIM, "r")
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertIsNone(ctx.exception.__cause__)
        text = self.pruefe_sauber()
        self.assertIn("ergebnis=timeout timeout_s=0.5", text)

    def test_helper_fehlt_und_nicht_startbar(self):
        weg = touchid.MacHelperBackend(self.wurzel / "gibtsnicht", platform="darwin")
        with self.assertRaises(touchid.TouchIdError):
            weg.enroll(self.account, GEHEIM, "r")
        kaputt = self.wurzel / "kaputt"
        kaputt.write_text("#!/gibt/es/nicht\n")
        kaputt.chmod(0o700)
        with self.assertRaises(touchid.TouchIdError) as ctx:
            touchid.MacHelperBackend(kaputt, platform="darwin").enroll(self.account, GEHEIM, "r")
        self.assertEqual(ctx.exception.code, "helper_missing")
        self.assertNotIn(str(self.wurzel), str(ctx.exception))
        text = self.pruefe_sauber()
        self.assertIn("helper vorhanden=nein", text)
        self.assertIn("errno=", text)

    def test_verfuegbarkeit_mit_grund_nur_bei_aenderung(self):
        b = self.backend("probe_aus")
        self.assertFalse(b.available())
        b.forget_probe()
        self.assertFalse(b.available())
        text = self.pruefe_sauber()
        self.assertIn("backend verfuegbar=nein grund=not_available plattform=darwin", text)
        self.assertEqual(text.count("backend verfuegbar="), 2)  # Datei + Logger, je einmal
        self.assertIn("la_name=biometryNotEnrolled", text)

    def test_invalidate_loggt_grund(self):
        env = self.wurzel / ".env"
        touchid.write_marker(env)
        fake = touchid.FakeBackend()
        touchid.set_backend(fake)
        self.addCleanup(touchid.set_backend, None)
        self.assertTrue(touchid.invalidate(env, grund="passwort_gesetzt"))
        self.assertIn("invalidiert grund=passwort_gesetzt eintrag_entfernt=ja", self.pruefe_sauber())


class TestHttpLogOhneGeheimnis(TouchIdHttpBasis):
    def setUp(self):
        super().setUp()
        self.fang = _LogFang(self, Path(self._tmp.name))

    def pruefe_sauber(self, *extra: str) -> str:
        text = self.fang.text()
        self.assertEqual(
            _verboten(text, TEST_SCRAMBLE_PASSWORD, FALSCH, GEHEIM, self.account, *extra), [], text,
        )
        return text

    def login(self):
        return self.roh("/api/auth/touchid", methode="POST", daten={})

    def test_ablauf_ok_falsch_stale_abbruch(self):
        cookie = self.mit_passwort()
        status, _, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST", cookie=cookie, daten={"password": FALSCH},
        )
        self.assertEqual(status, 403)
        self.state._login_failures.clear()
        status, body, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST", cookie=cookie,
            daten={"password": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(self.login()[0], 200)
        self.fake.next_error = "cancelled"
        self.assertEqual(self.login()[0], 403)
        self.fake.next_error = "failed"
        self.assertEqual(self.login()[0], 403)
        self.state._login_failures.clear()
        # Kopie im Schlüsselbund veraltet: stale, Eintrag weg.
        self.fake.store[self.account] = GEHEIM
        status, body, _ = self.login()
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("code"), "stale")
        text = self.pruefe_sauber()
        self.assertIn("gate route=enroll entscheidung=ok loopback=ja", text)
        self.assertIn("route route=enroll ergebnis=passwort_falsch http=403", text)
        self.assertIn("passwort_leer=nein", text)
        self.assertIn("route route=login ergebnis=ok http=200", text)
        self.assertIn("route route=login ergebnis=cancelled", text)
        self.assertIn("ergebnis=failed http=403", text)
        self.assertIn("fehlversuch=ja", text)
        self.assertIn("invalidiert grund=stale", text)
        self.assertIn("route route=login ergebnis=stale", text)

    def test_rate_limit_und_remote_gate(self):
        self.aktiviert()
        self.state._login_failures["127.0.0.1"] = [time.time()] * 10
        self.assertEqual(self.login()[0], 429)
        self.state._login_failures.clear()
        with mock.patch(
            "httpserver.handler_auth.HandlerAuthMixin._loopback_request", return_value=False,
        ):
            self.assertEqual(self.login()[0], 403)
        text = self.pruefe_sauber()
        self.assertIn("ergebnis=rate_limit http=429", text)
        self.assertIn("rate_limit=ja", text)
        self.assertIn("gate route=login entscheidung=remote loopback=nein", text)

    def test_ausnahme_beim_entsperren_ohne_text(self):
        self.aktiviert()
        with mock.patch(
            "server._scramble_unlock", side_effect=RuntimeError(f"kaputt {TEST_SCRAMBLE_PASSWORD}"),
        ):
            status, body, _ = self.login()
        self.assertEqual(status, 403)
        self.assertNotIn(TEST_SCRAMBLE_PASSWORD, str(body))
        text = self.pruefe_sauber()
        self.assertIn("ergebnis=entsperren_fehler", text)
        self.assertIn("ausnahme=RuntimeError", text)

    def test_passwort_aendern_invalidiert_mit_grund(self):
        cookie = self.aktiviert()
        status, body, _ = self.roh(
            "/api/auth/password", methode="POST", cookie=cookie,
            daten={
                "current_password": TEST_SCRAMBLE_PASSWORD,
                "new_password": "neues-Pw-Log-5551",
                "confirm": "neues-Pw-Log-5551",
            },
        )
        self.assertEqual(status, 200, body)
        text = self.pruefe_sauber("neues-Pw-Log-5551")
        self.assertIn("invalidiert grund=passwort_gesetzt", text)


if __name__ == "__main__":
    unittest.main()
