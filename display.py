"""Anzeige-Hilfen: Verbose-Modus und Fortschrittszeilen."""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone

_verbose: bool = False


def set_verbose(enabled: bool) -> None:
    global _verbose
    _verbose = bool(enabled)


def is_verbose() -> bool:
    return _verbose


def abbrev_display(value: str, *, verbose: bool | None = None) -> str:
    """Kürzt lange IDs auf erste/letzte 8 Zeichen (nur wenn nicht verbose)."""
    if not value:
        return value
    use_verbose = is_verbose() if verbose is None else verbose
    if use_verbose or len(value) <= 19:
        return value
    return f"{value[:8]}...{value[-8:]}"


def format_tx_display(txid: str, *, verbose: bool | None = None) -> str:
    """TxID-Anzeige (gekürzt bei verbose=n)."""
    return abbrev_display(txid, verbose=verbose)


def _primary_address(
    address: str | None = None,
    addresses: list[str] | None = None,
) -> str | None:
    if address and address != "?":
        return address
    if addresses:
        for item in addresses:
            if item and item != "?":
                return item
    return None


def format_utxo_display(
    txid: str,
    vout: int,
    *,
    address: str | None = None,
    addresses: list[str] | None = None,
    verbose: bool | None = None,
) -> str:
    """UTXO-Referenz mit optionaler Adresse (gekürzt bei verbose=n)."""
    base = f"{abbrev_display(txid, verbose=verbose)}:{vout}"
    addr = _primary_address(address, addresses)
    if addr:
        return f"{base} ({abbrev_display(addr, verbose=verbose)})"
    return base


def format_utxo_ref(utxo_ref: str, *, verbose: bool | None = None) -> str:
    if ":" not in utxo_ref:
        return abbrev_display(utxo_ref, verbose=verbose)
    txid, vout = utxo_ref.rsplit(":", 1)
    try:
        return format_utxo_display(txid, int(vout), verbose=verbose)
    except ValueError:
        return abbrev_display(utxo_ref, verbose=verbose)


SATS_BTC_MIN_DISPLAY = 1_000_000  # 0.01 BTC — kleinste sinnvolle 2-Dezimal-Anzeige

_cancel_abort_event: threading.Event | None = None
_cancel_listener_done: threading.Event | None = None


def format_sats(sats: int | float) -> str:
    """Bis 100k sats als sats; ab 0.01 BTC als BTC (2 Dez.); dazwischen weiter sats."""
    amount = int(sats)
    if amount < SATS_BTC_MIN_DISPLAY:
        return f"{amount:,} sats"
    return f"{amount / 1e8:.2f} BTC"


def is_list_abort_requested() -> bool:
    return _cancel_abort_event is not None and _cancel_abort_event.is_set()


def _abort_input_available() -> bool:
    """True wenn Tastendruck (q) erkannt werden kann — auch PyCharm ohne isatty()."""
    if sys.stdin.isatty():
        return True
    if sys.platform == "win32":
        return True
    return sys.stdout.isatty()


def remind_abort_hint(hint: str = "q zum Abbrechen") -> None:
    if is_list_abort_requested() or _cancel_abort_event is None:
        return
    print(f"  ({hint})", flush=True)


def _stdin_abort_listener(abort: threading.Event, done: threading.Event) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            while not done.is_set():
                if abort.is_set():
                    return
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("", ""):
                        abort.set()
                        return
                    if ch.lower() == "q":
                        abort.set()
                        return
                time.sleep(0.05)
            return
        if not sys.stdin.isatty():
            return
        import select

        while not done.is_set():
            if abort.is_set():
                return
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not ready:
                continue
            ch = sys.stdin.read(1)
            if ch in ("", "", "q", "Q"):
                abort.set()
                return
    except Exception:
        return


class cancellable_output:
    """Hintergrund-Listener: q bricht lange Listen zwischen Einträgen ab."""

    def __init__(self, *, hint: str = "Lange Liste — q zum Abbrechen") -> None:
        self._hint = hint
        self._abort = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._nested = False
        self._user_aborted = False

    @property
    def aborted(self) -> bool:
        return self._user_aborted or self._abort.is_set()

    def __enter__(self):
        global _cancel_abort_event, _cancel_listener_done
        if _cancel_abort_event is not None:
            self._nested = True
            self._abort = _cancel_abort_event
            return self
        _cancel_abort_event = self._abort
        _cancel_listener_done = self._done
        if _abort_input_available():
            print(f"  ({self._hint})", flush=True)
            self._thread = threading.Thread(
                target=_stdin_abort_listener,
                args=(self._abort, self._done),
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        global _cancel_abort_event, _cancel_listener_done
        if self._nested:
            self._user_aborted = self._abort.is_set()
            return False
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=0.3)
        self._user_aborted = self._abort.is_set()
        _cancel_abort_event = None
        _cancel_listener_done = None
        if self._user_aborted:
            print("\n  → Ausgabe abgebrochen.", flush=True)
        return False


def utxo_block_height(utxo: dict) -> int | None:
    """Blockhöhe aus UTXO-Status (Cache/Esplora-Format), falls vorhanden."""
    status = utxo.get("status")
    if not isinstance(status, dict):
        return None
    raw = status.get("block_height")
    try:
        height = int(raw)
    except (TypeError, ValueError):
        return None
    return height if height > 0 else None


def summarize_utxo_cache_usage(utxos: list[dict]) -> tuple[int, int]:
    """Zählt verschiedene Blockhöhen und TxIDs in einer UTXO-Liste."""
    blocks: set[int] = set()
    txids: set[str] = set()
    for utxo in utxos:
        height = utxo_block_height(utxo)
        if height is not None:
            blocks.add(height)
        txid = str(utxo.get("txid", "")).strip()
        if txid:
            txids.add(txid)
    return len(blocks), len(txids)


def normalize_rpc_progress(raw: float) -> float:
    """Normiert Bitcoin-Core-Fortschritt (0..1 oder 0..100) auf 0..100."""
    value = float(raw)
    if 0.0 <= value <= 1.0:
        pct = value * 100.0
    else:
        pct = value
    return max(0.0, min(100.0, round(pct, 1)))


def format_block_height_with_date(
    height: int,
    *,
    tip_height: int | None = None,
    tip_time: int | None = None,
) -> str:
    """
    Blockhöhe mit geschätztem Datum.

    Mit Tip-Höhe/-Zeit: Rückwärts in 10-Minuten-Schritten (treffsicher im
    Scan-Bereich). Sonst Genesis + 10 Min — grob, aber ohne RPC.
    """
    hoehe = int(height)
    block_label = f"{hoehe:,}"
    if hoehe <= 0:
        return f"Block {block_label}"
    try:
        from main import BITCOIN_BLOCK_INTERVAL_SECONDS, BITCOIN_GENESIS_TIMESTAMP
    except ImportError:
        return f"Block {block_label}"
    intervall = BITCOIN_BLOCK_INTERVAL_SECONDS
    if tip_height is not None and tip_time is not None and int(tip_height) >= hoehe:
        stempel = int(tip_time) - (int(tip_height) - hoehe) * intervall
    else:
        stempel = BITCOIN_GENESIS_TIMESTAMP + hoehe * intervall
    datum = datetime.fromtimestamp(stempel, tz=timezone.utc).strftime("%d.%m.%Y")
    return f"Block {block_label} (≈ {datum})"


def melde_zwischenstand(
    message: str,
    *,
    log: bool = True,
    ersetze_praefix: str | None = None,
) -> None:
    """
    Leitet Scan-Ausgaben in den Web-Log-Bereich, falls ein Job läuft.

    stdout bleibt unverändert. Ohne aktiven Fortschritt (CLI ohne Web-Job)
    ist der Aufruf wirkungslos.

    *ersetze_praefix*: statt neuer Zeile die letzte Log-Zeile mit diesem
    Anfang überschreiben (Filter-Treffer → False Positive / UTXO-Fund).
    """
    text = (message or "").strip()
    if not text:
        return
    try:
        from core.jobs import aktueller_zwischenstand
    except ImportError:
        return
    stand = aktueller_zwischenstand()
    if stand is None:
        return
    if ersetze_praefix:
        stand.ersetze(ersetze_praefix, text)
    elif log:
        stand.phase(text)
    else:
        stand.tick(text)


def _write_progress_line(message: str, *, tty: bool, shown: bool, line_width: int) -> bool:
    """Schreibt eine Fortschrittszeile (TTY: überschreiben, sonst neue Zeile)."""
    if len(message) > line_width:
        message = message[: line_width - 1] + "…"
    if tty:
        padded = message.ljust(line_width)
        try:
            print(f"\r\033[2K{padded}", end="", flush=True)
        except Exception:
            print(f"\r{padded}", end="", flush=True)
        return True
    print(message, flush=True)
    return shown


def _overwrite_progress_line(message: str, *, line_width: int) -> None:
    """Überschreibt die aktuelle Zeile (auch in IDE-Konsolen ohne isatty)."""
    if len(message) > line_width:
        message = message[: line_width - 1] + "…"
    padded = message.ljust(line_width)
    try:
        print(f"\r\033[2K{padded}", end="", flush=True)
    except Exception:
        print(f"\r{padded}", end="", flush=True)


def _clear_progress_line(*, tty: bool, shown: bool, line_width: int) -> None:
    if not shown:
        return
    if tty:
        try:
            print("\r\033[2K", end="", flush=True)
        except Exception:
            print("\r" + " " * line_width + "\r", end="", flush=True)
    else:
        print(flush=True)


class Bip158ProgressLine:
    """Einzelzeile: ``Scanne UTXO <id> in Block <höhe> (≈ Datum)``.

    *verb* ändert den Anfang — nach dem Filter-Scan „Prüfe UTXO“, damit
    der Log nicht so aussieht, als liefe der Scan vom Tip nochmal von vorn.
    """

    _LINE_WIDTH = 110
    _FALLBACK_BLOCK_STEP = 2_000

    def __init__(
        self,
        *,
        verbose: bool | None = None,
        tip_height: int | None = None,
        tip_time: int | None = None,
        verb: str = "Scanne UTXO",
    ) -> None:
        self._verbose = is_verbose() if verbose is None else verbose
        self._tty = sys.stdout.isatty()
        self._shown = False
        self._last_utxo_id: str | None = None
        self._last_fallback_height = -1
        self._last_fallback_utxo: str | None = None
        self._tip_height = tip_height
        self._tip_time = tip_time
        self._verb = verb

    def update(
        self,
        block_height: int | None,
        utxo_id: str | None = None,
        *,
        checked: int | None = None,
        total: int | None = None,
    ) -> None:
        if block_height is None:
            return
        if utxo_id:
            self._last_utxo_id = utxo_id
        label = self._last_utxo_id or "…"
        if label != "…":
            label = format_utxo_ref(label, verbose=self._verbose)
        height = int(block_height)
        block_label = format_block_height_with_date(
            height,
            tip_height=self._tip_height,
            tip_time=self._tip_time,
        )
        message = f"{self._verb} {label} in {block_label}"
        if total and total > 0:
            c = int(checked or 0)
            pct = min(100, int(c * 100 / total)) if c < total else 100
            message += f" · {pct} %"
        # Dieselbe Taktung wie die Nicht-TTY-Stdout-Zeilen: ins Web-Log, damit
        # der Scan dort so lesbar ist wie in der Konsole — ohne Zeile je Block.
        utxo_changed = bool(utxo_id) and utxo_id != self._last_fallback_utxo
        height_step = height - self._last_fallback_height >= self._FALLBACK_BLOCK_STEP
        diskret = self._last_fallback_height < 0 or utxo_changed or height_step
        if diskret:
            self._last_fallback_height = height
            if utxo_id:
                self._last_fallback_utxo = utxo_id
        melde_zwischenstand(message, log=diskret)
        if self._tty:
            self._shown = _write_progress_line(
                message,
                tty=True,
                shown=self._shown,
                line_width=self._LINE_WIDTH,
            )
            return
        if diskret:
            self._shown = _write_progress_line(
                message,
                tty=False,
                shown=self._shown,
                line_width=self._LINE_WIDTH,
            )

    def clear(self) -> None:
        _clear_progress_line(
            tty=self._tty,
            shown=self._shown,
            line_width=self._LINE_WIDTH,
        )
        self._shown = False

    def finish(self) -> None:
        self.clear()
        if self._tty:
            print(flush=True)


class ScantxoutsetProgressLine:
    """Fortschritt für ``scantxoutset`` (0..100 %, 100 % erst bei Fertigstellung)."""

    _LINE_WIDTH = 100
    _FALLBACK_STEP = 5.0

    def __init__(self, *, label: str = "UTXO-Set") -> None:
        self._label = label
        self._tty = sys.stdout.isatty()
        self._shown = False
        self._last_fallback = -1.0
        self._last_pct = 0.0

    def update(
        self,
        percent: float,
        *,
        elapsed_s: float | None = None,
    ) -> None:
        pct = min(99.0, normalize_rpc_progress(percent))
        self._last_pct = pct
        message = f"Scanne {self._label} … {pct:.0f}%"
        if elapsed_s is not None and elapsed_s >= 1:
            message += f" ({int(elapsed_s)}s)"
        diskret = self._last_fallback < 0 or pct - self._last_fallback >= self._FALLBACK_STEP
        if diskret:
            self._last_fallback = pct
        melde_zwischenstand(message, log=diskret)
        if self._tty:
            self._shown = _write_progress_line(
                message,
                tty=True,
                shown=self._shown,
                line_width=self._LINE_WIDTH,
            )
            return
        if diskret:
            self._shown = _write_progress_line(
                message,
                tty=False,
                shown=self._shown,
                line_width=self._LINE_WIDTH,
            )

    def heartbeat(
        self,
        *,
        elapsed_s: float,
        note: str = "finalisiere auf Node",
        percent: float | None = None,
    ) -> None:
        """
        Lebenszeichen während ``scantxoutset start`` (z. B. 99 % oder
        noch kein Status). Ins Job-Log nur über den 10s-Tick, damit
        nicht jede Sekunde eine Zeile entsteht.
        """
        if percent is not None:
            pct = min(99.0, normalize_rpc_progress(percent))
            self._last_pct = pct
        else:
            pct = max(self._last_pct, 0.0)
        secs = max(1, int(elapsed_s))
        if pct > 0:
            message = (
                f"Scanne {self._label} … {pct:.0f}% "
                f"(läuft noch, {secs}s — {note})"
            )
        else:
            message = f"Scanne {self._label} … ({secs}s — {note})"
        # tick: Fortschritt.herzschlag schreibt spätestens alle 10s
        # den aktuellen Text statt „Moment noch“.
        melde_zwischenstand(message, log=False)
        self._shown = _write_progress_line(
            message,
            tty=self._tty,
            shown=self._shown,
            line_width=self._LINE_WIDTH,
        )

    def finish(self, *, success: bool = True) -> None:
        if success:
            message = f"Scanne {self._label} … 100%"
            melde_zwischenstand(message, log=True)
            self._shown = _write_progress_line(
                message,
                tty=self._tty,
                shown=self._shown,
                line_width=self._LINE_WIDTH,
            )
        elif self._shown:
            _clear_progress_line(
                tty=self._tty,
                shown=True,
                line_width=self._LINE_WIDTH,
            )
        if self._tty:
            print(flush=True)
        self._shown = False


class SanctionUtxoScanProgressLine:
    """Fortschritt: UTXO-Scan auf sanktionierten Adressen (pro Batch in %)."""

    _LINE_WIDTH = 110

    def __init__(self) -> None:
        self._shown = False
        self._batch_index: int | None = None

    def finalize_batch_line(self) -> None:
        """Schließt die aktuelle Batch-Zeile ab (neue Zeile für nächsten Batch)."""
        if self._shown:
            print(flush=True)
            self._shown = False

    def _finalize_batch_line(self) -> None:
        self.finalize_batch_line()

    def update(
        self,
        *,
        batch_index: int,
        total_batches: int,
        addrs_done_in_batch: int,
        addrs_in_batch: int,
        utxos_found: int = 0,
    ) -> None:
        if self._batch_index is not None and batch_index != self._batch_index:
            self._finalize_batch_line()
        self._batch_index = batch_index

        if addrs_in_batch > 0:
            pct = min(100.0, 100.0 * addrs_done_in_batch / addrs_in_batch)
        else:
            pct = 100.0
        message = (
            f"Scanne UTXOs auf sanktionierten Adressen — "
            f"Batch {batch_index}/{total_batches}: "
            f"{addrs_done_in_batch}/{addrs_in_batch} ({pct:.0f}%)"
        )
        if utxos_found:
            message += f"  —  {utxos_found} UTXO(s) gefunden"
        _overwrite_progress_line(message, line_width=self._LINE_WIDTH)
        self._shown = True

    def clear(self) -> None:
        if self._shown:
            try:
                print("\r\033[2K", end="", flush=True)
            except Exception:
                print("\r" + " " * self._LINE_WIDTH + "\r", end="", flush=True)
        self._shown = False
        self._batch_index = None

    def finish(self) -> None:
        self._finalize_batch_line()
        self._batch_index = None


def _ascii_progress_bar(pct: float, width: int = 12) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(width * pct / 100.0))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _short_fulcrum_label(host: str, max_len: int = 22) -> str:
    if len(host) <= max_len:
        return host
    keep = max_len - 1
    left = keep // 2
    right = keep - left
    return f"{host[:left]}…{host[-right:]}"


class SanctionParallelScanProgress:
    """
    Mehrzeilige Fortschrittsanzeige (Downloader-Stil) für parallele Worker.
    In IDE-Konsolen (PyCharm, ohne isatty): kompakte Einzeile mit \\r-Overwrite.
    """

    _LINE_WIDTH = 78
    _COMPACT_LINE_WIDTH = 140
    _NON_TTY_RENDER_INTERVAL = 0.3
    _BAR_WIDTH = 12

    def __init__(
        self,
        *,
        worker_labels: list[str],
        total_addrs: int,
        total_batches: int,
        title: str = "Sanktions-Scan",
        batch_label: str = "Batch",
        item_label: str = "Adressen",
    ) -> None:
        self._title = title
        self._batch_label = batch_label
        self._item_label = item_label
        self._worker_labels = worker_labels
        self._total_addrs = max(0, int(total_addrs))
        self._total_batches = max(0, int(total_batches))
        self._lock = threading.Lock()
        self._tty = sys.stdout.isatty()
        self._block_started = False
        self._addrs_done = 0
        self._batches_done = 0
        self._utxos_found = 0
        self._last_non_tty_print = 0.0
        self._non_tty_shown = False
        self._force_render = False
        self._worker_state: dict[int, dict[str, object]] = {}
        for worker_id, label in enumerate(worker_labels):
            self._worker_state[worker_id] = {
                "label": _short_fulcrum_label(label),
                "batch_index": 0,
                "done": 0,
                "total": 0,
                "pct": 0.0,
                "state": "idle",
            }
        self._render_lines = len(worker_labels) + 4

    def start(self) -> None:
        with self._lock:
            if self._tty:
                print(flush=True)
            else:
                print(
                    f"  {self._title} — {len(self._worker_labels)} Server parallel",
                    flush=True,
                )
            self._block_started = False
            self._render_locked()

    def update_worker(
        self,
        worker_id: int,
        *,
        batch_index: int,
        done: int,
        total: int,
        state: str = "scan",
        detail: str | None = None,
    ) -> None:
        with self._lock:
            worker = self._worker_state[worker_id]
            worker["batch_index"] = batch_index
            worker["done"] = done
            worker["total"] = total
            worker["pct"] = (100.0 * done / total) if total else 0.0
            worker["state"] = state
            if detail is not None:
                worker["detail"] = detail
            self._render_locked()

    def batch_complete(
        self,
        worker_id: int,
        *,
        addrs_in_batch: int,
        utxos_found: int | None = None,
    ) -> None:
        with self._lock:
            self._addrs_done += addrs_in_batch
            self._batches_done += 1
            if utxos_found is not None:
                self._utxos_found = utxos_found
            worker = self._worker_state[worker_id]
            worker["state"] = "done"
            worker["pct"] = 100.0
            worker["done"] = worker["total"]
            self._force_render = True
            self._render_locked()

    def set_utxos_found(self, count: int) -> None:
        with self._lock:
            self._utxos_found = count
            self._render_locked()

    def pause_for_output(self) -> None:
        with self._lock:
            if self._tty and self._block_started:
                print(flush=True)
                self._block_started = False
            elif self._non_tty_shown:
                print(flush=True)
                self._non_tty_shown = False
            remind_abort_hint("Sanktions-UTXO-Scan — q zum Abbrechen")

    def _worker_line(self, worker_id: int) -> str:
        worker = self._worker_state[worker_id]
        label = str(worker["label"])
        batch_index = int(worker["batch_index"] or 0)
        done = int(worker["done"])
        total = int(worker["total"])
        pct = float(worker["pct"])
        state = str(worker["state"])
        bar = _ascii_progress_bar(pct, self._BAR_WIDTH)
        detail = str(worker.get("detail") or "")
        if state == "idle":
            status = "bereit"
            progress = "      "
        elif state == "done":
            status = "fertig"
            progress = f"{total:>3}/{total:<3}"
        else:
            status = detail[:14] if detail else f"B{batch_index}"
            progress = f"{done:>3}/{total:<3}"
        return (
            f"  [{worker_id + 1}] {label:<22} {bar} "
            f"{pct:5.1f}%  {progress}  {status}"
        )

    def _summary_line(self) -> str:
        done = min(self._addrs_done, self._total_addrs) if self._total_addrs else self._addrs_done
        overall_pct = (
            min(100.0, 100.0 * done / self._total_addrs)
            if self._total_addrs
            else 0.0
        )
        return (
            f"  Gesamt {done:,}/{self._total_addrs:,} {self._item_label} "
            f"({overall_pct:4.1f}%)  ·  {self._batch_label} {self._batches_done}/"
            f"{self._total_batches}  ·  {self._utxos_found} Treffer"
        )

    def _compact_progress_line(self) -> str:
        summary = self._summary_line().strip()
        worker_bits: list[str] = []
        for worker_id in range(len(self._worker_labels)):
            worker = self._worker_state[worker_id]
            state = str(worker["state"])
            if state == "idle":
                continue
            label = str(worker["label"])[:10]
            pct = float(worker["pct"])
            if state == "done":
                worker_bits.append(f"[{worker_id + 1}]{label}:OK")
            else:
                worker_bits.append(f"[{worker_id + 1}]{label}:{pct:.0f}%")
        if not worker_bits:
            return summary
        line = f"{summary}  |  {' '.join(worker_bits)}"
        if len(line) > self._COMPACT_LINE_WIDTH:
            line = line[: self._COMPACT_LINE_WIDTH - 1] + "…"
        return line

    def _render_locked(self) -> None:
        if is_list_abort_requested():
            return
        lines = [
            f"  {self._title} — {len(self._worker_labels)} Server parallel",
            "  " + "─" * (self._LINE_WIDTH - 2),
        ]
        for worker_id in range(len(self._worker_labels)):
            lines.append(self._worker_line(worker_id))
        lines.append("  " + "─" * (self._LINE_WIDTH - 2))
        lines.append(self._summary_line())

        if not self._tty:
            now = time.monotonic()
            if (
                not self._force_render
                and now - self._last_non_tty_print < self._NON_TTY_RENDER_INTERVAL
            ):
                return
            self._force_render = False
            self._last_non_tty_print = now
            _overwrite_progress_line(
                self._compact_progress_line(),
                line_width=self._COMPACT_LINE_WIDTH,
            )
            self._non_tty_shown = True
            return

        if self._block_started:
            sys.stdout.write(f"\033[{self._render_lines}A")
        else:
            self._block_started = True

        for line in lines:
            if len(line) > self._LINE_WIDTH:
                line = line[: self._LINE_WIDTH - 1] + "…"
            sys.stdout.write("\033[2K" + line + "\n")
        sys.stdout.flush()

    def finish(self) -> None:
        with self._lock:
            if self._tty and self._block_started:
                print(flush=True)
                self._block_started = False
            elif self._non_tty_shown:
                _overwrite_progress_line(
                    self._compact_progress_line(),
                    line_width=self._COMPACT_LINE_WIDTH,
                )
                print(flush=True)
                self._non_tty_shown = False


class SanctionCheckProgressLine:
    """Fortschritt: Sanktionsprüfung pro Wallet-UTXO und Hop."""

    _LINE_WIDTH = 110

    def __init__(self) -> None:
        self._tty = sys.stdout.isatty()
        self._shown = False

    def update(
        self,
        *,
        wallet_utxo: str,
        hop: int,
        max_hops: int,
        addrs_checked: int,
        status: str,
    ) -> None:
        utxo_label = format_utxo_ref(wallet_utxo)
        message = (
            f"Prüfe {utxo_label}  Hop {hop}/{max_hops}  "
            f"{addrs_checked} Adresse(n)  —  {status}"
        )
        self._shown = _write_progress_line(
            message,
            tty=self._tty,
            shown=self._shown,
            line_width=self._LINE_WIDTH,
        )

    def clear(self) -> None:
        _clear_progress_line(
            tty=self._tty,
            shown=self._shown,
            line_width=self._LINE_WIDTH,
        )
        self._shown = False

    def finish(self) -> None:
        self.clear()
        if self._tty:
            print(flush=True)

