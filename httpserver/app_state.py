"""AppState und Managed-Konstanten/-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports / bestehende
``from server import AppState``-Aufrufe.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path
from types import SimpleNamespace

import labels
import main
from core.bitcoind_rpc import rpc_credentials_from_env
from core.config import EnvFile, WalletEntry, read_wallets
from core.jobs import JobRegistry, ScanQueue
from core import source as source_mod

LOGGER = logging.getLogger("satsage.server")

# Plattformen, die Node- und Indexer-Adressen per Prozess-Env vorgeben und
# deren Datenquellen-Felder deshalb in der UI gesperrt sind.
_NODE_MANAGED = frozenset(("start9", "umbrel"))
# Alle Modi, in denen SatSage nicht allein über die eigene .env konfiguriert wird.
_MANAGED_MODI = frozenset(("specter", "start9", "umbrel"))
# Anzeigename je Modus für Hinweise und Fehlermeldungen.
_MANAGED_PLATTFORM = {"start9": "Start9", "umbrel": "Umbrel", "specter": "Specter"}


def _managed_by_from_env(explicit: str | None, env_path: Path) -> str | None:
    if explicit in _MANAGED_MODI:
        return explicit
    try:
        values = EnvFile.load(env_path).values()
    except (OSError, UnicodeError):
        values = {}
    managed = str(
        os.environ.get("SATSAGE_MANAGED_BY") or values.get("SATSAGE_MANAGED_BY", "")
    ).strip().lower()
    if managed in _NODE_MANAGED:
        return managed
    flag = os.environ.get("SATSAGE_START9")
    if flag is None:
        flag = values.get("SATSAGE_START9", "")
    if str(flag).strip().lower() in ("1", "true", "yes", "ja", "on"):
        return "start9"
    return "specter" if explicit == "specter" else None


def _managed_mode(state: AppState) -> bool:
    return state.managed_by in _MANAGED_MODI

class AppState:
    """Gemeinsamer Zustand aller Anfragen."""

    def __init__(self, env_path: Path, cache_dir: Path,
                 immutable_cache_dir: Path, sanctions_dir: Path | None = None,
                 label_dir: Path | None = None, managed_by: str | None = None):
        self.env_path = env_path
        # Vor dem ersten Laufzeit-Schreiben: vorgefundene .env rotieren.
        try:
            from core.config import rotate_env_backups_at_start

            sicherung = rotate_env_backups_at_start(self.env_path)
            if sicherung is not None:
                meldung = ".env in .env.backup[0-9] gesichert."
                print(meldung, flush=True)
                LOGGER.info("%s (%s)", meldung, sicherung.name)
        except OSError as exc:
            LOGGER.warning("env-backup Rotation fehlgeschlagen: %s", exc)
        from server import _pruefe_env_modus

        _pruefe_env_modus(self.env_path)
        self.cache_dir = cache_dir
        self.immutable_cache_dir = immutable_cache_dir
        self.sanctions_dir = sanctions_dir
        self.label_dir = label_dir or labels.LABEL_CACHE_DIR
        # Börsen-CSV-Reports (Klarname Ein-/Auszahlung) neben dem App-Verzeichnis.
        from core import exchange_reports as boerse_mod
        from core.paths import app_dir as _app_dir

        self.exchange_reports_dir = Path(_app_dir()) / "exchange_reports"
        boerse_mod.setze_verzeichnis(self.exchange_reports_dir)
        # None bedeutet eigenständige Desktop-GUI; der Plugin-Einstieg setzt
        # dieses Merkmal ausdrücklich, nicht über eine fremde .env.
        self.managed_by = _managed_by_from_env(managed_by, env_path)
        # Beschriftet wird tief in der Auswertung — einmal hier gesetzt, gilt
        # das Verzeichnis für alle Aufrufe dieses Laufs.
        labels.setze_verzeichnis(self.label_dir)
        self.token = secrets.token_urlsafe(24)
        # Opaque Sessions liegen nur im Prozessspeicher; der dauerhafte
        # Geheimnisbestand ist ausschließlich der Passwort-Hash im Volume.
        self.sessions: dict[str, float] = {}
        self._login_failures: dict[str, list[float]] = {}
        self._auth_lock = threading.Lock()
        # File-Key für .env.gobbledigook nur RAM (core.env_scramble Session).
        self.env_scramble_unlocked = False
        try:
            env0 = EnvFile.load(self.env_path)
            env_vals = env0.values()
            self.env_scramble_unlocked = not bool(getattr(env0, "scramble_locked", False))
        except Exception:
            env_vals = {}
            self.env_scramble_unlocked = True
        from server import _max_parallel_jobs

        self.max_parallel_jobs = _max_parallel_jobs(env_values=env_vals)
        self.jobs = JobRegistry(max_parallel_heavy=self.max_parallel_jobs)
        self.scan_queue = ScanQueue(self.jobs)
        self.header_job_id: str | None = None
        self.wallet_sync_job_id: str | None = None
        # Letzter Quellen-Check (dicts) — fuer /api/config ohne erneute Probe.
        self.sources_last: list[dict] | None = None
        #: monotonic: nächster erlaubter Header-Tip-Check (Cooldown-Spam).
        self.header_vorab_naechstes: float = 0.0
        self._lock = threading.Lock()
        self._wallet_ctx = None
        self._entries: list[WalletEntry] = []
        # Nächste Empfangsadresse je Wallet — sofort beim Wechsel, ohne Netz.
        self.empfang_cache: dict[str, dict] = {}
        # Wiederverwendeter Electrs-Client nur für Empfangs-QR (eigen oder öffentlich).
        self._empfang_fulcrum = None
        self._empfang_public_fulcrum = None
        self._empfang_fulcrum_lock = threading.Lock()
        # Öffentliches Electrum: pro Serverstart neu fragen (keine Dauer-.env).
        source_mod.setze_oeffentliche_electrum_session(False)
        self._streiche_dauerhafte_oeffentliche_electrum()
        self.reload()

    def _streiche_dauerhafte_oeffentliche_electrum(self) -> None:
        """
        Altes ``OEFFENTLICHE_ELECTRUM=1`` aus der ``.env`` nehmen.

        Die Web-GUI speichert die Freigabe nur sitzungsweise; sonst bliebe
        „Privatsphäre gering“ nach Neustart still freigegeben.
        """
        try:
            env = EnvFile.load(self.env_path)
        except OSError:
            return
        if not (env.values().get("OEFFENTLICHE_ELECTRUM") or "").strip():
            return
        env.apply({"OEFFENTLICHE_ELECTRUM": None})
        try:
            env.save()
            LOGGER.info(
                "OEFFENTLICHE_ELECTRUM aus .env entfernt "
                "(Opt-in gilt pro Serverstart)."
            )
        except OSError as exc:
            LOGGER.warning(
                "OEFFENTLICHE_ELECTRUM konnte nicht aus .env entfernt werden: %s",
                exc,
            )

    def set_managed_by(self, value: str | None) -> None:
        """Setzt die Herkunft der Konfiguration für diesen Serverlauf."""
        self.managed_by = _managed_by_from_env(value, self.env_path)

    # -- Konfiguration ------------------------------------------------------

    def env(self) -> EnvFile:
        env = EnvFile.load(self.env_path)
        if self.managed_by in _NODE_MANAGED:
            # Daemon env from the platform (StartOS bridges, Umbrel compose)
            # is process env, not .env — promote it into runtime_values without
            # overriding a value the user set in their own .env.
            for key in (
                "BITCOIND_HOST",
                "ELECTRS_HOST",
                "NODE_IP",
                "RPCHOST",
                "BITCOIN_RPC_HOST",
                "RPCPORT",
                "RPCUSER",
                "RPCPASSWORD",
                "RPC_SSL",
                "RPC_COOKIE_FILE",
                "FULCRUM_HOST",
                "FULCRUM_PORT",
                "FULCRUM_SSL",
                "SATSAGE_ELECTRUM_INDEXER",
                "MEMPOOL_URL",
                "LLM_BASE_URL",
                "LLM_ANBIETER",
                "LLM_MODELL",
            ):
                proc = (os.environ.get(key) or "").strip()
                if proc and key not in env.values():
                    env.runtime_values[key] = proc
            values = env.values()
            # Prefer explicit FULCRUM_* from the platform (StartOS daemon or the
            # Umbrel electrs dependency). Only fall back to ELECTRS_HOST when
            # FULCRUM_HOST is empty.
            if not (values.get("FULCRUM_HOST") or "").strip():
                bridge = (values.get("ELECTRS_HOST") or "electrs").strip()
                if bridge:
                    env.runtime_values["FULCRUM_HOST"] = bridge
            if not (values.get("NODE_IP") or values.get("RPCHOST") or "").strip():
                bridge = (values.get("BITCOIND_HOST") or "bitcoind").strip()
                if bridge:
                    env.runtime_values["NODE_IP"] = bridge
            # StartOS mounts bitcoind's cookie read-only, Umbrel passes RPC
            # credentials as compose env. Keep them runtime-only; never write
            # them into the user's .env file.
            cookie_user, cookie_password = rpc_credentials_from_env(values)
            if cookie_user and not (values.get("RPCUSER") or "").strip():
                env.runtime_values["RPCUSER"] = cookie_user
            if cookie_password and not (values.get("RPCPASSWORD") or "").strip():
                env.runtime_values["RPCPASSWORD"] = cookie_password
        elif self.managed_by not in _MANAGED_MODI:
            # Desktop: lokaler bitcoind → UTXO-Slot (still); Lookup nur wenn leer.
            from httpserver.local_core import _apply_local_core_runtime

            _apply_local_core_runtime(env)
        return env

    def reload(self) -> None:
        """Liest die .env neu und baut den WalletContext auf."""
        with self._lock:
            env = self.env()
            main.set_chain_network(env.values().get("NETWORK"))
            self._entries = read_wallets(env)
            self._wallet_ctx = self._build_context(self._entries)
            # UTXO-/Resolution-Cache → Mapping: sonst resolve_address je
            # ungeseedeter Adresse MAX_TRACE_ADDRESS_SEARCH Ableitungen
            # (Herkunftsliste mit 30+ UTXOs: Sekunden).
            if self._wallet_ctx is not None:
                schluessel = [
                    e.analyse_schluessel for e in self._entries if e.is_valid()
                ]
                try:
                    main.seed_wallet_addresses_from_utxo_cache(
                        self._wallet_ctx, schluessel, self.cache_dir,
                    )
                except Exception:
                    pass
                try:
                    main.seed_wallet_addresses_from_resolution_cache(
                        self._wallet_ctx, schluessel,
                    )
                except Exception:
                    pass
            # Empfangs-QR neu ableiten (Indizes/Adressen können sich geändert haben).
            self.empfang_cache.clear()
            with getattr(self, "_empfang_fulcrum_lock", threading.Lock()):
                alt = getattr(self, "_empfang_fulcrum", None)
                alt_pub = getattr(self, "_empfang_public_fulcrum", None)
                self._empfang_fulcrum = None
                self._empfang_public_fulcrum = None
            for client in (alt, alt_pub):
                if client is None:
                    continue
                try:
                    client.close()
                except Exception:
                    pass

    @staticmethod
    def _build_context(entries: list[WalletEntry]):
        # Single-Sig wie Multisig. Der Stack führt seine Wallets über einen
        # Zeichenketten-Schlüssel: bei Single-Sig der XPUB, bei Multisig der
        # Deskriptor. Aus beiden lassen sich Adressen ableiten — mehr braucht
        # er nicht zu wissen. Die *einzelnen* Cosigner dürfen dagegen nie
        # hinein, sonst gälten sie als eigene, leere Wallets.
        gueltig = [e for e in entries if e.is_valid()]
        if not gueltig:
            return None
        return main.build_wallet_context(
            [e.analyse_schluessel for e in gueltig],
            wallet_names=[e.display_name for e in gueltig],
            max_addresses_per_xpub=[e.max_addresses for e in gueltig],
            script_types=[e.script_type for e in gueltig],
        )

    @property
    def entries(self) -> list[WalletEntry]:
        with self._lock:
            return list(self._entries)

    @property
    def analyse_entries(self) -> list[WalletEntry]:
        """
        Die Wallets, für die sich Adressen ableiten lassen.
        Ausgeschlossen bleibt nur, was der Deskriptor-Parser nicht lesen kann
        (etwa aggregierte Taproot-Schlüssel) — dort gäbe es keine Adressen,
        und ein Eintrag ohne Adressen sähe im Bestand aus wie ein leeres
        Wallet.
        """
        return [e for e in self.entries if e.is_valid()]

    @property
    def unlesbare_entries(self) -> list[WalletEntry]:
        """Konfiguriert, aber nicht ableitbar — muss gesagt werden."""
        return [e for e in self.entries if not e.is_valid()]

    @property
    def multisig_entries(self) -> list[WalletEntry]:
        return [e for e in self.entries if e.is_multisig]

    @property
    def wallet_ctx(self):
        with self._lock:
            return self._wallet_ctx

    # -- Datenquelle --------------------------------------------------------

    def args_namespace(self) -> SimpleNamespace:
        """
        Baut das argparse-ähnliche Objekt, das die bestehenden Funktionen in
        main erwarten. So bleiben deren Signaturen unverändert.
        """
        entries = self.analyse_entries
        return SimpleNamespace(
            xpubs=[e.analyse_schluessel for e in entries],
            wallet_names=[e.display_name for e in entries],
            script_types=[e.script_type for e in entries],
            max_addresses_per_xpub=[e.max_addresses for e in entries],
            max_addresses=main.DEFAULT_MAX_ADDRESSES,
            cache_dir=str(self.cache_dir),
            immutable_cache_dir=str(self.immutable_cache_dir),
            rpc_only=False,
            bip158=False,
            bip158_start=None,
            rescan=False,
            no_verbose=True,
            cli=False,
            txid=None,
            address=None,
            utxo=None,
            top_utxos=10,
            rpchost=None,
            rpcport=None,
            rpcuser=None,
            rpcpass=None,
            fulcrum_host=None,
            fulcrum_port=None,
            fulcrum_no_ssl=(
                str(self.env().values().get("FULCRUM_SSL", "true")).strip().lower()
                in ("0", "false", "no", "off")
            ),
            oeffentliche_electrum=source_mod.oeffentliche_electrum_session_aktiv(),
        )

