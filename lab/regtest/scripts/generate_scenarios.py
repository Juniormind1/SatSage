#!/usr/bin/env python3
"""Create regtest wallets and trace-friendly transactions.

Private keys and seeds never leave Core wallets. Only public XPUBs are written
into the ignored local .data/.regtest.env file.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
COMPOSE_FILE = HERE / "docker-compose.yml"
WALLETS = ("lab-alpha", "lab-beta", "lab-change", "lab-gamma")
LABELS = ("alpha", "beta", "change", "gamma")

class Rpc:
    def __init__(self, native: bool):
        user = os.environ.get("RPCUSER", "bitcoin")
        password = os.environ.get("RPCPASSWORD", "secret")
        port = os.environ.get("RPCPORT", "18443")
        if native:
            cli = os.environ.get("BITCOIN_CLI", "bitcoin-cli").strip().strip('"')
            # Windows-Pfade nicht per shlex splitten (sonst fallen Backslashes weg).
            if os.name == "nt" or (len(cli) >= 2 and cli[1] == ":"):
                self.base = [cli]
            else:
                self.base = shlex.split(cli)
            extra = os.environ.get("BITCOIN_CLI_ARGS", "").strip()
            if extra:
                self.base += shlex.split(extra, posix=(os.name != "nt"))
        else:
            self.base = ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "bitcoind", "bitcoin-cli"]
        self.auth = ["-regtest", f"-rpcuser={user}", f"-rpcpassword={password}", f"-rpcport={port}"]

    def call(self, *args: str, wallet: str | None = None) -> str:
        command = self.base + self.auth + ([f"-rpcwallet={wallet}"] if wallet else []) + list(args)
        try:
            result = subprocess.run(command, check=True, text=True, capture_output=True)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Programm nicht gefunden: {command[0]}") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout).strip()
            raise RuntimeError(f"RPC fehlgeschlagen: {detail}") from exc
        return result.stdout.strip()

    def json(self, *args: str, wallet: str | None = None) -> Any:
        return json.loads(self.call(*args, wallet=wallet))

def on_path(program: str) -> bool:
    return any((Path(d) / program).is_file() and os.access(Path(d) / program, os.X_OK)
               for d in os.environ.get("PATH", "").split(os.pathsep))

def choose_native(force: bool) -> bool:
    if force or os.environ.get("SATSAGE_LAB_NATIVE") == "1":
        return True
    if not on_path("docker"):
        print("Docker fehlt; verwende native bitcoin-cli (BITCOIN_CLI/BITCOIN_CLI_ARGS).", file=sys.stderr)
        return True
    return False

def mine(rpc: Rpc, blocks: int, address: str) -> None:
    rpc.call("generatetoaddress", str(blocks), address, wallet="lab-faucet")

def new_address(rpc: Rpc, wallet: str) -> str:
    # bech32 = BIP84 native SegWit — muss zum exportierten wpkh-XPUB passen.
    return rpc.call("getnewaddress", "", "bech32", wallet=wallet)


#: Empfangs-Indizes, die die Szenarien maximal anfassen (Fan-out bis ~45).
#: SatSage teilt MAX_ADDRESSES auf Empfang+Change (//2) — deshalb ≥ 2× dieser
#: Wert, sonst bleiben UTXOs jenseits des Scan-Fensters unsichtbar.
LAB_RECEIVE_COUNT = 100
LAB_MAX_ADDRESSES = 400


def receive_addresses(rpc: Rpc, wallet: str, count: int = LAB_RECEIVE_COUNT) -> list[str]:
    """
    Feste BIP84-Empfangsadressen per deriveaddresses.

    getnewaddress schiebt den Keypool bei jedem Szenario-Lauf weiter — nach
    dem zweiten Lauf lagen UTXOs auf Index 50+, während SatSage mit
    MAX_ADDRESSES=100 nur 0–49 Empfang ableitet und „0 UTXOs“ meldet.
    """
    rows = rpc.json("listdescriptors", "false", wallet=wallet).get("descriptors", [])
    for row in rows:
        if row.get("internal"):
            continue
        desc = (row.get("desc") or "").strip()
        dlow = desc.lower()
        if "wpkh(" not in dlow or "sh(wpkh" in dlow:
            continue
        if not re.search(r"/\*", desc):
            continue
        addrs = rpc.json("deriveaddresses", desc, f"[0,{count - 1}]")
        if not isinstance(addrs, list) or len(addrs) < count:
            raise RuntimeError(
                f"{wallet}: deriveaddresses lieferte {len(addrs) if isinstance(addrs, list) else addrs}"
            )
        return [str(a) for a in addrs]
    # Fallback (ältere Wallets ohne wpkh-Deskriptor): Keypool wie bisher.
    return [new_address(rpc, wallet) for _ in range(count)]

def load_or_create(rpc: Rpc, wallet: str) -> None:
    try:
        rpc.call("loadwallet", wallet)
        return
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "already loaded" in msg:
            return
        # "path does not exist" -> create; andere Fehler durchreichen falls create scheitert
    try:
        rpc.call("createwallet", wallet, "false", "false", "", "false", "true")
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "already loaded" in msg:
            rpc.call("loadwallet", wallet)
            return
        raise

def public_receive_key(rpc: Rpc, wallet: str) -> tuple[str, str]:
    """Liefert (xpub, script_type) fuer Empfang — bevorzugt BIP84/wpkh.

    Core-Descriptor-Wallets listen zuerst oft BIP44/pkh. Die Lab-Adressen
    (getnewaddress bech32) liegen aber auf BIP84; der falsche tpub liefert
    in SatSage leere UTXO-Scans.
    """
    # include_private=false: kein xprv/seed.
    rows = rpc.json("listdescriptors", "false", wallet=wallet).get("descriptors", [])
    kandidaten: list[tuple[int, str, str]] = []
    for row in rows:
        if row.get("internal"):
            continue
        desc = row.get("desc") or ""
        match = re.search(r"\b((?:xpub|tpub|vpub|zpub)[A-Za-z0-9]+)", desc)
        if not match:
            continue
        dlow = desc.lower()
        # Lab nutzt getnewaddress "" bech32 -> BIP84/wpkh (bcrt1q), nicht Taproot (bcrt1p).
        if re.search(r"/84[h']/", dlow) or (
            "wpkh(" in dlow and "sh(wpkh" not in dlow
        ):
            score, script = 100, "segwit"
        elif re.search(r"/49[h']/", dlow) or "sh(wpkh" in dlow:
            score, script = 50, "nested"
        elif re.search(r"/44[h']/", dlow) or dlow.startswith("pkh("):
            score, script = 30, "legacy"
        elif re.search(r"/86[h']/", dlow) or dlow.startswith("tr("):
            score, script = 10, "taproot"
        else:
            score, script = 0, "auto"
        kandidaten.append((score, match.group(1), script))
    if not kandidaten:
        raise RuntimeError(f"Kein öffentlicher XPUB in {wallet} gefunden")
    kandidaten.sort(key=lambda row: -row[0])
    _score, xpub, script = kandidaten[0]
    return xpub, script

def unspent(rpc: Rpc, wallet: str) -> list[dict[str, Any]]:
    return rpc.json("listunspent", "1", "999999", wallet=wallet)

def select(rpc: Rpc, wallet: str, count: int) -> list[dict[str, Any]]:
    """Waehlt die groessten UTXOs (stabil), damit Folge-Spends nicht an Change scheitern."""
    rows = unspent(rpc, wallet)
    rows.sort(key=lambda row: (-float(row["amount"]), row["txid"], int(row["vout"])))
    if len(rows) < count:
        raise RuntimeError(f"Zu wenige UTXOs in {wallet}: {len(rows)} < {count}")
    return rows[:count]


def select_near(
    rpc: Rpc,
    wallet: str,
    count: int,
    *,
    target: float = 0.05,
    lo: float = 0.01,
    hi: float = 0.08,
) -> list[dict[str, Any]]:
    """
    Wählt UTXOs nahe *target* — nie Faucet-Coinbase-Wale.

    Sonst explodiert die Fee (maxtxfee), sobald ein Mix-Szenario große
    Miner-Outputs mit 0,05-Lab-Coins mischt.
    """
    rows = [
        u for u in unspent(rpc, wallet)
        if lo <= float(u["amount"]) <= hi
    ]
    rows.sort(
        key=lambda row: (
            abs(float(row["amount"]) - target),
            row["txid"],
            int(row["vout"]),
        )
    )
    if len(rows) < count:
        raise RuntimeError(
            f"Zu wenige UTXOs ~{target} BTC in {wallet}: {len(rows)} < {count} "
            f"(Range {lo}–{hi})"
        )
    return rows[:count]

def raw_spend(rpc: Rpc, name: str, inputs: list[dict[str, Any]],
              outputs: list[tuple[str, float]], signers: list[str]) -> dict[str, Any]:
    input_json = json.dumps([{"txid": u["txid"], "vout": int(u["vout"])} for u in inputs], separators=(",", ":"))
    output_map: dict[str, float] = {}
    for address, amount in outputs:
        output_map[address] = round(output_map.get(address, 0.0) + amount, 8)
    raw = rpc.call("createrawtransaction", input_json, json.dumps(output_map, separators=(",", ":")))
    for wallet in dict.fromkeys(signers):
        raw = rpc.json("signrawtransactionwithwallet", raw, wallet=wallet)["hex"]
    decoded = rpc.json("decoderawtransaction", raw)
    if len(decoded.get("vin", [])) != len(inputs) or len(decoded.get("vout", [])) != len(outputs):
        raise RuntimeError(f"{name}: Transaktionsform weicht ab")
    return {"name": name, "txid": rpc.call("sendrawtransaction", raw), "vin": len(inputs), "vout": len(outputs)}

def write_env(rpc: Rpc) -> None:
    lines = ["# Lokal generiert; niemals committen."]
    for index, (label, wallet) in enumerate(zip(LABELS, WALLETS)):
        xpub, script = public_receive_key(rpc, wallet)
        lines += [
            f"WALLET_{index}_NAME=Lab {label.title()}",
            f"WALLET_{index}_XPUB={xpub}",
            f"WALLET_{index}_SCRIPT={script}",
            # Empfang+Change je MAX//2 — muss Lab-Indizes (bis ~100) abdecken.
            f"WALLET_{index}_MAX_ADDRESSES={LAB_MAX_ADDRESSES}",
        ]
    lines += [
        "NETWORK=regtest",
        "FULCRUM_HOST=127.0.0.1",
        "FULCRUM_PORT=50001",
        "FULCRUM_SSL=false",
        "BIP158_P2P=0",
        "OEFFENTLICHE_ELECTRUM=0",
        "NODE_IP=127.0.0.1",
        "RPCPORT=18443",
        "RPCUSER=bitcoin",
        "RPCPASSWORD=secret",
        # Lokaler mempool.space-Explorer (docker: mempool-web auf :18080).
        "MEMPOOL_URL=http://127.0.0.1:18080",
        # Assistent: lokales Ollama (Loopback). Modell muss auf dem Host liegen
        # (z. B. ollama pull qwen2.5:0.5b) — sonst Pille grau / unreachable.
        "LLM_BASE_URL=http://127.0.0.1:11434/v1",
        "LLM_MODELL=qwen2.5:0.5b",
        "LLM_ANBIETER=ollama",
        "LLM_BETRIEB=loopback",
        "LLM_REMOTE_OPT_IN=0",
    ]
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

def run(rpc: Rpc) -> None:
    for wallet in ("lab-faucet", *WALLETS):
        load_or_create(rpc, wallet)
    faucet = new_address(rpc, "lab-faucet")
    mine(rpc, 110, faucet)
    # Feste Indizes 0..n — kein Keypool-Vorschub bei erneutem Lauf.
    addresses = {
        label: receive_addresses(rpc, wallet, LAB_RECEIVE_COUNT)
        for label, wallet in zip(LABELS, WALLETS)
    }
    for index in range(30):
        payouts = {addresses[label][index]: 0.05 for label in LABELS}
        rpc.call("sendmany", "", json.dumps(payouts, separators=(",", ":")), wallet="lab-faucet")
        mine(rpc, 1, faucet)

    alpha, beta, change, gamma = WALLETS
    records: list[dict[str, Any]] = []
    u = select(rpc, alpha, 1)
    records.append(raw_spend(rpc, "Alpha-hop-to-Beta", u, [(addresses["beta"][31], .02), (addresses["alpha"][31], .029)], [alpha]))
    mine(rpc, 1, faucet)
    u = select(rpc, alpha, 1)
    records.append(raw_spend(rpc, "Alpha-self-send", u, [(addresses["alpha"][32], .02), (addresses["alpha"][33], .029)], [alpha]))
    mine(rpc, 1, faucet)
    records.append(raw_spend(rpc, "Gamma-consolidation", select(rpc, gamma, 4), [(addresses["gamma"][34], .19)], [gamma] * 4))
    mine(rpc, 1, faucet)

    # Wait before spending one old coin, making age visible in the chain.
    old = select(rpc, beta, 1)
    mine(rpc, 12, faucet)
    # 10 gleiche Outputs + 1 Change; Change-Index darf nicht mit den 10 kollidieren
    # (sonst merged createrawtransaction und vout-Anzahl weicht ab).
    fanout = [(addresses["beta"][35 + i], .004) for i in range(10)] + [(addresses["beta"][45], .008)]
    records.append(raw_spend(rpc, "Beta-aged-fanout", old, fanout, [beta]))
    mine(rpc, 2, faucet)

    # ------------------------------------------------------------------
    # CoinJoin-Fixtures: Fremd-Peers = lab-faucet (Funding-Quelle aller Lab-
    # Sats). lab-faucet steht bewusst NICHT in SatSage WALLET_* → in SatSage
    # sind das fremde Inputs. Lab-Wallets = nur Viewer-Anteile (eigene Ins).
    # Kein Multisig — alles Einzelsignatur (P2WPKH).
    # ------------------------------------------------------------------

    # Extra-Funding: Lab-Wallets + viele kleine Faucet-Peer-UTXOs für Mixes.
    for index in range(30, 50):
        payouts = {addresses[label][index]: 0.05 for label in LABELS}
        rpc.call("sendmany", "", json.dumps(payouts, separators=(",", ":")), wallet="lab-faucet")
        mine(rpc, 1, faucet)

    peer_addrs = [new_address(rpc, "lab-faucet") for _ in range(60)]
    for i in range(0, len(peer_addrs), 12):
        chunk = peer_addrs[i : i + 12]
        rpc.call(
            "sendmany",
            "",
            json.dumps({a: 0.05 for a in chunk}, separators=(",", ":")),
            wallet="lab-faucet",
        )
        mine(rpc, 1, faucet)

    # Wasabi-Classic-ähnlich: 6× Alpha (eigen) + 18× Faucet (fremd);
    # 24 gleiche Mix-Outs + 4 Changes (1× Alpha, 3× Faucet).
    cj1_own = select_near(rpc, alpha, 6)
    cj1_foreign = select_near(rpc, "lab-faucet", 18)
    cj1_ins = cj1_own + cj1_foreign
    cj1_signers = [alpha] * 6 + ["lab-faucet"] * 18
    cj1_in_sum = sum(float(u["amount"]) for u in cj1_ins)
    cj1_equal = round((cj1_in_sum - 0.001) * 0.90 / 24, 8)
    cj1_change = round((cj1_in_sum - 24 * cj1_equal - 0.0005) / 4, 8)
    if cj1_equal <= 0 or cj1_change <= 0:
        raise RuntimeError("Wasabi-classic-like: Beträge ungültig")
    cj1_outputs = (
        [(addresses["alpha"][20 + i], cj1_equal) for i in range(6)]
        + [(new_address(rpc, "lab-faucet"), cj1_equal) for _ in range(18)]
        + [(addresses["alpha"][32], cj1_change)]
        + [(new_address(rpc, "lab-faucet"), cj1_change) for _ in range(3)]
    )
    cj1 = raw_spend(rpc, "Wasabi-classic-like", cj1_ins, cj1_outputs, cj1_signers)
    cj1["alias"] = "CoinJoin-like-round-1"
    cj1["expected_kind"] = "wasabi_classic"
    cj1["viewer_wallet"] = "lab-alpha"
    cj1["foreign_wallet"] = "lab-faucet"
    records.append(cj1)
    mine(rpc, 3, faucet)

    # Remix: nur Alpha-Equal-Outs aus Round 1 + neue Faucet-Peers.
    equal_alpha = set(addresses["alpha"][20:26])
    cj2_own = [
        u for u in unspent(rpc, alpha)
        if u["txid"] == cj1["txid"] and u.get("address") in equal_alpha
    ]
    if len(cj2_own) != 6:
        raise RuntimeError(f"Wasabi-classic-like: Alpha-Equal-Outs fehlen ({len(cj2_own)})")
    cj2_foreign = select_near(rpc, "lab-faucet", 18)
    cj2_ins = cj2_own + cj2_foreign
    cj2_signers = [alpha] * 6 + ["lab-faucet"] * 18
    cj2_sum = sum(float(u["amount"]) for u in cj2_ins)
    cj2_equal = round((cj2_sum - 0.001) * 0.90 / 24, 8)
    cj2_change = round((cj2_sum - 24 * cj2_equal - 0.0005) / 4, 8)
    cj2_outputs = (
        [(addresses["alpha"][28 + i], cj2_equal) for i in range(6)]
        + [(new_address(rpc, "lab-faucet"), cj2_equal) for _ in range(18)]
        + [(addresses["alpha"][39], cj2_change)]
        + [(new_address(rpc, "lab-faucet"), cj2_change) for _ in range(3)]
    )
    cj2 = raw_spend(rpc, "Wasabi-classic-remix", cj2_ins, cj2_outputs, cj2_signers)
    cj2["alias"] = "CoinJoin-like-round-2"
    cj2["expected_kind"] = "wasabi_classic"
    cj2["viewer_wallet"] = "lab-alpha"
    cj2["foreign_wallet"] = "lab-faucet"
    records.append(cj2)
    mine(rpc, 3, faucet)

    # Whirlpool-like 5×5: 1× Alpha + 4× Faucet-fremd.
    wp_own = select_near(rpc, alpha, 1)
    wp_foreign = select_near(rpc, "lab-faucet", 4)
    wp_ins = wp_own + wp_foreign
    wp_sum = sum(float(u["amount"]) for u in wp_ins)
    wp_denom = round((wp_sum - 0.0002) / 5, 8)
    if wp_denom <= 0:
        raise RuntimeError("Whirlpool-like: Inputs zu klein")
    wp_outs = [(addresses["alpha"][50], wp_denom)] + [
        (new_address(rpc, "lab-faucet"), wp_denom) for _ in range(4)
    ]
    wp = raw_spend(
        rpc, "Whirlpool-like-5x5", wp_ins, wp_outs, [alpha] + ["lab-faucet"] * 4
    )
    wp["expected_kind"] = "whirlpool"
    wp["viewer_wallet"] = "lab-alpha"
    wp["foreign_wallet"] = "lab-faucet"
    records.append(wp)
    mine(rpc, 2, faucet)

    # JoinMarket-like: 1 eigen + 3 fremd; 4 gleiche CJ-Outs + 3 Changes.
    jm_own = select_near(rpc, beta, 1)
    jm_foreign = select_near(rpc, "lab-faucet", 3)
    jm_ins = jm_own + jm_foreign
    jm_in_sum = sum(float(u["amount"]) for u in jm_ins)
    jm_equal = round(jm_in_sum * 0.18, 8)
    jm_change = round((jm_in_sum - 4 * jm_equal - 0.0002) / 3, 8)
    if jm_equal <= 0 or jm_change <= 0:
        raise RuntimeError("JoinMarket-like: Beträge ungültig")
    jm_outs = (
        [(addresses["beta"][51], jm_equal)]
        + [(new_address(rpc, "lab-faucet"), jm_equal) for _ in range(3)]
        + [(addresses["beta"][52], jm_change)]
        + [(new_address(rpc, "lab-faucet"), jm_change) for _ in range(2)]
    )
    jm = raw_spend(
        rpc, "JoinMarket-like", jm_ins, jm_outs, [beta] + ["lab-faucet"] * 3
    )
    jm["expected_kind"] = "joinmarket"
    jm["viewer_wallet"] = "lab-beta"
    jm["foreign_wallet"] = "lab-faucet"
    records.append(jm)
    mine(rpc, 2, faucet)

    # WabiSabi-like: 2× Alpha eigen + 14× Faucet fremd; 16 ungleiche Outs.
    ws_own = select_near(rpc, alpha, 2)
    ws_foreign = select_near(rpc, "lab-faucet", 14)
    ws_ins = ws_own + ws_foreign
    ws_signers = [alpha] * 2 + ["lab-faucet"] * 14
    ws_in_sum = sum(float(u["amount"]) for u in ws_ins)
    ws_weights = [
        31, 22, 17, 11, 9, 7, 5, 4,
        28, 19, 14, 8, 6, 3, 2, 1,
    ]
    wsum = float(sum(ws_weights))
    budget = ws_in_sum - 0.0005
    ws_amounts = [round(budget * (w / wsum), 8) for w in ws_weights]
    ws_amounts[-1] = round(budget - sum(ws_amounts[:-1]), 8)
    # 2 eigene Empfänge (Alpha), Rest Faucet — in SatSage nur Alpha „eigen“.
    ws_outs: list[tuple[str, float]] = [
        (addresses["alpha"][53], ws_amounts[0]),
        (addresses["alpha"][54], ws_amounts[1]),
    ]
    for amt in ws_amounts[2:]:
        ws_outs.append((new_address(rpc, "lab-faucet"), amt))
    ws = raw_spend(rpc, "Wabisabi-like", ws_ins, ws_outs, ws_signers)
    ws["expected_kind"] = "wabisabi"
    ws["viewer_wallet"] = "lab-alpha"
    ws["foreign_wallet"] = "lab-faucet"
    records.append(ws)
    mine(rpc, 2, faucet)

    # PayJoin-like: 1 eigen (Gamma) + 1 Faucet; 2 Outs.
    pj_ins = select_near(rpc, gamma, 1) + select_near(rpc, "lab-faucet", 1)
    pj_sum = sum(float(u["amount"]) for u in pj_ins)
    pj_outs = [
        (addresses["gamma"][54], round(pj_sum * 0.55, 8)),
        (new_address(rpc, "lab-faucet"), round(pj_sum * 0.40, 8)),
    ]
    pj = raw_spend(rpc, "PayJoin-like", pj_ins, pj_outs, [gamma, "lab-faucet"])
    pj["expected_kind"] = "payjoin"
    pj["viewer_wallet"] = "lab-gamma"
    records.append(pj)
    mine(rpc, 2, faucet)

    # Exchange-batch-like: Faucet-Fan-out, genau 1 Out an Alpha (0 eigene Ins).
    ex_ins = select_near(rpc, "lab-faucet", 1)
    ex_sum = float(ex_ins[0]["amount"])
    ex_main = round(ex_sum * 0.40, 8)
    ex_rest = round((ex_sum - ex_main - 0.0002) / 5, 8)
    ex_outs = [(addresses["alpha"][55], ex_main)] + [
        (new_address(rpc, "lab-faucet"), ex_rest) for _ in range(5)
    ]
    ex = raw_spend(rpc, "Exchange-batch-like", ex_ins, ex_outs, ["lab-faucet"])
    ex["expected_kind"] = "exchange_batch"
    ex["viewer_wallet"] = "lab-alpha"
    records.append(ex)
    mine(rpc, 2, faucet)

    # Fan-out-own: Alias auf bestehendes Beta-aged-fanout
    for rec in records:
        if rec.get("name") == "Beta-aged-fanout":
            rec["expected_kind"] = "fan_out_own"
            rec["viewer_wallet"] = "lab-beta"
            rec["alias"] = "Fan-out-own"
            break

    write_env(rpc)
    report = {"tip_height": int(rpc.call("getblockcount")), "records": records}
    (HERE / ".data" / "scenario-report.json").write_text(json.dumps(report, indent=2) + "\n")

    # Expectations für Klassifikation / Soft-Label-Abnahme
    txclass = {
        "tip_height": report["tip_height"],
        "cases": [
            {
                "name": r["name"],
                "txid": r["txid"],
                "expected_kind": r["expected_kind"],
                "viewer_wallet": r.get("viewer_wallet"),
                "alias": r.get("alias"),
            }
            for r in records
            if r.get("expected_kind")
        ],
    }
    (HERE / ".data" / "scenario-report-txclass.json").write_text(
        json.dumps(txclass, indent=2) + "\n"
    )

    for record in records:
        print(json.dumps(record, sort_keys=True))
    print(json.dumps({
        "env": str(ENV_PATH),
        "tip_height": report["tip_height"],
        "scenario_count": len(records),
        "txclass_cases": len(txclass["cases"]),
    }))

def main() -> int:
    parser = argparse.ArgumentParser(description="Erzeugt SatSage-Regtest-Wallets und Szenarien.")
    parser.add_argument("--native", action="store_true", help="native bitcoin-cli statt Docker Compose verwenden")
    parser.add_argument("--dry-run", action="store_true", help="nur Backend und Pfade prüfen, keine RPC-Aufrufe")
    args = parser.parse_args()
    native = choose_native(args.native)
    print(f"Backend: {'native bitcoin-cli' if native else 'Docker Compose'}")
    print(f"Lokale Env-Datei: {ENV_PATH}")
    if args.dry_run:
        return 0
    run(Rpc(native))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        raise SystemExit(1)
