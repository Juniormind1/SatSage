#!/usr/bin/env python3
"""Prüft Lab-Sanction-Chains gegen analyze.check_wallet_utxos_sanctions.

Voraussetzung: Lab läuft (bitcoind + Fulcrum), generate_scenarios +
generate_sanctions_scenarios bereits gelaufen.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
REPORT = HERE / ".data" / "scenario-report-sanctions.json"
SANCTIONS_DIR = HERE / ".data" / "sanctioned_cache"
ENV_PATH = HERE / ".data" / ".regtest.env"

sys.path.insert(0, str(REPO))


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depths", default="1,3,10,25,100")
    args = parser.parse_args()
    if not REPORT.is_file():
        print(f"Report fehlt: {REPORT}", file=sys.stderr)
        return 1

    os.environ.setdefault("SANKTION_MAX_HOPS_CAP", "100")
    os.environ.setdefault("NETWORK", "regtest")

    import main as satsage_main
    from analyze import check_wallet_utxos_sanctions
    from sanctioned import load_sanctioned_xbt_addresses

    werte = _load_env(ENV_PATH)
    for k, v in werte.items():
        os.environ.setdefault(k, v)

    listed, _meta = load_sanctioned_xbt_addresses(cache_dir=SANCTIONS_DIR)
    if not listed:
        print("Pseudo-Liste leer", file=sys.stderr)
        return 1

    client, quelle = satsage_main.resolve_sanctions_preferred_client(werte)
    if client is None:
        print("Kein Electrum/Fulcrum für get_tx", file=sys.stderr)
        return 1
    cache_root = HERE / ".data" / "immutable_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    get_tx = satsage_main.make_cached_fulcrum_get_tx(client, cache_root)
    print(f"get_tx Quelle: {quelle}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    depths = [int(x) for x in args.depths.split(",") if x.strip()]
    failures = 0

    for chain in report.get("chains", []):
        utxo = {
            "txid": chain["sink_txid"],
            "vout": int(chain["sink_vout"]),
            "address": chain["sink_address"],
            "value_sats": int(round(float(chain.get("amount_btc", 0)) * 1e8)),
            "key": chain["sink_utxo"],
        }
        expect_at = chain.get("expect_hit_at_hops")
        start = chain["start_address"]
        for depth in depths:
            hits, checked, _abort = check_wallet_utxos_sanctions(
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
            ok = got_hit is should_hit
            if not ok:
                failures += 1
            print(
                f"{'OK' if ok else 'FAIL'} {chain['name']} max_hops={depth} "
                f"expect_hit={should_hit} got={got_hit} checked={checked} "
                f"hit_hops={[h.get('hop') for h in hits]}"
            )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
