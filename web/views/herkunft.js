/** Herkunft-/Trace-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: nutzt Globals aus app.js (Zustand, api, t, $, …).
 * Kein import/export. Nach app.js, vor steuerjahr.js und boot.js laden
 * (Steuerjahr ruft herkunftGelbUtxos / herkunftAllerUtxos auf).
 */

// ---------------------------------------------------------------------------
// Herkunft
// ---------------------------------------------------------------------------

const PUNKT_KLASSE = {
  internal: "knoten-eigen",
  external: "knoten-extern",
  external_unresolved: "knoten-offen",
  coinbase: "knoten-coinbase",
  tax_horizon: "knoten-offen",
  error: "knoten-krit",
  unknown: "knoten-krit",
  cycle: "knoten-krit",
};

/**
 * Oberste Ebene (Adressen) startet zu. Darunter: gespeicherte Bäume offen,
 * ungescannte UTXOs zu — Aufklappen würde den Node fragen.
 *
 * *erzwingen*: auch im Fokus-Modus die volle Liste (Nav „Herkunft tracen“).
 */
async function ladeTraceListe({ erzwingen = false } = {}) {
  if (Zustand.traceFokus && !erzwingen) {
    await zeichneTraceFokusAnsicht(Zustand.traceFokus);
    return;
  }
  Zustand.traceFokus = null;
  setzeTraceFokusUi(false);
  const liste = $("#trace-liste");
  // /api/utxos ist Cache — Quellen-Hinweis gehört nur in die Scan-Leiste.
  liste.replaceChildren(hinweisZeile(t("common.loadingFromCache")));

  try {
    // mempool=0: Herkunftsliste braucht keinen Electrs-Rundlauf über alle Wallets.
    const daten = await api("/utxos?mempool=0");
    Zustand.traceListe = daten;
    zeichneTraceListe(daten);
  } catch (fehler) {
    liste.replaceChildren(hinweisZeile(t("common.couldNotLoad", { msg: fehler.message })));
  }
}

function setzeTraceFokusUi(an) {
  const karteTitel = document.querySelector("#ansicht-trace .karte-titel");
  if (karteTitel) {
    karteTitel.textContent = an
      ? (t("trace.focusTitle") !== "trace.focusTitle"
        ? t("trace.focusTitle")
        : t("ui.hard.2dcd257353"))
      : (t("trace.currentUtxos") !== "trace.currentUtxos"
        ? t("trace.currentUtxos")
        : "Aktuelle UTXOs");
  }
  const alle = $("#trace-herkunft-alle");
  if (alle) alle.hidden = Boolean(an);
}

/**
 * Fokus-Ansicht: nur ein UTXO/Tx (Sprung aus Wallet), kein Gesamtbestand.
 */
async function zeichneTraceFokusAnsicht(fokus, { neu = false, jobId = null } = {}) {
  const schluessel = (fokus && fokus.key) || "";
  if (!schluessel) {
    Zustand.traceFokus = null;
    await ladeTraceListe({ erzwingen: true });
    return;
  }
  setzeTraceFokusUi(true);
  const liste = $("#trace-liste");
  liste.replaceChildren();

  const leiste = document.createElement("div");
  leiste.className = "trace-fokus-leiste";
  const hinweis = document.createElement("span");
  hinweis.className = "meta";
  hinweis.textContent =
    t("trace.focusHint") !== "trace.focusHint"
      ? t("trace.focusHint")
      : "Nur dieses UTXO — Sprung aus der Wallet-Ansicht.";
  const zurueck = document.createElement("button");
  zurueck.type = "button";
  zurueck.className = "knopf knopf-klein";
  zurueck.textContent =
    t("trace.showAllUtxos") !== "trace.showAllUtxos"
      ? t("trace.showAllUtxos")
      : t("ui.hard.fd86abe4ac");
  zurueck.title =
    t("trace.showAllUtxosTitle") !== "trace.showAllUtxosTitle"
      ? t("trace.showAllUtxosTitle")
      : t("ui.hard.288a254437");
  zurueck.addEventListener("click", () => {
    Zustand.traceFokus = null;
    ladeTraceListe({ erzwingen: true });
  });
  leiste.append(hinweis, zurueck);
  liste.append(leiste);

  setzeText(
    $("#trace-liste-zusatz"),
    kuerze(schluessel, 14, 10),
  );

  const utxo = {
    key: schluessel,
    value_sats: fokus.value_sats ?? null,
    address: fokus.address || "",
    // Kein Fallback auf Zustand.walletId — sonst steht während des Scans
    // z. B. „Firmung“, obwohl das UTXO zu einem anderen Wallet gehört.
    wallet: fokus.wallet || "",
    time_label: fokus.time_label || "",
    hold_days: fokus.hold_days,
    block_height: fokus.block_height,
    verfolgt: Boolean(fokus.verfolgt),
    verfolgt_vollstaendig: Boolean(fokus.verfolgt_vollstaendig),
    receive_pending: Boolean(fokus.receive_pending),
  };

  const block = zeichneTraceWurzel(utxo);
  const huelle = document.createElement("div");
  huelle.className = "trace-fokus";
  huelle.append(block);
  liste.append(huelle);

  const kopf = block.querySelector(".utxo-kopf");
  const zweig = block.querySelector(".utxo-zweig");
  const klapp = block.querySelector(".klapp");
  if (!zweig) return;

  setzeKlapp(kopf, klapp, zweig, true);
  if (neu) {
    logZeile(
      t("ui.hard.2b19792199", { key: kuerze(schluessel, 12, 8) }),
      undefined,
      walletNameZu(Zustand.walletId),
    );
    // force: alten Cache verwerfen — sonst kommt derselbe kaputte Stand zurück.
    await starteZweigTrace(utxo, zweig, klapp, null, jobId, { force: true });
  } else {
    await oeffneZweig(utxo, zweig, klapp, jobId);
  }
  aktualisiereTraceWurzelKopf(utxo, block);
  huelle.scrollIntoView({ behavior: "smooth", block: "nearest" });
  aktualisiereKopfFilterFuerAnsicht();
  wendeKopfFilterAn();
}

function hinweisZeile(text) {
  const zeile = document.createElement("div");
  zeile.className = "zweig-status";
  zeile.textContent = text;
  return zeile;
}

// Sortiermodus für Herkunft-tracen (persistiert während der Sitzung)
if (!Zustand.traceSort) {
  Zustand.traceSort = "volume-desc";
}

function zeichneTraceListe(daten) {
  const liste = $("#trace-liste");
  liste.replaceChildren();

  const traceUtxos = [];
  for (const g of daten.addresses || []) {
    for (const u of g.utxos || []) traceUtxos.push(u);
  }
  const teile = [
    `${daten.total_count} UTXO`,
    formatSatsGemeinsam(daten.total_sats, traceUtxos),
  ];
  if (daten.wallets_ohne_cache && daten.wallets_ohne_cache.length > 0) {
    teile.push(`ohne Cache: ${daten.wallets_ohne_cache.join(", ")}`);
  }
  setzeText($("#trace-liste-zusatz"), teile.join(" · "));

  // Sortier-Dropdown in der gleichen Zeile wie Anzahl + Legende
  const sortWrap = $("#trace-sort-wrap");
  const sel = $("#trace-sort");
  if (sel) {
    sel.value = Zustand.traceSort || "volume-desc";
    if (!sel.dataset.gebunden) {
      sel.dataset.gebunden = "1";
      sel.addEventListener("change", () => {
        Zustand.traceSort = sel.value;
        if (Zustand.traceLastData) {
          zeichneTraceListe(Zustand.traceLastData);
        }
      });
    }
  } else if (!sortWrap) {
    // Fallback falls HTML-IDs fehlen
    const wrap = document.createElement("span");
    wrap.id = "trace-sort-wrap";
    wrap.className = "karte-zusatz";
    const neu = document.createElement("select");
    neu.id = "trace-sort";
    neu.className = "knopf knopf-klein";
    neu.innerHTML = `
      <option value="volume-desc">${t("ui.hard.7b461dc91e")}</option>
      <option value="age-desc">${t("ui.hard.330feefb19")}</option>
      <option value="age-asc">${t("ui.hard.9076c89cd2")}</option>
    `;
    neu.value = Zustand.traceSort || "volume-desc";
    neu.dataset.gebunden = "1";
    neu.addEventListener("change", () => {
      Zustand.traceSort = neu.value;
      if (Zustand.traceLastData) zeichneTraceListe(Zustand.traceLastData);
    });
    wrap.appendChild(neu);
    const kopf = document.querySelector("#ansicht-trace .karte-kopf");
    if (kopf) kopf.appendChild(wrap);
  }

  // Daten für spätere Sortier-Wechsel merken
  Zustand.traceLastData = daten;

  if (daten.total_count === 0 && !daten.hat_verlauf) {
    liste.append(hinweisZeile(
      "Keine UTXOs im Cache. Wallets zuerst scannen — in der Wallet-Ansicht " +
      "über „Bestand“."
    ));
    aktualisiereKopfFilterFuerAnsicht();
    return;
  }

  const sortMode = Zustand.traceSort || "volume-desc";
  fuelleTraceSortiert(liste, daten.addresses || [], sortMode);

  liste.append(zeichneAusgegeben(daten));
  aktualisiereKopfFilterFuerAnsicht();
  wendeKopfFilterAn();
}

/**
 * Sortierung wie Dropdown „Herkunft tracen“: Volumen → Adressgruppen,
 * Alter → flache UTXO-Liste. Wird für Bestand und „Bereits ausgegeben“ genutzt.
 */
function _traceUtxoAlterTs(utxo) {
  return Number(
    utxo.spent_time_ts
    || utxo.spent_block_time
    || utxo.block_time
    || 0,
  );
}

function _traceUtxoAlterHoehe(utxo) {
  return Number(
    utxo.spent_block_height
    || utxo.block_height
    || 0,
  );
}

function fuelleTraceSortiert(behaelter, addresses, sortMode) {
  const mode = sortMode || "volume-desc";
  if (mode === "volume-desc") {
    const gruppen = [...(addresses || [])].sort(
      (a, b) => (b.total_sats || 0) - (a.total_sats || 0),
    );
    for (const gruppe of gruppen) {
      behaelter.append(zeichneTraceAdressGruppe(gruppe));
    }
    return;
  }
  const alle = [];
  for (const gruppe of addresses || []) {
    for (const utxo of gruppe.utxos || []) {
      alle.push({ ...utxo, _address: gruppe.address });
    }
  }
  if (mode === "age-desc") {
    alle.sort((a, b) => {
      const dh = _traceUtxoAlterHoehe(b) - _traceUtxoAlterHoehe(a);
      if (dh) return dh;
      return _traceUtxoAlterTs(b) - _traceUtxoAlterTs(a);
    });
  } else if (mode === "age-asc") {
    alle.sort((a, b) => {
      const dh = _traceUtxoAlterHoehe(a) - _traceUtxoAlterHoehe(b);
      if (dh) return dh;
      return _traceUtxoAlterTs(a) - _traceUtxoAlterTs(b);
    });
  } else {
    alle.sort((a, b) => (b.value_sats || 0) - (a.value_sats || 0));
  }
  for (const utxo of alle) {
    const block = zeichneTraceWurzel(utxo);
    if (utxo._address) block.dataset.address = utxo._address;
    behaelter.append(block);
  }
}

/**
 * Bereits ausgegebene Outputs — Abschnitt bleibt zu, Inhalt ist Cache.
 *
 * Dieselbe Datei wie Steuerjahr. Der Kasten selbst bleibt zu, weil das
 * schnell hunderte Vorgänge sind; öffnet man ihn, stehen die Gruppen und
 * gespeicherten Bäume darin genauso offen wie beim aktuellen Bestand.
 */
function zeichneAusgegeben(daten) {
  const block = document.createElement("div");
  block.className = "ausgegeben-block";

  const verlauf = daten.verlauf || {};
  if (!daten.hat_verlauf) {
    block.append(hinweisZeile(
      "Ausgegebene Beträge sind nicht erfasst. „Historie“ in der " +
      "Wallet-Ansicht holt die Historie dieses Wallets — danach lassen sich " +
      "auch längst abgeflossene Sats hier verfolgen."
    ));
    return block;
  }
  if (!verlauf.total_count) {
    block.append(hinweisZeile(t("wallet.noSpendsYet")));
    return block;
  }

  const kopf = document.createElement("button");
  kopf.type = "button";
  kopf.className = "adress-kopf";
  kopf.setAttribute("aria-expanded", "false");

  const klapp = document.createElement("span");
  klapp.className = "klapp";
  klapp.textContent = "▸";
  klapp.setAttribute("aria-hidden", "true");

  const titel = document.createElement("span");
  titel.textContent = t("wallet.spentSection");
  titel.setAttribute("title", t("wallet.spentSectionTitle"));

  const zusatz = document.createElement("span");
  zusatz.className = "zart";
  const pendingN = Number(verlauf.pending_count || daten.pending_spends || 0);
  // Nur BTC/sats — kein Spot-€ auf dem Brutto-Volumen (alte Ausgaben
  // würden sonst zum heutigen Kurs zu „Reichtum“). € je Vorgang steht
  // an den Adress-/UTXO-Zeilen zum Tageskurs am Ausgabedatum.
  zusatz.textContent =
    t("wallet.spentSummary", {
      count: verlauf.total_count,
      sats: formatSatsBasis(verlauf.total_sats),
    }) +
    (pendingN > 0
      ? ` · ${t("wallet.spentPendingCount", { n: pendingN })}`
      : "") +
    (verlauf.shown_count < verlauf.total_count
      ? ` · ${t("wallet.spentShown", { n: verlauf.shown_count })}`
      : "");

  kopf.append(klapp, titel, zusatz);

  const inhalt = document.createElement("div");
  inhalt.className = "ausgegeben-inhalt";
  inhalt.hidden = true;

  kopf.addEventListener("click", () => {
    const auf = inhalt.hidden;
    setzeKlapp(kopf, klapp, inhalt, auf);
    // Erst beim Aufklappen zeichnen: Bei hunderten Vorgängen kostet das
    // sonst bei jedem Öffnen der Ansicht Zeit, die niemand angefordert hat.
    if (auf && !inhalt.dataset.gezeichnet) {
      inhalt.dataset.gezeichnet = "ja";
      Promise.resolve(ladeKursSerie()).finally(() => {
        inhalt.replaceChildren();
        fuelleTraceSortiert(
          inhalt,
          verlauf.addresses || [],
          Zustand.traceSort || "volume-desc",
        );
        // Aktiven Kopf-Filter auf frisch gezeichnete Zeilen anwenden.
        if (kopfFilterAnsichtAktiv(Zustand.ansicht)) wendeKopfFilterAn();
      });
    }
  });

  block.append(kopf, inhalt);
  return block;
}

/**
 * Eine Adresse mit ihren UTXOs.
 *
 * Die Gruppe ist die oberste Ebene und startet zu. Beim Öffnen stehen
 * gespeicherte Bäume offen; ohne Baum bleibt das UTXO zu.
 */
function zeichneTraceAdressGruppe(gruppe) {
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
  if (gruppe.address) {
    adresse.textContent = kuerze(gruppe.address, 16, 8);
    macheKopierbar(adresse, gruppe.address, "Adresse");
  } else {
    // Sparrow-Tx-CSV u. ä.: Verlauf ohne Adresse — kein leeres mono-Feld.
    adresse.classList.remove("mono");
    adresse.classList.add("zart");
    adresse.textContent = t("wallet.noAddressInExport");
  }

  const wallet = document.createElement("span");
  wallet.className = "zart";
  wallet.textContent = gruppe.wallet || t("wallet.unknownWallet");

  const anzahl = document.createElement("span");
  anzahl.className = "adress-zahl";
  const zahlBasis =
    gruppe.utxo_count === 1 ? "1 UTXO" : `${gruppe.utxo_count} UTXOs`;
  const ausgabeZusatz = gruppeAusgegebenZusatz(gruppe);
  anzahl.textContent = ausgabeZusatz
    ? `${zahlBasis}, ${ausgabeZusatz}`
    : zahlBasis;

  kopf.append(klapp, adresse, wallet, anzahl);
  if (gruppe.utxos.some((u) => u.flagged)) {
    kopf.append(pille("krit", t("trace.listed")));
  }
  haengeGruppenJuengsteAn(kopf, gruppe);

  const betrag = document.createElement("span");
  betrag.className = "betrag adress-betrag";
  if ((gruppe.utxos || []).some((u) => u.spent || u.spent_pending)) {
    setzeSatsBetrag(betrag, gruppe.total_sats, {
      gemeinsam: gruppe.utxos || [],
      tsFn: spentZeitstempel,
    });
  } else {
    setzeSatsBetrag(betrag, gruppe.total_sats, {
      gemeinsam: gruppe.utxos || [],
    });
  }
  kopf.append(betrag);
  // Mix-Icons + Börsen-Pillen vor dem Betrag (wie nach Trace-Update).
  _haengeGruppenLeistenAn(kopf, gruppe);

  const inhalt = document.createElement("div");
  inhalt.className = "trace-utxos";
  // Lazy: UTXO-Zeilen erst beim Aufklappen — sonst 30+ Wurzeln + Bäume sofort.
  let utxosGebaut = false;
  setzeKlapp(kopf, klapp, inhalt, false);

  kopf.addEventListener("click", () => {
    const auf = inhalt.hidden;
    if (auf && !utxosGebaut) {
      for (const utxo of gruppe.utxos || []) {
        inhalt.append(zeichneTraceWurzel(utxo));
      }
      utxosGebaut = true;
    }
    setzeKlapp(kopf, klapp, inhalt, auf);
    // Bäume bleiben zu — erst bei Klick aufs einzelne UTXO (oeffneZweig).
    if (kopfFilterAnsichtAktiv(Zustand.ansicht)) wendeKopfFilterAn();
  });

  const kopfzeile = document.createElement("div");
  kopfzeile.className = "kopf-mit-verweis";
  kopfzeile.append(kopf);
  const extern = mempoolVerweis("address", gruppe.address);
  if (extern) kopfzeile.append(extern);

  block.append(kopfzeile, inhalt);
  // Für Fokus-Sprung / Tests: Wurzeln nachziehbar ohne Gruppen-Klick.
  block.baueUtxos = () => {
    if (utxosGebaut) return;
    for (const utxo of gruppe.utxos || []) {
      inhalt.append(zeichneTraceWurzel(utxo));
    }
    utxosGebaut = true;
  };
  return block;
}

function zeichneTraceWurzel(utxo) {
  const block = document.createElement("div");
  block.className = "utxo-wurzel";
  setzeUtxoTraceDaten(block, utxo);

  // Die ganze Zeile ist bedienbar, nicht nur das Dreieck: Ein Ziel von zwölf
  // Pixeln trifft niemand gern. Als Button statt als div, damit Tastatur und
  // Bildschirmleser ihn ohne Zusatzarbeit bekommen.
  // Title nicht an die ganze Zeile — sonst überschreibt er Mix-Icon-Tooltips.
  const zeile = document.createElement("button");
  zeile.type = "button";
  zeile.className = "baum-knoten utxo-kopf";

  const klapp = document.createElement("span");
  klapp.className = "klapp";
  klapp.title = t("trace.hard.f3a13f2fe7");
  klapp.setAttribute("aria-hidden", "true");

  const punkt = document.createElement("span");
  punkt.className = "knoten-punkt knoten-eigen";

  const info = document.createElement("span");
  info.className = "knoten-info";

  const oben = document.createElement("span");
  oben.className = "knoten-oben";
  const betrag = document.createElement("span");
  betrag.className = "betrag";
  if (utxo.value_sats == null) {
    betrag.textContent = t("trace.amountPending");
    betrag.classList.add("zart");
  } else if (utxo.spent || utxo.spent_pending) {
    const st = spentZeitstempel(utxo);
    if (st) setzeSatsBetrag(betrag, utxo.value_sats, { atTs: st });
    else betrag.textContent = formatSatsBasis(utxo.value_sats);
  } else {
    const atTs = tsAusBewertungsObjekt(utxo);
    if (atTs) setzeSatsBetrag(betrag, utxo.value_sats, { atTs });
    else betrag.textContent = formatSats(utxo.value_sats);
  }
  const wer = document.createElement("span");
  wer.textContent = utxo.wallet || t("wallet.unknownWallet");
  const adresse = document.createElement("span");
  adresse.className = "mono zart";
  adresse.textContent = utxo.address
    ? kuerze(utxo.address, 12, 6)
    : t("trace.addressPending");
  if (utxo.address) macheKopierbar(adresse, utxo.address, "Adresse");
  oben.append(betrag, wer, adresse);

  // Vor dem Aufklappen sichtbar: Analyse da / unvollständig (rot) / frisch.
  if (utxo.verfolgt) {
    const marke = document.createElement("span");
    oben.append(marke);
    setzeVerfolgtMarke(oben, utxo);

    const juengste = juengsteSatsMarke(utxo);
    if (juengste) oben.append(juengste);
  }

  // Ausgabe unterwegs (Mempool, eigener Node) — noch im Bestand sichtbar.
  if (utxo.spending_pending && !utxo.spent && !utxo.spent_pending) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke spending-pending";
    marke.textContent = t("trace.spendingPending");
    marke.title = t("trace.spendingPendingTitle");
    if (utxo.spent_txid) {
      macheKopierbar(marke, utxo.spent_txid, "Ausgaben-TxID");
    }
    oben.append(marke);
  }

  // Eigener Empfang noch im Mempool (Selbstüberweisung/Change).
  if (utxo.receive_pending && !utxo.spending_pending && !utxo.spent) {
    const marke = document.createElement("span");
    marke.className = "verfolgt-marke receive-pending";
    marke.textContent = t("trace.receivePending");
    marke.title = t("trace.receivePendingTitle");
    oben.append(marke);
  }

  // Ausgegeben: Das muss in der Zeile stehen, sonst hielte man den Betrag für
  // Bestand — er ist längst weg. Pending = unbestätigt im Mempool (eigener Node).
  if (utxo.spent || utxo.spent_pending) {
    const marke = document.createElement("span");
    marke.className = utxo.spent_pending
      ? "verfolgt-marke ausgegeben pending"
      : "verfolgt-marke ausgegeben";
    if (utxo.spent_pending) {
      marke.textContent = t("trace.spentPending");
      marke.title = t("trace.spentPendingTitle");
    } else {
      const wann = formatAusgegebenWann(utxo);
      const an = formatAusgegebenAnBoerse(utxo);
      marke.title = an
        ? t("trace.spentToExchangeTitle")
        : t("trace.spentTitle");
      if (wann && an) {
        marke.append(document.createTextNode(`${wann} · `));
        const ziel = document.createElement("span");
        ziel.className = "label-boerse label-boerse-out";
        ziel.textContent = an;
        marke.append(ziel);
      } else {
        marke.textContent = wann || an || t("trace.spent");
      }
    }
    if (utxo.spent_txid) {
      macheKopierbar(marke, utxo.spent_txid, "Ausgaben-TxID");
    }
    oben.append(marke);
  }

  const unten = document.createElement("span");
  unten.className = "knoten-unten";
  const links = document.createElement("span");
  links.className = "knoten-unten-links";
  const utxoKennung = document.createElement("span");
  utxoKennung.className = "mono";
  utxoKennung.textContent = kuerze(utxo.key, 12, 8);
  macheKopierbar(utxoKennung, utxo.key, "UTXO (txid:vout)");
  links.append(utxoKennung);
  const ankunftText = formatAnkunft(utxo);
  if (ankunftText) {
    links.append(document.createTextNode(` · ${ankunftText}`));
  }
  unten.append(links);
  const rechts = document.createElement("span");
  rechts.className = "knoten-unten-rechts";
  rechts.hidden = true;
  unten.append(rechts);

  info.append(oben, unten);
  zeile.append(klapp, punkt, info);

  const zweig = document.createElement("div");
  zweig.className = "utxo-zweig";

  const kopfzeile = document.createElement("div");
  kopfzeile.className = "kopf-mit-verweis";
  kopfzeile.append(zeile);
  const neu = document.createElement("button");
  neu.type = "button";
  neu.className = "trace-link";
  neu.textContent = t("trace.rescan");
  neu.title = t("trace.rescanTitle");
  neu.addEventListener("click", (e) => {
    e.stopPropagation();
    zeigeHerkunftFuer(utxo.key, { neu: true });
  });
  kopfzeile.append(neu);
  const extern = mempoolVerweis("tx", (utxo.key || "").split(":")[0]);
  if (extern) kopfzeile.append(extern);

  block.append(kopfzeile, zweig);

  // Startet zu. Die Adressgruppe ruft oeffneAusCache, sobald sie selbst
  // aufgeht — dann nur, wenn der Baum im Cache liegt. Sonst würde jeder
  // sichtbare Eintrag den Node fragen.
  setzeKlapp(zeile, klapp, zweig, false);

  function oeffneAusCache() {
    if (!utxo.verfolgt) return;
    setzeKlapp(zeile, klapp, zweig, true);
    if (zweig.dataset.geladen === "ja" || zweig.dataset.geladen === "laeuft") return;
    ladeGespeichertenZweig(utxo, zweig, klapp).then((ok) => {
      if (!ok) setzeKlapp(zeile, klapp, zweig, false);
    });
  }
  block.oeffneAusCache = oeffneAusCache;

  zeile.addEventListener("click", (ereignis) => {
    // Der zweite Klick eines Doppelklicks würde sonst gleich wieder
    // zuklappen. So wirkt ein Doppelklick wie ein einfacher.
    if (ereignis.detail > 1) return;
    // Wer eine TxID mit der Maus markiert, will nicht aufklappen.
    if (window.getSelection().toString()) return;

    const auf = zweig.hidden;
    setzeKlapp(zeile, klapp, zweig, auf);
    if (!auf) return; // nur zuklappen
    // Schon geladen: nur aufklappen, kein erneuter Cache-/Analyse-Lauf.
    if (zweig.dataset.geladen === "ja" || zweig.dataset.geladen === "laeuft") {
      return;
    }
    oeffneZweig(utxo, zweig, klapp);
  });

  return block;
}

/** Liest nur den gespeicherten Baum. Kein Node, kein Job. */
async function ladeGespeichertenZweig(utxo, zweig, klapp) {
  if (!utxo || !utxo.key || !zweig) return false;
  zweig.dataset.geladen = "laeuft";
  zweig.replaceChildren(hinweisZeile(t("common.looking")));
  try {
    const gespeichert = await api(`/trace?target=${encodeURIComponent(utxo.key)}`);
    if (gespeichert && gespeichert.vorhanden && gespeichert.ergebnis) {
      zweig.dataset.geladen = "ja";
      try {
        zeichneZweig(gespeichert.ergebnis, zweig, utxo, klapp);
        merkeTraceAmUtxo(utxo, gespeichert.ergebnis);
        aktualisiereTraceWurzelKopf(utxo, zweig.closest(".utxo-wurzel"));
        // Snapshot-Kopf inkl. „Alles aufklappen“ ganz oben.
        zweig.prepend(gespeicherterKopf(gespeichert, utxo, zweig, klapp));
      } catch (zeichFehler) {
        zweig.dataset.geladen = "";
        zweig.replaceChildren(
          hinweisZeile(
            t("trace.cacheDrawFail") !== "trace.cacheDrawFail"
              ? t("trace.cacheDrawFail")
              : t("ui.hard.715fd677cb"),
          ),
        );
        return false;
      }
      return true;
    }
  } catch (fehler) {
    // Datei fehlt oder ist unlesbar — Aufrufer entscheidet.
  }
  zweig.dataset.geladen = "";
  zweig.replaceChildren();
  return false;
}

/**
 * Zweig öffnen: zuerst Cache. Neue Analyse nur wenn *nicht* als verfolgt
 * markiert — sonst würde jedes Aufklappen bei Cache-Hicksern einen Job starten.
 *
 * *jobId*: laufenden Job anbinden (Nav-Klick), kein zweiter POST.
 */
async function oeffneZweig(utxo, zweig, klapp, jobId = null) {
  if (!zweig) return;
  if (zweig.dataset.geladen === "ja") return;
  // Schon in Arbeit: kein zweiter Lauf (Timer/POST).
  if (zweig.dataset.geladen === "laeuft") return;
  // Sofort sperren — sonst starten zwei parallele oeffneZweig denselben Trace.
  zweig.dataset.geladen = "laeuft";

  // Laufender Job für dieses UTXO → anbinden statt Cache-Hop und neuem POST.
  const bekannt = jobId || (utxo && Zustand.traceJobs.get(utxo.key));
  if (bekannt) {
    starteZweigTrace(utxo, zweig, klapp, null, bekannt);
    return;
  }

  const ausCache = await ladeGespeichertenZweig(utxo, zweig, klapp);
  if (ausCache) return;

  // Markiert „verfolgt“, aber Datei fehlt/unlesbar → kein stiller Full-Trace.
  if (utxo && utxo.verfolgt) {
    zweig.dataset.geladen = "";
    const kasten = document.createElement("div");
    kasten.className = "zweig-status";
    const text = document.createElement("span");
    text.textContent =
      t("trace.cacheMissing") !== "trace.cacheMissing"
        ? t("trace.cacheMissing")
        : t("ui.hard.f6d3b51889");
    const neu = document.createElement("button");
    neu.type = "button";
    neu.className = "knopf knopf-klein";
    neu.textContent =
      t("trace.rescan") !== "trace.rescan" ? t("trace.rescan") : "Scan neu";
    neu.addEventListener("click", (e) => {
      e.stopPropagation();
      starteZweigTrace(utxo, zweig, klapp);
    });
    kasten.append(text, neu);
    zweig.replaceChildren(kasten);
    return;
  }

  // Noch nie verfolgt → Analyse starten (Server dedupliziert gleiches target).
  starteZweigTrace(utxo, zweig, klapp);
}

/**
 * Kopfzeile über einem gespeicherten Baum: wann erhoben, und der Weg zurück
 * zu einer frischen Analyse.
 *
 * Bei geänderter Adressmenge steht dort zusätzlich, woran das Ergebnis
 * womöglich vorbeigeht. Verworfen wird deshalb nichts — die Unsicherheit
 * benannt zu haben ist mehr wert als eine leere Ansicht.
 */
function gespeicherterKopf(gespeichert, utxo, zweig, klapp) {
  const kopf = document.createElement("div");
  kopf.className = "zweig-kopf";

  const stand = document.createElement("span");
  stand.className = "zweig-stand";
  stand.textContent = gespeichert.erstellt_ts
    ? t("trace.snapshotAt", { time: formatZeitpunkt(gespeichert.erstellt_ts * 1000) })
    : t("trace.storedAnalysis");
  kopf.append(stand);

  if (gespeichert.veraltet) {
    const warn = document.createElement("span");
    warn.className = "zweig-warnung";
    const dazu = gespeichert.adressen_seither;
    warn.textContent =
      dazu && dazu > 0
        ? t("trace.sinceAnalysisAdded", { count: formatZahl(dazu) })
        : t("trace.sinceAnalysisChanged");
    kopf.append(warn);
  }

  // Alles auf-/zuklappen direkt an der Snapshot-Zeile (gut sichtbar).
  if (zweig) kopf.append(baumKlappLeiste(zweig));

  return kopf;
}

/**
 * Startet die Analyse für genau einen UTXO und rendert sie in *zweig*.
 * *followup*: optional ``full`` (Lücken schließen), Legacy ``tx_oriented`` /
 * ``resolve_unresolved``.
 * *opts.force*: Cache verwerfen („Scan neu“) — sonst liefert der Server den
 * alten unvollständigen Baum wieder aus dem Immutable-Cache.
 */
async function starteZweigTrace(
  utxo, zweig, klapp, followup = null, jobIdVorgabe = null, opts = null,
) {
  const force = Boolean(opts && opts.force);
  zweig.dataset.geladen = "laeuft";

  const status = document.createElement("div");
  status.className = "zweig-status";
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  spinner.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.className = "zweig-status-text";
  text.textContent = followup
    ? t("trace.folgeStart")
    : t("trace.analyseStart");
  const abbruch = document.createElement("button");
  abbruch.type = "button";
  abbruch.className = "knopf knopf-klein";
  abbruch.textContent = t("common.cancel");
  abbruch.title = "Bricht diese Analyse ab. Andere laufen weiter.";
  status.append(spinner, text, abbruch);
  zweig.replaceChildren(status);

  let jobId = jobIdVorgabe || Zustand.traceJobs.get(utxo.key) || null;
  let timer = null;
  let abbruchWunsch = false;

  const aufraeumen = () => {
    clearInterval(timer);
    const gemerkt = Zustand.traceJobs.get(utxo.key);
    if (gemerkt === jobId) Zustand.traceJobs.delete(utxo.key);
  };

  const sendeAbbruch = async () => {
    const id = jobId;
    if (!id || String(id).startsWith("cache-")) return;
    try {
      await api(`/jobs/${id}`, { methode: "DELETE" });
    } catch (_) {
      /* war bereits beendet */
    }
  };

  abbruch.addEventListener("click", async (ereignis) => {
    // Nicht zum UTXO-Kopf durchbubbeln (Aufklappen / Fokus).
    ereignis.preventDefault();
    ereignis.stopPropagation();
    abbruchWunsch = true;
    abbruch.disabled = true;
    text.textContent = t("common.abortRequested");
    await sendeAbbruch();
  });

  const fehlschlag = (meldung) => {
    aufraeumen();
    zweig.dataset.geladen = "";
    zweig.replaceChildren(hinweisZeile(meldung));
  };

  const statusText = (job) => {
    const msg = (job && job.message) || "";
    const log = (job && job.log) || [];
    const letzte = log.length ? log[log.length - 1] : "";
    if (msg && letzte && letzte !== msg) return `${msg} · ${letzte}`;
    return msg || letzte || t("common.running");
  };

  try {
    if (jobId) {
      // Vorhandenen Job anbinden (Nav-Klick / zweiter Klick) — kein POST.
      try {
        const bestehend = await api(`/jobs/${jobId}`);
        if (!bestehend || (!bestehend.running && bestehend.status !== "done")) {
          jobId = null;
          Zustand.traceJobs.delete(utxo.key);
        } else if (bestehend.status === "done" && bestehend.result) {
          aufraeumen();
          zweig.dataset.geladen = "ja";
          zeichneZweig(bestehend.result, zweig, utxo, klapp);
          merkeTraceAmUtxo(utxo, bestehend.result);
          aktualisiereTraceWurzelKopf(utxo, zweig.closest(".utxo-wurzel"));
          if (bestehend.result.found) {
            zweig.prepend(gespeicherterKopf({
              erstellt_ts: utxo.verfolgt_ts || Math.floor(Date.now() / 1000),
              veraltet: false,
              adressen_seither: 0,
            }, utxo, zweig, klapp));
          }
          return;
        } else {
          text.textContent = statusText(bestehend);
        }
      } catch (_) {
        jobId = null;
        Zustand.traceJobs.delete(utxo.key);
      }
    }
    if (!jobId) {
      const daten = { target: utxo.key };
      if (followup) daten.followup = followup;
      if (force) daten.force = true;
      if (utxo.wallet) daten.wallet = utxo.wallet;
      if (utxo.address) daten.address = utxo.address;
      if (utxo.value_sats != null) daten.value_sats = utxo.value_sats;
      const job = await api("/trace", {
        methode: "POST",
        daten,
      });
      // Server-Cache-Hit: fertig ohne Job/Electrs (from_cache oder sofort done).
      if (
        (job.from_cache || job.status === "done")
        && job.result
        && job.result.found
      ) {
        aufraeumen();
        zweig.dataset.geladen = "ja";
        zeichneZweig(job.result, zweig, utxo, klapp);
        merkeTraceAmUtxo(utxo, job.result);
        aktualisiereTraceWurzelKopf(utxo, zweig.closest(".utxo-wurzel"));
        zweig.prepend(gespeicherterKopf({
          erstellt_ts: job.erstellt_ts
            || utxo.verfolgt_ts
            || Math.floor(Date.now() / 1000),
          veraltet: Boolean(job.veraltet),
          adressen_seither: job.adressen_seither || 0,
        }, utxo, zweig, klapp));
        return;
      }
      jobId = job.id;
      if (!jobId) {
        fehlschlag(job.error || t("trace.analyseFailShort"));
        return;
      }
      Zustand.traceJobs.set(utxo.key, jobId);
      // Abbruch schon vor Job-ID geklickt → jetzt nachreichen.
      if (abbruchWunsch) {
        text.textContent = t("common.abortRequested");
        abbruch.disabled = true;
        await sendeAbbruch();
      } else {
        text.textContent = statusText(job);
      }
    } else {
      Zustand.traceJobs.set(utxo.key, jobId);
      if (abbruchWunsch) {
        text.textContent = t("common.abortRequested");
        abbruch.disabled = true;
        await sendeAbbruch();
      }
    }
  } catch (fehler) {
    fehlschlag(t("trace.analyseFail", { msg: fehler.message }));
    return;
  }

  const fertigAusJob = (job) => {
    aufraeumen();
    if (job.status === "done" && job.result) {
      zweig.dataset.geladen = "ja";
      delete zweig.dataset.teilbaum;
      zeichneZweig(job.result, zweig, utxo, klapp);
      merkeTraceAmUtxo(utxo, job.result);
      aktualisiereTraceWurzelKopf(utxo, zweig.closest(".utxo-wurzel"));
      if (job.result.found) {
        zweig.prepend(gespeicherterKopf({
          erstellt_ts: utxo.verfolgt_ts || Math.floor(Date.now() / 1000),
          veraltet: false,
          adressen_seither: 0,
        }, utxo, zweig, klapp));
      } else if (!zweig.querySelector(".zweig-klapp-leiste")) {
        zweig.prepend(baumKlappLeiste(zweig));
      }
    } else if (job.status === "cancelled") {
      fehlschlag(t("trace.cancelled"));
    } else {
      fehlschlag(job.error || t("trace.analyseFailShort"));
    }
  };

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      text.textContent = statusText(job);
      if (job.running) return;
      fertigAusJob(job);
    } catch (fehler) {
      fehlschlag(fehler.message);
    }
  }, 900);
}

function folgeLueckenOffen(ergebnis) {
  // Bis jedes Blatt external (rot) oder coinbase (lila) ist, bleibt Entwirren offen.
  if (ergebnis && ergebnis.found && ergebnis.verfolgt_vollstaendig === false) {
    return true;
  }
  if (ergebnis && ergebnis.followup_tx_oriented_done && ergebnis.verfolgt_vollstaendig) {
    return false;
  }
  const suggestedTx = Boolean(ergebnis.followup_tx_oriented_suggested)
    && !ergebnis.followup_tx_oriented_done;
  const suggestedBundled = Boolean(
    ergebnis.followup_resolve_unresolved_suggested
    || (ergebnis.summary && ergebnis.summary.unresolved_inputs > 0),
  );
  return suggestedTx || suggestedBundled;
}

function folgeHinweisText(ergebnis) {
  if (ergebnis.verfolgt_vollstaendig && ergebnis.followup_tx_oriented_done) {
    return t("trace.folgeDoneHint");
  }
  if (folgeLueckenOffen(ergebnis)) {
    return t("trace.folgeLueckenHint");
  }
  if (ergebnis.verfolgt_vollstaendig) {
    return t("trace.folgeDoneHint");
  }
  return t("trace.folgeMore");
}

function zeichneFolgeBand(ergebnis, zweig, utxo, klapp) {
  const offen = folgeLueckenOffen(ergebnis);
  const doneTx = Boolean(ergebnis.followup_tx_oriented_done)
    && Boolean(ergebnis.verfolgt_vollstaendig);
  if (!offen && !doneTx) return;

  const band = document.createElement("div");
  band.className = "zweig-folge";
  const text = document.createElement("p");
  text.className = "zweig-folge-text";
  text.textContent = folgeHinweisText(ergebnis);
  const knoepfe = document.createElement("div");
  knoepfe.className = "zweig-folge-knoepfe";

  if (offen && utxo && klapp) {
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "knopf knopf-klein";
    knopf.textContent = t("trace.folgeLuecken");
    knopf.title = t("trace.folgeLueckenTitle");
    knopf.addEventListener("click", () => {
      if (!window.confirm(t("trace.folgeLueckenConfirm"))) return;
      starteZweigTrace(utxo, zweig, klapp, "full");
    });
    knoepfe.append(knopf);
  } else if (doneTx) {
    const erledigt = document.createElement("span");
    erledigt.className = "zweig-folge-erledigt";
    erledigt.textContent = t("trace.folgeDone");
    erledigt.title = t("trace.folgeDoneTitle");
    knoepfe.append(erledigt);
  }

  band.append(text, knoepfe);
  zweig.append(band);
}

function setzeWurzelTxClass(zweig, ergebnis, utxo = null) {
  /** Soft-Label (+ Icon) rechts neben Timestamp in der UTXO-Wurzelzeile. */
  const wurzel = zweig && zweig.closest(".utxo-wurzel");
  if (!wurzel) return;
  const unten = wurzel.querySelector(".utxo-kopf .knoten-unten");
  if (!unten) return;
  let rechts = unten.querySelector(".knoten-unten-rechts");
  if (!rechts) {
    rechts = document.createElement("span");
    rechts.className = "knoten-unten-rechts";
    unten.append(rechts);
  }
  const basis = ergebnis.root || ergebnis || {};
  // boerse_namen am UTXO/Ergebnis → „Auszahlung von Kraken“ statt „Wahrscheinlich…“.
  const ausErgebnis = boerseNamenAusErgebnis(ergebnis);
  const namen = (utxo && utxo.boerse_namen && utxo.boerse_namen.length)
    ? utxo.boerse_namen
    : (ausErgebnis.namen || basis.boerse_namen || []);
  fuelleTxClassRechts(rechts, {
    ...basis,
    boerse_namen: namen,
    tx_class: basis.tx_class || ergebnis.tx_class,
    tx_class_label: basis.tx_class_label || ergebnis.tx_class_label,
    tx_class_label_en: basis.tx_class_label_en || ergebnis.tx_class_label_en,
  });
}

function zeichneZweig(ergebnis, zweig, utxo = null, klapp = null) {
  zweig.replaceChildren();

  if (!ergebnis.found) {
    zweig.append(hinweisZeile(ergebnis.error || t("trace.none")));
    zweig.dataset.geladen = "";
    return;
  }

  setzeWurzelTxClass(zweig, ergebnis, utxo);
  const klasseHinweis = softTxClassLabel({
    ...(ergebnis.root || ergebnis || {}),
    boerse_namen: (utxo && utxo.boerse_namen) || boerseNamenAusErgebnis(ergebnis).namen,
    tx_class: (ergebnis.root || ergebnis || {}).tx_class || ergebnis.tx_class,
  });

  if (ergebnis.children.length === 0) {
    // Leere Kinder sind kein Trace-Ergebnis: entweder CJ-Soft-Label ohne
    // eigene Vorgänger, oder unvollständiger Lauf (Prevout fehlte). Nie
    // „Keine Zuflüsse“ so tun, als wäre extern/Coinbase erreicht.
    if (klasseHinweis) {
      zweig.append(hinweisZeile(t("trace.coinjoinOwnOnlyEmpty")));
    } else if (ergebnis.verfolgt_vollstaendig) {
      zweig.append(hinweisZeile(t("trace.noInflows")));
    } else {
      zweig.append(hinweisZeile(t("trace.incompleteEmpty")));
      zeichneFolgeBand(ergebnis, zweig, utxo, klapp);
    }
    return;
  }

  zweig.append(zeichneKnotenListe(ergebnis.children, utxo ? (utxo.wallet || "") : undefined));
  zeichneFolgeBand(ergebnis, zweig, utxo, klapp);

  const vorbehalt = vorbehaltText(ergebnis.summary);
  const fuss = document.createElement("div");
  fuss.className = "vorbehalt";
  fuss.style.paddingTop = "6px";
  const quelle = ergebnis.source ? `Quelle: ${ergebnis.source}. ` : "";
  fuss.textContent = quelle + vorbehalt;
  zweig.append(fuss);
}

/** Gezielte Suche nach TxID oder UTXO — Ergebnis erscheint oben in der Liste. */
async function starteTrace() {
  const roh = $("#trace-ziel").value.trim();
  if (!roh) return;

  $("#trace-start").disabled = true;
  $("#trace-meldung").hidden = true;

  // Reine TxID → Output #0 (explizit im Key und im Feld).
  const key = roh.includes(":") ? roh : `${roh}:0`;
  if (!roh.includes(":")) {
    $("#trace-ziel").value = key;
  }

  // Schon offene gezielte Suche zum selben UTXO wiederverwenden — sonst
  // stapeln sich Blöcke und der alte bleibt bei „0 sats“ / „…“.
  let block = document.querySelector(
    `#trace-liste .trace-suche .utxo-wurzel[data-key="${CSS.escape(key)}"]`,
  );
  let utxo = null;
  if (block) {
    utxo = {
      key,
      value_sats: null,
      address: "",
      wallet: t("trace.targetedWallet"),
      time_label: "",
    };
    const zweig = block.querySelector(".utxo-zweig");
    const klapp = block.querySelector(".klapp");
    if (zweig) {
      zweig.dataset.geladen = "";
      zweig.replaceChildren();
      zweig.hidden = false;
      if (klapp) klapp.textContent = "▾";
      // Frisch laden (Cache oder Job) und Kopfzeile danach setzen.
      await oeffneZweig(utxo, zweig, klapp);
      aktualisiereTraceWurzelKopf(utxo, block);
    }
    block.scrollIntoView({ behavior: "smooth", block: "nearest" });
    $("#trace-start").disabled = false;
    return;
  }

  utxo = {
    key,
    value_sats: null,
    address: "",
    wallet: t("trace.targetedWallet"),
    time_label: "",
  };

  // Steht ohne Adressgruppe ganz oben: Das UTXO muss nicht in der Liste
  // vorkommen — es kann längst ausgegeben sein.
  block = zeichneTraceWurzel(utxo);
  const huelle = document.createElement("div");
  huelle.className = "trace-suche";
  huelle.append(block);

  $("#trace-liste").prepend(huelle);
  const zweig = block.querySelector(".utxo-zweig");
  const klapp = block.querySelector(".klapp");
  // Direkt öffnen (nicht nur click) — sonst läuft der Trace ohne await und
  // die Kopfzeile wird nicht zuverlässig nachgezogen.
  if (zweig && klapp) {
    const zeile = block.querySelector(".utxo-kopf");
    if (zeile) zeile.setAttribute("aria-expanded", "true");
    zweig.hidden = false;
    klapp.textContent = "▾";
    await oeffneZweig(utxo, zweig, klapp);
    aktualisiereTraceWurzelKopf(utxo, block);
  }
  huelle.scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("#trace-start").disabled = false;
}

function traceMeldung(text, art) {
  const kasten = $("#trace-meldung");
  kasten.className = `hinweis hinweis-${art}`;
  setzeText(kasten, text);
  kasten.hidden = false;
}

/**
 * Sprung aus der Wallet-Ansicht.
 *
 * Fokus-Modus: nur dieses UTXO — keine volle Bestandsliste aller Wallets.
 */
function findeTraceUtxo(schluessel) {
  if (Zustand.traceFokus && Zustand.traceFokus.key === schluessel) {
    return {
      key: schluessel,
      value_sats: Zustand.traceFokus.value_sats ?? null,
      address: Zustand.traceFokus.address || "",
      wallet: Zustand.traceFokus.wallet || "",
      time_label: Zustand.traceFokus.time_label || "",
      hold_days: Zustand.traceFokus.hold_days,
      block_height: Zustand.traceFokus.block_height,
      verfolgt: Boolean(Zustand.traceFokus.verfolgt),
      verfolgt_vollstaendig: Boolean(Zustand.traceFokus.verfolgt_vollstaendig),
    };
  }
  const listen = [
    ...(Zustand.traceListe?.addresses || []),
    ...(Zustand.traceListe?.verlauf?.addresses || []),
  ];
  for (const gruppe of listen) {
    for (const utxo of gruppe.utxos || []) {
      if (utxo.key === schluessel) return utxo;
    }
  }
  return { key: schluessel };
}

/** Meta aus der Wallet-Ansicht, falls das UTXO dort schon gerendert ist. */
function utxoMetaAusWalletDom(schluessel) {
  const el = document.querySelector(
    `.utxo-zeile[data-key="${CSS.escape(schluessel)}"]`,
  );
  if (!el) return null;
  const sats = el.dataset.valueSats;
  return {
    key: schluessel,
    value_sats: sats != null && sats !== "" ? Number(sats) : null,
    address: el.dataset.address || "",
    wallet: walletNameZu(Zustand.walletId) || "",
    time_label: el.dataset.timeLabel || "",
    hold_days: el.dataset.holdDays ? Number(el.dataset.holdDays) : undefined,
    block_height: el.dataset.blockHeight
      ? Number(el.dataset.blockHeight)
      : undefined,
    verfolgt: el.dataset.verfolgt === "1" || el.dataset.verfolgtVollstaendig === "1",
    verfolgt_vollstaendig: el.dataset.verfolgtVollstaendig === "1",
  };
}

async function zeigeHerkunftFuer(schluessel, { neu = false, jobId = null, meta: metaExtra = null } = {}) {
  // Reihenfolge: explizite Meta (Steuerjahr-Chart) → DOM der Wallet-Liste
  // → Trace-Liste. Nie pauschal Zustand.walletId — das ist oft ein anderes
  // Wallet als das angeklickte UTXO (z. B. immer „Firmung“).
  const ausDom = utxoMetaAusWalletDom(schluessel);
  const ausListe = findeTraceUtxo(schluessel);
  const meta = {
    key: schluessel,
    ...(ausListe && ausListe.key ? ausListe : {}),
    ...(ausDom || {}),
    ...(metaExtra && typeof metaExtra === "object" ? metaExtra : {}),
    key: schluessel,
  };
  if (!meta.wallet) {
    // Letzter Versuch: Steuerjahr-Tabelle / Chart-Event ohne Fallback-WalletId.
    const ausSteuer = utxoMetaAusSteuerjahr(schluessel);
    if (ausSteuer) Object.assign(meta, ausSteuer);
  }
  Zustand.traceFokus = meta;
  zeigeAnsicht("trace");
  await zeichneTraceFokusAnsicht(Zustand.traceFokus, { neu, jobId });
}


function vorbehaltText(z) {
  const teile = [];
  if (z.external_count > 0) {
    teile.push(t("ui.hard.32106222d1", { sats: formatSats(z.external_sats) }));
  }
  if (z.unresolved_inputs > 0) {
    teile.push(
      `${z.unresolved_inputs} weitere Eingänge wurden nicht aufgelöst — ` +
      "ihre Beträge fehlen in dieser Summe. Sie ist damit eine Untergrenze, " +
      "keine Gesamtsumme."
    );
  }
  if (z.coinbase) {
    teile.push(t("ui.hard.b9ea0e8b6b"));
  }
  return teile.join(" ");
}

/** Knoten-Daten am DOM (WeakMap — überlebt Fragment-Append, kein Leak). */
const BAUM_KNOTEN_DATEN = new WeakMap();

/** Leere Labels und „eigenes Wallet“ für Vergleiche auf denselben Wert bringen. */
function normalisiereWalletLabel(wert) {
  const s = (wert == null ? "" : String(wert)).trim();
  if (!s) return "";
  const eigen = t("trace.ownWallet");
  return s === eigen ? "" : s;
}

function walletAnzeigeLabel(wert) {
  return normalisiereWalletLabel(wert) || t("trace.ownWallet");
}

/**
 * True, wenn *kind* das Wallet-Segment von *eltern* verlässt.
 *
 * Gleiche-Wallet-Hops bleiben flach; Einrückung nur bei Wallet-Wechsel
 * oder Übergang zu Extern/Coinbase/unaufgelöst.
 */
function knotenIstWalletAustritt(eltern, kind) {
  if (!eltern || eltern.type !== "internal" || !kind) return false;
  if (kind.type === "internal") {
    return (
      normalisiereWalletLabel(eltern.wallet)
      !== normalisiereWalletLabel(kind.wallet)
    );
  }
  return true;
}

function zeichneKnotenListe(knoten, elternWallet, elternKnoten) {
  const huelle = document.createDocumentFragment();
  for (const k of knoten) {
    huelle.append(zeichneKnoten(k, elternWallet, elternKnoten));
  }
  return huelle;
}

function baumKnotenEls(block) {
  if (!block) return {};
  const zeile = block.querySelector(":scope > .kopf-mit-verweis > .baum-knoten");
  const klapp = zeile && zeile.querySelector(":scope > .klapp");
  const kinder = block.querySelector(":scope > .baum-kinder");
  return { zeile, klapp, kinder };
}

function baumKinderKlasse(elternKnoten) {
  // Interne Knoten: Kinder standardmäßig flach; Austritte per .knoten-austritt.
  if (elternKnoten && elternKnoten.type === "internal") {
    return "baum-kinder flach";
  }
  return "baum-kinder";
}

/**
 * Einen Baumknoten aufklappen (Kinder ggf. lazy zeichnen).
 */
function expandiereKnotenBlock(block) {
  const knoten = BAUM_KNOTEN_DATEN.get(block);
  if (!knoten || !knoten.expandable) return false;
  let { zeile, klapp, kinder } = baumKnotenEls(block);
  if (!kinder) {
    kinder = document.createElement("div");
    kinder.className = baumKinderKlasse(knoten);
    kinder.hidden = true;
    block.append(kinder);
  }
  if (!kinder.dataset.gezeichnet) {
    kinder.dataset.gezeichnet = "ja";
    kinder.replaceChildren();
    kinder.append(zeichneKnotenListe(
      knoten.children || [],
      knoten.type === "internal" ? (knoten.wallet || "") : undefined,
      knoten,
    ));
  }
  kinder.hidden = false;
  if (klapp && !klapp.classList.contains("leer")) klapp.textContent = "▾";
  if (zeile) zeile.setAttribute("aria-expanded", "true");
  return true;
}

function klappeKnotenBlock(block) {
  if (!block) return;
  const { zeile, klapp, kinder } = baumKnotenEls(block);
  if (kinder) kinder.hidden = true;
  if (klapp && !klapp.classList.contains("leer")) klapp.textContent = "▸";
  if (zeile) zeile.setAttribute("aria-expanded", "false");
}

function toggleKnotenBlock(block) {
  const { kinder } = baumKnotenEls(block);
  if (kinder && !kinder.hidden && kinder.dataset.gezeichnet) {
    klappeKnotenBlock(block);
  } else {
    expandiereKnotenBlock(block);
  }
}

/** Gesamten Herkunftszweig unter *zweig* (.utxo-zweig) aufklappen. */
function expandiereBaumAlles(zweig) {
  if (!zweig) return;
  // Iterativ: nach jedem Zeichnen neue Blöcke, bis nichts mehr zu öffnen ist.
  let guard = 0;
  let fort = true;
  while (fort && guard++ < 800) {
    fort = false;
    const blocks = zweig.querySelectorAll(".baum-knoten-block");
    for (const block of blocks) {
      const knoten = BAUM_KNOTEN_DATEN.get(block);
      if (!knoten || !knoten.expandable) continue;
      const { kinder } = baumKnotenEls(block);
      if (!kinder || kinder.hidden || !kinder.dataset.gezeichnet) {
        if (expandiereKnotenBlock(block)) fort = true;
      }
    }
  }
}

function klappeBaumAlles(zweig) {
  if (!zweig) return;
  // Von innen nach außen zuklappen.
  const blocks = [...zweig.querySelectorAll(".baum-knoten-block")].reverse();
  for (const block of blocks) klappeKnotenBlock(block);
}

function baumKlappLeiste(zweig) {
  const leiste = document.createElement("div");
  leiste.className = "zweig-klapp-leiste";
  const auf = document.createElement("button");
  auf.type = "button";
  auf.className = "knopf knopf-klein";
  auf.textContent =
    t("trace.expandAll") !== "trace.expandAll"
      ? t("trace.expandAll")
      : "Alles aufklappen";
  auf.title =
    t("trace.expandAllTitle") !== "trace.expandAllTitle"
      ? t("trace.expandAllTitle")
      : t("ui.hard.876fa56c45");
  auf.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    expandiereBaumAlles(zweig);
  });
  const zu = document.createElement("button");
  zu.type = "button";
  zu.className = "knopf knopf-klein";
  zu.textContent =
    t("trace.collapseAll") !== "trace.collapseAll"
      ? t("trace.collapseAll")
      : "Alles zuklappen";
  zu.title =
    t("trace.collapseAllTitle") !== "trace.collapseAllTitle"
      ? t("trace.collapseAllTitle")
      : t("ui.hard.f1909de084");
  zu.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    klappeBaumAlles(zweig);
  });
  leiste.append(auf, zu);
  return leiste;
}

function zeichneKnoten(knoten, elternWallet, elternKnoten) {
  const block = document.createElement("div");
  block.className = "baum-knoten-block";
  BAUM_KNOTEN_DATEN.set(block, knoten);

  const walletUebergang =
    knoten.type === "internal"
    && elternWallet !== undefined
    && normalisiereWalletLabel(elternWallet) !== normalisiereWalletLabel(knoten.wallet);
  if (walletUebergang) block.classList.add("wallet-uebergang");
  // Visuelle Stufe nur bei Wallet-Wechsel / Extern — nicht pro Hop im selben Wallet.
  if (knotenIstWalletAustritt(elternKnoten, knoten)) {
    block.classList.add("knoten-austritt");
  }

  // Die ganze Zeile ist der Treffer — nicht das Dreieck allein.
  // Erste Ebene unter der UTXO-Wurzel zeichnet zeichneZweig sofort (sichtbar).
  // Tiefere Ebenen erst beim Aufklappen — große CoinJoin-/Remix-Bäume sonst
  // tausende DOM-Knoten und zehntausende Pixel Listenhöhe auf einmal.
  const zeile = document.createElement(knoten.expandable ? "button" : "div");
  zeile.className = "baum-knoten";
  if (knoten.expandable) {
    zeile.type = "button";
    zeile.setAttribute("aria-expanded", "false");
  }

  const klapp = document.createElement("span");
  klapp.className = knoten.expandable ? "klapp" : "klapp leer";
  klapp.textContent = knoten.expandable ? "▸" : "·";
  klapp.setAttribute("aria-hidden", "true");
  // Title nur am Pfeil — sonst überschreibt „Zweig auf-/zuklappen“ das
  // Soft-Label am Mix-Icon (native title am Button gewinnt über Kinder).
  if (knoten.expandable) klapp.title = "Zweig auf- und zuklappen";

  const punkt = document.createElement("span");
  punkt.className = `knoten-punkt ${PUNKT_KLASSE[knoten.type] || "knoten-extern"}`;

  const info = document.createElement("span");
  info.className = "knoten-info";

  const oben = document.createElement("span");
  oben.className = "knoten-oben";
  if (knoten.amount_sats > 0) {
    const betrag = document.createElement("span");
    betrag.className = "betrag";
    const atTs = Number(knoten.time_ts || 0);
    if (atTs > 0) setzeSatsBetrag(betrag, knoten.amount_sats, { atTs });
    else betrag.textContent = formatSats(knoten.amount_sats);
    oben.append(betrag);
  }
  const wer = document.createElement("span");
  if (knoten.type === "internal") {
    wer.textContent = knoten.wallet || t("trace.ownWallet");
  } else if (knoten.type === "tax_horizon") {
    wer.textContent = knoten.wallet || "Steuer-Horizont";
  } else if (knoten.type === "external_unresolved") {
    wer.textContent = t("trace.bundledInputs", { count: knoten.input_count });
  } else if (knoten.type === "coinbase") {
    wer.textContent = t("trace.coinbase");
  } else {
    wer.textContent = t("trace.external");
  }
  oben.append(wer);

  if (knoten.address) {
    const adresse = document.createElement("span");
    adresse.className = "mono zart";
    adresse.textContent = kuerze(knoten.address, 12, 6);
    macheKopierbar(adresse, knoten.address, "Adresse");
    oben.append(adresse);
  }

  // Wem die fremde Adresse zuzuordnen ist — das ist an einem externen Ende
  // die eigentliche Auskunft. Herkunftsblatt = Zufluss (Börse→Wallet → grün).
  const marke = labelMarke(knoten.label, {
    herkunft: true,
    zufluss: !knoten.abfluss,
    abfluss: Boolean(knoten.abfluss),
  });
  if (marke) oben.append(marke);

  info.append(oben);

  if (walletUebergang) {
    const hinweis = document.createElement("span");
    hinweis.className = "wallet-uebergang-hinweis";
    hinweis.textContent = t("trace.walletTransition", {
      from: walletAnzeigeLabel(elternWallet),
      to: walletAnzeigeLabel(knoten.wallet),
    });
    info.append(hinweis);
  }

  const klasseText = softTxClassLabel(knoten);
  const externKurz =
    knoten.type === "external" ? t("trace.externalInput") : "";
  const ankunftText = knoten.time_label ? formatAnkunft(knoten) : "";
  if (knoten.from_utxo || ankunftText || klasseText || externKurz) {
    const unten = document.createElement("span");
    unten.className = "knoten-unten";
    const links = document.createElement("span");
    links.className = "knoten-unten-links";
    if (knoten.from_utxo) {
      const utxoKennung = document.createElement("span");
      utxoKennung.className = "mono";
      utxoKennung.textContent = kuerze(knoten.from_utxo, 12, 8);
      macheKopierbar(utxoKennung, knoten.from_utxo, "UTXO (txid:vout)");
      links.append(utxoKennung);
    }
    if (externKurz) {
      links.append(
        document.createTextNode((knoten.from_utxo ? " · " : "") + externKurz),
      );
    }
    if (ankunftText) {
      links.append(
        document.createTextNode(
          (knoten.from_utxo || externKurz ? " · " : "") + ankunftText,
        ),
      );
    }
    unten.append(links);
    if (klasseText) {
      const rechts = document.createElement("span");
      rechts.className = "knoten-unten-rechts";
      fuelleTxClassRechts(rechts, knoten);
      unten.append(rechts);
    }
    info.append(unten);
  }

  const notizText = knotenNotiz(knoten);
  if (notizText) {
    const notiz = document.createElement("span");
    notiz.className = "knoten-notiz";
    notiz.textContent = notizText;
    info.append(notiz);
  }

  zeile.append(klapp, punkt, info);

  const kopfzeile = document.createElement("div");
  kopfzeile.className = "kopf-mit-verweis";
  kopfzeile.append(zeile);
  // Tx vor Adresse: VIN/VOUT-Grafik. Adresse nur, wenn keine Tx bekannt
  // (reine Adresszeilen bleiben bei /address/… — siehe Adressgruppen).
  const txid =
    (knoten.from_utxo || "").split(":")[0]
    || knoten.txid
    || "";
  const extern = txid
    ? mempoolVerweis("tx", txid)
    : (knoten.address ? mempoolVerweis("address", knoten.address) : null);
  if (extern) kopfzeile.append(extern);
  block.append(kopfzeile);

  if (knoten.expandable) {
    const kinder = document.createElement("div");
    kinder.className = baumKinderKlasse(knoten);
    kinder.hidden = true;
    block.append(kinder);

    zeile.addEventListener("click", (ereignis) => {
      // Nicht auf Bubbling von Copy-Klicks reagieren (die stoppen selbst).
      if (ereignis.defaultPrevented) return;
      if (ereignis.detail > 1) return;
      if (window.getSelection && window.getSelection().toString()) return;
      ereignis.preventDefault();
      ereignis.stopPropagation();
      toggleKnotenBlock(block);
    });
  }

  return block;
}


/**
 * Wallet-Knopf: jedes UTXO wie „Herkunftslücken schließen“ (gebündelte
 * Eingänge + Vorgänger-Txs) bis external/coinbase.
 * Bewusst mit Confirm — kann Stunden dauern, füllt den Herkunfts-Cache.
 */
async function starteHerkunftVollstaendig() {
  const wid = Zustand.walletId;
  if (!wid) return;
  const wallet = (Zustand.config?.wallets || []).find((w) => w.id === wid);
  if (!wallet || !wallet.has_cache) {
    meldung(t("wallet.originDeepNeedCache"), "warn");
    return;
  }
  if (herkunftTiefLaeuftFuer(wid)) {
    meldung(t("nav.jobAlreadyRunning"), "warn");
    return;
  }
  const name = wallet.name || wid;
  if (!window.confirm(t("wallet.originDeepConfirm", { name }))) return;

  Zustand.herkunftTiefWalletId = wid;
  stoesseEmpfangScanPuls();

  const knopf = $("#herkunft-tief-knopf");
  const leiste = $("#herkunft-tief-lauf");
  const textEl = $("#herkunft-tief-text");
  if (knopf) knopf.disabled = true;
  if (leiste) leiste.hidden = false;
  setzeText(textEl, t("wallet.originDeepRunning"));

  let jobId = null;
  let timer = null;
  const logStand = { index: 0 };
  let zuletztVerfolgt = -1;
  let refreshUm = 0;
  let refreshLaeuft = false;

  const fertig = async (meldungText, art) => {
    clearInterval(timer);
    Zustand.herkunftTiefWalletId = null;
    merkeScanJobBeendet(jobId);
    if (leiste) leiste.hidden = true;
    setzeWalletScanGesperrt();
    if (meldungText) meldung(meldungText, art || "gut");
    if (Zustand.ansicht === "wallet" && Zustand.walletId === wid) {
      try { await zeigeWallet(wid); } catch (_) { /* ignore */ }
    } else {
      loeseEmpfangScanPuls();
    }
    await ladeJobsNav();
  };

  logZeile(t("wallet.originDeepStarted", { name }), undefined, name);
  logZeile(
    "Browser darf geschlossen werden — Server und Scan laufen im Terminal weiter.",
    undefined,
    name,
  );
  try {
    const antwort = await api("/trace/alle", {
      methode: "POST",
      daten: { wallet_id: wid, vollstaendig: true },
    });
    if (antwort.nichts_zu_tun) {
      if (antwort.keine_utxos) {
        await fertig(t("wallet.originDeepNeedCache"), "warn");
      } else {
        await fertig(t("wallet.originDeepNothing"), "gut");
      }
      return;
    }
    jobId = antwort.id;
    nimmJobLogAb(antwort, logStand, name);
  } catch (fehler) {
    await fertig(fehler.message || String(fehler), "krit");
    return;
  }

  const abbruch = $("#herkunft-tief-abbruch");
  if (abbruch) {
    abbruch.onclick = async () => {
      setzeText(textEl, t("common.abortRequested"));
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* schon beendet */
      }
    };
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmJobLogAb(job, logStand, name);
      const zahl = job.result?.verfolgt;
      const vollOk = job.result?.vollstaendig_ok;
      let standText = übersetzeLogText(job.message || t("common.runningEllipsis"));
      if (typeof vollOk === "number" && vollOk > 0) {
        standText += t("ui.hard.4a3387f537", { n: vollOk });
      }
      setzeText(textEl, standText);

      if (job.running) {
        if (
          typeof zahl === "number"
          && zahl > zuletztVerfolgt
          && !refreshLaeuft
        ) {
          const jetzt = Date.now();
          if (zuletztVerfolgt < 0 || jetzt - refreshUm >= HERKUNFT_REFRESH_MS) {
            zuletztVerfolgt = zahl;
            refreshUm = jetzt;
            refreshLaeuft = true;
            try {
              if (Zustand.ansicht === "wallet" && Zustand.walletId === wid) {
                await zeigeWallet(wid);
              }
            } finally {
              refreshLaeuft = false;
            }
          }
        }
        return;
      }

      if (job.status === "done") {
        await fertig(
          t("wallet.originDeepDone", {
            msg: job.message || t("common.running"),
          }),
          "gut",
        );
      } else if (job.status === "cancelled") {
        await fertig(
          "Abgebrochen — bereits ermittelte Herkunft bleibt erhalten.",
          "warn",
        );
      } else {
        await fertig(job.error || t("trace.analyseFailShort"), "krit");
      }
    } catch (fehler) {
      await fertig(fehler.message, "krit");
    }
  }, 1200);
}

/**
 * Verfolgt die Herkunft aller noch offenen UTXOs.
 *
 * Steht in zwei Ansichten — im Steuerjahr, wo die Anschaffungsdaten davon
 * abhängen, und in der Herkunftsansicht, wo man ohnehin gerade damit
 * arbeitet. Eine Funktion für beide: Zwei Fassungen desselben Ablaufs gingen
 * über kurz oder lang auseinander.
 *
 * *ziele* benennt die Bedienelemente der jeweiligen Ansicht, *danach* das,
 * was nach dem Lauf neu zu laden ist.
 */
/** Während Massen-Herkunft: aktuelle Ansicht höchstens alle ~2,5 s neu laden. */
const HERKUNFT_REFRESH_MS = 2500;

async function erfrischeHerkunftZwischenstand() {
  try {
    if (Zustand.ansicht === "wallet" && Zustand.walletId) {
      await zeigeWallet(Zustand.walletId);
    } else if (Zustand.ansicht === "trace") {
      if (Zustand.traceFokus) {
        await zeichneTraceFokusAnsicht(Zustand.traceFokus);
      } else {
        await ladeTraceListe({ erzwingen: true });
      }
    } else if (Zustand.ansicht === "steuerjahr") {
      await ladeSteuerjahr();
    }
  } catch (_) {
    /* Zwischenstand ist Komfort — Fehler nicht den Lauf abbrechen */
  }
}

/** Wartet, bis ein Hintergrundjob fertig ist (done / cancelled / error). */
async function warteAufJobEnde(jobId, {
  onTick = null,
  sollAbbrechen = () => false,
  intervallMs = 900,
} = {}) {
  while (true) {
    if (sollAbbrechen()) {
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* schon weg */
      }
      const err = new Error("abgebrochen");
      err.abgebrochen = true;
      throw err;
    }
    const job = await api(`/jobs/${jobId}`);
    if (typeof onTick === "function") onTick(job);
    if (job.running) {
      await new Promise((r) => setTimeout(r, intervallMs));
      continue;
    }
    if (job.status === "done") return job;
    if (job.status === "cancelled") {
      const err = new Error("abgebrochen");
      err.abgebrochen = true;
      throw err;
    }
    throw new Error(job.error || t("common.failed"));
  }
}

/**
 * UTXO-Scan für jedes konfigurierte Wallet — Voraussetzung für
 * „Herkunft aller UTXOs“ bei leerem Cache.
 */
async function scanneAlleWalletsUtxo({
  textEl = null,
  sollAbbrechen = () => false,
  logStand = null,
} = {}) {
  const wallets = (Zustand.config?.wallets || []).filter((w) => w && w.id);
  if (!wallets.length) {
    throw new Error(t("wallets.emptyList"));
  }
  let scanAb = "";
  for (let i = 0; i < wallets.length; i += 1) {
    const wallet = wallets[i];
    if (sollAbbrechen()) {
      const err = new Error("abgebrochen");
      err.abgebrochen = true;
      throw err;
    }
    if (textEl) {
      setzeText(textEl, t("trace.allOriginsScanning", {
        aktuell: i + 1,
        gesamt: wallets.length,
        name: wallet.name || wallet.id,
      }));
    }
    logZeile(
      t("trace.allOriginsScanning", {
        aktuell: i + 1,
        gesamt: wallets.length,
        name: wallet.name || wallet.id,
      }),
      undefined,
      wallet.name,
    );

    let datum = scanAb;
    if (brauchtBip158Startdatum(wallet.id)) {
      const gewählt = await frageScanDatum(wallet);
      if (gewählt === undefined) {
        const err = new Error("abgebrochen");
        err.abgebrochen = true;
        throw err;
      }
      datum = gewählt || "";
      scanAb = datum;
    }

    const job = await api("/jobs/rescan", {
      methode: "POST",
      daten: { wallet_id: wallet.id, scan_ab: datum || "" },
    });
    const jid = job.id || job.job_id;
    if (!jid) {
      throw new Error(t("wallet.utxoScan") + " — " + t("common.failed"));
    }
    // Pipeline kann „queued“ liefern — trotzdem auf diese Job-ID warten.
    await warteAufJobEnde(jid, {
      sollAbbrechen,
      onTick: (j) => {
        if (logStand) nimmJobLogAb(j, logStand, wallet.name);
        if (textEl && j.message) {
          setzeText(
            textEl,
            t("trace.allOriginsScanning", {
              aktuell: i + 1,
              gesamt: wallets.length,
              name: wallet.name || wallet.id,
            }) + ` · ${übersetzeLogText(j.message)}`,
          );
        }
      },
    });
  }
}

async function herkunftGelbUtxos() {
  // Gelbe Scorecard (geprueft && !erfuellt): gründlich bis extern/Coinbase.
  // Steuer-Horizont allein reicht nicht — gelb ist erst „fertig“, wenn grün
  // oder der volle Baum bestätigt, dass gelb korrekt ist.
  if (Zustand.herkunftAlleLaeuft) {
    const k = $("#steuer-meldung");
    if (k) {
      k.className = "hinweis hinweis-warn";
      setzeText(k, t("tax.originAlreadyRunning") !== "tax.originAlreadyRunning"
        ? t("tax.originAlreadyRunning")
        : t("ui.hard.2c151e092b"));
      k.hidden = false;
    }
    return;
  }
  let daten = Zustand.steuer;
  if (!daten || !Array.isArray(daten.eintraege)) {
    const jahr = $("#jahr-wahl")?.value || "";
    const frist = $("#frist-wahl")?.value || "";
    const stichtag = steuerEinstellungen().stichtag || "";
    const abfrage =
      `?jahr=${encodeURIComponent(jahr)}&frist=${encodeURIComponent(frist)}` +
      `&stichtag=${encodeURIComponent(stichtag)}`;
    daten = await api(`/tax${abfrage}`);
  }
  const liste = daten.eintraege || [];
  const keys = liste
    .filter((e) => e.geprueft && !e.erfuellt)
    .map((e) => `${e.txid}:${e.vout}`);
  if (!keys.length) {
    const k = $("#steuer-meldung");
    k.className = "hinweis hinweis-warn";
    setzeText(k, t("tax.noYellowToClarify") !== "tax.noYellowToClarify"
      ? t("tax.noYellowToClarify")
      : t("ui.hard.d3b790167b"));
    k.hidden = false;
    return;
  }
  herkunftAllerUtxos({
    knopf: "#herkunft-gelb",
    lauf: "#herkunft-lauf",
    text: "#herkunft-text",
    abbruch: "#herkunft-abbruch",
    meldung: "#steuer-meldung",
    danach: ladeSteuerjahrMitKandidaten,
    utxo_keys: keys,
    // voll bis extern/Coinbase — nicht nur Steuer-Horizont
    steuer: false,
    gelbVertiefen: true,
  });
}

async function herkunftAllerUtxos(ziele = {
  knopf: "#herkunft-alle",
  lauf: "#herkunft-lauf",
  text: "#herkunft-text",
  abbruch: "#herkunft-abbruch",
  meldung: "#steuer-meldung",
  danach: ladeSteuerjahrMitKandidaten,
  utxo_keys: null,
  steuer: false,
  gelbVertiefen: false,
}) {
  // Selector-String oder bereits aufgelöstes Element (Zeilen-„klären“).
  const knopf = typeof ziele.knopf === "string"
    ? $(ziele.knopf)
    : ziele.knopf;
  if (Zustand.herkunftAlleLaeuft) {
    const kasten = $(ziele.meldung);
    if (kasten) {
      kasten.className = "hinweis hinweis-warn";
      setzeText(
        kasten,
        t("tax.originAlreadyRunning") !== "tax.originAlreadyRunning"
          ? t("tax.originAlreadyRunning")
          : t("ui.hard.2c151e092b"),
      );
      kasten.hidden = false;
    }
    return;
  }
  Zustand.herkunftAlleLaeuft = true;
  stoesseEmpfangScanPuls();
  if (knopf) knopf.disabled = true;
  $(ziele.lauf).hidden = false;
  setzeText($(ziele.text), "Wird vorbereitet…");

  let jobId = null;
  let timer = null;
  const logStand = { index: 0 };
  let zuletztVerfolgt = -1;
  let refreshUm = 0;
  let refreshLaeuft = false;
  let abbruchWunsch = false;

  const fertig = (meldung, art) => {
    clearInterval(timer);
    Zustand.herkunftAlleLaeuft = false;
    merkeScanJobBeendet(jobId);
    if (knopf) knopf.disabled = false;
    $(ziele.lauf).hidden = true;
    if (meldung) {
      const kasten = $(ziele.meldung);
      kasten.className = `hinweis hinweis-${art}`;
      setzeText(kasten, meldung);
      kasten.hidden = false;
    }
    Promise.resolve()
      .then(() => (typeof ziele.danach === "function" ? ziele.danach() : null))
      .catch(() => {})
      .then(() => loeseEmpfangScanPuls());
  };

  $(ziele.abbruch).onclick = async () => {
    abbruchWunsch = true;
    setzeText($(ziele.text), "Abbruch angefordert…");
    if (jobId) {
      try {
        await api(`/jobs/${jobId}`, { methode: "DELETE" });
      } catch (_) {
        /* schon beendet */
      }
    }
  };

  // Grau / initial: Steuer-Horizont reicht für erste Einstufung.
  // Gelb vertiefen: voll bis extern/Coinbase (gelb erst „fertig“ wenn grün
  // oder voll bestätigt).
  const gelbVoll = Boolean(ziele.gelbVertiefen) || ziele.knopf === "#herkunft-gelb";
  const steuerModus = !gelbVoll && (
    Boolean(ziele.steuer)
    || ziele.knopf === "#herkunft-alle"
    || ziele.knopf === "#herkunft-grau"
  );
  logZeile(
    gelbVoll
      ? t("ui.hard.499f733cb2")
      : steuerModus
        ? t("ui.hard.6508c40d20")
        : t("ui.hard.0a8622a114"),
  );
  try {
    const traceDaten = steuerModus
      ? {
          modus: "steuer",
          jahr: Number($("#jahr-wahl")?.value) || new Date().getFullYear(),
          haltefrist_jahre: Number($("#frist-wahl")?.value)
            || Number(steuerEinstellungen().haltefrist_jahre)
            || 1,
          stichtag: steuerEinstellungen().stichtag_iso
            || steuerEinstellungen().stichtag
            || "",
          utxo_keys: ziele.utxo_keys || null,
        }
      : {
          modus: "voll",
          utxo_keys: ziele.utxo_keys || null,
        };
    let antwort = await api("/trace/alle", {
      methode: "POST",
      daten: traceDaten,
    });
    if (antwort.nichts_zu_tun && antwort.keine_utxos) {
      // Bestand fehlt: nach Bestätigung erst alle Wallets scannen, dann Trace.
      if (knopf) knopf.disabled = false;
      $(ziele.lauf).hidden = true;
      if (!window.confirm(t("trace.allOriginsNeedUtxoConfirm"))) {
        fertig(t("trace.allOriginsScanAbort"), "warn");
        return;
      }
      if (knopf) knopf.disabled = true;
      $(ziele.lauf).hidden = false;
      abbruchWunsch = false;
      await scanneAlleWalletsUtxo({
        textEl: $(ziele.text),
        sollAbbrechen: () => abbruchWunsch,
        logStand,
      });
      if (abbruchWunsch) {
        fertig(t("trace.allOriginsScanAbort"), "warn");
        return;
      }
      setzeText($(ziele.text), t("trace.allOriginsScanDone"));
      await ladeConfig();
      antwort = await api("/trace/alle", {
        methode: "POST",
        daten: traceDaten,
      });
    }
    if (antwort.nichts_zu_tun) {
      if (antwort.keine_utxos) {
        fertig(t("trace.allOriginsNeedUtxo"), "warn");
      } else if (gelbVoll) {
        fertig(
          t("tax.yellowAlreadyDone") !== "tax.yellowAlreadyDone"
            ? t("tax.yellowAlreadyDone")
            : t("ui.hard.4dc80efd8d"),
          "gut",
        );
      } else {
        fertig(t("trace.allOriginsNothing"), "gut");
      }
      return;
    }
    jobId = antwort.id;
    nimmJobLogAb(antwort, logStand);
  } catch (fehler) {
    if (fehler && fehler.abgebrochen) {
      fertig(t("trace.allOriginsScanAbort"), "warn");
      return;
    }
    fertig(`Analyse fehlgeschlagen: ${fehler.message}`, "krit");
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      nimmJobLogAb(job, logStand);
      const zahl = job.result?.verfolgt;
      const juengste = job.result?.juengste_sats;
      let standText = übersetzeLogText(job.message || t("common.runningEllipsis"));
      if (typeof juengste === "number" && juengste > 0) {
        standText += t("ui.hard.7cdb0db2f7", { n: juengste });
      }
      setzeText($(ziele.text), standText);

      if (job.running) {
        if (
          typeof zahl === "number"
          && zahl > zuletztVerfolgt
          && !refreshLaeuft
        ) {
          const jetzt = Date.now();
          if (zuletztVerfolgt < 0 || jetzt - refreshUm >= HERKUNFT_REFRESH_MS) {
            zuletztVerfolgt = zahl;
            refreshUm = jetzt;
            refreshLaeuft = true;
            try {
              await erfrischeHerkunftZwischenstand();
            } finally {
              refreshLaeuft = false;
            }
          }
        }
        return;
      }

      if (job.status === "done") {
        fertig(job.message || "Herkunft ermittelt.", "gut");
      } else if (job.status === "cancelled") {
        fertig("Abgebrochen — bereits ermittelte Herkunft bleibt erhalten.",
               "warn");
      } else {
        fertig(job.error || "Analyse fehlgeschlagen.", "krit");
      }
    } catch (fehler) {
      fertig(fehler.message, "krit");
    }
  }, 1200);
}
