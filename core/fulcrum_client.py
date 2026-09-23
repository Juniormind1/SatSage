"""Fulcrum/Electrum JSON-RPC-Client, Notify-Session und Verbindungs-Pools."""
from __future__ import annotations

import hashlib
import json
import queue
import socket
import ssl
import threading
from typing import Any

from embit.script import address_to_scriptpubkey

import outbound_policy

from core.fulcrum_transport import _socks5_connect


FULCRUM_DEFAULT_PORT = 50002
FULCRUM_CONNECT_TIMEOUT = 8
FULCRUM_ONION_TIMEOUT = 30
#: Bei Tor/großen Tx-Antworten: nach Timeout neu verbinden und erneut fragen.
FULCRUM_REQUEST_RETRIES = 3
#: Electrum-JSON-RPC-Batch über Tor: Calls pro Nachricht (Timeout/Antwortgröße).
TOR_RPC_BATCH_SIZE = 32
CLIENT_NAME = "SatSage"
PROTOCOL_VERSION = "1.4"
_LISTUNSPENT_METHOD = "blockchain.scripthash.listunspent"
_GET_HISTORY_METHOD = "blockchain.scripthash.get_history"
_PROBE_SCRIPT_HASH = "0" * 64


def _is_unknown_method_error(exc: BaseException, method: str) -> bool:
    msg = str(exc).lower()
    return "unknown method" in msg and method.lower() in msg


def parse_electrum_server_software(version_result: Any) -> tuple[str, str]:
    """
    Kurzer Implementierungsname + Rohstring aus ``server.version``.

    Electrum-RPC liefert typisch ``[server_string, protocol]``, z. B.
    ``["/libbitcoin:4.0.0/", "1.4"]``, ``["electrs/0.10.5", "1.4"]``,
    ``["Fulcrum 1.9.1", "1.4"]``. Rückgabe: ``(label, roh)`` — label für
    die UI-Pille (``electrs`` / ``fulcrum`` / ``libbitcoin`` / …).
    """
    roh = ""
    if isinstance(version_result, (list, tuple)) and version_result:
        roh = str(version_result[0] or "").strip()
    elif isinstance(version_result, str):
        roh = version_result.strip()
    if not roh:
        return "", ""
    klein = roh.lower().strip().strip("/")
    # "/libbitcoin:4.0.0/" · electrs/0.10 · Fulcrum 1.9
    if "libbitcoin" in klein:
        return "libbitcoin", roh
    if "fulcrum" in klein:
        return "fulcrum", roh
    if "electrs" in klein:
        return "electrs", roh
    if "electrumx" in klein or "electrum-x" in klein:
        return "electrumx", roh
    if "rostrum" in klein:
        return "rostrum", roh
    # Unbekannt: erstes Token (ohne Versionszahlen-Pfad)
    token = klein.split("/")[0].split(":")[0].split()[0]
    token = "".join(c for c in token if c.isalnum() or c in "-_")[:24]
    return (token or "electrum"), roh


def supports_listunspent(client: "FulcrumClient") -> bool:
    """Prüft, ob der Server blockchain.scripthash.listunspent unterstützt."""
    try:
        client.request(_LISTUNSPENT_METHOD, [_PROBE_SCRIPT_HASH])
        return True
    except RuntimeError as exc:
        if _is_unknown_method_error(exc, _LISTUNSPENT_METHOD):
            return False
        raise


class FulcrumClient:
    """Synchroner Electrum-Protokoll-Client für Fulcrum."""

    def __init__(
        self,
        host: str,
        port: int = FULCRUM_DEFAULT_PORT,
        use_ssl: bool = True,
        timeout: int = FULCRUM_CONNECT_TIMEOUT,
        tor_proxy: tuple[str, int] | None = None,
    ):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.tor_proxy = tor_proxy
        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        # Genau ein server.version pro TCP-Session (libbitcoin: zweites → bad_request).
        self._handshaked = False
        self.server_version: Any = None
        self.server_software: str = ""
        self.server_software_raw: str = ""

    @staticmethod
    def _outbound_values() -> dict[str, str] | None:
        """`.env` für Outbound-Allowlist (OEFFENTLICHE_ELECTRUM u. a.)."""
        try:
            from core.env_bootstrap import _load_dotenv

            return _load_dotenv()
        except Exception:
            try:
                import main as main_mod

                return main_mod._load_dotenv()
            except Exception:
                return None

    def connect(self) -> None:
        outbound_policy.ensure_resolves_to_allowed_host(
            self.host,
            service="fulcrum",
            values=self._outbound_values(),
        )
        if self.tor_proxy:
            proxy_host, proxy_port = self.tor_proxy
            raw = _socks5_connect(
                proxy_host, proxy_port, self.host, self.port, self.timeout
            )
        else:
            raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.use_ssl:
            ctx = outbound_policy.tls_context(host=self.host)
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)
        else:
            self._sock = raw
        self._handshaked = False
        self.server_version = None
        self.server_software = ""
        self.server_software_raw = ""
        # Connect-Timeout gilt sonst nicht zuverlässig für spätere recv —
        # ohne das hängt get_history über Tor minutenlang ohne Abbruch.
        try:
            self._sock.settimeout(float(self.timeout))
        except OSError:
            pass

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._handshaked = False

    def _apply_server_version(self, version_result: Any) -> None:
        label, roh = parse_electrum_server_software(version_result)
        self.server_version = version_result
        self.server_software = label
        self.server_software_raw = roh

    def _handshake_locked(self) -> Any:
        """
        ``server.version`` genau einmal pro TCP-Session.

        libbitcoin antwortet auf ein zweites Handshake mit bad_request /
        „moin moin“-Geschwätz — deshalb kein erneutes ``server.version``.
        Aufruf nur unter ``self._lock``.
        """
        if self._handshaked:
            return self.server_version
        ver = self._request_once("server.version", [CLIENT_NAME, PROTOCOL_VERSION])
        self._apply_server_version(ver)
        self._handshaked = True
        return ver

    def handshake(self) -> Any:
        """Electrum-Handshake (einmalig). Siehe ``_handshake_locked``."""
        with self._lock:
            return self._handshake_locked()

    def _recv_json_line(self) -> Any:
        """Eine newline-terminierte JSON-Nachricht vom Socket lesen."""
        if not self._sock:
            raise RuntimeError("Fulcrum-Client nicht verbunden")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Fulcrum-Verbindung geschlossen")
            buf += chunk
        return json.loads(buf.decode("utf-8"))

    @staticmethod
    def _result_from_response(response: Any) -> Any:
        if not isinstance(response, dict):
            raise RuntimeError(f"Ungültige Electrum-Antwort: {type(response).__name__}")
        if response.get("error"):
            err = response["error"]
            if isinstance(err, dict):
                raise RuntimeError(err.get("message", err))
            raise RuntimeError(str(err))
        return response.get("result")

    def _request_once(self, method: str, params: list | None = None) -> Any:
        if not self._sock:
            raise RuntimeError("Fulcrum-Client nicht verbunden")

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }
        data = (json.dumps(payload) + "\n").encode("utf-8")
        self._sock.sendall(data)
        return self._result_from_response(self._recv_json_line())

    def _request_batch_once(
        self, calls: list[tuple[str, list | None]],
    ) -> list[Any]:
        """
        Electrum-JSON-RPC-Batch: eine Nachricht, Antworten per id.

        Spec: Request als JSON-Array; Server antwortet mit Array oder
        einzeln newline-getrennt. Reihenfolge der Rückgabe = *calls*.
        """
        if not self._sock:
            raise RuntimeError("Fulcrum-Client nicht verbunden")
        if not calls:
            return []

        payloads: list[dict] = []
        id_order: list[int] = []
        for method, params in calls:
            self._request_id += 1
            rid = self._request_id
            id_order.append(rid)
            payloads.append({
                "jsonrpc": "2.0",
                "id": rid,
                "method": method,
                "params": params or [],
            })
        data = (json.dumps(payloads) + "\n").encode("utf-8")
        self._sock.sendall(data)

        by_id: dict[int, Any] = {}
        first = self._recv_json_line()
        if isinstance(first, list):
            for item in first:
                if isinstance(item, dict) and "id" in item:
                    by_id[int(item["id"])] = item
        elif isinstance(first, dict) and "id" in first:
            by_id[int(first["id"])] = first
            while len(by_id) < len(id_order):
                nxt = self._recv_json_line()
                if isinstance(nxt, list):
                    for item in nxt:
                        if isinstance(item, dict) and "id" in item:
                            by_id[int(item["id"])] = item
                elif isinstance(nxt, dict) and "id" in nxt:
                    by_id[int(nxt["id"])] = nxt
                else:
                    raise RuntimeError("Batch-Antwort ohne id")
        else:
            raise RuntimeError("Unerwartete Batch-Antwort vom Electrum-Server")

        results: list[Any] = []
        for rid in id_order:
            if rid not in by_id:
                raise RuntimeError(f"Batch-Antwort fehlt für id={rid}")
            results.append(self._result_from_response(by_id[rid]))
        return results

    def request(self, method: str, params: list | None = None) -> Any:
        """
        JSON-RPC-Aufruf. Bei Timeout/Abbrecher (typisch Tor + große Tx)
        bis ``FULCRUM_REQUEST_RETRIES`` neu verbinden und wiederholen.
        """
        if method == "server.version":
            # Immer über handshake — kein zweites version auf derselben Session.
            return self.handshake()
        letzter: BaseException | None = None
        with self._lock:
            for versuch in range(1, FULCRUM_REQUEST_RETRIES + 1):
                try:
                    if not self._handshaked and self._sock is not None:
                        self._handshake_locked()
                    return self._request_once(method, params)
                except (TimeoutError, socket.timeout, ConnectionError, BrokenPipeError, OSError) as exc:
                    letzter = exc
                    if versuch >= FULCRUM_REQUEST_RETRIES:
                        break
                    self.close()
                    try:
                        self.connect()
                        self._handshake_locked()
                    except Exception as reconnect_exc:
                        letzter = reconnect_exc
                        continue
            assert letzter is not None
            raise TimeoutError(
                f"Fulcrum {method} nach {FULCRUM_REQUEST_RETRIES} Versuchen "
                f"fehlgeschlagen ({letzter})"
            ) from letzter

    def request_batch(
        self, calls: list[tuple[str, list | None]],
    ) -> list[Any]:
        """
        Mehrere JSON-RPC-Calls in einer Runde (Electrum-Batch).

        * Nur bei ``tor_proxy`` und ≥2 Calls wirklich batchen — sonst
          sequenziell ``request`` (LAN/Parallel-Pool braucht das nicht).
        * Chunking über ``TOR_RPC_BATCH_SIZE`` (Antwortgröße/Timeouts).
        * Reihenfolge der Ergebnisse = Reihenfolge von *calls*.
        """
        if not calls:
            return []
        if not self.tor_proxy or len(calls) == 1:
            return [self.request(m, p) for m, p in calls]

        out: list[Any] = []
        chunk_n = max(1, int(TOR_RPC_BATCH_SIZE))
        for start in range(0, len(calls), chunk_n):
            chunk = calls[start : start + chunk_n]
            if len(chunk) == 1:
                out.append(self.request(chunk[0][0], chunk[0][1]))
                continue
            letzter: BaseException | None = None
            with self._lock:
                for versuch in range(1, FULCRUM_REQUEST_RETRIES + 1):
                    try:
                        if not self._handshaked and self._sock is not None:
                            self._handshake_locked()
                        out.extend(self._request_batch_once(chunk))
                        letzter = None
                        break
                    except (
                        TimeoutError,
                        socket.timeout,
                        ConnectionError,
                        BrokenPipeError,
                        OSError,
                    ) as exc:
                        letzter = exc
                        if versuch >= FULCRUM_REQUEST_RETRIES:
                            break
                        self.close()
                        try:
                            self.connect()
                            self._handshake_locked()
                        except Exception as reconnect_exc:
                            letzter = reconnect_exc
                            continue
                if letzter is not None:
                    raise TimeoutError(
                        f"Fulcrum-Batch ({len(chunk)} Calls) nach "
                        f"{FULCRUM_REQUEST_RETRIES} Versuchen fehlgeschlagen "
                        f"({letzter})"
                    ) from letzter
        return out

    def tor_batch_sinnvoll(self, n_calls: int) -> bool:
        """True wenn Batch über Tor RTTs spart (eigener Electrs@Tor)."""
        return bool(self.tor_proxy) and int(n_calls) >= 2


class FulcrumNotifySession:
    """
    Eigene Electrs-Verbindung für ``scripthash.subscribe`` / Header-Subscribe.

    Liest in einem Hintergrund-Thread; Antworten und Server-Notifications
    (JSON-RPC ohne ``id`` bzw. mit ``method``) werden getrennt behandelt.
    Der normale ``FulcrumClient`` bleibt request/response und thread-sicher
    für Scans — Subscribe braucht einen ungestörten Reader.
    """

    def __init__(
        self,
        host: str,
        port: int = FULCRUM_DEFAULT_PORT,
        use_ssl: bool = True,
        timeout: int = FULCRUM_CONNECT_TIMEOUT,
        tor_proxy: tuple[str, int] | None = None,
        *,
        on_scripthash=None,
        on_header=None,
        on_log=None,
        on_disconnect=None,
    ):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.tor_proxy = tor_proxy
        self.on_scripthash = on_scripthash
        self.on_header = on_header
        self.on_log = on_log
        self.on_disconnect = on_disconnect
        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._request_id = 0
        self._send_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._buf = b""

    def _sag(self, text: str) -> None:
        if self.on_log:
            try:
                self.on_log(text)
            except Exception:
                pass

    def connect(self) -> None:
        outbound_policy.ensure_resolves_to_allowed_host(
            self.host,
            service="fulcrum",
            values=FulcrumClient._outbound_values(),
        )
        if self.tor_proxy:
            proxy_host, proxy_port = self.tor_proxy
            raw = _socks5_connect(
                proxy_host, proxy_port, self.host, self.port, self.timeout
            )
        else:
            raw = socket.create_connection(
                (self.host, self.port), timeout=self.timeout,
            )
        if self.use_ssl:
            ctx = outbound_policy.tls_context(host=self.host)
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)
        else:
            self._sock = raw
        # Blocking recv im Reader; send mit Timeout
        self._sock.settimeout(None)

    def start(self) -> None:
        if self._reader and self._reader.is_alive():
            return
        self._stop.clear()
        if not self._sock:
            self.connect()
        self._reader = threading.Thread(
            target=self._lese_schleife,
            name="fulcrum-notify",
            daemon=True,
        )
        self._reader.start()

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=3.0)
        self._reader = None
        with self._pending_lock:
            for q in self._pending.values():
                try:
                    q.put_nowait({"error": {"message": "session closed"}})
                except Exception:
                    pass
            self._pending.clear()

    def close(self) -> None:
        self.stop()

    def _lese_schleife(self) -> None:
        try:
            while not self._stop.is_set() and self._sock is not None:
                try:
                    chunk = self._sock.recv(65536)
                except (TimeoutError, socket.timeout):
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                self._buf += chunk
                while b"\n" in self._buf:
                    zeile, self._buf = self._buf.split(b"\n", 1)
                    if not zeile.strip():
                        continue
                    try:
                        msg = json.loads(zeile.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    self._dispatch(msg)
        finally:
            if self.on_disconnect and not self._stop.is_set():
                try:
                    self.on_disconnect()
                except Exception:
                    pass

    def _dispatch(self, msg: dict) -> None:
        mid = msg.get("id")
        if mid is not None:
            with self._pending_lock:
                q = self._pending.get(int(mid))
            if q is not None:
                q.put(msg)
                return
        method = msg.get("method")
        params = msg.get("params") or []
        if method == "blockchain.scripthash.subscribe" and self.on_scripthash:
            try:
                if len(params) >= 2:
                    self.on_scripthash(str(params[0]), params[1])
                elif len(params) == 1:
                    self.on_scripthash(str(params[0]), None)
            except Exception:
                pass
        elif method == "blockchain.headers.subscribe" and self.on_header:
            try:
                self.on_header(params[0] if params else None)
            except Exception:
                pass

    def request(self, method: str, params: list | None = None, *, timeout: float = 60.0) -> Any:
        if self._stop.is_set() or not self._sock:
            raise RuntimeError("Fulcrum-Notify-Session nicht verbunden")
        with self._send_lock:
            self._request_id += 1
            rid = self._request_id
            q: queue.Queue = queue.Queue(maxsize=1)
            with self._pending_lock:
                self._pending[rid] = q
            payload = {
                "jsonrpc": "2.0",
                "id": rid,
                "method": method,
                "params": params or [],
            }
            data = (json.dumps(payload) + "\n").encode("utf-8")
            try:
                self._sock.sendall(data)
            except OSError as exc:
                with self._pending_lock:
                    self._pending.pop(rid, None)
                raise ConnectionError(str(exc)) from exc
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(rid, None)
            raise TimeoutError(f"Fulcrum {method} Timeout") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)
        if msg.get("error"):
            err = msg["error"]
            if isinstance(err, dict):
                raise RuntimeError(err.get("message", err))
            raise RuntimeError(str(err))
        return msg.get("result")

    def subscribe_scripthash(self, scripthash: str) -> Any:
        """Abonniert Status-Änderungen; Rückgabe: aktueller Status-Hash."""
        return self.request(
            "blockchain.scripthash.subscribe", [scripthash],
        )

    def subscribe_headers(self) -> Any:
        """Abonniert neue Block-Header; Rückgabe: aktueller Header."""
        return self.request("blockchain.headers.subscribe", [])


def connect_fulcrum(
    host: str,
    port: int = FULCRUM_DEFAULT_PORT,
    use_ssl: bool = True,
    timeout: int = FULCRUM_CONNECT_TIMEOUT,
    tor_proxy: tuple[str, int] | None = None,
    *,
    require_listunspent: bool = False,
) -> tuple[FulcrumClient | None, str | None]:
    """Verbindet zu Fulcrum; gibt (client, None) oder (None, Fehlertext) zurück."""
    client = FulcrumClient(
        host,
        port,
        use_ssl=use_ssl,
        timeout=timeout,
        tor_proxy=tor_proxy,
    )
    try:
        client.connect()
        # Ein Handshake — Ergebnis liegt an client.server_software (Pille).
        client.handshake()
        if require_listunspent and not supports_listunspent(client):
            client.close()
            return None, "listunspent nicht unterstützt"
    except Exception as exc:
        client.close()
        return None, str(exc)
    return client, None


class RotatingFulcrumPool:
    """Round-robin über mehrere Fulcrum-Verbindungen (öffentliche Server)."""

    def __init__(self, clients: list[FulcrumClient]):
        if not clients:
            raise ValueError("mindestens ein Fulcrum-Client erforderlich")
        self._clients = clients
        self._index = 0
        self._lock = threading.Lock()

    @property
    def host(self) -> str:
        return f"rotation({len(self._clients)} Server)"

    def tor_batch_sinnvoll(self, n_calls: int) -> bool:
        """Kein Tor-Batch über Rotation — ``request_batch`` fehlt am Pool."""
        return False

    def request(self, method: str, params: list | None = None) -> Any:
        last_exc: BaseException | None = None
        n = len(self._clients)
        for _ in range(n):
            with self._lock:
                client = self._clients[self._index]
                self._index = (self._index + 1) % n
            try:
                return client.request(method, params)
            except RuntimeError as exc:
                if _is_unknown_method_error(exc, method):
                    last_exc = exc
                    continue
                raise
            except (TimeoutError, socket.timeout, ConnectionError, BrokenPipeError, OSError) as exc:
                # Nächster Onion/Clearnet-Server — sonst hängt der Verlauf
                # minutenlang auf einem toten Peer bei „noch 59 von 59“.
                last_exc = exc
                try:
                    client.close()
                except Exception:
                    pass
                try:
                    client.connect()
                except Exception:
                    pass
                continue
        if last_exc is not None:
            raise TimeoutError(
                f"Fulcrum-Rotation: alle {n} Server für {method} gescheitert "
                f"({last_exc})"
            ) from last_exc
        raise RuntimeError("kein Fulcrum-Server verfügbar")

    def close(self) -> None:
        for client in self._clients:
            client.close()


class SanctionsClearnetPool:
    """
    Feste Zuordnung: ein Worker-Thread pro Verbindung.

    Beim Clearnet-Pool ist das je ein anderer Server. Beim eigenen, privat
    adressierten Node sind es mehrere Verbindungen zum selben Host — der
    verträgt die Last selbst, und der Scan bleibt trotzdem parallel.
    """

    def __init__(self, clients: list[FulcrumClient]):
        if not clients:
            raise ValueError("mindestens ein Fulcrum-Client erforderlich")
        self._clients = clients

    def __len__(self) -> int:
        return len(self._clients)

    @property
    def primary(self) -> FulcrumClient:
        return self._clients[0]

    @property
    def host(self) -> str:
        hosts = {client.host for client in self._clients}
        if len(hosts) == 1:
            einziger = self._clients[0].host
            if len(self._clients) == 1:
                return einziger
            # Mehrere Verbindungen zum selben Host: eigener Node.
            return f"{einziger} ({len(self._clients)} Verbindungen)"
        return f"clearnet({len(self._clients)} Server)"

    def client_at(self, worker_id: int) -> FulcrumClient:
        return self._clients[worker_id % len(self._clients)]

    def worker_labels(self) -> list[str]:
        return [client.host for client in self._clients]

    def close(self) -> None:
        for client in self._clients:
            client.close()


def address_to_scripthash(address: str) -> str:
    """Electrum-Scripthash (SHA256 des scriptPubKey, reversed hex)."""
    script_pubkey = address_to_scriptpubkey(address).data
    return hashlib.sha256(script_pubkey).digest()[::-1].hex()


def parallel_ueber_pool(pool, aufgaben: list, arbeit, *, fortschritt=None) -> list:
    """
    Verteilt Aufgaben auf die Verbindungen eines Pools.

    Ein FulcrumClient hält genau einen Socket und verträgt keine
    gleichzeitigen Anfragen — deshalb bekommt jeder Worker-Thread über
    ``pool.client_at`` seine eigene Verbindung, statt sich eine zu teilen.

    *arbeit* ist ``(client, aufgabe) -> ergebnis``. Die Rückgabe steht in der
    Reihenfolge der Aufgaben, nicht in der ihrer Fertigstellung: Sonst hinge
    das Ergebnis davon ab, welcher Thread zuerst durch war.

    Eine fehlgeschlagene Aufgabe liefert None und stoppt die übrigen nicht —
    eine einzelne unerreichbare Adresse soll den ganzen Scan nicht entwerten.
    Ein Abbruchwunsch wirkt zwischen den Aufgaben; laufende Abfragen werden zu
    Ende geführt.
    """
    from display import is_list_abort_requested

    ergebnisse: list = [None] * len(aufgaben)
    if not aufgaben:
        return ergebnisse

    arbeitsvorrat: queue.Queue = queue.Queue()
    for nummer, aufgabe in enumerate(aufgaben):
        arbeitsvorrat.put((nummer, aufgabe))

    fertig = 0
    sperre = threading.Lock()
    worker_count = max(1, min(len(pool), len(aufgaben)))

    def worker(worker_id: int) -> None:
        nonlocal fertig
        client = pool.client_at(worker_id)
        while not is_list_abort_requested():
            try:
                nummer, aufgabe = arbeitsvorrat.get_nowait()
            except queue.Empty:
                break
            try:
                ergebnisse[nummer] = arbeit(client, aufgabe)
            except Exception:
                ergebnisse[nummer] = None
            if fortschritt is not None:
                with sperre:
                    fertig += 1
                    fortschritt(fertig, len(aufgaben))

    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True)
        for i in range(worker_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return ergebnisse

