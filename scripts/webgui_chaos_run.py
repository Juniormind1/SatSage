#!/usr/bin/env python3
"""
Web-GUI Chaos-/Stabilitäts-Runner.

Führt das Protokoll aus doc/testprotokoll-webgui-stabilitaet.md
abschnittweise automatisiert aus (Zufallsklicks via Harness-JS).

Beispiele:
  .venv/bin/python scripts/webgui_chaos_run.py --spawn --rounds 200 --seed 42
  .venv/bin/python scripts/webgui_chaos_run.py --url 'http://127.0.0.1:8730/?t=…'

Exit 0 = keine vom Harness gesammelten Errors, sonst 1.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = Path(__file__).resolve().parent / "webgui_chaos_harness.js"


def _http_json(url: str, token: str | None = None, timeout: float = 10.0) -> dict:
    headers = {}
    if token:
        headers["X-Satsage-Token"] = token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as ant:
        return json.loads(ant.read().decode("utf-8"))


def _warte_config(base: str, token: str, sekunden: float = 20.0) -> dict:
    deadline = time.time() + sekunden
    letzte = None
    while time.time() < deadline:
        try:
            return _http_json(f"{base}/api/config", token=token, timeout=5)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            letzte = exc
            time.sleep(0.4)
    raise RuntimeError(f"Server antwortet nicht auf /api/config: {letzte}")


def _spawn_server(port: int = 0):
    """Temp-.env + eingebetteter Server (kein Produktions-Cache)."""
    sys.path.insert(0, str(ROOT))
    import server
    from tests.fixtures import BIP84_ZPUB, ZWEITER_ALS_XPUB

    tmp = tempfile.TemporaryDirectory(prefix="satsage-chaos-")
    wurzel = Path(tmp.name)
    env = wurzel / ".env"
    env.write_text(
        "\n".join(
            [
                f"WALLET_0_NAME=ChaosA",
                f"WALLET_0_XPUB={BIP84_ZPUB}",
                f"WALLET_0_MAX_ADDRESSES=4",
                f"WALLET_1_NAME=ChaosB",
                f"WALLET_1_XPUB={ZWEITER_ALS_XPUB}",
                f"WALLET_1_MAX_ADDRESSES=4",
                "UI_LANG=en",
                "OEFFENTLICHE_ELECTRUM=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cache = wurzel / "utxo_cache"
    cache.mkdir()
    immutable = wurzel / "immutable_cache"
    immutable.mkdir()
    sanktionen = wurzel / "sanctioned_cache"
    sanktionen.mkdir()

    state = server.AppState(env, cache, immutable, sanctions_dir=sanktionen)
    eingebettet = server.starte_im_hintergrund(state, port=port or 0)
    return tmp, eingebettet


def _playwright_run(
    url: str,
    rounds: int,
    seed: int,
    destructive: bool,
    delay_ms: int,
    text_ratio: float,
    submit_ratio: float,
) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright fehlt. Installieren:\n"
            "  .venv/bin/pip install playwright && .venv/bin/playwright install chromium\n"
            "Oder Harness manuell in der Browser-Konsole laden "
            f"({HARNESS}).\n"
            f"({exc})"
        ) from exc

    harness_src = HARNESS.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(800)
        # Dialoge grob wegklicken
        for sel in (
            "#einrichtung-onchain-ok",
            "#einrichtung-spaeter",
            "#privatsphaere-ok",
            "#oeffentliche-electrum-nein",
        ):
            try:
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=1000)
            except Exception:
                pass
        # CSP (default-src 'self') blockiert add_script_tag(content=…);
        # page.evaluate läuft über CDP und umgeht die Inline-Script-Sperre.
        page.evaluate(harness_src)
        ergebnis = page.evaluate(
            """async ({ rounds, seed, destructive, delayMs, textRatio, submitRatio }) => {
                if (!window.__SATSAGE_CHAOS__) {
                    return { ok: false, error: 'harness missing' };
                }
                return await window.__SATSAGE_CHAOS__.run({
                    rounds, seed, destructive, delayMs, textRatio, submitRatio
                });
            }""",
            {
                "rounds": rounds,
                "seed": seed,
                "destructive": destructive,
                "delayMs": delay_ms,
                "textRatio": text_ratio,
                "submitRatio": submit_ratio,
            },
        )
        browser.close()
    return ergebnis if isinstance(ergebnis, dict) else {"ok": False, "error": str(ergebnis)}


def _manual_hinweis(
    url: str,
    rounds: int,
    seed: int,
    destructive: bool,
    text_ratio: float = 0.28,
    submit_ratio: float = 0.35,
) -> int:
    print("Playwright nicht genutzt / nicht installiert.")
    print("Manueller Chaos-Lauf (Klicks + wilde Texte):")
    print(f"  1. Öffne {url}")
    print(f"  2. DevTools-Konsole: Inhalt von {HARNESS} einfügen")
    print(
        "  3. Ausführen:\n"
        f"     await __SATSAGE_CHAOS__.run({{ rounds: {rounds}, seed: {seed}, "
        f"destructive: {str(destructive).lower()}, "
        f"textRatio: {text_ratio}, submitRatio: {submit_ratio} }})"
    )
    print("  4. Report: __SATSAGE_CHAOS__.report()")
    print()
    print("Protokoll: doc/testprotokoll-webgui-stabilitaet.md")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SatSage Web-GUI Chaos-Stabilitätstest")
    parser.add_argument("--url", help="Vollständige GUI-URL inkl. ?t=Token")
    parser.add_argument(
        "--spawn",
        action="store_true",
        help="Eigenen Temp-Server starten (isolierte .env, 2 Test-Wallets)",
    )
    parser.add_argument("--port", type=int, default=0, help="Port für --spawn (0=frei)")
    parser.add_argument("--rounds", type=int, default=200, help="Zufalls-Aktionen")
    parser.add_argument("--seed", type=int, default=None, help="RNG-Seed (Repro)")
    parser.add_argument(
        "--destructive",
        action="store_true",
        help="Danger-Zone/Löschen erlauben (nur Wegwerf-Env!)",
    )
    parser.add_argument("--delay-ms", type=int, default=40, help="Pause zwischen Aktionen")
    parser.add_argument(
        "--text-ratio",
        type=float,
        default=0.28,
        help="Anteil Aktionen = wilde Texteingabe (0..1, Default 0.28)",
    )
    parser.add_argument(
        "--submit-ratio",
        type=float,
        default=0.35,
        help="Nach Text: Wahrscheinlichkeit Enter/Submit (0..1)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Report-JSON-Pfad (Default: tmp/webgui-chaos-report-….json)",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Nur Anleitung ausgeben, kein Playwright",
    )
    args = parser.parse_args(argv)

    seed = args.seed if args.seed is not None else int(time.time()) % 1_000_000_000
    tmp_ctx = None
    eingebettet = None
    url = args.url

    try:
        if args.spawn:
            tmp_ctx, eingebettet = _spawn_server(port=args.port)
            url = eingebettet.url
            print(f"Spawn-Server: {url}")
            base = f"http://127.0.0.1:{eingebettet.port}"
            _warte_config(base, eingebettet.token)
        if not url:
            parser.error("Entweder --url oder --spawn angeben")

        if args.manual:
            return _manual_hinweis(
                url,
                args.rounds,
                seed,
                args.destructive,
                args.text_ratio,
                args.submit_ratio,
            )

        print(
            f"Chaos: rounds={args.rounds} seed={seed} "
            f"destructive={args.destructive} delay_ms={args.delay_ms} "
            f"text_ratio={args.text_ratio} submit_ratio={args.submit_ratio}"
        )
        try:
            ergebnis = _playwright_run(
                url,
                rounds=args.rounds,
                seed=seed,
                destructive=args.destructive,
                delay_ms=args.delay_ms,
                text_ratio=args.text_ratio,
                submit_ratio=args.submit_ratio,
            )
        except SystemExit as exc:
            if "Playwright fehlt" in str(exc):
                return _manual_hinweis(
                    url,
                    args.rounds,
                    seed,
                    args.destructive,
                    args.text_ratio,
                    args.submit_ratio,
                )
            raise

        report_pfad = args.report
        if report_pfad is None:
            out_dir = ROOT / "tmp"
            out_dir.mkdir(exist_ok=True)
            stempel = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            report_pfad = out_dir / f"webgui-chaos-report-{stempel}.json"

        payload = {
            "protocol": "doc/testprotokoll-webgui-stabilitaet.md",
            "url": url.split("?t=")[0] + "?t=…",
            "rounds": args.rounds,
            "seed": seed,
            "destructive": args.destructive,
            "text_ratio": args.text_ratio,
            "submit_ratio": args.submit_ratio,
            "result": ergebnis,
        }
        report_pfad.parent.mkdir(parents=True, exist_ok=True)
        report_pfad.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Report: {report_pfad}")
        print(f"ok={ergebnis.get('ok')} errors={ergebnis.get('errorCount', '?')}")
        for err in (ergebnis.get("errors") or [])[:12]:
            print(f"  - [{err.get('art')}] {err.get('detail')}")

        return 0 if ergebnis.get("ok") else 1
    finally:
        if eingebettet is not None:
            try:
                eingebettet.stop()
            except Exception:
                pass
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
