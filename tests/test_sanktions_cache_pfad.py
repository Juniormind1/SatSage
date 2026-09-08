"""
Wohin der Sanktionscheck sein Ergebnis legt.

Der Prüflauf dauert Minuten. Sein Ergebnis wird deshalb gespeichert und beim
Öffnen der Ansicht wieder gezeigt — mit Datum, denn ein Sanktionsbefund ohne
Datum wäre wertlos.

Ohne ``--sanctions-dir`` blieb das Verzeichnis leer, und damit fiel das
Speichern still aus: Jeder Lauf war nach dem Schließen der Ansicht verloren.
Der Standardpfad muss deshalb derselbe sein, in dem auch die Listen liegen.
"""
import tempfile
import unittest
from pathlib import Path

import sanctioned
import server
from core import sanctions


class TestStandardpfad(unittest.TestCase):

    def test_ohne_angabe_gilt_das_listen_verzeichnis(self):
        """
        Ohne eigene Angabe gehört das Ergebnis neben die Listen — dort liegen
        ohnehin schon die Daten desselben Themas, und der Ordner ist
        gitignoriert.
        """
        args = server.build_argumente().parse_args([])
        state_pfad = server.build_state(args).sanctions_dir
        self.assertIsNotNone(
            state_pfad, "Ohne --sanctions-dir wird nichts gespeichert."
        )
        self.assertEqual(Path(state_pfad), sanctioned.SANCTIONED_CACHE_DIR)

    def test_eigene_angabe_gewinnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = server.build_argumente().parse_args(["--sanctions-dir", tmp])
            self.assertEqual(server.build_state(args).sanctions_dir, Path(tmp))


class TestSpeichernUndLaden(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_rundlauf(self):
        ergebnis = {"max_hops": 3, "erstellt": "02.08.2026 21:35",
                    "erstellt_ts": 1_785_000_000, "wallets": []}
        self.assertTrue(sanctions.check_ergebnis_speichern(self.dir, ergebnis))
        geladen = sanctions.check_ergebnis_laden(self.dir)
        self.assertEqual(geladen["erstellt"], "02.08.2026 21:35")
        self.assertEqual(geladen["max_hops"], 3)

    def test_ohne_verzeichnis_faellt_es_still_aus(self):
        """
        Das ist das Verhalten, das den Fehler ermöglicht hat — es bleibt
        bestehen, darf aber nie durch einen fehlenden Standardpfad ausgelöst
        werden.
        """
        self.assertFalse(sanctions.check_ergebnis_speichern(None, {"a": 1}))
        self.assertIsNone(sanctions.check_ergebnis_laden(None))

    def test_verwerfen(self):
        sanctions.check_ergebnis_speichern(self.dir, {"wallets": []})
        self.assertTrue(sanctions.check_ergebnis_verwerfen(self.dir))
        self.assertIsNone(sanctions.check_ergebnis_laden(self.dir))


if __name__ == "__main__":
    unittest.main()
