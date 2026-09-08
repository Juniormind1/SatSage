"""Specter Extension: SatSage."""

from __future__ import annotations

import logging

from cryptoadvance.specter.services.service import Service, devstatus_alpha

logger = logging.getLogger(__name__)


class SatsageService(Service):
    id = "satsage"
    name = "SatSage"
    icon = "satsage/img/logo.png"
    logo = "satsage/img/logo.png"
    desc = "SatSage – know your sats. Herkunftsanalyse (Trace, Steuer, Cache) mit Specter-Wallets"
    has_blueprint = True
    blueprint_module = "satsage.specterext.satsage.controller"
    isolated_client = False
    devstatus = devstatus_alpha
    encrypt_data = False
    sort_priority = 50
