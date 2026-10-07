#!/usr/bin/env python3
"""Regtest: Scan-Abbruch hinterlässt keinen Cache, an dem der nächste Start stirbt.

Voraussetzung: Lab läuft (bitcoind + Electrs/Fulcrum), ``generate_scenarios.py``
hat ``.data/.regtest.env`` geschrieben. Dieser Prüfer startet Docker nicht.

Ablauf je Fall: Scan künstlich verlangsamen (Delay-Proxy) → Abbruch mitten
drin → Cache-Schnappschuss → neue SatSage-Instanz gegen denselben Cache.
Die neue Instanz muss in begrenzter Zeit antworten (kein Hang, keine
Endlosschleife) und einen neuen Scan starten können.

Gruppen:

* abort — UTXO-/Verlaufs-Scan, Abbruch per Knopf / Electrs-Drop / kill -9
* quelle — Wallet-Aktualisieren oder ungeduldiger Scan, bevor Electrs steht
* synthetic — bekannte kaputte Dateien (kill -9 während write_text ist racy)

Kein Pflichtlauf in Q6, bis das Produkt die Fälle grün hat.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
HERE = SCRIPTS.parent
REPO = HERE.parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
WORK = HERE / ".data" / "abort-scan"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))

from electrs_delay_proxy import ElectrsDelayProxy  # noqa: E402
from infra_check import brauche  # noqa: E402

DEFAULT_PORT = 8740
PROXY_PORT = 15001
ELECTRS_PORT = 50001
P2P_PORT = 18444
HANG_GET_S = 20.0
RECOVERY_SCAN_S = 90.0
BOOT_S = 90.0
CONTEXT_S = 120.0


# ---------------------------------------------------------------------------
# Szenario-Katalog
# ---------------------------------------------------------------------------

SCENARIOS: list[dict[str, Any]] = [
    # UTXO-Scan, Electrs schon da, nur langsam
    {"id": "U-ABORT", "group": "abort", "scan": "rescan", "abort": "cancel",
     "title": "UTXO-Scan: Abbruch-Knopf mitten im Gap"},
    {"id": "U-DROP", "group": "abort", "scan": "rescan", "abort": "drop",
     "title": "UTXO-Scan: Electrs-Verbindung gekappt"},
    {"id": "U-KILL", "group": "abort", "scan": "rescan", "abort": "kill",
     "title": "UTXO-Scan: kill -9 / taskkill /F"},
    # Verlauf
    {"id": "V-ABORT", "group": "abort", "scan": "verlauf", "abort": "cancel",
     "title": "Verlaufsscan: Abbruch-Knopf"},
    {"id": "V-DROP", "group": "abort", "scan": "verlauf", "abort": "drop",
     "title": "Verlaufsscan: Electrs-Verbindung gekappt"},
    {"id": "V-KILL", "group": "abort", "scan": "verlauf", "abort": "kill",
     "title": "Verlaufsscan: kill -9 / taskkill /F"},
    # Quelle zu früh
    {"id": "Q-START-P2P", "group": "quelle", "scan": "wallet-sync", "abort": "cancel",
     "title": "Wallet aktualisieren startet ohne Electrs (P2P-Halbverbindung), dann Electrs da"},
    {"id": "Q-START-KILL", "group": "quelle", "scan": "wallet-sync", "abort": "kill",
     "title": "Wallet aktualisieren ohne Electrs, dann kill -9"},
    {"id": "Q-IMPATIENT", "group": "quelle", "scan": "rescan", "abort": "cancel",
     "title": "Ungeduldiger UTXO-Scan bevor Electrs Handshake steht"},
    {"id": "Q-IMPATIENT-ONION", "group": "quelle", "scan": "rescan", "abort": "cancel",
     "title": "Ungeduldiger Scan bei onion-ähnlicher Electrs-Latenz"},
    {"id": "Q-IMPATIENT-DROP", "group": "quelle", "scan": "rescan", "abort": "drop",
     "title": "Ungeduldiger Scan, Electrs kommt nie — Drop"},
    # Synthetische Hinterlassenschaften
    {"id": "S-TRUNC-UTXO", "group": "synthetic", "kind": "trunc-utxo",
     "title": "Abgeschnittenes UTXO-JSON"},
    {"id": "S-EMPTY-UTXO", "group": "synthetic", "kind": "empty-utxo",
     "title": "Leere UTXO-Cache-Datei"},
    {"id": "S-TMP", "group": "synthetic", "kind": "tmp",
     "title": "Liegengebliebenes .json.tmp"},
    {"id": "S-LIST", "group": "synthetic", "kind": "list-utxo",
     "title": "UTXO-Cache ist ein JSON-Array"},
    {"id": "S-TRUNC-VERLAUF", "group": "synthetic", "kind": "trunc-verlauf",
     "title": "Abgeschnittener Verlaufs-Cache"},
    {"id": "S-INCOMPLETE-VERLAUF", "group": "synthetic", "kind": "incomplete-verlauf",
     "title": "Verlauf incomplete, scanned=planned"},
    {"id": "S-TRUNC-EXTERNAL", "group": "synthetic", "kind": "trunc-external",
     "title": "Abgeschnittenes external_addresses.json"},
]


def szenarien_fuer(only: str, group: str) -> list[dict[str, Any]]:
    if only:
        wollen = {t.strip() for t in only.split(",") if t.strip()}
        return [s for s in SCENARIOS if s["id"] in wollen]
    if group:
        return [s for s in SCENARIOS if s["group"] == group]
    return list(SCENARIOS)


# ---------------------------------------------------------------------------
# Env / Cache
# ---------------------------------------------------------------------------

def _load_env(path: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not path.is_file():
        return werte
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        werte[k.strip()] = v.strip()
    return werte


def _schreibe_env(path: Path, werte: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    zeilen = ["# Isolierte Lab-Env für Scan-Abbruch. Nicht committen."]
    for key, val in werte.items():
        zeilen.append(f"{key}={val}")
    path.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def isolierte_env(
    basis: dict[str, str],
    *,
    fulcrum_port: int,
    immer_aktuell: bool,
    bip158: bool,
) -> dict[str, str]:
    """Nur Lab-Alpha, kein Auto-Scan außer explizit, kein Mempool, kein LLM."""
    out: dict[str, str] = {}
    for key, val in basis.items():
        if key.startswith("WALLET_0_"):
            out[key] = val
        elif key in (
            "NETWORK", "FULCRUM_HOST", "FULCRUM_SSL",
            "NODE_IP", "RPCPORT", "RPCUSER", "RPCPASSWORD",
            "STEUER_HALTEFRIST_JAHRE",
        ):
            out[key] = val
    out["NETWORK"] = "regtest"
    out["FULCRUM_HOST"] = "127.0.0.1"
    out["FULCRUM_PORT"] = str(int(fulcrum_port))
    out["FULCRUM_SSL"] = basis.get("FULCRUM_SSL") or "false"
    out["WALLETS_IMMER_AKTUELL"] = "1" if immer_aktuell else "0"
    out["WALLETS_BEIM_START_AKTUALISIEREN"] = "1" if immer_aktuell else "0"
    out["MEMPOOL_URL"] = ""
    out["OEFFENTLICHE_ELECTRUM"] = "0"
    if bip158:
        out["BIP158_P2P"] = "1"
        out["BIP158_PEERS"] = f"127.0.0.1:{P2P_PORT}"
    else:
        out["BIP158_P2P"] = "0"
    return out


def inspect_cache(cache_dir: Path) -> dict[str, Any]:
    """Beschreibt Hinterlassenschaften ohne XPUB-Werte."""
    dateien: list[dict[str, Any]] = []
    if not cache_dir.is_dir():
        return {"files": dateien, "truncated": 0, "tmp": 0, "empty": 0}
    trunc = tmp = empty = 0
    for pfad in sorted(cache_dir.rglob("*")):
        if not pfad.is_file():
            continue
        info: dict[str, Any] = {
            "name": pfad.name,
            "bytes": pfad.stat().st_size,
        }
        name = pfad.name
        if name.endswith(".tmp") or name.endswith(".json.tmp"):
            info["kind"] = "tmp"
            info["json_ok"] = False
            tmp += 1
        elif name.endswith(".json"):
            if pfad.stat().st_size == 0:
                info["json_ok"] = False
                info["kind"] = "empty"
                empty += 1
            else:
                try:
                    daten = json.loads(pfad.read_text(encoding="utf-8"))
                    info["json_ok"] = True
                    info["type"] = type(daten).__name__
                    if isinstance(daten, dict):
                        info["keys"] = sorted(str(k) for k in daten.keys())[:24]
                        scan = daten.get("scan") if isinstance(daten.get("scan"), dict) else {}
                        info["incomplete"] = bool(scan.get("incomplete"))
                        if "utxo_count" in daten:
                            info["utxo_count"] = daten.get("utxo_count")
                        if "scan_end_index" in daten:
                            info["scan_end_index"] = daten.get("scan_end_index")
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    info["json_ok"] = False
                    info["kind"] = "truncated"
                    info["error"] = type(exc).__name__
                    trunc += 1
        dateien.append(info)
    return {"files": dateien, "truncated": trunc, "tmp": tmp, "empty": empty}


def cache_aktivitaet(cache_dir: Path) -> bool:
    if not cache_dir.is_dir():
        return False
    for pfad in cache_dir.glob("*.json"):
        name = pfad.name.lower()
        if name == "external_addresses.json":
            continue
        if name.endswith("_alter.json"):
            continue
        if pfad.stat().st_size > 2:
            return True
    return False


def snapshot_cache(src: Path, dest: Path) -> dict[str, Any]:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest / "utxo_cache", dirs_exist_ok=True)
    return inspect_cache(src)


# ---------------------------------------------------------------------------
# HTTP / Prozess
# ---------------------------------------------------------------------------

def api(sess: dict, path: str, method: str = "GET", data: Any = None, timeout: float = HANG_GET_S):
    body = None
    headers = {"X-Satsage-Token": sess["token"]}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = f"http://{sess['bind']}:{sess['port']}{path}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as ant:
            roh = ant.read().decode("utf-8")
            return ant.status, json.loads(roh) if roh else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"raw": raw[:400]}
    except (TimeoutError, socket.timeout) as exc:
        raise TimeoutError(f"{method} {path} Timeout nach {timeout:.0f}s") from exc


def port_frei(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return False
    except OSError:
        return True


def warte_port_frei(port: int, timeout: float = 8.0) -> None:
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        if port_frei(port):
            return
        time.sleep(0.15)
    raise TimeoutError(f"Port {port} bleibt belegt")


def waehle_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 8):
        if port_frei(port):
            return port
    raise RuntimeError(f"Kein freier Port ab {start}")


def starte_server(
    *,
    env_path: Path,
    cache_dir: Path,
    imm_dir: Path,
    session_path: Path,
    log_path: Path,
    port: int,
) -> subprocess.Popen:
    cache_dir.mkdir(parents=True, exist_ok=True)
    imm_dir.mkdir(parents=True, exist_ok=True)
    if session_path.is_file():
        session_path.unlink()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["SATSAGE_SESSION_FILE"] = str(session_path)
    env["NETWORK"] = "regtest"
    py = sys.executable
    cmd = [
        py, "server.py",
        "--env", str(env_path),
        "--cache-dir", str(cache_dir),
        "--immutable-cache-dir", str(imm_dir),
        "--port", str(port),
        "--bind", "127.0.0.1",
        "--no-browser",
        "--plain-console",
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    kwargs: dict[str, Any] = {
        "cwd": str(REPO),
        "env": env,
        "stdout": log,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    proc._satsage_log = log  # type: ignore[attr-defined]
    return proc


def _pid_baum_toeten(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, text=True,
        )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def stoppe_server(proc: subprocess.Popen | None, *, hart: bool = False) -> None:
    if proc is None:
        return
    log = getattr(proc, "_satsage_log", None)
    pid = proc.pid
    try:
        if hart or proc.poll() is None:
            if hart:
                _pid_baum_toeten(pid)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    _pid_baum_toeten(pid)
        else:
            proc.wait(timeout=1)
    except Exception:
        _pid_baum_toeten(pid)
    if log is not None:
        try:
            log.close()
        except Exception:
            pass


def warte_session(path: Path, proc: subprocess.Popen, timeout: float = BOOT_S) -> dict:
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        if proc.poll() is not None:
            raise RuntimeError(f"SatSage beendet vor Session (Exit {proc.returncode})")
        if path.is_file():
            try:
                daten = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                daten = None
            if isinstance(daten, dict) and daten.get("token") and daten.get("port"):
                return daten
        time.sleep(0.2)
    raise TimeoutError(f"Keine Session unter {path} nach {timeout:.0f}s")


def warte_context(sess: dict, timeout: float = CONTEXT_S) -> dict:
    ende = time.monotonic() + timeout
    letzter: dict = {}
    while time.monotonic() < ende:
        status, body = api(sess, "/api/config", timeout=HANG_GET_S)
        if status != 200:
            raise RuntimeError(f"GET /api/config → HTTP {status}")
        letzter = body if isinstance(body, dict) else {}
        if letzter.get("context_bereit"):
            return letzter
        time.sleep(0.4)
    raise TimeoutError("context_bereit kam nicht")


def wallet_alpha(cfg: dict) -> dict:
    for w in cfg.get("wallets") or []:
        name = str(w.get("name") or "").lower()
        if "alpha" in name:
            return w
    wallets = cfg.get("wallets") or []
    if not wallets:
        raise RuntimeError("Keine Wallets in /api/config")
    return wallets[0]


def starte_scan(sess: dict, art: str, wallet_id: str) -> dict:
    if art == "verlauf":
        status, body = api(
            sess, "/api/verlauf", "POST",
            {"wallet_id": wallet_id}, timeout=30,
        )
    elif art == "wallet-sync":
        status, body = api(sess, "/api/jobs/wallet-sync", "POST", {}, timeout=30)
    else:
        status, body = api(
            sess, "/api/jobs/rescan", "POST",
            {"wallet_id": wallet_id}, timeout=30,
        )
    if status not in (200, 202):
        raise RuntimeError(f"Scan {art} → HTTP {status}: {body}")
    if not isinstance(body, dict) or not body.get("id"):
        raise RuntimeError(f"Scan {art} ohne Job-ID: {body}")
    return body


def job_stand(sess: dict, job_id: str) -> dict:
    status, body = api(sess, f"/api/jobs/{job_id}", timeout=HANG_GET_S)
    if status == 404:
        return {"id": job_id, "status": "missing"}
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"GET /api/jobs/{job_id} → HTTP {status}")
    return body


def warte_scan_schreibt(
    sess: dict, job_id: str, cache_dir: Path, timeout: float,
) -> tuple[str, dict]:
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        stand = job_stand(sess, job_id)
        status = str(stand.get("status") or "")
        if status in ("done", "failed", "cancelled"):
            return "job_ended", stand
        if cache_aktivitaet(cache_dir):
            return "cache", stand
        result = stand.get("result") if isinstance(stand.get("result"), dict) else {}
        if result.get("utxo_count") or result.get("partial"):
            return "progress", stand
        msg = str(stand.get("message") or "")
        if "bisher" in msg.lower() or "adresse" in msg.lower():
            return "progress", stand
        time.sleep(0.25)
    return "timeout", {}


def warte_job_ende(sess: dict, job_id: str, timeout: float) -> dict:
    ende = time.monotonic() + timeout
    letzter = {}
    letzte_msg = ""
    still = 0
    while time.monotonic() < ende:
        stand = job_stand(sess, job_id)
        letzter = stand
        status = str(stand.get("status") or "")
        if status in ("done", "failed", "cancelled", "missing"):
            return stand
        msg = str(stand.get("message") or "")
        if msg == letzte_msg:
            still += 1
        else:
            still = 0
            letzte_msg = msg
        time.sleep(0.4)
    stand = letzter if letzter else {}
    stand["hang"] = True
    stand["still_ticks"] = still
    return stand


# ---------------------------------------------------------------------------
# Synthetische Dateien
# ---------------------------------------------------------------------------

def _cache_key(xpub: str) -> str:
    os.environ.setdefault("NETWORK", "regtest")
    from core.xpub_cache import _xpub_cache_key

    return _xpub_cache_key(xpub)


def lege_synthetic(kind: str, cache_dir: Path, xpub: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(xpub)
    utxo = cache_dir / f"{key}.json"
    verlauf = cache_dir / f"{key}_verlauf.json"
    external = cache_dir / "external_addresses.json"
    if kind == "trunc-utxo":
        utxo.write_text('{"xpub":"', encoding="utf-8")
    elif kind == "empty-utxo":
        utxo.write_text("", encoding="utf-8")
    elif kind == "tmp":
        tmp = utxo.with_suffix(".json.tmp")
        tmp.write_text('{"xpub":"halb"', encoding="utf-8")
    elif kind == "list-utxo":
        utxo.write_text("[]\n", encoding="utf-8")
    elif kind == "trunc-verlauf":
        verlauf.write_text('{"eintraege":[', encoding="utf-8")
    elif kind == "incomplete-verlauf":
        payload = {
            "eintraege": [],
            "scan": {
                "incomplete": True,
                "scanned_addresses": ["bcrt1qsynthetic0000000000000000000000"],
                "planned_addresses": ["bcrt1qsynthetic0000000000000000000000"],
            },
        }
        verlauf.write_text(json.dumps(payload), encoding="utf-8")
    elif kind == "trunc-external":
        external.write_text('{"xpub_set_hash":"', encoding="utf-8")
    else:
        raise ValueError(kind)


# ---------------------------------------------------------------------------
# Neustart-Prüfung (das eigentliche Soll)
# ---------------------------------------------------------------------------

def pruefe_neustart(
    *,
    env_path: Path,
    cache_dir: Path,
    imm_dir: Path,
    session_path: Path,
    log_path: Path,
    port: int,
    mit_scan: bool,
) -> dict[str, Any]:
    """Neue Instanz gegen Hinterlassenschaft: bootet, API antwortet, hängt nicht."""
    befund: dict[str, Any] = {"ok": False}
    proc = None
    try:
        proc = starte_server(
            env_path=env_path, cache_dir=cache_dir, imm_dir=imm_dir,
            session_path=session_path, log_path=log_path, port=port,
        )
        sess = warte_session(session_path, proc, timeout=BOOT_S)
        befund["boot_s"] = True
        cfg = warte_context(sess, timeout=CONTEXT_S)
        befund["context"] = True
        alpha = wallet_alpha(cfg)
        wid = str(alpha.get("id") or "")
        status, utxos = api(sess, f"/api/wallets/{wid}/utxos?mempool=0", timeout=HANG_GET_S)
        if status != 200:
            raise RuntimeError(f"UTXO-API HTTP {status}")
        befund["utxos_http"] = status
        status, jobs = api(sess, "/api/jobs?recent_s=5", timeout=HANG_GET_S)
        if status != 200:
            raise RuntimeError(f"Jobs-API HTTP {status}")
        befund["jobs_http"] = status
        if mit_scan:
            job = starte_scan(sess, "rescan", wid)
            ende = warte_job_ende(sess, job["id"], timeout=RECOVERY_SCAN_S)
            befund["recovery_job"] = ende.get("status")
            if ende.get("hang") or ende.get("status") == "running":
                raise TimeoutError("Recovery-Scan hängt")
        befund["ok"] = True
        return befund
    except Exception as exc:
        befund["error"] = f"{type(exc).__name__}: {exc}"
        return befund
    finally:
        stoppe_server(proc, hart=True)
        try:
            warte_port_frei(port, timeout=8.0)
        except TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Szenario-Läufe
# ---------------------------------------------------------------------------

class Lauf:
    def __init__(self, args: argparse.Namespace, basis: dict[str, str]) -> None:
        self.args = args
        self.basis = basis
        self.port = waehle_port(args.port)
        self.proxy = ElectrsDelayProxy(
            ("127.0.0.1", args.proxy_port),
            ("127.0.0.1", ELECTRS_PORT),
            delay_s=max(0.0, args.delay_ms) / 1000.0,
        )
        self.work = WORK / "work"
        self.cache = self.work / "utxo_cache"
        self.imm = self.work / "immutable_cache"
        self.env_abort = self.work / "abort.env"
        self.env_recover = self.work / "recover.env"
        self.session = self.work / "session.json"
        self.log = self.work / "server.log"
        self.leftovers = WORK / "leftovers"
        self.xpub = basis.get("WALLET_0_XPUB") or ""

    def vorbereiten_dirs(self) -> None:
        if self.work.exists():
            shutil.rmtree(self.work, ignore_errors=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.imm.mkdir(parents=True, exist_ok=True)
        self.leftovers.mkdir(parents=True, exist_ok=True)

    def schreibe_envs(self, *, immer: bool, bip158: bool, abort_port: int) -> None:
        _schreibe_env(
            self.env_abort,
            isolierte_env(
                self.basis, fulcrum_port=abort_port,
                immer_aktuell=immer, bip158=bip158,
            ),
        )
        _schreibe_env(
            self.env_recover,
            isolierte_env(
                self.basis, fulcrum_port=ELECTRS_PORT,
                immer_aktuell=False, bip158=False,
            ),
        )

    def seed_cache(self) -> None:
        """Schneller UTXO-Scan ohne Delay, damit Start-Sync einen Cache hat."""
        self.schreibe_envs(immer=False, bip158=False, abort_port=ELECTRS_PORT)
        proc = starte_server(
            env_path=self.env_recover, cache_dir=self.cache, imm_dir=self.imm,
            session_path=self.session, log_path=self.work / "seed.log",
            port=self.port,
        )
        try:
            sess = warte_session(self.session, proc)
            cfg = warte_context(sess)
            wid = str(wallet_alpha(cfg).get("id") or "")
            job = starte_scan(sess, "rescan", wid)
            ende = warte_job_ende(sess, job["id"], timeout=RECOVERY_SCAN_S)
            if ende.get("hang"):
                raise TimeoutError("Seed-Scan hängt")
        finally:
            stoppe_server(proc, hart=True)
            warte_port_frei(self.port)

    def abbrechen(self, sess: dict | None, job_id: str | None, art: str, proc) -> str:
        if art == "kill":
            stoppe_server(proc, hart=True)
            return "kill"
        if art == "drop":
            self.proxy.drop_all()
            if sess and job_id:
                try:
                    warte_job_ende(sess, job_id, timeout=15)
                except Exception:
                    pass
            return "drop"
        if sess and job_id:
            try:
                api(sess, f"/api/jobs/{job_id}", "DELETE", timeout=10)
            except Exception:
                pass
            try:
                warte_job_ende(sess, job_id, timeout=15)
            except Exception:
                pass
        return "cancel"

    def live_abort(self, szenario: dict[str, Any]) -> dict[str, Any]:
        self.vorbereiten_dirs()
        delay_ms = self.args.onion_delay_ms if szenario["id"] == "Q-IMPATIENT-ONION" else self.args.delay_ms
        self.proxy.set_delay(max(0.0, delay_ms) / 1000.0)
        self.proxy.resume()
        quelle = szenario["group"] == "quelle"
        immer = szenario["id"].startswith("Q-START")
        hold_zuerst = szenario["id"] in (
            "Q-START-P2P", "Q-START-KILL", "Q-IMPATIENT", "Q-IMPATIENT-DROP",
        )
        if immer:
            self.seed_cache()
        self.schreibe_envs(
            immer=immer, bip158=quelle,
            abort_port=self.args.proxy_port,
        )
        if hold_zuerst:
            self.proxy.hold()
        proc = starte_server(
            env_path=self.env_abort, cache_dir=self.cache, imm_dir=self.imm,
            session_path=self.session, log_path=self.log, port=self.port,
        )
        job_id = None
        sess = None
        ausloeser = "timeout"
        try:
            sess = warte_session(self.session, proc)
            cfg = warte_context(sess)
            wid = str(wallet_alpha(cfg).get("id") or "")
            if immer:
                api(sess, "/api/gui-bereit", "POST", {}, timeout=10)
                time.sleep(0.8)
            scan_art = szenario.get("scan") or "rescan"
            if scan_art == "wallet-sync":
                try:
                    job = starte_scan(sess, "wallet-sync", wid)
                    job_id = job["id"]
                except RuntimeError:
                    # Auto-Start nach gui-bereit — Job aus der Liste lesen.
                    status, body = api(sess, "/api/jobs?recent_s=30", timeout=HANG_GET_S)
                    jobs = (body or {}).get("jobs") if status == 200 else None
                    for j in jobs or []:
                        if j.get("kind") in ("wallet_sync", "rescan") and j.get("status") == "running":
                            job_id = j.get("id")
                            break
                    if not job_id:
                        raise
            else:
                job = starte_scan(sess, scan_art, wid)
                job_id = job["id"]

            if hold_zuerst and szenario["id"].startswith("Q-START"):
                time.sleep(max(1.0, self.args.hold_s))
                self.proxy.resume()
                time.sleep(1.0)
            elif hold_zuerst and szenario["id"] == "Q-IMPATIENT":
                time.sleep(max(2.0, min(12.0, self.args.hold_s)))
                self.proxy.resume()
            elif not hold_zuerst:
                pass

            warte = 12.0 if hold_zuerst else 45.0
            ausloeser, _stand = warte_scan_schreibt(
                sess, job_id, self.cache, timeout=warte,
            )
            if ausloeser == "job_ended" and szenario["abort"] != "drop":
                return {
                    "ok": False,
                    "error": "Scan war fertig bevor der Abbruch greifen konnte "
                             "(delay-ms erhöhen oder Hold länger).",
                    "trigger": ausloeser,
                }
            if ausloeser == "timeout" and not hold_zuerst:
                # Ohne Cache-Datei trotzdem abbrechen — kill kann genau das sein.
                ausloeser = "timeout-abort"

            self.abbrechen(sess, job_id, szenario["abort"], proc)
            if szenario["abort"] != "kill":
                time.sleep(0.6)
                stoppe_server(proc, hart=True)
            proc = None
            warte_port_frei(self.port)
        except Exception as exc:
            stoppe_server(proc, hart=True)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trigger": ausloeser}
        hinter = snapshot_cache(self.cache, self.leftovers / szenario["id"])
        recover_log = self.work / "recover.log"
        recover_session = self.work / "recover-session.json"
        neu = pruefe_neustart(
            env_path=self.env_recover,
            cache_dir=self.cache,
            imm_dir=self.imm,
            session_path=recover_session,
            log_path=recover_log,
            port=self.port,
            mit_scan=not self.args.skip_recovery_scan,
        )
        return {
            "ok": bool(neu.get("ok")),
            "trigger": ausloeser,
            "leftover": hinter,
            "restart": neu,
            "error": neu.get("error"),
        }

    def synthetic(self, szenario: dict[str, Any]) -> dict[str, Any]:
        self.vorbereiten_dirs()
        if not self.xpub:
            return {"ok": False, "error": "WALLET_0_XPUB fehlt in der Lab-Env"}
        lege_synthetic(szenario["kind"], self.cache, self.xpub)
        hinter = snapshot_cache(self.cache, self.leftovers / szenario["id"])
        self.schreibe_envs(immer=False, bip158=False, abort_port=ELECTRS_PORT)
        neu = pruefe_neustart(
            env_path=self.env_recover,
            cache_dir=self.cache,
            imm_dir=self.imm,
            session_path=self.work / "recover-session.json",
            log_path=self.work / "recover.log",
            port=self.port,
            mit_scan=not self.args.skip_recovery_scan,
        )
        return {
            "ok": bool(neu.get("ok")),
            "leftover": hinter,
            "restart": neu,
            "error": neu.get("error"),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="", help="Komma-IDs, z. B. U-KILL,Q-IMPATIENT")
    parser.add_argument("--group", default="", choices=("", "abort", "quelle", "synthetic"))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--delay-ms", type=float, default=400.0)
    parser.add_argument("--onion-delay-ms", type=float, default=2000.0)
    parser.add_argument("--hold-s", type=float, default=100.0,
                        help="Electrs-Hold für Q-START (Indexer-Wartefrist ist 90s)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--proxy-port", type=int, default=PROXY_PORT)
    parser.add_argument("--skip-recovery-scan", action="store_true")
    parser.add_argument("--report", type=Path, default=WORK / "report.json")
    args = parser.parse_args()

    if args.list:
        for s in SCENARIOS:
            print(f"{s['id']:22}  {s['group']:10}  {s['title']}")
        return 0

    fehl = brauche("bitcoind", "electrs")
    if fehl is not None:
        return fehl
    if not ENV_PATH.is_file():
        print(f"Lab-Env fehlt: {ENV_PATH}", file=sys.stderr)
        print("Zuerst generate_scenarios.py (bzw. run_scenarios.ps1).", file=sys.stderr)
        return 1

    basis = _load_env(ENV_PATH)
    if not basis.get("WALLET_0_XPUB"):
        print("WALLET_0_XPUB fehlt in der Lab-Env.", file=sys.stderr)
        return 1

    auswahl = szenarien_fuer(args.only, args.group)
    if not auswahl:
        print("Keine Szenarien gewählt.", file=sys.stderr)
        return 1

    WORK.mkdir(parents=True, exist_ok=True)
    lauf = Lauf(args, basis)
    try:
        lauf.proxy.start()
    except OSError as exc:
        print(f"Delay-Proxy Listen {args.proxy_port} fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    ergebnisse: list[dict[str, Any]] = []
    rot = 0
    try:
        for szenario in auswahl:
            sid = szenario["id"]
            print(f"→ {sid}: {szenario['title']}", flush=True)
            start = time.monotonic()
            if szenario["group"] == "synthetic":
                raw = lauf.synthetic(szenario)
            else:
                raw = lauf.live_abort(szenario)
            dauer = time.monotonic() - start
            ok = bool(raw.get("ok"))
            if not ok:
                rot += 1
            zeile = {
                "id": sid,
                "group": szenario["group"],
                "ok": ok,
                "seconds": round(dauer, 1),
                "error": raw.get("error"),
                "trigger": raw.get("trigger"),
                "leftover": {
                    "truncated": (raw.get("leftover") or {}).get("truncated"),
                    "tmp": (raw.get("leftover") or {}).get("tmp"),
                    "empty": (raw.get("leftover") or {}).get("empty"),
                    "files": len((raw.get("leftover") or {}).get("files") or []),
                },
                "restart": raw.get("restart"),
            }
            ergebnisse.append(zeile)
            marke = "OK" if ok else "FAIL"
            extra = f" — {raw.get('error')}" if raw.get("error") else ""
            print(f"  {marke}  {dauer:.1f}s{extra}", flush=True)
    finally:
        lauf.proxy.stop()

    report = {
        "ok": rot == 0,
        "failed": rot,
        "ran": len(ergebnisse),
        "cases": ergebnisse,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Report: {args.report}  ({len(ergebnisse) - rot}/{len(ergebnisse)} grün)", flush=True)
    return 0 if rot == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
