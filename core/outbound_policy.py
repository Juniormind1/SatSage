"""Zentrale Allowlist für ausgehende Verbindungen.

Slice 5 Schritt 11. Die Sitzungs-Freigabe für öffentliche Electrum liegt
hier, damit ``core.source`` nicht importiert werden muss (kein Zyklus
``source`` ↔ ``outbound_policy``). Root-``outbound_policy`` re-exportiert.
"""
from __future__ import annotations

import ipaddress
import os
import ssl
import threading
import warnings
from urllib.parse import urlparse


class OutboundPolicyError(ValueError):
    """Ein Ziel ist nach der Outbound-Policy nicht zulässig."""


#: Sitzungs-Opt-in für öffentliche Electrum-Server (Web-GUI).
#: Gilt nur für den laufenden Prozess — nach Server-Neustart wieder aus.
_SESSION_OEFFENTLICHE_ELECTRUM = False

#: Laufende öffentliche Electrum-Probes (Clearnet/Onion-Stichprobe,
#: Wallet-Clearnet-Pool, Onion-Rotation) — nicht der Sanktions-Pool.
_OEFFENTLICHE_ELECTRUM_STOP = threading.Event()
_OEFFENTLICHE_ELECTRUM_PROZESS_ENDE = threading.Event()


def oeffentliche_electrum_session_aktiv() -> bool:
    """True wenn diese Prozess-Sitzung öffentliche Electrum freigegeben hat."""
    return bool(_SESSION_OEFFENTLICHE_ELECTRUM)


def setze_oeffentliche_electrum_session(erlaubt: bool) -> None:
    """Sitzungs-Freigabe setzen (kein Schreiben in die .env)."""
    global _SESSION_OEFFENTLICHE_ELECTRUM
    _SESSION_OEFFENTLICHE_ELECTRUM = bool(erlaubt)
    if erlaubt:
        erlaube_oeffentliche_electrum_suche()


def widerrufe_oeffentliche_electrum_freigabe() -> bool:
    """Sitzungs-Opt-in zurücknehmen. True, wenn sie aktiv war."""
    if not oeffentliche_electrum_session_aktiv():
        return False
    setze_oeffentliche_electrum_session(False)
    return True


def stoppe_oeffentliche_electrum_suche(*, prozess_ende: bool = False) -> None:
    """
    Bricht laufende öffentliche Electrum-Probes ab.

    Aufruf sobald der eigene Indexer verbunden ist, und beim Server-Ende
    (Taste 3 / Strg+C) — sonst wartet ``httpd.shutdown`` auf die Probe.
    """
    _OEFFENTLICHE_ELECTRUM_STOP.set()
    if prozess_ende:
        _OEFFENTLICHE_ELECTRUM_PROZESS_ENDE.set()


def erlaube_oeffentliche_electrum_suche() -> None:
    """Stopp lösen — Nutzer hat öffentliche Electrum erneut bestätigt."""
    if not _OEFFENTLICHE_ELECTRUM_PROZESS_ENDE.is_set():
        _OEFFENTLICHE_ELECTRUM_STOP.clear()


def oeffentliche_electrum_suche_abgebrochen() -> bool:
    """True, wenn öffentliche Wallet-Probes sofort enden sollen."""
    return (
        _OEFFENTLICHE_ELECTRUM_STOP.is_set()
        or _OEFFENTLICHE_ELECTRUM_PROZESS_ENDE.is_set()
    )


def oeffentliche_electrum_suche_prozess_ende() -> bool:
    """True nach Taste 3 / Strg+C — kein weiteres Probe-Log."""
    return _OEFFENTLICHE_ELECTRUM_PROZESS_ENDE.is_set()


def melde_oeffentliche_electrum_abbruch(log_fn=None) -> None:
    """
    Loggt den Abbruch nur, wenn ein privater Indexer die Suche beendet.

    Beim Prozess-Ende (Taste 3) bleibt es still — sonst steht nach
    „Beendet.“ noch „eigener Indexer verbunden“ in der Konsole.
    """
    if _OEFFENTLICHE_ELECTRUM_PROZESS_ENDE.is_set():
        return
    if log_fn is None:
        return
    log_fn("Öffentliche Electrum-Suche beendet — eigener Indexer verbunden.")


def futures_bis_oeffentliche_electrum_stopp(futures, *, poll_s: float = 0.2):
    """
    Liefert fertige Futures, bis alle durch sind oder die öffentliche
    Suche gestoppt wurde (privater Indexer / Job-Abbruch / Prozess-Ende).
    """
    from concurrent.futures import FIRST_COMPLETED, wait

    pending = set(futures)
    while pending:
        if oeffentliche_electrum_suche_abgebrochen():
            return
        try:
            from core.jobs import job_abgebrochen

            if job_abgebrochen():
                return
        except Exception:
            pass
        done, pending = wait(
            pending, timeout=max(0.05, float(poll_s)), return_when=FIRST_COMPLETED,
        )
        for fut in done:
            yield fut


def _reset_oeffentliche_electrum_suche_fuer_tests() -> None:
    """Nur Tests: Stopp-Flags zurücksetzen."""
    _OEFFENTLICHE_ELECTRUM_STOP.clear()
    _OEFFENTLICHE_ELECTRUM_PROZESS_ENDE.clear()


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "ja", "on")


def _setting(values: dict[str, str] | None, key: str) -> str:
    if values and values.get(key) is not None:
        return str(values.get(key) or "").strip()
    return str(os.environ.get(key, "") or "").strip()


def normalize_host(host: str) -> str:
    value = str(host or "").strip().lower().rstrip(".")
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    if value.count(":") == 1:
        name, port = value.rsplit(":", 1)
        if port.isdigit():
            value = name
    try:
        return ipaddress.ip_address(value).compressed.lower()
    except ValueError:
        return value


def classify_host(host: str) -> str:
    """Return ``loopback``, ``private``, ``onion`` or ``public``."""
    name = normalize_host(host)
    if not name:
        return "public"
    if name.endswith(".onion"):
        return "onion"
    if name in ("localhost", "localhost.localdomain"):
        return "loopback"
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback:
            return "loopback"
        if address.is_private or address.is_link_local:
            return "private"
        return "public"
    if (
        "." not in name
        or name.endswith((".local", ".lan", ".internal", ".home", ".home.arpa"))
        or name.endswith((".test", ".example", ".invalid", ".example.com"))
    ):
        return "private"
    return "public"


def public_opt_in(values: dict[str, str] | None = None, service: str = "") -> bool:
    """Whether public Clearnet is explicitly enabled for this service."""
    service_key = "".join(ch for ch in service.upper() if ch.isalnum())
    keys = ["SATSAGE_OUTBOUND_PUBLIC_OPT_IN", "OUTBOUND_PUBLIC_OPT_IN"]
    if service_key:
        keys.insert(0, f"SATSAGE_{service_key}_PUBLIC_OPT_IN")
    if service_key == "LLM":
        keys.append("LLM_REMOTE_OPT_IN")
    # Öffentliche Electrum (Onion/Clearnet) nach UI-Bestätigung —
    # Sitzung (Web) oder .env/CLI-Flag.
    if service_key in ("", "FULCRUM", "ELECTRUM"):
        if oeffentliche_electrum_session_aktiv():
            return True
        keys.append("OEFFENTLICHE_ELECTRUM")
    return any(_truthy(_setting(values, key)) for key in keys)


def _price_service(service: str) -> bool:
    """Spot/Historie: nur Fiat-Kurse, keine Wallet-Daten — immer freigegeben."""
    key = "".join(ch for ch in service.upper() if ch.isalnum())
    return key in ("PRICE", "PRICEHISTORY")


def allowed_host(host: str, *, service: str = "", values=None, opt_in=None) -> bool:
    if classify_host(host) != "public":
        return True
    # BTC/Fiat-Kurse (mempool.space Spot, Coinbase, Bitstamp/CDD, …):
    # vertrauenswürdige Kursquellen, kein Opt-in. CSV-Import bleibt optional.
    if _price_service(service):
        return True
    return public_opt_in(values, service) if opt_in is None else bool(opt_in)


def ensure_host_allowed(host: str, *, service: str = "", values=None, opt_in=None) -> str:
    normalized = normalize_host(host)
    if not normalized:
        raise OutboundPolicyError("Outbound-Ziel enthält keinen Host.")
    if not allowed_host(normalized, service=service, values=values, opt_in=opt_in):
        label = service or "dieser Dienst"
        raise OutboundPolicyError(
            f"Öffentliches Ziel „{normalized}“ für {label} ist blockiert. "
            "Öffentliche Ziele nur mit SATSAGE_OUTBOUND_PUBLIC_OPT_IN=1 "
            "(bzw. ausdrücklichem Dienst-Opt-in) verwenden."
        )
    return normalized


def ensure_url_allowed(url: str, *, service: str = "", values=None, opt_in=None) -> str:
    text = str(url or "").strip()
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    if parsed.scheme.lower() not in ("http", "https"):
        raise OutboundPolicyError("Outbound-Ziel darf nur http oder https verwenden.")
    try:
        host = parsed.hostname or ""
        parsed.port
    except ValueError as exc:
        raise OutboundPolicyError("Outbound-Ziel enthält einen ungültigen Port.") from exc
    ensure_host_allowed(host, service=service, values=values, opt_in=opt_in)
    return text


def tls_insecure_enabled(values=None) -> bool:
    return _truthy(_setting(values, "SATSAGE_TLS_INSECURE"))


def _tls_insecure_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def tls_context(values=None, *, host: str | None = None) -> ssl.SSLContext:
    """TLS-Kontext abhängig vom Zielhost.

    Desktop/Heimnetz (LAN, Loopback, Onion) behält die alte Praxis: TLS an,
    Zertifikat aber nicht gegen öffentliche CAs geprüft — typisch für Start9-
    LAN und selbst signierte Nodes. Öffentliche Clearnet-Hosts prüfen streng;
    ``SATSAGE_TLS_INSECURE=1`` ist die ausdrückliche Ausnahme auch dafür.

    Der Start9-Sideload spricht Electrs/Core ohnehin ohne TLS über die Bridge
    (``FULCRUM_SSL=false``) und braucht diesen Pfad nicht.
    """
    if tls_insecure_enabled(values):
        warnings.warn(
            "SATSAGE_TLS_INSECURE=1 aktiviert unsichere TLS-Zertifikatsprüfung "
            "(auch für öffentliche Ziele; nur Laborbetrieb).",
            RuntimeWarning,
            stacklevel=2,
        )
        return _tls_insecure_context()
    if host and classify_host(host) != "public":
        return _tls_insecure_context()
    return ssl.create_default_context()


def ensure_resolves_to_allowed_host(host: str, *, service: str = "", values=None, opt_in=None) -> str:
    """Connect-time hook; no DNS lookup here (avoids a validation TOCTOU)."""
    return ensure_host_allowed(host, service=service, values=values, opt_in=opt_in)
