"""
Neutrale Status-Mails bei Job-Ende (SMTP).

Datenschutz: Betreff und Body enthalten nur Ereignistyp, Status und Zeit —
keine Walletnamen, Beträge, TxIDs, Adressen, Job-Labels oder Fehlertexte.
"""
from __future__ import annotations

import smtplib
import ssl
import threading
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any
from outbound_policy import OutboundPolicyError, ensure_host_allowed, public_opt_in

#: Job-Arten, für die v1 Mails vorgesehen sind.
STATUS_MAIL_KINDS = frozenset({"rescan", "verlauf"})

KIND_LABEL = {
    "rescan": "UTXO-Scan",
    "verlauf": "Verlaufsscan",
}

STATUS_LABEL = {
    "done": "fertig",
    "failed": "fehlgeschlagen",
    "cancelled": "abgebrochen",
}

ENV_OPT_IN = "STATUS_MAIL_OPT_IN"
ENV_TO = "STATUS_MAIL_TO"
ENV_HOST = "SMTP_HOST"
ENV_PORT = "SMTP_PORT"
ENV_USER = "SMTP_USER"
ENV_PASSWORD = "SMTP_PASSWORD"
ENV_FROM = "SMTP_FROM"
ENV_STARTTLS = "SMTP_STARTTLS"


def _als_bool(roh: Any, *, default: bool = False) -> bool:
    if roh is None:
        return default
    if isinstance(roh, bool):
        return roh
    return str(roh).strip().lower() in ("1", "true", "ja", "yes", "on")


def lese_einstellungen(werte: dict[str, str] | None) -> dict[str, Any]:
    """Rohwerte aus der .env — inkl. Passwort nur serverseitig nutzen."""
    w = werte or {}
    port_roh = (w.get(ENV_PORT) or "587").strip() or "587"
    try:
        port = int(port_roh)
    except ValueError:
        port = 587
    return {
        "opt_in": _als_bool(w.get(ENV_OPT_IN)),
        "to": (w.get(ENV_TO) or "").strip(),
        "smtp_host": (w.get(ENV_HOST) or "").strip(),
        "smtp_port": port,
        "smtp_user": (w.get(ENV_USER) or "").strip(),
        "smtp_password": (w.get(ENV_PASSWORD) or "").strip(),
        "smtp_from": (w.get(ENV_FROM) or "").strip(),
        "starttls": _als_bool(w.get(ENV_STARTTLS), default=True),
        "outbound_public_opt_in": public_opt_in(w, "smtp"),
    }


def als_dict(werte: dict[str, str] | None) -> dict[str, Any]:
    """Für GET /api/config — ohne Passwort."""
    e = lese_einstellungen(werte)
    configured = bool(
        e["opt_in"] and e["to"] and e["smtp_host"] and e["smtp_from"]
    )
    return {
        "opt_in": e["opt_in"],
        "configured": configured,
        "to": e["to"],
        "smtp_host": e["smtp_host"],
        "smtp_port": e["smtp_port"],
        "smtp_user": e["smtp_user"],
        "smtp_from": e["smtp_from"],
        "smtp_password_set": bool(e["smtp_password"]),
        "starttls": e["starttls"],
        "kinds": sorted(STATUS_MAIL_KINDS),
    }


def darf_senden(werte: dict[str, str] | None, kind: str) -> bool:
    if kind not in STATUS_MAIL_KINDS:
        return False
    e = lese_einstellungen(werte)
    if not e["opt_in"]:
        return False
    if not (e["to"] and e["smtp_host"] and e["smtp_from"]):
        return False
    try:
        ensure_host_allowed(e["smtp_host"], service="smtp", opt_in=e["outbound_public_opt_in"])
    except OutboundPolicyError:
        return False
    return True


def baue_nachricht(
    kind: str,
    status: str,
    finished_at: float | None,
) -> tuple[str, str]:
    """
    Neutrale Betreff-/Body-Zeilen.

    Nur ``kind`` und ``status`` (Enums), kein Job-Label oder Fehlertext.
    """
    ereignis = KIND_LABEL.get(kind, "Vorgang")
    stand = STATUS_LABEL.get(status, "beendet")
    if finished_at:
        zeit = datetime.fromtimestamp(finished_at, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    else:
        zeit = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    betreff = f"SatSage: {ereignis} {stand}"
    body = (
        f"Ereignis: {ereignis}\n"
        f"Status: {stand}\n"
        f"Zeit: {zeit}\n"
    )
    return betreff, body


def _smtp_senden(einstellungen: dict[str, Any], betreff: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = betreff
    msg["From"] = einstellungen["smtp_from"]
    msg["To"] = einstellungen["to"]
    msg.set_content(body)

    host = einstellungen["smtp_host"]
    port = int(einstellungen["smtp_port"])
    user = einstellungen["smtp_user"]
    password = einstellungen["smtp_password"]
    starttls = bool(einstellungen["starttls"])
    ensure_host_allowed(
        host, service="smtp", opt_in=einstellungen.get("outbound_public_opt_in", False)
    )

    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        if starttls:
            context = ssl.create_default_context()
            smtp.starttls(context=context)
            smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


def sende_status_mail(
    werte: dict[str, str] | None,
    *,
    kind: str,
    status: str,
    finished_at: float | None,
) -> bool:
    """
    Synchroner Versand. Rückgabe True bei Erfolg.

    Ruft ``darf_senden`` erneut — Hook sollte das schon geprüft haben.
    """
    if not darf_senden(werte, kind):
        return False
    betreff, body = baue_nachricht(kind, status, finished_at)
    _smtp_senden(lese_einstellungen(werte), betreff, body)
    return True


def sende_status_mail_async(
    werte: dict[str, str] | None,
    *,
    kind: str,
    status: str,
    finished_at: float | None,
) -> None:
    """Versand im Hintergrund — blockiert den Job-Thread nicht."""

    def lauf() -> None:
        try:
            sende_status_mail(
                werte, kind=kind, status=status, finished_at=finished_at,
            )
        except Exception:
            # Keine Empfänger/Secrets in die Konsole.
            print("Status-Mail: Versand fehlgeschlagen.", flush=True)

    threading.Thread(
        target=lauf, name="status-mail", daemon=True,
    ).start()
