#!/usr/bin/env python3
"""Jede eigene Datenquelle allein gegen das Lab-Inventar.

Reihenfolge wie die Datenquellen-Zeilen:

1. Eigener Electrum-Server
2. Pruned Node (UTXO-RPC-Slot)
3. Bitcoin Core · RPC (Tx/Block-Lookup)

Zuerst der SatSage-Cache des Labors (UTXO- und Tx-Cache der Präsentation).
Je Quelle: eigenes Cache-Verzeichnis leer, nur diese Verbindung in der Env,
dann UTXO-Bestand und Herkunft jedes Inventar-UTXOs. Kein Fallback
auf eine andere Quelle. P2P läuft für den UTXO-Bestand mit, auch
während ``p2p_gesperrt()`` wahr ist: die Sockets stehen nur in
``p2p_nur_utxo_entdeckung``. Der P2P-Lauf ist kein Vollvergleich:
Bestand über Compact Filter, dann die Knöpfe Grau und Gelb. Danach
bleiben rote Ringe (unvollständige Herkunft). Electrs auf demselben
Cache, noch einmal Grau und Gelb: die Ringe sind weg, jedes UTXO ist
entweder vollständig verfolgt oder ohne Baum schon außerhalb der
Haltefrist.

Soll: ``.data/herkunft-inventar.json`` (von ``generate_scenarios.py``).
Der Labor-Node ist nicht geprunt. „Pruned Node“ meint den Slot
``UTXO_RPC_*`` ohne ``NODE_IP`` und ohne Electrum. Tx-Lookup geht dann
über denselben RPC.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
HERE = SCRIPTS.parent
REPO = HERE.parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
WORK = HERE / ".data" / "quellen-inventar"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))

from infra_check import brauche  # noqa: E402
from herkunft_inventar import (  # noqa: E402
    _signatur,
    lade_inventar,
    vergleiche_bestand,
    vergleiche_herkunft,
)

# Zeilen 1–3. P2P ist die vierte, nur ohne Sperre.
QUELLEN = (
    "own_fulcrum",
    "own_utxo_core",
    "own_core",
)
P2P_QUELLE = "bip158"

_BEHALTEN = ("NETWORK", "STEUER_HALTEFRIST_JAHRE")
_STREICHEN = (
    "FULCRUM_HOST",
    "FULCRUM_TOR",
    "FULCRUM_PORT",
    "FULCRUM_SSL",
    "FULCRUM_TOR_PROXY",
    "NODE_IP",
    "RPCHOST",
    "BITCOIN_RPC_HOST",
    "BITCOIND_HOST",
    "RPCPORT",
    "RPCUSER",
    "RPCPASSWORD",
    "RPC_SSL",
    "RPC_COOKIE_FILE",
    "UTXO_RPC_HOST",
    "UTXO_RPCPORT",
    "UTXO_RPCUSER",
    "UTXO_RPCPASSWORD",
    "UTXO_RPC_SSL",
    "UTXO_RPC_COOKIE_FILE",
    "BIP158_P2P",
    "BIP158_PEERS",
    "BIP158_HOST",
    "OEFFENTLICHE_ELECTRUM",
    "WALLETS_IMMER_AKTUELL",
)

_NAMEN = {
    "own_fulcrum": "1 Eigener Electrum-Server",
    "own_utxo_core": "2 Pruned Node",
    "own_core": "3 Bitcoin Core · RPC",
    "bip158": "4 Bitcoin-P2P · Compact Filter",
}

_CACHE_QUELLE = {
    "own_fulcrum": "fulcrum",
    "own_utxo_core": "bitcoind",
    "own_core": "bitcoind",
    "bip158": "bip158",
}


def _load_env(path: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not path.is_file():
        return werte
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        werte[k.strip()] = v.strip()
    return werte


def _basis(werte: dict[str, str]) -> dict[str, str]:
    out = {
        k: v
        for k, v in werte.items()
        if k.startswith("WALLET_") or k in _BEHALTEN
    }
    out["NETWORK"] = "regtest"
    out["OEFFENTLICHE_ELECTRUM"] = "0"
    out["BIP158_P2P"] = "0"
    out["TOR_AUTOSTART"] = "0"
    out["WALLETS_IMMER_AKTUELL"] = "0"
    return out


def _brauche(werte: dict[str, str], *keys: str) -> None:
    fehlend = [k for k in keys if not (werte.get(k) or "").strip()]
    if fehlend:
        raise RuntimeError(
            "Lab-Env unvollständig: " + ", ".join(fehlend)
        )


def isolierte_env(basis: dict[str, str], quelle: str) -> dict[str, str]:
    """Env mit Wallets und genau einer Datenquelle."""
    out = _basis(basis)
    if quelle == "own_fulcrum":
        _brauche(basis, "FULCRUM_HOST", "FULCRUM_PORT")
        out["FULCRUM_HOST"] = basis["FULCRUM_HOST"]
        out["FULCRUM_PORT"] = basis["FULCRUM_PORT"]
        out["FULCRUM_SSL"] = basis.get("FULCRUM_SSL") or "false"
        return out
    if quelle == "own_utxo_core":
        _brauche(basis, "NODE_IP", "RPCPORT", "RPCUSER", "RPCPASSWORD")
        out["UTXO_RPC_HOST"] = basis["NODE_IP"]
        out["UTXO_RPCPORT"] = basis["RPCPORT"]
        out["UTXO_RPCUSER"] = basis["RPCUSER"]
        out["UTXO_RPCPASSWORD"] = basis["RPCPASSWORD"]
        out["UTXO_RPC_SSL"] = basis.get("RPC_SSL") or "false"
        return out
    if quelle == "own_core":
        _brauche(basis, "NODE_IP", "RPCPORT", "RPCUSER", "RPCPASSWORD")
        out["NODE_IP"] = basis["NODE_IP"]
        out["RPCPORT"] = basis["RPCPORT"]
        out["RPCUSER"] = basis["RPCUSER"]
        out["RPCPASSWORD"] = basis["RPCPASSWORD"]
        out["RPC_SSL"] = basis.get("RPC_SSL") or "false"
        return out
    if quelle == P2P_QUELLE:
        out["BIP158_P2P"] = "1"
        out["BIP158_START_HEIGHT"] = "1"
        out["BIP158_PEERS"] = basis.get("BIP158_PEERS") or "127.0.0.1:18444"
        return out
    raise ValueError(f"unbekannte Quelle: {quelle}")


def geplante_quellen(*, p2p_an: bool) -> list[str]:
    """1–3 immer. P2P, wenn der Aufrufer den Bestands-Schritt will."""
    quellen = list(QUELLEN)
    if p2p_an:
        quellen.append(P2P_QUELLE)
    return quellen


def _kurz(txid: str) -> str:
    t = (txid or "").strip().lower()
    return f"{t[:8]}…{t[-4:]}" if len(t) >= 16 else t


def _aktiviere_env(pfad: Path, werte: dict[str, str]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(
        "\n".join(f"{k}={v}" for k, v in werte.items()) + "\n",
        encoding="utf-8",
    )
    import core.env_bootstrap as boot
    import main

    boot.ENV_FILE = pfad
    main.ENV_FILE = pfad
    for key in list(os.environ):
        if key in _STREICHEN or key.startswith("FULCRUM_TOR_") or key.startswith("UTXO_RPC"):
            os.environ.pop(key, None)
    os.environ.update(werte)
    main.set_chain_network("regtest")


def _leere_cache(pfad: Path) -> None:
    if pfad.exists():
        shutil.rmtree(pfad)
    pfad.mkdir(parents=True)


def leere_labor_cache() -> None:
    """SatSage-Cache des Labors weg, bevor eine Quelle allein geprüft wird.

    Das ist der Cache der Präsentation (``--cache-dir``), nicht die
    Bitcoin- oder Electrs-Daten und nicht der Cache im Repository-Root.
    """
    for name in ("utxo_cache", "immutable_cache"):
        _leere_cache(HERE / ".data" / name)
    print("SatSage-Labor-Cache geleert.", flush=True)


def _sammle(utxos: list[dict]) -> dict[str, dict]:
    gefunden: dict[str, dict] = {}
    for u in utxos:
        txid = str(u.get("txid") or "").lower()
        try:
            vout = int(u.get("vout", 0))
        except (TypeError, ValueError):
            continue
        if not txid:
            continue
        zeile = dict(u)
        zeile["txid"] = txid
        zeile["vout"] = vout
        gefunden[f"{txid}:{vout}"] = zeile
    return gefunden


def _cache_quellen(cache_dir: Path) -> set[str]:
    quellen: set[str] = set()
    if not cache_dir.is_dir():
        return quellen
    for datei in cache_dir.glob("*.json"):
        try:
            roh = json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(roh, dict) and roh.get("source"):
            quellen.add(str(roh["source"]))
    return quellen


def _verboten(*_a, **_k):
    raise AssertionError(
        "UTXO-Scan hat die einzige konfigurierte Quelle verlassen"
    )


def _scan_electrum(env: dict[str, str], cache_dir: Path, ctx, wallets):
    from core.fulcrum_client import connect_fulcrum
    from core.fulcrum_wallet import fetch_wallet_utxos_fulcrum
    from core.wallet_sync_engine import _full_rescan_xpub
    from core.chain_sources import _build_blockchain_fetchers

    host = env["FULCRUM_HOST"]
    port = int(env["FULCRUM_PORT"])
    ssl = str(env.get("FULCRUM_SSL") or "false").lower() in ("1", "true", "ja")
    client, fehler = connect_fulcrum(host, port, use_ssl=ssl, timeout=30)
    if client is None:
        raise RuntimeError(f"Electrs nicht verbunden: {fehler}")
    print(f"  Electrs {host}:{port}", flush=True)

    def fetch(addrs, **kw):
        return fetch_wallet_utxos_fulcrum(
            client,
            addrs,
            on_progress=kw.get("on_progress"),
            on_utxos_update=kw.get("on_utxos_update"),
        )

    gefunden: dict[str, dict] = {}
    for w in wallets:
        stand = _full_rescan_xpub(
            w.xpub,
            fetch,
            cache_dir,
            "fulcrum",
            w.max_addresses,
            wallet=ctx,
            fulcrum=client,
        )
        gefunden.update(_sammle(stand or []))
    args = SimpleNamespace(
        xpubs=[w.xpub for w in wallets],
        max_addresses=max(w.max_addresses for w in wallets),
        no_verbose=True,
    )
    fetcher = _build_blockchain_fetchers(
        "fulcrum",
        client,
        args,
        ctx,
        immutable_cache_dir=cache_dir.parent / "immutable_cache",
    )
    return gefunden, fetcher["get_tx"], client


def _scan_core(env: dict[str, str], cache_dir: Path, ctx, wallets):
    from core.bitcoind_rpc import (
        fetch_tx_core_mit_rollen,
        stelle_tx_lookup_rollen,
    )
    from core.chain_sources import wrap_get_tx_with_immutable_cache
    from core.wallet_sync_engine import _full_rescan_xpub

    gefunden: dict[str, dict] = {}
    for w in wallets:
        stand = _full_rescan_xpub(
            w.xpub,
            _verboten,
            cache_dir,
            "bitcoind",
            w.max_addresses,
            wallet=ctx,
            fulcrum=None,
        )
        gefunden.update(_sammle(stand or []))
    lokal, archival, prune = stelle_tx_lookup_rollen(env, timeout=30.0)
    if lokal is None and archival is None:
        raise RuntimeError("kein Core-RPC für die Herkunft")

    def raw(txid: str) -> dict:
        return fetch_tx_core_mit_rollen(
            txid,
            local=lokal,
            archival=archival,
            local_pruneheight=prune,
        )

    get_tx = wrap_get_tx_with_immutable_cache(
        raw, cache_dir.parent / "immutable_cache", "bitcoind",
    )
    return gefunden, get_tx, (lokal, archival)


def _trace(
    *,
    quelle: str,
    soll: dict[str, dict],
    gefunden: dict[str, dict],
    get_tx,
    ctx,
    cache_dir: Path,
    max_traces: int,
) -> dict[str, Any]:
    from core.utxo_origin import trace_utxo_origin

    fehlend, extra, faelle = vergleiche_bestand(
        soll, gefunden, addr_wallet=ctx.address_to_wallet, quelle=quelle,
    )
    keys = list(soll)[:max_traces] if max_traces > 0 else list(soll)
    ok = 0
    fail = len(fehlend) + len(extra)
    eigene = set(ctx.address_to_wallet)
    for i, key in enumerate(keys, 1):
        if key not in gefunden:
            continue
        eintrag = soll[key]
        u = gefunden[key]
        txid = eintrag["txid"]
        vout = int(eintrag["vout"])
        start = time.monotonic()
        try:
            ist_sats = int(u.get("value") or 0)
            if ist_sats != int(eintrag["amount_sats"]):
                raise AssertionError(
                    f"Betrag {ist_sats} != {eintrag['amount_sats']}"
                )
            wallet_ist = ctx.address_to_wallet.get(u.get("address"))
            if wallet_ist != eintrag["wallet"]:
                raise AssertionError(
                    f"Wallet {wallet_ist} != {eintrag['wallet']}"
                )
            baum = trace_utxo_origin(
                get_tx, txid, vout, eigene, wallet=ctx, cache_dir=cache_dir,
            )
            diff = vergleiche_herkunft(eintrag["herkunft"], _signatur(baum))
            if diff:
                raise AssertionError(diff)
            dauer = time.monotonic() - start
            ok += 1
            print(
                f"  OK  {i}/{len(keys)} {_kurz(txid)}:{vout} "
                f"{eintrag['wallet']} {dauer:.1f}s",
                flush=True,
            )
            faelle.append({
                "txid": _kurz(txid), "vout": vout, "ok": True,
                "wallet": eintrag["wallet"], "seconds": round(dauer, 2),
            })
        except Exception as exc:
            dauer = time.monotonic() - start
            fail += 1
            print(
                f"  FAIL {i}/{len(keys)} {_kurz(txid)}:{vout} "
                f"{type(exc).__name__}: {exc} {dauer:.1f}s",
                flush=True,
            )
            faelle.append({
                "txid": _kurz(txid), "vout": vout, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(dauer, 2),
            })
    voll = (
        max_traces <= 0
        and not fehlend
        and not extra
        and fail == 0
        and ok == len(soll)
    )
    if max_traces > 0:
        print(
            f"  Teilvergleich {ok}/{len(keys)} — "
            "Quelle bleibt rot, bis alle Inventar-UTXOs verglichen sind.",
            flush=True,
        )
        voll = False
    return {
        "ok": voll,
        "traced": ok,
        "failed": fail,
        "utxos": len(gefunden),
        "missing": len(fehlend),
        "extra": len(extra),
        "cases": faelle,
    }


def _laufe_quelle(
    quelle: str,
    basis: dict[str, str],
    soll: dict[str, dict],
    *,
    max_traces: int,
) -> dict[str, Any]:
    import main as satsage_main
    from core.config import EnvFile, read_wallets

    name = _NAMEN[quelle]
    print(f"\n=== {name} — Cache leer, nur diese Quelle ===", flush=True)
    wurzel = WORK / quelle
    _leere_cache(wurzel)
    cache_dir = wurzel / "utxo_cache"
    cache_dir.mkdir(parents=True)
    (wurzel / "immutable_cache").mkdir(parents=True)
    env = isolierte_env(basis, quelle)
    env_pfad = wurzel / ".env"
    _aktiviere_env(env_pfad, env)
    wallets = read_wallets(EnvFile.load(env_pfad))
    if not wallets:
        raise RuntimeError("Keine WALLET_* in der isolierten Env")
    ctx = satsage_main.build_wallet_context(
        [w.xpub for w in wallets],
        wallet_names=[w.name for w in wallets],
        max_addresses_per_xpub=[w.max_addresses for w in wallets],
        script_types=[w.script_type for w in wallets],
    )
    t0 = time.monotonic()
    client = None
    cores = ()
    try:
        if quelle == "own_fulcrum":
            gefunden, get_tx, client = _scan_electrum(env, cache_dir, ctx, wallets)
        else:
            gefunden, get_tx, cores = _scan_core(env, cache_dir, ctx, wallets)
        print(
            f"  Bestand {len(gefunden)} UTXOs, Inventar {len(soll)}, "
            f"{time.monotonic() - t0:.1f}s",
            flush=True,
        )
        ist_cache = _cache_quellen(cache_dir)
        soll_cache = _CACHE_QUELLE[quelle]
        if soll_cache not in ist_cache:
            raise RuntimeError(
                f"Cache-Quelle {sorted(ist_cache) or 'leer'}, erwartet {soll_cache}"
            )
        if quelle == "own_fulcrum" and "bitcoind" in ist_cache:
            raise RuntimeError("Electrum-Lauf hat scantxoutset geschrieben")
        ergebnis = _trace(
            quelle=name,
            soll=soll,
            gefunden=gefunden,
            get_tx=get_tx,
            ctx=ctx,
            cache_dir=cache_dir,
            max_traces=max_traces,
        )
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        for rpc in cores:
            if rpc is None:
                continue
            try:
                rpc.close()
            except Exception:
                pass
    ergebnis["quelle"] = quelle
    ergebnis["name"] = name
    return ergebnis


def utxo_ist_voll_geklaert(zeile: dict, steuer: dict | None) -> bool:
    """Kein roter Ring. Ohne Baum nur, wenn die Haltefrist schon erfüllt ist.

    Gelb mit vollständigem Baum bleibt gelb, bis die Frist abläuft. Das
    ist geklärt. Grau, undatierte Lots und ein unvollständiger Baum nicht.
    """
    if zeile.get("unvollstaendig"):
        return False
    if zeile.get("verfolgt") and not zeile.get("verfolgt_vollstaendig"):
        return False
    if not steuer:
        return False
    if steuer.get("geprueft"):
        if int(steuer.get("sats_grau") or 0) > 0:
            return False
        if int(steuer.get("sats_ohne_datum") or 0) > 0:
            return False
        if steuer.get("herkunft_offen"):
            return False
        return bool(zeile.get("verfolgt_vollstaendig"))
    return bool(steuer.get("erfuellt"))


def p2p_nach_klaeren_ok(*, rote: int) -> tuple[bool, str]:
    """Nach dem P2P-Klären muss mindestens ein roter Ring stehen."""
    if rote < 1:
        return False, "nach P2P-Klären fehlt der rote Ring"
    return True, ""


def electrs_nach_klaeren_ok(
    *,
    rote: int,
    grau: list[str],
    lot: list[str],
    offen: list[str],
) -> tuple[bool, str]:
    """Nach Electrs: keine roten Ringe, kein Grau, nichts unvollständig."""
    if rote:
        return False, f"nach Electrs noch {rote} rote Ringe"
    if grau or lot:
        return False, "nach Electrs bleiben graue UTXOs"
    if offen:
        return False, f"nach Electrs noch {len(offen)} unvollständig geklärte UTXOs"
    return True, ""


def _parse_keys(keys: list[str]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    gesehen: set[tuple[str, int]] = set()
    for roh in keys:
        if not isinstance(roh, str) or ":" not in roh:
            continue
        tx, vo = roh.split(":", 1)
        try:
            key = (tx.strip(), int(vo))
        except ValueError:
            continue
        if key[0] and key not in gesehen:
            gesehen.add(key)
            out.append(key)
    return out


def _utxos_aus_cache(cache_dir: Path, wallets) -> list[dict]:
    from core.xpub_cache import load_xpub_utxo_cache

    alle: list[dict] = []
    for w in wallets:
        alle.extend(load_xpub_utxo_cache(w.xpub, cache_dir) or [])
    return alle


def _steuer_stand(utxos: list[dict], ctx, imm: Path, env: dict[str, str]):
    from datetime import datetime

    from core.steuer_fenster import klaeren_keys
    from core.tax import auswerten, lese_steuer_einstellungen, parse_stichtag
    from core.utxos import utxo_as_dict

    eigene = set(ctx.address_to_wallet)
    zeilen = [
        utxo_as_dict(
            u, wallet=ctx, immutable_cache_dir=imm, own_addresses=eigene,
        )
        for u in utxos
    ]
    einstellung = lese_steuer_einstellungen(env)
    auswertung = auswerten(
        utxos,
        datetime.now().year,
        haltefrist_jahre=einstellung["haltefrist_jahre"],
        stichtag=parse_stichtag(einstellung["stichtag"]),
        anschaffung=einstellung["anschaffung"],
        wallet=ctx,
        immutable_cache_dir=imm,
    )
    steuer = {
        f"{e.get('txid')}:{e.get('vout')}": e
        for e in (auswertung.get("eintraege") or [])
    }
    return zeilen, steuer, klaeren_keys(auswertung)


def _rote_ringe(zeilen: list[dict]) -> list[str]:
    return [str(z.get("key") or "") for z in zeilen if z.get("unvollstaendig")]


def _ungeklaert(zeilen: list[dict], steuer: dict[str, dict]) -> list[str]:
    offen: list[str] = []
    for zeile in zeilen:
        key = str(zeile.get("key") or "")
        if not utxo_ist_voll_geklaert(zeile, steuer.get(key)):
            offen.append(key)
    return offen


def _resume_origin(txid: str, vout: int, imm: Path, eigene: set):
    from core import trace_cache
    from core.utxo_origin import hat_brauchbaren_teilfortschritt

    geladen = trace_cache.laden(txid, vout, imm, eigene)
    if not geladen or not isinstance(geladen.get("baum"), dict):
        return None
    origin = geladen["baum"].get("origin_tree")
    if isinstance(origin, dict) and hat_brauchbaren_teilfortschritt(origin):
        return origin
    return None


def _klaere_keys(
    keys: list[str],
    *,
    erzwingen: bool,
    graue_anteile: bool,
    get_tx,
    ctx,
    cache_dir: Path,
    imm: Path,
    cache_source: str,
) -> None:
    """Dieselbe Auswahl wie ``/trace/alle`` für die Scorecard-Knöpfe."""
    from core import trace_cache
    from core.trace import externe_blockzeiten_speichern, hat_extern_ohne_zeit, trace_utxo
    from core.xpub_cache import load_utxo_ingress_cache
    from httpserver.trace_helpers import _ingress_veraltet

    gewuenscht = _parse_keys(keys)
    if not gewuenscht:
        print("  nichts zu klären", flush=True)
        return
    eigene = set(ctx.address_to_wallet)
    walk: list[tuple[str, int]] = []
    nur_zeiten: list[tuple[str, int]] = []
    for txid, vout in gewuenscht:
        if erzwingen:
            walk.append((txid, vout))
            continue
        kopf = trace_cache.kopf(txid, vout, imm, eigene)
        if kopf is None or kopf.get("veraltet") or not kopf.get("vollstaendig"):
            walk.append((txid, vout))
            continue
        geladen = trace_cache.laden(txid, vout, imm)
        baum = geladen.get("baum") if geladen else None
        ingress_offen = _ingress_veraltet(load_utxo_ingress_cache(txid, vout, imm))
        extern_ohne_zeit = bool(graue_anteile and hat_extern_ohne_zeit(baum))
        if not extern_ohne_zeit and not ingress_offen:
            continue
        if graue_anteile and kopf.get("vollstaendig") and not kopf.get("veraltet"):
            nur_zeiten.append((txid, vout))
        else:
            walk.append((txid, vout))
    print(
        f"  Klären: {len(walk)} Herkunft, {len(nur_zeiten)} Blockzeiten",
        flush=True,
    )
    for txid, vout in nur_zeiten:
        externe_blockzeiten_speichern(txid, vout, get_tx, imm)
    gesamt = len(walk)
    for i, (txid, vout) in enumerate(walk, 1):
        print(f"  {i}/{gesamt} {_kurz(txid)}:{vout}", flush=True)
        try:
            trace_utxo(
                get_tx, txid, vout, eigene,
                wallet=ctx,
                cache_dir=cache_dir,
                immutable_cache_dir=imm,
                cache_source=cache_source,
                resume_origin=_resume_origin(txid, vout, imm, eigene),
            )
            if graue_anteile:
                externe_blockzeiten_speichern(txid, vout, get_tx, imm)
        except Exception as exc:
            print(
                f"  FAIL {_kurz(txid)}:{vout} {type(exc).__name__}: {exc}",
                flush=True,
            )


def _druecke_grau(env, ctx, cache_dir: Path, imm: Path, wallets, get_tx, quelle: str) -> None:
    utxos = _utxos_aus_cache(cache_dir, wallets)
    _zeilen, _steuer, keys = _steuer_stand(utxos, ctx, imm, env)
    print(f"  Grau: {len(keys['grau_keys'])} UTXOs", flush=True)
    _klaere_keys(
        keys["grau_keys"],
        erzwingen=True,
        graue_anteile=False,
        get_tx=get_tx,
        ctx=ctx,
        cache_dir=cache_dir,
        imm=imm,
        cache_source=quelle,
    )
    utxos = _utxos_aus_cache(cache_dir, wallets)
    _zeilen, _steuer, keys = _steuer_stand(utxos, ctx, imm, env)
    print(f"  Lot-Grau: {len(keys['lot_grau_keys'])} UTXOs", flush=True)
    _klaere_keys(
        keys["lot_grau_keys"],
        erzwingen=False,
        graue_anteile=True,
        get_tx=get_tx,
        ctx=ctx,
        cache_dir=cache_dir,
        imm=imm,
        cache_source=quelle,
    )


def _druecke_gelb(env, ctx, cache_dir: Path, imm: Path, wallets, get_tx, quelle: str) -> None:
    utxos = _utxos_aus_cache(cache_dir, wallets)
    _zeilen, _steuer, keys = _steuer_stand(utxos, ctx, imm, env)
    if keys["grau_keys"]:
        print("  Gelb startet zuerst Grau", flush=True)
        _druecke_grau(env, ctx, cache_dir, imm, wallets, get_tx, quelle)
        utxos = _utxos_aus_cache(cache_dir, wallets)
        _zeilen, _steuer, keys = _steuer_stand(utxos, ctx, imm, env)
    print(f"  Gelb: {len(keys['gelb_keys'])} UTXOs", flush=True)
    _klaere_keys(
        keys["gelb_keys"],
        erzwingen=False,
        graue_anteile=True,
        get_tx=get_tx,
        ctx=ctx,
        cache_dir=cache_dir,
        imm=imm,
        cache_source=quelle,
    )


def _grau_und_gelb(env, ctx, cache_dir, imm, wallets, get_tx, quelle: str) -> dict[str, Any]:
    print("  Knopf Grau", flush=True)
    _druecke_grau(env, ctx, cache_dir, imm, wallets, get_tx, quelle)
    print("  Knopf Gelb", flush=True)
    _druecke_gelb(env, ctx, cache_dir, imm, wallets, get_tx, quelle)
    utxos = _utxos_aus_cache(cache_dir, wallets)
    zeilen, steuer, keys = _steuer_stand(utxos, ctx, imm, env)
    rote = [k for k in _rote_ringe(zeilen) if k]
    offen = _ungeklaert(zeilen, steuer)
    stand = {
        "rote": len(rote),
        "grau": list(keys["grau_keys"]),
        "gelb": list(keys["gelb_keys"]),
        "lot": list(keys["lot_grau_keys"]),
        "offen": offen,
        "utxos": len(zeilen),
    }
    print(
        f"  Ringe {stand['rote']}, grau {len(stand['grau'])}, "
        f"gelb {len(stand['gelb'])}, lot-grau {len(stand['lot'])}, "
        f"ungeklärt {len(offen)}",
        flush=True,
    )
    return stand


def _pruefe_bestand(soll: dict[str, dict], gefunden: dict[str, dict], ctx, quelle: str) -> None:
    fehlend, extra, _faelle = vergleiche_bestand(
        soll, gefunden, addr_wallet=ctx.address_to_wallet, quelle=quelle,
    )
    if fehlend or extra:
        raise RuntimeError(
            f"Bestand weicht ab: fehlend {len(fehlend)}, extra {len(extra)}"
        )
    for key, eintrag in soll.items():
        u = gefunden[key]
        ist_sats = int(u.get("value") or 0)
        if ist_sats != int(eintrag["amount_sats"]):
            raise RuntimeError(
                f"{_kurz(eintrag['txid'])}:{eintrag['vout']} "
                f"Betrag {ist_sats} != {eintrag['amount_sats']}"
            )
        wallet_ist = ctx.address_to_wallet.get(u.get("address"))
        if wallet_ist != eintrag["wallet"]:
            raise RuntimeError(
                f"{_kurz(eintrag['txid'])}:{eintrag['vout']} "
                f"Wallet {wallet_ist} != {eintrag['wallet']}"
            )


def _scan_p2p(client, cache_dir: Path, ctx, wallets) -> dict[str, dict]:
    from core.bip158_wallet import fetch_wallet_utxos_bip158
    from core.wallet_sync_engine import _full_rescan_xpub

    def fetch(_addrs, **kw):
        if not kw.get("filter_scan"):
            raise AssertionError("P2P-Bestand ohne Compact-Filter-Scan")
        xpubs = list(kw.get("xpubs") or [])
        return fetch_wallet_utxos_bip158(
            client,
            xpubs,
            max_addresses=int(kw.get("max_addr") or 400),
            on_utxos_update=kw.get("on_utxos_update"),
        )

    gefunden: dict[str, dict] = {}
    for w in wallets:
        stand = _full_rescan_xpub(
            w.xpub,
            fetch,
            cache_dir,
            "bip158",
            w.max_addresses,
            wallet=ctx,
            fulcrum=None,
        )
        gefunden.update(_sammle(stand or []))
    return gefunden


def _oeffne_electrs(env: dict[str, str], cache_dir: Path, ctx, wallets):
    from core.chain_sources import _build_blockchain_fetchers
    from core.fulcrum_client import connect_fulcrum

    host = env["FULCRUM_HOST"]
    port = int(env["FULCRUM_PORT"])
    ssl = str(env.get("FULCRUM_SSL") or "false").lower() in ("1", "true", "ja")
    client, fehler = connect_fulcrum(host, port, use_ssl=ssl, timeout=30)
    if client is None:
        raise RuntimeError(f"Electrs nicht verbunden: {fehler}")
    print(f"  Electrs {host}:{port}, Cache bleibt", flush=True)
    args = SimpleNamespace(
        xpubs=[w.xpub for w in wallets],
        max_addresses=max(w.max_addresses for w in wallets),
        no_verbose=True,
    )
    fetcher = _build_blockchain_fetchers(
        "fulcrum",
        client,
        args,
        ctx,
        immutable_cache_dir=cache_dir.parent / "immutable_cache",
    )
    return fetcher["get_tx"], client


def _schliesse_p2p(client) -> None:
    scanner = getattr(client, "scanner", None)
    close = getattr(scanner, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        pass


def _laufe_p2p(
    basis: dict[str, str],
    soll: dict[str, dict],
    *,
    max_traces: int,
) -> dict[str, Any]:
    from verify_p2p_traces import bau_client, bau_get_tx
    from core.bip158_wallet import clear_tx_height_hints
    from core.config import EnvFile, read_wallets
    import main as satsage_main

    name = _NAMEN[P2P_QUELLE]
    print(f"\n=== {name} — Bestand nur über P2P ===", flush=True)
    wurzel = WORK / P2P_QUELLE
    _leere_cache(wurzel)
    cache_dir = wurzel / "utxo_cache"
    imm = wurzel / "immutable_cache"
    cache_dir.mkdir(parents=True)
    imm.mkdir(parents=True)
    env = isolierte_env(basis, P2P_QUELLE)
    env_pfad = wurzel / ".env"
    _aktiviere_env(env_pfad, env)
    satsage_main.set_chain_network("regtest")
    clear_tx_height_hints()
    wallets = read_wallets(EnvFile.load(env_pfad))
    if not wallets:
        raise RuntimeError("Keine WALLET_* in der isolierten Env")
    ctx = satsage_main.build_wallet_context(
        [w.xpub for w in wallets],
        wallet_names=[w.name for w in wallets],
        max_addresses_per_xpub=[w.max_addresses for w in wallets],
        script_types=[w.script_type for w in wallets],
    )
    from core.p2p import p2p_nur_utxo_entdeckung

    p2p_client = None
    electrs = None
    try:
        # Herkunftssperre bleibt. Der Bestand und das anschließende
        # P2P-Klären (erwartet rote Ringe) öffnen nur hier Sockets.
        with p2p_nur_utxo_entdeckung():
            p2p_client, _tip = bau_client(env, cache_dir, imm)
            get_tx = bau_get_tx(p2p_client, imm)
            t0 = time.monotonic()
            gefunden = _scan_p2p(p2p_client, cache_dir, ctx, wallets)
            print(
                f"  Bestand {len(gefunden)} UTXOs, Inventar {len(soll)}, "
                f"{time.monotonic() - t0:.1f}s",
                flush=True,
            )
            ist_cache = _cache_quellen(cache_dir)
            if _CACHE_QUELLE[P2P_QUELLE] not in ist_cache:
                raise RuntimeError(
                    f"Cache-Quelle {sorted(ist_cache) or 'leer'}, erwartet bip158"
                )
            _pruefe_bestand(soll, gefunden, ctx, name)
            print("  Grau und Gelb über P2P", flush=True)
            nach_p2p = _grau_und_gelb(
                env, ctx, cache_dir, imm, wallets, get_tx, "bip158",
            )
            ok_p2p, grund = p2p_nach_klaeren_ok(rote=nach_p2p["rote"])
            if not ok_p2p:
                raise RuntimeError(grund)
            _schliesse_p2p(p2p_client)
            p2p_client = None

        print("  Electrs dazu, derselbe Cache", flush=True)
        env_electrs = isolierte_env(basis, "own_fulcrum")
        _aktiviere_env(env_pfad, env_electrs)
        get_tx, electrs = _oeffne_electrs(env_electrs, cache_dir, ctx, wallets)
        print("  Grau und Gelb über Electrs", flush=True)
        nach_electrs = _grau_und_gelb(
            env_electrs, ctx, cache_dir, imm, wallets, get_tx, "fulcrum",
        )
        ok_electrs, grund = electrs_nach_klaeren_ok(
            rote=nach_electrs["rote"],
            grau=nach_electrs["grau"],
            lot=nach_electrs["lot"],
            offen=nach_electrs["offen"],
        )
        if not ok_electrs:
            raise RuntimeError(grund)
    finally:
        if p2p_client is not None:
            _schliesse_p2p(p2p_client)
        if electrs is not None:
            try:
                electrs.close()
            except Exception:
                pass
    voll = max_traces <= 0
    if max_traces > 0:
        print(
            "  Teilvergleich — P2P bleibt rot, "
            "bis der Lauf ohne --max-traces durch ist.",
            flush=True,
        )
    return {
        "ok": voll,
        "quelle": P2P_QUELLE,
        "name": name,
        "utxos": len(soll),
        "rote_nach_p2p": nach_p2p["rote"],
        "rote_nach_electrs": nach_electrs["rote"],
        "gelb_nach_electrs": len(nach_electrs["gelb"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-traces", type=int, default=0,
        help="höchstens n Herkunftsbäume je Quelle (0 = alle). Teilvergleich bleibt rot.",
    )
    parser.add_argument(
        "--only", default="",
        help="Komma-Liste: own_fulcrum, own_utxo_core, own_core, bip158",
    )
    parser.add_argument("--report", type=Path, default=WORK / "report.json")
    args = parser.parse_args()

    fehl = brauche("bitcoind", "electrs")
    if fehl is not None:
        return fehl
    if not ENV_PATH.is_file():
        print(f"Lab-Env fehlt: {ENV_PATH}", file=sys.stderr)
        return 1
    leere_labor_cache()
    try:
        soll = lade_inventar()
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    basis = _load_env(ENV_PATH)
    # UTXO-Bestand über Compact Filter ist erlaubt. Die Herkunftssperre
    # bleibt; der P2P-Schritt öffnet Sockets nur in dem Discovery-Kontext.
    wollen = geplante_quellen(p2p_an=True)
    if args.only.strip():
        nur = {t.strip() for t in args.only.split(",") if t.strip()}
        wollen = [q for q in wollen if q in nur]
        unbekannt = nur - set(QUELLEN) - {P2P_QUELLE}
        if unbekannt:
            print(f"Unbekannte Quelle: {', '.join(sorted(unbekannt))}", file=sys.stderr)
            return 1
    if not wollen:
        print("Keine Quelle gewählt.", file=sys.stderr)
        return 1

    berichte: list[dict[str, Any]] = []
    rot = 0
    for quelle in wollen:
        try:
            if quelle == P2P_QUELLE:
                ergebnis = _laufe_p2p(
                    basis, soll, max_traces=max(0, args.max_traces),
                )
            else:
                ergebnis = _laufe_quelle(
                    quelle, basis, soll, max_traces=max(0, args.max_traces),
                )
        except Exception as exc:
            rot += 1
            print(
                f"FAIL {_NAMEN.get(quelle, quelle)}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            berichte.append({
                "quelle": quelle,
                "name": _NAMEN.get(quelle, quelle),
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        berichte.append(ergebnis)
        if not ergebnis.get("ok"):
            rot += 1
        print(
            f"{'OK' if ergebnis.get('ok') else 'FAIL'} {ergebnis.get('name')}",
            flush=True,
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps({"ok": rot == 0, "quellen": berichte}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"{'OK' if rot == 0 else 'FAIL'} quellen-inventar "
        f"quellen={len(wollen)} rot={rot}",
        flush=True,
    )
    return 0 if rot == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
