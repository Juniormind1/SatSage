/** Steuerjahr- + Selbstanzeige-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: nutzt Globals aus app.js (Zustand, api, t, $, meldung, format*, …).
 * Kein import/export. Wird nach app.js und vor boot.js geladen.
 */

/** Meta aus Steuerjahr-Tabelle oder zuletzt gezeichnetem Zeitstrahl. */
function utxoMetaAusSteuerjahr(schluessel) {
  if (!schluessel) return null;
  const zeile = document.querySelector(
    `#steuer-tabelle tr[data-key="${CSS.escape(schluessel)}"]`,
  );
  if (zeile) {
    return {
      key: schluessel,
      wallet: zeile.dataset.wallet || "",
      value_sats: zeile.dataset.valueSats
        ? Number(zeile.dataset.valueSats)
        : null,
      address: zeile.dataset.address || "",
    };
  }
  const events = Zustand.steuer?.zeitstrahl?.events || [];
  const treffer = events.find(
    (e) => e.key === schluessel
      || (e.txid != null && `${e.txid}:${e.vout}` === schluessel),
  );
  if (!treffer) return null;
  return {
    key: schluessel,
    wallet: treffer.wallet || "",
    value_sats: treffer.value_sats ?? null,
    address: treffer.address || "",
    time_label: treffer.datum || "",
  };
}

// ---------------------------------------------------------------------------
// Steuerjahr
// ---------------------------------------------------------------------------

/** Haltefrist-Label — auch bevor der Locale-Katalog da ist (nie Roh-Key). */
function haltefristJahreLabel(n) {
  const zahl = Number(n);
  const lang =
    (window.SatSageI18n && typeof window.SatSageI18n.currentLang === "function"
      && window.SatSageI18n.currentLang())
    || "de";
  if (lang === "en") {
    return zahl === 1 ? "1 year" : `${zahl} years`;
  }
  return zahl === 1 ? "1 Jahr" : `${zahl} Jahre`;
}

function fuelleHaltefristAuswahl(select, gewaehlt, jahre) {
  if (!select) return;
  // Dropdown nur 1…10 (plus „keine“); Server-Liste ggf. kürzen.
  let liste = (jahre && jahre.length ? jahre : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    .map((n) => Number(n))
    .filter((n) => Number.isFinite(n) && n >= 1 && n <= 10);
  liste = [...new Set(liste)].sort((a, b) => a - b);
  if (!liste.length) liste = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const wert = String(gewaehlt ?? 1);
  const lang =
    (window.SatSageI18n && typeof window.SatSageI18n.currentLang === "function"
      && window.SatSageI18n.currentLang())
    || "de";
  const stempel = JSON.stringify({ liste, lang });
  // Neu bauen, wenn Stempel anders ODER noch Roh-Keys in den Optionen stehen
  // (erster Fill vor initI18n ließ früher „tax.yearsN“ stehen und blieb hängen).
  const hatRohKey = [...select.options].some(
    (o) => (o.textContent || "").indexOf("tax.") === 0,
  );
  if (select.dataset.gefuellt === stempel && !hatRohKey) {
    select.value = wert;
    if (select.value !== wert) select.value = "1";
    return;
  }
  select.replaceChildren();
  const keine = document.createElement("option");
  keine.value = "0";
  const noneLabel = t("common.none");
  keine.textContent =
    noneLabel && noneLabel !== "common.none"
      ? noneLabel
      : (lang === "en" ? "none" : "keine");
  select.append(keine);
  for (const n of liste) {
    const option = document.createElement("option");
    option.value = String(n);
    option.textContent = haltefristJahreLabel(n);
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
    setzeText(kasten, t("tax.hard.f8c6a72307", { msg: fehler.message }));
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

  const alleE = daten.eintraege || [];
  const erfuelltE = alleE.filter((e) => e.erfuellt);
  const offenE = alleE.filter((e) => !e.erfuellt);
  const ungeprueftE = alleE.filter((e) => !e.geprueft);
  const fiatE = (sats, liste) => formatSatsGemeinsam(sats, liste);

  const kennzahlen = [
    [t("tax.hard.ee18fac200"), fiatE(k.gesamt_sats, alleE), `${k.gesamt_count} UTXOs`, ""],
    [t("tax.hard.91a2ea86bd"), fiatE(k.erfuellt_sats, erfuelltE),
     `${k.erfuellt_count} UTXOs`, "gut"],
    [t("tax.hard.innerhalbHaltefrist"), fiatE(k.offen_sats, offenE),
     k.naechste_frist ? t("tax.hard.ed098d09aa", { naechste_frist: k.naechste_frist }) : `${k.offen_count} UTXOs`,
     "warn",
     true], // separater „klären“ nur für gelbe UTXOs
  ];
  if (k.ungeprueft_count > 0) {
    kennzahlen.push([
      "Ohne Herkunftsanalyse", fiatE(k.ungeprueft_sats, ungeprueftE),
      `${k.ungeprueft_count} UTXOs — Frist evtl. länger`, "ungeprueft",
      true, // Aktion „klären“ nur für graue UTXOs
    ]);
  }
  if (k.ohne_datum > 0) {
    kennzahlen.push([
      t("tax.hard.f99058be55"), String(k.ohne_datum), t("tax.hard.3199eeb8e0"), "",
      false,
    ]);
  }

  for (const [titel, wert, zusatz, art, mitKlaeren] of kennzahlen) {
    const zelle = document.createElement("div");
    zelle.className = "kennzahl";
    const titelEl = document.createElement("span");
    titelEl.className = "kennzahl-titel";
    titelEl.textContent = titel;
    const w = document.createElement("span");
    w.className = `kennzahl-wert ${art}`.trim();
    w.textContent = wert;
    const z = document.createElement("span");
    z.className = "kennzahl-zusatz";
    z.textContent = zusatz;
    zelle.append(titelEl, w, z);
    if (mitKlaeren) {
      const knopf = document.createElement("button");
      knopf.type = "button";
      // Unterschiedliche IDs je Scorecard, damit wir gezielt nur gelbe oder nur graue tracen können
      knopf.id = art === "warn" ? "herkunft-gelb" : "herkunft-grau";
      knopf.className = "knopf knopf-klein kennzahl-aktion";
      knopf.textContent = t("tax.originAll");
      knopf.setAttribute("data-i18n", "tax.originAll");
      if (art === "warn") {
        // Gelb: voll bis extern/Coinbase — erst dann grün oder bestätigt gelb.
        knopf.title = t("tax.yellowClarifyTitle") !== "tax.yellowClarifyTitle"
          ? t("tax.yellowClarifyTitle")
          : t("tax.hard.4f776c0011");
        knopf.setAttribute("data-i18n-title", "tax.yellowClarifyTitle");
        knopf.addEventListener("click", () => {
          herkunftGelbUtxos().catch((fehler) => {
            Zustand.herkunftAlleLaeuft = false;
            const k = $("#steuer-meldung");
            if (!k) return;
            k.className = "hinweis hinweis-krit";
            setzeText(k, fehler.message || String(fehler));
            k.hidden = false;
          });
        });
      } else {
        // Grauer Scorecard-Knopf: alle noch nie analysierten UTXOs
        knopf.title = t("tax.hard.a430621437");
        knopf.setAttribute("data-i18n-title", "");
        knopf.addEventListener("click", () => {
          Promise.resolve(herkunftAllerUtxos()).catch((fehler) => {
            const k = $("#steuer-meldung");
            if (!k) return;
            k.className = "hinweis hinweis-krit";
            setzeText(k, fehler.message || String(fehler));
            k.hidden = false;
          });
        });
      }
      w.append(knopf);
    }
    kasten.append(zelle);
  }

  zeichneZeitstrahl(daten);

  setzeText(
    $("#steuer-zusatz"),
    `${daten.stichtag_label} · Haltefrist ` +
    (daten.haltefrist_jahre ? `${daten.haltefrist_jahre} Jahr(e)` : "keine") +
    (daten.stichtag_regel ? t("ui.hard.2d367c6a18", { stichtag_regel: daten.stichtag_regel }) : "")
  );

  zeichneSteuerUtxoGruppen(daten);

  setzeText($("#steuer-vorbehalt"), (daten.hinweise || []).join(" "));
  $("#steuer-meldung").hidden = true;
  if (typeof wendeKopfFilterSteuerjahrAn === "function") {
    wendeKopfFilterSteuerjahrAn(
      typeof steuerKopfFilter === "function" ? steuerKopfFilter() : null,
    );
  }
}

/** UTXO-Schlüssel in der Steuerjahr-Tabelle (Trace-Sprung, Meta). */
function steuerUtxoSchluessel(eintrag) {
  if (!eintrag) return "";
  if (eintrag.key) return String(eintrag.key);
  if (eintrag.txid == null || eintrag.vout == null) return "";
  return `${eintrag.txid}:${eintrag.vout}`;
}

/**
 * Eine Datenzeile der UTXO-Tabelle (Steuerjahr).
 * *versteckt*: Startzustand in eingeklappten Gruppen.
 */
function zeichneSteuerUtxoZeile(eintrag, daten, { versteckt = true } = {}) {
  const zeile = document.createElement("tr");
  zeile.className = "steuer-utxo-zeile";
  if (versteckt) zeile.hidden = true;

  const schluessel = steuerUtxoSchluessel(eintrag);
  if (schluessel) zeile.dataset.key = schluessel;
  if (eintrag.wallet) zeile.dataset.wallet = eintrag.wallet;
  if (eintrag.address) zeile.dataset.address = eintrag.address;
  if (eintrag.value_sats != null) {
    zeile.dataset.valueSats = String(eintrag.value_sats);
  }
  zeile.dataset.timeLabel = [eintrag.datum, eintrag.frist_ende]
    .filter(Boolean).join(" ");
  if (eintrag.time_ts) zeile.dataset.eventTs = String(eintrag.time_ts);
  zeile.dataset.filterLabels = [
    eintrag.wallet,
    eintrag.herkunft,
    eintrag.grundlage_label,
    eintrag.txid,
    haltefristBeschriftung(eintrag, Boolean(daten && daten.stichtag_regel)),
  ].filter(Boolean).join(" ");

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
  {
    const atTs = Number(eintrag.time_ts || 0) || tsAusBewertungsObjekt(eintrag);
    if (atTs) betrag.textContent = formatSats(eintrag.value_sats, { atTs });
    else betrag.textContent = formatSatsBasis(eintrag.value_sats);
  }

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
  // „nur Wallet-Eingang“: Analyse liegt vor, aber nur Wallet-Zeit — weiterer
  // Trace kann noch grün machen → gelb, nicht grün.
  const nurWallet = eintrag.grundlage === "wallet_eingang";
  marke.className = (eintrag.geprueft && !nurWallet)
    ? "grundlage-ok"
    : "grundlage-offen";
  marke.textContent = eintrag.grundlage_label;
  marke.title = nurWallet
    ? "Bisher nur der Wallet-Eingang bekannt. Gründlicherer Trace kann ein "
      + "älteres Anschaffungsdatum finden und die Haltefrist erfüllen."
    : (eintrag.geprueft
      ? t("tax.hard.e6c55be929")
      : "Nur das Entstehungsdatum des Outputs. Bei Wechselgeld oder "
        + "Konsolidierung ist das zu jung — die Haltefrist kann in Wahrheit "
        + "länger sein.");
  grundlage.append(marke);
  if (eintrag.herkunft) {
    const zusatz = document.createElement("div");
    zusatz.className = "zart";
    zusatz.textContent = eintrag.herkunft;
    grundlage.append(zusatz);
  }
  // Innerhalb Haltefrist + nur Wallet-Eingang → klären (wie Scorecard).
  if (nurWallet && !eintrag.erfuellt) {
    const klaeren = document.createElement("button");
    klaeren.type = "button";
    klaeren.className = "knopf knopf-klein steuer-utxo-klaeren";
    klaeren.textContent = t("tax.originAll") !== "tax.originAll"
      ? t("tax.originAll")
      : "klären";
    klaeren.title = t("tax.yellowClarifyTitle") !== "tax.yellowClarifyTitle"
      ? t("tax.yellowClarifyTitle")
      : t("tax.hard.0edab8771f");
    klaeren.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const key = steuerUtxoSchluessel(eintrag);
      if (!key) return;
      herkunftAllerUtxos({
        knopf: klaeren,
        lauf: "#herkunft-lauf",
        text: "#herkunft-text",
        abbruch: "#herkunft-abbruch",
        meldung: "#steuer-meldung",
        danach: ladeSteuerjahrMitKandidaten,
        utxo_keys: [key],
        steuer: false,
        gelbVertiefen: true,
      });
    });
    grundlage.append(klaeren);
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
  return zeile;
}

/**
 * Klappbare Haltefrist-Gruppe in der UTXO-Tabelle.
 * Startet zugeklappt — lange Listen sonst erdrücken die Ansicht.
 */
function zeichneSteuerUtxoGruppe(titel, eintraege, { art = "", daten }) {
  const tbody = document.createElement("tbody");
  tbody.className = `steuer-gruppe${art ? ` ${art}` : ""}`;

  const sats = eintraege.reduce(
    (summe, e) => summe + (Number(e.value_sats) || 0),
    0,
  );
  const anzahl = eintraege.length;
  const anzahlText = anzahl === 1 ? "1 UTXO" : `${anzahl} UTXOs`;

  const kopfZeile = document.createElement("tr");
  kopfZeile.className = "steuer-gruppe-kopf";

  const kopfZelle = document.createElement("td");
  kopfZelle.colSpan = 7;

  const kopf = document.createElement("button");
  kopf.type = "button";
  kopf.className = "steuer-gruppe-taste";

  const klapp = document.createElement("span");
  klapp.className = "klapp";
  klapp.setAttribute("aria-hidden", "true");

  const name = document.createElement("span");
  name.className = "steuer-gruppe-titel";
  name.textContent = titel;

  const meta = document.createElement("span");
  meta.className = "steuer-gruppe-meta zart";
  meta.textContent = `${anzahlText} · ${formatSatsGemeinsam(sats, eintraege)}`;
  meta.dataset.voll = meta.textContent;

  kopf.append(klapp, name, meta);
  kopfZelle.append(kopf);
  kopfZeile.append(kopfZelle);

  const datenZeilen = eintraege.map((eintrag) =>
    zeichneSteuerUtxoZeile(eintrag, daten, { versteckt: true })
  );

  const setzeGruppe = (auf) => {
    for (const z of datenZeilen) {
      z.hidden = z.dataset.filterAus === "1" || !auf;
    }
    klapp.textContent = auf ? "▾" : "▸";
    kopf.setAttribute("aria-expanded", String(auf));
  };
  tbody._setzeSteuerGruppe = setzeGruppe;
  setzeGruppe(false);

  kopf.addEventListener("click", () => {
    const istZu = datenZeilen.every((z) => z.hidden);
    setzeGruppe(istZu);
  });

  tbody.append(kopfZeile, ...datenZeilen);
  return tbody;
}

/** UTXO-Tabelle: außerhalb / innerhalb Haltefrist, initial zugeklappt. */
function zeichneSteuerUtxoGruppen(daten) {
  const tabelle = $("#steuer-tabelle");
  if (!tabelle) return;

  // Alte Gruppen-tbodys und den leeren Default-Körper ersetzen.
  for (const alt of tabelle.querySelectorAll("tbody")) {
    alt.remove();
  }

  const liste = daten.eintraege || [];
  if (liste.length === 0) {
    const koerper = document.createElement("tbody");
    koerper.id = "steuer-koerper";
    const zeile = document.createElement("tr");
    const zelle = document.createElement("td");
    zelle.colSpan = 7;
    zelle.className = "zart";
    zelle.style.padding = "20px 0";
    zelle.textContent = t("tax.hard.a2708f164f");
    zeile.append(zelle);
    koerper.append(zeile);
    tabelle.append(koerper);
    return;
  }

  const erfuellt = liste.filter((e) => e.erfuellt);
  const offen = liste.filter((e) => !e.erfuellt);

  // Reihenfolge wie Scorecard: außerhalb (grün), dann innerhalb (gelb).
  if (erfuellt.length) {
    tabelle.append(zeichneSteuerUtxoGruppe(
      t("tax.haltefristOut"),
      erfuellt,
      { art: "erfuellt", daten },
    ));
  }
  if (offen.length) {
    tabelle.append(zeichneSteuerUtxoGruppe(
      t("tax.haltefristIn"),
      offen,
      { art: "offen", daten },
    ));
  }
}

/**
 * Zeitstrahl-Ansicht: X-Fenster (Pan/Zoom) über dem 0..100 %-Datenraum.
 * Y kommt bereits logarithmisch (log1p) aus core/tax.zeitstrahl.
 */
const ZeitstrahlAnsicht = {
  daten: null,
  x0: 0,
  x1: 100,
  gebunden: false,
};

const ZEITSTRAHL_MIN_SPAN = 2;

/** Datum dd.mm.yyyy → Date (lokal, Mittag — vermeidet DST-Kanten). */
function parseDeDatum(text) {
  const m = String(text || "").match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!m) return null;
  return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]), 12, 0, 0);
}

function formatTickMonatJahr(d) {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${mm}/${d.getFullYear()}`;
}

/** Daten-% → sichtbare left-% im aktuellen X-Fenster. */
function zeitstrahlSichtPos(pos) {
  const span = ZeitstrahlAnsicht.x1 - ZeitstrahlAnsicht.x0;
  if (span <= 0) return 50;
  return ((pos - ZeitstrahlAnsicht.x0) / span) * 100;
}

function zeitstrahlFensterBegrenzen() {
  let { x0, x1 } = ZeitstrahlAnsicht;
  let span = x1 - x0;
  if (span < ZEITSTRAHL_MIN_SPAN) {
    const mitte = (x0 + x1) / 2;
    x0 = mitte - ZEITSTRAHL_MIN_SPAN / 2;
    x1 = mitte + ZEITSTRAHL_MIN_SPAN / 2;
    span = ZEITSTRAHL_MIN_SPAN;
  }
  if (span > 100) {
    x0 = 0;
    x1 = 100;
  } else {
    if (x0 < 0) {
      x1 -= x0;
      x0 = 0;
    }
    if (x1 > 100) {
      x0 -= x1 - 100;
      x1 = 100;
    }
    x0 = Math.max(0, x0);
    x1 = Math.min(100, x1);
  }
  ZeitstrahlAnsicht.x0 = x0;
  ZeitstrahlAnsicht.x1 = x1;
}

/**
 * Zoom nur auf der Zeitachse. ankerSichtPct: Mausposition im Viewport 0..100.
 */
function zeitstrahlZoom(faktor, ankerSichtPct) {
  zeitstrahlFensterBegrenzen();
  const { x0, x1 } = ZeitstrahlAnsicht;
  const span = x1 - x0;
  const anker = x0 + (ankerSichtPct / 100) * span;
  const neu = Math.min(100, Math.max(ZEITSTRAHL_MIN_SPAN, span * faktor));
  const linksAnteil = span > 0 ? (anker - x0) / span : 0.5;
  ZeitstrahlAnsicht.x0 = anker - linksAnteil * neu;
  ZeitstrahlAnsicht.x1 = ZeitstrahlAnsicht.x0 + neu;
  zeitstrahlFensterBegrenzen();
}

function zeitstrahlPan(deltaSichtPct) {
  const span = ZeitstrahlAnsicht.x1 - ZeitstrahlAnsicht.x0;
  const shift = (deltaSichtPct / 100) * span;
  ZeitstrahlAnsicht.x0 -= shift;
  ZeitstrahlAnsicht.x1 -= shift;
  zeitstrahlFensterBegrenzen();
}

/** Gleichmäßig verteilte Tick-Labels für das sichtbare X-Fenster. */
function zeitstrahlTicksImFenster(strahl) {
  const von = parseDeDatum(strahl.von);
  const bis = parseDeDatum(strahl.bis);
  if (!von || !bis) {
    return (strahl.ticks || []).map((tick) => tick.label);
  }
  const gesamtMs = bis.getTime() - von.getTime();
  const { x0, x1 } = ZeitstrahlAnsicht;
  const schritte = 4;
  const labels = [];
  for (let i = 0; i <= schritte; i += 1) {
    const dataPct = x0 + ((x1 - x0) * i) / schritte;
    const tMs = von.getTime() + (gesamtMs * dataPct) / 100;
    labels.push(formatTickMonatJahr(new Date(tMs)));
  }
  return labels;
}

/**
 * Dekaden-Ticks für die log1p-Y-Achse: 1, 10, 100, 1k … bis max.
 * max selbst nur, wenn er deutlich über der letzten Dekade liegt.
 */
function zeitstrahlYTickSats(maxSats) {
  const max = Math.max(0, Math.round(Number(maxSats) || 0));
  if (max <= 0) return [0];
  const ticks = [0];
  for (let s = 1; s <= max && s <= 1e15; s *= 10) {
    ticks.push(s);
  }
  const letzte = ticks[ticks.length - 1];
  // Oberkante beschriften, wenn max spürbar über der letzten Dekade liegt.
  if (max > letzte && max / letzte >= 1.4) {
    ticks.push(max);
  } else if (max > letzte) {
    // eng an Dekade: max gewinnt (exakter Top-Wert)
    ticks[ticks.length - 1] = max;
  }
  // Nur bei extremen Spannen ausdünnen (normale BTC-Bereiche: alle Dekaden).
  const maxLabels = 14;
  if (ticks.length <= maxLabels) return ticks;
  const oben = ticks[ticks.length - 1];
  const dekaden = ticks.slice(1, -1);
  const behalten = [0];
  const schritt = Math.ceil(dekaden.length / (maxLabels - 2));
  for (let i = 0; i < dekaden.length; i += schritt) {
    behalten.push(dekaden[i]);
  }
  if (behalten[behalten.length - 1] !== oben) behalten.push(oben);
  return behalten;
}

/**
 * Durchmesser des einen Geister-Saldos (außerhalb Haltefrist) auf y=0.
 * Logarithmisch am größeren von Saldo und max. Einzel-UTXO.
 */
function geisterSaldoDurchmesserPx(saldoSats, maxUtxoSats) {
  const minD = 10;
  const maxD = 40;
  const s = Math.max(0, Number(saldoSats) || 0);
  const m = Math.max(s, Math.max(0, Number(maxUtxoSats) || 0), 1);
  if (s <= 0) return minD;
  const t = Math.log1p(s) / Math.log1p(m);
  return Math.round(minD + Math.max(0, Math.min(1, t)) * (maxD - minD));
}

/**
 * Y-Achsenbeschriftung zur log1p-Skala (oben = max, unten = 0).
 * Stil wie X-Achse: Linie + mono/blass-Ticks an Zehnerpotenzen.
 */
function zeichneZeitstrahlYAchse(maxSats) {
  const yAchse = $("#achse-y");
  if (!yAchse) return;
  yAchse.replaceChildren();
  yAchse.removeAttribute("aria-hidden");

  const max = Math.max(Number(maxSats) || 0, 0);
  const skala = document.createElement("div");
  skala.className = "achse-y-skala";

  // Senkrechte Linie — Pendant zu .achse-linie auf der X-Achse.
  const linie = document.createElement("div");
  linie.className = "achse-y-linie";
  linie.setAttribute("aria-hidden", "true");
  skala.append(linie);

  const logMax = Math.log1p(max);
  for (const sats of zeitstrahlYTickSats(max)) {
    const span = document.createElement("span");
    span.className = "achse-y-tick";
    span.textContent = formatZeitstrahlBetrag(sats);
    const y = max <= 0 || logMax <= 0
      ? 0
      : (Math.log1p(sats) / logMax) * 100;
    span.style.bottom = `${y}%`;
    skala.append(span);
  }
  yAchse.append(skala);
}

function bindeZeitstrahlInteraktion() {
  if (ZeitstrahlAnsicht.gebunden) return;
  const viewport = $("#achse-viewport");
  if (!viewport) return;
  ZeitstrahlAnsicht.gebunden = true;

  viewport.addEventListener("wheel", (ereignis) => {
    if (!ZeitstrahlAnsicht.daten) return;
    ereignis.preventDefault();
    const rect = viewport.getBoundingClientRect();
    if (rect.width <= 0) return;
    const anker = ((ereignis.clientX - rect.left) / rect.width) * 100;
    // Runter = rauszoomen, hoch = reinzoomen — nur X.
    const faktor = ereignis.deltaY > 0 ? 1.15 : 1 / 1.15;
    zeitstrahlZoom(faktor, anker);
    zeichneZeitstrahl(ZeitstrahlAnsicht.daten, { fensterBehalten: true });
  }, { passive: false });

  // Mittelklick soll pannen, nicht Autoscroll/Paste.
  viewport.addEventListener("auxclick", (ereignis) => {
    if (ereignis.button === 1) ereignis.preventDefault();
  });

  // Move/Up am window: sonst verliert man den Drag, sobald der Zeiger
  // die Spur verlässt oder Punkte beim Neuzeichnen ausgetauscht werden.
  // Links (0) und Mittel (1) pannen — nur wenn reingezoomt.
  // Klick auf UTXO-Bubble (links) startet keinen Drag.
  viewport.addEventListener("pointerdown", (ereignis) => {
    if (!ZeitstrahlAnsicht.daten) return;
    if (ereignis.button !== 0 && ereignis.button !== 1) return;
    if (ZeitstrahlAnsicht.x1 - ZeitstrahlAnsicht.x0 >= 99.9) return;
    if (
      ereignis.button === 0
      && ereignis.target
      && ereignis.target.closest
      && ereignis.target.closest(".achse-punkt:not(.geister)")
    ) {
      return;
    }
    ereignis.preventDefault();
    const drag = { id: ereignis.pointerId, x: ereignis.clientX };
    viewport.classList.add("ziehend");

    const onMove = (ev) => {
      if (ev.pointerId !== drag.id) return;
      const rect = viewport.getBoundingClientRect();
      if (rect.width <= 0) return;
      const deltaPct = ((ev.clientX - drag.x) / rect.width) * 100;
      drag.x = ev.clientX;
      if (deltaPct === 0) return;
      zeitstrahlPan(deltaPct);
      zeichneZeitstrahl(ZeitstrahlAnsicht.daten, { fensterBehalten: true });
    };
    const onUp = (ev) => {
      if (ev.pointerId !== drag.id) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      viewport.classList.remove("ziehend");
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  });

  viewport.addEventListener("dblclick", () => {
    if (!ZeitstrahlAnsicht.daten) return;
    ZeitstrahlAnsicht.x0 = 0;
    ZeitstrahlAnsicht.x1 = 100;
    zeichneZeitstrahl(ZeitstrahlAnsicht.daten, { fensterBehalten: true });
  });
}

/**
 * Zeichnet die Zeitachse der UTXOs.
 *
 * X und Y kommen als Prozentwerte aus core/tax.zeitstrahl — hier wird
 * gezeichnet und das X-Fenster (Pan/Zoom) angewendet. Y ist log1p.
 */
function zeichneZeitstrahl(daten, optionen = {}) {
  const karte = $("#zeitstrahl-karte");
  const strahl = daten.zeitstrahl;

  if (!strahl || !strahl.vorhanden || strahl.events.length === 0) {
    karte.hidden = true;
    ZeitstrahlAnsicht.daten = null;
    return;
  }
  karte.hidden = false;

  ZeitstrahlAnsicht.daten = daten;
  if (!optionen.fensterBehalten) {
    ZeitstrahlAnsicht.x0 = 0;
    ZeitstrahlAnsicht.x1 = 100;
  }
  zeitstrahlFensterBegrenzen();
  bindeZeitstrahlInteraktion();

  const viewport = $("#achse-viewport");
  if (viewport) {
    viewport.removeAttribute("title");
  }

  zeichneZeitstrahlYAchse(strahl.max_sats || 0);

  const spur = $("#achse-spur");
  spur.replaceChildren();

  const linie = document.createElement("div");
  linie.className = "achse-linie";
  spur.append(linie);

  if (strahl.frist_pos !== null && strahl.frist_pos !== undefined) {
    const sicht = zeitstrahlSichtPos(strahl.frist_pos);
    if (sicht >= -2 && sicht <= 102) {
      const grenze = document.createElement("div");
      grenze.className = "achse-frist";
      grenze.style.left = `${sicht}%`;

      const beschriftung = document.createElement("span");
      // Nah am rechten Rand würde die Beschriftung sonst abgeschnitten.
      beschriftung.className =
        sicht > 70 ? "achse-frist-text rechts" : "achse-frist-text";
      beschriftung.textContent = t("tax.deadlineLine", { date: strahl.frist_datum });
      grenze.append(beschriftung);
      spur.append(grenze);
    }
  }

  // Sats vor Haltefrist: ein grüner Ring auf y=0 an der Fristgrenze,
  // Label horizontal links davon, knapp über der X-Achse.
  const geist = strahl.geister_saldo;
  if (geist && Number(geist.value_sats || 0) > 0) {
    const gSicht = zeitstrahlSichtPos(geist.pos);
    if (gSicht >= -5 && gSicht <= 105) {
      const gruppe = document.createElement("div");
      gruppe.className = "achse-geister";
      gruppe.style.left = `${gSicht}%`;
      const gLabel = document.createElement("span");
      gLabel.className = "achse-geister-label";
      const saldoText = formatZeitstrahlBetrag(geist.value_sats);
      gLabel.textContent = t("tax.satsBeforeHolding", { saldo: saldoText })
        !== "tax.satsBeforeHolding"
        ? t("tax.satsBeforeHolding", { saldo: saldoText })
        : `sats vor Haltefrist: ${saldoText}`;
      const ring = document.createElement("span");
      ring.className = "achse-punkt geister erfuellt";
      const d = geisterSaldoDurchmesserPx(
        geist.value_sats,
        strahl.max_sats || geist.value_sats,
      );
      ring.style.width = `${d}px`;
      ring.style.height = `${d}px`;
      gruppe.append(gLabel, ring);
      spur.append(gruppe);
    }
  }

  for (const eintrag of strahl.events) {
    const sicht = zeitstrahlSichtPos(eintrag.pos);
    if (sicht < -5 || sicht > 105) continue;

    const lage = haltefristBeschriftung(
      eintrag, Boolean(daten.stichtag_regel),
    );
    const y = Number(eintrag.y ?? 0);
    const key = eintrag.key
      || (eintrag.txid != null && eintrag.vout != null
        ? `${eintrag.txid}:${eintrag.vout}`
        : "");

    const punkt = document.createElement("span");
    // Farbe:
    // - außerhalb Haltefrist / prä-Stichtag → grün (auch ohne Herkunft)
    // - innerhalb Haltefrist + Herkunft: gelb
    // - innerhalb Haltefrist + ohne Herkunft: grau (nicht gelb)
    let farbe;
    if (eintrag.erfuellt) {
      farbe = "erfuellt";
    } else if (eintrag.geprueft) {
      farbe = "offen";
    } else {
      farbe = "ungeprueft";
    }
    punkt.className = `achse-punkt ${eintrag.groesse} ${farbe}`;
    if (key) punkt.dataset.key = key;
    if (eintrag.value_sats != null) {
      punkt.dataset.valueSats = String(eintrag.value_sats);
    }
    if (eintrag.address) punkt.dataset.address = eintrag.address;
    punkt.dataset.timeLabel = eintrag.datum || "";
    const punktTs = Number(eintrag.time_ts || 0) || tsAusDeDatumMittag(eintrag.datum);
    if (punktTs) punkt.dataset.eventTs = String(punktTs);
    punkt.dataset.filterLabels = [
      eintrag.wallet, eintrag.txid, lage,
    ].filter(Boolean).join(" ");
    if (key) {
      punkt.classList.add("klickbar");
      punkt.title =
        "HTML-Report für dieses UTXO (Was-wäre-wenn). "
        + "Angekreuzte Abflüsse/UTXOs unten werden mit einbezogen.";
    }
    punkt.style.left = `${sicht}%`;
    punkt.style.bottom = `${y}%`;
    // Betrag/Datum/Wallet nur im Hover-Tooltip — feste Labels überladen den Plot.
    const tip = document.createElement("span");
    tip.className = sicht > 70 ? "achse-punkt-tip links" : "achse-punkt-tip";
    const herkunftHinweis = (!eintrag.geprueft && !eintrag.erfuellt)
      ? (t("tax.legendUnchecked") !== "tax.legendUnchecked"
        ? t("tax.legendUnchecked")
        : t("ui.hard.e66ad7aa49"))
      : "";
    tip.textContent = [
      eintrag.datum || "",
      formatZeitstrahlBetrag(eintrag.value_sats),
      `${eintrag.wallet || "unbekannt"} · ${lage}`,
      herkunftHinweis,
    ].filter(Boolean).join("\n");
    punkt.append(tip);
    if (key) {
      punkt.addEventListener("click", (ereignis) => {
        ereignis.preventDefault();
        ereignis.stopPropagation();
        // HTML-Report: angekreuzte Zeilen, sonst nur dieses UTXO.
        const angekreuzt = saAnkreuzAuswahl();
        const hatAuswahl =
          angekreuzt.txids.length > 0 || angekreuzt.utxos.length > 0;
        const auswahl = hatAuswahl
          ? angekreuzt
          : { txids: [], utxos: [key] };
        ladeSelbstanzeigeExport("html", auswahl);
      });
    }
    spur.append(punkt);
  }

  const ticks = $("#achse-ticks");
  ticks.replaceChildren();
  for (const label of zeitstrahlTicksImFenster(strahl)) {
    const span = document.createElement("span");
    span.textContent = label;
    ticks.append(span);
  }

  const zusatz = [`${strahl.von} bis ${strahl.bis}`];
  if (daten.laufend) {
    zusatz.push(t("ui.hard.915044225f"));
  }
  setzeText($("#zeitstrahl-zusatz"), zusatz.join(" · "));
  if (typeof wendeKopfFilterSteuerPunkte === "function") {
    wendeKopfFilterSteuerPunkte(
      typeof steuerKopfFilter === "function" ? steuerKopfFilter() : null,
    );
  }
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
      ? t("ui.hard.c2b3477341")
      : `${abgaenge.length} · ${formatSatsGemeinsam(
        k.abgang_sats,
        abgaenge,
        (a) => Number(a.abgang_time_ts || 0) || tsAusBewertungsObjekt(a),
      )}` +
        (k.abgang_steuerpflichtig_count
          ? ` · davon ${k.abgang_steuerpflichtig_count} innerhalb der Frist`
          : " · alle nach Ablauf der Frist")
  );
  const abZusatz = $("#abgaenge-zusatz");
  if (abZusatz) abZusatz.dataset.voll = abZusatz.textContent;

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
    const abKey = abgang.txid != null && abgang.vout != null
      ? `${abgang.txid}:${abgang.vout}`
      : (abgang.abgang_txid || abgang.txid || "");
    if (abKey) zeile.dataset.key = abKey;
    if (abgang.address) zeile.dataset.address = abgang.address;
    if (abgang.value_sats != null) {
      zeile.dataset.valueSats = String(abgang.value_sats);
    }
    zeile.dataset.timeLabel = [abgang.datum, abgang.abgang_datum]
      .filter(Boolean).join(" ");
    const abTs = Number(abgang.abgang_time_ts || abgang.time_ts || 0);
    if (abTs > 0) zeile.dataset.eventTs = String(abTs);
    zeile.dataset.filterLabels = [
      abgang.wallet, abgang.abgang_txid, abgang.txid,
      haltefristBeschriftung(
        { erfuellt: abgang.frist_erfuellt, neuvermoegen: abgang.neuvermoegen },
        Boolean(daten.stichtag_regel),
      ),
    ].filter(Boolean).join(" ");

    const marke = pille(
      abgang.frist_erfuellt ? "gut" : "krit",
      haltefristBeschriftung(
        { erfuellt: abgang.frist_erfuellt, neuvermoegen: abgang.neuvermoegen },
        Boolean(daten.stichtag_regel),
      )
    );

    const betrag = document.createElement("span");
    betrag.className = "mono";
    {
      // Fiat am Abgangstag (Veräußerung), nicht Anschaffung.
      const atTs = Number(abgang.abgang_time_ts || 0)
        || tsAusBewertungsObjekt({ datum: abgang.abgang_datum });
      if (atTs) betrag.textContent = formatSats(abgang.value_sats, { atTs });
      else betrag.textContent = formatSatsBasis(abgang.value_sats);
    }

    const zeitraum = document.createElement("span");
    zeitraum.className = "zart";
    zeitraum.textContent =
      `${abgang.datum} → ${abgang.abgang_datum} · ` +
      `${formatHaltedauer(abgang.haltedauer_tage)} gehalten`;

    const wer = document.createElement("span");
    wer.className = "zart";
    wer.textContent = abgang.wallet || "";

    zeile.append(marke, betrag, zeitraum, wer);
    // Abgangs-Tx (Spend) bevorzugen; sonst der UTXO-Erzeuger.
    const extern = mempoolVerweis(
      "tx",
      abgang.abgang_txid || abgang.txid,
    );
    if (extern) zeile.append(extern);
    liste.append(zeile);
  }
}

/** Aktueller GUI-Farbmodus für HTML-Berichte (data-theme / UI_THEME). */
function guiThemeFuerBericht() {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "dark" || attr === "light") return attr;
  try {
    const lokal = localStorage.getItem("satsage-ui-theme");
    if (lokal === "dark" || lokal === "light") return lokal;
  } catch (_) { /* private mode */ }
  return Zustand.config?.ui_theme === "dark" ? "dark" : "light";
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
    `&theme=${encodeURIComponent(guiThemeFuerBericht())}` +
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
 * FiFo-/Report-Kandidaten aus dem Cache (Abflüsse + Was-wäre-wenn-UTXOs).
 *
 * Technisch: GET /tax/selbstanzeige/kandidaten — reiner Cache-Read, kein Trace.
 * Wird beim Öffnen des Steuerjahrs und bei Tip-Nachzug/Jahr-Wechsel oft
 * mitgeladen; das ist **kein** Herkunfts-Job.
 *
 * *opts.auto*: still nachladen (kein Log-Spam).
 * *opts.laut*: manuell (Knopf) — eine Zeile „FiFo-Kandidaten: …“ ins Log.
 */
async function ladeSelbstanzeigeKandidaten(opts = {}) {
  const auto = Boolean(opts.auto);
  const laut = Boolean(opts.laut) || !auto;
  const jahr = $("#jahr-wahl").value;
  const txid = ($("#sa-txid")?.value || "").trim();
  const liste = $("#sa-liste");
  if (!liste) return;
  // Nur bei bewusstem Laden loggen — Auto-Refresh (Jahr, Tip, Fokus) sonst
  // flutet das Log mit „Selbstanzeige:“ während ganz anderer Arbeit (Trace).
  if (laut) logZeile(t("ui.hard.221032d4fb"));
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
    if (laut) {
      const n = Zustand.saKandidaten.length;
      const u = Zustand.saUtxos.length;
      logZeile(
        t("ui.hard.92999accba", { n, u }),
      );
    }
  } catch (fehler) {
    liste.textContent = t("common.errorPrefix", { msg: fehler.message });
    if (laut) {
      logZeile(t("ui.hard.52e00c1044", { msg: fehler.message }));
    }
  }
}

/** Steuerjahr öffnen bzw. Jahr gewechselt: Auswertung + Kandidaten parallel. */
async function ladeSteuerjahrMitKandidaten() {
  await Promise.all([
    ladeSteuerjahr(),
    ladeSelbstanzeigeKandidaten({ auto: true }),
  ]);
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
  zeile.dataset.key = k.txid || k.id || "";
  if (k.netto_sats != null) zeile.dataset.valueSats = String(k.netto_sats);
  zeile.dataset.timeLabel = [k.abgang_datum, k.abgang_zeit].filter(Boolean).join(" ");
  if (k.abgang_ts) zeile.dataset.eventTs = String(k.abgang_ts);
  const abflussAdressen = (k.inputs || []).map((i) => i.address).filter(Boolean);
  if (abflussAdressen.length) zeile.dataset.address = abflussAdressen.join(" ");
  zeile.dataset.filterLabels = [...(k.wallets || []), k.txid].filter(Boolean).join(" ");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.value = k.id || k.txid;
  box.dataset.art = "abfluss";
  box.checked = Boolean(k.ausgewaehlt);
  if (k.eigenuebertrag) {
    box.title =
      t("ui.hard.adee7fb307");
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
    (k.eigenuebertrag ? t("ui.hard.423403ec7f") : "");
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
  zeile.append(
    saZeilenReportAktionen({
      art: "abfluss",
      id: box.value,
      txid: k.txid,
    }),
  );
  return zeile;
}

function zeichneSaUtxoZeile(u) {
  const zeile = document.createElement("label");
  zeile.className = "sa-zeile";
  const utxoKey = u.txid != null && u.vout != null
    ? `${u.txid}:${u.vout}`
    : (u.id || "");
  if (utxoKey) zeile.dataset.key = utxoKey;
  if (u.address) zeile.dataset.address = u.address;
  if (u.value_sats != null) zeile.dataset.valueSats = String(u.value_sats);
  zeile.dataset.timeLabel = [u.anschaffung_datum, u.stichtag].filter(Boolean).join(" ");
  const anschaffungTs = tsAusDeDatumMittag(u.anschaffung_datum);
  if (anschaffungTs) zeile.dataset.eventTs = String(anschaffungTs);
  zeile.dataset.filterLabels = [
    u.wallet, u.external_address, u.grundlage, u.txid,
  ].filter(Boolean).join(" ");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.value = u.id || `utxo:${u.txid}:${u.vout}`;
  box.dataset.art = "utxo";
  box.checked = Boolean(u.ausgewaehlt);
  box.title =
    t("ui.hard.3e6cbfdc60");
  const text = document.createElement("span");
  const titel = document.createElement("div");
  titel.className = "mono";
  titel.textContent = `${u.txid}:${u.vout}`;
  const meta = document.createElement("div");
  meta.className = "sa-meta";
  meta.textContent =
    `${formatSats(u.value_sats)} · ${u.wallet || "?"}` +
    (u.anschaffung_datum ? ` · Anschaffung ${u.anschaffung_datum}` : "") +
    (u.stichtag ? t("ui.hard.11361714f6", { stichtag: u.stichtag }) : "") +
    (u.address ? ` · ${u.address}` : "");
  text.append(titel, meta);
  zeile.append(box, text);
  const utxoId = box.value.startsWith("utxo:")
    ? box.value.slice(5)
    : box.value;
  zeile.append(
    saZeilenReportAktionen({
      art: "utxo",
      id: utxoId,
      txid: u.txid,
    }),
  );
  return zeile;
}

/**
 * Pro Zeile: HTML + CSV, dann ↗ rechts daneben.
 * Mit Ankreuzungen → Report für alle angekreuzten;
 * ohne Ankreuzung → nur diese Zeile (Fallback, wenn der Kopf-Knopf außer Sicht ist).
 */
function saZeilenReportAktionen({ art, id, txid }) {
  const wrap = document.createElement("span");
  wrap.className = "sa-zeile-aktionen";

  const zeilenAuswahl =
    art === "utxo"
      ? { txids: [], utxos: [id] }
      : { txids: [id], utxos: [] };

  for (const { key, label, title } of [
    {
      key: "html",
      label: "HTML",
      title:
        t("ui.hard.66e1d8f8c2"),
    },
    {
      key: "csv",
      label: "CSV",
      title:
        t("ui.hard.4161822366"),
    },
  ]) {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "knopf knopf-klein sa-zeile-report";
    knopf.textContent = label;
    knopf.title = title;
    knopf.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const angekreuzt = saAnkreuzAuswahl();
      const hatAuswahl =
        angekreuzt.txids.length > 0 || angekreuzt.utxos.length > 0;
      ladeSelbstanzeigeExport(
        key,
        hatAuswahl ? angekreuzt : zeilenAuswahl,
      );
    });
    wrap.append(knopf);
  }

  const extern = mempoolVerweis("tx", txid);
  if (extern) wrap.append(extern);
  return wrap;
}

/** Wie viele UTXO-Zeilen sofort; Rest per „Weitere laden“ (UI bleibt bedienbar). */
const SA_UTXO_CHUNK = 40;

function zeichneSelbstanzeigeKandidaten() {
  const liste = $("#sa-liste");
  if (!liste) return;
  liste.replaceChildren();

  const abfluesse = Zustand.saKandidaten || [];
  const utxos = Zustand.saUtxos || [];
  const verlauf = Zustand.saVerlauf;

  const ab = saAbschnitt(
    t("tax.hard.b5128ead22"),
    abfluesse.length
      ? `${abfluesse.length} Kandidat(en)`
      : "keine",
    {
      offen: false,
      ausklappbar: abfluesse.length > 0,
      leerText: abfluesse.length
        ? ""
        : t("ui.hard.38c0e7c352"),
    },
  );
  const abFrag = document.createDocumentFragment();
  for (const k of abfluesse) abFrag.append(zeichneSaAbflussZeile(k));
  ab.innen.append(abFrag);
  liste.append(ab.details);

  const stichtag = Zustand.saStichtag
    ? t("ui.hard.11361714f6", { stichtag: Zustand.saStichtag })
    : "";
  // UTXOs aufklappen, wenn keine Abflüsse — sonst sieht man keine Checkboxen.
  const ut = saAbschnitt(
    t("tax.hard.bb993ba73a"),
    utxos.length
      ? `${utxos.length} UTXO(s)${stichtag}`
      : `keine${stichtag}`,
    {
      offen: utxos.length > 0 && abfluesse.length === 0,
      ausklappbar: utxos.length > 0,
      leerText: utxos.length
        ? ""
        : t("ui.hard.3939cbbda7"),
    },
  );
  if (utxos.length) {
    const hinweis = document.createElement("p");
    hinweis.className = "sa-leer";
    hinweis.textContent =
      "Checkbox ankreuzen → Report. Angekreuzte UTXOs werden fiktiv zum Stichtag " +
      t("ui.hard.c5ddd7fafe");
    ut.innen.append(hinweis);

    const werkzeug = document.createElement("div");
    werkzeug.className = "sa-werkzeug";
    const alle = document.createElement("button");
    alle.type = "button";
    alle.className = "knopf knopf-klein";
    alle.textContent = t("ui.hard.b0ca3442c8");
    alle.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      for (const el of ut.innen.querySelectorAll(
        "input[type=checkbox][data-art=utxo]",
      )) {
        if (el.closest(".sa-zeile")?.hidden) continue;
        el.checked = true;
      }
    });
    const keine = document.createElement("button");
    keine.type = "button";
    keine.className = "knopf knopf-klein";
    keine.textContent = "Keine";
    keine.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      for (const el of ut.innen.querySelectorAll(
        "input[type=checkbox][data-art=utxo]",
      )) {
        if (el.closest(".sa-zeile")?.hidden) continue;
        el.checked = false;
      }
    });
    werkzeug.append(alle, keine);
    ut.innen.append(werkzeug);
  }

  // Chunked render — große Listen blockieren sonst den Main-Thread.
  let gezeigt = 0;
  const host = document.createElement("div");
  host.className = "sa-utxo-host";
  ut.innen.append(host);

  const mehr = document.createElement("button");
  mehr.type = "button";
  mehr.className = "knopf knopf-klein sa-mehr";
  mehr.hidden = true;

  let gefiltertVoll = false;

  function saChecksLesen() {
    const gesehen = new Set();
    const an = new Set();
    for (const el of liste.querySelectorAll("input[type=checkbox]")) {
      const id = `${el.dataset.art}:${el.value}`;
      gesehen.add(id);
      if (el.checked) an.add(id);
    }
    return { gesehen, an };
  }

  function zeichneSaUtxoMitCheck(u) {
    const zeile = zeichneSaUtxoZeile(u);
    const box = zeile.querySelector("input[type=checkbox]");
    const stand = Zustand._saChecks;
    if (box && stand) {
      const id = `${box.dataset.art}:${box.value}`;
      if (stand.gesehen.has(id)) box.checked = stand.an.has(id);
    }
    return zeile;
  }

  function haengeUtxoChunk() {
    const frag = document.createDocumentFragment();
    const ende = Math.min(gezeigt + SA_UTXO_CHUNK, utxos.length);
    for (; gezeigt < ende; gezeigt++) {
      frag.append(zeichneSaUtxoMitCheck(utxos[gezeigt]));
    }
    host.append(frag);
    if (gezeigt < utxos.length) {
      mehr.hidden = false;
      mehr.textContent = t("ui.hard.7244232282", { n: utxos.length - gezeigt });
    } else {
      mehr.hidden = true;
    }
  }

  // Filter: alle passenden UTXOs zeichnen (nicht nur den ersten Chunk).
  // Zurück auf leer: wieder stückweise, Häkchen bleiben.
  liste._saFilterNachladen = () => {
    const roh = ($("#kopf-filter")?.value || "").trim();
    if (gefiltertVoll && liste.dataset.saFilterRoh === roh) return;
    const f = typeof kopfFilterGelesen === "function"
      ? kopfFilterGelesen()
      : null;
    if (!f || f.leer || typeof _kopfFilterLeafOk !== "function") return;
    Zustand._saChecks = saChecksLesen();
    host.replaceChildren();
    const frag = document.createDocumentFragment();
    for (const u of utxos) {
      const zeile = zeichneSaUtxoMitCheck(u);
      if (!_kopfFilterLeafOk(zeile, f)) continue;
      frag.append(zeile);
    }
    host.append(frag);
    gezeigt = utxos.length;
    gefiltertVoll = true;
    liste.dataset.saFilterRoh = roh;
    mehr.hidden = true;
    Zustand._saChecks = null;
  };
  liste._saFilterZurueck = () => {
    if (!gefiltertVoll) return;
    Zustand._saChecks = saChecksLesen();
    host.replaceChildren();
    gezeigt = 0;
    gefiltertVoll = false;
    liste.dataset.saFilterRoh = "";
    haengeUtxoChunk();
    Zustand._saChecks = null;
  };
  mehr.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    haengeUtxoChunk();
  });
  haengeUtxoChunk();
  ut.innen.append(mehr);
  liste.append(ut.details);

  if (verlauf) {
    const teile = [];
    if (verlauf.vorhanden) teile.push("Verlaufsdaten vorhanden");
    else teile.push(t("ui.hard.c8e050f46b"));
    if (verlauf.empfaenge_im_jahr != null) {
      teile.push(t("ui.hard.3da5578025", { n: verlauf.empfaenge_im_jahr }));
    }
    if (verlauf.abgaenge_im_jahr != null) {
      teile.push(`${verlauf.abgaenge_im_jahr} Abgangszeilen im Jahr`);
    }
    if (verlauf.offen_utxos != null) {
      teile.push(`${verlauf.offen_utxos} offen`);
    }
    const vl = saAbschnitt(t("tax.hard.c8a4f137db"), teile.join(" · "), {
      ausklappbar: false,
      leerText:
        "Nur Orientierung: Abflüsse oben brauchen Verlauf; " +
        "UTXOs kommen aus dem Bestand.",
    });
    liste.append(vl.details);
  }
  if (typeof wendeKopfFilterSteuerjahrAn === "function") {
    wendeKopfFilterSteuerjahrAn(
      typeof steuerKopfFilter === "function" ? steuerKopfFilter() : null,
    );
  }
}

/** TT.MM.JJJJ (Mittag, lokal) → Unix-Sekunden, sonst 0. */
function tsAusDeDatumMittag(text) {
  const d = parseDeDatum(text);
  return d ? Math.floor(d.getTime() / 1000) : 0;
}

/** TxID aus Filterfeld — Outpoint ``txid:vout`` → nur Tx-Teil. */
function saTxidAusFeld() {
  let tip = ($("#sa-txid")?.value || "").trim();
  if (!tip) return "";
  if (tip.toLowerCase().startsWith("utxo:")) tip = tip.slice(5).trim();
  const dop = tip.indexOf(":");
  if (dop > 0) {
    const rechts = tip.slice(dop + 1);
    if (/^\d+$/.test(rechts)) tip = tip.slice(0, dop);
  }
  return tip.trim();
}

/** Nur angekreuzte Zeilen (ohne Einzahl-Tx-Feld). */
function saAnkreuzAuswahl() {
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

function saAuswahl() {
  const { txids, utxos } = saAnkreuzAuswahl();
  // TxID im Filterfeld zählt mit, wenn nichts angekreuzt ist (Einzahl-Tx).
  if (!txids.length && !utxos.length) {
    const tip = saTxidAusFeld();
    if (tip) txids.push(tip);
  }
  return { txids, utxos };
}

function ladeSelbstanzeigeExport(art, auswahl = null) {
  const { txids, utxos } = auswahl && typeof auswahl === "object"
    ? {
        txids: Array.isArray(auswahl.txids) ? auswahl.txids : [],
        utxos: Array.isArray(auswahl.utxos) ? auswahl.utxos : [],
      }
    : saAuswahl();
  if (!txids.length && !utxos.length) {
    const kasten = $("#steuer-meldung");
    if (kasten) {
      kasten.className = "hinweis hinweis-warn";
      setzeText(
        kasten,
        "Bitte mindestens einen Abfluss oder UTXO ankreuzen — oder eine TxID oben eintragen.",
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
    `&utxos=${encodeURIComponent(utxos.join(","))}` +
    `&theme=${encodeURIComponent(guiThemeFuerBericht())}`;

  if (art === "csv") {
    const adresse =
      `/api/tax/selbstanzeige/${datei}?${query}&t=${encodeURIComponent(Token)}`;
    window.open(adresse, "_blank", "noopener");
    return;
  }

  // HTML: erst laden (Auth-Header), dann Blob-Tab — vermeidet leere Tabs
  // (Token/CSP/JSON-Fehler in window.open) und zeigt Fortschritt in der UI.
  const kasten = $("#steuer-meldung");
  if (kasten) {
    kasten.className = "hinweis hinweis-lauf";
    setzeText(kasten, "Report wird erzeugt…");
    kasten.hidden = false;
  }
  // User-Geste: leeren Tab sofort (Popup-Blocker), Inhalt nach Fetch.
  const fenster = window.open("about:blank", "_blank");
  if (fenster) {
    try {
      fenster.document.write(
        "<!DOCTYPE html><title>Report…</title><body style='font-family:system-ui;"
        + "padding:2rem'><p>Bericht Sat-Geschichte wird erzeugt…</p></body>",
      );
      fenster.document.close();
    } catch (_) { /* cross-origin edge */ }
  }

  (async () => {
    try {
      const antwort = await fetch(`/api/tax/selbstanzeige/${datei}?${query}`, {
        headers: { "X-Satsage-Token": Token },
        credentials: "same-origin",
      });
      const roh = await antwort.arrayBuffer();
      const typ = antwort.headers.get("content-type") || "";
      if (!antwort.ok) {
        let meldung = `HTTP ${antwort.status}`;
        try {
          const text = new TextDecoder().decode(roh);
          if (typ.includes("json")) {
            const koerper = JSON.parse(text);
            if (koerper.error) meldung = koerper.error;
          } else if (text) {
            const m = text.match(/<p>([^<]+)<\/p>/);
            if (m) meldung = m[1];
            else meldung = text.slice(0, 200);
          }
        } catch (_) { /* ignore */ }
        throw new Error(meldung);
      }
      const blob = new Blob([roh], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      if (fenster && !fenster.closed) {
        fenster.location.href = url;
      } else {
        window.open(url, "_blank", "noopener");
      }
      // Zusätzlich speichern
      const link = document.createElement("a");
      link.href = url;
      link.download = `satsage-selbstanzeige-${jahr}.html`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 120_000);
      if (kasten) {
        kasten.className = "hinweis hinweis-gut";
        setzeText(kasten, t("ui.hard.bd517311c4"));
      }
    } catch (fehler) {
      if (fenster && !fenster.closed) {
        try {
          fenster.document.open();
          fenster.document.write(
            `<!DOCTYPE html><meta charset=utf-8><title>Fehler</title>`
            + `<body style="font-family:system-ui;padding:2rem">`
            + `<h1>Report fehlgeschlagen</h1><p>${String(fehler.message || fehler)
              .replace(/</g, "&lt;")}</p></body>`,
          );
          fenster.document.close();
        } catch (_) { /* ignore */ }
      }
      if (kasten) {
        kasten.className = "hinweis hinweis-krit";
        setzeText(kasten, `Report: ${fehler.message}`);
        kasten.hidden = false;
      }
    }
  })();
}
