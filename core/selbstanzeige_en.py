"""Englische Fassung des Berichts Sat-Geschichte (Einzel-UTXO/Selbstanzeige).

Der Bericht wird unverändert deutsch gerendert (die deutsche Ausgabe bleibt
damit Byte für Byte gleich) und erst danach für ``lang="en"`` übersetzt:
Satzbausteine aus ``selbstanzeige``, ``herkunft_bericht``, ``tax`` und
``tx_classify`` per Tabelle, Datums- (TT.MM.JJJJ → JJJJ-MM-TT) und
Zahlenformat (Dezimalkomma → Punkt) nur im sichtbaren Teil, nie im CSS.
Texte mit i18n-Schlüssel kommen direkt aus ``web/locales``.
"""

from __future__ import annotations

import re

_TABELLE: list[tuple[str, str]] = [
    # Hinweise (selbstanzeige.py)
    ("Diese Unterlage ist ein Bericht zur Sat-Geschichte (On-Chain) und dient "
     "der Dokumentation von Zu- und Abflüssen. Sie ist keine Steuerberatung. "
     "Vollständigkeit für den betroffenen Zeitraum und die betroffenen "
     "Vorgänge liegt in der Verantwortung des Nutzers.",
     "This document is a report on the sat history (on-chain) and documents "
     "inflows and outflows. It is not tax advice. Completeness for the period "
     "and transactions concerned is the user's responsibility."),
    ("Verwendungsreihenfolge: walletbezogenes FiFo (älteste Anschaffungslose "
     "zuerst), vereinfachend aus dem lokalen Verlauf. Markierte Vorgänge "
     "werden in zeitlicher Reihenfolge verbraucht; nicht markierte Abgänge "
     "gelten hier nicht als Veräußerung und verbrauchen keine Lose.",
     "Order of use: per-wallet FIFO (oldest acquisition lots first), "
     "simplified from the local history. Marked transactions are consumed in "
     "chronological order; unmarked outflows are not treated as disposals "
     "here and consume no lots."),
    ("Als Veräußerungszeitpunkt gilt in dieser Fassung die Blockzeit der "
     "on-chain-Einzahlung an die Börse. Ein späterer Trade auf der Börse "
     "kann der wirtschaftlich maßgebliche Zeitpunkt sein — ggf. belegen.",
     "In this version, the disposal date is the block time of the on-chain "
     "deposit to the exchange. A later trade on the exchange may be the "
     "economically relevant date — document it if so."),
    ("Hypothese „Was wäre wenn“: markierte offene UTXOs werden fiktiv zum "
     "Stichtag (Jahresende des Steuerjahres, bzw. heute wenn das Jahr noch "
     "läuft) als veräußert angenommen. Das ist keine tatsächliche Ausgabe — "
     "nur eine Durchrechnung der Haltedauer.",
     "“What if” scenario: marked unspent UTXOs are assumed to be disposed of "
     "on the reference date (end of the tax year, or today if the year is "
     "still running). This is not an actual spend — only a holding-period "
     "calculation."),
    # Fußtext
    ("Erzeugt mit SatSage aus lokal vorliegenden Wallet-/Cache-Daten.\n"
     "TxIDs und Adressen sind vollständig angegeben. Herkunft: on-chain Hop-Kette\n"
     "(keine Börsenbelege). PDF: Im Browser „Drucken → Als PDF sichern“.",
     "Generated with SatSage from locally available wallet/cache data.\n"
     "TxIDs and addresses are given in full. Origin: on-chain hop chain\n"
     "(no exchange records). PDF: in the browser use “Print → Save as PDF”."),
    ("<strong>Keine Vorgänge in diesem Report.</strong><br>TxID passt nicht zum "
     "gewählten Steuerjahr, oder FiFo fand keine Lose im Cache. Bitte Jahr "
     "prüfen, Abfluss ankreuzen oder „Aktualisieren“.",
     "<strong>No transactions in this report.</strong><br>The TxID does not "
     "match the selected tax year, or FIFO found no lots in the cache. Check "
     "the year, tick the outflow or use “Refresh”."),
    # Herkunftsnachweis (herkunft_bericht.py)
    ("On-chain-Nachweis der Sats-Herkunft bis zu den externen Zuflüssen.\n"
     "    Börsenhistorien und Kaufbelege ersetzt das nicht — es belegt die\n"
     "    Wallet-Haltedauer über verifizierbare Transaktionen.",
     "On-chain proof of the sats' origin back to the external inflows.\n"
     "    It does not replace exchange histories or purchase receipts — it\n"
     "    proves the wallet holding period through verifiable transactions."),
    ("Kein gespeicherter Herkunfts-Trace für die gelisteten UTXOs.\n"
     "    Unter „Herkunft tracen“ analysieren, danach den Bericht erneut erzeugen.",
     "No stored origin trace for the listed UTXOs.\n"
     "    Analyse them under “Trace origin”, then generate the report again."),
    ("Hop-Kette rückwärts (Ziel → Vorgänger). <strong>Intern</strong> =\n"
     "    eigene Adresse; <strong>Extern</strong> = Zufluss von außerhalb\n"
     "    der Eigenverwahrung.",
     "Hop chain backwards (target → predecessor). <strong>Internal</strong> =\n"
     "    own address; <strong>External</strong> = inflow from outside\n"
     "    self-custody."),
    ("Hop-Kette rückwärts (Ziel → Vorgänger). <strong>Intern</strong> =\n"
     "    eigene Adresse; <strong>Extern</strong> = Zufluss von außerhalb\n"
     "    der konfigurierten Wallets.",
     "Hop chain backwards (target → predecessor). <strong>Internal</strong> =\n"
     "    own address; <strong>External</strong> = inflow from outside\n"
     "    the configured wallets."),
    ("Hop-Kette rückwärts (Ziel → Vorgänger). <strong>Intern</strong> =\n"
     "    eigene Adresse; <strong>Extern</strong> = Zufluss von außerhalb\n"
     "    der ",
     "Hop chain backwards (target → predecessor). <strong>Internal</strong> =\n"
     "    own address; <strong>External</strong> = inflow from outside\n"
     "    "),
    ("Jede Zeile ist on-chain prüfbar (TxID:vout).",
     "Every line can be verified on-chain (TxID:vout)."),
    ("Herkunftsnachweis (on-chain Hop-Kette der Lose)",
     "Proof of origin (on-chain hop chain of the lots)"),
    ("Trace unvollständig — Datum vorsichtig (Obergrenze)",
     "trace incomplete — cautious date (upper bound)"),
    ("Trace vollständig", "trace complete"),
    (" Hops im Nachweis", " hops in proof"),
    (" externe Blätter", " external leaves"),
    (" unaufgelöste Eingänge", " unresolved inputs"),
    ("UTXO (Ziel)", "UTXO (target)"),
    # Grundlage (tax.py)
    ("Herkunft verfolgt (offensiv, Fallback jüngste)",
     "origin traced (offensive, fallback youngest)"),
    ("Herkunft verfolgt (offensiv, Lot-Anteil)",
     "origin traced (offensive, lot share)"),
    ("Herkunft verfolgt (nur Wallet-Eingang)",
     "origin traced (wallet inflow only)"),
    ("Herkunft verfolgt", "origin traced"),
    ("(Untergrenze)", "(lower bound)"),
    ("(Bündel, vorsichtig)", "(bundle, cautious)"),
    ("nur Output-Datum", "output date only"),
    # Kopf, Vorgang, Tabellen (selbstanzeige.py)
    ("Hypothese: offene UTXOs zum Stichtag",
     "Scenario: unspent UTXOs at reference date"),
    ("Hypothese: offener UTXO (fiktive Veräußerung)",
     "Scenario: unspent UTXO (hypothetical disposal)"),
    ("Einzahl-/Veräußerungs-Transaktion", "Deposit/disposal transaction"),
    ("<strong>Summenzeile (FiFo):</strong>", "<strong>Summary (FIFO):</strong>"),
    ("Jüngstes Anschaffungsdatum der verbrauchten Lose:",
     "Latest acquisition date of the consumed lots:"),
    ("· Quelle/Adresse:", "· Source/address:"),
    ("· Alle Lose außerhalb Haltefrist:",
     "· All lots outside holding period (tax-free):"),
    ("FiFo-Lose (Anschaffung → dieser Abgang)",
     "FIFO lots (acquisition → this disposal)"),
    ("On-Chain-Inputs dieser Einzahl-Tx", "On-chain inputs of this deposit tx"),
    ("<th>Anschaffung</th>", "<th>Acquisition date</th>"),
    ("<th>Adresse Empfang</th>", "<th>Receiving address</th>"),
    ("<th>Externe Quelle</th>", "<th>External source</th>"),
    ('<th class="r">Tage</th>', '<th class="r">Days</th>'),
    ("<th>Frist</th>", "<th>Holding period met</th>"),
    ("<th>Grundlage</th>", "<th>Basis</th>"),
    ("<th>Los (Tx:vout)</th>", "<th>Lot (tx:vout)</th>"),
    ("<th>Adresse</th>", "<th>Address</th>"),
    ("Keine Lose zugeordnet.", "No lots assigned."),
    ("Keine Inputs im Cache.", "No inputs in cache."),
    ("<dt>Steuernummer</dt>", "<dt>Tax number</dt>"),
    ("<dt>Anschrift</dt>", "<dt>Address</dt>"),
    ("<dt>E-Mail</dt>", "<dt>Email</dt>"),
    ("<dt>Finanzamt</dt>", "<dt>Tax office</dt>"),
    ("<dt>FA-Anschrift</dt>", "<dt>Tax office address</dt>"),
    ("<dt>Sachbearbeiter</dt>", "<dt>Case officer</dt>"),
    ("Bericht Sat-Geschichte", "Sat History Report"),
    ("Steuernummer ", "Tax number "),
    ("Steuerjahr ", "Tax year "),
    (" Jahr(e) ·", " year(s) ·"),
    ("Haltefrist ", "Holding period "),
    ("erstellt ", "created "),
    (" · Seite \"", " · Page \""),
    ("\n    Stichtag\n", "\n    Reference date\n"),
    ("\n    Abgang\n", "\n    Disposal\n"),
    ("    Netto ", "    Net "),
    ("<td>ja</td>", "<td>yes</td>"),
    ("<td><b>nein</b></td>", "<td><b>no</b></td>"),
    ("<strong>ja</strong>", "<strong>yes</strong>"),
    ("<strong>nein</strong>", "<strong>no</strong>"),
    ('<html lang="de"', '<html lang="en"'),
]

_KNOTEN_ART = re.compile(
    r"(^|\s)(Extern \(unaufgelöst\)|Intern|Extern)(?= · |\s*$)"
)
_KNOTEN_EN = {
    "Intern": "Internal",
    "Extern": "External",
    "Extern (unaufgelöst)": "External (unresolved)",
}

_DATUM = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_DEZIMAL = re.compile(r"(?<![\w,])(\d+),(\d+)(?![\w,])")


def _dynamische_paare() -> list[tuple[str, str]]:
    """Texte mit vorhandener Übersetzung (i18n-Schlüssel, tx_classify)."""
    paare: list[tuple[str, str]] = []
    try:
        from core import i18n, tax as tax_mod

        for key in (tax_mod.SCHLUESSEL_KEINE_BERATUNG,
                    tax_mod.SCHLUESSEL_HINWEIS_ONCHAIN):
            de, en = i18n.t_lang("de", key), i18n.t_lang("en", key)
            if de and en and de != en:
                paare.append((de, en))
        for alias in ("Eigenverwahrung",):
            if getattr(tax_mod, "BERICHT_WALLET_ALIAS_STANDARD", "") == alias:
                paare.append((alias, "Self-custody"))
    except Exception:
        pass
    try:
        from core import tx_classify

        for de, en in getattr(tx_classify, "_LABELS", {}).values():
            if de and en:
                paare.append((de, en))
    except Exception:
        pass
    return paare


def _sichtbar(text: str) -> str:
    """Datum/Zahl im Text (nicht in Tags/CSS) auf englisches Format."""
    teile = re.split(r"(<[^>]+>)", text)
    for i, t in enumerate(teile):
        if t.startswith("<"):
            continue
        t = _KNOTEN_ART.sub(lambda m: m[1] + _KNOTEN_EN[m[2]], t)
        t = _DATUM.sub(lambda m: f"{m[3]}-{m[2]}-{m[1]}", t)
        teile[i] = _DEZIMAL.sub(r"\1.\2", t)
    return "".join(teile)


def uebersetze_html(html: str) -> str:
    """Deutschen Bericht ins Englische übertragen."""
    kopf, trenner, rumpf = html.partition("</style>")
    if not trenner:
        kopf, rumpf = "", html
    # Lange Texte zuerst — kurze Bausteine stecken teils in langen.
    paare = _dynamische_paare() + _TABELLE
    paare.sort(key=lambda p: len(p[0]), reverse=True)
    for de, en in paare:
        kopf = kopf.replace(de, en)
        rumpf = rumpf.replace(de, en)
    # @page-Kopf/Fuß im CSS: nur Datum (Zahlen dort sind CSS).
    kopf = _DATUM.sub(lambda m: f"{m[3]}-{m[2]}-{m[1]}", kopf)
    rumpf = _sichtbar(rumpf)
    return kopf + trenner + rumpf
