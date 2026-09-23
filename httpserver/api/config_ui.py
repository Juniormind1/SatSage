"""Config-/UI-Einstellungen-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

from typing import Any


def _ui_theme_aus_env(werte: dict) -> str:
    """``light`` oder ``dark`` aus UI_THEME; Default Hell."""
    roh = str((werte or {}).get("UI_THEME") or "").strip().lower()
    if roh in ("dark", "dunkel"):
        return "dark"
    return "light"


def _lernhinweise_plebs_aus_env(werte: dict) -> bool:
    """``LERNHINWEISE_PLEBS=1`` — Experiment Neugier-Tooltips/Lern-QR; Default aus."""
    roh = str((werte or {}).get("LERNHINWEISE_PLEBS") or "").strip().lower()
    return roh in ("1", "true", "yes", "ja", "on")


def api_config(state: AppState, query: dict, accept_language: str | None = None) -> dict:
    from server import (
        _NODE_MANAGED,
        _electrum_indexer,
        _env_scramble_status,
        _header_tip,
        _ist_local_only,
        _live_p2p_peers,
        _local_core_status_for_api,
        _managed_hint,
        _password_is_set,
        _specter_labels_for_api,
        _ui_lang_fuer_web,
        _wallet_watch_status,
        bloecke_nach_luecke,
        llm_mod,
        main,
        mempool_info,
        sanctions_mod,
        source_mod,
        status_mail_mod,
        tax_mod,
        tip_sync_laeuft,
        wallets_mod,
    )

    from core.version import version as app_version
    from core import selbstanzeige as sa_mod
    from core.env_wallets import (
        UNLESBAR_HINWEIS,
        resolve_wallets_beim_start_aktualisieren,
        resolve_wallets_nur_bekannte_utxos,
    )

    entries = state.entries
    zusammenfassung = wallets_mod.summarize(entries, state.cache_dir)
    werte = state.env().values()
    quellen = source_mod.anreichere_live_p2p(
        source_mod.mergere_erreichbarkeit(
            source_mod.describe_sources(werte),
            getattr(state, "sources_last", None),
        )
    )
    return {
        "version": app_version(),
        "wallets": [z.as_dict() for z in zusammenfassung],
        "sources": [q.as_dict() for q in quellen],
        "script_types": [
            {"value": t, "label": wallets_mod.SCRIPT_TYPE_LABELS[t]}
            for t in main.SCRIPT_TYPE_CHOICES
        ],
        "sanktion_max_hops_cap": sanctions_mod.sanktion_max_hops_cap(),
        "env_path": str(state.env_path),
        "cache_dir": str(state.cache_dir),
        "rpc_password_set": bool((werte.get("RPCUSER") or "").strip() and (werte.get("RPCPASSWORD") or "").strip()),
        "mempool": mempool_info(werte.get("MEMPOOL_URL", "")),
        "steuer": tax_mod.lese_steuer_einstellungen(werte),
        "person": sa_mod.lese_steuer_person(werte),
        "wallets_beim_start_aktualisieren": (
            resolve_wallets_beim_start_aktualisieren(werte)
        ),
        "wallets_immer_aktuell": (
            resolve_wallets_beim_start_aktualisieren(werte)
        ),
        "wallets_nur_bekannte_utxos": (
            resolve_wallets_nur_bekannte_utxos(werte)
        ),
        "oeffentliche_electrum": source_mod.oeffentliche_electrum_erlaubt(werte),
        # Explizit: Web-Opt-in ist sitzungsweise (nach Neustart wieder false).
        "oeffentliche_electrum_session": (
            source_mod.oeffentliche_electrum_session_aktiv()
        ),
        "wallet_watch": _wallet_watch_status(),

        "hinweis_onchain": tax_mod.HINWEIS_ONCHAIN,
        "hinweis_onchain_bestaetigt": tax_mod.hinweis_onchain_bestaetigt(werte),
        # Wallet-Blöcke hinter einer Lücke werden nicht gelesen. Das muss die
        # Oberfläche sagen können, sonst fehlt ein Wallet ohne jeden Hinweis.
        "uebersprungene_bloecke": bloecke_nach_luecke(werte),
        "multisig_hinweis": (
            UNLESBAR_HINWEIS.format(anzahl=len(state.unlesbare_entries))
            if state.unlesbare_entries else ""
        ),
        "header_job_id": state.header_job_id,
        "header_tip": _header_tip(state),
        # Nur melden, wenn der Job wirklich noch läuft (stale ID → null).
        "wallet_sync_job_id": (
            state.wallet_sync_job_id if tip_sync_laeuft(state) else None
        ),
        "live_p2p_peers": _live_p2p_peers(),
        # Ohne Netzprobe — die Pille bleibt grau, bis /api/llm/status?check=1.
        "llm": llm_mod.status_dict(werte, check=False),
        "status_mail": status_mail_mod.als_dict(werte),
        "ui_lang": _ui_lang_fuer_web(werte, accept_language),
        # Hinter Umbrels app_proxy bindet SatSage an 0.0.0.0 — die Fußzeile
        # darf dann nicht "nur lokal erreichbar" behaupten.
        "local_only": _ist_local_only(state),
        "ui_theme": _ui_theme_aus_env(werte),
        "lernhinweise_plebs": _lernhinweise_plebs_aus_env(werte),
        "network": (werte.get("NETWORK") or "main").strip().lower() or "main",
        "managed_by": state.managed_by,
        "managed_hint": _managed_hint(state, werte),
        "electrum_indexer": (
            _electrum_indexer(werte) if state.managed_by in _NODE_MANAGED else None
        ),
        "specter_labels": (
            _specter_labels_for_api(state) if state.managed_by == "specter" else None
        ),
        "local_core": _local_core_status_for_api(state),
        # App-Passwort (Hash in .satsage-password) — UI Einstellungen; Scrambling später.
        "password_set": _password_is_set(state),
        "env_scramble": _env_scramble_status(state),
    }


def api_save_ui_lang(state: AppState, payload: dict) -> dict:
    """Speichert die UI-Sprache in der .env (``UI_LANG``)."""
    from server import (
        ApiError,
    )

    roh = payload.get("ui_lang", payload.get("lang", "de"))
    lang = "en" if str(roh).strip().lower().startswith("en") else "de"
    env = state.env()
    env.apply({"UI_LANG": lang})
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {"saved": True, "ui_lang": lang}


def api_save_ui_theme(state: AppState, payload: dict) -> dict:
    """Speichert den Farbmodus in der .env (``UI_THEME``)."""
    from server import (
        ApiError,
    )

    roh = str(payload.get("ui_theme", payload.get("theme", "light")) or "").strip().lower()
    theme = "dark" if roh in ("dark", "dunkel") else "light"
    env = state.env()
    env.apply({"UI_THEME": theme})
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {"saved": True, "ui_theme": theme}


def api_save_lernhinweise_plebs(state: AppState, payload: dict) -> dict:
    """Speichert das Experiment „Lernhinweise für Plebs“ in der .env."""
    from server import (
        ApiError,
    )

    roh = payload.get("lernhinweise_plebs", payload.get("enabled", False))
    an = roh in (True, 1, "1", "true", "yes", "ja", "on")
    env = state.env()
    env.apply({"LERNHINWEISE_PLEBS": "1" if an else "0"})
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {"saved": True, "lernhinweise_plebs": an}


def api_save_start_sync(state: AppState, payload: dict) -> dict:
    """
    Speichert „Wallets immer aktuell halten“ (+ Unteroption) in der .env.

    Bei ja: Tip-Nachzug beim Start + Electrs-Subscribe (eigener Node).
    ``nur_bekannte_utxos``: Tip-Nachzug ohne Gap — nur bekannte UTXOs.
    """
    from server import (
        ApiError,
        _payload_bool,
        _tip_sync_abbrechen,
        _wallet_watch_status,
        main,
        starte_wallet_aktualisierung,
    )

    an = _payload_bool(
        payload,
        "enabled",
        "wallets_immer_aktuell",
        "wallets_beim_start_aktualisieren",
        default=False,
    )
    assert an is not None
    nur_bekannte = _payload_bool(
        payload,
        "nur_bekannte_utxos",
        "known_only",
        "wallets_nur_bekannte_utxos",
        default=None,
    )
    if not an:
        nur_bekannte = False
    elif nur_bekannte is None:
        from core.env_wallets import resolve_wallets_nur_bekannte_utxos
        nur_bekannte = resolve_wallets_nur_bekannte_utxos(
            state.env().values()
        )

    env = state.env()
    # Beide Keys: UI-Name neu, Legacy bleibt lesbar.
    env.apply({
        "WALLETS_IMMER_AKTUELL": "1" if an else "0",
        "WALLETS_BEIM_START_AKTUALISIEREN": "1" if an else "0",
        "WALLETS_NUR_BEKANNTE_UTXOS": "1" if nur_bekannte else "0",
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    # Sofort wirksam — kein Server-Neustart nötig.
    sync_job = None
    try:
        from core import wallet_watch

        if an:
            # Alten Gap-Lauf stoppen, damit die neue Option (z. B. nur bekannte)
            # nicht hinter einem noch laufenden Tip-Nachzug stecken bleibt.
            _tip_sync_abbrechen(state)
            # 1) Tip-Nachzug jetzt (wie beim Start)
            sync_job = starte_wallet_aktualisierung(state, erzwingen=True)
            # 2) Electrs-Subscribe für Live-Updates
            wallet_watch.starte_wallet_watch(
                state, on_log=lambda t: print(f"  {t}", flush=True),
            )
        else:
            _tip_sync_abbrechen(state)
            wallet_watch.stoppe_wallet_watch()
    except Exception:
        pass

    out = {
        "saved": True,
        "wallets_beim_start_aktualisieren": an,
        "wallets_immer_aktuell": an,
        "wallets_nur_bekannte_utxos": bool(nur_bekannte),
        "wallet_watch": _wallet_watch_status(),
    }
    if isinstance(sync_job, dict) and sync_job.get("id"):
        out["wallet_sync_job_id"] = sync_job["id"]
        out["job"] = sync_job
    return out


def api_save_hinweis_onchain(state: AppState, payload: dict) -> dict:
    """
    Merkt, dass der On-Chain-Hinweis auf dieser Installation bestätigt wurde.

    Geschrieben wird die .env — nicht localStorage — damit derselbe Rechner
    den Absatz nicht in jedem Browser wieder zeigt.
    """
    from server import (
        ApiError,
        tax_mod,
    )

    roh = payload.get("bestaetigt", payload.get("hinweis_onchain_bestaetigt"))
    if isinstance(roh, str):
        an = roh.strip().lower() in ("1", "true", "ja", "yes", "on")
    else:
        an = bool(roh)

    env = state.env()
    env.apply({
        tax_mod.ENV_HINWEIS_ONCHAIN_BESTAETIGT: "1" if an else "0",
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {
        "saved": True,
        "hinweis_onchain_bestaetigt": an,
    }


def api_save_llm(state: AppState, payload: dict) -> dict:
    """
    Speichert die Assistenten-Anbindung (URL, Modell, Anbieter, Opt-in).

    Der API-Key wird nur geschrieben, wenn das Feld nicht leer ist — analog
    zu RPC-Passwort. ``XAI_API_KEY`` wird weder gelesen noch gesetzt; ein
    Key gehört ausschließlich nach ``LLM_API_KEY``.
    """
    from server import (
        ApiError,
        llm_mod,
    )

    if not isinstance(payload, dict):
        raise ApiError(400, "Ungültiger Körper.")

    base = str(payload.get("base_url") or payload.get("LLM_BASE_URL") or "").strip()
    modell = str(payload.get("modell") or payload.get("LLM_MODELL") or "").strip()
    anbieter = str(payload.get("anbieter") or payload.get("LLM_ANBIETER") or "").strip()
    anbieter = anbieter.lower().replace("_", "-")
    if anbieter == "apikey":
        anbieter = "api-key"
    if anbieter and anbieter not in llm_mod.ANBIETER_WERTE:
        raise ApiError(400, f"Unbekannter Anbieter „{anbieter}“.")

    roh_opt = payload.get("remote_opt_in", payload.get("LLM_REMOTE_OPT_IN"))
    if isinstance(roh_opt, str):
        opt_in = roh_opt.strip().lower() in ("1", "true", "yes", "ja", "on")
    else:
        opt_in = bool(roh_opt)

    key = str(payload.get("api_key") or payload.get("LLM_API_KEY") or "").strip()
    if payload.get("XAI_API_KEY"):
        raise ApiError(400, "XAI_API_KEY wird hier nicht entgegengenommen.")

    env = state.env()
    updates: dict[str, str | None] = {
        "LLM_BASE_URL": base or None,
        "LLM_MODELL": modell or None,
        "LLM_ANBIETER": anbieter or None,
        "LLM_REMOTE_OPT_IN": "1" if opt_in else "0",
    }
    if key:
        updates["LLM_API_KEY"] = key
    if payload.get("api_key_clear"):
        updates["LLM_API_KEY"] = None

    env.apply(updates)
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    werte = env.values()
    return {
        "saved": True,
        "llm": llm_mod.status_dict(werte, check=False),
    }


def api_save_status_mail(state: AppState, payload: dict) -> dict:
    """
    Speichert Status-Mail-Opt-in und SMTP-Zugang.

    Leeres Passwort-Feld behält den gesetzten Wert (wie LLM-API-Key).
    """
    from server import (
        ApiError,
        outbound_policy,
        status_mail_mod,
    )

    if not isinstance(payload, dict):
        raise ApiError(400, "Ungültiger Körper.")

    to = str(payload.get("to") or payload.get("STATUS_MAIL_TO") or "").strip()
    host = str(payload.get("smtp_host") or payload.get("SMTP_HOST") or "").strip()
    from_addr = str(
        payload.get("smtp_from") or payload.get("SMTP_FROM") or ""
    ).strip()
    user = str(payload.get("smtp_user") or payload.get("SMTP_USER") or "").strip()
    port_roh = payload.get("smtp_port", payload.get("SMTP_PORT", 587))
    try:
        port = int(port_roh)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "SMTP-Port muss eine Zahl sein.") from exc
    if not (1 <= port <= 65535):
        raise ApiError(400, "SMTP-Port ungültig.")

    roh_opt = payload.get("opt_in", payload.get("STATUS_MAIL_OPT_IN"))
    if isinstance(roh_opt, str):
        opt_in = roh_opt.strip().lower() in ("1", "true", "ja", "yes", "on")
    else:
        opt_in = bool(roh_opt)

    roh_tls = payload.get("starttls", payload.get("SMTP_STARTTLS"))
    if roh_tls is None:
        starttls = True
    elif isinstance(roh_tls, str):
        starttls = roh_tls.strip().lower() in ("1", "true", "ja", "yes", "on")
    else:
        starttls = bool(roh_tls)

    password = str(
        payload.get("smtp_password") or payload.get("SMTP_PASSWORD") or ""
    ).strip()
    if host:
        try:
            outbound_policy.ensure_host_allowed(
                host, service="smtp", values=state.env().values(),
                opt_in=outbound_policy.public_opt_in(state.env().values(), "smtp"),
            )
        except outbound_policy.OutboundPolicyError as exc:
            raise ApiError(400, str(exc)) from exc

    env = state.env()
    updates: dict[str, str | None] = {
        status_mail_mod.ENV_OPT_IN: "1" if opt_in else "0",
        status_mail_mod.ENV_TO: to or None,
        status_mail_mod.ENV_HOST: host or None,
        status_mail_mod.ENV_PORT: str(port),
        status_mail_mod.ENV_USER: user or None,
        status_mail_mod.ENV_FROM: from_addr or None,
        status_mail_mod.ENV_STARTTLS: "1" if starttls else "0",
    }
    if password:
        updates[status_mail_mod.ENV_PASSWORD] = password
    if payload.get("smtp_password_clear"):
        updates[status_mail_mod.ENV_PASSWORD] = None

    env.apply(updates)
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {
        "saved": True,
        "status_mail": status_mail_mod.als_dict(env.values()),
    }


def registriere_status_mail_hook(state: AppState) -> None:
    """Job-Ende → neutrale Status-Mail (rescan/verlauf), wenn konfiguriert."""

    from server import (
        setze_fertig_hook,
        status_mail_mod,
    )

    def fertig(job) -> None:
        kind = getattr(job, "kind", "") or ""
        if kind not in status_mail_mod.STATUS_MAIL_KINDS:
            return
        status = getattr(job, "status", "") or ""
        if status not in ("done", "failed", "cancelled"):
            return
        try:
            werte = state.env().values()
        except Exception:
            return
        if not status_mail_mod.darf_senden(werte, kind):
            return
        status_mail_mod.sende_status_mail_async(
            werte,
            kind=kind,
            status=status,
            finished_at=getattr(job, "finished_at", None),
        )

    setze_fertig_hook(fertig)

