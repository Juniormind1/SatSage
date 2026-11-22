"""Kraken-Ledgers und optional Trades zu Buchungen. Reine Funktion, kein I/O."""
from __future__ import annotations

import csv
import hashlib
import io
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from core.boerse.erkennung import Erkannt, erkenne
from core.boerse.modell import Art, Buchung, FormatFehler, ParseErgebnis, Quarantaene
from core.boerse.zahlen import ZahlenFehler, btc_nach_sats, parse_decimal

_BTC = frozenset({
    "xxbt", "xbt", "btc",
    "xbt.m", "xxbt.m", "btc.m",
    "xbt.s", "xxbt.s", "btc.s",
    "xbt.f", "xxbt.f", "btc.f",
    "xbt.hold", "xxbt.hold", "btc.hold",
    "xbt.b", "btc.b",
})
_EUR = frozenset({"zeur", "eur"})
_USD = frozenset({"zusd", "usd"})
_INTERN_SUB = frozenset({
    "allocation", "deallocation", "autoallocate", "migration",
    "spottostaking", "stakingfromspot", "stakingtospot", "spotfromstaking",
})
_QUARANTAENE_TYP = frozenset({
    "margin trade", "rollover", "settled", "staking", "adjustment", "invite bonus",
})
_QUARANTAENE_SUB = frozenset({"spottofutures", "spotfromfutures", "reward"})


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _asset(code: str) -> str | None:
    n = (code or "").strip().lower()
    if n in _BTC:
        return "BTC"
    if n in _EUR:
        return "EUR"
    if n in _USD:
        return "USD"
    kern = n.split(".", 1)[0]
    if kern in {"xxbt", "xbt", "btc"}:
        return None  # unbekannter BTC-Suffix → unsicher
    if kern in _EUR:
        return "EUR"
    if kern in _USD:
        return "USD"
    return None


def _unsicherer_btc(code: str) -> bool:
    n = (code or "").strip().lower()
    if not n or n in _BTC:
        return False
    return n.split(".", 1)[0] in {"xxbt", "xbt", "btc"}


def _zeit_ts(roh: str) -> int | None:
    text = (roh or "").strip().strip('"')
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    raise ZahlenFehler("Zeit nicht lesbar.")


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


def _feld(zeile: dict[str, str], *namen: str) -> str:
    for n in namen:
        if n in zeile:
            return zeile[n]
    return ""


def parse_ledgers(text: str, *, konto: str = "kraken") -> ParseErgebnis:
    """Nur das Ledger. Kurse aus der Fiat-Gegenzeile, falls nötig (E9, änderbar)."""
    return _parse(text, None, konto=konto)


def parse(ledgers_text: str, trades_text: str | None = None, *, konto: str = "kraken") -> ParseErgebnis:
    return _parse(ledgers_text, trades_text, konto=konto)


def _parse(ledgers_text: str, trades_text: str | None, *, konto: str) -> ParseErgebnis:
    erkannt = erkenne(ledgers_text)
    if erkannt.boerse != "kraken" or not erkannt.variante.startswith("ledgers"):
        raise FormatFehler("Kein Kraken-Ledger", erkannt.spalten)
    datei = _hash(ledgers_text)
    trades = _trades(trades_text) if trades_text else {}
    quarantaene: list[Quarantaene] = []
    raw: list[tuple[int, dict[str, str]]] = []
    for nr, zeile in _dict_zeilen(erkannt):
        typ = _feld(zeile, "type").strip().lower()
        if typ == "sale":
            # Offiziell nicht im Export; falls doch, ignorieren.
            continue
        raw.append((nr, zeile))

    gruppen: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    einzel: list[tuple[int, dict[str, str]]] = []
    for nr, zeile in raw:
        refid = _feld(zeile, "refid").strip()
        typ = _feld(zeile, "type").strip().lower()
        if typ in {"trade", "spend", "receive"} and not refid:
            quarantaene.append(Quarantaene(nr, "refid fehlt", typ, datei))
            continue
        if refid:
            gruppen[refid].append((nr, zeile))
        else:
            einzel.append((nr, zeile))

    buchungen: list[Buchung] = []
    for refid, zeilen in gruppen.items():
        ergebnis = _gruppe(konto, datei, refid, zeilen, trades)
        buchungen.extend(ergebnis[0])
        quarantaene.extend(ergebnis[1])
    for nr, zeile in einzel:
        b, q = _einzel(konto, datei, nr, zeile)
        if b:
            buchungen.append(b)
        if q:
            quarantaene.append(q)

    buchungen.sort(key=lambda b: (b.zeit_ts is None, b.zeit_ts or 0, b.zeile, b.ref))
    return ParseErgebnis(tuple(buchungen), tuple(quarantaene), erkannt.variante, datei)


def _trades(text: str) -> dict[str, dict]:
    erkannt = erkenne(text)
    if erkannt.boerse != "kraken" or erkannt.variante != "trades":
        raise FormatFehler("Kein Kraken-Trades-Export", erkannt.spalten)
    index: dict[str, dict] = {}
    for nr, zeile in _dict_zeilen(erkannt):
        txid = _feld(zeile, "txid").strip()
        ledgers = tuple(
            t.strip() for t in _feld(zeile, "ledgers").split(",") if t.strip()
        )
        eintrag = {
            "txid": txid,
            "price": _feld(zeile, "price"),
            "ledgers": ledgers,
        }
        if txid:
            index[txid] = eintrag
        for lid in ledgers:
            index.setdefault(lid, eintrag)
    return index


def _kurs(fiat: Decimal | None, btc: Decimal | None, trade: dict | None) -> Decimal | None:
    if trade:
        try:
            wert = parse_decimal(trade.get("price"))
            if wert is not None:
                return wert
        except ZahlenFehler:
            pass
    if fiat is None or btc is None or btc == 0:
        return None
    return abs(fiat) / abs(btc)


def _gruppe(
    konto: str,
    datei: str,
    refid: str,
    zeilen: list[tuple[int, dict[str, str]]],
    trades: dict[str, dict],
) -> tuple[list[Buchung], list[Quarantaene]]:
    typen = {_feld(z, "type").strip().lower() for _, z in zeilen}
    sub = {_feld(z, "subtype").strip().lower() for _, z in zeilen if _feld(z, "subtype").strip()}
    if typen <= {"transfer", "earn"}:
        if sub & _QUARANTAENE_SUB or typen & _QUARANTAENE_TYP:
            return [], [
                Quarantaene(nr, "nicht unterstützter Typ", _feld(z, "type"), datei)
                for nr, z in zeilen
            ]
        if sub <= _INTERN_SUB and sub:
            return _intern(konto, datei, refid, zeilen)
        return [], [
            Quarantaene(nr, "Transfer ohne bekannten Subtyp", _feld(z, "type"), datei)
            for nr, z in zeilen
        ]

    if typen & _QUARANTAENE_TYP or sub & _QUARANTAENE_SUB:
        return [], [
            Quarantaene(nr, "nicht unterstützter Typ", _feld(z, "type"), datei)
            for nr, z in zeilen
        ]

    if typen <= {"trade"} or typen <= {"spend", "receive"} or typen <= {"spend", "receive", "deposit"}:
        return _handel(konto, datei, refid, zeilen, trades)

    if typen <= {"deposit", "withdrawal"}:
        buchungen: list[Buchung] = []
        quarantaene: list[Quarantaene] = []
        for nr, z in zeilen:
            b, q = _einzel(konto, datei, nr, z)
            if b:
                buchungen.append(b)
            if q:
                quarantaene.append(q)
        return buchungen, quarantaene

    return [], [
        Quarantaene(nr, "ungepaarte oder unerwartete Zeilengruppe", _feld(z, "type"), datei)
        for nr, z in zeilen
    ]


def _intern(konto, datei, refid, zeilen) -> tuple[list[Buchung], list[Quarantaene]]:
    buchungen: list[Buchung] = []
    quarantaene: list[Quarantaene] = []
    for nr, z in zeilen:
        if _unsicherer_btc(_feld(z, "asset")):
            quarantaene.append(Quarantaene(nr, "unbekannter BTC-Suffix", _feld(z, "type"), datei))
            continue
        try:
            buchungen.append(_buchung_aus_zeile(
                konto, datei, nr, z, Art.INTERN, gruppe=refid, sats_override=None
            ))
        except ZahlenFehler:
            quarantaene.append(Quarantaene(nr, "Zahl nicht lesbar", _feld(z, "type"), datei))
    return buchungen, quarantaene


def _handel(konto, datei, refid, zeilen, trades):
    btc, fiat, fiat_deposits, fremd = [], [], [], []
    for nr, z in zeilen:
        typ = _feld(z, "type").strip().lower()
        asset = _asset(_feld(z, "asset"))
        if typ == "deposit" and asset in {"EUR", "USD"}:
            fiat_deposits.append((nr, z))
        elif typ in {"trade", "spend", "receive"} and asset == "BTC":
            btc.append((nr, z))
        elif typ in {"trade", "spend", "receive"} and asset in {"EUR", "USD"}:
            fiat.append((nr, z))
        else:
            fremd.append((nr, z))
    if any(_unsicherer_btc(_feld(z, "asset")) for _, z in zeilen):
        return [], [
            Quarantaene(nr, "unbekannter BTC-Suffix", _feld(z, "type"), datei)
            for nr, z in zeilen if _unsicherer_btc(_feld(z, "asset"))
        ]
    quarantaene: list[Quarantaene] = []
    if fremd or len(btc) != 1 or len(fiat) != 1:
        grund = "Trade ohne Fiat-Gegenzeile" if not fiat else "ungepaarte oder unerwartete Zeilengruppe"
        return [], [
            Quarantaene(nr, grund, _feld(z, "type"), datei)
            for nr, z in (btc + fiat + fremd)
        ]

    nr, zb = btc[0]
    _, zf = fiat[0]
    try:
        btc_dec = parse_decimal(_feld(zb, "amount"))
        fee_dec = parse_decimal(_feld(zb, "fee")) or Decimal(0)
        fiat_dec = parse_decimal(_feld(zf, "amount"))
        fiat_fee = parse_decimal(_feld(zf, "fee")) or Decimal(0)
        if btc_dec is None:
            raise ZahlenFehler("BTC-Betrag fehlt.")
        sats = btc_nach_sats(btc_dec)
        gebuehr_sats = abs(btc_nach_sats(fee_dec))
    except ZahlenFehler:
        return [], [Quarantaene(nr, "Zahl nicht lesbar", _feld(zb, "type"), datei)]

    if sats > 0:
        art = Art.KAUF
    elif sats < 0:
        art = Art.VERKAUF
    else:
        return [], [Quarantaene(nr, "BTC-Betrag ist null", _feld(zb, "type"), datei)]

    waehrung = _asset(_feld(zf, "asset"))
    trade = None
    for schluessel in (_feld(zb, "txid"), _feld(zf, "txid"), refid):
        if schluessel and schluessel in trades:
            trade = trades[schluessel]
            break
    try:
        zeit = _zeit_ts(_feld(zb, "time"))
    except ZahlenFehler:
        return [], [Quarantaene(nr, "Zeit nicht lesbar", _feld(zb, "type"), datei)]

    buchung = Buchung(
        konto=konto,
        ref=_feld(zb, "txid") or refid,
        gruppe=refid,
        zeit_ts=zeit,
        zeit_zone_belegt=True,
        art=art,
        sats=sats,
        gebuehr_sats=gebuehr_sats,
        fiat=fiat_dec,
        fiat_gebuehr=fiat_fee,
        waehrung=waehrung,
        kurs=_kurs(fiat_dec, btc_dec, trade),
        txid=None,
        adresse=None,
        lightning=False,
        roh_typ=_feld(zb, "type"),
        roh_subtyp=_feld(zb, "subtype") or None,
        datei=datei,
        zeile=nr,
    )
    buchungen = [buchung]
    for nrd, zd in fiat_deposits:
        b, q = _einzel(konto, datei, nrd, zd)
        if b:
            buchungen.append(b)
        if q:
            quarantaene.append(q)
    return buchungen, quarantaene


def _buchung_aus_zeile(konto, datei, nr, z, art: Art, *, gruppe, sats_override) -> Buchung:
    amount = parse_decimal(_feld(z, "amount")) or Decimal(0)
    fee = parse_decimal(_feld(z, "fee")) or Decimal(0)
    asset = _asset(_feld(z, "asset"))
    sats = 0
    gebuehr_sats = 0
    fiat = None
    fiat_gebuehr = None
    waehrung = None
    if asset == "BTC":
        sats = btc_nach_sats(amount) if sats_override is None else sats_override
        gebuehr_sats = abs(btc_nach_sats(fee))
    elif asset in {"EUR", "USD"}:
        fiat = amount
        fiat_gebuehr = fee
        waehrung = asset
    return Buchung(
        konto=konto,
        ref=_feld(z, "txid") or f"{gruppe or 'z'}:{nr}",
        gruppe=gruppe,
        zeit_ts=_zeit_ts(_feld(z, "time")),
        zeit_zone_belegt=True,
        art=art,
        sats=sats,
        gebuehr_sats=gebuehr_sats,
        fiat=fiat,
        fiat_gebuehr=fiat_gebuehr,
        waehrung=waehrung,
        kurs=None,
        txid=None,
        adresse=None,
        lightning=False,
        roh_typ=_feld(z, "type"),
        roh_subtyp=_feld(z, "subtype") or None,
        datei=datei,
        zeile=nr,
    )


def _einzel(konto, datei, nr, z) -> tuple[Buchung | None, Quarantaene | None]:
    typ = _feld(z, "type").strip().lower()
    asset = _asset(_feld(z, "asset"))
    if _unsicherer_btc(_feld(z, "asset")):
        return None, Quarantaene(nr, "unbekannter BTC-Suffix", typ, datei)
    if typ in _QUARANTAENE_TYP or _feld(z, "subtype").strip().lower() in _QUARANTAENE_SUB:
        return None, Quarantaene(nr, "nicht unterstützter Typ", typ, datei)
    if typ == "withdrawal" and asset == "BTC":
        art = Art.BTC_AUSGANG
    elif typ == "deposit" and asset == "BTC":
        art = Art.BTC_EINGANG
    elif typ == "deposit" and asset in {"EUR", "USD"}:
        art = Art.FIAT_EIN
    elif typ == "withdrawal" and asset in {"EUR", "USD"}:
        art = Art.FIAT_AUS
    elif typ in {"trade", "spend", "receive"}:
        return None, Quarantaene(nr, "refid fehlt", typ, datei)
    elif asset not in {"BTC", "EUR", "USD"} and typ in {"deposit", "withdrawal", "transfer", "earn"}:
        return None, None  # andere Assets still ignorieren
    else:
        return None, Quarantaene(nr, "nicht unterstützter Typ", typ or "unbekannt", datei)
    try:
        return _buchung_aus_zeile(konto, datei, nr, z, art, gruppe=_feld(z, "refid") or None, sats_override=None), None
    except ZahlenFehler:
        return None, Quarantaene(nr, "Zahl nicht lesbar", typ, datei)


def pruefe_saldo(text: str) -> tuple[int, ...]:
    """Zeilennummern, an denen der Ledger-Saldo nicht zur Vorgängerzeile passt."""
    erkannt = erkenne(text)
    if erkannt.boerse != "kraken" or not erkannt.variante.startswith("ledgers"):
        raise FormatFehler("Kein Kraken-Ledger", erkannt.spalten)
    letzte: dict[tuple[str, str], Decimal] = {}
    luecken: list[int] = []
    eintraege = []
    for nr, z in _dict_zeilen(erkannt):
        try:
            zeit = _zeit_ts(_feld(z, "time")) or 0
        except ZahlenFehler:
            zeit = 0
        eintraege.append((zeit, nr, z))
    eintraege.sort()
    for _zeit, nr, z in eintraege:
        asset = _feld(z, "asset").strip().lower()
        wallet = _feld(z, "wallet").strip().lower()
        try:
            amount = parse_decimal(_feld(z, "amount")) or Decimal(0)
            fee = parse_decimal(_feld(z, "fee")) or Decimal(0)
            balance = parse_decimal(_feld(z, "balance"))
        except ZahlenFehler:
            luecken.append(nr)
            continue
        if balance is None:
            continue
        key = (asset, wallet)
        alt = letzte.get(key)
        if alt is not None and alt + amount - fee != balance:
            luecken.append(nr)
        letzte[key] = balance
    return tuple(luecken)
