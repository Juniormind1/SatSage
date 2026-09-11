"""Start-Aktualisierung der Wallet-Caches (kein Fullscan)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from tests.fixtures import BIP84_RECEIVE_0, BIP84_ZPUB, txid


def _utxo(sats=1000, marker="a1", address=BIP84_RECEIVE_0):
    return {
        "txid": txid(marker),
        "vout": 0,
        "address": address,
        "value": sats,
        "status": {"confirmed": True, "block_height": 800_000, "block_time": 1_700_000_000},
    }


class TestWalletsBeimStart(unittest.TestCase):
    def test_env_flag_opt_in(self):
        self.assertFalse(main.resolve_wallets_beim_start_aktualisieren({}))
        self.assertFalse(
            main.resolve_wallets_beim_start_aktualisieren(
                {"WALLETS_BEIM_START_AKTUALISIEREN": "0"}
            )
        )
        self.assertFalse(
            main.resolve_wallets_beim_start_aktualisieren(
                {"WALLETS_BEIM_START_AKTUALISIEREN": "nein"}
            )
        )
        self.assertTrue(
            main.resolve_wallets_beim_start_aktualisieren(
                {"WALLETS_BEIM_START_AKTUALISIEREN": "1"}
            )
        )
        self.assertTrue(
            main.resolve_wallets_beim_start_aktualisieren(
                {"WALLETS_BEIM_START_AKTUALISIEREN": "ja"}
            )
        )
        self.assertTrue(
            main.resolve_wallets_beim_start_aktualisieren(
                {"WALLETS_IMMER_AKTUELL": "1"}
            )
        )
        # Neuer Key sticht Legacy
        self.assertFalse(
            main.resolve_wallets_beim_start_aktualisieren(
                {
                    "WALLETS_IMMER_AKTUELL": "0",
                    "WALLETS_BEIM_START_AKTUALISIEREN": "1",
                }
            )
        )


    def test_nur_bekannte_env_flag(self):
        self.assertFalse(main.resolve_wallets_nur_bekannte_utxos({}))
        self.assertFalse(
            main.resolve_wallets_nur_bekannte_utxos(
                {"WALLETS_NUR_BEKANNTE_UTXOS": "0"}
            )
        )
        self.assertTrue(
            main.resolve_wallets_nur_bekannte_utxos(
                {"WALLETS_NUR_BEKANNTE_UTXOS": "1"}
            )
        )
        self.assertTrue(
            main.resolve_wallets_nur_bekannte_utxos(
                {"WALLETS_NUR_BEKANNTE_UTXOS": "ja"}
            )
        )

    def test_ohne_cache_nichts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            out = main.sync_xpub_zum_tip(
                BIP84_ZPUB,
                lambda *_a, **_k: [],
                lambda *_a, **_k: [],
                lambda *_a, **_k: [],
                cache,
                "fulcrum",
            )
            self.assertIsNone(out)

    def test_fulcrum_light_prueft_bekannte_utxos_nicht_alle_indizes(self):
        """Light-Pfad: spent der bekannten UTXOs + Gap — nicht #0…scan_end."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            alt = _utxo(5000, "old")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], cache, "fulcrum", scan_end_index=2,
            )
            neu = _utxo(9000, "new")
            abgefragt: list[str] = []

            def fetch_addr(addr, **_kw):
                abgefragt.append(addr)
                return [dict(neu)] if addr == neu["address"] else []

            def fetch_batch(addrs, **_kw):
                for a in addrs:
                    abgefragt.append(a)
                return [dict(neu)] if neu["address"] in set(addrs) else []

            out = main.sync_xpub_zum_tip(
                BIP84_ZPUB,
                lambda addrs, **k: fetch_batch(addrs),
                fetch_addr,
                fetch_batch,
                cache,
                "fulcrum",
                fulcrum=None,  # Lookahead-Pfad statt Gap-Discover
            )
            self.assertIsNotNone(out)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["value"], 9000)
            # Nur die Adresse des bekannten UTXO (+ Lookahead), nicht blind
            # alle Indizes 0…N als „bekannte Adressen“-Vollabfrage.
            self.assertIn(BIP84_RECEIVE_0, abgefragt)
            geladen = main.load_xpub_utxo_cache(BIP84_ZPUB, cache)
            self.assertEqual(len(geladen), 1)
            self.assertEqual(geladen[0]["value"], 9000)


    def test_nur_bekannte_ueberspringt_gap_discover(self):
        """nur_bekannte: kein discover_wallet_scan_addresses, bekannte Adresse bleibt."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            alt = _utxo(5000, "old")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], cache, "fulcrum",
                scan_end_index=50, scan_tip_height=900_000,
            )
            abgefragt: list[str] = []

            def fetch_addr(addr, **_kw):
                abgefragt.append(addr)
                return [dict(alt)] if addr == alt["address"] else []

            def fetch_batch(addrs, **_kw):
                for a in addrs:
                    abgefragt.append(a)
                return [dict(alt)] if alt["address"] in set(addrs) else []

            class FakeFulcrum:
                pass

            with mock.patch.object(
                main, "discover_wallet_scan_addresses",
                side_effect=AssertionError("Gap darf nicht laufen"),
            ):
                out = main.sync_xpub_zum_tip(
                    BIP84_ZPUB,
                    lambda *_a, **_k: [],
                    fetch_addr,
                    fetch_batch,
                    cache,
                    "fulcrum",
                    fulcrum=FakeFulcrum(),
                    nur_bekannte=True,
                )
            self.assertIsNotNone(out)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["value"], 5000)
            self.assertIn(BIP84_RECEIVE_0, abgefragt)
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(int(entry["scan_end_index"]), 50)

    def test_bip158_ohne_tip_laesst_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            alt = _utxo(1234, "keep")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], cache, "bip158", scan_end_index=3,
            )
            # kein scan_tip_height
            out = main.sync_xpub_zum_tip(
                BIP84_ZPUB,
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("kein Scan")),
                lambda *_a, **_k: [],
                lambda *_a, **_k: [],
                cache,
                "bip158",
            )
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["value"], 1234)

    def test_bip158_mit_tip_ruft_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            alt = _utxo(100, "a")
            path = main.save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], cache, "bip158",
                scan_end_index=3, scan_tip_height=900_000,
            )
            self.assertTrue(path.is_file())
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(entry["raw"].get("scan_tip_height"), 900_000)

            frisch = [_utxo(777, "b")]
            with mock.patch.object(main, "_scan_xpub_utxos", return_value=frisch) as scan:
                out = main.sync_xpub_zum_tip(
                    BIP84_ZPUB,
                    lambda *_a, **_k: [],
                    lambda *_a, **_k: [],
                    lambda *_a, **_k: [],
                    cache,
                    "bip158",
                )
            self.assertEqual(out, frisch)
            scan.assert_called_once()
            kwargs = scan.call_args.kwargs
            self.assertFalse(kwargs.get("allow_scantxoutset", True))
            self.assertIsNone(kwargs.get("fulcrum"))

    def test_bip158_fetch_bevorzugt_auch_bei_fulcrum_quelle(self):
        """Produktregel: Tip-Nachzug nutzt bip158_fetch auch wenn Quelle Electrs."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            alt = _utxo(100, "a")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], cache, "fulcrum",
                scan_end_index=3, scan_tip_height=900_000,
            )
            frisch = [_utxo(555, "b")]
            bip_calls = {"n": 0}

            def bip_fetch(*_a, **_k):
                bip_calls["n"] += 1
                return frisch

            with mock.patch.object(
                main, "_scan_xpub_utxos", return_value=frisch
            ) as scan:
                out = main.sync_xpub_zum_tip(
                    BIP84_ZPUB,
                    lambda *_a, **_k: (_ for _ in ()).throw(
                        AssertionError("kein Electrs-Vollscan")
                    ),
                    lambda *_a, **_k: (_ for _ in ()).throw(
                        AssertionError("kein Electrs-Light")
                    ),
                    None,
                    cache,
                    "fulcrum",
                    fulcrum=object(),
                    bip158_fetch_wallet_utxos=bip_fetch,
                )
            self.assertEqual(out, frisch)
            scan.assert_called_once()
            self.assertEqual(scan.call_args.args[3], "bip158")
            self.assertFalse(scan.call_args.kwargs.get("allow_scantxoutset", True))

    def test_tip_sync_kein_scantxoutset(self):
        """scantxoutset darf beim Tip-Nachzug nie laufen (Vollabgleich = User-Scan)."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            alt = _utxo(42, "c")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], cache, "fulcrum", scan_end_index=2,
            )

            def fetch_addr(addr, **_kw):
                return [dict(alt)] if addr == alt["address"] else []

            with mock.patch.object(
                main, "_try_scantxoutset_xpub", return_value=[_utxo(999, "x")]
            ) as core:
                out = main.sync_xpub_zum_tip(
                    BIP84_ZPUB,
                    lambda *_a, **_k: [],
                    fetch_addr,
                    None,
                    cache,
                    "fulcrum",
                    fulcrum=None,
                )
            core.assert_not_called()
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["value"], 42)

    def test_try_bip158_fetch_for_tip_sync_none_wenn_aus(self):
        args = mock.Mock()
        args.xpubs = [BIP84_ZPUB]
        args.max_addresses = 50
        args.bip158_start = None
        args.cache_dir = None
        env = {"BIP158_P2P": "0"}
        self.assertIsNone(
            main.try_bip158_fetch_for_tip_sync(args, env, None)
        )

    def test_electrs_light_hebt_tip_auf_live_electrs(self):
        """Ohne Aktivität: scan_tip_height folgt dem Electrs-Tip (force)."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            alt = _utxo(100, "a")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], cache, "fulcrum",
                scan_end_index=2, scan_tip_height=900_000,
            )

            class FakeFulcrum:
                pass

            def fetch_addr(addr, **_kw):
                return [dict(alt)] if addr == alt["address"] else []

            with mock.patch(
                "fulcrum.get_chain_tip_height", return_value=912_345
            ) as tip_fn, mock.patch(
                "core.p2p.header_datei_tip", return_value=900_100
            ), mock.patch(
                "main.discover_wallet_scan_addresses",
                return_value=(set(), 2),
            ):
                out = main.sync_xpub_zum_tip(
                    BIP84_ZPUB,
                    lambda *_a, **_k: [],
                    fetch_addr,
                    None,
                    cache,
                    "fulcrum",
                    fulcrum=FakeFulcrum(),
                )
            self.assertIsNotNone(out)
            tip_fn.assert_called()
            self.assertTrue(tip_fn.call_args.kwargs.get("force"))
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(entry["raw"].get("scan_tip_height"), 912_345)


if __name__ == "__main__":
    unittest.main()
