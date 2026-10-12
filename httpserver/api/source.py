"""Datenquellen-/Source-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

import core.wallet_sync_engine as wallet_sync_engine

from typing import Any


def api_save_mempool(state: AppState, payload: dict) -> dict:
    """
    Speichert die Adresse der eigenen mempool-Instanz.

    Geprüft wird nur die Form. Ein Verbindungstest wäre schon der erste
    Abruf — und genau den soll der Benutzer selbst auslösen.

    Öffentliche Explorer (mempool.space u. ä.) brauchen ``public_opt_in``
    nach Warndialog in der UI — sonst bleibt die Outbound-Policy hart.
    """
    from server import (
        ApiError,
        _payload_bool,
        mempool_info,
        normalize_mempool_url,
        outbound_policy,
    )

    try:
        url = normalize_mempool_url(str(payload.get("url", "")))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    info = mempool_info(url)
    oeffentlich = bool(info.get("configured") and not info.get("local"))
    public_opt_in = bool(
        _payload_bool(payload, "public_opt_in", "confirm_public", default=False)
    )

    if url:
        try:
            outbound_policy.ensure_url_allowed(
                url,
                service="mempool",
                values=state.env().values(),
                # Nach expliziter Bestätigung in der UI freigeben.
                opt_in=True if (oeffentlich and public_opt_in) else None,
            )
        except outbound_policy.OutboundPolicyError as exc:
            raise ApiError(400, str(exc)) from exc

    env = state.env()
    updates: dict[str, str | None] = {"MEMPOOL_URL": url or None}
    if not url or not oeffentlich:
        # Kein öffentlicher Explorer mehr → Opt-in zurücknehmen.
        updates["SATSAGE_MEMPOOL_PUBLIC_OPT_IN"] = None
    elif public_opt_in:
        updates["SATSAGE_MEMPOOL_PUBLIC_OPT_IN"] = "1"
    env.apply(updates)
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    state.reload()
    return {"saved": True, "mempool": mempool_info(url)}


def api_mempool_probe(state: AppState) -> dict:
    """
    Prüft die eingetragene mempool-Instanz vom Server aus.

    Die Oberfläche fragt diese Route, statt die Instanz selbst anzutippen.
    Ein Browser-Abruf scheitert an der Seitenrichtlinie (nur ``'self'``)
    und an selbst signiertem TLS im LAN.
    """
    from server import mempool_info

    from core.config import mempool_erreichbar

    werte = state.env().values()
    info = mempool_info(werte.get("MEMPOOL_URL", ""))
    if not info.get("configured"):
        return {"ok": False, "reachable": False, "reason": "Keine Adresse eingetragen."}
    ok, grund = mempool_erreichbar(str(info.get("url") or ""))
    return {
        "ok": ok,
        "reachable": ok,
        "host": info.get("host") or "",
        "reason": grund,
    }


def api_p2p_scan_zeit(state: AppState, query: dict) -> dict:
    """Höhe ↔ Datum für den P2P-Scan-Start. Scan liest nur die Höhe."""
    from server import ApiError

    from core.scan_zeit import parse_utc_datum, rechne_scan_zeit

    hoehe_roh = str(
        (query.get("hoehe") or query.get("height") or [""])[0] or ""
    ).strip()
    datum_roh = str(
        (query.get("datum") or query.get("date") or [""])[0] or ""
    ).strip()
    if hoehe_roh and datum_roh:
        raise ApiError(400, "Nur Höhe oder Datum, nicht beides.")
    if not hoehe_roh and not datum_roh:
        raise ApiError(400, "Höhe oder Datum angeben.")

    hoehe = None
    datum = None
    if hoehe_roh:
        try:
            hoehe = int(hoehe_roh)
        except ValueError as exc:
            raise ApiError(400, "Scan-Block muss eine ganze Zahl ≥ 0 sein.") from exc
        if hoehe < 0:
            raise ApiError(400, "Scan-Block muss eine ganze Zahl ≥ 0 sein.")
    else:
        try:
            parse_utc_datum(datum_roh)
        except ValueError as exc:
            raise ApiError(400, f"Startdatum unlesbar: {exc}") from exc
        datum = datum_roh

    werte = state.env().values()
    explorer = (werte.get("MEMPOOL_URL") or "").strip() or None
    try:
        return rechne_scan_zeit(
            hoehe=hoehe,
            datum=datum,
            cache_root=state.immutable_cache_dir,
            explorer_url=explorer,
            values=werte,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc


def api_save_source(state: AppState, payload: dict) -> dict:
    from server import (
        ApiError,
        _datenquellen_config_gesperrt,
        _loesche_source_stand,
        _verwerfe_electrs_verbindungen,
        main,
        outbound_policy,
        source_mod,
    )

    _datenquellen_config_gesperrt(state)
    """
    Schreibt die Felder einer Datenquelle in die .env.

    Es werden ausschließlich Schlüssel aus der Positivliste der jeweiligen
    Quelle übernommen. Ohne diese Einschränkung wäre der Endpunkt ein
    Schreibzugriff auf beliebige Einträge — auch auf XPUBS.
    """
    quelle = str(payload.get("source", "")).strip()
    erlaubt = source_mod.EDITIERBARE_FELDER.get(quelle)
    if not erlaubt:
        raise ApiError(400, f"Quelle „{quelle}“ ist nicht bearbeitbar.")

    roh = payload.get("values")
    if not isinstance(roh, dict):
        raise ApiError(400, "Feld 'values' fehlt oder ist kein Objekt.")
    _datenquellen_config_gesperrt(state, quelle=quelle, werte=roh)

    env = state.env()
    vorhanden = env.values()
    updates: dict[str, str | None] = {}

    for schluessel, wert in roh.items():
        if schluessel not in erlaubt:
            raise ApiError(400, f"Feld „{schluessel}“ gehört nicht zu dieser Quelle.")
        text = str(wert).strip()

        # Die Onion-Rotation kommt als Liste und wird auf FULCRUM_TOR_0…9
        # abgebildet — so erwartet es main._indexed_env_values.
        if schluessel == "FULCRUM_TOR_LISTE":
            adressen = [z.strip() for z in text.splitlines() if z.strip()]
            if len(adressen) > main.MAX_PUBLIC_ONION_SERVERS:
                raise ApiError(
                    400,
                    f"Höchstens {main.MAX_PUBLIC_ONION_SERVERS} Onion-Adressen.",
                )
            for i in range(main.MAX_PUBLIC_ONION_SERVERS):
                adresse = adressen[i] if i < len(adressen) else None
                if adresse:
                    adresse = main._normalize_fulcrum_host(adresse)
                updates[f"FULCRUM_TOR_{i}"] = adresse
            continue

        # Ein leeres Passwortfeld heißt „nicht ändern“, nicht „löschen“.
        if schluessel in source_mod.GEHEIME_FELDER and not text:
            continue

        if schluessel.endswith(("PORT", "HEIGHT")) and text and not text.isdigit():
            raise ApiError(400, f"„{schluessel}“ muss eine Zahl sein.")
        if schluessel == "BIP158_GAP_LIMIT":
            if not text.isdigit():
                raise ApiError(
                    400, "Die Lücke muss eine ganze Zahl von 1 bis 10.000 sein.",
                )
            luecke = int(text)
            if luecke < 1 or luecke > 10_000:
                raise ApiError(
                    400, "Die Lücke muss eine ganze Zahl von 1 bis 10.000 sein.",
                )

        # Start9-GUI kopiert gern https://….onion — SOCKS/IDNA verstehen das nicht.
        if schluessel in ("FULCRUM_HOST", "FULCRUM_TOR", "NODE_IP") and text:
            text = main._normalize_fulcrum_host(text)
            service = "core" if schluessel == "NODE_IP" else "fulcrum"
            try:
                outbound_policy.ensure_host_allowed(text, service=service, values=vorhanden)
            except outbound_policy.OutboundPolicyError as exc:
                raise ApiError(400, str(exc)) from exc

        updates[schluessel] = text or None

    if not updates:
        return {"saved": False, "grund": "Nichts zu ändern."}

    # Ein Port/TLS in der UI — Tor-Sonderkeys (FULCRUM_TOR_PORT/_SSL) sonst
    # überschreiben den neuen Wert still und der Verbindungsversuch bleibt
    # am alten Endpoint (nur Server-Neustart half).
    if "FULCRUM_PORT" in updates:
        updates["FULCRUM_TOR_PORT"] = None
    if "FULCRUM_SSL" in updates:
        updates["FULCRUM_TOR_SSL"] = None

    electrs_keys = {
        "FULCRUM_HOST", "FULCRUM_TOR", "FULCRUM_PORT", "FULCRUM_SSL",
        "FULCRUM_TOR_PORT", "FULCRUM_TOR_SSL", "FULCRUM_TOR_PROXY",
    }
    electrs_geaendert = bool(electrs_keys & set(updates))
    core_keys = {
        "NODE_IP", "RPCHOST", "BITCOIN_RPC_HOST", "RPCPORT", "RPCUSER",
        "RPCPASSWORD", "RPC_SSL", "RPC_COOKIE_FILE", "BITCOIN_RPC_COOKIE",
    }
    core_geaendert = bool(core_keys & set(updates)) or quelle == "own_core"
    utxo_keys = {
        "UTXO_RPC_HOST", "UTXO_RPCPORT", "UTXO_RPCUSER", "UTXO_RPCPASSWORD",
        "UTXO_RPC_SSL", "UTXO_RPC_COOKIE_FILE",
    }
    utxo_geaendert = bool(utxo_keys & set(updates)) or quelle == "own_utxo_core"

    env.apply(updates)
    try:
        sicherung = env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    state.reload()
    if electrs_geaendert:
        _verwerfe_electrs_verbindungen(state)
        _loesche_source_stand(state, "own_fulcrum")
    if core_geaendert:
        _loesche_source_stand(state, "own_core")
    if utxo_geaendert:
        _loesche_source_stand(state, "own_utxo_core")
    # Pille sofort „unbekannt“, bis der nächste Check/Connect greift.
    pending = []
    if electrs_geaendert:
        pending.append("own_fulcrum")
    if core_geaendert:
        pending.append("own_core")
    if utxo_geaendert:
        pending.append("own_utxo_core")
    werte = state.env().values()
    return {
        "saved": True,
        "backup": str(sicherung) if sicherung else None,
        "sources": [q.as_dict() for q in source_mod.describe_sources(werte)],
        "pending_sources": pending,
    }


def api_lade_electrum_server(state: AppState, payload: dict) -> dict:
    from server import (
        ApiError,
        _datenquellen_config_gesperrt,
        main,
        source_mod,
    )

    _datenquellen_config_gesperrt(state)
    """
    Lädt servers.json vom Electrum-Repo, wenn die lokale Datei fehlt
    oder mindestens einen Tag alt ist.

    filter=onion  → schreibt bis zu zehn Onion-Hosts nach FULCRUM_TOR_0…
    filter=clearnet → legt nur electrum_servers.json an (Clearnet-Pool).
    Die Datei selbst bleibt vollständig, damit beide Abschnitte dieselbe
    Quelle nutzen und sich nicht gegenseitig die Liste zerschneiden.
    """
    from core.electrum_servers import (
        ELECTRUM_SERVERS_URL,
        lade_oder_aktualisiere_electrum_servers,
        splitte_electrum_server,
    )

    art = str(payload.get("filter") or "").strip()
    if art not in ("onion", "clearnet"):
        raise ApiError(400, "filter muss „onion“ oder „clearnet“ sein.")
    verbinden = bool(payload.get("verbinden"))
    # „Verbinden“ gilt nur für diese Zeile. Die Liste kommt bei Bedarf mit.
    # Sonst prüft der folgende Status-Check ohne Wahl und nimmt Clearnet,
    # weil es schneller antwortet als Onion.
    source_mod.setze_oeffentliche_electrum_art(art)
    from httpserver.empfang import _verwerfe_oeffentlichen_empfang_pool

    _verwerfe_oeffentlichen_empfang_pool(state)

    ziel = main.ELECTRUM_SERVERS_FILE
    try:
        servers, refreshed = lade_oder_aktualisiere_electrum_servers(ziel)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ApiError(502, f"Download fehlgeschlagen: {exc}") from exc

    onions, clearnet = splitte_electrum_server(servers)
    if art == "onion":
        if not onions:
            raise ApiError(502, "Die geladene Liste enthält keine Onion-Adressen.")
        env = state.env()
        schon_da = bool((env.values().get("FULCRUM_TOR_0") or "").strip())
        # Frische Liste und schon Einträge: .env nicht bei jedem Verbinden
        # überschreiben. Nachziehen oder erstes Laden schreibt die Rotation.
        if refreshed or not schon_da:
            updates: dict[str, str | None] = {}
            for i in range(main.MAX_PUBLIC_ONION_SERVERS):
                if i < len(onions):
                    host, port, use_ssl = onions[i]
                    updates[f"FULCRUM_TOR_{i}"] = host
                    updates[f"FULCRUM_PORT_{i}"] = str(port)
                    updates[f"FULCRUM_SSL_{i}"] = "true" if use_ssl else "false"
                else:
                    updates[f"FULCRUM_TOR_{i}"] = None
                    updates[f"FULCRUM_PORT_{i}"] = None
                    updates[f"FULCRUM_SSL_{i}"] = None
            env.apply(updates)
            try:
                env.save()
            except OSError as exc:
                raise ApiError(500, "Interner Serverfehler.") from exc
            state.reload()
        anzahl = min(len(onions), main.MAX_PUBLIC_ONION_SERVERS)
        meldung = (
            f"{anzahl} Onion-Adressen übernommen"
            + (f" (von {len(onions)})" if len(onions) > anzahl else "")
            + "."
        )
        zaehler = anzahl
    else:
        if not clearnet:
            raise ApiError(502, "Die geladene Liste enthält keine Clearnet-Server.")
        meldung = f"{len(clearnet)} Clearnet-Server in electrum_servers.json."
        zaehler = len(clearnet)

    werte = state.env().values()
    return {
        "saved": True,
        "filter": art,
        "count": zaehler,
        "url": ELECTRUM_SERVERS_URL,
        "message": meldung,
        "refreshed": refreshed,
        "verbinden": verbinden,
        "art": source_mod.oeffentliche_electrum_art(),
        "sources": [q.as_dict() for q in source_mod.describe_sources(werte)],
    }


def api_oeffentliche_electrum(state: AppState, payload: dict) -> dict:
    """
    Sitzungs-Bestätigung für öffentliche Electrum-Server.

    Gilt nur bis zum Prozessende — wird **nicht** in die ``.env`` geschrieben,
    damit nach jedem Server-Neustart bei geringer Privatsphäre erneut gefragt
    wird. Ein altes ``OEFFENTLICHE_ELECTRUM`` in der ``.env`` wird entfernt
    (Migration von der früheren Dauer-Freigabe).
    """
    from server import (
        ApiError,
        _datenquellen_config_gesperrt,
        source_mod,
    )

    _datenquellen_config_gesperrt(state)
    erlauben = bool(payload.get("erlauben"))
    art = str(payload.get("art") or "").strip().lower()
    if art and art not in ("onion", "clearnet"):
        raise ApiError(400, "art muss „onion“ oder „clearnet“ sein.")
    source_mod.setze_oeffentliche_electrum_session(erlauben)
    if erlauben and art:
        source_mod.setze_oeffentliche_electrum_art(art)
    # Dauerhafte Freigabe streichen — Opt-in ist sitzungsweise.
    env = state.env()
    if (env.values().get("OEFFENTLICHE_ELECTRUM") or "").strip():
        env.apply({"OEFFENTLICHE_ELECTRUM": None})
        try:
            env.save()
        except OSError as exc:
            raise ApiError(500, "Interner Serverfehler.") from exc
        state.reload()
    return {
        "saved": True,
        "erlaubt": erlauben,
        "session": True,
        "sources": [
            q.as_dict() for q in source_mod.describe_sources(state.env().values())
        ],
    }


def api_local_core_accept(state: AppState, payload: dict | None = None) -> dict:
    """Übernimmt erkannten Loopback-bitcoind in die .env (UTXO-Slot; Lookup nur wenn leer)."""
    from server import (
        ApiError,
        _MANAGED_MODI,
        _datenquellen_config_gesperrt,
        _discover_local_core_cached,
        _local_core_status_for_api,
        source_mod,
    )

    _datenquellen_config_gesperrt(state)
    if state.managed_by in _MANAGED_MODI:
        raise ApiError(403, "Im Managed-Modus kommt Core von der Plattform.")
    from core import local_bitcoind as local_core

    werte = state.env().values()
    hit = _discover_local_core_cached(werte)
    if hit is None:
        raise ApiError(404, "Kein lokaler Bitcoin Core (Cookie/RPC) gefunden.")
    already = local_core.core_already_configured(werte)
    env = state.env()
    env.apply(local_core.env_updates_from_hit(hit, lookup_core_already=already))
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    import httpserver.local_core as _local_core_mod

    _local_core_mod._local_core_probe_cache = None
    state.reload()
    if already:
        print(
            f"Lokaler Bitcoin Core → UTXO-Set-Slot gespeichert: "
            f"{hit.host}:{hit.port}, Prefer-Peer {hit.host}:{hit.p2p_port} "
            f"({hit.chain}, {'pruned' if hit.pruned else 'vollständig'}). "
            f"Lookup-NODE_IP unverändert.",
            flush=True,
        )
    else:
        print(
            f"Lokaler Bitcoin Core übernommen: RPC {hit.host}:{hit.port}, "
            f"BIP-158 Prefer-Peer {hit.host}:{hit.p2p_port} "
            f"({hit.chain}, {'pruned' if hit.pruned else 'vollständig'}).",
            flush=True,
        )
    return {
        "saved": True,
        "lookup_preserved": already,
        "local_core": _local_core_status_for_api(state),
        "sources": [
            q.as_dict() for q in source_mod.describe_sources(state.env().values())
        ],
    }


def _kappe_oeffentliche_wenn_indexer_steht(
    state, quellen: list, werte: dict, *, still: bool, on_log=None,
) -> tuple[list, dict]:
    """Eigener Indexer erreichbar → öffentliche Electrum-Reste und Opt-in weg."""
    from dataclasses import replace

    from server import source_mod

    own = next((q for q in quellen if getattr(q, "key", None) == "own_fulcrum"), None)
    if own is None or not own.reachable:
        return quellen, werte
    from httpserver.empfang import _kappe_oeffentliche_electrum_nach_privater_quelle

    _kappe_oeffentliche_electrum_nach_privater_quelle(
        state, on_log=None if still else on_log,
    )
    nach_kappe = {
        q.get("key"): q
        for q in (getattr(state, "sources_last", None) or [])
        if isinstance(q, dict) and q.get("key")
    }
    gekappt: list = []
    for q in quellen:
        a = nach_kappe.get(q.key)
        if a and q.key in source_mod.OEFFENTLICHE_QUELLEN_KEYS:
            q = replace(
                q,
                reachable=a.get("reachable"),
                peer_count=int(a.get("peer_count") or 0),
                peer_hosts=list(a.get("peer_hosts") or []),
                error=str(a.get("error") or ""),
                note=str(a.get("note") or q.note or ""),
            )
        gekappt.append(q)
    return gekappt, state.env().values()


def api_source_status(state: AppState, query: dict, *, on_log=None) -> dict:
    from server import (
        _header_tip,
        _live_p2p_peers,
        _persist_tls_auto,
        source_mod,
    )

    from dataclasses import replace

    from core.jobs import electrum_serial_busy

    werte = state.env().values()
    quellen = source_mod.describe_sources(werte)
    still = query.get("still", ["0"])[0] in ("1", "true", "ja")
    check_an = query.get("check", ["0"])[0] in ("1", "true", "ja")
    # Während UTXO-Scan/Herkunft: stiller Peer-Takt soll own_fulcrum nicht
    # neu connecten (Tor-SOCKS-Spam + Last auf dem Electrs-Socket).
    electrum_busy = electrum_serial_busy()
    skip_live_check = bool(check_an and still and electrum_busy)
    if check_an and not skip_live_check:
        quellen = source_mod.check_sources(
            quellen, werte, on_log=None if still else on_log, still=still,
        )
        quellen = _persist_tls_auto(
            state, quellen, on_log=None if still else on_log,
        )
        werte = state.env().values()
    elif skip_live_check and state.sources_last:
        alt = {
            q.get("key"): q
            for q in state.sources_last
            if isinstance(q, dict) and q.get("key")
        }
        aufgefrischt: list = []
        for q in quellen:
            a = alt.get(q.key)
            if a and q.key == "own_fulcrum":
                q = replace(
                    q,
                    reachable=a.get("reachable"),
                    peer_count=int(a.get("peer_count") or 0),
                    peer_hosts=list(a.get("peer_hosts") or []),
                    error=str(a.get("error") or ""),
                    detail=str(a.get("detail") or q.detail or ""),
                    software=str(a.get("software") or ""),
                    software_raw=str(a.get("software_raw") or ""),
                )
            aufgefrischt.append(q)
        quellen = aufgefrischt
    quellen = source_mod.anreichere_live_p2p(quellen)
    quellen, werte = _kappe_oeffentliche_wenn_indexer_steht(
        state, quellen, werte, still=still, on_log=on_log,
    )
    stand = source_mod.peer_status(quellen, werte)
    # Kein Header-Tip-Nachzug hier: der Peer-Takt (30 s) würde sonst
    # alle halbe Minute Tor/P2P + „Header-Cache fertig“ spammen.
    # Header laufen über Start, /headers und eigenen Cooldown.
    sources_dicts = [q.as_dict() for q in quellen]
    if check_an and not skip_live_check:
        state.sources_last = sources_dicts
    from core.bitcoind_rpc import rpc_allowlist_status

    out = {
        "sources": sources_dicts,
        "peers": stand["count"],
        "peer_status": stand,
        "live_p2p_peers": _live_p2p_peers(),
        "header_job_id": state.header_job_id,
        "header_tip": _header_tip(state),
        "oeffentliche_electrum": source_mod.oeffentliche_electrum_erlaubt(werte),
        "oeffentliche_electrum_session": (
            source_mod.oeffentliche_electrum_session_aktiv()
        ),
        "oeffentliche_electrum_art": source_mod.oeffentliche_electrum_art(),
        # Dealbreaker T14: Kopfzeile zeigt eine rote Pille, solange gesetzt.
        "rpc_allowlist": rpc_allowlist_status(),
    }
    if electrum_busy:
        out["electrum_busy"] = True
    return out


def api_clear_source(state: AppState, quelle: str) -> dict:
    """
    Streicht einen eigenen Node aus der .env, schaltet P2P aus
    (``BIP158_P2P=0``), oder löscht nur die geladene öffentliche
    Electrum-Liste (Onion-Rotation / electrum_servers.json).
    Sitzungs-Opt-in für öffentliche Electrum bleibt unberührt.
    """
    from server import (
        ApiError,
        _breche_p2p_jobs_ab,
        _datenquellen_config_gesperrt,
        main,
        source_mod,
    )

    name = (quelle or "").strip()
    _datenquellen_config_gesperrt(state, quelle=name, aktion="verwerfen")
    env = state.env()
    sicherung = None
    cancelled_jobs: list[str] = []

    if name in ("own_fulcrum", "own_core", "own_utxo_core"):
        erlaubt = source_mod.EDITIERBARE_FELDER[name]
        # Tor-Proxy teilen sich mehrere Quellen — nicht mit Core löschen.
        loeschen = [
            k for k in erlaubt
            if not (name == "own_core" and k == "FULCRUM_TOR_PROXY")
        ]
        env.apply({schluessel: None for schluessel in loeschen})
        for schluessel in loeschen:
            env.runtime_values.pop(schluessel, None)
        try:
            sicherung = env.save()
        except OSError as exc:
            raise ApiError(500, "Interner Serverfehler.") from exc
    elif name == "bip158":
        # Wie Zeilen-Knopf „Verbinden“ rückgängig (fehlender Key = Default an).
        env.apply({"BIP158_P2P": "false"})
        env.runtime_values.pop("BIP158_P2P", None)
        try:
            sicherung = env.save()
        except OSError as exc:
            raise ApiError(500, "Interner Serverfehler.") from exc
        # Zuerst Jobs stoppen, dann Peers leeren — sonst weiter Filter holen.
        cancelled_jobs = _breche_p2p_jobs_ab(state)
        try:
            import bip158_scanner as _bip

            with _bip._LIVE_FILTER_LOCK:
                _bip._LIVE_FILTER_PEERS.clear()
        except Exception:
            pass
        if cancelled_jobs:
            print(
                "P2P getrennt — laufende P2P-/Scan-Jobs abgebrochen "
                f"({len(cancelled_jobs)}).",
                flush=True,
            )
    elif name == "public_onion":
        updates: dict[str, str | None] = {}
        for i in range(main.MAX_PUBLIC_ONION_SERVERS):
            updates[f"FULCRUM_TOR_{i}"] = None
            updates[f"FULCRUM_PORT_{i}"] = None
            updates[f"FULCRUM_SSL_{i}"] = None
        env.apply(updates)
        try:
            sicherung = env.save()
        except OSError as exc:
            raise ApiError(500, "Interner Serverfehler.") from exc
    elif name == "clearnet":
        ziel = main.ELECTRUM_SERVERS_FILE
        if ziel.is_file():
            try:
                ziel.unlink()
            except OSError as exc:
                raise ApiError(500, "Interner Serverfehler.") from exc
    else:
        raise ApiError(
            400,
            "Nur eigener Electrum-Server, Bitcoin Core, P2P oder öffentliche "
            "Electrum-Listen können verworfen werden.",
        )

    state.reload()
    werte = state.env().values()
    quellen = [
        q.as_dict()
        for q in source_mod.anreichere_live_p2p(
            source_mod.describe_sources(werte)
        )
    ]
    # Letzter Check-Stand darf „P2P an/verbunden“ nicht über den Papierkorb retten.
    state.sources_last = quellen
    return {
        "saved": True,
        "cleared": name,
        "backup": str(sicherung) if sicherung else None,
        "sources": quellen,
        "cancelled_jobs": cancelled_jobs,
    }


def _bekannte_utxo_keys(state: AppState, entries) -> set[str]:
    """txid:vout, die vor diesem Scan schon im Cache lagen."""
    from server import main

    keys: set[str] = set()
    for entry in entries:
        try:
            liste = main.load_xpub_utxo_cache(
                entry.analyse_schluessel, state.cache_dir,
            ) or []
        except Exception:
            continue
        for utxo in liste:
            if not isinstance(utxo, dict):
                continue
            txid = str(utxo.get("txid") or "").strip().lower()
            if not txid:
                continue
            try:
                vout = int(utxo.get("vout") or 0)
            except (TypeError, ValueError):
                vout = 0
            keys.add(f"{txid}:{vout}")
    return keys


def _adresse_zu_wallet_id(entries) -> dict[str, str]:
    """Empfangs- und Wechseladressen → Wallet-Kennung. Für den Sammelscan."""
    from core.derivation import derive_addresses
    from core.wallets import eintrag_id

    zu: dict[str, str] = {}
    for entry in entries:
        wid = eintrag_id(entry)
        try:
            tiefe = max(int(entry.max_addresses or 0), 1000)
            adressen = derive_addresses(
                entry.analyse_schluessel,
                max_addresses=tiefe,
                script_type=getattr(entry, "script_type", None),
            )
        except Exception:
            continue
        for addr in adressen or ():
            if addr and addr not in zu:
                zu[addr] = wid
    return zu


def _merke_scan_funde(
    stand_utxos,
    *,
    gesehen: set[str],
    entdeckt: list[dict],
    wallet_id: str = "",
    adressen: dict[str, str] | None = None,
) -> list[dict]:
    """UTXOs, die in diesem Scan neu sind (nicht der Stand vor dem Start)."""
    for utxo in stand_utxos or []:
        if not isinstance(utxo, dict):
            continue
        txid = str(utxo.get("txid") or "").strip().lower()
        if not txid:
            continue
        try:
            vout = int(utxo.get("vout") or 0)
            sats = int(utxo.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if sats < 0:
            continue
        key = f"{txid}:{vout}"
        if key in gesehen:
            continue
        gesehen.add(key)
        wid = wallet_id or (adressen or {}).get(str(utxo.get("address") or ""), "")
        entdeckt.append({
            "key": key,
            "value_sats": sats,
            "wallet_id": wid,
        })
    return entdeckt


def _utxo_zahl_je_wallet(
    stand_utxos,
    adressen: dict[str, str] | None = None,
) -> dict[str, int]:
    """Offene UTXOs je Wallet-ID — für die Nav-Pille beim Sammelscan."""
    zaehl: dict[str, int] = {}
    for utxo in stand_utxos or []:
        if not isinstance(utxo, dict):
            continue
        wid = str(utxo.get("wallet_id") or "").strip()
        if not wid:
            wid = (adressen or {}).get(str(utxo.get("address") or ""), "")
        if not wid:
            continue
        zaehl[wid] = zaehl.get(wid, 0) + 1
    return zaehl


def _ganze_payload_zahl(roh: object) -> int | None:
    """Leer → None. Unlesbar → ValueError."""
    if roh is None or str(roh).strip() == "":
        return None
    try:
        return int(str(roh).strip())
    except (TypeError, ValueError):
        raise ValueError("unlesbar") from None


def lese_rescan_scan_grenzen(payload: dict) -> tuple[str, int | None, int | None]:
    """scan_ab, Start­höhe, Gap-Limit. ``start_height`` sticht die Datumsschätzung."""
    scan_ab = str(payload.get("scan_ab") or "").strip()
    try:
        hoehe = _ganze_payload_zahl(payload.get("start_height"))
    except ValueError:
        raise ValueError("Scan-Block muss eine ganze Zahl ≥ 0 sein.") from None
    if hoehe is not None and hoehe < 0:
        raise ValueError("Scan-Block muss eine ganze Zahl ≥ 0 sein.")
    try:
        gap = _ganze_payload_zahl(payload.get("gap_limit"))
    except ValueError:
        raise ValueError(
            "Die Lücke muss eine ganze Zahl von 1 bis 10.000 sein."
        ) from None
    if gap is not None and (gap < 1 or gap > 10_000):
        raise ValueError("Die Lücke muss eine ganze Zahl von 1 bis 10.000 sein.")
    if hoehe is None and scan_ab:
        try:
            from core.utxo_report import estimate_block_height_for_date

            hoehe = estimate_block_height_for_date(scan_ab)
        except ValueError as exc:
            raise ValueError(f"Startdatum unlesbar: {exc}") from exc
    return scan_ab, hoehe, gap


def api_rescan(state: AppState, payload: dict) -> dict:
    from server import (
        ApiError,
        ScanSchonGeplant,
        _schaerfe_empfang_nach_sync,
        main,
        threading,
        wallets_mod,
    )

    kennung = str(payload.get("wallet_id", "")).strip()
    entry = wallets_mod.find_entry(state.entries, kennung)
    if entry is None:
        raise ApiError(404, "Wallet nicht gefunden.")

    try:
        scan_ab, start_hoehe, scan_gap = lese_rescan_scan_grenzen(payload)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        fetchers = None
        try:
            stand.phase(f"Verbinde für {entry.display_name}…")
            args = state.args_namespace()
            args.xpubs = [entry.analyse_schluessel]
            args.rescan = True
            # Start­höhe still setzen (für den Fall BIP-158). Log erst nach
            # Quellenwahl — sonst „BIP-158 …“ und direkt danach Fulcrum.
            if start_hoehe is not None:
                args.bip158_start = start_hoehe
            else:
                # First-seen überlebt Cache-Löschen — Scan dort ansetzen,
                # nicht wieder bei SegWit und nicht bei einer späteren
                # Datenquellen-Höhe. BIP-158 liest das zusätzlich selbst.
                alter_start = main.bip158_start_aus_first_seen(
                    entry.analyse_schluessel,
                    state.cache_dir,
                    floor=main.DEFAULT_BIP158_START_HEIGHT,
                )
                if alter_start is not None:
                    args.bip158_start = alter_start

            werte = dict(state.env().values())
            if scan_gap is not None:
                werte["BIP158_GAP_LIMIT"] = str(scan_gap)
            try:
                quelle, backend = main._setup_blockchain_client(args, werte)
            except SystemExit:
                from core.chain_sources import fetchers_fuer_utxo_entdeckung

                ersatz = fetchers_fuer_utxo_entdeckung(
                    werte,
                    args,
                    cache_dir=state.cache_dir,
                    immutable_cache_dir=state.immutable_cache_dir,
                )
                if ersatz is None:
                    raise
                quelle, fetchers = ersatz
                backend = None
            job.raise_if_cancelled()
            if isinstance(job.meta, dict):
                job.meta["source"] = quelle

            if quelle == "bip158":
                bip_start = getattr(args, "bip158_start", None)
                if scan_ab and bip_start is not None:
                    stand.phase(
                        f"BIP-158 nicht vor {scan_ab} "
                        f"(Block {bip_start:,})".replace(",", ".")
                    )
                elif bip_start is not None and start_hoehe is None:
                    stand.phase(
                        f"BIP-158 ab Wallet-Beginn "
                        f"(Block {bip_start:,})…".replace(",", ".")
                    )
                elif bip_start is not None:
                    stand.phase(
                        f"BIP-158 ab Block {bip_start:,}".replace(",", ".")
                    )

            if fetchers is None:
                fetchers = main._build_blockchain_fetchers(
                    quelle, backend, args, state.wallet_ctx,
                    immutable_cache_dir=state.immutable_cache_dir,
                )
            stand.phase(f"Scanne {entry.display_name} über {quelle}…")

            gesehen_funde = _bekannte_utxo_keys(state, [entry])
            entdeckt_funde: list[dict] = []

            def on_utxos_update(stand_utxos: list) -> None:
                # Zwischenstand schon während des Scans — GUI kann zeichnen.
                # Neue Punkte: Output-Datum, grau. Ohne Blockzeit kein X.
                neu = []
                for u in stand_utxos or []:
                    if not isinstance(u, dict):
                        continue
                    txid = str(u.get("txid") or "").strip()
                    if not txid:
                        continue
                    status = u.get("status") or {}
                    try:
                        ts = int(status.get("block_time") or 0)
                        vout = int(u.get("vout", 0))
                        sats = int(u.get("value") or 0)
                    except (TypeError, ValueError):
                        continue
                    if ts <= 0 or sats < 0:
                        continue
                    neu.append({
                        "key": f"{txid}:{vout}",
                        "time_ts": ts,
                        "value_sats": sats,
                        "wallet": entry.display_name,
                        "wallet_id": wid,
                        "address": str(u.get("address") or ""),
                    })
                job.result = {
                    "utxo_count": len(stand_utxos),
                    "partial": True,
                    "neu": neu,
                    "entdeckt": _merke_scan_funde(
                        stand_utxos,
                        gesehen=gesehen_funde,
                        entdeckt=entdeckt_funde,
                        wallet_id=wid,
                    ),
                }
                wort = "UTXO" if len(stand_utxos) == 1 else "UTXOs"
                stand.tick(f"{len(stand_utxos)} {wort} bisher gefunden…")

            gefunden = wallet_sync_engine.resolve_wallet_utxos(
                [entry.analyse_schluessel],
                fetchers["fetch_wallet_utxos"],
                fetchers["fetch_address_utxos"],
                fetchers.get("fetch_addresses_utxos"),
                state.cache_dir,
                quelle,
                rescan=True,
                max_addresses=entry.max_addresses,
                wallet=state.wallet_ctx,
                verify_utxo_spent=fetchers.get("verify_utxo_spent"),
                fulcrum=fetchers.get("fulcrum"),
                # Nicht-interaktiv: ein Rescan ist die ausdrückliche Zustimmung.
                on_missing_xpubs=lambda fehlend: True,
                on_progress=lambda text, *, sofort=False: (
                    stand.phase(text) if sofort else stand.tick(text)
                ),
                on_utxos_update=on_utxos_update,
            )
            job.raise_if_cancelled()
            n_empfang = _schaerfe_empfang_nach_sync(
                state,
                [entry],
                fulcrum=fetchers.get("fulcrum"),
                on_progress=lambda text, *, sofort=False: (
                    stand.phase(text) if sofort else stand.tick(text)
                ),
            )
            wort = "UTXO" if len(gefunden) == 1 else "UTXOs"
            stand.phase(
                f"{len(gefunden)} {wort} gefunden."
                + (" Empfangsadresse per Electrs geschärft." if n_empfang else "")
            )
            return {
                "utxo_count": len(gefunden),
                "partial": False,
                "empfang_scharf": n_empfang,
            }
        finally:
            schliessen = fetchers.get("close") if isinstance(fetchers, dict) else None
            if schliessen is not None:
                try:
                    schliessen()
                except Exception:
                    pass
            halt.set()
            stand.close()

    wid = wallets_mod.eintrag_id(entry)
    label = f"UTXO-Scan {entry.display_name}"
    try:
        return state.scan_queue.einreihen(
            kind="rescan",
            wallet_id=wid,
            wallet_name=entry.display_name,
            label=label,
            factory=lauf,
            scan_ab=scan_ab,
        )
    except ScanSchonGeplant as exc:
        raise ApiError(409, str(exc)) from exc


# Kennung in der Scan-Warteschlange. Kein Wallet trägt diese ID (Hash).
ALLE_WALLETS_SCAN_ID = "alle"


def api_rescan_alle(state: AppState) -> dict:
    """UTXO-Bestand aller ableitbaren Wallets in einem Warteschlangen-Job.

    P2P als einzige Quelle: ein gemeinsamer Filterdurchgang. Sonst der
    schnellste Bestandsweg (Electrs im LAN, sonst ein scantxoutset).
    """
    from server import (
        ApiError,
        ScanSchonGeplant,
        _schaerfe_empfang_nach_sync,
        main,
        threading,
    )

    wallets = list(state.analyse_entries)
    if not wallets:
        raise ApiError(400, "Keine Wallets zum Scannen.")

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag
        from core.wallet_sync_engine import sammel_utxo_modus

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        fetchers = None
        try:
            stand.phase(f"Verbinde für {len(wallets)} Wallets…")
            args = state.args_namespace()
            args.xpubs = [e.analyse_schluessel for e in wallets]
            args.rescan = True
            werte = state.env().values()
            try:
                quelle, backend = main._setup_blockchain_client(args, werte)
            except SystemExit:
                from core.chain_sources import fetchers_fuer_utxo_entdeckung

                ersatz = fetchers_fuer_utxo_entdeckung(
                    werte,
                    args,
                    cache_dir=state.cache_dir,
                    immutable_cache_dir=state.immutable_cache_dir,
                )
                if ersatz is None:
                    raise
                quelle, fetchers = ersatz
                backend = None
            job.raise_if_cancelled()
            if fetchers is None:
                fetchers = main._build_blockchain_fetchers(
                    quelle, backend, args, state.wallet_ctx,
                    immutable_cache_dir=state.immutable_cache_dir,
                )
            fulcrum = fetchers.get("fulcrum")
            modus = sammel_utxo_modus(werte, fulcrum)
            if isinstance(job.meta, dict):
                job.meta["source"] = "bip158" if modus == "p2p" else (
                    "bitcoind" if modus == "scantxoutset" else quelle
                )
            max_by = {
                e.analyse_schluessel: int(e.max_addresses)
                for e in wallets
            }

            def max_addresses_for(xpub: str) -> int:
                return int(max_by.get(xpub) or 0) or 20

            gesehen_funde = _bekannte_utxo_keys(state, wallets)
            entdeckt_funde: list[dict] = []
            adressen_funde = _adresse_zu_wallet_id(wallets)

            def on_utxos_update(stand_utxos: list) -> None:
                n = len(stand_utxos or [])
                job.result = {
                    "utxo_count": n,
                    "partial": True,
                    "utxo_je_wallet": _utxo_zahl_je_wallet(
                        stand_utxos, adressen_funde,
                    ),
                    "entdeckt": _merke_scan_funde(
                        stand_utxos,
                        gesehen=gesehen_funde,
                        entdeckt=entdeckt_funde,
                        adressen=adressen_funde,
                    ),
                }
                wort = "UTXO" if n == 1 else "UTXOs"
                stand.tick(f"{n} {wort} bisher gefunden…")

            gefunden, quelle_lauf = wallet_sync_engine.scanne_alle_xpubs_utxo(
                [e.analyse_schluessel for e in wallets],
                fetchers["fetch_wallet_utxos"],
                state.cache_dir,
                quelle,
                max_addresses_for=max_addresses_for,
                wallet=state.wallet_ctx,
                fulcrum=fulcrum,
                on_progress=lambda text, *, sofort=False: (
                    stand.phase(text) if sofort else stand.tick(text)
                ),
                on_utxos_update=on_utxos_update,
                env=werte,
                immutable_cache_dir=state.immutable_cache_dir,
                start_height=getattr(args, "bip158_start", None),
            )
            if isinstance(job.meta, dict):
                job.meta["source"] = quelle_lauf
            job.raise_if_cancelled()
            n_empfang = _schaerfe_empfang_nach_sync(
                state,
                wallets,
                fulcrum=fulcrum,
                on_progress=lambda text, *, sofort=False: (
                    stand.phase(text) if sofort else stand.tick(text)
                ),
            )
            n = len(gefunden)
            wort = "UTXO" if n == 1 else "UTXOs"
            stand.phase(
                f"{n} {wort} in {len(wallets)} Wallets."
                + (" Empfangsadresse per Electrs geschärft." if n_empfang else "")
            )
            return {
                "utxo_count": n,
                "wallet_count": len(wallets),
                "partial": False,
                "source": quelle_lauf,
                "empfang_scharf": n_empfang,
            }
        finally:
            schliessen = fetchers.get("close") if isinstance(fetchers, dict) else None
            if schliessen is not None:
                try:
                    schliessen()
                except Exception:
                    pass
            halt.set()
            stand.close()

    try:
        return state.scan_queue.einreihen(
            kind="rescan",
            wallet_id=ALLE_WALLETS_SCAN_ID,
            wallet_name="Alle Wallets",
            label="UTXO-Scan alle Wallets",
            factory=lauf,
        )
    except ScanSchonGeplant as exc:
        raise ApiError(409, str(exc)) from exc


def api_header_vorab(state: AppState) -> dict:
    """Startet den Header-Download, wenn die Datei noch fehlt."""
    from server import (
        _header_tip,
        starte_header_vorab,
    )

    starte_header_vorab(state, nur_wenn_leer=True)
    return {
        "header_job_id": state.header_job_id,
        "header_tip": _header_tip(state),
    }
