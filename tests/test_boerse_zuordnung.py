"""Zuordnung Auszahlung ↔ Empfang: nur Erklärung, ohne Datums- oder Farbwirkung."""
from __future__ import annotations

import unittest

from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, txid
from core.boerse.modell import Art, Buchung, Zuordnung
from core.boerse.zuordnung import (
    FENSTER_NACH_S,
    KettenEmpfang,
    mergen,
    nach_outpoint,
    schlage_vor,
    setze_status,
)

T0 = 1_700_000_000
KETTE = txid("c1")
ANDERER = txid("c2")
DRITTER = txid("c3")


def _aus(
    ref: str,
    sats: int = -500_000,
    *,
    txid_wert: str | None = None,
    adresse: str | None = None,
    zeit: int = T0,
    lightning: bool = False,
    gebuehr: int = 10_000,
    konto: str = "strike",
) -> Buchung:
    return Buchung(
        konto=konto,
        ref=ref,
        gruppe=None,
        zeit_ts=zeit,
        zeit_zone_belegt=True,
        art=Art.BTC_AUSGANG,
        sats=sats,
        gebuehr_sats=gebuehr,
        fiat=None,
        fiat_gebuehr=None,
        waehrung=None,
        kurs=None,
        txid=txid_wert,
        adresse=adresse,
        lightning=lightning,
        roh_typ="send",
        roh_subtyp=None,
        datei="x",
        zeile=2,
    )


def _empf(
    tx, vout=0, sats=500_000, zeit=T0 + 600, adresse=BIP84_RECEIVE_0, eigene=False
) -> KettenEmpfang:
    return KettenEmpfang(
        txid=tx, vout=vout, sats=sats, zeit_ts=zeit, adresse=adresse, eigene_eingaenge=eigene
    )


class TxidExaktTest(unittest.TestCase):
    def test_eine_tx_ein_output_wird_bestaetigt(self):
        lauf = schlage_vor(
            [_aus("STSYN-1", txid_wert=KETTE)],
            [_empf(KETTE)],
        )
        self.assertEqual(lauf.luecken, ())
        self.assertEqual(lauf.quarantaene, ())
        z = lauf.zuordnungen[0]
        self.assertEqual(z.status, "bestaetigt")
        self.assertEqual(z.methode, "txid_exakt")
        self.assertEqual(z.txid, KETTE)
        self.assertEqual(z.vout, 0)
        self.assertEqual(z.sats_onchain, 500_000)

    def test_zwei_eigene_outputs_nicht_automatisch(self):
        lauf = schlage_vor(
            [_aus("STSYN-1", txid_wert=KETTE)],
            [_empf(KETTE, 0, 500_000), _empf(KETTE, 1, 200_000, adresse=BIP84_RECEIVE_1)],
        )
        self.assertEqual(lauf.zuordnungen, ())
        self.assertEqual(lauf.quarantaene[0]["grund"], "zwei eigene Outputs")

    def test_batch_mit_fremden_outputs_eindeutig(self):
        fremd = _empf(KETTE, 2, 100_000, adresse=None)
        # fremd is still "own" if in empfange list — batch case means foreign
        # outputs are simply not in `empfange`. Two own outputs + implied foreign.
        lauf = schlage_vor(
            [
                _aus("STSYN-A", -500_000, txid_wert=KETTE),
                _aus("STSYN-B", -200_000, txid_wert=KETTE),
            ],
            [_empf(KETTE, 0, 500_000), _empf(KETTE, 1, 200_000, adresse=BIP84_RECEIVE_1)],
        )
        self.assertEqual(len(lauf.zuordnungen), 2)
        self.assertTrue(all(z.status == "bestaetigt" and z.methode == "txid_exakt" for z in lauf.zuordnungen))
        refs = {z.auszahlung_ref: z.vout for z in lauf.zuordnungen}
        self.assertEqual(refs["STSYN-A"], 0)
        self.assertEqual(refs["STSYN-B"], 1)
        self.assertEqual(lauf.quarantaene, ())
        del fremd

    def test_eigene_eingaenge_kein_auto(self):
        lauf = schlage_vor(
            [_aus("STSYN-1", txid_wert=KETTE)],
            [_empf(KETTE, eigene=True)],
        )
        self.assertEqual(lauf.zuordnungen, ())
        self.assertEqual(lauf.quarantaene[0]["grund"], "eigene Eingänge in der Tx")

    def test_gebuehr_nicht_im_output(self):
        # 500_000 outbound + 10_000 fee; chain output is 500_000, not 510_000.
        lauf = schlage_vor(
            [_aus("K-1", -500_000, txid_wert=KETTE, gebuehr=10_000, konto="kraken")],
            [_empf(KETTE, sats=500_000)],
        )
        self.assertEqual(lauf.zuordnungen[0].status, "bestaetigt")
        lauf_falsch = schlage_vor(
            [_aus("K-1", -500_000, txid_wert=ANDERER, gebuehr=10_000, konto="kraken")],
            [_empf(ANDERER, sats=510_000)],
        )
        self.assertEqual(lauf_falsch.zuordnungen, ())


class AdresseUndZeitTest(unittest.TestCase):
    def test_betrag_zeit_eindeutig_ist_vorschlag(self):
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, konto="kraken")],
            [_empf(KETTE, zeit=T0 + 3600)],
        )
        z = lauf.zuordnungen[0]
        self.assertEqual(z.status, "vorschlag")
        self.assertEqual(z.methode, "betrag_zeit")
        self.assertEqual(z.txid, KETTE)

    def test_zwei_kandidaten_quarantaene(self):
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, konto="kraken")],
            [_empf(KETTE, zeit=T0 + 10), _empf(ANDERER, zeit=T0 + 20)],
        )
        self.assertEqual(lauf.zuordnungen, ())
        self.assertEqual(lauf.quarantaene[0]["grund"], "mehrere Kandidaten")

    def test_ausserhalb_des_fensters_luecke(self):
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, konto="kraken")],
            [_empf(KETTE, zeit=T0 + FENSTER_NACH_S + 1)],
        )
        self.assertEqual(lauf.zuordnungen, ())
        self.assertEqual(lauf.luecken, ("LSYN-1",))

    def test_adresse_im_fenster_ist_vorschlag(self):
        lauf = schlage_vor(
            [_aus("CB-1", -500_000, adresse=BIP84_RECEIVE_0, konto="coinbase")],
            [_empf(KETTE, adresse=BIP84_RECEIVE_0, zeit=T0 + 100)],
        )
        z = lauf.zuordnungen[0]
        self.assertEqual(z.status, "vorschlag")
        self.assertEqual(z.methode, "adresse")

    def test_lightning_kein_hop(self):
        lauf = schlage_vor(
            [_aus("STSYN-LN", -50_000, lightning=True, txid_wert=txid("ab"))],
            [_empf(txid("ab"), sats=50_000)],
        )
        self.assertEqual(lauf.zuordnungen, ())
        self.assertEqual(lauf.kein_hop, ("STSYN-LN",))
        self.assertEqual(lauf.luecken, ())


class EntscheidungTest(unittest.TestCase):
    def test_bestaetigt_bleibt_erhalten(self):
        alt = Zuordnung("kraken", "LSYN-1", KETTE, 0, 500_000, "betrag_zeit", "bestaetigt", 1)
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, konto="kraken")],
            [_empf(ANDERER, zeit=T0 + 10)],
            bestehend=(alt,),
        )
        self.assertEqual(len(lauf.zuordnungen), 1)
        self.assertEqual(lauf.zuordnungen[0].txid, KETTE)
        self.assertEqual(lauf.zuordnungen[0].status, "bestaetigt")

    def test_setze_status_bestaetigen_und_ablehnen(self):
        lauf = schlage_vor(
            [_aus("LSYN-1", -500_000, konto="kraken")],
            [_empf(KETTE, zeit=T0 + 10)],
        )
        neu = setze_status(
            lauf.zuordnungen, konto="kraken", auszahlung_ref="LSYN-1",
            status="bestaetigt", bestaetigt_ts=T0 + 20,
        )
        self.assertEqual(neu[0].status, "bestaetigt")
        self.assertEqual(neu[0].methode, "betrag_zeit")
        self.assertEqual(neu[0].bestaetigt_ts, T0 + 20)
        ab = setze_status(
            neu, konto="kraken", auszahlung_ref="LSYN-1",
            status="abgelehnt", bestaetigt_ts=None,
        )
        self.assertEqual(ab[0].status, "abgelehnt")
        self.assertIsNone(ab[0].bestaetigt_ts)
        self.assertNotIn(f"{KETTE}:0", nach_outpoint(ab))

    def test_mergen_ersetzt_nur_vorschlaege(self):
        fest = Zuordnung("kraken", "A", KETTE, 0, 1, "txid_exakt", "bestaetigt", 1)
        alt = Zuordnung("kraken", "B", ANDERER, 0, 1, "betrag_zeit", "vorschlag", None)
        lauf = schlage_vor(
            [_aus("A", -1, konto="kraken"), _aus("B", -500_000, konto="kraken")],
            [_empf(KETTE, sats=1), _empf(DRITTER, sats=500_000, zeit=T0 + 5)],
            bestehend=(fest, alt),
        )
        gem = mergen((fest, alt), lauf)
        refs = {z.auszahlung_ref: z for z in gem}
        self.assertEqual(refs["A"].status, "bestaetigt")
        self.assertEqual(refs["B"].txid, DRITTER)


if __name__ == "__main__":
    unittest.main()


class SpeicherUndApiTest(unittest.TestCase):
    def test_aktualisiere_aus_utxo_cache(self):
        import json
        import tempfile
        from pathlib import Path
        from core.boerse import speicher
        from core.boerse.zuordnung import aktualisiere_zuordnungen, sammeln_empfaenge
        from core.boerse.modell import ParseErgebnis

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ex = Path(tmp.name) / "ex"
        utxo_dir = Path(tmp.name) / "utxo"
        ex.mkdir(); utxo_dir.mkdir()
        buchung = _aus("STSYN-1", -500_000, txid_wert=KETTE, konto="strike")
        speicher.importiere_ergebnis(
            ParseErgebnis((buchung,), (), "statement-eur", "d1"),
            name="Strike", slug="strike", cache_dir=ex,
        )
        (utxo_dir / "wallet.json").write_text(json.dumps({
            "utxos": [{
                "txid": KETTE, "vout": 0, "value": 500_000,
                "address": BIP84_RECEIVE_0,
                "status": {"block_time": T0 + 600},
            }]
        }), encoding="utf-8")
        emp = sammeln_empfaenge(utxo_dir)
        self.assertEqual(len(emp), 1)
        self.assertEqual(emp[0].sats, 500_000)
        bericht = aktualisiere_zuordnungen("strike", ex, utxo_dir)
        self.assertEqual(len(bericht["zuordnungen"]), 1)
        self.assertEqual(bericht["zuordnungen"][0]["status"], "bestaetigt")
        self.assertEqual(bericht["zuordnungen"][0]["methode"], "txid_exakt")

    def test_tax_eintrag_bleibt_in_datum_und_grundlage_unveraendert(self):
        from datetime import datetime, timezone
        from core.tax import Eingang, GRUNDLAGE_OUTPUT
        e = Eingang(
            txid=KETTE, vout=0, address=BIP84_RECEIVE_0, wallet="w",
            value_sats=500_000,
            zeitpunkt=datetime.fromtimestamp(T0, timezone.utc).replace(tzinfo=None),
            frist_ende=None, erfuellt=False, haltedauer_tage=10,
            grundlage=GRUNDLAGE_OUTPUT,
        )
        d = e.as_dict()
        self.assertEqual(d["grundlage"], GRUNDLAGE_OUTPUT)
        self.assertEqual(d["grundlage_label"], e.grundlage_label)
        self.assertEqual(d["haltedauer_tage"], 10)
        self.assertIn("boerse_erklaerung", d)
