"""Tx-Cache: parallele Schreiber derselben Tx kollidieren nicht.

Vorlader und Hauptweg speichern im Herkunfts-Walk mitunter dieselbe Tx
gleichzeitig. Mit einer gemeinsamen ``<txid>.json.tmp`` scheiterte einer
mit FileNotFoundError, und eine Sammel-Tx verlor ihr Bündel.
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from core import xpub_cache
from tests.fixtures import EXTERN_A, TXID_COINBASE, core_tx, core_vin, core_vout

TXID = "ab" * 32


class TestTxCacheAtomar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tx-cache-atomar-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.tx = core_tx(
            TXID,
            [core_vin(TXID_COINBASE, 0)],
            [core_vout(0, EXTERN_A, 1.0)],
            blocktime=1_700_000_000,
        )

    def test_parallele_schreiber_ohne_fehler(self):
        fehler: list[str] = []
        start = threading.Barrier(4)

        def schreibe():
            start.wait()
            for _ in range(100):
                try:
                    xpub_cache.save_cached_tx(TXID, self.tx, self.root, "fulcrum")
                except Exception as exc:  # pragma: no cover - der Fehlerfall
                    fehler.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=schreibe) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(fehler, [])
        dateien = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertEqual([p.suffix for p in dateien], [".json"], dateien)
        daten = json.loads(dateien[0].read_text(encoding="utf-8"))
        self.assertEqual(daten["txid"], TXID)

    def test_keine_temp_datei_nach_einzelnem_schreiben(self):
        pfad = xpub_cache.save_cached_tx(TXID, self.tx, self.root, "fulcrum")
        self.assertTrue(pfad.is_file())
        self.assertEqual(list(pfad.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
