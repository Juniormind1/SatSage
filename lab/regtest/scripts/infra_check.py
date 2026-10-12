"""Labor-Infrastruktur: schnell scheitern, verständlich erklären.

Kein Docker-Start auf Windows. Kein minutenlanges Warten auf geschlossene
Ports. Bitcoin Core und Electrs/Fulcrum startet der Mensch, nicht der Prüfer.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent

BITCOIND_PORT = 18443
ELECTRS_PORT = 50001
NOWALLET_PORT = 18445
P2P_PORT = 18444
HOST = "127.0.0.1"


def _win() -> bool:
    return sys.platform == "win32"


def port_offen(port: int, host: str = HOST, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def _start_hinweis() -> str:
    if _win():
        return (
            "Windows: Docker nicht von SatSage starten. Labor lokal mit\n"
            "  lab\\regtest\\scripts\\win\\start_lab.ps1\n"
            "Dann diesen Prüfer noch einmal. Vor Merge nach main reicht der\n"
            "GitHub-Job „Regtest-Labor“ (Linux-Runner mit Docker)."
        )
    return (
        "Linux/macOS: im Ordner lab/regtest\n"
        "  ./scripts/start.sh\n"
        "Dann diesen Prüfer noch einmal. Vor Merge nach main: GitHub-Job\n"
        "„Regtest-Labor“."
    )


def hinweis_bitcoind() -> str:
    return (
        "Bitcoin Core (bitcoind) antwortet nicht auf "
        f"{HOST}:{BITCOIND_PORT} (Regtest-RPC).\n"
        "Die Unittest-Suite in tests/ braucht das nicht.\n"
        + _start_hinweis()
    )


def hinweis_electrs() -> str:
    return (
        "Electrs/Fulcrum antwortet nicht auf "
        f"{HOST}:{ELECTRS_PORT} (Electrum-RPC).\n"
        "Ohne Indexer kann der Prüfer keine Lab-Transaktionen lesen.\n"
        "Bitcoind allein reicht hier nicht — erst den Indexer starten.\n"
        + _start_hinweis()
    )


def hinweis_nowallet() -> str:
    return (
        "Der zweite Core-Node (disablewallet) antwortet nicht auf "
        f"{HOST}:{NOWALLET_PORT}.\n"
        + _start_hinweis()
    )


def hinweis_p2p() -> str:
    return (
        "Bitcoin-P2P antwortet nicht auf "
        f"{HOST}:{P2P_PORT} (Regtest Compact Filter / Blocks).\n"
        "Ohne diesen Port kein BIP-158-Labor. Docker: Port 18444 "
        "in docker-compose veröffentlichen. Windows: bitcoind listen=1, "
        "peerblockfilters=1.\n"
        + _start_hinweis()
    )


def darf_docker_starten() -> bool:
    """Windows: nie. Sonst nur wenn docker auf dem PATH liegt."""
    if _win():
        return False
    from shutil import which
    return which("docker") is not None


def hinweis_kein_docker() -> str:
    if _win():
        return (
            "Auf Windows startet dieser Prüfer kein Docker.\n"
            + _start_hinweis()
        )
    return (
        "Docker fehlt oder ist nicht auf dem PATH.\n"
        + _start_hinweis()
    )


def lab_optional() -> bool:
    """Auf WIP darf fehlende Infra ein sauberer Abbruch sein, kein Rot."""
    flag = (os.environ.get("SATSAGE_HARD_TESTS") or "").strip().lower()
    if flag in ("1", "true", "yes", "ja", "on"):
        return False
    if flag in ("0", "false", "no", "nein", "off"):
        return True
    base = (os.environ.get("GITHUB_BASE_REF") or "").strip()
    ref = (os.environ.get("GITHUB_REF") or "").strip()
    if base == "main" or ref == "refs/heads/main" or ref.startswith("refs/tags/"):
        return False
    if base == "dev-juniormind" or ref == "refs/heads/dev-juniormind":
        return True
    return False


def abbrechen(meldung: str) -> int:
    """1 = Pflicht verletzt, 0 = optional übersprungen."""
    text = meldung.rstrip() + "\n"
    if lab_optional():
        sys.stderr.write(
            "Labor-Prüfung übersprungen (dev-juniormind, Infra fehlt).\n"
            "Vor Merge nach main ist sie Pflicht.\n\n"
            + text
        )
        return 0
    sys.stderr.write(text)
    return 1


def brauche(*was: str) -> int | None:
    """None wenn alles da, sonst Exit-Code von ``abbrechen``."""
    mapping = {
        "bitcoind": (BITCOIND_PORT, hinweis_bitcoind),
        "electrs": (ELECTRS_PORT, hinweis_electrs),
        "nowallet": (NOWALLET_PORT, hinweis_nowallet),
        "p2p": (P2P_PORT, hinweis_p2p),
    }
    for name in was:
        port, hinweis = mapping[name]
        if not port_offen(port):
            return abbrechen(hinweis())
    return None
