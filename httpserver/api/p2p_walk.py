"""HTTP: P2P-Entdeckung und Herkunft gegen den Electrs-Cache."""
from __future__ import annotations

from typing import Any


def api_p2p_walk_abgleich(state: Any) -> dict:
    from server import ApiError

    from core.jobs import JobQuotaExceeded
    from core.p2p_walk_abgleich import cache_utxos

    if not state.entries:
        raise ApiError(400, "Kein Wallet eingetragen.")
    soll_utxos = cache_utxos(state.entries, state.cache_dir)
    if not soll_utxos:
        raise ApiError(
            400,
            "Kein UTXO im Cache. Zuerst über Electrs scannen.",
        )

    def lauf(job):
        from core.bip158_wallet import (
            create_bip158_client_from_env,
            fetch_tx_p2p_mit_fallback,
            fetch_wallet_utxos_bip158,
        )
        from core.jobs import Fortschritt
        from core.p2p_walk_abgleich import (
            gleiche_herkunft_ab,
            utxos_mit_herkunft,
            vergleiche_entdeckung,
        )
        from core.xpub_cache import _xpub_alter_path
        import shutil

        stand = Fortschritt(job)
        client = None
        try:
            stand.phase(
                f"P2P-Entdeckung gegen {len(soll_utxos)} Cache-UTXOs…"
            )
            job.raise_if_cancelled()
            env = dict(state.env().values())
            env["BIP158_P2P"] = "1"
            from core.p2p import p2p_headers_path

            arbeit = state.cache_dir.parent / "p2p_walk_abgleich"
            scan_cache = arbeit / "utxo_cache"
            scan_cache.mkdir(parents=True, exist_ok=True)
            # First-seen mitgeben, UTXO-Datei nicht. Sonst startet der
            # Scan am fertigen Tip und entdeckt nichts neu.
            for entry in state.entries:
                xpub = entry.analyse_schluessel
                alter = _xpub_alter_path(xpub, state.cache_dir)
                if alter.is_file():
                    shutil.copy2(alter, scan_cache / alter.name)
            kopf = p2p_headers_path(state.immutable_cache_dir)
            ziel_kopf = p2p_headers_path(arbeit / "immutable_cache")
            if kopf.is_file() and not ziel_kopf.is_file():
                ziel_kopf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(kopf, ziel_kopf)
            client = create_bip158_client_from_env(
                env,
                verbose=False,
                cache_dir=scan_cache,
                immutable_dir=arbeit / "immutable_cache",
            )
            job.raise_if_cancelled()
            xpubs = [e.analyse_schluessel for e in state.entries]
            max_by = {e.analyse_schluessel: e.max_addresses for e in state.entries}
            entdeckt = fetch_wallet_utxos_bip158(
                client,
                xpubs,
                max_addresses=max(max_by.values()) if max_by else 50,
                max_addresses_by_xpub=max_by,
            )
            job.raise_if_cancelled()
            eigene = set(state.wallet_ctx.address_to_wallet)
            bestand = vergleiche_entdeckung(
                soll_utxos, entdeckt, addr_wallet=state.wallet_ctx.address_to_wallet,
            )
            stand.phase(
                f"P2P-Entdeckung: {bestand['gefunden']}/{bestand['soll']}, "
                f"fehlend {bestand['fehlend']}, extra {bestand['extra']}."
            )

            def get_tx(txid: str) -> dict:
                job.raise_if_cancelled()
                return fetch_tx_p2p_mit_fallback(client, txid)

            soll_herkunft = utxos_mit_herkunft(
                state.entries, state.cache_dir, state.immutable_cache_dir,
            )
            if soll_herkunft:
                stand.phase(
                    f"P2P-Herkunft gegen {len(soll_herkunft)} gespeicherte Bäume…"
                )
            herkunft = gleiche_herkunft_ab(
                soll_herkunft,
                get_tx,
                eigene=eigene,
                wallet=state.wallet_ctx,
                on_progress=stand.tick,
                abbruch=job.raise_if_cancelled,
            )
            ok = bestand["ok"] and (herkunft["ok"] or not soll_herkunft)
            stand.phase(
                f"P2P-Check: Entdeckung "
                f"{'gleich' if bestand['ok'] else 'abweichend'}, "
                f"Herkunft {herkunft['verglichen']}/{herkunft['gesamt']}."
            )
            return {
                "ok": ok,
                "entdeckung": bestand,
                "verglichen": herkunft["verglichen"],
                "abweichungen": herkunft["abweichungen"] + (
                    0 if bestand["ok"] else bestand["fehlend"] + bestand["extra"] + bestand["betrag"]
                ),
                "gesamt": herkunft["gesamt"],
                "herkunft": herkunft,
            }
        finally:
            stand.close()
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    try:
        job = state.jobs.start(
            "p2p-walk",
            "P2P-Check",
            lauf,
            meta={"utxos": len(soll_utxos)},
        )
    except JobQuotaExceeded as exc:
        raise ApiError(409, str(exc)) from exc
    return {"job_id": job.id, "utxos": len(soll_utxos)}
