#!/usr/bin/env python3
"""Electrs-Gap: Index 101 nur mit Limit über 100.

Voraussetzung: Labor läuft, ``generate_scenarios.py`` (oder ``--gap-only``)
hat ``.data/scenario-report-gap.json`` geschrieben.

Wallet ``lab-gap`` steht nicht in ``WALLET_*``. Der Prüfer liest den XPUB
zur Laufzeit aus Core (ohne private Schlüssel) und scannt zweimal über
``discover_wallet_scan_addresses``:

- Gap 100: Empfang #0 ja, #101 nein
- Gap 101: beide, inklusive des gemerkten Outpoints

Core scantxoutset findet #101 unabhängig vom Limit. Deshalb bleibt das
Wallet aus dem Herkunfts-Inventar. Kein Teil von Q6. Startet kein Docker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
HERE = SCRIPTS.parent
REPO = HERE.parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
REPORT = HERE / ".data" / "scenario-report-gap.json"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))

from infra_check import brauche  # noqa: E402


def _load_env(path: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not path.is_file():
        return werte
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        werte[k.strip()] = v.strip().strip('"').strip("'")
    return werte


def _kurz(txid: str) -> str:
    t = (txid or "").strip().lower()
    return f"{t[:8]}…{t[-4:]}" if len(t) >= 16 else t


def _outpoint(row: dict) -> tuple[str, int]:
    return str(row["txid"]).lower(), int(row["vout"])


def _hat(utxos: list[dict], ziel: tuple[str, int]) -> bool:
    for u in utxos:
        txid = str(u.get("txid") or u.get("tx_hash") or "").lower()
        try:
            vout = int(u.get("vout", u.get("tx_pos", -1)))
        except (TypeError, ValueError):
            continue
        if (txid, vout) == ziel:
            return True
    return False


def _warte_indexer(client, adresse: str, ziel: tuple[str, int], sekunden: float) -> list[dict]:
    from core.fulcrum_wallet import fetch_address_utxos_fulcrum

    ende = time.monotonic() + sekunden
    letzte: list[dict] = []
    while True:
        letzte = fetch_address_utxos_fulcrum(client, adresse) or []
        if _hat(letzte, ziel):
            return letzte
        if time.monotonic() >= ende:
            return letzte
        time.sleep(2)


def _scan(xpub: str, client, gap: int, max_index: int) -> tuple[set[str], list[dict]]:
    from core.wallet_sync_engine import discover_wallet_scan_addresses

    stand: list[dict] = []

    def nimm(teil: list[dict]) -> None:
        stand.clear()
        stand.extend(teil)

    adressen, _ende = discover_wallet_scan_addresses(
        xpub,
        fulcrum=client,
        max_index_per_chain=max_index,
        gap_limit=gap,
        start_index=0,
        on_utxos_update=nimm,
    )
    return set(adressen), list(stand)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument(
        "--warte", type=float, default=90.0,
        help="Sekunden, bis Electrs den Outpoint an Index 101 indiziert hat",
    )
    args = parser.parse_args()

    fehl = brauche("bitcoind", "electrs")
    if fehl is not None:
        return fehl
    if not args.report.is_file():
        print(
            f"Gap-Bericht fehlt: {args.report}\n"
            "Zuerst generate_scenarios.py oder generate_scenarios.py --gap-only.",
            file=sys.stderr,
        )
        return 1

    bericht = json.loads(args.report.read_text(encoding="utf-8"))
    near_addr = str(bericht["near_address"])
    far_addr = str(bericht["far_address"])
    near_op = _outpoint(bericht["near"])
    far_op = _outpoint(bericht["far"])
    gap_miss = int(bericht["gap_miss"])
    gap_hit = int(bericht["gap_hit"])
    far_index = int(bericht["far_index"])
    if int(bericht.get("empty_between") or 0) < gap_miss:
        print(
            f"Bericht: nur {bericht.get('empty_between')} leere Indizes, "
            f"für Limit {gap_miss} braucht es mindestens so viele.",
            file=sys.stderr,
        )
        return 1

    werte = _load_env(ENV_PATH)
    os.environ["NETWORK"] = werte.get("NETWORK") or "regtest"
    import main as satsage_main
    from core.derivation import derive_address_at_index, register_script_types
    from core.fulcrum_client import connect_fulcrum
    from generate_scenarios import (  # noqa: E402
        Rpc, choose_native, load_or_create, public_receive_key,
    )

    satsage_main.set_chain_network(os.environ["NETWORK"])
    rpc = Rpc(choose_native(False))
    wallet = str(bericht.get("wallet") or "lab-gap")
    load_or_create(rpc, wallet)
    xpub, script = public_receive_key(rpc, wallet)
    register_script_types({xpub: script or "segwit"})
    abgeleitet = derive_address_at_index(xpub, 0, far_index)
    if abgeleitet != far_addr:
        print(
            "Abgeleitete Empfangsadresse an Index "
            f"{far_index} trifft die Core-Adresse nicht "
            f"(Skript {script}, Netz {os.environ['NETWORK']}).",
            file=sys.stderr,
        )
        return 1

    host = werte.get("FULCRUM_HOST") or "127.0.0.1"
    port = int(werte.get("FULCRUM_PORT") or "50001")
    ssl = str(werte.get("FULCRUM_SSL") or "false").lower() in ("1", "true", "ja")
    client, fehler = connect_fulcrum(host, port, use_ssl=ssl, timeout=30)
    if client is None:
        print(f"Electrs nicht verbunden: {fehler}", file=sys.stderr)
        return 1
    print(f"Electrs {host}:{port} ({client.server_software or '?'})", flush=True)

    try:
        print(f"Warte auf Index #{far_index} im Indexer…", flush=True)
        weit = _warte_indexer(client, far_addr, far_op, args.warte)
        if not _hat(weit, far_op):
            print(
                f"Electrs zeigt {_kurz(far_op[0])}:{far_op[1]} "
                f"an Index #{far_index} nach {args.warte:.0f}s nicht. "
                "Indexer hinter der Kette, kein Gap-Befund.",
                file=sys.stderr,
            )
            return 1
        nah = _warte_indexer(client, near_addr, near_op, 10)
        if not _hat(nah, near_op):
            print(
                f"Electrs zeigt {_kurz(near_op[0])}:{near_op[1]} "
                "an Index #0 nicht.",
                file=sys.stderr,
            )
            return 1

        max_index = far_index + 1
        print(f"Gap-Scan mit Limit {gap_miss}…", flush=True)
        adressen_miss, _utxos_miss = _scan(xpub, client, gap_miss, max_index)
        if near_addr not in adressen_miss:
            print(
                f"FAIL Limit {gap_miss}: Index #0 fehlt im Walk.",
                file=sys.stderr,
            )
            return 1
        if far_addr in adressen_miss:
            print(
                f"FAIL Limit {gap_miss}: Index #{far_index} wurde gefunden. "
                "Der Walk hätte an den leeren Indizes stoppen müssen.",
                file=sys.stderr,
            )
            return 1
        print(
            f"  OK  Limit {gap_miss}: Index #0 da, #{far_index} nicht",
            flush=True,
        )

        print(f"Gap-Scan mit Limit {gap_hit}…", flush=True)
        adressen_hit, utxos_hit = _scan(xpub, client, gap_hit, max_index)
        if near_addr not in adressen_hit or far_addr not in adressen_hit:
            print(
                f"FAIL Limit {gap_hit}: Index #0 oder #{far_index} fehlt.",
                file=sys.stderr,
            )
            return 1
        if not _hat(utxos_hit, far_op):
            print(
                f"FAIL Limit {gap_hit}: Adresse da, Outpoint "
                f"{_kurz(far_op[0])}:{far_op[1]} nicht im Walk.",
                file=sys.stderr,
            )
            return 1
        print(
            f"  OK  Limit {gap_hit}: Index #{far_index} "
            f"{_kurz(far_op[0])}:{far_op[1]}",
            flush=True,
        )
    finally:
        try:
            client.close()
        except Exception:
            pass

    print(
        f"OK electrs-gap wallet={wallet} miss={gap_miss} hit={gap_hit} "
        f"index={far_index}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        raise SystemExit(1)
