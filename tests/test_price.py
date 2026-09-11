"""
BTC/Fiat-Kurse: Parsing, Cache, Fallback — ohne Netz (Fetch injiziert).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from core import price


def _mempool_spot(**kwargs):
    basis = {"time": 1_700_000_000, "USD": 42000, "EUR": 39000, "GBP": 33000,
             "CAD": 56000, "CHF": 37000, "AUD": 64000, "JPY": 6_200_000}
    basis.update(kwargs)
    return basis


def _mempool_hist(eur: float = 39136.0, ts: int = 1_704_067_200):
    return {
        "prices": [{"time": ts, "EUR": eur, "USD": 42266}],
        "exchangeRates": {"USDEUR": 0.86},
    }


def _coinbase(amount: str = "38999.5"):
    return {"data": {"amount": amount, "base": "BTC", "currency": "EUR"}}


class TestHilfen(unittest.TestCase):

    def test_waehrung_normalisieren(self):
        self.assertEqual(price.normalisiere_waehrung("eur"), "EUR")
        with self.assertRaises(ValueError):
            price.normalisiere_waehrung("XYZ")

    def test_sats_umrechnung(self):
        self.assertAlmostEqual(price.sats_in_fiat(50_000_000, 40_000), 20_000.0)
        self.assertEqual(price.fiat_in_sats(20_000, 40_000), 50_000_000)

    def test_parse_tag(self):
        self.assertEqual(price.parse_tag("2024-01-01"), date(2024, 1, 1))
        self.assertEqual(price.parse_tag(1_704_067_200), date(2024, 1, 1))
        self.assertEqual(price.unix_tagesbeginn(date(2024, 1, 1)), 1_704_067_200)

    def test_mempool_base_default(self):
        self.assertEqual(price.mempool_price_base(None), price.MEMPOOL_PRICE_DEFAULT)
        self.assertEqual(
            price.mempool_price_base("https://mempool.lan/"),
            "https://mempool.lan",
        )


class TestQuellen(unittest.TestCase):

    def test_spot_mempool(self):
        def fetch(url, timeout):
            self.assertIn("/api/v1/prices", url)
            return _mempool_spot()

        preis = price.hole_spot_mempool("EUR", fetch=fetch)
        self.assertEqual(preis.amount, 39000)
        self.assertEqual(preis.source, "mempool")
        self.assertEqual(preis.kind, "spot")
        self.assertEqual(preis.currency, "EUR")

    def test_spot_coinbase(self):
        def fetch(url, timeout):
            self.assertIn("coinbase.com", url)
            self.assertIn("BTC-EUR", url)
            return _coinbase()

        preis = price.hole_spot_coinbase("EUR", fetch=fetch)
        self.assertEqual(preis.amount, 38999.5)
        self.assertEqual(preis.source, "coinbase")

    def test_tageskurs_mempool(self):
        gesehen = {}

        def fetch(url, timeout):
            gesehen["url"] = url
            return _mempool_hist()

        preis = price.hole_tageskurs_mempool("2024-01-01", "EUR", fetch=fetch)
        self.assertEqual(preis.amount, 39136.0)
        self.assertEqual(preis.kind, "day")
        self.assertEqual(preis.day, "2024-01-01")
        self.assertIn("historical-price", gesehen["url"])
        self.assertIn("timestamp=1704067200", gesehen["url"])
        self.assertIn("currency=EUR", gesehen["url"])

    def test_spot_fehlende_waehrung(self):
        def fetch(url, timeout):
            return {"time": 1, "USD": 1}

        with self.assertRaises(price.PriceError):
            price.hole_spot_mempool("EUR", fetch=fetch)


class TestOrchestrierung(unittest.TestCase):

    def test_spot_nutzt_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {"n": 0}

            def fetch(url, timeout):
                calls["n"] += 1
                return _mempool_spot()

            a = price.spot_preis(
                "EUR", immutable_cache_dir=root, fetch=fetch, jetzt=1_000,
            )
            b = price.spot_preis(
                "EUR", immutable_cache_dir=root, fetch=fetch, jetzt=1_000 + 60,
            )
            self.assertEqual(calls["n"], 1)
            self.assertEqual(a.amount, b.amount)
            self.assertTrue((root / "btc_price" / "spot_EUR.json").is_file())

    def test_spot_cache_laeuft_ab(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {"n": 0}

            def fetch(url, timeout):
                calls["n"] += 1
                return _mempool_spot(EUR=39000 + calls["n"])

            price.spot_preis(
                "EUR", immutable_cache_dir=root, fetch=fetch, jetzt=1_000, ttl=10,
            )
            price.spot_preis(
                "EUR", immutable_cache_dir=root, fetch=fetch, jetzt=1_020, ttl=10,
            )
            self.assertEqual(calls["n"], 2)

    def test_spot_fallback_coinbase(self):
        def fetch(url, timeout):
            if "mempool" in url:
                raise price.PriceError("mempool down")
            return _coinbase("40123.0")

        preis = price.spot_preis("EUR", fetch=fetch)
        self.assertEqual(preis.source, "coinbase")
        self.assertEqual(preis.amount, 40123.0)

    def test_spot_fallback_lokaler_tageskurs(self):
        """Wenn Mempool und Coinbase ausfallen: Bundle-/Cache-Tageskurs."""
        def fetch(url, timeout):
            raise price.PriceError("offline")

        heute = datetime.now(timezone.utc).date()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {heute.isoformat(): 55555.0},
                currency="EUR",
                quelle="test",
            )
            preis = price.spot_preis(
                "EUR", immutable_cache_dir=root, fetch=fetch,
            )
            self.assertEqual(preis.amount, 55555.0)
            self.assertIn("day", preis.source)
            self.assertEqual(preis.kind, "spot")
            self.assertTrue(preis.warning)
            self.assertIn(heute.isoformat(), preis.warning)

    def test_spot_fallback_alter_tageskurs_ohne_lange_fehlermeldung(self):
        """Veraltetes Bundle (>14 Tage): trotzdem letzter Kurs, kurze Warning."""
        def fetch(url, timeout):
            raise price.PriceError(
                "Öffentliches Ziel „mempool.space“ für mempool ist blockiert. "
                "| Öffentliches Ziel „api.coinbase.com“ …"
            )

        alt = date(2026, 8, 27)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {alt.isoformat(): 67669.08},
                currency="EUR",
                quelle="bundle",
            )
            preis = price.spot_preis(
                "EUR",
                immutable_cache_dir=root,
                fetch=fetch,
                jetzt=int(datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp()),
            )
            self.assertEqual(preis.amount, 67669.08)
            self.assertEqual(preis.day, alt.isoformat())
            self.assertIn("letzter Kurs aus Historie von 2026-08-27", preis.warning)
            self.assertNotIn(" | ", preis.warning or "")
            self.assertNotIn("blockiert", preis.warning or "")

    def test_eigene_mempool_url_zuerst(self):
        gesehen = []

        def fetch(url, timeout):
            gesehen.append(url)
            if "mempool.lan" in url:
                return _mempool_spot(EUR=11111)
            raise price.PriceError("sollte nicht")

        preis = price.spot_preis(
            "EUR", mempool_url="https://mempool.lan", fetch=fetch,
        )
        self.assertEqual(preis.amount, 11111)
        self.assertTrue(gesehen[0].startswith("https://mempool.lan/"))

    def test_tageskurs_dauerhaft_cache(self):
        """Netz nur für Tage außerhalb Bundle/CSV — dann JSON-Cache."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Cache-CSV ohne den gesuchten Tag — Bundle wird nicht mehr gelesen.
            price.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {"2000-01-01": 1.0},
                currency="EUR",
                quelle="test-leer",
            )
            calls = {"n": 0}

            def fetch(url, timeout):
                calls["n"] += 1
                return _mempool_hist(eur=39136.0, ts=1_704_067_200)

            a = price.tageskurs(
                "2024-01-01", "EUR", immutable_cache_dir=root, fetch=fetch,
            )
            b = price.tageskurs(
                "2024-01-01", "EUR", immutable_cache_dir=root, fetch=fetch,
            )
            self.assertEqual(calls["n"], 1)
            self.assertEqual(a.day, "2024-01-01")
            self.assertEqual(b.amount, 39136.0)
            pfad = root / "btc_price" / "EUR" / "2024-01-01.json"
            self.assertTrue(pfad.is_file())
            roh = json.loads(pfad.read_text(encoding="utf-8"))
            self.assertEqual(roh["source"], "mempool")
            self.assertIn("fetched_at", roh)

    def test_tageskurs_ohne_quelle(self):
        def fetch(url, timeout):
            raise price.PriceError("offline")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {"2000-01-01": 1.0},
                currency="EUR",
                quelle="test-leer",
            )
            with self.assertRaises(price.PriceError):
                price.tageskurs(
                    "2099-12-31", "EUR",
                    immutable_cache_dir=root, fetch=fetch,
                )


class TestCsvHistorie(unittest.TestCase):

    def test_parse_einfach(self):
        serie = price.parse_kurs_csv("date,price\n2024-01-01,42000.5\n2024-01-02,43000\n")
        self.assertEqual(serie["2024-01-01"], 42000.5)
        self.assertEqual(serie["2024-01-02"], 43000.0)

    def test_parse_deutsch_semikolon(self):
        serie = price.parse_kurs_csv(
            "Datum;Preis\n01.01.2024;42.000,50\n02.01.2024;43000\n"
        )
        self.assertEqual(serie["2024-01-01"], 42000.5)

    def test_bundle_tageskurs(self):
        bundel = price.bundel_historie_dir() / "EUR.csv"
        if not bundel.is_file():
            self.skipTest("Bundle EUR.csv fehlt")
        lokal = price.lade_tageskurs_csv(None, "2020-01-01", "EUR")
        self.assertIsNotNone(lokal)
        self.assertGreater(lokal.amount, 0)
        self.assertEqual(lokal.source, "bundle")

    def test_historie_status_mit_serie(self):
        bundel = price.bundel_historie_dir() / "EUR.csv"
        if not bundel.is_file():
            self.skipTest("Bundle EUR.csv fehlt")
        kurz = price.historie_status(None, "EUR")
        self.assertTrue(kurz["ok"])
        self.assertNotIn("series", kurz)
        voll = price.historie_status(None, "EUR", mit_serie=True)
        self.assertTrue(voll["ok"])
        self.assertIn("series", voll)
        self.assertEqual(len(voll["series"]), voll["days"])
        self.assertIn(voll["from"], voll["series"])
        self.assertGreater(voll["series"][voll["from"]], 0)

    def test_import_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Zuerst Bundle-Tag nutzen: Import ohne Cache startet von Bundle
            ergebnis = price.importiere_kurs_csv(
                root,
                "EUR",
                "date,price\n2099-01-01,1\n",
                dateiname="test.csv",
            )
            self.assertTrue(ergebnis["ok"])
            self.assertGreaterEqual(ergebnis["days"], 1)
            self.assertEqual(ergebnis["to"], "2099-01-01")
            # Zukunftstag aus Import
            p = price.tageskurs("2099-01-01", "EUR", immutable_cache_dir=root)
            self.assertEqual(p.amount, 1.0)
            self.assertIn(p.source, ("cache", "import", "csv"))
            # Historischer Tag bleibt aus Merge mit Bundle
            alt = price.lade_tageskurs_csv(root, "2020-06-01", "EUR")
            if alt is not None:
                self.assertGreater(alt.amount, 0)

    def test_tageskurs_ohne_netz_aus_bundle(self):
        """Fehlende Tage nicht im Bundle → Netz; vorhandene ohne Netz."""
        def fetch(url, timeout):
            raise price.PriceError("netz aus")

        lokal = price.lade_tageskurs_csv(None, "2019-06-15", "EUR")
        if lokal is None:
            self.skipTest("Kein Bundle-Kurs für 2019-06-15")
        preis = price.tageskurs(
            "2019-06-15", "EUR", immutable_cache_dir=None, fetch=fetch,
        )
        self.assertEqual(preis.amount, lokal.amount)


class TestLiveOptional(unittest.TestCase):
    """Nur wenn Netz erreichbar — sonst Skip."""

    @classmethod
    def setUpClass(cls):
        try:
            price._fetch_json(f"{price.MEMPOOL_PRICE_DEFAULT}/api/v1/prices", 5.0)
            cls.netz = True
        except price.PriceError:
            cls.netz = False

    def test_live_spot(self):
        if not self.netz:
            self.skipTest("mempool.space nicht erreichbar")
        preis = price.spot_preis("EUR")
        self.assertGreater(preis.amount, 0)
        self.assertEqual(preis.currency, "EUR")

    def test_live_tageskurs_netz_nur_luecke(self):
        if not self.netz:
            self.skipTest("mempool.space nicht erreichbar")
        # Tag weit vor Bundle-Start (EUR ab 2016) — muss Netz nutzen oder fehlen
        try:
            preis = price.tageskurs("2015-01-01", "USD")
            self.assertGreater(preis.amount, 0)
        except price.PriceError:
            self.skipTest("weder Bundle noch Mempool für 2015-01-01 USD")


if __name__ == "__main__":
    unittest.main()
