"""Steuerjahr seitenweise (ISSUES P2): Summen über alles, Zeilen im Fenster."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import main
from core import listen_fenster as lf
from core import steuer_fenster as sf
from tests.fixtures import BIP84_ZPUB, txid
from tests.test_api import ApiTestBasis, utxo


def eintrag(i, sats, *, erfuellt=True, geprueft=True, ts=1_700_000_000, wallet="Alpha", **extra):
    return {"txid": txid(f"{i:02x}"), "vout": 0, "address": f"bc1qadr{i}", "wallet": wallet,
            "value_sats": sats, "datum": datetime.fromtimestamp(ts).strftime("%d.%m.%Y"),
            "time_ts": ts, "frist_ende": "", "erfuellt": erfuellt, "geprueft": geprueft,
            "herkunft": "", "grundlage_label": "geprüft", "neuvermoegen": False, **extra}


def abgang(i, sats, *, ts=1_710_000_000, boerse=None):
    return {"txid": txid(f"a{i:01x}"), "vout": 1, "address": f"bc1qab{i}", "wallet": "Beta",
            "value_sats": sats, "datum": "01.01.2023", "time_ts": 1_672_570_000,
            "abgang_datum": "09.03.2024", "abgang_time_ts": ts, "abgang_txid": txid(f"b{i:01x}"),
            "exchange_spends": [{"name": boerse}] if boerse else [],
            "frist_erfuellt": True, "neuvermoegen": False}


def auswertung(eintraege, abgaenge=()):
    return {"jahr": 2024, "stichtag_regel": "", "kennzahlen": {"gesamt_count": len(eintraege)},
            "zeitstrahl": {"events": [1, 2, 3]}, "hinweise": ["x"],
            "eintraege": list(eintraege), "abgaenge": list(abgaenge), "_objekte": [object()]}


class TestFenster(unittest.TestCase):

    def setUp(self):
        self.e = [eintrag(i, 1000 + i, erfuellt=i % 3 != 0, ts=1_700_000_000 + i * 86400)
                  for i in range(25)]
        self.a = [abgang(i, 500 + i, boerse="Kraken" if i == 4 else None) for i in range(13)]

    def test_alle_summen_ueber_alles_zeilen_im_fenster(self):
        r = sf.fenster(auswertung(self.e, self.a), limit=4, limit_abgaenge=6)
        self.assertNotIn("eintraege", r)
        self.assertNotIn("_objekte", r)
        self.assertEqual(r["zeitstrahl"], {"events": [1, 2, 3]})
        g = r["steuer_gruppen"]
        erfuellt = [x for x in self.e if x["erfuellt"]]
        self.assertEqual(g["erfuellt"]["voll_count"], len(erfuellt))
        self.assertEqual(g["erfuellt"]["total"], len(erfuellt))
        self.assertEqual(g["erfuellt"]["voll_sats"], sum(x["value_sats"] for x in erfuellt))
        self.assertEqual(g["erfuellt"]["items"], erfuellt[:4])
        self.assertEqual(len(r["abgaenge_fenster"]["items"]), 6)
        self.assertEqual(r["abgaenge_fenster"]["total"], 13)
        # Verschiedene Tage → kein gemeinsamer Bewertungstag (kein Fiat).
        self.assertIsNone(r["kennzahlen_ts"]["gesamt"])
        self.assertEqual(len(r["gelb_keys"]), 9)
        self.assertEqual(len(r["grau_keys"]), 0)
        self.assertFalse(r["lots_fertig"])
        fertig = sf.fenster(
            {**auswertung(self.e, self.a), "_lots": True},
            limit=4, limit_abgaenge=6,
        )
        self.assertTrue(fertig["lots_fertig"])
        self.assertNotIn("_lots", fertig)

    def test_teil_seite_ohne_rest(self):
        r = sf.fenster(auswertung(self.e, self.a), teil="offen", offset=4, limit=4)
        offen = [x for x in self.e if not x["erfuellt"]]
        self.assertEqual(set(r), {"jahr", "teil", "seitenweise", "steuer_gruppen"})
        self.assertEqual(r["steuer_gruppen"]["offen"]["items"], offen[4:8])
        self.assertEqual(r["steuer_gruppen"]["offen"]["offset"], 4)
        ab = sf.fenster(auswertung(self.e, self.a), teil="abgaenge", offset=10, limit=5)
        self.assertEqual(len(ab["abgaenge_fenster"]["items"]), 3)  # 11–13, exakt

    def test_filter_ueber_alle_seiten(self):
        f = lf.parse_filter("kraken")
        r = sf.fenster(auswertung(self.e, self.a), limit=2, f=f)
        self.assertEqual(r["abgaenge_fenster"]["total"], 1)
        self.assertEqual(r["abgaenge_fenster"]["sats"], 504)
        self.assertEqual(r["abgaenge_fenster"]["voll_count"], 13)
        self.assertEqual(r["steuer_gruppen"]["erfuellt"]["total"], 0)
        # Adresse von „Seite 3“ findet sich auch mit Seitengröße 2.
        f = lf.parse_filter("bc1qadr20")
        r = sf.fenster(auswertung(self.e, self.a), limit=2, f=f)
        self.assertEqual([x["address"] for x in r["steuer_gruppen"]["erfuellt"]["items"]],
                         ["bc1qadr20"])

    def test_betrag_und_datum_wie_browser(self):
        f = lf.parse_filter(">1010 <1013")
        r = sf.fenster(auswertung(self.e), limit=50, f=f)
        werte = sorted(x["value_sats"] for g in r["steuer_gruppen"].values() for x in g["items"])
        self.assertEqual(werte, [1011, 1012])
        grenze = 1_700_000_000 + 20 * 86400
        f = lf.parse_filter(">1.1.20", nach_ts=str(grenze))  # Browser-Grenze gewinnt
        r = sf.fenster(auswertung(self.e), limit=50, f=f)
        n = sum(g["total"] for g in r["steuer_gruppen"].values())
        self.assertEqual(n, 5)

    def test_haltefrist_text_als_stichwort(self):
        f = lf.parse_filter("innerhalb")
        r = sf.fenster(auswertung(self.e), limit=50, f=f, lang="de")
        self.assertEqual(r["steuer_gruppen"]["erfuellt"]["total"], 0)
        self.assertEqual(r["steuer_gruppen"]["offen"]["total"], 9)
        f = lf.parse_filter("within")
        r = sf.fenster(auswertung(self.e), limit=50, f=f, lang="en")
        self.assertEqual(r["steuer_gruppen"]["offen"]["total"], 9)

    def test_gemeinsamer_tag_wie_gemeinsamerAtTs(self):
        mittag = int(datetime(2024, 3, 1, 12, tzinfo=timezone.utc).timestamp())
        self.assertEqual(sf.gemeinsamer_ts([{"time_ts": mittag - 3600}, {"time_ts": mittag}]),
                         mittag)
        self.assertIsNone(sf.gemeinsamer_ts([{"time_ts": mittag}, {"time_ts": mittag + 86400}]))
        self.assertIsNone(sf.gemeinsamer_ts([{"time_ts": mittag}, {"time_ts": 0}]))
        self.assertIsNone(sf.gemeinsamer_ts([]))

    def test_gelbe_schluessel_vollstaendig(self):
        e = [eintrag(i, 10, erfuellt=False, geprueft=i % 2 == 0) for i in range(30)]
        r = sf.fenster(auswertung(e), limit=1)
        self.assertEqual(len(r["gelb_keys"]), 15)
        self.assertEqual(len(r["grau_keys"]), 15)
        self.assertEqual(len(r["steuer_gruppen"]["offen"]["items"]), 1)


def sa_abfluss(i, sats, *, wallet="Alpha", ts=1_736_726_460, gewaehlt=False, adressen=()):
    return {"id": txid(f"c{i:02x}"), "txid": txid(f"c{i:02x}"), "abgang_datum": "13.01.2025",
            "abgang_zeit": "01:01:00", "abgang_ts": ts, "netto_sats": sats, "eigenuebertrag": False,
            "wallets": [wallet], "input_count": 1,
            "inputs": [{"address": a} for a in adressen], "ausgewaehlt": gewaehlt, "hypothese": False}


def sa_utxo(i, sats, *, datum="08.05.2024", wallet="Beta"):
    return {"id": f"utxo:{txid(f'd{i:02x}')}:{i}", "txid": txid(f"d{i:02x}"), "vout": i,
            "address": f"bc1qsa{i}", "wallet": wallet, "value_sats": sats,
            "anschaffung_datum": datum, "external_address": "", "grundlage": "Herkunft verfolgt",
            "stichtag": "31.12.2025", "hypothese": True, "ausgewaehlt": False}


def sa_kandidaten(abfluesse, utxos):
    return {"jahr": 2025, "txid_hinweis": "", "kandidaten": list(abfluesse),
            "abfluesse": list(abfluesse), "utxos": list(utxos), "verlauf": {"vorhanden": True},
            "stichtag_hypothese": "31.12.2025", "hinweise": ["x"], "person": {}}


class TestSaFenster(unittest.TestCase):
    """Bericht Sat-Geschichte: Kandidaten seitenweise, Auswahl über alle Seiten."""

    def setUp(self):
        self.ab = [sa_abfluss(i, 1000 + i, wallet="Kraken" if i % 3 == 0 else "Alpha",
                              gewaehlt=(i == 17)) for i in range(25)]
        self.ut = [sa_utxo(i, 500 + i, datum="01.03.2023" if i < 4 else "08.05.2024")
                   for i in range(12)]
        self.k = sa_kandidaten(self.ab, self.ut)

    def test_alle_ohne_listen_mit_fenstern_und_vorauswahl(self):
        r = sf.sa_fenster(self.k, limit=4, limit_utxos=6)
        for weg in ("kandidaten", "abfluesse", "utxos"):
            self.assertNotIn(weg, r)
        self.assertEqual(r["verlauf"], {"vorhanden": True})
        self.assertEqual(r["stichtag_hypothese"], "31.12.2025")
        a, u = r["abfluesse_fenster"], r["utxos_fenster"]
        self.assertEqual((len(a["items"]), a["total"], a["voll_count"]), (4, 25, 25))
        self.assertEqual(a["voll_sats"], sum(1000 + i for i in range(25)))
        self.assertEqual((len(u["items"]), u["total"]), (6, 12))
        # Vorauswahl auch außerhalb der ersten Seite.
        self.assertEqual(r["ausgewaehlt"], {"abfluss": [txid("c11")], "utxo": []})

    def test_seite_und_zeilen(self):
        r = sf.sa_fenster(self.k, teil="abfluesse", offset=20, limit=10)
        self.assertEqual([e["id"] for e in r["abfluesse_fenster"]["items"]],
                         [e["id"] for e in self.ab[20:]])
        self.assertNotIn("utxos_fenster", r)
        self.assertNotIn("verlauf", r)
        z = sf.sa_fenster(self.k, teil="zeilen", limit=3, limit_utxos=2)
        self.assertEqual(len(z["abfluesse_fenster"]["items"]), 3)
        self.assertEqual(len(z["utxos_fenster"]["items"]), 2)

    def test_filter_ueber_alle_seiten_wie_browser(self):
        f = lf.parse_filter("kraken")
        r = sf.sa_fenster(self.k, teil="abfluesse", limit=2, f=f)
        self.assertEqual(r["abfluesse_fenster"]["total"], 9)
        self.assertEqual(r["abfluesse_fenster"]["sats"], sum(1000 + i for i in range(0, 25, 3)))
        # Betrag (netto_sats) und Anschaffungsdatum (12 Uhr lokal) wie data-*.
        self.assertEqual(sf.sa_fenster(self.k, teil="abfluesse", f=lf.parse_filter(">1020"))
                         ["abfluesse_fenster"]["total"], 4)
        vor = sf.sa_fenster(self.k, teil="utxos", f=lf.parse_filter("<1.1.24"))
        self.assertEqual(vor["utxos_fenster"]["total"], 4)
        # Eingangsadressen zählen als Adresse der Zeile.
        k = sa_kandidaten([sa_abfluss(1, 5, adressen=["bc1qinput9"])], [])
        self.assertEqual(sf.sa_fenster(k, teil="abfluesse", f=lf.parse_filter("input9"))
                         ["abfluesse_fenster"]["total"], 1)

    def test_werte_aller_treffer_fuer_alle_keine(self):
        r = sf.sa_fenster(self.k, teil="utxos", limit=2, nur_werte=True)
        self.assertEqual(r["werte"], [u["id"] for u in self.ut])
        f = sf.sa_fenster(self.k, teil="utxos", nur_werte=True, f=lf.parse_filter("<1.1.24"))
        self.assertEqual(f["werte"], [u["id"] for u in self.ut[:4]])
        ohne_id = dict(self.ut[0]); del ohne_id["id"]
        self.assertEqual(sf.sa_wert("utxos", ohne_id), f"utxo:{txid('d00')}:0")

    def test_datum_rollt_wie_js(self):
        self.assertEqual(sf._ts_aus_de_datum_mittag("31.02.2024"),
                         int(datetime(2024, 3, 2, 12).timestamp()))
        self.assertEqual(sf._ts_aus_de_datum_mittag("01.00.2024"),
                         int(datetime(2023, 12, 1, 12).timestamp()))
        self.assertIsNone(sf._ts_aus_de_datum_mittag("2024-01-01"))


class TestSteuerFensterApi(ApiTestBasis):

    def setUp(self):
        super().setUp()
        main.save_xpub_utxo_cache(BIP84_ZPUB, [
            utxo(84_000_000 - i, marker=f"{i:02x}", vout=i) for i in range(5)
        ], self.cache, 6)

    def test_ohne_seite_unveraendert(self):
        _, körper = self.anfrage("/api/tax?jahr=2026&frist=1")
        self.assertEqual(len(körper["eintraege"]), 5)
        self.assertNotIn("seitenweise", körper)

    def test_seite_liefert_summen_und_fenster(self):
        _, voll = self.anfrage("/api/tax?jahr=2026&frist=1")
        _, körper = self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&limit=2")
        self.assertTrue(körper["seitenweise"])
        self.assertEqual(körper["kennzahlen"], voll["kennzahlen"])
        self.assertEqual(körper["zeitstrahl"], voll["zeitstrahl"])
        n = sum(g["voll_count"] for g in körper["steuer_gruppen"].values())
        self.assertEqual(n, 5)
        for g in körper["steuer_gruppen"].values():
            self.assertLessEqual(len(g["items"]), 2)
        _, seite = self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&teil=offen&offset=2&limit=2")
        self.assertNotIn("zeitstrahl", seite)
        self.assertIn("offen", seite["steuer_gruppen"])

    def test_blaettern_rechnet_nicht_neu(self):
        from unittest import mock
        import httpserver.steuer as steuer_mod
        import server

        echt = steuer_mod._steuer_auswertung
        with mock.patch.object(server, "_steuer_auswertung", side_effect=echt) as spion:
            _, erst = self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&limit=2")
            self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&teil=offen&offset=2&limit=2")
            self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&teil=zeilen&limit=2&q=bc1q")
            self.assertEqual(spion.call_count, 1)
            # Andere Parameter → eigene Auswertung.
            self.anfrage("/api/tax?jahr=2026&frist=2&seite=1&limit=2")
            self.assertEqual(spion.call_count, 2)
            # Neuer Cache-Stand → neu gerechnet.
            main.save_xpub_utxo_cache(BIP84_ZPUB, [
                utxo(84_000_000 - i, marker=f"{i:02x}", vout=i) for i in range(3)
            ], self.cache, 6)
            _, neu = self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&limit=2")
            self.assertEqual(spion.call_count, 3)
        n = sum(g["voll_count"] for g in neu["steuer_gruppen"].values())
        self.assertEqual(n, 3)


class TestSaFensterApi(ApiTestBasis):

    def setUp(self):
        super().setUp()
        main.save_xpub_utxo_cache(BIP84_ZPUB, [
            utxo(84_000_000 - i, marker=f"{i:02x}", vout=i) for i in range(5)
        ], self.cache, 6)

    def _roh(self, pfad, *, methode="GET", daten=None):
        import json as _json
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{pfad}", method=methode,
            data=_json.dumps(daten).encode() if daten is not None else None)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Satsage-Token", self.state.token)
        with urllib.request.urlopen(req, timeout=20) as antwort:
            return antwort.status, antwort.read().decode("utf-8")

    def test_ohne_seite_unveraendert(self):
        _, körper = self.anfrage("/api/tax/selbstanzeige/kandidaten?jahr=2026")
        self.assertIn("utxos", körper)
        self.assertIn("abfluesse", körper)
        self.assertNotIn("seitenweise", körper)

    def test_seite_zahlen_ueber_alles_und_werte(self):
        _, voll = self.anfrage("/api/tax/selbstanzeige/kandidaten?jahr=2026")
        n = len(voll["utxos"])
        self.assertGreater(n, 2)
        _, körper = self.anfrage(
            "/api/tax/selbstanzeige/kandidaten?jahr=2026&seite=1&limit=2&limit_utxos=2")
        self.assertTrue(körper["seitenweise"])
        self.assertNotIn("utxos", körper)
        self.assertEqual(körper["utxos_fenster"]["voll_count"], n)
        self.assertEqual(len(körper["utxos_fenster"]["items"]), 2)
        _, seite = self.anfrage(
            "/api/tax/selbstanzeige/kandidaten?jahr=2026&seite=1&teil=utxos&offset=2&limit=2")
        self.assertEqual([u["id"] for u in seite["utxos_fenster"]["items"]],
                         [u["id"] for u in voll["utxos"][2:4]])
        _, werte = self.anfrage(
            "/api/tax/selbstanzeige/kandidaten?jahr=2026&seite=1&teil=utxos&werte=1")
        self.assertEqual(werte["werte"], [u["id"] for u in voll["utxos"]])

    def test_blaettern_rechnet_nicht_neu(self):
        from unittest import mock
        from core import selbstanzeige as sa

        echt = sa.kandidaten
        with mock.patch.object(sa, "kandidaten", side_effect=echt) as spion:
            basis = "/api/tax/selbstanzeige/kandidaten?jahr=2026&seite=1"
            self.anfrage(basis + "&limit=2")
            self.anfrage(basis + "&teil=utxos&offset=2&limit=2")
            self.anfrage(basis + "&teil=utxos&werte=1&q=zz")
            self.assertEqual(spion.call_count, 1)
            self.anfrage(basis.replace("2026", "2025") + "&limit=2")
            self.assertEqual(spion.call_count, 2)

    def test_bericht_per_post_wie_get(self):
        _, voll = self.anfrage("/api/tax/selbstanzeige/kandidaten?jahr=2026")
        keys = [u["id"][5:] for u in voll["utxos"]]
        status, per_get = self._roh(
            "/api/tax/selbstanzeige/export.csv?jahr=2026&frist=1&utxos=" + ",".join(keys))
        self.assertEqual(status, 200)
        status, per_post = self._roh(
            "/api/tax/selbstanzeige/export.csv", methode="POST",
            daten={"jahr": "2026", "frist": "1", "txids": [], "utxos": keys})
        self.assertEqual(status, 200)
        self.assertEqual(per_post, per_get)
        for k in keys:
            self.assertIn(k.split(":")[0], per_post)
        status, html = self._roh(
            "/api/tax/selbstanzeige/bericht.html", methode="POST",
            daten={"jahr": 2026, "frist": 1, "utxos": keys[:1], "theme": "hell"})
        self.assertEqual(status, 200)
        self.assertIn("<html", html.lower())


if __name__ == "__main__":
    unittest.main()
