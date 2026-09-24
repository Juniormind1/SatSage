"""Zentrale Allowlist für ausgehende Verbindungen.

Dünne Re-Export-Fassade. Fachcode liegt in ``core.outbound_policy``
(Slice 5 Schritt 11). Symbol-Identität: ``outbound_policy.X is core.outbound_policy.X``.
"""
from __future__ import annotations

import ssl

from core.outbound_policy import (
    OutboundPolicyError,
    _SESSION_OEFFENTLICHE_ELECTRUM,
    _price_service,
    _setting,
    _tls_insecure_context,
    _truthy,
    allowed_host,
    classify_host,
    ensure_host_allowed,
    ensure_resolves_to_allowed_host,
    ensure_url_allowed,
    normalize_host,
    oeffentliche_electrum_session_aktiv,
    public_opt_in,
    setze_oeffentliche_electrum_session,
    tls_context,
    tls_insecure_enabled,
)
