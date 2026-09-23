/** Sanktionscheck-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: Globals aus app.js (Zustand, api, t, $, …).
 * Kein import/export. Mix-/Börsen-Leisten bleiben in app.js (geteilt).
 * Wallet-Sanktionskarte bleibt in wallets.js.
 */

// ---------------------------------------------------------------------------
// Sanktionscheck (xpub-blind, Hop-Vorgeschichte)
// ---------------------------------------------------------------------------

function fuellSankWallets() {
  const wahl = $("#sank-wallet");
  wahl.replaceChildren();
  const alle = document.createElement("option");
  alle.value = "";
  alle.textContent = t("wallets.allWallets");
  wahl.append(alle);
  for (const w of Zustand.config?.wallets || []) {
    const opt = document.createElement("option");
    opt.value = w.id;
    opt.textContent = w.name;
    wahl.append(opt);
  }
}

function sankMeldung(text, krit = true) {
  const kasten = $("#sank-meldung");
  kasten.className = krit ? "hinweis hinweis-krit" : "hinweis";
  setzeText(kasten, text);
  kasten.hidden = !text;
}

function zeichneSankErgebnis(daten) {
  const behaelter = $("#sank-ergebnis");
  behaelter.replaceChildren();

  // Woher das Ergebnis stammt: frisch gelaufen oder aus dem Cache. Ein
  // Sanktionsbefund ohne Datum wäre wertlos — die Listen ändern sich, und
  // der UTXO-Bestand auch.
  const zusatz = $("#sank-check-zusatz");
  if (daten.erstellt) {
    const teile = [`Stand ${daten.erstellt}`, `${daten.max_hops} Hop(s)`];
    if (daten.listen_adressen) {
      teile.push(`${formatZahl(daten.listen_adressen)} Listenadressen`);
    }
    if (daten.verbindungen > 1) teile.push(`${daten.verbindungen} Verbindungen`);
    if (daten.vollstaendig === false) teile.push("abgebrochen");
    setzeText(zusatz, teile.join(" · "));
  } else {
    setzeText(zusatz, "");
  }
  $("#sank-verwerfen").hidden = !daten.erstellt;

  for (const w of daten.wallets || []) {
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    const treffer = w.treffer || [];
    const umfang =
      `${w.wallet}: ${w.geprueft} UTXO(s)` +
      (w.adressen_geprueft
        ? t("sanctions.addressesChecked", { count: formatZahl(w.adressen_geprueft) })
        : "");
    if (treffer.length === 0) {
      zeile.append(pille("gut", t("sanctions.noHit")));
      const text = document.createElement("span");
      text.textContent =
        t("sanctions.cleanWindow", { hops: daten.max_hops || "?" }) +
        " · " +
        umfang +
        (w.abgebrochen ? t("sanctions.abortedSuffix") : "");
      zeile.append(text);
    } else {
      zeile.append(pille("krit", t("sanctions.hits", { count: treffer.length })));
      const text = document.createElement("span");
      text.textContent = umfang;
      zeile.append(text);
    }
    behaelter.append(zeile);

    for (const hit of treffer) {
      const detail = document.createElement("div");
      detail.className = "sanktions-zeile sanktions-treffer";
      const beschreibung = document.createElement("span");
      beschreibung.className = "mono klein";
      beschreibung.textContent =
        `Hop ${hit.hop} · ${hit.address} · ${formatSats(hit.amount_sats || 0)} ` +
        `über UTXO ${hit.from_utxo}`;
      detail.append(beschreibung);
      const link = mempoolVerweis("address", hit.address);
      if (link) detail.append(link);
      behaelter.append(detail);
    }

    const coinjoins = w.coinjoins || [];
    if (coinjoins.length) {
      const cjKopf = document.createElement("div");
      cjKopf.className = "sanktions-zeile";
      cjKopf.append(pille("warn", t("sanctions.coinjoins", { count: coinjoins.length })));
      const cjText = document.createElement("span");
      cjText.textContent = t("sanctions.coinjoinsHint");
      cjKopf.append(cjText);
      behaelter.append(cjKopf);
      for (const cj of coinjoins) {
        const detail = document.createElement("div");
        detail.className = "sanktions-zeile sanktions-coinjoin";
        const beschreibung = document.createElement("span");
        beschreibung.className = "mono klein";
        const when = cj.time || t("sanctions.timeUnknown");
        const en = uiSprache() === "en";
        let label =
          (en ? cj.label_en : cj.label) ||
          cj.label ||
          cj.label_en ||
          t("sanctions.coinjoinGeneric");
        if (/^wahrscheinlich\s+/i.test(label)) {
          label =
            t("sanctions.presumablyPrefix") +
            label.replace(/^wahrscheinlich\s+/i, "");
        } else if (/^likely\s+/i.test(label)) {
          label =
            t("sanctions.presumablyPrefix") + label.replace(/^likely\s+/i, "");
        }
        const tid = cj.txid ? kuerze(cj.txid, 10, 8) : "";
        beschreibung.textContent = t("sanctions.coinjoinLine", {
          hop: cj.hop ?? "?",
          when,
          label,
          tx: tid ? ` · Tx ${tid}` : "",
        });
        detail.append(beschreibung);
        if (cj.txid) {
          const link = mempoolVerweis("tx", cj.txid);
          if (link) detail.append(link);
        }
        behaelter.append(detail);
      }
    }

    const adressen = w.adressen || [];
    if (adressen.length) {
      const block = document.createElement("details");
      block.className = "sanktions-adressen";
      const titel = document.createElement("summary");
      titel.textContent = w.adressen_gekappt
        ? t("ui.hard.fa188a3309", { shown: formatZahl(adressen.length), total: formatZahl(w.adressen_geprueft) })
        : t("ui.hard.87e81c14a3", { n: formatZahl(adressen.length) });
      block.append(titel);
      const liste = document.createElement("div");
      liste.className = "mono klein";
      liste.textContent = adressen.join("\n");
      block.append(liste);
      behaelter.append(block);
    }
  }
}

/**
 * Zuletzt gespeichertes Ergebnis anzeigen.
 *
 * Ein Lauf über mehrere Hops dauert Minuten; beim Öffnen der Ansicht wird
 * deshalb der letzte Stand gezeigt, sichtbar datiert, statt automatisch neu
 * zu prüfen.
 */
async function ladeSankCache() {
  $("#sank-verwerfen").hidden = true;
  try {
    const daten = await api("/sanctions/check");
    if (!daten.vorhanden) {
      $("#sank-ergebnis").replaceChildren();
      setzeText($("#sank-check-zusatz"), t("sanctions.notYetChecked"));
      return;
    }
    zeichneSankErgebnis(daten);
    if (daten.max_hops) $("#sank-hops").value = daten.max_hops;
  } catch (fehler) {
    setzeText($("#sank-check-zusatz"), "");
    sankMeldung(t("sanctions.cacheUnreadable", { msg: fehler.message }));
  }
}

async function verwerfeSankCache() {
  try {
    await api("/sanctions/check", { methode: "DELETE" });
  } catch (fehler) {
    sankMeldung(t("sanctions.discardFailed", { msg: fehler.message }));
    return;
  }
  $("#sank-ergebnis").replaceChildren();
  setzeText($("#sank-check-zusatz"), t("sanctions.notYetChecked"));
  $("#sank-verwerfen").hidden = true;
  sankMeldung("");
}

/** Stoppt den lokalen Sanktions-Check-Poller (Seitenwechsel / Neustart). */
function stoppeSanktionsCheckPoller() {
  if (Zustand.sanktionsCheckTimer) {
    clearInterval(Zustand.sanktionsCheckTimer);
    Zustand.sanktionsCheckTimer = null;
  }
}

/**
 * Bindet UI an einen laufenden (oder fertigen) sanctions-check-Job.
 * Nach Seitenwechsel / Klick auf den Vorgang wieder aufrufen.
 */
function bindeSanktionsCheckJob(jobId, opts = {}) {
  if (!jobId) return;
  stoppeSanktionsCheckPoller();
  Zustand.sanktionsCheckJobId = jobId;

  const knopf = $("#sank-start");
  const abbruch = $("#sank-abbruch");
  const lauf = $("#sank-lauf");
  const laufText = $("#sank-lauf-text");
  if (knopf) knopf.disabled = true;
  if (abbruch) abbruch.hidden = false;
  if (lauf) lauf.hidden = false;
  if (laufText) {
    setzeText(laufText, t("sanctions.running") || "Prüfe…");
  }
  if (opts.hops && $("#sank-hops")) {
    $("#sank-hops").value = opts.hops;
  }

  const fertig = (meldung, kritisch = true) => {
    stoppeSanktionsCheckPoller();
    Zustand.sanktionsCheckJobId = null;
    if (knopf) knopf.disabled = false;
    if (abbruch) abbruch.hidden = true;
    if (lauf) lauf.hidden = true;
    if (meldung) sankMeldung(meldung, kritisch);
  };

  if (abbruch) {
    abbruch.onclick = async () => {
      setzeText(laufText, t("common.abortRequested") || "Abbruch angefordert…");
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* Job evtl. schon weg */
      }
    };
  }

  const tick = async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      if (laufText) {
        setzeText(
          laufText,
          übersetzeLogText(job.message || t("common.runningEllipsis")),
        );
      }
      if (job.running) return;
      if (job.status === "done" && job.result) {
        fertig(übersetzeLogText(job.message || ""), false);
        zeichneSankErgebnis(job.result);
      } else if (job.status === "cancelled") {
        fertig(t("common.cancelled") || "Abgebrochen", false);
        ladeSankCache();
      } else {
        fertig(
          übersetzeServerMeldung(job.error)
            || übersetzeLogText(job.message)
            || t("common.failed"),
        );
      }
    } catch (fehler) {
      // Kurz weg: Poll weiter — Job kann noch laufen (Netz/Throttle).
      if (laufText) {
        setzeText(
          laufText,
          t("sanctions.checkPollError", { msg: fehler.message }) !== "sanctions.checkPollError"
            ? t("sanctions.checkPollError", { msg: fehler.message })
            : t("ui.hard.d42b02b7be", { msg: fehler.message }),
        );
      }
    }
  };

  tick();
  Zustand.sanktionsCheckTimer = setInterval(tick, 1200);
}

async function starteSanktionsCheck() {
  if (Zustand.sanktionsCheckJobId) {
    bindeSanktionsCheckJob(Zustand.sanktionsCheckJobId);
    return;
  }
  const knopf = $("#sank-start");
  const abbruch = $("#sank-abbruch");
  knopf.disabled = true;
  abbruch.hidden = false;
  $("#sank-lauf").hidden = false;
  setzeText($("#sank-lauf-text"), t("sanctions.checkStarting"));
  sankMeldung("");
  $("#sank-ergebnis").replaceChildren();

  let hops = parseInt($("#sank-hops").value, 10);
  if (Number.isNaN(hops) || hops < 1) hops = 3;
  const hopCap = Number((Zustand.config || {}).sanktion_max_hops_cap) || 20;
  hops = Math.min(hops, hopCap);

  const daten = { max_hops: hops };
  const walletId = $("#sank-wallet").value;
  if (walletId) daten.wallet_id = walletId;

  try {
    const job = await api("/sanctions/check", { methode: "POST", daten });
    bindeSanktionsCheckJob(job.id, { hops });
  } catch (fehler) {
    stoppeSanktionsCheckPoller();
    Zustand.sanktionsCheckJobId = null;
    knopf.disabled = false;
    abbruch.hidden = true;
    $("#sank-lauf").hidden = true;
    sankMeldung(t("sanctions.checkFailed", { msg: fehler.message }));
  }
}

