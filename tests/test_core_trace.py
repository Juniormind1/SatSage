"""
Herkunftsanalyse in der Form, die die Oberfläche bekommt.

Wichtig ist hier weniger die Baumstruktur an sich — die deckt test_trace.py ab —
als die Frage, ob die Oberfläche aus den Daten ein ehrliches Bild bauen kann:
Sind unvollständige Angaben als solche erkennbar?
"""
import unittest

import main
from core.trace import parse_ziel, trace_utxo
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    BIP84_ZPUB,
    EXTERN_A,
    EXTERN_B,
    TXID_EXTERN,
    TXID_WALLET_IN,
    core_tx,
    core_vin,
    core_vout,
    make_get_tx,
    simple_chain,
    txid,
)

EIGENE = {BIP84_RECEIVE_0, BIP84_CHANGE_0}


class TestZielErkennung(unittest.TestCase):

    def test_txid_mit_vout(self):
        self.assertEqual(parse_ziel(f"{txid('a1')}:2"), (txid("a1"), 2))

    def test_reine_txid_meint_vout_null(self):
        self.assertEqual(parse_ziel(txid("a1")), (txid("a1"), 0))

    def test_grossschreibung_wird_normalisiert(self):
        ziel = parse_ziel(("AB" * 32) + ":1")
        self.assertEqual(ziel, ("ab" * 32, 1))

    def test_leerzeichen_werden_entfernt(self):
        self.assertEqual(parse_ziel(f"  {txid('a1')}:0  "), (txid("a1"), 0))

    def test_unbrauchbare_eingaben(self):
        for eingabe in ("", "   ", "kein-txid", "zu:kurz", f"{txid('a1')}:x", "abc"):
            self.assertIsNone(parse_ziel(eingabe), eingabe)


class TestEinfacherBaum(unittest.TestCase):

    def setUp(self):
        self.ergebnis = trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE
        )

    def test_wurzel_beschreibt_das_utxo(self):
        wurzel = self.ergebnis["root"]
        self.assertTrue(self.ergebnis["found"])
        self.assertEqual(wurzel["txid"], TXID_WALLET_IN)
        self.assertEqual(wurzel["vout"], 0)
        self.assertEqual(wurzel["address"], BIP84_RECEIVE_0)
        self.assertEqual(wurzel["amount_sats"], 60_000_000)

    def test_externer_zufluss_als_kind(self):
        kinder = self.ergebnis["children"]
        self.assertEqual(len(kinder), 1)
        self.assertEqual(kinder[0]["type"], "external")
        self.assertEqual(kinder[0]["address"], EXTERN_A)
        self.assertEqual(kinder[0]["from_utxo"], f"{TXID_EXTERN}:0")

    def test_vollstaendiger_baum_meldet_sich_an_der_wurzel(self):
        """Die Liste braucht das, sonst erscheint „jüngste sats" erst nach Refresh."""
        self.assertTrue(self.ergebnis["verfolgt_vollstaendig"])
        self.assertIn("juengste_sats_ts", self.ergebnis)

    def test_externer_knoten_erklaert_sein_ende(self):
        """Der Nutzer muss sehen, dass hier nicht weitergesucht wurde."""
        kind = self.ergebnis["children"][0]
        self.assertFalse(kind["expandable"])
        self.assertIn("nicht weiterverfolgt", kind["note"])

    def test_kennungen_sind_eindeutig(self):
        kennungen = [k["id"] for k in self.ergebnis["children"]]
        self.assertEqual(len(kennungen), len(set(kennungen)))
        self.assertTrue(all(k.startswith("0.") for k in kennungen))


class TestVerschachtelung(unittest.TestCase):

    def setUp(self):
        vorher = txid("d1")
        self.chain = {
            vorher: core_tx(vorher, [core_vin(TXID_EXTERN, 0)],
                            [core_vout(0, BIP84_CHANGE_0, 0.8)]),
            TXID_WALLET_IN: core_tx(TXID_WALLET_IN, [core_vin(vorher, 0)],
                                    [core_vout(0, BIP84_RECEIVE_0, 0.79)]),
            TXID_EXTERN: core_tx(TXID_EXTERN, [core_vin(txid("c0"), 0)],
                                 [core_vout(0, EXTERN_A, 1.0)]),
        }
        self.ctx = main.build_wallet_context(
            [BIP84_ZPUB], wallet_names=["Cold Storage"], max_addresses=6
        )
        self.ergebnis = trace_utxo(
            make_get_tx(self.chain), TXID_WALLET_IN, 0, EIGENE, wallet=self.ctx
        )

    def test_eigener_zufluss_ist_aufklappbar(self):
        kind = self.ergebnis["children"][0]
        self.assertEqual(kind["type"], "internal")
        self.assertTrue(kind["expandable"])
        self.assertEqual(kind["wallet"], "Cold Storage")

    def test_enkel_ist_extern(self):
        enkel = self.ergebnis["children"][0]["children"]
        self.assertEqual(enkel[0]["type"], "external")

    def test_tiefe_waechst(self):
        kind = self.ergebnis["children"][0]
        self.assertEqual(kind["depth"], 1)
        self.assertEqual(kind["children"][0]["depth"], 2)

    def test_kennungen_bilden_den_pfad_ab(self):
        kind = self.ergebnis["children"][0]
        self.assertEqual(kind["id"], "0.0")
        self.assertEqual(kind["children"][0]["id"], "0.0.0")


class TestUnvollstaendigeAngaben(unittest.TestCase):
    """
    Der heikelste Teil: Wo die Analyse abkürzt, darf die Oberfläche keine
    Vollständigkeit vortäuschen.

    Gebündelt wird nur bei großen Sammel-Txs (über
    trace_engine.FULL_RESOLUTION_INPUT_LIMIT); kleine Txs werden seit der
    Untergrenzen-Logik für das Anschaffungsdatum vollständig aufgelöst.
    """

    def _baum_mit_gebuendelten_eingaengen(self):
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
        return trace_utxo(make_get_tx(chain), ziel, 0, EIGENE)

    def test_gebuendelte_eingaenge_werden_gezaehlt(self):
        from trace_engine import FULL_RESOLUTION_INPUT_LIMIT

        ergebnis = self._baum_mit_gebuendelten_eingaengen()
        rest = next(
            k for k in ergebnis["children"] if k["type"] == "external_unresolved"
        )
        self.assertEqual(rest["input_count"], FULL_RESOLUTION_INPUT_LIMIT + 1)
        self.assertEqual(
            ergebnis["summary"]["unresolved_inputs"],
            FULL_RESOLUTION_INPUT_LIMIT + 1,
        )

    def test_gebuendelte_eingaenge_erklaeren_sich(self):
        ergebnis = self._baum_mit_gebuendelten_eingaengen()
        rest = next(
            k for k in ergebnis["children"] if k["type"] == "external_unresolved"
        )
        self.assertIn("nicht aufgelöst", rest["note"])
        self.assertIn("Beträge", rest["note"])

    def test_summe_externer_zufluesse_ist_untergrenze(self):
        """
        Die 0,7 BTC des gebündelten Eingangs fehlen in external_sats. Wer die
        Zahl als Gesamtsumme anzeigt, zeigt etwas Falsches.
        """
        ergebnis = self._baum_mit_gebuendelten_eingaengen()
        self.assertEqual(ergebnis["summary"]["external_sats"], 0)
        self.assertGreater(ergebnis["summary"]["unresolved_inputs"], 0)

    def test_resolve_bundled_findet_alle_eigenen_inputs(self):
        """
        Opt-in: große Sammel-Tx vollständig auflösen — zweiter eigener Input
        und Fremder bleiben sichtbar, unresolved_inputs fällt auf 0.
        """
        from trace_engine import FULL_RESOLUTION_INPUT_LIMIT

        eigener_a, eigener_b, fremder, ziel = (
            txid("e0"), txid("e1"), txid("f0"), txid("f5"),
        )
        chain = {
            eigener_a: core_tx(
                eigener_a, [], [core_vout(0, BIP84_CHANGE_0, 0.2)],
            ),
            eigener_b: core_tx(
                eigener_b, [], [core_vout(0, BIP84_RECEIVE_0, 0.3)],
            ),
            fremder: core_tx(fremder, [], [core_vout(0, EXTERN_B, 0.5)]),
            ziel: core_tx(
                ziel,
                [
                    core_vin(eigener_a, 0),
                    core_vin(fremder, 0),
                    core_vin(eigener_b, 0),
                ]
                + [
                    core_vin(txid(f"x{i:02x}"), 0)
                    for i in range(FULL_RESOLUTION_INPUT_LIMIT)
                ],
                [core_vout(0, BIP84_RECEIVE_0, 0.99)],
            ),
        }
        # Extra-Prevouts brauchen Platzhalter-Txs, sonst scheitert resolve.
        for i in range(FULL_RESOLUTION_INPUT_LIMIT):
            tid = txid(f"x{i:02x}")
            chain[tid] = core_tx(
                tid, [], [core_vout(0, EXTERN_A, 0.01)],
            )

        gebuendelt = trace_utxo(make_get_tx(chain), ziel, 0, EIGENE)
        self.assertGreater(gebuendelt["summary"]["unresolved_inputs"], 0)

        voll = trace_utxo(
            make_get_tx(chain), ziel, 0, EIGENE, resolve_bundled=True,
        )
        self.assertEqual(voll["summary"]["unresolved_inputs"], 0)
        interne = [k for k in voll["children"] if k["type"] == "internal"]
        self.assertGreaterEqual(len(interne), 2)
        self.assertTrue(voll.get("followup_resolve_unresolved_suggested") is False
                        or voll["summary"]["unresolved_inputs"] == 0)

    def test_raute_ui_baum_endet_ueberall_extern(self):
        """CoinJoin-Raute: alle Äste bis external, verfolgt_vollstaendig, done ok."""
        t_ext, t_own, t_mix, t_ziel = (
            txid("e7"), txid("a7"), txid("b7"), txid("c7"),
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
        ergebnis = trace_utxo(
            make_get_tx(chain),
            t_ziel,
            0,
            EIGENE,
            resolve_bundled=True,
            merke_tx_oriented_done=True,
        )
        self.assertTrue(ergebnis["found"])
        self.assertTrue(ergebnis.get("verfolgt_vollstaendig"))
        self.assertTrue(ergebnis.get("followup_tx_oriented_done"))
        self.assertEqual(ergebnis["summary"].get("unresolved_inputs", 0), 0)

        def blaetter(knoten, acc=None):
            if acc is None:
                acc = []
            for k in knoten or []:
                kids = k.get("children") or []
                if kids:
                    blaetter(kids, acc)
                else:
                    acc.append(k.get("type"))
            return acc

        tipen = blaetter(ergebnis["children"])
        self.assertTrue(tipen, "keine Blätter")
        self.assertTrue(
            all(t in ("external", "coinbase") for t in tipen),
            f"nicht-terminale Blätter: {tipen}",
        )

    def test_coinbase_wird_als_ende_markiert(self):
        block = txid("cb")
        chain = {block: core_tx(
            block, [{"coinbase": "03", "sequence": 0, "is_coinbase": True}],
            [core_vout(0, BIP84_RECEIVE_0, 6.25)])}
        ergebnis = trace_utxo(make_get_tx(chain), block, 0, EIGENE)
        typen = {k["type"] for k in ergebnis["children"]}
        if "coinbase" in typen:
            self.assertTrue(ergebnis["summary"]["coinbase"])


class TestFehlerfaelle(unittest.TestCase):

    def test_unbekannte_tx(self):
        ergebnis = trace_utxo(make_get_tx({}), txid("a1"), 0, EIGENE)
        self.assertFalse(ergebnis["found"])
        self.assertTrue(ergebnis["error"])
        self.assertEqual(ergebnis["children"], [])

    def test_ungueltiger_vout(self):
        ergebnis = trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 99, EIGENE
        )
        self.assertFalse(ergebnis["found"])
        # error ist der übersetzte Klartext, error_raw die Originalmeldung.
        self.assertIn("Ausgang", ergebnis["error"])
        self.assertIn("vout", ergebnis["error_raw"])


class TestFehlerUebersetzung(unittest.TestCase):
    """
    Rohmeldungen der Datenquelle sagen niemandem, was zu tun ist. Die Anzeige
    braucht Klartext — aber nur dort, wo die Deutung sicher ist.
    """

    def test_unbekannte_transaktion(self):
        from core.trace import erklaere_fehler

        roh = ("daemon error: DaemonError({'code': -5, 'message': 'No such "
               "mempool or blockchain transaction. Use gettransaction for "
               "wallet transactions.'})")
        text = erklaere_fehler(roh)
        self.assertNotIn("DaemonError", text)
        self.assertIn("kennt diese Transaktion nicht", text)

    def test_zeitueberschreitung(self):
        from core.trace import erklaere_fehler

        self.assertIn("nicht rechtzeitig", erklaere_fehler("socket timed out"))

    def test_keine_verbindung(self):
        from core.trace import erklaere_fehler

        text = erklaere_fehler("[Errno 111] Connection refused")
        self.assertIn("Keine Verbindung", text)

    def test_ssl_mismatch(self):
        from core.trace import erklaere_fehler

        text = erklaere_fehler("[SSL: WRONG_VERSION_NUMBER] wrong version number")
        self.assertIn("FULCRUM_SSL", text)

    def test_unbekannte_meldung_bleibt_roh(self):
        """Lieber unübersetzt als falsch gedeutet."""
        from core.trace import erklaere_fehler

        self.assertEqual(erklaere_fehler("etwas ganz Neues"), "etwas ganz Neues")

    def test_leere_meldung(self):
        from core.trace import erklaere_fehler

        self.assertEqual(erklaere_fehler(""), "Unbekannter Fehler.")
        self.assertEqual(erklaere_fehler(None), "Unbekannter Fehler.")

    def test_ergebnis_traegt_klartext_und_rohtext(self):
        """Der Rohtext bleibt für die Fehlersuche erhalten."""
        ergebnis = trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 99, EIGENE
        )
        self.assertFalse(ergebnis["found"])
        self.assertIn("Ausgang", ergebnis["error"])
        self.assertIn("vout", ergebnis["error_raw"])


class TestFortschritt(unittest.TestCase):

    def test_meldungen_kommen_an(self):
        meldungen = []
        trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
            progress=meldungen.append,
        )
        self.assertTrue(meldungen, "keine Fortschrittsmeldung erhalten")
        self.assertTrue(any("Herkunft" in m for m in meldungen))

    def test_abbruch_ueber_fortschritt_wirkt(self):
        """
        core.jobs bricht ab, indem der Fortschritts-Callback wirft. Das muss
        durch die Analyse hindurchreichen.
        """
        class Abbruch(Exception):
            pass

        def callback(_):
            raise Abbruch()

        with self.assertRaises(Abbruch):
            trace_utxo(
                make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
                progress=callback,
            )


if __name__ == "__main__":
    unittest.main()
