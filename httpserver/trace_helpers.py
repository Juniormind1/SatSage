"""Trace-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations


def _ingress_veraltet(eintrag: dict | None) -> bool:
    """
    Sagt, ob ein UTXO (noch einmal) verfolgt werden muss.

    Einträge aus der Zeit vor dem externen Anschaffungsdatum kennen den
    Schlüssel ``external_time_ts`` gar nicht. Sie ergäben im Steuerjahr
    dauerhaft „nur Wallet-Eingang", obwohl ein neuer Lauf das genaue Datum
    liefern könnte — sie gelten deshalb als offen.

    Ein Eintrag *mit* dem Schlüssel, aber ohne Wert, ist dagegen fertig: Dort
    hat die Datenquelle keine Blockzeiten der Vorgänger hergegeben, und ein
    weiterer Lauf brächte dasselbe Ergebnis.
    """
    if not eintrag:
        return True
    return "external_time_ts" not in eintrag


def _utxos_fuer_trace(
    state: AppState,
    *,
    wallet_id: str = "",
) -> list[dict]:
    """UTXOs aus dem Cache, optional auf ein Wallet gefiltert."""
    from server import (
        ApiError,
        utxos_mod,
        wallets_mod,
        _alle_gecachten_utxos,
    )

    kennung = (wallet_id or "").strip()
    if not kennung:
        return list(_alle_gecachten_utxos(state))
    entry = wallets_mod.find_entry(state.entries, kennung)
    if entry is None or not entry.is_valid():
        raise ApiError(404, "Wallet nicht gefunden.")
    gecacht = utxos_mod.load_cached_utxos(
        entry.analyse_schluessel,
        state.cache_dir,
        immutable_cache_dir=state.immutable_cache_dir,
    )
    return list(gecacht or [])


def _trace_offen_steuer(
    state: AppState,
    utxos: list[dict],
    eigene_jetzt,
) -> list[tuple[str, int]]:
    """
    UTXOs ohne steuerlich ausreichenden Herkunftsbaum.

    Reicht: Blätter extern/Coinbase **oder** Steuer-Horizont (vor Stichtag/
    Haltefrist-Anfang). Volle Graphen bis Coinbase sind nicht nötig.
    """
    from server import (
        main,
        trace_cache,
    )

    offen: list[tuple[str, int]] = []
    gesehen: set[tuple[str, int]] = set()
    for utxo in utxos:
        txid = str(utxo.get("txid") or "").strip()
        if not txid:
            continue
        try:
            vout = int(utxo.get("vout", 0))
        except (TypeError, ValueError):
            continue
        key = (txid, vout)
        if key in gesehen:
            continue
        gesehen.add(key)
        kopf = trace_cache.kopf(
            txid, vout, state.immutable_cache_dir, eigene_jetzt
        )
        if kopf is None:
            # Kein Baum: alter Ingress mit Extern reicht für Steuerjahr.
            if not _ingress_veraltet(
                main.load_utxo_ingress_cache(
                    txid, vout, state.immutable_cache_dir
                )
            ):
                continue
            offen.append(key)
            continue
        if kopf.get("veraltet"):
            offen.append(key)
            continue
        if kopf.get("vollstaendig") or kopf.get("steuer_ausreichend"):
            continue
        offen.append(key)
    return offen


def _trace_offen_basis(
    state: AppState,
    utxos: list[dict],
    eigene_jetzt,
) -> list[tuple[str, int]]:
    """
    Herkunft tracen: UTXOs ohne **vollen** Baum bis extern/Coinbase.

    Steuer-Horizont allein reicht nicht — diese Lücken werden nachgezogen,
    idealerweise auf dem gespeicherten origin_tree (kein Komplett-Neulauf).
    """
    from server import trace_cache

    offen: list[tuple[str, int]] = []
    gesehen: set[tuple[str, int]] = set()
    for utxo in utxos:
        txid = str(utxo.get("txid") or "").strip()
        if not txid:
            continue
        try:
            vout = int(utxo.get("vout", 0))
        except (TypeError, ValueError):
            continue
        key = (txid, vout)
        if key in gesehen:
            continue
        gesehen.add(key)
        kopf = trace_cache.kopf(
            txid, vout, state.immutable_cache_dir, eigene_jetzt
        )
        if kopf is None:
            offen.append(key)
            continue
        if kopf.get("veraltet"):
            offen.append(key)
            continue
        if kopf.get("vollstaendig"):
            continue
        offen.append(key)
    return offen


def _trace_offen_tief(
    state: AppState,
    utxos: list[dict],
    eigene_jetzt,
) -> list[tuple[str, int]]:
    """
    UTXOs ohne vollständigen Baum (rot/lila-Blätter) — auch wenn schon
    einmal getraced. Veraltete Bäume und fehlender Ingress ebenso.
    """
    # Gleicher Maßstab wie Herkunft-tracen-Massenlauf (voll bis extern).
    return _trace_offen_basis(state, utxos, eigene_jetzt)


def _stop_before_ts_aus_payload(roh: dict) -> int | None:
    """Steuer-Horizont aus Job-Payload (Jahr, Haltefrist, Stichtag)."""
    from server import tax_mod

    try:
        jahr = int(roh.get("jahr") or 0)
    except (TypeError, ValueError):
        jahr = 0
    if jahr < 2009:
        from datetime import datetime as _dt
        jahr = _dt.now().year
    try:
        frist = int(
            roh.get("haltefrist_jahre")
            if roh.get("haltefrist_jahre") is not None
            else roh.get("frist") or tax_mod.STANDARD_HALTEFRIST_JAHRE
        )
    except (TypeError, ValueError):
        frist = tax_mod.STANDARD_HALTEFRIST_JAHRE
    stichtag_roh = roh.get("stichtag") or roh.get("stichtag_iso") or ""
    stichtag_tag = tax_mod.parse_stichtag(
        str(stichtag_roh) if stichtag_roh else None
    )
    return tax_mod.stop_before_ts_fuer_steuer(jahr, frist, stichtag_tag)


def _trace_ein_utxo_tief(
    *,
    get_tx,
    txid: str,
    vout: int,
    eigene: set,
    wallet_ctx,
    cache_dir,
    immutable_cache_dir,
    fetch_addr,
    cache_source: str,
    progress=None,
    cancel_cb=None,
    folge_bundled: bool = True,
    folge_tx: bool = True,
    resume_origin: dict | None = None,
) -> dict:
    """
    Ein UTXO wie „Herkunftslücken schließen“ (followup=full):

    1. Roh-Trace mit allen eigenen Eingängen (große Sammel-Txs),
       oder Resume aus ``resume_origin`` (nur Lücken)
    2. optional eigene Vorgänger-Txs nachverfolgen (Cache/Adressen warm)
    3. UI-Baum speichern mit resolve_bundled

    Wird vom Einzel-Trace und von „Herkunft vollständig“ genutzt — sonst
    bliebe der Superscan hinter dem Lücken-Knopf zurück.

    *progress* und *cancel_cb* müssen greifen — sonst hängt Phase 1/2 ohne
    Log und Abbruch (bare except in der Engine schluckte Cancelled früher).
    """
    from server import (
        Cancelled,
        analyze,
        trace_mod,
    )

    import contextlib
    import io

    log = progress if callable(progress) else (lambda _m: None)
    abbruch = cancel_cb if callable(cancel_cb) else None
    # analyze.trace_utxo_origin erwartet .update(text); Jobs liefern Callables.
    fortschritt = (
        trace_mod._FortschrittsAdapter(progress) if callable(progress) else None
    )

    def _check_abbruch() -> None:
        if abbruch and abbruch():
            raise Cancelled()

    if folge_tx or folge_bundled:
        _check_abbruch()
        if folge_bundled:
            log("Lücken: eigene Eingänge großer Sammel-Txs nachziehen…")
        else:
            log("Folgeanalyse: erst Herkunft, dann Vorgänger…")
        # Fortschritt/Abbruch hier mitgeben — Phase 1 war sonst stumm und
        # unabbrechbar (CoinJoin/Remix: Minuten ohne job.progress).
        if (
            resume_origin
            and isinstance(resume_origin, dict)
            and analyze.hat_brauchbaren_teilfortschritt(resume_origin)
        ):
            log("Setze gespeicherten Teilbaum fort…")
            roh = analyze.vertiefe_herkunft_luecken(
                resume_origin,
                get_tx,
                eigene,
                wallet=wallet_ctx,
                cache_dir=cache_dir,
                fetch_address_utxos=fetch_addr,
                cache_source=cache_source,
                progress=fortschritt,
                alle_eigenen_inputs=folge_bundled,
            )
        else:
            roh = analyze.trace_utxo_origin(
                get_tx,
                txid,
                vout,
                eigene,
                wallet=wallet_ctx,
                cache_dir=cache_dir,
                fetch_address_utxos=fetch_addr,
                cache_source=cache_source,
                progress=fortschritt,
                alle_eigenen_inputs=folge_bundled,
            )
        _check_abbruch()
        if folge_tx:
            vorgaenger: set[str] = set()
            if roh:
                analyze._collect_internal_creator_txs(roh, vorgaenger)
            log(
                f"Eigene Vorgänger-Txs weiterverfolgen "
                f"({len(vorgaenger)})…"
            )
            if vorgaenger:
                buf = io.StringIO()

                def _log_zeilen() -> None:
                    text = buf.getvalue()
                    if not text:
                        return
                    buf.seek(0)
                    buf.truncate(0)
                    for zeile in text.splitlines():
                        zeile = zeile.strip()
                        if zeile:
                            log(zeile)

                def _folge_fortschritt(text: str) -> None:
                    _check_abbruch()
                    _log_zeilen()
                    log(str(text or ""))

                with contextlib.redirect_stdout(buf):
                    analyze._run_tx_oriented_followups(
                        get_tx,
                        vorgaenger,
                        txid,
                        eigene,
                        set(),
                        0,
                        wallet_ctx,
                        cache_dir,
                        fetch_addr,
                        cache_source,
                        cancel_cb=abbruch,
                        progress_cb=_folge_fortschritt,
                    )
                _log_zeilen()
        _check_abbruch()
        log("Aktualisiere Herkunftsbaum…")

    ergebnis = trace_mod.trace_utxo(
        get_tx,
        txid,
        vout,
        eigene,
        wallet=wallet_ctx,
        cache_dir=cache_dir,
        immutable_cache_dir=immutable_cache_dir,
        fetch_address_utxos=fetch_addr,
        cache_source=cache_source,
        progress=progress if callable(progress) else None,
        resolve_bundled=folge_bundled,
        merke_tx_oriented_done=folge_tx,
        resume_origin=resume_origin,
    )
    return ergebnis


def _wallet_name_fuer_utxo(
    state: AppState,
    txid: str,
    vout: int,
    *,
    hinweis: str = "",
) -> str:
    """
    Anzeigename des Wallets zu txid:vout — für Job-Meta und UI nach Reload.

    Reihenfolge: Client-Hinweis → gespeicherter Trace-Root → UTXO-Cache-Adresse
    → Adressauflösung im Wallet-Kontext.
    """
    from server import (
        main,
        trace_cache,
    )

    name = str(hinweis or "").strip()
    if name:
        return name
    try:
        treffer = trace_cache.laden(
            txid, vout, state.immutable_cache_dir, None,
        )
        if treffer:
            root = (treffer.get("baum") or {}).get("root") or {}
            w = str(root.get("wallet") or "").strip()
            if w:
                return w
            addr = str(root.get("address") or "").strip()
            ctx = state.wallet_ctx
            if addr and ctx is not None:
                w = str(ctx.resolve_address(addr) or "").strip()
                if w:
                    return w
    except Exception:
        pass
    try:
        ctx = state.wallet_ctx
        if ctx is None:
            return ""
        for entry in state.entries or []:
            schluessel = getattr(entry, "analyse_schluessel", None) or getattr(
                entry, "xpub", None,
            )
            if not schluessel:
                continue
            cached = main.load_xpub_utxo_cache(schluessel, state.cache_dir) or []
            for u in cached:
                if (
                    str(u.get("txid") or "").lower() == str(txid).lower()
                    and int(u.get("vout") or -1) == int(vout)
                ):
                    addr = str(u.get("address") or "").strip()
                    if addr:
                        w = str(ctx.resolve_address(addr) or "").strip()
                        if w:
                            return w
                    return str(entry.display_name or "").strip()
    except Exception:
        pass
    return ""
