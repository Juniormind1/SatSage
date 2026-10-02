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
  // Seitenweise (ISSUES P2): Summen, Kennzahlen und Zeitstrahl über alles,
  // Zeilen nur im Fenster — die erste Anfrage bringt je Liste zwei Seiten.
  const filter = steuerFilterParameter();
  const p = new URLSearchParams(filter);
  p.set("seite", "1");
  p.set("limit", String(2 * pagerGroesse("steuerjahr")));
  p.set("limit_abgaenge", String(2 * pagerGroesse("abgaenge")));
  p.set("lang", uiSprache());

  try {
    const daten = await api(`/tax${abfrage}&${p}`);
    daten._abfrage = abfrage;
    daten._q = filter.toString();
    Zustand.steuer = daten;
    zeichneSteuerjahr(daten);
  } catch (fehler) {
    const kasten = $("#steuer-meldung");
    kasten.className = "hinweis hinweis-krit";
    setzeText(kasten, t("tax.hard.f8c6a72307", { msg: fehler.message }));
    kasten.hidden = false;
  }
}

/** Kopf-Filter für die Steuerzeilen (nur in der Steuerjahr-Ansicht). */
function steuerFilterParameter() {
  if (Zustand.ansicht !== "steuerjahr" || typeof kopfFilterParameter !== "function") {
    return new URLSearchParams();
  }
  return kopfFilterParameter();
}

function steuerSeitenParameter(teil, offset, limit, filter) {
  const p = new URLSearchParams(filter || "");
  p.set("seite", "1");
  p.set("teil", teil);
  p.set("offset", String(offset));
  p.set("limit", String(limit));
  p.set("limit_abgaenge", String(limit));
  p.set("lang", uiSprache());
  return p.toString();
}

/** Betrag mit Fiat nur bei einheitlichem Bewertungstag (Server: gemeinsam_ts). */
function steuerSatsGemeinsam(sats, ts) {
  return ts ? formatSats(sats, { atTs: ts }) : formatSatsBasis(sats);
}

/** Neuer Kopf-Filter: nur die Zeilenfenster neu holen, Rest bleibt stehen. */
async function ladeSteuerSeitenNeu() {
  const daten = Zustand.steuer;
  if (!daten || !daten.seitenweise) return;
  const filter = steuerFilterParameter();
  const q = filter.toString();
  const lauf = (Zustand.steuerZeilenLauf || 0) + 1;
  Zustand.steuerZeilenLauf = lauf;
  const p = new URLSearchParams(filter);
  p.set("seite", "1");
  p.set("teil", "zeilen");
  p.set("limit", String(2 * pagerGroesse("steuerjahr")));
  p.set("limit_abgaenge", String(2 * pagerGroesse("abgaenge")));
  p.set("lang", uiSprache());
  const neu = await api(`/tax${daten._abfrage}&${p}`);
  if (lauf !== Zustand.steuerZeilenLauf || Zustand.steuer !== daten) return;
  daten.steuer_gruppen = neu.steuer_gruppen;
  daten.abgaenge_fenster = neu.abgaenge_fenster;
  daten._q = q;
  zeichneAbgaenge(daten);
  zeichneSteuerUtxoGruppen(daten);
  if (typeof wendeKopfFilterSteuerjahrAn === "function") {
    wendeKopfFilterSteuerjahrAn(steuerKopfFilter());
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

/** Scorecards oben im Steuerjahr. id bleibt stabil, solange die Farbe steht. */
function steuerScorecardModelle(daten) {
  const k = daten.kennzahlen || {};
  const alleE = daten.eintraege || [];
  const erfuelltE = alleE.filter((e) => e.erfuellt);
  const offenE = alleE.filter((e) => !e.erfuellt);
  const ungeprueftE = alleE.filter((e) => !e.geprueft);
  // Seitenweise liegt nur ein Fenster vor: Der Server nennt den gemeinsamen
  // Bewertungstag je Menge (sonst null → kein Fiat, wie bisher).
  const kts = daten.seitenweise ? (daten.kennzahlen_ts || {}) : null;
  const fiatE = (sats, liste, name) => (kts
    ? steuerSatsGemeinsam(sats, kts[name])
    : formatSatsGemeinsam(sats, liste));

  const karten = [
    {
      id: "gesamt",
      titel: t("tax.hard.ee18fac200"),
      wert: fiatE(k.gesamt_sats, alleE, "gesamt"),
      zusatz: `${k.gesamt_count} UTXOs`,
      art: "",
      klaeren: false,
    },
    {
      id: "erfuellt",
      titel: t("tax.hard.91a2ea86bd"),
      wert: fiatE(k.erfuellt_sats, erfuelltE, "erfuellt"),
      zusatz: `${k.erfuellt_count} UTXOs`,
      art: "gut",
      klaeren: false,
    },
    {
      id: "offen",
      titel: t("tax.hard.innerhalbHaltefrist"),
      wert: fiatE(k.offen_sats, offenE, "offen"),
      zusatz: k.naechste_frist
        ? t("tax.hard.ed098d09aa", { naechste_frist: k.naechste_frist })
        : `${k.offen_count} UTXOs`,
      art: "warn",
      klaeren: true,
    },
  ];
  if (k.ungeprueft_count > 0) {
    karten.push({
      id: "ungeprueft",
      titel: "Ohne Herkunftsanalyse",
      wert: fiatE(k.ungeprueft_sats, ungeprueftE, "ungeprueft"),
      zusatz: `${k.ungeprueft_count} UTXOs — Frist evtl. länger`,
      art: "ungeprueft",
      klaeren: true,
    });
  }
  if (k.ohne_datum > 0) {
    karten.push({
      id: "ohne_datum",
      titel: t("tax.hard.f99058be55"),
      wert: String(k.ohne_datum),
      zusatz: t("tax.hard.3199eeb8e0"),
      art: "",
      klaeren: false,
    });
  }
  return karten;
}

function baueSteuerScorecard(karte) {
  const zelle = document.createElement("div");
  zelle.className = "kennzahl";
  zelle.dataset.score = karte.id;
  const titelEl = document.createElement("span");
  titelEl.className = "kennzahl-titel";
  titelEl.textContent = karte.titel;
  const w = document.createElement("span");
  w.className = `kennzahl-wert ${karte.art}`.trim();
  const zahl = document.createElement("span");
  zahl.className = "kennzahl-zahl";
  zahl.textContent = karte.wert;
  w.append(zahl);
  const z = document.createElement("span");
  z.className = "kennzahl-zusatz";
  z.textContent = karte.zusatz;
  if (karte.art === "ungeprueft") z.dataset.klaerZaehler = "grau";
  zelle.append(titelEl, w, z);
  if (!karte.klaeren) return zelle;
  const knopf = document.createElement("button");
  knopf.type = "button";
  // Unterschiedliche IDs je Scorecard, damit wir gezielt nur gelbe oder nur graue tracen können
  knopf.id = karte.art === "warn" ? "herkunft-gelb" : "herkunft-grau";
  knopf.className = "knopf knopf-klein kennzahl-aktion";
  knopf.textContent = t("tax.originAll");
  knopf.setAttribute("data-i18n", "tax.originAll");
  if (karte.art === "warn") {
    // Gelb: voll bis extern/Coinbase — erst dann grün oder bestätigt gelb.
    knopf.title = t("tax.yellowClarifyTitle") !== "tax.yellowClarifyTitle"
      ? t("tax.yellowClarifyTitle")
      : t("tax.hard.4f776c0011");
    knopf.setAttribute("data-i18n-title", "tax.yellowClarifyTitle");
    knopf.addEventListener("click", () => {
      herkunftGelbUtxos().catch((fehler) => {
        Zustand.herkunftAlleLaeuft = false;
        if (typeof loeseEmpfangScanPuls === "function") loeseEmpfangScanPuls();
        const kasten = $("#steuer-meldung");
        if (!kasten) return;
        kasten.className = "hinweis hinweis-krit";
        setzeText(kasten, fehler.message || String(fehler));
        kasten.hidden = false;
      });
    });
  } else {
    // Grauer Scorecard-Knopf: alle noch nie analysierten UTXOs
    knopf.title = t("tax.hard.a430621437");
    knopf.setAttribute("data-i18n-title", "");
    knopf.addEventListener("click", () => {
      Promise.resolve(herkunftGrauUtxos()).catch((fehler) => {
        Zustand.herkunftAlleLaeuft = false;
        if (typeof loeseEmpfangScanPuls === "function") loeseEmpfangScanPuls();
        const kasten = $("#steuer-meldung");
        if (!kasten) return;
        kasten.className = "hinweis hinweis-krit";
        setzeText(kasten, fehler.message || String(fehler));
        kasten.hidden = false;
      });
    });
  }
  w.append(knopf);
  return zelle;
}

/**
 * Scorecards neu zeichnen.
 * Kommt eine Farbe dazu oder fällt sie weg, werden alle Karten neu gebaut.
 * Sonst bleiben die Karten stehen und nur die geänderten Zahlen werden ersetzt.
 */
function zeichneSteuerScorecards(daten) {
  const kasten = $("#steuer-kennzahlen");
  if (!kasten || !daten) return;
  const karten = steuerScorecardModelle(daten);
  const neu = karten.map((karte) => karte.id).join("\0");
  const alt = [...kasten.children]
    .map((el) => (el.dataset && el.dataset.score) || "")
    .join("\0");
  if (neu !== alt) {
    kasten.replaceChildren(...karten.map(baueSteuerScorecard));
    return;
  }
  for (const karte of karten) {
    const zelle = kasten.querySelector(`[data-score="${karte.id}"]`);
    if (!zelle) continue;
    const zahl = zelle.querySelector(".kennzahl-zahl");
    if (zahl && zahl.textContent !== karte.wert) zahl.textContent = karte.wert;
    const zusatz = zelle.querySelector(".kennzahl-zusatz");
    if (zusatz && zusatz.textContent !== karte.zusatz) {
      zusatz.textContent = karte.zusatz;
      if (karte.id === "ungeprueft") delete zusatz.dataset.klaerStart;
    }
  }
}

function zeichneSteuerjahr(daten) {
  fuelleJahresauswahl(daten.verfuegbare_jahre || [], daten.jahr);
  fuelleHaltefristAuswahl(
    $("#frist-wahl"),
    daten.haltefrist_jahre,
    steuerEinstellungen().haltefrist_jahre_auswahl,
  );
  zeichneAbgaenge(daten);

  // Serverstand ist maßgeblich. Scan-Punkte, die der Plot noch nicht hat,
  // zählt zeichneScanPunkte danach erneut auf diesen Stand drauf.
  ScanPunktStand.gezahlt.clear();
  zeichneSteuerScorecards(daten);

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
 *
 * *fenster* (seitenweise): Zeilen kommen seitenweise vom Server, Anzahl und
 * Summe im Kopf gelten trotzdem für die ganze Gruppe.
 */
function zeichneSteuerUtxoGruppe(titel, eintraege, { art = "", daten, fenster = null }) {
  const tbody = document.createElement("tbody");
  tbody.className = `steuer-gruppe${art ? ` ${art}` : ""}`;

  const sats = fenster
    ? Number(fenster.voll_sats) || 0
    : eintraege.reduce((summe, e) => summe + (Number(e.value_sats) || 0), 0);
  const anzahl = fenster ? Number(fenster.voll_count) || 0 : eintraege.length;
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
  meta.textContent = `${anzahlText} · ${fenster
    ? steuerSatsGemeinsam(sats, fenster.gemeinsam_ts)
    : formatSatsGemeinsam(sats, eintraege)}`;
  meta.dataset.voll = meta.textContent;

  kopf.append(klapp, name, meta);
  kopfZelle.append(kopf);
  kopfZeile.append(kopfZelle);

  let datenZeilen = [];
  let auf = false;
  let pagerZeile = null;

  const setzeGruppe = (neuAuf) => {
    auf = neuAuf;
    for (const z of datenZeilen) {
      z.hidden = z.dataset.filterAus === "1" || !auf;
    }
    if (pagerZeile) pagerZeile.hidden = !auf;
    klapp.textContent = auf ? "▾" : "▸";
    kopf.setAttribute("aria-expanded", String(auf));
  };
  tbody._setzeSteuerGruppe = setzeGruppe;

  const setzeZeilen = (liste) => {
    for (const z of datenZeilen) z.remove();
    datenZeilen = liste.map((eintrag) =>
      zeichneSteuerUtxoZeile(eintrag, daten, { versteckt: !auf })
    );
    if (pagerZeile) pagerZeile.before(...datenZeilen);
    else tbody.append(...datenZeilen);
  };

  tbody.append(kopfZeile);
  if (!fenster) {
    setzeZeilen(eintraege);
  } else {
    tbody.dataset.seitenweise = "1";
    pagerZeile = document.createElement("tr");
    pagerZeile.className = "steuer-pager-zeile";
    const pagerZelle = document.createElement("td");
    pagerZelle.colSpan = 7;
    pagerZeile.append(pagerZelle);
    tbody.append(pagerZeile);
    const teil = art;
    const auszug = (antwort) => {
      const f = (antwort.steuer_gruppen || {})[teil] || {};
      return { items: f.items || [], total: Number(f.total) || 0, sats: Number(f.sats) || 0 };
    };
    const neueQuelle = (vorab) => neueSeitenQuelle({
      groesse: pagerGroesse("steuerjahr"),
      laden: (o, l) => api(`/tax${daten._abfrage}&${steuerSeitenParameter(teil, o, l, daten._q)}`),
      auszug,
      vorab,
    });
    let quelle = neueQuelle({ steuer_gruppen: { [teil]: fenster } });
    const zeigeSeite = (seite, q) => {
      setzeZeilen(seite.items);
      tbody._fensterTreffer = { q: daten._q, total: seite.total, sats: auszug(seite.antwort).sats };
      pagerZelle.replaceChildren(zeichnePager({
        total: seite.total,
        offset: seite.offset,
        groesse: q.groesse,
        ansicht: "steuerjahr",
        onSeite: (o) => {
          q.seite(o).then((s2) => { if (q === quelle) zeigeSeite(s2, q); }).catch(() => {});
        },
        onGroesse: () => {
          quelle = neueQuelle(null);
          const q2 = quelle;
          q2.seite(0).then((s2) => { if (q2 === quelle) zeigeSeite(s2, q2); }).catch(() => {});
        },
      }));
      setzeGruppe(auf);
    };
    // Erste Seite sofort aus der Gesamtantwort (kein Warten auf einen Tick).
    const g = quelle.groesse;
    zeigeSeite({
      antwort: { steuer_gruppen: { [teil]: fenster } },
      items: (fenster.items || []).slice(0, g),
      total: Number(fenster.total) || 0,
      offset: 0,
    }, quelle);
  }
  setzeGruppe(false);

  kopf.addEventListener("click", () => {
    if (fenster) {
      setzeGruppe(!auf);
      return;
    }
    const istZu = datenZeilen.every((z) => z.hidden);
    setzeGruppe(istZu);
  });

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

  const fenster = daten.seitenweise ? (daten.steuer_gruppen || {}) : null;
  const liste = daten.eintraege || [];
  const leer = fenster
    ? !(Number(fenster.erfuellt?.voll_count) || Number(fenster.offen?.voll_count))
    : liste.length === 0;
  if (leer) {
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

  // Reihenfolge wie Scorecard: außerhalb (grün), dann innerhalb (gelb).
  if (fenster) {
    for (const [teil, titel] of [["erfuellt", "tax.haltefristOut"], ["offen", "tax.haltefristIn"]]) {
      const f = fenster[teil];
      if (!f || !Number(f.voll_count)) continue;
      tabelle.append(zeichneSteuerUtxoGruppe(t(titel), [], { art: teil, daten, fenster: f }));
    }
    return;
  }

  const erfuellt = liste.filter((e) => e.erfuellt);
  const offen = liste.filter((e) => !e.erfuellt);

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
  // Y: 0 = Betrag 0, 100 = größter UTXO. y0 darf über 0 steigen,
  // unter 0 nicht. y1 höchstens bis zum höchsten gezeichneten Punkt
  // (UTXO-Plot oder, wenn offen, Herkunftsnetz).
  y0: 0,
  y1: 100,
  hoehe: 220,
  gebunden: false,
};

const ZEITSTRAHL_MIN_SPAN = 2;
const ZEITSTRAHL_MIN_HOEHE = 140;
const ZEITSTRAHL_MAX_HOEHE = 720;
const ZEITSTRAHL_HOEHE_KEY = "satsage-zeitstrahl-hoehe";

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

function formatTickTag(d) {
  const dd = String(d.getDate()).padStart(2, "0");
  return `${dd}.${formatTickMonatJahr(d)}`;
}

/**
 * UTXO-Discover: neue Outputs grau einzeichnen, sobald der Walk sie kennt.
 * X = Output-Datum. Punkte, die der Plot schon hat, bleiben unangetastet.
 */
const ScanPunktStand = {
  keys: new Set(),
  offen: new Map(),
  // Schlüssel, die schon in den Scorecards stecken. Zoom zeichnet die
  // Punkte neu, ohne die Summen ein zweites Mal zu erhöhen.
  gezahlt: new Set(),
};

/** Neuer grauer Scan-Punkt: Bestand und „ohne Herkunft“ um diesen Betrag heben. */
function steuerScanPunktInKennzahlen(eintrag) {
  const daten = Zustand.steuer;
  const k = daten && daten.kennzahlen;
  const key = String((eintrag && eintrag.key) || "");
  if (!k || !key || ScanPunktStand.gezahlt.has(key)) return false;
  ScanPunktStand.gezahlt.add(key);
  const sats = Number(eintrag.value_sats) || 0;
  k.gesamt_count = (Number(k.gesamt_count) || 0) + 1;
  k.gesamt_sats = (Number(k.gesamt_sats) || 0) + sats;
  k.ungeprueft_count = (Number(k.ungeprueft_count) || 0) + 1;
  k.ungeprueft_sats = (Number(k.ungeprueft_sats) || 0) + sats;
  if (Array.isArray(daten.grau_keys) && !daten.grau_keys.includes(key)) {
    daten.grau_keys.push(key);
  }
  return true;
}

function scanPunktGroesse(sats, maxSats) {
  const max = Number(maxSats) || Number(sats) || 1;
  const anteil = Number(sats) / max;
  if (anteil >= 0.1) return "gross";
  if (anteil >= 0.01) return "mittel";
  return "klein";
}

function zeichneScanPunkte(liste) {
  if (Zustand.ansicht !== "steuerjahr") return 0;
  const spur = $("#achse-spur");
  const strahl = ZeitstrahlAnsicht.daten && ZeitstrahlAnsicht.daten.zeitstrahl;
  if (!spur || !strahl || !strahl.von || !strahl.bis) return 0;
  const von = parseDeDatum(strahl.von);
  const bis = parseDeDatum(strahl.bis);
  if (!von || !bis) return 0;
  const gesamtMs = bis.getTime() - von.getTime();
  if (!(gesamtMs > 0)) return 0;
  const maxSats = Number(strahl.max_sats) || 1;
  let dazu = 0;
  for (const eintrag of liste || []) {
    const key = String(eintrag.key || "");
    const ts = Number(eintrag.time_ts || 0);
    const sats = Number(eintrag.value_sats || 0);
    if (!key || !(ts > 0) || !(sats >= 0)) continue;
    if (spur.querySelector(
      `.achse-punkt[data-key="${CSS.escape(key)}"]:not([data-scan-neu])`,
    )) {
      ScanPunktStand.keys.add(key);
      ScanPunktStand.offen.delete(key);
      continue;
    }
    ScanPunktStand.offen.set(key, eintrag);
    if (spur.querySelector(`.achse-punkt[data-key="${CSS.escape(key)}"]`)) {
      continue;
    }
    const wann = new Date(ts * 1000);
    if (Number.isNaN(wann.getTime())) continue;
    const pos = Math.max(
      0,
      Math.min(100, (wann.getTime() - von.getTime()) / gesamtMs * 100),
    );
    const sicht = zeitstrahlSichtPos(pos);
    if (sicht < -5 || sicht > 105) continue;
    const yRoh = Math.log1p(sats) / Math.log1p(maxSats) * 100;
    const y = zeitstrahlSichtY(Math.max(0, Math.min(100, yRoh)));
    const punkt = document.createElement("span");
    punkt.className = `achse-punkt ${scanPunktGroesse(sats, maxSats)} ungeprueft klickbar`;
    punkt.dataset.key = key;
    punkt.dataset.scanNeu = "1";
    if (eintrag.wallet) punkt.dataset.wallet = eintrag.wallet;
    if (eintrag.wallet_id) punkt.dataset.walletId = eintrag.wallet_id;
    punkt.dataset.valueSats = String(sats);
    punkt.dataset.eventTs = String(ts);
    punkt.style.left = `${sicht}%`;
    punkt.style.bottom = `${y}%`;
    const dd = String(wann.getDate()).padStart(2, "0");
    const mm = String(wann.getMonth() + 1).padStart(2, "0");
    const datum = `${dd}.${mm}.${wann.getFullYear()}`;
    const tip = document.createElement("span");
    tip.className = sicht > 70 ? "achse-punkt-tip links" : "achse-punkt-tip";
    const lage = t("tax.legendUnchecked") !== "tax.legendUnchecked"
      ? t("tax.legendUnchecked")
      : "innerhalb Frist, ohne Herkunft";
    tip.textContent = [
      datum,
      typeof formatZeitstrahlBetrag === "function" ? formatZeitstrahlBetrag(sats) : "",
      `${eintrag.wallet || "unbekannt"} · ${lage}`,
    ].filter(Boolean).join("\n");
    punkt.append(tip);
    spur.append(punkt);
    ScanPunktStand.keys.add(key);
    dazu += 1;
    // Pro neuem Punkt. Fehlt die graue Karte, baut der erste Punkt alle
    // Scorecards neu. Jeder weitere ändert nur die Zahlen.
    if (steuerScanPunktInKennzahlen(eintrag)) {
      zeichneSteuerScorecards(Zustand.steuer);
    }
  }
  return dazu;
}

/** „?“ am laufenden Punkt, „!“ kurz nach seinem Abschluss. Überlebt den Redraw. */
const TracePunktMarke = {
  frage: "",
  ausrufe: new Map(),
};

function tracePunktImPlot(key) {
  const spur = $("#achse-spur");
  if (!spur || !key) return null;
  return spur.querySelector(
    `.achse-punkt[data-key="${CSS.escape(String(key))}"]`,
  );
}

function setzeTraceMarke(key, art) {
  const punkt = tracePunktImPlot(key);
  if (!punkt || punkt.classList.contains("geister")) return;
  punkt.classList.remove("trace-frage", "trace-fertig");
  if (art === "frage") punkt.classList.add("trace-frage");
  if (art === "fertig") punkt.classList.add("trace-fertig");
}

/** Dieses UTXO wird gerade getracet. Der vorige Punkt wechselt auf „!“. */
function traceFrageAn(key) {
  const neu = String(key || "");
  if (!neu) return;
  if (TracePunktMarke.frage && TracePunktMarke.frage !== neu) {
    traceAusrufeAn(TracePunktMarke.frage);
  }
  const timer = TracePunktMarke.ausrufe.get(neu);
  if (timer) {
    clearTimeout(timer);
    TracePunktMarke.ausrufe.delete(neu);
  }
  TracePunktMarke.frage = neu;
  setzeTraceMarke(neu, "frage");
}

/** Trace dieses UTXO ist durch: „!“ bleibt kurz, dann weg. */
function traceAusrufeAn(key) {
  const ziel = String(key || "");
  if (!ziel) return;
  if (TracePunktMarke.frage === ziel) TracePunktMarke.frage = "";
  setzeTraceMarke(ziel, "fertig");
  const alt = TracePunktMarke.ausrufe.get(ziel);
  if (alt) clearTimeout(alt);
  TracePunktMarke.ausrufe.set(ziel, setTimeout(() => {
    TracePunktMarke.ausrufe.delete(ziel);
    const punkt = tracePunktImPlot(ziel);
    if (punkt) punkt.classList.remove("trace-fertig", "trace-frage");
  }, 1600));
}

function traceFrageAus() {
  if (TracePunktMarke.frage) traceAusrufeAn(TracePunktMarke.frage);
}

function traceMarkenNachZeichnen() {
  if (TracePunktMarke.frage) setzeTraceMarke(TracePunktMarke.frage, "frage");
  for (const key of TracePunktMarke.ausrufe.keys()) {
    setzeTraceMarke(key, "fertig");
  }
}

/**
 * Laufender Trace: Punkt nur verschieben, wenn das Datum schon feststeht.
 *
 * Defensiv wandert X nur nach rechts (jünger). Fest ist Gelb, sobald der
 * jüngste bekannte externe Zufluss innerhalb der Frist liegt. Offensiv
 * wandert X nur nach links; fest ist dann Grün. Alles andere wartet auf
 * den fertigen Trace — ein späterer Hop könnte die Farbe umkehren.
 */
function wendeLivePunktAn(live) {
  if (!live || !live.key || Zustand.ansicht !== "steuerjahr") return false;
  const ts = Number(live.time_ts || 0);
  const altTs = Number(live.oldest_time_ts || 0);
  if (!(ts > 0)) return false;
  const spur = $("#achse-spur");
  if (!spur) return false;
  const punkt = spur.querySelector(
    `.achse-punkt[data-key="${CSS.escape(String(live.key))}"]`,
  );
  if (!punkt || punkt.classList.contains("geister")) return false;
  const strahl = ZeitstrahlAnsicht.daten && ZeitstrahlAnsicht.daten.zeitstrahl;
  if (!strahl || !strahl.von || !strahl.bis) return false;
  const von = parseDeDatum(strahl.von);
  const bis = parseDeDatum(strahl.bis);
  if (!von || !bis) return false;
  const gesamtMs = bis.getTime() - von.getTime();
  if (!(gesamtMs > 0)) return false;

  const anschaffung = (steuerEinstellungen().anschaffung || "juengste") === "aelteste"
    ? "aelteste"
    : "juengste";
  const wirksamTs = anschaffung === "aelteste" ? (altTs || ts) : ts;
  const fristJahre = Number(
    ($("#frist-wahl") && $("#frist-wahl").value)
    || steuerEinstellungen().haltefrist_jahre
    || 1,
  );
  const jahr = Number(($("#jahr-wahl") && $("#jahr-wahl").value) || 0);
  const bezug = jahr
    ? new Date(jahr, 11, 31, 23, 59, 59)
    : new Date();
  const stichtagIso = steuerEinstellungen().stichtag_iso || steuerEinstellungen().stichtag || "";
  const stichtag = stichtagIso ? new Date(`${stichtagIso}T12:00:00`) : null;
  const anschaffungDate = new Date(wirksamTs * 1000);
  if (Number.isNaN(anschaffungDate.getTime())) return false;

  let erfuellt = false;
  let neuvermoegen = false;
  if (stichtag && !Number.isNaN(stichtag.getTime())
      && anschaffungDate.getTime() > stichtag.getTime()) {
    neuvermoegen = true;
  } else if (!(fristJahre > 0)) {
    erfuellt = true;
  } else {
    const fristEnde = new Date(anschaffungDate.getTime());
    fristEnde.setFullYear(fristEnde.getFullYear() + fristJahre);
    erfuellt = fristEnde.getTime() <= bezug.getTime();
  }
  // Nur die Richtung, die ein späterer Hop nicht mehr umkehren kann.
  const sicherGelb = anschaffung === "juengste" && !erfuellt;
  const sicherGruen = anschaffung === "aelteste" && erfuellt;
  if (!sicherGelb && !sicherGruen) return false;

  const pos = Math.max(
    0,
    Math.min(100, (anschaffungDate.getTime() - von.getTime()) / gesamtMs * 100),
  );
  const bisher = Number(punkt.dataset.livePos);
  if (Number.isFinite(bisher)) {
    const rueckwaerts = anschaffung === "juengste" ? pos < bisher - 0.05 : pos > bisher + 0.05;
    if (rueckwaerts) return false;
  }
  punkt.dataset.livePos = String(pos);
  punkt.style.left = `${zeitstrahlSichtPos(pos)}%`;
  punkt.classList.remove("ungeprueft", "offen", "erfuellt");
  punkt.classList.add(sicherGruen ? "erfuellt" : "offen");
  punkt.classList.add("herkunft-offen-marke");
  const tip = punkt.querySelector(".achse-punkt-tip");
  if (tip) {
    const dd = String(anschaffungDate.getDate()).padStart(2, "0");
    const mm = String(anschaffungDate.getMonth() + 1).padStart(2, "0");
    const datum = `${dd}.${mm}.${anschaffungDate.getFullYear()}`;
    const lage = sicherGruen
      ? (t("tax.haltefristOut") !== "tax.haltefristOut" ? t("tax.haltefristOut") : "außerhalb Haltefrist")
      : (t("tax.haltefristIn") !== "tax.haltefristIn" ? t("tax.haltefristIn") : "innerhalb Haltefrist");
    const wallet = punkt.dataset.wallet || "unbekannt";
    const betrag = punkt.dataset.valueSats
      ? formatZeitstrahlBetrag(Number(punkt.dataset.valueSats))
      : "";
    tip.textContent = [datum, betrag, `${wallet} · ${lage}`, t("tax.plotIncomplete")]
      .filter(Boolean)
      .join("\n");
  }
  return true;
}

/** Daten-% → sichtbare left-% im aktuellen X-Fenster. */
function zeitstrahlSichtPos(pos) {
  const span = ZeitstrahlAnsicht.x1 - ZeitstrahlAnsicht.x0;
  if (span <= 0) return 50;
  return ((pos - ZeitstrahlAnsicht.x0) / span) * 100;
}

/**
 * Linke Grenze der Zeitachse in Daten-%.
 * 0 = ältester UTXO minus sechs Monate. Liegt ein Herkunfts-Input davor,
 * geht die Achse bis zu dessen Datum, damit er nicht auf dem Nullpunkt stapelt.
 */
function zeitstrahlXMin() {
  let min = 0;
  const netz = typeof Herkunftsnetz !== "undefined" ? Herkunftsnetz : null;
  const daten = netz && netz.daten;
  if (!daten) return min;
  const werte = [daten.fokus_pos];
  for (const v of daten.vorfahren || []) werte.push(v && v.pos_output);
  for (const pos of werte) {
    if (pos === null || pos === undefined || pos === "") continue;
    const n = Number(pos);
    if (Number.isFinite(n) && n < min) min = n;
  }
  return min;
}

/** Oberkante in Daten-%: 100, oder höher wenn ein Netz-Ring darüber liegt. */
function zeitstrahlYMax() {
  let max = 100;
  const netz = typeof Herkunftsnetz !== "undefined" ? Herkunftsnetz : null;
  const daten = netz && netz.daten;
  if (!daten) return max;
  const werte = [daten.fokus_y];
  for (const v of daten.vorfahren || []) werte.push(v && v.y);
  for (const y of werte) {
    const n = Number(y);
    if (n > max) max = n;
  }
  return max;
}

/** Daten-Y-% (0 = 0 sats, 100 = max) → sichtbare bottom-% im Y-Fenster. */
function zeitstrahlSichtY(y) {
  const span = ZeitstrahlAnsicht.y1 - ZeitstrahlAnsicht.y0;
  if (span <= 0) return 0;
  return ((Number(y) - ZeitstrahlAnsicht.y0) / span) * 100;
}

function zeitstrahlFensterBegrenzen() {
  let { x0, x1 } = ZeitstrahlAnsicht;
  const xMin = zeitstrahlXMin();
  const xSpanne = 100 - xMin;
  let span = x1 - x0;
  if (span < ZEITSTRAHL_MIN_SPAN) {
    const mitte = (x0 + x1) / 2;
    x0 = mitte - ZEITSTRAHL_MIN_SPAN / 2;
    x1 = mitte + ZEITSTRAHL_MIN_SPAN / 2;
    span = ZEITSTRAHL_MIN_SPAN;
  }
  if (span > xSpanne) {
    x0 = xMin;
    x1 = 100;
  } else {
    if (x0 < xMin) {
      x1 += xMin - x0;
      x0 = xMin;
    }
    if (x1 > 100) {
      x0 -= x1 - 100;
      x1 = 100;
    }
    x0 = Math.max(xMin, x0);
    x1 = Math.min(100, x1);
  }
  ZeitstrahlAnsicht.x0 = x0;
  ZeitstrahlAnsicht.x1 = x1;

  // Unterkante mindestens 0, Oberkante höchstens beim höchsten Punkt.
  const yDeckel = zeitstrahlYMax();
  let y0 = ZeitstrahlAnsicht.y0;
  let y1 = ZeitstrahlAnsicht.y1;
  let ySpan = y1 - y0;
  if (!(ySpan > 0)) {
    y0 = 0;
    y1 = yDeckel;
    ySpan = yDeckel;
  }
  if (ySpan < ZEITSTRAHL_MIN_SPAN) {
    const mitte = (y0 + y1) / 2;
    y0 = mitte - ZEITSTRAHL_MIN_SPAN / 2;
    y1 = mitte + ZEITSTRAHL_MIN_SPAN / 2;
    ySpan = ZEITSTRAHL_MIN_SPAN;
  }
  if (ySpan > yDeckel) {
    y0 = 0;
    y1 = yDeckel;
  } else {
    if (y0 < 0) {
      y1 -= y0;
      y0 = 0;
    }
    if (y1 > yDeckel) {
      y0 -= y1 - yDeckel;
      y1 = yDeckel;
    }
    y0 = Math.max(0, y0);
    y1 = Math.min(yDeckel, y1);
  }
  ZeitstrahlAnsicht.y0 = y0;
  ZeitstrahlAnsicht.y1 = y1;
}

/**
 * Zoom auf Zeit- und Betragsachse. Anker: Mausposition im Viewport 0..100.
 * Y zoomt am senkrechten Mauszeiger. Die Unterkante bleibt mindestens bei 0.
 */
function zeitstrahlZoom(faktor, ankerXPct, ankerYPct) {
  zeitstrahlFensterBegrenzen();
  const { x0, x1, y0, y1 } = ZeitstrahlAnsicht;
  const span = x1 - x0;
  const anker = x0 + (ankerXPct / 100) * span;
  const xSpanne = 100 - zeitstrahlXMin();
  const neu = Math.min(xSpanne, Math.max(ZEITSTRAHL_MIN_SPAN, span * faktor));
  const linksAnteil = span > 0 ? (anker - x0) / span : 0.5;
  ZeitstrahlAnsicht.x0 = anker - linksAnteil * neu;
  ZeitstrahlAnsicht.x1 = ZeitstrahlAnsicht.x0 + neu;

  const ySpan = y1 - y0;
  const yAnker = y0 + (Math.max(0, Math.min(100, ankerYPct)) / 100) * ySpan;
  const yNeu = Math.max(ZEITSTRAHL_MIN_SPAN, ySpan * faktor);
  const untenAnteil = ySpan > 0 ? (yAnker - y0) / ySpan : 0;
  ZeitstrahlAnsicht.y0 = yAnker - untenAnteil * yNeu;
  ZeitstrahlAnsicht.y1 = ZeitstrahlAnsicht.y0 + yNeu;
  zeitstrahlFensterBegrenzen();
}

function zeitstrahlPan(deltaXPct, deltaYPct) {
  const span = ZeitstrahlAnsicht.x1 - ZeitstrahlAnsicht.x0;
  const shift = (deltaXPct / 100) * span;
  ZeitstrahlAnsicht.x0 -= shift;
  ZeitstrahlAnsicht.x1 -= shift;
  const ySpan = ZeitstrahlAnsicht.y1 - ZeitstrahlAnsicht.y0;
  const yShift = ((deltaYPct || 0) / 100) * ySpan;
  ZeitstrahlAnsicht.y0 += yShift;
  ZeitstrahlAnsicht.y1 += yShift;
  zeitstrahlFensterBegrenzen();
}

const ZEITSTRAHL_TICK_TAG = 86_400_000;
const ZEITSTRAHL_TICK_STUFEN = [
  { ms: ZEITSTRAHL_TICK_TAG, art: "tag" },
  { ms: 7 * ZEITSTRAHL_TICK_TAG, art: "tag" },
  { ms: 30 * ZEITSTRAHL_TICK_TAG, art: "monat" },
  { ms: 90 * ZEITSTRAHL_TICK_TAG, art: "monat" },
  { ms: 365 * ZEITSTRAHL_TICK_TAG, art: "jahr" },
  { ms: 2 * 365 * ZEITSTRAHL_TICK_TAG, art: "jahr" },
  { ms: 5 * 365 * ZEITSTRAHL_TICK_TAG, art: "jahr" },
];

/** Kleinste Stufe, bei der die Labels noch auseinanderliegen. */
function zeitstrahlTickStufe(sichtMs, breitePx) {
  const ziel = Math.max(72, Math.min(140, (Number(breitePx) || 640) / 6));
  const n = Math.max(2, Math.floor((Number(breitePx) || 640) / ziel));
  const gewuenscht = Math.max(ZEITSTRAHL_TICK_TAG, sichtMs / n);
  let stufe = ZEITSTRAHL_TICK_STUFEN[ZEITSTRAHL_TICK_STUFEN.length - 1];
  for (const kandidat of ZEITSTRAHL_TICK_STUFEN) {
    if (kandidat.ms >= gewuenscht) {
      stufe = kandidat;
      break;
    }
  }
  return stufe;
}

function zeitstrahlTickText(datum, art) {
  if (art === "tag") return formatTickTag(datum);
  if (art === "jahr") return String(datum.getFullYear());
  return formatTickMonatJahr(datum);
}

/**
 * Tick-Labels für das sichtbare X-Fenster.
 * Weit herausgezoomt: Jahre. Reinzoomen verdichtet bis auf einzelne Tage,
 * sobald der Platz zwischen den Labels das hergibt.
 */
function zeitstrahlTicksImFenster(strahl, breitePx) {
  const von = parseDeDatum(strahl.von);
  const bis = parseDeDatum(strahl.bis);
  if (!von || !bis) {
    return (strahl.ticks || []).map((tick) => ({ label: tick.label, left: null }));
  }
  const gesamtMs = bis.getTime() - von.getTime();
  if (!(gesamtMs > 0)) {
    return [{ label: formatTickMonatJahr(von), left: 0 }];
  }
  const { x0, x1 } = ZeitstrahlAnsicht;
  const span = x1 - x0;
  const sichtMs = gesamtMs * span / 100;
  const stufe = zeitstrahlTickStufe(sichtMs, breitePx);
  const fensterStart = von.getTime() + (gesamtMs * x0) / 100;
  const fensterEnde = von.getTime() + (gesamtMs * x1) / 100;
  const erster = Math.ceil(fensterStart / stufe.ms) * stufe.ms;
  const ticks = [];
  const gesehen = new Set();
  for (let t = erster; t <= fensterEnde + stufe.ms / 2; t += stufe.ms) {
    const datum = new Date(t);
    const label = zeitstrahlTickText(datum, stufe.art);
    if (gesehen.has(label)) continue;
    gesehen.add(label);
    const dataPct = ((t - von.getTime()) / gesamtMs) * 100;
    ticks.push({
      label,
      left: ((dataPct - x0) / span) * 100,
    });
  }
  if (!ticks.length) {
    ticks.push({
      label: zeitstrahlTickText(new Date(fensterStart), stufe.art),
      left: 0,
    });
  }
  return ticks;
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
/** Sats an einer Daten-Y-% (0 = 0 sats, 100 = max), log1p. */
function zeitstrahlYSatsAn(maxSats, yPct) {
  const max = Math.max(Number(maxSats) || 0, 0);
  if (max <= 0 || yPct <= 0) return 0;
  if (yPct >= 99.9) return max;
  return Math.expm1(Math.log1p(max) * (yPct / 100));
}

/** log1p-Daten-% eines Betrags auf der Achse 0 … max. */
function zeitstrahlYPctFuerSats(maxSats, sats) {
  const max = Math.max(Number(maxSats) || 0, 0);
  const ziel = Math.max(0, Number(sats) || 0);
  if (max <= 0 || ziel <= 0) return 0;
  if (ziel >= max) return 100;
  return (Math.log1p(ziel) / Math.log1p(max)) * 100;
}

function zeichneZeitstrahlYAchse(maxSats) {
  const yAchse = $("#achse-y");
  if (!yAchse) return;
  yAchse.replaceChildren();
  yAchse.removeAttribute("aria-hidden");

  const max = Math.max(Number(maxSats) || 0, 0);
  const unten = zeitstrahlYSatsAn(max, ZeitstrahlAnsicht.y0);
  const oben = Math.max(unten, zeitstrahlYSatsAn(max, ZeitstrahlAnsicht.y1));
  const skala = document.createElement("div");
  skala.className = "achse-y-skala";
  skala.style.height = `${ZeitstrahlAnsicht.hoehe}px`;

  // Senkrechte Linie — Pendant zu .achse-linie auf der X-Achse.
  const linie = document.createElement("div");
  linie.className = "achse-y-linie";
  linie.setAttribute("aria-hidden", "true");
  linie.style.height = `${ZeitstrahlAnsicht.hoehe}px`;
  skala.append(linie);

  const logUnten = Math.log1p(unten);
  const logOben = Math.log1p(oben);
  const logSpan = logOben - logUnten;
  const kandidaten = new Set(zeitstrahlYTickSats(oben));
  if (unten > 0) kandidaten.add(Math.round(unten));
  for (const sats of [...kandidaten].sort((a, b) => a - b)) {
    if (sats < unten * 0.98) continue;
    const span = document.createElement("span");
    span.className = "achse-y-tick";
    span.textContent = formatZeitstrahlBetrag(sats);
    const y = logSpan <= 0
      ? 0
      : ((Math.log1p(Math.min(sats, oben)) - logUnten) / logSpan) * 100;
    if (y < -2 || y > 102) continue;
    span.style.bottom = `${y}%`;
    skala.append(span);
  }
  yAchse.append(skala);
}

function zeitstrahlHoeheSetzen(px) {
  const hoehe = Math.round(
    Math.max(ZEITSTRAHL_MIN_HOEHE, Math.min(ZEITSTRAHL_MAX_HOEHE, Number(px) || 220)),
  );
  ZeitstrahlAnsicht.hoehe = hoehe;
  const spur = $("#achse-spur");
  if (spur) spur.style.height = `${hoehe}px`;
  try {
    localStorage.setItem(ZEITSTRAHL_HOEHE_KEY, String(hoehe));
  } catch (_) { /* privat / voll — Höhe gilt nur für diese Sitzung */ }
}

function liesZeitstrahlHoehe() {
  try {
    const roh = Number(localStorage.getItem(ZEITSTRAHL_HOEHE_KEY));
    if (roh >= ZEITSTRAHL_MIN_HOEHE && roh <= ZEITSTRAHL_MAX_HOEHE) return roh;
  } catch (_) { /* leer */ }
  return 220;
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
    if (rect.width <= 0 || rect.height <= 0) return;
    const ankerX = ((ereignis.clientX - rect.left) / rect.width) * 100;
    const ankerY = ((rect.bottom - ereignis.clientY) / rect.height) * 100;
    // Runter = rauszoomen, hoch = reinzoomen — am Mauszeiger, Y nicht unter 0.
    const faktor = ereignis.deltaY > 0 ? 1.15 : 1 / 1.15;
    zeitstrahlZoom(faktor, ankerX, ankerY);
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
    const xVoll = ZeitstrahlAnsicht.x0 <= zeitstrahlXMin() + 0.05
      && ZeitstrahlAnsicht.x1 >= 99.9;
    const yVoll = ZeitstrahlAnsicht.y0 <= 0.05
      && ZeitstrahlAnsicht.y1 <= 100.05;
    if (xVoll && yVoll) return;
    if (
      ereignis.button === 0
      && ereignis.target
      && ereignis.target.closest
      && ereignis.target.closest(".achse-punkt:not(.geister)")
    ) {
      return;
    }
    ereignis.preventDefault();
    const drag = { id: ereignis.pointerId, x: ereignis.clientX, y: ereignis.clientY };
    viewport.classList.add("ziehend");

    const onMove = (ev) => {
      if (ev.pointerId !== drag.id) return;
      const rect = viewport.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const deltaX = ((ev.clientX - drag.x) / rect.width) * 100;
      // Maus rauf → Inhalt rauf (Fenster sinkt), wie die Zeitachse der Maus folgt.
      const deltaY = ((ev.clientY - drag.y) / rect.height) * 100;
      drag.x = ev.clientX;
      drag.y = ev.clientY;
      if (deltaX === 0 && deltaY === 0) return;
      zeitstrahlPan(deltaX, deltaY);
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
    ZeitstrahlAnsicht.y0 = 0;
    ZeitstrahlAnsicht.y1 = 100;
    zeichneZeitstrahl(ZeitstrahlAnsicht.daten, { fensterBehalten: true });
  });

  const griff = $("#zeitstrahl-griff");
  if (griff && !griff.dataset.gebunden) {
    griff.dataset.gebunden = "1";
    griff.addEventListener("pointerdown", (ereignis) => {
      if (ereignis.button !== 0) return;
      ereignis.preventDefault();
      const startY = ereignis.clientY;
      const startH = ZeitstrahlAnsicht.hoehe;
      griff.classList.add("ziehend");
      const onMove = (ev) => {
        zeitstrahlHoeheSetzen(startH + (ev.clientY - startY));
        if (ZeitstrahlAnsicht.daten) {
          zeichneZeitstrahl(ZeitstrahlAnsicht.daten, { fensterBehalten: true });
        }
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        griff.classList.remove("ziehend");
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    });
    griff.addEventListener("dblclick", (ereignis) => {
      ereignis.preventDefault();
      zeitstrahlHoeheSetzen(220);
      if (ZeitstrahlAnsicht.daten) {
        zeichneZeitstrahl(ZeitstrahlAnsicht.daten, { fensterBehalten: true });
      }
    });
  }
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
  const events = (strahl && strahl.events) || [];
  // Ohne UTXOs bleibt die Fläche sichtbar, mit festem Ausschnitt.
  const leerRahmen = Boolean(strahl && strahl.leer && strahl.von && strahl.bis);

  if (!strahl || !strahl.vorhanden || (!events.length && !leerRahmen)) {
    karte.hidden = true;
    ZeitstrahlAnsicht.daten = null;
    if (typeof herkunftsnetzBeenden === "function") herkunftsnetzBeenden();
    return;
  }
  karte.hidden = false;

  ZeitstrahlAnsicht.daten = daten;
  if (!optionen.fensterBehalten) {
    ZeitstrahlAnsicht.x0 = 0;
    ZeitstrahlAnsicht.x1 = 100;
    if (typeof Herkunftsnetz !== "undefined") Herkunftsnetz.fensterGeoeffnet = false;
    if (leerRahmen && Number(strahl.y_min_sats) > 0) {
      ZeitstrahlAnsicht.y0 = zeitstrahlYPctFuerSats(strahl.max_sats, strahl.y_min_sats);
      ZeitstrahlAnsicht.y1 = 100;
    } else {
      ZeitstrahlAnsicht.y0 = 0;
      ZeitstrahlAnsicht.y1 = 100;
    }
  }
  if (!ZeitstrahlAnsicht.hoehe || ZeitstrahlAnsicht.hoehe === 220) {
    ZeitstrahlAnsicht.hoehe = liesZeitstrahlHoehe();
  }
  zeitstrahlHoeheSetzen(ZeitstrahlAnsicht.hoehe);
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
    const y = zeitstrahlSichtY(eintrag.y ?? 0);
    if (y < -8 || y > 108) continue;
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
    if (eintrag.herkunft_offen) punkt.classList.add("herkunft-offen-marke");
    if (key) punkt.dataset.key = key;
    if (eintrag.wallet_id) punkt.dataset.walletId = eintrag.wallet_id;
    if (eintrag.wallet) punkt.dataset.wallet = eintrag.wallet;
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
    if (key) punkt.classList.add("klickbar");
    punkt.style.left = `${sicht}%`;
    punkt.style.bottom = `${y}%`;
    // Betrag/Datum/Wallet nur im Hover-Tooltip — feste Labels überladen den Plot.
    const tip = document.createElement("span");
    tip.className = sicht > 70 ? "achse-punkt-tip links" : "achse-punkt-tip";
    const herkunftHinweis = eintrag.herkunft_offen
      ? t("tax.plotIncomplete")
      : (!eintrag.geprueft && !eintrag.erfuellt)
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
      // Einfachklick wartet, bis klar ist, dass kein Doppelklick folgt.
      let einfach = null;
      punkt.addEventListener("click", (ereignis) => {
        ereignis.preventDefault();
        ereignis.stopPropagation();
        if (ereignis.detail > 1) return;
        if (eintrag.address && typeof kopiereInZwischenablage === "function") {
          kopiereInZwischenablage(eintrag.address);
        }
        if (einfach) clearTimeout(einfach);
        einfach = setTimeout(() => {
          einfach = null;
          herkunftsnetzUmschalten(key);
        }, 280);
      });
      punkt.addEventListener("dblclick", (ereignis) => {
        ereignis.preventDefault();
        ereignis.stopPropagation();
        if (einfach) {
          clearTimeout(einfach);
          einfach = null;
        }
        herkunftsnetzBericht(key);
      });
    }
    spur.append(punkt);
  }

  const ticks = $("#achse-ticks");
  ticks.replaceChildren();
  const breite = ticks.getBoundingClientRect().width
    || (ticks.parentElement && ticks.parentElement.getBoundingClientRect().width)
    || 0;
  for (const tick of zeitstrahlTicksImFenster(strahl, breite)) {
    const span = document.createElement("span");
    span.textContent = tick.label;
    if (tick.left != null) {
      span.style.left = `${tick.left}%`;
    }
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
  // Ephemerer Overlay (Herkunftsnetz) über dem neu gezeichneten Bestand.
  if (typeof herkunftsnetzZeichnen === "function") herkunftsnetzZeichnen();
  traceMarkenNachZeichnen();
  if (ScanPunktStand.offen.size && typeof zeichneScanPunkte === "function") {
    zeichneScanPunkte([...ScanPunktStand.offen.values()]);
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
  const fenster = daten.seitenweise ? (daten.abgaenge_fenster || {}) : null;
  const abgaenge = fenster ? (fenster.items || []) : (daten.abgaenge || []);
  const anzahl = fenster ? Number(fenster.voll_count) || 0 : abgaenge.length;

  if (!daten.hat_verlauf) {
    karte.hidden = true;
    return;
  }
  karte.hidden = false;

  const k = daten.kennzahlen;
  setzeText(
    $("#abgaenge-zusatz"),
    anzahl === 0
      ? t("ui.hard.c2b3477341")
      : `${anzahl} · ${fenster
        ? steuerSatsGemeinsam(k.abgang_sats, fenster.gemeinsam_ts)
        : formatSatsGemeinsam(
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
  liste._fensterTreffer = null;
  if (anzahl === 0) {
    liste.append(hinweisZeile(
      "In diesem Jahr wurde nichts ausgegeben."
    ));
    return;
  }

  if (!fenster) {
    for (const abgang of abgaenge) liste.append(zeichneAbgangZeile(abgang, daten));
    return;
  }

  // Seitenweise: Zeilen im Fenster, Leiste darunter.
  const auszug = (antwort) => {
    const f = antwort.abgaenge_fenster || {};
    return { items: f.items || [], total: Number(f.total) || 0, sats: Number(f.sats) || 0 };
  };
  const neueQuelle = (vorab) => neueSeitenQuelle({
    groesse: pagerGroesse("abgaenge"),
    laden: (o, l) => api(`/tax${daten._abfrage}&${steuerSeitenParameter("abgaenge", o, l, daten._q)}`),
    auszug,
    vorab,
  });
  let quelle = neueQuelle({ abgaenge_fenster: fenster });
  const zeigeSeite = (seite, q) => {
    liste.replaceChildren(...seite.items.map((a) => zeichneAbgangZeile(a, daten)));
    liste._fensterTreffer = { q: daten._q, total: seite.total, sats: auszug(seite.antwort).sats };
    liste.append(zeichnePager({
      total: seite.total,
      offset: seite.offset,
      groesse: q.groesse,
      ansicht: "abgaenge",
      onSeite: (o) => {
        q.seite(o).then((s2) => { if (q === quelle) zeigeSeite(s2, q); }).catch(() => {});
      },
      onGroesse: () => {
        quelle = neueQuelle(null);
        const q2 = quelle;
        q2.seite(0).then((s2) => { if (q2 === quelle) zeigeSeite(s2, q2); }).catch(() => {});
      },
    }));
  };
  zeigeSeite({
    antwort: { abgaenge_fenster: fenster },
    items: abgaenge.slice(0, quelle.groesse),
    total: Number(fenster.total) || 0,
    offset: 0,
  }, quelle);
}

/** Eine Zeile der Veräußerungen. */
function zeichneAbgangZeile(abgang, daten) {
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
    ...(abgang.exchange_spends || []).map((z) => z && z.name),
    haltefristBeschriftung(
      { erfuellt: abgang.frist_erfuellt, neuvermoegen: abgang.neuvermoegen },
      Boolean(daten.stichtag_regel),
    ),
  ].filter(Boolean).join(" ");

  const boerseAn = typeof formatAusgegebenAnBoerse === "function"
    ? formatAusgegebenAnBoerse({ exchange_spends: abgang.exchange_spends })
    : "";
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
    `${formatHaltedauer(abgang.haltedauer_tage)} gehalten` +
    (boerseAn ? ` · ${boerseAn}` : "");

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
  return zeile;
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
/** Seitenweise Kandidaten-Antwort (ISSUES P2) samt ``_abfrage``/``_q``. */
Zustand.saDaten = null;
/**
 * Angekreuzte Kandidaten als ``art:wert`` (wie ``input.dataset.art`` und
 * ``input.value``) — über Seiten, Vorladen und Filter hinweg; der Bericht
 * nimmt die ganze Auswahl, nicht nur die sichtbare Seite.
 */
Zustand.saGewaehlt = new Set();

/**
 * FiFo-/Report-Kandidaten aus dem Cache (Abflüsse + Was-wäre-wenn-UTXOs).
 *
 * Technisch: GET /tax/selbstanzeige/kandidaten — reiner Cache-Read, kein Trace.
 * Wird beim Öffnen des Steuerjahrs und bei Tip-Nachzug/Jahr-Wechsel oft
 * mitgeladen; das ist **kein** Herkunfts-Job.
 *
 * Seitenweise (ISSUES P2): Anzahlen über alles, je Liste zwei Seiten in der
 * ersten Antwort, weitere Seiten per Seitenleiste.
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
  const lauf = (Zustand.saLadeLauf || 0) + 1;
  Zustand.saLadeLauf = lauf;
  try {
    let abfrage = `?jahr=${encodeURIComponent(jahr)}`;
    if (txid) abfrage += `&txid=${encodeURIComponent(txid)}`;
    const filter = steuerFilterParameter();
    const p = new URLSearchParams(filter);
    p.set("seite", "1");
    p.set("limit", String(2 * pagerGroesse("sa_abfluesse")));
    p.set("limit_utxos", String(2 * pagerGroesse("sa_utxos")));
    p.set("lang", uiSprache());
    const daten = await api(`/tax/selbstanzeige/kandidaten${abfrage}&${p}`);
    if (lauf !== Zustand.saLadeLauf) return;
    daten._abfrage = abfrage;
    daten._q = filter.toString();
    Zustand.saDaten = daten;
    // Neu geladen = neue Liste: Häkchen wie bisher aus der Vorauswahl.
    const vorab = daten.ausgewaehlt || {};
    Zustand.saGewaehlt = new Set([
      ...(vorab.abfluss || []).map((w) => `abfluss:${w}`),
      ...(vorab.utxo || []).map((w) => `utxo:${w}`),
    ]);
    Zustand.saKandidaten = daten.abfluesse_fenster?.items || [];
    Zustand.saUtxos = daten.utxos_fenster?.items || [];
    Zustand.saVerlauf = daten.verlauf || null;
    Zustand.saStichtag = daten.stichtag_hypothese || "";
    zeichneSelbstanzeigeKandidaten();
    if (laut) {
      const n = Number(daten.abfluesse_fenster?.voll_count) || 0;
      const u = Number(daten.utxos_fenster?.voll_count) || 0;
      logZeile(
        t("ui.hard.92999accba", { n, u }),
      );
    }
  } catch (fehler) {
    if (lauf !== Zustand.saLadeLauf) return;
    liste.textContent = t("common.errorPrefix", { msg: fehler.message });
    if (laut) {
      logZeile(t("ui.hard.52e00c1044", { msg: fehler.message }));
    }
  }
}

/** Seiten-Parameter der Kandidatenlisten (Filter wie die geladene Seite). */
function saSeitenParameter(teil, offset, limit, filter) {
  const p = new URLSearchParams(filter || "");
  p.set("seite", "1");
  p.set("teil", teil);
  p.set("offset", String(offset));
  p.set("limit", String(limit));
  p.set("limit_utxos", String(limit));
  p.set("lang", uiSprache());
  return p.toString();
}

/** Neuer Kopf-Filter: nur die beiden Kandidatenfenster neu (Seite 1). */
async function ladeSaSeitenNeu() {
  const daten = Zustand.saDaten;
  if (!daten || !daten.seitenweise) return;
  const filter = steuerFilterParameter();
  const lauf = (Zustand.saZeilenLauf || 0) + 1;
  Zustand.saZeilenLauf = lauf;
  const p = new URLSearchParams(filter);
  p.set("seite", "1");
  p.set("teil", "zeilen");
  p.set("limit", String(2 * pagerGroesse("sa_abfluesse")));
  p.set("limit_utxos", String(2 * pagerGroesse("sa_utxos")));
  p.set("lang", uiSprache());
  const neu = await api(`/tax/selbstanzeige/kandidaten${daten._abfrage}&${p}`);
  if (lauf !== Zustand.saZeilenLauf || Zustand.saDaten !== daten) return;
  daten.abfluesse_fenster = neu.abfluesse_fenster;
  daten.utxos_fenster = neu.utxos_fenster;
  daten._q = filter.toString();
  zeichneSelbstanzeigeKandidaten();
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

/** Häkchen einer gezeichneten Zeile aus der Auswahl (``art:wert``). */
function saZeileMitAuswahl(zeile) {
  const box = zeile.querySelector("input[type=checkbox]");
  if (box) box.checked = Zustand.saGewaehlt.has(`${box.dataset.art}:${box.value}`);
  return zeile;
}

/** Häkchen → Auswahl; einmal je Liste (Zeilen wechseln beim Blättern). */
function saAuswahlMitschreiben(liste) {
  if (liste._saAuswahlHorcht) return;
  liste._saAuswahlHorcht = true;
  liste.addEventListener("change", (e) => {
    const el = e.target;
    if (!(el instanceof HTMLInputElement) || el.type !== "checkbox" || !el.value) return;
    const id = `${el.dataset.art}:${el.value}`;
    if (el.checked) Zustand.saGewaehlt.add(id);
    else Zustand.saGewaehlt.delete(id);
  });
}

/**
 * „Alle“/„Keine“ für Hypothese-UTXOs: gilt für **alle** Treffer des aktuellen
 * Filters über alle Seiten — der Server nennt ihre Werte.
 */
async function saUtxosAlleKeine(an) {
  const daten = Zustand.saDaten;
  const liste = $("#sa-liste");
  if (!daten || !liste) return;
  const p = new URLSearchParams(daten._q || "");
  p.set("seite", "1");
  p.set("teil", "utxos");
  p.set("werte", "1");
  p.set("lang", uiSprache());
  const antwort = await api(`/tax/selbstanzeige/kandidaten${daten._abfrage}&${p}`);
  if (Zustand.saDaten !== daten) return;
  for (const wert of antwort.werte || []) {
    const id = `utxo:${wert}`;
    if (an) Zustand.saGewaehlt.add(id);
    else Zustand.saGewaehlt.delete(id);
  }
  for (const el of liste.querySelectorAll("input[type=checkbox][data-art=utxo]")) {
    el.checked = Zustand.saGewaehlt.has(`utxo:${el.value}`);
  }
}

/**
 * Eine Kandidatenliste seitenweise in *innen*: Zeilen des Fensters, Leiste
 * darunter; Treffer über alle Seiten merkt sich *abschnitt* für den Filter.
 */
function zeichneSaSeiten({ abschnitt, innen, teil, fenster, zeichneZeile, ansicht, hostKlasse }) {
  const daten = Zustand.saDaten;
  const host = document.createElement("div");
  host.className = hostKlasse;
  const leiste = document.createElement("div");
  leiste.className = "sa-pager";
  innen.append(host, leiste);
  const auszug = (antwort) => {
    const f = antwort[`${teil}_fenster`] || {};
    return { items: f.items || [], total: Number(f.total) || 0, sats: Number(f.sats) || 0 };
  };
  const neueQuelle = (vorab) => neueSeitenQuelle({
    groesse: pagerGroesse(ansicht),
    laden: (o, l) => api(
      `/tax/selbstanzeige/kandidaten${daten._abfrage}&${saSeitenParameter(teil, o, l, daten._q)}`,
    ),
    auszug,
    vorab,
  });
  let quelle = neueQuelle({ [`${teil}_fenster`]: fenster });
  const zeigeSeite = (seite, q) => {
    host.replaceChildren(...seite.items.map((e) => saZeileMitAuswahl(zeichneZeile(e))));
    abschnitt._fensterTreffer = { q: daten._q, total: seite.total, sats: auszug(seite.antwort).sats };
    leiste.replaceChildren(zeichnePager({
      total: seite.total,
      offset: seite.offset,
      groesse: q.groesse,
      ansicht,
      onSeite: (o) => {
        q.seite(o).then((s2) => { if (q === quelle) zeigeSeite(s2, q); }).catch(() => {});
      },
      onGroesse: () => {
        quelle = neueQuelle(null);
        const q2 = quelle;
        q2.seite(0).then((s2) => { if (q2 === quelle) zeigeSeite(s2, q2); }).catch(() => {});
      },
    }));
  };
  // Erste Seite sofort aus der Gesamtantwort.
  zeigeSeite({
    antwort: { [`${teil}_fenster`]: fenster },
    items: (fenster.items || []).slice(0, quelle.groesse),
    total: Number(fenster.total) || 0,
    offset: 0,
  }, quelle);
}

function zeichneSelbstanzeigeKandidaten() {
  const liste = $("#sa-liste");
  if (!liste) return;
  liste.replaceChildren();
  saAuswahlMitschreiben(liste);

  const daten = Zustand.saDaten || {};
  const abFenster = daten.abfluesse_fenster || { items: [], total: 0, voll_count: 0 };
  const utFenster = daten.utxos_fenster || { items: [], total: 0, voll_count: 0 };
  const nAb = Number(abFenster.voll_count) || 0;
  const nUt = Number(utFenster.voll_count) || 0;
  const verlauf = Zustand.saVerlauf;

  const ab = saAbschnitt(
    t("tax.hard.b5128ead22"),
    nAb
      ? `${nAb} Kandidat(en)`
      : "keine",
    {
      offen: false,
      ausklappbar: nAb > 0,
      leerText: nAb
        ? ""
        : t("ui.hard.38c0e7c352"),
    },
  );
  if (nAb) {
    zeichneSaSeiten({
      abschnitt: ab.details,
      innen: ab.innen,
      teil: "abfluesse",
      fenster: abFenster,
      zeichneZeile: zeichneSaAbflussZeile,
      ansicht: "sa_abfluesse",
      hostKlasse: "sa-abfluss-host",
    });
  }
  liste.append(ab.details);

  const stichtag = Zustand.saStichtag
    ? t("ui.hard.11361714f6", { stichtag: Zustand.saStichtag })
    : "";
  // UTXOs aufklappen, wenn keine Abflüsse — sonst sieht man keine Checkboxen.
  const ut = saAbschnitt(
    t("tax.hard.bb993ba73a"),
    nUt
      ? `${nUt} UTXO(s)${stichtag}`
      : `keine${stichtag}`,
    {
      offen: nUt > 0 && nAb === 0,
      ausklappbar: nUt > 0,
      leerText: nUt
        ? ""
        : t("ui.hard.3939cbbda7"),
    },
  );
  if (nUt) {
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
      saUtxosAlleKeine(true).catch(() => {});
    });
    const keine = document.createElement("button");
    keine.type = "button";
    keine.className = "knopf knopf-klein";
    keine.textContent = "Keine";
    keine.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      saUtxosAlleKeine(false).catch(() => {});
    });
    werkzeug.append(alle, keine);
    ut.innen.append(werkzeug);
    zeichneSaSeiten({
      abschnitt: ut.details,
      innen: ut.innen,
      teil: "utxos",
      fenster: utFenster,
      zeichneZeile: zeichneSaUtxoZeile,
      ansicht: "sa_utxos",
      hostKlasse: "sa-utxo-host",
    });
  }
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

/**
 * Nur angekreuzte Kandidaten (ohne Einzahl-Tx-Feld) — die ganze Auswahl über
 * alle Seiten, nicht nur die gezeichnete (``Zustand.saGewaehlt``).
 */
function saAnkreuzAuswahl() {
  const txids = [];
  const utxos = [];
  for (const id of Zustand.saGewaehlt || []) {
    const trenner = id.indexOf(":");
    if (trenner < 0) continue;
    const art = id.slice(0, trenner);
    const wert = id.slice(trenner + 1);
    if (!wert) continue;
    if (art === "utxo" || wert.startsWith("utxo:")) {
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

/** Längste GET-Adresse für den CSV-Bericht; darüber per POST + Download. */
const SA_URL_MAX = 6000;

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

  // Auswahl über viele Seiten kann für eine URL zu lang werden → POST.
  const koerper = JSON.stringify({
    jahr, frist, txids, utxos, theme: guiThemeFuerBericht(),
  });
  const postKopf = { ...tokenKopf(), ...sprachKopf(), "Content-Type": "application/json" };

  if (art === "csv") {
    const adresse =
      `/api/tax/selbstanzeige/${datei}?${query}&t=${encodeURIComponent(Token)}`;
    if (adresse.length <= SA_URL_MAX) {
      window.open(adresse, "_blank", "noopener");
      return;
    }
    (async () => {
      try {
        const antwort = await fetch(`/api/tax/selbstanzeige/${datei}`, {
          method: "POST", headers: postKopf, body: koerper, credentials: "same-origin",
        });
        if (!antwort.ok) throw new Error(`HTTP ${antwort.status}`);
        const url = URL.createObjectURL(await antwort.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = `satsage-trace-${jahr}.csv`;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 120_000);
      } catch (fehler) {
        const kasten = $("#steuer-meldung");
        if (kasten) {
          kasten.className = "hinweis hinweis-krit";
          setzeText(kasten, `Report: ${fehler.message}`);
          kasten.hidden = false;
        }
      }
    })();
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
      const antwort = await fetch(`/api/tax/selbstanzeige/${datei}`, {
        method: "POST",
        headers: postKopf,
        body: koerper,
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
      link.download = `satsage-trace-${jahr}.html`;
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
