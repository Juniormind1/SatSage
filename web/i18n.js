/**
 * SatSage UI-Sprache: Catalogs unter /locales/{lang}.json.
 *
 * Laden: localStorage["satsage-ui-lang"] → config.ui_lang (Server: UI_LANG,
 * sonst Accept-Language, sonst Englisch) → Browsersprache.
 * Fehlende EN-Keys fallen auf DE zurück. Kein Build-Schritt.
 */
(() => {
  const STORAGE_KEY = "satsage-ui-lang";
  const SUPPORTED = ["de", "en"];

  let lang = "de";
  let catalog = {};
  let fallbackCatalog = {};

  function normalizeLang(roh) {
    const w = String(roh || "").trim().toLowerCase();
    if (w === "en" || w.startsWith("en-")) return "en";
    if (w === "de" || w.startsWith("de-")) return "de";
    return "de";
  }

  function formatLocale() {
    return lang === "en" ? "en-US" : "de-DE";
  }

  function currentLang() {
    return lang;
  }

  // null, wenn der Nutzer noch nichts gewaehlt hat — sonst faellt initI18n
  // nie auf config.ui_lang zurueck, weil normalizeLang() alles Unbekannte zu
  // "de" macht. Genau daran war die Sprachwahl des Servers wirkungslos.
  function storedLang() {
    try {
      const roh = String(localStorage.getItem(STORAGE_KEY) || "").trim().toLowerCase();
      if (roh === "en" || roh.startsWith("en-")) return "en";
      if (roh === "de" || roh.startsWith("de-")) return "de";
      return null;
    } catch (_) {
      return null;
    }
  }

  function rememberLang(wert) {
    try {
      localStorage.setItem(STORAGE_KEY, wert);
    } catch (_) {
      /* private mode */
    }
  }

  function lookup(key) {
    if (!key) return "";
    if (Object.prototype.hasOwnProperty.call(catalog, key) && catalog[key] !== "") {
      return catalog[key];
    }
    if (
      Object.prototype.hasOwnProperty.call(fallbackCatalog, key)
      && fallbackCatalog[key] !== ""
    ) {
      return fallbackCatalog[key];
    }
    return key;
  }

  function t(key, vars) {
    let text = lookup(key);
    if (vars && typeof vars === "object") {
      for (const [name, wert] of Object.entries(vars)) {
        text = text.split(`{${name}}`).join(String(wert));
      }
    }
    return text;
  }

  function applyAttr(el, attrName, key) {
    if (!key) return;
    const wert = t(key);
    if (attrName === "text") {
      el.textContent = wert;
    } else if (attrName === "html") {
      el.innerHTML = wert;
    } else {
      el.setAttribute(attrName, wert);
    }
  }

  function applyDom(root) {
    const basis = root || document;
    basis.querySelectorAll("[data-i18n]").forEach((el) => {
      applyAttr(el, "text", el.getAttribute("data-i18n"));
    });
    basis.querySelectorAll("[data-i18n-html]").forEach((el) => {
      applyAttr(el, "html", el.getAttribute("data-i18n-html"));
    });
    basis.querySelectorAll("[data-i18n-title]").forEach((el) => {
      applyAttr(el, "title", el.getAttribute("data-i18n-title"));
    });
    basis.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      applyAttr(el, "placeholder", el.getAttribute("data-i18n-placeholder"));
    });
    basis.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
      applyAttr(el, "aria-label", el.getAttribute("data-i18n-aria-label"));
    });
  }

  async function fetchCatalog(code) {
    const antwort = await fetch(`/locales/${code}.json`, { cache: "no-cache" });
    if (!antwort.ok) {
      throw new Error(`locale ${code}: HTTP ${antwort.status}`);
    }
    return antwort.json();
  }

  async function loadCatalogs(ziel) {
    const code = normalizeLang(ziel);
    if (code === "de") {
      fallbackCatalog = await fetchCatalog("de");
      catalog = fallbackCatalog;
    } else {
      fallbackCatalog = await fetchCatalog("de");
      try {
        catalog = await fetchCatalog(code);
      } catch (_) {
        catalog = {};
      }
    }
    lang = code;
    return code;
  }

  async function setLang(ziel, opts) {
    const code = await loadCatalogs(ziel);
    rememberLang(code);
    document.documentElement.lang = code;
    applyDom(document);
    window.dispatchEvent(
      new CustomEvent("satsage:lang", { detail: { lang: code } }),
    );
    if (opts && opts.persistEnv && typeof opts.persistEnv === "function") {
      try {
        await opts.persistEnv(code);
      } catch (_) {
        /* optional */
      }
    }
    return code;
  }

  // Reihenfolge: ausdrueckliche Wahl des Nutzers (localStorage) → Antwort des
  // Servers (UI_LANG, sonst Accept-Language, sonst Englisch) → Browsersprache,
  // falls die Config nicht erreichbar war.
  async function initI18n(opts) {
    const ausConfig = opts && opts.configLang;
    const vomBrowser = String(
      (navigator.languages && navigator.languages[0]) || navigator.language || ""
    ).toLowerCase();
    const gewaehlt =
      storedLang()
      || (ausConfig ? normalizeLang(ausConfig) : null)
      || (vomBrowser.startsWith("de") ? "de" : "en");
    return setLang(gewaehlt, { persistEnv: null });
  }

  window.SatSageI18n = {
    STORAGE_KEY,
    SUPPORTED,
    t,
    applyDom,
    setLang,
    initI18n,
    formatLocale,
    currentLang,
    normalizeLang,
    rememberLang,
    storedLang,
  };
  window.t = t;
  window.formatLocale = formatLocale;
})();
