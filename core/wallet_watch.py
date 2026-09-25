"""
Hintergrund: Wallets „immer aktuell“ halten über eigenen Electrs.

Strategie (gut, wenn eigener Electrs da ist):

1. Einmal Tip-Nachzug beim Start (wie bisher) — Nav darf „aktualisiere…“ zeigen.
2. ``blockchain.scripthash.subscribe`` auf bekannte Cache- + Empfangs-Gap-Adressen —
   Push bei Mempool/Bestätigung, dann nur ``listunspent`` dieser Adresse.
3. ``blockchain.headers.subscribe``: **kein** Tip-Nachzug, solange Subscribe greift
   (Adress-Push reicht). Greift Subscribe nicht (0 Adressen / Session weg):
   debounced **stiller** Tip-Nachzug (Hintergrund, ohne Nav-„aktualisiere…“).

Bitcoin Core hat kein leichtes Adress-Subscribe (nur ZMQ/Wallet) — deshalb
Electrs zuerst. Ohne eigenen Electrs: nur Start-Tip-Nachzug, kein Watcher.

Öffentliche Electrum-Server: bewusst **kein** Dauer-Subscribe (Privatsphäre).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable


# Nach neuem Block: kurz warten (Batch), dann leichter Tip-Nachzug.
_HEADER_DEBOUNCE_S = 4.0
# Nach Scripthash-Notify: Adressen bündeln.
_SCRIPT_DEBOUNCE_S = 1.0
# Max. Adressen pro Wallet (UTXO + letzte Verlaufsadressen).
_MAX_ADDR_PRO_WALLET = 400


def _header_hoehe(header) -> int | None:
    """Höhe aus Electrs ``headers.subscribe``-Notify/Result."""
    if header is None:
        return None
    if isinstance(header, dict):
        roh = header.get("height")
        if roh is None and isinstance(header.get("header"), dict):
            roh = header["header"].get("height")
        try:
            return int(roh) if roh is not None else None
        except (TypeError, ValueError):
            return None
    try:
        return int(header)
    except (TypeError, ValueError):
        return None


class WalletWatchService:
    """Ein Prozess, ein Watcher — start/stop von server.py."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session = None
        self._state = None
        self._sh_to_addr: dict[str, str] = {}
        self._addr_to_xpubs: dict[str, set[str]] = {}
        self._status: dict[str, Any] = {}
        self._pending_scripts: set[str] = set()
        self._script_timer: threading.Timer | None = None
        self._header_timer: threading.Timer | None = None
        self._on_log: Callable[[str], None] | None = None
        #: Header kam während laufendem Tip-Nachzug — danach nochmal.
        self._tip_nachzug_offen = False
        #: Letzter gesehener Chain-Tip (Electrs headers.subscribe) für UI-Atem.
        self._last_block_height: int | None = None
        self._last_block_seq: int = 0

    @property
    def laeuft(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.laeuft,
                "subscribed": len(self._sh_to_addr),
                "host": (self._status.get("host") if self._session else None),
                "last_block_height": self._last_block_height,
                "last_block_seq": self._last_block_seq,
                **{k: v for k, v in self._status.items() if k != "host"},
            }

    def start(self, state, *, on_log=None) -> bool:
        """
        Startet Watcher wenn Option an und eigener Electrs erreichbar.
        Rückgabe True wenn Thread läuft (oder schon lief).
        """
        from core.env_wallets import resolve_wallets_beim_start_aktualisieren

        self._on_log = on_log
        werte = state.env().values()
        if not resolve_wallets_beim_start_aktualisieren(werte):
            self.stop()
            return False

        with self._lock:
            if self._thread and self._thread.is_alive():
                self._state = state
                return True
            self._state = state
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._lauf,
                name="wallet-watch",
                daemon=True,
            )
            self._thread.start()
        return True

    def restart(self, state, *, on_log=None) -> bool:
        """
        Stoppt und startet neu — nach Host/Port/TLS-Änderung am eigenen Electrs.

        ``start`` allein lässt einen laufenden Thread auf dem alten Endpoint
        sitzen; erst Neustart baut die Subscribe-Session neu auf.
        """
        if on_log is not None:
            self._on_log = on_log
        self.stop()
        return self.start(state, on_log=self._on_log)

    def stop(self) -> None:
        self._stop.set()
        self._cancel_timers()
        sess = self._session
        self._session = None
        if sess is not None:
            try:
                sess.stop()
            except Exception:
                pass
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=5.0)
        self._thread = None
        with self._lock:
            self._sh_to_addr.clear()
            self._addr_to_xpubs.clear()

    def _cancel_timers(self) -> None:
        for attr in ("_script_timer", "_header_timer"):
            tim = getattr(self, attr, None)
            if tim is not None:
                try:
                    tim.cancel()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _log(self, text: str) -> None:
        if self._on_log:
            try:
                self._on_log(text)
            except Exception:
                pass
        else:
            print(f"  {text}", flush=True)

    def _lauf(self) -> None:
        import core.chain_sources as chain_sources
        from core.env_wallets import resolve_wallets_beim_start_aktualisieren
        from core.fulcrum_client import FulcrumNotifySession, address_to_scripthash

        state = self._state
        if state is None:
            return
        while not self._stop.is_set():
            werte = state.env().values()
            if not resolve_wallets_beim_start_aktualisieren(werte):
                self._log("Wallet-Watch: aus (Option deaktiviert).")
                break
            client = None
            try:
                client = chain_sources._try_own_fulcrum_client(
                    state.args_namespace(), werte,
                )
            except Exception as exc:
                self._log(f"Wallet-Watch: kein eigener Electrs ({exc}).")
                self._status["error"] = str(exc)
                break
            if client is None:
                self._log(
                    "Wallet-Watch: kein eigener Electrs — "
                    "nur Start-Tip-Nachzug, kein Dauer-Subscribe."
                )
                self._status["error"] = "kein eigener Electrs"
                break

            host, port = client.host, client.port
            use_ssl = client.use_ssl
            tor_proxy = client.tor_proxy
            try:
                client.close()
            except Exception:
                pass

            self._log(
                f"Wallet-Watch: Electrs-Subscribe {host}:{port}…"
            )
            # Absicht: on_disconnect setzt _stop *nicht*. Sonst stirbt der
            # Watcher bei kurzem Electrs-Hänger endgültig — über Nacht typisch
            # „vor N Std. −M Blöcke“ trotz WALLETS_IMMER_AKTUELL.
            session = FulcrumNotifySession(
                host,
                port,
                use_ssl=use_ssl,
                tor_proxy=tor_proxy,
                on_scripthash=self._on_scripthash,
                on_header=self._on_header,
                on_log=self._log,
                on_disconnect=None,
            )
            self._session = session
            try:
                session.start()
                session.subscribe_headers()
                n = self._subscribe_alle_adressen(session, state)
                self._status = {
                    "host": f"{host}:{port}",
                    "subscribed": n,
                    "error": "",
                }
                self._log(
                    f"Wallet-Watch: {n} Adresse(n) abonniert — "
                    "Wallets bleiben aktuell."
                )
                # Läuft bis stop oder Reader-Ende (dann Reconnect unten).
                while not self._stop.is_set():
                    if not session._reader or not session._reader.is_alive():
                        break
                    if self._tip_nachzug_offen:
                        self._versuch_offenen_tip_nachzug()
                    time.sleep(0.5)
            except Exception as exc:
                self._log(f"Wallet-Watch abgebrochen: {exc}")
                self._status["error"] = str(exc)
            finally:
                try:
                    session.stop()
                except Exception:
                    pass
                self._session = None

            if self._stop.is_set():
                break
            # Kurze Pause, dann Reconnect-Versuch
            self._log("Wallet-Watch: Verbindung weg — Reconnect in 15 s…")
            self._stop.wait(15.0)

        self._cancel_timers()

    def _adressen_aus_caches(self, state) -> dict[str, set[str]]:
        """address → set(xpub/desc keys)."""
        mapping: dict[str, set[str]] = {}
        for entry in state.analyse_entries:
            xpub = entry.analyse_schluessel
            utxos = xpub_cache.load_xpub_utxo_cache(xpub, state.cache_dir) or []
            addrs: list[str] = []
            for u in utxos:
                a = (u.get("address") or "").strip()
                if a:
                    addrs.append(a)
            verlauf = xpub_cache.load_xpub_verlauf_cache(xpub, state.cache_dir) or []
            for e in verlauf[-200:]:
                a = (e.get("address") or "").strip()
                if a:
                    addrs.append(a)
            # Einzigartig, Kappe
            gesehen: set[str] = set()
            gekuerzt: list[str] = []
            for a in addrs:
                if a in gesehen:
                    continue
                gesehen.add(a)
                gekuerzt.append(a)
                if len(gekuerzt) >= _MAX_ADDR_PRO_WALLET:
                    break
            for a in gekuerzt:
                mapping.setdefault(a, set()).add(xpub)
        return mapping

    def _subscribe_alle_adressen(self, session, state) -> int:
        from core.fulcrum_client import address_to_scripthash

        mapping = self._adressen_aus_caches(state)
        with self._lock:
            self._addr_to_xpubs = {a: set(xs) for a, xs in mapping.items()}
            self._sh_to_addr = {}
        n = 0
        for addr, xpubs in mapping.items():
            if self._stop.is_set():
                break
            try:
                sh = address_to_scripthash(addr)
                session.subscribe_scripthash(sh)
                with self._lock:
                    self._sh_to_addr[sh] = addr
                    self._addr_to_xpubs[addr] = set(xpubs)
                n += 1
            except Exception:
                continue
        return n

    def _subscribe_extra(self, addrs: list[str], xpub: str) -> None:
        """Neue Empfangsadressen (z. B. Change aus Mempool-Tx) nachabonnieren."""
        from core.fulcrum_client import address_to_scripthash

        session = self._session
        if session is None or not addrs:
            return
        for addr in addrs:
            a = (addr or "").strip()
            if not a:
                continue
            with self._lock:
                schon = a in self._sh_to_addr.values() or a in self._addr_to_xpubs
                if schon:
                    self._addr_to_xpubs.setdefault(a, set()).add(xpub)
                    continue
            try:
                sh = address_to_scripthash(a)
                session.subscribe_scripthash(sh)
            except Exception:
                continue
            with self._lock:
                self._sh_to_addr[sh] = a
                self._addr_to_xpubs.setdefault(a, set()).add(xpub)
            self._log(f"Wallet-Watch: neue Adresse abonniert ({a[:12]}…)")

    def subscribe_addresses(self, addrs: list[str], xpub: str) -> bool:
        """
        Öffentlich: Lookahead-Adressen nachabonnieren, wenn der Watcher läuft.

        Rückgabe True, wenn Session aktiv und Aufruf durchging (auch wenn
        einzelne Adressen schon abonniert waren).
        """
        if not self.laeuft or self._session is None:
            return False
        if not addrs or not (xpub or "").strip():
            return False
        try:
            self._subscribe_extra(addrs, xpub)
            return True
        except Exception:
            return False

    def _on_scripthash(self, scripthash: str, _status) -> None:
        with self._lock:
            self._pending_scripts.add(str(scripthash))
            if self._script_timer is not None:
                try:
                    self._script_timer.cancel()
                except Exception:
                    pass
            self._script_timer = threading.Timer(
                _SCRIPT_DEBOUNCE_S, self._flush_scripts,
            )
            self._script_timer.daemon = True
            self._script_timer.start()

    def _on_header(self, header) -> None:
        hoehe = _header_hoehe(header)
        if hoehe is not None:
            with self._lock:
                if hoehe != self._last_block_height:
                    self._last_block_height = int(hoehe)
                    self._last_block_seq += 1
        with self._lock:
            if self._header_timer is not None:
                try:
                    self._header_timer.cancel()
                except Exception:
                    pass
            self._header_timer = threading.Timer(
                _HEADER_DEBOUNCE_S, self._flush_header,
            )
            self._header_timer.daemon = True
            self._header_timer.start()

    def _flush_scripts(self) -> None:
        state = self._state
        if state is None or self._stop.is_set():
            return
        with self._lock:
            shs = list(self._pending_scripts)
            self._pending_scripts.clear()
            sh_map = dict(self._sh_to_addr)
            addr_xpubs = {a: set(xs) for a, xs in self._addr_to_xpubs.items()}

        addrs = []
        for sh in shs:
            a = sh_map.get(sh)
            if a:
                addrs.append(a)
        if not addrs:
            return
        self._log(
            f"Wallet-Watch: Aktivität auf {len(addrs)} Adresse(n) — "
            "gezieltes listunspent…"
        )
        try:
            self._update_adressen(state, addrs, addr_xpubs)
        except Exception as exc:
            self._log(f"Wallet-Watch Adress-Update: {exc}")

    def _subscribe_greift(self) -> bool:
        """True wenn Scripthash-Subscribe aktiv und mindestens eine Adresse hält."""
        if self._stop.is_set() or self._session is None:
            return False
        with self._lock:
            return bool(self._sh_to_addr)

    def _flush_header(self) -> None:
        state = self._state
        if state is None or self._stop.is_set():
            return
        # 1) Subscribe greift → kein Tip (Adress-Push + Empfangs-Gap reichen).
        if self._subscribe_greift():
            return
        # 3) Fallback: stiller Tip ohne Nav-„aktualisiere…“.
        self._log(
            "Wallet-Watch: neuer Block, Subscribe unwirksam — "
            "stiller Tip-Nachzug…"
        )
        try:
            from server import starte_wallet_aktualisierung, tip_sync_laeuft

            job = starte_wallet_aktualisierung(
                state, erzwingen=True, still=True,
            )
            if job is None and tip_sync_laeuft(state):
                self._tip_nachzug_offen = True
                self._log(
                    "Wallet-Watch: Tip-Nachzug läuft schon — "
                    "erneuter stiller Lauf vorgemerkt."
                )
            elif job is not None:
                self._tip_nachzug_offen = False
        except Exception as exc:
            self._tip_nachzug_offen = True
            self._log(f"Wallet-Watch Tip-Nachzug: {exc}")

    def _versuch_offenen_tip_nachzug(self) -> None:
        """Startet vorgemerkten stillen Tip-Nachzug, sobald kein Job mehr läuft."""
        if not self._tip_nachzug_offen or self._stop.is_set():
            return
        # Subscribe inzwischen ok → vorgemerkten Tip verwerfen.
        if self._subscribe_greift():
            self._tip_nachzug_offen = False
            return
        state = self._state
        if state is None:
            return
        try:
            from server import starte_wallet_aktualisierung, tip_sync_laeuft

            if tip_sync_laeuft(state):
                return
            job = starte_wallet_aktualisierung(
                state, erzwingen=True, still=True,
            )
            if job is not None:
                self._tip_nachzug_offen = False
                self._log("Wallet-Watch: nachgezogener stiller Tip-Nachzug…")
            else:
                self._tip_nachzug_offen = False
        except Exception as exc:
            self._log(f"Wallet-Watch nachgezogener Tip-Nachzug: {exc}")

    def tip_nachzug_job_beendet(self) -> None:
        """Vom Sync-Job: offenen Header-Nachzug anstoßen."""
        if self._tip_nachzug_offen and not self._stop.is_set():
            self._versuch_offenen_tip_nachzug()

    def _update_adressen(
        self,
        state,
        addrs: list[str],
        addr_xpubs: dict[str, set[str]],
    ) -> None:
        from core.fulcrum_wallet import fetch_address_utxos_fulcrum, klassifiziere_utxo_spends

        client = _eigener_client_kurz(state)
        if client is None:
            return
        try:
            live_by_addr: dict[str, list[dict]] = {}
            for addr in addrs:
                try:
                    live = fetch_address_utxos_fulcrum(client, addr)
                except Exception:
                    continue
                angereichert = []
                for u in live:
                    neu = dict(u)
                    neu["address"] = addr
                    angereichert.append(neu)
                live_by_addr[addr] = angereichert

            # Pro Wallet: Cache-UTXOs der Adressen + live mergen / spends settlen
            xpubs_done: set[str] = set()
            for addr in addrs:
                for xpub in addr_xpubs.get(addr) or ():
                    xpubs_done.add(xpub)

            for xpub in xpubs_done:
                cached = xpub_cache.load_xpub_utxo_cache(xpub, state.cache_dir)
                if cached is None:
                    continue
                relevant = [
                    u for u in cached
                    if (u.get("address") or "").strip() in live_by_addr
                ]
                if not relevant and not any(
                    live_by_addr.get(a) for a in addrs
                    if xpub in (addr_xpubs.get(a) or ())
                ):
                    continue
                try:
                    pending, confirmed, _live = klassifiziere_utxo_spends(
                        client, relevant,
                    )
                except Exception:
                    pending, confirmed = [], []

                empfaenge: list[dict] = []
                if pending:
                    try:
                        from core.fulcrum_wallet import eigene_mempool_empfaenge

                        ctx = getattr(state, "wallet_ctx", None)
                        if ctx is not None:
                            empfaenge = eigene_mempool_empfaenge(
                                client,
                                pending,
                                is_own_address=ctx.is_own_address,
                            )
                    except Exception:
                        empfaenge = []

                live_merge: list[dict] = []
                for addr in addrs:
                    if xpub not in (addr_xpubs.get(addr) or ()):
                        continue
                    live_merge.extend(live_by_addr.get(addr) or [])

                # Pending-UTXOs im Bestand behalten (Anzeige: „wird gerade ausgegeben“).
                pend_keys = {
                    f"{str(p.get('txid') or '').lower()}:"
                    f"{int(p.get('vout') or 0)}"
                    for p in pending
                }
                for u in relevant:
                    key = (
                        f"{str(u.get('txid') or '').lower()}:"
                        f"{int(u.get('vout') or 0)}"
                    )
                    if key not in pend_keys:
                        continue
                    neu = dict(u)
                    neu["spending_pending"] = True
                    for p in pending:
                        pk = (
                            f"{str(p.get('txid') or '').lower()}:"
                            f"{int(p.get('vout') or 0)}"
                        )
                        if pk == key:
                            neu["spent_txid"] = p.get("spent_txid") or ""
                            break
                    live_merge.append(neu)

                # Change/Self-Tx: unbestätigte eigenen Empfänge in den Cache.
                live_keys = {
                    f"{str(u.get('txid') or '').lower()}:"
                    f"{int(u.get('vout') or 0)}"
                    for u in live_merge
                }
                neue_addrs: list[str] = []
                for e in empfaenge:
                    key = (
                        f"{str(e.get('txid') or '').lower()}:"
                        f"{int(e.get('vout') or 0)}"
                    )
                    if key in live_keys:
                        continue
                    live_keys.add(key)
                    live_merge.append(dict(e))
                    a = (e.get("address") or "").strip()
                    if a:
                        neue_addrs.append(a)

                if confirmed or live_merge:
                    xpub_cache.settle_gezielte_spends_im_cache(
                        xpub,
                        state.cache_dir,
                        confirmed_spent=confirmed,
                        live_auf_adressen=live_merge,
                        source="fulcrum",
                        fulcrum=client,
                    )
                if neue_addrs and self._session is not None:
                    self._subscribe_extra(neue_addrs, xpub)
                if pending:
                    try:
                        xpub_cache.merke_bip158_verlauf(
                            xpub,
                            [
                                {
                                    "txid": str(p.get("txid") or "").lower(),
                                    "vout": int(p.get("vout") or 0),
                                    "address": p.get("address"),
                                    "value": int(p.get("value") or 0),
                                    "spent": True,
                                    "spent_pending": True,
                                    "spent_txid": p.get("spent_txid") or "",
                                    "spent_height": 0,
                                    "spent_outputs": p.get("spent_outputs") or [],
                                    "spent_coinjoin": bool(p.get("spent_coinjoin")),
                                    "status": p.get("status") or {},
                                }
                                for p in pending
                            ],
                            state.cache_dir,
                        )
                    except Exception:
                        pass
        finally:
            try:
                client.close()
            except Exception:
                pass


def _eigener_client_kurz(state):
    import core.chain_sources as chain_sources

    werte = state.env().values()
    try:
        return chain_sources._try_own_fulcrum_client(state.args_namespace(), werte)
    except Exception:
        return None


# Singleton für den Server-Prozess
_WATCH: WalletWatchService | None = None
_WATCH_LOCK = threading.Lock()


def get_watch_service() -> WalletWatchService:
    global _WATCH
    with _WATCH_LOCK:
        if _WATCH is None:
            _WATCH = WalletWatchService()
        return _WATCH


def starte_wallet_watch(state, *, on_log=None) -> bool:
    return get_watch_service().start(state, on_log=on_log)


def stoppe_wallet_watch() -> None:
    get_watch_service().stop()


def restart_wallet_watch(state, *, on_log=None) -> bool:
    """Watch nach Electrs-Config-Wechsel neu aufbauen (Host/Port/TLS)."""
    return get_watch_service().restart(state, on_log=on_log)


def wallet_watch_status() -> dict[str, Any]:
    return get_watch_service().status()


def subscribe_addresses(addrs: list[str], xpub: str) -> bool:
    """Lookahead-Adressen beim laufenden Wallet-Watch nachabonnieren."""
    return get_watch_service().subscribe_addresses(addrs, xpub)
