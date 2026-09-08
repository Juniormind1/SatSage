#!/usr/bin/env python3
"""
Prüft Specter REST-API und listet Wallets/UTXOs (sofern vorhanden).

Voraussetzung:
  - Specter läuft (run_specter.sh)
  - SPECTER_API_ACTIVE=True (DevConfig default)
  - User/Pass (Default admin:admin)

Usage:
  python scripts/probe_api.py
  python scripts/probe_api.py --base http://127.0.0.1:25441 --user admin --password admin
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from base64 import b64encode


def _req(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    data: dict | None = None,
    auth: tuple[str, str] | None = None,
) -> dict:
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    if auth is not None:
        token = b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        hdrs["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {url}\n{detail}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Verbindung fehlgeschlagen: {url}\n{e}") from e


def main() -> int:
    p = argparse.ArgumentParser(description="Specter API Probe für SatSage")
    p.add_argument("--base", default="http://127.0.0.1:25441")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin")
    args = p.parse_args()
    base = args.base.rstrip("/")

    print(f"==> Liveness {base}/healthz/liveness …")
    try:
        _req("GET", f"{base}/healthz/liveness")
        print("    OK")
    except SystemExit as e:
        # ältere/neuere Pfade
        print(f"    (healthz optional) {e}")

    print("==> JWT Token holen …")
    token_resp = _req(
        "POST",
        f"{base}/api/v1alpha/token",
        auth=(args.user, args.password),
        data={
            "jwt_token_description": "SatSage probe",
            "jwt_token_life": "1 days",
        },
    )
    jwt = token_resp.get("jwt_token")
    if not jwt:
        print(json.dumps(token_resp, indent=2))
        return 1
    print(f"    token id: {token_resp.get('jwt_token_id')}")

    headers = {"Authorization": f"Bearer {jwt}"}

    print("==> GET /api/v1alpha/specter …")
    specter = _req("GET", f"{base}/api/v1alpha/specter", headers=headers)
    aliases = specter.get("wallets_alias") or []
    chain = (specter.get("info") or {}).get("chain")
    print(f"    chain={chain}  wallets={aliases}")

    for alias in aliases:
        print(f"==> GET /api/v1alpha/wallets/{alias} …")
        w = _req("GET", f"{base}/api/v1alpha/wallets/{alias}", headers=headers)
        # Response kann wallet-dict unter alias-key enthalten
        block = w.get(alias) if isinstance(w.get(alias), dict) else w
        name = block.get("name") if isinstance(block, dict) else alias
        utxo = w.get("utxo") or (block.get("full_utxo") if isinstance(block, dict) else []) or []
        keys = block.get("keys") if isinstance(block, dict) else []
        desc = block.get("recv_descriptor") if isinstance(block, dict) else None
        print(f"    name={name}  keys={len(keys) if keys else 0}  utxos={len(utxo)}")
        if desc:
            print(f"    recv_descriptor={desc[:80]}…")

    print("\nFertig. Für In-Process-Kontext im Plugin: /svc/satsage/context.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
