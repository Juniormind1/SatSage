"""BIP-158 Wallet-API: Skript-Ableitung, Tx-Fetch, UTXO-Scan.

Slice 5 Schritt 8. Der Scanner bleibt in ``core.bip158_scan`` und holt
Ableitung bzw. die Client-Factory per Late-Import (kein Lade-Zyklus).
"""
from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from embit import script
from embit.bip32 import HDKey
from embit.script import address_to_scriptpubkey

from core.bip158_filter import MatchedOutput, ScanProgress
from core.bip158_scan import (
    DEFAULT_GAP_LIMIT,
    DEFAULT_MAX_ADDRESSES,
    DEFAULT_MAX_INDEX,
    BIP158Scanner,
    Bip158Client,
    _header_unixzeit,
    parse_raw_block,
)


# XPUB derivation (self-contained, embit only)
# ---------------------------------------------------------------------------


def _encoders_for_xpub(xpub: str, script_type: str | None = None) -> list[Callable]:
    """
    Delegiert an ``core.derivation._encoders_for_xpub``, damit der konfigurierte
    Skripttyp auch beim BIP-158-Scan gilt.

    Der Fallback hält das Modul eigenständig lauffähig — dann allerdings ohne
    Skripttyp-Konfiguration, weshalb 'xpub' dort alle Typen probiert.
    """
    try:
        from core.derivation import _encoders_for_xpub as _impl

        return _impl(xpub, script_type)
    except Exception:
        pass

    pubkey = lambda pk: script.p2pkh(pk)
    nested = lambda pk: script.p2sh(script.p2wpkh(pk))
    segwit = lambda pk: script.p2wpkh(pk)
    taproot = lambda pk: script.p2tr(pk)
    mapping = {
        "ypub": [nested],
        "zpub": [segwit],
        "upub": [nested],
        "vpub": [segwit],
    }
    return mapping.get(xpub[:4].lower(), [pubkey, nested, segwit, taproot])



def derive_script_pubkeys_from_xpub(
    xpub: str,
    *,
    max_index: int = DEFAULT_MAX_INDEX,
    include_change: bool = True,
) -> dict[bytes, str | None]:
    """
    Derive receive (+ optional change) scriptPubKeys from an XPUB
    **or Output-Deskriptor** (Multisig ``wsh(sortedmulti…)`` u. a.).

    Returns ``script_pubkey_bytes -> address`` (address may be None if encoding fails).
    """
    # Multisig/Deskriptor: embit HDKey versteht den String nicht.
    try:
        from core.derivation import derive_addresses, ist_deskriptor

        if ist_deskriptor(xpub):
            # max_index ≈ pro Chain; Deskriptor-Pfad teilt max_addresses auf Zweige.
            zweige = 2 if include_change else 1
            max_addr = max(2, int(max_index) * zweige)
            addrs = derive_addresses(
                xpub, max_addresses=max_addr, start_index=0,
            )
            result: dict[bytes, str | None] = {}
            for addr in addrs or []:
                if not addr:
                    continue
                try:
                    spk = bytes(address_to_scriptpubkey(addr).data)
                except Exception:
                    continue
                result[spk] = addr
            if not result:
                raise ValueError(
                    f"Deskriptor liefert keine Adressen: {xpub[:40]}…"
                )
            return result
    except ValueError:
        raise
    except Exception:
        pass

    try:
        hd = HDKey.from_string(xpub)
    except Exception as exc:
        raise ValueError(f"invalid xpub: {exc}") from exc

    result = {}
    chains = (0, 1) if include_change else (0,)
    for encoder in _encoders_for_xpub(xpub):
        for change in chains:
            for index in range(max_index):
                try:
                    child = hd.derive([change, index])
                    sc = encoder(child.key)
                    spk = bytes(sc.data)
                    try:
                        addr = sc.address()
                    except Exception:
                        addr = None
                    result[spk] = addr
                except Exception:
                    break
    return result



def addresses_to_script_pubkeys(addresses: Sequence[str]) -> dict[bytes, str]:
    """Convert base58/bech32 addresses to scriptPubKey bytes."""
    mapping: dict[bytes, str] = {}
    for address in addresses:
        if not address:
            continue
        try:
            spk = bytes(address_to_scriptpubkey(address).data)
        except Exception:
            continue
        mapping[spk] = address
    return mapping



def gap_scripts_anfang(
    xpub: str,
    *,
    gap_limit: int = DEFAULT_GAP_LIMIT,
    include_change: bool = True,
) -> set[bytes]:
    """Erste gap_limit Indizes (Receive + optional Change) — Historie-Seed."""
    return set(
        derive_script_pubkeys_from_xpub(
            xpub, max_index=max(1, int(gap_limit)), include_change=include_change,
        ).keys()
    )



def scripts_mit_gap_um_treffer(
    xpub: str,
    hit_scripts: set[bytes],
    *,
    gap_limit: int = DEFAULT_GAP_LIMIT,
    max_index: int = DEFAULT_MAX_INDEX,
    include_change: bool = True,
) -> set[bytes]:
    """
    Getroffene Scripts plus lokale Gap (nächste gap_limit Indizes je Chain).

    Pro Receive/Change-Zweig: höchster getroffener Index, dann +gap_limit.
    """
    gap_limit = max(1, int(gap_limit))
    max_index = max(gap_limit, int(max_index))
    hits = set(hit_scripts or ())
    # Deskriptor: keine Index-Matrix — Hits + Anfangs-Gap.
    try:
        from core.derivation import ist_deskriptor

        if ist_deskriptor(xpub):
            out = set(hits)
            out |= gap_scripts_anfang(
                xpub, gap_limit=gap_limit, include_change=include_change,
            )
            return out
    except Exception:
        pass

    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        out = set(hits)
        out |= gap_scripts_anfang(
            xpub, gap_limit=gap_limit, include_change=include_change,
        )
        return out

    chains = (0, 1) if include_change else (0,)
    # script → (change, index) für alle Encoder (wie derive).
    index_von: dict[bytes, tuple[int, int]] = {}
    for encoder in _encoders_for_xpub(xpub):
        for change in chains:
            for index in range(max_index):
                try:
                    child = hd.derive([change, index])
                    spk = bytes(encoder(child.key).data)
                except Exception:
                    break
                index_von.setdefault(spk, (change, index))

    max_je_chain: dict[int, int] = {}
    out = set(hits)
    for spk in hits:
        wo = index_von.get(spk)
        if wo is None:
            continue
        change, index = wo
        prev = max_je_chain.get(change, -1)
        if index > prev:
            max_je_chain[change] = index

    for change in chains:
        basis = max_je_chain.get(change, -1)
        # Kein Hit auf dem Zweig: Gap ab 0; sonst ab höchstem Hit.
        start_i = 0 if basis < 0 else basis
        ende = min(max_index, start_i + gap_limit + (0 if basis < 0 else 1))
        for encoder in _encoders_for_xpub(xpub):
            for index in range(start_i, ende):
                try:
                    child = hd.derive([change, index])
                    out.add(bytes(encoder(child.key).data))
                except Exception:
                    break
    if not out:
        out = gap_scripts_anfang(
            xpub, gap_limit=gap_limit, include_change=include_change,
        )
    return out



def create_bip158_client_from_env(
    env: dict[str, str],
    *,
    start_height: int = 0,
    progress_callback: ProgressCallback | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
    immutable_dir: Path | None = None,
) -> Bip158Client:
    """P2P-Client: Clearnet zuerst, bei Fehlschlag Tor wie beim eigenen Node."""
    from core.p2p import SEGWIT_HEIGHT, p2p_headers_path, p2p_peers_from_env
    from core.paths import app_dir

    peers = p2p_peers_from_env(env)
    if immutable_dir is not None:
        header_path = p2p_headers_path(immutable_dir)
    elif cache_dir is not None:
        header_path = Path(cache_dir).parent / "immutable_cache" / "p2p_headers.bin"
    else:
        header_path = app_dir() / "immutable_cache" / "p2p_headers.bin"
    scanner = BIP158Scanner(
        peers=peers,
        header_path=header_path,
        progress_callback=progress_callback,
        env=env,
    )
    hoehe = start_height if start_height else SEGWIT_HEIGHT
    return Bip158Client(
        scanner=scanner, start_height=hoehe, verbose=verbose, cache_dir=cache_dir,
    )



def _matched_output_to_utxo(output: MatchedOutput) -> dict[str, Any]:
    return {
        "txid": output.txid,
        "vout": output.vout,
        "value": output.value_sats,
        "address": output.address,
        "status": {
            "confirmed": output.block_height > 0,
            "block_height": output.block_height,
        },
    }



def _used_scripts_aus_cache(xpub: str, cache_dir: Path | None) -> set[bytes]:
    """
    Used-Keys für TurboSync-Historie — nur nach abgeschlossenem Fullscan.

    Zwischenstände nach Abbruch (UTXOs ohne ``bip158_fullscan_ok``) liefern
    absichtlich leer, damit der nächste Lauf wieder Turbo-Erstscan macht.
    """
    if cache_dir is None:
        return set()
    try:
        from core.xpub_cache import (
            bip158_fullscan_ist_fertig,
            load_xpub_cache_entry,
            load_xpub_verlauf_cache,
        )

        eintrag = load_xpub_cache_entry(xpub, cache_dir)
    except Exception:
        return set()
    roh = (eintrag or {}).get("raw") or {}
    if not bip158_fullscan_ist_fertig(roh):
        return set()
    adressen: list[str] = []
    for utxo in roh.get("utxos") or []:
        addr = utxo.get("address")
        if addr:
            adressen.append(addr)
    adressen.extend(roh.get("scanned_addresses") or [])
    try:
        verlauf = load_xpub_verlauf_cache(xpub, cache_dir)
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
    from core.xpub_cache import load_xpub_cache_entry, load_xpub_verlauf_cache

    seed_out: dict[str, MatchedOutput] = {}
    entry = load_xpub_cache_entry(xpub, cache_dir)
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
    for e in load_xpub_verlauf_cache(xpub, cache_dir) or []:
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
    from core.xpub_cache import (
        bip158_fullscan_ist_fertig,
        bip158_start_aus_first_seen,
        load_xpub_cache_entry,
        merke_bip158_verlauf,
    )
    from display import Bip158ProgressLine, melde_zwischenstand

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
            entry = load_xpub_cache_entry(xpub, client.cache_dir)
            roh = (entry or {}).get("raw") or {}
            fertig = bip158_fullscan_ist_fertig(roh)
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
                alter_start = bip158_start_aus_first_seen(
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
            merke_bip158_verlauf(xpub, result.verlauf, client.cache_dir)
            melde_zwischenstand(
                f"BIP-158 Verlauf: {len(result.verlauf)} Ein- und Ausgänge"
            )
    fertig = f"BIP-158: {len(utxos)} unspent UTXO(s) nach Filter-Scan"
    print(f"\n{fertig}", flush=True)
    melde_zwischenstand(fertig)
    return utxos
