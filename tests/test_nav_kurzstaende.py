"""Nav-Stände aus dem Cache-Dateikopf — ohne die UTXO-Liste zu lesen."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core import wallets as wallets_mod
from core import xpub_cache


class _Eintrag:
    def __init__(self, schluessel: str, kennung: str):
        self.analyse_schluessel = schluessel
        self._id = kennung

    def wallet_id(self) -> str:
        return self._id


class TestNavKurzstaende(unittest.TestCase):
    def test_liest_die_zahl_aus_dem_kopf_und_nicht_die_liste(self):
        schluessel = "zpub-nav-kurz-test"
        with TemporaryDirectory() as tmp:
            wurzel = Path(tmp)
            pfad = xpub_cache._xpub_cache_path(schluessel, wurzel)
            # Die Liste wäre riesig; der Kopf reicht.
            pfad.write_text(
                '{"utxo_count":2,"utxos":[{"txid":"aa","vout":0}]}',
                encoding="utf-8",
            )
            staende = wallets_mod.nav_kurzstaende(
                [_Eintrag(schluessel, "nav1")], wurzel,
            )
        self.assertEqual(len(staende), 1)
        self.assertEqual(staende[0]["id"], "nav1")
        self.assertTrue(staende[0]["has_cache"])
        self.assertEqual(staende[0]["utxo_count"], 2)
        self.assertIsInstance(staende[0]["cache_mtime"], int)

    def test_ohne_datei_ist_der_bestand_leer_und_unbekannt(self):
        with TemporaryDirectory() as tmp:
            staende = wallets_mod.nav_kurzstaende(
                [_Eintrag("zpub-nav-leer", "leer")], Path(tmp),
            )
        self.assertEqual(staende[0]["has_cache"], False)
        self.assertEqual(staende[0]["utxo_count"], 0)
        self.assertNotIn("cache_mtime", staende[0])

    def test_kopf_ohne_zahl_setzt_keine_null(self):
        schluessel = "zpub-nav-ohne-zahl"
        with TemporaryDirectory() as tmp:
            wurzel = Path(tmp)
            pfad = xpub_cache._xpub_cache_path(schluessel, wurzel)
            pfad.write_bytes(b'{"xpub":"geheim"')
            staende = wallets_mod.nav_kurzstaende(
                [_Eintrag(schluessel, "offen")], wurzel,
            )
        self.assertTrue(staende[0]["has_cache"])
        self.assertNotIn("utxo_count", staende[0])


if __name__ == "__main__":
    unittest.main()
