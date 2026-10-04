"""Tip-Nachzug: Rückwärtsfenster und Gap-Walk je Chain (Empfang/Change getrennt).

Lab-Fall HS Alpha (Promo-Lab 2026-10-04): Empfang bis #21 benutzt (Scan-Ende
#122), Change bis #15. Das tx0-Wechselgeld landete auf Change #16/#17. Mit
einem gemeinsamen Scan-Ende lief das Fenster #22…#121 auf beiden Chains und
fand die neuen Change-UTXOs nicht — erst ein voller Neu-Scan.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
import core.wallet_sync_engine as wse
from core.derivation import derive_addresses_at_index
from tests.fixtures import BIP84_ZPUB, txid


def _adr(kette: int, index: int) -> str:
    return derive_addresses_at_index(BIP84_ZPUB, kette, index)[0]


def _utxo(kette: int, index: int, sats: int, marker: str) -> dict:
    return {
        "txid": txid(marker), "vout": 0, "address": _adr(kette, index), "value": sats,
        "status": {"confirmed": True, "block_height": 640, "block_time": 1_700_000_000},
    }


class FakeFulcrum:
    pass


def _sync(cache: Path, bestand: list[dict], walk=None):
    """Tip-Nachzug gegen einen festen Chain-Bestand; liefert (UTXOs, Abfragen, discover-Aufrufe)."""
    abgefragt: list[str] = []
    nach_adresse: dict[str, list[dict]] = {}
    for u in bestand:
        nach_adresse.setdefault(u["address"], []).append(dict(u))

    def fetch_addr(addr, **_kw):
        abgefragt.append(addr)
        return [dict(u) for u in nach_adresse.get(addr, [])]

    def fetch_batch(addrs, **_kw):
        aus = []
        for a in addrs:
            abgefragt.append(a)
            aus.extend(dict(u) for u in nach_adresse.get(a, []))
        return aus

    aufrufe: list[dict] = []

    def discover(xpub, **kw):
        aufrufe.append(kw)
        if walk:
            return walk(kw)
        for k, v in (kw.get("start_je_chain") or {}).items():
            if kw.get("enden_je_chain") is not None:
                kw["enden_je_chain"][k] = v
        return set(), kw.get("start_index", 0)

    with mock.patch.object(wse, "discover_wallet_scan_addresses", side_effect=discover), \
            mock.patch("core.fulcrum_history.get_chain_tip_height", return_value=648), \
            mock.patch("core.p2p.header_datei_tip", return_value=648):
        out = main.sync_xpub_zum_tip(
            BIP84_ZPUB, lambda *_a, **_k: [], fetch_addr, fetch_batch, cache, "fulcrum",
            fulcrum=FakeFulcrum(),
        )
    return out, abgefragt, aufrufe


class TestFensterJeChain(unittest.TestCase):
    def test_lab_fall_alter_cache_findet_wechselgeld_unter_gemeinsamem_ende(self):
        """Alter Cache ohne Ende je Chain: Change-Fenster ab bekanntem Change-UTXO + 1."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            empfang = _utxo(0, 21, 1_000_000, "r21")
            change_alt = _utxo(1, 15, 500_000, "c15")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [empfang, change_alt], cache, "fulcrum",
                scan_end_index=122, scan_tip_height=647,
            )
            premix = _utxo(1, 16, 1_000_250, "c16")
            wechsel = _utxo(1, 17, 107_658_088, "c17")
            out, abgefragt, aufrufe = _sync(cache, [empfang, change_alt, premix, wechsel])
            werte = sorted(u["value"] for u in out)
            self.assertEqual(werte, [500_000, 1_000_000, 1_000_250, 107_658_088])
            # Gap-Walk startet je Chain an ihrem eigenen Ende.
            self.assertEqual(aufrufe[0]["start_je_chain"], {0: 122, 1: 116})
            # Fenster je Chain: Empfang #22…#121, Change #16…#115.
            self.assertIn(_adr(1, 16), abgefragt)
            self.assertIn(_adr(0, 22), abgefragt)
            self.assertNotIn(_adr(0, 21 - 1), abgefragt)
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            # Wechselgeld auf #17 schiebt das Change-Ende auf #17 + Gap + 1.
            self.assertEqual(entry["raw"]["scan_end_je_chain"], {"0": 122, "1": 118})
            self.assertEqual(entry["scan_end_index"], 122)

    def test_gemeinsames_ende_haette_es_verpasst(self):
        """Gegenprobe: Mit Change-Ende = gemeinsames Ende liegt #16/#17 außerhalb des Fensters."""
        fenster = wse._rueckwaerts_fenster_je_chain(BIP84_ZPUB, {0: 122, 1: 122}, 100)
        self.assertNotIn(_adr(1, 16), fenster)
        self.assertNotIn(_adr(1, 17), fenster)
        fenster = wse._rueckwaerts_fenster_je_chain(BIP84_ZPUB, {0: 122, 1: 116}, 100)
        self.assertEqual(fenster[_adr(1, 16)], (1, 16))
        self.assertEqual(fenster[_adr(0, 22)], (0, 22))
        self.assertNotIn(_adr(0, 21), fenster)

    def test_gespeichertes_ende_je_chain_gilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            empfang = _utxo(0, 21, 1_000_000, "r21")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [empfang], cache, "fulcrum", scan_end_index=122,
                scan_tip_height=647, scan_end_je_chain={0: 122, 1: 40},
            )
            neu = _utxo(1, 0, 70_000, "c0")   # unterhalb [40 − 100, 40) = [0, 40)
            out, abgefragt, aufrufe = _sync(cache, [empfang, neu])
            self.assertIn(70_000, [u["value"] for u in out])
            self.assertEqual(aufrufe[0]["start_je_chain"], {0: 122, 1: 40})
            self.assertNotIn(_adr(1, 40), abgefragt)  # Fenster endet am Change-Ende

    def test_alter_cache_ohne_change_utxo_prueft_change_ab_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            empfang = _utxo(0, 50, 1_000_000, "r50")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [empfang], cache, "fulcrum", scan_end_index=151, scan_tip_height=647,
            )
            neu = _utxo(1, 3, 42_000, "c3")
            out, _abgefragt, aufrufe = _sync(cache, [empfang, neu])
            self.assertIn(42_000, [u["value"] for u in out])
            self.assertEqual(aufrufe[0]["start_je_chain"], {0: 151, 1: 100})

    def test_walk_ende_je_chain_wird_gespeichert(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            empfang = _utxo(0, 21, 1_000_000, "r21")
            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [empfang], cache, "fulcrum", scan_end_index=122,
                scan_tip_height=647, scan_end_je_chain={0: 122, 1: 30},
            )
            neu = _utxo(1, 35, 9_000, "c35")

            def walk(kw):
                kw["enden_je_chain"].update({0: 122, 1: 136})   # Change #35 benutzt
                return {_adr(1, 35)}, 136

            out, _a, _c = _sync(cache, [empfang, neu], walk=walk)
            self.assertIn(9_000, [u["value"] for u in out])
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(entry["raw"]["scan_end_je_chain"], {"0": 122, "1": 136})
            self.assertEqual(entry["scan_end_index"], 136)


class TestGapWalkJeChain(unittest.TestCase):
    def test_start_und_ende_je_chain(self):
        aufrufe = []

        def collect(client, xpub, change, max_index, gap, derive, *, start_index=0, **_kw):
            aufrufe.append((change, start_index))
            if change == 0:
                return {21}, 122          # Empfang bis #21 benutzt
            return set(), start_index     # Change ab Start nichts Neues

        with mock.patch("core.fulcrum_wallet.collect_used_chain_indices_fulcrum", side_effect=collect):
            enden: dict = {}
            _adressen, ende = wse.discover_wallet_scan_addresses(
                BIP84_ZPUB, fulcrum=FakeFulcrum(), max_index_per_chain=400,
                start_index=0, start_je_chain={0: 0, 1: 16}, enden_je_chain=enden,
            )
        self.assertEqual(aufrufe, [(0, 0), (1, 16)])
        self.assertEqual(enden, {0: 122, 1: 16})
        self.assertEqual(ende, 122)

    def test_speichern_ohne_wert_behaelt_den_alten(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_utxo_cache(BIP84_ZPUB, [], cache, "fulcrum", scan_end_index=122,
                                      scan_end_je_chain={0: 122, 1: 116})
            main.save_xpub_utxo_cache(BIP84_ZPUB, [], cache, "fulcrum", scan_end_index=122)
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(entry["raw"]["scan_end_je_chain"], {"0": 122, "1": 116})

    def test_normalisieren(self):
        from core.xpub_cache import normalisiere_scan_end_je_chain as n
        self.assertEqual(n({"0": "5", "1": 7, "2": 9, "x": 1}), {0: 5, 1: 7})
        self.assertEqual(n(None), {})
        self.assertEqual(n({"1": -3}), {})


if __name__ == "__main__":
    unittest.main()
