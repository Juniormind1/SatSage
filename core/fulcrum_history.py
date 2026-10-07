"""Fulcrum tx normalize/batch, address/wallet history, tip/date→height."""
from __future__ import annotations

import contextvars
from typing import Any

from embit.script import Script, address_to_scriptpubkey
from embit.transaction import Transaction

from core.derivation import script_address
from core.fulcrum_client import (
    TOR_RPC_BATCH_SIZE,
    FulcrumClient,
    address_to_scripthash,
)


_HEADER_TIME_CACHE: dict[int, int] = {}
_TX_HEIGHT_CACHE: dict[str, int | None] = {}


def _timestamp_from_block_header(header_hex: str) -> int:
    raw = bytes.fromhex(header_hex)
    if len(raw) < 80:
        raise ValueError("Block-Header zu kurz")
    return int.from_bytes(raw[68:72], "little")


def _vout_addresses(vout: dict) -> list[str]:
    spk = vout.get("scriptPubKey", {})
    addrs: list[str] = []
    if spk.get("address"):
        addrs.append(str(spk["address"]))
    addrs.extend(str(addr) for addr in spk.get("addresses", []) if addr)
    return addrs


def _vout_matches_address(vout: dict, address: str) -> bool:
    """
    True, wenn der Output an ``address`` zahlt.

    Electrs/Core auf Regtest liefern ``bcrt1…``, SatSage leitet ohne
    Chain-Schalter oft ``bc1…`` ab — gleicher scriptPubKey, anderer HRP.
    String-Vergleich allein würde Treffer still verwerfen; Hex-Vergleich
    der scriptPubKey fängt die Varianten (main/test/regtest) ab.
    """
    if address in _vout_addresses(vout):
        return True
    spk = vout.get("scriptPubKey") or {}
    hex_spk = str(spk.get("hex") or "").strip().lower()
    if not hex_spk:
        return False
    try:
        want = address_to_scriptpubkey(address).data.hex().lower()
    except Exception:
        return False
    return hex_spk == want


_HISTORY_CACHE: dict[str, list] = {}
#: Eigener Electrs im LAN antwortet in Millisekunden. Eine Zeile je Adresse
#: füllt den Log-Bereich, ohne dass jemand auf den Abruf wartet.
_HOEHE_LOG_BUENDEL = 32
_hoehe_abrufe_lan = 0


def _electrs_im_lan(client: FulcrumClient) -> bool:
    """Klares TCP zum eigenen Host. Onion (tor_proxy) und öffentlicher Pool: False."""
    if getattr(client, "tor_proxy", None):
        return False
    host = str(getattr(client, "host", "") or "").strip().lower()
    return bool(host) and not host.endswith(".onion")


def _melde_blockhoehe(txid: str, addr: str, *, lan: bool, n: int) -> None:
    """
    Onion und öffentliche Server: eine Zeile je Adresse (der Abruf dauert).

    Eigenes Electrs im LAN: die erste Adresse und dann jede
    ``_HOEHE_LOG_BUENDEL``-te. Dazwischen bleibt der Log-Bereich still.
    """
    from display import abbrev_display, melde_zwischenstand

    if lan and n > 1 and n % _HOEHE_LOG_BUENDEL != 0:
        return
    if lan and n > 1:
        melde_zwischenstand(
            f"↻ Herkunft: Blockhöhe für {n} Adressen beim eigenen Electrum-Server"
        )
        return
    melde_zwischenstand(
        f"↻ Herkunft: Blockhöhe von {txid[:12]}… über {abbrev_display(addr)}"
    )


def _history_fuer_adresse(client: FulcrumClient, addr: str, txid: str) -> list:
    """Historie je Adresse merken. Sonst holt jede neue Tx dieselbe Adresse neu."""
    global _hoehe_abrufe_lan

    sh = address_to_scripthash(addr)
    if sh in _HISTORY_CACHE:
        return _HISTORY_CACHE[sh]
    lan = _electrs_im_lan(client)
    if lan:
        _hoehe_abrufe_lan += 1
        n = _hoehe_abrufe_lan
    else:
        n = 1
    _melde_blockhoehe(txid, addr, lan=lan, n=n)
    history = client.request("blockchain.scripthash.get_history", [sh]) or []
    if not isinstance(history, list):
        history = []
    _HISTORY_CACHE[sh] = history
    return history


def _lookup_tx_height(client: FulcrumClient, txid: str, vouts: list[dict]) -> int | None:
    """
    Blockhöhe einer bekannten Tx.

    Eine Abfrage je Tx, nicht je Output. Fremde Mit-Outputs einer
    Sammeltransaktion bleiben unangetastet. Reihenfolge:

    1. ``blockchain.transaction.get_height`` (eine Zahl).
    2. Blockhash aus der ausführlichen Antwort, lokal in ``p2p_headers.bin``.
    3. Historie einer eigenen Output-Adresse, die der Scan schon kennt.
    4. Bisheriger Weg über die Output-Adressen, falls nichts davon greift.
    """
    cached = _TX_HEIGHT_CACHE.get(txid.lower())
    if cached is not None or txid.lower() in _TX_HEIGHT_CACHE:
        return cached

    height = _hoehe_per_txid(client, txid, vouts)
    _TX_HEIGHT_CACHE[txid.lower()] = height
    return height


def _hoehe_per_txid(
    client: FulcrumClient, txid: str, vouts: list[dict],
) -> int | None:
    direkt = _hoehe_von_get_height(client, txid)
    if direkt is not None:
        return direkt
    blockhash, blocktime = _block_der_tx(client, txid)
    if blockhash:
        aus_datei = _hoehe_aus_headerdatei(blockhash)
        if aus_datei is not None:
            return aus_datei
        # Hash bekannt, Datei hinkt hinterher: nur das Reststück über dem
        # lokalen Tip. Die Zeit bleibt dabei ungenutzt — Miner-Zeiten
        # liegen um wenige Blöcke daneben und taugen nicht als gespeicherte
        # Höhe.
        rest = _hoehe_ueber_lokalem_tip(client, blockhash)
        if rest is not None:
            return rest
    elif blocktime:
        # Zeit ohne Hash: lokale Obergrenze, damit die Adress-Historie
        # nicht bei Genesis anfängt. Die gespeicherte Höhe kommt weiter
        # aus der Historie einer eigenen Adresse.
        pass
    eigene = _eigene_output_adressen(vouts)
    if eigene:
        aus_eigener = _hoehe_aus_historie(client, txid, eigene)
        if aus_eigener is not None:
            return aus_eigener
    if not eigene:
        return _hoehe_aus_historie(client, txid, _vout_addresses_flach(vouts))
    return None


def _hoehe_von_get_height(client: FulcrumClient, txid: str) -> int | None:
    """Eine Zahl vom Server. Unbekannte Methode: still None, kein Fallback-Log."""
    from core.fulcrum_client import _is_unknown_method_error

    try:
        roh = client.request("blockchain.transaction.get_height", [txid])
    except Exception as exc:
        if _is_unknown_method_error(exc, "blockchain.transaction.get_height"):
            return None
        return None
    try:
        return int(roh)
    except (TypeError, ValueError):
        return None


def _block_der_tx(client: FulcrumClient, txid: str) -> tuple[str | None, int | None]:
    """
    Blockhash und Blockzeit aus der ausführlichen Antwort.

    Das JSON wird nicht behalten. Server ohne verbose liefern den bekannten
    Fehler; alles andere fällt auf die Adress-Historie zurück.
    """
    try:
        tx = client.request("blockchain.transaction.get", [txid, True])
    except Exception as exc:
        if _verbose_tx_unsupported(exc):
            return None, None
        return None, None
    if not isinstance(tx, dict):
        return None, None
    blockhash = str(tx.get("blockhash") or "").strip().lower()
    if len(blockhash) != 64:
        blockhash = None
    zeit = tx.get("blocktime") or tx.get("time")
    try:
        blocktime = int(zeit) if zeit else None
    except (TypeError, ValueError):
        blocktime = None
    return blockhash, blocktime


def _hoehe_ueber_lokalem_tip(client: FulcrumClient, blockhash: str) -> int | None:
    """Höhe eines Blocks, der über dem Stand von ``p2p_headers.bin`` liegt."""
    try:
        from core.p2p import header_hash, hex_to_hash
        from core.xpub_cache import _p2p_header_chain
    except Exception:
        return None
    chain = _p2p_header_chain(None)
    if chain is None:
        return None
    try:
        ziel = hex_to_hash(blockhash)
        tip = int(chain.tip_height())
    except (TypeError, ValueError):
        return None
    # Ein paar Header über dem lokalen Tip. Der Peer-Nachzug pflegt die
    # Datei; hier reicht das kurze Fenster, das der Tip-Job noch nicht hat.
    for schritt in range(1, 9):
        header = _fetch_block_header_hex(client, tip + schritt)
        if not header:
            return None
        try:
            roh = bytes.fromhex(header)
        except ValueError:
            return None
        if len(roh) < 80:
            return None
        if header_hash(roh[:80]) == ziel:
            return tip + schritt
    return None


def _hoehe_aus_headerdatei(blockhash: str) -> int | None:
    try:
        from core.xpub_cache import hoehe_fuer_blockhash

        return hoehe_fuer_blockhash(blockhash)
    except Exception:
        return None


# Eigene Adressen des laufenden Herkunftslaufs. Nur O(1)-Lookup, keine
# XPUB-Ableitung — eine große Transaktion darf hier nicht alle Wallets
# durchrechnen. Der Trace setzt das Set; ohne Trace bleibt es leer und
# der Fallback fragt die Output-Adressen wie bisher.
_EIGENE_ADRESSEN: contextvars.ContextVar[frozenset[str] | None] = (
    contextvars.ContextVar("satsage_eigene_adressen", default=None)
)


def setze_eigene_adressen(adressen) -> None:
    """Bekannte Wallet-Adressen für die Höhen-Suche dieses Laufs."""
    if not adressen:
        _EIGENE_ADRESSEN.set(None)
        return
    _EIGENE_ADRESSEN.set(frozenset(str(a) for a in adressen if a))


def _eigene_output_adressen(vouts: list[dict]) -> list[str]:
    """Output-Adressen, die der Scan schon einem Wallet zugeordnet hat."""
    bekannt = _EIGENE_ADRESSEN.get()
    if not bekannt:
        return []
    eigene: list[str] = []
    gesehen: set[str] = set()
    for addr in _vout_addresses_flach(vouts):
        if addr in gesehen or addr not in bekannt:
            continue
        gesehen.add(addr)
        eigene.append(addr)
    return eigene


def _vout_addresses_flach(vouts: list[dict]) -> list[str]:
    adressen: list[str] = []
    gesehen: set[str] = set()
    for vout in vouts or []:
        for addr in _vout_addresses(vout):
            if addr in gesehen:
                continue
            gesehen.add(addr)
            adressen.append(addr)
    return adressen


def _hoehe_aus_historie(
    client: FulcrumClient, txid: str, adressen: list[str],
) -> int | None:
    """Höhe aus der Historie der genannten Adressen. Erste Treffer-Adresse reicht."""
    txid_l = txid.lower()
    for addr in adressen:
        try:
            history = _history_fuer_adresse(client, addr, txid)
        except Exception:
            continue
        for entry in history:
            if str(entry.get("tx_hash", "")).lower() == txid_l:
                try:
                    return int(entry.get("height", 0))
                except (TypeError, ValueError):
                    return None
    return None


def _fetch_block_header_hex(client, height: int) -> str | None:
    for attempt in range(2):
        try:
            header = client.request("blockchain.block.header", [height])
            if isinstance(header, dict):
                header = header.get("header") or header.get("hex") or ""
            if isinstance(header, str) and header:
                return header
            return None
        except (ConnectionError, BrokenPipeError, OSError, RuntimeError):
            if attempt == 0 and hasattr(client, "close") and hasattr(client, "connect"):
                try:
                    client.close()
                    client.connect()
                except Exception:
                    pass
                continue
            return None
    return None


def _hoehe_zur_zeit_lokal(ziel: int) -> int | None:
    try:
        from core.xpub_cache import hoehe_zur_blockzeit

        return hoehe_zur_blockzeit(ziel)
    except Exception:
        return None


def _lokaler_header_tip() -> int | None:
    try:
        from core.p2p import header_datei_tip, p2p_headers_path

        return header_datei_tip(p2p_headers_path())
    except Exception:
        return None


def _block_time_for_height(client: FulcrumClient, height: int) -> int | None:
    if height <= 0:
        return None
    if height in _HEADER_TIME_CACHE:
        return _HEADER_TIME_CACHE[height]
    try:
        from core.xpub_cache import IMMUTABLE_CACHE_DIR, load_cached_block_time, save_cached_block_time

        disk_time = load_cached_block_time(height, IMMUTABLE_CACHE_DIR)
        if disk_time is not None:
            _HEADER_TIME_CACHE[height] = disk_time
            return disk_time
    except Exception:
        pass
    header = _fetch_block_header_hex(client, height)
    if not header:
        return None
    try:
        blocktime = _timestamp_from_block_header(header)
    except ValueError:
        return None
    _HEADER_TIME_CACHE[height] = blocktime
    try:
        from core.xpub_cache import IMMUTABLE_CACHE_DIR, save_cached_block_time

        save_cached_block_time(height, blocktime, IMMUTABLE_CACHE_DIR, "fulcrum")
    except Exception:
        pass
    return blocktime


def _enrich_tx_block_info(client: FulcrumClient, tx: dict) -> dict:
    """Ergänzt Hex-geparste Txs um Blockhöhe und Blockzeit."""
    if _tx_block_time_from_dict(tx) is not None:
        return tx

    txid = str(tx.get("txid", ""))
    if not txid:
        return tx

    height = _lookup_tx_height(client, txid, tx.get("vout", []))
    if height is None:
        return tx

    tx["blockheight"] = height
    if height <= 0:
        # Noch nicht im Block. Frühestens im aktuellen Tip, eher später.
        # Höhe 0 wäre eine falsche Hypothese und bliebe im Cache hängen.
        status = _status_fuer_hoehe(client, 0)
        tx["confirmations"] = 0
        tx["blockheight"] = status.get("block_height")
        tx["status"] = status
        return tx

    blocktime = _block_time_for_height(client, height)
    if blocktime is None:
        # Höhe ohne Zeit nicht festschreiben. Aufrufer speichert nur Vollständiges.
        return tx
    tx["blocktime"] = blocktime
    tx["confirmations"] = max(int(tx.get("confirmations", 0)), 1)
    tx["status"] = {
        "confirmed": True,
        "block_height": height,
        "block_time": blocktime,
    }
    return tx


def _tx_block_time_from_dict(tx: dict) -> int | None:
    status = tx.get("status", {})
    if status.get("block_time"):
        return int(status["block_time"])
    if tx.get("blocktime"):
        return int(tx["blocktime"])
    if tx.get("time"):
        return int(tx["time"])
    return None

_VERBOSE_TX_UNSUPPORTED = "verbose transactions are currently unsupported"


def _verbose_tx_unsupported(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "verbose" in msg and "unsupported" in msg


def _script_pubkey_to_dict(script: Script) -> dict:
    spk: dict[str, object] = {"hex": script.data.hex()}
    script_type = script.script_type()
    if script_type:
        spk["type"] = script_type
    try:
        # Im konfigurierten Netz (regtest: bcrt1…), sonst erkennt der Trace
        # eigene Vorgänger-Adressen nicht und bricht nach einer Ebene ab.
        spk["address"] = script_address(script)
    except ValueError:
        pass
    return spk


def _vin_to_dict(inp) -> dict:
    if inp.txid == b"\x00" * 32:
        coinbase = inp.script_sig.data.hex() if inp.script_sig else ""
        return {
            "is_coinbase": True,
            "coinbase": coinbase or "00",
            "sequence": inp.sequence,
        }
    # embit speichert die Vorgänger-ID schon in Anzeige-Reihenfolge
    # (read_from dreht die Wire-Bytes). Ein zweites Umdrehen fragt
    # Electrs nach einer Tx, die es nicht gibt — gleicher Wortlaut
    # wie Core „No such mempool…“.
    return {
        "txid": bytes(inp.txid).hex(),
        "vout": inp.vout,
        "sequence": inp.sequence,
    }


def _parse_tx_hex(raw_hex: str, expected_txid: str | None = None) -> dict:
    """Parst Roh-Hex lokal (Fallback wenn verbose am Server fehlt)."""
    raw = raw_hex.strip()
    if not raw:
        raise ValueError("leere Transaktion")

    tx = Transaction.from_string(raw)
    txid = tx.txid().hex()
    if expected_txid and txid.lower() != expected_txid.lower():
        raise ValueError(
            f"Txid stimmt nicht: erwartet {expected_txid}, erhalten {txid}"
        )

    return {
        "txid": txid,
        "version": tx.version,
        "locktime": tx.locktime,
        "vin": [_vin_to_dict(inp) for inp in tx.vin],
        "vout": [
            {
                "n": index,
                "value": out.value / 1e8,
                "scriptPubKey": _script_pubkey_to_dict(out.script_pubkey),
            }
            for index, out in enumerate(tx.vout)
        ],
        "confirmations": 0,
        "hex": raw,
    }

def _normalize_electrum_tx(tx: dict) -> dict:
    """Bringt Electrum-Tx in ein für analyze.py nutzbares Format."""
    if not tx:
        return tx

    for vin in tx.get("vin", []):
        if "coinbase" in vin and "is_coinbase" not in vin:
            vin["is_coinbase"] = True
        if "txid" not in vin and "tx_hash" in vin:
            vin["txid"] = vin["tx_hash"]

    confirmations = int(tx.get("confirmations", 0))
    confirmed = confirmations > 0
    block_time = tx.get("blocktime") or tx.get("time")
    if block_time and "status" not in tx:
        tx["status"] = {
            "confirmed": confirmed,
            "block_time": block_time,
        }

    return tx


def fetch_tx_fulcrum(
    client: FulcrumClient,
    txid: str,
    *,
    enrich_block_info: bool = True,
    roh: bool = True,
) -> dict:
    """Lädt eine Tx als Roh-Hex und parst sie lokal.

    Die verbose JSON-Form ist bei CoinJoin ein Vielfaches der Rohgröße
    und kommt über Fulcrum nicht zuverlässig zurück. Adressen und Beträge
    stehen im Script, die Blockzeit holt der Nachzug. *roh=False* bleibt
    nur für den alten verbose Weg, den kein Aufrufer mehr braucht.
    """
    from core.vervollstaendigen_log import schritt

    host = getattr(client, "host", "")
    software = getattr(client, "server_software", "") or "?"
    if not roh:
        schritt(f"rpc-anfrage {txid} verbose host={host} software={software}")
        try:
            tx = client.request("blockchain.transaction.get", [txid, True])
            if isinstance(tx, str):
                raise RuntimeError(_VERBOSE_TX_UNSUPPORTED)
            return _normalize_electrum_tx(tx)
        except RuntimeError as exc:
            if not _verbose_tx_unsupported(exc):
                raise
    schritt(f"rpc-anfrage {txid} roh host={host} software={software}")
    raw = client.request("blockchain.transaction.get", [txid, False])
    schritt(
        f"rpc-antwort {txid} art={type(raw).__name__} "
        f"bytes={len(raw) if isinstance(raw, str) else 0}"
    )
    if isinstance(raw, dict):
        # Ältere Tests und Server, die trotz verbose=false JSON liefern.
        return _normalize_electrum_tx(raw)
    if not isinstance(raw, str):
        raise RuntimeError("Unerwartete Antwort bei Roh-Transaktion")
    schritt(f"parse {txid}")
    tx = _normalize_electrum_tx(_parse_tx_hex(raw, expected_txid=txid))
    schritt(
        f"parsed {txid} vin={len(tx.get('vin') or [])} "
        f"vout={len(tx.get('vout') or [])}"
    )
    if enrich_block_info:
        schritt(f"blockzeit {txid}")
        tx = _enrich_tx_block_info(client, tx)
        schritt(f"blockzeit-fertig {txid}")
    return tx


def fetch_txs_fulcrum_batch(
    client: FulcrumClient,
    txids: list[str],
    *,
    on_progress=None,
) -> dict[str, dict]:
    """
    Mehrere Txs laden — bei Tor/Batch-fähigem Client per ``request_batch``.

    Chunks à ``TOR_RPC_BATCH_SIZE`` mit Zwischenstand (noch X Tx), damit
    lange Onion-Batches nicht stumm wirken. Rückgabe nur erfolgreiche Treffer.
    """
    ergebnis: dict[str, dict] = {}
    offen: list[str] = []
    gesehen: set[str] = set()
    for roh in txids:
        t = str(roh or "").strip().lower()
        if len(t) != 64 or t in gesehen:
            continue
        gesehen.add(t)
        offen.append(t)
    if not offen:
        return ergebnis

    batch_ok = bool(getattr(client, "tor_batch_sinnvoll", lambda _n: False)(2))
    total = len(offen)
    chunk_n = max(1, int(TOR_RPC_BATCH_SIZE)) if batch_ok else 1

    def _norm_eine(txid: str, roh_wert: Any) -> dict | None:
        try:
            if isinstance(roh_wert, str):
                return _normalize_electrum_tx(
                    _parse_tx_hex(roh_wert, expected_txid=txid)
                )
            if isinstance(roh_wert, dict):
                return _normalize_electrum_tx(roh_wert)
        except Exception:
            return None
        return None

    def _melde(text: str, *, sofort: bool = False) -> None:
        if not on_progress:
            return
        try:
            on_progress(text, sofort=sofort)
        except TypeError:
            on_progress(text)

    def _chunk_hex(chunk: list[str]) -> None:
        if not chunk:
            return
        if len(chunk) == 1 or not batch_ok:
            for t in chunk:
                try:
                    ergebnis[t] = fetch_tx_fulcrum(
                        client, t, enrich_block_info=False,
                    )
                except Exception:
                    pass
            return
        try:
            answers = client.request_batch([
                ("blockchain.transaction.get", [t, False]) for t in chunk
            ])
        except Exception:
            answers = None
        if not isinstance(answers, list) or len(answers) != len(chunk):
            for t in chunk:
                try:
                    ergebnis[t] = fetch_tx_fulcrum(
                        client, t, enrich_block_info=False,
                    )
                except Exception:
                    pass
            return
        for t, ant in zip(chunk, answers):
            tx = _norm_eine(t, ant)
            if tx is not None:
                ergebnis[t] = tx

    modus = "Batch" if batch_ok and total >= 2 else "einzeln"
    _melde(f"Tx-Abruf ({modus}): {total} Tx…", sofort=True)

    erledigt = 0
    for start in range(0, total, chunk_n):
        chunk = offen[start : start + chunk_n]
        rest = total - erledigt
        _melde(
            f"Tx-Abruf: noch {rest} Tx "
            f"(Chunk {start // chunk_n + 1}, je {len(chunk)})…",
            sofort=True,
        )
        _chunk_hex(chunk)
        erledigt += len(chunk)

    return ergebnis


def _tx_ist_coinjoin(tx: dict) -> bool:
    try:
        from core.exchange_spend import ist_coinjoin_tx

        return ist_coinjoin_tx(tx)
    except Exception:
        return False


def _fremde_outputs(tx: dict) -> list[dict]:
    """
    Outputs der ausgebenden Tx: Adresse und Satoshis.

    Eigenes Wechselgeld filtert die Anzeige später über den Wallet-Kontext.
    Hier bleibt jede Output-Adresse, damit der Verlauf die Tx nicht erneut
    laden muss.
    """
    from core.utxo_report import _extract_addresses, _extract_value_sats

    ziele: list[dict] = []
    for vout in tx.get("vout") or []:
        if not isinstance(vout, dict):
            continue
        addrs = [a for a in _extract_addresses(vout) if a]
        if not addrs:
            addrs = _vout_addresses(vout)
        if not addrs:
            continue
        try:
            sats = int(_extract_value_sats(vout))
        except (TypeError, ValueError):
            sats = _vout_value_sats(vout)
        if sats <= 0:
            continue
        # Eine Zeile je Output. Flach je Adresse würde ein Multisig den
        # Betrag doppelt zählen.
        ziele.append({
            "addresses": [str(a) for a in addrs],
            "sats": sats,
        })
    return ziele


def _vout_value_sats(vout: dict) -> int:
    value = vout.get("value", 0)
    if isinstance(value, float):
        return int(round(value * 1e8))
    return int(value)


def _walk_address_history(
    client: FulcrumClient,
    address: str,
    scripthash: str,
    *,
    on_step=None,
) -> tuple[dict[tuple[str, int], dict[str, int]], dict[tuple[str, int], str]]:
    """
    Geht die Historie einer Adresse durch.

    Liefert *(received, spent_by)*: alle je auf dieser Adresse empfangenen
    Outputs, und zu jedem verbrauchten die TxID plus fremde Zieladressen
    der ausgebenden Tx (für „davon … an Kraken“).

    Gemeinsame Grundlage für zwei Sichten — die unverbrauchte Teilmenge
    (UTXO-Fallback für Server ohne listunspent) und den vollständigen Verlauf.
    Beide aus einem Walk, damit sie sich nicht widersprechen können.

    *on_step(text)*: Zwischenstand (get_history / Tx i/n) für lange Tor-Läufe.
    """
    if on_step:
        try:
            on_step("get_history…")
        except Exception:
            pass
    history = client.request("blockchain.scripthash.get_history", [scripthash]) or []
    if not history:
        return {}, {}

    received: dict[tuple[str, int], dict[str, int]] = {}
    spent_by: dict[tuple[str, int], dict] = {}
    anzahl = len(history)

    for index, entry in enumerate(history, start=1):
        if on_step:
            try:
                on_step(f"Tx {index}/{anzahl}")
            except Exception:
                pass
        txid = str(entry["tx_hash"])
        height = int(entry.get("height", 0))
        tx = fetch_tx_fulcrum(client, txid)
        txid_key = txid.lower()

        for vout_idx, vout in enumerate(tx.get("vout", [])):
            if not _vout_matches_address(vout, address):
                continue
            received[(txid_key, vout_idx)] = {
                "value": _vout_value_sats(vout),
                "height": height,
            }

        for vin in tx.get("vin", []):
            if vin.get("is_coinbase"):
                continue
            prev_txid = str(vin.get("txid", "")).lower()
            if prev_txid:
                # Die Höhe der ausgebenden Tx gleich mitnehmen: Sie steht hier
                # ohnehin zur Verfügung, und ohne sie ließe sich später nicht
                # sagen, in welchem Steuerjahr der Abgang lag.
                spent_by[(prev_txid, int(vin.get("vout", 0)))] = {
                    "txid": txid_key,
                    "height": height,
                    "outputs": _fremde_outputs(tx),
                    # Diese Tx gibt aus. CoinJoin: eine Börsenadresse darin
                    # ist nicht das eigene Ziel.
                    "coinjoin": _tx_ist_coinjoin(tx),
                }

    return received, spent_by


def _status_fuer_hoehe(client: FulcrumClient, height: int) -> dict:
    """Bestätigungs-Status eines Outputs.

    Unbestätigt (Höhe ≤ 0): die Mindesthöhe ist der aktuelle Chain-Tip,
    die Zeit die dieses Blocks. ``mindesthoehe`` markiert den Zwischenstand,
    damit der Cache ihn nicht als endgültige Bestätigung behält.
    """
    if height <= 0:
        tip = int(get_chain_tip_height(client))
        status: dict[str, object] = {
            "confirmed": False,
            "block_height": tip,
            "mindesthoehe": True,
        }
        block_time = _block_time_for_height(client, tip)
        if block_time is not None:
            status["block_time"] = block_time
        return status
    status = {"confirmed": True, "block_height": height}
    block_time = _block_time_for_height(client, height)
    if block_time is not None:
        status["block_time"] = block_time
    return status


def fetch_address_history_fulcrum(
    client: FulcrumClient,
    address: str,
    scripthash: str,
    *,
    on_step=None,
) -> list[dict]:
    """
    Alle je auf einer Adresse empfangenen Outputs — auch längst ausgegebene.

    Der UTXO-Cache kennt nur Unverbrauchtes und taugt für zurückliegende
    Steuerjahre deshalb nicht: Was 2023 empfangen und 2024 ausgegeben wurde,
    steht dort nicht mehr. Hier steht es, mit ``spent`` und ``spent_txid``.
    """
    received, spent_by = _walk_address_history(
        client, address, scripthash, on_step=on_step,
    )

    eintraege: list[dict] = []
    n_rec = len(received)
    for index, ((txid_key, vout_idx), info) in enumerate(received.items(), start=1):
        if on_step and n_rec:
            try:
                on_step(f"Zeiten {index}/{n_rec}")
            except Exception:
                pass
        abgang = spent_by.get((txid_key, vout_idx))
        eintrag = {
            "txid": txid_key,
            "vout": vout_idx,
            "value": info["value"],
            "status": _status_fuer_hoehe(client, info["height"]),
            "spent": abgang is not None,
            "spent_txid": abgang["txid"] if abgang else None,
        }
        if abgang:
            # Zieladressen der Ausgabetransaktion — ohne erneuten Tx-Abruf
            # beschriftbar („davon … an Kraken“). CoinJoin: Adresse ist nicht
            # das eigene Ziel, nur eine Report-TxID darf dann benennen.
            eintrag["spent_outputs"] = list(abgang.get("outputs") or [])
            eintrag["spent_coinjoin"] = bool(abgang.get("coinjoin"))
        if abgang and abgang["height"] > 0:
            eintrag["spent_height"] = abgang["height"]
            abgangszeit = _block_time_for_height(client, abgang["height"])
            if abgangszeit is not None:
                eintrag["spent_time_ts"] = abgangszeit
        eintraege.append(eintrag)
    return eintraege


def _verlauf_fortschritt(
    rest: int,
    gesamt: int,
    bisher: int,
    *,
    adresse_nr: int | None = None,
    detail: str = "",
) -> str:
    """Statuszeile: Restadressen zuerst, dann schon erfasste Einträge."""
    wort = "Eintrag" if bisher == 1 else "Einträge"
    text = (
        f"Frage Verlauf für {gesamt} Adressen — noch {rest} von {gesamt} Adressen"
        f" · bisher {bisher} {wort}"
    )
    if adresse_nr is not None:
        text += f" · Adresse {adresse_nr}/{gesamt}"
    if detail:
        text += f" · {detail}"
    return text


def fetch_wallet_history_fulcrum(
    client: FulcrumClient,
    addresses,
    *,
    on_progress=None,
    skip_addresses=None,
    on_address_done=None,
    seed_eintraege=None,
) -> list[dict]:
    """
    Verlauf über alle Adressen eines Wallets, je Eintrag mit ``address``.

    Ohne die Adresse ließe sich später nicht mehr sagen, zu welchem Wallet ein
    Eintrag gehört — dieselbe Zuordnung, die der UTXO-Scan mitführt.

    *skip_addresses*: bereits erledigte Adressen (Resume nach Abbruch).
    *on_address_done(address, neue_eintraege)*: nach jeder Adresse — zum
    Zwischenstand speichern.
    *seed_eintraege*: bereits bekannte Einträge (zählen für die Fortschrittszeile).
    """
    from display import is_list_abort_requested

    eintraege: list[dict] = list(seed_eintraege or [])
    skip = set(skip_addresses or [])
    adressliste = sorted(addresses)
    offen = [a for a in adressliste if a not in skip]
    gesamt = len(adressliste)
    erledigt_basis = gesamt - len(offen)

    def _melde(
        rest_offen: int,
        *,
        sofort: bool = False,
        adresse_nr: int | None = None,
        detail: str = "",
    ) -> None:
        if not on_progress:
            return
        text = _verlauf_fortschritt(
            rest_offen, gesamt, len(eintraege),
            adresse_nr=adresse_nr, detail=detail,
        )
        try:
            on_progress(text, sofort=sofort)
        except TypeError:
            on_progress(text)

    if erledigt_basis and on_progress:
        _melde(len(offen), sofort=True)

    for nummer, address in enumerate(offen, start=1):
        if is_list_abort_requested():
            return eintraege
        rest = len(offen) - nummer + 1
        adresse_nr = erledigt_basis + nummer
        # Erste Adresse / jede 5.: sofort ins Log — sonst nur „Moment noch“,
        # während Tor an get_history oder den Tx-Downloads hängt.
        _melde(
            rest,
            sofort=(nummer == 1 or nummer % 5 == 1),
            adresse_nr=adresse_nr,
            detail="get_history…",
        )
        neu: list[dict] = []
        try:
            scripthash = address_to_scripthash(address)
        except Exception as exc:
            try:
                from core.jobs import ist_abbruch

                if ist_abbruch(exc):
                    raise
            except ImportError:
                pass
            if on_address_done:
                on_address_done(address, [])
            continue

        def _schritt(detail: str, *, _rest=rest, _nr=adresse_nr) -> None:
            # Text ändert sich (Tx 3/12…) → tick schreibt nach ~10s Stille.
            _melde(_rest, sofort=False, adresse_nr=_nr, detail=detail)

        for eintrag in fetch_address_history_fulcrum(
            client, address, scripthash, on_step=_schritt,
        ):
            eintrag["address"] = address
            neu.append(eintrag)
            eintraege.append(eintrag)
        if on_address_done:
            on_address_done(address, neu)
        # Nach Adresse: Rest zählt runter (tick, nicht jede Adresse phase).
        _melde(
            max(0, rest - 1),
            sofort=(nummer % 5 == 0 or nummer == len(offen)),
            adresse_nr=adresse_nr,
        )
        if on_progress is None and (
            (erledigt_basis + nummer) % 25 == 0 or nummer == len(offen)
        ):
            print(
                f"  Fulcrum Verlauf {erledigt_basis + nummer}/{gesamt}...",
                flush=True,
            )
    if gesamt:
        _melde(0, sofort=True)
    return eintraege


def _fetch_address_utxos_from_history(
    client: FulcrumClient,
    address: str,
    scripthash: str,
) -> list[dict]:
    """
    Leitet unspent UTXOs aus get_history + Transaktionsdaten ab.

    Fallback für Server ohne ``listunspent``. Die Ausgabe bleibt bewusst die
    eines UTXO-Abrufs — ohne die Verlaufsfelder, damit Aufrufer nicht
    versehentlich ausgegebene Outputs mitzählen.
    """
    received, spent_by = _walk_address_history(client, address, scripthash)

    utxos: list[dict] = []
    for (txid_key, vout_idx), info in received.items():
        if (txid_key, vout_idx) in spent_by:
            continue
        utxos.append({
            "txid": txid_key,
            "vout": vout_idx,
            "value": info["value"],
            "status": _status_fuer_hoehe(client, info["height"]),
        })
    return utxos


def _parse_utc_date_timestamp(date_str: str) -> int:
    from datetime import datetime, timezone

    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            continue
    raise ValueError(
        f"Datum nicht erkannt: {date_str!r} (DD.MM.YYYY oder YYYY-MM-DD)"
    )


_TIP_HEIGHT_CACHE: dict[str, int] = {}
_DATE_HEIGHT_CACHE: dict[tuple[str, str], int] = {}
_TIP_SEARCH_CEILING = 1_500_000
SANCTIONS_HISTORY_PROBE_HEIGHT = 500_000


def _fulcrum_client_cache_key(client) -> str:
    host = getattr(client, "host", None)
    if host:
        return str(host)
    return str(id(client))


def _header_exists_at_height(client, height: int) -> bool:
    return _fetch_block_header_hex(client, height) is not None


def supports_historical_headers(
    client,
    probe_height: int = SANCTIONS_HISTORY_PROBE_HEIGHT,
) -> bool:
    """True wenn der Server Block-Header weit in der Vergangenheit liefert."""
    return _header_exists_at_height(client, probe_height)


def _tip_height_via_binary_search(client) -> int:
    lo, hi = 0, _TIP_SEARCH_CEILING
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _header_exists_at_height(client, mid):
            lo = mid
        else:
            hi = mid - 1
    if lo <= 0:
        raise RuntimeError("Chain-Tip über Fulcrum nicht ermittelbar")
    return lo


def get_chain_tip_height(client: FulcrumClient, *, force: bool = False) -> int:
    """Aktuelle Chain-Tip-Höhe (subscribe, sonst Binärsuche auf block.header).

    *force*: Cache ignorieren — nötig für Tip-Nachzug über Stunden, sonst
    bleibt der Prozess auf dem ersten Tip der Session kleben.
    """
    cache_key = _fulcrum_client_cache_key(client)
    if not force:
        cached = _TIP_HEIGHT_CACHE.get(cache_key)
        if cached is not None:
            return cached

    try:
        result = client.request("blockchain.headers.subscribe")
    except Exception:
        result = None

    tip: int | None = None
    if isinstance(result, dict) and result.get("height") is not None:
        tip = int(result["height"])
    elif isinstance(result, list):
        # Manche Server liefern Notifications statt Tip-Dict — nicht vertrauen.
        pass

    if tip is None or not _header_exists_at_height(client, tip):
        tip = _tip_height_via_binary_search(client)

    _TIP_HEIGHT_CACHE[cache_key] = tip
    return tip


def date_to_block_height_fulcrum(client: FulcrumClient, date_str: str) -> int:
    """Erste Blockhöhe am oder nach dem Datum (UTC-Tagesbeginn).

    Liegt das Datum unter dem Tip von ``p2p_headers.bin``, kommt die Höhe
    lokal aus der Halbierung. Sonst ist der lokale Tip die untere Grenze
    und nur das Reststück geht an den Server.
    """
    cache_key = _fulcrum_client_cache_key(client)
    date_key = date_str.strip()
    cached = _DATE_HEIGHT_CACHE.get((cache_key, date_key))
    if cached is not None:
        return cached

    target_ts = _parse_utc_date_timestamp(date_key)
    lokal = _hoehe_zur_zeit_lokal(target_ts)
    if lokal is not None:
        _DATE_HEIGHT_CACHE[(cache_key, date_key)] = lokal
        return lokal
    tip = get_chain_tip_height(client)
    lo = _lokaler_header_tip() or 0
    if lo > tip:
        lo = 0
    hi = tip
    while lo < hi:
        mid = (lo + hi) // 2
        block_time = _block_time_for_height(client, mid)
        if block_time is None:
            # Geprunter/unvollständiger Server: nur oberhalb von mid weitersuchen.
            lo = mid + 1
            continue
        if block_time < target_ts:
            lo = mid + 1
        else:
            hi = mid
    if lo > tip:
        raise RuntimeError(
            f"Kein Block für Datum {date_key!r} ermittelbar "
            f"(Server ohne Historie ab Höhe {tip:,})"
        )
    _DATE_HEIGHT_CACHE[(cache_key, date_key)] = lo
    return lo