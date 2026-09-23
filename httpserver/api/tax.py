"""Steuerjahr-/Tax-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

from typing import Any


def api_save_steuer(state: AppState, payload: dict) -> dict:
    """
    Speichert Haltefrist, Stichtagsregel und Anschaffungslesart.

    Die Haltefrist ist die Zahl der Jahre bis zur Steuerfreiheit (Vorgabe 1,
    Deutschland). Der Stichtag ist optional — etwa der österr. Altbestand
    (28.02.2021): Anschaffungen danach werden nicht durch Halten steuerfrei.
    Leer schaltet die Cutoff-Regel aus.

    *anschaffung*: ``juengste`` (defensiv, Default) oder ``aelteste`` (offensiv).
    """
    from server import (
        ApiError,
        tax_mod,
    )

    try:
        frist = int(payload.get("haltefrist_jahre", tax_mod.STANDARD_HALTEFRIST_JAHRE))
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Haltefrist muss eine ganze Zahl von Jahren sein.") from exc
    frist = max(0, min(tax_mod.HALTEFRIST_MAX_JAHRE, frist))

    roh = payload.get("stichtag")
    if roh is None:
        roh = ""
    try:
        tag = tax_mod.parse_stichtag(str(roh))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    env = state.env()
    bisher = tax_mod.lese_steuer_einstellungen(env.values())
    if "anschaffung" in payload:
        anschaffung = tax_mod.parse_anschaffung(payload.get("anschaffung"))
    else:
        anschaffung = bisher["anschaffung"]

    env.apply({
        "STEUER_HALTEFRIST_JAHRE": str(frist),
        "STEUER_STICHTAG": tax_mod.format_stichtag(tag),
        "STEUER_ANSCHAFFUNG": anschaffung,
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {
        "saved": True,
        "steuer": tax_mod.lese_steuer_einstellungen(env.values()),
    }


def api_save_steuer_person(state: AppState, payload: dict) -> dict:
    """
    Speichert persönliche Daten und Finanzamt-Angaben für HTML/CSV-Berichte.

    Leere Felder → Env-Key entfernen → Name/Steuernummer/Anschrift wieder
    Donald-Duck-Defaults; optionale Felder (E-Mail, Finanzamt, …) bleiben leer.
    """
    from server import ApiError

    from core import selbstanzeige as sa_mod

    def _feld(*keys: str) -> str:
        for key in keys:
            if key in payload and payload.get(key) is not None:
                return str(payload.get(key) or "").strip()
        return ""

    name = _feld("name", "person_name")
    steuernummer = _feld("steuernummer", "tax_id")
    anschrift = _feld("anschrift", "address", "adresse")
    email = _feld("email", "e_mail", "mail")
    finanzamt = _feld("finanzamt", "tax_office")
    finanzamt_anschrift = _feld(
        "finanzamt_anschrift", "finanzamt_address", "tax_office_address",
    )
    sachbearbeiter = _feld("sachbearbeiter", "case_worker", "clerk")

    if len(name) > 200:
        raise ApiError(400, "Name ist zu lang (max. 200 Zeichen).")
    if len(steuernummer) > 80:
        raise ApiError(400, "Steuernummer ist zu lang (max. 80 Zeichen).")
    if len(anschrift) > 400:
        raise ApiError(400, "Anschrift ist zu lang (max. 400 Zeichen).")
    if len(email) > 200:
        raise ApiError(400, "E-Mail ist zu lang (max. 200 Zeichen).")
    if email and ("@" not in email or " " in email):
        raise ApiError(400, "E-Mail sieht ungültig aus.")
    if len(finanzamt) > 200:
        raise ApiError(400, "Finanzamt ist zu lang (max. 200 Zeichen).")
    if len(finanzamt_anschrift) > 400:
        raise ApiError(400, "Finanzamt-Anschrift ist zu lang (max. 400 Zeichen).")
    if len(sachbearbeiter) > 200:
        raise ApiError(400, "Sachbearbeiter ist zu lang (max. 200 Zeichen).")

    env = state.env()
    env.apply({
        "STEUER_PERSON_NAME": name or None,
        "STEUER_PERSON_STEUERNUMMER": steuernummer or None,
        "STEUER_PERSON_ANSCHRIFT": anschrift or None,
        "STEUER_PERSON_EMAIL": email or None,
        "STEUER_PERSON_FINANZAMT": finanzamt or None,
        "STEUER_PERSON_FINANZAMT_ANSCHRIFT": finanzamt_anschrift or None,
        "STEUER_PERSON_SACHBEARBEITER": sachbearbeiter or None,
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {"saved": True, "person": sa_mod.lese_steuer_person(env.values())}


def api_tax(state: AppState, query: dict) -> dict:
    from server import _steuer_auswertung

    auswertung = _steuer_auswertung(state, query)
    auswertung.pop("_objekte", None)
    return auswertung


def api_selbstanzeige_kandidaten(state: AppState, query: dict) -> dict:
    from server import (
        ApiError,
        _steuer_grundlage,
        tax_mod,
    )

    from core import selbstanzeige as sa

    utxos, _ohne = _steuer_grundlage(state)
    try:
        jahr = int(query.get("jahr", [""])[0])
    except (ValueError, TypeError, IndexError):
        jahre = tax_mod.verfuegbare_jahre(utxos)
        jahr = jahre[0] if jahre else __import__("datetime").date.today().year
    txid = (query.get("txid", [""])[0] or "").strip() or None
    try:
        return sa.kandidaten(
            utxos,
            jahr,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            txid=txid,
        )
    except ValueError as exc:
        # z. B. ungültige TxID im Filterfeld
        raise ApiError(400, str(exc)) from exc
