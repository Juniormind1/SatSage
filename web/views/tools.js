/** Auswerten · Tools. Weitere Werkzeuge kommen als eigene Karte dazu. */

let toolsPruefLauf = 0;
let toolsLetztes = null;

function toolsErgebnis(text, art) {
  const el = $("#tools-meine-ergebnis");
  if (!el) return;
  el.className = "tools-ergebnis" + (art ? " tools-ergebnis-" + art : "");
  setzeText(el, text || "");
  el.hidden = !text;
}

function zeichneToolsStatus(status, wallet) {
  const bekannt = status === "meine" || status === "fremd"
    || status === "keine_wallets" || status === "checking" || status === "ungueltig";
  const effektiv = bekannt ? status : (status ? "ungueltig" : "");
  toolsLetztes = effektiv ? { status: effektiv, wallet: wallet || "" } : null;
  if (effektiv === "meine") toolsErgebnis(wallet || "", "meine");
  else if (effektiv === "fremd") toolsErgebnis(t("tools.notMine"), "fremd");
  else if (effektiv === "keine_wallets") toolsErgebnis(t("tools.noWallets"), "hinweis");
  else if (effektiv === "checking") toolsErgebnis(t("tools.checking"), "hinweis");
  else if (effektiv === "ungueltig") toolsErgebnis(t("tools.invalid"), "hinweis");
  else toolsErgebnis("", "");
}

async function pruefeIstDieMeine() {
  const feld = $("#tools-adresse");
  const knopf = $("#tools-meine");
  if (!feld || !knopf) return;
  const adresse = (feld.value || "").trim();
  const lauf = ++toolsPruefLauf;
  if (!adresse) {
    zeichneToolsStatus("ungueltig");
    feld.focus();
    return;
  }
  knopf.disabled = true;
  zeichneToolsStatus("checking");
  try {
    const daten = await api("/tools/adresse", {
      methode: "POST",
      daten: { address: adresse },
    });
    if (lauf !== toolsPruefLauf) return;
    zeichneToolsStatus(daten.status, daten.wallet);
  } catch (fehler) {
    if (lauf !== toolsPruefLauf) return;
    toolsLetztes = null;
    toolsErgebnis((fehler && fehler.message) || t("common.netError"), "hinweis");
  } finally {
    if (lauf === toolsPruefLauf) knopf.disabled = false;
  }
}

function bindeTools() {
  const knopf = $("#tools-meine");
  const feld = $("#tools-adresse");
  if (!knopf || !feld || knopf.dataset.gebunden) return;
  knopf.dataset.gebunden = "1";
  knopf.addEventListener("click", pruefeIstDieMeine);
  feld.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    pruefeIstDieMeine();
  });
}

bindeTools();
window.addEventListener("satsage:lang", () => {
  if (!toolsLetztes) return;
  zeichneToolsStatus(toolsLetztes.status, toolsLetztes.wallet);
});
