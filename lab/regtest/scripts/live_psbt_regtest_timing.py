#!/usr/bin/env python3
"""Pfad R — Regtest Live-PSBT: selbst bauen, signieren, broadcasten, Timing messen."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from embit import bip32, networks, script
from embit.psbt import PSBT
from embit.script import address_to_scriptpubkey

NET = networks.NETWORKS["regtest"]
ELECTRS = ("127.0.0.1", 50001)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lab-root", type=Path, default=Path("/workspace/satsage-lab"))
    p.add_argument("--repo", type=Path, default=Path("/workspace/xPubQuery"))
    p.add_argument("--amount-btc", type=float, default=0.0001)
    p.add_argument("--poll-ms", type=int, default=250)
    p.add_argument("--timeout-s", type=float, default=45.0)
    p.add_argument(
        "--report",
        type=Path,
        default=Path("/workspace/xPubQuery/tmp/live-timing-regtest.json"),
    )
    p.add_argument("--no-mine", action="store_true")
    p.add_argument(
        "--after-mine",
        choices=("tip-sync", "rescan-beta", "none"),
        default="tip-sync",
    )
    return p.parse_args()


def load_secrets(lab: Path):
    files = {
        "alpha": lab / "secrets/lab-bip84-secrets.txt",
        "beta": lab / "secrets/lab-beta-secrets.txt",
    }
    accounts, addrs = {}, {}
    for label, path in files.items():
        kv = {}
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        root = bip32.HDKey.from_seed(bytes.fromhex(kv["seed_hex"]), NET["xprv"])
        accounts[label] = root.derive("m/84h/1h/0h")
        addrs[label] = [
            script.p2wpkh(
                accounts[label].derive(f"m/0/{i}").get_public_key()
            ).address(NET)
            for i in range(40)
        ]
    return accounts, addrs


def rpc(lab: Path, *args, wallet=None):
    cli = str(lab / "bin/bitcoin-cli")
    conf = str(lab / "bitcoin/bitcoin.conf")
    cmd = [cli, f"-conf={conf}", "-regtest"]
    if wallet:
        cmd.append(f"-rpcwallet={wallet}")
    cmd += [str(a) for a in args]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"rpc {args}: {p.stderr or p.stdout}")
    return p.stdout.strip()


def session(repo: Path):
    candidates = []
    sf = repo / "tmp/satsage-gui-session.json"
    if sf.exists():
        try:
            candidates.append(json.loads(sf.read_text()))
        except Exception:
            pass
    log = Path("/workspace/satsage-lab/logs/satsage-web.log")
    if log.exists():
        ms = list(re.finditer(r"SATSAGE_SESSION (\{.*\})", log.read_text()))
        if ms:
            try:
                candidates.append(json.loads(ms[-1].group(1)))
            except Exception:
                pass
    if not candidates:
        raise RuntimeError("Keine SatSage-Session — Server starten")
    candidates.sort(key=lambda c: float(c.get("ts") or 0), reverse=True)
    return candidates[0]


def api(sess, path, method="GET", data=None, timeout=30):
    body = None
    headers = {"X-Satsage-Token": sess["token"]}
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    url = f"http://{sess['bind']}:{sess['port']}{path}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as ant:
            return ant.status, json.loads(ant.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:500]}


def electrs_has_history(addr: str) -> bool:
    spk = address_to_scriptpubkey(addr).data
    sh = hashlib.sha256(spk).digest()[::-1].hex()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "blockchain.scripthash.get_history",
        "params": [sh],
    }
    s = socket.create_connection(ELECTRS, timeout=5)
    try:
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    return bool((json.loads(buf.decode()).get("result") or []))


def next_free_index(addrs, label):
    for i, addr in enumerate(addrs[label]):
        if not electrs_has_history(addr):
            return i, addr
    raise RuntimeError(f"Keine freie Empfangsadresse für {label}")


def find_input(lab, addrs, amount_btc):
    utxos = json.loads(
        rpc(lab, "listunspent", "1", "9999999", wallet="satsage-watch")
    )
    alpha_set = set(addrs["alpha"])
    rows = [u for u in utxos if u.get("address") in alpha_set]
    rows.sort(key=lambda u: (u["amount"], u["txid"], u["vout"]))
    for u in rows:
        if u["amount"] + 1e-8 >= amount_btc + 0.00001:
            return u
    if not rows:
        raise RuntimeError("Keine Alpha-UTXOs")
    return rows[-1]


def snapshot_utxo_views(sess, alpha_id, beta_id):
    views = {}
    for key, path in (
        ("alpha", f"/api/wallets/{alpha_id}/utxos"),
        ("beta", f"/api/wallets/{beta_id}/utxos"),
        ("all", "/api/utxos"),
        ("config", "/api/config"),
    ):
        code, data = api(sess, path)
        views[key] = {"http": code, "data": data}
    return views


def summarize(views, txid=None):
    def flags(utxos):
        spending = [u for u in utxos if u.get("spending_pending")]
        receiving = [u for u in utxos if u.get("receive_pending")]
        by_txid = [
            u
            for u in utxos
            if txid and str(u.get("txid", "")).lower() == txid.lower()
        ]
        return {
            "n": len(utxos),
            "spending_pending": len(spending),
            "receive_pending": len(receiving),
            "txid_hits": len(by_txid),
            "txid_pending_recv": sum(
                1 for u in by_txid if u.get("receive_pending")
            ),
            "txid_pending_spend": sum(
                1 for u in by_txid if u.get("spending_pending")
            ),
            "txid_confirmed": sum(
                1
                for u in by_txid
                if not u.get("receive_pending") and not u.get("spending_pending")
            ),
        }

    alpha = views["alpha"]["data"]
    beta = views["beta"]["data"]
    alle = views["all"]["data"]
    cfg = views["config"]["data"]
    wallets = {w["name"]: w for w in cfg.get("wallets", [])}
    return {
        "alpha_api": flags(alpha.get("utxos") or []),
        "beta_api": flags(beta.get("utxos") or []),
        "all_api": flags(alle.get("utxos") or []),
        "config": {
            name: {"utxo": w.get("utxo_count"), "sats": w.get("total_sats")}
            for name, w in wallets.items()
            if name in ("Lab Alpha", "Lab Beta")
        },
    }


def build_sign_broadcast(lab, accounts, addrs, amount_btc):
    vin = find_input(lab, addrs, amount_btc)
    recv_i, recv_addr = next_free_index(addrs, "beta")
    ch_i, ch_addr = next_free_index(addrs, "alpha")
    fee = 0.00001
    send = float(f"{amount_btc:.8f}")
    change = float(f"{(vin['amount'] - send - fee):.8f}")
    if change < 0:
        raise RuntimeError(f"Input zu klein: {vin['amount']}")

    in_json = json.dumps(
        [{"txid": vin["txid"], "vout": vin["vout"]}], separators=(",", ":")
    )
    outs = [{recv_addr: send}]
    if change > 0:
        outs.append({ch_addr: change})
    out_json = json.dumps(outs, separators=(",", ":"))

    raw_psbt = rpc(lab, "createpsbt", in_json, out_json)
    updated = json.loads(
        rpc(lab, "walletprocesspsbt", raw_psbt, wallet="satsage-watch")
    )["psbt"]
    psbt = PSBT.from_string(updated)
    if psbt.sign_with(accounts["alpha"]) < 1:
        raise RuntimeError("Signatur fehlgeschlagen")
    finalized = json.loads(rpc(lab, "finalizepsbt", psbt.to_string()))
    if not finalized.get("complete"):
        raise RuntimeError("PSBT nicht final")
    hex_tx = finalized["hex"]
    accept = json.loads(rpc(lab, "testmempoolaccept", json.dumps([hex_tx])))
    if not accept or not accept[0].get("allowed"):
        raise RuntimeError(f"testmempoolaccept: {accept}")

    t0 = time.time()
    txid = rpc(lab, "sendrawtransaction", hex_tx)
    return {
        "t0": t0,
        "txid": txid,
        "vin": vin,
        "send_btc": send,
        "change_btc": change,
        "recv_addr": recv_addr,
        "recv_index": recv_i,
        "change_addr": ch_addr,
        "change_index": ch_i,
        "accept": accept[0],
    }


def wait_until(pred, timeout_s, poll_ms):
    t_start = time.time()
    samples = []
    while True:
        now = time.time()
        ok, detail = pred()
        samples.append(
            {"t": now, "dt_ms": round((now - t_start) * 1000), "ok": ok, "detail": detail}
        )
        if ok:
            return True, now, samples
        if now - t_start > timeout_s:
            return False, now, samples
        time.sleep(poll_ms / 1000.0)


def main():
    args = parse_args()
    lab, repo = args.lab_root, args.repo
    accounts, addrs = load_secrets(lab)
    tip = int(json.loads(rpc(lab, "getblockchaininfo"))["blocks"])
    sess = session(repo)
    code, cfg = api(sess, "/api/config")
    if code != 200:
        raise SystemExit(f"config {code}: {cfg}")
    by_name = {w["name"]: w for w in cfg["wallets"]}
    alpha, beta = by_name["Lab Alpha"], by_name["Lab Beta"]

    before = summarize(snapshot_utxo_views(sess, alpha["id"], beta["id"]))
    built = build_sign_broadcast(lab, accounts, addrs, args.amount_btc)
    txid, t0 = built["txid"], built["t0"]

    def mempool_pred():
        s = summarize(snapshot_utxo_views(sess, alpha["id"], beta["id"]), txid)
        ok = (
            s["alpha_api"]["spending_pending"] > 0
            or s["beta_api"]["receive_pending"] > 0
            or s["all_api"]["spending_pending"] > 0
            or s["all_api"]["receive_pending"] > 0
        )
        return ok, s

    ok1, t1, samples1 = wait_until(mempool_pred, args.timeout_s, args.poll_ms)

    mined = None
    tip_sync = None
    rescan = None
    ok2, t2, samples2 = False, None, []
    after_mine_sum = None
    code_ts = None

    if not args.no_mine:
        mined = {
            "t_mine": time.time(),
            "hashes": json.loads(
                rpc(
                    lab,
                    "generatetoaddress",
                    "1",
                    "bcrt1qyg98racuakcl2tj6srphcjemhmsgxeheaffpnf",
                    wallet="satsage-lab",
                )
            ),
        }
        if args.after_mine == "tip-sync":
            code_ts, tip_sync = api(sess, "/api/jobs/wallet-sync", "POST", {})
        elif args.after_mine == "rescan-beta":
            code_ts, rescan = api(
                sess, "/api/jobs/rescan", "POST", {"wallet_id": beta["id"]}
            )

        beta0 = before["config"]["Lab Beta"]["utxo"]
        alpha0 = before["config"]["Lab Alpha"]["utxo"]

        def conf_pred():
            views = snapshot_utxo_views(sess, alpha["id"], beta["id"])
            s = summarize(views, txid)
            pending_gone = (
                s["all_api"]["spending_pending"] == 0
                and s["all_api"]["receive_pending"] == 0
            )
            beta_utxos = views["beta"]["data"].get("utxos") or []
            confirmed_recv = any(
                str(u.get("txid", "")).lower() == txid.lower()
                and not u.get("receive_pending")
                for u in beta_utxos
            )
            cfg_moved = (
                s["config"]["Lab Beta"]["utxo"] != beta0
                or s["config"]["Lab Alpha"]["utxo"] != alpha0
            )
            return pending_gone and (confirmed_recv or cfg_moved), s

        ok2, t2, samples2 = wait_until(conf_pred, args.timeout_s, args.poll_ms)
        after_mine_sum = samples2[-1]["detail"] if samples2 else None

    report = {
        "path": "R-regtest-bot",
        "tip_before": tip,
        "amount_btc": args.amount_btc,
        "built": built,
        "before": before,
        "mempool": {
            "ok": ok1,
            "t0": t0,
            "t1": t1,
            "dt_ms": None if t1 is None else round((t1 - t0) * 1000),
            "samples": samples1[-8:],
            "sample_count": len(samples1),
        },
        "mine": mined,
        "after_mine_action": args.after_mine,
        "tip_sync_post": {"http": code_ts, "body": tip_sync or rescan},
        "confirmed": {
            "ok": ok2,
            "t2": t2,
            "dt_from_t0_ms": None if t2 is None else round((t2 - t0) * 1000),
            "dt_from_mine_ms": None
            if (t2 is None or not mined)
            else round((t2 - mined["t_mine"]) * 1000),
            "samples": samples2[-8:],
            "sample_count": len(samples2),
            "final": after_mine_sum,
        },
        "views_checked": [
            "GET /api/wallets/{id}/utxos",
            "GET /api/utxos",
            "GET /api/config",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "report": str(args.report),
                "txid": txid,
                "recv_index": built["recv_index"],
                "mempool_ok": ok1,
                "mempool_ms": report["mempool"]["dt_ms"],
                "confirmed_ok": ok2,
                "confirmed_ms_from_mine": report["confirmed"]["dt_from_mine_ms"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok1 and (args.no_mine or ok2) else 2


if __name__ == "__main__":
    sys.exit(main())
