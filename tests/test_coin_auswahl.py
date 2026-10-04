"""Coin-Auswahl fürs FIFO-Spend: kleinstes Wechselgeld (core/coin_auswahl.py)."""
import itertools
import random
import time
import unittest

from core import coin_auswahl as ca
from core import fee_vorschlag as fv
from httpserver.api.psbt import api_psbt_auswahl


def u(key, wert, gruen=None, *, orange=0, grau=0, zeit=1000, neu=False):
    return {
        "key": key, "value_sats": wert, "sats_gruen": wert if gruen is None else gruen,
        "sats_orange": orange, "sats_grau": grau, "neuvermoegen": neu, "time_ts": zeit,
    }


def waehle(utxos, betrag, *, modus="defensiv", pending=(), rate=None, budget=ca.BUDGET_KNOTEN,
           strategie="wechselgeld"):
    kand = ca.kandidaten(utxos, modus=modus, pending=pending)
    return ca.waehle(kand, betrag=betrag, basis_rate=rate, budget=budget, strategie=strategie)


def keys(erg):
    return sorted(i["key"] for i in erg.get("inputs", []))


class TestKandidaten(unittest.TestCase):

    def test_defensiv_offensiv_gemischt(self):
        utxos = [
            u("aa:0", 50_000),                                     # ganz grün
            u("bb:0", 200_000, 120_000, grau=80_000),              # grün/grau
            u("cc:0", 500_000, 400_000, orange=100_000),           # grün/gelb
            u("dd:0", 9_000, neu=True),                            # Neuvermögen
            {"key": "ee:0", "value_sats": 7_000, "sats_gruen": None},  # ohne Herkunft
            u("ff:0", 19_339_420, 19_339_419),                     # BTC-Rundung: 1 sat
        ]
        de = {k.key: k.beitrag for k in ca.kandidaten(utxos, modus="defensiv")}
        off = {k.key: k.beitrag for k in ca.kandidaten(utxos, modus="offensiv")}
        self.assertEqual(de, {"aa:0": 50_000, "ff:0": 19_339_420})
        # Offensiv auch grün/gelb gemischt (cc:0) — nur der grüne Teil zählt.
        # bb:0 (grün/grau) nie: Grau schließt in beiden Modi aus.
        self.assertEqual(off, {"aa:0": 50_000, "cc:0": 400_000, "ff:0": 19_339_419})

    def test_rein_gelb_grau_neuvermoegen_mempool_nie(self):
        utxos = [
            u("ge:0", 80_000, 0, orange=80_000),                   # rein gelb
            u("gr:0", 80_000, 0, grau=80_000),                     # rein grau
            u("gg:0", 80_000, 79_999, grau=1),                     # grün + 1 sat grau
            u("gy:0", 80_000, 40_000, orange=30_000, grau=10_000), # grün/gelb/grau
            u("nv:0", 80_000, 40_000, orange=40_000, neu=True),    # Neuvermögen
            {"key": "oh:0", "value_sats": 80_000, "sats_gruen": None, "sats_orange": 80_000},
            u("mp:0", 80_000, 40_000, orange=40_000),              # im Mempool
        ]
        for modus in ("defensiv", "offensiv"):
            self.assertEqual(ca.kandidaten(utxos, modus=modus, pending=["mp:0"]), [], modus)

    def test_mempool_und_doppelte_raus(self):
        utxos = [u("AA:0", 50_000), u("aa:0", 50_000), u("bb:0", 60_000),
                 {**u("cc:0", 70_000), "spending_pending": True}]
        k = ca.kandidaten(utxos, modus="defensiv", pending=["bb:0"])
        self.assertEqual([x.key for x in k], ["aa:0"])


class TestWahl(unittest.TestCase):

    def test_exakter_treffer_ohne_wechselgeld(self):
        # 60 000 + 40 178 = 100 000 + 178 (2 Inputs, 1 Output, 1 sat/vB).
        erg = waehle([u("x:0", 60_000), u("y:0", 40_178), u("z:0", 200_000)], 100_000)
        self.assertEqual(erg["status"], "ok")
        self.assertEqual(keys(erg), ["x:0", "y:0"])
        self.assertEqual(erg["wechselgeld_sats"], 0)
        self.assertTrue(erg["ohne_wechselgeld"])
        self.assertEqual(erg["fee_sats"], 178)
        self.assertEqual(erg["vsize"], 178)
        self.assertEqual(erg["staub_in_gebuehr_sats"], 0)
        self.assertEqual(erg["methode"], "bnb")
        self.assertFalse(erg["budget_erschoepft"])

    def test_kleinstes_wechselgeld_gewinnt(self):
        erg = waehle([u("a:0", 300_000), u("b:0", 120_000), u("c:0", 101_000)], 100_000)
        self.assertEqual(keys(erg), ["c:0"])
        self.assertEqual(erg["wechselgeld_sats"], 101_000 - 100_000 - 141)
        self.assertEqual(erg["outputs"], 2)

    def test_staub_geht_in_die_gebuehr(self):
        # Rest 290 sats < 546; Gesamtgebühr 400 ≤ 0,1 % von 1 000 000.
        erg = waehle([u("a:0", 1_000_400)], 1_000_000)
        self.assertTrue(erg["ohne_wechselgeld"])
        self.assertEqual(erg["wechselgeld_sats"], 0)
        self.assertEqual(erg["staub_in_gebuehr_sats"], 290)
        self.assertEqual(erg["fee_sats"], 400)
        self.assertFalse(erg["staub_wechselgeld"])

    def test_staub_deckel_konflikt_wechselgeld_bleibt(self):
        # Betrag 100 000 → Deckel 100 sats; 390 sats Rest als Gebühr wären zu viel.
        erg = waehle([u("a:0", 100_500)], 100_000)
        self.assertEqual(erg["status"], "ok")
        self.assertFalse(erg["ohne_wechselgeld"])
        self.assertTrue(erg["staub_wechselgeld"])
        self.assertEqual(erg["wechselgeld_sats"], 100_500 - 100_000 - 141)   # 359
        self.assertEqual(erg["fee_sats"], 141)

    def test_wechselgeld_unter_relay_staub_ist_keine_loesung(self):
        # Rest 259 < 330 und als Gebühr über dem Deckel → diese Kombination nicht.
        self.assertEqual(waehle([u("a:0", 100_400)], 100_000)["status"], "nicht_gedeckt")
        erg = waehle([u("a:0", 100_400), u("b:0", 150_000)], 100_000)
        self.assertEqual(keys(erg), ["b:0"])

    def test_nicht_gedeckt_und_keine_kandidaten(self):
        erg = waehle([u("a:0", 50_000)], 50_000)          # Gebühr fehlt
        self.assertEqual(erg["status"], "nicht_gedeckt")
        self.assertEqual(erg["gruen_verfuegbar_sats"], 50_000)
        self.assertEqual(waehle([u("a:0", 60)], 10)["status"], "keine_kandidaten")  # unwirtschaftlich
        self.assertEqual(waehle([], 10)["status"], "keine_kandidaten")
        self.assertEqual(waehle([u("a:0", 1000)], 0)["status"], "kein_betrag")

    def test_tie_break_weniger_inputs(self):
        erg = waehle([u("b:0", 50_000), u("c:0", 50_178), u("a:0", 100_110)], 100_000)
        self.assertEqual(keys(erg), ["a:0"])
        self.assertEqual(erg["wechselgeld_sats"], 0)

    def test_tie_break_aelter_dann_key(self):
        erg = waehle([u("b:0", 150_000, zeit=200), u("a:0", 150_000, zeit=100)], 100_000)
        self.assertEqual(keys(erg), ["a:0"])
        erg = waehle([u("b:0", 150_000, zeit=100), u("a:0", 150_000, zeit=200)], 100_000)
        self.assertEqual(keys(erg), ["b:0"])
        erg = waehle([u("bb:0", 150_000), u("aa:1", 150_000)], 100_000)
        self.assertEqual(keys(erg), ["aa:1"])
        # Ohne Blockzeit (unbestätigt) = jüngstes.
        ohne = {**u("a:0", 150_000), "time_ts": None}
        self.assertEqual(keys(waehle([ohne, u("z:0", 150_000, zeit=5)], 100_000)), ["z:0"])

    def test_defensiv_offensiv(self):
        utxos = [
            u("p:0", 50_000),
            u("g:0", 200_000, 120_000, grau=80_000),     # Grau: nie Input
            u("y:0", 500_000, 400_000, orange=100_000),
            u("k:0", 70_000, 60_000, orange=10_000),
        ]
        self.assertEqual(waehle(utxos, 100_000)["status"], "nicht_gedeckt")
        erg = waehle(utxos, 100_000, modus="offensiv")
        # p+k: grün 110 000 ≥ 100 209; Wechselgeld 120 000 − 100 209 = 19 791 (davon 10 000 gelb).
        self.assertEqual(keys(erg), ["k:0", "p:0"])
        self.assertEqual(erg["summe_gruen_sats"], 110_000)
        self.assertEqual(erg["wechselgeld_sats"], 120_000 - 100_000 - 209)
        self.assertEqual(erg["wechselgeld_nicht_gruen_sats"], 10_000)
        # 300 000: nur y deckt (grün 400 000); defensiv nie.
        erg = waehle(utxos, 300_000, modus="offensiv")
        self.assertIn("y:0", keys(erg))
        self.assertEqual(waehle(utxos, 300_000)["status"], "nicht_gedeckt")
        for modus in ("defensiv", "offensiv"):
            for betrag in (10_000, 100_000, 300_000, 500_000):
                self.assertNotIn("g:0", keys(waehle(utxos, betrag, modus=modus)), (modus, betrag))

    def test_grau_nie_input_beide_modi(self):
        utxos = [u("g:0", 1_000_000, 999_000, grau=1_000)]
        for modus in ("defensiv", "offensiv"):
            self.assertEqual(waehle(utxos, 100_000, modus=modus)["status"], "keine_kandidaten", modus)

    def test_t2_halbe_gruene_sats_eines_gemischten_utxo(self):
        # 1 000 000 sats: 400 000 grün, 600 000 gelb. Offensiv die Hälfte des Grüns.
        erg = waehle([u("m:0", 1_000_000, 400_000, orange=600_000)], 200_000, modus="offensiv")
        self.assertEqual(erg["status"], "ok")
        self.assertEqual(keys(erg), ["m:0"])
        self.assertEqual((erg["outputs"], erg["fee_sats"]), (2, 141))
        # Wechselgeld = restliches Grün (200 000 − 141 Gebühr) + alles Gelb, exakt.
        self.assertEqual(erg["wechselgeld_sats"], (200_000 - 141) + 600_000)
        self.assertEqual(erg["wechselgeld_nicht_gruen_sats"], 600_000)
        self.assertEqual(erg["gemischte_inputs"], 1)
        self.assertEqual(erg["summe_inputs_sats"], 200_000 + 141 + erg["wechselgeld_sats"])

    def test_gemischt_nie_ohne_wechselgeld(self):
        # Grün deckt exakt (100 000 + 110): rein grün wäre das ohne Wechselgeld.
        rein = waehle([u("a:0", 100_110)], 100_000, modus="offensiv")
        self.assertTrue(rein["ohne_wechselgeld"])
        gem = waehle([u("a:0", 101_000, 100_141, orange=859)], 100_000, modus="offensiv")
        self.assertFalse(gem["ohne_wechselgeld"])
        self.assertEqual(gem["wechselgeld_sats"], 859)          # genau der gelbe Teil
        self.assertTrue(gem["staub_wechselgeld"] is False)
        # Kleiner gelber Rest: Wechselgeld 359 (< 546) bleibt trotzdem stehen …
        klein = waehle([u("b:0", 100_500, 100_300, orange=200)], 100_000, modus="offensiv")
        self.assertEqual((klein["wechselgeld_sats"], klein["staub_wechselgeld"]), (359, True))
        self.assertGreaterEqual(klein["wechselgeld_sats"], klein["wechselgeld_nicht_gruen_sats"])
        # … unter 330 sats ist es keine Lösung (Gelb dürfte nicht in die Gebühr).
        self.assertEqual(waehle([u("c:0", 100_400, 100_300, orange=100)], 100_000,
                                modus="offensiv")["status"], "nicht_gedeckt")

    def test_gebuehr_nur_aus_gruen(self):
        # Wert reicht dicke, Grün nicht für Betrag + Gebühr.
        self.assertEqual(waehle([u("m:0", 900_000, 100_100, orange=799_900)], 100_000,
                                modus="offensiv")["status"], "nicht_gedeckt")

    def test_offensiv_gruen_muss_betrag_und_gebuehr_decken(self):
        # 100 141 grün nötig; 100 100 grün reicht nicht, obwohl der Wert reicht.
        erg = waehle([u("g:0", 300_000, 100_100, orange=199_900)], 100_000, modus="offensiv")
        self.assertEqual(erg["status"], "nicht_gedeckt")

    def test_mempool_ausschluss(self):
        utxos = [u("a:0", 100_110), u("b:0", 150_000)]
        self.assertEqual(keys(waehle(utxos, 100_000)), ["a:0"])
        self.assertEqual(keys(waehle(utxos, 100_000, pending=["A:0"])), ["b:0"])

    def test_rate_aus_schaetzung_und_deckel(self):
        erg = waehle([u("a:0", 2_000_000)], 1_000_000, rate=5)
        self.assertEqual((erg["sat_vb"], erg["fee_sats"], erg["deckel"]), (5, 705, False))
        erg = waehle([u("a:0", 200_000)], 100_000, rate=5)
        self.assertEqual((erg["sat_vb"], erg["fee_sats"], erg["deckel"]), (1, 141, True))

    def test_budget_fallback_viele_utxos(self):
        rnd = random.Random(7)
        utxos = [u(f"{i:04x}:0", rnd.randint(10_000, 5_000_000), zeit=i) for i in range(300)]
        betrag = 123_456_789
        t0 = time.monotonic()
        voll = waehle(utxos, betrag)
        dauer = time.monotonic() - t0
        self.assertLess(dauer, 10.0)
        knapp = waehle(utxos, betrag, budget=50)
        self.assertTrue(knapp["budget_erschoepft"])
        self.assertEqual(knapp["status"], "ok")
        self.assertIn(knapp["methode"], ("bnb", "greedy"))
        self.assertGreaterEqual(knapp["summe_gruen_sats"], betrag + knapp["fee_sats"])
        self.assertLessEqual(voll["wechselgeld_sats"], knapp["wechselgeld_sats"])

    def test_gier_greift_wenn_budget_vor_der_ersten_loesung_endet(self):
        utxos = [u(f"{i:02x}:0", 10_000 + i, zeit=i) for i in range(60)]
        erg = waehle(utxos, 400_000, budget=5)
        self.assertEqual(erg["status"], "ok")
        self.assertEqual(erg["methode"], "greedy")
        self.assertTrue(erg["budget_erschoepft"])

    def test_gegen_vollsuche(self):
        rnd = random.Random(3)
        for runde in range(40):
            utxos = [u(f"{runde}-{i}:0", rnd.choice([rnd.randint(600, 3_000), rnd.randint(1_000, 400_000)]),
                       zeit=rnd.randint(1, 5)) for i in range(rnd.randint(1, 9))]
            betrag = rnd.randint(1_000, 600_000)
            rate = rnd.choice([None, 1, 3, 20])
            kand = ca.kandidaten(utxos, modus="defensiv")
            nutzbar = [k for k in kand if k.beitrag > 68 * (rate or 1)] or [
                k for k in kand if k.beitrag > 68]
            beste = None
            for n in range(1, len(nutzbar) + 1):
                for c in itertools.combinations(nutzbar, n):
                    l = ca._bewerte(n, sum(k.beitrag for k in c), sum(k.wert for k in c), betrag, rate)
                    if l is not None:
                        r = ca._rang(l, c)
                        beste = r if beste is None or r < beste else beste
            erg = ca.waehle(kand, betrag=betrag, basis_rate=rate)
            if beste is None:
                self.assertNotEqual(erg["status"], "ok", runde)
            else:
                self.assertEqual((erg["wechselgeld_sats"], erg["anzahl_inputs"]), beste[:2], runde)
                self.assertEqual(tuple(sorted(i["key"] for i in erg["inputs"])), beste[3], runde)

    def test_antwort_ohne_schluesselmaterial(self):
        erg = waehle([u("a:0", 150_000)], 100_000)
        self.assertEqual(set(erg["inputs"][0]), {"key", "txid", "vout", "value_sats", "sats_gruen", "time_ts"})
        self.assertEqual((erg["inputs"][0]["txid"], erg["inputs"][0]["vout"]), ("a", 0))


class TestStrategien(unittest.TestCase):

    DREI = [u("a:0", 60_000, zeit=1), u("b:0", 50_000, zeit=2), u("c:0", 200_000, zeit=3)]

    def test_drei_strategien_unterscheiden_sich(self):
        we = waehle(self.DREI, 100_000)
        ge = waehle(self.DREI, 100_000, strategie="gebuehr")
        al = waehle(self.DREI, 100_000, strategie="aelteste")
        self.assertEqual(keys(we), ["a:0", "b:0"])           # 9 791 Wechselgeld
        self.assertEqual(we["wechselgeld_sats"], 110_000 - 100_000 - 209)
        self.assertEqual(keys(ge), ["c:0"])                  # 1 Input, 141 sats
        self.assertEqual((ge["anzahl_inputs"], ge["fee_sats"]), (1, 141))
        self.assertEqual(keys(al), ["a:0", "b:0"])           # älteste zuerst
        self.assertEqual([x["strategie"] for x in (we, ge, al)], ["wechselgeld", "gebuehr", "aelteste"])
        self.assertEqual(ge["methode"], "groesste_zuerst")
        self.assertEqual(al["methode"], "aelteste_zuerst")

    def test_aelteste_nimmt_nichts_wieder_raus(self):
        utxos = [u("alt:0", 20_000, zeit=1), u("mitte:0", 30_000, zeit=2), u("neu:0", 500_000, zeit=3)]
        al = waehle(utxos, 100_000, strategie="aelteste")
        self.assertEqual(keys(al), ["alt:0", "mitte:0", "neu:0"])
        self.assertEqual(keys(waehle(utxos, 100_000, strategie="gebuehr")), ["neu:0"])

    def test_aelteste_tie_break_key_und_ohne_zeit_zuletzt(self):
        utxos = [u("bb:0", 80_000, zeit=5), u("aa:0", 80_000, zeit=5),
                 {**u("00:0", 80_000), "time_ts": None}]
        al = waehle(utxos, 100_000, strategie="aelteste")
        self.assertEqual(keys(al), ["aa:0", "bb:0"])

    def test_gebuehr_tie_break_aelter_dann_key(self):
        utxos = [u("b:0", 150_000, zeit=9), u("a:0", 150_000, zeit=4), u("c:0", 150_000, zeit=4)]
        self.assertEqual(keys(waehle(utxos, 100_000, strategie="gebuehr")), ["a:0"])

    def test_gebuehr_respektiert_staub_und_deckel(self):
        # Größter allein: Rest 290 → ohne Wechselgeld in die Gebühr (Deckel 1 000).
        erg = waehle([u("a:0", 1_000_400), u("b:0", 600_000)], 1_000_000, strategie="gebuehr")
        self.assertEqual(keys(erg), ["a:0"])
        self.assertTrue(erg["ohne_wechselgeld"])
        self.assertEqual(erg["staub_in_gebuehr_sats"], 290)

    def test_unbekannte_strategie_ist_standard(self):
        self.assertEqual(waehle(self.DREI, 100_000, strategie="quatsch")["strategie"], "wechselgeld")

    def test_staub_sammelt_kleine_zusaetzlich(self):
        utxos = [u("c:0", 1_100_000), u("d:0", 5_000), u("e:0", 8_000), u("f:0", 50_000),
                 u("g:0", 150_000),                       # über der Grenze
                 u("y:0", 7_000, 3_000, orange=4_000),    # gelb: nie
                 u("m:0", 6_000)]                          # im Mempool
        basis = waehle(utxos, 1_000_000, pending=["m:0"])
        st = waehle(utxos, 1_000_000, pending=["m:0"], strategie="staub")
        dazu = set(keys(st)) - set(keys(basis))
        self.assertLessEqual(set(keys(basis)), set(keys(st)))
        self.assertTrue(dazu)
        self.assertTrue(all(int(next(i["value_sats"] for i in st["inputs"] if i["key"] == k))
                            < ca.STAUB_AUFRAEUMEN_SATS for k in dazu))
        self.assertNotIn("y:0", keys(st))
        self.assertNotIn("m:0", keys(st))
        self.assertNotIn("g:0", dazu)
        self.assertEqual(st["aufraeumen_anzahl"], len(dazu))
        self.assertEqual(st["aufraeumen_grenze_sats"], 100_000)
        self.assertLessEqual(st["fee_sats"] * 1000, 1_000_000)
        self.assertEqual(st["wechselgeld_sats"],
                         st["summe_inputs_sats"] - 1_000_000 - st["fee_sats"])

    def test_staub_deckel_kleinste_zuerst_teilweise(self):
        # Deckel 300 sats: Basis 141, +d 209, +e 277, +f 345 → f bleibt liegen.
        utxos = [u("c:0", 400_000), u("f:0", 9_000), u("e:0", 8_000), u("d:0", 5_000)]
        st = waehle(utxos, 300_000, strategie="staub")
        self.assertEqual(keys(st), ["c:0", "d:0", "e:0"])
        self.assertEqual((st["aufraeumen_anzahl"], st["aufraeumen_sats"]), (2, 13_000))
        self.assertTrue(st["aufraeumen_begrenzt"])
        self.assertEqual(st["fee_sats"], 277)

    def test_staub_kein_platz_im_deckel(self):
        st = waehle([u("c:0", 300_000), u("d:0", 5_000)], 200_000, strategie="staub")
        self.assertEqual(keys(st), ["c:0"])
        self.assertEqual(st["aufraeumen_anzahl"], 0)
        self.assertTrue(st["aufraeumen_begrenzt"])
        # Basis schon über dem Deckel (100 sats < 141): nichts dazu.
        st = waehle([u("c:0", 300_000), u("d:0", 5_000)], 100_000, strategie="staub")
        self.assertEqual(keys(st), ["c:0"])
        self.assertTrue(st["aufraeumen_begrenzt"])

    def test_staub_rate_faellt_nicht_auf_1(self):
        # 2 sat/vB: Basis 282 ≤ 300; mit d wären es 418 > 300 → Rate fiele auf 1.
        st = waehle([u("c:0", 400_000), u("d:0", 5_000)], 300_000, rate=2, strategie="staub")
        self.assertEqual(keys(st), ["c:0"])
        self.assertEqual(st["sat_vb"], 2)
        self.assertTrue(st["aufraeumen_begrenzt"])

    def test_staub_ohne_kleine_wie_wechselgeld(self):
        st = waehle(self.DREI, 100_000, strategie="staub")
        self.assertEqual(keys(st), keys(waehle(self.DREI, 100_000)))
        self.assertEqual(st["aufraeumen_anzahl"], 0)
        self.assertFalse(st["aufraeumen_begrenzt"])

    def test_alle_strategien_gegen_regeln(self):
        rnd = random.Random(11)
        for runde in range(30):
            utxos = []
            for i in range(rnd.randint(1, 12)):
                wert = rnd.randint(1_000, 300_000)
                gruen = rnd.choice([wert, wert, rnd.randint(0, wert)])
                rest = wert - gruen
                gelb = rnd.randint(0, rest)
                utxos.append(u(f"{runde}-{i}:0", wert, gruen, orange=gelb, grau=rest - gelb,
                               zeit=rnd.randint(1, 9)))
            betrag = rnd.randint(5_000, 500_000)
            for st, modus in itertools.product(ca.STRATEGIEN, ("defensiv", "offensiv")):
                erg = waehle(utxos, betrag, strategie=st, modus=modus, rate=rnd.choice([None, 2]))
                if erg["status"] != "ok":
                    continue
                self.assertGreaterEqual(erg["summe_gruen_sats"], betrag + erg["fee_sats"], (runde, st))
                self.assertEqual(erg["summe_inputs_sats"],
                                 betrag + erg["fee_sats"] + erg["wechselgeld_sats"], (runde, st))
                if not erg["ohne_wechselgeld"]:
                    self.assertGreaterEqual(erg["wechselgeld_sats"], ca.STAUB_HART_SATS)
                # Gelb + grau gehen nie in Gebühr oder Ziel.
                self.assertGreaterEqual(erg["wechselgeld_sats"], erg["wechselgeld_nicht_gruen_sats"], (runde, st))
                if erg["gemischte_inputs"]:
                    self.assertFalse(erg["ohne_wechselgeld"], (runde, st))
                if modus == "defensiv":
                    self.assertEqual(erg["gemischte_inputs"], 0)
                mit_grau = {x["key"] for x in utxos if x["sats_grau"] > 0}
                self.assertFalse(mit_grau & set(keys(erg)), (runde, st, modus))


class TestVorschau(unittest.TestCase):

    def test_quelle(self):
        utxos = [u("a:0", 2_000_000)]
        fb = ca.auswahl_vorschau(utxos, modus="defensiv", betrag=1_000_000, fehler="Insufficient data")
        self.assertEqual((fb["quelle"], fb["sat_vb"], fb["grund"]), ("fallback", 1, "Insufficient data"))
        s = ca.auswahl_vorschau(utxos, modus="defensiv", betrag=1_000_000, feerate_btc_kvb=0.00004)
        self.assertEqual((s["quelle"], s["schaetzung_sat_vb"], s["sat_vb"]), ("schaetzung", 4.0, 5))
        d = ca.auswahl_vorschau(utxos, modus="defensiv", betrag=100_000, feerate_btc_kvb=0.00004)
        self.assertEqual((d["quelle"], d["sat_vb"], d["fee_ohne_deckel"]), ("deckel", 1, 5 * 141))


class _Env:
    def values(self):
        return {}


class _State:
    def env(self):
        return _Env()


class TestApi(unittest.TestCase):

    def setUp(self):
        fv.cache_leeren()
        self.addCleanup(fv.cache_leeren)

    def test_ohne_core_fallback(self):
        erg = api_psbt_auswahl(_State(), {
            "betrag": 100_000, "modus": "defensiv",
            "utxos": [u("a:0", 100_110), u("b:0", 150_000)], "pending": ["a:0"],
        })
        self.assertEqual(erg["status"], "ok")
        self.assertEqual(erg["quelle"], "fallback")
        self.assertEqual(keys(erg), ["b:0"])
        self.assertEqual(erg["modus"], "defensiv")

    def test_unsinn_400(self):
        from server import ApiError
        for koerper in ({"betrag": "x"}, {"betrag": -1}, {"betrag": 0},
                        {"betrag": 5, "utxos": "nein"}, {"betrag": 5, "pending": {}},
                        {"betrag": 5, "utxos": [{}] * 20_001}):
            with self.assertRaises(ApiError, msg=str(koerper)[:60]):
                api_psbt_auswahl(_State(), koerper)

    def test_strategie_parameter(self):
        from server import ApiError
        koerper = {"betrag": 100_000, "utxos": TestStrategien.DREI}
        self.assertEqual(api_psbt_auswahl(_State(), koerper)["strategie"], "wechselgeld")
        erg = api_psbt_auswahl(_State(), {**koerper, "strategie": "gebuehr"})
        self.assertEqual((erg["strategie"], keys(erg)), ("gebuehr", ["c:0"]))
        with self.assertRaises(ApiError):
            api_psbt_auswahl(_State(), {**koerper, "strategie": "quatsch"})

    def test_route_in_server(self):
        from pathlib import Path
        server = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('teile == ["psbt", "auswahl"] and methode == "POST"', server)
        self.assertIn('teile == ["config", "fifo-strategie"] and methode == "PUT"', server)


class _SpeicherEnv:
    def __init__(self, werte=None):
        self.werte, self.gespeichert = dict(werte or {}), 0

    def values(self):
        return dict(self.werte)

    def apply(self, neu):
        self.werte.update(neu)

    def save(self):
        self.gespeichert += 1


class TestEinstellung(unittest.TestCase):

    def test_lesen_und_speichern(self):
        from httpserver.api.config_ui import _fifo_strategie_aus_env, api_save_fifo_strategie
        from server import ApiError

        self.assertEqual(_fifo_strategie_aus_env({}), "wechselgeld")
        self.assertEqual(_fifo_strategie_aus_env({"FIFO_STRATEGIE": " Staub "}), "staub")
        self.assertEqual(_fifo_strategie_aus_env({"FIFO_STRATEGIE": "x"}), "wechselgeld")
        env = _SpeicherEnv()

        class St:
            def env(self):
                return env

        erg = api_save_fifo_strategie(St(), {"fifo_strategie": "aelteste"})
        self.assertEqual(erg, {"saved": True, "fifo_strategie": "aelteste"})
        self.assertEqual((env.werte["FIFO_STRATEGIE"], env.gespeichert), ("aelteste", 1))
        with self.assertRaises(ApiError):
            api_save_fifo_strategie(St(), {"fifo_strategie": "alles"})


if __name__ == "__main__":
    unittest.main()
