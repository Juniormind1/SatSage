"""
HTTPS-CA-Kontext für stdlib-urllib.

macOS-/Framework-Python setzt oft ``cafile=None``; ohne explizites Bündel
scheitern Abrufe mit CERTIFICATE_VERIFY_FAILED. Derselbe Kontext für Kurs,
Labels und Sanktionslisten.
"""
from __future__ import annotations

import os
import ssl
from pathlib import Path

#: macOS System, Debian/Ubuntu, Homebrew.
_CA_KANDIDATEN = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/opt/homebrew/etc/openssl@3/cert.pem",
    "/usr/local/etc/openssl@3/cert.pem",
    # Python.org „Install Certificates.command“ legt hier ab, falls ausgeführt.
    "/Library/Frameworks/Python.framework/Versions/Current/etc/openssl/cert.pem",
)


def ssl_context() -> ssl.SSLContext:
    """SSL-Kontext mit brauchbarem CA-Bündel, falls das System keins setzt."""
    env = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    for pfad in (env, *_CA_KANDIDATEN):
        if not pfad:
            continue
        if not Path(pfad).is_file():
            continue
        try:
            return ssl.create_default_context(cafile=pfad)
        except ssl.SSLError:
            continue
    return ssl.create_default_context()
