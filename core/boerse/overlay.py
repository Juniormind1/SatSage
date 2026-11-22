"""Börsenlose für bestätigte Auszahlungs-Zuordnungen (M8).

Nur bestätigte Zuordnungen zählen. Vorschläge ändern den Steuerbericht
nicht. FIFO wird je Konto aus den Importfakten neu gerechnet, nicht
gespeichert. Fehler in einem Konto lassen die übrigen unberührt.
"""
from __future__ import annotations

import time
from pathlib import Path

from core.boerse import speicher
from core.boerse.fifo import BoerseLos, anzeige_name, fifo_konto
from core.log_redaktion import schreibe, schreibe_ausnahme


class BoerseKontext:
    """Lädt Zuordnungen und FIFO-Lose einmal je Auswertung."""

    def __init__(self, exchange_dir: Path | str | None = None):
        self.exchange_dir = Path(exchange_dir) if exchange_dir is not None else None
        self._lose: dict[tuple[str, int], tuple[BoerseLos, ...]] = {}
        self._geladen = False

    @classmethod
    def aus_speicher(cls, exchange_dir: Path | str | None = None) -> "BoerseKontext":
        ziel = exchange_dir
        if ziel is None:
            try:
                from core.paths import exchange_dir as standard_dir
                ziel = standard_dir()
            except Exception:
                ziel = None
        return cls(ziel)

    def lade(self) -> None:
        if self._geladen:
            return
        self._geladen = True
        start = time.perf_counter()
        wurzel = self.exchange_dir
        n_konten = n_bestaetigt = n_fehler = n_lose = 0
        if wurzel is None or not Path(wurzel).is_dir():
            schreibe("boerse_fifo_overlay", n_konten=0, n_bestaetigt=0, dauer_ms=0)
            return
        try:
            slugs = speicher.v2_slugs(Path(wurzel))
        except Exception as exc:
            schreibe_ausnahme("boerse_fifo_overlay_fehler", exc)
            return
        for slug in slugs:
            n_konten += 1
            try:
                zuordnungen = speicher.lies_zuordnungen(slug, Path(wurzel))
                bestaetigt = [z for z in zuordnungen if z.status == "bestaetigt"]
                if not bestaetigt:
                    continue
                buchungen = speicher.lies_buchungen(slug, Path(wurzel))
                quellen = speicher.lies_quellen(slug, Path(wurzel))
                typ = str(quellen.get("typ") or quellen.get("boerse") or slug)
                name = str(quellen.get("name") or "") or None
                zu_aus, _rest, fehler = fifo_konto(
                    buchungen, boerse_typ=typ, name=name or anzeige_name(slug, typ)
                )
                n_fehler += len(fehler)
                for z in bestaetigt:
                    n_bestaetigt += 1
                    lose = zu_aus.get(z.auszahlung_ref, ())
                    if not lose:
                        continue
                    schluessel = (str(z.txid).casefold(), int(z.vout))
                    # Eine bestätigte Zuordnung je Outpoint; spätere werden gezählt, nicht gemischt.
                    if schluessel in self._lose:
                        n_fehler += 1
                        continue
                    self._lose[schluessel] = lose
                    n_lose += len(lose)
            except Exception as exc:
                n_fehler += 1
                schreibe_ausnahme("boerse_fifo_konto_fehler", exc)
        dauer = int((time.perf_counter() - start) * 1000)
        schreibe(
            "boerse_fifo_overlay",
            n_konten=n_konten,
            n_bestaetigt=n_bestaetigt,
            n_lose=n_lose,
            n_fehler=n_fehler,
            dauer_ms=dauer,
        )

    def setze(self, txid: str, vout: int, lose: tuple[BoerseLos, ...] | list[BoerseLos]) -> None:
        """Für Tests: Lose ohne Speicher zuweisen."""
        self._geladen = True
        self._lose[(str(txid).casefold(), int(vout))] = tuple(lose)

    def lose_fuer_outpoint(self, txid: str, vout: int) -> tuple[BoerseLos, ...]:
        self.lade()
        return self._lose.get((str(txid).casefold(), int(vout)), ())
