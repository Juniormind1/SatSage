#!/usr/bin/env python3
"""Pseudo-Sanktionslisten und Hop-Ketten für das Regtest-Lab.

Voraussetzung: Basis-Szenarien (`generate_scenarios.py`) haben die Lab-Wallets
Alpha/Beta/Change/Gamma bereits angelegt und befüllt.

Erzeugt:
- Core-Wallets lab-sanctioned / lab-relay / lab-clean-source (NICHT in SatSage WALLET_*)
- Lineare True-Positive-Ketten (1/10/25/100 Hops) + Clean-Ketten
- Pseudo-Liste unter .data/sanctioned_cache/
- Expectations in .data/scenario-report-sanctions.json

Hop-Semantik = analyze.scan_external_sanction_hops: depth=1 am ersten externen
Prevout der Lab-Empfangs-Tx; die gelistete Startadresse liegt bei Hop == N.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Sibling-Imports aus demselben scripts/-Ordner
HERE = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generate_scenarios import (  # noqa: E402
    ENV_PATH,
    LABELS,
    WALLETS,
    Rpc,
    choose_native,
    load_or_create,
    mine,
    new_address,
    raw_spend,
    receive_addresses,
    unspent,
)

SANCTIONS_DIR = HERE / ".data" / "sanctioned_cache"
REPORT_PATH = HERE / ".data" / "scenario-report-sanctions.json"

# Empfangs-Indizes abseits Faucet 0–29 und bestehender Szenarien (~20–45)
SINK_INDEX = {
    "alpha": 80,   # TP hop 1
    "beta": 81,    # TP hop 10
    "change": 82,  # TP hop 25
    "gamma": 83,   # TP hop 100
    "alpha_clean": 84,
    "beta_clean": 85,
    "change_clean": 86,
    "gamma_clean": 87,
    "gamma_cross": 88,  # zusätzliche Hop-1 TP
}

TP_MATRIX = (
    ("alpha", 1),
    ("beta", 10),
    ("change", 25),
    ("gamma", 100),
)
CLEAN_MATRIX = (
    ("alpha", 1),
    ("beta", 10),
    ("change", 25),
    ("gamma", 10),  # 100 clean wäre unnötig teuer; 10 reicht FP-Check
)

# raw_spend legt keinen Change an — Rest = Fee. Deshalb nur winzige Fee lassen,
# sonst trifft Core maxfeerate (Fehler -25).
HOP_FEE_BTC = 0.0001


def _fund_address(rpc: Rpc, address: str, amount: float, faucet_addr: str) -> None:
    rpc.call(
        "sendtoaddress",
        address,
        f"{amount:.8f}",
        wallet="lab-faucet",
    )
    mine(rpc, 1, faucet_addr)


def _utxo_for_address(rpc: Rpc, wallet: str, address: str) -> dict[str, Any]:
    # minconf=0: erlaubt Hop-Ketten mit gebündeltem Mining (Mempool-UTXOs).
    rows = [
        u
        for u in rpc.json("listunspent", "0", "999999", wallet=wallet)
        if u.get("address") == address
    ]
    if not rows:
        raise RuntimeError(f"Kein UTXO für {address} in {wallet}")
    rows.sort(key=lambda row: (-float(row["amount"]), row["txid"], int(row["vout"])))
    return rows[0]


def _fund_for_hops(hops: int, amount: float) -> float:
    """Startbetrag: Zielbetrag + Hop-Fees + Puffer (kein Fee-Burn über maxfeerate)."""
    return round(amount + hops * HOP_FEE_BTC + 0.001, 8)


def build_hop_chain(
    rpc: Rpc,
    *,
    hops: int,
    sink_addr: str,
    start_wallet: str,
    start_addr: str,
    relay_wallet: str,
    faucet_addr: str,
    amount: float,
    name: str,
) -> dict[str, Any]:
    """Baut S→…→Lab mit genau ``hops`` Scan-Hops bis zur Startadresse."""
    if hops < 1:
        raise ValueError("hops >= 1")

    # Start-UTXO sicherstellen
    try:
        current = _utxo_for_address(rpc, start_wallet, start_addr)
    except RuntimeError:
        _fund_address(rpc, start_addr, _fund_for_hops(hops, amount), faucet_addr)
        current = _utxo_for_address(rpc, start_wallet, start_addr)

    current_wallet = start_wallet
    path_addrs = [start_addr]
    hop_txids: list[str] = []

    # hops-1 Intermediate-Schritte, dann final an Sink.
    # Je Schritt: Input − HOP_FEE weiterreichen (kein Change in raw_spend).
    # Mining gebündelt (alle 10 Hops + Final), damit bitcoind bei 100 Hops
    # nicht an Dauer-generatetoaddress stirbt.
    mine_every = 10
    for step in range(hops - 1):
        next_addr = new_address(rpc, relay_wallet)
        path_addrs.append(next_addr)
        send_amt = round(float(current["amount"]) - HOP_FEE_BTC, 8)
        if send_amt <= 0:
            raise RuntimeError(f"{name}: Betrag zu klein bei Hop-Schritt {step}")
        rec = raw_spend(
            rpc,
            f"{name}-hop{step + 1}",
            [current],
            [(next_addr, send_amt)],
            [current_wallet],
        )
        hop_txids.append(rec["txid"])
        if (step + 1) % mine_every == 0:
            mine(rpc, 1, faucet_addr)
        current_wallet = relay_wallet
        current = _utxo_for_address(rpc, relay_wallet, next_addr)

    send_amt = round(float(current["amount"]) - HOP_FEE_BTC, 8)
    if send_amt <= 0:
        raise RuntimeError(f"{name}: Betrag zu klein beim Final-Hop")
    final = raw_spend(
        rpc,
        f"{name}-to-sink",
        [current],
        [(sink_addr, send_amt)],
        [current_wallet],
    )
    hop_txids.append(final["txid"])
    mine(rpc, 1, faucet_addr)

    # Sink-UTXO (Lab-Wallet hält den Output — wir lesen ihn aus der Tx)
    decoded = rpc.json("decoderawtransaction", rpc.call("getrawtransaction", final["txid"]))
    sink_vout = None
    for i, out in enumerate(decoded.get("vout", [])):
        spk = out.get("scriptPubKey") or {}
        addrs = spk.get("addresses") or ([] if not spk.get("address") else [spk["address"]])
        if sink_addr in addrs or spk.get("address") == sink_addr:
            sink_vout = i
            break
    if sink_vout is None:
        raise RuntimeError(f"{name}: Sink-Output nicht in {final['txid']}")

    return {
        "name": name,
        "hops": hops,
        "start_address": start_addr,
        "path_addresses": path_addrs,
        "txids": hop_txids,
        "sink_address": sink_addr,
        "sink_utxo": f"{final['txid']}:{sink_vout}",
        "sink_txid": final["txid"],
        "sink_vout": sink_vout,
        "amount_btc": send_amt,
    }


def write_pseudo_list(addresses: list[str]) -> None:
    SANCTIONS_DIR.mkdir(parents=True, exist_ok=True)
    unique = sorted(set(addresses))
    (SANCTIONS_DIR / "sanctioned_addresses_XBT.json").write_text(
        json.dumps(unique, indent=2) + "\n", encoding="utf-8"
    )
    index = {
        addr: {
            "person": "Lab Pseudo",
            "reason": "regtest controlled sanctioned wallet",
            "sources": ["lab"],
        }
        for addr in unique
    }
    (SANCTIONS_DIR / "sanctioned_address_index.json").write_text(
        json.dumps(index, indent=2) + "\n", encoding="utf-8"
    )
    meta = {
        "updated_at": "lab",
        "lab": True,
        "sources": {"lab": len(unique)},
        "note": "Pseudo-OFAC for regtest; not real sanctions data",
    }
    (SANCTIONS_DIR / "sanctioned_addresses_XBT.meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    (SANCTIONS_DIR / ".meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )


def patch_lab_env() -> None:
    """Hängt Lab-Cap und Hinweis an die bestehende .regtest.env."""
    if not ENV_PATH.is_file():
        raise RuntimeError(f"Lab-Env fehlt: {ENV_PATH} — zuerst generate_scenarios.py")
    text = ENV_PATH.read_text(encoding="utf-8")
    lines = [
        "SANKTION_MAX_HOPS_CAP=100",
        "# Pseudo-Listen unter lab/regtest/.data/sanctioned_cache — GUI mit --sanctions-dir",
    ]
    for line in lines:
        key = line.split("=", 1)[0].lstrip("# ").strip()
        if key and any(
            existing.startswith(key + "=") or existing.startswith("# " + key)
            for existing in text.splitlines()
        ):
            continue
        text = text.rstrip() + "\n" + line + "\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def run(rpc: Rpc) -> dict[str, Any]:
    for wallet in ("lab-faucet", "lab-sanctioned", "lab-relay", "lab-clean-source", *WALLETS):
        load_or_create(rpc, wallet)

    faucet = new_address(rpc, "lab-faucet")
    mine(rpc, 1, faucet)

    addresses = {
        label: receive_addresses(rpc, wallet, 100)
        for label, wallet in zip(LABELS, WALLETS)
    }
    # Lab-Wallets nach Ableitung entladen — weniger I/O während langer Hop-Ketten.
    for wallet in WALLETS:
        try:
            rpc.call("unloadwallet", wallet)
        except RuntimeError:
            pass

    chains: list[dict[str, Any]] = []
    listed: list[str] = []

    def _new_listed_start(hops: int) -> str:
        addr = new_address(rpc, "lab-sanctioned")
        _fund_address(rpc, addr, _fund_for_hops(hops, 0.002), faucet)
        listed.append(addr)
        return addr

    def _new_clean_start(hops: int) -> str:
        addr = new_address(rpc, "lab-clean-source")
        _fund_address(rpc, addr, _fund_for_hops(hops, 0.002), faucet)
        return addr

    for label, hops in TP_MATRIX:
        sanc_addr = _new_listed_start(hops)
        sink = addresses[label][SINK_INDEX[label]]
        chain = build_hop_chain(
            rpc,
            hops=hops,
            sink_addr=sink,
            start_wallet="lab-sanctioned",
            start_addr=sanc_addr,
            relay_wallet="lab-relay",
            faucet_addr=faucet,
            amount=0.002,
            name=f"TP-hop{hops}-{label}",
        )
        chain["kind"] = "true_positive"
        chain["sink_wallet"] = f"Lab {label.title()}"
        chain["expect_hit_at_hops"] = hops
        chain["expect_hit_for_max_hops"] = list(range(hops, 101))
        chain["expect_miss_for_max_hops"] = list(range(1, hops))
        chains.append(chain)

    # Cross-Check: Hop-1 auch an Gamma
    sanc_addr = _new_listed_start(1)
    sink = addresses["gamma"][SINK_INDEX["gamma_cross"]]
    chain = build_hop_chain(
        rpc,
        hops=1,
        sink_addr=sink,
        start_wallet="lab-sanctioned",
        start_addr=sanc_addr,
        relay_wallet="lab-relay",
        faucet_addr=faucet,
        amount=0.002,
        name="TP-hop1-gamma-cross",
    )
    chain["kind"] = "true_positive_cross"
    chain["sink_wallet"] = "Lab Gamma"
    chain["expect_hit_at_hops"] = 1
    chain["expect_hit_for_max_hops"] = list(range(1, 101))
    chain["expect_miss_for_max_hops"] = []
    chains.append(chain)

    for label, hops in CLEAN_MATRIX:
        clean_addr = _new_clean_start(hops)
        sink = addresses[label][SINK_INDEX[f"{label}_clean"]]
        chain = build_hop_chain(
            rpc,
            hops=hops,
            sink_addr=sink,
            start_wallet="lab-clean-source",
            start_addr=clean_addr,
            relay_wallet="lab-relay",
            faucet_addr=faucet,
            amount=0.002,
            name=f"CLEAN-hop{hops}-{label}",
        )
        chain["kind"] = "clean"
        chain["sink_wallet"] = f"Lab {label.title()}"
        chain["expect_hit_at_hops"] = None
        chain["expect_hit_for_max_hops"] = []
        chain["expect_miss_for_max_hops"] = list(range(1, 101))
        chains.append(chain)

    write_pseudo_list(listed)
    patch_lab_env()

    report = {
        "tip_height": int(rpc.call("getblockcount")),
        "sanctions_dir": str(SANCTIONS_DIR),
        "listed_addresses": listed,
        "hop_semantics": (
            "scan_external_sanction_hops depth=1 is first external prevout; "
            "listed start_address appears at hop==N for an N-hop chain"
        ),
        "chains": chains,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "env": str(ENV_PATH),
        "sanctions_dir": str(SANCTIONS_DIR),
        "report": str(REPORT_PATH),
        "tip_height": report["tip_height"],
        "chain_count": len(chains),
        "listed": listed,
    }, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pseudo-Sanktionslisten und Hop-Ketten für das Regtest-Lab."
    )
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    native = choose_native(args.native)
    print(f"Backend: {'native bitcoin-cli' if native else 'Docker Compose'}")
    if args.dry_run:
        return 0
    if not ENV_PATH.is_file():
        print(
            f"Fehler: {ENV_PATH} fehlt — zuerst generate_scenarios.py ausführen.",
            file=sys.stderr,
        )
        return 1
    run(Rpc(native))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        raise SystemExit(1)
