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
    || status === "keine_wallets" || status === "checking"
    || status === "preparing" || status === "ungueltig";
  const effektiv = bekannt ? status : (status ? "ungueltig" : "");
  toolsLetztes = effektiv ? { status: effektiv, wallet: wallet || "" } : null;
  if (effektiv === "meine") toolsErgebnis(wallet || "", "meine");
  else if (effektiv === "fremd") toolsErgebnis(t("tools.notMine"), "fremd");
  else if (effektiv === "keine_wallets") toolsErgebnis(t("tools.noWallets"), "hinweis");
  else if (effektiv === "checking") toolsErgebnis(t("tools.checking"), "hinweis");
  else if (effektiv === "preparing") toolsErgebnis(t("tools.preparing"), "hinweis");
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
  if (Zustand.contextBereit === false) {
    zeichneToolsStatus("preparing");
    knopf.disabled = false;
    return;
  }
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
    const status = fehler && fehler.status;
    if (status === 409) {
      zeichneToolsStatus("preparing");
      return;
    }
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
  zeichneSchatzListe(schatzFunde);
  zeichneCacheListe(cacheTreffer);
  fuelleSchatzWallets();
});

let schatzJobId = null;
let schatzTimer = null;
let schatzLogStand = { index: 0, knoten: [], texte: [] };
let schatzFunde = [];
let schatzListeAnzeigen = false;

function scantxoutsetVerbunden() {
  const qs = Zustand.config?.sources || [];
  const utxo = qs.find((q) => q.key === "own_utxo_core");
  const core = qs.find((q) => q.key === "own_core");
  // Dieselbe Wahl wie der Server: eigener UTXO-Slot, sonst Lookup-Core.
  if (utxo && utxo.configured) return utxo.reachable === true;
  return Boolean(core && core.reachable === true);
}

function fuelleSchatzWallets() {
  const wahl = $("#tools-schatz-wallet");
  if (!wahl) return;
  const bisher = wahl.value || "*";
  const wallets = (Zustand.config && Zustand.config.wallets) || [];
  wahl.replaceChildren();
  const alle = document.createElement("option");
  alle.value = "*";
  alle.textContent = t("tools.treasureAll");
  wahl.append(alle);
  for (const wallet of wallets) {
    if (!wallet || !wallet.id) continue;
    const option = document.createElement("option");
    option.value = wallet.id;
    option.textContent = wallet.name || wallet.id;
    wahl.append(option);
  }
  wahl.value = [...wahl.options].some((o) => o.value === bisher) ? bisher : "*";
  wahl.disabled = Boolean(schatzJobId);
}

function aktualisiereSchatzKnopf() {
  const knopf = $("#tools-schatz");
  if (!knopf) return;
  const laeuft = Boolean(schatzJobId);
  // Aktiv lassen: die Suche ist fertig. Ob Core scantxoutset kann, prüft
  // der Start — ein grauer Knopf bei noch unbekannter Quelle wäre eine Sackgasse.
  knopf.disabled = laeuft;
  knopf.title = laeuft ? t("tools.treasureRunning") : t("tools.treasureTitle");
  const wahl = $("#tools-schatz-wallet");
  if (wahl) wahl.disabled = laeuft;
}

function schatzStatus(text) {
  const el = $("#tools-schatz-status");
  if (!el) return;
  setzeText(el, text || "");
  el.hidden = !text;
}

function leereSchatzListe() {
  schatzListeAnzeigen = false;
  schatzFunde = [];
  const liste = $("#tools-schatz-liste");
  if (liste) {
    liste.replaceChildren();
    liste.hidden = true;
  }
  schatzStatus("");
}

function zeichneSchatzListe(funde) {
  const liste = $("#tools-schatz-liste");
  if (!liste) return;
  liste.replaceChildren();
  if (!schatzListeAnzeigen || Zustand.ansicht !== "tools" || !funde || !funde.length) {
    liste.hidden = true;
    return;
  }
  for (const fund of funde) {
    const li = document.createElement("li");
    const kette = Number(fund.chain) === 0
      ? t("tools.chainReceive")
      : t("tools.chainChange");
    li.textContent = t("tools.treasureItem", {
      amount: formatSats(fund.sats),
      wallet: fund.wallet || "",
      chain: kette,
      index: fund.index,
      until: Math.max(0, Number(fund.fenster_bis) - 1),
      address: kuerze(fund.address || ""),
    });
    liste.append(li);
  }
  liste.hidden = false;
}

function schatzPollStop() {
  if (schatzTimer) clearInterval(schatzTimer);
  schatzTimer = null;
  schatzJobId = null;
  aktualisiereSchatzKnopf();
}

async function pruefeSchatzJob() {
  if (!schatzJobId) return;
  try {
    const job = await api("/jobs/" + schatzJobId);
    nimmLogZeilen(job, schatzLogStand);
    if (job.running) {
      schatzStatus(job.message || t("tools.treasureRunning"));
      return;
    }
    const funde = (job.result && job.result.funde) || [];
    if (job.status === "done" && funde.length) {
      const sats = Math.max(
        500,
        Number(job.result && job.result.sats) || 0,
      );
      if (typeof EmpfangPuls !== "undefined" && EmpfangPuls.flashOrangeB) {
        EmpfangPuls.flashOrangeB(sats);
      }
    }
    if (schatzListeAnzeigen && Zustand.ansicht === "tools" && job.status === "done") {
      schatzFunde = funde;
      zeichneSchatzListe(funde);
      schatzStatus(funde.length ? "" : t("tools.treasureEmpty"));
    } else if (Zustand.ansicht === "tools" && job.status !== "done") {
      schatzStatus(job.error || job.message || t("tools.treasureEmpty"));
    } else {
      schatzStatus("");
    }
    schatzPollStop();
  } catch (fehler) {
    schatzStatus((fehler && fehler.message) || t("common.netError"));
    schatzPollStop();
  }
}

function bindeSchatzJob(id) {
  schatzJobId = id;
  schatzLogStand = { index: 0, knoten: [], texte: [] };
  aktualisiereSchatzKnopf();
  if (schatzTimer) clearInterval(schatzTimer);
  schatzTimer = setInterval(pruefeSchatzJob, 1000);
  pruefeSchatzJob();
}

async function starteSchatzsuche() {
  const knopf = $("#tools-schatz");
  if (!knopf || knopf.disabled) return;
  schatzListeAnzeigen = true;
  schatzFunde = [];
  zeichneSchatzListe([]);
  schatzStatus(t("tools.treasureRunning"));
  knopf.disabled = true;
  try {
    const wahl = $("#tools-schatz-wallet");
    const walletId = (wahl && wahl.value) || "*";
    const job = await api("/tools/schatzsuche", {
      methode: "POST",
      daten: { wallet_id: walletId },
    });
    bindeSchatzJob(job.id);
  } catch (fehler) {
    schatzStatus((fehler && fehler.message) || t("common.netError"));
    schatzPollStop();
  }
}

function merkeLaufendeSchatzsuche() {
  const jobs = Zustand.jobsNav?.jobs || [];
  const laufend = jobs.find((j) => j.kind === "schatzsuche" && j.running);
  if (!laufend || !laufend.id || schatzJobId) return;
  schatzListeAnzeigen = false;
  bindeSchatzJob(laufend.id);
}

let cacheJobId = null;
let cacheTimer = null;
let cacheLogStand = { index: 0, knoten: [], texte: [] };
let cacheTreffer = [];
let cacheListeAnzeigen = false;

function cacheKnopfStand() {
  const suche = $("#tools-cache");
  const abbruch = $("#tools-cache-abbruch");
  const laeuft = Boolean(cacheJobId);
  if (suche) suche.disabled = laeuft;
  if (abbruch) abbruch.hidden = !laeuft;
}

function cacheStatus(text) {
  const el = $("#tools-cache-status");
  if (!el) return;
  setzeText(el, text || "");
  el.hidden = !text;
}

function zeichneCacheListe(treffer) {
  const liste = $("#tools-cache-liste");
  if (!liste) return;
  liste.replaceChildren();
  if (!cacheListeAnzeigen || Zustand.ansicht !== "tools" || !treffer || !treffer.length) {
    liste.hidden = true;
    return;
  }
  for (const trefferEintrag of treffer) {
    const li = document.createElement("li");
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "knopf knopf-klein";
    const wo = trefferEintrag.spent || trefferEintrag.teil === "verlauf"
      ? t("tools.cacheSpent")
      : t("tools.cacheOpen");
    knopf.textContent = t("tools.cacheItem", {
      amount: formatSats(trefferEintrag.value_sats),
      wallet: trefferEintrag.wallet || "",
      wo,
      address: kuerze(trefferEintrag.address || trefferEintrag.key || ""),
    });
    knopf.addEventListener("click", () => oeffneCacheTreffer(trefferEintrag));
    li.append(knopf);
    liste.append(li);
  }
  liste.hidden = false;
}

function oeffneCacheTreffer(treffer) {
  const key = String(treffer.key || "");
  if (!key) return;
  if (treffer.teil === "verlauf" || treffer.spent) {
    if (typeof zeigeHerkunftFuer === "function") {
      zeigeHerkunftFuer(key, {
        meta: {
          key,
          wallet: treffer.wallet || "",
          value_sats: treffer.value_sats ?? null,
          address: treffer.address || "",
          time_label: treffer.time_label || "",
        },
      });
    }
    return;
  }
  if (treffer.wallet_id && typeof zeigeWallet === "function") {
    zeigeWallet(treffer.wallet_id).catch(() => {});
  }
}

function cachePollStop() {
  if (cacheTimer) clearInterval(cacheTimer);
  cacheTimer = null;
  cacheJobId = null;
  cacheKnopfStand();
}

async function pruefeCacheJob() {
  if (!cacheJobId) return;
  try {
    const job = await api("/jobs/" + cacheJobId);
    nimmLogZeilen(job, cacheLogStand);
    if (job.running) {
      cacheStatus(job.message || t("tools.cacheRunning"));
      return;
    }
    const treffer = (job.result && job.result.treffer) || [];
    if (cacheListeAnzeigen && Zustand.ansicht === "tools" && job.status === "done") {
      cacheTreffer = treffer;
      zeichneCacheListe(treffer);
      cacheStatus(treffer.length ? "" : t("tools.cacheEmpty"));
    } else if (Zustand.ansicht === "tools" && job.status !== "done") {
      cacheStatus(job.error || job.message || t("tools.cacheEmpty"));
    } else {
      cacheStatus("");
    }
    cachePollStop();
  } catch (fehler) {
    cacheStatus((fehler && fehler.message) || t("common.netError"));
    cachePollStop();
  }
}

function bindeCacheJob(id) {
  cacheJobId = id;
  cacheLogStand = { index: 0, knoten: [], texte: [] };
  cacheKnopfStand();
  if (cacheTimer) clearInterval(cacheTimer);
  cacheTimer = setInterval(pruefeCacheJob, 1000);
  pruefeCacheJob();
}

async function starteCacheSuche() {
  const feld = $("#tools-cache-q");
  const knopf = $("#tools-cache");
  if (!feld || !knopf || knopf.disabled) return;
  const roh = (feld.value || "").trim();
  if (!roh) {
    feld.focus();
    return;
  }
  cacheListeAnzeigen = true;
  cacheTreffer = [];
  zeichneCacheListe([]);
  cacheStatus(t("tools.cacheRunning"));
  knopf.disabled = true;
  const daten = { q: roh, lang: uiSprache() };
  if (typeof parseKopfFilter === "function") {
    const f = parseKopfFilter(roh);
    if (f.afterTs != null) daten.q_nach = f.afterTs;
    if (f.beforeTs != null) daten.q_vor = f.beforeTs;
  }
  try {
    const job = await api("/tools/cache-suche", { methode: "POST", daten });
    bindeCacheJob(job.id);
  } catch (fehler) {
    cacheStatus((fehler && fehler.message) || t("common.netError"));
    cachePollStop();
  }
}

async function brichCacheSucheAb() {
  if (!cacheJobId) return;
  try {
    await api("/jobs/" + cacheJobId, { methode: "DELETE" });
  } catch (_) { /* Poll zeigt den Stand */ }
}

function merkeLaufendeCacheSuche() {
  const jobs = Zustand.jobsNav?.jobs || [];
  const laufend = jobs.find((j) => j.kind === "cache_suche" && j.running);
  if (!laufend || !laufend.id || cacheJobId) return;
  cacheListeAnzeigen = false;
  bindeCacheJob(laufend.id);
}

function bindeCacheSuche() {
  const knopf = $("#tools-cache");
  const feld = $("#tools-cache-q");
  const abbruch = $("#tools-cache-abbruch");
  if (!knopf || !feld || knopf.dataset.gebunden) return;
  knopf.dataset.gebunden = "1";
  knopf.addEventListener("click", starteCacheSuche);
  feld.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    starteCacheSuche();
  });
  if (abbruch) abbruch.addEventListener("click", brichCacheSucheAb);
  cacheKnopfStand();
}

bindeCacheSuche();

function bindeSchatzKnopf() {
  const knopf = $("#tools-schatz");
  if (!knopf || knopf.dataset.gebunden) return;
  knopf.dataset.gebunden = "1";
  knopf.addEventListener("click", starteSchatzsuche);
  fuelleSchatzWallets();
  aktualisiereSchatzKnopf();
}

bindeSchatzKnopf();
