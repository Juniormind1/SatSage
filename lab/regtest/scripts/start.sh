#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
RPCUSER="${RPCUSER:-bitcoin}"
RPCPASSWORD="${RPCPASSWORD:-secret}"
if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'MSG'
Docker ist nicht installiert. Für einen nativen Linux-Start siehe
specter_plugin/scripts/run_bitcoind_regtest.sh und lab/regtest/README.md;
danach kann generate_scenarios.py mit SATSAGE_LAB_NATIVE=1 laufen.
MSG
  exit 2
fi
mkdir -p "$ROOT/.data/bitcoin" "$ROOT/.data/electrs"
# bitcoind mit -rpcuser/-rpcpassword legt kein .cookie an — electrs braucht
# aber CookieFile. Gleiche Credentials als Cookie schreiben, bevor electrs startet.
"${COMPOSE[@]}" up -d bitcoind
echo "Warte auf bitcoind…"
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T bitcoind bitcoin-cli -regtest \
      -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" getblockchaininfo \
      >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
COOKIE_DIR="$ROOT/.data/bitcoin/regtest"
mkdir -p "$COOKIE_DIR"
# Ohne Newline — sonst 401 bei manchen electrs-Versionen.
printf '%s' "${RPCUSER}:${RPCPASSWORD}" > "$COOKIE_DIR/.cookie"
chmod 644 "$COOKIE_DIR/.cookie"
"${COMPOSE[@]}" up -d electrs mempool-db mempool-api mempool-web
echo "Regtest gestartet:"
echo "  RPC       127.0.0.1:18443"
echo "  Electrum  127.0.0.1:50001"
echo "  Mempool   http://127.0.0.1:18080  (Explorer; Index braucht kurz)"
