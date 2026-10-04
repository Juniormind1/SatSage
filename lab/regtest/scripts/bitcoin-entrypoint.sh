#!/bin/bash
# Wrapper um den Image-Entrypoint. groupmod ohne -o scheitert, wenn die
# Host-GID im Image schon vergeben ist (macOS staff = 20 = dialout).
set -e

if [ -n "${GID+x}" ] && [ "${GID}" != "0" ]; then
  if getent group "$GID" >/dev/null 2>&1; then
    groupmod -o -g "$GID" bitcoin
  fi
fi

# Zweiter Labor-User. Klartext-Passwort nur hier im Labor: lab-whitelist.
# Sobald eine rpcwhitelist existiert, ist die Vorgabe für alle anderen User
# „keine Methode“ (Core setzt rpcwhitelistdefault dann auf 1). 0 hebt das auf:
# bitcoin/secret (Electrs, Szenarien, Healthcheck) darf weiter alles, satsage
# bleibt auf den Lese-Methoden.
mkdir -p /home/bitcoin/.bitcoin
cat > /home/bitcoin/.bitcoin/bitcoin.conf << 'EOF'
rpcauth=satsage:00112233445566778899aabbccddeeff$cb721729928b84fc5bfdcbc50eae8a6f12abca12e6036a7d57505d0ab2aff24c
rpcwhitelist=satsage:getblockchaininfo,getblockhash,getblockheader,getblock,getrawtransaction,scantxoutset,estimatesmartfee
rpcwhitelistdefault=0
EOF
chmod 644 /home/bitcoin/.bitcoin/bitcoin.conf
if id bitcoin >/dev/null 2>&1; then
  chown bitcoin:bitcoin /home/bitcoin/.bitcoin/bitcoin.conf
fi

exec /entrypoint.sh "$@"
