"""
Dealbreaker T14 — statischer Riegel für Core-RPC im Produktivcode.

Durchsucht alle ``.py`` außerhalb von Lab/Tests (``lab/``, ``tests/``,
``specter_plugin/scripts/``) per AST:

* Jeder ``<obj>.call("…")`` nennt eine Methode aus der Allowlist
  (``core.bitcoind_rpc.ALLE_RPC_METHODEN``).
* Nicht-literale Methodennamen (Variable, f-String) gibt es nur in
  ``core/bitcoind_rpc.py`` — dort sitzt die Laufzeitprüfung.
* Lab-Methoden (Gruppe C, ``sendtoaddress``) nur im Lab-Faucet.
* Kein Roh-JSON-RPC an bitcoind (``{"method": "getblock…"}``) und kein
  ``bitcoin-cli`` am Client vorbei.

Rot hier = Merge-Dealbreaker (doc/merge-dealbreakers.md, T14).
"""
from __future__ import annotations

import ast
import os
import re
import unittest
from pathlib import Path

from core.bitcoind_rpc import (
    ALLE_RPC_METHODEN,
    RPC_KERN,
    RPC_LAB_REGTEST,
    RPC_WALLET_IMPORT,
)

WURZEL = Path(__file__).resolve().parents[1]

#: Reine Lab-/Test-/Hilfsbäume (dürfen bitcoin-cli & Co. direkt nutzen).
AUSGENOMMEN_PRAEFIXE = (
    "lab/",
    "tests/",
    "specter_plugin/scripts/",
)
#: Verzeichnisse ohne Quellcode des Projekts.
UEBERSPRINGEN = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__", "tmp",
    "data", "immutable_cache", "tor_data", "build", "dist", ".mypy_cache",
    ".pytest_cache", "utxo_cache", "sanctioned_cache",
}
#: Einzige Stelle mit dynamischem Methodennamen (die Prüfung selbst).
ZENTRALE = "core/bitcoind_rpc.py"
#: Einzige Stelle, die Gruppe C (regtest) nutzen darf.
LAB_FAUCET = "httpserver/api/wallets.py"


def produktiv_dateien() -> list[Path]:
    out: list[Path] = []
    for ordner, unter, dateien in os.walk(WURZEL):
        rel_ordner = Path(ordner).relative_to(WURZEL).as_posix()
        rel_ordner = "" if rel_ordner == "." else rel_ordner + "/"
        unter[:] = [
            u for u in unter
            if u not in UEBERSPRINGEN
            and not u.startswith(".")
            and not (rel_ordner + u + "/").startswith(AUSGENOMMEN_PRAEFIXE)
        ]
        for name in dateien:
            if not name.endswith(".py"):
                continue
            rel = rel_ordner + name
            if rel.startswith(AUSGENOMMEN_PRAEFIXE):
                continue
            out.append(WURZEL / rel)
    return sorted(out)


def _rel(pfad: Path) -> str:
    return pfad.relative_to(WURZEL).as_posix()


def _baum(pfad: Path) -> ast.AST | None:
    try:
        return ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
    except (SyntaxError, UnicodeDecodeError):
        return None


class TestRpcAllowlistStatisch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dateien = produktiv_dateien()
        cls.baeume = {_rel(p): _baum(p) for p in cls.dateien}

    def test_scan_findet_den_client(self):
        self.assertIn(ZENTRALE, self.baeume)
        self.assertIn("core/wallet_discover.py", self.baeume)
        self.assertNotIn("lab/regtest/scripts/generate_scenarios.py", self.baeume)
        self.assertGreater(len(self.dateien), 50)

    def test_call_methoden_in_allowlist(self):
        fehler: list[str] = []
        gefunden: set[str] = set()
        for rel, baum in self.baeume.items():
            if baum is None:
                continue
            for knoten in ast.walk(baum):
                if not (
                    isinstance(knoten, ast.Call)
                    and isinstance(knoten.func, ast.Attribute)
                    and knoten.func.attr == "call"
                ):
                    continue
                arg = knoten.args[0] if knoten.args else None
                ort = f"{rel}:{knoten.lineno}"
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    gefunden.add(arg.value)
                    if arg.value not in ALLE_RPC_METHODEN:
                        fehler.append(f"{ort}: .call({arg.value!r}) nicht in der Allowlist")
                    elif arg.value in RPC_LAB_REGTEST and rel != LAB_FAUCET:
                        fehler.append(f"{ort}: {arg.value!r} nur im Lab-Faucet ({LAB_FAUCET})")
                elif rel != ZENTRALE:
                    fehler.append(f"{ort}: .call(...) ohne literalen Methodennamen")
        self.assertEqual(fehler, [], "\n".join(fehler))
        # Plausibilität: der Scan sieht die bekannten Aufrufe wirklich.
        self.assertTrue({"getblockchaininfo", "scantxoutset", "listdescriptors"} <= gefunden)

    def test_kein_roh_jsonrpc_an_bitcoind(self):
        fehler: list[str] = []
        for rel, baum in self.baeume.items():
            if baum is None or rel == ZENTRALE:
                continue
            for knoten in ast.walk(baum):
                if not isinstance(knoten, ast.Dict):
                    continue
                for k, v in zip(knoten.keys, knoten.values):
                    if not (isinstance(k, ast.Constant) and k.value == "method"):
                        continue
                    # Electrum-Protokoll ist gepunktet (blockchain.*, server.*).
                    if isinstance(v, ast.Constant) and isinstance(v.value, str) and "." not in v.value:
                        fehler.append(f"{rel}:{knoten.lineno}: Roh-JSON-RPC {v.value!r}")
                for k, v in zip(knoten.keys, knoten.values):
                    if (
                        isinstance(k, ast.Constant) and k.value == "jsonrpc"
                        and isinstance(v, ast.Constant) and v.value == "1.0"
                    ):
                        fehler.append(f"{rel}:{knoten.lineno}: bitcoind-JSON-RPC 1.0 am Client vorbei")
        self.assertEqual(fehler, [], "\n".join(fehler))

    def test_kein_bitcoin_cli_im_produktivcode(self):
        fehler: list[str] = []
        for rel, baum in self.baeume.items():
            if baum is None:
                continue
            for knoten in ast.walk(baum):
                if (
                    isinstance(knoten, ast.Constant)
                    and isinstance(knoten.value, str)
                    and knoten.value.strip().startswith("bitcoin-cli")
                ):
                    fehler.append(f"{rel}:{knoten.lineno}: bitcoin-cli am Client vorbei")
        self.assertEqual(fehler, [], "\n".join(fehler))


#: Dateien mit ``rpcwhitelist=satsage:…``-Beispiel (bitcoin.conf).
DOKU_BEISPIELE = (".env.example", "doc/handbuch.html", "README.md")
_WHITELIST = re.compile(r"rpcwhitelist=satsage:([a-z,]+)")
_BACKTICK = re.compile(r"`([a-z]+)`")


class TestDokuPasstZurAllowlist(unittest.TestCase):
    """Die Doku nennt genau die Methoden der Konstanten — nicht mehr, nicht weniger."""

    def _whitelists(self, rel: str) -> list[frozenset[str]]:
        text = (WURZEL / rel).read_text(encoding="utf-8")
        return [frozenset(m.group(1).split(",")) for m in _WHITELIST.finditer(text)]

    def test_bitcoin_conf_beispiele(self):
        kern = frozenset(RPC_KERN)
        mit_import = frozenset(RPC_KERN + RPC_WALLET_IMPORT)
        for rel in DOKU_BEISPIELE:
            with self.subTest(datei=rel):
                zeilen = self._whitelists(rel)
                self.assertTrue(zeilen, f"{rel}: kein rpcwhitelist=satsage:-Beispiel")
                self.assertIn(kern, zeilen, rel)
                for z in zeilen:
                    self.assertIn(z, (kern, mit_import), f"{rel}: {sorted(z)}")
                    self.assertFalse(z & frozenset(RPC_LAB_REGTEST), rel)
        for rel in (".env.example", "doc/handbuch.html"):
            self.assertIn(mit_import, self._whitelists(rel), rel)

    def test_rpcwhitelistdefault_steht_dabei(self):
        for rel in DOKU_BEISPIELE:
            with self.subTest(datei=rel):
                self.assertIn("rpcwhitelistdefault=0", (WURZEL / rel).read_text(encoding="utf-8"))

    def test_merge_dealbreaker_t14_liste(self):
        text = (WURZEL / "doc/merge-dealbreakers.md").read_text(encoding="utf-8")
        self.assertIn("| T14 |", text)
        gruppen = {}
        for zeile in text.splitlines():
            for marke in ("A · Kern", "B · Core-Wallet-Import", "C · Lab-Faucet"):
                if zeile.startswith(f"- **{marke}"):
                    gruppen[marke] = set(_BACKTICK.findall(zeile)) - {"false"}
        self.assertEqual(gruppen.get("A · Kern"), set(RPC_KERN))
        self.assertEqual(gruppen.get("B · Core-Wallet-Import"), set(RPC_WALLET_IMPORT))
        self.assertEqual(gruppen.get("C · Lab-Faucet"), set(RPC_LAB_REGTEST))

    def test_agents_nennt_t14(self):
        text = (WURZEL / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("T14", text)
        self.assertIn("RpcAllowlistError", text)


if __name__ == "__main__":
    unittest.main()
