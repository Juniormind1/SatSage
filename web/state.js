/** Zustand und Entwurf-Helfer — aus app.js extrahiert (Modularisierung UI-Schritt 2).
 * Klassisches Script: Globals (Zustand, entwurfGeaendert, walletZeileGeaendert).
 * Kein import/export.
 * Laden nach api.js, vor app.js (Formatierung u. a.), Views und chrome.
 */

// ---------------------------------------------------------------------------
// Zustand
// ---------------------------------------------------------------------------

const Zustand = {
  config: null,
  entwurf: [],        // bearbeitete Wallet-Liste (Einstellungen)
  walletSpeichernLaeuft: false,
  ansicht: "einstellungen",
  walletId: null,
  rescanJob: null,
  rescanTimer: null,
  scanArt: null,
  scanWalletId: null,
  scanWalletName: "",
  /** Server-Scan-Pipeline + andere Nutzer-Jobs (Nav). */
  jobsNav: { jobs: [], scan_pipeline: { current: null, queued: [] } },
  jobsNavFehler: "",
  jobsTimer: null,
  scanLogIndex: 0,
  scanLogStand: { index: 0, knoten: [], texte: [] },
  /** Bisherige UTXO-Zahl aus Job-Zwischenstand (während UTXO-Scan). */
  scanUtxoZahl: null,
  /** Zeitpunkt des letzten Wallet-/Nav-Refresh während Scan (ms). */
  scanRefreshUm: 0,
  scanRefreshLaeuft: false,
  peers: 0,
  peersGeprueft: false,
  peerLabel: "0 Peers verbunden",
  peerStatus: null,
  /** Hosts offener BIP-158-Scan-Peers (Tip-Sync), unabhängig vom Probe-Takt. */
  liveP2pPeers: [],
  peerTakt: null,
  peerTaktMs: null,
  peerCheckLaeuft: false,
  /** Laufender Sanktions-Hop-Check (UI nach Seitenwechsel wieder anbinden). */
  sanktionsCheckJobId: null,
  sanktionsCheckTimer: null,
  oeffentlicheGefragt: false,
  headerJob: null,
  headerTimer: null,
  headerLogStand: { index: 0 },
  walletSyncJob: null,
  walletSyncTimer: null,
  walletSyncLogStand: { index: 0 },
  /** Tip-Sync-Ziele (wallet_ids), sobald bekannt — gegen Cross-Wallet-Puls. */
  walletSyncWalletIds: [],
  /** Stiller Watch-Fallback-Tip: kein Nav-Marker / kein Empfangs-Puls. */
  walletSyncStill: false,
  /** "empfang" = UTXO-Tip fertig, QR-Schärfung läuft noch (Nav schon grün). */
  walletSyncPhase: null,
  /** Chain-Tip-Events vom Wallet-Watch (seq-Baseline gegen Reload-Flash). */
  blockEventSeq: 0,
  blockEventSeqInit: false,
  llmStatus: null,
  llmTimer: null,
  kurs: null,
  kursSerie: null,
  kursSerieLade: null,
  kursTimer: null,
  chatMessages: [],
  chatWartet: false,
  /** Empfangs-QR: letzte Adresse / Poll-Handle / Cache je Wallet. */
  empfang: null,
  empfangByWallet: Object.create(null),
  empfangTimer: null,
  empfangLadeGen: 0,
  /** Mempool-Pending-Zähler je Wallet für Animations-Trigger. */
  pendingByWallet: Object.create(null),
  /** Lernhinweise für Plebs (Experiment). */
  lernhinweise: null,
  lernThema: null,
  slashIndex: 0,
  traceJobs: new Map(),
  /** Massen-Herkunft (Steuerjahr klären / „Herkünfte UTXOs“) — Empfangs-Atem. */
  herkunftAlleLaeuft: false,
  /** Steuerjahr „Historien“ (Verlauf aller Wallets) — Empfangs-Atem. */
  verlaufAlleLaeuft: false,
  /** Wallet-„Herkunft“ (trace-tief) für diese Wallet-ID — Empfangs-Atem. */
  herkunftTiefWalletId: null,
  traceListe: null,
  /** Sprung aus Wallet: nur dieses UTXO — null = volle Herkunftsliste. */
  traceFokus: null,
  steuer: null,
  onchainHinweisSitzungWeg: false,
};

function entwurfGeaendert() {
  const original = Zustand.config?.wallets || [];
  if (Zustand.entwurf.length !== original.length) return true;
  // Neue Einträge (noch ohne id) zählen immer als Änderung.
  if (Zustand.entwurf.some((w) => w.is_new)) return true;
  const originalById = Object.create(null);
  for (const w of original) {
    if (w.id) originalById[w.id] = w;
  }
  for (const w of Zustand.entwurf) {
    const alt = originalById[w.id];
    if (!alt) return true;
    if (
      (w.name || "") !== (alt.name || "")
      || w.script_type !== alt.script_type
      || Number(w.max_addresses) !== Number(alt.max_addresses)
      || Boolean(w.read_only) !== Boolean(alt.read_only)
    ) {
      return true;
    }
  }
  return false;
}

/** Ob genau diese Zeile vom gespeicherten Stand abweicht. */
function walletZeileGeaendert(wallet) {
  if (!wallet) return false;
  if (wallet.is_new) return true;
  const alt = (Zustand.config?.wallets || []).find((w) => w.id === wallet.id);
  if (!alt) return true;
  return (
    (wallet.name || "") !== (alt.name || "")
    || wallet.script_type !== alt.script_type
    || Number(wallet.max_addresses) !== Number(alt.max_addresses)
    || Boolean(wallet.read_only) !== Boolean(alt.read_only)
  );
}

