"""Sanktionierte und gemeldete Bitcoin-Adressen (mehrere Quellen)."""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from core.import_limits import ImportBudget, add_direct_file, unpack_zip_limited
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from email.utils import parsedate_to_datetime
from pathlib import Path

SANCTIONED_CACHE_DIR = Path(__file__).resolve().parent / "sanctioned_cache"
SANCTIONED_JSON_NAME = "sanctioned_addresses_XBT.json"
SANCTIONED_TXT_NAME = "sanctioned_addresses_XBT.txt"
SANCTIONED_META_NAME = "sanctioned_addresses_XBT.meta.json"
SANCTIONED_ENTITIES_NAME = "sanctioned_entities_XBT.json"
SANCTIONED_ENTITIES_META_NAME = "sanctioned_entities_XBT.meta.json"
SANCTIONED_ADDRESS_INDEX_NAME = "sanctioned_address_index.json"
SDN_XML_NAME = "sdn_advanced.xml"

DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/0xB10C/"
    "ofac-sanctioned-digital-currency-addresses/lists/"
    "sanctioned_addresses_XBT.json"
)
DEFAULT_TXT_URL = (
    "https://raw.githubusercontent.com/0xB10C/"
    "ofac-sanctioned-digital-currency-addresses/lists/"
    "sanctioned_addresses_XBT.txt"
)
SDN_XML_URL = (
    "https://www.treasury.gov/ofac/downloads/sanctions/1.0/sdn_advanced.xml"
)
OPENSANCTIONS_INDEX_URL = (
    "https://data.opensanctions.org/datasets/latest/{dataset}/index.json"
)
BADD_BOYZ_URL = (
    "https://raw.githubusercontent.com/mitchellkrogza/"
    "Badd-Boyz-Bitcoin-Scammers/master/bitcoin-scammers.txt"
)

OPENSANCTIONS_SOURCES = (
    {
        "id": "opensanctions_il_mod_crypto",
        "name": "Israel NBCTF (OpenSanctions)",
        "entity_name": "Israel Sanctioned Crypto Wallets List",
        "category": "sanction",
        "dataset": "il_mod_crypto",
        "group_mode": "collapsed",
    },
    {
        "id": "opensanctions_us_fbi_lazarus",
        "name": "US FBI Lazarus Group (OpenSanctions)",
        "category": "sanction",
        "dataset": "us_fbi_lazarus_crypto",
        "group_mode": "organization",
    },
    {
        "id": "opensanctions_ransomwhere",
        "name": "ransomwhe.re (OpenSanctions)",
        "category": "ransomware",
        "dataset": "ransomwhere",
        "group_mode": "collapsed",
    },
)

CATEGORY_PRIORITY = {"sanction": 0, "ransomware": 1, "scam": 2, "abuse": 3}
CATEGORY_LABELS = {
    "sanction": "Sanktion",
    "ransomware": "Ransomware",
    "scam": "Scam",
    "abuse": "Missbrauch",
}

SOURCE_LABELS = {
    "ofac_0xb10c": "OFAC SDN (0xB10C)",
    "ofac_sdn": "OFAC SDN XML",
    "opensanctions_il_mod_crypto": "Israel NBCTF (OpenSanctions)",
    "opensanctions_us_fbi_lazarus": "US FBI Lazarus Group (OpenSanctions)",
    "opensanctions_ransomwhere": "ransomwhe.re (OpenSanctions)",
    "badd_boyz_scammers": "Badd-Boyz Bitcoin Scammers",
}
SOURCE_ORDER = tuple(SOURCE_LABELS.keys())

ADDRESS_TYPE_ORDER = ("p2pkh", "p2sh", "segwit", "taproot", "other")
ADDRESS_TYPE_LABELS = {
    "p2pkh": "Legacy (1…)",
    "p2sh": "P2SH (3…)",
    "segwit": "SegWit (bc1q…)",
    "taproot": "Taproot (bc1p…)",
    "other": "Sonstige",
}

SDN_NS = {
    "sdn": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML"
}
XBT_FEATURE_LABEL = "Digital Currency Address - XBT"

_USER_AGENT = "SatSage/1.0"
_ADDRESS_RE = re.compile(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,62}$|^bc1[a-z0-9]{25,90}$")
_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_EXPORT_ID_RE = re.compile(r"/(\d{14})-")


@dataclass
class SanctionEntityGroup:
    entity_id: str
    person: str
    aliases: list[str]
    programs: list[str]
    reasons: list[str]
    listed_date: str | None
    addresses: list[str]
    sources: list[str] = field(default_factory=list)
    category: str = "sanction"


def resolve_sanctioned_cache_dir(base: Path | None = None) -> Path:
    return base or SANCTIONED_CACHE_DIR


def _json_path(cache_dir: Path) -> Path:
    return cache_dir / SANCTIONED_JSON_NAME


def _txt_path(cache_dir: Path) -> Path:
    return cache_dir / SANCTIONED_TXT_NAME


def _meta_path(cache_dir: Path) -> Path:
    return cache_dir / SANCTIONED_META_NAME


def _entities_path(cache_dir: Path) -> Path:
    return cache_dir / SANCTIONED_ENTITIES_NAME


def _entities_meta_path(cache_dir: Path) -> Path:
    return cache_dir / SANCTIONED_ENTITIES_META_NAME


def _address_index_path(cache_dir: Path) -> Path:
    return cache_dir / SANCTIONED_ADDRESS_INDEX_NAME


def _sdn_xml_path(cache_dir: Path) -> Path:
    return cache_dir / SDN_XML_NAME


def _fetch_url(url: str, *, timeout: int = 60) -> bytes:
    payload, _ = _fetch_url_with_meta(url, timeout=timeout)
    return payload


def _fetch_url_with_meta(url: str, *, timeout: int = 60) -> tuple[bytes, dict]:
    from core.tls import ssl_context

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return resp.read(), {
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
        }


def _head_url(url: str, *, timeout: int = 20) -> dict:
    from core.tls import ssl_context

    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return {
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "content_length": resp.headers.get("Content-Length"),
        }


def _normalize_etag(etag: str | None) -> str | None:
    if not etag:
        return None
    return etag.strip().strip('"').lower()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None




def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def _parse_http_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _format_remote_stamp(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone().strftime("%d.%m.%Y %H:%M")
    dt = _parse_iso_datetime(value) or _parse_http_datetime(value)
    if dt:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    if len(value) >= 10 and value[4] == "-":
        return _format_listed_date(value[:10])
    return value


def _export_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _EXPORT_ID_RE.search(url)
    return match.group(1) if match else None


def _opensanctions_remote_meta(dataset: str) -> dict:
    index_url = OPENSANCTIONS_INDEX_URL.format(dataset=dataset)
    payload = json.loads(_fetch_url(index_url, timeout=20).decode("utf-8"))
    csv_url = None
    for resource in payload.get("resources", []):
        if resource.get("name") == "targets.simple.csv":
            csv_url = resource.get("url")
            break
    return {
        "last_export": payload.get("last_export") or payload.get("updated_at"),
        "export_id": _export_id_from_url(csv_url),
        "source_url": csv_url,
    }


def _local_source_stamp(
    source_info: dict,
    *,
    meta: dict | None,
    cache_dir: Path,
) -> datetime | None:
    for key in ("last_export", "last_modified", "fetched_at"):
        dt = _parse_iso_datetime(source_info.get(key))
        if dt:
            return dt
    dt = _parse_http_datetime(source_info.get("last_modified"))
    if dt:
        return dt

    source_id = source_info.get("id")
    if source_id == "ofac_sdn":
        xml_path = _sdn_xml_path(cache_dir)
        if xml_path.is_file():
            return datetime.fromtimestamp(xml_path.stat().st_mtime, UTC)

    fetched_at = (meta or {}).get("fetched_at")
    return _parse_iso_datetime(fetched_at)


@dataclass
class SourceUpdateCheck:
    source_id: str
    name: str
    status: str
    local_label: str | None = None
    remote_label: str | None = None
    detail: str = ""


def _check_opensanctions_source(
    source_id: str,
    source_info: dict,
    *,
    dataset: str,
    meta: dict | None,
    cache_dir: Path,
) -> SourceUpdateCheck:
    name = source_info.get("name") or _source_label(source_id)
    local_export = source_info.get("export_id") or _export_id_from_url(
        source_info.get("source_url")
    )
    local_export_label = _format_remote_stamp(
        source_info.get("last_export")
    ) or (local_export and f"Export {local_export}")
    try:
        remote = _opensanctions_remote_meta(dataset)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return SourceUpdateCheck(
            source_id=source_id,
            name=name,
            status="error",
            local_label=local_export_label,
            detail=f"Prüfung fehlgeschlagen: {exc}",
        )

    remote_export = remote.get("export_id")
    remote_label = _format_remote_stamp(remote.get("last_export")) or (
        f"Export {remote_export}" if remote_export else None
    )
    update_available = bool(
        remote_export and local_export and remote_export > local_export
    )
    if not update_available and remote.get("last_export"):
        local_dt = _local_source_stamp(source_info, meta=meta, cache_dir=cache_dir)
        remote_dt = _parse_iso_datetime(remote.get("last_export"))
        if local_dt and remote_dt:
            update_available = _ensure_utc(remote_dt) > _ensure_utc(local_dt)

    if update_available:
        detail = "neuere Version verfügbar"
        if remote_label:
            detail += f" (Stand: {remote_label})"
        status = "update_available"
    else:
        detail = "aktuell"
        status = "current"

    return SourceUpdateCheck(
        source_id=source_id,
        name=name,
        status=status,
        local_label=local_export_label,
        remote_label=remote_label,
        detail=detail,
    )


def _check_http_source(
    source_id: str,
    source_info: dict,
    *,
    url: str,
    meta: dict | None,
    cache_dir: Path,
) -> SourceUpdateCheck:
    name = source_info.get("name") or _source_label(source_id)
    local_label = _format_remote_stamp(
        source_info.get("last_modified") or source_info.get("last_export")
    )
    if not local_label:
        local_dt = _local_source_stamp(source_info, meta=meta, cache_dir=cache_dir)
        if local_dt:
            local_label = local_dt.astimezone().strftime("%d.%m.%Y %H:%M")

    try:
        remote_head = _head_url(url, timeout=20)
    except (OSError, urllib.error.URLError) as exc:
        return SourceUpdateCheck(
            source_id=source_id,
            name=name,
            status="error",
            local_label=local_label,
            detail=f"Prüfung fehlgeschlagen: {exc}",
        )

    remote_label = _format_remote_stamp(remote_head.get("last_modified"))
    local_etag = _normalize_etag(source_info.get("etag"))
    remote_etag = _normalize_etag(remote_head.get("etag"))
    update_available = False

    if local_etag and remote_etag:
        update_available = local_etag != remote_etag
        if not remote_label:
            remote_label = f"ETag {remote_etag[:12]}…"
    elif remote_head.get("last_modified"):
        remote_dt = _parse_http_datetime(remote_head.get("last_modified"))
        local_dt = _local_source_stamp(source_info, meta=meta, cache_dir=cache_dir)
        if remote_dt and local_dt:
            update_available = _ensure_utc(remote_dt) > _ensure_utc(local_dt)

    if update_available:
        detail = "neuere Version verfügbar"
        if remote_label:
            detail += f" (Stand: {remote_label})"
        status = "update_available"
    elif local_etag or remote_head.get("last_modified"):
        detail = "aktuell"
        status = "current"
    elif remote_etag:
        detail = "Referenz fehlt — einmal aktualisieren für Prüfung"
        status = "unknown"
    else:
        detail = "Prüfung fehlgeschlagen (keine Remote-Metadaten)"
        status = "unknown"

    return SourceUpdateCheck(
        source_id=source_id,
        name=name,
        status=status,
        local_label=local_label,
        remote_label=remote_label,
        detail=detail,
    )


def check_sanctions_source_updates(
    meta: dict | None,
    *,
    cache_dir: Path | None = None,
) -> list[SourceUpdateCheck]:
    """Prüft pro Quelle online, ob eine neuere Version verfügbar ist."""
    root = resolve_sanctioned_cache_dir(cache_dir)
    source_meta = _source_meta_by_id(meta)
    opensanctions_datasets = {
        spec["id"]: spec["dataset"] for spec in OPENSANCTIONS_SOURCES
    }
    default_urls = {
        "ofac_0xb10c": DEFAULT_SOURCE_URL,
        "ofac_sdn": SDN_XML_URL,
        "badd_boyz_scammers": BADD_BOYZ_URL,
    }
    results: list[SourceUpdateCheck] = []

    for source_id in SOURCE_ORDER:
        source_info = dict(source_meta.get(source_id) or {})
        source_info.setdefault("id", source_id)
        if source_info.get("status") == "error" and not source_info.get("source_url"):
            results.append(
                SourceUpdateCheck(
                    source_id=source_id,
                    name=_source_label(source_id),
                    status="skipped",
                    detail="lokal nicht geladen",
                )
            )
            continue

        if source_id in opensanctions_datasets:
            results.append(
                _check_opensanctions_source(
                    source_id,
                    source_info,
                    dataset=opensanctions_datasets[source_id],
                    meta=meta,
                    cache_dir=root,
                )
            )
            continue

        url = source_info.get("source_url") or default_urls.get(source_id)
        if not url:
            results.append(
                SourceUpdateCheck(
                    source_id=source_id,
                    name=_source_label(source_id),
                    status="skipped",
                    detail="keine Quell-URL",
                )
            )
            continue

        results.append(
            _check_http_source(
                source_id,
                source_info,
                url=url,
                meta=meta,
                cache_dir=root,
            )
        )

    return results


def print_sanctions_source_update_status(
    checks: list[SourceUpdateCheck],
) -> bool:
    """Gibt die Aktualitätsprüfung aus. Rückgabe: True wenn Updates verfügbar."""
    print(f"\n{'─' * 78}")
    print("  Aktualitätsprüfung (online)")
    print(f"{'─' * 78}")

    updates_available = False
    for check in checks:
        if check.status == "update_available":
            updates_available = True
        line = f"  {check.name}: {check.detail}"
        if check.local_label and check.status == "update_available":
            line += f"  [lokal: {check.local_label}]"
        print(line, flush=True)

    return updates_available


def _opensanctions_csv_url(dataset: str) -> str:
    index_url = OPENSANCTIONS_INDEX_URL.format(dataset=dataset)
    payload = json.loads(_fetch_url(index_url, timeout=30).decode("utf-8"))
    for resource in payload.get("resources", []):
        if resource.get("name") == "targets.simple.csv":
            return resource["url"]
    raise ValueError(f"targets.simple.csv nicht in OpenSanctions-Dataset {dataset}")


def _extract_btc_address(*values: str | None) -> str | None:
    for raw in values:
        if not raw:
            continue
        candidate = raw.strip()
        if _ADDRESS_RE.fullmatch(candidate):
            return candidate
    return None


def _parse_listed_date_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = _ISO_DATE_RE.search(text.strip())
    return match.group(1) if match else None


def _merge_unique_strings(existing: list[str], new_items: list[str]) -> list[str]:
    merged = list(existing)
    seen = set(existing)
    for item in new_items:
        if item and item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def _merge_address_record(
    existing: dict | None,
    *,
    source_id: str,
    category: str,
    person: str | None = None,
    programs: list[str] | None = None,
    reasons: list[str] | None = None,
    listed_date: str | None = None,
) -> dict:
    record = dict(existing or {})
    sources = list(record.get("sources") or [])
    if source_id not in sources:
        sources.append(source_id)
    record["sources"] = sources

    old_category = record.get("category")
    if not old_category:
        record["category"] = category
    else:
        record["category"] = min(
            old_category,
            category,
            key=lambda value: CATEGORY_PRIORITY.get(value, 99),
        )

    if person and (
        not record.get("person")
        or (record.get("category") != "sanction" and category == "sanction")
    ):
        record["person"] = person
    elif person and not record.get("person"):
        record["person"] = person

    record["programs"] = _merge_unique_strings(
        list(record.get("programs") or []),
        programs or [],
    )
    record["reasons"] = _merge_unique_strings(
        list(record.get("reasons") or []),
        reasons or [],
    )

    dates = [d for d in (record.get("listed_date"), listed_date) if d]
    if dates:
        record["listed_date"] = min(dates)
    return record


def _ingest_entity_groups(
    groups: list[SanctionEntityGroup],
    *,
    source_id: str,
    category: str,
    address_index: dict[str, dict],
    all_addresses: set[str],
) -> None:
    for group in groups:
        if source_id not in group.sources:
            group.sources.append(source_id)
        if not group.category:
            group.category = category
        for address in group.addresses:
            all_addresses.add(address)
            address_index[address] = _merge_address_record(
                address_index.get(address),
                source_id=source_id,
                category=group.category,
                person=group.person,
                programs=group.programs,
                reasons=group.reasons,
                listed_date=group.listed_date,
            )


def _normalize_addresses(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("Unerwartetes JSON-Format (Liste erwartet)")
    seen: set[str] = set()
    addresses: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        address = item.strip()
        if not address or address in seen:
            continue
        if not _ADDRESS_RE.fullmatch(address):
            continue
        seen.add(address)
        addresses.append(address)
    if not addresses:
        raise ValueError("Keine gültigen Bitcoin-Adressen in der Quelldatei")
    return addresses


def _parse_json_payload(payload: bytes) -> list[str]:
    data = json.loads(payload.decode("utf-8"))
    return _normalize_addresses(data)


def _parse_txt_payload(payload: bytes) -> list[str]:
    lines = [
        line.strip()
        for line in payload.decode("utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return _normalize_addresses(lines)


def _parse_opensanctions_csv(
    payload: bytes,
    *,
    source_id: str,
    source_name: str,
    category: str,
    group_mode: str,
    entity_name: str | None = None,
) -> list[SanctionEntityGroup]:
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8"))))
    wallets: list[dict] = []
    organization_name: str | None = None

    for row in rows:
        schema = (row.get("schema") or "").strip()
        if schema == "Organization":
            organization_name = (row.get("name") or organization_name or "").strip() or None
            continue

        address = _extract_btc_address(row.get("identifiers"), row.get("name"))
        if not address:
            continue

        dataset = (row.get("dataset") or source_name).strip() or source_name
        sanctions = (row.get("sanctions") or "").strip()
        listed_date = _parse_listed_date_from_text(sanctions) or _parse_listed_date_from_text(
            row.get("first_seen")
        )
        person = (row.get("name") or "").strip()
        if person == address or person.lower() == "cryptocurrency wallet":
            person = organization_name or dataset

        wallets.append(
            {
                "id": (row.get("id") or f"{source_id}-{address}").strip(),
                "address": address,
                "person": person or source_name,
                "programs": [dataset] if dataset else [],
                "reasons": [sanctions] if sanctions else [source_name],
                "listed_date": listed_date,
            }
        )

    if not wallets:
        return []

    groups: list[SanctionEntityGroup] = []
    if group_mode == "collapsed":
        listed_dates = [item["listed_date"] for item in wallets if item["listed_date"]]
        groups.append(
            SanctionEntityGroup(
                entity_id=source_id,
                person=entity_name or source_name,
                aliases=[],
                programs=[source_name],
                reasons=[CATEGORY_LABELS.get(category, category)],
                listed_date=max(listed_dates) if listed_dates else None,
                addresses=sorted({item["address"] for item in wallets}),
                sources=[source_id],
                category=category,
            )
        )
        return groups

    if group_mode == "organization":
        org = organization_name or source_name
        groups.append(
            SanctionEntityGroup(
                entity_id=source_id,
                person=org,
                aliases=[],
                programs=[source_name],
                reasons=[source_name],
                listed_date=min(
                    (item["listed_date"] for item in wallets if item["listed_date"]),
                    default=None,
                ),
                addresses=sorted({item["address"] for item in wallets}),
                sources=[source_id],
                category=category,
            )
        )
        return groups

    for item in wallets:
        groups.append(
            SanctionEntityGroup(
                entity_id=item["id"],
                person=item["person"],
                aliases=[],
                programs=item["programs"],
                reasons=item["reasons"],
                listed_date=item["listed_date"],
                addresses=[item["address"]],
                sources=[source_id],
                category=category,
            )
        )
    return groups


def _parse_badd_boyz_txt(payload: bytes) -> list[SanctionEntityGroup]:
    addresses: list[str] = []
    reasons: list[str] = []
    for raw_line in payload.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        reason = "Bitcoin Scam"
        if "#" in line:
            address_part, comment = line.split("#", 1)
            reason = comment.strip() or reason
            line = address_part.strip()
        address = _extract_btc_address(line)
        if not address:
            continue
        addresses.append(address)
        reasons.append(reason)

    if not addresses:
        return []

    unique_reasons = sorted(set(reasons))
    return [
        SanctionEntityGroup(
            entity_id="badd_boyz_scammers",
            person="Badd-Boyz Bitcoin Scammers",
            aliases=[],
            programs=["Badd-Boyz-Bitcoin-Scammers"],
            reasons=unique_reasons[:12] + (
                [f"… +{len(unique_reasons) - 12} weitere"] if len(unique_reasons) > 12 else []
            ),
            listed_date=None,
            addresses=sorted(set(addresses)),
            sources=["badd_boyz_scammers"],
            category="scam",
        )
    ]


def _fetch_opensanctions_groups(
    spec: dict,
) -> tuple[list[SanctionEntityGroup], str, dict]:
    index_url = OPENSANCTIONS_INDEX_URL.format(dataset=spec["dataset"])
    index_payload = json.loads(_fetch_url(index_url, timeout=30).decode("utf-8"))
    csv_url = None
    for resource in index_payload.get("resources", []):
        if resource.get("name") == "targets.simple.csv":
            csv_url = resource["url"]
            break
    if not csv_url:
        raise ValueError(f"targets.simple.csv nicht in OpenSanctions-Dataset {spec['dataset']}")
    payload, http_meta = _fetch_url_with_meta(csv_url, timeout=180)
    groups = _parse_opensanctions_csv(
        payload,
        source_id=spec["id"],
        source_name=spec["name"],
        category=spec["category"],
        group_mode=spec["group_mode"],
        entity_name=spec.get("entity_name"),
    )
    remote_meta = {
        "export_id": _export_id_from_url(csv_url),
        "last_export": index_payload.get("last_export") or index_payload.get("updated_at"),
        "etag": http_meta.get("etag"),
        "last_modified": http_meta.get("last_modified"),
    }
    return groups, csv_url, remote_meta


def _fetch_ofac_flat_addresses(
    source_url: str = DEFAULT_SOURCE_URL,
) -> tuple[list[str], str, dict]:
    try:
        payload, http_meta = _fetch_url_with_meta(source_url)
        addresses = _parse_json_payload(payload)
        return addresses, source_url, http_meta
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        payload, http_meta = _fetch_url_with_meta(DEFAULT_TXT_URL)
        addresses = _parse_txt_payload(payload)
        return addresses, DEFAULT_TXT_URL, http_meta


def _sdn_tag(elem) -> str:
    return elem.tag.split("}")[-1]


def _parse_sdn_date(date_elem) -> str | None:
    if date_elem is None:
        return None
    year = date_elem.find("sdn:Year", SDN_NS)
    if year is None or not (year.text or "").strip():
        return None
    parts = [year.text.strip()]
    month = date_elem.find("sdn:Month", SDN_NS)
    day = date_elem.find("sdn:Day", SDN_NS)
    if month is not None and (month.text or "").strip():
        parts.append(month.text.strip().zfill(2))
    if day is not None and (day.text or "").strip():
        parts.append(day.text.strip().zfill(2))
    return "-".join(parts)


def _format_listed_date(iso_date: str | None) -> str:
    if not iso_date:
        return "unbekannt"
    try:
        dt = datetime.strptime(iso_date[:10], "%Y-%m-%d")
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date


def _party_display_names(party) -> tuple[str, list[str]]:
    names: list[str] = []
    seen: set[str] = set()
    for documented in party.findall(".//sdn:DocumentedName", SDN_NS):
        parts = [
            part.text.strip()
            for part in documented.findall(".//sdn:NamePartValue", SDN_NS)
            if part.text and part.text.strip()
        ]
        if not parts:
            continue
        full = " ".join(parts)
        if full in seen:
            continue
        seen.add(full)
        names.append(full)
    if not names:
        return "Unbekannt", []
    return names[0], names[1:]


def _load_legal_basis_map(root) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in root.findall(
        "sdn:ReferenceValueSets/sdn:LegalBasisValues/sdn:LegalBasis",
        SDN_NS,
    ):
        text = (item.text or "").strip()
        if text:
            mapping[item.attrib["ID"]] = text
    return mapping


def _xbt_feature_type_id(root) -> str:
    feature = root.find(
        "sdn:ReferenceValueSets/sdn:FeatureTypeValues/"
        f"sdn:FeatureType[.='{XBT_FEATURE_LABEL}']",
        SDN_NS,
    )
    if feature is None:
        raise ValueError(f"{XBT_FEATURE_LABEL} nicht in SDN-XML gefunden")
    return feature.attrib["ID"]


def parse_sdn_xbt_entities(xml_path: Path) -> list[SanctionEntityGroup]:
    """Extrahiert OFAC-Entitäten mit XBT-Adressen aus ``sdn_advanced.xml``."""
    root = ET.parse(xml_path).getroot()
    xbt_id = _xbt_feature_type_id(root)
    legal_basis = _load_legal_basis_map(root)
    groups: list[SanctionEntityGroup] = []

    for party in root.findall("sdn:DistinctParties/sdn:DistinctParty", SDN_NS):
        entity_id = party.attrib.get("FixedRef") or party.attrib.get("ID", "")
        addresses = sorted({
            detail.text.strip()
            for detail in party.findall(
                f".//sdn:Feature[@FeatureTypeID='{xbt_id}']//sdn:VersionDetail",
                SDN_NS,
            )
            if detail.text and _ADDRESS_RE.fullmatch(detail.text.strip())
        })
        if not addresses:
            continue

        person, aliases = _party_display_names(party)
        programs: list[str] = []
        reasons: list[str] = []
        dates: list[str] = []

        entry = root.find(
            f"sdn:SanctionsEntries/sdn:SanctionsEntry[@ID='{entity_id}']",
            SDN_NS,
        )
        if entry is not None:
            for measure in entry.findall("sdn:SanctionsMeasure", SDN_NS):
                for comment in measure.findall("sdn:Comment", SDN_NS):
                    text = (comment.text or "").strip()
                    if text and text not in programs:
                        programs.append(text)
            for event in entry.findall("sdn:EntryEvent", SDN_NS):
                basis_id = event.attrib.get("LegalBasisID")
                if basis_id and basis_id in legal_basis:
                    reason = legal_basis[basis_id]
                    if reason not in reasons:
                        reasons.append(reason)
                listed = _parse_sdn_date(event.find("sdn:Date", SDN_NS))
                if listed:
                    dates.append(listed)

        listed_date = min(dates) if dates else None
        groups.append(
            SanctionEntityGroup(
                entity_id=entity_id,
                person=person,
                aliases=aliases,
                programs=programs,
                reasons=reasons,
                listed_date=listed_date,
                addresses=addresses,
                sources=["ofac_sdn"],
                category="sanction",
            )
        )

    groups.sort(key=lambda g: (g.person.lower(), g.entity_id))
    return groups


def _groups_to_payload(groups: list[SanctionEntityGroup]) -> dict:
    address_to_entity_id: dict[str, str] = {}
    for group in groups:
        for address in group.addresses:
            if address not in address_to_entity_id:
                address_to_entity_id[address] = group.entity_id
    return {
        "entities": [asdict(group) for group in groups],
        "address_to_entity_id": address_to_entity_id,
    }


def _groups_from_payload(payload: dict) -> list[SanctionEntityGroup]:
    entities = payload.get("entities")
    if not isinstance(entities, list):
        return []
    groups: list[SanctionEntityGroup] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        addresses = item.get("addresses") or []
        if not isinstance(addresses, list):
            addresses = []
        groups.append(
            SanctionEntityGroup(
                entity_id=str(item.get("entity_id", "")),
                person=str(item.get("person", "Unbekannt")),
                aliases=list(item.get("aliases") or []),
                programs=list(item.get("programs") or []),
                reasons=list(item.get("reasons") or []),
                listed_date=item.get("listed_date"),
                addresses=sorted(set(str(a) for a in addresses if a)),
                sources=list(item.get("sources") or []),
                category=str(item.get("category") or "sanction"),
            )
        )
    return groups


def load_sanctioned_meta(cache_dir: Path | None = None) -> dict | None:
    root = resolve_sanctioned_cache_dir(cache_dir)
    path = _meta_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_sanctioned_address_index(cache_dir: Path | None = None) -> dict[str, dict]:
    root = resolve_sanctioned_cache_dir(cache_dir)
    path = _address_index_path(root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_entity_lookup(
    groups: list[SanctionEntityGroup],
) -> tuple[dict[str, SanctionEntityGroup], dict[str, str]]:
    by_id: dict[str, SanctionEntityGroup] = {}
    addr_to_id: dict[str, str] = {}
    for group in groups:
        by_id[group.entity_id] = group
        for address in group.addresses:
            addr_to_id.setdefault(address, group.entity_id)
    return by_id, addr_to_id


def load_sanctioned_entities(
    *,
    cache_dir: Path | None = None,
) -> tuple[list[SanctionEntityGroup], dict | None]:
    root = resolve_sanctioned_cache_dir(cache_dir)
    path = _entities_path(root)
    meta = None
    meta_path = _entities_meta_path(root)
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = None
    if not path.is_file():
        return [], meta
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], meta
    return _groups_from_payload(payload), meta


def load_sanctioned_xbt_addresses(
    *,
    cache_dir: Path | None = None,
) -> tuple[frozenset[str], dict | None]:
    root = resolve_sanctioned_cache_dir(cache_dir)
    meta = load_sanctioned_meta(root)
    json_path = _json_path(root)
    if not json_path.is_file():
        return frozenset(), meta
    try:
        addresses = _parse_json_payload(json_path.read_bytes())
    except (OSError, ValueError, json.JSONDecodeError):
        return frozenset(), meta
    return frozenset(addresses), meta


def format_sanctioned_status(meta: dict | None, count: int | None = None) -> str:
    if not meta and not count:
        return "nicht geladen"
    n = count if count is not None else int(meta.get("count", 0) if meta else 0)
    fetched_at = (meta or {}).get("fetched_at")
    stamp = None
    if fetched_at:
        try:
            dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            stamp = dt.astimezone().strftime("%d.%m.%Y %H:%M")
        except ValueError:
            stamp = None
    source_count = len((meta or {}).get("sources") or [])
    if stamp and source_count:
        return f"{n:,} Adressen aus {source_count} Quelle(n) (Stand: {stamp})"
    if stamp:
        return f"{n:,} Adressen (Stand: {stamp})"
    return f"{n:,} Adressen"


def format_entities_status(
    meta: dict | None,
    *,
    group_count: int | None = None,
) -> str:
    if not meta and not group_count:
        return "nicht geladen"
    n = group_count if group_count is not None else int(meta.get("group_count", 0) if meta else 0)
    fetched_at = (meta or {}).get("fetched_at")
    if fetched_at:
        try:
            dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            stamp = dt.astimezone().strftime("%d.%m.%Y %H:%M")
            return f"{n:,} Gruppen (Stand: {stamp})"
        except ValueError:
            pass
    return f"{n:,} Gruppen"


def download_sdn_xml(
    *,
    cache_dir: Path | None = None,
    url: str = SDN_XML_URL,
    http_meta_out: dict | None = None,
) -> Path:
    root = resolve_sanctioned_cache_dir(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    print("Lade OFAC SDN-XML (sdn_advanced.xml)…", flush=True)
    payload, http_meta = _fetch_url_with_meta(url, timeout=300)
    path = _sdn_xml_path(root)
    path.write_bytes(payload)
    print(f"  → {len(payload):,} Bytes gespeichert.", flush=True)
    # Metadaten über einen Out-Parameter zurückgeben: pathlib.Path definiert
    # __slots__, eine Attribut-Zuweisung am Pfad wirft AttributeError.
    if http_meta_out is not None:
        http_meta_out.update(http_meta)
    return path


def update_sanctioned_entities_from_sdn(
    *,
    cache_dir: Path | None = None,
    sdn_path: Path | None = None,
    download_if_missing: bool = True,
) -> tuple[list[SanctionEntityGroup], dict]:
    root = resolve_sanctioned_cache_dir(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    xml_path = sdn_path or _sdn_xml_path(root)
    if not xml_path.is_file():
        if not download_if_missing:
            raise FileNotFoundError(f"SDN-XML nicht gefunden: {xml_path}")
        xml_path = download_sdn_xml(cache_dir=root)

    print("Parse OFAC-Entitäten (XBT)…", flush=True)
    groups = parse_sdn_xbt_entities(xml_path)
    return groups, {
        "source_url": SDN_XML_URL,
        "sdn_xml": xml_path.name,
        "group_count": len(groups),
        "address_count": sum(len(group.addresses) for group in groups),
    }


def _write_sanctioned_catalog(
    *,
    cache_dir: Path,
    addresses: list[str],
    groups: list[SanctionEntityGroup],
    address_index: dict[str, dict],
    meta: dict,
    entities_meta: dict,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _json_path(cache_dir).write_text(
        json.dumps(sorted(addresses), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _txt_path(cache_dir).write_text("\n".join(sorted(addresses)) + "\n", encoding="utf-8")
    _meta_path(cache_dir).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    payload = _groups_to_payload(groups)
    _entities_path(cache_dir).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _entities_meta_path(cache_dir).write_text(
        json.dumps(entities_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _address_index_path(cache_dir).write_text(
        json.dumps(address_index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def importiere_dateien(
    dateien: dict[str, bytes],
    *,
    cache_dir: Path | None = None,
) -> tuple[frozenset[str], dict]:
    """
    Übernimmt lokal beschaffte Listen-Dateien.

    Akzeptiert:
    - ``sanctioned_addresses_XBT.json`` / beliebiges ``.json`` (Adressliste)
    - ``.txt`` (eine Adresse je Zeile)
    - ``sdn_advanced.xml`` (nur speichern + Entity-Parse, wenn möglich)
    - ZIP mit denselben Namen
    - optional ``sanctioned_entities_XBT.json`` und Meta-/Index-Dateien
    """
    if not dateien:
        raise ValueError("Keine Dateien übergeben.")

    flach: dict[str, bytes] = {}
    budget = ImportBudget()
    for name, inhalt in dateien.items():
        n = Path(name or "").name.lower()
        if n.endswith(".zip"):
            for dateiname, dateiinhalt in unpack_zip_limited(inhalt, budget=budget):
                flach[Path(dateiname).name.lower()] = dateiinhalt
        else:
            add_direct_file(budget, name, inhalt)
            flach[n] = inhalt

    root = resolve_sanctioned_cache_dir(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()

    all_addresses: set[str] = set()
    address_index: dict[str, dict] = {}
    groups: list[SanctionEntityGroup] = []
    source_stats: list[dict] = []

    # Voller Cache-Satz aus ZIP/Dateien?
    kanon_json = SANCTIONED_JSON_NAME.lower()
    if kanon_json in flach:
        try:
            addrs = _parse_json_payload(flach[kanon_json])
            all_addresses.update(addrs)
            source_stats.append({
                "id": "import_json",
                "name": "Manueller Import (JSON)",
                "category": "sanction",
                "address_count": len(addrs),
                "status": "ok",
            })
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON-Liste ungültig: {exc}") from exc
    else:
        # Beliebige .json / .txt
        for name, inhalt in flach.items():
            if name.endswith(".json") and name not in (
                SANCTIONED_ENTITIES_NAME.lower(),
                SANCTIONED_META_NAME.lower(),
                SANCTIONED_ENTITIES_META_NAME.lower(),
                SANCTIONED_ADDRESS_INDEX_NAME.lower(),
            ):
                try:
                    addrs = _parse_json_payload(inhalt)
                except (ValueError, json.JSONDecodeError):
                    continue
                if addrs:
                    all_addresses.update(addrs)
                    source_stats.append({
                        "id": "import_json",
                        "name": f"Manueller Import ({name})",
                        "category": "sanction",
                        "address_count": len(addrs),
                        "status": "ok",
                    })
            elif name.endswith(".txt"):
                try:
                    addrs = _parse_txt_payload(inhalt)
                except ValueError:
                    continue
                if addrs:
                    all_addresses.update(addrs)
                    source_stats.append({
                        "id": "import_txt",
                        "name": f"Manueller Import ({name})",
                        "category": "scam",
                        "address_count": len(addrs),
                        "status": "ok",
                    })

    # SDN-XML optional
    xml_name = SDN_XML_NAME.lower()
    if xml_name in flach:
        xml_path = _sdn_xml_path(root)
        xml_path.write_bytes(flach[xml_name])
        try:
            ofac_groups = parse_sdn_xbt_entities(xml_path)
            groups.extend(ofac_groups)
            for g in ofac_groups:
                all_addresses.update(g.addresses)
            source_stats.append({
                "id": "ofac_sdn",
                "name": "OFAC SDN XML (Import)",
                "category": "sanction",
                "address_count": sum(len(g.addresses) for g in ofac_groups),
                "status": "ok",
            })
        except (OSError, ET.ParseError, ValueError) as exc:
            source_stats.append({
                "id": "ofac_sdn",
                "name": "OFAC SDN XML (Import)",
                "category": "sanction",
                "address_count": 0,
                "status": "error",
                "error": str(exc),
            })

    if SANCTIONED_ADDRESS_INDEX_NAME.lower() in flach:
        try:
            address_index = json.loads(
                flach[SANCTIONED_ADDRESS_INDEX_NAME.lower()].decode("utf-8")
            )
            if not isinstance(address_index, dict):
                address_index = {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            address_index = {}

    if not all_addresses and not groups:
        raise ValueError(
            "Keine Bitcoin-Adressen erkannt. Erwartet: JSON-Liste, TXT "
            "(eine Adresse je Zeile), SDN-XML oder ZIP mit Cache-Dateien."
        )

    for address in sorted(all_addresses):
        if address not in address_index:
            address_index[address] = _merge_address_record(
                None,
                source_id="import",
                category="sanction",
                programs=["Import"],
                reasons=["Manueller Datei-Import"],
            )

    # Fertige Entities-Datei: Gruppen daraus lesen, bevor wir überschreiben
    if not groups and SANCTIONED_ENTITIES_NAME.lower() in flach:
        try:
            payload = json.loads(
                flach[SANCTIONED_ENTITIES_NAME.lower()].decode("utf-8")
            )
            groups = _groups_from_payload(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            groups = []

    meta = {
        "fetched_at": fetched_at,
        "count": len(all_addresses),
        "sources": source_stats,
        "import": True,
    }
    entities_meta = {
        "fetched_at": fetched_at,
        "group_count": len(groups),
        "import": True,
    }

    _write_sanctioned_catalog(
        cache_dir=root,
        addresses=sorted(all_addresses),
        groups=groups,
        address_index=address_index,
        meta=meta,
        entities_meta=entities_meta,
    )
    return frozenset(all_addresses), meta


def update_sanctioned_lists(
    *,
    cache_dir: Path | None = None,
) -> tuple[frozenset[str], dict]:
    """
    Aktualisiert die lokale Bitcoin-Blacklist aus mehreren Quellen.

    Quellen mit robustem Download:
    - OFAC SDN (0xB10C + treasury.gov XML)
    - OpenSanctions: Israel NBCTF, FBI Lazarus, ransomwhe.re
    - GitHub: Badd-Boyz-Bitcoin-Scammers
    """
    root = resolve_sanctioned_cache_dir(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()

    all_addresses: set[str] = set()
    address_index: dict[str, dict] = {}
    all_groups: list[SanctionEntityGroup] = []
    source_stats: list[dict] = []

    print("  [1/6] OFAC SDN Flatliste (0xB10C)…", flush=True)
    try:
        ofac_addresses, ofac_url, ofac_http = _fetch_ofac_flat_addresses()
        for address in ofac_addresses:
            all_addresses.add(address)
            address_index[address] = _merge_address_record(
                address_index.get(address),
                source_id="ofac_0xb10c",
                category="sanction",
                programs=["OFAC SDN"],
                reasons=["US Treasury OFAC"],
            )
        source_stats.append({
            "id": "ofac_0xb10c",
            "name": "OFAC SDN (0xB10C)",
            "category": "sanction",
            "address_count": len(ofac_addresses),
            "source_url": ofac_url,
            "etag": ofac_http.get("etag"),
            "last_modified": ofac_http.get("last_modified"),
            "status": "ok",
        })
        print(f"      → {len(ofac_addresses):,} Adressen", flush=True)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        source_stats.append({
            "id": "ofac_0xb10c",
            "name": "OFAC SDN (0xB10C)",
            "category": "sanction",
            "address_count": 0,
            "status": "error",
            "error": str(exc),
        })
        print(f"      ⚠️  {exc}", flush=True)

    print("  [2/6] OFAC SDN-XML (Metadaten)…", flush=True)
    ofac_groups: list[SanctionEntityGroup] = []
    try:
        xml_path = _sdn_xml_path(root)
        sdn_http: dict = {}
        if not xml_path.is_file():
            xml_path = download_sdn_xml(cache_dir=root, http_meta_out=sdn_http)
        else:
            try:
                sdn_http = _head_url(SDN_XML_URL, timeout=20)
            except (OSError, urllib.error.URLError):
                sdn_http = {}
        ofac_groups = parse_sdn_xbt_entities(xml_path)
        _ingest_entity_groups(
            ofac_groups,
            source_id="ofac_sdn",
            category="sanction",
            address_index=address_index,
            all_addresses=all_addresses,
        )
        all_groups.extend(ofac_groups)
        source_stats.append({
            "id": "ofac_sdn",
            "name": "OFAC SDN XML",
            "category": "sanction",
            "group_count": len(ofac_groups),
            "address_count": sum(len(group.addresses) for group in ofac_groups),
            "source_url": SDN_XML_URL,
            "last_modified": sdn_http.get("last_modified"),
            "etag": sdn_http.get("etag"),
            "status": "ok",
        })
        print(
            f"      → {len(ofac_groups):,} Gruppen, "
            f"{sum(len(group.addresses) for group in ofac_groups):,} Adressen",
            flush=True,
        )
    except (OSError, urllib.error.URLError, ValueError, ET.ParseError) as exc:
        source_stats.append({
            "id": "ofac_sdn",
            "name": "OFAC SDN XML",
            "category": "sanction",
            "group_count": 0,
            "address_count": 0,
            "status": "error",
            "error": str(exc),
        })
        print(f"      ⚠️  {exc}", flush=True)

    step = 3
    for spec in OPENSANCTIONS_SOURCES:
        print(f"  [{step}/6] {spec['name']}…", flush=True)
        step += 1
        try:
            groups, csv_url, os_meta = _fetch_opensanctions_groups(spec)
            _ingest_entity_groups(
                groups,
                source_id=spec["id"],
                category=spec["category"],
                address_index=address_index,
                all_addresses=all_addresses,
            )
            all_groups.extend(groups)
            source_stats.append({
                "id": spec["id"],
                "name": spec["name"],
                "category": spec["category"],
                "group_count": len(groups),
                "address_count": sum(len(group.addresses) for group in groups),
                "source_url": csv_url,
                "export_id": os_meta.get("export_id"),
                "last_export": os_meta.get("last_export"),
                "etag": os_meta.get("etag"),
                "last_modified": os_meta.get("last_modified"),
                "status": "ok",
            })
            print(
                f"      → {len(groups):,} Gruppe(n), "
                f"{sum(len(group.addresses) for group in groups):,} Adressen",
                flush=True,
            )
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            source_stats.append({
                "id": spec["id"],
                "name": spec["name"],
                "category": spec["category"],
                "group_count": 0,
                "address_count": 0,
                "status": "error",
                "error": str(exc),
            })
            print(f"      ⚠️  {exc}", flush=True)

    print("  [6/6] Badd-Boyz Bitcoin Scammers…", flush=True)
    try:
        payload, badd_http = _fetch_url_with_meta(BADD_BOYZ_URL, timeout=60)
        groups = _parse_badd_boyz_txt(payload)
        _ingest_entity_groups(
            groups,
            source_id="badd_boyz_scammers",
            category="scam",
            address_index=address_index,
            all_addresses=all_addresses,
        )
        all_groups.extend(groups)
        source_stats.append({
            "id": "badd_boyz_scammers",
            "name": "Badd-Boyz Bitcoin Scammers",
            "category": "scam",
            "group_count": len(groups),
            "address_count": sum(len(group.addresses) for group in groups),
            "source_url": BADD_BOYZ_URL,
            "etag": badd_http.get("etag"),
            "last_modified": badd_http.get("last_modified"),
            "status": "ok",
        })
        print(
            f"      → {sum(len(group.addresses) for group in groups):,} Adressen",
            flush=True,
        )
    except (OSError, urllib.error.URLError, ValueError) as exc:
        source_stats.append({
            "id": "badd_boyz_scammers",
            "name": "Badd-Boyz Bitcoin Scammers",
            "category": "scam",
            "group_count": 0,
            "address_count": 0,
            "status": "error",
            "error": str(exc),
        })
        print(f"      ⚠️  {exc}", flush=True)

    if not all_addresses:
        raise OSError("Keine Adressen aus allen Quellen geladen")

    addresses_sorted = sorted(all_addresses)
    meta = {
        "fetched_at": fetched_at,
        "count": len(addresses_sorted),
        "sources": source_stats,
    }
    entities_meta = {
        "fetched_at": fetched_at,
        "group_count": len(all_groups),
        "address_count": len(addresses_sorted),
        "sources": source_stats,
    }
    _write_sanctioned_catalog(
        cache_dir=root,
        addresses=addresses_sorted,
        groups=all_groups,
        address_index=address_index,
        meta=meta,
        entities_meta=entities_meta,
    )
    return frozenset(addresses_sorted), meta


def update_sanctioned_xbt_addresses(
    *,
    cache_dir: Path | None = None,
    source_url: str = DEFAULT_SOURCE_URL,
    parse_entities: bool = True,
) -> tuple[frozenset[str], dict]:
    """Kompatibilitäts-Wrapper — nutzt ``update_sanctioned_lists``."""
    _ = source_url, parse_entities
    return update_sanctioned_lists(cache_dir=cache_dir)


def _category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def classify_btc_address_type(address: str) -> str:
    """Bitcoin-Adress-Standard anhand des Präfixes."""
    addr = address.strip()
    if addr.startswith("bc1p"):
        return "taproot"
    if addr.startswith("bc1q") or addr.startswith("bc1"):
        return "segwit"
    if addr.startswith("3"):
        return "p2sh"
    if addr.startswith("1"):
        return "p2pkh"
    return "other"


def count_address_types(addresses: list[str]) -> dict[str, int]:
    counts = {key: 0 for key in ADDRESS_TYPE_ORDER}
    for address in addresses:
        counts[classify_btc_address_type(address)] += 1
    return counts


def _source_label(source_id: str) -> str:
    return SOURCE_LABELS.get(source_id, source_id)


def _groups_for_source(
    groups: list[SanctionEntityGroup],
    source_id: str,
) -> list[SanctionEntityGroup]:
    matched = [group for group in groups if source_id in group.sources]
    matched.sort(key=lambda group: (group.person.lower(), group.entity_id))
    return matched


def _addresses_for_source(
    address_index: dict[str, dict],
    source_id: str,
) -> list[str]:
    return sorted(
        address
        for address, record in address_index.items()
        if source_id in (record.get("sources") or [])
    )


def _source_meta_by_id(meta: dict | None) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for item in (meta or {}).get("sources") or []:
        if isinstance(item, dict) and item.get("id"):
            mapping[item["id"]] = item
    return mapping


def _format_type_counts(counts: dict[str, int], *, compact: bool = False) -> str:
    if compact:
        return "  ".join(f"{counts.get(key, 0):,}" for key in ADDRESS_TYPE_ORDER)
    labeled = [
        f"{ADDRESS_TYPE_LABELS[key]}: {counts[key]:,}"
        for key in ADDRESS_TYPE_ORDER
        if counts.get(key, 0)
    ]
    return ", ".join(labeled) if labeled else "—"


def print_sanctions_overview(
    groups: list[SanctionEntityGroup],
    meta: dict | None,
    *,
    entities_meta: dict | None = None,
    address_index: dict[str, dict] | None = None,
) -> bool:
    """Übersicht pro Quelle. Rückgabe: True wenn mit q abgebrochen."""
    from display import cancellable_output, is_list_abort_requested

    address_index = (
        address_index if address_index is not None else load_sanctioned_address_index()
    )
    source_meta = _source_meta_by_id(meta or entities_meta)

    print(f"\n{'═' * 78}")
    print("  Sanktionslisten-Überblick")
    print(f"{'═' * 78}")

    fetched_at = (meta or entities_meta or {}).get("fetched_at")
    if fetched_at:
        try:
            dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            print(f"  Stand: {dt.astimezone().strftime('%d.%m.%Y %H:%M')}")
        except ValueError:
            print(f"  Stand: {fetched_at}")

    total_addresses = int((meta or {}).get("count", 0))
    total_entities = len(groups)
    if total_addresses:
        print(
            f"  Gesamt: {total_entities:,} Entitäten, {total_addresses:,} BTC-Adressen",
            flush=True,
        )

    known_sources = list(SOURCE_ORDER)
    extra_ids = sorted({
        source_id
        for record in address_index.values()
        for source_id in (record.get("sources") or [])
    } - set(known_sources))
    known_sources.extend(extra_ids)

    for source_id in known_sources:
        source_info = source_meta.get(source_id, {})
        source_name = source_info.get("name") or _source_label(source_id)
        category = source_info.get("category")
        category_label = _category_label(category) if category else None

        source_groups = _groups_for_source(groups, source_id)
        source_addresses = _addresses_for_source(address_index, source_id)
        if not source_groups and not source_addresses:
            continue

        entity_count = len(source_groups) if source_groups else int(
            source_info.get("group_count", 0) or 0
        )
        address_count = len(source_addresses) or int(
            source_info.get("address_count", 0) or 0
        )
        type_counts = count_address_types(source_addresses)

        print(f"\n{'─' * 78}")
        heading = f"  {source_name}"
        if category_label:
            heading += f"  [{category_label}]"
        print(heading)
        if source_groups:
            print(
                f"  Entitäten: {entity_count:,}   "
                f"BTC-Adressen: {address_count:,}",
                flush=True,
            )
        else:
            print(
                f"  Entitäten: — (nur Adress-Flatliste)   "
                f"BTC-Adressen: {address_count:,}",
                flush=True,
            )
        print(
            f"  Adress-Standards: {_format_type_counts(type_counts)}",
            flush=True,
        )

        if not source_groups:
            continue

        print(
            f"\n  {'Entität':<34} {'Listung':<12} {'Σ':>5}  "
            f"{'1…':>5}  {'3…':>5}  {'bc1q':>5}  {'bc1p':>5}",
            flush=True,
        )
        print(
            f"  {'-' * 34} {'-' * 12} {'-' * 5}  "
            f"{'-' * 5}  {'-' * 5}  {'-' * 5}  {'-' * 5}"
        )

        overview_ctx = cancellable_output(hint="Überblick — q zum Abbrechen")
        with overview_ctx:
            for group in source_groups:
                if is_list_abort_requested():
                    break
                entity_types = count_address_types(group.addresses)
                person = group.person
                if len(person) > 34:
                    person = person[:31] + "…"
                date_label = _format_listed_date(group.listed_date)
                if len(date_label) > 12:
                    date_label = date_label[:12]
                print(
                    f"  {person:<34} {date_label:<12} {len(group.addresses):>5,}  "
                    f"{entity_types.get('p2pkh', 0):>5,}  "
                    f"{entity_types.get('p2sh', 0):>5,}  "
                    f"{entity_types.get('segwit', 0):>5,}  "
                    f"{entity_types.get('taproot', 0):>5,}",
                    flush=True,
                )
        if overview_ctx.aborted:
            print(f"\n{'═' * 78}")
            return True

    print(f"\n{'═' * 78}")
    return False


def print_sanctioned_entity_groups(
    groups: list[SanctionEntityGroup],
    *,
    all_addresses: frozenset[str] | set[str] | None = None,
    max_addrs_preview: int = 3,
) -> bool:
    from display import abbrev_display, cancellable_output, is_list_abort_requested

    total_addrs = sum(len(g.addresses) for g in groups)
    print(f"\n{'═' * 72}")
    print(f"  Adress-Gruppen: {len(groups):,} Einträge, {total_addrs:,} Adressen")
    print(f"{'═' * 72}")

    if not groups:
        print("\n  Keine Gruppendaten geladen.")
        print("  Bitte unter Einstellungen (7) → [7] Aktualisiere Sanktions- & Blacklists.")
        return False

    mapped = {addr for group in groups for addr in group.addresses}
    if all_addresses:
        unmapped = sorted(all_addresses - mapped)
        if unmapped:
            print(
                f"\n  ⚠️  {len(unmapped):,} Adresse(n) ohne Gruppen-Zuordnung "
                f"(nur Index/Flatliste).",
                flush=True,
            )

    groups_ctx = cancellable_output(hint="Adress-Gruppen — q zum Abbrechen")
    with groups_ctx:
        for index, group in enumerate(groups, start=1):
            if is_list_abort_requested():
                break
            programs = ", ".join(group.programs) if group.programs else "—"
            reasons = "; ".join(group.reasons) if group.reasons else "—"
            date_label = _format_listed_date(group.listed_date)
            sources = ", ".join(group.sources) if group.sources else "—"
            print(f"\n  [{index}] {group.person}")
            print(f"      Kategorie: {_category_label(group.category)}")
            print(f"      Quellen: {sources}")
            if group.aliases:
                alias_preview = ", ".join(group.aliases[:4])
                if len(group.aliases) > 4:
                    alias_preview += f" … +{len(group.aliases) - 4}"
                print(f"      Alias(e): {alias_preview}")
            print(f"      Programm: {programs}")
            print(f"      Grund: {reasons}")
            print(f"      Datum: {date_label}")
            print(f"      Adressen: {len(group.addresses):,}")
            for addr in group.addresses[:max_addrs_preview]:
                print(f"        {abbrev_display(addr)}")
            if len(group.addresses) > max_addrs_preview:
                print(f"        … +{len(group.addresses) - max_addrs_preview} weitere")
    return groups_ctx.aborted


def print_sanctioned_entity_detail(group: SanctionEntityGroup) -> bool:
    from display import abbrev_display

    programs = ", ".join(group.programs) if group.programs else "—"
    reasons = "; ".join(group.reasons) if group.reasons else "—"
    sources = ", ".join(group.sources) if group.sources else "—"
    print(f"\n{'─' * 72}")
    print(f"  {group.person}  (ID {group.entity_id})")
    print(f"  Kategorie: {_category_label(group.category)}")
    print(f"  Quellen: {sources}")
    print(f"  Programm: {programs}")
    print(f"  Grund: {reasons}")
    print(f"  Datum: {_format_listed_date(group.listed_date)}")
    print(f"  Adressen ({len(group.addresses):,}):")
    from display import cancellable_output, is_list_abort_requested

    detail_ctx = cancellable_output(hint="Adressliste — q zum Abbrechen")
    with detail_ctx:
        for addr in group.addresses:
            if is_list_abort_requested():
                break
            print(f"    {abbrev_display(addr)}")
    return detail_ctx.aborted
