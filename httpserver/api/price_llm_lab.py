"""Price-/LLM-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

from typing import Any


def api_llm_status(state: AppState, query: dict) -> dict:
    """
    Assistenten-Anbindung: Banner-, Pillen- und Privacy-Felder.

    ``?check=1`` löst eine kurze Erreichbarkeitsprobe aus. Ohne Check bleibt
    die Pille grau (kein Rot-Flash vor dem ersten Versuch). Der API-Key
    kommt nicht in die Antwort.
    """
    from server import llm_mod

    check = query.get("check", ["0"])[0] in ("1", "true", "ja")
    return llm_mod.status_dict(state.env().values(), check=check)


def api_price(state: AppState, query: dict) -> dict:
    """
    Aktueller BTC-Spotkurs (Anzeige in der Kopfzeile).

    Keine Wallet-Daten — nur Fiat-Kurs über Mempool (optional eigene
    ``MEMPOOL_URL``) mit Coinbase-Fallback. Ergebnis wird unter
    ``immutable_cache/btc_price/`` kurz gecacht.
    """
    from server import (
        ApiError,
        price_mod,
    )

    roh = (query.get("currency", ["EUR"])[0] or "EUR").strip()
    try:
        waehrung = price_mod.normalisiere_waehrung(roh)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    mempool = (state.env().values().get("MEMPOOL_URL") or "").strip() or None
    try:
        # Kurzes Timeout: die Kopfzeile soll den Start nicht aufhalten.
        preis = price_mod.spot_preis(
            waehrung,
            immutable_cache_dir=state.immutable_cache_dir,
            mempool_url=mempool,
            timeout=5.0,
        )
    except price_mod.PriceError as exc:
        raise ApiError(502, str(exc)) from exc
    return preis.to_dict()


def api_price_history(state: AppState, query: dict) -> dict:
    """Stand der lokalen BTC-Tageskurs-Historie (EUR/USD).

    ``?series=1`` liefert zusätzlich die Tag→Preis-Map (für EUR-Umrechnung
    ausgegebener Beträge zum Ausgabedatum).
    """
    from server import price_mod

    from core import price_history_sync as hist_sync

    mit_serie = (query.get("series", ["0"])[0] or "").strip().lower() in (
        "1", "true", "ja", "yes", "on",
    )
    werte = state.env().values()
    roh = (query.get("currency", [""])[0] or "").strip()
    if roh:
        return {
            "histories": [
                price_mod.historie_status(
                    state.immutable_cache_dir, roh, mit_serie=mit_serie,
                ),
            ],
            "price_history_opt_in": True,
        }
    return {
        "histories": [
            price_mod.historie_status(
                state.immutable_cache_dir, w, mit_serie=mit_serie,
            )
            for w in sorted(price_mod.HISTORIE_WAEHRUNGEN)
        ],
        "price_history_opt_in": True,
    }


def api_price_history_sync(state: AppState, payload: dict | None = None) -> dict:
    """Manueller Historie-Nachzug (Lücken füllen — Bitstamp/CDD, sonst Mempool)."""
    from server import price_mod

    from core import price_history_sync as hist_sync

    _ = payload  # früher opt_in — Nachzug braucht keine Erlaubnis mehr
    logs: list[str] = []
    # Manueller API-Lauf: Tages-Stamp ignorieren, immer versuchen.
    ergebnisse = hist_sync.historie_nachziehen_alle(
        state.immutable_cache_dir,
        values=state.env().values(),
        on_log=logs.append,
        force=True,
    )
    for zeile in logs:
        print(zeile, flush=True)
    return {
        "ok": all(e.get("ok") for e in ergebnisse),
        "results": ergebnisse,
        "log": logs,
        "price_history_opt_in": True,
        "histories": [
            price_mod.historie_status(state.immutable_cache_dir, w)
            for w in sorted(price_mod.HISTORIE_WAEHRUNGEN)
        ],
    }


def api_price_import(state: AppState, payload: dict) -> dict:
    """
    CSV-Tageskurse (Datum/Preis) in den Kurs-Cache schreiben.

    Body: ``currency`` (EUR|USD), ``csv`` (Text), optional ``filename``,
    ``ersetzen`` (true = Serie verwerfen statt mergen).
    """
    from server import (
        ApiError,
        price_mod,
    )

    if not isinstance(payload, dict):
        raise ApiError(400, "JSON-Objekt erwartet.")
    roh_w = str(payload.get("currency") or "EUR")
    try:
        waehrung = price_mod.normalisiere_historie_waehrung(roh_w)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    csv_text = payload.get("csv")
    if csv_text is None:
        raise ApiError(400, "Feld „csv“ fehlt.")
    if not isinstance(csv_text, str):
        raise ApiError(400, "Feld „csv“ muss Text sein.")
    if len(csv_text) > 20 * 1024 * 1024:
        raise ApiError(400, "CSV zu groß (max. 20 MB).")
    dateiname = str(payload.get("filename") or "").strip()[:200]
    ersetzen = bool(payload.get("ersetzen"))
    try:
        ergebnis = price_mod.importiere_kurs_csv(
            state.immutable_cache_dir,
            waehrung,
            csv_text,
            dateiname=dateiname,
            ersetzen=ersetzen,
        )
    except price_mod.PriceError as exc:
        raise ApiError(400, str(exc)) from exc
    return ergebnis


def api_llm_context(state: AppState, rest: list[str], query: dict) -> dict:
    """
    Reine Cache-Reader für Slash-Befehle.

    Kein Job, kein Node, kein Chat-Completion. Unbekannte Unterpfade 404.
    """
    from server import (
        ApiError,
        llm_ctx,
        _steuer_auswertung,
    )

    if not rest:
        raise ApiError(404, "Welcher Kontext? luecken, wallets, steuer, export.")
    ziel = rest[0]
    if ziel == "luecken":
        return llm_ctx.luecken(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
            jobs=state.jobs,
        )
    if ziel == "wallets":
        return llm_ctx.wallets(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
        )
    if ziel == "steuer":
        return llm_ctx.steuer_kompakt(_steuer_auswertung(state, query))
    if ziel == "export":
        art = (query.get("art") or ["legende"])[0].strip().lower()
        if art not in llm_ctx.EXPORT_ARTEN:
            raise ApiError(400, "art muss legende, markdown oder brief sein.")
        return llm_ctx.export_aus(_steuer_auswertung(state, query), art)
    raise ApiError(404, f"Unbekannter Assistenten-Kontext: {ziel}")


def _llm_werkzeug(state: AppState, name: str, args: dict) -> str:
    """Cache-Reader für den Chat — dieselben Texte wie die Slash-Befehle."""
    from server import (
        llm_ctx,
        _steuer_auswertung,
    )

    args = args or {}
    if name == "luecken":
        return llm_ctx.luecken(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
            jobs=state.jobs,
        )["text"]
    if name == "wallets":
        return llm_ctx.wallets(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
        )["text"]
    query: dict[str, list[str]] = {}
    jahr = args.get("jahr")
    if jahr not in (None, ""):
        query["jahr"] = [str(jahr)]
    if name == "steuer":
        return llm_ctx.steuer_kompakt(_steuer_auswertung(state, query))["text"]
    if name in ("export", "export_legende", "export_markdown", "export_brief"):
        art = str(args.get("art") or "").strip().lower()
        if not art:
            art = {
                "export_legende": "legende",
                "export_markdown": "markdown",
                "export_brief": "brief",
            }.get(name, "legende")
        return llm_ctx.export_aus(_steuer_auswertung(state, query), art)["text"]
    return f"Werkzeug „{name}“ ist nicht erlaubt."


def api_llm_chat(state: AppState, payload: dict) -> dict:
    """
    Eine Freitext-Runde. Remote nur mit Opt-in und Key aus der .env.

    Der Client schickt nur user/assistant-Nachrichten. Systemprompt und
    Werkzeuge setzt der Server. Kein Job-Start.
    """
    from server import (
        ApiError,
        llm_mod,
        llm_chat,
    )

    if not isinstance(payload, dict):
        raise ApiError(400, "Ungültiger Körper.")
    cfg = llm_mod.lese_llm_chat_einstellungen(state.env().values())
    try:
        return llm_chat.fuehre_chat(
            cfg,
            payload.get("messages"),
            tools_fn=lambda name, args: _llm_werkzeug(state, name, args),
        )
    except llm_chat.LlmFehler as exc:
        raise ApiError(exc.status, exc.message) from exc
