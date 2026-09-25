/** Datenquellen-UI — aus app.js extrahiert (Modularisierung Slice 2).
 * Klassisches Script: nutzt Globals aus app.js (Zustand, api, t, $, …).
 * Kein import/export. Laden nach app.js; vor oder nach wallets.js ok
 * (oeffneVerwaltung in chrome_nav.js ruft zeichneDatenquellenAnsicht auf).
 */

/* --- nav-warn --- */
const DATENQUELLEN_NAV_WARNUNG =
  "Eigener Node weder per RPC noch per Electrum konfiguriert, " +
  t("ui.hard.2fd28d331d");

function hatPrivatenNode(quellen) {
  const liste = quellen || Zustand.config?.sources || [];
  return liste.some(
    (q) =>
      (q.key === "own_core" || q.key === "own_fulcrum") && q.configured,
  );
}

function aktualisiereDatenquellenNav() {
  const knopf = $("#nav-datenquellen");
  if (!knopf) return;
  const warnung = !hatPrivatenNode();
  knopf.classList.toggle("nav-warn", warnung);
  knopf.title = warnung ? DATENQUELLEN_NAV_WARNUNG : "";
}

/* --- view-boerse-kurs --- */
function zeichneLocalCoreHinweis() {
  const kasten = $("#local-core-hinweis");
  const text = $("#local-core-hinweis-text");
  const knopf = $("#local-core-uebernehmen");
  if (!kasten || !text) return;
  const stand = Zustand.config?.local_core;
  const zeigen = Boolean(stand?.needs_opt_in && stand?.hit);
  kasten.hidden = !zeigen;
  if (!zeigen) return;
  const hit = stand.hit;
  const art = hit.pruned ? t("ui.hard.fa3712d804") : t("ui.hard.4a3387f537");
  const p2p = hit.p2p_port || 8333;
  const p2pHinweis = hit.p2p_tcp_open === false
    ? " " + t("ui.hard.b29012adb2", { p2p })
    : " " + t("ui.hard.6d107a5813", { host: hit.host, p2p });
  text.textContent = t("ui.hard.fc5fef80c2", {
    host: hit.host,
    port: hit.port,
    chain: hit.chain || hit.network,
    art,
    blocks: Number(hit.blocks || 0).toLocaleString(formatLocale()),
    p2pHinweis,
  });
  if (knopf && !knopf.dataset.bound) {
    knopf.dataset.bound = "1";
    knopf.addEventListener("click", async () => {
      knopf.disabled = true;
      try {
        const antwort = await api("/source/local-core", { method: "POST", body: {} });
        if (antwort?.sources) {
          Zustand.config = {
            ...(Zustand.config || {}),
            sources: antwort.sources,
            local_core: antwort.local_core,
          };
        } else {
          await ladeConfig();
        }
        setzeQuellenPending(["own_core", "own_utxo_core"]);
        zeichneDatenquellenAnsicht();
        logZeile("Lokaler Bitcoin Core übernommen.");
        try {
          await testeEigenenNode($("#quelle-pruefen"));
        } catch (_) {
          /* Pille bleibt grau/rot bis zum nächsten Check */
        }
      } catch (fehler) {
        logZeile(String(fehler?.message || fehler), "krit");
      } finally {
        knopf.disabled = false;
      }
    });
  }
}

function zeichneDatenquellenAnsicht() {
  zeichneLocalCoreHinweis();
  zeichneQuellen(Zustand.config?.sources || []);
  zeichneMempoolStatus();
  ladeKursHistorie();
  ladeBoersenReports();
  ladeLabelStatus();
  ladeListenStatus();
  setzeEnvPfad(Zustand.config?.env_path);
  aktualisiereDatenquellenNav();
}

async function ladeBoersenReports() {
  const kasten = $("#boerse-status");
  const zusatz = $("#boerse-zusatz");
  if (!kasten) return;
  try {
    const stand = await api("/exchange-reports");
    zeichneBoersenReports(stand);
  } catch (fehler) {
    kasten.replaceChildren();
    kasten.append(hinweisZeile(t("common.loadFailed", { msg: fehler.message })));
    if (zusatz) setzeText(zusatz, "");
  }
}

function zeichneBoersenReports(stand) {
  const kasten = $("#boerse-status");
  const zusatz = $("#boerse-zusatz");
  if (!kasten) return;
  kasten.replaceChildren();
  const liste = stand?.exchanges || [];
  const nAdr = Number(stand?.addresses || 0);
  const nTx = Number(stand?.txids || 0);
  if (zusatz) {
    setzeText(
      zusatz,
      liste.length
        ? `${liste.length} · ${formatZahl(nAdr)} Adr. · ${formatZahl(nTx)} Tx`
        : "",
    );
  }
  if (!liste.length) {
    kasten.append(hinweisZeile(t("sources.exchangeNone")));
    return;
  }
  for (const e of liste) {
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    zeile.append(pille("gut", e.name || e.slug || "?"));
    const text = document.createElement("span");
    text.textContent = t("sources.exchangeLine", {
      name: "",
      addresses: formatZahl(e.addresses || 0),
      txids: formatZahl(e.txids || 0),
    }).replace(/^:\s*/, "").replace(/^\s+/, "");
    // exchangeLine starts with {name}: — name already in pill
    text.textContent = `${formatZahl(e.addresses || 0)} Adr. · ${formatZahl(e.txids || 0)} Tx`;
    zeile.append(text);
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "stift papierkorb";
    knopf.textContent = "🗑";
    knopf.title = t("sources.exchangeRemoveTitle");
    knopf.setAttribute("aria-label", t("sources.exchangeRemove"));
    knopf.addEventListener("click", () => verwerfeBoersenReport(e.slug));
    zeile.append(knopf);
    kasten.append(zeile);
  }
  if (liste.length > 1) {
    const alle = document.createElement("button");
    alle.type = "button";
    alle.className = "stift papierkorb";
    alle.textContent = "🗑";
    alle.title = t("sources.exchangeRemoveAll");
    alle.setAttribute("aria-label", t("sources.exchangeRemoveAll"));
    alle.addEventListener("click", () => verwerfeBoersenReport(null, true));
    kasten.append(alle);
  }
}

function starteBoersenCsvImport() {
  const feld = $("#boerse-csv-datei");
  if (feld) feld.click();
}

function liesBoersenCsvDatei(ereignis) {
  const datei = ereignis.target.files && ereignis.target.files[0];
  ereignis.target.value = "";
  if (!datei) return;
  const name = window.prompt(t("sources.exchangePromptName"), "");
  if (name == null) return;
  const boerse = String(name || "").trim();
  if (!boerse) {
    meldung(t("sources.exchangePromptName"), "krit");
    return;
  }
  logZeile(t("ui.hard.9ef8652c95", { name: datei.name, boerse }));
  const leser = new FileReader();
  leser.onload = async () => {
    try {
      const ergebnis = await api("/exchange-reports/import", {
        methode: "POST",
        daten: {
          name: boerse,
          csv: String(leser.result || ""),
          filename: datei.name,
          ersetzen: false,
        },
        timeoutMs: 120_000,
      });
      logZeile(
        t("sources.exchangeImported", {
          name: ergebnis.name || boerse,
          addresses: formatZahl(ergebnis.imported_addresses || 0),
          txids: formatZahl(ergebnis.imported_txids || 0),
          btc: formatZahl(ergebnis.rows_btc || 0),
          total: formatZahl(ergebnis.rows_total || 0),
        }),
        true,
      );
      meldung(
        t("sources.exchangeImported", {
          name: ergebnis.name || boerse,
          addresses: formatZahl(ergebnis.addresses || 0),
          txids: formatZahl(ergebnis.txids || 0),
          btc: formatZahl(ergebnis.rows_btc || 0),
          total: formatZahl(ergebnis.rows_total || 0),
        }),
        "gut",
      );
      await ladeBoersenReports();
    } catch (fehler) {
      logZeile(t("ui.hard.b55a184807", { msg: fehler.message }), true);
      meldung(fehler.message, "krit");
    }
  };
  leser.onerror = () => {
    logZeile(t("ui.hard.d7a4215402"), true);
    meldung(t("common.fileUnreadable"), "krit");
  };
  leser.readAsText(datei);
}

async function verwerfeBoersenReport(slug, alle = false) {
  try {
    const q = alle ? "all=1" : `slug=${encodeURIComponent(slug || "")}`;
    await api(`/exchange-reports?${q}`, { methode: "DELETE" });
    await ladeBoersenReports();
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

function zeichneKursHistorie(stand) {
  const kasten = $("#kurs-historie-status");
  if (!kasten) return;
  kasten.replaceChildren();
  const listen = stand?.histories || [];
  if (!listen.length) {
    kasten.append(hinweisZeile("Keine Kurs-Historie geladen."));
    return;
  }
  for (const h of listen) {
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    if (!h.ok) {
      zeile.append(pille("warn", h.currency || "?"));
      zeile.append(document.createTextNode(
        ` ${h.error || t("sources.rates.noFile")}`,
      ));
    } else {
      zeile.append(pille("gut", h.currency));
      const von = h.from || "?";
      const bis = h.to || "?";
      const tage = Number(h.days || 0).toLocaleString(formatLocale());
      const quelle = h.source === "bundle" ? t("sources.rates.bundled")
        : h.source === "cache" ? t("sources.rates.cache")
          : (h.source || "?");
      zeile.append(document.createTextNode(
        ` ${t("sources.rates.line", { days: tage, from: von, to: bis, source: quelle })}`,
      ));
    }
    kasten.append(zeile);
  }
}

async function ladeKursHistorie() {
  try {
    const stand = await api("/price/history");
    Zustand.kursHistorie = stand;
    zeichneKursHistorie(stand);
  } catch (fehler) {
    const kasten = $("#kurs-historie-status");
    if (kasten) {
      kasten.replaceChildren(hinweisZeile(
        /Token fehlt|token missing/i.test(fehler.message || "")
          ? t("history.priceTokenMissing")
          : `${t("sources.rates")}: ${übersetzeServerMeldung(fehler.message)}`,
      ));
    }
  }
}

async function starteKursHistorieSync() {
  logZeile(t("ui.hard.2db4778e8b"));
  try {
    const stand = await api("/price/history/sync", {
      methode: "POST",
      daten: {},
    });
    for (const zeile of stand.log || []) logZeile(zeile);
    Zustand.kursHistorie = {
      histories: stand.histories || [],
      price_history_opt_in: true,
    };
    zeichneKursHistorie(Zustand.kursHistorie);
    // Spot/Serie neu — frische Tage sollen Umrechnung und Kopfzeile sehen.
    Zustand.kursSerie = null;
    Zustand.kursWarnGeloggt = false;
    try {
      await Promise.all([ladeSpotkurs({ laut: false }), ladeKursSerie()]);
    } catch (_e) { /* Spot loggt selbst */ }
    meldung(
      stand.ok ? t("sources.ratesSyncDone") : t("sources.ratesSyncPartial"),
      stand.ok ? "gut" : "warn",
    );
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

let _kursImportWaehrung = "EUR";

function starteKursImport(waehrung) {
  _kursImportWaehrung = waehrung;
  const feld = $("#kurs-csv-datei");
  if (feld) feld.click();
}

function liesKursCsvDatei(ereignis) {
  const datei = ereignis.target.files && ereignis.target.files[0];
  ereignis.target.value = "";
  if (!datei) return;
  const waehrung = _kursImportWaehrung || "EUR";
  logZeile(t("ui.hard.86d64de416", { ccy: waehrung, name: datei.name }));
  const leser = new FileReader();
  leser.onload = async () => {
    try {
      const ergebnis = await api("/price/import", {
        methode: "POST",
        daten: {
          currency: waehrung,
          csv: String(leser.result || ""),
          filename: datei.name,
          ersetzen: false,
        },
      });
      const tage = Number(ergebnis.days || 0).toLocaleString(formatLocale());
      const neu = Number(ergebnis.imported || 0).toLocaleString(formatLocale());
      logZeile(
        `Kurs-CSV ${waehrung}: ${neu} Zeilen gelesen, ${tage} Tage im Cache`
        + (ergebnis.from && ergebnis.to
          ? ` (${ergebnis.from} – ${ergebnis.to}).`
          : "."),
        true,
      );
      meldung(t("ui.hard.ad9ac58e28", { ccy: waehrung }), "gut");
      Zustand.kursSerie = null;
      await Promise.all([ladeKursHistorie(), ladeKursSerie()]);
    } catch (fehler) {
      logZeile(t("ui.hard.0e8ba65bab", { msg: fehler.message }), true);
      meldung(fehler.message, "krit");
    }
  };
  leser.onerror = () => {
    logZeile(t("ui.hard.35e1e02ff2"), true);
    meldung(t("common.fileUnreadable"), "krit");
  };
  leser.readAsText(datei);
}

/* --- quellen-ui --- */
/**
 * Hoch-private Quelle verdrängt mäßig/gering (Auto-Vorrang), solange sie
 * nicht nachweislich unerreichbar ist.
 */
function quelleHochVerdraengt(quellen) {
  return (quellen || []).some(
    (q) => q && q.privacy === "hoch" && q.configured && q.reachable !== false,
  );
}

/**
 * Farbe der Erläuterungsnotiz unter einer Datenquelle.
 * - grün: konfiguriert und Privatsphäre hoch
 * - grau: nicht konfiguriert; Liste geladen aber unverbunden; oder mäßig/gering
 *   und von einer Hoch-Privatsphäre-Quelle verdrängt
 * - gelb: mäßig/gering mit bestehender und genutzter Verbindung
 */
function quelleNotizKlasse(quelle, quellen) {
  if (!quelle.configured) return "quelle-notiz notiz-inaktiv";
  if (quelle.privacy === "hoch") return "quelle-notiz notiz-hoch";
  // Nur gelb bei echter, genutzter Verbindung — geladene Liste allein bleibt grau.
  if (quelle.reachable !== true || quelleHochVerdraengt(quellen)) {
    return "quelle-notiz notiz-inaktiv";
  }
  return "quelle-notiz";
}

/**
 * Privatsphäre-Pille: mäßig/gering erst bei genutzter Verbindung färben.
 */
function quellePrivacyStufe(quelle, quellen) {
  if (!quelle.configured) return "neutral";
  if (quelle.privacy === "hoch") return "gut";
  if (quelle.reachable !== true || quelleHochVerdraengt(quellen)) {
    return "neutral";
  }
  return ({ "mäßig": "warn", gering: "krit" }[quelle.privacy] || "neutral");
}

/**
 * Gelbe „Verbindung im Aufbau…“-Pille nur während eines echten Checks
 * für Quellen, die der Check gerade anfasst — nicht bei idle reachable=null
 * und nicht bei öffentlich, wenn P2P/Eigen Vorrang hat oder Opt-in aus ist.
 */
function quelleZeigtVerbindungsaufbau(quelle, quellen) {
  if (!quelle || !quelle.configured) return false;
  if (!Zustand.peerCheckLaeuft) return false;
  if (quelle.reachable === true || quelle.reachable === false) return false;
  if (quelle.key === "public_onion" || quelle.key === "clearnet") {
    if (!Zustand.config?.oeffentliche_electrum) return false;
    if (quelleHochVerdraengt(quellen)) return false;
  }
  return true;
}

function zeichneQuellen(quellen) {
  const behaelter = $("#quellen-liste");
  if (!behaelter) return;
  behaelter.replaceChildren();
  const liste = quellen || [];

  for (const quelle of liste) {
    const bridgeManaged = start9BridgeManaged(quelle);
    const block = document.createElement("div");
    const zeile = document.createElement("div");
    zeile.className = "quelle-zeile";
    if (!quelle.configured) zeile.classList.add("nicht-konfiguriert");

    const rang = document.createElement("span");
    rang.className = "quelle-rang";
    rang.textContent = quelle.rank;

    const name = document.createElement("span");
    name.className = "quelle-name";
    const anzeigename = quelleName(quelle);
    name.textContent = anzeigename;

    const detail = document.createElement("span");
    detail.className = "quelle-detail";
    detail.textContent = quelleDetail(quelle);

    const rechts = document.createElement("span");
    rechts.className = "quelle-rechts";

    if (quelle.configured && quelle.reachable === true) {
      rechts.append(pille("gut", t("sources.reachable")));
    } else if (quelle.configured && quelle.reachable === false) {
      rechts.append(pille("krit", t("sources.unreachable")));
    } else if (quelleZeigtVerbindungsaufbau(quelle, liste)) {
      rechts.append(pille("warn", t("sources.connecting")));
    }
    // Sonst keine Status-Pille: Liste geladen, aber gerade nicht genutzt
    // (z. B. öffentlich nach „P2P / kappen“) → grau über Notiz/Privatsphäre.
    rechts.append(pille(quellePrivacyStufe(quelle, liste), privacyLabel(quelle.privacy)));

    const formular = document.createElement("div");
    formular.className = "quelle-formular";
    formular.hidden = true;

    if (quelle.editierbar) {
      const stift = document.createElement("button");
      stift.type = "button";
      stift.className = "stift";
      stift.textContent = "✎";
      stift.title = bridgeManaged
        ? t("sources.start9BridgeHint")
        : t("sources.editTitle", { name: anzeigename });
      stift.disabled = bridgeManaged;
      stift.setAttribute("aria-expanded", "false");
      stift.addEventListener("click", () => {
        const auf = formular.hidden;
        if (auf && formular.childElementCount === 0) {
          formular.append(quellenFormular(quelle, formular));
        }
        formular.hidden = !auf;
        stift.setAttribute("aria-expanded", String(auf));
      });
      rechts.append(stift);
    }

    // Papierkorb für eigene Nodes hier; P2P erst hinter „Verbinden“
    // (gleiche Reihenfolge wie Electrum: Aktion, dann 🗑).
    if (quelle.verwerfbar && quelle.key !== "bip158") {
      const korb = document.createElement("button");
      korb.type = "button";
      korb.className = "stift papierkorb";
      korb.textContent = "🗑";
      korb.title = bridgeManaged
        ? t("sources.start9BridgeHint")
        : t("sources.discardTitle", { name: anzeigename });
      korb.disabled = bridgeManaged;
      korb.addEventListener("click", () => verwerfeQuelle(quelle));
      rechts.append(korb);
    }

    if (quelle.laden_url && quelle.laden_filter) {
      const laden = document.createElement("button");
      laden.type = "button";
      laden.className = "knopf knopf-klein";
      laden.textContent = t("sources.connect");
      laden.title = t("sources.loadElectrumTitle", { url: quelle.laden_url });
      laden.addEventListener("click", () => ladeElectrumServer(quelle, laden));
      rechts.append(laden);
      // Papierkorb hinter dem Verbinden-Knopf: nur die Serverliste, nicht Opt-in.
      if (quelle.configured) {
        const listeKorb = document.createElement("button");
        listeKorb.type = "button";
        listeKorb.className = "stift papierkorb";
        listeKorb.textContent = "🗑";
        listeKorb.title = t("sources.clearListTitle", { name: anzeigename });
        listeKorb.addEventListener("click", () => loescheElectrumListe(quelle));
        rechts.append(listeKorb);
      }
    }

    if (quelle.key === "bip158") {
      const hoehe = document.createElement("input");
      hoehe.type = "number";
      hoehe.className = "quelle-start-hoehe";
      hoehe.min = "0";
      hoehe.step = "1";
      hoehe.inputMode = "numeric";
      hoehe.placeholder = t("sources.bip158StartPlaceholder");
      hoehe.title = t("sources.bip158StartTitle");
      hoehe.disabled = bridgeManaged;
      const startWert = quelle.start_height != null
        ? String(quelle.start_height)
        : "";
      hoehe.value = startWert;
      hoehe.dataset.savedValue = startWert;
      hoehe.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          hoehe.blur();
        }
      });
      hoehe.addEventListener("change", () => speichereBip158StartHoehe(hoehe));
      rechts.append(hoehe);

      const verbinden = document.createElement("button");
      verbinden.type = "button";
      verbinden.className = "knopf knopf-klein";
      verbinden.textContent = t("sources.connect");
      verbinden.title = t("sources.connectP2pTitle");
      verbinden.disabled = bridgeManaged;
      verbinden.addEventListener("click", () => verbindeP2p(quelle, verbinden));
      rechts.append(verbinden);
      if (quelle.verwerfbar) {
        const korb = document.createElement("button");
        korb.type = "button";
        korb.className = "stift papierkorb";
        korb.textContent = "🗑";
        korb.title = bridgeManaged
          ? t("sources.start9BridgeHint")
          : t("sources.disableP2pTitle");
        korb.disabled = bridgeManaged;
        korb.addEventListener("click", () => verwerfeQuelle(quelle));
        rechts.append(korb);
      }
    }

    zeile.append(rang, name, detail, rechts);

    const notizText = quelleNotiz(quelle);
    if (notizText) {
      const notiz = document.createElement("span");
      notiz.className = quelleNotizKlasse(quelle, liste);
      notiz.textContent = notizText;
      zeile.append(notiz);
    }
    if (bridgeManaged) {
      const hinweis = document.createElement("span");
      hinweis.className = "quelle-notiz notiz-inaktiv";
      hinweis.textContent = t("sources.start9BridgeHint");
      zeile.append(hinweis);
    }

    block.append(zeile, formular);
    behaelter.append(block);
  }
}

async function verwerfeQuelle(quelle) {
  const ok = window.confirm(
    quelle.key === "bip158"
      ? t("sources.confirmDisableP2p")
      : t("sources.confirmDiscard", { name: quelleName(quelle) }),
  );
  if (!ok) return;
  try {
    const ergebnis = await api(`/config/source/${encodeURIComponent(quelle.key)}`, {
      methode: "DELETE",
    });
    // P2P-Papierkorb bricht Header/Scan-Jobs serverseitig ab — UI mitziehen.
    if (quelle.key === "bip158") {
      const cancelled = Array.isArray(ergebnis.cancelled_jobs)
        ? ergebnis.cancelled_jobs
        : [];
      if (
        Zustand.rescanJob
        && (cancelled.includes(Zustand.rescanJob) || cancelled.length)
      ) {
        beendeRescan(t("sources.p2pJobsCancelled"), false);
      }
      if (cancelled.length) {
        meldung(t("sources.p2pJobsCancelled"), "warn");
      }
      await ladeJobsNav();
    }
    // Zuerst Server-Antwort (P2P-Schalter aus), dann Config — sonst hält
    // uebernehmeQuellenErreichbarkeit kurz den alten „an“-Stand.
    if (Zustand.config && Array.isArray(ergebnis.sources)) {
      Zustand.config.sources = ergebnis.sources;
    }
    await ladeConfig();
    // Nach ladeConfig nochmals DELETE-Stand für bip158 erzwingen, falls Merge
    // reachable/peers aus Altlasten mischt — configured kommt aus .env.
    if (Array.isArray(ergebnis.sources)) {
      const nach = Object.create(null);
      for (const q of ergebnis.sources) {
        if (q && q.key) nach[q.key] = q;
      }
      Zustand.config.sources = (Zustand.config.sources || []).map((q) => {
        const frisch = nach[q.key];
        if (!frisch) return q;
        if (q.key === "bip158" || !frisch.configured) {
          return {
            ...frisch,
            reachable: frisch.configured ? q.reachable : null,
            peer_count: frisch.configured ? (q.peer_count || 0) : 0,
            peer_hosts: frisch.configured ? (q.peer_hosts || []) : [],
          };
        }
        return q;
      });
    }
    zeichneDatenquellenAnsicht();
    zeichneKopfStatus(Zustand.config.sources);
    meldung(
      quelle.key === "bip158"
        ? t("sources.p2pDisabled")
        : t("sources.discarded", { name: quelleName(quelle) }),
      "warn",
    );
    // Node-Check nachziehen (nächste Quelle), P2P nicht wieder „an“ malen.
    pruefeNodeStatus();
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

async function ladeElectrumServer(quelle, knopf) {
  const vorher = knopf.textContent;
  knopf.disabled = true;
  knopf.textContent = t("common.loadingEllipsis");
  try {
    const ergebnis = await api("/config/electrum-servers", {
      methode: "POST",
      daten: { filter: quelle.laden_filter },
    });
    await ladeConfig();
    zeichneQuellen(Zustand.config.sources);
    meldung(übersetzeLogText(ergebnis.message || t("sources.listAdopted")), "gut");
    pruefeNodeStatus();
  } catch (fehler) {
    meldung(fehler.message, "krit");
    knopf.disabled = false;
    knopf.textContent = vorher;
  }
}

/** P2P-Zeile: Start­höhe speichern (kein Stift-Dialog mehr). */
async function speichereBip158StartHoehe(eingabe) {
  if (!eingabe || eingabe.disabled) return;
  const roh = String(eingabe.value || "").trim();
  if (!roh) return;
  const n = Number(roh);
  if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
    meldung(t("sources.bip158StartInvalid"), "krit");
    return;
  }
  const vorher = eingabe.dataset.savedValue;
  if (vorher != null && vorher === String(n)) return;
  eingabe.disabled = true;
  try {
    const ergebnis = await api("/config/source", {
      methode: "PUT",
      daten: {
        source: "bip158",
        values: { BIP158_START_HEIGHT: String(n) },
      },
    });
    await ladeConfig();
    if (Array.isArray(ergebnis.sources) && Zustand.config) {
      Zustand.config.sources = ergebnis.sources;
    }
    eingabe.dataset.savedValue = String(n);
    zeichneQuellen(Zustand.config?.sources || ergebnis.sources || []);
    meldung(t("sources.bip158StartSaved", { n }), "gut");
  } catch (fehler) {
    meldung(fehler.message, "krit");
    eingabe.disabled = false;
  }
}

/** P2P-Zeile: „Verbinden“ schaltet Compact Filter ein (früher Checkbox). */
async function verbindeP2p(quelle, knopf) {
  const vorher = knopf.textContent;
  knopf.disabled = true;
  knopf.textContent = t("common.loadingEllipsis");
  const hatteOeffentlich = oeffentlicheElectrumNochAktiv();
  try {
    const ergebnis = await api("/config/source", {
      methode: "PUT",
      daten: { source: "bip158", values: { BIP158_P2P: "true" } },
    });
    await ladeConfig();
    const pending = Array.isArray(ergebnis.pending_sources)
      && ergebnis.pending_sources.length
      ? ergebnis.pending_sources
      : quellenPendingKeysNachSave("bip158");
    setzeQuellenPending(pending);
    zeichneQuellen(Zustand.config?.sources || ergebnis.sources || []);
    meldung(t("sources.appliedTesting"), "warn");
    try {
      const stand = await testeEigenenNode($("#quelle-pruefen"));
      meldung(
        t("sources.appliedResult", { stand: stand.label }),
        stand.gut ? "gut" : "krit",
      );
      if (hatteOeffentlich && p2pQuelleVerbunden()) {
        await frageP2pPrivatsphaereKappen();
      }
    } catch (testFehler) {
      meldung(t("sources.appliedTestFailed", { msg: testFehler.message }), "krit");
    }
  } catch (fehler) {
    meldung(fehler.message, "krit");
    knopf.disabled = false;
    knopf.textContent = vorher;
  }
}

async function loescheElectrumListe(quelle) {
  const ok = window.confirm(
    t("sources.confirmClearList", { name: quelleName(quelle) }),
  );
  if (!ok) return;
  try {
    const ergebnis = await api(`/config/source/${encodeURIComponent(quelle.key)}`, {
      methode: "DELETE",
    });
    await ladeConfig();
    zeichneQuellen(ergebnis.sources || Zustand.config.sources);
    meldung(t("sources.listCleared", { name: quelleName(quelle) }), "warn");
    pruefeNodeStatus();
  } catch (fehler) {
    meldung(fehler.message, "krit");
  }
}

/** Baut das Bearbeitungsformular einer Datenquelle. */
function quellenFormular(quelle, behaelter) {
  const form = document.createElement("div");
  const bridgeManaged = start9BridgeManaged(quelle);
  const eingaben = new Map();

  for (const feld of quelle.felder) {
    const zeile = document.createElement("label");
    zeile.className = "feld-zeile";

    const titel = document.createElement("span");
    titel.className = "feld-titel";
    titel.textContent = quelleFeldLabel(feld, quelle.key);
    zeile.append(titel);

    let eingabe;
    if (feld.typ === "checkbox") {
      eingabe = document.createElement("input");
      eingabe.type = "checkbox";
      eingabe.checked = feld.value === "true";
      eingabe.className = "feld-checkbox";
    } else if (feld.typ === "schalter") {
      eingabe = document.createElement("select");
      for (const [wert, text] of [["true", t("common.yes")], ["false", t("common.no")]]) {
        const option = document.createElement("option");
        option.value = wert;
        option.textContent = text;
        eingabe.append(option);
      }
      eingabe.value = feld.value === "true" ? "true" : "false";
    } else if (feld.typ === "liste") {
      eingabe = document.createElement("textarea");
      eingabe.rows = 4;
      eingabe.className = "mono";
      eingabe.value = feld.value;
    } else {
      eingabe = document.createElement("input");
      eingabe.type = feld.typ === "geheim" ? "password" : "text";
      eingabe.className = "mono";
      eingabe.value = feld.value;
      eingabe.autocomplete = "off";
      if (feld.typ === "geheim") {
        eingabe.placeholder = feld.gesetzt ? t("common.passwordKept") : "";
      }
    }
    eingabe.dataset.key = feld.key;
    if (bridgeManaged) eingabe.disabled = true;
    eingaben.set(feld.key, eingabe);
    zeile.append(eingabe);

    const hinweisText = quelleFeldHinweis(feld, quelle.key);
    if (hinweisText) {
      const hinweis = document.createElement("span");
      hinweis.className = "feld-hinweis";
      hinweis.textContent = hinweisText;
      zeile.append(hinweis);
    }
    form.append(zeile);
  }

  const fuss = document.createElement("div");
  fuss.className = "formular-fuss";

  const meldungsfeld = document.createElement("span");
  meldungsfeld.className = "feld-hinweis";

  const abbrechen = document.createElement("button");
  abbrechen.type = "button";
  abbrechen.className = "knopf knopf-klein";
  abbrechen.textContent = t("common.close");
  abbrechen.addEventListener("click", () => {
    behaelter.hidden = true;
  });

  const speichern = document.createElement("button");
  speichern.type = "button";
  speichern.className = "knopf knopf-klein knopf-primaer";
  speichern.textContent = t("common.apply");
  speichern.disabled = bridgeManaged;
  speichern.addEventListener("click", async () => {
    speichern.disabled = true;
    meldungsfeld.textContent = "";
    const werte = {};
    for (const [key, eingabe] of eingaben) {
      werte[key] = eingabe.type === "checkbox"
        ? (eingabe.checked ? "true" : "false")
        : eingabe.value;
    }
    try {
      const ergebnis = await api("/config/source", {
        methode: "PUT",
        daten: { source: quelle.key, values: werte },
      });
      await ladeConfig();
      // Alte grüne Pille verwerfen: grau bis der neue Connect steht.
      const pending = Array.isArray(ergebnis.pending_sources)
        && ergebnis.pending_sources.length
        ? ergebnis.pending_sources
        : quellenPendingKeysNachSave(quelle.key);
      setzeQuellenPending(pending);
      zeichneQuellen(Zustand.config?.sources || ergebnis.sources || []);
      meldung(t("sources.appliedTesting"), "warn");
      try {
        // jubel:true — Staub nach jedem erfolgreichen Indexer-Übernehmen.
        const stand = await testeEigenenNode($("#quelle-pruefen"), { jubel: true });
        meldung(
          t("sources.appliedResult", { stand: stand.label }),
          stand.gut
            || standHatHochPrivateVerbindung(stand, Zustand.config?.sources)
            ? "gut"
            : "krit",
        );
      } catch (testFehler) {
        meldung(t("sources.appliedTestFailed", { msg: testFehler.message }), "krit");
      }
    } catch (fehler) {
      meldungsfeld.textContent = fehler.message;
      speichern.disabled = false;
    }
  });

  fuss.append(meldungsfeld, abbrechen, speichern);
  form.append(fuss);
  return form;
}

async function ladeListenStatus() {
  const kasten = $("#listen-status");
  try {
    const status = await api("/sanctions");
    kasten.replaceChildren();

    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    if (!status.vorhanden) {
      zeile.append(pille("warn", t("sanctions.noLists")));
      const text = document.createElement("span");
      text.textContent = t("sanctions.noListsHint");
      zeile.append(text);
      setzeText($("#listen-zusatz"), "");
    } else {
      zeile.append(pille("gut", t("common.loaded")));
      const text = document.createElement("span");
      text.textContent = t("sanctions.counts", {
        addresses: status.adressen.toLocaleString(formatLocale()),
        entities: status.entitaeten.toLocaleString(formatLocale()),
      });
      zeile.append(text);
      setzeText(
        $("#listen-zusatz"),
        status.stand ? t("sanctions.asOf", { when: formatZeitpunkt(status.stand) }) : ""
      );
    }

    const vorbehalt = document.createElement("span");
    vorbehalt.className = "vorbehalt";
    // Backend liefert DE-Hinweise; UI-Keys decken die bekannten ab.
    const hinweise = (status.hinweise || []).map((h) => {
      if (/Zahl je Quelle|count per source/i.test(h)) return t("sanctions.hintMultiList");
      if (/Fehler und veralten|errors and go stale/i.test(h)) return t("sanctions.hintFallible");
      return h;
    });
    vorbehalt.textContent = hinweise.join(" ");
    zeile.append(vorbehalt);
    kasten.append(zeile);

    if (status.quellen && status.quellen.length > 0) {
      const liste = document.createElement("div");
      liste.className = "quellen-liste";
      for (const quelle of status.quellen) {
        const eintrag = document.createElement("div");
        eintrag.className = "quelle-eintrag";
        const name = document.createElement("span");
        name.textContent = quelle.name;
        const anzahl = document.createElement("span");
        anzahl.textContent = quelle.adressen.toLocaleString(formatLocale());
        eintrag.append(name, anzahl);
        liste.append(eintrag);
      }
      kasten.append(liste);
    }
  } catch (fehler) {
    kasten.replaceChildren();
    const zeile = document.createElement("div");
    zeile.className = "sanktions-zeile";
    zeile.textContent = t("sanctions.statusUnavailable", { msg: fehler.message });
    kasten.append(zeile);
  }
}

async function aktualisiereListen() {
  const knopf = $("#listen-update");
  knopf.disabled = true;
  const imp = $("#listen-import");
  if (imp) imp.disabled = true;
  $("#listen-lauf").hidden = false;
  const abbruchKnopf = $("#listen-abbruch");
  if (abbruchKnopf) {
    abbruchKnopf.hidden = false;
    abbruchKnopf.disabled = false;
  }
  setzeText($("#listen-text"), t("common.downloadStarting"));

  const fertig = (meldung) => {
    clearInterval(timer);
    knopf.disabled = false;
    if (imp) imp.disabled = false;
    $("#listen-lauf").hidden = true;
    if (abbruchKnopf) abbruchKnopf.hidden = true;
    if (meldung) meldungListen(meldung);
    ladeListenStatus();
  };

  let jobId = null;
  let timer = null;
  if (abbruchKnopf) {
    abbruchKnopf.onclick = async () => {
      abbruchKnopf.disabled = true;
      setzeText($("#listen-text"), t("common.abortRequested"));
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
    const job = await api("/sanctions/update", { methode: "POST", daten: {} });
    jobId = job.id;
  } catch (fehler) {
    fertig(`Aktualisierung fehlgeschlagen: ${fehler.message}`);
    return;
  }

  timer = setInterval(async () => {
    try {
      const job = await api(`/jobs/${jobId}`);
      setzeText($("#listen-text"), übersetzeLogText(job.message || t("common.runningEllipsis")));
      if (job.running) return;
      if (job.status === "cancelled") {
        fertig(t("common.cancelled"));
        return;
      }
      fertig(job.status === "done" ? "" : (übersetzeServerMeldung(job.error) || t("common.failed")));
    } catch (fehler) {
      fertig(fehler.message);
    }
  }, 1200);
}

/* --- mempool-status --- */
function zeichneMempoolStatus() {
  const instanz = Zustand.config?.mempool || {};
  const managed = sourcesFullyManaged();
  const kasten = document.getElementById(managed ? "mempool-status-managed" : "mempool-status");
  if (!kasten) return;
  kasten.replaceChildren();
  const stufen = {
    keine: ["warn", t("sources.detail.notSet")],
    lokal: ["gut", t("sources.ownNetwork")],
    oeffentlich: ["warn", t("sources.mempool.publicReachable")],
    fremd: ["krit", t("sources.mempool.publicService")],
  };
  const [art, beschriftung] = stufen[instanz.stufe] || stufen.keine;
  kasten.append(pille(art, beschriftung));
  const hinweisKey = {
    lokal: "sources.mempool.local",
    fremd: "sources.mempool.publicKnown",
    oeffentlich: "sources.mempool.publicOther",
  }[instanz.stufe];
  const text = document.createElement("span");
  text.textContent = hinweisKey ? t(hinweisKey) : (instanz.hinweis || "");
  kasten.append(text);
  const feld = document.getElementById(managed ? "mempool-url-managed" : "mempool-url");
  if (feld) feld.value = instanz.url || "";
}

/* --- mempool-save --- */
function mempoolUrlWirktOeffentlich(roh) {
  let text = String(roh || "").trim();
  if (!text) return false;
  try {
    // Kein /…/-Literal mit // — sonst stolpert der Klammer-Check in tests/test_web_js.
    if (!(text.startsWith("http://") || text.startsWith("https://"))) {
      text = `https://${text}`;
    }
    const u = new URL(text);
    const host = String(u.hostname || "").toLowerCase();
    if (!host) return false;
    if (host === "localhost" || host.endsWith(".localhost")) return false;
    if (host.endsWith(".onion")) return false;
    if (
      host.endsWith(".local")
      || host.endsWith(".lan")
      || host.endsWith(".internal")
      || host.endsWith(".home")
      || host.endsWith(".home.arpa")
      || host.endsWith(".test")
      || host.endsWith(".example")
      || host.endsWith(".invalid")
    ) {
      return false;
    }
    if (
      /^127\./.test(host)
      || /^10\./.test(host)
      || /^192\.168\./.test(host)
      || /^172\.(1[6-9]|2\d|3[01])\./.test(host)
    ) {
      return false;
    }
    // Hostname ohne Punkt → typisch LAN-Kurzname.
    if (!host.includes(".")) return false;
    return true;
  } catch (_) {
    return false;
  }
}

async function speichereMempool() {
  const managed = sourcesFullyManaged();
  const knopf = document.getElementById(managed ? "mempool-speichern-managed" : "mempool-speichern");
  if (!knopf) return;
  knopf.disabled = true;
  try {
    const feld = document.getElementById(managed ? "mempool-url-managed" : "mempool-url");
    const url = feld ? String(feld.value || "").trim() : "";
    let publicOptIn = false;
    if (url && mempoolUrlWirktOeffentlich(url)) {
      const ok = window.confirm(
        t("sources.mempool.publicConfirm"),
      );
      if (!ok) {
        // Abbruch: nicht speichern, Eingabe leeren.
        if (feld) feld.value = "";
        return;
      }
      publicOptIn = true;
    }
    await api("/config/mempool", {
      methode: "PUT",
      daten: { url, public_opt_in: publicOptIn },
    });
    await ladeConfig();
    zeichneMempoolStatus();
    zeichneKopfStatus(Zustand.config?.quellen || []);
    Zustand.traceListe = null;
    verwerfeGezeichneteVerweise();
    meldung(t("sources.explorerSaved"), "gut");
  } catch (fehler) {
    meldung(t("settings.notSaved", { msg: fehler.message }), "krit");
  } finally {
    knopf.disabled = false;
  }
}

/* --- node-test --- */
async function testeEigenenNode(knopf, opts = {}) {
  const vorher = knopf ? knopf.textContent : "";
  if (knopf) {
    knopf.disabled = true;
    knopf.textContent = t("common.testing");
  }
  if (eigenerNode(Zustand.config?.sources) || knopf) {
    logZeile(t("ui.hard.7c5b3235d4"));
  }
  Zustand.peerCheckLaeuft = true;
  // Sofort „Verbindung im Aufbau…“ in Datenquellen, solange der Check läuft.
  if ($("#quellen-liste")?.childElementCount) {
    zeichneQuellen(Zustand.config?.sources || []);
  }
  try {
    const ergebnis = await apiSourceCheck();
    const stand = nimmPeerStand(ergebnis, false);
    // Staub bei jedem erfolgreichen Speichern/Test einer hoch-privaten
    // Verbindung (Indexer/P2P) — auch nach IP-/Software-Wechsel.
    // Öffentliches Electrum: nie. Stiller Poll: nie.
    const bewusst = Boolean(knopf) || Boolean(opts.jubel);
    if (
      bewusst
      && standHatHochPrivateVerbindung(
        stand,
        Zustand.config?.sources || ergebnis.sources,
      )
    ) {
      jubelDatenquelleErfolg();
    }
    return stand;
  } finally {
    Zustand.peerCheckLaeuft = false;
    if ($("#quellen-liste")?.childElementCount) {
      zeichneQuellen(Zustand.config?.sources || []);
    }
    if (knopf) {
      knopf.disabled = false;
      knopf.textContent = vorher || "Eigenen Node testen";
    }
  }
}

async function pruefeNodeStatus() {
  try {
    await testeEigenenNode();
  } catch (_) {
    /* Kopfzeile bleibt beim letzten Stand — kein rotes Aufblitzen bei Netzfehlern zum eigenen Server. */
  }
}

