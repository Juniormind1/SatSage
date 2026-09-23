/** Einstellungen-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: Globals aus app.js (Zustand, api, t, $, meldung, …).
 * Kein import/export. Laden nach app.js, vor datenquellen.js.
 * Header-Pillen (LLM/Kurs) und oeffneVerwaltung bleiben in app.js.
 */

/* --- passwort-scramble --- */
// ---------------------------------------------------------------------------
// Einstellungen
// ---------------------------------------------------------------------------


/** Kompatibilität: Wallet-Seite neu zeichnen (früher alles unter Einstellungen). */
function zeichneEinstellungen() {
  zeichneWalletVerwaltung();
}


function zeichneAppEinstellungen() {
  zeichneSteuerEinstellungen();
  zeichneUiLang();
  zeichneUiTheme();
  zeichneAppPasswort();
  zeichneStartSync();
  zeichneStatusMailEinstellungen();
  zeichneMempoolStatus();
  setzeEnvPfad(Zustand.config?.env_path);
}

/**
 * Meldung in der Passwort-Karte (nicht #speicher-meldung — die ist nur unter Wallets).
 */
function appPasswortMeldung(text, art) {
  const kasten = $("#app-passwort-meldung");
  if (!kasten) {
    try { meldung(text, art); } catch (_) { /* ignore */ }
    return;
  }
  kasten.className = `hinweis app-passwort-meldung hinweis-${art || "krit"}`;
  setzeText(kasten, text);
  kasten.hidden = !text;
  if (art === "gut" && text) {
    setTimeout(() => {
      if (kasten.textContent === text) kasten.hidden = true;
    }, 5000);
  }
}

/** Live: ✕ rot bis neu===wiederholung und nicht leer, dann ✓ grün. */
function aktualisiereAppPasswortMatch() {
  const mark = $("#app-passwort-match");
  if (!mark) return;
  const neu = String($("#app-passwort-neu")?.value || "");
  const neu2 = String($("#app-passwort-neu2")?.value || "");
  mark.classList.remove("match-ok", "match-bad", "match-leer");
  if (!neu && !neu2) {
    mark.textContent = "—";
    mark.classList.add("match-leer");
    mark.title = "";
    return;
  }
  if (neu && neu2 && neu === neu2) {
    mark.textContent = "✓";
    mark.classList.add("match-ok");
    mark.title = t("settings.password.matchOk");
    return;
  }
  mark.textContent = "✕";
  mark.classList.add("match-bad");
  mark.title = t("settings.password.matchBad");
}

/** Einstellungen · optionales App-Passwort + .env-Scramble. */
function zeichneAppPasswort() {
  const karte = $("#karte-app-passwort");
  if (!karte) return;
  const gesetzt = Boolean(Zustand.config?.password_set);
  const aktuell = $("#app-passwort-aktuell");
  const entfernen = $("#app-passwort-entfernen");
  const zusatz = $("#app-passwort-zusatz");
  if (aktuell) {
    aktuell.disabled = !gesetzt;
    if (!gesetzt) aktuell.value = "";
    aktuell.placeholder = gesetzt ? "" : t("settings.password.currentPh");
  }
  if (entfernen) entfernen.disabled = !gesetzt;
  if (zusatz) {
    zusatz.textContent = gesetzt
      ? t("settings.password.zusatzOn")
      : t("settings.password.zusatzOff");
    zusatz.setAttribute(
      "data-i18n",
      gesetzt ? "settings.password.zusatzOn" : "settings.password.zusatzOff",
    );
  }
  aktualisiereAppPasswortMatch();
  bindeAppPasswortUi();
}

function _appPasswortFelderLeeren({ auchAktuell = true } = {}) {
  if (auchAktuell) {
    const a = $("#app-passwort-aktuell");
    if (a) a.value = "";
  }
  const n = $("#app-passwort-neu");
  const n2 = $("#app-passwort-neu2");
  if (n) n.value = "";
  if (n2) n2.value = "";
  aktualisiereAppPasswortMatch();
}

async function speichereAppPasswort() {
  const neu = String($("#app-passwort-neu")?.value || "");
  const neu2 = String($("#app-passwort-neu2")?.value || "");
  const aktuell = String($("#app-passwort-aktuell")?.value || "");
  const gesetzt = Boolean(Zustand.config?.password_set);
  aktualisiereAppPasswortMatch();
  if (!neu) {
    appPasswortMeldung(t("settings.password.emptyNew"), "krit");
    return;
  }
  if (neu !== neu2) {
    appPasswortMeldung(t("settings.password.mismatch"), "krit");
    return;
  }
  if (gesetzt && !aktuell) {
    appPasswortMeldung(t("settings.password.needCurrent"), "krit");
    return;
  }
  const knopf = $("#app-passwort-setzen");
  if (knopf) knopf.disabled = true;
  appPasswortMeldung(t("settings.password.saving"), "warn");
  try {
    const ergebnis = await api("/config/app-password", {
      methode: "PUT",
      daten: {
        current_password: aktuell,
        new_password: neu,
        confirm: neu2,
      },
    });
    if (!Zustand.config) Zustand.config = {};
    Zustand.config.password_set = true;
    if (ergebnis && ergebnis.env_scramble) {
      Zustand.config.env_scramble = ergebnis.env_scramble;
    }
    _appPasswortFelderLeeren();
    zeichneAppPasswort();
    appPasswortMeldung(t("settings.password.saved"), "gut");
    try {
      await ladeConfig();
    } catch (e) {
      appPasswortMeldung(
        t("settings.password.saved") + " (" + ((e && e.message) || e) + ")",
        "warn",
      );
    }
    zeichneAppPasswort();
  } catch (fehler) {
    appPasswortMeldung(
      t("settings.password.saveFailed", {
        msg: (fehler && fehler.message) || String(fehler),
      }),
      "krit",
    );
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

async function entferneAppPasswort() {
  const aktuellFeld = $("#app-passwort-aktuell");
  const aktuell = String(aktuellFeld?.value || "");
  if (!Boolean(Zustand.config?.password_set)) {
    appPasswortMeldung(t("settings.password.zusatzOff"), "warn");
    return;
  }
  if (!aktuell) {
    appPasswortMeldung(t("settings.password.needCurrent"), "krit");
    if (aktuellFeld) {
      aktuellFeld.disabled = false;
      aktuellFeld.focus();
    }
    return;
  }
  const knopf = $("#app-passwort-entfernen");
  if (knopf) knopf.disabled = true;
  appPasswortMeldung(t("settings.password.removing"), "warn");
  try {
    // POST statt DELETE+Body — Firefox/manche Stacks brechen DELETE mit Body ab
    // („NetworkError when attempting to fetch resource“).
    const ergebnis = await api("/config/app-password", {
      methode: "POST",
      daten: { action: "delete", current_password: aktuell },
    });
    if (!Zustand.config) Zustand.config = {};
    Zustand.config.password_set = Boolean(ergebnis.password_set);
    if (ergebnis.env_scramble) {
      Zustand.config.env_scramble = ergebnis.env_scramble;
    }
    _appPasswortFelderLeeren();
    zeichneAppPasswort();
    appPasswortMeldung(t("settings.password.removed"), "gut");
    try { await ladeConfig(); } catch (_) { /* ignore */ }
    zeichneAppPasswort();
  } catch (fehler) {
    appPasswortMeldung(
      t("settings.password.removeFailed", {
        msg: (fehler && fehler.message) || String(fehler),
      }),
      "krit",
    );
  } finally {
    zeichneAppPasswort();
  }
}

function bindeAppPasswortUi() {
  const karte = $("#karte-app-passwort");
  if (!karte || karte.dataset.passBound === "1") return;
  karte.dataset.passBound = "1";
  karte.addEventListener("click", (e) => {
    const el = e.target instanceof Element ? e.target : null;
    if (!el) return;
    if (el.closest("#app-passwort-setzen")) {
      e.preventDefault();
      speichereAppPasswort();
    } else if (el.closest("#app-passwort-entfernen")) {
      e.preventDefault();
      entferneAppPasswort();
    }
  });
  karte.addEventListener("input", (e) => {
    const el = e.target instanceof Element ? e.target : null;
    if (!el) return;
    if (el.id === "app-passwort-neu" || el.id === "app-passwort-neu2") {
      aktualisiereAppPasswortMatch();
    }
  });
  karte.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const el = e.target instanceof Element ? e.target : null;
    if (!el) return;
    if (
      el.id === "app-passwort-neu"
      || el.id === "app-passwort-neu2"
      || el.id === "app-passwort-aktuell"
    ) {
      e.preventDefault();
      speichereAppPasswort();
    }
  });
}

// Global für onclick-Fallback / Konsole.
try {
  window.speichereAppPasswort = speichereAppPasswort;
  window.entferneAppPasswort = entferneAppPasswort;
} catch (_) { /* ignore */ }

/** Nach Server-Neustart: gobbledigook entsperren. */
async function unlockEnvScramble(password) {
  const ergebnis = await api("/config/unlock-env", {
    methode: "POST",
    daten: { password: String(password || "") },
  });
  if (Zustand.config && ergebnis.env_scramble) {
    Zustand.config.env_scramble = ergebnis.env_scramble;
  }
  await ladeConfig();
  return ergebnis;
}

function ggfEnvScrambleUnlockDialog() {
  const st = Zustand.config?.env_scramble;
  if (!st || !st.locked || !st.active) return;
  const pw = window.prompt(
    t("settings.password.unlockPrompt") !== "settings.password.unlockPrompt"
      ? t("settings.password.unlockPrompt")
      : t("ui.hard.f9683fc0c6"),
  );
  if (pw == null || pw === "") return;
  unlockEnvScramble(pw).then(() => {
    meldung(
      t("settings.password.unlocked") !== "settings.password.unlocked"
        ? t("settings.password.unlocked")
        : "Konfiguration entsperrt.",
      "gut",
    );
  }).catch((fehler) => {
    meldung(
      (fehler && fehler.message) || String(fehler),
      "krit",
    );
  });
}

/* --- steuer-person-sync --- */
function zeichneSteuerEinstellungen() {
  const steuer = steuerEinstellungen();
  const jahre = steuer.haltefrist_jahre_auswahl;
  const gewaehlt = steuer.haltefrist_jahre;
  fuelleHaltefristAuswahl($("#steuer-haltefrist"), gewaehlt, jahre);
  // Steuerjahr-Dropdown teilt dieselben Labels (Sprache / Catalog-Nachzug).
  fuelleHaltefristAuswahl($("#frist-wahl"), gewaehlt, jahre);
  const datum = $("#steuer-stichtag");
  if (datum) datum.value = steuer.stichtag_iso || "";
  const anschaffung = $("#steuer-anschaffung");
  if (anschaffung) {
    anschaffung.value =
      steuer.anschaffung === "aelteste" ? "aelteste" : "juengste";
  }
  zeichnePersonEinstellungen();
}

function personEinstellungen() {
  const p = Zustand.config?.person || {};
  return {
    name: p.name || "Donald Duck",
    steuernummer: p.steuernummer || "0/8/15",
    anschrift: p.anschrift || "Entenhausen",
    email: p.email || "",
    finanzamt: p.finanzamt || "",
    finanzamt_anschrift: p.finanzamt_anschrift || "",
    sachbearbeiter: p.sachbearbeiter || "",
  };
}

function zeichnePersonEinstellungen() {
  const p = personEinstellungen();
  const name = $("#person-name");
  const sn = $("#person-steuernummer");
  const adr = $("#person-anschrift");
  const mail = $("#person-email");
  const fa = $("#person-finanzamt");
  const faAdr = $("#person-finanzamt-anschrift");
  const sb = $("#person-sachbearbeiter");
  if (name) name.value = p.name;
  if (sn) sn.value = p.steuernummer;
  if (adr) adr.value = p.anschrift;
  if (mail) mail.value = p.email;
  if (fa) fa.value = p.finanzamt;
  if (faAdr) faAdr.value = p.finanzamt_anschrift;
  if (sb) sb.value = p.sachbearbeiter;
}

async function speicherePersonEinstellungen() {
  const knopf = $("#person-uebernehmen");
  if (knopf) knopf.disabled = true;
  try {
    const ergebnis = await api("/config/person", {
      methode: "PUT",
      daten: {
        name: $("#person-name")?.value || "",
        steuernummer: $("#person-steuernummer")?.value || "",
        anschrift: $("#person-anschrift")?.value || "",
        email: $("#person-email")?.value || "",
        finanzamt: $("#person-finanzamt")?.value || "",
        finanzamt_anschrift: $("#person-finanzamt-anschrift")?.value || "",
        sachbearbeiter: $("#person-sachbearbeiter")?.value || "",
      },
    });
    if (Zustand.config) Zustand.config.person = ergebnis.person;
    zeichnePersonEinstellungen();
    meldung(
      t("settings.personSaved") !== "settings.personSaved"
        ? t("settings.personSaved")
        : t("ui.hard.516a1e0970"),
      "gut",
    );
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

function setzeKnownOnlySichtbarkeit(parentAn = undefined) {
  const zeile = $("#start-sync-known-only-zeile");
  const box = $("#start-sync-known-only");
  if (!zeile || !box) return;
  const an = parentAn === undefined
    ? Boolean(
      Zustand.config?.wallets_immer_aktuell
      ?? Zustand.config?.wallets_beim_start_aktualisieren,
    )
    : Boolean(parentAn);
  zeile.hidden = !an;
  box.disabled = !an;
  if (!an) box.checked = false;
}

function zeichneStartSync() {
  const box = $("#start-sync");
  if (!box) return;
  const an = Boolean(
    Zustand.config?.wallets_immer_aktuell
    ?? Zustand.config?.wallets_beim_start_aktualisieren,
  );
  box.checked = an;
  const known = $("#start-sync-known-only");
  if (known) {
    known.checked = an && Boolean(Zustand.config?.wallets_nur_bekannte_utxos);
  }
  setzeKnownOnlySichtbarkeit(an);
  setzeTipSyncSichtbarkeit(an);
}

async function speichereStartSync(ereignis) {
  const box = $("#start-sync");
  if (!box) return;
  const an = box.checked;
  const knownBox = $("#start-sync-known-only");
  const nurBekannte = an && Boolean(knownBox?.checked);
  const vonKnownOnly = Boolean(
    ereignis && knownBox && ereignis.target === knownBox,
  );
  // Hide/show immediately; the config response below remains authoritative.
  setzeKnownOnlySichtbarkeit(an);
  setzeTipSyncSichtbarkeit(an);
  try {
    const ergebnis = await api("/config/start-sync", {
      methode: "PUT",
      daten: {
        enabled: an,
        nur_bekannte_utxos: nurBekannte,
      },
    });
    if (Zustand.config) {
      const v = Boolean(
        ergebnis.wallets_immer_aktuell
        ?? ergebnis.wallets_beim_start_aktualisieren,
      );
      Zustand.config.wallets_immer_aktuell = v;
      Zustand.config.wallets_beim_start_aktualisieren = v;
      Zustand.config.wallets_nur_bekannte_utxos = Boolean(
        ergebnis.wallets_nur_bekannte_utxos,
      );
      if (ergebnis.wallet_watch) {
        Zustand.config.wallet_watch = ergebnis.wallet_watch;
      }
    }
    zeichneStartSync();
    // Tip-Nachzug sofort mitverfolgen (ohne Server-Neustart).
    const jobId = ergebnis.wallet_sync_job_id || ergebnis.job?.id;
    if (an && jobId) {
      if (Zustand.config) {
        Zustand.config.wallet_sync_job_id = jobId;
      }
      folgeWalletSyncJob(jobId, ergebnis.job);
      if (!vonKnownOnly) logZeile(t("settings.startSyncStarted"));
      await ladeJobsNav();
    }
    let text = t("settings.startSyncOff");
    if (an && vonKnownOnly) {
      text = nurBekannte
        ? t("settings.startSyncKnownOnlyOn")
        : t("settings.startSyncKnownOnlyOff");
    } else if (an && nurBekannte) {
      text = t("settings.startSyncKnownOnlyOn");
    } else if (an) {
      text = t("settings.startSyncOn");
    }
    meldung(text, "gut");
  } catch (fehler) {
    zeichneStartSync();
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  }
}

async function speichereSteuerEinstellungen() {
  const knopf = $("#steuer-uebernehmen");
  knopf.disabled = true;
  try {
    const ergebnis = await api("/config/steuer", {
      methode: "PUT",
      daten: {
        haltefrist_jahre: Number($("#steuer-haltefrist").value),
        stichtag: $("#steuer-stichtag").value,
        anschaffung: $("#steuer-anschaffung")?.value || "juengste",
      },
    });
    if (Zustand.config) Zustand.config.steuer = ergebnis.steuer;
    zeichneSteuerEinstellungen();
    fuelleHaltefristAuswahl(
      $("#frist-wahl"),
      ergebnis.steuer.haltefrist_jahre,
      ergebnis.steuer.haltefrist_jahre_auswahl,
    );
    meldung(t("settings.taxSaved"), "gut");
    if (Zustand.ansicht === "steuerjahr") ladeSteuerjahrMitKandidaten();
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    knopf.disabled = false;
  }
}

/* --- llm-form --- */
function zeichneLlmEinstellungen() {
  const s = Zustand.llmStatus || Zustand.config?.llm || {};
  const url = $("#llm-url");
  const modell = $("#llm-modell");
  const anbieter = $("#llm-anbieter");
  const optIn = $("#llm-remote-opt-in");
  const key = $("#llm-api-key");
  if (url) url.value = s.base_url || "";
  if (modell) modell.value = s.modell || "";
  if (anbieter) anbieter.value = s.anbieter || "";
  if (optIn) optIn.checked = Boolean(s.remote_opt_in);
  if (key) {
    key.value = "";
    key.placeholder = s.api_key_set
      ? "gesetzt — leer lassen, um zu behalten"
      : "optional, nur bei API-Key";
  }
}

async function ladeLlmStatus({ check = false, laut = false } = {}) {
  if (laut && check) logZeile(t("ui.hard.7628c50446"));
  try {
    Zustand.llmStatus = await api(check ? "/llm/status?check=1" : "/llm/status");
  } catch (fehler) {
    if (laut) logZeile(t("ui.hard.f559917bc5", { msg: fehler.message }), true);
    return;
  }
  if (laut && check) {
    const s = Zustand.llmStatus;
    if (s.reachable) {
      logZeile(`Assistent erreichbar. ${s.banner}`, true);
    } else if (s.configured) {
      const grund = s.probe_error ? `: ${s.probe_error}` : ".";
      logZeile(t("ui.hard.151407fe6c", { grund }), true);
    } else {
      logZeile(t("ui.hard.16d796814c"));
    }
  }
  zeichneLlmPille();
  zeichneChatAnbindung();
}

function setzeLlmTakt() {
  if (Zustand.llmTimer) return;
  Zustand.llmTimer = setInterval(() => {
    const konfiguriert = Boolean(Zustand.llmStatus?.configured);
    ladeLlmStatus({ check: konfiguriert });
  }, LLM_TAKT_MS);
}

async function speichereLlmEinstellungen() {
  const knopf = $("#llm-uebernehmen");
  if (knopf) knopf.disabled = true;
  const keyFeld = $("#llm-api-key");
  const daten = {
    base_url: $("#llm-url") ? $("#llm-url").value : "",
    modell: $("#llm-modell") ? $("#llm-modell").value : "",
    anbieter: $("#llm-anbieter") ? $("#llm-anbieter").value : "",
    remote_opt_in: Boolean($("#llm-remote-opt-in") && $("#llm-remote-opt-in").checked),
  };
  if (keyFeld && keyFeld.value.trim()) daten.api_key = keyFeld.value.trim();
  try {
    const ergebnis = await api("/config/llm", {
      methode: "PUT",
      daten,
    });
    if (Zustand.config) Zustand.config.llm = ergebnis.llm;
    Zustand.llmStatus = ergebnis.llm;
    if (keyFeld) keyFeld.value = "";
    zeichneLlmEinstellungen();
    zeichneLlmPille();
    zeichneChatAnbindung();
    meldung(t("settings.llmSaved"), "gut");
    await ladeLlmStatus({ check: true, laut: true });
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

/* --- status-mail --- */
function zeichneStatusMailEinstellungen() {
  const s = Zustand.config?.status_mail || {};
  const optIn = $("#status-mail-opt-in");
  const to = $("#status-mail-to");
  const host = $("#status-mail-host");
  const port = $("#status-mail-port");
  const user = $("#status-mail-user");
  const pass = $("#status-mail-password");
  const from = $("#status-mail-from");
  const tls = $("#status-mail-starttls");
  if (optIn) optIn.checked = Boolean(s.opt_in);
  if (to) to.value = s.to || "";
  if (host) host.value = s.smtp_host || "";
  if (port) port.value = s.smtp_port != null ? String(s.smtp_port) : "587";
  if (user) user.value = s.smtp_user || "";
  if (from) from.value = s.smtp_from || "";
  if (tls) tls.checked = s.starttls !== false;
  if (pass) {
    pass.value = "";
    pass.placeholder = s.smtp_password_set
      ? "gesetzt — leer lassen, um zu behalten"
      : "optional";
  }
}

async function speichereStatusMailEinstellungen() {
  const knopf = $("#status-mail-uebernehmen");
  if (knopf) knopf.disabled = true;
  const passFeld = $("#status-mail-password");
  const daten = {
    opt_in: Boolean($("#status-mail-opt-in") && $("#status-mail-opt-in").checked),
    to: $("#status-mail-to") ? $("#status-mail-to").value : "",
    smtp_host: $("#status-mail-host") ? $("#status-mail-host").value : "",
    smtp_port: $("#status-mail-port") ? $("#status-mail-port").value : "587",
    smtp_user: $("#status-mail-user") ? $("#status-mail-user").value : "",
    smtp_from: $("#status-mail-from") ? $("#status-mail-from").value : "",
    starttls: Boolean(
      !$("#status-mail-starttls") || $("#status-mail-starttls").checked,
    ),
  };
  if (passFeld && passFeld.value.trim()) {
    daten.smtp_password = passFeld.value.trim();
  }
  try {
    const ergebnis = await api("/config/status-mail", {
      methode: "PUT",
      daten,
    });
    if (Zustand.config) Zustand.config.status_mail = ergebnis.status_mail;
    if (passFeld) passFeld.value = "";
    zeichneStatusMailEinstellungen();
    meldung(
      ergebnis.status_mail?.configured
        ? t("settings.mail.savedActive")
        : t("settings.mail.saved"),
      "gut",
    );
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

/* --- lang-theme --- */
function zeichneUiLang() {
  const aktuell = uiSprache();
  const wahl = $("#ui-lang");
  if (wahl) wahl.value = aktuell === "en" ? "en" : "de";
  const deBtn = $("#lang-de");
  const enBtn = $("#lang-en");
  if (deBtn) deBtn.classList.toggle("aktiv", aktuell === "de");
  if (enBtn) enBtn.classList.toggle("aktiv", aktuell === "en");
}

/**
 * UI-Sprache setzen (Header-Knöpfe und Einstellungen-Select).
 *
 * Reihenfolge absichtlich: Katalog + DOM zuerst (sofort sichtbar), dann
 * UI_LANG speichern und Fiat nachladen. Persistenz-Fehler brechen den
 * Sprachwechsel nicht ab.
 */
async function wechsleUiLang(ziel, { meldungZeigen = true } = {}) {
  if (!window.SatSageI18n) {
    console.warn("wechsleUiLang: SatSageI18n fehlt");
    return;
  }
  const lang = ziel === "en" ? "en" : "de";
  if (uiSprache() === lang) {
    zeichneUiLang();
    return;
  }
  try {
    // Ohne persistEnv — Sprache wechselt auch wenn /config/ui-lang hängt.
    await window.SatSageI18n.setLang(lang, { persistEnv: null });
  } catch (fehler) {
    console.error("wechsleUiLang setLang", fehler);
    if (typeof meldung === "function") {
      meldung(String(fehler.message || fehler), "krit");
    }
    return;
  }
  if (Zustand.config) Zustand.config.ui_lang = lang;
  zeichneUiLang();
  zeichneKursPille();

  // Persistenz und Fiat parallel, blockieren die UI nicht.
  api("/config/ui-lang", {
    methode: "PUT",
    daten: { ui_lang: lang },
    timeoutMs: 8000,
  }).then((ergebnis) => {
    if (Zustand.config && ergebnis && ergebnis.ui_lang) {
      Zustand.config.ui_lang = ergebnis.ui_lang;
    }
  }).catch((fehler) => {
    console.warn("UI_LANG speichern:", fehler);
  });

  Zustand.kursSerie = null;
  Zustand.kursWarnGeloggt = false;
  Promise.all([
    ladeSpotkurs({ laut: false }),
    ladeKursSerie(),
  ]).then(() => {
    aktualisiereFiatAnzeigen();
  }).catch(() => {
    aktualisiereFiatAnzeigen();
  });

  if (meldungZeigen && typeof meldung === "function") {
    meldung(t("settings.language.saved"), "gut");
  }
}

async function speichereUiLang() {
  const wahl = $("#ui-lang");
  if (!wahl) return;
  const lang = wahl.value === "en" ? "en" : "de";
  await wechsleUiLang(lang);
}

/** Header DE/EN — früh binden, nicht erst nach Header-Job/Wallet-Sync. */
function bindeSprachUmschalter() {
  if (bindeSprachUmschalter._done) return;
  bindeSprachUmschalter._done = true;
  const deBtn = $("#lang-de");
  const enBtn = $("#lang-en");
  if (deBtn) {
    deBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      wechsleUiLang("de", { meldungZeigen: false });
    });
  }
  if (enBtn) {
    enBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      wechsleUiLang("en", { meldungZeigen: false });
    });
  }
  const langWahl = $("#ui-lang");
  if (langWahl && !langWahl.dataset.langBound) {
    langWahl.dataset.langBound = "1";
    langWahl.addEventListener("change", () => {
      speichereUiLang();
    });
  }
  zeichneUiLang();
}

const UI_THEME_STORAGE = "satsage-ui-theme";

function liesUiTheme() {
  try {
    const lokal = localStorage.getItem(UI_THEME_STORAGE);
    if (lokal === "dark" || lokal === "light") return lokal;
  } catch (_) { /* private mode */ }
  const ausConfig = Zustand.config?.ui_theme;
  if (ausConfig === "dark" || ausConfig === "light") return ausConfig;
  return "light";
}

function setzeUiTheme(theme) {
  const wert = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", wert);
  try {
    localStorage.setItem(UI_THEME_STORAGE, wert);
  } catch (_) { /* private mode */ }
  return wert;
}

function liesUiThemeAusRadios() {
  const aktiv = document.querySelector('input[name="ui-theme"]:checked');
  if (aktiv && (aktiv.value === "dark" || aktiv.value === "light")) {
    return aktiv.value;
  }
  return liesUiTheme();
}

function zeichneUiTheme() {
  const theme = liesUiTheme();
  const hell = $("#ui-theme-light");
  const dunkel = $("#ui-theme-dark");
  if (hell) hell.checked = theme === "light";
  if (dunkel) dunkel.checked = theme === "dark";
}

async function speichereUiTheme() {
  const theme = setzeUiTheme(liesUiThemeAusRadios());
  const ergebnis = await api("/config/ui-theme", {
    methode: "PUT",
    daten: { ui_theme: theme },
  });
  if (Zustand.config) Zustand.config.ui_theme = ergebnis.ui_theme;
  zeichneUiTheme();
  if (typeof meldung === "function") {
    meldung(t("settings.theme.saved"), "gut");
  }
}

