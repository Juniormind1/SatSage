"""
LLM-Anbindung: Konfiguration, Privatsphäre-Einstufung, Status für UI/API.

Phase 0: kein Chat, keine Tools, kein Job-Start. Nur lesen, einstufen und
optional den konfigurierten Endpoint kurz anpingen. Der API-Key erscheint
nirgends im Status — nur ``api_key_set``.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from outbound_policy import OutboundPolicyError, ensure_url_allowed

#: Bekannte Cloud-Hosts → klar „remote“, Label für Banner.
CLOUD_HOSTS = frozenset({
    "api.x.ai",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.groq.com",
    "openrouter.ai",
})

ANBIETER_WERTE = frozenset({"ollama", "lmstudio", "api-key"})
BETRIEB_WERTE = frozenset({"loopback", "lan", "remote", "onion"})

DATENMODUS = "nur lokaler Cache · keine Scans aus dem Chat"

#: Kurzer Timeout: Status-Refresh darf die Oberfläche nicht blockieren.
PROBE_TIMEOUT_S = 2.5


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    modell: str
    anbieter: str  # ollama | lmstudio | api-key | ""
    betrieb_deklaration: str  # loopback | lan | remote | onion | ""
    remote_opt_in: bool

    @property
    def configured(self) -> bool:
        return bool(self.base_url) or bool(self.anbieter) or bool(self.api_key)


def _truthy(wert: str | None) -> bool:
    return (wert or "").strip().lower() in ("1", "true", "yes", "ja", "on")


def lese_llm_einstellungen(werte: dict[str, str] | None) -> LlmConfig:
    """Liest Assistenten-Einstellungen aus der .env (oder gleichwertigem Dict)."""
    werte = werte or {}
    base = (werte.get("LLM_BASE_URL") or "").strip()
    key = (werte.get("LLM_API_KEY") or werte.get("XAI_API_KEY") or "").strip()
    modell = (werte.get("LLM_MODELL") or werte.get("LLM_MODEL") or "").strip()
    anbieter = (werte.get("LLM_ANBIETER") or "").strip().lower().replace("_", "-")
    if anbieter == "apikey":
        anbieter = "api-key"
    if anbieter not in ANBIETER_WERTE:
        anbieter = ""
    betrieb = (werte.get("LLM_BETRIEB") or "").strip().lower()
    if betrieb not in BETRIEB_WERTE:
        betrieb = ""
    opt_in = _truthy(werte.get("LLM_REMOTE_OPT_IN")) or _truthy(
        werte.get("LLM_OEFFENTLICH")
    )
    return LlmConfig(
        base_url=base,
        api_key=key,
        modell=modell,
        anbieter=anbieter,
        betrieb_deklaration=betrieb,
        remote_opt_in=opt_in,
    )


def lese_llm_chat_einstellungen(werte: dict[str, str] | None) -> LlmConfig:
    """Chat-Config nur aus dem übergebenen Dict (.env), nie aus ``os.environ``.

    ``LLM_API_KEY`` zuerst, sonst ``XAI_API_KEY`` als Alias für einen eigens
    in der .env hinterlegten Cloud-Key — nicht den Key der laufenden Sitzung.
    """
    cfg = lese_llm_einstellungen(werte)
    werte = werte or {}
    key = (werte.get("LLM_API_KEY") or werte.get("XAI_API_KEY") or "").strip()
    return LlmConfig(
        base_url=cfg.base_url,
        api_key=key,
        modell=cfg.modell,
        anbieter=cfg.anbieter,
        betrieb_deklaration=cfg.betrieb_deklaration,
        remote_opt_in=cfg.remote_opt_in,
    )


def basis_url(cfg: LlmConfig) -> str:
    """OpenAI-kompatible Basis ohne trailing slash."""
    text = (cfg.base_url or "").strip()
    if not text:
        if cfg.anbieter == "ollama":
            text = "http://127.0.0.1:11434/v1"
        elif cfg.anbieter == "lmstudio":
            text = "http://127.0.0.1:1234/v1"
        else:
            return ""
    if "://" not in text:
        text = "http://" + text
    return text.rstrip("/")


def betrieb_von(cfg: LlmConfig) -> str:
    host, _port, _schema = _host_aus_url(basis_url(cfg))
    if not host and cfg.anbieter in ("ollama", "lmstudio"):
        host = "127.0.0.1"
    betrieb, _ = betrieb_effektiv(cfg, host)
    return betrieb


def _host_aus_url(base_url: str) -> tuple[str, int | None, str]:
    """Liefert (hostname, port|None, schema). Leere URL → ("", None, "")."""
    text = (base_url or "").strip()
    if not text:
        return "", None, ""
    if "://" not in text:
        text = "http://" + text
    zerlegt = urlparse(text)
    host = (zerlegt.hostname or "").strip().lower()
    port = zerlegt.port
    schema = (zerlegt.scheme or "http").lower()
    return host, port, schema


def _ip_oder_none(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def klassifiziere_host(host: str) -> str:
    """
    Heuristik für den Endpoint-Host.

    Rückgabe: ``loopback`` | ``lan`` | ``remote`` | ``onion`` | ```` (leer).
    """
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return ""
    if host.endswith(".onion"):
        return "onion"
    if host in ("localhost", "localhost.localdomain"):
        return "loopback"
    adresse = _ip_oder_none(host)
    if adresse is not None:
        if adresse.is_loopback:
            return "loopback"
        if adresse.is_private or adresse.is_link_local:
            return "lan"
        # CGNAT / Shared (Tailscale o. ä.): nicht RFC1918-„private“, aber
        # auch kein öffentliches Ziel → wie LAN einstufen (gelb, nicht grün).
        if isinstance(adresse, ipaddress.IPv4Address) and adresse in ipaddress.ip_network(
            "100.64.0.0/10"
        ):
            return "lan"
        return "remote"
    if host in CLOUD_HOSTS or host.endswith(".openai.com") or host.endswith(".x.ai"):
        return "remote"
    # Unbekannter Hostname: konservativ remote (kein Grün ohne Loopback-IP).
    return "remote"


def rate_anbieter(cfg: LlmConfig, host: str, port: int | None) -> str:
    """Anbieter-Klasse: Deklaration, sonst Port-/Key-Heuristik."""
    if cfg.anbieter in ANBIETER_WERTE:
        return cfg.anbieter
    if port == 11434 or host in ("ollama.local",):
        return "ollama"
    if port == 1234:
        return "lmstudio"
    if cfg.api_key:
        return "api-key"
    if host in CLOUD_HOSTS:
        return "api-key"
    if cfg.base_url:
        # Lokaler Default ohne Key: eher Ollama-artig, sonst api-key-neutral.
        betrieb = klassifiziere_host(host)
        if betrieb == "loopback":
            return "ollama"
        return "api-key"
    return ""


def anbieter_label(anbieter: str) -> str:
    return {
        "ollama": "Ollama",
        "lmstudio": "LM Studio",
        "api-key": "API-Key",
        "": "nicht konfiguriert",
    }.get(anbieter, anbieter or "nicht konfiguriert")


def privacy_fuer_betrieb(betrieb: str) -> tuple[str, str]:
    """(stufe, Kurzlabel) — stufe leer wenn unkonfiguriert."""
    if betrieb == "loopback":
        return "hoch", "hoch (Loopback)"
    if betrieb == "lan":
        return "mittel", "mittel (LAN)"
    if betrieb == "onion":
        return "niedrig", "niedrig (Tor/Remote)"
    if betrieb == "remote":
        return "niedrig", "niedrig (Remote)"
    return "", ""


def betrieb_effektiv(cfg: LlmConfig, host: str) -> tuple[str, str | None]:
    """
    Effektiver Betrieb aus Heuristik und optionaler Deklaration.

    Bei Widerspruch (URL remote, Deklaration loopback) gewinnt die Heuristik;
    ``widerspruch`` erklärt das für Tooltip/Banner.
    """
    heuristik = klassifiziere_host(host) if host else ""
    dekl = cfg.betrieb_deklaration
    if not dekl:
        return heuristik, None
    if not heuristik:
        return dekl, None
    if dekl == heuristik:
        return heuristik, None
    # „Lokaler“ Anspruch bei nicht-loopback URL: nicht hochstufen.
    if dekl == "loopback" and heuristik != "loopback":
        return heuristik, (
            f"LLM_BETRIEB=loopback widerspricht der URL ({heuristik}); "
            f"Einstufung bleibt {heuristik}."
        )
    # Strengere Deklaration (remote) darf die Heuristik verschärfen.
    if dekl == "remote" and heuristik in ("loopback", "lan"):
        return "remote", (
            f"LLM_BETRIEB=remote überschreibt die Host-Heuristik ({heuristik})."
        )
    return heuristik, None


def ziel_anzeige(base_url: str, host: str, port: int | None, schema: str) -> str:
    """Menschliches Ziel ohne Pfad und ohne Key."""
    if not host:
        return ""
    if port:
        return f"{host}:{port}"
    if schema == "https":
        return host
    # Default-Ports weglassen wirkte inkonsistent zu Ollama-Beispielen.
    return host


def pille_zustand(
    *,
    configured: bool,
    checked: bool,
    reachable: bool | None,
    betrieb: str,
) -> tuple[str, str]:
    """
    Kopf-Pille: (css-stufe, Kurzlabel).

    grau unkonfiguriert / noch nicht geprüft ·
    rot konfiguriert aber tot ·
    gelb verbunden remote/LAN ·
    grün lokales Modell (Loopback) läuft.
    """
    if not configured:
        return "neutral", "LLM aus"
    if not checked or reachable is None:
        return "neutral", "LLM"
    if reachable is False:
        return "krit", "LLM offline"
    if betrieb == "loopback":
        return "gut", "LLM lokal"
    # LAN und Remote: gelb (verbunden, aber nicht dieses Gerät allein).
    return "warn", "LLM remote"


def _models_urls(base_url: str) -> list[str]:
    text = (base_url or "").strip().rstrip("/")
    if not text:
        return []
    if "://" not in text:
        text = "http://" + text
    if text.endswith("/v1"):
        return [f"{text}/models"]
    return [f"{text}/v1/models", f"{text}/api/tags", f"{text}/models"]


def probe_erreichbar(
    cfg: LlmConfig,
    *,
    timeout: float = PROBE_TIMEOUT_S,
) -> tuple[bool, str]:
    """
    Leichte HTTP-Probe gegen den konfigurierten Endpoint.

    OpenAI-kompatibel ``/v1/models``, sonst Ollama ``/api/tags``.
    Liefert ``(ok, fehlertext)``.
    """
    if not cfg.base_url and not cfg.anbieter:
        return False, "nicht konfiguriert"
    base = cfg.base_url
    if not base:
        if cfg.anbieter == "ollama":
            base = "http://127.0.0.1:11434/v1"
        elif cfg.anbieter == "lmstudio":
            base = "http://127.0.0.1:1234/v1"
        else:
            return False, "LLM_BASE_URL fehlt"
    try:
        ensure_url_allowed(
            base, service="llm",
            values={"LLM_REMOTE_OPT_IN": "1" if cfg.remote_opt_in else "0"},
        )
    except OutboundPolicyError as exc:
        return False, str(exc)
    letzter_fehler = "keine Antwort"
    for url in _models_urls(base):
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        if cfg.api_key:
            req.add_header("Authorization", f"Bearer {cfg.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as antwort:
                # 401/403 wären HTTPError — 2xx reicht als „Prozess antwortet“.
                if 200 <= getattr(antwort, "status", 200) < 300:
                    return True, ""
                letzter_fehler = f"HTTP {antwort.status}"
        except urllib.error.HTTPError as exc:
            # Auth-Fehler: Endpoint lebt, Key falsch — für „verbunden“ zählen.
            if exc.code in (401, 403):
                return True, ""
            letzter_fehler = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            letzter_fehler = str(exc.reason if hasattr(exc, "reason") else exc)
        except Exception as exc:  # noqa: BLE001 — Status darf nie crashen
            letzter_fehler = f"{type(exc).__name__}: {exc}"
    return False, letzter_fehler


def banner_zeile(
    *,
    anbieter: str,
    ziel: str,
    modell: str,
    privacy_label: str,
    remote_opt_in: bool,
    betrieb: str,
) -> str:
    teile = [anbieter_label(anbieter)]
    if anbieter == "api-key" and ziel:
        teile = [f"API-Key zu {ziel}"]
    elif ziel:
        teile.append(ziel)
    if modell:
        teile.append(f"Modell {modell}")
    if privacy_label:
        teile.append(f"Stufe {privacy_label}")
    teile.append("nur Cache")
    if betrieb in ("remote", "onion", "lan") and not remote_opt_in:
        teile.append("Opt-in erforderlich")
    elif betrieb in ("remote", "onion") and remote_opt_in:
        teile.append("Opt-in aktiv")
    return " · ".join(t for t in teile if t)


def status_dict(
    werte: dict[str, str] | None,
    *,
    check: bool = False,
    timeout: float = PROBE_TIMEOUT_S,
    probe_fn=None,
) -> dict[str, Any]:
    """
    Vollständiger Status für ``GET /api/llm/status``.

    Ohne ``check``: keine Netzprobe, Pille grau auch wenn konfiguriert
    (kein Rot-Flash vor dem ersten Check). Mit ``check``: Probe und
    rot/gelb/grün.
    """
    cfg = lese_llm_einstellungen(werte)
    host, port, schema = _host_aus_url(cfg.base_url)
    if not host and cfg.anbieter == "ollama":
        host, port, schema = "127.0.0.1", 11434, "http"
    elif not host and cfg.anbieter == "lmstudio":
        host, port, schema = "127.0.0.1", 1234, "http"

    anbieter = rate_anbieter(cfg, host, port) if cfg.configured else ""
    betrieb, widerspruch = betrieb_effektiv(cfg, host) if cfg.configured else ("", None)
    privacy_stufe, privacy_label = privacy_fuer_betrieb(betrieb)
    ziel = ziel_anzeige(cfg.base_url, host, port, schema)
    if anbieter == "api-key" and cfg.base_url:
        # Für Banner: Schema+Host(+Port), ohne Pfad/Key.
        zerlegt = urlparse(
            cfg.base_url if "://" in cfg.base_url else "https://" + cfg.base_url
        )
        netloc = zerlegt.netloc or ziel
        ziel_banner = netloc or ziel
    else:
        ziel_banner = ziel

    reachable: bool | None = None
    probe_error = ""
    checked = False
    if check and cfg.configured:
        checked = True
        fn = probe_fn or probe_erreichbar
        ok, probe_error = fn(cfg, timeout=timeout)
        reachable = bool(ok)
        if ok:
            probe_error = ""

    pille, pille_label = pille_zustand(
        configured=cfg.configured,
        checked=checked,
        reachable=reachable,
        betrieb=betrieb,
    )

    banner = (
        banner_zeile(
            anbieter=anbieter,
            ziel=ziel_banner,
            modell=cfg.modell,
            privacy_label=privacy_label,
            remote_opt_in=cfg.remote_opt_in,
            betrieb=betrieb,
        )
        if cfg.configured
        else "Assistent nicht konfiguriert"
    )

    tooltip_teile = [banner]
    if widerspruch:
        tooltip_teile.append(widerspruch)
    if checked and reachable is False and probe_error:
        tooltip_teile.append(f"nicht erreichbar: {probe_error}")
    elif checked and reachable:
        tooltip_teile.append("erreichbar")

    # base_url_anzeige: Key nie einbetten; Roh-URL ohne Userinfo.
    anzeige_url = cfg.base_url
    if anzeige_url and "@" in anzeige_url:
        try:
            p = urlparse(anzeige_url if "://" in anzeige_url else "http://" + anzeige_url)
            anzeige_url = f"{p.scheme}://{p.netloc.split('@')[-1]}{p.path}"
        except Exception:  # noqa: BLE001
            anzeige_url = ziel_banner

    payload = {
        "configured": cfg.configured,
        "anbieter": anbieter,
        "anbieter_label": anbieter_label(anbieter),
        "base_url": anzeige_url,
        "ziel": ziel_banner,
        "modell": cfg.modell,
        "betrieb": betrieb,
        "privacy_stufe": privacy_stufe,
        "privacy_label": privacy_label,
        "remote_opt_in": cfg.remote_opt_in,
        "api_key_set": bool(cfg.api_key),
        "datenmodus": DATENMODUS,
        "reachable": reachable,
        "checked": checked,
        "probe_error": probe_error,
        "pille": pille,
        "pille_label": pille_label,
        "banner": banner,
        "tooltip": " · ".join(tooltip_teile),
        "widerspruch": widerspruch or "",
    }
    # Harte Absicherung: echte Keys (nicht Ein-Zeichen-Dummies) dürfen in
    # keiner String-Form vorkommen. Sehr kurze Werte kollidieren sonst mit
    # JSON-Feldnamen („k“ in „checked“).
    if cfg.api_key and len(cfg.api_key) >= 8:
        dump = json.dumps(payload, ensure_ascii=False)
        if cfg.api_key in dump:
            raise RuntimeError("API-Key darf nicht im LLM-Status landen")
    return payload
