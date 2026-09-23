"""Electrs-/Wallet-Sync-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations

import logging
import threading
import time

import main
from core import wallets as wallets_mod
from httpserver.empfang import (
    _merke_own_fulcrum_client,
    _schaerfe_empfang_nach_sync,
)

LOGGER = logging.getLogger("satsage.server")


def _verwerfe_electrs_verbindungen(state: AppState) -> None:
    """
    Alte Electrs-Sockets/Sessions nach Host-/Port-Wechsel schließen.

    * Empfangs-QR-Client (AppState-Cache)
    * Wallet-Watch-Subscribe (sonst hängt die Session am alten Endpoint)
    """
    # Empfang-Clients: reload() hat sie schon genullt; sicherheitshalber nochmal.
    with getattr(state, "_empfang_fulcrum_lock", threading.Lock()):
        alt = getattr(state, "_empfang_fulcrum", None)
        alt_pub = getattr(state, "_empfang_public_fulcrum", None)
        state._empfang_fulcrum = None
        state._empfang_public_fulcrum = None
    for client in (alt, alt_pub):
        if client is None:
            continue
        try:
            client.close()
        except Exception:
            pass
    try:
        from core import wallet_watch

        if wallet_watch.get_watch_service().laeuft:
            wallet_watch.restart_wallet_watch(
                state,
                on_log=lambda t: LOGGER.info("%s", t),
            )
        else:
            # Watch war aus — falls Option an, frisch starten mit neuem Endpoint.
            wallet_watch.starte_wallet_watch(
                state,
                on_log=lambda t: LOGGER.info("%s", t),
            )
    except Exception as exc:
        LOGGER.warning("Electrs-Verbindungen nach Config-Wechsel: %s", exc)

def tip_sync_laeuft(state: AppState) -> bool:
    """Ob gerade ein Tip-Nachzug-Job läuft (Watcher darf dann nachziehen)."""
    jid = state.wallet_sync_job_id
    if not jid:
        return False
    job = state.jobs.get(jid)
    if job is None or job.status != "running":
        # Fertig/weg: stale ID freigeben — sonst meldet /api/config ewig den alten Job.
        if job is None or job.status in ("done", "failed", "cancelled"):
            state.wallet_sync_job_id = None
        return False
    # Abbruch angefordert: neuer Start darf den Slot übernehmen.
    if getattr(job, "cancelled", False):
        return False
    return True


def _tip_sync_abbrechen(state: AppState, *, warte_s: float = 3.0) -> None:
    """Bricht laufenden Tip-Nachzug ab und gibt den Slot frei."""
    jid = state.wallet_sync_job_id
    if not jid:
        return
    job = state.jobs.get(jid)
    if job is not None and job.status == "running":
        try:
            state.jobs.cancel(jid)
        except Exception:
            pass
        deadline = time.monotonic() + max(0.0, warte_s)
        while time.monotonic() < deadline:
            job = state.jobs.get(jid)
            if job is None or job.status != "running":
                break
            time.sleep(0.05)
    state.wallet_sync_job_id = None


def starte_wallet_aktualisierung(
    state: AppState,
    *,
    erzwingen: bool = False,
    wallet_ids: list[str] | None = None,
    still: bool = False,
) -> dict | None:
    """
    Hintergrund: Wallets mit Cache bis Chain-Tip nachziehen.

    Kein Fullscan — BIP-158 ab ``scan_tip_height`` oder Electrs light.
    *erzwingen*: auch ohne ``WALLETS_BEIM_START_AKTUALISIEREN`` (UI-Knopf).
    *wallet_ids*: nur diese Wallets; sonst alle mit Cache.
    *still*: Hintergrund (Wallet-Watch-Fallback) — GUI ohne Nav-„aktualisiere…“.
    Rückgabe: Job-Dict bei Start, None wenn nichts zu tun / schon läuft.
    """
    werte = state.env().values()
    if not erzwingen and not main.resolve_wallets_beim_start_aktualisieren(
        werte
    ):
        return None
    if tip_sync_laeuft(state):
        return None

    # Auch leerer Cache (0 UTXOs) zählt — Scan-Stand zum Fortsetzen.
    eintraege = [
        e for e in state.analyse_entries
        if main.load_xpub_cache_entry(e.analyse_schluessel, state.cache_dir)
    ]
    if wallet_ids:
        erlaubt = {str(x) for x in wallet_ids}
        eintraege = [
            e for e in eintraege
            if wallets_mod.eintrag_id(e) in erlaubt
        ]
    if not eintraege:
        return None

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        try:
            nur_bekannte = main.resolve_wallets_nur_bekannte_utxos(
                state.env().values()
            )
            extras = []
            if still:
                extras.append("still")
            if nur_bekannte:
                extras.append("nur bekannte UTXOs, kein Gap")
            suffix = f" ({', '.join(extras)})…" if extras else "…"
            stand.phase(
                f"Aktualisiere {len(eintraege)} Wallet(s) bis Chain-Tip{suffix}"
            )
            args = state.args_namespace()
            args.xpubs = [e.analyse_schluessel for e in eintraege]
            quelle, backend = main._setup_blockchain_client(args, state.env().values())
            job.raise_if_cancelled()
            fetchers = main._build_blockchain_fetchers(
                quelle, backend, args, state.wallet_ctx,
                immutable_cache_dir=state.immutable_cache_dir,
            )
            stand.phase(f"Datenquelle: {quelle}")

            # Tip-Nachzug:
            # * Eigener Electrs → nur Electrs light, kein BIP-158 (schneller;
            #   Subscribe hält danach aktuell).
            # * Nur BIP-158 / kein Electrs → Filter inkrementell.
            # * Öffentliches Electrum → BIP-158 wenn Tip da (Privatsphäre).
            # * nur_bekannte → kein Gap / kein BIP-158-Walk.
            bip158_fetch = None
            fulcrum = fetchers.get("fulcrum")
            electrs_eigen = (
                quelle == "fulcrum"
                and fulcrum is not None
                and main.is_own_fulcrum_backend(fulcrum)
            )
            # Kopf-Pille sofort: Indexer schon in Nutzung, nicht erst Peer-Takt.
            if electrs_eigen:
                own_stand = _merke_own_fulcrum_client(state, fulcrum)
                if own_stand and isinstance(job.meta, dict):
                    job.meta["own_fulcrum"] = own_stand
                    soft = str(own_stand.get("software") or "").strip()
                    if soft:
                        stand.phase(f"Indexer: {soft}")
            schluessel = [e.analyse_schluessel for e in eintraege]
            hat_tip = any(
                (main.load_xpub_cache_entry(x, state.cache_dir) or {})
                .get("raw", {})
                .get("scan_tip_height")
                is not None
                for x in schluessel
            )
            if nur_bekannte:
                stand.phase(
                    "Tip-Nachzug: nur bekannte UTXOs "
                    "(kein Gap — neue Adressen per UTXO-Scan)"
                )
            elif electrs_eigen:
                stand.phase(
                    "Tip-Nachzug: eigener Electrs (listunspent/Gap) — "
                    "ohne BIP-158; Subscribe übernimmt Live-Updates"
                )
            elif quelle == "bip158":
                bip158_fetch = fetchers.get("fetch_wallet_utxos")
                stand.phase("Tip-Nachzug: BIP-158 inkrementell")
            elif hat_tip:
                stand.phase("Prüfe BIP-158 für Tip-Nachzug…")
                job.raise_if_cancelled()
                bip158_fetch = main.try_bip158_fetch_for_tip_sync(
                    args,
                    state.env().values(),
                    state.wallet_ctx,
                    immutable_cache_dir=state.immutable_cache_dir,
                )
                if bip158_fetch is not None:
                    stand.phase(
                        "Tip-Nachzug: BIP-158 inkrementell "
                        "(kein eigener Electrs)"
                    )
                else:
                    stand.phase(
                        "Tip-Nachzug: Electrs/Adresse light "
                        "(kein BIP-158-Peer)"
                    )
            else:
                stand.phase(
                    "Tip-Nachzug: Electrs light "
                    "(kein scan_tip_height — kein Filter-Nachzug)"
                )

            def on_progress(text, *, sofort=False):
                job.raise_if_cancelled()
                if sofort:
                    stand.phase(text)
                else:
                    stand.tick(text)

            zaehler = {"ok": 0, "utxos": 0}
            # xpub → Nav-ID, damit die GUI je fertigem Wallet „gerade eben“ zeigt
            # (nicht erst wenn alle Wallets durch sind).
            id_nach_schluessel = {
                e.analyse_schluessel: wallets_mod.eintrag_id(e)
                for e in eintraege
            }
            if isinstance(job.meta, dict):
                job.meta["done_wallet_ids"] = []
                job.meta["total_wallets"] = len(eintraege)

            def on_done(xpub, utxos):
                if utxos is not None:
                    zaehler["ok"] += 1
                    zaehler["utxos"] += len(utxos)
                wid = id_nach_schluessel.get(xpub)
                if not wid or not isinstance(job.meta, dict):
                    return
                fertig = list(job.meta.get("done_wallet_ids") or [])
                if wid in fertig:
                    return
                fertig.append(wid)
                job.meta["done_wallet_ids"] = fertig
                job.meta["done_wallets"] = len(fertig)
                # Leichte Message für Poller — ohne Log-Flut.
                name = next(
                    (
                        e.display_name for e in eintraege
                        if wallets_mod.eintrag_id(e) == wid
                    ),
                    wid,
                )
                job.message = (
                    f"Wallet-Tip {len(fertig)}/{len(eintraege)}: "
                    f"„{name}“ aktuell"
                )

            main.sync_wallets_zum_tip(
                [e.analyse_schluessel for e in eintraege],
                fetchers["fetch_wallet_utxos"],
                fetchers["fetch_address_utxos"],
                fetchers.get("fetch_addresses_utxos"),
                state.cache_dir,
                quelle,
                max_addresses=main.DEFAULT_MAX_ADDRESSES,
                wallet=state.wallet_ctx,
                fulcrum=fetchers.get("fulcrum"),
                verify_utxo_spent=fetchers.get("verify_utxo_spent"),
                bip158_fetch_wallet_utxos=bip158_fetch,
                on_progress=on_progress,
                on_wallet_done=on_done,
                nur_bekannte=nur_bekannte,
            )
            job.raise_if_cancelled()
            # UTXO-Tip ist fertig → Nav darf „gerade eben“ zeigen. Empfangs-QR
            # wird danach noch geschärft; der Nutzer sieht das am QR, nicht am
            # Wallet-Marker.
            if isinstance(job.meta, dict):
                job.meta["phase"] = "empfang"
            job.result = {
                "wallets": zaehler["ok"],
                "utxo_count": zaehler["utxos"],
                "empfang_phase": True,
            }
            if state.wallet_sync_job_id == job.id:
                state.wallet_sync_job_id = None
            stand.phase(
                f"{zaehler['ok']} Wallet(s) aktualisiert, "
                f"{zaehler['utxos']} UTXO(s) — Empfangsadressen folgen…"
            )
            n_empfang = _schaerfe_empfang_nach_sync(
                state,
                eintraege,
                fulcrum=fetchers.get("fulcrum"),
                on_progress=lambda text, *, sofort=False: (
                    stand.phase(text) if sofort else stand.tick(text)
                ),
            )
            job.raise_if_cancelled()
            if n_empfang:
                stand.phase(f"Empfang per Electrs: {n_empfang} Wallet(s).")
            return {
                "wallets": zaehler["ok"],
                "utxo_count": zaehler["utxos"],
                "empfang_scharf": n_empfang,
            }
        finally:
            halt.set()
            stand.close()
            # Slot freigeben sobald der Job-Thread endet (done/fail/cancel).
            if state.wallet_sync_job_id == job.id:
                state.wallet_sync_job_id = None
            try:
                from core import wallet_watch

                wallet_watch.get_watch_service().tip_nachzug_job_beendet()
            except Exception:
                pass

    namen = ", ".join(e.display_name for e in eintraege[:3])
    if len(eintraege) > 3:
        namen += f" +{len(eintraege) - 3}"
    if still:
        label = f"Tip-Nachzug still ({namen})"
    elif erzwingen:
        label = f"Tip-Nachzug ({namen})"
    else:
        label = f"Start-Aktualisierung ({namen})"
    job = state.jobs.start(
        "wallet_sync",
        label,
        lauf,
        meta={
            "art": "wallet_sync",
            "wallet_ids": [wallets_mod.eintrag_id(e) for e in eintraege],
            "still": bool(still),
        },
    )
    state.wallet_sync_job_id = job.id
    return job.as_dict()
