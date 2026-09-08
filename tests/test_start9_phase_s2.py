"""Regressionen für Start9 Phase S2 (Outbound/SSRF)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import outbound_policy
import server


class TestOutboundPolicy(unittest.TestCase):
    def test_public_ohne_opt_in_abgelehnt(self):
        with self.assertRaises(outbound_policy.OutboundPolicyError):
            outbound_policy.ensure_url_allowed("https://example.org", service="mempool")

    def test_loopback_private_und_onion_erlaubt(self):
        for url in (
            "http://127.0.0.1:8080",
            "http://192.168.10.5:8080",
            "http://[fd00::1]:8080",
            "https://nodeexample.onion",
        ):
            self.assertTrue(outbound_policy.ensure_url_allowed(url, service="fulcrum"))

    def test_xai_public_without_llm_opt_in_is_blocked(self):
        self.assertEqual(outbound_policy.classify_host("api.x.ai"), "public")
        with self.assertRaises(outbound_policy.OutboundPolicyError):
            outbound_policy.ensure_url_allowed("https://api.x.ai/v1", service="llm", values={"LLM_REMOTE_OPT_IN": "0"})

    def test_public_mit_opt_in(self):
        self.assertTrue(
            outbound_policy.ensure_url_allowed(
                "https://example.org", service="mempool",
                values={"SATSAGE_OUTBOUND_PUBLIC_OPT_IN": "1"},
            )
        )

    def test_llm_remote_opt_in_bleibt_service_opt_in(self):
        with self.assertRaises(outbound_policy.OutboundPolicyError):
            outbound_policy.ensure_url_allowed(
                "https://api.example.org/v1", service="llm",
                values={"LLM_REMOTE_OPT_IN": "0"},
            )
        self.assertTrue(
            outbound_policy.ensure_url_allowed(
                "https://api.example.org/v1", service="llm",
                values={"LLM_REMOTE_OPT_IN": "1"},
            )
        )

    def test_tls_lan_locker_clearnet_streng(self):
        """Desktop/LAN behält alte Self-Signed-Praxis; Clearnet prüft Zertifikate."""
        with mock.patch.dict(os.environ, {}, clear=True):
            lan = outbound_policy.tls_context(host="192.168.2.168")
            self.assertEqual(lan.verify_mode, outbound_policy.ssl.CERT_NONE)
            onion = outbound_policy.tls_context(host="abc.onion")
            self.assertEqual(onion.verify_mode, outbound_policy.ssl.CERT_NONE)
            public = outbound_policy.tls_context(host="electrum.example.org")
            self.assertEqual(public.verify_mode, outbound_policy.ssl.CERT_REQUIRED)
            ohne_host = outbound_policy.tls_context()
            self.assertEqual(ohne_host.verify_mode, outbound_policy.ssl.CERT_REQUIRED)
        with mock.patch.dict(os.environ, {"SATSAGE_TLS_INSECURE": "1"}, clear=True):
            with self.assertWarns(RuntimeWarning):
                context = outbound_policy.tls_context(host="electrum.example.org")
            self.assertEqual(context.verify_mode, outbound_policy.ssl.CERT_NONE)


class TestStart9ManagedMode(unittest.TestCase):
    def test_managed_start9_blockiert_node_mutationen(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "SATSAGE_MANAGED_BY=start9\nELECTRS_HOST=electrs\nBITCOIND_HOST=bitcoind\n",
                encoding="utf-8",
            )
            state = server.AppState(
                env_path=env_path,
                cache_dir=Path(tmp) / "cache",
                immutable_cache_dir=Path(tmp) / "immutable",
            )
            self.assertEqual(state.managed_by, "start9")
            self.assertEqual(state.env().values()["FULCRUM_HOST"], "electrs")
            with self.assertRaises(server.ApiError) as raised:
                server.api_save_source(state, {"source": "own_core", "values": {"NODE_IP": "127.0.0.1"}})
            self.assertEqual(raised.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
