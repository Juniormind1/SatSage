#!/usr/bin/env python3
"""
GUI-Test-Session: Token/URL zuverlässig, ohne Log-Grep.

Beispiele:
  # Isolierter Server (Temp-.env) — Standard für Assistenten/Playwright
  .venv/bin/python scripts/webgui_test_ready.py spawn --json

  # Laufenden Server nutzen (Session-Datei muss existieren und API antworten)
  .venv/bin/python scripts/webgui_test_ready.py attach --json

  # Nur URL / Token
  .venv/bin/python scripts/webgui_test_ready.py url
  .venv/bin/python scripts/webgui_test_ready.py token

  # Warten bis Session da (Server separat gestartet)
  .venv/bin/python scripts/webgui_test_ready.py wait --json

  # API-Probe
  .venv/bin/python scripts/webgui_test_ready.py config

Exit 0 = ok. JSON auf stdout bei --json (eine Zeile).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _json_out(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _http_json(url: str, token: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={"X-Satsage-Token": token},
    )
    with urllib.request.urlopen(req, timeout=timeout) as ant:
        return json.loads(ant.read().decode("utf-8"))


def cmd_spawn(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    import server
    from core import gui_session as gs
    from tests.fixtures import BIP84_ZPUB, ZWEITER_ALS_XPUB

    tmp = tempfile.TemporaryDirectory(prefix="satsage-gui-test-")
    # tmp muss bis Prozessende leben — an args hängen
    args._tmp = tmp  # noqa: SLF001
    wurzel = Path(tmp.name)
    env = wurzel / ".env"
    env.write_text(
        "\n".join(
            [
                "WALLET_0_NAME=GuiTestA",
                f"WALLET_0_XPUB={BIP84_ZPUB}",
                "WALLET_0_MAX_ADDRESSES=4",
                "WALLET_1_NAME=GuiTestB",
                f"WALLET_1_XPUB={ZWEITER_ALS_XPUB}",
                "WALLET_1_MAX_ADDRESSES=4",
                "UI_LANG=de",
                "OEFFENTLICHE_ELECTRUM=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for name in ("utxo_cache", "immutable_cache", "sanctioned_cache"):
        (wurzel / name).mkdir()

    state = server.AppState(
        env,
        wurzel / "utxo_cache",
        wurzel / "immutable_cache",
        sanctions_dir=wurzel / "sanctioned_cache",
    )
    eingebettet = server.starte_im_hintergrund(state, port=int(args.port))
    payload = gs.bau_payload(
        url=eingebettet.url,
        token=eingebettet.token,
        port=eingebettet.port,
        bind=eingebettet.bind,
        env_path=str(env),
    )
    # Feste Session-Datei im Repo-tmp (Assistenten finden sie)
    if args.session_file:
        ziel = Path(args.session_file)
    else:
        ziel = ROOT / "tmp" / gs.SESSION_NAME
    pfad = gs.schreibe_session(
        payload, pfad=ziel, stdout_zeile=not args.json
    )
    payload["_path"] = str(pfad)
    payload["_mode"] = "spawn"

    # Kurz warten bis API steht
    deadline = time.time() + 15
    while time.time() < deadline:
        if gs.session_lebt(payload):
            break
        time.sleep(0.2)
    else:
        print("Server antwortet nicht auf /api/config", file=sys.stderr)
        eingebettet.stop()
        return 1

    if args.json:
        _json_out(payload)
    else:
        print(payload["url"])
        print(f"token={payload['token']}", file=sys.stderr)
        print(f"session={pfad}", file=sys.stderr)

    if args.hold:
        print("Läuft — Strg+C beendet.", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            eingebettet.stop()
            gs.loesche_session(pfad)
        return 0

    # Ohne --hold: Session-Datei bleibt, Prozess endet — Server stirbt mit
    # (Daemon-Thread im selben Prozess). Deshalb --hold Default für spawn?
    # Für Assistenten: spawn --hold im Hintergrund, oder chaos --spawn.
    # Hier: ohne hold Server stoppen und Session löschen wäre nutzlos.
    # → spawn ohne hold lässt Server laufen indem wir hold erzwingen wenn
    #   nicht --once.
    if args.once:
        eingebettet.stop()
        gs.loesche_session(pfad)
        return 0

    # Default: blockieren, damit der Server lebt (Hintergrund-Terminal).
    print("GUI-Test-Server läuft (Strg+C stoppt).", file=sys.stderr)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        eingebettet.stop()
        gs.loesche_session(pfad)
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from core import gui_session as gs

    pfad = Path(args.session_file) if args.session_file else None
    try:
        data = gs.warte_session(
            sekunden=float(args.timeout),
            pfad=pfad,
            muss_leben=not args.stale_ok,
        )
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "Hinweis: Server mit plain-console starten oder:\n"
            "  .venv/bin/python scripts/webgui_test_ready.py spawn --json",
            file=sys.stderr,
        )
        return 1
    data["_mode"] = "attach"
    if args.json:
        _json_out(data)
    else:
        print(data["url"])
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    return cmd_attach(args)


def cmd_info(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from core import gui_session as gs

    pfad = Path(args.session_file) if args.session_file else None
    data = gs.lese_session(pfad)
    if not data:
        print("Keine Session-Datei.", file=sys.stderr)
        return 1
    data["alive"] = gs.session_lebt(data)
    if args.json:
        _json_out(data)
    else:
        print(f"url={data.get('url')}")
        print(f"port={data.get('port')}")
        print(f"alive={data['alive']}")
        print(f"path={data.get('_path')}")
    return 0 if data.get("alive") or args.stale_ok else 2


def cmd_url(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from core import gui_session as gs

    data = gs.lese_session(Path(args.session_file) if args.session_file else None)
    if not data:
        return cmd_attach(args)
    if not args.stale_ok and not gs.session_lebt(data):
        print("Session tot — attach/spawn nötig.", file=sys.stderr)
        return 2
    print(data["url"], flush=True)
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from core import gui_session as gs

    data = gs.lese_session(Path(args.session_file) if args.session_file else None)
    if not data:
        print("Keine Session.", file=sys.stderr)
        return 1
    print(data["token"], flush=True)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from core import gui_session as gs

    data = gs.lese_session(Path(args.session_file) if args.session_file else None)
    if not data:
        print("Keine Session.", file=sys.stderr)
        return 1
    base = f"http://{data.get('bind', '127.0.0.1')}:{data['port']}"
    try:
        cfg = _http_json(f"{base}/api/config", data["token"])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"API-Fehler: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _json_out(cfg)
    else:
        print(f"version={cfg.get('version')}")
        print(f"wallets={len(cfg.get('wallets') or [])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    gemein = argparse.ArgumentParser(add_help=False)
    gemein.add_argument(
        "--session-file",
        default=None,
        help="Pfad zur Session-JSON (Default: tmp/satsage-gui-session.json)",
    )
    gemein.add_argument(
        "--json", action="store_true", help="Eine JSON-Zeile auf stdout"
    )
    gemein.add_argument(
        "--stale-ok",
        action="store_true",
        help="Session-Datei auch ohne lebende API akzeptieren",
    )
    gemein.add_argument("--timeout", type=float, default=20.0)

    parser = argparse.ArgumentParser(
        description="SatSage GUI-Test-Session (Token ohne Log-Grep)",
        parents=[gemein],
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_spawn = sub.add_parser(
        "spawn", help="Temp-Server starten, Session schreiben", parents=[gemein]
    )
    p_spawn.add_argument("--port", type=int, default=0)
    p_spawn.add_argument(
        "--hold",
        action="store_true",
        help="Blockieren (Default-Verhalten ohne --once)",
    )
    p_spawn.add_argument(
        "--once",
        action="store_true",
        help="Nur Session erzeugen/prüfen und Server sofort stoppen (Smoke)",
    )
    p_spawn.set_defaults(func=cmd_spawn)

    sub.add_parser(
        "attach", help="Bestehende Session lesen + API-Check", parents=[gemein]
    ).set_defaults(func=cmd_attach)
    sub.add_parser(
        "wait", help="Warten bis Session+API bereit", parents=[gemein]
    ).set_defaults(func=cmd_wait)
    sub.add_parser(
        "info", help="Session-Datei anzeigen", parents=[gemein]
    ).set_defaults(func=cmd_info)
    sub.add_parser(
        "url", help="Nur GUI-URL drucken", parents=[gemein]
    ).set_defaults(func=cmd_url)
    sub.add_parser(
        "token", help="Nur Token drucken", parents=[gemein]
    ).set_defaults(func=cmd_token)
    sub.add_parser(
        "config", help="GET /api/config", parents=[gemein]
    ).set_defaults(func=cmd_config)

    args = parser.parse_args(argv)
    return int(args.func(args))

if __name__ == "__main__":
    raise SystemExit(main())
