import json
import os
import urllib.error
import urllib.request
from unittest import mock

import server
from tests.test_api import ApiTestBasis


class TestStart9PhaseS0(ApiTestBasis):
    def _request_headers(self, path, **headers):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        request.add_header("Host", headers.pop("Host", f"127.0.0.1:{self.port}"))
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_default_bind_bleibt_loopback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server._bind_host(), server.BIND_HOST)
        self.assertEqual(server.build_argumente().parse_args([]).bind, None)
        with mock.patch.dict(os.environ, {"SATSAGE_BIND": "0.0.0.0"}, clear=True):
            self.assertEqual(server._bind_host(), "0.0.0.0")
        self.assertEqual(server.build_argumente().parse_args(["--bind", "::1"]).bind, "::1")

    def test_health_ohne_token_und_config_weiterhin_tokenpflichtig(self):
        status, payload = self.anfrage("/api/health", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(payload["ok"], True)
        self.assertIn("version", payload)
        self.assertIn("managed_by", payload)
        self.assertNotIn("wallets", payload)
        status, _ = self.anfrage("/api/config", token=False)
        self.assertEqual(status, 403)

    def test_allowlist_erlaubt_local_und_onion_muster(self):
        with self.env_pfad.open("a", encoding="utf-8") as env_file:
            env_file.write("SATSAGE_HOST_ALLOWLIST=*.local,.onion\n")
        for host in ("ui.start9.local", "service.onion"):
            status, _ = self.anfrage("/api/health", token=False, host=host)
            self.assertEqual(status, 200)
        status, _ = self.anfrage("/api/health", token=False, host="evil.example")
        self.assertEqual(status, 403)

    def test_forwarded_host_nur_mit_proxy_trust(self):
        ohne_trust, _ = self._request_headers(
            "/api/health", Host="proxy.invalid", **{"X-Forwarded-Host": "ui.start9.local"}
        )
        self.assertEqual(ohne_trust, 403)
        with mock.patch.dict(os.environ, {"SATSAGE_TRUST_PROXY": "1"}, clear=False):
            mit_trust, _ = self._request_headers(
                "/api/health", Host="proxy.invalid", **{"X-Forwarded-Host": "ui.start9.local"}
            )
        self.assertEqual(mit_trust, 403)
        with self.env_pfad.open("a", encoding="utf-8") as env_file:
            env_file.write("SATSAGE_HOST_ALLOWLIST=ui.start9.local\n")
        with mock.patch.dict(os.environ, {"SATSAGE_TRUST_PROXY": "1"}, clear=False):
            mit_allowlist, _ = self._request_headers(
                "/api/health", Host="proxy.invalid", **{"X-Forwarded-Host": "ui.start9.local"}
            )
        self.assertEqual(mit_allowlist, 200)


    def test_forwarded_private_hosts_nur_mit_proxy_trust(self):
        private_hosts = ("192.168.50.20", "10.23.0.7", "172.16.4.9", "169.254.10.2", "fd12:3456::20")
        with mock.patch.dict(os.environ, dict(SATSAGE_TRUST_PROXY="1"), clear=False):
            for host in private_hosts:
                status, _ = self._request_headers(
                    "/api/health", Host="proxy.invalid", **{"X-Forwarded-Host": host}
                )
                self.assertEqual(status, 200, host)


if __name__ == "__main__":
    import unittest
    unittest.main()
