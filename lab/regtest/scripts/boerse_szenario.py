#!/usr/bin/env python3
"""Regtest-Szenario: Börse zahlt an ein eigenes Empfangswallet.

Voraussetzung: ``generate_scenarios.py`` hat ``lab-faucet`` und die Lab-Env
angelegt. Dieses Skript legt drei Core-Wallets an, die **nicht** in
``WALLET_*`` stehen, damit das Herkunfts-Inventar unverändert bleibt:

- ``lab-boerse`` sendet die Auszahlungen (Mittel kommen vom Faucet)
- ``lab-boerse-empfang`` ist das Ziel der eigenen Ausgänge
- ``lab-boerse-fremd`` liefert drei fremde Adressen für die Sammel-Tx

Erzeugt eine Sammelauszahlung (zwei eigene, drei fremde Ausgänge) und
eine Einzelauszahlung. Dazu synthetische CSVs: Strike mit der echten
Regtest-TxID der Sammel-Tx, Kraken-Ledger ohne TxID zur Einzelauszahlung.

Zeiten über ``setmocktime``, wie ``generate_scenarios.py``. Nur Regtest.
Bericht: ``.data/scenario-report-boerse.json``. CSVs unter ``.data/boerse/``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generate_scenarios import (  # noqa: E402
    ENV_PATH,
    Rpc,
    _blockzeit,
    _outs_der_tx,
    _sats_betrag,
    choose_native,
    load_or_create,
    mine,
    new_address,
    public_receive_key,
    receive_addresses,
    rescan_wallets,
    set_time,
    unspent,
)

BOERSE_WALLET = "lab-boerse"
EMPFANG_WALLET = "lab-boerse-empfang"
FREMD_WALLET = "lab-boerse-fremd"
REPORT = HERE / ".data" / "scenario-report-boerse.json"
CSV_DIR = HERE / ".data" / "boerse"

BATCH_INDIZES = (0, 1)
EINZEL_INDEX = 2
BATCH_SATS = (110_000, 120_000)
EINZEL_SATS = 130_000
FREMD_SATS = (14_000, 15_000, 16_000)
FAUCET_FUND_SATS = 1_000_000
CSV_VORLAUF_S = 600
_MONATE = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _nur_regtest(rpc: Rpc) -> dict[str, Any]:
    info = rpc.json("getblockchaininfo")
    chain = str(info.get("chain") or "")
    if chain != "regtest":
        raise RuntimeError(
            f"Abbruch: Kette ist '{chain}', nicht Regtest. Mainnet nie."
        )
    return info


def _kette_an_hostuhr(rpc: Rpc) -> int:
    """Tip auf die Host-Uhr ziehen, ohne Mocktime in der Zukunft."""
    info = _nur_regtest(rpc)
    tip = str(info.get("bestblockhash") or "")
    header = rpc.json("getblockheader", tip) if tip else {}
    tip_zeit = int(header.get("time") or info.get("mediantime") or 0)
    jetzt = int(time.time())
    if tip_zeit >= jetzt - 120:
        return tip_zeit
    load_or_create(rpc, "lab-faucet")
    adresse = new_address(rpc, "lab-faucet")
    set_time(rpc, jetzt)
    mine(rpc, 1, adresse)
    set_time(rpc, 0)
    neu = rpc.json("getblockheader", rpc.json("getblockchaininfo")["bestblockhash"])
    return int(neu.get("time") or jetzt)


def _sendmany(rpc: Rpc, payouts: dict[str, int], *, wallet: str) -> str:
    teile = [
        f"{json.dumps(addr)}:{sats / 1e8:.8f}"
        for addr, sats in payouts.items()
    ]
    return rpc.call(
        "sendmany", "", "{" + ",".join(teile) + "}", wallet=wallet,
    )


def _btc(sats: int) -> str:
    return f"{sats / 1e8:.8f}"


def kraken_zeit(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.0000"
    )


def strike_zeit(ts: int) -> str:
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return (
        f"{_MONATE[dt.month - 1]} {dt.day:02d} {dt.year} "
        f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
    )


def baue_kraken_ledger(
    *,
    amount_sats: int,
    fee_sats: int,
    buchung_ts: int,
    row_id: str = "LSYN07-LAB00-000004",
    trade_id: str = "TSYN07-LAB00-000001",
) -> str:
    """Synthetisches Ledger: Fiat-Eingang, Kauf, Auszahlung ohne TxID."""
    kopf = (
        '"txid","refid","time","type","subtype","aclass","asset",'
        '"wallet","amount","fee","balance"'
    )
    t_ein = kraken_zeit(buchung_ts - 86400 * 30)
    t_kauf = kraken_zeit(buchung_ts - 86400 * 10)
    t_aus = kraken_zeit(buchung_ts)
    btc = _btc(amount_sats)
    fee = _btc(fee_sats)
    zeilen = [
        kopf,
        f'"LSYN07-LAB00-000001","","{t_ein}","deposit","","currency","ZEUR",'
        f'"spot / main","2000.0000","0.0000","2000.0000"',
        f'"LSYN07-LAB00-000002","{trade_id}","{t_kauf}","trade","","currency",'
        f'"ZEUR","spot / main","-650.0000","1.2500","1348.7500"',
        f'"LSYN07-LAB00-000003","{trade_id}","{t_kauf}","trade","","currency",'
        f'"XXBT","spot / main","{btc}","0.00000000","{btc}"',
        f'"{row_id}","","{t_aus}","withdrawal","","currency","XXBT",'
        f'"spot / main","-{btc}","{fee}","0.00000000"',
    ]
    return "\n".join(zeilen) + "\n"


def baue_strike_sends(
    *,
    sends: list[dict[str, Any]],
    buchung_ts: int,
) -> str:
    """Synthetisches Strike-Statement mit On-Chain-Sends (echte TxID erlaubt)."""
    kopf = (
        "Reference,Date & Time (UTC),Transaction Type,Amount EUR,Fee EUR,"
        "Amount BTC,Fee BTC,BTC Price,Cost Basis (EUR),Destination,"
        "Description,Transaction Hash,Note"
    )
    t_ein = strike_zeit(buchung_ts - 86400 * 30)
    t_kauf = strike_zeit(buchung_ts - 86400 * 10)
    t_aus = strike_zeit(buchung_ts)
    zeilen = [
        kopf,
        f"STSYN07-0001,{t_ein},Deposit,2000.00,0.00,-,-,-,-,-,Fiat deposit,-,",
        f"STSYN07-0002,{t_kauf},Purchase,-650.00,1.25,0.00230000,0.00000000,"
        f"28260.87,650.00,-,Bought BTC,-,",
    ]
    for i, send in enumerate(sends, start=3):
        btc = _btc(int(send["sats"]))
        fee = _btc(int(send.get("fee_sats") or 10_000))
        dest = send["adresse"]
        txid = send.get("txid") or "-"
        ref = send.get("ref") or f"STSYN07-000{i}"
        zeilen.append(
            f"{ref},{t_aus},Send,-,-,-{btc},{fee},-,-,{dest},"
            f"On-chain withdrawal,{txid},"
        )
    return "\n".join(zeilen) + "\n"


def _bestehende_auszahlung(rpc: Rpc, wallet: str, adresse: str, sats: int) -> dict[str, Any] | None:
    try:
        rows = [
            u for u in unspent(rpc, wallet)
            if u.get("address") == adresse and _sats_betrag(u.get("amount") or 0) == sats
        ]
    except RuntimeError:
        return None
    if not rows:
        return None
    u = rows[0]
    txid = str(u["txid"]).lower()
    return {
        "txid": txid,
        "vout": int(u["vout"]),
        "amount_sats": sats,
        "address": adresse,
        "block_time": _blockzeit(rpc, txid),
    }


def _zahle(
    rpc: Rpc,
    faucet: str,
    payouts: dict[str, int],
    *,
    ts: int,
) -> dict[str, dict[str, Any]]:
    set_time(rpc, ts)
    rescan_wallets(rpc, BOERSE_WALLET, "lab-faucet")
    txid = _sendmany(rpc, payouts, wallet=BOERSE_WALLET)
    mine(rpc, 1, faucet)
    gefunden = _outs_der_tx(rpc, txid, payouts)
    block_time = _blockzeit(rpc, txid)
    for row in gefunden.values():
        row["block_time"] = block_time
    return gefunden


def run(rpc: Rpc) -> dict[str, Any]:
    if not ENV_PATH.is_file():
        raise RuntimeError(f"Lab-Env fehlt: {ENV_PATH} — zuerst generate_scenarios.py")
    _nur_regtest(rpc)
    tip_zeit = _kette_an_hostuhr(rpc)
    start_ts = max(tip_zeit + 120, int(time.time()) - 60)

    for w in ("lab-faucet", BOERSE_WALLET, EMPFANG_WALLET, FREMD_WALLET):
        load_or_create(rpc, w)

    empfang_addrs = receive_addresses(rpc, EMPFANG_WALLET, EINZEL_INDEX + 1)
    fremd_addrs = receive_addresses(rpc, FREMD_WALLET, len(FREMD_SATS))
    boerse_addr = new_address(rpc, BOERSE_WALLET)
    xpub, script = public_receive_key(rpc, EMPFANG_WALLET)

    eigen_batch = {
        empfang_addrs[i]: BATCH_SATS[j]
        for j, i in enumerate(BATCH_INDIZES)
    }
    eigen_einzel = {empfang_addrs[EINZEL_INDEX]: EINZEL_SATS}
    fremd = {fremd_addrs[i]: FREMD_SATS[i] for i in range(len(FREMD_SATS))}

    rescan_wallets(rpc, EMPFANG_WALLET, BOERSE_WALLET, "lab-faucet")
    batch_ist = [
        _bestehende_auszahlung(rpc, EMPFANG_WALLET, addr, sats)
        for addr, sats in eigen_batch.items()
    ]
    einzel_ist = _bestehende_auszahlung(
        rpc, EMPFANG_WALLET, empfang_addrs[EINZEL_INDEX], EINZEL_SATS,
    )
    neu = not (all(batch_ist) and einzel_ist)

    faucet = new_address(rpc, "lab-faucet")
    if neu:
        set_time(rpc, start_ts)
        _sendmany(rpc, {boerse_addr: FAUCET_FUND_SATS}, wallet="lab-faucet")
        mine(rpc, 1, faucet)
        # Ein Block von der Börse selbst, die Coinbase bleibt unreif.
        mine(rpc, 1, boerse_addr)
        rescan_wallets(rpc, BOERSE_WALLET)

        buendel_payouts = dict(eigen_batch)
        buendel_payouts.update(fremd)
        buendel_outs = _zahle(rpc, faucet, buendel_payouts, ts=start_ts + 180)
        einzel_outs = _zahle(rpc, faucet, eigen_einzel, ts=start_ts + 300)
        set_time(rpc, 0)
    else:
        buendel_txid = str(batch_ist[0]["txid"])
        buendel_outs = {}
        wanted = dict(eigen_batch)
        wanted.update(fremd)
        buendel_outs.update(_outs_der_tx(rpc, buendel_txid, wanted))
        block_time = _blockzeit(rpc, buendel_txid)
        for row in buendel_outs.values():
            row["block_time"] = block_time
        einzel_outs = {
            empfang_addrs[EINZEL_INDEX]: {
                "txid": str(einzel_ist["txid"]).lower(),
                "vout": int(einzel_ist["vout"]),
                "amount_sats": EINZEL_SATS,
                "block_time": int(einzel_ist["block_time"]),
            }
        }

    def _aus(addr: str, index: int, rolle: str, src: dict[str, dict]) -> dict[str, Any]:
        row = src[addr]
        return {
            "rolle": rolle,
            "index": index,
            "address": addr,
            "txid": row["txid"],
            "vout": int(row["vout"]),
            "sats": int(row["amount_sats"]),
            "block_time": int(row["block_time"]),
        }

    buendel_ausgaben = [
        _aus(empfang_addrs[i], i, "eigen", buendel_outs)
        for i in BATCH_INDIZES
    ] + [
        _aus(fremd_addrs[i], i, "fremd", buendel_outs)
        for i in range(len(FREMD_SATS))
    ]
    einzel = _aus(empfang_addrs[EINZEL_INDEX], EINZEL_INDEX, "eigen", einzel_outs)
    buendel_txid = buendel_ausgaben[0]["txid"]
    buendel_zeit = int(buendel_ausgaben[0]["block_time"])
    einzel_zeit = int(einzel["block_time"])

    kraken_csv = baue_kraken_ledger(
        amount_sats=EINZEL_SATS,
        fee_sats=10_000,
        buchung_ts=einzel_zeit - CSV_VORLAUF_S,
    )
    strike_csv = baue_strike_sends(
        sends=[
            {
                "sats": BATCH_SATS[j],
                "fee_sats": 10_000,
                "adresse": empfang_addrs[i],
                "txid": buendel_txid,
                "ref": f"STSYN07-000{j + 3}",
            }
            for j, i in enumerate(BATCH_INDIZES)
        ],
        buchung_ts=buendel_zeit - CSV_VORLAUF_S,
    )
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    kraken_pfad = CSV_DIR / "kraken_ledgers.csv"
    strike_pfad = CSV_DIR / "strike.csv"
    kraken_pfad.write_text(kraken_csv, encoding="utf-8")
    strike_pfad.write_text(strike_csv, encoding="utf-8")

    bericht = {
        "network": "regtest",
        "in_satsage_env": False,
        "wallet_boerse": BOERSE_WALLET,
        "wallet_empfang": EMPFANG_WALLET,
        "wallet_fremd": FREMD_WALLET,
        "empfang_script": script,
        "empfang_xpub": xpub,
        "buendel": {
            "txid": buendel_txid,
            "block_time": buendel_zeit,
            "ausgaben": buendel_ausgaben,
        },
        "einzeln": einzel,
        "csv": {
            "kraken": str(kraken_pfad.relative_to(HERE)),
            "strike": str(strike_pfad.relative_to(HERE)),
        },
        "funded": neu,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(bericht, indent=2) + "\n", encoding="utf-8")
    eigen = [a for a in buendel_ausgaben if a["rolle"] == "eigen"]
    print(
        f"Börsen-Szenario: Sammel-Tx {len(eigen)} eigene + {len(FREMD_SATS)} fremde "
        f"Ausgänge, Einzelauszahlung {EINZEL_SATS} sat, "
        f"{'neu angelegt' if neu else 'bereits vorhanden'}.",
        file=sys.stderr,
    )
    return bericht


def main() -> int:
    parser = argparse.ArgumentParser(description="Regtest-Börsenszenario erzeugen")
    parser.add_argument("--native", action="store_true", help="bitcoin-cli statt Docker")
    args = parser.parse_args()
    os.environ.setdefault("NETWORK", "regtest")
    try:
        rpc = Rpc(choose_native(bool(args.native)))
        run(rpc)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
