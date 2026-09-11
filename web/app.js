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
  const key = `trace.txClass.${kind}`;
  const uebersetzt = t(key);
  if (uebersetzt !== key) return uebersetzt;
  return knotenOderErgebnis.tx_class_label || knotenOderErgebnis.note || "";
}

/** Mempool-artige Form-Icons für Mix-Soft-Labels (kein Markenlogo). */
const TX_CLASS_ICON = {
  whirlpool: "img/tx-class/whirlpool.svg",
  wasabi_classic: "img/tx-class/wasabi-classic.svg",
  wabisabi: "img/tx-class/wabisabi.svg",
  joinmarket: "img/tx-class/joinmarket.svg",
};

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
  const iconSrc = TX_CLASS_ICON[kind];
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
];

/** Mix-Arten aus einem Trace-Ergebnis (Root + Kinder), ohne Extra-Netzwerk. */
function mixArtenAusErgebnis(ergebnis) {
  const gesehen = new Set();
  if (!ergebnis || !ergebnis.found) return [];
  const stapel = [];
  if (ergebnis.root) stapel.push(ergebnis.root);
  for (const k of ergebnis.children || []) stapel.push(k);
  if (ergebnis.tx_class && TX_CLASS_ICON[ergebnis.tx_class]) {
    gesehen.add(ergebnis.tx_class);
  }
  while (stapel.length) {
    const knoten = stapel.pop();
    if (!knoten || typeof knoten !== "object") continue;
    if (knoten.tx_class && TX_CLASS_ICON[knoten.tx_class]) {
      gesehen.add(knoten.tx_class);
    }
    for (const kind of knoten.children || []) stapel.push(kind);
  }
  return MIX_ICON_ORDER.filter((k) => gesehen.has(k));
}

/** Mix-Arten einer Adressgruppe aus schon gespeicherten Traces (ohne Extra-Job). */
function mixArtenDerGruppe(gruppe) {
  const gesehen = new Set();
  for (const u of gruppe.utxos || []) {
    for (const k of u.mix_arten || []) {
      if (TX_CLASS_ICON[k]) gesehen.add(k);
    }
    if (u.tx_class && TX_CLASS_ICON[u.tx_class]) gesehen.add(u.tx_class);
  }
  return MIX_ICON_ORDER.filter((k) => gesehen.has(k));
}

/** Kurznamen für Adressgruppen-Tooltips (nicht das volle Soft-Label). */
const MIX_ICON_KURZ = {
  whirlpool: "Whirlpool",
  wasabi_classic: "Wasabi",
  wabisabi: "WabiSabi",
  joinmarket: "JoinMarket",
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

/** Nach neuem Trace: Mix-Icons an der Adressgruppe nachziehen. */
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
  const alt = kopf.querySelector(".adress-mix-icons");
  if (alt) alt.remove();
  const leiste = zeichneMixIconLeiste(mixArtenDerGruppe(gruppe));
  if (!leiste) return;
  // Vor dem Betrag rechts einfügen, falls vorhanden.
  const betrag = kopf.querySelector(".adress-betrag");
  if (betrag) kopf.insertBefore(leiste, betrag);
  else kopf.append(leiste);
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

/** EUR-Zahl als Anzeigetext (ohne Kurs-Herkunft). */
function formatEurBetrag(eur) {
  if (!Number.isFinite(eur)) return "";
  if (Math.abs(eur) < 0.005) return "0 €";
  if (Math.abs(eur) < 10) {
    return `${eur.toLocaleString(formatLocale(), {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    })} €`;
  }
  return `${Math.round(eur).toLocaleString(formatLocale())} €`;
}

/**
 * EUR-Gegenwert zum Spotkurs aus der Kopfzeile (Zustand.kurs).
 * Leer, solange kein Kurs da ist — formatSats bleibt dann unverändert.
 */
function formatEurAusSats(sats) {
  const kurs = Zustand.kurs;
  if (!kurs || !(Number(kurs.amount) > 0)) return "";
  const eur = (Number(sats || 0) / 1e8) * Number(kurs.amount);
  return formatEurBetrag(eur);
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
  const stand = Zustand.kursSerie?.EUR;
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
  if (atTs) {
    const hist = tageskursAusSerie(atTs);
    if (hist) {
      return {
        text: formatEurBetrag((wert / 1e8) * hist.amount),
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

/** Summe EUR über ausgegebene UTXOs — je UTXO eigener Tageskurs. */
function eurInfoFuerSpentUtxos(utxos) {
  const liste = utxos || [];
  if (!liste.length) return null;
  let summe = 0;
  let warn = false;
  let treffer = false;
  const tage = new Set();
  for (const u of liste) {
    const sats = Number(u.value_sats || 0);
    const ts = spentZeitstempel(u);
    if (ts) {
      const hist = tageskursAusSerie(ts);
      if (hist) {
        summe += (sats / 1e8) * hist.amount;
        treffer = true;
        tage.add(hist.day);
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
    title = t("price.atDay", {
      day: [...tage][0],
      source: Zustand.kursSerie?.EUR?.source === "bundle"
        ? t("sources.rates.bundled")
        : (Zustand.kursSerie?.EUR?.source || "?"),
    });
  } else if (tage.size > 1) {
    title = t("price.atDaysMixed", { n: tage.size });
  }
  return { text: formatEurBetrag(summe), warn, title };
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
 * Betragszelle füllen; bei Spot-Fallback trotz Ausgabedatum gelb + Tooltip.
 * opts.atTs oder opts.spentUtxos (Summe je Tageskurs).
 */
function setzeSatsBetrag(el, sats, opts = {}) {
  if (!el) return;
  el.replaceChildren();
  const basis = formatSatsBasis(sats);
  el.append(document.createTextNode(basis));
  const info = opts.spentUtxos
    ? eurInfoFuerSpentUtxos(opts.spentUtxos)
    : eurInfoAusSats(sats, opts.atTs);
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

/** Immer BTC mit drei Nachkommastellen — für den Zeitstrahl, nicht für Listen. */
function formatBtcDrei(sats) {
  return `${(Number(sats || 0) / 1e8).toLocaleString(formatLocale(), {
    minimumFractionDigits: 3, maximumFractionDigits: 3,
  })} BTC`;
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

function walletSyncLaeuftFuer(walletId) {
  if (!walletId) return false;
  const jobs = Zustand.jobsNav?.jobs || [];
  for (const job of jobs) {
    if (job.kind !== "wallet_sync") continue;
    if (!(job.running || job.status === "running" || job.status === "queued")) {
      continue;
    }
    const ids = job.meta?.wallet_ids;
    if (Array.isArray(ids) && ids.length) {
      if (ids.includes(walletId)) return true;
      continue;
    }
    // Sync ohne explizite Wallet-Liste: Tip-Knopf darf global warten,
    // UTXO-Scan dieses Portfolios nicht pauschal sperren.
    if (job.meta?.wallet_id === walletId) return true;
  }
  return false;
}

/** Job-ID noch wirklich laufend/in Queue laut jobsNav (sonst stale GUI-Bindung). */
function jobNochAktiv(jobId) {
  if (!jobId) return false;
  const jobs = Zustand.jobsNav?.jobs || [];
  const j = jobs.find((x) => x && x.id === jobId);
  if (!j) {
    // Nav noch nicht da / älterer Server: lokale Bindung nur kurz vertrauen
    return Boolean(Zustand.rescanTimer);
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
  "header.sourceElectrumOwn": "Electrum privat",
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
  const z = ergebnis.summary || {};
  const voll = ergebnis.verfolgt_vollstaendig ?? (
    !(z.unresolved_inputs > 0) && Boolean(z.external_count || z.coinbase)
  );
  utxo.verfolgt = true;
  // Immer neu setzen — sonst bleibt bei „Scan neu" das alte Stand-Datum.
  utxo.verfolgt_ts = Math.floor(Date.now() / 1000);
  utxo.verfolgt_veraltet = false;
  utxo.verfolgt_vollstaendig = Boolean(voll);
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
  if (root.tx_class && TX_CLASS_ICON[root.tx_class]) {
    utxo.tx_class = root.tx_class;
    const arten = new Set(utxo.mix_arten || []);
    arten.add(root.tx_class);
    utxo.mix_arten = MIX_ICON_ORDER.filter((k) => arten.has(k));
  }
  // Auch Mix-Formen tiefer im Baum (Remix-Hops).
  const tief = mixArtenAusErgebnis(ergebnis);
  if (tief.length) {
    const arten = new Set([...(utxo.mix_arten || []), ...tief]);
    utxo.mix_arten = MIX_ICON_ORDER.filter((k) => arten.has(k));
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
        if (utxo.juengste_sats_ts) {
          eintrag.juengste_sats_ts = utxo.juengste_sats_ts;
        }
        if (utxo.value_sats != null) eintrag.value_sats = utxo.value_sats;
        if (utxo.address) eintrag.address = utxo.address;
        if (utxo.wallet) eintrag.wallet = utxo.wallet;
        if (utxo.time_label) eintrag.time_label = utxo.time_label;
        if (utxo.mix_arten) eintrag.mix_arten = utxo.mix_arten;
        if (utxo.tx_class) eintrag.tx_class = utxo.tx_class;
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

/** Marke „verfolgt · Datum" in der UTXO-Kopfzeile an den aktuellen Stand anpassen. */
function setzeVerfolgtMarke(oben, utxo) {
  if (!oben || !utxo || !utxo.verfolgt) return;
  const selektor =
    ".verfolgt-marke:not(.ausgegeben):not(.juengste-sats-marke):not(.ohne-herkunft-marke)";
  let marke = oben.querySelector(selektor);
  if (!marke) {
    marke = document.createElement("span");
    oben.append(marke);
  }
  marke.className = utxo.verfolgt_veraltet
    ? "verfolgt-marke veraltet"
    : "verfolgt-marke";
  const wann = utxo.verfolgt_ts
    ? formatKurzdatum(utxo.verfolgt_ts * 1000)
    : "";
  marke.textContent = wann ? t("trace.followedWhen", { wann }) : t("trace.followed");
  marke.title = utxo.verfolgt_veraltet
    ? t("trace.followedStale")
    : t("trace.followedCached");
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
  return /^(Verbunden\.|Verbindung fehlgeschlagen|TLS-Handshake fehlgeschlagen|Port geschlossen|Zertifikat nicht überprüfbar|Verbindung ohne TLS abgebrochen|Wechsel:|Neuer Peer |Peer .+ ausgefallen|Header-Cache fertig|Port 8333 wirkt blockiert|Filter-Treffer|Nur \d+)/.test(
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
  const buehne = document.querySelector(".buehne");
  if (buehne) buehne.classList.toggle("log-an", Boolean(an));
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

function macheDockSpalter() {
  const spalter = $("#dock-spalter");
  const spalten = document.querySelector(".dock-spalten");
  if (!spalter || !spalten) return;

  try {
    const gemerkt = localStorage.getItem(DOCK_SPALTE_MERKER);
    if (gemerkt) spalten.style.setProperty("--dock-log-pct", gemerkt);
  } catch (_) {
    /* ohne Speicher bleibt 50/50 */
  }

  let startX = 0;
  let startPct = 50;
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
    startPct = Number.parseFloat(roh) || 50;
    spalter.setPointerCapture(ereignis.pointerId);
    ereignis.preventDefault();
  });
  spalter.addEventListener("pointermove", (ereignis) => {
    if (!zieht) return;
    const breite = spalten.getBoundingClientRect().width;
    if (breite < 40) return;
    const delta = ((ereignis.clientX - startX) / breite) * 100;
    const pct = Math.min(80, Math.max(20, startPct + delta));
    spalten.style.setProperty("--dock-log-pct", `${Math.round(pct)}%`);
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
  oeffentlicheGefragt: false,
  headerJob: null,
  headerTimer: null,
  headerLogStand: { index: 0 },
  walletSyncJob: null,
  walletSyncTimer: null,
  walletSyncLogStand: { index: 0 },
  llmStatus: null,
  llmTimer: null,
  kurs: null,
  kursSerie: null,
  kursSerieLade: null,
  kursTimer: null,
  chatMessages: [],
  chatWartet: false,
  slashIndex: 0,
  traceJobs: new Map(),
  traceListe: null,
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
    const leer = document.createElement("div");
    leer.className = "nav-eintrag";
    leer.style.cursor = "default";
    leer.textContent = t("wallet.noHistoryYet");
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
    "trace", "steuerjahr", "sanktionen",
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
  "wallet", "trace", "steuerjahr", "sanktionen",
  "wallets", "einstellungen", "datenquellen",
];

const DATENQUELLEN_NAV_WARNUNG =
  "Eigener Node weder per RPC noch per Electrum konfiguriert, " +
  "Privatsphäre nur extrem zeitaufwändig geschützt";

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

async function zeigeWallet(walletId) {
  Zustand.walletId = walletId;
  zeigeAnsicht("wallet");

  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  setzeText($("#wallet-titel"), wallet ? wallet.name : t("common.wallet"));
  // Dieser GET liest nur den lokalen Cache — nie Electrum/P2P/Core.
  setzeText($("#wallet-meta"), t("common.loadingFromCache"));
  $("#adress-liste").hidden = true;
  $("#wallet-leer").hidden = true;

  const limit = $("#limit-wahl").value;
  const sort = $("#sort-wahl")?.value || "betrag";
  try {
    const daten = await api(
      `/wallets/${walletId}/utxos?limit=${limit}&sort=${encodeURIComponent(sort)}`,
    );
    zeichneUtxos(daten, wallet);
  } catch (fehler) {
    zeigeLeer(t("wallet.loadFailed", { msg: fehler.message }), "");
    setzeText($("#wallet-meta"), "");
  }
  aktualisiereScanAnzeige();
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
  const hatVerlauf = Boolean(daten.hat_verlauf);
  const hatUtxos = Boolean(daten.has_cache && daten.total_count);

  if (!daten.has_cache && !hatVerlauf) {
    zeigeLeer(
      t("wallet.emptyNoCache"),
      t("wallet.emptyNoCacheHint"),
    );
    setzeText($("#wallet-meta"), t("wallet.metaNeverScanned"));
    return;
  }
  if (daten.has_cache && !hatUtxos && !hatVerlauf) {
    zeigeLeer(
      t("wallet.emptyNoUtxo"),
      t("wallet.emptyNoUtxoHint"),
    );
    setzeText($("#wallet-meta"), t("wallet.metaZeroCache"));
    return;
  }

  const teile = [];
  if (daten.has_cache) {
    teile.push(`${daten.total_count} UTXO`, formatSats(daten.total_sats));
    if (daten.shown_count < daten.total_count) {
      teile.push(`angezeigt: ${daten.shown_count} · ${formatSats(daten.shown_sats)}`);
    }
    const pendOut = Number(daten.pending_spending_count || 0);
    const pendIn = Number(daten.pending_receive_count || 0);
    if (pendOut > 0 || pendIn > 0) {
      const bits = [];
      if (pendOut > 0) bits.push(t("wallet.metaPendingOut", { n: pendOut }));
      if (pendIn > 0) bits.push(t("wallet.metaPendingIn", { n: pendIn }));
      teile.push(bits.join(", "));
    }
  } else {
    teile.push("kein UTXO-Cache");
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
    ? `${tage} Tage — ein Jahr überschritten`
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
  betrag.textContent = formatSats(gruppe.total_sats);

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

function setzeUtxoTraceDaten(el, utxo) {
  if (!el || !utxo) return;
  if (utxo.key) el.dataset.key = utxo.key;
  el.dataset.verfolgtVollstaendig = utxoHatVollenHerkunftstrace(utxo) ? "1" : "0";
  if (utxo.juengste_sats_ts) {
    el.dataset.juengsteSatsTs = String(utxo.juengste_sats_ts);
  } else {
    delete el.dataset.juengsteSatsTs;
  }
}

function zeichneUtxoZeile(utxo) {
  const zeile = document.createElement("div");
  zeile.className = "utxo-zeile";
  if (utxo.spending_pending) zeile.classList.add("spending-pending-zeile");
  if (utxo.receive_pending) zeile.classList.add("receive-pending-zeile");
  setzeUtxoTraceDaten(zeile, utxo);

  const betrag = document.createElement("span");
  betrag.className = "betrag";
  betrag.textContent = formatSats(utxo.value_sats);

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

  const juengste = juengsteSatsMarke(utxo);
  if (juengste) zeile.append(juengste);

  // Woher der letzte externe Zufluss kam, sofern die Herkunft schon
  // ermittelt und die Adresse zuzuordnen ist.
  const herkunft = labelMarke(utxo.herkunft_label);
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
        ? `Läuft für „${name}“, nicht für dieses Wallet. ${art} · ${schritt}${danach}`
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
    folgeWalletSyncJob(jobId);
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
  Zustand.rescanJob = job.id;
  nimmJobLog(job);
  aktualisiereScanAnzeige(job.message || "wird gestartet…");
  zeichneNav();
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
  Zustand.rescanJob = null;
  Zustand.scanArt = null;
  Zustand.scanWalletId = null;
  Zustand.scanWalletName = "";
  Zustand.scanUtxoZahl = null;
  Zustand.scanRefreshUm = 0;
  Zustand.scanRefreshLaeuft = false;
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
}

// ---------------------------------------------------------------------------
// Nav: laufende Nutzer-Jobs (Server-Wahrheit, GUI-zu-fest)
// ---------------------------------------------------------------------------

async function ladeJobsNav() {
  try {
    const daten = await api("/jobs?recent_s=10");
    Zustand.jobsNav = {
      jobs: daten.jobs || [],
      scan_pipeline: daten.scan_pipeline || { current: null, queued: [] },
    };
    Zustand.jobsNavFehler = "";
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
    zeigeAnsicht("trace");
    if (kind === "trace" && job.meta?.target && $("#trace-ziel")) {
      $("#trace-ziel").value = job.meta.target;
    }
    return;
  }
  if (kind === "labels" || kind === "sanctions") {
    oeffneVerwaltung("datenquellen");
    return;
  }
  if (kind === "sanctions-check") {
    zeigeAnsicht("sanktionen");
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
    kasten.append(knopf);
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
  const scanId = Zustand.scanWalletId;
  const art = scanArtName();
  setzeText($("#rescan-text"), "Abbruch angefordert…");
  try {
    await api(`/jobs/${Zustand.rescanJob}`, { methode: "DELETE" });
  } catch (_) {
    /* Vorgang war bereits beendet */
  }
  // Knopf sofort freigeben — nicht auf den nächsten Poll warten
  // (sonst bleibt UTXO-Scan nach Abbruch/Quellenwechsel tot).
  beendeRescan(`${art} abgebrochen.`, false);
  await erfrischeWalletNachScan(scanId);
  await ladeJobsNav();
  setzeWalletScanGesperrt();
}

// ---------------------------------------------------------------------------
// Herkunft
// ---------------------------------------------------------------------------

const PUNKT_KLASSE = {
  internal: "knoten-eigen",
  external: "knoten-extern",
  external_unresolved: "knoten-offen",
  coinbase: "knoten-coinbase",
};

/**
 * Oberste Ebene (Adressen) startet zu. Darunter: gespeicherte Bäume offen,
 * ungescannte UTXOs zu — Aufklappen würde den Node fragen.
 */
async function ladeTraceListe() {
  const liste = $("#trace-liste");
  // /api/utxos ist Cache — Quellen-Hinweis gehört nur in die Scan-Leiste.
  liste.replaceChildren(hinweisZeile(t("common.loadingFromCache")));

  try {
    const daten = await api("/utxos");
    Zustand.traceListe = daten;
    zeichneTraceListe(daten);
  } catch (fehler) {
    liste.replaceChildren(hinweisZeile(t("common.couldNotLoad", { msg: fehler.message })));
  }
}

function hinweisZeile(text) {
  const zeile = document.createElement("div");
  zeile.className = "zweig-status";
  zeile.textContent = text;
  return zeile;
}

function zeichneTraceListe(daten) {
  const liste = $("#trace-liste");
  liste.replaceChildren();

  const teile = [`${daten.total_count} UTXO`, formatSats(daten.total_sats)];
  if (daten.wallets_ohne_cache && daten.wallets_ohne_cache.length > 0) {
    teile.push(`ohne Cache: ${daten.wallets_ohne_cache.join(", ")}`);
  }
  setzeText($("#trace-liste-zusatz"), teile.join(" · "));

  if (daten.total_count === 0 && !daten.hat_verlauf) {
    liste.append(hinweisZeile(
      "Keine UTXOs im Cache. Wallets zuerst scannen — in der Wallet-Ansicht " +
      "über „UTXO-Scan“."
    ));
    return;
  }

  for (const gruppe of daten.addresses || []) {
    liste.append(zeichneTraceAdressGruppe(gruppe));
  }

  liste.append(zeichneAusgegeben(daten));
}

/**
 * Bereits ausgegebene Outputs — Abschnitt bleibt zu, Inhalt ist Cache.
 *
 * Dieselbe Datei wie Steuerjahr. Der Kasten selbst bleibt zu, weil das
 * schnell hunderte Vorgänge sind; öffnet man ihn, stehen die Gruppen und
 * gespeicherten Bäume darin genauso offen wie beim aktuellen Bestand.
 */
function zeichneAusgegeben(daten) {
  const block = document.createElement("div");
  block.className = "ausgegeben-block";

  const verlauf = daten.verlauf || {};
  if (!daten.hat_verlauf) {
    block.append(hinweisZeile(
      "Ausgegebene Beträge sind nicht erfasst. „Verlaufsscan“ in der " +
      "Wallet-Ansicht holt die Historie dieses Wallets — danach lassen sich " +
      "auch längst abgeflossene Sats hier verfolgen."
    ));
    return block;
  }
  if (!verlauf.total_count) {
    block.append(hinweisZeile(t("wallet.noSpendsYet")));
    return block;
  }

  const kopf = document.createElement("button");
  kopf.type = "button";
  kopf.className = "adress-kopf";
  kopf.setAttribute("aria-expanded", "false");

  const klapp = document.createElement("span");
  klapp.className = "klapp";
  klapp.textContent = "▸";
  klapp.setAttribute("aria-hidden", "true");

  const titel = document.createElement("span");
  titel.textContent = t("wallet.spentSection");
  titel.setAttribute("title", t("wallet.spentSectionTitle"));

  const zusatz = document.createElement("span");
  zusatz.className = "zart";
  const pendingN = Number(verlauf.pending_count || daten.pending_spends || 0);
  // Nur BTC/sats — kein Spot-€ auf dem Brutto-Volumen (alte Ausgaben
  // würden sonst zum heutigen Kurs zu „Reichtum“). € je Vorgang steht
  // an den Adress-/UTXO-Zeilen zum Tageskurs am Ausgabedatum.
  zusatz.textContent =
    t("wallet.spentSummary", {
      count: verlauf.total_count,
      sats: formatSatsBasis(verlauf.total_sats),
    }) +
    (pendingN > 0
      ? ` · ${t("wallet.spentPendingCount", { n: pendingN })}`
      : "") +
    (verlauf.shown_count < verlauf.total_count
      ? ` · ${t("wallet.spentShown", { n: verlauf.shown_count })}`
      : "");

  kopf.append(klapp, titel, zusatz);

  const inhalt = document.createElement("div");
  inhalt.className = "ausgegeben-inhalt";
  inhalt.hidden = true;

  kopf.addEventListener("click", () => {
    const auf = inhalt.hidden;
    setzeKlapp(kopf, klapp, inhalt, auf);
    // Erst beim Aufklappen zeichnen: Bei hunderten Vorgängen kostet das
    // sonst bei jedem Öffnen der Ansicht Zeit, die niemand angefordert hat.
    if (auf && !inhalt.dataset.gezeichnet) {
      inhalt.dataset.gezeichnet = "ja";
      Promise.resolve(ladeKursSerie()).finally(() => {
        inhalt.replaceChildren();
        for (const gruppe of verlauf.addresses || []) {
          inhalt.append(zeichneTraceAdressGruppe(gruppe));
        }
      });
    }
  });

  block.append(kopf, inhalt);
  return block;
}

/**
 * Eine Adresse mit ihren UTXOs.
 *
 * Die Gruppe ist die oberste Ebene und startet zu. Beim Öffnen stehen
 * gespeicherte Bäume offen; ohne Baum bleibt das UTXO zu.
 */
function zeichneTraceAdressGruppe(gruppe) {
  const block = document.createElement("div");
  block.className = "adress-gruppe";
  block.dataset.address = gruppe.address;

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

  const wallet = document.createElement("span");
  wallet.className = "zart";
  wallet.textContent = gruppe.wallet || t("wallet.unknownWallet");

  const anzahl = document.createElement("span");
  anzahl.className = "adress-zahl";
  const zahlBasis =
    gruppe.utxo_count === 1 ? "1 UTXO" : `${gruppe.utxo_count} UTXOs`;
  const ausgabeZusatz = gruppeAusgegebenZusatz(gruppe);
  anzahl.textContent = ausgabeZusatz
    ? `${zahlBasis}, ${ausgabeZusatz}`
    : zahlBasis;

  kopf.append(klapp, adresse, wallet, anzahl);
  if (gruppe.utxos.some((u) => u.flagged)) {
    kopf.append(pille("krit", t("trace.listed")));
  }
  haengeGruppenJuengsteAn(kopf, gruppe);

  // Nur Icons, wenn gespeicherte Herkunft Mix-Formen kennt — sonst nichts.
  const mixLeiste = zeichneMixIconLeiste(mixArtenDerGruppe(gruppe));
  if (mixLeiste) kopf.append(mixLeiste);

  const betrag = document.createElement("span");
  betrag.className = "betrag adress-betrag";
  if ((gruppe.utxos || []).some((u) => u.spent || u.spent_pending)) {
    setzeSatsBetrag(betrag, gruppe.total_sats, { spentUtxos: gruppe.utxos });
  } else {
    betrag.textContent = formatSats(gruppe.total_sats);
  }
  kopf.append(betrag);

  const inhalt = document.createElement("div");
  inhalt.className = "trace-utxos";
  for (const utxo of gruppe.utxos) {
    inhalt.append(zeichneTraceWurzel(utxo));
  }
  setzeKlapp(kopf, klapp, inhalt, false);

  kopf.addEventListener("click", () => {
    const auf = inhalt.hidden;
    setzeKlapp(kopf, klapp, inhalt, auf);
    if (auf) {
      for (const wurzel of inhalt.querySelectorAll(".utxo-wurzel")) {
        if (typeof wurzel.oeffneAusCache === "function") wurzel.oeffneAusCache();
      }
    }
  });

  const kopfzeile = document.createElement("div");
  kopfzeile.className = "kopf-mit-verweis";
  kopfzeile.append(kopf);
  const extern = mempoolVerweis("address", gruppe.address);
  if (extern) kopfzeile.append(extern);

  block.append(kopfzeile, inhalt);
  return block;
}

function zeichneTraceWurzel(utxo) {
  const block = document.createElement("div");
  block.className = "utxo-wurzel";
  setzeUtxoTraceDaten(block, utxo);

  // Die ganze Zeile ist bedienbar, nicht nur das Dreieck: Ein Ziel von zwölf
  // Pixeln trifft niemand gern. Als Button statt als div, damit Tastatur und
  // Bildschirmleser ihn ohne Zusatzarbeit bekommen.
  // Title nicht an die ganze Zeile — sonst überschreibt er Mix-Icon-Tooltips.
  const zeile = document.createElement("button");
  zeile.type = "button";
  zeile.className = "baum-knoten utxo-kopf";

  const klapp = document.createElement("span");
  klapp.className = "klapp";
  klapp.title = "Herkunft dieses UTXO verfolgen";
  klapp.setAttribute("aria-hidden", "true");

  const punkt = document.createElement("span");
  punkt.className = "knoten-punkt knoten-eigen";

  const info = document.createElement("span");
  info.className = "knoten-info";

  const oben = document.createElement("span");
  oben.className = "knoten-oben";
  const betrag = document.createElement("span");
  betrag.className = "betrag";
  if (utxo.value_sats == null) {
    betrag.textContent = t("trace.amountPending");
    betrag.classList.add("zart");
  } else if (utxo.spent || utxo.spent_pending) {
    setzeSatsBetrag(betrag, utxo.value_sats, {
      atTs: spentZeitstempel(utxo) || undefined,
      spentUtxos: [utxo],
    });
  } else {
    betrag.textContent = formatSats(utxo.value_sats);
  }
  const wer = document.createElement("span");
  wer.textContent = utxo.wallet || t("wallet.unknownWallet");
  const adresse = document.createElement("span");
  adresse.className = "mono zart";
  adresse.textContent = utxo.address
    ? kuerze(utxo.address, 12, 6)
    : t("trace.addressPending");
  if (utxo.address) macheKopierbar(adresse, utxo.address, "Adresse");
  oben.append(betrag, wer, adresse);

  // Vor dem Aufklappen sichtbar machen, ob eine Analyse vorliegt: Dann geht
  // es sofort, sonst startet ein Lauf über die Datenquelle.
  if (utxo.verfolgt) {
    const marke = document.createElement("span");
    marke.className = utxo.verfolgt_veraltet
      ? "verfolgt-marke veraltet"
      : "verfolgt-marke";
    const wann = utxo.verfolgt_ts
      ? formatKurzdatum(utxo.verfolgt_ts * 1000)
      : "";
    marke.textContent = wann ? t("trace.followedWhen", { wann }) : t("trace.followed");
    marke.title = utxo.verfolgt_veraltet
      ? t("trace.followedStale")
      : t("trace.followedCached");
    oben.append(marke);

    const juengste = juengsteSatsMarke(utxo);
    if (juengste) oben.append(juengste);
  }

  // Ausgabe unterwegs (Mempool, eigener Node) — noch im Bestand sichtbar.
  if (utxo.spending_pending && !utxo.spent && !utxo.spent_pending) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke spending-pending";
    marke.textContent = t("trace.spendingPending");
    marke.title = t("trace.spendingPendingTitle");
    if (utxo.spent_txid) {
      macheKopierbar(marke, utxo.spent_txid, "Ausgaben-TxID");
    }
    oben.append(marke);
  }

  // Eigener Empfang noch im Mempool (Selbstüberweisung/Change).
  if (utxo.receive_pending && !utxo.spending_pending && !utxo.spent) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke receive-pending";
    marke.textContent = t("trace.receivePending");
    marke.title = t("trace.receivePendingTitle");
    oben.append(marke);
  }

  // Ausgegeben: Das muss in der Zeile stehen, sonst hielte man den Betrag für
  // Bestand — er ist längst weg. Pending = unbestätigt im Mempool (eigener Node).
  if (utxo.spent || utxo.spent_pending) {
    const marke = document.createElement("span");
    marke.className = utxo.spent_pending
      ? "verfolgt-marke ausgegeben pending"
      : "verfolgt-marke ausgegeben";
    if (utxo.spent_pending) {
      marke.textContent = t("trace.spentPending");
      marke.title = t("trace.spentPendingTitle");
    } else {
      const wann = formatAusgegebenWann(utxo);
      marke.textContent = wann
        ? t("trace.spentWhen", { wann })
        : t("trace.spent");
      marke.title = t("trace.spentTitle");
    }
    if (utxo.spent_txid) {
      macheKopierbar(marke, utxo.spent_txid, "Ausgaben-TxID");
    }
    oben.append(marke);
  }

  const unten = document.createElement("span");
  unten.className = "knoten-unten";
  const links = document.createElement("span");
  links.className = "knoten-unten-links";
  const utxoKennung = document.createElement("span");
  utxoKennung.className = "mono";
  utxoKennung.textContent = kuerze(utxo.key, 12, 8);
  macheKopierbar(utxoKennung, utxo.key, "UTXO (txid:vout)");
  links.append(utxoKennung);
  const ankunftText = formatAnkunft(utxo);
  if (ankunftText) {
    links.append(document.createTextNode(` · ${ankunftText}`));
  }
  unten.append(links);
  const rechts = document.createElement("span");
  rechts.className = "knoten-unten-rechts";
  rechts.hidden = true;
  unten.append(rechts);

  info.append(oben, unten);
  zeile.append(klapp, punkt, info);

  const zweig = document.createElement("div");
  zweig.className = "utxo-zweig";

  const kopfzeile = document.createElement("div");
  kopfzeile.className = "kopf-mit-verweis";
  kopfzeile.append(zeile);
  const neu = document.createElement("button");
  neu.type = "button";
  neu.className = "trace-link";
  neu.textContent = t("trace.rescan");
  neu.title = t("trace.rescanTitle");
  neu.addEventListener("click", (e) => {
    e.stopPropagation();
    zeigeHerkunftFuer(utxo.key, { neu: true });
  });
  kopfzeile.append(neu);
  const extern = mempoolVerweis("tx", (utxo.key || "").split(":")[0]);
  if (extern) kopfzeile.append(extern);

  block.append(kopfzeile, zweig);

  // Startet zu. Die Adressgruppe ruft oeffneAusCache, sobald sie selbst
  // aufgeht — dann nur, wenn der Baum im Cache liegt. Sonst würde jeder
  // sichtbare Eintrag den Node fragen.
  setzeKlapp(zeile, klapp, zweig, false);

  function oeffneAusCache() {
    if (!utxo.verfolgt) return;
    setzeKlapp(zeile, klapp, zweig, true);
    if (zweig.dataset.geladen === "ja" || zweig.dataset.geladen === "laeuft") return;
    ladeGespeichertenZweig(utxo, zweig, klapp).then((ok) => {
      if (!ok) setzeKlapp(zeile, klapp, zweig, false);
    });
  }
  block.oeffneAusCache = oeffneAusCache;

  zeile.addEventListener("click", (ereignis) => {
    // Der zweite Klick eines Doppelklicks würde sonst gleich wieder
    // zuklappen. So wirkt ein Doppelklick wie ein einfacher.
    if (ereignis.detail > 1) return;
    // Wer eine TxID mit der Maus markiert, will nicht aufklappen.
    if (window.getSelection().toString()) return;

    const auf = zweig.hidden;
    setzeKlapp(zeile, klapp, zweig, auf);
    if (auf && !zweig.dataset.geladen) {
      oeffneZweig(utxo, zweig, klapp);
    }
  });

  return block;
}

/** Liest nur den gespeicherten Baum. Kein Node, kein Job. */
async function ladeGespeichertenZweig(utxo, zweig, klapp) {
  zweig.dataset.geladen = "laeuft";
  zweig.replaceChildren(hinweisZeile(t("common.looking")));
  try {
    const gespeichert = await api(`/trace?target=${encodeURIComponent(utxo.key)}`);
    if (gespeichert && gespeichert.vorhanden) {
      zweig.dataset.geladen = "ja";
      zeichneZweig(gespeichert.ergebnis, zweig, utxo, klapp);
      merkeTraceAmUtxo(utxo, gespeichert.ergebnis);
      aktualisiereTraceWurzelKopf(utxo, zweig.closest(".utxo-wurzel"));
      zweig.prepend(gespeicherterKopf(gespeichert, utxo, zweig, klapp));
      return true;
    }
  } catch (fehler) {
    // Datei fehlt oder ist unlesbar — Aufrufer entscheidet, ob ein Lauf startet.
  }
  zweig.dataset.geladen = "";
  zweig.replaceChildren();
  return false;
}

async function oeffneZweig(utxo, zweig, klapp) {
  if (await ladeGespeichertenZweig(utxo, zweig, klapp)) return;
  starteZweigTrace(utxo, zweig, klapp);
}

/**
 * Kopfzeile über einem gespeicherten Baum: wann erhoben, und der Weg zurück
 * zu einer frischen Analyse.
 *
 * Bei geänderter Adressmenge steht dort zusätzlich, woran das Ergebnis
 * womöglich vorbeigeht. Verworfen wird deshalb nichts — die Unsicherheit
 * benannt zu haben ist mehr wert als eine leere Ansicht.
 */
function gespeicherterKopf(gespeichert, utxo, zweig, klapp) {
  const kopf = document.createElement("div");
  kopf.className = "zweig-kopf";

  const stand = document.createElement("span");
  stand.className = "zweig-stand";
  stand.textContent = gespeichert.erstellt_ts
    ? t("trace.snapshotAt", { time: formatZeitpunkt(gespeichert.erstellt_ts * 1000) })
    : t("trace.storedAnalysis");
  kopf.append(stand);

  if (gespeichert.veraltet) {
    const warn = document.createElement("span");
    warn.className = "zweig-warnung";
    const dazu = gespeichert.adressen_seither;
    warn.textContent =
      dazu && dazu > 0
        ? t("trace.sinceAnalysisAdded", { count: formatZahl(dazu) })
        : t("trace.sinceAnalysisChanged");
    kopf.append(warn);
  }

  return kopf;
}

/**
 * Startet die Analyse für genau einen UTXO und rendert sie in *zweig*.
 * *followup*: optional ``full`` (Lücken schließen), Legacy ``tx_oriented`` /
 * ``resolve_unresolved``.
 */
async function starteZweigTrace(utxo, zweig, klapp, followup = null) {
  zweig.dataset.geladen = "laeuft";

  const status = document.createElement("div");
  status.className = "zweig-status";
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  spinner.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.textContent = followup
    ? t("trace.folgeStart")
    : t("trace.analyseStart");
  const abbruch = document.createElement("button");
  abbruch.type = "button";
  abbruch.className = "knopf knopf-klein";
  abbruch.textContent = t("common.cancel");
  abbruch.title = "Bricht diese Analyse ab. Andere laufen weiter.";
  status.append(spinner, text, abbruch);
  zweig.replaceChildren(status);

  let jobId = null;
  let timer = null;

  const aufraeumen = () => {
    clearInterval(timer);
    Zustand.traceJobs.delete(utxo.key);
  };

  abbruch.addEventListener("click", async () => {
    text.textContent = t("common.abortRequested");
    if (jobId) {
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* war bereits beendet */
      }
    }
  });

  const fehlschlag = (meldung) => {
    aufraeumen();
    zweig.dataset.geladen = "";
    zweig.replaceChildren(hinweisZeile(meldung));
  };

  try {
    const daten = { target: utxo.key };
    if (followup) daten.followup = followup;
    const job = await api("/trace", {
      methode: "POST",
      daten,
    });
    jobId = job.id;
    Zustand.traceJobs.set(utxo.key, jobId);
  } catch (fehler) {
    fehlschlag(t("trace.analyseFail", { msg: fehler.message }));
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      text.textContent = job.message || t("common.running");
      if (job.running) return;

      aufraeumen();
      if (job.status === "done" && job.result) {
        zweig.dataset.geladen = "ja";
        zeichneZweig(job.result, zweig, utxo, klapp);
        merkeTraceAmUtxo(utxo, job.result);
        // Kopfzeile am konkreten Block (gezielte Suche startet oft mit „…“).
        aktualisiereTraceWurzelKopf(utxo, zweig.closest(".utxo-wurzel"));
        // Stand-Zeile wie nach Cache-Laden — sonst fehlt sie bis zum Refresh.
        if (job.result.found) {
          zweig.prepend(gespeicherterKopf({
            erstellt_ts: utxo.verfolgt_ts,
            veraltet: false,
            adressen_seither: 0,
          }, utxo, zweig, klapp));
        }
      } else if (job.status === "cancelled") {
        fehlschlag(t("trace.cancelled"));
      } else {
        fehlschlag(job.error || t("trace.analyseFailShort"));
      }
    } catch (fehler) {
      fehlschlag(fehler.message);
    }
  }, 900);
}

function folgeLueckenOffen(ergebnis) {
  // Bis jedes Blatt external (rot) oder coinbase (lila) ist, bleibt Entwirren offen.
  if (ergebnis && ergebnis.found && ergebnis.verfolgt_vollstaendig === false) {
    return true;
  }
  if (ergebnis && ergebnis.followup_tx_oriented_done && ergebnis.verfolgt_vollstaendig) {
    return false;
  }
  const suggestedTx = Boolean(ergebnis.followup_tx_oriented_suggested)
    && !ergebnis.followup_tx_oriented_done;
  const suggestedBundled = Boolean(
    ergebnis.followup_resolve_unresolved_suggested
    || (ergebnis.summary && ergebnis.summary.unresolved_inputs > 0),
  );
  return suggestedTx || suggestedBundled;
}

function folgeHinweisText(ergebnis) {
  if (ergebnis.verfolgt_vollstaendig && ergebnis.followup_tx_oriented_done) {
    return t("trace.folgeDoneHint");
  }
  if (folgeLueckenOffen(ergebnis)) {
    return t("trace.folgeLueckenHint");
  }
  if (ergebnis.verfolgt_vollstaendig) {
    return t("trace.folgeDoneHint");
  }
  return t("trace.folgeMore");
}

function zeichneFolgeBand(ergebnis, zweig, utxo, klapp) {
  const offen = folgeLueckenOffen(ergebnis);
  const doneTx = Boolean(ergebnis.followup_tx_oriented_done)
    && Boolean(ergebnis.verfolgt_vollstaendig);
  if (!offen && !doneTx) return;

  const band = document.createElement("div");
  band.className = "zweig-folge";
  const text = document.createElement("p");
  text.className = "zweig-folge-text";
  text.textContent = folgeHinweisText(ergebnis);
  const knoepfe = document.createElement("div");
  knoepfe.className = "zweig-folge-knoepfe";

  if (offen && utxo && klapp) {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "knopf knopf-klein";
    knopf.textContent = t("trace.folgeLuecken");
    knopf.title = t("trace.folgeLueckenTitle");
    knopf.addEventListener("click", () => {
      if (!window.confirm(t("trace.folgeLueckenConfirm"))) return;
      starteZweigTrace(utxo, zweig, klapp, "full");
    });
    knoepfe.append(knopf);
  } else if (doneTx) {
    const erledigt = document.createElement("span");
    erledigt.className = "zweig-folge-erledigt";
    erledigt.textContent = t("trace.folgeDone");
    erledigt.title = t("trace.folgeDoneTitle");
    knoepfe.append(erledigt);
  }

  band.append(text, knoepfe);
  zweig.append(band);
}

function setzeWurzelTxClass(zweig, ergebnis) {
  /** Soft-Label (+ Icon) rechts neben Timestamp in der UTXO-Wurzelzeile. */
  const wurzel = zweig && zweig.closest(".utxo-wurzel");
  if (!wurzel) return;
  const unten = wurzel.querySelector(".utxo-kopf .knoten-unten");
  if (!unten) return;
  let rechts = unten.querySelector(".knoten-unten-rechts");
  if (!rechts) {
    rechts = document.createElement("span");
    rechts.className = "knoten-unten-rechts";
    unten.append(rechts);
  }
  fuelleTxClassRechts(rechts, ergebnis.root || ergebnis);
}

function zeichneZweig(ergebnis, zweig, utxo = null, klapp = null) {
  zweig.replaceChildren();

  if (!ergebnis.found) {
    zweig.append(hinweisZeile(ergebnis.error || t("trace.none")));
    zweig.dataset.geladen = "";
    return;
  }

  const klasseHinweis = softTxClassLabel(ergebnis.root || ergebnis);
  setzeWurzelTxClass(zweig, ergebnis);

  if (ergebnis.children.length === 0) {
    zweig.append(hinweisZeile(
      klasseHinweis
        ? t("trace.coinjoinOwnOnlyEmpty")
        : t("trace.noInflows"),
    ));
    return;
  }

  zweig.append(zeichneKnotenListe(ergebnis.children));
  zeichneFolgeBand(ergebnis, zweig, utxo, klapp);

  const vorbehalt = vorbehaltText(ergebnis.summary);
  const fuss = document.createElement("div");
  fuss.className = "vorbehalt";
  fuss.style.paddingTop = "6px";
  const quelle = ergebnis.source ? `Quelle: ${ergebnis.source}. ` : "";
  fuss.textContent = quelle + vorbehalt;
  zweig.append(fuss);
}

/** Gezielte Suche nach TxID oder UTXO — Ergebnis erscheint oben in der Liste. */
async function starteTrace() {
  const roh = $("#trace-ziel").value.trim();
  if (!roh) return;

  $("#trace-start").disabled = true;
  $("#trace-meldung").hidden = true;

  // Reine TxID → Output #0 (explizit im Key und im Feld).
  const key = roh.includes(":") ? roh : `${roh}:0`;
  if (!roh.includes(":")) {
    $("#trace-ziel").value = key;
  }

  // Schon offene gezielte Suche zum selben UTXO wiederverwenden — sonst
  // stapeln sich Blöcke und der alte bleibt bei „0 sats“ / „…“.
  let block = document.querySelector(
    `#trace-liste .trace-suche .utxo-wurzel[data-key="${CSS.escape(key)}"]`,
  );
  let utxo = null;
  if (block) {
    utxo = {
      key,
      value_sats: null,
      address: "",
      wallet: t("trace.targetedWallet"),
      time_label: "",
    };
    const zweig = block.querySelector(".utxo-zweig");
    const klapp = block.querySelector(".klapp");
    if (zweig) {
      zweig.dataset.geladen = "";
      zweig.replaceChildren();
      zweig.hidden = false;
      if (klapp) klapp.textContent = "▾";
      // Frisch laden (Cache oder Job) und Kopfzeile danach setzen.
      await oeffneZweig(utxo, zweig, klapp);
      aktualisiereTraceWurzelKopf(utxo, block);
    }
    block.scrollIntoView({ behavior: "smooth", block: "nearest" });
    $("#trace-start").disabled = false;
    return;
  }

  utxo = {
    key,
    value_sats: null,
    address: "",
    wallet: t("trace.targetedWallet"),
    time_label: "",
  };

  // Steht ohne Adressgruppe ganz oben: Das UTXO muss nicht in der Liste
  // vorkommen — es kann längst ausgegeben sein.
  block = zeichneTraceWurzel(utxo);
  const huelle = document.createElement("div");
  huelle.className = "trace-suche";
  huelle.append(block);

  $("#trace-liste").prepend(huelle);
  const zweig = block.querySelector(".utxo-zweig");
  const klapp = block.querySelector(".klapp");
  // Direkt öffnen (nicht nur click) — sonst läuft der Trace ohne await und
  // die Kopfzeile wird nicht zuverlässig nachgezogen.
  if (zweig && klapp) {
    const zeile = block.querySelector(".utxo-kopf");
    if (zeile) zeile.setAttribute("aria-expanded", "true");
    zweig.hidden = false;
    klapp.textContent = "▾";
    await oeffneZweig(utxo, zweig, klapp);
    aktualisiereTraceWurzelKopf(utxo, block);
  }
  huelle.scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("#trace-start").disabled = false;
}

function traceMeldung(text, art) {
  const kasten = $("#trace-meldung");
  kasten.className = `hinweis hinweis-${art}`;
  setzeText(kasten, text);
  kasten.hidden = false;
}

/**
 * Sprung aus der Wallet-Ansicht.
 *
 * Das UTXO liegt seit der Gruppierung eine Ebene tiefer: erst die Adresse
 * aufklappen, dann den Eintrag selbst.
 */
function findeTraceUtxo(schluessel) {
  const listen = [
    ...(Zustand.traceListe?.addresses || []),
    ...(Zustand.traceListe?.verlauf?.addresses || []),
  ];
  for (const gruppe of listen) {
    for (const utxo of gruppe.utxos || []) {
      if (utxo.key === schluessel) return utxo;
    }
  }
  return { key: schluessel };
}

async function zeigeHerkunftFuer(schluessel, { neu = false } = {}) {
  zeigeAnsicht("trace");
  if (!Zustand.traceListe) {
    await ladeTraceListe();
  }

  const block = document.querySelector(
    `#trace-liste .utxo-wurzel[data-key="${CSS.escape(schluessel)}"]`
  );
  if (!block) {
    // Typisch: Output steht unter „Bereits ausgegeben“, fehlt aber in der
    // Herkunftsliste. Suchfeld vorausfüllen — Start bleibt bewusste Aktion.
    const feld = $("#trace-ziel");
    if (feld) {
      feld.value = schluessel;
      feld.focus();
      feld.select();
    }
    traceMeldung(
      `${kuerze(schluessel, 12, 8)} steht nicht in der Herkunftsliste ` +
      "(oft schon ausgegeben). Steht oben im Suchfeld — „Gezielt tracen“ " +
      "startet die Analyse.",
      "warn"
    );
    return;
  }

  const gruppe = block.closest(".adress-gruppe");
  if (gruppe) {
    const gruppenKopf = gruppe.querySelector(".adress-kopf");
    if (gruppenKopf.getAttribute("aria-expanded") !== "true") {
      gruppenKopf.click();
    }
  }

  const kopf = block.querySelector(".utxo-kopf");
  const zweig = block.querySelector(".utxo-zweig");
  const klapp = block.querySelector(".klapp");
  if (neu) {
    if (zweig) {
      zweig.hidden = false;
      if (klapp) klapp.textContent = "▾";
      if (kopf) kopf.setAttribute("aria-expanded", "true");
      logZeile(
        `Starte Scan neu für ${kuerze(schluessel, 12, 8)}…`,
        undefined,
        walletNameZu(Zustand.walletId),
      );
      await starteZweigTrace(findeTraceUtxo(schluessel), zweig, klapp);
    }
  } else if (kopf && kopf.getAttribute("aria-expanded") !== "true") {
    kopf.click();
  }
  block.scrollIntoView({ behavior: "smooth", block: "center" });
}

function vorbehaltText(z) {
  const teile = [];
  if (z.external_count > 0) {
    teile.push(
      `Aufgelöste externe Zuflüsse: ${formatSats(z.external_sats)}. ` +
      "Hinter fremden Adressen endet die Analyse."
    );
  }
  if (z.unresolved_inputs > 0) {
    teile.push(
      `${z.unresolved_inputs} weitere Eingänge wurden nicht aufgelöst — ` +
      "ihre Beträge fehlen in dieser Summe. Sie ist damit eine Untergrenze, " +
      "keine Gesamtsumme."
    );
  }
  if (z.coinbase) {
    teile.push("Ein Zweig endet bei frisch geschürften Sats.");
  }
  return teile.join(" ");
}

function zeichneKnotenListe(knoten) {
  const huelle = document.createDocumentFragment();
  for (const k of knoten) {
    huelle.append(zeichneKnoten(k));
  }
  return huelle;
}

function zeichneKnoten(knoten) {
  const block = document.createElement("div");

  // Die ganze Zeile ist der Treffer — nicht das Dreieck allein.
  // Erste Ebene unter der UTXO-Wurzel zeichnet zeichneZweig sofort (sichtbar).
  // Tiefere Ebenen erst beim Aufklappen — große CoinJoin-/Remix-Bäume sonst
  // tausende DOM-Knoten und zehntausende Pixel Listenhöhe auf einmal.
  const zeile = document.createElement(knoten.expandable ? "button" : "div");
  zeile.className = "baum-knoten";
  if (knoten.expandable) {
    zeile.type = "button";
    zeile.setAttribute("aria-expanded", "false");
  }

  const klapp = document.createElement("span");
  klapp.className = knoten.expandable ? "klapp" : "klapp leer";
  klapp.textContent = knoten.expandable ? "▸" : "·";
  klapp.setAttribute("aria-hidden", "true");
  // Title nur am Pfeil — sonst überschreibt „Zweig auf-/zuklappen“ das
  // Soft-Label am Mix-Icon (native title am Button gewinnt über Kinder).
  if (knoten.expandable) klapp.title = "Zweig auf- und zuklappen";

  const punkt = document.createElement("span");
  punkt.className = `knoten-punkt ${PUNKT_KLASSE[knoten.type] || "knoten-extern"}`;

  const info = document.createElement("span");
  info.className = "knoten-info";

  const oben = document.createElement("span");
  oben.className = "knoten-oben";
  if (knoten.amount_sats > 0) {
    const betrag = document.createElement("span");
    betrag.className = "betrag";
    betrag.textContent = formatSats(knoten.amount_sats);
    oben.append(betrag);
  }
  const wer = document.createElement("span");
  if (knoten.type === "internal") {
    wer.textContent = knoten.wallet || t("trace.ownWallet");
  } else if (knoten.type === "external_unresolved") {
    wer.textContent = t("trace.bundledInputs", { count: knoten.input_count });
  } else if (knoten.type === "coinbase") {
    wer.textContent = t("trace.coinbase");
  } else {
    wer.textContent = t("trace.external");
  }
  oben.append(wer);

  if (knoten.address) {
    const adresse = document.createElement("span");
    adresse.className = "mono zart";
    adresse.textContent = kuerze(knoten.address, 12, 6);
    macheKopierbar(adresse, knoten.address, "Adresse");
    oben.append(adresse);
  }

  // Wem die fremde Adresse zuzuordnen ist — das ist an einem externen Ende
  // die eigentliche Auskunft.
  const marke = labelMarke(knoten.label);
  if (marke) oben.append(marke);

  info.append(oben);

  const klasseText = softTxClassLabel(knoten);
  const externKurz =
    knoten.type === "external" ? t("trace.externalInput") : "";
  const ankunftText = knoten.time_label ? formatAnkunft(knoten) : "";
  if (knoten.from_utxo || ankunftText || klasseText || externKurz) {
    const unten = document.createElement("span");
    unten.className = "knoten-unten";
    const links = document.createElement("span");
    links.className = "knoten-unten-links";
    if (knoten.from_utxo) {
      const utxoKennung = document.createElement("span");
      utxoKennung.className = "mono";
      utxoKennung.textContent = kuerze(knoten.from_utxo, 12, 8);
      macheKopierbar(utxoKennung, knoten.from_utxo, "UTXO (txid:vout)");
      links.append(utxoKennung);
    }
    if (externKurz) {
      links.append(
        document.createTextNode((knoten.from_utxo ? " · " : "") + externKurz),
      );
    }
    if (ankunftText) {
      links.append(
        document.createTextNode(
          (knoten.from_utxo || externKurz ? " · " : "") + ankunftText,
        ),
      );
    }
    unten.append(links);
    if (klasseText) {
      const rechts = document.createElement("span");
      rechts.className = "knoten-unten-rechts";
      fuelleTxClassRechts(rechts, knoten);
      unten.append(rechts);
    }
    info.append(unten);
  }

  const notizText = knotenNotiz(knoten);
  if (notizText) {
    const notiz = document.createElement("span");
    notiz.className = "knoten-notiz";
    notiz.textContent = notizText;
    info.append(notiz);
  }

  zeile.append(klapp, punkt, info);

  const kopfzeile = document.createElement("div");
  kopfzeile.className = "kopf-mit-verweis";
  kopfzeile.append(zeile);
  // Tx vor Adresse: VIN/VOUT-Grafik. Adresse nur, wenn keine Tx bekannt
  // (reine Adresszeilen bleiben bei /address/… — siehe Adressgruppen).
  const txid =
    (knoten.from_utxo || "").split(":")[0]
    || knoten.txid
    || "";
  const extern = txid
    ? mempoolVerweis("tx", txid)
    : (knoten.address ? mempoolVerweis("address", knoten.address) : null);
  if (extern) kopfzeile.append(extern);
  block.append(kopfzeile);

  if (knoten.expandable) {
    const kinder = document.createElement("div");
    kinder.className = "baum-kinder";
    kinder.hidden = true;
    block.append(kinder);

    zeile.addEventListener("click", (ereignis) => {
      if (ereignis.detail > 1) return;
      if (window.getSelection().toString()) return;
      const auf = kinder.hidden;
      if (auf && !kinder.dataset.gezeichnet) {
        kinder.dataset.gezeichnet = "ja";
        kinder.append(zeichneKnotenListe(knoten.children || []));
      }
      kinder.hidden = !auf;
      klapp.textContent = auf ? "▾" : "▸";
      zeile.setAttribute("aria-expanded", String(auf));
    });
  }

  return block;
}

// ---------------------------------------------------------------------------
// Steuerjahr
// ---------------------------------------------------------------------------

function fuelleHaltefristAuswahl(select, gewaehlt, jahre) {
  if (!select) return;
  const liste = jahre && jahre.length ? jahre : [1, 2, 3, 4, 5, 7, 10, 15, 20];
  const wert = String(gewaehlt ?? 1);
  // Sprache in den Stempel: sonst bleiben Roh-Keys / DE-Labels nach initI18n bzw. Umschalten.
  const lang =
    (window.SatSageI18n && typeof window.SatSageI18n.currentLang === "function"
      && window.SatSageI18n.currentLang())
    || "de";
  const stempel = JSON.stringify({ liste, lang });
  if (select.dataset.gefuellt === stempel) {
    select.value = wert;
    if (select.value !== wert) select.value = "1";
    return;
  }
  select.replaceChildren();
  const keine = document.createElement("option");
  keine.value = "0";
  keine.textContent = t("common.none");
  select.append(keine);
  for (const n of liste) {
    const option = document.createElement("option");
    option.value = String(n);
    option.textContent =
      n === 1 ? t("tax.yearsOne") : t("tax.yearsN", { n });
    select.append(option);
  }
  select.dataset.gefuellt = stempel;
  select.value = wert;
  if (select.value !== wert) select.value = "1";
}

function steuerEinstellungen() {
  return Zustand.config?.steuer || {};
}

async function ladeSteuerjahr() {
  const jahr = $("#jahr-wahl").value;
  const frist = $("#frist-wahl").value;
  const stichtag = steuerEinstellungen().stichtag || "";
  const abfrage =
    `?jahr=${encodeURIComponent(jahr)}&frist=${encodeURIComponent(frist)}` +
    `&stichtag=${encodeURIComponent(stichtag)}`;

  try {
    const daten = await api(`/tax${abfrage}`);
    Zustand.steuer = daten;
    zeichneSteuerjahr(daten);
  } catch (fehler) {
    const kasten = $("#steuer-meldung");
    kasten.className = "hinweis hinweis-krit";
    setzeText(kasten, `Auswertung fehlgeschlagen: ${fehler.message}`);
    kasten.hidden = false;
  }
}

function fuelleJahresauswahl(jahre, gewaehlt) {
  const wahl = $("#jahr-wahl");
  if (wahl.dataset.gefuellt === JSON.stringify(jahre)) return;
  wahl.replaceChildren();
  for (const jahr of jahre) {
    const option = document.createElement("option");
    option.value = jahr;
    option.textContent = jahr;
    wahl.append(option);
  }
  wahl.dataset.gefuellt = JSON.stringify(jahre);
  if (gewaehlt) wahl.value = gewaehlt;
}

function zeichneSteuerjahr(daten) {
  fuelleJahresauswahl(daten.verfuegbare_jahre || [], daten.jahr);
  fuelleHaltefristAuswahl(
    $("#frist-wahl"),
    daten.haltefrist_jahre,
    steuerEinstellungen().haltefrist_jahre_auswahl,
  );
  zeichneAbgaenge(daten);

  const k = daten.kennzahlen;
  const kasten = $("#steuer-kennzahlen");
  kasten.replaceChildren();

  const kennzahlen = [
    ["Bestand gesamt", formatSats(k.gesamt_sats), `${k.gesamt_count} UTXOs`, ""],
    ["außerhalb Haltefrist", formatSats(k.erfuellt_sats),
     `${k.erfuellt_count} UTXOs`, "gut"],
    ["innerhalb Haltefrist", formatSats(k.offen_sats),
     k.naechste_frist ? `nächste am ${k.naechste_frist}` : `${k.offen_count} UTXOs`,
     "warn"],
  ];
  if (k.ungeprueft_count > 0) {
    kennzahlen.push([
      "Ohne Herkunftsanalyse", formatSats(k.ungeprueft_sats),
      `${k.ungeprueft_count} UTXOs — Frist evtl. länger`, "warn",
    ]);
  }
  if (k.ohne_datum > 0) {
    kennzahlen.push([
      "Ohne Datum", String(k.ohne_datum), "unbestätigt, nicht gewertet", "",
    ]);
  }

  for (const [titel, wert, zusatz, art] of kennzahlen) {
    const zelle = document.createElement("div");
    zelle.className = "kennzahl";
    const t = document.createElement("span");
    t.className = "kennzahl-titel";
    t.textContent = titel;
    const w = document.createElement("span");
    w.className = `kennzahl-wert ${art}`.trim();
    w.textContent = wert;
    const z = document.createElement("span");
    z.className = "kennzahl-zusatz";
    z.textContent = zusatz;
    zelle.append(t, w, z);
    kasten.append(zelle);
  }

  zeichneZeitstrahl(daten);

  setzeText(
    $("#steuer-zusatz"),
    `${daten.stichtag_label} · Haltefrist ` +
    (daten.haltefrist_jahre ? `${daten.haltefrist_jahre} Jahr(e)` : "keine") +
    (daten.stichtag_regel ? ` · Altbestand bis ${daten.stichtag_regel}` : "")
  );

  const koerper = $("#steuer-koerper");
  koerper.replaceChildren();

  for (const eintrag of daten.eintraege) {
    const zeile = document.createElement("tr");

    const datum = document.createElement("td");
    datum.className = "zahl";
    datum.textContent = eintrag.datum;
    if (eintrag.herkunft) {
      const h = document.createElement("div");
      h.className = "zart";
      h.textContent = eintrag.herkunft;
      datum.append(h);
    }

    const betrag = document.createElement("td");
    betrag.className = "r betrag";
    betrag.textContent = formatSats(eintrag.value_sats);

    const wallet = document.createElement("td");
    wallet.textContent = eintrag.wallet;

    const adresse = document.createElement("td");
    adresse.className = "mono zart";
    adresse.textContent = kuerze(eintrag.address, 12, 6);
    macheKopierbar(adresse, eintrag.address, "Adresse");

    const dauer = document.createElement("td");
    dauer.className = "r zahl";
    dauer.textContent = `${eintrag.haltedauer_tage} T`;

    const grundlage = document.createElement("td");
    const marke = document.createElement("span");
    marke.className = eintrag.geprueft ? "grundlage-ok" : "grundlage-offen";
    marke.textContent = eintrag.grundlage_label;
    marke.title = eintrag.geprueft
      ? "Anschaffungsdatum aus der Herkunftsanalyse"
      : "Nur das Entstehungsdatum des Outputs. Bei Wechselgeld oder " +
        "Konsolidierung ist das zu jung — die Haltefrist kann in Wahrheit " +
        "länger sein.";
    grundlage.append(marke);
    if (eintrag.herkunft) {
      const zusatz = document.createElement("div");
      zusatz.className = "zart";
      zusatz.textContent = eintrag.herkunft;
      grundlage.append(zusatz);
    }

    const status = document.createElement("td");
    status.className = "r";
    const hatStichtag = Boolean(daten.stichtag_regel);
    let statusText = haltefristBeschriftung(eintrag, hatStichtag);
    if (!eintrag.erfuellt && eintrag.frist_ende && !eintrag.neuvermoegen) {
      statusText += ` · ab ${eintrag.frist_ende}`;
    }
    status.append(pille(eintrag.erfuellt ? "gut" : "warn", statusText));

    const extern = mempoolVerweis("tx", eintrag.txid);
    if (extern) status.append(extern);

    zeile.append(datum, betrag, wallet, adresse, dauer, grundlage, status);
    koerper.append(zeile);
  }

  if (daten.eintraege.length === 0) {
    const zeile = document.createElement("tr");
    const zelle = document.createElement("td");
    zelle.colSpan = 7;
    zelle.className = "zart";
    zelle.style.padding = "20px 0";
    zelle.textContent =
      "Keine UTXOs bis zum Stichtag. Wallets zuerst scannen (UTXO-Scan in der " +
      "Wallet-Ansicht).";
    zeile.append(zelle);
    koerper.append(zeile);
  }

  setzeText($("#steuer-vorbehalt"), (daten.hinweise || []).join(" "));
  $("#steuer-meldung").hidden = true;
}

/**
 * Zeichnet die Zeitachse der UTXOs.
 *
 * X und Y kommen als Prozentwerte aus core/tax.zeitstrahl — hier wird
 * nur gezeichnet. So bleibt die Rechnerei testbar und die Darstellung
 * unabhängig von der Fensterbreite.
 */
function zeichneZeitstrahl(daten) {
  const karte = $("#zeitstrahl-karte");
  const strahl = daten.zeitstrahl;

  if (!strahl || !strahl.vorhanden || strahl.events.length === 0) {
    karte.hidden = true;
    return;
  }
  karte.hidden = false;

  const yAchse = $("#achse-y");
  if (yAchse) {
    yAchse.replaceChildren();
    const oben = document.createElement("span");
    oben.textContent = formatBtcDrei(strahl.max_sats || 0);
    const unten = document.createElement("span");
    unten.textContent = formatBtcDrei(0);
    yAchse.append(oben, unten);
  }

  const spur = $("#achse-spur");
  spur.replaceChildren();

  const linie = document.createElement("div");
  linie.className = "achse-linie";
  spur.append(linie);

  if (strahl.frist_pos !== null && strahl.frist_pos !== undefined) {
    const grenze = document.createElement("div");
    grenze.className = "achse-frist";
    grenze.style.left = `${strahl.frist_pos}%`;

    const beschriftung = document.createElement("span");
    // Nah am rechten Rand würde die Beschriftung sonst abgeschnitten.
    beschriftung.className =
      strahl.frist_pos > 70 ? "achse-frist-text rechts" : "achse-frist-text";
    beschriftung.textContent = t("tax.deadlineLine", { date: strahl.frist_datum });
    grenze.append(beschriftung);
    spur.append(grenze);
  }

  for (const eintrag of strahl.events) {
    const punkt = document.createElement("span");
    punkt.className =
      `achse-punkt ${eintrag.groesse} ${eintrag.erfuellt ? "erfuellt" : "offen"}`;
    punkt.style.left = `${eintrag.pos}%`;
    punkt.style.bottom = `${eintrag.y ?? 0}%`;
    const aeltere = eintrag.aeltere_sats || 0;
    const summe = aeltere + (eintrag.value_sats || 0);
    const labelText = formatBtcDrei(eintrag.value_sats);
    const tip = document.createElement("span");
    tip.className = eintrag.pos > 70 ? "achse-punkt-tip links" : "achse-punkt-tip";
    const zeilen = [
      `${eintrag.datum} · Σ=${formatBtcDrei(summe)}`,
      formatBtcDrei(eintrag.value_sats),
      `${eintrag.wallet || "unbekannt"} · ${haltefristBeschriftung(
        eintrag, Boolean(daten.stichtag_regel),
      )}`,
    ];
    if (eintrag.gruppe && eintrag.gruppe_n) {
      const n = eintrag.gruppe_n;
      const wort = n === 1 ? "UTXO" : "UTXOs";
      zeilen.push(
        eintrag.gruppe === "stichtag"
          ? `${n} ${wort} vor Stichtag`
          : `${n} ${wort} älter als Haltefrist`,
      );
    }
    tip.textContent = zeilen.join("\n");
    const label = document.createElement("span");
    label.className = "achse-punkt-label";
    label.textContent = labelText;
    punkt.append(label, tip);
    spur.append(punkt);
  }

  const ticks = $("#achse-ticks");
  ticks.replaceChildren();
  for (const tick of strahl.ticks) {
    const span = document.createElement("span");
    span.textContent = tick.label;
    ticks.append(span);
  }

  const zusatz = [`${strahl.von} bis ${strahl.bis}`];
  if (daten.laufend) {
    zusatz.push("Jahr läuft noch — Fristen gegen heute gerechnet");
  }
  setzeText($("#zeitstrahl-zusatz"), zusatz.join(" · "));
}

/**
 * Verfolgt die Herkunft aller noch ungeprüften UTXOs.
 *
 * Ohne das müsste jede Zeile der Tabelle einzeln in der Herkunftsansicht
 * aufgeklappt werden. Danach beruht das Anschaffungsdatum auf der Analyse
 * statt auf dem bloßen Entstehungsdatum des Outputs.
 */
/**
 * Erhebt den vollständigen Verlauf aller Wallets.
 *
 * Ohne ihn rechnet das Steuerjahr nur mit dem heutigen Bestand: Ein 2023
 * empfangener und 2024 verkaufter Betrag taucht nirgends auf — obwohl gerade
 * die Veräußerung der steuerlich maßgebliche Vorgang ist.
 *
 * Kostet eine Abfrage je Adresse und braucht einen Electrum-Server, läuft
 * deshalb nur auf ausdrücklichen Wunsch.
 */
/**
 * Zeigt, was im Steuerjahr veräußert wurde.
 *
 * Die Karte bleibt verborgen, solange kein Verlauf vorliegt — dort wäre eine
 * leere Liste keine Aussage („nichts verkauft"), sondern ein Nichtwissen.
 */
function zeichneAbgaenge(daten) {
  const karte = $("#abgaenge-karte");
  const abgaenge = daten.abgaenge || [];

  if (!daten.hat_verlauf) {
    karte.hidden = true;
    return;
  }
  karte.hidden = false;

  const k = daten.kennzahlen;
  setzeText(
    $("#abgaenge-zusatz"),
    abgaenge.length === 0
      ? "keine im gewählten Jahr"
      : `${abgaenge.length} · ${formatSats(k.abgang_sats)}` +
        (k.abgang_steuerpflichtig_count
          ? ` · davon ${k.abgang_steuerpflichtig_count} innerhalb der Frist`
          : " · alle nach Ablauf der Frist")
  );

  const liste = $("#abgaenge-liste");
  liste.replaceChildren();
  if (abgaenge.length === 0) {
    liste.append(hinweisZeile(
      "In diesem Jahr wurde nichts ausgegeben."
    ));
    return;
  }

  for (const abgang of abgaenge) {
    const zeile = document.createElement("div");
    zeile.className = "abgang-zeile";

    const marke = pille(
      abgang.frist_erfuellt ? "gut" : "krit",
      haltefristBeschriftung(
        { erfuellt: abgang.frist_erfuellt, neuvermoegen: abgang.neuvermoegen },
        Boolean(daten.stichtag_regel),
      )
    );

    const betrag = document.createElement("span");
    betrag.className = "mono";
    betrag.textContent = formatSats(abgang.value_sats);

    const zeitraum = document.createElement("span");
    zeitraum.className = "zart";
    zeitraum.textContent =
      `${abgang.datum} → ${abgang.abgang_datum} · ` +
      `${formatHaltedauer(abgang.haltedauer_tage)} gehalten`;

    const wer = document.createElement("span");
    wer.className = "zart";
    wer.textContent = abgang.wallet || "";

    zeile.append(marke, betrag, zeitraum, wer);
    liste.append(zeile);
  }
}

/**
 * Wallet-Knopf: jedes UTXO wie „Herkunftslücken schließen“ (gebündelte
 * Eingänge + Vorgänger-Txs) bis external/coinbase.
 * Bewusst mit Confirm — kann Stunden dauern, füllt den Herkunfts-Cache.
 */
async function starteHerkunftVollstaendig() {
  const wid = Zustand.walletId;
  if (!wid) return;
  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === wid);
  if (!wallet || !wallet.has_cache) {
    meldung(t("wallet.originDeepNeedCache"), "warn");
    return;
  }
  if (herkunftTiefLaeuftFuer(wid)) {
    meldung(t("nav.jobAlreadyRunning"), "warn");
    return;
  }
  const name = wallet.name || wid;
  if (!window.confirm(t("wallet.originDeepConfirm", { name }))) return;

  const knopf = $("#herkunft-tief-knopf");
  const leiste = $("#herkunft-tief-lauf");
  const textEl = $("#herkunft-tief-text");
  if (knopf) knopf.disabled = true;
  if (leiste) leiste.hidden = false;
  setzeText(textEl, t("wallet.originDeepRunning"));

  let jobId = null;
  let timer = null;
  const logStand = { index: 0 };
  let zuletztVerfolgt = -1;
  let refreshUm = 0;
  let refreshLaeuft = false;

  const fertig = async (meldungText, art) => {
    clearInterval(timer);
    if (leiste) leiste.hidden = true;
    setzeWalletScanGesperrt();
    if (meldungText) meldung(meldungText, art || "gut");
    if (Zustand.ansicht === "wallet" && Zustand.walletId === wid) {
      try { await zeigeWallet(wid); } catch (_) { /* ignore */ }
    }
    await ladeJobsNav();
  };

  logZeile(t("wallet.originDeepStarted", { name }), undefined, name);
  logZeile(
    "Browser darf geschlossen werden — Server und Scan laufen im Terminal weiter.",
    undefined,
    name,
  );
  try {
    const antwort = await api("/trace/alle", {
      methode: "POST",
      daten: { wallet_id: wid, vollstaendig: true },
    });
    if (antwort.nichts_zu_tun) {
      if (antwort.keine_utxos) {
        await fertig(t("wallet.originDeepNeedCache"), "warn");
      } else {
        await fertig(t("wallet.originDeepNothing"), "gut");
      }
      return;
    }
    jobId = antwort.id;
    nimmJobLogAb(antwort, logStand, name);
  } catch (fehler) {
    await fertig(fehler.message || String(fehler), "krit");
    return;
  }

  const abbruch = $("#herkunft-tief-abbruch");
  if (abbruch) {
    abbruch.onclick = async () => {
      setzeText(textEl, t("common.abortRequested"));
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* schon beendet */
      }
    };
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmJobLogAb(job, logStand, name);
      const zahl = job.result?.verfolgt;
      const vollOk = job.result?.vollstaendig_ok;
      let standText = übersetzeLogText(job.message || t("common.runningEllipsis"));
      if (typeof vollOk === "number" && vollOk > 0) {
        standText += ` · ${vollOk}× vollständig`;
      }
      setzeText(textEl, standText);

      if (job.running) {
        if (
          typeof zahl === "number"
          && zahl > zuletztVerfolgt
          && !refreshLaeuft
        ) {
          const jetzt = Date.now();
          if (zuletztVerfolgt < 0 || jetzt - refreshUm >= HERKUNFT_REFRESH_MS) {
            zuletztVerfolgt = zahl;
            refreshUm = jetzt;
            refreshLaeuft = true;
            try {
              if (Zustand.ansicht === "wallet" && Zustand.walletId === wid) {
                await zeigeWallet(wid);
              }
            } finally {
              refreshLaeuft = false;
            }
          }
        }
        return;
      }

      if (job.status === "done") {
        await fertig(
          t("wallet.originDeepDone", {
            msg: job.message || t("common.running"),
          }),
          "gut",
        );
      } else if (job.status === "cancelled") {
        await fertig(
          "Abgebrochen — bereits ermittelte Herkunft bleibt erhalten.",
          "warn",
        );
      } else {
        await fertig(job.error || t("trace.analyseFailShort"), "krit");
      }
    } catch (fehler) {
      await fertig(fehler.message, "krit");
    }
  }, 1200);
}

async function verlaufErheben() {
  const knopf = $("#verlauf-erheben");
  knopf.disabled = true;
  $("#herkunft-lauf").hidden = false;
  setzeText($("#herkunft-text"), "Verlauf wird vorbereitet…");

  let jobId = null;
  let timer = null;
  const logStand = { index: 0 };

  const fertig = (meldung, art) => {
    clearInterval(timer);
    knopf.disabled = false;
    $("#herkunft-lauf").hidden = true;
    if (meldung) {
      const kasten = $("#steuer-meldung");
      kasten.className = `hinweis hinweis-${art}`;
      setzeText(kasten, meldung);
      kasten.hidden = false;
    }
    ladeSteuerjahrMitKandidaten();
  };

  logZeile("Starte Verlauf aller Wallets…");
  try {
    const start = await api("/verlauf", { methode: "POST", daten: {} });
    jobId = start.id;
    nimmJobLogAb(start, logStand);
  } catch (fehler) {
    fertig(`Verlauf fehlgeschlagen: ${fehler.message}`, "krit");
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
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmJobLogAb(job, logStand);
      setzeText($("#herkunft-text"), übersetzeLogText(job.message || t("common.runningEllipsis")));
      if (job.running) return;
      if (job.status === "done") {
        fertig(job.message || "Verlauf erfasst.", "gut");
      } else if (job.status === "cancelled") {
        fertig("Abgebrochen — bereits erfasste Wallets bleiben erhalten.", "warn");
      } else {
        fertig(job.error || "Verlauf fehlgeschlagen.", "krit");
      }
    } catch (fehler) {
      fertig(fehler.message, "krit");
    }
  }, 1200);
}

/**
 * Verfolgt die Herkunft aller noch offenen UTXOs.
 *
 * Steht in zwei Ansichten — im Steuerjahr, wo die Anschaffungsdaten davon
 * abhängen, und in der Herkunftsansicht, wo man ohnehin gerade damit
 * arbeitet. Eine Funktion für beide: Zwei Fassungen desselben Ablaufs gingen
 * über kurz oder lang auseinander.
 *
 * *ziele* benennt die Bedienelemente der jeweiligen Ansicht, *danach* das,
 * was nach dem Lauf neu zu laden ist.
 */
/** Während Massen-Herkunft: aktuelle Ansicht höchstens alle ~2,5 s neu laden. */
const HERKUNFT_REFRESH_MS = 2500;

async function erfrischeHerkunftZwischenstand() {
  try {
    if (Zustand.ansicht === "wallet" && Zustand.walletId) {
      await zeigeWallet(Zustand.walletId);
    } else if (Zustand.ansicht === "trace") {
      await ladeTraceListe();
    } else if (Zustand.ansicht === "steuerjahr") {
      await ladeSteuerjahr();
    }
  } catch (_) {
    /* Zwischenstand ist Komfort — Fehler nicht den Lauf abbrechen */
  }
}

/** Wartet, bis ein Hintergrundjob fertig ist (done / cancelled / error). */
async function warteAufJobEnde(jobId, {
  onTick = null,
  sollAbbrechen = () => false,
  intervallMs = 900,
} = {}) {
  while (true) {
    if (sollAbbrechen()) {
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* schon weg */
      }
      const err = new Error("abgebrochen");
      err.abgebrochen = true;
      throw err;
    }
    const job = await api(`/jobs/${jobId}`);
    if (typeof onTick === "function") onTick(job);
    if (job.running) {
      await new Promise((r) => setTimeout(r, intervallMs));
      continue;
    }
    if (job.status === "done") return job;
    if (job.status === "cancelled") {
      const err = new Error("abgebrochen");
      err.abgebrochen = true;
      throw err;
    }
    throw new Error(job.error || t("common.failed"));
  }
}

/**
 * UTXO-Scan für jedes konfigurierte Wallet — Voraussetzung für
 * „Herkunft aller UTXOs“ bei leerem Cache.
 */
async function scanneAlleWalletsUtxo({
  textEl = null,
  sollAbbrechen = () => false,
  logStand = null,
} = {}) {
  const wallets = (Zustand.config?.wallets || []).filter((w) => w && w.id);
  if (!wallets.length) {
    throw new Error(t("wallets.emptyList"));
  }
  let scanAb = "";
  for (let i = 0; i < wallets.length; i += 1) {
    const wallet = wallets[i];
    if (sollAbbrechen()) {
      const err = new Error("abgebrochen");
      err.abgebrochen = true;
      throw err;
    }
    if (textEl) {
      setzeText(textEl, t("trace.allOriginsScanning", {
        aktuell: i + 1,
        gesamt: wallets.length,
        name: wallet.name || wallet.id,
      }));
    }
    logZeile(
      t("trace.allOriginsScanning", {
        aktuell: i + 1,
        gesamt: wallets.length,
        name: wallet.name || wallet.id,
      }),
      undefined,
      wallet.name,
    );

    let datum = scanAb;
    if (brauchtBip158Startdatum(wallet.id)) {
      const gewählt = await frageScanDatum(wallet);
      if (gewählt === undefined) {
        const err = new Error("abgebrochen");
        err.abgebrochen = true;
        throw err;
      }
      datum = gewählt || "";
      scanAb = datum;
    }

    const job = await api("/jobs/rescan", {
      methode: "POST",
      daten: { wallet_id: wallet.id, scan_ab: datum || "" },
    });
    const jid = job.id || job.job_id;
    if (!jid) {
      throw new Error(t("wallet.utxoScan") + " — " + t("common.failed"));
    }
    // Pipeline kann „queued“ liefern — trotzdem auf diese Job-ID warten.
    await warteAufJobEnde(jid, {
      sollAbbrechen,
      onTick: (j) => {
        if (logStand) nimmJobLogAb(j, logStand, wallet.name);
        if (textEl && j.message) {
          setzeText(
            textEl,
            t("trace.allOriginsScanning", {
              aktuell: i + 1,
              gesamt: wallets.length,
              name: wallet.name || wallet.id,
            }) + ` · ${übersetzeLogText(j.message)}`,
          );
        }
      },
    });
  }
}

async function herkunftAllerUtxos(ziele = {
  knopf: "#herkunft-alle",
  lauf: "#herkunft-lauf",
  text: "#herkunft-text",
  abbruch: "#herkunft-abbruch",
  meldung: "#steuer-meldung",
  danach: ladeSteuerjahrMitKandidaten,
}) {
  const knopf = $(ziele.knopf);
  knopf.disabled = true;
  $(ziele.lauf).hidden = false;
  setzeText($(ziele.text), "Wird vorbereitet…");

  let jobId = null;
  let timer = null;
  const logStand = { index: 0 };
  let zuletztVerfolgt = -1;
  let refreshUm = 0;
  let refreshLaeuft = false;
  let abbruchWunsch = false;

  const fertig = (meldung, art) => {
    clearInterval(timer);
    knopf.disabled = false;
    $(ziele.lauf).hidden = true;
    if (meldung) {
      const kasten = $(ziele.meldung);
      kasten.className = `hinweis hinweis-${art}`;
      setzeText(kasten, meldung);
      kasten.hidden = false;
    }
    ziele.danach();
  };

  $(ziele.abbruch).onclick = async () => {
    abbruchWunsch = true;
    setzeText($(ziele.text), "Abbruch angefordert…");
    if (jobId) {
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* schon beendet */
      }
    }
  };

  logZeile("Starte Herkunft aller UTXOs…");
  try {
    let antwort = await api("/trace/alle", { methode: "POST", daten: {} });
    if (antwort.nichts_zu_tun && antwort.keine_utxos) {
      // Bestand fehlt: nach Bestätigung erst alle Wallets scannen, dann Trace.
      knopf.disabled = false;
      $(ziele.lauf).hidden = true;
      if (!window.confirm(t("trace.allOriginsNeedUtxoConfirm"))) {
        fertig(t("trace.allOriginsScanAbort"), "warn");
        return;
      }
      knopf.disabled = true;
      $(ziele.lauf).hidden = false;
      abbruchWunsch = false;
      await scanneAlleWalletsUtxo({
        textEl: $(ziele.text),
        sollAbbrechen: () => abbruchWunsch,
        logStand,
      });
      if (abbruchWunsch) {
        fertig(t("trace.allOriginsScanAbort"), "warn");
        return;
      }
      setzeText($(ziele.text), t("trace.allOriginsScanDone"));
      await ladeConfig();
      antwort = await api("/trace/alle", { methode: "POST", daten: {} });
    }
    if (antwort.nichts_zu_tun) {
      if (antwort.keine_utxos) {
        fertig(t("trace.allOriginsNeedUtxo"), "warn");
      } else {
        fertig(t("trace.allOriginsNothing"), "gut");
      }
      return;
    }
    jobId = antwort.id;
    nimmJobLogAb(antwort, logStand);
  } catch (fehler) {
    if (fehler && fehler.abgebrochen) {
      fertig(t("trace.allOriginsScanAbort"), "warn");
      return;
    }
    fertig(`Analyse fehlgeschlagen: ${fehler.message}`, "krit");
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmJobLogAb(job, logStand);
      const zahl = job.result?.verfolgt;
      const juengste = job.result?.juengste_sats;
      let standText = übersetzeLogText(job.message || t("common.runningEllipsis"));
      if (typeof juengste === "number" && juengste > 0) {
        standText += ` · ${juengste}× jüngste sats`;
      }
      setzeText($(ziele.text), standText);

      if (job.running) {
        if (
          typeof zahl === "number"
          && zahl > zuletztVerfolgt
          && !refreshLaeuft
        ) {
          const jetzt = Date.now();
          if (zuletztVerfolgt < 0 || jetzt - refreshUm >= HERKUNFT_REFRESH_MS) {
            zuletztVerfolgt = zahl;
            refreshUm = jetzt;
            refreshLaeuft = true;
            try {
              await erfrischeHerkunftZwischenstand();
            } finally {
              refreshLaeuft = false;
            }
          }
        }
        return;
      }

      if (job.status === "done") {
        fertig(job.message || "Herkunft ermittelt.", "gut");
      } else if (job.status === "cancelled") {
        fertig("Abgebrochen — bereits ermittelte Herkunft bleibt erhalten.",
               "warn");
      } else {
        fertig(job.error || "Analyse fehlgeschlagen.", "krit");
      }
    } catch (fehler) {
      fertig(fehler.message, "krit");
    }
  }, 1200);
}

function ladeExport(pfad) {
  const jahr = $("#jahr-wahl").value;
  const frist = $("#frist-wahl").value;
  const stichtag = steuerEinstellungen().stichtag || "";
  // Download über einen eigenen Tab: fetch könnte die Datei nicht speichern.
  // Das Token muss dabei in die Adresse, weil kein Header mitgeht.
  const adresse =
    `/api/tax/${pfad}?jahr=${encodeURIComponent(jahr)}` +
    `&frist=${encodeURIComponent(frist)}` +
    `&stichtag=${encodeURIComponent(stichtag)}` +
    `&t=${encodeURIComponent(Token)}`;
  window.open(adresse, "_blank", "noopener");
}

// ---------------------------------------------------------------------------
// Selbstanzeige-Report
// ---------------------------------------------------------------------------

Zustand.saKandidaten = [];
Zustand.saUtxos = [];
Zustand.saVerlauf = null;
Zustand.saStichtag = "";

/**
 * Selbstanzeige-Kandidaten aus dem Cache (kein Netz).
 * *opts.auto*: kurzer Log-Hinweis — beim Öffnen der Steuerjahr-Ansicht.
 */
async function ladeSelbstanzeigeKandidaten(opts = {}) {
  const auto = Boolean(opts.auto);
  const jahr = $("#jahr-wahl").value;
  const txid = ($("#sa-txid")?.value || "").trim();
  const liste = $("#sa-liste");
  if (!liste) return;
  if (auto) logZeile("Selbstanzeige: Kandidaten aus Cache…");
  liste.textContent = t("common.loading");
  try {
    let pfad = `/tax/selbstanzeige/kandidaten?jahr=${encodeURIComponent(jahr)}`;
    if (txid) pfad += `&txid=${encodeURIComponent(txid)}`;
    const daten = await api(pfad);
    Zustand.saKandidaten = daten.abfluesse || daten.kandidaten || [];
    Zustand.saUtxos = daten.utxos || [];
    Zustand.saVerlauf = daten.verlauf || null;
    Zustand.saStichtag = daten.stichtag_hypothese || "";
    zeichneSelbstanzeigeKandidaten();
    if (auto) {
      const n = Zustand.saKandidaten.length;
      const u = Zustand.saUtxos.length;
      logZeile(
        `Selbstanzeige: ${n} Abfluss-Kandidat(en) · ${u} UTXO(s) Was-wäre-wenn.`,
      );
    }
  } catch (fehler) {
    liste.textContent = t("common.errorPrefix", { msg: fehler.message });
    if (auto) logZeile(`Selbstanzeige: Kandidaten fehlgeschlagen — ${fehler.message}`);
  }
}

/** Steuerjahr öffnen bzw. Jahr gewechselt: Auswertung + Kandidaten. */
async function ladeSteuerjahrMitKandidaten() {
  await ladeSteuerjahr();
  await ladeSelbstanzeigeKandidaten({ auto: true });
}

function saAbschnitt(titel, zusatz, {
  offen = false,
  leerText = "",
  ausklappbar = true,
} = {}) {
  const name = document.createElement("span");
  name.className = "sa-summary-titel";
  name.textContent = titel;
  const meta = document.createElement("span");
  meta.className = "sa-summary-meta";
  meta.textContent = zusatz || "";

  // Nichts zum Aufklappen: grauer Kasten ohne Pfeil — sonst wirkt es wie
  // ein toter Knopf.
  if (!ausklappbar) {
    const kasten = document.createElement("div");
    kasten.className = "sa-abschnitt sa-abschnitt-leer";
    const kopf = document.createElement("div");
    kopf.className = "sa-summary sa-summary-statisch";
    kopf.append(name, meta);
    kasten.append(kopf);
    if (leerText) {
      const leer = document.createElement("p");
      leer.className = "sa-leer";
      leer.textContent = leerText;
      kasten.append(leer);
    }
    const innen = document.createElement("div");
    innen.className = "sa-abschnitt-innen";
    kasten.append(innen);
    return { details: kasten, innen };
  }

  const details = document.createElement("details");
  details.className = "sa-abschnitt";
  details.open = Boolean(offen);
  const summary = document.createElement("summary");
  summary.className = "sa-summary";
  const pfeil = document.createElement("span");
  pfeil.className = "sa-pfeil";
  pfeil.setAttribute("aria-hidden", "true");
  pfeil.textContent = offen ? "▾" : "▸";
  summary.append(pfeil, name, meta);
  details.append(summary);
  details.addEventListener("toggle", () => {
    pfeil.textContent = details.open ? "▾" : "▸";
  });
  const innen = document.createElement("div");
  innen.className = "sa-abschnitt-innen";
  details.append(innen);
  return { details, innen };
}

function zeichneSaAbflussZeile(k) {
  const zeile = document.createElement("label");
  zeile.className = "sa-zeile" + (k.eigenuebertrag ? " eigen" : "");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.value = k.id || k.txid;
  box.dataset.art = "abfluss";
  box.checked = Boolean(k.ausgewaehlt);
  if (k.eigenuebertrag) {
    box.title =
      "Wirkt wie Eigenübertrag — nur ankreuzen, wenn es doch ein Verkauf war.";
  }
  const text = document.createElement("span");
  const titel = document.createElement("div");
  titel.className = "mono";
  titel.textContent = k.txid;
  const meta = document.createElement("div");
  meta.className = "sa-meta";
  meta.textContent =
    `${k.abgang_datum} ${k.abgang_zeit} · Netto ${formatSats(k.netto_sats)}` +
    ` · ${k.input_count} Inputs` +
    (k.wallets?.length ? ` · ${k.wallets.join(", ")}` : "") +
    (k.eigenuebertrag ? " · vermutlich Eigenübertrag" : "");
  text.append(titel, meta);
  if (k.inputs && k.inputs.length) {
    const inp = document.createElement("div");
    inp.className = "sa-inputs";
    inp.textContent = k.inputs
      .map(
        (i) =>
          `${i.wallet}: ${i.txid}:${i.vout} · ${i.address} · ${i.value_sats} sats`,
      )
      .join("\n");
    text.append(inp);
  }
  zeile.append(box, text);
  return zeile;
}

function zeichneSaUtxoZeile(u) {
  const zeile = document.createElement("label");
  zeile.className = "sa-zeile";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.value = u.id || `utxo:${u.txid}:${u.vout}`;
  box.dataset.art = "utxo";
  box.checked = Boolean(u.ausgewaehlt);
  box.title =
    "Hypothese: fiktive Veräußerung zum Stichtag (Jahresende bzw. heute).";
  const text = document.createElement("span");
  const titel = document.createElement("div");
  titel.className = "mono";
  titel.textContent = `${u.txid}:${u.vout}`;
  const meta = document.createElement("div");
  meta.className = "sa-meta";
  meta.textContent =
    `${formatSats(u.value_sats)} · ${u.wallet || "?"}` +
    (u.anschaffung_datum ? ` · Anschaffung ${u.anschaffung_datum}` : "") +
    (u.stichtag ? ` · Stichtag ${u.stichtag}` : "") +
    (u.address ? ` · ${u.address}` : "");
  text.append(titel, meta);
  zeile.append(box, text);
  return zeile;
}

function zeichneSelbstanzeigeKandidaten() {
  const liste = $("#sa-liste");
  if (!liste) return;
  liste.replaceChildren();

  const abfluesse = Zustand.saKandidaten || [];
  const utxos = Zustand.saUtxos || [];
  const verlauf = Zustand.saVerlauf;

  const ab = saAbschnitt(
    "Abflüsse im Steuerjahr",
    abfluesse.length
      ? `${abfluesse.length} Kandidat(en)`
      : "keine",
    {
      offen: abfluesse.length > 0,
      ausklappbar: abfluesse.length > 0,
      leerText: abfluesse.length
        ? ""
        : "Keine Netto-Abflüsse in diesem Jahr — Verlauf fehlt oder nichts ausgegeben.",
    },
  );
  for (const k of abfluesse) ab.innen.append(zeichneSaAbflussZeile(k));
  liste.append(ab.details);

  const stichtag = Zustand.saStichtag
    ? ` · Stichtag ${Zustand.saStichtag}`
    : "";
  const ut = saAbschnitt(
    "Offene UTXOs — Was wäre wenn",
    utxos.length
      ? `${utxos.length} UTXO(s)${stichtag}`
      : `keine${stichtag}`,
    {
      offen: false,
      ausklappbar: utxos.length > 0,
      leerText: utxos.length
        ? ""
        : "Keine offenen UTXOs im Cache. Zuerst UTXO-Scan.",
    },
  );
  if (utxos.length) {
    const hinweis = document.createElement("p");
    hinweis.className = "sa-leer";
    hinweis.textContent =
      "Angekreuzte UTXOs werden fiktiv zum Stichtag als veräußert gerechnet " +
      "(Haltedauer / FiFo-Anschaffung dieses Outputs). Keine echte Ausgabe.";
    ut.innen.append(hinweis);
  }
  for (const u of utxos) ut.innen.append(zeichneSaUtxoZeile(u));
  liste.append(ut.details);

  if (verlauf) {
    const teile = [];
    if (verlauf.vorhanden) teile.push("Verlaufsdaten vorhanden");
    else teile.push("wenig/kein Verlauf");
    if (verlauf.empfaenge_im_jahr != null) {
      teile.push(`${verlauf.empfaenge_im_jahr} Empfang(e) im Jahr`);
    }
    if (verlauf.abgaenge_im_jahr != null) {
      teile.push(`${verlauf.abgaenge_im_jahr} Abgangszeilen im Jahr`);
    }
    if (verlauf.offen_utxos != null) {
      teile.push(`${verlauf.offen_utxos} offen`);
    }
    const vl = saAbschnitt("Verlauf (Überblick)", teile.join(" · "), {
      ausklappbar: false,
      leerText:
        "Nur Orientierung: Abflüsse oben brauchen Verlauf; " +
        "UTXOs kommen aus dem Bestand.",
    });
    liste.append(vl.details);
  }
}

function saAuswahl() {
  const txids = [];
  const utxos = [];
  for (const el of document.querySelectorAll(
    "#sa-liste input[type=checkbox]:checked",
  )) {
    const wert = el.value;
    if (!wert) continue;
    if (el.dataset.art === "utxo" || wert.startsWith("utxo:")) {
      utxos.push(wert.startsWith("utxo:") ? wert.slice(5) : wert);
    } else {
      txids.push(wert);
    }
  }
  return { txids, utxos };
}

function ladeSelbstanzeigeExport(art) {
  const { txids, utxos } = saAuswahl();
  if (!txids.length && !utxos.length) {
    const kasten = $("#steuer-meldung");
    if (kasten) {
      kasten.className = "hinweis hinweis-warn";
      setzeText(
        kasten,
        "Bitte mindestens einen Abfluss oder einen offenen UTXO ankreuzen.",
      );
      kasten.hidden = false;
    }
    return;
  }
  const jahr = $("#jahr-wahl").value;
  const frist = $("#frist-wahl").value;
  const datei = art === "csv" ? "export.csv" : "bericht.html";
  const query =
    `jahr=${encodeURIComponent(jahr)}` +
    `&frist=${encodeURIComponent(frist)}` +
    `&txids=${encodeURIComponent(txids.join(","))}` +
    `&utxos=${encodeURIComponent(utxos.join(","))}`;
  const adresse =
    `/api/tax/selbstanzeige/${datei}?${query}&t=${encodeURIComponent(Token)}`;

  if (art === "csv") {
    window.open(adresse, "_blank", "noopener");
    return;
  }

  // HTML: sofort Tab öffnen (User-Geste, kein Popup-Blocker) und parallel
  // die Datei speichern — Drucken im Tab, Archiv als Download.
  const fenster = window.open(adresse, "_blank", "noopener");
  (async () => {
    try {
      const antwort = await fetch(`/api/tax/selbstanzeige/${datei}?${query}`, {
        headers: { "X-Satsage-Token": Token },
      });
      if (!antwort.ok) {
        let meldung = `HTTP ${antwort.status}`;
        try {
          const koerper = await antwort.json();
          if (koerper.error) meldung = koerper.error;
        } catch (_) { /* ignore */ }
        throw new Error(meldung);
      }
      const blob = await antwort.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `satsage-selbstanzeige-${jahr}.html`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (fehler) {
      const kasten = $("#steuer-meldung");
      if (kasten) {
        kasten.className = "hinweis hinweis-warn";
        setzeText(
          kasten,
          fenster
            ? `Report geöffnet; Download fehlgeschlagen: ${fehler.message}`
            : `Report: ${fehler.message}`,
        );
        kasten.hidden = false;
      }
    }
  })();
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
  typWahl.title = "Bei Multisig durch die .env vorgegeben.";
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
    } else if (wallet.has_cache) {
      cache.className = "pille pille-gut";
      const hinweis = cacheHinweis(wallet);
      cache.textContent = hinweis || `${wallet.utxo_count} UTXO`;
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
      speichereWallets(false);
    });

    liste.append(fragment);
  });
  if (window.SatSageI18n) window.SatSageI18n.applyDom(liste);
  zeichneGefahrWallets();

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
    ? "einem entfernten Wallet"
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
      ? `Unreferenzierte Cachedaten gelöscht (${label}, ${n} Dateien).`
      : "Keine unreferenzierten Cachedaten.";
    meldung(text, "gut");
    logZeile(text);
    zeichneUnreferenziertenCache({ vorhanden: false, dateien: 0, bytes: 0 });
    await ladeCacheDashboard();
  } catch (fehler) {
    meldung(`Aufräumen fehlgeschlagen — ${fehler.message}`, "krit");
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
  zeichneStartSync();
  zeichneStatusMailEinstellungen();
  zeichneMempoolStatus();
  setzeEnvPfad(Zustand.config?.env_path);
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
  const art = hit.pruned ? "pruned (scantxoutset trotzdem nützlich)" : "vollständig";
  const p2p = hit.p2p_port || 8333;
  const p2pHinweis = hit.p2p_tcp_open === false
    ? ` P2P :${p2p} derzeit nicht offen — BIP-158 Prefer-Peer wird trotzdem gesetzt (peerblockfilters=1 nötig).`
    : ` Opt-in setzt auch BIP158_HOST=${hit.host}:${p2p} (Compact Filter zuerst lokal).`;
  text.textContent =
    `Lokaler Bitcoin Core erkannt: ${hit.host}:${hit.port} `
    + `(${hit.chain || hit.network}, ${art}, ~${Number(hit.blocks || 0).toLocaleString("de-DE")} Blöcke). `
    + `Nicht still verbunden — „Lokalen Core übernehmen“ schreibt RPC + BIP-158-Prefer-Peer `
    + `(LOCAL_CORE_OPT_IN=1).`
    + p2pHinweis;
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
        zeichneDatenquellenAnsicht();
        logZeile("Lokaler Bitcoin Core übernommen.");
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
  ladeLabelStatus();
  ladeListenStatus();
  setzeEnvPfad(Zustand.config?.env_path);
  aktualisiereDatenquellenNav();
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
    const opt = $("#kurs-historie-opt-in");
    if (opt) opt.checked = Boolean(stand.price_history_opt_in);
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

async function speichereKursHistorieOptInUndSync() {
  const opt = $("#kurs-historie-opt-in");
  const an = Boolean(opt && opt.checked);
  logZeile(
    an
      ? "Kurs-Historie: Opt-in an — prüfe Lücken (Bitstamp)…"
      : "Kurs-Historie: Opt-in aus — nur Lücken-Hinweis.",
  );
  try {
    const stand = await api("/price/history/sync", {
      methode: "POST",
      daten: { opt_in: an },
    });
    for (const zeile of stand.log || []) logZeile(zeile);
    Zustand.kursHistorie = {
      histories: stand.histories || [],
      price_history_opt_in: stand.price_history_opt_in,
    };
    zeichneKursHistorie(Zustand.kursHistorie);
    if (opt) opt.checked = Boolean(stand.price_history_opt_in);
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
  logZeile(`Importiere BTC/${waehrung}-Kurs-CSV „${datei.name}“…`);
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
      meldung(`BTC/${waehrung}-Historie aktualisiert.`, "gut");
      Zustand.kursSerie = null;
      await Promise.all([ladeKursHistorie(), ladeKursSerie()]);
    } catch (fehler) {
      logZeile(`Kurs-Import: ${fehler.message}`, true);
      meldung(fehler.message, "krit");
    }
  };
  leser.onerror = () => {
    logZeile("Kurs-CSV ließ sich nicht lesen.", true);
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

    if (quelle.verwerfbar) {
      const korb = document.createElement("button");
      korb.type = "button";
      korb.className = "stift papierkorb";
      korb.textContent = "🗑";
      korb.title = bridgeManaged
        ? t("sources.start9BridgeHint")
        : (quelle.key === "bip158"
          ? t("sources.disableP2pTitle")
          : t("sources.discardTitle", { name: anzeigename }));
      korb.disabled = bridgeManaged;
      korb.addEventListener("click", () => verwerfeQuelle(quelle));
      rechts.append(korb);
    }

    if (quelle.laden_url && quelle.laden_filter) {
      const laden = document.createElement("button");
      laden.type = "button";
      laden.className = "knopf knopf-klein";
      laden.textContent = t("wallets.loadFromElectrum");
      laden.title = t("sources.loadElectrumTitle", { url: quelle.laden_url });
      laden.addEventListener("click", () => ladeElectrumServer(quelle, laden));
      rechts.append(laden);
      // Papierkorb hinter dem Laden-Knopf: nur die Serverliste, nicht Opt-in.
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
    const p2pWirdAn = quelle.key === "bip158"
      && String(werte.BIP158_P2P || "").toLowerCase() === "true";
    const hatteOeffentlich = oeffentlicheElectrumNochAktiv();
    try {
      const ergebnis = await api("/config/source", {
        methode: "PUT",
        daten: { source: quelle.key, values: werte },
      });
      await ladeConfig();
      // Während des Tests „im Aufbau“ zeigen.
      Zustand.peerCheckLaeuft = true;
      zeichneQuellen(ergebnis.sources || Zustand.config.sources);
      meldung(t("sources.appliedTesting"), "warn");
      try {
        const stand = await testeEigenenNode($("#quelle-pruefen"));
        meldung(
          t("sources.appliedResult", { stand: stand.label }),
          stand.gut ? "gut" : "krit",
        );
        if (p2pWirdAn && hatteOeffentlich && p2pQuelleVerbunden()) {
          await frageP2pPrivatsphaereKappen();
        }
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
  setzeText($("#listen-text"), t("common.downloadStarting"));

  const fertig = (meldung) => {
    clearInterval(timer);
    knopf.disabled = false;
    if (imp) imp.disabled = false;
    $("#listen-lauf").hidden = true;
    if (meldung) meldungListen(meldung);
    ladeListenStatus();
  };

  let jobId = null;
  let timer = null;
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
    logZeile(`Label-Import: ${fehler.message}`, true);
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
    logZeile(`Listen-Import: ${fehler.message}`, true);
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
  setzeText($("#label-text"), t("common.downloadStarting"));
  const fertig = (meldung) => {
    clearInterval(timer);
    knopf.disabled = false;
    if (imp) imp.disabled = false;
    $("#label-lauf").hidden = true;
    if (meldung) meldungListen(meldung);
    ladeLabelStatus();
  };

  let jobId = null;
  let timer = null;
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
    meldungListen(`Entfernen fehlgeschlagen: ${fehler.message}`);
  }
  ladeLabelStatus();
}

/**
 * Die Beschriftung einer fremden Adresse als Element — oder null.
 *
 * Eine Forenerwähnung wird bewusst anders formuliert als ein Dienst: „auf
 * BitcoinTalk erwähnt" ist keine Aussage darüber, wem die Adresse gehört.
 */
function labelMarke(label) {
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

  const katKey = `labels.cat.${label.kategorie || label.art || ""}`;
  const kat = (() => {
    const u = t(katKey);
    return u !== katKey ? u : (label.kategorie_label || label.art || "");
  })();
  marke.textContent = `${kat} · ${label.name}`;
  const teile = [];
  if (label.land) teile.push(t("labels.seat", { land: label.land }));
  if (label.status === "closed") teile.push(t("labels.serviceClosed"));
  teile.push(t("labels.sourceFile", {
    quelle: label.quelle,
    date: (label.stand || "").split("-").reverse().join("."),
  }));
  marke.title = `${teile.join(" · ")}. ${hinweis}`;
  return marke;
}

function meldungListen(text) {
  const kasten = $("#speicher-meldung");
  kasten.className = "hinweis hinweis-krit";
  setzeText(kasten, text);
  kasten.hidden = false;
}

// ---------------------------------------------------------------------------
// Sanktionscheck (externe Vorgeschichte)
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
      text.textContent = umfang + (w.abgebrochen ? t("sanctions.abortedSuffix") : "");
      zeile.append(text);
    } else {
      zeile.append(pille("krit", t("sanctions.hits", { count: treffer.length })));
      const text = document.createElement("span");
      text.textContent = umfang;
      zeile.append(text);
    }
    behaelter.append(zeile);

    for (const t of treffer) {
      const detail = document.createElement("div");
      detail.className = "sanktions-zeile sanktions-treffer";
      const beschreibung = document.createElement("span");
      beschreibung.className = "mono klein";
      beschreibung.textContent =
        `Hop ${t.hop} · ${t.address} · ${formatSats(t.amount_sats || 0)} ` +
        `über UTXO ${t.from_utxo}`;
      detail.append(beschreibung);
      const link = mempoolVerweis("address", t.address);
      if (link) detail.append(link);
      behaelter.append(detail);
    }

    const adressen = w.adressen || [];
    if (adressen.length) {
      const block = document.createElement("details");
      block.className = "sanktions-adressen";
      const titel = document.createElement("summary");
      titel.textContent = w.adressen_gekappt
        ? `Geprüfte Adressen (erste ${formatZahl(adressen.length)} von ` +
          `${formatZahl(w.adressen_geprueft)})`
        : `Geprüfte Adressen (${formatZahl(adressen.length)})`;
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

async function starteSanktionsCheck() {
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

  let jobId = null;
  let timer = null;
  const fertig = (meldung, kritisch = true) => {
    clearInterval(timer);
    knopf.disabled = false;
    abbruch.hidden = true;
    $("#sank-lauf").hidden = true;
    if (meldung) sankMeldung(meldung, kritisch);
  };

  abbruch.onclick = async () => {
    if (jobId) {
      try { await api(`/jobs/${jobId}`, { methode: "DELETE" }); } catch (e) { /* Job evtl. schon weg */ }
    }
  };

  try {
    const job = await api("/sanctions/check", { methode: "POST", daten });
    jobId = job.id;
  } catch (fehler) {
    fertig(t("sanctions.checkFailed", { msg: fehler.message }));
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      setzeText($("#sank-lauf-text"), übersetzeLogText(job.message || t("common.runningEllipsis")));
      if (job.running) return;
      if (job.status === "done" && job.result) {
        fertig(übersetzeLogText(job.message || ""), false);
        zeichneSankErgebnis(job.result);
      } else {
        fertig(übersetzeServerMeldung(job.error) || übersetzeLogText(job.message) || t("common.failed"));
      }
    } catch (fehler) {
      fertig(fehler.message);
    }
  }, 1200);
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
  // Der Klick darf nicht die darunterliegende Zeile aufklappen.
  link.addEventListener("click", (e) => e.stopPropagation());
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
}

function zeichneStartSync() {
  const box = $("#start-sync");
  if (!box) return;
  box.checked = Boolean(
    Zustand.config?.wallets_immer_aktuell
    ?? Zustand.config?.wallets_beim_start_aktualisieren,
  );
  setzeTipSyncSichtbarkeit();
}

async function speichereStartSync() {
  const box = $("#start-sync");
  if (!box) return;
  const an = box.checked;
  // Hide/show immediately; the config response below remains authoritative.
  setzeTipSyncSichtbarkeit(an);
  try {
    const ergebnis = await api("/config/start-sync", {
      methode: "PUT",
      daten: { enabled: an },
    });
    if (Zustand.config) {
      const v = Boolean(
        ergebnis.wallets_immer_aktuell
        ?? ergebnis.wallets_beim_start_aktualisieren,
      );
      Zustand.config.wallets_immer_aktuell = v;
      Zustand.config.wallets_beim_start_aktualisieren = v;
      if (ergebnis.wallet_watch) {
        Zustand.config.wallet_watch = ergebnis.wallet_watch;
      }
    }
    box.checked = Boolean(
      Zustand.config?.wallets_immer_aktuell
      ?? Zustand.config?.wallets_beim_start_aktualisieren,
    );
    setzeTipSyncSichtbarkeit();
    // Tip-Nachzug sofort mitverfolgen (ohne Server-Neustart).
    const jobId = ergebnis.wallet_sync_job_id || ergebnis.job?.id;
    if (an && jobId) {
      if (Zustand.config) {
        Zustand.config.wallet_sync_job_id = jobId;
      }
      folgeWalletSyncJob(jobId);
      logZeile(t("settings.startSyncStarted"));
      await ladeJobsNav();
    }
    meldung(
      an
        ? t("settings.startSyncOn")
        : t("settings.startSyncOff"),
      "gut",
    );
  } catch (fehler) {
    box.checked = Boolean(
      Zustand.config?.wallets_immer_aktuell
      ?? Zustand.config?.wallets_beim_start_aktualisieren,
    );
    setzeTipSyncSichtbarkeit();
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

async function speichereMempool() {
  const managed = sourcesFullyManaged();
  const knopf = document.getElementById(managed ? "mempool-speichern-managed" : "mempool-speichern");
  if (!knopf) return;
  knopf.disabled = true;
  try {
    const feld = document.getElementById(managed ? "mempool-url-managed" : "mempool-url");
    await api("/config/mempool", { methode: "PUT", daten: { url: feld ? feld.value : "" } });
    await ladeConfig();
    zeichneMempoolStatus();
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

function zeichneGefahrWallets() {
  const ziel = $("#cache-wallets");
  if (!ziel) return;
  ziel.replaceChildren();
  const wallets = (Zustand.config?.wallets || []).filter((w) => !w.is_new);
  if (!wallets.length) {
    const leer = document.createElement("p");
    leer.className = "gefahr-leer";
    leer.textContent = t("wallets.noWallets");
    ziel.append(leer);
    return;
  }
  for (const wallet of wallets) {
    const zeile = document.createElement("div");
    zeile.className = "gefahr-zeile";
    zeile.dataset.walletId = wallet.id;

    const name = document.createElement("span");
    name.className = "gefahr-name";
    name.textContent = wallet.name || t("common.wallet");

    const stand = document.createElement("span");
    stand.className = "gefahr-stand";
    if (wallet.has_cache) {
      const utxo = wallet.utxo_count === 1
        ? t("wallets.utxoOne")
        : t("wallets.utxoMany", { n: wallet.utxo_count });
      stand.textContent = cacheHinweis(wallet) ? `${utxo} · ${cacheHinweis(wallet)}` : utxo;
    } else {
      stand.textContent = t("wallets.noCache");
    }

    const loeschen = document.createElement("button");
    loeschen.type = "button";
    loeschen.className = "knopf knopf-gefahr knopf-klein wallet-cache-leeren";
    loeschen.textContent = t("wallets.cacheDelete");
    loeschen.title = t("wallets.cacheDeleteTitle");
    loeschen.disabled = !wallet.has_cache;
    loeschen.addEventListener("click", () => {
      setzeCacheLeerenBestaetigung(false);
      setzeWalletCacheBestaetigung(wallet.id);
    });

    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "knopf knopf-gefahr knopf-klein wallet-cache-ok";
    ok.textContent = t("wallets.cacheDeleteReally");
    ok.title = t("wallets.cacheDeleteReallyTitle", { name: wallet.name });
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
    const text = n
      ? `Cache von „${name}“ gelöscht (${n} Einträge). Wallet-Alter bleibt — neu scannen ab First-seen.`
      : `Cache von „${name}“ war bereits leer.`;
    kasten.className = "hinweis hinweis-gut";
    setzeText(kasten, text);
    kasten.hidden = false;
    logZeile(text, undefined, name);
    await ladeConfig();
    zeichneEinstellungen();
    if (Zustand.ansicht === "wallet" && Zustand.walletId === wallet.id) {
      await zeigeWallet(Zustand.walletId);
    }
  } catch (fehler) {
    kasten.className = "hinweis hinweis-krit";
    setzeText(kasten, `Löschen fehlgeschlagen: ${fehler.message}`);
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
      ? `Cache gelöscht (${n} Einträge). Wallet-Alter bleibt — neu scannen ab First-seen.`
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
    setzeText(kasten, `Löschen fehlgeschlagen: ${fehler.message}`);
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
    meldung(`Cache-Vorschau fehlgeschlagen — ${fehler.message}`, "krit");
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
    `Zugehörigen Analyse-Cache auch löschen (${mbText})?`,
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
  Zustand.walletSpeichernLaeuft = true;
  setzeWalletSpeichernGesperrt(true);
  try {
    const nutzlast = walletsNutzlast();
    if (cacheEntfernteLoeschen === null) {
      const behalten = new Set(
        Zustand.entwurf.filter((w) => !w.is_new && w.id).map((w) => w.id),
      );
      const vielleichtEntfernt = (Zustand.config?.wallets || []).some(
        (w) => w.id && !behalten.has(w.id),
      );
      if (vielleichtEntfernt) {
        const entscheidung = await frageCacheBeiWalletLoeschung(nutzlast);
        cacheEntfernteLoeschen = entscheidung === true;
      } else {
        cacheEntfernteLoeschen = false;
      }
    }
    const ergebnis = await api("/config/wallets", {
      methode: "PUT",
      daten: {
        wallets: nutzlast,
        confirm: bestaetigt,
        cache_entfernte_loeschen: Boolean(cacheEntfernteLoeschen),
      },
    });
    let text = ergebnis.backup
      ? `Gespeichert. Sicherung der vorherigen Fassung: ${ergebnis.backup}`
      : "Gespeichert.";
    if ((ergebnis.cache_entfernt || []).length) {
      text += ` Cache entfernt (${ergebnis.cache_groesse_label || "0 MB"}).`;
    }
    meldung(text, "gut");
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
    if (fehler.brauchtBestaetigung) {
      warnungMitBestaetigung(fehler.message, cacheEntfernteLoeschen);
    } else {
      meldung(`Nicht gespeichert — ${fehler.message}`, "krit");
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
    art.textContent = `${treffer.cosigner_count} Schlüssel`;
    kopf.append(art);
  } else {
    const art = document.createElement("span");
    art.textContent = "Single-Sig · Deskriptor";
    kopf.append(art);
  }
  if (treffer.bereits_vorhanden) {
    kopf.append(pille("warn", "bereits eingetragen"));
  }
  block.append(kopf);

  const adresse = document.createElement("div");
  adresse.className = "deskriptor-adresse";
  adresse.innerHTML =
    "<span class='feld-titel'>Erste Empfangsadresse — mit der Wallet vergleichen</span>";
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
    ? "Trotzdem übernehmen"
    : "Übernehmen";
  knopf.title = treffer.bereits_vorhanden
    ? "Diese Wallet ist bereits eingetragen — ein zweiter Eintrag zählte die " +
      "Beträge doppelt."
    : "Übernimmt den Deskriptor und schreibt ihn sofort in die .env.";
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
  if (/\b(sh|wsh|tr|wpkh|pkh|combo)\s*\(/i.test(xpub)) {
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
    meldung(`Hinweis nicht gespeichert — ${fehler.message}`, "krit");
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
    };
  }
  const nach = {};
  for (const q of quellen || []) nach[q.key] = q;
  const own = nach.own_fulcrum;
  if (own && own.reachable) {
    return {
      n: 1,
      kind: "own",
      label: "Eigener Peer verbunden",
      peers: own.peer_hosts || [],
      gut: true,
    };
  }
  const p2p = nach.bip158;
  if (p2p && (p2p.peer_count || 0) > 0) {
    const n = p2p.peer_count;
    return {
      n,
      kind: "p2p",
      label: n === 1 ? "1 Peer verbunden" : `${n} Peers verbunden`,
      peers: p2p.peer_hosts || [],
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
      gut: true,
    };
  }
  return { n: 0, kind: "none", label: "0 Peers verbunden", peers: [], gut: false };
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
  if (alt.kind !== neu.kind) {
    if (alt.n || neu.n) return [`Wechsel: ${alt.label} → ${neu.label}`];
    return [];
  }
  // P2P-/Public-Probe-Peers wechseln oft — kein Ausgefallen/Neu-Spam pro Host.
  if (alt.kind === "p2p" || alt.kind === "public") {
    if (alt.n !== neu.n) return [`Wechsel: ${alt.label} → ${neu.label}`];
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
    Zustand.peerStatus = {
      n: uniq.length,
      kind: "p2p",
      label: uniq.length === 1 ? "1 Peer verbunden" : `${uniq.length} Peers verbunden`,
      peers: uniq,
      gut: true,
    };
    Zustand.peers = uniq.length;
    Zustand.peerLabel = Zustand.peerStatus.label;
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
      };
    }
    return neu;
  });
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
  logZeile("Öffentliche Electrum-Server nur nach Bestätigung.");
  overlay.hidden = false;
  const nein = $("#oeffentliche-electrum-nein");
  if (nein) nein.focus();
}

function lehneOeffentlicheElectrumAb() {
  const overlay = $("#oeffentliche-electrum-warnung");
  if (overlay) overlay.hidden = true;
  logZeile("Öffentliche Electrum-Server abgelehnt.");
}

async function erlaubeOeffentlicheElectrum() {
  const overlay = $("#oeffentliche-electrum-warnung");
  if (overlay) overlay.hidden = true;
  logZeile("Öffentliche Electrum-Server bestätigt — verbinde…");
  try {
    await api("/source/oeffentlich", {
      methode: "POST",
      daten: { erlauben: true },
    });
    if (Zustand.config) Zustand.config.oeffentliche_electrum = true;
    await testeEigenenNode();
  } catch (fehler) {
    Zustand.oeffentlicheGefragt = false;
    logZeile(`Öffentliche Server: ${fehler.message}`, true);
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
          logZeile("Öffentliche Electrum-Nutzung gekappt (höhere Privatsphäre).");
          meldung(t("sources.publicCut"), "gut");
        } catch (fehler) {
          logZeile(`Öffentlich kappen: ${fehler.message}`, true);
          meldung(fehler.message, "krit");
        }
      } else if (wahl === "behalten") {
        logZeile("Öffentliche Electrum bleiben als Fallback erlaubt.");
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
      ? `Aktiv für Filter/Tip-Sync: ${liveN} Peer(s). `
      : "")
    + "Bitcoin-P2P mit BIP-158 Compact Filters. "
    + (p2pHosts.length ? p2pHosts.slice(0, 6).join(", ") : "");

  const eintraege = [];

  if (coreVerbunden || kopfQuelleAufbau(core) || kopfQuelleFehler(core)) {
    eintraege.push({
      key: "own_core",
      label: t("header.sourceCore"),
      stufe: coreVerbunden ? "gut" : (kopfQuelleAufbau(core) ? "warn" : "krit"),
      title: core?.error
        || "Bitcoin Core RPC (scantxoutset / Lookups), hohe Privatsphäre",
    });
  }

  if (p2pVerbunden || p2pAufbau) {
    const n = p2pVerbunden ? p2pAnzahl : 0;
    eintraege.push({
      key: "bip158",
      label: t("header.p2pPeers", { n }),
      stufe: p2pAufbau
        ? "warn"
        : (p2pAnzahl > 2 ? "gut" : (p2pAnzahl > 0 ? "warn" : "krit")),
      title: p2pTitle || t("header.p2pPeers", { n }),
    });
  }

  if (electrsVerbunden || kopfQuelleAufbau(electrs) || kopfQuelleFehler(electrs)) {
    eintraege.push({
      key: "own_fulcrum",
      label: t("header.sourceElectrumOwn"),
      stufe: electrsVerbunden
        ? "gut"
        : (kopfQuelleAufbau(electrs) ? "warn" : "krit"),
      title: electrs?.error
        || "Eigener Electrum-Server (Fulcrum/electrs) gemäß Datenquellen",
    });
  }

  if (oeffentlichVerbunden) {
    eintraege.push({
      key: "public",
      label: t("header.sourceElectrumPublic"),
      stufe: "krit",
      title: "Öffentliche Electrum-Server — keine Privatsphäre",
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
  if (oeffentlichVerbunden) {
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

  const status = $("#quelle-status");
  status.replaceChildren();
  for (const eintrag of eintraege) {
    const pill = pille(eintrag.stufe, eintrag.label);
    pill.title = eintrag.title;
    status.append(pill);
  }
  status.append(pille(privStufe, privText));
  zeichneKursPille();
  zeichneLlmPille();
}

const LLM_TAKT_MS = 30000;
/** Spotkurs: an den Cache-TTL in core/price.py angelehnt (10 Min). */
const KURS_TAKT_MS = 10 * 60 * 1000;

function formatKursLabel(preis) {
  if (!preis || !(Number(preis.amount) > 0)) return "BTC —";
  const n = Math.round(Number(preis.amount)).toLocaleString(formatLocale());
  if (preis.currency === "EUR") return `${n} €`;
  return `${n} ${preis.currency || ""}`.trim();
}

function formatKursTooltip(preis) {
  if (!preis || !(Number(preis.amount) > 0)) {
    return "Bitcoin-Kurs noch nicht geladen (Clearnet, ohne Wallet-Daten)";
  }
  const wann = preis.time
    ? new Date(Number(preis.time) * 1000).toLocaleString(formatLocale())
    : "?";
  const quelle = preis.source || "?";
  return (
    `1 BTC ≈ ${formatKursLabel(preis)} · Quelle: ${quelle} · Stand: ${wann}. ` +
    "Abruf ohne Wallet-Adressen."
  );
}

function zeichneKursPille() {
  const status = $("#quelle-status");
  if (!status) return;
  const preis = Zustand.kurs;
  const stufe = preis && Number(preis.amount) > 0 ? "gut" : "neutral";
  const neu = pille(stufe, formatKursLabel(preis));
  neu.id = "kurs-pille";
  neu.title = formatKursTooltip(preis);
  const alt = $("#kurs-pille");
  if (alt) {
    alt.replaceWith(neu);
    return;
  }
  const llm = $("#llm-pille");
  if (llm) status.insertBefore(neu, llm);
  else status.append(neu);
}

/** Tageskurs-Serie für EUR-Umrechnung ausgegebener Beträge (einmalig cachen). */
async function ladeKursSerie() {
  if (Zustand.kursSerie?.EUR?.series) return Zustand.kursSerie;
  if (Zustand.kursSerieLade) return Zustand.kursSerieLade;
  Zustand.kursSerieLade = (async () => {
    try {
      const stand = await api("/price/history?currency=EUR&series=1", {
        timeoutMs: 15000,
      });
      const eintrag = (stand.histories || []).find((h) => h.currency === "EUR");
      if (eintrag?.series && eintrag.ok) {
        Zustand.kursSerie = { EUR: eintrag };
      } else {
        Zustand.kursSerie = { EUR: { ok: false, series: null } };
      }
    } catch (_fehler) {
      Zustand.kursSerie = { EUR: { ok: false, series: null } };
    } finally {
      Zustand.kursSerieLade = null;
    }
    return Zustand.kursSerie;
  })();
  return Zustand.kursSerieLade;
}

async function ladeSpotkurs({ laut = false } = {}) {
  if (laut) logZeile("Hole Bitcoin-Kurs…");
  try {
    // Kurz timeout: sonst blockiert der Start bei Netz-/SSL-Problemen.
    Zustand.kurs = await api("/price?currency=EUR", { timeoutMs: 8000 });
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
          ? "Kurs: aktueller Kurs nicht beschaffbar."
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

/** Nach Kurswechsel: sichtbare Beträge mit ≈ € neu zeichnen. */
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
  const status = $("#quelle-status");
  if (!status) return;
  const s = Zustand.llmStatus || Zustand.config?.llm || {};
  const neu = pille(s.pille || "neutral", übersetzeLlmLabel(s.pille_label) || "LLM");
  neu.id = "llm-pille";
  neu.title = übersetzeLlmLabel(s.tooltip) || t("settings.llm.notConfigured");
  const alt = $("#llm-pille");
  if (alt) alt.replaceWith(neu);
  else status.append(neu);
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
  if (laut && check) logZeile("Prüfe Assistenten-Anbindung…");
  try {
    Zustand.llmStatus = await api(check ? "/llm/status?check=1" : "/llm/status");
  } catch (fehler) {
    if (laut) logZeile(`Assistent: ${fehler.message}`, true);
    return;
  }
  if (laut && check) {
    const s = Zustand.llmStatus;
    if (s.reachable) {
      logZeile(`Assistent erreichbar. ${s.banner}`, true);
    } else if (s.configured) {
      const grund = s.probe_error ? `: ${s.probe_error}` : ".";
      logZeile(`Assistent nicht erreichbar${grund}`, true);
    } else {
      logZeile("Assistent nicht konfiguriert.");
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

async function testeEigenenNode(knopf) {
  const vorher = knopf ? knopf.textContent : "";
  if (knopf) {
    knopf.disabled = true;
    knopf.textContent = t("common.testing");
  }
  if (eigenerNode(Zustand.config?.sources) || knopf) {
    logZeile("Starte Verbindungstest…");
  }
  Zustand.peerCheckLaeuft = true;
  // Sofort „Verbindung im Aufbau…“ in Datenquellen, solange der Check läuft.
  if ($("#quellen-liste")?.childElementCount) {
    zeichneQuellen(Zustand.config?.sources || []);
  }
  try {
    const ergebnis = await apiSourceCheck();
    return nimmPeerStand(ergebnis, false);
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

function folgeWalletSyncJob(jobId) {
  const id = jobId || Zustand.config?.wallet_sync_job_id;
  if (!id || Zustand.walletSyncJob === id) return;
  Zustand.walletSyncJob = id;
  if (Zustand.config) Zustand.config.wallet_sync_job_id = id;
  Zustand.walletSyncLogStand = { index: 0 };
  logZeile("Tip-Nachzug der Wallets…");
  if (Zustand.walletSyncTimer) clearInterval(Zustand.walletSyncTimer);
  Zustand.walletSyncTimer = setInterval(pruefeWalletSyncJob, 900);
  pruefeWalletSyncJob();
  setzeWalletScanGesperrt();
}

async function pruefeWalletSyncJob() {
  if (!Zustand.walletSyncJob) return;
  try {
    const job = await api(`/jobs/${Zustand.walletSyncJob}`);
    nimmJobLogAb(job, Zustand.walletSyncLogStand);
    if (Array.isArray(job.live_p2p_peers)) {
      nimmLiveP2pPeers(job.live_p2p_peers);
    }
    if (job.running) return;
    if (Zustand.walletSyncTimer) {
      clearInterval(Zustand.walletSyncTimer);
      Zustand.walletSyncTimer = null;
    }
    // Live-Peers nach Scan freigeben — Pille darf wieder auf Probe-Stand.
    Zustand.liveP2pPeers = [];
    Zustand.walletSyncJob = null;
    setzePeerTakt(Zustand.config?.sources);
    if (job.status === "done") {
      const n = job.result?.wallets;
      const u = job.result?.utxo_count;
      if (typeof n === "number") {
        logZeile(
          `Tip-Nachzug fertig: ${n} Wallet(s), ${u ?? "?"} UTXO(s).`,
        );
      }
      await ladeConfig();
      await ladeJobsNav();
      setzeWalletScanGesperrt();
      if (Zustand.ansicht === "wallet" && Zustand.walletId) {
        await zeigeWallet(Zustand.walletId);
      } else {
        zeichneNav();
      }
    } else if (job.status === "cancelled") {
      logZeile("Tip-Nachzug abgebrochen.");
      setzeWalletScanGesperrt();
    } else if (job.error) {
      logZeile(`Tip-Nachzug: ${job.error}`);
      setzeWalletScanGesperrt();
    }
  } catch (_) {
    /* optionaler Hintergrund-Job */
  }
}

function zeichneFussVersion() {
  const ziel = $("#fuss-version");
  if (!ziel) return;
  const ver = (Zustand.config?.version || "").trim();
  if (!ver) {
    ziel.textContent = "";
    return;
  }
  ziel.textContent = `v${ver} · `;
}

function zeichneUiLang() {
  const wahl = $("#ui-lang");
  if (!wahl) return;
  const aktuell =
    (window.SatSageI18n && window.SatSageI18n.currentLang())
    || Zustand.config?.ui_lang
    || "de";
  wahl.value = aktuell === "en" ? "en" : "de";
}

async function speichereUiLang() {
  const wahl = $("#ui-lang");
  if (!wahl || !window.SatSageI18n) return;
  const lang = wahl.value === "en" ? "en" : "de";
  await window.SatSageI18n.setLang(lang, {
    persistEnv: async (code) => {
      const ergebnis = await api("/config/ui-lang", {
        methode: "PUT",
        daten: { ui_lang: code },
      });
      if (Zustand.config) Zustand.config.ui_lang = ergebnis.ui_lang;
    },
  });
  zeichneUiLang();
  if (typeof meldung === "function") {
    meldung(t("settings.language.saved"), "gut");
  }
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

function zeichneUiTheme() {
  const wahl = $("#ui-theme");
  if (!wahl) return;
  wahl.value = liesUiTheme();
}

async function speichereUiTheme() {
  const wahl = $("#ui-theme");
  if (!wahl) return;
  const theme = setzeUiTheme(wahl.value);
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
  zeichneLlmEinstellungen();
  zeichneStatusMailEinstellungen();
  zeichneMempoolStatus();
  zeichneChatAnbindung();
  zeichneNav();
  zeichneFussVersion();
  const hopFeld = $("#sank-hops");
  if (hopFeld) {
    const cap = Number(Zustand.config?.sanktion_max_hops_cap) || 20;
    hopFeld.max = String(cap);
  }
}

async function start() {
  // Console-Token OR password session (StartOS / remote login).
  if (!Token) {
    let auth = null;
    try {
      const antwort = await fetch("/api/auth/status", { credentials: "same-origin" });
      if (antwort.ok) auth = await antwort.json();
    } catch (_) {
      auth = null;
    }
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
  const logSchalter = $("#log-anzeige");
  setzeLogSichtbar(logSchalter.checked);
  logSchalter.addEventListener("change", () => {
    setzeLogSichtbar(logSchalter.checked);
  });
  macheLogZiehbar();
  macheDockSpalter();

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
    const langWahl = $("#ui-lang");
    if (langWahl) {
      langWahl.addEventListener("change", () => {
        speichereUiLang();
      });
    }
    const themeWahl = $("#ui-theme");
    if (themeWahl) {
      themeWahl.addEventListener("change", () => {
        speichereUiTheme();
      });
    }
    window.addEventListener("satsage:lang", () => {
      if (window.SatSageI18n) window.SatSageI18n.applyDom(document);
      // data-i18n-html setzt .env-pfad zurück auf „.env“ — echten Pfad wiederherstellen.
      if (Zustand.config?.env_path) setzeEnvPfad(Zustand.config.env_path);
      zeichneNav();
      zeichneFussVersion();
      zeichneUiLang();
      zeichneSteuerEinstellungen();
      // Template und dynamische Texte ohne data-i18n neu setzen.
      if (window.SatSageI18n) {
        window.SatSageI18n.applyDom($("#vorlage-wallet"));
      }
      const chatLeer = document.querySelector("#chat-verlauf .chat-leer");
      if (chatLeer) chatLeer.textContent = t("dock.empty");
      if (typeof zeichneEinrichtung === "function" && $("#einrichtung") && !$("#einrichtung").hidden) {
        zeichneEinrichtung();
      }
      if (typeof zeichneWalletVerwaltung === "function" && Zustand.ansicht === "wallets") {
        zeichneWalletVerwaltung();
      }
      if (typeof zeichneGefahrWallets === "function" && Zustand.ansicht === "wallets") {
        zeichneGefahrWallets();
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
      zeigeAnsicht("trace");
      if (!Zustand.traceListe) ladeTraceListe();
    });
  document
    .querySelector('[data-ansicht="steuerjahr"]')
    .addEventListener("click", () => {
      zeigeAnsicht("steuerjahr");
      ladeSteuerjahrMitKandidaten();
    });
  document
    .querySelector('[data-ansicht="sanktionen"]')
    .addEventListener("click", () => {
      zeigeAnsicht("sanktionen");
      fuellSankWallets();
      ladeSankCache();
    });

  $("#einrichtung-weiter").addEventListener("click", () => {
    schliesseEinrichtung();
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
  const startSync = $("#start-sync");
  if (startSync) {
    startSync.addEventListener("change", speichereStartSync);
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
  $("#herkunft-alle").addEventListener("click", () => herkunftAllerUtxos());
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
  if (saLaden) saLaden.addEventListener("click", () => ladeSelbstanzeigeKandidaten());
  const saHtml = $("#sa-html");
  if (saHtml) saHtml.addEventListener("click", () => ladeSelbstanzeigeExport("html"));
  const saCsv = $("#sa-csv");
  if (saCsv) saCsv.addEventListener("click", () => ladeSelbstanzeigeExport("csv"));
  const saTxid = $("#sa-txid");
  if (saTxid) {
    saTxid.addEventListener("keydown", (e) => {
      if (e.key === "Enter") ladeSelbstanzeigeKandidaten();
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
  const kursOpt = $("#kurs-historie-opt-in");
  if (kursOpt) {
    kursOpt.addEventListener("change", () => speichereKursHistorieOptInUndSync());
  }
  const kursSync = $("#kurs-historie-sync");
  if (kursSync) {
    kursSync.addEventListener("click", () => speichereKursHistorieOptInUndSync());
  }
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
      meldung(`Test fehlgeschlagen: ${fehler.message}`, "krit");
    }
  });

  window.addEventListener("beforeunload", (e) => {
    if (entwurfGeaendert()) e.preventDefault();
  });

  // Einstieg: Wallets vorhanden → erstes Wallet, sonst Wallet-Verwaltung.
  if ((Zustand.config.wallets || []).length > 0) {
    zeigeWallet(Zustand.config.wallets[0].id);
  } else if (walletsManaged()) {
    oeffneVerwaltung("einstellungen");
  } else {
    oeffneVerwaltung("wallets");
  }

  einrichtungBeimStart();
  // Still nachladen: Server hält Connections; lauter Neu-Test nur über Knopf.
  pruefePeersLeise();

  // Sprachumschalter oben rechts
  const deBtn = $("#lang-de");
  const enBtn = $("#lang-en");
  function markLangButton(code) {
    if (deBtn) deBtn.classList.toggle("aktiv", code === "de");
    if (enBtn) enBtn.classList.toggle("aktiv", code === "en");
  }
  if (deBtn) deBtn.addEventListener("click", async () => {
    if (window.SatSageI18n) {
      await window.SatSageI18n.setLang("de");
      markLangButton("de");
      zeichneUiLang();
    }
  });
  if (enBtn) enBtn.addEventListener("click", async () => {
    if (window.SatSageI18n) {
      await window.SatSageI18n.setLang("en");
      markLangButton("en");
      zeichneUiLang();
    }
  });
  // Initialen Zustand markieren
  const startLang = (window.SatSageI18n && window.SatSageI18n.currentLang()) || "de";
  markLangButton(startLang);
}

start();
