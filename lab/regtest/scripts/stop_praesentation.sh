#!/usr/bin/env bash
# Beendet die Präsentations-GUI und das Docker-Labor.
# Chain und Caches unter lab/regtest/.data/ bleiben liegen.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/.data/gui-server.pid"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" || true)"
  if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "SatSage beendet (PID $pid)."
  fi
  rm -f "$PID_FILE"
fi

"$ROOT/scripts/stop.sh"
echo "Labor gestoppt. Daten bleiben unter lab/regtest/.data/."
