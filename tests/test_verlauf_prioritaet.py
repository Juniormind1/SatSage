"""
Verlaufsscan: eigene Prioritätskette (nicht UTXO-/Auto-Kette).

1. Electrs LAN → 2. Electrs Onion → 3. BIP-158 → 4. öffentliche Electrum
Core scantxoutset entfällt (kein Verlauf).
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main


def _args(**kw):
    basis = dict(
        bip158=False,
        rpc_only=False,
        oeffentliche_electrum=False,
        xpubs=["zpub6rFR7y4Q2AijBEqTUquhVz38LU3R8JGvG4RZQRVfBLWjqs2mJg9gH4z4"],
        max_addresses=50,
    )
    basis.update(kw)
    return SimpleNamespace(**basis)


class TestVerlaufPrioritaet(unittest.TestCase):
    def setUp(self):
        self.logs: list[str] = []
        self._log = patch.object(
            main, "_log_quelle", side_effect=lambda t: self.logs.append(t)
        )
        self._log.start()
        self.addCleanup(self._log.stop)

    def test_lan_electrs_gewinnt_ohne_bip158_oder_public(self):
        client = object()
        with patch.object(
            main, "_resolve_own_lan_endpoint",
            return_value=("192.168.1.10", 50001, False),
        ), patch.object(
            main, "_try_fulcrum_endpoint", return_value=client,
        ) as try_ep, patch.object(
            main, "_try_bip158_backend",
        ) as bip, patch.object(
            main, "_try_public_onion_fulcrum",
        ) as onion:
            quelle, backend = main._try_verlauf_priority_chain(
                _args(), {}, include_bip158=True,
            )
        self.assertEqual(quelle, "fulcrum")
        self.assertIs(backend, client)
        try_ep.assert_called_once()
        bip.assert_not_called()
        onion.assert_not_called()
        self.assertTrue(any("Verlauf:" in z and "LAN" in z for z in self.logs))
        self.assertTrue(any("get_history" in z for z in self.logs))

    def test_tor_electrs_wenn_lan_fehlt(self):
        client = object()
        with patch.object(
            main, "_resolve_own_lan_endpoint", return_value=None,
        ), patch.object(
            main, "_resolve_own_tor_endpoint",
            return_value=("abc.onion", 50001, True),
        ), patch.object(
            main, "_require_tor_proxy", return_value=("127.0.0.1", 9050),
        ), patch.object(
            main, "_try_fulcrum_endpoint", return_value=client,
        ), patch.object(
            main, "_try_bip158_backend",
        ) as bip:
            quelle, backend = main._try_verlauf_priority_chain(
                _args(), {}, include_bip158=True,
            )
        self.assertEqual(quelle, "fulcrum")
        self.assertIs(backend, client)
        bip.assert_not_called()
        self.assertTrue(any("Verlauf:" in z and "Tor" in z for z in self.logs))

    def test_bip158_wenn_electrs_fehlt(self):
        backend = {"get_tx": lambda txid: {}, "client": MagicMock(cache_dir=None)}
        with patch.object(
            main, "_resolve_own_lan_endpoint", return_value=None,
        ), patch.object(
            main, "_resolve_own_tor_endpoint", return_value=None,
        ), patch.object(
            main, "_try_bip158_backend", return_value=backend,
        ), patch.object(
            main, "_try_public_onion_fulcrum",
        ) as onion:
            quelle, gewählt = main._try_verlauf_priority_chain(
                _args(), {}, include_bip158=True,
            )
        self.assertEqual(quelle, "bip158")
        self.assertIs(gewählt, backend)
        onion.assert_not_called()
        self.assertTrue(
            any("BIP-158" in z and "Blockwalk" in z for z in self.logs)
        )

    def test_oeffentlich_nur_mit_bestaetigung_nach_bip158(self):
        pool = object()
        with patch.object(
            main, "_resolve_own_lan_endpoint", return_value=None,
        ), patch.object(
            main, "_resolve_own_tor_endpoint", return_value=None,
        ), patch.object(
            main, "_try_bip158_backend", return_value=None,
        ), patch.object(
            main, "_try_public_onion_fulcrum", return_value=pool,
        ) as onion, patch.object(
            main, "_setup_public_clearnet_fulcrum",
        ) as clear:
            self.assertIsNone(
                main._try_verlauf_priority_chain(
                    _args(), {}, include_bip158=True,
                )
            )
            onion.assert_not_called()
            clear.assert_not_called()

            quelle, backend = main._try_verlauf_priority_chain(
                _args(), {"OEFFENTLICHE_ELECTRUM": "1"}, include_bip158=True,
            )
        self.assertEqual(quelle, "fulcrum")
        self.assertIs(backend, pool)
        self.assertTrue(any("öffentlich" in z.lower() for z in self.logs))

    def test_rpc_only_ueberspringt_bip158(self):
        with patch.object(
            main, "_resolve_own_lan_endpoint", return_value=None,
        ), patch.object(
            main, "_resolve_own_tor_endpoint", return_value=None,
        ), patch.object(
            main, "_try_bip158_backend",
        ) as bip, patch.object(
            main, "_try_public_electrum_fuer_verlauf", return_value=None,
        ):
            self.assertIsNone(
                main._try_verlauf_priority_chain(
                    _args(rpc_only=True),
                    {},
                    include_bip158=False,
                )
            )
        bip.assert_not_called()

    def test_setup_verlauf_explizit_bip158(self):
        backend = {"client": MagicMock()}
        with patch.object(
            main, "_setup_bip158_client", return_value=backend,
        ), patch.object(
            main, "_load_dotenv", return_value={},
        ):
            quelle, gewählt = main._setup_verlauf_client(_args(bip158=True))
        self.assertEqual(quelle, "bip158")
        self.assertIs(gewählt, backend)

    def test_build_fetchers_bip158_hat_history(self):
        client = MagicMock()
        client.cache_dir = None
        backend = {
            "get_tx": lambda txid: {"txid": txid},
            "fetch_address_utxos": lambda addr: [],
            "fetch_wallet_utxos": MagicMock(return_value=[]),
            "client": client,
        }
        args = _args()
        wallet = MagicMock()
        wallet.max_addresses_for.return_value = 50
        wallet.address_to_xpub = {}
        fetchers = main._build_blockchain_fetchers(
            "bip158", backend, args, wallet_ctx=wallet,
        )
        self.assertIn("fetch_wallet_history", fetchers)
        self.assertTrue(callable(fetchers["fetch_wallet_history"]))


if __name__ == "__main__":
    unittest.main()
