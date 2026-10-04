"""Unsignierte PSBT fürs FIFO-Spend: Bau, Wechselgeld, RBF/Locktime, Staub, Server-Prüfung.

Schlüssel: fester Test-Seed nur in diesem Test (Signier-Probe). Das Produkt
sieht ausschließlich den öffentlichen Konto-XPUB.
"""
from __future__ import annotations

import base64
import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from embit import script as escript
from embit.bip32 import HDKey
from embit.networks import NETWORKS
from embit.psbt import PSBT
from embit.transaction import Transaction, TransactionInput, TransactionOutput

from core import psbt_bau as pb
from core.coin_auswahl import FesteRate, Groessen, kandidaten, waehle

NET = NETWORKS["main"]
ROOT = HDKey.from_seed(bytes(range(32)), version=NET["xprv"])
KONTO_PRV = ROOT.derive("m/84h/0h/0h")
XPUB = KONTO_PRV.to_public().to_string()
FP_ROOT = ROOT.my_fingerprint.hex()
HD = HDKey.from_string(XPUB)
ZIEL = escript.p2wpkh(HDKey.from_seed(b"\x07" * 32).key).address(NET)
ZIEL_TR = escript.p2tr(HDKey.from_seed(b"\x08" * 32).key).address(NET)
HOEHE = 850_000


def _adresse(change, index, typ="segwit"):
    return pb.skript_fuer(HD.derive([change, index]).key, typ).address(NET)


def _funding(change, index, wert, typ="segwit", nr=0, politik=None):
    """Vorgänger-Tx mit einem Output an change/index; liefert (txid, roh)."""
    spk = (politik.ableiten(change, index).spk if politik is not None
           else pb.skript_fuer(HD.derive([change, index]).key, typ))
    tx = Transaction(vin=[TransactionInput(bytes([nr + 1]) * 32, nr)],
                     vout=[TransactionOutput(wert, spk)])
    return tx.txid().hex(), tx.serialize()


class Lab:
    """Kleines Wallet: UTXOs mit Lot-Anteilen + Roh-Tx-Quelle."""

    def __init__(self, typ="segwit", politik=None):
        self.typ = typ
        self.politik = politik
        self.utxos: list[dict] = []
        self.roh: dict[str, bytes] = {}

    def utxo(self, change, index, wert, *, gruen=None, gelb=0, grau=0, zeit=1000,
             pending=False, bestaetigt=True):
        txid, roh = _funding(change, index, wert, self.typ, nr=len(self.utxos), politik=self.politik)
        self.roh[txid] = roh
        adresse = (self.politik.ableiten(change, index).spk.address(NET) if self.politik is not None
                   else _adresse(change, index, self.typ))
        self.utxos.append({
            "key": f"{txid}:0", "txid": txid, "vout": 0, "value_sats": wert,
            "address": adresse,
            "sats_gruen": wert - gelb - grau if gruen is None else gruen,
            "sats_orange": gelb, "sats_grau": grau, "neuvermoegen": False,
            "time_ts": zeit, "spending_pending": pending, "bestaetigt": bestaetigt,
        })
        return f"{txid}:0"

    def erzeuge(self, betrag, *, milli=2000, modus="defensiv", strategie="wechselgeld",
                ziel=ZIEL, herkunft=None, bekannt=(), hat_history=None, hoehe=HOEHE,
                nur=None, ohne_roh=False):
        return pb.erzeuge(
            xpub=XPUB, typ=self.typ, herkunft=herkunft or pb.herkunft_fuer(XPUB),
            netz=NET, max_index=100, utxos=self.utxos, pending=(), modus=modus,
            strategie=strategie, betrag=betrag, fee_milli=milli, ziel_adresse=ziel,
            ziel_status="fremd", bekannte_adressen=bekannt, hat_history=hat_history,
            roh_tx_holen=None if ohne_roh else self.roh.get, hoehe=hoehe,
            nur_inputs=nur, rng=random.Random(1), multisig=self.politik,
        )


def _psbt(erg) -> PSBT:
    return PSBT.parse(base64.b64decode(erg["psbt_base64"]))


class TestBausteine(unittest.TestCase):
    def test_fee_text(self):
        self.assertEqual(pb.fee_text_zu_milli("2,5"), 2500)
        self.assertEqual(pb.fee_text_zu_milli("2.125 sat/vB"), 2125)
        self.assertEqual(pb.fee_text_zu_milli(3), 3000)
        self.assertEqual(pb.fee_text_zu_milli(1.5), 1500)
        for falsch in ("", "0", "1.2345", "abc", "-1", "10000.001", True, None):
            self.assertIsNone(pb.fee_text_zu_milli(falsch), falsch)

    def test_herkunft_ohne_und_mit_origin(self):
        ohne = pb.herkunft_fuer(XPUB)
        self.assertEqual((ohne.quelle, ohne.pfad), ("xpub", ()))
        self.assertEqual(ohne.fingerprint, HD.my_fingerprint)
        self.assertFalse(pb.global_xpub_passt(HD, ohne))
        mit = pb.herkunft_fuer(XPUB, f"wpkh([{FP_ROOT}/84h/0h/0h]{XPUB}/<0;1>/*)")
        self.assertEqual(mit.quelle, "deskriptor")
        self.assertEqual(mit.fingerprint_hex, FP_ROOT)
        self.assertEqual(mit.pfad_text(1, 4), "m/84h/0h/0h/1/4")
        self.assertTrue(pb.global_xpub_passt(HD, mit))
        # Falsche Tiefe: kein GLOBAL_XPUB (Electrum lehnt das ab).
        kurz = pb.Herkunft(bytes.fromhex(FP_ROOT), (0x80000054,), "deskriptor")
        self.assertFalse(pb.global_xpub_passt(HD, kurz))

    def test_vsize_und_output_groessen(self):
        p2wpkh = escript.p2wpkh(HD.key).data
        p2tr = escript.p2tr(HD.key).data
        self.assertEqual(pb.output_vbytes(p2wpkh), 31)
        self.assertEqual(pb.output_vbytes(p2tr), 43)
        self.assertEqual(pb.vsize_tx(["segwit"], [p2wpkh]), 110)
        self.assertEqual(pb.vsize_tx(["segwit"] * 4, [p2wpkh]), 314)
        self.assertEqual(pb.vsize_tx(["legacy"], [p2wpkh, p2wpkh]), 220)
        # Gleiche Formel wie die Auswahl-Schätzung bei P2WPKH.
        self.assertEqual(Groessen().vsize(3, 2), pb.vsize_tx(["segwit"] * 3, [p2wpkh] * 2))

    def test_roh_tx_pruefung(self):
        txid, roh = _funding(0, 1, 50_000)
        spk = pb.skript_fuer(HD.derive([0, 1]).key, "segwit").data
        pb.pruefe_roh_tx(roh, txid, 0, 50_000, spk)
        with self.assertRaises(pb.PsbtFehler):
            pb.pruefe_roh_tx(roh, txid, 0, 50_001, spk)
        with self.assertRaises(pb.PsbtFehler):
            pb.pruefe_roh_tx(roh, txid, 0, 50_000, escript.p2wpkh(HD.derive([0, 2]).key).data)
        with self.assertRaises(pb.PsbtFehler):
            pb.pruefe_roh_tx(roh, "00" * 32, 0, 50_000, spk)

    def test_wechsel_index(self):
        pfade = pb.Pfade(HD, "segwit", NET, 100)
        bekannt = [_adresse(0, 7), _adresse(1, 3), _adresse(1, 1)]
        self.assertEqual(pb.naechster_wechsel_index(pfade, bekannt), 4)
        benutzt = {_adresse(1, 4), _adresse(1, 5)}
        self.assertEqual(pb.naechster_wechsel_index(
            pfade, bekannt, hat_history=lambda a: a in benutzt), 6)
        self.assertEqual(pb.naechster_wechsel_index(pfade, [], ausser=[_adresse(1, 0)]), 1)
        with self.assertRaises(pb.PsbtFehler):
            pb.naechster_wechsel_index(pfade, [], hat_history=lambda a: True, gap=3)


class TestErzeuge(unittest.TestCase):
    def test_sweep_ohne_wechselgeld_rbf_locktime(self):
        lab = Lab()
        lab.utxo(1, 10, 5_021_579)
        erg = lab.erzeuge(5_021_579 - 220)
        self.assertEqual(erg["status"], "ok")
        self.assertEqual((erg["fee_sats"], erg["vsize"], erg["wechselgeld_sats"]), (220, 110, 0))
        self.assertTrue(erg["ohne_wechselgeld"])
        p = _psbt(erg)
        self.assertIsNone(p.version)  # BIP174 v0
        self.assertEqual(p.tx.locktime, HOEHE)
        self.assertEqual(p.tx.version, 2)
        self.assertTrue(all(i.sequence == 0xFFFFFFFD for i in p.tx.vin))
        inp = p.inputs[0]
        self.assertEqual(inp.witness_utxo.value, 5_021_579)
        self.assertIsNotNone(inp.non_witness_utxo)
        self.assertEqual(inp.non_witness_utxo.txid(), p.tx.vin[0].txid)
        (pub, der), = inp.bip32_derivations.items()
        self.assertEqual((der.fingerprint, der.derivation), (HD.my_fingerprint, [1, 10]))
        self.assertEqual(pub, HD.derive([1, 10]).key)
        self.assertEqual(len(p.xpubs), 0)
        self.assertEqual(erg["sequence"], 0xFFFFFFFD)

    def test_locktime_null_ohne_hoehe(self):
        lab = Lab()
        lab.utxo(0, 1, 100_000)
        erg = lab.erzeuge(50_000, hoehe=None)
        self.assertEqual(_psbt(erg).tx.locktime, 0)
        self.assertEqual(erg["locktime"], 0)

    def test_wechselgeld_mit_deskriptor_origin(self):
        lab = Lab()
        lab.utxo(0, 2, 5_021_579)
        herkunft = pb.herkunft_fuer(XPUB, f"wpkh([{FP_ROOT}/84h/0h/0h]{XPUB}/<0;1>/*)")
        erg = lab.erzeuge(2_000_000, herkunft=herkunft, bekannt=[_adresse(1, 2)])
        self.assertEqual((erg["fee_sats"], erg["wechselgeld_sats"], erg["wechsel_index"]), (282, 3_021_297, 3))
        p = _psbt(erg)
        werte = sorted(o.value for o in p.tx.vout)
        self.assertEqual(werte, [2_000_000, 3_021_297])
        idx = [o.value for o in p.tx.vout].index(3_021_297)
        (pub, der), = p.outputs[idx].bip32_derivations.items()
        self.assertEqual(der.fingerprint.hex(), FP_ROOT)
        self.assertEqual(der.derivation, [0x80000054, 0x80000000, 0x80000000, 1, 3])
        self.assertEqual(p.tx.vout[idx].script_pubkey.data,
                         escript.p2wpkh(HD.derive([1, 3]).key).data)
        ziel_idx = 1 - idx
        self.assertEqual(p.outputs[ziel_idx].bip32_derivations, {})
        (_, der_in), = p.inputs[0].bip32_derivations.items()
        self.assertEqual(der_in.derivation[-2:], [0, 2])
        self.assertEqual(len(p.xpubs), 1)

    def test_signierbar_mit_beiden_fingerprints(self):
        """Ein Signer mit dem privaten Schlüssel erkennt jeden Input (Probe mit embit)."""
        for herkunft, signer in (
            (pb.herkunft_fuer(XPUB), KONTO_PRV),
            (pb.herkunft_fuer(XPUB, f"wpkh([{FP_ROOT}/84h/0h/0h]{XPUB}/<0;1>/*)"), ROOT),
        ):
            lab = Lab()
            lab.utxo(0, 1, 300_000)
            lab.utxo(1, 4, 200_000)
            erg = lab.erzeuge(450_000, herkunft=herkunft)
            p = _psbt(erg)
            self.assertEqual(p.sign_with(signer), len(p.inputs), herkunft.quelle)

    def test_feste_rate_mit_nachkommastellen(self):
        lab = Lab()
        lab.utxo(0, 1, 1_000_000)
        erg = lab.erzeuge(400_000, milli=1500)
        self.assertEqual(erg["vsize"], 141)
        self.assertEqual(erg["fee_sats"], 212)  # ceil(1,5 × 141)
        self.assertEqual(erg["sat_vb"], 1.5)
        self.assertEqual(erg["wechselgeld_sats"], 1_000_000 - 400_000 - 212)

    def test_deckel_senkt_feste_rate_nicht(self):
        """0,1 %-Deckel: bei der Vorschau 1 sat/vB, bei der PSBT bleibt die gewählte Rate."""
        lab = Lab()
        lab.utxo(0, 1, 1_000_000)
        erg = lab.erzeuge(50_000, milli=20_000)
        self.assertEqual(erg["fee_sats"], 20 * 141)

    def test_ziel_taproot_groesse(self):
        lab = Lab()
        lab.utxo(0, 1, 1_000_000)
        erg = lab.erzeuge(400_000, ziel=ZIEL_TR)
        self.assertEqual(erg["vsize"], 153)  # 10,5 + 68 + 43 + 31

    def test_staub_geht_in_gebuehr(self):
        # Rest 400 sats < 546, Gesamtgebühr 220 + 400 ≤ 0,1 % von 4 Mio → kein Wechselgeld.
        lab = Lab()
        lab.utxo(0, 1, 4_000_620)
        erg = lab.erzeuge(4_000_000)
        self.assertTrue(erg["ohne_wechselgeld"])
        self.assertEqual(erg["fee_sats"], 620)
        self.assertEqual(erg["staub_in_gebuehr_sats"], 400)
        self.assertEqual(len(_psbt(erg).tx.vout), 1)

    def test_staub_bleibt_wenn_deckel_ueberschritten(self):
        # Rest 400 sats wäre 620 Gebühr > 0,1 % von 100 000 → kleines Wechselgeld (≥ 330) bleibt.
        lab = Lab()
        lab.utxo(0, 1, 100_682)
        erg = lab.erzeuge(100_000)
        self.assertFalse(erg["ohne_wechselgeld"])
        self.assertTrue(erg["staub_wechselgeld"])
        self.assertEqual(erg["wechselgeld_sats"], 400)

    def test_offensiv_gelb_zurueck_ins_wechselgeld(self):
        lab = Lab()
        key = lab.utxo(0, 23, 97_847_370, gelb=68_379_055)
        erg = lab.erzeuge(14_734_157, modus="offensiv", nur=[key])
        self.assertEqual(erg["status"], "ok")
        self.assertEqual(erg["fee_sats"], 282)
        self.assertEqual(erg["wechselgeld_sats"], 83_112_931)
        wechsel = next(o for o in erg["outputs"] if o["rolle"] == "wechsel")
        self.assertEqual((wechsel["sats_gruen"], wechsel["sats_gelb"]), (14_733_876, 68_379_055))
        ziel = next(o for o in erg["outputs"] if o["rolle"] == "ziel")
        self.assertEqual((ziel["sats_gruen"], ziel["sats_gelb"], ziel["farbe"]), (14_734_157, 0, "gelb"))
        # Grüner Anteil minus Gebühr ist das Maximum; ein sat mehr: nicht gedeckt.
        self.assertEqual(lab.erzeuge(29_468_315 - 282 + 1, modus="offensiv", nur=[key])["status"],
                         "nicht_gedeckt")
        # Defensiv ist der gemischte UTXO unzulässig.
        self.assertEqual(lab.erzeuge(1_000_000, nur=[key])["status"], "unzulaessig")

    def test_genau_max_und_max_plus_eins(self):
        lab = Lab()
        werte = [112_173_005, 51_480_067, 60_349_786, 19_339_420]
        for i, w in enumerate(werte):
            lab.utxo(0, i, w)
        summe = sum(werte)
        erg = lab.erzeuge(summe - 628)
        self.assertEqual((erg["status"], len(erg["inputs"])), ("ok", 4))
        self.assertEqual((erg["fee_sats"], erg["wechselgeld_sats"]), (628, 0))
        self.assertEqual(lab.erzeuge(summe - 627)["status"], "nicht_gedeckt")
        self.assertEqual(lab.erzeuge(summe + 1)["status"], "ueber_max")
        # Netto-Maximum (grünes Maximum minus Gebühr): genau das, was noch geht.
        m = pb.erzeuge(**self._args(lab, 0), nur_max=True)
        self.assertEqual((m["status"], m["max_netto_sats"], m["max_netto_fee_sats"]),
                         ("max", summe - 628, 628))
        self.assertEqual(m["max_sats"], summe)

    @staticmethod
    def _args(lab, betrag, **ueber):
        return {**dict(xpub=XPUB, typ=lab.typ, herkunft=pb.herkunft_fuer(XPUB), netz=NET,
                       max_index=100, utxos=lab.utxos, pending=(), modus="defensiv",
                       strategie="wechselgeld", betrag=betrag, fee_milli=2000, ziel_adresse=ZIEL,
                       ziel_status="fremd", roh_tx_holen=lab.roh.get, hoehe=HOEHE,
                       rng=random.Random(1)), **ueber}

    def test_netto_max_ohne_ziel_und_taproot(self):
        lab = Lab()
        lab.utxo(0, 1, 700_000)
        lab.utxo(0, 2, 300_000)
        ohne = pb.erzeuge(**{**self._args(lab, 0), "ziel_adresse": "", "ziel_status": ""}, nur_max=True)
        self.assertTrue(ohne["ziel_angenommen"])
        mit = pb.erzeuge(**self._args(lab, 0), nur_max=True)
        self.assertEqual(ohne["max_netto_sats"], mit["max_netto_sats"])  # P2WPKH wie Wechsel
        tr = pb.erzeuge(**{**self._args(lab, 0), "ziel_adresse": ZIEL_TR}, nur_max=True)
        self.assertEqual(mit["max_netto_sats"] - tr["max_netto_sats"], 2 * 12)  # +12 vB
        for erg, ziel in ((mit, ZIEL), (tr, ZIEL_TR)):
            m = erg["max_netto_sats"]
            self.assertEqual(lab.erzeuge(m, ziel=ziel)["status"], "ok")
            self.assertEqual(lab.erzeuge(m + 1, ziel=ziel)["status"], "nicht_gedeckt")

    def test_offensiv_fifo_zwei_gemischte_wie_t5c(self):
        """Lab-Fall T5c: zwei gemischte Inputs — Ziel ganz grün, Wechsel ganz gelb."""
        lab = Lab()
        lab.utxo(0, 1, 29_468_066 + 68_379_304, gelb=68_379_304, zeit=10)
        lab.utxo(0, 2, 1_723_934 + 18_028_117, gelb=18_028_117, zeit=20)
        m = pb.erzeuge(**self._args(lab, 0, modus="offensiv"), nur_max=True)
        self.assertEqual((m["max_netto_sats"], m["max_netto_fee_sats"]), (31_191_582, 418))
        erg = lab.erzeuge(31_191_582, modus="offensiv")
        self.assertEqual((erg["status"], erg["fee_sats"], len(erg["inputs"])), ("ok", 418, 2))
        ziel = next(o for o in erg["outputs"] if o["rolle"] == "ziel")
        wechsel = next(o for o in erg["outputs"] if o["rolle"] == "wechsel")
        self.assertEqual((ziel["sats_gruen"], ziel["sats_gelb"]), (31_191_582, 0))
        self.assertEqual((wechsel["sats_gruen"], wechsel["sats_gelb"]), (0, 86_407_421))
        self.assertEqual(lab.erzeuge(31_191_583, modus="offensiv")["status"], "nicht_gedeckt")

    def test_ziel_im_selben_wallet_zaehlt_als_rueckfluss(self):
        """Umbuchung ins eigene Wallet: Gebühr zuerst, dann beide Outputs nach vout."""
        from core import fifo_lots as fl

        lab = Lab()
        lab.utxo(0, 1, 1_000_000, gelb=600_000)
        eigen = _adresse(0, 50)
        erg = pb.erzeuge(**{**self._args(lab, 150_000, modus="offensiv"), "ziel_adresse": eigen,
                            "ziel_status": "meine", "ziel_wallet": "Test"}, quelle_wallet="Test")
        self.assertEqual(erg["status"], "ok")
        rest = 400_000 - erg["fee_sats"]
        erwartet = []
        for o in erg["outputs"]:
            gruen = min(rest, o["value_sats"])
            rest -= gruen
            erwartet.append((gruen, o["value_sats"] - gruen))
        self.assertEqual([(o["sats_gruen"], o["sats_gelb"]) for o in erg["outputs"]], erwartet)
        # Fremd (oder anderes Wallet) verlässt das Wallet: Ziel zuerst.
        fremd = lab.erzeuge(150_000, modus="offensiv")
        ziel = next(o for o in fremd["outputs"] if o["rolle"] == "ziel")
        self.assertEqual(ziel["sats_gruen"], 150_000)
        self.assertTrue(fl.GEBUEHR)

    def test_ausschluesse(self):
        lab = Lab()
        lab.utxo(0, 1, 500_000, pending=True)
        lab.utxo(0, 2, 500_000, bestaetigt=False)
        lab.utxo(0, 3, 500_000, grau=1)
        lab.utxo(0, 4, 500_000, gruen=0, gelb=500_000)
        erg = lab.erzeuge(100_000)
        self.assertEqual((erg["status"], erg["max_sats"]), ("ueber_max", 0))

    def test_eingaben_pruefung(self):
        lab = Lab()
        lab.utxo(0, 1, 500_000)
        with self.assertRaises(pb.PsbtFehler):
            lab.erzeuge(545)  # unter Staubgrenze
        with self.assertRaises(pb.PsbtFehler):
            lab.erzeuge(10_000, milli=0)
        with self.assertRaises(pb.PsbtFehler):
            pb.erzeuge(xpub=XPUB, typ="taproot", herkunft=pb.herkunft_fuer(XPUB), netz=NET,
                       max_index=10, utxos=[], pending=(), modus="defensiv",
                       strategie="wechselgeld", betrag=1000, fee_milli=1000,
                       ziel_adresse=ZIEL, ziel_status="fremd")
        with self.assertRaises(pb.PsbtFehler):
            pb.erzeuge(
                xpub=XPUB, typ="segwit", herkunft=pb.herkunft_fuer(XPUB), netz=NET,
                max_index=10, utxos=lab.utxos, pending=(), modus="defensiv",
                strategie="wechselgeld", betrag=10_000, fee_milli=1000,
                ziel_adresse=ZIEL, ziel_status="falsches_netz")

    def test_privater_schluessel_abgelehnt(self):
        lab = Lab()
        lab.utxo(0, 1, 500_000)
        with self.assertRaises(pb.PsbtFehler):
            pb.erzeuge(xpub=KONTO_PRV.to_string(), typ="segwit", herkunft=pb.herkunft_fuer(XPUB),
                       netz=NET, max_index=10, utxos=lab.utxos, pending=(), modus="defensiv",
                       strategie="wechselgeld", betrag=10_000, fee_milli=1000,
                       ziel_adresse=ZIEL, ziel_status="fremd")
        self.assertNotIn("prv", pb.psbt_base64(_psbt(lab.erzeuge(10_000))))

    def test_nested_und_legacy(self):
        lab = Lab("nested")
        lab.utxo(0, 1, 500_000)
        p = _psbt(lab.erzeuge(100_000))
        self.assertIsNotNone(p.inputs[0].redeem_script)
        self.assertIsNotNone(p.inputs[0].witness_utxo)
        wechsel = [o for o in p.outputs if o.bip32_derivations]
        self.assertEqual(len(wechsel), 1)
        self.assertIsNotNone(wechsel[0].redeem_script)
        leg = Lab("legacy")
        leg.utxo(0, 1, 500_000)
        p = _psbt(leg.erzeuge(100_000))
        self.assertIsNone(p.inputs[0].witness_utxo)
        self.assertIsNotNone(p.inputs[0].non_witness_utxo)
        with self.assertRaises(pb.PsbtFehler):
            leg.erzeuge(100_000, ohne_roh=True)

    def test_fremde_adresse_als_input_abgelehnt(self):
        lab = Lab()
        lab.utxo(0, 1, 500_000)
        lab.utxos[0]["address"] = ZIEL
        with self.assertRaises(pb.PsbtFehler):
            lab.erzeuge(100_000)

    def test_coin_control_waehle(self):
        lab = Lab()
        a = lab.utxo(0, 1, 500_000)
        lab.utxo(0, 2, 900_000)
        kand = kandidaten(lab.utxos, modus="defensiv")
        erg = waehle(kand, betrag=100_000, basis_rate=FesteRate(1000), nur=[a])
        self.assertEqual([i["key"] for i in erg["inputs"]], [a])
        self.assertEqual(waehle(kand, betrag=100_000, basis_rate=1, nur=["x:0"])["status"], "unzulaessig")


# ---------------------------------------------------------------------------
# Multisig 2-von-3 (wsh/sh-wsh sortedmulti) — Test-Seeds nur hier
# ---------------------------------------------------------------------------

MS_ROOTS = [HDKey.from_seed(bytes([0x40 + i]) * 32, version=NET["xprv"]) for i in range(3)]
MS_PFAD = "m/48h/0h/0h/2h"
MS_KONTEN = [r.derive(MS_PFAD) for r in MS_ROOTS]
MS_XPUBS = [k.to_public().to_string() for k in MS_KONTEN]
MS_FPS = [r.my_fingerprint.hex() for r in MS_ROOTS]
MS_PFAD_INT = [0x80000030, 0x80000000, 0x80000000, 0x80000002]


def _ms_desc(huelle="wsh", art="sortedmulti", origin=True, m=2, ableitung="/<0;1>/*"):
    teile = [(f"[{fp}/48h/0h/0h/2h]" if origin else "") + x + ableitung
             for fp, x in zip(MS_FPS, MS_XPUBS)]
    kern = f"{art}({m},{','.join(teile)})"
    return f"sh(wsh({kern}))" if huelle == "sh-wsh" else f"wsh({kern})"


def _ms_lab(**kw):
    return Lab(politik=pb.MultisigPolitik(_ms_desc(**kw)))


class TestMultisigBausteine(unittest.TestCase):
    def test_vbytes_m_von_n(self):
        self.assertEqual(pb.multisig_input_vbytes(2, 3), 104.5)
        self.assertEqual(pb.multisig_input_vbytes(2, 3, "sh-wsh"), 139.5)
        self.assertEqual(pb.multisig_input_vbytes(1, 1), 41 + (1 + 1 + 73 + 1 + 37) / 4)
        self.assertEqual(pb.multisig_input_vbytes(3, 5), 41 + (1 + 1 + 219 + 1 + 173) / 4)
        for m, n in ((0, 3), (4, 3), (2, 17)):
            with self.assertRaises(pb.PsbtFehler):
                pb.multisig_input_vbytes(m, n)
        p2wsh = escript.p2wsh(escript.multisig(1, [HD.key])).data
        self.assertEqual(pb.output_vbytes(p2wsh), 43)
        # 10,5 + 104,5 + Ziel P2WPKH 31 + Wechsel P2WSH 43
        self.assertEqual(pb.vsize_tx([104.5], [escript.p2wpkh(HD.key).data, p2wsh]), 189)
        self.assertEqual(pb.vsize_tx([104.5] * 2, [p2wsh]), 263)

    def test_politik_wie_embit_deskriptor(self):
        from embit.descriptor import Descriptor

        for huelle in ("wsh", "sh-wsh"):
            for art in ("sortedmulti", "multi"):
                text = _ms_desc(huelle, art)
                pol = pb.MultisigPolitik(text)
                desc = Descriptor.from_string(text)
                self.assertEqual((pol.m, pol.n, pol.typ, pol.sortiert),
                                 (2, 3, huelle, art == "sortedmulti"))
                for change in (0, 1):
                    for i in (0, 1, 7, 33):
                        soll = desc.derive(i, branch_index=change)
                        abl = pol.ableiten(change, i)
                        self.assertEqual(abl.spk.data, soll.script_pubkey().data)
                        self.assertEqual(abl.witness_script.data, soll.witness_script().data)
        pol = pb.MultisigPolitik(_ms_desc())
        abl = pol.ableiten(1, 4)
        secs = [p.sec() for p, _ in abl.schluessel]
        self.assertNotEqual(secs, sorted(secs), "Testdaten: Deskriptor-Reihenfolge ≠ sortiert")
        # BIP67: im Skript sortiert, Pfade je Cosigner aus dem Origin.
        self.assertIn(b"".join(b"\x21" + s for s in sorted(secs)), abl.witness_script.data)
        for (pub, dp), fp, konto in zip(abl.schluessel, MS_FPS, MS_KONTEN):
            self.assertEqual(dp.fingerprint.hex(), fp)
            self.assertEqual(dp.derivation, MS_PFAD_INT + [1, 4])
            self.assertEqual(pub, konto.derive([1, 4]).key)
        self.assertEqual(pol.pfad_text(1, 4), "m/48h/0h/0h/2h/1/4")
        self.assertEqual(pol.quelle, "deskriptor")
        self.assertTrue(all(c.global_xpub for c in pol.cosigner))
        for x in MS_XPUBS:
            self.assertNotIn(x, str(pol.uebersicht()))

    def test_nicht_unterstuetzte_deskriptoren(self):
        for text in (
            "",
            _ms_desc(ableitung="/0/*"),                         # kein Wechselzweig
            f"tr({MS_XPUBS[0]}/<0;1>/*,multi_a(2,{MS_XPUBS[1]}/<0;1>/*,{MS_XPUBS[2]}/<0;1>/*))",
            f"wsh(and_v(v:pk({MS_XPUBS[0]}/<0;1>/*),older(144)))",  # Miniscript
            f"sh(sortedmulti(2,{MS_XPUBS[0]}/<0;1>/*,{MS_XPUBS[1]}/<0;1>/*))",  # Legacy-P2SH
            f"wsh(sortedmulti(2,{MS_KONTEN[0].to_string()}/<0;1>/*,{MS_XPUBS[1]}/<0;1>/*))",  # xprv
        ):
            with self.subTest(text=text[:40]):
                with self.assertRaises(pb.PsbtFehler):
                    pb.MultisigPolitik(text)


class TestMultisigErzeuge(unittest.TestCase):
    def test_ein_gruener_utxo_mit_wechselgeld(self):
        lab = _ms_lab()
        lab.utxo(0, 3, 5_000_000)
        erg = lab.erzeuge(2_000_000, bekannt=[lab.politik.ableiten(1, 2).spk.address(NET)])
        self.assertEqual(erg["status"], "ok")
        # 10,5 + 104,5 + 31 + 43 = 189 vB × 2 sat/vB
        self.assertEqual((erg["vsize"], erg["fee_sats"], erg["wechsel_index"]), (189, 378, 3))
        self.assertEqual(erg["wechselgeld_sats"], 5_000_000 - 2_000_000 - 378)
        self.assertEqual(erg["multisig"]["m"], 2)
        self.assertEqual(erg["multisig"]["fingerprints"], MS_FPS)
        self.assertEqual(erg["herkunft"]["quelle"], "deskriptor")
        self.assertTrue(erg["global_xpub"])
        self.assertEqual(erg["inputs"][0]["pfad"], "m/48h/0h/0h/2h/0/3")
        for x in MS_XPUBS:
            self.assertNotIn(x, str({k: v for k, v in erg.items() if k != "psbt_base64"}))
        p = _psbt(erg)
        inp = p.inputs[0]
        abl = lab.politik.ableiten(0, 3)
        self.assertEqual(inp.witness_utxo.value, 5_000_000)
        self.assertEqual(inp.witness_utxo.script_pubkey.data, abl.spk.data)
        self.assertEqual(inp.non_witness_utxo.txid(), p.tx.vin[0].txid)
        self.assertEqual(inp.witness_script.data, abl.witness_script.data)
        self.assertIsNone(inp.redeem_script)
        self.assertEqual(len(inp.bip32_derivations), 3)
        self.assertEqual(sorted(d.fingerprint.hex() for d in inp.bip32_derivations.values()), sorted(MS_FPS))
        self.assertTrue(all(d.derivation == MS_PFAD_INT + [0, 3] for d in inp.bip32_derivations.values()))
        idx = [o.value for o in p.tx.vout].index(erg["wechselgeld_sats"])
        out = p.outputs[idx]
        wabl = lab.politik.ableiten(1, 3)
        self.assertEqual(p.tx.vout[idx].script_pubkey.data, wabl.spk.data)
        self.assertEqual(out.witness_script.data, wabl.witness_script.data)
        self.assertEqual(len(out.bip32_derivations), 3)
        self.assertTrue(all(d.derivation == MS_PFAD_INT + [1, 3] for d in out.bip32_derivations.values()))
        self.assertEqual(p.outputs[1 - idx].bip32_derivations, {})
        self.assertIsNone(p.outputs[1 - idx].witness_script)
        # GLOBAL_XPUB je Cosigner mit Fingerprint und Konto-Pfad.
        self.assertEqual(len(p.xpubs), 3)
        for hd, dp in p.xpubs.items():
            i = MS_XPUBS.index(hd.to_string())
            self.assertEqual((dp.fingerprint.hex(), dp.derivation), (MS_FPS[i], MS_PFAD_INT))
        self.assertTrue(all(i.sequence == 0xFFFFFFFD for i in p.tx.vin))
        self.assertEqual(p.tx.locktime, HOEHE)

    def test_signieren_je_cosigner_teilweise(self):
        """Jeder Cosigner erkennt alle Inputs; nach 2 von 3 liegen 2 Teil-Signaturen je Input."""
        lab = _ms_lab()
        lab.utxo(0, 1, 300_000)
        lab.utxo(1, 4, 200_000)
        erg = lab.erzeuge(450_000)
        self.assertEqual(len(erg["inputs"]), 2)
        b64 = erg["psbt_base64"]
        for paar in ((0, 1), (1, 2)):
            p = PSBT.from_string(b64)
            for i in paar:
                self.assertEqual(p.sign_with(MS_ROOTS[i]), 2)
            self.assertTrue(all(len(inp.partial_sigs) == 2 for inp in p.inputs))
        einzeln = PSBT.from_string(b64)
        einzeln.sign_with(MS_ROOTS[2])
        self.assertTrue(all(len(inp.partial_sigs) == 1 for inp in einzeln.inputs))

    def test_sh_wsh_redeem_script_und_groesse(self):
        lab = _ms_lab(huelle="sh-wsh")
        lab.utxo(0, 1, 1_000_000)
        erg = lab.erzeuge(400_000)
        # 10,5 + 139,5 + 31 + P2SH-Wechsel 32 = 213
        self.assertEqual(erg["vsize"], 213)
        p = _psbt(erg)
        abl = lab.politik.ableiten(0, 1)
        self.assertEqual(p.inputs[0].redeem_script.data, escript.p2wsh(abl.witness_script).data)
        self.assertEqual(p.inputs[0].witness_script.data, abl.witness_script.data)
        wechsel = [o for o in p.outputs if o.bip32_derivations]
        self.assertEqual(len(wechsel), 1)
        self.assertIsNotNone(wechsel[0].redeem_script)
        self.assertEqual(p.sign_with(MS_ROOTS[0]), 1)

    def test_ohne_origin_fingerprint_des_xpub(self):
        """Kurzform ohne [fp/…]: Fingerprint je XPUB, Pfad relativ, kein GLOBAL_XPUB."""
        lab = _ms_lab(origin=False)
        lab.utxo(0, 1, 1_000_000)
        erg = lab.erzeuge(400_000)
        self.assertEqual(erg["herkunft"]["quelle"], "xpub")
        self.assertFalse(erg["global_xpub"])
        p = _psbt(erg)
        self.assertEqual(len(p.xpubs), 0)
        ders = list(p.inputs[0].bip32_derivations.values())
        self.assertTrue(all(d.derivation == [0, 1] for d in ders))
        self.assertEqual(sorted(d.fingerprint for d in ders),
                         sorted(HDKey.from_string(x).my_fingerprint for x in MS_XPUBS))
        self.assertEqual(p.sign_with(MS_KONTEN[1]), 1)

    def test_offensiv_gemischt_gelb_zurueck(self):
        lab = _ms_lab()
        key = lab.utxo(0, 9, 97_847_370, gelb=68_379_055)
        erg = lab.erzeuge(14_734_157, modus="offensiv", nur=[key])
        self.assertEqual(erg["status"], "ok")
        self.assertEqual(erg["fee_sats"], 378)
        wechsel = next(o for o in erg["outputs"] if o["rolle"] == "wechsel")
        self.assertEqual((wechsel["sats_gruen"], wechsel["sats_gelb"]),
                         (97_847_370 - 68_379_055 - 14_734_157 - 378, 68_379_055))
        self.assertEqual(lab.erzeuge(1_000_000, nur=[key])["status"], "unzulaessig")

    def test_mehrere_inputs_genau_max_und_max_plus_eins(self):
        lab = _ms_lab()
        werte = [40_000_000, 25_000_000, 10_000_000]
        for i, w in enumerate(werte):
            lab.utxo(0, i, w)
        summe = sum(werte)
        # Ohne Wechselgeld: 10,5 + 3 × 104,5 + 31 = 355 vB → 355 sats bei 1 sat/vB.
        erg = lab.erzeuge(summe - 355, milli=1000)
        self.assertEqual((erg["status"], len(erg["inputs"]), erg["fee_sats"], erg["vsize"]),
                         ("ok", 3, 355, 355))
        self.assertTrue(erg["ohne_wechselgeld"])
        self.assertEqual(lab.erzeuge(summe - 354, milli=1000)["status"], "nicht_gedeckt")
        self.assertEqual(lab.erzeuge(summe + 1, milli=1000)["status"], "ueber_max")
        p = _psbt(erg)
        self.assertTrue(all(len(i.bip32_derivations) == 3 and i.witness_script for i in p.inputs))

    def test_fremde_adresse_als_input_abgelehnt(self):
        lab = _ms_lab()
        lab.utxo(0, 1, 500_000)
        lab.utxos[0]["address"] = ZIEL
        with self.assertRaises(pb.PsbtFehler):
            lab.erzeuge(100_000)


class TestZusammenfuehren(unittest.TestCase):
    def test_nur_echter_bestand_mit_lots(self):
        bestand = [
            {"txid": "AA" * 32, "vout": 0, "value": 1000, "address": "a",
             "status": {"confirmed": True}},
            {"txid": "bb" * 32, "vout": 1, "value": 2000, "address": "b",
             "status": {"confirmed": False}},
            {"txid": "cc" * 32, "vout": 0, "value": 3000, "address": "c"},
        ]
        lots = [
            {"txid": "aa" * 32, "vout": 0, "value_sats": 1000, "sats_gruen": 1000},
            {"txid": "bb" * 32, "vout": 1, "value_sats": 2000, "sats_gruen": 2000},
            {"txid": "cc" * 32, "vout": 0, "value_sats": 9999, "sats_gruen": 9999},
            {"txid": "dd" * 32, "vout": 0, "value_sats": 5000, "sats_gruen": 5000},
        ]
        aus = pb.zusammenfuehren(bestand, lots)
        self.assertEqual([u["key"] for u in aus], ["aa" * 32 + ":0", "bb" * 32 + ":1"])
        self.assertEqual([u["bestaetigt"] for u in aus], [True, False])


class TestServerPruefung(unittest.TestCase):
    """``_erzeugen``: Bestand, Lots und Mempool kommen vom Server, nie vom Browser."""

    def setUp(self):
        from core.config import WalletEntry

        self.lab = self._lab()
        self.k_gruen = self.lab.utxo(0, 1, 600_000, zeit=100)
        self.k_weg = self.lab.utxo(0, 2, 900_000, zeit=50)       # schon ausgegeben
        self.k_pending = self.lab.utxo(0, 3, 800_000, zeit=60)  # im Mempool
        self.entry = self._entry(WalletEntry)
        self.geheim = [XPUB]
        bestand = []
        for u in self.lab.utxos:
            if u["key"] == self.k_weg:
                continue
            bestand.append({"txid": u["txid"], "vout": 0, "value": u["value_sats"],
                            "address": u["address"], "status": {"confirmed": True}})
        self.bestand = bestand
        from core import wallets as wm

        self.kid = wm.eintrag_id(self.entry)
        self.events = [dict(u, wallet_id=self.kid) for u in self.lab.utxos]
        self.state = SimpleNamespace(
            context_bereit=lambda: True, entries=[self.entry],
            env=lambda: SimpleNamespace(values=lambda: {"STEUER_ANSCHAFFUNG": "juengste"}),
            wallet_ctx=SimpleNamespace(xpubs=[XPUB], resolve_address=lambda a: None),
            wallet_ctx_fuer_ansicht=lambda: None, cache_dir=Path("/nix"),
            immutable_cache_dir=Path("/nix"),
        )

    def _lab(self):
        return Lab()

    def _entry(self, WalletEntry):
        return WalletEntry(xpub=XPUB, name="Test", script_type="segwit")

    def _rufe(self, payload, **ueber):
        import server
        from httpserver.api import psbt as api

        def mempool(state, gecacht, anhang, **kw):
            for u in gecacht:
                if f"{u['txid']}:{u['vout']}" == self.k_pending:
                    u["spending_pending"] = True
            return gecacht, anhang

        client = SimpleNamespace(request=lambda m, p: self.lab.roh[p[0]].hex()
                                 if m == "blockchain.transaction.get" else
                                 ({"height": HOEHE} if m == "blockchain.headers.subscribe" else []))
        with mock.patch.object(server.utxos_mod, "load_cached_utxos",
                               return_value=[dict(b) for b in self.bestand]), \
                mock.patch.object(server, "_eigener_fulcrum_client", return_value=client), \
                mock.patch.object(server, "_mit_mempool_pending", side_effect=mempool), \
                mock.patch.object(server, "_cache_bekannt_adressen", return_value=(set(), 0)), \
                mock.patch("httpserver.api.tax.api_tax",
                           return_value={"zeitstrahl": {"events": self.events}}), \
                mock.patch("core.bitcoind_rpc.stelle_core_client_bereit", return_value=None), \
                mock.patch("core.bitcoind_rpc.stelle_utxo_core_client_bereit", return_value=None):
            return api._erzeugen(self.state, {"wallet_id": self.kid, "adresse": ZIEL, "fee": "2",
                                              **payload}, **ueber)

    def test_browser_werte_werden_ignoriert(self):
        erg = self._rufe({"betrag": 100_000, "utxos": [{"key": "ff" * 32 + ":0",
                          "value_sats": 10**12, "sats_gruen": 10**12}], "max": 10**12})
        self.assertEqual(erg["status"], "ok")
        self.assertEqual([i["key"] for i in erg["inputs"]], [self.k_gruen])
        self.assertEqual(erg["max_sats"], 600_000)  # ohne ausgegebenen und Mempool-UTXO
        self.assertTrue(erg["mempool_geprueft"])
        self.assertEqual(erg["locktime"], HOEHE)
        for x in self.geheim:
            self.assertNotIn(x, str({k: v for k, v in erg.items() if k != "psbt_base64"}))

    def test_ueber_max_und_mempool(self):
        self.assertEqual(self._rufe({"betrag": 700_000})["status"], "ueber_max")
        erg = self._rufe({"betrag": 100_000, "nur_inputs": [self.k_pending]})
        self.assertEqual(erg["status"], "unzulaessig")
        erg = self._rufe({"betrag": 100_000, "nur_inputs": [self.k_weg]})
        self.assertEqual(erg["status"], "unzulaessig")

    def test_fehlerfaelle(self):
        from server import ApiError

        for payload, status in (
            ({"betrag": 100_000, "fee": "0"}, 400),
            ({"betrag": 100_000, "fee": "1,2345"}, 400),
            ({"betrag": 100_000, "adresse": "bc1qungueltig"}, 400),
            ({"betrag": 100_000, "adresse": "tb1qlkg6h5f6kva8jx0ktaceaeyty8tax0l4n4acqp"}, 400),
            ({"betrag": 0}, 400),
            ({"betrag": 100_000, "modus": "offensiv"}, 409),
            ({"betrag": 100_000, "strategie": "zufall"}, 400),
            ({"betrag": 100_000, "nur_inputs": "x"}, 400),
            ({"betrag": 100, "fee": "2"}, 422),
            ({"betrag": 100_000, "wallet_id": "unbekannt"}, 404),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ApiError) as ctx:
                    self._rufe(payload)
                self.assertEqual(ctx.exception.status, status)

    def test_multisig_ohne_bausteine_400(self):
        """Multisig-Policy, die SatSage nicht baut (Taproot multi_a): 400 mit Grund."""
        from core import wallets as wm
        from core.config import WalletEntry
        from server import ApiError

        tr = WalletEntry(name="Tr", descriptor=(f"tr({MS_XPUBS[0]}/<0;1>/*,multi_a(2,{MS_XPUBS[1]}/<0;1>/*,"
                                                f"{MS_XPUBS[2]}/<0;1>/*))"))
        self.assertTrue(tr.is_multisig)
        self.state.entries = [tr]
        self.kid = wm.eintrag_id(tr)
        with self.assertRaises(ApiError) as ctx:
            self._rufe({"betrag": 100_000})
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("Taproot", str(ctx.exception))

    def test_offensiv_aus_einstellung(self):
        erg = self._rufe({"betrag": 100_000},
                         einstellungen={"anschaffung": "aelteste", "haltefrist_jahre": 1, "stichtag": ""})
        self.assertEqual(erg["modus"], "offensiv")

    def test_route_in_server(self):
        text = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('teile == ["psbt", "erzeugen"] and methode == "POST"', text)
        self.assertIn('teile == ["psbt", "max"] and methode == "POST"', text)

    def test_netto_max_endpunkt(self):
        """``POST /api/psbt/max``: Netto-Maximum geht genau, + 1 nicht mehr."""
        erg = self._rufe({}, nur_max=True)
        self.assertEqual(erg["status"], "max")
        self.assertEqual(erg["max_sats"], 600_000)
        m = erg["max_netto_sats"]
        self.assertEqual(m, 600_000 - erg["max_netto_fee_sats"])
        self.assertEqual(self._rufe({"betrag": m})["status"], "ok")
        self.assertEqual(self._rufe({"betrag": m + 1})["status"], "nicht_gedeckt")
        # Höhere Rate: kleineres Maximum; ohne Adresse: Größe der Wechseladresse.
        self.assertLess(self._rufe({"fee": "5"}, nur_max=True)["max_netto_sats"], m)
        ohne = self._rufe({"adresse": ""}, nur_max=True)
        self.assertTrue(ohne["ziel_angenommen"])
        for x in self.geheim:
            self.assertNotIn(x, str(erg))


class TestServerPruefungMultisig(TestServerPruefung):
    """Dieselbe Server-Neuprüfung für ein 2-von-3-Deskriptor-Wallet (``WALLET_n_DESC``)."""

    def _lab(self):
        return _ms_lab()

    def _entry(self, WalletEntry):
        return WalletEntry(descriptor=_ms_desc(), name="Multi")

    def setUp(self):
        super().setUp()
        self.geheim = list(MS_XPUBS)
        self.assertTrue(self.entry.is_multisig)

    def test_multisig_psbt_felder(self):
        erg = self._rufe({"betrag": 100_000})
        self.assertEqual((erg["status"], erg["skripttyp"]), ("ok", "wsh"))
        self.assertEqual(erg["multisig"]["n"], 3)
        self.assertEqual(erg["vsize"], 189)
        p = _psbt(erg)
        self.assertEqual(len(p.xpubs), 3)
        self.assertEqual(len(p.inputs[0].bip32_derivations), 3)
        self.assertIsNotNone(p.inputs[0].non_witness_utxo)

    def test_vorschau_groessen_nach_wallet(self):
        from httpserver.api import psbt as api

        g = api._vorschau_groessen(self.state, self.kid)
        self.assertEqual((g.input_vb, g.wechsel_vb), (104.5, 43))
        self.assertIsNone(api._vorschau_groessen(self.state, ""))
        self.assertIsNone(api._vorschau_groessen(self.state, "unbekannt"))


if __name__ == "__main__":
    unittest.main()
