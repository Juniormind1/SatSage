"""Katalogvollständigkeit für die Weboberfläche.

``t()`` gibt bei unbekanntem Schlüssel den Schlüssel selbst zurück, und
``applyDom`` schreibt das Ergebnis in ``textContent``. Ein fehlender
Schlüssel löscht damit den HTML-Fallback und zeigt dem Nutzer den rohen
Schlüsselnamen — in **beiden** Sprachen. Genau das ist im Sortier-Menü
der Herkunftsansicht passiert.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WEB = WURZEL / "web"

HTML_SCHLUESSEL = re.compile(
    r'data-i18n(?:-title|-placeholder|-aria-label|-html)?="([^"]+)"'
)
JS_SCHLUESSEL = re.compile(r'\bt\(\s*["\']([\w.]+)["\']')


def _katalog(code: str) -> dict:
    return json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))


class TestKataloge(unittest.TestCase):
    def setUp(self):
        self.de = _katalog("de")
        self.en = _katalog("en")

    def test_beide_sprachen_haben_dieselben_schluessel(self):
        nur_de = sorted(set(self.de) - set(self.en))
        nur_en = sorted(set(self.en) - set(self.de))
        self.assertEqual(nur_de, [], f"fehlt in en.json: {nur_de[:10]}")
        self.assertEqual(nur_en, [], f"fehlt in de.json: {nur_en[:10]}")

    def test_kein_eintrag_ist_leer(self):
        for code, katalog in (("de", self.de), ("en", self.en)):
            leer = sorted(k for k, v in katalog.items() if not str(v).strip())
            self.assertEqual(leer, [], f"{code}.json: leere Einträge {leer[:10]}")

    def test_html_schluessel_sind_uebersetzt(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        fehlend = sorted(
            k for k in set(HTML_SCHLUESSEL.findall(html))
            if k not in self.de or k not in self.en
        )
        self.assertEqual(
            fehlend, [],
            "data-i18n-Schlüssel ohne Katalogeintrag — die Oberfläche zeigt "
            f"dann den rohen Schlüssel: {fehlend}",
        )

    def test_js_schluessel_sind_uebersetzt(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        verwendet = set(JS_SCHLUESSEL.findall(js))
        # app.js prüft manche Schlüssel bewusst auf Existenz
        # (``t(k) !== k ? … : deutscher Fallback``). Solche Stellen sind
        # kein Fehler, aber der Katalog sollte sie trotzdem kennen.
        fehlend = sorted(
            k for k in verwendet if k not in self.de or k not in self.en
        )
        self.assertEqual(fehlend, [], f"t()-Schlüssel ohne Katalogeintrag: {fehlend}")


if __name__ == "__main__":
    unittest.main()
