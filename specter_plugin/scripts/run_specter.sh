#!/usr/bin/env bash
# Startet Specter Desktop mit SatSage-Plugin (DevConfig).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${SPECTER_VENV:-$ROOT/.venv}"

if [[ -x "$VENV/bin/python" ]]; then
  VENV_PY="$VENV/bin/python"
elif [[ -x "$VENV/Scripts/python.exe" ]]; then
  VENV_PY="$VENV/Scripts/python.exe"
else
  echo "Kein venv unter $VENV — zuerst: $ROOT/scripts/setup_dev.sh" >&2
  exit 1
fi

if [[ -f "$ROOT/.run/env.sh" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.run/env.sh"
fi

export SPECTER_DATA_FOLDER="${SPECTER_DATA_FOLDER:-$ROOT/.specter_dev}"
export SPECTER_API_ACTIVE="${SPECTER_API_ACTIVE:-True}"
export SERVICES_DEVSTATUS_THRESHOLD="${SERVICES_DEVSTATUS_THRESHOLD:-alpha}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-25441}"

echo "==> Specter Desktop"
echo "    data : $SPECTER_DATA_FOLDER"
echo "    url  : http://${HOST}:${PORT}"
echo "    cfg  : satsage.specterext.satsage.app_config.DevConfig"
echo ""
echo "Login-Default (falls Auth aktiv): admin / admin"
echo "Plugin: Sidebar → Plugins / Choose plugins → SatSage"
echo ""

exec "$VENV_PY" -m cryptoadvance.specter server \
  --config satsage.specterext.satsage.app_config.DevConfig \
  --debug
