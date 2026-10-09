"""Sprache EN → DE und Suche nach nicht übersetzten Texten in der offenen GUI."""

from __future__ import annotations

_ANSICHTEN = (
    "wallet",
    "trace",
    "steuerjahr",
    "sanktionen",
    "tools",
    "wallets",
    "einstellungen",
    "datenquellen",
)

# Im Seitenkontext. Liefert {roh: [...], fremd: [...]} für die aktuelle Sprache.
_SCAN = """
async () => {
  const de = await (await fetch('/locales/de.json', {cache: 'no-cache'})).json();
  const en = await (await fetch('/locales/en.json', {cache: 'no-cache'})).json();
  const lang = (window.SatSageI18n && window.SatSageI18n.currentLang()) || '';
  const hier = lang === 'en' ? en : de;
  const dort = lang === 'en' ? de : en;
  const roh = [];
  const fremd = [];
  const gesehen = new Set();
  const merke = (liste, eintrag) => {
    const id = eintrag.art + '|' + eintrag.key + '|' + (eintrag.text || '');
    if (gesehen.has(id) || liste.length >= 12) return;
    gesehen.add(id);
    liste.push(eintrag);
  };
  const norm = (wert) => String(wert || '').replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim();
  const imLog = (el) => Boolean(el.closest && el.closest('#log-text'));
  const pruefeText = (el, art, key, text) => {
    const gezeigt = norm(text);
    if (!gezeigt || !key) return;
    if (gezeigt === key) {
      merke(roh, {art, key, text: gezeigt.slice(0, 80)});
      return;
    }
    const erwartet = norm(hier[key]);
    const anders = norm(dort[key]);
    if (!erwartet || !anders || erwartet === anders) return;
    if (gezeigt === anders && gezeigt !== erwartet) {
      merke(fremd, {art, key, text: gezeigt.slice(0, 80), lang});
    }
  };
  const wurzel = document.getElementById('app') || document.body;
  wurzel.querySelectorAll('[data-i18n]').forEach((el) => {
    if (imLog(el)) return;
    const key = el.getAttribute('data-i18n');
    if (el.childElementCount) {
      if (norm(el.textContent) === key) pruefeText(el, 'data-i18n', key, key);
      return;
    }
    pruefeText(el, 'data-i18n', key, el.textContent);
  });
  for (const [attr, art] of [
    ['data-i18n-title', 'title'],
    ['data-i18n-placeholder', 'placeholder'],
    ['data-i18n-aria-label', 'aria-label'],
  ]) {
    wurzel.querySelectorAll('[' + attr + ']').forEach((el) => {
      if (imLog(el)) return;
      pruefeText(el, art, el.getAttribute(attr), el.getAttribute(art));
    });
  }
  const keyRe = /^[a-z][a-z0-9]*(\\.[a-zA-Z0-9_]+)+$/;
  const walker = document.createTreeWalker(wurzel, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const knoten = walker.currentNode;
    const el = knoten.parentElement;
    if (!el || imLog(el) || el.closest('script, style')) continue;
    const text = norm(knoten.nodeValue);
    if (!keyRe.test(text)) continue;
    if (Object.prototype.hasOwnProperty.call(de, text) || Object.prototype.hasOwnProperty.call(en, text)) {
      merke(roh, {art: 'sichtbar', key: text, text});
    }
  }
  return {lang, roh, fremd};
}
"""


def _klick(page, auswahl: str) -> None:
    page.evaluate(
        """(auswahl) => {
          const el = document.querySelector(auswahl);
          if (!el) throw new Error('fehlt: ' + auswahl);
          el.click();
        }""",
        auswahl,
    )


def _sprache(page, code: str) -> None:
    knopf = "#lang-en" if code == "en" else "#lang-de"
    _klick(page, knopf)
    page.wait_for_function(
        """(code) => window.SatSageI18n && window.SatSageI18n.currentLang() === code""",
        arg=code,
        timeout=8_000,
    )
    page.wait_for_timeout(350)
    for ansicht in _ANSICHTEN:
        page.evaluate(
            """(name) => {
              const el = document.querySelector(
                'button.nav-eintrag[data-ansicht="' + name + '"]'
              );
              if (el && !el.hidden) el.click();
            }""",
            ansicht,
        )
        page.wait_for_timeout(150)


def _scan(page) -> dict:
    return page.evaluate(_SCAN)


def pruefe_sprachen(page) -> dict:
    """EN, zurück nach DE. Roh-Schlüssel und Texte der anderen Sprache sind ein Fehler.

    Das Log bleibt ausgenommen: seine Zeilen sind absichtlich deutsch.
    """
    funde: list[dict] = []
    for code in ("en", "de"):
        _sprache(page, code)
        bericht = _scan(page)
        if bericht.get("lang") != code:
            raise RuntimeError(f"Sprache ist {bericht.get('lang')!r}, erwartet {code}")
        for art, liste in (("roh", bericht.get("roh") or []), ("fremd", bericht.get("fremd") or [])):
            for eintrag in liste:
                eintrag["sprache"] = code
                eintrag["klasse"] = art
                funde.append(eintrag)
    if funde:
        zeilen = []
        for eintrag in funde[:12]:
            zeilen.append(
                f"{eintrag['sprache']}/{eintrag['klasse']} {eintrag.get('key')} "
                f"({eintrag.get('art')}): {eintrag.get('text')}"
            )
        reste = len(funde) - len(zeilen)
        if reste > 0:
            zeilen.append(f"… und {reste} weitere")
        raise RuntimeError("nicht übersetzt: " + "; ".join(zeilen))
    return {"ok": True, "detail": "EN→DE, keine Roh-Schlüssel, keine fremde Sprache"}
