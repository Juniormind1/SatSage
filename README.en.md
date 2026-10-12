<p align="center">
  <img src="web/img/logo.jpg" alt="SatSage" width="320">
</p>

<p align="center">
  <strong>know your sats</strong><br>
  <em>Where your sats came from and when — on-chain age for taxes and overview</em>
</p>

https://github.com/user-attachments/assets/6d43ef05-3753-498f-8ac2-c02413820271

<p align="center">
  <a href="VERSION"><img src="https://img.shields.io/badge/version-0.9.2-f7931a?style=flat-square" alt="Version 0.9.2"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/badge/UI-localhost%20Web--GUI-111111?style=flat-square" alt="Web-GUI">
</p>

---

## What is SatSage?

**SatSage** (pun: *Sat Sage* / *Sats Age*) analyzes xPub single-sig and multisig wallets and shows **where your sats came from and when** — in particular when they entered or left an xPub wallet. From this you can read the on-chain holding period. It does not replace exchange history or purchase receipts.

The web GUI is available in German and English (`UI_LANG=en` or in the settings).

## Data sources

Your own Electrum server (electrs/Fulcrum) → compact block filters via Bitcoin P2P (`--bip158`) → public onion/clearnet servers only after confirmation. A local pruned node is detected for fast UTXO scans.

## Getting started

```bash
pip install -r requirements.txt
python server.py
```

Then open the local web GUI shown in the console.

## Documentation

The detailed manual is currently available in German only: see [README.md](README.md) and [`doc/handbuch.html`](doc/handbuch.html).
