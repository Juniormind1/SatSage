/** Formatierung und UI-Helfer — aus app.js extrahiert (Modularisierung UI-Schritt 4).
 * Klassisches Script: Globals (formatSats, $, t, EmpfangPuls, …). Kein import/export.
 * Laden nach api.js/state.js, vor app.js. Late-Abhängigkeiten (zeigeWallet, ladeEmpfang,
 * zeichneEmpfang*, meldung, …) nur zur Laufzeit — Definitions in app.js/Views danach.
 */

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

