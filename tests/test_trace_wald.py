"""Hop-weiser Wald: kurze UTXOs enden in Runde 1, tiefe Ketten danach."""
from __future__ import annotations

import unittest

from core.trace_wald import wald_schicht
from core.utxo_origin import (
    ORIGIN_PENDING,
    _hat_pending,
    _origin_hat_luecken,
    trace_utxo_origin,
    vertiefe_herkunft_luecken,
)
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    EXTERN_A,
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


def _kette_intern(laenge: int) -> tuple[str, dict, str]:
    """laenge eigene Hops, dann extern. Wurzel ist der jüngste eigene Output."""
    ext = txid("ee")
    chain = {
        ext: core_tx(
            ext,
            [core_vin(txid("c0"), 0)],
            [core_vout(0, EXTERN_A, 1.0)],
            blocktime=1_680_000_000,
        ),
    }
    prev = ext
    wurzel = ext
    for i in range(laenge):
        aktuell = txid(f"d{i:02x}")
        addr = BIP84_CHANGE_0 if i % 2 else BIP84_RECEIVE_0
        chain[aktuell] = core_tx(
            aktuell,
            [core_vin(prev, 0)],
            [core_vout(0, addr, 0.9 - i * 0.01)],
            blocktime=1_690_000_000 + i,
        )
        prev = aktuell
        wurzel = aktuell
    return wurzel, chain, ext


class TestHopBudget(unittest.TestCase):

    def test_budget_eins_haengt_intern_pending(self):
        wurzel, chain, _ext = _kette_intern(2)
        node = trace_utxo_origin(
            make_get_tx(chain), wurzel, 0, EIGENE, hop_budget=1,
        )
        self.assertEqual(node["type"], "utxo")
        intern = node["sources"][0]
        self.assertEqual(intern["type"], "internal")
        self.assertEqual(intern["trace"]["type"], ORIGIN_PENDING)
        self.assertTrue(_hat_pending(node))
        self.assertTrue(_origin_hat_luecken(node))

    def test_zweite_schicht_schliesst_kurze_kette(self):
        wurzel, chain, _ext = _kette_intern(2)
        get_tx = make_get_tx(chain)
        node = trace_utxo_origin(get_tx, wurzel, 0, EIGENE, hop_budget=1)
        node = vertiefe_herkunft_luecken(
            node, get_tx, EIGENE, hop_budget=1,
        )
        self.assertFalse(_hat_pending(node))
        intern = node["sources"][0]
        self.assertEqual(intern["type"], "internal")
        enkel = intern["trace"]["sources"][0]
        self.assertEqual(enkel["type"], "external")
        self.assertEqual(enkel["address"], EXTERN_A)

    def test_ohne_budget_bleibt_voller_tiefenlauf(self):
        node = trace_utxo_origin(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
        )
        self.assertEqual(node["sources"][0]["type"], "external")
        self.assertFalse(_hat_pending(node))


class TestWaldSchicht(unittest.TestCase):

    def test_runde_eins_schliesst_kurze_utxos(self):
        """Zwei direkte Extern-UTXOs fertig, die lange Kette bleibt offen."""
        kurz_a = TXID_WALLET_IN
        kurz_chain = simple_chain()
        lang_wurzel, lang_chain, lang_ext = _kette_intern(4)
        chain = {**kurz_chain, **lang_chain}
        geladen: list[str] = []
        get_tx = make_get_tx(chain, counter=geladen)

        baeume = {
            (kurz_a, 0): None,
            (lang_wurzel, 0): None,
        }
        offen = list(baeume.keys())
        memo: dict = {}
        weiter, fertig = wald_schicht(
            baeume, offen, get_tx, EIGENE, memo=memo,
        )
        self.assertIn((kurz_a, 0), fertig)
        self.assertIn((lang_wurzel, 0), weiter)
        self.assertTrue(_hat_pending(baeume[(lang_wurzel, 0)]))
        # Hop 1 der langen Kette lädt die Wurzel und den direkten Prevout,
        # nicht den externen Ursprung vier Hops weiter.
        self.assertNotIn(lang_ext, geladen)

    def test_spaetere_runden_holen_die_nuss(self):
        wurzel, chain, _ext = _kette_intern(3)
        get_tx = make_get_tx(chain)
        baeume = {(wurzel, 0): None}
        offen = [(wurzel, 0)]
        memo: dict = {}
        runden = 0
        while offen:
            runden += 1
            self.assertLessEqual(runden, 6)
            offen, fertig = wald_schicht(
                baeume, offen, get_tx, EIGENE, memo=memo,
            )
            if fertig:
                break
        self.assertEqual(offen, [])
        self.assertEqual(fertig, [(wurzel, 0)])
        self.assertFalse(_hat_pending(baeume[(wurzel, 0)]))
        # Drei eigene Hops plus die erste Schicht der Wurzel.
        self.assertGreaterEqual(runden, 3)

    def test_gemeinsames_memo_teilt_vorgaenger(self):
        """Zwei Wurzeln, derselbe eigene Prevout — zweiter Hop aus dem Memo."""
        prev = txid("p1")
        a = txid("a1")
        b = txid("b2")
        chain = {
            TXID_EXTERN: core_tx(
                TXID_EXTERN, [], [core_vout(0, EXTERN_A, 2.0)],
            ),
            prev: core_tx(
                prev,
                [core_vin(TXID_EXTERN, 0)],
                [core_vout(0, BIP84_CHANGE_0, 1.9)],
            ),
            a: core_tx(
                a,
                [core_vin(prev, 0)],
                [core_vout(0, BIP84_RECEIVE_0, 0.9)],
            ),
            b: core_tx(
                b,
                [core_vin(prev, 0)],
                [core_vout(0, BIP84_CHANGE_0, 0.9)],
            ),
        }
        get_tx = make_get_tx(chain)
        baeume = {(a, 0): None, (b, 0): None}
        memo: dict = {}
        offen = list(baeume.keys())
        for _ in range(4):
            offen, _fertig = wald_schicht(
                baeume, offen, get_tx, EIGENE, memo=memo,
            )
            if not offen:
                break
        self.assertEqual(offen, [])
        self.assertIn(f"{prev}:0", memo)


if __name__ == "__main__":
    unittest.main()
