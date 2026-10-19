"""
Stufe-1-Index ``own_prevouts_for_txid``: Verlaufsdatei bleibt im Speicher,
bis sich die Datei ändert. Nur temporäre Verzeichnisse.
"""
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import main
from core import tx_classify
from tests.fixtures import txid

XPUB = "xpubTESTPREV"


def _eintrag(tid, vout, spent_txid):
    return {
        "txid": tid, "vout": vout, "value": 1000,
        "spent": spent_txid is not None, "spent_txid": spent_txid,
    }


class OwnPrevoutsCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = Path(self._tmp.name)
        self.wallet = types.SimpleNamespace(xpubs=[XPUB])
        tx_classify.leere_verlauf_index()
        self.addCleanup(tx_classify.leere_verlauf_index)

    def _frage(self, creator):
        return tx_classify.own_prevouts_for_txid(
            creator, wallet=self.wallet, cache_dir=self.cache_dir,
        )

    def test_treffer_wie_bisher(self):
        main.save_xpub_verlauf_cache(XPUB, [
            _eintrag(txid("a1"), 0, txid("c1")),
            _eintrag(txid("a2"), 1, txid("c1")),
            _eintrag(txid("a3"), 0, txid("c2")),
            _eintrag(txid("a4"), 0, None),
        ], self.cache_dir)
        self.assertEqual(
            self._frage(txid("c1").upper()),
            {f"{txid('a1')}:0", f"{txid('a2')}:1"},
        )
        self.assertEqual(self._frage(txid("c2")), {f"{txid('a3')}:0"})
        self.assertEqual(self._frage(txid("ff")), set())

    def test_zweite_abfrage_liest_die_datei_nicht_neu(self):
        main.save_xpub_verlauf_cache(
            XPUB, [_eintrag(txid("a1"), 0, txid("c1"))], self.cache_dir,
        )
        with mock.patch.object(
            main, "load_xpub_verlauf_cache", wraps=main.load_xpub_verlauf_cache,
        ) as spion:
            for _ in range(5):
                self.assertEqual(self._frage(txid("c1")), {f"{txid('a1')}:0"})
        self.assertEqual(spion.call_count, 1)

    def test_geaenderte_datei_wird_neu_gelesen(self):
        main.save_xpub_verlauf_cache(
            XPUB, [_eintrag(txid("a1"), 0, txid("c1"))], self.cache_dir,
        )
        self.assertEqual(self._frage(txid("c1")), {f"{txid('a1')}:0"})
        main.save_xpub_verlauf_cache(XPUB, [
            _eintrag(txid("a1"), 0, txid("c1")),
            _eintrag(txid("a9"), 2, txid("c1")),
        ], self.cache_dir)
        self.assertEqual(
            self._frage(txid("c1")),
            {f"{txid('a1')}:0", f"{txid('a9')}:2"},
        )

    def test_geloeschte_datei_liefert_nichts(self):
        main.save_xpub_verlauf_cache(
            XPUB, [_eintrag(txid("a1"), 0, txid("c1"))], self.cache_dir,
        )
        self.assertTrue(self._frage(txid("c1")))
        main._xpub_verlauf_cache_path(XPUB, self.cache_dir).unlink()
        self.assertEqual(self._frage(txid("c1")), set())

    def test_cache_ist_begrenzt(self):
        with mock.patch.object(tx_classify, "_VERLAUF_INDEX_MAX", 3):
            for i in range(6):
                xpub = f"xpubTESTGRENZE{i}"
                main.save_xpub_verlauf_cache(
                    xpub, [_eintrag(txid(f"b{i}"), 0, txid("c1"))], self.cache_dir,
                )
                tx_classify.own_prevouts_for_txid(
                    txid("c1"),
                    wallet=types.SimpleNamespace(xpubs=[xpub]),
                    cache_dir=self.cache_dir,
                )
            self.assertLessEqual(len(tx_classify._verlauf_index), 3)

    def test_parallele_abfragen(self):
        main.save_xpub_verlauf_cache(XPUB, [
            _eintrag(txid(f"{i:02x}"), 0, txid("c1")) for i in range(50)
        ], self.cache_dir)
        fehler = []

        def los():
            try:
                for _ in range(20):
                    if len(self._frage(txid("c1"))) != 50:
                        fehler.append("falsche Anzahl")
            except Exception as exc:  # pragma: no cover - nur Diagnose
                fehler.append(repr(exc))

        threads = [threading.Thread(target=los) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(fehler, [])


if __name__ == "__main__":
    unittest.main()
