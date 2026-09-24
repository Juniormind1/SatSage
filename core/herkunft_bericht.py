"""
Herkunftsnachweis für Steuer-HTML: vollständige on-chain Hop-Kette.

Kein Börsen-/Konto-Beleg — nur das, was SatSage aus Trace-Cache und
Blockchain rekonstruieren kann. Ziel: Haltedauer-Behauptung mit
verifizierbaren TxID:vout-Hops untermauern (Fahndung / Nachvollziehbarkeit).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core import tax as tax_mod
from core.xpub_cache import _normalize_txid
from core import trace_cache


def _esc(text: Any) -> str:
    return tax_mod._html_escape(str(text if text is not None else ""))


def _btc(sats: int | None) -> str:
    return tax_mod._btc(int(sats or 0))


def _knoten_label(knoten: dict) -> str:
    typ = str(knoten.get("type") or "")
    if typ == "internal":
        art = "Intern"
    elif typ == "external":
        art = "Extern"
    elif typ == "external_unresolved":
        art = "Extern (unaufgelöst)"
    elif typ == "coinbase":
        art = "Coinbase"
    elif typ == "utxo":
        art = "UTXO (Ziel)"
    else:
        art = typ or "Knoten"

    teile = [art]
    wallet = (knoten.get("wallet") or "").strip()
    if wallet:
        teile.append(wallet)
    addr = (knoten.get("address") or "").strip()
    if addr:
        teile.append(addr)
    from_u = (knoten.get("from_utxo") or "").strip()
    if not from_u:
        txid = (knoten.get("txid") or "").strip()
        if txid:
            try:
                vout = int(knoten.get("vout", 0))
            except (TypeError, ValueError):
                vout = 0
            from_u = f"{txid}:{vout}"
    if from_u:
        teile.append(from_u)
    sats = knoten.get("amount_sats")
    if sats is not None:
        teile.append(f"{_btc(int(sats))} BTC")
    zeit = (knoten.get("time_label") or "").strip()
    if zeit:
        teile.append(zeit)
    note = (knoten.get("note") or "").strip()
    # UI-Notiz „Externe Zweige…“ im Beleg weglassen — redundant.
    if note and "nicht weiterverfolgt" not in note.lower():
        teile.append(note)
    return " · ".join(teile)


def _kinder(knoten: dict) -> list[dict]:
    roh = knoten.get("children")
    if isinstance(roh, list):
        return [k for k in roh if isinstance(k, dict)]
    return []


def _wallet_norm(wert: Any) -> str:
    return str(wert or "").strip()


def _ist_wallet_austritt(eltern: dict | None, kind: dict) -> bool:
    """
    True, wenn *kind* das Wallet-Segment von *eltern* verlässt.

    Gleiche-Wallet-Hops bleiben flach; Einrückung nur bei Wallet-Wechsel
    oder Übergang zu Extern/Coinbase/unaufgelöst (wie Web-UI).
    """
    if not isinstance(eltern, dict):
        return False
    if str(eltern.get("type") or "") != "internal":
        return False
    if str(kind.get("type") or "") == "internal":
        return _wallet_norm(eltern.get("wallet")) != _wallet_norm(kind.get("wallet"))
    return True


def _baum_als_ol(knoten: dict, *, max_knoten: int = 50_000) -> tuple[str, int]:
    """
    Nested ``<ol>`` der Hop-Kette. Rückgabe (html, anzahl_gerendert).

    Visuell flach innerhalb desselben Wallets (``.hop-kinder.flach`` /
    ``.hop-austritt``); *max_knoten* schützt vor pathologischen Bäumen.
    """
    gezaehlt = [0]
    abgeschnitten = [False]

    def render(k: dict, eltern: dict | None = None) -> str:
        if gezaehlt[0] >= max_knoten:
            abgeschnitten[0] = True
            return ""
        gezaehlt[0] += 1
        label = _esc(_knoten_label(k))
        typ = str(k.get("type") or "")
        klassen = [f"hop hop-{_esc(typ)}" if typ else "hop"]
        if _ist_wallet_austritt(eltern, k):
            klassen.append("hop-austritt")
            if (
                typ == "internal"
                and eltern is not None
                and _wallet_norm(eltern.get("wallet")) != _wallet_norm(k.get("wallet"))
            ):
                klassen.append("hop-wallet-uebergang")
        klasse = " ".join(klassen)
        kinder_html = []
        for kind in _kinder(k):
            if gezaehlt[0] >= max_knoten:
                abgeschnitten[0] = True
                break
            stueck = render(kind, eltern=k)
            if stueck:
                kinder_html.append(stueck)
        innen = ""
        if kinder_html:
            # Interne Segmente: Kinder standardmäßig flach; Austritte per Klasse.
            kinder_cls = (
                "hop-kinder flach" if typ == "internal" else "hop-kinder"
            )
            innen = f"<ol class='{kinder_cls}'>{''.join(kinder_html)}</ol>"
        return (
            f"<li class='{klasse}'>"
            f"<span class='hop-zeile'>{label}</span>{innen}</li>"
        )

    body = render(knoten)
    if abgeschnitten[0]:
        body += (
            f"<li class='klein'><em>… weitere Hops ausgelassen "
            f"(Limit {max_knoten}).</em></li>"
        )
    html = f"<ol class='hop-wurzel'>{body}</ol>"
    return html, gezaehlt[0]


def _wurzel_aus_baum(baum: dict) -> dict | None:
    root = baum.get("root")
    if isinstance(root, dict):
        # UI speichert Kinder neben root, nicht in root.children
        kinder = baum.get("children")
        if isinstance(kinder, list) and kinder and not _kinder(root):
            root = dict(root)
            root["children"] = kinder
        return root
    kinder = baum.get("children")
    if isinstance(kinder, list) and kinder:
        # synthetische Wurzel
        return {
            "type": "utxo",
            "children": kinder,
            "txid": baum.get("txid"),
            "vout": baum.get("vout"),
        }
    return None


def hop_kette_html(
    txid: str,
    vout: int,
    *,
    immutable_cache_dir: Path | str | None,
    wallet: str = "",
    address: str = "",
    value_sats: int | None = None,
) -> str:
    """
    Ein Herkunftsblock für *txid:vout* oder leer, wenn kein Trace-Cache.
    """
    geladen = trace_cache.laden(txid, vout, immutable_cache_dir, adressen=None)
    if not geladen:
        return ""
    baum = geladen.get("baum")
    if not isinstance(baum, dict):
        return ""
    wurzel = _wurzel_aus_baum(baum)
    if wurzel is None:
        return ""

    # Kopfzeile: Ziel-UTXO
    if not (wurzel.get("txid") or wurzel.get("from_utxo")):
        wurzel = dict(wurzel)
        wurzel.setdefault("txid", _normalize_txid(txid))
        wurzel.setdefault("vout", int(vout))
        if address:
            wurzel.setdefault("address", address)
        if wallet:
            wurzel.setdefault("wallet", wallet)
        if value_sats is not None:
            wurzel.setdefault("amount_sats", value_sats)

    ol, n = _baum_als_ol(wurzel)
    summary = baum.get("summary") if isinstance(baum.get("summary"), dict) else {}
    voll = baum.get("verfolgt_vollstaendig")
    meta_teile = [f"{n} Hops im Nachweis"]
    if summary.get("external_count") is not None:
        meta_teile.append(f"{summary.get('external_count')} externe Blätter")
    if summary.get("unresolved_inputs"):
        meta_teile.append(
            f"{summary.get('unresolved_inputs')} unaufgelöste Eingänge"
        )
    if voll is False:
        meta_teile.append("Trace unvollständig — Untergrenze möglich")
    elif voll is True:
        meta_teile.append("Trace vollständig")

    titel = f"{_normalize_txid(txid)}:{int(vout)}"
    if wallet:
        titel = f"{wallet} · {titel}"

    return f"""
<section class="herkunft-utxo">
  <h3 class="mono">{_esc(titel)}</h3>
  <p class="unter klein">{_esc(" · ".join(meta_teile))}</p>
  <p class="klein">
    Hop-Kette rückwärts (Ziel → Vorgänger). <strong>Intern</strong> =
    eigene Wallet-Adresse; <strong>Extern</strong> = Zufluss von außerhalb
    der konfigurierten Wallets. Jede Zeile ist on-chain prüfbar (TxID:vout).
  </p>
  {ol}
</section>
"""


def abschnitt_hop_ketten(
    eintraege: list[dict],
    *,
    immutable_cache_dir: Path | str | None,
    ueberschrift: str = "Herkunftsnachweis (on-chain Hop-Kette)",
) -> str:
    """
    Abschnitt für alle Einträge mit gespeichertem Trace.

    *eintraege*: dicts mit mindestens ``txid``, ``vout``; optional
    ``wallet``, ``address``, ``value_sats``.
    """
    if immutable_cache_dir is None:
        return ""
    bloecke: list[str] = []
    for e in eintraege:
        if not isinstance(e, dict):
            continue
        txid = str(e.get("txid") or "").strip()
        if not txid:
            continue
        try:
            vout = int(e.get("vout", 0))
        except (TypeError, ValueError):
            continue
        block = hop_kette_html(
            txid,
            vout,
            immutable_cache_dir=immutable_cache_dir,
            wallet=str(e.get("wallet") or ""),
            address=str(e.get("address") or ""),
            value_sats=e.get("value_sats"),
        )
        if block:
            bloecke.append(block)
    if not bloecke:
        return f"""
<section class="herkunft-nachweis">
  <h2>{_esc(ueberschrift)}</h2>
  <p class="unter">
    Kein gespeicherter Herkunfts-Trace für die gelisteten UTXOs.
    Unter „Herkunft tracen“ analysieren, danach den Bericht erneut erzeugen.
  </p>
</section>
"""
    return f"""
<section class="herkunft-nachweis">
  <h2>{_esc(ueberschrift)}</h2>
  <p class="unter">
    On-chain-Nachweis der Sats-Herkunft bis zu den externen Zuflüssen.
    Börsenhistorien und Kaufbelege ersetzt das nicht — es belegt die
    Wallet-Haltedauer über verifizierbare Transaktionen.
  </p>
  {"".join(bloecke)}
</section>
"""


def normalize_bericht_theme(roh: str | None) -> str:
    """``light`` oder ``dark`` — wie GUI-``UI_THEME`` / ``data-theme``."""
    text = str(roh or "").strip().lower()
    if text in ("dark", "dunkel"):
        return "dark"
    return "light"


#: Screen Dark/Light folgt ``html[data-theme]`` (GUI-Farbmodus beim Erzeugen),
#: nicht dem OS. Print immer hell (kein schwarzes Papier).
#: In alle SatSage-HTML-Berichte einbetten; Farben nur über diese Variablen.
BERICHT_THEME_CSS = """
  :root, html[data-theme="light"] {
    color-scheme: light;
    --bg: #ffffff;
    --fg: #1a1a1a;
    --muted: #444444;
    --muted2: #555555;
    --line: #333333;
    --line-soft: #dddddd;
    --line-mid: #cccccc;
    --panel: #f4f4f0;
    --panel2: #f8f8f4;
  }
  /* Explizit GUI-Dark — nicht prefers-color-scheme (OS kann abweichen). */
  html[data-theme="dark"] {
    color-scheme: dark;
    --bg: #12141a;
    --fg: #e8eaed;
    --muted: #a8adb6;
    --muted2: #9aa0a8;
    --line: #c5c9d0;
    --line-soft: #3a3f4a;
    --line-mid: #4a5060;
    --panel: #1c2028;
    --panel2: #181c24;
  }
  /* Druck/PDF: immer hell — spart Tinte und bleibt lesbar. */
  @media print {
    :root, html[data-theme="light"], html[data-theme="dark"] {
      color-scheme: light only;
      --bg: #ffffff !important;
      --fg: #1a1a1a !important;
      --muted: #444444 !important;
      --muted2: #555555 !important;
      --line: #333333 !important;
      --line-soft: #dddddd !important;
      --line-mid: #cccccc !important;
      --panel: #f4f4f0 !important;
      --panel2: #f8f8f4 !important;
    }
    body {
      background: #ffffff !important;
      color: #1a1a1a !important;
      print-color-adjust: economy;
      -webkit-print-color-adjust: economy;
    }
  }
"""

#: CSS-Fragment für nested Hop-Listen (in Bericht einbetten).
HOP_KETTE_CSS = """
  .herkunft-nachweis { margin-top: 28pt; padding-top: 12pt;
                       border-top: 1.5px solid var(--line, #333); }
  .herkunft-utxo { margin: 16pt 0 20pt; }
  .herkunft-utxo h3 { font-size: 10pt; margin: 0 0 4pt; word-break: break-all; }
  ol.hop-wurzel, ol.hop-kinder {
    margin: 4pt 0 4pt 14pt; padding: 0 0 0 10pt;
    font-size: 7.5pt; font-family: "Courier New", monospace;
  }
  /* Gleiches Wallet: keine extra Einrückung pro Hop. */
  ol.hop-kinder.flach {
    margin-left: 0; padding-left: 0;
  }
  ol.hop-kinder.flach > li.hop-austritt {
    margin-left: 14pt; padding-left: 10pt;
    border-left: 1.5px solid var(--line-mid, #ccc);
  }
  li.hop-wallet-uebergang > .hop-zeile { font-weight: bold; }
  li.hop { margin: 2pt 0; }
  li.hop-external > .hop-zeile { font-weight: bold; }
  li.hop-external_unresolved > .hop-zeile { color: var(--muted, #666); }
  .hop-zeile { word-break: break-all; }
"""
