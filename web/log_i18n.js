/**
 * Log-Zeilen: Backend und Jobs liefern deutsch. Bei UI-Sprache EN
 * hier per Muster übersetzen. DE bleibt unverändert.
 *
 * Reihenfolge der Muster zählt — spezifischere zuerst.
 */
(() => {
  function lang() {
    if (window.SatSageI18n && typeof window.SatSageI18n.currentLang === "function") {
      return window.SatSageI18n.currentLang();
    }
    return "de";
  }

  /** @type {Array<[RegExp, string|((...a:string[])=>string)]>} */
  const MUSTER = [
    // --- Frontend / Jobs: Scan & Queue ---
    [/^Lade Block-Header ab SegWit \(Block 481\.824, August 2017\) — einmalig, für alle späteren Wallets\.$/,
      "Loading block headers from SegWit (block 481,824, August 2017) — one-time, for all later wallets."],
    [/^Lade Block-Header ab SegWit \(Block 481\.824, August 2017\) — (.*)$/,
      "Loading block headers from SegWit (block 481,824, August 2017) — $1"],
    [/^Header-Cache bei Block (.+) — prüfe Chain-Tip…$/,
      "Header cache at block $1 — checking chain tip…"],
    [/^Header-Cache aktuell bis Block (.+) \(Peer-Tip (.+)\)\.$/,
      "Header cache current up to block $1 (peer tip $2)."],
    [/^Header-Cache unverändert bis Block (.+)\.$/,
      "Header cache unchanged up to block $1."],
    [/^Prüfe (.+)…$/, "Checking $1…"],
    [/^Prüfe (.+)$/, "Checking $1"],
    [/^(\d+) Vorgänge · (.+)$/, "$1 events · $2"],
    [/^UTXO-Scan$/, "UTXO scan"],
    [/^Verlaufsscan$/, "History scan"],
    [/^(.+) für „(.+)“ läuft schon oder wartet\.$/, "$1 for “$2” already running or queued."],
    [/^(.+) für „(.+)“ angestellt\.$/, "$1 for “$2” queued."],
    [/^Starte (.+) für „(.+)“…$/, "Starting $1 for “$2”…"],
    [/^BIP-158 nicht vor (.+)\.$/, "BIP-158 not before $1."],
    [/^Browser darf geschlossen werden — Server und Scan laufen im Terminal weiter\.$/,
      "You can close the browser — server and scan continue in the terminal."],
    [/^Starte Scan neu für (.+)…$/, "Restarting scan for $1…"],
    [/^Starte Verlauf aller Wallets…$/, "Starting history for all wallets…"],
    [/^Herkunft vollständig für /, "Full origin for "],
    [/^Herkunft vollständig — noch /, "Full origin — still "],
    [/^Starte Herkunft aller UTXOs…$/, "Starting origin for all UTXOs…"],
    [/^Starte Verbindungstest…$/, "Starting connection test…"],
    [/^Start-Aktualisierung der Wallets…$/, "Start-up wallet refresh…"],
    [/^Start-Aktualisierung abgebrochen\.$/, "Start-up refresh cancelled."],
    [/^Start-Aktualisierung fertig: (\d+) Wallet\(s\), (.+) UTXO\(s\)\.$/,
      "Start-up refresh done: $1 wallet(s), $2 UTXO(s)."],
    [/^Start-Aktualisierung: (.+)$/, "Start-up refresh: $1"],

    // --- Kurse / Assistent ---
    [/^Hole Bitcoin-Kurs…$/, "Fetching Bitcoin price…"],
    [/^Kurs: (.+) \((.+)\)\.$/, "Price: $1 ($2)."],
    [/^Kurs: (.+)$/, "Price: $1"],
    [/^Importiere BTC\/(.+)-Kurs-CSV „(.+)“…$/, "Importing BTC/$1 rate CSV “$2”…"],
    [/^Kurs-CSV (.+): (\d+) Zeilen gelesen, (\d+) Tage im Cache(.*)$/,
      "Rate CSV $1: $2 rows read, $3 days in cache$4"],
    [/^Kurs-Import: (.+)$/, "Rate import: $1"],
    [/^Kurs-CSV ließ sich nicht lesen\.$/, "Could not read rate CSV."],
    [/^Prüfe Assistenten-Anbindung…$/, "Checking assistant connection…"],
    [/^Assistent: (.+)$/, "Assistant: $1"],
    [/^Assistent erreichbar\. (.+)$/, "Assistant reachable. $1"],
    [/^Assistent nicht erreichbar(.*)$/, "Assistant not reachable$1"],
    [/^Assistent nicht konfiguriert\.$/, "Assistant not configured."],
    [/^Frage Assistent…$/, "Asking assistant…"],

    // --- Öffentliche Electrum ---
    [/^Öffentliche Electrum-Server nur nach Bestätigung\.$/,
      "Public Electrum servers only after confirmation."],
    [/^Öffentliche Electrum-Server abgelehnt\.$/, "Public Electrum servers declined."],
    [/^Öffentliche Electrum-Server bestätigt — verbinde…$/,
      "Public Electrum servers confirmed — connecting…"],
    [/^Öffentliche Server: (.+)$/, "Public servers: $1"],
    [/^Öffentliche Electrum-Server nicht genutzt \(Bestätigung fehlt\)\.$/,
      "Public Electrum servers not used (confirmation missing)."],
    [/^Öffentliche Electrum-Server nicht angefragt(.*)$/, "Public Electrum servers not requested$1"],

    // --- Verbindung ---
    [/^Verbinde mit dem Sanktions-Server…$/, "Connecting to the sanctions server…"],
    [/^Verbinde mit der Datenquelle…$/, "Connecting to the data source…"],
    [/^Verbinde mit der Verlaufs-Datenquelle…$/, "Connecting to the history data source…"],
    [/^Verbinde mit (.+) über Tor$/, "Connecting to $1 via Tor"],
    [/^Verbinde mit (.+)$/, "Connecting to $1"],
    [/^Verbinde für (.+)…$/, "Connecting for $1…"],
    [/^Verbunden\. Compact-Filter-Peer (.+)$/, "Connected. Compact-filter peer $1"],
    [/^Verbunden\. Compact Filter (.+)$/, "Connected. Compact filter $1"],
    [/^Verbunden\. (\d+) öffentliche Electrum-Peers\.$/, "Connected. $1 public Electrum peers."],
    [/^Verbunden\. (.+ onion-electrs.*)\.$/, "Connected. $1."],
    [/^Verbunden\. (.+ clearnet-electrs.*)\.$/, "Connected. $1."],
    [/^Nur (.+ onion-electrs.*)\.$/, "Only $1."],
    [/^Nur (.+ clearnet-electrs.*)\.$/, "Only $1."],
    [/^Verbunden\. (\d+) Compact-Filter-(Peer|Peers) für den Scan\.$/,
      "Connected. $1 compact-filter $2 for the scan."],
    [/^Verbunden\. (\d+) Compact-Filter-Peers\.$/, "Connected. $1 compact-filter peers."],
    [/^Verbunden\. (.+)$/, "Connected. $1"],
    [/^Verbindung fehlgeschlagen (.+): (.+)$/, "Connection failed $1: $2"],
    [/^Verbindung fehlgeschlagen: kein Compact-Filter-Peer$/,
      "Connection failed: no compact-filter peer"],
    [/^Verbindung fehlgeschlagen: keine öffentlichen Electrum-Server$/,
      "Connection failed: no public Electrum servers"],
    [/^Verbindung fehlgeschlagen(.*)$/, "Connection failed$1"],
    [/^TLS-Handshake fehlgeschlagen(.*)$/, "TLS handshake failed$1"],
    [/^Port geschlossen(.*)$/, "Port closed$1"],
    [/^Zertifikat nicht überprüfbar(.*)$/, "Certificate not verifiable$1"],
    [/^Verbindung ohne TLS abgebrochen(.*)$/, "Connection without TLS aborted$1"],

    // --- Tor ---
    [/^Starte Tor \((.+)\) — SOCKS (.+)$/, "Starting Tor ($1) — SOCKS $2"],
    [/^Prüfe Tor-SOCKS (.+)…$/, "Checking Tor SOCKS $1…"],
    [/^Tor-SOCKS (.+) erreichbar$/, "Tor SOCKS $1 reachable"],
    [/^Tor-SOCKS (.+) lauscht auf (.+)$/, "Tor SOCKS $1 listening on $2"],
    [/^Tor-SOCKS lauscht auf (.+)$/, "Tor SOCKS listening on $1"],
    [/^Kein laufender Tor-SOCKS — suche Binary…$/, "No running Tor SOCKS — searching binary…"],
    [/^Tor für Core-RPC nicht bereit: (.+)$/, "Tor for Core RPC not ready: $1"],
    [/^Tor für P2P nicht bereit: (.+)$/, "Tor for P2P not ready: $1"],
    [/^Tor für öffentliche Onions nicht bereit: (.+)$/, "Tor for public onions not ready: $1"],
    [/^Tor hat nach (\d+)s noch keinen SOCKS-Port geöffnet\.(.*)$/,
      "Tor has not opened a SOCKS port after $1s.$2"],
    [/^Tor ist sofort beendet:(.*)$/, "Tor exited immediately:$1"],
    [/^Tor nicht erreichbar und nicht startbar\.$/, "Tor not reachable and not startable."],
    [/^Tor übersprungen — (.+) ist erreichbar\.$/, "Tor skipped — $1 is reachable."],
    [/^Tor: Kein SOCKS-Proxy — Tor Browser \(portable\) starten$/,
      "Tor: no SOCKS proxy — start Tor Browser (portable)"],
    [/^Kein Tor-Binary gefunden\.(.*)$/, "No tor binary found.$1"],
    [/^Clearnet-P2P ohne Compact-Filter-Peer — versuche über Tor…$/,
      "Clearnet P2P without compact-filter peer — trying via Tor…"],
    [/^(\d+) öffentliche Onions…$/, "$1 public onions…"],
    [/^(\d+) Clearnet-Server in der Liste, prüfe bis zu (\d+)…$/,
      "$1 clearnet servers in the list, checking up to $2…"],
    [/^Zuerst (.+), ohne Filter weitere Peers\.$/,
      "First $1, without filters more peers."],

    // --- Header / BIP-158 / Filter ---
    [/^Synchronisiere Block-Header…$/, "Syncing block headers…"],
    [/^Lade Block-Header ab SegWit \(Block 481\.824, August 2017\) — (.*)$/,
      "Loading block headers from SegWit (block 481,824, August 2017) — $1"],
    [/^Lade Block-Header ab SegWit \(Block 481\.824, August 2017\)…$/,
      "Loading block headers from SegWit (block 481,824, August 2017)…"],
    [/^Header-Cache fertig bis Block (.+)\.$/, "Header cache ready up to block $1."],
    [/^Header-Cache nachgezogen bis Block (.+)\.$/, "Header cache advanced to block $1."],
    [/^Header-Cache unverändert bis Block (.+)\.$/, "Header cache unchanged up to block $1."],
    [/^Header bis Block (.+) nachziehen…$/, "Catching up headers to block $1…"],
    [/^Header bis Block (.+)\.?$/, "Headers up to block $1."],
    [/^Header-Sync abgebrochen \((.+)\) — (.*)$/, "Header sync aborted ($1) — $2"],
    [/^P2P-Header-Vorab aus \(BIP158_P2P=0\)\.$/, "P2P header prefetch off (BIP158_P2P=0)."],
    [/^Frage Block-Header ab Höhe (.+) \(Checkpoint\)…$/,
      "Requesting block headers from height $1 (checkpoint)…"],
    [/^Frage Block-Header ab Höhe (.+)…$/, "Requesting block headers from height $1…"],
    [/^Filter über (\d+) Peers parallel…$/, "Filters over $1 peers in parallel…"],
    [/^Filter (\S+) Blöcke zu prüfen(.*)$/, "Filter $1 blocks to check$2"],
    [/^Filter Block (.+)–(.+)…$/, "Filter blocks $1–$2…"],
    [/^Filter Block (.+)–(.+)$/, "Filter blocks $1–$2"],
    [/^Inkrementell ab Block (.+): (.*)$/, "Incremental from block $1: $2"],
    [/^Filter-Treffer(.*)$/, "Filter hit$1"],
    [/^False Positive$/, "False positive"],
    [/^hole Block (.+) \((.+)…\) (.*)$/, "fetching block $1 ($2…) $3"],
    [/^hole Block (.+)$/, "fetching block $1"],
    [/^— hole Block…$/, "— fetching block…"],
    [/ — hole Block…$/, " — fetching block…"],
    [/^Chunk (.+)–(.+) fehlgeschlagen (.*)$/, "Chunk $1–$2 failed $3"],
    [/^Tx (.+)… über Core-RPC…$/, "Tx $1… via Core RPC…"],
    [/^Nur (\d+) Compact-Filter-(Peer|Peers) — Scan wird langsamer\.$/,
      "Only $1 compact-filter $2 — scan will be slower."],
    [/^Kein P2P-Peer mit Compact Filter gefunden(.*)$/,
      "No P2P peer with compact filters found$1"],
    [/^Suche bis zu (\d+) Compact-Filter-Peers…$/, "Searching up to $1 compact-filter peers…"],
    [/^Port 8333 wirkt blockiert(.*)$/, "Port 8333 appears blocked$1"],
    [/^Neuer Peer (.+)$/, "New peer $1"],
    [/^Peer (.+) ausgefallen(.*)$/, "Peer $1 failed$2"],
    [/^Wechsel: (.+)$/, "Switch: $1"],

    // --- UTXO / Gap / Scan ---
    [/^Frage UTXOs für (\d+) Adressen…$/, "Querying UTXOs for $1 addresses…"],
    [/^Frage UTXOs…$/, "Querying UTXOs…"],
    [/^Frage Verlauf für (\d+) Adressen — noch (\d+) von (\d+) Adressen$/,
      "Querying history for $1 addresses — $2 of $3 remaining"],
    [/^Frage Verlauf für (\d+) Adressen — (.*)$/, "Querying history for $1 addresses — $2"],
    [/^Gap-Scan (.+)-Adressen…$/, "Gap scan $1 addresses…"],
    [/^Gap-Scan (.*)Index #(\d+) · bisher (.+)$/, "Gap scan $1index #$2 · so far $3"],
    [/^Gap-Scan (.*)Index #(\d+) — darin (.+)$/, "Gap scan $1index #$2 — contains $3"],
    [/^Gap-Scan (.*)Index #(\d+)…$/, "Gap scan $1index #$2…"],
    [/^Suche benutzte Adressen von (.+)…$/, "Searching used addresses of $1…"],
    [/^Ermittle Wallet-Alter…$/, "Determining wallet age…"],
    [/^Wallet-Alter: Adresse (\d+) von (\d+)…$/, "Wallet age: address $1 of $2…"],
    [/^Prüfe Adresse (\d+) von (\d+)…$/, "Checking address $1 of $2…"],
    [/^Aktualisiere (.+) bis Chain-Tip…$/, "Updating $1 to chain tip…"],
    [/^(.+): Gap ab Index #(\d+)…$/, "$1: gap from index #$2…"],
    [/^(.+): Lookahead (\d+) Indizes…$/, "$1: lookahead $2 indices…"],
    [/^(.+): prüfe (\d+) bekannte Adressen…$/, "$1: checking $2 known addresses…"],
    [/^(.+): (\d+) UTXO\(s\) aktuell\.$/, "$1: $2 UTXO(s) current."],
    [/^(.+): (\d+) neue Gap-Adressen…$/, "$1: $2 new gap addresses…"],
    [/^scantxoutset läuft auf dem Node…$/, "scantxoutset running on the node…"],
    [/^scantxoutset: (\d+) UTXO\(s\) in (.+)s$/, "scantxoutset: $1 UTXO(s) in $2s"],
    [/^BIP-158: (\d+) unspent UTXO\(s\)(.*)$/, "BIP-158: $1 unspent UTXO(s)$2"],
    [/^BIP-158 Blockwalk für Verlauf(.*)$/, "BIP-158 block walk for history$1"],
    [/^BIP-158 Verlauf: (\d+) Ein- und Ausgänge$/, "BIP-158 history: $1 inflows and outflows"],
    [/^UTXO-Cache geladen: (.+)$/, "UTXO cache loaded: $1"],
    [/^UTXO-Cache nicht speicherbar: zu wenig freier Speicherplatz\.$/,
      "UTXO cache not writable: not enough free disk space."],
    [/^Kein UTXO-Cache(.*)$/, "No UTXO cache$1"],
    [/^Keine UTXOs(.*)$/, "No UTXOs$1"],

    // --- Verlauf / Herkunft ---
    [/^Starte Verlaufsscan für (.+)…$/, "Starting history scan for $1…"],
    [/^Verlaufsscan — eigene Datenquellen-Priorität…$/,
      "History scan — own data-source priority…"],
    [/^Verlauf: (.+)$/, "History: $1"],
    [/^Herkunft — noch (\d+) von (\d+) UTXOs$/, "Origin — $1 of $2 UTXOs remaining"],
    [/^Herkunft für (\d+) UTXOs$/, "Origin for $1 UTXOs"],
    [/^Herkunft (.+)$/, "Origin $1"],
    [/^Verfolge Herkunft über (.+)…$/, "Tracing origin via $1…"],
    [/^Speichere gründlichere Herkunft über (.+)…$/, "Saving deeper origin via $1…"],
    [/^Aktualisiere Herkunftsbaum…$/, "Updating origin tree…"],
    [/^Folgeanalyse: erst Herkunft, dann Vorgänger-Txs…$/,
      "Follow-up: origin first, then predecessor txs…"],
    [/^Transaktionsorientierte Folge-Analyse(.*)$/, "Transaction-oriented follow-up analysis$1"],
    [/^Nachziehen: alle eigenen Eingänge großer Sammel-Txs…$/,
      "Catch-up: all own inputs of large consolidation txs…"],
    [/^↻ Herkunft: Blockzeit zu (.+)…$/, "↻ Origin: block time for $1…"],
    [/^↻ Herkunft: lade Vorgänger-Output (.+)…$/, "↻ Origin: loading previous output $1…"],
    [/^Fortschritt: (\d+)% \((\d+)\/(\d+) UTXOs analysiert\)$/,
      "Progress: $1% ($2/$3 UTXOs analyzed)"],
    [/^Trace abgeschlossen: 100% \((\d+)\/(\d+) UTXOs\)(.*)$/,
      "Trace complete: 100% ($1/$2 UTXOs)$3"],
    [/^UTXO (\d+)\/(\d+) \((\d+)%\): (.*)$/, "UTXO $1/$2 ($3%): $4"],

    // --- Listen / Labels / Sanktionen ---
    [/^Lade Sanktions- und Blacklists…$/, "Loading sanctions and blacklists…"],
    [/^Lade Adress-Labels…$/, "Loading address labels…"],
    [/^(.+): (\d+) KB(.*)$/, "$1: $2 KB$3"],
    [/^Sanktions-Fulcrum \((.+)\): (.+)$/, "Sanctions Fulcrum ($1): $2"],
    [/^Sanktionsprüfung (.+)$/, "Sanctions check $1"],
    [/^Sanktionsliste Batch (.+)$/, "Sanctions list batch $1"],
    [/^Scanne UTXOs auf sanktionierten Adressen — (.*)$/,
      "Scanning UTXOs on sanctioned addresses — $1"],
    [/^Suche öffentliche Electrum-Server \(Clearnet\)…$/,
      "Searching public Electrum servers (clearnet)…"],
    [/^Suche geeignete Clearnet-Fulcrum-Server für Sanktionslisten(.*)$/,
      "Searching suitable clearnet Fulcrum servers for sanctions lists$1"],
    [/^Kein Fulcrum für Sanktionsabfragen erreichbar(.*)$/,
      "No Fulcrum reachable for sanctions queries$1"],

    // --- Datenquelle Status ---
    [/^Datenquelle: Bitcoin-P2P \(BIP-158 Compact Filter\)$/,
      "Data source: Bitcoin P2P (BIP-158 compact filter)"],
    [/^Datenquelle: eigener Electrum-Server \(LAN\) (.+)$/,
      "Data source: own Electrum server (LAN) $1"],
    [/^Datenquelle: eigener Electrum-Server \(Tor\) (.+)$/,
      "Data source: own Electrum server (Tor) $1"],
    [/^Datenquelle: öffentliche Electrum-Server(.*)$/,
      "Data source: public Electrum servers$1"],
    [/^Keine Datenquelle erreichbar(.*)$/, "No data source reachable$1"],
    [/^Moment noch(.*)$/, "Still working$1"],
    [/^anderes Wallet$/, "another wallet"],
  ];

  function übersetzeLogZeile(roh) {
    const text = String(roh ?? "");
    if (!text || lang() !== "en") return text;

    let out = text;
    for (const [re, repl] of MUSTER) {
      if (re.test(out)) {
        out = out.replace(re, repl);
        // Ein Treffer reicht oft; weitere Muster können Restteile fangen.
      }
    }
    // Restfragmente in gemischten Zeilen (nach den ganzen Mustern)
    out = out
      .replace(/\bfehlgeschlagen\b/g, "failed")
      .replace(/\babgebrochen\b/g, "cancelled")
      .replace(/\büber Tor\b/g, "via Tor")
      .replace(/\bohne TLS\b/g, "without TLS")
      .replace(/\bmit TLS\b/g, "with TLS")
      .replace(/\bnoch (\d+) von (\d+)\b/g, "$1 of $2 remaining")
      .replace(/\bMoment noch\b/g, "Still working");

    return out;
  }

  window.übersetzeLogZeile = übersetzeLogZeile;
  window.translateLogLine = übersetzeLogZeile;
})();
