#!/bin/sh
# StartOS container entrypoint. Volume `main` is mounted at /data.
set -eu

DATA="${SATSAGE_DATA_DIR:-/data}"
mkdir -p \
  "$DATA/utxo_cache" \
  "$DATA/immutable_cache" \
  "$DATA/sanctioned_cache" \
  "$DATA/label_cache"

if [ ! -f "$DATA/.env" ]; then
  umask 077
  : > "$DATA/.env"
fi
chmod 600 "$DATA/.env" 2>/dev/null || true
if [ -f "$DATA/.env.bak" ]; then
  chmod 600 "$DATA/.env.bak" 2>/dev/null || true
fi

export SATSAGE_MANAGED_BY="${SATSAGE_MANAGED_BY:-start9}"
export PYTHONUNBUFFERED=1

exec python3 /opt/satsage/server.py \
  --bind "${SATSAGE_BIND:-0.0.0.0}" \
  --port "${SATSAGE_PORT:-8730}" \
  --env "$DATA/.env" \
  --cache-dir "$DATA/utxo_cache" \
  --immutable-cache-dir "$DATA/immutable_cache" \
  --sanctions-dir "$DATA/sanctioned_cache" \
  --label-dir "$DATA/label_cache" \
  --no-browser \
  --plain-console
