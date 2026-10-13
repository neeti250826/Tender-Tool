from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup


DATE_FROM = "2024-01-01"
DATE_TO = "2026-09-30"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CANONICAL_COLUMNS = [
    "source", "country", "country_code", "publication_date", "title",
    "title_english", "description", "description_english", "buyer",
    "buyer_english", "classification", "status", "currency", "amount",
    "awarding_agency_name", "awarding_agency_name_english", "supplier_name",
    "supplier_name_english", "awarded_date", "contract_period",
    "contract_period_english", "item_no", "item_description",
    "item_description_english", "item_uom", "item_uom_english", "quantity",
    "notice_id", "notice_url", "_source_workbook", "_duplicate_rows_removed",
    "_dedupe_key", "medtech_filter_basis", "mapped_oem", "mapped_oem_basis",
    "mapped_oem_match_term", "likely_oem", "likely_oem_score",
    "oem_match_terms", "oem_match_basis", "medtech_confidence",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_key(*parts: Any) -> str:
    return sha256_bytes("|".join(str(p or "") for p in parts).encode("utf-8"))


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def redact_contact_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[redacted-email]", text, flags=re.I)
    text = re.sub(r"(?<!\d)(?:\+?971[-\s]?)?(?:\d[-\s]?){8,12}(?!\d)", "[redacted-phone]", text)
    return clean(text)


def base_row(source: str) -> dict[str, str]:
    row = {column: "" for column in CANONICAL_COLUMNS}
    row.update({"source": source, "country": "United Arab Emirates", "country_code": "AE"})
    return row


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return len(materialized)


def soup_text(html: str) -> str:
    return clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-GB,en;q=0.9,ar;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    })
    return s


def fetch_to_file(
    s: requests.Session,
    url: str,
    path: Path,
    *,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"url": url, "method": method, "requested_at": now_iso(), "tls_verify": True}
    try:
        response = s.request(method, url, data=data, timeout=timeout, allow_redirects=True)
        body = response.content
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        meta.update({
            "ok": response.ok,
            "status_code": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("Content-Type", ""),
            "content_length": len(body),
            "sha256": sha256_bytes(body),
            "output_path": str(path.resolve()),
        })
    except Exception as exc:
        meta.update({"ok": False, "error_type": exc.__class__.__name__, "error": str(exc)})
    return meta


def iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and path.name != "evidence_manifest.json")


def build_manifest(root: Path) -> list[dict[str, Any]]:
    manifest = []
    for path in iter_files(root):
        manifest.append({
            "path": str(path.resolve()),
            "relative_path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return manifest
