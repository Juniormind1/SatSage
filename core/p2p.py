"""
Bitcoin-P2P für Compact Filter (BIP 157/158).

Kein Core-RPC. Peers mit ``NODE_COMPACT_FILTERS`` liefern Filter und Blöcke.
Adressen verlassen den Rechner nicht — der Peer sieht nur Höhenbereiche und
später Block-Hashes bei Treffern.
"""
from __future__ import annotations

import hashlib
import logging
import random
import socket
import struct
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

logger = logging.getLogger(__name__)

MAINNET_MAGIC = b"\xf9\xbe\xb4\xd9"
PROTOCOL_VERSION = 70016
NODE_NETWORK = 1
NODE_WITNESS = 8
NODE_COMPACT_FILTERS = 64
NODE_NETWORK_LIMITED = 1024
USER_AGENT = "/SatSage:1.0/"
DEFAULT_P2P_PORT = 8333
FILTER_TYPE_BASIC = 0
GETCFILTERS_MAX = 1000
#: Parallel Compact-Filter-Verbindungen beim Scan.
FILTER_PEERS_MAX = 4
#: Unter dieser Zahl wird während des Scans eine Peer-Warnung geloggt.
P2P_SCAN_WARN_PEERS = 3
#: TCP-Stichprobe, ob ausgehendes 8333 generell gedroppt wird (Firewall).
CLEAR_PORT_PROBE_HOSTS = 3
CLEAR_PORT_PROBE_TIMEOUT = 2.5
MSG_WITNESS_BLOCK = 2 | (1 << 30)
MSG_WITNESS_TX = 1 | (1 << 30)

DNS_SEEDS = (
    "seed.bitcoin.sipa.be",
    "dnsseed.bluematt.me",
    "dnsseed.bitcoin.dashjr.org",
    "seed.bitcoin.jonasschnelli.ch",
    "seed.bitcoin.sprovoost.nl",
    "dnsseed.emzy.de",
)

#: SegWit-Aktivierung — darunter gibt es keine nativen SegWit-Outputs.
SEGWIT_HEIGHT = 481_824


def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def header_hash(header: bytes) -> bytes:
    """Internes Hash-Byte-Order (wie auf dem P2P-Draht)."""
    if len(header) < 80:
        raise ValueError("Block-Header zu kurz")
    return double_sha256(header[:80])


def hash_to_hex(internal: bytes) -> str:
    return internal[::-1].hex()


def hex_to_hash(display: str) -> bytes:
    return bytes.fromhex(display)[::-1]


def compact_size(value: int) -> bytes:
    if value < 253:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", value)
    if value <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", value)
    return b"\xff" + struct.pack("<Q", value)


def read_compact_size(data: bytes, offset: int = 0) -> tuple[int, int]:
    first = data[offset]
    if first < 253:
        return first, offset + 1
    if first == 253:
        return struct.unpack_from("<H", data, offset + 1)[0], offset + 3
    if first == 254:
        return struct.unpack_from("<I", data, offset + 1)[0], offset + 5
    return struct.unpack_from("<Q", data, offset + 1)[0], offset + 9


def encode_message(command: str, payload: bytes = b"") -> bytes:
    cmd = command.encode("ascii")
    if len(cmd) > 12:
        raise ValueError(f"P2P-Befehl zu lang: {command}")
    cmd = cmd.ljust(12, b"\x00")
    return (
        MAINNET_MAGIC
        + cmd
        + struct.pack("<I", len(payload))
        + double_sha256(payload)[:4]
        + payload
    )


def decode_header(header: bytes) -> tuple[str, int, bytes]:
    if len(header) != 24:
        raise ValueError("P2P-Kopf muss 24 Byte haben")
    if header[:4] != MAINNET_MAGIC:
        # Oft Desync nach Tor-Abbruch — als Verbindungsfehler behandeln,
        # damit der Scan den Peer wechselt statt komplett zu stoppen.
        raise ConnectionError(
            f"falsches Bitcoin-Netz (Magic={header[:4].hex()})"
        )
    command = header[4:16].rstrip(b"\x00").decode("ascii", errors="replace")
    length = struct.unpack_from("<I", header, 16)[0]
    checksum = header[20:24]
    return command, length, checksum


def _ipv6_mapped(ipv4: str) -> bytes:
    parts = [int(p) for p in ipv4.split(".")]
    return b"\x00" * 10 + b"\xff\xff" + bytes(parts)


def encode_version(
    *,
    services: int = NODE_NETWORK | NODE_WITNESS,
    start_height: int = 0,
    nonce: int | None = None,
    user_agent: str = USER_AGENT,
) -> bytes:
    now = int(time.time())
    nonce = nonce if nonce is not None else random.getrandbits(64)
    ua = user_agent.encode("ascii")
    payload = (
        struct.pack("<i", PROTOCOL_VERSION)
        + struct.pack("<Q", services)
        + struct.pack("<q", now)
        + struct.pack("<Q", 0)
        + b"\x00" * 16
        + struct.pack(">H", 0)
        + struct.pack("<Q", services)
        + b"\x00" * 16
        + struct.pack(">H", 0)
        + struct.pack("<Q", nonce)
        + compact_size(len(ua))
        + ua
        + struct.pack("<i", start_height)
        + b"\x01"
    )
    return payload


def decode_version_services(payload: bytes) -> tuple[int, int, int]:
    """version, services, start_height."""
    if len(payload) < 4 + 8 + 8:
        raise ValueError("version-Nachricht zu kurz")
    version = struct.unpack_from("<i", payload, 0)[0]
    services = struct.unpack_from("<Q", payload, 4)[0]
    offset = 4 + 8 + 8 + 26 + 26 + 8
    ua_len, offset = read_compact_size(payload, offset)
    offset += ua_len
    start_height = 0
    if offset + 4 <= len(payload):
        start_height = struct.unpack_from("<i", payload, offset)[0]
    return version, services, start_height


def encode_getcfilters(start_height: int, stop_hash: bytes) -> bytes:
    if len(stop_hash) != 32:
        raise ValueError("stop_hash muss 32 Byte sein")
    return struct.pack("<B", FILTER_TYPE_BASIC) + struct.pack("<I", start_height) + stop_hash


def decode_cfilter(payload: bytes) -> tuple[bytes, bytes]:
    """(block_hash intern, filter bytes)."""
    if len(payload) < 1 + 32:
        raise ValueError("cfilter zu kurz")
    block_hash = payload[1:33]
    n, offset = read_compact_size(payload, 33)
    blob = payload[offset : offset + n]
    if len(blob) != n:
        raise ValueError("cfilter unvollständig")
    return block_hash, blob


def encode_getdata_block(block_hash: bytes) -> bytes:
    return compact_size(1) + struct.pack("<I", MSG_WITNESS_BLOCK) + block_hash


def encode_getdata_tx(txid_internal: bytes) -> bytes:
    return compact_size(1) + struct.pack("<I", MSG_WITNESS_TX) + txid_internal


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("P2P-Verbindung geschlossen")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class BitcoinPeer:
    """Eine Bitcoin-P2P-Verbindung."""

    def __init__(self, sock: socket.socket, *, host: str = "", port: int = 0):
        self.sock = sock
        self.host = host
        self.port = port
        self.services = 0
        self.start_height = 0
        self.version = 0

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, command: str, payload: bytes = b"") -> None:
        self.sock.sendall(encode_message(command, payload))

    def recv(self, *, timeout: float | None = None) -> tuple[str, bytes]:
        if timeout is not None:
            self.sock.settimeout(timeout)
        header = _recv_exact(self.sock, 24)
        command, length, checksum = decode_header(header)
        payload = _recv_exact(self.sock, length) if length else b""
        if double_sha256(payload)[:4] != checksum:
            raise ConnectionError(f"P2P-Prüfsumme falsch ({command})")
        return command, payload

    def handshake(self) -> None:
        self.send("version", encode_version())
        gesehen: set[str] = set()
        while "verack" not in gesehen or "version" not in gesehen:
            command, payload = self.recv(timeout=20)
            gesehen.add(command)
            if command == "version":
                self.version, self.services, self.start_height = decode_version_services(
                    payload
                )
                self.send("verack")
            elif command == "ping":
                self.send("pong", payload)
            elif command in ("sendheaders", "sendcmpct", "wtxidrelay", "sendaddrv2"):
                continue
        if not (self.services & NODE_COMPACT_FILTERS):
            raise ConnectionError(
                f"{self.host}:{self.port} bietet keine Compact Filter "
                f"(services={self.services})"
            )

    def ping_keep(self, command: str, payload: bytes) -> bool:
        if command == "ping":
            self.send("pong", payload)
            return True
        return False

    def fetch_cfilters(
        self, start_height: int, stop_hash: bytes, *, expect: int
    ) -> list[tuple[bytes, bytes]]:
        self.send("getcfilters", encode_getcfilters(start_height, stop_hash))
        gefunden: list[tuple[bytes, bytes]] = []
        while len(gefunden) < expect:
            command, payload = self.recv(timeout=60)
            if self.ping_keep(command, payload):
                continue
            if command != "cfilter":
                continue
            gefunden.append(decode_cfilter(payload))
        return gefunden

    def fetch_block(self, block_hash: bytes) -> bytes:
        self.send("getdata", encode_getdata_block(block_hash))
        while True:
            command, payload = self.recv(timeout=180)
            if self.ping_keep(command, payload):
                continue
            if command == "block":
                return payload
            if command == "notfound":
                raise ConnectionError("Peer hat den Block nicht")

    def fetch_tx(self, txid_internal: bytes) -> bytes:
        self.send("getdata", encode_getdata_tx(txid_internal))
        while True:
            command, payload = self.recv(timeout=30)
            if self.ping_keep(command, payload):
                continue
            if command == "tx":
                return payload
            if command == "notfound":
                raise ConnectionError("Peer hat die Transaktion nicht")


def host_ist_lan(host: str) -> bool:
    """Heimnetz, Loopback, .local — nicht über Tor."""
    text = (host or "").strip().lower()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if text in ("localhost", "::1") or text.endswith(".local"):
        return True
    if text.startswith("127.") or text.startswith("10.") or text.startswith("192.168."):
        return True
    if text.startswith("172."):
        teile = text.split(".")
        if len(teile) >= 2 and teile[1].isdigit() and 16 <= int(teile[1]) <= 31:
            return True
    if text.startswith("fe80:") or text.startswith("fc") or text.startswith("fd"):
        return True
    return False


def host_ist_onion(host: str) -> bool:
    text = (host or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.split("/")[0].split(":")[0].endswith(".onion")


def p2p_peers_from_env(env: dict[str, str] | None) -> list[tuple[str, int]]:
    """LAN-Node zuerst (Host im LAN), dann ``BIP158_PEERS``."""
    env = env or {}
    lan = (env.get("BIP158_HOST") or env.get("FULCRUM_HOST") or "").strip()
    fest = parse_peer_liste(env.get("BIP158_PEERS", ""))
    gesehen: set[tuple[str, int]] = set()
    out: list[tuple[str, int]] = []
    if lan and not host_ist_onion(lan):
        for paar in parse_peer_liste(lan):
            if paar not in gesehen:
                gesehen.add(paar)
                out.append(paar)
    for paar in fest:
        if paar not in gesehen:
            gesehen.add(paar)
            out.append(paar)
    return out


def _oeffne_socket(
    host: str,
    port: int,
    timeout: float,
    tor_proxy: tuple[str, int] | None,
) -> socket.socket:
    if tor_proxy and not host_ist_lan(host):
        from fulcrum import _socks5_connect

        return _socks5_connect(tor_proxy[0], tor_proxy[1], host, port, int(timeout))
    return socket.create_connection((host, port), timeout=timeout)


def verbinde_peer(
    host: str,
    port: int = DEFAULT_P2P_PORT,
    *,
    timeout: float = 8.0,
    tor_proxy: tuple[str, int] | None = None,
) -> BitcoinPeer:
    sock = _oeffne_socket(host, port, timeout, tor_proxy)
    sock.settimeout(timeout)
    peer = BitcoinPeer(sock, host=host, port=port)
    try:
        peer.handshake()
    except Exception:
        peer.close()
        raise
    return peer


def _sag(on_log: Callable[[str], None] | None, text: str) -> None:
    if on_log:
        on_log(text)


def _verbinde_ansage(
    host: str,
    port: int,
    tor_proxy: tuple[str, int] | None,
    on_log: Callable[[str], None] | None,
) -> None:
    if tor_proxy and not host_ist_lan(host):
        _sag(on_log, f"Verbinde mit {host}:{port} über Tor")
    else:
        _sag(on_log, f"Verbinde mit {host}:{port}")


def parse_p2p_tor_proxy(env: dict[str, str] | None) -> tuple[str, int]:
    """Wie ``main._parse_tor_proxy``: .env, sonst 127.0.0.1:9050."""
    raw = ""
    if env:
        raw = (env.get("FULCRUM_TOR_PROXY") or env.get("TOR_PROXY") or "").strip()
    if not raw:
        raw = "127.0.0.1:9050"
    if ":" in raw:
        host, port_str = raw.rsplit(":", 1)
        if port_str.isdigit():
            return host, int(port_str)
    return raw, 9050


def stelle_p2p_tor_bereit(
    env: dict[str, str] | None = None,
    *,
    on_log: Callable[[str], None] | None = None,
) -> tuple[str, int] | None:
    """
    Tor-SOCKS wie beim eigenen Onion-Node.

    Zuerst ein schon laufender Proxy (konfiguriert, Tor Browser 9150, Dienst
    9050). Sonst Autostart des ``tor``-Binary, ohne Browser-Fenster.
    """
    from core.tor import TorFehler, stelle_tor_socks_bereit

    try:
        return stelle_tor_socks_bereit(
            parse_p2p_tor_proxy(env),
            env=env or {},
            log=on_log,
        )
    except (TorFehler, ValueError) as exc:
        _sag(on_log, f"Tor für P2P nicht bereit: {exc}")
        return None


_CLEAR_PORT_BLOCKIERT = False


def reset_clearnet_port_block_cache() -> None:
    """Nur Tests — die Firewall-Lage ändert sich in einer Sitzung nicht."""
    global _CLEAR_PORT_BLOCKIERT
    _CLEAR_PORT_BLOCKIERT = False


def _timeout_fehler(exc: BaseException) -> bool:
    """SYN-Drop / kein Handshake — nicht Connection refused."""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    errno = getattr(exc, "errno", None)
    if errno in (110, 10060, 10035, 11):
        return True
    klein = str(exc).lower()
    return "timed out" in klein or "timeout" in klein


def _tcp_connect_fehler(
    host: str,
    port: int,
    timeout: float,
    tor_proxy: tuple[str, int] | None,
) -> BaseException | None:
    """Nur TCP. Kein Bitcoin-Handshake, kein Compact Filter."""
    try:
        sock = _oeffne_socket(host, port, timeout, tor_proxy)
        sock.close()
        return None
    except BaseException as exc:
        return exc


def _stichprobe_clearnet_hosts(
    peers: list[tuple[str, int]] | None,
    *,
    anzahl: int = CLEAR_PORT_PROBE_HOSTS,
) -> list[tuple[str, int]]:
    """Wenige Internet-IPs, ohne x40-Rundlauf und ohne alle Seeds."""
    gesehen: set[str] = set()
    out: list[tuple[str, int]] = []
    for host, port in list(peers or []) + bekannte_filter_peers():
        if host_ist_lan(host) or host in gesehen:
            continue
        gesehen.add(host)
        out.append((host, port or DEFAULT_P2P_PORT))
        if len(out) >= anzahl:
            return out
    try:
        infos = socket.getaddrinfo(
            DNS_SEEDS[0], DEFAULT_P2P_PORT, socket.AF_INET,
        )
    except OSError:
        infos = []
    for info in infos:
        ip = info[4][0]
        if host_ist_lan(ip) or ip in gesehen:
            continue
        gesehen.add(ip)
        out.append((ip, DEFAULT_P2P_PORT))
        if len(out) >= anzahl:
            break
    return out


def clearnet_p2p_port_blockiert(
    peers: list[tuple[str, int]] | None = None,
    *,
    timeout: float = CLEAR_PORT_PROBE_TIMEOUT,
    on_log: Callable[[str], None] | None = None,
) -> bool:
    """
    True, wenn ausgehendes TCP 8333 überall per Timeout stirbt.

    Drei Hosts parallel, nur SYN — kein Peer-Handshake. Alle Timeouts
    heißen Firewall, nicht „dieser Node ist tot“ (das wäre refused).
    """
    global _CLEAR_PORT_BLOCKIERT
    if _CLEAR_PORT_BLOCKIERT:
        _sag(on_log, "Port 8333 wirkt blockiert (bereits geprüft).")
        return True
    stich = _stichprobe_clearnet_hosts(peers)
    if len(stich) < 2:
        return False
    _sag(
        on_log,
        f"Prüfe Port 8333 an {len(stich)} Hosts (TCP, ohne Handshake)…",
    )
    fehler: list[BaseException | None] = []
    with ThreadPoolExecutor(max_workers=len(stich)) as pool:
        futures = [
            pool.submit(_tcp_connect_fehler, host, port, timeout, None)
            for host, port in stich
        ]
        for fut in as_completed(futures):
            fehler.append(fut.result())
    if fehler and all(f is not None and _timeout_fehler(f) for f in fehler):
        _CLEAR_PORT_BLOCKIERT = True
        _sag(
            on_log,
            "Port 8333 wirkt blockiert (Timeout zu allen Stichproben).",
        )
        return True
    if any(f is None for f in fehler):
        _sag(on_log, "Port 8333 ist erreichbar.")
    return False


def _nur_lan(
    paare: list[tuple[str, int]] | None,
) -> list[tuple[str, int]]:
    return [p for p in (paare or []) if host_ist_lan(p[0])]


_FILTER_PEER_CACHE: list[tuple[str, int]] = []
_FILTER_PEER_LOCK = threading.Lock()
_FILTER_PEER_CACHE_MAX = 20
_FILTER_PEER_LOADED = False
#: Persistente Merk-Liste (überlebt Neustart) — zuletzt erfolgreiche zuerst.
FILTER_PEER_DATEI = "p2p_filter_peers.json"


def _filter_peer_pfad() -> Path:
    from core.paths import app_dir

    return app_dir() / "immutable_cache" / FILTER_PEER_DATEI


def _lade_filter_peers_datei() -> None:
    """Einmalig: gemerkte Compact-Filter-Peers von Disk in den RAM-Cache."""
    global _FILTER_PEER_LOADED
    with _FILTER_PEER_LOCK:
        if _FILTER_PEER_LOADED:
            return
        _FILTER_PEER_LOADED = True
        pfad = _filter_peer_pfad()
        if not pfad.is_file():
            return
        try:
            import json

            roh = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        eintraege = roh.get("peers") if isinstance(roh, dict) else roh
        if not isinstance(eintraege, list):
            return
        geladen: list[tuple[str, int]] = []
        gesehen: set[tuple[str, int]] = set()
        for item in eintraege:
            host, port = "", DEFAULT_P2P_PORT
            if isinstance(item, str) and ":" in item:
                h, _, p = item.rpartition(":")
                host, port = h.strip(), int(p) if p.isdigit() else DEFAULT_P2P_PORT
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                host = str(item[0]).strip()
                try:
                    port = int(item[1])
                except (TypeError, ValueError):
                    port = DEFAULT_P2P_PORT
            elif isinstance(item, dict):
                host = str(item.get("host") or "").strip()
                try:
                    port = int(item.get("port") or DEFAULT_P2P_PORT)
                except (TypeError, ValueError):
                    port = DEFAULT_P2P_PORT
            if not host:
                continue
            paar = (host, port)
            if paar in gesehen:
                continue
            gesehen.add(paar)
            geladen.append(paar)
            if len(geladen) >= _FILTER_PEER_CACHE_MAX:
                break
        # Datei = zuletzt erfolgreich zuerst; RAM noch leere Liste füllen.
        if geladen and not _FILTER_PEER_CACHE:
            _FILTER_PEER_CACHE[:] = geladen


def _speichere_filter_peers_datei() -> None:
    """Schreibt den RAM-Cache atomar auf Disk (best effort)."""
    with _FILTER_PEER_LOCK:
        snapshot = list(_FILTER_PEER_CACHE)
    if not snapshot:
        return
    pfad = _filter_peer_pfad()
    try:
        import json

        pfad.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "peers": [{"host": h, "port": p} for h, p in snapshot],
            "updated": int(time.time()),
        }
        tmp = pfad.with_suffix(pfad.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=0) + "\n",
            encoding="utf-8",
        )
        tmp.replace(pfad)
    except OSError:
        pass


def merke_filter_peer(host: str, port: int) -> None:
    """Erfolgreichen Compact-Filter-Peer merken (RAM + Disk, MRU)."""
    _lade_filter_peers_datei()
    paar = (str(host).strip(), int(port) or DEFAULT_P2P_PORT)
    if not paar[0]:
        return
    with _FILTER_PEER_LOCK:
        if paar in _FILTER_PEER_CACHE:
            _FILTER_PEER_CACHE.remove(paar)
        _FILTER_PEER_CACHE.insert(0, paar)
        del _FILTER_PEER_CACHE[_FILTER_PEER_CACHE_MAX:]
    _speichere_filter_peers_datei()


def demote_filter_peer(host: str, port: int) -> None:
    """Fehlgeschlagenen Peer ans Ende schieben (bleibt für Retry)."""
    _lade_filter_peers_datei()
    paar = (str(host).strip(), int(port) or DEFAULT_P2P_PORT)
    with _FILTER_PEER_LOCK:
        if paar not in _FILTER_PEER_CACHE:
            return
        _FILTER_PEER_CACHE.remove(paar)
        _FILTER_PEER_CACHE.append(paar)
    _speichere_filter_peers_datei()


def bekannte_filter_peers() -> list[tuple[str, int]]:
    """Zuletzt erfolgreiche Compact-Filter-Peers (Disk beim ersten Aufruf)."""
    _lade_filter_peers_datei()
    with _FILTER_PEER_LOCK:
        return list(_FILTER_PEER_CACHE)


def _dns_seed_aufloesen(
    name: str,
    *,
    on_log: Callable[[str], None] | None = None,
) -> list[tuple[str, int]]:
    _sag(on_log, f"Frage DNS-Seed {name}…")
    try:
        infos = socket.getaddrinfo(name, DEFAULT_P2P_PORT, socket.AF_INET)
    except OSError as exc:
        _sag(on_log, f"DNS-Seed {name} nicht erreichbar: {exc}")
        return []
    frisch: list[str] = []
    gesehen: set[str] = set()
    ziele: list[tuple[str, int]] = []
    for info in infos:
        ip = info[4][0]
        if ip in gesehen:
            continue
        gesehen.add(ip)
        frisch.append(ip)
        ziele.append((ip, DEFAULT_P2P_PORT))
    wort = "Adresse" if len(frisch) == 1 else "Adressen"
    _sag(on_log, f"DNS-Seed {name}: {len(frisch)} {wort}")
    return ziele


def dns_seed_hosts(
    seed: str = "",
    *,
    on_log: Callable[[str], None] | None = None,
) -> list[tuple[str, int]]:
    """
    P2P-Adressen aus DNS-Seeds.

    Ohne festen Seed zuerst ``x40.<seed>`` (NODE_COMPACT_FILTERS). Die
    ungefilterten Seeds liefern fast nur Nodes ohne Filter — der Scan
    darf damit nicht nach acht Versuchen aufgeben.
    """
    seeds = (seed,) if seed else DNS_SEEDS
    gefiltert: list[tuple[str, int]] = []
    rest: list[tuple[str, int]] = []
    for name in seeds:
        if not seed:
            x40 = f"x{NODE_COMPACT_FILTERS:x}.{name}"
            gefiltert.extend(_dns_seed_aufloesen(x40, on_log=on_log))
        rest.extend(_dns_seed_aufloesen(name, on_log=on_log))
    ziele = gefiltert or rest
    if gefiltert and rest:
        # x40-Treffer vorn; ungefilterte Seeds erst danach.
        extra = [p for p in rest if p not in set(gefiltert)]
        random.shuffle(gefiltert)
        random.shuffle(extra)
        ziele = gefiltert + extra
    else:
        random.shuffle(ziele)
    gesehen: set[str] = set()
    einzig: list[tuple[str, int]] = []
    for host, port in ziele:
        if host in gesehen:
            continue
        gesehen.add(host)
        einzig.append((host, port))
    return einzig


def parse_peer_liste(roh: str) -> list[tuple[str, int]]:
    """``host:port`` je Zeile oder Komma. Port default 8333."""
    paare: list[tuple[str, int]] = []
    for teil in roh.replace(",", "\n").splitlines():
        text = teil.strip()
        if not text or text.startswith("#"):
            continue
        if ":" in text:
            host, _, port_s = text.rpartition(":")
            if port_s.isdigit():
                paare.append((host.strip(), int(port_s)))
                continue
        paare.append((text, DEFAULT_P2P_PORT))
    return paare


#: Mainnet-Genesis, 80 Byte.
GENESIS_HEADER = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)

#: Bekannte Mainnet-Hashes (Anzeige-Byteorder). Locator springt hierhin,
#: statt die Kette von Genesis zu holen. Filter-Scan braucht nur Header
#: ab der Scan-Höhe.
MAINNET_CHECKPOINTS: tuple[tuple[int, str], ...] = (
    (0, "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"),
    (481_824, "0000000000000000001c8018d9cb3b742ef25114f27563e3fc4a1902167f9893"),
    (700_000, "0000000000000000000590fc0f3eba193a278534220b2b37e9849e1a770ca959"),
    (800_000, "00000000000000000002a7c4c1e48d76c5a37902165a270156b7a8d72728a054"),
    (850_000, "00000000000000000002a0b5db2a7f8d9087464c2586b546be7bce8eb53b8187"),
    (900_000, "000000000000000000010538edbfd2d5b809a33dd83f284aeea41c6d0d96968a"),
)

HEADER_FILE_MAGIC = b"XPQH1"
HEADER_LOG_STEP = 50_000
_HEADER_LOCK = threading.Lock()
HEADER_ARCHIV_NAME = "p2p_headers_segwit.bin.gz"
HEADER_ARCHIV_META_NAME = "p2p_headers_segwit.meta.json"


def p2p_headers_path(immutable_dir: Path | None = None) -> Path:
    from core.paths import app_dir

    if immutable_dir is not None:
        return Path(immutable_dir) / "p2p_headers.bin"
    return app_dir() / "immutable_cache" / "p2p_headers.bin"


def header_datei_tip(path: Path | None) -> int | None:
    """Tip der gespeicherten Kette, oder None wenn keine Datei."""
    if path is None or not Path(path).is_file():
        return None
    chain = HeaderChain(path)
    return chain.tip_height()


def header_cache_leer(path: Path | None, *, start_height: int = SEGWIT_HEIGHT) -> bool:
    """True, wenn noch keine Header hinter dem Anker liegen."""
    tip = header_datei_tip(path)
    if tip is None:
        return True
    return tip <= start_height


def header_archiv_pfad() -> Path:
    from core.paths import resource_dir

    return resource_dir() / "data" / HEADER_ARCHIV_NAME


def header_archiv_meta(pfad: Path | None = None) -> dict | None:
    meta_pfad = Path(pfad) if pfad else header_archiv_pfad().with_name(HEADER_ARCHIV_META_NAME)
    if not meta_pfad.is_file():
        return None
    import json

    try:
        daten = json.loads(meta_pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return daten if isinstance(daten, dict) else None


def _tip_aus_datei(path: Path) -> int | None:
    """Tip ohne die Datei komplett zu lesen."""
    try:
        groesse = path.stat().st_size
    except OSError:
        return None
    if groesse < 5 + 4 + 32:
        return None
    with path.open("rb") as fh:
        magic = fh.read(5)
        if magic != HEADER_FILE_MAGIC:
            if groesse % 80 == 0:
                return groesse // 80 - 1
            return None
        hoehe_b = fh.read(4)
    hoehe = struct.unpack("<I", hoehe_b)[0]
    return hoehe + (groesse - 41) // 80


def lege_header_archiv_aus(dest: Path | None, *, on_log=None) -> int | None:
    """
    Entpackt das mitgelieferte SegWit-Archiv nach *dest*, falls der lokale
    Cache fehlt oder hinter dem Archiv-Tip liegt.

    Rückgabe: ausgelegte Höhe, sonst None.
    """
    if dest is None:
        return None
    dest = Path(dest)
    archiv = header_archiv_pfad()
    if not archiv.is_file():
        return None
    meta = header_archiv_meta() or {}
    archiv_tip = int(meta.get("tip_height") or 0)
    lokal = _tip_aus_datei(dest) if dest.is_file() else None
    if lokal is not None and archiv_tip and lokal >= archiv_tip:
        return None
    import gzip

    _sag(
        on_log,
        (
            f"Lege Header-Archiv aus (bis Block {archiv_tip:,})…"
            if archiv_tip
            else "Lege Header-Archiv aus…"
        ).replace(",", "."),
    )
    roh = gzip.decompress(archiv.read_bytes())
    if not roh.startswith(HEADER_FILE_MAGIC):
        raise ValueError("Header-Archiv hat das falsche Format")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(roh)
    tmp.replace(dest)
    tip = _tip_aus_datei(dest)
    if tip is not None:
        _sag(
            on_log,
            f"Header-Archiv liegt bis Block {tip:,}.".replace(",", "."),
        )
    return tip


def checkpoint_fuer(start_height: int) -> tuple[int, bytes]:
    """Höchster bekannter Anker-Hash mit Höhe ≤ ``start_height``."""
    hoehe, anzeige = MAINNET_CHECKPOINTS[0]
    for kandidat, hexhash in MAINNET_CHECKPOINTS:
        if kandidat <= start_height:
            hoehe, anzeige = kandidat, hexhash
    return hoehe, hex_to_hash(anzeige)


def encode_getheaders(locator: list[bytes], hashstop: bytes | None = None) -> bytes:
    stop = hashstop if hashstop is not None else b"\x00" * 32
    body = struct.pack("<I", PROTOCOL_VERSION) + compact_size(len(locator))
    for item in locator:
        if len(item) != 32:
            raise ValueError("Header-Locator-Hash muss 32 Byte sein")
        body += item
    return body + stop


def decode_headers(payload: bytes) -> list[bytes]:
    n, offset = read_compact_size(payload, 0)
    headers: list[bytes] = []
    for _ in range(n):
        headers.append(payload[offset : offset + 80])
        offset += 81
    return headers


class HeaderChain:
    """Header lokal ab einem Anker (Genesis oder Checkpoint).

    ``_data`` hält 80-Byte-Header ab ``anchor + 1``. Der Anker selbst ist
    nur als Hash bekannt — genug für ``getheaders`` und ``getcfilters``.
    """

    def __init__(self, path: Path | None = None, *, start_height: int = 0):
        self.path = Path(path) if path else None
        self._anchor_height = 0
        self._anchor_hash = header_hash(GENESIS_HEADER)
        self._data = bytearray()
        geladen = False
        if self.path and self.path.is_file():
            geladen = self._load(self.path)
        if not geladen:
            self._setze_anker(*checkpoint_fuer(start_height))
        elif start_height > 0 and self._anker_reicht_nicht(start_height):
            self._setze_anker(*checkpoint_fuer(start_height))

    def _setze_anker(self, hoehe: int, intern: bytes) -> None:
        self._anchor_height = hoehe
        self._anchor_hash = intern
        self._data = bytearray()

    def _anker_reicht_nicht(self, start_height: int) -> bool:
        if self._anchor_height > start_height:
            return True
        anker, _ = checkpoint_fuer(start_height)
        return self.tip_height() < anker

    def tip_height(self) -> int:
        return self._anchor_height + len(self._data) // 80

    def header_at(self, height: int) -> bytes:
        if height == 0 and self._anchor_height == 0:
            return GENESIS_HEADER
        if height <= self._anchor_height:
            raise IndexError(f"kein voller Header bei Höhe {height} (Anker {self._anchor_height})")
        idx = height - self._anchor_height - 1
        start = idx * 80
        return bytes(self._data[start : start + 80])

    def hash_at(self, height: int) -> bytes:
        if height == self._anchor_height:
            return self._anchor_hash
        return header_hash(self.header_at(height))

    def locator(self) -> list[bytes]:
        hoehe = self.tip_height()
        hashes: list[bytes] = []
        schritt = 1
        i = hoehe
        while i > self._anchor_height:
            hashes.append(self.hash_at(i))
            i -= schritt
            if len(hashes) >= 10:
                schritt *= 2
            if i < self._anchor_height:
                break
        hashes.append(self._anchor_hash)
        return hashes

    def append(self, header: bytes) -> None:
        if len(header) != 80:
            raise ValueError("Header muss 80 Byte haben")
        prev = header[4:36]
        if prev != self.hash_at(self.tip_height()):
            raise ConnectionError("Header-Kette reißt (prev-Hash)")
        self._data.extend(header)

    def truncate_to(self, height: int) -> None:
        """Kürzt die Kette auf ``height`` (inkl.). Darf nicht unter den Anker."""
        if height < self._anchor_height:
            raise ValueError(
                f"truncate_to({height}) unter Anker {self._anchor_height}"
            )
        if height == self._anchor_height:
            self._data = bytearray()
            return
        n = height - self._anchor_height
        self._data = self._data[: n * 80]

    def hoehe_fuer_hash(
        self, intern: bytes, *, max_tiefe: int | None = 4_096,
    ) -> int | None:
        """
        Höhe zu einem internen Block-Hash, oder None.

        Sucht vom Tip rückwärts. ``max_tiefe`` begrenzt den Scan (None = bis
        Anker) — reicht für Overlap und typische Kurz-Reorgs.
        """
        tip = self.tip_height()
        unten = self._anchor_height
        if max_tiefe is not None:
            unten = max(unten, tip - max_tiefe)
        for hoehe in range(tip, unten - 1, -1):
            if self.hash_at(hoehe) == intern:
                return hoehe
        if unten > self._anchor_height and self.hash_at(self._anchor_height) == intern:
            return self._anchor_height
        return None

    def wende_header_batch_an(
        self, batch: list[bytes], *, on_log=None,
    ) -> None:
        """
        Hängt eine ``headers``-Antwort an — inkl. Overlap und Kurz-Reorg.

        Ein Peer hinter unserem Tip (oder mit anderem Locator-Treffer) liefert
        oft Header ab einem älteren gemeinsamen Vorfahren. Bekannte Header
        werden übersprungen; weicht die Spitze ab, kappen wir auf den
        gemeinsamen Vorgänger und setzen die gelieferte Kette fort.
        """
        if not batch:
            return
        i = 0
        while i < len(batch):
            vorhanden = self.hoehe_fuer_hash(header_hash(batch[i]))
            if vorhanden is None:
                break
            i += 1
        if i == len(batch):
            return
        if i:
            _sag(
                on_log,
                f"Header-Overlap: {i} bereits bekannte übersprungen "
                f"(Tip {self.tip_height():,}).".replace(",", "."),
            )
        for header in batch[i:]:
            if len(header) != 80:
                raise ValueError("Header muss 80 Byte haben")
            prev = header[4:36]
            tip = self.tip_height()
            if prev == self.hash_at(tip):
                self._data.extend(header)
                continue
            eltern = self.hoehe_fuer_hash(prev)
            if eltern is None:
                raise ConnectionError("Header-Kette reißt (prev-Hash)")
            if eltern < tip:
                _sag(
                    on_log,
                    f"Header-Reorg: Tip {tip:,} → {eltern:,}.".replace(",", "."),
                )
                self.truncate_to(eltern)
            if prev != self.hash_at(self.tip_height()):
                raise ConnectionError("Header-Kette reißt (prev-Hash)")
            self._data.extend(header)

    def _load(self, path: Path) -> bool:
        roh = path.read_bytes()
        if roh.startswith(HEADER_FILE_MAGIC):
            if len(roh) < 5 + 4 + 32:
                return False
            hoehe = struct.unpack_from("<I", roh, 5)[0]
            intern = roh[9:41]
            rest = roh[41:]
            if len(rest) % 80 != 0:
                return False
            self._anchor_height = hoehe
            self._anchor_hash = intern
            self._data = bytearray(rest)
            return True
        if roh and len(roh) % 80 == 0 and roh[:80] == GENESIS_HEADER:
            self._anchor_height = 0
            self._anchor_hash = header_hash(GENESIS_HEADER)
            self._data = bytearray(roh[80:])
            return True
        return False

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = (
            HEADER_FILE_MAGIC
            + struct.pack("<I", self._anchor_height)
            + self._anchor_hash
            + bytes(self._data)
        )
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_bytes(blob)
        tmp.replace(self.path)

    def sync(self, peer: BitcoinPeer, *, on_log=None) -> int:
        """Holt Header bis zum Peer-Tip. Rückgabe: neue Höhe."""
        anfang = self.tip_height()
        # version.start_height ≈ Peer-Best-Height — Cache schon am Tip: nichts holen.
        peer_tip = int(getattr(peer, "start_height", 0) or 0)
        if peer_tip > 0 and anfang >= peer_tip:
            _sag(
                on_log,
                f"Header-Cache aktuell bis Block {anfang:,} "
                f"(Peer-Tip {peer_tip:,}).".replace(",", "."),
            )
            return anfang
        if self._anchor_height and anfang == self._anchor_height:
            _sag(
                on_log,
                f"Frage Block-Header ab Höhe {anfang:,} (Checkpoint)…".replace(",", "."),
            )
        else:
            _sag(
                on_log,
                f"Frage Block-Header ab Höhe {anfang:,}…".replace(",", "."),
            )
        letzter_log = anfang
        while True:
            peer.send("getheaders", encode_getheaders(self.locator()))
            while True:
                command, payload = peer.recv(timeout=60)
                if peer.ping_keep(command, payload):
                    continue
                if command == "headers":
                    batch = decode_headers(payload)
                    break
            if not batch:
                break
            vorher = self.tip_height()
            self.wende_header_batch_an(batch, on_log=on_log)
            tip = self.tip_height()
            # Peer hinter uns / nur Overlap: Tip unverändert, Batch zu Ende
            # → dieser Peer hat nichts Neues.
            if tip == vorher and len(batch) < 2000:
                break
            if tip == vorher and len(batch) >= 2000:
                # Volle Antwort ohne Fortschritt — anderer Peer / Locator.
                _sag(
                    on_log,
                    "Header-Antwort ohne Fortschritt — Sync hier beendet.",
                )
                break
            if on_log and (
                tip - letzter_log >= HEADER_LOG_STEP or len(batch) < 2000
            ):
                on_log(f"Header bis Block {tip:,}".replace(",", "."))
                letzter_log = tip
            self.save()
            if len(batch) < 2000:
                break
        self.save()
        return self.tip_height()


def hole_header(
    path: Path | None,
    start_height: int,
    peer: BitcoinPeer,
    *,
    on_log=None,
) -> HeaderChain:
    """Lädt und ergänzt die Header-Datei unter einem Prozess-Schloss."""
    if not _HEADER_LOCK.acquire(timeout=0.05):
        _sag(on_log, "Warte, bis der Header-Download im Hintergrund fertig ist…")
        _HEADER_LOCK.acquire()
    try:
        lege_header_archiv_aus(path, on_log=on_log)
        chain = HeaderChain(path, start_height=start_height)
        chain.sync(peer, on_log=on_log)
        return chain
    finally:
        _HEADER_LOCK.release()


def _kandidaten_ohne_dns(
    peers: list[tuple[str, int]] | None,
    *,
    on_log: Callable[[str], None] | None = None,
) -> list[tuple[str, int]]:
    """
    Schnellpfad: feste/.env-Peers und zuletzt erfolgreiche Merk-Liste.

    Kein DNS — für Tip-Check und ersten Verbindungsversuch.
    Reihenfolge: LAN/fest → gemerkte (MRU).
    """
    fest = list(peers or [])
    kandidaten: list[tuple[str, int]] = []
    gesehen: set[tuple[str, int]] = set()
    for paar in fest:
        if paar in gesehen:
            continue
        gesehen.add(paar)
        kandidaten.append(paar)
    bekannt = bekannte_filter_peers()
    if fest:
        _sag(on_log, f"Feste Peer-Liste: {len(fest)} Einträge")
    if bekannt:
        _sag(
            on_log,
            f"Merk-Liste: {len(bekannt)} zuletzt erfolgreiche "
            f"Compact-Filter-Peer(s)",
        )
    for paar in bekannt:
        if paar in gesehen:
            continue
        gesehen.add(paar)
        kandidaten.append(paar)
    return kandidaten


def _kandidaten_mit_dns(
    peers: list[tuple[str, int]] | None,
    *,
    dns_fallback: bool,
    on_log: Callable[[str], None] | None,
) -> list[tuple[str, int]]:
    """LAN/fest + Merk-Liste, optional DNS-Seeds hinten."""
    kandidaten = _kandidaten_ohne_dns(peers, on_log=on_log)
    gesehen = set(kandidaten)
    if dns_fallback or not kandidaten:
        _sag(on_log, "Suche P2P-Peers über DNS-Seeds…")
        for paar in dns_seed_hosts(on_log=on_log):
            if paar in gesehen:
                continue
            gesehen.add(paar)
            kandidaten.append(paar)
    return kandidaten


def _p2p_kandidaten(
    peers: list[tuple[str, int]] | None,
    *,
    dns_fallback: bool,
    tor_proxy: tuple[str, int] | None,
    on_log: Callable[[str], None] | None,
    dns_sofort: bool = True,
) -> list[tuple[str, int]]:
    """
    Peer-Liste für Handshake.

    Wirkt Port 8333 blockiert, entfällt DNS und jeder Internet-Host —
    übrig bleibt nur das LAN.

    *dns_sofort=False*: nur fest + Merk-Liste (DNS später nachziehen).
    """
    if tor_proxy is None and dns_fallback and dns_sofort:
        if clearnet_p2p_port_blockiert(peers, on_log=on_log):
            # 8333 blockiert: kein Internet, auch keine gemerkten Clearnet-IPs.
            return _nur_lan(peers)
    if not dns_sofort:
        return _kandidaten_ohne_dns(peers, on_log=on_log)
    return _kandidaten_mit_dns(
        peers, dns_fallback=dns_fallback, on_log=on_log,
    )


def probe_compact_filter_peer(
    *,
    timeout: float = 8.0,
    tor_proxy: tuple[str, int] | None = None,
    peers: list[tuple[str, int]] | None = None,
    on_log: Callable[[str], None] | None = None,
    versuche: int = 24,
    dns_fallback: bool = True,
) -> tuple[str, int] | None:
    """
    Findet einen Peer mit Compact-Filter-Dienst.

    Zuerst LAN/fest + Merk-Liste, bei Misserfolg DNS-Seeds.
    """
    def _versuche(liste: list[tuple[str, int]]) -> tuple[str, int] | None:
        for host, port in liste[:versuche]:
            _verbinde_ansage(host, port, tor_proxy, on_log)
            try:
                peer = verbinde_peer(
                    host, port, timeout=timeout, tor_proxy=tor_proxy,
                )
            except Exception as exc:
                demote_filter_peer(host, port)
                _sag(on_log, f"Verbindung fehlgeschlagen {host}:{port}: {exc}")
                continue
            peer.close()
            merke_filter_peer(host, port)
            _sag(on_log, f"Verbunden. Compact Filter {host}:{port}")
            return host, port
        return None

    phase1 = _p2p_kandidaten(
        peers,
        dns_fallback=False,
        tor_proxy=tor_proxy,
        on_log=on_log,
        dns_sofort=False,
    )
    if phase1:
        _sag(
            on_log,
            f"{len(phase1)} Kandidaten (Merk-Liste/LAN), prüfe Compact Filter…",
        )
        treffer = _versuche(phase1)
        if treffer:
            return treffer
    if dns_fallback:
        _sag(on_log, "Merk-Liste ohne Treffer — DNS-Seeds…")
        phase2 = [
            p
            for p in _p2p_kandidaten(
                peers,
                dns_fallback=True,
                tor_proxy=tor_proxy,
                on_log=on_log,
                dns_sofort=True,
            )
            if p not in set(phase1)
        ]
        if phase2:
            _sag(on_log, f"{len(phase2)} DNS-Kandidaten, prüfe Compact Filter…")
            treffer = _versuche(phase2)
            if treffer:
                return treffer
    if not phase1 and not dns_fallback:
        _sag(on_log, "Keine P2P-Adressen gefunden.")
    else:
        _sag(on_log, "Verbindung fehlgeschlagen: kein Compact-Filter-Peer")
    return None


def _verbinde_peer_batch(
    warteschlange: list[tuple[str, int]],
    *,
    live: list,
    limit: int,
    timeout: float,
    tor_proxy: tuple[str, int] | None,
    on_log: Callable[[str], None] | None,
) -> None:
    """Füllt *live* bis *limit* aus der Warteschlange (parallel je Batch)."""
    while warteschlange and len(live) < limit:
        batch = warteschlange[:8]
        del warteschlange[:8]
        for host, port in batch:
            _verbinde_ansage(host, port, tor_proxy, on_log)

        def eines(
            paar: tuple[str, int],
        ) -> tuple[str, int, object | None, BaseException | None]:
            host, port = paar
            try:
                peer = verbinde_peer(
                    host, port, timeout=timeout, tor_proxy=tor_proxy,
                )
                return host, port, peer, None
            except BaseException as exc:
                return host, port, None, exc

        with ThreadPoolExecutor(max_workers=min(8, len(batch))) as pool:
            futures = [pool.submit(eines, paar) for paar in batch]
            for fut in as_completed(futures):
                host, port, peer, fehler = fut.result()
                if peer is None:
                    demote_filter_peer(host, port)
                    _sag(
                        on_log,
                        f"Verbindung fehlgeschlagen {host}:{port}: {fehler}",
                    )
                    continue
                if len(live) >= limit:
                    peer.close()  # type: ignore[union-attr]
                    continue
                live.append(peer)
                merke_filter_peer(host, port)
                _sag(on_log, f"Verbunden. Compact Filter {host}:{port}")


def verbinde_compact_filter_peers(
    *,
    timeout: float = 8.0,
    tor_proxy: tuple[str, int] | None = None,
    peers: list[tuple[str, int]] | None = None,
    on_log: Callable[[str], None] | None = None,
    limit: int = FILTER_PEERS_MAX,
    exclude: set[tuple[str, int]] | None = None,
    dns_fallback: bool = True,
    versuche: int = 32,
    ruhig: bool = False,
) -> list[BitcoinPeer]:
    """
    Offene Compact-Filter-Verbindungen. Nicht schließen.

    1. Zuerst LAN/fest + **Merk-Liste** (zuletzt erfolgreiche, auch von Disk)
    2. Nur wenn zu wenige: DNS-Seeds nachziehen

    *ruhig*: Scan-Betrieb — knappe Logs, Warnung unter ``P2P_SCAN_WARN_PEERS``.
    """
    if limit <= 0:
        return []
    meld = None if ruhig else on_log
    gesperrt = set(exclude or [])
    live: list[BitcoinPeer] = []

    # --- Phase 1: bekannte Peers, kein DNS ---------------------------------
    phase1 = [
        p
        for p in _p2p_kandidaten(
            peers,
            dns_fallback=False,
            tor_proxy=tor_proxy,
            on_log=meld,
            dns_sofort=False,
        )
        if p not in gesperrt
    ][:versuche]
    if phase1:
        _sag(
            meld,
            f"Suche bis zu {limit} Compact-Filter-Peers "
            f"(zuerst {len(phase1)} aus Merk-Liste/LAN)…",
        )
        _verbinde_peer_batch(
            list(phase1),
            live=live,
            limit=limit,
            timeout=timeout,
            tor_proxy=tor_proxy,
            on_log=meld,
        )
    else:
        _sag(meld, f"Suche bis zu {limit} Compact-Filter-Peers…")

    # --- Phase 2: DNS nur wenn noch Plätze --------------------------------
    if len(live) < limit and dns_fallback:
        if live:
            _sag(
                meld,
                f"{len(live)} Peer(s) aus Merk-Liste — "
                f"weitere über DNS (noch {limit - len(live)})…",
            )
        else:
            _sag(meld, "Merk-Liste leer/ohne Treffer — DNS-Seeds…")
        gesperrt_live = {(p.host, p.port) for p in live} | gesperrt
        phase2 = [
            p
            for p in _p2p_kandidaten(
                peers,
                dns_fallback=True,
                tor_proxy=tor_proxy,
                on_log=meld,
                dns_sofort=True,
            )
            if p not in gesperrt_live
        ][: max(0, versuche - len(phase1))]
        if phase2:
            _verbinde_peer_batch(
                list(phase2),
                live=live,
                limit=limit,
                timeout=timeout,
                tor_proxy=tor_proxy,
                on_log=meld,
            )

    if live:
        wort = "Peer" if len(live) == 1 else "Peers"
        # limit=1: Header-/Probe-Pfad — kein „Scan langsamer“-Alarm.
        if limit <= 1:
            p0 = live[0]
            host = getattr(p0, "host", "?")
            port = getattr(p0, "port", "")
            wo = f"{host}:{port}" if port != "" else str(host)
            _sag(on_log, f"Verbunden. Compact-Filter-Peer {wo} (Header/Probe).")
        else:
            _sag(
                on_log,
                f"Verbunden. {len(live)} Compact-Filter-{wort} für den Scan.",
            )
            if len(live) < min(P2P_SCAN_WARN_PEERS, limit):
                _sag(
                    on_log,
                    f"Nur {len(live)} Compact-Filter-{wort} "
                    f"(Ziel {limit}) — Filter-Scan wird langsamer.",
                )
    else:
        _sag(on_log, "Verbindung fehlgeschlagen: kein Compact-Filter-Peer")
    return live


def zaehle_compact_filter_peers(
    *,
    timeout: float = 4.0,
    tor_proxy: tuple[str, int] | None = None,
    peers: list[tuple[str, int]] | None = None,
    on_log: Callable[[str], None] | None = None,
    versuche: int = 16,
    dns_fallback: bool = True,
) -> list[str]:
    """
    Compact-Filter-Peers als ``host:port``.

    Parallel, kurzes Timeout — für den Verbindungstest, nicht den Scan.
    LAN/feste Peers zuerst; ohne Filter zusätzlich DNS-Seeds.
    Wirkt Port 8333 blockiert, entfällt der DNS-Rundlauf.
    """
    kandidaten = _p2p_kandidaten(
        peers, dns_fallback=dns_fallback, tor_proxy=tor_proxy, on_log=on_log,
    )
    if not kandidaten:
        _sag(on_log, "Keine P2P-Adressen gefunden.")
        return []
    auswahl = kandidaten[:versuche]
    _sag(on_log, f"{len(auswahl)} Kandidaten, prüfe Compact Filter…")
    for host, port in auswahl:
        _verbinde_ansage(host, port, tor_proxy, on_log)

    def eines(paar: tuple[str, int]) -> tuple[str, int, BaseException | None]:
        host, port = paar
        try:
            peer = verbinde_peer(host, port, timeout=timeout, tor_proxy=tor_proxy)
            peer.close()
            return host, port, None
        except BaseException as exc:
            return host, port, exc

    treffer: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, len(auswahl))) as pool:
        futures = [pool.submit(eines, paar) for paar in auswahl]
        for fut in as_completed(futures):
            host, port, fehler = fut.result()
            if fehler is None:
                treffer.append(f"{host}:{port}")
                merke_filter_peer(host, port)
                _sag(on_log, f"Verbunden. Compact Filter {host}:{port}")
            else:
                _sag(on_log, f"Verbindung fehlgeschlagen {host}:{port}: {fehler}")
    treffer.sort()
    if treffer:
        _sag(on_log, f"Verbunden. {len(treffer)} Compact-Filter-Peers.")
    else:
        _sag(on_log, "Verbindung fehlgeschlagen: kein Compact-Filter-Peer")
    return treffer
