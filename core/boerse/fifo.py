"""Börsen-FIFO je Konto: einzelne Lose, kein Durchschnittspreis.

Die Lose hängen an bestätigten Auszahlungen. Anschaffungszeit und
Einzelkaufpreis stammen aus den Importfakten der Börsenhistorie
(BMF-Schreiben 6. März 2025, Rn. 20/55/61). Der Bericht kennzeichnet
sie als Börsenbeleg; On-Chain-Datum und Lot-Farbe bleiben unverändert.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from core.boerse.modell import Art, Buchung
from core.fifo_lots import Los, ordnen, verteilen
from core.log_redaktion import groessenordnung, schreibe

FIAT_WAEHRUNGEN = frozenset({"EUR", "USD"})
SATOSHIS_JE_BTC = Decimal(100_000_000)
_KOSTEN_QUANT = Decimal("0.00000001")
_PREIS_QUANT = Decimal("0.00000001")

_ANZEIGE = {
    "kraken": "Kraken",
    "coinbase": "Coinbase",
    "strike": "Strike",
}


class FifoFehler(ValueError):
    """Bestand reicht für Verkauf, Auszahlung oder Gebühr nicht."""

    def __init__(self, grund: str, *, zeile: int | None = None, art: str | None = None):
        super().__init__(grund)
        self.grund = grund
        self.zeile = zeile
        self.art = art


@dataclass(frozen=True)
class BoerseLos:
    """Ein FIFO-Anteil. Der Einzelkaufpreis gilt für genau dieses Los."""

    sats: int
    zeit_ts: int | None
    konto: str
    boerse: str
    kauf_art: str
    einzelpreis_btc: Decimal | None
    waehrung: str | None
    kosten: Decimal | None

    def label(self) -> str:
        name = (self.boerse or "").strip() or "Börse"
        return f"laut {name}"


def anzeige_name(konto: str | None, boerse_typ: str | None = None, *, name: str | None = None) -> str:
    """Anzeigename für die Spalte, z. B. „Kraken“."""
    if name and str(name).strip():
        return str(name).strip()
    roh = (boerse_typ or konto or "").strip()
    schluessel = roh.split("-")[0].casefold()
    if schluessel in _ANZEIGE:
        return _ANZEIGE[schluessel]
    if roh:
        return roh[:1].upper() + roh[1:]
    return "Börse"


def waehrung_ok(waehrung: str | None) -> bool:
    return (waehrung or "").strip().upper() in FIAT_WAEHRUNGEN


def nimm_lose(lose: tuple[BoerseLos, ...] | list[BoerseLos], sats: int) -> tuple[BoerseLos, ...]:
    """Nimmt die ältesten Lose zuerst. Kein anteiliges Skalieren über alle Lose."""
    rest = int(sats)
    if rest <= 0:
        return ()
    out: list[BoerseLos] = []
    for los in lose:
        if rest <= 0:
            break
        if los.sats <= 0:
            continue
        if los.sats <= rest:
            out.append(los)
            rest -= los.sats
            continue
        kosten = None
        if los.kosten is not None and los.sats:
            kosten = (los.kosten * Decimal(rest) / Decimal(los.sats)).quantize(
                _KOSTEN_QUANT, rounding=ROUND_HALF_UP
            )
        out.append(
            BoerseLos(
                sats=rest,
                zeit_ts=los.zeit_ts,
                konto=los.konto,
                boerse=los.boerse,
                kauf_art=los.kauf_art,
                einzelpreis_btc=los.einzelpreis_btc,
                waehrung=los.waehrung,
                kosten=kosten,
            )
        )
        rest = 0
    return tuple(out)


def _kosten_kauf(b: Buchung, bestand: int) -> tuple[Decimal | None, Decimal | None, str | None]:
    w = (b.waehrung or "").strip().upper() or None
    if w and not waehrung_ok(w):
        return None, None, None
    kosten = None
    if b.fiat is not None:
        kosten = abs(Decimal(b.fiat))
        if b.fiat_gebuehr is not None:
            kosten += abs(Decimal(b.fiat_gebuehr))
    einzel = None
    if b.kurs is not None and waehrung_ok(w):
        einzel = abs(Decimal(b.kurs))
    if kosten is None and einzel is not None and bestand > 0:
        kosten = (einzel * Decimal(bestand) / SATOSHIS_JE_BTC)
    if einzel is None and kosten is not None and bestand > 0:
        einzel = (kosten * SATOSHIS_JE_BTC / Decimal(bestand))
    if einzel is not None:
        einzel = einzel.quantize(_PREIS_QUANT, rounding=ROUND_HALF_UP)
    return kosten, einzel, w if (kosten is not None or einzel is not None) else None


def _neuer_los(b: Buchung, boerse: str, art: str) -> Los | None:
    sats = abs(int(b.sats))
    geb = max(0, int(b.gebuehr_sats or 0))
    bestand = sats - geb
    if bestand <= 0:
        return None
    kosten, einzel, w = _kosten_kauf(b, bestand) if art == "kauf" else (None, None, None)
    marke = {
        "konto": b.konto,
        "boerse": boerse,
        "kauf_ref": b.ref,
        "art": art,
        "kosten_voll": kosten,
        "sats_voll": bestand,
        "waehrung": w,
        "einzelpreis_btc": einzel,
    }
    return Los(
        sats=bestand,
        zeit=b.zeit_ts,
        rang=(int(b.zeile), str(b.art), b.ref or ""),
        marke=marke,
    )


def _zu_boerse(los: Los) -> BoerseLos:
    marke = los.marke or {}
    voll = int(marke.get("sats_voll") or los.sats)
    kosten_voll = marke.get("kosten_voll")
    kosten = None
    if kosten_voll is not None and voll > 0:
        kosten = (Decimal(kosten_voll) * Decimal(los.sats) / Decimal(voll)).quantize(
            _KOSTEN_QUANT, rounding=ROUND_HALF_UP
        )
    return BoerseLos(
        sats=los.sats,
        zeit_ts=los.zeit,
        konto=marke.get("konto") or "",
        boerse=marke.get("boerse") or "Börse",
        kauf_art=marke.get("art") or "kauf",
        einzelpreis_btc=marke.get("einzelpreis_btc"),
        waehrung=marke.get("waehrung"),
        kosten=kosten,
    )


def verbrauchen(
    lose: list[Los],
    reihe: list[tuple[str, int]],
) -> tuple[dict[str, list[Los]], list[Los]]:
    """Verteilt den Bestand nach FIFO und gibt Restlose zurück."""
    geordnet = ordnen(list(lose))
    verteilt = verteilen(geordnet, reihe)
    verbraucht: dict[tuple, int] = {}
    for anteile in verteilt.values():
        for los in anteile:
            marke = los.marke or {}
            schluessel = (los.zeit, los.rang, marke.get("kauf_ref"))
            verbraucht[schluessel] = verbraucht.get(schluessel, 0) + los.sats
    rest: list[Los] = []
    for los in geordnet:
        marke = los.marke or {}
        schluessel = (los.zeit, los.rang, marke.get("kauf_ref"))
        nimm = verbraucht.get(schluessel, 0)
        if nimm > los.sats:
            raise FifoFehler("interner_fifo_fehler")
        if nimm < los.sats:
            rest.append(Los(sats=los.sats - nimm, zeit=los.zeit, rang=los.rang, marke=los.marke))
        verbraucht[schluessel] = 0
    return verteilt, rest


def _sortiert(buchungen: list[Buchung] | tuple[Buchung, ...]) -> list[Buchung]:
    return sorted(
        buchungen,
        key=lambda b: (b.zeit_ts is None, int(b.zeit_ts or 0), int(b.zeile), b.ref or ""),
    )


def _reihe_erfuellt(verteilt: dict[str, list[Los]], reihe: list[tuple[str, int]]) -> bool:
    for name, bedarf in reihe:
        bekommen = sum(int(l.sats) for l in verteilt.get(name, []))
        if bekommen < int(bedarf):
            return False
    return True


def _verbrauche(stapel: list[Los], reihe: list[tuple[str, int]], b: Buchung) -> tuple[dict[str, list[Los]], list[Los]]:
    try:
        verteilt, rest = verbrauchen(stapel, reihe)
    except ValueError as exc:
        raise FifoFehler("bestand_zu_klein", zeile=b.zeile, art=str(b.art)) from exc
    if not _reihe_erfuellt(verteilt, reihe):
        raise FifoFehler("bestand_zu_klein", zeile=b.zeile, art=str(b.art))
    return verteilt, rest


def fifo_konto(
    buchungen: list[Buchung] | tuple[Buchung, ...],
    *,
    boerse_typ: str | None = None,
    name: str | None = None,
) -> tuple[dict[str, tuple[BoerseLos, ...]], list[Los], list[FifoFehler]]:
    """
    Striktes FIFO je Börsenkonto.

    Rückgabe: Auszahlung-Ref → Lose der Auszahlung (ohne Gebührenanteile),
    Restbestand, Fehler (Bestand zu klein). Mehrere Konten in *buchungen*
    werden getrennt verrechnet.
    """
    start = time.perf_counter()
    if not buchungen:
        schreibe("boerse_fifo", n_kauf=0, n_auszahlung=0, n_fehler=0, dauer_ms=0)
        return {}, [], []

    gruppen: dict[str, list[Buchung]] = {}
    for b in buchungen:
        gruppen.setdefault(b.konto or "", []).append(b)

    zu_aus: dict[str, tuple[BoerseLos, ...]] = {}
    rest_alle: list[Los] = []
    fehler: list[FifoFehler] = []
    n_kauf = n_ein = n_verkauf = n_aus = n_geb = n_skip = 0

    for konto, gruppe in gruppen.items():
        boerse = anzeige_name(konto, boerse_typ, name=name)
        stapel: list[Los] = []
        for b in _sortiert(gruppe):
            if b.art is Art.KAUF:
                if b.waehrung and not waehrung_ok(b.waehrung):
                    n_skip += 1
                    continue
                los = _neuer_los(b, boerse, "kauf")
                if los is None:
                    n_skip += 1
                    continue
                stapel.append(los)
                n_kauf += 1
            elif b.art is Art.BTC_EINGANG:
                los = _neuer_los(b, boerse, "btc_eingang")
                if los is None:
                    n_skip += 1
                    continue
                stapel.append(los)
                n_ein += 1
            elif b.art is Art.VERKAUF:
                betrag = abs(int(b.sats))
                fee = max(0, int(b.gebuehr_sats or 0))
                reihe: list[tuple[str, int]] = [("verkauf", betrag)]
                if fee:
                    reihe.append(("gebuehr", fee))
                try:
                    _verteilt, stapel = _verbrauche(stapel, reihe, b)
                    n_verkauf += 1
                except FifoFehler as exc:
                    fehler.append(exc)
            elif b.art is Art.BTC_AUSGANG:
                betrag = abs(int(b.sats))
                fee = max(0, int(b.gebuehr_sats or 0))
                reihe = [("auszahlung", betrag)]
                if fee:
                    reihe.append(("gebuehr", fee))
                try:
                    verteilt, stapel = _verbrauche(stapel, reihe, b)
                    zu_aus[b.ref] = tuple(_zu_boerse(l) for l in verteilt.get("auszahlung", ()))
                    n_aus += 1
                except FifoFehler as exc:
                    fehler.append(exc)
            elif b.art is Art.GEBUEHR:
                fee = abs(int(b.sats)) or max(0, int(b.gebuehr_sats or 0))
                if fee <= 0:
                    n_skip += 1
                    continue
                try:
                    _verteilt, stapel = _verbrauche(stapel, [("gebuehr", fee)], b)
                    n_geb += 1
                except FifoFehler as exc:
                    fehler.append(exc)
            elif b.art in (Art.FIAT_EIN, Art.FIAT_AUS, Art.INTERN, Art.QUARANTAENE):
                continue
            else:
                n_skip += 1
        rest_alle.extend(stapel)

    dauer = int((time.perf_counter() - start) * 1000)
    bestand_sats = sum(l.sats for l in rest_alle)
    schreibe(
        "boerse_fifo",
        n_kauf=n_kauf,
        n_einzahlung=n_ein,
        n_verkauf=n_verkauf,
        n_auszahlung=n_aus,
        n_gebuehr=n_geb,
        n_uebersprungen=n_skip,
        n_fehler=len(fehler),
        n_lose_bestand=len(rest_alle),
        bestand=groessenordnung(bestand_sats),
        n_konten=len(gruppen),
        dauer_ms=dauer,
    )
    return zu_aus, rest_alle, fehler


def lose_fuer_auszahlung(
    buchungen: list[Buchung] | tuple[Buchung, ...],
    auszahlung_ref: str,
    *,
    boerse_typ: str | None = None,
    name: str | None = None,
) -> tuple[BoerseLos, ...]:
    zu, _rest, _fehler = fifo_konto(buchungen, boerse_typ=boerse_typ, name=name)
    return zu.get(auszahlung_ref, ())
