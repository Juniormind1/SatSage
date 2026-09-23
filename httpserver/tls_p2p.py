"""TLS-Auto- und P2P-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations


def _persist_tls_auto(state: AppState, quellen: list, *, on_log=None) -> list:
    """
    Schreibt TLS-Auto-Ergebnis (FULCRUM_SSL / FULCRUM_TOR_SSL) in die .env.

    Nur Desktop/.env — nicht Start9/Umbrel-Bridge. Liefert Quellenliste mit
    aktualisierten Schalter-Feldern und geleertem ssl_persist.
    """
    from dataclasses import replace

    from server import _NODE_MANAGED, source_mod

    if state.managed_by in _NODE_MANAGED:
        return quellen
    erlaubt = source_mod.EDITIERBARE_FELDER.get("own_fulcrum", ())
    persist: dict[str, str | None] = {}
    for q in quellen:
        if q.key != "own_fulcrum" or not q.ssl_persist:
            continue
        for k, v in q.ssl_persist.items():
            if k in erlaubt:
                persist[k] = v
    if not persist:
        return quellen
    try:
        env = state.env()
        env.apply(persist)
        env.save()
        state.reload()
    except OSError:
        return quellen
    if on_log:
        bits = ", ".join(f"{k}={v}" for k, v in persist.items())
        on_log(f"TLS-Einstellung gespeichert: {bits}")
    werte = state.env().values()
    frisch = {q.key: q for q in source_mod.describe_sources(werte)}
    out: list = []
    for q in quellen:
        basis = frisch.get(q.key, q)
        out.append(
            replace(
                basis,
                reachable=q.reachable,
                error=q.error,
                peer_count=q.peer_count,
                peer_hosts=list(q.peer_hosts),
                software=q.software,
                software_raw=q.software_raw,
                ssl_effective=q.ssl_effective,
                ssl_persist={},
                note=q.note or basis.note,
                detail=q.detail or basis.detail,
                log=list(q.log),
            )
        )
    return out


def _live_p2p_peers() -> list[str]:
    """Gerade offene Compact-Filter-Peers (Tip-Sync / Scan)."""
    try:
        from bip158_scanner import live_filter_peer_hosts

        return live_filter_peer_hosts()
    except Exception:
        return []


def _breche_p2p_jobs_ab(state: AppState) -> list[str]:
    """
    Bricht laufende/geplante Jobs ab, die über BIP-158/P2P hängen.

    Aufruf beim Papierkorb „P2P trennen“ — Nutzer startet Electrum/Scan selbst.
    """
    abgebrochen: list[str] = []
    gesehen: set[str] = set()

    def _merk(jid: str | None) -> None:
        j = str(jid or "").strip()
        if j and j not in gesehen:
            gesehen.add(j)
            abgebrochen.append(j)

    # Header-Vorab ist immer P2P.
    hid = getattr(state, "header_job_id", None)
    if hid and (state.scan_queue.cancel(hid) or state.jobs.cancel(hid)):
        _merk(hid)
    state.header_job_id = None

    # Scan-Pipeline: aktiver Job + Warteschlange (sonst startet der nächste
    # Eintrag noch mit der alten P2P-Priorität).
    try:
        snap = state.scan_queue.snapshot()
    except Exception:
        snap = {"current": None, "queued": []}
    cur = snap.get("current") or {}
    jid = cur.get("job_id")
    if jid and state.scan_queue.cancel(jid):
        _merk(jid)
    for eintrag in snap.get("queued") or []:
        qid = eintrag.get("queue_id")
        if qid and state.scan_queue.cancel(qid):
            _merk(qid)

    # Laufende Registry-Jobs: Header/Rescan/Verlauf; wallet_sync nur mit
    # bekannter BIP-158-Quelle (sonst Electrs-Tip-Sync nicht killen).
    for job in state.jobs.list():
        if job.status != "running":
            continue
        if job.id in gesehen:
            continue
        src = (job.meta or {}).get("source")
        if job.kind == "headers" or job.kind in ("rescan", "verlauf"):
            if state.jobs.cancel(job.id) or state.scan_queue.cancel(job.id):
                _merk(job.id)
        elif job.kind == "wallet_sync" and src == "bip158":
            if state.jobs.cancel(job.id):
                _merk(job.id)

    return abgebrochen
