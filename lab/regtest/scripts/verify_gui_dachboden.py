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

Voraussetzung: bitcoind und Electrs laufen. Der Prüfer startet selbst eine
SatSage-Sitzung wie Userflow und Chaos (``tmp/satsage-gui-session.json``),
mit einer Kopie der Lab-Env. ``--url`` hängt sich an eine schon laufende
Sitzung. Weder Docker noch die Präsentations-GUI.

macOS und Windows: installiertes Chrome (``channel=chrome``).
Linux: gebündeltes Chromium, ohne ``channel``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
ENV_LAB = HERE / ".data" / ".regtest.env"
WALLET = "lab-dachprobe"
NAME = "Dachprobe"
SATS = 100_000

_SCHLUESSEL = re.compile(
    r"\b(?:xpub|tpub|ypub|upub|zpub|vpub|xprv|tprv|yprv|uprv|zprv|vprv)[1-9A-HJ-NP-Za-km-z]{20,}\b"
)


def _ruhig(text: str) -> str:
    return _SCHLUESSEL.sub("[schluessel]", text or "")


_SPAWN_KEYS = {
    "NETWORK": "regtest",
    "BIP158_P2P": "0",
    "OEFFENTLICHE_ELECTRUM": "0",
    "TOR_AUTOSTART": "0",
    "WALLETS_BEIM_START_AKTUALISIEREN": "0",
    "UI_LANG": "de",
}


def _env_text(roh: str) -> str:
    gesehen: set[str] = set()
    zeilen: list[str] = []
    for line in roh.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in line:
            zeilen.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in _SPAWN_KEYS:
            zeilen.append(f"{key}={_SPAWN_KEYS[key]}")
            gesehen.add(key)
        else:
            zeilen.append(line)
    for key, wert in _SPAWN_KEYS.items():
        if key not in gesehen:
            zeilen.append(f"{key}={wert}")
    return "\n".join(zeilen) + "\n"


def _warte_api(url: str) -> None:
    basis, _, query = url.partition("?")
    token = ""
    for teil in query.split("&"):
        if teil.startswith("t="):
            token = teil[2:]
            break
    ziel = basis.rstrip("/") + "/api/config"
    req = urllib.request.Request(ziel, headers={"X-Satsage-Token": token})
    ende = time.monotonic() + 15
    letzte: Exception | None = None
    while time.monotonic() < ende:
        try:
            with urllib.request.urlopen(req, timeout=3) as ant:
                if ant.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            letzte = exc
        time.sleep(0.3)
    raise RuntimeError(f"Server antwortet nicht auf /api/config: {letzte}")


def _spawn_lab():
    """Wegwerf-Server auf einer Kopie der Lab-Env. Session wie Userflow."""
    if not ENV_LAB.is_file():
        raise SystemExit(
            f"Lab-Env fehlt: {ENV_LAB}\n"
            "Einmalig: cd lab/regtest && ./scripts/start.sh && ./scripts/generate_scenarios.py"
        )
    sys.path.insert(0, str(REPO))
    from infra_check import pinne_lab_env

    gehalten = tempfile.TemporaryDirectory(prefix="satsage-dachboden-")
    wurzel = Path(gehalten.name)
    env = wurzel / ".env"
    env.write_text(_env_text(ENV_LAB.read_text(encoding="utf-8")), encoding="utf-8")
    for name in ("utxo_cache", "immutable_cache", "sanctioned_cache"):
        (wurzel / name).mkdir()
    pinne_lab_env(env)
    import server
    import main as satsage_main
    from core import gui_session as gs

    pinne_lab_env(env)
    satsage_main.set_chain_network("regtest")
    state = server.AppState(
        env,
        wurzel / "utxo_cache",
        wurzel / "immutable_cache",
        sanctions_dir=wurzel / "sanctioned_cache",
    )
    eingebettet = server.starte_im_hintergrund(state, port=0, header_vorab=False)
    from core import wallet_watch

    wallet_watch.starte_wallet_watch(
        state, on_log=lambda text: print(f"  {text}", flush=True),
    )
    session_pfad = REPO / "tmp" / gs.SESSION_NAME
    alt = session_pfad.read_bytes() if session_pfad.is_file() else None
    gs.schreibe_session(
        gs.bau_payload(
            url=eingebettet.url,
            token=eingebettet.token,
            port=eingebettet.port,
            bind=eingebettet.bind,
            env_path=str(env),
        ),
        pfad=session_pfad,
        stdout_zeile=False,
    )
    _warte_api(eingebettet.url)
    return gehalten, eingebettet, session_pfad, alt


def _beende_sitzung(gehalten, eingebettet, pfad: Path | None, alt: bytes | None) -> None:
    try:
        from core import wallet_watch

        wallet_watch.stoppe_wallet_watch()
    except Exception:
        pass
    _session_zurueck(pfad, alt)
    if eingebettet is not None:
        eingebettet.stop()
    if gehalten is not None:
        gehalten.cleanup()


def _session_zurueck(pfad: Path | None, alt: bytes | None) -> None:
    if pfad is None:
        return
    if alt is None:
        try:
            pfad.unlink(missing_ok=True)
        except TypeError:
            if pfad.exists():
                pfad.unlink()
        return
    pfad.write_bytes(alt)


def _browser(p, headed: bool):
    sys.path.insert(0, str(REPO / "scripts"))
    from webgui_test_ready import playwright_kanal

    kwargs: dict = {"headless": not headed}
    kanal = playwright_kanal(None)
    if kanal:
        kwargs["channel"] = kanal
    return p.chromium.launch(**kwargs)


def _dialoge_weg(page) -> None:
    """Erst der On-Chain-Hinweis, danach die Einrichtung. Der Hinweis
    erscheint erst nach /api/config und liegt über der Sprachwahl."""
    for overlay, knopf in (
        ("#onchain-hinweis", "#einrichtung-onchain-ok"),
        ("#einrichtung", "#einrichtung-spaeter"),
        ("#privatsphaere-warnung", "#privatsphaere-ok"),
        ("#oeffentliche-electrum-warnung", "#oeffentliche-electrum-nein"),
    ):
        try:
            page.locator(overlay).wait_for(state="visible", timeout=4000)
        except Exception:
            continue
        page.evaluate(
            """(knopf) => {
              const el = document.querySelector(knopf);
              if (el) el.click();
            }""",
            knopf,
        )
        try:
            page.locator(overlay).wait_for(state="hidden", timeout=8000)
        except Exception:
            pass


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


def _warte_einen(page, orte: tuple[str, ...], sekunden: float) -> str:
    erlaubt = json.dumps(list(orte))
    page.wait_for_function(
        f"(name) => {erlaubt}.includes(({_ORT_JS})(name))",
        arg=NAME,
        timeout=int(sekunden * 1000),
    )
    return page.evaluate(_ORT_JS, NAME)


def _zuerst_leeren(page, rpc) -> None:
    """Rest vom vorigen Lauf: erst sweepen, dann den leeren Dachboden erwarten."""
    print("  Dachprobe hat noch Bestand — zuerst sweepen")
    _oeffne_wallet_oben(page)
    _sweep(rpc)
    _warte_ort(page, "dachboden", 90)
    if not _seite_lebt(page):
        raise RuntimeError("Reload beim Leeren vor dem Szenario.")


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
    parser.add_argument(
        "--url",
        default=None,
        help="Laufende Sitzung. Ohne Angabe startet der Prüfer eine Lab-Sitzung.",
    )
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from infra_check import brauche

    code = brauche("bitcoind", "electrs")
    if code is not None:
        return code

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright fehlt.\n"
            "  macOS: .venv/bin/python3.14 -m pip install playwright"
            "  (Browser: installiertes Chrome)\n"
            "  Linux: .venv/bin/python -m playwright install chromium\n"
            "  Windows: py -3 -m pip install playwright  (Browser: installiertes Chrome)",
            file=sys.stderr,
        )
        return 4

    gehalten = None
    eingebettet = None
    session_pfad = None
    session_alt = None
    try:
        if args.url:
            url = args.url.strip()
            if "t=" not in url:
                print("URL ohne Token.", file=sys.stderr)
                return 2
        else:
            gehalten, eingebettet, session_pfad, session_alt = _spawn_lab()
            url = eingebettet.url
            print(f"Spawn: port={eingebettet.port}", flush=True)
    except SystemExit as exc:
        print(_ruhig(str(exc)), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Sitzung: {_ruhig(str(exc))}", file=sys.stderr)
        _beende_sitzung(gehalten, eingebettet, session_pfad, session_alt)
        return 2

    try:
        rpc, xpub = _core()
    except Exception as exc:
        print(f"Core-Wallet: {_ruhig(str(exc))}", file=sys.stderr)
        _beende_sitzung(gehalten, eingebettet, session_pfad, session_alt)
        return 3

    try:
        with sync_playwright() as p:
            browser = _browser(p, args.headed)
            page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.locator("#app").wait_for(state="visible", timeout=30000)
            _dialoge_weg(page)
            # DE, damit die Gruppe „Dachboden“ heißt. Die Prüfung nutzt die Klasse.
            # DOM-Klick: ein noch offener Hinweis fängt den Playwright-Klick ab.
            page.evaluate(
                """() => {
                  const de = document.querySelector('#lang-de');
                  if (de) de.click();
                }"""
            )
            # Vor dem ersten Sweep setzen, sonst wirkt ein Reload-Check wie ein Fehlalarm.
            page.evaluate("() => { window.__dachbodenSeite = 1; }")
            schon = page.evaluate(_ORT_JS, NAME)
            if schon == "liste":
                _zuerst_leeren(page, rpc)
            elif schon == "weg":
                _lege_an(page, xpub)
                # Ein frischer Import scannt den Core-Bestand. Sats vom vorigen
                # Lauf liegen dann in der normalen Liste, nicht im Dachboden.
                if _warte_einen(page, ("dachboden", "liste"), 180) == "liste":
                    _zuerst_leeren(page, rpc)
            else:
                _warte_ort(page, "dachboden", 30)
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
    finally:
        _beende_sitzung(gehalten, eingebettet, session_pfad, session_alt)

    print("PASS: Dachboden → Liste → Dachboden")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
