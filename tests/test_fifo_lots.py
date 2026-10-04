"""
Herkunft · FIFO je Output: Reihenfolge der Lose, Verbraucher, Teilung,
Herkunftsnetz mit Tx-Kontext (FIFO bzw. Rückfall anteilig), PSBT-Vorschau
und Herkunftsverfolgung mit derselben Verteilung, Netto-Maximum.
"""
from __future__ import annotations

import inspect
import itertools
import random
import unittest
from datetime import datetime

from core import coin_auswahl as ca
from core import fifo_lots as fl
from core import herkunftsnetz as hn
from core import psbt_bau
from tests.fixtures import txid

SKALA = hn.Skala(von=datetime(2023, 1, 1), bis=datetime(2025, 1, 1), hoechst=10_000)
L = fl.Los


def k(name, vout=0):
    return f"{txid(name)}:{vout}"


def marken(lose):
    return [(l.marke, l.sats) for l in lose]


# --- core.fifo_lots ----------------------------------------------------------

class TestOrdnen(unittest.TestCase):
    def test_aelteste_zuerst_ohne_zeit_zuletzt(self):
        lose = [L(1, 30, (0,), "c"), L(1, None, (0,), "x"), L(1, 10, (2,), "a"), L(1, 20, (1,), "b")]
        self.assertEqual([l.marke for l in fl.ordnen(lose)], ["a", "b", "c", "x"])

    def test_gleichstand_nach_vin_dann_reihenfolge_im_eingang(self):
        lose = [L(1, 5, (1, 0), "v1a"), L(1, 5, (0, 1), "v0b"), L(1, 5, (0, 0), "v0a"),
                L(1, 5, (1, 1), "v1b")]
        self.assertEqual([l.marke for l in fl.ordnen(lose)], ["v0a", "v0b", "v1a", "v1b"])

    def test_deterministisch_unabhaengig_von_der_eingabe_reihenfolge(self):
        lose = [L(1 + i, i % 3, (i % 2, i), i) for i in range(12)]
        erwartet = [l.marke for l in fl.ordnen(lose)]
        rng = random.Random(7)
        for _ in range(20):
            gemischt = lose[:]
            rng.shuffle(gemischt)
            self.assertEqual([l.marke for l in fl.ordnen(gemischt)], erwartet)

    def test_leere_lose_fallen_weg(self):
        self.assertEqual(fl.ordnen([L(0, 1), L(-3, 2)]), [])

    def test_mehrere_ohne_zeit_nach_rang(self):
        lose = [L(1, None, (1,), "b"), L(1, None, (0,), "a")]
        self.assertEqual([l.marke for l in fl.ordnen(lose)], ["a", "b"])


class TestVerbraucher(unittest.TestCase):
    def test_raus_nach_vout_dann_gebuehr_dann_zurueck(self):
        reihe = fl.verbraucher([(3, 30, True), (2, 20, False), (0, 10, True), (1, 5, False)], 7)
        self.assertEqual(reihe, [(("vout", 1), 5), (("vout", 2), 20), (fl.GEBUEHR, 7),
                                 (("vout", 0), 10), (("vout", 3), 30)])

    def test_ohne_gebuehr_kein_verbraucher(self):
        self.assertEqual(fl.verbraucher([(0, 10, False)], 0), [(("vout", 0), 10)])

    def test_nur_rueckfluesse_gebuehr_zuerst(self):
        self.assertEqual(fl.verbraucher([(1, 4, True), (0, 6, True)], 2),
                         [(fl.GEBUEHR, 2), (("vout", 0), 6), (("vout", 1), 4)])


class TestVerteilen(unittest.TestCase):
    def test_teilt_lose_und_behaelt_zeit_und_marke(self):
        lose = fl.ordnen([L(600, 1, (0,), "alt"), L(500, 2, (1,), "jung")])
        aus = fl.verteilen(lose, [("a", 700), ("b", 400)])
        self.assertEqual(marken(aus["a"]), [("alt", 600), ("jung", 100)])
        self.assertEqual(marken(aus["b"]), [("jung", 400)])
        self.assertEqual(aus["a"][1].zeit, 2)

    def test_exakt_ganzzahlig_und_erhaltend(self):
        rng = random.Random(3)
        for _ in range(200):
            lose = fl.ordnen(L(rng.randint(1, 10**8), rng.randint(0, 9), (i,), i)
                             for i in range(rng.randint(1, 6)))
            gesamt = fl.summe(lose)
            teile = sorted(rng.sample(range(1, gesamt), min(3, gesamt - 1))) if gesamt > 1 else []
            grenzen = [0] + teile + [gesamt]
            reihe = [(i, b - a) for i, (a, b) in enumerate(zip(grenzen, grenzen[1:]))]
            aus = fl.verteilen(lose, reihe)
            for schluessel, bedarf in reihe:
                self.assertEqual(fl.summe(aus[schluessel]), bedarf)
                self.assertTrue(all(isinstance(l.sats, int) for l in aus[schluessel]))
            # Reihenfolge bleibt: Verkettung = die ursprünglichen Lose.
            flach = [l for s, _b in reihe for l in aus[s]]
            je = {}
            for l in flach:
                je[l.marke] = je.get(l.marke, 0) + l.sats
            self.assertEqual(je, {l.marke: l.sats for l in lose})

    def test_fehlbetrag_trifft_die_letzten(self):
        aus = fl.verteilen([L(50, 1, (), "x")], [("a", 40), ("b", 30), ("c", 5)])
        self.assertEqual((fl.summe(aus["a"]), fl.summe(aus["b"]), aus["c"]), (40, 10, []))

    def test_ueberschuss_bleibt_unverteilt(self):
        aus = fl.verteilen([L(100, 1, (), "x")], [("a", 30)])
        self.assertEqual(fl.summe(aus["a"]), 30)

    def test_ohne_lose_leer(self):
        self.assertEqual(fl.verteilen([], [("a", 5)]), {"a": []})

    def test_verbraucher_mit_null_bedarf(self):
        aus = fl.verteilen([L(10, 1, (), "x")], [("a", 0), ("b", 10)])
        self.assertEqual((aus["a"], fl.summe(aus["b"])), ([], 10))


class TestKlassen(unittest.TestCase):
    def test_gruen_vor_gelb_ueber_alle_inputs(self):
        lose = fl.klassen_lose([(0, 5, 0), (7, 3, 0), (2, 0, 0)])
        self.assertEqual([(l.marke, l.rang, l.sats) for l in lose],
                         [("gruen", (1,), 7), ("gruen", (2,), 2), ("gelb", (0,), 5), ("gelb", (1,), 3)])

    def test_beta_e463_wie_im_lab(self):
        """Lab: 61 815 219 grün + 3 127 089 gelb, :1 verlässt (16 235 577), Gebühr 418."""
        lose = fl.klassen_lose([(61_815_219, 3_127_089, 0)])
        wechsel = 61_815_219 + 3_127_089 - 16_235_577 - 418
        aus = fl.verteilen(lose, fl.verbraucher([(0, wechsel, True), (1, 16_235_577, False)], 418))
        self.assertEqual(fl.klassen_summen(aus[("vout", 1)]),
                         {"sats_gruen": 16_235_577, "sats_gelb": 0, "sats_grau": 0})
        self.assertEqual(fl.klassen_summen(aus[fl.GEBUEHR])["sats_gruen"], 418)
        self.assertEqual(fl.klassen_summen(aus[("vout", 0)]),
                         {"sats_gruen": 45_579_224, "sats_gelb": 3_127_089, "sats_grau": 0})

    def test_grau_zuletzt(self):
        lose = fl.klassen_lose([(0, 0, 4), (1, 2, 0)])
        self.assertEqual([l.marke for l in lose], ["gruen", "gelb", "grau"])


class TestPlanGleichSpur(unittest.TestCase):
    """PSBT-Vorschau (Klassen-Rang) = Spur (echte Zeiten), solange grün älter als gelb ist."""

    def test_zufaellige_txs(self):
        rng = random.Random(11)
        for _ in range(300):
            inputs = [(rng.choice([0, rng.randint(1, 10**7)]), rng.choice([0, rng.randint(1, 10**7)]), 0)
                      for _i in range(rng.randint(1, 5))]
            inputs = [i for i in inputs if i[0] + i[1] > 0] or [(1000, 0, 0)]
            gesamt = sum(g + y for g, y, _ in inputs)
            fee = rng.randint(0, min(1000, gesamt - 1))
            rest = gesamt - fee
            n = rng.randint(1, 4)
            schnitte = sorted(rng.sample(range(1, rest), n - 1)) if rest > n else []
            grenzen = [0] + schnitte + [rest]
            werte = [b - a for a, b in zip(grenzen, grenzen[1:])]
            ausgaenge = [(v, w, rng.random() < 0.5) for v, w in enumerate(werte)]
            reihe = fl.verbraucher(ausgaenge, fee)
            plan = fl.verteilen(fl.klassen_lose(inputs), reihe)
            # Spur: echte Zeiten, grün vor der Frist (< 100), gelb danach (>= 200).
            echt = []
            for pos, (g, y, _gr) in enumerate(inputs):
                if g:
                    echt.append(L(g, rng.randint(0, 99), (pos, 0), "gruen"))
                if y:
                    echt.append(L(y, rng.randint(200, 299), (pos, 1), "gelb"))
            spur = fl.verteilen(fl.ordnen(echt), reihe)
            for schluessel, _b in reihe:
                self.assertEqual(fl.klassen_summen(plan[schluessel]), fl.klassen_summen(spur[schluessel]))

    def test_eine_funktion_fuer_beide(self):
        self.assertIn("fifo_lots.verteilen", inspect.getsource(psbt_bau.erzeuge))
        self.assertIn("fifo_lots.verbraucher", inspect.getsource(psbt_bau.erzeuge))
        quelle = inspect.getsource(hn._fifo_hop)
        self.assertIn("fifo_lots.verteilen", quelle)
        self.assertIn("fifo_lots.verbraucher", quelle)


# --- Herkunftsnetz mit FIFO-Kontext -----------------------------------------

ALPHA = {f"alpha{i}" for i in range(10)}
BETA = {f"beta{i}" for i in range(10)}


def wallet_von(adresse):
    if adresse in ALPHA:
        return "Alpha"
    if adresse in BETA:
        return "Beta"
    return None


def tx(eingaenge, ausgaenge):
    """Esplora-Form: eingaenge [(name, vout)], ausgaenge [(sats, adresse)]."""
    return {"vin": [{"txid": txid(n), "vout": v} for n, v in eingaenge],
            "vout": [{"value": s, "scriptpubkey_address": a, "scriptpubkey": "00"} for s, a in ausgaenge]}


def kontext(txs):
    return hn.FifoKontext(tx=lambda t: txs.get(t), wallet=wallet_von)


def knoten(name, sats, zeit, kinder=(), *, vout=0, adresse="alpha0", typ="internal"):
    return {"type": typ, "from_utxo": k(name, vout), "amount_sats": sats,
            "wallet": wallet_von(adresse) or "", "time_label": zeit, "block_height": None,
            "address": adresse, "children": list(kinder)}


def fremd(name, sats, zeit):
    return {"type": "external", "from_utxo": k(name), "amount_sats": sats, "wallet": None,
            "time_label": zeit, "block_height": None, "address": "fremd", "children": []}


def baum(sats, kinder, *, vout=0, zeit="01.06.2024 12:00:00"):
    return {"found": True,
            "root": {"txid": txid("f0"), "vout": vout, "amount_sats": sats, "wallet": "Alpha",
                     "time_label": zeit, "type": "utxo"},
            "children": list(kinder)}


def netz(b, txs, vout=0):
    return hn.flach(b, k("f0", vout), SKALA, fifo=None if txs is None else kontext(txs))


def anteile(r):
    return {v["key"]: v["anteil_sats"] for v in r["vorfahren"]}


def kanten(r):
    return {(e["von"], e["nach"]): e["sats"] for e in r["kanten"]}


ALT, MITTEL, JUNG = "01.01.2023 12:00:00", "01.06.2023 12:00:00", "01.01.2024 12:00:00"


class TestHerkunftFifo(unittest.TestCase):
    def setUp(self):
        # f0: jung (vin 0) + alt (vin 1); :0 fremd 700, :1 Wechsel 390, Gebühr 10.
        self.txs = {txid("f0"): tx([("a2", 0), ("a1", 0)], [(700, "fremd1"), (390, "alpha1")])}
        self.kinder = lambda: [knoten("a2", 500, JUNG), knoten("a1", 600, ALT)]  # noqa: E731

    def test_zahlung_bekommt_die_aeltesten(self):
        r = netz(baum(700, self.kinder()), self.txs)
        self.assertEqual(anteile(r), {k("f0"): 700, k("a1"): 600, k("a2"): 100})
        self.assertEqual(kanten(r), {(k("a1"), k("f0")): 600, (k("a2"), k("f0")): 100})

    def test_wechselgeld_behaelt_den_rest(self):
        r = netz(baum(390, self.kinder(), vout=1), self.txs, vout=1)
        # Der alte Input ist ganz in Zahlung + Gebühr aufgegangen: kein Vorfahr mehr.
        self.assertEqual(anteile(r), {k("f0", 1): 390, k("a2"): 390})

    def test_anteilig_ohne_kontext(self):
        r = netz(baum(390, self.kinder(), vout=1), None, vout=1)
        self.assertEqual(anteile(r), {k("f0", 1): 390, k("a2"): 177, k("a1"): 213})

    def test_gebuehr_vor_wechselgeld_und_wechsel_vor_zahlung_in_vout(self):
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(590, "alpha1"), (500, "fremd1")])}
        kinder = [knoten("a1", 100, ALT), knoten("a2", 1000, JUNG)]
        zahlung = netz(baum(500, kinder, vout=1), txs, vout=1)
        self.assertEqual(anteile(zahlung), {k("f0", 1): 500, k("a1"): 100, k("a2"): 400})
        wechsel = netz(baum(590, [knoten("a1", 100, ALT), knoten("a2", 1000, JUNG)]), txs)
        self.assertEqual(anteile(wechsel), {k("f0"): 590, k("a2"): 590})

    def test_mehrere_zahlungen_nach_vout(self):
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(200, "fremd1"), (200, "fremd2"), (190, "alpha1")])}
        mk = lambda: [knoten("a1", 300, ALT), knoten("a2", 300, JUNG)]  # noqa: E731
        self.assertEqual(anteile(netz(baum(200, mk()), txs)), {k("f0"): 200, k("a1"): 200})
        self.assertEqual(anteile(netz(baum(200, mk(), vout=1), txs, 1)),
                         {k("f0", 1): 200, k("a1"): 100, k("a2"): 100})
        self.assertEqual(anteile(netz(baum(190, mk(), vout=2), txs, 2)), {k("f0", 2): 190, k("a2"): 190})

    def test_anderes_eigenes_wallet_verlaesst_das_wallet(self):
        """Umbuchung Alpha → Beta: Beta bekommt die ältesten Lose (Klassen bleiben)."""
        txs = {txid("f0"): tx([("a2", 0), ("a1", 0)], [(495, "alpha1"), (500, "beta1")])}
        mk = lambda: [knoten("a2", 500, JUNG), knoten("a1", 500, ALT)]  # noqa: E731
        self.assertEqual(anteile(netz(baum(500, mk(), vout=1), txs, 1)), {k("f0", 1): 500, k("a1"): 500})
        self.assertEqual(anteile(netz(baum(495, mk()), txs)), {k("f0"): 495, k("a2"): 495})

    def test_alles_im_selben_wallet_gebuehr_zuerst_dann_nach_vout(self):
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(400, "alpha1"), (595, "alpha2")])}
        mk = lambda: [knoten("a1", 500, ALT), knoten("a2", 500, JUNG)]  # noqa: E731
        self.assertEqual(anteile(netz(baum(400, mk()), txs)), {k("f0"): 400, k("a1"): 400})
        self.assertEqual(anteile(netz(baum(595, mk(), vout=1), txs, 1)),
                         {k("f0", 1): 595, k("a1"): 95, k("a2"): 500})

    def test_gleichstand_nach_vin(self):
        txs = {txid("f0"): tx([("a2", 0), ("a1", 0)], [(300, "fremd1"), (695, "alpha1")])}
        r = netz(baum(300, [knoten("a2", 500, ALT), knoten("a1", 500, ALT)]), txs)
        self.assertEqual(anteile(r), {k("f0"): 300, k("a2"): 300})

    def test_ohne_zeit_zaehlt_die_zeit_des_hops(self):
        """Ein Los ohne Zeit ist höchstens so alt wie die Tx, die es ausgibt."""
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(300, "fremd1"), (695, "alpha1")])}
        r = netz(baum(300, [knoten("a1", 500, ""), knoten("a2", 500, JUNG)]), txs)
        self.assertEqual(anteile(r), {k("f0"): 300, k("a2"): 300})

    def test_zwei_hops_lose_wandern_mit(self):
        txs = {
            txid("a1"): tx([("c1", 0), ("c2", 0)], [(300, "fremd1"), (495, "alpha1")]),
            txid("f0"): tx([("a1", 1), ("b1", 0)], [(250, "fremd2"), (540, "alpha2")]),
        }
        a1 = knoten("a1", 495, MITTEL, [knoten("c1", 400, ALT), knoten("c2", 400, JUNG)], vout=1)
        b1 = knoten("b1", 300, "01.03.2023 12:00:00")
        r = netz(baum(250, [a1, b1]), txs)
        # a1:1 trägt c1 95 (alt, Rest nach Zahlung + Gebühr) + c2 400 (jung);
        # b1 liegt zeitlich dazwischen und füllt die Zahlung auf.
        self.assertEqual(anteile(r), {k("f0"): 250, k("a1", 1): 95, k("c1"): 95, k("b1"): 155})
        self.assertEqual(kanten(r), {(k("a1", 1), k("f0")): 95, (k("c1"), k("a1", 1)): 95,
                                     (k("b1"), k("f0")): 155})

    def test_zwei_outputs_derselben_tx_als_vorfahren(self):
        txs = {
            txid("a1"): tx([("c1", 0), ("c2", 0)], [(400, "alpha1"), (595, "alpha2")]),
            txid("f0"): tx([("a1", 0), ("a1", 1)], [(990, "fremd1")]),
        }
        c = lambda: [knoten("c1", 500, ALT), knoten("c2", 500, JUNG)]  # noqa: E731
        b = baum(990, [knoten("a1", 400, MITTEL, c()), knoten("a1", 595, MITTEL, c(), vout=1)])
        r = netz(b, txs)
        self.assertEqual(anteile(r), {k("f0"): 990, k("a1"): 400, k("a1", 1): 590,
                                      k("c1"): 495, k("c2"): 495})
        self.assertEqual(kanten(r)[(k("c1"), k("a1"))], 400)
        self.assertEqual(kanten(r)[(k("c1"), k("a1", 1))], 95)
        self.assertEqual(kanten(r)[(k("c2"), k("a1", 1))], 495)
        self.assertEqual(sum(1 for v in r["vorfahren"] if v["key"] == k("c1")), 1)

    def test_summe_in_den_fokus_exakt(self):
        rng = random.Random(5)
        for _ in range(50):
            werte = [rng.randint(1000, 10**8) for _i in range(rng.randint(2, 5))]
            fee = rng.randint(1, 999)
            zahlung = rng.randint(1, sum(werte) - fee - 1)
            wechsel = sum(werte) - fee - zahlung
            namen = [f"{i + 1:02x}" for i in range(len(werte))]
            txs = {txid("f0"): tx([(n, 0) for n in namen], [(zahlung, "fremd1"), (wechsel, "alpha1")])}
            for vout, sats in ((0, zahlung), (1, wechsel)):
                kinder = [knoten(n, w, f"0{1 + rng.randint(0, 8)}.0{1 + i}.2023 12:00:00")
                          for i, (n, w) in enumerate(zip(namen, werte))]
                r = netz(baum(sats, kinder, vout=vout), txs, vout)
                self.assertEqual(sum(s for (v, n), s in kanten(r).items() if n == k("f0", vout)), sats)


class TestHerkunftRueckfall(unittest.TestCase):
    """Anteilig, wo FIFO keine sichere Grundlage hat."""

    def _gleich_anteilig(self, b, txs, vout=0):
        mit = netz(b, txs, vout)
        ohne = netz(b, None, vout)
        self.assertEqual(anteile(mit), anteile(ohne))
        return mit

    def test_fremder_input(self):
        txs = {txid("f0"): tx([("a1", 0), ("e1", 0)], [(700, "fremd1"), (390, "alpha1")])}
        r = self._gleich_anteilig(baum(700, [knoten("a1", 600, ALT), fremd("e1", 500, JUNG)]), txs)
        self.assertEqual(anteile(r)[k("e1")], 318)

    def test_tx_fehlt_im_cache(self):
        self._gleich_anteilig(baum(700, [knoten("a1", 600, ALT), knoten("a2", 500, JUNG)]), {})

    def test_betrag_passt_nicht(self):
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(701, "fremd1"), (389, "alpha1")])}
        self._gleich_anteilig(baum(700, [knoten("a1", 600, ALT), knoten("a2", 500, JUNG)]), txs)

    def test_eingangszahl_passt_nicht(self):
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0), ("a3", 0)], [(700, "fremd1"), (390, "alpha1")])}
        self._gleich_anteilig(baum(700, [knoten("a1", 600, ALT), knoten("a2", 500, JUNG)]), txs)

    def test_negative_gebuehr(self):
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(700, "fremd1"), (500, "alpha1")])}
        self._gleich_anteilig(baum(700, [knoten("a1", 600, ALT), knoten("a2", 500, JUNG)]), txs)

    def test_eingaenge_ohne_bekanntes_wallet(self):
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(700, "fremd1"), (390, "alpha1")])}
        kinder = [knoten("a1", 600, ALT, adresse="x1"), knoten("a2", 500, JUNG, adresse="x2")]
        self._gleich_anteilig(baum(700, kinder), txs)

    def test_coinjoin_buendel(self):
        b = baum(500, [knoten("a1", 250, ALT), knoten("a2", 250, JUNG)])
        b["root"]["tx_class"] = "whirlpool"
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(500, "fremd1")])}
        self.assertEqual([v["typ"] for v in netz(b, txs)["vorfahren"]], ["eigen", "buendel"])

    def test_tieferer_hop_rueckfall_oberer_fifo(self):
        """Pro Hop entschieden: unten fremd (anteilig), oben FIFO."""
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(300, "fremd1"), (695, "alpha1")])}
        a1 = knoten("a1", 500, MITTEL, [knoten("c1", 400, ALT), fremd("e1", 400, ALT)])
        r = netz(baum(300, [a1, knoten("a2", 500, JUNG)]), txs)
        # a1 anteilig: c1 250 + e1 250, beide mit alter Zeit; oben FIFO: erst
        # c1 (Reihenfolge im Eingang), dann e1 — a2 (jung) bleibt im Wechselgeld.
        self.assertEqual(anteile(r), {k("f0"): 300, k("a1"): 300, k("c1"): 250, k("e1"): 50})


class TestFifoKontextAusCache(unittest.TestCase):
    def test_ohne_wallet_kontext_kein_fifo(self):
        self.assertIsNone(hn.FifoKontext.aus_cache("/nix", None))

    def test_zuordnung_nur_bekannter_bestand(self):
        from types import SimpleNamespace

        ctx = SimpleNamespace(own_label=lambda a: "Alpha" if a == "a" else None,
                              address_to_wallet={"b": "Beta"})
        f = hn.FifoKontext.aus_cache("/nix", ctx)
        self.assertEqual((f.wallet("a"), f.wallet("b"), f.wallet("c"), f.wallet("")),
                         ("Alpha", "Beta", None, None))
        self.assertIsNone(f.tx("00" * 32))  # nicht im Cache: Rückfall anteilig


# --- Netto-Maximum -------------------------------------------------------------

def kand(werte):
    return [ca.Kandidat(key=f"{i:064x}:0", txid=f"{i:064x}", vout=0, wert=w, beitrag=g, zeit=i)
            for i, (w, g) in enumerate(werte, start=1)]


class TestNettoMax(unittest.TestCase):
    def _pruefe(self, kd, rate, groessen=None):
        m = ca.netto_max(kd, basis_rate=rate, groessen=groessen)
        b = m["max_netto_sats"]
        if b <= 0:
            return m
        for strategie in ca.STRATEGIEN:
            erg = ca.waehle(kd, betrag=b, basis_rate=rate, strategie=strategie, groessen=groessen)
            self.assertEqual(erg["status"], "ok", (strategie, b))
            self.assertNotEqual(ca.waehle(kd, betrag=b + 1, basis_rate=rate, strategie=strategie,
                                          groessen=groessen)["status"], "ok", strategie)
        # Brute force: keine Teilmenge deckt m + 1.
        for n in range(1, len(kd) + 1):
            for teil in itertools.combinations(kd, n):
                erg = ca.waehle(kd, betrag=b + 1, basis_rate=rate, groessen=groessen,
                                nur=[x.key for x in teil])
                self.assertNotEqual(erg["status"], "ok")
        return m

    def test_vier_gruene_wie_psbt_test(self):
        werte = [112_173_005, 51_480_067, 60_349_786, 19_339_420]
        m = self._pruefe(kand([(w, w) for w in werte]), ca.FesteRate(2000))
        self.assertEqual(m["max_netto_sats"], sum(werte) - 628)
        self.assertEqual((m["inputs"], m["outputs"], m["fee_sats"]), (4, 1, 628))

    def test_gemischt_braucht_wechselgeld(self):
        m = self._pruefe(kand([(97_847_370, 29_468_315)]), ca.FesteRate(2000))
        self.assertEqual(m["max_netto_sats"], 29_468_315 - 282)
        self.assertEqual(m["outputs"], 2)

    def test_gemischt_und_gruen(self):
        self._pruefe(kand([(1_000_000, 400_000), (300_000, 300_000), (50_000, 50_000)]), ca.FesteRate(3000))

    def test_staub_input_faellt_weg(self):
        kd = kand([(100_000, 100_000), (60, 60)])
        m = self._pruefe(kd, ca.FesteRate(1000))
        self.assertEqual(m["inputs"], 1)

    def test_taproot_ziel(self):
        g = ca.Groessen(ziel_vb=43)
        m = self._pruefe(kand([(500_000, 500_000), (70_000, 70_000)]), ca.FesteRate(5000), g)
        self.assertEqual(m["fee_sats"], 5 * g.vsize(2, 1))

    def test_bruchteil_rate(self):
        self._pruefe(kand([(123_457, 123_457), (98_765, 40_000)]), ca.FesteRate(1234))

    def test_ohne_kandidaten(self):
        self.assertEqual(ca.netto_max([], basis_rate=ca.FesteRate(1000))["max_netto_sats"], 0)

    def test_zufaellig(self):
        rng = random.Random(21)
        for _ in range(25):
            werte = []
            for _i in range(rng.randint(1, 4)):
                w = rng.randint(500, 3_000_000)
                werte.append((w, w if rng.random() < 0.6 else rng.randint(1, w - 1)))
            self._pruefe(kand(werte), ca.FesteRate(rng.choice([1000, 1500, 2000, 7000])))


if __name__ == "__main__":
    unittest.main()


# --- Datum aus den FIFO-Losen (Option A) — Lab-Fälle T2, T5c, T3 -------------

import json as _json  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest import mock  # noqa: E402

import main  # noqa: E402
from core import tax  # noqa: E402
from core import trace_cache  # noqa: E402

JETZT = datetime(2026, 10, 4, 12, 0)  # Bezug: Frist-Grenze 04.10.2025


def _ts(text):
    return int(datetime.strptime(text, "%d.%m.%Y").replace(hour=12).timestamp())


class TestDatumAusLosen(unittest.TestCase):
    """
    Nachgebaut aus dem Regtest-Lab (Broadcast 2026-10-04): Datum, Farbe und
    „erfüllt“ kommen aus denselben FIFO-Losen; anteilig bleibt der Stempel.
    """

    WALLET = {f"beta{i}": "HS Beta" for i in range(9)} | {f"gamma{i}": "HS Gamma" for i in range(9)} \
        | {f"delta{i}": "HS Delta" for i in range(9)} | {f"alpha{i}": "HS Alpha" for i in range(9)}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name)
        self.txs = {}
        self.ctx = SimpleNamespace(
            own_label=lambda a: self.WALLET.get(a), address_to_wallet={},
            resolve_address=lambda a: self.WALLET.get(a), xpub_for_address=lambda a: None,
        )
        patcher = mock.patch("core.xpub_cache.load_cached_tx", side_effect=lambda t, *_a: self.txs.get(t))
        patcher.start()
        self.addCleanup(patcher.stop)

    # Bausteine ------------------------------------------------------------
    def _tx(self, name, eingaenge, ausgaenge):
        self.txs[txid(name)] = tx(eingaenge, ausgaenge)

    @staticmethod
    def _ende(name, sats, datum):
        return {"type": "external", "from_utxo": k(name), "amount_sats": sats,
                "time_label": f"{datum} 12:00:00", "children": []}

    def _eigen(self, name, sats, datum, adresse, kinder, vout=0):
        return {"type": "internal", "from_utxo": k(name, vout), "amount_sats": sats,
                "wallet": self.WALLET[adresse], "address": adresse,
                "time_label": f"{datum} 12:00:00", "children": kinder}

    def _gemischt(self, name, adresse, lose, datum):
        """Eigenes UTXO *name*:0 aus je einem eigenen Vorgänger pro Los."""
        kinder = []
        for i, (sats, los_datum) in enumerate(lose):
            vor = f"{name}{i}"
            self._tx(vor, [(f"x{vor}", 0)], [(sats, adresse)])
            kinder.append(self._eigen(vor, sats, los_datum, adresse, [self._ende(f"x{vor}", sats, los_datum)]))
        self._tx(name, [(f"{name}{i}", 0) for i in range(len(lose))], [(sum(s for s, _ in lose), adresse)])
        return self._eigen(name, sum(s for s, _ in lose), datum, adresse, kinder)

    def _utxo(self, name, vout, sats, datum, adresse, kinder, stempel, **root):
        trace_cache.speichern(txid(name), vout, {
            "found": True,
            "root": {"txid": txid(name), "vout": vout, "amount_sats": sats, "address": adresse,
                     "wallet": self.WALLET[adresse], "time_label": f"{datum} 12:00:00", "type": "utxo",
                     **root},
            "children": kinder,
        }, self.cache)
        ordner = self.cache / main.UTXO_INGRESS_CACHE_SUBDIR
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / f"{txid(name)}_{vout}.json").write_text(_json.dumps({
            "txid": txid(name), "vout": vout,
            "external_time_ts": _ts(stempel[0]), "external_oldest_time_ts": _ts(stempel[1]),
        }), encoding="utf-8")
        return {"txid": txid(name), "vout": vout, "address": adresse, "value": sats,
                "status": {"confirmed": True, "block_height": 800_000, "block_time": _ts(datum)}}

    def _werte(self, utxos, anschaffung):
        erg = tax.auswerten(utxos, 2026, jetzt=JETZT, immutable_cache_dir=self.cache,
                            wallet=self.ctx, anschaffung=anschaffung)
        return {f"{e['txid'][:2]}:{e['vout']}": e for e in erg["eintraege"]}, erg

    def _fall(self, utxos, erwartet):
        for modus, soll in erwartet.items():
            ist, erg = self._werte(utxos, modus)
            for schluessel, (datum, gruen, orange, erfuellt) in soll.items():
                e = ist[schluessel]
                with self.subTest(modus=modus, utxo=schluessel):
                    self.assertEqual((e["datum"], e["sats_gruen"], e["sats_orange"], e["erfuellt"]),
                                     (datum, gruen, orange, erfuellt))
                    self.assertTrue(e["datum_aus_losen"])
                    event = next(v for v in erg["zeitstrahl"]["events"] if v["key"].startswith(e["txid"])
                                 and v["vout"] == e["vout"])
                    self.assertEqual((event["datum"], event["time_ts"]), (e["datum"], e["time_ts"]))
            zeiten = [v["time_ts"] for v in erg["zeitstrahl"]["events"]]
            self.assertEqual(zeiten, sorted(zeiten))

    # Fälle ----------------------------------------------------------------
    def test_t2_beta_an_gamma(self):
        """e463 (grün 45 579 224 vom 03.06.2024, gelb 3 127 089 vom 21.01.2026) → 23 180 508, Gebühr 282."""
        e463 = lambda: self._gemischt("e4", "beta0", [(45_579_224, "03.06.2024"), (3_127_089, "21.01.2026")],  # noqa: E731
                                      "01.02.2026")
        self._tx("c2", [("e4", 0)], [(25_525_523, "beta1"), (23_180_508, "gamma0")])
        utxos = [
            self._utxo("c2", 1, 23_180_508, "05.10.2026", "gamma0", [e463()], ("21.01.2026", "03.06.2024")),
            self._utxo("c2", 0, 25_525_523, "05.10.2026", "beta1", [e463()], ("21.01.2026", "03.06.2024")),
        ]
        for u in utxos:
            u["status"]["block_time"] = _ts("01.10.2026")
        self._fall(utxos, {
            # Ziel ganz grün: früher 21.01.2026 (Stempel über den Baum), jetzt sein Los.
            "juengste": {"c2:1": ("03.06.2024", 23_180_508, 0, True),
                         "c2:0": ("21.01.2026", 22_398_434, 3_127_089, False)},
            "aelteste": {"c2:1": ("03.06.2024", 23_180_508, 0, True),
                         "c2:0": ("03.06.2024", 22_398_434, 3_127_089, False)},
        })

    def test_t5c_delta_an_alpha(self):
        """5aca + 29c9 gemischt → 31 191 582 ganz grün, Wechselgeld 86 407 421 ganz gelb, Gebühr 418."""
        def eingaenge():
            return [
                self._gemischt("5a", "delta0", [(29_468_066, "25.09.2025"), (68_379_304, "08.10.2025")], "10.10.2025"),
                self._gemischt("29", "delta1", [(1_723_934, "30.08.2023"), (18_028_117, "25.11.2025")], "26.11.2025"),
            ]
        self._tx("82", [("5a", 0), ("29", 0)], [(86_407_421, "delta2"), (31_191_582, "alpha0")])
        stempel = ("25.11.2025", "30.08.2023")
        utxos = [
            self._utxo("82", 1, 31_191_582, "01.10.2026", "alpha0", eingaenge(), stempel),
            self._utxo("82", 0, 86_407_421, "01.10.2026", "delta2", eingaenge(), stempel),
        ]
        self._fall(utxos, {
            "juengste": {"82:1": ("25.09.2025", 31_191_582, 0, True),
                         "82:0": ("25.11.2025", 0, 86_407_421, False)},
            # Wechselgeld ganz gelb: früher 30.08.2023 (Frist scheinbar erfüllt), jetzt 08.10.2025.
            "aelteste": {"82:1": ("30.08.2023", 31_191_582, 0, True),
                         "82:0": ("08.10.2025", 0, 86_407_421, False)},
        })

    def test_t3_alpha_an_beta(self):
        """Zwei grüne Alpha-UTXOs (07.07.2023, 01.11.2023) → 30 000 000, Wechselgeld 1 587 893, Gebühr 1 098."""
        def eingaenge():
            return [
                self._eigen("a1", 20_000_000, "07.07.2023", "alpha1", [self._ende("xa1", 20_000_000, "07.07.2023")]),
                self._eigen("a2", 11_588_991, "01.11.2023", "alpha2", [self._ende("xa2", 11_588_991, "01.11.2023")]),
            ]
        self._tx("a1", [("xa1", 0)], [(20_000_000, "alpha1")])
        self._tx("a2", [("xa2", 0)], [(11_588_991, "alpha2")])
        self._tx("65", [("a1", 0), ("a2", 0)], [(30_000_000, "beta0"), (1_587_893, "alpha3")])
        stempel = ("01.11.2023", "07.07.2023")
        utxos = [
            self._utxo("65", 0, 30_000_000, "01.10.2026", "beta0", eingaenge(), stempel),
            self._utxo("65", 1, 1_587_893, "01.10.2026", "alpha3", eingaenge(), stempel),
        ]
        self._fall(utxos, {
            "juengste": {"65:0": ("01.11.2023", 30_000_000, 0, True),
                         "65:1": ("01.11.2023", 1_587_893, 0, True)},
            # Wechselgeld trägt nur das jüngere Los: früher 07.07.2023, jetzt 01.11.2023.
            "aelteste": {"65:0": ("07.07.2023", 30_000_000, 0, True),
                         "65:1": ("01.11.2023", 1_587_893, 0, True)},
        })

    def test_anteilig_behaelt_den_stempel(self):
        """Fremder Eingang im Hop: anteilig, das Datum bleibt beim Ingress-Stempel."""
        a1 = self._eigen("a1", 600, "01.01.2024", "alpha1", [self._ende("xa1", 600, "01.01.2024")])
        self._tx("a1", [("xa1", 0)], [(600, "alpha1")])
        fremder = self._ende("e9", 500, "01.03.2026")
        self._tx("f1", [("a1", 0), ("e9", 0)], [(700, "fremd"), (390, "alpha2")])
        utxos = [self._utxo("f1", 1, 390, "01.10.2026", "alpha2", [a1, fremder], ("01.03.2026", "01.01.2024"))]
        for modus, datum in (("juengste", "01.03.2026"), ("aelteste", "01.01.2024")):
            e = self._werte(utxos, modus)[0]["f1:1"]
            self.assertEqual(e["datum"], datum)
            self.assertFalse(e.get("datum_aus_losen", False))

    def test_lot_zeile_traegt_das_neue_datum(self):
        self._tx("a2", [("xa2", 0)], [(1000, "alpha1")])
        self._tx("b5", [("a2", 0)], [(400, "fremd"), (590, "alpha2")])
        kind = self._eigen("a2", 1000, "01.01.2024", "alpha1", [self._ende("xa2", 1000, "01.01.2024")])
        u = self._utxo("b5", 1, 590, "01.10.2026", "alpha2", [kind], ("01.06.2025", "01.06.2025"))
        zeilen = []
        tax.auswerten([u], 2026, jetzt=JETZT, immutable_cache_dir=self.cache, wallet=self.ctx,
                      on_lot=zeilen.append)
        self.assertEqual(len(zeilen), 1)
        z = zeilen[0]
        self.assertTrue(z["datum_aus_losen"])
        self.assertEqual((z["datum"], z["frist_ende"], z["erfuellt"]), ("01.01.2024", "01.01.2025", True))
        self.assertIsInstance(z["pos"], float)


class TestLosDatenInDerMischung(unittest.TestCase):
    def _ende(self, key, typ, sats, ts, pos=10.0):
        return {"key": key, "typ": typ, "ende": True, "anteil_sats": sats, "time_ts": ts, "pos_output": pos}

    def test_von_bis_ueber_die_lose_mit_anteil(self):
        seg = hn.lot_mischung([self._ende("a", "fremd", 5, 100), self._ende("b", "coinbase", 5, 300),
                               self._ende("c", "fremd", 0, 1)], 50.0, "f")
        self.assertEqual((seg["lot_von_ts"], seg["lot_bis_ts"]), (100, 300))

    def test_undatiert_buendel_oder_luecke_ohne_von_bis(self):
        for typ, ts in (("fremd", None), ("buendel", 200), ("luecke", 200), ("horizont", 200)):
            seg = hn.lot_mischung([self._ende("a", "fremd", 5, 100), self._ende("b", typ, 5, ts, None)], 50.0, "f")
            self.assertNotIn("lot_von_ts", seg, typ)

    def test_flach_meldet_anteilig(self):
        # Fremder Eingang mischt zwei Zeiten anteilig.
        txs = {txid("f0"): tx([("a1", 0), ("e1", 0)], [(700, "fremd1"), (390, "alpha1")])}
        r = netz(baum(390, [knoten("a1", 600, ALT), fremd("e1", 500, JUNG)], vout=1), txs, 1)
        self.assertTrue(r["anteilig"])
        # FIFO-genau: nicht anteilig.
        txs = {txid("f0"): tx([("a1", 0), ("a2", 0)], [(700, "fremd1"), (390, "alpha1")])}
        r = netz(baum(390, [knoten("a1", 600, ALT), knoten("a2", 500, JUNG)], vout=1), txs, 1)
        self.assertFalse(r["anteilig"])
        # Ein einziges Los anteilig verteilt: gleichgültig, nicht anteilig.
        r = netz(baum(390, [fremd("e1", 500, JUNG)], vout=1), {}, 1)
        self.assertFalse(r["anteilig"])


class TestLotZeileImPlot(unittest.TestCase):
    """steuerjahr.js: eine Lot-Zeile mit Los-Datum verschiebt den Punkt; Abschluss zeichnet neu."""

    def test_punkt_rueckt_an_das_los_datum(self):
        import shutil
        import subprocess

        if not shutil.which("node"):
            self.skipTest("node fehlt")
        quelle = (Path(__file__).resolve().parent.parent / "web" / "views" / "steuerjahr.js").read_text(
            encoding="utf-8")

        def funktion(name):
            start = quelle.index(f"function {name}(")
            ende = quelle.index("\nfunction ", start + 10)
            return quelle[start:ende]

        skript = r"""
const aufrufe = [];
const punkt = { classList: { remove() {}, add() {} } };
function tracePunktImPlot() { return punkt; }
function steuerGelbKeySetzen() {}
function steuerPunktFarbe() { return "erfuellt"; }
function steuerLotUiPlanen() {}
function zeichneSteuerScorecards() {}
function zeichneZeitstrahlGeister() { aufrufe.push("geister"); }
function zeichneZeitstrahl(d, o) { aufrufe.push(["neu", Boolean(o && o.fensterBehalten)]); }
let steuerLotUiTimer = null;
const daten = { zeitstrahl: { events: [
  { key: "a:0", pos: 80, datum: "21.01.2026", time_ts: 2 },
  { key: "b:0", pos: 40, datum: "03.06.2024", time_ts: 1 },
] } };
const Zustand = { steuer: daten };
const ZeitstrahlAnsicht = { daten };
""" + funktion("steuerLotZeile") + funktion("steuerLotsAbschluss") + r"""
steuerLotZeile({ key: "b:0", erfuellt: true, sats_gruen: 5 });
steuerLotsAbschluss({});
const ohne = aufrufe.splice(0);
steuerLotZeile({ key: "a:0", erfuellt: true, sats_gruen: 5, datum_aus_losen: true,
                 datum: "03.06.2024", time_ts: 1, pos: 40, neuvermoegen: false });
steuerLotsAbschluss({});
console.log(JSON.stringify({ ohne, mit: aufrufe, ev: daten.zeitstrahl.events[0] }));
"""
        aus = subprocess.run(["node", "-e", skript], capture_output=True, text=True, timeout=60)
        self.assertEqual(aus.returncode, 0, aus.stderr)
        r = _json.loads(aus.stdout)
        self.assertEqual(r["ohne"], ["geister"])
        self.assertEqual(r["mit"], [["neu", True]])
        self.assertEqual((r["ev"]["datum"], r["ev"]["time_ts"], r["ev"]["pos"], r["ev"]["datum_aus_losen"]),
                         ("03.06.2024", 1, 40, True))


class TestWhirlpoolPostmix(TestDatumAusLosen):
    """
    Promo-Lab 2026-10-04 (Höhe 648): Whirlpool-tx0 035d4a2f… und Mix 7296934f….

    tx0: Eingänge grün 086dca…:0 24 421 152 (02.10.2025) und gelb bfd896…:0
    84 287 666 (Los 07.05.2026); Outputs Premix 1 000 250 (vout 0, HS Alpha),
    Koordinator 50 000 (vout 1, extern), Wechselgeld 107 658 088 (vout 2, HS Alpha).
    Mix: 5 Eingänge (Premix an vin 2, sonst fremde Remixer), 5 × 1 000 000;
    Postmix vout 4 an HS Alpha. Vor dem Fix endete die Herkunft des Postmix als
    Bündel an der Output-Zeit des Premix (04.10.2026) → ganz gelb.
    """

    def _premix(self):
        gruen = self._eigen("08", 24_421_152, "02.10.2025", "alpha0",
                            [self._ende("ed", 24_441_152, "02.10.2025")])
        gelb = self._eigen("bf", 84_287_666, "12.06.2026", "alpha4", [
            self._eigen("fb", 105_359_935, "07.05.2026", "alpha5",
                        [self._ende("7a", 105_379_935, "07.05.2026")])])
        return [gruen, gelb]

    def _lab(self, mit_mix_tx=True):
        self._tx("08", [("ed", 1)], [(24_421_152, "alpha0")])
        self._tx("fb", [("7a", 0)], [(105_359_935, "alpha5")])
        self._tx("bf", [("fb", 0)], [(84_287_666, "alpha4"), (21_071_987, "fremd-p")])
        self._tx("35", [("08", 0), ("bf", 0)],
                 [(1_000_250, "alpha1"), (50_000, "koordinator"), (107_658_088, "alpha2")])
        if mit_mix_tx:
            self._tx("72", [("43", 0), ("43", 1), ("35", 0), ("43", 2), ("43", 3)],
                     [(1_000_000, f"remix{i}") for i in range(4)] + [(1_000_000, "alpha3")])
        premix = self._eigen("35", 1_000_250, "03.10.2026", "alpha1", self._premix())
        postmix = self._utxo("72", 4, 1_000_000, "03.10.2026", "alpha3", [premix],
                             ("07.05.2026", "02.10.2025"), tx_class="whirlpool")
        wechsel = self._utxo("35", 2, 107_658_088, "03.10.2026", "alpha2", self._premix(),
                             ("07.05.2026", "02.10.2025"))
        for u in (postmix, wechsel):
            u["status"]["block_time"] = _ts("03.10.2026")
        # Ein alter UTXO wie im Lab, damit die Fristgrenze auf der Achse liegt.
        alt = self._utxo("d0", 0, 1_000, "01.01.2024", "alpha6",
                         [self._ende("dd", 1_000, "01.01.2024")], ("01.01.2024", "01.01.2024"))
        return [postmix, wechsel, alt]

    def test_postmix_gruen_aus_dem_premix_los(self):
        mx, t0 = k("72")[:2], k("35")[:2]
        self._fall(self._lab(), {
            "juengste": {f"{mx}:4": ("02.10.2025", 1_000_000, 0, True),
                         f"{t0}:2": ("07.05.2026", 23_370_422, 84_287_666, False)},
            "aelteste": {f"{mx}:4": ("02.10.2025", 1_000_000, 0, True),
                         f"{t0}:2": ("02.10.2025", 23_370_422, 84_287_666, False)},
        })

    def test_herkunft_laeuft_durch_den_mix(self):
        """Kein Bündel: Premix und seine Vorfahren tragen den Anteil, Abfluss 250 aus dem ältesten Los."""
        self._lab()
        baum = trace_cache.laden(txid("72"), 4, self.cache)["baum"]
        fifo = hn.FifoKontext.aus_cache(self.cache, self.ctx)
        r = hn.flach(baum, k("72", 4), SKALA, fifo=fifo)
        kn = {v["key"]: v for v in r["vorfahren"]}
        self.assertNotIn(f"buendel:{k('72', 4)}", kn)
        self.assertEqual(kn[k("35")]["anteil_sats"], 1_000_000)
        self.assertEqual(kn[k("ed")]["anteil_sats"], 1_000_000)
        self.assertNotIn(k("7a"), kn)
        self.assertFalse(r["anteilig"])

    def test_lot_ring_der_herkunft_wie_im_steuerjahr(self):
        """``GET /api/trace`` → ``lot_fifo``: derselbe Ring (FIFO) für Herkunft und Wallet-Liste."""
        self._lab()
        fifo = hn.FifoKontext.aus_cache(self.cache, self.ctx)
        jetzt = datetime(2026, 10, 4, 12, 0)
        post = hn.lot_ring(trace_cache.laden(txid("72"), 4, self.cache)["baum"], k("72", 4),
                           fifo=fifo, jahre=1, jetzt=jetzt)
        self.assertEqual((post["sats_gruen"], post["sats_orange"], post["sats_grau"]), (1_000_000, 0, 0))
        wechsel = hn.lot_ring(trace_cache.laden(txid("35"), 2, self.cache)["baum"], k("35", 2),
                              fifo=fifo, jahre=1, jetzt=jetzt)
        self.assertEqual((wechsel["sats_gruen"], wechsel["sats_orange"]), (23_370_422, 84_287_666))
        # Anteilig (ohne FIFO-Kontext) wären es beim Wechselgeld andere Zahlen.
        anteilig = hn.lot_ring(trace_cache.laden(txid("35"), 2, self.cache)["baum"], k("35", 2),
                               fifo=None, jahre=1, jetzt=jetzt)
        self.assertNotEqual(anteilig["sats_gruen"], 23_370_422)
        self.assertIsNone(hn.lot_ring({"found": False}, k("35", 2)))

    def test_ohne_mix_tx_anteilig_ueber_eigene_eingaenge(self):
        """Mix-Tx nicht im Cache: anteilig über den Premix — der ist ganz grün, also bleibt der Postmix grün."""
        mx = k("72")[:2]
        ist, _erg = self._werte(self._lab(mit_mix_tx=False), "juengste")
        e = ist[f"{mx}:4"]
        self.assertEqual((e["sats_gruen"], e["sats_orange"]), (1_000_000, 0))


class TestCoinjoinHop(unittest.TestCase):
    """``_fifo_coinjoin_hop``: nur eigene Ein- und Ausgänge, Abfluss vor dem Wechselgeld."""

    WALLET = {"a0": "A", "a1": "A", "a2": "A", "b0": "B"}

    def _ctx(self, txs):
        return hn.FifoKontext(tx=lambda t: txs.get(t), wallet=lambda a: self.WALLET.get(a))

    def _kind(self, name, sats, adresse):
        return ({"type": "internal", "from_utxo": k(name), "amount_sats": sats, "address": adresse},
                k(name), hn.TYP_EIGEN)

    def test_zwei_eigene_outputs_nach_vout_abfluss_zuerst(self):
        # Eigene Eingänge 600 (alt) + 400 (jung); eigene Outputs vout 1 (450) und vout 3 (500);
        # Abfluss 50 (Gebühren) nimmt das älteste Los zuerst.
        txs = {txid("cj"): tx([("f0", 0), ("e0", 0), ("e1", 0)],
                               [(500, "x"), (450, "a1"), (500, "y"), (500, "a2")])}
        kinder = [self._kind("e0", 600, "a0"), self._kind("e1", 400, "a0")]
        eingang = [[L(600, 1, (), ("alt",))], [L(400, 2, (), ("jung",))]]
        v1 = hn._fifo_coinjoin_hop(self._ctx(txs), k("cj", 1), 450, kinder, eingang)
        v3 = hn._fifo_coinjoin_hop(self._ctx(txs), k("cj", 3), 500, kinder, eingang)
        self.assertEqual(marken(v1), [(("alt",), 450)])
        self.assertEqual(marken(v3), [(("alt",), 100), (("jung",), 400)])

    def test_anderes_eigenes_wallet_vor_dem_abfluss(self):
        txs = {txid("cj"): tx([("e0", 0), ("e1", 0)], [(300, "b0"), (650, "a1")])}
        kinder = [self._kind("e0", 500, "a0"), self._kind("e1", 500, "a0")]
        eingang = [[L(500, 1, (), ("alt",))], [L(500, 2, (), ("jung",))]]
        self.assertEqual(marken(hn._fifo_coinjoin_hop(self._ctx(txs), k("cj", 0), 300, kinder, eingang)),
                         [(("alt",), 300)])
        # Abfluss 50 nach dem Output an B, dann der Rest an A.
        self.assertEqual(marken(hn._fifo_coinjoin_hop(self._ctx(txs), k("cj", 1), 650, kinder, eingang)),
                         [(("alt",), 150), (("jung",), 500)])

    def test_eigene_outputs_groesser_als_eigene_eingaenge_fallback(self):
        txs = {txid("cj"): tx([("e0", 0), ("f0", 0)], [(600, "a1"), (400, "x")])}
        kinder = [self._kind("e0", 500, "a0")]
        self.assertIsNone(hn._fifo_coinjoin_hop(self._ctx(txs), k("cj", 0), 600, kinder, [[L(500, 1)]]))
        self.assertFalse(hn._coinjoin_eigen({"tx_class": "whirlpool", "amount_sats": 600},
                                            [kinder[0][0]], k("cj", 0), self._ctx(txs)))

    def test_eingang_nicht_in_der_tx_kein_coinjoin_pfad(self):
        txs = {txid("cj"): tx([("f0", 0)], [(400, "a1")])}
        kind = self._kind("e0", 500, "a0")
        self.assertIsNone(hn._fifo_coinjoin_hop(self._ctx(txs), k("cj", 0), 400, [kind], [[L(500, 1)]]))
        self.assertFalse(hn._coinjoin_eigen({"tx_class": "whirlpool", "amount_sats": 400},
                                            [kind[0]], k("cj", 0), self._ctx(txs)))

    def test_kein_coinjoin_bleibt_normaler_hop(self):
        kind = self._kind("e0", 500, "a0")[0]
        self.assertFalse(hn._coinjoin_eigen({"tx_class": "fan_out_own", "amount_sats": 400},
                                            [kind], k("cj", 0), None))
        self.assertTrue(hn._coinjoin_eigen({"tx_class": "wabisabi", "amount_sats": 400},
                                           [kind], k("cj", 0), None))
