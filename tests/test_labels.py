"""
Adress-Labels: Format lesen und richtig einordnen.

Der Bestand kommt als Binärdatei von außen. Wird das Format auch nur um ein
Byte falsch gelesen, findet die Suche nichts mehr — ohne Fehlermeldung, denn
„nicht gefunden" ist ein gültiges Ergebnis. Diese Tests bauen die Dateien
deshalb selbst nach der dokumentierten Beschreibung und prüfen den Rundlauf.

Zusätzlich wird gegen den echten heruntergeladenen Bestand geprüft, sofern
einer vorliegt. Nur das beweist, dass die Nachbildung der Hashfunktion mit der
Vorlage übereinstimmt.
"""
import json
import struct
import tempfile
import unittest
from pathlib import Path

import labels


def baue_filter(adressen: list[str], *, m: int = 4096, k: int = 10) -> bytes:
    """Erzeugt eine Filterdatei nach der Beschreibung im Modulkopf."""
    bits = bytearray((m + 7) // 8)
    for adresse in adressen:
        h1 = labels._fnv1a(adresse, 2166136261)
        h2 = labels._fnv1a(adresse, 2654435761)
        for i in range(k):
            pos = (h1 + i * h2) % m
            bits[pos >> 3] |= 1 << (pos & 7)

    datum = b"2026-05-11T20:26".ljust(16, b"\x00")
    kopf = struct.pack("<IIII", 2, len(adressen), 1, 16) + datum
    parameter = struct.pack("<IIII", m, k, 2166136261, 2654435761)
    return kopf + parameter + bytes(bits)


def baue_index(eintraege: list[tuple[str, str, str]]) -> bytes:
    """eintraege: (adresse, entitaetsname, kategorie)."""
    namen: list[tuple[str, str]] = []
    zeilen = []
    for adresse, name, kategorie in eintraege:
        paar = (name, kategorie)
        if paar not in namen:
            namen.append(paar)
        zeilen.append((labels._fnv1a(adresse, 2166136261), namen.index(paar)))
    zeilen.sort()

    tabelle = bytearray()
    for name, kategorie in namen:
        roh = name.encode("utf-8")
        tabelle += bytes([len(roh)]) + roh
        tabelle += bytes([labels._KATEGORIE_BYTES.index(kategorie)])

    kopf = (b"EIDX" + struct.pack("<II", 2, len(zeilen))
            + struct.pack("<H", len(namen)) + struct.pack("<I", 2166136261)
            + struct.pack("<H", 0))
    koerper = b"".join(struct.pack("<IH", h, e) for h, e in zeilen)
    return kopf + bytes(tabelle) + koerper


class TestRundlauf(unittest.TestCase):
    """Selbst geschriebene Dateien müssen sich selbst wiederfinden."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        labels._geladen.clear()

        self.bekannt = ["1BoerseAAA", "bc1qmineraaa", "3MixerAAA"]
        (self.dir / labels.FILTER_NAME).write_bytes(baue_filter(self.bekannt))
        (self.dir / labels.INDEX_NAME).write_bytes(baue_index([
            ("1BoerseAAA", "Kraken", "exchange"),
            ("bc1qmineraaa", "F2Pool", "mining"),
            ("3MixerAAA", "ChipMixer", "mixer"),
        ]))
        (self.dir / labels.ENTITIES_NAME).write_text(json.dumps({
            "entities": [
                {"name": "Kraken", "category": "exchange",
                 "country": "US", "status": "active", "ofac": False},
            ]
        }), encoding="utf-8")

    def test_bekannte_adresse_wird_benannt(self):
        treffer = labels.beschrifte("1BoerseAAA", self.dir)
        self.assertEqual(treffer["name"], "Kraken")
        self.assertEqual(treffer["kategorie"], "exchange")
        self.assertEqual(treffer["kategorie_label"], "Börse")
        self.assertEqual(treffer["land"], "US")

    def test_kategorie_kommt_auch_ohne_entities_json(self):
        """Der Index trägt sie selbst — entities.json ergänzt nur."""
        treffer = labels.beschrifte("bc1qmineraaa", self.dir)
        self.assertEqual(treffer["kategorie_label"], "Mining-Pool")

    def test_unbekannte_adresse_bleibt_ohne_label(self):
        self.assertIsNone(labels.beschrifte("1Unbekannt999", self.dir))

    def test_ohne_bestand_kein_fehler(self):
        with tempfile.TemporaryDirectory() as leer:
            self.assertIsNone(labels.beschrifte("1BoerseAAA", Path(leer)))
            self.assertFalse(labels.status(Path(leer))["vorhanden"])

    def test_bech32_wird_unabhaengig_von_der_schreibweise_gefunden(self):
        """Bech32 ist schreibweise-unabhängig, Base58 nicht."""
        self.assertIsNotNone(labels.beschrifte("BC1QMINERAAA", self.dir))

    def test_base58_wird_nicht_kleingeschrieben(self):
        self.assertIsNone(labels.beschrifte("1boerseaaa", self.dir))

    def test_status_nennt_umfang_und_stand(self):
        stand = labels.status(self.dir)
        self.assertTrue(stand["vorhanden"])
        self.assertEqual(stand["adressen"], 3)
        self.assertEqual(stand["stand"], "2026-05-11")

    def test_verwerfen_entfernt_den_bestand(self):
        self.assertTrue(labels.verwirf(self.dir))
        self.assertFalse(labels.status(self.dir)["vorhanden"])


class TestWiderspruechlicherBestand(unittest.TestCase):
    """
    Beim Vollbestand des Anbieters stammen Filter und Index aus verschiedenen
    Läufen: Der Index kennt Adressen, die der Filter verneint. Wer den Filter
    vorschaltet, verliert genau diese Namen — von 321 bekannten Adressen
    blieben zwei übrig. Der Index gibt deshalb den Ausschlag.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        labels._geladen.clear()
        # Der Filter kennt nur eine andere Adresse — die gesuchte fehlt ihm.
        (self.dir / labels.FILTER_NAME).write_bytes(baue_filter(["1EtwasAnderes"]))
        (self.dir / labels.INDEX_NAME).write_bytes(
            baue_index([("1NurImIndex", "Bitstamp", "exchange")])
        )

    def test_name_aus_dem_index_gilt_auch_ohne_filtertreffer(self):
        treffer = labels.beschrifte("1NurImIndex", self.dir)
        self.assertIsNotNone(treffer, "Der Filter darf den Index nicht ausbremsen.")
        self.assertEqual(treffer["name"], "Bitstamp")

    def test_filtertreffer_ohne_namen_bleibt_unbenannt(self):
        treffer = labels.beschrifte("1EtwasAnderes", self.dir)
        self.assertIsNotNone(treffer)
        self.assertFalse(treffer["benannt"])

    def test_was_keiner_von_beiden_kennt_bleibt_ohne_label(self):
        self.assertIsNone(labels.beschrifte("1VoelligUnbekannt", self.dir))


class TestEinordnung(unittest.TestCase):
    """
    Nicht jeder Name im Bestand ist ein Dienst. Ein Eintrag „BitcoinTalk"
    bedeutet, dass die Adresse dort einmal gepostet wurde — daraus „Börse
    BitcoinTalk" zu machen, wäre eine erfundene Zuordnung.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        labels._geladen.clear()
        adressen = ["1ForumAAA", "1RansomAAA"]
        (self.dir / labels.FILTER_NAME).write_bytes(baue_filter(adressen))
        (self.dir / labels.INDEX_NAME).write_bytes(baue_index([
            ("1ForumAAA", "BitcoinTalk", "exchange"),
            ("1RansomAAA", "Ransomwhere", "unknown"),
        ]))

    def test_forenerwaehnung_ist_keine_boerse(self):
        treffer = labels.beschrifte("1ForumAAA", self.dir)
        self.assertEqual(treffer["art"], "erwaehnung")
        self.assertEqual(treffer["kategorie_label"], "öffentlich erwähnt")

    def test_ransomware_behaelt_ihre_bedeutung(self):
        treffer = labels.beschrifte("1RansomAAA", self.dir)
        self.assertEqual(treffer["art"], "dienst")
        self.assertEqual(treffer["kategorie_label"], "Ransomware-Zahlung")


BESTAND_DA = (labels.LABEL_CACHE_DIR / labels.FILTER_NAME).exists()


@unittest.skipUnless(BESTAND_DA, "Kein heruntergeladener Bestand vorhanden")
class TestGegenEchtenBestand(unittest.TestCase):
    """
    Der eigentliche Beweis: Die hier nachgebaute Hashfunktion muss dieselben
    Bitpositionen treffen wie die Vorlage. Stimmt auch nur der Startwert
    nicht, findet der Filter keine einzige der bekannten Adressen.
    """

    @classmethod
    def setUpClass(cls):
        labels._geladen.clear()
        cls.bestand = labels.lade()
        cls.entitaeten = json.loads(
            (labels.LABEL_CACHE_DIR / labels.ENTITIES_NAME).read_text(encoding="utf-8")
        )["entities"]

    def test_bekannte_boersen_werden_gefunden(self):
        gesucht = {"Binance", "Coinbase", "Kraken", "Bitfinex"}
        for eintrag in self.entitaeten:
            if eintrag["name"] not in gesucht:
                continue
            adresse = eintrag["sampleAddresses"][0]
            treffer = self.bestand.suche(adresse)
            self.assertIsNotNone(treffer, f"{eintrag['name']} nicht gefunden")
            self.assertEqual(treffer["name"], eintrag["name"])
            self.assertEqual(treffer["kategorie"], "exchange")

    def test_erfundene_adressen_treffen_praktisch_nie(self):
        """
        Bloom-Filter: erfundene Adressen dürfen nur selten treffen.

        Der am-i.exposed-Bestand liegt bei grob 1–3 % Falschpositivrate
        (nicht 0,1 %). Bei 2.000 Proben sind zweistellige Treffer normal;
        Hunderte/Tausende wären ein kaputter Hash / Index.
        """
        treffer = sum(
            1 for i in range(2000)
            if self.bestand.suche(f"bc1qerfunden{i:08d}satsage")
        )
        self.assertLess(
            treffer,
            100,
            f"{treffer} Falschtreffer bei 2.000 Proben — Filter verdächtig",
        )


if __name__ == "__main__":
    unittest.main()
