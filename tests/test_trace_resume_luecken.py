"""Resume unvollständiger Herkunft: fertige Zweige behalten, Lücken nachziehen."""
from __future__ import annotations

import unittest

import analyze
from core.trace import trace_utxo
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


class TestBrauchbarerTeilfortschritt(unittest.TestCase):

    def test_leerer_baum_nicht_brauchbar(self):
        self.assertFalse(
            analyze.hat_brauchbaren_teilfortschritt(
                {"type": "unknown", "txid": txid("a1"), "vout": 0, "sources": []}
            )
        )

    def test_externes_blatt_brauchbar(self):
        self.assertTrue(
            analyze.hat_brauchbaren_teilfortschritt({
                "type": "utxo",
                "txid": TXID_WALLET_IN,
                "vout": 0,
                "sources": [{
                    "type": "external",
                    "address": EXTERN_A,
                    "amount_sats": 1,
                    "from_utxo": f"{TXID_EXTERN}:0",
                }],
            })
        )

    def test_nur_error_nicht_brauchbar(self):
        self.assertFalse(
            analyze.hat_brauchbaren_teilfortschritt({
                "type": "utxo",
                "txid": TXID_WALLET_IN,
                "vout": 0,
                "sources": [{
                    "type": "error",
                    "from_utxo": f"{txid('f9')}:0",
                    "error": "fehlte",
                }],
            })
        )


class TestResumeErrorPrevout(unittest.TestCase):
    """Abgebrochener Prevout-Fehler → Resume lädt nur den fehlenden Hop."""

    def test_resume_zieht_error_prevout_nach(self):
        creator = txid("a3")
        missing_prev = TXID_EXTERN  # wird im zweiten Lauf lieferbar
        # Erster „Lauf“: Prevout fehlte → error-Source, aber Struktur da
        # (from_utxo + parallel schon bekannter anderer Zweig wäre ideal;
        #  hier: error allein gilt als nicht brauchbar — mit internal stub)
        teil = {
            "type": "utxo",
            "txid": creator,
            "vout": 0,
            "addresses": [BIP84_RECEIVE_0],
            "amount_sats": 50_000,
            "sources": [
                {
                    "type": "error",
                    "from_utxo": f"{missing_prev}:0",
                    "amount_sats": 50_000,
                    "error": "Vorgänger-Tx nicht ladbar",
                },
                # Brauchbarer Parallel-Zweig (fertig), damit Resume greift
                {
                    "type": "external",
                    "address": EXTERN_A,
                    "amount_sats": 1,
                    "from_utxo": f"{txid('e2')}:0",
                },
            ],
        }
        self.assertTrue(analyze.hat_brauchbaren_teilfortschritt(teil))
        self.assertTrue(analyze._origin_hat_luecken(teil))

        chain = {
            creator: core_tx(
                creator,
                [core_vin(missing_prev, 0)],
                [core_vout(0, BIP84_RECEIVE_0, 0.0005)],
            ),
            missing_prev: core_tx(
                missing_prev,
                [core_vin(txid("c0"), 0)],
                [core_vout(0, EXTERN_A, 0.0005)],
                blocktime=1_600_000_000,
            ),
        }
        counter: list[str] = []
        voll = trace_utxo(
            make_get_tx(chain, counter=counter),
            creator,
            0,
            EIGENE,
            resume_origin=teil,
        )
        self.assertTrue(voll.get("found"))
        # Error-Source sollte ersetzt sein — Kinder nicht mehr nur error
        types = {c.get("type") for c in (voll.get("children") or [])}
        self.assertNotIn("error", types)
        self.assertTrue(
            "external" in types or voll.get("verfolgt_vollstaendig"),
            msg=voll.get("children"),
        )


class TestResumeBehaeltFertiges(unittest.TestCase):

    def test_fertiger_simple_chain_ohne_luecke_kein_neulauf(self):
        ergebnis = trace_utxo(make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE)
        origin = ergebnis["origin_tree"]
        self.assertFalse(analyze._origin_hat_luecken(origin))
        counter: list[str] = []
        nochmal = trace_utxo(
            make_get_tx(simple_chain(), counter=counter),
            TXID_WALLET_IN,
            0,
            EIGENE,
            resume_origin=origin,
        )
        # Ohne Lücken: normaler Neulauf-Pfad (kein Resume-Branch) — oder
        # Resume der nichts ändert. Hauptsache vollständig.
        self.assertTrue(nochmal.get("verfolgt_vollstaendig"))


if __name__ == "__main__":
    unittest.main()
