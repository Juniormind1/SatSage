#!/usr/bin/env bash
# Richtet eine isolierte Specter-Desktop-Testumgebung für das xPubQuery-Plugin ein.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
VENV="${SPECTER_VENV:-$ROOT/.venv}"
DATA_DIR="${SPECTER_DATA_FOLDER:-$ROOT/.specter_dev}"
# Specter braucht 3.9/3.10 (Wheels); Default: 3.10 falls vorhanden
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x /Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10 ]]; then
    PYTHON_BIN=/Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10
  elif command -v python3.10 >/dev/null 2>&1; then
    PYTHON_BIN=python3.10
  else
    PYTHON_BIN=python3
  fi
fi

echo "==> xPubQuery Specter Plugin — Setup"
echo "    plugin dir : $ROOT"
echo "    venv       : $VENV"
echo "    data folder: $DATA_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Fehler: $PYTHON_BIN nicht gefunden." >&2
  exit 1
fi

PY_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "    python     : $PY_VER ($PYTHON_BIN)"

# Specter empfiehlt 3.9/3.10; neuere Versionen oft ok, aber warnen
case "$PY_VER" in
  3.9|3.10|3.11|3.12) ;;
  *)
    echo "Hinweis: Specter Desktop ist offiziell auf 3.9/3.10 getestet (du: $PY_VER)."
    ;;
esac

if [[ ! -d "$VENV" ]]; then
  echo "==> Virtualenv anlegen"
  "$PYTHON_BIN" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel setuptools

echo "==> cryptoadvance.specter installieren"
pip install "cryptoadvance.specter>=2.0.0" requests

echo "==> xPubQuery-Plugin (editable)"
pip install -e "$ROOT"

mkdir -p "$DATA_DIR"
mkdir -p "$ROOT/.run"

cat > "$ROOT/.run/env.sh" <<EOF
# generiert von setup_dev.sh — nicht committen
export SPECTER_DATA_FOLDER="$DATA_DIR"
export SPECTER_API_ACTIVE=True
export SERVICES_DEVSTATUS_THRESHOLD=alpha
export HOST=127.0.0.1
export PORT=25441
EOF

echo ""
echo "Fertig."
echo ""
echo "Nächste Schritte:"
echo "  1) Optional Regtest-Node:  $ROOT/scripts/run_bitcoind_regtest.sh"
echo "  2) Specter starten:       $ROOT/scripts/run_specter.sh"
echo "  3) Browser:               http://127.0.0.1:25441"
echo "  4) Plugins → xPubQuery aktivieren"
echo "  5) API-Probe:             $ROOT/scripts/probe_api.py"
echo ""
echo "Hinweis: Für Bitcoin-Core-Regtest via Docker siehe docker-compose.regtest.yml"
