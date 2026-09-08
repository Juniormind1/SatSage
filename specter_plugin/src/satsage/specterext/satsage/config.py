"""Extension-spezifische Flask-Config.

Keys hier dürfen NICHT schon in der Server-Config (app_config.DevConfig)
stehen — Specter wirft sonst „tries to override existing key“.
"""


class BaseConfig:
    """Defaults der Extension (Production-ähnlich)."""

    SATSAGE_SHOW_SENSITIVE = False
    # Max. UTXOs/Txs in der UI-Vorschau
    SATSAGE_PREVIEW_LIMIT = 25


class DevelopmentConfig(BaseConfig):
    """Wird geladen, wenn Specter mit DevelopmentConfig / DevConfig startet."""

    SATSAGE_SHOW_SENSITIVE = True
    SATSAGE_PREVIEW_LIMIT = 50
