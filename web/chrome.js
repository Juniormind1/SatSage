/** App-Shell Bootstrap — aus app.js extrahiert (Modularisierung Slice 2).
 * zeichneFussVersion / logReleaseAlsErsteZeile / zeichneFussLocalOnly,
 * ladeConfig, start und Top-Level-UI-Bindungen am Ende von start().
 * Klassisches Script: Globals aus app.js + views. Kein import/export.
 * Laden nach chrome_nav.js; boot.js ruft start() auf.
 * Mittlerer Laden-Ballast (Peers/Kopf/Kurs/Chat/Wallet-Sync) bleibt in app.js.
 */

function zeichneFussVersion() {
  zeichneFussLocalOnly();
  const ziel = $("#fuss-version");
  if (!ziel) return;
  const ver = (Zustand.config?.version || "").trim();
  if (!ver) {
    ziel.textContent = "";
    return;
  }
  ziel.textContent = `v${ver} · `;
}

/**
 * Laufende SatSage-Version als erste Log-Zeile (einmalig, bleibt oben).
 */
function logReleaseAlsErsteZeile() {
  const ziel = $("#log-text");
  if (!ziel) return;
  const ver = (Zustand.config?.version || "").trim();
  if (!ver) return;
  const text = `SatSage v${ver}`;
  let zeile = ziel.querySelector(".log-zeile.log-release");
  if (zeile) {
    const meldung = zeile.querySelector(".log-meldung");
    if (meldung) meldung.textContent = text;
    if (ziel.firstChild !== zeile) ziel.prepend(zeile);
    return;
  }
  zeile = document.createElement("div");
  zeile.className = "log-zeile log-release";
  const zeit = document.createElement("span");
  zeit.className = "log-zeit";
  zeit.textContent = logZeitstempel();
  zeile.append(zeit);
  const meldung = document.createElement("span");
  meldung.className = "log-meldung";
  meldung.textContent = text;
  zeile.append("  ", meldung);
  ziel.prepend(zeile);
}

// "nur lokal erreichbar" nur behaupten, wenn es stimmt. Hinter Umbrels
// app_proxy bindet der Server an 0.0.0.0 und ist aus dem ganzen LAN offen.
function zeichneFussLocalOnly() {
  const ziel = $("#fuss-local-only");
  if (!ziel) return;
  ziel.hidden = Zustand.config?.local_only !== true;
}


/**
 * Start-Log der Wallet-Vorbereitung, Zeile für Zeile.
 * Nicht awaiten: der Strom endet erst, wenn das letzte Wallet gelesen ist.
 */
function folgeBootLog() {
  Zustand.bootLogLive = true;
  if (Zustand.bootLogGestartet) return;
  Zustand.bootLogGestartet = true;
  const kopf = { ...tokenKopf(), Accept: "application/x-ndjson" };
  fetch("/api/boot-log", { headers: kopf, credentials: "same-origin" })
    .then((antwort) => {
      if (!antwort.ok || !antwort.body) return null;
      const typ = antwort.headers.get("Content-Type") || "";
      if (!typ.includes("ndjson")) return null;
      return leseBootLogStream(antwort);
    })
    .catch(() => {});
}

async function leseBootLogStream(antwort) {
  const leser = antwort.body.getReader();
  const decoder = new TextDecoder();
  let puffer = "";
  const nimm = (obj) => {
    if (obj.log) logZeile(obj.log, undefined, obj.wallet || "");
    if (obj.wallet_summary && typeof nimmWalletSobaldFertig === "function") {
      nimmWalletSobaldFertig(obj.wallet_summary);
    }
    if (obj.done && obj.context_bereit) {
      Zustand.contextBereit = true;
      if (typeof EmpfangPuls !== "undefined") EmpfangPuls.stop();
      if (Zustand.walletId && typeof ladeEmpfang === "function") {
        ladeEmpfang(Zustand.walletId).catch(() => {});
      }
      if (typeof holeWalletMempoolNachStart === "function") holeWalletMempoolNachStart();
    }
  };
  while (true) {
    const { done, value } = await leser.read();
    if (done) break;
    puffer += decoder.decode(value, { stream: true });
    const zeilen = puffer.split("\n");
    puffer = zeilen.pop();
    for (const zeile of zeilen) {
      if (!zeile.trim()) continue;
      try { nimm(JSON.parse(zeile)); } catch (_) { /* halbe Zeile */ }
    }
  }
  if (puffer.trim()) {
    try { nimm(JSON.parse(puffer)); } catch (_) { /* Ende ohne Zeile */ }
  }
}

async function ladeConfig() {
  const altQuellen = Zustand.config?.sources;
  Zustand.config = await api("/config");
  Zustand.config.sources = uebernehmeQuellenErreichbarkeit(
    altQuellen, Zustand.config.sources,
  );
  // Offene Server-Peers sofort in die Pille — ohne erneute Netzprobe.
  if (Array.isArray(Zustand.config.live_p2p_peers) && Zustand.config.live_p2p_peers.length) {
    nimmLiveP2pPeers(Zustand.config.live_p2p_peers);
  }
  Zustand.entwurf = Zustand.config.wallets.map((w) => ({ ...w }));
  setzeEnvPfad(Zustand.config.env_path);
  Zustand.llmStatus = Zustand.config.llm || Zustand.llmStatus;
  zeichneKopfStatus(Zustand.config.sources);
  zeichneSteuerEinstellungen();
  zeichneUiLang();
  // Theme: localStorage hat Vorrang; fehlt es, greift config/Default.
  try {
    if (!localStorage.getItem(UI_THEME_STORAGE) && Zustand.config?.ui_theme) {
      setzeUiTheme(Zustand.config.ui_theme);
    } else {
      setzeUiTheme(liesUiTheme());
    }
  } catch (_) {
    setzeUiTheme(liesUiTheme());
  }
  zeichneUiTheme();
  fuellOnchainHinweisTexte();
  zeichneStartSync();
  zeichneAppPasswort();
  zeichneLernhinweiseEinstellung();
  setzeEmpfangLabSenden();
  zeichneLlmEinstellungen();
  zeichneStatusMailEinstellungen();
  zeichneMempoolStatus();
  zeichneChatAnbindung();
  zeichneNav();
  ggfEnvScrambleUnlockDialog();
  zeichneFussVersion();
  logReleaseAlsErsteZeile();
  if (typeof fuelleSchatzWallets === "function") fuelleSchatzWallets();
  if (Zustand.config?.lernhinweise_plebs) {
    wendeAlleLernTooltipsAn().catch(() => {});
  }
  if (Zustand.contextBereit === false) {
    zeichneEmpfangLeer(t("dock.empfangPuls"), { puls: true });
  } else if (Zustand.walletId) {
    ladeEmpfang(Zustand.walletId).catch(() => {});
  } else {
    zeichneEmpfangLeer();
  }
  const hopFeld = $("#sank-hops");
  if (hopFeld) {
    const cap = Number(Zustand.config?.sanktion_max_hops_cap) || 20;
    hopFeld.max = String(cap);
  }
}

/**
 * Sprachdatei laden, bevor Cache und Verbindungen angefasst werden.
 * Die Sprache des Servers kommt aus /api/auth/status (ohne Cache-Zugriff),
 * nicht erst aus /api/config. Ohne Antwort entscheidet die Browsersprache;
 * ladeConfig gleicht danach mit config.ui_lang ab.
 */
async function ladeSprachstringsVorStart(auth) {
  if (!window.SatSageI18n) return;
  let configLang = auth?.ui_lang || null;
  if (!configLang && !window.SatSageI18n.storedLang()) {
    try {
      const antwort = await fetch("/api/auth/status", { credentials: "same-origin" });
      if (antwort.ok) configLang = (await antwort.json())?.ui_lang || null;
    } catch (_) {
      configLang = null;
    }
  }
  try {
    await window.SatSageI18n.initI18n({ configLang });
  } catch (_) {
    /* Sprachdatei fehlt — t() bleibt leer statt Roh-Keys; ladeConfig meldet den Fehler */
  }
}

/** Start-Nachzug: einmal, nachdem die erste Ansicht aus dem Cache da ist. */
function meldeGuiBereit() {
  if (Zustand._guiBereitGemeldet) return;
  Zustand._guiBereitGemeldet = true;
  api("/gui-bereit", { methode: "POST", daten: {} }).catch(() => {});
}

async function start() {
  // Status immer zuerst — auch wenn sessionStorage noch ein altes ?t= hat.
  // Hinter StartOS ist das kein Zugang. Mit gesetztem Passwort kommt der
  // Login aus den Einstellungen, nicht der Kasten „Token fehlt“.
  let auth = null;
  try {
    const antwort = await fetch("/api/auth/status", { credentials: "same-origin" });
    if (antwort.ok) auth = await antwort.json();
  } catch (_) {
    auth = null;
  }
  const start9 = auth && auth.managed_by === "start9";
  const umbrel = auth && auth.managed_by === "umbrel";
  if (start9) {
    // Konsolen-Token nicht mitschicken. Ein leerer oder fremder Header
    // darf die Proxy-Anmeldung nicht überstimmen.
    window.SatSageOhneToken = true;
    try { sessionStorage.removeItem("xpq-token"); } catch (_) {}
  }
  if (auth && auth.authenticated) {
    // Sitzung, oder StartOS ohne Passwort.
  } else if (auth && (auth.password_set || umbrel)) {
    location.replace("/login?next=/");
    return;
  } else if (start9) {
    // Kein Konsolen-Token, kein StartOS-Passwort. Oberfläche offen,
    // bis der Nutzer in den Einstellungen selbst eines setzt.
  } else if (!Token) {
    $("#token-fehlt").hidden = false;
    return;
  }
  // Reihenfolge: 1. Oberfläche (Gerüst), 2. Sprachstrings, 3. Cache,
  // Verbindungen und der Rest (Wallet-Kontext, Empfangsadresse, Quellen).
  // Bis 2. fertig ist, zeigt nichts einen technischen Schlüssel.
  $("#app").hidden = false;
  // DE/EN sofort klickbar — nicht erst nach Jobs/Header-Sync am Ende von start().
  bindeSprachUmschalter();
  const logKnopf = $("#log-anzeige");
  // Standard an (wie bisher checked); Klick toggelt wie DE/EN.
  setzeLogSichtbar(logKnopf ? logKnopf.classList.contains("aktiv") : true);
  if (logKnopf) {
    logKnopf.addEventListener("click", () => {
      const an = !document.querySelector(".buehne")?.classList.contains("log-an");
      setzeLogSichtbar(an);
    });
  }
  macheLogZiehbar();
  macheDockSpalter();
  macheEmpfangSpalter();
  if (typeof bindeNavLeiste === "function") bindeNavLeiste();
  setzeLernhinweiseDelegates();
  setzeEmpfangAnimDebug();
  setzeEmpfangLabSenden();

  await ladeSprachstringsVorStart(auth);

  // Vor /api/config: Login kann die GUI öffnen, während Adressen noch
  // abgeleitet werden. Kein QR, bis der Kontext steht. Atem und Titel erst
  // jetzt — vorher stünden „receive.breath.0“ / „dock.empfangPuls“ da.
  if (typeof zeichneEmpfangLeer === "function") {
    zeichneEmpfangLeer(t("dock.empfangPuls"), { puls: true });
  }
  setzeEmpfangPoll();
  if (typeof aktualisiereSchatzKnopf === "function") aktualisiereSchatzKnopf();
  // Vorbereitung läuft schon. Zeilen kommen, sobald sie entstehen — start()
  // wartet diesen Strom nicht ab.
  folgeBootLog();

  try {
    await ladeConfig();
    Zustand.contextBereit = Zustand.config?.context_bereit !== false;
    if (Zustand.contextBereit && typeof EmpfangPuls !== "undefined") {
      EmpfangPuls.stop();
    }
    if (window.SatSageI18n) {
      // Catalog steht schon (ladeSprachstringsVorStart) — lädt nicht neu,
      // setzt nur data-i18n über das, was ladeConfig gezeichnet hat.
      await window.SatSageI18n.initI18n({
        configLang: Zustand.config?.ui_lang,
      });
      zeichneUiLang();
      zeichneSteuerEinstellungen();
      zeichneKopfStatus(Zustand.config?.sources || []);
    }
    // Select-Listener falls #ui-lang erst jetzt im DOM wäre (idempotent).
    bindeSprachUmschalter();
    for (const radio of document.querySelectorAll('input[name="ui-theme"]')) {
      radio.addEventListener("change", () => {
        if (radio.checked) speichereUiTheme();
      });
    }
    window.addEventListener("satsage:lang", () => {
      if (window.SatSageI18n) window.SatSageI18n.applyDom(document);
      // data-i18n-html setzt .env-pfad zurück auf „.env“ — echten Pfad wiederherstellen.
      if (Zustand.config?.env_path) setzeEnvPfad(Zustand.config.env_path);
      zeichneNav();
      zeichneFussVersion();
      zeichneUiLang();
      zeichneKursPille();
      zeichneSteuerEinstellungen();
      // Template und dynamische Texte ohne data-i18n neu setzen.
      if (window.SatSageI18n) {
        window.SatSageI18n.applyDom($("#vorlage-wallet"));
      }
      const chatLeer = document.querySelector("#chat-verlauf .chat-leer");
      if (chatLeer) chatLeer.textContent = t("dock.empty");
      if (Zustand.empfang && Zustand.walletId) {
        ladeEmpfang(Zustand.walletId, { still: true }).catch(() => {});
      } else {
        zeichneEmpfangLeer();
      }
      if (typeof zeichneEinrichtung === "function" && $("#einrichtung") && !$("#einrichtung").hidden) {
        zeichneEinrichtung();
      }
      if (typeof zeichneWalletVerwaltung === "function" && Zustand.ansicht === "wallets") {
        zeichneWalletVerwaltung();
      }
      if (typeof ladeGefahrWallets === "function" && Zustand.ansicht === "wallets") {
        ladeGefahrWallets();
      }
      if (typeof zeichneQuellen === "function" && Zustand.ansicht === "datenquellen") {
        zeichneQuellen(Zustand.config?.sources || []);
        if (typeof ladeListenStatus === "function") ladeListenStatus();
        if (typeof ladeLabelStatus === "function") ladeLabelStatus();
        if (typeof ladeKursHistorie === "function") ladeKursHistorie();
        if (typeof zeichneMempoolStatus === "function") zeichneMempoolStatus();
      }
      if (typeof zeichneKopfStatus === "function") {
        zeichneKopfStatus(Zustand.config?.sources || []);
      }
      if (typeof zeichneLlmPille === "function" && Zustand.llmStatus) {
        zeichneLlmPille();
      }
      if (typeof aktualisiereNavWerkzeuge === "function") aktualisiereNavWerkzeuge();
      if (Zustand.ansicht === "wallet" && Zustand.walletId) {
        zeigeWallet(Zustand.walletId).catch(() => {});
      } else if (Zustand.ansicht === "steuerjahr" && typeof ladeSteuerjahr === "function") {
        ladeSteuerjahr();
      } else if (Zustand.ansicht === "trace" && typeof ladeTraceListe === "function") {
        ladeTraceListe();
      } else if (Zustand.ansicht === "sanktionen" && typeof ladeSankCache === "function") {
        ladeSankCache();
      }
    });
    await ladeLlmStatus({ check: Boolean(Zustand.llmStatus?.configured), laut: true });
    setzeLlmTakt();
    // Kurs parallel: darf den Start nicht blockieren (früher „Load failed“ / Hänger).
    ladeSpotkurs({ laut: true }).finally(() => setzeKursTakt());
    // Tageshistorie für „ausgegeben am …“-EUR; Fehler → Spot-Fallback (gelb).
    ladeKursSerie().catch(() => {});
    await ladeJobsNav();
    setzeJobsTakt();
    await sichereHeaderVorab();
    folgeHeaderJob();
    folgeWalletSyncJob();
  } catch (fehler) {
    const status = fehler && fehler.status;
    if (status === 401 || status === 403) {
      if (auth && (auth.password_set || auth.managed_by === "umbrel" || auth.managed_by === "start9")) {
        location.replace("/login?next=/");
        return;
      }
    }
    $("#app").hidden = true;
    $("#token-fehlt").hidden = false;
    const mono = $("#token-fehlt").querySelector(".mono");
    if (mono && auth && auth.managed_by === "start9") mono.hidden = true;
    $("#token-fehlt").querySelector("h1").textContent = t("common.noConnection");
    $("#token-fehlt").querySelector("p").textContent = fehler.message;
    return;
  }

  document
    .querySelector('[data-ansicht="wallets"]')
    .addEventListener("click", () => oeffneVerwaltung("wallets"));
  document
    .querySelector('[data-ansicht="einstellungen"]')
    .addEventListener("click", () => oeffneVerwaltung("einstellungen"));
  document
    .querySelector('[data-ansicht="datenquellen"]')
    .addEventListener("click", () => oeffneVerwaltung("datenquellen"));
  document
    .querySelector('[data-ansicht="trace"]')
    .addEventListener("click", () => {
      // Schon in Herkunft: nichts ändern (Fokus bleibt Fokus, Liste bleibt Liste).
      // Volle Liste nur beim Wechsel *aus einer anderen* Ansicht.
      if (Zustand.ansicht === "trace") {
        zeichneNav();
        return;
      }
      Zustand.traceFokus = null;
      zeigeAnsicht("trace");
      ladeTraceListe({ erzwingen: true });
    });
  document
    .querySelector('[data-ansicht="steuerjahr"]')
    .addEventListener("click", () => {
      zeigeAnsicht("steuerjahr");
      ladeSteuerjahrMitKandidaten();
    });
  document
    .querySelector('[data-ansicht="tools"]')
    .addEventListener("click", () => {
      zeigeAnsicht("tools");
      const feld = $("#tools-adresse");
      if (feld) feld.focus();
      if (typeof fuelleSchatzWallets === "function") fuelleSchatzWallets();
      if (typeof aktualisiereSchatzKnopf === "function") aktualisiereSchatzKnopf();
      if (typeof merkeLaufendeSchatzsuche === "function") merkeLaufendeSchatzsuche();
      if (typeof merkeLaufendeCacheSuche === "function") merkeLaufendeCacheSuche();
    });
  document
    .querySelector('[data-ansicht="sanktionen"]')
    .addEventListener("click", async () => {
      zeigeAnsicht("sanktionen");
      fuellSankWallets();
      // Laufenden Check bevorzugen — sonst verschwindet die Fortschrittszeile.
      try {
        const nav = Zustand.jobsNav?.jobs || [];
        const laufend = nav.find(
          (j) => j.kind === "sanctions-check" && j.running,
        );
        if (laufend?.id) {
          bindeSanktionsCheckJob(laufend.id, { hops: laufend.meta?.hops });
          return;
        }
        if (Zustand.sanktionsCheckJobId) {
          bindeSanktionsCheckJob(Zustand.sanktionsCheckJobId);
          return;
        }
      } catch (_) {
        /* Cache laden */
      }
      ladeSankCache();
    });

  $("#sank-start").addEventListener("click", starteSanktionsCheck);
  $("#sank-verwerfen").addEventListener("click", verwerfeSankCache);

  $("#trace-start").addEventListener("click", starteTrace);
  $("#trace-ziel").addEventListener("keydown", (e) => {
    if (e.key === "Enter") starteTrace();
  });
  $("#jahr-wahl").addEventListener("change", () => ladeSteuerjahrMitKandidaten());
  $("#frist-wahl").addEventListener("change", async () => {
    try {
      const ergebnis = await api("/config/steuer", {
        methode: "PUT",
        daten: {
          haltefrist_jahre: Number($("#frist-wahl").value),
          stichtag: steuerEinstellungen().stichtag_iso || "",
          anschaffung: steuerEinstellungen().anschaffung || "juengste",
        },
      });
      if (Zustand.config) Zustand.config.steuer = ergebnis.steuer;
      zeichneSteuerEinstellungen();
    } catch (_) {
      /* Auswertung trotzdem mit der gewählten Frist */
    }
    ladeSteuerjahr();
  });
  $("#steuer-uebernehmen").addEventListener("click", speichereSteuerEinstellungen);
  const personBtn = $("#person-uebernehmen");
  if (personBtn) personBtn.addEventListener("click", speicherePersonEinstellungen);
  const berichtWalletBtn = $("#bericht-wallet-uebernehmen");
  if (berichtWalletBtn) {
    berichtWalletBtn.addEventListener("click", speichereBerichtWalletEinstellungen);
  }
  const berichtWalletEcht = $("#bericht-wallet-echt");
  if (berichtWalletEcht) {
    berichtWalletEcht.addEventListener("change", () => {
      setzeBerichtWalletAliasAktiv(berichtWalletEcht.checked);
    });
  }
  bindeAppPasswortUi();
  zeichneAppPasswort();
  const lernPlebs = $("#lernhinweise-plebs");
  if (lernPlebs) {
    lernPlebs.addEventListener("change", () => {
      speichereLernhinweiseEinstellung().catch((fehler) => {
        meldung(fehler.message || String(fehler), "krit");
      });
    });
  }
  const empfangZurueck = $("#empfang-lern-zurueck");
  if (empfangZurueck) {
    empfangZurueck.addEventListener("click", () => loescheLernThema());
  }
  const empfangQr = $("#empfang-qr");
  if (empfangQr) {
    empfangQr.addEventListener("click", () => {
      if (Zustand.empfang?.lern && Zustand.empfang.url) {
        oeffneLernUrl(Zustand.empfang.url);
      }
    });
  }
  const empfangAdresse = $("#empfang-adresse");
  if (empfangAdresse) {
    empfangAdresse.addEventListener("click", (e) => {
      if (Zustand.empfang?.lern && Zustand.empfang.url) {
        e.preventDefault();
        e.stopPropagation();
        oeffneLernUrl(Zustand.empfang.url);
      }
    });
  }
  const startSync = $("#start-sync");
  if (startSync) {
    startSync.addEventListener("change", speichereStartSync);
  }
  const startSyncKnown = $("#start-sync-known-only");
  if (startSyncKnown) {
    startSyncKnown.addEventListener("change", speichereStartSync);
  }
  const llmKnopf = $("#llm-uebernehmen");
  if (llmKnopf) {
    llmKnopf.addEventListener("click", speichereLlmEinstellungen);
  }
  const statusMailKnopf = $("#status-mail-uebernehmen");
  if (statusMailKnopf) {
    statusMailKnopf.addEventListener("click", speichereStatusMailEinstellungen);
  }
  const chatForm = $("#chat-eingabe");
  const chatFeld = $("#chat-feld");
  if (chatForm) {
    chatForm.addEventListener("submit", (ereignis) => {
      ereignis.preventDefault();
      sendeChatZeile();
    });
  }
  if (chatFeld) {
    chatFeld.addEventListener("input", () => {
      Zustand.slashIndex = 0;
      zeichneSlashListe(chatFeld.value);
    });
    chatFeld.addEventListener("keydown", (ereignis) => {
      const offen = $("#chat-slash") && !$("#chat-slash").hidden;
      if (ereignis.key === "ArrowRight" || ereignis.key === "Tab") {
        if (vervollstaendigeSlash(chatFeld)) {
          ereignis.preventDefault();
        }
        return;
      }
      if (!offen) return;
      if (ereignis.key === "ArrowDown") {
        ereignis.preventDefault();
        Zustand.slashIndex += 1;
        zeichneSlashListe(chatFeld.value);
      } else if (ereignis.key === "ArrowUp") {
        ereignis.preventDefault();
        Zustand.slashIndex -= 1;
        zeichneSlashListe(chatFeld.value);
      } else if (ereignis.key === "Escape") {
        ereignis.preventDefault();
        schliesseSlashListe();
      }
    });
    chatFeld.addEventListener("blur", () => {
      window.setTimeout(schliesseSlashListe, 0);
    });
  }
  // Steuerjahr „klären“ sitzt in der Scorecard (wird in zeichneSteuerjahr gebunden).
  $("#trace-herkunft-alle").addEventListener("click", () => herkunftAllerUtxos({
    knopf: "#trace-herkunft-alle",
    lauf: "#trace-herkunft-lauf",
    text: "#trace-herkunft-text",
    abbruch: "#trace-herkunft-abbruch",
    meldung: "#trace-meldung",
    danach: ladeTraceListe,
  }));
  const herkunftTief = $("#herkunft-tief-knopf");
  if (herkunftTief) {
    herkunftTief.addEventListener("click", () => starteHerkunftVollstaendig());
  }
  $("#verlauf-erheben").addEventListener("click", verlaufErheben);
  $("#export-csv").addEventListener("click", () => ladeExport("export.csv"));
  $("#export-bericht").addEventListener("click", () => ladeExport("bericht.html"));
  const saLaden = $("#sa-laden");
  if (saLaden) {
    saLaden.addEventListener("click", () => ladeSelbstanzeigeKandidaten({ laut: true }));
  }
  const saHtml = $("#sa-html");
  if (saHtml) saHtml.addEventListener("click", () => ladeSelbstanzeigeExport("html"));
  const saCsv = $("#sa-csv");
  if (saCsv) saCsv.addEventListener("click", () => ladeSelbstanzeigeExport("csv"));
  const saTxid = $("#sa-txid");
  if (saTxid) {
    saTxid.addEventListener("keydown", (e) => {
      if (e.key === "Enter") ladeSelbstanzeigeKandidaten({ laut: true });
    });
  }

  $("#sort-wahl").addEventListener("change", () => {
    // Andere Reihenfolge: vorgeladene Seiten gehören zur alten (ISSUES P2).
    if (typeof pagerCachesVerwerfen === "function") pagerCachesVerwerfen();
    zeigeWallet(Zustand.walletId);
  });
  $("#tip-sync-knopf")?.addEventListener("click", starteTipSync);
  $("#rescan-knopf").addEventListener("click", starteRescan);
  $("#verlauf-knopf").addEventListener("click", starteVerlaufsscan);
  $("#rescan-abbruch").addEventListener("click", brichRescanAb);
  $("#hinzufuegen").addEventListener("click", fuegeWalletHinzu);
  $("#deskriptor-import").addEventListener("click", oeffneDeskriptorImport);
  $("#deskriptor-datei").addEventListener("change", liesDeskriptorDatei);
  const sparrowImport = $("#sparrow-import");
  if (sparrowImport) sparrowImport.addEventListener("click", oeffneSparrowImport);
  const sparrowDateien = $("#sparrow-dateien");
  if (sparrowDateien) sparrowDateien.addEventListener("change", liesSparrowDateien);
  const exportSuchen = $("#wallet-export-suchen");
  if (exportSuchen) exportSuchen.addEventListener("click", starteWalletExportSuche);
  aktualisiereWalletExportImportKnopf();

  let deskriptorTimer = null;
  $("#neuer-deskriptor").addEventListener("input", () => {
    clearTimeout(deskriptorTimer);
    deskriptorTimer = setTimeout(pruefeDeskriptor, 400);
  });
  $("#neuer-xpub").addEventListener("keydown", (e) => {
    if (e.key === "Enter") fuegeWalletHinzu();
  });
  const neuerName = $("#neuer-name");
  if (neuerName) {
    neuerName.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const xpub = $("#neuer-xpub");
        if (xpub) xpub.focus();
      }
    });
  }
  const unrefLoeschen = $("#cache-unreferenziert-loeschen");
  if (unrefLoeschen) {
    unrefLoeschen.addEventListener("click", loescheUnreferenziertenCache);
  }
  const cacheDashRefresh = $("#cache-dash-aktualisieren");
  if (cacheDashRefresh) {
    cacheDashRefresh.addEventListener("click", () => {
      ladeCacheDashboard();
    });
  }
  bindeKopfFilter();
  aktualisiereKopfFilterFuerAnsicht();
  $("#privatsphaere-entfernen").addEventListener("click", verwerfeErstenXpub);
  $("#privatsphaere-ok").addEventListener("click", akzeptiereOhneSicherenNode);
  $("#oeffentliche-electrum-nein").addEventListener("click", lehneOeffentlicheElectrumAb);
  $("#oeffentliche-electrum-ja").addEventListener("click", erlaubeOeffentlicheElectrum);
  $("#oeffentliche-electrum-warnung").addEventListener("keydown", (e) => {
    if ($("#oeffentliche-electrum-warnung").hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      lehneOeffentlicheElectrumAb();
      return;
    }
    if (e.key === "Enter" && e.target.id !== "oeffentliche-electrum-ja") {
      e.preventDefault();
      lehneOeffentlicheElectrumAb();
    }
  });
  $("#privatsphaere-warnung").addEventListener("keydown", (e) => {
    if ($("#privatsphaere-warnung").hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      verwerfeErstenXpub();
      return;
    }
    if (e.key === "Enter" && e.target.id !== "privatsphaere-ok") {
      e.preventDefault();
      verwerfeErstenXpub();
    }
  });
  $("#listen-update").addEventListener("click", aktualisiereListen);
  const listenImport = $("#listen-import");
  if (listenImport) listenImport.addEventListener("click", starteListenImport);
  const listenDateien = $("#listen-dateien");
  if (listenDateien) listenDateien.addEventListener("change", liesListenImportDateien);
  $("#cache-leeren").addEventListener("click", () => setzeCacheLeerenBestaetigung(true));
  $("#cache-leeren-abbruch").addEventListener("click", () => setzeCacheLeerenBestaetigung(false));
  $("#cache-leeren-ok").addEventListener("click", leereGesamtenCache);
  $("#mempool-speichern").addEventListener("click", speichereMempool);
  const managedMempoolSave = document.getElementById("mempool-speichern-managed");
  if (managedMempoolSave) managedMempoolSave.addEventListener("click", speichereMempool);
  const kursEur = $("#kurs-import-eur");
  if (kursEur) kursEur.addEventListener("click", () => starteKursImport("EUR"));
  const kursUsd = $("#kurs-import-usd");
  if (kursUsd) kursUsd.addEventListener("click", () => starteKursImport("USD"));
  const kursDatei = $("#kurs-csv-datei");
  if (kursDatei) kursDatei.addEventListener("change", liesKursCsvDatei);
  const kursSync = $("#kurs-historie-sync");
  if (kursSync) {
    kursSync.addEventListener("click", () => starteKursHistorieSync());
  }
  const boerseImport = $("#boerse-csv-import");
  if (boerseImport) boerseImport.addEventListener("click", starteBoersenCsvImport);
  const boerseDatei = $("#boerse-csv-datei");
  if (boerseDatei) boerseDatei.addEventListener("change", liesBoersenCsvDatei);
  $("#mempool-url").addEventListener("keydown", (e) => {
    if (e.key === "Enter") speichereMempool();
  });
  const managedMempool = document.getElementById("mempool-url-managed");
  if (managedMempool) managedMempool.addEventListener("keydown", (e) => {
    if (e.key === "Enter") speichereMempool();
  });
  $("#quelle-pruefen").addEventListener("click", async (ereignis) => {
    try {
      await testeEigenenNode(ereignis.currentTarget);
    } catch (fehler) {
      meldung(t("ui.hard.4c7456e438", { msg: fehler.message }), "krit");
    }
  });

  window.addEventListener("beforeunload", (e) => {
    if (entwurfGeaendert()) e.preventDefault();
  });

  // Einstieg: mit Wallets → erstes Wallet. Ohne Wallets und ohne echte
  // Datenquelle (P2P „eh da“ zählt nicht) → Datenquellen; sonst Wallets.
  // Der Start-Nachzug wartet auf diese erste Cache-Ansicht.
  let ersteAnsicht = Promise.resolve();
  if ((Zustand.config.wallets || []).length > 0) {
    // Kontext noch im Aufbau: Wallet zeigen, Empfangsadresse nicht.
    // Ein während der Vorbereitung schon angeklicktes Wallet bleibt stehen.
    const einstieg = einstiegsWalletId();
    if (einstieg) {
      ersteAnsicht = Promise.resolve(zeigeWallet(
        einstieg, { ohneEmpfang: Zustand.contextBereit === false },
      ));
    }
  } else if (walletsManaged()) {
    oeffneVerwaltung("einstellungen");
  } else if (brauchtDatenquellenZuerst()) {
    oeffneVerwaltung("datenquellen");
  } else {
    oeffneVerwaltung("wallets");
  }
  ersteAnsicht.finally(() => { meldeGuiBereit(); });

  einrichtungBeimStart();
  // Still nachladen: Server hält Connections; lauter Neu-Test nur über Knopf.
  pruefePeersLeise();
  // Sprach-Handler bereits früh via bindeSprachUmschalter(); hier nur Sync.
  zeichneUiLang();
}

