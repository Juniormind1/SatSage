"""
Bitcoin Core JSON-RPC — vor allem ``scantxoutset`` für schnellen UTXO-Bestand.

LAN oder Onion (SOCKS). Kein Verlauf: nur was *jetzt* unspent ist.
"""
from __future__ import annotations

import base64
import json
import socket
import ssl
import struct
import threading
import time
import outbound_policy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

LogFn = Callable[[str], None]


def _log(on_log: LogFn | None, text: str) -> None:
    if on_log:
        on_log(text)


def normalize_rpc_host(value: str) -> str:
    """Host ohne Schema/Pfad; ``user@host`` → host (Start9/Copy-Paste)."""
    raw = (value or "").strip()
    for prefix in ("https://", "http://"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix) :]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    if ":" in raw and not raw.endswith(".onion"):
        host, port_str = raw.rsplit(":", 1)
        if port_str.isdigit():
            return host
    return raw


def host_ist_onion(host: str) -> bool:
    h = normalize_rpc_host(host).lower()
    return h.endswith(".onion")


@dataclass
class CoreRpcConfig:
    host: str
    port: int
    user: str
    password: str
    use_ssl: bool
    tor_proxy: tuple[str, int] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    @property
    def ziel(self) -> str:
        tls = "TLS" if self.use_ssl else "ohne TLS"
        return f"{self.host}:{self.port} ({tls})"


def _rpc_credentials(
    env: dict[str, str],
    *,
    user_key: str,
    password_key: str,
    cookie_key: str,
) -> tuple[str, str]:
    user = (env.get(user_key) or "").strip()
    password = (env.get(password_key) or "").strip()
    if user and password:
        return user, password
    cookie_path = (env.get(cookie_key) or "").strip()
    if not cookie_path and cookie_key == "RPC_COOKIE_FILE":
        cookie_path = "/mnt/bitcoind/.cookie"
    if not cookie_path:
        return user, password
    try:
        cookie = Path(cookie_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return user, password
    if ":" not in cookie:
        return user, password
    cookie_user, cookie_password = cookie.split(":", 1)
    return user or cookie_user.strip(), password or cookie_password.strip()


def rpc_credentials_from_env(env: dict[str, str]) -> tuple[str, str]:
    """Liest Lookup-RPC-Zugangsdaten, notfalls aus der Bitcoin-Core-Cookie-Datei."""
    return _rpc_credentials(
        env,
        user_key="RPCUSER",
        password_key="RPCPASSWORD",
        cookie_key="RPC_COOKIE_FILE",
    )


def _config_from_keys(
    env: dict[str, str],
    *,
    host_keys: tuple[str, ...],
    port_key: str,
    user_key: str,
    password_key: str,
    cookie_key: str,
    ssl_key: str,
) -> CoreRpcConfig | None:
    host_raw = ""
    for key in host_keys:
        host_raw = (env.get(key) or "").strip()
        if host_raw:
            break
    if not host_raw:
        return None
    host = normalize_rpc_host(host_raw)
    outbound_policy.ensure_host_allowed(host, service="core", values=env)
    user, password = _rpc_credentials(
        env, user_key=user_key, password_key=password_key, cookie_key=cookie_key,
    )
    if not user or not password:
        return None
    try:
        port = int((env.get(port_key) or "8332").strip() or "8332")
    except ValueError:
        port = 8332
    ssl_raw = (env.get(ssl_key) or "").strip().lower()
    if ssl_raw:
        use_ssl = ssl_raw not in ("0", "false", "nein", "no", "off")
    else:
        use_ssl = port == 443
    proxy = None
    if host_ist_onion(host):
        from main import _parse_tor_proxy

        proxy = _parse_tor_proxy(env)
    return CoreRpcConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        use_ssl=use_ssl,
        tor_proxy=proxy,
    )


def config_from_env(env: dict[str, str]) -> CoreRpcConfig | None:
    """Lookup/Tx-Block-Rolle: NODE_IP / RPCPORT / RPCUSER / RPCPASSWORD / RPC_SSL."""
    return _config_from_keys(
        env,
        host_keys=("NODE_IP", "RPCHOST", "BITCOIN_RPC_HOST", "BITCOIND_HOST"),
        port_key="RPCPORT",
        user_key="RPCUSER",
        password_key="RPCPASSWORD",
        cookie_key="RPC_COOKIE_FILE",
        ssl_key="RPC_SSL",
    )


def config_utxo_from_env(env: dict[str, str]) -> CoreRpcConfig | None:
    """UTXO-Set-Rolle (scantxoutset): UTXO_RPC_* , sonst Fallback auf Lookup-Core."""
    dedicated = _config_from_keys(
        env,
        host_keys=("UTXO_RPC_HOST",),
        port_key="UTXO_RPCPORT",
        user_key="UTXO_RPCUSER",
        password_key="UTXO_RPCPASSWORD",
        cookie_key="UTXO_RPC_COOKIE_FILE",
        ssl_key="UTXO_RPC_SSL",
    )
    if dedicated is not None:
        return dedicated
    return config_from_env(env)


def _socks5_connect(
    proxy_host: str,
    proxy_port: int,
    dest_host: str,
    dest_port: int,
    timeout: float,
) -> socket.socket:
    from fulcrum import _socks5_connect as fulcrum_socks

    return fulcrum_socks(proxy_host, proxy_port, dest_host, dest_port, int(timeout))


def _recv_http_body(sock: socket.socket, timeout: float) -> bytes:
    """
    Liest eine HTTP-Antwort vollständig.

    *timeout* gilt pro ``recv``-Schritt (nicht für die Gesamtdauer) — lange
    ``scantxoutset``-Läufe über Tor dürfen Minuten brauchen, solange der
    Socket lebt. Gesamtdauer begrenzt der Aufrufer über den Connect-Timeout
    nur beim Aufbau; hier warten wir auf Close oder Content-Length.
    """
    # Zwischen zwei Chunks: bei Tor/scantxoutset oft lange Stille, Node rechnet.
    sock.settimeout(max(float(timeout), 120.0))
    chunks: list[bytes] = []
    deadline = time.monotonic() + max(float(timeout), 120.0) * 20  # hartes Limit
    while time.monotonic() < deadline:
        try:
            piece = sock.recv(65536)
        except socket.timeout:
            # noch kein Byte — weiter warten bis Gesamtdeadline
            if chunks:
                # schon Header? bei Content-Length unvollständig weiter
                blob = b"".join(chunks)
                if b"\r\n\r\n" in blob:
                    continue
            continue
        if not piece:
            break
        chunks.append(piece)
        blob = b"".join(chunks)
        if b"\r\n\r\n" not in blob:
            continue
        head, _, rest = blob.partition(b"\r\n\r\n")
        head_l = head.lower()
        cl = None
        for line in head.split(b"\r\n")[1:]:
            if line.lower().startswith(b"content-length:"):
                try:
                    cl = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    cl = None
                break
        if cl is not None:
            if len(rest) >= cl:
                break
            continue
        if b"transfer-encoding: chunked" in head_l:
            # fertig wenn abschließender 0-chunk da
            if rest.endswith(b"0\r\n\r\n") or b"\r\n0\r\n\r\n" in rest:
                break
    return b"".join(chunks)


class BitcoinRpcClient:
    """Minimaler bitcoind JSON-RPC-Client (HTTP, optional TLS + SOCKS)."""

    def __init__(self, cfg: CoreRpcConfig, *, timeout: float = 60.0):
        self.cfg = cfg
        self.timeout = timeout
        self._id = 0

    def call(self, method: str, params: list | None = None) -> Any:
        self._id += 1
        payload = {
            "jsonrpc": "1.0",
            "id": self._id,
            "method": method,
            "params": params or [],
        }
        body = json.dumps(payload).encode("utf-8")
        auth = base64.b64encode(
            f"{self.cfg.user}:{self.cfg.password}".encode("utf-8")
        ).decode("ascii")
        host = outbound_policy.ensure_resolves_to_allowed_host(self.cfg.host, service="core")
        headers = (
            f"POST / HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Authorization: Basic {auth}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("ascii")

        if self.cfg.tor_proxy:
            sock = _socks5_connect(
                self.cfg.tor_proxy[0],
                self.cfg.tor_proxy[1],
                host,
                self.cfg.port,
                self.timeout,
            )
        else:
            sock = socket.create_connection((host, self.cfg.port), self.timeout)

        try:
            if self.cfg.use_ssl:
                ctx = outbound_policy.tls_context(host=host)
                sock = ctx.wrap_socket(sock, server_hostname=host)
            sock.sendall(headers + body)
            raw = _recv_http_body(sock, self.timeout)
        finally:
            try:
                sock.close()
            except OSError:
                pass

        if not raw:
            raise ConnectionError("leere RPC-Antwort")
        if b"\r\n\r\n" not in raw:
            raise ConnectionError("ungültige HTTP-Antwort vom Node")
        _head, _, resp_body = raw.partition(b"\r\n\r\n")
        # chunked transfer
        if b"transfer-encoding: chunked" in _head.lower():
            resp_body = _dechunk(resp_body)
        try:
            data = json.loads(resp_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ConnectionError(
                f"RPC-Antwort kein JSON ({exc})"
            ) from exc
        if data.get("error"):
            err = data["error"]
            if isinstance(err, dict):
                msg = err.get("message") or str(err)
                code = err.get("code")
                raise RuntimeError(f"RPC {method} Fehler {code}: {msg}")
            raise RuntimeError(f"RPC {method}: {err}")
        return data.get("result")


def _dechunk(body: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(body):
        nl = body.find(b"\r\n", i)
        if nl < 0:
            break
        try:
            size = int(body[i:nl], 16)
        except ValueError:
            break
        i = nl + 2
        if size == 0:
            break
        out.extend(body[i : i + size])
        i += size + 2
    return bytes(out)


def _client_aus_config(
    env: dict[str, str],
    cfg: CoreRpcConfig,
    *,
    on_log: LogFn | None = None,
    timeout: float = 60.0,
) -> BitcoinRpcClient | None:
    if host_ist_onion(cfg.host):
        from core.tor import stelle_tor_socks_bereit
        from main import _parse_tor_proxy

        try:
            proxy = stelle_tor_socks_bereit(
                _parse_tor_proxy(env),
                env=env,
                log=on_log,
            )
        except Exception as exc:
            _log(on_log, f"Tor für Core-RPC nicht bereit: {exc}")
            return None
        cfg = CoreRpcConfig(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            use_ssl=cfg.use_ssl,
            tor_proxy=proxy,
        )
    return BitcoinRpcClient(cfg, timeout=timeout)


def stelle_core_client_bereit(
    env: dict[str, str],
    *,
    on_log: LogFn | None = None,
    timeout: float = 60.0,
) -> BitcoinRpcClient | None:
    """
    Lookup/Tx-Block-Client (NODE_IP). None wenn nicht konfiguriert.
    """
    cfg = config_from_env(env)
    if cfg is None or not cfg.configured:
        return None
    return _client_aus_config(env, cfg, on_log=on_log, timeout=timeout)


def stelle_utxo_core_client_bereit(
    env: dict[str, str],
    *,
    on_log: LogFn | None = None,
    timeout: float = 60.0,
) -> BitcoinRpcClient | None:
    """
    UTXO-Set-Client (UTXO_RPC_*, sonst Lookup-Core). Für scantxoutset.
    """
    cfg = config_utxo_from_env(env)
    if cfg is None or not cfg.configured:
        return None
    return _client_aus_config(env, cfg, on_log=on_log, timeout=timeout)


def verify_core_rpc(
    client: BitcoinRpcClient,
    *,
    on_log: LogFn | None = None,
) -> dict[str, Any]:
    """``getblockchaininfo`` — wirft bei Fehler."""
    _log(on_log, f"Prüfe Bitcoin Core {client.cfg.ziel}…")
    _log(on_log, f"Verbinde mit Bitcoin Core {client.cfg.host}:{client.cfg.port}…")
    info = client.call("getblockchaininfo")
    if not isinstance(info, dict):
        raise RuntimeError("getblockchaininfo: unerwartete Antwort")
    blocks = info.get("blocks")
    chain = info.get("chain")
    _log(
        on_log,
        f"Verbunden. Bitcoin Core · {chain} · Tip {blocks}",
    )
    return info


def _xpub_to_core_xpub(xpub: str) -> str:
    """SLIP-132 (zpub/ypub/…) → Standard-xpub für Core-Deskriptoren."""
    from embit.bip32 import HDKey

    hd = HDKey.from_string(xpub)
    # Mainnet xpub-Version erzwingen, falls SLIP-132
    try:
        from embit.networks import NETWORKS

        ver = NETWORKS["main"]["xpub"]
        return hd.to_base58(version=ver)
    except Exception:
        return hd.to_string()


def descriptors_for_key(
    schluessel: str,
    *,
    max_index: int,
    script_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    scantxoutset-Objekte für ein XPUB oder einen Output-Deskriptor.

    Range 0..max_index-1 (Core: end inklusive in manchen Versionen —
    wir nutzen [0, max_index]).
    """
    from main import ist_deskriptor, normalize_script_type, script_type_for_xpub

    ende = max(0, int(max_index))
    span = [0, ende]

    if ist_deskriptor(schluessel):
        desc = schluessel.strip()
        # Prüfsumme anhängen wenn fehlt — Core mag beides, mit # sicherer
        return [{"desc": desc, "range": span}]

    xpub = _xpub_to_core_xpub(schluessel)
    chosen = normalize_script_type(script_type or script_type_for_xpub(schluessel))
    prefix = schluessel[:4].lower()

    def zweige(schablone: str) -> list[str]:
        # Pfad *innerhalb* des Keys: wpkh(xpub/0/*), nicht wpkh(xpub)/0/*
        return [
            schablone.format(f"{xpub}/0/*"),
            schablone.format(f"{xpub}/1/*"),
        ]

    descs: list[str] = []
    if chosen == "legacy" or (chosen == "auto" and prefix in ("xpub", "tpub")):
        if chosen == "legacy":
            descs.extend(zweige("pkh({})"))
        elif chosen == "auto":
            descs.extend(zweige("pkh({})"))
    if chosen == "nested" or prefix in ("ypub", "upub") or (
        chosen == "auto" and prefix in ("xpub", "tpub")
    ):
        descs.extend(zweige("sh(wpkh({}))"))
    if chosen == "segwit" or prefix in ("zpub", "vpub") or (
        chosen == "auto" and prefix in ("xpub", "tpub", "zpub", "vpub")
    ):
        descs.extend(zweige("wpkh({})"))
    if chosen == "taproot" or (
        chosen == "auto" and prefix in ("xpub", "tpub")
    ):
        descs.extend(zweige("tr({})"))

    # Dedup + optional Prüfsumme über embit
    gesehen: set[str] = set()
    out: list[dict[str, Any]] = []
    for d in descs:
        if d in gesehen:
            continue
        gesehen.add(d)
        out.append({"desc": _desc_mit_checksum(d), "range": span})
    if not out:
        out = [
            {"desc": _desc_mit_checksum(f"wpkh({xpub}/0/*)"), "range": span},
            {"desc": _desc_mit_checksum(f"wpkh({xpub}/1/*)"), "range": span},
        ]
    return out


def _desc_mit_checksum(desc: str) -> str:
    """Hängt die Descriptor-Checksum an, wenn embit sie liefert."""
    text = (desc or "").strip()
    if "#" in text:
        return text
    try:
        from embit.descriptor import Descriptor

        return Descriptor.from_string(text).to_string()
    except Exception:
        return text


def _unspent_to_utxo(u: dict) -> dict | None:
    txid = (u.get("txid") or "").lower()
    if not txid:
        return None
    try:
        vout = int(u.get("vout", 0))
    except (TypeError, ValueError):
        return None
    try:
        amount = float(u.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    sats = int(round(amount * 100_000_000))
    try:
        height = int(u.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    spk = u.get("scriptPubKey") or ""
    address = None
    if spk:
        try:
            from embit.script import Script

            address = Script(bytes.fromhex(spk)).address()
        except Exception:
            address = None
    status: dict[str, Any] = {
        "confirmed": height > 0,
        "block_height": height if height > 0 else None,
    }
    if height > 0:
        try:
            from main import block_time_for_height

            ts = block_time_for_height(height)
            if ts:
                status["block_time"] = ts
        except Exception:
            pass
    return {
        "txid": txid,
        "vout": vout,
        "value": sats,
        "address": address,
        "status": status,
    }


def scantxoutset_status_prozent(result: Any) -> float | None:
    """
    Liest den Prozentwert aus ``scantxoutset status``.

    Core liefert ``null`` wenn kein Scan läuft, sonst
    ``{"progress": n}`` (0..100, selten 0..1).
    """
    from display import normalize_rpc_progress

    if result is None:
        return None
    if isinstance(result, (int, float)):
        return normalize_rpc_progress(float(result))
    if isinstance(result, dict) and "progress" in result:
        try:
            return normalize_rpc_progress(float(result["progress"]))
        except (TypeError, ValueError):
            return None
    return None


def _scantxoutset_status_poller(
    status_client: BitcoinRpcClient,
    stop: threading.Event,
    progress: Any,
    *,
    interval_s: float = 1.5,
) -> None:
    """
    Parallelthread: ``scantxoutset status`` auf eigener RPC-Verbindung.

    ``start`` blockiert den anderen Worker — Status geht nur so.
    Bei Job-Abbruch: ``abort``, damit ``start`` zurückkehrt.
    """
    t0 = time.monotonic()
    while not stop.wait(interval_s):
        try:
            from core.jobs import aktueller_zwischenstand

            stand = aktueller_zwischenstand()
            if stand is not None and stand.job.cancelled:
                try:
                    status_client.call("scantxoutset", ["abort"])
                except Exception:
                    pass
                return
        except Exception:
            pass

        try:
            raw = status_client.call("scantxoutset", ["status"])
        except Exception:
            progress.heartbeat(
                elapsed_s=time.monotonic() - t0,
                note="Status-Abfrage fehlgeschlagen, Scan läuft weiter",
            )
            continue

        pct = scantxoutset_status_prozent(raw)
        elapsed = time.monotonic() - t0
        if pct is None:
            progress.heartbeat(
                elapsed_s=elapsed,
                note="warte auf Node-Status",
            )
            continue
        if pct >= 99.0:
            progress.heartbeat(
                elapsed_s=elapsed,
                note="finalisiere auf Node",
                percent=pct,
            )
        else:
            progress.update(pct, elapsed_s=elapsed)


def scantxoutset_utxos(
    client: BitcoinRpcClient,
    schluessel_liste: list[str],
    *,
    max_index_by_key: dict[str, int] | None = None,
    default_max_index: int = 500,
    script_type_by_key: dict[str, str] | None = None,
    on_log: LogFn | None = None,
    on_progress: Callable[..., None] | None = None,
    status_client: BitcoinRpcClient | None = None,
    status_interval_s: float | None = None,
) -> tuple[list[dict], int | None]:
    """
    Läuft ``scantxoutset start`` und liefert (utxos, tip_height).

    Bricht einen hängenden Scan vorher ab. Während ``start`` blockiert,
    pollt ein Parallelthread ``scantxoutset status`` auf einer zweiten
    RPC-Verbindung und meldet den Prozentstand ins Log.
    """
    from display import ScantxoutsetProgressLine

    objs: list[dict[str, Any]] = []
    for key in schluessel_liste:
        mx = default_max_index
        if max_index_by_key and key in max_index_by_key:
            mx = int(max_index_by_key[key])
        st = None
        if script_type_by_key:
            st = script_type_by_key.get(key)
        objs.extend(
            descriptors_for_key(key, max_index=mx, script_type=st)
        )

    if not objs:
        return [], None

    _log(on_log, f"scantxoutset: {len(objs)} Deskriptor-Zweige…")
    try:
        client.call("scantxoutset", ["abort"])
    except Exception:
        pass

    progress = ScantxoutsetProgressLine(label="UTXO-Set (Core)")
    t0 = time.monotonic()
    stop = threading.Event()
    poller: threading.Thread | None = None
    try:
        if on_progress:
            try:
                on_progress("scantxoutset läuft auf dem Node…", sofort=True)
            except TypeError:
                on_progress("scantxoutset läuft auf dem Node…")

        # Eigene Verbindung: start hält einen RPC-Worker belegt.
        poll_client = status_client or BitcoinRpcClient(
            client.cfg,
            timeout=min(30.0, float(client.timeout) or 30.0),
        )
        if status_interval_s is not None:
            interval = float(status_interval_s)
        else:
            interval = 2.5 if host_ist_onion(client.cfg.host) else 1.5
        poller = threading.Thread(
            target=_scantxoutset_status_poller,
            args=(poll_client, stop, progress),
            kwargs={"interval_s": interval},
            name="scantxoutset-status",
            daemon=True,
        )
        poller.start()

        result = client.call("scantxoutset", ["start", objs])
    except Exception:
        progress.finish(success=False)
        raise
    finally:
        stop.set()
        if poller is not None:
            poller.join(timeout=5.0)

    progress.finish(success=True)
    dt = time.monotonic() - t0
    if not isinstance(result, dict):
        raise RuntimeError("scantxoutset: unerwartete Antwort")

    tip = result.get("height")
    try:
        tip_i = int(tip) if tip is not None else None
    except (TypeError, ValueError):
        tip_i = None

    utxos: list[dict] = []
    for u in result.get("unspents") or []:
        if not isinstance(u, dict):
            continue
        mapped = _unspent_to_utxo(u)
        if mapped:
            utxos.append(mapped)

    _log(
        on_log,
        f"scantxoutset: {len(utxos)} UTXO(s) in {dt:.1f}s"
        + (f" · Tip {tip_i}" if tip_i else ""),
    )
    return utxos, tip_i


def try_scantxoutset_for_xpubs(
    env: dict[str, str],
    xpubs: list[str],
    *,
    max_addresses_for=None,
    default_max: int = 500,
    wallet=None,
    on_log: LogFn | None = None,
    on_progress: Callable[..., None] | None = None,
) -> tuple[dict[str, list[dict]], int | None] | None:
    """
    Wenn Core konfiguriert und erreichbar: UTXOs je XPUB.

    Rückgabe None bei fehlender Config oder Verbindungsfehler
    (Caller fällt auf Electrum/BIP-158 zurück).
    """
    if not xpubs:
        return None

    def log(text: str) -> None:
        _log(on_log, text)
        if on_progress:
            try:
                on_progress(text, sofort=True)
            except TypeError:
                try:
                    on_progress(text)
                except TypeError:
                    pass

    # scantxoutset über Onion kann viele Minuten dauern.
    # Eigener UTXO-RPC-Slot (lokaler pruned Node) vor Lookup-Core (Start9).
    client = stelle_utxo_core_client_bereit(env, on_log=log, timeout=900.0)
    if client is None:
        return None
    try:
        info = verify_core_rpc(client, on_log=log)
    except Exception as exc:
        log(f"Bitcoin Core nicht erreichbar: {exc}")
        return None

    tip_info = None
    try:
        tip_info = int(info.get("blocks"))
    except (TypeError, ValueError):
        tip_info = None

    max_by: dict[str, int] = {}
    type_by: dict[str, str] = {}
    for x in xpubs:
        if max_addresses_for is not None:
            try:
                max_by[x] = int(max_addresses_for(x))
            except Exception:
                max_by[x] = default_max
        else:
            max_by[x] = default_max
        if wallet is not None:
            try:
                type_by[x] = wallet.script_type_for(x)  # type: ignore[attr-defined]
            except Exception:
                pass

    # Ein Scan für alle Keys — schneller als nacheinander
    try:
        alle, tip_scan = scantxoutset_utxos(
            client,
            xpubs,
            max_index_by_key=max_by,
            default_max_index=default_max,
            script_type_by_key=type_by or None,
            on_log=log,
            on_progress=on_progress,
        )
    except Exception as exc:
        log(f"scantxoutset fehlgeschlagen: {exc}")
        return None

    tip = tip_scan if tip_scan is not None else tip_info

    # UTXOs den XPUBs zuordnen über Adresse
    from main import derive_addresses

    by_xpub: dict[str, list[dict]] = {x: [] for x in xpubs}
    addr_to_xpub: dict[str, str] = {}
    for x in xpubs:
        mx = max_by.get(x, default_max)
        # max_addresses = 2 * indices roughly
        addrs = derive_addresses(x, max_addresses=max(mx * 2, 2))
        for a in addrs:
            addr_to_xpub[a] = x

    orphan = 0
    for u in alle:
        a = u.get("address")
        if a and a in addr_to_xpub:
            by_xpub[addr_to_xpub[a]].append(u)
        else:
            orphan += 1
    if orphan:
        log(f"scantxoutset: {orphan} UTXO(s) ohne Wallet-Zuordnung (Range?)")

    return by_xpub, tip


def _core_vout_to_dict(vout: dict, index: int) -> dict:
    spk = vout.get("scriptPubKey") or {}
    if not isinstance(spk, dict):
        spk = {}
    value = vout.get("value", 0)
    try:
        btc = float(value)
    except (TypeError, ValueError):
        btc = 0.0
    return {
        "n": int(vout.get("n", index)),
        "value": btc,
        "scriptPubKey": {
            "hex": spk.get("hex") or "",
            "address": spk.get("address"),
            "addresses": list(spk.get("addresses") or []),
            "type": spk.get("type"),
        },
    }


def _core_vin_to_dict(vin: dict) -> dict:
    if "coinbase" in vin:
        return {"is_coinbase": True, "coinbase": vin.get("coinbase")}
    return {
        "txid": str(vin.get("txid") or ""),
        "vout": int(vin.get("vout", 0)),
    }


def normalize_core_tx(tx: dict, client: BitcoinRpcClient | None = None) -> dict:
    """Core-``getrawtransaction`` verbose → Format wie Fulcrum/P2P für analyze."""
    if not tx:
        return tx
    out = {
        "txid": str(tx.get("txid") or ""),
        "vin": [_core_vin_to_dict(v) for v in (tx.get("vin") or [])],
        "vout": [
            _core_vout_to_dict(v, i)
            for i, v in enumerate(tx.get("vout") or [])
        ],
    }
    confirmations = int(tx.get("confirmations") or 0)
    blockhash = tx.get("blockhash")
    blocktime = tx.get("blocktime") or tx.get("time")
    status: dict[str, Any] = {"confirmed": confirmations > 0}
    if blocktime:
        status["block_time"] = int(blocktime)
    if blockhash and client is not None:
        try:
            header = client.call("getblockheader", [blockhash])
            if isinstance(header, dict) and header.get("height") is not None:
                status["block_height"] = int(header["height"])
            if isinstance(header, dict) and header.get("time") and "block_time" not in status:
                status["block_time"] = int(header["time"])
        except Exception:
            pass
    if status.get("confirmed") or status.get("block_height") or status.get("block_time"):
        out["status"] = status
    return out


def _embit_tx_to_analyze_dict(tx) -> dict:
    """embit.Transaction → analyze-kompatibles Dict (Werte in BTC)."""
    null = b"\x00" * 32
    vins = []
    for vin in tx.vin:
        if bytes(vin.txid) == null:
            vins.append({"is_coinbase": True})
        else:
            vins.append({"txid": bytes(vin.txid).hex(), "vout": int(vin.vout)})
    vouts = []
    for n, vout in enumerate(tx.vout):
        try:
            addr = vout.script_pubkey.address()
        except Exception:
            addr = None
        vouts.append({
            "n": n,
            "value": vout.value / 1e8,
            "scriptPubKey": {
                "hex": bytes(vout.script_pubkey.data).hex(),
                "address": addr,
            },
        })
    return {"txid": tx.txid().hex(), "vin": vins, "vout": vouts}


def fetch_tx_core(client: BitcoinRpcClient, txid: str) -> dict:
    """
    ``getrawtransaction`` — braucht ``-txindex=1`` für historische Tx,
    sonst nur Mempool/Wallet. Wirft bei Fehler (kein stilles None).
    """
    from embit.transaction import Transaction

    key = (txid or "").strip().lower()
    if len(key) != 64:
        raise ValueError(f"ungültige TxID: {txid!r}")

    try:
        raw = client.call("getrawtransaction", [key, True])
    except RuntimeError as exc:
        text = str(exc).lower()
        # Verbose unbekannt oder Tx fehlt — einmal Hex versuchen, sonst
        # den Originalfehler durchreichen (Caller macht Fallback).
        if "not found" in text or "no such" in text or "code\":-5" in text or "fehler -5" in text:
            raise
        try:
            raw = client.call("getrawtransaction", [key, False])
        except Exception:
            raise exc from None

    if isinstance(raw, dict):
        return normalize_core_tx(raw, client)
    if isinstance(raw, str):
        return _embit_tx_to_analyze_dict(Transaction.from_string(raw.strip()))
    raise RuntimeError(f"unerwartete getrawtransaction-Antwort: {type(raw)}")


def pruneheight_of(client: BitcoinRpcClient) -> int | None:
    """
    Unterste gehaltene Blockhöhe bei pruned Node; ``0`` wenn nicht gepruned;
    ``None`` wenn Abfrage scheitert.
    """
    try:
        info = client.call("getblockchaininfo")
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    if not info.get("pruned"):
        return 0
    try:
        return int(info.get("pruneheight") or 0)
    except (TypeError, ValueError):
        return None


def _cfg_ziel(cfg: CoreRpcConfig) -> str:
    return f"{cfg.host}:{cfg.port}"


def stelle_tx_lookup_rollen(
    env: dict[str, str],
    *,
    on_log: LogFn | None = None,
    timeout: float = 30.0,
) -> tuple[BitcoinRpcClient | None, BitcoinRpcClient | None, int | None]:
    """
    (lokal_oder_None, archival_lookup, local_pruneheight).

    *lokal* nur bei dediziertem ``UTXO_RPC_*``, der sich vom Lookup-Host unterscheidet.
    """
    from core.local_bitcoind import utxo_rpc_dedicated

    archival = stelle_core_client_bereit(env, on_log=on_log, timeout=timeout)
    lokal: BitcoinRpcClient | None = None
    ph: int | None = None
    if utxo_rpc_dedicated(env):
        lokal = stelle_utxo_core_client_bereit(env, on_log=on_log, timeout=timeout)
        if (
            lokal is not None
            and archival is not None
            and _cfg_ziel(lokal.cfg) == _cfg_ziel(archival.cfg)
        ):
            # Derselbe Node — eine Verbindung reicht (archival).
            lokal = None
        elif lokal is not None:
            ph = pruneheight_of(lokal)
    return lokal, archival, ph


def fetch_tx_from_block_core(
    client: BitcoinRpcClient,
    txid: str,
    height: int,
) -> dict:
    """Tx aus ``getblock`` (verbosity 2) — braucht den Block noch lokal."""
    key = (txid or "").strip().lower()
    if int(height) < 0:
        raise ValueError(f"ungültige Höhe: {height}")
    blockhash = client.call("getblockhash", [int(height)])
    block = client.call("getblock", [blockhash, 2])
    if not isinstance(block, dict):
        raise RuntimeError("getblock: unerwartete Antwort")
    for raw in block.get("tx") or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("txid") or "").lower() == key:
            # Block-Kontext für status
            if "blockhash" not in raw:
                raw = dict(raw)
                raw["blockhash"] = blockhash
            if "blocktime" not in raw and block.get("time") is not None:
                raw["blocktime"] = block.get("time")
            if "confirmations" not in raw and block.get("confirmations") is not None:
                raw["confirmations"] = block.get("confirmations")
            tx = normalize_core_tx(raw, client)
            st = tx.setdefault("status", {})
            st["block_height"] = int(height)
            return tx
    raise RuntimeError(f"Tx {key[:16]}… nicht in Block {height}")


def _core_reihenfolge(
    *,
    local: BitcoinRpcClient | None,
    archival: BitcoinRpcClient | None,
    local_pruneheight: int | None,
    height: int | None,
) -> list[tuple[str, BitcoinRpcClient]]:
    """Welche Core-Verbindung zuerst — lokal nur wenn Höhe noch gehalten."""
    if local is None and archival is None:
        return []
    if local is None:
        return [("lookup", archival)] if archival else []
    if archival is None:
        return [("lokal", local)]

    # Höhe unter/gleich pruneheight → Block weg → archival zuerst.
    if (
        height is not None
        and int(height) > 0
        and local_pruneheight is not None
        and int(height) <= int(local_pruneheight)
    ):
        return [("lookup", archival), ("lokal", local)]
    # Unbekannt oder jung genug → lokal (Loopback) zuerst.
    return [("lokal", local), ("lookup", archival)]


def fetch_tx_core_mit_rollen(
    txid: str,
    *,
    local: BitcoinRpcClient | None = None,
    archival: BitcoinRpcClient | None = None,
    local_pruneheight: int | None = None,
    height: int | None = None,
    on_log: LogFn | None = None,
) -> dict:
    """
    Tx über lokalen pruned Node und/oder Lookup-Core (Start9).

    Reihenfolge: lokal wenn Höhe > pruneheight (oder unbekannt), sonst Lookup;
    bei Fehler die andere Rolle; optional ``getblock`` bei bekannter Höhe.
    """
    key = (txid or "").strip().lower()
    hoehe = int(height) if (height and int(height) > 0) else None
    fehler: list[str] = []
    reihenfolge = _core_reihenfolge(
        local=local,
        archival=archival,
        local_pruneheight=local_pruneheight,
        height=hoehe,
    )
    if not reihenfolge:
        raise RuntimeError("kein Core-RPC für Tx-Lookup konfiguriert")

    for name, client in reihenfolge:
        try:
            _log(on_log, f"Tx {key[:16]}… über Core-RPC ({name})…")
            return fetch_tx_core(client, key)
        except Exception as exc:
            fehler.append(f"{name}/getrawtransaction: {exc}")

    if hoehe is not None:
        for name, client in reihenfolge:
            # getblock nur sinnvoll wenn Block noch da.
            if (
                name == "lokal"
                and local_pruneheight is not None
                and hoehe <= int(local_pruneheight)
            ):
                continue
            try:
                _log(on_log, f"Tx {key[:16]}… Core-getblock {hoehe} ({name})…")
                return fetch_tx_from_block_core(client, key, hoehe)
            except Exception as exc:
                fehler.append(f"{name}/getblock: {exc}")

    raise RuntimeError("; ".join(fehler) if fehler else "Core-Tx-Lookup fehlgeschlagen")
