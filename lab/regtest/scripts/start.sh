#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'MSG'
Docker ist nicht installiert. Für einen nativen Linux-Start siehe
specter_plugin/scripts/run_bitcoind_regtest.sh und lab/regtest/README.md;
danach kann generate_scenarios.py mit SATSAGE_LAB_NATIVE=1 laufen.
MSG
  exit 2
fi
mkdir -p "$ROOT/.data/bitcoin" "$ROOT/.data/electrs"
"${COMPOSE[@]}" up -d
echo "Regtest gestartet: RPC 127.0.0.1:18443, Electrum 127.0.0.1:50001"
