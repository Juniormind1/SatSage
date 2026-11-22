# Issue: Passwort speichern hängt während P2P-Header-Abgleich?

**Status:** offen · Verdacht, nicht belegt · kein Blocker für 1.0.2 (2026-11-22)
**Ort:** `api_save_app_password` (`httpserver/api/auth_session.py`), Header-Vorab (`server.py` `starte_header_vorab`, `core/bip158_scan.py` `vorab_block_header`, `core/p2p.py` `hole_header` mit `_HEADER_LOCK`), Test `scripts/webgui_passwort_flow.py` (Schritt `passwort_desktop`)

## Befund

CI an PR #5 (Release 1.0.2, Stand `e775aee`), Lauf 45011131229, Job `labor / gui`, beide Versuche (10:11 und 10:22 UTC, 11:11 und 11:22 MEZ): Der Schritt `passwort_desktop` wartet 60 Sekunden darauf, dass „Speichere Passwort…“ verschwindet, und scheitert mit `Page.wait_for_function: Timeout 60000ms exceeded`. Specter und Umbrel nutzen dieselbe Seite mit denselben Augen-Knöpfen und laufen grün. Das Auge ist es also sehr wahrscheinlich nicht.

- Die Wegwerf-Server des Userflows hatten kein `BIP158_P2P=0`. Beim Start lädt SatSage Block-Header vorab. Der GitHub-Runner erreicht Port 8333, die Server haben sich deshalb mit echten Mainnet-Peers verbunden (Versuch 1: `98.29.240.189`, Versuch 2: `72.93.238.12`, dann `96.35.228.28`). Ein Test darf Mainnet nicht anfragen.
- Im Log stehen Tracebacks aus `hole_header` → `HeaderChain.sync` → `peer.recv(timeout=60)` → `_recv_exact`. Ein Peer kann die Verbindung also bis zu 60 Sekunden pro Nachricht offen halten.
- Ob das Speichern tatsächlich auf den Header-Abgleich wartet (etwa über `_HEADER_LOCK`, einen Reload des Zustands oder volle Verbindungen des Browsers), ist nicht belegt. Es fehlte ein Thread-Dump.
- Lokal (ohne Mainnet) ist der Userflow grün, auch mit `BIP158_P2P=0`. Zwei Nachbauten mit einem künstlich hängenden Header-Abgleich blieben ebenfalls grün. Der Hänger hängt also vom Verhalten fremder Peers ab.
- Der Schritt hat schon vor 1.0.1 gewackelt. Damals wurde die Wartezeit von 15 auf 60 Sekunden erhöht und der Userflow-Server vor den Passwort-Zyklen angehalten.

## Was geändert ist (Test, nicht Produkt)

- Beide Wegwerf-Server (`webgui_userflow.py` und `webgui_passwort_flow.py`) bekommen `BIP158_P2P=0`. Der Test hängt nicht mehr vom Internet ab.
- Scheitert ein Schritt mit Timeout, schreibt der Userflow einen Thread-Dump aller Threads ins Log (`faulthandler`, zwischen `=== Thread-Dump (…) ===` und `=== Ende Thread-Dump ===`). Die Testserver laufen im selben Prozess, der Dump zeigt also auch die wartende Anfrage. Kein Endpoint, nichts im Produktivserver.

## Offene Frage

Kann das Speichern des App-Passworts bei echten Desktop-Nutzern hängen, solange der Header-Abgleich nach dem Start läuft oder ein Peer langsam antwortet? Desktop ist der einzige Modus, der beim Setzen auch die `.env` scrambelt und den Zustand neu lädt.

## Diagnose

1. Im Test-Log nach `=== Thread-Dump` suchen. Steht der Thread von `api_save_app_password` (oder vom Scramble/`reload`) in einem `acquire` und hält ein anderer Thread `hole_header`/`HeaderChain.sync`, ist der Verdacht bestätigt.
2. Nachbau nur mit Regtest-Peer oder einem lokalen Fake-Peer, der Antworten verzögert (kein Mainnet): Desktop-Server mit P2P an, Passwort setzen, während der Abgleich läuft.
3. Bestätigt: Das Speichern darf nicht auf den Header-Abgleich warten (Lock nicht teilen, Abgleich beim Reload nicht blockierend anhalten). Test in `tests/` mit einem Fake-Peer.
