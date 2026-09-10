"""Zentrale Allowlist für ausgehende Verbindungen."""
from __future__ import annotations

import ipaddress
import os
import ssl
import warnings
from urllib.parse import urlparse


class OutboundPolicyError(ValueError):
    """Ein Ziel ist nach der Outbound-Policy nicht zulässig."""


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
    # sonst blockiert die Allowlist Clearnet-IPs trotz OEFFENTLICHE_ELECTRUM=1.
    if service_key in ("", "FULCRUM", "ELECTRUM"):
        keys.append("OEFFENTLICHE_ELECTRUM")
    return any(_truthy(_setting(values, key)) for key in keys)


def allowed_host(host: str, *, service: str = "", values=None, opt_in=None) -> bool:
    if classify_host(host) != "public":
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
