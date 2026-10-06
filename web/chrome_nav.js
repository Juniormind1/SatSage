/** Chrome-Navigation / Job-Nav — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: Globals aus app.js (Zustand, api, t, $, …).
 * Kein import/export. Laden nach view-Scripts, vor chrome.js / boot.js.
 */

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

/**
 * Ein Wallet, sobald sein Cache gelesen ist — nicht erst mit dem letzten.
 * Reihenfolge bleibt die der Konfiguration. Der Cache-Stand (UTXO-Zahl,
 * Frische) kommt mit „Cache gelesen.“ und ersetzt den Platzhalter.
 */
function nimmWalletSobaldFertig(wallet) {
  if (!wallet || !wallet.id) return;
  // Stand kommt aus dem Start-Log, /api/config steht evtl. noch aus: Der
  // Start läuft. Ein Klick jetzt holt den Mempool-Abgleich erst danach.
  if (Zustand.contextBereit === undefined) Zustand.contextBereit = false;
  if (!Zustand.config) Zustand.config = {};
  const liste = Zustand.config.wallets || [];
  const da = liste.findIndex((w) => w.id === wallet.id);
  if (da >= 0) liste[da] = { ...liste[da], ...wallet };
  else liste.push(wallet);
  Zustand.config.wallets = liste;
  if (!Array.isArray(Zustand.entwurf) || !Zustand.entwurf.length) {
    Zustand.entwurf = liste.map((w) => ({ ...w }));
  }
  zeichneNav();
  if (
    Zustand.ansicht === "wallet"
    && !Zustand.walletId
    && liste.length === 1
    && typeof zeigeWallet === "function"
  ) {
    zeigeWallet(wallet.id, { ohneEmpfang: true });
  }
}

/**
 * Wallet für den Einstieg nach /api/config: das erste der Konfiguration.
 * Hat der Nutzer während der Vorbereitung schon ein Wallet geöffnet, bleibt
 * es stehen (null) — der Start holt ihn nicht zum ersten zurück.
 */
function einstiegsWalletId() {
  const liste = Zustand.config?.wallets || [];
  if (!liste.length) return null;
  if (Zustand.walletId && liste.some((w) => w.id === Zustand.walletId)) return null;
  return liste[0].id;
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
    "steuerjahr", "trace", "sanktionen", "tools",
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
  "wallet", "steuerjahr", "trace", "sanktionen", "tools",
  "wallets", "einstellungen", "datenquellen",
];


function zeigeAnsicht(name) {
  if ((name === "wallets" && walletsManaged()) || (name === "datenquellen" && sourcesFullyManaged())) name = "einstellungen";
  if (Zustand.ansicht === "tools" && name !== "tools" && typeof leereSchatzListe === "function") {
    leereSchatzListe();
  }
  // Ansichtswechsel beendet den Herkunftsnetz-Overlay im Steuerjahr.
  if (typeof herkunftsnetzBeenden === "function") herkunftsnetzBeenden();
  Zustand.ansicht = name;
  for (const ansicht of ANSICHTEN) {
    const el = $(`#ansicht-${ansicht}`);
    if (el) el.hidden = ansicht !== name;
  }
  zeichneNav();
  aktualisiereKopfFilterFuerAnsicht();
  if (typeof schliesseNavWennUngepinnt === "function") schliesseNavWennUngepinnt();
}

function setzeEnvPfad(pfad) {
  const text = pfad || ".env";
  for (const span of document.querySelectorAll(".env-pfad")) {
    span.textContent = text;
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

/** Wallet-Watch-Zeilen aus dem Jobs-Poll ins Web-Log (Reconnect, Subscribe, …). */
function nimmWalletWatchLog(daten) {
  const zeilen = daten && daten.wallet_watch && daten.wallet_watch.log;
  if (!Array.isArray(zeilen) || !zeilen.length) return;
  let seqStand = Number(Zustand.watchLogSeq) || 0;
  for (const eintrag of zeilen) {
    const seq = Number(eintrag && eintrag.seq);
    const text = String((eintrag && eintrag.text) || "").trim();
    if (!Number.isFinite(seq) || seq <= seqStand || !text) continue;
    seqStand = seq;
    logZeile(text);
  }
  Zustand.watchLogSeq = seqStand;
}

/** Fallback, falls der Start-Strom die Zeile noch nicht gezeigt hat. */
function nimmBootLogAusJobs(daten) {
  // Der Live-Strom schreibt dieselben Zeilen schon. Nur ohne ihn nachziehen.
  if (Zustand.bootLogLive) return;
  const job = (daten.jobs || []).find((j) => j && j.kind === "wallet_context");
  if (!job || !Array.isArray(job.log)) return;
  if (!Zustand.bootLogStand) Zustand.bootLogStand = { index: 0 };
  const namen = job.log_wallets || [];
  const stand = Zustand.bootLogStand;
  for (; stand.index < job.log.length; stand.index += 1) {
    logZeile(job.log[stand.index], undefined, namen[stand.index] || "");
  }
}

async function ladeJobsNav() {
  try {
    const daten = await api("/jobs?recent_s=3");
    if (typeof daten.context_bereit === "boolean") {
      const war = Zustand.contextBereit;
      Zustand.contextBereit = daten.context_bereit;
      if (war === false && daten.context_bereit) {
        if (Zustand.walletId) ladeEmpfang(Zustand.walletId).catch(() => {});
        else zeichneEmpfangLeer();
        if (typeof holeWalletMempoolNachStart === "function") holeWalletMempoolNachStart();
      }
    }
    Zustand.jobsNav = {
      jobs: daten.jobs || [],
      scan_pipeline: daten.scan_pipeline || { current: null, queued: [] },
    };
    Zustand.jobsNavFehler = "";
    nimmBlockEvent(daten);
    nimmBootLogAusJobs(daten);
    nimmWalletWatchLog(daten);
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
  // QR-Atem an jeden laufenden Scan hängen, und nach dem Ende wieder lösen.
  // Läuft der Atem schon, nicht neu anstoßen — sonst setzt der 2s-Takt den Takt zurück.
  if (typeof empfangScanLaeuftFuer === "function") {
    const scanWid = Zustand.walletId || "";
    const atmetSchon = Boolean(Zustand.empfang && Zustand.empfang.puls)
      && typeof EmpfangPuls !== "undefined"
      && EmpfangPuls.laeuft();
    if (empfangScanLaeuftFuer(scanWid)) {
      if (!atmetSchon) stoesseEmpfangScanPuls();
    } else if (
      Zustand.walletId
      && Zustand.empfang
      && Zustand.empfang.puls
    ) {
      ladeEmpfang(Zustand.walletId).catch(() => {});
    }
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
  // Rohe Job-Meldung liegt in Zustand.scanSchritt. Der Leistentext nicht
  // zurückgeben — sonst bleibt „läuft für …“ stehen, obwohl das Wallet offen ist.
  aktualisiereScanAnzeige();
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
  if (kind === "schatzsuche" || kind === "cache_suche") return true;
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
  if (kind === "schatzsuche" || kind === "cache_suche") {
    zeigeAnsicht("tools");
    if (kind === "schatzsuche" && typeof merkeLaufendeSchatzsuche === "function") {
      merkeLaufendeSchatzsuche();
    }
    if (kind === "cache_suche" && typeof merkeLaufendeCacheSuche === "function") {
      merkeLaufendeCacheSuche();
    }
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
  Zustand.verlaufAlleLaeuft = true;
  stoesseEmpfangScanPuls();

  let jobId = null;
  let timer = null;
  const logStand = { index: 0 };

  const fertig = async (meldung, art) => {
    clearInterval(timer);
    Zustand.verlaufAlleLaeuft = false;
    merkeScanJobBeendet(jobId);
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
    loeseEmpfangScanPuls();
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


// ---------------------------------------------------------------------------
// Kompakte Navigation: Pillen umgebrochen → Overlay am linken Rand, pinbar
// ---------------------------------------------------------------------------

const NAV_PIN_MERKER = "satsage-nav-pin";
let navKompaktGebunden = false;
let navHoverTimer = 0;
let navBeobachter = null;

function navPinGemerkt() {
  try {
    return localStorage.getItem(NAV_PIN_MERKER) === "1";
  } catch (_) {
    return false;
  }
}

function merkeNavPin(an) {
  try {
    localStorage.setItem(NAV_PIN_MERKER, an ? "1" : "0");
  } catch (_) {
    /* ohne Speicher bleibt die Sitzung */
  }
}

function navInEinbettung() {
  try {
    return window.self !== window.top;
  } catch (_) {
    return true;
  }
}

function navKompaktErzwungen() {
  // Start9-Dienst-UI und jedes iframe (StartOS/Specter/Umbrel) haben wenig Breite.
  if (navInEinbettung()) return true;
  return Zustand.config?.managed_by === "start9";
}

function kopfPillenUmgebrochen() {
  const app = document.getElementById("app");
  const kopf = document.querySelector(".kopf");
  const pillen = document.getElementById("quelle-pillen");
  if (!app || app.hidden || !kopf || !pillen) return false;
  const sichtbare = Array.from(pillen.children).filter(
    (el) => el.getClientRects().length > 0,
  );
  if (sichtbare.length >= 2) {
    const oben = sichtbare[0].getBoundingClientRect().top;
    const unten = sichtbare[sichtbare.length - 1].getBoundingClientRect().top;
    if (unten - oben > 8) return true;
  }
  const start = kopf.querySelector(".kopf-start") || kopf.querySelector(".marke");
  const quelle = kopf.querySelector(".quelle");
  if (start && quelle) {
    if (quelle.getBoundingClientRect().top - start.getBoundingClientRect().top > 8) {
      return true;
    }
  }
  return kopf.scrollHeight - kopf.clientHeight > 6;
}

function navIstOffen() {
  const app = document.getElementById("app");
  return Boolean(app && app.classList.contains("nav-offen"));
}

function navIstGepinnt() {
  const app = document.getElementById("app");
  return Boolean(app && app.classList.contains("nav-gepinnt"));
}

function navIstKompakt() {
  const app = document.getElementById("app");
  return Boolean(app && app.classList.contains("nav-kompakt"));
}

function setzeNavOffen(an) {
  const app = document.getElementById("app");
  if (!app) return;
  app.classList.toggle("nav-offen", Boolean(an));
  aktualisiereNavWerkzeuge();
}

function setzeNavPin(an) {
  const app = document.getElementById("app");
  if (!app) return;
  const pin = Boolean(an);
  app.classList.toggle("nav-gepinnt", pin);
  merkeNavPin(pin);
  if (pin) app.classList.add("nav-offen");
  aktualisiereNavKompakt();
}

function aktualisiereNavWerkzeuge() {
  const toggle = document.getElementById("nav-toggle");
  const pin = document.getElementById("nav-pin");
  const rand = document.getElementById("nav-rand");
  const kompakt = navIstKompakt();
  const offen = navIstOffen() || navIstGepinnt();
  const gepinnt = navIstGepinnt();
  if (toggle) {
    toggle.hidden = !kompakt;
    toggle.setAttribute("aria-expanded", offen ? "true" : "false");
    toggle.tabIndex = kompakt ? 0 : -1;
    const titel = offen ? t("nav.toggleHideTitle") : t("nav.toggleTitle");
    toggle.title = titel;
    toggle.setAttribute("aria-label", t("nav.toggleAria"));
    toggle.setAttribute("data-i18n-title", offen ? "nav.toggleHideTitle" : "nav.toggleTitle");
  }
  if (pin) {
    pin.setAttribute("aria-pressed", gepinnt ? "true" : "false");
    pin.title = gepinnt ? t("nav.unpinTitle") : t("nav.pinTitle");
    pin.setAttribute("aria-label", gepinnt ? t("nav.unpinAria") : t("nav.pinAria"));
    pin.setAttribute("data-i18n-title", gepinnt ? "nav.unpinTitle" : "nav.pinTitle");
    pin.setAttribute("data-i18n-aria-label", gepinnt ? "nav.unpinAria" : "nav.pinAria");
  }
  if (rand) {
    rand.hidden = !kompakt || gepinnt;
  }
}

function aktualisiereNavKompakt() {
  const app = document.getElementById("app");
  if (!app || app.hidden) return;
  const umbruch = kopfPillenUmgebrochen();
  const gepinnt = navPinGemerkt();
  app.classList.toggle("nav-gepinnt", gepinnt);
  const kompakt = umbruch || navKompaktErzwungen();
  app.classList.toggle("nav-kompakt", kompakt);
  if (!kompakt) {
    app.classList.remove("nav-offen");
  } else if (gepinnt) {
    app.classList.add("nav-offen");
  }
  aktualisiereNavWerkzeuge();
}

function schliesseNavWennUngepinnt() {
  if (!navIstKompakt() || navIstGepinnt()) return;
  setzeNavOffen(false);
}

function navZeigerUeberLeiste(ziel) {
  if (!ziel || typeof ziel.closest !== "function") return false;
  return Boolean(
    ziel.closest("#seitenleiste")
    || ziel.closest("#nav-toggle")
    || ziel.closest("#nav-rand")
    || ziel.closest("#nav-pin"),
  );
}

function bindeNavLeiste() {
  if (navKompaktGebunden) {
    aktualisiereNavKompakt();
    return;
  }
  navKompaktGebunden = true;
  const app = document.getElementById("app");
  const toggle = document.getElementById("nav-toggle");
  const pin = document.getElementById("nav-pin");
  const rand = document.getElementById("nav-rand");
  const leiste = document.getElementById("seitenleiste");
  const kopf = document.querySelector(".kopf");
  const pillen = document.getElementById("quelle-pillen");

  if (toggle) {
    toggle.addEventListener("click", () => {
      if (!navIstKompakt()) return;
      if (navIstGepinnt()) {
        setzeNavPin(false);
        setzeNavOffen(false);
        return;
      }
      setzeNavOffen(!navIstOffen());
    });
  }
  if (pin) {
    pin.addEventListener("click", () => {
      setzeNavPin(!navIstGepinnt());
    });
  }

  const navHatFokus = () => navZeigerUeberLeiste(document.activeElement);
  const hoverAn = () => {
    if (!navIstKompakt() || navIstGepinnt()) return;
    window.clearTimeout(navHoverTimer);
    setzeNavOffen(true);
  };
  const hoverAus = () => {
    if (!navIstKompakt() || navIstGepinnt()) return;
    window.clearTimeout(navHoverTimer);
    navHoverTimer = window.setTimeout(() => {
      if (navIstGepinnt() || navHatFokus()) return;
      setzeNavOffen(false);
    }, 280);
  };
  if (rand) {
    rand.addEventListener("pointerenter", hoverAn);
    rand.addEventListener("pointerleave", hoverAus);
  }
  if (leiste) {
    leiste.addEventListener("pointerenter", hoverAn);
    leiste.addEventListener("pointerleave", hoverAus);
    leiste.addEventListener("focusin", hoverAn);
    leiste.addEventListener("focusout", hoverAus);
  }
  if (toggle) {
    toggle.addEventListener("focus", hoverAn);
  }

  document.addEventListener("pointerdown", (ereignis) => {
    if (!navIstKompakt() || navIstGepinnt() || !navIstOffen()) return;
    if (navZeigerUeberLeiste(ereignis.target)) return;
    setzeNavOffen(false);
  });
  document.addEventListener("keydown", (ereignis) => {
    if (ereignis.key !== "Escape") return;
    if (!navIstKompakt() || navIstGepinnt() || !navIstOffen()) return;
    setzeNavOffen(false);
  });

  if (typeof ResizeObserver === "function") {
    navBeobachter = new ResizeObserver(() => aktualisiereNavKompakt());
    if (kopf) navBeobachter.observe(kopf);
    if (pillen) navBeobachter.observe(pillen);
    if (app) navBeobachter.observe(app);
  }
  window.addEventListener("resize", () => aktualisiereNavKompakt());
  aktualisiereNavKompakt();
}
