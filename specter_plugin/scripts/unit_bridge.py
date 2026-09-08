#!/usr/bin/env python3
"""Kleine Offline-Checks für bridge.py (ohne laufendes Specter)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from satsage.specterext.satsage.bridge import (  # noqa: E402
    build_context,
    extract_xpubs_from_text,
    key_to_info,
    wallet_to_info,
)


class FakeKey:
    def __init__(self):
        self.original = "[abcd1234/84h/0h/0h]zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
        self.xpub = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
        self.fingerprint = "abcd1234"
        self.derivation = "m/84h/0h/0h"


class FakeWallet:
    name = "Test Wallet"
    alias = "test_wallet"
    address_type = "bech32"
    description = "Single (Segwit)"
    keys = [FakeKey()]
    recv_descriptor = "wpkh([abcd1234/84h/0h/0h]zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs/0/*)#checksum"
    change_descriptor = None
    balance = {"trusted": 0.5}
    full_utxo = [
        {"txid": "aa" * 32, "vout": 0, "address": "bc1qtest", "amount": 0.5, "confirmations": 3}
    ]
    _transactions = {"tx1": {"txid": "bb" * 32}}


class FakeNode:
    alias = "default"
    name = "Bitcoin Core"
    host = "127.0.0.1"
    port = 18443
    user = "bitcoin"
    password = "secret"
    protocol = "http"
    external_node = True


class FakeWM:
    wallets = {"Test Wallet": FakeWallet()}


class FakeSpecter:
    wallet_manager = FakeWM()
    node = FakeNode()
    chain = "regtest"


def main() -> int:
    found = extract_xpubs_from_text(FakeWallet.recv_descriptor)
    assert found, "XPUB aus Descriptor erwartet"
    info = wallet_to_info(FakeWallet())
    assert info.xpubs, info
    assert info.utxo_count == 1
    ctx = build_context(FakeSpecter())
    d = ctx.to_dict(include_secrets=False)
    assert d["env_like"].get("NODE_IP") == "127.0.0.1"
    assert d["env_like"].get("NETWORK") == "regtest"
    assert d["env_like"].get("RPCPASSWORD") == "***"
    assert d["xpubs"]
    print("OK bridge unit checks")
    print("  xpubs:", len(d["xpubs"]))
    print("  env_like keys:", sorted(d["env_like"].keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
