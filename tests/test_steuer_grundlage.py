"""
Woraus die Steuerauswertung rechnet, wenn nur ein Teil der Wallets einen
Verlauf hat.

Der Verlauf wird je Wallet erhoben und kann abbrechen oder für ein einzelnes
Wallet fehlen. Wird er dann global gegen den UTXO-Bestand ausgespielt,
verschwinden die übrigen Wallets aus der Aufstellung — in einer Steuerangabe
ein stiller Verlust, den niemand bemerkt.

Richtig ist die Entscheidung **je Wallet**: Verlauf, wo er vorliegt, sonst der
UTXO-Bestand. Und die Auswertung muss sagen, welche Wallets nur auf dem
Bestand beruhen.
"""
import tempfile
import unittest
from pathlib import Path

import main
import server
from tests.fixtures import BIP84_RECEIVE_0, BIP84_ZPUB, ZWEITER_ALS_XPUB, txid


def utxo(marker: str, sats: int) -> dict:
    return {
        "txid": txid(marker), "vout": 0, "address": BIP84_RECEIVE_0,
        "value": sats,
        "status": {"confirmed": True, "block_time": 1_700_000_000},
    }


def verlaufs_eintrag(marker: str, sats: int, *, ausgegeben: bool = False) -> dict:
    eintrag = dict(utxo(marker, sats))
    eintrag["spent"] = ausgegeben
    eintrag["spent_txid"] = txid("ff") if ausgegeben else None
    if ausgegeben:
        eintrag["spent_time_ts"] = 1_760_000_000
    return eintrag


class GrundlageBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        wurzel = Path(self._tmp.name)
        self.cache = wurzel / "utxo_cache"
        self.cache.mkdir()
        immutable = wurzel / "immutable_cache"
        immutable.mkdir()
        env_pfad = wurzel / ".env"
        env_pfad.write_text(
            f"XPUBS={BIP84_ZPUB} {ZWEITER_ALS_XPUB}\n"
            "WALLET_NAMES=Erstes|Zweites\n"
            "MAX_ADDRESSES_PER_XPUB=4|4\n",
            encoding="utf-8",
        )
        self.state = server.AppState(
            env_pfad, self.cache, immutable, sanctions_dir=wurzel
        )

    def bestand(self, xpub: str, marker: str, sats: int) -> None:
        main.save_xpub_utxo_cache(xpub, [utxo(marker, sats)], self.cache, "test")

    def verlauf(self, xpub: str, eintraege: list[dict]) -> None:
        main.save_xpub_verlauf_cache(xpub, eintraege, self.cache)

    def grundlage(self) -> list[dict]:
        """Nur die Einträge — die Wallet-Namen prüft TestAusweis."""
        eintraege, _ = server._steuer_grundlage(self.state)
        return eintraege


class TestGrundlage(GrundlageBasis):

    def test_ohne_verlauf_zaehlen_alle_bestaende(self):
        self.bestand(BIP84_ZPUB, "a1", 100_000)
        self.bestand(ZWEITER_ALS_XPUB, "b1", 200_000)
        self.assertEqual(len(self.grundlage()), 2)

    def test_verlauf_fuer_ein_wallet_verdraengt_das_andere_nicht(self):
        """
        Der Fehler, um den es geht: Wallet B verschwand vollständig, sobald
        Wallet A einen Verlauf hatte.
        """
        self.bestand(BIP84_ZPUB, "a1", 100_000)
        self.bestand(ZWEITER_ALS_XPUB, "b1", 200_000)
        self.verlauf(BIP84_ZPUB, [verlaufs_eintrag("c1", 50_000)])

        grundlage = self.grundlage()
        self.assertEqual(len(grundlage), 2)
        betraege = sorted(e["value"] for e in grundlage)
        self.assertEqual(betraege, [50_000, 200_000])

    def test_verlauf_ersetzt_den_bestand_desselben_wallets(self):
        """Für dasselbe Wallet gilt der Verlauf — er enthält den Bestand mit."""
        self.bestand(BIP84_ZPUB, "a1", 100_000)
        self.verlauf(BIP84_ZPUB, [
            verlaufs_eintrag("c1", 50_000),
            verlaufs_eintrag("c2", 70_000, ausgegeben=True),
        ])
        grundlage = self.grundlage()
        self.assertEqual(len(grundlage), 2)
        self.assertNotIn(100_000, [e["value"] for e in grundlage])

    def test_verlauf_fuer_beide(self):
        self.verlauf(BIP84_ZPUB, [verlaufs_eintrag("c1", 10_000)])
        self.verlauf(ZWEITER_ALS_XPUB, [verlaufs_eintrag("d1", 20_000)])
        self.assertEqual(len(self.grundlage()), 2)

    def test_leerer_verlauf_faellt_auf_den_bestand_zurueck(self):
        """
        Ein abgebrochener Lauf hinterlässt eine leere Liste. Sie als „dieses
        Wallet ist leer" zu lesen wäre falsch — dann lieber der Bestand.
        """
        self.bestand(BIP84_ZPUB, "a1", 100_000)
        self.verlauf(BIP84_ZPUB, [])
        grundlage = self.grundlage()
        self.assertEqual(len(grundlage), 1)
        self.assertEqual(grundlage[0]["value"], 100_000)


class TestAusweis(GrundlageBasis):
    """Die Auswertung muss sagen, worauf sie beruht."""

    def test_wallets_ohne_verlauf_werden_benannt(self):
        self.bestand(BIP84_ZPUB, "a1", 100_000)
        self.bestand(ZWEITER_ALS_XPUB, "b1", 200_000)
        self.verlauf(BIP84_ZPUB, [verlaufs_eintrag("c1", 50_000)])

        auswertung = server._steuer_auswertung(self.state, {})
        self.assertEqual(auswertung["ohne_verlauf"], ["Zweites"])

    def test_alle_mit_verlauf_meldet_nichts(self):
        self.verlauf(BIP84_ZPUB, [verlaufs_eintrag("c1", 10_000)])
        self.verlauf(ZWEITER_ALS_XPUB, [verlaufs_eintrag("d1", 20_000)])
        auswertung = server._steuer_auswertung(self.state, {})
        self.assertEqual(auswertung["ohne_verlauf"], [])

    def test_hinweis_nennt_die_betroffenen_wallets(self):
        """
        Eine gemischte Grundlage muss auffallen: Für die einen Wallets sind
        Veräußerungen erfasst, für die anderen nicht.
        """
        self.bestand(ZWEITER_ALS_XPUB, "b1", 200_000)
        self.verlauf(BIP84_ZPUB, [verlaufs_eintrag("c1", 50_000)])

        auswertung = server._steuer_auswertung(self.state, {})
        hinweise = " ".join(auswertung["hinweise"])
        self.assertIn("Zweites", hinweise)


if __name__ == "__main__":
    unittest.main()
