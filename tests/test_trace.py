"""
Rückwärts-Walk über Transaktions-Inputs.

Prüft die Herkunftsanalyse gegen erfundene Ketten: Wo endet der Walk, was
zählt als eigener und was als externer Zufluss, und bricht er bei Zyklen und
zu großer Tiefe zuverlässig ab.
"""
import unittest

import analyze
import trace_engine
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    EXTERN_A,
    EXTERN_B,
    TXID_EXTERN,
    TXID_WALLET_IN,
    core_tx,
    core_vin,
    core_vout,
    cyclic_chain,
    esplora_tx,
    esplora_vin,
    esplora_vout,
    make_get_tx,
    simple_chain,
    txid,
)

EIGENE = {BIP84_RECEIVE_0, BIP84_CHANGE_0}


class TestEinfacheKette(unittest.TestCase):
    """Extern → Wallet: der Walk endet beim externen Zufluss."""

    def setUp(self):
        self.chain = simple_chain()
        self.geladen = []
        self.get_tx = make_get_tx(self.chain, counter=self.geladen)

    def trace(self):
        return analyze.trace_utxo_origin(
            self.get_tx, TXID_WALLET_IN, 0, EIGENE
        )

    def test_knoten_beschreibt_das_utxo(self):
        node = self.trace()
        self.assertEqual(node["type"], "utxo")
        self.assertEqual(node["txid"], TXID_WALLET_IN)
        self.assertEqual(node["vout"], 0)
        self.assertEqual(node["addresses"], [BIP84_RECEIVE_0])

    def test_betrag_wird_aus_btc_umgerechnet(self):
        self.assertEqual(self.trace()["amount_sats"], 60_000_000)

    def test_externer_zufluss_wird_als_extern_gefuehrt(self):
        quellen = self.trace()["sources"]
        self.assertEqual(len(quellen), 1)
        self.assertEqual(quellen[0]["type"], "external")
        self.assertEqual(quellen[0]["address"], EXTERN_A)
        self.assertEqual(quellen[0]["from_utxo"], f"{TXID_EXTERN}:0")

    def test_externer_zweig_wird_nicht_weiterverfolgt(self):
        """Hinter einer fremden Adresse endet die Analyse — sonst liefe sie ewig."""
        self.trace()
        self.assertNotIn("external", str(self.geladen))
        self.assertNotIn(txid("c0"), self.geladen)


class TestInterneKette(unittest.TestCase):
    """Wallet → Wallet: der Walk läuft weiter und verschachtelt die Knoten."""

    def setUp(self):
        vorher = txid("d1")
        self.chain = {
            vorher: core_tx(
                vorher,
                [core_vin(TXID_EXTERN, 0)],
                [core_vout(0, BIP84_CHANGE_0, 0.8)],
                blocktime=1_690_000_000,
            ),
            TXID_WALLET_IN: core_tx(
                TXID_WALLET_IN,
                [core_vin(vorher, 0)],
                [core_vout(0, BIP84_RECEIVE_0, 0.79)],
                blocktime=1_700_000_000,
            ),
            TXID_EXTERN: core_tx(
                TXID_EXTERN,
                [core_vin(txid("c0"), 0)],
                [core_vout(0, EXTERN_A, 1.0)],
                blocktime=1_680_000_000,
            ),
        }
        self.vorher = vorher
        self.get_tx = make_get_tx(self.chain)

    def test_eigener_zufluss_wird_verschachtelt(self):
        node = analyze.trace_utxo_origin(self.get_tx, TXID_WALLET_IN, 0, EIGENE)
        quellen = node["sources"]
        self.assertEqual(len(quellen), 1)
        self.assertEqual(quellen[0]["type"], "internal")
        self.assertEqual(quellen[0]["address"], BIP84_CHANGE_0)

        kind = quellen[0]["trace"]
        self.assertEqual(kind["txid"], self.vorher)
        self.assertEqual(kind["addresses"], [BIP84_CHANGE_0])

    def test_der_ursprung_ist_extern(self):
        """Eine Ebene tiefer endet auch die interne Kette bei fremdem Geld."""
        node = analyze.trace_utxo_origin(self.get_tx, TXID_WALLET_IN, 0, EIGENE)
        enkel = node["sources"][0]["trace"]["sources"]
        self.assertEqual(enkel[0]["type"], "external")
        self.assertEqual(enkel[0]["address"], EXTERN_A)


class TestRauteGemeinsamerVorgaenger(unittest.TestCase):
    """
    Mehrere eigene Ausgänge derselben Tx speisen später eine Sammel-Tx.
    Der gemeinsame Vorgänger darf nicht als leerer cycle-Blattknoten enden —
    sonst bleiben CoinJoin-Bäume grün statt rot/lila.
    """

    def test_raute_expandiert_beide_aeste_bis_extern(self):
        # extern → own → mix (2 eigene outs aus demselben own-Input) → ziel
        # spendet beide mix-outs. Ohne Memo würde der 2. Ast own als cycle
        # abschneiden und ein leeres grünes Blatt hinterlassen.
        t_ext, t_own, t_mix, t_ziel = (
            txid("e9"), txid("o9"), txid("m9"), txid("z9"),
        )
        chain = {
            t_ext: core_tx(t_ext, [], [core_vout(0, EXTERN_A, 2.0)]),
            t_own: core_tx(
                t_own,
                [core_vin(t_ext, 0)],
                [core_vout(0, BIP84_RECEIVE_0, 1.9)],
            ),
            t_mix: core_tx(
                t_mix,
                [core_vin(t_own, 0)],
                [
                    core_vout(0, BIP84_RECEIVE_0, 0.9),
                    core_vout(1, BIP84_CHANGE_0, 0.9),
                ],
            ),
            t_ziel: core_tx(
                t_ziel,
                [core_vin(t_mix, 0), core_vin(t_mix, 1)],
                [core_vout(0, BIP84_RECEIVE_0, 1.7)],
            ),
        }
        node = analyze.trace_utxo_origin(
            make_get_tx(chain), t_ziel, 0, EIGENE, alle_eigenen_inputs=True,
        )
        self.assertEqual(node["type"], "utxo")
        interne = [s for s in node["sources"] if s["type"] == "internal"]
        self.assertEqual(len(interne), 2)
        for src in interne:
            kind = src.get("trace") or {}
            self.assertEqual(kind.get("type"), "utxo", src.get("from_utxo"))
            self.assertTrue(kind.get("sources"), src.get("from_utxo"))
            # Kein leerer cycle-Marker auf dem Mix-Ast.
            self.assertNotEqual(kind.get("type"), "cycle")
            # Unterbaum bis external durchreichen.
            stapel = list(kind.get("sources") or [])
            tipen = []
            while stapel:
                s = stapel.pop()
                if s.get("type") == "internal":
                    stapel.extend((s.get("trace") or {}).get("sources") or [])
                else:
                    tipen.append(s.get("type"))
            self.assertTrue(
                tipen and all(t in ("external", "coinbase") for t in tipen),
                f"Ast {src.get('from_utxo')} endet nicht extern: {tipen}",
            )


class TestAbbruchbedingungen(unittest.TestCase):

    def test_zyklus_wird_erkannt(self):
        chain = cyclic_chain()
        a = txid("aa")
        node = analyze.trace_utxo_origin(
            make_get_tx(chain), a, 0, {BIP84_RECEIVE_0}
        )
        self.assertEqual(node["type"], "utxo")
        # Der Rückweg über b landet wieder bei a und muss dort abbrechen.
        self.assertEqual(str(node).count("'cycle'"), 0, "Zyklus lief weiter als erwartet")

    def test_bereits_besuchtes_utxo_bricht_ab(self):
        chain = simple_chain()
        besucht = {f"{TXID_WALLET_IN}:0"}
        node = analyze.trace_utxo_origin(
            make_get_tx(chain), TXID_WALLET_IN, 0, EIGENE, besucht
        )
        self.assertEqual(node["type"], "cycle")
        self.assertEqual(node["sources"], [])

    def test_zu_grosse_tiefe_bricht_ab(self):
        chain = simple_chain()
        node = analyze.trace_utxo_origin(
            make_get_tx(chain),
            TXID_WALLET_IN,
            0,
            EIGENE,
            None,
            analyze.MAX_TRACE_DEPTH + 1,
        )
        self.assertEqual(node["type"], "cycle")

    def test_unbekannte_tx_ergibt_fehlerknoten(self):
        node = analyze.trace_utxo_origin(
            make_get_tx({}), TXID_WALLET_IN, 0, EIGENE
        )
        self.assertEqual(node["type"], "error")
        self.assertIn("error", node)
        self.assertEqual(node["sources"], [])

    def test_ungueltiger_vout_index_ergibt_fehlerknoten(self):
        chain = simple_chain()
        node = analyze.trace_utxo_origin(
            make_get_tx(chain), TXID_WALLET_IN, 99, EIGENE
        )
        self.assertEqual(node["type"], "error")
        self.assertIn("vout", node["error"])


class TestCoinbase(unittest.TestCase):

    def test_coinbase_wird_als_quelle_gefuehrt(self):
        block = txid("cb")
        chain = {
            block: core_tx(
                block,
                [{"coinbase": "03", "sequence": 0, "is_coinbase": True}],
                [core_vout(0, BIP84_RECEIVE_0, 6.25)],
            )
        }
        node = analyze.trace_utxo_origin(make_get_tx(chain), block, 0, EIGENE)
        typen = {q["type"] for q in node["sources"]}
        self.assertTrue(
            typen <= {"coinbase"} or node["type"] == "unknown",
            f"unerwartete Quellen bei Coinbase: {node['sources']}",
        )


class TestMehrereEingaenge(unittest.TestCase):
    """
    Auflösung der Eingänge hängt von der Tx-Größe ab
    (trace_engine.FULL_RESOLUTION_INPUT_LIMIT):

    * Kleine Txs (≤ Limit) werden **vollständig** aufgelöst — erst dann ist
      das jüngste externe Zuflussdatum exakt, das steuerlich als
      Anschaffungsdatum gilt. Ein Abbruch nach dem ersten eigenen Eingang
      könnte einen jüngeren externen Zufluss übersehen.
    * Große Sammel-Txs (> Limit) brechen weiterhin nach dem ersten eigenen
      Eingang ab und zählen den Rest nur (``external_unresolved``); das
      ausgewiesene Datum ist dann eine markierte Untergrenze.

    Historie: Früher wurde *immer* nach dem ersten eigenen Eingang
    abgebrochen. Die Eingänge *davor* wurden dabei schon korrekt
    ausgeliefert — dass das früher nicht geschah (ein `return` sprang über
    die Schlussschleife hinweg), war ein Fehler und kein Teil des
    Kompromisses.
    """

    def _kette(self, reihenfolge, anzahl_extra=0):
        eigener, fremder, ziel = txid("e0"), txid("f0"), txid("f5")
        vins = {
            "eigen": core_vin(eigener, 0),
            "fremd": core_vin(fremder, 0),
        }
        chain = {
            eigener: core_tx(eigener, [], [core_vout(0, BIP84_CHANGE_0, 0.3)]),
            fremder: core_tx(fremder, [], [core_vout(0, EXTERN_B, 0.7)]),
            ziel: core_tx(
                ziel,
                [vins[name] for name in reihenfolge]
                + [core_vin(txid(f"x{i:02x}"), 0) for i in range(anzahl_extra)],
                [core_vout(0, BIP84_RECEIVE_0, 0.99)],
            ),
        }
        return analyze.trace_utxo_origin(make_get_tx(chain), ziel, 0, EIGENE)

    def test_fremd_vor_eigen_zeigt_beide_zufluesse(self):
        """
        Steht ein externer Eingang *vor* dem ersten eigenen, muss er in den
        Quellen auftauchen — mit Adresse und Betrag.

        Hier saß der Fehler: iter_trace_funding_inputs verließ den Generator
        beim ersten eigenen Eingang per `return` und sprang damit über die
        Schlussschleife hinweg, die `external_before_internal` ausliefert. Die
        bereits aufgelösten externen Eingänge fielen still unter den Tisch.

        Betroffen waren nur Transaktionen ohne inline-prevout — also Bitcoin
        Core und Fulcrum, die datenschutzfreundlichen Quellen. Über Esplora
        trat es nie auf, weil dort prevout mitgeliefert wird. Verloren ging
        genau die Angabe, wonach das Werkzeug fragt: woher die Sats kamen.
        """
        node = self._kette(["fremd", "eigen"])
        typen = sorted(q["type"] for q in node["sources"])
        self.assertEqual(typen, ["external", "internal"])

        extern = next(q for q in node["sources"] if q["type"] == "external")
        self.assertEqual(extern["amount_sats"], 70_000_000)
        self.assertEqual(extern["address"], EXTERN_B)

    def test_eigen_vor_fremd_wird_bei_kleiner_tx_aufgeloest(self):
        """Kleine Tx: auch der Eingang nach dem ersten eigenen zählt."""
        node = self._kette(["eigen", "fremd"])
        typen = sorted(q["type"] for q in node["sources"])
        self.assertEqual(typen, ["external", "internal"])

    def test_eigen_vor_fremd_buendelt_bei_grosser_tx(self):
        """Über dem Limit bleibt der alte, sparsame Abbruch bestehen."""
        from trace_engine import FULL_RESOLUTION_INPUT_LIMIT

        node = self._kette(
            ["eigen", "fremd"], anzahl_extra=FULL_RESOLUTION_INPUT_LIMIT
        )
        typen = sorted(q["type"] for q in node["sources"])
        self.assertEqual(typen, ["external_unresolved", "internal"])

        rest = next(q for q in node["sources"] if q["type"] == "external_unresolved")
        # Eigen + Fremd + 20 Füller = 22 Eingänge; nach dem ersten eigenen
        # bleiben 21 unaufgelöst.
        self.assertEqual(rest["input_count"], FULL_RESOLUTION_INPUT_LIMIT + 1)
        self.assertEqual(
            rest["amount_sats"],
            0,
            "Gebündelte Eingänge haben keinen Betrag — die Summe der externen "
            "Zuflüsse ist damit unvollständig und darf nicht als Gesamtsumme "
            "dargestellt werden.",
        )

    def test_gebuendelte_eingaenge_kosten_keine_zusaetzlichen_abrufe(self):
        from trace_engine import FULL_RESOLUTION_INPUT_LIMIT

        eigener, fremder, ziel = txid("e0"), txid("f0"), txid("f5")
        chain = {
            eigener: core_tx(eigener, [], [core_vout(0, BIP84_CHANGE_0, 0.3)]),
            fremder: core_tx(fremder, [], [core_vout(0, EXTERN_B, 0.7)]),
            ziel: core_tx(
                ziel,
                [core_vin(eigener, 0), core_vin(fremder, 0)]
                + [core_vin(txid(f"x{i:02x}"), 0)
                   for i in range(FULL_RESOLUTION_INPUT_LIMIT)],
                [core_vout(0, BIP84_RECEIVE_0, 0.99)],
            ),
        }
        geladen = []
        analyze.trace_utxo_origin(
            make_get_tx(chain, counter=geladen), ziel, 0, EIGENE
        )
        self.assertNotIn(fremder, geladen, "gebündelter Eingang wurde doch geladen")


class TestExternerZeitstempel(unittest.TestCase):
    """
    Externe Kanten tragen die Blockzeit ihrer Vorgänger-Tx — daraus ergibt
    sich das steuerliche Anschaffungsdatum (jüngster externer Zufluss).
    """

    def test_externer_zufluss_traegt_die_blockzeit_seiner_tx(self):
        node = analyze.trace_utxo_origin(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE
        )
        extern = node["sources"][0]
        self.assertEqual(extern["type"], "external")
        self.assertEqual(extern["time_ts"], 1_690_000_000)

    def test_kleine_tx_loest_alle_eingaenge_auf(self):
        """
        Unter dem Limit wird auch der Eingang *nach* dem ersten eigenen noch
        aufgelöst — sonst fehlte ein möglicherweise jüngerer externer Zufluss.
        """
        eigener, fremder, ziel = txid("e0"), txid("f0"), txid("f5")
        chain = {
            eigener: core_tx(
                eigener, [], [core_vout(0, BIP84_CHANGE_0, 0.3)],
                blocktime=1_680_000_000,
            ),
            fremder: core_tx(
                fremder, [], [core_vout(0, EXTERN_B, 0.7)],
                blocktime=1_695_000_000,
            ),
            ziel: core_tx(
                ziel,
                # Eigener Eingang zuerst: früher hätte die Auflösung hier
                # abgebrochen und der externe Eingang fehlte komplett.
                [core_vin(eigener, 0), core_vin(fremder, 0)],
                [core_vout(0, BIP84_RECEIVE_0, 0.99)],
            ),
        }
        geladen = []
        node = analyze.trace_utxo_origin(
            make_get_tx(chain, counter=geladen), ziel, 0, EIGENE
        )
        typen = sorted(q["type"] for q in node["sources"])
        self.assertEqual(typen, ["external", "internal"])
        self.assertIn(fremder, geladen, "kleine Tx muss alle Eingänge auflösen")

        extern = next(q for q in node["sources"] if q["type"] == "external")
        self.assertEqual(extern["time_ts"], 1_695_000_000)

    def test_grosse_tx_bricht_weiterhin_ab(self):
        """
        Über dem Limit bleibt es beim alten Verhalten: erster eigener Eingang
        beendet die Auflösung, der Rest wird gebündelt gezählt.
        """
        from trace_engine import FULL_RESOLUTION_INPUT_LIMIT

        eigener, fremder, ziel = txid("e0"), txid("f0"), txid("f5")
        vins = [core_vin(eigener, 0)]
        vins += [core_vin(txid(f"f{i:02x}"), 0)
                 for i in range(FULL_RESOLUTION_INPUT_LIMIT)]
        chain = {
            eigener: core_tx(eigener, [], [core_vout(0, BIP84_CHANGE_0, 0.3)]),
            fremder: core_tx(fremder, [], [core_vout(0, EXTERN_B, 0.7)]),
            ziel: core_tx(
                ziel, vins, [core_vout(0, BIP84_RECEIVE_0, 0.99)]
            ),
        }
        # Erster Vorgänger ist eigen; einer der fremden folgt danach.
        vins[1] = core_vin(fremder, 0)
        geladen = []
        node = analyze.trace_utxo_origin(
            make_get_tx(chain, counter=geladen), ziel, 0, EIGENE
        )
        typen = {q["type"] for q in node["sources"]}
        self.assertIn("external_unresolved", typen)
        self.assertNotIn(fremder, geladen)


class TestJuengsterExternerZufluss(unittest.TestCase):
    """analyze._youngest_external_ingress gegen ganze Bäume."""

    def _interne_kette(self):
        vorher = txid("d1")
        chain = {
            vorher: core_tx(
                vorher,
                [core_vin(TXID_EXTERN, 0)],
                [core_vout(0, BIP84_CHANGE_0, 0.8)],
                blocktime=1_690_000_000,
            ),
            TXID_WALLET_IN: core_tx(
                TXID_WALLET_IN,
                [core_vin(vorher, 0)],
                [core_vout(0, BIP84_RECEIVE_0, 0.79)],
                blocktime=1_700_000_000,
            ),
            TXID_EXTERN: core_tx(
                TXID_EXTERN,
                [core_vin(txid("c0"), 0)],
                [core_vout(0, EXTERN_A, 1.0)],
                blocktime=1_680_000_000,
            ),
        }
        return analyze.trace_utxo_origin(
            make_get_tx(chain), TXID_WALLET_IN, 0, EIGENE
        )

    def test_interne_uebertraege_behalten_den_externen_ursprung(self):
        """
        Börse → Wallet A → Wallet B: Anschaffungsdatum bleibt der Börsen-
        Zufluss, obwohl der letzte Wallet-Eingang jünger ist.
        """
        ergebnis = analyze._youngest_external_ingress(self._interne_kette())
        self.assertEqual(ergebnis["time_ts"], 1_680_000_000)
        self.assertFalse(ergebnis["untergrenze"])

    def test_unaufloesbare_externe_markieren_untergrenze(self):
        node = {
            "type": "utxo", "sources": [
                {"type": "external_unresolved", "input_count": 3,
                 "amount_sats": 0},
                {"type": "external", "address": EXTERN_A, "amount_sats": 100,
                 "from_utxo": "x:0", "time_ts": 1_680_000_000},
            ],
        }
        ergebnis = analyze._youngest_external_ingress(node)
        self.assertTrue(ergebnis["untergrenze"])
        self.assertEqual(ergebnis["time_ts"], 1_680_000_000)

    def test_juengster_gewinnt_ueber_zeitstempel_hinweg(self):
        node = {
            "type": "utxo", "sources": [
                {"type": "external", "address": EXTERN_A, "amount_sats": 100,
                 "from_utxo": "x:0", "time_ts": 1_600_000_000},
                {"type": "external", "address": EXTERN_B, "amount_sats": 200,
                 "from_utxo": "y:0", "time_ts": 1_700_000_000},
            ],
        }
        ergebnis = analyze._youngest_external_ingress(node)
        self.assertEqual(ergebnis["time_ts"], 1_700_000_000)
        self.assertEqual(ergebnis["amount_sats"], 200)

    def test_coinbase_ist_anschaffung_zur_blockzeit(self):
        block = txid("cb")
        chain = {
            block: core_tx(
                block,
                [{"coinbase": "03", "sequence": 0, "is_coinbase": True}],
                [core_vout(0, BIP84_RECEIVE_0, 6.25)],
                blocktime=1_650_000_000,
            )
        }
        node = analyze.trace_utxo_origin(make_get_tx(chain), block, 0, EIGENE)
        ergebnis = analyze._youngest_external_ingress(node)
        self.assertEqual(ergebnis["time_ts"], 1_650_000_000)


if __name__ == "__main__":
    unittest.main()


class TestInlinePrevoutBlockzeit(unittest.TestCase):
    """
    Esplora liefert den Vorgänger-Output inline in ``vin[].prevout`` — aber
    ohne dessen Blockzeit. Genau die ist das Anschaffungsdatum. Bei kleinen
    Transaktionen wird sie für externe Eingänge nachgeladen; sonst liefe das
    Feature auf dieser Datenquelle stillschweigend ins Leere.
    """

    ZEIT_EXTERN = 1_584_262_800   # 15.03.2020
    ZEIT_WALLET = 1_759_312_800   # 01.10.2025

    def kette(self, eingaenge):
        """Wallet-Tx mit *eingaenge* Inline-Vins, dazu deren Vorgänger-Txs."""
        vins, chain = [], {}
        for index in range(eingaenge):
            vorgaenger = txid(f"e{index:02d}")
            chain[vorgaenger] = esplora_tx(
                vorgaenger,
                [],
                [esplora_vout(EXTERN_A, 10_000)],
                block_time=self.ZEIT_EXTERN + index,
            )
            vins.append(esplora_vin(vorgaenger, 0, EXTERN_A, 10_000))
        chain[TXID_WALLET_IN] = esplora_tx(
            TXID_WALLET_IN,
            vins,
            [esplora_vout(BIP84_RECEIVE_0, 10_000 * eingaenge)],
            block_time=self.ZEIT_WALLET,
        )
        return chain

    def trace(self, eingaenge):
        self.geladen = []
        get_tx = make_get_tx(self.kette(eingaenge), counter=self.geladen)
        return analyze.trace_utxo_origin(get_tx, TXID_WALLET_IN, 0, EIGENE)

    def test_kleine_tx_bekommt_die_blockzeit_nachgeladen(self):
        quellen = self.trace(2)["sources"]
        self.assertEqual([q["type"] for q in quellen], ["external", "external"])
        self.assertEqual(
            [q["time_ts"] for q in quellen],
            [self.ZEIT_EXTERN, self.ZEIT_EXTERN + 1],
        )

    def test_anschaffungsdatum_ist_der_juengste_externe_zufluss(self):
        external = analyze._youngest_external_ingress(self.trace(3))
        self.assertIsNotNone(external)
        self.assertEqual(external["time_ts"], self.ZEIT_EXTERN + 2)
        self.assertFalse(external["untergrenze"])

    def test_grosse_sammel_tx_laedt_nicht_nach(self):
        """
        Über dem Auflösungslimit wäre ein get_tx je Eingang zu teuer — und
        das Datum bliebe ohnehin unsicher.
        """
        eingaenge = trace_engine.FULL_RESOLUTION_INPUT_LIMIT + 1
        quellen = self.trace(eingaenge)["sources"]
        self.assertTrue(all(q["time_ts"] is None for q in quellen))
        # Keine einzige Vorgänger-Tx wurde angefasst. (Die Wallet-Tx selbst
        # holen trace_utxo_origin und iter_trace_funding_inputs je einmal;
        # in der Anwendung ist get_tx gecacht.)
        self.assertEqual(set(self.geladen), {TXID_WALLET_IN})

    def test_ohne_datierten_zufluss_kein_anschaffungsdatum(self):
        """
        Lieber gar keine Angabe als eine erfundene: Die Steuerschicht fällt
        dann auf den Wallet-Eingang zurück und weist das aus.
        """
        eingaenge = trace_engine.FULL_RESOLUTION_INPUT_LIMIT + 1
        self.assertIsNone(analyze._youngest_external_ingress(self.trace(eingaenge)))

    def test_interne_eingaenge_kosten_keinen_zusatzabruf(self):
        """
        Für interne Eingänge ist die Blockzeit des Vorgängers belanglos —
        der Zweig wird ohnehin weiterverfolgt.
        """
        vorgaenger = txid("i1")
        chain = {
            vorgaenger: esplora_tx(
                vorgaenger, [], [esplora_vout(BIP84_CHANGE_0, 50_000)],
                block_time=self.ZEIT_EXTERN,
            ),
            TXID_WALLET_IN: esplora_tx(
                TXID_WALLET_IN,
                [esplora_vin(vorgaenger, 0, BIP84_CHANGE_0, 50_000)],
                [esplora_vout(BIP84_RECEIVE_0, 50_000)],
                block_time=self.ZEIT_WALLET,
            ),
        }
        geladen = []
        analyze.trace_utxo_origin(
            make_get_tx(chain, counter=geladen), TXID_WALLET_IN, 0, EIGENE
        )
        # Zwei Abrufe je Tx — einer aus trace_utxo_origin, einer aus
        # iter_trace_funding_inputs. Ein Blockzeit-Nachschlag für den
        # internen Eingang wäre der dritte.
        self.assertEqual(geladen.count(vorgaenger), 2)
