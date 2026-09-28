# SatSage on StartOS

SatSage reconstructs watch-only Bitcoin wallet history from XPUBs and
descriptors. It does not store seeds or private keys.

## Requirements

SatSage depends on services on the same StartOS device:

- **Bitcoin** (Bitcoin Core) — RPC plus the cookie file (**required**)
- **Electrs** *or* **Fulcrum** — Electrum index for address history and UTXOs

Use the SatSage action **Select Indexer** to pick Electrs or Fulcrum (default
for existing installs: Electrs). Install and sync the chosen indexer before
expecting wallet scans to work.

This package does **not** put SatSage “on Tor” or on the public internet.
LAN / Tor / clearnet exposure is whatever you enable in StartOS for this
service.

## First start

1. Start Bitcoin and your chosen indexer (Electrs or Fulcrum); wait until healthy.
2. In SatSage, run **Select Indexer** if you want Fulcrum instead of Electrs.
3. Start SatSage.
4. Open **Web UI**. There is no StartOS password and no username `admin`.
   The address printed in the service log is inside the container; do not
   paste it into a browser.
5. SatSage opens without a password. A password exists only if you set one
   in SatSage → Settings. That password is optional and encrypts `.env`.

## Data

Wallets, caches, and the password hash live on the service volume.
A StartOS backup of SatSage includes `.env`, the password hash, and the
analysis caches. Restoring a backup restores that volume.

## Bitcoin Core RPC

SatSage only calls a fixed allowlist of read-only Bitcoin Core RPC methods
(chain lookups and `scantxoutset`; for importing Core wallets also
`listwallets`, `listwalletdir`, `loadwallet` and public-only
`listdescriptors`). Anything else is blocked inside SatSage before it reaches
the node, and the header shows a red “Core RPC blocked” pill.

On StartOS SatSage reads the Bitcoin package's cookie file. That cookie user
is shared with other services, so an `rpcwhitelist` for it would restrict
them too. Treat `rpcwhitelist` / `rpcauth` / `disablewallet` as a note for
your own standalone node only (see the SatSage handbook, chapter 9, “Bitcoin
Core absichern”); do not change the StartOS Bitcoin settings for SatSage.

## Limitations

- Watch-only: no signing, no seed management.
- Public Electrum servers stay off unless you explicitly opt in.
- Only the x86_64 package is built today.
- Fulcrum needs more disk/RAM than Electrs; follow Fulcrum’s StartOS docs.
