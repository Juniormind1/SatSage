"""Logs der Börsenhistorie enthalten keine Fixture-Kennungen."""
from __future__ import annotations

import logging
import unittest
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


if __name__ == "__main__":
    unittest.main()
