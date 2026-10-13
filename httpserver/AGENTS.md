# AGENTS.md — `httpserver/` und `server.py`

Gilt für `httpserver/` **und** für [`../server.py`](../server.py). Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

`server.py` ist die Web-Oberfläche: stdlib-HTTP, nur `127.0.0.1:8730`, Sitzungs-Token. Terminal-Steuerung liegt in `core/terminal_steuerung.py` (Browser darf zu; Job-Log wird gespiegelt). UI-Regeln: [`../web/AGENTS.md`](../web/AGENTS.md).

## Wohin neue HTTP-Logik kommt

- HTTP-Handler nach `httpserver/api/<domäne>.py` oder in den passenden Helfer unter `httpserver/`.
- `server.py` bleibt Bind, Sitzung, Static, dünner Dispatch und Re-Export.
- Neuer Code importiert `core.*` direkt. Root-Fassaden bleiben für Tests, Specter und Packaging. Eine Fassade in einem Feature-Commit nicht löschen.
- Eine neue Analyse-Funktion: Route hier, View in `web/views/`, Fachlogik in `core/`. `server.py` nur Dispatch.

## Sitzung und Token

- Nie Session-Token aus Logs greppen. Session-JSON und Helfer: [`../scripts/AGENTS.md`](../scripts/AGENTS.md).
- Key des Assistenten nie im Status. Der Assistent startet keinen Job (`core/llm_*`).

## Header-Vorab

`server.py` startet `starte_header_vorab`: Header ab SegWit in `p2p_headers.bin`, Job `headers` für das Log. Ist der Cache schon über SegWit, nur Tip-Nachzug. Das läuft, sobald P2P die einzige Bestandsquelle ist (`p2p_utxo_entdeckung_frei`), auch während `p2p_gesperrt()` wahr ist. Sockets dafür nur in `p2p_nur_header`. Herkunft, Verlauf und `get_tx` bleiben zu. Fachregeln: [`../core/AGENTS.md`](../core/AGENTS.md) und [`../doc/issues/p2p-herkunft.md`](../doc/issues/p2p-herkunft.md).
