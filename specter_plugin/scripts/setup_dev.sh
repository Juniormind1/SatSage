#!/usr/bin/env bash
# Richtet eine isolierte Specter-Desktop-Testumgebung für das SatSage-Plugin ein.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
VENV="${SPECTER_VENV:-$ROOT/.venv}"
DATA_DIR="${SPECTER_DATA_FOLDER:-$ROOT/.specter_dev}"

_python_ok() {
  "$1" -c "import sys" >/dev/null 2>&1
}

_venv_python() {
  if [[ -x "$1/bin/python" ]]; then
    echo "$1/bin/python"
  elif [[ -x "$1/Scripts/python.exe" ]]; then
    echo "$1/Scripts/python.exe"
  else
    return 1
  fi
}

# Specter braucht 3.9/3.10 (Wheels); Default: 3.10 falls vorhanden.
# python3 unter Git/Windows ist oft der Store-Stub — den überspringen.
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x /Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10 ]]; then
    PYTHON_BIN=/Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10
  elif command -v python3.10 >/dev/null 2>&1 && _python_ok python3.10; then
    PYTHON_BIN=python3.10
  elif [[ -x "${HOME}/AppData/Local/Programs/Python/Python310/python.exe" ]]; then
    PYTHON_BIN="${HOME}/AppData/Local/Programs/Python/Python310/python.exe"
  elif command -v python3 >/dev/null 2>&1 && _python_ok python3; then
    PYTHON_BIN=python3
  elif command -v python >/dev/null 2>&1 && _python_ok python; then
    PYTHON_BIN=python
  else
    PYTHON_BIN=python3
  fi
fi

echo "==> SatSage Specter Plugin — Setup"
echo "    plugin dir : $ROOT"
echo "    venv       : $VENV"
echo "    data folder: $DATA_DIR"

if ! _python_ok "$PYTHON_BIN"; then
  echo "Fehler: $PYTHON_BIN nicht gefunden oder nicht lauffähig." >&2
  echo "Setze PYTHON_BIN auf python.exe (z. B. Python310) und erneut ausführen." >&2
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

VENV_PY="$(_venv_python "$VENV")" || {
  echo "venv ohne python unter $VENV (weder bin/python noch Scripts/python.exe)" >&2
  exit 1
}

"$VENV_PY" -m pip install --upgrade pip wheel setuptools

echo "==> cryptoadvance.specter installieren"
"$VENV_PY" -m pip install "cryptoadvance.specter>=2.0.0" requests

echo "==> SatSage-Plugin (editable)"
"$VENV_PY" -m pip install -e "$ROOT"

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
echo "  4) Plugins → SatSage aktivieren"
echo "  5) API-Probe:             $ROOT/scripts/probe_api.py"
echo ""
echo "Hinweis: Für Bitcoin-Core-Regtest via Docker siehe docker-compose.regtest.yml"
