"""Kleine lokale Werkzeuge."""

from __future__ import annotations

from typing import Any


def api_tools_adresse(state: Any, payload: dict | None) -> dict:
    """Gehört die Adresse zu einem hinterlegten Wallet? Auch unbenutzt."""
    from core.adresse_werkzeug import pruefe_eigene_adresse

    koerper = payload or {}
    return pruefe_eigene_adresse(
        state.wallet_ctx,
        str(koerper.get("address") or ""),
    )


def api_tools_schatzsuche(state: Any, _payload: dict | None = None) -> dict:
    """
    Startet scantxoutset jenseits des Suchfensters.

    409, wenn kein Core mit scantxoutset verbunden ist oder ein UTXO-Scan
    den Node gerade selbst mit scantxoutset belegt.
    """
    from server import ApiError

    from core.schatzsuche import core_fuer_scantxoutset, jage_verlorene_schaetze

    for job in state.jobs.list():
        if job.kind == "schatzsuche" and job.status == "running":
            raise ApiError(409, "Die Schatzsuche läuft schon.")
    laufend = state.scan_queue.snapshot().get("current") or {}
    if laufend.get("kind") == "rescan":
        raise ApiError(
            409,
            "Ein UTXO-Scan läuft. scantxoutset ist auf dem Node belegt.",
        )

    probe = core_fuer_scantxoutset(state.env().values())
    if probe is None:
        raise ApiError(
            409,
            "Keine verbundene Bitcoin-Core-Quelle mit scantxoutset.",
        )
    try:
        probe.close()
    except Exception:
        pass

    def lauf(job):
        def fortschritt(text: str, sofort: bool = False) -> None:
            if sofort:
                job.progress(text, log=True)
            else:
                job.progress(text, log=False)

        funde = jage_verlorene_schaetze(
            env=state.env().values(),
            wallets=state.analyse_entries,
            wallet_ctx=state.wallet_ctx,
            cache_dir=state.cache_dir,
            on_log=lambda text: job.progress(text, log=True),
            on_progress=fortschritt,
            raise_if_cancelled=job.raise_if_cancelled,
        )
        n = len(funde)
        wort = "UTXO" if n == 1 else "UTXOs"
        job.progress(
            f"{n} {wort} außerhalb des Suchfensters." if n else
            "Kein UTXO außerhalb des Suchfensters.",
            log=True,
        )
        return {
            "count": n,
            "funde": funde,
            "sats": max((int(f.get("sats") or 0) for f in funde), default=0),
        }

    job = state.jobs.start(
        "schatzsuche",
        "Jäger der verlorene Schätze",
        lauf,
        meta={"art": "schatzsuche"},
    )
    return job.as_dict()
