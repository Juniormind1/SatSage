#!/usr/bin/env python3
"""
BIP-158-Scanner über Bitcoin-P2P (BIP 157 Compact Filter).

Filter und Blöcke kommen von Peers mit NODE_COMPACT_FILTERS, nicht von
Bitcoin-Core-RPC. Abgleich lokal. Ungenutzte Keys nur gegen das Turbo-Fenster
(Wasabi-TurboSync), damit False-Positive-Downloads in der Historie entfallen.

chiabip158 nur für Self-Tests. Produktions-Filter: _CoreBasicFilterMatcher.

Scan-Pipeline, Block-Extract, Peers und ``BIP158Scanner`` liegen in
``core.bip158_scan`` und werden hier re-exportiert (Slice 5 Schritt 7).
"""

from __future__ import annotations

import argparse
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterable

try:
    from chiabip158 import PyBIP158
except ImportError:  # pragma: no cover - optional at import time
    PyBIP158 = None  # type: ignore[misc, assignment]

from core.bip158_filter import (
    BASIC_FILTER_M,
    BASIC_FILTER_P,
    MatchedOutput,
    MatchedTransaction,
    ProgressCallback,
    ScanProgress,
    ScanResult,
    _BitStreamReader,
    _BitStreamWriter,
    _CoreBasicFilterMatcher,
    _encode_core_basic_filter,
    _golomb_rice_decode,
    _golomb_rice_encode,
    _hash_to_range,
    _match_with_chiabip158,
    _read_compact_size,
    _rotl64,
    _sip_keys_from_block_hash,
    _siphash_round,
    _write_compact_size,
    siphash,
)

from core.bip158_scan import (
    DEFAULT_GAP_LIMIT,
    DEFAULT_MAX_INDEX,
    DEFAULT_MAX_ADDRESSES,
    TURBO_WINDOW,
    _encoders_for_xpub,
    derive_script_pubkeys_from_xpub,
    addresses_to_script_pubkeys,
    _BLOCK_PENDING,
    plane_filter_passes,
    gap_scripts_anfang,
    scripts_mit_gap_um_treffer,
    _cfilter_chunks,
    _filter_umfang,
    _filter_prozent_text,
    _tick_filter_stand,
    _kuerze_adresse,
    _filter_treffer_praefix,
    _beschreibe_block_treffer,
    _lade_cfilter_chunk,
    _block_aus_warteschlange,
    _zeilen_bloecke_aufloesen,
    verteile_cfilter_chunks,
    parse_raw_block,
    _header_unixzeit,
    _verlauf_eintrag,
    _uebernehme_block_verlauf,
    extract_from_parsed_block,
    _LIVE_FILTER_LOCK,
    _LIVE_FILTER_PEERS,
    _peer_host_label,
    melde_live_filter_peers,
    clear_live_filter_peers,
    live_filter_peer_hosts,
    BIP158Scanner,
    Bip158Client,
    create_bip158_client_from_env,
    vorab_block_header,
    verify_p2p_filters,
    _matched_output_to_utxo,
)

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _used_scripts_aus_cache(xpub: str, cache_dir: Path | None) -> set[bytes]:
    """
    Used-Keys für TurboSync-Historie — nur nach abgeschlossenem Fullscan.

    Zwischenstände nach Abbruch (UTXOs ohne ``bip158_fullscan_ok``) liefern
    absichtlich leer, damit der nächste Lauf wieder Turbo-Erstscan macht.
    """
    if cache_dir is None:
        return set()
    try:
        import main as main_mod

        eintrag = main_mod.load_xpub_cache_entry(xpub, cache_dir)
    except Exception:
        return set()
    roh = (eintrag or {}).get("raw") or {}
    if not main_mod.bip158_fullscan_ist_fertig(roh):
        return set()
    adressen: list[str] = []
    for utxo in roh.get("utxos") or []:
        addr = utxo.get("address")
        if addr:
            adressen.append(addr)
    adressen.extend(roh.get("scanned_addresses") or [])
    try:
        verlauf = main_mod.load_xpub_verlauf_cache(xpub, cache_dir)
    except Exception:
        verlauf = None
    for eintrag in verlauf or []:
        addr = eintrag.get("address")
        if addr:
            adressen.append(addr)
    if not adressen:
        return set()
    return set(addresses_to_script_pubkeys(adressen).keys())


#: TxID → Blockhöhe für P2P-Block-Fallback (z. B. aus UTXO-Scan).
_TX_HEIGHT_HINTS: ContextVar[dict[str, int] | None] = ContextVar(
    "xpq_tx_height_hints", default=None,
)


def note_tx_height(txid: str, height: int | None) -> None:
    """Merkt eine bekannte Bestätigungshöhe für den nächsten ``get_tx``."""
    if height is None:
        return
    try:
        h = int(height)
    except (TypeError, ValueError):
        return
    if h <= 0:
        return
    key = (txid or "").strip().lower()
    if len(key) != 64:
        return
    cur = _TX_HEIGHT_HINTS.get()
    if cur is None:
        cur = {}
        _TX_HEIGHT_HINTS.set(cur)
    cur[key] = h


def tx_height_hint(txid: str) -> int | None:
    cur = _TX_HEIGHT_HINTS.get()
    if not cur:
        return None
    return cur.get((txid or "").strip().lower())


def clear_tx_height_hints() -> None:
    """Leert den Höhen-Hinweis (Tests / neuer Lauf)."""
    _TX_HEIGHT_HINTS.set({})


def _embit_tx_to_dict(
    tx,
    *,
    height: int | None = None,
    block_time: int | None = None,
) -> dict[str, Any]:
    null = b"\x00" * 32
    vins: list[dict[str, Any]] = []
    for vin in tx.vin:
        if bytes(vin.txid) == null:
            vins.append({"is_coinbase": True})
        else:
            vins.append({"txid": bytes(vin.txid).hex(), "vout": int(vin.vout)})
    vouts: list[dict[str, Any]] = []
    for n, vout in enumerate(tx.vout):
        try:
            addr = vout.script_pubkey.address()
        except Exception:
            addr = None
        vouts.append({
            "n": n,
            "value": vout.value / 1e8,
            "scriptPubKey": {
                "hex": bytes(vout.script_pubkey.data).hex(),
                "address": addr,
            },
        })
    out: dict[str, Any] = {
        "txid": tx.txid().hex(),
        "vin": vins,
        "vout": vouts,
    }
    if height and height > 0:
        status: dict[str, Any] = {
            "confirmed": True,
            "block_height": int(height),
        }
        if block_time:
            status["block_time"] = int(block_time)
        out["status"] = status
    return out


def fetch_tx_p2p(client: Bip158Client, txid: str) -> dict[str, Any]:
    """Reine ``getdata``-TX — scheitert bei historischen Tx oft mit notfound."""
    from core.p2p import hex_to_hash
    from embit.transaction import Transaction

    peer = client.scanner._ensure_peer()
    raw = peer.fetch_tx(hex_to_hash(txid))
    return _embit_tx_to_dict(Transaction.parse(raw))


def fetch_tx_from_block_p2p(
    client: Bip158Client,
    txid: str,
    height: int,
    *,
    on_log=None,
) -> dict[str, Any]:
    """
    Lädt den Block an *height* und extrahiert die Tx.

    Peers ohne Tx-Index liefern historische Tx nicht per ``getdata``, wohl
    aber den ganzen Block (wie beim BIP-158-Scan).
    """
    from core.p2p import (
        SEGWIT_HEIGHT,
        HeaderChain,
        hash_to_hex,
        hole_header,
    )
    from embit.transaction import Transaction

    key = (txid or "").strip().lower()
    hoehe = int(height)
    if hoehe <= 0:
        raise ValueError(f"ungültige Blockhöhe: {height}")

    scanner = client.scanner
    start = client.start_height or SEGWIT_HEIGHT
    chain = HeaderChain(scanner._header_path, start_height=start)
    if chain.tip_height() < hoehe:
        peer = scanner._ensure_peer()
        if on_log:
            on_log(f"Header bis Block {hoehe:,} nachziehen…".replace(",", "."))
        chain = hole_header(
            scanner._header_path, start, peer, on_log=on_log or scanner._log,
        )
    if chain.tip_height() < hoehe:
        raise ConnectionError(
            f"Header-Cache endet bei {chain.tip_height()}, braucht {hoehe}"
        )
    block_hash = chain.hash_at(hoehe)
    if on_log:
        on_log(
            f"hole Block {hoehe:,} ({hash_to_hex(block_hash)[:12]}…) "
            f"für Tx {key[:16]}…".replace(",", ".")
        )
    peer = scanner._ensure_peer()
    raw = peer.fetch_block(block_hash)
    header, txs = parse_raw_block(raw)
    block_time = _header_unixzeit(header)
    gefunden: dict[str, Any] | None = None
    for tx in txs:
        d = _embit_tx_to_dict(tx, height=hoehe, block_time=block_time)
        if d["txid"].lower() == key:
            gefunden = d
            break
    if gefunden is None:
        raise ConnectionError(
            f"Tx {key[:16]}… nicht in Block {hoehe} "
            f"(Peer lieferte {len(txs)} Transaktionen)"
        )
    return gefunden


def fetch_tx_p2p_mit_fallback(
    client: Bip158Client,
    txid: str,
    *,
    core_client=None,
    local_core=None,
    archival_core=None,
    local_pruneheight: int | None = None,
    height: int | None = None,
    on_log=None,
) -> dict[str, Any]:
    """
    Tx-Lookup ohne Electrs: Core-RPC (lokal/Lookup) → P2P getdata → Block.

    *local_core* / *archival_core*: Rollen-Split (pruned lokal bis pruneheight,
    sonst Lookup z. B. Start9). *core_client* bleibt als Einzel-Fallback.
    *height* oder ``note_tx_height`` für Block-Fallback.
    """
    key = (txid or "").strip().lower()
    hoehe = height if (height and int(height) > 0) else tx_height_hint(key)
    fehler: list[str] = []

    hat_rollen = local_core is not None or archival_core is not None
    if hat_rollen:
        try:
            from core.bitcoind_rpc import fetch_tx_core_mit_rollen

            tx = fetch_tx_core_mit_rollen(
                key,
                local=local_core,
                archival=archival_core or core_client,
                local_pruneheight=local_pruneheight,
                height=hoehe,
                on_log=on_log,
            )
            st = tx.get("status") or {}
            if st.get("block_height"):
                note_tx_height(key, st["block_height"])
            return tx
        except Exception as exc:
            fehler.append(f"Core: {exc}")
    elif core_client is not None:
        try:
            from core.bitcoind_rpc import fetch_tx_core

            if on_log:
                on_log(f"Tx {key[:16]}… über Core-RPC…")
            tx = fetch_tx_core(core_client, key)
            st = tx.get("status") or {}
            if st.get("block_height"):
                note_tx_height(key, st["block_height"])
            return tx
        except Exception as exc:
            fehler.append(f"Core: {exc}")

    try:
        return fetch_tx_p2p(client, key)
    except Exception as exc:
        fehler.append(f"P2P-Tx: {exc}")

    if hoehe:
        return fetch_tx_from_block_p2p(
            client, key, int(hoehe), on_log=on_log,
        )

    detail = "; ".join(fehler) if fehler else "unbekannt"
    raise ConnectionError(
        "Transaktion nicht auflösbar ohne Electrs: weder Core-RPC "
        f"(txindex?) noch P2P-getdata, und keine Blockhöhe bekannt ({detail}). "
        "UTXO-Scan-Höhe fehlt, oder Core mit -txindex=1 / Electrs nutzen."
    )


def fetch_address_utxos_bip158(client: Bip158Client, address: str) -> list[dict]:
    return fetch_addresses_utxos_bip158(client, [address])


def fetch_addresses_utxos_bip158(
    client: Bip158Client,
    addresses: Iterable[str],
    *,
    progress_label: str | None = None,
    start_height: int | None = None,
) -> list[dict]:
    _ = progress_label
    address_list = sorted(set(addresses))
    if not address_list:
        return []
    scan_from = client.start_height if start_height is None else start_height
    from display import Bip158ProgressLine, melde_zwischenstand

    tip = None
    try:
        tip = client.scanner.get_block_count()
    except Exception:
        pass
    progress_line = Bip158ProgressLine(verbose=client.verbose, tip_height=tip)

    def on_progress(event: ScanProgress) -> None:
        progress_line.update(
            event.height, event.utxo_id,
            checked=event.blocks_checked, total=event.total_blocks,
        )

    client.scanner._progress_callback = on_progress
    try:
        result = client.scanner.scan_addresses(
            address_list, start_height=scan_from,
        )
    finally:
        progress_line.finish()
    known = set(address_list)
    utxos = []
    for output in result.outputs:
        if output.address in known:
            utxos.append(_matched_output_to_utxo(output))
    melde_zwischenstand(f"BIP-158: {len(utxos)} unspent UTXO(s)")
    return utxos


#: Blöcke vor dem letzten Tip erneut scannen (Reorg-Puffer).
BIP158_REORG_BUFFER = 6
_LAST_SCAN_TIPS: dict[str, int] = {}


def take_last_scan_tip(xpub: str) -> int | None:
    """Einmaliger Tip-Abruf nach fetch_wallet_utxos_bip158."""
    return _LAST_SCAN_TIPS.pop(xpub, None)


def _seed_aus_cache(
    xpub: str,
    cache_dir: Path | None,
    *,
    ab_hoehe: int,
) -> tuple[dict[str, MatchedOutput], dict[str, dict[str, Any]]]:
    """UTXOs und Verlauf unter *ab_hoehe* als Startbestand für den Inkremental-Scan."""
    if cache_dir is None:
        return {}, {}
    import main as main_mod

    seed_out: dict[str, MatchedOutput] = {}
    entry = main_mod.load_xpub_cache_entry(xpub, cache_dir)
    for u in (entry or {}).get("utxos") or []:
        hoehe = int((u.get("status") or {}).get("block_height") or 0)
        if hoehe >= ab_hoehe:
            continue
        txid = str(u.get("txid") or "").lower()
        vout = int(u.get("vout") or 0)
        key = f"{txid}:{vout}"
        seed_out[key] = MatchedOutput(
            txid=txid,
            vout=vout,
            value_sats=int(u.get("value") or 0),
            address=u.get("address"),
            script_pubkey_hex="",
            block_height=hoehe,
            block_hash="",
        )
    seed_verlauf: dict[str, dict[str, Any]] = {}
    for e in main_mod.load_xpub_verlauf_cache(xpub, cache_dir) or []:
        txid = str(e.get("txid") or "").lower()
        vout = int(e.get("vout") or 0)
        seed_verlauf[f"{txid}:{vout}"] = e
    return seed_out, seed_verlauf


def fetch_wallet_utxos_bip158(
    client: Bip158Client,
    xpubs: list[str],
    *,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    max_addresses_by_xpub: dict[str, int] | None = None,
    on_utxos_update=None,
) -> list[dict]:
    from display import Bip158ProgressLine, melde_zwischenstand
    import main as main_mod

    utxos: list[dict] = []
    for xpub in xpubs:
        konfiguriert = (
            max_addresses_by_xpub.get(xpub, max_addresses)
            if max_addresses_by_xpub
            else max_addresses
        )
        xpub_max = max(int(konfiguriert), int(max_addresses))
        used = _used_scripts_aus_cache(xpub, client.cache_dir)
        from core.p2p import SEGWIT_HEIGHT

        # client.start_height = UI/CLI/Env (kann jünger als SegWit sein).
        start = int(client.start_height or 0)
        seed_out: dict[str, MatchedOutput] = {}
        seed_verlauf: dict[str, dict[str, Any]] = {}
        start_grund = "konfiguriert"
        unvollstaendig = False
        if client.cache_dir is not None:
            entry = main_mod.load_xpub_cache_entry(xpub, client.cache_dir)
            roh = (entry or {}).get("raw") or {}
            fertig = main_mod.bip158_fullscan_ist_fertig(roh)
            unvollstaendig = bool(
                (roh.get("utxos") or roh.get("bip158_fullscan_ok") is False)
                and not fertig
            )
            prev_tip = roh.get("scan_tip_height") if fertig else None
            if prev_tip is not None:
                try:
                    prev_tip_i = int(prev_tip)
                except (TypeError, ValueError):
                    prev_tip_i = 0
                if prev_tip_i > 0:
                    tip_start = max(0, prev_tip_i - BIP158_REORG_BUFFER + 1)
                    start = max(start, tip_start) if start > 0 else tip_start
                    seed_out, seed_verlauf = _seed_aus_cache(
                        xpub, client.cache_dir, ab_hoehe=start,
                    )
                    start_grund = "tip"
            if start_grund != "tip":
                # First-seen − Reorg-Puffer. SegWit-Default weicht dem Alter;
                # explizit jüngeres UI/CLI (Höhe > First-seen) bleibt.
                alter_start = main_mod.bip158_start_aus_first_seen(
                    xpub,
                    client.cache_dir,
                    floor=None,
                    puffer=BIP158_REORG_BUFFER,
                )
                if alter_start is not None:
                    if start <= 0 or start <= SEGWIT_HEIGHT:
                        start = alter_start
                    elif start < alter_start:
                        # UI älter als First-seen → First-seen (weniger Blindflug)
                        start = alter_start
                    # else: start > alter_start → User will ab jüngerer Höhe
                    start_grund = "alter"
        if start <= 0:
            start = SEGWIT_HEIGHT
            start_grund = "segwit-default"
        if seed_out or start_grund == "tip":
            keys_txt = f"{len(used)} used Keys, inkrementell"
        elif start_grund == "alter":
            keys_txt = "ab Wallet-Beginn"
        elif used:
            keys_txt = f"{len(used)} used Keys"
        elif unvollstaendig:
            keys_txt = "Erstscan (letzter Lauf unvollständig — Turbo)"
        else:
            keys_txt = "Erstscan"
        anfang = (
            f"P2P-BIP-158 {xpub[:20]}… ab Höhe {start:,} ({keys_txt})"
            .replace(",", ".")
        )
        print(f"\n{anfang}", flush=True)
        melde_zwischenstand(anfang)
        progress_line = Bip158ProgressLine(verbose=client.verbose)

        def on_progress(event: ScanProgress) -> None:
            progress_line.update(
                event.height, event.utxo_id,
                checked=event.blocks_checked, total=event.total_blocks,
            )

        client.scanner._progress_callback = on_progress

        def _bip158_zwischenstand(stand: list[dict], *, _xpub=xpub) -> None:
            if on_utxos_update:
                # Ein XPUB nach dem anderen — Zwischenstand ist der laufende
                # XPUB plus bereits fertige XPUBs dieses Aufrufs.
                on_utxos_update(utxos + stand)

        try:
            result = client.scanner.scan_from_xpub(
                xpub,
                max_index=max(xpub_max // 2, 1),
                start_height=start,
                used_scripts=used,
                seed_outputs=seed_out or None,
                seed_verlauf=seed_verlauf or None,
                on_utxos_update=_bip158_zwischenstand if on_utxos_update else None,
            )
        finally:
            progress_line.finish()
        _LAST_SCAN_TIPS[xpub] = int(result.stop_height)
        for output in result.outputs:
            utxos.append(_matched_output_to_utxo(output))
        if on_utxos_update:
            on_utxos_update(list(utxos))
        if client.cache_dir is not None and result.verlauf:
            main_mod.merke_bip158_verlauf(xpub, result.verlauf, client.cache_dir)
            melde_zwischenstand(
                f"BIP-158 Verlauf: {len(result.verlauf)} Ein- und Ausgänge"
            )
    fertig = f"BIP-158: {len(utxos)} unspent UTXO(s) nach Filter-Scan"
    print(f"\n{fertig}", flush=True)
    melde_zwischenstand(fertig)
    return utxos


def _run_chiabip158_self_test() -> None:
    if PyBIP158 is None:
        print("chiabip158 not installed — skip self-test")
        return
    script_a = bytes.fromhex("0014" + "ab" * 20)
    script_b = bytes.fromhex("0014" + "cd" * 20)
    built = PyBIP158([bytearray(script_a), bytearray(script_b)])
    encoded = bytes(built.filter_bytes) if hasattr(built, "filter_bytes") else bytes()
    if not encoded:
        print("chiabip158 self-test skipped (kein filter_bytes)")
        return
    matcher = PyBIP158(list(encoded))
    print("chiabip158 self-test OK (synthetic filter)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BIP-158 Compact-Filter-Scanner (Bitcoin-P2P)"
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        _run_chiabip158_self_test()
        return 0
    print("P2P-Scan: py main.py --bip158", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


