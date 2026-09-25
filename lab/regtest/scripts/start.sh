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
# bitcoin/bitcoin chownt den Bind-Mount auf den Container-User. Ohne passende
# UID/GID gehört .data/bitcoin danach UID 101 (Mode 700) und der Host darf
# dort nichts mehr anlegen — auf GitHub-Runnern sofort, lokal oft unsichtbar.
export SATSAGE_LAB_UID="${SATSAGE_LAB_UID:-$(id -u)}"
export SATSAGE_LAB_GID="${SATSAGE_LAB_GID:-$(id -g)}"
# bitcoind mit -rpcuser/-rpcpassword legt kein .cookie an — electrs braucht
# aber CookieFile. Gleiche Credentials als Cookie schreiben, bevor electrs startet.
"${COMPOSE[@]}" up -d bitcoind
echo "Warte auf bitcoind…"
bereit=0
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T bitcoind bitcoin-cli -regtest \
      -rpcuser="$RPCUSER" -rpcpassword="$RPCPASSWORD" getblockchaininfo \
      >/dev/null 2>&1; then
    bereit=1
    break
  fi
  sleep 1
done
if [[ "$bereit" != 1 ]]; then
  echo "bitcoind antwortet nicht." >&2
  "${COMPOSE[@]}" logs --tail 40 bitcoind >&2 || true
  exit 1
fi
# Cookie im Container schreiben. Der Entrypoint chownt den Datadir nach dem
# ersten Start; ein Host-mkdir in .data/bitcoin/regtest scheitert dann, wenn
# UID/GID nicht gegriffen haben (CI: Permission denied).
# Ohne Newline — sonst 401 bei manchen electrs-Versionen.
"${COMPOSE[@]}" exec -T -u bitcoin bitcoind \
  sh -c 'mkdir -p "$BITCOIN_DATA/regtest" && printf "%s" "$1" > "$BITCOIN_DATA/regtest/.cookie"' \
  sh "${RPCUSER}:${RPCPASSWORD}"
if [[ "${SATSAGE_LAB_SKIP_MEMPOOL:-}" == "1" ]]; then
  "${COMPOSE[@]}" up -d electrs
else
  "${COMPOSE[@]}" up -d electrs mempool-db mempool-api mempool-web
fi
echo "Regtest gestartet:"
echo "  RPC       127.0.0.1:18443"
echo "  Electrum  127.0.0.1:50001"
if [[ "${SATSAGE_LAB_SKIP_MEMPOOL:-}" != "1" ]]; then
  echo "  Mempool   http://127.0.0.1:18080  (Explorer; Index braucht kurz)"
fi
