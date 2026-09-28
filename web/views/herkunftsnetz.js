/*
 * Steuerjahr · Herkunftsnetz als Overlay (ISSUES, Schritt 1).
 *
 * Klick auf einen Bestandspunkt im Zeitstrahl blendet ephemer das eigene
 * Vorgängernetz dieses UTXO ein: Layer A (Bestand) bleibt, ungewählte Punkte
 * werden gedimmt; Layer B zeichnet Vorfahren als orange Ringe an ihrer
 * Output-Zeit, Kanten orange mit Dicke ~ Sat-Anteil am gewählten Output.
 *
 * Nur das flache Netz vom Server liegt im Speicher (GET /api/tax/herkunftsnetz)
 * — nie ein Baum. Nichts davon landet in zeitstrahl.events[].
 * Ende: Esc, Klick ins Leere, zweiter Klick auf denselben Punkt, Ansichtswechsel.
 */

const Herkunftsnetz = {
  key: null,
  daten: null,
  abfrage: "",
  status: "",      // "" | "laedt" | "trace" | "fehlt" | "busy" | "fehler"
  fehler: "",
  lauf: 0,
  gebunden: false,
  druck: null,     // pointerdown-Position — Ziehen ist kein „Klick ins Leere“
};

const NETZ_SVG = "http://www.w3.org/2000/svg";

function herkunftsnetzAktiv() {
  return Boolean(Herkunftsnetz.key);
}

/**
 * HTML-Bericht: angekreuzte Zeilen, sonst nur dieses UTXO.
 * Doppelklick auf den Punkt und der Knopf in der Hinweiszeile.
 */
function herkunftsnetzBericht(key) {
  if (!key || typeof ladeSelbstanzeigeExport !== "function") return;
  const angekreuzt = typeof saAnkreuzAuswahl === "function"
    ? saAnkreuzAuswahl()
    : { txids: [], utxos: [] };
  const hatAuswahl = angekreuzt.txids.length > 0 || angekreuzt.utxos.length > 0;
  ladeSelbstanzeigeExport("html", hatAuswahl ? angekreuzt : { txids: [], utxos: [key] });
}

/** Klick auf einen Bestandspunkt: ein-, bei zweitem Klick ausblenden. */
function herkunftsnetzUmschalten(key) {
  if (!key) return;
  if (Herkunftsnetz.key === key) {
    herkunftsnetzBeenden();
    return;
  }
  herkunftsnetzStarten(key);
}

function herkunftsnetzBeenden() {
  if (!Herkunftsnetz.key && !Herkunftsnetz.daten) return;
  Herkunftsnetz.key = null;
  Herkunftsnetz.daten = null;
  Herkunftsnetz.status = "";
  Herkunftsnetz.fehler = "";
  Herkunftsnetz.lauf += 1;
  herkunftsnetzZeichnen();
}

function herkunftsnetzAbfrage() {
  const daten = typeof Zustand !== "undefined" ? Zustand.steuer : null;
  return (daten && daten._abfrage) || "";
}

async function herkunftsnetzStarten(key, { nachJob = false } = {}) {
  herkunftsnetzBinden();
  Herkunftsnetz.key = key;
  Herkunftsnetz.daten = null;
  Herkunftsnetz.status = "laedt";
  Herkunftsnetz.fehler = "";
  Herkunftsnetz.abfrage = herkunftsnetzAbfrage();
  const lauf = ++Herkunftsnetz.lauf;
  herkunftsnetzZeichnen();

  const trenner = Herkunftsnetz.abfrage ? "&" : "?";
  let daten;
  try {
    daten = await api(
      `/tax/herkunftsnetz${Herkunftsnetz.abfrage}${trenner}key=${encodeURIComponent(key)}`,
    );
  } catch (fehler) {
    if (lauf !== Herkunftsnetz.lauf) return;
    Herkunftsnetz.status = "fehler";
    Herkunftsnetz.fehler = (fehler && fehler.message) || String(fehler);
    herkunftsnetzZeichnen();
    return;
  }
  if (lauf !== Herkunftsnetz.lauf || Herkunftsnetz.key !== key) return;
  if (daten.trace_fehlt) {
    if (nachJob) {
      Herkunftsnetz.status = "fehlt";
      herkunftsnetzZeichnen();
      return;
    }
    herkunftsnetzHorizontLauf(key, lauf);
    return;
  }
  Herkunftsnetz.daten = daten;
  Herkunftsnetz.status = "";
  herkunftsnetzZeichnen();
}

/**
 * Fehlender Baum: begrenzter Steuer-Horizont-Lauf wie „Herkünfte UTXOs“
 * (Stop an Frist/Stichtag). Abbruch lässt den Bestand unangetastet.
 */
function herkunftsnetzHorizontLauf(key, lauf) {
  if (typeof herkunftAllerUtxos !== "function") {
    Herkunftsnetz.status = "fehlt";
    herkunftsnetzZeichnen();
    return;
  }
  if (typeof Zustand !== "undefined" && Zustand.herkunftAlleLaeuft) {
    Herkunftsnetz.status = "busy";
    herkunftsnetzZeichnen();
    return;
  }
  Herkunftsnetz.status = "trace";
  herkunftsnetzZeichnen();
  if (typeof logZeile === "function") {
    logZeile(t("tax.netzTraceLog", { key: `${key.slice(0, 12)}…:${key.split(":").pop()}` }));
  }
  herkunftAllerUtxos({
    knopf: null,
    lauf: "#herkunft-lauf",
    text: "#herkunft-text",
    abbruch: "#herkunft-abbruch",
    meldung: "#steuer-meldung",
    utxo_keys: [key],
    steuer: true,
    baumNoetig: true,
    gelbVertiefen: false,
    danach: async (ergebnis) => {
      if (lauf !== Herkunftsnetz.lauf || Herkunftsnetz.key !== key) return;
      if (!ergebnis || ergebnis.art !== "gut") {
        // Abbruch/Fehler: Bestand bleibt, wie er war — nur der Modus endet.
        Herkunftsnetz.status = "fehlt";
        herkunftsnetzZeichnen();
        return;
      }
      // Neuer Baum kann die wirksame Anschaffung (Layer A) verschieben.
      if (typeof ladeSteuerjahr === "function") await ladeSteuerjahr();
      if (Herkunftsnetz.key !== key) return;
      herkunftsnetzStarten(key, { nachJob: true });
    },
  });
}

/** Einmalig: Esc und Klick ins Leere beenden den Modus. */
function herkunftsnetzBinden() {
  if (Herkunftsnetz.gebunden) return;
  Herkunftsnetz.gebunden = true;
  document.addEventListener("keydown", (ereignis) => {
    if (ereignis.key === "Escape" && herkunftsnetzAktiv()) {
      herkunftsnetzBeenden();
    }
  });
  const viewport = document.querySelector("#achse-viewport");
  if (!viewport) return;
  viewport.addEventListener("pointerdown", (ereignis) => {
    Herkunftsnetz.druck = { x: ereignis.clientX, y: ereignis.clientY };
  }, true);
  viewport.addEventListener("click", (ereignis) => {
    if (!herkunftsnetzAktiv()) return;
    const druck = Herkunftsnetz.druck;
    Herkunftsnetz.druck = null;
    if (druck && Math.hypot(ereignis.clientX - druck.x, ereignis.clientY - druck.y) > 4) {
      return; // Pan, kein Klick
    }
    const ziel = ereignis.target;
    if (ziel && ziel.closest && ziel.closest(".achse-punkt:not(.geister), .netz-knoten")) return;
    herkunftsnetzBeenden();
  });
}

function herkunftsnetzProzent(anteil) {
  const wert = Math.max(0, Number(anteil) || 0) * 100;
  const stellen = wert > 0 && wert < 1 ? 2 : 1;
  return `${wert.toLocaleString(uiSprache() === "en" ? "en-US" : "de-DE", {
    minimumFractionDigits: stellen, maximumFractionDigits: stellen,
  })} %`;
}

/** Daten-% (ungeklemmt) → sichtbare Koordinaten; Vorfahren vor der Achse an den Rand. */
function herkunftsnetzLage(pos, y) {
  const p = Number(pos);
  const yy = Number(y) || 0;
  return {
    x: zeitstrahlSichtPos(Math.max(0, Math.min(100, p))),
    y: Math.max(0, Math.min(100, yy)),
    vorAchse: p < 0,
    ueberAchse: yy > 100,
  };
}

/** Aufgelöste Ringfarbe. CSS-Variable, damit Hell/Dunkel mitgeht. */
function herkunftsnetzFarbwert(name) {
  const fallback = name === "gut" ? "#2C7460" : "#E0730B";
  try {
    const wert = getComputedStyle(document.documentElement)
      .getPropertyValue(name === "gut" ? "--gut" : "--netz").trim();
    if (wert) return wert;
  } catch (fehler) {
    // DOM-Stub der Tests kennt getComputedStyle nicht.
  }
  return fallback;
}

/**
 * Lose des Fokus aus den Endknoten des Netzes, gewichtet mit anteil_sats.
 *
 * Grün: Output-Zeit links der Fristgrenze. Orange: rechts davon.
 * Grau: ohne Datum oder Bündel/Lücke/Horizont. Eigene Zwischenhops zählen nicht.
 */
function herkunftsnetzLotMischung(daten) {
  const vorfahren = (daten && daten.vorfahren) || [];
  const strahl = (typeof ZeitstrahlAnsicht !== "undefined"
    && ZeitstrahlAnsicht.daten && ZeitstrahlAnsicht.daten.zeitstrahl) || {};
  const frist = Number(strahl.frist_pos);
  const acc = { gruen: 0, orange: 0, grau: 0 };
  for (const v of vorfahren) {
    if (!v || !v.ende || v.key === daten.fokus_key) continue;
    const gewicht = Math.max(0, Number(v.anteil_sats) || 0);
    if (!(gewicht > 0)) continue;
    const pos = Number(v.pos_output);
    const typ = v.typ;
    let farbe = "grau";
    if (
      (typ === "fremd" || typ === "coinbase")
      && Number.isFinite(pos)
      && Number.isFinite(frist)
    ) {
      farbe = pos < frist ? "gruen" : "orange";
    }
    acc[farbe] += gewicht;
  }
  return acc.gruen + acc.orange + acc.grau > 0 ? acc : null;
}

/** Doughnut auf dem angeklickten Bestandspunkt. Kein title, kein aria-label. */
function setzeAchseLotDonut(punkt, daten) {
  if (!punkt || typeof setzeLotDonut !== "function") return;
  const mischung = herkunftsnetzLotMischung(daten);
  if (!mischung) {
    entferneAchseLotDonut(punkt);
    return;
  }
  const vorher = punkt.style.background;
  setzeLotDonut(punkt, mischung);
  if (!punkt.classList.contains("lot-donut")) return;
  punkt.classList.add("achse-lot");
  punkt.style.background = "";
  if (vorher) punkt.style.background = vorher;
}

function entferneAchseLotDonut(punkt) {
  if (!punkt || !punkt.classList.contains("achse-lot")) return;
  punkt.classList.remove("achse-lot", "lot-donut");
  delete punkt.dataset.lotGruen;
  delete punkt.dataset.lotOrange;
  delete punkt.dataset.lotGrau;
}

/** Ringfarbe: links der Fristgrenze grün, sonst orange. */
function herkunftsnetzRingFarbe(posOutput) {
  const strahl = (typeof ZeitstrahlAnsicht !== "undefined"
    && ZeitstrahlAnsicht.daten && ZeitstrahlAnsicht.daten.zeitstrahl) || {};
  const frist = Number(strahl.frist_pos);
  const pos = Number(posOutput);
  if (Number.isFinite(frist) && Number.isFinite(pos) && pos < frist) return "gut";
  return "netz";
}

function herkunftsnetzTypText(v, fokusKey) {
  if (v.key === fokusKey) return t("tax.netzFocus");
  if (v.typ === "buendel") return t("tax.netzBundle", { n: v.n });
  if (v.typ === "fremd") return t("tax.netzForeign");
  if (v.typ === "coinbase") return t("tax.netzCoinbase");
  if (v.typ === "horizont") return t("tax.netzHorizonNode");
  if (v.typ === "luecke") return t("tax.netzGap");
  return t("tax.netzOwn");
}

function herkunftsnetzHinweis() {
  const kasten = document.querySelector("#netz-hinweis");
  if (!kasten) return;
  if (!herkunftsnetzAktiv()) {
    kasten.hidden = true;
    kasten.replaceChildren();
    return;
  }
  kasten.hidden = false;
  kasten.replaceChildren();
  const marke = document.createElement("span");
  marke.className = "netz-hinweis-marke";
  marke.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.className = "netz-hinweis-text";
  text.textContent = t("tax.netzHint");
  const stand = document.createElement("span");
  stand.className = "netz-hinweis-stand";
  const d = Herkunftsnetz.daten;
  const teile = [];
  if (Herkunftsnetz.status === "laedt") teile.push(t("tax.netzWait"));
  else if (Herkunftsnetz.status === "trace") teile.push(t("tax.netzTraceRunning"));
  else if (Herkunftsnetz.status === "fehlt") teile.push(t("tax.netzNoTrace"));
  else if (Herkunftsnetz.status === "busy") teile.push(t("tax.netzBusy"));
  else if (Herkunftsnetz.status === "fehler") {
    teile.push(t("tax.netzError", { msg: Herkunftsnetz.fehler }));
  } else if (d) {
    teile.push(t("tax.netzCount", {
      n: Math.max(0, (d.vorfahren || []).length - 1),
      k: (d.kanten || []).length,
    }));
    teile.push(d.verfolgt_vollstaendig ? t("tax.netzFull") : t("tax.netzHorizon"));
    if (d.gekappt) teile.push(t("tax.netzCapped"));
  }
  stand.textContent = teile.length ? `· ${teile.join(" · ")}` : "";
  kasten.dataset.status = Herkunftsnetz.status || "bereit";

  const bericht = document.createElement("button");
  bericht.type = "button";
  bericht.className = "knopf knopf-klein netz-bericht";
  bericht.textContent = t("tax.netzReport");
  bericht.title = t("tax.netzReportTitle");
  const key = Herkunftsnetz.key;
  bericht.addEventListener("click", (ereignis) => {
    ereignis.preventDefault();
    herkunftsnetzBericht(key);
  });
  const ende = document.createElement("button");
  ende.type = "button";
  ende.className = "knopf knopf-klein netz-ende";
  ende.textContent = t("tax.netzEnd");
  ende.addEventListener("click", (ereignis) => {
    ereignis.preventDefault();
    herkunftsnetzBeenden();
  });
  kasten.append(marke, text, stand, bericht, ende);
}

/**
 * Zeichnet (oder entfernt) den Overlay über #achse-spur. Wird nach jedem
 * Neuzeichnen des Zeitstrahls aufgerufen (Pan/Zoom, Filter, Reload).
 */
function herkunftsnetzZeichnen() {
  const spur = document.querySelector("#achse-spur");
  if (!spur) return;
  for (const alt of spur.querySelectorAll(".netz-schicht")) alt.remove();

  const key = Herkunftsnetz.key;
  // Anderes Jahr/andere Frist oder Punkt nicht mehr im Bestand: Modus aus.
  // (Liegt der Punkt nur außerhalb des X-Fensters, bleibt der Modus an.)
  if (key) {
    const events = (ZeitstrahlAnsicht.daten?.zeitstrahl?.events) || [];
    const imBestand = events.some((e) => e.key === key);
    if (!imBestand || herkunftsnetzAbfrage() !== Herkunftsnetz.abfrage) {
      Herkunftsnetz.key = null;
      Herkunftsnetz.daten = null;
      Herkunftsnetz.status = "";
      Herkunftsnetz.lauf += 1;
    }
  }
  const aktiv = herkunftsnetzAktiv();
  spur.classList.toggle("netz-an", aktiv);
  for (const punkt of spur.querySelectorAll(".achse-punkt[data-key]")) {
    const fokus = aktiv && punkt.dataset.key === Herkunftsnetz.key;
    punkt.classList.toggle("netz-fokus", fokus);
    if (fokus && Herkunftsnetz.daten) setzeAchseLotDonut(punkt, Herkunftsnetz.daten);
    else entferneAchseLotDonut(punkt);
  }
  herkunftsnetzHinweis();
  const d = Herkunftsnetz.daten;
  if (!aktiv || !d) return;

  const schicht = document.createElement("div");
  schicht.className = "netz-schicht";
  const svg = document.createElementNS(NETZ_SVG, "svg");
  svg.setAttribute("class", "netz-kanten");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("preserveAspectRatio", "none");
  schicht.append(svg);

  const fokusSats = Math.max(1, Number(d.fokus_sats) || 1);
  const lagen = new Map();
  for (const v of d.vorfahren || []) {
    if (v.pos_output === null || v.pos_output === undefined) continue;
    lagen.set(v.key, herkunftsnetzLage(v.pos_output, v.y));
  }

  const defs = document.createElementNS(NETZ_SVG, "defs");
  svg.append(defs);
  let verlaufNr = 0;

  // Kante entlang der sichtbaren Linie. vonFarbe/nachFarbe sind
  // "gut" oder "netz"; gleiche Farbe bleibt ein einfacher Strich.
  const linie = (von, nach, klasse, breite, titel, vonFarbe, nachFarbe) => {
    const el = document.createElementNS(NETZ_SVG, "line");
    el.setAttribute("x1", String(von.x));
    el.setAttribute("y1", String(100 - von.y));
    el.setAttribute("x2", String(nach.x));
    el.setAttribute("y2", String(100 - nach.y));
    el.setAttribute("class", klasse);
    el.setAttribute("vector-effect", "non-scaling-stroke");
    el.setAttribute("stroke-width", String(breite));
    if (vonFarbe && nachFarbe && vonFarbe !== nachFarbe) {
      const id = `netz-verlauf-${++verlaufNr}`;
      const g = document.createElementNS(NETZ_SVG, "linearGradient");
      g.setAttribute("id", id);
      g.setAttribute("gradientUnits", "userSpaceOnUse");
      g.setAttribute("x1", String(von.x));
      g.setAttribute("y1", String(100 - von.y));
      g.setAttribute("x2", String(nach.x));
      g.setAttribute("y2", String(100 - nach.y));
      for (const [offset, name] of [["0%", vonFarbe], ["100%", nachFarbe]]) {
        const stopp = document.createElementNS(NETZ_SVG, "stop");
        stopp.setAttribute("offset", offset);
        // Attribut, nicht nur Klasse: sonst bleibt der Stopp ohne Farbe.
        stopp.setAttribute("stop-color", herkunftsnetzFarbwert(name));
        g.append(stopp);
      }
      defs.append(g);
      // .netz-kante setzt stroke per CSS und schlägt das Attribut.
      // Inline-Style gewinnt, sonst bleibt die Kante einfarbig orange.
      const bezug = `url(#${id})`;
      el.setAttribute("stroke", bezug);
      el.style.stroke = bezug;
      el.classList.add("netz-kante-verlauf");
    }
    if (titel) {
      const tip = document.createElementNS(NETZ_SVG, "title");
      tip.textContent = titel;
      el.append(tip);
    }
    svg.append(el);
  };

  // Layer A → Layer B des Fokus: erbt die Anschaffung, behält die Bewegungszeit.
  const fokusB = lagen.get(d.fokus_key);
  if (fokusB && d.fokus_pos !== null && d.fokus_pos !== undefined) {
    const fokusA = herkunftsnetzLage(d.fokus_pos, d.fokus_y);
    linie(fokusA, fokusB, "netz-kante netz-anschaffung", 1, "");
  }

  const farbeNachKey = new Map();
  for (const v of d.vorfahren || []) {
    farbeNachKey.set(v.key, herkunftsnetzRingFarbe(v.pos_output));
  }

  for (const kante of d.kanten || []) {
    const von = lagen.get(kante.von);
    const nach = lagen.get(kante.nach);
    if (!von || !nach) continue;
    const anteil = Math.max(0, Number(kante.sats) || 0) / fokusSats;
    const breite = 0.75 + 5.25 * Math.min(1, anteil);
    const klasse = kante.eigen ? "netz-kante" : "netz-kante netz-kante-fremd";
    linie(
      von, nach, klasse, breite.toFixed(2),
      `${formatZeitstrahlBetrag(kante.sats)} · ${t("tax.netzShare", { pct: herkunftsnetzProzent(anteil) })}`,
      farbeNachKey.get(kante.von),
      farbeNachKey.get(kante.nach),
    );
  }

  for (const v of d.vorfahren || []) {
    const lage = lagen.get(v.key);
    if (!lage || lage.x < -1 || lage.x > 101) continue;
    const ring = document.createElement("span");
    const klassen = ["netz-knoten", `netz-${v.typ || "eigen"}`];
    if (v.key === d.fokus_key) klassen.push("netz-fokus-b");
    if (lage.vorAchse) klassen.push("netz-vor-achse");
    if (herkunftsnetzRingFarbe(v.pos_output) === "gut") klassen.push("netz-vor-frist");
    if (lage.ueberAchse) klassen.push("netz-ueber-achse");
    ring.className = klassen.join(" ");
    ring.dataset.key = v.key;
    ring.style.left = `${lage.x}%`;
    ring.style.bottom = `${lage.y}%`;
    const tip = document.createElement("span");
    tip.className = lage.x > 70 ? "achse-punkt-tip links" : "achse-punkt-tip";
    const zeilen = [
      v.zeit || "",
      formatZeitstrahlBetrag(v.value_sats),
      [v.wallet, herkunftsnetzTypText(v, d.fokus_key)].filter(Boolean).join(" · "),
      t("tax.netzShare", { pct: herkunftsnetzProzent((Number(v.anteil_sats) || 0) / fokusSats) }),
    ];
    if (v.typ === "buendel" && v.zeit_von) {
      zeilen.push(t("tax.netzBundleRange", { von: v.zeit_von, bis: v.zeit }));
    }
    if (lage.vorAchse) zeilen.push(t("tax.netzBeforeAxis"));
    if (lage.ueberAchse) zeilen.push(t("tax.netzAboveAxis"));
    tip.textContent = zeilen.filter(Boolean).join("\n");
    ring.append(tip);
    if (v.typ === "buendel") {
      const zahl = document.createElement("span");
      zahl.className = "netz-buendel-zahl";
      zahl.textContent = String(v.n || "");
      ring.append(zahl);
    }
    schicht.append(ring);
  }
  spur.append(schicht);
}
