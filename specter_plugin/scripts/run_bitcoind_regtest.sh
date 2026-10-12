#!/usr/bin/env bash
# Startet bitcoind im Regtest (Docker bevorzugt, sonst lokales bitcoind).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATADIR="${BTCD_REGTEST_DATA_DIR:-$ROOT/.bitcoin_regtest}"
RPCUSER="${RPCUSER:-bitcoin}"
RPCPASSWORD="${RPCPASSWORD:-secret}"
RPCPORT="${RPCPORT:-18443}"

echo "==> Bitcoin Core Regtest"
echo "    RPC: http://127.0.0.1:${RPCPORT}  user=${RPCUSER}"

if command -v docker >/dev/null 2>&1; then
  echo "    via Docker Compose ($ROOT/docker-compose.regtest.yml)"
  cd "$ROOT"
  docker compose -f docker-compose.regtest.yml up -d
  echo ""
  echo "Warte auf RPC..."
  for i in $(seq 1 30); do
    if docker compose -f docker-compose.regtest.yml exec -T bitcoind \
        bitcoin-cli -regtest -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" getblockchaininfo >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  docker compose -f docker-compose.regtest.yml exec -T bitcoind \
    bitcoin-cli -regtest -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" createwallet "specter" 2>/dev/null || true
  ADDR=$(docker compose -f docker-compose.regtest.yml exec -T bitcoind \
    bitcoin-cli -regtest -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" -rpcwallet=specter getnewaddress)
  docker compose -f docker-compose.regtest.yml exec -T bitcoind \
    bitcoin-cli -regtest -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" -rpcwallet=specter generatetoaddress 101 "$ADDR" >/dev/null
  echo "101 Blöcke gemined → $ADDR"
else
  if ! command -v bitcoind >/dev/null 2>&1; then
    echo "Weder Docker noch bitcoind gefunden." >&2
    echo "Installiere Docker Desktop oder Bitcoin Core, dann erneut ausführen." >&2
    exit 1
  fi
  mkdir -p "$DATADIR"
  if ! pgrep -f "bitcoind.*-regtest" >/dev/null 2>&1; then
    bitcoind -regtest -daemon \
      -datadir="$DATADIR" \
      -rpcuser="$RPCUSER" \
      -rpcpassword="$RPCPASSWORD" \
      -rpcport="$RPCPORT" \
      -fallbackfee=0.0001 \
      -server=1
    sleep 2
  fi
  bitcoin-cli -regtest -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" createwallet specter 2>/dev/null || true
  ADDR=$(bitcoin-cli -regtest -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" -rpcwallet=specter getnewaddress)
  bitcoin-cli -regtest -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" -rpcwallet=specter generatetoaddress 101 "$ADDR" >/dev/null
  echo "101 Blöcke gemined → $ADDR"
fi

echo ""
echo "In Specter Node konfigurieren:"
echo "  Host: localhost"
echo "  Port: ${RPCPORT}"
echo "  User: ${RPCUSER}"
echo "  Pass: ${RPCPASSWORD}"
echo "  Network: regtest"
