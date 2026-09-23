/* SatSage – know your sats.
   Kein Framework, kein Build-Schritt. */

"use strict";

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

// ---------------------------------------------------------------------------
// Formatierung
// ---------------------------------------------------------------------------

/**
 * Muss display.format_sats entsprechen: unter 0,01 BTC in sats, darüber in
 * BTC mit zwei Nachkommastellen. Die Schwelle steht in display.py als
 * SATS_BTC_MIN_DISPLAY; tests/test_anzeige.py schlägt fehl, wenn sie sich
 * ändert, ohne dass dieser Wert nachgezogen wird.
 */
const SATS_BTC_MIN_DISPLAY = 1000000;

/**
 * Aktive UI-Sprache — Quelle der Wahrheit für Texte und Fiat.
 * Preferiert SatSageI18n.currentLang() (localStorage + Umschalter), nicht
 * allein config.ui_lang (Accept-Language kann EN sein, während der Nutzer DE wählt).
 */
function uiSprache() {
  if (window.SatSageI18n && typeof window.SatSageI18n.currentLang === "function") {
    const live = window.SatSageI18n.currentLang();
    if (live === "en" || live === "de") return live;
  }
  const ausConfig = (Zustand.config?.ui_lang || "").toLowerCase();
  if (ausConfig.startsWith("en")) return "en";
  if (ausConfig.startsWith("de")) return "de";
  return "de";
}

/**
 * Anzeige-Währung: nur Deutsch → EUR, sonst (EN) → USD.
 * Folgt der **aktiven** UI-Sprache.
 */
function fiatWaehrung() {
  return uiSprache() === "en" ? "USD" : "EUR";
}

function fiatSymbol(waehrung) {
  const w = (waehrung || fiatWaehrung()).toUpperCase();
  if (w === "EUR") return "€";
  if (w === "USD") return "$";
  return w;
}

/** Fiat-Zahl als Anzeigetext (ohne Kurs-Herkunft). */
function formatFiatBetrag(betrag, waehrung) {
  if (!Number.isFinite(betrag)) return "";
  const w = (waehrung || fiatWaehrung()).toUpperCase();
  const sym = fiatSymbol(w);
  if (Math.abs(betrag) < 0.005) {
    return w === "USD" ? `${sym}0` : `0 ${sym}`;
  }
  const zahl = Math.abs(betrag) < 10
    ? betrag.toLocaleString(formatLocale(), {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    })
    : Math.round(betrag).toLocaleString(formatLocale());
  // USD üblich vor der Zahl, EUR nach der Zahl (wie bisher).
  if (w === "USD") return `${sym}${zahl}`;
  if (w === "EUR") return `${zahl} ${sym}`;
  return `${zahl} ${sym}`;
}

/** @deprecated Name; leitet auf formatFiatBetrag (aktive UI-Währung). */
function formatEurBetrag(eur) {
  return formatFiatBetrag(eur, fiatWaehrung());
}

/**
 * Fiat-Gegenwert zum Spotkurs aus der Kopfzeile (Zustand.kurs).
 * Leer, solange kein Kurs da ist — formatSats bleibt dann unverändert.
 */
function formatEurAusSats(sats) {
  const kurs = Zustand.kurs;
  if (!kurs || !(Number(kurs.amount) > 0)) return "";
  const fiat = (Number(sats || 0) / 1e8) * Number(kurs.amount);
  return formatFiatBetrag(fiat, kurs.currency || fiatWaehrung());
}

/** UTC-Kalendertag (YYYY-MM-DD) aus Unix-Sekunden. */
function utcTagAusTs(ts) {
  const sekunden = Number(ts);
  if (!Number.isFinite(sekunden) || sekunden <= 0) return "";
  return new Date(sekunden * 1000).toISOString().slice(0, 10);
}

/**
 * Tageskurs aus der geladenen Historie am/vor dem Timestamp
 * (bis 14 Tage rückwärts, wie Server-Fallback).
 */
function tageskursAusSerie(ts) {
  const w = fiatWaehrung();
  const stand = Zustand.kursSerie?.[w] || Zustand.kursSerie?.EUR;
  const serie = stand?.series;
  if (!serie || !ts) return null;
  let tag = utcTagAusTs(ts);
  if (!tag) return null;
  for (let i = 0; i < 15; i += 1) {
    const amount = Number(serie[tag]);
    if (Number.isFinite(amount) && amount > 0) {
      return {
        amount,
        day: tag,
        source: stand.source || "history",
        currency: stand.currency || w,
        historic: true,
      };
    }
    const dt = new Date(`${tag}T00:00:00Z`);
    dt.setUTCDate(dt.getUTCDate() - 1);
    tag = dt.toISOString().slice(0, 10);
  }
  return null;
}

function spentZeitstempel(utxo) {
  if (!utxo) return 0;
  const status = utxo.status || {};
  return Number(
    utxo.spent_time_ts ||
    utxo.spent_block_time ||
    status.spent_time_ts ||
    0,
  ) || 0;
}

/**
 * EUR-Info für Anzeige: bei atTs Historie bevorzugen, sonst Spot.
 * warn=true → Spot-Fallback obwohl ein Ausgabedatum gewünscht war.
 */
function eurInfoAusSats(sats, atTs) {
  const wert = Number(sats || 0);
  const w = fiatWaehrung();
  if (atTs) {
    const hist = tageskursAusSerie(atTs);
    if (hist) {
      return {
        text: formatFiatBetrag(
          (wert / 1e8) * hist.amount,
          hist.currency || w,
        ),
        warn: false,
        title: t("price.atDay", {
          day: hist.day,
          source: hist.source === "bundle"
            ? t("sources.rates.bundled")
            : (hist.source || "?"),
        }),
      };
    }
  }
  const spot = formatEurAusSats(wert);
  if (!spot) return null;
  return {
    text: spot,
    warn: Boolean(atTs),
    title: atTs ? t("price.spotFallbackWarn") : "",
  };
}

/** Summe Fiat über ausgegebene UTXOs — je UTXO eigener Tageskurs. */
function eurInfoFuerSpentUtxos(utxos) {
  const liste = utxos || [];
  if (!liste.length) return null;
  const w = fiatWaehrung();
  let summe = 0;
  let warn = false;
  let treffer = false;
  const tage = new Set();
  let serieSource = "";
  for (const u of liste) {
    const sats = Number(u.value_sats || 0);
    const ts = spentZeitstempel(u);
    if (ts) {
      const hist = tageskursAusSerie(ts);
      if (hist) {
        summe += (sats / 1e8) * hist.amount;
        treffer = true;
        tage.add(hist.day);
        serieSource = hist.source || serieSource;
        continue;
      }
    }
    const kurs = Zustand.kurs;
    if (kurs && Number(kurs.amount) > 0) {
      summe += (sats / 1e8) * Number(kurs.amount);
      treffer = true;
      warn = true;
    }
  }
  if (!treffer) return null;
  let title = "";
  if (warn) title = t("price.spotFallbackWarn");
  else if (tage.size === 1) {
    const stand = Zustand.kursSerie?.[w] || Zustand.kursSerie?.EUR;
    title = t("price.atDay", {
      day: [...tage][0],
      source: (serieSource || stand?.source) === "bundle"
        ? t("sources.rates.bundled")
        : (serieSource || stand?.source || "?"),
    });
  } else if (tage.size > 1) {
    title = t("price.atDaysMixed", { n: tage.size });
  }
  return { text: formatFiatBetrag(summe, w), warn, title };
}

function formatSatsBasis(sats) {
  if (sats < SATS_BTC_MIN_DISPLAY) {
    return `${Number(sats).toLocaleString(formatLocale())} sats`;
  }
  return `${(sats / 1e8).toLocaleString(formatLocale(), {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })} BTC`;
}

function formatSats(sats, opts = {}) {
  const basis = formatSatsBasis(sats);
  const info = opts.atTs
    ? eurInfoAusSats(sats, opts.atTs)
    : (() => {
      const fiat = formatEurAusSats(sats);
      return fiat ? { text: fiat, warn: false, title: "" } : null;
    })();
  return info ? `${basis} (≈ ${info.text})` : basis;
}

/**
 * Unix-ts aus Objekt: time_ts / block_time / spent / datum TT.MM.JJJJ.
 * Für Salden: nur wenn *alle* Zeilen denselben UTC-Kalendertag haben.
 */
function tsAusBewertungsObjekt(obj) {
  if (!obj) return 0;
  const direkt = Number(
    obj.time_ts
    || obj.abgang_time_ts
    || obj.block_time
    || obj.spent_time_ts
    || obj.spent_block_time
    || obj.juengste_sats_ts
    || (obj.status && (obj.status.block_time || obj.status.spent_time_ts))
    || 0,
  );
  if (direkt > 1_000_000_000) return direkt;
  // utxoEreignisTs ist später definiert — zur Laufzeit verfügbar.
  if (typeof utxoEreignisTs === "function") {
    const e = utxoEreignisTs(obj);
    if (e > 0) return e;
  }
  for (const label of [obj.abgang_datum, obj.datum, obj.time_label]) {
    if (!label) continue;
    const m = String(label).match(/(\d{1,2})\.(\d{1,2})\.(\d{2,4})/);
    if (!m) continue;
    let y = Number(m[3]);
    if (m[3].length <= 2) y += 2000;
    const d = Date.UTC(y, Number(m[2]) - 1, Number(m[1]), 12, 0, 0);
    if (!Number.isNaN(d)) return Math.floor(d / 1000);
  }
  return 0;
}

/**
 * Gemeinsamer Bewertungszeitpunkt für ein Saldo.
 * Nur wenn *jede* Zeile ein Datum hat und alle denselben UTC-Tag teilen.
 * Sonst null — kein Spot-Mix unterschiedlicher Tage in eine Summe.
 */
function gemeinsamerAtTs(items, tsFn) {
  const liste = items || [];
  if (!liste.length) return null;
  const fn = tsFn || tsAusBewertungsObjekt;
  const tage = [];
  let sample = 0;
  for (const item of liste) {
    const ts = Number(fn(item) || 0);
    if (!ts || ts <= 0) return null;
    const tag = utcTagAusTs(ts);
    if (!tag) return null;
    tage.push(tag);
    sample = ts;
  }
  if (new Set(tage).size !== 1) return null;
  return sample;
}

/** formatSats mit atTs nur bei einheitlichem Datum der saldierten Zeilen. */
function formatSatsGemeinsam(sats, items, tsFn) {
  const atTs = gemeinsamerAtTs(items, tsFn);
  if (atTs) return formatSats(sats, { atTs });
  // Gemischt / ohne Datum: nur sats/BTC — kein Spot als Pseudo-Historie.
  return formatSatsBasis(sats);
}

/**
 * Betragszelle füllen; bei Spot-Fallback trotz Ausgabedatum gelb + Tooltip.
 * opts.atTs oder opts.spentUtxos (Summe je Tageskurs).
 * opts.gemeinsam: Liste — Fiat nur bei einheitlichem Bewertungsdatum.
 */
function setzeSatsBetrag(el, sats, opts = {}) {
  if (!el) return;
  el.replaceChildren();
  const basis = formatSatsBasis(sats);
  el.append(document.createTextNode(basis));

  let info = null;
  if (opts.gemeinsam) {
    const atTs = gemeinsamerAtTs(opts.gemeinsam, opts.tsFn);
    if (atTs) info = eurInfoAusSats(sats, atTs);
    // sonst: kein Fiat (keine Mischung)
  } else if (opts.spentUtxos) {
    // Ausgaben-Summe: nur bei gleichem Ausgabetag historisch, sonst kein Mix.
    const atTs = gemeinsamerAtTs(opts.spentUtxos, spentZeitstempel);
    if (atTs) info = eurInfoAusSats(sats, atTs);
  } else {
    info = eurInfoAusSats(sats, opts.atTs);
  }
  if (!info) return;
  el.append(document.createTextNode(" (≈ "));
  const fiat = document.createElement("span");
  fiat.textContent = info.text;
  if (info.warn) fiat.className = "fiat-schaetzung";
  if (info.title) fiat.title = info.title;
  el.append(fiat, document.createTextNode(")"));
}

function formatZahl(wert) {
  return Number(wert || 0).toLocaleString(formatLocale());
}

/**
 * Zeitstrahl-Beträge: dekadische Lesart statt „0,000 BTC“.
 * 1 sat … 100k sat, ab 0,01 BTC als btc (1e6 sats).
 */
function formatZeitstrahlBetrag(sats) {
  const n = Math.round(Number(sats) || 0);
  if (n <= 0) return "0";
  if (n < 1000) return `${n} sat`;
  if (n < 1_000_000) {
    const k = n / 1000;
    const kText = Number.isInteger(k)
      ? String(k)
      : k.toLocaleString(formatLocale(), {
        maximumFractionDigits: 1,
        minimumFractionDigits: 0,
      });
    return `${kText}k sat`;
  }
  const btc = n / 1e8;
  let btcText;
  if (btc >= 1 && Number.isInteger(btc)) {
    btcText = String(btc);
  } else if (btc >= 0.01) {
    // 0.01 / 0.1 / 1.5 — wenige Stellen, Locale-Dezimaltrenner
    const stellen = btc >= 1 ? 2 : (btc >= 0.1 ? 1 : 2);
    btcText = btc.toLocaleString(formatLocale(), {
      minimumFractionDigits: 0,
      maximumFractionDigits: stellen,
    });
  } else {
    btcText = btc.toLocaleString(formatLocale(), {
      minimumFractionDigits: 0,
      maximumFractionDigits: 8,
    });
  }
  return `${btcText} btc`;
}

/** @deprecated Alias — Punkt/Achse nutzen formatZeitstrahlBetrag. */
function formatBtcDrei(sats) {
  return formatZeitstrahlBetrag(sats);
}

/**
 * Lage zur Haltefrist — und, wenn ein Cutoff gilt, zum Stichtag.
 *
 * außerhalb = Frist um (steuerfrei nach der hier gerechneten Anschaffung).
 * innerhalb = Frist läuft noch, oder Neuvermögen nach dem Stichtag.
 */
function haltefristBeschriftung(eintrag, hatStichtag) {
  const lage = eintrag.erfuellt ? t("tax.haltefristOut") : t("tax.haltefristIn");
  if (!hatStichtag) return lage;
  const schnitt = eintrag.neuvermoegen ? t("tax.afterCutoff") : t("tax.beforeCutoff");
  return `${lage}, ${schnitt}`;
}

/**
 * ISO-Zeitstempel als lesbares Datum in Ortszeit.
 *
 * Die Metadaten der Listen tragen die volle ISO-Form mit Mikrosekunden und
 * Zeitzone ("2026-07-22T05:25:39.430001+00:00"). Unverändert angezeigt ist
 * das eine Maschinenangabe. Unlesbare Werte bleiben unverändert stehen —
 * lieber roh als falsch gedeutet.
 */
function formatZeitpunkt(wert) {
  if (!wert) return "";
  const zeit = new Date(wert);
  if (Number.isNaN(zeit.getTime())) return String(wert);
  return zeit.toLocaleString(formatLocale(), {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/**
 * Wie alt ein Wallet ist: „seit 22.08.2023".
 *
 * Gemeint ist die älteste Transaktion irgendeiner seiner Adressen — auch
 * längst ausgegebene zählen. Wird beim Scan einmalig erhoben; bis dahin bleibt
 * die Angabe leer, statt ein Alter zu behaupten.
 */
function cacheDatum(wallet) {
  if (!wallet || !wallet.cache_mtime) return "";
  const zeit = new Date(wallet.cache_mtime * 1000);
  if (Number.isNaN(zeit.getTime())) return "";
  return zeit.toLocaleDateString(formatLocale(), {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
}

/** Chain-Tip aus Config (Header-Cache), falls bekannt. */
function chainTipHoehe() {
  const tip = Zustand.config?.header_tip;
  if (tip == null || tip === "") return null;
  const n = Number(tip);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Wallet-IDs aus wallet_sync-Job-Meta (leer = unbekannt, nicht „alle“). */
function walletIdsAusSyncJob(job) {
  if (!job) return [];
  const meta = job.meta || {};
  if (Array.isArray(meta.wallet_ids) && meta.wallet_ids.length) {
    return meta.wallet_ids.map(String);
  }
  if (meta.wallet_id) return [String(meta.wallet_id)];
  return [];
}

function merkeWalletSyncZiele(jobOrIds) {
  if (Array.isArray(jobOrIds)) {
    Zustand.walletSyncWalletIds = jobOrIds.map(String);
    return;
  }
  const ids = walletIdsAusSyncJob(jobOrIds);
  if (ids.length) Zustand.walletSyncWalletIds = ids;
}

function tipSyncDoneWalletIds(job) {
  const roh = job?.meta?.done_wallet_ids;
  if (!Array.isArray(roh)) return [];
  return roh.map(String);
}

function walletSyncLaeuftFuer(walletId) {
  if (!walletId) return false;
  const wid = String(walletId);
  // UTXO-Tip fertig, Empfangsadressen trudeln noch → Nav schon „gerade eben“.
  if (Zustand.walletSyncPhase === "empfang") return false;
  if (Zustand.walletSyncLogStand?._tipUiFertig) return false;
  // Dieses Wallet schon im laufenden Job fertig → mtime / „gerade eben“.
  const lokalFertig = Zustand.walletSyncDoneIds || [];
  if (lokalFertig.map(String).includes(wid)) return false;
  const jobs = Zustand.jobsNav?.jobs || [];
  for (const job of jobs) {
    if (job.kind !== "wallet_sync") continue;
    // Stiller Watch-Fallback: kein Nav-„aktualisiere…“ / kein Empfangs-Puls.
    if (job.meta?.still) continue;
    // UTXO-Tip fertig, nur noch Empfangs-QR: Marker grün — QR zeigt den Rest.
    if (job.meta?.phase === "empfang") continue;
    if (!(job.running || job.status === "running" || job.status === "queued")) {
      continue;
    }
    // Pro Wallet: sobald Tip für diese ID steht, nicht mehr „aktualisiere…“.
    if (tipSyncDoneWalletIds(job).includes(wid)) return false;
    const ids = walletIdsAusSyncJob(job);
    if (ids.length) {
      if (ids.includes(wid)) return true;
      continue;
    }
    // Meta fehlt: nicht pauschal alle Wallets markieren.
  }
  // Lokaler Tip-Poller mit bekannten Zielen (Nav noch ohne Meta).
  // Nicht während Empfangs-Phase — sonst bleibt „aktualisiere…“ trotz Log-Fertig.
  if (
    Zustand.walletSyncJob
    && Zustand.walletSyncTimer
    && Array.isArray(Zustand.walletSyncWalletIds)
    && Zustand.walletSyncWalletIds.length
    && !Zustand.walletSyncStill
    && Zustand.walletSyncPhase !== "empfang"
    && !Zustand.walletSyncLogStand?._tipUiFertig
  ) {
    if ((Zustand.walletSyncDoneIds || []).map(String).includes(wid)) return false;
    return Zustand.walletSyncWalletIds.includes(wid);
  }
  return false;
}

/** Job-ID noch wirklich laufend/in Queue laut jobsNav (sonst stale GUI-Bindung). */
function jobNochAktiv(jobId) {
  if (!jobId) return false;
  const jobs = Zustand.jobsNav?.jobs || [];
  const j = jobs.find((x) => x && x.id === jobId);
  if (!j) {
    // Nav kennt den Job noch nicht / nicht mehr: nur solange der zugehörige
    // Poller die ID noch aktiv verfolgt — nie pauschal „ja“ für alle Wallets.
    if (Zustand.rescanJob === jobId && Zustand.rescanTimer) return true;
    if (Zustand.walletSyncJob === jobId && Zustand.walletSyncTimer) return true;
    return false;
  }
  return Boolean(
    j.running
    || j.status === "running"
    || j.status === "queued"
    || j.queue_status === "queued",
  );
}

/**
 * Aktualität des UTXO-Caches für Anzeige.
 *
 * Primär: **mtime** (wie lange der letzte Sync her ist).
 * Tip-Abstand nur Zusatz: hinter der Chain → Warnung + „−N Blöcke“.
 * „bis Tip“ allein entfällt — das ist nur Sekunden lang wahr.
 */
function cacheFrische(wallet) {
  if (!wallet || !wallet.has_cache) {
    return {
      stufe: "leer",
      kurz: "",
      lang: t("wallet.fresh.none"),
      title: t("wallet.fresh.noneTitle"),
    };
  }
  if (walletSyncLaeuftFuer(wallet.id)) {
    return {
      stufe: "warn",
      kurz: t("wallet.fresh.syncingShort"),
      lang: t("wallet.fresh.syncing"),
      title: t("wallet.fresh.syncingTitle"),
    };
  }

  const tip = chainTipHoehe();
  const scanTip = wallet.scan_tip_height != null
    ? Number(wallet.scan_tip_height)
    : null;
  let rueckstand = null;
  if (tip != null && scanTip != null && Number.isFinite(scanTip)) {
    rueckstand = tip - scanTip;
  }
  const hinterTip = rueckstand != null && rueckstand > 2;

  const mtime = wallet.cache_mtime ? Number(wallet.cache_mtime) : 0;
  if (mtime > 0) {
    const alterSek = Math.max(0, Math.floor(Date.now() / 1000 - mtime));
    const datum = cacheDatum(wallet);
    let stufe = "gut";
    let kurz;
    let lang;
    let title;
    if (alterSek < 5 * 60) {
      kurz = t("wallet.fresh.justNowShort");
      lang = t("wallet.fresh.justNow");
      title = t("wallet.fresh.justNowTitle", { datum: datum || "—" });
    } else if (alterSek < 60 * 60) {
      const m = Math.max(1, Math.floor(alterSek / 60));
      kurz = t("wallet.fresh.minutesShort", { n: m });
      lang = t("wallet.fresh.minutes", { n: m });
      title = t("wallet.fresh.ageTitle", { datum: datum || "—" });
    } else if (alterSek < 24 * 60 * 60) {
      const h = Math.max(1, Math.floor(alterSek / 3600));
      stufe = "warn";
      kurz = t("wallet.fresh.hoursShort", { n: h });
      lang = t("wallet.fresh.hours", { n: h });
      title = t("wallet.fresh.ageTitle", { datum: datum || "—" });
    } else {
      const tagen = Math.max(1, Math.floor(alterSek / 86400));
      stufe = "warn";
      kurz = t("wallet.fresh.daysShort", { n: tagen });
      lang = t("wallet.fresh.days", { n: tagen, datum: datum || "—" });
      title = t("wallet.fresh.oldTitle");
    }
    if (hinterTip) {
      const n = formatZahl(rueckstand);
      stufe = "warn";
      kurz = `${kurz} · ${t("wallet.fresh.behindShort", { n })}`;
      lang = `${lang} · ${t("wallet.fresh.behind", {
        tip: formatZahl(scanTip),
        chain: formatZahl(tip),
        n,
      })}`;
      title = t("wallet.fresh.behindTitle");
    } else if (rueckstand != null && rueckstand <= 2) {
      title = `${title} · ${t("wallet.fresh.tipTitle", {
        tip: formatZahl(scanTip),
        chain: formatZahl(tip),
      })}`;
    }
    return { stufe, kurz, lang, title };
  }

  // Ohne mtime: Tip-Abstand als Notbehelf
  if (hinterTip) {
    return {
      stufe: "warn",
      kurz: t("wallet.fresh.behindShort", { n: formatZahl(rueckstand) }),
      lang: t("wallet.fresh.behind", {
        tip: formatZahl(scanTip),
        chain: formatZahl(tip),
        n: formatZahl(rueckstand),
      }),
      title: t("wallet.fresh.behindTitle"),
    };
  }
  if (rueckstand != null && rueckstand <= 2) {
    return {
      stufe: "gut",
      kurz: t("wallet.fresh.tipShort"),
      lang: t("wallet.fresh.tip", { tip: formatZahl(scanTip) }),
      title: t("wallet.fresh.tipTitle", {
        tip: formatZahl(scanTip),
        chain: formatZahl(tip),
      }),
    };
  }
  return {
    stufe: "neutral",
    kurz: t("wallet.fresh.unknownShort"),
    lang: t("wallet.fresh.unknown"),
    title: t("wallet.fresh.unknownTitle"),
  };
}

function cacheHinweis(wallet) {
  if (!wallet || !wallet.has_cache) return "";
  const frisch = cacheFrische(wallet);
  if (frisch.kurz) return frisch.kurz;
  const datum = cacheDatum(wallet);
  return datum ? t("wallet.cacheFrom", { datum }) : t("wallet.cacheCached");
}

function walletAlter(wallet, { kurz = false } = {}) {
  if (!wallet) return "";

  // „seit …" allein ließ offen, worauf es sich bezieht — auf den Scan? den
  // Cache? Gemeint ist der erste Zahlungseingang, und das soll dastehen.
  // In Pillen bleibt die Kurzform, dort ist der Platz knapp.
  const beschriftung = kurz ? t("wallet.firstUseShort") : t("wallet.firstUse");

  if (wallet.first_seen_ts) {
    const zeit = new Date(wallet.first_seen_ts * 1000);
    if (!Number.isNaN(zeit.getTime())) {
      return `${beschriftung} ${zeit.toLocaleDateString(formatLocale(), {
        day: "2-digit", month: "2-digit", year: "numeric",
      })}`;
    }
  }
  // Ohne Blockzeit bleibt die Höhe — sie ist der eigentliche Befund.
  if (wallet.first_seen_height) {
    return t("wallet.firstUseBlock", {
      label: beschriftung,
      n: formatZahl(wallet.first_seen_height),
    });
  }
  return "";
}

/** Kurzform für Marken in Listen: „02.08." — das Jahr nur, wenn es abweicht. */
function formatKurzdatum(wert) {
  if (!wert) return "";
  const zeit = new Date(wert);
  if (Number.isNaN(zeit.getTime())) return "";
  const tagMonat = zeit.toLocaleDateString(formatLocale(), {
    day: "2-digit", month: "2-digit",
  });
  const jahr = zeit.getFullYear();
  return jahr === new Date().getFullYear() ? tagMonat : `${tagMonat}${jahr}`;
}

function formatHaltedauer(tage) {
  if (tage === null || tage === undefined) return "—";
  if (tage < 31) return `${tage} T`;
  const jahre = Math.floor(tage / 365);
  const monate = Math.floor((tage % 365) / 30);
  if (jahre > 0) return monate > 0 ? `${jahre} J ${monate} M` : `${jahre} J`;
  return `${monate} M`;
}

function kuerze(text, vorne = 10, hinten = 6) {
  if (!text || text.length <= vorne + hinten + 1) return text || "—";
  return `${text.slice(0, vorne)}…${text.slice(-hinten)}`;
}

/**
 * Vollständigen Wert (Adresse, TxID, UTXO) in die Zwischenablage.
 * Kurzschreibweise in der UI lässt sich sonst nicht sauber markieren.
 */
async function kopiereInZwischenablage(text) {
  const wert = String(text || "");
  if (!wert) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(wert);
      return true;
    }
  } catch (_) {
    /* Fallback unten */
  }
  try {
    const feld = document.createElement("textarea");
    feld.value = wert;
    feld.setAttribute("readonly", "");
    feld.style.position = "fixed";
    feld.style.left = "-9999px";
    document.body.appendChild(feld);
    feld.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(feld);
    return ok;
  } catch (_) {
    return false;
  }
}

function kurzKopieFeedback(el, ok) {
  if (!el) return;
  if (el._kopieTimer) clearTimeout(el._kopieTimer);
  const vorher = el.dataset.kopieAnzeige || el.textContent;
  el.dataset.kopieAnzeige = vorher;
  el.textContent = ok ? t("common.copy") : t("common.copyFail");
  el.classList.toggle("kopierbar-ok", ok);
  el.classList.toggle("kopierbar-fehl", !ok);
  el._kopieTimer = setTimeout(() => {
    el.textContent = el.dataset.kopieAnzeige || vorher;
    el.classList.remove("kopierbar-ok", "kopierbar-fehl");
    delete el._kopieTimer;
  }, 900);
}

/**
 * Gekürzte Anzeige: Klick (und Enter/Leertaste) kopiert den Vollwert.
 * stopPropagation — sonst klappen Adress-/UTXO-Zeilen mit auf.
 */
function macheKopierbar(el, volltext, art) {
  if (art === undefined) art = t("common.copyArtValue");
  if (!el || !volltext) return el;
  const wert = String(volltext);
  el.classList.add("kopierbar");
  el.dataset.kopie = wert;
  el.title = t("common.copyClick", { value: wert, art });
  el.setAttribute("role", "button");
  el.tabIndex = 0;
  const ausloesen = async (ereignis) => {
    ereignis.preventDefault();
    ereignis.stopPropagation();
    const ok = await kopiereInZwischenablage(wert);
    kurzKopieFeedback(el, ok);
  };
  el.addEventListener("click", ausloesen);
  el.addEventListener("keydown", (ereignis) => {
    if (ereignis.key === "Enter" || ereignis.key === " ") ausloesen(ereignis);
  });
  return el;
}

const $ = (auswahl) => document.querySelector(auswahl);

/** Anzeige-Locale aus i18n; Fallback Deutsch wenn i18n.js fehlt. */
function formatLocale() {
  if (window.SatSageI18n && typeof window.SatSageI18n.formatLocale === "function") {
    return window.SatSageI18n.formatLocale();
  }
  return "de-DE";
}

/** Fallback bevor locales geladen sind — Kopf-Pillen nie als Roh-Keys. */
const T_FALLBACK = {
  "header.p2pPeers": "P2P {n}",
  "header.sourceCore": "Core",
  "header.sourceIndexer": "Indexer",
  "header.sourceIndexerTitle": "Eigener Electrum-Indexer — Verbindung wird geprüft…",
  "header.sourceElectrumOwn": "Electrum privat",
  "header.sourceElectrumImpl": "{name}",
  "header.sourceElectrumImplTitle": "Eigener Electrum-Indexer: {name} ({raw}). {detail}",
  "header.sourceElectrumPublic": "Electrum öffentlich",
  "privacy.pillHigh": "Privatsphäre hoch",
  "privacy.pillMedium": "Privatsphäre mittel",
  "privacy.pillNone": "keine Privatsphäre",
  "privacy.pillUnclear": "Privatsphäre unklar",
};

function t(key, vars) {
  let text;
  if (window.SatSageI18n && typeof window.SatSageI18n.t === "function") {
    text = window.SatSageI18n.t(key, vars);
    // Catalog noch leer / Key fehlt → Roh-Key vermeiden.
    if (text === key && T_FALLBACK[key]) text = T_FALLBACK[key];
  } else {
    text = T_FALLBACK[key] || key;
  }
  if (vars && typeof vars === "object" && text.indexOf("{") >= 0) {
    for (const [name, wert] of Object.entries(vars)) {
      text = text.split(`{${name}}`).join(String(wert));
    }
  }
  return text;
}


function setzeText(element, text) {
  element.textContent = text;
}

/** Datum und Uhrzeit im selben Format wie „jüngste sats“. */
function formatVollerZeitpunkt(ts) {
  const sekunden = Number(ts);
  if (!Number.isFinite(sekunden) || sekunden <= 0) return "";
  const wann = new Date(sekunden * 1000);
  if (Number.isNaN(wann.getTime())) return "";
  const datum = wann.toLocaleDateString(formatLocale(), {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
  const uhr = wann.toLocaleTimeString(formatLocale(), {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  return t("common.atTime", { datum, uhr });
}


/** Jüngster externer Zufluss — nur bei vollständigem Herkunftsbaum. */
function formatJuengsteSats(utxo) {
  if (!utxo || !utxo.verfolgt_vollstaendig) return "";
  return formatVollerZeitpunkt(utxo.juengste_sats_ts);
}

/** Ausgabezeit; bei älteren Cache-Einträgen bestmöglichen Zeitstempel nehmen. */
function formatAusgegebenWann(utxo) {
  if (!utxo) return "";
  const status = utxo.status || {};
  const zeit = formatVollerZeitpunkt(
    utxo.spent_time_ts ||
    utxo.spent_block_time ||
    status.spent_time_ts ||
    (utxo.spent_height ? status.block_time : null),
  );
  if (zeit) return zeit;
  const hoehe = Number(utxo.spent_height || status.spent_height || 0);
  return hoehe > 0
    ? t("trace.spentAtBlock", {
      hoehe: hoehe.toLocaleString(formatLocale()),
    })
    : "";
}

/**
 * Zusatz für die zugeklappte Adresszeile unter „Bereits ausgegeben“:
 * „1 UTXO, ausgegeben am …“ — ohne Aufklappen sichtbar.
 */
function gruppeAusgegebenZusatz(gruppe) {
  const utxos = (gruppe && gruppe.utxos) || [];
  const spent = utxos.filter((u) => u.spent || u.spent_pending);
  if (!spent.length) return "";
  if (spent.every((u) => u.spent_pending)) return t("trace.spentPending");
  let best = null;
  for (const u of spent) {
    if (u.spent_pending) continue;
    const wann = formatAusgegebenWann(u);
    if (!wann) continue;
    const ts = Number(u.spent_time_ts || u.spent_block_time || 0);
    if (!best || ts >= best.ts) best = { wann, ts };
  }
  return best ? t("trace.spentWhen", { wann: best.wann }) : "";
}

function juengsteSatsMarke(utxo) {
  const wann = formatJuengsteSats(utxo);
  if (!wann) return null;
  const satz = document.createElement("span");
  satz.className = "verfolgt-marke juengste-sats-marke";
  satz.textContent = t("trace.youngestSats", { wann });
  satz.title = t("trace.youngestSatsTitle");
  return satz;
}

/** Vollständig verfolgt (für den gelben Gruppennachweis). */
function utxoHatVollenHerkunftstrace(utxo) {
  return Boolean(utxo && utxo.verfolgt_vollstaendig);
}

/**
 * Gelber Hinweis an der Adressgruppe: „jüngste sats“ gilt nur für die
 * bereits vollständig verfolgten UTXOs — unverfolgte können jünger sein.
 */
function gruppeOhneHerkunftstraceMarke(gruppe) {
  const utxos = (gruppe && gruppe.utxos) || [];
  if (utxos.length < 2) return null;
  const mitTrace = utxos.filter(utxoHatVollenHerkunftstrace).length;
  // Ohne mindestens eine „jüngste sats“-Angabe wäre der Vorbehalt sinnlos.
  const hatJuengste = utxos.some((u) => formatJuengsteSats(u));
  if (!hatJuengste || mitTrace === 0) return null;
  const ohne = utxos.length - mitTrace;
  if (ohne <= 0) return null;
  const satz = document.createElement("span");
  satz.className = "verfolgt-marke ohne-herkunft-marke";
  satz.textContent =
    ohne === 1
      ? t("trace.missingOne")
      : t("trace.missingMany", { n: ohne });
  satz.title = t("trace.missingTitle");
  return satz;
}

/** Der jüngste vollständige Zufluss in einer Adressgruppe — für die Kopfzeile. */
function juengsteSatsDerGruppe(gruppe) {
  let best = null;
  for (const u of gruppe.utxos || []) {
    if (!formatJuengsteSats(u)) continue;
    if (!best || (u.juengste_sats_ts || 0) > (best.juengste_sats_ts || 0)) {
      best = u;
    }
  }
  return best;
}

/** „jüngste sats“ und ggf. gelber Vorbehalt an den Adresskopf. */
function haengeGruppenJuengsteAn(kopf, gruppe) {
  if (!kopf || !gruppe) return;
  const juengste = juengsteSatsMarke(juengsteSatsDerGruppe(gruppe));
  if (juengste) kopf.append(juengste);
  const ohne = gruppeOhneHerkunftstraceMarke(gruppe);
  if (ohne) kopf.append(ohne);
}

function gruppeAusDom(adressBlock) {
  if (!adressBlock) return null;
  const address = adressBlock.dataset.address || "";
  const utxos = [];
  const gesehen = new Set();
  for (const knoten of adressBlock.querySelectorAll(
    ".utxo-wurzel[data-key], .utxo-zeile[data-key]",
  )) {
    const key = knoten.dataset.key;
    if (!key || gesehen.has(key)) continue;
    gesehen.add(key);
    utxos.push({
      key,
      verfolgt_vollstaendig: knoten.dataset.verfolgtVollstaendig === "1",
      juengste_sats_ts: Number(knoten.dataset.juengsteSatsTs || 0) || null,
    });
  }
  return { address, utxos };
}

/** Adressgruppe aus dem Trace-Cache — zuverlässiger als nur DOM-Attribute. */
function gruppeAusTraceListe(address, keyHinweis) {
  const listen = [
    ...(Zustand.traceListe?.addresses || []),
    ...(Zustand.traceListe?.verlauf?.addresses || []),
  ];
  if (address) {
    const treffer = listen.find((g) => g.address === address);
    if (treffer) return treffer;
  }
  if (keyHinweis) {
    for (const g of listen) {
      if ((g.utxos || []).some((u) => u.key === keyHinweis)) return g;
    }
  }
  return null;
}

/**
 * Nach einem frischen Trace: Listendaten und Kopfzeilen nachziehen.
 * Sonst sähe man „jüngste sats" und das Verfolgt-Datum erst nach Refresh.
 *
 * Bei gezielter Tx-Suche startet die Kopfzeile oft mit 0 sats / leerer
 * Adresse — hier kommen Output-Betrag und Adresse aus dem Trace-Root.
 */
function merkeTraceAmUtxo(utxo, ergebnis) {
  if (!utxo || !ergebnis || !ergebnis.found) return;
  // Nur Server-Flag — kein Fallback über external_count (leere/lückige Bäume
  // wirkten sonst fälschlich „vollständig“).
  const voll = Boolean(ergebnis.verfolgt_vollstaendig);
  utxo.verfolgt = true;
  // Immer neu setzen — sonst bleibt bei „Scan neu" das alte Stand-Datum.
  utxo.verfolgt_ts = Math.floor(Date.now() / 1000);
  utxo.verfolgt_veraltet = false;
  utxo.verfolgt_vollstaendig = voll;
  utxo.unvollstaendig = Boolean(ergebnis.unvollstaendig) || !voll;
  if (ergebnis.juengste_sats_ts) {
    utxo.juengste_sats_ts = ergebnis.juengste_sats_ts;
  }
  const root = ergebnis.root || {};
  if (root.amount_sats != null && Number(root.amount_sats) >= 0) {
    utxo.value_sats = Number(root.amount_sats) || 0;
  }
  if (root.address && !utxo.address) {
    utxo.address = root.address;
  }
  if (root.wallet) {
    utxo.wallet = root.wallet;
  } else if (root.address && !utxo.wallet) {
    utxo.wallet = t("trace.targetedWallet");
  }
  if (root.time_label) {
    utxo.time_label = root.time_label;
  }
  if (root.tx_class && (TX_CLASS_ICON[root.tx_class] || TX_CLASS_ICON[txClassIconKind(root.tx_class)])) {
    utxo.tx_class = root.tx_class;
    const arten = new Set(utxo.mix_arten || []);
    _merkeTxClassIcon(arten, root.tx_class);
    utxo.mix_arten = MIX_ICON_ORDER.filter((k) => arten.has(k));
  }
  // Auch Mix-Formen tiefer im Baum (Remix-Hops).
  const tief = mixArtenAusErgebnis(ergebnis);
  if (tief.length) {
    const arten = new Set([...(utxo.mix_arten || []), ...tief]);
    utxo.mix_arten = MIX_ICON_ORDER.filter((k) => arten.has(k));
  }
  // Börsen (Kraken/Coinbase/…) aus Trace-Blättern — für Gruppen-Kopfzeile.
  const boersen = boerseNamenAusErgebnis(ergebnis);
  if (boersen.namen && boersen.namen.length) {
    utxo.boerse_namen = boersen.namen;
    utxo.boerse_richtungen = boersen.richtungen || {};
  }
  // Dieselbe Instanz in der Trace-Liste nachziehen (findeTraceUtxo kann
  // ein anderes Objekt geliefert haben als die Gruppenzeile).
  for (const liste of [
    Zustand.traceListe?.addresses,
    Zustand.traceListe?.verlauf?.addresses,
  ]) {
    for (const gruppe of liste || []) {
      for (const eintrag of gruppe.utxos || []) {
        if (eintrag.key !== utxo.key) continue;
        eintrag.verfolgt = true;
        eintrag.verfolgt_ts = utxo.verfolgt_ts;
        eintrag.verfolgt_veraltet = false;
        eintrag.verfolgt_vollstaendig = utxo.verfolgt_vollstaendig;
        eintrag.unvollstaendig = utxo.unvollstaendig;
        if (utxo.juengste_sats_ts) {
          eintrag.juengste_sats_ts = utxo.juengste_sats_ts;
        }
        if (utxo.value_sats != null) eintrag.value_sats = utxo.value_sats;
        if (utxo.address) eintrag.address = utxo.address;
        if (utxo.wallet) eintrag.wallet = utxo.wallet;
        if (utxo.time_label) eintrag.time_label = utxo.time_label;
        if (utxo.mix_arten) eintrag.mix_arten = utxo.mix_arten;
        if (utxo.tx_class) eintrag.tx_class = utxo.tx_class;
        if (utxo.boerse_namen) eintrag.boerse_namen = utxo.boerse_namen;
        if (utxo.boerse_richtungen) {
          eintrag.boerse_richtungen = utxo.boerse_richtungen;
        }
        if (!utxo.address && gruppe.address) utxo.address = gruppe.address;
      }
    }
  }
  aktualisiereTraceWurzelKopf(utxo);
  zeichneJuengsteSatsNach(utxo);
  if (utxo.address) aktualisiereGruppenMixIcons(utxo.address);
}

/**
 * Betrag/Adresse/Wallet in der UTXO-Kopfzeile nachziehen.
 * *wurzelEl*: optional der konkrete Block (zuverlässiger als data-key-Suche).
 */
function aktualisiereTraceWurzelKopf(utxo, wurzelEl = null) {
  if (!utxo || !utxo.key) return;
  let block = wurzelEl && wurzelEl.classList?.contains("utxo-wurzel")
    ? wurzelEl
    : null;
  if (!block && wurzelEl?.closest) {
    block = wurzelEl.closest(".utxo-wurzel");
  }
  if (!block) {
    block = document.querySelector(
      `.utxo-wurzel[data-key="${CSS.escape(utxo.key)}"]`,
    );
  }
  if (!block) return;
  const oben = block.querySelector(".utxo-kopf .knoten-oben");
  if (!oben) return;

  const betrag = oben.querySelector(".betrag");
  if (betrag && utxo.value_sats != null) {
    betrag.classList.remove("zart");
    if (utxo.spent || utxo.spent_pending) {
      setzeSatsBetrag(betrag, utxo.value_sats, {
        atTs: spentZeitstempel(utxo) || undefined,
        spentUtxos: [utxo],
      });
    } else {
      betrag.textContent = formatSats(utxo.value_sats);
    }
  }

  // Wallet-Label: zweites Kind nach .betrag (nicht Marken).
  let wer = null;
  for (const el of oben.children) {
    if (el.classList.contains("betrag")) continue;
    if (el.classList.contains("mono")) continue;
    if (el.classList.contains("verfolgt-marke")) continue;
    wer = el;
    break;
  }
  if (wer && utxo.wallet) wer.textContent = utxo.wallet;

  let adresse = oben.querySelector("span.mono.zart");
  if (!adresse) {
    // Fallback: erstes mono ohne betrag
    adresse = [...oben.querySelectorAll("span.mono")].find(
      (el) => !el.classList.contains("betrag"),
    );
  }
  if (adresse && utxo.address) {
    adresse.textContent = kuerze(utxo.address, 12, 6);
    macheKopierbar(adresse, utxo.address, "Adresse");
  }

  const unten = block.querySelector(".utxo-kopf .knoten-unten-links");
  if (unten && (utxo.time_label || utxo.key)) {
    const ankunft = formatAnkunft(utxo);
    unten.replaceChildren();
    const utxoKennung = document.createElement("span");
    utxoKennung.className = "mono";
    utxoKennung.textContent = kuerze(utxo.key, 12, 8);
    macheKopierbar(utxoKennung, utxo.key, "UTXO (txid:vout)");
    unten.append(utxoKennung);
    if (ankunft) {
      unten.append(document.createTextNode(` · ${ankunft}`));
    }
  }
}

/** Unvollständiger Herkunftsbaum (Lücke, Abbruch, fehlender Prevout, …). */
function utxoHerkunftUnvollstaendig(utxo) {
  if (!utxo || !utxo.verfolgt) return false;
  if (utxo.unvollstaendig) return true;
  if (utxo.verfolgt_vollstaendig === false) return true;
  return false;
}

/** Marke „verfolgt · Datum" / „unvollständig · Datum" (rot) anpassen. */
function setzeVerfolgtMarke(oben, utxo) {
  if (!oben || !utxo || !utxo.verfolgt) return;
  const selektor =
    ".verfolgt-marke:not(.ausgegeben):not(.juengste-sats-marke):not(.ohne-herkunft-marke)";
  let marke = oben.querySelector(selektor);
  if (!marke) {
    marke = document.createElement("span");
    oben.append(marke);
  }
  const unvoll = utxoHerkunftUnvollstaendig(utxo);
  if (unvoll) {
    marke.className = "verfolgt-marke unvollstaendig";
  } else if (utxo.verfolgt_veraltet) {
    marke.className = "verfolgt-marke veraltet";
  } else {
    marke.className = "verfolgt-marke";
  }
  const wann = utxo.verfolgt_ts
    ? formatKurzdatum(utxo.verfolgt_ts * 1000)
    : "";
  if (unvoll) {
    marke.textContent = wann
      ? t("trace.incompleteWhen", { wann })
      : t("trace.incomplete");
    marke.title = t("trace.incompleteTitle");
  } else {
    marke.textContent = wann ? t("trace.followedWhen", { wann }) : t("trace.followed");
    marke.title = utxo.verfolgt_veraltet
      ? t("trace.followedStale")
      : t("trace.followedCached");
  }
}

function ersetzeJuengsteMarke(ort, marke) {
  if (!ort) return;
  const alt = ort.querySelector(".juengste-sats-marke");
  if (!marke) {
    if (alt) alt.remove();
    return;
  }
  if (alt) alt.replaceWith(marke);
  else {
    const betrag = ort.querySelector(".adress-betrag");
    if (betrag) betrag.before(marke);
    else ort.append(marke);
  }
}

function ersetzeOhneHerkunftMarke(ort, marke) {
  if (!ort) return;
  const alt = ort.querySelector(".ohne-herkunft-marke");
  if (!marke) {
    if (alt) alt.remove();
    return;
  }
  if (alt) alt.replaceWith(marke);
  else {
    const juengste = ort.querySelector(".juengste-sats-marke");
    if (juengste) juengste.after(marke);
    else {
      const betrag = ort.querySelector(".adress-betrag");
      if (betrag) betrag.before(marke);
      else ort.append(marke);
    }
  }
}

function setzeTraceDatenAmKnoten(knoten, utxo) {
  if (!knoten || !utxo) return;
  setzeUtxoTraceDaten(knoten, utxo);
}

/** Alle Adressköpfe (Wallet + Herkunft) zu dieser Adresse aktualisieren. */
function aktualisiereAdressgruppenJuengste(utxo) {
  let address = utxo.address || "";
  if (!address) {
    const knoten = document.querySelector(
      `.utxo-wurzel[data-key="${CSS.escape(utxo.key)}"], ` +
      `.utxo-zeile[data-key="${CSS.escape(utxo.key)}"]`,
    );
    const gruppeEl = knoten && knoten.closest(".adress-gruppe");
    if (gruppeEl) address = gruppeEl.dataset.address || "";
  }
  if (!address) return;

  const standListe = gruppeAusTraceListe(address, utxo.key);
  const gruppen = document.querySelectorAll(
    `.adress-gruppe[data-address="${CSS.escape(address)}"]`,
  );
  for (const gruppeEl of gruppen) {
    const kopf = gruppeEl.querySelector(".adress-kopf");
    if (!kopf) continue;
    const stand = standListe || gruppeAusDom(gruppeEl);
    if (!stand) continue;
    // Frisch getractes UTXO in den Stand mischen.
    const eintrag = (stand.utxos || []).find((u) => u.key === utxo.key);
    if (eintrag) {
      eintrag.verfolgt_vollstaendig = Boolean(utxo.verfolgt_vollstaendig);
      if (utxo.juengste_sats_ts) {
        eintrag.juengste_sats_ts = utxo.juengste_sats_ts;
      }
    }
    ersetzeJuengsteMarke(kopf, juengsteSatsMarke(juengsteSatsDerGruppe(stand)));
    ersetzeOhneHerkunftMarke(kopf, gruppeOhneHerkunftstraceMarke(stand));
  }
}

function zeichneJuengsteSatsNach(utxo) {
  const marke = juengsteSatsMarke(utxo);

  for (const wurzel of document.querySelectorAll(
    `.utxo-wurzel[data-key="${CSS.escape(utxo.key)}"]`,
  )) {
    setzeTraceDatenAmKnoten(wurzel, utxo);
    const oben = wurzel.querySelector(".knoten-oben");
    if (oben) {
      setzeVerfolgtMarke(oben, utxo);
      if (marke) ersetzeJuengsteMarke(oben, juengsteSatsMarke(utxo));
    }
  }

  for (const zeile of document.querySelectorAll(
    `.utxo-zeile[data-key="${CSS.escape(utxo.key)}"]`,
  )) {
    setzeTraceDatenAmKnoten(zeile, utxo);
    if (marke) ersetzeJuengsteMarke(zeile, juengsteSatsMarke(utxo));
  }

  aktualisiereAdressgruppenJuengste(utxo);
}

function formatAnkunft(utxo) {
  if (utxo && (utxo.receive_pending || (utxo.confirmed === false && !utxo.block_height))) {
    return t("trace.receivePending");
  }
  let wann = null;
  if (utxo && utxo.block_time) {
    wann = new Date(utxo.block_time * 1000);
  } else if (utxo && utxo.time_label) {
    const m = String(utxo.time_label).match(
      /(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?/,
    );
    if (m) {
      wann = new Date(
        Number(m[3]), Number(m[2]) - 1, Number(m[1]),
        Number(m[4]), Number(m[5]), Number(m[6] || 0),
      );
    }
  }
  if (!wann || Number.isNaN(wann.getTime())) {
    return (utxo && utxo.time_label) || "—";
  }
  const datum = wann.toLocaleDateString(formatLocale(), {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
  const uhr = wann.toLocaleTimeString(formatLocale(), {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  return t("trace.arrival", { datum, uhr });
}

function logZeitstempel(wann = new Date()) {
  const datum = wann.toLocaleDateString(formatLocale(), {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
  const uhr = wann.toLocaleTimeString(formatLocale(), {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  return `${datum} ${uhr}`;
}

function logIstWichtig(text) {
  // Erfolg, Misserfolg und die Diagnose danach. Fortschritt
  // (Verbinde, Fallback, Tor-Start, Bootstrap) bleibt normal.
  // JOB-START/JOB-ENDE: Dauer langer Sammelläufe greppbar und sichtbar.
  return /^(JOB-START|JOB-ENDE|Verbunden\.|Verbindung fehlgeschlagen|TLS-Handshake fehlgeschlagen|Port geschlossen|Zertifikat nicht überprüfbar|Verbindung ohne TLS abgebrochen|Wechsel:|Neuer Peer |Peer .+ ausgefallen|Header-Cache fertig|Port 8333 wirkt blockiert|Filter-Treffer|Nur \d+)/.test(
    String(text),
  );
}

/**
 * Hängt eine Zeile an das Log-Feld. Nur diese Fläche, kein Umleiten der Konsole.
 *
 * Ankündigung vor dem Schritt, nicht danach: der Benutzer soll sehen, was
 * als Nächstes passiert, nicht was schon vorbei ist.
 *
 * *wallet*: Name nach dem Timestamp, nur wenn die Aktion zu einem Wallet
 * gehört. Verbindungstest und Listen bleiben ohne.
 *
 * Rückgabe: das DOM-Element der Zeile (für spätere In-place-Updates).
 */
function logZeile(text, wichtig, wallet) {
  const ziel = $("#log-text");
  if (!ziel) return null;
  const roh = String(text ?? "");
  // Wichtigkeit am Original (DE-Muster); Anzeige ggf. übersetzt.
  const zeile = document.createElement("div");
  zeile.className = (wichtig ?? logIstWichtig(roh)) ? "log-zeile log-wichtig" : "log-zeile";

  const zeit = document.createElement("span");
  zeit.className = "log-zeit";
  zeit.textContent = logZeitstempel();
  zeile.append(zeit);

  const name = String(wallet || "").trim();
  if (name) {
    const marke = document.createElement("span");
    marke.className = "log-wallet";
    marke.textContent = name;
    zeile.append("  ", marke);
  }

  const meldung = document.createElement("span");
  meldung.className = "log-meldung";
  meldung.textContent = übersetzeLogText(roh);
  zeile.append("  ", meldung);

  const amEnde = ziel.scrollHeight - ziel.scrollTop - ziel.clientHeight < 28;
  ziel.append(zeile);
  if (amEnde) ziel.scrollTop = ziel.scrollHeight;
  return zeile;
}

/** Text einer schon gezeigten Log-Zeile ändern (Filter-Treffer-Ergebnis). */
function aktualisiereLogZeile(knoten, text, wichtig) {
  if (!knoten) return;
  const roh = String(text ?? "");
  const meldung = knoten.querySelector(".log-meldung");
  if (meldung) meldung.textContent = übersetzeLogText(roh);
  const istWichtig = wichtig ?? logIstWichtig(roh);
  knoten.classList.toggle("log-wichtig", Boolean(istWichtig));
}

function übersetzeLogText(roh) {
  if (typeof window.übersetzeLogZeile === "function") {
    return window.übersetzeLogZeile(roh);
  }
  return String(roh ?? "");
}

/**
 * Job-Log nachziehen: neue Zeilen anhängen; geänderte (ersetzt) Zeilen
 * in place aktualisieren — z. B. „hole Block…“ → „False Positive“.
 */
function nimmLogZeilen(job, stand, wallet) {
  const zeilen = job.log || [];
  if (!stand.knoten) stand.knoten = [];
  if (!stand.texte) stand.texte = [];
  const bis = Math.min(stand.index, zeilen.length, stand.knoten.length);
  for (let i = 0; i < bis; i += 1) {
    if (zeilen[i] !== stand.texte[i]) {
      stand.texte[i] = zeilen[i];
      aktualisiereLogZeile(stand.knoten[i], zeilen[i]);
    }
  }
  for (; stand.index < zeilen.length; stand.index += 1) {
    const text = zeilen[stand.index];
    stand.texte[stand.index] = text;
    stand.knoten[stand.index] = logZeile(text, undefined, wallet);
  }
}

function setzeLogSichtbar(an) {
  const sichtbar = Boolean(an);
  const buehne = document.querySelector(".buehne");
  if (buehne) buehne.classList.toggle("log-an", sichtbar);
  const knopf = $("#log-anzeige");
  if (knopf) {
    knopf.classList.toggle("aktiv", sichtbar);
    knopf.setAttribute("aria-pressed", sichtbar ? "true" : "false");
  }
}

const LOG_HOEHE_MERKER = "xpq-log-hoehe";

function macheLogZiehbar() {
  const zieher = $("#log-zieher");
  const pane = $("#dock") || $("#log-pane");
  const buehne = document.querySelector(".buehne");
  if (!zieher || !pane || !buehne) return;

  try {
    const gemerkt = localStorage.getItem(LOG_HOEHE_MERKER);
    if (gemerkt) buehne.style.setProperty("--log-hoehe", gemerkt);
  } catch (_) {
    /* ohne Speicher bleibt die Vorgabe */
  }

  let startY = 0;
  let startH = 0;
  let zieht = false;

  const beenden = (ereignis) => {
    if (!zieht) return;
    zieht = false;
    try {
      zieher.releasePointerCapture(ereignis.pointerId);
    } catch (_) {
      /* Capture war schon weg */
    }
    const wert = getComputedStyle(buehne).getPropertyValue("--log-hoehe").trim();
    if (wert) {
      try {
        localStorage.setItem(LOG_HOEHE_MERKER, wert);
      } catch (_) {
        /* gleichgültig */
      }
    }
  };

  zieher.addEventListener("pointerdown", (ereignis) => {
    if (ereignis.button !== 0) return;
    zieht = true;
    startY = ereignis.clientY;
    startH = pane.getBoundingClientRect().height;
    zieher.setPointerCapture(ereignis.pointerId);
    ereignis.preventDefault();
  });
  zieher.addEventListener("pointermove", (ereignis) => {
    if (!zieht) return;
    const max = Math.max(120, buehne.clientHeight * 0.7);
    const hoehe = Math.min(max, Math.max(72, startH + (startY - ereignis.clientY)));
    buehne.style.setProperty("--log-hoehe", `${Math.round(hoehe)}px`);
  });
  zieher.addEventListener("pointerup", beenden);
  zieher.addEventListener("pointercancel", beenden);
}

const DOCK_SPALTE_MERKER = "xpq-dock-spalte";
const EMPFANG_SPALTE_MERKER = "xpq-dock-empfang";

const EMPFANG_POLL_MS = 12_000;

/** QR-Matrix → SVG (lokal, kein CDN). */
function empfangQrSvg(text, { dunkel = false } = {}) {
  if (typeof window.QR !== "function" || !text) return "";
  let matrix;
  try {
    matrix = window.QR(String(text));
  } catch (_) {
    return "";
  }
  if (!matrix || !matrix.length) return "";
  const n = matrix.length;
  const quiet = 2;
  const size = n + quiet * 2;
  const teile = [];
  for (let y = 0; y < n; y++) {
    const zeile = matrix[y];
    if (!zeile) continue;
    for (let x = 0; x < n; x++) {
      if (zeile[x]) teile.push(`M${x + quiet},${y + quiet}h1v1h-1z`);
    }
  }
  // Dunkel: nur Graustufen — nicht scannbar/beruhigend beim „Denken“.
  const bg = dunkel ? "#111111" : "#fff";
  const fg = dunkel ? "#9a9a9a" : "#000";
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" ` +
    `shape-rendering="crispEdges" role="img" aria-hidden="true">` +
    `<rect width="100%" height="100%" fill="${bg}"/>` +
    `<path fill="${fg}" d="${teile.join("")}"/></svg>`
  );
}

/**
 * Herzschlag: gedimmter QR nur durch Glyph-Maske sichtbar — nie scanbar.
 * Atem = QR-Alpha; Zyklus ₿ → sat → Pfeife → Lupe → ∞/21M (→ Student wenn Lernhinweise).
 */
const EmpfangPuls = (() => {
  let raf = 0;
  let startTs = 0;
  let maskeIx = 0;
  let gewechseltInZyklus = false;
  let canvas = null;
  let ctx = null;
  let qrBmp = null; // ImageData-fertig gerendertes QR (volle Fläche)
  let qrSeite = 0;
  let maskLuma = {}; // art → Uint8ClampedArray luma 0..255
  const MASK_SRC = {
    btc: "/img/bitcoin-mask.png",
    sat: "/img/sat-mask.png",
    pfeiffe: "/img/pfeiffe-mask.png",
    student: "/img/student-mask.png",
    lupe: "/img/lupe-mask.png",
    unendlich21m: "/img/unendlich21m-mask.png",
  };
  // Gleicher Hintergrund für alle Masken (dark: schwarz; light ggf. später).
  const MASK_BG = {
    btc: "#000000",
    sat: "#000000",
    pfeiffe: "#000000",
    student: "#000000",
    lupe: "#000000",
    unendlich21m: "#000000",
  };

  function maskenListe() {
    // Basis-Zyklus; Student nur mit „Lernhinweise für Plebs“.
    const basis = ["btc", "sat", "pfeiffe", "lupe", "unendlich21m"];
    if (typeof lernhinweiseAn === "function" && lernhinweiseAn()) {
      return [...basis, "student"];
    }
    return basis;
  }

  const PAYLOADS = [
    "satsage:denken",
    "satsage:warten",
    "satsage:suchen",
    "satsage:atmen",
  ];
  // Pro Atemzug über dem QR — feste Ketten nicht auseinanderreißen:
  // dies→das→ananas; Mine…→Scams→Bootsunfall→Frage→sauer.
  function atemWorte() {
  const w = [];
  for (let i = 0; i < 25; i++) w.push(t("receive.breath." + i));
  return w;
}

  let payloadIx = 0;
  let wortIx = 0;
  /** Noch so viele Atemzüge mit dem aktuellen funny Text (2–4, neu gewürfelt). */
  let wortAtemRest = 0;
  const ATEM_MS = 2200;
  /** Sonderatem: orangeB | ohNo | incoming */
  let sonderQueue = [];
  let sonder = null; // { typ, t0, phase?, walletId? }
  const BTC_ORANGE = { r: 247, g: 147, b: 26 };

  function wuerfleWortAtemRest() {
    return 2 + Math.floor(Math.random() * 3); // 2, 3 oder 4
  }

  function setzeAtemKopfStil({ mehrzeilig = false, mono = false } = {}) {
    const kopf = $("#empfang-kopf");
    if (!kopf) return;
    kopf.classList.toggle("empfang-kopf--mehrzeilig", Boolean(mehrzeilig));
    kopf.classList.toggle("empfang-kopf--mono", Boolean(mono));
  }

  function setzeAtemWort(fest) {
    const kopf = $("#empfang-kopf");
    if (!kopf) return;
    if (fest != null && fest !== "") {
      kopf.textContent = String(fest);
      return;
    }
    setzeAtemKopfStil({});
    const wort = atemWorte()[wortIx % atemWorte().length];
    kopf.textContent = wort;
    if (wortAtemRest <= 0) wortAtemRest = wuerfleWortAtemRest();
  }

  function setzeAtemTextSicht(sicht) {
    const kopf = $("#empfang-kopf");
    if (!kopf) return;
    if (!document.querySelector(".empfang-pane--puls")) {
      kopf.style.opacity = "";
      kopf.style.color = "";
      return;
    }
    const s = Math.max(0, Math.min(1, sicht));
    kopf.style.opacity = String(s);
    const dark = (typeof liesUiTheme === "function" ? liesUiTheme() : "dark") !== "light";
    // Farbe mitatmen: dimm ↔ hell
    if (dark) {
      const v = Math.round(90 + 150 * s);
      kopf.style.color = `rgb(${v},${v},${v})`;
    } else {
      const v = Math.round(180 - 140 * s);
      kopf.style.color = `rgb(${v},${v},${v})`;
    }
  }

  function stop(opts) {
    const force = Boolean(opts && opts.force);
    // Incoming/Konfetti und Orange-₿ (UTXO-Fund): nicht von zeichneEmpfang/Poll
    // /Scan-Refresh abwürgen — Animation soll zu Ende laufen.
    if (
      !force
      && (
        incomingAktiv
        || (sonder && (sonder.typ === "incoming" || sonder.typ === "orangeB"))
        || sonderQueue.some(
          (s) => s && (s.typ === "incoming" || s.typ === "orangeB"),
        )
      )
    ) {
      return;
    }
    if (force) {
      incomingAktiv = false;
      incomingOnDone = null;
      incomingKonfettiFertig = true;
    }

    const pane = $("#empfang-pane");
    const warAn = Boolean(
      raf
      || sonder
      || sonderQueue.length
      || (pane && pane.classList.contains("empfang-pane--puls")),
    );
    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    startTs = 0;
    gewechseltInZyklus = false;
    sonderQueue = [];
    sonder = null;
    // Ohne laufende Animation den normalen Empfangs-QR nicht zerstören
    // (Tip-Sync-Ende fremdes Wallet rief stop() und wischte Firmung-QR weg).
    if (!warAn) return;
    if (pane) pane.classList.remove("empfang-pane--puls", "empfang-pane--konfetti");
    const qr = $("#empfang-qr");
    if (qr) {
      qr.classList.remove("empfang-qr--puls");
      qr.replaceChildren();
    }
    const maske = $("#empfang-qr-maske");
    if (maske) {
      maske.hidden = true;
      maske.replaceChildren();
    }
    const kopf = $("#empfang-kopf");
    if (kopf) {
      kopf.textContent = t("dock.empfangHead");
      kopf.style.opacity = "";
      kopf.style.color = "";
      kopf.classList.remove("empfang-kopf--mehrzeilig", "empfang-kopf--mono");
    }
    const konfetti = document.getElementById("empfang-konfetti");
    if (konfetti) konfetti.remove();
    canvas = null;
    ctx = null;
    qrBmp = null;
    qrSeite = 0;
  }

  function ensureRunning() {
    if (!raf) start();
  }

  function queueSonder(eintrag) {
    sonderQueue.push(eintrag);
    ensureRunning();
  }

  /**
   * Oranges ₿-Glyph: Größe 15 %…90 % der QR-Seite, log1p von Dust (500) bis 500 k.
   * Unter 500 sats keine Animation. Ab 500 k → 90 %.
   */
  const ORANGE_B_MIN = 0.15;
  const ORANGE_B_MAX = 0.90;
  const ORANGE_B_DUST_SATS = 500;
  const ORANGE_B_CAP_SATS = 500_000;

  function orangeBScaleFromSats(sats) {
    const s = Math.max(0, Number(sats) || 0);
    if (s < ORANGE_B_DUST_SATS) return null;
    if (s >= ORANGE_B_CAP_SATS) return ORANGE_B_MAX;
    // log1p relativ zu Dust…Cap (wie Haltefrist-Y: log1p-Anteil).
    const logLo = Math.log1p(ORANGE_B_DUST_SATS);
    const logHi = Math.log1p(ORANGE_B_CAP_SATS);
    const t = (Math.log1p(s) - logLo) / (logHi - logLo);
    return ORANGE_B_MIN + Math.max(0, Math.min(1, t)) * (ORANGE_B_MAX - ORANGE_B_MIN);
  }

  /** Orange-B läuft oder steht in der Queue — keine Nachklapp-Animationen. */
  function istOrangeB() {
    if (sonder && sonder.typ === "orangeB") return true;
    return sonderQueue.some((s) => s && s.typ === "orangeB");
  }

  /**
   * UTXO gefunden: ein oranger ₿-Atemzug (nur ab 500 sats).
   * Läuft bereits eine Orange-B-Animation (oder wartet in der Queue), werden
   * weitere Funde still verworfen — laufende Animation läuft zu Ende.
   */
  function flashOrangeB(sats) {
    if (istOrangeB()) return;
    const betrag = Number(sats);
    if (!Number.isFinite(betrag) || betrag < ORANGE_B_DUST_SATS) return;
    const bScale = orangeBScaleFromSats(betrag);
    if (bScale == null) return;
    queueSonder({
      typ: "orangeB",
      sats: betrag,
      bScale,
      halteDanach: typeof empfangScanLaeuftFuer === "function"
        && empfangScanLaeuftFuer(Zustand.walletId),
    });
  }

  function flashOhNo() {
    queueSonder({
      typ: "ohNo",
      halteDanach: typeof empfangScanLaeuftFuer === "function"
        && empfangScanLaeuftFuer(Zustand.walletId),
    });
  }

  /** True solange TxIN-Jubel (Text und/oder Konfetti) aktiv ist. */
  let incomingAktiv = false;
  let incomingOnDone = null;
  let incomingKonfettiFertig = true;

  function _incomingFertigPruefen() {
    if (!incomingAktiv) return;
    if (!incomingKonfettiFertig) return;
    // Noch Sonderatem „incoming“ in Queue/RAF → warten.
    if (sonder && sonder.typ === "incoming") return;
    if (sonderQueue.some((s) => s && s.typ === "incoming")) return;
    incomingAktiv = false;
    const cb = incomingOnDone;
    incomingOnDone = null;
    if (typeof cb === "function") {
      try {
        cb();
      } catch (_) {
        /* optional */
      }
    }
  }

  function flashIncoming(walletId, sats, konfettiOpts) {
    const wid = walletId || Zustand.walletId;
    // auto: < 1 Mio bunt, ≥ 1 Mio alle Schnipsel gold/silber (goldAb überschreibbar)
    const opts = Object.assign({ modus: "auto", goldAb: 1_000_000 }, konfettiOpts || {});
    if (sats != null && sats !== "" && Number.isFinite(Number(sats))) {
      opts.sats = Number(sats);
    } else if (opts.sats == null || opts.sats === "" || !Number.isFinite(Number(opts.sats))) {
      // Ohne Betrag: trotzdem sichtbare Schnipsel (nicht 0 → leere Kanone optisch).
      opts.sats = 100_000;
    }
    const onDone = typeof opts.onDone === "function" ? opts.onDone : null;
    delete opts.onDone;
    const halte = opts.halteDanach != null
      ? Boolean(opts.halteDanach)
      : (typeof empfangScanLaeuftFuer === "function" && empfangScanLaeuftFuer(wid));
    delete opts.halteDanach;

    incomingAktiv = true;
    incomingOnDone = onDone;
    incomingKonfettiFertig = false;

    // Konfetti SOFORT — nicht erst nach 420 ms Fadeout (der oft abgewürgt wurde).
    try {
      starteKonfetti(opts, () => {
        incomingKonfettiFertig = true;
        if (sonder && sonder.typ === "incoming") {
          sonder.konfettiFertig = true;
        }
        _incomingFertigPruefen();
      });
    } catch (_) {
      incomingKonfettiFertig = true;
    }

    // Pane sichtbar + Ka-Ching-Text, auch wenn noch kein Puls-RAF lief.
    const pane = $("#empfang-pane");
    const leer = $("#empfang-leer");
    const inhalt = $("#empfang-inhalt");
    if (pane) pane.classList.add("empfang-pane--puls", "empfang-pane--konfetti");
    if (leer) leer.hidden = true;
    if (inhalt) inhalt.hidden = false;
    setzeAtemWort("Ka-Ching!");
    setzeAtemTextSicht(1);

    queueSonder({
      typ: "incoming",
      walletId: wid,
      sats: opts.sats,
      konfettiOpts: opts,
      halteDanach: halte,
      // onDone nur über _incomingFertigPruefen (Konfetti + Atem-Ende).
      konfettiBereitsGestartet: true,
    });
  }

  /** TxIN-/Konfetti-Sonderatem läuft (QR darf nicht überschrieben werden). */
  function istIncoming() {
    if (incomingAktiv) return true;
    if (sonder && sonder.typ === "incoming") return true;
    return sonderQueue.some((s) => s && s.typ === "incoming");
  }

  /** Tx im Block bestätigt — grüner Haken, einen Atemzug. */
  function flashHaken() {
    queueSonder({
      typ: "haken",
      halteDanach: typeof empfangScanLaeuftFuer === "function"
        && empfangScanLaeuftFuer(Zustand.walletId),
    });
  }

  /** Neuer Chain-Tip: Atem 1 „NEUER BLOCK“, Atem 2 Blockhöhe (Mono). */
  function flashNeuerBlock(hoehe) {
    const n = Number(hoehe);
    queueSonder({
      typ: "neuerBlock",
      hoehe: Number.isFinite(n) ? Math.trunc(n) : hoehe,
      halteDanach: typeof empfangScanLaeuftFuer === "function"
        && empfangScanLaeuftFuer(Zustand.walletId),
    });
  }

  function formatBlockHoeheAtem(hoehe) {
    const n = Number(hoehe);
    if (!Number.isFinite(n)) return String(hoehe ?? "");
    try {
      return Math.trunc(n).toLocaleString("de-DE");
    } catch (_) {
      return String(Math.trunc(n));
    }
  }

  function beendeSonderWennIdle(halteDanach) {
    if (halteDanach || sonderQueue.length) return;
    // Nach Event-Atem wieder Empfangsadresse, wenn kein Scan/Sync läuft.
    setTimeout(() => {
      if (raf && !sonder && !sonderQueue.length) {
        stop();
        if (Zustand.walletId && !Zustand.lernThema) {
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
    }, 0);
  }

  function ladeBild(src) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  async function bereiteMaskeLuma(art, seite) {
    const key = `${art}@${seite}`;
    if (maskLuma[key]) return maskLuma[key];
    const img = await ladeBild(MASK_SRC[art]);
    if (!img) return null;
    const c = document.createElement("canvas");
    c.width = seite;
    c.height = seite;
    const cctx = c.getContext("2d");
    cctx.drawImage(img, 0, 0, seite, seite);
    const data = cctx.getImageData(0, 0, seite, seite).data;
    const luma = new Uint8Array(seite * seite);
    for (let i = 0, p = 0; i < data.length; i += 4, p++) {
      luma[p] = (data[i] + data[i + 1] + data[i + 2]) / 3;
    }
    maskLuma[key] = luma;
    return luma;
  }

  function stelleCanvas() {
    const host = $("#empfang-qr");
    if (!host) return null;
    if (!canvas) {
      canvas = document.createElement("canvas");
      canvas.className = "empfang-puls-canvas";
      canvas.setAttribute("aria-hidden", "true");
      host.replaceChildren(canvas);
      ctx = canvas.getContext("2d");
    } else if (!host.contains(canvas)) {
      host.replaceChildren(canvas);
    }
    // Seite = größtes Quadrat in der Wrap-Box (CSS: min(cqw,cqh)); Host selbst
    // kann vor dem ersten Layout noch 0 sein.
    const box = host.closest(".empfang-qr-wrap") || host;
    const amHost = Math.min(host.clientWidth || 0, host.clientHeight || 0);
    const amBox = Math.min(box.clientWidth || 160, box.clientHeight || 160);
    const seite = Math.max(64, Math.floor(amHost > 0 ? amHost : amBox));
    if (canvas.width !== seite || canvas.height !== seite) {
      canvas.width = seite;
      canvas.height = seite;
      qrBmp = null;
      qrSeite = 0;
    }
    return canvas;
  }

  function baueQrBitmap(seite) {
    if (qrBmp && qrSeite === seite) return Promise.resolve(qrBmp);
    const payload = PAYLOADS[payloadIx % PAYLOADS.length];
    const svg = empfangQrSvg(payload, { dunkel: true });
    if (!svg) return Promise.resolve(null);
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement("canvas");
        c.width = seite;
        c.height = seite;
        const qctx = c.getContext("2d");
        qctx.fillStyle = "#111111";
        qctx.fillRect(0, 0, seite, seite);
        qctx.drawImage(img, 0, 0, seite, seite);
        const data = qctx.getImageData(0, 0, seite, seite);
        // Harte Graustufen — keine Brauntöne aus SVG/Skalierung.
        const d = data.data;
        for (let i = 0; i < d.length; i += 4) {
          const g = Math.round((d[i] + d[i + 1] + d[i + 2]) / 3);
          d[i] = d[i + 1] = d[i + 2] = g;
          d[i + 3] = 255;
        }
        qrBmp = data;
        qrSeite = seite;
        resolve(qrBmp);
      };
      img.onerror = () => resolve(null);
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    });
  }

  function zeichneOhNoMaske(seite, aScale, dark, herzScale = 1) {
    const bg = dark ? 0 : 255;
    const out = ctx.createImageData(seite, seite);
    const od = out.data;
    for (let i = 0; i < od.length; i += 4) {
      od[i] = od[i + 1] = od[i + 2] = bg;
      od[i + 3] = 255;
    }
    ctx.putImageData(out, 0, 0);
    const s = Math.max(0.1, Math.min(1, Number(herzScale) || 1));
    ctx.save();
    ctx.globalAlpha = Math.max(0, Math.min(1, aScale));
    ctx.translate(seite / 2, seite / 2);
    ctx.scale(s, s);
    ctx.fillStyle = dark ? "#fff" : "#111";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    // Zwei Zeilen füllen zusammen ~80 % der Quadratfläche.
    const fs = Math.max(28, Math.floor(seite * 0.38));
    ctx.font = `bold ${fs}px system-ui, sans-serif`;
    ctx.fillText("OH", 0, seite * (0.34 - 0.5));
    ctx.fillText("NO!", 0, seite * (0.70 - 0.5));
    ctx.restore();
  }

  function zeichneHakenMaske(seite, aScale, dark, herzScale = 1) {
    const bg = dark ? 0 : 255;
    const out = ctx.createImageData(seite, seite);
    const od = out.data;
    for (let i = 0; i < od.length; i += 4) {
      od[i] = od[i + 1] = od[i + 2] = bg;
      od[i + 3] = 255;
    }
    ctx.putImageData(out, 0, 0);
    const s = Math.max(0.1, Math.min(1, Number(herzScale) || 1));
    ctx.save();
    ctx.globalAlpha = Math.max(0, Math.min(1, aScale));
    ctx.translate(seite / 2, seite / 2);
    ctx.scale(s, s);
    ctx.fillStyle = "#3ddc84"; // grüner Haken
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    // ~80 % der Quadratseite
    const fs = Math.max(40, Math.floor(seite * 0.8));
    ctx.font = `bold ${fs}px system-ui, "Segoe UI Symbol", "Apple Color Emoji", sans-serif`;
    ctx.fillText("✓", 0, fs * 0.06);
    ctx.restore();
  }

  async function zeichneGlyphAtem(
    sichtQr,
    { art, orange = false, nurSchwarz = false, bScale } = {},
  ) {
    const c = stelleCanvas();
    if (!c || !ctx) return;
    const seite = c.width;
    const dark = (typeof liesUiTheme === "function" ? liesUiTheme() : "dark") !== "light";
    const bg = dark ? 0 : 255;
    const glow = dark ? 255 : 0;
    const aScale = Math.max(0, Math.min(1, sichtQr));
    // Herzschlag: Maske 10 %↔100 % mitskalieren (parallel zum Fade).
    const herzScale = 0.1 + 0.9 * aScale;

    if (nurSchwarz) {
      ctx.fillStyle = dark ? "#000" : "#fff";
      ctx.fillRect(0, 0, seite, seite);
      return;
    }

    if (art === "ohNo") {
      zeichneOhNoMaske(seite, aScale, dark, herzScale);
      return;
    }
    if (art === "haken") {
      zeichneHakenMaske(seite, aScale, dark, herzScale);
      return;
    }

    // Oranges ₿: feste Sats-Skala; normaler Atem: herzScale zentriert.
    let maskSeite = seite;
    let maskOx = 0;
    let maskOy = 0;
    let lumaSeite = seite;
    if (orange && (art || "btc") === "btc") {
      const scale = Math.max(
        ORANGE_B_MIN,
        Math.min(
          ORANGE_B_MAX,
          Number.isFinite(Number(bScale)) && Number(bScale) > 0
            ? Number(bScale)
            : ORANGE_B_MAX,
        ),
      );
      maskSeite = Math.max(8, Math.floor(seite * scale));
      maskOx = Math.floor((seite - maskSeite) / 2);
      maskOy = maskOx;
      lumaSeite = maskSeite;
    } else {
      // Luma immer full-size cachen; nur die Abtastung skaliert (kein Cache-Sturm).
      maskSeite = Math.max(8, seite * herzScale);
      maskOx = (seite - maskSeite) / 2;
      maskOy = maskOx;
      lumaSeite = seite;
    }

    const luma = await bereiteMaskeLuma(art || "btc", lumaSeite);
    const qr = orange ? null : await baueQrBitmap(seite);
    const out = ctx.createImageData(seite, seite);
    const od = out.data;
    const qd = qr ? qr.data : null;
    const innen = new Uint8Array(seite * seite);
    // Innen-Karte in Canvas-Koordinaten (skalierte Maske → Glow-Rand).
    if (luma && !orange) {
      const inv = maskSeite > 0 ? lumaSeite / maskSeite : 1;
      for (let y = 0, p = 0; y < seite; y++) {
        for (let x = 0; x < seite; x++, p++) {
          const mx = (x - maskOx) * inv;
          const my = (y - maskOy) * inv;
          if (mx < 0 || my < 0 || mx >= lumaSeite || my >= lumaSeite) continue;
          const mp = (my | 0) * lumaSeite + (mx | 0);
          if (luma[mp] >= 120) innen[p] = 1;
        }
      }
    }

    for (let y = 0, p = 0; y < seite; y++) {
      for (let x = 0; x < seite; x++, p++) {
        const i = p * 4;
        let maskA = 0;
        if (luma) {
          if (orange) {
            const mx = x - maskOx;
            const my = y - maskOy;
            if (mx >= 0 && my >= 0 && mx < maskSeite && my < maskSeite) {
              const mp = (my | 0) * lumaSeite + (mx | 0);
              maskA = Math.max(0, Math.min(1, (luma[mp] - 40) / 180));
            }
          } else {
            const inv = maskSeite > 0 ? lumaSeite / maskSeite : 1;
            const mx = (x - maskOx) * inv;
            const my = (y - maskOy) * inv;
            if (mx >= 0 && my >= 0 && mx < lumaSeite && my < lumaSeite) {
              const mp = (my | 0) * lumaSeite + (mx | 0);
              maskA = Math.max(0, Math.min(1, (luma[mp] - 40) / 180));
            }
          }
        }
        let r = bg;
        let g = bg;
        let b = bg;
        if (maskA > 0.02 && aScale > 0) {
          const a = aScale * maskA;
          if (orange) {
            r = Math.round(BTC_ORANGE.r * a + bg * (1 - a));
            g = Math.round(BTC_ORANGE.g * a + bg * (1 - a));
            b = Math.round(BTC_ORANGE.b * a + bg * (1 - a));
          } else if (qd) {
            const qg = qd[i];
            r = g = b = Math.round(qg * a + bg * (1 - a));
          }
        }
        if (innen[p] && !orange) {
          let rand = false;
          if (x === 0 || y === 0 || x === seite - 1 || y === seite - 1) {
            rand = true;
          } else if (
            !innen[p - 1] || !innen[p + 1]
            || !innen[p - seite] || !innen[p + seite]
          ) {
            rand = true;
          }
          if (rand && aScale > 0.01) {
            const glowA = aScale;
            r = Math.round(glow * glowA + r * (1 - glowA));
            g = Math.round(glow * glowA + g * (1 - glowA));
            b = Math.round(glow * glowA + b * (1 - glowA));
          }
        }
        od[i] = r;
        od[i + 1] = g;
        od[i + 2] = b;
        od[i + 3] = 255;
      }
    }
    ctx.putImageData(out, 0, 0);
  }

  /**
   * Sats → Geldscheine (greedy, auf 10 gerundet).
   * Losgrößen: 100000, 10000, 1000, 100, 10. Staub = 10.
   */
  function konfettiScheineAusSats(sats) {
    let rest = Math.max(0, Math.round(Number(sats) / 10) * 10);
    if (rest <= 0 && Number(sats) > 0) rest = 10; // unter 5 → 0; 5–9 → 10
    if (rest <= 0) rest = 100_000; // Fallback: sichtbarer Schuss
    const denoms = [100000, 10000, 1000, 100, 10];
    const scheine = [];
    for (const d of denoms) {
      const n = Math.floor(rest / d);
      for (let i = 0; i < n; i++) scheine.push(d);
      rest -= n * d;
    }
    return scheine;
  }

  /** Pixelgröße je Schein — 100k ≈ 2× bisherige max. Länge. */
  function konfettiGroesseFuerSchein(denom) {
    switch (denom) {
      case 10:
        return { w0: 1.5, h: 1.5 }; // Staub (sichtbar)
      case 100:
        return { w0: 3 + Math.random() * 1.2, h: 1.2 + Math.random() * 0.5 };
      case 1000:
        return { w0: 6 + Math.random() * 2.5, h: 1.8 + Math.random() * 0.7 };
      case 10000:
        return { w0: 10 + Math.random() * 3.5, h: 2.4 + Math.random() * 0.9 };
      case 100000:
        return { w0: 16 + Math.random() * 6, h: 3.8 + Math.random() * 1.8 };
      default:
        return { w0: 6, h: 2 };
    }
  }

  /**
   * Kalibrierte Defaults (animdebug-Regler / Lab):
   * Impuls 500, Streu 80 %, Grav 5, Luft 2, Winkel 30–80°, Dauer 3 s,
   * Gold ab 1 Mio, +25 Staub je Schuss.
   */
  const KONFETTI_DEFAULTS = {
    goldAb: 1_000_000,
    impuls: 500,
    impulsStreu: 80,
    grav: 5,
    luft: 2,
    winkelMin: 30,
    winkelMax: 80,
    dauer: 3000,
    staubExtra: 25,
  };

  function konfettiParamsAusSats(sats, overrides) {
    const o = overrides || {};
    const goldAb = Math.max(2, Number(o.goldAb) || KONFETTI_DEFAULTS.goldAb);
    let s = Math.max(0, Number(sats != null && sats !== "" ? sats : o.sats) || 0);
    if (s <= 0) s = 100_000;
    const modus = o.modus || "auto"; // auto | bunt | gold
    let gold = s >= goldAb;
    if (modus === "bunt") gold = false;
    if (modus === "gold") gold = true;
    // Stärke nur für Anzeige / Sats→Impuls-Vorschlag — Physik nutzt Impuls.
    const ref = Math.min(Math.max(1, s), goldAb - 1);
    const staerkeAuto = Math.min(
      1,
      Math.log10(Math.max(1, ref)) / Math.log10(Math.max(2, goldAb - 1)),
    );
    let staerke = staerkeAuto;
    if (o.staerke != null && o.staerke !== "" && Number(o.staerke) >= 0) {
      staerke = Math.max(0, Math.min(1, Number(o.staerke)));
    }
    // Impuls: Override oder Default 500 (volle Kanone). Optional aus Stärke ableiten.
    let impuls = Number(o.impuls);
    if (!Number.isFinite(impuls) || impuls <= 0) {
      if (o.impulsAusStaerke) {
        impuls = 5 + staerke * 495;
      } else {
        impuls = KONFETTI_DEFAULTS.impuls;
      }
    }
    impuls = Math.max(5, Math.min(500, impuls));
    const impulsStreu = Math.max(
      0,
      Math.min(90, Number(o.impulsStreu != null ? o.impulsStreu : KONFETTI_DEFAULTS.impulsStreu)),
    ) / 100;
    // Mündungsgeschwindigkeit relativ zur QR-Seite (bei Impuls 500 ≈ 0.15·seite/Frame-Einheit).
    const speed = 0.04 + (impuls / 500) * 0.14;
    const grav = Math.max(
      0,
      Math.min(100, Number(o.grav != null && o.grav !== "" ? o.grav : KONFETTI_DEFAULTS.grav)),
    );
    let scheine = konfettiScheineAusSats(s);
    const staubExtra = Math.max(
      0,
      Math.min(80, Number(o.staubExtra != null ? o.staubExtra : KONFETTI_DEFAULTS.staubExtra)),
    );
    for (let i = 0; i < staubExtra; i++) scheine.push(10);
    const maxParts = 220;
    if (scheine.length > maxParts) {
      const wert = scheine.filter((d) => d > 10);
      const staub = scheine.filter((d) => d === 10);
      const room = Math.max(0, maxParts - wert.length);
      scheine = wert.concat(staub.slice(0, room));
    }
    const zählung = { 10: 0, 100: 0, 1000: 0, 10000: 0, 100000: 0 };
    for (const d of scheine) zählung[d] = (zählung[d] || 0) + 1;
    return {
      sats: s,
      gold,
      goldAb,
      modus,
      staerke,
      staerkeAuto,
      impuls,
      impulsStreu,
      grav,
      scheine,
      zählung,
      count: scheine.length,
      dauer: Math.max(1000, Math.min(60000, Number(o.dauer) || KONFETTI_DEFAULTS.dauer)),
      winkelMin: Number(o.winkelMin != null ? o.winkelMin : KONFETTI_DEFAULTS.winkelMin),
      winkelMax: Number(o.winkelMax != null ? o.winkelMax : KONFETTI_DEFAULTS.winkelMax),
      luft: Math.max(
        0,
        Math.min(100, Number(o.luft != null && o.luft !== "" ? o.luft : KONFETTI_DEFAULTS.luft)),
      ),
      speed,
      staubExtra,
    };
  }

  function _hexRgb(hex) {
    const h = hex.replace("#", "");
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
    ];
  }

  function _lerpRgb(a, b, t) {
    const u = Math.max(0, Math.min(1, t));
    return `rgb(${Math.round(a[0] + (b[0] - a[0]) * u)},${Math.round(a[1] + (b[1] - a[1]) * u)},${Math.round(a[2] + (b[2] - a[2]) * u)})`;
  }

  /**
   * Belohnung nach kniffliger Config (z. B. Datenquelle/TLS): viel Staub
   * im QR-Feld (schwarz), keine großen Scheine — wie Ka-Ching-Fläche.
   */
  function starteStaubKonfetti(onDone) {
    const pane = document.getElementById("empfang-pane");
    const leer = document.getElementById("empfang-leer");
    const inhalt = document.getElementById("empfang-inhalt");
    const qr = document.getElementById("empfang-qr");
    if (pane) {
      pane.classList.add(
        "empfang-pane--puls",
        "empfang-pane--konfetti",
        "empfang-pane--staub",
      );
    }
    if (leer) leer.hidden = true;
    if (inhalt) inhalt.hidden = false;
    if (qr) qr.classList.add("empfang-qr--schwarz");

    const nStaub = 480; // 3× vorher
    const fertig = () => {
      if (qr) qr.classList.remove("empfang-qr--schwarz");
      if (pane) pane.classList.remove("empfang-pane--staub");
      if (typeof onDone === "function") onDone();
    };
    return starteKonfetti({
      scheine: Array.from({ length: nStaub }, () => 10),
      staubExtra: 0,
      sats: 10,
      modus: "bunt",
      impuls: 280, // langsamer Start
      impulsStreu: 70,
      grav: 2.2, // 50 %+ langsamer Fall
      luft: 14,
      winkelMin: 15,
      winkelMax: 100,
      dauer: 7200, // 50 % länger
      fullViewport: false,
    }, fertig);
  }

  function starteKonfetti(opts, onDone) {
    const qr = document.getElementById("empfang-qr");
    const wrap = document.querySelector(".empfang-qr-wrap");
    const pane = document.getElementById("empfang-pane");
    const fullVp = Boolean(opts && opts.fullViewport);
    // Konfetti auf dem QR-Quadrat (nicht der ggf. rechteckigen Wrap-Box).
    let host = fullVp
      ? (document.body || document.getElementById("app"))
      : (qr || wrap || pane);
    if (!host) {
      if (typeof onDone === "function") onDone();
      return 3000;
    }
    // Altes Layer weg — sonst hängt ein totes Canvas.
    const alt = document.getElementById("empfang-konfetti");
    if (alt) alt.remove();
    const altVp = document.getElementById("satsage-staub-konfetti");
    if (altVp) altVp.remove();

    const layer = document.createElement("canvas");
    layer.id = fullVp ? "satsage-staub-konfetti" : "empfang-konfetti";
    layer.className = fullVp ? "satsage-staub-konfetti" : "empfang-konfetti";
    host.appendChild(layer);

    let seiteW;
    let seiteH;
    if (fullVp) {
      seiteW = Math.max(280, Math.floor(window.innerWidth || 800));
      seiteH = Math.max(280, Math.floor(window.innerHeight || 600));
      layer.width = seiteW;
      layer.height = seiteH;
    } else {
      // Echte Pixelgröße des QR-Quadrats (nicht 0 durch flex/hidden).
      const rect = host.getBoundingClientRect();
      let seite = Math.floor(Math.min(rect.width || 0, rect.height || 0));
      if (seite < 80) {
        seite = Math.floor(Math.min(
          host.clientWidth || 0,
          host.clientHeight || 0,
          pane?.clientWidth || 0,
          pane?.clientHeight || 0,
        ));
      }
      if (seite < 80) seite = 200;
      seiteW = seite;
      seiteH = seite;
      layer.width = seite;
      layer.height = seite;
      // CSS-Größe = Bitmap — kein verzerrtes Hochskalieren.
      layer.style.width = `${seite}px`;
      layer.style.height = `${seite}px`;
    }

    const cctx = layer.getContext("2d");
    if (!cctx) {
      layer.remove();
      if (typeof onDone === "function") onDone();
      return 3000;
    }

    const p = konfettiParamsAusSats(opts && opts.sats, opts);
    // Explizite Scheine (z. B. nur Staub) — Params nicht nochmal mit Sats füllen.
    if (opts && Array.isArray(opts.scheine) && opts.scheine.length) {
      p.scheine = opts.scheine.slice();
      p.staubExtra = 0;
    }
    const seite = Math.min(seiteW, seiteH);
    const farbenBunt = [
      "#f7931a", "#ff5c5c", "#5cff8a", "#5cb8ff", "#ffd15c", "#d45cff", "#fff4c4",
    ];
    const goldDunkel = _hexRgb("#e6b422");
    const goldHell = _hexRgb("#fff8e7");
    const wMin = Math.min(p.winkelMin, p.winkelMax);
    const wMax = Math.max(p.winkelMin, p.winkelMax);
    const luft = (p.luft != null ? p.luft : 2) / 100;
    const kLuft = 0.00025 + luft * 0.0022;
    const bodenY = seiteH - 3;
    const scheine = (p.scheine && p.scheine.length)
      ? p.scheine.slice()
      : konfettiScheineAusSats(p.sats).concat(
        Array.from({ length: KONFETTI_DEFAULTS.staubExtra }, () => 10),
      );

    // Kanone: unten links (QR) bzw. unten-mitte (Viewport-Staub).
    const parts = scheine.map((denom) => {
      const grad = wMin + Math.random() * Math.max(1, wMax - wMin);
      const rad = (grad * Math.PI) / 180;
      const streu = 1 + (Math.random() * 2 - 1) * p.impulsStreu;
      const speed = seite * p.speed * Math.max(0.35, streu);
      const gravMul = (p.grav != null ? p.grav : 5) / 5;
      const sz = konfettiGroesseFuerSchein(denom);
      const originX = fullVp
        ? seiteW * (0.35 + Math.random() * 0.3)
        : seiteW * (0.04 + Math.random() * 0.08);
      const originY = seiteH * (0.88 + Math.random() * 0.06);
      return {
        denom,
        x: originX,
        y: originY,
        vx: Math.cos(rad) * speed * (fullVp && Math.random() < 0.5 ? -1 : 1),
        vy: -Math.sin(rad) * speed,
        g: (seite * 0.00018 + Math.random() * seite * 0.0001) * gravMul,
        c: p.gold
          ? "#e6b422"
          : farbenBunt[Math.floor(Math.random() * farbenBunt.length)],
        shimmerPhase: Math.random() * Math.PI * 2,
        shimmerHz: 1.2 + Math.random() * 2.4,
        w0: sz.w0,
        h: sz.h,
        rot: Math.random() * Math.PI,
        vr: (Math.random() - 0.5) * 0.05,
        spinPhase: Math.random() * Math.PI * 2,
        spinHz: 2.5 + Math.random() * 3.5,
        dead: false,
        vx0: 0,
      };
    });
    for (const part of parts) {
      part.vx0 = Math.abs(part.vx) || 0.0001;
    }

    const vTerminal = seite * (0.005 + (1 - luft) * 0.01);
    const t0 = performance.now();
    const maxDauer = p.dauer;
    let done = false;
    function beenden() {
      if (done) return;
      done = true;
      try {
        cctx.clearRect(0, 0, seiteW, seiteH);
      } catch (_) {
        /* */
      }
      layer.remove();
      if (typeof onDone === "function") onDone();
    }
    function frame(now) {
      if (done) return;
      const elapsed = now - t0;
      const dt = Math.min(40, now - (frame.t || now));
      const step = dt * 0.045;
      frame.t = now;
      cctx.clearRect(0, 0, seiteW, seiteH);
      let alleTot = true;
      for (const part of parts) {
        if (part.dead) continue;
        alleTot = false;
        const spd = Math.hypot(part.vx, part.vy) || 0.0001;
        part.vx += -kLuft * part.vx * spd * dt;
        part.vy += -kLuft * part.vy * spd * dt + part.g * dt;
        if (part.vy > 0) {
          const sinkDamp = Math.pow(0.92 - luft * 0.08, dt / 16);
          part.vx *= sinkDamp;
          if (part.vy > vTerminal) {
            part.vy += (vTerminal - part.vy) * Math.min(1, 0.15 * dt);
          }
        }
        part.x += part.vx * step;
        part.y += part.vy * step;
        part.rot += part.vr;
        // Boden oder weit draußen → weg
        if (
          part.y >= bodenY
          || part.x < -40
          || part.x > seiteW + 40
          || part.y < -40
        ) {
          part.dead = true;
          continue;
        }
        let fill = part.c;
        if (p.gold) {
          const age = elapsed / 1000;
          const wave = 0.5 + 0.5 * Math.sin(
            age * part.shimmerHz * Math.PI * 2 + part.shimmerPhase,
          );
          fill = _lerpRgb(goldDunkel, goldHell, wave);
        }
        let drawW = part.w0;
        if (Math.abs(part.vx) <= 0.5 * part.vx0) {
          const spin = 0.5 + 0.5 * Math.sin(
            elapsed / 1000 * part.spinHz * Math.PI * 2 + part.spinPhase,
          );
          drawW = 1 + spin * Math.max(0, part.w0 - 1);
        }
        cctx.save();
        cctx.globalAlpha = 1;
        cctx.translate(part.x, part.y);
        cctx.rotate(part.rot);
        cctx.fillStyle = fill;
        cctx.fillRect(-drawW / 2, -part.h / 2, drawW, part.h);
        cctx.restore();
      }
      if (alleTot || elapsed >= maxDauer) {
        beenden();
        return;
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    return maxDauer;
  }

  function tick(ts) {
    if (!startTs) startTs = ts;

    // Sonderatem aus Queue annehmen
    if (!sonder && sonderQueue.length) {
      const next = sonderQueue.shift();
      sonder = {
        ...next,
        t0: ts,
        phase: next.typ === "incoming"
          ? "fadeout"
          : (next.typ === "neuerBlock" ? "titel" : "breath"),
      };
      gewechseltInZyklus = false;
      // TxIN: fester Jubel-Text; nächster normaler Atemzug wieder atemWorte().
      if (sonder.typ === "incoming") {
        setzeAtemWort("Ka-Ching!");
      } else if (sonder.typ === "neuerBlock") {
        setzeAtemKopfStil({ mehrzeilig: true, mono: false });
        setzeAtemWort("NEUER\nBLOCK");
      }
    }

    let sicht = 0;
    let zeichneOpts = {};

    if (sonder && sonder.typ === "incoming") {
      const elapsed = ts - sonder.t0;
      // Konfetti läuft parallel (in flashIncoming gestartet). Atem: kurz dimmen,
      // Ka-Ching halten, dann ausklingen — neuer QR erst wenn Konfetti + Atem fertig.
      if (sonder.phase === "fadeout") {
        sicht = Math.max(0, 1 - elapsed / 280);
        zeichneOpts = { nurSchwarz: true };
        if (elapsed >= 280) {
          sonder.phase = "konfetti";
          sonder.t0 = ts;
          sicht = 0;
        }
      } else if (sonder.phase === "konfetti") {
        sicht = 0;
        zeichneOpts = { nurSchwarz: true };
        // Mind. 1,2 s Ka-Ching + Konfetti, oder bis Schnipsel liegen.
        const minHold = 1200;
        if ((sonder.konfettiFertig || incomingKonfettiFertig) && elapsed >= minHold) {
          sonder.phase = "fadein";
          sonder.t0 = ts;
        } else if (elapsed >= 8000) {
          // Notbremse
          sonder.phase = "fadein";
          sonder.t0 = ts;
          incomingKonfettiFertig = true;
        }
      } else if (sonder.phase === "fadein") {
        sicht = Math.min(1, elapsed / 400);
        zeichneOpts = { nurSchwarz: true };
        if (elapsed >= 400) {
          const halte = sonder.halteDanach;
          sonder = null;
          startTs = ts;
          gewechseltInZyklus = false;
          if (halte || sonderQueue.length) {
            wortAtemRest = wuerfleWortAtemRest();
            setzeAtemWort();
          }
          beendeSonderWennIdle(halte);
          _incomingFertigPruefen();
        }
      }
    } else if (sonder && sonder.typ === "neuerBlock") {
      const tNorm = Math.min(0.999, (ts - sonder.t0) / ATEM_MS);
      sicht = tNorm < 0.5 ? (tNorm / 0.5) : (1 - (tNorm - 0.5) / 0.5);
      {
        const listen = maskenListe();
        zeichneOpts = { art: listen[maskeIx % listen.length] };
      }
      if (tNorm >= 0.97) {
        if (sonder.phase === "titel") {
          sonder.phase = "hoehe";
          sonder.t0 = ts;
          setzeAtemKopfStil({ mehrzeilig: false, mono: true });
          setzeAtemWort(formatBlockHoeheAtem(sonder.hoehe));
        } else {
          const halte = sonder.halteDanach;
          sonder = null;
          startTs = ts;
          gewechseltInZyklus = false;
          setzeAtemKopfStil({});
          if (halte || sonderQueue.length) {
            wortAtemRest = wuerfleWortAtemRest();
            setzeAtemWort();
          }
          beendeSonderWennIdle(halte);
        }
      }
    } else if (sonder && (sonder.typ === "orangeB" || sonder.typ === "ohNo" || sonder.typ === "haken")) {
      const tNorm = Math.min(0.999, (ts - sonder.t0) / ATEM_MS);
      sicht = tNorm < 0.5 ? (tNorm / 0.5) : (1 - (tNorm - 0.5) / 0.5);
      if (sonder.typ === "orangeB") {
        zeichneOpts = {
          art: "btc",
          orange: true,
          bScale: Number.isFinite(Number(sonder.bScale))
            ? Number(sonder.bScale)
            : orangeBScaleFromSats(sonder.sats),
        };
      } else if (sonder.typ === "ohNo") zeichneOpts = { art: "ohNo" };
      else zeichneOpts = { art: "haken" };
      if (tNorm >= 0.97) {
        const halte = sonder.halteDanach;
        sonder = null;
        startTs = ts;
        beendeSonderWennIdle(halte);
      }
    } else {
      const tNorm = ((ts - startTs) % ATEM_MS) / ATEM_MS;
      sicht = tNorm < 0.5 ? (tNorm / 0.5) : (1 - (tNorm - 0.5) / 0.5);
      const listen = maskenListe();
      zeichneOpts = { art: listen[maskeIx % listen.length] };
      if (tNorm >= 0.97 || tNorm <= 0.03) {
        if (!gewechseltInZyklus && tNorm >= 0.97) {
          maskeIx = (maskeIx + 1) % listen.length;
          payloadIx += 1;
          // Funny-Text nur alle 2–4 Atemzüge (Ketten dies→das→… bleiben in Reihenfolge).
          wortAtemRest -= 1;
          if (wortAtemRest <= 0) {
            wortIx = (wortIx + 1) % atemWorte().length;
            wortAtemRest = wuerfleWortAtemRest();
            setzeAtemWort();
          }
          qrBmp = null;
          qrSeite = 0;
          gewechseltInZyklus = true;
        }
      } else {
        gewechseltInZyklus = false;
      }
    }

    // TxIN: „Ka-Ching!“ bleibt lesbar (auch bei schwarzem QR / Konfetti).
    const textSicht = (sonder && sonder.typ === "incoming")
      ? Math.max(sicht, sonder.phase === "konfetti" ? 1 : 0.35)
      : sicht;
    setzeAtemTextSicht(textSicht);
    zeichneGlyphAtem(sicht, zeichneOpts).catch(() => {});
    raf = requestAnimationFrame(tick);
  }

  function start() {
    // Schon am Atmen → nicht neu anstoßen (Poll würde sonst den Takt resetten).
    if (raf) return;
    maskeIx = 0;
    payloadIx = 0;
    wortIx = 0;
    wortAtemRest = wuerfleWortAtemRest();
    maskLuma = {}; // Masken-Assets können sich ändern (z. B. B ohne Kreisrand)
    const pane = $("#empfang-pane");
    const leer = $("#empfang-leer");
    const inhalt = $("#empfang-inhalt");
    if (pane) pane.classList.add("empfang-pane--puls");
    if (leer) leer.hidden = true;
    if (inhalt) inhalt.hidden = false;
    const qr = $("#empfang-qr");
    if (qr) {
      qr.classList.add("empfang-qr--puls");
      qr.title = t("dock.empfangPuls");
    }
    const maske = $("#empfang-qr-maske");
    if (maske) {
      maske.hidden = true;
      maske.replaceChildren();
    }
    setzeAtemWort();
    setzeText($("#empfang-wallet"), t("dock.empfangPuls"));
    setzeText($("#empfang-adresse"), "");
    setzeText($("#empfang-index"), "");
    setzeText($("#empfang-quelle"), "");
    const zurueck = $("#empfang-lern-zurueck");
    if (zurueck) zurueck.hidden = true;
    Promise.all(maskenListe().map((a) => ladeBild(MASK_SRC[a]))).then(() => {
      if (raf) return;
      stelleCanvas();
      startTs = 0;
      raf = requestAnimationFrame(tick);
    });
  }

  function laeuft() {
    return Boolean(raf);
  }

  return {
    start,
    stop,
    laeuft,
    istIncoming,
    istOrangeB,
    flashOrangeB,
    flashOhNo,
    flashIncoming,
    flashHaken,
    flashNeuerBlock,
    flashStaubBelohnung: starteStaubKonfetti,
    orangeBScaleFromSats,
    konfettiParamsAusSats,
    konfettiScheineAusSats,
    starteKonfetti,
  };
})();

/** Einmal Staub-Konfetti nach gelungener Datenquellen-Config (Anfänger-Jubel). */
function jubelDatenquelleErfolg() {
  try {
    if (typeof EmpfangPuls.flashStaubBelohnung === "function") {
      EmpfangPuls.flashStaubBelohnung();
    }
  } catch (_) {
    /* Animation optional */
  }
}

/**
 * Privatsphäre hoch: eigener Indexer und/oder P2P.
 * Öffentliches Electrum (kind public) — nie.
 */
function standHatHochPrivateVerbindung(stand, quellen) {
  if (stand && stand.kind === "public") return false;
  if (stand && stand.gut && (stand.kind === "own" || stand.kind === "mixed" || stand.kind === "p2p")) {
    return true;
  }
  const liste = quellen || [];
  const own = liste.find((q) => q && q.key === "own_fulcrum");
  if (own && own.reachable === true) return true;
  const p2p = liste.find((q) => q && q.key === "bip158");
  return Boolean(p2p && p2p.configured && p2p.reachable === true);
}

function liesKonfettiProtoOpts() {
  const num = (id, fallback) => {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const v = Number(el.value);
    return Number.isFinite(v) ? v : fallback;
  };
  const modus = ($("#konfetti-modus") && $("#konfetti-modus").value) || "auto";
  return {
    sats: num("konfetti-sats", 100000),
    goldAb: num("konfetti-gold-ab", 1_000_000),
    modus,
    impuls: num("konfetti-impuls", 500),
    impulsStreu: num("konfetti-impuls-streu", 80),
    grav: num("konfetti-grav", 5),
    count: num("konfetti-count", 64),
    dauer: num("konfetti-dauer", 3000),
    winkelMin: num("konfetti-winkel-min", 30),
    winkelMax: num("konfetti-winkel-max", 80),
    luft: num("konfetti-luft", 2),
  };
}

function aktualisiereKonfettiProtoStatus() {
  const status = $("#konfetti-proto-status");
  if (!status || typeof EmpfangPuls.konfettiParamsAusSats !== "function") return;
  const opts = liesKonfettiProtoOpts();
  const p = EmpfangPuls.konfettiParamsAusSats(opts.sats, opts);
  const setTxt = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  setTxt("konfetti-impuls-wert", String(Math.round(p.impuls)));
  setTxt("konfetti-impuls-streu-wert", String(Math.round(p.impulsStreu * 100)));
  setTxt("konfetti-grav-wert", String(Math.round(p.grav)));
  setTxt(
    "konfetti-staerke-wert",
    `Vorschlag ${Math.round(5 + p.staerkeAuto * 495)}`,
  );
  setTxt("konfetti-count-wert", String(opts.count));
  setTxt("konfetti-dauer-wert", String(opts.dauer));
  setTxt("konfetti-winkel-min-wert", String(opts.winkelMin));
  setTxt("konfetti-winkel-max-wert", String(opts.winkelMax));
  setTxt("konfetti-luft-wert", String(Math.round(p.luft)));
  const z = p.zählung || {};
  const teile = [];
  if (z[100000]) teile.push(`${z[100000]}×100k`);
  if (z[10000]) teile.push(`${z[10000]}×10k`);
  if (z[1000]) teile.push(`${z[1000]}×1k`);
  if (z[100]) teile.push(`${z[100]}×100`);
  if (z[10]) teile.push(`${z[10]}×Staub`);
  const mix = teile.length ? teile.join(" + ") : "—";
  const farbe = p.gold ? "GOLD" : "BUNT";
  status.textContent = (
    `${farbe} · ${opts.sats.toLocaleString("de-DE")} sats → ${p.count} Schnipsel (${mix}) · `
    + `Impuls ${Math.round(p.impuls)} · Luft ${Math.round(p.luft)} · Grav ${Math.round(p.grav)}`
  );
}

function istRegtestNetz() {
  const n = String(Zustand.config?.network || "").toLowerCase();
  return n === "regtest" || n === "reg";
}

function setzeEmpfangLabSenden() {
  const box = $("#empfang-lab-senden");
  if (!box) return;
  const an = istRegtestNetz();
  box.hidden = !an;
  if (!an || box.dataset.gebunden === "1") return;
  box.dataset.gebunden = "1";
  const knopf = $("#empfang-lab-ok");
  if (!knopf) return;
  knopf.addEventListener("click", () => {
    sendeLabFaucetSats().catch((fehler) => {
      meldung(fehler.message || String(fehler), "krit");
    });
  });
}

async function sendeLabFaucetSats() {
  const feld = $("#empfang-lab-sats");
  const sats = Math.floor(Number(feld && feld.value) || 0);
  if (sats < 546) {
    throw new Error("Mindestens 546 sats.");
  }
  let adresse = Zustand.empfang?.address || Zustand.empfangByWallet?.[Zustand.walletId]?.address;
  if (!adresse && Zustand.walletId) {
    const daten = await ladeEmpfang(Zustand.walletId);
    adresse = daten && daten.address;
  }
  if (!adresse) {
    throw new Error(t("ui.hard.4b52aa422b"));
  }
  const ergebnis = await api("/lab/faucet-senden", {
    methode: "POST",
    daten: { address: adresse, sats },
  });
  meldung(
    `Faucet → Empfang: ${sats.toLocaleString("de-DE")} sats (${String(ergebnis.txid || "").slice(0, 12)}…)`,
    "gut",
  );
  // Incoming-Animation mit Betrag; Mempool-Pending folgt über Watch/Refresh.
  EmpfangPuls.flashIncoming(Zustand.walletId, sats);
  if (Zustand.walletId) {
    setTimeout(() => {
      zeigeWallet(Zustand.walletId).catch(() => {});
    }, 800);
  }
  return ergebnis;
}

/** Debug-Leiste neben Empfangen — nur mit ?animdebug=1 (nicht für Releases). */
function setzeEmpfangAnimDebug() {
  const leiste = $("#empfang-anim-debug");
  const proto = $("#empfang-konfetti-proto");
  if (!leiste) return;
  const an = empfangAnimDebugAn();
  leiste.hidden = !an;
  if (proto) proto.hidden = !an;
  if (an) stoppeEmpfangPoll();
  if (!an || leiste.dataset.gebunden === "1") return;
  leiste.dataset.gebunden = "1";
  if (proto) {
    proto.addEventListener("input", aktualisiereKonfettiProtoStatus);
    proto.addEventListener("change", aktualisiereKonfettiProtoStatus);
    const ausSats = $("#konfetti-impuls-aus-sats");
    if (ausSats) {
      ausSats.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const opts = liesKonfettiProtoOpts();
        const p = EmpfangPuls.konfettiParamsAusSats(opts.sats, { ...opts, impuls: 0 });
        const impulsEl = $("#konfetti-impuls");
        if (impulsEl) impulsEl.value = String(Math.round(5 + p.staerkeAuto * 495));
        aktualisiereKonfettiProtoStatus();
      });
    }
    aktualisiereKonfettiProtoStatus();
  }
  leiste.addEventListener("click", (e) => {
    const btn = e.target && e.target.closest && e.target.closest("button[data-anim]");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const art = btn.getAttribute("data-anim");
    Zustand.lernThema = null;
    try {
      if (art === "puls") {
        EmpfangPuls.stop();
        EmpfangPuls.start();
      } else if (art === "orangeB") {
        const opts = liesKonfettiProtoOpts();
        EmpfangPuls.flashOrangeB(opts.sats);
      } else if (art === "ohNo") {
        EmpfangPuls.flashOhNo();
      } else if (art === "incoming" || art === "konfetti-tune") {
        const opts = liesKonfettiProtoOpts();
        EmpfangPuls.flashIncoming(Zustand.walletId, opts.sats, opts);
      } else if (art === "haken") {
        EmpfangPuls.flashHaken();
      } else if (art === "neuerBlock") {
        const tip = Zustand.config?.header_tip
          || Zustand.config?.wallet_watch?.last_block_height
          || 840000;
        EmpfangPuls.flashNeuerBlock(tip);
      } else if (art === "stop") {
        EmpfangPuls.stop({ force: true });
        if (Zustand.walletId) ladeEmpfang(Zustand.walletId).catch(() => {});
      }
    } catch (fehler) {
      meldung(fehler.message || String(fehler), "krit");
    }
  });
}

function empfangQuelleLabel(source) {
  if (source === "fulcrum") return t("dock.empfangSourceFulcrum");
  if (source === "cache_estimate") return t("dock.empfangSourceCache");
  return source || "";
}

function setzeEmpfangQuelle(source) {
  const el = $("#empfang-quelle");
  if (!el) return;
  el.textContent = empfangQuelleLabel(source);
  el.classList.toggle("empfang-quelle--warn", source === "cache_estimate");
  el.title = source === "cache_estimate" ? t("dock.empfangSourceCache") : "";
}

function lernhinweiseAn() {
  return Boolean(Zustand.config?.lernhinweise_plebs);
}

function lernLang() {
  return uiSprache();
}

async function ladeLernhinweiseKatalog() {
  if (Zustand.lernhinweise) return Zustand.lernhinweise;
  try {
    const antwort = await fetch("/lernhinweise.json", { credentials: "same-origin" });
    if (!antwort.ok) return null;
    Zustand.lernhinweise = await antwort.json();
    return Zustand.lernhinweise;
  } catch (_) {
    return null;
  }
}

function lernThemaEintrag(id) {
  const kat = Zustand.lernhinweise;
  if (!kat || !Array.isArray(kat.themen)) return null;
  return kat.themen.find((t) => t && t.id === id && t.status !== "verworfen") || null;
}

function lernUrlFuerThema(eintrag) {
  if (!eintrag) return null;
  const block = eintrag[lernLang()] || eintrag.de || eintrag.en;
  if (!block || !block.url) return null;
  return {
    url: String(block.url),
    titel: String(block.titel || ""),
    stichwort: String(
      (lernLang() === "en" ? eintrag.stichwort_en : eintrag.stichwort_de)
      || eintrag.id
      || "",
    ),
  };
}

function ergaenzeLernTooltip(el) {
  if (!lernhinweiseAn() || !el || !el.getAttribute) return;
  const id = el.getAttribute("data-lern");
  if (!id) return;
  const ziel = lernUrlFuerThema(lernThemaEintrag(id));
  if (!ziel) return;
  // Basis immer frisch aus i18n-Title, sonst überschreibt Locale den Kaninchenbau.
  const i18nKey = el.getAttribute("data-i18n-title");
  const basis = i18nKey
    ? t(i18nKey)
    : (el.dataset.lernBaseTitle || el.getAttribute("title") || "");
  el.dataset.lernBaseTitle = basis;
  const suffix = t("lernhinweise.tooltipSuffix", { url: ziel.url });
  el.setAttribute("title", basis ? `${basis} — ${suffix}` : suffix);
}

async function wendeAlleLernTooltipsAn() {
  if (!lernhinweiseAn()) return;
  await ladeLernhinweiseKatalog();
  document.querySelectorAll("[data-lern]").forEach((el) => {
    ergaenzeLernTooltip(el);
  });
}

async function setzeLernThema(id) {
  if (!lernhinweiseAn()) return;
  await ladeLernhinweiseKatalog();
  const ziel = lernUrlFuerThema(lernThemaEintrag(id));
  if (!ziel) return;
  Zustand.lernThema = { id, ...ziel };
  zeichneEmpfangLernstoff(Zustand.lernThema);
}

function loescheLernThema() {
  Zustand.lernThema = null;
  const pane = $("#empfang-pane");
  if (pane) pane.classList.remove("empfang-pane--lern");
  const zurueck = $("#empfang-lern-zurueck");
  if (zurueck) zurueck.hidden = true;
  if (Zustand.walletId) {
    ladeEmpfang(Zustand.walletId).catch(() => {});
  } else {
    zeichneEmpfangLeer();
  }
}

function zeichneEmpfangLernstoff(thema) {
  if (!thema || !thema.url) return;
  EmpfangPuls.stop();
  // Flüchtigkeit: Empfangsadresse entwerten, bevor Lern-QR erscheint.
  const leer = $("#empfang-leer");
  const inhalt = $("#empfang-inhalt");
  if (leer) leer.hidden = true;
  if (!inhalt) return;
  inhalt.hidden = false;
  const pane = $("#empfang-pane");
  if (pane) {
    pane.classList.add("empfang-pane--lern");
    pane.classList.remove("empfang-pane--puls");
  }

  const qr = $("#empfang-qr");
  if (qr) {
    const svg = empfangQrSvg(thema.url);
    qr.replaceChildren();
    if (svg) qr.insertAdjacentHTML("afterbegin", svg);
    qr.title = t("dock.empfangLernClick");
    qr.classList.add("kopierbar");
    qr.classList.remove("empfang-qr--puls");
  }
  setzeText(
    $("#empfang-wallet"),
    t("dock.empfangLernstoff", { topic: thema.stichwort || thema.id }),
  );
  const adresse = $("#empfang-adresse");
  if (adresse) {
    adresse.replaceChildren();
    adresse.textContent = thema.url;
    adresse.title = t("dock.empfangLernClick");
    adresse.classList.add("kopierbar");
  }
  setzeText($("#empfang-index"), "");
  setzeText($("#empfang-quelle"), thema.titel || "");
  const zurueck = $("#empfang-lern-zurueck");
  if (zurueck) zurueck.hidden = false;
  Zustand.empfang = {
    wallet_id: Zustand.walletId,
    address: "",
    index: 0,
    lern: true,
    url: thema.url,
  };
}

function oeffneLernUrl(url) {
  const ziel = String(url || "").trim();
  if (!ziel) return;
  const schreiben = navigator.clipboard && navigator.clipboard.writeText
    ? navigator.clipboard.writeText(ziel)
    : Promise.reject();
  schreiben.catch(() => {
    /* Clipboard optional — Tab öffnen trotzdem */
  }).finally(() => {
    try {
      window.open(ziel, "_blank", "noopener,noreferrer");
    } catch (_) { /* ignore */ }
  });
}

/** Wie lange warten, bis der Browser-Tooltip typischerweise da ist (~1 s). */
const LERN_TOOLTIP_WARTE_MS = 1000;
let lernHoverTimer = null;
let lernHoverEl = null;

function brichLernHoverAb() {
  if (lernHoverTimer) {
    clearTimeout(lernHoverTimer);
    lernHoverTimer = null;
  }
  lernHoverEl = null;
}

function setzeLernhinweiseDelegates() {
  if (document.documentElement.dataset.lernDelegates === "1") return;
  document.documentElement.dataset.lernDelegates = "1";
  document.addEventListener("mouseover", (e) => {
    if (!lernhinweiseAn()) return;
    const el = e.target && e.target.closest && e.target.closest("[data-lern]");
    if (!el) return;
    // Schon auf demselben Element (Kind→Eltern): Timer nicht neu starten.
    if (el === lernHoverEl) return;
    brichLernHoverAb();
    lernHoverEl = el;
    const id = el.getAttribute("data-lern");
    // Tooltip-Text sofort vorbereiten; Lern-QR erst nach Wartezeit (wie title).
    const vorbereiten = () => ergaenzeLernTooltip(el);
    if (!Zustand.lernhinweise) {
      ladeLernhinweiseKatalog().then(vorbereiten);
    } else {
      vorbereiten();
    }
    lernHoverTimer = setTimeout(() => {
      lernHoverTimer = null;
      if (!lernhinweiseAn() || lernHoverEl !== el) return;
      if (id && Zustand.lernThema?.id !== id) {
        setzeLernThema(id);
      }
    }, LERN_TOOLTIP_WARTE_MS);
  });
  document.addEventListener("mouseout", (e) => {
    if (!lernhinweiseAn()) return;
    const el = e.target && e.target.closest && e.target.closest("[data-lern]");
    if (!el || el !== lernHoverEl) return;
    const wohin = e.relatedTarget;
    // Innerhalb desselben data-lern-Elements bleiben → Timer weiterlaufen lassen.
    if (wohin && el.contains(wohin)) return;
    brichLernHoverAb();
  });
  document.addEventListener("click", (e) => {
    if (!lernhinweiseAn()) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    // Klick auf Lern-QR / URL darunter → Tab öffnen (nicht als data-lern werten).
    if (Zustand.empfang?.lern && Zustand.empfang.url) {
      const amQr = e.target && e.target.closest
        && e.target.closest("#empfang-qr, #empfang-adresse");
      if (amQr) {
        e.preventDefault();
        e.stopPropagation();
        oeffneLernUrl(Zustand.empfang.url);
        return;
      }
    }
    const el = e.target && e.target.closest && e.target.closest("[data-lern]");
    if (!el) return;
    brichLernHoverAb();
    setzeLernThema(el.getAttribute("data-lern"));
  });
}

function zeichneLernhinweiseEinstellung() {
  const box = $("#lernhinweise-plebs");
  if (!box) return;
  box.checked = Boolean(Zustand.config?.lernhinweise_plebs);
}

async function speichereLernhinweiseEinstellung() {
  const box = $("#lernhinweise-plebs");
  if (!box) return;
  const an = Boolean(box.checked);
  const ergebnis = await api("/config/lernhinweise-plebs", {
    methode: "PUT",
    daten: { lernhinweise_plebs: an },
  });
  if (Zustand.config) {
    Zustand.config.lernhinweise_plebs = Boolean(ergebnis.lernhinweise_plebs);
  }
  if (!an) {
    Zustand.lernThema = null;
    document.querySelectorAll("[data-lern]").forEach((el) => {
      const basis = el.dataset.lernBaseTitle;
      if (basis != null) el.setAttribute("title", basis);
    });
    if (Zustand.walletId) ladeEmpfang(Zustand.walletId).catch(() => {});
  } else {
    await wendeAlleLernTooltipsAn();
  }
  zeichneLernhinweiseEinstellung();
  if (typeof meldung === "function") {
    meldung(
      an ? t("settings.lernhinweise.savedAn") : t("settings.lernhinweise.saved"),
      "gut",
    );
  }
}

function empfangAnimDebugAn() {
  try {
    return new URLSearchParams(location.search).get("animdebug") === "1"
      || localStorage.getItem("empfangAnimDebug") === "1";
  } catch (_) {
    return false;
  }
}

function stoppeEmpfangPoll() {
  if (Zustand.empfangTimer) {
    clearInterval(Zustand.empfangTimer);
    Zustand.empfangTimer = null;
  }
}

function setzeEmpfangPoll() {
  stoppeEmpfangPoll();
  // Bei Animations-Debug keinen Empfangs-Poll — sonst überschreibt er die Demos.
  if (empfangAnimDebugAn()) return;
  Zustand.empfangTimer = setInterval(() => {
    const pane = $("#empfang-pane");
    if (!pane || pane.offsetParent === null) return;
    if (!Zustand.walletId) return;
    ladeEmpfang(Zustand.walletId, { still: true }).catch(() => {});
  }, EMPFANG_POLL_MS);
}

function zeichneEmpfangLeer(text, { puls = false } = {}) {
  // Puls weiterlaufen lassen, wenn wir ohnehin wieder atmen sollen.
  if (!puls) EmpfangPuls.stop();
  const leer = $("#empfang-leer");
  const inhalt = $("#empfang-inhalt");
  if (!puls) {
    const qr = $("#empfang-qr");
    if (qr) {
      qr.replaceChildren();
      qr.removeAttribute("title");
      qr.classList.remove("empfang-qr--puls");
    }
  }
  const adresse = $("#empfang-adresse");
  if (adresse) {
    adresse.replaceChildren();
    adresse.textContent = "";
    adresse.removeAttribute("title");
    adresse.classList.remove("kopierbar", "kopierbar-ok", "kopierbar-fehl");
  }
  if (!puls) {
    setzeText($("#empfang-wallet"), "");
    setzeText($("#empfang-index"), "");
    const quelle = $("#empfang-quelle");
    if (quelle) {
      quelle.textContent = "";
      quelle.classList.remove("empfang-quelle--warn");
      quelle.removeAttribute("title");
    }
  }
  const hinweis = $("#empfang-hinweis");
  if (hinweis) {
    hinweis.hidden = true;
    hinweis.textContent = "";
    hinweis.classList.remove("empfang-hinweis--warn");
  }
  const zurueck = $("#empfang-lern-zurueck");
  if (zurueck) zurueck.hidden = true;
  const pane = $("#empfang-pane");
  if (pane && !puls) {
    pane.classList.remove("empfang-pane--lern", "empfang-pane--puls");
  }
  Zustand.empfang = null;

  if (puls) {
    EmpfangPuls.start();
    return;
  }
  if (leer) {
    leer.hidden = false;
    leer.textContent = text || t("dock.empfangEmpty");
  }
  if (inhalt) inhalt.hidden = true;
}

function zeichneEmpfangReadOnly(walletName, { puls = false } = {}) {
  // Während Tip/Scan: Atem statt statischem „Read-only“ — der Bestand
  // läuft noch, auch wenn kein QR kommt.
  const text = puls
    ? t("dock.empfangSyncing")
    : t("dock.empfangReadOnly");
  zeichneEmpfangLeer(text, { puls });
  const leer = $("#empfang-leer");
  if (leer && !puls && walletName) {
    leer.textContent = t("dock.empfangReadOnly");
  }
}

/**
 * Empfangspanel im „beschäftigt“-Zustand: QR weg, Atem an.
 * Gilt für UTXO-/Verlaufs-Scan und Tip-/Start-Sync — auch Read-only-Wallets.
 */
function zeichneEmpfangBeschaeftigt(walletId) {
  const walletMeta = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  Zustand.lernThema = null;
  if (walletMeta && walletMeta.read_only) {
    zeichneEmpfangReadOnly(walletMeta.name, { puls: true });
  } else {
    zeichneEmpfangLeer(t("dock.empfangPuls"), { puls: true });
  }
  Zustand.empfang = {
    wallet_id: walletId || "",
    address: "",
    index: 0,
    puls: true,
  };
}

function empfangSonderAtemLaeuft() {
  if (typeof EmpfangPuls === "undefined") return false;
  if (EmpfangPuls.istIncoming && EmpfangPuls.istIncoming()) return true;
  if (EmpfangPuls.istOrangeB && EmpfangPuls.istOrangeB()) return true;
  return false;
}

function zeichneEmpfang(daten, { zahlung = false } = {}) {
  // Konfetti/Incoming oder Orange-₿ (UTXO-Fund): QR merken, Animation nicht killen.
  if (empfangSonderAtemLaeuft()) {
    Zustand._empfangNachIncoming = { daten, zahlung: Boolean(zahlung) };
    if (daten && daten.wallet_id) {
      Zustand.empfangByWallet[daten.wallet_id] = daten;
    }
    return;
  }
  EmpfangPuls.stop();
  if (daten && daten.read_only) {
    zeichneEmpfangReadOnly(daten.wallet_name);
    Zustand.empfang = {
      wallet_id: daten.wallet_id,
      address: "",
      index: daten.index,
      read_only: true,
    };
    if (daten.wallet_id) {
      Zustand.empfangByWallet[daten.wallet_id] = daten;
    }
    return;
  }

  const leer = $("#empfang-leer");
  const inhalt = $("#empfang-inhalt");
  if (!inhalt) return;
  if (leer) leer.hidden = true;
  inhalt.hidden = false;
  const pane = $("#empfang-pane");
  if (pane) pane.classList.remove("empfang-pane--lern", "empfang-pane--puls");
  const zurueck = $("#empfang-lern-zurueck");
  if (zurueck) zurueck.hidden = true;

  const qr = $("#empfang-qr");
  if (qr) {
    const svg = empfangQrSvg(daten.address);
    qr.replaceChildren();
    if (svg) {
      qr.insertAdjacentHTML("afterbegin", svg);
    } else {
      qr.textContent = t("dock.empfangQrFehlt");
    }
  }

  setzeText($("#empfang-wallet"), daten.wallet_name || "");
  const adresse = $("#empfang-adresse");
  if (adresse) {
    adresse.replaceChildren();
    const kurz = String(daten.address || "");
    adresse.textContent = kurz;
    macheKopierbar(adresse, kurz, "Adresse");
  }
  setzeText(
    $("#empfang-index"),
    t("dock.empfangIndex", { n: daten.index }),
  );
  setzeEmpfangQuelle(daten.source);

  // Cache-Warnung nur in #empfang-quelle (setzeEmpfangQuelle) — nicht noch
  // einmal in #empfang-hinweis (war doppelte Zeile „Schätzung aus Cache …“).
  const hinweis = $("#empfang-hinweis");
  if (hinweis) {
    if (zahlung) {
      hinweis.hidden = false;
      hinweis.textContent = t("dock.empfangZahlung");
      hinweis.classList.remove("empfang-hinweis--warn");
    } else if (!hinweis.hidden && Zustand.empfang?.address === daten.address) {
      /* Zahlungshinweis bleibt kurz stehen, bis Adresse wechselt */
    } else {
      hinweis.hidden = true;
      hinweis.textContent = "";
      hinweis.classList.remove("empfang-hinweis--warn");
    }
  }
  Zustand.empfang = {
    wallet_id: daten.wallet_id,
    address: daten.address,
    index: daten.index,
    read_only: false,
  };
  if (daten.wallet_id) {
    Zustand.empfangByWallet[daten.wallet_id] = daten;
  }
}

/** Tip-/Start-Aktualisierung betrifft dieses Wallet. */
function tipSyncLaeuftFuer(walletId) {
  if (!walletId) return false;
  return walletSyncLaeuftFuer(walletId);
}

/** Empfang noch unsicher: UTXO-/Verlaufs-Scan oder Tip-/Start-Sync. */
function empfangScanLaeuftFuer(walletId) {
  if (!walletId) return false;
  if (
    Zustand.rescanJob
    && Zustand.scanWalletId === walletId
    && (Zustand.scanArt === "utxo" || Zustand.scanArt === "verlauf")
  ) {
    return true;
  }
  return tipSyncLaeuftFuer(walletId);
}

async function ladeEmpfang(walletId, { still = false } = {}) {
  if (!walletId) {
    zeichneEmpfangLeer();
    return null;
  }

  const walletMeta = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  const scanLaeuft = empfangScanLaeuftFuer(walletId);

  // TxIN/Orange-₿: weder Poll noch zeigeWallet darf QR/Animation ersetzen.
  if (empfangSonderAtemLaeuft()) {
    return Zustand.empfangByWallet[walletId] || Zustand.empfang || null;
  }

  // Animation läuft: Poll nicht mit Adresse erschlagen —
  // * Scan/Sync-Puls: nur überspringen solange Scan wirklich läuft
  // * Ereignis-Atem (Konfetti/…): Zustand.empfang.puls ist nicht gesetzt
  if (still && typeof EmpfangPuls !== "undefined" && EmpfangPuls.laeuft()) {
    if (scanLaeuft) return null;
    if (!(Zustand.empfang && Zustand.empfang.puls)) return null;
  }

  // Scan/Sync hat Vorrang vor Lern-QR und Read-only-Text — Atem bis „gerade eben“.
  if (scanLaeuft) {
    zeichneEmpfangBeschaeftigt(walletId);
    return null;
  }

  // Scan-Puls hing nach Scan-Ende (stale tipSync) → stoppen und Adresse holen.
  // Konfetti/Sonderatem nicht anfassen (kein empfang.puls).
  if (
    typeof EmpfangPuls !== "undefined"
    && EmpfangPuls.laeuft()
    && Zustand.empfang
    && Zustand.empfang.puls
  ) {
    EmpfangPuls.stop();
  }

  // Lern-QR (Hover/Klick) nicht durch Poll/Cache überschreiben — nur ohne Scan.
  if (still && Zustand.lernThema && lernhinweiseAn() && Zustand.empfang?.lern) {
    return null;
  }

  // Flüchtigkeit: bei Kontextwechsel QR/Adresse sofort ungültig — ohne
  // Scan-Herzschlag (der nur bei echtem Scan/Sync startet, s. oben).
  const gleicherWallet = Zustand.empfang && Zustand.empfang.wallet_id === walletId
    && !Zustand.empfang.lern;

  if (walletMeta && walletMeta.read_only) {
    zeichneEmpfangReadOnly(walletMeta.name);
  } else if (!still || !gleicherWallet) {
    zeichneEmpfangLeer(t("dock.empfangLade"), { puls: false });
  }
  // still + gleiches Wallet (Poll): sichtbaren QR stehen lassen, bis neue
  // Antwort da ist — Adresse gehört noch zu diesem Wallet.

  Zustand.empfangLadeGen = (Zustand.empfangLadeGen || 0) + 1;
  const gen = Zustand.empfangLadeGen;
  try {
    const daten = await api(`/wallets/${walletId}/empfang`);
    if (gen !== Zustand.empfangLadeGen || Zustand.walletId !== walletId) {
      return null;
    }
    // Scan kann während dem Request gestartet haben — Cache-QR unterdrücken.
    if (empfangScanLaeuftFuer(walletId)) {
      zeichneEmpfangBeschaeftigt(walletId);
      return null;
    }
    // Index-Sprung = gezeigte Adresse wurde benutzt (oft Mempool).
    // Reihenfolge: Konfetti auf *alter* Adresse → Wallet-Update → neuer QR
    // erst nach Ende der Animation (nicht vorher umspringen).
    const prevEmp = Zustand.empfangByWallet[walletId]
      || (Zustand.empfang?.wallet_id === walletId ? Zustand.empfang : null);
    const prevIdx = prevEmp && Number.isFinite(Number(prevEmp.index))
      ? Number(prevEmp.index)
      : null;
    const neuIdx = Number(daten.index);
    const indexSprung = prevIdx != null && Number.isFinite(neuIdx) && neuIdx > prevIdx;

    if (indexSprung) {
      return starteEmpfangSprungMitKonfetti(walletId, daten, prevEmp);
    }

    Zustand.empfangByWallet[walletId] = daten;
    Zustand.empfang = daten;
    if (spieleQueuedIncomingFlash(walletId)) {
      return daten;
    }
    zeichneEmpfang(daten, { zahlung: false });
    return daten;
  } catch (fehler) {
    if (gen !== Zustand.empfangLadeGen) return null;
    if (empfangScanLaeuftFuer(walletId)) {
      zeichneEmpfangBeschaeftigt(walletId);
      return null;
    }
    if (!still) {
      zeichneEmpfangLeer(fehler.message || t("dock.empfangFehler"));
    }
    return null;
  }
}

function macheDockSpalter() {
  const spalter = $("#dock-spalter");
  const spalten = document.querySelector(".dock-spalten");
  if (!spalter || !spalten) return;

  try {
    const gemerkt = localStorage.getItem(DOCK_SPALTE_MERKER);
    if (gemerkt) spalten.style.setProperty("--dock-log-pct", gemerkt);
  } catch (_) {
    /* ohne Speicher bleibt Vorgabe */
  }

  let startX = 0;
  let startPct = 40;
  let zieht = false;

  const merken = (wert) => {
    try {
      localStorage.setItem(DOCK_SPALTE_MERKER, wert);
    } catch (_) {
      /* gleichgültig */
    }
  };

  const beenden = (ereignis) => {
    if (!zieht) return;
    zieht = false;
    try {
      spalter.releasePointerCapture(ereignis.pointerId);
    } catch (_) {
      /* Capture war schon weg */
    }
    const wert = getComputedStyle(spalten).getPropertyValue("--dock-log-pct").trim();
    if (wert) merken(wert);
  };

  spalter.addEventListener("pointerdown", (ereignis) => {
    if (ereignis.button !== 0) return;
    const buehne = document.querySelector(".buehne");
    if (!buehne || !buehne.classList.contains("log-an")) return;
    zieht = true;
    startX = ereignis.clientX;
    const roh = getComputedStyle(spalten).getPropertyValue("--dock-log-pct").trim();
    startPct = Number.parseFloat(roh) || 40;
    spalter.setPointerCapture(ereignis.pointerId);
    ereignis.preventDefault();
  });
  spalter.addEventListener("pointermove", (ereignis) => {
    if (!zieht) return;
    const breite = spalten.getBoundingClientRect().width;
    if (breite < 40) return;
    const delta = ((ereignis.clientX - startX) / breite) * 100;
    // Platz für Assistent + Empfangs-QR lassen.
    const pct = Math.min(70, Math.max(15, startPct + delta));
    spalten.style.setProperty("--dock-log-pct", `${Math.round(pct)}%`);
  });
  spalter.addEventListener("pointerup", beenden);
  spalter.addEventListener("pointercancel", beenden);
}

/** Empfangs-QR horizontal relativ zum Assistenten (LLM) ziehbar. */
function macheEmpfangSpalter() {
  const spalter = $("#empfang-spalter");
  const spalten = document.querySelector(".dock-spalten");
  if (!spalter || !spalten) return;

  try {
    const gemerkt = localStorage.getItem(EMPFANG_SPALTE_MERKER);
    if (gemerkt) spalten.style.setProperty("--dock-empfang-pct", gemerkt);
  } catch (_) {
    /* ohne Speicher bleibt Vorgabe */
  }

  let startX = 0;
  let startPct = 22;
  let zieht = false;

  const merken = (wert) => {
    try {
      localStorage.setItem(EMPFANG_SPALTE_MERKER, wert);
    } catch (_) {
      /* gleichgültig */
    }
  };

  const beenden = (ereignis) => {
    if (!zieht) return;
    zieht = false;
    try {
      spalter.releasePointerCapture(ereignis.pointerId);
    } catch (_) {
      /* Capture war schon weg */
    }
    const wert = getComputedStyle(spalten)
      .getPropertyValue("--dock-empfang-pct")
      .trim();
    if (wert) merken(wert);
  };

  spalter.addEventListener("pointerdown", (ereignis) => {
    if (ereignis.button !== 0) return;
    zieht = true;
    startX = ereignis.clientX;
    const roh = getComputedStyle(spalten)
      .getPropertyValue("--dock-empfang-pct")
      .trim();
    startPct = Number.parseFloat(roh) || 22;
    spalter.setPointerCapture(ereignis.pointerId);
    ereignis.preventDefault();
  });
  spalter.addEventListener("pointermove", (ereignis) => {
    if (!zieht) return;
    const breite = spalten.getBoundingClientRect().width;
    if (breite < 40) return;
    // Nach rechts ziehen → QR schmaler; nach links → QR breiter (Anteil der Dock-Breite).
    const delta = ((startX - ereignis.clientX) / breite) * 100;
    const pct = Math.min(48, Math.max(12, startPct + delta));
    spalten.style.setProperty("--dock-empfang-pct", `${Math.round(pct)}%`);
  });
  spalter.addEventListener("pointerup", beenden);
  spalter.addEventListener("pointercancel", beenden);
}

function logQuellenVerbindung(quellen) {
  for (const quelle of quellen || []) {
    for (const zeile of quelle.log || []) logZeile(zeile);
  }
}

/**
 * Liest den Verbindungstest zeilenweise. Jede Log-Zeile erscheint sofort —
 * nicht erst, wenn Tor und Node fertig sind.
 */
async function leseSourceCheckStream(antwort) {
  const leser = antwort.body.getReader();
  const decoder = new TextDecoder();
  let puffer = "";
  let sources = null;
  let peers = null;
  let peer_status = null;
  let fehler = "";

  const nimm = (obj) => {
    if (obj.log) logZeile(obj.log);
    if (obj.sources) sources = obj.sources;
    if (obj.peers != null) peers = obj.peers;
    if (obj.peer_status) peer_status = obj.peer_status;
    if (obj.error) fehler = obj.error;
  };

  while (true) {
    const { done, value } = await leser.read();
    if (done) break;
    puffer += decoder.decode(value, { stream: true });
    const zeilen = puffer.split("\n");
    puffer = zeilen.pop();
    for (const zeile of zeilen) {
      if (!zeile.trim()) continue;
      nimm(JSON.parse(zeile));
    }
  }
  if (puffer.trim()) nimm(JSON.parse(puffer));
  if (fehler && !sources) throw new ApiFehler(500, fehler);
  return { sources: sources || [], peers, peer_status };
}

async function apiSourceCheck(optionen = {}) {
  const still = Boolean(optionen.still);
  const url = still
    ? "/api/source/status?check=1&still=1"
    : "/api/source/status?check=1";
  const kopf = { "X-Satsage-Token": Token };
  if (!still) kopf.Accept = "application/x-ndjson";
  const antwort = await fetch(url, { headers: kopf });
  if (!antwort.ok) {
    let koerper = {};
    try {
      koerper = await antwort.json();
    } catch (_) {
      /* leerer Körper ist in Ordnung */
    }
    throw new ApiFehler(antwort.status, koerper.error || `HTTP ${antwort.status}`);
  }
  const typ = antwort.headers.get("Content-Type") || "";
  if (typ.includes("ndjson") && antwort.body) {
    return leseSourceCheckStream(antwort);
  }
  const koerper = await antwort.json();
  if (!still) logQuellenVerbindung(koerper.sources);
  return koerper;
}

// ---------------------------------------------------------------------------
// Zustand
// ---------------------------------------------------------------------------

const Zustand = {
  config: null,
  entwurf: [],        // bearbeitete Wallet-Liste (Einstellungen)
  walletSpeichernLaeuft: false,
  ansicht: "einstellungen",
  walletId: null,
  rescanJob: null,
  rescanTimer: null,
  scanArt: null,
  scanWalletId: null,
  scanWalletName: "",
  /** Server-Scan-Pipeline + andere Nutzer-Jobs (Nav). */
  jobsNav: { jobs: [], scan_pipeline: { current: null, queued: [] } },
  jobsNavFehler: "",
  jobsTimer: null,
  scanLogIndex: 0,
  scanLogStand: { index: 0, knoten: [], texte: [] },
  /** Bisherige UTXO-Zahl aus Job-Zwischenstand (während UTXO-Scan). */
  scanUtxoZahl: null,
  /** Zeitpunkt des letzten Wallet-/Nav-Refresh während Scan (ms). */
  scanRefreshUm: 0,
  scanRefreshLaeuft: false,
  peers: 0,
  peersGeprueft: false,
  peerLabel: "0 Peers verbunden",
  peerStatus: null,
  /** Hosts offener BIP-158-Scan-Peers (Tip-Sync), unabhängig vom Probe-Takt. */
  liveP2pPeers: [],
  peerTakt: null,
  peerTaktMs: null,
  peerCheckLaeuft: false,
  /** Laufender Sanktions-Hop-Check (UI nach Seitenwechsel wieder anbinden). */
  sanktionsCheckJobId: null,
  sanktionsCheckTimer: null,
  oeffentlicheGefragt: false,
  headerJob: null,
  headerTimer: null,
  headerLogStand: { index: 0 },
  walletSyncJob: null,
  walletSyncTimer: null,
  walletSyncLogStand: { index: 0 },
  /** Tip-Sync-Ziele (wallet_ids), sobald bekannt — gegen Cross-Wallet-Puls. */
  walletSyncWalletIds: [],
  /** Stiller Watch-Fallback-Tip: kein Nav-Marker / kein Empfangs-Puls. */
  walletSyncStill: false,
  /** "empfang" = UTXO-Tip fertig, QR-Schärfung läuft noch (Nav schon grün). */
  walletSyncPhase: null,
  /** Chain-Tip-Events vom Wallet-Watch (seq-Baseline gegen Reload-Flash). */
  blockEventSeq: 0,
  blockEventSeqInit: false,
  llmStatus: null,
  llmTimer: null,
  kurs: null,
  kursSerie: null,
  kursSerieLade: null,
  kursTimer: null,
  chatMessages: [],
  chatWartet: false,
  /** Empfangs-QR: letzte Adresse / Poll-Handle / Cache je Wallet. */
  empfang: null,
  empfangByWallet: Object.create(null),
  empfangTimer: null,
  empfangLadeGen: 0,
  /** Mempool-Pending-Zähler je Wallet für Animations-Trigger. */
  pendingByWallet: Object.create(null),
  /** Lernhinweise für Plebs (Experiment). */
  lernhinweise: null,
  lernThema: null,
  slashIndex: 0,
  traceJobs: new Map(),
  traceListe: null,
  /** Sprung aus Wallet: nur dieses UTXO — null = volle Herkunftsliste. */
  traceFokus: null,
  steuer: null,
  onchainHinweisSitzungWeg: false,
};

function entwurfGeaendert() {
  const original = Zustand.config?.wallets || [];
  if (Zustand.entwurf.length !== original.length) return true;
  // Neue Einträge (noch ohne id) zählen immer als Änderung.
  if (Zustand.entwurf.some((w) => w.is_new)) return true;
  const originalById = Object.create(null);
  for (const w of original) {
    if (w.id) originalById[w.id] = w;
  }
  for (const w of Zustand.entwurf) {
    const alt = originalById[w.id];
    if (!alt) return true;
    if (
      (w.name || "") !== (alt.name || "")
      || w.script_type !== alt.script_type
      || Number(w.max_addresses) !== Number(alt.max_addresses)
      || Boolean(w.read_only) !== Boolean(alt.read_only)
    ) {
      return true;
    }
  }
  return false;
}

/** Ob genau diese Zeile vom gespeicherten Stand abweicht. */
function walletZeileGeaendert(wallet) {
  if (!wallet) return false;
  if (wallet.is_new) return true;
  const alt = (Zustand.config?.wallets || []).find((w) => w.id === wallet.id);
  if (!alt) return true;
  return (
    (wallet.name || "") !== (alt.name || "")
    || wallet.script_type !== alt.script_type
    || Number(wallet.max_addresses) !== Number(alt.max_addresses)
    || Boolean(wallet.read_only) !== Boolean(alt.read_only)
  );
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function sourcesFullyManaged() {
  return Zustand.config?.managed_by === "specter";
}
function sourcesManaged() {
  // Compatibility name for callers that only need the fully-managed mode.
  return sourcesFullyManaged();
}
function walletsManaged() {
  return Zustand.config?.managed_by === "specter";
}
function start9BridgeManaged(quelle) {
  const key = typeof quelle === "string" ? quelle : quelle?.key;
  return Zustand.config?.managed_by === "start9"
    && ["own_fulcrum", "own_core"].includes(key);
}


function aktualisiereSpecterUi() {
  const managed = sourcesFullyManaged();
  const hinweis = document.getElementById("specter-managed-hinweis");
  if (hinweis) {
    hinweis.hidden = !managed;
    if (managed && Zustand.config?.managed_hint) hinweis.textContent = Zustand.config.managed_hint;
  }
  const walletsNav = document.querySelector("[data-ansicht=\"wallets\"]");
  if (walletsNav) walletsNav.hidden = walletsManaged();
  const sourcesNav = document.getElementById("nav-datenquellen");
  if (sourcesNav) sourcesNav.hidden = managed;
  const sourcesHint = document.getElementById("sources-managed-hinweis");
  if (sourcesHint) {
    const start9 = Zustand.config?.managed_by === "start9";
    sourcesHint.hidden = !start9;
    if (start9 && Zustand.config?.managed_hint) {
      sourcesHint.textContent = Zustand.config.managed_hint;
    }
  }
  const wallets = document.getElementById("ansicht-wallets");
  const sources = document.getElementById("ansicht-datenquellen");
  if (wallets) wallets.hidden = walletsManaged() || Zustand.ansicht !== "wallets";
  if (sources) sources.hidden = managed || Zustand.ansicht !== "datenquellen";
  const mempool = document.getElementById("specter-mempool-karte");
  if (mempool) mempool.hidden = !managed;
}

function zeichneNav() {
  const behaelter = $("#wallet-nav");
  behaelter.replaceChildren();

  const wallets = Zustand.config?.wallets || [];
  if (wallets.length === 0) {
    // Neunutzer: Klick → Verwaltung · Wallets (nicht nur toter Hinweis).
    const leer = document.createElement("button");
    leer.type = "button";
    leer.className = "nav-eintrag";
    leer.textContent = t("wallet.noHistoryYet");
    leer.title = t("wallet.noWalletsNavTitle");
    leer.addEventListener("click", () => oeffneVerwaltung(
      brauchtDatenquellenZuerst() ? "datenquellen" : "wallets",
    ));
    behaelter.append(leer);
  }

  for (const wallet of wallets) {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "nav-eintrag";
    knopf.dataset.ansicht = "wallet";
    knopf.dataset.walletId = wallet.id;
    if (Zustand.ansicht === "wallet" && Zustand.walletId === wallet.id) {
      knopf.classList.add("aktiv");
    }
    const name = document.createElement("span");
    name.className = "nav-name";
    name.textContent = wallet.name;
    knopf.append(name);
    if (Zustand.rescanJob && Zustand.scanWalletId === wallet.id) {
      const marker = document.createElement("span");
      marker.className = "nav-marker";
      if (Zustand.scanArt === "verlauf") {
        marker.textContent = t("wallet.historyScanShort");
      } else if (Zustand.scanUtxoZahl != null && Zustand.scanUtxoZahl > 0) {
        const n = Zustand.scanUtxoZahl;
        marker.textContent = n === 1 ? "1 UTXO…" : `${n} UTXOs…`;
      } else {
        marker.textContent = t("wallet.utxoScanShort");
      }
      knopf.append(marker);
    } else if (
      (scanPipeline().queued || []).some((s) => s.wallet_id === wallet.id)
    ) {
      const marker = document.createElement("span");
      marker.className = "nav-marker";
      marker.textContent = t("wallet.navWaiting");
      knopf.append(marker);
    } else if (wallet.has_cache || walletSyncLaeuftFuer(wallet.id)) {
      const frisch = cacheFrische(wallet);
      const marker = document.createElement("span");
      marker.className = "nav-marker";
      if (frisch.stufe === "gut") marker.classList.add("nav-marker-gut");
      else if (frisch.stufe === "warn") marker.classList.add("nav-marker-warn");
      marker.textContent = frisch.kurz || cacheHinweis(wallet);
      marker.title = frisch.title || frisch.lang || t("wallet.cachePresentTitle");
      knopf.append(marker);
    }
    knopf.addEventListener("click", () => zeigeWallet(wallet.id));
    behaelter.append(knopf);
  }

  for (const name of [
    "steuerjahr", "trace", "sanktionen",
    "wallets", "einstellungen", "datenquellen",
  ]) {
    const knopf = document.querySelector(`[data-ansicht="${name}"]`);
    if (knopf) knopf.classList.toggle("aktiv", Zustand.ansicht === name);
  }
  aktualisiereDatenquellenNav();
  aktualisiereSpecterUi();
  zeichneJobsNav();
}

const ANSICHTEN = [
  "wallet", "steuerjahr", "trace", "sanktionen",
  "wallets", "einstellungen", "datenquellen",
];

const DATENQUELLEN_NAV_WARNUNG =
  "Eigener Node weder per RPC noch per Electrum konfiguriert, " +
  t("ui.hard.2fd28d331d");

function hatPrivatenNode(quellen) {
  const liste = quellen || Zustand.config?.sources || [];
  return liste.some(
    (q) =>
      (q.key === "own_core" || q.key === "own_fulcrum") && q.configured,
  );
}

function aktualisiereDatenquellenNav() {
  const knopf = $("#nav-datenquellen");
  if (!knopf) return;
  const warnung = !hatPrivatenNode();
  knopf.classList.toggle("nav-warn", warnung);
  knopf.title = warnung ? DATENQUELLEN_NAV_WARNUNG : "";
}

function zeigeAnsicht(name) {
  if ((name === "wallets" && walletsManaged()) || (name === "datenquellen" && sourcesFullyManaged())) name = "einstellungen";
  Zustand.ansicht = name;
  for (const ansicht of ANSICHTEN) {
    const el = $(`#ansicht-${ansicht}`);
    if (el) el.hidden = ansicht !== name;
  }
  zeichneNav();
  aktualisiereKopfFilterFuerAnsicht();
}

function setzeEnvPfad(pfad) {
  const text = pfad || ".env";
  for (const span of document.querySelectorAll(".env-pfad")) {
    span.textContent = text;
  }
}

// ---------------------------------------------------------------------------
// Wallet-Ansicht
// ---------------------------------------------------------------------------

/**
 * Geschätzte Quelle nur für die Scan-/Sync-Leiste (nicht für Cache-GETs).
 * Tip-Nachzug bevorzugt BIP-158, wenn Peers da sind.
 */
function quellKeyFuerLadehinweis(job) {
  if (job?.meta?.source) return job.meta.source;
  const liste = Zustand.config?.sources || [];
  const nach = {};
  for (const q of liste) nach[q.key] = q;
  const erreichbar = (key) => {
    const q = nach[key];
    if (!q || !q.configured) return false;
    return q.reachable === true || (q.peer_count || 0) > 0;
  };
  if (job?.kind === "wallet_sync") {
    if (erreichbar("bip158")) return "bip158";
    if (erreichbar("own_fulcrum")) return "own_fulcrum";
    if (erreichbar("own_core")) return "own_core";
  }
  for (const key of [
    "own_fulcrum", "own_core", "bip158", "public_onion", "clearnet",
  ]) {
    if (erreichbar(key)) return key;
  }
  return autoQuelle(liste)?.key || null;
}

function ladeHinweisVonQuelle(key) {
  switch (key) {
    case "own_fulcrum":
    case "public_onion":
    case "clearnet":
      return t("common.loadingFromElectrum");
    case "own_core":
      return t("common.loadingFromCore");
    case "bip158":
      return t("common.loadingFromP2P");
    default:
      return t("common.loadingFromCache");
  }
}

async function zeigeWallet(walletId, { ohneEmpfang = false } = {}) {
  Zustand.walletId = walletId;
  Zustand.walletLadeGen = (Zustand.walletLadeGen || 0) + 1;
  const ladeGen = Zustand.walletLadeGen;
  zeigeAnsicht("wallet");
  // Während TxIN/Orange-₿ / Empfang-Sprung-Konfetti nicht neu laden.
  if (
    !ohneEmpfang
    && !empfangSonderAtemLaeuft()
    && Zustand._empfangSprungInArbeit !== String(walletId)
  ) {
    ladeEmpfang(walletId).catch(() => {});
  }

  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  setzeText($("#wallet-titel"), wallet ? wallet.name : t("common.wallet"));
  // Erst Cache (schnell), Mempool-Pending danach im Hintergrund.
  setzeText($("#wallet-meta"), t("common.loadingFromCache"));
  $("#adress-liste").hidden = true;
  $("#wallet-leer").hidden = true;

  const limit = $("#limit-wahl").value;
  const sort = $("#sort-wahl")?.value || "betrag";
  const basis =
    `/wallets/${walletId}/utxos?limit=${limit}&sort=${encodeURIComponent(sort)}`;
  try {
    const daten = await api(`${basis}&mempool=0`);
    if (Zustand.walletId !== walletId || Zustand.walletLadeGen !== ladeGen) return;
    zeichneUtxos(daten, wallet);
  } catch (fehler) {
    if (Zustand.walletId !== walletId || Zustand.walletLadeGen !== ladeGen) return;
    zeigeLeer(t("wallet.loadFailed", { msg: fehler.message }), "");
    setzeText($("#wallet-meta"), "");
  }
  aktualisiereScanAnzeige();

  // Pending über eigenen Electrs — blockiert den Erst-Paint nicht.
  api(basis)
    .then((frisch) => {
      if (Zustand.walletId !== walletId || Zustand.walletLadeGen !== ladeGen) return;
      zeichneUtxos(frisch, wallet);
      aktualisiereScanAnzeige();
    })
    .catch(() => {});
}

function zeigeLeer(titel, text) {
  const kasten = $("#wallet-leer");
  kasten.replaceChildren();
  const stark = document.createElement("strong");
  stark.textContent = titel;
  kasten.append(stark);
  if (text) kasten.append(document.createTextNode(text));
  kasten.hidden = false;
  $("#adress-liste").hidden = true;
  $("#sanktions-karte").hidden = true;
}

function zeichneUtxos(daten, wallet) {
  // Für Kopf-Filter: Ausgegeben-Block lazy nachzeichnen.
  Zustand._walletUtxoDaten = daten || null;
  const hatVerlauf = Boolean(daten.hat_verlauf);
  const hatUtxos = Boolean(daten.has_cache && daten.total_count);

  if (!daten.has_cache && !hatVerlauf) {
    zeigeLeer(
      t("wallet.emptyNoCache"),
      t("wallet.emptyNoCacheHint"),
    );
    setzeText($("#wallet-meta"), t("wallet.metaNeverScanned"));
    aktualisiereKopfFilterFuerAnsicht();
    return;
  }
  if (daten.has_cache && !hatUtxos && !hatVerlauf) {
    zeigeLeer(
      t("wallet.emptyNoUtxo"),
      t("wallet.emptyNoUtxoHint"),
    );
    setzeText($("#wallet-meta"), t("wallet.metaZeroCache"));
    aktualisiereKopfFilterFuerAnsicht();
    return;
  }

  const teile = [];
  if (daten.has_cache) {
    const utxoListe = daten.utxos || [];
    teile.push(
      `${daten.total_count} UTXO`,
      formatSatsGemeinsam(daten.total_sats, utxoListe),
    );
    if (daten.shown_count < daten.total_count) {
      teile.push(
        `angezeigt: ${daten.shown_count} · ${formatSatsGemeinsam(daten.shown_sats, utxoListe)}`,
      );
    }
    const pendOut = Number(daten.pending_spending_count || 0);
    const pendIn = Number(daten.pending_receive_count || 0);
    if (wallet && wallet.id) {
      const internOut = (daten.utxos || []).some(
        (u) => u && u.spending_pending && u.spending_internal,
      );
      meldePendingAenderung(wallet.id, pendIn, pendOut, { internOut });
    }
    if (pendOut > 0 || pendIn > 0) {
      const bits = [];
      if (pendOut > 0) bits.push(t("wallet.metaPendingOut", { n: pendOut }));
      if (pendIn > 0) bits.push(t("wallet.metaPendingIn", { n: pendIn }));
      teile.push(bits.join(", "));
    }
  } else {
    teile.push(t("ui.hard.d22bed085a"));
  }
  if (hatVerlauf && daten.verlauf) {
    const pendingN = Number(daten.verlauf.pending_count || daten.pending_spends || 0);
    teile.push(
      daten.verlauf.total_count
        ? `${daten.verlauf.total_count} ausgegeben`
          + (pendingN > 0 ? ` · ${t("wallet.spentPendingCount", { n: pendingN })}` : "")
        : t("wallet.metaHistoryNoSpends"),
    );
  }
  if (wallet) {
    teile.push(t("wallet.metaScript", {
      label: scriptTypLabel(wallet.script_type, wallet.script_type_label),
    }));
  }
  const alter = walletAlter(wallet);
  if (alter) teile.push(alter);
  if (wallet && wallet.has_cache) {
    const frisch = cacheFrische(wallet);
    if (frisch.lang) teile.push(frisch.lang);
  }
  setzeText($("#wallet-meta"), teile.join(" · "));
  const metaEl = $("#wallet-meta");
  if (metaEl && wallet) {
    const frisch = cacheFrische(wallet);
    metaEl.title = frisch.title || "";
    metaEl.dataset.fresh = frisch.stufe || "";
  }

  zeichneSanktionsBefund(daten.sanctions);

  const gruppen = daten.addresses || [];
  setzeText(
    $("#adress-zusatz"),
    hatUtxos
      ? t("wallet.addressCountWithBalance", {
          count: gruppen.length,
          sort: ($("#sort-wahl")?.value === "datum")
            ? t("wallet.sortNewestFirst")
            : t("wallet.sortLargestFirst"),
        })
      : t("wallet.addressCountNoBalance"),
  );

  const koerper = $("#adress-koerper");
  koerper.replaceChildren();
  if (hatUtxos) {
    for (const gruppe of gruppen) {
      koerper.append(zeichneAdressGruppe(gruppe));
    }
  } else {
    koerper.append(hinweisZeile(
      daten.has_cache
        ? t("wallet.noSpendsHint")
        : t("wallet.noScanSpentBelow"),
    ));
  }

  const ausgegeben = $("#wallet-ausgegeben");
  ausgegeben.replaceChildren();
  if (hatVerlauf) {
    ausgegeben.append(zeichneAusgegeben(daten));
  }

  $("#wallet-leer").hidden = true;
  $("#adress-liste").hidden = false;
  aktualisiereKopfFilterFuerAnsicht();
  wendeKopfFilterAn();
}

/**
 * Zeigt den Abgleich gegen die Sanktionslisten.
 *
 * Drei Zustände, die sich deutlich unterscheiden müssen: nicht geprüft
 * (keine Listen im Cache), geprüft ohne Treffer, geprüft mit Treffer.
 * „Nichts gefunden“ und „nicht nachgesehen“ dürfen sich nie gleich anfühlen.
 */
function platziereSanktionsKarte(oben) {
  const karte = $("#sanktions-karte");
  const liste = $("#adress-liste");
  if (!karte || !liste) return;
  if (oben) {
    liste.before(karte);
  } else {
    liste.after(karte);
  }
}

function zeichneSanktionsBefund(befund) {
  const karte = $("#sanktions-karte");
  if (!befund) {
    karte.hidden = true;
    return;
  }
  karte.hidden = false;
  platziereSanktionsKarte(Boolean(befund.treffer && befund.treffer.length));

  const kasten = $("#sanktions-befund");
  kasten.replaceChildren();

  const zeile = document.createElement("div");
  zeile.className = "sanktions-zeile";

  if (!befund.geprueft) {
    zeile.append(pille("warn", t("sanctions.notChecked")));
    const text = document.createElement("span");
    text.textContent = befund.grund;
    zeile.append(text);
    setzeText($("#sanktions-zusatz"), "");
  } else if (befund.treffer.length === 0) {
    zeile.append(pille("gut", t("sanctions.noHit")));
    const text = document.createElement("span");
    text.textContent = t("wallet.sanctionsChecked", { count: befund.geprueft_count });
    zeile.append(text);
    setzeText($("#sanktions-zusatz"), "");
  } else {
    zeile.append(pille("krit", t("sanctions.hits", { count: befund.treffer.length })));
    const text = document.createElement("span");
    text.textContent =
      `${formatSats(befund.flagged_sats)} auf gelisteten Adressen.`;
    zeile.append(text);
    setzeText($("#sanktions-zusatz"), t("common.pleaseCheck"));
  }

  const vorbehalt = document.createElement("span");
  vorbehalt.className = "vorbehalt";
  vorbehalt.textContent = t("sanctions.selfCheckHint");
  zeile.append(vorbehalt);
  kasten.append(zeile);

  if (befund.treffer.length > 0) {
    const liste = document.createElement("div");
    liste.className = "treffer-liste";
    for (const treffer of befund.treffer) {
      const eintrag = document.createElement("div");
      eintrag.className = "treffer";

      const adresse = document.createElement("span");
      adresse.className = "mono";
      adresse.textContent = kuerze(treffer.address, 16, 8);
      macheKopierbar(adresse, treffer.address, "Adresse");
      eintrag.append(adresse);

      if (treffer.person) {
        const person = document.createElement("span");
        person.textContent = treffer.person;
        eintrag.append(person);
      }
      const grund = document.createElement("span");
      grund.className = "treffer-grund";
      grund.textContent = [
        treffer.grund,
        (treffer.quellen || []).join(", "),
        treffer.gelistet_am ? `gelistet ${treffer.gelistet_am}` : "",
      ].filter(Boolean).join(" · ");
      eintrag.append(grund);

      liste.append(eintrag);
    }
    kasten.append(liste);
  }
}

/** Haltedauer als Balken: gefüllt = Frist erreicht. */
function haltedauerAnzeige(tage, fristTage = 365) {
  const huelle = document.createElement("span");
  huelle.className = "haltedauer";

  if (tage === null || tage === undefined) {
    const text = document.createElement("span");
    text.className = "halte-text";
    text.textContent = "—";  // neutral dash, no translation needed
    huelle.append(text);
    return huelle;
  }

  const anteil = Math.max(0, Math.min(1, tage / fristTage));
  const voll = tage >= fristTage;

  const balken = document.createElement("span");
  balken.className = voll ? "halte-balken voll" : "halte-balken";
  const fuellung = document.createElement("span");
  fuellung.style.width = `${anteil * 100}%`;
  balken.append(fuellung);

  const text = document.createElement("span");
  text.className = voll ? "halte-text voll" : "halte-text";
  text.textContent = formatHaltedauer(tage);

  huelle.append(balken, text);
  huelle.title = voll
    ? t("scan.hard.2e18213140", { tage })
    : `${tage} von ${fristTage} Tagen bis zur Jahresfrist`;
  return huelle;
}

/** Pfeil und aria-expanded an den Inhalt koppeln. */
function setzeKlapp(kopf, klapp, inhalt, auf) {
  inhalt.hidden = !auf;
  if (klapp) klapp.textContent = auf ? "▾" : "▸";
  if (kopf) kopf.setAttribute("aria-expanded", String(auf));
}

function zeichneAdressGruppe(gruppe) {
  const block = document.createElement("div");
  block.className = "adress-gruppe";
  block.dataset.address = gruppe.address || "";
  const gLabels = kopfFilterLabelText(gruppe);
  if (gLabels) block.dataset.filterLabels = gLabels;

  const kopf = document.createElement("button");
  kopf.type = "button";
  kopf.className = "adress-kopf";

  const klapp = document.createElement("span");
  klapp.className = "klapp";
  klapp.setAttribute("aria-hidden", "true");

  const adresse = document.createElement("span");
  adresse.className = "mono";
  adresse.textContent = kuerze(gruppe.address, 16, 8);
  macheKopierbar(adresse, gruppe.address, "Adresse");

  const anzahl = document.createElement("span");
  anzahl.className = "adress-zahl";
  anzahl.textContent =
    gruppe.utxo_count === 1 ? "1 UTXO" : `${gruppe.utxo_count} UTXOs`;

  const betrag = document.createElement("span");
  betrag.className = "betrag adress-betrag";
  setzeSatsBetrag(betrag, gruppe.total_sats, {
    gemeinsam: gruppe.utxos || [],
  });

  kopf.append(klapp, adresse, anzahl);
  if (gruppe.utxos.some((u) => u.flagged)) {
    kopf.append(pille("krit", t("trace.listed")));
  }
  haengeGruppenJuengsteAn(kopf, gruppe);
  kopf.append(betrag);

  const inhalt = document.createElement("div");
  inhalt.className = "adress-utxos";
  for (const utxo of gruppe.utxos) {
    inhalt.append(zeichneUtxoZeile(utxo));
  }
  // Oberste Ebene bleibt zu — die Liste selbst ist Cache, aber die
  // Adressen sind die Übersicht, nicht der Inhalt.
  setzeKlapp(kopf, klapp, inhalt, false);

  kopf.addEventListener("click", () => {
    setzeKlapp(kopf, klapp, inhalt, inhalt.hidden);
  });

  // Der Verweis sitzt neben dem Knopf, nicht darin: Ein Link in einem Button
  // wäre ungültiges HTML und für Bildschirmleser eine Zumutung.
  const kopfzeile = document.createElement("div");
  kopfzeile.className = "kopf-mit-verweis";
  kopfzeile.append(kopf);
  const extern = mempoolVerweis("address", gruppe.address);
  if (extern) kopfzeile.append(extern);

  block.dataset.address = gruppe.address || "";
  block.append(kopfzeile, inhalt);
  return block;
}

/** Unix-Sekunden für Kopf-Filter (Ausgabe bevorzugt, sonst Ankunft). */
function utxoEreignisTs(utxo) {
  if (!utxo) return 0;
  if (utxo.spent || utxo.spent_pending) {
    const st = Number(
      utxo.spent_time_ts
      || utxo.spent_block_time
      || (utxo.status && utxo.status.spent_time_ts)
      || 0,
    );
    if (st > 0) return st;
  }
  const bt = Number(utxo.block_time || 0);
  if (bt > 0) return bt;
  if (utxo.time_label) {
    const m = String(utxo.time_label).match(
      /(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/,
    );
    if (m) {
      let y = Number(m[3]);
      if (m[3].length <= 2) y += 2000;
      const d = new Date(
        y, Number(m[2]) - 1, Number(m[1]),
        Number(m[4] || 0), Number(m[5] || 0), Number(m[6] || 0),
      );
      if (!Number.isNaN(d.getTime())) return Math.floor(d.getTime() / 1000);
    }
  }
  const js = Number(utxo.juengste_sats_ts || 0);
  return js > 0 ? js : 0;
}

/** Suchtext für Kopf-Filter: Mix-Formen + Börsennamen (Kraken, Wasabi, …). */
function kopfFilterLabelText(utxoOderGruppe) {
  if (!utxoOderGruppe || typeof utxoOderGruppe !== "object") return "";
  const teile = [];
  const mix = utxoOderGruppe.mix_arten
    || (utxoOderGruppe.utxos ? mixArtenDerGruppe(utxoOderGruppe) : []);
  for (const k of mix || []) {
    if (!k) continue;
    teile.push(String(k));
    teile.push(MIX_ICON_KURZ[k] || "");
    const soft = softTxClassLabel({ tx_class: k });
    if (soft) teile.push(soft);
  }
  const txc = utxoOderGruppe.tx_class;
  if (txc) {
    teile.push(String(txc));
    teile.push(MIX_ICON_KURZ[txc] || "");
    const soft = softTxClassLabel({ tx_class: txc });
    if (soft) teile.push(soft);
  }
  let boerse = utxoOderGruppe.boerse_namen;
  if (!boerse && utxoOderGruppe.utxos) {
    boerse = boerseNamenDerGruppe(utxoOderGruppe).namen;
  }
  for (const n of boerse || []) {
    if (n) teile.push(String(n));
  }
  // Einzel-Label-Objekte (falls am Root)
  const ein = boerseNameAusKnoten(utxoOderGruppe);
  if (ein) teile.push(ein);
  return teile.filter(Boolean).join(" ");
}

function setzeUtxoTraceDaten(el, utxo) {
  if (!el || !utxo) return;
  if (utxo.key) el.dataset.key = utxo.key;
  el.dataset.verfolgtVollstaendig = utxoHatVollenHerkunftstrace(utxo) ? "1" : "0";
  el.dataset.verfolgt = utxo.verfolgt ? "1" : "0";
  if (utxo.value_sats != null && utxo.value_sats !== "") {
    el.dataset.valueSats = String(utxo.value_sats);
  }
  if (utxo.address) el.dataset.address = String(utxo.address);
  if (utxo.hold_days != null && utxo.hold_days !== "") {
    el.dataset.holdDays = String(utxo.hold_days);
  }
  if (utxo.block_height != null && utxo.block_height !== "") {
    el.dataset.blockHeight = String(utxo.block_height);
  }
  if (utxo.time_label) el.dataset.timeLabel = String(utxo.time_label);
  if (utxo.juengste_sats_ts) {
    el.dataset.juengsteSatsTs = String(utxo.juengste_sats_ts);
  } else {
    delete el.dataset.juengsteSatsTs;
  }
  const ets = utxoEreignisTs(utxo);
  if (ets > 0) el.dataset.eventTs = String(ets);
  else delete el.dataset.eventTs;
  const labels = kopfFilterLabelText(utxo);
  if (labels) el.dataset.filterLabels = labels;
  else delete el.dataset.filterLabels;
}

function zeichneUtxoZeile(utxo) {
  const zeile = document.createElement("div");
  zeile.className = "utxo-zeile";
  if (utxo.spending_pending) zeile.classList.add("spending-pending-zeile");
  if (utxo.receive_pending) zeile.classList.add("receive-pending-zeile");
  setzeUtxoTraceDaten(zeile, utxo);

  const betrag = document.createElement("span");
  betrag.className = "betrag";
  {
    const atTs = tsAusBewertungsObjekt(utxo);
    if (atTs) setzeSatsBetrag(betrag, utxo.value_sats, { atTs });
    else betrag.textContent = formatSats(utxo.value_sats);
  }

  const kennung = document.createElement("span");
  kennung.className = "mono zart";
  kennung.textContent = kuerze(utxo.key, 12, 8);
  macheKopierbar(kennung, utxo.key, t("common.copyArtUtxo"));

  const zeit = document.createElement("span");
  zeit.className = "zart zahl";
  const ankunft = document.createElement("button");
  ankunft.type = "button";
  ankunft.className = "ankunft-link";
  ankunft.textContent = formatAnkunft(utxo);
  ankunft.title = utxo.receive_pending
    ? t("trace.receivePendingTitle")
    : t("trace.arrivalTitle");
  ankunft.addEventListener("click", () => zeigeHerkunftFuer(utxo.key));
  zeit.append(ankunft);
  if (utxo.block_height) {
    const hoehe = document.createElement("span");
    hoehe.textContent = ` · Block ${utxo.block_height.toLocaleString(formatLocale())}`;
    zeit.append(hoehe);
  }

  zeile.append(betrag, kennung, zeit, haltedauerAnzeige(utxo.hold_days));

  if (utxo.flagged) {
    zeile.append(pille("krit", "gelistet"));
  }

  // Mempool: Ausgabe unterwegs (eigener Electrs).
  if (utxo.spending_pending && !utxo.spent && !utxo.spent_pending) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke spending-pending";
    marke.textContent = t("trace.spendingPending");
    marke.title = t("trace.spendingPendingTitle");
    if (utxo.spent_txid) {
      macheKopierbar(marke, utxo.spent_txid, "Ausgaben-TxID");
    }
    zeile.append(marke);
  }

  // Mempool: eigener Empfang noch unbestätigt.
  if (utxo.receive_pending && !utxo.spending_pending) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke receive-pending";
    marke.textContent = t("trace.receivePending");
    marke.title = t("trace.receivePendingTitle");
    zeile.append(marke);
  }

  // Herkunft unvollständig (rot) — Abbruch, Lücken, fehlende Prevouts.
  if (utxo.verfolgt && utxoHerkunftUnvollstaendig(utxo)) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke unvollstaendig";
    const wann = utxo.verfolgt_ts
      ? formatKurzdatum(utxo.verfolgt_ts * 1000)
      : "";
    marke.textContent = wann
      ? t("trace.incompleteWhen", { wann })
      : t("trace.incomplete");
    marke.title = t("trace.incompleteTitle");
    zeile.append(marke);
  }

  const juengste = juengsteSatsMarke(utxo);
  if (juengste) zeile.append(juengste);

  // Woher der letzte externe Zufluss kam, sofern die Herkunft schon
  // ermittelt und die Adresse zuzuordnen ist.
  // Ingress = Zufluss von außen (Börse→Wallet → grün).
  const herkunft = labelMarke(utxo.herkunft_label, { herkunft: true, zufluss: true });
  if (herkunft) zeile.append(herkunft);

  const neu = document.createElement("button");
  neu.type = "button";
  neu.className = "trace-link";
  neu.textContent = t("trace.rescan");
  neu.title = t("trace.rescanTitle");
  neu.addEventListener("click", (e) => {
    e.stopPropagation();
    zeigeHerkunftFuer(utxo.key, { neu: true });
  });
  zeile.append(neu);

  const extern = mempoolVerweis("tx", utxo.txid);
  if (extern) zeile.append(extern);

  return zeile;
}

// ---------------------------------------------------------------------------
// Wallet-Scans (UTXO-Bestand und Verlauf)
// ---------------------------------------------------------------------------

function scanArtName(art = Zustand.scanArt) {
  return art === "verlauf" ? t("wallet.historyScan") : t("wallet.utxoScan");
}

function scanWalletName() {
  const id = Zustand.scanWalletId;
  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === id);
  return wallet?.name || Zustand.scanWalletName || t("wallet.otherWallet");
}

function walletNameZu(id) {
  return (Zustand.config?.wallets || []).find((w) => w.id === id)?.name || "";
}

function scanBetrifftDieseAnsicht() {
  return Zustand.ansicht === "wallet" && Zustand.walletId === Zustand.scanWalletId;
}

function scanPipeline() {
  return Zustand.jobsNav?.scan_pipeline || { current: null, queued: [] };
}

function scanArtVonKind(kind) {
  return kind === "verlauf" ? "verlauf" : "utxo";
}

function schonGeplant(ziel) {
  if (!ziel || !ziel.id) return false;
  const artKind = ziel.art === "verlauf" ? "verlauf" : "rescan";
  const pipe = scanPipeline();
  const cur = pipe.current;
  if (
    cur
    && cur.wallet_id === ziel.id
    && (cur.kind === artKind || scanArtVonKind(cur.kind) === ziel.art)
  ) {
    // Pipeline-Eintrag nur zählen, wenn der Job noch aktiv ist.
    if (!cur.job_id || jobNochAktiv(cur.job_id)) return true;
  }
  if (
    Zustand.rescanJob
    && Zustand.scanWalletId === ziel.id
    && Zustand.scanArt === ziel.art
    && jobNochAktiv(Zustand.rescanJob)
  ) {
    return true;
  }
  return (pipe.queued || []).some(
    (q) => q.wallet_id === ziel.id && q.kind === artKind,
  );
}

function schlangeText() {
  const q = scanPipeline().queued || [];
  if (!q.length) return "";
  const liste = q.map((s) => {
    const art = s.kind === "verlauf" ? "Verlauf" : "UTXO";
    const name = s.wallet_name || s.label || s.wallet_id;
    return `„${name}“ (${art})`;
  }).join(", ");
  return ` Dann: ${liste}`;
}

function herkunftTiefLaeuftFuer(walletId) {
  if (!walletId) return false;
  const jobs = Zustand.jobsNav?.jobs || [];
  return jobs.some((job) => (
    job.running
    && job.kind === "trace-tief"
    && job.meta?.wallet_id === walletId
  ));
}

function setzeTipSyncSichtbarkeit(enabled = undefined) {
  const tipSync = $("#tip-sync-knopf");
  if (!tipSync) return;
  const autoAktuell = enabled === undefined
    ? Boolean(
      Zustand.config?.wallets_immer_aktuell
      ?? Zustand.config?.wallets_beim_start_aktualisieren,
    )
    : Boolean(enabled);
  tipSync.hidden = autoAktuell;
}

function setzeWalletScanGesperrt() {
  const rescan = $("#rescan-knopf");
  const verlauf = $("#verlauf-knopf");
  const tipSync = $("#tip-sync-knopf");
  const tief = $("#herkunft-tief-knopf");
  const wid = Zustand.walletId;
  // UTXO/Verlauf nur sperren, wenn wirklich dieses Portfolio scannt/wartet —
  // nicht wegen fremdem Wallet, stale rescanJob oder globalem Tip-Nachzug.
  const utxoGeplant = Boolean(wid && schonGeplant({ id: wid, art: "utxo" }));
  const verlaufGeplant = Boolean(wid && schonGeplant({ id: wid, art: "verlauf" }));
  const tipLaeuft = Boolean(wid && walletSyncLaeuftFuer(wid));
  const tiefLaeuft = Boolean(wid && herkunftTiefLaeuftFuer(wid));
  if (rescan) {
    if (!rescan.dataset.titel) rescan.dataset.titel = rescan.title || "";
    rescan.disabled = utxoGeplant;
    rescan.title = rescan.disabled
      ? t("nav.jobAlreadyRunning")
      : rescan.dataset.titel;
  }
  if (verlauf) {
    if (!verlauf.dataset.titel) verlauf.dataset.titel = verlauf.title || "";
    verlauf.disabled = verlaufGeplant;
    verlauf.title = verlauf.disabled
      ? t("nav.jobAlreadyRunning")
      : verlauf.dataset.titel;
  }
  if (tipSync) {
    setzeTipSyncSichtbarkeit();
    if (!tipSync.dataset.titel) tipSync.dataset.titel = tipSync.title || "";
    const hatCache = (Zustand.config?.wallets || []).some(
      (w) => w.id === wid && w.has_cache,
    );
    tipSync.disabled = Boolean(tipLaeuft || !hatCache || !wid);
    tipSync.title = tipLaeuft
      ? t("nav.jobAlreadyRunning")
      : (!hatCache ? t("wallet.tipSyncNeedCache") : tipSync.dataset.titel);
  }
  if (tief) {
    if (!tief.dataset.titel) tief.dataset.titel = tief.title || "";
    const hatCache = (Zustand.config?.wallets || []).some(
      (w) => w.id === wid && w.has_cache,
    );
    tief.disabled = Boolean(tiefLaeuft || !hatCache || !wid);
    tief.title = tiefLaeuft
      ? t("nav.jobAlreadyRunning")
      : (!hatCache ? t("wallet.originDeepNeedCache") : tief.dataset.titel);
  }
}

function aktualisiereScanAnzeige(stand) {
  const leiste = $("#rescan-lauf");
  if (!leiste) return;
  const pipe = scanPipeline();
  const hatScan = Boolean(Zustand.rescanJob || pipe.current || (pipe.queued || []).length);
  if (!hatScan) {
    leiste.hidden = true;
    leiste.classList.remove("hinweis-fremd");
    setzeWalletScanGesperrt();
    return;
  }
  leiste.hidden = false;
  const art = scanArtName();
  const name = scanWalletName();
  const quelleHinweis = ladeHinweisVonQuelle(
    quellKeyFuerLadehinweis(Zustand.rescanJob || {
      kind: pipe.current?.kind,
      meta: pipe.current?.meta || { source: pipe.current?.source },
    }),
  );
  const schritt = stand || quelleHinweis;
  const danach = schlangeText();
  if (!Zustand.rescanJob && !pipe.current) {
    leiste.classList.remove("hinweis-fremd");
    setzeText($("#rescan-text"), (danach || "").trim() || t("common.runningEllipsis"));
  } else if (scanBetrifftDieseAnsicht()) {
    leiste.classList.remove("hinweis-fremd");
    setzeText($("#rescan-text"), `„${name}“ · ${art} · ${schritt}${danach}`);
  } else {
    leiste.classList.add("hinweis-fremd");
    setzeText(
      $("#rescan-text"),
      name
        ? t("ui.hard.a7e393ac49", { name, art, schritt, danach })
        : `${art} · ${schritt}${danach}`,
    );
  }
  setzeWalletScanGesperrt();
}

function nimmJobLog(job) {
  if (!Zustand.scanLogStand) {
    Zustand.scanLogStand = { index: 0, knoten: [], texte: [] };
  }
  // scanLogIndex bleibt Spiegel von stand.index (ältere Aufrufer/Reset).
  Zustand.scanLogStand.index = Zustand.scanLogIndex || 0;
  nimmLogZeilen(job, Zustand.scanLogStand, scanWalletName());
  Zustand.scanLogIndex = Zustand.scanLogStand.index;
}

/** Job-Log in den Log-Bereich, mit eigenem Zähler — nicht den des Wallet-Scans. */
function nimmJobLogAb(job, stand, wallet) {
  nimmLogZeilen(job, stand, wallet);
}

function stelleScanAn(art) {
  if (!Zustand.walletId) return;
  const ziel = {
    id: Zustand.walletId,
    name: walletNameZu(Zustand.walletId),
    art,
  };
  if (schonGeplant(ziel)) {
    logZeile(
      `${scanArtName(art)} für „${ziel.name}“ läuft schon oder wartet.`,
      undefined,
      ziel.name,
    );
    setzeWalletScanGesperrt();
    return;
  }
  starteScanFuer(ziel);
}

/**
 * BIP-158-Startdatum fragen, wenn das Wallet kein First-seen hat und der
 * UTXO-Scan über Compact Filter laufen wird (oder dorthin fällt).
 *
 * Früher: nur wenn autoQuelle() === bip158. autoQuelle nimmt aber die erste
 * *konfigurierte* Quelle (z. B. eigenen Electrum-Host), auch wenn der nicht
 * erreichbar ist und der Scan real über P2P geht — dann fehlte der Dialog.
 */
function brauchtBip158Startdatum(walletId) {
  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  if (!wallet || wallet.first_seen_height) return false;

  const liste = Zustand.config?.sources || [];
  const nach = {};
  for (const q of liste) nach[q.key] = q;

  const bip = nach.bip158;
  if (!bip || !bip.configured) return false;

  // Eigener Node wirklich verbunden → Gap-Scan ohne BIP-158-Geburtstag.
  for (const key of ["own_fulcrum", "own_core"]) {
    const q = nach[key];
    if (q && q.configured && q.reachable === true) return false;
  }
  return true;
}

function vorschlagScanDatum(wallet) {
  const typ = (wallet && (wallet.script_type_effective || wallet.script_type)) || "";
  if (typ === "taproot" || typ === "tr") return "2021-11-14";
  if (typ === "legacy") return "2009-01-03";
  return "2017-08-24";
}

function frageScanDatum(wallet) {
  return new Promise((resolve) => {
    const dlg = $("#scan-datum-dialog");
    const feld = $("#scan-datum-feld");
    const hinweis = $("#scan-datum-hinweis");
    const ok = $("#scan-datum-ok");
    const abbruch = $("#scan-datum-abbruch");
    feld.value = vorschlagScanDatum(wallet);
    const typ = (wallet && (wallet.script_type_effective || wallet.script_type)) || "";
    hinweis.textContent =
      typ === "legacy"
        ? t("dialog.scanDate.hintGenesis")
        : typ === "taproot" || typ === "tr"
          ? t("dialog.scanDate.hintTaproot")
          : t("dialog.scanDate.hintSegwit");
    dlg.hidden = false;
    feld.focus();

    const fertig = (wert) => {
      ok.removeEventListener("click", onOk);
      abbruch.removeEventListener("click", onAbbruch);
      dlg.removeEventListener("keydown", onTaste);
      dlg.hidden = true;
      resolve(wert);
    };
    const onOk = () => fertig(feld.value || null);
    const onAbbruch = () => fertig(undefined);
    const onTaste = (ev) => {
      if (ev.key === "Escape") onAbbruch();
      if (ev.key === "Enter") onOk();
    };
    ok.addEventListener("click", onOk);
    abbruch.addEventListener("click", onAbbruch);
    dlg.addEventListener("keydown", onTaste);
  });
}

/**
 * Nach neuem Wallet: UTXO-Scan / Verlauf / manuell.
 * @returns {Promise<"utxo"|"verlauf"|"manuell">}
 */
function frageWalletScanWahl(wallet) {
  return new Promise((resolve) => {
    const dlg = $("#wallet-scan-wahl");
    const titel = $("#wallet-scan-wahl-titel");
    const text = $("#wallet-scan-wahl-text");
    const utxo = $("#wallet-scan-utxo");
    const verlauf = $("#wallet-scan-verlauf");
    const manuell = $("#wallet-scan-manuell");
    const name = (wallet && wallet.name) || "Wallet";
    titel.textContent = t("dialog.walletScan.titleNamed", { name });
    text.textContent = t("dialog.walletScan.body");
    dlg.hidden = false;
    utxo.focus();

    const fertig = (wahl) => {
      utxo.removeEventListener("click", onUtxo);
      verlauf.removeEventListener("click", onVerlauf);
      manuell.removeEventListener("click", onManuell);
      dlg.removeEventListener("keydown", onTaste);
      dlg.hidden = true;
      resolve(wahl);
    };
    const onUtxo = () => fertig("utxo");
    const onVerlauf = () => fertig("verlauf");
    const onManuell = () => fertig("manuell");
    const onTaste = (ev) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        onManuell();
      }
      if (ev.key === "Enter") {
        ev.preventDefault();
        onUtxo();
      }
    };
    utxo.addEventListener("click", onUtxo);
    verlauf.addEventListener("click", onVerlauf);
    manuell.addEventListener("click", onManuell);
    dlg.addEventListener("keydown", onTaste);
  });
}

async function nachNeuemWalletScannen(neuWallets) {
  if (!neuWallets || !neuWallets.length) return;
  for (const wallet of neuWallets) {
    const wahl = await frageWalletScanWahl(wallet);
    if (wahl === "utxo" || wahl === "verlauf") {
      await starteScanFuer({
        id: wallet.id,
        name: wallet.name,
        art: wahl,
      });
    } else {
      meldung(
        `„${wallet.name}“ gespeichert. Scans später in der Wallet-Ansicht.`,
        "gut",
      );
    }
  }
}

function starteRescan() {
  stelleScanAn("utxo");
}

function starteVerlaufsscan() {
  stelleScanAn("verlauf");
}

/** Inkrementell bis Chain-Tip — kein Fullscan (anders als UTXO-Scan). */
async function starteTipSync() {
  const wid = Zustand.walletId;
  if (!wid) return;
  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === wid);
  if (!wallet || !wallet.has_cache) {
    meldung(t("wallet.tipSyncNeedCache"), "warn");
    return;
  }
  if (walletSyncLaeuftFuer(wid)) {
    meldung(t("nav.jobAlreadyRunning"), "warn");
    return;
  }
  const knopf = $("#tip-sync-knopf");
  if (knopf) knopf.disabled = true;
  logZeile(
    t("wallet.tipSyncStarted", { name: wallet.name || wid }),
    undefined,
    wallet.name,
  );
  try {
    const antwort = await api("/jobs/wallet-sync", {
      methode: "POST",
      daten: { wallet_id: wid },
    });
    const jobId = antwort.job_id || antwort.job?.id;
    if (Zustand.config) {
      Zustand.config.wallet_sync_job_id = jobId;
    }
    folgeWalletSyncJob(jobId, antwort.job || { meta: { wallet_ids: [wid] } });
    await ladeJobsNav();
    setzeWalletScanGesperrt();
    zeichneNav();
  } catch (fehler) {
    meldung(fehler.message || String(fehler), "krit");
    logZeile(fehler.message || String(fehler), true, wallet.name);
    setzeWalletScanGesperrt();
  }
}

async function starteScanFuer(ziel) {
  if (ziel.art === "utxo" && brauchtBip158Startdatum(ziel.id)) {
    const wallet = (Zustand.config?.wallets || []).find((w) => w.id === ziel.id);
    const datum = await frageScanDatum(wallet);
    if (datum === undefined) return;
    ziel.scan_ab = datum;
  }

  if (schonGeplant(ziel)) {
    logZeile(
      `${scanArtName(ziel.art)} für „${ziel.name}“ läuft schon oder wartet.`,
      undefined,
      ziel.name,
    );
    setzeWalletScanGesperrt();
    return;
  }

  logZeile(
    `Starte ${scanArtName(ziel.art)} für „${ziel.name}“…`,
    undefined,
    ziel.name,
  );
  if (ziel.scan_ab) {
    logZeile(
      `BIP-158 nicht vor ${ziel.scan_ab.split("-").reverse().join(".")}.`,
      undefined,
      ziel.name,
    );
  }

  try {
    const job = ziel.art === "verlauf"
      ? await api("/verlauf", { methode: "POST", daten: { wallet_id: ziel.id } })
      : await api("/jobs/rescan", {
          methode: "POST",
          daten: { wallet_id: ziel.id, scan_ab: ziel.scan_ab || "" },
        });

    if (job.queue_status === "queued" || job.status === "queued") {
      logZeile(
        `${scanArtName(ziel.art)} für „${ziel.name}“ in die Warteschlange.`,
        undefined,
        ziel.name,
      );
      await ladeJobsNav();
      return;
    }

    bindeWalletScanJob(job, ziel);
    logZeile(
      "Browser darf geschlossen werden — Server und Scan laufen im Terminal weiter.",
      undefined,
      ziel.name,
    );
    await ladeJobsNav();
  } catch (fehler) {
    if (fehler && fehler.status === 409) {
      logZeile(fehler.message || t("nav.jobAlreadyRunning"), true, ziel.name);
      setzeWalletScanGesperrt();
      await ladeJobsNav();
      return;
    }
    beendeRescan(`${scanArtName(ziel.art)} fehlgeschlagen: ${fehler.message}`, true);
  }
}

function bindeWalletScanJob(job, ziel) {
  Zustand.scanWalletId = ziel.id;
  Zustand.scanWalletName = ziel.name || walletNameZu(ziel.id);
  Zustand.scanArt = ziel.art;
  Zustand.scanUtxoZahl = null;
  Zustand.scanRefreshUm = 0;
  Zustand.scanRefreshLaeuft = false;
  Zustand.scanLogIndex = 0;
  Zustand.scanLogStand = { index: 0, knoten: [], texte: [] };
  // Pending-Baseline neu: Scan-Ende/Refresh darf kein „In steigt“-Konfetti
  // für schon vorhandene Mempool-Txs auslösen.
  if (ziel.id) {
    Zustand.pendingByWallet[ziel.id] = { in: 0, out: 0, seen: false };
  }
  Zustand.rescanJob = job.id;
  nimmJobLog(job);
  aktualisiereScanAnzeige(job.message || "wird gestartet…");
  zeichneNav();
  // Empfangs-Pane: Herzschlag wenn dieses Wallet gewählt (Lern-QR weichen).
  if (Zustand.walletId === ziel.id) {
    Zustand.lernThema = null;
    EmpfangPuls.stop();
    ladeEmpfang(ziel.id).catch(() => {});
  }
  if (Zustand.rescanTimer) clearInterval(Zustand.rescanTimer);
  Zustand.rescanTimer = setInterval(pruefeWalletScan, 900);
}

/** Während UTXO-Scan: Cache-Zwischenstand höchstens alle ~2,5 s in die GUI. */
const SCAN_REFRESH_MS = 2500;

async function erfrischeScanZwischenstand(scanId, utxoZahl) {
  if (Zustand.scanRefreshLaeuft) return;
  const vorher = Zustand.scanUtxoZahl;
  const gestiegen = utxoZahl != null && (vorher == null || utxoZahl > vorher);
  if (!gestiegen && vorher != null) return;
  const jetzt = Date.now();
  if (jetzt - Zustand.scanRefreshUm < SCAN_REFRESH_MS && vorher != null) return;

  // Erster Fund-Schub: ein oranger ₿-Atemzug (nur wenn Betrag ≥ 500 sats
  // bekannt — Zwischenstand hat oft nur die Anzahl, dann kein Flash).
  // Weitere Funde während der Animation → still, Animation läuft aus.
  if (
    Zustand.walletId === scanId
    && typeof utxoZahl === "number"
    && utxoZahl > 0
    && (vorher == null || utxoZahl > vorher)
  ) {
    // Ohne Einzelbetrag: Mindestgröße (Dust = 500 → 15 %).
    EmpfangPuls.flashOrangeB(500);
  }

  Zustand.scanRefreshLaeuft = true;
  Zustand.scanRefreshUm = jetzt;
  if (utxoZahl != null) Zustand.scanUtxoZahl = utxoZahl;
  try {
    await ladeConfig();
    if (Zustand.ansicht === "wallet" && Zustand.walletId === scanId) {
      await zeigeWallet(Zustand.walletId);
    } else {
      zeichneNav();
    }
  } catch (_) {
    zeichneNav();
  } finally {
    Zustand.scanRefreshLaeuft = false;
  }
}

/**
 * Mempool-Pending → QR-Animation — nur für das *aktuell gewählte* Wallet.
 *
 * Konfetti **nur** wenn ``pending_receive`` steigt (neue TxIN im Mempool).
 * Nicht bei UTXO-Scan, Cache-Aufbau oder Empfangsadress-Sprung allein.
 *
 * Während Tip-Sync/Scan ist ``empfangScanLaeuftFuer`` true — dann merken wir
 * den Incoming und spielen Ka-Ching nach Sync-Ende nach (sonst: QR springt,
 * Konfetti fehlt).
 *
 * * In → Konfetti
 * * In+Out gleichzeitig (Self) → nur Konfetti
 * * internOut: Spend an eigenes Wallet → Konfetti
 * * sonst Out → OH NO!
 */
function merkeQueuedIncomingFlash(walletId) {
  if (!walletId) return;
  Zustand._queuedIncomingFlash = { walletId: String(walletId), um: Date.now() };
}

function holeQueuedIncomingFlash(walletId) {
  const q = Zustand._queuedIncomingFlash;
  if (!q || String(q.walletId) !== String(walletId)) return null;
  if (Date.now() - (q.um || 0) > 120000) {
    Zustand._queuedIncomingFlash = null;
    return null;
  }
  Zustand._queuedIncomingFlash = null;
  return q;
}

/**
 * Empfangs-Index ist weitergesprungen (Adresse benutzt) → Wallet-UTXOs inkl.
 * Mempool-Pending neu laden. Gedrosselt, damit Polls nicht fluten.
 */
function frischeWalletNachEmpfangSprung(walletId) {
  if (!walletId || Zustand.walletId !== walletId) return;
  if (Zustand.ansicht !== "wallet") return;
  if (typeof empfangScanLaeuftFuer === "function" && empfangScanLaeuftFuer(walletId)) {
    return;
  }
  const jetzt = Date.now();
  if (
    Zustand._lastEmpfangSprungRefreshUm
    && jetzt - Zustand._lastEmpfangSprungRefreshUm < 2500
  ) {
    return;
  }
  Zustand._lastEmpfangSprungRefreshUm = jetzt;
  // zeigeWallet: zweiter Request mit Mempool — Pending sichtbar.
  // Empfang nicht erneut anstoßen (ohneEmpfang), sonst QR-Loop / Animation-Kill.
  Promise.resolve(zeigeWallet(walletId, { ohneEmpfang: true })).catch(() => {});
}

/**
 * Mempool/History hat die gezeigte Adresse benutzt.
 * 1) Alter QR bleibt · 2) Konfetti · 3) Wallet-Update · 4) neuer QR nach Animation.
 */
function starteEmpfangSprungMitKonfetti(walletId, neueDaten, alterEmpfang) {
  // Schon in Konfetti: nur neueren Empfangsstand merken.
  if (Zustand._empfangSprungInArbeit === String(walletId)) {
    Zustand._pendingEmpfangNachKonfetti = {
      walletId: String(walletId),
      daten: neueDaten,
    };
    return neueDaten;
  }
  Zustand._pendingEmpfangNachKonfetti = { walletId: String(walletId), daten: neueDaten };
  Zustand._empfangSprungInArbeit = String(walletId);

  // Alten QR behalten (nicht neueDaten speichern/zeichnen).
  if (alterEmpfang && alterEmpfang.address) {
    Zustand.empfangByWallet[walletId] = alterEmpfang;
    Zustand.empfang = alterEmpfang;
    if (!empfangSonderAtemLaeuft()) {
      zeichneEmpfang(alterEmpfang, { zahlung: false });
    }
  }

  frischeWalletNachEmpfangSprung(walletId);

  const zeigeNeuenQr = () => {
    const pending = Zustand._pendingEmpfangNachKonfetti;
    Zustand._pendingEmpfangNachKonfetti = null;
    Zustand._empfangSprungInArbeit = null;
    if (!pending || String(pending.walletId) !== String(Zustand.walletId)) return;
    Zustand.empfangByWallet[pending.walletId] = pending.daten;
    Zustand.empfang = pending.daten;
    zeichneEmpfang(pending.daten, { zahlung: false });
  };

  const jetzt = Date.now();
  if (
    Zustand._lastIncomingFlashUm
    && jetzt - Zustand._lastIncomingFlashUm <= 4000
  ) {
    // Debounce: kein zweites Konfetti — neuen QR trotzdem nachziehen.
    zeigeNeuenQr();
    return neueDaten;
  }
  Zustand._lastIncomingFlashUm = jetzt;
  Zustand._queuedIncomingFlash = null;
  EmpfangPuls.flashIncoming(walletId, undefined, {
    halteDanach: false,
    onDone: zeigeNeuenQr,
  });
  return neueDaten;
}

/** Nach Tip-Sync/Scan: gemerktes Mempool-Incoming als Ka-Ching nachholen. */
function spieleQueuedIncomingFlash(walletId) {
  if (!walletId || Zustand.walletId !== walletId) return false;
  if (Zustand._empfangSprungInArbeit === String(walletId)) return false;
  if (typeof empfangScanLaeuftFuer === "function" && empfangScanLaeuftFuer(walletId)) {
    return false;
  }
  if (!holeQueuedIncomingFlash(walletId)) return false;
  const jetzt = Date.now();
  if (
    Zustand._lastIncomingFlashUm
    && jetzt - Zustand._lastIncomingFlashUm <= 4000
  ) {
    return false;
  }
  Zustand._lastIncomingFlashUm = jetzt;
  EmpfangPuls.flashIncoming(walletId, undefined, {
    halteDanach: false,
    onDone: () => {
      if (Zustand.walletId !== walletId) return;
      const pending = Zustand._pendingEmpfangNachKonfetti;
      if (pending && String(pending.walletId) === String(walletId)) {
        Zustand._pendingEmpfangNachKonfetti = null;
        Zustand.empfangByWallet[walletId] = pending.daten;
        Zustand.empfang = pending.daten;
        zeichneEmpfang(pending.daten, { zahlung: false });
        return;
      }
      ladeEmpfang(walletId, { still: true }).catch(() => {});
    },
  });
  return true;
}

function meldePendingAenderung(walletId, pendIn, pendOut, { internOut = false } = {}) {
  if (!walletId) return;
  const prev = Zustand.pendingByWallet[walletId] || { in: 0, out: 0 };
  const neuIn = Number(pendIn) || 0;
  const neuOut = Number(pendOut) || 0;
  Zustand.pendingByWallet[walletId] = { in: neuIn, out: neuOut };
  // Baseline ohne Animation: erster Stand, Scan/Refresh, Wallet-Wechsel.
  // Nur *Anstieg* nach gesehenem Stand = echte neue Mempool-Tx.
  const scanLaeuft = typeof empfangScanLaeuftFuer === "function"
    && empfangScanLaeuftFuer(walletId);
  if (prev.seen && Zustand.walletId === walletId) {
    const inNeu = neuIn > prev.in;
    const outNeu = neuOut > prev.out;
    const jetzt = Date.now();
    const darfIncoming = () => {
      if (
        Zustand._lastIncomingFlashUm
        && jetzt - Zustand._lastIncomingFlashUm <= 4000
      ) {
        return false;
      }
      Zustand._lastIncomingFlashUm = jetzt;
      return true;
    };
    const starteIncoming = () => {
      if (scanLaeuft) {
        // Tip-Sync läuft oft parallel: QR wird geschärft, Konfetti sonst verschluckt.
        merkeQueuedIncomingFlash(walletId);
        return;
      }
      if (!darfIncoming()) return;
      EmpfangPuls.flashIncoming(walletId, undefined, {
        halteDanach: false,
        onDone: () => {
          // Nach Konfetti: nächste freie Adresse holen (ohne erneuten Flash).
          if (Zustand.walletId === walletId) {
            ladeEmpfang(walletId).catch(() => {});
          }
        },
      });
    };
    if (inNeu && outNeu) {
      // Self-Send im selben Wallet: nur Konfetti.
      starteIncoming();
    } else if (inNeu) {
      starteIncoming();
    } else if (outNeu) {
      if (internOut) {
        // Interner Transfer (z. B. Cash+Carry → Bitkey): nur Konfetti, kein OH NO.
        starteIncoming();
      } else if (!scanLaeuft) {
        EmpfangPuls.flashOhNo();
      }
    }
  }
  Zustand.pendingByWallet[walletId].seen = true;
}

async function pruefeWalletScan() {
  if (!Zustand.rescanJob) return;
  const art = scanArtName();
  const scanId = Zustand.scanWalletId;
  try {
    const job = await api(`/jobs/${Zustand.rescanJob}`);
    nimmJobLog(job);
    aktualisiereScanAnzeige(job.message);
    if (job.running) {
      if (Zustand.scanArt === "utxo") {
        const zahl = job.result?.utxo_count;
        if (typeof zahl === "number") {
          await erfrischeScanZwischenstand(scanId, zahl);
        }
      }
      return;
    }

    if (job.status === "done") {
      beendeRescan("");
      Zustand.traceListe = null;
      await ladeConfig();
      if (Zustand.ansicht === "wallet" && Zustand.walletId === scanId) {
        await zeigeWallet(Zustand.walletId);
      } else {
        zeichneNav();
      }
      await ladeJobsNav();
    } else if (job.status === "cancelled") {
      // Abbruch: Zwischenstand bleibt im Cache — Liste einmal nachziehen.
      beendeRescan(`${art} abgebrochen.`, false);
      await erfrischeWalletNachScan(scanId);
      await ladeJobsNav();
    } else {
      // Fehler: Zwischenstand trotzdem zeigen, Meldung ins Log.
      const meldung = job.error || `${art} fehlgeschlagen.`;
      const name = Zustand.scanWalletName;
      beendeRescan(meldung, true);
      logZeile(meldung, true, name || undefined);
      await erfrischeWalletNachScan(scanId);
      await ladeJobsNav();
    }
  } catch (fehler) {
    beendeRescan(fehler.message, true);
    await ladeJobsNav();
  }
}

async function erfrischeWalletNachScan(scanId) {
  try {
    await ladeConfig();
    if (Zustand.ansicht === "wallet" && Zustand.walletId === scanId) {
      await zeigeWallet(Zustand.walletId);
    } else {
      zeichneNav();
    }
  } catch (_) {
    zeichneNav();
  }
}

function beendeRescan(_meldung, _istFehler = false) {
  clearInterval(Zustand.rescanTimer);
  Zustand.rescanTimer = null;
  const scanId = Zustand.scanWalletId;
  Zustand.rescanJob = null;
  Zustand.scanArt = null;
  Zustand.scanWalletId = null;
  Zustand.scanWalletName = "";
  Zustand.scanUtxoZahl = null;
  Zustand.scanRefreshUm = 0;
  Zustand.scanRefreshLaeuft = false;
  if (scanId) {
    Zustand.pendingByWallet[scanId] = { in: 0, out: 0, seen: false };
  }
  EmpfangPuls.stop();
  const leiste = $("#rescan-lauf");
  const pipe = scanPipeline();
  if (leiste && !pipe.current && !(pipe.queued || []).length) {
    leiste.hidden = true;
    leiste.classList.remove("hinweis-fremd");
  }
  setzeWalletScanGesperrt();
  // Wallet-Inhalt kommt vom Cache-Zwischenstand (Caller refreshed) —
  // hier keine Leer-Meldung mehr, die gefundene UTXOs verdecken würde.
  zeichneNav();
  if (scanId && Zustand.walletId === scanId && !Zustand.lernThema) {
    ladeEmpfang(scanId).catch(() => {});
  }
}

// ---------------------------------------------------------------------------
// Nav: laufende Nutzer-Jobs (Server-Wahrheit, GUI-zu-fest)
// ---------------------------------------------------------------------------

function nimmBlockEvent(daten) {
  const ev = daten && daten.block_event;
  if (!ev || ev.height == null || !ev.seq) return;
  const seq = Number(ev.seq);
  const hoehe = Number(ev.height);
  if (!Number.isFinite(seq) || !Number.isFinite(hoehe)) return;
  // Erster Poll: nur Baseline — kein Atem beim Seitenladen.
  if (!Zustand.blockEventSeqInit) {
    Zustand.blockEventSeqInit = true;
    Zustand.blockEventSeq = seq;
    return;
  }
  if (seq <= (Zustand.blockEventSeq || 0)) return;
  Zustand.blockEventSeq = seq;
  try {
    EmpfangPuls.flashNeuerBlock(hoehe);
  } catch (_) {
    /* Animation optional */
  }
}

async function ladeJobsNav() {
  try {
    const daten = await api("/jobs?recent_s=3");
    Zustand.jobsNav = {
      jobs: daten.jobs || [],
      scan_pipeline: daten.scan_pipeline || { current: null, queued: [] },
    };
    Zustand.jobsNavFehler = "";
    nimmBlockEvent(daten);
  } catch (fehler) {
    /* offline / alter Server ohne /api/jobs */
    Zustand.jobsNavFehler = (fehler && fehler.message) || t("common.netError");
  }
  zeichneJobsNav();
  setzeWalletScanGesperrt();
  // Re-Attach: laufender Scan ohne lokalen Poller
  const pipe = scanPipeline();
  const cur = pipe.current;
  if (cur && cur.job_id && !Zustand.rescanTimer) {
    const art = cur.kind === "verlauf" ? "verlauf" : "utxo";
    bindeWalletScanJob(
      { id: cur.job_id, message: cur.message || "" },
      {
        id: cur.wallet_id,
        name: cur.meta?.wallet_name || cur.label || walletNameZu(cur.wallet_id),
        art,
      },
    );
  }
  // Tip-Sync-Job aus Nav übernehmen (Watcher/Start), falls noch kein Poller.
  // Stille Watch-Fallbacks mitverfolgen (Log), aber Nav-Marker bleiben aus.
  const tipJob = (Zustand.jobsNav?.jobs || []).find(
    (j) =>
      j
      && j.kind === "wallet_sync"
      && (j.running || j.status === "running" || j.status === "queued"),
  );
  if (tipJob && !Zustand.walletSyncJob) {
    folgeWalletSyncJob(tipJob.id, tipJob);
  } else if (tipJob && Zustand.walletSyncJob === tipJob.id) {
    merkeWalletSyncZiele(tipJob);
    if (jobIstStillerTip(tipJob)) Zustand.walletSyncStill = true;
  }
  // Scan-Puls ohne laufenden Scan/Sync → Empfang neu laden (stoppt hängenden Puls).
  if (
    Zustand.walletId
    && Zustand.empfang
    && Zustand.empfang.puls
    && !empfangScanLaeuftFuer(Zustand.walletId)
  ) {
    ladeEmpfang(Zustand.walletId).catch(() => {});
  }
  // Nav-Marker „aktualisiere…“ nur neu zeichnen, wenn sich Tip-Sync-Lage ändert.
  const syncSig = (Zustand.jobsNav?.jobs || [])
    .filter((j) =>
      j
      && j.kind === "wallet_sync"
      && !j.meta?.still
      && j.meta?.phase !== "empfang"
      && (j.running || j.status === "running" || j.status === "queued"),
    )
    .map((j) => `${j.id}:${(j.meta?.wallet_ids || []).join(",")}`)
    .sort()
    .join("|");
  // Auch Empfangs-Phase aus /jobs-Meta übernehmen (falls Poller vor Job-Detail).
  const empfangPhase = (Zustand.jobsNav?.jobs || []).some(
    (j) =>
      j
      && j.kind === "wallet_sync"
      && j.meta?.phase === "empfang"
      && (j.running || j.status === "running"),
  );
  if (empfangPhase && Zustand.walletSyncPhase !== "empfang") {
    Zustand.walletSyncPhase = "empfang";
    if (Zustand.walletSyncLogStand) {
      Zustand.walletSyncLogStand._tipUiFertig = true;
    }
  }
  if (
    syncSig !== Zustand._walletSyncNavSig
    || empfangPhase !== Boolean(Zustand._walletSyncEmpfangSig)
  ) {
    Zustand._walletSyncNavSig = syncSig;
    Zustand._walletSyncEmpfangSig = empfangPhase;
    zeichneNav();
  }
  aktualisiereScanAnzeige(
    Zustand.rescanJob
      ? ($("#rescan-text") && $("#rescan-text").textContent) || undefined
      : undefined,
  );
}

function jobNavZeileText(job, pipe) {
  if (job.kind === "rescan" || job.kind === "verlauf") {
    const cur = pipe?.current;
    if (cur && cur.job_id === job.id) {
      let text = job.label || cur.label || "";
      const q = pipe.queued || [];
      if (q.length) {
        const rest = q.map((e) => e.label || e.wallet_name).filter(Boolean);
        if (rest.length) text += `, dann ${rest.join(", ")}`;
      }
      return text;
    }
  }
  return job.label || job.kind;
}

function jobIstKlickbar(job) {
  const kind = job.kind;
  if (kind === "rescan" || kind === "verlauf") {
    return Boolean(job.meta?.wallet_id || scanPipeline().current?.wallet_id);
  }
  if (kind === "trace" || kind === "trace-alle" || kind === "trace-tief") return true;
  if (kind === "labels" || kind === "sanctions" || kind === "sanctions-check") {
    return true;
  }
  if (kind === "wallet_sync") {
    const ids = job.meta?.wallet_ids;
    return Array.isArray(ids) && ids.length > 0;
  }
  return false;
}

function springeZuJob(job) {
  const kind = job.kind;
  if (kind === "rescan" || kind === "verlauf") {
    const wid = job.meta?.wallet_id || scanPipeline().current?.wallet_id;
    if (wid) zeigeWallet(wid);
    return;
  }
  if (kind === "wallet_sync") {
    const ids = job.meta?.wallet_ids;
    if (Array.isArray(ids) && ids[0]) zeigeWallet(ids[0]);
    return;
  }
  if (kind === "trace" || kind === "trace-alle" || kind === "trace-tief") {
    if (kind === "trace-tief" && job.meta?.wallet_id) {
      zeigeWallet(job.meta.wallet_id);
      return;
    }
    if (kind === "trace" && job.meta?.target) {
      if ($("#trace-ziel")) $("#trace-ziel").value = job.meta.target;
      // Laufenden Job anbinden — Wallet aus Job-Meta (überlebt Browser-Neustart).
      zeigeHerkunftFuer(job.meta.target, {
        jobId: job.running ? job.id : null,
        meta: {
          key: job.meta.target,
          wallet: job.meta.wallet_name || job.meta.wallet || "",
          value_sats: job.meta.value_sats ?? null,
          address: job.meta.address || "",
        },
      });
      return;
    }
    zeigeAnsicht("trace");
    return;
  }
  if (kind === "labels" || kind === "sanctions") {
    oeffneVerwaltung("datenquellen");
    return;
  }
  if (kind === "sanctions-check") {
    zeigeAnsicht("sanktionen");
    fuellSankWallets();
    // Laufenden Check wieder an die Fortschrittszeile binden (sonst fehlt
    // die Leiste nach Seitenwechsel — Timer/UI waren nur lokal in starte…).
    if (job.running && job.id) {
      bindeSanktionsCheckJob(job.id, { hops: job.meta?.hops });
    } else {
      ladeSankCache();
    }
  }
}

function zeichneJobsNav() {
  const kasten = $("#nav-jobs");
  if (!kasten) return;
  const pipe = scanPipeline();
  const jobs = Zustand.jobsNav?.jobs || [];
  // Scan-Pipeline: eine Zeile für current+queued; andere Jobs einzeln.
  const scanJobIds = new Set();
  if (pipe.current?.job_id) scanJobIds.add(pipe.current.job_id);

  const zeilen = [];
  if (pipe.current || (pipe.queued || []).length) {
    const curJob = jobs.find((j) => j.id === pipe.current?.job_id);
    const label = jobNavZeileText(
      curJob || {
        id: pipe.current?.job_id,
        kind: pipe.current?.kind || "rescan",
        label: pipe.current?.label || t("common.runningEllipsis"),
        meta: pipe.current?.meta,
      },
      pipe,
    );
    const msg = curJob?.message || pipe.current?.message || "";
    zeilen.push({
      key: "scan-pipe",
      label,
      msg,
      status: curJob?.status || (pipe.current ? "running" : "queued"),
      job: curJob || {
        kind: pipe.current?.kind || "rescan",
        meta: pipe.current?.meta || {},
      },
    });
  }
  for (const job of jobs) {
    if (scanJobIds.has(job.id)) continue;
    if (job.kind === "rescan" || job.kind === "verlauf") {
      // Nur anzeigen wenn nicht schon in Pipeline-Zeile
      if (pipe.current || (pipe.queued || []).length) continue;
    }
    zeilen.push({
      key: job.id,
      label: job.label,
      msg: job.message || job.error || "",
      status: job.status,
      job,
    });
  }

  kasten.replaceChildren();
  // Immer sichtbar unter „Datenquellen“, sonst wirkt die Feature unsichtbar.
  kasten.hidden = false;
  const kopf = document.createElement("div");
  kopf.className = "nav-jobs-titel";
  kopf.textContent = t("nav.jobsTitle");
  kasten.append(kopf);

  if (Zustand.jobsNavFehler) {
    const err = document.createElement("div");
    err.className = "nav-job nav-job-leer";
    err.textContent = t("nav.jobsError", { msg: Zustand.jobsNavFehler });
    kasten.append(err);
    return;
  }

  if (!zeilen.length) {
    const leer = document.createElement("div");
    leer.className = "nav-job nav-job-leer";
    leer.textContent = t("nav.jobsEmpty");
    kasten.append(leer);
    return;
  }
  for (const z of zeilen) {
    const zeile = document.createElement("div");
    zeile.className = "nav-job-zeile";
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "nav-job";
    if (z.status === "done") knopf.classList.add("nav-job-ende", "nav-job-gut");
    else if (z.status === "failed" || z.status === "cancelled") {
      knopf.classList.add("nav-job-ende");
    }
    const klickbar = jobIstKlickbar(z.job);
    if (klickbar) knopf.classList.add("klickbar");
    const lab = document.createElement("span");
    lab.className = "nav-job-label";
    lab.textContent = z.label;
    knopf.append(lab);
    if (z.msg) {
      const msg = document.createElement("span");
      msg.className = "nav-job-msg";
      msg.textContent = z.msg.length > 80 ? `${z.msg.slice(0, 77)}…` : z.msg;
      knopf.append(msg);
    }
    if (klickbar) {
      knopf.addEventListener("click", () => springeZuJob(z.job));
    }
    zeile.append(knopf);
    // Abbruch an jedem laufenden Vorgang — nicht nur an speziellen Statuszeilen.
    const laeuft = z.status === "running" || z.status === "queued";
    const jobId = (z.job && z.job.id)
      || (z.key === "scan-pipe" ? (pipe.current && pipe.current.job_id) : z.key);
    if (laeuft && jobId && !String(jobId).startsWith("cache-")) {
      const abbruch = document.createElement("button");
      abbruch.type = "button";
      abbruch.className = "knopf knopf-klein nav-job-abbruch";
      abbruch.textContent = t("common.cancel");
      abbruch.title = t("common.cancel");
      abbruch.addEventListener("click", async (ereignis) => {
        ereignis.preventDefault();
        ereignis.stopPropagation();
        abbruch.disabled = true;
        try {
          await api(`/jobs/${jobId}`, { methode: "DELETE" });
        } catch (fehler) {
          // 409 = schon weg — ok; sonst kurz melden (sonst wirkt der Knopf tot).
          if (!(fehler && fehler.status === 409)) {
            meldung(
              (fehler && fehler.message) || t("common.failed"),
              "krit",
            );
          }
        }
        // Rescan-Statuszeile mitziehen, falls es der aktive Scan war.
        if (Zustand.rescanJob === jobId) {
          setzeText($("#rescan-text"), t("common.abortRequested"));
          const rk = $("#rescan-abbruch");
          if (rk) rk.disabled = true;
          try {
            await pruefeWalletScan();
          } catch (_) {
            /* nächster Takt */
          }
        }
        await ladeJobsNav();
      });
      zeile.append(abbruch);
    }
    kasten.append(zeile);
  }
}

function setzeJobsTakt() {
  if (Zustand.jobsTimer) clearInterval(Zustand.jobsTimer);
  Zustand.jobsTimer = setInterval(() => {
    ladeJobsNav();
  }, 2000);
}

async function brichRescanAb() {
  if (!Zustand.rescanJob) return;
  setzeText($("#rescan-text"), t("common.abortRequested"));
  const knopf = $("#rescan-abbruch");
  if (knopf) knopf.disabled = true;
  try {
    await api(`/jobs/${Zustand.rescanJob}`, { methode: "DELETE" });
  } catch (_) {
    /* Vorgang war bereits beendet */
  }
  // Nicht sofort beendeRescan: Backend braucht den Cancel-Event in den
  // Filter/Block-Workern. pruefeWalletScan beendet bei status=cancelled.
  await ladeJobsNav();
  // Einmal sofort pollen — sonst klebt die Zeile bis zum 2s-Takt.
  try {
    await pruefeWalletScan();
  } catch (_) {
    /* Poll-Fehler: nächster Takt */
  }
}


async function verlaufErheben() {
  const knopf = $("#verlauf-erheben");
  knopf.disabled = true;
  $("#herkunft-lauf").hidden = false;
  setzeText($("#herkunft-text"), "Verlauf wird vorbereitet…");

  let jobId = null;
  let timer = null;
  const logStand = { index: 0 };

  const fertig = async (meldung, art) => {
    clearInterval(timer);
    knopf.disabled = false;
    $("#herkunft-lauf").hidden = true;
    if (meldung) {
      const kasten = $("#steuer-meldung");
      kasten.className = `hinweis hinweis-${art}`;
      setzeText(kasten, meldung);
      kasten.hidden = false;
    }
    // UTXO-Cache-mtime / scan_tip → Nav „gerade eben“ (wie Einzel-Verlaufsscan).
    // Ohne ladeConfig blieb Zustand.config alt, bis zum Browser-Refresh.
    try {
      await ladeConfig();
    } catch (_) {
      zeichneNav();
    }
    await ladeSteuerjahrMitKandidaten();
    await ladeJobsNav();
  };

  logZeile(t("ui.hard.81c16e3fef"));
  try {
    const start = await api("/verlauf", { methode: "POST", daten: {} });
    jobId = start.id;
    nimmJobLogAb(start, logStand);
  } catch (fehler) {
    await fertig(`Verlauf fehlgeschlagen: ${fehler.message}`, "krit");
    return;
  }

  $("#herkunft-abbruch").onclick = async () => {
    setzeText($("#herkunft-text"), "Abbruch angefordert…");
    try {
      await api(`/jobs/${jobId}`, { methode: "DELETE" });
    } catch (_) {
      /* war bereits beendet */
    }
  };

  timer = setInterval(async () => {
    if (!timer) return;
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmJobLogAb(job, logStand);
      setzeText($("#herkunft-text"), übersetzeLogText(job.message || t("common.runningEllipsis")));
      if (job.running) return;
      // Intervall sofort stoppen — sonst läuft der nächste Tick parallel zu fertig.
      clearInterval(timer);
      timer = null;
      if (job.status === "done") {
        await fertig(job.message || "Verlauf erfasst.", "gut");
      } else if (job.status === "cancelled") {
        await fertig("Abgebrochen — bereits erfasste Wallets bleiben erhalten.", "warn");
      } else {
        await fertig(job.error || "Verlauf fehlgeschlagen.", "krit");
      }
    } catch (fehler) {
      clearInterval(timer);
      timer = null;
      await fertig(fehler.message, "krit");
    }
  }, 1200);
}




// ---------------------------------------------------------------------------
// Einstellungen
// ---------------------------------------------------------------------------

/**
 * Stellt eine Multisig-Wallet schreibgeschützt dar.
 *
 * Anlegen und Ändern geschieht in der .env — hier fehlt der Editor für
 * Cosigner und Schwellwert. Sichtbar sein muss sie trotzdem: Sonst wüsste
 * niemand, dass sie konfiguriert ist, und ein Speichern sähe aus, als hätte
 * die Oberfläche sie verloren.
 */
function zeigeMultisig(zeile, wallet, typWahl, ergebnisFeld) {
  typWahl.disabled = true;
  typWahl.title = t("ui.hard.dff0e41104");
  const pruefen = zeile.querySelector(".pruefen");
  if (pruefen) pruefen.disabled = true;

  const xpubFeld = zeile.querySelector(".xpub-anzeige");
  if (xpubFeld) {
    xpubFeld.textContent =
      `${t("wallets.thresholdOf", { m: wallet.threshold ?? "?", n: wallet.cosigner_count })} · ` +
      (wallet.xpubs_masked || []).join(", ");
  }

  if (ergebnisFeld) {
    ergebnisFeld.textContent =
      "Multisig: gespeichert und hier sichtbar. Bestände und Herkunft werden " +
      "dafür noch nicht ermittelt.";
  }
}

/** Kompatibilität: Wallet-Seite neu zeichnen (früher alles unter Einstellungen). */
function zeichneEinstellungen() {
  zeichneWalletVerwaltung();
}

function zeichneWalletVerwaltung() {
  const liste = $("#wallet-liste");
  if (!liste) return;
  liste.replaceChildren();

  const vorlage = $("#vorlage-wallet");
  Zustand.entwurf.forEach((wallet, index) => {
    const fragment = vorlage.content.cloneNode(true);
    const zeile = fragment.querySelector(".wallet-zeile");

    const name = zeile.querySelector(".wallet-name");
    name.value = wallet.name;
    const haken = zeile.querySelector(".name-uebernehmen");
    const aktualisiereKnopf = () => {
      if (haken) haken.disabled = !walletZeileGeaendert(wallet);
    };
    name.addEventListener("input", () => {
      wallet.name = name.value;
      aktualisiereKnopf();
    });
    name.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && walletZeileGeaendert(wallet)) {
        e.preventDefault();
        speichereWallets(false);
      }
    });
    if (haken) {
      haken.addEventListener("click", () => speichereWallets(false));
      aktualisiereKnopf();
    }

    zeile.querySelector(".prefix-marker").textContent = wallet.prefix || "?";

    const cache = zeile.querySelector(".cache-pille");
    if (wallet.is_new) {
      cache.className = "pille pille-warn";
      cache.textContent = t("wallets.newBadge");
    } else if (wallet.export_import === "complete") {
      // Sparrow/Wasabi: alle Export-Adressen zugeordnet.
      cache.className = "pille pille-gut";
      cache.textContent = t("wallets.importedOk");
      const teile = [
        t("wallets.importedOkTitle"),
        Number(wallet.utxo_count) > 0 ? `${wallet.utxo_count} UTXO` : "",
        Number(wallet.export_verlauf_n) > 0
          ? `${wallet.export_verlauf_n} Tx`
          : "",
        walletAlter(wallet),
      ];
      cache.title = teile.filter(Boolean).join(" · ");
    } else if (wallet.export_import === "partial") {
      // Sparrow/Wasabi: noch Einträge ohne Adresse.
      cache.className = "pille pille-warn";
      cache.textContent = t("wallets.importedPartial");
      cache.title = t("wallets.importedPartialTitle", {
        ohne: wallet.export_ohne_adresse || 0,
        n: wallet.export_verlauf_n || 0,
      });
    } else if (wallet.has_cache) {
      cache.className = "pille pille-gut";
      const hinweis = cacheHinweis(wallet);
      const nUtxo = Number(wallet.utxo_count) || 0;
      cache.textContent = hinweis || (nUtxo ? `${nUtxo} UTXO` : t("wallets.importedOk"));
      cache.title = [hinweis, walletAlter(wallet)].filter(Boolean).join(" · ");
    } else {
      cache.className = "pille pille-warn";
      cache.textContent = t("wallet.noCache");
    }

    zeile.querySelector(".xpub-anzeige").textContent =
      wallet.is_new ? wallet.xpub : wallet.xpub_masked;

    const typ = zeile.querySelector(".typ-wahl");
    for (const eintrag of Zustand.config.script_types) {
      const option = document.createElement("option");
      option.value = eintrag.value;
      option.textContent = scriptTypLabel(eintrag.value, eintrag.label);
      typ.append(option);
    }
    typ.value = wallet.script_type;
    typ.addEventListener("change", () => {
      wallet.script_type = typ.value;
      aktualisiereKnopf();
    });

    const tiefe = zeile.querySelector(".tiefe-wahl");
    tiefe.value = wallet.max_addresses;
    tiefe.addEventListener("change", () => {
      wallet.max_addresses = Math.max(2, parseInt(tiefe.value, 10) || 50);
      tiefe.value = wallet.max_addresses;
      aktualisiereKnopf();
    });

    const nurLesen = zeile.querySelector(".read-only-wahl");
    if (nurLesen) {
      nurLesen.checked = Boolean(wallet.read_only);
      nurLesen.addEventListener("change", () => {
        wallet.read_only = Boolean(nurLesen.checked);
        aktualisiereKnopf();
      });
    }

    const ergebnisFeld = zeile.querySelector(".probe-ergebnis");
    zeile.querySelector(".pruefen").addEventListener("click", (ereignis) => {
      pruefeSkripttyp(wallet, ergebnisFeld, ereignis.currentTarget);
    });

    // Multisig lässt sich hier nicht bearbeiten: Cosigner, Schwellwert und
    // Skripttyp stehen in der .env. Änderbar sind Name und Scan-Tiefe; alles
    // andere wird angezeigt und unverändert zurückgeschickt.
    if (wallet.is_multisig) {
      zeigeMultisig(zeile, wallet, typ, ergebnisFeld);
    }

    zeile.querySelector(".entfernen").addEventListener("click", () => {
      const nameHint = wallet.name || wallet.xpub_masked || t("wallets.thisWallet");
      const ok = window.confirm(
        t("wallets.confirmRemove", { name: nameHint }),
      );
      if (!ok) return;
      Zustand.entwurf.splice(index, 1);
      // Name merken — speichereWallets loggt „Lösche …“ / „Löschen beendet“.
      speichereWallets(false, false, null, [nameHint]);
    });

    liste.append(fragment);
  });
  if (window.SatSageI18n) window.SatSageI18n.applyDom(liste);
  ladeGefahrWallets();

  if (Zustand.entwurf.length === 0) {
    const leer = document.createElement("div");
    leer.className = "wallet-zeile";
    leer.style.color = "var(--blass)";
    leer.textContent = t("wallets.emptyList");
    liste.append(leer);
  }

  setzeText(
    $("#wallet-anzahl"),
    t("wallets.keyCountOrder", { count: Zustand.entwurf.length })
  );
  setzeEnvPfad(Zustand.config?.env_path);
  ladeUnreferenziertenCache();
  ladeCacheDashboard();
}

function setzeZeileAktualisieren(zeile, wallet) {
  if (!zeile || !zeile.querySelector) return;
  const knopf = zeile.querySelector(".name-uebernehmen");
  if (knopf) knopf.disabled = !walletZeileGeaendert(wallet);
}

/**
 * Zeile über „Speichern“: Cache von Wallets, die nicht mehr in der .env stehen.
 * Nur sichtbar, wenn es wirklich etwas zu löschen gibt — Aufräumen, kein Danger.
 */
async function ladeUnreferenziertenCache() {
  const kasten = $("#cache-unreferenziert");
  if (!kasten) return;
  try {
    const stand = await api("/cache/unreferenziert");
    zeichneUnreferenziertenCache(stand);
  } catch (_) {
    kasten.hidden = true;
  }
}

function zeichneUnreferenziertenCache(stand) {
  const kasten = $("#cache-unreferenziert");
  const text = $("#cache-unreferenziert-text");
  const knopf = $("#cache-unreferenziert-loeschen");
  if (!kasten || !text || !knopf) return;

  const bytes = Number(stand?.bytes || 0);
  const dateien = Number(stand?.dateien || 0);
  if (!stand?.vorhanden || dateien <= 0 || bytes < 0) {
    kasten.hidden = true;
    return;
  }

  const mb = Number(stand.groesse_mb || 0);
  const mbText = Number.isFinite(mb)
    ? `${mb.toLocaleString(formatLocale(), {
        minimumFractionDigits: mb >= 0.1 || mb === 0 ? 1 : 3,
        maximumFractionDigits: 3,
      })} MB`
    : (stand.groesse_label || "0 MB");
  const n = Number(stand.kennungen || 0);
  const was = n === 1
    ? t("ui.hard.1ec1e4421a")
    : `${n || "?"} entfernten Wallets`;
  text.textContent =
    `Cache von ${was} liegt noch auf der Platte (${mbText}, ${dateien} Dateien) — ` +
    `die Oberfläche nutzt ihn nicht mehr.`;
  knopf.textContent = t("wallets.clearUnreferenced", { size: mbText });
  kasten.hidden = false;
}

async function loescheUnreferenziertenCache() {
  const knopf = $("#cache-unreferenziert-loeschen");
  if (knopf) knopf.disabled = true;
  try {
    const ergebnis = await api("/cache/unreferenziert", { methode: "DELETE" });
    const label = ergebnis.groesse_label || "0 MB";
    const n = ergebnis.dateien || 0;
    const text = n
      ? t("ui.hard.92f53adbad", { label, n })
      : t("ui.hard.0b2ff9302a");
    meldung(text, "gut");
    logZeile(text);
    zeichneUnreferenziertenCache({ vorhanden: false, dateien: 0, bytes: 0 });
    await ladeCacheDashboard();
  } catch (fehler) {
    meldung(t("ui.hard.2ce465fdb1", { msg: fehler.message }), "krit");
  } finally {
    if (knopf) knopf.disabled = false;
    await ladeUnreferenziertenCache();
  }
}

async function ladeCacheDashboard() {
  const karte = $("#cache-dashboard");
  if (!karte) return;
  const meldungEl = $("#cache-dash-meldung");
  try {
    const stand = await api("/cache/stats");
    zeichneCacheDashboard(stand);
    if (meldungEl) meldungEl.hidden = true;
  } catch (fehler) {
    if (meldungEl) {
      setzeText(meldungEl, t("wallets.cacheDashError", { error: fehler.message }));
      meldungEl.hidden = false;
    }
  }
}

function _cacheDashKachel(titel, wert, meta, ampel) {
  const kachel = document.createElement("div");
  kachel.className = "cache-dash-kachel";
  const tEl = document.createElement("div");
  tEl.className = "titel";
  tEl.textContent = titel;
  const wEl = document.createElement("div");
  wEl.className = "wert" + (ampel === "warn" || ampel === "krit" ? ` ${ampel}` : "");
  wEl.textContent = wert;
  kachel.append(tEl, wEl);
  if (meta) {
    const m = document.createElement("div");
    m.className = "meta";
    m.textContent = meta;
    kachel.append(m);
  }
  return kachel;
}

function zeichneCacheDashboard(stand) {
  const zusatz = $("#cache-dash-zusatz");
  const platte = $("#cache-dash-platte");
  const balken = $("#cache-dash-balken");
  const kacheln = $("#cache-dash-kacheln");
  const wallets = $("#cache-dash-wallets");
  if (!platte || !balken || !kacheln || !wallets) return;

  if (zusatz) {
    setzeText(zusatz, t("wallets.cacheDashSum", { size: stand.summe_label || "0 MB" }));
  }

  platte.replaceChildren();
  const ampel = document.createElement("span");
  const platteStand = stand.platte || {};
  ampel.className = `cache-dash-ampel ${platteStand.ampel || ""}`;
  const text = document.createElement("span");
  if (platteStand.free_bytes == null) {
    text.textContent = t("wallets.cacheDashDiskUnknown");
  } else {
    const pct = Math.round((Number(platteStand.free_ratio) || 0) * 1000) / 10;
    text.textContent = t("wallets.cacheDashDisk", {
      free: platteStand.free_label || "—",
      total: platteStand.total_label || "—",
      pct,
    });
  }
  platte.append(ampel, text);
  if (platteStand.write_blocked) {
    const warn = document.createElement("span");
    warn.className = "meta";
    warn.textContent = t("wallets.cacheDashDiskBlocked");
    platte.append(warn);
  }

  const utxoB = Number(stand.utxo_cache?.bytes || 0);
  const immB = Number(stand.immutable_cache?.bytes || 0);
  const sankB = Number(stand.sanctioned_cache?.bytes || 0);
  const sumB = Math.max(1, utxoB + immB + sankB);
  balken.replaceChildren();
  const segs = [
    ["seg-utxo", utxoB],
    ["seg-immutable", immB],
    ["seg-sanctioned", sankB],
  ];
  for (const [cls, bytes] of segs) {
    if (bytes <= 0) continue;
    const seg = document.createElement("span");
    seg.className = cls;
    seg.style.flex = String(bytes / sumB);
    seg.title = `${cls.replace("seg-", "")}: ${format_dateigroesse_client(bytes)}`;
    balken.append(seg);
  }

  const flatAmpel = stand.tx?.ampel || stand.utxo_ingress?.ampel || "gut";
  kacheln.replaceChildren(
    _cacheDashKachel(
      t("wallets.cacheDashTileUtxo"),
      stand.utxo_cache?.groesse_label || "0 MB",
      t("wallets.cacheDashFiles", { n: formatZahl(stand.utxo_cache?.dateien || 0) }),
    ),
    _cacheDashKachel(
      t("wallets.cacheDashTileImmutable"),
      stand.immutable_cache?.groesse_label || "0 MB",
      t("wallets.cacheDashFiles", { n: formatZahl(stand.immutable_cache?.dateien || 0) }),
    ),
    _cacheDashKachel(
      t("wallets.cacheDashTileTx"),
      stand.tx?.groesse_label || "0 MB",
      `${t("wallets.cacheDashFiles", { n: formatZahl(stand.tx?.dateien || 0) })} · ${t("wallets.cacheDashSchwelle", { n: formatZahl(stand.tx?.schwelle || 10000) })}`,
      flatAmpel,
    ),
    _cacheDashKachel(
      t("wallets.cacheDashTileIngress"),
      stand.utxo_ingress?.groesse_label || "0 MB",
      t("wallets.cacheDashFiles", { n: formatZahl(stand.utxo_ingress?.dateien || 0) }),
      flatAmpel,
    ),
    _cacheDashKachel(
      t("wallets.cacheDashTileHeaders"),
      stand.p2p_headers?.groesse_label || "0 MB",
      stand.p2p_headers?.tip != null
        ? t("wallets.cacheDashHeaderTip", { tip: formatZahl(stand.p2p_headers.tip) })
        : "—",
    ),
    _cacheDashKachel(
      t("wallets.cacheDashTileSanctions"),
      stand.sanctioned_cache?.groesse_label || "0 MB",
      t("wallets.cacheDashFiles", { n: formatZahl(stand.sanctioned_cache?.dateien || 0) }),
    ),
    _cacheDashKachel(
      t("wallets.cacheDashTileExternal"),
      stand.external_addresses?.groesse_label || "0 MB",
      stand.external_addresses?.vorhanden ? "JSON" : "—",
    ),
    _cacheDashKachel(
      t("wallets.cacheDashTilePrice"),
      stand.btc_price?.groesse_label || "0 MB",
      t("wallets.cacheDashFiles", { n: formatZahl(stand.btc_price?.dateien || 0) }),
    ),
  );

  wallets.replaceChildren();
  const liste = Array.isArray(stand.wallets) ? stand.wallets : [];
  if (liste.length === 0) {
    const leer = document.createElement("p");
    leer.className = "meta";
    leer.textContent = t("wallets.cacheDashEmpty");
    wallets.append(leer);
    return;
  }

  const tabelle = document.createElement("table");
  const kopf = document.createElement("tr");
  const spalten = [
    ["wallets.cacheDashColWallet", false],
    ["wallets.cacheDashColUtxo", true],
    ["wallets.cacheDashColSats", true],
    ["wallets.cacheDashColTip", true],
    ["wallets.cacheDashColGap", true],
    ["wallets.cacheDashColVerlauf", true],
    ["wallets.cacheDashColHerkunft", true],
    ["wallets.cacheDashColSize", true],
  ];
  for (const [key, zahl] of spalten) {
    const th = document.createElement("th");
    if (zahl) th.className = "zahl";
    th.textContent = t(key);
    kopf.append(th);
  }
  tabelle.append(kopf);

  for (const w of liste) {
    const zeile = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = w.wallet_name || w.wallet_id || "—";
    zeile.append(name);

    const zelle = (text, zahl = true) => {
      const td = document.createElement("td");
      if (zahl) td.className = "zahl mono";
      td.textContent = text;
      zeile.append(td);
    };

    zelle(formatZahl(w.utxo_count || 0));
    zelle(formatSats(w.total_sats || 0));
    if (w.tip_lag == null) zelle("—");
    else if (Number(w.tip_lag) <= 0) zelle(t("wallets.cacheDashLagOk"));
    else zelle(t("wallets.cacheDashLag", { n: formatZahl(w.tip_lag) }));

    if (w.scan_end_index == null || !w.max_addresses) zelle("—");
    else zelle(`${formatZahl(w.scan_end_index)}/${formatZahl(w.max_addresses)}`);

    zelle(formatZahl(w.verlauf_count || 0));

    if (w.herkunft_referenzen) {
      const pct = Math.round((Number(w.herkunft_ratio) || 0) * 100);
      zelle(`${formatZahl(w.herkunft_treffer || 0)}/${formatZahl(w.herkunft_referenzen)} (${pct} %)`);
    } else {
      zelle("—");
    }
    zelle(w.groesse_label || "0 MB");
    tabelle.append(zeile);
  }
  wallets.append(tabelle);
}

function format_dateigroesse_client(bytes) {
  const n = Number(bytes) || 0;
  if (n <= 0) return "0 MB";
  const mb = n / (1024 * 1024);
  // Ab 1000 MB → GB, max. 2 Nachkommastellen; Tausendertrenner per Locale.
  if (mb >= 1000) {
    const gb = n / (1024 * 1024 * 1024);
    return `${gb.toLocaleString(formatLocale(), {
      maximumFractionDigits: 2,
    })} GB`;
  }
  if (mb >= 0.1) {
    return `${mb.toLocaleString(formatLocale(), {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })} MB`;
  }
  if (n >= 1024) {
    const kb = n / 1024;
    return `${kb.toLocaleString(formatLocale(), {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })} KB`;
  }
  return `${n} B`;
}

function zeichneAppEinstellungen() {
  zeichneSteuerEinstellungen();
  zeichneUiLang();
  zeichneUiTheme();
  zeichneAppPasswort();
  zeichneStartSync();
  zeichneStatusMailEinstellungen();
  zeichneMempoolStatus();
  setzeEnvPfad(Zustand.config?.env_path);
}

/**
 * Meldung in der Passwort-Karte (nicht #speicher-meldung — die ist nur unter Wallets).
 */
function appPasswortMeldung(text, art) {
  const kasten = $("#app-passwort-meldung");
  if (!kasten) {
    try { meldung(text, art); } catch (_) { /* ignore */ }
    return;
  }
  kasten.className = `hinweis app-passwort-meldung hinweis-${art || "krit"}`;
  setzeText(kasten, text);
  kasten.hidden = !text;
  if (art === "gut" && text) {
    setTimeout(() => {
      if (kasten.textContent === text) kasten.hidden = true;
    }, 5000);
  }
}

/** Live: ✕ rot bis neu===wiederholung und nicht leer, dann ✓ grün. */
function aktualisiereAppPasswortMatch() {
  const mark = $("#app-passwort-match");
  if (!mark) return;
  const neu = String($("#app-passwort-neu")?.value || "");
  const neu2 = String($("#app-passwort-neu2")?.value || "");
  mark.classList.remove("match-ok", "match-bad", "match-leer");
  if (!neu && !neu2) {
    mark.textContent = "—";
    mark.classList.add("match-leer");
    mark.title = "";
    return;
  }
  if (neu && neu2 && neu === neu2) {
    mark.textContent = "✓";
    mark.classList.add("match-ok");
    mark.title = t("settings.password.matchOk");
    return;
  }
  mark.textContent = "✕";
  mark.classList.add("match-bad");
  mark.title = t("settings.password.matchBad");
}

/** Einstellungen · optionales App-Passwort + .env-Scramble. */
function zeichneAppPasswort() {
  const karte = $("#karte-app-passwort");
  if (!karte) return;
  const gesetzt = Boolean(Zustand.config?.password_set);
  const aktuell = $("#app-passwort-aktuell");
  const entfernen = $("#app-passwort-entfernen");
  const zusatz = $("#app-passwort-zusatz");
  if (aktuell) {
    aktuell.disabled = !gesetzt;
    if (!gesetzt) aktuell.value = "";
    aktuell.placeholder = gesetzt ? "" : t("settings.password.currentPh");
  }
  if (entfernen) entfernen.disabled = !gesetzt;
  if (zusatz) {
    zusatz.textContent = gesetzt
      ? t("settings.password.zusatzOn")
      : t("settings.password.zusatzOff");
    zusatz.setAttribute(
      "data-i18n",
      gesetzt ? "settings.password.zusatzOn" : "settings.password.zusatzOff",
    );
  }
  aktualisiereAppPasswortMatch();
  bindeAppPasswortUi();
}

function _appPasswortFelderLeeren({ auchAktuell = true } = {}) {
  if (auchAktuell) {
    const a = $("#app-passwort-aktuell");
    if (a) a.value = "";
  }
  const n = $("#app-passwort-neu");
  const n2 = $("#app-passwort-neu2");
  if (n) n.value = "";
  if (n2) n2.value = "";
  aktualisiereAppPasswortMatch();
}

async function speichereAppPasswort() {
  const neu = String($("#app-passwort-neu")?.value || "");
  const neu2 = String($("#app-passwort-neu2")?.value || "");
  const aktuell = String($("#app-passwort-aktuell")?.value || "");
  const gesetzt = Boolean(Zustand.config?.password_set);
  aktualisiereAppPasswortMatch();
  if (!neu) {
    appPasswortMeldung(t("settings.password.emptyNew"), "krit");
    return;
  }
  if (neu !== neu2) {
    appPasswortMeldung(t("settings.password.mismatch"), "krit");
    return;
  }
  if (gesetzt && !aktuell) {
    appPasswortMeldung(t("settings.password.needCurrent"), "krit");
    return;
  }
  const knopf = $("#app-passwort-setzen");
  if (knopf) knopf.disabled = true;
  appPasswortMeldung(t("settings.password.saving"), "warn");
  try {
    const ergebnis = await api("/config/app-password", {
      methode: "PUT",
      daten: {
        current_password: aktuell,
        new_password: neu,
        confirm: neu2,
      },
    });
    if (!Zustand.config) Zustand.config = {};
    Zustand.config.password_set = true;
    if (ergebnis && ergebnis.env_scramble) {
      Zustand.config.env_scramble = ergebnis.env_scramble;
    }
    _appPasswortFelderLeeren();
    zeichneAppPasswort();
    appPasswortMeldung(t("settings.password.saved"), "gut");
    try {
      await ladeConfig();
    } catch (e) {
      appPasswortMeldung(
        t("settings.password.saved") + " (" + ((e && e.message) || e) + ")",
        "warn",
      );
    }
    zeichneAppPasswort();
  } catch (fehler) {
    appPasswortMeldung(
      t("settings.password.saveFailed", {
        msg: (fehler && fehler.message) || String(fehler),
      }),
      "krit",
    );
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

async function entferneAppPasswort() {
  const aktuellFeld = $("#app-passwort-aktuell");
  const aktuell = String(aktuellFeld?.value || "");
  if (!Boolean(Zustand.config?.password_set)) {
    appPasswortMeldung(t("settings.password.zusatzOff"), "warn");
    return;
  }
  if (!aktuell) {
    appPasswortMeldung(t("settings.password.needCurrent"), "krit");
    if (aktuellFeld) {
      aktuellFeld.disabled = false;
      aktuellFeld.focus();
    }
    return;
  }
  const knopf = $("#app-passwort-entfernen");
  if (knopf) knopf.disabled = true;
  appPasswortMeldung(t("settings.password.removing"), "warn");
  try {
    // POST statt DELETE+Body — Firefox/manche Stacks brechen DELETE mit Body ab
    // („NetworkError when attempting to fetch resource“).
    const ergebnis = await api("/config/app-password", {
      methode: "POST",
      daten: { action: "delete", current_password: aktuell },
    });
    if (!Zustand.config) Zustand.config = {};
    Zustand.config.password_set = Boolean(ergebnis.password_set);
    if (ergebnis.env_scramble) {
      Zustand.config.env_scramble = ergebnis.env_scramble;
    }
    _appPasswortFelderLeeren();
    zeichneAppPasswort();
    appPasswortMeldung(t("settings.password.removed"), "gut");
    try { await ladeConfig(); } catch (_) { /* ignore */ }
    zeichneAppPasswort();
  } catch (fehler) {
    appPasswortMeldung(
      t("settings.password.removeFailed", {
        msg: (fehler && fehler.message) || String(fehler),
      }),
      "krit",
    );
  } finally {
    zeichneAppPasswort();
  }
}

function bindeAppPasswortUi() {
  const karte = $("#karte-app-passwort");
  if (!karte || karte.dataset.passBound === "1") return;
  karte.dataset.passBound = "1";
  karte.addEventListener("click", (e) => {
    const el = e.target instanceof Element ? e.target : null;
    if (!el) return;
    if (el.closest("#app-passwort-setzen")) {
      e.preventDefault();
      speichereAppPasswort();
    } else if (el.closest("#app-passwort-entfernen")) {
      e.preventDefault();
      entferneAppPasswort();
    }
  });
  karte.addEventListener("input", (e) => {
    const el = e.target instanceof Element ? e.target : null;
    if (!el) return;
    if (el.id === "app-passwort-neu" || el.id === "app-passwort-neu2") {
      aktualisiereAppPasswortMatch();
    }
  });
  karte.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const el = e.target instanceof Element ? e.target : null;
    if (!el) return;
    if (
      el.id === "app-passwort-neu"
      || el.id === "app-passwort-neu2"
      || el.id === "app-passwort-aktuell"
    ) {
      e.preventDefault();
      speichereAppPasswort();
    }
  });
}

// Global für onclick-Fallback / Konsole.
try {
  window.speichereAppPasswort = speichereAppPasswort;
  window.entferneAppPasswort = entferneAppPasswort;
} catch (_) { /* ignore */ }

/** Nach Server-Neustart: gobbledigook entsperren. */
async function unlockEnvScramble(password) {
  const ergebnis = await api("/config/unlock-env", {
    methode: "POST",
    daten: { password: String(password || "") },
  });
  if (Zustand.config && ergebnis.env_scramble) {
    Zustand.config.env_scramble = ergebnis.env_scramble;
  }
  await ladeConfig();
  return ergebnis;
}

function ggfEnvScrambleUnlockDialog() {
  const st = Zustand.config?.env_scramble;
  if (!st || !st.locked || !st.active) return;
  const pw = window.prompt(
    t("settings.password.unlockPrompt") !== "settings.password.unlockPrompt"
      ? t("settings.password.unlockPrompt")
      : t("ui.hard.f9683fc0c6"),
  );
  if (pw == null || pw === "") return;
  unlockEnvScramble(pw).then(() => {
    meldung(
      t("settings.password.unlocked") !== "settings.password.unlocked"
        ? t("settings.password.unlocked")
        : "Konfiguration entsperrt.",
      "gut",
    );
  }).catch((fehler) => {
    meldung(
      (fehler && fehler.message) || String(fehler),
      "krit",
    );
  });
}

function zeichneLocalCoreHinweis() {
  const kasten = $("#local-core-hinweis");
  const text = $("#local-core-hinweis-text");
  const knopf = $("#local-core-uebernehmen");
  if (!kasten || !text) return;
  const stand = Zustand.config?.local_core;
  const zeigen = Boolean(stand?.needs_opt_in && stand?.hit);
  kasten.hidden = !zeigen;
  if (!zeigen) return;
  const hit = stand.hit;
  const art = hit.pruned ? t("ui.hard.fa3712d804") : t("ui.hard.4a3387f537");
  const p2p = hit.p2p_port || 8333;
  const p2pHinweis = hit.p2p_tcp_open === false
    ? " " + t("ui.hard.b29012adb2", { p2p })
    : " " + t("ui.hard.6d107a5813", { host: hit.host, p2p });
  text.textContent = t("ui.hard.fc5fef80c2", {
    host: hit.host,
    port: hit.port,
    chain: hit.chain || hit.network,
    art,
    blocks: Number(hit.blocks || 0).toLocaleString(formatLocale()),
    p2pHinweis,
  });
  if (knopf && !knopf.dataset.bound) {
    knopf.dataset.bound = "1";
    knopf.addEventListener("click", async () => {
      knopf.disabled = true;
      try {
        const antwort = await api("/source/local-core", { method: "POST", body: {} });
        if (antwort?.sources) {
          Zustand.config = {
            ...(Zustand.config || {}),
            sources: antwort.sources,
            local_core: antwort.local_core,
          };
        } else {
          await ladeConfig();
        }
        setzeQuellenPending(["own_core", "own_utxo_core"]);
        zeichneDatenquellenAnsicht();
        logZeile("Lokaler Bitcoin Core übernommen.");
        try {
          await testeEigenenNode($("#quelle-pruefen"));
        } catch (_) {
          /* Pille bleibt grau/rot bis zum nächsten Check */
        }
      } catch (fehler) {
        logZeile(String(fehler?.message || fehler), "krit");
      } finally {
        knopf.disabled = false;
      }
    });
  }
}

function zeichneDatenquellenAnsicht() {
  zeichneLocalCoreHinweis();
  zeichneQuellen(Zustand.config?.sources || []);
  zeichneMempoolStatus();
  ladeKursHistorie();
  ladeBoersenReports();
  ladeLabelStatus();
  ladeListenStatus();
  setzeEnvPfad(Zustand.config?.env_path);
  aktualisiereDatenquellenNav();
}

async function ladeBoersenReports() {
  const kasten = $("#boerse-status");
  const zusatz = $("#boerse-zusatz");
  if (!kasten) return;
  try {
    const stand = await api("/exchange-reports");
    zeichneBoersenReports(stand);
  } catch (fehler) {
    kasten.replaceChildren();
    kasten.append(hinweisZeile(t("common.loadFailed", { msg: fehler.message })));
    if (zusatz) setzeText(zusatz, "");
  }
}

function zeichneBoersenReports(stand) {
  const kasten = $("#boerse-status");
  const zusatz = $("#boerse-zusatz");
  if (!kasten) return;
  kasten.replaceChildren();
  const liste = stand?.exchanges || [];
  const nAdr = Number(stand?.addresses || 0);
  const nTx = Number(stand?.txids || 0);
  if (zusatz) {
    setzeText(
      zusatz,
      liste.length
        ? `${liste.length} · ${formatZahl(nAdr)} Adr. · ${formatZahl(nTx)} Tx`
        : "",
    );
  }
  if (!liste.length) {
    kasten.append(hinweisZeile(t("sources.exchangeNone")));
    return;
  }
  for (const e of liste) {
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    zeile.append(pille("gut", e.name || e.slug || "?"));
    const text = document.createElement("span");
    text.textContent = t("sources.exchangeLine", {
      name: "",
      addresses: formatZahl(e.addresses || 0),
      txids: formatZahl(e.txids || 0),
    }).replace(/^:\s*/, "").replace(/^\s+/, "");
    // exchangeLine starts with {name}: — name already in pill
    text.textContent = `${formatZahl(e.addresses || 0)} Adr. · ${formatZahl(e.txids || 0)} Tx`;
    zeile.append(text);
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "stift papierkorb";
    knopf.textContent = "🗑";
    knopf.title = t("sources.exchangeRemoveTitle");
    knopf.setAttribute("aria-label", t("sources.exchangeRemove"));
    knopf.addEventListener("click", () => verwerfeBoersenReport(e.slug));
    zeile.append(knopf);
    kasten.append(zeile);
  }
  if (liste.length > 1) {
    const alle = document.createElement("button");
    alle.type = "button";
    alle.className = "stift papierkorb";
    alle.textContent = "🗑";
    alle.title = t("sources.exchangeRemoveAll");
    alle.setAttribute("aria-label", t("sources.exchangeRemoveAll"));
    alle.addEventListener("click", () => verwerfeBoersenReport(null, true));
    kasten.append(alle);
  }
}

function starteBoersenCsvImport() {
  const feld = $("#boerse-csv-datei");
  if (feld) feld.click();
}

function liesBoersenCsvDatei(ereignis) {
  const datei = ereignis.target.files && ereignis.target.files[0];
  ereignis.target.value = "";
  if (!datei) return;
  const name = window.prompt(t("sources.exchangePromptName"), "");
  if (name == null) return;
  const boerse = String(name || "").trim();
  if (!boerse) {
    meldung(t("sources.exchangePromptName"), "krit");
    return;
  }
  logZeile(t("ui.hard.9ef8652c95", { name: datei.name, boerse }));
  const leser = new FileReader();
  leser.onload = async () => {
    try {
      const ergebnis = await api("/exchange-reports/import", {
        methode: "POST",
        daten: {
          name: boerse,
          csv: String(leser.result || ""),
          filename: datei.name,
          ersetzen: false,
        },
        timeoutMs: 120_000,
      });
      logZeile(
        t("sources.exchangeImported", {
          name: ergebnis.name || boerse,
          addresses: formatZahl(ergebnis.imported_addresses || 0),
          txids: formatZahl(ergebnis.imported_txids || 0),
          btc: formatZahl(ergebnis.rows_btc || 0),
          total: formatZahl(ergebnis.rows_total || 0),
        }),
        true,
      );
      meldung(
        t("sources.exchangeImported", {
          name: ergebnis.name || boerse,
          addresses: formatZahl(ergebnis.addresses || 0),
          txids: formatZahl(ergebnis.txids || 0),
          btc: formatZahl(ergebnis.rows_btc || 0),
          total: formatZahl(ergebnis.rows_total || 0),
        }),
        "gut",
      );
      await ladeBoersenReports();
    } catch (fehler) {
      logZeile(t("ui.hard.b55a184807", { msg: fehler.message }), true);
      meldung(fehler.message, "krit");
    }
  };
  leser.onerror = () => {
    logZeile(t("ui.hard.d7a4215402"), true);
    meldung(t("common.fileUnreadable"), "krit");
  };
  leser.readAsText(datei);
}

async function verwerfeBoersenReport(slug, alle = false) {
  try {
    const q = alle ? "all=1" : `slug=${encodeURIComponent(slug || "")}`;
    await api(`/exchange-reports?${q}`, { methode: "DELETE" });
    await ladeBoersenReports();
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

function zeichneKursHistorie(stand) {
  const kasten = $("#kurs-historie-status");
  if (!kasten) return;
  kasten.replaceChildren();
  const listen = stand?.histories || [];
  if (!listen.length) {
    kasten.append(hinweisZeile("Keine Kurs-Historie geladen."));
    return;
  }
  for (const h of listen) {
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    if (!h.ok) {
      zeile.append(pille("warn", h.currency || "?"));
      zeile.append(document.createTextNode(
        ` ${h.error || t("sources.rates.noFile")}`,
      ));
    } else {
      zeile.append(pille("gut", h.currency));
      const von = h.from || "?";
      const bis = h.to || "?";
      const tage = Number(h.days || 0).toLocaleString(formatLocale());
      const quelle = h.source === "bundle" ? t("sources.rates.bundled")
        : h.source === "cache" ? t("sources.rates.cache")
          : (h.source || "?");
      zeile.append(document.createTextNode(
        ` ${t("sources.rates.line", { days: tage, from: von, to: bis, source: quelle })}`,
      ));
    }
    kasten.append(zeile);
  }
}

async function ladeKursHistorie() {
  try {
    const stand = await api("/price/history");
    Zustand.kursHistorie = stand;
    zeichneKursHistorie(stand);
  } catch (fehler) {
    const kasten = $("#kurs-historie-status");
    if (kasten) {
      kasten.replaceChildren(hinweisZeile(
        /Token fehlt|token missing/i.test(fehler.message || "")
          ? t("history.priceTokenMissing")
          : `${t("sources.rates")}: ${übersetzeServerMeldung(fehler.message)}`,
      ));
    }
  }
}

async function starteKursHistorieSync() {
  logZeile(t("ui.hard.2db4778e8b"));
  try {
    const stand = await api("/price/history/sync", {
      methode: "POST",
      daten: {},
    });
    for (const zeile of stand.log || []) logZeile(zeile);
    Zustand.kursHistorie = {
      histories: stand.histories || [],
      price_history_opt_in: true,
    };
    zeichneKursHistorie(Zustand.kursHistorie);
    // Spot/Serie neu — frische Tage sollen Umrechnung und Kopfzeile sehen.
    Zustand.kursSerie = null;
    Zustand.kursWarnGeloggt = false;
    try {
      await Promise.all([ladeSpotkurs({ laut: false }), ladeKursSerie()]);
    } catch (_e) { /* Spot loggt selbst */ }
    meldung(
      stand.ok ? t("sources.ratesSyncDone") : t("sources.ratesSyncPartial"),
      stand.ok ? "gut" : "warn",
    );
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

let _kursImportWaehrung = "EUR";

function starteKursImport(waehrung) {
  _kursImportWaehrung = waehrung;
  const feld = $("#kurs-csv-datei");
  if (feld) feld.click();
}

function liesKursCsvDatei(ereignis) {
  const datei = ereignis.target.files && ereignis.target.files[0];
  ereignis.target.value = "";
  if (!datei) return;
  const waehrung = _kursImportWaehrung || "EUR";
  logZeile(t("ui.hard.86d64de416", { ccy: waehrung, name: datei.name }));
  const leser = new FileReader();
  leser.onload = async () => {
    try {
      const ergebnis = await api("/price/import", {
        methode: "POST",
        daten: {
          currency: waehrung,
          csv: String(leser.result || ""),
          filename: datei.name,
          ersetzen: false,
        },
      });
      const tage = Number(ergebnis.days || 0).toLocaleString(formatLocale());
      const neu = Number(ergebnis.imported || 0).toLocaleString(formatLocale());
      logZeile(
        `Kurs-CSV ${waehrung}: ${neu} Zeilen gelesen, ${tage} Tage im Cache`
        + (ergebnis.from && ergebnis.to
          ? ` (${ergebnis.from} – ${ergebnis.to}).`
          : "."),
        true,
      );
      meldung(t("ui.hard.ad9ac58e28", { ccy: waehrung }), "gut");
      Zustand.kursSerie = null;
      await Promise.all([ladeKursHistorie(), ladeKursSerie()]);
    } catch (fehler) {
      logZeile(t("ui.hard.0e8ba65bab", { msg: fehler.message }), true);
      meldung(fehler.message, "krit");
    }
  };
  leser.onerror = () => {
    logZeile(t("ui.hard.35e1e02ff2"), true);
    meldung(t("common.fileUnreadable"), "krit");
  };
  leser.readAsText(datei);
}

function oeffneVerwaltung(ansicht) {
  if ((ansicht === "wallets" && walletsManaged()) || (ansicht === "datenquellen" && sourcesFullyManaged())) {
    zeigeAnsicht("einstellungen");
    zeichneAppEinstellungen();
    return;
  }
  zeigeAnsicht(ansicht);
  if (ansicht === "wallets") zeichneWalletVerwaltung();
  else if (ansicht === "einstellungen") zeichneAppEinstellungen();
  else if (ansicht === "datenquellen") zeichneDatenquellenAnsicht();
}

/**
 * Neustart ohne Wallets: erst Indexer, P2P „eh da“ und mitgelieferte
 * electrum_servers.json zählen nicht als konfigurierte Datenquelle.
 */
function brauchtDatenquellenZuerst() {
  const wallets = Zustand.config?.wallets || [];
  if (wallets.length > 0) return false;
  if (walletsManaged() || sourcesFullyManaged()) return false;
  const quellen = Zustand.config?.sources || [];
  // Nur vom Nutzer gesetzte eigene Nodes — nicht Bundle-Clearnet, nicht P2P.
  const eigenerIndexer = quellen.some(
    (q) => q
      && q.configured
      && (
        q.key === "own_fulcrum"
        || q.key === "own_core"
        || q.key === "own_utxo_core"
      ),
  );
  // Öffentliche Onions nur, wenn der Nutzer welche eingetragen/geladen hat.
  const onion = quellen.some(
    (q) => q && q.key === "public_onion" && q.configured,
  );
  return !eigenerIndexer && !onion;
}

function aktualisiereSpeicherleiste() {
  // Früher: sticky „Speichern/Verwerfen“. Jetzt speichert jede Aktion
  // sofort; pro Zeile steuert „Aktualisieren“, ob Name/Optionen offen sind.
  const zeilen = document.querySelectorAll("#wallet-liste .wallet-zeile");
  Zustand.entwurf.forEach((wallet, index) => {
    const zeile = zeilen[index];
    if (zeile) setzeZeileAktualisieren(zeile, wallet);
  });
}

/**
 * Hoch-private Quelle verdrängt mäßig/gering (Auto-Vorrang), solange sie
 * nicht nachweislich unerreichbar ist.
 */
function quelleHochVerdraengt(quellen) {
  return (quellen || []).some(
    (q) => q && q.privacy === "hoch" && q.configured && q.reachable !== false,
  );
}

/**
 * Farbe der Erläuterungsnotiz unter einer Datenquelle.
 * - grün: konfiguriert und Privatsphäre hoch
 * - grau: nicht konfiguriert; Liste geladen aber unverbunden; oder mäßig/gering
 *   und von einer Hoch-Privatsphäre-Quelle verdrängt
 * - gelb: mäßig/gering mit bestehender und genutzter Verbindung
 */
function quelleNotizKlasse(quelle, quellen) {
  if (!quelle.configured) return "quelle-notiz notiz-inaktiv";
  if (quelle.privacy === "hoch") return "quelle-notiz notiz-hoch";
  // Nur gelb bei echter, genutzter Verbindung — geladene Liste allein bleibt grau.
  if (quelle.reachable !== true || quelleHochVerdraengt(quellen)) {
    return "quelle-notiz notiz-inaktiv";
  }
  return "quelle-notiz";
}

/**
 * Privatsphäre-Pille: mäßig/gering erst bei genutzter Verbindung färben.
 */
function quellePrivacyStufe(quelle, quellen) {
  if (!quelle.configured) return "neutral";
  if (quelle.privacy === "hoch") return "gut";
  if (quelle.reachable !== true || quelleHochVerdraengt(quellen)) {
    return "neutral";
  }
  return ({ "mäßig": "warn", gering: "krit" }[quelle.privacy] || "neutral");
}

/**
 * Gelbe „Verbindung im Aufbau…“-Pille nur während eines echten Checks
 * für Quellen, die der Check gerade anfasst — nicht bei idle reachable=null
 * und nicht bei öffentlich, wenn P2P/Eigen Vorrang hat oder Opt-in aus ist.
 */
function quelleZeigtVerbindungsaufbau(quelle, quellen) {
  if (!quelle || !quelle.configured) return false;
  if (!Zustand.peerCheckLaeuft) return false;
  if (quelle.reachable === true || quelle.reachable === false) return false;
  if (quelle.key === "public_onion" || quelle.key === "clearnet") {
    if (!Zustand.config?.oeffentliche_electrum) return false;
    if (quelleHochVerdraengt(quellen)) return false;
  }
  return true;
}

function zeichneQuellen(quellen) {
  const behaelter = $("#quellen-liste");
  if (!behaelter) return;
  behaelter.replaceChildren();
  const liste = quellen || [];

  for (const quelle of liste) {
    const bridgeManaged = start9BridgeManaged(quelle);
    const block = document.createElement("div");
    const zeile = document.createElement("div");
    zeile.className = "quelle-zeile";
    if (!quelle.configured) zeile.classList.add("nicht-konfiguriert");

    const rang = document.createElement("span");
    rang.className = "quelle-rang";
    rang.textContent = quelle.rank;

    const name = document.createElement("span");
    name.className = "quelle-name";
    const anzeigename = quelleName(quelle);
    name.textContent = anzeigename;

    const detail = document.createElement("span");
    detail.className = "quelle-detail";
    detail.textContent = quelleDetail(quelle);

    const rechts = document.createElement("span");
    rechts.className = "quelle-rechts";

    if (quelle.configured && quelle.reachable === true) {
      rechts.append(pille("gut", t("sources.reachable")));
    } else if (quelle.configured && quelle.reachable === false) {
      rechts.append(pille("krit", t("sources.unreachable")));
    } else if (quelleZeigtVerbindungsaufbau(quelle, liste)) {
      rechts.append(pille("warn", t("sources.connecting")));
    }
    // Sonst keine Status-Pille: Liste geladen, aber gerade nicht genutzt
    // (z. B. öffentlich nach „P2P / kappen“) → grau über Notiz/Privatsphäre.
    rechts.append(pille(quellePrivacyStufe(quelle, liste), privacyLabel(quelle.privacy)));

    const formular = document.createElement("div");
    formular.className = "quelle-formular";
    formular.hidden = true;

    if (quelle.editierbar) {
      const stift = document.createElement("button");
      stift.type = "button";
      stift.className = "stift";
      stift.textContent = "✎";
      stift.title = bridgeManaged
        ? t("sources.start9BridgeHint")
        : t("sources.editTitle", { name: anzeigename });
      stift.disabled = bridgeManaged;
      stift.setAttribute("aria-expanded", "false");
      stift.addEventListener("click", () => {
        const auf = formular.hidden;
        if (auf && formular.childElementCount === 0) {
          formular.append(quellenFormular(quelle, formular));
        }
        formular.hidden = !auf;
        stift.setAttribute("aria-expanded", String(auf));
      });
      rechts.append(stift);
    }

    // Papierkorb für eigene Nodes hier; P2P erst hinter „Verbinden“
    // (gleiche Reihenfolge wie Electrum: Aktion, dann 🗑).
    if (quelle.verwerfbar && quelle.key !== "bip158") {
      const korb = document.createElement("button");
      korb.type = "button";
      korb.className = "stift papierkorb";
      korb.textContent = "🗑";
      korb.title = bridgeManaged
        ? t("sources.start9BridgeHint")
        : t("sources.discardTitle", { name: anzeigename });
      korb.disabled = bridgeManaged;
      korb.addEventListener("click", () => verwerfeQuelle(quelle));
      rechts.append(korb);
    }

    if (quelle.laden_url && quelle.laden_filter) {
      const laden = document.createElement("button");
      laden.type = "button";
      laden.className = "knopf knopf-klein";
      laden.textContent = t("sources.connect");
      laden.title = t("sources.loadElectrumTitle", { url: quelle.laden_url });
      laden.addEventListener("click", () => ladeElectrumServer(quelle, laden));
      rechts.append(laden);
      // Papierkorb hinter dem Verbinden-Knopf: nur die Serverliste, nicht Opt-in.
      if (quelle.configured) {
        const listeKorb = document.createElement("button");
        listeKorb.type = "button";
        listeKorb.className = "stift papierkorb";
        listeKorb.textContent = "🗑";
        listeKorb.title = t("sources.clearListTitle", { name: anzeigename });
        listeKorb.addEventListener("click", () => loescheElectrumListe(quelle));
        rechts.append(listeKorb);
      }
    }

    if (quelle.key === "bip158") {
      const hoehe = document.createElement("input");
      hoehe.type = "number";
      hoehe.className = "quelle-start-hoehe";
      hoehe.min = "0";
      hoehe.step = "1";
      hoehe.inputMode = "numeric";
      hoehe.placeholder = t("sources.bip158StartPlaceholder");
      hoehe.title = t("sources.bip158StartTitle");
      hoehe.disabled = bridgeManaged;
      const startWert = quelle.start_height != null
        ? String(quelle.start_height)
        : "";
      hoehe.value = startWert;
      hoehe.dataset.savedValue = startWert;
      hoehe.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          hoehe.blur();
        }
      });
      hoehe.addEventListener("change", () => speichereBip158StartHoehe(hoehe));
      rechts.append(hoehe);

      const verbinden = document.createElement("button");
      verbinden.type = "button";
      verbinden.className = "knopf knopf-klein";
      verbinden.textContent = t("sources.connect");
      verbinden.title = t("sources.connectP2pTitle");
      verbinden.disabled = bridgeManaged;
      verbinden.addEventListener("click", () => verbindeP2p(quelle, verbinden));
      rechts.append(verbinden);
      if (quelle.verwerfbar) {
        const korb = document.createElement("button");
        korb.type = "button";
        korb.className = "stift papierkorb";
        korb.textContent = "🗑";
        korb.title = bridgeManaged
          ? t("sources.start9BridgeHint")
          : t("sources.disableP2pTitle");
        korb.disabled = bridgeManaged;
        korb.addEventListener("click", () => verwerfeQuelle(quelle));
        rechts.append(korb);
      }
    }

    zeile.append(rang, name, detail, rechts);

    const notizText = quelleNotiz(quelle);
    if (notizText) {
      const notiz = document.createElement("span");
      notiz.className = quelleNotizKlasse(quelle, liste);
      notiz.textContent = notizText;
      zeile.append(notiz);
    }
    if (bridgeManaged) {
      const hinweis = document.createElement("span");
      hinweis.className = "quelle-notiz notiz-inaktiv";
      hinweis.textContent = t("sources.start9BridgeHint");
      zeile.append(hinweis);
    }

    block.append(zeile, formular);
    behaelter.append(block);
  }
}

async function verwerfeQuelle(quelle) {
  const ok = window.confirm(
    quelle.key === "bip158"
      ? t("sources.confirmDisableP2p")
      : t("sources.confirmDiscard", { name: quelleName(quelle) }),
  );
  if (!ok) return;
  try {
    const ergebnis = await api(`/config/source/${encodeURIComponent(quelle.key)}`, {
      methode: "DELETE",
    });
    // P2P-Papierkorb bricht Header/Scan-Jobs serverseitig ab — UI mitziehen.
    if (quelle.key === "bip158") {
      const cancelled = Array.isArray(ergebnis.cancelled_jobs)
        ? ergebnis.cancelled_jobs
        : [];
      if (
        Zustand.rescanJob
        && (cancelled.includes(Zustand.rescanJob) || cancelled.length)
      ) {
        beendeRescan(t("sources.p2pJobsCancelled"), false);
      }
      if (cancelled.length) {
        meldung(t("sources.p2pJobsCancelled"), "warn");
      }
      await ladeJobsNav();
    }
    // Zuerst Server-Antwort (P2P-Schalter aus), dann Config — sonst hält
    // uebernehmeQuellenErreichbarkeit kurz den alten „an“-Stand.
    if (Zustand.config && Array.isArray(ergebnis.sources)) {
      Zustand.config.sources = ergebnis.sources;
    }
    await ladeConfig();
    // Nach ladeConfig nochmals DELETE-Stand für bip158 erzwingen, falls Merge
    // reachable/peers aus Altlasten mischt — configured kommt aus .env.
    if (Array.isArray(ergebnis.sources)) {
      const nach = Object.create(null);
      for (const q of ergebnis.sources) {
        if (q && q.key) nach[q.key] = q;
      }
      Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
        const frisch = nach[q.key];
        if (!frisch) return q;
        if (q.key === "bip158" || !frisch.configured) {
          return {
            ...frisch,
            reachable: frisch.configured ? q.reachable : null,
            peer_count: frisch.configured ? (q.peer_count || 0) : 0,
            peer_hosts: frisch.configured ? (q.peer_hosts || []) : [],
          };
        }
        return q;
      });
    }
    zeichneDatenquellenAnsicht();
    zeichneKopfStatus(Zustand.config.sources);
    meldung(
      quelle.key === "bip158"
        ? t("sources.p2pDisabled")
        : t("sources.discarded", { name: quelleName(quelle) }),
      "warn",
    );
    // Node-Check nachziehen (nächste Quelle), P2P nicht wieder „an“ malen.
    pruefeNodeStatus();
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

async function ladeElectrumServer(quelle, knopf) {
  const vorher = knopf.textContent;
  knopf.disabled = true;
  knopf.textContent = t("common.loadingEllipsis");
  try {
    const ergebnis = await api("/config/electrum-servers", {
      methode: "POST",
      daten: { filter: quelle.laden_filter },
    });
    await ladeConfig();
    zeichneQuellen(Zustand.config.sources);
    meldung(übersetzeLogText(ergebnis.message || t("sources.listAdopted")), "gut");
    pruefeNodeStatus();
  } catch (fehler) {
    meldung(fehler.message, "krit");
    knopf.disabled = false;
    knopf.textContent = vorher;
  }
}

/** P2P-Zeile: Start­höhe speichern (kein Stift-Dialog mehr). */
async function speichereBip158StartHoehe(eingabe) {
  if (!eingabe || eingabe.disabled) return;
  const roh = String(eingabe.value || "").trim();
  if (!roh) return;
  const n = Number(roh);
  if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
    meldung(t("sources.bip158StartInvalid"), "krit");
    return;
  }
  const vorher = eingabe.dataset.savedValue;
  if (vorher != null && vorher === String(n)) return;
  eingabe.disabled = true;
  try {
    const ergebnis = await api("/config/source", {
      methode: "PUT",
      daten: {
        source: "bip158",
        values: { BIP158_START_HEIGHT: String(n) },
      },
    });
    await ladeConfig();
    if (Array.isArray(ergebnis.sources) && Zustand.config) {
      Zustand.config.sources = ergebnis.sources;
    }
    eingabe.dataset.savedValue = String(n);
    zeichneQuellen(Zustand.config?.sources || ergebnis.sources || []);
    meldung(t("sources.bip158StartSaved", { n }), "gut");
  } catch (fehler) {
    meldung(fehler.message, "krit");
    eingabe.disabled = false;
  }
}

/** P2P-Zeile: „Verbinden“ schaltet Compact Filter ein (früher Checkbox). */
async function verbindeP2p(quelle, knopf) {
  const vorher = knopf.textContent;
  knopf.disabled = true;
  knopf.textContent = t("common.loadingEllipsis");
  const hatteOeffentlich = oeffentlicheElectrumNochAktiv();
  try {
    const ergebnis = await api("/config/source", {
      methode: "PUT",
      daten: { source: "bip158", values: { BIP158_P2P: "true" } },
    });
    await ladeConfig();
    const pending = Array.isArray(ergebnis.pending_sources)
      && ergebnis.pending_sources.length
      ? ergebnis.pending_sources
      : quellenPendingKeysNachSave("bip158");
    setzeQuellenPending(pending);
    zeichneQuellen(Zustand.config?.sources || ergebnis.sources || []);
    meldung(t("sources.appliedTesting"), "warn");
    try {
      const stand = await testeEigenenNode($("#quelle-pruefen"));
      meldung(
        t("sources.appliedResult", { stand: stand.label }),
        stand.gut ? "gut" : "krit",
      );
      if (hatteOeffentlich && p2pQuelleVerbunden()) {
        await frageP2pPrivatsphaereKappen();
      }
    } catch (testFehler) {
      meldung(t("sources.appliedTestFailed", { msg: testFehler.message }), "krit");
    }
  } catch (fehler) {
    meldung(fehler.message, "krit");
    knopf.disabled = false;
    knopf.textContent = vorher;
  }
}

async function loescheElectrumListe(quelle) {
  const ok = window.confirm(
    t("sources.confirmClearList", { name: quelleName(quelle) }),
  );
  if (!ok) return;
  try {
    const ergebnis = await api(`/config/source/${encodeURIComponent(quelle.key)}`, {
      methode: "DELETE",
    });
    await ladeConfig();
    zeichneQuellen(ergebnis.sources || Zustand.config.sources);
    meldung(t("sources.listCleared", { name: quelleName(quelle) }), "warn");
    pruefeNodeStatus();
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

/** Baut das Bearbeitungsformular einer Datenquelle. */
function quellenFormular(quelle, behaelter) {
  const form = document.createElement("div");
  const bridgeManaged = start9BridgeManaged(quelle);
  const eingaben = new Map();

  for (const feld of quelle.felder) {
    const zeile = document.createElement("label");
    zeile.className = "feld-zeile";

    const titel = document.createElement("span");
    titel.className = "feld-titel";
    titel.textContent = quelleFeldLabel(feld, quelle.key);
    zeile.append(titel);

    let eingabe;
    if (feld.typ === "checkbox") {
      eingabe = document.createElement("input");
      eingabe.type = "checkbox";
      eingabe.checked = feld.value === "true";
      eingabe.className = "feld-checkbox";
    } else if (feld.typ === "schalter") {
      eingabe = document.createElement("select");
      for (const [wert, text] of [["true", t("common.yes")], ["false", t("common.no")]]) {
        const option = document.createElement("option");
        option.value = wert;
        option.textContent = text;
        eingabe.append(option);
      }
      eingabe.value = feld.value === "true" ? "true" : "false";
    } else if (feld.typ === "liste") {
      eingabe = document.createElement("textarea");
      eingabe.rows = 4;
      eingabe.className = "mono";
      eingabe.value = feld.value;
    } else {
      eingabe = document.createElement("input");
      eingabe.type = feld.typ === "geheim" ? "password" : "text";
      eingabe.className = "mono";
      eingabe.value = feld.value;
      eingabe.autocomplete = "off";
      if (feld.typ === "geheim") {
        eingabe.placeholder = feld.gesetzt ? t("common.passwordKept") : "";
      }
    }
    eingabe.dataset.key = feld.key;
    if (bridgeManaged) eingabe.disabled = true;
    eingaben.set(feld.key, eingabe);
    zeile.append(eingabe);

    const hinweisText = quelleFeldHinweis(feld, quelle.key);
    if (hinweisText) {
      const hinweis = document.createElement("span");
      hinweis.className = "feld-hinweis";
      hinweis.textContent = hinweisText;
      zeile.append(hinweis);
    }
    form.append(zeile);
  }

  const fuss = document.createElement("div");
  fuss.className = "formular-fuss";

  const meldungsfeld = document.createElement("span");
  meldungsfeld.className = "feld-hinweis";

  const abbrechen = document.createElement("button");
  abbrechen.type = "button";
  abbrechen.className = "knopf knopf-klein";
  abbrechen.textContent = t("common.close");
  abbrechen.addEventListener("click", () => {
    behaelter.hidden = true;
  });

  const speichern = document.createElement("button");
  speichern.type = "button";
  speichern.className = "knopf knopf-klein knopf-primaer";
  speichern.textContent = t("common.apply");
  speichern.disabled = bridgeManaged;
  speichern.addEventListener("click", async () => {
    speichern.disabled = true;
    meldungsfeld.textContent = "";
    const werte = {};
    for (const [key, eingabe] of eingaben) {
      werte[key] = eingabe.type === "checkbox"
        ? (eingabe.checked ? "true" : "false")
        : eingabe.value;
    }
    try {
      const ergebnis = await api("/config/source", {
        methode: "PUT",
        daten: { source: quelle.key, values: werte },
      });
      await ladeConfig();
      // Alte grüne Pille verwerfen: grau bis der neue Connect steht.
      const pending = Array.isArray(ergebnis.pending_sources)
        && ergebnis.pending_sources.length
        ? ergebnis.pending_sources
        : quellenPendingKeysNachSave(quelle.key);
      setzeQuellenPending(pending);
      zeichneQuellen(Zustand.config?.sources || ergebnis.sources || []);
      meldung(t("sources.appliedTesting"), "warn");
      try {
        // jubel:true — Staub nach jedem erfolgreichen Indexer-Übernehmen.
        const stand = await testeEigenenNode($("#quelle-pruefen"), { jubel: true });
        meldung(
          t("sources.appliedResult", { stand: stand.label }),
          stand.gut
            || standHatHochPrivateVerbindung(stand, Zustand.config?.sources)
            ? "gut"
            : "krit",
        );
      } catch (testFehler) {
        meldung(t("sources.appliedTestFailed", { msg: testFehler.message }), "krit");
      }
    } catch (fehler) {
      meldungsfeld.textContent = fehler.message;
      speichern.disabled = false;
    }
  });

  fuss.append(meldungsfeld, abbrechen, speichern);
  form.append(fuss);
  return form;
}

async function ladeListenStatus() {
  const kasten = $("#listen-status");
  try {
    const status = await api("/sanctions");
    kasten.replaceChildren();

    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    if (!status.vorhanden) {
      zeile.append(pille("warn", t("sanctions.noLists")));
      const text = document.createElement("span");
      text.textContent = t("sanctions.noListsHint");
      zeile.append(text);
      setzeText($("#listen-zusatz"), "");
    } else {
      zeile.append(pille("gut", t("common.loaded")));
      const text = document.createElement("span");
      text.textContent = t("sanctions.counts", {
        addresses: status.adressen.toLocaleString(formatLocale()),
        entities: status.entitaeten.toLocaleString(formatLocale()),
      });
      zeile.append(text);
      setzeText(
        $("#listen-zusatz"),
        status.stand ? t("sanctions.asOf", { when: formatZeitpunkt(status.stand) }) : ""
      );
    }

    const vorbehalt = document.createElement("span");
    vorbehalt.className = "vorbehalt";
    // Backend liefert DE-Hinweise; UI-Keys decken die bekannten ab.
    const hinweise = (status.hinweise || []).map((h) => {
      if (/Zahl je Quelle|count per source/i.test(h)) return t("sanctions.hintMultiList");
      if (/Fehler und veralten|errors and go stale/i.test(h)) return t("sanctions.hintFallible");
      return h;
    });
    vorbehalt.textContent = hinweise.join(" ");
    zeile.append(vorbehalt);
    kasten.append(zeile);

    if (status.quellen && status.quellen.length > 0) {
      const liste = document.createElement("div");
      liste.className = "quellen-liste";
      for (const quelle of status.quellen) {
        const eintrag = document.createElement("div");
        eintrag.className = "quelle-eintrag";
        const name = document.createElement("span");
        name.textContent = quelle.name;
        const anzahl = document.createElement("span");
        anzahl.textContent = quelle.adressen.toLocaleString(formatLocale());
        eintrag.append(name, anzahl);
        liste.append(eintrag);
      }
      kasten.append(liste);
    }
  } catch (fehler) {
    kasten.replaceChildren();
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    zeile.textContent = t("sanctions.statusUnavailable", { msg: fehler.message });
    kasten.append(zeile);
  }
}

async function aktualisiereListen() {
  const knopf = $("#listen-update");
  knopf.disabled = true;
  const imp = $("#listen-import");
  if (imp) imp.disabled = true;
  $("#listen-lauf").hidden = false;
  const abbruchKnopf = $("#listen-abbruch");
  if (abbruchKnopf) {
    abbruchKnopf.hidden = false;
    abbruchKnopf.disabled = false;
  }
  setzeText($("#listen-text"), t("common.downloadStarting"));

  const fertig = (meldung) => {
    clearInterval(timer);
    knopf.disabled = false;
    if (imp) imp.disabled = false;
    $("#listen-lauf").hidden = true;
    if (abbruchKnopf) abbruchKnopf.hidden = true;
    if (meldung) meldungListen(meldung);
    ladeListenStatus();
  };

  let jobId = null;
  let timer = null;
  if (abbruchKnopf) {
    abbruchKnopf.onclick = async () => {
      abbruchKnopf.disabled = true;
      setzeText($("#listen-text"), t("common.abortRequested"));
      if (jobId) {
        try {
          await api(`/jobs/${jobId}`, { methode: "DELETE" });
        } catch (_) {
          /* schon beendet */
        }
      }
    };
  }
  try {
    const job = await api("/sanctions/update", { methode: "POST", daten: {} });
    jobId = job.id;
  } catch (fehler) {
    fertig(`Aktualisierung fehlgeschlagen: ${fehler.message}`);
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      setzeText($("#listen-text"), übersetzeLogText(job.message || t("common.runningEllipsis")));
      if (job.running) return;
      if (job.status === "cancelled") {
        fertig(t("common.cancelled"));
        return;
      }
      fertig(job.status === "done" ? "" : (übersetzeServerMeldung(job.error) || t("common.failed")));
    } catch (fehler) {
      fertig(fehler.message);
    }
  }, 1200);
}

// ---------------------------------------------------------------------------
// Adress-Labels
// ---------------------------------------------------------------------------

async function ladeLabelStatus() {
  const kasten = $("#label-status");
  let status;
  try {
    status = await api("/labels");
  } catch (fehler) {
    setzeText(
      kasten,
      /Token fehlt|token missing/i.test(fehler.message || "")
        ? t("state.unreadableToken")
        : t("common.errorPrefix", { msg: übersetzeServerMeldung(fehler.message) }),
    );
    return;
  }
  Zustand.labels = status;

  const auswahl = $("#label-variante");
  if (!auswahl.options.length) {
    for (const variante of status.varianten || []) {
      const option = document.createElement("option");
      option.value = variante.wert;
      const key = `labels.variant.${variante.wert}`;
      const uebersetzt = t(key);
      option.textContent = uebersetzt !== key ? uebersetzt : variante.label;
      auswahl.append(option);
    }
  }
  if (status.variante) auswahl.value = status.variante;
  $("#label-verwerfen").hidden = !status.vorhanden;

  kasten.replaceChildren();
  const zeile = document.createElement("div");
  zeile.className = "sanktions-zeile";

  if (!status.vorhanden) {
    zeile.append(pille("warn", t("labels.notLoaded")));
    const text = document.createElement("span");
    text.textContent = t("labels.emptyHint");
    zeile.append(text);
    setzeText($("#label-zusatz"), "");
  } else {
    zeile.append(pille("gut", t("common.loaded")));
    const text = document.createElement("span");
    text.textContent = t("labels.counts", {
      addresses: status.adressen.toLocaleString(formatLocale()),
      named: status.benannt.toLocaleString(formatLocale()),
      entities: status.entitaeten.toLocaleString(formatLocale()),
    });
    zeile.append(text);
    // Bewusst „Datei vom": Das ist das Datum des Downloads, nicht das der
    // Daten darin. Die stammen von 2018 — das sagt der Vorbehalt darunter.
    const datei = (status.stand || "").split("-").reverse().join(".");
    setzeText($("#label-zusatz"), datei ? t("labels.fileFrom", { date: datei }) : "");
  }
  kasten.append(zeile);

  // Der Datenstand ist die wichtigste Einschränkung — er gehört sichtbar
  // neben den Bestand, nicht in eine Fußnote.
  const vorbehalt = document.createElement("p");
  vorbehalt.className = "vorbehalt";
  vorbehalt.textContent = t("labels.dataHint");
  kasten.append(vorbehalt);

  const herkunft = document.createElement("p");
  herkunft.className = "meta";
  herkunft.textContent = t("labels.sourceLine", { quelle: status.quelle, url: status.quelle_url });
  kasten.append(herkunft);
}

/** Datei → Base64 (große Binärdateien, Chunk-weise). */
function dateiAlsBase64(datei) {
  return new Promise((resolve, reject) => {
    const leser = new FileReader();
    leser.onload = () => {
      try {
        const bytes = new Uint8Array(leser.result);
        const stuecke = [];
        const schritt = 0x8000;
        for (let i = 0; i < bytes.length; i += schritt) {
          stuecke.push(
            String.fromCharCode.apply(null, bytes.subarray(i, i + schritt)),
          );
        }
        resolve(btoa(stuecke.join("")));
      } catch (fehler) {
        reject(fehler);
      }
    };
    leser.onerror = () => reject(new Error(t("common.fileUnreadable")));
    leser.readAsArrayBuffer(datei);
  });
}

async function dateienAlsImportPayload(dateiListe) {
  const files = [];
  for (const datei of dateiListe) {
    files.push({
      name: datei.name,
      data_b64: await dateiAlsBase64(datei),
    });
  }
  return { files };
}

function starteLabelImport() {
  const feld = $("#label-dateien");
  if (feld) feld.click();
}

function starteListenImport() {
  const feld = $("#listen-dateien");
  if (feld) feld.click();
}

async function liesLabelImportDateien(ereignis) {
  const liste = ereignis.target.files ? [...ereignis.target.files] : [];
  ereignis.target.value = "";
  if (!liste.length) return;
  const knopf = $("#label-import");
  const laden = $("#label-laden");
  if (knopf) knopf.disabled = true;
  if (laden) laden.disabled = true;
  $("#label-lauf").hidden = false;
  setzeText($("#label-text"), t("sources.labelsImporting"));
  try {
    const payload = await dateienAlsImportPayload(liste);
    payload.variante = $("#label-variante")?.value || undefined;
    const stand = await api("/labels/import", {
      methode: "POST",
      daten: payload,
      timeoutMs: 300_000,
    });
    const n = Number(stand.adressen || 0).toLocaleString(formatLocale());
    meldungListen(t("sources.labelsImportDone", { addresses: n }));
    logZeile(`Labels importiert: ${n} Adressen.`, true);
  } catch (fehler) {
    meldungListen(t("common.loadFailed", { msg: fehler.message }));
    logZeile(t("ui.hard.80816bd6d6", { msg: fehler.message }), true);
  } finally {
    if (knopf) knopf.disabled = false;
    if (laden) laden.disabled = false;
    $("#label-lauf").hidden = true;
    ladeLabelStatus();
  }
}

async function liesListenImportDateien(ereignis) {
  const liste = ereignis.target.files ? [...ereignis.target.files] : [];
  ereignis.target.value = "";
  if (!liste.length) return;
  const knopf = $("#listen-import");
  const update = $("#listen-update");
  if (knopf) knopf.disabled = true;
  if (update) update.disabled = true;
  $("#listen-lauf").hidden = false;
  setzeText($("#listen-text"), t("sources.listsImporting"));
  try {
    const payload = await dateienAlsImportPayload(liste);
    const ergebnis = await api("/sanctions/import", {
      methode: "POST",
      daten: payload,
      timeoutMs: 300_000,
    });
    const n = Number(ergebnis.adressen || 0).toLocaleString(formatLocale());
    meldungListen(t("sources.listsImportDone", { addresses: n }));
    logZeile(`Sanktionslisten importiert: ${n} Adressen.`, true);
  } catch (fehler) {
    meldungListen(t("common.loadFailed", { msg: fehler.message }));
    logZeile(t("ui.hard.18e555dc2b", { msg: fehler.message }), true);
  } finally {
    if (knopf) knopf.disabled = false;
    if (update) update.disabled = false;
    $("#listen-lauf").hidden = true;
    ladeListenStatus();
  }
}

async function ladeLabels() {
  const knopf = $("#label-laden");
  knopf.disabled = true;
  const imp = $("#label-import");
  if (imp) imp.disabled = true;
  $("#label-lauf").hidden = false;
  const abbruchKnopf = $("#label-abbruch");
  if (abbruchKnopf) {
    abbruchKnopf.hidden = false;
    abbruchKnopf.disabled = false;
  }
  setzeText($("#label-text"), t("common.downloadStarting"));
  const fertig = (meldung) => {
    clearInterval(timer);
    knopf.disabled = false;
    if (imp) imp.disabled = false;
    $("#label-lauf").hidden = true;
    if (abbruchKnopf) abbruchKnopf.hidden = true;
    if (meldung) meldungListen(meldung);
    ladeLabelStatus();
  };

  let jobId = null;
  let timer = null;
  if (abbruchKnopf) {
    abbruchKnopf.onclick = async () => {
      abbruchKnopf.disabled = true;
      setzeText($("#label-text"), t("common.abortRequested"));
      if (jobId) {
        try {
          await api(`/jobs/${jobId}`, { methode: "DELETE" });
        } catch (_) {
          /* schon beendet */
        }
      }
    };
  }
  try {
    const job = await api("/labels", {
      methode: "POST",
      daten: { variante: $("#label-variante").value },
    });
    jobId = job.id;
  } catch (fehler) {
    fertig(t("common.loadFailed", { msg: fehler.message }));
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      setzeText($("#label-text"), übersetzeLogText(job.message || t("common.runningEllipsis")));
      if (job.running) return;
      if (job.status === "done") {
        fertig("");
        return;
      }
      if (job.status === "cancelled") {
        fertig(t("common.cancelled"));
        return;
      }
      // Fehler sichtbar halten — sonst wirkt es wie „nicht geladen“ ohne Grund
      // (z. B. früher SSL-Zertifikatfehler beim GitHub-Download).
      const detail =
        übersetzeServerMeldung(job.error || job.message || "") || t("common.failed");
      fertig(detail);
    } catch (fehler) {
      fertig(fehler.message);
    }
  }, 1000);
}

async function verwirfLabels() {
  try {
    await api("/labels", { methode: "DELETE" });
  } catch (fehler) {
    meldungListen(t("ui.hard.7e9ce1e8a1", { msg: fehler.message }));
  }
  ladeLabelStatus();
}

/**
 * Die Beschriftung einer fremden Adresse als Element — oder null.
 *
 * Eine Forenerwähnung wird bewusst anders formuliert als ein Dienst: „auf
 * BitcoinTalk erwähnt" ist keine Aussage darüber, wem die Adresse gehört.
 */
/**
 * Börse: nur Klarname. Grün = Zufluss von der Börse ins Wallet;
 * rot = Sats zur Börse geschickt (Einzahlung dort).
 */
function istBoersenLabel(label) {
  if (!label) return false;
  return (
    label.kategorie === "exchange"
    || label.kategorie_label === "Börse"
    || label.quelle === "Börsen-CSV"
    || Boolean(label.nutzer_import && label.kategorie === "exchange")
  );
}

/** "in" = von Börse→Wallet, "out" = Wallet→Börse, "" = unklar. */
function boerseRichtung(label, kontext) {
  const rolle = String(label?.rolle || "").toLowerCase();
  const hatEin = rolle.includes("einzahlung") || rolle.includes("deposit");
  const hatAus = rolle.includes("auszahlung") || rolle.includes("withdrawal");
  if (hatEin && !hatAus) return "out"; // Einzahlung auf die Börse
  if (hatAus && !hatEin) return "in"; // Auszahlung von der Börse
  if (kontext && kontext.zufluss) return "in"; // Herkunfts-Zufluss
  if (kontext && kontext.abfluss) return "out";
  // Ohne Rolle: im Herkunftsbaum typisch Zufluss von außen.
  if (kontext && kontext.herkunft) return "in";
  return "";
}

function labelMarke(label, kontext) {
  if (!label) return null;

  const marke = document.createElement("span");
  marke.className = `label-marke label-${label.art}`;
  const hinweis = t("labels.dataHint");

  if (!label.benannt) {
    marke.textContent = t("labels.knownService");
    marke.title = t("labels.knownNoNameTitle", { hint: hinweis });
    return marke;
  }
  if (label.art === "erwaehnung") {
    marke.textContent = t("labels.mentionedOn", { name: label.name });
    marke.title = t("labels.mentionedTitle", { hint: hinweis });
    return marke;
  }

  // Börsen: nur Name; Farbe nach Richtung.
  if (istBoersenLabel(label)) {
    const name = String(label.name || "").trim() || t("labels.cat.exchange");
    marke.textContent = name;
    marke.classList.add("label-boerse");
    const richtung = boerseRichtung(label, kontext || {});
    if (richtung === "in") marke.classList.add("label-boerse-in");
    else if (richtung === "out") marke.classList.add("label-boerse-out");
    const teile = [name];
    if (label.rolle) teile.push(label.rolle);
    if (richtung === "in") teile.push(t("labels.exchangeInflow"));
    else if (richtung === "out") teile.push(t("labels.exchangeOutflow"));
    if (label.quelle) teile.push(label.quelle);
    if (label.hinweis) teile.push(label.hinweis);
    teile.push(hinweis);
    marke.title = teile.filter(Boolean).join(" · ");
    return marke;
  }

  const katKey = `labels.cat.${label.kategorie || label.art || ""}`;
  const kat = (() => {
    const u = t(katKey);
    return u !== katKey ? u : (label.kategorie_label || label.art || "");
  })();
  const rolle = (label.rolle || "").trim();
  marke.textContent = rolle
    ? `${kat} · ${label.name} (${rolle})`
    : `${kat} · ${label.name}`;
  if (label.nutzer_import) {
    marke.classList.add("label-nutzer");
  }
  const teile = [];
  if (label.land) teile.push(t("labels.seat", { land: label.land }));
  if (label.status === "closed") teile.push(t("labels.serviceClosed"));
  if (label.nutzer_import) {
    teile.push(label.quelle || "Börsen-CSV");
    teile.push(label.hinweis || "");
  } else {
    teile.push(t("labels.sourceFile", {
      quelle: label.quelle,
      date: (label.stand || "").split("-").reverse().join("."),
    }));
    teile.push(hinweis);
  }
  marke.title = teile.filter(Boolean).join(" · ");
  return marke;
}

function meldungListen(text) {
  const kasten = $("#speicher-meldung");
  kasten.className = "hinweis hinweis-krit";
  setzeText(kasten, text);
  kasten.hidden = false;
}

// ---------------------------------------------------------------------------
// Sanktionscheck (xpub-blind, Hop-Vorgeschichte)
// ---------------------------------------------------------------------------

function fuellSankWallets() {
  const wahl = $("#sank-wallet");
  wahl.replaceChildren();
  const alle = document.createElement("option");
  alle.value = "";
  alle.textContent = t("wallets.allWallets");
  wahl.append(alle);
  for (const w of Zustand.config?.wallets || []) {
    const opt = document.createElement("option");
    opt.value = w.id;
    opt.textContent = w.name;
    wahl.append(opt);
  }
}

function sankMeldung(text, krit = true) {
  const kasten = $("#sank-meldung");
  kasten.className = krit ? "hinweis hinweis-krit" : "hinweis";
  setzeText(kasten, text);
  kasten.hidden = !text;
}

function zeichneSankErgebnis(daten) {
  const behaelter = $("#sank-ergebnis");
  behaelter.replaceChildren();

  // Woher das Ergebnis stammt: frisch gelaufen oder aus dem Cache. Ein
  // Sanktionsbefund ohne Datum wäre wertlos — die Listen ändern sich, und
  // der UTXO-Bestand auch.
  const zusatz = $("#sank-check-zusatz");
  if (daten.erstellt) {
    const teile = [`Stand ${daten.erstellt}`, `${daten.max_hops} Hop(s)`];
    if (daten.listen_adressen) {
      teile.push(`${formatZahl(daten.listen_adressen)} Listenadressen`);
    }
    if (daten.verbindungen > 1) teile.push(`${daten.verbindungen} Verbindungen`);
    if (daten.vollstaendig === false) teile.push("abgebrochen");
    setzeText(zusatz, teile.join(" · "));
  } else {
    setzeText(zusatz, "");
  }
  $("#sank-verwerfen").hidden = !daten.erstellt;

  for (const w of daten.wallets || []) {
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    const treffer = w.treffer || [];
    const umfang =
      `${w.wallet}: ${w.geprueft} UTXO(s)` +
      (w.adressen_geprueft
        ? t("sanctions.addressesChecked", { count: formatZahl(w.adressen_geprueft) })
        : "");
    if (treffer.length === 0) {
      zeile.append(pille("gut", t("sanctions.noHit")));
      const text = document.createElement("span");
      text.textContent =
        t("sanctions.cleanWindow", { hops: daten.max_hops || "?" }) +
        " · " +
        umfang +
        (w.abgebrochen ? t("sanctions.abortedSuffix") : "");
      zeile.append(text);
    } else {
      zeile.append(pille("krit", t("sanctions.hits", { count: treffer.length })));
      const text = document.createElement("span");
      text.textContent = umfang;
      zeile.append(text);
    }
    behaelter.append(zeile);

    for (const hit of treffer) {
      const detail = document.createElement("div");
      detail.className = "sanktions-zeile sanktions-treffer";
      const beschreibung = document.createElement("span");
      beschreibung.className = "mono klein";
      beschreibung.textContent =
        `Hop ${hit.hop} · ${hit.address} · ${formatSats(hit.amount_sats || 0)} ` +
        `über UTXO ${hit.from_utxo}`;
      detail.append(beschreibung);
      const link = mempoolVerweis("address", hit.address);
      if (link) detail.append(link);
      behaelter.append(detail);
    }

    const coinjoins = w.coinjoins || [];
    if (coinjoins.length) {
      const cjKopf = document.createElement("div");
      cjKopf.className = "sanktions-zeile";
      cjKopf.append(pille("warn", t("sanctions.coinjoins", { count: coinjoins.length })));
      const cjText = document.createElement("span");
      cjText.textContent = t("sanctions.coinjoinsHint");
      cjKopf.append(cjText);
      behaelter.append(cjKopf);
      for (const cj of coinjoins) {
        const detail = document.createElement("div");
        detail.className = "sanktions-zeile sanktions-coinjoin";
        const beschreibung = document.createElement("span");
        beschreibung.className = "mono klein";
        const when = cj.time || t("sanctions.timeUnknown");
        const en = uiSprache() === "en";
        let label =
          (en ? cj.label_en : cj.label) ||
          cj.label ||
          cj.label_en ||
          t("sanctions.coinjoinGeneric");
        if (/^wahrscheinlich\s+/i.test(label)) {
          label =
            t("sanctions.presumablyPrefix") +
            label.replace(/^wahrscheinlich\s+/i, "");
        } else if (/^likely\s+/i.test(label)) {
          label =
            t("sanctions.presumablyPrefix") + label.replace(/^likely\s+/i, "");
        }
        const tid = cj.txid ? kuerze(cj.txid, 10, 8) : "";
        beschreibung.textContent = t("sanctions.coinjoinLine", {
          hop: cj.hop ?? "?",
          when,
          label,
          tx: tid ? ` · Tx ${tid}` : "",
        });
        detail.append(beschreibung);
        if (cj.txid) {
          const link = mempoolVerweis("tx", cj.txid);
          if (link) detail.append(link);
        }
        behaelter.append(detail);
      }
    }

    const adressen = w.adressen || [];
    if (adressen.length) {
      const block = document.createElement("details");
      block.className = "sanktions-adressen";
      const titel = document.createElement("summary");
      titel.textContent = w.adressen_gekappt
        ? t("ui.hard.fa188a3309", { shown: formatZahl(adressen.length), total: formatZahl(w.adressen_geprueft) })
        : t("ui.hard.87e81c14a3", { n: formatZahl(adressen.length) });
      block.append(titel);
      const liste = document.createElement("div");
      liste.className = "mono klein";
      liste.textContent = adressen.join("\n");
      block.append(liste);
      behaelter.append(block);
    }
  }
}

/**
 * Zuletzt gespeichertes Ergebnis anzeigen.
 *
 * Ein Lauf über mehrere Hops dauert Minuten; beim Öffnen der Ansicht wird
 * deshalb der letzte Stand gezeigt, sichtbar datiert, statt automatisch neu
 * zu prüfen.
 */
async function ladeSankCache() {
  $("#sank-verwerfen").hidden = true;
  try {
    const daten = await api("/sanctions/check");
    if (!daten.vorhanden) {
      $("#sank-ergebnis").replaceChildren();
      setzeText($("#sank-check-zusatz"), t("sanctions.notYetChecked"));
      return;
    }
    zeichneSankErgebnis(daten);
    if (daten.max_hops) $("#sank-hops").value = daten.max_hops;
  } catch (fehler) {
    setzeText($("#sank-check-zusatz"), "");
    sankMeldung(t("sanctions.cacheUnreadable", { msg: fehler.message }));
  }
}

async function verwerfeSankCache() {
  try {
    await api("/sanctions/check", { methode: "DELETE" });
  } catch (fehler) {
    sankMeldung(t("sanctions.discardFailed", { msg: fehler.message }));
    return;
  }
  $("#sank-ergebnis").replaceChildren();
  setzeText($("#sank-check-zusatz"), t("sanctions.notYetChecked"));
  $("#sank-verwerfen").hidden = true;
  sankMeldung("");
}

/** Stoppt den lokalen Sanktions-Check-Poller (Seitenwechsel / Neustart). */
function stoppeSanktionsCheckPoller() {
  if (Zustand.sanktionsCheckTimer) {
    clearInterval(Zustand.sanktionsCheckTimer);
    Zustand.sanktionsCheckTimer = null;
  }
}

/**
 * Bindet UI an einen laufenden (oder fertigen) sanctions-check-Job.
 * Nach Seitenwechsel / Klick auf den Vorgang wieder aufrufen.
 */
function bindeSanktionsCheckJob(jobId, opts = {}) {
  if (!jobId) return;
  stoppeSanktionsCheckPoller();
  Zustand.sanktionsCheckJobId = jobId;

  const knopf = $("#sank-start");
  const abbruch = $("#sank-abbruch");
  const lauf = $("#sank-lauf");
  const laufText = $("#sank-lauf-text");
  if (knopf) knopf.disabled = true;
  if (abbruch) abbruch.hidden = false;
  if (lauf) lauf.hidden = false;
  if (laufText) {
    setzeText(laufText, t("sanctions.running") || "Prüfe…");
  }
  if (opts.hops && $("#sank-hops")) {
    $("#sank-hops").value = opts.hops;
  }

  const fertig = (meldung, kritisch = true) => {
    stoppeSanktionsCheckPoller();
    Zustand.sanktionsCheckJobId = null;
    if (knopf) knopf.disabled = false;
    if (abbruch) abbruch.hidden = true;
    if (lauf) lauf.hidden = true;
    if (meldung) sankMeldung(meldung, kritisch);
  };

  if (abbruch) {
    abbruch.onclick = async () => {
      setzeText(laufText, t("common.abortRequested") || "Abbruch angefordert…");
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* Job evtl. schon weg */
      }
    };
  }

  const tick = async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      if (laufText) {
        setzeText(
          laufText,
          übersetzeLogText(job.message || t("common.runningEllipsis")),
        );
      }
      if (job.running) return;
      if (job.status === "done" && job.result) {
        fertig(übersetzeLogText(job.message || ""), false);
        zeichneSankErgebnis(job.result);
      } else if (job.status === "cancelled") {
        fertig(t("common.cancelled") || "Abgebrochen", false);
        ladeSankCache();
      } else {
        fertig(
          übersetzeServerMeldung(job.error)
            || übersetzeLogText(job.message)
            || t("common.failed"),
        );
      }
    } catch (fehler) {
      // Kurz weg: Poll weiter — Job kann noch laufen (Netz/Throttle).
      if (laufText) {
        setzeText(
          laufText,
          t("sanctions.checkPollError", { msg: fehler.message }) !== "sanctions.checkPollError"
            ? t("sanctions.checkPollError", { msg: fehler.message })
            : t("ui.hard.d42b02b7be", { msg: fehler.message }),
        );
      }
    }
  };

  tick();
  Zustand.sanktionsCheckTimer = setInterval(tick, 1200);
}

async function starteSanktionsCheck() {
  if (Zustand.sanktionsCheckJobId) {
    bindeSanktionsCheckJob(Zustand.sanktionsCheckJobId);
    return;
  }
  const knopf = $("#sank-start");
  const abbruch = $("#sank-abbruch");
  knopf.disabled = true;
  abbruch.hidden = false;
  $("#sank-lauf").hidden = false;
  setzeText($("#sank-lauf-text"), t("sanctions.checkStarting"));
  sankMeldung("");
  $("#sank-ergebnis").replaceChildren();

  let hops = parseInt($("#sank-hops").value, 10);
  if (Number.isNaN(hops) || hops < 1) hops = 3;
  const hopCap = Number((Zustand.config || {}).sanktion_max_hops_cap) || 20;
  hops = Math.min(hops, hopCap);

  const daten = { max_hops: hops };
  const walletId = $("#sank-wallet").value;
  if (walletId) daten.wallet_id = walletId;

  try {
    const job = await api("/sanctions/check", { methode: "POST", daten });
    bindeSanktionsCheckJob(job.id, { hops });
  } catch (fehler) {
    stoppeSanktionsCheckPoller();
    Zustand.sanktionsCheckJobId = null;
    knopf.disabled = false;
    abbruch.hidden = true;
    $("#sank-lauf").hidden = true;
    sankMeldung(t("sanctions.checkFailed", { msg: fehler.message }));
  }
}

// ---------------------------------------------------------------------------
// Verweise auf die eigene mempool-Instanz
// ---------------------------------------------------------------------------

/**
 * Baut einen Verweis nach außen — oder nichts.
 *
 * Ohne konfigurierte Instanz entsteht bewusst kein Element. Ein Standardwert
 * auf mempool.space würde jedem Klick verraten, welche Adresse den Benutzer
 * interessiert; das widerspräche allem, was die Datenquellenwahl schützt.
 */
function mempoolVerweis(art, wert) {
  const instanz = Zustand.config?.mempool;
  if (!instanz || !instanz.configured || !wert) return null;

  const link = document.createElement("a");
  // Grün = eigenes Netz; Gelb = öffentlicher/fremder Explorer (Klick verrät Interesse).
  link.className = instanz.local
    ? "extern-link extern-link-lokal"
    : "extern-link extern-link-fremd";
  link.href = `${instanz.url}/${art}/${encodeURIComponent(wert)}`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.referrerPolicy = "no-referrer";
  link.textContent = "↗";
  const kopf = instanz.local
    ? t("sources.mempool.openPrivate")
    : t("sources.mempool.openPublic");
  const zielArt = art === "address"
    ? t("sources.mempool.targetAddress")
    : t("sources.mempool.targetTx");
  // Host in zweiter Zeile — native title zeigt Zeilenumbruch.
  link.title = `${kopf}\n${zielArt}\n${instanz.host}`;
  // stopPropagation: Zeile/Baum nicht aufklappen.
  // preventDefault auf dem Bubbling reicht nicht gegen <label>-Toggle —
  // deshalb defaultAction am Link belassen (Navigation), Label-Aktivierung
  // per stopImmediatePropagation + explizitem Fenster-Open vermeiden wir nicht;
  // Link liegt oft in label: Klick darf die Checkbox nicht umschalten.
  link.addEventListener("click", (e) => {
    e.stopPropagation();
    // In <label>: ohne preventDefault würde der Klick die Checkbox togglen.
    // Navigation bleibt über target=_blank + eigenem open, falls nötig.
    if (e.currentTarget.closest("label")) {
      e.preventDefault();
      window.open(link.href, "_blank", "noopener,noreferrer");
    }
  });
  return link;
}

function zeichneMempoolStatus() {
  const instanz = Zustand.config?.mempool || {};
  const managed = sourcesFullyManaged();
  const kasten = document.getElementById(managed ? "mempool-status-managed" : "mempool-status");
  if (!kasten) return;
  kasten.replaceChildren();
  const stufen = {
    keine: ["warn", t("sources.detail.notSet")],
    lokal: ["gut", t("sources.ownNetwork")],
    oeffentlich: ["warn", t("sources.mempool.publicReachable")],
    fremd: ["krit", t("sources.mempool.publicService")],
  };
  const [art, beschriftung] = stufen[instanz.stufe] || stufen.keine;
  kasten.append(pille(art, beschriftung));
  const hinweisKey = {
    lokal: "sources.mempool.local",
    fremd: "sources.mempool.publicKnown",
    oeffentlich: "sources.mempool.publicOther",
  }[instanz.stufe];
  const text = document.createElement("span");
  text.textContent = hinweisKey ? t(hinweisKey) : (instanz.hinweis || "");
  kasten.append(text);
  const feld = document.getElementById(managed ? "mempool-url-managed" : "mempool-url");
  if (feld) feld.value = instanz.url || "";
}

function zeichneSteuerEinstellungen() {
  const steuer = steuerEinstellungen();
  const jahre = steuer.haltefrist_jahre_auswahl;
  const gewaehlt = steuer.haltefrist_jahre;
  fuelleHaltefristAuswahl($("#steuer-haltefrist"), gewaehlt, jahre);
  // Steuerjahr-Dropdown teilt dieselben Labels (Sprache / Catalog-Nachzug).
  fuelleHaltefristAuswahl($("#frist-wahl"), gewaehlt, jahre);
  const datum = $("#steuer-stichtag");
  if (datum) datum.value = steuer.stichtag_iso || "";
  const anschaffung = $("#steuer-anschaffung");
  if (anschaffung) {
    anschaffung.value =
      steuer.anschaffung === "aelteste" ? "aelteste" : "juengste";
  }
  zeichnePersonEinstellungen();
}

function personEinstellungen() {
  const p = Zustand.config?.person || {};
  return {
    name: p.name || "Donald Duck",
    steuernummer: p.steuernummer || "0/8/15",
    anschrift: p.anschrift || "Entenhausen",
    email: p.email || "",
    finanzamt: p.finanzamt || "",
    finanzamt_anschrift: p.finanzamt_anschrift || "",
    sachbearbeiter: p.sachbearbeiter || "",
  };
}

function zeichnePersonEinstellungen() {
  const p = personEinstellungen();
  const name = $("#person-name");
  const sn = $("#person-steuernummer");
  const adr = $("#person-anschrift");
  const mail = $("#person-email");
  const fa = $("#person-finanzamt");
  const faAdr = $("#person-finanzamt-anschrift");
  const sb = $("#person-sachbearbeiter");
  if (name) name.value = p.name;
  if (sn) sn.value = p.steuernummer;
  if (adr) adr.value = p.anschrift;
  if (mail) mail.value = p.email;
  if (fa) fa.value = p.finanzamt;
  if (faAdr) faAdr.value = p.finanzamt_anschrift;
  if (sb) sb.value = p.sachbearbeiter;
}

async function speicherePersonEinstellungen() {
  const knopf = $("#person-uebernehmen");
  if (knopf) knopf.disabled = true;
  try {
    const ergebnis = await api("/config/person", {
      methode: "PUT",
      daten: {
        name: $("#person-name")?.value || "",
        steuernummer: $("#person-steuernummer")?.value || "",
        anschrift: $("#person-anschrift")?.value || "",
        email: $("#person-email")?.value || "",
        finanzamt: $("#person-finanzamt")?.value || "",
        finanzamt_anschrift: $("#person-finanzamt-anschrift")?.value || "",
        sachbearbeiter: $("#person-sachbearbeiter")?.value || "",
      },
    });
    if (Zustand.config) Zustand.config.person = ergebnis.person;
    zeichnePersonEinstellungen();
    meldung(
      t("settings.personSaved") !== "settings.personSaved"
        ? t("settings.personSaved")
        : t("ui.hard.516a1e0970"),
      "gut",
    );
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

function setzeKnownOnlySichtbarkeit(parentAn = undefined) {
  const zeile = $("#start-sync-known-only-zeile");
  const box = $("#start-sync-known-only");
  if (!zeile || !box) return;
  const an = parentAn === undefined
    ? Boolean(
      Zustand.config?.wallets_immer_aktuell
      ?? Zustand.config?.wallets_beim_start_aktualisieren,
    )
    : Boolean(parentAn);
  zeile.hidden = !an;
  box.disabled = !an;
  if (!an) box.checked = false;
}

function zeichneStartSync() {
  const box = $("#start-sync");
  if (!box) return;
  const an = Boolean(
    Zustand.config?.wallets_immer_aktuell
    ?? Zustand.config?.wallets_beim_start_aktualisieren,
  );
  box.checked = an;
  const known = $("#start-sync-known-only");
  if (known) {
    known.checked = an && Boolean(Zustand.config?.wallets_nur_bekannte_utxos);
  }
  setzeKnownOnlySichtbarkeit(an);
  setzeTipSyncSichtbarkeit(an);
}

async function speichereStartSync(ereignis) {
  const box = $("#start-sync");
  if (!box) return;
  const an = box.checked;
  const knownBox = $("#start-sync-known-only");
  const nurBekannte = an && Boolean(knownBox?.checked);
  const vonKnownOnly = Boolean(
    ereignis && knownBox && ereignis.target === knownBox,
  );
  // Hide/show immediately; the config response below remains authoritative.
  setzeKnownOnlySichtbarkeit(an);
  setzeTipSyncSichtbarkeit(an);
  try {
    const ergebnis = await api("/config/start-sync", {
      methode: "PUT",
      daten: {
        enabled: an,
        nur_bekannte_utxos: nurBekannte,
      },
    });
    if (Zustand.config) {
      const v = Boolean(
        ergebnis.wallets_immer_aktuell
        ?? ergebnis.wallets_beim_start_aktualisieren,
      );
      Zustand.config.wallets_immer_aktuell = v;
      Zustand.config.wallets_beim_start_aktualisieren = v;
      Zustand.config.wallets_nur_bekannte_utxos = Boolean(
        ergebnis.wallets_nur_bekannte_utxos,
      );
      if (ergebnis.wallet_watch) {
        Zustand.config.wallet_watch = ergebnis.wallet_watch;
      }
    }
    zeichneStartSync();
    // Tip-Nachzug sofort mitverfolgen (ohne Server-Neustart).
    const jobId = ergebnis.wallet_sync_job_id || ergebnis.job?.id;
    if (an && jobId) {
      if (Zustand.config) {
        Zustand.config.wallet_sync_job_id = jobId;
      }
      folgeWalletSyncJob(jobId, ergebnis.job);
      if (!vonKnownOnly) logZeile(t("settings.startSyncStarted"));
      await ladeJobsNav();
    }
    let text = t("settings.startSyncOff");
    if (an && vonKnownOnly) {
      text = nurBekannte
        ? t("settings.startSyncKnownOnlyOn")
        : t("settings.startSyncKnownOnlyOff");
    } else if (an && nurBekannte) {
      text = t("settings.startSyncKnownOnlyOn");
    } else if (an) {
      text = t("settings.startSyncOn");
    }
    meldung(text, "gut");
  } catch (fehler) {
    zeichneStartSync();
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  }
}

async function speichereSteuerEinstellungen() {
  const knopf = $("#steuer-uebernehmen");
  knopf.disabled = true;
  try {
    const ergebnis = await api("/config/steuer", {
      methode: "PUT",
      daten: {
        haltefrist_jahre: Number($("#steuer-haltefrist").value),
        stichtag: $("#steuer-stichtag").value,
        anschaffung: $("#steuer-anschaffung")?.value || "juengste",
      },
    });
    if (Zustand.config) Zustand.config.steuer = ergebnis.steuer;
    zeichneSteuerEinstellungen();
    fuelleHaltefristAuswahl(
      $("#frist-wahl"),
      ergebnis.steuer.haltefrist_jahre,
      ergebnis.steuer.haltefrist_jahre_auswahl,
    );
    meldung(t("settings.taxSaved"), "gut");
    if (Zustand.ansicht === "steuerjahr") ladeSteuerjahrMitKandidaten();
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    knopf.disabled = false;
  }
}

/**
 * Grobe Client-Schätzung: öffentliche Clearnet-Domain vs. LAN/Loopback/Onion.
 * Server entscheidet final (mempool_info / outbound_policy).
 */
function mempoolUrlWirktOeffentlich(roh) {
  let text = String(roh || "").trim();
  if (!text) return false;
  try {
    // Kein /…/-Literal mit // — sonst stolpert der Klammer-Check in tests/test_web_js.
    if (!(text.startsWith("http://") || text.startsWith("https://"))) {
      text = `https://${text}`;
    }
    const u = new URL(text);
    const host = String(u.hostname || "").toLowerCase();
    if (!host) return false;
    if (host === "localhost" || host.endsWith(".localhost")) return false;
    if (host.endsWith(".onion")) return false;
    if (
      host.endsWith(".local")
      || host.endsWith(".lan")
      || host.endsWith(".internal")
      || host.endsWith(".home")
      || host.endsWith(".home.arpa")
      || host.endsWith(".test")
      || host.endsWith(".example")
      || host.endsWith(".invalid")
    ) {
      return false;
    }
    if (
      /^127\./.test(host)
      || /^10\./.test(host)
      || /^192\.168\./.test(host)
      || /^172\.(1[6-9]|2\d|3[01])\./.test(host)
    ) {
      return false;
    }
    // Hostname ohne Punkt → typisch LAN-Kurzname.
    if (!host.includes(".")) return false;
    return true;
  } catch (_) {
    return false;
  }
}

async function speichereMempool() {
  const managed = sourcesFullyManaged();
  const knopf = document.getElementById(managed ? "mempool-speichern-managed" : "mempool-speichern");
  if (!knopf) return;
  knopf.disabled = true;
  try {
    const feld = document.getElementById(managed ? "mempool-url-managed" : "mempool-url");
    const url = feld ? String(feld.value || "").trim() : "";
    let publicOptIn = false;
    if (url && mempoolUrlWirktOeffentlich(url)) {
      const ok = window.confirm(
        t("sources.mempool.publicConfirm"),
      );
      if (!ok) {
        // Abbruch: nicht speichern, Eingabe leeren.
        if (feld) feld.value = "";
        return;
      }
      publicOptIn = true;
    }
    await api("/config/mempool", {
      methode: "PUT",
      daten: { url, public_opt_in: publicOptIn },
    });
    await ladeConfig();
    zeichneMempoolStatus();
    zeichneKopfStatus(Zustand.config?.quellen || []);
    Zustand.traceListe = null;
    verwerfeGezeichneteVerweise();
    meldung(t("sources.explorerSaved"), "gut");
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    knopf.disabled = false;
  }
}

/** Entfernt Verweise aus bereits gezeichneten Ansichten. */
function verwerfeGezeichneteVerweise() {
  for (const link of document.querySelectorAll(".extern-link")) {
    link.remove();
  }
  if (Zustand.walletId) {
    // Neu laden, damit die Verweise mit der neuen Einstellung entstehen.
    zeigeWallet(Zustand.walletId).catch(() => {});
  }
}

function pille(stufe, text) {
  const span = document.createElement("span");
  span.className = `pille pille-${stufe}`;
  span.textContent = text;
  return span;
}

async function pruefeSkripttyp(wallet, ausgabe, knopf) {
  knopf.disabled = true;
  ausgabe.hidden = false;
  ausgabe.replaceChildren(document.createTextNode("Leite Adressen ab…"));

  try {
    // Gespeicherte Wallets über die Kennung: Die Oberfläche kennt nur die
    // maskierte Fassung, der Server schlägt den vollen Schlüssel selbst nach.
    const ergebnis = await api("/wallets/probe", {
      methode: "POST",
      daten: wallet.is_new
        ? { xpub: wallet.xpub }
        : { wallet_id: wallet.id },
    });
    ausgabe.replaceChildren();

    const tabelle = document.createElement("table");
    for (const kandidat of ergebnis.candidates) {
      const zeile = document.createElement("tr");
      const typ = document.createElement("td");
      typ.textContent = kandidat.label;
      const adresse = document.createElement("td");
      adresse.className = "mono klein";
      adresse.textContent = kandidat.example_address;
      zeile.append(typ, adresse);
      tabelle.append(zeile);
    }
    ausgabe.append(tabelle);

    const hinweis = document.createElement("div");
    hinweis.className = "probe-hinweis";
    hinweis.textContent = ergebnis.note;
    ausgabe.append(hinweis);
  } catch (fehler) {
    ausgabe.replaceChildren(
      document.createTextNode(`Erkennung fehlgeschlagen: ${fehler.message}`)
    );
  } finally {
    knopf.disabled = false;
  }
}

function meldung(text, art) {
  const kasten = $("#speicher-meldung");
  kasten.className = `hinweis hinweis-${art}`;
  setzeText(kasten, text);
  kasten.hidden = false;
  if (art === "gut") {
    setTimeout(() => { kasten.hidden = true; }, 4000);
  }
}

function setzeCacheLeerenBestaetigung(an) {
  $("#cache-leeren").hidden = an;
  $("#cache-leeren-ok").hidden = !an;
  $("#cache-leeren-abbruch").hidden = !an;
  if (an) setzeWalletCacheBestaetigung(null);
}

function setzeWalletCacheBestaetigung(walletId) {
  for (const zeile of document.querySelectorAll("#cache-wallets .gefahr-zeile")) {
    const hier = zeile.dataset.walletId === walletId;
    const loeschen = zeile.querySelector(".wallet-cache-leeren");
    const ok = zeile.querySelector(".wallet-cache-ok");
    const abbruch = zeile.querySelector(".wallet-cache-abbruch");
    if (loeschen) loeschen.hidden = hier;
    if (ok) ok.hidden = !hier;
    if (abbruch) abbruch.hidden = !hier;
  }
}

async function ladeGefahrWallets() {
  const ziel = $("#cache-wallets");
  if (!ziel) return;
  try {
    const antwort = await api("/cache/wallets");
    zeichneGefahrWallets(antwort?.wallets || []);
  } catch (_) {
    // Fallback: nur konfigurierte Wallets aus der Config.
    const fallback = (Zustand.config?.wallets || [])
      .filter((w) => !w.is_new)
      .map((w) => ({
        id: w.id,
        name: w.name,
        configured: true,
        has_cache: Boolean(w.has_cache),
        utxo_count: w.utxo_count || 0,
        verlauf_count: w.export_verlauf_n || 0,
        stale: false,
      }));
    zeichneGefahrWallets(fallback);
  }
}

function zeichneGefahrWallets(wallets) {
  const ziel = $("#cache-wallets");
  if (!ziel) return;
  ziel.replaceChildren();
  const liste = Array.isArray(wallets) ? wallets : [];
  if (!liste.length) {
    const leer = document.createElement("p");
    leer.className = "gefahr-leer";
    leer.textContent = t("wallets.noWallets");
    ziel.append(leer);
    return;
  }
  for (const wallet of liste) {
    const zeile = document.createElement("div");
    zeile.className = "gefahr-zeile";
    if (wallet.stale || wallet.configured === false) {
      zeile.classList.add("gefahr-stale");
    }
    zeile.dataset.walletId = wallet.id;

    const name = document.createElement("span");
    name.className = "gefahr-name";
    name.textContent = wallet.name || t("common.wallet");
    if (wallet.stale || wallet.configured === false) {
      name.title = t("wallets.cacheStaleTitle");
      const badge = document.createElement("span");
      badge.className = "pille pille-warn";
      badge.textContent = t("wallets.cacheStaleBadge");
      badge.title = t("wallets.cacheStaleTitle");
      name.append(document.createTextNode(" "), badge);
    }

    const stand = document.createElement("span");
    stand.className = "gefahr-stand";
    const has = Boolean(wallet.has_cache)
      || Number(wallet.utxo_count || 0) > 0
      || Number(wallet.verlauf_count || 0) > 0;
    if (has) {
      const teile = [];
      const u = Number(wallet.utxo_count || 0);
      const v = Number(wallet.verlauf_count || 0);
      if (u > 0) {
        teile.push(u === 1 ? t("wallets.utxoOne") : t("wallets.utxoMany", { n: u }));
      }
      if (v > 0) {
        teile.push(v === 1 ? "1 Tx" : `${v} Tx`);
      }
      if (!teile.length) teile.push("Cache");
      // Konfigurierte: optional Frische-Hinweis
      const cfg = (Zustand.config?.wallets || []).find((w) => w.id === wallet.id);
      if (cfg && cacheHinweis(cfg)) teile.push(cacheHinweis(cfg));
      stand.textContent = teile.join(" · ");
    } else {
      stand.textContent = t("wallets.noCache");
    }

    const loeschen = document.createElement("button");
    loeschen.type = "button";
    loeschen.className = "knopf knopf-gefahr knopf-klein wallet-cache-leeren";
    loeschen.textContent = t("wallets.cacheDelete");
    loeschen.title = t("wallets.cacheDeleteTitle");
    loeschen.disabled = !has;
    loeschen.addEventListener("click", () => {
      setzeCacheLeerenBestaetigung(false);
      setzeWalletCacheBestaetigung(wallet.id);
    });

    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "knopf knopf-gefahr knopf-klein wallet-cache-ok";
    ok.textContent = t("wallets.cacheDeleteReally");
    ok.title = t("wallets.cacheDeleteReallyTitle", {
      name: wallet.name || wallet.id || "?",
    });
    ok.hidden = true;
    ok.addEventListener("click", () => leereWalletCache(wallet));

    const abbruch = document.createElement("button");
    abbruch.type = "button";
    abbruch.className = "knopf knopf-klein wallet-cache-abbruch";
    abbruch.textContent = t("common.cancel");
    abbruch.hidden = true;
    abbruch.addEventListener("click", () => setzeWalletCacheBestaetigung(null));

    zeile.append(name, stand, loeschen, ok, abbruch);
    ziel.append(zeile);
  }
}

async function leereWalletCache(wallet) {
  const kasten = $("#cache-leeren-meldung");
  kasten.hidden = true;
  setzeWalletCacheBestaetigung(null);
  const nameVorab = wallet.name || wallet.id || t("wallets.thisWallet");
  logZeile(`Lösche ${nameVorab}`, undefined, nameVorab);
  try {
    const ergebnis = await api(`/cache/${encodeURIComponent(wallet.id)}`, {
      methode: "DELETE",
    });
    Zustand.traceListe = null;
    Zustand.steuer = null;
    const n = (ergebnis.utxo_eintraege || 0)
      + (ergebnis.verlauf_eintraege || 0)
      + (ergebnis.herkunft_eintraege || 0);
    const name = ergebnis.wallet_name || wallet.name;
    const stale = wallet.stale || wallet.configured === false;
    const text = n
      ? (stale
        ? t("ui.hard.087dcf6171", { name, n })
        : t("ui.hard.96e1d96d33", { name, n }))
      : t("ui.hard.482eb153dd", { name });
    kasten.className = "hinweis hinweis-gut";
    setzeText(kasten, text);
    kasten.hidden = false;
    logZeile(text, undefined, name);
    for (const z of ergebnis.logs || []) {
      const s = String(z || "").trim();
      // Start/Ende loggt die UI selbst (Timestamps um den API-Call).
      if (!s || s === t("ui.hard.7bf2df499b") || /^Lösche [^:]/.test(s)) continue;
      logZeile(s, undefined, name);
    }
    logZeile(t("ui.hard.7bf2df499b"), undefined, name);
    await ladeConfig();
    zeichneEinstellungen();
    await ladeGefahrWallets();
    await ladeUnreferenziertenCache();
    if (Zustand.ansicht === "wallet" && Zustand.walletId === wallet.id) {
      await zeigeWallet(Zustand.walletId);
    }
  } catch (fehler) {
    logZeile(t("ui.hard.7bf2df499b"), true, nameVorab);
    kasten.className = "hinweis hinweis-krit";
    setzeText(kasten, t("ui.hard.4b44b452e9", { msg: fehler.message }));
    kasten.hidden = false;
  }
}

async function leereGesamtenCache() {
  const kasten = $("#cache-leeren-meldung");
  kasten.hidden = true;
  $("#cache-leeren-ok").disabled = true;
  try {
    const ergebnis = await api("/cache", { methode: "DELETE" });
    Zustand.traceListe = null;
    Zustand.steuer = null;
    setzeCacheLeerenBestaetigung(false);
    const n = (ergebnis.utxo_eintraege || 0) + (ergebnis.immutable_eintraege || 0);
    const text = n
      ? t("ui.hard.fb93960ca3", { n })
      : "Cache war bereits leer.";
    kasten.className = "hinweis hinweis-gut";
    setzeText(kasten, text);
    kasten.hidden = false;
    logZeile(text);
    await ladeConfig();
    zeichneEinstellungen();
    if (Zustand.ansicht === "wallet" && Zustand.walletId) {
      await zeigeWallet(Zustand.walletId);
    }
  } catch (fehler) {
    kasten.className = "hinweis hinweis-krit";
    setzeText(kasten, t("ui.hard.4b44b452e9", { msg: fehler.message }));
    kasten.hidden = false;
  } finally {
    $("#cache-leeren-ok").disabled = false;
  }
}

function hatNodeMitHoherPrivatsphaere() {
  const quellen = Zustand.config?.sources || [];
  return quellen.some(
    (q) =>
      (q.key === "own_fulcrum" && q.configured) ||
      (q.key === "bip158" && q.configured),
  );
}

/**
 * Der Sprung „keine Wallet → mindestens eine“ ohne eigenen Node.
 * Genau das ist der Daddeldu-Fall (leere .env plus erstes XPUB).
 */
function ersterXpubOhneSicherenNode(anzahlNeu) {
  const bisher = (Zustand.config?.wallets || []).length;
  return bisher === 0 && anzahlNeu > 0 && !hatNodeMitHoherPrivatsphaere();
}

function zeigePrivatsphaereWarnung() {
  const overlay = $("#privatsphaere-warnung");
  overlay.hidden = false;
  const sicher = $("#privatsphaere-entfernen");
  if (sicher) sicher.focus();
}

function verwerfeErstenXpub() {
  $("#privatsphaere-warnung").hidden = true;
  Zustand.entwurf = (Zustand.config?.wallets || []).map((w) => ({ ...w }));
  const nameFeld = $("#neuer-name");
  if (nameFeld) nameFeld.value = "";
  const xpubFeld = $("#neuer-xpub");
  if (xpubFeld) xpubFeld.value = "";
  const deskName = $("#neuer-deskriptor-name");
  if (deskName) deskName.value = "";
  const deskFeld = $("#neuer-deskriptor");
  if (deskFeld) deskFeld.value = "";
  const befund = $("#deskriptor-befund");
  if (befund) befund.hidden = true;
  zeichneEinstellungen();
}

function akzeptiereOhneSicherenNode() {
  $("#privatsphaere-warnung").hidden = true;
  speichereWallets(false, true, null);
}

function walletsNutzlast() {
  // Bestehende Wallets über ihre Kennung, neue über den eingefügten
  // Schlüssel — der volle XPUB verlässt den Server nie.
  return Zustand.entwurf.map((w) => ({
    // Neu angelegte Multisig kommt über ihren Deskriptor, neue Single-Sig
    // über den XPUB, bestehende über ihre Kennung — der volle Schlüssel
    // verlässt den Server nie.
    ...(w.is_new
      ? (w.descriptor ? { descriptor: w.descriptor } : { xpub: w.xpub })
      : { id: w.id }),
    name: w.name,
    script_type: w.script_type,
    max_addresses: w.max_addresses,
    read_only: Boolean(w.read_only),
    ...(w.origin ? { origin: w.origin } : {}),
  }));
}

/**
 * Fragt nach, ob der Cache entfernter Wallets mit weg soll.
 *
 * Rückgabe: true = löschen, false = behalten, null = keine Entfernung.
 * confirm-Abbrechen bedeutet „Cache behalten“, nicht „Speichern abbrechen“.
 */
async function frageCacheBeiWalletLoeschung(nutzlast) {
  let vorschau;
  try {
    vorschau = await api("/config/wallets/cache-vorschau", {
      methode: "POST",
      daten: { wallets: nutzlast },
    });
  } catch (fehler) {
    meldung(t("ui.hard.592e956ae3", { msg: fehler.message }), "krit");
    return false;
  }
  const entfernt = vorschau.entfernt || [];
  if (!entfernt.length) return null;

  const namen = entfernt.map((e) => e.wallet_name || e.wallet_id).join(", ");
  const groesse = vorschau.groesse_label || "0 MB";
  const mb = Number(vorschau.groesse_mb || 0);
  const mbText = Number.isFinite(mb)
    ? `${mb.toLocaleString(formatLocale(), {
        minimumFractionDigits: mb >= 0.1 || mb === 0 ? 1 : 3,
        maximumFractionDigits: 3,
      })} MB`
    : groesse;
  const zeilen = [
    entfernt.length === 1
      ? `Du entfernst das Wallet „${namen}“.`
      : `Du entfernst ${entfernt.length} Wallets: ${namen}.`,
    "",
    t("sources.hard.d5d69df339", { mb: mbText }),
    "",
    "OK = Cache löschen",
    "Abbrechen = Wallet weg, Cache behalten",
  ];
  return window.confirm(zeilen.join("\n"));
}

async function speichereWallets(
  bestaetigt = false,
  privatsphaereOk = false,
  cacheEntfernteLoeschen = null,
  loeschNamenHinweis = null,
) {
  if (Zustand.walletSpeichernLaeuft) return;
  if (!privatsphaereOk && ersterXpubOhneSicherenNode(Zustand.entwurf.length)) {
    zeigePrivatsphaereWarnung();
    return;
  }
  const idsVorher = new Set(
    (Zustand.config?.wallets || []).map((w) => w.id).filter(Boolean),
  );
  const hatteNeue = Zustand.entwurf.some((w) => w.is_new);
  const behaltenIds = new Set(
    Zustand.entwurf.filter((w) => !w.is_new && w.id).map((w) => w.id),
  );
  const entferntVorab = (Zustand.config?.wallets || []).filter(
    (w) => w.id && !behaltenIds.has(w.id),
  );
  const loeschNamen = (
    Array.isArray(loeschNamenHinweis) && loeschNamenHinweis.length
      ? loeschNamenHinweis
      : entferntVorab.map((w) => w.name || w.id || "?")
  ).filter(Boolean);
  Zustand.walletSpeichernLaeuft = true;
  setzeWalletSpeichernGesperrt(true);
  let loeschLogOffen = false;
  try {
    const nutzlast = walletsNutzlast();
    if (cacheEntfernteLoeschen === null) {
      const vielleichtEntfernt = entferntVorab.length > 0;
      if (vielleichtEntfernt) {
        if (loeschNamen.length) {
          for (const n of loeschNamen) {
            logZeile(`Lösche ${n}`, undefined, n);
          }
          loeschLogOffen = true;
        }
        const entscheidung = await frageCacheBeiWalletLoeschung(nutzlast);
        cacheEntfernteLoeschen = entscheidung === true;
      } else {
        cacheEntfernteLoeschen = false;
      }
    } else if (loeschNamen.length) {
      for (const n of loeschNamen) {
        logZeile(`Lösche ${n}`, undefined, n);
      }
      loeschLogOffen = true;
    }
    const ergebnis = await api("/config/wallets", {
      methode: "PUT",
      daten: {
        wallets: nutzlast,
        confirm: bestaetigt,
        cache_entfernte_loeschen: Boolean(cacheEntfernteLoeschen),
      },
    });
    for (const z of ergebnis.logs || []) {
      const s = String(z || "").trim();
      // Start/Ende loggt die UI selbst (Timestamps um den API-Call).
      if (!s || s === t("ui.hard.7bf2df499b") || /^Lösche [^:]/.test(s)) continue;
      logZeile(s);
    }
    let text = ergebnis.backup
      ? t("ui.hard.130ee40b9e", { backup: ergebnis.backup })
      : "Gespeichert.";
    if ((ergebnis.cache_entfernt || []).length) {
      text += ` Cache entfernt (${ergebnis.cache_groesse_label || "0 MB"}).`;
    }
    meldung(text, "gut");
    if (loeschLogOffen || (ergebnis.cache_entfernt || []).length) {
      logZeile(t("ui.hard.7bf2df499b"));
      loeschLogOffen = false;
    }
    await ladeConfig();
    zeichneEinstellungen();
    if (Zustand.ansicht === "wallets") ladeUnreferenziertenCache();
    if (hatteNeue) {
      const neu = (Zustand.config?.wallets || []).filter(
        (w) => w.id && !idsVorher.has(w.id),
      );
      if (neu.length) await nachNeuemWalletScannen(neu);
    }
  } catch (fehler) {
    if (loeschLogOffen) {
      logZeile(t("ui.hard.7bf2df499b"), true);
      loeschLogOffen = false;
    }
    if (fehler.brauchtBestaetigung) {
      warnungMitBestaetigung(fehler.message, cacheEntfernteLoeschen);
    } else {
      meldung(t("ui.hard.37ce417490", { msg: fehler.message }), "krit");
    }
  } finally {
    Zustand.walletSpeichernLaeuft = false;
    setzeWalletSpeichernGesperrt(false);
  }
}

function setzeWalletSpeichernGesperrt(an) {
  const hinzufuegen = $("#hinzufuegen");
  if (hinzufuegen) hinzufuegen.disabled = an;
  for (const knopf of document.querySelectorAll(".name-uebernehmen")) {
    if (an) knopf.disabled = true;
  }
  if (!an) aktualisiereSpeicherleiste();
}

/**
 * Zeigt eine Warnung, die der Benutzer übergehen darf.
 *
 * Anders als ein Fehler beschreibt sie eine Folge, keine Unmöglichkeit — die
 * Abwägung gehört dem Benutzer, nicht dem Programm.
 */
function warnungMitBestaetigung(text, cacheEntfernteLoeschen = false) {
  const kasten = $("#speicher-meldung");
  kasten.className = "hinweis hinweis-warn";
  kasten.replaceChildren();

  const inhalt = document.createElement("span");
  inhalt.textContent = text;

  const trotzdem = document.createElement("button");
  trotzdem.type = "button";
  trotzdem.className = "knopf knopf-klein";
  trotzdem.style.marginLeft = "auto";
  trotzdem.style.flex = "none";
  trotzdem.textContent = t("wallets.saveAnyway");
  trotzdem.addEventListener("click", () => {
    kasten.hidden = true;
    speichereWallets(true, true, cacheEntfernteLoeschen);
  });

  kasten.append(inhalt, trotzdem);
  kasten.hidden = false;
}

/**
 * Prüft den eingefügten Text und zeigt, was daraus würde.
 *
 * Ein Feld für zwei Wege: den von Hand getippten Deskriptor und den
 * kopierten Wallet-Export. Der Unterschied liegt im Text, nicht in der
 * Absicht — der Server zieht in beiden Fällen dasselbe heraus.
 *
 * Angezeigt wird immer die **erste Empfangsadresse**. Nur an ihr lässt sich
 * vor dem Speichern erkennen, ob wirklich die eigene Wallet gemeint ist: Ein
 * Deskriptor sieht auch dann richtig aus, wenn ein Schlüssel vertauscht wurde.
 */
async function pruefeDeskriptor() {
  const feld = $("#neuer-deskriptor");
  const kasten = $("#deskriptor-befund");
  const text = feld.value.trim();

  if (!text) {
    kasten.hidden = true;
    return;
  }

  let antwort;
  try {
    antwort = await api("/config/deskriptor", {
      methode: "POST", daten: { text },
    });
  } catch (fehler) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(fehler.message));
    return;
  }

  kasten.hidden = false;
  kasten.replaceChildren();

  if (antwort.fehler) {
    const zeile = document.createElement("div");
    zeile.className = "hinweis hinweis-warn";
    zeile.textContent = antwort.fehler;
    kasten.append(zeile);
    return;
  }

  for (const treffer of antwort.gefunden) {
    kasten.append(deskriptorKarte(treffer, feld));
  }
}

/** Ein gefundener Deskriptor mit Befund und Übernehmen-Knopf. */
function deskriptorKarte(treffer, feld) {
  const block = document.createElement("div");
  block.className = "deskriptor-treffer";

  const kopf = document.createElement("div");
  kopf.className = "knoten-oben";
  kopf.append(pille("gut", scriptTypLabel(treffer.script_type, treffer.script_type_label)));
  if (treffer.is_multisig && treffer.threshold) {
    const art = document.createElement("span");
    art.textContent = t("wallets.thresholdOf", { m: treffer.threshold, n: treffer.cosigner_count });
    kopf.append(art);
  } else if (treffer.is_multisig) {
    // Bei Policies mit mehreren Ausgabepfaden gibt es kein „m von n" — eine
    // Zahl zu erfinden wäre schlimmer als keine.
    const art = document.createElement("span");
    art.textContent = t("wallets.hard.48466a35e2", { n: treffer.cosigner_count });
    kopf.append(art);
  } else {
    const art = document.createElement("span");
    art.textContent = t("ui.hard.bed1685e9b");
    kopf.append(art);
  }
  if (treffer.bereits_vorhanden) {
    kopf.append(pille("warn", t("ui.hard.f76bf868bb")));
  }
  block.append(kopf);

  const adresse = document.createElement("div");
  adresse.className = "deskriptor-adresse";
  adresse.innerHTML =
    "<span class='feld-titel'>" + t("ui.hard.4707ae5509") + "</span>";
  const wert = document.createElement("div");
  wert.className = "mono";
  wert.textContent = treffer.erste_adresse || "—";
  adresse.append(wert);
  block.append(adresse);

  const keys = document.createElement("div");
  keys.className = "zart mono";
  keys.textContent = (treffer.xpubs_masked || []).join(", ");
  block.append(keys);

  const knopf = document.createElement("button");
  knopf.type = "button";
  knopf.className = "knopf knopf-primaer";
  knopf.textContent = treffer.bereits_vorhanden
    ? t("ui.hard.2e2eed6931")
    : t("ui.hard.5943084263");
  knopf.title = treffer.bereits_vorhanden
    ? t("ui.hard.e861e729a2")
    : t("ui.hard.105945eed3");
  knopf.addEventListener("click", () => {
    uebernimmDeskriptor(treffer);
    feld.value = "";
    $("#deskriptor-befund").hidden = true;
  });
  block.append(knopf);

  return block;
}

function oeffneDeskriptorImport() {
  $("#deskriptor-datei").click();
}

function liesDeskriptorDatei(ereignis) {
  const datei = ereignis.target.files && ereignis.target.files[0];
  ereignis.target.value = "";
  if (!datei) return;
  const leser = new FileReader();
  leser.onload = () => {
    $("#neuer-deskriptor").value = String(leser.result || "");
    pruefeDeskriptor();
  };
  leser.onerror = () => {
    const kasten = $("#deskriptor-befund");
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(t("common.fileUnreadable")));
  };
  leser.readAsText(datei);
}

/** Gewählte Pfade in der Sparrow/Wasabi-Suchliste. */
function walletExportGewaehltePfade() {
  const liste = $("#wallet-export-liste");
  if (!liste) return [];
  return [...liste.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)')]
    .map((el) => el.value)
    .filter(Boolean);
}

/** Knopf-Text: Datei(en) vs. Wallet(s) je nach Checkbox-Auswahl. */
function aktualisiereWalletExportImportKnopf() {
  const knopf = $("#sparrow-import");
  if (!knopf) return;
  const n = walletExportGewaehltePfade().length;
  if (n > 0) {
    knopf.textContent = t("wallets.exportImportWallets");
    knopf.title = t("wallets.exportImportWalletsTitle");
    knopf.dataset.i18n = "wallets.exportImportWallets";
    knopf.dataset.i18nTitle = "wallets.exportImportWalletsTitle";
  } else {
    knopf.textContent = t("wallets.exportImportFile");
    knopf.title = t("wallets.exportImportTitle");
    knopf.dataset.i18n = "wallets.exportImportFile";
    knopf.dataset.i18nTitle = "wallets.exportImportTitle";
  }
}

/**
 * Ein Knopf: mit Checkbox-Auswahl → Wallet-Pfade importieren,
 * sonst Datei-Dialog.
 */
function oeffneSparrowImport() {
  const pfade = walletExportGewaehltePfade();
  if (pfade.length) {
    starteWalletExportImportAuswahl(false);
    return;
  }
  const feld = $("#sparrow-dateien");
  if (feld) feld.click();
}

function liesSparrowDateien(ereignis) {
  const liste = ereignis.target.files;
  ereignis.target.value = "";
  if (!liste || !liste.length) return;
  starteSparrowImport(Array.from(liste));
}

/** Letzte Suchtreffer (Pfad → Meta) für den Import-Knopf. */
let _walletExportTreffer = [];

/**
 * Wallet-Export-Suche als normales JSON (kein NDJSON-Stream).
 *
 * Die Suche ist lokal und schnell; NDJSON ohne Content-Length/Chunked
 * endet unter WebKit oft mit „Load failed“, obwohl die Log-Zeilen schon da
 * waren. logs[] kommt mit der Antwort und wird hier ins GUI-Log geschrieben.
 */
async function holeWalletExportSuche() {
  return api("/config/wallet-export-suchen", {
    methode: "POST",
    daten: {},
    timeoutMs: 60_000,
  });
}

async function starteWalletExportSuche() {
  const kasten = $("#sparrow-befund");
  const fund = $("#wallet-export-fund");
  const liste = $("#wallet-export-liste");
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(t("wallets.exportSearching")));
  }
  logZeile(t("wallets.exportSearching"));
  try {
    const antwort = await holeWalletExportSuche();
    _walletExportTreffer = antwort.wallets || [];
    for (const z of antwort.logs || []) {
      if (z) logZeile(String(z));
    }
    zeichneWalletExportListe(_walletExportTreffer);
    if (fund) fund.hidden = false;
    const n = _walletExportTreffer.length;
    const imp = Number(antwort.importable || 0);
    const text = n
      ? t("wallets.exportSearchDone", { n, imp })
      : t("wallets.exportSearchEmpty");
    if (kasten) kasten.replaceChildren(hinweisZeile(text));
    logZeile(`Wallet-Suche: ${text}`);
    aktualisiereWalletExportImportKnopf();
  } catch (fehler) {
    _walletExportTreffer = [];
    if (liste) liste.replaceChildren();
    if (fund) fund.hidden = true;
    if (kasten) {
      kasten.replaceChildren(
        hinweisZeile(fehler.message || t("wallets.exportFailed")),
      );
    }
    meldung(fehler.message || t("wallets.exportFailed"), "krit");
    aktualisiereWalletExportImportKnopf();
  }
}

function zeichneWalletExportListe(treffer) {
  const liste = $("#wallet-export-liste");
  if (!liste) return;
  liste.replaceChildren();
  // Server sortiert bereits: importierbar → locked, jeweils A–Z.
  // Client-seitig nochmals absichern.
  const sortiert = [...(treffer || [])].sort((a, b) => {
    const ai = a && a.importable ? 0 : 1;
    const bi = b && b.importable ? 0 : 1;
    if (ai !== bi) return ai - bi;
    const an = String((a && a.name) || "").toLowerCase();
    const bn = String((b && b.name) || "").toLowerCase();
    if (an < bn) return -1;
    if (an > bn) return 1;
    return 0;
  });
  for (const w of sortiert) {
    const zeile = document.createElement("div");
    zeile.className = "export-zeile";
    if (w.locked) zeile.classList.add("export-gesperrt");
    if (!w.importable) zeile.classList.add("export-blockiert");

    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = w.path || "";
    cb.disabled = !w.importable;
    cb.dataset.exportId = w.id || "";
    // Default unchecked: Nutzer wählt ausdrücklich, was importiert wird.
    cb.checked = false;
    cb.addEventListener("change", aktualisiereWalletExportImportKnopf);
    label.append(cb);

    const name = document.createElement("span");
    name.className = "export-name";
    name.textContent = w.name || w.path || "?";
    name.title = w.path || "";
    label.append(name);

    if (w.locked) {
      const lock = document.createElement("span");
      lock.className = "export-schloss";
      lock.textContent = "🔒";
      lock.title = t("wallets.exportLockTitle");
      label.append(lock);
    }

    if (w.reason && (!w.importable || w.locked)) {
      const grund = document.createElement("span");
      grund.className = "export-grund";
      grund.textContent = w.reason;
      grund.title = w.importable
        ? t("wallets.exportLockTitle")
        : t("wallets.exportBlockedTitle");
      label.append(grund);
    }

    // Herkunft rechtsbündig (Wasabi / Specter / Electrum / Core / …)
    const herkunft = document.createElement("span");
    herkunft.className = "export-herkunft";
    herkunft.textContent = w.origin_label
      || (w.app
        ? String(w.app).charAt(0).toUpperCase() + String(w.app).slice(1)
        : "");
    herkunft.title = w.path || herkunft.textContent || "";
    label.append(herkunft);

    zeile.append(label);
    liste.append(zeile);
  }
  aktualisiereWalletExportImportKnopf();
}

async function starteWalletExportImportAuswahl(bestaetigt = false) {
  const kasten = $("#sparrow-befund");
  const knopf = $("#sparrow-import");
  const pfade = walletExportGewaehltePfade();
  if (!pfade.length) {
    if (kasten) {
      kasten.hidden = false;
      kasten.replaceChildren(hinweisZeile(t("wallets.exportNoSelection")));
    }
    return;
  }
  if (knopf) knopf.disabled = true;
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(t("wallets.exportImporting")));
  }
  logZeile(t("ui.hard.ddad9af15b", { n: pfade.length }));
  try {
    const antwort = await api("/config/wallet-export-import-pfade", {
      methode: "POST",
      daten: { paths: pfade, confirm: bestaetigt },
      timeoutMs: 180_000,
    });
    await nachWalletExportErfolg(antwort);
    try {
      await starteWalletExportSuche();
    } catch (_) {
      /* Suche optional nachziehen */
    }
  } catch (fehler) {
    if (fehler && fehler.status === 409 && !bestaetigt) {
      const ok = window.confirm(
        `${fehler.message || ""}\n\n${t("wallets.saveAnyway")}?`,
      );
      if (ok) {
        if (knopf) knopf.disabled = false;
        await starteWalletExportImportAuswahl(true);
        return;
      }
    }
    const msg = (fehler && fehler.message) || t("wallets.exportFailed");
    if (kasten) {
      kasten.replaceChildren(hinweisZeile(msg));
    }
    meldung(msg, "krit");
    logZeile(`Wallet-Export: ${msg}`, true);
  } finally {
    if (knopf) knopf.disabled = false;
    aktualisiereWalletExportImportKnopf();
  }
}

/** Nach Import: alphabetisch erstes importiertes Wallet öffnen. */
async function wechsleZuImportiertemWallet(antwort) {
  let zielId = "";
  const liste = Array.isArray(antwort?.wallets) ? antwort.wallets : [];
  if (liste.length) {
    const sortiert = [...liste].sort((a, b) => {
      const an = String((a && a.name) || "").toLowerCase();
      const bn = String((b && b.name) || "").toLowerCase();
      if (an < bn) return -1;
      if (an > bn) return 1;
      return String((a && a.id) || "").localeCompare(String((b && b.id) || ""));
    });
    zielId = sortiert[0]?.id || "";
  }
  if (!zielId && antwort?.wallet_id) zielId = antwort.wallet_id;
  if (!zielId && Array.isArray(antwort?.wallet_ids) && antwort.wallet_ids[0]) {
    zielId = antwort.wallet_ids[0];
  }
  if (!zielId) return;
  // Config kann IDs frisch haben — Prefer Matching aus config.
  const cfg = (Zustand.config?.wallets || []).find((w) => w.id === zielId);
  if (!cfg && (Zustand.config?.wallets || []).length) {
    const names = new Set(
      liste.map((w) => String((w && w.name) || "").toLowerCase()).filter(Boolean),
    );
    const treffer = (Zustand.config.wallets || [])
      .filter((w) => names.has(String(w.name || "").toLowerCase()))
      .sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), undefined, { sensitivity: "base" }));
    if (treffer[0]?.id) zielId = treffer[0].id;
  }
  try {
    await zeigeWallet(zielId);
  } catch (fehler) {
    logZeile(
      `Wallet-Export: Wechsel zur Ansicht fehlgeschlagen — ${fehler.message || fehler}`,
      true,
    );
  }
}

async function nachWalletExportErfolg(antwort) {
  const kasten = $("#sparrow-befund");
  const fmt = antwort.format
    ? t("wallets.exportFormat", { format: antwort.format })
    : "";
  const teile = [
    antwort.already_present
      ? t("wallets.exportAlreadyPresent", { name: antwort.name || "", format: fmt })
      : t("wallets.exportSaved", { name: antwort.name || "", format: fmt }),
    t("wallets.exportCounts", {
      utxo: antwort.utxo_count || 0,
      verlauf: antwort.verlauf_count || 0,
    }),
  ];
  if (antwort.wallets_added > 1) {
    teile.push(`${antwort.wallets_added} Wallets`);
  }
  if (antwort.erste_adresse) {
    teile.push(t("wallets.exportFirstAddr", { addr: antwort.erste_adresse }));
  }
  for (const h of antwort.hinweise || []) {
    if (h) teile.push(String(h));
  }
  // Erfolg sofort sichtbar — Config-Reload darf die Meldung nicht blockieren.
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(teile.join(" · ")));
  }
  meldung(teile[0], "ok");
  const fmtLog = antwort.format ? ` · ${antwort.format}` : "";
  logZeile(
    `Wallet-Export${fmtLog}: ${antwort.name || "?"} · ${antwort.utxo_count || 0} UTXO · ${antwort.verlauf_count || 0} Tx`,
  );
  try {
    await ladeConfig();
    Zustand.entwurf = (Zustand.config?.wallets || []).map((w) => ({ ...w }));
    zeichneEinstellungen();
  } catch (fehler) {
    logZeile(
      `Wallet-Export: Import ok, Ansicht nicht aktualisiert — ${fehler.message || fehler}`,
      true,
    );
  }
  try {
    ladeCacheDashboard();
  } catch (_) {
    /* optional */
  }
  await ggfAdressenNachziehenNachExport(antwort);
  await wechsleZuImportiertemWallet(antwort);
}

/**
 * Nach Wallet-Export: Adressen per Electrs nachziehen.
 * ≤100 Tx automatisch, >100 mit Nachfrage.
 * Indexer konfiguriert aber noch nicht da (Tor): Job startet und wartet.
 * Ohne konfigurierten Indexer: klare Log-Zeile, kein stiller Abbruch.
 */
async function ggfAdressenNachziehenNachExport(antwort) {
  const meta = antwort && antwort.address_nachziehen;
  if (!meta) return;
  const n = Number(meta.pending_txids || 0);
  const name = meta.name || antwort.name || "?";
  if (n <= 0) return;

  const indexerDa = Boolean(meta.indexer_configured);
  if (!indexerDa) {
    logZeile(
      t("wallets.exportAddrNeedsIndexer", { name, n }),
      true,
    );
    return;
  }

  if (meta.needs_confirm) {
    logZeile(t("wallets.exportAddrAskLog", { name, n }));
    const ok = window.confirm(
      t("wallets.exportAddrConfirm", { name, n, max: meta.auto_max || 100 }),
    );
    if (!ok) {
      logZeile(t("wallets.exportAddrSkipped", { name, n }));
      return;
    }
  } else if (meta.auto_start) {
    if (!meta.electrs) {
      logZeile(t("wallets.exportAddrIndexerPending", { name, n }));
    } else {
      logZeile(t("wallets.exportAddrAutoLog", { name, n }));
    }
  } else {
    return;
  }

  try {
    // Job wartet intern auf Tor — API-Timeout länger als Bootstrap-Rest.
    const job = await api("/config/wallet-export-adressen-nachziehen", {
      methode: "POST",
      daten: { wallet_id: meta.wallet_id },
      timeoutMs: 60_000,
    });
    logZeile(
      t("wallets.exportAddrJobStarted", {
        name,
        n,
        id: (job && job.id) || "?",
      }),
    );
    if (job && job.id) {
      folgeExportAdressenJob(job.id, name, meta.wallet_id || antwort.wallet_id);
    }
  } catch (fehler) {
    const msg = (fehler && fehler.message) || String(fehler);
    logZeile(
      t("wallets.exportAddrJobFailed", { msg }),
      true,
    );
    if (/Indexer|Electrs|Fulcrum|Tor/i.test(msg)) {
      logZeile(t("wallets.exportAddrNeedsIndexer", { name, n }), true);
    }
  }
}

/** Job-Log „Adressen nachziehen“ in den GUI-Log-Bereich spiegeln. */
function folgeExportAdressenJob(jobId, walletName, walletId) {
  if (!jobId) return;
  if (!Zustand.exportAddrLogStand) {
    Zustand.exportAddrLogStand = { index: 0, knoten: [], texte: [] };
  }
  const stand = Zustand.exportAddrLogStand;
  // Neuer Job → Log-Stand zurücksetzen
  if (Zustand.exportAddrJob !== jobId) {
    stand.index = 0;
    stand.knoten = [];
    stand.texte = [];
    Zustand.exportAddrJob = jobId;
  }
  if (Zustand.exportAddrTimer) {
    clearInterval(Zustand.exportAddrTimer);
    Zustand.exportAddrTimer = null;
  }

  const tick = async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmLogZeilen(job, stand, walletName || "");
      if (job.running || job.status === "running" || job.status === "queued") {
        return;
      }
      clearInterval(Zustand.exportAddrTimer);
      Zustand.exportAddrTimer = null;
      Zustand.exportAddrJob = null;
      if (job.status === "done") {
        const st = job.result || {};
        const quelle = st.quelle === "cache"
          ? t("wallets.exportAddrQuelleCache")
          : st.quelle === "electrs-batch"
            ? t("wallets.exportAddrQuelleBatch")
            : st.quelle === "electrs"
              ? t("wallets.exportAddrQuelleElectrs")
              : "";
        logZeile(
          t("wallets.exportAddrJobDone", {
            name: walletName || "?",
            filled: st.filled || 0,
            failed: st.failed || 0,
          }) + (quelle ? ` · ${quelle}` : ""),
        );
        try {
          ladeCacheDashboard();
        } catch (_) {
          /* optional */
        }
        // Pille grün/gelb „importiert“ + Wallet-Ansicht aktualisieren.
        try {
          await ladeConfig();
          Zustand.entwurf = (Zustand.config?.wallets || []).map((w) => ({ ...w }));
          if (Zustand.ansicht === "wallets") {
            zeichneWalletVerwaltung();
          }
        } catch (_) {
          /* Config optional */
        }
        const wid = walletId || (job.meta && job.meta.wallet_id) || "";
        if (wid && Zustand.ansicht === "wallet" && Zustand.walletId === wid) {
          try {
            await zeigeWallet(wid, { ohneEmpfang: true });
          } catch (_) {
            /* Ansicht optional */
          }
        }
      } else if (job.status === "cancelled") {
        logZeile(t("wallets.exportAddrJobCancelled", { name: walletName || "?" }));
      } else if (job.error) {
        logZeile(
          t("wallets.exportAddrJobFailed", { msg: job.error }),
          true,
        );
      }
    } catch (fehler) {
      clearInterval(Zustand.exportAddrTimer);
      Zustand.exportAddrTimer = null;
      logZeile(
        t("wallets.exportAddrJobFailed", {
          msg: (fehler && fehler.message) || String(fehler),
        }),
        true,
      );
    }
  };
  tick();
  Zustand.exportAddrTimer = setInterval(tick, 900);
}

/** Wallet-Export-Dateien als Klartext lesen (kein Base64 — große CSVs frieren sonst ein). */
function dateiAlsText(datei) {
  return new Promise((resolve, reject) => {
    const maxBytes = 25 * 1024 * 1024;
    if (datei && typeof datei.size === "number" && datei.size > maxBytes) {
      reject(new Error(
        t("wallets.exportFileTooLarge", {
          name: datei.name || "?",
          mb: Math.ceil(datei.size / (1024 * 1024)),
        }),
      ));
      return;
    }
    const leser = new FileReader();
    leser.onload = () => resolve(String(leser.result || ""));
    leser.onerror = () => reject(new Error(t("common.fileUnreadable")));
    leser.readAsText(datei);
  });
}

async function dateienAlsTextImportPayload(dateiListe) {
  const files = [];
  for (const datei of dateiListe) {
    const text = await dateiAlsText(datei);
    files.push({ name: datei.name || "export", text });
  }
  return { files };
}

async function starteSparrowImport(dateiListe, bestaetigt = false) {
  const kasten = $("#sparrow-befund");
  const knopf = $("#sparrow-import");
  if (knopf) knopf.disabled = true;
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(t("wallets.exportImporting")));
  }
  const namen = (dateiListe || []).map((d) => d.name || "?").join(", ");
  logZeile(`Wallet-Export: lese ${dateiListe.length} Datei(en) — ${namen}`);
  try {
    let payload;
    try {
      payload = await dateienAlsTextImportPayload(dateiListe);
    } catch (fehler) {
      throw new Error(fehler.message || t("common.fileUnreadable"));
    }
    const files = (payload && payload.files) || [];
    if (!files.length) {
      throw new Error(t("wallets.exportNoFiles"));
    }
    logZeile(`Wallet-Export: sende ${files.length} Datei(en) an Server…`);
    const antwort = await api("/config/wallet-export-import", {
      methode: "POST",
      daten: { files, confirm: bestaetigt },
      timeoutMs: 180_000,
    });
    await nachWalletExportErfolg(antwort);
  } catch (fehler) {
    if (fehler && fehler.status === 409 && !bestaetigt) {
      const ok = window.confirm(
        `${fehler.message || ""}\n\n${t("wallets.saveAnyway")}?`,
      );
      if (ok) {
        if (knopf) knopf.disabled = false;
        await starteSparrowImport(dateiListe, true);
        return;
      }
    }
    const msg = (fehler && fehler.message) || t("wallets.exportFailed");
    if (kasten) {
      kasten.replaceChildren(hinweisZeile(msg));
    }
    meldung(msg, "krit");
    logZeile(`Wallet-Export: ${msg}`, true);
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

function uebernimmDeskriptor(treffer) {
  const nameFeld = $("#neuer-deskriptor-name");
  const name = (nameFeld && nameFeld.value.trim()) || "";
  const multisig = !!treffer.is_multisig;
  Zustand.entwurf.push({
    descriptor: treffer.descriptor,
    name,
    prefix: (treffer.xpubs_masked && treffer.xpubs_masked[0]
      ? String(treffer.xpubs_masked[0]).slice(0, 4)
      : treffer.script_type || "?"
    ).toLowerCase(),
    script_type: treffer.script_type,
    script_type_label: treffer.script_type_label,
    max_addresses: 50,
    read_only: false,
    origin: "descriptor",
    has_cache: false,
    utxo_count: 0,
    is_new: true,
    is_multisig: multisig,
    threshold: multisig ? treffer.threshold : null,
    cosigner_count: treffer.cosigner_count,
    xpubs_masked: treffer.xpubs_masked,
    xpub_masked: (!multisig && treffer.xpubs_masked && treffer.xpubs_masked[0])
      || "",
  });
  if (nameFeld) nameFeld.value = "";
  zeichneEinstellungen();
  // Sofort in die .env — kein zweiter Klick unten.
  speichereWallets(false);
}

function fuegeWalletHinzu() {
  const feld = $("#neuer-xpub");
  const nameFeld = $("#neuer-name");
  const xpub = feld.value.trim();
  if (!xpub) return;
  const name = (nameFeld && nameFeld.value.trim()) || "";

  // Wasabi WPKH-Policy / Output-Deskriptor versehentlich im XPUB-Feld:
  // denselben Importweg nutzen wie beim Deskriptor-Kasten.
  // RegExp als String: ein Literal mit `\(` würde die Klammerbilanz der
  // statischen JS-Prüfung (ohne Regex-Literale) falsch negativ machen.
  if (new RegExp("\\b(sh|wsh|tr|wpkh|pkh|combo)\\s*\\(", "i").test(xpub)) {
    const deskFeld = $("#neuer-deskriptor");
    const deskName = $("#neuer-deskriptor-name");
    if (deskFeld) deskFeld.value = xpub;
    if (deskName && name) deskName.value = name;
    feld.value = "";
    if (nameFeld) nameFeld.value = "";
    pruefeDeskriptor();
    return;
  }

  Zustand.entwurf.push({
    xpub,
    xpub_voll: xpub,
    xpub_masked: xpub,
    name,
    prefix: xpub.slice(0, 4).toLowerCase(),
    script_type: "auto",
    max_addresses: 50,
    read_only: false,
    origin: "xpub",
    has_cache: false,
    utxo_count: 0,
    is_new: true,
  });
  feld.value = "";
  if (nameFeld) nameFeld.value = "";
  zeichneEinstellungen();
  // Sofort speichern: „Hinzufügen“ heißt hinzufügen, nicht vormerken.
  speichereWallets(false);
}

// ---------------------------------------------------------------------------
// Einrichtung
// ---------------------------------------------------------------------------

/** Merker, dass der Hinweis schon einmal gezeigt wurde — er soll nicht nerven. */
const EINRICHTUNG_MERKER = "xpq-einrichtung-gesehen";

/**
 * Die drei Dinge, ohne die das Werkzeug nichts oder nur wenig zeigen kann.
 *
 * Der Stand wird aus der Konfiguration abgeleitet, nicht gespeichert: Wer
 * etwas in der .env von Hand einträgt, sieht es hier sofort als erledigt.
 */
function einrichtungsSchritte(config) {
  const wallets = config?.wallets || [];
  const electrum = (config?.sources || []).find((q) => q.key === "own_fulcrum");
  const core = (config?.sources || []).find((q) => q.key === "own_core");
  const mempool = config?.mempool || {};

  return [
    {
      titel: t("setup.step.wallets"),
      erledigt: wallets.length > 0,
      stand: wallets.length
        ? t("setup.step.walletsStand", { n: wallets.length })
        : t("setup.step.walletsNone"),
      text: t("setup.step.walletsText"),
    },
    {
      titel: t("setup.step.electrum"),
      erledigt: Boolean(electrum?.configured),
      stand: electrum?.configured ? electrum.detail : t("setup.step.notSet"),
      text: t("setup.step.electrumText"),
    },
    {
      titel: t("setup.step.core"),
      erledigt: Boolean(core?.configured),
      stand: core?.configured ? core.detail : t("setup.step.notSet"),
      text: t("setup.step.coreText"),
    },
    {
      titel: t("setup.step.explorer"),
      erledigt: Boolean(mempool.configured),
      stand: mempool.configured ? mempool.host : t("setup.step.notSet"),
      text: t("setup.step.explorerText"),
    },
  ];
}

function zeichneEinrichtung() {
  const liste = $("#einrichtung-schritte");
  liste.replaceChildren();

  for (const schritt of einrichtungsSchritte(Zustand.config)) {
    const punkt = document.createElement("li");
    punkt.className = schritt.erledigt ? "schritt erledigt" : "schritt offen";

    const kopf = document.createElement("div");
    kopf.className = "schritt-kopf";
    const titel = document.createElement("strong");
    titel.textContent = schritt.titel;
    kopf.append(titel, pille(schritt.erledigt ? "gut" : "warn", schritt.stand));

    const text = document.createElement("p");
    text.className = "schritt-text";
    text.textContent = schritt.text;

    punkt.append(kopf, text);
    liste.append(punkt);
  }

  setzeText($("#einrichtung-pfad"), Zustand.config?.env_path || ".env");
  fuellOnchainHinweisTexte();
}

function onchainHinweisSichtbar() {
  return !Boolean(Zustand.config?.hinweis_onchain_bestaetigt)
      && !Zustand.onchainHinweisSitzungWeg;
}

/** Kanonischen Absatz in Dialog, Steuerjahr und Fristen halten. */
function fuellOnchainHinweisTexte() {
  const text = (Zustand.config && Zustand.config.hinweis_onchain) || "";
  if (!text) return;
  setzeText($("#einrichtung-onchain-text"), text);
  setzeText($("#steuer-onchain-hinweis"), text);
  setzeText($("#frist-onchain-hinweis"), text);
}

function einrichtungNochOffen() {
  let gesehen = false;
  try {
    gesehen = localStorage.getItem(EINRICHTUNG_MERKER) === "1";
  } catch (_) {
    /* siehe schliesseEinrichtung */
  }
  if (gesehen) return false;
  return einrichtungsSchritte(Zustand.config).some((s) => !s.erledigt);
}

async function merkeOnchainHinweisWennGewuenscht() {
  const box = $("#einrichtung-onchain-nicht-nochmal");
  if (!box || !box.checked) return false;
  if (Zustand.config?.hinweis_onchain_bestaetigt) return true;
  try {
    const ergebnis = await api("/config/hinweis-onchain", {
      methode: "PUT",
      daten: { bestaetigt: true },
    });
    if (Zustand.config) {
      Zustand.config.hinweis_onchain_bestaetigt =
        Boolean(ergebnis.hinweis_onchain_bestaetigt);
    }
    return true;
  } catch (fehler) {
    meldung(t("ui.hard.433c6a7fc6", { msg: fehler.message }), "krit");
    return false;
  }
}

function zeigeOnchainHinweis() {
  fuellOnchainHinweisTexte();
  const overlay = $("#onchain-hinweis");
  if (!overlay) return;
  overlay.hidden = false;
  const ok = $("#einrichtung-onchain-ok");
  if (ok) ok.focus();
}

function schliesseOnchainHinweis() {
  const overlay = $("#onchain-hinweis");
  if (overlay) overlay.hidden = true;
}

/**
 * OK auf dem On-Chain-Dialog: optional dauerhaft merken, dann ggf. die
 * eigentliche Einrichtung — nie beides gleichzeitig.
 */
async function bestaetigeOnchainHinweis() {
  await merkeOnchainHinweisWennGewuenscht();
  Zustand.onchainHinweisSitzungWeg = true;
  schliesseOnchainHinweis();
  if (einrichtungNochOffen()) zeigeEinrichtung();
}

function zeigeEinrichtung() {
  zeichneEinrichtung();
  $("#einrichtung").hidden = false;
}

function schliesseEinrichtung() {
  $("#einrichtung").hidden = true;
  try {
    localStorage.setItem(EINRICHTUNG_MERKER, "1");
  } catch (_) {
    /* Ohne localStorage erscheint der Hinweis eben erneut — kein Grund zu scheitern. */
  }
}

/**
 * Beim ersten Start nacheinander: zuerst On-Chain-Hinweis (eigener Dialog),
 * danach die Einrichtung, falls noch etwas fehlt.
 *
 * „Erster Start" der Einrichtung: Der Hinweis wurde in diesem Browser noch nie
 * weggeklickt und es fehlt noch etwas. Ist alles eingerichtet, gibt es nichts
 * zu sagen; wer den Block-Explorer bewusst weglässt, wird nicht erneut gefragt.
 *
 * Der On-Chain-Absatz ist unabhängig: solange er auf dieser Installation nicht
 * bestätigt wurde, kommt sein Dialog noch einmal — allein, nicht oben auf der
 * Einrichtung.
 */
function einrichtungBeimStart() {
  if (onchainHinweisSichtbar()) {
    zeigeOnchainHinweis();
    return;
  }
  if (einrichtungNochOffen()) zeigeEinrichtung();
}

// ---------------------------------------------------------------------------
// Laden
// ---------------------------------------------------------------------------

function autoQuelle(quellen) {
  const auto = new Set([
    "own_fulcrum", "own_core", "bip158", "public_onion", "clearnet",
  ]);
  return (quellen || []).find((q) => q.configured && auto.has(q.key)) || null;
}

function eigenerNode(quellen) {
  const liste = quellen || [];
  const eigene = ["own_fulcrum", "own_core"]
    .map((key) => liste.find((q) => q.key === key))
    .filter((q) => q && q.configured);
  const verbunden = eigene.find((q) => q.reachable === true);
  if (verbunden) return verbunden;
  return eigene[0] || null;
}

function peerStatusAusQuellen(quellen, apiStand) {
  if (apiStand && apiStand.label) {
    return {
      n: apiStand.count || 0,
      kind: apiStand.kind || "none",
      label: apiStand.label,
      peers: apiStand.peers || [],
      gut: (apiStand.count || 0) > 0,
      software: apiStand.software || "",
    };
  }
  const nach = {};
  for (const q of quellen || []) nach[q.key] = q;
  const own = nach.own_fulcrum;
  const core = nach.own_core;
  const p2p = nach.bip158;
  const peersN = p2p?.peer_count || 0;
  const electrsN = own && own.reachable ? 1 : 0;
  const electrumName = String(own?.software || "").trim();

  if (peersN > 0 || electrsN > 0) {
    const hosts = [];
    if (peersN > 0) hosts.push(...(p2p.peer_hosts || []));
    if (electrsN > 0) hosts.push(...(own.peer_hosts || []));
    let kind = "p2p";
    if (peersN > 0 && electrsN > 0) kind = "mixed";
    else if (electrsN > 0) kind = "own";
    return {
      n: peersN + electrsN,
      kind,
      label: verbindungLabel({ peersN, electrsN, electrumName }),
      peers: hosts,
      peers_n: peersN,
      electrs_n: electrsN,
      software: electrumName,
      gut: true,
    };
  }
  if (core && core.reachable) {
    return {
      n: 1,
      kind: "own",
      label: "Eigener Peer verbunden",
      peers: core.peer_hosts || [],
      peers_n: 0,
      electrs_n: 0,
      gut: true,
    };
  }
  const onionN = nach.public_onion?.peer_count || 0;
  const clearN = nach.clearnet?.peer_count || 0;
  const pub = onionN + clearN;
  if (pub > 0) {
    const hosts = [
      ...(nach.public_onion?.peer_hosts || []),
      ...(nach.clearnet?.peer_hosts || []),
    ];
    return {
      n: pub,
      kind: "public",
      label: oeffentlicheElectrumLabel(onionN, clearN),
      peers: hosts,
      onion_electrs: onionN,
      clearnet_electrs: clearN,
      peers_n: 0,
      electrs_n: 0,
      gut: true,
    };
  }
  return {
    n: 0, kind: "none", label: "0 Peers verbunden", peers: [],
    peers_n: 0, electrs_n: 0, gut: false,
  };
}

/** Peers (BIP-158) + eigener Indexer nebeneinander. */
function verbindungLabel({
  peersN = 0, electrsN = 0, onionN = 0, clearN = 0, electrumName = "",
} = {}) {
  const teile = [];
  if (peersN > 0) teile.push(peersN === 1 ? "1 Peer" : `${peersN} Peers`);
  if (electrsN > 0) {
    const name = String(electrumName || "").trim() || "electrs";
    teile.push(electrsN === 1 ? `1 ${name}` : `${electrsN} ${name}`);
  }
  if (onionN > 0) teile.push(`${onionN} onion-electrs`);
  if (clearN > 0) teile.push(`${clearN} clearnet-electrs`);
  if (!teile.length) return "0 Peers verbunden";
  return `${teile.join(" · ")} verbunden`;
}

/** Öffentliche Electrum: onion-electrs / clearnet-electrs — nicht „Peers“. */
function oeffentlicheElectrumLabel(onionN, clearN) {
  const teile = [];
  if (onionN > 0) teile.push(`${onionN} onion-electrs`);
  if (clearN > 0) teile.push(`${clearN} clearnet-electrs`);
  if (!teile.length) return "0 electrs verbunden";
  return `${teile.join(" · ")} verbunden`;
}

function peerAenderungen(alt, neu) {
  if (!alt) return [];
  const altLabel = alt.label || "0 Peers verbunden";
  const neuLabel = neu.label || "0 Peers verbunden";
  if (altLabel !== neuLabel) {
    if (alt.n || neu.n) return [`Wechsel: ${altLabel} → ${neuLabel}`];
    return [];
  }
  // P2P/public/mixed: Host-Probe rotiert — kein Spam.
  if (alt.kind === "p2p" || alt.kind === "public" || alt.kind === "mixed") {
    return [];
  }
  const vorher = new Set(alt.peers || []);
  const nachher = new Set(neu.peers || []);
  const zeilen = [];
  for (const altHost of [...vorher].sort()) {
    if (!nachher.has(altHost)) zeilen.push(`Peer ${altHost} ausgefallen.`);
  }
  for (const neuHost of [...nachher].sort()) {
    if (!vorher.has(neuHost)) zeilen.push(`Neuer Peer ${neuHost}.`);
  }
  return zeilen;
}

/** Während eines UTXO-Scans: keine Host-Liste, nur Wechsel und < 3 Peers/electrs. */
function peerAenderungenFuerLog(alt, neu, scanLaeuft) {
  const roh = peerAenderungen(alt, neu);
  if (!scanLaeuft) return roh;
  const zeilen = roh.filter((z) => z.startsWith("Wechsel:"));
  if (neu.n < 3 && alt.n !== neu.n) {
    if (neu.kind === "public") {
      // Label schon „n onion-electrs · m clearnet-electrs verbunden“
      zeilen.push(`Nur ${neu.label}.`);
    } else {
      const wort = neu.n === 1 ? "Peer" : "Peers";
      zeilen.push(`Nur ${neu.n} ${wort} verbunden.`);
    }
  }
  return zeilen;
}

/** Normal: alle 30 s. Mit Electrs+Core: alle 10 Min (≈ Blockintervall). */
const PEER_TAKT_MS = 30_000;
const PEER_TAKT_RUHE_MS = 10 * 60_000;

function eigeneNodesBeideErreichbar(quellen) {
  const nach = {};
  for (const q of quellen || []) nach[q.key] = q;
  return (
    nach.own_fulcrum?.reachable === true &&
    nach.own_core?.reachable === true
  );
}

function peerTaktMs(quellen) {
  // Live-Peers während Scan kommen aus Job-Poll — kein 4s-Vollcheck
  // (der sonst Header-Tip-Jobs und Log-Spam auslöst).
  return eigeneNodesBeideErreichbar(quellen) ? PEER_TAKT_RUHE_MS : PEER_TAKT_MS;
}

/**
 * Live-Peers aus Job/Config in die BIP-158-Quelle und Kopf-Pille schreiben.
 * Ohne Netzprobe — die Connections hält der Scan bereits.
 *
 * @param {{ setzeStatus?: boolean }} opts  setzeStatus=false: nur Quellen/Pille,
 *   peerStatus setzt der Aufrufer (nimmPeerStand) — sonst überschreibt die
 *   kurze Tor-Probe (oft 2 Peers) den Live-Stand und erzeugt „Wechsel: 2 → N“.
 */
function nimmLiveP2pPeers(hosts, opts = {}) {
  const setzeStatus = opts.setzeStatus !== false;
  const liste = Array.isArray(hosts)
    ? hosts.map((h) => String(h || "").trim()).filter(Boolean)
    : [];
  const uniq = [...new Set(liste)];
  Zustand.liveP2pPeers = uniq;
  if (!Zustand.config) return;
  const sources = (Zustand.config.sources || []).map((q) => {
    if (q.key !== "bip158") return q;
    if (!uniq.length) {
      // Scan vorbei: Live-Markierung fallen lassen, Check-Stand behalten.
      return q;
    }
    // Nur aktuelle Live-Hosts — nicht unbegrenzt mit alten Probe-Hosts mergen.
    return {
      ...q,
      reachable: true,
      peer_count: uniq.length,
      peer_hosts: uniq,
      error: "",
    };
  });
  Zustand.config.sources = sources;
  if (uniq.length && setzeStatus) {
    // Volle Formel: Peers + electrs, nicht nur P2P (sonst „→ onion-electrs“-Quatsch).
    const stand = peerStatusAusQuellen(Zustand.config.sources);
    Zustand.peerStatus = stand;
    Zustand.peers = stand.n;
    Zustand.peerLabel = stand.label;
    Zustand.peersGeprueft = true;
  }
  zeichneKopfStatus(sources);
  // Peer-Takt nicht anfassen — Live-Update braucht keinen kürzeren Netzcheck.
}

function setzePeerTakt(quellen) {
  const ms = peerTaktMs(quellen);
  if (Zustand.peerTakt && Zustand.peerTaktMs === ms) return;
  if (Zustand.peerTakt) {
    clearInterval(Zustand.peerTakt);
    Zustand.peerTakt = null;
  }
  Zustand.peerTaktMs = ms;
  Zustand.peerTakt = setInterval(pruefePeersLeise, ms);
}

/** @deprecated Name bleibt für Tests; startet bzw. passt den Takt an. */
function startePeerTakt(quellen) {
  setzePeerTakt(quellen || Zustand.config?.sources);
}

async function pruefePeersLeise() {
  if (Zustand.peerCheckLaeuft) return;
  Zustand.peerCheckLaeuft = true;
  try {
    const ergebnis = await apiSourceCheck({ still: true });
    nimmPeerStand(ergebnis, true);
  } catch (_) {
    /* letzter Stand bleibt */
  } finally {
    Zustand.peerCheckLaeuft = false;
  }
}

/**
 * /config liefert Quellen ohne Live-Check (reachable: null). Nach einem Scan
 * würde zeichneKopfStatus die Pillen sonst kurz rot malen, bis der nächste
 * Peer-Takt wieder grün setzt. Bekannten Stand mitnehmen.
 *
 * Während eines UTXO-Scans kann Core (scantxoutset) den RPC kurz blockieren —
 * ein paralleler Check meldet dann fälschlich „nicht erreichbar“. Den letzten
 * positiven Stand behalten, bis der Scan durch ist.
 */
function uebernehmeQuellenErreichbarkeit(altListe, neuListe, {
  behaltePositivBeiNegativ = false,
} = {}) {
  if (!Array.isArray(neuListe) || !neuListe.length) return neuListe || [];
  if (!Array.isArray(altListe) || !altListe.length) return neuListe;
  const altNach = Object.create(null);
  for (const q of altListe) {
    if (q && q.key) altNach[q.key] = q;
  }
  return neuListe.map((neu) => {
    const alt = altNach[neu.key];
    if (!alt) return neu;
    // .env gelöscht / Host geleert: kein alter „verbunden“-Stand behalten.
    if (!neu.configured) {
      if (
        neu.reachable == null
        && alt.reachable == null
        && !(alt.peer_count > 0)
      ) {
        return neu;
      }
      return {
        ...neu,
        reachable: null,
        error: "",
        peer_count: 0,
        peer_hosts: [],
      };
    }
    if (neu.reachable == null) {
      if (alt.reachable == null && !(alt.peer_count > 0)) return neu;
      return {
        ...neu,
        reachable: alt.reachable,
        error: neu.error || alt.error || "",
        peer_count: neu.peer_count || alt.peer_count || 0,
        peer_hosts:
          (neu.peer_hosts && neu.peer_hosts.length)
            ? neu.peer_hosts
            : (alt.peer_hosts || []),
        software: neu.software || alt.software || "",
        software_raw: neu.software_raw || alt.software_raw || "",
        detail: neu.detail || alt.detail || "",
      };
    }
    if (
      behaltePositivBeiNegativ
      && neu.reachable === false
      && alt.reachable === true
    ) {
      return {
        ...neu,
        reachable: true,
        error: "",
        peer_count: alt.peer_count || neu.peer_count || 0,
        peer_hosts:
          (alt.peer_hosts && alt.peer_hosts.length)
            ? alt.peer_hosts
            : (neu.peer_hosts || []),
        software: alt.software || neu.software || "",
        software_raw: alt.software_raw || neu.software_raw || "",
        detail: alt.detail || neu.detail || "",
      };
    }
    // Software vom älteren Stand behalten, wenn der neue Check sie weglässt.
    if (
      neu.reachable === true
      && !String(neu.software || "").trim()
      && String(alt.software || "").trim()
    ) {
      return {
        ...neu,
        software: alt.software,
        software_raw: alt.software_raw || neu.software_raw || "",
      };
    }
    return neu;
  });
}

/** Welche Kopf-Pillen nach Speichern einer Quelle neu verbunden werden müssen. */
function quellenPendingKeysNachSave(quelleKey) {
  if (quelleKey === "own_fulcrum") return ["own_fulcrum"];
  if (quelleKey === "own_core") return ["own_core"];
  if (quelleKey === "own_utxo_core") return ["own_utxo_core"];
  return [];
}

/**
 * Nach „Übernehmen“: betroffene Pillen sofort grau (pending), ohne alten
 * reachable/software-Stand. Farbe + Name erst nach erfolgreichem Check.
 */
function setzeQuellenPending(keys) {
  const keyset = new Set(
    (Array.isArray(keys) ? keys : [keys]).map((k) => String(k || "")).filter(Boolean),
  );
  if (!keyset.size || !Zustand.config) return;
  Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
    if (!q || !keyset.has(q.key) || !q.configured) return q;
    return {
      ...q,
      reachable: null,
      error: "",
      peer_count: 0,
      peer_hosts: [],
      software: "",
      software_raw: "",
    };
  });
  // Noch kein frischer Check — Aufbau (grau), nicht Fehler (rot).
  Zustand.peersGeprueft = false;
  Zustand.peerCheckLaeuft = true;
  const stand = peerStatusAusQuellen(Zustand.config.sources);
  Zustand.peerStatus = stand;
  Zustand.peers = stand.n;
  Zustand.peerLabel = stand.label;
  zeichneKopfStatus(Zustand.config.sources);
}

/**
 * Eigener Indexer schon in Nutzung (Tip-Sync/Empfang) → Pille sofort grün.
 * Kommt aus Job-Meta oder sources_last, nicht erst vom 30‑s-Peer-Takt.
 */
function nimmOwnFulcrumStand(info) {
  if (!info || !Zustand.config) return;
  const soft = String(info.software || "").trim();
  const softRaw = String(info.software_raw || "").trim();
  const hosts = Array.isArray(info.peer_hosts)
    ? info.peer_hosts.map((h) => String(h || "").trim()).filter(Boolean)
    : [];
  Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
    if (q.key !== "own_fulcrum" || !q.configured) return q;
    return {
      ...q,
      reachable: info.reachable === false ? false : true,
      error: info.reachable === false ? String(info.error || q.error || "") : "",
      peer_count: Number(info.peer_count || hosts.length || 1),
      peer_hosts: hosts.length ? hosts : (q.peer_hosts || []),
      software: soft || q.software || "",
      software_raw: softRaw || q.software_raw || "",
      detail: String(info.detail || q.detail || ""),
    };
  });
  Zustand.peersGeprueft = true;
  const stand = peerStatusAusQuellen(Zustand.config.sources);
  Zustand.peerStatus = stand;
  Zustand.peers = stand.n;
  Zustand.peerLabel = stand.label;
  zeichneKopfStatus(Zustand.config.sources);
  setzePeerTakt(Zustand.config.sources);
}

function nimmPeerStand(ergebnis, still) {
  const altStand = Zustand.peerStatus;
  const quellen = uebernehmeQuellenErreichbarkeit(
    Zustand.config?.sources,
    ergebnis.sources || [],
    { behaltePositivBeiNegativ: Boolean(Zustand.rescanJob) },
  );
  if (Zustand.config) {
    Zustand.config.sources = quellen;
    if (ergebnis.header_job_id) {
      Zustand.config.header_job_id = ergebnis.header_job_id;
    }
    if (ergebnis.header_tip != null) {
      Zustand.config.header_tip = ergebnis.header_tip;
    }
  }
  const liveHosts = Array.isArray(ergebnis.live_p2p_peers)
    ? [...new Set(
      ergebnis.live_p2p_peers.map((h) => String(h || "").trim()).filter(Boolean),
    )]
    : [];
  if (liveHosts.length) {
    // Quellen aktualisieren, peerStatus noch nicht — sonst steht der Vergleich
    // immer auf der kurzen Live-/Tor-Probe (oft 2) statt dem letzten Stand.
    nimmLiveP2pPeers(liveHosts, { setzeStatus: false });
  }
  let stand = peerStatusAusQuellen(
    Zustand.config?.sources || quellen,
    ergebnis.peer_status,
  );
  // Aktive Filter-Peers des Scans schlagen die Erreichbarkeits-Probe
  // (Probe über Tor oft max. 2, Scan-Pool kann anders zählen).
  if (liveHosts.length && (Zustand.rescanJob || stand.kind === "p2p" || stand.kind === "none")) {
    stand = {
      n: liveHosts.length,
      kind: "p2p",
      label:
        liveHosts.length === 1
          ? "1 Peer verbunden"
          : `${liveHosts.length} Peers verbunden`,
      peers: liveHosts,
      gut: true,
    };
  }
  const ruhig = eigeneNodesBeideErreichbar(ergebnis.sources);
  // Bei Electrs+Core kein Log über ausfallende P2P-/Wechsel-Peers —
  // der stille Takt reicht alle 10 Min für den Header-Tip.
  if (still && altStand && !ruhig) {
    const scanLaeuft = Boolean(Zustand.rescanJob);
    for (const zeile of peerAenderungenFuerLog(altStand, stand, scanLaeuft)) {
      logZeile(zeile, true);
    }
  }
  Zustand.peerStatus = stand;
  Zustand.peers = stand.n;
  Zustand.peerLabel = stand.label;
  Zustand.peersGeprueft = true;
  zeichneKopfStatus(Zustand.config?.sources || quellen);
  aktualisiereDatenquellenNav();
  const liste = $("#quellen-liste");
  if (liste && liste.childElementCount) {
    zeichneQuellen(Zustand.config?.sources || quellen);
  }
  setzePeerTakt(Zustand.config?.sources || quellen);
  if (
    !still &&
    ergebnis.peer_status &&
    ergebnis.peer_status.braucht_oeffentliche &&
    !Zustand.oeffentlicheGefragt
  ) {
    frageOeffentlicheElectrum();
  }
  if (ergebnis.header_job_id) folgeHeaderJob();
  return stand;
}

function frageOeffentlicheElectrum() {
  Zustand.oeffentlicheGefragt = true;
  const overlay = $("#oeffentliche-electrum-warnung");
  if (!overlay) return;
  logZeile(t("ui.hard.6665b8b4e2"));
  overlay.hidden = false;
  const nein = $("#oeffentliche-electrum-nein");
  if (nein) nein.focus();
}

async function lehneOeffentlicheElectrumAb() {
  const overlay = $("#oeffentliche-electrum-warnung");
  if (overlay) overlay.hidden = true;
  logZeile(t("ui.hard.d3aa220782"));
  try {
    await api("/source/oeffentlich", {
      methode: "POST",
      daten: { erlauben: false },
    });
    if (Zustand.config) {
      Zustand.config.oeffentliche_electrum = false;
      Zustand.config.oeffentliche_electrum_session = false;
    }
  } catch (fehler) {
    logZeile(t("ui.hard.57a8b6a5d2", { msg: fehler.message }), true);
  }
}

async function erlaubeOeffentlicheElectrum() {
  const overlay = $("#oeffentliche-electrum-warnung");
  if (overlay) overlay.hidden = true;
  logZeile(
    t("ui.hard.81909b08fe"),
  );
  try {
    await api("/source/oeffentlich", {
      methode: "POST",
      daten: { erlauben: true },
    });
    if (Zustand.config) {
      Zustand.config.oeffentliche_electrum = true;
      Zustand.config.oeffentliche_electrum_session = true;
    }
    await testeEigenenNode();
  } catch (fehler) {
    Zustand.oeffentlicheGefragt = false;
    logZeile(t("ui.hard.57a8b6a5d2", { msg: fehler.message }), true);
  }
}

function oeffentlicheElectrumNochAktiv() {
  if (Zustand.config?.oeffentliche_electrum) return true;
  const liste = Zustand.config?.sources || [];
  return liste.some(
    (q) =>
      q
      && (q.key === "public_onion" || q.key === "clearnet")
      && q.configured
      && (q.reachable === true || (q.peer_count || 0) > 0),
  );
}

function p2pQuelleVerbunden() {
  const p2p = (Zustand.config?.sources || []).find((q) => q && q.key === "bip158");
  return Boolean(
    p2p
    && p2p.configured
    && (p2p.reachable === true || (p2p.peer_count || 0) > 0),
  );
}

/**
 * Nach P2P-Aktivierung: optional öffentliche Electrum-Nutzung kappen.
 * @returns {Promise<"kappen"|"behalten"|undefined>}
 */
function frageP2pPrivatsphaereKappen() {
  return new Promise((resolve) => {
    const dlg = $("#p2p-privatsphaere-dialog");
    if (!dlg) {
      resolve(undefined);
      return;
    }
    const ja = $("#p2p-privatsphaere-ja");
    const nein = $("#p2p-privatsphaere-nein");
    dlg.hidden = false;
    if (ja) ja.focus();

    const fertig = async (wahl) => {
      ja?.removeEventListener("click", onJa);
      nein?.removeEventListener("click", onNein);
      dlg.removeEventListener("keydown", onTaste);
      dlg.hidden = true;
      if (wahl === "kappen") {
        try {
          await api("/source/oeffentlich", {
            methode: "POST",
            daten: { erlauben: false },
          });
          if (Zustand.config) Zustand.config.oeffentliche_electrum = false;
          Zustand.peerCheckLaeuft = false;
          // Stale „verbunden“/„im Aufbau“ an Onion/Clearnet entfernen.
          Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
            if (q.key !== "public_onion" && q.key !== "clearnet") return q;
            return {
              ...q,
              reachable: null,
              peer_count: 0,
              peer_hosts: [],
            };
          });
          zeichneDatenquellenAnsicht();
          zeichneKopfStatus(Zustand.config.sources);
          logZeile(t("ui.hard.667be59b8a"));
          meldung(t("sources.publicCut"), "gut");
        } catch (fehler) {
          logZeile(t("ui.hard.741faf4a73", { msg: fehler.message }), true);
          meldung(fehler.message, "krit");
        }
      } else if (wahl === "behalten") {
        logZeile(t("ui.hard.d8ecdd15d4"));
      }
      resolve(wahl);
    };
    const onJa = () => fertig("kappen");
    const onNein = () => fertig("behalten");
    const onTaste = (ev) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        onNein();
      }
      if (ev.key === "Enter") {
        ev.preventDefault();
        onJa();
      }
    };
    ja?.addEventListener("click", onJa);
    nein?.addEventListener("click", onNein);
    dlg.addEventListener("keydown", onTaste);
  });
}

/**
 * Kopfzeile: nur aktive/im Aufbau/fehlerhafte Quellen + eine Privatsphäre-Pille.
 * Kein Katalog ungenutzter Quellen. Cache-only → Privatsphäre hoch.
 */
function kopfQuelleVerbunden(quelle) {
  if (!quelle || !quelle.configured) return false;
  if (quelle.reachable === true) return true;
  return (quelle.peer_count || 0) > 0;
}

/** konfiguriert, noch kein Check → Aufbau; nach Check unerreichbar → Fehler. */
function kopfQuelleAufbau(quelle) {
  if (!quelle || !quelle.configured) return false;
  if (kopfQuelleVerbunden(quelle)) return false;
  if (quelle.reachable === false) return false;
  return !Zustand.peersGeprueft || quelle.reachable == null;
}

function kopfQuelleFehler(quelle) {
  return Boolean(
    quelle
    && quelle.configured
    && !kopfQuelleVerbunden(quelle)
    && Zustand.peersGeprueft
    && quelle.reachable === false,
  );
}

function zeichneKopfStatus(quellen) {
  const nach = {};
  for (const q of quellen || []) nach[q.key] = q;

  const core = nach.own_core;
  const electrs = nach.own_fulcrum;
  const p2p = nach.bip158;
  const oeffentlichOnion = nach.public_onion;
  const oeffentlichClear = nach.clearnet;

  const coreVerbunden = kopfQuelleVerbunden(core);
  const electrsVerbunden = kopfQuelleVerbunden(electrs);
  const liveN = Array.isArray(Zustand.liveP2pPeers)
    ? Zustand.liveP2pPeers.length
    : 0;
  let p2pAnzahl = Math.max(
    Number(p2p?.peer_count || 0),
    liveN,
  );
  if (
    !p2pAnzahl
    && Zustand.peerStatus
    && Zustand.peerStatus.kind === "p2p"
  ) {
    p2pAnzahl = Number(Zustand.peerStatus.n || Zustand.peers || 0);
  }
  const p2pAktiv =
    (Zustand.peerStatus && Zustand.peerStatus.kind === "p2p")
    || liveN > 0;
  const p2pVerbunden = p2pAnzahl > 0 || p2pAktiv;
  const p2pAufbau =
    Boolean(p2p?.configured)
    && !p2pVerbunden
    && (!Zustand.peersGeprueft || Zustand.peerCheckLaeuft);
  const oeffentlichVerbunden =
    kopfQuelleVerbunden(oeffentlichOnion)
    || kopfQuelleVerbunden(oeffentlichClear)
    || (Zustand.peerStatus && Zustand.peerStatus.kind === "public");

  const p2pHosts = [
    ...new Set([
      ...(p2p?.peer_hosts || []),
      ...(Zustand.liveP2pPeers || []),
    ]),
  ];
  const p2pTitle =
    (liveN > 0
      ? t("ui.hard.30afd7b333", { n: liveN }) + " "
      : "")
    + "Bitcoin-P2P mit BIP-158 Compact Filters. "
    + (p2pHosts.length ? p2pHosts.slice(0, 6).join(", ") : "");

  const eintraege = [];

  if (coreVerbunden || kopfQuelleAufbau(core) || kopfQuelleFehler(core)) {
    // Wie Indexer: Aufbau grau, erst nach Connect grün — kein Gelb-Flash.
    eintraege.push({
      key: "own_core",
      lern: "core",
      label: t("header.sourceCore"),
      stufe: coreVerbunden
        ? "gut"
        : (kopfQuelleAufbau(core) ? "neutral" : "krit"),
      title: core?.error
        || t("header.sourceCoreTitle"),
    });
  }

  if (p2pVerbunden || p2pAufbau) {
    const n = p2pVerbunden ? p2pAnzahl : 0;
    eintraege.push({
      key: "bip158",
      lern: "p2p",
      label: t("header.p2pPeers", { n }),
      stufe: p2pAufbau
        ? "warn"
        : (p2pAnzahl > 2 ? "gut" : (p2pAnzahl > 0 ? "warn" : "krit")),
      title: p2pTitle || t("header.p2pTitle"),
    });
  }

  if (electrsVerbunden || kopfQuelleAufbau(electrs) || kopfQuelleFehler(electrs)) {
    // Vor Handshake: grau „Indexer“. Erst mit server.version grün + Name.
    const soft = String(electrs?.software || "").trim();
    const softRaw = String(electrs?.software_raw || "").trim();
    const aufbau = kopfQuelleAufbau(electrs);
    const fehler = kopfQuelleFehler(electrs);
    let electrsLabel;
    let electrsTitle;
    let stufe;
    if (electrsVerbunden && soft) {
      electrsLabel = t("header.sourceElectrumImpl", { name: soft });
      electrsTitle = t("header.sourceElectrumImplTitle", {
        name: soft,
        raw: softRaw || soft,
        detail: electrs?.detail || "",
      });
      stufe = "gut";
    } else if (electrsVerbunden) {
      electrsLabel = t("header.sourceIndexer");
      electrsTitle = t("header.sourceElectrumOwnTitle");
      stufe = "gut";
    } else if (aufbau) {
      electrsLabel = t("header.sourceIndexer");
      electrsTitle = t("header.sourceIndexerTitle");
      stufe = "neutral";
    } else {
      electrsLabel = soft
        ? t("header.sourceElectrumImpl", { name: soft })
        : t("header.sourceIndexer");
      electrsTitle = electrs?.error || t("header.sourceElectrumOwnTitle");
      stufe = "krit";
    }
    if (fehler && electrs?.error) electrsTitle = electrs.error;
    eintraege.push({
      key: "own_fulcrum",
      lern: "electrum",
      label: electrsLabel,
      stufe,
      title: electrsTitle,
    });
  }

  if (oeffentlichVerbunden) {
    eintraege.push({
      key: "public",
      lern: "privatsphaere",
      label: t("header.sourceElectrumPublic"),
      stufe: "krit",
      title: t("header.sourceElectrumPublicTitle"),
    });
  }

  // Block-Explorer: immer sichtbar (Konfiguration, kein Live-Peer).
  // privat=grün, öffentlich=rot, unkonfiguriert=grau ohne Zusatztext.
  const mp = Zustand.config?.mempool || {};
  const blockExplorerOeffentlich = Boolean(
    mp.configured && !(mp.local || mp.stufe === "lokal"),
  );
  {
    let beLabel;
    let beStufe;
    let beTitle;
    if (!mp.configured) {
      beLabel = t("header.blockExplorer") !== "header.blockExplorer"
        ? t("header.blockExplorer")
        : "Block-Explorer";
      beStufe = "neutral";
      beTitle = t("header.blockExplorerNoneTitle") !== "header.blockExplorerNoneTitle"
        ? t("header.blockExplorerNoneTitle")
        : t("header.blockExplorerNoneTitle");
    } else if (mp.local || mp.stufe === "lokal") {
      beLabel = t("header.blockExplorerPrivate") !== "header.blockExplorerPrivate"
        ? t("header.blockExplorerPrivate")
        : t("header.blockExplorerPrivate");
      beStufe = "gut";
      beTitle = t("header.blockExplorerPrivateTitle") !== "header.blockExplorerPrivateTitle"
        ? t("header.blockExplorerPrivateTitle")
        : `Eigener/LAN-Explorer${mp.host ? `: ${mp.host}` : ""} — Aufrufe bleiben bei dir.`;
    } else {
      beLabel = t("header.blockExplorerPublic") !== "header.blockExplorerPublic"
        ? t("header.blockExplorerPublic")
        : t("header.blockExplorerPublic");
      beStufe = "krit";
      beTitle = t("header.blockExplorerPublicTitle") !== "header.blockExplorerPublicTitle"
        ? t("header.blockExplorerPublicTitle")
        : t("ui.hard.695025d2a1", { host: mp.host ? `: ${mp.host}` : "" });
    }
    eintraege.push({
      key: "mempool",
      lern: "privatsphaere",
      label: beLabel,
      stufe: beStufe,
      title: beTitle,
    });
  }

  const privateVerbunden =
    coreVerbunden || electrsVerbunden || (p2pVerbunden && p2pAnzahl > 0);
  const privateAufbau =
    kopfQuelleAufbau(core)
    || kopfQuelleAufbau(electrs)
    || p2pAufbau;

  let privText;
  let privStufe;
  // Öffentlicher Electrum ODER öffentlicher Block-Explorer → keine Privatsphäre.
  // Explorer zählt schon bei Konfiguration (↗-Klicks), nicht erst bei Electrs-Link.
  if (oeffentlichVerbunden || blockExplorerOeffentlich) {
    privText = t("privacy.pillNone");
    privStufe = "krit";
  } else if (privateVerbunden && p2pVerbunden && p2pAnzahl === 1
    && !coreVerbunden && !electrsVerbunden) {
    // Nur ein P2P-Peer: privat, aber schwach.
    privText = t("privacy.pillMedium");
    privStufe = "warn";
  } else if (privateVerbunden) {
    privText = t("privacy.pillHigh");
    privStufe = "gut";
  } else if (privateAufbau) {
    privText = t("privacy.pillUnclear");
    privStufe = "warn";
  } else {
    // Nichts live verbunden — nur Cache: kein Leak.
    privText = t("privacy.pillHigh");
    privStufe = "gut";
  }

  setzeText($("#fuss-quelle"), privText);

  // Nur Pillen neu bauen — Suchfeld (#kopf-filter) bleibt links stehen.
  const pillen = $("#quelle-pillen") || $("#quelle-status");
  if (!pillen) return;
  pillen.replaceChildren();
  for (const eintrag of eintraege) {
    const pill = pille(eintrag.stufe, eintrag.label);
    pill.title = eintrag.title;
    if (eintrag.lern) pill.setAttribute("data-lern", eintrag.lern);
    pillen.append(pill);
  }
  const privPill = pille(privStufe, privText);
  privPill.title = t("header.privacyTitle");
  privPill.setAttribute("data-lern", "privatsphaere");
  pillen.append(privPill);
  zeichneKursPille();
  zeichneLlmPille();
  aktualisiereKopfFilterFuerAnsicht();
  if (lernhinweiseAn()) {
    wendeAlleLernTooltipsAn().catch(() => {});
  }
}

/**
 * Globaler Listen-Filter in der Pillen-Zeile.
 * *aktiv* = false: ausgegraut. Wallet-Ansicht: aktiv (Text + >/<-Sats).
 */
function setzeKopfFilterAktiv(aktiv) {
  const feld = $("#kopf-filter");
  if (!feld) return;
  const an = Boolean(aktiv);
  const warAn = !feld.disabled;
  feld.disabled = !an;
  feld.setAttribute("aria-disabled", an ? "false" : "true");
  feld.title = an
    ? t("header.filterTitleActive")
    : t("header.filterTitleDisabled");
  feld.setAttribute(
    "data-i18n-title",
    an ? "header.filterTitleActive" : "header.filterTitleDisabled",
  );
  if (!an) {
    if (warAn || feld.value) {
      feld.value = "";
      wendeKopfFilterAn();
    }
  } else if (feld.value.trim()) {
    wendeKopfFilterAn();
  }
}

/** Welche Ansichten den Kopf-Filter nutzen (weitere folgen schrittweise). */
function kopfFilterAnsichtAktiv(ansicht) {
  return ansicht === "wallet" || ansicht === "trace";
}

function aktualisiereKopfFilterFuerAnsicht() {
  setzeKopfFilterAktiv(kopfFilterAnsichtAktiv(Zustand.ansicht));
}

/**
 * Kalendertag TT.MM.JJJJ oder TT.MM.JJ (lokal) → Date 00:00 oder null.
 * Zweistellige Jahre: 2000+ (Bitcoin-Kontext).
 */
function parseKopfFilterDatum(dd, mm, yy) {
  const day = Number(dd);
  const month = Number(mm);
  let year = Number(yy);
  if (!Number.isFinite(day) || !Number.isFinite(month) || !Number.isFinite(year)) {
    return null;
  }
  if (String(yy).length <= 2) year += 2000;
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const d = new Date(year, month - 1, day, 0, 0, 0, 0);
  if (
    d.getFullYear() !== year
    || d.getMonth() !== month - 1
    || d.getDate() !== day
  ) {
    return null;
  }
  return d;
}

/**
 * Parse: Freitext + `>1234`/`<1234` (sats) + `>1.1.25`/`<05.12.2023` (Datum).
 * Datum: nach dem Tag = ab Folgetag 00:00; vor dem Tag = vor 00:00 dieses Tags.
 * Mehrere Tokens = UND.
 */
function parseKopfFilter(roh) {
  const text = String(roh || "").trim();
  if (!text) {
    return {
      leer: true, terms: [], minSats: null, maxSats: null,
      afterTs: null, beforeTs: null,
    };
  }
  const terms = [];
  let minSats = null;
  let maxSats = null;
  let afterTs = null;
  let beforeTs = null;
  // Datum vor reinem Betrag prüfen (Punkte!).
  const reDatum = /^([<>])(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$/;
  const reSats = /^([<>])(\d+(?:[.,]\d+)?)$/;
  for (const tok of text.split(/\s+/)) {
    if (!tok) continue;
    const dm = tok.match(reDatum);
    if (dm) {
      const start = parseKopfFilterDatum(dm[2], dm[3], dm[4]);
      if (start) {
        if (dm[1] === ">") {
          // nach dem Kalendertag → ab 00:00 des Folgetags
          const next = new Date(start);
          next.setDate(next.getDate() + 1);
          const ts = Math.floor(next.getTime() / 1000);
          afterTs = afterTs == null ? ts : Math.max(afterTs, ts);
        } else {
          // vor dem Kalendertag → vor 00:00 dieses Tags
          const ts = Math.floor(start.getTime() / 1000);
          beforeTs = beforeTs == null ? ts : Math.min(beforeTs, ts);
        }
      }
      continue;
    }
    const sm = tok.match(reSats);
    if (sm) {
      const n = Number(String(sm[2]).replace(",", "."));
      if (Number.isFinite(n)) {
        if (sm[1] === ">") {
          minSats = minSats == null ? n : Math.max(minSats, n);
        } else {
          maxSats = maxSats == null ? n : Math.min(maxSats, n);
        }
      }
      continue;
    }
    terms.push(tok.toLowerCase());
  }
  return { leer: false, terms, minSats, maxSats, afterTs, beforeTs };
}

function _kopfFilterBetragOk(sats, f) {
  if (f.minSats != null) {
    if (!Number.isFinite(sats) || !(sats > f.minSats)) return false;
  }
  if (f.maxSats != null) {
    if (!Number.isFinite(sats) || !(sats < f.maxSats)) return false;
  }
  return true;
}

function _kopfFilterDatumOk(eventTs, f) {
  if (f.afterTs == null && f.beforeTs == null) return true;
  const ts = Number(eventTs);
  if (!Number.isFinite(ts) || ts <= 0) return false;
  if (f.afterTs != null && !(ts >= f.afterTs)) return false;
  if (f.beforeTs != null && !(ts < f.beforeTs)) return false;
  return true;
}

function _kopfFilterHaystack(el) {
  const key = String(el.dataset.key || "");
  const txid = key.includes(":") ? key.split(":")[0] : key;
  return [
    key,
    txid,
    String(el.dataset.address || ""),
    String(el.dataset.timeLabel || ""),
    // Börsen (Kraken, …) und CJ-Formen (Wasabi, Whirlpool, …)
    String(el.dataset.filterLabels || ""),
    // Sichtbarer Pillen-/Icon-Text (aria-label), falls schon gerendert
    String(el.getAttribute("aria-label") || ""),
  ].join(" ").toLowerCase();
}

function _kopfFilterTextOk(hay, terms) {
  if (!terms.length) return true;
  return terms.every((t) => hay.includes(t));
}

function _kopfFilterLeafOk(leaf, f, { textSchonOk = false } = {}) {
  const sats = Number(leaf.dataset.valueSats);
  if (!_kopfFilterBetragOk(sats, f)) return false;
  if (!_kopfFilterDatumOk(leaf.dataset.eventTs, f)) return false;
  if (textSchonOk) return true;
  return _kopfFilterTextOk(_kopfFilterHaystack(leaf), f.terms);
}

function _kopfFilterGruppeAufklappen(gruppe) {
  const kopf = gruppe.querySelector(":scope > .kopf-mit-verweis .adress-kopf, :scope > .adress-kopf");
  const inhalt = gruppe.querySelector(
    ":scope > .adress-utxos, :scope > .trace-utxos",
  );
  const klapp = kopf && kopf.querySelector(".klapp");
  if (kopf && inhalt && inhalt.hidden) {
    setzeKlapp(kopf, klapp, inhalt, true);
  }
}

/**
 * Filter auf eine Adressgruppe (Bestand oder ausgegeben/Trace-Stil).
 * @returns {boolean} Gruppe hat sichtbare Treffer
 */
function _kopfFilterAdressGruppe(gruppe, f) {
  if (typeof gruppe.baueUtxos === "function") {
    try { gruppe.baueUtxos(); } catch (_) { /* ignore */ }
  }
  const leaves = [...gruppe.querySelectorAll(
    ":scope > .adress-utxos > .utxo-zeile, :scope > .trace-utxos > .utxo-wurzel",
  )];
  // Fallback, falls verschachtelt anders
  const liste = leaves.length
    ? leaves
    : [...gruppe.querySelectorAll(".utxo-zeile, .utxo-wurzel")];

  const groupHay = [
    String(gruppe.dataset.address || ""),
    String(gruppe.dataset.filterLabels || ""),
  ].join(" ").toLowerCase();
  const groupTextOk = _kopfFilterTextOk(groupHay, f.terms);

  let any = false;
  for (const leaf of liste) {
    const ok = _kopfFilterLeafOk(leaf, f, { textSchonOk: groupTextOk });
    leaf.hidden = !ok;
    if (ok) any = true;
  }

  // Nur Gruppen-Adresse matched, keine Betrags-/Datumsgrenzen, noch keine Leaves:
  // Gruppe zeigen (UTXOs ggf. lazy).
  if (!any && groupTextOk && liste.length === 0
      && f.minSats == null && f.maxSats == null
      && f.afterTs == null && f.beforeTs == null) {
    any = true;
  }

  gruppe.hidden = !any;
  if (any && liste.some((el) => !el.hidden)) {
    _kopfFilterGruppeAufklappen(gruppe);
  }
  return any;
}

/**
 * Ausgegeben-Block unter *container*: Inhalt bei Bedarf zeichnen.
 * *daten* liefert verlauf.addresses (Wallet- oder Trace-LastData).
 */
function _kopfFilterStelleAusgegebenBereit(container, daten) {
  if (!container) return null;
  const block = container.querySelector(".ausgegeben-block");
  if (!block) return null;
  const inhalt = block.querySelector(".ausgegeben-inhalt");
  const kopf = block.querySelector(".adress-kopf");
  if (!inhalt || !kopf) return block;
  if (!inhalt.dataset.gezeichnet) {
    const klapp = kopf.querySelector(".klapp");
    inhalt.dataset.gezeichnet = "ja";
    setzeKlapp(kopf, klapp, inhalt, true);
    const addrs = daten?.verlauf?.addresses || [];
    inhalt.replaceChildren();
    fuelleTraceSortiert(
      inhalt,
      addrs,
      Zustand.traceSort || "volume-desc",
    );
  } else if (inhalt.hidden) {
    const klapp = kopf.querySelector(".klapp");
    setzeKlapp(kopf, klapp, inhalt, true);
  }
  return block;
}

function _kopfFilterAusgegebenAnwenden(ausBlock, f) {
  if (!ausBlock) return;
  if (f.leer) {
    ausBlock.hidden = false;
    for (const el of ausBlock.querySelectorAll(
      ".adress-gruppe, .utxo-zeile, .utxo-wurzel",
    )) {
      el.hidden = false;
    }
    return;
  }
  let any = false;
  for (const gruppe of ausBlock.querySelectorAll(".adress-gruppe")) {
    if (_kopfFilterAdressGruppe(gruppe, f)) any = true;
  }
  for (const leaf of ausBlock.querySelectorAll(
    ".ausgegeben-inhalt > .utxo-wurzel",
  )) {
    const ok = _kopfFilterLeafOk(leaf, f);
    leaf.hidden = !ok;
    if (ok) any = true;
  }
  ausBlock.hidden = !any;
}

function _kopfFilterRootLeeren(root) {
  if (!root) return;
  for (const el of root.querySelectorAll(
    ".adress-gruppe, .utxo-zeile, .utxo-wurzel, .ausgegeben-block, .trace-fokus",
  )) {
    el.hidden = false;
  }
}

function wendeKopfFilterWalletAn(f) {
  const root = $("#ansicht-wallet");
  if (!root) return;

  if (f.leer) {
    _kopfFilterRootLeeren(root);
    return;
  }

  for (const gruppe of root.querySelectorAll("#adress-koerper .adress-gruppe")) {
    _kopfFilterAdressGruppe(gruppe, f);
  }

  const ausBlock = _kopfFilterStelleAusgegebenBereit(
    $("#wallet-ausgegeben") || root,
    Zustand._walletUtxoDaten,
  );
  _kopfFilterAusgegebenAnwenden(ausBlock, f);
}

/** Herkunft tracen: Bestand (#trace-liste) + ausgegeben + Fokus-UTXO. */
function wendeKopfFilterTraceAn(f) {
  const root = $("#ansicht-trace");
  const liste = $("#trace-liste");
  if (!root || !liste) return;

  if (f.leer) {
    _kopfFilterRootLeeren(root);
    return;
  }

  // Adressgruppen (Volumen-Sortierung)
  for (const gruppe of liste.querySelectorAll(":scope > .adress-gruppe")) {
    _kopfFilterAdressGruppe(gruppe, f);
  }

  // Flache UTXO-Wurzeln (Alter-Sortierung) und Fokus-Hülle
  for (const leaf of liste.querySelectorAll(":scope > .utxo-wurzel")) {
    const ok = _kopfFilterLeafOk(leaf, f);
    leaf.hidden = !ok;
  }
  for (const fokus of liste.querySelectorAll(":scope > .trace-fokus")) {
    const wurzel = fokus.querySelector(".utxo-wurzel");
    if (!wurzel) {
      fokus.hidden = true;
      continue;
    }
    const ok = _kopfFilterLeafOk(wurzel, f);
    fokus.hidden = !ok;
    wurzel.hidden = false;
  }

  const ausBlock = _kopfFilterStelleAusgegebenBereit(liste, Zustand.traceLastData);
  _kopfFilterAusgegebenAnwenden(ausBlock, f);
}

function wendeKopfFilterAn() {
  const feld = $("#kopf-filter");
  const f = parseKopfFilter(feld && !feld.disabled ? feld.value : "");
  if (Zustand.ansicht === "wallet") {
    wendeKopfFilterWalletAn(f);
    // Trace-DOM zurücksetzen, falls zuvor gefiltert
    _kopfFilterRootLeeren($("#ansicht-trace"));
    return;
  }
  if (Zustand.ansicht === "trace") {
    wendeKopfFilterTraceAn(f);
    _kopfFilterRootLeeren($("#ansicht-wallet"));
    return;
  }
  const leer = {
    leer: true, terms: [], minSats: null, maxSats: null,
    afterTs: null, beforeTs: null,
  };
  wendeKopfFilterWalletAn(leer);
  wendeKopfFilterTraceAn(leer);
}

let _kopfFilterTimer = null;
function planeKopfFilter() {
  if (_kopfFilterTimer) clearTimeout(_kopfFilterTimer);
  _kopfFilterTimer = setTimeout(() => {
    _kopfFilterTimer = null;
    wendeKopfFilterAn();
  }, 150);
}

function bindeKopfFilter() {
  const feld = $("#kopf-filter");
  if (!feld || feld.dataset.gebunden === "1") return;
  feld.dataset.gebunden = "1";
  feld.addEventListener("input", planeKopfFilter);
  feld.addEventListener("search", planeKopfFilter);
  feld.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      feld.value = "";
      wendeKopfFilterAn();
      feld.blur();
    }
  });
}

const LLM_TAKT_MS = 30000;
/** Spotkurs: an den Cache-TTL in core/price.py angelehnt (10 Min). */
const KURS_TAKT_MS = 10 * 60 * 1000;

function formatKursLabel(preis) {
  if (!preis || !(Number(preis.amount) > 0)) return "BTC —";
  const n = Math.round(Number(preis.amount)).toLocaleString(formatLocale());
  const w = String(preis.currency || fiatWaehrung()).toUpperCase();
  if (w === "EUR") return `${n} €`;
  if (w === "USD") return `$${n}`;
  return `${n} ${w}`.trim();
}

function formatKursTooltip(preis) {
  if (!preis || !(Number(preis.amount) > 0)) {
    return t("header.btcTitleEmpty");
  }
  const wann = preis.time
    ? new Date(Number(preis.time) * 1000).toLocaleString(formatLocale())
    : "?";
  const quelle = preis.source || "?";
  return t("header.btcTitleLive", {
    preis: formatKursLabel(preis),
    quelle,
    wann,
  });
}

function zeichneKursPille() {
  const pillen = $("#quelle-pillen") || $("#quelle-status");
  if (!pillen) return;
  const preis = Zustand.kurs;
  const stufe = preis && Number(preis.amount) > 0 ? "gut" : "neutral";
  const neu = pille(stufe, formatKursLabel(preis));
  neu.id = "kurs-pille";
  neu.title = formatKursTooltip(preis);
  neu.setAttribute("data-lern", "preis");
  neu.setAttribute("data-i18n-title", "header.btcTitle");
  const alt = $("#kurs-pille");
  if (alt) {
    alt.replaceWith(neu);
    if (lernhinweiseAn()) ergaenzeLernTooltip(neu);
    return;
  }
  const llm = $("#llm-pille");
  if (llm) pillen.insertBefore(neu, llm);
  else pillen.append(neu);
  if (lernhinweiseAn()) ergaenzeLernTooltip(neu);
}

/** Tageskurs-Serie für Fiat-Umrechnung ausgegebener Beträge (je Währung). */
async function ladeKursSerie() {
  const w = fiatWaehrung();
  if (Zustand.kursSerie?.[w]?.series) return Zustand.kursSerie;
  if (Zustand.kursSerieLade) return Zustand.kursSerieLade;
  Zustand.kursSerieLade = (async () => {
    try {
      const stand = await api(
        `/price/history?currency=${encodeURIComponent(w)}&series=1`,
        { timeoutMs: 15000 },
      );
      const eintrag = (stand.histories || []).find((h) => h.currency === w);
      const basis = Zustand.kursSerie && typeof Zustand.kursSerie === "object"
        ? { ...Zustand.kursSerie }
        : {};
      if (eintrag?.series && eintrag.ok) {
        basis[w] = eintrag;
      } else {
        basis[w] = { ok: false, series: null, currency: w };
      }
      Zustand.kursSerie = basis;
    } catch (_fehler) {
      const basis = Zustand.kursSerie && typeof Zustand.kursSerie === "object"
        ? { ...Zustand.kursSerie }
        : {};
      basis[w] = { ok: false, series: null, currency: w };
      Zustand.kursSerie = basis;
    } finally {
      Zustand.kursSerieLade = null;
    }
    return Zustand.kursSerie;
  })();
  return Zustand.kursSerieLade;
}

async function ladeSpotkurs({ laut = false } = {}) {
  if (laut) logZeile("Hole Bitcoin-Kurs…");
  const w = fiatWaehrung();
  try {
    // Kurz timeout: sonst blockiert der Start bei Netz-/SSL-Problemen.
    Zustand.kurs = await api(
      `/price?currency=${encodeURIComponent(w)}`,
      { timeoutMs: 8000 },
    );
    const warn = (Zustand.kurs && Zustand.kurs.warning) || "";
    if (warn) {
      // Nur einmal pro Session — und nur wenn wirklich ein älterer Tag.
      if (!Zustand.kursWarnGeloggt) {
        Zustand.kursWarnGeloggt = true;
        logZeile(`Kurs: ${warn}.`, true);
      }
    } else if (laut) {
      const label = formatKursLabel(Zustand.kurs);
      const quelle = Zustand.kurs.source || "?";
      logZeile(`Kurs: ${label} (${quelle}).`, true);
    }
  } catch (fehler) {
    const msg = String(fehler.message || fehler || "");
    // Keine mehrzeilige Opt-in-/Pipe-Forensik; höchstens einmal.
    if (!Zustand.kursWarnGeloggt && (laut || /nicht beschaffbar/i.test(msg))) {
      Zustand.kursWarnGeloggt = true;
      logZeile(
        msg.length > 120 || msg.includes(" | ")
          ? t("ui.hard.64ef962e0f")
          : `Kurs: ${msg}`,
        true,
      );
    }
  }
  zeichneKursPille();
  if (Zustand.kurs && Number(Zustand.kurs.amount) > 0) {
    aktualisiereFiatAnzeigen();
  }
}

function setzeKursTakt() {
  if (Zustand.kursTimer) return;
  Zustand.kursTimer = setInterval(() => {
    ladeSpotkurs({ laut: false });
  }, KURS_TAKT_MS);
}

/** Nach Kurs-/Sprachwechsel: sichtbare Beträge mit ≈ Fiat neu zeichnen. */
function aktualisiereFiatAnzeigen() {
  if (Zustand.ansicht === "wallet" && Zustand.walletId) {
    zeigeWallet(Zustand.walletId).catch(() => {});
    return;
  }
  if (Zustand.ansicht === "steuerjahr") {
    const jahr = $("#jahr-wahl");
    if (jahr && typeof ladeSteuerjahr === "function") {
      ladeSteuerjahr().catch(() => {});
    }
  }
}

function zeichneLlmPille() {
  const pillen = $("#quelle-pillen") || $("#quelle-status");
  if (!pillen) return;
  const s = Zustand.llmStatus || Zustand.config?.llm || {};
  const neu = pille(s.pille || "neutral", übersetzeLlmLabel(s.pille_label) || "LLM");
  neu.id = "llm-pille";
  neu.title = übersetzeLlmLabel(s.tooltip) || t("settings.llm.notConfigured");
  const alt = $("#llm-pille");
  if (alt) alt.replaceWith(neu);
  else pillen.append(neu);
}

function übersetzeLlmLabel(roh) {
  if (!roh) return "";
  let text = String(roh);
  text = text
    .replace(/\bModell\b/g, t("settings.llm.modelWord"))
    .replace(/\bStufe hoch\b/g, t("settings.llm.levelHigh"))
    .replace(/\bStufe mittel\b/g, t("settings.llm.levelMid"))
    .replace(/\bStufe niedrig\b/g, t("settings.llm.levelLow"))
    .replace(/\bnur Cache\b/g, t("settings.llm.cacheOnly"))
    .replace(/\blokal\b/g, t("settings.llm.local"))
    .replace(/Assistent nicht konfiguriert/g, t("settings.llm.notConfigured"));
  return text;
}

function zeichneChatAnbindung() {
  const kasten = $("#chat-anbindung");
  if (!kasten) return;
  const s = Zustand.llmStatus || Zustand.config?.llm || {};
  kasten.textContent = übersetzeLlmLabel(s.banner) || t("settings.llm.notConfigured");
  kasten.classList.toggle("unkonfiguriert", !s.configured);
}

function zeichneLlmEinstellungen() {
  const s = Zustand.llmStatus || Zustand.config?.llm || {};
  const url = $("#llm-url");
  const modell = $("#llm-modell");
  const anbieter = $("#llm-anbieter");
  const optIn = $("#llm-remote-opt-in");
  const key = $("#llm-api-key");
  if (url) url.value = s.base_url || "";
  if (modell) modell.value = s.modell || "";
  if (anbieter) anbieter.value = s.anbieter || "";
  if (optIn) optIn.checked = Boolean(s.remote_opt_in);
  if (key) {
    key.value = "";
    key.placeholder = s.api_key_set
      ? "gesetzt — leer lassen, um zu behalten"
      : "optional, nur bei API-Key";
  }
}

async function ladeLlmStatus({ check = false, laut = false } = {}) {
  if (laut && check) logZeile(t("ui.hard.7628c50446"));
  try {
    Zustand.llmStatus = await api(check ? "/llm/status?check=1" : "/llm/status");
  } catch (fehler) {
    if (laut) logZeile(t("ui.hard.f559917bc5", { msg: fehler.message }), true);
    return;
  }
  if (laut && check) {
    const s = Zustand.llmStatus;
    if (s.reachable) {
      logZeile(`Assistent erreichbar. ${s.banner}`, true);
    } else if (s.configured) {
      const grund = s.probe_error ? `: ${s.probe_error}` : ".";
      logZeile(t("ui.hard.151407fe6c", { grund }), true);
    } else {
      logZeile(t("ui.hard.16d796814c"));
    }
  }
  zeichneLlmPille();
  zeichneChatAnbindung();
}

function setzeLlmTakt() {
  if (Zustand.llmTimer) return;
  Zustand.llmTimer = setInterval(() => {
    const konfiguriert = Boolean(Zustand.llmStatus?.configured);
    ladeLlmStatus({ check: konfiguriert });
  }, LLM_TAKT_MS);
}

async function speichereLlmEinstellungen() {
  const knopf = $("#llm-uebernehmen");
  if (knopf) knopf.disabled = true;
  const keyFeld = $("#llm-api-key");
  const daten = {
    base_url: $("#llm-url") ? $("#llm-url").value : "",
    modell: $("#llm-modell") ? $("#llm-modell").value : "",
    anbieter: $("#llm-anbieter") ? $("#llm-anbieter").value : "",
    remote_opt_in: Boolean($("#llm-remote-opt-in") && $("#llm-remote-opt-in").checked),
  };
  if (keyFeld && keyFeld.value.trim()) daten.api_key = keyFeld.value.trim();
  try {
    const ergebnis = await api("/config/llm", {
      methode: "PUT",
      daten,
    });
    if (Zustand.config) Zustand.config.llm = ergebnis.llm;
    Zustand.llmStatus = ergebnis.llm;
    if (keyFeld) keyFeld.value = "";
    zeichneLlmEinstellungen();
    zeichneLlmPille();
    zeichneChatAnbindung();
    meldung(t("settings.llmSaved"), "gut");
    await ladeLlmStatus({ check: true, laut: true });
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

function zeichneStatusMailEinstellungen() {
  const s = Zustand.config?.status_mail || {};
  const optIn = $("#status-mail-opt-in");
  const to = $("#status-mail-to");
  const host = $("#status-mail-host");
  const port = $("#status-mail-port");
  const user = $("#status-mail-user");
  const pass = $("#status-mail-password");
  const from = $("#status-mail-from");
  const tls = $("#status-mail-starttls");
  if (optIn) optIn.checked = Boolean(s.opt_in);
  if (to) to.value = s.to || "";
  if (host) host.value = s.smtp_host || "";
  if (port) port.value = s.smtp_port != null ? String(s.smtp_port) : "587";
  if (user) user.value = s.smtp_user || "";
  if (from) from.value = s.smtp_from || "";
  if (tls) tls.checked = s.starttls !== false;
  if (pass) {
    pass.value = "";
    pass.placeholder = s.smtp_password_set
      ? "gesetzt — leer lassen, um zu behalten"
      : "optional";
  }
}

async function speichereStatusMailEinstellungen() {
  const knopf = $("#status-mail-uebernehmen");
  if (knopf) knopf.disabled = true;
  const passFeld = $("#status-mail-password");
  const daten = {
    opt_in: Boolean($("#status-mail-opt-in") && $("#status-mail-opt-in").checked),
    to: $("#status-mail-to") ? $("#status-mail-to").value : "",
    smtp_host: $("#status-mail-host") ? $("#status-mail-host").value : "",
    smtp_port: $("#status-mail-port") ? $("#status-mail-port").value : "587",
    smtp_user: $("#status-mail-user") ? $("#status-mail-user").value : "",
    smtp_from: $("#status-mail-from") ? $("#status-mail-from").value : "",
    starttls: Boolean(
      !$("#status-mail-starttls") || $("#status-mail-starttls").checked,
    ),
  };
  if (passFeld && passFeld.value.trim()) {
    daten.smtp_password = passFeld.value.trim();
  }
  try {
    const ergebnis = await api("/config/status-mail", {
      methode: "PUT",
      daten,
    });
    if (Zustand.config) Zustand.config.status_mail = ergebnis.status_mail;
    if (passFeld) passFeld.value = "";
    zeichneStatusMailEinstellungen();
    meldung(
      ergebnis.status_mail?.configured
        ? t("settings.mail.savedActive")
        : t("settings.mail.saved"),
      "gut",
    );
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

function slashHilfeText() {
  return t("dock.helpText");
}

const SLASH_BLOCK = new Set([
  "scan", "rescan", "verlauf", "herkunft", "sanktion", "sync", "fetch",
  "exec", "shell", "python", "eval", "system",
  "env", "xpub", "key", "seed", "token", "api-key", "apikey",
  "delete", "cache-loeschen", "danger", "reset-all",
  "send", "broadcast", "sign", "psbt",
  "url", "http", "curl", "download",
]);

const SLASH_ALIAS = {
  help: "hilfe",
  clear: "neu",
  leeren: "neu",
  status: "anbindung",
};

const SLASH_BEFEHLE = [
  "/hilfe",
  "/help",
  "/anbindung",
  "/neu",
  "/luecken",
  "/wallets",
  "/steuer",
  "/export legende",
  "/export markdown",
  "/export brief",
];

function slashTreffer(eingabe) {
  const text = String(eingabe || "");
  if (!text.startsWith("/")) return [];
  const klein = text.toLowerCase();
  return SLASH_BEFEHLE.filter((befehl) => befehl.toLowerCase().startsWith(klein));
}

function slashGemeinsam(treffer) {
  if (!treffer.length) return "";
  let prefix = treffer[0];
  for (const befehl of treffer) {
    let i = 0;
    while (
      i < prefix.length &&
      i < befehl.length &&
      prefix[i].toLowerCase() === befehl[i].toLowerCase()
    ) {
      i += 1;
    }
    prefix = prefix.slice(0, i);
  }
  return prefix;
}

function schliesseSlashListe() {
  const liste = $("#chat-slash");
  if (liste) {
    liste.hidden = true;
    liste.replaceChildren();
  }
  Zustand.slashIndex = 0;
}

function zeichneSlashListe(eingabe) {
  const liste = $("#chat-slash");
  if (!liste) return;
  const treffer = slashTreffer(eingabe);
  if (!treffer.length) {
    schliesseSlashListe();
    return;
  }
  if (Zustand.slashIndex >= treffer.length) Zustand.slashIndex = 0;
  if (Zustand.slashIndex < 0) Zustand.slashIndex = treffer.length - 1;
  liste.hidden = false;
  liste.replaceChildren();
  treffer.forEach((befehl, index) => {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "chat-slash-eintrag";
    if (index === Zustand.slashIndex) knopf.classList.add("aktiv");
    knopf.textContent = befehl;
    knopf.addEventListener("mousedown", (ereignis) => {
      ereignis.preventDefault();
      const feld = $("#chat-feld");
      if (!feld) return;
      feld.value = befehl;
      feld.focus();
      feld.setSelectionRange(befehl.length, befehl.length);
      Zustand.slashIndex = index;
      zeichneSlashListe(befehl);
    });
    liste.append(knopf);
  });
}

function vervollstaendigeSlash(feld) {
  if (!feld) return false;
  const text = feld.value;
  if (feld.selectionStart !== text.length || feld.selectionEnd !== text.length) {
    return false;
  }
  const treffer = slashTreffer(text);
  if (!treffer.length) return false;
  const idx = Math.min(Zustand.slashIndex || 0, treffer.length - 1);
  const gemeinsam = slashGemeinsam(treffer);
  let ziel = treffer[idx];
  if (treffer.length > 1 && gemeinsam.length > text.length) ziel = gemeinsam;
  if (ziel === text) return false;
  feld.value = ziel;
  feld.setSelectionRange(ziel.length, ziel.length);
  zeichneSlashListe(ziel);
  return true;
}

function parseSlash(text) {
  const roh = String(text || "").trim();
  if (!roh.startsWith("/")) return { art: "freitext", text: roh };
  const teile = roh.slice(1).trim().split(/\s+/).filter(Boolean);
  const rohCmd = (teile[0] || "").toLowerCase();
  const cmd = SLASH_ALIAS[rohCmd] || rohCmd;
  const rest = teile.slice(1);
  if (!cmd) return { art: "unbekannt", befehl: roh };
  if (SLASH_BLOCK.has(cmd) || (cmd === "modell" && rest[0])) {
    return { art: "block", befehl: `/${rohCmd}` };
  }
  if (cmd === "export") {
    const erst = (rest[0] || "").toLowerCase();
    if (!erst) return { art: "export", unter: "legende", jahr: "" };
    if (/^\d{4}$/.test(erst)) return { art: "export", unter: "legende", jahr: erst };
    if (["legende", "markdown", "brief"].includes(erst)) {
      return { art: "export", unter: erst, jahr: rest[1] || "" };
    }
    return { art: "unbekannt", befehl: roh };
  }
  if (["hilfe", "anbindung", "neu", "luecken", "wallets", "steuer"].includes(cmd)) {
    return { art: cmd, jahr: rest[0] || "" };
  }
  return { art: "unbekannt", befehl: roh };
}

function chatLeeren() {
  Zustand.chatMessages = [];
  const box = $("#chat-verlauf");
  if (!box) return;
  box.replaceChildren();
  const leer = document.createElement("p");
  leer.className = "chat-leer";
  leer.textContent = t("dock.empty");
  box.append(leer);
}

function chatZeile(rolle, text) {
  const box = $("#chat-verlauf");
  if (!box) return null;
  const leer = box.querySelector(".chat-leer");
  if (leer) leer.remove();
  const blase = document.createElement("div");
  blase.className = `chat-blase chat-${rolle}`;
  blase.textContent = text;
  box.append(blase);
  box.scrollTop = box.scrollHeight;
  return blase;
}

function slashJahrQuery(jahr) {
  const n = Number.parseInt(jahr, 10);
  if (Number.isFinite(n) && n >= 2009 && n <= 2100) return `?jahr=${n}`;
  return "";
}

function setzeChatWartet(an) {
  Zustand.chatWartet = Boolean(an);
  const feld = $("#chat-feld");
  const knopf = $("#chat-senden");
  if (feld) feld.disabled = Boolean(an);
  if (knopf) knopf.disabled = Boolean(an);
  if (an) schliesseSlashListe();
}

async function frageAssistent(text) {
  const historie = Zustand.chatMessages.concat([{ role: "user", content: text }]);
  const warte = chatZeile("system", t("dock.asking"));
  if (warte) warte.classList.add("chat-warte");
  logZeile("Frage Assistent…");
  setzeChatWartet(true);
  try {
    const koerper = await api("/llm/chat", {
      methode: "POST",
      daten: { messages: historie },
    });
    const antwort = (koerper && koerper.text) || t("dock.noAnswer");
    Zustand.chatMessages = historie.concat([
      { role: "assistant", content: antwort },
    ]);
    if (warte) warte.remove();
    chatZeile("assistent", antwort);
  } catch (fehler) {
    if (warte) warte.remove();
    chatZeile("system", t("dock.notAnswered", { msg: fehler.message }));
  } finally {
    setzeChatWartet(false);
    const feld = $("#chat-feld");
    if (feld) feld.focus();
  }
}

async function sendeChatZeile() {
  const feld = $("#chat-feld");
  if (!feld || Zustand.chatWartet) return;
  const text = feld.value.trim();
  if (!text) return;
  schliesseSlashListe();
  feld.value = "";
  feld.blur();
  window.requestAnimationFrame(() => {
    if (!Zustand.chatWartet) feld.focus();
  });
  chatZeile("user", text);
  const befehl = parseSlash(text);
  if (befehl.art === "freitext") {
    await frageAssistent(text);
    return;
  }
  if (befehl.art === "block") {
    chatZeile(
      "system",
      t("dock.blocked", { cmd: befehl.befehl }),
    );
    return;
  }
  if (befehl.art === "unbekannt") {
    chatZeile("system", t("dock.unknown"));
    return;
  }
  if (befehl.art === "hilfe") {
    chatZeile("assistent", slashHilfeText());
    return;
  }
  if (befehl.art === "anbindung") {
    const s = Zustand.llmStatus || Zustand.config?.llm || {};
    chatZeile("assistent", s.banner || "Assistent nicht konfiguriert");
    return;
  }
  if (befehl.art === "neu") {
    chatLeeren();
    return;
  }
  const pfade = {
    luecken: "/llm/context/luecken",
    wallets: "/llm/context/wallets",
    steuer: `/llm/context/steuer${slashJahrQuery(befehl.jahr)}`,
    export: `/llm/context/export?art=${encodeURIComponent(befehl.unter || "legende")}${
      slashJahrQuery(befehl.jahr).replace("?", "&")
    }`,
  };
  const pfad = pfade[befehl.art];
  if (!pfad) {
    chatZeile("system", t("dock.unknown"));
    return;
  }
  try {
    const koerper = await api(pfad);
    chatZeile("assistent", koerper.text || "Keine Daten im Cache.");
  } catch (fehler) {
    chatZeile("system", `Nicht gelesen — ${fehler.message}`);
  }
}

async function testeEigenenNode(knopf, opts = {}) {
  const vorher = knopf ? knopf.textContent : "";
  if (knopf) {
    knopf.disabled = true;
    knopf.textContent = t("common.testing");
  }
  if (eigenerNode(Zustand.config?.sources) || knopf) {
    logZeile(t("ui.hard.7c5b3235d4"));
  }
  Zustand.peerCheckLaeuft = true;
  // Sofort „Verbindung im Aufbau…“ in Datenquellen, solange der Check läuft.
  if ($("#quellen-liste")?.childElementCount) {
    zeichneQuellen(Zustand.config?.sources || []);
  }
  try {
    const ergebnis = await apiSourceCheck();
    const stand = nimmPeerStand(ergebnis, false);
    // Staub bei jedem erfolgreichen Speichern/Test einer hoch-privaten
    // Verbindung (Indexer/P2P) — auch nach IP-/Software-Wechsel.
    // Öffentliches Electrum: nie. Stiller Poll: nie.
    const bewusst = Boolean(knopf) || Boolean(opts.jubel);
    if (
      bewusst
      && standHatHochPrivateVerbindung(
        stand,
        Zustand.config?.sources || ergebnis.sources,
      )
    ) {
      jubelDatenquelleErfolg();
    }
    return stand;
  } finally {
    Zustand.peerCheckLaeuft = false;
    if ($("#quellen-liste")?.childElementCount) {
      zeichneQuellen(Zustand.config?.sources || []);
    }
    if (knopf) {
      knopf.disabled = false;
      knopf.textContent = vorher || "Eigenen Node testen";
    }
  }
}

async function pruefeNodeStatus() {
  try {
    await testeEigenenNode();
  } catch (_) {
    /* Kopfzeile bleibt beim letzten Stand — kein rotes Aufblitzen bei Netzfehlern zum eigenen Server. */
  }
}

async function sichereHeaderVorab() {
  const tip = Zustand.config?.header_tip;
  if (Zustand.config?.header_job_id) return;
  if (tip != null && tip > 481824) return;
  try {
    const antwort = await api("/headers", { methode: "POST" });
    if (Zustand.config) {
      Zustand.config.header_job_id = antwort.header_job_id;
      Zustand.config.header_tip = antwort.header_tip;
    }
  } catch (_) {
    /* Scan holt Header zur Not selbst. */
  }
}

function folgeHeaderJob() {
  const id = Zustand.config?.header_job_id;
  if (!id || Zustand.headerJob === id) return;
  Zustand.headerJob = id;
  Zustand.headerLogStand = { index: 0 };
  if (Zustand.headerTimer) clearInterval(Zustand.headerTimer);
  Zustand.headerTimer = setInterval(pruefeHeaderJob, 1500);
  pruefeHeaderJob();
}

async function pruefeHeaderJob() {
  if (!Zustand.headerJob) return;
  try {
    const job = await api(`/jobs/${Zustand.headerJob}`);
    nimmJobLogAb(job, Zustand.headerLogStand);
    if (Array.isArray(job.live_p2p_peers)) {
      nimmLiveP2pPeers(job.live_p2p_peers);
    }
    if (job.running) return;
    if (Zustand.headerTimer) {
      clearInterval(Zustand.headerTimer);
      Zustand.headerTimer = null;
    }
    Zustand.headerJob = null;
    if (!Zustand.walletSyncJob) {
      Zustand.liveP2pPeers = [];
      setzePeerTakt(Zustand.config?.sources);
    }
  } catch (_) {
    /* Vorab-Job ist optional — der Scan holt Header zur Not selbst. */
  }
}

function loeseWalletSyncBindung() {
  if (Zustand.walletSyncTimer) {
    clearInterval(Zustand.walletSyncTimer);
    Zustand.walletSyncTimer = null;
  }
  if (Zustand.walletSyncJob) {
    // Für Ka-Ching nach Empfangs-Index-Sprung (QR oft vor Pending-Flash).
    Zustand._tipSyncEndedUm = Date.now();
  }
  Zustand.walletSyncJob = null;
  Zustand.walletSyncWalletIds = [];
  Zustand.walletSyncDoneIds = [];
  Zustand.walletSyncStill = false;
  Zustand.walletSyncPhase = null;
  if (Zustand.config) Zustand.config.wallet_sync_job_id = null;
  Zustand.liveP2pPeers = [];
  setzePeerTakt(Zustand.config?.sources);
}

function jobIstStillerTip(jobOrMeta) {
  if (!jobOrMeta) return false;
  if (jobOrMeta.still || jobOrMeta.meta?.still) return true;
  return false;
}

/** Tip-Sync betraf das gerade gewählte Wallet (Empfang/UTXO nur dann anfassen). */
function tipSyncBetrifftAktuellesWallet(ids) {
  const wid = Zustand.walletId;
  if (!wid) return false;
  const liste = Array.isArray(ids) && ids.length
    ? ids
    : (Zustand.walletSyncWalletIds || []);
  if (!liste.length) return false;
  return liste.map(String).includes(String(wid));
}

function folgeWalletSyncJob(jobId, meta) {
  const id = jobId || Zustand.config?.wallet_sync_job_id;
  if (!id || Zustand.walletSyncJob === id) {
    if (meta) {
      merkeWalletSyncZiele(meta);
      if (jobIstStillerTip(meta)) Zustand.walletSyncStill = true;
    }
    return;
  }
  // Fertiger/staler Job aus Config: nicht als laufend behandeln, Puls nicht starten.
  const bekannt = (Zustand.jobsNav?.jobs || []).find((x) => x && x.id === id);
  if (
    bekannt
    && !(
      bekannt.running
      || bekannt.status === "running"
      || bekannt.status === "queued"
      || bekannt.queue_status === "queued"
    )
  ) {
    if (Zustand.config) Zustand.config.wallet_sync_job_id = null;
    return;
  }
  Zustand.walletSyncJob = id;
  if (Zustand.config) Zustand.config.wallet_sync_job_id = id;
  Zustand.walletSyncLogStand = { index: 0 };
  Zustand.walletSyncDoneIds = [];
  Zustand.walletSyncStill = jobIstStillerTip(meta) || jobIstStillerTip(bekannt);
  if (meta) merkeWalletSyncZiele(meta);
  else if (bekannt) merkeWalletSyncZiele(bekannt);
  if (Zustand.walletSyncTimer) clearInterval(Zustand.walletSyncTimer);
  Zustand.walletSyncTimer = setInterval(pruefeWalletSyncJob, 900);
  // Erst Status prüfen — erst bei running loggen/atmen (siehe pruefeWalletSyncJob).
  pruefeWalletSyncJob();
  setzeWalletScanGesperrt();
}

async function pruefeWalletSyncJob() {
  if (!Zustand.walletSyncJob) return;
  const syncId = Zustand.walletSyncJob;
  try {
    const job = await api(`/jobs/${syncId}`);
    nimmJobLogAb(job, Zustand.walletSyncLogStand);
    if (Array.isArray(job.live_p2p_peers)) {
      nimmLiveP2pPeers(job.live_p2p_peers);
    }
    if (job.meta?.own_fulcrum) {
      nimmOwnFulcrumStand(job.meta.own_fulcrum);
    }
    merkeWalletSyncZiele(job);
    if (jobIstStillerTip(job)) Zustand.walletSyncStill = true;
    if (job.meta?.phase === "empfang") {
      Zustand.walletSyncPhase = "empfang";
      // jobsNav-Meta mitziehen (sonst zeigt der Poller weiter „läuft“).
      const navJob = (Zustand.jobsNav?.jobs || []).find((x) => x && x.id === syncId);
      if (navJob) {
        navJob.meta = navJob.meta || {};
        navJob.meta.phase = "empfang";
      }
    }
    if (job.running || job.status === "running" || job.status === "queued") {
      // Echt laufend: einmal loggen; Empfang nur wenn DIESES Wallet im Tip-Sync ist.
      // Stiller Watch-Fallback: Log ok, kein Puls / keine Nav-Marker.
      if (!Zustand.walletSyncLogStand?._tipAngekuendigt) {
        Zustand.walletSyncLogStand = Zustand.walletSyncLogStand || { index: 0 };
        Zustand.walletSyncLogStand._tipAngekuendigt = true;
        if (Zustand.walletSyncStill) {
          logZeile("Tip-Nachzug (still, Hintergrund)…");
        } else {
          logZeile("Tip-Nachzug der Wallets…");
          if (
            Zustand.walletId
            && !Zustand.lernThema
            && tipSyncBetrifftAktuellesWallet()
          ) {
            ladeEmpfang(Zustand.walletId).catch(() => {});
          }
          zeichneNav();
        }
      }
      // Je fertigem Wallet: Config/Nav nachziehen → „gerade eben“ statt warten
      // bis alle Wallets durch sind.
      const fertigIds = tipSyncDoneWalletIds(job);
      const vorher = Zustand.walletSyncDoneIds || [];
      if (
        fertigIds.length > vorher.length
        && !Zustand.walletSyncStill
      ) {
        Zustand.walletSyncDoneIds = fertigIds.slice();
        // jobsNav-Meta mitziehen (walletSyncLaeuftFuer liest beides).
        const navJob = (Zustand.jobsNav?.jobs || []).find((x) => x && x.id === syncId);
        if (navJob) {
          navJob.meta = navJob.meta || {};
          navJob.meta.done_wallet_ids = fertigIds.slice();
        }
        try {
          await ladeConfig();
        } catch (_) {
          /* Nav trotzdem */
        }
        setzeWalletScanGesperrt();
        zeichneNav();
        // Empfangspanel an aktuellem Wallet ausrichten: fertig → QR/Read-only,
        // noch Tip → weiter Atem (auch Read-only).
        if (Zustand.walletId && !Zustand.lernThema) {
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      // UTXO-Tip fertig, Empfangsadressen laufen noch → Nav grün, QR darf laden.
      if (
        (job.meta?.phase === "empfang" || Zustand.walletSyncPhase === "empfang")
        && !Zustand.walletSyncLogStand?._tipUiFertig
        && !Zustand.walletSyncStill
      ) {
        Zustand.walletSyncLogStand._tipUiFertig = true;
        Zustand.walletSyncPhase = "empfang";
        const n = job.result?.wallets;
        const u = job.result?.utxo_count;
        if (typeof n === "number") {
          logZeile(
            `Tip-Nachzug fertig: ${n} Wallet(s), ${u ?? "?"} UTXO(s) `
            + "(Empfangsadressen folgen)…",
          );
        }
        if (Zustand.config) Zustand.config.wallet_sync_job_id = null;
        const betroffene = walletIdsAusSyncJob(job);
        for (const wid of betroffene) {
          delete Zustand.empfangByWallet[wid];
        }
        try {
          await ladeConfig();
        } catch (_) {
          /* Nav trotzdem */
        }
        setzeWalletScanGesperrt();
        zeichneNav();
        if (
          Zustand.walletId
          && !Zustand.lernThema
          && tipSyncBetrifftAktuellesWallet(betroffene.length ? betroffene : null)
        ) {
          // phase empfang → tipSyncLaeuftFuer false → Electrs-Adresse holen
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      return;
    }
    const warAktiv = Boolean(Zustand.walletSyncLogStand?._tipAngekuendigt);
    const warStill = Zustand.walletSyncStill;
    const betroffene = walletIdsAusSyncJob(job).length
      ? walletIdsAusSyncJob(job)
      : (Zustand.walletSyncWalletIds || []).slice();
    const betrifftAktuell = !warStill && tipSyncBetrifftAktuellesWallet(betroffene);
    const pulsAn = EmpfangPuls.laeuft()
      || Boolean(Zustand.empfang && Zustand.empfang.puls);
    loeseWalletSyncBindung();
    // Puls/QR nur anfassen, wenn Tip-Sync dieses Wallet betraf und wir atmeten —
    // nicht wenn gerade Ka-Ching nachgeholt wird.
    if (betrifftAktuell && pulsAn && !EmpfangPuls.laeuft()) {
      EmpfangPuls.stop();
    }
    setzeWalletScanGesperrt();
    // Stale done-Job aus Config beim Start: nur Slot freigeben, kein Reload-Sturm.
    if (!warAktiv) {
      zeichneNav();
      return;
    }
    if (job.status === "done") {
      const n = job.result?.wallets;
      const u = job.result?.utxo_count;
      // Fertig-Zeile schon bei phase=empfang geloggt → nicht doppelt.
      if (typeof n === "number" && !Zustand.walletSyncLogStand?._tipUiFertig) {
        logZeile(
          `Tip-Nachzug fertig: ${n} Wallet(s), ${u ?? "?"} UTXO(s).`,
        );
      } else if (job.result?.empfang_scharf) {
        logZeile(
          `Empfangsadressen nachgezogen (${job.result.empfang_scharf}).`,
        );
      }
      // Nur Cache der betroffenen Wallets — nicht Firmung-QR wegen Cash+Carry.
      for (const wid of betroffene) {
        delete Zustand.empfangByWallet[wid];
      }
      await ladeConfig();
      await ladeJobsNav();
      setzeWalletScanGesperrt();
      if (betrifftAktuell && Zustand.walletId) {
        // Pending während Tip-Sync → Konfetti jetzt (QR-Sprung ohne Ka-Ching vermeiden).
        const kaChing = spieleQueuedIncomingFlash(Zustand.walletId);
        if (Zustand.ansicht === "wallet") {
          await zeigeWallet(Zustand.walletId);
          if (!kaChing && !EmpfangPuls.laeuft()) {
            ladeEmpfang(Zustand.walletId).catch(() => {});
          }
        } else if (!Zustand.lernThema) {
          if (!kaChing) ladeEmpfang(Zustand.walletId).catch(() => {});
          zeichneNav();
        } else {
          zeichneNav();
        }
      } else {
        zeichneNav();
      }
    } else if (job.status === "cancelled") {
      logZeile("Tip-Nachzug abgebrochen.");
      if (betrifftAktuell && Zustand.walletId && !Zustand.lernThema) {
        if (!spieleQueuedIncomingFlash(Zustand.walletId)) {
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      zeichneNav();
    } else {
      if (job.error) logZeile(`Tip-Nachzug: ${job.error}`);
      if (betrifftAktuell && Zustand.walletId && !Zustand.lernThema) {
        if (!spieleQueuedIncomingFlash(Zustand.walletId)) {
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      zeichneNav();
    }
  } catch (_) {
    // Job weg (404) oder Netz: Bindung lösen, sonst atmet der QR ewig.
    const betrifftAktuell = tipSyncBetrifftAktuellesWallet();
    const pulsAn = EmpfangPuls.laeuft()
      || Boolean(Zustand.empfang && Zustand.empfang.puls);
    loeseWalletSyncBindung();
    if (betrifftAktuell && pulsAn) EmpfangPuls.stop();
    setzeWalletScanGesperrt();
    if (betrifftAktuell && Zustand.walletId && !Zustand.lernThema) {
      ladeEmpfang(Zustand.walletId).catch(() => {});
    }
    zeichneNav();
  }
}

function zeichneFussVersion() {
  zeichneFussLocalOnly();
  const ziel = $("#fuss-version");
  if (!ziel) return;
  const ver = (Zustand.config?.version || "").trim();
  if (!ver) {
    ziel.textContent = "";
    return;
  }
  ziel.textContent = `v${ver} · `;
}

/**
 * Laufende SatSage-Version als erste Log-Zeile (einmalig, bleibt oben).
 */
function logReleaseAlsErsteZeile() {
  const ziel = $("#log-text");
  if (!ziel) return;
  const ver = (Zustand.config?.version || "").trim();
  if (!ver) return;
  const text = `SatSage v${ver}`;
  let zeile = ziel.querySelector(".log-zeile.log-release");
  if (zeile) {
    const meldung = zeile.querySelector(".log-meldung");
    if (meldung) meldung.textContent = text;
    if (ziel.firstChild !== zeile) ziel.prepend(zeile);
    return;
  }
  zeile = document.createElement("div");
  zeile.className = "log-zeile log-release";
  const zeit = document.createElement("span");
  zeit.className = "log-zeit";
  zeit.textContent = logZeitstempel();
  zeile.append(zeit);
  const meldung = document.createElement("span");
  meldung.className = "log-meldung";
  meldung.textContent = text;
  zeile.append("  ", meldung);
  ziel.prepend(zeile);
}

// "nur lokal erreichbar" nur behaupten, wenn es stimmt. Hinter Umbrels
// app_proxy bindet der Server an 0.0.0.0 und ist aus dem ganzen LAN offen.
function zeichneFussLocalOnly() {
  const ziel = $("#fuss-local-only");
  if (!ziel) return;
  ziel.hidden = Zustand.config?.local_only !== true;
}

function zeichneUiLang() {
  const aktuell = uiSprache();
  const wahl = $("#ui-lang");
  if (wahl) wahl.value = aktuell === "en" ? "en" : "de";
  const deBtn = $("#lang-de");
  const enBtn = $("#lang-en");
  if (deBtn) deBtn.classList.toggle("aktiv", aktuell === "de");
  if (enBtn) enBtn.classList.toggle("aktiv", aktuell === "en");
}

/**
 * UI-Sprache setzen (Header-Knöpfe und Einstellungen-Select).
 *
 * Reihenfolge absichtlich: Katalog + DOM zuerst (sofort sichtbar), dann
 * UI_LANG speichern und Fiat nachladen. Persistenz-Fehler brechen den
 * Sprachwechsel nicht ab.
 */
async function wechsleUiLang(ziel, { meldungZeigen = true } = {}) {
  if (!window.SatSageI18n) {
    console.warn("wechsleUiLang: SatSageI18n fehlt");
    return;
  }
  const lang = ziel === "en" ? "en" : "de";
  if (uiSprache() === lang) {
    zeichneUiLang();
    return;
  }
  try {
    // Ohne persistEnv — Sprache wechselt auch wenn /config/ui-lang hängt.
    await window.SatSageI18n.setLang(lang, { persistEnv: null });
  } catch (fehler) {
    console.error("wechsleUiLang setLang", fehler);
    if (typeof meldung === "function") {
      meldung(String(fehler.message || fehler), "krit");
    }
    return;
  }
  if (Zustand.config) Zustand.config.ui_lang = lang;
  zeichneUiLang();
  zeichneKursPille();

  // Persistenz und Fiat parallel, blockieren die UI nicht.
  api("/config/ui-lang", {
    methode: "PUT",
    daten: { ui_lang: lang },
    timeoutMs: 8000,
  }).then((ergebnis) => {
    if (Zustand.config && ergebnis && ergebnis.ui_lang) {
      Zustand.config.ui_lang = ergebnis.ui_lang;
    }
  }).catch((fehler) => {
    console.warn("UI_LANG speichern:", fehler);
  });

  Zustand.kursSerie = null;
  Zustand.kursWarnGeloggt = false;
  Promise.all([
    ladeSpotkurs({ laut: false }),
    ladeKursSerie(),
  ]).then(() => {
    aktualisiereFiatAnzeigen();
  }).catch(() => {
    aktualisiereFiatAnzeigen();
  });

  if (meldungZeigen && typeof meldung === "function") {
    meldung(t("settings.language.saved"), "gut");
  }
}

async function speichereUiLang() {
  const wahl = $("#ui-lang");
  if (!wahl) return;
  const lang = wahl.value === "en" ? "en" : "de";
  await wechsleUiLang(lang);
}

/** Header DE/EN — früh binden, nicht erst nach Header-Job/Wallet-Sync. */
function bindeSprachUmschalter() {
  if (bindeSprachUmschalter._done) return;
  bindeSprachUmschalter._done = true;
  const deBtn = $("#lang-de");
  const enBtn = $("#lang-en");
  if (deBtn) {
    deBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      wechsleUiLang("de", { meldungZeigen: false });
    });
  }
  if (enBtn) {
    enBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      wechsleUiLang("en", { meldungZeigen: false });
    });
  }
  const langWahl = $("#ui-lang");
  if (langWahl && !langWahl.dataset.langBound) {
    langWahl.dataset.langBound = "1";
    langWahl.addEventListener("change", () => {
      speichereUiLang();
    });
  }
  zeichneUiLang();
}

const UI_THEME_STORAGE = "satsage-ui-theme";

function liesUiTheme() {
  try {
    const lokal = localStorage.getItem(UI_THEME_STORAGE);
    if (lokal === "dark" || lokal === "light") return lokal;
  } catch (_) { /* private mode */ }
  const ausConfig = Zustand.config?.ui_theme;
  if (ausConfig === "dark" || ausConfig === "light") return ausConfig;
  return "light";
}

function setzeUiTheme(theme) {
  const wert = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", wert);
  try {
    localStorage.setItem(UI_THEME_STORAGE, wert);
  } catch (_) { /* private mode */ }
  return wert;
}

function liesUiThemeAusRadios() {
  const aktiv = document.querySelector('input[name="ui-theme"]:checked');
  if (aktiv && (aktiv.value === "dark" || aktiv.value === "light")) {
    return aktiv.value;
  }
  return liesUiTheme();
}

function zeichneUiTheme() {
  const theme = liesUiTheme();
  const hell = $("#ui-theme-light");
  const dunkel = $("#ui-theme-dark");
  if (hell) hell.checked = theme === "light";
  if (dunkel) dunkel.checked = theme === "dark";
}

async function speichereUiTheme() {
  const theme = setzeUiTheme(liesUiThemeAusRadios());
  const ergebnis = await api("/config/ui-theme", {
    methode: "PUT",
    daten: { ui_theme: theme },
  });
  if (Zustand.config) Zustand.config.ui_theme = ergebnis.ui_theme;
  zeichneUiTheme();
  if (typeof meldung === "function") {
    meldung(t("settings.theme.saved"), "gut");
  }
}

async function ladeConfig() {
  const altQuellen = Zustand.config?.sources;
  Zustand.config = await api("/config");
  Zustand.config.sources = uebernehmeQuellenErreichbarkeit(
    altQuellen, Zustand.config.sources,
  );
  // Offene Server-Peers sofort in die Pille — ohne erneute Netzprobe.
  if (Array.isArray(Zustand.config.live_p2p_peers) && Zustand.config.live_p2p_peers.length) {
    nimmLiveP2pPeers(Zustand.config.live_p2p_peers);
  }
  Zustand.entwurf = Zustand.config.wallets.map((w) => ({ ...w }));
  setzeEnvPfad(Zustand.config.env_path);
  Zustand.llmStatus = Zustand.config.llm || Zustand.llmStatus;
  zeichneKopfStatus(Zustand.config.sources);
  zeichneSteuerEinstellungen();
  zeichneUiLang();
  // Theme: localStorage hat Vorrang; fehlt es, greift config/Default.
  try {
    if (!localStorage.getItem(UI_THEME_STORAGE) && Zustand.config?.ui_theme) {
      setzeUiTheme(Zustand.config.ui_theme);
    } else {
      setzeUiTheme(liesUiTheme());
    }
  } catch (_) {
    setzeUiTheme(liesUiTheme());
  }
  zeichneUiTheme();
  fuellOnchainHinweisTexte();
  zeichneStartSync();
  zeichneAppPasswort();
  zeichneLernhinweiseEinstellung();
  setzeEmpfangLabSenden();
  zeichneLlmEinstellungen();
  zeichneStatusMailEinstellungen();
  zeichneMempoolStatus();
  zeichneChatAnbindung();
  zeichneNav();
  ggfEnvScrambleUnlockDialog();
  zeichneFussVersion();
  logReleaseAlsErsteZeile();
  if (Zustand.config?.lernhinweise_plebs) {
    wendeAlleLernTooltipsAn().catch(() => {});
  }
  if (Zustand.walletId) {
    ladeEmpfang(Zustand.walletId).catch(() => {});
  } else {
    zeichneEmpfangLeer();
  }
  const hopFeld = $("#sank-hops");
  if (hopFeld) {
    const cap = Number(Zustand.config?.sanktion_max_hops_cap) || 20;
    hopFeld.max = String(cap);
  }
}

async function start() {
  // Auth: Session-Cookie und/oder Bootstrap-Token. Mit gesetztem Passwort
  // reicht ?t= nicht — Login ist Pflicht (auch Loopback / nach Server-Neustart).
  let auth = null;
  try {
    const antwort = await fetch("/api/auth/status", { credentials: "same-origin" });
    if (antwort.ok) auth = await antwort.json();
  } catch (_) {
    auth = null;
  }
  if (auth && auth.password_set && !auth.authenticated) {
    location.href = "/login?next=/";
    return;
  }
  if (!Token) {
    if (auth && auth.authenticated) {
      // Session-Cookie reicht — kein ?t= nötig.
    } else if (auth && auth.password_set) {
      location.href = "/login?next=/";
      return;
    } else {
      $("#token-fehlt").hidden = false;
      return;
    }
  }
  $("#app").hidden = false;
  // DE/EN sofort klickbar — nicht erst nach Jobs/Header-Sync am Ende von start().
  bindeSprachUmschalter();
  const logKnopf = $("#log-anzeige");
  // Standard an (wie bisher checked); Klick toggelt wie DE/EN.
  setzeLogSichtbar(logKnopf ? logKnopf.classList.contains("aktiv") : true);
  if (logKnopf) {
    logKnopf.addEventListener("click", () => {
      const an = !document.querySelector(".buehne")?.classList.contains("log-an");
      setzeLogSichtbar(an);
    });
  }
  macheLogZiehbar();
  macheDockSpalter();
  macheEmpfangSpalter();
  setzeEmpfangPoll();
  setzeLernhinweiseDelegates();
  setzeEmpfangAnimDebug();
  setzeEmpfangLabSenden();

  try {
    await ladeConfig();
    if (window.SatSageI18n) {
      await window.SatSageI18n.initI18n({
        configLang: Zustand.config?.ui_lang,
      });
      zeichneUiLang();
      // Haltefrist-Optionen wurden in ladeConfig vor dem Catalog befüllt (Roh-Keys).
      zeichneSteuerEinstellungen();
      // Kopf nach Catalog nochmal — ladeConfig kann vor initI18n gelaufen sein.
      zeichneKopfStatus(Zustand.config?.sources || []);
    }
    // Select-Listener falls #ui-lang erst jetzt im DOM wäre (idempotent).
    bindeSprachUmschalter();
    for (const radio of document.querySelectorAll('input[name="ui-theme"]')) {
      radio.addEventListener("change", () => {
        if (radio.checked) speichereUiTheme();
      });
    }
    window.addEventListener("satsage:lang", () => {
      if (window.SatSageI18n) window.SatSageI18n.applyDom(document);
      // data-i18n-html setzt .env-pfad zurück auf „.env“ — echten Pfad wiederherstellen.
      if (Zustand.config?.env_path) setzeEnvPfad(Zustand.config.env_path);
      zeichneNav();
      zeichneFussVersion();
      zeichneUiLang();
      zeichneKursPille();
      zeichneSteuerEinstellungen();
      // Template und dynamische Texte ohne data-i18n neu setzen.
      if (window.SatSageI18n) {
        window.SatSageI18n.applyDom($("#vorlage-wallet"));
      }
      const chatLeer = document.querySelector("#chat-verlauf .chat-leer");
      if (chatLeer) chatLeer.textContent = t("dock.empty");
      if (Zustand.empfang && Zustand.walletId) {
        ladeEmpfang(Zustand.walletId, { still: true }).catch(() => {});
      } else {
        zeichneEmpfangLeer();
      }
      if (typeof zeichneEinrichtung === "function" && $("#einrichtung") && !$("#einrichtung").hidden) {
        zeichneEinrichtung();
      }
      if (typeof zeichneWalletVerwaltung === "function" && Zustand.ansicht === "wallets") {
        zeichneWalletVerwaltung();
      }
      if (typeof ladeGefahrWallets === "function" && Zustand.ansicht === "wallets") {
        ladeGefahrWallets();
      }
      if (typeof zeichneQuellen === "function" && Zustand.ansicht === "datenquellen") {
        zeichneQuellen(Zustand.config?.sources || []);
        if (typeof ladeListenStatus === "function") ladeListenStatus();
        if (typeof ladeLabelStatus === "function") ladeLabelStatus();
        if (typeof ladeKursHistorie === "function") ladeKursHistorie();
        if (typeof zeichneMempoolStatus === "function") zeichneMempoolStatus();
      }
      if (typeof zeichneKopfStatus === "function") {
        zeichneKopfStatus(Zustand.config?.sources || []);
      }
      if (typeof zeichneLlmPille === "function" && Zustand.llmStatus) {
        zeichneLlmPille();
      }
      if (Zustand.ansicht === "wallet" && Zustand.walletId) {
        zeigeWallet(Zustand.walletId).catch(() => {});
      } else if (Zustand.ansicht === "steuerjahr" && typeof ladeSteuerjahr === "function") {
        ladeSteuerjahr();
      } else if (Zustand.ansicht === "trace" && typeof ladeTraceListe === "function") {
        ladeTraceListe();
      } else if (Zustand.ansicht === "sanktionen" && typeof ladeSankCache === "function") {
        ladeSankCache();
      }
    });
    await ladeLlmStatus({ check: Boolean(Zustand.llmStatus?.configured), laut: true });
    setzeLlmTakt();
    // Kurs parallel: darf den Start nicht blockieren (früher „Load failed“ / Hänger).
    ladeSpotkurs({ laut: true }).finally(() => setzeKursTakt());
    // Tageshistorie für „ausgegeben am …“-EUR; Fehler → Spot-Fallback (gelb).
    ladeKursSerie().catch(() => {});
    await ladeJobsNav();
    setzeJobsTakt();
    await sichereHeaderVorab();
    folgeHeaderJob();
    folgeWalletSyncJob();
  } catch (fehler) {
    $("#app").hidden = true;
    $("#token-fehlt").hidden = false;
    $("#token-fehlt").querySelector("h1").textContent = t("common.noConnection");
    $("#token-fehlt").querySelector("p").textContent = fehler.message;
    return;
  }

  document
    .querySelector('[data-ansicht="wallets"]')
    .addEventListener("click", () => oeffneVerwaltung("wallets"));
  document
    .querySelector('[data-ansicht="einstellungen"]')
    .addEventListener("click", () => oeffneVerwaltung("einstellungen"));
  document
    .querySelector('[data-ansicht="datenquellen"]')
    .addEventListener("click", () => oeffneVerwaltung("datenquellen"));
  document
    .querySelector('[data-ansicht="trace"]')
    .addEventListener("click", () => {
      // Schon in Herkunft: nichts ändern (Fokus bleibt Fokus, Liste bleibt Liste).
      // Volle Liste nur beim Wechsel *aus einer anderen* Ansicht.
      if (Zustand.ansicht === "trace") {
        zeichneNav();
        return;
      }
      Zustand.traceFokus = null;
      zeigeAnsicht("trace");
      ladeTraceListe({ erzwingen: true });
    });
  document
    .querySelector('[data-ansicht="steuerjahr"]')
    .addEventListener("click", () => {
      zeigeAnsicht("steuerjahr");
      ladeSteuerjahrMitKandidaten();
    });
  document
    .querySelector('[data-ansicht="sanktionen"]')
    .addEventListener("click", async () => {
      zeigeAnsicht("sanktionen");
      fuellSankWallets();
      // Laufenden Check bevorzugen — sonst verschwindet die Fortschrittszeile.
      try {
        const nav = Zustand.jobsNav?.jobs || [];
        const laufend = nav.find(
          (j) => j.kind === "sanctions-check" && j.running,
        );
        if (laufend?.id) {
          bindeSanktionsCheckJob(laufend.id, { hops: laufend.meta?.hops });
          return;
        }
        if (Zustand.sanktionsCheckJobId) {
          bindeSanktionsCheckJob(Zustand.sanktionsCheckJobId);
          return;
        }
      } catch (_) {
        /* Cache laden */
      }
      ladeSankCache();
    });

  $("#einrichtung-weiter").addEventListener("click", () => {
    schliesseEinrichtung();
    if (brauchtDatenquellenZuerst()) {
      oeffneVerwaltung("datenquellen");
      return;
    }
    const schritte = einrichtungsSchritte(Zustand.config);
    const walletsOk = schritte.find((s) => s.titel.startsWith("Wallets"))?.erledigt;
    oeffneVerwaltung(walletsOk ? "datenquellen" : "wallets");
  });
  $("#einrichtung-spaeter").addEventListener("click", () => schliesseEinrichtung());
  $("#einrichtung-onchain-ok").addEventListener("click", bestaetigeOnchainHinweis);
  $("#onchain-hinweis").addEventListener("keydown", (e) => {
    if ($("#onchain-hinweis").hidden) return;
    if (e.key === "Enter" || e.key === "Escape") {
      e.preventDefault();
      bestaetigeOnchainHinweis();
    }
  });
  $("#einrichtung-oeffnen").addEventListener("click", zeigeEinrichtung);

  $("#sank-start").addEventListener("click", starteSanktionsCheck);
  $("#sank-verwerfen").addEventListener("click", verwerfeSankCache);

  $("#trace-start").addEventListener("click", starteTrace);
  $("#trace-ziel").addEventListener("keydown", (e) => {
    if (e.key === "Enter") starteTrace();
  });
  $("#jahr-wahl").addEventListener("change", () => ladeSteuerjahrMitKandidaten());
  $("#frist-wahl").addEventListener("change", async () => {
    try {
      const ergebnis = await api("/config/steuer", {
        methode: "PUT",
        daten: {
          haltefrist_jahre: Number($("#frist-wahl").value),
          stichtag: steuerEinstellungen().stichtag_iso || "",
          anschaffung: steuerEinstellungen().anschaffung || "juengste",
        },
      });
      if (Zustand.config) Zustand.config.steuer = ergebnis.steuer;
      zeichneSteuerEinstellungen();
    } catch (_) {
      /* Auswertung trotzdem mit der gewählten Frist */
    }
    ladeSteuerjahr();
  });
  $("#steuer-uebernehmen").addEventListener("click", speichereSteuerEinstellungen);
  const personBtn = $("#person-uebernehmen");
  if (personBtn) personBtn.addEventListener("click", speicherePersonEinstellungen);
  bindeAppPasswortUi();
  zeichneAppPasswort();
  const lernPlebs = $("#lernhinweise-plebs");
  if (lernPlebs) {
    lernPlebs.addEventListener("change", () => {
      speichereLernhinweiseEinstellung().catch((fehler) => {
        meldung(fehler.message || String(fehler), "krit");
      });
    });
  }
  const empfangZurueck = $("#empfang-lern-zurueck");
  if (empfangZurueck) {
    empfangZurueck.addEventListener("click", () => loescheLernThema());
  }
  const empfangQr = $("#empfang-qr");
  if (empfangQr) {
    empfangQr.addEventListener("click", () => {
      if (Zustand.empfang?.lern && Zustand.empfang.url) {
        oeffneLernUrl(Zustand.empfang.url);
      }
    });
  }
  const empfangAdresse = $("#empfang-adresse");
  if (empfangAdresse) {
    empfangAdresse.addEventListener("click", (e) => {
      if (Zustand.empfang?.lern && Zustand.empfang.url) {
        e.preventDefault();
        e.stopPropagation();
        oeffneLernUrl(Zustand.empfang.url);
      }
    });
  }
  const startSync = $("#start-sync");
  if (startSync) {
    startSync.addEventListener("change", speichereStartSync);
  }
  const startSyncKnown = $("#start-sync-known-only");
  if (startSyncKnown) {
    startSyncKnown.addEventListener("change", speichereStartSync);
  }
  const llmKnopf = $("#llm-uebernehmen");
  if (llmKnopf) {
    llmKnopf.addEventListener("click", speichereLlmEinstellungen);
  }
  const statusMailKnopf = $("#status-mail-uebernehmen");
  if (statusMailKnopf) {
    statusMailKnopf.addEventListener("click", speichereStatusMailEinstellungen);
  }
  const chatForm = $("#chat-eingabe");
  const chatFeld = $("#chat-feld");
  if (chatForm) {
    chatForm.addEventListener("submit", (ereignis) => {
      ereignis.preventDefault();
      sendeChatZeile();
    });
  }
  if (chatFeld) {
    chatFeld.addEventListener("input", () => {
      Zustand.slashIndex = 0;
      zeichneSlashListe(chatFeld.value);
    });
    chatFeld.addEventListener("keydown", (ereignis) => {
      const offen = $("#chat-slash") && !$("#chat-slash").hidden;
      if (ereignis.key === "ArrowRight" || ereignis.key === "Tab") {
        if (vervollstaendigeSlash(chatFeld)) {
          ereignis.preventDefault();
        }
        return;
      }
      if (!offen) return;
      if (ereignis.key === "ArrowDown") {
        ereignis.preventDefault();
        Zustand.slashIndex += 1;
        zeichneSlashListe(chatFeld.value);
      } else if (ereignis.key === "ArrowUp") {
        ereignis.preventDefault();
        Zustand.slashIndex -= 1;
        zeichneSlashListe(chatFeld.value);
      } else if (ereignis.key === "Escape") {
        ereignis.preventDefault();
        schliesseSlashListe();
      }
    });
    chatFeld.addEventListener("blur", () => {
      window.setTimeout(schliesseSlashListe, 0);
    });
  }
  // Steuerjahr „klären“ sitzt in der Scorecard (wird in zeichneSteuerjahr gebunden).
  $("#trace-herkunft-alle").addEventListener("click", () => herkunftAllerUtxos({
    knopf: "#trace-herkunft-alle",
    lauf: "#trace-herkunft-lauf",
    text: "#trace-herkunft-text",
    abbruch: "#trace-herkunft-abbruch",
    meldung: "#trace-meldung",
    danach: ladeTraceListe,
  }));
  const herkunftTief = $("#herkunft-tief-knopf");
  if (herkunftTief) {
    herkunftTief.addEventListener("click", () => starteHerkunftVollstaendig());
  }
  $("#verlauf-erheben").addEventListener("click", verlaufErheben);
  $("#export-csv").addEventListener("click", () => ladeExport("export.csv"));
  $("#export-bericht").addEventListener("click", () => ladeExport("bericht.html"));
  const saLaden = $("#sa-laden");
  if (saLaden) {
    saLaden.addEventListener("click", () => ladeSelbstanzeigeKandidaten({ laut: true }));
  }
  const saHtml = $("#sa-html");
  if (saHtml) saHtml.addEventListener("click", () => ladeSelbstanzeigeExport("html"));
  const saCsv = $("#sa-csv");
  if (saCsv) saCsv.addEventListener("click", () => ladeSelbstanzeigeExport("csv"));
  const saTxid = $("#sa-txid");
  if (saTxid) {
    saTxid.addEventListener("keydown", (e) => {
      if (e.key === "Enter") ladeSelbstanzeigeKandidaten({ laut: true });
    });
  }

  $("#limit-wahl").addEventListener("change", () => zeigeWallet(Zustand.walletId));
  $("#sort-wahl").addEventListener("change", () => zeigeWallet(Zustand.walletId));
  $("#tip-sync-knopf")?.addEventListener("click", starteTipSync);
  $("#rescan-knopf").addEventListener("click", starteRescan);
  $("#verlauf-knopf").addEventListener("click", starteVerlaufsscan);
  $("#rescan-abbruch").addEventListener("click", brichRescanAb);
  $("#hinzufuegen").addEventListener("click", fuegeWalletHinzu);
  $("#deskriptor-import").addEventListener("click", oeffneDeskriptorImport);
  $("#deskriptor-datei").addEventListener("change", liesDeskriptorDatei);
  const sparrowImport = $("#sparrow-import");
  if (sparrowImport) sparrowImport.addEventListener("click", oeffneSparrowImport);
  const sparrowDateien = $("#sparrow-dateien");
  if (sparrowDateien) sparrowDateien.addEventListener("change", liesSparrowDateien);
  const exportSuchen = $("#wallet-export-suchen");
  if (exportSuchen) exportSuchen.addEventListener("click", starteWalletExportSuche);
  aktualisiereWalletExportImportKnopf();

  let deskriptorTimer = null;
  $("#neuer-deskriptor").addEventListener("input", () => {
    clearTimeout(deskriptorTimer);
    deskriptorTimer = setTimeout(pruefeDeskriptor, 400);
  });
  $("#neuer-xpub").addEventListener("keydown", (e) => {
    if (e.key === "Enter") fuegeWalletHinzu();
  });
  const neuerName = $("#neuer-name");
  if (neuerName) {
    neuerName.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const xpub = $("#neuer-xpub");
        if (xpub) xpub.focus();
      }
    });
  }
  const unrefLoeschen = $("#cache-unreferenziert-loeschen");
  if (unrefLoeschen) {
    unrefLoeschen.addEventListener("click", loescheUnreferenziertenCache);
  }
  const cacheDashRefresh = $("#cache-dash-aktualisieren");
  if (cacheDashRefresh) {
    cacheDashRefresh.addEventListener("click", () => {
      ladeCacheDashboard();
    });
  }
  bindeKopfFilter();
  aktualisiereKopfFilterFuerAnsicht();
  $("#privatsphaere-entfernen").addEventListener("click", verwerfeErstenXpub);
  $("#privatsphaere-ok").addEventListener("click", akzeptiereOhneSicherenNode);
  $("#oeffentliche-electrum-nein").addEventListener("click", lehneOeffentlicheElectrumAb);
  $("#oeffentliche-electrum-ja").addEventListener("click", erlaubeOeffentlicheElectrum);
  $("#oeffentliche-electrum-warnung").addEventListener("keydown", (e) => {
    if ($("#oeffentliche-electrum-warnung").hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      lehneOeffentlicheElectrumAb();
      return;
    }
    if (e.key === "Enter" && e.target.id !== "oeffentliche-electrum-ja") {
      e.preventDefault();
      lehneOeffentlicheElectrumAb();
    }
  });
  $("#privatsphaere-warnung").addEventListener("keydown", (e) => {
    if ($("#privatsphaere-warnung").hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      verwerfeErstenXpub();
      return;
    }
    if (e.key === "Enter" && e.target.id !== "privatsphaere-ok") {
      e.preventDefault();
      verwerfeErstenXpub();
    }
  });
  $("#listen-update").addEventListener("click", aktualisiereListen);
  const listenImport = $("#listen-import");
  if (listenImport) listenImport.addEventListener("click", starteListenImport);
  const listenDateien = $("#listen-dateien");
  if (listenDateien) listenDateien.addEventListener("change", liesListenImportDateien);
  $("#label-laden").addEventListener("click", ladeLabels);
  const labelImport = $("#label-import");
  if (labelImport) labelImport.addEventListener("click", starteLabelImport);
  const labelDateien = $("#label-dateien");
  if (labelDateien) labelDateien.addEventListener("change", liesLabelImportDateien);
  $("#label-verwerfen").addEventListener("click", verwirfLabels);
  $("#cache-leeren").addEventListener("click", () => setzeCacheLeerenBestaetigung(true));
  $("#cache-leeren-abbruch").addEventListener("click", () => setzeCacheLeerenBestaetigung(false));
  $("#cache-leeren-ok").addEventListener("click", leereGesamtenCache);
  $("#mempool-speichern").addEventListener("click", speichereMempool);
  const managedMempoolSave = document.getElementById("mempool-speichern-managed");
  if (managedMempoolSave) managedMempoolSave.addEventListener("click", speichereMempool);
  const kursEur = $("#kurs-import-eur");
  if (kursEur) kursEur.addEventListener("click", () => starteKursImport("EUR"));
  const kursUsd = $("#kurs-import-usd");
  if (kursUsd) kursUsd.addEventListener("click", () => starteKursImport("USD"));
  const kursDatei = $("#kurs-csv-datei");
  if (kursDatei) kursDatei.addEventListener("change", liesKursCsvDatei);
  const kursSync = $("#kurs-historie-sync");
  if (kursSync) {
    kursSync.addEventListener("click", () => starteKursHistorieSync());
  }
  const boerseImport = $("#boerse-csv-import");
  if (boerseImport) boerseImport.addEventListener("click", starteBoersenCsvImport);
  const boerseDatei = $("#boerse-csv-datei");
  if (boerseDatei) boerseDatei.addEventListener("change", liesBoersenCsvDatei);
  $("#mempool-url").addEventListener("keydown", (e) => {
    if (e.key === "Enter") speichereMempool();
  });
  const managedMempool = document.getElementById("mempool-url-managed");
  if (managedMempool) managedMempool.addEventListener("keydown", (e) => {
    if (e.key === "Enter") speichereMempool();
  });
  $("#quelle-pruefen").addEventListener("click", async (ereignis) => {
    try {
      await testeEigenenNode(ereignis.currentTarget);
    } catch (fehler) {
      meldung(t("ui.hard.4c7456e438", { msg: fehler.message }), "krit");
    }
  });

  window.addEventListener("beforeunload", (e) => {
    if (entwurfGeaendert()) e.preventDefault();
  });

  // Einstieg: mit Wallets → erstes Wallet. Ohne Wallets und ohne echte
  // Datenquelle (P2P „eh da“ zählt nicht) → Datenquellen; sonst Wallets.
  if ((Zustand.config.wallets || []).length > 0) {
    zeigeWallet(Zustand.config.wallets[0].id);
  } else if (walletsManaged()) {
    oeffneVerwaltung("einstellungen");
  } else if (brauchtDatenquellenZuerst()) {
    oeffneVerwaltung("datenquellen");
  } else {
    oeffneVerwaltung("wallets");
  }

  einrichtungBeimStart();
  // Still nachladen: Server hält Connections; lauter Neu-Test nur über Knopf.
  pruefePeersLeise();
  // Sprach-Handler bereits früh via bindeSprachUmschalter(); hier nur Sync.
  zeichneUiLang();
}

