#!/usr/bin/env python3
"""Create regtest wallets and trace-friendly transactions.

Private keys and seeds never leave Core wallets. Only public XPUBs are written
into the ignored local .data/.regtest.env file.
"""
from __future__ import annotations
import argparse
import json
import os
import random
import re
import shlex
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
COMPOSE_FILE = HERE / "docker-compose.yml"
WALLETS = ("lab-alpha", "lab-beta", "lab-change", "lab-gamma")
LABELS = ("alpha", "beta", "change", "gamma")

# Unspent-Alterungs-Kohorte (nie ausgegeben) vs. Spend-Pool für Shape-Txs.
# Beträge trennen select_near(target=0.05) von der Alters-Kohorte.
AGE_FUND_AMOUNT = 0.049
SPEND_FUND_AMOUNT = 0.05
#: Zusätzliche unspent Kohorte: gleiche Stückzahl und Zeitstreuung, Volumen log-gleich
#: von 1000 Sat bis 0,2 BTC. Liegt hinter Spend-Pool und Shape-Indizes.
#: 1000 Sat bleibt über der Core-Dust-Grenze für natives SegWit.
VOL_INDEX_START = 120
VOL_MIN_SATS = 1000
VOL_MAX_BTC = 0.2
#: Empfangs-Indizes 0..AGE_INDEX_COUNT-1 = nur Alter (unspent).
AGE_INDEX_COUNT = 40
#: Indizes AGE_INDEX_COUNT .. AGE+SPEND-1 = Spend-Pool (CJ/Hop/…).
SPEND_INDEX_COUNT = 40

# Sammel-Tx, die das 20er-Auflöse-Limit trifft: ein eigener Eingang zuerst,
# danach mehr fremde Eingänge als core.trace.FULL_RESOLUTION_INPUT_LIMIT.
# Indizes 96 und 97 liegen in der Lücke zwischen Shape (~55) und Volumen (120).
# Eingang 0,002 BTC und Ausgang 0,0061 BTC liegen unter select_near (ab 0,01),
# der Spend-Pool fasst sie nicht an.
BUENDEL_NAME = "Sammel-eigen-zuerst"
BUENDEL_EIGEN_INDEX = 96
BUENDEL_AUSGANG_INDEX = 97
BUENDEL_FREMDE = 21
BUENDEL_EIGEN_SATS = 200_000
BUENDEL_FREMD_SATS = 20_000
BUENDEL_FEE_SATS = 10_000

#: Eigenes Core-Wallet, nicht in SatSage WALLET_* und nicht im Herkunfts-Inventar.
#: Empfang 0 ist belegt, 1…100 leer, 101 belegt. Gap 100 findet 101 nicht.
GAP_WALLET = "lab-gap"
GAP_NEAR_INDEX = 0
GAP_FAR_INDEX = 101
GAP_MISS = 100
GAP_HIT = 101
GAP_NEAR_SATS = 10_000
GAP_FAR_SATS = 10_101
GAP_REPORT = HERE / ".data" / "scenario-report-gap.json"

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


def rescan_wallets(rpc: Rpc, *wallets: str) -> None:
    """
    Full-Rescan ab Genesis.

    setmocktime legt Blöcke in 2022–2025 an, während createwallet die
    Birthtime auf die Host-Uhr (z. B. 2026) setzt — ohne Rescan bleibt
    listunspent leer (Insufficient funds trotz generatetoaddress).
    """
    for wallet in wallets:
        if not wallet:
            continue
        try:
            rpc.call("rescanblockchain", "0", wallet=wallet)
        except RuntimeError as exc:
            # Ältere Core / schon am Tip: nicht fatal.
            print(f"  rescan {wallet}: {exc}", file=sys.stderr)


def utc_ts(iso_date: str) -> int:
    """UTC-Mitternacht für YYYY-MM-DD → Unix-Timestamp."""
    return int(datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc).timestamp())


def set_time(rpc: Rpc, unix_ts: int) -> None:
    """Mocktime setzen. 0 hebt sie auf.

    Core lehnt einen Block ab, dessen Zeit mehr als zwei Stunden vor der
    Host-Uhr liegt (time-too-new). Ein Zeitsprung, der darüber hinaus
    wollte, bleibt auf der Host-Uhr.
    """
    ts = int(unix_ts)
    if ts > 0:
        ts = min(ts, int(time.time()))
    rpc.call("setmocktime", str(ts))


def mine_at(rpc: Rpc, ts: int, blocks: int, address: str) -> int:
    """Mocktime setzen und minen; je Block +60s, damit nTime > MTP bleibt.

    Ruft ``mine`` direkt (nicht ``mine_next``) — sonst Rekursion.
    Rückgabe: letzter verwendeter Mock-Timestamp.
    """
    cursor = int(ts)
    for _ in range(max(0, int(blocks))):
        set_time(rpc, cursor)
        mine(rpc, 1, address)
        cursor += 60
    return cursor


# Laufender Mock-Cursor innerhalb einer Phase (fund/spend/mine).
_MOCK_CURSOR = 0


def phase_jump(
    rpc: Rpc,
    iso_date: str,
    faucet: str,
    phases: list[dict[str, Any]],
    *,
    label: str,
    note: str,
    blocks: int = 2,
) -> int:
    """Jahres-Sprung: Mocktime vorwärts, ≥1 Block für MTP/Header, Phase loggen."""
    global _MOCK_CURSOR
    ts = utc_ts(iso_date)
    _MOCK_CURSOR = mine_at(rpc, ts, blocks, faucet)
    height = int(rpc.call("getblockcount"))
    phases.append({
        "label": label,
        "date": iso_date,
        "mock_ts": ts,
        "height": height,
        "note": note,
    })
    print(f"Phase {label} ({iso_date}): Höhe {height}", file=sys.stderr)
    return ts


def mine_next(rpc: Rpc, blocks: int, address: str) -> None:
    """Weiter minen in der aktuellen Phase (Mock-Cursor +60s je Block)."""
    global _MOCK_CURSOR
    if _MOCK_CURSOR <= 0:
        mine(rpc, blocks, address)
        return
    _MOCK_CURSOR = mine_at(rpc, _MOCK_CURSOR, blocks, address)


def age_window_ts(*, days_back: int = 365 * 7) -> tuple[int, int]:
    """Unix-Fenster: vor *days_back* Tagen … gestern (UTC)."""
    now = datetime.now(timezone.utc)
    end = now - timedelta(days=1)
    start = now - timedelta(days=int(days_back))
    return int(start.timestamp()), int(end.timestamp())


def volume_btc(rng: random.Random) -> float:
    """Log-gleich zwischen 1000 Sat und 0,2 BTC, auf 1 Sat gerundet."""
    lo = VOL_MIN_SATS / 1e8
    span = rng.random()
    btc = lo * ((VOL_MAX_BTC / lo) ** span)
    sats = max(VOL_MIN_SATS, min(int(VOL_MAX_BTC * 1e8), round(btc * 1e8)))
    return sats / 1e8


def sorted_random_timestamps(n: int, t0: int, t1: int, rng: random.Random) -> list[int]:
    """n Zufallszeiten in [t0, t1], aufsteigend (Chain-Zeit darf nicht zurück)."""
    if n <= 0:
        return []
    if t1 <= t0:
        return [t0] * n
    return sorted(int(rng.randint(t0, t1)) for _ in range(n))


def fund_index_at(
    rpc: Rpc,
    addresses: dict[str, list[str]],
    faucet: str,
    index: int,
    ts: int,
    *,
    amount: float,
) -> int:
    """
    Eine Funding-Runde (alle Lab-Wallets, fester Index) bei Blockzeit *ts*.

    Rückgabe: Mock-Cursor nach dem Bestätigungsblock.
    """
    global _MOCK_CURSOR
    ts = max(int(ts), int(_MOCK_CURSOR) + 60 if _MOCK_CURSOR else int(ts))
    payouts = {addresses[label][index]: float(amount) for label in LABELS}
    # Mocktime vor dem Send, damit wallet-interne Zeiten konsistent sind.
    set_time(rpc, ts)
    rpc.call(
        "sendmany",
        "",
        json.dumps(payouts, separators=(",", ":")),
        wallet="lab-faucet",
    )
    _MOCK_CURSOR = mine_at(rpc, ts, 1, faucet)
    return int(_MOCK_CURSOR)


def fund_indices(
    rpc: Rpc,
    addresses: dict[str, list[str]],
    faucet: str,
    start: int,
    stop: int,
    *,
    amount: float = 0.05,
) -> None:
    """Faucet → feste Empfangs-Indizes [start, stop) je Lab-Wallet, 1 Block je Index."""
    # Faucet muss Coinbases mit Mocktime-Timestamps sehen.
    rescan_wallets(rpc, "lab-faucet")
    for index in range(start, stop):
        payouts = {addresses[label][index]: amount for label in LABELS}
        rpc.call("sendmany", "", json.dumps(payouts, separators=(",", ":")), wallet="lab-faucet")
        mine_next(rpc, 1, faucet)
    # Empfänger-Wallets: Funding-Txs mit altem nTime ebenfalls einsammeln.
    rescan_wallets(rpc, *WALLETS)


def new_address(rpc: Rpc, wallet: str) -> str:
    # bech32 = BIP84 native SegWit — muss zum exportierten wpkh-XPUB passen.
    return rpc.call("getnewaddress", "", "bech32", wallet=wallet)


#: Empfangs-Indizes, die die Szenarien maximal anfassen (Volumen-Kohorte bis 159).
#: SatSage teilt MAX_ADDRESSES auf Empfang+Change (//2) — deshalb ≥ 2× dieser
#: Wert, sonst bleiben UTXOs jenseits des Scan-Fensters unsichtbar.
LAB_RECEIVE_COUNT = 160
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


def _sats_betrag(amount: object) -> int:
    return int(round(float(amount) * 1e8))


def _btc_aus_sats(sats: int) -> float:
    return round(int(sats) / 1e8, 8)


def _blockzeit(rpc: Rpc, txid: str) -> int:
    tx = rpc.json("getrawtransaction", txid, "true")
    zeit = tx.get("blocktime")
    if zeit is None:
        raise RuntimeError(f"{txid}: keine Blockzeit")
    return int(zeit)


def _vout_an(rpc: Rpc, txid: str, address: str) -> int:
    tx = rpc.json("getrawtransaction", txid, "true")
    for out in tx.get("vout") or []:
        if (out.get("scriptPubKey") or {}).get("address") == address:
            return int(out["n"])
    raise RuntimeError(f"{txid}: kein Ausgang an {address}")


def fund_eine_adresse(
    rpc: Rpc,
    address: str,
    faucet: str,
    ts: int,
    amount: float,
) -> dict[str, Any]:
    """Faucet zahlt genau eine Adresse und bestätigt einen Block."""
    global _MOCK_CURSOR
    ts = max(int(ts), int(_MOCK_CURSOR) + 60 if _MOCK_CURSOR else int(ts))
    set_time(rpc, ts)
    txid = str(rpc.call(
        "sendmany",
        "",
        json.dumps({address: round(float(amount), 8)}, separators=(",", ":")),
        wallet="lab-faucet",
    )).strip()
    _MOCK_CURSOR = mine_at(rpc, ts, 1, faucet)
    return {
        "txid": txid,
        "vout": _vout_an(rpc, txid, address),
        "block_time": _blockzeit(rpc, txid),
        "address": address,
    }


def lege_sammel_buendel(
    rpc: Rpc,
    addresses: dict[str, list[str]],
    faucet: str,
    eigen: dict[str, Any],
) -> dict[str, Any]:
    """
    Ein eigener Eingang, danach 21 fremde, ein Ausgang an Alpha.

    Der eigene Eingang ist Jahre alt. Die Sammel-Tx wird am aktuellen
    Mock-Cursor bestätigt, direkt nach dem Alters-Funding (etwa ein Tag
    vor dem Laborlauf) und damit noch in der Haltefrist von einem Jahr.
    """
    alpha = "lab-alpha"
    ausgang = addresses["alpha"][BUENDEL_AUSGANG_INDEX]
    rescan_wallets(rpc, alpha, "lab-faucet")
    eigene = [
        u for u in unspent(rpc, alpha)
        if u.get("address") == eigen["address"]
    ]
    if len(eigene) != 1:
        raise RuntimeError(
            f"{BUENDEL_NAME}: eigener Eingang {len(eigene)}× statt 1×"
        )
    fremd_adressen = [new_address(rpc, "lab-faucet") for _ in range(BUENDEL_FREMDE)]
    betrag = _btc_aus_sats(BUENDEL_FREMD_SATS)
    set_time(rpc, int(_MOCK_CURSOR) or int(time.time()))
    rpc.call(
        "sendmany",
        "",
        json.dumps({a: betrag for a in fremd_adressen}, separators=(",", ":")),
        wallet="lab-faucet",
    )
    mine_next(rpc, 1, faucet)
    rescan_wallets(rpc, "lab-faucet")
    fremde = []
    for adresse in fremd_adressen:
        treffer = [u for u in unspent(rpc, "lab-faucet") if u.get("address") == adresse]
        if len(treffer) != 1:
            raise RuntimeError(
                f"{BUENDEL_NAME}: fremder Eingang {adresse} {len(treffer)}×"
            )
        fremde.append(treffer[0])
    fremde.sort(key=lambda row: (row["txid"], int(row["vout"])))
    summe = BUENDEL_EIGEN_SATS + BUENDEL_FREMDE * BUENDEL_FREMD_SATS
    ausgang_sats = summe - BUENDEL_FEE_SATS
    if ausgang_sats <= 0:
        raise RuntimeError(f"{BUENDEL_NAME}: Ausgang nicht positiv")
    rec = raw_spend(
        rpc,
        BUENDEL_NAME,
        [eigene[0], *fremde],
        [(ausgang, _btc_aus_sats(ausgang_sats))],
        [alpha, "lab-faucet"],
    )
    tx = rpc.json("getrawtransaction", rec["txid"], "true")
    erster = tx["vin"][0]
    if (
        erster["txid"] != eigene[0]["txid"]
        or int(erster["vout"]) != int(eigene[0]["vout"])
    ):
        raise RuntimeError(f"{BUENDEL_NAME}: eigener Eingang steht nicht vorn")
    if len(tx["vin"]) != 1 + BUENDEL_FREMDE:
        raise RuntimeError(
            f"{BUENDEL_NAME}: {len(tx['vin'])} Eingänge, erwartet {1 + BUENDEL_FREMDE}"
        )
    mine_next(rpc, 1, faucet)
    block_time = _blockzeit(rpc, rec["txid"])
    if block_time <= int(eigen["block_time"]):
        raise RuntimeError(f"{BUENDEL_NAME}: Sammel-Tx nicht jünger als der eigene Eingang")
    vout = _vout_an(rpc, rec["txid"], ausgang)
    rec.update({
        "alias": "Sammel-Bündel",
        "expected_kind": "unknown",
        "viewer_wallet": alpha,
        "vout_index": vout,
        "block_time": block_time,
        "eigen_time": int(eigen["block_time"]),
        "foreign_inputs": BUENDEL_FREMDE,
    })
    return rec


def _unspents_an_adresse(rpc: Rpc, address: str) -> list[dict[str, Any]]:
    """Unspents einer Adresse, ohne dass das Wallet den Index beobachten muss."""
    try:
        rpc.call("scantxoutset", "abort")
    except RuntimeError:
        pass
    info = rpc.json("getdescriptorinfo", f"addr({address})")
    desc = str(info.get("descriptor") or "")
    if not desc:
        raise RuntimeError(f"Kein Deskriptor für {address}")
    daten = rpc.json("scantxoutset", "start", json.dumps([desc]))
    if not isinstance(daten, dict) or daten.get("success") is False:
        raise RuntimeError(f"scantxoutset ohne Erfolg: {daten!r}")
    rows: list[dict[str, Any]] = []
    for row in daten.get("unspents") or []:
        if not isinstance(row, dict) or "txid" not in row:
            continue
        rows.append({
            "txid": str(row["txid"]).lower(),
            "vout": int(row["vout"]),
            "amount_sats": _sats_betrag(row.get("amount") or 0),
        })
    return rows


def _sendmany_sats(rpc: Rpc, payouts: dict[str, int]) -> str:
    """Beträge als Dezimaltext, nicht als Binärfloat."""
    teile = [
        f"{json.dumps(addr)}:{sats / 1e8:.8f}"
        for addr, sats in payouts.items()
    ]
    return rpc.call(
        "sendmany", "", "{" + ",".join(teile) + "}", wallet="lab-faucet",
    )


def _outs_der_tx(
    rpc: Rpc, txid: str, wanted: dict[str, int],
) -> dict[str, dict[str, Any]]:
    decoded = rpc.json("getrawtransaction", txid, "true")
    gefunden: dict[str, dict[str, Any]] = {}
    for vout in decoded.get("vout") or []:
        spk = vout.get("scriptPubKey") or {}
        addr = str(spk.get("address") or "")
        if not addr:
            liste = spk.get("addresses") or []
            if liste:
                addr = str(liste[0])
        if addr not in wanted:
            continue
        gefunden[addr] = {
            "txid": txid.lower(),
            "vout": int(vout["n"]),
            "amount_sats": _sats_betrag(vout.get("value") or 0),
        }
    fehlend = [addr for addr in wanted if addr not in gefunden]
    if fehlend:
        raise RuntimeError(
            f"Gap-Tx {txid} enthält nicht alle Ziele ({len(fehlend)} fehlen)"
        )
    return gefunden


def fund_gap_wallet(rpc: Rpc) -> dict[str, Any]:
    """
    Legt ``lab-gap`` an: Empfangsindex 0 und 101, dazwischen nichts.

    Das Wallet steht nicht in ``WALLET_*``. Core sieht Index 101 über
    scantxoutset, der Electrs-Gap-Walk mit Limit 100 nicht.
    """
    load_or_create(rpc, "lab-faucet")
    load_or_create(rpc, GAP_WALLET)
    addrs = receive_addresses(rpc, GAP_WALLET, GAP_FAR_INDEX + 1)
    near = addrs[GAP_NEAR_INDEX]
    far = addrs[GAP_FAR_INDEX]
    xpub, script = public_receive_key(rpc, GAP_WALLET)
    try:
        near_rows = _unspents_an_adresse(rpc, near)
        far_rows = _unspents_an_adresse(rpc, far)
    except RuntimeError as exc:
        print(f"Gap-Bestand unklar ({exc}) — zahle neu.", file=sys.stderr)
        near_rows, far_rows = [], []
    neu: dict[str, dict[str, Any]] = {}
    if not near_rows or not far_rows:
        payouts: dict[str, int] = {}
        if not near_rows:
            payouts[near] = GAP_NEAR_SATS
        if not far_rows:
            payouts[far] = GAP_FAR_SATS
        rescan_wallets(rpc, "lab-faucet")
        faucet = new_address(rpc, "lab-faucet")
        txid = _sendmany_sats(rpc, payouts)
        mine(rpc, 1, faucet)
        neu = _outs_der_tx(rpc, txid, payouts)
        ziele = []
        if near in payouts:
            ziele.append(f"#{GAP_NEAR_INDEX}")
        if far in payouts:
            ziele.append(f"#{GAP_FAR_INDEX}")
        print(
            f"Gap-Wallet {GAP_WALLET}: Empfang {' und '.join(ziele)} "
            f"finanziert ({txid})",
            file=sys.stderr,
        )
    else:
        print(
            f"Gap-Wallet {GAP_WALLET}: Index {GAP_NEAR_INDEX} und "
            f"{GAP_FAR_INDEX} schon belegt",
            file=sys.stderr,
        )
    near_out = neu.get(near) or near_rows[0]
    far_out = neu.get(far) or far_rows[0]
    bericht = {
        "wallet": GAP_WALLET,
        "script": script,
        "xpub": xpub,
        "chain": 0,
        "near_index": GAP_NEAR_INDEX,
        "far_index": GAP_FAR_INDEX,
        "empty_between": GAP_FAR_INDEX - GAP_NEAR_INDEX - 1,
        "gap_miss": GAP_MISS,
        "gap_hit": GAP_HIT,
        "near_address": near,
        "far_address": far,
        "near": near_out,
        "far": far_out,
        "in_satsage_env": False,
        "funded": bool(neu),
        "note": (
            "Nicht in WALLET_*. Gap 100 findet nur Index 0. "
            "Gap 101 findet Index 101. Core scantxoutset findet beide."
        ),
    }
    GAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    GAP_REPORT.write_text(json.dumps(bericht, indent=2) + "\n", encoding="utf-8")
    return bericht

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
        # Regtest-Kette ist kurz — Mainnet-Default 481824 würde jeden Filter-Scan überspringen.
        "BIP158_START_HEIGHT=1",
        "BIP158_PEERS=127.0.0.1:18444",
        "OEFFENTLICHE_ELECTRUM=0",
        "NODE_IP=127.0.0.1",
        "RPCPORT=18443",
        "RPCUSER=bitcoin",
        "RPCPASSWORD=secret",
        # Haltefrist-Demo: Lab-Blöcke sind über 2022–2025 gestreut.
        "STEUER_HALTEFRIST_JAHRE=1",
        # Empfangs-QR / Mempool-ASAP: Dauer-Watch am eigenen Electrs.
        "WALLETS_IMMER_AKTUELL=1",
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
    global _MOCK_CURSOR
    _MOCK_CURSOR = 0
    rng = random.Random()
    t0, t1 = age_window_ts(days_back=365 * 7)
    for wallet in ("lab-faucet", *WALLETS):
        load_or_create(rpc, wallet)
    faucet = new_address(rpc, "lab-faucet")
    phases: list[dict[str, Any]] = []

    # --- Bootstrap: Coinbase-Reife am Beginn des 7-Jahres-Fensters ---
    _MOCK_CURSOR = mine_at(rpc, t0, 110, faucet)
    phases.append({
        "label": "bootstrap",
        "date": datetime.fromtimestamp(t0, tz=timezone.utc).date().isoformat(),
        "mock_ts": t0,
        "height": int(rpc.call("getblockcount")),
        "note": "110 Blocks ab Fensterstart (Coinbase-Reife)",
    })
    print(
        f"Phase bootstrap: Höhe {phases[-1]['height']} "
        f"({phases[-1]['date']})",
        file=sys.stderr,
    )
    rescan_wallets(rpc, "lab-faucet", *WALLETS)

    # Feste Indizes — kein Keypool-Vorschub bei erneutem Lauf.
    # Volumen-Kohorte beginnt bei VOL_INDEX_START (hinter Shape-Empfängern).
    need = VOL_INDEX_START + AGE_INDEX_COUNT
    addresses = {
        label: receive_addresses(rpc, wallet, max(LAB_RECEIVE_COUNT, need))
        for label, wallet in zip(LABELS, WALLETS)
    }

    # --- Funding: je Index eigene Zufallszeit, dann zeitlich aufsteigend minen ---
    # Indizes 0..AGE-1: nur Alter, bleiben unspent (Betrag ≠ 0.05).
    # Indizes AGE..AGE+SPEND-1: Spend-Pool für Hop/CJ (0.05).
    # Wichtig: Zeit nicht an Index-Reihenfolge koppeln (sonst nur alte Hälfte = Alter).
    rescan_wallets(rpc, "lab-faucet")
    fund_slots: list[tuple[int, int, float]] = []
    lo, hi = t0 + 3600, t1
    for i in range(AGE_INDEX_COUNT):
        fund_slots.append((rng.randint(lo, hi), i, AGE_FUND_AMOUNT))
    for j in range(SPEND_INDEX_COUNT):
        idx = AGE_INDEX_COUNT + j
        fund_slots.append((rng.randint(lo, hi), idx, SPEND_FUND_AMOUNT))
    fund_slots.sort(key=lambda row: (row[0], row[1]))
    # Der eigene Eingang liegt nah am Fensteranfang, Jahre vor der Sammel-Tx.
    eigen_ts = t0 + 120 * 24 * 3600
    if not (t0 < eigen_ts < t1):
        raise RuntimeError("Bündel-Zeiten liegen außerhalb des Laborfensters")
    buendel_eigen: dict[str, Any] | None = None
    age_dates: list[str] = []
    for ts, index, amount in fund_slots:
        if buendel_eigen is None and ts >= eigen_ts:
            buendel_eigen = fund_eine_adresse(
                rpc,
                addresses["alpha"][BUENDEL_EIGEN_INDEX],
                faucet,
                eigen_ts,
                _btc_aus_sats(BUENDEL_EIGEN_SATS),
            )
        fund_index_at(rpc, addresses, faucet, index, ts, amount=amount)
        if amount == AGE_FUND_AMOUNT:
            age_dates.append(
                datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            )
    rescan_wallets(rpc, *WALLETS, "lab-faucet")
    # Grob-Histogramm für Report (Jahr → Anzahl Alters-Fundings)
    year_hist = Counter(d[:4] for d in age_dates)
    phases.append({
        "label": "random-age-funding",
        "date": f"{datetime.fromtimestamp(t0, tz=timezone.utc).date()}"
                f" … {datetime.fromtimestamp(t1, tz=timezone.utc).date()}",
        "mock_ts": t0,
        "height": int(rpc.call("getblockcount")),
        "note": (
            f"{AGE_INDEX_COUNT}× unspent @{AGE_FUND_AMOUNT} BTC + "
            f"{SPEND_INDEX_COUNT}× spend-pool @{SPEND_FUND_AMOUNT} BTC; "
            f"Jahre {dict(sorted(year_hist.items()))}"
        ),
        "age_fund_years": dict(sorted(year_hist.items())),
    })
    print(
        f"Phase random-age-funding: Höhe {phases[-1]['height']} — "
        f"Alters-Jahre {dict(sorted(year_hist.items()))}",
        file=sys.stderr,
    )

    # Sammel-Tx jetzt: der Cursor steht am Ende des Alters-Fundings, etwa
    # einen Tag vor der Host-Uhr. Spätere Shape-Sprünge ändern diese
    # Blockzeit nicht mehr. Der Ausgang bleibt liegen (unter select_near).
    if buendel_eigen is None:
        raise RuntimeError(f"{BUENDEL_NAME}: eigener Eingang wurde nicht angelegt")
    buendel_record = lege_sammel_buendel(rpc, addresses, faucet, buendel_eigen)
    phases.append({
        "label": "sammel-buendel",
        "date": datetime.fromtimestamp(
            int(buendel_record["block_time"]), tz=timezone.utc,
        ).date().isoformat(),
        "mock_ts": int(buendel_record["block_time"]),
        "height": int(rpc.call("getblockcount")),
        "note": (
            f"{BUENDEL_NAME}: 1 eigener Eingang vor {BUENDEL_FREMDE} "
            "fremden. Anschaffung = Blockzeit dieser Tx, noch in der Haltefrist."
        ),
    })
    print(
        f"Phase sammel-buendel: Höhe {phases[-1]['height']} "
        f"({phases[-1]['date']})",
        file=sys.stderr,
    )

    # Dieselbe Zeitstreuung, andere Beträge. Eigener Index-Block, damit
    # CoinJoin/Fan-out die festen Alters-Indizes nicht mitausgeben.
    vol_slots: list[tuple[int, int, float]] = []
    vol_sats: list[int] = []
    for i in range(AGE_INDEX_COUNT):
        amount = volume_btc(rng)
        vol_slots.append((rng.randint(lo, hi), VOL_INDEX_START + i, amount))
        vol_sats.append(round(amount * 1e8))
    vol_slots.sort(key=lambda row: (row[0], row[1]))
    vol_dates: list[str] = []
    for ts, index, amount in vol_slots:
        fund_index_at(rpc, addresses, faucet, index, ts, amount=amount)
        vol_dates.append(datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat())
    rescan_wallets(rpc, *WALLETS, "lab-faucet")
    vol_years = Counter(d[:4] for d in vol_dates)
    phases.append({
        "label": "random-volume-funding",
        "date": f"{datetime.fromtimestamp(t0, tz=timezone.utc).date()}"
                f" … {datetime.fromtimestamp(t1, tz=timezone.utc).date()}",
        "mock_ts": t0,
        "height": int(rpc.call("getblockcount")),
        "note": (
            f"{AGE_INDEX_COUNT}× unspent je Wallet, Index {VOL_INDEX_START}…"
            f"{VOL_INDEX_START + AGE_INDEX_COUNT - 1}, "
            f"log-gleich {VOL_MIN_SATS} Sat … {VOL_MAX_BTC} BTC; "
            f"Jahre {dict(sorted(vol_years.items()))}"
        ),
        "volume_fund_years": dict(sorted(vol_years.items())),
        "volume_sats_min": min(vol_sats),
        "volume_sats_max": max(vol_sats),
        "volume_sats_median": sorted(vol_sats)[len(vol_sats) // 2],
    })
    print(
        f"Phase random-volume-funding: Höhe {phases[-1]['height']} — "
        f"{min(vol_sats)} … {max(vol_sats)} Sat, "
        f"Jahre {dict(sorted(vol_years.items()))}",
        file=sys.stderr,
    )

    alpha, beta, _change, gamma = WALLETS
    records: list[dict[str, Any]] = [buendel_record]

    # Shape-Spends nur aus Spend-Pool (0.05); Alters-Kohorte bleibt liegen.
    def _bump(hours: float = 2.0) -> None:
        global _MOCK_CURSOR
        _MOCK_CURSOR = mine_at(
            rpc, int(_MOCK_CURSOR) + int(hours * 3600), 1, faucet,
        )

    u = select_near(rpc, alpha, 1, target=SPEND_FUND_AMOUNT)
    records.append(raw_spend(
        rpc, "Alpha-hop-to-Beta", u,
        [(addresses["beta"][AGE_INDEX_COUNT + SPEND_INDEX_COUNT], .02),
         (addresses["alpha"][AGE_INDEX_COUNT + SPEND_INDEX_COUNT], .029)],
        [alpha],
    ))
    _bump()
    u = select_near(rpc, alpha, 1, target=SPEND_FUND_AMOUNT)
    records.append(raw_spend(
        rpc, "Alpha-self-send", u,
        [(addresses["alpha"][AGE_INDEX_COUNT + SPEND_INDEX_COUNT + 1], .02),
         (addresses["alpha"][AGE_INDEX_COUNT + SPEND_INDEX_COUNT + 2], .029)],
        [alpha],
    ))
    _bump()
    records.append(raw_spend(
        rpc, "Gamma-consolidation",
        select_near(rpc, gamma, 4, target=SPEND_FUND_AMOUNT),
        [(addresses["gamma"][AGE_INDEX_COUNT + SPEND_INDEX_COUNT + 3], .19)],
        [gamma] * 4,
    ))
    _bump(6)

    old = select_near(rpc, beta, 1, target=SPEND_FUND_AMOUNT)
    _bump(24)
    base = AGE_INDEX_COUNT + SPEND_INDEX_COUNT + 5
    fanout = (
        [(addresses["beta"][base + i], .004) for i in range(10)]
        + [(addresses["beta"][base + 10], .008)]
    )
    records.append(raw_spend(rpc, "Beta-aged-fanout", old, fanout, [beta]))
    _bump(4)

    # ------------------------------------------------------------------
    # CoinJoin-Fixtures (Form-Tests). Fremd-Peers = lab-faucet.
    # Spend-Pool + frische Peer-Fundings; Alters-Kohorte unangetastet.
    # ------------------------------------------------------------------
    peer_addrs = [new_address(rpc, "lab-faucet") for _ in range(60)]
    for i in range(0, len(peer_addrs), 12):
        chunk = peer_addrs[i : i + 12]
        set_time(rpc, int(_MOCK_CURSOR))
        rpc.call(
            "sendmany",
            "",
            json.dumps({a: SPEND_FUND_AMOUNT for a in chunk}, separators=(",", ":")),
            wallet="lab-faucet",
        )
        _bump(1)
    rescan_wallets(rpc, "lab-faucet")

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
    mine_next(rpc, 3, faucet)

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
    mine_next(rpc, 3, faucet)

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
    mine_next(rpc, 2, faucet)

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
    mine_next(rpc, 2, faucet)

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
    mine_next(rpc, 2, faucet)

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
    mine_next(rpc, 2, faucet)

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
    mine_next(rpc, 2, faucet)

    # Fan-out-own: Alias auf bestehendes Beta-aged-fanout
    for rec in records:
        if rec.get("name") == "Beta-aged-fanout":
            rec["expected_kind"] = "fan_out_own"
            rec["viewer_wallet"] = "lab-beta"
            rec["alias"] = "Fan-out-own"
            break

    # --- Tip ≈ Host-Jetzt: Bezugstag Steuerjahr = datetime.now(); Chain-Tip nachziehen ---
    tip_ts = int(time.time())
    tip_date = datetime.fromtimestamp(tip_ts, tz=timezone.utc).date().isoformat()
    _MOCK_CURSOR = mine_at(rpc, tip_ts, 3, faucet)
    phases.append({
        "label": "tip-now",
        "date": tip_date,
        "mock_ts": tip_ts,
        "height": int(rpc.call("getblockcount")),
        "note": "Tip auf Wanduhr; Mocktime danach aus (0)",
    })
    # Mocktime aus — weitere manuelle Mines nutzen wieder die Systemzeit.
    set_time(rpc, 0)
    _MOCK_CURSOR = 0

    gap = fund_gap_wallet(rpc)
    if gap.get("funded"):
        phases.append({
            "label": "gap-101",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "height": int(rpc.call("getblockcount")),
            "note": (
                f"{GAP_WALLET}: Empfang #{GAP_NEAR_INDEX} und #{GAP_FAR_INDEX}, "
                f"{gap['empty_between']} leere Indizes dazwischen. "
                "Nicht in WALLET_*."
            ),
        })

    write_env(rpc)
    report = {
        "tip_height": int(rpc.call("getblockcount")),
        "phases": phases,
        "tax_note": (
            f"Indizes 0–{AGE_INDEX_COUNT - 1}: unspent @{AGE_FUND_AMOUNT} BTC, "
            f"Blockzeiten zufällig gestern…vor 7 Jahren; "
            f"Indizes {AGE_INDEX_COUNT}–{AGE_INDEX_COUNT + SPEND_INDEX_COUNT - 1}: "
            f"Spend-Pool @{SPEND_FUND_AMOUNT} BTC für Hop/CJ."
        ),
        "records": records,
        "buendel": {
            "name": BUENDEL_NAME,
            "txid": buendel_record["txid"],
            "vout": int(buendel_record["vout_index"]),
            "block_time": int(buendel_record["block_time"]),
            "eigen_time": int(buendel_record["eigen_time"]),
            "input_count": 1 + BUENDEL_FREMDE,
            "foreign_inputs": BUENDEL_FREMDE,
            "viewer_wallet": "lab-alpha",
        },
    }
    (HERE / ".data" / "scenario-report.json").write_text(json.dumps(report, indent=2) + "\n")
    from herkunft_inventar import schreibe_inventar

    schreibe_inventar(rpc)

    # Expectations für Klassifikation / Soft-Label-Abnahme
    txclass = {
        "tip_height": report["tip_height"],
        "phases": phases,
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
        "phases": [p["label"] for p in phases],
        "gap_wallet": GAP_WALLET,
        "gap_far_index": GAP_FAR_INDEX,
        "gap_report": str(GAP_REPORT),
    }))


def add_gap_case(rpc: Rpc) -> None:
    """Nur das Gap-Wallet an eine schon erzeugte Chain hängen."""
    tip = int(rpc.call("getblockcount"))
    if tip < 101:
        raise RuntimeError(
            "Chain ist zu kurz für das Gap-Wallet — zuerst generate_scenarios.py"
        )
    set_time(rpc, 0)
    global _MOCK_CURSOR
    _MOCK_CURSOR = 0
    gap = fund_gap_wallet(rpc)
    report_path = HERE / ".data" / "scenario-report.json"
    if gap.get("funded") and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        phases = list(report.get("phases") or [])
        phases.append({
            "label": "gap-101",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "height": int(rpc.call("getblockcount")),
            "note": (
                f"{GAP_WALLET}: Empfang #{GAP_NEAR_INDEX} und #{GAP_FAR_INDEX}, "
                f"{gap['empty_between']} leere Indizes dazwischen. "
                "Nicht in WALLET_*."
            ),
        })
        report["phases"] = phases
        report["tip_height"] = int(rpc.call("getblockcount"))
        report_path.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps({
        "gap_wallet": GAP_WALLET,
        "gap_far_index": GAP_FAR_INDEX,
        "gap_miss": GAP_MISS,
        "gap_hit": GAP_HIT,
        "gap_report": str(GAP_REPORT),
        "tip_height": int(rpc.call("getblockcount")),
    }))

def add_volume_cohort(rpc: Rpc) -> None:
    """
    Hängt die Volumen-Kohorte an eine bestehende Chain.

    Dieselbe Stückzahl und Zeitstreuung wie die Alters-Kohorte, Beträge
    log-gleich von 1000 Sat bis 0,2 BTC. Bestehende UTXOs und Shape-Txs
    bleiben liegen.
    """
    global _MOCK_CURSOR
    rng = random.Random()
    t0, t1 = age_window_ts(days_back=365 * 7)
    for wallet in ("lab-faucet", *WALLETS):
        load_or_create(rpc, wallet)
    faucet = new_address(rpc, "lab-faucet")
    tip = int(rpc.call("getblockcount"))
    if tip < 1:
        raise RuntimeError("Chain ist leer — zuerst generate_scenarios.py ohne --volume-only")
    # Tip muss jünger sein als die jüngste Funding-Zeit, sonst lehnt Core ab.
    now = int(time.time())
    set_time(rpc, now)
    _MOCK_CURSOR = mine_at(rpc, now, 1, faucet)
    rescan_wallets(rpc, "lab-faucet", *WALLETS)
    need = VOL_INDEX_START + AGE_INDEX_COUNT
    addresses = {
        label: receive_addresses(rpc, wallet, max(LAB_RECEIVE_COUNT, need))
        for label, wallet in zip(LABELS, WALLETS)
    }
    lo, hi = t0 + 3600, t1
    vol_slots: list[tuple[int, int, float]] = []
    vol_sats: list[int] = []
    for i in range(AGE_INDEX_COUNT):
        amount = volume_btc(rng)
        vol_slots.append((rng.randint(lo, hi), VOL_INDEX_START + i, amount))
        vol_sats.append(round(amount * 1e8))
    vol_slots.sort(key=lambda row: (row[0], row[1]))
    for ts, index, amount in vol_slots:
        fund_index_at(rpc, addresses, faucet, index, ts, amount=amount)
    # Tip wieder auf die Wanduhr, damit Electrs nicht in IBD hängen bleibt.
    now = int(time.time())
    set_time(rpc, now)
    _MOCK_CURSOR = mine_at(rpc, now, 1, faucet)
    set_time(rpc, 0)
    _MOCK_CURSOR = 0
    rescan_wallets(rpc, *WALLETS, "lab-faucet")
    report_path = HERE / ".data" / "scenario-report.json"
    report: dict[str, Any] = {}
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    phases = list(report.get("phases") or [])
    phases.append({
        "label": "random-volume-funding",
        "date": f"{datetime.fromtimestamp(t0, tz=timezone.utc).date()}"
                f" … {datetime.fromtimestamp(t1, tz=timezone.utc).date()}",
        "height": int(rpc.call("getblockcount")),
        "note": (
            f"{AGE_INDEX_COUNT}× unspent je Wallet, Index {VOL_INDEX_START}…"
            f"{VOL_INDEX_START + AGE_INDEX_COUNT - 1}, "
            f"log-gleich {VOL_MIN_SATS} Sat … {VOL_MAX_BTC} BTC"
        ),
        "volume_sats_min": min(vol_sats),
        "volume_sats_max": max(vol_sats),
        "volume_sats_median": sorted(vol_sats)[len(vol_sats) // 2],
    })
    report["phases"] = phases
    report["tip_height"] = int(rpc.call("getblockcount"))
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Volumen-Kohorte: {AGE_INDEX_COUNT} Indizes × {len(LABELS)} Wallets, "
        f"{min(vol_sats)} … {max(vol_sats)} Sat, Tip {report['tip_height']}",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Erzeugt SatSage-Regtest-Wallets und Szenarien.")
    parser.add_argument("--native", action="store_true", help="native bitcoin-cli statt Docker Compose verwenden")
    parser.add_argument("--dry-run", action="store_true", help="nur Backend und Pfade prüfen, keine RPC-Aufrufe")
    parser.add_argument(
        "--volume-only",
        action="store_true",
        help="nur die Volumen-Kohorte an eine bestehende Chain hängen",
    )
    parser.add_argument(
        "--gap-only",
        action="store_true",
        help="nur lab-gap (Index 0 und 101) an eine bestehende Chain hängen",
    )
    args = parser.parse_args()
    native = choose_native(args.native)
    print(f"Backend: {'native bitcoin-cli' if native else 'Docker Compose'}")
    print(f"Lokale Env-Datei: {ENV_PATH}")
    if args.dry_run:
        return 0
    if args.volume_only and args.gap_only:
        print("Nur eines von --volume-only und --gap-only.", file=sys.stderr)
        return 2
    rpc = Rpc(native)
    if args.volume_only:
        add_volume_cohort(rpc)
        return 0
    if args.gap_only:
        add_gap_case(rpc)
        return 0
    run(rpc)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        raise SystemExit(1)
