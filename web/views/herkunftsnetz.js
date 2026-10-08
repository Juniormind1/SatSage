/*
 * Steuerjahr · Herkunftsnetz als Overlay (ISSUES, Schritt 1).
 *
 * Hover auf einem Bestandspunkt mit Lot-Mix zeigt den 32-px-Lot-Ring
 * aus den Zeitstrahl-Zahlen (sats_gruen/orange/grau), ohne Request.
 * Klick blendet ephemer das eigene Vorgängernetz ein: Layer A (Bestand)
 * bleibt, ungewählte Punkte werden gedimmt; Layer B zeichnet Vorfahren
 * als orange Ringe an ihrer Output-Zeit, Kanten orange mit Dicke ~
 * Sat-Anteil am gewählten Output.
 *
 * Nur das flache Netz vom Server liegt im Speicher (GET /api/tax/herkunftsnetz)
 * — nie ein Baum. Nichts davon landet in zeitstrahl.events[].
 * Ende: Esc, Klick ins Leere, Ansichtswechsel.
 * Klick auf den Lot-Ring des Fokus (Netz an) springt zum UTXO in „Herkunft tracen“.
 * Klick auf einen eigenen Vorgänger-Ring springt in den Herkunftsbaum
 * dieses UTXO unter „Bereits ausgegeben“ des zugehörigen Wallets.
 */

const Herkunftsnetz = {
  key: null,
  daten: null,
  abfrage: "",
  status: "",      // "" | "laedt" | "trace" | "fehlt" | "busy" | "fehler"
  fehler: "",
  lauf: 0,
  fensterGeoeffnet: false,
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

/**
 * Grauer Punkt: innerhalb der Frist, ohne Herkunft.
 *
 * Dafür gibt es kein Netz. Der Klick öffnet „Herkunft tracen“ und
 * klappt dieses UTXO dort auf.
 */
function herkunftsnetzOhneHerkunft(key) {
  const punkt = herkunftsnetzPunktEl(key);
  if (punkt && punkt.classList.contains("ungeprueft")) return true;
  const events = (typeof Zustand !== "undefined" && Zustand.steuer?.zeitstrahl?.events) || [];
  const treffer = events.find(
    (e) => e && (e.key === key || (e.txid != null && `${e.txid}:${e.vout}` === key)),
  );
  return Boolean(treffer && treffer.geprueft === false && !treffer.erfuellt);
}

/** Klick auf einen Bestandspunkt: Netz einblenden.
 *  Liegt der Lot-Ring schon auf diesem Punkt, springt der Klick zum UTXO.
 *  Klick ins Leere blendet das Netz aus.
 */
function herkunftsnetzUmschalten(key) {
  if (!key) return;
  if (Herkunftsnetz.key === key) {
    const punktEl = herkunftsnetzPunktEl(key);
    // Sprung nur mit sichtbarem Netz-Ring, nicht schon durch Hover-Mix.
    const lot = Boolean(
      Herkunftsnetz.daten
      && punktEl
      && punktEl.classList.contains("achse-lot"),
    );
    const meta = herkunftsnetzPunkt(key);
    herkunftsnetzBeenden();
    if (lot && typeof springeZuTraceUtxo === "function") {
      springeZuTraceUtxo(key, meta);
    }
    return;
  }
  if (herkunftsnetzOhneHerkunft(key)) {
    const punkt = herkunftsnetzPunkt(key);
    if (typeof springeZuTraceUtxo === "function") {
      springeZuTraceUtxo(key, punkt);
      return;
    }
  }
  herkunftsnetzStarten(key);
}

function herkunftsnetzBaumVerwerfen() {
  Herkunftsnetz.baum = null;
}

function herkunftsnetzBeenden() {
  Herkunftsnetz.fensterGeoeffnet = false;
  if (!Herkunftsnetz.key && !Herkunftsnetz.daten) return;
  Herkunftsnetz.key = null;
  Herkunftsnetz.daten = null;
  Herkunftsnetz.status = "";
  Herkunftsnetz.fehler = "";
  Herkunftsnetz.lauf += 1;
  herkunftsnetzBaumVerwerfen();
  herkunftsnetzZeichnen();
}

/** Bestandspunkt im Plot. Id-Suche, dann Kinder — der Schlüssel enthält einen Doppelpunkt. */
function herkunftsnetzPunktEl(key) {
  const spur = document.querySelector("#achse-spur");
  if (!spur || !spur.querySelectorAll) return null;
  const gesucht = String(key || "");
  for (const el of spur.querySelectorAll(".achse-punkt")) {
    if (el.dataset && el.dataset.key === gesucht) return el;
  }
  return null;
}

/** Bestandspunkt zu txid:vout — Plot-DOM, sonst Zeitstrahl-Daten. */
function herkunftsnetzPunkt(key) {
  const punkt = herkunftsnetzPunktEl(key);
  const events = (typeof Zustand !== "undefined" && Zustand.steuer?.zeitstrahl?.events) || [];
  const treffer = events.find(
    (e) => e && (e.key === key || (e.txid != null && `${e.txid}:${e.vout}` === key)),
  ) || {};
  return {
    walletId: (punkt && punkt.dataset.walletId) || treffer.wallet_id || "",
    wallet: (punkt && punkt.dataset.wallet) || treffer.wallet || "",
    address: (punkt && punkt.dataset.address) || treffer.address || "",
    value_sats: (punkt && punkt.dataset.valueSats)
      ? Number(punkt.dataset.valueSats)
      : (treffer.value_sats ?? null),
  };
}

/** Wallet-Kennung des Bestandspunkts — für den Sprung, wenn kein Netz da ist. */
function herkunftsnetzWalletId(key) {
  const punkt = herkunftsnetzPunkt(key);
  if (punkt.walletId) return punkt.walletId;
  const wallets = (typeof Zustand !== "undefined" && Zustand.config?.wallets) || [];
  const name = String(punkt.wallet || "").trim();
  const nachName = wallets.find((w) => w && name && w.name === name);
  return (nachName && nachName.id) || "";
}

/** Netz mit wenigstens einem Vorgänger — sonst gehört der Klick ins Wallet. */
function herkunftsnetzHatDaten(daten) {
  if (!daten || daten.trace_fehlt) return false;
  const vorfahren = (daten.vorfahren || []).filter((v) => v && v.key !== daten.fokus_key);
  return vorfahren.length > 0 || (daten.kanten || []).length > 0;
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
  // Roter Ring = Herkunft leer und ungetraced. Farbe des Punkts (grün, gelb,
  // grau) ändert daran nichts: der Klick geht ins Wallet, nicht ins leere Netz.
  const punktEl = herkunftsnetzPunktEl(key);
  const ring = Boolean(punktEl && punktEl.classList.contains("herkunft-offen-marke"));
  if (ring) {
    if (nachJob) {
      Herkunftsnetz.status = "fehlt";
      herkunftsnetzZeichnen();
      return;
    }
    // Kein brauchbares Netz (kein Baum, oder nur die Wurzel). Im Wallet
    // liegen „Scan neu“ und „Herkunftslücken schließen“ an diesem UTXO.
    const punkt = herkunftsnetzPunkt(key);
    const walletId = herkunftsnetzWalletId(key);
    herkunftsnetzBeenden();
    if (walletId && typeof springeZuWalletUtxo === "function") {
      springeZuWalletUtxo(walletId, key, punkt.address);
      return;
    }
    Herkunftsnetz.key = key;
    Herkunftsnetz.status = "fehlt";
    herkunftsnetzZeichnen();
    return;
  }
  Herkunftsnetz.daten = daten;
  Herkunftsnetz.status = "";
  herkunftsnetzZeichnen();
  herkunftsnetzBaumVorladen(key);
}

/** Gespeicherten Baum schon holen, solange der Benutzer das Netz ansieht. */
function herkunftsnetzBaumVorladen(key) {
  if (!key || typeof api !== "function") return;
  if (Herkunftsnetz.baum && Herkunftsnetz.baum.key === key && Herkunftsnetz.baum.stand !== "fehler") {
    return;
  }
  const lauf = Herkunftsnetz.lauf;
  Herkunftsnetz.baum = { key, stand: "laedt", wert: null };
  api(`/trace?target=${encodeURIComponent(key)}`)
    .then((antwort) => {
      if (lauf !== Herkunftsnetz.lauf || Herkunftsnetz.key !== key) return;
      if (antwort && antwort.vorhanden && antwort.ergebnis) {
        Herkunftsnetz.baum = { key, stand: "da", wert: antwort.ergebnis };
      } else {
        Herkunftsnetz.baum = { key, stand: "fehlt", wert: null };
      }
    })
    .catch(() => {
      if (lauf !== Herkunftsnetz.lauf) return;
      Herkunftsnetz.baum = { key, stand: "fehler", wert: null };
    });
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

/** Echte Daten-Position. null/leer ist keine 0 — sonst liegt ein undatiertes Ende links der Frist. */
function herkunftsnetzPos(wert) {
  if (wert === null || wert === undefined || wert === "") return null;
  const n = Number(wert);
  return Number.isFinite(n) ? n : null;
}

/** Daten-% (ungeklemmt) → sichtbare Koordinaten. X darf vor 0 liegen. */
function herkunftsnetzLage(pos, y) {
  const p = Number(pos);
  const yy = Number(y) || 0;
  const xMin = typeof zeitstrahlXMin === "function" ? zeitstrahlXMin() : 0;
  return {
    x: zeitstrahlSichtPos(p),
    y: typeof zeitstrahlSichtY === "function"
      ? zeitstrahlSichtY(yy)
      : Math.max(0, Math.min(100, yy)),
    vorAchse: Number.isFinite(p) && p < xMin,
    ueberAchse: yy > (typeof zeitstrahlYMax === "function" ? zeitstrahlYMax() : 100),
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

/** Früheste datierte Nachfolger-Zeit. Der Eingang kann nicht jünger sein. */
function herkunftsnetzObergrenze(key, daten) {
  const nach = new Map();
  const zeiten = new Map();
  for (const kante of (daten && daten.kanten) || []) {
    if (!kante || !kante.von || !kante.nach) continue;
    const liste = nach.get(kante.von) || [];
    liste.push(String(kante.nach));
    nach.set(String(kante.von), liste);
  }
  for (const v of (daten && daten.vorfahren) || []) {
    const ts = Number(v && v.time_ts);
    if (v && v.key && Number.isFinite(ts) && ts > 0) zeiten.set(String(v.key), ts);
  }
  let beste = null;
  const schlange = [...(nach.get(String(key)) || [])];
  const gesehen = new Set();
  while (schlange.length) {
    const nxt = schlange.pop();
    if (!nxt || gesehen.has(nxt)) continue;
    gesehen.add(nxt);
    const ts = zeiten.get(nxt) || 0;
    if (ts > 0 && (beste === null || ts < beste)) beste = ts;
    for (const weiter of nach.get(nxt) || []) schlange.push(weiter);
  }
  return beste;
}

/** Stichtag der geladenen Auswertung, sonst der Einstellung. Leer = keine Regel. */
function herkunftsnetzStichtagIso() {
  const daten = (typeof ZeitstrahlAnsicht !== "undefined" && ZeitstrahlAnsicht.daten) || {};
  const regel = String(daten.stichtag_regel || "").trim();
  const de = regel.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (de) return `${de[3]}-${de[2]}-${de[1]}`;
  if (/^\d{4}-\d{2}-\d{2}$/.test(regel)) return regel;
  const steuer = typeof steuerEinstellungen === "function" ? steuerEinstellungen() : {};
  const iso = String(steuer.stichtag_iso || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso : "";
}

/**
 * Obergrenze liegt außerhalb der Haltefrist des geladenen Steuerjahres
 * und, falls gesetzt, nicht nach dem Stichtag. Dieselbe Entscheidung wie
 * ``haltefrist_entscheidung``, gegen ``bezug_ts`` — nicht gegen jetzt.
 */
function herkunftsnetzSicherAusserhalb(timeTs) {
  const ts = Number(timeTs);
  if (!Number.isFinite(ts) || ts <= 0) return false;
  const daten = (typeof ZeitstrahlAnsicht !== "undefined" && ZeitstrahlAnsicht.daten) || {};
  const bezug = Number(daten.bezug_ts);
  if (!Number.isFinite(bezug) || bezug <= 0) return false;
  const anschaffung = new Date(ts * 1000);
  const iso = herkunftsnetzStichtagIso();
  if (iso) {
    const monat = String(anschaffung.getMonth() + 1).padStart(2, "0");
    const tag = String(anschaffung.getDate()).padStart(2, "0");
    if (`${anschaffung.getFullYear()}-${monat}-${tag}` > iso) return false;
  }
  const jahre = Number(daten.haltefrist_jahre);
  const fristJahre = Number.isFinite(jahre) ? jahre : 1;
  if (fristJahre <= 0) return true;
  const monat = anschaffung.getMonth();
  const ziel = new Date(
    anschaffung.getFullYear() + fristJahre,
    monat,
    anschaffung.getDate(),
    anschaffung.getHours(),
    anschaffung.getMinutes(),
    anschaffung.getSeconds(),
  );
  const ende = ziel.getMonth() === monat
    ? ziel
    : new Date(
      anschaffung.getFullYear() + fristJahre,
      monat,
      28,
      anschaffung.getHours(),
      anschaffung.getMinutes(),
      anschaffung.getSeconds(),
    );
  return ende.getTime() / 1000 <= bezug;
}

/**
 * Lose des Fokus aus den Endknoten des Netzes, gewichtet mit anteil_sats.
 *
 * Grün: Output-Zeit links der Fristgrenze. Orange: rechts davon.
 * Datierte Bündel zählen mit ihrem jüngsten Eingang. Grau: ohne Datum,
 * Lücke oder Horizont. Eigene Zwischenhops zählen nicht.
 * Ein undatiertes Ende zählt grün, wenn ein Nachfolger schon außerhalb
 * der Haltefrist und nicht nach dem Stichtag liegt.
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
    const pos = herkunftsnetzPos(v.pos_output);
    const typ = v.typ;
    let farbe = "grau";
    if (
      (typ === "fremd" || typ === "coinbase" || typ === "buendel")
      && pos !== null
      && Number.isFinite(frist)
    ) {
      farbe = pos < frist ? "gruen" : "orange";
    } else if (
      pos === null
      && herkunftsnetzSicherAusserhalb(herkunftsnetzObergrenze(v.key, daten))
    ) {
      farbe = "gruen";
    }
    acc[farbe] += gewicht;
  }
  return acc.gruen + acc.orange + acc.grau > 0 ? acc : null;
}

/** Drei Zeilen für den Hover des Lot-Rings. Kleine Anteile bleiben sichtbar. */
function herkunftsnetzLotZeilen(mischung) {
  const summe = mischung.gruen + mischung.orange + mischung.grau;
  if (!(summe > 0)) return [];
  return [
    t("tax.netzLotGruen", { pct: herkunftsnetzProzent(mischung.gruen / summe) }),
    t("tax.netzLotGelb", { pct: herkunftsnetzProzent(mischung.orange / summe) }),
    t("tax.netzLotGrau", { pct: herkunftsnetzProzent(mischung.grau / summe) }),
  ];
}

function setzeAchseLotTooltip(punkt, mischung) {
  const tip = punkt.querySelector(".achse-punkt-tip");
  if (!tip) return;
  if (tip.dataset.lotBasis === undefined) tip.dataset.lotBasis = tip.textContent;
  const zeilen = herkunftsnetzLotZeilen(mischung);
  tip.textContent = [tip.dataset.lotBasis, ...zeilen].filter(Boolean).join("\n");
}

function entferneAchseLotTooltip(punkt) {
  const tip = punkt.querySelector(".achse-punkt-tip");
  if (!tip || tip.dataset.lotBasis === undefined) return;
  tip.textContent = tip.dataset.lotBasis;
  delete tip.dataset.lotBasis;
}

/** Lot-Mix aus den Zeitstrahl-Zahlen. Fehlt sats_gruen, gibt es keinen Ring. */
function achseLotMischungAusEvent(eintrag) {
  if (!eintrag) return null;
  if (eintrag.sats_gruen === null || eintrag.sats_gruen === undefined) return null;
  const gruen = Math.max(0, Number(eintrag.sats_gruen) || 0);
  const orange = Math.max(0, Number(eintrag.sats_orange) || 0);
  const grau = Math.max(0, Number(eintrag.sats_grau) || 0);
  if (!(gruen + orange + grau > 0)) return null;
  return { gruen, orange, grau };
}

/** Doughnut-Daten auf dem Punkt. Kein title, kein aria-label. */
function setzeAchseLotAusMischung(punkt, mischung) {
  if (!punkt) return;
  if (!mischung) {
    entferneAchseLotDonut(punkt);
    return;
  }
  if (typeof setzeLotDonut !== "function") return;
  const vorher = punkt.style.background;
  setzeLotDonut(punkt, mischung);
  if (!punkt.classList.contains("lot-donut")) return;
  punkt.classList.add("achse-lot");
  punkt.style.background = "";
  if (vorher) punkt.style.background = vorher;
  punkt.removeAttribute("title");
  setzeAchseLotTooltip(punkt, mischung);
}

/** Doughnut aus dem Herkunftsnetz des angeklickten Punkts. */
function setzeAchseLotDonut(punkt, daten) {
  setzeAchseLotAusMischung(punkt, herkunftsnetzLotMischung(daten));
}

/** Doughnut aus dem Zeitstrahl-Event — Hover ohne extra Request. */
function setzeAchseLotAusEvent(punkt, eintrag) {
  setzeAchseLotAusMischung(punkt, achseLotMischungAusEvent(eintrag));
}

function entferneAchseLotDonut(punkt) {
  if (!punkt || !punkt.classList.contains("achse-lot")) return;
  entferneAchseLotTooltip(punkt);
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
  const pos = herkunftsnetzPos(posOutput);
  if (pos !== null && Number.isFinite(frist) && pos < frist) return "gut";
  if (pos === null) return "";
  return "netz";
}

/** Jeder Punkt außer dem Fokus hat eine Stelle im Baum dieses UTXO. */
function herkunftsnetzSpringbar(v, fokusKey) {
  return Boolean(v && v.key && v.key !== fokusKey);
}

/** txid:vout, wenn der Punkt einen echten Output meint. mempool.space sucht das. */
function herkunftsnetzOutpoint(key) {
  const treffer = String(key || "").match(/^([0-9a-f]{64}):(\d+)$/i);
  return treffer ? `${treffer[1]}:${treffer[2]}` : "";
}

/**
 * Klick auf einen Vorgänger-Punkt: Herkunft tracen des Fokus öffnen und
 * dort die Zeile zeigen, die dieser Punkt meint.
 */
function herkunftsnetzZumBaum(v) {
  const fokus = Herkunftsnetz.key;
  const eltern = (Herkunftsnetz.daten?.kanten || []).find((k) => k.von === v?.key);
  // Bündel hat keinen eigenen Output. Die Transaktion, die es zusammenfasst,
  // ist die des Hops, den die Eingänge finanzieren — bei einem CoinJoin genau die.
  const outpoint = herkunftsnetzOutpoint(v && v.key)
    || (v && v.typ === "buendel" ? herkunftsnetzOutpoint(eltern && eltern.nach) : "");
  if (outpoint && typeof kopiereInZwischenablage === "function") {
    kopiereInZwischenablage(outpoint);
  }
  if (!v || !fokus || typeof zeigeHerkunftFuer !== "function") return;
  Zustand.traceSprung = {
    fokus,
    key: v.key,
    typ: v.typ || "",
    eltern: eltern ? eltern.nach : "",
  };
  const meta = typeof utxoMetaAusSteuerjahr === "function"
    ? utxoMetaAusSteuerjahr(fokus)
    : null;
  zeigeHerkunftFuer(fokus, { meta: meta || { key: fokus } });
}

/** Beide Enden haben ein Wallet, und es ist nicht dasselbe. */
function herkunftsnetzWalletWechsel(kante, knotenNachKey) {
  const a = String(knotenNachKey.get(kante.von)?.wallet || "").trim();
  const b = String(knotenNachKey.get(kante.nach)?.wallet || "").trim();
  return Boolean(a && b && a !== b);
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
      herkunftsnetzBaumVerwerfen();
    }
  }
  const aktiv = herkunftsnetzAktiv();
  spur.classList.toggle("netz-an", aktiv);
  const events = (ZeitstrahlAnsicht.daten?.zeitstrahl?.events) || [];
  const nachKey = new Map();
  for (const event of events) {
    if (event && event.key) nachKey.set(event.key, event);
  }
  for (const punkt of spur.querySelectorAll(".achse-punkt[data-key]")) {
    const fokus = aktiv && punkt.dataset.key === Herkunftsnetz.key;
    punkt.classList.toggle("netz-fokus", fokus);
    if (fokus && Herkunftsnetz.daten) setzeAchseLotDonut(punkt, Herkunftsnetz.daten);
    else setzeAchseLotAusEvent(punkt, nachKey.get(punkt.dataset.key));
  }
  herkunftsnetzHinweis();
  const d = Herkunftsnetz.daten;
  // Ältester Input links vom Achsenbeginn: Fenster einmal dorthin öffnen,
  // damit er nicht außerhalb bei 0 liegt. Danach darf der Nutzer frei pannen.
  if (
    aktiv && d
    && !Herkunftsnetz.fensterGeoeffnet
    && typeof ZeitstrahlAnsicht !== "undefined"
    && typeof zeitstrahlXMin === "function"
    && typeof zeichneZeitstrahl === "function"
  ) {
    const xMin = zeitstrahlXMin();
    if (xMin < -0.05 && ZeitstrahlAnsicht.x0 > xMin + 0.05 && ZeitstrahlAnsicht.daten) {
      Herkunftsnetz.fensterGeoeffnet = true;
      const span = ZeitstrahlAnsicht.x1 - ZeitstrahlAnsicht.x0;
      ZeitstrahlAnsicht.x0 = xMin;
      ZeitstrahlAnsicht.x1 = xMin + span;
      zeichneZeitstrahl(ZeitstrahlAnsicht.daten, { fensterBehalten: true });
      return;
    }
    Herkunftsnetz.fensterGeoeffnet = true;
  }
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
  const knotenNachKey = new Map();
  for (const v of d.vorfahren || []) {
    farbeNachKey.set(v.key, herkunftsnetzRingFarbe(v.pos_output));
    knotenNachKey.set(v.key, v);
  }

  for (const kante of d.kanten || []) {
    const von = lagen.get(kante.von);
    const nach = lagen.get(kante.nach);
    if (!von || !nach) continue;
    const anteil = Math.max(0, Number(kante.sats) || 0) / fokusSats;
    const breite = 0.75 + 5.25 * Math.min(1, anteil);
    const klassen = [kante.eigen ? "netz-kante" : "netz-kante netz-kante-fremd"];
    if (herkunftsnetzWalletWechsel(kante, knotenNachKey)) {
      klassen.push("netz-kante-wallet");
    }
    const klasse = klassen.join(" ");
    linie(
      von, nach, klasse, breite.toFixed(2),
      `${formatZeitstrahlBetrag(kante.sats)} · ${t("tax.netzShare", { pct: herkunftsnetzProzent(anteil) })}`,
      farbeNachKey.get(kante.von),
      farbeNachKey.get(kante.nach),
    );
  }

  for (const v of d.vorfahren || []) {
    const lage = lagen.get(v.key);
    // Auch knapp links vom Fenster: sonst verschwindet der älteste Ring,
    // solange die Achse noch bei 0 steht und der Pan noch nicht dort ist.
    if (!lage || lage.x < -12 || lage.x > 108) continue;
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
    if (herkunftsnetzSpringbar(v, d.fokus_key)) {
      zeilen.push(t("tax.netzJump"));
      ring.classList.add("netz-sprung");
      ring.title = t("tax.netzJumpTitle");
      ring.addEventListener("click", (ereignis) => {
        ereignis.preventDefault();
        ereignis.stopPropagation();
        herkunftsnetzZumBaum(v);
      });
    }
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
