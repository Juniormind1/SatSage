"""Coinbase-Custom-Statement zu Buchungen. Reine Funktion, kein I/O."""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal

from core.boerse.erkennung import Erkannt, erkenne
from core.boerse.modell import Art, Buchung, FormatFehler, ParseErgebnis, Quarantaene
from core.boerse.zahlen import ZahlenFehler, btc_nach_sats, parse_decimal

_KAUF = frozenset({"buy", "advanced trade buy"})
_VERKAUF = frozenset({"sell", "advanced trade sell"})
_AUS = frozenset({"send"})
_EIN = frozenset({"receive"})
_FIAT_EIN = frozenset({"deposit"})
_FIAT_AUS = frozenset({"withdrawal"})
_INTERN = frozenset({
    "pro deposit", "pro withdrawal", "exchange deposit", "exchange withdrawal",
})
_QUAR = frozenset({
    "convert", "rewards income", "staking income", "learning reward",
})
_BTC = frozenset({"btc", "bitcoin"})
_FIAT = frozenset({"eur", "usd", "euro", "us dollar"})
_RE_ADDR = re.compile(
    r"\b((?:bc1|tb1|bcrt1)[ac-hj-np-z02-9]{25,80}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dict_zeilen(erkannt: Erkannt):
    leser = csv.reader(erkannt.zeilen, delimiter=erkannt.trennzeichen)
    for i, reihe in enumerate(leser):
        nr = erkannt.kopf_zeile + 1 + i
        if not reihe or all(not (z or "").strip() for z in reihe):
            continue
        werte = {}
        for j, name in enumerate(erkannt.spalten):
            werte[name] = reihe[j].strip() if j < len(reihe) else ""
        yield nr, werte


def _get(zeile: dict[str, str], *namen: str) -> str:
    for n in namen:
        if n in zeile:
            return zeile[n]
    return ""


def _waehrung(zeile: dict[str, str], spalten: tuple[str, ...]) -> str | None:
    roh = _get(zeile, "price currency", "spot price currency").strip().upper()
    if roh in {"EUR", "USD"}:
        return roh
    for prefix in ("eur", "usd"):
        if any(s.startswith(prefix + " ") for s in spalten):
            return prefix.upper()
    if roh in {"€", "EURO"}:
        return "EUR"
    if roh in {"$", "US DOLLAR"}:
        return "USD"
    return roh or None


def _zeit(roh: str) -> tuple[int | None, bool]:
    text = (roh or "").strip().strip('"')
    if not text:
        return None, False
    zone = bool(re.search(r"\bUTC\b|Z$|[+-]\d{2}:\d{2}$|[+-]\d{4}$", text, re.I))
    t = re.sub(r"\s+UTC\s*$", "", text, flags=re.I)
    t = t.replace("Z", "+00:00") if t.endswith("Z") else t
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            dt = datetime.strptime(t, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp()), zone
    try:
        dt = datetime.fromisoformat(t)
    except ValueError as exc:
        raise ZahlenFehler("Zeit nicht lesbar.") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        zone = False
    else:
        zone = True
    return int(dt.timestamp()), zone


def _adresse(zeile: dict[str, str]) -> str | None:
    for feld in ("recipient address", "sender address"):
        wert = _get(zeile, feld).strip()
        if wert:
            return wert
    notes = _get(zeile, "notes")
    m = _RE_ADDR.search(notes)
    return m.group(1) if m else None


def _ref(zeile: dict[str, str]) -> str:
    ident = _get(zeile, "id").strip()
    if ident:
        return ident
    roh = "|".join((
        _get(zeile, "timestamp"),
        _get(zeile, "transaction type"),
        _get(zeile, "quantity transacted"),
        _get(zeile, "subtotal", "eur subtotal", "usd subtotal"),
    ))
    return "CBH-" + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:20]


def parse(text: str, *, konto: str = "coinbase") -> ParseErgebnis:
    erkannt = erkenne(text)
    if erkannt.boerse != "coinbase":
        raise FormatFehler("Kein Coinbase-Statement", erkannt.spalten)
    datei = _hash(text)
    buchungen: list[Buchung] = []
    quarantaene: list[Quarantaene] = []
    for nr, zeile in _dict_zeilen(erkannt):
        typ = _get(zeile, "transaction type").strip()
        typ_n = typ.casefold()
        asset = _get(zeile, "asset").strip()
        asset_n = asset.casefold()
        try:
            b, q = _zeile(konto, datei, nr, zeile, typ, typ_n, asset, asset_n, erkannt.spalten)
        except ZahlenFehler:
            quarantaene.append(Quarantaene(nr, "Zahl nicht lesbar", typ or None, datei))
            continue
        if b:
            buchungen.append(b)
        if q:
            quarantaene.append(q)
    buchungen.sort(key=lambda b: (b.zeit_ts is None, b.zeit_ts or 0, b.zeile, b.ref))
    return ParseErgebnis(tuple(buchungen), tuple(quarantaene), erkannt.variante, datei)


def _zeile(konto, datei, nr, zeile, typ, typ_n, asset, asset_n, spalten):
    if typ_n in _QUAR:
        return None, Quarantaene(nr, "nicht unterstützter Typ", typ, datei)
    if typ_n not in _KAUF | _VERKAUF | _AUS | _EIN | _FIAT_EIN | _FIAT_AUS | _INTERN:
        if typ_n:
            return None, Quarantaene(nr, "nicht unterstützter Typ", typ, datei)
        return None, Quarantaene(nr, "Typ fehlt", None, datei)

    ist_btc = asset_n in _BTC
    ist_fiat = asset_n in _FIAT or asset_n in {"eur", "usd"}
    waehrung = _waehrung(zeile, spalten)
    if waehrung not in {None, "EUR", "USD"}:
        waehrung = None

    if typ_n in _KAUF | _VERKAUF:
        if not ist_btc or waehrung not in {"EUR", "USD"}:
            return None, None
        art = Art.KAUF if typ_n in _KAUF else Art.VERKAUF
        return _handel(konto, datei, nr, zeile, typ, art, waehrung), None

    if typ_n in _AUS | _EIN:
        if not ist_btc:
            return None, None
        art = Art.BTC_AUSGANG if typ_n in _AUS else Art.BTC_EINGANG
        return _kette(konto, datei, nr, zeile, typ, art), None

    if typ_n in _FIAT_EIN | _FIAT_AUS:
        if ist_btc:
            return None, Quarantaene(nr, "unerwartete Asset-Typ-Kombination", typ, datei)
        if not ist_fiat and waehrung not in {"EUR", "USD"}:
            return None, None
        art = Art.FIAT_EIN if typ_n in _FIAT_EIN else Art.FIAT_AUS
        return _fiat(konto, datei, nr, zeile, typ, art, waehrung if waehrung in {"EUR", "USD"} else asset.upper()), None

    if typ_n in _INTERN:
        if not ist_btc:
            return None, None
        return _kette(konto, datei, nr, zeile, typ, Art.INTERN), None

    return None, Quarantaene(nr, "nicht unterstützter Typ", typ, datei)


def _kurs_und_fiat(zeile: dict[str, str], art: Art | None):
    kurs = parse_decimal(_get(
        zeile,
        "price at transaction",
        "spot price at transaction",
        "eur spot price at transaction",
        "usd spot price at transaction",
    ))
    sub = parse_decimal(_get(zeile, "subtotal", "eur subtotal", "usd subtotal"))
    fee = parse_decimal(_get(
        zeile,
        "fees and/or spread",
        "fees",
        "eur fees",
        "usd fees",
    ))
    if sub is not None and art is Art.KAUF:
        sub = -abs(sub)
    elif sub is not None and art is Art.VERKAUF:
        sub = abs(sub)
    if fee is not None:
        fee = abs(fee)
    return kurs, sub, fee


def _sats(zeile: dict[str, str], art: Art) -> int:
    menge = parse_decimal(_get(zeile, "quantity transacted"))
    if menge is None:
        return 0
    sats = btc_nach_sats(menge)
    if art in {Art.KAUF, Art.BTC_EINGANG}:
        return abs(sats)
    if art in {Art.VERKAUF, Art.BTC_AUSGANG}:
        return -abs(sats)
    return sats


def _buchung(konto, datei, nr, zeile, typ, art, *, sats, gebuehr_sats, fiat, fiat_gebuehr, waehrung, kurs, adresse=None):
    zeit_ts, zone = _zeit(_get(zeile, "timestamp"))
    return Buchung(
        konto=konto,
        ref=_ref(zeile),
        gruppe=None,
        zeit_ts=zeit_ts,
        zeit_zone_belegt=zone,
        art=art,
        sats=sats,
        gebuehr_sats=gebuehr_sats,
        fiat=fiat,
        fiat_gebuehr=fiat_gebuehr,
        waehrung=waehrung,
        kurs=kurs,
        txid=None,
        adresse=adresse,
        lightning=False,
        roh_typ=typ,
        roh_subtyp=None,
        datei=datei,
        zeile=nr,
    )


def _handel(konto, datei, nr, zeile, typ, art, waehrung):
    kurs, sub, fee = _kurs_und_fiat(zeile, art)
    return _buchung(
        konto, datei, nr, zeile, typ, art,
        sats=_sats(zeile, art),
        gebuehr_sats=0,
        fiat=sub,
        fiat_gebuehr=fee,
        waehrung=waehrung,
        kurs=kurs,
    )


def _kette(konto, datei, nr, zeile, typ, art):
    sats = _sats(zeile, art)
    return _buchung(
        konto, datei, nr, zeile, typ, art,
        sats=sats,
        gebuehr_sats=0,
        fiat=None,
        fiat_gebuehr=None,
        waehrung=None,
        kurs=None,
        adresse=_adresse(zeile) if art is Art.BTC_AUSGANG else _adresse(zeile),
    )


def _fiat(konto, datei, nr, zeile, typ, art, waehrung):
    _kurs, sub, fee = _kurs_und_fiat(zeile, None)
    menge = parse_decimal(_get(zeile, "quantity transacted"))
    wert = sub if sub is not None else menge
    if wert is not None and art is Art.FIAT_EIN:
        wert = abs(wert)
    elif wert is not None and art is Art.FIAT_AUS:
        wert = -abs(wert)
    return _buchung(
        konto, datei, nr, zeile, typ, art,
        sats=0,
        gebuehr_sats=0,
        fiat=wert,
        fiat_gebuehr=fee,
        waehrung=waehrung if waehrung in {"EUR", "USD"} else None,
        kurs=None,
    )
