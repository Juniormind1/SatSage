"""
Steuerjahr seitenweise (ISSUES P2): Summen, Kennzahlen und Zeitstrahl rechnen
über alles, geschnitten werden nur die Zeilen der UTXO-Gruppen und der
Veräußerungen.

Der Stichwortfilter ist derselbe wie im Browser (``parseKopfFilter`` +
``_kopfFilterLeafOk`` auf den ``data-*``-Feldern, die ``steuerjahr.js`` an
die Zeilen schreibt) — nur eben über alle Seiten statt über die gezeichnete.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from core import listen_fenster as lf

TEILE = ("erfuellt", "offen", "abgaenge")


def haltefrist_beschriftung(erfuellt: bool, neuvermoegen: bool, hat_stichtag: bool,
                            lang: str) -> str:
    """Port von ``haltefristBeschriftung`` (web/format.js)."""
    kat = lf._katalog(lang)
    lage = kat.get("tax.haltefristOut" if erfuellt else "tax.haltefristIn", "")
    if not hat_stichtag:
        return lage
    schnitt = kat.get("tax.afterCutoff" if neuvermoegen else "tax.beforeCutoff", "")
    return f"{lage}, {schnitt}"


def _js_text(wert) -> str:
    return "" if wert is None else str(wert)


def utxo_zeile(e: dict, hat_stichtag: bool, lang: str) -> dict:
    """``data-*`` einer UTXO-Zeile wie ``zeichneSteuerUtxoZeile``."""
    if e.get("key"):
        key = str(e["key"])
    elif e.get("txid") is None or e.get("vout") is None:
        key = ""
    else:
        key = f"{e['txid']}:{e['vout']}"
    labels = [e.get("wallet"), e.get("herkunft"), e.get("grundlage_label"), e.get("txid"),
              haltefrist_beschriftung(bool(e.get("erfuellt")), bool(e.get("neuvermoegen")),
                                      hat_stichtag, lang)]
    return {
        "key": key,
        "address": _js_text(e.get("address")) if e.get("address") else "",
        "value_sats": e.get("value_sats"),
        "time_label": " ".join(_js_text(x) for x in (e.get("datum"), e.get("frist_ende")) if x),
        "event_ts": e.get("time_ts") or None,
        "labels": " ".join(_js_text(x) for x in labels if x),
    }


def abgang_zeile(a: dict, hat_stichtag: bool, lang: str) -> dict:
    """``data-*`` einer Veräußerungszeile wie ``zeichneAbgaenge``."""
    if a.get("txid") is not None and a.get("vout") is not None:
        key = f"{a['txid']}:{a['vout']}"
    else:
        key = _js_text(a.get("abgang_txid") or a.get("txid") or "")
    ts = int(a.get("abgang_time_ts") or a.get("time_ts") or 0)
    boersen = [z.get("name") for z in (a.get("exchange_spends") or []) if isinstance(z, dict)]
    labels = [a.get("wallet"), a.get("abgang_txid"), a.get("txid"), *boersen,
              haltefrist_beschriftung(bool(a.get("frist_erfuellt")), bool(a.get("neuvermoegen")),
                                      hat_stichtag, lang)]
    return {
        "key": key,
        "address": _js_text(a.get("address")) if a.get("address") else "",
        "value_sats": a.get("value_sats"),
        "time_label": " ".join(_js_text(x) for x in (a.get("datum"), a.get("abgang_datum")) if x),
        "event_ts": ts if ts > 0 else None,
        "labels": " ".join(_js_text(x) for x in labels if x),
    }


def zeile_ok(z: dict, f: dict) -> bool:
    """Port von ``_kopfFilterLeafOk`` + ``_kopfFilterHaystack`` auf einer Zeile."""
    if f["leer"]:
        return True
    try:
        sats = float(z["value_sats"]) if z["value_sats"] is not None else math.nan
    except (TypeError, ValueError):
        sats = math.nan
    if f["min_sats"] is not None and (math.isnan(sats) or not sats > f["min_sats"]):
        return False
    if f["max_sats"] is not None and (math.isnan(sats) or not sats < f["max_sats"]):
        return False
    if f["after_ts"] is not None or f["before_ts"] is not None:
        ts = z["event_ts"]
        if not ts or ts <= 0:
            return False
        if f["after_ts"] is not None and not ts >= f["after_ts"]:
            return False
        if f["before_ts"] is not None and not ts < f["before_ts"]:
            return False
    if not f["terms"]:
        return True
    key = z["key"]
    txid = key.split(":")[0] if ":" in key else key
    heu = " ".join([key, txid, z["address"], z["time_label"], z["labels"], ""]).lower()
    return all(t in heu for t in f["terms"])


def _bewertungs_ts(e: dict) -> int:
    ts = int(e.get("time_ts") or 0)
    return ts if ts > 1_000_000_000 else 0


def _abgang_ts(a: dict) -> int:
    return int(a.get("abgang_time_ts") or 0) or _bewertungs_ts(a)


def gemeinsamer_ts(items: list[dict], ts_fn=_bewertungs_ts) -> int | None:
    """Port von ``gemeinsamerAtTs``: Zeitpunkt nur bei einheitlichem UTC-Tag."""
    if not items:
        return None
    tage = set()
    probe = 0
    for item in items:
        ts = int(ts_fn(item) or 0)
        if ts <= 0:
            return None
        tage.add(datetime.fromtimestamp(ts, tz=timezone.utc).date())
        probe = ts
        if len(tage) > 1:
            return None
    return probe


def _teil(zeilen: list[dict], daten: list[dict], f: dict, offset: int, limit: int,
          ts_fn) -> dict:
    treffer = [e for e, z in zip(daten, zeilen) if zeile_ok(z, f)]
    offset = max(0, int(offset or 0))
    limit = max(0, min(int(limit or 0), lf.MAX_LIMIT))
    return {
        "items": treffer[offset:offset + limit],
        "offset": offset,
        "limit": limit,
        "total": len(treffer),
        "sats": sum(int(e.get("value_sats") or 0) for e in treffer),
        "voll_count": len(daten),
        "voll_sats": sum(int(e.get("value_sats") or 0) for e in daten),
        "gemeinsam_ts": gemeinsamer_ts(daten, ts_fn),
    }


def fenster(auswertung: dict, *, teil: str = "alle", offset: int = 0, limit: int = 10,
            limit_abgaenge: int | None = None, f: dict | None = None,
            lang: str = "de") -> dict:
    """
    Seitenweise Antwort aus einer vollständigen Auswertung.

    ``teil=alle``: alles außer den Zeilenlisten, dazu die ersten Fenster je
    Gruppe (``steuer_gruppen``) und der Veräußerungen (``abgaenge_fenster``).
    ``teil=erfuellt|offen|abgaenge``: nur dieses Fenster — der Zeitstrahl
    geht beim Blättern nicht jedes Mal neu über die Leitung.
    ``teil=zeilen``: die ersten Fenster aller drei Listen ohne den Rest
    (neuer Filter).
    """
    f = f or lf.parse_filter("")
    hat_stichtag = bool(auswertung.get("stichtag_regel"))
    alle = list(auswertung.get("eintraege") or [])
    gruppen = {
        "erfuellt": [e for e in alle if e.get("erfuellt")],
        "offen": [e for e in alle if not e.get("erfuellt")],
    }
    abgaenge = list(auswertung.get("abgaenge") or [])

    def g_teil(name: str, lim: int, off: int) -> dict:
        daten = gruppen[name]
        zeilen = [utxo_zeile(e, hat_stichtag, lang) for e in daten] if not f["leer"] else [None] * len(daten)
        return _teil(zeilen, daten, f, off, lim, _bewertungs_ts)

    def ab_teil(lim: int, off: int) -> dict:
        zeilen = [abgang_zeile(a, hat_stichtag, lang) for a in abgaenge] if not f["leer"] else [None] * len(abgaenge)
        return _teil(zeilen, abgaenge, f, off, lim, _abgang_ts)

    lim_ab = limit if limit_abgaenge is None else limit_abgaenge
    if teil in TEILE:
        antwort = {"jahr": auswertung.get("jahr"), "teil": teil, "seitenweise": True}
        if teil == "abgaenge":
            antwort["abgaenge_fenster"] = ab_teil(lim_ab, offset)
        else:
            antwort["steuer_gruppen"] = {teil: g_teil(teil, limit, offset)}
        return antwort
    if teil == "zeilen":
        return {
            "jahr": auswertung.get("jahr"), "teil": teil, "seitenweise": True,
            "steuer_gruppen": {name: g_teil(name, limit, 0) for name in ("erfuellt", "offen")},
            "abgaenge_fenster": ab_teil(lim_ab, 0),
        }

    antwort = {k: v for k, v in auswertung.items() if k not in ("eintraege", "abgaenge", "_objekte")}
    antwort["seitenweise"] = True
    antwort["teil"] = "alle"
    antwort["steuer_gruppen"] = {name: g_teil(name, limit, 0) for name in ("erfuellt", "offen")}
    antwort["abgaenge_fenster"] = ab_teil(lim_ab, 0)
    antwort["kennzahlen_ts"] = {
        "gesamt": gemeinsamer_ts(alle),
        "erfuellt": gemeinsamer_ts(gruppen["erfuellt"]),
        "offen": gemeinsamer_ts(gruppen["offen"]),
        "ungeprueft": gemeinsamer_ts([e for e in alle if not e.get("geprueft")]),
    }
    # „klären“ für gelbe UTXOs braucht alle Schlüssel, nicht nur die Seite.
    antwort["gelb_keys"] = [f"{e.get('txid')}:{e.get('vout')}" for e in alle
                            if e.get("geprueft") and not e.get("erfuellt")]
    return antwort
