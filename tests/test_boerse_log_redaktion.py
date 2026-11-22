"""Logs der Börsenhistorie enthalten keine Fixture-Kennungen."""
from __future__ import annotations

import io
import logging
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from core.log_redaktion import (
    LOGGER_NAME,
    ausnahme_text,
    get_logger,
    groessenordnung,
    redigiere,
    ref_hash,
    schreibe,
    schreibe_ausnahme,
    tag_iso,
)
from tests.fixtures import (
    BIP84_AS_XPUB,
    BIP84_RECEIVE_0,
    BIP84_RECEIVE_1,
    BIP84_ZPUB,
    txid,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "boerse"


def _marker() -> list[str]:
    werte = [
        BIP84_RECEIVE_0,
        BIP84_RECEIVE_1,
        BIP84_ZPUB,
        BIP84_AS_XPUB,
        txid("c1"),
        txid("ab"),
        "lnbc1synthetictestinvoice0001",
        "/Users/max/Downloads/kraken_ledgers.csv",
        r"C:\Users\max\Documents\strike.csv",
    ]
    # IDs und Adressen aus den synthetischen Fixtures.
    for pfad in FIXTURE_DIR.glob("*.csv"):
        text = pfad.read_text(encoding="utf-8")
        for zeile in text.splitlines():
            for teil in zeile.replace(",", " ").replace(";", " ").split():
                teil = teil.strip().strip('"')
                if not teil:
                    continue
                if (
                    teil.startswith(("LSYN", "TSYN", "CBSYN", "STSYN", "lnbc"))
                    or teil.startswith(("bc1", "tb1", "bcrt1"))
                    or (len(teil) == 64 and all(c in "0123456789abcdefABCDEF" for c in teil))
                ):
                    werte.append(teil)
    # Reihenfolge beibehalten, Duplikate raus.
    return list(dict.fromkeys(werte))


MARKEN = _marker()


def _enthalt_marke(text: str) -> list[str]:
    return [m for m in MARKEN if m and m in text]


class RedaktionUnitTest(unittest.TestCase):
    def test_ref_hash_ist_stabil_und_kurz(self):
        a = ref_hash(BIP84_RECEIVE_0)
        b = ref_hash(BIP84_RECEIVE_0)
        self.assertEqual(a, b)
        self.assertRegex(a, r"^ref:[0-9a-f]{8}$")
        self.assertNotIn(BIP84_RECEIVE_0, a)

    def test_txid_gross_klein_gleiche_referenz(self):
        wert = txid("c1")
        self.assertEqual(ref_hash(wert), ref_hash(wert.upper()))

    def test_redigiere_entfernt_fixture_kennungen(self):
        roh = " ".join(MARKEN)
        aus = redigiere(roh)
        self.assertEqual(_enthalt_marke(aus), [], aus)

    def test_redigiere_ersetzt_durch_ref_hash(self):
        aus = redigiere(f"addr={BIP84_RECEIVE_0}")
        self.assertIn(ref_hash(BIP84_RECEIVE_0), aus)
        self.assertNotIn(BIP84_RECEIVE_0, aus)

    def test_pfade_und_dateinamen(self):
        for roh in (
            "Datei /Users/eva/Downloads/ledgers_geheim.csv gelesen",
            r"Import C:\Users\eva\Documents\coinbase.xlsx",
            "Quelle ~/private/strike_statement.csv",
            "nur ledgers_geheim.csv",
        ):
            aus = redigiere(roh)
            self.assertNotIn("eva", aus, roh)
            self.assertNotIn("ledgers_geheim", aus, aus)
            self.assertNotIn("strike_statement", aus, aus)
            self.assertNotIn("coinbase.xlsx", aus.lower() if "coinbase.xlsx" in roh.lower() else aus + "ok")

    def test_groessenordnung_kein_exakter_betrag(self):
        text = groessenordnung("0.01000000", einheit="BTC")
        self.assertIn("10^", text)
        self.assertNotIn("0.01000000", text)
        self.assertEqual(groessenordnung(0), "0")
        self.assertEqual(groessenordnung(None), "ohne Betrag")

    def test_tag_iso_nur_kalendertag(self):
        # 2024-07-01 10:00:00 UTC
        self.assertEqual(tag_iso(1719831600), "2024-07-01")
        self.assertNotIn("10:00", tag_iso(1719831600))
        self.assertEqual(tag_iso(None), "ohne Datum")

    def test_ausnahme_ohne_werte(self):
        try:
            raise ValueError(f"Zeile mit {BIP84_RECEIVE_0} und {txid('c1')}")
        except ValueError as exc:
            text = ausnahme_text(exc)
        self.assertIn("ValueError", text)
        self.assertIn("test_boerse_log_redaktion", text)
        self.assertEqual(_enthalt_marke(text), [], text)

    def test_schreibe_filtert_auch_unstrukturierte_werte(self):
        log = get_logger()
        with self.assertLogs(log, level="INFO") as cm:
            schreibe(
                "test_zeile",
                adresse=BIP84_RECEIVE_0,
                txid=txid("c1"),
                filename="kraken_ledgers.csv",
                sats=1_300_000,
                zeit_ts=1719831600,
            )
        gesamt = "\n".join(cm.output)
        self.assertEqual(_enthalt_marke(gesamt), [], gesamt)
        self.assertNotIn("kraken_ledgers.csv", gesamt)
        self.assertNotIn("1300000", gesamt)
        self.assertIn("2024-07-01", gesamt)
        self.assertIn("ref:", gesamt)


class ParserImportLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _lauf_und_log(self, funktion) -> str:
        buf = io.StringIO()
        log = get_logger()
        with redirect_stdout(buf), self.assertLogs(log, level="INFO") as cm:
            funktion()
        return "\n".join(cm.output) + "\n" + buf.getvalue()

    def _assert_sauber(self, text: str, quellen: dict | None = None) -> None:
        self.assertEqual(_enthalt_marke(text), [], text)
        if quellen is not None:
            roh = str(quellen)
            self.assertEqual(_enthalt_marke(roh), [], roh)
            self.assertNotIn("filename", roh)
            self.assertNotIn(".csv", roh)

    def test_kraken_import_log_ohne_marker(self):
        from core.boerse import kraken, speicher
        from core.exchange_reports import importiere_csv, vorschau

        text = (FIXTURE_DIR / "ledgers_grund.csv").read_text(encoding="utf-8")
        trades = (FIXTURE_DIR / "trades_grund.csv").read_text(encoding="utf-8")

        def lauf():
            vorschau(text, trades, name="Kraken", cache_dir=self.dir)
            importiere_csv(
                text, name="Kraken", filename="ledgers_geheim.csv",
                cache_dir=self.dir, csv_trades=trades,
            )

        logs = self._lauf_und_log(lauf)
        self._assert_sauber(logs, speicher.lies_quellen("kraken", self.dir))
        self.assertIn("kraken", logs.lower())
        self.assertRegex(logs, r"kauf|buchungen|nach_art")

    def test_coinbase_und_strike_import_log_ohne_marker(self):
        from core.boerse import speicher
        from core.exchange_reports import importiere_csv

        def lauf():
            importiere_csv(
                (FIXTURE_DIR / "coinbase_2024.csv").read_text(encoding="utf-8"),
                name="Coinbase", filename="cb_privat.csv", cache_dir=self.dir,
            )
            importiere_csv(
                (FIXTURE_DIR / "strike_eur.csv").read_text(encoding="utf-8"),
                name="Strike", filename="strike_privat.csv", cache_dir=self.dir,
            )

        logs = self._lauf_und_log(lauf)
        self._assert_sauber(logs, speicher.lies_quellen("coinbase", self.dir))
        self._assert_sauber(logs, speicher.lies_quellen("strike", self.dir))
        self.assertIn("coinbase", logs.lower())
        self.assertIn("strike", logs.lower())

    def test_zuordnung_log_ohne_marker_und_mit_kandidaten(self):
        from core.boerse import strike, zuordnung
        from core.boerse.zuordnung import KettenEmpfang

        text = (FIXTURE_DIR / "strike_eur.csv").read_text(encoding="utf-8")
        empfaenge = (
            KettenEmpfang(
                txid=txid("c1"), vout=0, sats=500_000,
                zeit_ts=1751364000, adresse=BIP84_RECEIVE_0,
            ),
        )

        def lauf():
            ergebnis = strike.parse(text, konto="strike")
            zuordnung.schlage_vor(ergebnis.buchungen, empfaenge)

        logs = self._lauf_und_log(lauf)
        self._assert_sauber(logs)
        self.assertIn("kandidaten", logs.lower())
        # Kein exakter Betrag zusammen mit einer Uhrzeit.
        self.assertNotIn("1751364000", logs)
        self.assertNotIn("0.00500000", logs)

    def test_vorschau_spalten_ohne_adresse(self):
        from core.exchange_reports import vorschau

        csv = (
            f"{BIP84_RECEIVE_0},menge,zeit\n"
            f"{txid('c1')},0.01,2024-07-01 10:00:00\n"
        )
        logs = self._lauf_und_log(lambda: vorschau(csv, name="X"))
        self._assert_sauber(logs)
        antwort = vorschau(csv, name="X")
        self.assertFalse(antwort.get("erkannt"))
        gebuendelt = str(antwort)
        self.assertEqual(_enthalt_marke(gebuendelt), [], gebuendelt)

    def test_api_fehlertext_ohne_marker(self):
        from httpserver.api.labels_sanctions_exchange import (
            api_exchange_reports_vorschau,
        )
        from types import SimpleNamespace
        from server import ApiError

        state = SimpleNamespace(exchange_reports_dir=self.dir)
        payload = {
            "name": "X",
            "csv": f"{BIP84_RECEIVE_0},{txid('c1')}\n1,2\n",
        }
        try:
            antwort = api_exchange_reports_vorschau(state, payload)
            text = str(antwort)
        except ApiError as exc:
            text = str(exc.message)
        self.assertEqual(_enthalt_marke(text), [], text)

    def test_unerwartete_ausnahme_landet_redigiert_im_log(self):
        log = get_logger()
        with self.assertLogs(log, level="ERROR") as cm:
            try:
                raise RuntimeError(f"Import {BIP84_ZPUB} {BIP84_RECEIVE_0}")
            except RuntimeError as exc:
                schreibe_ausnahme("import_fehlgeschlagen", exc, filename="geheim.csv")
        gesamt = "\n".join(cm.output)
        self.assertEqual(_enthalt_marke(gesamt), [], gesamt)
        self.assertNotIn("geheim.csv", gesamt)
        self.assertIn("RuntimeError", gesamt)


if __name__ == "__main__":
    unittest.main()
