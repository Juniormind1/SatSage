#!/usr/bin/env bash
# Startet Specter Desktop mit xPubQuery-Plugin (DevConfig).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${SPECTER_VENV:-$ROOT/.venv}"

if [[ ! -f "$VENV/bin/activate" ]]; then
  echo "Kein venv unter $VENV — zuerst: $ROOT/scripts/setup_dev.sh" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

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
echo "Plugin: Sidebar → Plugins / Choose plugins → xPubQuery"
echo ""

exec python -m cryptoadvance.specter server \
  --config satsage.specterext.satsage.app_config.DevConfig \
  --debug
