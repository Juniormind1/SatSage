"""Zahlen aus Börsen-CSV: kein Float, BTC wird exakt in Sats gewandelt."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

SATOSHIS_JE_BTC = Decimal(100_000_000)
_LEER = frozenset({"", "-", "—", "n/a", "na", "null"})
_SYMBOL = re.compile(r"[€$£¥]")
_TAUSENDER = re.compile(r"[ \u00a0\u202f']")


class ZahlenFehler(ValueError):
    """Zahl nicht lesbar oder nicht exakt in Sats darstellbar."""


def parse_decimal(roh: str | None) -> Decimal | None:
    """Liest einen Betrag. Leere Zelle und ``-`` ergeben ``None``."""
    if roh is None:
        return None
    text = str(roh).strip()
    if not text or text.casefold() in _LEER:
        return None
    text = _SYMBOL.sub("", text)
    text = _TAUSENDER.sub("", text)
    text = text.replace("+", "")
    if text.endswith("-") and not text.startswith("-"):
        text = "-" + text[:-1]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        teile = text.replace("-", "").split(",")
        if len(teile) == 2 and len(teile[1]) in (1, 2, 3, 8) and len(teile[0].lstrip("0") or "0") <= 6:
            # 1,23 oder 1,23456789 (Dezimal) gegen 1,234 (Tausender, untypisch allein).
            # Eine einzelne Komma-Gruppe mit 3 Ziffern kann beides sein.
            # Europäische Dezimalstelle: wenn Nachkomma nicht genau 3 *oder*
            # der ganzzahlige Teil dreistellig-gruppiert wirkt. Sichere Regel:
            # genau 3 Nachkomma *und* Ganzteil bereits > 3 Stellen → Tausender.
            ganz, nach = teile
            ganz = ganz.lstrip("+-")
            if len(nach) == 3 and len(ganz) > 3:
                text = text.replace(",", "")
            else:
                text = text.replace(",", ".")
        else:
            text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ZahlenFehler("Zahl nicht lesbar.") from exc


def btc_nach_sats(wert: Decimal) -> int:
    """Wandelt BTC exakt in Sats. Mehr als acht Nachkommastellen sind ein Fehler."""
    sats = wert * SATOSHIS_JE_BTC
    ganz = sats.to_integral_value()
    if sats != ganz:
        raise ZahlenFehler("BTC-Betrag ist nicht exakt in Sats darstellbar.")
    return int(ganz)


def parse_btc_sats(roh: str | None) -> int | None:
    wert = parse_decimal(roh)
    if wert is None:
        return None
    return btc_nach_sats(wert)
