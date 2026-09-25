"""Job-/Scan-Pipeline-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

from typing import Any


def api_jobs(state: Any, query: dict) -> dict:
    """
    Nutzer-Jobs für die Nav: running + finished der letzten ~10 s,
    plus Scan-Pipeline (aktuell + Warteschlange).
    """
    # Späte Imports: Hilfsfunktionen bleiben vorerst in server.py (keine Zyklen zur Load-Zeit).
    from server import (
        _live_p2p_peers,
        _wallet_name_fuer_utxo,
        _wallet_watch_status,
    )
    try:
        recent = float((query.get("recent_s") or ["3"])[0])
    except (TypeError, ValueError, IndexError):
        recent = 3.0
    recent = max(0.0, min(recent, 120.0))
    jobs = [j.as_dict() for j in state.jobs.nutzer_jobs(recent_s=recent)]
    # Laufende Traces ohne wallet_name (vor dem Fix gestartet / Browser-Reload):
    # Name aus Cache nachziehen, damit der Job-Klick kein „unbekanntes Wallet“ zeigt.
    for eintrag in jobs:
        if eintrag.get("kind") != "trace":
            continue
        meta = eintrag.get("meta") or {}
        if meta.get("wallet_name") or meta.get("wallet"):
            continue
        txid = meta.get("txid") or ""
        try:
            vout = int(meta.get("vout"))
        except (TypeError, ValueError):
            continue
        if not txid:
            continue
        name = _wallet_name_fuer_utxo(state, str(txid), vout)
        if name:
            meta = dict(meta)
            meta["wallet_name"] = name
            eintrag["meta"] = meta
    # Teil-Ergebnis an hanging result für rescan
    for daten in jobs:
        job = state.jobs.get(daten["id"])
        if job is not None and job.result is not None:
            daten["result"] = job.result
    watch = _wallet_watch_status()
    block_event = None
    try:
        seq = int(watch.get("last_block_seq") or 0)
        hoehe = watch.get("last_block_height")
        if seq > 0 and hoehe is not None:
            block_event = {"seq": seq, "height": int(hoehe)}
    except (TypeError, ValueError):
        block_event = None
    if not state.context_bereit():
        jobs.insert(0, {
            "id": "wallet-context",
            "kind": "wallet_context",
            "label": "Wallets werden vorbereitet",
            "status": "running",
            "message": "Adressen und Cache werden gelesen…",
            "log": [],
            "running": True,
            "elapsed_s": 0,
            "error": None,
            "meta": {"still": True},
            "started_at": None,
            "finished_at": None,
        })
    return {
        "jobs": jobs,
        "scan_pipeline": state.scan_queue.snapshot(),
        "block_event": block_event,
        "context_bereit": state.context_bereit(),
    }


def api_job(state: Any, job_id: str) -> dict:
    from server import ApiError, _live_p2p_peers

    job = state.jobs.get(job_id)
    if job is None:
        raise ApiError(404, "Vorgang nicht gefunden.")
    daten = job.as_dict()
    # Auch während des Laufs: Teil-Ergebnis (z. B. bisherige UTXO-Zahl),
    # damit die Oberfläche schon zeichnen kann.
    if isinstance(job.result, dict):
        daten["result"] = job.result
    # Während Tip-Sync/BIP-158: Live-Peers für die Kopf-Pille mitschicken.
    if job.status == "running" and job.kind in (
        "wallet_sync", "headers", "rescan", "verlauf",
    ):
        live = _live_p2p_peers()
        if live:
            daten["live_p2p_peers"] = live
    return daten


def api_cancel_job(state: Any, job_id: str) -> dict:
    """
    Bricht einen laufenden Job ab — oder einen wartenden Scan in der Pipeline.

    Scan-Queue: ``queue_id`` der Warteschlange wird entfernt, ohne zu starten.
    """
    from server import ApiError

    jid = str(job_id or "").strip()
    if not jid:
        raise ApiError(400, "Keine Job-ID.")
    # Zuerst Scan-Pipeline (wartend + aktiv), sonst allgemeine Registry.
    if state.scan_queue.cancel(jid):
        return {"cancelled": True}
    if state.jobs.cancel(jid):
        return {"cancelled": True}
    raise ApiError(409, "Vorgang läuft nicht mehr.")
