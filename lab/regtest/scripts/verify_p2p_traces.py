#!/usr/bin/env python3
"""Alle Lab-Traces ausschließlich über Bitcoin-P2P (kein Electrs, kein Core-get_tx).

Voraussetzung: Lab-bitcoind mit P2P ``127.0.0.1:18444``, Compact Filter
(``peerblockfilters=1`` + ``blockfilterindex=1``), Szenarien erzeugt.
Electrs wird nicht benutzt.

Suiten:

* origin — BIP-158-Wallet-Scan, danach Herkunft jedes UTXOs
* classify — Tx-Klassifikation der Lab-Formen (Wasabi/Whirlpool/…)
* sanctions — Hop-Ketten gegen die Pseudo-Liste

Der Lauf ist dazu da, P2P-Lücken sichtbar zu machen (Magic, Start-Höhe,
Tx ohne Blockhöhe, Compact Filter). Noch nicht Teil von Q6.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

SCRIPTS = Path(__file__).resolve().parent
HERE = SCRIPTS.parent
REPO = HERE.parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
TXCLASS = HERE / ".data" / "scenario-report-txclass.json"
SANCTIONS = HERE / ".data" / "scenario-report-sanctions.json"
INVENTAR = HERE / ".data" / "herkunft-inventar.json"
SANCTIONS_DIR = HERE / ".data" / "sanctioned_cache"
WORK = HERE / ".data" / "p2p-traces"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))

from infra_check import brauche  # noqa: E402
from herkunft_inventar import (  # noqa: E402
    lade_inventar,
    vergleiche_bestand,
    vergleiche_herkunft,
)

P2P_PEER = "127.0.0.1:18444"


class P2pZaehler:
    """Zählt getcfilters/getdata — Bruteforce und Doppel-Downloads fallen auf."""

    def __init__(self) -> None:
        self.blocks: list[bytes] = []
        self.cfilter_calls = 0
        self.cfilter_expect = 0
        self.tx_getdata = 0

    def install(self, peer) -> None:
        if getattr(peer, "_satsage_zaehler", None) is self:
            return
        orig_b = peer.fetch_block
        orig_c = peer.fetch_cfilters
        orig_t = getattr(peer, "fetch_tx", None)

        def fetch_block(block_hash):
            self.blocks.append(bytes(block_hash))
            return orig_b(block_hash)

        def fetch_cfilters(start_height, stop_hash, *, expect):
            self.cfilter_calls += 1
            self.cfilter_expect += int(expect)
            return orig_c(start_height, stop_hash, expect=expect)

        peer.fetch_block = fetch_block
        peer.fetch_cfilters = fetch_cfilters
        if orig_t is not None:
            def fetch_tx(txid_internal):
                self.tx_getdata += 1
                return orig_t(txid_internal)
            peer.fetch_tx = fetch_tx
        peer._satsage_zaehler = self

    def budgets(self, tip: int) -> list[str]:
        """Leere Liste = ok. Sonst Stockfehler-Texte."""
        tip = max(1, int(tip))
        unique = len(set(self.blocks))
        dups = len(self.blocks) - unique
        rot: list[str] = []
        # Ein Pass über die Kette, plus etwas Chunk-Überhang — nicht Keys×Höhe.
        if self.cfilter_expect > tip * 3 + 1000:
            rot.append(
                f"getcfilters expect={self.cfilter_expect} bei Tip {tip} "
                f"(Budget {tip * 3 + 1000}) — wirkt wie Bruteforce"
            )
        if unique and dups > unique:
            rot.append(
                f"Block-Downloads {len(self.blocks)} bei {unique} Hashes "
                f"({dups} Doppelt) — Session-Cache greift nicht"
            )
        return rot


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


def _kurz_txid(txid: str) -> str:
    t = (txid or "").strip().lower()
    if len(t) < 16:
        return t
    return f"{t[:8]}…{t[-4:]}"


def _hoehe_aus_utxo(utxo: dict) -> int | None:
    status = utxo.get("status") if isinstance(utxo.get("status"), dict) else {}
    for roh in (status.get("block_height"), utxo.get("height"), utxo.get("block_height")):
        try:
            h = int(roh)
        except (TypeError, ValueError):
            continue
        if h > 0:
            return h
    return None


def p2p_env(basis: dict[str, str]) -> dict[str, str]:
    """Isolierte Env: nur P2P, kein Electrs-Host, kein Core-Lookup."""
    out: dict[str, str] = {}
    for key, val in basis.items():
        if key.startswith("WALLET_"):
            out[key] = val
        elif key in ("NETWORK", "STEUER_HALTEFRIST_JAHRE"):
            out[key] = val
    out["NETWORK"] = "regtest"
    out["BIP158_P2P"] = "1"
    out["BIP158_START_HEIGHT"] = "1"
    out["BIP158_PEERS"] = P2P_PEER
    out["OEFFENTLICHE_ELECTRUM"] = "0"
    out["WALLETS_IMMER_AKTUELL"] = "0"
    return out


def bau_client(werte: dict[str, str], cache_dir: Path, imm_dir: Path):
    os.environ["NETWORK"] = "regtest"
    import main as satsage_main
    from core.bip158_scan import verify_p2p_filters
    from core.bip158_wallet import create_bip158_client_from_env

    satsage_main.set_chain_network("regtest")
    client = create_bip158_client_from_env(
        werte,
        start_height=1,
        verbose=False,
        cache_dir=cache_dir,
        immutable_dir=imm_dir,
    )
    tip = verify_p2p_filters(client)
    return client, int(tip)


def bau_get_tx(client, imm_dir: Path) -> Callable[[str], dict]:
    """P2P-only: kein Core, kein Electrs. Tx-Cache vermeidet denselben Block."""
    from core.bip158_wallet import fetch_tx_p2p_mit_fallback
    from core.chain_sources import wrap_get_tx_with_immutable_cache

    def raw(txid: str) -> dict:
        return fetch_tx_p2p_mit_fallback(client, txid)

    return wrap_get_tx_with_immutable_cache(raw, imm_dir, "bip158")


def wrap_scanner(scanner, zaehler: P2pZaehler) -> None:
    orig_peer = scanner._ensure_peer
    orig_peers = scanner._ensure_peers

    def _peer(*args, **kwargs):
        peer = orig_peer(*args, **kwargs)
        zaehler.install(peer)
        return peer

    def _peers(*args, **kwargs):
        peers = orig_peers(*args, **kwargs)
        for peer in peers or []:
            zaehler.install(peer)
        return peers

    scanner._ensure_peer = _peer
    scanner._ensure_peers = _peers


def merke_hoehen(utxos: list[dict]) -> int:
    from core.bip158_wallet import note_tx_height

    n = 0
    for u in utxos:
        txid = str(u.get("txid") or "")
        hoehe = _hoehe_aus_utxo(u)
        if txid and hoehe:
            note_tx_height(txid, hoehe)
            n += 1
    return n


def _utxo_key(txid: str, vout: int) -> str:
    return f"{txid.strip().lower()}:{int(vout)}"


def suite_origin(
    *,
    client,
    get_tx,
    wallets,
    cache_dir: Path,
    max_traces: int,
) -> dict[str, Any]:
    from core.bip158_wallet import fetch_wallet_utxos_bip158
    from core.utxo_origin import trace_utxo_origin
    import main as satsage_main

    xpubs = [w.xpub for w in wallets]
    names = [w.name for w in wallets]
    scripts = [w.script_type for w in wallets]
    maxes = [w.max_addresses for w in wallets]
    ctx = satsage_main.build_wallet_context(
        xpubs,
        wallet_names=names,
        max_addresses_per_xpub=maxes,
        script_types=scripts,
    )
    eigene = set(ctx.address_to_wallet)
    addr_wallet = ctx.address_to_wallet
    try:
        soll = lade_inventar(INVENTAR)
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "utxos": 0, "failed": 1}
    t0 = time.monotonic()
    print("BIP-158-Scan der Lab-Wallets…", flush=True)
    utxos = fetch_wallet_utxos_bip158(
        client,
        xpubs,
        max_addresses=max(maxes) if maxes else 400,
        max_addresses_by_xpub={w.xpub: w.max_addresses for w in wallets},
    )
    n_hint = merke_hoehen(utxos)
    print(
        f"  {len(utxos)} UTXOs gescannt, Inventar {len(soll)}, "
        f"{n_hint} Höhen-Hinweise, {time.monotonic() - t0:.1f}s",
        flush=True,
    )
    gefunden: dict[str, dict] = {}
    for u in utxos:
        txid = str(u.get("txid") or "").lower()
        try:
            vout = int(u.get("vout", 0))
        except (TypeError, ValueError):
            vout = 0
        gefunden[_utxo_key(txid, vout)] = u

    if max_traces > 0:
        # Rauchtest: Teilmenge, aber Bestand bleibt vollständig.
        trace_keys = list(soll)[:max_traces]
    else:
        trace_keys = list(soll)

    ok = fail = 0
    fehlend, extra, faelle = vergleiche_bestand(
        soll, gefunden, addr_wallet=addr_wallet, quelle="P2P",
    )
    fail += len(fehlend) + len(extra)

    for i, key in enumerate(trace_keys, 1):
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
            wallet_ist = addr_wallet.get(u.get("address"))
            if wallet_ist != eintrag["wallet"]:
                raise AssertionError(
                    f"Wallet {wallet_ist} != {eintrag['wallet']}"
                )
            baum = trace_utxo_origin(
                get_tx, txid, vout, eigene, wallet=ctx, cache_dir=cache_dir,
            )
            from herkunft_inventar import _signatur

            diff = vergleiche_herkunft(eintrag["herkunft"], _signatur(baum))
            if diff:
                raise AssertionError(diff)
            dauer = time.monotonic() - start
            ok += 1
            print(
                f"  OK  origin {i}/{len(trace_keys)} {_kurz_txid(txid)}:{vout} "
                f"{eintrag['wallet']} {dauer:.1f}s",
                flush=True,
            )
            faelle.append({
                "txid": _kurz_txid(txid), "vout": vout, "ok": True,
                "wallet": eintrag["wallet"], "seconds": round(dauer, 2),
            })
        except Exception as exc:
            dauer = time.monotonic() - start
            fail += 1
            print(
                f"  FAIL origin {i}/{len(trace_keys)} {_kurz_txid(txid)}:{vout} "
                f"{type(exc).__name__}: {exc} {dauer:.1f}s",
                flush=True,
            )
            faelle.append({
                "txid": _kurz_txid(txid), "vout": vout, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(dauer, 2),
            })
    vollstaendig = (
        max_traces <= 0
        and not fehlend
        and not extra
        and fail == 0
        and ok == len(soll)
    )
    if max_traces > 0:
        print(
            f"  Teilvergleich {ok}/{len(trace_keys)} — "
            "Suite bleibt rot, bis alle Inventar-UTXOs verglichen sind.",
            flush=True,
        )
    return {
        "ok": vollstaendig,
        "traced": ok,
        "failed": fail,
        "utxos": len(gefunden),
        "inventar": len(soll),
        "missing": len(fehlend),
        "extra": len(extra),
        "height_hints": n_hint,
        "cases": faelle,
    }


def suite_classify(*, get_tx, wallets) -> dict[str, Any]:
    from core.tx_classify import classify_tx
    import main as satsage_main

    if not TXCLASS.is_file():
        return {"ok": False, "error": f"Report fehlt: {TXCLASS}"}
    report = json.loads(TXCLASS.read_text(encoding="utf-8"))
    xpubs = [w.xpub for w in wallets]
    names = [w.name for w in wallets]
    scripts = [w.script_type for w in wallets]
    maxes = [w.max_addresses for w in wallets]
    ctx = satsage_main.build_wallet_context(
        xpubs,
        wallet_names=names,
        max_addresses_per_xpub=maxes,
        script_types=scripts,
    )
    addrs_by_wallet: dict[str, set[str]] = {}
    for addr, wname in ctx.address_to_wallet.items():
        addrs_by_wallet.setdefault(wname, set()).add(addr)
    viewer_name = {
        "lab-alpha": "Lab Alpha",
        "lab-beta": "Lab Beta",
        "lab-change": "Lab Change",
        "lab-gamma": "Lab Gamma",
    }
    eigene = set(ctx.address_to_wallet)
    ok = fail = 0
    faelle: list[dict[str, Any]] = []
    for case in report.get("cases") or []:
        name = case.get("name") or "?"
        txid = case.get("txid") or ""
        expected = case.get("expected_kind")
        try:
            tx = get_tx(txid)
            vw = case.get("viewer_wallet") or ""
            wlabel = viewer_name.get(vw)
            own = set(addrs_by_wallet[wlabel]) if wlabel in addrs_by_wallet else set(eigene)
            result = classify_tx(tx, own, wallet=None, get_tx=get_tx)
            treffer = result.kind == expected
            if not treffer and expected == "wasabi_classic" and result.kind == "coinjoin":
                treffer = True
            if treffer:
                ok += 1
                print(f"  OK  classify {name}: {result.kind}", flush=True)
            else:
                fail += 1
                print(
                    f"  FAIL classify {name}: expected={expected} got={result.kind}",
                    flush=True,
                )
            faelle.append({
                "name": name, "ok": treffer,
                "expected": expected, "got": result.kind,
            })
        except Exception as exc:
            fail += 1
            print(f"  FAIL classify {name}: {type(exc).__name__}: {exc}", flush=True)
            faelle.append({
                "name": name, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return {
        "ok": fail == 0 and ok > 0,
        "passed": ok,
        "failed": fail,
        "cases": faelle,
    }


def suite_sanctions(*, get_tx, depths: list[int]) -> dict[str, Any]:
    from analyze import check_wallet_utxos_sanctions
    from sanctioned import load_sanctioned_xbt_addresses

    if not SANCTIONS.is_file():
        return {"ok": False, "error": f"Report fehlt: {SANCTIONS}"}
    listed, _meta = load_sanctioned_xbt_addresses(cache_dir=SANCTIONS_DIR)
    if not listed:
        return {"ok": False, "error": "Pseudo-Liste leer"}
    report = json.loads(SANCTIONS.read_text(encoding="utf-8"))
    ok = fail = 0
    faelle: list[dict[str, Any]] = []
    for chain in report.get("chains") or []:
        utxo = {
            "txid": chain["sink_txid"],
            "vout": int(chain["sink_vout"]),
            "address": chain["sink_address"],
            "value_sats": int(round(float(chain.get("amount_btc", 0)) * 1e8)),
            "key": chain["sink_utxo"],
        }
        hoehe = chain.get("sink_height") or chain.get("height")
        if hoehe:
            from core.bip158_wallet import note_tx_height
            note_tx_height(chain["sink_txid"], int(hoehe))
        expect_at = chain.get("expect_hit_at_hops")
        start = chain["start_address"]
        for depth in depths:
            try:
                hits, checked, _abort, _coinjoins = check_wallet_utxos_sanctions(
                    get_tx,
                    [utxo],
                    set(),
                    listed,
                    max_hops=depth,
                    abort_on_hit=False,
                )
                hit_addrs = {h["address"] for h in hits}
                should_hit = expect_at is not None and depth >= int(expect_at)
                got_hit = start in hit_addrs
                treffer = got_hit is should_hit
                if treffer:
                    ok += 1
                else:
                    fail += 1
                print(
                    f"  {'OK' if treffer else 'FAIL'} sanctions {chain['name']} "
                    f"max_hops={depth} expect_hit={should_hit} got={got_hit} "
                    f"checked={checked}",
                    flush=True,
                )
                faelle.append({
                    "name": chain["name"], "depth": depth, "ok": treffer,
                    "expect_hit": should_hit, "got_hit": got_hit,
                    "checked": checked,
                })
            except Exception as exc:
                fail += 1
                print(
                    f"  FAIL sanctions {chain['name']} max_hops={depth} "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                faelle.append({
                    "name": chain["name"], "depth": depth, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })
    return {
        "ok": fail == 0 and ok > 0,
        "passed": ok,
        "failed": fail,
        "cases": faelle,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        default="origin,classify,sanctions,economy",
        help="Komma: origin, classify, sanctions, economy",
    )
    parser.add_argument("--max-traces", type=int, default=0,
                        help="origin: höchstens n UTXOs (0 = alle)")
    parser.add_argument("--depths", default="1,3,10",
                        help="sanctions: Hop-Tiefen")
    parser.add_argument("--report", type=Path, default=WORK / "report.json")
    args = parser.parse_args()

    fehl = brauche("bitcoind", "p2p")
    if fehl is not None:
        return fehl
    if not ENV_PATH.is_file():
        print(f"Lab-Env fehlt: {ENV_PATH}", file=sys.stderr)
        print("Zuerst generate_scenarios.py.", file=sys.stderr)
        return 1

    basis = _load_env(ENV_PATH)
    werte = p2p_env(basis)
    for k, v in werte.items():
        os.environ[k] = v

    WORK.mkdir(parents=True, exist_ok=True)
    cache_dir = WORK / "utxo_cache"
    imm_dir = WORK / "immutable_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    imm_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("NETWORK", "regtest")
    import main as satsage_main
    from core.bip158_wallet import clear_tx_height_hints
    from core.config import EnvFile, read_wallets

    satsage_main.set_chain_network("regtest")
    clear_tx_height_hints()

    env_file = EnvFile.load(ENV_PATH)
    wallets = read_wallets(env_file)
    if not wallets:
        print("Keine WALLET_* in Lab-Env", file=sys.stderr)
        return 1

    print(f"P2P-only Peer {P2P_PEER}, Start-Höhe 1, kein Electrs, kein Core-get_tx", flush=True)
    try:
        client, peer_h = bau_client(werte, cache_dir, imm_dir)
    except SystemExit as exc:
        print(f"P2P-Handshake fehlgeschlagen: {exc}", file=sys.stderr)
        print(
            "Labor-Node: peerblockfilters=1 und Port 18444 erreichbar. "
            "P2P-Magic/Genesis im Client müssen Regtest sein "
            "(nicht Mainnet f9beb4d9 / Höhe 481824).",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"P2P-Client: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "Häufig: Mainnet-Magic gegen Regtest-Node, Compact Filter aus, "
            "oder Start-Höhe 481824 auf einer kurzen Kette.",
            file=sys.stderr,
        )
        return 1
    print(f"Compact-Filter-Peer verbunden (start_height={peer_h})", flush=True)
    if int(getattr(client, "start_height", 0) or 0) >= 481_824:
        print(
            "Start-Höhe ist Mainnet-SegWit — Lab-Kette wird übersprungen.",
            file=sys.stderr,
        )
        return 1
    zaehler = P2pZaehler()
    wrap_scanner(client.scanner, zaehler)
    get_tx = bau_get_tx(client, imm_dir)

    suiten = [s.strip() for s in args.suite.split(",") if s.strip()]
    depths = [int(x) for x in args.depths.split(",") if x.strip()]
    ergebnisse: dict[str, Any] = {}
    rot = 0
    try:
        if "origin" in suiten:
            print("→ origin", flush=True)
            ergebnisse["origin"] = suite_origin(
                client=client, get_tx=get_tx, wallets=wallets,
                cache_dir=cache_dir, max_traces=max(0, args.max_traces),
            )
            if not ergebnisse["origin"].get("ok"):
                rot += 1
        if "classify" in suiten:
            print("→ classify", flush=True)
            ergebnisse["classify"] = suite_classify(get_tx=get_tx, wallets=wallets)
            if not ergebnisse["classify"].get("ok"):
                rot += 1
        if "sanctions" in suiten:
            print("→ sanctions", flush=True)
            ergebnisse["sanctions"] = suite_sanctions(get_tx=get_tx, depths=depths)
            if not ergebnisse["sanctions"].get("ok"):
                rot += 1
        if "economy" in suiten:
            print("→ economy", flush=True)
            from core.bip158_scan import plane_filter_passes

            alle = {bytes([i]) for i in range(1, 80)}
            gap = {bytes([i]) for i in range(1, 5)}
            passe = plane_filter_passes(
                481_824, 900_000, alle, set(), gap_scripts=gap,
            )
            histo = [p for p in passe if p[0] == "historie"]
            turbo_ok = bool(histo) and histo[0][3] == frozenset(gap)
            stock = zaehler.budgets(peer_h)
            if not turbo_ok:
                stock.append("Erstscan-Historie trägt alle Lookahead-Keys")
            ok_e = not stock
            for zeile in stock:
                print(f"  FAIL economy {zeile}", flush=True)
            if ok_e:
                print(
                    f"  OK  economy cfilters expect={zaehler.cfilter_expect} "
                    f"calls={zaehler.cfilter_calls} blocks={len(zaehler.blocks)} "
                    f"unique={len(set(zaehler.blocks))} getdata_tx={zaehler.tx_getdata}",
                    flush=True,
                )
            ergebnisse["economy"] = {
                "ok": ok_e,
                "cfilter_expect": zaehler.cfilter_expect,
                "cfilter_calls": zaehler.cfilter_calls,
                "blocks": len(zaehler.blocks),
                "unique_blocks": len(set(zaehler.blocks)),
                "tx_getdata": zaehler.tx_getdata,
                "errors": stock,
            }
            if not ok_e:
                rot += 1
    finally:
        try:
            client.scanner.close()
        except Exception:
            pass

    report = {"ok": rot == 0, "failed_suites": rot, "suites": ergebnisse}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Report: {args.report}", flush=True)
    return 0 if rot == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
