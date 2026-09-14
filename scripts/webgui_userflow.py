#!/usr/bin/env python3
"""
Web-GUI Userflow-Testframe — fiktiver Nutzer klickt die Hauptmenüs durch.

Akzeptanz: Jede Kernansicht lädt in endlicher Zeit, ohne hängendes
„Lade aus Cache…“, ohne Token-Sperre, ohne ungefangene Page-Errors.
Erst Exit 0 = Test grün (Assistent darf freigeben).

Beispiele:
  # Isoliert (Temp-Wallets, eingebetteter Server)
  .venv/bin/python scripts/webgui_userflow.py --spawn

  # Laufender Dev-Server (Session-JSON)
  .venv/bin/python scripts/webgui_userflow.py --attach

  # Explizite URL
  .venv/bin/python scripts/webgui_userflow.py --url 'http://127.0.0.1:8730/?t=…'

Report: tmp/webgui-userflow-report.json
Protokoll: doc/testprotokoll-webgui-userflow.md
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

# Kern-Navigation (data-ansicht) — Reihenfolge = typischer Userflow
NAV_SCHRITTE = (
    ("wallet", "ansicht-wallet", ("#wallet-titel", "#adress-liste", "#wallet-leer")),
    ("trace", "ansicht-trace", ("#trace-liste",)),
    ("steuerjahr", "ansicht-steuerjahr", ("#steuer-kennzahlen", "#sa-liste", "#jahr-wahl")),
    ("sanktionen", "ansicht-sanktionen", ("#sanktions-status", "#ansicht-sanktionen")),
    ("wallets", "ansicht-wallets", ("#wallet-zeilen", "#ansicht-wallets")),
    ("einstellungen", "ansicht-einstellungen", ("#ui-lang", "#ansicht-einstellungen")),
    ("datenquellen", "ansicht-datenquellen", ("#ansicht-datenquellen",)),
)

LADE_MUSTER = (
    "Lade aus Cache",
    "loadingFromCache",
    "common.loadingFromCache",
)


def _http_json(url: str, token: str | None = None, timeout: float = 15.0) -> dict:
    headers = {}
    if token:
        headers["X-Satsage-Token"] = token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as ant:
        return json.loads(ant.read().decode("utf-8"))


def _warte_config(base: str, token: str, sekunden: float = 25.0) -> dict:
    deadline = time.time() + sekunden
    letzte = None
    while time.time() < deadline:
        try:
            return _http_json(f"{base.rstrip('/')}/api/config", token=token, timeout=6)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            letzte = exc
            time.sleep(0.35)
    raise RuntimeError(f"Server antwortet nicht auf /api/config: {letzte}")


def _spawn():
    sys.path.insert(0, str(ROOT))
    import server
    from tests.fixtures import BIP84_ZPUB, ZWEITER_ALS_XPUB

    tmp = tempfile.TemporaryDirectory(prefix="satsage-userflow-")
    wurzel = Path(tmp.name)
    env = wurzel / ".env"
    env.write_text(
        "\n".join(
            [
                "WALLET_0_NAME=UserflowA",
                f"WALLET_0_XPUB={BIP84_ZPUB}",
                "WALLET_0_MAX_ADDRESSES=6",
                "WALLET_1_NAME=UserflowB",
                f"WALLET_1_XPUB={ZWEITER_ALS_XPUB}",
                "WALLET_1_MAX_ADDRESSES=6",
                "UI_LANG=de",
                "OEFFENTLICHE_ELECTRUM=0",
                "SATSAGE_PRICE_HISTORY_OPT_IN=0",
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
    eingebettet = server.starte_im_hintergrund(state, port=0)
    return tmp, eingebettet


def _attach() -> tuple[str, str]:
    sys.path.insert(0, str(ROOT))
    from core import gui_session as gs

    pfad = ROOT / "tmp" / gs.SESSION_NAME
    if not pfad.is_file():
        raise SystemExit(
            f"Keine Session-Datei {pfad}. Server starten oder --spawn nutzen."
        )
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    url = str(daten.get("url") or "")
    token = str(daten.get("token") or "")
    if not url or not token:
        raise SystemExit("Session-Datei ohne url/token.")
    return url, token


def _dismiss_dialogs(page) -> list[str]:
    """Erste Einrichtung / On-Chain / Privacy wegklicken."""
    done: list[str] = []
    for sel in (
        "#einrichtung-onchain-ok",
        "#einrichtung-spaeter",
        "#einrichtung-weiter",
        "#privatsphaere-ok",
        "#privatsphaere-entfernen",
        "#oeffentliche-electrum-nein",
        "#oeffentliche-electrum-ok",
    ):
        try:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible(timeout=400):
                loc.first.click(timeout=2000)
                done.append(sel)
                page.wait_for_timeout(250)
        except Exception:
            pass
    return done


def _sichtbar(page, selektor: str, timeout_ms: int = 8000) -> bool:
    try:
        loc = page.locator(selektor)
        loc.first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False


def _text_enthält_lade(page, root_sel: str) -> bool:
    try:
        text = page.locator(root_sel).inner_text(timeout=2000)
    except Exception:
        return False
    return any(m in text for m in LADE_MUSTER)


def _warte_nicht_lade(page, root_sel: str, sekunden: float = 25.0) -> bool:
    """True = Lade-Text verschwunden oder nie da."""
    deadline = time.time() + sekunden
    gesehen = False
    while time.time() < deadline:
        if not _text_enthält_lade(page, root_sel):
            return True
        gesehen = True
        page.wait_for_timeout(400)
    return not gesehen


def _nav_klick(page, ansicht: str) -> None:
    btn = page.locator(f'button.nav-eintrag[data-ansicht="{ansicht}"]')
    btn.first.click(timeout=8000)
    page.wait_for_timeout(300)


def _console_collector(page) -> list[str]:
    errors: list[str] = []

    def _on(msg):
        if msg.type in ("error",):
            errors.append(msg.text)

    page.on("console", _on)
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    return errors


def run_userflow(url: str, *, headless: bool = True, timeout_s: float = 90.0) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright fehlt:\n"
            "  .venv/bin/pip install playwright && .venv/bin/playwright install chromium\n"
            f"({exc})"
        ) from exc

    schritte: list[dict] = []
    console_errors: list[str] = []
    ok = True
    start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        console_errors = _console_collector(page)

        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(600)
        dismissed = _dismiss_dialogs(page)
        page.wait_for_timeout(400)
        # App sichtbar?
        if not _sichtbar(page, "#app", 15000):
            # Token-Sperre?
            token_fehlt = page.locator("#token-fehlt")
            if token_fehlt.count() and token_fehlt.first.is_visible():
                ok = False
                schritte.append({
                    "schritt": "start",
                    "ok": False,
                    "fehler": "Token-Sperre sichtbar — URL ohne gültiges ?t=",
                })
            else:
                ok = False
                schritte.append({
                    "schritt": "start",
                    "ok": False,
                    "fehler": "#app nicht sichtbar",
                })
            browser.close()
            return _report(ok, schritte, console_errors, url, start, dismissed)

        schritte.append({
            "schritt": "start",
            "ok": True,
            "detail": f"App sichtbar, Dialoge: {dismissed or 'keine'}",
        })

        # Sprache DE (Baseline)
        try:
            de = page.locator("#lang-de")
            if de.count() and de.first.is_visible():
                de.first.click(timeout=2000)
                page.wait_for_timeout(400)
        except Exception:
            pass

        for ansicht, section_id, markers in NAV_SCHRITTE:
            if time.time() - start > timeout_s:
                ok = False
                schritte.append({
                    "schritt": ansicht,
                    "ok": False,
                    "fehler": f"Gesamt-Timeout {timeout_s}s",
                })
                break
            eintrag: dict = {"schritt": ansicht, "ok": True}
            try:
                _nav_klick(page, ansicht)
                sec = f"#{section_id}"
                if not _sichtbar(page, sec, 10000):
                    raise RuntimeError(f"{sec} nicht sichtbar nach Klick")
                # Lade-Zustand abwarten (Herkunft/Steuer können kurz laden)
                if not _warte_nicht_lade(page, sec, sekunden=30.0):
                    raise RuntimeError(
                        f"{sec} hängt an Lade-Text: "
                        + page.locator(sec).inner_text()[:120]
                    )
                # Mindestens ein Marker vorhanden (nicht zwingend sichtbar —
                # z. B. leere Liste ok)
                gefunden = False
                for m in markers:
                    if page.locator(m).count() > 0:
                        gefunden = True
                        break
                if not gefunden:
                    raise RuntimeError(f"Keine Marker {markers} in {sec}")
                # Harte Fehlermeldungen
                body = page.locator(sec).inner_text(timeout=3000)
                for bad in (
                    "Interner Serverfehler",
                    "Internal Server Error",
                    "Auswertung fehlgeschlagen",
                    "couldNotLoad",
                    "Token fehlt",
                ):
                    if bad in body:
                        raise RuntimeError(f"Fehlermeldung in Ansicht: {bad}")
                eintrag["detail"] = f"{sec} ok, text_len={len(body)}"
            except Exception as exc:
                ok = False
                eintrag["ok"] = False
                eintrag["fehler"] = str(exc)
            schritte.append(eintrag)

        # DE → EN → DE (Sprache)
        try:
            en = page.locator("#lang-en")
            de = page.locator("#lang-de")
            if en.count() and en.first.is_visible():
                en.first.click(timeout=2000)
                page.wait_for_timeout(800)
                lang = page.evaluate("() => document.documentElement.lang || ''")
                if lang not in ("en", "de"):
                    # currentLang via i18n
                    lang = page.evaluate(
                        "() => (window.SatSageI18n && window.SatSageI18n.currentLang"
                        " && window.SatSageI18n.currentLang()) || ''"
                    )
                if lang != "en":
                    raise RuntimeError(f"nach EN-Klick lang={lang!r}")
                de.first.click(timeout=2000)
                page.wait_for_timeout(600)
                schritte.append({"schritt": "sprache_en_de", "ok": True, "detail": "EN↔DE"})
            else:
                schritte.append({
                    "schritt": "sprache_en_de",
                    "ok": True,
                    "detail": "übersprungen (kein #lang-en)",
                })
        except Exception as exc:
            ok = False
            schritte.append({
                "schritt": "sprache_en_de",
                "ok": False,
                "fehler": str(exc),
            })

        # Steuerjahr: Report-Knopf existiert (kein Crash-Klick ohne Auswahl)
        try:
            _nav_klick(page, "steuerjahr")
            page.wait_for_timeout(500)
            html_btn = page.locator("#sa-html")
            if html_btn.count():
                # Ohne Auswahl → Warnung, kein Crash
                html_btn.first.click(timeout=3000)
                page.wait_for_timeout(400)
                schritte.append({
                    "schritt": "steuer_report_ohne_auswahl",
                    "ok": True,
                    "detail": "Klick #sa-html ohne Auswahl",
                })
            else:
                schritte.append({
                    "schritt": "steuer_report_ohne_auswahl",
                    "ok": True,
                    "detail": "kein #sa-html",
                })
        except Exception as exc:
            ok = False
            schritte.append({
                "schritt": "steuer_report_ohne_auswahl",
                "ok": False,
                "fehler": str(exc),
            })

        # Page-Errors (nur schwere). CSP-Hinweis zum Theme-Boot-Script in
        # index.html ist bekannt und blockiert den Userflow nicht.
        def _console_schwer(text: str) -> bool:
            t = text.lower()
            if "favicon" in t or "net::" in t:
                return False
            if "content security policy" in t and "inline script" in t:
                return False
            if "pageerror:" in t:
                return True
            if "uncaught" in t or "typeerror" in t or "referenceerror" in t:
                return True
            return False

        schwere = [e for e in console_errors if _console_schwer(e)]
        if schwere:
            ok = False
            schritte.append({
                "schritt": "console",
                "ok": False,
                "fehler": "; ".join(schwere[:5]),
            })
        else:
            schritte.append({
                "schritt": "console",
                "ok": True,
                "detail": f"{len(console_errors)} console msgs (ok)",
            })

        browser.close()

    return _report(ok, schritte, console_errors, url, start, [])


def _report(
    ok: bool,
    schritte: list[dict],
    console_errors: list[str],
    url: str,
    start: float,
    dismissed: list[str],
) -> dict:
    return {
        "ok": ok,
        "schema": 1,
        "name": "webgui-userflow",
        "url": url.split("?t=")[0] + ("?t=…" if "?t=" in url else ""),
        "dauer_s": round(time.time() - start, 2),
        "ts": datetime.now(timezone.utc).isoformat(),
        "schritte": schritte,
        "console_errors": console_errors[:30],
        "dismissed": dismissed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SatSage Web-GUI Userflow-Test")
    parser.add_argument("--url", help="GUI-URL inkl. ?t=Token")
    parser.add_argument("--spawn", action="store_true", help="Isolierter Temp-Server")
    parser.add_argument("--attach", action="store_true", help="Laufende Session-Datei")
    parser.add_argument("--headed", action="store_true", help="Browser sichtbar")
    parser.add_argument("--timeout", type=float, default=120.0, help="Gesamt-Timeout s")
    parser.add_argument(
        "--report",
        type=Path,
        help="Report-JSON (Default: tmp/webgui-userflow-report.json)",
    )
    args = parser.parse_args(argv)

    tmp_hold = None
    url = args.url
    if args.spawn or (not url and not args.attach):
        if not url:
            tmp_hold, emb = _spawn()
            url = emb.url
            print(f"Spawn: {url.split('?t=')[0]}?t=… port={emb.port}", flush=True)
            time.sleep(0.8)
            try:
                base = url.split("?")[0].rstrip("/")
                tok = url.split("t=", 1)[-1].split("&")[0]
                _warte_config(base, tok)
            except Exception as exc:
                print(f"WARN config: {exc}", flush=True)
    elif args.attach or not url:
        url, _tok = _attach()
        print(f"Attach: {url.split('?t=')[0]}?t=…", flush=True)

    assert url
    print("Userflow start…", flush=True)
    report = run_userflow(url, headless=not args.headed, timeout_s=args.timeout)

    out = args.report or (ROOT / "tmp" / "webgui-userflow-report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print()
    print("=" * 60)
    print("USERFLOW", "OK" if report["ok"] else "FAIL", f"({report['dauer_s']}s)")
    print("=" * 60)
    for s in report["schritte"]:
        mark = "✓" if s.get("ok") else "✗"
        extra = s.get("detail") or s.get("fehler") or ""
        print(f"  {mark} {s.get('schritt')}: {extra}")
    print(f"Report: {out}")
    print()

    if tmp_hold is not None:
        # Server lebt bis Prozessende — bei spawn absichtlich am Ende freigeben
        pass

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
