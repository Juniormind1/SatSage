#!/usr/bin/env python3
"""Sammel-Bündel im Regtest-Labor: eigener Eingang vor mehr als 20 fremden.

``generate_scenarios.py`` schreibt den Soll-Satz nach
``.data/scenario-report.json`` unter ``buendel``. Die Kette ist die
Wahrheit (Blockzeit der Sammel-Tx, Blockzeit des älteren eigenen
Eingangs). ``verify_quellen_inventar.py`` prüft danach die
Steuerzeile: das Anschaffungsdatum ist die Blockzeit der Sammel-Tx,
nie der ältere eigene Eingang.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

NAME = "Sammel-eigen-zuerst"


def schluessel(soll: dict) -> str:
    return f"{str(soll['txid']).strip().lower()}:{int(soll['vout'])}"


def lade_soll(pfad: Path) -> dict:
    """Soll aus dem Szenario-Bericht. Fehlt er, ist die Chain zu alt."""
    if not pfad.is_file():
        raise RuntimeError(
            f"Szenario-Bericht fehlt: {pfad}. Zuerst generate_scenarios.py."
        )
    report = json.loads(pfad.read_text(encoding="utf-8"))
    soll = report.get("buendel") if isinstance(report, dict) else None
    if not isinstance(soll, dict) or soll.get("name") != NAME:
        raise RuntimeError(
            "Bündel-Szenario fehlt im Szenario-Bericht. "
            "generate_scenarios.py braucht eine frische Chain."
        )
    for feld in ("txid", "vout", "block_time", "eigen_time"):
        if soll.get(feld) in (None, ""):
            raise RuntimeError(f"Bündel-Szenario ohne {feld}")
    return soll


def offen_ohne_erwartetes_buendel(offen: list[str], soll: dict) -> list[str]:
    """Das eine erwartete Bündel darf nach dem Klären offen bleiben."""
    ziel = schluessel(soll)
    return [k for k in offen if str(k).strip().lower() != ziel]


def stand_ohne_erwartetes_buendel(nach: dict, soll: dict) -> bool:
    """Nimmt das Bündel aus den offenen UTXOs und aus den roten Ringen.

    Der Baum bleibt unvollständig (fremde Eingänge nach dem ersten
    eigenen). Das ist genau ein roter Ring. Jeder weitere Ring bleibt
    stehen und fällt in der strengen Electrs-Prüfung auf.
    """
    vorher_offen = list(nach.get("offen") or [])
    hatte_ringe = "rote_keys" in nach
    vorher_ringe = list(nach.get("rote_keys") or [])
    nach["offen"] = offen_ohne_erwartetes_buendel(vorher_offen, soll)
    ringe = offen_ohne_erwartetes_buendel(vorher_ringe, soll)
    nach["rote_keys"] = ringe
    if hatte_ringe:
        nach["rote"] = len(ringe)
    return (
        len(nach["offen"]) < len(vorher_offen)
        or len(ringe) < len(vorher_ringe)
    )


def pruefe_zeile(
    zeile: dict,
    soll: dict,
    *,
    bezug: datetime,
    haltefrist_jahre: int,
    stichtag=None,
) -> list[str]:
    """
    Fehlertexte, leer wenn die Zeile die Kette trifft.

    Das Datum muss die Blockzeit der Sammel-Tx sein. Liegt diese noch
    in der Haltefrist, darf die Zeile nicht erfüllt und kein Los grün sein.
    """
    from core.tax import haltefrist_entscheidung

    fehler: list[str] = []
    block = int(soll["block_time"])
    eigen = int(soll["eigen_time"])
    if block <= eigen:
        fehler.append(
            "Szenario ungültig: die Sammel-Tx ist nicht jünger als der eigene Eingang"
        )
    try:
        ts = int(zeile.get("time_ts") or 0)
    except (TypeError, ValueError):
        ts = 0
    if ts != block:
        hinweis = f" (das ist der ältere eigene Eingang {eigen})" if ts == eigen else ""
        fehler.append(
            f"Anschaffung {ts} ist nicht die Blockzeit der Sammel-Tx {block}{hinweis}"
        )
    if zeile.get("untergrenze"):
        fehler.append("Untergrenze statt Bündel, vorsichtig")
    if not zeile.get("buendel_obergrenze"):
        fehler.append("Markierung Bündel (vorsichtig) fehlt")
    _ende, periode_erfuellt, _neu = haltefrist_entscheidung(
        datetime.fromtimestamp(block), bezug, int(haltefrist_jahre), stichtag,
    )
    # Liegt die Sammel-Tx schon außerhalb der Frist, ist Grün die richtige
    # Farbe. Riskant ist nur Grün, solange die Blockzeit noch in der Frist liegt.
    if periode_erfuellt:
        return fehler
    if zeile.get("erfuellt"):
        fehler.append(
            "Haltefrist erfüllt, obwohl die Sammel-Tx noch in der Frist liegt"
        )
    if "sats_gruen" not in zeile:
        fehler.append("Lot-Farben fehlen")
    elif int(zeile.get("sats_gruen") or 0) > 0:
        fehler.append(f"Los grün ({zeile.get('sats_gruen')} sats)")
    return fehler
