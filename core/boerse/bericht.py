"""Felder des Steuerberichts für Börsen-FIFO-Lose (M8).

Ohne P&L ist das ein Herkunftsnachweis: Datum, Menge und Einzelkaufpreis
je Los. Gewinn und Verlust erscheinen nur, wenn die Einstellung
eingeschaltet ist. On-Chain-Datum und Lot-Farbe bleiben unberührt.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

from core.boerse.fifo import BoerseLos, nimm_lose
from core.log_redaktion import schreibe

_FIAT_QUANT = Decimal("0.01")
KursFn = Callable[[datetime, str], Decimal | None]


def parse_boerse_pnl(roh: object | None) -> bool:
    """P&L-Schalter. Default ist aus; nur eindeutige Ja-Werte schalten ein."""
    if roh is None:
        return False
    if isinstance(roh, bool):
        return roh
    text = str(roh).strip().casefold()
    return text in {"1", "true", "ja", "on", "yes", "ein"}


def _fiat_text(wert: Decimal | None, stellen: int = 2) -> str | None:
    if wert is None:
        return None
    quant = Decimal("1").scaleb(-stellen)
    return format(wert.quantize(quant, rounding=ROUND_HALF_UP), "f")


def _zeitpunkt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def los_als_zeile(
    los: BoerseLos,
    *,
    bezug: datetime,
    haltefrist_jahre: int,
    stichtag,
    pnl: bool,
    kurs_am: KursFn | None,
) -> dict:
    from core.tax import haltefrist_entscheidung

    anschaffung = _zeitpunkt(los.zeit_ts)
    frist_ende = None
    erfuellt = False
    neuvermoegen = False
    tage = None
    if anschaffung is not None:
        frist_ende, erfuellt, neuvermoegen = haltefrist_entscheidung(
            anschaffung, bezug, haltefrist_jahre, stichtag
        )
        tage = max(0, (bezug - anschaffung).days)
    zeile = {
        "label": los.label(),
        "boerse": los.boerse,
        "konto": los.konto,
        "kauf_art": los.kauf_art,
        "sats": int(los.sats),
        "datum": anschaffung.strftime("%d.%m.%Y") if anschaffung else "",
        "zeit": anschaffung.strftime("%H:%M:%S") if anschaffung else "",
        "time_ts": int(los.zeit_ts) if los.zeit_ts is not None else None,
        "haltedauer_tage": tage,
        "frist_ende": frist_ende.strftime("%d.%m.%Y") if frist_ende else "",
        "erfuellt": bool(erfuellt),
        "neuvermoegen": bool(neuvermoegen),
        "einzelpreis": _fiat_text(los.einzelpreis_btc),
        "kosten": _fiat_text(los.kosten),
        "waehrung": los.waehrung,
        "beleg": "Börsenbeleg",
    }
    if los.kauf_art == "btc_eingang" and los.kosten is None:
        zeile["hinweis"] = "einzahlung_ohne_kaufpreis"
    if pnl:
        zeile.update(_pnl_felder(los, bezug, kurs_am))
    return zeile


def _pnl_felder(los: BoerseLos, bezug: datetime, kurs_am: KursFn | None) -> dict:
    felder = {
        "wert_bezug": None,
        "ergebnis": None,
        "kurs_quelle": None,
    }
    if los.kosten is None or not los.waehrung or kurs_am is None:
        return felder
    try:
        kurs = kurs_am(bezug, los.waehrung)
    except Exception:
        kurs = None
    if kurs is None:
        return felder
    wert = (Decimal(kurs) * Decimal(los.sats) / Decimal(100_000_000)).quantize(
        _FIAT_QUANT, rounding=ROUND_HALF_UP
    )
    ergebnis = (wert - Decimal(los.kosten)).quantize(_FIAT_QUANT, rounding=ROUND_HALF_UP)
    felder["wert_bezug"] = _fiat_text(wert)
    felder["ergebnis"] = _fiat_text(ergebnis)
    felder["kurs_quelle"] = "tageskurs"
    return felder


def haenge_an_eintrag(
    eintrag: dict,
    lose: tuple[BoerseLos, ...] | list[BoerseLos],
    *,
    bezug: datetime,
    haltefrist_jahre: int,
    stichtag,
    pnl: bool,
    kurs_am: KursFn | None,
) -> None:
    if not lose:
        eintrag["boerse_lose"] = []
        eintrag["boerse_belegt"] = False
        return
    zeilen = [
        los_als_zeile(
            los,
            bezug=bezug,
            haltefrist_jahre=haltefrist_jahre,
            stichtag=stichtag,
            pnl=pnl,
            kurs_am=kurs_am,
        )
        for los in lose
    ]
    namen = []
    for z in zeilen:
        if z["boerse"] and z["boerse"] not in namen:
            namen.append(z["boerse"])
    eintrag["boerse_lose"] = zeilen
    eintrag["boerse_belegt"] = True
    eintrag["boerse_label"] = "laut " + (" / ".join(namen) if namen else "Börse")
    eintrag["sats_aus_boerse"] = sum(z["sats"] for z in zeilen)
    # Laut Börse erfüllt: alle Lose mit Datum erfüllen die Frist.
    datiert = [z for z in zeilen if z["time_ts"] is not None]
    eintrag["erfuellt_laut_boerse"] = bool(datiert) and all(z["erfuellt"] for z in datiert)


def pnl_summen(eintraege: list[dict], *, pnl: bool) -> dict[str, str]:
    """Summe der Ergebnisse je Währung. Leer, wenn P&L aus ist."""
    if not pnl:
        return {}
    summen: dict[str, Decimal] = {}
    for eintrag in eintraege:
        for los in eintrag.get("boerse_lose") or []:
            roh = los.get("ergebnis")
            w = los.get("waehrung")
            if roh is None or not w:
                continue
            summen[w] = summen.get(w, Decimal("0")) + Decimal(roh)
    return {w: _fiat_text(v) or "0.00" for w, v in summen.items()}


def lose_im_netz(netz: dict, overlay) -> tuple[BoerseLos, ...]:
    """FIFO-Lose entlang des Herkunftsnetzes, ohne anteiliges Mischen."""
    from core.herkunftsnetz import _schluessel_outpoint

    if not netz or overlay is None:
        return ()
    fokus = netz.get("fokus_key")
    fokus_sats = int(netz.get("fokus_sats") or 0)
    if not fokus or fokus_sats <= 0:
        return ()
    eingehend: dict[str, list[tuple[str, int]]] = {}
    for kante in netz.get("kanten") or []:
        nach = kante.get("nach")
        von = kante.get("von")
        sats = int(kante.get("sats") or 0)
        if nach and von and sats > 0:
            eingehend.setdefault(str(nach), []).append((str(von), sats))

    gesehen: set[str] = set()

    def fuer(key: str, sats: int) -> tuple[BoerseLos, ...]:
        if sats <= 0 or key in gesehen:
            return ()
        gesehen.add(key)
        op = _schluessel_outpoint(key)
        if op is not None:
            direkt = overlay.lose_fuer_outpoint(*op)
            if direkt:
                return nimm_lose(direkt, sats)
        teile: list[BoerseLos] = []
        for von, menge in eingehend.get(key, []):
            teile.extend(fuer(von, menge))
        return nimm_lose(teile, sats) if teile else ()

    lose = fuer(str(fokus), fokus_sats)
    return lose


def lokaler_kurs_fn(immutable_cache_dir, fest: dict[tuple[str, str], Decimal] | None = None) -> KursFn:
    """Tageskurs nur aus lokalem Cache/Bundle, nie aus dem Netz."""

    def kurs_am(bezug: datetime, waehrung: str) -> Decimal | None:
        if fest:
            for schluessel in (
                (bezug.date().isoformat(), waehrung.upper()),
                (bezug.strftime("%Y-%m-%d"), waehrung.upper()),
            ):
                if schluessel in fest:
                    return Decimal(fest[schluessel])
        if immutable_cache_dir is None:
            return None
        try:
            from core.price import lade_tageskurs_csv

            preis = lade_tageskurs_csv(
                immutable_cache_dir, bezug.date(), waehrung,
            )
        except Exception as exc:
            schreibe("boerse_pnl_kurs_fehlt", grund=type(exc).__name__)
            return None
        if preis is None:
            return None
        betrag = getattr(preis, "amount", None)
        if betrag is None or betrag <= 0:
            return None
        return Decimal(str(betrag))

    return kurs_am
