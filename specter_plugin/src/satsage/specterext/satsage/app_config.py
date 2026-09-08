"""
Eigene Specter-Server-Config für die SatSage-Testumgebung.

Start (nach `pip install -e specter_plugin`):
  python3 -m cryptoadvance.specter server \\
    --config satsage.specterext.satsage.app_config.DevConfig --debug
"""

from cryptoadvance.specter.config import DevelopmentConfig, ProductionConfig


def _with_satsage(base_list: list[str] | None) -> list[str]:
    ext = "satsage.specterext.satsage.service"
    out = list(base_list or [])
    if ext not in out:
        out.append(ext)
    return out


class DevConfig(DevelopmentConfig):
    """Development: API an, Alpha-Plugins, Extension explizit geladen.

    SERVICES_LOAD_FROM_CWD bleibt aus, damit die Extension nicht doppelt
    (CWD + EXTENSION_LIST) registriert wird → Flask-Name-Collision.
    """

    SERVICES_DEVSTATUS_THRESHOLD = "alpha"
    SERVICES_LOAD_FROM_CWD = False
    SPECTER_API_ACTIVE = True

    EXTENSION_LIST = _with_satsage(getattr(DevelopmentConfig, "EXTENSION_LIST", None))
    # SATSAGE_* kommt nur aus der Extension-config.py (Specter erlaubt kein Override)


class ProdLikeConfig(ProductionConfig):
    """Production-ähnlich, aber mit SatSage in EXTENSION_LIST (nur für Tests)."""

    SERVICES_DEVSTATUS_THRESHOLD = "alpha"
    SERVICES_LOAD_FROM_CWD = False
    SPECTER_API_ACTIVE = True
    EXTENSION_LIST = _with_satsage(getattr(ProductionConfig, "EXTENSION_LIST", None))
