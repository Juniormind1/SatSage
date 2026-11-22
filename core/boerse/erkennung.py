"""Formaterkennung über die Kopf-Signatur. Unbekannte Varianten werden abgelehnt."""
from __future__ import annotations

from dataclasses import dataclass

from core.boerse.modell import FormatFehler

# Erste Zeilen, in denen der Kopf stehen darf (Präambel darüber).
_MAX_KOPF = 12


@dataclass(frozen=True)
class Erkannt:
    boerse: str
    variante: str
    kopf_zeile: int
    trennzeichen: str
    spalten: tuple[str, ...]
    zeilen: tuple[str, ...]


def _norm_name(name: str) -> str:
    t = (name or "").strip().strip('"').strip("'")
    t = t.replace("\ufeff", "")
    t = t.lower().replace("_", " ").replace("-", " ")
    return " ".join(t.split())


def _spalten(zeile: str, trenn: str) -> tuple[str, ...]:
    teile = [t.strip().strip('"').strip("'") for t in zeile.split(trenn)]
    return tuple(t for t in teile if t != "" or len(teile) > 1)


def _trennzeichen(zeile: str) -> str:
    # Ohne Quoting-Parser: typische Köpfe enthalten keine Trennzeichen in Namen.
    return ";" if zeile.count(";") > zeile.count(",") else ","


def _menge(spalten: tuple[str, ...]) -> frozenset[str]:
    return frozenset(_norm_name(s) for s in spalten if s)


def _variante(boerse: str, basis: str, namen: frozenset[str]) -> str:
    if boerse == "kraken" and basis == "ledgers":
        if "wallet" not in namen:
            return "ledgers-ohne-wallet"
        return "ledgers"
    if boerse == "coinbase":
        if "id" in namen and "price currency" in namen:
            return "2024" if "sender address" not in namen else "2024-adressen"
        if "price currency" in namen and "id" not in namen:
            return "2024-ohne-id"
        if "spot price currency" in namen and "fees and/or spread" in namen:
            return "2023"
        if "spot price currency" in namen:
            return "2021"
        for prefix in ("eur", "usd"):
            if f"{prefix} subtotal" in namen or f"{prefix} spot price at transaction" in namen:
                return f"2019-{prefix}"
        return "unbekannt"
    if boerse == "strike":
        if "amount eur" in namen:
            return "statement-eur"
        if "amount usd" in namen:
            return "statement-usd"
        return "statement"
    return basis


def _passt(namen: frozenset[str], pflicht: frozenset[str], verboten: frozenset[str]) -> bool:
    if not pflicht <= namen:
        return False
    if namen & verboten:
        return False
    return True


# Pflichtspalten und Spalten, die die Signatur ausschließen.
_SIGNATUR = (
    (
        "kraken",
        "trades",
        frozenset({"txid", "ordertxid", "pair", "time", "vol"}),
        frozenset({"refid", "transaction type", "quantity transacted", "reference"}),
    ),
    (
        "kraken",
        "ledgers",
        frozenset({"txid", "time", "type", "asset", "amount"}),
        frozenset({"ordertxid", "transaction type", "quantity transacted", "reference"}),
    ),
    (
        "coinbase",
        "statement",
        frozenset({"timestamp", "transaction type", "asset", "quantity transacted", "notes"}),
        frozenset({"ordertxid", "refid", "transaction hash"}),
    ),
    (
        "strike",
        "statement",
        frozenset({"reference", "transaction type"}),
        frozenset({"ordertxid", "refid", "quantity transacted"}),
    ),
)


def _ist_praeambel(zeile: str, trenn: str) -> bool:
    kopf = zeile.strip().lstrip("\ufeff")
    if not kopf:
        return True
    niedrig = kopf.casefold()
    if niedrig in {"transactions", "transaction history", "account statement"}:
        return True
    if niedrig.startswith("user,") or niedrig.startswith("user;"):
        return True
    return False


def erkenne(text: str) -> Erkannt:
    """Erkennt Börse und Variante. Unbekannter Kopf wirft ``FormatFehler``."""
    if text.startswith("\ufeff"):
        text = text[1:]
    rohzeilen = text.splitlines()
    if not rohzeilen:
        raise FormatFehler("Datei ist leer.")
    letzter_kopf: tuple[str, ...] = ()
    for nr, zeile in enumerate(rohzeilen[:_MAX_KOPF], 1):
        if not zeile.strip():
            continue
        trenn = _trennzeichen(zeile)
        if _ist_praeambel(zeile, trenn):
            continue
        spalten = _spalten(zeile, trenn)
        namen = _menge(spalten)
        if len(namen) < 3:
            continue
        if not any(any(c.isalpha() for c in n) for n in namen):
            continue
        letzter_kopf = tuple(_norm_name(s) for s in spalten)
        for boerse, basis, pflicht, verboten in _SIGNATUR:
            if _passt(namen, pflicht, verboten):
                if boerse == "strike" and "date & time (utc)" not in namen and "date & time" not in namen:
                    # Strike braucht eine Zeitspalte; getrennte Datum/Zeit-Fassungen
                    # sind unbestätigt und werden nicht geraten.
                    continue
                return Erkannt(
                    boerse=boerse,
                    variante=_variante(boerse, basis, namen),
                    kopf_zeile=nr,
                    trennzeichen=trenn,
                    spalten=tuple(_norm_name(s) for s in spalten),
                    zeilen=tuple(rohzeilen[nr:]),
                )
        # Eine kopfähnliche Zeile ohne Signatur wird nicht als Daten weitergesucht.
        raise FormatFehler("Format nicht erkannt", letzter_kopf)
    raise FormatFehler("Format nicht erkannt", letzter_kopf)
