"""Fulcrum-Anbindung über das Electrum-Protokoll (TCP/SSL)."""
from __future__ import annotations

import hashlib
import json
import queue
import socket
import ssl
import threading
from typing import Any

from embit.script import Script, address_to_scriptpubkey
from embit.transaction import Transaction

import struct
import outbound_policy


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("SOCKS5-Verbindung unerwartet geschlossen")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _socks5_connect(
    proxy_host: str,
    proxy_port: int,
    dest_host: str,
    dest_port: int,
    timeout: int,
) -> socket.socket:
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        sock.sendall(b"\x05\x01\x00")
        greeting = sock.recv(2)
        if len(greeting) != 2 or greeting[0] != 0x05 or greeting[1] != 0x00:
            raise ConnectionError("Tor-SOCKS5-Proxy nicht erreichbar")

        host_bytes = dest_host.encode("idna")
        request = (
            b"\x05\x01\x00\x03"
            + bytes([len(host_bytes)])
            + host_bytes
            + struct.pack(">H", dest_port)
        )
        sock.sendall(request)

        header = _recv_exact(sock, 4)
        if header[0] != 0x05 or header[1] != 0x00:
            raise ConnectionError(f"SOCKS5-Connect fehlgeschlagen (Status {header[1]})")

        atyp = header[3]
        if atyp == 0x01:
            _recv_exact(sock, 4 + 2)
        elif atyp == 0x03:
            length = _recv_exact(sock, 1)[0]
            _recv_exact(sock, length + 2)
        elif atyp == 0x04:
            _recv_exact(sock, 16 + 2)

        return sock
    except Exception:
        sock.close()
        raise



FULCRUM_DEFAULT_PORT = 50002
FULCRUM_CONNECT_TIMEOUT = 8
FULCRUM_ONION_TIMEOUT = 30
#: Bei Tor/großen Tx-Antworten: nach Timeout neu verbinden und erneut fragen.
FULCRUM_REQUEST_RETRIES = 3
TOR_PROXY_CHECK_TIMEOUT = 2
TOR_BROWSER_SOCKS_HOST = "127.0.0.1"
TOR_BROWSER_SOCKS_PORT = 9150
TOR_EXPERT_SOCKS_PORT = 9050
TOR_BROWSER_DOWNLOAD = "https://www.torproject.org/download/"
CLIENT_NAME = "SatSage"
PROTOCOL_VERSION = "1.4"
_LISTUNSPENT_METHOD = "blockchain.scripthash.listunspent"
_PROBE_SCRIPT_HASH = "0" * 64


def _is_unknown_method_error(exc: BaseException, method: str) -> bool:
    msg = str(exc).lower()
    return "unknown method" in msg and method.lower() in msg


def supports_listunspent(client: FulcrumClient) -> bool:
    """Prüft, ob der Server blockchain.scripthash.listunspent unterstützt."""
    try:
        client.request(_LISTUNSPENT_METHOD, [_PROBE_SCRIPT_HASH])
        return True
    except RuntimeError as exc:
        if _is_unknown_method_error(exc, _LISTUNSPENT_METHOD):
            return False
        raise


def socks_proxy_reachable(
    proxy_host: str,
    proxy_port: int,
    timeout: int = TOR_PROXY_CHECK_TIMEOUT,
) -> bool:
    try:
        sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def resolve_tor_proxy(
    configured_host: str = TOR_BROWSER_SOCKS_HOST,
    configured_port: int = TOR_EXPERT_SOCKS_PORT,
) -> tuple[str, int] | None:
    """SOCKS-Proxy: konfigurierter Wert zuerst, dann Browser (9150) / Dienst (9050)."""
    from core.tor import erkenne_tor_socks

    return erkenne_tor_socks((configured_host, configured_port))


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

    @staticmethod
    def _outbound_values() -> dict[str, str] | None:
        """`.env` für Outbound-Allowlist (OEFFENTLICHE_ELECTRUM u. a.)."""
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

        buf = b""
        while not buf.endswith(b"\n"):
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Fulcrum-Verbindung geschlossen")
            buf += chunk

        response = json.loads(buf.decode("utf-8"))
        if response.get("error"):
            err = response["error"]
            if isinstance(err, dict):
                raise RuntimeError(err.get("message", err))
            raise RuntimeError(str(err))
        return response.get("result")

    def request(self, method: str, params: list | None = None) -> Any:
        """
        JSON-RPC-Aufruf. Bei Timeout/Abbrecher (typisch Tor + große Tx)
        bis ``FULCRUM_REQUEST_RETRIES`` neu verbinden und wiederholen.
        """
        letzter: BaseException | None = None
        with self._lock:
            for versuch in range(1, FULCRUM_REQUEST_RETRIES + 1):
                try:
                    return self._request_once(method, params)
                except (TimeoutError, socket.timeout, ConnectionError, BrokenPipeError, OSError) as exc:
                    letzter = exc
                    if versuch >= FULCRUM_REQUEST_RETRIES:
                        break
                    self.close()
                    try:
                        self.connect()
                    except Exception as reconnect_exc:
                        letzter = reconnect_exc
                        continue
            assert letzter is not None
            raise TimeoutError(
                f"Fulcrum {method} nach {FULCRUM_REQUEST_RETRIES} Versuchen "
                f"fehlgeschlagen ({letzter})"
            ) from letzter


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
        client.request("server.version", [CLIENT_NAME, PROTOCOL_VERSION])
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


def address_has_received_fulcrum(client: FulcrumClient, address: str) -> bool:
    """True, wenn die Adresse je eine On-Chain-Transaktion hatte."""
    sh = address_to_scripthash(address)
    history = client.request("blockchain.scripthash.get_history", [sh])
    return bool(history)


def first_seen_height_fulcrum(
    client: FulcrumClient,
    addresses,
    *,
    on_progress=None,
) -> int | None:
    """
    Blockhöhe der ältesten Transaktion über alle genannten Adressen.

    Das ist das Alter eines Wallets. Der UTXO-Cache taugt dafür nicht: Er kennt
    nur Unverbrauchtes, und ein Wallet von 2019, das zwischendurch geleert und
    später neu befüllt wurde, sähe dort jung aus. Die Historie kennt dagegen
    auch längst ausgegebene Eingänge.

    Unbestätigte Transaktionen melden Höhe 0 oder −1 und werden übergangen —
    als „ältestes" gewertet ergäben sie ein Wallet-Alter von heute.

    Eine Adresse, die sich nicht abfragen lässt, wird übersprungen statt das
    ganze Ergebnis zu verwerfen: Ein Datum aus den übrigen ist mehr wert als
    gar keines.
    """
    liste = list(addresses)
    gesamt = len(liste)
    aeltester: int | None = None
    for nummer, address in enumerate(liste, start=1):
        try:
            sh = address_to_scripthash(address)
            history = client.request(
                "blockchain.scripthash.get_history", [sh]
            ) or []
        except Exception:
            history = []
        for eintrag in history:
            try:
                hoehe = int(eintrag.get("height", 0))
            except (TypeError, ValueError):
                continue
            if hoehe <= 0:
                continue
            if aeltester is None or hoehe < aeltester:
                aeltester = hoehe
        if on_progress and (nummer == 1 or nummer == gesamt or nummer % 10 == 0):
            on_progress(f"Wallet-Alter: Adresse {nummer} von {gesamt}…")
    return aeltester


def first_seen_fulcrum(
    client: FulcrumClient,
    addresses,
    *,
    on_progress=None,
) -> dict | None:
    """
    Wann ein Wallet zum ersten Mal benutzt wurde — Höhe und Blockzeit.

    Liefert ``{"height": …, "time_ts": …}`` oder None, wenn keine der Adressen
    je eine bestätigte Transaktion hatte.

    Bleibt die Blockzeit unauflösbar, wird die Höhe trotzdem gemeldet: Sie ist
    der eigentliche Befund, die Zeit nur ihre Übersetzung.
    """
    hoehe = first_seen_height_fulcrum(
        client, addresses, on_progress=on_progress
    )
    if hoehe is None:
        return None
    return {"height": hoehe, "time_ts": _block_time_for_height(client, hoehe)}


def collect_used_chain_indices_fulcrum(
    client: FulcrumClient,
    xpub: str,
    change: int,
    max_index: int,
    gap_limit: int,
    derive_address_at_index,
    *,
    start_index: int = 0,
    on_progress=None,
    on_utxos_update=None,
    kette: str = "",
) -> tuple[set[int], int]:
    """
    Ermittelt benutzte Indizes einer Chain (change=0/1) per get_history
    mit Gap-Limit-Abbruch. Rückgabe: (used_indices, next_index).

    *on_utxos_update* erhält nach jedem Fund die bisher gefundenen UTXOs
    dieser Chain (voller Zwischenstand), damit die GUI schon während des
    Gap-Scans zeichnen kann.
    """
    from display import is_list_abort_requested

    used: set[int] = set()
    gap = 0
    next_index = start_index
    bisher = 0
    gefunden: list[dict] = []
    for i in range(start_index, max_index):
        if is_list_abort_requested():
            break
        next_index = i + 1
        roh = derive_address_at_index(xpub, change, i)
        # Eine Adresse (alt) oder alle Skript-Varianten (xpub+auto).
        if isinstance(roh, (list, tuple, set)):
            adressen = [a for a in roh if a]
        elif roh:
            adressen = [roh]
        else:
            adressen = []
        if not adressen:
            break
        utxo_zahl = 0
        getroffen = False
        for address in adressen:
            if not address_has_received_fulcrum(client, address):
                continue
            getroffen = True
            # Anzahl jetzt, nicht erst im späteren listunspent-Lauf —
            # die History sagt nur „je benutzt“, nicht wie viel noch liegt.
            try:
                addr_utxos = fetch_address_utxos_fulcrum(client, address)
                for utxo in addr_utxos:
                    utxo["address"] = address
                gefunden.extend(addr_utxos)
                utxo_zahl += len(addr_utxos)
            except Exception:
                pass
        if getroffen:
            used.add(i)
            gap = 0
            bisher += utxo_zahl
            if on_utxos_update and utxo_zahl > 0:
                on_utxos_update(list(gefunden))
        else:
            gap += 1
            if gap >= gap_limit:
                break
        if on_progress:
            name = f"{kette} " if kette else ""
            wort = "UTXO" if bisher == 1 else "UTXOs"
            if utxo_zahl > 0:
                hier = "UTXO" if utxo_zahl == 1 else "UTXOs"
                text = (
                    f"Gap-Scan {name}Index #{i} — darin {utxo_zahl} {hier} "
                    f"gefunden · bisher {bisher} {wort}"
                )
            else:
                # Nicht „0 gefunden“: das würde den letzten Treffer in der
                # Statuszeile überschreiben und widerspräche dem Log.
                text = f"Gap-Scan {name}Index #{i} · bisher {bisher} {wort}"
            try:
                on_progress(text, sofort=utxo_zahl > 0)
            except TypeError:
                on_progress(text)
    return used, next_index


def collect_used_receive_indices_fulcrum(
    client: FulcrumClient,
    xpub: str,
    max_index: int,
    gap_limit: int,
    derive_receive_address_at_index,
) -> set[int]:
    """
    Ermittelt benutzte Empfangs-Indizes per get_history mit Gap-Limit-Abbruch.
    """
    print("  Finde freie Adresse...", end="", flush=True)
    try:
        used, _next_index = collect_used_chain_indices_fulcrum(
            client,
            xpub,
            0,
            max_index,
            gap_limit,
            lambda xp, _change, index: (
                derive_receive_address_at_index(xp, index)[0]
                if derive_receive_address_at_index(xp, index)
                else None
            ),
        )
        print("." * min(len(used), 20), end="", flush=True)
    finally:
        print(flush=True)
    return used


def _utxos_from_listunspent_entries(
    client: FulcrumClient,
    entries: list[dict],
) -> list[dict]:
    utxos: list[dict] = []
    for entry in entries:
        height = int(entry.get("height", 0))
        status: dict[str, object] = {"confirmed": height > 0}
        if height > 0:
            status["block_height"] = height
            block_time = _block_time_for_height(client, height)
            if block_time is not None:
                status["block_time"] = block_time
        utxos.append({
            "txid": entry["tx_hash"],
            "vout": entry["tx_pos"],
            "value": int(entry["value"]),
            "status": status,
        })
    return utxos


def fetch_address_utxos_fulcrum(client: FulcrumClient, address: str) -> list[dict]:
    """Unspent UTXOs einer Adresse (listunspent, Fallback: Tx-Historie)."""
    sh = address_to_scripthash(address)
    try:
        entries = client.request(_LISTUNSPENT_METHOD, [sh]) or []
    except RuntimeError as exc:
        if _is_unknown_method_error(exc, _LISTUNSPENT_METHOD):
            return _fetch_address_utxos_from_history(client, address, sh)
        raise
    return _utxos_from_listunspent_entries(client, entries)


def _spender_map_fuer_outpoints(
    client: FulcrumClient,
    address: str,
    outpoints: set[tuple[str, int]],
) -> dict[tuple[str, int], dict]:
    """
    Findet ausgebende Tx zu bekannten Outpoints über get_history.

    Liefert ``(txid, vout) → {txid, height, pending}``. Nur die History-Einträge
    der einen Adresse — kein Wallet-weiter Scan.
    """
    if not outpoints:
        return {}
    try:
        sh = address_to_scripthash(address)
        history = client.request(
            "blockchain.scripthash.get_history", [sh],
        ) or []
    except Exception:
        return {}

    # Neueste zuerst — Mempool und frische Bestätigungen früh finden.
    def _hoehe(entry: dict) -> int:
        try:
            return int(entry.get("height") or 0)
        except (TypeError, ValueError):
            return 0

    history_sorted = sorted(history, key=_hoehe)
    gefunden: dict[tuple[str, int], dict] = {}
    offen = set(outpoints)

    for entry in reversed(history_sorted):
        if not offen:
            break
        height = _hoehe(entry)
        spend_txid = str(entry.get("tx_hash") or "").strip()
        if not spend_txid:
            continue
        try:
            tx = fetch_tx_fulcrum(
                client, spend_txid, enrich_block_info=(height > 0),
            )
        except Exception:
            continue
        for vin in tx.get("vin") or []:
            if vin.get("is_coinbase"):
                continue
            prev = str(vin.get("txid") or "").lower()
            if not prev:
                continue
            try:
                prev_vout = int(vin.get("vout", 0))
            except (TypeError, ValueError):
                continue
            key = (prev, prev_vout)
            if key not in offen:
                continue
            status = tx.get("status") or {}
            time_ts = status.get("block_time")
            if time_ts is None and height > 0:
                time_ts = _block_time_for_height(client, height)
            gefunden[key] = {
                "txid": spend_txid.lower(),
                "height": height,
                "pending": height <= 0,
                "time_ts": int(time_ts) if time_ts else None,
            }
            offen.discard(key)
    return gefunden


def finde_mempool_spends_utxos(
    client: FulcrumClient,
    utxos: list[dict],
) -> list[dict]:
    """Nur unconfirmed Spends — Kompatibilität; siehe ``klassifiziere_utxo_spends``."""
    pending, _confirmed, _live = klassifiziere_utxo_spends(client, utxos)
    return pending


def klassifiziere_utxo_spends(
    client: FulcrumClient,
    utxos: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Gezielter Electrs-Check für Cache-UTXOs (eigener Node).

    Rückgabe ``(pending, confirmed_spent, live_auf_betroffenen_adressen)``:

    * **pending** — Mempool-Ausgabe (height ≤ 0)
    * **confirmed_spent** — bestätigte Ausgabe (height > 0), zum Cache-Settle
    * **live_…** — aktuelles ``listunspent`` der betroffenen Adressen
      (inkl. Change), mit ``address`` gesetzt

    Nur Adressen der übergebenen UTXOs — kein Gap, kein Fullscan.
    """
    if not utxos:
        return [], [], []

    nach_addr: dict[str, list[dict]] = {}
    for utxo in utxos:
        addr = (utxo.get("address") or "").strip()
        if not addr:
            continue
        nach_addr.setdefault(addr, []).append(utxo)

    pending: list[dict] = []
    confirmed: list[dict] = []
    live_all: list[dict] = []

    for address, gruppe in nach_addr.items():
        try:
            live = fetch_address_utxos_fulcrum(client, address)
        except Exception:
            continue
        for u in live:
            neu = dict(u)
            neu["address"] = address
            live_all.append(neu)
        live_keys = {
            f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
            for u in live
        }

        fehlt: list[dict] = []
        outpoints: set[tuple[str, int]] = set()
        for utxo in gruppe:
            txid = str(utxo.get("txid") or "").lower()
            try:
                vout = int(utxo.get("vout") or 0)
            except (TypeError, ValueError):
                continue
            if f"{txid}:{vout}" in live_keys:
                continue
            fehlt.append(utxo)
            outpoints.add((txid, vout))

        if not fehlt:
            continue

        spender = _spender_map_fuer_outpoints(client, address, outpoints)
        for utxo in fehlt:
            txid = str(utxo.get("txid") or "").lower()
            try:
                vout = int(utxo.get("vout") or 0)
            except (TypeError, ValueError):
                continue
            info = spender.get((txid, vout))
            if not info:
                continue
            eintrag = dict(utxo)
            eintrag["txid"] = txid
            eintrag["vout"] = vout
            eintrag["address"] = address
            eintrag["spent"] = True
            eintrag["spent_txid"] = info["txid"]
            eintrag["spent_height"] = int(info.get("height") or 0)
            eintrag["spent_time_ts"] = info.get("time_ts")
            if info.get("pending"):
                eintrag["spent_pending"] = True
                pending.append(eintrag)
            else:
                eintrag["spent_pending"] = False
                status = eintrag.setdefault("status", {})
                if eintrag["spent_height"] > 0:
                    status["block_height"] = eintrag["spent_height"]
                    status["confirmed"] = True
                if eintrag.get("spent_time_ts"):
                    status["block_time"] = eintrag["spent_time_ts"]
                confirmed.append(eintrag)

    return pending, confirmed, live_all


def eigene_mempool_empfaenge(
    client: FulcrumClient,
    pending_spends: list[dict],
    *,
    is_own_address,
) -> list[dict]:
    """
    Eigene Empfangs-Outputs aus Mempool-Spend-Txs (Selbstüberweisung / Change).

    ``is_own_address(addr) -> bool`` — typisch ``WalletContext.is_own_address``
    (erweiterte Index-Suche, damit Change jenseits der Gap-Limit gefunden wird).
    """
    if not pending_spends or not callable(is_own_address):
        return []

    txids: list[str] = []
    gesehen: set[str] = set()
    for p in pending_spends:
        tid = str(p.get("spent_txid") or "").strip().lower()
        if not tid or tid in gesehen:
            continue
        gesehen.add(tid)
        txids.append(tid)

    empfangen: list[dict] = []
    out_keys: set[str] = set()
    for tid in txids:
        try:
            tx = fetch_tx_fulcrum(client, tid, enrich_block_info=False)
        except Exception:
            continue
        for vout_idx, vout in enumerate(tx.get("vout") or []):
            own_addr = None
            for addr in _vout_addresses(vout):
                try:
                    if is_own_address(addr):
                        own_addr = addr
                        break
                except Exception:
                    continue
            if not own_addr:
                continue
            key = f"{tid}:{int(vout_idx)}"
            if key in out_keys:
                continue
            out_keys.add(key)
            empfangen.append({
                "txid": tid,
                "vout": int(vout_idx),
                "value": _vout_value_sats(vout),
                "address": own_addr,
                "status": {"confirmed": False},
                "receive_pending": True,
            })
    return empfangen


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


def fetch_wallet_utxos_fulcrum(
    client: FulcrumClient,
    addresses: set[str],
    *,
    pool=None,
    on_progress=None,
    on_utxos_update=None,
) -> list[dict]:
    """
    Lädt unspent UTXOs für alle Wallet-Adressen.

    Mit *pool* laufen die Adressen parallel über mehrere Verbindungen — bei
    einigen hundert Adressen ist das der Unterschied zwischen Minuten und
    Sekunden. Ohne Pool bleibt es beim sequenziellen Weg über die eine
    Verbindung; die Ergebnisse sind in beiden Fällen dieselben.

    *on_utxos_update* erhält den bisherigen Fund-Zwischenstand (voller
    Snapshot), sobald neue UTXOs dazukommen — parallel nur nach jedem
    abgeschlossenen Adress-Batch im Fortschrittstakt.
    """
    from display import is_list_abort_requested

    addr_list = sorted(addresses)
    total = len(addr_list)
    stand: list[dict] = []
    stand_lock = threading.Lock()

    def melde(done: int, gesamt: int) -> None:
        if done % 25 == 0 or done == gesamt:
            print(f"  Fulcrum Adressen {done}/{gesamt}...", flush=True)
        if on_progress:
            on_progress(f"Prüfe Adresse {done} von {gesamt}…")

    def melde_stand(neu: list[dict]) -> None:
        if not on_utxos_update or not neu:
            return
        with stand_lock:
            stand.extend(neu)
            snapshot = list(stand)
        on_utxos_update(snapshot)

    if pool is not None and len(pool) > 1 and total > 1:
        def hole(verbindung, adresse: str) -> list[dict]:
            return [
                dict(utxo, address=adresse)
                for utxo in fetch_address_utxos_fulcrum(verbindung, adresse)
            ]

        def fortschritt(done: int, gesamt: int) -> None:
            melde(done, gesamt)

        gefunden = parallel_ueber_pool(
            pool, addr_list, hole, fortschritt=fortschritt,
        )
        utxos = [utxo for teil in gefunden if teil for utxo in teil]
        if on_utxos_update and utxos:
            on_utxos_update(utxos)
        return utxos

    utxos: list[dict] = []
    for done, address in enumerate(addr_list, start=1):
        if is_list_abort_requested():
            return utxos
        neu: list[dict] = []
        for utxo in fetch_address_utxos_fulcrum(client, address):
            utxo["address"] = address
            utxos.append(utxo)
            neu.append(utxo)
        if neu:
            melde_stand(neu)
        melde(done, total)
    return utxos






_HEADER_TIME_CACHE: dict[int, int] = {}
_TX_HEIGHT_CACHE: dict[str, int | None] = {}


def _timestamp_from_block_header(header_hex: str) -> int:
    raw = bytes.fromhex(header_hex)
    if len(raw) < 80:
        raise ValueError("Block-Header zu kurz")
    return int.from_bytes(raw[68:72], "little")


def _vout_addresses(vout: dict) -> list[str]:
    spk = vout.get("scriptPubKey", {})
    addrs: list[str] = []
    if spk.get("address"):
        addrs.append(str(spk["address"]))
    addrs.extend(str(addr) for addr in spk.get("addresses", []) if addr)
    return addrs


def _vout_matches_address(vout: dict, address: str) -> bool:
    """
    True, wenn der Output an ``address`` zahlt.

    Electrs/Core auf Regtest liefern ``bcrt1…``, SatSage leitet ohne
    Chain-Schalter oft ``bc1…`` ab — gleicher scriptPubKey, anderer HRP.
    String-Vergleich allein würde Treffer still verwerfen; Hex-Vergleich
    der scriptPubKey fängt die Varianten (main/test/regtest) ab.
    """
    if address in _vout_addresses(vout):
        return True
    spk = vout.get("scriptPubKey") or {}
    hex_spk = str(spk.get("hex") or "").strip().lower()
    if not hex_spk:
        return False
    try:
        want = address_to_scriptpubkey(address).data.hex().lower()
    except Exception:
        return False
    return hex_spk == want


def _lookup_tx_height(client: FulcrumClient, txid: str, vouts: list[dict]) -> int | None:
    cached = _TX_HEIGHT_CACHE.get(txid.lower())
    if cached is not None or txid.lower() in _TX_HEIGHT_CACHE:
        return cached

    txid_l = txid.lower()
    seen_addrs: set[str] = set()
    height: int | None = None

    for vout in vouts:
        for addr in _vout_addresses(vout):
            if addr in seen_addrs:
                continue
            seen_addrs.add(addr)
            try:
                sh = address_to_scripthash(addr)
                history = client.request("blockchain.scripthash.get_history", [sh]) or []
            except Exception:
                continue
            for entry in history:
                if str(entry.get("tx_hash", "")).lower() == txid_l:
                    height = int(entry.get("height", 0))
                    break
            if height is not None:
                break

    _TX_HEIGHT_CACHE[txid.lower()] = height
    return height


def _fetch_block_header_hex(client, height: int) -> str | None:
    for attempt in range(2):
        try:
            header = client.request("blockchain.block.header", [height])
            if isinstance(header, dict):
                header = header.get("header") or header.get("hex") or ""
            if isinstance(header, str) and header:
                return header
            return None
        except (ConnectionError, BrokenPipeError, OSError, RuntimeError):
            if attempt == 0 and hasattr(client, "close") and hasattr(client, "connect"):
                try:
                    client.close()
                    client.connect()
                except Exception:
                    pass
                continue
            return None
    return None


def _block_time_for_height(client: FulcrumClient, height: int) -> int | None:
    if height <= 0:
        return None
    if height in _HEADER_TIME_CACHE:
        return _HEADER_TIME_CACHE[height]
    try:
        from main import IMMUTABLE_CACHE_DIR, load_cached_block_time, save_cached_block_time

        disk_time = load_cached_block_time(height, IMMUTABLE_CACHE_DIR)
        if disk_time is not None:
            _HEADER_TIME_CACHE[height] = disk_time
            return disk_time
    except Exception:
        pass
    header = _fetch_block_header_hex(client, height)
    if not header:
        return None
    try:
        blocktime = _timestamp_from_block_header(header)
    except ValueError:
        return None
    _HEADER_TIME_CACHE[height] = blocktime
    try:
        from main import IMMUTABLE_CACHE_DIR, save_cached_block_time

        save_cached_block_time(height, blocktime, IMMUTABLE_CACHE_DIR, "fulcrum")
    except Exception:
        pass
    return blocktime


def _enrich_tx_block_info(client: FulcrumClient, tx: dict) -> dict:
    """Ergänzt Hex-geparste Txs um Blockhöhe und Blockzeit."""
    if _tx_block_time_from_dict(tx) is not None:
        return tx

    txid = str(tx.get("txid", ""))
    if not txid:
        return tx

    height = _lookup_tx_height(client, txid, tx.get("vout", []))
    if height is None:
        return tx

    tx["blockheight"] = height
    if height <= 0:
        tx["confirmations"] = 0
        tx["status"] = {"confirmed": False, "block_height": 0}
        return tx

    blocktime = _block_time_for_height(client, height)
    if blocktime is not None:
        tx["blocktime"] = blocktime
    tx["confirmations"] = max(int(tx.get("confirmations", 0)), 1)
    tx["status"] = {
        "confirmed": True,
        "block_height": height,
        "block_time": blocktime,
    }
    return tx


def _tx_block_time_from_dict(tx: dict) -> int | None:
    status = tx.get("status", {})
    if status.get("block_time"):
        return int(status["block_time"])
    if tx.get("blocktime"):
        return int(tx["blocktime"])
    if tx.get("time"):
        return int(tx["time"])
    return None

_VERBOSE_TX_UNSUPPORTED = "verbose transactions are currently unsupported"


def _verbose_tx_unsupported(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "verbose" in msg and "unsupported" in msg


def _script_pubkey_to_dict(script: Script) -> dict:
    spk: dict[str, object] = {"hex": script.data.hex()}
    script_type = script.script_type()
    if script_type:
        spk["type"] = script_type
    try:
        spk["address"] = script.address()
    except ValueError:
        pass
    return spk


def _vin_to_dict(inp) -> dict:
    if inp.txid == b"\x00" * 32:
        coinbase = inp.script_sig.data.hex() if inp.script_sig else ""
        return {
            "is_coinbase": True,
            "coinbase": coinbase or "00",
            "sequence": inp.sequence,
        }
    return {
        "txid": inp.txid[::-1].hex(),
        "vout": inp.vout,
        "sequence": inp.sequence,
    }


def _parse_tx_hex(raw_hex: str, expected_txid: str | None = None) -> dict:
    """Parst Roh-Hex lokal (Fallback wenn verbose am Server fehlt)."""
    raw = raw_hex.strip()
    if not raw:
        raise ValueError("leere Transaktion")

    tx = Transaction.from_string(raw)
    txid = tx.txid().hex()
    if expected_txid and txid.lower() != expected_txid.lower():
        raise ValueError(
            f"Txid stimmt nicht: erwartet {expected_txid}, erhalten {txid}"
        )

    return {
        "txid": txid,
        "version": tx.version,
        "locktime": tx.locktime,
        "vin": [_vin_to_dict(inp) for inp in tx.vin],
        "vout": [
            {
                "n": index,
                "value": out.value / 1e8,
                "scriptPubKey": _script_pubkey_to_dict(out.script_pubkey),
            }
            for index, out in enumerate(tx.vout)
        ],
        "confirmations": 0,
        "hex": raw,
    }

def _normalize_electrum_tx(tx: dict) -> dict:
    """Bringt Electrum-Tx in ein für analyze.py nutzbares Format."""
    if not tx:
        return tx

    for vin in tx.get("vin", []):
        if "coinbase" in vin and "is_coinbase" not in vin:
            vin["is_coinbase"] = True
        if "txid" not in vin and "tx_hash" in vin:
            vin["txid"] = vin["tx_hash"]

    confirmations = int(tx.get("confirmations", 0))
    confirmed = confirmations > 0
    block_time = tx.get("blocktime") or tx.get("time")
    if block_time and "status" not in tx:
        tx["status"] = {
            "confirmed": confirmed,
            "block_time": block_time,
        }

    return tx


def fetch_tx_fulcrum(
    client: FulcrumClient,
    txid: str,
    *,
    enrich_block_info: bool = True,
) -> dict:
    """Lädt eine Tx; bei fehlendem verbose-Modus Fallback auf Hex-Parsing."""
    try:
        tx = client.request("blockchain.transaction.get", [txid, True])
        if isinstance(tx, str):
            raise RuntimeError(_VERBOSE_TX_UNSUPPORTED)
        return _normalize_electrum_tx(tx)
    except RuntimeError as exc:
        if not _verbose_tx_unsupported(exc):
            raise
        raw_hex = client.request("blockchain.transaction.get", [txid, False])
        if not isinstance(raw_hex, str):
            raise RuntimeError("Unerwartete Antwort bei Roh-Transaktion") from exc
        tx = _normalize_electrum_tx(_parse_tx_hex(raw_hex, expected_txid=txid))
        if enrich_block_info:
            return _enrich_tx_block_info(client, tx)
        return tx


def _vout_value_sats(vout: dict) -> int:
    value = vout.get("value", 0)
    if isinstance(value, float):
        return int(round(value * 1e8))
    return int(value)


def _walk_address_history(
    client: FulcrumClient,
    address: str,
    scripthash: str,
    *,
    on_step=None,
) -> tuple[dict[tuple[str, int], dict[str, int]], dict[tuple[str, int], str]]:
    """
    Geht die Historie einer Adresse durch.

    Liefert *(received, spent_by)*: alle je auf dieser Adresse empfangenen
    Outputs, und zu jedem verbrauchten die TxID, die ihn ausgegeben hat.

    Gemeinsame Grundlage für zwei Sichten — die unverbrauchte Teilmenge
    (UTXO-Fallback für Server ohne listunspent) und den vollständigen Verlauf.
    Beide aus einem Walk, damit sie sich nicht widersprechen können.

    *on_step(text)*: Zwischenstand (get_history / Tx i/n) für lange Tor-Läufe.
    """
    if on_step:
        try:
            on_step("get_history…")
        except Exception:
            pass
    history = client.request("blockchain.scripthash.get_history", [scripthash]) or []
    if not history:
        return {}, {}

    received: dict[tuple[str, int], dict[str, int]] = {}
    spent_by: dict[tuple[str, int], dict] = {}
    anzahl = len(history)

    for index, entry in enumerate(history, start=1):
        if on_step:
            try:
                on_step(f"Tx {index}/{anzahl}")
            except Exception:
                pass
        txid = str(entry["tx_hash"])
        height = int(entry.get("height", 0))
        tx = fetch_tx_fulcrum(client, txid)
        txid_key = txid.lower()

        for vout_idx, vout in enumerate(tx.get("vout", [])):
            if not _vout_matches_address(vout, address):
                continue
            received[(txid_key, vout_idx)] = {
                "value": _vout_value_sats(vout),
                "height": height,
            }

        for vin in tx.get("vin", []):
            if vin.get("is_coinbase"):
                continue
            prev_txid = str(vin.get("txid", "")).lower()
            if prev_txid:
                # Die Höhe der ausgebenden Tx gleich mitnehmen: Sie steht hier
                # ohnehin zur Verfügung, und ohne sie ließe sich später nicht
                # sagen, in welchem Steuerjahr der Abgang lag.
                spent_by[(prev_txid, int(vin.get("vout", 0)))] = {
                    "txid": txid_key,
                    "height": height,
                }

    return received, spent_by


def _status_fuer_hoehe(client: FulcrumClient, height: int) -> dict:
    """Bestätigungs-Status eines Outputs; Blockzeit nur bei bestätigter Höhe."""
    status: dict[str, object] = {"confirmed": height > 0}
    if height > 0:
        status["block_height"] = height
        block_time = _block_time_for_height(client, height)
        if block_time is not None:
            status["block_time"] = block_time
    return status


def fetch_address_history_fulcrum(
    client: FulcrumClient,
    address: str,
    scripthash: str,
    *,
    on_step=None,
) -> list[dict]:
    """
    Alle je auf einer Adresse empfangenen Outputs — auch längst ausgegebene.

    Der UTXO-Cache kennt nur Unverbrauchtes und taugt für zurückliegende
    Steuerjahre deshalb nicht: Was 2023 empfangen und 2024 ausgegeben wurde,
    steht dort nicht mehr. Hier steht es, mit ``spent`` und ``spent_txid``.
    """
    received, spent_by = _walk_address_history(
        client, address, scripthash, on_step=on_step,
    )

    eintraege: list[dict] = []
    n_rec = len(received)
    for index, ((txid_key, vout_idx), info) in enumerate(received.items(), start=1):
        if on_step and n_rec:
            try:
                on_step(f"Zeiten {index}/{n_rec}")
            except Exception:
                pass
        abgang = spent_by.get((txid_key, vout_idx))
        eintrag = {
            "txid": txid_key,
            "vout": vout_idx,
            "value": info["value"],
            "status": _status_fuer_hoehe(client, info["height"]),
            "spent": abgang is not None,
            "spent_txid": abgang["txid"] if abgang else None,
        }
        if abgang and abgang["height"] > 0:
            eintrag["spent_height"] = abgang["height"]
            abgangszeit = _block_time_for_height(client, abgang["height"])
            if abgangszeit is not None:
                eintrag["spent_time_ts"] = abgangszeit
        eintraege.append(eintrag)
    return eintraege


def _verlauf_fortschritt(
    rest: int,
    gesamt: int,
    bisher: int,
    *,
    adresse_nr: int | None = None,
    detail: str = "",
) -> str:
    """Statuszeile: Restadressen zuerst, dann schon erfasste Einträge."""
    wort = "Eintrag" if bisher == 1 else "Einträge"
    text = (
        f"Frage Verlauf für {gesamt} Adressen — noch {rest} von {gesamt} Adressen"
        f" · bisher {bisher} {wort}"
    )
    if adresse_nr is not None:
        text += f" · Adresse {adresse_nr}/{gesamt}"
    if detail:
        text += f" · {detail}"
    return text


def fetch_wallet_history_fulcrum(
    client: FulcrumClient,
    addresses,
    *,
    on_progress=None,
    skip_addresses=None,
    on_address_done=None,
    seed_eintraege=None,
) -> list[dict]:
    """
    Verlauf über alle Adressen eines Wallets, je Eintrag mit ``address``.

    Ohne die Adresse ließe sich später nicht mehr sagen, zu welchem Wallet ein
    Eintrag gehört — dieselbe Zuordnung, die der UTXO-Scan mitführt.

    *skip_addresses*: bereits erledigte Adressen (Resume nach Abbruch).
    *on_address_done(address, neue_eintraege)*: nach jeder Adresse — zum
    Zwischenstand speichern.
    *seed_eintraege*: bereits bekannte Einträge (zählen für die Fortschrittszeile).
    """
    from display import is_list_abort_requested

    eintraege: list[dict] = list(seed_eintraege or [])
    skip = set(skip_addresses or [])
    adressliste = sorted(addresses)
    offen = [a for a in adressliste if a not in skip]
    gesamt = len(adressliste)
    erledigt_basis = gesamt - len(offen)

    def _melde(
        rest_offen: int,
        *,
        sofort: bool = False,
        adresse_nr: int | None = None,
        detail: str = "",
    ) -> None:
        if not on_progress:
            return
        text = _verlauf_fortschritt(
            rest_offen, gesamt, len(eintraege),
            adresse_nr=adresse_nr, detail=detail,
        )
        try:
            on_progress(text, sofort=sofort)
        except TypeError:
            on_progress(text)

    if erledigt_basis and on_progress:
        _melde(len(offen), sofort=True)

    for nummer, address in enumerate(offen, start=1):
        if is_list_abort_requested():
            return eintraege
        rest = len(offen) - nummer + 1
        adresse_nr = erledigt_basis + nummer
        # Erste Adresse / jede 5.: sofort ins Log — sonst nur „Moment noch“,
        # während Tor an get_history oder den Tx-Downloads hängt.
        _melde(
            rest,
            sofort=(nummer == 1 or nummer % 5 == 1),
            adresse_nr=adresse_nr,
            detail="get_history…",
        )
        neu: list[dict] = []
        try:
            scripthash = address_to_scripthash(address)
        except Exception:
            if on_address_done:
                on_address_done(address, [])
            continue

        def _schritt(detail: str, *, _rest=rest, _nr=adresse_nr) -> None:
            # Text ändert sich (Tx 3/12…) → tick schreibt nach ~10s Stille.
            _melde(_rest, sofort=False, adresse_nr=_nr, detail=detail)

        for eintrag in fetch_address_history_fulcrum(
            client, address, scripthash, on_step=_schritt,
        ):
            eintrag["address"] = address
            neu.append(eintrag)
            eintraege.append(eintrag)
        if on_address_done:
            on_address_done(address, neu)
        # Nach Adresse: Rest zählt runter (tick, nicht jede Adresse phase).
        _melde(
            max(0, rest - 1),
            sofort=(nummer % 5 == 0 or nummer == len(offen)),
            adresse_nr=adresse_nr,
        )
        if on_progress is None and (
            (erledigt_basis + nummer) % 25 == 0 or nummer == len(offen)
        ):
            print(
                f"  Fulcrum Verlauf {erledigt_basis + nummer}/{gesamt}...",
                flush=True,
            )
    if gesamt:
        _melde(0, sofort=True)
    return eintraege


def _fetch_address_utxos_from_history(
    client: FulcrumClient,
    address: str,
    scripthash: str,
) -> list[dict]:
    """
    Leitet unspent UTXOs aus get_history + Transaktionsdaten ab.

    Fallback für Server ohne ``listunspent``. Die Ausgabe bleibt bewusst die
    eines UTXO-Abrufs — ohne die Verlaufsfelder, damit Aufrufer nicht
    versehentlich ausgegebene Outputs mitzählen.
    """
    received, spent_by = _walk_address_history(client, address, scripthash)

    utxos: list[dict] = []
    for (txid_key, vout_idx), info in received.items():
        if (txid_key, vout_idx) in spent_by:
            continue
        utxos.append({
            "txid": txid_key,
            "vout": vout_idx,
            "value": info["value"],
            "status": _status_fuer_hoehe(client, info["height"]),
        })
    return utxos


def _parse_utc_date_timestamp(date_str: str) -> int:
    from datetime import datetime, timezone

    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            continue
    raise ValueError(
        f"Datum nicht erkannt: {date_str!r} (DD.MM.YYYY oder YYYY-MM-DD)"
    )


_TIP_HEIGHT_CACHE: dict[str, int] = {}
_DATE_HEIGHT_CACHE: dict[tuple[str, str], int] = {}
_TIP_SEARCH_CEILING = 1_500_000
SANCTIONS_HISTORY_PROBE_HEIGHT = 500_000


def _fulcrum_client_cache_key(client) -> str:
    host = getattr(client, "host", None)
    if host:
        return str(host)
    return str(id(client))


def _header_exists_at_height(client, height: int) -> bool:
    return _fetch_block_header_hex(client, height) is not None


def supports_historical_headers(
    client,
    probe_height: int = SANCTIONS_HISTORY_PROBE_HEIGHT,
) -> bool:
    """True wenn der Server Block-Header weit in der Vergangenheit liefert."""
    return _header_exists_at_height(client, probe_height)


def _tip_height_via_binary_search(client) -> int:
    lo, hi = 0, _TIP_SEARCH_CEILING
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _header_exists_at_height(client, mid):
            lo = mid
        else:
            hi = mid - 1
    if lo <= 0:
        raise RuntimeError("Chain-Tip über Fulcrum nicht ermittelbar")
    return lo


def get_chain_tip_height(client: FulcrumClient, *, force: bool = False) -> int:
    """Aktuelle Chain-Tip-Höhe (subscribe, sonst Binärsuche auf block.header).

    *force*: Cache ignorieren — nötig für Tip-Nachzug über Stunden, sonst
    bleibt der Prozess auf dem ersten Tip der Session kleben.
    """
    cache_key = _fulcrum_client_cache_key(client)
    if not force:
        cached = _TIP_HEIGHT_CACHE.get(cache_key)
        if cached is not None:
            return cached

    try:
        result = client.request("blockchain.headers.subscribe")
    except Exception:
        result = None

    tip: int | None = None
    if isinstance(result, dict) and result.get("height") is not None:
        tip = int(result["height"])
    elif isinstance(result, list):
        # Manche Server liefern Notifications statt Tip-Dict — nicht vertrauen.
        pass

    if tip is None or not _header_exists_at_height(client, tip):
        tip = _tip_height_via_binary_search(client)

    _TIP_HEIGHT_CACHE[cache_key] = tip
    return tip


def date_to_block_height_fulcrum(client: FulcrumClient, date_str: str) -> int:
    """Erste Blockhöhe am oder nach dem Datum (UTC-Tagesbeginn), via Fulcrum."""
    cache_key = _fulcrum_client_cache_key(client)
    date_key = date_str.strip()
    cached = _DATE_HEIGHT_CACHE.get((cache_key, date_key))
    if cached is not None:
        return cached

    target_ts = _parse_utc_date_timestamp(date_key)
    tip = get_chain_tip_height(client)
    lo, hi = 0, tip
    while lo < hi:
        mid = (lo + hi) // 2
        block_time = _block_time_for_height(client, mid)
        if block_time is None:
            # Geprunter/unvollständiger Server: nur oberhalb von mid weitersuchen.
            lo = mid + 1
            continue
        if block_time < target_ts:
            lo = mid + 1
        else:
            hi = mid
    if lo > tip:
        raise RuntimeError(
            f"Kein Block für Datum {date_key!r} ermittelbar "
            f"(Server ohne Historie ab Höhe {tip:,})"
        )
    _DATE_HEIGHT_CACHE[(cache_key, date_key)] = lo
    return lo