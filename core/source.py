"""
Datenquellen: Konfiguration und Erreichbarkeit — ohne Prompts.

Die automatische Priorität aus main._setup_blockchain_client ist heute
implizites Verhalten. Hier wird sie beschreibbar, damit die Oberfläche zeigen
kann, worüber gerade gefragt wird und was das für die Privatsphäre bedeutet.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

import main
from check_fulcrum_tor import ELECTRUM_SERVERS_URL, splitte_electrum_server

#: Reihenfolge wie in main._setup_blockchain_client.
PRIVACY_HIGH = "hoch"
PRIVACY_MEDIUM = "mäßig"
PRIVACY_LOW = "gering"


#: Welche .env-Schlüssel eine Quelle bearbeiten darf.
#:
#: Positivliste, kein Filter: Ohne sie wäre der Bearbeiten-Endpunkt ein
#: Schreibzugriff auf beliebige Einträge der .env.
EDITIERBARE_FELDER: dict[str, tuple[str, ...]] = {
    "own_fulcrum": ("FULCRUM_HOST", "FULCRUM_TOR", "FULCRUM_PORT",
                    "FULCRUM_SSL", "FULCRUM_TOR_PROXY"),
    # scantxoutset am eigenen bitcoind — schneller UTXO-Bestand, kein Verlauf.
    "own_core": ("NODE_IP", "RPCPORT", "RPCUSER", "RPCPASSWORD", "RPC_SSL",
                 "FULCRUM_TOR_PROXY"),
    "bip158": ("BIP158_P2P", "BIP158_START_HEIGHT", "BIP158_PEERS",
               "FULCRUM_TOR_PROXY"),
    "public_onion": ("FULCRUM_TOR_LISTE", "FULCRUM_TOR_PROXY"),
}

#: Schlüssel, deren Wert die Oberfläche nie zu sehen bekommt.
GEHEIME_FELDER = ("RPCPASSWORD",)


def verbindungsversuch_kommentar(erfolg: bool, wann: datetime | None = None) -> str:
    """Eine .env-Kommentarzeile zum letzten Core-/RPC-Versuch."""
    zeit = wann or datetime.now()
    return (
        f"# {'Erfolgreicher' if erfolg else 'Erfolgloser'} "
        f"Verbindungsversuch am {zeit.strftime('%d.%m.%Y')} "
        f"um {zeit.strftime('%H:%M')}"
    )


def merke_verbindungsversuch(env, werte: dict[str, str], *, timeout: float = 3.0) -> bool | None:
    """Früher Core-RPC-Kommentar. P2P braucht keine Zugangsdaten — no-op."""
    return None


@dataclass
class Feld:
    """Ein bearbeitbares Konfigurationsfeld."""

    key: str
    label: str
    typ: str = "text"          # text | port | schalter | geheim | liste
    value: str = ""
    hinweis: str = ""
    gesetzt: bool = False

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "typ": self.typ,
            # Geheimnisse verlassen den Server nicht — nur die Angabe, ob
            # überhaupt etwas hinterlegt ist.
            "value": "" if self.typ == "geheim" else self.value,
            "gesetzt": self.gesetzt,
            "hinweis": self.hinweis,
        }


@dataclass
class SourceInfo:
    """Ein Eintrag der Prioritätskette."""

    rank: int
    key: str
    name: str
    detail: str
    privacy: str
    configured: bool
    note: str = ""
    reachable: bool | None = None
    error: str = ""
    peer_count: int = 0
    peer_hosts: list[str] = field(default_factory=list)
    felder: list[Feld] = field(default_factory=list)
    #: Wenn gesetzt, zeigt die Oberfläche „Von Electrum laden“.
    laden_url: str = ""
    laden_filter: str = ""  # onion | clearnet | ""
    #: Zeilen für den Log-Bereich. Ankündigung vor dem Schritt, nicht danach.
    log: list[str] = field(default_factory=list)

    @property
    def editierbar(self) -> bool:
        return bool(self.felder)

    @property
    def verwerfbar(self) -> bool:
        """Eigene Nodes streichen oder P2P ausschalten (BIP158_P2P=0)."""
        return self.key in ("own_fulcrum", "own_core", "bip158") and self.configured

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "key": self.key,
            "name": self.name,
            "detail": self.detail,
            "privacy": self.privacy,
            "configured": self.configured,
            "note": self.note,
            "reachable": self.reachable,
            "error": self.error,
            "peer_count": self.peer_count,
            "peer_hosts": list(self.peer_hosts),
            "editierbar": self.editierbar,
            "verwerfbar": self.verwerfbar,
            "felder": [f.as_dict() for f in self.felder],
            "laden_url": self.laden_url,
            "laden_filter": self.laden_filter,
            "log": list(self.log),
        }


def mergere_erreichbarkeit(
    frisch: list[SourceInfo],
    alt: list[dict] | None,
) -> list[SourceInfo]:
    """
    Übernimmt ``reachable``/Peers aus dem letzten Check in frische describe-Daten.

    Damit ``GET /api/config`` (ohne Netzprobe) denselben Stand zeigen kann wie
    nach dem letzten ``?check=1`` — Browser-Reload muss Verbindungen nicht
    optisch „neu aufbauen“.
    """
    if not alt:
        return list(frisch)
    nach: dict[str, dict] = {}
    for eintrag in alt:
        if isinstance(eintrag, dict) and eintrag.get("key"):
            nach[str(eintrag["key"])] = eintrag
    out: list[SourceInfo] = []
    for q in frisch:
        alt_q = nach.get(q.key)
        if not alt_q:
            out.append(q)
            continue
        if not q.configured:
            out.append(
                replace(
                    q,
                    reachable=None,
                    error="",
                    peer_count=0,
                    peer_hosts=[],
                )
            )
            continue
        if q.reachable is not None:
            out.append(q)
            continue
        hosts = list(alt_q.get("peer_hosts") or [])
        out.append(
            replace(
                q,
                reachable=alt_q.get("reachable"),
                error=str(alt_q.get("error") or ""),
                peer_count=int(alt_q.get("peer_count") or 0),
                peer_hosts=hosts,
            )
        )
    return out


def anreichere_live_p2p(quellen: list) -> list:
    """
    Hängt gerade offene BIP-158-Scan-Peers an die bip158-Quelle.

    Tip-Nachzug / Filter-Walk halten Connections, die der periodische
    Erreichbarkeits-Check nicht sieht — die Pille soll sie trotzdem zählen.
    Nur wenn P2P konfiguriert/an ist (``BIP158_P2P``), sonst bleibt die
    Quelle nach Papierkorb/Schalter-Aus grau und ohne „verbunden“.
    """
    try:
        from bip158_scanner import live_filter_peer_hosts

        live = live_filter_peer_hosts()
    except Exception:
        live = []
    if not live:
        return list(quellen)
    out: list = []
    for q in quellen:
        if getattr(q, "key", None) != "bip158":
            out.append(q)
            continue
        # P2P aus (Papierkorb / Schalter): keine Live-Peers anzeigen.
        if not getattr(q, "configured", False):
            out.append(q)
            continue
        alt_hosts = list(getattr(q, "peer_hosts", None) or [])
        hosts: list[str] = []
        for h in alt_hosts + list(live):
            if h and h not in hosts:
                hosts.append(h)
        n = max(int(getattr(q, "peer_count", 0) or 0), len(hosts))
        if isinstance(q, SourceInfo):
            out.append(
                replace(
                    q,
                    reachable=True,
                    peer_count=n,
                    peer_hosts=hosts,
                    error="",
                )
            )
        else:
            # Tests / einfache Namespace-Objekte
            try:
                q.reachable = True
                q.peer_count = n
                q.peer_hosts = hosts
                if hasattr(q, "error"):
                    q.error = ""
            except Exception:
                pass
            out.append(q)
    return out


def peer_status(
    quellen: list[SourceInfo],
    values: dict[str, str] | None = None,
) -> dict:
    """
    Kopfzeilen-Pille: welche Sorte Peer und wie viele.

    Eigener Electrum-Server sticht Compact Filter, die wieder öffentliche
    Server. Die Zahl ist nur die der gewählten Sorte, nicht die Summe.
    """
    quellen = anreichere_live_p2p(quellen)
    nach = {q.key: q for q in quellen}

    def _hosts(q) -> list[str]:
        if q is None:
            return []
        return list(getattr(q, "peer_hosts", None) or [])

    stand = {
        "kind": "none",
        "count": 0,
        "label": "0 Peers verbunden",
        "peers": [],
    }
    own = nach.get("own_fulcrum")
    core = nach.get("own_core")
    if own and own.reachable:
        stand = {
            "kind": "own",
            "count": 1,
            "label": "Eigener Peer verbunden",
            "peers": _hosts(own),
        }
    elif core and core.reachable:
        stand = {
            "kind": "own",
            "count": 1,
            "label": "Eigener Peer verbunden",
            "peers": _hosts(core),
        }
    else:
        p2p = nach.get("bip158")
        if p2p and p2p.peer_count > 0:
            n = p2p.peer_count
            stand = {
                "kind": "p2p",
                "count": n,
                "label": "1 Peer verbunden" if n == 1 else f"{n} Peers verbunden",
                "peers": _hosts(p2p),
            }
        else:
            public_hosts: list[str] = []
            public = 0
            for key in ("public_onion", "clearnet"):
                q = nach.get(key)
                if q:
                    public += getattr(q, "peer_count", 0) or 0
                    public_hosts.extend(_hosts(q))
            if public > 0:
                stand = {
                    "kind": "public",
                    "count": public,
                    "label": (
                        "1 öffentlicher Peer verbunden"
                        if public == 1
                        else f"{public} öffentliche Peers verbunden"
                    ),
                    "peers": public_hosts,
                }
    stand["braucht_oeffentliche"] = (
        stand["count"] == 0
        and not oeffentliche_electrum_erlaubt(values)
        and hat_oeffentliche_electrum_listen(values)
    )
    return stand


def oeffentliche_electrum_erlaubt(values: dict[str, str] | None) -> bool:
    """Öffentliche Electrum-Server (Onion/Clearnet) nur nach Bestätigung."""
    return _flag(values or {}, "OEFFENTLICHE_ELECTRUM", False)


def hat_oeffentliche_electrum_listen(values: dict[str, str] | None) -> bool:
    values = values or {}
    for i in range(main.MAX_PUBLIC_ONION_SERVERS):
        if values.get(f"FULCRUM_TOR_{i}", "").strip():
            return True
    return main.ELECTRUM_SERVERS_FILE.is_file()


def peer_aenderungen(vorher: dict | None, nachher: dict) -> list[str]:
    """
    Log-Zeilen, wenn Peers ausfallen, dazukommen oder die Sorte wechselt.

    Beim ersten Stand (vorher None) keine Zeilen — das ist der Start, kein Wechsel.
    """
    if not vorher:
        return []
    alt_art = vorher.get("kind") or "none"
    neu_art = nachher.get("kind") or "none"
    alt_label = vorher.get("label") or "0 Peers verbunden"
    neu_label = nachher.get("label") or "0 Peers verbunden"
    if alt_art != neu_art:
        if (vorher.get("count") or 0) or (nachher.get("count") or 0):
            return [f"Wechsel: {alt_label} → {neu_label}"]
        return []
    alt = set(vorher.get("peers") or [])
    neu = set(nachher.get("peers") or [])
    zeilen: list[str] = []
    for host in sorted(alt - neu):
        zeilen.append(f"Peer {host} ausgefallen.")
    for host in sorted(neu - alt):
        zeilen.append(f"Neuer Peer {host}.")
    return zeilen


def _flag(values: dict[str, str], key: str, default: bool = False) -> bool:
    raw = values.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "ja", "on")


def _int(values: dict[str, str], key: str, default: int) -> int:
    try:
        return int(values.get(key, "").strip())
    except (ValueError, TypeError):
        return default


def describe_sources(values: dict[str, str]) -> list[SourceInfo]:
    """Beschreibt die Prioritätskette anhand der .env — ohne Netzzugriff."""
    quellen: list[SourceInfo] = []

    host = values.get("FULCRUM_HOST", "").strip()
    tor = values.get("FULCRUM_TOR", "").strip()
    if host:
        host = main._normalize_fulcrum_host(host)
    if tor:
        tor = main._normalize_fulcrum_host(tor)
    port = _int(values, "FULCRUM_PORT", 50002)
    # 50001 ist bei Start9/electrs der Klartext-Port; 50002 typisch TLS.
    ssl_an = _flag(values, "FULCRUM_SSL", port != 50001)
    ziel = host or tor
    quellen.append(SourceInfo(
        rank=1,
        key="own_fulcrum",
        # Das Werkzeug spricht das Electrum-Protokoll — Fulcrum ist nur eine
        # Implementierung davon. electrs und ElectrumX funktionieren ebenso.
        # Die .env-Schlüssel heißen weiterhin FULCRUM_*, damit bestehende
        # Konfigurationen unverändert weiterlaufen.
        name="Eigener Electrum-Server",
        detail=f"{ziel}:{port} · {'mit TLS' if ssl_an else 'ohne TLS'}" if ziel else "nicht eingetragen",
        privacy=PRIVACY_HIGH,
        configured=bool(ziel),
        note="" if ziel else "Host eintragen — Fulcrum, electrs oder ElectrumX",
        felder=[
            Feld("FULCRUM_HOST", "Host im LAN", "text", host,
                 "IP oder Name, z. B. 192.168.1.50"),
            Feld("FULCRUM_TOR", "Onion-Adresse", "text", tor,
                 "optional, statt oder zusätzlich zum LAN-Host"),
            Feld("FULCRUM_PORT", "Port", "port", str(port),
                 "Fulcrum meist 50002 (TLS) oder 50001, electrs oft 50001"),
            Feld("FULCRUM_SSL", "TLS verwenden", "schalter",
                 "true" if ssl_an else "false",
                 "Start9-Onion auf Port 50001 meist ohne TLS; 50002 oft mit"),
            Feld("FULCRUM_TOR_PROXY", "Tor-SOCKS-Proxy", "text",
                 values.get("FULCRUM_TOR_PROXY", "").strip(),
                 "nur für .onion nötig, z. B. 127.0.0.1:9150"),
        ],
    ))

    # --- Bitcoin Core (scantxoutset) — schneller UTXO-Bestand ---------------
    node = (values.get("NODE_IP") or values.get("RPCHOST")
            or values.get("BITCOIN_RPC_HOST") or "").strip()
    if node:
        node = main._normalize_fulcrum_host(node)
    rpc_port = _int(values, "RPCPORT", 8332)
    rpc_user = values.get("RPCUSER", "").strip()
    rpc_cookie = values.get("RPC_COOKIE_FILE", "").strip()
    rpc_ssl = _flag(values, "RPC_SSL", False)
    # Start9-Tor-RPC oft Port 443 + TLS.
    if rpc_port == 443 and "RPC_SSL" not in values:
        rpc_ssl = True
    core_ok = bool(node and (rpc_user or rpc_cookie))
    core_detail = (
        f"{node}:{rpc_port} · {'TLS' if rpc_ssl else 'ohne TLS'}"
        + (" · Cookie" if rpc_cookie and not rpc_user else "")
        if core_ok else "nicht eingetragen"
    )
    quellen.append(SourceInfo(
        rank=2,
        key="own_core",
        name="Bitcoin Core · RPC",
        detail=core_detail,
        privacy=PRIVACY_HIGH,
        configured=core_ok,
        note=(
            "UTXO-Bestand per scantxoutset am eigenen bitcoind (LAN vor Onion). "
            "Electrs im LAN hat Vorrang — Gap-Scan ist oft schneller. Kein "
            "Verlauf und keine Herkunft aus Core; die bleiben bei Electrum "
            "oder BIP-158."
            if core_ok else
            "UTXO-Bestand per scantxoutset: Host (LAN oder .onion), Port, "
            "RPC-Benutzer und Passwort (oder Cookie-Datei). Ideal mit "
            "-txindex=1. Electrs im LAN bleibt schneller und hat Vorrang. "
            "Lokaler bitcoind auf derselben Maschine: Opt-in unter "
            "Datenquellen bzw. LOCAL_CORE_OPT_IN=1."
        ),
        felder=[
            Feld("NODE_IP", "Host", "text", node,
                 "IP im LAN oder rpc-onion.onion (Start9: RPC über Tor)"),
            Feld("RPCPORT", "RPC-Port", "port", str(rpc_port),
                 "8332 im LAN; bei Start9 über Tor oft 443"),
            Feld("RPCUSER", "Benutzer", "text", rpc_user,
                 "rpcuser aus bitcoin.conf bzw. Start9-RPC"),
            Feld("RPCPASSWORD", "Passwort", "geheim", "",
                 "Leer lassen behält das gespeicherte Passwort",
                 gesetzt=bool(values.get("RPCPASSWORD", "").strip())),
            Feld("RPC_COOKIE_FILE", "Cookie-Datei", "text", rpc_cookie,
                 "Optional: Pfad zu bitcoind .cookie statt User/Passwort"),
            Feld("RPC_SSL", "TLS verwenden", "schalter",
                 "true" if rpc_ssl else "false",
                 "LAN meist nein; Onion hinter TLS-Terminator oft ja"),
            Feld("FULCRUM_TOR_PROXY", "Tor-SOCKS-Proxy", "text",
                 values.get("FULCRUM_TOR_PROXY", "").strip(),
                 "nur für .onion-RPC, z. B. 127.0.0.1:9150"),
        ],
    ))

    start = _int(values, "BIP158_START_HEIGHT", main.DEFAULT_BIP158_START_HEIGHT)
    peers = values.get("BIP158_PEERS", "").strip()
    lan_host = values.get("FULCRUM_HOST", "").strip()
    p2p_an = values.get("BIP158_P2P", "1").strip().lower() not in (
        "0", "false", "nein", "off",
    )
    p2p_teile = [f"ab Block {start:,}".replace(",", ".")]
    if lan_host and not _host_ist_onion(lan_host):
        p2p_teile.append(f"Node im LAN {lan_host}")
    if peers:
        p2p_teile.append(f"{len(peers.splitlines())} extra Peers")
    p2p_teile.append("DNS-Seeds")
    quellen.append(SourceInfo(
        rank=3,
        key="bip158",
        name="Bitcoin-P2P · Compact Filter",
        detail=(
            " · ".join(p2p_teile)
            if p2p_an
            else "aus — öffentliche Listen können greifen"
        ),
        privacy=PRIVACY_HIGH,
        configured=p2p_an,
        note=(
            (
                "Zuerst der Node im LAN (P2P-Port 8333), dann extra Peers, "
                "dann DNS-Seeds. Ohne Compact Filter am eigenen Node werden "
                "andere Filter-Peers gesucht — nicht gleich öffentliche "
                "Electrum-Server. Adressen bleiben lokal."
            )
            if p2p_an
            else (
                "P2P ist aus. Wenn Onion- oder Clearnet-Listen geladen sind "
                "und öffentliche Electrum erlaubt ist, greifen die."
            )
        ),
        felder=[
            Feld(
                "BIP158_P2P",
                "P2P aufbauen",
                "checkbox",
                "true" if p2p_an else "false",
                "Nur wenn aktiv: Compact Filter über Bitcoin-P2P. "
                "Sonst können geladene öffentliche Listen greifen.",
            ),
            Feld("BIP158_START_HEIGHT", "Erster Scan-Block", "port", str(start),
                 "Vorgabe SegWit (481824). Blöcke davor werden nicht durchsucht."),
            Feld("BIP158_PEERS", "P2P-Peers", "text", peers,
                 "Optional extra host:port. Der Host im LAN wird zuerst "
                 "gefragt; ohne Filter folgen DNS-Seeds."),
            Feld("FULCRUM_TOR_PROXY", "Tor-SOCKS-Proxy", "text",
                 values.get("FULCRUM_TOR_PROXY", "").strip(),
                 "Nach fehlgeschlagenem Clearnet-P2P: laufender Tor Browser "
                 "(9150) oder Autostart des tor-Binary. LAN-IPs bleiben direkt."),
        ],
    ))

    onions = [v for k, v in values.items() if k.startswith("FULCRUM_TOR_") and v.strip()
              and k != "FULCRUM_TOR_PROXY"]
    proxy = values.get("FULCRUM_TOR_PROXY", "").strip() or "127.0.0.1:9050"
    quellen.append(SourceInfo(
        rank=4,
        key="public_onion",
        name="Öffentliche Onions",
        detail=f"{len(onions)} Server · SOCKS {proxy}" if onions else "keine eingetragen",
        privacy=PRIVACY_MEDIUM,
        configured=bool(onions),
        note="Rotation mildert das Risiko einzelner Server. Erst nach Bestätigung.",
        laden_url=ELECTRUM_SERVERS_URL,
        laden_filter="onion",
        felder=[
            Feld("FULCRUM_TOR_LISTE", "Onion-Adressen", "liste",
                 "\n".join(onions),
                 "Eine Adresse je Zeile, höchstens zehn. "
                 "„Von Electrum laden“ übernimmt Onion-Hosts aus der Liste."),
            Feld("FULCRUM_TOR_PROXY", "Tor-SOCKS-Proxy", "text", proxy,
                 "Tor Browser: 127.0.0.1:9150, Tor-Dienst: 127.0.0.1:9050"),
        ],
    ))

    clearnet_datei = main.ELECTRUM_SERVERS_FILE.is_file()
    clearnet_anzahl = 0
    if clearnet_datei:
        try:
            from check_fulcrum_tor import load_electrum_servers
            _onions, clear = splitte_electrum_server(
                load_electrum_servers(main.ELECTRUM_SERVERS_FILE)
            )
            clearnet_anzahl = len(clear)
        except (OSError, ValueError):
            clearnet_datei = False
    quellen.append(SourceInfo(
        rank=5,
        key="clearnet",
        name="Öffentliche Electrum-Server",
        detail=(
            f"{clearnet_anzahl} Clearnet-Server in electrum_servers.json"
            if clearnet_datei else "keine Liste"
        ),
        privacy=PRIVACY_MEDIUM,
        configured=clearnet_datei,
        note=(
            "Erst nach Bestätigung — Adressen gehen an Dritte."
            if clearnet_datei
            else "Noch keine Liste — „Von Electrum laden“ holt sie."
        ),
        laden_url=ELECTRUM_SERVERS_URL,
        laden_filter="clearnet",
    ))

    return quellen


def _host_ist_onion(host: str) -> bool:
    text = (host or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.split("/")[0].split(":")[0]
    return text.endswith(".onion")


def source_needs_tor(info: SourceInfo, values: dict[str, str]) -> bool:
    """True, wenn die Prüfung dieser Quelle einen SOCKS-Proxy starten würde."""
    if not info.configured:
        return False
    if info.key == "own_fulcrum":
        lan = values.get("FULCRUM_HOST", "").strip()
        onion = values.get("FULCRUM_TOR", "").strip()
        roh = lan or onion
        if not roh:
            return False
        return _host_ist_onion(main._normalize_fulcrum_host(roh))
    if info.key == "own_core":
        host = (
            values.get("NODE_IP")
            or values.get("RPCHOST")
            or values.get("BITCOIN_RPC_HOST")
            or ""
        ).strip()
        if not host:
            return False
        return _host_ist_onion(main._normalize_fulcrum_host(host))
    if info.key == "bip158":
        lan = values.get("FULCRUM_HOST", "").strip()
        if lan and not _host_ist_onion(lan):
            return False
        return bool(
            (values.get("FULCRUM_TOR_PROXY") or values.get("TOR_PROXY") or "").strip()
        )
    return False


def check_sources(
    quellen: list[SourceInfo],
    values: dict[str, str],
    *,
    timeout: int = 5,
    on_log=None,
    still: bool = False,
) -> list[SourceInfo]:
    """
    Prüft die eigenen Nodes.

    LAN zuerst — eigener Electrum-Server. Sobald der ohne Tor antwortet,
    wird kein SOCKS mehr angefasst. P2P-BIP-158 ist kein eigener Node und
    wird hier nicht als LAN-Core geprüft.
    """
    lan: list[SourceInfo] = []
    ueber_tor: list[SourceInfo] = []
    rest: list[SourceInfo] = []
    for quelle in quellen:
        if quelle.key == "own_fulcrum" and quelle.configured:
            if source_needs_tor(quelle, values):
                ueber_tor.append(quelle)
            else:
                lan.append(quelle)
        else:
            rest.append(quelle)

    log = None if still else on_log
    gefunden: dict[str, SourceInfo] = {}
    lan_ok: SourceInfo | None = None

    for quelle in lan:
        geprueft = check_reachable(quelle, values, timeout=timeout, on_log=log)
        gefunden[quelle.key] = geprueft
        if geprueft.reachable and lan_ok is None:
            lan_ok = geprueft

    for quelle in ueber_tor:
        if lan_ok is not None:
            text = (
                f"Tor übersprungen — {lan_ok.name} ist erreichbar."
            )
            if log:
                log(text)
            gefunden[quelle.key] = replace(
                quelle,
                log=[text],
                note=text,
            )
            continue
        gefunden[quelle.key] = check_reachable(
            quelle, values, timeout=timeout, on_log=log,
        )

    for quelle in rest:
        gefunden[quelle.key] = check_reachable(
            quelle, values, timeout=timeout, on_log=log,
        )

    own = gefunden.get("own_fulcrum")
    own_ok = bool(own and own.reachable)

    p2p = gefunden.get("bip158")
    if p2p is not None and p2p.configured:
        if own_ok:
            core = gefunden.get("own_core")
            core_ok = bool(core and core.reachable)
            if core_ok:
                # Ruhiger UI-Takt (~10 Min) zieht den Header-Tip nach.
                text = (
                    "P2P als Datenquelle nicht erforderlich; "
                    "Header-Tip wird nur selten nachgezogen."
                )
            else:
                text = (
                    "P2P als Datenquelle nicht erforderlich "
                    "(Electrs erreichbar)."
                )
            if log:
                log(text)
            gefunden["bip158"] = replace(p2p, log=[text], note=text)
        else:
            gefunden["bip158"] = _pruefe_p2p_peers(
                p2p, values, timeout=timeout, on_log=log,
            )

    p2p_ok = bool(
        gefunden.get("bip158") and gefunden["bip158"].peer_count > 0
    )
    if not own_ok and not p2p_ok:
        if oeffentliche_electrum_erlaubt(values):
            gefunden = _pruefe_oeffentliche_electrum(
                gefunden, values, timeout=timeout, on_log=log,
            )
        elif log:
            log(
                "Öffentliche Electrum-Server nicht angefragt "
                "(Bestätigung fehlt)."
            )
    else:
        # Höhere Quelle aktiv: öffentliche „verbunden“-Reste nicht stehen lassen.
        gefunden = _oeffentliche_electrum_als_ungenutzt(gefunden, on_log=log)

    return [gefunden[q.key] for q in quellen]


def _oeffentliche_electrum_als_ungenutzt(
    gefunden: dict[str, SourceInfo],
    *,
    on_log=None,
) -> dict[str, SourceInfo]:
    """Löscht stale Peer-Stand bei Onion/Clearnet, wenn P2P/Eigen aktiv ist."""
    note = "Nicht genutzt — höhere Privatsphäre-Quelle ist aktiv."
    geaendert = False
    for key in ("public_onion", "clearnet"):
        info = gefunden.get(key)
        if info is None:
            continue
        if not info.configured:
            continue
        if (
            info.reachable is None
            and not info.peer_count
            and not (info.peer_hosts or [])
        ):
            continue
        gefunden[key] = replace(
            info,
            reachable=None,
            peer_count=0,
            peer_hosts=[],
            error="",
            note=note,
        )
        geaendert = True
    if geaendert and on_log:
        on_log("Öffentliche Electrum-Verbindung nicht mehr aktiv (höhere Quelle).")
    return gefunden


def _oeffentliche_onion_endpunkte(values: dict[str, str]) -> list[tuple[str, int, bool]]:
    port_default = _int(values, "FULCRUM_PORT", 50002)
    ssl_default = _flag(values, "FULCRUM_SSL", port_default != 50001)
    endpunkte: list[tuple[str, int, bool]] = []
    for i in range(main.MAX_PUBLIC_ONION_SERVERS):
        roh = values.get(f"FULCRUM_TOR_{i}", "").strip()
        if not roh:
            continue
        host = main._normalize_fulcrum_host(roh)
        port = _int(values, f"FULCRUM_PORT_{i}", port_default)
        if values.get(f"FULCRUM_SSL_{i}", "").strip():
            ssl = _flag(values, f"FULCRUM_SSL_{i}", True)
        else:
            ssl = ssl_default
        endpunkte.append((host, port, ssl))
    return endpunkte


def _zaehle_electrum_endpunkte(
    endpunkte: list[tuple[str, int, bool]],
    *,
    timeout: float,
    tor_proxy: tuple[str, int] | None,
    on_log=None,
    limit: int = 8,
) -> list[str]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from fulcrum import connect_fulcrum

    auswahl = endpunkte[:limit]
    if not auswahl:
        return []
    for host, port, ssl in auswahl:
        if on_log:
            on_log(f"Verbinde mit {host}:{port}")

    def eines(ende: tuple[str, int, bool]):
        host, port, ssl = ende
        client, fehler = connect_fulcrum(
            host, port, use_ssl=ssl, timeout=int(timeout),
            tor_proxy=tor_proxy, require_listunspent=False,
        )
        if client:
            try:
                client.close()
            except Exception:
                pass
            return host, port, None
        return host, port, fehler or "fehlgeschlagen"

    treffer: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, len(auswahl))) as pool:
        futures = [pool.submit(eines, e) for e in auswahl]
        for fut in as_completed(futures):
            host, port, fehler = fut.result()
            if fehler is None:
                treffer.append(f"{host}:{port}")
                if on_log:
                    on_log(f"Verbunden. {host}:{port}")
            elif on_log:
                on_log(f"Verbindung fehlgeschlagen {host}:{port}: {fehler}")
    treffer.sort()
    return treffer


def _pruefe_oeffentliche_electrum(
    gefunden: dict[str, SourceInfo],
    values: dict[str, str],
    *,
    timeout: int,
    on_log=None,
) -> dict[str, SourceInfo]:
    """Öffentliche Onions und Clearnet zählen, wenn eigener Node und P2P fehlen."""

    def log(text: str) -> None:
        if on_log:
            on_log(text)

    log("Prüfe öffentliche Electrum-Server…")
    onions = _oeffentliche_onion_endpunkte(values)
    onion_hosts: list[str] = []
    if onions:
        from core.tor import TorFehler, stelle_tor_socks_bereit

        raw = values.get("FULCRUM_TOR_PROXY") or values.get("TOR_PROXY") or "127.0.0.1:9050"
        if ":" in raw:
            ph, pp = raw.rsplit(":", 1)
            konfiguriert = (ph, int(pp)) if pp.isdigit() else (raw, 9050)
        else:
            konfiguriert = (raw, 9050)
        try:
            tor_proxy = stelle_tor_socks_bereit(konfiguriert, env=values, log=log)
        except (TorFehler, ValueError) as exc:
            log(f"Tor für öffentliche Onions nicht bereit: {exc}")
            tor_proxy = None
        else:
            log(f"{len(onions)} öffentliche Onions…")
            onion_hosts = _zaehle_electrum_endpunkte(
                onions, timeout=min(float(timeout), 8.0),
                tor_proxy=tor_proxy, on_log=log,
            )

    clear_hosts: list[str] = []
    try:
        from check_fulcrum_tor import load_electrum_servers

        servers = load_electrum_servers(main.ELECTRUM_SERVERS_FILE)
        _onion_liste, clear = splitte_electrum_server(servers)
    except (OSError, ValueError):
        clear = []
    if clear:
        log(f"{len(clear)} Clearnet-Server in der Liste, prüfe bis zu 8…")
        clear_hosts = _zaehle_electrum_endpunkte(
            clear, timeout=min(float(timeout), 5.0),
            tor_proxy=None, on_log=log,
        )

    onion_info = gefunden.get("public_onion")
    if onion_info is not None:
        gefunden["public_onion"] = replace(
            onion_info,
            reachable=bool(onion_hosts) if onions else onion_info.reachable,
            peer_count=len(onion_hosts),
            peer_hosts=onion_hosts,
        )
    clear_info = gefunden.get("clearnet")
    if clear_info is not None:
        gefunden["clearnet"] = replace(
            clear_info,
            reachable=bool(clear_hosts) if clear else clear_info.reachable,
            peer_count=len(clear_hosts),
            peer_hosts=clear_hosts,
        )
    gesamt = len(onion_hosts) + len(clear_hosts)
    if gesamt:
        log(f"Verbunden. {gesamt} öffentliche Electrum-Peers.")
    else:
        log("Verbindung fehlgeschlagen: keine öffentlichen Electrum-Server")
    return gefunden


def _pruefe_p2p_peers(
    info: SourceInfo,
    values: dict[str, str],
    *,
    timeout: int,
    on_log=None,
) -> SourceInfo:
    """Compact-Filter-Peers zählen — nach dem eigenen Electrum-Server."""
    from core.p2p import p2p_peers_from_env, stelle_p2p_tor_bereit, zaehle_compact_filter_peers

    zeilen = list(info.log)

    def log(text: str) -> None:
        zeilen.append(text)
        if on_log:
            on_log(text)

    fest = p2p_peers_from_env(values)
    # Kein Vorlauf-Log — Erfolg kommt als eine Zeile je neuem Peer aus p2p.
    hosts = zaehle_compact_filter_peers(
        timeout=min(float(timeout), 4.0),
        tor_proxy=None,
        peers=fest or None,
        on_log=log,
        dns_fallback=True,
    )
    if not hosts:
        tor_proxy = stelle_p2p_tor_bereit(values, on_log=log)
        if tor_proxy:
            hosts = zaehle_compact_filter_peers(
                timeout=max(float(timeout), 8.0),
                tor_proxy=tor_proxy,
                peers=fest or None,
                on_log=log,
                dns_fallback=True,
            )
    n = len(hosts)
    return replace(
        info,
        reachable=n > 0,
        peer_count=n,
        peer_hosts=hosts,
        error="" if n else "kein Compact-Filter-Peer",
        log=zeilen,
    )


def _verbindung_ziel(
    host: str,
    port: int,
    use_ssl: bool,
    tor_proxy: tuple[str, int] | None = None,
) -> str:
    weg = "TLS" if use_ssl else "ohne TLS"
    if tor_proxy:
        weg += f", Tor {tor_proxy[0]}:{tor_proxy[1]}"
    return f"{host}:{port} ({weg})"


def check_reachable(
    info: SourceInfo,
    values: dict[str, str],
    *,
    timeout: int = 5,
    on_log=None,
) -> SourceInfo:
    """
    Prüft eine einzelne Quelle. Verändert *info* nicht, sondern liefert eine
    Kopie mit ausgefülltem reachable/error.

    Geprüft wird der eigene Electrum-Server (Fulcrum/electrs).
    P2P-BIP-158 und öffentliche Quellen kosten Verbindungen zu Dritten —
    das gehört nicht in einen beiläufigen Statuscheck.

    *on_log* wird bei jeder neuen Zeile aufgerufen — noch während SOCKS-Suche
    und Tor-Start laufen, nicht erst am Ende der Prüfung. Die Zeile selbst
    kommt *vor* dem Schritt (Erwartungsmanagement), nicht als Nachtrag.
    """
    ergebnis = replace(info, log=[])

    def log(text: str) -> None:
        ergebnis.log.append(text)
        if on_log:
            on_log(text)

    if info.key == "bip158":
        return ergebnis
    if info.key == "own_core":
        if not info.configured:
            return ergebnis
        from core.bitcoind_rpc import stelle_core_client_bereit, verify_core_rpc

        log(f"Prüfe {info.name}…")
        try:
            client = stelle_core_client_bereit(
                values, on_log=log, timeout=float(timeout) + 25.0,
            )
            if client is None:
                return replace(
                    ergebnis,
                    reachable=False,
                    error="nicht konfiguriert",
                    log=list(ergebnis.log),
                )
            info_chain = verify_core_rpc(client, on_log=log)
            tip = info_chain.get("blocks")
            host = client.cfg.host
            return replace(
                ergebnis,
                reachable=True,
                peer_count=1,
                peer_hosts=[f"{host}:{client.cfg.port}"],
                error="",
                detail=(
                    f"{client.cfg.ziel}"
                    + (f" · Tip {tip}" if tip is not None else "")
                ),
                log=list(ergebnis.log),
            )
        except Exception as exc:
            log(f"Verbindung fehlgeschlagen: {exc}")
            return replace(
                ergebnis,
                reachable=False,
                error=str(exc),
                log=list(ergebnis.log),
            )
    if info.key != "own_fulcrum" or not info.configured:
        return ergebnis

    lan = values.get("FULCRUM_HOST", "").strip()
    onion = values.get("FULCRUM_TOR", "").strip()
    roh = lan or onion
    host = main._normalize_fulcrum_host(roh) if roh else ""
    if lan:
        port = _int(values, "FULCRUM_PORT", 50002)
        use_ssl = _flag(values, "FULCRUM_SSL", port != 50001)
    else:
        port = _int(values, "FULCRUM_TOR_PORT", _int(values, "FULCRUM_PORT", 50002))
        if values.get("FULCRUM_TOR_SSL", "").strip():
            use_ssl = _flag(values, "FULCRUM_TOR_SSL", True)
        else:
            use_ssl = _flag(values, "FULCRUM_SSL", port != 50001)

    log(f"Prüfe {info.name}…")

    tor_proxy = None
    if host.endswith(".onion"):
        from core.tor import TorFehler, stelle_tor_socks_bereit
        from fulcrum import FULCRUM_ONION_TIMEOUT

        raw = values.get("FULCRUM_TOR_PROXY") or values.get("TOR_PROXY") or "127.0.0.1:9050"
        if ":" in raw:
            ph, pp = raw.rsplit(":", 1)
            konfiguriert = (ph, int(pp)) if pp.isdigit() else (raw, 9050)
        else:
            konfiguriert = (raw, 9050)
        try:
            tor_proxy = stelle_tor_socks_bereit(
                konfiguriert, env=values, log=log,
            )
        except (TorFehler, ValueError) as exc:
            ergebnis.reachable = False
            ergebnis.error = str(exc)
            log(f"Verbinde mit {_verbindung_ziel(host, port, use_ssl)}")
            log(f"Verbindung fehlgeschlagen: {exc}")
            return ergebnis
        if tor_proxy != konfiguriert:
            log(
                f"Fallback SOCKS {tor_proxy[0]}:{tor_proxy[1]} "
                f"(statt {konfiguriert[0]}:{konfiguriert[1]})"
            )
        timeout = max(timeout, FULCRUM_ONION_TIMEOUT)

    try:
        from fulcrum import connect_fulcrum

        log(f"Verbinde mit {_verbindung_ziel(host, port, use_ssl, tor_proxy)}")
        client, fehler = connect_fulcrum(
            host, port, use_ssl=use_ssl, timeout=timeout,
            tor_proxy=tor_proxy, require_listunspent=True,
        )
        # Start9-Onion auf 50001 spricht kein TLS — der GUI-Default „ja“
        # führt sonst zu WRONG_VERSION_NUMBER und „nicht erreichbar“.
        if (
            not client
            and use_ssl
            and host.endswith(".onion")
            and fehler
            and "wrong version number" in fehler.lower()
        ):
            log(f"TLS-Handshake fehlgeschlagen: {fehler}")
            log("Fallback: derselbe Port ohne TLS")
            use_ssl = False
            log(f"Verbinde mit {_verbindung_ziel(host, port, False, tor_proxy)}")
            client, fehler = connect_fulcrum(
                host, port, use_ssl=False, timeout=timeout,
                tor_proxy=tor_proxy, require_listunspent=True,
            )
            if client:
                ergebnis.note = (
                    "Verbunden ohne TLS — FULCRUM_SSL=false setzen "
                    "(Start9-Onion typisch)."
                )
    except Exception as exc:  # Import- oder Laufzeitfehler
        ergebnis.reachable = False
        ergebnis.error = str(exc)
        log(f"Verbindung fehlgeschlagen: {exc}")
        return ergebnis

    if client:
        ergebnis.reachable = True
        ergebnis.peer_count = 1
        ergebnis.peer_hosts = [f"{host}:{port}"]
        log(f"Verbunden. Privatsphäre: {ergebnis.privacy}")
        try:
            client.close()
        except Exception:
            pass
        return ergebnis

    ergebnis.reachable = False
    ergebnis.error = fehler or "unbekannter Fehler"
    log(f"Verbindung fehlgeschlagen: {ergebnis.error}")
    hinweis = main.connection_error_hint(fehler, use_ssl)
    if hinweis:
        ergebnis.note = hinweis
        log(hinweis)
    return ergebnis
