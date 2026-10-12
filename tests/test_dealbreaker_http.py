"""Dealbreaker T9, Auth-Rest, CSRF am Desktop-Loopback.

Ohne Node. Auf ``dev-juniormind`` optional, auf ``main`` Pflicht.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest import mock

from tests.env_scramble_helpers import (
    TEST_SCRAMBLE_PASSWORD,
    read_env_plaintext,
    write_env_scrambled,
)
from tests.hart import skip_wenn_dev
from tests.test_api import ApiTestBasis


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@skip_wenn_dev()
class TestDealbreakerHttp(ApiTestBasis):
    def roh(
        self, pfad, *, methode="GET", daten=None, token=False, cookie=None,
        headers=None, host=None,
    ):
        url = f"http://127.0.0.1:{self.port}{pfad}"
        koerper = json.dumps(daten).encode() if daten is not None else None
        req = urllib.request.Request(url, data=koerper, method=methode)
        req.add_header("Host", host or f"127.0.0.1:{self.port}")
        if daten is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("X-Satsage-Token", self.state.token)
        if cookie:
            req.add_header("Cookie", cookie)
        for name, wert in (headers or {}).items():
            req.add_header(name, wert)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=10) as antwort:
                rohtext = antwort.read()
                try:
                    body = json.loads(rohtext or b"{}")
                except json.JSONDecodeError:
                    body = {"raw": rohtext.decode("utf-8", "replace")}
                return antwort.status, body, antwort.headers
        except urllib.error.HTTPError as fehler:
            rohtext = fehler.read()
            try:
                body = json.loads(rohtext or b"{}")
            except json.JSONDecodeError:
                body = {"raw": rohtext.decode("utf-8", "replace")}
            return fehler.code, body, fehler.headers

    @staticmethod
    def _cookie(headers) -> str:
        if headers is None:
            return ""
        alle = headers.get_all("Set-Cookie") if hasattr(headers, "get_all") else None
        zeile = (alle or [headers.get("Set-Cookie")])[0] or ""
        return zeile.split(";", 1)[0]

    def _mit_passwort(self):
        status, body, headers = self.roh(
            "/api/auth/setup",
            methode="POST",
            daten={
                "password": TEST_SCRAMBLE_PASSWORD,
                "confirm": TEST_SCRAMBLE_PASSWORD,
            },
        )
        self.assertEqual(status, 201, body)
        cookie = self._cookie(headers)
        self.assertTrue(cookie.startswith("satsage_session="), cookie)
        return cookie

    def test_t9_faucet_nur_regtest_ohne_socket(self):
        with mock.patch("core.bitcoind_rpc.BitcoinRpcClient.call") as call:
            status, body = self.anfrage(
                "/api/lab/faucet-senden",
                methode="POST",
                daten={"address": "bcrt1qtestfaucet0000000000000000000000", "sats": 100000},
            )
        self.assertEqual(status, 403, body)
        self.assertIn("regtest", str(body.get("error", "")).lower())
        call.assert_not_called()

    def test_t9_faucet_regtest_ohne_core_rpc_kein_hang(self):
        write_env_scrambled(
            self.env_pfad,
            read_env_plaintext(self.env_pfad) + "NETWORK=regtest\n",
        )
        with mock.patch("core.bitcoind_rpc.BitcoinRpcClient.call") as call:
            status, body = self.anfrage(
                "/api/lab/faucet-senden",
                methode="POST",
                daten={"address": "bcrt1qtestfaucet0000000000000000000000", "sats": 100000},
            )
        self.assertEqual(status, 503, body)
        self.assertIn("Core-RPC", str(body.get("error", "")))
        call.assert_not_called()

    def test_t9_psbt_erzeugen_sendet_nicht(self):
        with mock.patch("core.bitcoind_rpc.BitcoinRpcClient.call") as call:
            status, body = self.anfrage(
                "/api/psbt/erzeugen",
                methode="POST",
                daten={"wallet_id": "gibtsnicht", "betrag": 1000, "adresse": "x", "fee": 1},
            )
        self.assertIn(status, (400, 404), body)
        call.assert_not_called()
        dump = json.dumps(body)
        self.assertNotIn("sendrawtransaction", dump)

    def test_csrf_loopback_mit_passwort_lehnt_fremde_origin_ab(self):
        cookie = self._mit_passwort()
        origin_hier = f"http://127.0.0.1:{self.port}"
        status, body, _ = self.roh(
            "/api/config/ui-lang",
            methode="PUT",
            daten={"ui_lang": "en"},
            cookie=cookie,
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403, body)
        self.assertIn("Origin", str(body.get("error", "")))
        status, body, _ = self.roh(
            "/api/config/ui-lang",
            methode="PUT",
            daten={"ui_lang": "en"},
            cookie=cookie,
            headers={"Origin": origin_hier},
        )
        self.assertEqual(status, 200, body)

    def test_auth_logout_password_unlock(self):
        cookie = self._mit_passwort()
        status, body, _ = self.roh("/api/config", cookie=cookie)
        self.assertEqual(status, 200, body)

        status, body, _ = self.roh("/api/auth/logout", methode="POST", cookie=cookie)
        self.assertEqual(status, 200, body)
        status, body, _ = self.roh("/api/config", cookie=cookie)
        self.assertEqual(status, 403, body)

        status, body, headers = self.roh(
            "/api/auth/login",
            methode="POST",
            daten={"password": TEST_SCRAMBLE_PASSWORD, "phase": "full"},
        )
        self.assertEqual(status, 200, body)
        cookie = self._cookie(headers)

        from core import env_scramble as sc

        sc.clear_session_key()
        status, body, _ = self.roh(
            "/api/auth/unlock-env",
            methode="POST",
            cookie=cookie,
            daten={"password": TEST_SCRAMBLE_PASSWORD},
            headers={"Origin": f"http://127.0.0.1:{self.port}"},
        )
        self.assertEqual(status, 200, body)

        status, body, headers = self.roh(
            "/api/auth/password",
            methode="PUT",
            cookie=cookie,
            daten={
                "current_password": TEST_SCRAMBLE_PASSWORD,
                "new_password": TEST_SCRAMBLE_PASSWORD,
                "confirm": TEST_SCRAMBLE_PASSWORD,
            },
            headers={"Origin": f"http://127.0.0.1:{self.port}"},
        )
        self.assertEqual(status, 200, body)
        cookie = self._cookie(headers)
        status, body, _ = self.roh("/api/config", cookie=cookie)
        self.assertEqual(status, 200, body)
