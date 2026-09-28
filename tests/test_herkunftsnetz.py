"""
Steuerjahr · Herkunftsnetz als Overlay (Schritt 1): flaches Netz aus dem
gespeicherten Baum — Anteile, Endknoten, Bündel, X aus Blockhöhen, dieselbe
Skala wie ``core.tax.zeitstrahl``; dazu die API.
"""
from __future__ import annotations

import unittest
from datetime import datetime

import main
from core import herkunftsnetz as hn
from core import trace_cache
from core.tax import auswerten
from core.trace import FULL_RESOLUTION_INPUT_LIMIT
from tests.fixtures import BIP84_ZPUB, txid
from tests.test_api import ApiTestBasis, utxo as api_utxo
from tests.test_tax import utxo as tax_utxo

SKALA = hn.Skala(
    von=datetime(2023, 1, 1), bis=datetime(2025, 1, 1), hoechst=10_000,
)


def k(name, vout=0):
    return f"{txid(name)}:{vout}"


def intern(name, sats, zeit, kinder=(), **extra):
    return {"type": "internal", "from_utxo": k(name), "amount_sats": sats,
            "wallet": "Alpha", "time_label": zeit, "block_height": None,
            "children": list(kinder), **extra}


def extern(name, sats, zeit):
    return {"type": "external", "from_utxo": k(name), "amount_sats": sats,
            "wallet": None, "time_label": zeit, "block_height": None,
            "children": []}


def baum(sats, kinder, zeit="01.06.2024 12:00:00", **root):
    return {"found": True,
            "root": {"txid": txid("f0"), "vout": 0, "amount_sats": sats,
                     "wallet": "Alpha", "time_label": zeit, "type": "utxo", **root},
            "children": list(kinder)}


def netz(b, **kw):
    return hn.flach(b, k("f0"), SKALA, **kw)


def knoten(r):
    return {v["key"]: v for v in r["vorfahren"]}


def kanten(r):
    return {(e["von"], e["nach"]): e["sats"] for e in r["kanten"]}


class TestSkalaWieZeitstrahl(unittest.TestCase):
    """X/Y der Overlay-Skala = pos/y aller Zeitstrahl-Events."""

    def _pruefe(self, auswertung):
        skala = hn.skala_aus_auswertung(auswertung)
        events = auswertung["zeitstrahl"]["events"]
        self.assertTrue(events)
        for e in events:
            zeit = datetime.fromtimestamp(e["time_ts"])
            self.assertAlmostEqual(
                max(0.0, min(100.0, skala.pos(zeit))), e["pos"], places=3,
            )
            self.assertEqual(skala.y(e["value_sats"]), e["y"])
        self.assertEqual(skala.hoechst, auswertung["zeitstrahl"]["max_sats"])

    def test_abgeschlossenes_jahr(self):
        utxos = [tax_utxo(1000 * (i + 1), f"0{i + 1}.0{i + 2}.202{i % 3 + 3} 1{i}:00",
                          marker=f"{i:02x}") for i in range(6)]
        self._pruefe(auswerten(utxos, 2025, jetzt=datetime(2026, 2, 1, 9, 0)))

    def test_laufendes_jahr_bezug_heute(self):
        utxos = [tax_utxo(5_000, "15.03.2024 08:00", marker="a1"),
                 tax_utxo(70_000, "20.05.2026 18:30", marker="a2")]
        a = auswerten(utxos, 2026, jetzt=datetime(2026, 9, 28, 7, 59, 13))
        self.assertTrue(a["laufend"])
        self.assertEqual(a["bezug_ts"], datetime(2026, 9, 28, 7, 59, 13).timestamp())
        self._pruefe(a)

    def test_ohne_zeitstrahl_none(self):
        self.assertIsNone(hn.skala_aus_auswertung({"zeitstrahl": {"vorhanden": False}}))

    def test_vor_achsenbeginn_negativ_ungeklemmt(self):
        self.assertLess(SKALA.pos(datetime(2022, 1, 1)), 0)
        self.assertGreater(SKALA.y(10**9), 100)  # größer als Skalenende


class TestOutputZeit(unittest.TestCase):

    def test_hoehe_ueber_block_header_cache(self):
        ts = int(datetime(2024, 1, 2, 3, 4, 5).timestamp())
        kn = {"block_height": 840_000, "time_label": "01.01.2020 00:00:00"}
        self.assertEqual(hn.output_zeit(kn, {840_000: ts}.get),
                         datetime.fromtimestamp(ts))

    def test_hoehe_aus_label(self):
        ts = int(datetime(2024, 5, 6, 7, 8, 9).timestamp())
        kn = {"time_label": "Block 841,234 · 01.01.2020 00:00:00"}
        self.assertEqual(hn.output_zeit(kn, {841_234: ts}.get),
                         datetime.fromtimestamp(ts))

    def test_rueckfall_blockzeit_dann_label(self):
        self.assertEqual(hn.output_zeit({"block_time": 1_700_000_000}),
                         datetime.fromtimestamp(1_700_000_000))
        kn = {"block_height": 5, "time_label": "Block 5 · 02.03.2024 04:05:06"}
        self.assertEqual(hn.output_zeit(kn, lambda h: None),
                         datetime(2024, 3, 2, 4, 5, 6))
        self.assertIsNone(hn.output_zeit({"time_label": "unbekannt"}))

    def test_pos_output_aus_hoehe(self):
        ts = int(datetime(2024, 1, 1).timestamp())
        b = baum(1000, [dict(intern("a1", 1000, ""), block_height=900_001)])
        r = netz(b, block_zeit={900_001: ts}.get)
        self.assertEqual(knoten(r)[k("a1")]["pos_output"],
                         SKALA.pos(datetime(2024, 1, 1)))
        self.assertAlmostEqual(knoten(r)[k("a1")]["pos_output"], 365 / 731 * 100, places=3)


class TestFlach(unittest.TestCase):

    def test_anteile_pro_rata_und_endknoten(self):
        b = baum(1000, [
            intern("a1", 600, "01.03.2024 12:00:00", [
                extern("e1", 700, "01.01.2024 12:00:00"),
                intern("b1", 300, "01.02.2024 12:00:00", [
                    {"type": "coinbase", "from_utxo": "", "amount_sats": 0,
                     "time_label": "", "children": []},
                ]),
            ]),
            extern("e2", 400, "01.04.2024 12:00:00"),
        ])
        r = netz(b)
        kn, ka = knoten(r), kanten(r)
        self.assertEqual(r["fokus_key"], k("f0"))
        self.assertEqual(kn[k("f0")]["tiefe"], 0)
        self.assertEqual(ka[(k("a1"), k("f0"))], 600)
        self.assertEqual(ka[(k("e2"), k("f0"))], 400)
        self.assertEqual(ka[(k("e1"), k("a1"))], 420)
        self.assertEqual(ka[(k("b1"), k("a1"))], 180)
        self.assertEqual(ka[(f"coinbase:{k('b1')}", k("b1"))], 180)
        # Summe in den Fokus = Fokus-Output.
        self.assertEqual(sum(s for (v, n), s in ka.items() if n == k("f0")), 1000)
        self.assertEqual(kn[k("a1")]["typ"], "eigen")
        self.assertFalse(kn[k("a1")]["ende"])
        self.assertTrue(kn[k("a1")]["eigen"])
        self.assertEqual(kn[k("e1")]["typ"], "fremd")
        self.assertTrue(kn[k("e1")]["ende"])
        self.assertFalse(kn[k("e1")]["eigen"])
        self.assertEqual(kn[f"coinbase:{k('b1')}"]["typ"], "coinbase")
        self.assertTrue(kn[f"coinbase:{k('b1')}"]["ende"])
        self.assertEqual(kn[k("b1")]["anteil_sats"], 180)
        # Voller Vorgänger bleibt im Tooltip; Y ist der Anteil am Fokus.
        self.assertGreater(kn[k("e1")]["value_sats"], kn[k("b1")]["value_sats"])
        self.assertEqual(kn[k("e1")]["anteil_sats"], 420)
        # Y = Vorgänger-UTXO × Anteil am Fokus (420/1000 bzw. 180/1000).
        self.assertEqual(kn[k("e1")]["y"], SKALA.y(int(round(700 * 420 / 1000))))
        self.assertEqual(kn[k("b1")]["y"], SKALA.y(int(round(300 * 180 / 1000))))
        self.assertGreater(kn[k("e1")]["y"], kn[k("b1")]["y"])
        self.assertTrue(next(e for e in r["kanten"] if e["von"] == k("a1"))["eigen"])
        self.assertFalse(next(e for e in r["kanten"] if e["von"] == k("e1"))["eigen"])

    def test_sammel_tx_ueber_limit_ein_buendel(self):
        n = FULL_RESOLUTION_INPUT_LIMIT + 5
        kinder = [intern(f"{i:02x}", 10, f"0{1 + i % 9}.01.2024 12:00:00") for i in range(n)]
        r = netz(baum(n * 10, kinder))
        kn = knoten(r)
        self.assertEqual(len(kn), 2)
        bund = kn[f"buendel:{k('f0')}"]
        self.assertEqual(bund["typ"], "buendel")
        self.assertEqual(bund["n"], n)
        self.assertEqual(bund["value_sats"], n * 10)
        self.assertTrue(bund["ende"])
        self.assertTrue(bund["eigen"])
        # X: jüngste Output-Zeit im Bündel.
        self.assertEqual(bund["zeit"], "09.01.2024 12:00")
        self.assertEqual(bund["zeit_von"], "01.01.2024 12:00")
        self.assertEqual(kanten(r)[(f"buendel:{k('f0')}", k("f0"))], n * 10)

    def test_coinjoin_und_abgebrochene_aufloesung_buendeln(self):
        cj = baum(500, [intern("a1", 250, "01.01.2024 00:00:00"),
                        intern("a2", 250, "01.01.2024 00:00:00")],
                  tx_class="whirlpool")
        self.assertEqual([v["typ"] for v in netz(cj)["vorfahren"]], ["eigen", "buendel"])
        abbruch = baum(500, [
            intern("a1", 500, "01.01.2024 00:00:00"),
            {"type": "external_unresolved", "input_count": 30, "amount_sats": 0,
             "from_utxo": "", "children": []},
        ])
        bund = knoten(netz(abbruch))[f"buendel:{k('f0')}"]
        self.assertEqual(bund["n"], 31)

    def test_dag_kopien_zusammengefuehrt(self):
        gemeinsam = lambda: intern("c1", 100, "01.01.2024 00:00:00")  # noqa: E731
        b = baum(200, [
            intern("a1", 100, "01.02.2024 00:00:00", [gemeinsam()]),
            intern("a2", 100, "01.02.2024 00:00:00", [gemeinsam()]),
        ])
        r = netz(b)
        self.assertEqual(sum(1 for v in r["vorfahren"] if v["key"] == k("c1")), 1)
        self.assertEqual(knoten(r)[k("c1")]["anteil_sats"], 200)
        self.assertEqual(knoten(r)[k("c1")]["y"], SKALA.y(int(round(100 * 200 / 200))))
        self.assertEqual(kanten(r)[(k("c1"), k("a1"))], 100)
        self.assertEqual(kanten(r)[(k("c1"), k("a2"))], 100)

    def test_horizont_marker_am_hop_ohne_eigenen_knoten(self):
        b = baum(1000, [{"type": "tax_horizon", "from_utxo": k("f0"), "amount_sats": 1000,
                         "time_label": "01.06.2024 12:00:00", "children": []}])
        r = netz(b)
        self.assertEqual(len(r["vorfahren"]), 1)
        self.assertEqual(r["kanten"], [])
        self.assertTrue(r["vorfahren"][0]["ende"])
        self.assertEqual(r["vorfahren"][0]["abbruch"], "horizont")

    def test_obergrenze_buendelt_rest(self):
        kette = intern("z9", 10, "01.01.2024 00:00:00")
        for i in range(8):
            kette = intern(f"{i:02x}", 10, "01.01.2024 00:00:00", [kette])
        r = netz(baum(10, [kette]), max_knoten=4)
        self.assertTrue(r["gekappt"])
        self.assertLessEqual(len(r["vorfahren"]), 5)
        self.assertEqual(r["vorfahren"][-1]["typ"], "buendel")


class TestHorizontLaufBraucht(unittest.TestCase):
    """Overlay-Lauf (``baum_noetig``): alter Ingress ohne Baum reicht nicht."""

    def test_ingress_ohne_baum(self):
        from types import SimpleNamespace
        from unittest import mock

        import server
        from httpserver.trace_helpers import _trace_offen_steuer

        state = SimpleNamespace(immutable_cache_dir=None)
        utxos = [{"txid": txid("a1"), "vout": 0}]
        with mock.patch.object(server.trace_cache, "kopf", return_value=None), \
                mock.patch.object(server.main, "load_utxo_ingress_cache",
                                  return_value={"external_time_ts": 1_700_000_000}):
            self.assertEqual(_trace_offen_steuer(state, utxos, set()), [])
            self.assertEqual(
                _trace_offen_steuer(state, utxos, set(), baum_noetig=True),
                [(txid("a1"), 0)],
            )


class TestHerkunftsnetzApi(ApiTestBasis):

    def setUp(self):
        super().setUp()
        self.utxos = [api_utxo(84_000_000 - i, marker=f"{i:02x}", vout=i) for i in range(3)]
        main.save_xpub_utxo_cache(BIP84_ZPUB, self.utxos, self.cache, 6)
        self.key = f"{txid('01')}:1"
        trace_cache.speichern(txid("01"), 1, {
            "found": True,
            "root": {"id": "0", "txid": txid("01"), "vout": 1, "amount_sats": 83_999_999,
                     "wallet": "Cold Storage", "time_label": "14.11.2023 23:13:20",
                     "type": "utxo"},
            "children": [
                {"id": "0.0", "type": "external", "from_utxo": f"{txid('e1')}:0",
                 "amount_sats": 90_000_000, "wallet": None, "block_height": None,
                 "time_label": "01.10.2023 10:00:00", "children": []},
            ],
            "summary": {},
        }, self.immutable)

    def test_netz_auf_zeitstrahl_skala(self):
        _, steuer = self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&limit=2")
        ev = {e["key"]: e for e in steuer["zeitstrahl"]["events"]}
        status, r = self.anfrage(f"/api/tax/herkunftsnetz?jahr=2026&frist=1&key={self.key}")
        self.assertEqual(status, 200)
        self.assertFalse(r["trace_fehlt"])
        self.assertEqual(r["fokus_pos"], ev[self.key]["pos"])
        self.assertEqual(r["fokus_y"], ev[self.key]["y"])
        kn = knoten(r)
        self.assertEqual(kn[self.key].get("wallet_id"), self.wallet_id(BIP84_ZPUB))
        self.assertNotIn("wallet_id", kn[f"{txid('e1')}:0"])
        self.assertEqual(kn[f"{txid('e1')}:0"]["typ"], "fremd")
        self.assertEqual(r["kanten"], [{"von": f"{txid('e1')}:0", "nach": self.key,
                                        "sats": 83_999_999, "eigen": False}])
        # Nur das flache Netz geht raus — kein Baum (Lazy-Tree-Invariante).
        self.assertNotIn("children", r)
        self.assertNotIn("baum", r)
        self.assertFalse(any("children" in v for v in r["vorfahren"]))
        # Zeitstrahl selbst unverändert, kein Overlay in events[].
        _, danach = self.anfrage("/api/tax?jahr=2026&frist=1&seite=1&limit=2")
        self.assertEqual(danach["zeitstrahl"]["events"], steuer["zeitstrahl"]["events"])

    def test_ohne_trace_meldet_fehlend(self):
        status, r = self.anfrage(
            f"/api/tax/herkunftsnetz?jahr=2026&frist=1&key={txid('00')}:0")
        self.assertEqual(status, 200)
        self.assertTrue(r["trace_fehlt"])
        self.assertEqual(r["vorfahren"], [])

    def test_fremder_oder_kaputter_schluessel(self):
        status, _ = self.anfrage(
            f"/api/tax/herkunftsnetz?jahr=2026&frist=1&key={txid('ff')}:0")
        self.assertEqual(status, 404)
        status, _ = self.anfrage("/api/tax/herkunftsnetz?jahr=2026&key=kaputt")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
