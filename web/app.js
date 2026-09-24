/* SatSage – know your sats.
   Kein Framework, kein Build-Schritt. */

"use strict";

// Token + API → web/api.js (Modularisierung UI-Schritt 1).
// Token / ApiFehler / api / übersetzeServerMeldung / Quelle- & Soft-Label-Helfer …


// Formatierung → web/format.js (Modularisierung UI-Schritt 4).
// SATS_BTC_MIN_DISPLAY / formatSats / $ / t / EmpfangPuls / apiSourceCheck …

// Zustand → web/state.js (Modularisierung UI-Schritt 2).
// Zustand / entwurfGeaendert / walletZeileGeaendert


// Navigation + Nav-Jobs → web/chrome_nav.js (Modularisierung Slice 2).
// sourcesFullyManaged / zeichneNav / zeigeAnsicht / oeffneVerwaltung / Job-Nav …




// Adress-Labels-UI → web/views/adress_labels.js (Modularisierung Slice 2).
// dateiAlsBase64 / Import-Payload / Listen-Import / meldungListen bleiben hier (geteilt).

/** Datei → Base64 (große Binärdateien, Chunk-weise). */
function dateiAlsBase64(datei) {
  return new Promise((resolve, reject) => {
    const leser = new FileReader();
    leser.onload = () => {
      try {
        const bytes = new Uint8Array(leser.result);
        const stuecke = [];
        const schritt = 0x8000;
        for (let i = 0; i < bytes.length; i += schritt) {
          stuecke.push(
            String.fromCharCode.apply(null, bytes.subarray(i, i + schritt)),
          );
        }
        resolve(btoa(stuecke.join("")));
      } catch (fehler) {
        reject(fehler);
      }
    };
    leser.onerror = () => reject(new Error(t("common.fileUnreadable")));
    leser.readAsArrayBuffer(datei);
  });
}

async function dateienAlsImportPayload(dateiListe) {
  const files = [];
  for (const datei of dateiListe) {
    files.push({
      name: datei.name,
      data_b64: await dateiAlsBase64(datei),
    });
  }
  return { files };
}

function starteListenImport() {
  const feld = $("#listen-dateien");
  if (feld) feld.click();
}

async function liesListenImportDateien(ereignis) {
  const liste = ereignis.target.files ? [...ereignis.target.files] : [];
  ereignis.target.value = "";
  if (!liste.length) return;
  const knopf = $("#listen-import");
  const update = $("#listen-update");
  if (knopf) knopf.disabled = true;
  if (update) update.disabled = true;
  $("#listen-lauf").hidden = false;
  setzeText($("#listen-text"), t("sources.listsImporting"));
  try {
    const payload = await dateienAlsImportPayload(liste);
    const ergebnis = await api("/sanctions/import", {
      methode: "POST",
      daten: payload,
      timeoutMs: 300_000,
    });
    const n = Number(ergebnis.adressen || 0).toLocaleString(formatLocale());
    meldungListen(t("sources.listsImportDone", { addresses: n }));
    logZeile(`Sanktionslisten importiert: ${n} Adressen.`, true);
  } catch (fehler) {
    meldungListen(t("common.loadFailed", { msg: fehler.message }));
    logZeile(t("ui.hard.18e555dc2b", { msg: fehler.message }), true);
  } finally {
    if (knopf) knopf.disabled = false;
    if (update) update.disabled = false;
    $("#listen-lauf").hidden = true;
    ladeListenStatus();
  }
}

function meldungListen(text) {
  const kasten = $("#speicher-meldung");
  kasten.className = "hinweis hinweis-krit";
  setzeText(kasten, text);
  kasten.hidden = false;
}

function pille(stufe, text) {
  const span = document.createElement("span");
  span.className = `pille pille-${stufe}`;
  span.textContent = text;
  return span;
}

async function pruefeSkripttyp(wallet, ausgabe, knopf) {
  knopf.disabled = true;
  ausgabe.hidden = false;
  ausgabe.replaceChildren(document.createTextNode("Leite Adressen ab…"));

  try {
    // Gespeicherte Wallets über die Kennung: Die Oberfläche kennt nur die
    // maskierte Fassung, der Server schlägt den vollen Schlüssel selbst nach.
    const ergebnis = await api("/wallets/probe", {
      methode: "POST",
      daten: wallet.is_new
        ? { xpub: wallet.xpub }
        : { wallet_id: wallet.id },
    });
    ausgabe.replaceChildren();

    const tabelle = document.createElement("table");
    for (const kandidat of ergebnis.candidates) {
      const zeile = document.createElement("tr");
      const typ = document.createElement("td");
      typ.textContent = kandidat.label;
      const adresse = document.createElement("td");
      adresse.className = "mono klein";
      adresse.textContent = kandidat.example_address;
      zeile.append(typ, adresse);
      tabelle.append(zeile);
    }
    ausgabe.append(tabelle);

    const hinweis = document.createElement("div");
    hinweis.className = "probe-hinweis";
    hinweis.textContent = ergebnis.note;
    ausgabe.append(hinweis);
  } catch (fehler) {
    ausgabe.replaceChildren(
      document.createTextNode(`Erkennung fehlgeschlagen: ${fehler.message}`)
    );
  } finally {
    knopf.disabled = false;
  }
}

function meldung(text, art) {
  const kasten = $("#speicher-meldung");
  kasten.className = `hinweis hinweis-${art}`;
  setzeText(kasten, text);
  kasten.hidden = false;
  if (art === "gut") {
    setTimeout(() => { kasten.hidden = true; }, 4000);
  }
}

function setzeCacheLeerenBestaetigung(an) {
  $("#cache-leeren").hidden = an;
  $("#cache-leeren-ok").hidden = !an;
  $("#cache-leeren-abbruch").hidden = !an;
  if (an) setzeWalletCacheBestaetigung(null);
}

function setzeWalletCacheBestaetigung(walletId) {
  for (const zeile of document.querySelectorAll("#cache-wallets .gefahr-zeile")) {
    const hier = zeile.dataset.walletId === walletId;
    const loeschen = zeile.querySelector(".wallet-cache-leeren");
    const ok = zeile.querySelector(".wallet-cache-ok");
    const abbruch = zeile.querySelector(".wallet-cache-abbruch");
    if (loeschen) loeschen.hidden = hier;
    if (ok) ok.hidden = !hier;
    if (abbruch) abbruch.hidden = !hier;
  }
}

async function ladeGefahrWallets() {
  const ziel = $("#cache-wallets");
  if (!ziel) return;
  try {
    const antwort = await api("/cache/wallets");
    zeichneGefahrWallets(antwort?.wallets || []);
  } catch (_) {
    // Fallback: nur konfigurierte Wallets aus der Config.
    const fallback = (Zustand.config?.wallets || [])
      .filter((w) => !w.is_new)
      .map((w) => ({
        id: w.id,
        name: w.name,
        configured: true,
        has_cache: Boolean(w.has_cache),
        utxo_count: w.utxo_count || 0,
        verlauf_count: w.export_verlauf_n || 0,
        stale: false,
      }));
    zeichneGefahrWallets(fallback);
  }
}

function zeichneGefahrWallets(wallets) {
  const ziel = $("#cache-wallets");
  if (!ziel) return;
  ziel.replaceChildren();
  const liste = Array.isArray(wallets) ? wallets : [];
  if (!liste.length) {
    const leer = document.createElement("p");
    leer.className = "gefahr-leer";
    leer.textContent = t("wallets.noWallets");
    ziel.append(leer);
    return;
  }
  for (const wallet of liste) {
    const zeile = document.createElement("div");
    zeile.className = "gefahr-zeile";
    if (wallet.stale || wallet.configured === false) {
      zeile.classList.add("gefahr-stale");
    }
    zeile.dataset.walletId = wallet.id;

    const name = document.createElement("span");
    name.className = "gefahr-name";
    name.textContent = wallet.name || t("common.wallet");
    if (wallet.stale || wallet.configured === false) {
      name.title = t("wallets.cacheStaleTitle");
      const badge = document.createElement("span");
      badge.className = "pille pille-warn";
      badge.textContent = t("wallets.cacheStaleBadge");
      badge.title = t("wallets.cacheStaleTitle");
      name.append(document.createTextNode(" "), badge);
    }

    const stand = document.createElement("span");
    stand.className = "gefahr-stand";
    const has = Boolean(wallet.has_cache)
      || Number(wallet.utxo_count || 0) > 0
      || Number(wallet.verlauf_count || 0) > 0;
    if (has) {
      const teile = [];
      const u = Number(wallet.utxo_count || 0);
      const v = Number(wallet.verlauf_count || 0);
      if (u > 0) {
        teile.push(u === 1 ? t("wallets.utxoOne") : t("wallets.utxoMany", { n: u }));
      }
      if (v > 0) {
        teile.push(v === 1 ? "1 Tx" : `${v} Tx`);
      }
      if (!teile.length) teile.push("Cache");
      // Konfigurierte: optional Frische-Hinweis
      const cfg = (Zustand.config?.wallets || []).find((w) => w.id === wallet.id);
      if (cfg && cacheHinweis(cfg)) teile.push(cacheHinweis(cfg));
      stand.textContent = teile.join(" · ");
    } else {
      stand.textContent = t("wallets.noCache");
    }

    const loeschen = document.createElement("button");
    loeschen.type = "button";
    loeschen.className = "knopf knopf-gefahr knopf-klein wallet-cache-leeren";
    loeschen.textContent = t("wallets.cacheDelete");
    loeschen.title = t("wallets.cacheDeleteTitle");
    loeschen.disabled = !has;
    loeschen.addEventListener("click", () => {
      setzeCacheLeerenBestaetigung(false);
      setzeWalletCacheBestaetigung(wallet.id);
    });

    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "knopf knopf-gefahr knopf-klein wallet-cache-ok";
    ok.textContent = t("wallets.cacheDeleteReally");
    ok.title = t("wallets.cacheDeleteReallyTitle", {
      name: wallet.name || wallet.id || "?",
    });
    ok.hidden = true;
    ok.addEventListener("click", () => leereWalletCache(wallet));

    const abbruch = document.createElement("button");
    abbruch.type = "button";
    abbruch.className = "knopf knopf-klein wallet-cache-abbruch";
    abbruch.textContent = t("common.cancel");
    abbruch.hidden = true;
    abbruch.addEventListener("click", () => setzeWalletCacheBestaetigung(null));

    zeile.append(name, stand, loeschen, ok, abbruch);
    ziel.append(zeile);
  }
}

async function leereWalletCache(wallet) {
  const kasten = $("#cache-leeren-meldung");
  kasten.hidden = true;
  setzeWalletCacheBestaetigung(null);
  const nameVorab = wallet.name || wallet.id || t("wallets.thisWallet");
  logZeile(`Lösche ${nameVorab}`, undefined, nameVorab);
  try {
    const ergebnis = await api(`/cache/${encodeURIComponent(wallet.id)}`, {
      methode: "DELETE",
    });
    Zustand.traceListe = null;
    Zustand.steuer = null;
    const n = (ergebnis.utxo_eintraege || 0)
      + (ergebnis.verlauf_eintraege || 0)
      + (ergebnis.herkunft_eintraege || 0);
    const name = ergebnis.wallet_name || wallet.name;
    const stale = wallet.stale || wallet.configured === false;
    const text = n
      ? (stale
        ? t("ui.hard.087dcf6171", { name, n })
        : t("ui.hard.96e1d96d33", { name, n }))
      : t("ui.hard.482eb153dd", { name });
    kasten.className = "hinweis hinweis-gut";
    setzeText(kasten, text);
    kasten.hidden = false;
    logZeile(text, undefined, name);
    for (const z of ergebnis.logs || []) {
      const s = String(z || "").trim();
      // Start/Ende loggt die UI selbst (Timestamps um den API-Call).
      if (!s || s === t("ui.hard.7bf2df499b") || /^Lösche [^:]/.test(s)) continue;
      logZeile(s, undefined, name);
    }
    logZeile(t("ui.hard.7bf2df499b"), undefined, name);
    await ladeConfig();
    zeichneEinstellungen();
    await ladeGefahrWallets();
    await ladeUnreferenziertenCache();
    if (Zustand.ansicht === "wallet" && Zustand.walletId === wallet.id) {
      await zeigeWallet(Zustand.walletId);
    }
  } catch (fehler) {
    logZeile(t("ui.hard.7bf2df499b"), true, nameVorab);
    kasten.className = "hinweis hinweis-krit";
    setzeText(kasten, t("ui.hard.4b44b452e9", { msg: fehler.message }));
    kasten.hidden = false;
  }
}

async function leereGesamtenCache() {
  const kasten = $("#cache-leeren-meldung");
  kasten.hidden = true;
  $("#cache-leeren-ok").disabled = true;
  try {
    const ergebnis = await api("/cache", { methode: "DELETE" });
    Zustand.traceListe = null;
    Zustand.steuer = null;
    setzeCacheLeerenBestaetigung(false);
    const n = (ergebnis.utxo_eintraege || 0) + (ergebnis.immutable_eintraege || 0);
    const text = n
      ? t("ui.hard.fb93960ca3", { n })
      : "Cache war bereits leer.";
    kasten.className = "hinweis hinweis-gut";
    setzeText(kasten, text);
    kasten.hidden = false;
    logZeile(text);
    await ladeConfig();
    zeichneEinstellungen();
    if (Zustand.ansicht === "wallet" && Zustand.walletId) {
      await zeigeWallet(Zustand.walletId);
    }
  } catch (fehler) {
    kasten.className = "hinweis hinweis-krit";
    setzeText(kasten, t("ui.hard.4b44b452e9", { msg: fehler.message }));
    kasten.hidden = false;
  } finally {
    $("#cache-leeren-ok").disabled = false;
  }
}

function hatNodeMitHoherPrivatsphaere() {
  const quellen = Zustand.config?.sources || [];
  return quellen.some(
    (q) =>
      (q.key === "own_fulcrum" && q.configured) ||
      (q.key === "bip158" && q.configured),
  );
}

/**
 * Der Sprung „keine Wallet → mindestens eine“ ohne eigenen Node.
 * Genau das ist der Daddeldu-Fall (leere .env plus erstes XPUB).
 */
function ersterXpubOhneSicherenNode(anzahlNeu) {
  const bisher = (Zustand.config?.wallets || []).length;
  return bisher === 0 && anzahlNeu > 0 && !hatNodeMitHoherPrivatsphaere();
}

function zeigePrivatsphaereWarnung() {
  const overlay = $("#privatsphaere-warnung");
  overlay.hidden = false;
  const sicher = $("#privatsphaere-entfernen");
  if (sicher) sicher.focus();
}

function verwerfeErstenXpub() {
  $("#privatsphaere-warnung").hidden = true;
  Zustand.entwurf = (Zustand.config?.wallets || []).map((w) => ({ ...w }));
  const nameFeld = $("#neuer-name");
  if (nameFeld) nameFeld.value = "";
  const xpubFeld = $("#neuer-xpub");
  if (xpubFeld) xpubFeld.value = "";
  const deskName = $("#neuer-deskriptor-name");
  if (deskName) deskName.value = "";
  const deskFeld = $("#neuer-deskriptor");
  if (deskFeld) deskFeld.value = "";
  const befund = $("#deskriptor-befund");
  if (befund) befund.hidden = true;
  zeichneEinstellungen();
}

function akzeptiereOhneSicherenNode() {
  $("#privatsphaere-warnung").hidden = true;
  speichereWallets(false, true, null);
}

function walletsNutzlast() {
  // Bestehende Wallets über ihre Kennung, neue über den eingefügten
  // Schlüssel — der volle XPUB verlässt den Server nie.
  return Zustand.entwurf.map((w) => ({
    // Neu angelegte Multisig kommt über ihren Deskriptor, neue Single-Sig
    // über den XPUB, bestehende über ihre Kennung — der volle Schlüssel
    // verlässt den Server nie.
    ...(w.is_new
      ? (w.descriptor ? { descriptor: w.descriptor } : { xpub: w.xpub })
      : { id: w.id }),
    name: w.name,
    script_type: w.script_type,
    max_addresses: w.max_addresses,
    read_only: Boolean(w.read_only),
    ...(w.origin ? { origin: w.origin } : {}),
  }));
}

/**
 * Fragt nach, ob der Cache entfernter Wallets mit weg soll.
 *
 * Rückgabe: true = löschen, false = behalten, null = keine Entfernung.
 * confirm-Abbrechen bedeutet „Cache behalten“, nicht „Speichern abbrechen“.
 */
async function frageCacheBeiWalletLoeschung(nutzlast) {
  let vorschau;
  try {
    vorschau = await api("/config/wallets/cache-vorschau", {
      methode: "POST",
      daten: { wallets: nutzlast },
    });
  } catch (fehler) {
    meldung(t("ui.hard.592e956ae3", { msg: fehler.message }), "krit");
    return false;
  }
  const entfernt = vorschau.entfernt || [];
  if (!entfernt.length) return null;

  const namen = entfernt.map((e) => e.wallet_name || e.wallet_id).join(", ");
  const groesse = vorschau.groesse_label || "0 MB";
  const mb = Number(vorschau.groesse_mb || 0);
  const mbText = Number.isFinite(mb)
    ? `${mb.toLocaleString(formatLocale(), {
        minimumFractionDigits: mb >= 0.1 || mb === 0 ? 1 : 3,
        maximumFractionDigits: 3,
      })} MB`
    : groesse;
  const zeilen = [
    entfernt.length === 1
      ? `Du entfernst das Wallet „${namen}“.`
      : `Du entfernst ${entfernt.length} Wallets: ${namen}.`,
    "",
    t("sources.hard.d5d69df339", { mb: mbText }),
    "",
    "OK = Cache löschen",
    "Abbrechen = Wallet weg, Cache behalten",
  ];
  return window.confirm(zeilen.join("\n"));
}

async function speichereWallets(
  bestaetigt = false,
  privatsphaereOk = false,
  cacheEntfernteLoeschen = null,
  loeschNamenHinweis = null,
) {
  if (Zustand.walletSpeichernLaeuft) return;
  if (!privatsphaereOk && ersterXpubOhneSicherenNode(Zustand.entwurf.length)) {
    zeigePrivatsphaereWarnung();
    return;
  }
  const idsVorher = new Set(
    (Zustand.config?.wallets || []).map((w) => w.id).filter(Boolean),
  );
  const hatteNeue = Zustand.entwurf.some((w) => w.is_new);
  const behaltenIds = new Set(
    Zustand.entwurf.filter((w) => !w.is_new && w.id).map((w) => w.id),
  );
  const entferntVorab = (Zustand.config?.wallets || []).filter(
    (w) => w.id && !behaltenIds.has(w.id),
  );
  const loeschNamen = (
    Array.isArray(loeschNamenHinweis) && loeschNamenHinweis.length
      ? loeschNamenHinweis
      : entferntVorab.map((w) => w.name || w.id || "?")
  ).filter(Boolean);
  Zustand.walletSpeichernLaeuft = true;
  setzeWalletSpeichernGesperrt(true);
  let loeschLogOffen = false;
  try {
    const nutzlast = walletsNutzlast();
    if (cacheEntfernteLoeschen === null) {
      const vielleichtEntfernt = entferntVorab.length > 0;
      if (vielleichtEntfernt) {
        if (loeschNamen.length) {
          for (const n of loeschNamen) {
            logZeile(`Lösche ${n}`, undefined, n);
          }
          loeschLogOffen = true;
        }
        const entscheidung = await frageCacheBeiWalletLoeschung(nutzlast);
        cacheEntfernteLoeschen = entscheidung === true;
      } else {
        cacheEntfernteLoeschen = false;
      }
    } else if (loeschNamen.length) {
      for (const n of loeschNamen) {
        logZeile(`Lösche ${n}`, undefined, n);
      }
      loeschLogOffen = true;
    }
    const ergebnis = await api("/config/wallets", {
      methode: "PUT",
      daten: {
        wallets: nutzlast,
        confirm: bestaetigt,
        cache_entfernte_loeschen: Boolean(cacheEntfernteLoeschen),
      },
    });
    for (const z of ergebnis.logs || []) {
      const s = String(z || "").trim();
      // Start/Ende loggt die UI selbst (Timestamps um den API-Call).
      if (!s || s === t("ui.hard.7bf2df499b") || /^Lösche [^:]/.test(s)) continue;
      logZeile(s);
    }
    let text = ergebnis.backup
      ? t("ui.hard.130ee40b9e", { backup: ergebnis.backup })
      : "Gespeichert.";
    if ((ergebnis.cache_entfernt || []).length) {
      text += ` Cache entfernt (${ergebnis.cache_groesse_label || "0 MB"}).`;
    }
    meldung(text, "gut");
    if (loeschLogOffen || (ergebnis.cache_entfernt || []).length) {
      logZeile(t("ui.hard.7bf2df499b"));
      loeschLogOffen = false;
    }
    await ladeConfig();
    zeichneEinstellungen();
    if (Zustand.ansicht === "wallets") ladeUnreferenziertenCache();
    if (hatteNeue) {
      const neu = (Zustand.config?.wallets || []).filter(
        (w) => w.id && !idsVorher.has(w.id),
      );
      if (neu.length) await nachNeuemWalletScannen(neu);
    }
  } catch (fehler) {
    if (loeschLogOffen) {
      logZeile(t("ui.hard.7bf2df499b"), true);
      loeschLogOffen = false;
    }
    if (fehler.brauchtBestaetigung) {
      warnungMitBestaetigung(fehler.message, cacheEntfernteLoeschen);
    } else {
      meldung(t("ui.hard.37ce417490", { msg: fehler.message }), "krit");
    }
  } finally {
    Zustand.walletSpeichernLaeuft = false;
    setzeWalletSpeichernGesperrt(false);
  }
}

function setzeWalletSpeichernGesperrt(an) {
  const hinzufuegen = $("#hinzufuegen");
  if (hinzufuegen) hinzufuegen.disabled = an;
  for (const knopf of document.querySelectorAll(".name-uebernehmen")) {
    if (an) knopf.disabled = true;
  }
  if (!an) aktualisiereSpeicherleiste();
}

/**
 * Zeigt eine Warnung, die der Benutzer übergehen darf.
 *
 * Anders als ein Fehler beschreibt sie eine Folge, keine Unmöglichkeit — die
 * Abwägung gehört dem Benutzer, nicht dem Programm.
 */
function warnungMitBestaetigung(text, cacheEntfernteLoeschen = false) {
  const kasten = $("#speicher-meldung");
  kasten.className = "hinweis hinweis-warn";
  kasten.replaceChildren();

  const inhalt = document.createElement("span");
  inhalt.textContent = text;

  const trotzdem = document.createElement("button");
  trotzdem.type = "button";
  trotzdem.className = "knopf knopf-klein";
  trotzdem.style.marginLeft = "auto";
  trotzdem.style.flex = "none";
  trotzdem.textContent = t("wallets.saveAnyway");
  trotzdem.addEventListener("click", () => {
    kasten.hidden = true;
    speichereWallets(true, true, cacheEntfernteLoeschen);
  });

  kasten.append(inhalt, trotzdem);
  kasten.hidden = false;
}

/**
 * Prüft den eingefügten Text und zeigt, was daraus würde.
 *
 * Ein Feld für zwei Wege: den von Hand getippten Deskriptor und den
 * kopierten Wallet-Export. Der Unterschied liegt im Text, nicht in der
 * Absicht — der Server zieht in beiden Fällen dasselbe heraus.
 *
 * Angezeigt wird immer die **erste Empfangsadresse**. Nur an ihr lässt sich
 * vor dem Speichern erkennen, ob wirklich die eigene Wallet gemeint ist: Ein
 * Deskriptor sieht auch dann richtig aus, wenn ein Schlüssel vertauscht wurde.
 */
async function pruefeDeskriptor() {
  const feld = $("#neuer-deskriptor");
  const kasten = $("#deskriptor-befund");
  const text = feld.value.trim();

  if (!text) {
    kasten.hidden = true;
    return;
  }

  let antwort;
  try {
    antwort = await api("/config/deskriptor", {
      methode: "POST", daten: { text },
    });
  } catch (fehler) {
    kasten.hidden = false;
    kasten.replaceChildren(hinweisZeile(fehler.message));
    return;
  }

  kasten.hidden = false;
  kasten.replaceChildren();

  if (antwort.fehler) {
    const zeile = document.createElement("div");
    zeile.className = "hinweis hinweis-warn";
    zeile.textContent = antwort.fehler;
    kasten.append(zeile);
    return;
  }

  for (const treffer of antwort.gefunden) {
    kasten.append(deskriptorKarte(treffer, feld));
  }
}

/** Ein gefundener Deskriptor mit Befund und Übernehmen-Knopf. */
function deskriptorKarte(treffer, feld) {
  const block = document.createElement("div");
  block.className = "deskriptor-treffer";

  const kopf = document.createElement("div");
  kopf.className = "knoten-oben";
  kopf.append(pille("gut", scriptTypLabel(treffer.script_type, treffer.script_type_label)));
  if (treffer.is_multisig && treffer.threshold) {
    const art = document.createElement("span");
    art.textContent = t("wallets.thresholdOf", { m: treffer.threshold, n: treffer.cosigner_count });
    kopf.append(art);
  } else if (treffer.is_multisig) {
    // Bei Policies mit mehreren Ausgabepfaden gibt es kein „m von n" — eine
    // Zahl zu erfinden wäre schlimmer als keine.
    const art = document.createElement("span");
    art.textContent = t("wallets.hard.48466a35e2", { n: treffer.cosigner_count });
    kopf.append(art);
  } else {
    const art = document.createElement("span");
    art.textContent = t("ui.hard.bed1685e9b");
    kopf.append(art);
  }
  if (treffer.bereits_vorhanden) {
    kopf.append(pille("warn", t("ui.hard.f76bf868bb")));
  }
  block.append(kopf);

  const adresse = document.createElement("div");
  adresse.className = "deskriptor-adresse";
  adresse.innerHTML =
    "<span class='feld-titel'>" + t("ui.hard.4707ae5509") + "</span>";
  const wert = document.createElement("div");
  wert.className = "mono";
  wert.textContent = treffer.erste_adresse || "—";
  adresse.append(wert);
  block.append(adresse);

  const keys = document.createElement("div");
  keys.className = "zart mono";
  keys.textContent = (treffer.xpubs_masked || []).join(", ");
  block.append(keys);

  const knopf = document.createElement("button");
  knopf.type = "button";
  knopf.className = "knopf knopf-primaer";
  knopf.textContent = treffer.bereits_vorhanden
    ? t("ui.hard.2e2eed6931")
    : t("ui.hard.5943084263");
  knopf.title = treffer.bereits_vorhanden
    ? t("ui.hard.e861e729a2")
    : t("ui.hard.105945eed3");
  knopf.addEventListener("click", () => {
    uebernimmDeskriptor(treffer);
    feld.value = "";
    $("#deskriptor-befund").hidden = true;
  });
  block.append(knopf);

  return block;
}

// Einrichtung-UI → web/views/einrichtung.js (Modularisierung Slice 2).

// ---------------------------------------------------------------------------
// Laden
// ---------------------------------------------------------------------------

function autoQuelle(quellen) {
  const auto = new Set([
    "own_fulcrum", "own_core", "bip158", "public_onion", "clearnet",
  ]);
  return (quellen || []).find((q) => q.configured && auto.has(q.key)) || null;
}

function eigenerNode(quellen) {
  const liste = quellen || [];
  const eigene = ["own_fulcrum", "own_core"]
    .map((key) => liste.find((q) => q.key === key))
    .filter((q) => q && q.configured);
  const verbunden = eigene.find((q) => q.reachable === true);
  if (verbunden) return verbunden;
  return eigene[0] || null;
}

function peerStatusAusQuellen(quellen, apiStand) {
  if (apiStand && apiStand.label) {
    return {
      n: apiStand.count || 0,
      kind: apiStand.kind || "none",
      label: apiStand.label,
      peers: apiStand.peers || [],
      gut: (apiStand.count || 0) > 0,
      software: apiStand.software || "",
    };
  }
  const nach = {};
  for (const q of quellen || []) nach[q.key] = q;
  const own = nach.own_fulcrum;
  const core = nach.own_core;
  const p2p = nach.bip158;
  const peersN = p2p?.peer_count || 0;
  const electrsN = own && own.reachable ? 1 : 0;
  const electrumName = String(own?.software || "").trim();

  if (peersN > 0 || electrsN > 0) {
    const hosts = [];
    if (peersN > 0) hosts.push(...(p2p.peer_hosts || []));
    if (electrsN > 0) hosts.push(...(own.peer_hosts || []));
    let kind = "p2p";
    if (peersN > 0 && electrsN > 0) kind = "mixed";
    else if (electrsN > 0) kind = "own";
    return {
      n: peersN + electrsN,
      kind,
      label: verbindungLabel({ peersN, electrsN, electrumName }),
      peers: hosts,
      peers_n: peersN,
      electrs_n: electrsN,
      software: electrumName,
      gut: true,
    };
  }
  if (core && core.reachable) {
    return {
      n: 1,
      kind: "own",
      label: "Eigener Peer verbunden",
      peers: core.peer_hosts || [],
      peers_n: 0,
      electrs_n: 0,
      gut: true,
    };
  }
  const onionN = nach.public_onion?.peer_count || 0;
  const clearN = nach.clearnet?.peer_count || 0;
  const pub = onionN + clearN;
  if (pub > 0) {
    const hosts = [
      ...(nach.public_onion?.peer_hosts || []),
      ...(nach.clearnet?.peer_hosts || []),
    ];
    return {
      n: pub,
      kind: "public",
      label: oeffentlicheElectrumLabel(onionN, clearN),
      peers: hosts,
      onion_electrs: onionN,
      clearnet_electrs: clearN,
      peers_n: 0,
      electrs_n: 0,
      gut: true,
    };
  }
  return {
    n: 0, kind: "none", label: "0 Peers verbunden", peers: [],
    peers_n: 0, electrs_n: 0, gut: false,
  };
}

/** Peers (BIP-158) + eigener Indexer nebeneinander. */
function verbindungLabel({
  peersN = 0, electrsN = 0, onionN = 0, clearN = 0, electrumName = "",
} = {}) {
  const teile = [];
  if (peersN > 0) teile.push(peersN === 1 ? "1 Peer" : `${peersN} Peers`);
  if (electrsN > 0) {
    const name = String(electrumName || "").trim() || "electrs";
    teile.push(electrsN === 1 ? `1 ${name}` : `${electrsN} ${name}`);
  }
  if (onionN > 0) teile.push(`${onionN} onion-electrs`);
  if (clearN > 0) teile.push(`${clearN} clearnet-electrs`);
  if (!teile.length) return "0 Peers verbunden";
  return `${teile.join(" · ")} verbunden`;
}

/** Öffentliche Electrum: onion-electrs / clearnet-electrs — nicht „Peers“. */
function oeffentlicheElectrumLabel(onionN, clearN) {
  const teile = [];
  if (onionN > 0) teile.push(`${onionN} onion-electrs`);
  if (clearN > 0) teile.push(`${clearN} clearnet-electrs`);
  if (!teile.length) return "0 electrs verbunden";
  return `${teile.join(" · ")} verbunden`;
}

function peerAenderungen(alt, neu) {
  if (!alt) return [];
  const altLabel = alt.label || "0 Peers verbunden";
  const neuLabel = neu.label || "0 Peers verbunden";
  if (altLabel !== neuLabel) {
    if (alt.n || neu.n) return [`Wechsel: ${altLabel} → ${neuLabel}`];
    return [];
  }
  // P2P/public/mixed: Host-Probe rotiert — kein Spam.
  if (alt.kind === "p2p" || alt.kind === "public" || alt.kind === "mixed") {
    return [];
  }
  const vorher = new Set(alt.peers || []);
  const nachher = new Set(neu.peers || []);
  const zeilen = [];
  for (const altHost of [...vorher].sort()) {
    if (!nachher.has(altHost)) zeilen.push(`Peer ${altHost} ausgefallen.`);
  }
  for (const neuHost of [...nachher].sort()) {
    if (!vorher.has(neuHost)) zeilen.push(`Neuer Peer ${neuHost}.`);
  }
  return zeilen;
}

/** Während eines UTXO-Scans: keine Host-Liste, nur Wechsel und < 3 Peers/electrs. */
function peerAenderungenFuerLog(alt, neu, scanLaeuft) {
  const roh = peerAenderungen(alt, neu);
  if (!scanLaeuft) return roh;
  const zeilen = roh.filter((z) => z.startsWith("Wechsel:"));
  if (neu.n < 3 && alt.n !== neu.n) {
    if (neu.kind === "public") {
      // Label schon „n onion-electrs · m clearnet-electrs verbunden“
      zeilen.push(`Nur ${neu.label}.`);
    } else {
      const wort = neu.n === 1 ? "Peer" : "Peers";
      zeilen.push(`Nur ${neu.n} ${wort} verbunden.`);
    }
  }
  return zeilen;
}

/** Normal: alle 30 s. Mit Electrs+Core: alle 10 Min (≈ Blockintervall). */
const PEER_TAKT_MS = 30_000;
const PEER_TAKT_RUHE_MS = 10 * 60_000;

function eigeneNodesBeideErreichbar(quellen) {
  const nach = {};
  for (const q of quellen || []) nach[q.key] = q;
  return (
    nach.own_fulcrum?.reachable === true &&
    nach.own_core?.reachable === true
  );
}

function peerTaktMs(quellen) {
  // Live-Peers während Scan kommen aus Job-Poll — kein 4s-Vollcheck
  // (der sonst Header-Tip-Jobs und Log-Spam auslöst).
  return eigeneNodesBeideErreichbar(quellen) ? PEER_TAKT_RUHE_MS : PEER_TAKT_MS;
}

/**
 * Live-Peers aus Job/Config in die BIP-158-Quelle und Kopf-Pille schreiben.
 * Ohne Netzprobe — die Connections hält der Scan bereits.
 *
 * @param {{ setzeStatus?: boolean }} opts  setzeStatus=false: nur Quellen/Pille,
 *   peerStatus setzt der Aufrufer (nimmPeerStand) — sonst überschreibt die
 *   kurze Tor-Probe (oft 2 Peers) den Live-Stand und erzeugt „Wechsel: 2 → N“.
 */
function nimmLiveP2pPeers(hosts, opts = {}) {
  const setzeStatus = opts.setzeStatus !== false;
  const liste = Array.isArray(hosts)
    ? hosts.map((h) => String(h || "").trim()).filter(Boolean)
    : [];
  const uniq = [...new Set(liste)];
  Zustand.liveP2pPeers = uniq;
  if (!Zustand.config) return;
  const sources = (Zustand.config.sources || []).map((q) => {
    if (q.key !== "bip158") return q;
    if (!uniq.length) {
      // Scan vorbei: Live-Markierung fallen lassen, Check-Stand behalten.
      return q;
    }
    // Nur aktuelle Live-Hosts — nicht unbegrenzt mit alten Probe-Hosts mergen.
    return {
      ...q,
      reachable: true,
      peer_count: uniq.length,
      peer_hosts: uniq,
      error: "",
    };
  });
  Zustand.config.sources = sources;
  if (uniq.length && setzeStatus) {
    // Volle Formel: Peers + electrs, nicht nur P2P (sonst „→ onion-electrs“-Quatsch).
    const stand = peerStatusAusQuellen(Zustand.config.sources);
    Zustand.peerStatus = stand;
    Zustand.peers = stand.n;
    Zustand.peerLabel = stand.label;
    Zustand.peersGeprueft = true;
  }
  zeichneKopfStatus(sources);
  // Peer-Takt nicht anfassen — Live-Update braucht keinen kürzeren Netzcheck.
}

function setzePeerTakt(quellen) {
  const ms = peerTaktMs(quellen);
  if (Zustand.peerTakt && Zustand.peerTaktMs === ms) return;
  if (Zustand.peerTakt) {
    clearInterval(Zustand.peerTakt);
    Zustand.peerTakt = null;
  }
  Zustand.peerTaktMs = ms;
  Zustand.peerTakt = setInterval(pruefePeersLeise, ms);
}

/** @deprecated Name bleibt für Tests; startet bzw. passt den Takt an. */
function startePeerTakt(quellen) {
  setzePeerTakt(quellen || Zustand.config?.sources);
}

async function pruefePeersLeise() {
  if (Zustand.peerCheckLaeuft) return;
  Zustand.peerCheckLaeuft = true;
  try {
    const ergebnis = await apiSourceCheck({ still: true });
    nimmPeerStand(ergebnis, true);
  } catch (_) {
    /* letzter Stand bleibt */
  } finally {
    Zustand.peerCheckLaeuft = false;
  }
}

/**
 * /config liefert Quellen ohne Live-Check (reachable: null). Nach einem Scan
 * würde zeichneKopfStatus die Pillen sonst kurz rot malen, bis der nächste
 * Peer-Takt wieder grün setzt. Bekannten Stand mitnehmen.
 *
 * Während eines UTXO-Scans kann Core (scantxoutset) den RPC kurz blockieren —
 * ein paralleler Check meldet dann fälschlich „nicht erreichbar“. Den letzten
 * positiven Stand behalten, bis der Scan durch ist.
 */
function uebernehmeQuellenErreichbarkeit(altListe, neuListe, {
  behaltePositivBeiNegativ = false,
} = {}) {
  if (!Array.isArray(neuListe) || !neuListe.length) return neuListe || [];
  if (!Array.isArray(altListe) || !altListe.length) return neuListe;
  const altNach = Object.create(null);
  for (const q of altListe) {
    if (q && q.key) altNach[q.key] = q;
  }
  return neuListe.map((neu) => {
    const alt = altNach[neu.key];
    if (!alt) return neu;
    // .env gelöscht / Host geleert: kein alter „verbunden“-Stand behalten.
    if (!neu.configured) {
      if (
        neu.reachable == null
        && alt.reachable == null
        && !(alt.peer_count > 0)
      ) {
        return neu;
      }
      return {
        ...neu,
        reachable: null,
        error: "",
        peer_count: 0,
        peer_hosts: [],
      };
    }
    if (neu.reachable == null) {
      if (alt.reachable == null && !(alt.peer_count > 0)) return neu;
      return {
        ...neu,
        reachable: alt.reachable,
        error: neu.error || alt.error || "",
        peer_count: neu.peer_count || alt.peer_count || 0,
        peer_hosts:
          (neu.peer_hosts && neu.peer_hosts.length)
            ? neu.peer_hosts
            : (alt.peer_hosts || []),
        software: neu.software || alt.software || "",
        software_raw: neu.software_raw || alt.software_raw || "",
        detail: neu.detail || alt.detail || "",
      };
    }
    if (
      behaltePositivBeiNegativ
      && neu.reachable === false
      && alt.reachable === true
    ) {
      return {
        ...neu,
        reachable: true,
        error: "",
        peer_count: alt.peer_count || neu.peer_count || 0,
        peer_hosts:
          (alt.peer_hosts && alt.peer_hosts.length)
            ? alt.peer_hosts
            : (neu.peer_hosts || []),
        software: alt.software || neu.software || "",
        software_raw: alt.software_raw || neu.software_raw || "",
        detail: alt.detail || neu.detail || "",
      };
    }
    // Software vom älteren Stand behalten, wenn der neue Check sie weglässt.
    if (
      neu.reachable === true
      && !String(neu.software || "").trim()
      && String(alt.software || "").trim()
    ) {
      return {
        ...neu,
        software: alt.software,
        software_raw: alt.software_raw || neu.software_raw || "",
      };
    }
    return neu;
  });
}

/** Welche Kopf-Pillen nach Speichern einer Quelle neu verbunden werden müssen. */
function quellenPendingKeysNachSave(quelleKey) {
  if (quelleKey === "own_fulcrum") return ["own_fulcrum"];
  if (quelleKey === "own_core") return ["own_core"];
  if (quelleKey === "own_utxo_core") return ["own_utxo_core"];
  return [];
}

/**
 * Nach „Übernehmen“: betroffene Pillen sofort grau (pending), ohne alten
 * reachable/software-Stand. Farbe + Name erst nach erfolgreichem Check.
 */
function setzeQuellenPending(keys) {
  const keyset = new Set(
    (Array.isArray(keys) ? keys : [keys]).map((k) => String(k || "")).filter(Boolean),
  );
  if (!keyset.size || !Zustand.config) return;
  Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
    if (!q || !keyset.has(q.key) || !q.configured) return q;
    return {
      ...q,
      reachable: null,
      error: "",
      peer_count: 0,
      peer_hosts: [],
      software: "",
      software_raw: "",
    };
  });
  // Noch kein frischer Check — Aufbau (grau), nicht Fehler (rot).
  Zustand.peersGeprueft = false;
  Zustand.peerCheckLaeuft = true;
  const stand = peerStatusAusQuellen(Zustand.config.sources);
  Zustand.peerStatus = stand;
  Zustand.peers = stand.n;
  Zustand.peerLabel = stand.label;
  zeichneKopfStatus(Zustand.config.sources);
}

/**
 * Eigener Indexer schon in Nutzung (Tip-Sync/Empfang) → Pille sofort grün.
 * Kommt aus Job-Meta oder sources_last, nicht erst vom 30‑s-Peer-Takt.
 */
function nimmOwnFulcrumStand(info) {
  if (!info || !Zustand.config) return;
  const soft = String(info.software || "").trim();
  const softRaw = String(info.software_raw || "").trim();
  const hosts = Array.isArray(info.peer_hosts)
    ? info.peer_hosts.map((h) => String(h || "").trim()).filter(Boolean)
    : [];
  Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
    if (q.key !== "own_fulcrum" || !q.configured) return q;
    return {
      ...q,
      reachable: info.reachable === false ? false : true,
      error: info.reachable === false ? String(info.error || q.error || "") : "",
      peer_count: Number(info.peer_count || hosts.length || 1),
      peer_hosts: hosts.length ? hosts : (q.peer_hosts || []),
      software: soft || q.software || "",
      software_raw: softRaw || q.software_raw || "",
      detail: String(info.detail || q.detail || ""),
    };
  });
  Zustand.peersGeprueft = true;
  const stand = peerStatusAusQuellen(Zustand.config.sources);
  Zustand.peerStatus = stand;
  Zustand.peers = stand.n;
  Zustand.peerLabel = stand.label;
  zeichneKopfStatus(Zustand.config.sources);
  setzePeerTakt(Zustand.config.sources);
}

function nimmPeerStand(ergebnis, still) {
  const altStand = Zustand.peerStatus;
  const quellen = uebernehmeQuellenErreichbarkeit(
    Zustand.config?.sources,
    ergebnis.sources || [],
    { behaltePositivBeiNegativ: Boolean(Zustand.rescanJob) },
  );
  if (Zustand.config) {
    Zustand.config.sources = quellen;
    if (ergebnis.header_job_id) {
      Zustand.config.header_job_id = ergebnis.header_job_id;
    }
    if (ergebnis.header_tip != null) {
      Zustand.config.header_tip = ergebnis.header_tip;
    }
  }
  const liveHosts = Array.isArray(ergebnis.live_p2p_peers)
    ? [...new Set(
      ergebnis.live_p2p_peers.map((h) => String(h || "").trim()).filter(Boolean),
    )]
    : [];
  if (liveHosts.length) {
    // Quellen aktualisieren, peerStatus noch nicht — sonst steht der Vergleich
    // immer auf der kurzen Live-/Tor-Probe (oft 2) statt dem letzten Stand.
    nimmLiveP2pPeers(liveHosts, { setzeStatus: false });
  }
  let stand = peerStatusAusQuellen(
    Zustand.config?.sources || quellen,
    ergebnis.peer_status,
  );
  // Aktive Filter-Peers des Scans schlagen die Erreichbarkeits-Probe
  // (Probe über Tor oft max. 2, Scan-Pool kann anders zählen).
  if (liveHosts.length && (Zustand.rescanJob || stand.kind === "p2p" || stand.kind === "none")) {
    stand = {
      n: liveHosts.length,
      kind: "p2p",
      label:
        liveHosts.length === 1
          ? "1 Peer verbunden"
          : `${liveHosts.length} Peers verbunden`,
      peers: liveHosts,
      gut: true,
    };
  }
  const ruhig = eigeneNodesBeideErreichbar(ergebnis.sources);
  // Bei Electrs+Core kein Log über ausfallende P2P-/Wechsel-Peers —
  // der stille Takt reicht alle 10 Min für den Header-Tip.
  if (still && altStand && !ruhig) {
    const scanLaeuft = Boolean(Zustand.rescanJob);
    for (const zeile of peerAenderungenFuerLog(altStand, stand, scanLaeuft)) {
      logZeile(zeile, true);
    }
  }
  Zustand.peerStatus = stand;
  Zustand.peers = stand.n;
  Zustand.peerLabel = stand.label;
  Zustand.peersGeprueft = true;
  zeichneKopfStatus(Zustand.config?.sources || quellen);
  aktualisiereDatenquellenNav();
  const liste = $("#quellen-liste");
  if (liste && liste.childElementCount) {
    zeichneQuellen(Zustand.config?.sources || quellen);
  }
  setzePeerTakt(Zustand.config?.sources || quellen);
  if (
    !still &&
    ergebnis.peer_status &&
    ergebnis.peer_status.braucht_oeffentliche &&
    !Zustand.oeffentlicheGefragt
  ) {
    frageOeffentlicheElectrum();
  }
  if (ergebnis.header_job_id) folgeHeaderJob();
  return stand;
}

function frageOeffentlicheElectrum() {
  Zustand.oeffentlicheGefragt = true;
  const overlay = $("#oeffentliche-electrum-warnung");
  if (!overlay) return;
  logZeile(t("ui.hard.6665b8b4e2"));
  overlay.hidden = false;
  const nein = $("#oeffentliche-electrum-nein");
  if (nein) nein.focus();
}

async function lehneOeffentlicheElectrumAb() {
  const overlay = $("#oeffentliche-electrum-warnung");
  if (overlay) overlay.hidden = true;
  logZeile(t("ui.hard.d3aa220782"));
  try {
    await api("/source/oeffentlich", {
      methode: "POST",
      daten: { erlauben: false },
    });
    if (Zustand.config) {
      Zustand.config.oeffentliche_electrum = false;
      Zustand.config.oeffentliche_electrum_session = false;
    }
  } catch (fehler) {
    logZeile(t("ui.hard.57a8b6a5d2", { msg: fehler.message }), true);
  }
}

async function erlaubeOeffentlicheElectrum() {
  const overlay = $("#oeffentliche-electrum-warnung");
  if (overlay) overlay.hidden = true;
  logZeile(
    t("ui.hard.81909b08fe"),
  );
  try {
    await api("/source/oeffentlich", {
      methode: "POST",
      daten: { erlauben: true },
    });
    if (Zustand.config) {
      Zustand.config.oeffentliche_electrum = true;
      Zustand.config.oeffentliche_electrum_session = true;
    }
    await testeEigenenNode();
  } catch (fehler) {
    Zustand.oeffentlicheGefragt = false;
    logZeile(t("ui.hard.57a8b6a5d2", { msg: fehler.message }), true);
  }
}

function oeffentlicheElectrumNochAktiv() {
  if (Zustand.config?.oeffentliche_electrum) return true;
  const liste = Zustand.config?.sources || [];
  return liste.some(
    (q) =>
      q
      && (q.key === "public_onion" || q.key === "clearnet")
      && q.configured
      && (q.reachable === true || (q.peer_count || 0) > 0),
  );
}

function p2pQuelleVerbunden() {
  const p2p = (Zustand.config?.sources || []).find((q) => q && q.key === "bip158");
  return Boolean(
    p2p
    && p2p.configured
    && (p2p.reachable === true || (p2p.peer_count || 0) > 0),
  );
}

/**
 * Nach P2P-Aktivierung: optional öffentliche Electrum-Nutzung kappen.
 * @returns {Promise<"kappen"|"behalten"|undefined>}
 */
function frageP2pPrivatsphaereKappen() {
  return new Promise((resolve) => {
    const dlg = $("#p2p-privatsphaere-dialog");
    if (!dlg) {
      resolve(undefined);
      return;
    }
    const ja = $("#p2p-privatsphaere-ja");
    const nein = $("#p2p-privatsphaere-nein");
    dlg.hidden = false;
    if (ja) ja.focus();

    const fertig = async (wahl) => {
      ja?.removeEventListener("click", onJa);
      nein?.removeEventListener("click", onNein);
      dlg.removeEventListener("keydown", onTaste);
      dlg.hidden = true;
      if (wahl === "kappen") {
        try {
          await api("/source/oeffentlich", {
            methode: "POST",
            daten: { erlauben: false },
          });
          if (Zustand.config) Zustand.config.oeffentliche_electrum = false;
          Zustand.peerCheckLaeuft = false;
          // Stale „verbunden“/„im Aufbau“ an Onion/Clearnet entfernen.
          Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
            if (q.key !== "public_onion" && q.key !== "clearnet") return q;
            return {
              ...q,
              reachable: null,
              peer_count: 0,
              peer_hosts: [],
            };
          });
          zeichneDatenquellenAnsicht();
          zeichneKopfStatus(Zustand.config.sources);
          logZeile(t("ui.hard.667be59b8a"));
          meldung(t("sources.publicCut"), "gut");
        } catch (fehler) {
          logZeile(t("ui.hard.741faf4a73", { msg: fehler.message }), true);
          meldung(fehler.message, "krit");
        }
      } else if (wahl === "behalten") {
        logZeile(t("ui.hard.d8ecdd15d4"));
      }
      resolve(wahl);
    };
    const onJa = () => fertig("kappen");
    const onNein = () => fertig("behalten");
    const onTaste = (ev) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        onNein();
      }
      if (ev.key === "Enter") {
        ev.preventDefault();
        onJa();
      }
    };
    ja?.addEventListener("click", onJa);
    nein?.addEventListener("click", onNein);
    dlg.addEventListener("keydown", onTaste);
  });
}

/**
 * Kopfzeile: nur aktive/im Aufbau/fehlerhafte Quellen + eine Privatsphäre-Pille.
 * Kein Katalog ungenutzter Quellen. Cache-only → Privatsphäre hoch.
 */
function kopfQuelleVerbunden(quelle) {
  if (!quelle || !quelle.configured) return false;
  if (quelle.reachable === true) return true;
  return (quelle.peer_count || 0) > 0;
}

/** konfiguriert, noch kein Check → Aufbau; nach Check unerreichbar → Fehler. */
function kopfQuelleAufbau(quelle) {
  if (!quelle || !quelle.configured) return false;
  if (kopfQuelleVerbunden(quelle)) return false;
  if (quelle.reachable === false) return false;
  return !Zustand.peersGeprueft || quelle.reachable == null;
}

function kopfQuelleFehler(quelle) {
  return Boolean(
    quelle
    && quelle.configured
    && !kopfQuelleVerbunden(quelle)
    && Zustand.peersGeprueft
    && quelle.reachable === false,
  );
}

function zeichneKopfStatus(quellen) {
  const nach = {};
  for (const q of quellen || []) nach[q.key] = q;

  const core = nach.own_core;
  const electrs = nach.own_fulcrum;
  const p2p = nach.bip158;
  const oeffentlichOnion = nach.public_onion;
  const oeffentlichClear = nach.clearnet;

  const coreVerbunden = kopfQuelleVerbunden(core);
  const electrsVerbunden = kopfQuelleVerbunden(electrs);
  const liveN = Array.isArray(Zustand.liveP2pPeers)
    ? Zustand.liveP2pPeers.length
    : 0;
  let p2pAnzahl = Math.max(
    Number(p2p?.peer_count || 0),
    liveN,
  );
  if (
    !p2pAnzahl
    && Zustand.peerStatus
    && Zustand.peerStatus.kind === "p2p"
  ) {
    p2pAnzahl = Number(Zustand.peerStatus.n || Zustand.peers || 0);
  }
  const p2pAktiv =
    (Zustand.peerStatus && Zustand.peerStatus.kind === "p2p")
    || liveN > 0;
  const p2pVerbunden = p2pAnzahl > 0 || p2pAktiv;
  const p2pAufbau =
    Boolean(p2p?.configured)
    && !p2pVerbunden
    && (!Zustand.peersGeprueft || Zustand.peerCheckLaeuft);
  const oeffentlichVerbunden =
    kopfQuelleVerbunden(oeffentlichOnion)
    || kopfQuelleVerbunden(oeffentlichClear)
    || (Zustand.peerStatus && Zustand.peerStatus.kind === "public");

  const p2pHosts = [
    ...new Set([
      ...(p2p?.peer_hosts || []),
      ...(Zustand.liveP2pPeers || []),
    ]),
  ];
  const p2pTitle =
    (liveN > 0
      ? t("ui.hard.30afd7b333", { n: liveN }) + " "
      : "")
    + "Bitcoin-P2P mit BIP-158 Compact Filters. "
    + (p2pHosts.length ? p2pHosts.slice(0, 6).join(", ") : "");

  const eintraege = [];

  if (coreVerbunden || kopfQuelleAufbau(core) || kopfQuelleFehler(core)) {
    // Wie Indexer: Aufbau grau, erst nach Connect grün — kein Gelb-Flash.
    eintraege.push({
      key: "own_core",
      lern: "core",
      label: t("header.sourceCore"),
      stufe: coreVerbunden
        ? "gut"
        : (kopfQuelleAufbau(core) ? "neutral" : "krit"),
      title: core?.error
        || t("header.sourceCoreTitle"),
    });
  }

  if (p2pVerbunden || p2pAufbau) {
    const n = p2pVerbunden ? p2pAnzahl : 0;
    eintraege.push({
      key: "bip158",
      lern: "p2p",
      label: t("header.p2pPeers", { n }),
      stufe: p2pAufbau
        ? "warn"
        : (p2pAnzahl > 2 ? "gut" : (p2pAnzahl > 0 ? "warn" : "krit")),
      title: p2pTitle || t("header.p2pTitle"),
    });
  }

  if (electrsVerbunden || kopfQuelleAufbau(electrs) || kopfQuelleFehler(electrs)) {
    // Vor Handshake: grau „Indexer“. Erst mit server.version grün + Name.
    const soft = String(electrs?.software || "").trim();
    const softRaw = String(electrs?.software_raw || "").trim();
    const aufbau = kopfQuelleAufbau(electrs);
    const fehler = kopfQuelleFehler(electrs);
    let electrsLabel;
    let electrsTitle;
    let stufe;
    if (electrsVerbunden && soft) {
      electrsLabel = t("header.sourceElectrumImpl", { name: soft });
      electrsTitle = t("header.sourceElectrumImplTitle", {
        name: soft,
        raw: softRaw || soft,
        detail: electrs?.detail || "",
      });
      stufe = "gut";
    } else if (electrsVerbunden) {
      electrsLabel = t("header.sourceIndexer");
      electrsTitle = t("header.sourceElectrumOwnTitle");
      stufe = "gut";
    } else if (aufbau) {
      electrsLabel = t("header.sourceIndexer");
      electrsTitle = t("header.sourceIndexerTitle");
      stufe = "neutral";
    } else {
      electrsLabel = soft
        ? t("header.sourceElectrumImpl", { name: soft })
        : t("header.sourceIndexer");
      electrsTitle = electrs?.error || t("header.sourceElectrumOwnTitle");
      stufe = "krit";
    }
    if (fehler && electrs?.error) electrsTitle = electrs.error;
    eintraege.push({
      key: "own_fulcrum",
      lern: "electrum",
      label: electrsLabel,
      stufe,
      title: electrsTitle,
    });
  }

  if (oeffentlichVerbunden) {
    eintraege.push({
      key: "public",
      lern: "privatsphaere",
      label: t("header.sourceElectrumPublic"),
      stufe: "krit",
      title: t("header.sourceElectrumPublicTitle"),
    });
  }

  // Block-Explorer: immer sichtbar (Konfiguration, kein Live-Peer).
  // privat=grün, öffentlich=rot, unkonfiguriert=grau ohne Zusatztext.
  const mp = Zustand.config?.mempool || {};
  const blockExplorerOeffentlich = Boolean(
    mp.configured && !(mp.local || mp.stufe === "lokal"),
  );
  {
    let beLabel;
    let beStufe;
    let beTitle;
    if (!mp.configured) {
      beLabel = t("header.blockExplorer") !== "header.blockExplorer"
        ? t("header.blockExplorer")
        : "Block-Explorer";
      beStufe = "neutral";
      beTitle = t("header.blockExplorerNoneTitle") !== "header.blockExplorerNoneTitle"
        ? t("header.blockExplorerNoneTitle")
        : t("header.blockExplorerNoneTitle");
    } else if (mp.local || mp.stufe === "lokal") {
      beLabel = t("header.blockExplorerPrivate") !== "header.blockExplorerPrivate"
        ? t("header.blockExplorerPrivate")
        : t("header.blockExplorerPrivate");
      beStufe = "gut";
      beTitle = t("header.blockExplorerPrivateTitle") !== "header.blockExplorerPrivateTitle"
        ? t("header.blockExplorerPrivateTitle")
        : `Eigener/LAN-Explorer${mp.host ? `: ${mp.host}` : ""} — Aufrufe bleiben bei dir.`;
    } else {
      beLabel = t("header.blockExplorerPublic") !== "header.blockExplorerPublic"
        ? t("header.blockExplorerPublic")
        : t("header.blockExplorerPublic");
      beStufe = "krit";
      beTitle = t("header.blockExplorerPublicTitle") !== "header.blockExplorerPublicTitle"
        ? t("header.blockExplorerPublicTitle")
        : t("ui.hard.695025d2a1", { host: mp.host ? `: ${mp.host}` : "" });
    }
    eintraege.push({
      key: "mempool",
      lern: "privatsphaere",
      label: beLabel,
      stufe: beStufe,
      title: beTitle,
    });
  }

  const privateVerbunden =
    coreVerbunden || electrsVerbunden || (p2pVerbunden && p2pAnzahl > 0);
  const privateAufbau =
    kopfQuelleAufbau(core)
    || kopfQuelleAufbau(electrs)
    || p2pAufbau;

  let privText;
  let privStufe;
  // Öffentlicher Electrum ODER öffentlicher Block-Explorer → keine Privatsphäre.
  // Explorer zählt schon bei Konfiguration (↗-Klicks), nicht erst bei Electrs-Link.
  if (oeffentlichVerbunden || blockExplorerOeffentlich) {
    privText = t("privacy.pillNone");
    privStufe = "krit";
  } else if (privateVerbunden && p2pVerbunden && p2pAnzahl === 1
    && !coreVerbunden && !electrsVerbunden) {
    // Nur ein P2P-Peer: privat, aber schwach.
    privText = t("privacy.pillMedium");
    privStufe = "warn";
  } else if (privateVerbunden) {
    privText = t("privacy.pillHigh");
    privStufe = "gut";
  } else if (privateAufbau) {
    privText = t("privacy.pillUnclear");
    privStufe = "warn";
  } else {
    // Nichts live verbunden — nur Cache: kein Leak.
    privText = t("privacy.pillHigh");
    privStufe = "gut";
  }

  setzeText($("#fuss-quelle"), privText);

  // Nur Pillen neu bauen — Suchfeld (#kopf-filter) bleibt links stehen.
  const pillen = $("#quelle-pillen") || $("#quelle-status");
  if (!pillen) return;
  pillen.replaceChildren();
  for (const eintrag of eintraege) {
    const pill = pille(eintrag.stufe, eintrag.label);
    pill.title = eintrag.title;
    if (eintrag.lern) pill.setAttribute("data-lern", eintrag.lern);
    pillen.append(pill);
  }
  const privPill = pille(privStufe, privText);
  privPill.title = t("header.privacyTitle");
  privPill.setAttribute("data-lern", "privatsphaere");
  pillen.append(privPill);
  zeichneKursPille();
  zeichneLlmPille();
  aktualisiereKopfFilterFuerAnsicht();
  if (lernhinweiseAn()) {
    wendeAlleLernTooltipsAn().catch(() => {});
  }
}

/**
 * Globaler Listen-Filter in der Pillen-Zeile.
 * *aktiv* = false: ausgegraut. Wallet-Ansicht: aktiv (Text + >/<-Sats).
 */
function setzeKopfFilterAktiv(aktiv) {
  const feld = $("#kopf-filter");
  if (!feld) return;
  const an = Boolean(aktiv);
  const warAn = !feld.disabled;
  feld.disabled = !an;
  feld.setAttribute("aria-disabled", an ? "false" : "true");
  feld.title = an
    ? t("header.filterTitleActive")
    : t("header.filterTitleDisabled");
  feld.setAttribute(
    "data-i18n-title",
    an ? "header.filterTitleActive" : "header.filterTitleDisabled",
  );
  if (!an) {
    if (warAn || feld.value) {
      feld.value = "";
      wendeKopfFilterAn();
    }
  } else if (feld.value.trim()) {
    wendeKopfFilterAn();
  }
}

/** Welche Ansichten den Kopf-Filter nutzen (weitere folgen schrittweise). */
function kopfFilterAnsichtAktiv(ansicht) {
  return ansicht === "wallet" || ansicht === "trace" || ansicht === "steuerjahr";
}

function kopfFilterLeer() {
  return {
    leer: true, terms: [], minSats: null, maxSats: null,
    afterTs: null, beforeTs: null,
  };
}

/** Aktueller Feldinhalt, oder leer wenn das Feld aus ist. */
function kopfFilterGelesen() {
  const feld = $("#kopf-filter");
  if (!feld || feld.disabled) return kopfFilterLeer();
  return parseKopfFilter(feld.value);
}

function aktualisiereKopfFilterFuerAnsicht() {
  setzeKopfFilterAktiv(kopfFilterAnsichtAktiv(Zustand.ansicht));
}

/**
 * Kalendertag TT.MM.JJJJ oder TT.MM.JJ (lokal) → Date 00:00 oder null.
 * Zweistellige Jahre: 2000+ (Bitcoin-Kontext).
 */
function parseKopfFilterDatum(dd, mm, yy) {
  const day = Number(dd);
  const month = Number(mm);
  let year = Number(yy);
  if (!Number.isFinite(day) || !Number.isFinite(month) || !Number.isFinite(year)) {
    return null;
  }
  if (String(yy).length <= 2) year += 2000;
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const d = new Date(year, month - 1, day, 0, 0, 0, 0);
  if (
    d.getFullYear() !== year
    || d.getMonth() !== month - 1
    || d.getDate() !== day
  ) {
    return null;
  }
  return d;
}

/**
 * Parse: Freitext + `>1234`/`<1234` (sats) + `>1.1.25`/`<05.12.2023` (Datum).
 * Datum: nach dem Tag = ab Folgetag 00:00; vor dem Tag = vor 00:00 dieses Tags.
 * Mehrere Tokens = UND.
 */
function parseKopfFilter(roh) {
  const text = String(roh || "").trim();
  if (!text) {
    return {
      leer: true, terms: [], minSats: null, maxSats: null,
      afterTs: null, beforeTs: null,
    };
  }
  const terms = [];
  let minSats = null;
  let maxSats = null;
  let afterTs = null;
  let beforeTs = null;
  // Datum vor reinem Betrag prüfen (Punkte!).
  const reDatum = /^([<>])(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$/;
  const reSats = /^([<>])(\d+(?:[.,]\d+)?)$/;
  for (const tok of text.split(/\s+/)) {
    if (!tok) continue;
    const dm = tok.match(reDatum);
    if (dm) {
      const start = parseKopfFilterDatum(dm[2], dm[3], dm[4]);
      if (start) {
        if (dm[1] === ">") {
          // nach dem Kalendertag → ab 00:00 des Folgetags
          const next = new Date(start);
          next.setDate(next.getDate() + 1);
          const ts = Math.floor(next.getTime() / 1000);
          afterTs = afterTs == null ? ts : Math.max(afterTs, ts);
        } else {
          // vor dem Kalendertag → vor 00:00 dieses Tags
          const ts = Math.floor(start.getTime() / 1000);
          beforeTs = beforeTs == null ? ts : Math.min(beforeTs, ts);
        }
      }
      continue;
    }
    const sm = tok.match(reSats);
    if (sm) {
      const n = Number(String(sm[2]).replace(",", "."));
      if (Number.isFinite(n)) {
        if (sm[1] === ">") {
          minSats = minSats == null ? n : Math.max(minSats, n);
        } else {
          maxSats = maxSats == null ? n : Math.min(maxSats, n);
        }
      }
      continue;
    }
    terms.push(tok.toLowerCase());
  }
  return { leer: false, terms, minSats, maxSats, afterTs, beforeTs };
}

function _kopfFilterBetragOk(sats, f) {
  if (f.minSats != null) {
    if (!Number.isFinite(sats) || !(sats > f.minSats)) return false;
  }
  if (f.maxSats != null) {
    if (!Number.isFinite(sats) || !(sats < f.maxSats)) return false;
  }
  return true;
}

function _kopfFilterDatumOk(eventTs, f) {
  if (f.afterTs == null && f.beforeTs == null) return true;
  const ts = Number(eventTs);
  if (!Number.isFinite(ts) || ts <= 0) return false;
  if (f.afterTs != null && !(ts >= f.afterTs)) return false;
  if (f.beforeTs != null && !(ts < f.beforeTs)) return false;
  return true;
}

function _kopfFilterHaystack(el) {
  const key = String(el.dataset.key || "");
  const txid = key.includes(":") ? key.split(":")[0] : key;
  return [
    key,
    txid,
    String(el.dataset.address || ""),
    String(el.dataset.timeLabel || ""),
    // Börsen (Kraken, …) und CJ-Formen (Wasabi, Whirlpool, …)
    String(el.dataset.filterLabels || ""),
    // Sichtbarer Pillen-/Icon-Text (aria-label), falls schon gerendert
    String(el.getAttribute("aria-label") || ""),
  ].join(" ").toLowerCase();
}

function _kopfFilterTextOk(hay, terms) {
  if (!terms.length) return true;
  return terms.every((t) => hay.includes(t));
}

function _kopfFilterLeafOk(leaf, f, { textSchonOk = false } = {}) {
  const sats = Number(leaf.dataset.valueSats);
  if (!_kopfFilterBetragOk(sats, f)) return false;
  if (!_kopfFilterDatumOk(leaf.dataset.eventTs, f)) return false;
  if (textSchonOk) return true;
  return _kopfFilterTextOk(_kopfFilterHaystack(leaf), f.terms);
}

function _kopfFilterGruppeAufklappen(gruppe) {
  const kopf = gruppe.querySelector(":scope > .kopf-mit-verweis .adress-kopf, :scope > .adress-kopf");
  const inhalt = gruppe.querySelector(
    ":scope > .adress-utxos, :scope > .trace-utxos",
  );
  const klapp = kopf && kopf.querySelector(".klapp");
  if (kopf && inhalt && inhalt.hidden) {
    setzeKlapp(kopf, klapp, inhalt, true);
  }
}

/**
 * Filter auf eine Adressgruppe (Bestand oder ausgegeben/Trace-Stil).
 * @returns {boolean} Gruppe hat sichtbare Treffer
 */
function _kopfFilterAdressGruppe(gruppe, f) {
  if (typeof gruppe.baueUtxos === "function") {
    try { gruppe.baueUtxos(); } catch (_) { /* ignore */ }
  }
  const leaves = [...gruppe.querySelectorAll(
    ":scope > .adress-utxos > .utxo-zeile, :scope > .trace-utxos > .utxo-wurzel",
  )];
  // Fallback, falls verschachtelt anders
  const liste = leaves.length
    ? leaves
    : [...gruppe.querySelectorAll(".utxo-zeile, .utxo-wurzel")];

  const groupHay = [
    String(gruppe.dataset.address || ""),
    String(gruppe.dataset.filterLabels || ""),
  ].join(" ").toLowerCase();
  const groupTextOk = _kopfFilterTextOk(groupHay, f.terms);

  let any = false;
  for (const leaf of liste) {
    const ok = _kopfFilterLeafOk(leaf, f, { textSchonOk: groupTextOk });
    leaf.hidden = !ok;
    if (ok) any = true;
  }

  // Nur Gruppen-Adresse matched, keine Betrags-/Datumsgrenzen, noch keine Leaves:
  // Gruppe zeigen (UTXOs ggf. lazy).
  if (!any && groupTextOk && liste.length === 0
      && f.minSats == null && f.maxSats == null
      && f.afterTs == null && f.beforeTs == null) {
    any = true;
  }

  gruppe.hidden = !any;
  if (any && liste.some((el) => !el.hidden)) {
    _kopfFilterGruppeAufklappen(gruppe);
  }
  return any;
}

/**
 * Ausgegeben-Block unter *container*: Inhalt bei Bedarf zeichnen.
 * *daten* liefert verlauf.addresses (Wallet- oder Trace-LastData).
 */
function _kopfFilterStelleAusgegebenBereit(container, daten) {
  if (!container) return null;
  const block = container.querySelector(".ausgegeben-block");
  if (!block) return null;
  const inhalt = block.querySelector(".ausgegeben-inhalt");
  const kopf = block.querySelector(".adress-kopf");
  if (!inhalt || !kopf) return block;
  if (!inhalt.dataset.gezeichnet) {
    const klapp = kopf.querySelector(".klapp");
    inhalt.dataset.gezeichnet = "ja";
    setzeKlapp(kopf, klapp, inhalt, true);
    const addrs = daten?.verlauf?.addresses || [];
    inhalt.replaceChildren();
    fuelleTraceSortiert(
      inhalt,
      addrs,
      Zustand.traceSort || "volume-desc",
    );
  } else if (inhalt.hidden) {
    const klapp = kopf.querySelector(".klapp");
    setzeKlapp(kopf, klapp, inhalt, true);
  }
  return block;
}

function _kopfFilterAusgegebenAnwenden(ausBlock, f) {
  if (!ausBlock) return;
  if (f.leer) {
    ausBlock.hidden = false;
    for (const el of ausBlock.querySelectorAll(
      ".adress-gruppe, .utxo-zeile, .utxo-wurzel",
    )) {
      el.hidden = false;
    }
    return;
  }
  let any = false;
  for (const gruppe of ausBlock.querySelectorAll(".adress-gruppe")) {
    if (_kopfFilterAdressGruppe(gruppe, f)) any = true;
  }
  for (const leaf of ausBlock.querySelectorAll(
    ".ausgegeben-inhalt > .utxo-wurzel",
  )) {
    const ok = _kopfFilterLeafOk(leaf, f);
    leaf.hidden = !ok;
    if (ok) any = true;
  }
  ausBlock.hidden = !any;
}

function _kopfFilterRootLeeren(root) {
  if (!root) return;
  for (const el of root.querySelectorAll(
    ".adress-gruppe, .utxo-zeile, .utxo-wurzel, .ausgegeben-block, .trace-fokus",
  )) {
    el.hidden = false;
  }
}

function wendeKopfFilterWalletAn(f) {
  const root = $("#ansicht-wallet");
  if (!root) return;

  if (f.leer) {
    _kopfFilterRootLeeren(root);
    return;
  }

  for (const gruppe of root.querySelectorAll("#adress-koerper .adress-gruppe")) {
    _kopfFilterAdressGruppe(gruppe, f);
  }

  const ausBlock = _kopfFilterStelleAusgegebenBereit(
    $("#wallet-ausgegeben") || root,
    Zustand._walletUtxoDaten,
  );
  _kopfFilterAusgegebenAnwenden(ausBlock, f);
}

/** Herkunft tracen: Bestand (#trace-liste) + ausgegeben + Fokus-UTXO. */
function wendeKopfFilterTraceAn(f) {
  const root = $("#ansicht-trace");
  const liste = $("#trace-liste");
  if (!root || !liste) return;

  if (f.leer) {
    _kopfFilterRootLeeren(root);
    return;
  }

  // Adressgruppen (Volumen-Sortierung)
  for (const gruppe of liste.querySelectorAll(":scope > .adress-gruppe")) {
    _kopfFilterAdressGruppe(gruppe, f);
  }

  // Flache UTXO-Wurzeln (Alter-Sortierung) und Fokus-Hülle
  for (const leaf of liste.querySelectorAll(":scope > .utxo-wurzel")) {
    const ok = _kopfFilterLeafOk(leaf, f);
    leaf.hidden = !ok;
  }
  for (const fokus of liste.querySelectorAll(":scope > .trace-fokus")) {
    const wurzel = fokus.querySelector(".utxo-wurzel");
    if (!wurzel) {
      fokus.hidden = true;
      continue;
    }
    const ok = _kopfFilterLeafOk(wurzel, f);
    fokus.hidden = !ok;
    wurzel.hidden = false;
  }

  const ausBlock = _kopfFilterStelleAusgegebenBereit(liste, Zustand.traceLastData);
  _kopfFilterAusgegebenAnwenden(ausBlock, f);
}

/** Feldinhalt nur, solange die Steuerjahr-Ansicht den Filter wirklich nutzt. */
function steuerKopfFilter() {
  if (Zustand.ansicht !== "steuerjahr") return kopfFilterLeer();
  return kopfFilterGelesen();
}

/** Punktdiagramm: Treffer gefüllt, sonst nur gepunkteter Rand. */
function wendeKopfFilterSteuerPunkte(f) {
  const spur = $("#achse-spur");
  if (!spur) return;
  const filter = f && !f.leer ? f : kopfFilterLeer();
  for (const punkt of spur.querySelectorAll(".achse-punkt")) {
    if (filter.leer || punkt.classList.contains("geister")) {
      punkt.classList.toggle("filter-daneben", !filter.leer);
      continue;
    }
    punkt.classList.toggle("filter-daneben", !_kopfFilterLeafOk(punkt, filter));
  }
}

/**
 * Steuerjahr: Punkte mit Treffer bleiben gefüllt, der Rest wird zum
 * gepunkteten Ring. Listen zeigen nur Treffer.
 */
function wendeKopfFilterSteuerjahrAn(f) {
  const root = $("#ansicht-steuerjahr");
  if (!root) return;
  const filter = f && !f.leer ? f : kopfFilterLeer();
  wendeKopfFilterSteuerPunkte(filter);

  for (const tbody of root.querySelectorAll("tbody.steuer-gruppe")) {
    const zeilen = [...tbody.querySelectorAll(":scope > tr.steuer-utxo-zeile")];
    const meta = tbody.querySelector(".steuer-gruppe-meta");
    if (meta && filter.leer && meta.dataset.voll) {
      meta.textContent = meta.dataset.voll;
    }
    let n = 0;
    let sats = 0;
    for (const z of zeilen) {
      const ok = filter.leer || _kopfFilterLeafOk(z, filter);
      if (ok) {
        delete z.dataset.filterAus;
        n += 1;
        sats += Number(z.dataset.valueSats) || 0;
      } else {
        z.dataset.filterAus = "1";
      }
    }
    if (filter.leer) {
      tbody.hidden = false;
      if (typeof tbody._setzeSteuerGruppe === "function") {
        tbody._setzeSteuerGruppe(false);
      }
      continue;
    }
    if (n === 0) {
      tbody.hidden = true;
      continue;
    }
    tbody.hidden = false;
    if (meta) {
      const anzahl = n === 1 ? "1 UTXO" : `${n} UTXOs`;
      meta.textContent = `${anzahl} · ${formatSatsBasis(sats)}`;
    }
    if (typeof tbody._setzeSteuerGruppe === "function") {
      tbody._setzeSteuerGruppe(true);
    }
  }

  const abListe = $("#abgaenge-liste");
  const abZusatz = $("#abgaenge-zusatz");
  if (abListe) {
    const zeilen = [...abListe.querySelectorAll(":scope > .abgang-zeile")];
    let n = 0;
    let sats = 0;
    for (const z of zeilen) {
      const ok = filter.leer || _kopfFilterLeafOk(z, filter);
      z.hidden = !ok;
      if (ok) {
        n += 1;
        sats += Number(z.dataset.valueSats) || 0;
      }
    }
    if (abZusatz && zeilen.length) {
      if (!abZusatz.dataset.voll) abZusatz.dataset.voll = abZusatz.textContent;
      abZusatz.textContent = filter.leer
        ? (abZusatz.dataset.voll || abZusatz.textContent)
        : (n
          ? `${t("header.filterMatchCount", { n })} · ${formatSatsBasis(sats)}`
          : t("header.filterNone"));
    }
  }

  const sa = $("#sa-liste");
  if (sa && !filter.leer && typeof sa._saFilterNachladen === "function") {
    sa._saFilterNachladen();
  }
  if (sa && filter.leer && typeof sa._saFilterZurueck === "function") {
    sa._saFilterZurueck();
  }
  if (sa) {
    for (const abschnitt of sa.querySelectorAll(".sa-abschnitt")) {
      const zeilen = [...abschnitt.querySelectorAll(".sa-zeile")];
      if (!zeilen.length) continue;
      let n = 0;
      for (const z of zeilen) {
        const ok = filter.leer || _kopfFilterLeafOk(z, filter);
        z.hidden = !ok;
        if (ok) n += 1;
      }
      const meta = abschnitt.querySelector(".sa-summary-meta");
      if (meta && !meta.dataset.voll) meta.dataset.voll = meta.textContent;
      if (filter.leer) {
        if (meta && meta.dataset.voll) meta.textContent = meta.dataset.voll;
      } else if (meta) {
        meta.textContent = n
          ? t("header.filterMatchCount", { n })
          : t("header.filterNone");
        if (n > 0 && abschnitt.tagName === "DETAILS") abschnitt.open = true;
      }
    }
  }
}

function wendeKopfFilterAn() {
  const f = kopfFilterGelesen();
  const leer = kopfFilterLeer();
  if (Zustand.ansicht === "wallet") {
    wendeKopfFilterWalletAn(f);
    _kopfFilterRootLeeren($("#ansicht-trace"));
    wendeKopfFilterSteuerjahrAn(leer);
    return;
  }
  if (Zustand.ansicht === "trace") {
    wendeKopfFilterTraceAn(f);
    _kopfFilterRootLeeren($("#ansicht-wallet"));
    wendeKopfFilterSteuerjahrAn(leer);
    return;
  }
  if (Zustand.ansicht === "steuerjahr") {
    wendeKopfFilterSteuerjahrAn(f);
    _kopfFilterRootLeeren($("#ansicht-wallet"));
    _kopfFilterRootLeeren($("#ansicht-trace"));
    return;
  }
  wendeKopfFilterWalletAn(leer);
  wendeKopfFilterTraceAn(leer);
  wendeKopfFilterSteuerjahrAn(leer);
}

let _kopfFilterTimer = null;
function planeKopfFilter() {
  if (_kopfFilterTimer) clearTimeout(_kopfFilterTimer);
  _kopfFilterTimer = setTimeout(() => {
    _kopfFilterTimer = null;
    wendeKopfFilterAn();
  }, 150);
}

function bindeKopfFilter() {
  const feld = $("#kopf-filter");
  if (!feld || feld.dataset.gebunden === "1") return;
  feld.dataset.gebunden = "1";
  feld.addEventListener("input", planeKopfFilter);
  feld.addEventListener("search", planeKopfFilter);
  feld.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      feld.value = "";
      wendeKopfFilterAn();
      feld.blur();
    }
  });
}

const LLM_TAKT_MS = 30000;
/** Spotkurs: an den Cache-TTL in core/price.py angelehnt (10 Min). */
const KURS_TAKT_MS = 10 * 60 * 1000;

function formatKursLabel(preis) {
  if (!preis || !(Number(preis.amount) > 0)) return "BTC —";
  const n = Math.round(Number(preis.amount)).toLocaleString(formatLocale());
  const w = String(preis.currency || fiatWaehrung()).toUpperCase();
  if (w === "EUR") return `${n} €`;
  if (w === "USD") return `$${n}`;
  return `${n} ${w}`.trim();
}

function formatKursTooltip(preis) {
  if (!preis || !(Number(preis.amount) > 0)) {
    return t("header.btcTitleEmpty");
  }
  const wann = preis.time
    ? new Date(Number(preis.time) * 1000).toLocaleString(formatLocale())
    : "?";
  const quelle = preis.source || "?";
  return t("header.btcTitleLive", {
    preis: formatKursLabel(preis),
    quelle,
    wann,
  });
}

function zeichneKursPille() {
  const pillen = $("#quelle-pillen") || $("#quelle-status");
  if (!pillen) return;
  const preis = Zustand.kurs;
  const stufe = preis && Number(preis.amount) > 0 ? "gut" : "neutral";
  const neu = pille(stufe, formatKursLabel(preis));
  neu.id = "kurs-pille";
  neu.title = formatKursTooltip(preis);
  neu.setAttribute("data-lern", "preis");
  neu.setAttribute("data-i18n-title", "header.btcTitle");
  const alt = $("#kurs-pille");
  if (alt) {
    alt.replaceWith(neu);
    if (lernhinweiseAn()) ergaenzeLernTooltip(neu);
    return;
  }
  const llm = $("#llm-pille");
  if (llm) pillen.insertBefore(neu, llm);
  else pillen.append(neu);
  if (lernhinweiseAn()) ergaenzeLernTooltip(neu);
}

/** Tageskurs-Serie für Fiat-Umrechnung ausgegebener Beträge (je Währung). */
async function ladeKursSerie() {
  const w = fiatWaehrung();
  if (Zustand.kursSerie?.[w]?.series) return Zustand.kursSerie;
  if (Zustand.kursSerieLade) return Zustand.kursSerieLade;
  Zustand.kursSerieLade = (async () => {
    try {
      const stand = await api(
        `/price/history?currency=${encodeURIComponent(w)}&series=1`,
        { timeoutMs: 15000 },
      );
      const eintrag = (stand.histories || []).find((h) => h.currency === w);
      const basis = Zustand.kursSerie && typeof Zustand.kursSerie === "object"
        ? { ...Zustand.kursSerie }
        : {};
      if (eintrag?.series && eintrag.ok) {
        basis[w] = eintrag;
      } else {
        basis[w] = { ok: false, series: null, currency: w };
      }
      Zustand.kursSerie = basis;
    } catch (_fehler) {
      const basis = Zustand.kursSerie && typeof Zustand.kursSerie === "object"
        ? { ...Zustand.kursSerie }
        : {};
      basis[w] = { ok: false, series: null, currency: w };
      Zustand.kursSerie = basis;
    } finally {
      Zustand.kursSerieLade = null;
    }
    return Zustand.kursSerie;
  })();
  return Zustand.kursSerieLade;
}

async function ladeSpotkurs({ laut = false } = {}) {
  if (laut) logZeile("Hole Bitcoin-Kurs…");
  const w = fiatWaehrung();
  try {
    // Kurz timeout: sonst blockiert der Start bei Netz-/SSL-Problemen.
    Zustand.kurs = await api(
      `/price?currency=${encodeURIComponent(w)}`,
      { timeoutMs: 8000 },
    );
    const warn = (Zustand.kurs && Zustand.kurs.warning) || "";
    if (warn) {
      // Nur einmal pro Session — und nur wenn wirklich ein älterer Tag.
      if (!Zustand.kursWarnGeloggt) {
        Zustand.kursWarnGeloggt = true;
        logZeile(`Kurs: ${warn}.`, true);
      }
    } else if (laut) {
      const label = formatKursLabel(Zustand.kurs);
      const quelle = Zustand.kurs.source || "?";
      logZeile(`Kurs: ${label} (${quelle}).`, true);
    }
  } catch (fehler) {
    const msg = String(fehler.message || fehler || "");
    // Keine mehrzeilige Opt-in-/Pipe-Forensik; höchstens einmal.
    if (!Zustand.kursWarnGeloggt && (laut || /nicht beschaffbar/i.test(msg))) {
      Zustand.kursWarnGeloggt = true;
      logZeile(
        msg.length > 120 || msg.includes(" | ")
          ? t("ui.hard.64ef962e0f")
          : `Kurs: ${msg}`,
        true,
      );
    }
  }
  zeichneKursPille();
  if (Zustand.kurs && Number(Zustand.kurs.amount) > 0) {
    aktualisiereFiatAnzeigen();
  }
}

function setzeKursTakt() {
  if (Zustand.kursTimer) return;
  Zustand.kursTimer = setInterval(() => {
    ladeSpotkurs({ laut: false });
  }, KURS_TAKT_MS);
}

/** Nach Kurs-/Sprachwechsel: sichtbare Beträge mit ≈ Fiat neu zeichnen. */
function aktualisiereFiatAnzeigen() {
  if (Zustand.ansicht === "wallet" && Zustand.walletId) {
    zeigeWallet(Zustand.walletId).catch(() => {});
    return;
  }
  if (Zustand.ansicht === "steuerjahr") {
    const jahr = $("#jahr-wahl");
    if (jahr && typeof ladeSteuerjahr === "function") {
      ladeSteuerjahr().catch(() => {});
    }
  }
}

function zeichneLlmPille() {
  const pillen = $("#quelle-pillen") || $("#quelle-status");
  if (!pillen) return;
  const s = Zustand.llmStatus || Zustand.config?.llm || {};
  const neu = pille(s.pille || "neutral", übersetzeLlmLabel(s.pille_label) || "LLM");
  neu.id = "llm-pille";
  neu.title = übersetzeLlmLabel(s.tooltip) || t("settings.llm.notConfigured");
  const alt = $("#llm-pille");
  if (alt) alt.replaceWith(neu);
  else pillen.append(neu);
}

function übersetzeLlmLabel(roh) {
  if (!roh) return "";
  let text = String(roh);
  text = text
    .replace(/\bModell\b/g, t("settings.llm.modelWord"))
    .replace(/\bStufe hoch\b/g, t("settings.llm.levelHigh"))
    .replace(/\bStufe mittel\b/g, t("settings.llm.levelMid"))
    .replace(/\bStufe niedrig\b/g, t("settings.llm.levelLow"))
    .replace(/\bnur Cache\b/g, t("settings.llm.cacheOnly"))
    .replace(/\blokal\b/g, t("settings.llm.local"))
    .replace(/Assistent nicht konfiguriert/g, t("settings.llm.notConfigured"));
  return text;
}

function zeichneChatAnbindung() {
  const kasten = $("#chat-anbindung");
  if (!kasten) return;
  const s = Zustand.llmStatus || Zustand.config?.llm || {};
  kasten.textContent = übersetzeLlmLabel(s.banner) || t("settings.llm.notConfigured");
  kasten.classList.toggle("unkonfiguriert", !s.configured);
}



function slashHilfeText() {
  return t("dock.helpText");
}

const SLASH_BLOCK = new Set([
  "scan", "rescan", "verlauf", "herkunft", "sanktion", "sync", "fetch",
  "exec", "shell", "python", "eval", "system",
  "env", "xpub", "key", "seed", "token", "api-key", "apikey",
  "delete", "cache-loeschen", "danger", "reset-all",
  "send", "broadcast", "sign", "psbt",
  "url", "http", "curl", "download",
]);

const SLASH_ALIAS = {
  help: "hilfe",
  clear: "neu",
  leeren: "neu",
  status: "anbindung",
};

const SLASH_BEFEHLE = [
  "/hilfe",
  "/help",
  "/anbindung",
  "/neu",
  "/luecken",
  "/wallets",
  "/steuer",
  "/export legende",
  "/export markdown",
  "/export brief",
];

function slashTreffer(eingabe) {
  const text = String(eingabe || "");
  if (!text.startsWith("/")) return [];
  const klein = text.toLowerCase();
  return SLASH_BEFEHLE.filter((befehl) => befehl.toLowerCase().startsWith(klein));
}

function slashGemeinsam(treffer) {
  if (!treffer.length) return "";
  let prefix = treffer[0];
  for (const befehl of treffer) {
    let i = 0;
    while (
      i < prefix.length &&
      i < befehl.length &&
      prefix[i].toLowerCase() === befehl[i].toLowerCase()
    ) {
      i += 1;
    }
    prefix = prefix.slice(0, i);
  }
  return prefix;
}

function schliesseSlashListe() {
  const liste = $("#chat-slash");
  if (liste) {
    liste.hidden = true;
    liste.replaceChildren();
  }
  Zustand.slashIndex = 0;
}

function zeichneSlashListe(eingabe) {
  const liste = $("#chat-slash");
  if (!liste) return;
  const treffer = slashTreffer(eingabe);
  if (!treffer.length) {
    schliesseSlashListe();
    return;
  }
  if (Zustand.slashIndex >= treffer.length) Zustand.slashIndex = 0;
  if (Zustand.slashIndex < 0) Zustand.slashIndex = treffer.length - 1;
  liste.hidden = false;
  liste.replaceChildren();
  treffer.forEach((befehl, index) => {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "chat-slash-eintrag";
    if (index === Zustand.slashIndex) knopf.classList.add("aktiv");
    knopf.textContent = befehl;
    knopf.addEventListener("mousedown", (ereignis) => {
      ereignis.preventDefault();
      const feld = $("#chat-feld");
      if (!feld) return;
      feld.value = befehl;
      feld.focus();
      feld.setSelectionRange(befehl.length, befehl.length);
      Zustand.slashIndex = index;
      zeichneSlashListe(befehl);
    });
    liste.append(knopf);
  });
}

function vervollstaendigeSlash(feld) {
  if (!feld) return false;
  const text = feld.value;
  if (feld.selectionStart !== text.length || feld.selectionEnd !== text.length) {
    return false;
  }
  const treffer = slashTreffer(text);
  if (!treffer.length) return false;
  const idx = Math.min(Zustand.slashIndex || 0, treffer.length - 1);
  const gemeinsam = slashGemeinsam(treffer);
  let ziel = treffer[idx];
  if (treffer.length > 1 && gemeinsam.length > text.length) ziel = gemeinsam;
  if (ziel === text) return false;
  feld.value = ziel;
  feld.setSelectionRange(ziel.length, ziel.length);
  zeichneSlashListe(ziel);
  return true;
}

function parseSlash(text) {
  const roh = String(text || "").trim();
  if (!roh.startsWith("/")) return { art: "freitext", text: roh };
  const teile = roh.slice(1).trim().split(/\s+/).filter(Boolean);
  const rohCmd = (teile[0] || "").toLowerCase();
  const cmd = SLASH_ALIAS[rohCmd] || rohCmd;
  const rest = teile.slice(1);
  if (!cmd) return { art: "unbekannt", befehl: roh };
  if (SLASH_BLOCK.has(cmd) || (cmd === "modell" && rest[0])) {
    return { art: "block", befehl: `/${rohCmd}` };
  }
  if (cmd === "export") {
    const erst = (rest[0] || "").toLowerCase();
    if (!erst) return { art: "export", unter: "legende", jahr: "" };
    if (/^\d{4}$/.test(erst)) return { art: "export", unter: "legende", jahr: erst };
    if (["legende", "markdown", "brief"].includes(erst)) {
      return { art: "export", unter: erst, jahr: rest[1] || "" };
    }
    return { art: "unbekannt", befehl: roh };
  }
  if (["hilfe", "anbindung", "neu", "luecken", "wallets", "steuer"].includes(cmd)) {
    return { art: cmd, jahr: rest[0] || "" };
  }
  return { art: "unbekannt", befehl: roh };
}

function chatLeeren() {
  Zustand.chatMessages = [];
  const box = $("#chat-verlauf");
  if (!box) return;
  box.replaceChildren();
  const leer = document.createElement("p");
  leer.className = "chat-leer";
  leer.textContent = t("dock.empty");
  box.append(leer);
}

function chatZeile(rolle, text) {
  const box = $("#chat-verlauf");
  if (!box) return null;
  const leer = box.querySelector(".chat-leer");
  if (leer) leer.remove();
  const blase = document.createElement("div");
  blase.className = `chat-blase chat-${rolle}`;
  blase.textContent = text;
  box.append(blase);
  box.scrollTop = box.scrollHeight;
  return blase;
}

function slashJahrQuery(jahr) {
  const n = Number.parseInt(jahr, 10);
  if (Number.isFinite(n) && n >= 2009 && n <= 2100) return `?jahr=${n}`;
  return "";
}

function setzeChatWartet(an) {
  Zustand.chatWartet = Boolean(an);
  const feld = $("#chat-feld");
  const knopf = $("#chat-senden");
  if (feld) feld.disabled = Boolean(an);
  if (knopf) knopf.disabled = Boolean(an);
  if (an) schliesseSlashListe();
}

async function frageAssistent(text) {
  const historie = Zustand.chatMessages.concat([{ role: "user", content: text }]);
  const warte = chatZeile("system", t("dock.asking"));
  if (warte) warte.classList.add("chat-warte");
  logZeile("Frage Assistent…");
  setzeChatWartet(true);
  try {
    const koerper = await api("/llm/chat", {
      methode: "POST",
      daten: { messages: historie },
    });
    const antwort = (koerper && koerper.text) || t("dock.noAnswer");
    Zustand.chatMessages = historie.concat([
      { role: "assistant", content: antwort },
    ]);
    if (warte) warte.remove();
    chatZeile("assistent", antwort);
  } catch (fehler) {
    if (warte) warte.remove();
    chatZeile("system", t("dock.notAnswered", { msg: fehler.message }));
  } finally {
    setzeChatWartet(false);
    const feld = $("#chat-feld");
    if (feld) feld.focus();
  }
}

async function sendeChatZeile() {
  const feld = $("#chat-feld");
  if (!feld || Zustand.chatWartet) return;
  const text = feld.value.trim();
  if (!text) return;
  schliesseSlashListe();
  feld.value = "";
  feld.blur();
  window.requestAnimationFrame(() => {
    if (!Zustand.chatWartet) feld.focus();
  });
  chatZeile("user", text);
  const befehl = parseSlash(text);
  if (befehl.art === "freitext") {
    await frageAssistent(text);
    return;
  }
  if (befehl.art === "block") {
    chatZeile(
      "system",
      t("dock.blocked", { cmd: befehl.befehl }),
    );
    return;
  }
  if (befehl.art === "unbekannt") {
    chatZeile("system", t("dock.unknown"));
    return;
  }
  if (befehl.art === "hilfe") {
    chatZeile("assistent", slashHilfeText());
    return;
  }
  if (befehl.art === "anbindung") {
    const s = Zustand.llmStatus || Zustand.config?.llm || {};
    chatZeile("assistent", s.banner || "Assistent nicht konfiguriert");
    return;
  }
  if (befehl.art === "neu") {
    chatLeeren();
    return;
  }
  const pfade = {
    luecken: "/llm/context/luecken",
    wallets: "/llm/context/wallets",
    steuer: `/llm/context/steuer${slashJahrQuery(befehl.jahr)}`,
    export: `/llm/context/export?art=${encodeURIComponent(befehl.unter || "legende")}${
      slashJahrQuery(befehl.jahr).replace("?", "&")
    }`,
  };
  const pfad = pfade[befehl.art];
  if (!pfad) {
    chatZeile("system", t("dock.unknown"));
    return;
  }
  try {
    const koerper = await api(pfad);
    chatZeile("assistent", koerper.text || "Keine Daten im Cache.");
  } catch (fehler) {
    chatZeile("system", `Nicht gelesen — ${fehler.message}`);
  }
}


async function sichereHeaderVorab() {
  const tip = Zustand.config?.header_tip;
  if (Zustand.config?.header_job_id) return;
  if (tip != null && tip > 481824) return;
  try {
    const antwort = await api("/headers", { methode: "POST" });
    if (Zustand.config) {
      Zustand.config.header_job_id = antwort.header_job_id;
      Zustand.config.header_tip = antwort.header_tip;
    }
  } catch (_) {
    /* Scan holt Header zur Not selbst. */
  }
}

function folgeHeaderJob() {
  const id = Zustand.config?.header_job_id;
  if (!id || Zustand.headerJob === id) return;
  Zustand.headerJob = id;
  Zustand.headerLogStand = { index: 0 };
  if (Zustand.headerTimer) clearInterval(Zustand.headerTimer);
  Zustand.headerTimer = setInterval(pruefeHeaderJob, 1500);
  pruefeHeaderJob();
}

async function pruefeHeaderJob() {
  if (!Zustand.headerJob) return;
  try {
    const job = await api(`/jobs/${Zustand.headerJob}`);
    nimmJobLogAb(job, Zustand.headerLogStand);
    if (Array.isArray(job.live_p2p_peers)) {
      nimmLiveP2pPeers(job.live_p2p_peers);
    }
    if (job.running) return;
    if (Zustand.headerTimer) {
      clearInterval(Zustand.headerTimer);
      Zustand.headerTimer = null;
    }
    Zustand.headerJob = null;
    if (!Zustand.walletSyncJob) {
      Zustand.liveP2pPeers = [];
      setzePeerTakt(Zustand.config?.sources);
    }
  } catch (_) {
    /* Vorab-Job ist optional — der Scan holt Header zur Not selbst. */
  }
}

function loeseWalletSyncBindung() {
  if (Zustand.walletSyncTimer) {
    clearInterval(Zustand.walletSyncTimer);
    Zustand.walletSyncTimer = null;
  }
  if (Zustand.walletSyncJob) {
    // Für Ka-Ching nach Empfangs-Index-Sprung (QR oft vor Pending-Flash).
    Zustand._tipSyncEndedUm = Date.now();
  }
  Zustand.walletSyncJob = null;
  Zustand.walletSyncWalletIds = [];
  Zustand.walletSyncDoneIds = [];
  Zustand.walletSyncStill = false;
  Zustand.walletSyncPhase = null;
  if (Zustand.config) Zustand.config.wallet_sync_job_id = null;
  Zustand.liveP2pPeers = [];
  setzePeerTakt(Zustand.config?.sources);
}

function jobIstStillerTip(jobOrMeta) {
  if (!jobOrMeta) return false;
  if (jobOrMeta.still || jobOrMeta.meta?.still) return true;
  return false;
}

/** Tip-Sync betraf das gerade gewählte Wallet (Empfang/UTXO nur dann anfassen). */
function tipSyncBetrifftAktuellesWallet(ids) {
  const wid = Zustand.walletId;
  if (!wid) return false;
  const liste = Array.isArray(ids) && ids.length
    ? ids
    : (Zustand.walletSyncWalletIds || []);
  if (!liste.length) return false;
  return liste.map(String).includes(String(wid));
}

function folgeWalletSyncJob(jobId, meta) {
  const id = jobId || Zustand.config?.wallet_sync_job_id;
  if (!id || Zustand.walletSyncJob === id) {
    if (meta) {
      merkeWalletSyncZiele(meta);
      if (jobIstStillerTip(meta)) Zustand.walletSyncStill = true;
    }
    return;
  }
  // Fertiger/staler Job aus Config: nicht als laufend behandeln, Puls nicht starten.
  const bekannt = (Zustand.jobsNav?.jobs || []).find((x) => x && x.id === id);
  if (
    bekannt
    && !(
      bekannt.running
      || bekannt.status === "running"
      || bekannt.status === "queued"
      || bekannt.queue_status === "queued"
    )
  ) {
    if (Zustand.config) Zustand.config.wallet_sync_job_id = null;
    return;
  }
  Zustand.walletSyncJob = id;
  if (Zustand.config) Zustand.config.wallet_sync_job_id = id;
  Zustand.walletSyncLogStand = { index: 0 };
  Zustand.walletSyncDoneIds = [];
  Zustand.walletSyncStill = jobIstStillerTip(meta) || jobIstStillerTip(bekannt);
  if (meta) merkeWalletSyncZiele(meta);
  else if (bekannt) merkeWalletSyncZiele(bekannt);
  if (Zustand.walletSyncTimer) clearInterval(Zustand.walletSyncTimer);
  Zustand.walletSyncTimer = setInterval(pruefeWalletSyncJob, 900);
  // Erst Status prüfen — erst bei running loggen/atmen (siehe pruefeWalletSyncJob).
  pruefeWalletSyncJob();
  setzeWalletScanGesperrt();
}

async function pruefeWalletSyncJob() {
  if (!Zustand.walletSyncJob) return;
  const syncId = Zustand.walletSyncJob;
  try {
    const job = await api(`/jobs/${syncId}`);
    nimmJobLogAb(job, Zustand.walletSyncLogStand);
    if (Array.isArray(job.live_p2p_peers)) {
      nimmLiveP2pPeers(job.live_p2p_peers);
    }
    if (job.meta?.own_fulcrum) {
      nimmOwnFulcrumStand(job.meta.own_fulcrum);
    }
    merkeWalletSyncZiele(job);
    if (jobIstStillerTip(job)) Zustand.walletSyncStill = true;
    if (job.meta?.phase === "empfang") {
      Zustand.walletSyncPhase = "empfang";
      // jobsNav-Meta mitziehen (sonst zeigt der Poller weiter „läuft“).
      const navJob = (Zustand.jobsNav?.jobs || []).find((x) => x && x.id === syncId);
      if (navJob) {
        navJob.meta = navJob.meta || {};
        navJob.meta.phase = "empfang";
      }
    }
    if (job.running || job.status === "running" || job.status === "queued") {
      // Echt laufend: einmal loggen; Empfang nur wenn DIESES Wallet im Tip-Sync ist.
      // Stiller Watch-Fallback: Log ok, kein Puls / keine Nav-Marker.
      if (!Zustand.walletSyncLogStand?._tipAngekuendigt) {
        Zustand.walletSyncLogStand = Zustand.walletSyncLogStand || { index: 0 };
        Zustand.walletSyncLogStand._tipAngekuendigt = true;
        if (Zustand.walletSyncStill) {
          logZeile("Tip-Nachzug (still, Hintergrund)…");
        } else {
          logZeile("Tip-Nachzug der Wallets…");
          if (
            Zustand.walletId
            && !Zustand.lernThema
            && tipSyncBetrifftAktuellesWallet()
          ) {
            ladeEmpfang(Zustand.walletId).catch(() => {});
          }
          zeichneNav();
        }
      }
      // Je fertigem Wallet: Config/Nav nachziehen → „gerade eben“ statt warten
      // bis alle Wallets durch sind.
      const fertigIds = tipSyncDoneWalletIds(job);
      const vorher = Zustand.walletSyncDoneIds || [];
      if (
        fertigIds.length > vorher.length
        && !Zustand.walletSyncStill
      ) {
        Zustand.walletSyncDoneIds = fertigIds.slice();
        // jobsNav-Meta mitziehen (walletSyncLaeuftFuer liest beides).
        const navJob = (Zustand.jobsNav?.jobs || []).find((x) => x && x.id === syncId);
        if (navJob) {
          navJob.meta = navJob.meta || {};
          navJob.meta.done_wallet_ids = fertigIds.slice();
        }
        try {
          await ladeConfig();
        } catch (_) {
          /* Nav trotzdem */
        }
        setzeWalletScanGesperrt();
        zeichneNav();
        // Empfangspanel an aktuellem Wallet ausrichten: fertig → QR/Read-only,
        // noch Tip → weiter Atem (auch Read-only).
        if (Zustand.walletId && !Zustand.lernThema) {
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      // UTXO-Tip fertig, Empfangsadressen laufen noch → Nav grün, QR darf laden.
      if (
        (job.meta?.phase === "empfang" || Zustand.walletSyncPhase === "empfang")
        && !Zustand.walletSyncLogStand?._tipUiFertig
        && !Zustand.walletSyncStill
      ) {
        Zustand.walletSyncLogStand._tipUiFertig = true;
        Zustand.walletSyncPhase = "empfang";
        const n = job.result?.wallets;
        const u = job.result?.utxo_count;
        if (typeof n === "number") {
          logZeile(
            `Tip-Nachzug fertig: ${n} Wallet(s), ${u ?? "?"} UTXO(s) `
            + "(Empfangsadressen folgen)…",
          );
        }
        if (Zustand.config) Zustand.config.wallet_sync_job_id = null;
        const betroffene = walletIdsAusSyncJob(job);
        for (const wid of betroffene) {
          delete Zustand.empfangByWallet[wid];
        }
        try {
          await ladeConfig();
        } catch (_) {
          /* Nav trotzdem */
        }
        setzeWalletScanGesperrt();
        zeichneNav();
        if (
          Zustand.walletId
          && !Zustand.lernThema
          && tipSyncBetrifftAktuellesWallet(betroffene.length ? betroffene : null)
        ) {
          // phase empfang → tipSyncLaeuftFuer false → Electrs-Adresse holen
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      return;
    }
    const warAktiv = Boolean(Zustand.walletSyncLogStand?._tipAngekuendigt);
    const warStill = Zustand.walletSyncStill;
    const betroffene = walletIdsAusSyncJob(job).length
      ? walletIdsAusSyncJob(job)
      : (Zustand.walletSyncWalletIds || []).slice();
    const betrifftAktuell = !warStill && tipSyncBetrifftAktuellesWallet(betroffene);
    const pulsAn = EmpfangPuls.laeuft()
      || Boolean(Zustand.empfang && Zustand.empfang.puls);
    loeseWalletSyncBindung();
    // Puls/QR nur anfassen, wenn Tip-Sync dieses Wallet betraf und wir atmeten —
    // nicht wenn gerade Ka-Ching nachgeholt wird.
    if (betrifftAktuell && pulsAn && !EmpfangPuls.laeuft()) {
      EmpfangPuls.stop();
    }
    setzeWalletScanGesperrt();
    // Stale done-Job aus Config beim Start: nur Slot freigeben, kein Reload-Sturm.
    if (!warAktiv) {
      zeichneNav();
      return;
    }
    if (job.status === "done") {
      const n = job.result?.wallets;
      const u = job.result?.utxo_count;
      // Fertig-Zeile schon bei phase=empfang geloggt → nicht doppelt.
      if (typeof n === "number" && !Zustand.walletSyncLogStand?._tipUiFertig) {
        logZeile(
          `Tip-Nachzug fertig: ${n} Wallet(s), ${u ?? "?"} UTXO(s).`,
        );
      } else if (job.result?.empfang_scharf) {
        logZeile(
          `Empfangsadressen nachgezogen (${job.result.empfang_scharf}).`,
        );
      }
      // Nur Cache der betroffenen Wallets — nicht Firmung-QR wegen Cash+Carry.
      for (const wid of betroffene) {
        delete Zustand.empfangByWallet[wid];
      }
      await ladeConfig();
      await ladeJobsNav();
      setzeWalletScanGesperrt();
      if (betrifftAktuell && Zustand.walletId) {
        // Pending während Tip-Sync → Konfetti jetzt (QR-Sprung ohne Ka-Ching vermeiden).
        const kaChing = spieleQueuedIncomingFlash(Zustand.walletId);
        if (Zustand.ansicht === "wallet") {
          await zeigeWallet(Zustand.walletId);
          if (!kaChing && !EmpfangPuls.laeuft()) {
            ladeEmpfang(Zustand.walletId).catch(() => {});
          }
        } else if (!Zustand.lernThema) {
          if (!kaChing) ladeEmpfang(Zustand.walletId).catch(() => {});
          zeichneNav();
        } else {
          zeichneNav();
        }
      } else {
        zeichneNav();
      }
    } else if (job.status === "cancelled") {
      logZeile("Tip-Nachzug abgebrochen.");
      if (betrifftAktuell && Zustand.walletId && !Zustand.lernThema) {
        if (!spieleQueuedIncomingFlash(Zustand.walletId)) {
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      zeichneNav();
    } else {
      if (job.error) logZeile(`Tip-Nachzug: ${job.error}`);
      if (betrifftAktuell && Zustand.walletId && !Zustand.lernThema) {
        if (!spieleQueuedIncomingFlash(Zustand.walletId)) {
          ladeEmpfang(Zustand.walletId).catch(() => {});
        }
      }
      zeichneNav();
    }
  } catch (_) {
    // Job weg (404) oder Netz: Bindung lösen, sonst atmet der QR ewig.
    const betrifftAktuell = tipSyncBetrifftAktuellesWallet();
    const pulsAn = EmpfangPuls.laeuft()
      || Boolean(Zustand.empfang && Zustand.empfang.puls);
    loeseWalletSyncBindung();
    if (betrifftAktuell && pulsAn) EmpfangPuls.stop();
    setzeWalletScanGesperrt();
    if (betrifftAktuell && Zustand.walletId && !Zustand.lernThema) {
      ladeEmpfang(Zustand.walletId).catch(() => {});
    }
    zeichneNav();
  }
}

// Shell-Bootstrap → web/chrome.js (Modularisierung Slice 2).
// zeichneFussVersion / logReleaseAlsErsteZeile / zeichneFussLocalOnly /
// ladeConfig / start (+ Top-Level-Event-Listener).

