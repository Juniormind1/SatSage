/** Einrichtung-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: Globals aus app.js (Zustand, api, t, $, pille, meldung, …).
 * Kein import/export. Laden nach app.js, vor boot.js.
 * Navigation nach „Weiter“ nutzt oeffneVerwaltung (chrome_nav.js), Ziel aus der Schritt-ID.
 */

// ---------------------------------------------------------------------------
// Einrichtung
// ---------------------------------------------------------------------------

/** Merker, dass der Hinweis schon einmal gezeigt wurde — er soll nicht nerven. */
const EINRICHTUNG_MERKER = "xpq-einrichtung-gesehen";

/** Quellen, die als „eigener Node“ zählen (Electrum-Server oder Bitcoin Core). */
const EINRICHTUNG_NODE_QUELLEN = ["own_fulcrum", "own_core", "own_utxo_core"];

/**
 * Die Schritte der Einrichtung in Anzeige-Reihenfolge: eigener Node
 * (empfohlen; ohne ihn greifen Compact Filter), Block-Explorer (optional,
 * hält die Einrichtung nicht offen) und zuletzt das Wallet (Pflicht).
 *
 * Der Stand wird aus der Konfiguration abgeleitet, nicht gespeichert: Wer
 * etwas in der .env von Hand einträgt, sieht es hier sofort als erledigt.
 * ``id`` ist sprachunabhängig (Navigation), ``titel`` nur Anzeige;
 * ``optional`` zählt nicht als offen.
 */
function einrichtungsSchritte(config) {
  const wallets = config?.wallets || [];
  const quellen = config?.sources || [];
  const mempool = config?.mempool || {};
  const node = EINRICHTUNG_NODE_QUELLEN
    .map((key) => quellen.find((q) => q.key === key))
    .find((q) => q?.configured);

  return [
    {
      id: "node",
      titel: t("setup.step.node"),
      erledigt: Boolean(node),
      stand: node ? node.detail : t("setup.step.notSet"),
      text: t("setup.step.nodeText"),
    },
    {
      id: "explorer",
      optional: true,
      titel: t("setup.step.explorer"),
      erledigt: Boolean(mempool.configured),
      stand: mempool.configured ? mempool.host : t("setup.step.notSet"),
      text: t("setup.step.explorerText"),
    },
    {
      id: "wallets",
      titel: t("setup.step.wallets"),
      erledigt: wallets.length > 0,
      stand: wallets.length
        ? t("setup.step.walletsStand", { n: wallets.length })
        : t("setup.step.walletsNone"),
      text: t("setup.step.walletsText"),
    },
  ];
}

/** Wohin der Hauptknopf führt: erst Wallets, dann Datenquellen. */
function einrichtungsZiel(config) {
  const schritte = einrichtungsSchritte(config);
  const offen = (id) => !schritte.find((s) => s.id === id)?.erledigt;
  return offen("wallets") || !offen("node") ? "wallets" : "datenquellen";
}

/** Beschriftung des Hauptknopfs passend zum Ziel. */
function zeichneEinrichtungKnopf() {
  const knopf = $("#einrichtung-weiter");
  if (!knopf) return;
  const node = einrichtungsZiel(Zustand.config) === "datenquellen";
  knopf.textContent = t(node ? "dialog.setup.continueNode" : "dialog.setup.continue");
  knopf.title = t(node ? "dialog.setup.continueNodeTitle" : "dialog.setup.continueTitle");
}

function zeichneEinrichtung() {
  const liste = $("#einrichtung-schritte");
  liste.replaceChildren();

  for (const schritt of einrichtungsSchritte(Zustand.config)) {
    const punkt = document.createElement("li");
    punkt.className = schritt.erledigt
      ? "schritt erledigt"
      : (schritt.optional ? "schritt optional" : "schritt offen");
    punkt.dataset.schritt = schritt.id;

    const kopf = document.createElement("div");
    kopf.className = "schritt-kopf";
    const titel = document.createElement("strong");
    titel.textContent = schritt.titel;
    kopf.append(titel, pille(schritt.erledigt ? "gut" : (schritt.optional ? "neutral" : "warn"), schritt.stand));

    const text = document.createElement("p");
    text.className = "schritt-text";
    text.textContent = schritt.text;

    punkt.append(kopf, text);
    liste.append(punkt);
  }

  zeichneEinrichtungKnopf();
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
  return einrichtungsSchritte(Zustand.config).some((s) => !s.erledigt && !s.optional);
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
// Event-Listener (DOM steht: Scripts am Ende von index.html)
// ---------------------------------------------------------------------------

function bindeEinrichtungUi() {
  if (bindeEinrichtungUi._done) return;
  bindeEinrichtungUi._done = true;

  const weiter = $("#einrichtung-weiter");
  if (weiter) {
    weiter.addEventListener("click", () => {
      // Ziel aus der Schritt-ID, nicht aus dem (übersetzten) Titel.
      const ziel = einrichtungsZiel(Zustand.config);
      schliesseEinrichtung();
      oeffneVerwaltung(ziel);
    });
  }

  const spaeter = $("#einrichtung-spaeter");
  if (spaeter) spaeter.addEventListener("click", () => schliesseEinrichtung());

  const onchainOk = $("#einrichtung-onchain-ok");
  if (onchainOk) onchainOk.addEventListener("click", bestaetigeOnchainHinweis);

  const onchain = $("#onchain-hinweis");
  if (onchain) {
    onchain.addEventListener("keydown", (e) => {
      if ($("#onchain-hinweis").hidden) return;
      if (e.key === "Enter" || e.key === "Escape") {
        e.preventDefault();
        bestaetigeOnchainHinweis();
      }
    });
  }

  const oeffnen = $("#einrichtung-oeffnen");
  if (oeffnen) oeffnen.addEventListener("click", zeigeEinrichtung);
}

bindeEinrichtungUi();
