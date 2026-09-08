"""
Cache-Reader für den Assistenten (Phase 2).

Nur lokale Bestände: UTXO-Cache, Verlauf, Ingress. Kein Netzwerk, kein
Job-Start. Die Antworten sind Aggregates — Wallet-Namen, Zahlen, Hinweise;
keine XPUBs und keine vollen Adresslisten.
"""
from __future__ import annotations

from typing import Any

import main
from core import tax
from core import wallets as wallets_mod
from display import format_sats

KNOPF_SCAN = "UTXO-Scan in der Wallet-Ansicht"
KNOPF_VERLAUF = "Verlaufsscan (Wallet) bzw. Verlauf aller Wallets"
KNOPF_HERKUNFT = "Herkunft aller UTXOs (Steuerjahr oder Herkunft tracen)"
KNOPF_HERKUNFT_TIEF = (
    "Herkunft vollständig (Wallet): jedes UTXO bis extern/Coinbase, "
    "kann sehr lange dauern"
)

EXPORT_ARTEN = frozenset({"legende", "markdown", "brief"})

EXPORT_LEGENDE = (
    "Grundlage Anschaffungsdatum: Herkunft (Ingress), sonst das Output-Datum.",
    "außerhalb Haltefrist: nach der hier gerechneten Anschaffung steuerfrei.",
    "innerhalb Haltefrist: Frist läuft noch, oder Neuvermögen nach Stichtag.",
    "Untergrenze: Herkunft unvollständig — das Datum kann zu jung sein.",
    "ungeprüft: noch kein Herkunftslauf, es zählt nur das Output-Datum.",
    "Abgänge: nur sichtbar, wenn ein Verlaufsscan vorliegt.",
    "Maßgeblich bleibt der CSV-/HTML-Export aus dem Code, nicht dieser Text.",
)


def _ingress_offen(txid: str, vout: int, immutable_dir) -> bool:
    eintrag = main.load_utxo_ingress_cache(txid, vout, immutable_dir)
    if not eintrag:
        return True
    return "external_time_ts" not in eintrag


def _wallet_zeilen(entries, cache_dir, immutable_dir) -> list[dict[str, Any]]:
    zusammen = wallets_mod.summarize(entries, cache_dir)
    zeilen = []
    for z in zusammen:
        schluessel = z.entry.analyse_schluessel
        verlauf = main.load_xpub_verlauf_cache(schluessel, cache_dir)
        utxos = (main.load_xpub_cache_entry(schluessel, cache_dir) or {}).get(
            "utxos"
        ) or []
        ohne_herkunft = 0
        if immutable_dir is not None:
            for utxo in utxos:
                if _ingress_offen(
                    utxo.get("txid", ""), int(utxo.get("vout", 0)), immutable_dir
                ):
                    ohne_herkunft += 1
        zeilen.append({
            "name": z.entry.display_name,
            "has_cache": z.has_cache,
            "hat_verlauf": bool(verlauf),
            "utxo_count": z.utxo_count,
            "total_sats": z.total_sats,
            "ohne_herkunft": ohne_herkunft,
        })
    return zeilen


def luecken(
    *,
    entries,
    cache_dir,
    immutable_dir,
    jobs=None,
) -> dict[str, Any]:
    """Was für sinnvolle Antworten fehlt — und welcher Knopf das füllt."""
    zeilen = _wallet_zeilen(entries, cache_dir, immutable_dir)
    ohne_cache = [z["name"] for z in zeilen if not z["has_cache"]]
    ohne_verlauf = [z["name"] for z in zeilen if z["has_cache"] and not z["hat_verlauf"]]
    ohne_herkunft = sum(z["ohne_herkunft"] for z in zeilen)
    utxo_zahl = sum(z["utxo_count"] for z in zeilen)
    laufend = []
    if jobs is not None:
        for job in jobs.list():
            if job.status == "running":
                laufend.append({"kind": job.kind, "label": job.label})

    punkte: list[str] = []
    knoepfe: list[str] = []
    if not zeilen:
        punkte.append("Kein Wallet eingetragen.")
        knoepfe.append("Verwaltung → Wallets")
    if ohne_cache:
        namen = ", ".join(f"„{n}“" for n in ohne_cache)
        punkte.append(f"Kein UTXO-Cache: {namen}.")
        knoepfe.append(KNOPF_SCAN)
    if ohne_verlauf:
        namen = ", ".join(f"„{n}“" for n in ohne_verlauf)
        punkte.append(
            f"Kein Verlaufsscan: {namen} — Abgänge früherer Jahre fehlen."
        )
        knoepfe.append(KNOPF_VERLAUF)
    if ohne_herkunft:
        punkte.append(
            f"Herkunft fehlt bei {ohne_herkunft} von {utxo_zahl} offenen UTXOs "
            "— ohne sie gilt oft nur das Output-Datum."
        )
        knoepfe.append(KNOPF_HERKUNFT)
    if laufend:
        punkte.append(
            "Läuft gerade: " + ", ".join(j["label"] for j in laufend) + "."
        )
    if not punkte:
        punkte.append(
            "Cache, Verlauf und Herkunft sind vorhanden. "
            "/steuer und /wallets können antworten."
        )

    if knoepfe:
        knoepfe.append("Danach Kaffee — ich starte keine Scans.")

    text_teile = ["Lücken (nur lokaler Cache):", *[f"• {p}" for p in punkte]]
    if knoepfe:
        text_teile.append("Knöpfe: " + " · ".join(knoepfe))
    return {
        "punkte": punkte,
        "knoepfe": knoepfe,
        "ohne_cache": ohne_cache,
        "ohne_verlauf": ohne_verlauf,
        "ohne_herkunft": ohne_herkunft,
        "utxo_count": utxo_zahl,
        "jobs": laufend,
        "text": "\n".join(text_teile),
    }


def wallets(
    *,
    entries,
    cache_dir,
    immutable_dir,
) -> dict[str, Any]:
    """Geladene Wallet-Namen und grober Cache-Stand."""
    zeilen = _wallet_zeilen(entries, cache_dir, immutable_dir)
    if not zeilen:
        text = "Keine Wallets geladen."
    else:
        teile = ["Wallets (Cache-Stand):"]
        for z in zeilen:
            if not z["has_cache"]:
                stand = "kein Cache"
            else:
                stand = (
                    f"{z['utxo_count']} UTXO(s), {format_sats(z['total_sats'])}"
                )
                stand += ", Verlauf ja" if z["hat_verlauf"] else ", Verlauf nein"
                if z["ohne_herkunft"]:
                    stand += f", Herkunft offen {z['ohne_herkunft']}"
            teile.append(f"• {z['name']}: {stand}")
        text = "\n".join(teile)
    return {"wallets": zeilen, "text": text}


def steuer_kompakt(auswertung: dict[str, Any]) -> dict[str, Any]:
    """Kennzahlen ohne Einträge/Adressen — für Slash und spätere Tools."""
    k = auswertung.get("kennzahlen") or {}
    jahr = auswertung.get("jahr")
    zeilen = [
        f"Steuerjahr {jahr} · {auswertung.get('stichtag_label') or ''}".rstrip(),
        f"Haltefrist {auswertung.get('haltefrist_jahre')} Jahr(e)"
        + (
            f" · Stichtag {auswertung['stichtag_regel']}"
            if auswertung.get("stichtag_regel")
            else ""
        ),
        (
            f"Bestand: {format_sats(k.get('gesamt_sats', 0))} "
            f"({k.get('gesamt_count', 0)} UTXOs) · "
            f"außerhalb Frist {format_sats(k.get('erfuellt_sats', 0))} · "
            f"innerhalb {format_sats(k.get('offen_sats', 0))}"
        ),
    ]
    if k.get("abgang_count"):
        zeilen.append(
            f"Abgänge im Jahr: {k['abgang_count']} · "
            f"{format_sats(k.get('abgang_sats', 0))} "
            f"(davon innerhalb Frist {format_sats(k.get('abgang_steuerpflichtig_sats', 0))})"
        )
    elif not auswertung.get("hat_verlauf"):
        zeilen.append("Keine Abgänge sichtbar — es fehlt der Verlaufsscan.")
    if k.get("ungeprueft_count"):
        zeilen.append(
            f"Ohne Herkunft: {k['ungeprueft_count']} UTXOs "
            f"({format_sats(k.get('ungeprueft_sats', 0))}) — "
            f"{KNOPF_HERKUNFT}."
        )
    if auswertung.get("ohne_verlauf"):
        namen = ", ".join(f"„{n}“" for n in auswertung["ohne_verlauf"])
        zeilen.append(f"Ohne Verlauf: {namen} — {KNOPF_VERLAUF}.")
    zeilen.append(
        "Keine Steuerberatung. Quelle: Steuerjahr-Auswertung aus dem Cache. "
        + tax.HINWEIS_ONCHAIN
    )
    return {
        "jahr": jahr,
        "stichtag_label": auswertung.get("stichtag_label", ""),
        "haltefrist_jahre": auswertung.get("haltefrist_jahre"),
        "stichtag_regel": auswertung.get("stichtag_regel", ""),
        "kennzahlen": k,
        "hinweise": list(auswertung.get("hinweise") or []),
        "ohne_verlauf": list(auswertung.get("ohne_verlauf") or []),
        "verfuegbare_jahre": list(auswertung.get("verfuegbare_jahre") or []),
        "hat_verlauf": bool(auswertung.get("hat_verlauf")),
        "text": "\n".join(zeilen),
    }


def export_legende(auswertung: dict[str, Any]) -> dict[str, Any]:
    """Spalten- und Vorbehaltstext zum festen Steuer-Export."""
    jahr = auswertung.get("jahr")
    zeilen = [f"Legende Steuerjahr {jahr} (Cache, kein neuer Report):"]
    zeilen.extend(f"• {z}" for z in EXPORT_LEGENDE)
    for hinweis in auswertung.get("hinweise") or []:
        zeilen.append(f"• {hinweis}")
    return {
        "art": "legende",
        "jahr": jahr,
        "zeilen": list(EXPORT_LEGENDE),
        "hinweise": list(auswertung.get("hinweise") or []),
        "text": "\n".join(zeilen),
    }


def export_markdown(auswertung: dict[str, Any]) -> dict[str, Any]:
    """Markdown-Übersicht aus denselben Kennzahlen wie ``steuer_kompakt``."""
    k = auswertung.get("kennzahlen") or {}
    jahr = auswertung.get("jahr")
    zeilen = [
        f"# Steuerjahr {jahr}",
        "",
        auswertung.get("stichtag_label") or "",
        (
            f"Haltefrist {auswertung.get('haltefrist_jahre')} Jahr(e)"
            + (
                f" · Stichtag {auswertung['stichtag_regel']}"
                if auswertung.get("stichtag_regel")
                else ""
            )
        ),
        "",
        "## Bestand",
        (
            f"- Gesamt: {format_sats(k.get('gesamt_sats', 0))} "
            f"({k.get('gesamt_count', 0)} UTXOs)"
        ),
        f"- außerhalb Haltefrist: {format_sats(k.get('erfuellt_sats', 0))}",
        f"- innerhalb Haltefrist: {format_sats(k.get('offen_sats', 0))}",
        "",
        "## Abgänge",
    ]
    if k.get("abgang_count"):
        zeilen.append(
            f"- {k['abgang_count']} Vorgänge · {format_sats(k.get('abgang_sats', 0))}"
            f" · innerhalb Frist {format_sats(k.get('abgang_steuerpflichtig_sats', 0))}"
        )
    else:
        zeilen.append("- keine bzw. ohne Verlauf nicht sichtbar")
    zeilen.extend(["", "## Hinweise"])
    for hinweis in auswertung.get("hinweise") or []:
        zeilen.append(f"- {hinweis}")
    zeilen.extend([
        "",
        "Keine Steuerberatung. Maßgeblich bleibt der CSV-/HTML-Export. "
        + tax.HINWEIS_ONCHAIN,
    ])
    text = "\n".join(z for z in zeilen if z is not None)
    return {"art": "markdown", "jahr": jahr, "text": text}


def export_brief(auswertung: dict[str, Any]) -> dict[str, Any]:
    """Kurzes Anschreiben aus denselben Kennzahlen — kein LLM, kein neuer Report."""
    k = auswertung.get("kennzahlen") or {}
    jahr = auswertung.get("jahr")
    zeilen = [
        f"Steuerjahr {jahr} — Kurzfassung für den Steuerberater",
        "",
        "Die Zahlen stammen aus dem lokalen Cache von SatSage. "
        "Das ist keine Steuerberatung. " + tax.HINWEIS_ONCHAIN,
        "",
        (
            f"Bestand ({auswertung.get('stichtag_label') or 'Stichtag'}): "
            f"{format_sats(k.get('gesamt_sats', 0))} in "
            f"{k.get('gesamt_count', 0)} UTXOs. "
            f"Außerhalb der Haltefrist {format_sats(k.get('erfuellt_sats', 0))}, "
            f"innerhalb {format_sats(k.get('offen_sats', 0))}."
        ),
    ]
    if k.get("abgang_count"):
        zeilen.append(
            f"Abgänge im Jahr: {k['abgang_count']} Vorgänge über "
            f"{format_sats(k.get('abgang_sats', 0))} "
            f"(davon innerhalb der Frist "
            f"{format_sats(k.get('abgang_steuerpflichtig_sats', 0))})."
        )
    elif not auswertung.get("hat_verlauf"):
        zeilen.append(
            "Abgänge sind nicht ausgewiesen — es fehlt der Verlaufsscan."
        )
    if auswertung.get("ohne_verlauf"):
        namen = ", ".join(f"„{n}“" for n in auswertung["ohne_verlauf"])
        zeilen.append(f"Ohne Verlauf: {namen}.")
    zeilen.extend([
        "",
        "Die maßgebliche Datei bleibt der CSV- oder HTML-Export aus der Oberfläche.",
    ])
    return {"art": "brief", "jahr": jahr, "text": "\n".join(zeilen)}


def export_aus(auswertung: dict[str, Any], art: str) -> dict[str, Any]:
    """Wählt den deterministischen Renderer. Unbekannte Art → Fehlertext."""
    name = (art or "legende").strip().lower()
    if name == "legende":
        return export_legende(auswertung)
    if name == "markdown":
        return export_markdown(auswertung)
    if name == "brief":
        return export_brief(auswertung)
    return {
        "art": name,
        "jahr": auswertung.get("jahr"),
        "text": "Unbekanntes Exportformat. Erlaubt: legende, markdown, brief.",
    }
