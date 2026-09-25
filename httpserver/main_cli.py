"""Splash/CLI-Bootstrap und main_cli — aus server.py extrahiert (Modularisierung).

Fassade bleibt in server.py für Tests und den dünnen ``__main__``-Einstieg.
"""

from __future__ import annotations

import argparse
import errno
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from core import gui_session as gui_session_mod
from core import single_instance as single_mod

from httpserver.splash import (
    _splash_schliessen,
    _splash_start,
    _splash_text,
    _splash_timeout_wache,
)

LOGGER = logging.getLogger("satsage.server")


def _konsole_auf_utf8() -> None:
    """
    Stellt die Ausgabe auf UTF-8 um.

    Unter Windows verwendet Python die Codepage der Umgebung, sobald die
    Ausgabe in eine Datei umgeleitet wird — Gedankenstriche und Umlaute
    lösen dann einen UnicodeEncodeError aus und der Server startet nicht.
    """
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def build_argumente() -> argparse.ArgumentParser:
    """Die Startoptionen — als Funktion, damit die Vorgaben prüfbar sind."""
    from server import DEFAULT_PORT

    parser = argparse.ArgumentParser(
        description="Lokale Web-Oberfläche für SatSage"
    )
    parser.add_argument("--bind", default=None, help="Listener-Adresse (Default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--env", default=None, help="Pfad zur .env")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--immutable-cache-dir", default=None)
    parser.add_argument("--sanctions-dir", default=None,
                        help="Verzeichnis der Sanktionslisten")
    parser.add_argument("--label-dir", default=None,
                        help="Verzeichnis der Adress-Labels")
    parser.add_argument("--no-browser", action="store_true",
                        help="Browser nicht automatisch öffnen")
    parser.add_argument(
        "--plain-console",
        action="store_true",
        help="Ohne Terminal-Menü: nur URL ausgeben und auf Strg+C warten "
             "(Tests/Automation, non-TTY)",
    )
    return parser


def _port_belegt_errno(exc: BaseException) -> bool:
    return getattr(exc, "errno", None) in (
        errno.EADDRINUSE,
        getattr(errno, "WSAEADDRINUSE", -1),
    )


def _httpd_binden(port: int, bind: str | None = None):
    """
    Bindet an host:port. Bei Belegung durch eine SatSage-Instanz:
    alten Prozess beenden und erneut binden.
    """
    from server import Handler, QuietThreadingHTTPServer, _bind_host

    host = _bind_host(bind)
    try:
        return QuietThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        if not _port_belegt_errno(exc):
            raise
        beendet = single_mod.port_freigeben_satsage(port, host=host)
        if not beendet:
            raise
        print(
            f"Port {port} war belegt — vorherige SatSage-Instanz beendet "
            f"(PID {', '.join(str(p) for p in beendet)}), starte weiter…",
            flush=True,
        )
        time.sleep(0.25)
        try:
            return QuietThreadingHTTPServer((host, port), Handler)
        except OSError as exc2:
            if _port_belegt_errno(exc2):
                # Zweiter Versuch nach kurzer Pause (TIME_WAIT)
                time.sleep(0.75)
                return QuietThreadingHTTPServer((host, port), Handler)
            raise

def _oeffne_browser_sicher(adresse: str) -> None:
    """
    Öffnet die GUI-URL ohne die Server-Konsole zu gefährden.

    Unter Windows können ``webbrowser.open`` / ``cmd start`` CTRL-Events an die
    Konsolen-Prozessgruppe senden — dann endet der Server sofort. Deshalb:
    verzögert im Daemon-Thread und auf Windows ``os.startfile`` (ShellExecute).
    """

    def _lauf() -> None:
        time.sleep(1.2)
        try:
            if sys.platform == "win32":
                os.startfile(adresse)  # noqa: S606 — lokale http://-URL
                return
            webbrowser.open(adresse)
        except Exception:
            try:
                webbrowser.open(adresse)
            except Exception:
                pass

    threading.Thread(target=_lauf, name="satsage-open-browser", daemon=True).start()


def _http_debug_log(text: str) -> None:
    """Datei-Log für Windows-Diagnose (Konsole kann Events verschlucken)."""
    try:
        pfad = Path("tmp") / "satsage-http-thread.log"
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with pfad.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {text}\n")
    except Exception:
        pass


def _http_loop_bis_strg_c(httpd) -> None:
    """
    HTTP in Daemon-Thread; Hauptthread blockiert bis Strg+C.

    Die Prozess-Lebensdauer hängt nicht an ``serve_forever``. Unter Windows
    kann die HTTP-Schleife sterben (Konsolen-CTRL / SystemExit im Thread) —
    der Hauptthread hält den Prozess und startet HTTP neu.
    """
    stop = threading.Event()
    http_thread: threading.Thread | None = None

    def _serve_once() -> None:
        _http_debug_log("serve_forever enter")
        try:
            httpd.serve_forever(poll_interval=0.5)
            _http_debug_log("serve_forever returned normally")
        except BaseException as exc:
            _http_debug_log(f"serve_forever BaseException: {exc!r}")
            if not stop.is_set() and not isinstance(exc, (SystemExit, KeyboardInterrupt)):
                LOGGER.exception("HTTP-Server-Fehler")

    def _ensure_http() -> None:
        nonlocal http_thread
        if http_thread is not None and http_thread.is_alive():
            return
        if stop.is_set():
            return
        if http_thread is not None:
            print(
                "\n  ⚠️  HTTP-Thread weg — starte neu (Strg+C beendet).",
                flush=True,
            )
            _http_debug_log("restarting http thread")
        http_thread = threading.Thread(
            target=_serve_once, name="satsage-http", daemon=True,
        )
        http_thread.start()

    _ensure_http()
    try:
        while True:
            _ensure_http()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nBeendet.", flush=True)
        _http_debug_log("KeyboardInterrupt in main keep-alive")
        stop.set()
        try:
            httpd.shutdown()
        except Exception:
            pass
        if http_thread is not None:
            http_thread.join(timeout=5.0)


def main_cli(argv=None) -> int:
    from core.terminal_steuerung import lauf_steuerung, steuerung_sinnvoll
    from server import (
        Handler,
        _bind_host,
        build_state,
        starte_header_vorab,
        starte_historie_nachzug_taeglich,
        starte_wallet_aktualisierung,
    )

    _splash_start()
    _splash_text("SatSage …")
    _konsole_auf_utf8()
    args = build_argumente().parse_args(argv)

    _splash_text("Konfiguration …")
    state = build_state(args)
    bind = _bind_host(args.bind, state=state, args=args)
    try:
        from core.i18n import init_from_env
        from core.log_i18n import install_stdout_translation

        env_datei = state.env()
        werte = env_datei.values() if hasattr(env_datei, "values") else {}
        init_from_env(werte if isinstance(werte, dict) else None)
        install_stdout_translation()
    except Exception:
        pass
    Handler.state = state
    _splash_text("Hintergrunddienste …")
    starte_header_vorab(state)
    starte_wallet_aktualisierung(state)
    try:
        from core import wallet_watch

        wallet_watch.starte_wallet_watch(
            state, on_log=lambda t: print(f"  {t}", flush=True),
        )
    except Exception as exc:
        print(f"  Wallet-Watch nicht gestartet: {exc}", flush=True)

    _splash_text("Server …")
    try:
        httpd = _httpd_binden(args.port, bind=bind)
    except OSError as exc:
        _splash_schliessen()
        if _port_belegt_errno(exc):
            name = single_mod.binary_name()
            print(
                f"Port {args.port} ist belegt ({bind}) — keine SatSage-Instanz "
                f"zum Übernehmen gefunden.\n"
                f"  Anderen Prozess beenden oder starten mit:\n"
                f"    {name} --port {args.port + 1}\n"
                f"  Belegten Port prüfen:  lsof -nP -iTCP:{args.port} -sTCP:LISTEN",
                file=sys.stderr,
                flush=True,
            )
            return 1
        raise
    adresse = f"http://{bind}:{httpd.server_address[1]}/?t={state.token}"
    # Maschinenlesbar für GUI-Tests/Assistenten (kein Log-Grep auf Token).
    session_pfad = None
    try:
        session_pfad = gui_session_mod.schreibe_session(
            gui_session_mod.bau_payload(
                url=adresse,
                token=state.token,
                port=args.port,
                bind=bind,
                env_path=str(state.env_path),
            )
        )
    except Exception:
        session_pfad = None

    # Splash bleibt bis Browser die GUI lädt (nicht schon beim Bind).
    _splash_text("Browser …")

    mit_steuerung = steuerung_sinnvoll(plain_console=bool(args.plain_console))
    if mit_steuerung:
        # HTTP robust im Hintergrund; Hauptthread = Menü (1/2/3).
        stop_http = threading.Event()
        state._http_stop_event = stop_http  # type: ignore[attr-defined]

        def _http_im_hintergrund() -> None:
            while not stop_http.is_set():
                try:
                    httpd.serve_forever(poll_interval=0.5)
                except BaseException as exc:
                    _http_debug_log(f"menu-path http: {exc!r}")
                if stop_http.is_set():
                    break
                # shutdown() kann vor stop.set() zurückkehren — kurz nachprüfen
                time.sleep(0.05)
                if stop_http.is_set():
                    break
                print(
                    "\n  ⚠️  HTTP-Thread weg — starte neu.",
                    flush=True,
                )
                time.sleep(0.5)

        threading.Thread(
            target=_http_im_hintergrund, name="satsage-webgui", daemon=True,
        ).start()
        if state.header_job_id:
            from core.i18n import t

            print(t("cli.term.blockHeaders"), flush=True)
        if not args.no_browser:
            _splash_timeout_wache(25.0)
        else:
            _splash_schliessen()
        # GUI/HTTP stehen — Historie-Nachzug erst danach (nicht im Splash).
        starte_historie_nachzug_taeglich(state)
        try:
            return lauf_steuerung(
                state,
                httpd,
                adresse,
                # Windows: Auto-Browser aus dem Menü-Modul gesteuert
                oeffne_browser_anfangs=not args.no_browser,
            )
        finally:
            stop_http.set()
            try:
                httpd.shutdown()
            except Exception:
                pass
            _splash_schliessen()
            try:
                gui_session_mod.loesche_session(session_pfad)
            except Exception:
                pass

    from core.i18n import t

    print("SatSage – know your sats")
    print(t("cli.term.webUi"))
    print(t("cli.term.configLabel", path=state.env_path))
    print(t("cli.term.utxoCache", path=state.cache_dir))
    print(t("cli.term.sanctions", path=state.sanctions_dir))
    print(t("cli.term.wallets", n=len(state.entries)))
    print()
    print("  Im Browser öffnen (Token ist enthalten):")
    print(f"    {adresse}")
    if session_pfad is not None:
        print(f"  Session-Datei : {session_pfad}")
    print()
    print(f"  Listener {bind}. Beenden mit Strg+C.")
    print("  Browser darf geschlossen werden — Server läuft hier weiter.")
    if state.header_job_id:
        print("  Block-Header ab SegWit werden im Hintergrund geladen.")
    if not args.no_browser:
        _splash_timeout_wache(25.0)
        # Auch Windows: erst nach Banner/HTTP, verzögert via os.startfile.
        _oeffne_browser_sicher(adresse)
    else:
        _splash_schliessen()
    print("  Server bereit — Anfragen werden angenommen (Strg+C beendet).", flush=True)
    # GUI erreichbar — Lücken-Nachzug nachgelagert (nicht Startpfad).
    starte_historie_nachzug_taeglich(state)
    try:
        _http_loop_bis_strg_c(httpd)
    finally:
        _splash_schliessen()
        try:
            gui_session_mod.loesche_session(session_pfad)
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
    return 0

