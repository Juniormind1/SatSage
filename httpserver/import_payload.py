"""Import-Payload-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations


def _dateien_aus_import_payload(payload: dict) -> dict[str, bytes]:
    """
    Body: ``files`` = [{name, data_b64|text}, …] oder {name: data_b64}.

    Base64 für Binär (Labels); Klartext ``text`` für Wallet-Exporte (CSV/Descriptor),
    damit der Browser große Dateien nicht unnötig base64-kodieren muss.
    """
    import base64

    from server import ApiError

    #: harte Grenze je Datei (Wallet-CSV/Descriptor) — ~25 MiB Rohbytes
    _max_bytes = 25 * 1024 * 1024

    roh = payload.get("files")
    ergebnis: dict[str, bytes] = {}
    if isinstance(roh, dict):
        eintraege = [(str(k), v, None) for k, v in roh.items()]
    elif isinstance(roh, list):
        eintraege = []
        for eintrag in roh:
            if not isinstance(eintrag, dict):
                continue
            name = str(eintrag.get("name") or "").strip()
            if not name:
                continue
            if eintrag.get("text") is not None:
                eintraege.append((name, None, str(eintrag.get("text") or "")))
            else:
                data = eintrag.get("data_b64") or eintrag.get("data") or ""
                eintraege.append((name, data, None))
    else:
        raise ApiError(400, "Feld „files“ fehlt oder ist ungültig.")

    for name, data, text in eintraege:
        name = str(name or "").strip()
        if not name:
            continue
        if text is not None:
            roh_bytes = text.encode("utf-8")
        else:
            if data is None:
                continue
            if not isinstance(data, str):
                raise ApiError(400, f"Datei {name}: data_b64 muss Text sein.")
            try:
                roh_bytes = base64.b64decode(data, validate=False)
            except Exception as exc:
                raise ApiError(400, f"Datei {name}: Base64 ungültig ({exc})") from exc
        if not roh_bytes:
            raise ApiError(400, f"Datei {name} ist leer.")
        if len(roh_bytes) > _max_bytes:
            raise ApiError(
                400,
                f"Datei {name} ist zu groß ({len(roh_bytes) // (1024 * 1024)} MiB, "
                f"max. {_max_bytes // (1024 * 1024)} MiB).",
            )
        # Gleicher Dateiname zweimal (txt+csv selten): Suffix, nicht überschreiben.
        schluessel = name
        if schluessel in ergebnis:
            n = 2
            while f"{name}#{n}" in ergebnis:
                n += 1
            schluessel = f"{name}#{n}"
        ergebnis[schluessel] = roh_bytes
    if not ergebnis:
        raise ApiError(400, "Keine Dateien im Upload.")
    return ergebnis
