#!/usr/bin/env python3
"""TCP-Proxy: Electrum-JSON-RPC künstlich verlangsamen, halten oder kappen.

Regtest-Scans sind sonst in Sekunden durch — ein Abbruch trifft dann keinen
halben Cache. Dieser Proxy sitzt vor 127.0.0.1:50001 und:

* verzögert jede JSON-RPC-Zeile (Scan bleibt lange genug in der Schreibphase)
* hält TCP-Verbindungen ohne Handshake (Electrs „noch nicht da“, Onion-ähnlich)
* kappt alle Sockets (Verbindungsabbruch zum Indexer)

Nur Loopback. Kein WAN, keine Secrets.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from typing import Callable


DEFAULT_LISTEN = ("127.0.0.1", 15001)
DEFAULT_BACKEND = ("127.0.0.1", 50001)


class ElectrsDelayProxy:
    """Ein Listener, viele Client-Sockets, ein Backend (Electrs/Fulcrum)."""

    def __init__(
        self,
        listen: tuple[str, int] = DEFAULT_LISTEN,
        backend: tuple[str, int] = DEFAULT_BACKEND,
        delay_s: float = 0.4,
    ) -> None:
        self.listen = listen
        self.backend = backend
        self._delay_s = float(delay_s)
        self._delay_lock = threading.Lock()
        self._hold = threading.Event()
        self._drop = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._clients: list[socket.socket] = []
        self._listen_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.lines_client = 0
        self.lines_backend = 0
        self.accepts = 0
        self.drops = 0

    @property
    def delay_s(self) -> float:
        with self._delay_lock:
            return self._delay_s

    def set_delay(self, delay_s: float) -> None:
        with self._delay_lock:
            self._delay_s = max(0.0, float(delay_s))

    def hold(self) -> None:
        """TCP annehmen, nichts zum Backend durchreichen (Handshake bleibt aus)."""
        self._hold.set()

    def resume(self) -> None:
        """Gehaltene und neue Verbindungen weiterleiten."""
        self._hold.clear()
        self._drop.clear()

    def drop_all(self) -> None:
        """Alle Sockets schließen — Electrs-Abbruch aus Sicht von SatSage."""
        self._drop.set()
        self._close_clients()
        self.drops += 1

    def holding(self) -> bool:
        return self._hold.is_set()

    def start(self) -> None:
        if self._thread is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(self.listen)
        sock.listen(32)
        sock.settimeout(0.4)
        self._listen_sock = sock
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._accept_loop, name="electrs-delay-proxy", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._hold.clear()
        self._close_clients()
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except OSError:
                pass
            self._listen_sock = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def stats(self) -> dict:
        return {
            "listen": f"{self.listen[0]}:{self.listen[1]}",
            "backend": f"{self.backend[0]}:{self.backend[1]}",
            "delay_s": self.delay_s,
            "hold": self._hold.is_set(),
            "drop": self._drop.is_set(),
            "accepts": self.accepts,
            "drops": self.drops,
            "lines_client": self.lines_client,
            "lines_backend": self.lines_backend,
            "open_clients": len(self._clients),
        }

    def _close_clients(self) -> None:
        with self._lock:
            sockets = list(self._clients)
            self._clients.clear()
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _track(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.append(sock)

    def _untrack(self, sock: socket.socket) -> None:
        with self._lock:
            if sock in self._clients:
                self._clients.remove(sock)

    def _accept_loop(self) -> None:
        listen = self._listen_sock
        if listen is None:
            return
        while not self._stop.is_set():
            try:
                client, _addr = listen.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            self.accepts += 1
            if self._drop.is_set():
                try:
                    client.close()
                except OSError:
                    pass
                continue
            worker = threading.Thread(
                target=self._handle_client, args=(client,), daemon=True,
            )
            worker.start()

    def _sleep_interruptible(self, seconds: float) -> bool:
        """True wenn die volle Pause durchlief, False bei Stop/Drop."""
        ende = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < ende:
            if self._stop.is_set() or self._drop.is_set():
                return False
            time.sleep(min(0.05, ende - time.monotonic()))
        return True

    def _handle_client(self, client: socket.socket) -> None:
        self._track(client)
        backend: socket.socket | None = None
        try:
            client.settimeout(0.4)
            while self._hold.is_set() and not self._stop.is_set():
                if self._drop.is_set():
                    return
                # Nicht lesen: der Handshake bleibt im Socket, bis resume
                # ihn zum Backend durchreicht (halbgare TCP-Verbindung).
                time.sleep(0.05)
            if self._stop.is_set() or self._drop.is_set():
                return
            backend = socket.create_connection(self.backend, timeout=8)
            backend.settimeout(0.4)
            self._track(backend)
            fertig = threading.Event()
            nach_backend = threading.Thread(
                target=self._relay,
                args=(client, backend, True, fertig),
                daemon=True,
            )
            nach_client = threading.Thread(
                target=self._relay,
                args=(backend, client, False, fertig),
                daemon=True,
            )
            nach_backend.start()
            nach_client.start()
            while not fertig.is_set() and not self._stop.is_set() and not self._drop.is_set():
                time.sleep(0.05)
        except OSError:
            return
        finally:
            for sock in (client, backend):
                if sock is None:
                    continue
                self._untrack(sock)
                try:
                    sock.close()
                except OSError:
                    pass

    def _relay(
        self,
        src: socket.socket,
        dst: socket.socket,
        from_client: bool,
        fertig: threading.Event,
    ) -> None:
        buf = b""
        try:
            while not self._stop.is_set() and not self._drop.is_set() and not fertig.is_set():
                try:
                    chunk = src.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    zeile, buf = buf.split(b"\n", 1)
                    delay = self.delay_s if from_client else 0.0
                    if delay and not self._sleep_interruptible(delay):
                        return
                    try:
                        dst.sendall(zeile + b"\n")
                    except OSError:
                        return
                    if from_client:
                        self.lines_client += 1
                    else:
                        self.lines_backend += 1
            if buf and not self._stop.is_set() and not self._drop.is_set():
                try:
                    dst.sendall(buf)
                except OSError:
                    pass
        finally:
            fertig.set()


def _parse_hostport(text: str, default_host: str, default_port: int) -> tuple[str, int]:
    roh = (text or "").strip()
    if not roh:
        return default_host, default_port
    if ":" not in roh:
        return default_host, int(roh)
    host, port = roh.rsplit(":", 1)
    return (host or default_host), int(port)


def _watch_control_file(proxy: ElectrsDelayProxy, pfad: str, on_log: Callable[[str], None]) -> None:
    """Steuerung für manuelle Läufe: hold / resume / drop / delay 400 / stop."""
    from pathlib import Path

    datei = Path(pfad)
    gesehen = 0
    while not proxy._stop.is_set():
        time.sleep(0.2)
        if not datei.is_file():
            continue
        try:
            zeilen = datei.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if len(zeilen) <= gesehen:
            continue
        neu = zeilen[gesehen:]
        gesehen = len(zeilen)
        for roh in neu:
            cmd = roh.strip().lower()
            if not cmd or cmd.startswith("#"):
                continue
            if cmd == "hold":
                proxy.hold()
                on_log("hold")
            elif cmd == "resume":
                proxy.resume()
                on_log("resume")
            elif cmd == "drop":
                proxy.drop_all()
                on_log("drop")
            elif cmd.startswith("delay"):
                teile = cmd.split()
                if len(teile) >= 2:
                    try:
                        ms = float(teile[1])
                    except ValueError:
                        continue
                    proxy.set_delay(ms / 1000.0 if ms >= 10 else ms)
                    on_log(f"delay {proxy.delay_s:.3f}s")
            elif cmd == "stop":
                proxy.stop()
                on_log("stop")
                return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1:15001")
    parser.add_argument("--backend", default="127.0.0.1:50001")
    parser.add_argument("--delay-ms", type=float, default=400.0)
    parser.add_argument("--hold", action="store_true", help="Zuerst Handshake zurückhalten")
    parser.add_argument(
        "--control-file",
        default="",
        help="Textdatei: je Zeile hold|resume|drop|delay <ms>|stop",
    )
    args = parser.parse_args()
    listen = _parse_hostport(args.listen, *DEFAULT_LISTEN)
    backend = _parse_hostport(args.backend, *DEFAULT_BACKEND)
    proxy = ElectrsDelayProxy(listen, backend, delay_s=max(0.0, args.delay_ms) / 1000.0)
    if args.hold:
        proxy.hold()
    try:
        proxy.start()
    except OSError as exc:
        print(f"Listen fehlgeschlagen {listen[0]}:{listen[1]}: {exc}", file=sys.stderr)
        return 1
    print(
        f"electrs-delay-proxy {listen[0]}:{listen[1]} → {backend[0]}:{backend[1]} "
        f"delay={proxy.delay_s:.3f}s hold={proxy.holding()}",
        flush=True,
    )
    if args.control_file:
        watcher = threading.Thread(
            target=_watch_control_file,
            args=(proxy, args.control_file, lambda m: print(f"control: {m}", flush=True)),
            daemon=True,
        )
        watcher.start()
    try:
        while not proxy._stop.is_set():
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("stop", flush=True)
    finally:
        proxy.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
