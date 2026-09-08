"""
Hintergrund-Vorgänge mit Fortschritt und Abbruch.

Ein Rescan läuft Minuten. Im Browser braucht das eine Kennung, über die sich
Fortschritt abfragen und der Vorgang beenden lässt.

Unterschied zum vorhandenen cancellable_output: Ein Abbruch hier beendet die
Abfrage selbst, nicht nur ihre Ausgabe.
"""
from __future__ import annotations

import contextvars
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

_zwischenstand: contextvars.ContextVar["Fortschritt | None"] = contextvars.ContextVar(
    "job_zwischenstand", default=None
)
_fortschritt_lock = threading.Lock()
_fortschritte: list["Fortschritt"] = []

#: Optional: Web-Job-Log zusätzlich ausgeben (Terminal-Steuerung).
_log_spiegel: Callable[["Job", str], None] | None = None
_log_spiegel_lock = threading.Lock()

#: Optional: nach Job-Ende (Status-Mails o. ä.).
_fertig_hook: Callable[["Job"], None] | None = None
_fertig_hook_lock = threading.Lock()

#: Globaler Herzschlag: „Moment noch“ nennt keinen Job — deshalb höchstens
#: alle INTERVALL Sekunden *einmal*, und nur wenn *kein* paralleler Job
#: irgendetwas ins Log geschrieben hat.
_herz_global_lock = threading.Lock()
_letzte_log_ausgabe_global = time.monotonic()


def setze_log_spiegel(fn: Callable[["Job", str], None] | None) -> None:
    """
    Hängt an jede Job-Log-Zeile (wie im Web-Log) einen Callback.

    ``None`` schaltet ab. Typisch: Terminal-Steuerung spiegelt nach stdout.
    """
    global _log_spiegel
    with _log_spiegel_lock:
        _log_spiegel = fn


def _rufe_log_spiegel(job: "Job", text: str) -> None:
    with _log_spiegel_lock:
        fn = _log_spiegel
    if fn is None:
        return
    try:
        fn(job, text)
    except Exception:
        pass


def _merke_globale_log_aktivitaet() -> None:
    """Jede echte Log-Zeile (beliebiger Job) setzt die globale Stille zurück."""
    global _letzte_log_ausgabe_global
    with _herz_global_lock:
        _letzte_log_ausgabe_global = time.monotonic()


def _versuche_globalen_herzschlag(job: "Job", text: str) -> bool:
    """
    Hängt *text* („Moment noch“) an *job*, wenn global INTERVALL Stille war.

    Rückgabe True, wenn geschrieben. Parallel laufende Jobs bekommen höchstens
    eine gemeinsame Zeile — nicht jeder Job eine eigene.

    Lock-Reihenfolge: zuerst globaler Herz-Lock (Slot belegen), dann Job-Log —
    nie umgekehrt verschachteln (Deadlock mit ``_haenge_log_an``).
    """
    global _letzte_log_ausgabe_global
    with _herz_global_lock:
        jetzt = time.monotonic()
        if jetzt - _letzte_log_ausgabe_global < Fortschritt.INTERVALL:
            return False
        # Slot belegen, bevor die Zeile hängt — sonst schreiben zwei Jobs.
        _letzte_log_ausgabe_global = jetzt
    with job._log_lock:
        job._log.append(text)
        job._log_zuletzt = time.monotonic()
    _rufe_log_spiegel(job, text)
    return True


def _reset_herzschlag_stand_fuer_tests(zeit: float | None = None) -> None:
    """Nur Tests: globale Stille-Uhr setzen (Default: jetzt)."""
    global _letzte_log_ausgabe_global
    with _herz_global_lock:
        _letzte_log_ausgabe_global = (
            time.monotonic() if zeit is None else float(zeit)
        )


def setze_fertig_hook(fn: Callable[["Job"], None] | None) -> None:
    """Callback nach Job-Ende (done/failed/cancelled). ``None`` schaltet ab."""
    global _fertig_hook
    with _fertig_hook_lock:
        _fertig_hook = fn


def _rufe_fertig_hook(job: "Job") -> None:
    with _fertig_hook_lock:
        fn = _fertig_hook
    if fn is None:
        return
    try:
        fn(job)
    except Exception:
        pass


def aktueller_zwischenstand() -> "Fortschritt | None":
    """
    Job-Fortschritt dieses Threads, sonst der zuletzt gestartete.

    Filter-Worker laufen in eigenen Threads ohne ContextVar — ohne den
    Fallback kämen Filter-Treffer nur auf stdout, nicht ins Web-Log.
    """
    stand = _zwischenstand.get()
    if stand is not None:
        return stand
    with _fortschritt_lock:
        return _fortschritte[-1] if _fortschritte else None


class Cancelled(Exception):
    """Wird geworfen, wenn ein Vorgang abgebrochen wurde."""


class JobQuotaExceeded(Exception):
    """Zu viele schwere Hintergrundvorgänge laufen bereits."""


#: Job-Arten in der Nav „Vorgänge“ (Nutzer + Start-Sync, der den Cache frischt).
NUTZER_JOB_KINDS = frozenset({
    "rescan",
    "verlauf",
    "trace",
    "trace-alle",
    "trace-tief",  # Wallet: wie Lücken schließen (bundled + Vorgänger-Txs)
    "labels",
    "sanctions",
    "sanctions-check",
    "wallet_sync",  # Start-Aktualisierung — Nutzer soll „wird frisch“ sehen
})


HEAVY_JOB_KINDS = NUTZER_JOB_KINDS | frozenset({"headers"})


@dataclass
class Job:
    """Ein laufender oder abgeschlossener Vorgang."""

    id: str
    kind: str
    label: str
    status: str = "running"          # running | done | failed | cancelled
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: object = None
    error: str = ""
    #: Freie Metadaten für die GUI (wallet_id, art, target, …).
    meta: dict = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event)
    _log: list[str] = field(default_factory=list)
    _log_lock: threading.Lock = field(default_factory=threading.Lock)
    #: monotonic()-Zeit der letzten echten Log-Zeile (auch ohne Fortschritt).
    _log_zuletzt: float = field(default_factory=time.monotonic)
    _on_done: Callable[["Job"], None] | None = field(default=None, repr=False)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise Cancelled()

    def sekunden_seit_letztem_log(self) -> float:
        """Wie lange gar nichts mehr ins Job-Log geschrieben wurde."""
        with self._log_lock:
            zuletzt = self._log_zuletzt
        return max(0.0, time.monotonic() - zuletzt)

    def progress(self, message: str, *, log: bool = False) -> None:
        """
        Fortschritts-Callback, kompatibel zu trace_engine.ProgressCallback.

        Bricht den Vorgang ab, sobald ein Abbruch angefordert wurde — dadurch
        wirkt der Abbruch an jeder Stelle, die Fortschritt meldet.

        *log=True* hängt die Zeile zusätzlich an die Job-Liste, damit die
        Oberfläche sie im Log-Bereich zeigen kann — vor dem Schritt, nicht danach.
        """
        self.raise_if_cancelled()
        self.message = message
        if log:
            self._haenge_log_an(message)

    def _haenge_log_an(self, text: str) -> None:
        with self._log_lock:
            self._log.append(text)
            self._log_zuletzt = time.monotonic()
        _merke_globale_log_aktivitaet()
        _rufe_log_spiegel(self, text)

    def ersetze_log_mit_praefix(self, praefix: str, text: str) -> bool:
        """
        Ersetzt die letzte Log-Zeile, die mit *praefix* beginnt.

        Für Filter-Treffer: „… — hole Block…“ wird zu „… — False Positive“
        bzw. „… — +n UTXO…“, ohne eine zweite Zeile. Fehlt die Zeile,
        wird *text* angehängt. Rückgabe: True wenn ersetzt.
        """
        self.raise_if_cancelled()
        self.message = text
        nadel = (praefix or "").strip()
        ersetzt = False
        with self._log_lock:
            if nadel:
                for i in range(len(self._log) - 1, -1, -1):
                    if self._log[i].startswith(nadel):
                        self._log[i] = text
                        ersetzt = True
                        break
            if not ersetzt:
                self._log.append(text)
            self._log_zuletzt = time.monotonic()
        _merke_globale_log_aktivitaet()
        _rufe_log_spiegel(self, text)
        return ersetzt

    def as_dict(self) -> dict:
        with self._log_lock:
            log = list(self._log)
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "log": log,
            "running": self.status == "running",
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "error": self.error,
            "meta": dict(self.meta or {}),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class Fortschritt:
    """
    Zwischenstand für lange Jobs.

    Phasen (Verbinden, Filter-Treffer, Blockinhalt) stehen sofort im Log.
    „Moment noch“ ist **global** (kein Job-Name daran): höchstens alle
    ``INTERVALL`` Sekunden eine Zeile, und nur wenn *kein* paralleler Job
    irgendetwas gemeldet hat. Hat sich der Tick-Text dieses Jobs geändert,
    kommt nach job-lokaler Stille der neue Text — nicht der Herzschlag.
    """

    #: Sekunden ohne Log-Ausgabe, bevor Herzschlag oder nachgezogener Tick.
    #: Bewusst 10 — nicht kürzer (AGENTS.md / Changelog).
    INTERVALL = 10.0
    HERZSCHLAG = "Moment noch"

    def __init__(self, job: Job):
        self.job = job
        self._lock = threading.Lock()
        self._text = ""
        self._geloggt = ""
        self._token = _zwischenstand.set(self)
        with _fortschritt_lock:
            _fortschritte.append(self)

    def close(self) -> None:
        _zwischenstand.reset(self._token)
        with _fortschritt_lock:
            if self in _fortschritte:
                _fortschritte.remove(self)

    def phase(self, text: str) -> None:
        """Ankündigung vor dem nächsten Schritt — sofort ins Log."""
        with self._lock:
            self._text = text
            self._geloggt = text
            self.job.progress(text, log=True)

    def ersetze(self, praefix: str, text: str) -> None:
        """Letzte passende Log-Zeile überschreiben (Filter-Treffer-Ergebnis)."""
        with self._lock:
            self._text = text
            self._geloggt = text
            self.job.ersetze_log_mit_praefix(praefix, text)

    def tick(self, text: str | None = None) -> None:
        """
        Aktuellen Stand merken.

        - Neuer Tick-Text: nach ``INTERVALL`` *job-lokaler* Stille ausgeschrieben.
        - Unverändert: globaler Herzschlag „Moment noch“ (Semaphor über alle Jobs).
        """
        with self._lock:
            if text:
                self._text = text
                self.job.progress(text)
            if not self._text:
                return
            if self._text != self._geloggt:
                # Fortschritt dieses Jobs — nur nach Stille *dieses* Job-Logs.
                if self.job.sekunden_seit_letztem_log() < self.INTERVALL:
                    return
                self._geloggt = self._text
                self.job.progress(self._text, log=True)
                return
            # Gleicher Stand: anonymer Herzschlag, global gedrosselt.
            self.job.raise_if_cancelled()
            _versuche_globalen_herzschlag(self.job, self.HERZSCHLAG)


def herzschlag(stand: Fortschritt, stop: threading.Event) -> None:
    """Globaler „Moment noch“-Takt über tick() — siehe Fortschritt."""
    pause = max(1.0, min(2.0, Fortschritt.INTERVALL / 5.0))
    while not stop.wait(pause):
        try:
            stand.tick()
        except Cancelled:
            return


class JobRegistry:
    """Verwaltet laufende Vorgänge. Threadsicher."""

    def __init__(self, *, keep: int = 20, max_parallel_heavy: int = 3):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep
        self.max_parallel_heavy = max(1, int(max_parallel_heavy))

    def running_heavy_count(self) -> int:
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.status == "running" and job.kind in HEAVY_JOB_KINDS)

    def heavy_capacity_available(self) -> bool:
        return self.running_heavy_count() < self.max_parallel_heavy

    def start(
        self,
        kind: str,
        label: str,
        func,
        *,
        meta: dict | None = None,
        on_done: Callable[[Job], None] | None = None,
    ) -> Job:
        """
        Startet *func(job)* in einem eigenen Thread.

        Der Rückgabewert von func landet in job.result; eine Cancelled-Ausnahme
        gilt als sauberer Abbruch, jede andere als Fehlschlag.
        """
        job = Job(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            label=label,
            meta=dict(meta or {}),
            _on_done=on_done,
        )
        with self._lock:
            running_heavy = sum(1 for existing in self._jobs.values() if existing.status == "running" and existing.kind in HEAVY_JOB_KINDS)
            if kind in HEAVY_JOB_KINDS and running_heavy >= self.max_parallel_heavy:
                raise JobQuotaExceeded(
                    "Zu viele schwere Vorgänge laufen bereits. Bitte warten oder einen laufenden Vorgang abbrechen."
                )
            self._jobs[job.id] = job
            self._aufraeumen()

        def lauf():
            try:
                job.result = func(job)
                job.status = "cancelled" if job.cancelled else "done"
            except Cancelled:
                job.status = "cancelled"
                job.message = "Abgebrochen."
            except SystemExit as exc:
                # main._setup_blockchain_client bricht so ab — sonst bleibt
                # der Job ewig auf running (letzte Log-Zeile klebt).
                job.status = "failed"
                if isinstance(exc.code, str) and exc.code.strip():
                    text = exc.code.strip()
                elif exc.code not in (None, 0):
                    text = str(exc.code)
                else:
                    text = str(exc) or "Vorgang beendet."
                job.error = text
                job.message = text
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.message = "Fehlgeschlagen."
                traceback.print_exc()
            finally:
                job.finished_at = time.time()
                if job._on_done is not None:
                    try:
                        job._on_done(job)
                    except Exception:
                        traceback.print_exc()
                _rufe_fertig_hook(job)

        threading.Thread(target=lauf, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status != "running":
            return False
        job.cancel()
        job.message = "Abbruch angefordert…"
        return True

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)

    def nutzer_jobs(self, *, recent_s: float = 10.0) -> list[Job]:
        """
        Nutzer-Jobs: alle running plus finished der letzten *recent_s* Sekunden.
        """
        jetzt = time.time()
        out: list[Job] = []
        with self._lock:
            for job in self._jobs.values():
                if job.kind not in NUTZER_JOB_KINDS:
                    continue
                if job.status == "running":
                    out.append(job)
                elif job.finished_at is not None and (jetzt - job.finished_at) <= recent_s:
                    out.append(job)
        out.sort(key=lambda j: j.started_at, reverse=True)
        return out

    def _aufraeumen(self) -> None:
        """Hält die Zahl abgeschlossener Vorgänge klein (Aufrufer hält das Lock)."""
        fertig = [j for j in self._jobs.values() if j.status != "running"]
        if len(fertig) <= self._keep:
            return
        fertig.sort(key=lambda j: j.finished_at or 0)
        for job in fertig[: len(fertig) - self._keep]:
            self._jobs.pop(job.id, None)


class ScanSchonGeplant(Exception):
    """Gleicher Wallet-Scan läuft bereits oder wartet in der Queue."""


class ScanQueue:
    """
    Eine Pipeline nur für UTXO-/Verlaufs-Scans (FIFO).

    Andere Job-Arten laufen parallel über JobRegistry.start. Die Queue
    überlebt GUI-Schließen solange der Server-Prozess lebt.
    """

    def __init__(self, jobs: JobRegistry):
        self._jobs = jobs
        self._lock = threading.Lock()
        # Einträge: queue_id, kind, wallet_id, wallet_name, label, scan_ab, factory
        self._wartend: list[dict] = []
        self._aktiv_job_id: str | None = None
        self._aktiv_key: tuple[str, str] | None = None
        self._aktiv_meta: dict = {}

    def _belegte_keys(self) -> set[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        if self._aktiv_key is not None:
            keys.add(self._aktiv_key)
        for eintrag in self._wartend:
            keys.add((eintrag["kind"], eintrag["wallet_id"]))
        return keys

    def einreihen(
        self,
        *,
        kind: str,
        wallet_id: str,
        wallet_name: str,
        label: str,
        factory: Callable[[Job], object],
        scan_ab: str = "",
    ) -> dict:
        """
        Startet sofort oder reiht ein.

        Rückgabe: Job-as_dict plus ``queue_status`` (running|queued) und
        ``scan_pipeline``-Snapshot. Bei Duplikat: ScanSchonGeplant.
        """
        if kind not in ("rescan", "verlauf"):
            raise ValueError(f"ScanQueue nur für rescan/verlauf, nicht {kind}")
        wid = str(wallet_id or "").strip()
        key = (kind, wid)
        with self._lock:
            if not self._jobs.heavy_capacity_available():
                raise JobQuotaExceeded(
                    "Zu viele schwere Vorgänge laufen bereits. Bitte warten oder einen laufenden Vorgang abbrechen."
                )
            if key in self._belegte_keys():
                raise ScanSchonGeplant(
                    f"{label} läuft bereits oder wartet in der Warteschlange."
                )
            if self._aktiv_job_id is None:
                return self._starte_gesperrt(
                    kind=kind,
                    wallet_id=wid,
                    wallet_name=wallet_name,
                    label=label,
                    scan_ab=scan_ab,
                    factory=factory,
                )
            qid = uuid.uuid4().hex[:12]
            self._wartend.append({
                "queue_id": qid,
                "kind": kind,
                "wallet_id": wid,
                "wallet_name": wallet_name,
                "label": label,
                "scan_ab": scan_ab or "",
                "factory": factory,
            })
            return {
                "id": qid,
                "kind": kind,
                "label": label,
                "status": "queued",
                "message": "Wartet…",
                "log": [],
                "running": False,
                "elapsed_s": 0,
                "error": "",
                "meta": {
                    "wallet_id": wid,
                    "wallet_name": wallet_name,
                    "art": "utxo" if kind == "rescan" else "verlauf",
                    "scan_ab": scan_ab or "",
                    "queue_id": qid,
                },
                "queue_status": "queued",
                "scan_pipeline": self._snapshot_gesperrt(),
            }

    def _starte_gesperrt(
        self,
        *,
        kind: str,
        wallet_id: str,
        wallet_name: str,
        label: str,
        scan_ab: str,
        factory: Callable[[Job], object],
    ) -> dict:
        meta = {
            "wallet_id": wallet_id,
            "wallet_name": wallet_name,
            "art": "utxo" if kind == "rescan" else "verlauf",
            "scan_ab": scan_ab or "",
        }
        job = self._jobs.start(
            kind,
            label,
            factory,
            meta=meta,
            on_done=self._nach_fertig,
        )
        self._aktiv_job_id = job.id
        self._aktiv_key = (kind, wallet_id)
        self._aktiv_meta = dict(meta)
        daten = job.as_dict()
        daten["queue_status"] = "running"
        daten["scan_pipeline"] = self._snapshot_gesperrt()
        return daten

    def _nach_fertig(self, job: Job) -> None:
        naechster = None
        with self._lock:
            if job.id != self._aktiv_job_id:
                return
            self._aktiv_job_id = None
            self._aktiv_key = None
            self._aktiv_meta = {}
            if self._wartend:
                naechster = self._wartend.pop(0)
        if naechster is None:
            return
        with self._lock:
            self._starte_gesperrt(
                kind=naechster["kind"],
                wallet_id=naechster["wallet_id"],
                wallet_name=naechster["wallet_name"],
                label=naechster["label"],
                scan_ab=naechster.get("scan_ab") or "",
                factory=naechster["factory"],
            )

    def _snapshot_gesperrt(self) -> dict:
        current = None
        if self._aktiv_job_id:
            job = self._jobs.get(self._aktiv_job_id)
            current = {
                "job_id": self._aktiv_job_id,
                "kind": self._aktiv_key[0] if self._aktiv_key else "",
                "wallet_id": self._aktiv_key[1] if self._aktiv_key else "",
                "label": job.label if job else "",
                "message": job.message if job else "",
                "meta": dict(self._aktiv_meta),
            }
        queued = [
            {
                "queue_id": e["queue_id"],
                "kind": e["kind"],
                "wallet_id": e["wallet_id"],
                "wallet_name": e["wallet_name"],
                "label": e["label"],
                "meta": {
                    "wallet_id": e["wallet_id"],
                    "wallet_name": e["wallet_name"],
                    "art": "utxo" if e["kind"] == "rescan" else "verlauf",
                },
            }
            for e in self._wartend
        ]
        return {"current": current, "queued": queued}

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot_gesperrt()

    def ist_geplant(self, kind: str, wallet_id: str) -> bool:
        key = (kind, str(wallet_id or "").strip())
        with self._lock:
            return key in self._belegte_keys()

