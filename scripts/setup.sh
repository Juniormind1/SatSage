#!/usr/bin/env bash
# SatSage (satsage) — Entwicklungsumgebung einrichten (idempotent).
# Aufruf aus dem Repo-Wurzelverzeichnis: bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY_BIN="$(command -v python3.12 || command -v python3.11 || command -v python3)"
echo "Interpreter: $PY_BIN ($("$PY_BIN" --version))"

if [ ! -x .venv/bin/python ]; then
  "$PY_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "--- Tests ---"
.venv/bin/python -m unittest discover -s tests
echo "Setup abgeschlossen. Aktivieren mit: source .venv/bin/activate"
