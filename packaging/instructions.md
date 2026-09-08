# SatSage on StartOS

SatSage reconstructs watch-only Bitcoin wallet history from XPUBs and
descriptors. It does not store seeds or private keys.

## Requirements

SatSage depends on two services on the same StartOS device:

- **Bitcoin** (Bitcoin Core) — RPC plus the cookie file
- **Electrs** — address history and UTXO lookups

Both must be installed, configured, and synced before SatSage is useful.
This package does **not** put SatSage “on Tor” or on the public internet.
LAN / Tor / clearnet exposure is whatever you enable in StartOS for this
service.

## First start

1. Start Bitcoin and Electrs and wait until they are healthy.
2. Start SatSage.
3. Open **Web UI**. StartOS asks for HTTP Basic auth:
   - username: `admin`
   - password: the generated service password (StartOS → SatSage →
     Properties / the rotate-password action)
4. The same password is the SatSage login.

If you rotate the password, stop SatSage first, run **Rotate Web UI
Password**, then start it again.

## Data

Wallets, caches, and the password hash live on the service volume.
A StartOS backup of SatSage includes `.env`, the password hash, and the
analysis caches. Restoring a backup restores that volume.

## Limitations

- Watch-only: no signing, no seed management.
- Public Electrum servers stay off unless you explicitly opt in.
- Only the x86_64 package is built today.
