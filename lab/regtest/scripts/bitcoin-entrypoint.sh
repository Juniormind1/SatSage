#!/bin/bash
# Wrapper um den Image-Entrypoint. groupmod ohne -o scheitert, wenn die
# Host-GID im Image schon vergeben ist (macOS staff = 20 = dialout).
set -e

if [ -n "${GID+x}" ] && [ "${GID}" != "0" ]; then
  if getent group "$GID" >/dev/null 2>&1; then
    groupmod -o -g "$GID" bitcoin
  fi
fi

exec /entrypoint.sh "$@"
