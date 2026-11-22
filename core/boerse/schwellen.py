"""Schwellen für Auszahlung↔Empfang. Defaults entsprechen dem bisherigen Verhalten."""
from __future__ import annotations

from dataclasses import dataclass

FENSTER_VOR_S = 3600
FENSTER_NACH_S = 72 * 3600
MAX_DELTA_SATS = 0
MAX_DELTA_REL = 0.0

# Minuten-Buckets fürs Kalibrier-Log (obere Grenze, offen).
_ZEIT_BUCKETS = (1, 5, 15, 60, 180, 720, 4320)
# Relative Abweichung.
_REL_BUCKETS = (0.0, 0.0001, 0.001, 0.01, 0.05)


def _als_int(roh: object, default: int, *, min_v: int = 0, max_v: int | None = None) -> int:
    if roh is None or str(roh).strip() == "":
        return default
    try:
        wert = int(str(roh).strip())
    except (TypeError, ValueError):
        return default
    if wert < min_v:
        return min_v
    if max_v is not None and wert > max_v:
        return max_v
    return wert


def _als_float(roh: object, default: float, *, min_v: float = 0.0, max_v: float | None = None) -> float:
    if roh is None or str(roh).strip() == "":
        return default
    text = str(roh).strip().replace(",", ".")
    try:
        wert = float(text)
    except (TypeError, ValueError):
        return default
    if wert < min_v:
        return min_v
    if max_v is not None and wert > max_v:
        return max_v
    return wert


def _als_bool(roh: object, default: bool = False) -> bool:
    if roh is None or str(roh).strip() == "":
        return default
    if isinstance(roh, bool):
        return roh
    return str(roh).strip().casefold() in {"1", "true", "ja", "on", "yes", "ein"}


@dataclass(frozen=True)
class Schwellen:
    """Einstellbare Strenge. Ohne Angabe gelten die bisherigen festen Werte."""

    fenster_vor_s: int = FENSTER_VOR_S
    fenster_nach_s: int = FENSTER_NACH_S
    max_delta_sats: int = MAX_DELTA_SATS
    max_delta_rel: float = MAX_DELTA_REL
    gebuehr_als_toleranz: bool = False
    auto: bool = False
    auto_adresse: bool = True
    auto_min_abstand_s: int = 0

    def als_dict(self) -> dict:
        return {
            "fenster_vor_s": self.fenster_vor_s,
            "fenster_nach_s": self.fenster_nach_s,
            "max_delta_sats": self.max_delta_sats,
            "max_delta_rel": self.max_delta_rel,
            "gebuehr_als_toleranz": self.gebuehr_als_toleranz,
            "auto": self.auto,
            "auto_adresse": self.auto_adresse,
            "auto_min_abstand_s": self.auto_min_abstand_s,
        }

    def env_werte(self) -> dict[str, str]:
        return {
            "ZUORDNUNG_FENSTER_VOR_S": str(self.fenster_vor_s),
            "ZUORDNUNG_FENSTER_NACH_S": str(self.fenster_nach_s),
            "ZUORDNUNG_MAX_DELTA_SATS": str(self.max_delta_sats),
            "ZUORDNUNG_MAX_DELTA_REL": format(self.max_delta_rel, "g"),
            "ZUORDNUNG_GEBUEHR_ALS_TOLERANZ": "1" if self.gebuehr_als_toleranz else "0",
            "ZUORDNUNG_AUTO": "1" if self.auto else "0",
            "ZUORDNUNG_AUTO_ADRESSE": "1" if self.auto_adresse else "0",
            "ZUORDNUNG_AUTO_MIN_ABSTAND_S": str(self.auto_min_abstand_s),
        }


def standard() -> Schwellen:
    return Schwellen()


def lese_zuordnung_einstellungen(werte: dict[str, str] | None) -> Schwellen:
    werte = werte or {}
    return Schwellen(
        fenster_vor_s=_als_int(werte.get("ZUORDNUNG_FENSTER_VOR_S"), FENSTER_VOR_S, max_v=30 * 24 * 3600),
        fenster_nach_s=_als_int(werte.get("ZUORDNUNG_FENSTER_NACH_S"), FENSTER_NACH_S, max_v=30 * 24 * 3600),
        max_delta_sats=_als_int(werte.get("ZUORDNUNG_MAX_DELTA_SATS"), MAX_DELTA_SATS, max_v=10_000_000),
        max_delta_rel=_als_float(werte.get("ZUORDNUNG_MAX_DELTA_REL"), MAX_DELTA_REL, max_v=1.0),
        gebuehr_als_toleranz=_als_bool(werte.get("ZUORDNUNG_GEBUEHR_ALS_TOLERANZ"), False),
        auto=_als_bool(werte.get("ZUORDNUNG_AUTO"), False),
        auto_adresse=_als_bool(werte.get("ZUORDNUNG_AUTO_ADRESSE"), True) if "ZUORDNUNG_AUTO_ADRESSE" in werte else True,
        auto_min_abstand_s=_als_int(werte.get("ZUORDNUNG_AUTO_MIN_ABSTAND_S"), 0, max_v=30 * 24 * 3600),
    )


def schwellen_aus_payload(payload: dict, bisher: Schwellen | None = None) -> Schwellen:
    """Übernimmt Felder aus der API; fehlende bleiben beim bisherigen Stand."""
    basis = bisher or standard()
    d = basis.als_dict()
    if "fenster_vor_s" in payload:
        d["fenster_vor_s"] = _als_int(payload.get("fenster_vor_s"), basis.fenster_vor_s, max_v=30 * 24 * 3600)
    if "fenster_nach_s" in payload:
        d["fenster_nach_s"] = _als_int(payload.get("fenster_nach_s"), basis.fenster_nach_s, max_v=30 * 24 * 3600)
    if "max_delta_sats" in payload:
        d["max_delta_sats"] = _als_int(payload.get("max_delta_sats"), basis.max_delta_sats, max_v=10_000_000)
    if "max_delta_rel" in payload:
        d["max_delta_rel"] = _als_float(payload.get("max_delta_rel"), basis.max_delta_rel, max_v=1.0)
    if "gebuehr_als_toleranz" in payload:
        d["gebuehr_als_toleranz"] = _als_bool(payload.get("gebuehr_als_toleranz"), basis.gebuehr_als_toleranz)
    if "auto" in payload:
        d["auto"] = _als_bool(payload.get("auto"), basis.auto)
    if "auto_adresse" in payload:
        d["auto_adresse"] = _als_bool(payload.get("auto_adresse"), basis.auto_adresse)
    if "auto_min_abstand_s" in payload:
        d["auto_min_abstand_s"] = _als_int(payload.get("auto_min_abstand_s"), basis.auto_min_abstand_s, max_v=30 * 24 * 3600)
    return Schwellen(**d)


def im_fenster(buchung_ts: int | None, ketten_ts: int | None, s: Schwellen | None = None) -> bool:
    s = s or standard()
    if buchung_ts is None or ketten_ts is None:
        return False
    return buchung_ts - s.fenster_vor_s <= ketten_ts <= buchung_ts + s.fenster_nach_s


def betrag_delta_sats(soll: int, empfang_sats: int, gebuehr_sats: int = 0, *, inkl_gebuehr: bool = False) -> int:
    delta = abs(int(empfang_sats) - int(soll))
    if not inkl_gebuehr:
        return delta
    geb = max(0, int(gebuehr_sats or 0))
    return min(
        delta,
        abs(int(empfang_sats) - (int(soll) + geb)),
        abs(int(empfang_sats) - abs(int(soll) - geb)),
    )


def betrag_passt(soll: int, empfang_sats: int, gebuehr_sats: int = 0, s: Schwellen | None = None) -> bool:
    s = s or standard()
    delta = betrag_delta_sats(soll, empfang_sats, gebuehr_sats, inkl_gebuehr=s.gebuehr_als_toleranz)
    if delta <= s.max_delta_sats:
        if s.max_delta_rel <= 0:
            return delta <= s.max_delta_sats and (s.max_delta_sats > 0 or delta == 0)
        basis = max(abs(int(soll)), 1)
        return (delta / basis) <= s.max_delta_rel or delta <= s.max_delta_sats
    if s.max_delta_rel > 0:
        basis = max(abs(int(soll)), 1)
        return (delta / basis) <= s.max_delta_rel
    return False


def zeit_abstand_s(buchung_ts: int | None, ketten_ts: int | None) -> int | None:
    if buchung_ts is None or ketten_ts is None:
        return None
    return int(ketten_ts) - int(buchung_ts)


def bucket_minuten(abstand_s: int | None) -> str:
    if abstand_s is None:
        return "unbekannt"
    minuten = abs(int(abstand_s)) / 60.0
    vor = 0
    for grenze in _ZEIT_BUCKETS:
        if minuten <= grenze:
            return f"{vor}-{grenze}"
        vor = grenze
    return f"gt{_ZEIT_BUCKETS[-1]}"


def bucket_rel(delta_rel: float | None) -> str:
    if delta_rel is None:
        return "unbekannt"
    wert = abs(float(delta_rel))
    if wert == 0:
        return "0"
    vor = 0.0
    for grenze in _REL_BUCKETS:
        if grenze == 0.0:
            continue
        if wert <= grenze:
            return f"{vor:g}-{grenze:g}"
        vor = grenze
    return f"gt{_REL_BUCKETS[-1]:g}"


def auto_erlaubt(n_kandidaten: int, abstand_zweit_s: int | None, adresse_trifft: bool, s: Schwellen) -> bool:
    """Nur eindeutige Treffer, die die strengen Auto-Kriterien erfüllen."""
    if not s.auto:
        return False
    if s.auto_adresse and not adresse_trifft:
        return False
    if n_kandidaten <= 0:
        return False
    if n_kandidaten == 1:
        return True
    # Mehrere Kandidaten: nur wenn ein Mindestabstand gesetzt ist und greift.
    if s.auto_min_abstand_s <= 0:
        return False
    if abstand_zweit_s is None:
        return False
    return abs(int(abstand_zweit_s)) >= s.auto_min_abstand_s
