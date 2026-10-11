"""Sammel-UTXO: P2P ein Durchgang, sonst Electrs-LAN oder ein scantxoutset."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.bip158_filter import MatchedOutput, ScanResult
from core.bip158_wallet import _uebernimm_scan_ergebnis
from core.wallet_sync_engine import sammel_utxo_modus, scanne_alle_xpubs_utxo


class _Client:
    cache_dir = None


class TestScanFunde(unittest.TestCase):
    def test_nur_neue_utxos_und_wallet_ueber_adresse(self):
        from httpserver.api.source import _merke_scan_funde

        gesehen = {"aa" * 32 + ":0"}
        entdeckt: list[dict] = []
        stand = [
            {"txid": "AA" * 32, "vout": 0, "value": 5, "address": "bc1qalt"},
            {"txid": "bb" * 32, "vout": 1, "value": 9, "address": "bc1qneu"},
        ]
        _merke_scan_funde(
            stand, gesehen=gesehen, entdeckt=entdeckt,
            adressen={"bc1qneu": "wallet-a"},
        )
        self.assertEqual(len(entdeckt), 1)
        self.assertEqual(entdeckt[0]["value_sats"], 9)
        self.assertEqual(entdeckt[0]["wallet_id"], "wallet-a")
        _merke_scan_funde(
            stand, gesehen=gesehen, entdeckt=entdeckt,
            adressen={"bc1qneu": "wallet-a"},
        )
        self.assertEqual(len(entdeckt), 1)


class TestGruppen(unittest.TestCase):
    def test_uebernahme_teilt_je_xpub(self):
        ausgang = MatchedOutput(
            "ab" * 32, 1, 10, "bc1qtest", "", 5, "00" * 32,
        )
        ergebnis = ScanResult(start_height=1, stop_height=5, outputs=[ausgang])
        utxos: list[dict] = []
        gruppen: dict[str, list[dict]] = {}
        _uebernimm_scan_ergebnis(
            _Client(), "xpub-a", ergebnis, utxos,
            on_utxos_update=None, gruppen=gruppen,
        )
        self.assertEqual(len(utxos), 1)
        self.assertEqual(gruppen["xpub-a"][0]["value"], 10)
        self.assertIs(gruppen["xpub-a"][0], utxos[0])


class TestSammelModus(unittest.TestCase):
    def test_nur_p2p_ist_ein_durchgang(self):
        with patch(
            "core.chain_sources.p2p_utxo_entdeckung_frei", return_value=True,
        ):
            self.assertEqual(sammel_utxo_modus({}, None), "p2p")

    def test_electrs_lan_vor_scantxoutset(self):
        with patch(
            "core.chain_sources.p2p_utxo_entdeckung_frei", return_value=False,
        ), patch(
            "core.wallet_sync_engine._fulcrum_transport_ist_lan", return_value=True,
        ):
            self.assertEqual(sammel_utxo_modus({}, object()), "electrs")

    def test_sonst_scantxoutset(self):
        with patch(
            "core.chain_sources.p2p_utxo_entdeckung_frei", return_value=False,
        ), patch(
            "core.wallet_sync_engine._fulcrum_transport_ist_lan", return_value=False,
        ):
            self.assertEqual(sammel_utxo_modus({}, object()), "scantxoutset")


class TestSammellauf(unittest.TestCase):
    def test_p2p_ein_aufruf_und_cache_je_xpub(self):
        xpubs = ["xpub-a", "xpub-b"]
        gesehen: list[list[str]] = []

        def fetch(_addrs, **kw):
            gesehen.append(list(kw.get("xpubs") or []))
            gruppen = kw["gruppen"]
            gruppen["xpub-a"].append({"value": 7, "txid": "aa" * 32, "vout": 0})

        def baue(*_a, **_k):
            return fetch, (lambda: None)

        with patch(
            "core.chain_sources.p2p_utxo_entdeckung_frei", return_value=True,
        ), patch(
            "core.chain_sources.baue_p2p_utxo_fetch", baue,
        ), patch(
            "core.wallet_sync_engine.derive_addresses", return_value=["bc1q"],
        ), patch(
            "core.wallet_sync_engine.ermittle_first_seen", return_value=None,
        ), patch(
            "core.bip158_wallet.take_last_scan_tip", return_value=10,
        ), patch(
            "core.wallet_sync_engine.save_xpub_utxo_cache",
        ) as speichern, patch(
            "core.wallet_sync_engine._scan_xpub_utxos",
        ) as einzel:
            utxos, quelle = scanne_alle_xpubs_utxo(
                xpubs,
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Gap")),
                cache_dir=__import__("pathlib").Path("/tmp"),
                source="fulcrum",
                max_addresses_for=lambda _x: 20,
                env={},
            )
        einzel.assert_not_called()
        self.assertEqual(gesehen, [xpubs])
        self.assertEqual(quelle, "bip158")
        self.assertEqual(sum(u["value"] for u in utxos), 7)
        self.assertEqual(speichern.call_count, 2)
        quellen = {c.args[3] for c in speichern.call_args_list}
        self.assertEqual(quellen, {"bip158"})
        self.assertTrue(all(
            c.kwargs.get("bip158_fullscan_ok") is True
            for c in speichern.call_args_list
        ))

    def test_electrs_lan_wallet_fuer_wallet(self):
        with patch(
            "core.chain_sources.p2p_utxo_entdeckung_frei", return_value=False,
        ), patch(
            "core.wallet_sync_engine._fulcrum_transport_ist_lan", return_value=True,
        ), patch(
            "core.wallet_sync_engine._scan_xpub_utxos",
            side_effect=lambda xpub, *_a, **_k: [{"value": 1, "xpub": xpub}],
        ) as einzel:
            utxos, quelle = scanne_alle_xpubs_utxo(
                ["a", "b"],
                lambda *_a, **_k: [],
                cache_dir=__import__("pathlib").Path("/tmp"),
                source="fulcrum",
                max_addresses_for=lambda _x: 20,
                fulcrum=object(),
                env={},
            )
        self.assertEqual(einzel.call_count, 2)
        self.assertTrue(all(
            c.kwargs.get("allow_scantxoutset") is False
            and c.kwargs.get("_p2p_schon") is True
            for c in einzel.call_args_list
        ))
        self.assertEqual(quelle, "fulcrum")
        self.assertEqual(len(utxos), 2)

    def test_scantxoutset_ein_batch(self):
        gesehen = {"n": 0}

        def versuch(_env, xpubs, **_k):
            gesehen["n"] += 1
            self.assertEqual(list(xpubs), ["a", "b"])
            return {x: [{"value": 3}] for x in xpubs}, 42

        with patch(
            "core.chain_sources.p2p_utxo_entdeckung_frei", return_value=False,
        ), patch(
            "core.wallet_sync_engine._fulcrum_transport_ist_lan", return_value=False,
        ), patch(
            "core.bitcoind_rpc.try_scantxoutset_for_xpubs", versuch,
        ), patch(
            "core.wallet_sync_engine.derive_addresses", return_value=[],
        ), patch(
            "core.wallet_sync_engine.ermittle_first_seen", return_value=None,
        ), patch(
            "core.wallet_sync_engine.save_xpub_utxo_cache",
        ) as speichern, patch(
            "core.wallet_sync_engine._scan_xpub_utxos",
        ) as einzel:
            utxos, quelle = scanne_alle_xpubs_utxo(
                ["a", "b"],
                lambda *_a, **_k: [],
                cache_dir=__import__("pathlib").Path("/tmp"),
                source="fulcrum",
                max_addresses_for=lambda _x: 20,
                env={},
            )
        self.assertEqual(gesehen["n"], 1)
        einzel.assert_not_called()
        self.assertEqual(quelle, "bitcoind")
        self.assertEqual(len(utxos), 2)
        self.assertEqual(
            {c.args[3] for c in speichern.call_args_list},
            {"bitcoind"},
        )


if __name__ == "__main__":
    unittest.main()
