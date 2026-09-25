#!/usr/bin/env bash
# Präsentation: vorhandenes Regtest-Labor + SatSage-GUI.
# Baut nichts neu und erzeugt keine Szenarien. Chain und Caches bleiben
# unter lab/regtest/.data/.
#
#   ./scripts/start_praesentation.sh
#   ./scripts/start_praesentation.sh --no-browser
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
DATA="$ROOT/.data"
ENV_FILE="$DATA/.regtest.env"
SESSION="$DATA/gui-session.json"
URL_FILE="$DATA/gui-url.txt"
GUI_LOG="$DATA/gui-server.log"
PID_FILE="$DATA/gui-server.pid"
PORT="${SATSAGE_LAB_PORT:-8731}"
OPEN_BROWSER=1

for arg in "$@"; do
  case "$arg" in
    --no-browser) OPEN_BROWSER=0 ;;
    -h|--help)
      echo "Startet Docker-Labor (bitcoind, Electrs, Mempool) und die SatSage-GUI."
      echo "  --no-browser   URL nur ausgeben, Browser nicht öffnen"
      echo "  SATSAGE_LAB_PORT  GUI-Port (Default 8731, damit 8730 frei bleibt)"
      exit 0
      ;;
    *) echo "Unbekannt: $arg" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Lab-Env fehlt: $ENV_FILE" >&2
  echo "Einmalig: cd lab/regtest && ./scripts/start.sh && ./scripts/generate_scenarios.py" >&2
  exit 2
fi

docker_bin() {
  if command -v docker >/dev/null 2>&1; then
    command -v docker
    return
  fi
  if [[ -x /usr/local/bin/docker ]]; then
    echo /usr/local/bin/docker
    return
  fi
  return 1
}

if ! docker_bin >/dev/null; then
  echo "Docker fehlt. Docker Desktop installieren und dieses Skript erneut starten." >&2
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "Starte Docker Desktop…"
  open -a Docker || {
    echo "Docker Desktop ließ sich nicht öffnen." >&2
    exit 2
  }
  echo "Warte auf den Docker-Daemon…"
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  if ! docker info >/dev/null 2>&1; then
    echo "Docker-Daemon antwortet nicht. Desktop fertig starten lassen, dann erneut." >&2
    exit 2
  fi
fi

echo "Starte bitcoind, Electrs und Mempool (bestehende Chain)…"
"$ROOT/scripts/start.sh"

# Ein stehender Tip (Tage alt) hält Core in initialblockdownload.
# Electrs wartet dann ewig auf „Block-Download“ und beantwortet keine Anfrage.
rpc() {
  "${COMPOSE[@]}" exec -T bitcoind bitcoin-cli -regtest \
    -rpcuser=bitcoin -rpcpassword=secret "$@"
}
echo "Ziehe den Chain-Tip auf jetzt, damit Electrs den Index freigibt…"
if ! rpc loadwallet lab-faucet >/dev/null 2>&1; then
  rpc listwallets >/dev/null
fi
rpc setmocktime "$(date +%s)" >/dev/null
FAUCET_ADDR="$(rpc -rpcwallet=lab-faucet getnewaddress)"
rpc generatetoaddress 1 "$FAUCET_ADDR" >/dev/null
rpc setmocktime 0 >/dev/null

# Electrs löst „bitcoind“ erst auf, wenn der Node im Compose-Netz steht.
# Ein zu früher Start endet in „sync failed“ / Name not known — dann neu starten.
echo "Warte, bis Electrs den Node im Docker-Netz findet…"
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T electrs getent hosts bitcoind >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"${COMPOSE[@]}" restart electrs >/dev/null

echo "Warte auf Electrs (Port 50001)…"
electrs_ok=0
for _ in $(seq 1 40); do
  if python3 - <<'PY'
import json, socket, sys
try:
    s = socket.create_connection(("127.0.0.1", 50001), 3)
    s.sendall((json.dumps({"id": 1, "method": "blockchain.headers.subscribe", "params": []}) + "\n").encode())
    s.settimeout(4)
    data = b""
    while b"\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    msg = json.loads(data.decode().splitlines()[0])
    height = (msg.get("result") or {}).get("height")
    if height is None:
        sys.exit(1)
    print(height)
except Exception:
    sys.exit(1)
PY
  then
    electrs_ok=1
    break
  fi
  if "${COMPOSE[@]}" logs --since 20s electrs 2>/dev/null | grep -q "electrs failed"; then
    echo "Electrs-Sync abgebrochen, starte den Indexer erneut…"
    "${COMPOSE[@]}" restart electrs >/dev/null
  fi
  sleep 2
done
if [[ "$electrs_ok" -ne 1 ]]; then
  echo "Electrs liefert noch keinen Tip. Log:" >&2
  "${COMPOSE[@]}" logs --tail 20 electrs >&2 || true
  exit 1
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  url=""
  if [[ -s "$SESSION" ]]; then
    url="$(python3 -c "import json; print(json.load(open('$SESSION')).get('url') or '')" 2>/dev/null || true)"
  fi
  if [[ -z "$url" && -f "$URL_FILE" ]]; then
    url="$(cat "$URL_FILE")"
  fi
  echo "SatSage läuft schon auf Port $PORT."
  if [[ -n "$url" ]]; then
    echo ""
    echo "Browser öffnen:"
    echo "  open \"$url\""
    echo ""
    if [[ "$OPEN_BROWSER" -eq 1 ]]; then
      open "$url"
      echo "Browser wurde geöffnet."
    fi
  else
    echo "Keine gespeicherte URL. Im Log nach der Zeile SATSAGE_SESSION suchen: $GUI_LOG"
  fi
  exit 0
fi

PYTHON="$REPO/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

rm -f "$SESSION"
mkdir -p "$DATA/utxo_cache" "$DATA/immutable_cache" "$DATA/sanctioned_cache"
echo "Starte SatSage auf 127.0.0.1:$PORT …"
(
  cd "$REPO"
  export PYTHONUNBUFFERED=1
  export SATSAGE_SESSION_FILE="$SESSION"
  export SANKTION_MAX_HOPS_CAP=100
  exec "$PYTHON" server.py \
    --env "$ENV_FILE" \
    --cache-dir "$DATA/utxo_cache" \
    --immutable-cache-dir "$DATA/immutable_cache" \
    --sanctions-dir "$DATA/sanctioned_cache" \
    --port "$PORT" \
    --no-browser
) >>"$GUI_LOG" 2>&1 &
echo $! >"$PID_FILE"

url=""
for _ in $(seq 1 40); do
  if [[ -s "$SESSION" ]]; then
    url="$(python3 -c "import json; print(json.load(open('$SESSION')).get('url') or '')")"
    if [[ -n "$url" ]]; then
      break
    fi
  fi
  sleep 0.4
done
if [[ -z "$url" ]]; then
  echo "SatSage-Sitzung kam nicht. Letzte Logzeilen:" >&2
  tail -30 "$GUI_LOG" >&2 || true
  exit 1
fi
printf '%s\n' "$url" >"$URL_FILE"

echo ""
echo "Präsentation bereit."
echo "  SatSage   $url"
echo "  Electrs   127.0.0.1:50001"
echo "  Explorer  http://127.0.0.1:18080"
echo ""
echo "Browser öffnen:"
echo "  open \"$url\""
echo "  Explorer: open http://127.0.0.1:18080"
echo ""
echo "Stop: ./scripts/stop_praesentation.sh"
echo ""

if [[ "$OPEN_BROWSER" -eq 1 ]]; then
  open "$url"
  echo "Browser wurde geöffnet."
fi
