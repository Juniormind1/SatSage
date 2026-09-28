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


def api_tax(
    state: AppState,
    query: dict,
    accept_language: str | None = None,
    client_lang: str | None = None,
) -> dict:
    from server import _steuer_auswertung, _ui_lang_fuer_web

    # Ohne jeden Header (Export, LLM, Tests) bleibt der deutsche Wortlaut.
    # Die englische Web-Vorgabe gilt nur, wenn ein Browser Accept-Language
    # schickt und keine Wahl mitgibt.
    if client_lang is None and accept_language is None:
        sprache = "de"
    else:
        sprache = _ui_lang_fuer_web(
            state.env().values(), accept_language, client_lang
        )
    if (query.get("seite") or [""])[0] == "1":
        # Seitenweise (ISSUES P2): Summen über alles, Zeilen nur im Fenster.
        from core import listen_fenster as lf
        from core import steuer_fenster

        auswertung = _steuer_auswertung_gecacht(state, query, sprache)
        lim_ab = lf.query_int(query, "limit_abgaenge", -1)
        return steuer_fenster.fenster(
            auswertung,
            teil=lf.query_text(query, "teil", "alle"),
            offset=lf.query_int(query, "offset", 0),
            limit=lf.query_int(query, "limit", 10),
            limit_abgaenge=None if lim_ab < 0 else lim_ab,
            f=lf.filter_aus_query(query),
            lang=lf.query_text(query, "lang", "") or sprache,
        )
    auswertung = _steuer_auswertung(state, query, lang=sprache)
    auswertung.pop("_objekte", None)
    return auswertung


#: Letzte Auswertungen für Seitenwechsel (ISSUES P2, Schritt 6): Blättern
#: rechnet nicht jedes Mal das ganze Jahr neu. Gültig, solange Parameter,
#: Sprache, Tag und der Abdruck der Caches/Einstellungen gleich bleiben.
_STEUER_FENSTER_CACHE = None


def _steuer_auswertung_gecacht(state: AppState, query: dict, sprache: str) -> dict:
    global _STEUER_FENSTER_CACHE
    import datetime

    from core import listen_fenster as lf
    from httpserver.api.listen_fenster import cache_abdruck
    from server import _steuer_auswertung

    if _STEUER_FENSTER_CACHE is None:
        _STEUER_FENSTER_CACHE = lf.KleinCache(2)
    def schluessel():
        return (
            tuple((query.get(k) or [None])[0]
                  for k in ("jahr", "frist", "stichtag", "anschaffung")),
            sprache,
            datetime.date.today().isoformat(),
            cache_abdruck(state, preise=True),
        )

    vorher = schluessel()
    auswertung = _STEUER_FENSTER_CACHE.hole(vorher)
    if auswertung is None:
        auswertung = _steuer_auswertung(state, query, lang=sprache)
        auswertung.pop("_objekte", None)
        # Die Rechnung kann eigene Adressen aus den Caches nachladen — der
        # Stand danach ist der, den die nächste Anfrage sieht.
        _STEUER_FENSTER_CACHE.lege(schluessel(), auswertung)
    return auswertung


def api_tax_herkunftsnetz(
    state: AppState,
    query: dict,
    accept_language: str | None = None,
    client_lang: str | None = None,
) -> dict:
    """
    Herkunftsnetz eines Bestandspunkts als Overlay (ISSUES: Steuerjahr ·
    Herkunftsnetz, Schritt 1).

    Nur lesend: dieselbe (gecachte) Auswertung wie ``/api/tax?seite=1`` für
    die Skala, der **eine** gespeicherte Baum des UTXO (LRU-1 aus
    ``/api/trace``) für das Netz. Ausgeliefert wird nur das flache Netz —
    kein Baum. Fehlt der Baum, sagt ``trace_fehlt`` das; die Oberfläche
    startet dann den begrenzten Steuer-Horizont-Lauf.
    """
    from core import herkunftsnetz, xpub_cache
    from httpserver.api.trace import _gespeicherter_baum
    from server import ApiError, _ui_lang_fuer_web, trace_mod

    ziel = trace_mod.parse_ziel(str((query.get("key") or [""])[0]))
    if ziel is None or ":" not in str((query.get("key") or [""])[0]):
        raise ApiError(400, "Bitte ein UTXO in der Form txid:vout angeben.")
    txid, vout = ziel
    fokus_key = f"{txid}:{vout}"

    if client_lang is None and accept_language is None:
        sprache = "de"
    else:
        sprache = _ui_lang_fuer_web(
            state.env().values(), accept_language, client_lang
        )
    auswertung = _steuer_auswertung_gecacht(state, query, sprache)
    skala = herkunftsnetz.skala_aus_auswertung(auswertung)
    events = (auswertung.get("zeitstrahl") or {}).get("events") or []
    fokus = next((e for e in events if e.get("key") == fokus_key), None)
    if skala is None or fokus is None:
        raise ApiError(404, "Dieses UTXO steht nicht im Bestand des Steuerjahres.")

    antwort = {
        "fokus_key": fokus_key,
        "fokus_pos": fokus.get("pos"),
        "fokus_y": fokus.get("y"),
        "vorfahren": [],
        "kanten": [],
        "trace_fehlt": True,
    }
    gespeichert = _gespeicherter_baum(state, txid, vout, mit_veraltet=False)
    baum = (gespeichert or {}).get("baum") or {}
    if not baum.get("found") or not baum.get("root"):
        return antwort

    def block_zeit(hoehe: int) -> int | None:
        return xpub_cache.load_cached_block_time(hoehe, state.immutable_cache_dir)

    netz = herkunftsnetz.flach(baum, fokus_key, skala, block_zeit=block_zeit)
    from core import wallets as wallets_mod

    namen = {
        str(e.display_name or "").strip(): wallets_mod.eintrag_id(e)
        for e in (state.entries or [])
        if str(e.display_name or "").strip()
    }
    for v in netz.get("vorfahren") or []:
        name = str(v.get("wallet") or "").strip()
        if name and name in namen:
            v["wallet_id"] = namen[name]
    antwort.update(netz)
    antwort.update({
        "trace_fehlt": False,
        "steuer_ausreichend": bool(baum.get("steuer_ausreichend")),
        "verfolgt_vollstaendig": bool(baum.get("verfolgt_vollstaendig")),
    })
    return antwort


def api_selbstanzeige_kandidaten(state: AppState, query: dict) -> dict:
    from server import (
        ApiError,
        _steuer_grundlage,
        tax_mod,
    )

    from core import selbstanzeige as sa

    def rechnen() -> dict:
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

    if (query.get("seite") or [""])[0] != "1":
        return rechnen()
    # Seitenweise (ISSUES P2): Zahlen über alles, Zeilen nur im Fenster.
    from core import listen_fenster as lf
    from core import steuer_fenster

    kandidaten = _sa_kandidaten_gecacht(state, query, rechnen)
    lim_u = lf.query_int(query, "limit_utxos", -1)
    return steuer_fenster.sa_fenster(
        kandidaten,
        teil=lf.query_text(query, "teil", "alle"),
        offset=lf.query_int(query, "offset", 0),
        limit=lf.query_int(query, "limit", 10),
        limit_utxos=None if lim_u < 0 else lim_u,
        f=lf.filter_aus_query(query),
        nur_werte=lf.query_text(query, "werte") == "1",
    )


#: Letzte Kandidatenlisten für Seitenwechsel — gleiche Gültigkeit wie oben.
_SA_FENSTER_CACHE = None


def _sa_kandidaten_gecacht(state: AppState, query: dict, rechnen) -> dict:
    global _SA_FENSTER_CACHE
    import datetime

    from core import listen_fenster as lf
    from httpserver.api.listen_fenster import cache_abdruck

    if _SA_FENSTER_CACHE is None:
        _SA_FENSTER_CACHE = lf.KleinCache(2)

    def schluessel():
        return (
            (query.get("jahr") or [None])[0],
            ((query.get("txid") or [""])[0] or "").strip(),
            datetime.date.today().isoformat(),
            cache_abdruck(state, preise=True),
        )

    kandidaten = _SA_FENSTER_CACHE.hole(schluessel())
    if kandidaten is None:
        kandidaten = rechnen()
        _SA_FENSTER_CACHE.lege(schluessel(), kandidaten)
    return kandidaten
