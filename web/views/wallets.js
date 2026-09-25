/** Wallets-/UTXO-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: nutzt Globals aus app.js (Zustand, api, t, $, …).
 * Kein import/export. Laden: nach app.js, vor herkunft.js (herkunft ruft
 * zeigeWallet / setzeUtxoTraceDaten / herkunftTiefLaeuftFuer auf).
 */

/* --- empfang-lernstoff --- */
function zeichneEmpfangLernstoff(thema) {
  if (!thema || !thema.url) return;
  EmpfangPuls.stop();
  // Flüchtigkeit: Empfangsadresse entwerten, bevor Lern-QR erscheint.
  const leer = $("#empfang-leer");
  const inhalt = $("#empfang-inhalt");
  if (leer) leer.hidden = true;
  if (!inhalt) return;
  inhalt.hidden = false;
  const pane = $("#empfang-pane");
  if (pane) {
    pane.classList.add("empfang-pane--lern");
    pane.classList.remove("empfang-pane--puls");
  }

  const qr = $("#empfang-qr");
  if (qr) {
    const svg = empfangQrSvg(thema.url);
    qr.replaceChildren();
    if (svg) qr.insertAdjacentHTML("afterbegin", svg);
    qr.title = t("dock.empfangLernClick");
    qr.classList.add("kopierbar");
    qr.classList.remove("empfang-qr--puls");
  }
  setzeText(
    $("#empfang-wallet"),
    t("dock.empfangLernstoff", { topic: thema.stichwort || thema.id }),
  );
  const adresse = $("#empfang-adresse");
  if (adresse) {
    adresse.replaceChildren();
    adresse.textContent = thema.url;
    adresse.title = t("dock.empfangLernClick");
    adresse.classList.add("kopierbar");
  }
  setzeText($("#empfang-index"), "");
  setzeText($("#empfang-quelle"), thema.titel || "");
  const zurueck = $("#empfang-lern-zurueck");
  if (zurueck) zurueck.hidden = false;
  Zustand.empfang = {
    wallet_id: Zustand.walletId,
    address: "",
    index: 0,
    lern: true,
    url: thema.url,
  };
}

/* --- empfang-core --- */
function empfangAnimDebugAn() {
  try {
    return new URLSearchParams(location.search).get("animdebug") === "1"
      || localStorage.getItem("empfangAnimDebug") === "1";
  } catch (_) {
    return false;
  }
}

function stoppeEmpfangPoll() {
  if (Zustand.empfangTimer) {
    clearInterval(Zustand.empfangTimer);
    Zustand.empfangTimer = null;
  }
}

function setzeEmpfangPoll() {
  stoppeEmpfangPoll();
  // Bei Animations-Debug keinen Empfangs-Poll — sonst überschreibt er die Demos.
  if (empfangAnimDebugAn()) return;
  Zustand.empfangTimer = setInterval(() => {
    const pane = $("#empfang-pane");
    if (!pane || pane.offsetParent === null) return;
    if (!Zustand.walletId) return;
    ladeEmpfang(Zustand.walletId, { still: true }).catch(() => {});
  }, EMPFANG_POLL_MS);
}

function zeichneEmpfangLeer(text, { puls = false } = {}) {
  // Puls weiterlaufen lassen, wenn wir ohnehin wieder atmen sollen.
  if (!puls) EmpfangPuls.stop();
  const leer = $("#empfang-leer");
  const inhalt = $("#empfang-inhalt");
  if (!puls) {
    const qr = $("#empfang-qr");
    if (qr) {
      qr.replaceChildren();
      qr.removeAttribute("title");
      qr.classList.remove("empfang-qr--puls");
    }
  }
  const adresse = $("#empfang-adresse");
  if (adresse) {
    adresse.replaceChildren();
    adresse.textContent = "";
    adresse.removeAttribute("title");
    adresse.classList.remove("kopierbar", "kopierbar-ok", "kopierbar-fehl");
  }
  if (!puls) {
    setzeText($("#empfang-wallet"), "");
    setzeText($("#empfang-index"), "");
    const quelle = $("#empfang-quelle");
    if (quelle) {
      quelle.textContent = "";
      quelle.classList.remove("empfang-quelle--warn");
      quelle.removeAttribute("title");
    }
  }
  const hinweis = $("#empfang-hinweis");
  if (hinweis) {
    hinweis.hidden = true;
    hinweis.textContent = "";
    hinweis.classList.remove("empfang-hinweis--warn");
  }
  const zurueck = $("#empfang-lern-zurueck");
  if (zurueck) zurueck.hidden = true;
  const pane = $("#empfang-pane");
  if (pane && !puls) {
    pane.classList.remove("empfang-pane--lern", "empfang-pane--puls");
  }
  Zustand.empfang = null;

  if (puls) {
    EmpfangPuls.start();
    return;
  }
  if (leer) {
    leer.hidden = false;
    leer.textContent = text || t("dock.empfangEmpty");
  }
  if (inhalt) inhalt.hidden = true;
}

function zeichneEmpfangReadOnly(walletName, { puls = false } = {}) {
  // Während Tip/Scan: Atem statt statischem „Read-only“ — der Bestand
  // läuft noch, auch wenn kein QR kommt.
  const text = puls
    ? t("dock.empfangSyncing")
    : t("dock.empfangReadOnly");
  zeichneEmpfangLeer(text, { puls });
  const leer = $("#empfang-leer");
  if (leer && !puls && walletName) {
    leer.textContent = t("dock.empfangReadOnly");
  }
}

/**
 * Empfangspanel im „beschäftigt“-Zustand: QR weg, Atem an.
 * Gilt für UTXO-Scan, Historie, Tip-Nachzug, Herkunft und die
 * Sammel-Jobs Historien / Herkünfte UTXOs — auch Read-only-Wallets.
 */
function zeichneEmpfangBeschaeftigt(walletId) {
  const walletMeta = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  Zustand.lernThema = null;
  if (walletMeta && walletMeta.read_only) {
    zeichneEmpfangReadOnly(walletMeta.name, { puls: true });
  } else {
    zeichneEmpfangLeer(t("dock.empfangPuls"), { puls: true });
  }
  Zustand.empfang = {
    wallet_id: walletId || "",
    address: "",
    index: 0,
    puls: true,
  };
}

function empfangSonderAtemLaeuft() {
  if (typeof EmpfangPuls === "undefined") return false;
  if (EmpfangPuls.istIncoming && EmpfangPuls.istIncoming()) return true;
  if (EmpfangPuls.istOrangeB && EmpfangPuls.istOrangeB()) return true;
  return false;
}

function zeichneEmpfang(daten, { zahlung = false } = {}) {
  // Konfetti/Incoming oder Orange-₿ (UTXO-Fund): QR merken, Animation nicht killen.
  if (empfangSonderAtemLaeuft()) {
    Zustand._empfangNachIncoming = { daten, zahlung: Boolean(zahlung) };
    if (daten && daten.wallet_id) {
      Zustand.empfangByWallet[daten.wallet_id] = daten;
    }
    return;
  }
  EmpfangPuls.stop();
  if (daten && daten.read_only) {
    zeichneEmpfangReadOnly(daten.wallet_name);
    Zustand.empfang = {
      wallet_id: daten.wallet_id,
      address: "",
      index: daten.index,
      read_only: true,
    };
    if (daten.wallet_id) {
      Zustand.empfangByWallet[daten.wallet_id] = daten;
    }
    return;
  }

  const leer = $("#empfang-leer");
  const inhalt = $("#empfang-inhalt");
  if (!inhalt) return;
  if (leer) leer.hidden = true;
  inhalt.hidden = false;
  const pane = $("#empfang-pane");
  if (pane) pane.classList.remove("empfang-pane--lern", "empfang-pane--puls");
  const zurueck = $("#empfang-lern-zurueck");
  if (zurueck) zurueck.hidden = true;

  const qr = $("#empfang-qr");
  if (qr) {
    const svg = empfangQrSvg(daten.address);
    qr.replaceChildren();
    if (svg) {
      qr.insertAdjacentHTML("afterbegin", svg);
    } else {
      qr.textContent = t("dock.empfangQrFehlt");
    }
  }

  setzeText($("#empfang-wallet"), daten.wallet_name || "");
  const adresse = $("#empfang-adresse");
  if (adresse) {
    adresse.replaceChildren();
    const kurz = String(daten.address || "");
    adresse.textContent = kurz;
    macheKopierbar(adresse, kurz, "Adresse");
  }
  setzeText(
    $("#empfang-index"),
    t("dock.empfangIndex", { n: daten.index }),
  );
  setzeEmpfangQuelle(daten.source);

  // Cache-Warnung nur in #empfang-quelle (setzeEmpfangQuelle) — nicht noch
  // einmal in #empfang-hinweis (war doppelte Zeile „Schätzung aus Cache …“).
  const hinweis = $("#empfang-hinweis");
  if (hinweis) {
    if (zahlung) {
      hinweis.hidden = false;
      hinweis.textContent = t("dock.empfangZahlung");
      hinweis.classList.remove("empfang-hinweis--warn");
    } else if (!hinweis.hidden && Zustand.empfang?.address === daten.address) {
      /* Zahlungshinweis bleibt kurz stehen, bis Adresse wechselt */
    } else {
      hinweis.hidden = true;
      hinweis.textContent = "";
      hinweis.classList.remove("empfang-hinweis--warn");
    }
  }
  Zustand.empfang = {
    wallet_id: daten.wallet_id,
    address: daten.address,
    index: daten.index,
    read_only: false,
  };
  if (daten.wallet_id) {
    Zustand.empfangByWallet[daten.wallet_id] = daten;
  }
}

/** Tip-/Start-Aktualisierung betrifft dieses Wallet. */
function tipSyncLaeuftFuer(walletId) {
  if (!walletId) return false;
  return walletSyncLaeuftFuer(walletId);
}

function jobIstAktiv(job) {
  if (!job) return false;
  return Boolean(
    job.running
    || job.status === "running"
    || job.status === "queued"
    || job.queue_status === "queued",
  );
}

/**
 * Scan über alle Wallets: Steuerjahr „Historien“ und Massen-Herkunft
 * („Herkünfte UTXOs“ / klären). Atem unabhängig vom gerade offenen Wallet.
 */
function empfangGlobalerScanLaeuft() {
  if (Zustand.contextBereit === false) return true;
  if (Zustand.herkunftAlleLaeuft || Zustand.verlaufAlleLaeuft) return true;
  const jobs = Zustand.jobsNav?.jobs || [];
  return jobs.some((job) => {
    if (!jobIstAktiv(job) || job.meta?.still) return false;
    if (job.kind === "trace-alle") return true;
    return job.kind === "verlauf" && Boolean(job.meta?.alle);
  });
}

/**
 * Empfang noch unsicher: UTXO-Scan, Historie, Tip-Nachzug, Wallet-Herkunft
 * oder ein globaler Scan (Historien / Herkünfte UTXOs).
 */
function empfangScanLaeuftFuer(walletId) {
  if (empfangGlobalerScanLaeuft()) return true;
  if (!walletId) return false;
  if (
    Zustand.herkunftTiefWalletId
    && String(Zustand.herkunftTiefWalletId) === String(walletId)
  ) {
    return true;
  }
  if (herkunftTiefLaeuftFuer(walletId)) return true;
  if (
    Zustand.rescanJob
    && Zustand.scanWalletId === walletId
    && (Zustand.scanArt === "utxo" || Zustand.scanArt === "verlauf")
  ) {
    return true;
  }
  return tipSyncLaeuftFuer(walletId);
}

/** QR-Atem an, solange für das offene Wallet (oder global) ein Scan läuft. */
function stoesseEmpfangScanPuls() {
  if (empfangSonderAtemLaeuft()) return;
  const wid = Zustand.walletId || "";
  if (!empfangScanLaeuftFuer(wid)) return;
  zeichneEmpfangBeschaeftigt(wid);
}

/** Job in der Nav nicht mehr als laufend führen, damit der QR-Atem endet. */
function merkeScanJobBeendet(jobId) {
  if (!jobId) return;
  const jobs = Zustand.jobsNav?.jobs || [];
  for (const job of jobs) {
    if (!job || job.id !== jobId) continue;
    job.running = false;
    if (job.status === "running" || job.status === "queued") job.status = "done";
  }
  const cur = Zustand.jobsNav?.scan_pipeline?.current;
  if (cur && cur.job_id === jobId) {
    Zustand.jobsNav.scan_pipeline.current = null;
  }
}

/** Atem aus und Empfangsadresse zurück, sobald kein Scan mehr läuft. */
function loeseEmpfangScanPuls() {
  if (empfangSonderAtemLaeuft()) return;
  const wid = Zustand.walletId || "";
  if (empfangScanLaeuftFuer(wid)) return;
  const atmet = Boolean(Zustand.empfang && Zustand.empfang.puls)
    || (typeof EmpfangPuls !== "undefined" && EmpfangPuls.laeuft());
  if (!atmet) return;
  if (wid) {
    ladeEmpfang(wid).catch(() => {});
    return;
  }
  if (typeof EmpfangPuls !== "undefined") EmpfangPuls.stop();
}

async function ladeEmpfang(walletId, { still = false } = {}) {
  if (Zustand.contextBereit === false) {
    zeichneEmpfangLeer(t("dock.empfangPuls"), { puls: true });
    return null;
  }
  if (!walletId) {
    zeichneEmpfangLeer();
    return null;
  }

  const walletMeta = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  const scanLaeuft = empfangScanLaeuftFuer(walletId);

  // TxIN/Orange-₿: weder Poll noch zeigeWallet darf QR/Animation ersetzen.
  if (empfangSonderAtemLaeuft()) {
    return Zustand.empfangByWallet[walletId] || Zustand.empfang || null;
  }

  // Animation läuft: Poll nicht mit Adresse erschlagen —
  // * Scan/Sync-Puls: nur überspringen solange Scan wirklich läuft
  // * Ereignis-Atem (Konfetti/…): Zustand.empfang.puls ist nicht gesetzt
  if (still && typeof EmpfangPuls !== "undefined" && EmpfangPuls.laeuft()) {
    if (scanLaeuft) return null;
    if (!(Zustand.empfang && Zustand.empfang.puls)) return null;
  }

  // Scan/Sync hat Vorrang vor Lern-QR und Read-only-Text — Atem bis „gerade eben“.
  if (scanLaeuft) {
    zeichneEmpfangBeschaeftigt(walletId);
    return null;
  }

  // Scan-Puls hing nach Scan-Ende (stale tipSync) → stoppen und Adresse holen.
  // Konfetti/Sonderatem nicht anfassen (kein empfang.puls).
  if (
    typeof EmpfangPuls !== "undefined"
    && EmpfangPuls.laeuft()
    && Zustand.empfang
    && Zustand.empfang.puls
  ) {
    EmpfangPuls.stop();
  }

  // Lern-QR (Hover/Klick) nicht durch Poll/Cache überschreiben — nur ohne Scan.
  if (still && Zustand.lernThema && lernhinweiseAn() && Zustand.empfang?.lern) {
    return null;
  }

  // Flüchtigkeit: bei Kontextwechsel QR/Adresse sofort ungültig — ohne
  // Scan-Herzschlag (der nur bei echtem Scan/Sync startet, s. oben).
  const gleicherWallet = Zustand.empfang && Zustand.empfang.wallet_id === walletId
    && !Zustand.empfang.lern;

  if (walletMeta && walletMeta.read_only) {
    zeichneEmpfangReadOnly(walletMeta.name);
  } else if (!still || !gleicherWallet) {
    zeichneEmpfangLeer(t("dock.empfangLade"), { puls: false });
  }
  // still + gleiches Wallet (Poll): sichtbaren QR stehen lassen, bis neue
  // Antwort da ist — Adresse gehört noch zu diesem Wallet.

  Zustand.empfangLadeGen = (Zustand.empfangLadeGen || 0) + 1;
  const gen = Zustand.empfangLadeGen;
  try {
    const daten = await api(`/wallets/${walletId}/empfang`);
    if (gen !== Zustand.empfangLadeGen || Zustand.walletId !== walletId) {
      return null;
    }
    // Scan kann während dem Request gestartet haben — Cache-QR unterdrücken.
    if (empfangScanLaeuftFuer(walletId)) {
      zeichneEmpfangBeschaeftigt(walletId);
      return null;
    }
    // Index-Sprung = gezeigte Adresse wurde benutzt (oft Mempool).
    // Reihenfolge: Konfetti auf *alter* Adresse → Wallet-Update → neuer QR
    // erst nach Ende der Animation (nicht vorher umspringen).
    const prevEmp = Zustand.empfangByWallet[walletId]
      || (Zustand.empfang?.wallet_id === walletId ? Zustand.empfang : null);
    const prevIdx = prevEmp && Number.isFinite(Number(prevEmp.index))
      ? Number(prevEmp.index)
      : null;
    const neuIdx = Number(daten.index);
    const indexSprung = prevIdx != null && Number.isFinite(neuIdx) && neuIdx > prevIdx;

    if (indexSprung) {
      return starteEmpfangSprungMitKonfetti(walletId, daten, prevEmp);
    }

    Zustand.empfangByWallet[walletId] = daten;
    Zustand.empfang = daten;
    if (spieleQueuedIncomingFlash(walletId)) {
      return daten;
    }
    zeichneEmpfang(daten, { zahlung: false });
    return daten;
  } catch (fehler) {
    if (gen !== Zustand.empfangLadeGen) return null;
    if (empfangScanLaeuftFuer(walletId)) {
      zeichneEmpfangBeschaeftigt(walletId);
      return null;
    }
    if (!still) {
      zeichneEmpfangLeer(fehler.message || t("dock.empfangFehler"));
    }
    return null;
  }
}

function macheDockSpalter() {
  const spalter = $("#dock-spalter");
  const spalten = document.querySelector(".dock-spalten");
  if (!spalter || !spalten) return;

  try {
    const gemerkt = localStorage.getItem(DOCK_SPALTE_MERKER);
    if (gemerkt) spalten.style.setProperty("--dock-log-pct", gemerkt);
  } catch (_) {
    /* ohne Speicher bleibt Vorgabe */
  }

  let startX = 0;
  let startPct = 40;
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
    startPct = Number.parseFloat(roh) || 40;
    spalter.setPointerCapture(ereignis.pointerId);
    ereignis.preventDefault();
  });
  spalter.addEventListener("pointermove", (ereignis) => {
    if (!zieht) return;
    const breite = spalten.getBoundingClientRect().width;
    if (breite < 40) return;
    const delta = ((ereignis.clientX - startX) / breite) * 100;
    // Platz für Assistent + Empfangs-QR lassen.
    const pct = Math.min(70, Math.max(15, startPct + delta));
    spalten.style.setProperty("--dock-log-pct", `${Math.round(pct)}%`);
  });
  spalter.addEventListener("pointerup", beenden);
  spalter.addEventListener("pointercancel", beenden);
}

/** Empfangs-QR horizontal relativ zum Assistenten (LLM) ziehbar. */
function macheEmpfangSpalter() {
  const spalter = $("#empfang-spalter");
  const spalten = document.querySelector(".dock-spalten");
  if (!spalter || !spalten) return;

  try {
    const gemerkt = localStorage.getItem(EMPFANG_SPALTE_MERKER);
    if (gemerkt) spalten.style.setProperty("--dock-empfang-pct", gemerkt);
  } catch (_) {
    /* ohne Speicher bleibt Vorgabe */
  }

  let startX = 0;
  let startPct = 22;
  let zieht = false;

  const merken = (wert) => {
    try {
      localStorage.setItem(EMPFANG_SPALTE_MERKER, wert);
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
    const wert = getComputedStyle(spalten)
      .getPropertyValue("--dock-empfang-pct")
      .trim();
    if (wert) merken(wert);
  };

  spalter.addEventListener("pointerdown", (ereignis) => {
    if (ereignis.button !== 0) return;
    zieht = true;
    startX = ereignis.clientX;
    const roh = getComputedStyle(spalten)
      .getPropertyValue("--dock-empfang-pct")
      .trim();
    startPct = Number.parseFloat(roh) || 22;
    spalter.setPointerCapture(ereignis.pointerId);
    ereignis.preventDefault();
  });
  spalter.addEventListener("pointermove", (ereignis) => {
    if (!zieht) return;
    const breite = spalten.getBoundingClientRect().width;
    if (breite < 40) return;
    // Nach rechts ziehen → QR schmaler; nach links → QR breiter (Anteil der Dock-Breite).
    const delta = ((startX - ereignis.clientX) / breite) * 100;
    const pct = Math.min(48, Math.max(12, startPct + delta));
    spalten.style.setProperty("--dock-empfang-pct", `${Math.round(pct)}%`);
  });
  spalter.addEventListener("pointerup", beenden);
  spalter.addEventListener("pointercancel", beenden);
}

/* --- wallet-view-scans --- */
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

/**
 * Wallet-Überschrift in der großen Schrift: Name, optional
 * (sats bzw. BTC, ≈ Fiat zum Spotkurs) in derselben Zeile.
 * sats === undefined: nur der Name.
 */
function setzeWalletTitel(wallet, sats) {
  const el = $("#wallet-titel");
  if (!el) return;
  const base = (wallet && wallet.name) || t("common.wallet");
  if (sats === undefined) {
    setzeText(el, base);
    return;
  }
  const basis = formatSatsBasis(Number(sats) || 0);
  const fiat = formatEurAusSats(Number(sats) || 0);
  const klammer = fiat ? `${basis}, ≈ ${fiat}` : basis;
  setzeText(el, `${base} (${klammer})`);
}

async function zeigeWallet(walletId, { ohneEmpfang = false } = {}) {
  Zustand.walletId = walletId;
  Zustand.walletLadeGen = (Zustand.walletLadeGen || 0) + 1;
  const ladeGen = Zustand.walletLadeGen;
  zeigeAnsicht("wallet");
  // Während TxIN/Orange-₿ / Empfang-Sprung-Konfetti nicht neu laden.
  if (
    !ohneEmpfang
    && !empfangSonderAtemLaeuft()
    && Zustand._empfangSprungInArbeit !== String(walletId)
  ) {
    ladeEmpfang(walletId).catch(() => {});
  }

  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === walletId);
  setzeWalletTitel(wallet);
  // Erst Cache (schnell), Mempool-Pending danach im Hintergrund.
  setzeText($("#wallet-meta"), t("common.loadingFromCache"));
  $("#adress-liste").hidden = true;
  $("#wallet-leer").hidden = true;

  const limit = $("#limit-wahl").value;
  const sort = $("#sort-wahl")?.value || "betrag";
  const basis =
    `/wallets/${walletId}/utxos?limit=${limit}&sort=${encodeURIComponent(sort)}`;
  try {
    const daten = await api(`${basis}&mempool=0`);
    if (Zustand.walletId !== walletId || Zustand.walletLadeGen !== ladeGen) return;
    zeichneUtxos(daten, wallet);
  } catch (fehler) {
    if (Zustand.walletId !== walletId || Zustand.walletLadeGen !== ladeGen) return;
    zeigeLeer(t("wallet.loadFailed", { msg: fehler.message }), "");
    setzeText($("#wallet-meta"), "");
  }
  aktualisiereScanAnzeige();

  // Pending über eigenen Electrs — blockiert den Erst-Paint nicht.
  api(basis)
    .then((frisch) => {
      if (Zustand.walletId !== walletId || Zustand.walletLadeGen !== ladeGen) return;
      zeichneUtxos(frisch, wallet);
      aktualisiereScanAnzeige();
    })
    .catch(() => {});
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
  // Für Kopf-Filter: Ausgegeben-Block lazy nachzeichnen.
  Zustand._walletUtxoDaten = daten || null;
  const hatVerlauf = Boolean(daten.hat_verlauf);
  const hatUtxos = Boolean(daten.has_cache && daten.total_count);

  if (!daten.has_cache && !hatVerlauf) {
    zeigeLeer(
      t("wallet.emptyNoCache"),
      t("wallet.emptyNoCacheHint"),
    );
    setzeText($("#wallet-meta"), t("wallet.metaNeverScanned"));
    setzeWalletTitel(wallet);
    aktualisiereKopfFilterFuerAnsicht();
    return;
  }
  if (daten.has_cache && !hatUtxos && !hatVerlauf) {
    zeigeLeer(
      t("wallet.emptyNoUtxo"),
      t("wallet.emptyNoUtxoHint"),
    );
    setzeText($("#wallet-meta"), t("wallet.metaZeroCache"));
    setzeWalletTitel(wallet, 0);
    aktualisiereKopfFilterFuerAnsicht();
    return;
  }

  const teile = [];
  if (daten.has_cache) {
    const utxoListe = daten.utxos || [];
    setzeWalletTitel(wallet, daten.total_sats);
    teile.push(`${daten.total_count} UTXO`);
    if (daten.shown_count < daten.total_count) {
      teile.push(
        `angezeigt: ${daten.shown_count} · ${formatSatsGemeinsam(daten.shown_sats, utxoListe)}`,
      );
    }
    const pendOut = Number(daten.pending_spending_count || 0);
    const pendIn = Number(daten.pending_receive_count || 0);
    if (wallet && wallet.id) {
      const internOut = (daten.utxos || []).some(
        (u) => u && u.spending_pending && u.spending_internal,
      );
      meldePendingAenderung(wallet.id, pendIn, pendOut, { internOut });
    }
    if (pendOut > 0 || pendIn > 0) {
      const bits = [];
      if (pendOut > 0) bits.push(t("wallet.metaPendingOut", { n: pendOut }));
      if (pendIn > 0) bits.push(t("wallet.metaPendingIn", { n: pendIn }));
      teile.push(bits.join(", "));
    }
  } else {
    teile.push(t("ui.hard.d22bed085a"));
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
  aktualisiereKopfFilterFuerAnsicht();
  wendeKopfFilterAn();
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
    ? t("scan.hard.2e18213140", { tage })
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
  block.dataset.address = gruppe.address || "";
  const gLabels = kopfFilterLabelText(gruppe);
  if (gLabels) block.dataset.filterLabels = gLabels;

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
  setzeSatsBetrag(betrag, gruppe.total_sats, {
    gemeinsam: gruppe.utxos || [],
  });

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

/** Unix-Sekunden für Kopf-Filter (Ausgabe bevorzugt, sonst Ankunft). */
function utxoEreignisTs(utxo) {
  if (!utxo) return 0;
  if (utxo.spent || utxo.spent_pending) {
    const st = Number(
      utxo.spent_time_ts
      || utxo.spent_block_time
      || (utxo.status && utxo.status.spent_time_ts)
      || 0,
    );
    if (st > 0) return st;
  }
  const bt = Number(utxo.block_time || 0);
  if (bt > 0) return bt;
  if (utxo.time_label) {
    const m = String(utxo.time_label).match(
      /(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/,
    );
    if (m) {
      let y = Number(m[3]);
      if (m[3].length <= 2) y += 2000;
      const d = new Date(
        y, Number(m[2]) - 1, Number(m[1]),
        Number(m[4] || 0), Number(m[5] || 0), Number(m[6] || 0),
      );
      if (!Number.isNaN(d.getTime())) return Math.floor(d.getTime() / 1000);
    }
  }
  const js = Number(utxo.juengste_sats_ts || 0);
  return js > 0 ? js : 0;
}

/** Suchtext für Kopf-Filter: Mix-Formen + Börsennamen (Kraken, Wasabi, …). */
function kopfFilterLabelText(utxoOderGruppe) {
  if (!utxoOderGruppe || typeof utxoOderGruppe !== "object") return "";
  const teile = [];
  const mix = utxoOderGruppe.mix_arten
    || (utxoOderGruppe.utxos ? mixArtenDerGruppe(utxoOderGruppe) : []);
  for (const k of mix || []) {
    if (!k) continue;
    teile.push(String(k));
    teile.push(MIX_ICON_KURZ[k] || "");
    const soft = softTxClassLabel({ tx_class: k });
    if (soft) teile.push(soft);
  }
  const txc = utxoOderGruppe.tx_class;
  if (txc) {
    teile.push(String(txc));
    teile.push(MIX_ICON_KURZ[txc] || "");
    const soft = softTxClassLabel({ tx_class: txc });
    if (soft) teile.push(soft);
  }
  let boerse = utxoOderGruppe.boerse_namen;
  if (!boerse && utxoOderGruppe.utxos) {
    boerse = boerseNamenDerGruppe(utxoOderGruppe).namen;
  }
  for (const n of boerse || []) {
    if (n) teile.push(String(n));
  }
  // „davon … an Kraken“: Ziele der Ausgabetransaktion, nicht die Herkunft.
  for (const ziel of utxoOderGruppe.exchange_spends || []) {
    const name = ziel && String(ziel.name || "").trim();
    if (name) teile.push(name);
  }
  // Einzel-Label-Objekte (falls am Root)
  const ein = boerseNameAusKnoten(utxoOderGruppe);
  if (ein) teile.push(ein);
  return teile.filter(Boolean).join(" ");
}

function setzeUtxoTraceDaten(el, utxo) {
  if (!el || !utxo) return;
  if (utxo.key) el.dataset.key = utxo.key;
  el.dataset.verfolgtVollstaendig = utxoHatVollenHerkunftstrace(utxo) ? "1" : "0";
  el.dataset.verfolgt = utxo.verfolgt ? "1" : "0";
  if (utxo.value_sats != null && utxo.value_sats !== "") {
    el.dataset.valueSats = String(utxo.value_sats);
  }
  if (utxo.address) el.dataset.address = String(utxo.address);
  if (utxo.hold_days != null && utxo.hold_days !== "") {
    el.dataset.holdDays = String(utxo.hold_days);
  }
  if (utxo.block_height != null && utxo.block_height !== "") {
    el.dataset.blockHeight = String(utxo.block_height);
  }
  if (utxo.time_label) el.dataset.timeLabel = String(utxo.time_label);
  if (utxo.juengste_sats_ts) {
    el.dataset.juengsteSatsTs = String(utxo.juengste_sats_ts);
  } else {
    delete el.dataset.juengsteSatsTs;
  }
  const ets = utxoEreignisTs(utxo);
  if (ets > 0) el.dataset.eventTs = String(ets);
  else delete el.dataset.eventTs;
  const labels = kopfFilterLabelText(utxo);
  if (labels) el.dataset.filterLabels = labels;
  else delete el.dataset.filterLabels;
}

function zeichneUtxoZeile(utxo) {
  const zeile = document.createElement("div");
  zeile.className = "utxo-zeile";
  if (utxo.spending_pending) zeile.classList.add("spending-pending-zeile");
  if (utxo.receive_pending) zeile.classList.add("receive-pending-zeile");
  setzeUtxoTraceDaten(zeile, utxo);

  const betrag = document.createElement("span");
  betrag.className = "betrag";
  {
    const atTs = tsAusBewertungsObjekt(utxo);
    if (atTs) setzeSatsBetrag(betrag, utxo.value_sats, { atTs });
    else betrag.textContent = formatSats(utxo.value_sats);
  }

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

  // Herkunft unvollständig (rot) — Abbruch, Lücken, fehlende Prevouts.
  if (utxo.verfolgt && utxoHerkunftUnvollstaendig(utxo)) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke unvollstaendig";
    const wann = utxo.verfolgt_ts
      ? formatKurzdatum(utxo.verfolgt_ts * 1000)
      : "";
    marke.textContent = wann
      ? t("trace.incompleteWhen", { wann })
      : t("trace.incomplete");
    marke.title = t("trace.incompleteTitle");
    zeile.append(marke);
  }

  const juengste = juengsteSatsMarke(utxo);
  if (juengste) zeile.append(juengste);

  // Woher der letzte externe Zufluss kam, sofern die Herkunft schon
  // ermittelt und die Adresse zuzuordnen ist.
  // Ingress = Zufluss von außen (Börse→Wallet → grün).
  const herkunft = labelMarke(utxo.herkunft_label, { herkunft: true, zufluss: true });
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

/** „Aktualisieren“ bleibt sichtbar — auch bei „Wallets immer aktuell halten“. */
function setzeTipSyncSichtbarkeit() {
  const tipSync = $("#tip-sync-knopf");
  if (!tipSync) return;
  tipSync.hidden = false;
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
        ? t("ui.hard.a7e393ac49", { name, art, schritt, danach })
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
    folgeWalletSyncJob(jobId, antwort.job || { meta: { wallet_ids: [wid] } });
    stoesseEmpfangScanPuls();
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
  // Pending-Baseline neu: Scan-Ende/Refresh darf kein „In steigt“-Konfetti
  // für schon vorhandene Mempool-Txs auslösen.
  if (ziel.id) {
    Zustand.pendingByWallet[ziel.id] = { in: 0, out: 0, seen: false };
  }
  Zustand.rescanJob = job.id;
  nimmJobLog(job);
  aktualisiereScanAnzeige(job.message || "wird gestartet…");
  zeichneNav();
  // Empfangs-Pane: Herzschlag wenn dieses Wallet gewählt (Lern-QR weichen).
  if (Zustand.walletId === ziel.id) {
    Zustand.lernThema = null;
    EmpfangPuls.stop();
    ladeEmpfang(ziel.id).catch(() => {});
  }
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

  // Erster Fund-Schub: ein oranger ₿-Atemzug (nur wenn Betrag ≥ 500 sats
  // bekannt — Zwischenstand hat oft nur die Anzahl, dann kein Flash).
  // Weitere Funde während der Animation → still, Animation läuft aus.
  if (
    Zustand.walletId === scanId
    && typeof utxoZahl === "number"
    && utxoZahl > 0
    && (vorher == null || utxoZahl > vorher)
  ) {
    // Ohne Einzelbetrag: Mindestgröße (Dust = 500 → 15 %).
    EmpfangPuls.flashOrangeB(500);
  }

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

/**
 * Mempool-Pending → QR-Animation — nur für das *aktuell gewählte* Wallet.
 *
 * Konfetti **nur** wenn ``pending_receive`` steigt (neue TxIN im Mempool).
 * Nicht bei UTXO-Scan, Cache-Aufbau oder Empfangsadress-Sprung allein.
 *
 * Während Tip-Sync/Scan ist ``empfangScanLaeuftFuer`` true — dann merken wir
 * den Incoming und spielen Ka-Ching nach Sync-Ende nach (sonst: QR springt,
 * Konfetti fehlt).
 *
 * * In → Konfetti
 * * In+Out gleichzeitig (Self) → nur Konfetti
 * * internOut: Spend an eigenes Wallet → Konfetti
 * * sonst Out → OH NO!
 */
function merkeQueuedIncomingFlash(walletId) {
  if (!walletId) return;
  Zustand._queuedIncomingFlash = { walletId: String(walletId), um: Date.now() };
}

function holeQueuedIncomingFlash(walletId) {
  const q = Zustand._queuedIncomingFlash;
  if (!q || String(q.walletId) !== String(walletId)) return null;
  if (Date.now() - (q.um || 0) > 120000) {
    Zustand._queuedIncomingFlash = null;
    return null;
  }
  Zustand._queuedIncomingFlash = null;
  return q;
}

/**
 * Empfangs-Index ist weitergesprungen (Adresse benutzt) → Wallet-UTXOs inkl.
 * Mempool-Pending neu laden. Gedrosselt, damit Polls nicht fluten.
 */
function frischeWalletNachEmpfangSprung(walletId) {
  if (!walletId || Zustand.walletId !== walletId) return;
  if (Zustand.ansicht !== "wallet") return;
  if (typeof empfangScanLaeuftFuer === "function" && empfangScanLaeuftFuer(walletId)) {
    return;
  }
  const jetzt = Date.now();
  if (
    Zustand._lastEmpfangSprungRefreshUm
    && jetzt - Zustand._lastEmpfangSprungRefreshUm < 2500
  ) {
    return;
  }
  Zustand._lastEmpfangSprungRefreshUm = jetzt;
  // zeigeWallet: zweiter Request mit Mempool — Pending sichtbar.
  // Empfang nicht erneut anstoßen (ohneEmpfang), sonst QR-Loop / Animation-Kill.
  Promise.resolve(zeigeWallet(walletId, { ohneEmpfang: true })).catch(() => {});
}

/**
 * Mempool/History hat die gezeigte Adresse benutzt.
 * 1) Alter QR bleibt · 2) Konfetti · 3) Wallet-Update · 4) neuer QR nach Animation.
 */
function starteEmpfangSprungMitKonfetti(walletId, neueDaten, alterEmpfang) {
  // Schon in Konfetti: nur neueren Empfangsstand merken.
  if (Zustand._empfangSprungInArbeit === String(walletId)) {
    Zustand._pendingEmpfangNachKonfetti = {
      walletId: String(walletId),
      daten: neueDaten,
    };
    return neueDaten;
  }
  Zustand._pendingEmpfangNachKonfetti = { walletId: String(walletId), daten: neueDaten };
  Zustand._empfangSprungInArbeit = String(walletId);

  // Alten QR behalten (nicht neueDaten speichern/zeichnen).
  if (alterEmpfang && alterEmpfang.address) {
    Zustand.empfangByWallet[walletId] = alterEmpfang;
    Zustand.empfang = alterEmpfang;
    if (!empfangSonderAtemLaeuft()) {
      zeichneEmpfang(alterEmpfang, { zahlung: false });
    }
  }

  frischeWalletNachEmpfangSprung(walletId);

  const zeigeNeuenQr = () => {
    const pending = Zustand._pendingEmpfangNachKonfetti;
    Zustand._pendingEmpfangNachKonfetti = null;
    Zustand._empfangSprungInArbeit = null;
    if (!pending || String(pending.walletId) !== String(Zustand.walletId)) return;
    Zustand.empfangByWallet[pending.walletId] = pending.daten;
    Zustand.empfang = pending.daten;
    zeichneEmpfang(pending.daten, { zahlung: false });
  };

  const jetzt = Date.now();
  if (
    Zustand._lastIncomingFlashUm
    && jetzt - Zustand._lastIncomingFlashUm <= 4000
  ) {
    // Debounce: kein zweites Konfetti — neuen QR trotzdem nachziehen.
    zeigeNeuenQr();
    return neueDaten;
  }
  Zustand._lastIncomingFlashUm = jetzt;
  Zustand._queuedIncomingFlash = null;
  EmpfangPuls.flashIncoming(walletId, undefined, {
    halteDanach: false,
    onDone: zeigeNeuenQr,
  });
  return neueDaten;
}

/** Nach Tip-Sync/Scan: gemerktes Mempool-Incoming als Ka-Ching nachholen. */
function spieleQueuedIncomingFlash(walletId) {
  if (!walletId || Zustand.walletId !== walletId) return false;
  if (Zustand._empfangSprungInArbeit === String(walletId)) return false;
  if (typeof empfangScanLaeuftFuer === "function" && empfangScanLaeuftFuer(walletId)) {
    return false;
  }
  if (!holeQueuedIncomingFlash(walletId)) return false;
  const jetzt = Date.now();
  if (
    Zustand._lastIncomingFlashUm
    && jetzt - Zustand._lastIncomingFlashUm <= 4000
  ) {
    return false;
  }
  Zustand._lastIncomingFlashUm = jetzt;
  EmpfangPuls.flashIncoming(walletId, undefined, {
    halteDanach: false,
    onDone: () => {
      if (Zustand.walletId !== walletId) return;
      const pending = Zustand._pendingEmpfangNachKonfetti;
      if (pending && String(pending.walletId) === String(walletId)) {
        Zustand._pendingEmpfangNachKonfetti = null;
        Zustand.empfangByWallet[walletId] = pending.daten;
        Zustand.empfang = pending.daten;
        zeichneEmpfang(pending.daten, { zahlung: false });
        return;
      }
      ladeEmpfang(walletId, { still: true }).catch(() => {});
    },
  });
  return true;
}

function meldePendingAenderung(walletId, pendIn, pendOut, { internOut = false } = {}) {
  if (!walletId) return;
  const prev = Zustand.pendingByWallet[walletId] || { in: 0, out: 0 };
  const neuIn = Number(pendIn) || 0;
  const neuOut = Number(pendOut) || 0;
  Zustand.pendingByWallet[walletId] = { in: neuIn, out: neuOut };
  // Baseline ohne Animation: erster Stand, Scan/Refresh, Wallet-Wechsel.
  // Nur *Anstieg* nach gesehenem Stand = echte neue Mempool-Tx.
  const scanLaeuft = typeof empfangScanLaeuftFuer === "function"
    && empfangScanLaeuftFuer(walletId);
  if (prev.seen && Zustand.walletId === walletId) {
    const inNeu = neuIn > prev.in;
    const outNeu = neuOut > prev.out;
    const jetzt = Date.now();
    const darfIncoming = () => {
      if (
        Zustand._lastIncomingFlashUm
        && jetzt - Zustand._lastIncomingFlashUm <= 4000
      ) {
        return false;
      }
      Zustand._lastIncomingFlashUm = jetzt;
      return true;
    };
    const starteIncoming = () => {
      if (scanLaeuft) {
        // Tip-Sync läuft oft parallel: QR wird geschärft, Konfetti sonst verschluckt.
        merkeQueuedIncomingFlash(walletId);
        return;
      }
      if (!darfIncoming()) return;
      EmpfangPuls.flashIncoming(walletId, undefined, {
        halteDanach: false,
        onDone: () => {
          // Nach Konfetti: nächste freie Adresse holen (ohne erneuten Flash).
          if (Zustand.walletId === walletId) {
            ladeEmpfang(walletId).catch(() => {});
          }
        },
      });
    };
    if (inNeu && outNeu) {
      // Self-Send im selben Wallet: nur Konfetti.
      starteIncoming();
    } else if (inNeu) {
      starteIncoming();
    } else if (outNeu) {
      if (internOut) {
        // Interner Transfer (z. B. Cash+Carry → Bitkey): nur Konfetti, kein OH NO.
        starteIncoming();
      } else if (!scanLaeuft) {
        EmpfangPuls.flashOhNo();
      }
    }
  }
  Zustand.pendingByWallet[walletId].seen = true;
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
  const scanId = Zustand.scanWalletId;
  Zustand.rescanJob = null;
  Zustand.scanArt = null;
  Zustand.scanWalletId = null;
  Zustand.scanWalletName = "";
  Zustand.scanUtxoZahl = null;
  Zustand.scanRefreshUm = 0;
  Zustand.scanRefreshLaeuft = false;
  if (scanId) {
    Zustand.pendingByWallet[scanId] = { in: 0, out: 0, seen: false };
  }
  EmpfangPuls.stop();
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
  if (scanId && Zustand.walletId === scanId && !Zustand.lernThema) {
    ladeEmpfang(scanId).catch(() => {});
  }
}

/* --- zeigeMultisig --- */
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
  typWahl.title = t("ui.hard.dff0e41104");
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

/* --- wallet-verwaltung-cache --- */
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
    } else if (wallet.export_import === "complete") {
      // Sparrow/Wasabi: alle Export-Adressen zugeordnet.
      cache.className = "pille pille-gut";
      cache.textContent = t("wallets.importedOk");
      const teile = [
        t("wallets.importedOkTitle"),
        Number(wallet.utxo_count) > 0 ? `${wallet.utxo_count} UTXO` : "",
        Number(wallet.export_verlauf_n) > 0
          ? `${wallet.export_verlauf_n} Tx`
          : "",
        walletAlter(wallet),
      ];
      cache.title = teile.filter(Boolean).join(" · ");
    } else if (wallet.export_import === "partial") {
      // Sparrow/Wasabi: noch Einträge ohne Adresse.
      cache.className = "pille pille-warn";
      cache.textContent = t("wallets.importedPartial");
      cache.title = t("wallets.importedPartialTitle", {
        ohne: wallet.export_ohne_adresse || 0,
        n: wallet.export_verlauf_n || 0,
      });
    } else if (wallet.has_cache) {
      cache.className = "pille pille-gut";
      const hinweis = cacheHinweis(wallet);
      const nUtxo = Number(wallet.utxo_count) || 0;
      cache.textContent = hinweis || (nUtxo ? `${nUtxo} UTXO` : t("wallets.importedOk"));
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

    const nurLesen = zeile.querySelector(".read-only-wahl");
    if (nurLesen) {
      nurLesen.checked = Boolean(wallet.read_only);
      nurLesen.addEventListener("change", () => {
        wallet.read_only = Boolean(nurLesen.checked);
        aktualisiereKnopf();
      });
    }

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
      // Name merken — speichereWallets loggt „Lösche …“ / „Löschen beendet“.
      speichereWallets(false, false, null, [nameHint]);
    });

    liste.append(fragment);
  });
  if (window.SatSageI18n) window.SatSageI18n.applyDom(liste);
  ladeGefahrWallets();

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
    ? t("ui.hard.1ec1e4421a")
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
      ? t("ui.hard.92f53adbad", { label, n })
      : t("ui.hard.0b2ff9302a");
    meldung(text, "gut");
    logZeile(text);
    zeichneUnreferenziertenCache({ vorhanden: false, dateien: 0, bytes: 0 });
    await ladeCacheDashboard();
  } catch (fehler) {
    meldung(t("ui.hard.2ce465fdb1", { msg: fehler.message }), "krit");
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
  // Ab 1000 MB → GB, max. 2 Nachkommastellen; Tausendertrenner per Locale.
  if (mb >= 1000) {
    const gb = n / (1024 * 1024 * 1024);
    return `${gb.toLocaleString(formatLocale(), {
      maximumFractionDigits: 2,
    })} GB`;
  }
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

/* --- wallet-import-export --- */
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

/** Gewählte Pfade in der Sparrow/Wasabi-Suchliste. */
function walletExportGewaehltePfade() {
  const liste = $("#wallet-export-liste");
  if (!liste) return [];
  return [...liste.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)')]
    .map((el) => el.value)
    .filter(Boolean);
}

/** Knopf-Text: Datei(en) vs. Wallet(s) je nach Checkbox-Auswahl. */
function aktualisiereWalletExportImportKnopf() {
  const knopf = $("#sparrow-import");
  if (!knopf) return;
  const n = walletExportGewaehltePfade().length;
  if (n > 0) {
    knopf.textContent = t("wallets.exportImportWallets");
    knopf.title = t("wallets.exportImportWalletsTitle");
    knopf.dataset.i18n = "wallets.exportImportWallets";
    knopf.dataset.i18nTitle = "wallets.exportImportWalletsTitle";
  } else {
    knopf.textContent = t("wallets.exportImportFile");
    knopf.title = t("wallets.exportImportTitle");
    knopf.dataset.i18n = "wallets.exportImportFile";
    knopf.dataset.i18nTitle = "wallets.exportImportTitle";
  }
}

/**
 * Ein Knopf: mit Checkbox-Auswahl → Wallet-Pfade importieren,
 * sonst Datei-Dialog.
 */
function oeffneSparrowImport() {
  const pfade = walletExportGewaehltePfade();
  if (pfade.length) {
    starteWalletExportImportAuswahl(false);
    return;
  }
  const feld = $("#sparrow-dateien");
  if (feld) feld.click();
}

function liesSparrowDateien(ereignis) {
  const liste = ereignis.target.files;
  ereignis.target.value = "";
  if (!liste || !liste.length) return;
  starteSparrowImport(Array.from(liste));
}

/** Letzte Suchtreffer (Pfad → Meta) für den Import-Knopf. */
let _walletExportTreffer = [];

/**
 * Wallet-Export-Suche als normales JSON (kein NDJSON-Stream).
 *
 * Die Suche ist lokal und schnell; NDJSON ohne Content-Length/Chunked
 * endet unter WebKit oft mit „Load failed“, obwohl die Log-Zeilen schon da
 * waren. logs[] kommt mit der Antwort und wird hier ins GUI-Log geschrieben.
 */
async function holeWalletExportSuche() {
  return api("/config/wallet-export-suchen", {
    methode: "POST",
    daten: {},
    timeoutMs: 60_000,
  });
}

async function starteWalletExportSuche() {
  const kasten = $("#sparrow-befund");
  const fund = $("#wallet-export-fund");
  const liste = $("#wallet-export-liste");
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(t("wallets.exportSearching")));
  }
  logZeile(t("wallets.exportSearching"));
  try {
    const antwort = await holeWalletExportSuche();
    _walletExportTreffer = antwort.wallets || [];
    for (const z of antwort.logs || []) {
      if (z) logZeile(String(z));
    }
    zeichneWalletExportListe(_walletExportTreffer);
    if (fund) fund.hidden = false;
    const n = _walletExportTreffer.length;
    const imp = Number(antwort.importable || 0);
    const text = n
      ? t("wallets.exportSearchDone", { n, imp })
      : t("wallets.exportSearchEmpty");
    if (kasten) kasten.replaceChildren(hinweisZeile(text));
    logZeile(`Wallet-Suche: ${text}`);
    aktualisiereWalletExportImportKnopf();
  } catch (fehler) {
    _walletExportTreffer = [];
    if (liste) liste.replaceChildren();
    if (fund) fund.hidden = true;
    if (kasten) {
      kasten.replaceChildren(
        hinweisZeile(fehler.message || t("wallets.exportFailed")),
      );
    }
    meldung(fehler.message || t("wallets.exportFailed"), "krit");
    aktualisiereWalletExportImportKnopf();
  }
}

function zeichneWalletExportListe(treffer) {
  const liste = $("#wallet-export-liste");
  if (!liste) return;
  liste.replaceChildren();
  // Server sortiert bereits: importierbar → locked, jeweils A–Z.
  // Client-seitig nochmals absichern.
  const sortiert = [...(treffer || [])].sort((a, b) => {
    const ai = a && a.importable ? 0 : 1;
    const bi = b && b.importable ? 0 : 1;
    if (ai !== bi) return ai - bi;
    const an = String((a && a.name) || "").toLowerCase();
    const bn = String((b && b.name) || "").toLowerCase();
    if (an < bn) return -1;
    if (an > bn) return 1;
    return 0;
  });
  for (const w of sortiert) {
    const zeile = document.createElement("div");
    zeile.className = "export-zeile";
    if (w.locked) zeile.classList.add("export-gesperrt");
    if (!w.importable) zeile.classList.add("export-blockiert");

    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = w.path || "";
    cb.disabled = !w.importable;
    cb.dataset.exportId = w.id || "";
    // Default unchecked: Nutzer wählt ausdrücklich, was importiert wird.
    cb.checked = false;
    cb.addEventListener("change", aktualisiereWalletExportImportKnopf);
    label.append(cb);

    const name = document.createElement("span");
    name.className = "export-name";
    name.textContent = w.name || w.path || "?";
    name.title = w.path || "";
    label.append(name);

    if (w.locked) {
      const lock = document.createElement("span");
      lock.className = "export-schloss";
      lock.textContent = "🔒";
      lock.title = t("wallets.exportLockTitle");
      label.append(lock);
    }

    if (w.reason && (!w.importable || w.locked)) {
      const grund = document.createElement("span");
      grund.className = "export-grund";
      grund.textContent = w.reason;
      grund.title = w.importable
        ? t("wallets.exportLockTitle")
        : t("wallets.exportBlockedTitle");
      label.append(grund);
    }

    // Herkunft rechtsbündig (Wasabi / Specter / Electrum / Core / …)
    const herkunft = document.createElement("span");
    herkunft.className = "export-herkunft";
    herkunft.textContent = w.origin_label
      || (w.app
        ? String(w.app).charAt(0).toUpperCase() + String(w.app).slice(1)
        : "");
    herkunft.title = w.path || herkunft.textContent || "";
    label.append(herkunft);

    zeile.append(label);
    liste.append(zeile);
  }
  aktualisiereWalletExportImportKnopf();
}

async function starteWalletExportImportAuswahl(bestaetigt = false) {
  const kasten = $("#sparrow-befund");
  const knopf = $("#sparrow-import");
  const pfade = walletExportGewaehltePfade();
  if (!pfade.length) {
    if (kasten) {
      kasten.hidden = false;
      kasten.replaceChildren(hinweisZeile(t("wallets.exportNoSelection")));
    }
    return;
  }
  if (knopf) knopf.disabled = true;
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(t("wallets.exportImporting")));
  }
  logZeile(t("ui.hard.ddad9af15b", { n: pfade.length }));
  try {
    const antwort = await api("/config/wallet-export-import-pfade", {
      methode: "POST",
      daten: { paths: pfade, confirm: bestaetigt },
      timeoutMs: 180_000,
    });
    await nachWalletExportErfolg(antwort);
    try {
      await starteWalletExportSuche();
    } catch (_) {
      /* Suche optional nachziehen */
    }
  } catch (fehler) {
    if (fehler && fehler.status === 409 && !bestaetigt) {
      const ok = window.confirm(
        `${fehler.message || ""}\n\n${t("wallets.saveAnyway")}?`,
      );
      if (ok) {
        if (knopf) knopf.disabled = false;
        await starteWalletExportImportAuswahl(true);
        return;
      }
    }
    const msg = (fehler && fehler.message) || t("wallets.exportFailed");
    if (kasten) {
      kasten.replaceChildren(hinweisZeile(msg));
    }
    meldung(msg, "krit");
    logZeile(`Wallet-Export: ${msg}`, true);
  } finally {
    if (knopf) knopf.disabled = false;
    aktualisiereWalletExportImportKnopf();
  }
}

/** Nach Import: alphabetisch erstes importiertes Wallet öffnen. */
async function wechsleZuImportiertemWallet(antwort) {
  let zielId = "";
  const liste = Array.isArray(antwort?.wallets) ? antwort.wallets : [];
  if (liste.length) {
    const sortiert = [...liste].sort((a, b) => {
      const an = String((a && a.name) || "").toLowerCase();
      const bn = String((b && b.name) || "").toLowerCase();
      if (an < bn) return -1;
      if (an > bn) return 1;
      return String((a && a.id) || "").localeCompare(String((b && b.id) || ""));
    });
    zielId = sortiert[0]?.id || "";
  }
  if (!zielId && antwort?.wallet_id) zielId = antwort.wallet_id;
  if (!zielId && Array.isArray(antwort?.wallet_ids) && antwort.wallet_ids[0]) {
    zielId = antwort.wallet_ids[0];
  }
  if (!zielId) return;
  // Config kann IDs frisch haben — Prefer Matching aus config.
  const cfg = (Zustand.config?.wallets || []).find((w) => w.id === zielId);
  if (!cfg && (Zustand.config?.wallets || []).length) {
    const names = new Set(
      liste.map((w) => String((w && w.name) || "").toLowerCase()).filter(Boolean),
    );
    const treffer = (Zustand.config.wallets || [])
      .filter((w) => names.has(String(w.name || "").toLowerCase()))
      .sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), undefined, { sensitivity: "base" }));
    if (treffer[0]?.id) zielId = treffer[0].id;
  }
  try {
    await zeigeWallet(zielId);
  } catch (fehler) {
    logZeile(
      `Wallet-Export: Wechsel zur Ansicht fehlgeschlagen — ${fehler.message || fehler}`,
      true,
    );
  }
}

async function nachWalletExportErfolg(antwort) {
  const kasten = $("#sparrow-befund");
  const fmt = antwort.format
    ? t("wallets.exportFormat", { format: antwort.format })
    : "";
  const teile = [
    antwort.already_present
      ? t("wallets.exportAlreadyPresent", { name: antwort.name || "", format: fmt })
      : t("wallets.exportSaved", { name: antwort.name || "", format: fmt }),
    t("wallets.exportCounts", {
      utxo: antwort.utxo_count || 0,
      verlauf: antwort.verlauf_count || 0,
    }),
  ];
  if (antwort.wallets_added > 1) {
    teile.push(`${antwort.wallets_added} Wallets`);
  }
  if (antwort.erste_adresse) {
    teile.push(t("wallets.exportFirstAddr", { addr: antwort.erste_adresse }));
  }
  for (const h of antwort.hinweise || []) {
    if (h) teile.push(String(h));
  }
  // Erfolg sofort sichtbar — Config-Reload darf die Meldung nicht blockieren.
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(teile.join(" · ")));
  }
  meldung(teile[0], "ok");
  const fmtLog = antwort.format ? ` · ${antwort.format}` : "";
  logZeile(
    `Wallet-Export${fmtLog}: ${antwort.name || "?"} · ${antwort.utxo_count || 0} UTXO · ${antwort.verlauf_count || 0} Tx`,
  );
  try {
    await ladeConfig();
    Zustand.entwurf = (Zustand.config?.wallets || []).map((w) => ({ ...w }));
    zeichneEinstellungen();
  } catch (fehler) {
    logZeile(
      `Wallet-Export: Import ok, Ansicht nicht aktualisiert — ${fehler.message || fehler}`,
      true,
    );
  }
  try {
    ladeCacheDashboard();
  } catch (_) {
    /* optional */
  }
  await ggfAdressenNachziehenNachExport(antwort);
  await wechsleZuImportiertemWallet(antwort);
}

/**
 * Nach Wallet-Export: Adressen per Electrs nachziehen.
 * ≤100 Tx automatisch, >100 mit Nachfrage.
 * Indexer konfiguriert aber noch nicht da (Tor): Job startet und wartet.
 * Ohne konfigurierten Indexer: klare Log-Zeile, kein stiller Abbruch.
 */
async function ggfAdressenNachziehenNachExport(antwort) {
  const meta = antwort && antwort.address_nachziehen;
  if (!meta) return;
  const n = Number(meta.pending_txids || 0);
  const name = meta.name || antwort.name || "?";
  if (n <= 0) return;

  const indexerDa = Boolean(meta.indexer_configured);
  if (!indexerDa) {
    logZeile(
      t("wallets.exportAddrNeedsIndexer", { name, n }),
      true,
    );
    return;
  }

  if (meta.needs_confirm) {
    logZeile(t("wallets.exportAddrAskLog", { name, n }));
    const ok = window.confirm(
      t("wallets.exportAddrConfirm", { name, n, max: meta.auto_max || 100 }),
    );
    if (!ok) {
      logZeile(t("wallets.exportAddrSkipped", { name, n }));
      return;
    }
  } else if (meta.auto_start) {
    if (!meta.electrs) {
      logZeile(t("wallets.exportAddrIndexerPending", { name, n }));
    } else {
      logZeile(t("wallets.exportAddrAutoLog", { name, n }));
    }
  } else {
    return;
  }

  try {
    // Job wartet intern auf Tor — API-Timeout länger als Bootstrap-Rest.
    const job = await api("/config/wallet-export-adressen-nachziehen", {
      methode: "POST",
      daten: { wallet_id: meta.wallet_id },
      timeoutMs: 60_000,
    });
    logZeile(
      t("wallets.exportAddrJobStarted", {
        name,
        n,
        id: (job && job.id) || "?",
      }),
    );
    if (job && job.id) {
      folgeExportAdressenJob(job.id, name, meta.wallet_id || antwort.wallet_id);
    }
  } catch (fehler) {
    const msg = (fehler && fehler.message) || String(fehler);
    logZeile(
      t("wallets.exportAddrJobFailed", { msg }),
      true,
    );
    if (/Indexer|Electrs|Fulcrum|Tor/i.test(msg)) {
      logZeile(t("wallets.exportAddrNeedsIndexer", { name, n }), true);
    }
  }
}

/** Job-Log „Adressen nachziehen“ in den GUI-Log-Bereich spiegeln. */
function folgeExportAdressenJob(jobId, walletName, walletId) {
  if (!jobId) return;
  if (!Zustand.exportAddrLogStand) {
    Zustand.exportAddrLogStand = { index: 0, knoten: [], texte: [] };
  }
  const stand = Zustand.exportAddrLogStand;
  // Neuer Job → Log-Stand zurücksetzen
  if (Zustand.exportAddrJob !== jobId) {
    stand.index = 0;
    stand.knoten = [];
    stand.texte = [];
    Zustand.exportAddrJob = jobId;
  }
  if (Zustand.exportAddrTimer) {
    clearInterval(Zustand.exportAddrTimer);
    Zustand.exportAddrTimer = null;
  }

  const tick = async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmLogZeilen(job, stand, walletName || "");
      if (job.running || job.status === "running" || job.status === "queued") {
        return;
      }
      clearInterval(Zustand.exportAddrTimer);
      Zustand.exportAddrTimer = null;
      Zustand.exportAddrJob = null;
      if (job.status === "done") {
        const st = job.result || {};
        const quelle = st.quelle === "cache"
          ? t("wallets.exportAddrQuelleCache")
          : st.quelle === "electrs-batch"
            ? t("wallets.exportAddrQuelleBatch")
            : st.quelle === "electrs"
              ? t("wallets.exportAddrQuelleElectrs")
              : "";
        logZeile(
          t("wallets.exportAddrJobDone", {
            name: walletName || "?",
            filled: st.filled || 0,
            failed: st.failed || 0,
          }) + (quelle ? ` · ${quelle}` : ""),
        );
        try {
          ladeCacheDashboard();
        } catch (_) {
          /* optional */
        }
        // Pille grün/gelb „importiert“ + Wallet-Ansicht aktualisieren.
        try {
          await ladeConfig();
          Zustand.entwurf = (Zustand.config?.wallets || []).map((w) => ({ ...w }));
          if (Zustand.ansicht === "wallets") {
            zeichneWalletVerwaltung();
          }
        } catch (_) {
          /* Config optional */
        }
        const wid = walletId || (job.meta && job.meta.wallet_id) || "";
        if (wid && Zustand.ansicht === "wallet" && Zustand.walletId === wid) {
          try {
            await zeigeWallet(wid, { ohneEmpfang: true });
          } catch (_) {
            /* Ansicht optional */
          }
        }
      } else if (job.status === "cancelled") {
        logZeile(t("wallets.exportAddrJobCancelled", { name: walletName || "?" }));
      } else if (job.error) {
        logZeile(
          t("wallets.exportAddrJobFailed", { msg: job.error }),
          true,
        );
      }
    } catch (fehler) {
      clearInterval(Zustand.exportAddrTimer);
      Zustand.exportAddrTimer = null;
      logZeile(
        t("wallets.exportAddrJobFailed", {
          msg: (fehler && fehler.message) || String(fehler),
        }),
        true,
      );
    }
  };
  tick();
  Zustand.exportAddrTimer = setInterval(tick, 900);
}

/** Wallet-Export-Dateien als Klartext lesen (kein Base64 — große CSVs frieren sonst ein). */
function dateiAlsText(datei) {
  return new Promise((resolve, reject) => {
    const maxBytes = 25 * 1024 * 1024;
    if (datei && typeof datei.size === "number" && datei.size > maxBytes) {
      reject(new Error(
        t("wallets.exportFileTooLarge", {
          name: datei.name || "?",
          mb: Math.ceil(datei.size / (1024 * 1024)),
        }),
      ));
      return;
    }
    const leser = new FileReader();
    leser.onload = () => resolve(String(leser.result || ""));
    leser.onerror = () => reject(new Error(t("common.fileUnreadable")));
    leser.readAsText(datei);
  });
}

async function dateienAlsTextImportPayload(dateiListe) {
  const files = [];
  for (const datei of dateiListe) {
    const text = await dateiAlsText(datei);
    files.push({ name: datei.name || "export", text });
  }
  return { files };
}

async function starteSparrowImport(dateiListe, bestaetigt = false) {
  const kasten = $("#sparrow-befund");
  const knopf = $("#sparrow-import");
  if (knopf) knopf.disabled = true;
  if (kasten) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(t("wallets.exportImporting")));
  }
  const namen = (dateiListe || []).map((d) => d.name || "?").join(", ");
  logZeile(`Wallet-Export: lese ${dateiListe.length} Datei(en) — ${namen}`);
  try {
    let payload;
    try {
      payload = await dateienAlsTextImportPayload(dateiListe);
    } catch (fehler) {
      throw new Error(fehler.message || t("common.fileUnreadable"));
    }
    const files = (payload && payload.files) || [];
    if (!files.length) {
      throw new Error(t("wallets.exportNoFiles"));
    }
    logZeile(`Wallet-Export: sende ${files.length} Datei(en) an Server…`);
    const antwort = await api("/config/wallet-export-import", {
      methode: "POST",
      daten: { files, confirm: bestaetigt },
      timeoutMs: 180_000,
    });
    await nachWalletExportErfolg(antwort);
  } catch (fehler) {
    if (fehler && fehler.status === 409 && !bestaetigt) {
      const ok = window.confirm(
        `${fehler.message || ""}\n\n${t("wallets.saveAnyway")}?`,
      );
      if (ok) {
        if (knopf) knopf.disabled = false;
        await starteSparrowImport(dateiListe, true);
        return;
      }
    }
    const msg = (fehler && fehler.message) || t("wallets.exportFailed");
    if (kasten) {
      kasten.replaceChildren(hinweisZeile(msg));
    }
    meldung(msg, "krit");
    logZeile(`Wallet-Export: ${msg}`, true);
  } finally {
    if (knopf) knopf.disabled = false;
  }
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
    read_only: false,
    origin: "descriptor",
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
  // RegExp als String: ein Literal mit `\(` würde die Klammerbilanz der
  // statischen JS-Prüfung (ohne Regex-Literale) falsch negativ machen.
  if (new RegExp("\\b(sh|wsh|tr|wpkh|pkh|combo)\\s*\\(", "i").test(xpub)) {
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
    read_only: false,
    origin: "xpub",
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

