"""Touch-ID-API und Login-Seite (gemocktes Backend, ohne Mac).

Gates: Loopback, Origin, Sitzung, Rate-Limit, ein Dialog gleichzeitig,
Plattform. Invalidierung bei Passwort ändern/löschen/vergessen. Das
Passwort aus dem Schlüsselbund geht durch denselben Prüf- und
Entsperrweg wie ein getipptes.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from unittest import mock

from core import env_scramble as sc
from core import touchid
from tests.env_scramble_helpers import TEST_SCRAMBLE_PASSWORD
from tests.test_api import ApiTestBasis


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TouchIdHttpBasis(ApiTestBasis):
    def setUp(self):
        super().setUp()
        self.fake = touchid.FakeBackend()
        touchid.set_backend(self.fake)
        self.addCleanup(touchid.set_backend, None)
        self.account = touchid.account_for(self.state.env_path)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def roh(self, pfad, *, methode="GET", daten=None, cookie=None, origin=True, headers=None):
        url = f"http://127.0.0.1:{self.port}{pfad}"
        koerper = json.dumps(daten).encode() if daten is not None else None
        req = urllib.request.Request(url, data=koerper, method=methode)
        req.add_header("Host", f"127.0.0.1:{self.port}")
        if daten is not None:
            req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", cookie)
        if origin:
            req.add_header("Origin", self.origin)
        for name, wert in (headers or {}).items():
            req.add_header(name, wert)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=10) as antwort:
                text = antwort.read()
                status, kopf = antwort.status, antwort.headers
        except urllib.error.HTTPError as fehler:
            text = fehler.read()
            status, kopf = fehler.code, fehler.headers
        try:
            body = json.loads(text or b"{}")
        except json.JSONDecodeError:
            body = {"raw": text.decode("utf-8", "replace")}
        return status, body, kopf

    @staticmethod
    def keks(headers) -> str:
        alle = headers.get_all("Set-Cookie") if headers is not None else None
        return ((alle or [""])[0] or "").split(";", 1)[0]

    def mit_passwort(self) -> str:
        status, body, kopf = self.roh(
            "/api/auth/setup", methode="POST",
            daten={"password": TEST_SCRAMBLE_PASSWORD, "confirm": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 201, body)
        return self.keks(kopf)

    def aktiviert(self) -> str:
        cookie = self.mit_passwort()
        status, body, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST", cookie=cookie,
            daten={"password": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 200, body)
        return cookie


class TestTouchIdStatusUndLoginSeite(TouchIdHttpBasis):
    def test_status_ohne_backend(self):
        self.fake.is_available = False
        self.mit_passwort()
        status, body, _ = self.roh("/api/auth/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["touchid"], {"available": False, "enrolled": False})

    def test_status_remote_nie_verfuegbar(self):
        self.aktiviert()
        with mock.patch("server.Handler._loopback_request", return_value=False):
            status, body, _ = self.roh("/api/auth/status")
        self.assertEqual(body["touchid"], {"available": False, "enrolled": False})

    def test_status_managed_plattform_nie(self):
        self.aktiviert()
        for plattform in ("start9", "umbrel", "specter"):
            with mock.patch.object(self.state, "managed_by", plattform):
                status, body, _ = self.roh("/api/auth/status")
            self.assertFalse(body["touchid"]["available"], plattform)

    def test_login_seite_ohne_touchid_unveraendert(self):
        self.fake.is_available = False
        self.mit_passwort()
        status, body, _ = self.roh("/login")
        html = body["raw"]
        self.assertNotIn('id="touchid-login"', html)
        self.assertNotIn('id="touchid-aktivieren"', html)

    def test_login_seite_bietet_aktivieren_an_default_aus(self):
        self.mit_passwort()
        _, body, _ = self.roh("/login")
        html = body["raw"]
        self.assertIn('id="touchid-aktivieren"', html)
        self.assertNotIn("checked", html.split('id="touchid-aktivieren"', 1)[1][:40])
        self.assertNotIn('id="touchid-login"', html)

    def test_login_seite_zeigt_knopf_wenn_aktiv(self):
        self.aktiviert()
        _, body, _ = self.roh("/login")
        html = body["raw"]
        self.assertIn('id="touchid-login"', html)
        self.assertNotIn('id="touchid-aktivieren"', html)
        # Passwortfeld bleibt immer da.
        self.assertIn('id="password"', html)

    def test_login_seite_englisch(self):
        self.aktiviert()
        _, body, _ = self.roh("/login", headers={"Accept-Language": "en"})
        self.assertIn("Unlock with Touch ID", body["raw"])


class TestTouchIdEnroll(TouchIdHttpBasis):
    def test_ohne_sitzung_verboten(self):
        self.mit_passwort()
        status, body, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST",
            daten={"password": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 403, body)
        self.assertFalse(touchid.is_enrolled(self.state.env_path))

    def test_ohne_origin_verboten(self):
        cookie = self.mit_passwort()
        status, body, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST", cookie=cookie, origin=False,
            daten={"password": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 403, body)
        self.assertEqual(self.fake.store, {})

    def test_fremde_origin_verboten(self):
        cookie = self.mit_passwort()
        status, body, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST", cookie=cookie, origin=False,
            headers={"Origin": "https://evil.example"},
            daten={"password": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 403, body)

    def test_falsches_passwort(self):
        cookie = self.mit_passwort()
        status, body, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST", cookie=cookie,
            daten={"password": "falsch-falsch"},
        )
        self.assertEqual(status, 403, body)
        self.assertEqual(self.fake.store, {})
        self.assertFalse(touchid.is_enrolled(self.state.env_path))
        self.assertTrue(self.state._login_failures)

    def test_remote_verboten(self):
        cookie = self.mit_passwort()
        with mock.patch("server.Handler._loopback_request", return_value=False):
            status, body, _ = self.roh(
                "/api/auth/touchid/enroll", methode="POST", cookie=cookie,
                daten={"password": TEST_SCRAMBLE_PASSWORD},
            )
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("code"), "remote")

    def test_abbruch_im_dialog(self):
        cookie = self.mit_passwort()
        self.fake.next_error = "cancelled"
        status, body, _ = self.roh(
            "/api/auth/touchid/enroll", methode="POST", cookie=cookie,
            daten={"password": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("code"), "cancelled")
        self.assertFalse(touchid.is_enrolled(self.state.env_path))

    def test_erfolg(self):
        self.aktiviert()
        self.assertTrue(touchid.is_enrolled(self.state.env_path))
        self.assertEqual(self.fake.store, {self.account: TEST_SCRAMBLE_PASSWORD})
        status, body, _ = self.roh("/api/auth/status")
        self.assertEqual(body["touchid"], {"available": True, "enrolled": True})


class TestTouchIdLogin(TouchIdHttpBasis):
    def neu_starten(self):
        """Wie nach Server-Neustart: keine Sitzung, Konfiguration gesperrt."""
        with self.state._auth_lock:
            self.state.sessions.clear()
        sc.clear_session_key()
        self.state.env_scramble_unlocked = False

    def test_login_und_entsperren(self):
        self.aktiviert()
        self.neu_starten()
        with mock.patch("server._verify_password", wraps=__import__("server")._verify_password) as pruef, \
             mock.patch("server._scramble_unlock", wraps=__import__("server")._scramble_unlock) as entsperr:
            status, body, kopf = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["authenticated"])
        self.assertFalse(body["unlock_needed"])
        pruef.assert_called_once()
        self.assertEqual(pruef.call_args.args[0], TEST_SCRAMBLE_PASSWORD)
        entsperr.assert_called_once()
        self.assertTrue(self.state.env_scramble_unlocked)
        self.assertIsNotNone(sc.get_session_key())
        cookie = self.keks(kopf)
        self.assertTrue(cookie.startswith("satsage_session="), cookie)
        _, status_body, _ = self.roh("/api/auth/status", cookie=cookie)
        self.assertTrue(status_body["authenticated"])
        self.assertNotIn(TEST_SCRAMBLE_PASSWORD, json.dumps(body))

    def test_ohne_origin(self):
        self.aktiviert()
        self.neu_starten()
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={}, origin=False)
        self.assertEqual(status, 403, body)
        self.assertEqual(self.fake.calls[-1][0], "enroll", "kein Dialog ohne Origin")

    def test_remote(self):
        self.aktiviert()
        self.neu_starten()
        with mock.patch("server.Handler._loopback_request", return_value=False):
            status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("code"), "remote")
        self.assertNotIn(("unlock", self.account), self.fake.calls)

    def test_nicht_aktiviert(self):
        self.mit_passwort()
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("code"), "not_enrolled")

    def test_backend_weg(self):
        self.aktiviert()
        self.fake.is_available = False
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 404, body)
        self.assertEqual(body.get("code"), "not_available")

    def test_abbruch_zaehlt_nicht_als_fehlversuch(self):
        self.aktiviert()
        self.neu_starten()
        self.state._login_failures.clear()
        self.fake.next_error = "cancelled"
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 403, body)
        self.assertEqual(body.get("code"), "cancelled")
        self.assertEqual(self.state._login_failures.get("127.0.0.1", []), [])
        self.assertTrue(touchid.is_enrolled(self.state.env_path))

    def test_fingerabdruck_falsch_zaehlt(self):
        self.aktiviert()
        self.neu_starten()
        self.state._login_failures.clear()
        self.fake.next_error = "failed"
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 403, body)
        self.assertEqual(len(self.state._login_failures.get("127.0.0.1", [])), 1)

    def test_rate_limit(self):
        self.aktiviert()
        self.neu_starten()
        self.state._login_failures["127.0.0.1"] = [time.time()] * 10
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 429, body)
        self.assertNotIn(("unlock", self.account), self.fake.calls)

    def test_fingerabdruecke_geaendert_invalidiert(self):
        self.aktiviert()
        self.neu_starten()
        self.fake.next_error = "invalidated"
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("code"), "invalidated")
        self.assertFalse(touchid.is_enrolled(self.state.env_path))
        self.assertNotIn(self.account, self.fake.store)

    def test_veraltetes_passwort_loescht_eintrag(self):
        self.aktiviert()
        self.neu_starten()
        self.fake.store[self.account] = "altes-passwort-xyz"
        status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("code"), "stale")
        self.assertFalse(touchid.is_enrolled(self.state.env_path))
        self.assertNotIn(self.account, self.fake.store)
        self.assertFalse(self.state.env_scramble_unlocked)

    def test_nur_ein_dialog(self):
        self.aktiviert()
        self.neu_starten()
        with touchid.dialog_slot():
            status, body, _ = self.roh("/api/auth/touchid", methode="POST", daten={})
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("code"), "busy")


class TestTouchIdInvalidierung(TouchIdHttpBasis):
    def test_passwort_aendern(self):
        cookie = self.aktiviert()
        status, body, _ = self.roh(
            "/api/auth/password", methode="POST", cookie=cookie,
            daten={
                "current_password": TEST_SCRAMBLE_PASSWORD,
                "new_password": "neues-testpasswort-1",
                "confirm": "neues-testpasswort-1",
            },
        )
        self.assertEqual(status, 200, body)
        self.assertFalse(touchid.is_enrolled(self.state.env_path))
        self.assertNotIn(self.account, self.fake.store)

    def test_passwort_aendern_ueber_einstellungen(self):
        cookie = self.aktiviert()
        status, body, _ = self.roh(
            "/api/config/app-password", methode="PUT", cookie=cookie,
            daten={
                "current_password": TEST_SCRAMBLE_PASSWORD,
                "new_password": "neues-testpasswort-2",
                "confirm": "neues-testpasswort-2",
            },
        )
        self.assertEqual(status, 200, body)
        self.assertFalse(touchid.is_enrolled(self.state.env_path))

    def test_passwort_loeschen(self):
        cookie = self.aktiviert()
        status, body, _ = self.roh(
            "/api/auth/password", methode="DELETE", cookie=cookie,
            daten={"current_password": TEST_SCRAMBLE_PASSWORD},
        )
        self.assertEqual(status, 200, body)
        self.assertFalse(touchid.is_enrolled(self.state.env_path))
        self.assertNotIn(self.account, self.fake.store)

    def test_passwort_vergessen(self):
        self.aktiviert()
        with self.state._auth_lock:
            self.state.sessions.clear()
        sc.clear_session_key()
        status, body, _ = self.roh(
            "/api/auth/forgot", methode="POST", daten={"confirm": "start-over"},
        )
        self.assertEqual(status, 200, body)
        self.assertFalse(touchid.is_enrolled(self.state.env_path))
        self.assertNotIn(self.account, self.fake.store)

    def test_deaktivieren(self):
        cookie = self.aktiviert()
        status, body, _ = self.roh("/api/auth/touchid/remove", methode="POST", cookie=cookie, daten={})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["touchid"], {"available": True, "enrolled": False})
        self.assertNotIn(self.account, self.fake.store)

    def test_deaktivieren_per_delete_braucht_sitzung(self):
        self.aktiviert()
        status, body, _ = self.roh("/api/auth/touchid", methode="DELETE")
        self.assertEqual(status, 403, body)
        self.assertTrue(touchid.is_enrolled(self.state.env_path))


if __name__ == "__main__":
    import unittest

    unittest.main()
