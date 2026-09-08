#!/usr/bin/env python3
"""
Adress-Labels: zu wem eine fremde Adresse gehört.

Beim Verfolgen der Herkunft endet ein Zweig irgendwann bei einer fremden
Adresse. „Fremd" allein sagt wenig — ob die Sats von einer Börse, einem
Mining-Pool oder einem Darknet-Markt kamen, ist der eigentlich interessante
Teil. Dieses Modul beantwortet genau diese Frage aus einem lokalen Datenbestand.

**Die Abfrage bleibt auf diesem Rechner.** Eine Online-Abfrage „wem gehört
diese Adresse" würde einem Dritten verraten, welche Adressen den Benutzer
interessieren — also genau das, was das Werkzeug sonst schützt. Deshalb wird
der gesamte Bestand einmal heruntergeladen und danach nur noch lokal gelesen.

Datenherkunft
-------------
Die Dateien stammen aus dem Projekt am-i.exposed (MIT-Lizenz,
github.com/Copexit/am-i-exposed). Deren Massendaten gehen auf eine Erhebung
von WalletExplorer aus **April 2018** zurück. Das ist die wichtigste
Einschränkung: Börsen vergeben laufend neue Einzahlungsadressen, ein Abgang
von 2024 steht dort nicht. Nützlich ist der Bestand bei alten Herkunftsketten,
Mining-Pools und historischen Diensten. Jedes Ergebnis trägt diesen Stand
deshalb mit sich, damit ein Treffer nicht wie eine aktuelle Feststellung
aussieht.

Genauigkeit
-----------
Beide Bestandteile sind fehlbar, jeder auf seine Art. Der Namensindex bildet
Adressen auf 4-Byte-Hashes ab; eine unbekannte Adresse trifft mit etwa
1:15.000 zufällig einen fremden Eintrag. Der Bloom-Filter hat eine
eingestellte Falsch-Positiv-Rate von 0,1 %, benennt dafür aber nichts — er
liefert nur „gehört zu einem erfassten Dienst".

Ein Ergebnis ist damit ein begründeter Hinweis, keine Feststellung. Die
Oberfläche formuliert es entsprechend und nennt immer die Quelle.

Format
------
Beides sind einfache Binärdateien; die Beschreibung folgt dem Erzeuger.

``entity-filter.bin``
    Kopf (32 B): version(4) adressen(4) fpr*1000(4) datumLaenge(4) datum(16)
    Parameter (16 B): m(4) k(4) seed1(4) seed2(4)
    danach das Bitfeld, ceil(m/8) Bytes.

``entity-index.bin``
    Kopf (20 B): "EIDX" version(4) eintraege(4) namen(2) seed(4) reserviert(2)
    Namenstabelle: je Name laenge(1) + UTF-8 + kategorie(1)
    Einträge: je hash(4, LE) + entitaet(2, LE), nach hash aufsteigend sortiert.
"""
from __future__ import annotations

import json
import struct
import time
import urllib.request

from core.import_limits import ImportBudget, add_direct_file, unpack_zip_limited
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc

LABEL_CACHE_DIR = Path(__file__).resolve().parent / "label_cache"

# Feste Fassung statt „main": Die Dateien sollen sich nicht unter der Hand
# ändern. Für eine neuere Ausgabe wird hier bewusst nachgezogen.
_QUELLE_ZWEIG = "main"
_QUELLE_BASIS = (
    f"https://raw.githubusercontent.com/Copexit/am-i-exposed/{_QUELLE_ZWEIG}"
)
QUELLE_NAME = "am-i.exposed"
QUELLE_URL = "https://github.com/Copexit/am-i-exposed"

FILTER_NAME = "entity-filter.bin"
INDEX_NAME = "entity-index.bin"
ENTITIES_NAME = "entities.json"
META_NAME = "labels.meta.json"

# Zwei Ausbaustufen. Der Kern benennt fast jede seiner Adressen; die volle
# Fassung kennt zwar 20 Millionen, benennt davon aber nur einen Bruchteil —
# für den Rest lautet die Antwort „bekannter Dienst" ohne Namen.
VARIANTEN = {
    "kern": {
        FILTER_NAME: f"{_QUELLE_BASIS}/public/data/entity-filter.bin",
        INDEX_NAME: f"{_QUELLE_BASIS}/public/data/entity-index.bin",
        ENTITIES_NAME: f"{_QUELLE_BASIS}/src/data/entities.json",
    },
    "voll": {
        FILTER_NAME: f"{_QUELLE_BASIS}/public/data/entity-filter-full.bin",
        INDEX_NAME: f"{_QUELLE_BASIS}/public/data/entity-index-full.bin",
        ENTITIES_NAME: f"{_QUELLE_BASIS}/src/data/entities.json",
    },
}
VARIANTEN_LABELS = {
    "kern": "Kernbestand — 1,7 MB, rund 187.000 benannte Adressen",
    "voll": "Vollbestand — 37 MB, rund 276.000 benannte Adressen",
}

DATEN_HINWEIS = (
    "Die Zuordnung beruht auf einer Erhebung von WalletExplorer aus dem Jahr "
    "2018. Börsen vergeben laufend neue Einzahlungsadressen — ein Zufluss aus "
    "den letzten Jahren steht dort meist nicht. Ein Treffer ist ein Hinweis, "
    "keine Feststellung."
)

KATEGORIE_LABELS = {
    "exchange": "Börse",
    "darknet": "Darknet-Markt",
    "scam": "Betrug",
    "gambling": "Glücksspiel",
    "payment": "Zahlungsdienst",
    "mining": "Mining-Pool",
    "mixer": "Mixer",
    "p2p": "P2P-Börse",
    "ransomware": "Ransomware-Zahlung",
    "erwaehnung": "öffentlich erwähnt",
    "unknown": "unbekannt",
}

# Nicht jeder Name im Bestand ist ein Dienst. Ein knappes Drittel der Einträge
# stammt aus Forenauswertungen: „BitcoinTalk" heißt nur, dass die Adresse dort
# einmal gepostet wurde — nicht, dass sie jemandem gehört. Als „Börse
# BitcoinTalk" angezeigt wäre das schlicht falsch, deshalb bekommen diese
# Einträge eine eigene Art und eine andere Formulierung.
_ERWAEHNUNGEN = {"bitcointalk", "reddit", "collectibles"}

# Umgekehrt: Diese Herkunft ist eine echte Zuordnung, steht aber nicht in
# entities.json und käme sonst ohne Kategorie an.
_SONDERKATEGORIEN = {"ransomwhere": "ransomware"}
_KATEGORIE_BYTES = ("exchange", "darknet", "scam", "gambling",
                    "payment", "mining", "mixer", "p2p", "unknown")

_USER_AGENT = "SatSage/1.0"
_FNV_PRIME = 16777619
_MASKE = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _fnv1a(text: str, seed: int) -> int:
    """
    FNV-1a, 32 Bit, mit dem Startwert als Basis.

    Bitgleich zur Vorlage in JavaScript: Dort rechnet ``Math.imul`` im
    vorzeichenbehafteten 32-Bit-Bereich, hier wird nach jedem Schritt
    maskiert. Das Bitmuster ist dasselbe, nur die Lesart unterscheidet sich.
    """
    h = seed
    for zeichen in text:
        h ^= ord(zeichen)
        h = (h * _FNV_PRIME) & _MASKE
    return h


def normalisiere(adresse: str) -> str:
    """
    Bech32 wird kleingeschrieben, Base58 bleibt unverändert.

    Bech32 ist unabhängig von der Groß-/Kleinschreibung, Base58 nicht — dort
    wäre ein Kleinschreiben eine andere Adresse.
    """
    adresse = (adresse or "").strip()
    if adresse[:3].lower() in ("bc1", "tb1"):
        return adresse.lower()
    return adresse


# ---------------------------------------------------------------------------
# Bloom-Filter
# ---------------------------------------------------------------------------


@dataclass
class Bloomfilter:
    """Sagt zuverlässig „nein", mit kleiner Fehlerrate „ja"."""

    m: int
    k: int
    seed1: int
    seed2: int
    bits: bytes
    adressen: int
    fpr: float
    gebaut: str

    def enthaelt(self, schluessel: str) -> bool:
        h1 = _fnv1a(schluessel, self.seed1)
        h2 = _fnv1a(schluessel, self.seed2)
        for i in range(self.k):
            pos = (h1 + i * h2) % self.m
            if not self.bits[pos >> 3] & (1 << (pos & 7)):
                return False
        return True


def _lies_filter(pfad: Path) -> Bloomfilter:
    roh = pfad.read_bytes()
    if len(roh) < 48:
        raise ValueError(f"{pfad.name} ist zu kurz für einen Kopf.")

    version, adressen, fpr_mal_1000, datum_laenge = struct.unpack_from("<IIII", roh, 0)
    if version != 2:
        raise ValueError(f"{pfad.name}: unbekannte Fassung {version}.")
    datum = roh[16:16 + min(datum_laenge, 16)].split(b"\x00")[0].decode("ascii", "replace")
    m, k, seed1, seed2 = struct.unpack_from("<IIII", roh, 32)

    erwartet = 48 + (m + 7) // 8
    if len(roh) < erwartet:
        raise ValueError(
            f"{pfad.name}: Bitfeld unvollständig — {len(roh)} statt {erwartet} Bytes."
        )
    return Bloomfilter(
        m=m, k=k, seed1=seed1, seed2=seed2, bits=roh[48:],
        adressen=adressen, fpr=fpr_mal_1000 / 1000, gebaut=datum,
    )


# ---------------------------------------------------------------------------
# Namensindex
# ---------------------------------------------------------------------------


@dataclass
class Namensindex:
    """Hash einer Adresse → Name und Kategorie der Entität."""

    namen: list[tuple[str, str]]
    hashes: list[int]
    ids: list[int]
    seed: int

    def suche(self, schluessel: str) -> tuple[str, str] | None:
        gesucht = _fnv1a(schluessel, self.seed)
        stelle = bisect_left(self.hashes, gesucht)
        if stelle >= len(self.hashes) or self.hashes[stelle] != gesucht:
            return None
        eintrag = self.ids[stelle]
        if eintrag >= len(self.namen):
            return None
        return self.namen[eintrag]


def _lies_index(pfad: Path) -> Namensindex:
    roh = pfad.read_bytes()
    if roh[:4] != b"EIDX":
        raise ValueError(f"{pfad.name}: kein Namensindex (Kennung fehlt).")
    version, anzahl = struct.unpack_from("<II", roh, 4)
    if version != 2:
        raise ValueError(f"{pfad.name}: unbekannte Fassung {version}.")
    namen_anzahl = struct.unpack_from("<H", roh, 12)[0]
    seed = struct.unpack_from("<I", roh, 14)[0]

    stelle = 20
    namen: list[tuple[str, str]] = []
    for _ in range(namen_anzahl):
        laenge = roh[stelle]
        name = roh[stelle + 1:stelle + 1 + laenge].decode("utf-8", "replace")
        kategorie_byte = roh[stelle + 1 + laenge]
        kategorie = (_KATEGORIE_BYTES[kategorie_byte]
                     if kategorie_byte < len(_KATEGORIE_BYTES) else "unknown")
        namen.append((name, kategorie))
        stelle += laenge + 2

    # Getrennte Listen statt Tupel-Liste: bisect sucht so direkt auf den
    # Hashes, ohne für jeden Vergleich ein Tupel anzufassen.
    hashes: list[int] = []
    ids: list[int] = []
    for _ in range(anzahl):
        wert, eintrag = struct.unpack_from("<IH", roh, stelle)
        hashes.append(wert)
        ids.append(eintrag)
        stelle += 6

    return Namensindex(namen=namen, hashes=hashes, ids=ids, seed=seed)


# ---------------------------------------------------------------------------
# Verzeichnis
# ---------------------------------------------------------------------------


@dataclass
class Labelverzeichnis:
    """Der geladene Bestand — Filter, Namen und Zusatzangaben."""

    filter: Bloomfilter
    index: Namensindex
    entitaeten: dict[str, dict] = field(default_factory=dict)
    variante: str = "kern"
    geladen: str = ""

    @property
    def stand(self) -> str:
        return self.filter.gebaut[:10]

    def suche(self, adresse: str) -> dict | None:
        """
        Liefert das Label einer Adresse oder None.

        ``benannt=False`` heißt: Die Adresse gehört zu einem erfassten Dienst,
        der Bestand kennt aber seinen Namen nicht. Das ist bei der vollen
        Fassung der Regelfall und wird bewusst nicht verschwiegen.
        """
        schluessel = normalisiere(adresse)
        if not schluessel:
            return None

        # Zuerst der Namensindex, dann der Filter — und nicht umgekehrt.
        #
        # Naheliegender wäre, den Filter vorzuschalten und den Index nur bei
        # einem Treffer zu befragen. Beim Vollbestand geht das schief: Dessen
        # Filter (Ausgabe 03/2026) und Index stammen aus verschiedenen Läufen
        # und widersprechen sich. Von 321 bekannten Beispieladressen kennt der
        # Index 203, der Filter nur 2. Vorgeschaltet würde er also fast alle
        # Namen wegwerfen, die daneben stehen.
        #
        # Preis dieser Reihenfolge: Der Index bildet Adressen auf 4-Byte-Hashes
        # ab. Eine unbekannte Adresse trifft mit rund 1:15.000 zufällig einen
        # fremden Eintrag und bekäme dessen Namen. Selten, aber nicht nie —
        # deshalb heißt es in der Anzeige „Hinweis", nicht „Feststellung".
        treffer = self.index.suche(schluessel)
        if treffer is None:
            if not self.filter.enthaelt(schluessel):
                return None
        name, kategorie = treffer if treffer else ("", "unknown")
        schlicht = name.lower()

        # entities.json ist die bessere Quelle für die Kategorie: Im Index
        # steht bei mehreren großen Diensten nur „unknown".
        zusatz = self.entitaeten.get(schlicht, {}) if name else {}
        if zusatz.get("category"):
            kategorie = zusatz["category"]
        elif schlicht in _SONDERKATEGORIEN:
            kategorie = _SONDERKATEGORIEN[schlicht]

        art = "erwaehnung" if schlicht in _ERWAEHNUNGEN else "dienst"
        if art == "erwaehnung":
            kategorie = "erwaehnung"

        return {
            "name": name,
            "benannt": bool(name),
            "art": art,
            "kategorie": kategorie,
            "kategorie_label": KATEGORIE_LABELS.get(kategorie, kategorie),
            "land": zusatz.get("country", ""),
            "status": zusatz.get("status", ""),
            "ofac": bool(zusatz.get("ofac")),
            "quelle": QUELLE_NAME,
            "stand": self.stand,
            "hinweis": DATEN_HINWEIS,
        }


def _lies_entitaeten(pfad: Path) -> dict[str, dict]:
    if not pfad.exists():
        return {}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(e.get("name", "")).lower(): e
        for e in daten.get("entities", [])
        if e.get("name")
    }


# Einmal lesen, dann behalten: Das volle Bitfeld sind 35 MB, die bei jeder
# Adresse neu zu laden wäre sinnlos. Der Schlüssel enthält Größe und
# Änderungszeit, damit ein neuer Download sofort greift.
_geladen: dict[tuple, Labelverzeichnis] = {}


# Wo der Bestand liegt, wenn kein Verzeichnis mitgegeben wird. Die
# Beschriftung passiert tief in der Auswertung — den Pfad durch jede Ebene
# durchzureichen wäre viel Beiwerk für eine Angabe, die sich pro Lauf nie
# ändert. Der Server setzt ihn beim Start, sonst gilt das Verzeichnis im
# Projektordner.
_aktives_verzeichnis: Path | None = None


def setze_verzeichnis(pfad: Path | None) -> None:
    global _aktives_verzeichnis
    _aktives_verzeichnis = Path(pfad) if pfad else None
    _geladen.clear()


def _verzeichnis(cache_dir: Path | None) -> Path:
    if cache_dir:
        return Path(cache_dir)
    return _aktives_verzeichnis or LABEL_CACHE_DIR


def _kennung(cache_dir: Path) -> tuple | None:
    try:
        pfade = [cache_dir / FILTER_NAME, cache_dir / INDEX_NAME]
        return tuple(
            (p.name, p.stat().st_size, int(p.stat().st_mtime)) for p in pfade
        )
    except OSError:
        return None


def lade(cache_dir: Path | None = None) -> Labelverzeichnis | None:
    """Lädt den Bestand — oder None, wenn keiner heruntergeladen wurde."""
    verzeichnis = _verzeichnis(cache_dir)
    kennung = _kennung(verzeichnis)
    if kennung is None:
        return None
    if kennung in _geladen:
        return _geladen[kennung]

    try:
        bestand = Labelverzeichnis(
            filter=_lies_filter(verzeichnis / FILTER_NAME),
            index=_lies_index(verzeichnis / INDEX_NAME),
            entitaeten=_lies_entitaeten(verzeichnis / ENTITIES_NAME),
        )
    except (OSError, ValueError, struct.error, IndexError):
        # Eine kaputte Datei darf die Auswertung nicht anhalten; ohne Labels
        # ist das Werkzeug vollständig benutzbar.
        return None

    meta = _lies_meta(verzeichnis)
    bestand.variante = meta.get("variante", "kern")
    bestand.geladen = meta.get("geladen", "")
    _geladen.clear()
    _geladen[kennung] = bestand
    return bestand


def beschrifte(adresse: str, cache_dir: Path | None = None) -> dict | None:
    """Bequemer Einzelaufruf — None, wenn nichts bekannt ist."""
    bestand = lade(cache_dir)
    return bestand.suche(adresse) if bestand else None


# ---------------------------------------------------------------------------
# Herunterladen und Zustand
# ---------------------------------------------------------------------------


def _meta_pfad(cache_dir: Path) -> Path:
    return cache_dir / META_NAME


def _lies_meta(cache_dir: Path) -> dict:
    try:
        return json.loads(_meta_pfad(cache_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _hole(url: str, ziel: Path, fortschritt=None) -> int:
    """Lädt eine Datei über eine .tmp, damit nie ein halber Stand liegen bleibt."""
    from core.tls import ssl_context

    anfrage = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    tmp = ziel.with_suffix(ziel.suffix + ".tmp")
    geladen = 0
    # context=…: Framework-Python ohne CA-Bündel sonst CERTIFICATE_VERIFY_FAILED.
    with urllib.request.urlopen(
        anfrage, timeout=120, context=ssl_context()
    ) as antwort:
        gesamt = int(antwort.headers.get("Content-Length") or 0)
        with tmp.open("wb") as datei:
            while True:
                block = antwort.read(65536)
                if not block:
                    break
                datei.write(block)
                geladen += len(block)
                if fortschritt:
                    fortschritt(ziel.name, geladen, gesamt)
    tmp.replace(ziel)
    return geladen

def aktualisiere(cache_dir: Path | None = None, *, variante: str = "kern",
                 fortschritt=None) -> dict:
    """
    Lädt den gewählten Bestand herunter.

    ``fortschritt(dateiname, geladen, gesamt)`` wird währenddessen gerufen.
    Gibt die Angaben zurück, die auch in der Oberfläche erscheinen.
    """
    if variante not in VARIANTEN:
        raise ValueError(f"Unbekannte Variante: {variante}")

    verzeichnis = _verzeichnis(cache_dir)
    verzeichnis.mkdir(parents=True, exist_ok=True)

    groessen = {}
    for name, url in VARIANTEN[variante].items():
        groessen[name] = _hole(url, verzeichnis / name, fortschritt)

    meta = {
        "variante": variante,
        "geladen": datetime.now(UTC).isoformat(timespec="seconds"),
        "geladen_ts": int(time.time()),
        "quelle": QUELLE_NAME,
        "quelle_url": QUELLE_URL,
        "dateien": groessen,
    }
    _meta_pfad(verzeichnis).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _geladen.clear()
    return status(verzeichnis)


def verwirf(cache_dir: Path | None = None) -> bool:
    """Entfernt den Bestand wieder — 35 MB will nicht jeder liegen haben."""
    verzeichnis = _verzeichnis(cache_dir)
    entfernt = False
    for name in (FILTER_NAME, INDEX_NAME, ENTITIES_NAME, META_NAME):
        pfad = verzeichnis / name
        if pfad.exists():
            pfad.unlink()
            entfernt = True
    _geladen.clear()
    return entfernt


def _norm_dateiname(name: str) -> str:
    return Path(name or "").name.lower().replace("\\", "/")


def _map_import_dateien(roh: dict[str, bytes]) -> tuple[dict[str, bytes], str]:
    """
    Ordnet Dateinamen den kanonischen Cache-Dateien zu.

    Erlaubt Kern- und Voll-Namen sowie ZIP mit denselben Dateien.
    """
    flach: dict[str, bytes] = {}
    budget = ImportBudget()
    for name, inhalt in roh.items():
        n = _norm_dateiname(name)
        if n.endswith(".zip"):
            for dateiname, dateiinhalt in unpack_zip_limited(inhalt, budget=budget):
                flach[_norm_dateiname(dateiname)] = dateiinhalt
        else:
            add_direct_file(budget, name, inhalt)
            flach[n] = inhalt

    ziel: dict[str, bytes] = {}
    variante = "kern"
    for name, inhalt in flach.items():
        basis = Path(name).name
        if basis in (FILTER_NAME, "entity-filter-full.bin"):
            ziel[FILTER_NAME] = inhalt
            if "full" in basis:
                variante = "voll"
        elif basis in (INDEX_NAME, "entity-index-full.bin"):
            ziel[INDEX_NAME] = inhalt
            if "full" in basis:
                variante = "voll"
        elif basis == ENTITIES_NAME:
            ziel[ENTITIES_NAME] = inhalt
    return ziel, variante


def importiere_dateien(
    dateien: dict[str, bytes],
    cache_dir: Path | None = None,
    *,
    variante: str | None = None,
) -> dict:
    """
    Übernimmt lokal beschaffte Label-Dateien (Filter, Index, entities.json).

    ``dateien``: Dateiname → Bytes. ZIP erlaubt. Nach dem Schreiben wird
    geladen/validiert — kaputte Dateien werden abgewiesen.
    """
    if not dateien:
        raise ValueError("Keine Dateien übergeben.")

    mapped, erkannt = _map_import_dateien(dateien)
    if FILTER_NAME not in mapped or INDEX_NAME not in mapped:
        raise ValueError(
            "Mindestens entity-filter.bin und entity-index.bin "
            "(oder *-full.bin) werden benötigt."
        )
    if ENTITIES_NAME not in mapped:
        # entities.json ist optional fürs Laden, aber nützlich
        mapped[ENTITIES_NAME] = b"{}\n"

    gewaehlt = variante if variante in VARIANTEN else erkannt
    verzeichnis = _verzeichnis(cache_dir)
    verzeichnis.mkdir(parents=True, exist_ok=True)

    groessen: dict[str, int] = {}
    for name, inhalt in mapped.items():
        pfad = verzeichnis / name
        tmp = pfad.with_suffix(pfad.suffix + ".tmp")
        tmp.write_bytes(inhalt)
        tmp.replace(pfad)
        groessen[name] = len(inhalt)

    meta = {
        "variante": gewaehlt,
        "geladen": datetime.now(UTC).isoformat(timespec="seconds"),
        "geladen_ts": int(time.time()),
        "quelle": "manueller Import",
        "quelle_url": "",
        "dateien": groessen,
    }
    _meta_pfad(verzeichnis).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _geladen.clear()
    stand = status(verzeichnis)
    if not stand.get("vorhanden"):
        # Kaputte Dateien nicht liegen lassen
        verwirf(verzeichnis)
        raise ValueError(
            "Dateien ließen sich nicht als Labelbestand lesen "
            "(Format/Version prüfen)."
        )
    return stand


def status(cache_dir: Path | None = None) -> dict:
    """Was liegt vor — für die Anzeige in den Einstellungen."""
    verzeichnis = _verzeichnis(cache_dir)
    bestand = lade(verzeichnis)
    if bestand is None:
        return {
            "vorhanden": False,
            "hinweis": DATEN_HINWEIS,
            "quelle": QUELLE_NAME,
            "quelle_url": QUELLE_URL,
            "varianten": [
                {"wert": k, "label": VARIANTEN_LABELS[k]} for k in VARIANTEN
            ],
        }

    meta = _lies_meta(verzeichnis)
    return {
        "vorhanden": True,
        "variante": bestand.variante,
        "variante_label": VARIANTEN_LABELS.get(bestand.variante, ""),
        "adressen": bestand.filter.adressen,
        "benannt": len(bestand.index.hashes),
        "entitaeten": len(bestand.index.namen),
        "fpr": bestand.filter.fpr,
        "stand": bestand.stand,
        "geladen": meta.get("geladen", ""),
        "groesse": sum(meta.get("dateien", {}).values()),
        "hinweis": DATEN_HINWEIS,
        "quelle": QUELLE_NAME,
        "quelle_url": QUELLE_URL,
        "varianten": [
            {"wert": k, "label": VARIANTEN_LABELS[k]} for k in VARIANTEN
        ],
    }
