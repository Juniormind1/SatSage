/** Token + API-Client und zugehörige Anzeige-Helfer — aus app.js extrahiert (Modularisierung UI-Schritt 1).
 * Klassisches Script: Globals (Token, ApiFehler, api, …). Kein import/export.
 * Laden nach i18n.js / log_i18n.js, vor app.js (Format/Zustand), Views und chrome.
 */

// ---------------------------------------------------------------------------
// Token
// ---------------------------------------------------------------------------

const Token = (() => {
  const ausUrl = (new URLSearchParams(location.search).get("t") || "").trim();
  let gespeichert = "";
  try {
    if (ausUrl) {
      sessionStorage.setItem("xpq-token", ausUrl);
      // Token aus der Adresszeile entfernen: Lesezeichen/Verlauf ohne Secret.
      // Nur wenn Speichern geklappt hat — sonst bleibt ?t= fuer Reload nutzbar.
      history.replaceState(null, "", location.pathname + location.hash);
    }
    gespeichert = sessionStorage.getItem("xpq-token") || "";
  } catch (_) {
    // sessionStorage blockiert (Privatmodus, Policy): URL-Token weiter nutzen.
  }
  return ausUrl || gespeichert || "";
})();

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

class ApiFehler extends Error {
  constructor(status, meldung) {
    super(meldung);
    this.status = status;
  }
  /** 409: nichts kaputt, es fehlt nur die Zustimmung des Benutzers. */
  get brauchtBestaetigung() {
    return this.status === 409;
  }
}

async function api(pfad, { methode = "GET", daten, timeoutMs } = {}) {
  const ctrl = timeoutMs ? new AbortController() : null;
  const timer = ctrl
    ? setTimeout(() => ctrl.abort(), timeoutMs)
    : null;
  let antwort;
  try {
    antwort = await fetch(`/api${pfad}`, {
      method: methode,
      credentials: "same-origin",
      headers: {
        "X-Satsage-Token": Token,
        ...(daten !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: daten !== undefined ? JSON.stringify(daten) : undefined,
      signal: ctrl ? ctrl.signal : undefined,
    });
  } catch (fehler) {
    if (fehler && fehler.name === "AbortError") {
      throw new ApiFehler(408, t("common.timeout"));
    }
    const text = (fehler && fehler.message) || t("common.netError");
    throw new ApiFehler(0, text === "Failed to fetch" || text === "Load failed"
      ? t("common.noConnection")
      : text);
  } finally {
    if (timer) clearTimeout(timer);
  }

  let koerper = {};
  try {
    koerper = await antwort.json();
  } catch (_) {
    /* leerer Körper ist in Ordnung */
  }
  if (!antwort.ok) {
    throw new ApiFehler(
      antwort.status,
      übersetzeServerMeldung(koerper.error || `HTTP ${antwort.status}`),
    );
  }
  return koerper;
}

/** Bekannte Server-Meldungen (DE) → UI-Sprache. */
function übersetzeServerMeldung(roh) {
  const text = String(roh || "");
  if (!text) return text;
  if (/Token fehlt oder ist ungültig/i.test(text)) {
    return t("api.tokenInvalid");
  }
  return text;
}

function scriptTypLabel(value, fallback) {
  const key = `wallets.scriptType.${value}`;
  const uebersetzt = t(key);
  return uebersetzt !== key ? uebersetzt : (fallback || value || "");
}

function quelleName(quelle) {
  const key = `sources.name.${quelle.key}`;
  const uebersetzt = t(key);
  return uebersetzt !== key ? uebersetzt : quelle.name;
}

function quelleNotiz(quelle) {
  if (!quelle) return "";
  let key = `sources.note.${quelle.key}`;
  if (!quelle.configured) {
    const leer = t(`${key}.empty`);
    if (leer !== `${key}.empty`) return leer;
  }
  const text = t(key);
  if (text !== key) return text;
  return quelle.note || "";
}

function quelleDetail(quelle) {
  if (!quelle) return "";
  let d = String(quelle.detail || "");
  if (!d) return d;
  // Backend liefert deutsche Fragmente; Zahlen/Hosts bleiben stehen.
  d = d.replace(
    /(\d+)\s+Clearnet-Server in electrum_servers\.json/g,
    (_, n) => t("sources.detail.clearnetCount", { n }),
  );
  d = d.replace(
    /(\d+)\s+Server · SOCKS\s+(\S+)/g,
    (_, n, proxy) => t("sources.detail.serversSocks", { n, proxy }),
  );
  d = d.replace(
    /ab Block\s+([\d.]+)/g,
    (_, n) => t("sources.detail.fromBlock", { n }),
  );
  d = d.replace(
    /Node im LAN\s+(\S+)/g,
    (_, host) => t("sources.detail.lanNode", { host }),
  );
  d = d.replace(
    /(\d+)\s+extra Peers/g,
    (_, n) => t("sources.detail.extraPeers", { n }),
  );
  d = d
    .replace(
      /\baus — öffentliche Listen können greifen\b/g,
      t("sources.detail.p2pOff"),
    )
    .replace(/\bnicht eingetragen\b/g, t("sources.detail.notSet"))
    .replace(/\bkeine eingetragen\b/g, t("sources.detail.noneSet"))
    .replace(/\bkeine Liste\b/g, t("sources.detail.noList"))
    .replace(/\bmit TLS\b/g, t("sources.detail.withTls"))
    .replace(/\bohne TLS\b/g, t("sources.detail.withoutTls"))
    .replace(/\bDNS-Seeds\b/g, t("sources.detail.dnsSeeds"));
  return d;
}

function privacyLabel(stufe) {
  const level = t(`privacy.${stufe}`) || stufe;
  return t("privacy.label", { level });
}

function knotenNotiz(knoten) {
  if (!knoten) return "";
  // Soft-Label und „Extern“ sitzen in der TxID-/Zeit-Zeile, nicht als Extra-Band.
  if (softTxClassLabel(knoten)) return "";
  if (knoten.type === "external") return "";
  if (!knoten.note) return "";
  if (knoten.type === "external_unresolved") {
    return t("trace.noteUnresolvedInputs", { count: knoten.input_count || 0 });
  }
  if (knoten.type === "coinbase") return t("trace.noteCoinbase");
  if (knoten.note === "Keine Herkunft ermittelbar.") {
    return t("trace.errorNoOriginDetermined");
  }
  // Backend-Notiz „Externe Zweige…“ / Soft-Label nicht nochmal als Band.
  if (knoten.note === "Externe Zweige werden nicht weiterverfolgt.") return "";
  if (knoten.tx_class_label && knoten.note === knoten.tx_class_label) return "";
  return knoten.note;
}

/** Soft-Label der Tx-Klassifikation (CoinJoin-Art, PayJoin, …). */
function softTxClassLabel(knotenOderErgebnis) {
  if (!knotenOderErgebnis) return "";
  const kind = knotenOderErgebnis.tx_class || "";
  if (!kind || kind === "unknown") return "";
  // exchange_batch: bekannte Börsen → „Auszahlung von Kraken“ (auch aus
  // boerse_namen am UTXO/Ergebnis, wenn Soft-Label noch „Wahrscheinlich…“ ist).
  if (kind === "exchange_batch") {
    const namen = Array.isArray(knotenOderErgebnis.boerse_namen)
      ? knotenOderErgebnis.boerse_namen.filter(Boolean)
      : [];
    if (namen.length) {
      return uiSprache() === "en"
        ? `incl. payout from ${namen.join(", ")}`
        : `u. a. Auszahlung von ${namen.join(", ")}`;
    }
    const backend = uiSprache() === "en"
      ? (knotenOderErgebnis.tx_class_label_en || knotenOderErgebnis.tx_class_label || "")
      : (knotenOderErgebnis.tx_class_label || "");
    if (backend) return backend;
  }
  const key = `trace.txClass.${kind}`;
  const uebersetzt = t(key);
  if (uebersetzt !== key) return uebersetzt;
  return knotenOderErgebnis.tx_class_label || knotenOderErgebnis.note || "";
}

/** Mempool-artige Form-Icons für Soft-Labels (kein Markenlogo). */
const TX_CLASS_ICON = {
  whirlpool: "img/tx-class/whirlpool.svg",
  wasabi_classic: "img/tx-class/wasabi-classic.svg",
  wabisabi: "img/tx-class/wabisabi.svg",
  joinmarket: "img/tx-class/joinmarket.svg",
  bisq_payout: "img/tx-class/bisq.svg",
  bisq_deposit: "img/tx-class/bisq.svg",
};

/** Icon-/Leisten-Schlüssel: Deposit und Payout teilen dasselbe Bisq-Icon. */
function txClassIconKind(kind) {
  if (kind === "bisq_deposit") return "bisq_payout";
  return kind || "";
}

function softTxClassKind(knotenOderErgebnis) {
  const kind = (knotenOderErgebnis && knotenOderErgebnis.tx_class) || "";
  if (!kind || kind === "unknown") return "";
  return kind;
}

/** Füllt .knoten-unten-rechts mit optionalem Icon + Soft-Label-Text. */
function fuelleTxClassRechts(rechts, knotenOderErgebnis) {
  if (!rechts) return;
  const text = softTxClassLabel(knotenOderErgebnis);
  const kind = softTxClassKind(knotenOderErgebnis);
  rechts.replaceChildren();
  if (!text) {
    rechts.hidden = true;
    return;
  }
  rechts.hidden = false;
  rechts.title = text;
  const iconSrc = TX_CLASS_ICON[txClassIconKind(kind)] || TX_CLASS_ICON[kind];
  if (iconSrc) {
    const img = document.createElement("img");
    img.className = "tx-class-icon";
    img.src = iconSrc;
    img.alt = text;
    img.title = text;
    img.width = 18;
    img.height = 18;
    img.decoding = "async";
    rechts.append(img);
  }
  const span = document.createElement("span");
  span.className = "tx-class-text";
  span.textContent = text;
  span.title = text;
  rechts.append(span);
}

const MIX_ICON_ORDER = [
  "whirlpool",
  "wasabi_classic",
  "wabisabi",
  "joinmarket",
  "bisq_payout",
];

function _merkeTxClassIcon(gesehen, kind) {
  const k = txClassIconKind(kind);
  if (k && TX_CLASS_ICON[k]) gesehen.add(k);
}

/** Mix-/Form-Arten aus einem Trace-Ergebnis (Root + Kinder), ohne Extra-Netzwerk. */
function mixArtenAusErgebnis(ergebnis) {
  const gesehen = new Set();
  if (!ergebnis || !ergebnis.found) return [];
  const stapel = [];
  if (ergebnis.root) stapel.push(ergebnis.root);
  for (const k of ergebnis.children || []) stapel.push(k);
  _merkeTxClassIcon(gesehen, ergebnis.tx_class);
  while (stapel.length) {
    const knoten = stapel.pop();
    if (!knoten || typeof knoten !== "object") continue;
    _merkeTxClassIcon(gesehen, knoten.tx_class);
    for (const kind of knoten.children || []) stapel.push(kind);
  }
  return MIX_ICON_ORDER.filter((k) => gesehen.has(k));
}

/** Form-Arten einer Adressgruppe aus schon gespeicherten Traces (ohne Extra-Job). */
function mixArtenDerGruppe(gruppe) {
  const gesehen = new Set();
  for (const u of gruppe.utxos || []) {
    for (const k of u.mix_arten || []) {
      _merkeTxClassIcon(gesehen, k);
    }
    _merkeTxClassIcon(gesehen, u.tx_class);
  }
  return MIX_ICON_ORDER.filter((k) => gesehen.has(k));
}

/** Kurznamen für Adressgruppen-Tooltips (nicht das volle Soft-Label). */
const MIX_ICON_KURZ = {
  whirlpool: "Whirlpool",
  wasabi_classic: "Wasabi",
  wabisabi: "WabiSabi",
  joinmarket: "JoinMarket",
  bisq_payout: "Bisq",
};

/** Nur Icons, kein Text — Tooltip: „Im Verlauf …-Muster erkannt.“ */
function zeichneMixIconLeiste(arten) {
  if (!arten || !arten.length) return null;
  const leiste = document.createElement("span");
  leiste.className = "adress-mix-icons";
  const tipps = [];
  for (const kind of arten) {
    const src = TX_CLASS_ICON[kind];
    if (!src) continue;
    const name = MIX_ICON_KURZ[kind] || softTxClassLabel({ tx_class: kind }) || kind;
    const tipp = t("trace.mixInHistory", { art: name });
    tipps.push(tipp);
    const img = document.createElement("img");
    img.className = "tx-class-icon adress-mix-icon";
    img.src = src;
    img.alt = tipp;
    img.title = tipp;
    img.width = 16;
    img.height = 16;
    img.decoding = "async";
    leiste.append(img);
  }
  if (tipps.length) leiste.setAttribute("aria-label", tipps.join("; "));
  return leiste.children.length ? leiste : null;
}

/** Börsenname aus Label / exchange_label (CSV-Import oder Dienst-Katalog). */
function boerseNameAusLabel(lab) {
  if (!lab || typeof lab !== "object") return "";
  const name = String(lab.name || "").trim();
  if (!name) return "";
  if (lab.kategorie === "exchange" || lab.nutzer_import) return name;
  if (lab.kategorie_label === "Börse" || lab.quelle === "Börsen-CSV") return name;
  return "";
}

function boerseNameAusKnoten(knoten) {
  if (!knoten || typeof knoten !== "object") return "";
  return (
    boerseNameAusLabel(knoten.label)
    || boerseNameAusLabel(knoten.exchange_label)
  );
}

function _boerseRichtungMerken(richtungen, name, lab, kontext) {
  if (!name) return;
  const r = boerseRichtung(lab || { name }, kontext || { herkunft: true });
  if (!r) return;
  // out sticht in — wenn jemals zur Börse gesendet, rot behalten.
  if (richtungen[name] === "out") return;
  richtungen[name] = r;
}

/** Börsen-Namen + Richtungen aus einem Trace-Ergebnis (Root + Kinder). */
function boerseNamenAusErgebnis(ergebnis) {
  const gesehen = new Set();
  const richtungen = {};
  if (!ergebnis || !ergebnis.found) {
    return { namen: [], richtungen };
  }
  const stapel = [];
  if (ergebnis.root) stapel.push(ergebnis.root);
  for (const k of ergebnis.children || []) stapel.push(k);
  while (stapel.length) {
    const knoten = stapel.pop();
    if (!knoten || typeof knoten !== "object") continue;
    const lab = knoten.label || knoten.exchange_label;
    const name = boerseNameAusKnoten(knoten);
    if (name) {
      gesehen.add(name);
      _boerseRichtungMerken(richtungen, name, lab, {
        herkunft: true,
        zufluss: !knoten.abfluss,
        abfluss: Boolean(knoten.abfluss),
      });
    }
    for (const kind of knoten.children || []) stapel.push(kind);
    for (const src of knoten.sources || []) {
      const slab = src.label || src.exchange_label;
      const n = boerseNameAusLabel(slab);
      if (n) {
        gesehen.add(n);
        _boerseRichtungMerken(richtungen, n, slab, { herkunft: true, zufluss: true });
      }
    }
  }
  return {
    namen: [...gesehen].sort((a, b) => a.localeCompare(b, "de")),
    richtungen,
  };
}

function boerseNamenDerGruppe(gruppe) {
  const gesehen = new Set();
  const richtungen = {};
  for (const u of gruppe.utxos || []) {
    for (const n of u.boerse_namen || []) {
      if (!n) continue;
      gesehen.add(String(n));
      const r = (u.boerse_richtungen && u.boerse_richtungen[n]) || "in";
      if (richtungen[n] !== "out") richtungen[n] = r;
    }
  }
  return {
    namen: [...gesehen].sort((a, b) => a.localeCompare(b, "de")),
    richtungen,
  };
}

/**
 * Kompakte Börsen-Pillen in der Adressgruppen-Kopfzeile.
 * *richtungen*: optional Map name → "in"|"out" (sonst neutral/grün Zufluss).
 */
function zeichneBoersenLeiste(namen, richtungen) {
  if (!namen || !namen.length) return null;
  const leiste = document.createElement("span");
  leiste.className = "adress-boerse-leiste";
  const tipps = [];
  const map = richtungen || {};
  for (const name of namen) {
    const richtung = map[name] || "in";
    const tipp = richtung === "out"
      ? t("labels.exchangeOutflowNamed", { name })
      : t("trace.exchangeInHistory", { name });
    tipps.push(tipp);
    const p = document.createElement("span");
    p.className = "adress-boerse-pille"
      + (richtung === "out" ? " label-boerse-out" : " label-boerse-in");
    p.textContent = name;
    p.title = tipp;
    leiste.append(p);
  }
  if (tipps.length) leiste.setAttribute("aria-label", tipps.join("; "));
  return leiste;
}

function _haengeGruppenLeistenAn(kopf, gruppe) {
  if (!kopf || !gruppe) return;
  for (const sel of [".adress-mix-icons", ".adress-boerse-leiste"]) {
    const alt = kopf.querySelector(sel);
    if (alt) alt.remove();
  }
  const betrag = kopf.querySelector(".adress-betrag");
  const boerse = boerseNamenDerGruppe(gruppe);
  for (const leiste of [
    zeichneMixIconLeiste(mixArtenDerGruppe(gruppe)),
    zeichneBoersenLeiste(boerse.namen, boerse.richtungen),
  ]) {
    if (!leiste) continue;
    if (betrag) kopf.insertBefore(leiste, betrag);
    else kopf.append(leiste);
  }
}

/** Nach neuem Trace: Mix-Icons + Börsen-Pillen an der Adressgruppe nachziehen. */
function aktualisiereGruppenMixIcons(address) {
  if (!address) return;
  const gruppeEl = document.querySelector(
    `.adress-gruppe[data-address="${CSS.escape(address)}"]`,
  );
  if (!gruppeEl) return;
  const gruppe = gruppeAusTraceListe(address);
  if (!gruppe) return;
  const kopf = gruppeEl.querySelector(".adress-kopf");
  if (!kopf) return;
  _haengeGruppenLeistenAn(kopf, gruppe);
}

function quelleFeldLabel(feld, quelleKey) {
  const key = `sources.field.${feld.key}.label`;
  const uebersetzt = t(key);
  return uebersetzt !== key ? uebersetzt : feld.label;
}

function quelleFeldHinweis(feld, quelleKey) {
  let key = `sources.field.${feld.key}.hint`;
  if (feld.key === "FULCRUM_TOR_PROXY") {
    if (quelleKey === "own_core") key = "sources.field.FULCRUM_TOR_PROXY.hintCore";
    else if (quelleKey === "bip158") key = "sources.field.FULCRUM_TOR_PROXY.hintBip";
    else if (quelleKey === "public_onion") key = "sources.field.FULCRUM_TOR_PROXY.hintOnion";
  }
  const uebersetzt = t(key);
  return uebersetzt !== key ? uebersetzt : (feld.hinweis || "");
}
