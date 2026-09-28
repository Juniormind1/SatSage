"""
Tip der Labor-Kette vor der Prüfung auf die Host-Uhr ziehen.

setmocktime legt Blöcke in die Vergangenheit. Bleibt die Mock-Zeit stehen,
scheitert der nächste Mine mit time-too-new, obwohl ein Block auf der
Host-Uhr die Kette wieder anschlussfähig macht. Das passiert vor dem Test,
nicht als Fehlerausgabe danach.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
NOW_TOLERANZ = 120


def _rpc(*args: str) -> str:
    command = [
        "docker", "compose", "-f", str(COMPOSE), "exec", "-T", "bitcoind",
        "bitcoin-cli", "-regtest", "-rpcuser=bitcoin", "-rpcpassword=secret",
        *args,
    ]
    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError(detail.strip()) from exc
    return result.stdout.strip()


def tip_nachziehen() -> str:
    info = json.loads(_rpc("getblockchaininfo"))
    tip_hash = info.get("bestblockhash") or ""
    header = json.loads(_rpc("getblockheader", tip_hash)) if tip_hash else {}
    tip_zeit = int(header.get("time") or info.get("mediantime") or 0)
    jetzt = int(time.time())
    if tip_zeit >= jetzt - NOW_TOLERANZ:
        return f"Kette aktuell: Tip {info.get('blocks')} liegt bei der Host-Uhr."
    _rpc("setmocktime", str(jetzt))
    try:
        adresse = _rpc("-rpcwallet=lab-faucet", "getnewaddress").strip()
    except RuntimeError as exc:
        raise RuntimeError(
            "lab-faucet fehlt. Kette neu aufsetzen, Nachzug mined nicht ins Leere."
        ) from exc
    _rpc("-rpcwallet=lab-faucet", "generatetoaddress", "1", adresse)
    _rpc("setmocktime", "0")
    neu = json.loads(_rpc("getblockchaininfo"))
    return (
        f"Kette nachgezogen: Tip {info.get('blocks')} → {neu.get('blocks')}, "
        f"Blockzeit auf Host-Uhr."
    )


def main() -> int:
    try:
        print(tip_nachziehen())
    except RuntimeError as exc:
        print(f"Kette nicht nachziehbar: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
