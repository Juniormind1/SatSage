"""Regtest-Börsenszenario: synthetische CSVs und Zuordnungsregeln ohne Lab."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "lab" / "regtest" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from boerse_szenario import (  # noqa: E402
    BATCH_SATS,
    EINZEL_SATS,
    baue_kraken_ledger,
    baue_strike_sends,
)
from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, BIP84_CHANGE_0, txid
from verify_boerse_zuordnung import (  # noqa: E402
    empfaenge_aus_bericht,
    pruefe_zuordnungen,
    steuer_kern,
)


class CsvSzenarioTest(unittest.TestCase):
    def test_kraken_hat_eine_auszahlung_ohne_txid(self):
        from core.boerse import kraken
        from core.boerse.modell import Art

        text = baue_kraken_ledger(
            amount_sats=EINZEL_SATS, fee_sats=10_000, buchung_ts=1_719_831_600,
        )
        ergebnis = kraken.parse(text, konto="kraken")
        aus = [b for b in ergebnis.buchungen if b.art is Art.BTC_AUSGANG]
        self.assertEqual(len(aus), 1)
        self.assertIsNone(aus[0].txid)
        self.assertEqual(abs(aus[0].sats), EINZEL_SATS)
        self.assertTrue(aus[0].ref.startswith("LSYN07"))

    def test_strike_hat_zwei_sends_mit_gleicher_txid(self):
        from core.boerse import strike
        from core.boerse.modell import Art

        tid = txid("c2")
        text = baue_strike_sends(
            sends=[
                {"sats": BATCH_SATS[0], "adresse": BIP84_RECEIVE_0, "txid": tid, "ref": "STSYN07-0003"},
                {"sats": BATCH_SATS[1], "adresse": BIP84_RECEIVE_1, "txid": tid, "ref": "STSYN07-0004"},
            ],
            buchung_ts=1_719_831_600,
        )
        ergebnis = strike.parse(text, konto="strike")
        aus = [b for b in ergebnis.buchungen if b.art is Art.BTC_AUSGANG]
        self.assertEqual(len(aus), 2)
        self.assertEqual({b.txid for b in aus}, {tid})
        self.assertEqual(sorted(abs(b.sats) for b in aus), sorted(BATCH_SATS))


class ZuordnungSzenarioTest(unittest.TestCase):
    def _bericht(self) -> dict:
        tid_b = txid("c2")
        tid_e = txid("c3")
        t0 = 1_719_831_600
        return {
            "network": "regtest",
            "buendel": {
                "txid": tid_b,
                "block_time": t0,
                "ausgaben": [
                    {"rolle": "eigen", "index": 0, "address": BIP84_RECEIVE_0,
                     "txid": tid_b, "vout": 0, "sats": BATCH_SATS[0], "block_time": t0},
                    {"rolle": "eigen", "index": 1, "address": BIP84_RECEIVE_1,
                     "txid": tid_b, "vout": 1, "sats": BATCH_SATS[1], "block_time": t0},
                    {"rolle": "fremd", "index": 0, "address": BIP84_CHANGE_0,
                     "txid": tid_b, "vout": 2, "sats": 14_000, "block_time": t0},
                ],
            },
            "einzeln": {
                "rolle": "eigen", "index": 2, "address": BIP84_CHANGE_0,
                "txid": tid_e, "vout": 0, "sats": EINZEL_SATS, "block_time": t0 + 180,
            },
        }

    def test_strike_bestaetigt_kraken_ein_vorschlag(self):
        from core.boerse import kraken, strike, zuordnung

        bericht = self._bericht()
        t_s = int(bericht["buendel"]["block_time"]) - 600
        t_k = int(bericht["einzeln"]["block_time"]) - 600
        strike_csv = baue_strike_sends(
            sends=[
                {"sats": a["sats"], "adresse": a["address"], "txid": a["txid"],
                 "ref": f"STSYN07-000{i + 3}"}
                for i, a in enumerate(
                    a for a in bericht["buendel"]["ausgaben"] if a["rolle"] == "eigen"
                )
            ],
            buchung_ts=t_s,
        )
        kraken_csv = baue_kraken_ledger(
            amount_sats=EINZEL_SATS, fee_sats=10_000, buchung_ts=t_k,
        )
        empfange = empfaenge_aus_bericht(bericht)
        lauf_s = zuordnung.schlage_vor(strike.parse(strike_csv).buchungen, empfange)
        lauf_k = zuordnung.schlage_vor(kraken.parse(kraken_csv).buchungen, empfange)
        self.assertEqual(pruefe_zuordnungen(strike=lauf_s, kraken=lauf_k, bericht=bericht), [])

    def test_steuer_kern_ignoriert_boerse_erklaerung(self):
        alt = {
            "time_ts": 100, "erfuellt": False, "haltedauer_tage": 10,
            "frist_ende": "11.01.2025", "grundlage": "kette",
            "untergrenze": False, "buendel_obergrenze": False,
            "sats_gruen": 0, "sats_orange": 130000, "sats_grau": 0,
            "sats_ohne_datum": 0, "boerse_erklaerung": "Vorschlag",
        }
        neu = dict(alt, boerse_erklaerung="bestätigt")
        herkunft = {"unvollstaendig": False}
        self.assertEqual(steuer_kern(alt, herkunft), steuer_kern(neu, herkunft))
        self.assertNotIn("boerse_erklaerung", steuer_kern(alt))


if __name__ == "__main__":
    unittest.main()
