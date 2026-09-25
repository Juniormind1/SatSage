/** Mempool-Verweise (Explorer-Links) — aus app.js extrahiert (Modularisierung UI-Schritt 3).
 * Klassisches Script: Globals (mempoolVerweis, verwerfeGezeichneteVerweise).
 * Kein import/export.
 * Laden nach app.js (zeigeWallet), vor Views und chrome — Aufrufer in Views.
 */

// ---------------------------------------------------------------------------
// Verweise auf die eigene mempool-Instanz
// ---------------------------------------------------------------------------

/**
 * Baut einen Verweis nach außen — oder nichts.
 *
 * Ohne konfigurierte Instanz entsteht bewusst kein Element. Ein Standardwert
 * auf mempool.space würde jedem Klick verraten, welche Adresse den Benutzer
 * interessiert; das widerspräche allem, was die Datenquellenwahl schützt.
 */
function mempoolVerweis(art, wert) {
  const instanz = Zustand.config?.mempool;
  if (!instanz || !instanz.configured || !wert) return null;

  const link = document.createElement("a");
  // Grün = eigenes Netz; Gelb = öffentlicher/fremder Explorer (Klick verrät Interesse).
  link.className = instanz.local
    ? "extern-link extern-link-lokal"
    : "extern-link extern-link-fremd";
  link.href = `${instanz.url}/${art}/${encodeURIComponent(wert)}`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.referrerPolicy = "no-referrer";
  link.textContent = "↗";
  const kopf = instanz.local
    ? t("sources.mempool.openPrivate")
    : t("sources.mempool.openPublic");
  const zielArt = art === "address"
    ? t("sources.mempool.targetAddress")
    : t("sources.mempool.targetTx");
  // Host in zweiter Zeile — native title zeigt Zeilenumbruch.
  link.title = `${kopf}\n${zielArt}\n${instanz.host}`;
  // stopPropagation: Zeile/Baum nicht aufklappen.
  // preventDefault auf dem Bubbling reicht nicht gegen <label>-Toggle —
  // deshalb defaultAction am Link belassen (Navigation), Label-Aktivierung
  // per stopImmediatePropagation + explizitem Fenster-Open vermeiden wir nicht;
  // Link liegt oft in label: Klick darf die Checkbox nicht umschalten.
  link.addEventListener("click", (e) => {
    e.stopPropagation();
    // In <label>: ohne preventDefault würde der Klick die Checkbox togglen.
    // Navigation bleibt über target=_blank + eigenem open, falls nötig.
    if (e.currentTarget.closest("label")) {
      e.preventDefault();
      window.open(link.href, "_blank", "noopener,noreferrer");
    }
  });
  return link;
}



/**
 * Grobe Client-Schätzung: öffentliche Clearnet-Domain vs. LAN/Loopback/Onion.
 * Server entscheidet final (mempool_info / outbound_policy).
 */

/** Entfernt Verweise aus bereits gezeichneten Ansichten. */
function verwerfeGezeichneteVerweise() {
  for (const link of document.querySelectorAll(".extern-link")) {
    link.remove();
  }
  if (Zustand.walletId) {
    // Neu laden, damit die Verweise mit der neuen Einstellung entstehen.
    zeigeWallet(Zustand.walletId).catch(() => {});
  }
}
