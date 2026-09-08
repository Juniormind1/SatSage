#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker ist nicht installiert; native Prozesse bitte nach README beenden." >&2
  exit 2
fi
docker compose -f "$ROOT/docker-compose.yml" down
