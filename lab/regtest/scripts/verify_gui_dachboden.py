#!/usr/bin/env python3
"""Regtest-Playwright: leeres Wallet, Dachboden, Empfang, Sweep.

Szenario ``dachboden``:

1. Wallet ``Dachprobe`` anlegen (Core-Wallet nur lokal, in die GUI nur der XPUB)
   und Bestand scannen.
2. Es steht unter Dachboden, nicht in der normalen Walletliste.
3. Sats von lab-faucet an die Empfangsadresse, ein Block.
4. Ohne Seiten-Reload wandert es in die normale Liste.
5. Sweep zurück an lab-faucet, ein Block.
6. Ohne Seiten-Reload steht es wieder unter Dachboden.

Voraussetzung: bitcoind + Electrs und eine laufende Lab-GUI
(``lab/regtest/.data/gui-session.json`` oder ``--url``).
Der Prüfer startet weder Docker noch den Server.

macOS/Linux: gebündeltes Chromium, ohne ``channel``.
Windows: ``channel=chrome``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
SESSION_LAB = HERE / ".data" / "gui-session.json"
SESSION_REPO = REPO / "tmp" / "satsage-gui-session.json"
WALLET = "lab-dachprobe"
NAME = "Dachprobe"
SATS = 100_000

_SCHLUESSEL = re.compile(
    r"\b(?:xpub|tpub|ypub|upub|zpub|vpub|xprv|tprv|yprv|uprv|zprv|vprv)[1-9A-HJ-NP-Za-km-z]{20,}\b"
)


def _ruhig(text: str) -> str:
    return _SCHLUESSEL.sub("[schluessel]", text or "")


def _session(url_arg: str | None) -> tuple[str, str]:
    if url_arg:
        url = url_arg.strip()
    elif SESSION_LAB.is_file():
        url = str(json.loads(SESSION_LAB.read_text(encoding="utf-8"))["url"])
    elif SESSION_REPO.is_file():
        url = str(json.loads(SESSION_REPO.read_text(encoding="utf-8"))["url"])
    else:
        raise SystemExit(
            "Keine Lab-GUI-Session. Zuerst die GUI gegen die Lab-Env starten.\n"
            "  lab/regtest/.data/gui-session.json fehlt.\n"
            "Windows: lab\\regtest\\scripts\\win\\start_gui.ps1\n"
            "macOS/Linux: lab/regtest/scripts/start_praesentation.sh"
        )
    token = ""
    if "t=" in url:
        token = url.split("t=", 1)[1].split("&", 1)[0]
    if not token:
        raise SystemExit("URL ohne Token.")
    return url, token


def _browser(p, headed: bool):
    kwargs: dict = {"headless": not headed}
    if sys.platform == "win32":
        kwargs["channel"] = "chrome"
    return p.chromium.launch(**kwargs)


def _core():
    from generate_scenarios import (
        Rpc,
        choose_native,
        load_or_create,
        public_receive_key,
    )

    rpc = Rpc(choose_native(False))
    load_or_create(rpc, "lab-faucet")
    load_or_create(rpc, WALLET)
    xpub, _script = public_receive_key(rpc, WALLET)
    return rpc, xpub


def _mine(rpc, blocks: int = 1) -> None:
    try:
        rpc.call("setmocktime", "0")
    except RuntimeError as exc:
        print(f"  setmocktime: {_ruhig(str(exc))}", file=sys.stderr)
    ziel = rpc.call("getnewaddress", "", "bech32", wallet="lab-faucet")
    rpc.call("generatetoaddress", str(blocks), ziel, wallet="lab-faucet")


def _sweep(rpc) -> None:
    try:
        rpc.call("rescanblockchain", "0", wallet=WALLET)
    except RuntimeError as exc:
        print(f"  rescan {WALLET}: {_ruhig(str(exc))}", file=sys.stderr)
    offen = rpc.json("listunspent", "0", "9999999", wallet=WALLET)
    if not offen:
        raise RuntimeError(f"{WALLET} hat nichts zu sweepen.")
    ziel = rpc.call("getnewaddress", "", "bech32", wallet="lab-faucet")
    try:
        rpc.call("sendall", json.dumps([ziel]), wallet=WALLET)
    except RuntimeError:
        betrag = sum(float(u["amount"]) for u in offen)
        # Grobe Fee, damit sendtoaddress auf Regtest durchgeht.
        netto = round(betrag - 0.0001, 8)
        if netto <= 0:
            raise
        rpc.call("sendtoaddress", ziel, f"{netto:.8f}", wallet=WALLET)
    _mine(rpc, 1)


_ORT_JS = """
(name) => {
  const nav = document.querySelector('#wallet-nav');
  if (!nav) return 'weg';
  const treffer = [...nav.querySelectorAll('button[data-wallet-id]')].filter((knopf) => {
    const titel = knopf.querySelector('.nav-name');
    return titel && titel.textContent.trim() === name;
  });
  if (!treffer.length) return 'weg';
  if (treffer.every((knopf) => knopf.closest('.nav-dachboden-liste'))) return 'dachboden';
  if (treffer.every((knopf) => !knopf.closest('.nav-dachboden'))) return 'liste';
  return 'gemischt';
}
"""


def _warte_ort(page, ort: str, sekunden: float) -> None:
    page.wait_for_function(
        f"(name) => ({_ORT_JS})(name) === {json.dumps(ort)}",
        arg=NAME,
        timeout=int(sekunden * 1000),
    )


def _seite_lebt(page) -> bool:
    return page.evaluate("() => window.__dachbodenSeite === 1")


def _oeffne_wallet(page) -> None:
    # Die Seitenleiste ist höher als das Fenster, der Körper scrollt nicht.
    # locator.click meldet den Kopf als „outside of the viewport“.
    page.evaluate(
        """(name) => {
          const kopf = document.querySelector('.nav-dachboden-kopf');
          if (!kopf) throw new Error('Dachboden fehlt');
          if (kopf.getAttribute('aria-expanded') !== 'true') kopf.click();
          const liste = document.querySelector('.nav-dachboden-liste');
          const knopf = [...(liste ? liste.querySelectorAll('button[data-wallet-id]') : [])]
            .find((el) => {
              const titel = el.querySelector('.nav-name');
              return titel && titel.textContent.trim() === name;
            });
          if (!knopf) throw new Error('Wallet im Dachboden fehlt');
          knopf.click();
        }""",
        NAME,
    )
    page.locator("#ansicht-wallet").wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        """() => {
          const adresse = document.querySelector('#empfang-adresse');
          return adresse && (adresse.textContent || '').trim().length > 20;
        }""",
        timeout=60000,
    )
    page.locator("#empfang-lab-senden").wait_for(state="visible", timeout=10000)


def _lege_an(page, xpub: str) -> None:
    page.evaluate(
        """() => {
          const knopf = document.querySelector('[data-ansicht="wallets"]');
          if (knopf) knopf.click();
        }"""
    )
    page.locator("#ansicht-wallets").wait_for(state="visible", timeout=15000)
    page.locator("#neuer-name").fill(NAME)
    page.locator("#neuer-xpub").fill(xpub)
    page.locator("#hinzufuegen").click()
    page.wait_for_function(
        """() => {
          const scan = document.querySelector('#wallet-scan-wahl');
          const warn = document.querySelector('#privatsphaere-warnung');
          const scanOffen = scan && !scan.hidden;
          const warnOffen = warn && !warn.hidden;
          return scanOffen || warnOffen;
        }""",
        timeout=30000,
    )
    warnung = page.locator("#privatsphaere-warnung")
    if warnung.count() and warnung.is_visible():
        page.locator("#privatsphaere-ok").click()
        page.locator("#wallet-scan-wahl").wait_for(state="visible", timeout=20000)
    page.locator("#wallet-scan-utxo").click()


def _oeffne_wallet_oben(page) -> None:
    page.evaluate(
        """(name) => {
          const knopf = [...document.querySelectorAll('#wallet-nav button[data-wallet-id]')]
            .find((el) => {
              const titel = el.querySelector('.nav-name');
              return titel && titel.textContent.trim() === name
                && !el.closest('.nav-dachboden');
            });
          if (!knopf) throw new Error('Wallet in der normalen Liste fehlt');
          knopf.click();
        }""",
        NAME,
    )
    page.locator("#ansicht-wallet").wait_for(state="visible", timeout=15000)


def main() -> int:
    parser = argparse.ArgumentParser(description="Playwright-Szenario Dachboden")
    parser.add_argument("--url", default=None)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from infra_check import brauche

    code = brauche("bitcoind", "electrs")
    if code is not None:
        return code

    try:
        url, _token = _session(args.url)
    except SystemExit as exc:
        print(_ruhig(str(exc)), file=sys.stderr)
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright fehlt.\n"
            "  macOS/Linux: .venv/bin/python -m playwright install chromium\n"
            "  Windows: py -3 -m pip install playwright  (Browser: installiertes Chrome)",
            file=sys.stderr,
        )
        return 4

    try:
        rpc, xpub = _core()
    except Exception as exc:
        print(f"Core-Wallet: {_ruhig(str(exc))}", file=sys.stderr)
        return 3

    try:
        with sync_playwright() as p:
            browser = _browser(p, args.headed)
            page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.locator("#app").wait_for(state="visible", timeout=30000)
            # DE, damit die Gruppe „Dachboden“ heißt. Die Prüfung nutzt die Klasse.
            de = page.locator("#lang-de")
            if de.count():
                de.click()
            schon = page.evaluate(_ORT_JS, NAME)
            if schon == "liste":
                print("  Dachprobe hat noch Bestand — zuerst sweepen")
                _oeffne_wallet_oben(page)
                _sweep(rpc)
                _warte_ort(page, "dachboden", 90)
                if not _seite_lebt(page):
                    raise RuntimeError("Reload beim Leeren vor dem Szenario.")
            elif schon == "weg":
                _lege_an(page, xpub)
                _warte_ort(page, "dachboden", 180)
            else:
                _warte_ort(page, "dachboden", 30)
            page.evaluate("() => { window.__dachbodenSeite = 1; }")
            print("  im Dachboden")

            _oeffne_wallet(page)
            with page.expect_response(
                lambda antwort: "faucet-senden" in antwort.url and antwort.status == 200,
                timeout=40000,
            ):
                page.evaluate(
                    """() => {
                      const knopf = document.querySelector('#empfang-lab-ok');
                      if (!knopf) throw new Error('Faucet-Knopf fehlt');
                      knopf.click();
                    }"""
                )
            _mine(rpc, 1)
            _warte_ort(page, "liste", 90)
            if not _seite_lebt(page):
                raise RuntimeError("Reload, als das Wallet die normale Liste betrat.")
            print("  in der normalen Liste")

            _sweep(rpc)
            _warte_ort(page, "dachboden", 90)
            if not _seite_lebt(page):
                raise RuntimeError("Reload, als das Wallet zurück in den Dachboden zog.")
            print("  wieder im Dachboden")
            browser.close()
    except Exception as exc:
        print(f"FAIL: {_ruhig(str(exc))}", file=sys.stderr)
        return 10

    print("PASS: Dachboden → Liste → Dachboden")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
