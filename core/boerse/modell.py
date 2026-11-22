"""Normalisierte Börsenbuchung. Lose werden hier nicht gespeichert."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Art(StrEnum):
    KAUF = "kauf"
    VERKAUF = "verkauf"
    BTC_EINGANG = "btc_eingang"
    BTC_AUSGANG = "btc_ausgang"
    GEBUEHR = "gebuehr"
    FIAT_EIN = "fiat_ein"
    FIAT_AUS = "fiat_aus"
    INTERN = "intern"
    QUARANTAENE = "quarantaene"


@dataclass(frozen=True)
class Buchung:
    """Eine normalisierte Zeile oder ein Zeilenpaar. Nur Importfakten."""

    konto: str
    ref: str
    gruppe: str | None
    zeit_ts: int | None
    zeit_zone_belegt: bool
    art: Art
    sats: int
    gebuehr_sats: int
    fiat: Decimal | None
    fiat_gebuehr: Decimal | None
    waehrung: str | None
    kurs: Decimal | None
    txid: str | None
    adresse: str | None
    lightning: bool
    roh_typ: str
    roh_subtyp: str | None
    datei: str
    zeile: int


@dataclass(frozen=True)
class Quarantaene:
    """Eine nicht zuordenbare Zeile. Ohne Rohinhalt, Beträge oder IDs."""

    zeile: int
    grund: str
    roh_typ: str | None
    datei: str
    ref: str | None = None
    spalte: str | None = None


@dataclass(frozen=True)
class ParseErgebnis:
    buchungen: tuple[Buchung, ...]
    quarantaene: tuple[Quarantaene, ...]
    variante: str
    datei_hash: str


@dataclass(frozen=True)
class Zuordnung:
    """Auszahlung ↔ On-Chain-Empfang. Nur Erklärung, bis Stufe 2 das Datum ändert."""

    konto: str
    auszahlung_ref: str
    txid: str
    vout: int
    sats_onchain: int
    methode: str  # txid_exakt | betrag_zeit | adresse | manuell
    status: str  # vorschlag | bestaetigt | abgelehnt
    bestaetigt_ts: int | None = None
    #: txid_exakt | auto | manuell — nur bei status bestaetigt relevant.
    bestaetigt_durch: str | None = None
    #: Kurzer Grund, warum automatisch bestätigt wurde. Ohne Kennungen.
    auto_grund: str | None = None


class FormatFehler(ValueError):
    """Unbekannter oder unbrauchbarer Kopf. Nennt Spalten, keine Werte."""

    def __init__(self, grund: str, spalten: tuple[str, ...] = ()):
        self.grund = grund
        self.spalten = tuple(spalten)
        if spalten:
            super().__init__(f"{grund}: {', '.join(spalten)}")
        else:
            super().__init__(grund)
