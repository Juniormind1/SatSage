/** Adress-Labels-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: Globals aus app.js (Zustand, api, t, $, pille,
 * meldungListen, dateienAlsImportPayload, formatLocale, logZeile,
 * übersetzeServerMeldung, übersetzeLogText, …).
 * Kein import/export. Laden nach app.js, vor boot.js.
 * dateiAlsBase64 / dateienAlsImportPayload / Listen-Import / meldungListen
 * bleiben in app.js (geteilt mit Sanktionslisten / Datenquellen).
 */

// ---------------------------------------------------------------------------
// Adress-Labels
// ---------------------------------------------------------------------------

async function ladeLabelStatus() {
  const kasten = $("#label-status");
  let status;
  try {
    status = await api("/labels");
  } catch (fehler) {
    setzeText(
      kasten,
      /Token fehlt|token missing/i.test(fehler.message || "")
        ? t("state.unreadableToken")
        : t("common.errorPrefix", { msg: übersetzeServerMeldung(fehler.message) }),
    );
    return;
  }
  Zustand.labels = status;

  const auswahl = $("#label-variante");
  if (!auswahl.options.length) {
    for (const variante of status.varianten || []) {
      const option = document.createElement("option");
      option.value = variante.wert;
      const key = `labels.variant.${variante.wert}`;
      const uebersetzt = t(key);
      option.textContent = uebersetzt !== key ? uebersetzt : variante.label;
      auswahl.append(option);
    }
  }
  if (status.variante) auswahl.value = status.variante;
  $("#label-verwerfen").hidden = !status.vorhanden;

  kasten.replaceChildren();
  const zeile = document.createElement("div");
  zeile.className = "sanktions-zeile";

  if (!status.vorhanden) {
    zeile.append(pille("warn", t("labels.notLoaded")));
    const text = document.createElement("span");
    text.textContent = t("labels.emptyHint");
    zeile.append(text);
    setzeText($("#label-zusatz"), "");
  } else {
    zeile.append(pille("gut", t("common.loaded")));
    const text = document.createElement("span");
    text.textContent = t("labels.counts", {
      addresses: status.adressen.toLocaleString(formatLocale()),
      named: status.benannt.toLocaleString(formatLocale()),
      entities: status.entitaeten.toLocaleString(formatLocale()),
    });
    zeile.append(text);
    // Bewusst „Datei vom": Das ist das Datum des Downloads, nicht das der
    // Daten darin. Die stammen von 2018 — das sagt der Vorbehalt darunter.
    const datei = (status.stand || "").split("-").reverse().join(".");
    setzeText($("#label-zusatz"), datei ? t("labels.fileFrom", { date: datei }) : "");
  }
  kasten.append(zeile);

  // Der Datenstand ist die wichtigste Einschränkung — er gehört sichtbar
  // neben den Bestand, nicht in eine Fußnote.
  const vorbehalt = document.createElement("p");
  vorbehalt.className = "vorbehalt";
  vorbehalt.textContent = t("labels.dataHint");
  kasten.append(vorbehalt);

  const herkunft = document.createElement("p");
  herkunft.className = "meta";
  herkunft.textContent = t("labels.sourceLine", { quelle: status.quelle, url: status.quelle_url });
  kasten.append(herkunft);
}

function starteLabelImport() {
  const feld = $("#label-dateien");
  if (feld) feld.click();
}

async function liesLabelImportDateien(ereignis) {
  const liste = ereignis.target.files ? [...ereignis.target.files] : [];
  ereignis.target.value = "";
  if (!liste.length) return;
  const knopf = $("#label-import");
  const laden = $("#label-laden");
  if (knopf) knopf.disabled = true;
  if (laden) laden.disabled = true;
  $("#label-lauf").hidden = false;
  setzeText($("#label-text"), t("sources.labelsImporting"));
  try {
    const payload = await dateienAlsImportPayload(liste);
    payload.variante = $("#label-variante")?.value || undefined;
    const stand = await api("/labels/import", {
      methode: "POST",
      daten: payload,
      timeoutMs: 300_000,
    });
    const n = Number(stand.adressen || 0).toLocaleString(formatLocale());
    meldungListen(t("sources.labelsImportDone", { addresses: n }));
    logZeile(`Labels importiert: ${n} Adressen.`, true);
  } catch (fehler) {
    meldungListen(t("common.loadFailed", { msg: fehler.message }));
    logZeile(t("ui.hard.80816bd6d6", { msg: fehler.message }), true);
  } finally {
    if (knopf) knopf.disabled = false;
    if (laden) laden.disabled = false;
    $("#label-lauf").hidden = true;
    ladeLabelStatus();
  }
}

async function ladeLabels() {
  const knopf = $("#label-laden");
  knopf.disabled = true;
  const imp = $("#label-import");
  if (imp) imp.disabled = true;
  $("#label-lauf").hidden = false;
  const abbruchKnopf = $("#label-abbruch");
  if (abbruchKnopf) {
    abbruchKnopf.hidden = false;
    abbruchKnopf.disabled = false;
  }
  setzeText($("#label-text"), t("common.downloadStarting"));
  const fertig = (meldung) => {
    clearInterval(timer);
    knopf.disabled = false;
    if (imp) imp.disabled = false;
    $("#label-lauf").hidden = true;
    if (abbruchKnopf) abbruchKnopf.hidden = true;
    if (meldung) meldungListen(meldung);
    ladeLabelStatus();
  };

  let jobId = null;
  let timer = null;
  if (abbruchKnopf) {
    abbruchKnopf.onclick = async () => {
      abbruchKnopf.disabled = true;
      setzeText($("#label-text"), t("common.abortRequested"));
      if (jobId) {
        try {
          await api(`/jobs/${jobId}`, { methode: "DELETE" });
        } catch (_) {
          /* schon beendet */
        }
      }
    };
  }
  try {
    const job = await api("/labels", {
      methode: "POST",
      daten: { variante: $("#label-variante").value },
    });
    jobId = job.id;
  } catch (fehler) {
    fertig(t("common.loadFailed", { msg: fehler.message }));
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      setzeText($("#label-text"), übersetzeLogText(job.message || t("common.runningEllipsis")));
      if (job.running) return;
      if (job.status === "done") {
        fertig("");
        return;
      }
      if (job.status === "cancelled") {
        fertig(t("common.cancelled"));
        return;
      }
      // Fehler sichtbar halten — sonst wirkt es wie „nicht geladen“ ohne Grund
      // (z. B. früher SSL-Zertifikatfehler beim GitHub-Download).
      const detail =
        übersetzeServerMeldung(job.error || job.message || "") || t("common.failed");
      fertig(detail);
    } catch (fehler) {
      fertig(fehler.message);
    }
  }, 1000);
}

async function verwirfLabels() {
  try {
    await api("/labels", { methode: "DELETE" });
  } catch (fehler) {
    meldungListen(t("ui.hard.7e9ce1e8a1", { msg: fehler.message }));
  }
  ladeLabelStatus();
}

/**
 * Die Beschriftung einer fremden Adresse als Element — oder null.
 *
 * Eine Forenerwähnung wird bewusst anders formuliert als ein Dienst: „auf
 * BitcoinTalk erwähnt" ist keine Aussage darüber, wem die Adresse gehört.
 */
/**
 * Börse: nur Klarname. Grün = Zufluss von der Börse ins Wallet;
 * rot = Sats zur Börse geschickt (Einzahlung dort).
 */
function istBoersenLabel(label) {
  if (!label) return false;
  return (
    label.kategorie === "exchange"
    || label.kategorie_label === "Börse"
    || label.quelle === "Börsen-CSV"
    || Boolean(label.nutzer_import && label.kategorie === "exchange")
  );
}

/** "in" = von Börse→Wallet, "out" = Wallet→Börse, "" = unklar. */
function boerseRichtung(label, kontext) {
  const rolle = String(label?.rolle || "").toLowerCase();
  const hatEin = rolle.includes("einzahlung") || rolle.includes("deposit");
  const hatAus = rolle.includes("auszahlung") || rolle.includes("withdrawal");
  if (hatEin && !hatAus) return "out"; // Einzahlung auf die Börse
  if (hatAus && !hatEin) return "in"; // Auszahlung von der Börse
  if (kontext && kontext.zufluss) return "in"; // Herkunfts-Zufluss
  if (kontext && kontext.abfluss) return "out";
  // Ohne Rolle: im Herkunftsbaum typisch Zufluss von außen.
  if (kontext && kontext.herkunft) return "in";
  return "";
}

function labelMarke(label, kontext) {
  if (!label) return null;

  const marke = document.createElement("span");
  marke.className = `label-marke label-${label.art}`;
  const hinweis = t("labels.dataHint");

  if (!label.benannt) {
    marke.textContent = t("labels.knownService");
    marke.title = t("labels.knownNoNameTitle", { hint: hinweis });
    return marke;
  }
  if (label.art === "erwaehnung") {
    marke.textContent = t("labels.mentionedOn", { name: label.name });
    marke.title = t("labels.mentionedTitle", { hint: hinweis });
    return marke;
  }

  // Börsen: nur Name; Farbe nach Richtung.
  if (istBoersenLabel(label)) {
    const name = String(label.name || "").trim() || t("labels.cat.exchange");
    marke.textContent = name;
    marke.classList.add("label-boerse");
    const richtung = boerseRichtung(label, kontext || {});
    if (richtung === "in") marke.classList.add("label-boerse-in");
    else if (richtung === "out") marke.classList.add("label-boerse-out");
    const teile = [name];
    if (label.rolle) teile.push(label.rolle);
    if (richtung === "in") teile.push(t("labels.exchangeInflow"));
    else if (richtung === "out") teile.push(t("labels.exchangeOutflow"));
    if (label.quelle) teile.push(label.quelle);
    if (label.hinweis) teile.push(label.hinweis);
    teile.push(hinweis);
    marke.title = teile.filter(Boolean).join(" · ");
    return marke;
  }

  const katKey = `labels.cat.${label.kategorie || label.art || ""}`;
  const kat = (() => {
    const u = t(katKey);
    return u !== katKey ? u : (label.kategorie_label || label.art || "");
  })();
  const rolle = (label.rolle || "").trim();
  marke.textContent = rolle
    ? `${kat} · ${label.name} (${rolle})`
    : `${kat} · ${label.name}`;
  if (label.nutzer_import) {
    marke.classList.add("label-nutzer");
  }
  const teile = [];
  if (label.land) teile.push(t("labels.seat", { land: label.land }));
  if (label.status === "closed") teile.push(t("labels.serviceClosed"));
  if (label.nutzer_import) {
    teile.push(label.quelle || "Börsen-CSV");
    teile.push(label.hinweis || "");
  } else {
    teile.push(t("labels.sourceFile", {
      quelle: label.quelle,
      date: (label.stand || "").split("-").reverse().join("."),
    }));
    teile.push(hinweis);
  }
  marke.title = teile.filter(Boolean).join(" · ");
  return marke;
}

function bindeAdressLabelsUi() {
  if (bindeAdressLabelsUi._done) return;
  bindeAdressLabelsUi._done = true;

  const laden = $("#label-laden");
  if (laden) laden.addEventListener("click", ladeLabels);
  const labelImport = $("#label-import");
  if (labelImport) labelImport.addEventListener("click", starteLabelImport);
  const labelDateien = $("#label-dateien");
  if (labelDateien) labelDateien.addEventListener("change", liesLabelImportDateien);
  const verwerfen = $("#label-verwerfen");
  if (verwerfen) verwerfen.addEventListener("click", verwirfLabels);
}

bindeAdressLabelsUi();
