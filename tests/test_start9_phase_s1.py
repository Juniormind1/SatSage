import json
import stat
import sys
import urllib.error
import urllib.request

import server
from tests.test_api import ApiTestBasis


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TestStart9PhaseS1(ApiTestBasis):
    def request(self, path, *, method="GET", data=None, host=None, cookie=None, headers=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
        )
        request.add_header("Host", host or f"127.0.0.1:{self.port}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if cookie:
            request.add_header("Cookie", cookie)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, json.loads(response.read() or b"{}"), response.headers
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                body = {"raw": raw.decode("utf-8", "replace")}
            return error.code, body, error.headers

    def setUp(self):
        super().setUp()
        with self.env_pfad.open("a", encoding="utf-8") as env_file:
            env_file.write("SATSAGE_HOST_ALLOWLIST=remote.example\n")

    def setup_password(self, password="test-passwort"):
        return self.request(
            "/api/auth/setup", method="POST",
            data={"password": password, "confirm": password},
        )

    def test_ohne_passwort_bleibt_token_gueltig(self):
        status, _, _ = self.request(
            "/api/config", headers={"X-Satsage-Token": self.state.token}
        )
        self.assertEqual(status, 200)

    def test_query_bootstrap_laesst_token_in_der_url(self):
        """Client entfernt ?t= per history.replaceState — kein 303 mehr."""
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/?t={self.state.token}"
        )
        request.add_header("Host", f"127.0.0.1:{self.port}")
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            body = response.read()
        self.assertTrue(body.startswith(b"<!DOCTYPE html>") or b"<html" in body[:200])

    def test_setup_speichert_hash_und_remote_braucht_login(self):
        status, _, headers = self.setup_password()
        self.assertEqual(status, 201)
        password_file = self.env_pfad.parent / ".satsage-password"
        self.assertTrue(password_file.is_file())
        if sys.platform != "win32":
            self.assertEqual(stat.S_IMODE(password_file.stat().st_mode), 0o600)
        self.assertNotIn("test-passwort", password_file.read_text())

        status, _, _ = self.request("/api/config", host="remote.example")
        self.assertEqual(status, 403)
        status, payload, _ = self.request("/api/health", host="remote.example")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("satsage_session=", headers.get("Set-Cookie", ""))

    def test_login_setzt_cookie_und_erlaubt_config(self):
        self.setup_password()
        status, _, headers = self.request(
            "/api/auth/login", method="POST", host="remote.example",
            data={"password": "test-passwort"},
        )
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
        self.assertTrue(cookie.startswith("satsage_session="))
        status, _, _ = self.request("/api/config", host="remote.example", cookie=cookie)
        self.assertEqual(status, 200)

    def test_login_rate_limit(self):
        self.setup_password()
        for _ in range(5):
            status, _, _ = self.request(
                "/api/auth/login", method="POST", host="remote.example",
                data={"password": "falsch"},
            )
            self.assertEqual(status, 403)
        status, _, _ = self.request(
            "/api/auth/login", method="POST", host="remote.example",
            data={"password": "falsch"},
        )
        self.assertEqual(status, 429)

    def test_cookie_mutation_ohne_origin_abgelehnt(self):
        self.setup_password()
        _, _, headers = self.request(
            "/api/auth/login", method="POST", host="remote.example",
            data={"password": "test-passwort"},
        )
        cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
        status, _, _ = self.request(
            "/api/config/ui-lang", method="PUT", host="remote.example", cookie=cookie,
            data={"lang": "de"},
        )
        self.assertEqual(status, 403)

    def test_login_seite_hat_marke_und_dark_mode(self):
        self.setup_password()
        self.state.managed_by = "start9"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/login",
            method="GET",
        )
        request.add_header("Host", "remote.example")
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")
        self.assertIn("/img/sat-logo.png", html)
        self.assertIn("know your sats", html)
        self.assertIn("data-theme", html)
        self.assertIn("--grund:#1A1E22", html)
        self.assertIn("StartOS: Benutzername", html)
        self.assertIn('class="karte"', html)

        logo = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/img/sat-logo.png",
            method="GET",
        )
        logo.add_header("Host", "remote.example")
        with opener.open(logo, timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("image/", response.headers.get("Content-Type", ""))
            self.assertGreater(len(response.read()), 100)

        # UI-Shell bleibt hinter Auth.
        status, body, headers = self.request("/style.css", host="remote.example")
        self.assertEqual(status, 303)
        self.assertTrue(headers.get("Location", "").startswith("/login"))


if __name__ == "__main__":
    import unittest
    unittest.main()
