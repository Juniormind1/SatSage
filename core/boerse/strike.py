"""Strike-Account-Statement zu Buchungen. Reine Funktion, kein I/O."""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal

from core.boerse.erkennung import Erkannt, erkenne
from core.boerse.modell import Art, Buchung, FormatFehler, ParseErgebnis, Quarantaene
from core.boerse.zahlen import ZahlenFehler, btc_nach_sats, parse_decimal

_KAUF = frozenset({"purchase", "buy"})
_VERKAUF = frozenset({"sell"})
_EIN = frozenset({"receive"})
_AUS = frozenset({"send"})
_FIAT_EIN = frozenset({"deposit"})
_FIAT_AUS = frozenset({"withdrawal"})
_RE_TXID = re.compile(r"^[0-9a-fA-F]{64}$")
_RE_ADDR = re.compile(
    r"^(?:bc1|tb1|bcrt1)[ac-hj-np-z02-9]{25,80}$|^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$"
)
_MONAT = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


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


def _ist_lightning(ziel: str) -> bool:
    t = (ziel or "").strip().casefold()
    if t.startswith("lightning:"):
        t = t[len("lightning:"):]
    return t.startswith(("lnbc", "lntb"))


def _ist_adresse(ziel: str) -> bool:
    return bool(_RE_ADDR.match((ziel or "").strip()))


def _fiat_und_waehrung(zeile: dict[str, str]) -> tuple[Decimal | None, Decimal | None, str | None]:
    waehrung = None
    betrag = None
    gebuehr = None
    for name, wert in zeile.items():
        if name in {"amount eur", "amount usd"}:
            waehrung = "EUR" if "eur" in name else "USD"
            betrag = parse_decimal(wert)
        elif name in {"fee eur", "fee usd"}:
            gebuehr = parse_decimal(wert)
    return betrag, gebuehr, waehrung


def _zeit(roh: str) -> int | None:
    text = (roh or "").strip().strip('"')
    if not text:
        return None
    text = re.sub(r"\s+UTC\s*$", "", text, flags=re.I)
    m = re.match(
        r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})$",
        text,
    )
    if m:
        mon = _MONAT.get(m.group(1).casefold())
        if mon is None:
            raise ZahlenFehler("Zeit nicht lesbar.")
        dt = datetime(
            int(m.group(3)), mon, int(m.group(2)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            tzinfo=timezone.utc,
        )
        return int(dt.timestamp())
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(text.replace("Z", "+00:00") if text.endswith("Z") else text, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    raise ZahlenFehler("Zeit nicht lesbar.")


def parse(text: str, *, konto: str = "strike") -> ParseErgebnis:
    erkannt = erkenne(text)
    if erkannt.boerse != "strike":
        raise FormatFehler("Kein Strike-Statement", erkannt.spalten)
    datei = _hash(text)
    buchungen: list[Buchung] = []
    quarantaene: list[Quarantaene] = []
    for nr, zeile in _dict_zeilen(erkannt):
        typ = _get(zeile, "transaction type").strip()
        typ_n = typ.casefold()
        try:
            b, q = _zeile(konto, datei, nr, zeile, typ, typ_n)
        except ZahlenFehler:
            quarantaene.append(Quarantaene(nr, "Zahl nicht lesbar", typ or None, datei))
            continue
        if b:
            buchungen.append(b)
        if q:
            quarantaene.append(q)
    buchungen.sort(key=lambda b: (b.zeit_ts is None, b.zeit_ts or 0, b.zeile, b.ref))
    return ParseErgebnis(tuple(buchungen), tuple(quarantaene), erkannt.variante, datei)


def _zeile(konto, datei, nr, zeile, typ, typ_n):
    if "p2p" in typ_n:
        return None, Quarantaene(nr, "P2P-Typ", typ, datei)
    if typ_n not in _KAUF | _VERKAUF | _EIN | _AUS | _FIAT_EIN | _FIAT_AUS:
        if typ_n:
            return None, Quarantaene(nr, "nicht unterstützter Typ", typ, datei)
        return None, Quarantaene(nr, "Typ fehlt", None, datei)

    ziel = _get(zeile, "destination")
    ln = _ist_lightning(ziel)
    adresse = ziel if _ist_adresse(ziel) else None
    hash_roh = _get(zeile, "transaction hash").strip()
    # Payment-Hash einer Lightning-Zeile ist keine Chain-TxID.
    txid = hash_roh.lower() if (not ln and adresse and _RE_TXID.match(hash_roh)) else None
    # On-Chain ohne Destination, aber mit gültiger TxID: trotzdem merken.
    if txid is None and not ln and _RE_TXID.match(hash_roh) and typ_n in _EIN | _AUS:
        if adresse or not ziel:
            txid = hash_roh.lower()

    fiat, fiat_fee, waehrung = _fiat_und_waehrung(zeile)
    btc = parse_decimal(_get(zeile, "amount btc"))
    fee_btc = parse_decimal(_get(zeile, "fee btc")) or Decimal(0)
    kurs = parse_decimal(_get(zeile, "btc price"))
    gebuehr_sats = abs(btc_nach_sats(fee_btc)) if fee_btc else 0

    if typ_n in _KAUF | _VERKAUF:
        if btc is None:
            return None, Quarantaene(nr, "Zahl nicht lesbar", typ, datei)
        art = Art.KAUF if typ_n in _KAUF else Art.VERKAUF
        sats = abs(btc_nach_sats(btc))
        if art is Art.VERKAUF:
            sats = -sats
        if fiat is not None:
            fiat = -abs(fiat) if art is Art.KAUF else abs(fiat)
        if fiat_fee is not None:
            fiat_fee = abs(fiat_fee)
        return _buchung(
            konto, datei, nr, zeile, typ, art,
            sats=sats, gebuehr_sats=gebuehr_sats,
            fiat=fiat, fiat_gebuehr=fiat_fee, waehrung=waehrung, kurs=kurs,
        ), None

    if typ_n in _EIN | _AUS:
        if btc is None:
            return None, Quarantaene(nr, "Zahl nicht lesbar", typ, datei)
        art = Art.BTC_EINGANG if typ_n in _EIN else Art.BTC_AUSGANG
        sats = abs(btc_nach_sats(btc))
        if art is Art.BTC_AUSGANG:
            sats = -sats
        return _buchung(
            konto, datei, nr, zeile, typ, art,
            sats=sats, gebuehr_sats=gebuehr_sats,
            fiat=None, fiat_gebuehr=None, waehrung=None, kurs=None,
            txid=None if ln else txid,
            adresse=None if ln else adresse,
            lightning=ln,
        ), None

    # Fiat
    if btc is not None and btc != 0:
        return None, Quarantaene(nr, "unerwartete Asset-Typ-Kombination", typ, datei)
    art = Art.FIAT_EIN if typ_n in _FIAT_EIN else Art.FIAT_AUS
    if fiat is not None:
        fiat = abs(fiat) if art is Art.FIAT_EIN else -abs(fiat)
    if fiat_fee is not None:
        fiat_fee = abs(fiat_fee)
    return _buchung(
        konto, datei, nr, zeile, typ, art,
        sats=0, gebuehr_sats=0,
        fiat=fiat, fiat_gebuehr=fiat_fee, waehrung=waehrung, kurs=None,
    ), None


def _buchung(konto, datei, nr, zeile, typ, art, *, sats, gebuehr_sats, fiat, fiat_gebuehr, waehrung, kurs, txid=None, adresse=None, lightning=False):
    zeit_roh = _get(zeile, "date & time (utc)", "date & time")
    return Buchung(
        konto=konto,
        ref=_get(zeile, "reference") or f"STH-{nr}",
        gruppe=None,
        zeit_ts=_zeit(zeit_roh) if zeit_roh else None,
        zeit_zone_belegt=True,
        art=art,
        sats=sats,
        gebuehr_sats=gebuehr_sats,
        fiat=fiat,
        fiat_gebuehr=fiat_gebuehr,
        waehrung=waehrung,
        kurs=kurs,
        txid=txid,
        adresse=adresse,
        lightning=lightning,
        roh_typ=typ,
        roh_subtyp=None,
        datei=datei,
        zeile=nr,
    )
