#!/usr/bin/env python3
"""Passwort setzen, ändern, löschen in der echten Oberfläche.

Läuft nur gegen einen Wegwerf-Server aus diesem Modul. Ein Attach an eine
laufende Sitzung würde dort die ``.env`` anfassen.

Drei Modi, weil der Fehler nur ohne Scramble sichtbar war:

- desktop: Hash und scrambled ``.env`` entstehen zusammen
- specter: erstes Setzen ohne aktuelles Passwort, ``.env`` bleibt Klartext
- umbrel: Bootstrap-Hash gilt schon, Ändern verlangt ihn, ``.env`` bleibt Klartext
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS_EINS = "flow-pass-eins"
PASS_ZWEI = "flow-pass-zwei"
UMBREL_BOOT = "umbrel-flow-pass"


def _spawn(modus: str):
    import server

    tmp = tempfile.TemporaryDirectory(prefix=f"satsage-passwort-{modus}-")
    wurzel = Path(tmp.name)
    zeilen = [
        "UI_LANG=de",
        "OEFFENTLICHE_ELECTRUM=0",
        "SATSAGE_PRICE_HISTORY_OPT_IN=0",
    ]
    managed = None
    if modus == "specter":
        zeilen.append("SATSAGE_MANAGED_BY=specter")
        managed = "specter"
    elif modus == "umbrel":
        zeilen.append("SATSAGE_MANAGED_BY=umbrel")
        managed = "umbrel"
    elif modus != "desktop":
        raise ValueError(modus)
    env = wurzel / ".env"
    env.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    for name in ("utxo_cache", "immutable_cache", "sanctioned_cache"):
        (wurzel / name).mkdir()
    vorher = os.environ.get("SATSAGE_BOOTSTRAP_PASSWORD")
    try:
        if modus == "umbrel":
            os.environ["SATSAGE_BOOTSTRAP_PASSWORD"] = UMBREL_BOOT
        state = server.AppState(
            env,
            wurzel / "utxo_cache",
            wurzel / "immutable_cache",
            sanctions_dir=wurzel / "sanctioned_cache",
            managed_by=managed,
        )
        if modus == "umbrel":
            server._seed_managed_password(state)
        eingebettet = server.starte_im_hintergrund(state, port=0)
    finally:
        if modus == "umbrel":
            if vorher is None:
                os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)
            else:
                os.environ["SATSAGE_BOOTSTRAP_PASSWORD"] = vorher
    return tmp, eingebettet


def _oeffne(page, url: str, modus: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(500)
    login = page.locator("#login-form")
    if login.count() and login.first.is_visible():
        if modus != "umbrel":
            raise RuntimeError(f"{modus} zeigt die Anmeldung, obwohl noch kein Passwort gilt")
        page.locator("#password").fill(UMBREL_BOOT)
        page.locator("#login-form button[type=submit]").click()
        page.locator("#app").wait_for(state="visible", timeout=15_000)
    for sel in (
        "#einrichtung-onchain-ok",
        "#einrichtung-spaeter",
        "#einrichtung-weiter",
        "#privatsphaere-ok",
        "#oeffentliche-electrum-nein",
    ):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible(timeout=300):
                loc.first.click(timeout=1500)
                page.wait_for_timeout(200)
        except Exception:
            pass
    if not page.locator("#app").is_visible():
        raise RuntimeError("#app nicht sichtbar")
    # Die Nav ist höher als das Fenster. Ein DOM-Klick trifft den Listener
    # auch dann, wenn Playwright den Knopf als außerhalb sieht.
    page.evaluate(
        """() => {
          const el = document.querySelector(
            'button.nav-eintrag[data-ansicht="einstellungen"]'
          );
          if (!el) throw new Error('Einstellungen-Knopf fehlt');
          el.click();
        }"""
    )
    karte = page.locator("#karte-app-passwort")
    karte.wait_for(state="visible", timeout=8000)
    karte.scroll_into_view_if_needed()


def _gesetzt(page) -> bool:
    text = page.locator("#app-passwort-zusatz").inner_text().strip()
    return "gesetzt" in text and "nicht gesetzt" not in text


def _warte_gesetzt(page, gesetzt: bool) -> None:
    page.wait_for_function(
        """(soll) => {
          const z = document.querySelector('#app-passwort-zusatz');
          const a = document.querySelector('#app-passwort-aktuell');
          if (!z || !a) return false;
          const text = z.textContent || '';
          const an = text.includes('gesetzt') && !text.includes('nicht gesetzt');
          return soll ? (an && !a.disabled) : (!an && a.disabled);
        }""",
        arg=gesetzt,
        timeout=10_000,
    )


def _klick_und_meldung(page, knopf: str) -> str:
    page.evaluate(
        """() => {
          const el = document.querySelector('#app-passwort-meldung');
          if (el) el.textContent = '';
        }"""
    )
    page.locator(knopf).evaluate("el => el.click()")
    page.wait_for_function(
        """() => {
          const el = document.querySelector('#app-passwort-meldung');
          if (!el || el.hidden) return false;
          const t = el.textContent || '';
          if (!t.trim()) return false;
          return !t.includes('Speichere') && !t.includes('Saving')
            && !t.includes('wird entfernt') && !t.includes('Removing');
        }""",
        timeout=15_000,
    )
    return page.locator("#app-passwort-meldung").inner_text().strip()


def _fuellen(page, neu: str, aktuell: str | None) -> None:
    page.evaluate(
        """({ neu, aktuell }) => {
          const setze = (id, wert) => {
            const el = document.getElementById(id);
            if (!el) throw new Error(id);
            el.value = wert;
            el.dispatchEvent(new Event('input', { bubbles: true }));
          };
          setze('app-passwort-neu', neu);
          setze('app-passwort-neu2', neu);
          if (aktuell !== null) setze('app-passwort-aktuell', aktuell);
        }""",
        {"neu": neu, "aktuell": aktuell},
    )


def _config(page) -> dict:
    return page.evaluate(
        """async () => {
          const r = await fetch('/api/config', {credentials: 'same-origin'});
          const j = await r.json();
          const sc = j.env_scramble || {};
          return {
            status: r.status,
            password_set: Boolean(j.password_set),
            allowed: Boolean(sc.allowed),
            active: Boolean(sc.active),
          };
        }"""
    )


def _zyklus(page, url: str, modus: str) -> None:
    page.on("dialog", lambda dialog: dialog.dismiss())
    _oeffne(page, url, modus)
    if modus == "desktop":
        # Einmal über alle Ansichten. Specter und Umbrel wiederholen das nicht.
        from webgui_i18n_check import pruefe_sprachen

        pruefe_sprachen(page)
    if modus == "umbrel":
        _warte_gesetzt(page, True)
        _fuellen(page, PASS_ZWEI, None)
        text = _klick_und_meldung(page, "#app-passwort-setzen")
        if "eingeben" not in text or "ist falsch" in text:
            raise RuntimeError(
                f"Umbrel ohne aktuelles Passwort: {text!r}"
            )
        _fuellen(page, PASS_ZWEI, UMBREL_BOOT)
    else:
        _warte_gesetzt(page, False)
        _fuellen(page, PASS_EINS, None)
        text = _klick_und_meldung(page, "#app-passwort-setzen")
        if "gespeichert" not in text or "ist falsch" in text or "nicht gesetzt" in text:
            raise RuntimeError(f"{modus} erstes Setzen: {text!r}")
        _warte_gesetzt(page, True)
        _fuellen(page, "flow-pass-leer", None)
        text = _klick_und_meldung(page, "#app-passwort-setzen")
        if "eingeben" not in text or "ist falsch" in text:
            raise RuntimeError(
                f"{modus} zweites Setzen ohne aktuelles Passwort: {text!r}"
            )
        _fuellen(page, PASS_ZWEI, PASS_EINS)
    text = _klick_und_meldung(page, "#app-passwort-setzen")
    if "gespeichert" not in text or "ist falsch" in text:
        raise RuntimeError(f"{modus} Ändern: {text!r}")
    _warte_gesetzt(page, True)
    stand = _config(page)
    if stand["status"] != 200 or not stand["password_set"]:
        raise RuntimeError(f"{modus} Config nach Ändern: {stand}")
    if modus == "desktop":
        if not stand["allowed"] or not stand["active"]:
            raise RuntimeError(f"Desktop scramble: {stand}")
    elif stand["allowed"] or stand["active"]:
        raise RuntimeError(f"{modus} darf nicht scramblen: {stand}")
    page.evaluate(
        """(wert) => {
          const el = document.getElementById('app-passwort-aktuell');
          el.value = wert;
          el.dispatchEvent(new Event('input', { bubbles: true }));
        }""",
        PASS_ZWEI,
    )
    text = _klick_und_meldung(page, "#app-passwort-entfernen")
    if "entfernt" not in text or "ist falsch" in text:
        raise RuntimeError(f"{modus} Löschen: {text!r}")
    _warte_gesetzt(page, False)
    stand = _config(page)
    if stand["status"] != 200 or stand["password_set"] or stand["active"]:
        raise RuntimeError(f"{modus} Config nach Löschen: {stand}")


def lauf_passwort_zyklen(*, headless: bool = True, channel: str | None = None) -> dict:
    """Setzen, Ändern, Löschen für desktop, specter und umbrel."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return {
            "ok": False,
            "schritte": [{
                "schritt": "passwort_playwright",
                "ok": False,
                "fehler": f"Playwright fehlt: {exc}",
            }],
        }

    schritte: list[dict] = []
    ok = True
    holds: list[tuple] = []
    launch: dict = {"headless": headless}
    if channel:
        launch["channel"] = channel
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch)
            for modus in ("desktop", "specter", "umbrel"):
                tmp, emb = _spawn(modus)
                holds.append((tmp, emb))
                eintrag = {"schritt": f"passwort_{modus}", "ok": True}
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    locale="de-DE",
                )
                page = context.new_page()
                try:
                    _zyklus(page, emb.url, modus)
                    eintrag["detail"] = "setzen, ändern, löschen"
                except Exception as exc:
                    ok = False
                    eintrag["ok"] = False
                    eintrag["fehler"] = str(exc)
                schritte.append(eintrag)
                context.close()
                try:
                    emb.stop()
                except Exception:
                    pass
            browser.close()
    except Exception as exc:
        ok = False
        schritte.append({
            "schritt": "passwort_playwright",
            "ok": False,
            "fehler": str(exc),
        })
    finally:
        for tmp, emb in holds:
            try:
                emb.stop()
            except Exception:
                pass
            try:
                tmp.cleanup()
            except Exception:
                pass
    return {"ok": ok, "schritte": schritte}


if __name__ == "__main__":
    bericht = lauf_passwort_zyklen(headless=True)
    for schritt in bericht["schritte"]:
        mark = "OK" if schritt.get("ok") else "FAIL"
        print(f"{mark} {schritt.get('schritt')}: {schritt.get('detail') or schritt.get('fehler')}")
    raise SystemExit(0 if bericht["ok"] else 1)
