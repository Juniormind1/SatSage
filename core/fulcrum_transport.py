"""Fulcrum/Electrum SOCKS5-Transport und Tor-Proxy-Hilfen."""
from __future__ import annotations

import socket
import struct


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


TOR_PROXY_CHECK_TIMEOUT = 2
TOR_BROWSER_SOCKS_HOST = "127.0.0.1"
TOR_BROWSER_SOCKS_PORT = 9150
TOR_EXPERT_SOCKS_PORT = 9050
TOR_BROWSER_DOWNLOAD = "https://www.torproject.org/download/"


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
