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
async function ladeTraceListe({ erzwingen = false, still = false } = {}) {
  if (Zustand.traceFokus && !erzwingen) {
    await zeichneTraceFokusAnsicht(Zustand.traceFokus);
    return;
  }
  Zustand.traceFokus = null;
  setzeTraceFokusUi(false);
  const liste = $("#trace-liste");
  // /api/utxos ist Cache — Quellen-Hinweis gehört nur in die Scan-Leiste.
  // still: Filter/Sortierung — alte Seite stehen lassen, bis die neue da ist.
  if (!still) liste.replaceChildren(hinweisZeile(t("common.loadingFromCache")));

  try {
    // Seitenweise (ISSUES P2): nur die gezeigte Seite kommt angereichert.
    const quelle = traceSeitenQuelle("bestand");
    Zustand.traceQuelle = quelle;
    const seite = await quelle.seite(0);
    if (Zustand.traceQuelle !== quelle) return;
    zeichneTraceListe(seite.antwort, seite);
  } catch (fehler) {
    liste.replaceChildren(hinweisZeile(t("common.couldNotLoad", { msg: fehler.message })));
  }
}

/** Filter oder Seitengröße geändert: Liste neu vom Server (Seite 1). */
function ladeTraceSeitenNeu() {
  if (Zustand.ansicht !== "trace" || Zustand.traceFokus) return;
  ladeTraceListe({ still: true });
}

/**
 * Anfrage-Parameter der Herkunftsliste: Sortiermodus, Seite, Kopf-Filter.
 * mempool=0: Herkunftsliste braucht keinen Electrs-Rundlauf über alle Wallets.
 */
function traceListenParameter(teil, offset, limit, filter = "") {
  const p = new URLSearchParams(filter);
  p.set("mempool", "0");
  p.set("seite", "1");
  p.set("teil", teil);
  p.set("modus", Zustand.traceSort || "volume-desc");
  p.set("offset", String(offset));
  p.set("limit", String(limit));
  p.set("lang", uiSprache());
  return p.toString();
}

/** Seitenquelle für Bestand bzw. „Bereits ausgegeben“ (``teil``). */
function traceSeitenQuelle(teil) {
  // Filter beim Anlegen festhalten — Vorladen gehört zu genau diesem Filter.
  const filter = kopfFilterParameter().toString();
  const quelle = neueSeitenQuelle({
    groesse: pagerGroesse(teil === "verlauf" ? "ausgegeben" : "trace"),
    laden: (o, l) => api(`/utxos?${traceListenParameter(teil, o, l, filter)}`),
    auszug: teil === "verlauf" ? verlaufSeitenAuszug : bestandSeitenAuszug,
  });
  quelle.q = filter;
  return quelle;
}

function bestandSeitenAuszug(antwort) {
  const f = (antwort && antwort.fenster) || {};
  return {
    art: f.art || "gruppen",
    items: (f.art === "utxos" ? antwort.utxos : antwort.addresses) || [],
    total: Number(f.total) || 0,
  };
}

function verlaufSeitenAuszug(antwort) {
  return bestandSeitenAuszug((antwort && antwort.verlauf) || {});
}

/** Seiteneinträge zeichnen: Adressgruppen (Volumen) oder flache UTXOs (Alter). */
function fuelleTraceSeite(behaelter, seite) {
  if (seite.art === "utxos") {
    for (const utxo of seite.items) {
      const block = zeichneTraceWurzel(utxo);
      if (utxo.address) block.dataset.address = utxo.address;
      behaelter.append(block);
    }
    return;
  }
  for (const gruppe of seite.items) {
    behaelter.append(zeichneTraceAdressGruppe(gruppe));
  }
}

/** Gruppen der Seite für findeTraceUtxo/gruppeAusTraceListe. */
function seitenGruppen(seite) {
  if (seite.art !== "utxos") return seite.items;
  return seite.items.map((u) => ({ address: u.address, utxos: [u] }));
}

/** Bestand: andere Seite zeigen, „Bereits ausgegeben“ bleibt stehen. */
async function zeigeTraceSeite(offset) {
  const quelle = Zustand.traceQuelle;
  if (!quelle) return;
  const seite = await quelle.seite(offset);
  if (Zustand.traceQuelle !== quelle) return;
  const liste = $("#trace-liste");
  for (const el of liste.querySelectorAll(
    ":scope > .adress-gruppe, :scope > .utxo-wurzel, :scope > .pager",
  )) {
    el.remove();
  }
  const teil = document.createDocumentFragment();
  fuelleTraceSeite(teil, seite);
  teil.append(traceBestandPager(seite));
  liste.insertBefore(teil, liste.querySelector(":scope > .ausgegeben-block"));
  if (Zustand.traceListe) Zustand.traceListe.addresses = seitenGruppen(seite);
  wendeKopfFilterAn();
}

function traceBestandPager(seite) {
  return zeichnePager({
    total: seite.total,
    offset: seite.offset,
    groesse: Zustand.traceQuelle ? Zustand.traceQuelle.groesse : pagerGroesse("trace"),
    ansicht: "trace",
    onSeite: (o) => zeigeTraceSeite(o).catch(() => {}),
    onGroesse: () => ladeTraceSeitenNeu(),
  });
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
  block.classList.add("herkunft-offen");
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
  if (zweig.dataset.geladen === "ja") aktualisiereLotDonut(block, zweig);
  huelle.scrollIntoView({ behavior: "smooth", block: "nearest" });
  aktualisiereKopfFilterFuerAnsicht();
  wendeKopfFilterAn();
  const auftrag = Zustand.traceVervollstaendigen;
  if (auftrag && auftrag.key === schluessel) {
    Zustand.traceVervollstaendigen = null;
    starteZweigTrace(utxo, zweig, klapp, auftrag.buendel ? "full" : null, null, {
      force: !auftrag.buendel,
    });
  }
  const sprung = Zustand.traceSprung;
  if (sprung && sprung.fokus === schluessel && typeof springeImHerkunftsbaum === "function") {
    Zustand.traceSprung = null;
    await springeImHerkunftsbaum(zweig, sprung);
  }
}

/**
 * Grauer Punkt im Dotplot: „Herkunft tracen“ öffnen und dieses UTXO
 * sofort aufklappen — nicht die zugeklappte Zeile in der Gesamtliste.
 */
async function springeZuTraceUtxo(key, meta = null) {
  if (!key || typeof zeigeHerkunftFuer !== "function") return false;
  const ausSteuer = typeof utxoMetaAusSteuerjahr === "function"
    ? utxoMetaAusSteuerjahr(key)
    : null;
  await zeigeHerkunftFuer(key, { meta: { ...(ausSteuer || {}), ...(meta || {}), key } });
  return true;
}

/**
 * Im schon geöffneten Baum des Fokus die Zeile zum Netz-Punkt zeigen.
 * *sprung*: ``{ key, typ, eltern }``. Bündel landet bei den Kindern des Eltern-Hops.
 */
async function springeImHerkunftsbaum(zweig, sprung) {
  if (!zweig || !sprung) return false;
  const ziel = sprung.typ === "buendel" ? String(sprung.eltern || "") : String(sprung.key || "");
  if (!ziel) return false;
  const fokus = zweig.closest(".utxo-wurzel");
  const baumZiel = zweig.dataset.baumZiel || (fokus && fokus.dataset.key) || "";
  let pfad = "";
  if (baumZiel) {
    try {
      const antwort = await api(
        `/trace/pfad?target=${encodeURIComponent(baumZiel)}&key=${encodeURIComponent(ziel)}`,
      );
      if (antwort && antwort.vorhanden && antwort.pfad != null) pfad = String(antwort.pfad);
    } catch (_) {
      pfad = "";
    }
  }
  const vorab = typeof Herkunftsnetz !== "undefined" && Herkunftsnetz.baum;
  const baumSchonDa = Boolean(
    vorab && vorab.key === baumZiel && vorab.stand === "da" && vorab.wert,
  );
  if (!baumSchonDa && pfad && baumZiel && zweig.dataset.baumZiel) {
    try {
      await expandiereBaumAlles(zweig);
    } catch (_) { /* Suche läuft danach über die gezeichneten Zeilen. */ }
  }
  if (baumSchonDa && zweig.dataset.baumZiel) {
    const ebene = zweig.querySelector(":scope > .baum-ebene");
    if (ebene && Array.isArray(vorab.wert.children)) {
      delete zweig.dataset.baumZiel;
      ebene.replaceChildren(zeichneKnotenListe(vorab.wert.children, ebene._elternWallet));
    }
  }
  if (pfad && !zweig.dataset.baumZiel) {
    const teile = pfad.split(".").filter(Boolean);
    let behaelter = zweig.querySelector(":scope > .baum-ebene") || zweig;
    for (let i = 0; i < teile.length; i += 1) {
      const bis = teile.slice(0, i + 1).join(".");
      let block = behaelter.querySelector(
        `:scope > .baum-knoten-block[data-pfad="${CSS.escape(bis)}"]`,
      );
      if (!block && baumZiel) {
        const elternPfad = teile.slice(0, i).join(".");
        const eltern = behaelter.closest(".baum-knoten-block");
        const elternKnoten = eltern ? BAUM_KNOTEN_DATEN.get(eltern) : null;
        const index = Number(teile[i]);
        const groesse = Math.max(1, pagerGroesse("baum"));
        await zeichneBaumSeiten(behaelter, baumZiel, elternPfad, {
          elternWallet: behaelter._elternWallet,
          elternKnoten,
          offset: Math.floor(index / groesse) * groesse,
          limit: Math.max(groesse, (index % groesse) + 1),
        });
        block = behaelter.querySelector(
          `:scope > .baum-knoten-block[data-pfad="${CSS.escape(bis)}"]`,
        );
      }
      if (!block) break;
      if (i < teile.length - 1 || sprung.typ === "buendel") {
        expandiereKnotenBlock(block);
        const { kinder } = baumKnotenEls(block);
        if (kinder) behaelter = kinder;
      }
      if (i === teile.length - 1 && sprung.typ !== "buendel") {
        return markiereBaumZeile(block);
      }
      if (i === teile.length - 1 && sprung.typ === "buendel") {
        const { kinder } = baumKnotenEls(block);
        return markiereBaumZeile(kinder || block);
      }
    }
  }
  const zeile = [...zweig.querySelectorAll(".baum-knoten-block")].find((block) => {
    const knoten = BAUM_KNOTEN_DATEN.get(block);
    if (!knoten) return false;
    if (String(knoten.from_utxo || "") !== ziel) return false;
    if (sprung.typ === "coinbase") return knoten.type === "coinbase";
    if (sprung.typ === "horizont") return Boolean(knoten.tax_horizon) || knoten.type === "tax_horizon";
    if (sprung.typ === "fremd") return knoten.type === "external";
    if (sprung.typ === "luecke") return knoten.type !== "internal" && knoten.type !== "external";
    return true;
  });
  return markiereBaumZeile(zeile);
}

function markiereBaumZeile(el) {
  if (!el) return false;
  document.querySelectorAll(".herkunft-sprung").forEach((alt) => {
    alt.classList.remove("herkunft-sprung");
  });
  el.classList.add("herkunft-sprung");
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => el.classList.remove("herkunft-sprung"), 2400);
  return true;
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

function zeichneTraceListe(daten, seite) {
  const liste = $("#trace-liste");
  const warOffen = Boolean(
    liste.querySelector(":scope > .ausgegeben-block .ausgegeben-inhalt:not([hidden])"),
  );
  liste.replaceChildren();

  // Fiat nur bei einheitlichem Datum aller UTXOs — die kennt nur eine Seite,
  // die alles enthält.
  const traceUtxos = [];
  if (seite.items.length >= seite.total) {
    for (const g of seitenGruppen(seite)) {
      for (const u of g.utxos || []) traceUtxos.push(u);
    }
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
        // Sortierung wechselt die Seitenfolge: vom Server neu (Seite 1).
        ladeTraceSeitenNeu();
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
      ladeTraceSeitenNeu();
    });
    wrap.appendChild(neu);
    const kopf = document.querySelector("#ansicht-trace .karte-kopf");
    if (kopf) kopf.appendChild(wrap);
  }

  // Seite merken (Filter, findeTraceUtxo); Verlauf kommt beim Aufklappen.
  Zustand.traceLastData = daten;
  Zustand.traceListe = { ...daten, addresses: seitenGruppen(seite) };

  if (daten.total_count === 0 && !daten.hat_verlauf) {
    liste.append(hinweisZeile(
      "Keine UTXOs im Cache. Wallets zuerst scannen — in der Wallet-Ansicht " +
      "über „Bestand“."
    ));
    aktualisiereKopfFilterFuerAnsicht();
    return;
  }

  fuelleTraceSeite(liste, seite);
  liste.append(traceBestandPager(seite));

  liste.append(zeichneAusgegeben(daten, {
    quelle: () => traceSeitenQuelle("verlauf"),
    offen: warOffen,
    merke: (s) => {
      if (Zustand.traceListe) {
        Zustand.traceListe.verlauf = {
          ...(Zustand.traceListe.verlauf || {}),
          addresses: seitenGruppen(s),
        };
      }
    },
  }));
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
 * schnell hunderte Vorgänge sind; öffnet man ihn, verhalten sich Gruppen und
 * Bäume darin wie beim aktuellen Bestand.
 */
function zeichneAusgegeben(daten, seitenweise = null) {
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
    (!seitenweise && verlauf.shown_count < verlauf.total_count
      ? ` · ${t("wallet.spentShown", { n: verlauf.shown_count })}`
      : "");

  kopf.append(klapp, titel, zusatz);

  const inhalt = document.createElement("div");
  inhalt.className = "ausgegeben-inhalt";
  inhalt.hidden = true;

  // Seitenweise: erst beim Aufklappen die erste Seite vom Server holen.
  let quelle = null;
  const zeigeSeite = async (offset) => {
    if (!quelle) quelle = seitenweise.quelle();
    const q = quelle;
    const seite = await q.seite(offset);
    if (q !== quelle) return;
    inhalt.replaceChildren();
    fuelleTraceSeite(inhalt, seite);
    inhalt.append(zeichnePager({
      total: seite.total,
      offset: seite.offset,
      groesse: q.groesse,
      ansicht: "ausgegeben",
      onSeite: (o) => zeigeSeite(o).catch(() => {}),
      onGroesse: () => {
        quelle = null;
        zeigeSeite(0).catch(() => {});
      },
    }));
    if (typeof seitenweise.merke === "function") seitenweise.merke(seite);
    if (kopfFilterAnsichtAktiv(Zustand.ansicht)) wendeKopfFilterAn();
  };
  const oeffne = () => {
    setzeKlapp(kopf, klapp, inhalt, true);
    if (inhalt.dataset.gezeichnet) return;
    inhalt.dataset.gezeichnet = "ja";
    inhalt.replaceChildren(hinweisZeile(t("common.loadingFromCache")));
    Promise.resolve(ladeKursSerie())
      .finally(() => zeigeSeite(0).catch((fehler) => {
        inhalt.replaceChildren(hinweisZeile(
          t("common.couldNotLoad", { msg: fehler.message }),
        ));
      }));
  };
  if (seitenweise) {
    // Für den Kopf-Filter: Treffer sollen sichtbar werden.
    block.oeffneAusgegeben = oeffne;
  }

  kopf.addEventListener("click", () => {
    const auf = inhalt.hidden;
    if (seitenweise) {
      if (auf) oeffne();
      else setzeKlapp(kopf, klapp, inhalt, false);
      return;
    }
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
  if (seitenweise && seitenweise.offen) oeffne();
  return block;
}

/**
 * Eine Adresse mit ihren UTXOs.
 *
 * Die Gruppe ist die oberste Ebene und startet zu. Die UTXOs darin bleiben
 * zu, auch mit gespeichertem Baum — geladen wird erst auf Klick.
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

  const ring = typeof zeichneAdressLotDonut === "function"
    ? zeichneAdressLotDonut(gruppe)
    : null;
  kopf.append(klapp);
  if (ring) kopf.append(ring);
  kopf.append(adresse, wallet, anzahl);
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
  if (ring) ring.hidden = false;

  kopf.addEventListener("click", () => {
    const auf = inhalt.hidden;
    if (auf && !utxosGebaut) {
      for (const utxo of gruppe.utxos || []) {
        inhalt.append(zeichneTraceWurzel(utxo));
      }
      utxosGebaut = true;
    }
    setzeKlapp(kopf, klapp, inhalt, auf);
    // Zugeklappt zeigt der Ring die Mischung. Aufgeklappt hat jedes UTXO
    // seinen eigenen Ring, der im Kopf wäre doppelt.
    if (ring) ring.hidden = !inhalt.hidden;
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
  block.klappeAuf = () => {
    if (inhalt.hidden) kopf.click();
  };
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
    else {
      const klaeren = alterKlaerenKnopf(utxo);
      if (klaeren) oben.append(klaeren);
    }
  } else {
    const klaeren = alterKlaerenKnopf(utxo);
    if (klaeren) oben.append(klaeren);
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
  if (typeof blendeAlterKlaerenUndScan === "function") {
    blendeAlterKlaerenUndScan(kopfzeile);
  } else if (typeof blendeScanNeuNebenVervollstaendigen === "function") {
    blendeScanNeuNebenVervollstaendigen(kopfzeile);
  }
  const extern = mempoolVerweis("tx", (utxo.key || "").split(":")[0]);
  if (extern) kopfzeile.append(extern);

  block.append(kopfzeile, zweig);

  // Startet zu — auch mit gespeichertem Baum. Geladen wird er erst beim
  // Klick auf genau dieses UTXO (höchstens ein Baum im Speicher).
  // Der Lot-Ring hängt nicht am Aufklappen: verfolgte UTXOs holen nur
  // die Mischung, der Zweig bleibt leer.
  setzeKlapp(zeile, klapp, zweig, false);
  if (utxo.verfolgt && utxo.key) ladeLotDonutZugeklappt(block, zweig, utxo.key);

  zeile.addEventListener("click", (ereignis) => {
    // Der zweite Klick eines Doppelklicks würde sonst gleich wieder
    // zuklappen. So wirkt ein Doppelklick wie ein einfacher.
    if (ereignis.detail > 1) return;
    // Wer eine TxID mit der Maus markiert, will nicht aufklappen.
    if (window.getSelection().toString()) return;

    const auf = zweig.hidden;
    setzeKlapp(zeile, klapp, zweig, auf);
    if (auf) {
      block.classList.add("herkunft-offen");
      if (zweig.dataset.geladen === "ja") aktualisiereLotDonut(block, zweig);
    } else {
      block.classList.remove("herkunft-offen");
    }
    if (!auf) return; // nur zuklappen
    // Schon geladen: nur aufklappen, kein erneuter Cache-/Analyse-Lauf.
    if (zweig.dataset.geladen === "ja" || zweig.dataset.geladen === "laeuft") {
      return;
    }
    oeffneZweig(utxo, zweig, klapp);
  });

  // Sprung aus dem Herkunftsnetz: aufklappen und den gespeicherten Baum
  // zeichnen, ohne den Klick-Handler der Zeile zu duplizieren.
  block.oeffneHerkunft = () => {
    if (zweig.hidden) zeile.click();
    else if (zweig.dataset.geladen !== "ja" && zweig.dataset.geladen !== "laeuft") {
      oeffneZweig(utxo, zweig, klapp);
    }
    return zweig;
  };

  return block;
}

/**
 * Liest nur den gespeicherten Baum. Kein Node, kein Job.
 * *ausJob*: Meta eines fertigen Trace-Jobs (``baum_im_cache``) — der Server
 * hält den Baum nicht im Job; ``source`` kommt von dort für die Fußzeile.
 */
async function ladeGespeichertenZweig(utxo, zweig, klapp, ausJob = null) {
  if (!utxo || !utxo.key || !zweig) return false;
  zweig.dataset.geladen = "laeuft";
  delete zweig._lotKinder;
  // Ring der zugeklappten Zeile stehen lassen, bis der neue Baum ihn ersetzt.
  zweig.replaceChildren(hinweisZeile(t("common.looking")));
  try {
    const ziel = (ausJob && ausJob.target) || utxo.key;
    // Seitenweise (ISSUES P2): Wurzel + erste Kinderseite, tiefer beim Aufklappen.
    const gespeichert = await api(
      `/trace?target=${encodeURIComponent(ziel)}&seite=1&limit=${2 * pagerGroesse("baum")}`,
    );
    if (gespeichert && gespeichert.vorhanden && gespeichert.ergebnis) {
      if (ausJob && ausJob.source) gespeichert.ergebnis.source = ausJob.source;
      if (gespeichert.ergebnis.seitenweise) gespeichert.ergebnis._ziel = ziel;
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
  if (utxo && utxo.key && Zustand.traceJobs) {
    Zustand.traceJobs.set(utxo.key, Zustand.traceJobs.get(utxo.key) || "wartet");
  }
  if (typeof stoesseEmpfangScanPuls === "function") stoesseEmpfangScanPuls();
  delete zweig._lotKinder;
  if (force) entferneLotDonut(wurzelLotPunkt(zweig.closest(".utxo-wurzel")));

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
    if (gemerkt === jobId || gemerkt === "wartet") Zustand.traceJobs.delete(utxo.key);
    if (typeof loeseEmpfangScanPuls === "function") loeseEmpfangScanPuls();
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
        } else if (bestehend.status === "done" && bestehend.result?.baum_im_cache) {
          aufraeumen();
          if (!await ladeGespeichertenZweig(utxo, zweig, klapp, bestehend.result)) {
            fehlschlag(t("trace.analyseFailShort"));
          }
          return;
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
    if (job.status === "done" && job.result?.baum_im_cache) {
      // Fertig und gespeichert: Baum einzeln aus dem Cache holen.
      delete zweig.dataset.teilbaum;
      ladeGespeichertenZweig(utxo, zweig, klapp, job.result).then((ok) => {
        if (!ok) fehlschlag(t("trace.analyseFailShort"));
      });
    } else if (job.status === "done" && job.result) {
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

/**
 * Rote Marke „unvollständig“: gebündelte Eingänge auspacken, sonst den
 * vorhandenen Baum fortsetzen. Bestätigt wird nicht noch einmal — der Knopf
 * sitzt direkt an der Marke.
 */
function starteHerkunftVervollstaendigen(utxo, { buendel = false } = {}) {
  if (!utxo || !utxo.key) return;
  const wurzel = document.querySelector(
    `.utxo-wurzel[data-key="${CSS.escape(utxo.key)}"]`,
  );
  const zweig = wurzel && wurzel.querySelector(".utxo-zweig");
  const klapp = wurzel && wurzel.querySelector(".klapp");
  if (zweig && klapp && typeof starteZweigTrace === "function") {
    if (wurzel) wurzel.classList.add("herkunft-offen");
    setzeKlapp(wurzel.querySelector(".utxo-kopf") || wurzel, klapp, zweig, true);
    starteZweigTrace(utxo, zweig, klapp, buendel ? "full" : null, null, {
      force: !buendel,
    });
    return;
  }
  if (typeof Zustand !== "undefined") {
    Zustand.traceVervollstaendigen = { key: utxo.key, buendel: Boolean(buendel) };
  }
  if (typeof zeigeHerkunftFuer === "function") zeigeHerkunftFuer(utxo.key);
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

/**
 * Der Zweig mit dem gerade geladenen Baum. Höchstens einer: Wer einen
 * neuen Baum zeichnet, gibt den vorigen frei (DOM + Knoten-Daten).
 */
let _offenerBaumZweig = null;

function gebeAnderenBaumFrei(zweig) {
  const alt = _offenerBaumZweig;
  _offenerBaumZweig = zweig;
  if (!alt || alt === zweig) return;
  // Dort läuft gerade eine Analyse/ein Laden — Spinner und Job stehen lassen.
  if (alt.dataset.geladen === "laeuft") return;
  alt.replaceChildren();
  alt.dataset.geladen = "";
  delete alt._lotKinder;
  delete alt.dataset.teilbaum;
  delete alt.dataset.baumZiel;
  const wurzelAlt = alt.closest(".utxo-wurzel");
  const kopf = wurzelAlt?.querySelector(".utxo-kopf");
  if (wurzelAlt) wurzelAlt.classList.remove("herkunft-offen");
  // Der Ring der zugeklappten Zeile bleibt. Nur der offene Baum geht weg.
  setzeKlapp(kopf, kopf && kopf.querySelector(".klapp"), alt, false);
}

function zeichneZweig(ergebnis, zweig, utxo = null, klapp = null) {
  gebeAnderenBaumFrei(zweig);
  zweig.replaceChildren();
  delete zweig._lotKinder;
  const wurzelVorab = zweig.closest(".utxo-wurzel");

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

  const kinderAnzahl = ergebnis.seitenweise
    ? Number(ergebnis.children_total) || 0
    : ergebnis.children.length;
  if (kinderAnzahl === 0) {
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
    aktualisiereLotDonut(
      zweig.closest(".utxo-wurzel"), zweig, ergebnis.children, lotZeitTs(ergebnis.root),
    );
    return;
  }

  const wurzelWallet = utxo ? (utxo.wallet || "") : undefined;
  if (ergebnis.seitenweise && ergebnis._ziel) {
    zweig.dataset.baumZiel = ergebnis._ziel;
    const ebene = document.createElement("div");
    ebene.className = "baum-ebene";
    ebene._elternWallet = wurzelWallet;
    zweig.append(ebene);
    zeichneBaumSeiten(ebene, ergebnis._ziel, "", {
      elternWallet: wurzelWallet,
      vorab: { items: ergebnis.children, total: kinderAnzahl },
    });
  } else {
    delete zweig.dataset.baumZiel;
    zweig.append(zeichneKnotenListe(ergebnis.children, wurzelWallet));
  }
  zeichneFolgeBand(ergebnis, zweig, utxo, klapp);

  const vorbehalt = vorbehaltText(ergebnis.summary);
  const fuss = document.createElement("div");
  fuss.className = "vorbehalt";
  fuss.style.paddingTop = "6px";
  const quelle = ergebnis.source ? `Quelle: ${ergebnis.source}. ` : "";
  fuss.textContent = quelle + vorbehalt;
  zweig.append(fuss);
  aktualisiereLotDonut(
    zweig.closest(".utxo-wurzel"), zweig, ergebnis.children, lotZeitTs(ergebnis.root),
  );
}

/**
 * Haltefrist-Lose der Blatt-Knoten, wertgewichtet.
 *
 * Interne Hops sind kein Lot — ihr Gewicht geht an die Kinder.
 * Liefert ``{gruen, orange, grau}`` oder ``null``, wenn nichts zu mischen ist.
 */
function lotBetrag(knoten) {
  return Math.max(0, Number(knoten && knoten.amount_sats) || 0);
}

/** Betrag des Teilbaums: Blätter ihr amount_sats, interne Hops die Summe der Kinder. */
function lotTeilbaumBetrag(knoten, gesehen) {
  if (!knoten || typeof knoten !== "object" || gesehen.has(knoten)) return 0;
  gesehen.add(knoten);
  if (knoten.type !== "internal") return lotBetrag(knoten);
  const eigene = Array.isArray(knoten.children) ? knoten.children : [];
  const summe = eigene.reduce((s, k) => s + lotTeilbaumBetrag(k, gesehen), 0);
  return summe > 0 ? summe : lotBetrag(knoten);
}

/** Blockzeit des Knotens, sonst das Datum im time_label. 0 = keine Zeit. */
function lotZeitTs(knoten) {
  if (!knoten || typeof knoten !== "object") return 0;
  const ts = Number(knoten.time_ts || knoten.block_time);
  if (Number.isFinite(ts) && ts > 0) return ts;
  const m = String(knoten.time_label || "").match(
    /(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?/,
  );
  if (!m) return 0;
  const zeit = new Date(
    Number(m[3]), Number(m[2]) - 1, Number(m[1]),
    Number(m[4] || 0), Number(m[5] || 0), Number(m[6] || 0),
  );
  const unix = Math.floor(zeit.getTime() / 1000);
  return Number.isFinite(unix) && unix > 0 ? unix : 0;
}

/** Engste Obergrenze: eigene Zeit des Hops, sonst die der Vorfahren. */
function lotObergrenze(bisher, knoten) {
  const ts = lotZeitTs(knoten);
  const alt = Number(bisher) || 0;
  if (!(ts > 0)) return alt;
  if (!(alt > 0)) return ts;
  return Math.min(alt, ts);
}

/** Mehrere Mischungen, gewichtet mit dem UTXO-Betrag. Ohne Betrag zählt jedes gleich. */
function lotMischungGewichtet(teile) {
  const acc = { gruen: 0, orange: 0, grau: 0 };
  let hatGewicht = false;
  for (const teil of teile || []) {
    const mischung = teil && teil.mischung;
    if (!mischung) continue;
    const summe = mischung.gruen + mischung.orange + mischung.grau;
    if (!(summe > 0)) continue;
    const gewicht = Number(teil.gewicht) || 0;
    if (gewicht > 0) hatGewicht = true;
    const faktor = gewicht > 0 ? gewicht / summe : 1 / summe;
    acc.gruen += mischung.gruen * faktor;
    acc.orange += mischung.orange * faktor;
    acc.grau += mischung.grau * faktor;
  }
  if (!hatGewicht) return acc.gruen + acc.orange + acc.grau > 0 ? acc : null;
  // UTXOs ohne Betrag fallen heraus, sobald irgendeiner einen hat.
  const neu = { gruen: 0, orange: 0, grau: 0 };
  for (const teil of teile) {
    const mischung = teil && teil.mischung;
    if (!mischung) continue;
    const summe = mischung.gruen + mischung.orange + mischung.grau;
    const gewicht = Number(teil.gewicht) || 0;
    if (!(summe > 0) || !(gewicht > 0)) continue;
    const faktor = gewicht / summe;
    neu.gruen += mischung.gruen * faktor;
    neu.orange += mischung.orange * faktor;
    neu.grau += mischung.grau * faktor;
  }
  return neu.gruen + neu.orange + neu.grau > 0 ? neu : null;
}

function lotMischungAusBaum(kinder, startObergrenze) {
  if (!Array.isArray(kinder) || !kinder.length) return null;
  const start = Number(startObergrenze) || 0;
  const gesehen = new Set();
  const starts = kinder.map((knoten) => ({
    knoten,
    gewicht: lotTeilbaumBetrag(knoten, gesehen),
    obergrenze: start,
  }));
  let summe = starts.reduce((s, e) => s + e.gewicht, 0);
  if (!(summe > 0)) {
    // Kein Betrag im Baum: jedes Blatt Gewicht 1, interne Hops teilen gleich.
    starts.forEach((e) => { e.gewicht = 1; });
  }
  const acc = { gruen: 0, orange: 0, grau: 0 };
  const stapel = [...starts];
  const besucht = new Set();
  while (stapel.length) {
    const { knoten, gewicht, obergrenze } = stapel.pop();
    if (!knoten || typeof knoten !== "object" || !(gewicht > 0)) continue;
    if (besucht.has(knoten)) continue;
    besucht.add(knoten);
    if (knoten.type === "internal") {
      const eigene = Array.isArray(knoten.children) ? knoten.children : [];
      if (!eigene.length) {
        acc.grau += gewicht;
        continue;
      }
      const gesehenKind = new Set();
      const teile = eigene.map((k) => lotTeilbaumBetrag(k, gesehenKind));
      const teilSumme = teile.reduce((s, w) => s + w, 0);
      const grenze = lotObergrenze(obergrenze, knoten);
      eigene.forEach((k, i) => {
        const anteil = teilSumme > 0 ? teile[i] / teilSumme : 1 / eigene.length;
        if (anteil > 0) {
          stapel.push({ knoten: k, gewicht: gewicht * anteil, obergrenze: grenze });
        }
      });
      continue;
    }
    acc[lotFarbeBlatt(knoten, obergrenze)] += gewicht;
  }
  summe = acc.gruen + acc.orange + acc.grau;
  return summe > 0 ? acc : null;
}

/**
 * Grün außerhalb der Frist, orange innerhalb, grau ohne Datum oder unaufgelöst.
 * Liegt ein Nachfolger schon sicher außerhalb, zählt das undatierte Blatt grün.
 */
function lotFarbeBlatt(knoten, obergrenze) {
  const typ = knoten && knoten.type;
  if (typ !== "external" && typ !== "coinbase") return "grau";
  const ts = lotZeitTs(knoten);
  if (ts > 0) return lotFristErfuellt(ts) ? "gruen" : "orange";
  const grenze = Number(obergrenze);
  if (grenze > 0 && lotFristErfuellt(grenze)) return "gruen";
  return "grau";
}

/**
 * Bezug ist jetzt. Stichtag (Anschaffung danach bleibt orange) nur, wenn
 * ``steuerEinstellungen().stichtag_iso`` schon im Client liegt — dieselbe
 * Regel wie ``haltefrist_entscheidung``, ohne neue UI-Texte.
 */
function lotFristErfuellt(timeTs) {
  const steuer = typeof steuerEinstellungen === "function" ? steuerEinstellungen() : {};
  const jahre = Number(steuer.haltefrist_jahre);
  const fristJahre = Number.isFinite(jahre) ? jahre : 1;
  if (fristJahre <= 0) return true;
  const anschaffung = new Date(timeTs * 1000);
  const iso = String(steuer.stichtag_iso || "").trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const monat = String(anschaffung.getMonth() + 1).padStart(2, "0");
    const tag = String(anschaffung.getDate()).padStart(2, "0");
    if (`${anschaffung.getFullYear()}-${monat}-${tag}` > iso) return false;
  }
  const ende = lotPlusJahre(anschaffung, fristJahre);
  return ende.getTime() <= Date.now();
}

function lotPlusJahre(zeitpunkt, jahre) {
  const ziel = new Date(zeitpunkt.getTime());
  const monat = ziel.getMonth();
  ziel.setFullYear(ziel.getFullYear() + jahre);
  if (ziel.getMonth() !== monat) ziel.setDate(0);
  return ziel;
}

/** Drei ganzzahlige Prozente, Summe 100. Größter Rest gewinnt. */
function lotProzente(mischung) {
  const summe = mischung.gruen + mischung.orange + mischung.grau;
  if (!(summe > 0)) return null;
  const roh = ["gruen", "orange", "grau"].map((name) => {
    const exakt = (mischung[name] / summe) * 100;
    return { name, boden: Math.floor(exakt), rest: exakt - Math.floor(exakt) };
  });
  let offen = 100 - roh.reduce((s, t) => s + t.boden, 0);
  const reihe = [...roh].sort((a, b) => b.rest - a.rest || (a.name < b.name ? -1 : 1));
  for (const eintrag of reihe) {
    if (offen <= 0) break;
    if (eintrag.rest <= 0 && offen > 0 && roh.every((t) => t.boden === 0)) break;
    if (eintrag.rest <= 0) continue;
    eintrag.boden += 1;
    offen -= 1;
  }
  // Rundungsreste ohne Bruchteil (z. B. exakt 100) bleiben; Defizit auf den größten Wert.
  if (offen > 0) {
    reihe.sort((a, b) => b.boden - a.boden);
    reihe[0].boden += offen;
  }
  const aus = {};
  for (const eintrag of roh) aus[eintrag.name] = eintrag.boden;
  return aus;
}

function entferneLotDonut(punkt) {
  if (!punkt) return;
  punkt.classList.remove("lot-donut");
  punkt.style.removeProperty("--lot-g");
  punkt.style.removeProperty("--lot-o");
  punkt.style.background = "";
  delete punkt.dataset.lotGruen;
  delete punkt.dataset.lotOrange;
  delete punkt.dataset.lotGrau;
  if (!punkt.getAttribute("class") || punkt.className === "knoten-punkt") {
    punkt.className = "knoten-punkt knoten-eigen";
  } else if (!punkt.classList.contains("knoten-eigen") && punkt.closest(".utxo-kopf")) {
    punkt.classList.add("knoten-eigen");
  }
}

function setzeLotDonut(punkt, mischung) {
  if (!punkt) return;
  const prozent = mischung ? lotProzente(mischung) : null;
  const summe = prozent
    ? prozent.gruen + prozent.orange + prozent.grau
    : 0;
  if (!prozent || summe <= 0) {
    entferneLotDonut(punkt);
    return;
  }
  const stops = [];
  let grad = 0;
  const scheiben = [
    ["gruen", "var(--lot-gruen)"],
    ["orange", "var(--lot-orange)"],
    ["grau", "var(--lot-grau)"],
  ].filter(([name]) => prozent[name] > 0);
  scheiben.forEach(([name, farbe], index) => {
    const ende = index === scheiben.length - 1
      ? 360
      : Math.round((grad + prozent[name] * 3.6) * 1000) / 1000;
    stops.push(`${farbe} ${grad}deg ${ende}deg`);
    grad = ende;
  });
  punkt.classList.add("lot-donut");
  punkt.style.setProperty("--lot-g", String(prozent.gruen));
  punkt.style.setProperty("--lot-o", String(prozent.orange));
  punkt.style.background = "";
  // Auch eine Farbe bleibt Verlauf, sonst überdeckt die Fläche das Loch.
  punkt.style.background = `conic-gradient(${stops.join(", ")})`;
  punkt.dataset.lotGruen = String(prozent.gruen);
  punkt.dataset.lotOrange = String(prozent.orange);
  punkt.dataset.lotGrau = String(prozent.grau);
  punkt.title = lotDonutTitel(mischung);
  punkt.removeAttribute("aria-hidden");
}

/** Echte Anteile, nicht die gerundeten Scheiben. Eine Nachkommastelle. */
function lotDonutTitel(mischung) {
  const summe = mischung.gruen + mischung.orange + mischung.grau;
  if (!(summe > 0)) return "";
  const zahl = (wert) => {
    const anteil = (wert / summe) * 100;
    const text = anteil.toLocaleString(
      typeof formatLocale === "function" ? formatLocale() : "de-DE",
      { minimumFractionDigits: 1, maximumFractionDigits: 1 },
    );
    return `${text} %`;
  };
  return `Grün ${zahl(mischung.gruen)} · Gelb ${zahl(mischung.orange)} · Grau ${zahl(mischung.grau)}`;
}

/** Mischung für die zugeklappte Zeile. Der Zweig selbst bleibt ungezeichnet. */
function ladeLotDonutZugeklappt(wurzel, zweig, ziel, danach) {
  const speicher = zweig || wurzel;
  if (!wurzel || !speicher || !ziel) {
    if (typeof danach === "function") danach(null);
    return;
  }
  // Mehrere UTXOs teilen sich einen Ring: jeder Lauf braucht eigenen Speicher.
  if (!zweig && typeof danach === "function") {
    const lauf = {};
    speicher._lotLaeufe = speicher._lotLaeufe || [];
    speicher._lotLaeufe.push(lauf);
    return holeLotMischung(ziel, lauf).then((mischung) => {
      danach(mischung);
    }).finally(() => {
      const liste = speicher._lotLaeufe;
      if (!liste) return;
      const i = liste.indexOf(lauf);
      if (i >= 0) liste.splice(i, 1);
    });
  }
  if (speicher._lotLauf) return;
  if (punktHatLotDonut(wurzelLotPunkt(wurzel))) return;
  if (zweig) zweig.dataset.baumZiel = ziel;
  speicher._lotLauf = holeLotMischung(ziel, speicher)
    .then((mischung) => {
      if (zweig && zweig.dataset.baumZiel !== ziel) return;
      if (mischung) setzeLotDonut(wurzelLotPunkt(wurzel), mischung);
    })
    .finally(() => { delete speicher._lotLauf; });
}

function holeLotMischung(ziel, speicher) {
  return api(`/trace?target=${encodeURIComponent(ziel)}`)
    .then((g) => {
      const voll = g && g.vorhanden && g.ergebnis && g.ergebnis.children;
      if (!Array.isArray(voll)) return null;
      speicher._lotKinder = voll;
      const wurzelZeit = g.ergebnis && g.ergebnis.root
        ? lotZeitTs(g.ergebnis.root)
        : 0;
      if (wurzelZeit) speicher._lotObergrenze = wurzelZeit;
      return lotMischungAusBaum(voll, Number(speicher._lotObergrenze) || 0);
    })
    .catch(() => null);
}

function punktHatLotDonut(punkt) {
  return Boolean(punkt && punkt.classList.contains("lot-donut"));
}

function wurzelLotPunkt(wurzel) {
  if (!wurzel) return null;
  if (wurzel.classList.contains("knoten-punkt")) return wurzel;
  if (wurzel.classList.contains("utxo-zeile")) {
    return wurzel.querySelector(":scope > .knoten-punkt");
  }
  return wurzel.querySelector(":scope > .kopf-mit-verweis > .utxo-kopf > .knoten-punkt");
}

/**
 * Donut am Wurzelpunkt, sobald die Mischung da ist — auch zugeklappt.
 * *kinder* optional — sonst der beim Zeichnen gemerkte Baum, sonst DOM.
 * Seitenweise Wurzeln holen den vollen Cache-Baum einmal nur für die Mischung.
 */
function aktualisiereLotDonut(wurzel, zweig, kinder, startObergrenze) {
  const punkt = wurzelLotPunkt(wurzel);
  if (!punkt || !wurzel || !zweig) return;
  // Merken, auch solange der Zweig zu ist — Zuklappen lässt den Ring stehen.
  if (Array.isArray(kinder)) zweig._lotKinder = kinder;
  if (startObergrenze) zweig._lotObergrenze = Number(startObergrenze) || 0;
  if (zweig.dataset.geladen !== "ja" && !Array.isArray(zweig._lotKinder)) {
    return;
  }
  const quelle = Array.isArray(kinder) ? kinder : zweig._lotKinder;
  const grenze = Number(zweig._lotObergrenze) || 0;
  if (Array.isArray(quelle) && lotKinderVollstaendig(quelle)) {
    const mischung = lotMischungAusBaum(quelle, grenze);
    if (mischung) setzeLotDonut(punkt, mischung);
    else entferneLotDonut(punkt);
    return;
  }
  const ziel = zweig.dataset.baumZiel;
  if (ziel && !zweig._lotLauf && !punktHatLotDonut(punkt)) {
    zweig._lotLauf = api(`/trace?target=${encodeURIComponent(ziel)}`)
      .then((g) => {
        if (zweig.dataset.baumZiel !== ziel) return;
        const voll = g && g.vorhanden && g.ergebnis && g.ergebnis.children;
        if (!Array.isArray(voll)) return;
        zweig._lotKinder = voll;
        const wurzelZeit = g.ergebnis && g.ergebnis.root
          ? lotZeitTs(g.ergebnis.root)
          : 0;
        if (wurzelZeit) zweig._lotObergrenze = wurzelZeit;
        const mischung = lotMischungAusBaum(
          voll, Number(zweig._lotObergrenze) || 0,
        );
        if (mischung) setzeLotDonut(punkt, mischung);
      })
      .catch(() => {})
      .finally(() => { delete zweig._lotLauf; });
    return;
  }
  if (Array.isArray(quelle)) {
    const mischung = lotMischungAusBaum(quelle, grenze);
    if (mischung) setzeLotDonut(punkt, mischung);
    else entferneLotDonut(punkt);
  }
}

/** Seitenweise Kinder haben keine ``children``-Arrays — die Mischung braucht den vollen Baum. */
function lotKinderVollstaendig(kinder) {
  const stapel = [...kinder];
  while (stapel.length) {
    const knoten = stapel.pop();
    if (!knoten || knoten.type !== "internal") continue;
    if (!Array.isArray(knoten.children)) return false;
    stapel.push(...knoten.children);
  }
  return true;
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
      delete zweig._lotKinder;
      zweig.replaceChildren();
      entferneLotDonut(wurzelLotPunkt(block));
      const zeile = block.querySelector(".utxo-kopf");
      setzeKlapp(zeile, klapp, zweig, true);
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
    setzeKlapp(zeile, klapp, zweig, true);
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
    const elternWallet = knoten.type === "internal" ? (knoten.wallet || "") : undefined;
    const zweig = block.closest(".utxo-zweig");
    const ziel = !Array.isArray(knoten.children) && knoten.pfad != null
      ? zweig?.dataset.baumZiel
      : "";
    if (ziel) {
      // Seitenweise: Kinder dieses Knotens erst jetzt vom Server.
      zeichneBaumSeiten(kinder, ziel, knoten.pfad, {
        elternWallet,
        elternKnoten: knoten,
      });
    } else if (Array.isArray(knoten.children)) {
      kinder.append(zeichneKnotenListe(knoten.children || [], elternWallet, knoten));
    } else if (knoten.pfad != null && zweig) {
      // Der Sprung hat den Baum geholt und baumZiel gelöscht. Ein Knoten ohne
      // Kinderliste ist noch die schlanke Seite — die Kinder jetzt nachladen.
      const wurzel = zweig.closest(".utxo-wurzel");
      const target = wurzel?.dataset.key || "";
      if (target) {
        zweig.dataset.baumZiel = target;
        zeichneBaumSeiten(kinder, target, knoten.pfad, {
          elternWallet,
          elternKnoten: knoten,
        });
      }
    }
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
async function expandiereBaumAlles(zweig) {
  if (!zweig) return;
  // Seitenweise geladen: „Alles aufklappen“ holt den Baum einmal ganz (ein
  // Abruf statt einer Anfrage je Knoten) und zeichnet wie bisher. Es bleibt
  // derselbe eine Baum im Browser.
  const ziel = zweig.dataset.baumZiel;
  if (ziel) {
    try {
      const g = await api(`/trace?target=${encodeURIComponent(ziel)}`);
      const voll = g && g.vorhanden && g.ergebnis;
      const ebene = zweig.querySelector(":scope > .baum-ebene");
      if (voll && Array.isArray(voll.children) && ebene && zweig.dataset.baumZiel === ziel) {
        delete zweig.dataset.baumZiel;
        ebene.replaceChildren(zeichneKnotenListe(voll.children, ebene._elternWallet));
      }
    } catch (_) {
      return;
    }
  }
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

/**
 * Kinder eines Knotens (oder die oberste Ebene, *pfad* leer) seitenweise
 * aus dem gespeicherten Baum. *vorab*: schon mitgelieferte erste Seiten.
 */
function zeichneBaumSeiten(behaelter, ziel, pfad, { elternWallet, elternKnoten, vorab = null, offset = 0, limit = 0 } = {}) {
  const neueQuelle = (erste) => neueSeitenQuelle({
    groesse: Math.max(pagerGroesse("baum"), Number(limit) || 0),
    laden: (o, l) => api(
      `/trace/knoten?target=${encodeURIComponent(ziel)}` +
      `&pfad=${encodeURIComponent(pfad || "")}&offset=${o}&limit=${l}`,
    ),
    auszug: (a) => ({ items: a.items || [], total: Number(a.total) || 0 }),
    vorab: erste,
  });
  let quelle = neueQuelle(vorab);
  const zeige = async (offset) => {
    const q = quelle;
    const seite = await q.seite(offset);
    if (q !== quelle) return;
    behaelter.replaceChildren(zeichneKnotenListe(seite.items, elternWallet, elternKnoten));
    behaelter.append(zeichnePager({
      total: seite.total,
      offset: seite.offset,
      groesse: q.groesse,
      ansicht: "baum",
      onSeite: (o) => { zeige(o).catch(() => {}); },
      onGroesse: () => {
        quelle = neueQuelle(null);
        zeige(0).catch(() => {});
      },
    }));
  };
  if (!vorab) behaelter.replaceChildren(hinweisZeile(t("common.looking")));
  return zeige(offset || 0).catch((fehler) => {
    behaelter.replaceChildren(hinweisZeile(
      t("common.couldNotLoad", { msg: fehler.message }),
    ));
  });
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
  if (knoten.pfad != null && knoten.pfad !== "") block.dataset.pfad = String(knoten.pfad);
  else if (knoten.id != null && /^\d+(?:\.\d+)*$/.test(String(knoten.id))) {
    block.dataset.pfad = String(knoten.id);
    knoten.pfad = String(knoten.id);
  }
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
  if (knoten.from_utxo) block.dataset.fromUtxo = String(knoten.from_utxo);
  if (knoten.type) block.dataset.typ = String(knoten.type);
  if (knoten.tax_horizon) block.dataset.horizont = "1";
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

/**
 * Scorecard „Ohne Herkunftsanalyse“: Zahl unter „klären“ sofort senken.
 * Die Ansicht selbst lädt seltener neu — der Zähler soll trotzdem
 * Punkt für Punkt mitlaufen.
 */
function zaehleGraueKlaerungHerunter(verfolgt) {
  const ziel = document.querySelector("[data-klaer-zaehler='grau']");
  if (!ziel || typeof verfolgt !== "number") return;
  if (ziel.dataset.klaerStart == null) {
    const treffer = String(ziel.textContent || "").match(/(\d+)/);
    if (!treffer) return;
    ziel.dataset.klaerStart = treffer[1];
  }
  const start = Number(ziel.dataset.klaerStart);
  if (!Number.isFinite(start)) return;
  const rest = Math.max(0, start - verfolgt);
  ziel.textContent = ziel.textContent.replace(/\d+/, String(rest));
}

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
    if (typeof onTick === "function") {
      try { onTick(job); } catch (_) { /* Zeichnen darf das Warten nicht abbrechen */ }
    }
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
 * Dieselbe Toleranz wie die Frische-Anzeige: zwei Blöcke sind noch „am Tip“.
 * Weiter zurück ist der Bestand nur nicht nachgezogen — kein Erst-Scan.
 */
const KLAEREN_TIP_TOLERANZ = 2;

function walletLiegtHinterTip(wallet, tipHoehe) {
  if (tipHoehe == null || !Number.isFinite(Number(tipHoehe))) return false;
  if (!wallet || wallet.scan_tip_height == null || wallet.scan_tip_height === "") {
    return false;
  }
  const scanTip = Number(wallet.scan_tip_height);
  if (!Number.isFinite(scanTip)) return false;
  return Number(tipHoehe) - scanTip > KLAEREN_TIP_TOLERANZ;
}

/**
 * Wallets, für die noch kein UTXO-Scan vorliegt.
 * Schon gescannt und leer, sowie Bestände hinter dem aktuellen Tip, bleiben außen vor.
 */
function walletsOhneUtxoScan(config, tipHoehe) {
  const quelle = config || (typeof Zustand !== "undefined" ? Zustand.config : null);
  if (!quelle || quelle.context_bereit === false) return [];
  const tip = tipHoehe !== undefined
    ? tipHoehe
    : (typeof chainTipHoehe === "function" ? chainTipHoehe() : quelle.header_tip);
  return (quelle.wallets || []).filter((wallet) => {
    if (!wallet || !wallet.id || wallet.is_new) return false;
    if (Number(wallet.utxo_count) > 0) return false;
    if (wallet.has_cache) return false;
    if (walletLiegtHinterTip(wallet, tip)) return false;
    return true;
  });
}

function sperreKlaerenKnoepfe(an) {
  for (const id of ["#herkunft-gelb", "#herkunft-grau"]) {
    const el = typeof $ === "function" ? $(id) : null;
    if (el) el.disabled = Boolean(an);
  }
}

function gibKlaerenSperreFrei() {
  Zustand.herkunftAlleLaeuft = false;
  sperreKlaerenKnoepfe(false);
  const lauf = $("#herkunft-lauf");
  if (lauf) lauf.hidden = true;
  if (typeof loeseEmpfangScanPuls === "function") loeseEmpfangScanPuls();
}

/**
 * UTXO-Scan für jedes konfigurierte Wallet — Voraussetzung für
 * „Herkunft aller UTXOs“ bei leerem Cache.
 * *wallets* schränkt auf die noch nie gescannten ein (Scorecard „klären“).
 */
async function scanneAlleWalletsUtxo({
  textEl = null,
  sollAbbrechen = () => false,
  logStand = null,
  wallets = null,
} = {}) {
  const liste = Array.isArray(wallets)
    ? wallets.filter((w) => w && w.id)
    : (Zustand.config?.wallets || []).filter((w) => w && w.id);
  if (!liste.length) {
    throw new Error(t("wallets.emptyList"));
  }
  let scanAb = "";
  for (let i = 0; i < liste.length; i += 1) {
    const wallet = liste[i];
    if (sollAbbrechen()) {
      const err = new Error("abgebrochen");
      err.abgebrochen = true;
      throw err;
    }
    if (textEl) {
      setzeText(textEl, t("trace.allOriginsScanning", {
        aktuell: i + 1,
        gesamt: liste.length,
        name: wallet.name || wallet.id,
      }));
    }
    logZeile(
      t("trace.allOriginsScanning", {
        aktuell: i + 1,
        gesamt: liste.length,
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
    // Neue graue Punkte kommen im Job-Zwischenstand. Ohne Zeichnen hier
    // bleiben sie bis zum nächsten Steuerjahr-Reload an alter Stelle.
    await warteAufJobEnde(jid, {
      sollAbbrechen,
      onTick: (j) => {
        if (logStand) nimmJobLogAb(j, logStand, wallet.name);
        if (Array.isArray(j.result?.neu) && typeof zeichneScanPunkte === "function") {
          zeichneScanPunkte(j.result.neu);
        }
        if (textEl && j.message) {
          setzeText(
            textEl,
            t("trace.allOriginsScanning", {
              aktuell: i + 1,
              gesamt: liste.length,
              name: wallet.name || wallet.id,
            }) + ` · ${übersetzeLogText(j.message)}`,
          );
        }
      },
    });
  }
}

/**
 * Scorecard „klären“: fehlende UTXO-Scans zuerst, dann die eigentliche Routine.
 * Hält die Sperre, solange der Scan lief und die Routine ihn übernehmen soll.
 */
async function scanneUngescannteVorKlaeren() {
  if (
    Zustand.config?.context_bereit === false
    && typeof ladeConfig === "function"
  ) {
    try { await ladeConfig(); } catch (_) { /* alter Stand bleibt */ }
  }
  const tip = typeof chainTipHoehe === "function" ? chainTipHoehe() : null;
  const offen = walletsOhneUtxoScan(Zustand.config, tip);
  if (!offen.length) return { gescannt: false, haeltSperre: false };

  Zustand.herkunftAlleLaeuft = true;
  if (typeof stoesseEmpfangScanPuls === "function") stoesseEmpfangScanPuls();
  sperreKlaerenKnoepfe(true);
  const lauf = $("#herkunft-lauf");
  const textEl = $("#herkunft-text");
  const abbruchKnopf = $("#herkunft-abbruch");
  if (lauf) lauf.hidden = false;
  const ankuendigung = t("trace.clarifyScanFirst", { n: offen.length });
  if (textEl) setzeText(textEl, ankuendigung);
  if (typeof logZeile === "function") logZeile(ankuendigung);
  let abbruchWunsch = false;
  if (abbruchKnopf) {
    abbruchKnopf.onclick = () => {
      abbruchWunsch = true;
      if (textEl) setzeText(textEl, t("common.abortRequested"));
    };
  }
  try {
    await scanneAlleWalletsUtxo({
      textEl,
      sollAbbrechen: () => abbruchWunsch,
      logStand: { index: 0 },
      wallets: offen,
    });
  } catch (fehler) {
    if (typeof ladeConfig === "function") {
      try { await ladeConfig(); } catch (_) { /* nächster Klick sieht den alten Stand */ }
    }
    gibKlaerenSperreFrei();
    if (fehler && fehler.abgebrochen) {
      const k = $("#steuer-meldung");
      if (k) {
        k.className = "hinweis hinweis-warn";
        setzeText(k, t("trace.allOriginsScanAbort"));
        k.hidden = false;
      }
      return { gescannt: false, haeltSperre: false, abbruch: true };
    }
    throw fehler;
  }
  if (typeof ladeConfig === "function") {
    try { await ladeConfig(); } catch (_) { /* Schlüssel kommen trotzdem neu */ }
  }
  if (textEl) setzeText(textEl, t("trace.allOriginsScanDone"));
  return { gescannt: true, haeltSperre: true };
}

function zeigeKlaerenLaeuftSchon() {
  const k = $("#steuer-meldung");
  if (!k) return;
  k.className = "hinweis hinweis-warn";
  setzeText(k, t("tax.originAlreadyRunning") !== "tax.originAlreadyRunning"
    ? t("tax.originAlreadyRunning")
    : t("ui.hard.2c151e092b"));
  k.hidden = false;
}

/**
 * Gelb und grau: erst fehlende UTXO-Scans, danach die bisherige Klären-Routine.
 * *sammle* liefert die Schlüssel oder null, wenn nichts zu tun ist (Meldung selbst).
 * Ein Objekt ist ebenfalls ein Auftrag — Gelb hängt den grauen Lauf davor.
 */
async function klaerenNachUngescannten(sammle, starte) {
  if (Zustand.herkunftAlleLaeuft) {
    zeigeKlaerenLaeuftSchon();
    return;
  }
  let vorab = { gescannt: false, haeltSperre: false };
  let keys = null;
  try {
    vorab = await scanneUngescannteVorKlaeren();
    if (vorab.abbruch) return;
    if (vorab.gescannt) Zustand.steuer = null;
    keys = await sammle();
  } catch (fehler) {
    if (vorab.haeltSperre || Zustand.herkunftAlleLaeuft) gibKlaerenSperreFrei();
    throw fehler;
  }
  if (!keys) {
    if (vorab.haeltSperre) gibKlaerenSperreFrei();
    return;
  }
  if (vorab.haeltSperre) sperreKlaerenKnoepfe(false);
  return starte(keys, Boolean(vorab.haeltSperre));
}

function steuerAbfrageFuerKlaeren() {
  const jahr = $("#jahr-wahl")?.value || "";
  const frist = $("#frist-wahl")?.value || "";
  const stichtag = steuerEinstellungen().stichtag || "";
  return (
    `?jahr=${encodeURIComponent(jahr)}&frist=${encodeURIComponent(frist)}` +
    `&stichtag=${encodeURIComponent(stichtag)}`
  );
}

/** Steuerjahr-Stand mit grau_keys und gelb_keys. Fehlende Listen neu holen. */
async function steuerStandFuerKlaeren() {
  if (Zustand.steuerLots) {
    try { await Zustand.steuerLots; } catch (_) { /* vorläufige Schlüssel */ }
  }
  let daten = Zustand.steuer;
  const hatGrau = daten && Array.isArray(daten.grau_keys);
  const hatGelb = daten && (
    Array.isArray(daten.eintraege) || Array.isArray(daten.gelb_keys)
  );
  if (!hatGrau || !hatGelb) {
    daten = await api(`/tax${steuerAbfrageFuerKlaeren()}&seite=1&limit=0`);
  }
  return daten || {};
}

function grauKeysAus(daten) {
  return Array.isArray(daten?.grau_keys) ? daten.grau_keys : [];
}

function gelbKeysAus(daten) {
  if (!daten) return [];
  const keys = new Set();
  if (Array.isArray(daten.gelb_keys)) {
    for (const key of daten.gelb_keys) {
      if (key) keys.add(String(key));
    }
  } else {
    for (const e of daten.eintraege || []) {
      if (e.geprueft && !e.erfuellt) keys.add(`${e.txid}:${e.vout}`);
    }
  }
  // Graue Lot-Anteile auch in Punkten außerhalb der Haltefrist.
  for (const e of daten.eintraege || []) {
    if (Number(e.sats_ohne_datum) > 0 && e.txid) {
      keys.add(`${e.txid}:${e.vout}`);
    }
  }
  return [...keys];
}

function zeigeKeinGelbZumKlaeren() {
  const k = $("#steuer-meldung");
  if (!k) return;
  k.className = "hinweis hinweis-warn";
  setzeText(k, t("tax.noYellowToClarify") !== "tax.noYellowToClarify"
    ? t("tax.noYellowToClarify")
    : t("ui.hard.d3b790167b"));
  k.hidden = false;
}

/** Dieselben Argumente wie der graue Scorecard-Knopf. *danach* nur für Gelb. */
function starteGrauKlaerung(keys, uebernommen, danach) {
  return herkunftAllerUtxos({
    knopf: "#herkunft-grau",
    lauf: "#herkunft-lauf",
    text: "#herkunft-text",
    abbruch: "#herkunft-abbruch",
    meldung: "#steuer-meldung",
    danach: danach || ladeSteuerjahrMitKandidaten,
    utxo_keys: keys,
    steuer: false,
    gelbVertiefen: false,
    erzwingen: true,
    uebernommen,
    keinPauschalScan: true,
  });
}

function starteGelbKlaerung(keys, uebernommen) {
  return herkunftAllerUtxos({
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
    graueAnteile: true,
    uebernommen,
    keinPauschalScan: true,
  });
}

/**
 * Grauer Lauf aus Gelb ist fertig (gut): Steuerjahr neu lesen, dann Gelb.
 * Abbruch und Fehler beenden hier — Gelb startet nicht hinterher.
 */
function gelbNachGrauFortsetzen(info) {
  if (!info || info.art !== "gut") return;
  Promise.resolve()
    .then(async () => {
      if (typeof ladeSteuerjahrMitKandidaten === "function") {
        try { await ladeSteuerjahrMitKandidaten(); } catch (_) { /* Schlüssel unten */ }
      }
      let daten = Zustand.steuer;
      if (
        !daten
        || (!Array.isArray(daten.eintraege) && !Array.isArray(daten.gelb_keys))
      ) {
        Zustand.steuer = null;
        daten = await steuerStandFuerKlaeren();
      }
      const keys = gelbKeysAus(daten);
      if (!keys.length) {
        zeigeKeinGelbZumKlaeren();
        return;
      }
      return starteGelbKlaerung(keys, false);
    })
    .catch((fehler) => {
      Zustand.herkunftAlleLaeuft = false;
      if (typeof loeseEmpfangScanPuls === "function") loeseEmpfangScanPuls();
      const kasten = $("#steuer-meldung");
      if (!kasten) return;
      kasten.className = "hinweis hinweis-krit";
      setzeText(kasten, fehler.message || String(fehler));
      kasten.hidden = false;
    });
}

async function herkunftGrauUtxos() {
  // Graue Scorecard: noch nie analysiert. Der Massenlauf ohne Schlüssel
  // nimmt nur UTXOs ohne vollen Baum — ein grauer Punkt kann einen
  // unvollständigen Cache haben und würde sonst sofort als „nichts zu tun“
  // enden. Deshalb dieselben Schlüssel wie der Punkt selbst.
  return klaerenNachUngescannten(async () => {
    const keys = grauKeysAus(await steuerStandFuerKlaeren());
    if (!keys.length) {
      const k = $("#steuer-meldung");
      if (!k) return null;
      k.className = "hinweis hinweis-warn";
      setzeText(k, t("trace.allOriginsNothing"));
      k.hidden = false;
      return null;
    }
    return keys;
  }, (keys, uebernommen) => starteGrauKlaerung(keys, uebernommen));
}

async function herkunftGelbUtxos() {
  // Nach dem UTXO-Scan ungescannter Portfolios: derselbe Grau-Lauf wie der
  // graue Knopf. Erst wenn der gut durch ist, die gelben Schlüssel.
  // Gelb (geprüft und Frist offen) und jeder Punkt mit grauem Lot-Anteil,
  // auch links der Haltefrist. Der Lauf geht bis extern/Coinbase und zieht
  // fehlende Blockzeiten undatierter Blätter nach.
  return klaerenNachUngescannten(async () => {
    const daten = await steuerStandFuerKlaeren();
    const grau = grauKeysAus(daten);
    if (grau.length) return { art: "grau", keys: grau };
    const gelb = gelbKeysAus(daten);
    if (!gelb.length) {
      zeigeKeinGelbZumKlaeren();
      return null;
    }
    return { art: "gelb", keys: gelb };
  }, (auftrag, uebernommen) => {
    if (auftrag && auftrag.art === "grau") {
      return starteGrauKlaerung(
        auftrag.keys,
        uebernommen,
        gelbNachGrauFortsetzen,
      );
    }
    return starteGelbKlaerung(auftrag.keys, uebernommen);
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
  erzwingen: false,
  graueAnteile: false,
}) {
  // Selector-String oder bereits aufgelöstes Element (Zeilen-„klären“).
  const knopf = typeof ziele.knopf === "string"
    ? $(ziele.knopf)
    : ziele.knopf;
  if (Zustand.herkunftAlleLaeuft && !ziele.uebernommen) {
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

  const fertig = (meldung, art, jobStand) => {
    clearInterval(timer);
    if (jobStand && jobStand.result && typeof traceMarkenAusJob === "function") {
      traceMarkenAusJob(jobStand.result);
    }
    // Abbruch und Fehler: „?“ weg. Fertige volle Bäume behalten ihr „!“.
    if (art !== "gut" && typeof traceFragenLeeren === "function") {
      traceFragenLeeren();
    }
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
      .then(() => (typeof ziele.danach === "function" ? ziele.danach({ art }) : null))
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

  // Steuergrenze aufgehoben: jeder Lauf bis extern/Coinbase.
  logZeile(t("ui.hard.0a8622a114"));
  try {
    const traceDaten = {
      modus: "voll",
      utxo_keys: ziele.utxo_keys || null,
      erzwingen: Boolean(ziele.erzwingen),
      graue_anteile: Boolean(ziele.graueAnteile),
    };
    let antwort = await api("/trace/alle", {
      methode: "POST",
      daten: traceDaten,
    });
    if (antwort.nichts_zu_tun && antwort.keine_utxos && ziele.keinPauschalScan) {
      // Scorecard hat fehlende Bestände schon gezielt gescannt. Leer und
      // hinter dem Tip bleiben außen vor — kein zweiter Lauf über alle.
      fertig(t("trace.clarifyScanEmpty"), "warn");
      return;
    }
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
      } else if (ziele.gelbVertiefen) {
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
      const live = job.result?.live;
      if (typeof zahl === "number" && zahl !== zuletztVerfolgt) {
        zaehleGraueKlaerungHerunter(zahl);
      }
      if (live && typeof wendeLivePunktAn === "function") {
        wendeLivePunktAn(live);
      }
      if (typeof traceMarkenAusJob === "function") {
        traceMarkenAusJob(job.result);
      }
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
        fertig(job.message || "Herkunft ermittelt.", "gut", job);
      } else if (job.status === "cancelled") {
        fertig("Abgebrochen — bereits ermittelte Herkunft bleibt erhalten.",
               "warn", job);
      } else {
        fertig(job.error || "Analyse fehlgeschlagen.", "krit", job);
      }
    } catch (fehler) {
      fertig(fehler.message, "krit");
    }
  }, 1200);
}
