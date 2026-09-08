#!/usr/bin/env python3
"""Oeffnet die Lab-GUI im Playwright-Browser und prueft, dass die App sichtbar ist."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
SESSION = HERE / ".data" / "gui-session.json"
SHOT_DIR = HERE / ".data" / "gui-verify"
DEFAULT_URL_FILE = HERE / ".data" / "gui-url.txt"


def load_url(explicit: str | None) -> tuple[str, str]:
    if explicit:
        url = explicit.strip()
        token = ""
        if "t=" in url:
            token = url.split("t=", 1)[1].split("&", 1)[0]
        return url, token
    if SESSION.is_file():
        data = json.loads(SESSION.read_text(encoding="utf-8"))
        return str(data["url"]), str(data.get("token") or "")
    if DEFAULT_URL_FILE.is_file():
        url = DEFAULT_URL_FILE.read_text(encoding="utf-8").strip()
        token = url.split("t=", 1)[1].split("&", 1)[0] if "t=" in url else ""
        return url, token
    raise SystemExit("Keine Session/URL gefunden. Zuerst start_gui.ps1.")


def api_ok(token: str, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:8730/api/config",
        headers={"X-Satsage-Token": token},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None)
    parser.add_argument("--headed", action="store_true", help="Browser-Fenster zeigen")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args()

    url, token = load_url(args.url)
    if not token and "t=" in url:
        token = url.split("t=", 1)[1].split("&", 1)[0]
    if not token:
        print("FAIL: URL ohne Token", file=sys.stderr)
        return 2

    try:
        cfg = api_ok(token)
    except Exception as exc:
        print(f"FAIL: API /api/config: {exc}", file=sys.stderr)
        return 3
    print(f"API ok: wallets={len(cfg.get('wallets') or [])} env={cfg.get('env_path')}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: playwright nicht installiert (pip install playwright)", file=sys.stderr)
        return 4

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    shot = SHOT_DIR / "gui.png"
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()
        page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        # App startet async; warte auf sichtbare App ODER Token-Dialog.
        deadline = time.time() + max(5.0, args.timeout_ms / 1000.0)
        state = "unknown"
        while time.time() < deadline:
            token_vis = page.locator("#token-fehlt").is_visible()
            app_vis = page.locator("#app").is_visible()
            if app_vis and not token_vis:
                state = "app"
                break
            if token_vis and not app_vis:
                state = "token-fehlt"
                break
            time.sleep(0.25)

        # Zusaetzlich: Nav / Wallets
        nav_ok = False
        try:
            nav_ok = page.locator("#app").is_visible() and (
                page.locator("[data-ansicht]").count() > 0
                or page.locator("nav").count() > 0
            )
        except Exception:
            nav_ok = False

        title = page.title()
        h1 = ""
        try:
            if page.locator("#token-fehlt h1").is_visible():
                h1 = page.locator("#token-fehlt h1").inner_text().strip()
            elif page.locator("h1").count():
                h1 = page.locator("h1").first.inner_text().strip()
        except Exception:
            pass

        page.screenshot(path=str(shot), full_page=True)
        browser.close()

    print(f"title={title!r}")
    print(f"state={state}")
    print(f"h1={h1!r}")
    print(f"nav_ok={nav_ok}")
    print(f"screenshot={shot}")
    if page_errors:
        print("page_errors:")
        for line in page_errors[:20]:
            print(f"  {line}")
    if console_errors:
        print("console_errors:")
        for line in console_errors[:20]:
            print(f"  {line}")

    if state == "app" and nav_ok and not page_errors:
        print("PASS: Web-GUI aufgebaut")
        return 0
    if state == "token-fehlt":
        print("FAIL: Token-Dialog sichtbar", file=sys.stderr)
        return 10
    print(f"FAIL: unerwarteter Zustand state={state} nav_ok={nav_ok}", file=sys.stderr)
    return 11


if __name__ == "__main__":
    raise SystemExit(main())
