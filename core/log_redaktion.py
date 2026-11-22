"""Zentrale Redaktion für Logs: Aussagekräftig, ohne Geheimnisse.

Kennungen (XPUBs, Adressen, TxIDs, Börsen-IDs, Dateinamen, Pfade) werden
nicht vollständig geschrieben. Als stabile Referenz dient höchstens
``ref:`` plus die ersten acht Hex-Zeichen von SHA-256. Exakte Beträge
werden nicht zusammen mit einer Uhrzeit geloggt; stattdessen
Größenordnung und Kalendertag.
"""
from __future__ import annotations

import hashlib
import logging
import re
import traceback
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Iterable

LOGGER_NAME = "satsage.boerse"

# Präfixe nach BIP-32 / SLIP-132, öffentlich und privat.
_RE_XPUB = re.compile(
    r"\b[tuvxyzTUVXYZ](?:pub|prv)[1-9A-HJ-NP-Za-km-z]{80,}\b"
)
_RE_BECH32 = re.compile(
    r"\b(?:bc|tb|bcrt|tbrt)1[02-9ac-hj-np-z]{6,}\b",
    re.I,
)
_RE_BASE58 = re.compile(
    r"\b[13mn2][a-km-zA-HJ-NP-Z1-9]{25,34}\b"
)
_RE_TXID = re.compile(r"\b[0-9a-fA-F]{64}\b")
_RE_LN = re.compile(r"\bln(?:bc|tb|crt)[0-9a-z]{10,}\b", re.I)
_RE_KRAKEN_ID = re.compile(
    r"\b[LT][A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{6}\b"
)
_RE_SYN_ID = re.compile(r"\b[A-Z]{2,8}SYN-[0-9A-Z]+\b")
_RE_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_RE_UNIX_HOME = re.compile(r"(?i)(?:/Users|/home)/[^\s,;:'\"]+")
_RE_WIN_HOME = re.compile(
    r"(?i)(?:[A-Z]:\\Users\\|[A-Z]:\\Dokumente und Einstellungen\\)[^\s,;]+"
)
_RE_TILDE = re.compile(r"~/[^\s,;:'\"]+")
_RE_DATEINAME = re.compile(
    r"(?i)(?<![A-Za-z0-9._-])[\w.-]+\.(?:csv|xlsx|xls|tsv|json|txt)(?![A-Za-z0-9._-])"
)

_MUSTER = (
    _RE_XPUB,
    _RE_LN,
    _RE_BECH32,
    _RE_KRAKEN_ID,
    _RE_SYN_ID,
    _RE_UUID,
    _RE_TXID,
    _RE_BASE58,
    _RE_UNIX_HOME,
    _RE_WIN_HOME,
    _RE_TILDE,
    _RE_DATEINAME,
)


def ref_hash(wert: str | None) -> str:
    """Stabile Kurzreferenz, nie der Originalwert."""
    if wert is None or str(wert).strip() == "":
        return "ref:leer"
    text = str(wert).strip()
    if re.fullmatch(r"[0-9a-fA-F]+", text) and len(text) % 2 == 0:
        text = text.lower()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"ref:{digest}"


def _ersetzen(m: re.Match[str]) -> str:
    return ref_hash(m.group(0))


def redigiere(text: str, extra: Iterable[str] = ()) -> str:
    """Ersetzt Geheimnisse im Text durch ``ref:``-Präfixe."""
    if text is None:
        return ""
    aus = str(text)
    # Längere Extra-Werte zuerst, damit Teilstrings nicht zuerst greifen.
    bekannt = sorted(
        {str(v) for v in extra if v},
        key=len,
        reverse=True,
    )
    for wert in bekannt:
        if wert and wert in aus:
            aus = aus.replace(wert, ref_hash(wert))
    for muster in _MUSTER:
        aus = muster.sub(_ersetzen, aus)
    return aus


def groessenordnung(betrag: object, *, einheit: str = "") -> str:
    """Zehnerpotenz, kein exakter Betrag."""
    if betrag is None or betrag == "":
        return "ohne Betrag"
    try:
        wert = abs(Decimal(str(betrag)))
    except (InvalidOperation, ValueError, TypeError):
        return "Betrag unlesbar"
    if wert == 0:
        return "0"
    exponent = int(wert.log10().to_integral_value(rounding=ROUND_FLOOR))
    suffix = f" {einheit}" if einheit else ""
    return f"10^{exponent}{suffix}"


def tag_iso(ts: int | float | None) -> str:
    """Kalendertag in UTC, ohne Uhrzeit."""
    if ts is None:
        return "ohne Datum"
    try:
        wert = int(ts)
    except (TypeError, ValueError):
        return "ohne Datum"
    if wert <= 0:
        return "ohne Datum"
    import datetime

    return datetime.datetime.fromtimestamp(wert, tz=datetime.timezone.utc).strftime(
        "%Y-%m-%d"
    )


def ausnahme_text(exc: BaseException) -> str:
    """Exception-Typ und Stack, Werte und Pfade redigiert."""
    typ = type(exc).__name__
    msg = redigiere(str(exc))
    roh = traceback.format_exception(type(exc), exc, exc.__traceback__)
    koerper = redigiere("".join(roh))
    return f"{typ}: {msg}\n{koerper}".rstrip()


def geheimnisse_aus(*teile: object) -> tuple[str, ...]:
    """Sammelt typische Kennungsfelder aus Buchungen, Diktaten und Listen."""
    gefunden: list[str] = []

    def _nimm(wert: object) -> None:
        if wert is None:
            return
        if isinstance(wert, (str, int)):
            text = str(wert).strip()
            if text:
                gefunden.append(text)
            return
        if isinstance(wert, dict):
            for schluessel, inhalt in wert.items():
                name = str(schluessel).lower()
                if name in {
                    "ref", "txid", "adresse", "address", "xpub", "filename",
                    "dateiname", "auszahlung_ref", "gruppe", "destination",
                    "transaction hash", "id", "konto",
                }:
                    _nimm(inhalt)
                elif isinstance(inhalt, (dict, list, tuple)):
                    _nimm(inhalt)
            return
        if isinstance(wert, (list, tuple, set)):
            for item in wert:
                _nimm(item)
            return
        for attr in (
            "ref", "txid", "adresse", "address", "auszahlung_ref",
            "gruppe", "filename",
        ):
            if hasattr(wert, attr):
                _nimm(getattr(wert, attr, None))

    for teil in teile:
        _nimm(teil)
    return tuple(dict.fromkeys(gefunden))


def spalten_anzeige(spalten: Iterable[str]) -> list[str]:
    """Spaltennamen für GUI/API, Kennungen darin redigiert."""
    return [redigiere(str(s)) for s in spalten]


class RedaktionsFilter(logging.Filter):
    """Hängt an ``satsage.boerse`` und entfernt Geheimnisse aus jeder Zeile."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            extra = getattr(record, "geheim", ()) or ()
            text = record.getMessage()
            record.msg = redigiere(text, extra)
            record.args = ()
            if record.exc_info and record.exc_info[1] is not None:
                record.msg = record.msg + "\n" + ausnahme_text(record.exc_info[1])
                record.exc_info = None
                record.exc_text = None
        except Exception:
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.msg = "Logzeile konnte nicht redigiert werden."
        return True


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    log = logging.getLogger(name)
    if not any(isinstance(f, RedaktionsFilter) for f in log.filters):
        log.addFilter(RedaktionsFilter())
    return log


def schreibe(ereignis: str, /, *, stufe: int = logging.INFO, **felder: object) -> None:
    """Eine strukturierte, bereits redigierte Logzeile."""
    teile = [str(ereignis)]
    geheim = geheimnisse_aus(felder)
    for name, wert in felder.items():
        if name.startswith("_"):
            continue
        teile.append(f"{name}={_feld_text(name, wert)}")
    get_logger().log(stufe, " ".join(teile), extra={"geheim": geheim})


def schreibe_ausnahme(
    ereignis: str,
    exc: BaseException,
    /,
    *,
    stufe: int = logging.ERROR,
    **felder: object,
) -> None:
    felder = dict(felder)
    felder["ausnahme"] = type(exc).__name__
    felder["stack"] = ausnahme_text(exc)
    schreibe(ereignis, stufe=stufe, **felder)


def _feld_text(name: str, wert: object) -> str:
    if wert is None:
        return "-"
    if name in {"dauer_ms", "zeile", "zeilen", "vout", "fassung"} or name.startswith(
        ("n_", "anzahl_")
    ):
        return str(wert)
    if name in {"txid", "adresse", "address", "ref", "auszahlung_ref", "xpub",
                "filename", "dateiname", "pfad", "gruppe", "id"}:
        return ref_hash(str(wert) if wert is not None else None)
    if name in {"betrag", "sats", "amount", "fiat"}:
        einheit = "sat" if name == "sats" else ""
        return groessenordnung(wert, einheit=einheit)
    if name in {"zeit_ts", "ts"}:
        return tag_iso(wert if isinstance(wert, (int, float)) else None)
    if isinstance(wert, (int, float, Decimal)) and not isinstance(wert, bool):
        return str(wert)
    if isinstance(wert, (list, tuple)):
        return ",".join(_feld_text(name, v) for v in wert)
    if isinstance(wert, dict):
        innen = " ".join(f"{k}={_feld_text(k, v)}" for k, v in wert.items())
        return "{" + innen + "}"
    return redigiere(str(wert))


def dauer_ms(start: float) -> int:
    import time

    return int(round((time.perf_counter() - start) * 1000))
