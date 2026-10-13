from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES
from scripts.probe_ted_medical_awards import DEFAULT_MEDICAL_CPVS, collect_rows

CONFIG = SOURCES["romania_sicap"]
EVIDENCE_PATH = Path("evidence") / "romania_direct_acquisition_snippet_120291101.json"
SEED_EVIDENCE_PATH = Path("evidence") / "romania_direct_acquisition_seed_notices.json"


def _load_fixture() -> dict[str, object]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def _load_seed_fixtures() -> list[dict[str, object]]:
    return json.loads(SEED_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I)
    return normalize_text(match.group(1)) if match else ""


def _coerce_to_iso_date(value: str) -> str:
    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _parse_raw_snippet_fields(snippet: str) -> dict[str, str]:
    notice_description = _first_match(
        r"Descriere\s+(.*?)\s+Cod si denumire CPV:",
        snippet,
    )
    return {
        "title": _first_match(r"Descriere\s+([^\.]+)", snippet),
        "notice_description": notice_description,
        "item_reference": _first_match(r"Numar de referinta:\s*([^\.]+)", snippet),
        "delivery_window": _first_match(r"Conditii de livrare:\s*.*?(\d+\s+zile\s+lucratoare)", snippet),
        "supplier_response_date": _first_match(r"Data de raspuns a ofertantului:\s*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", snippet),
        "authority_response_date": _first_match(
            r"Data de raspuns a autoritatii contractante:\s*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})",
            snippet,
        ),
        "direct_purchase_value": _first_match(r"Valoare cumparare directa:\s*([^\.]+\d,\d{2})", snippet),
    }


def _map_payload_to_row(payload: dict[str, object], query_text: str = "") -> dict[str, str]:
    mapped = payload["mapped_fields"]
    parsed = _parse_raw_snippet_fields(normalize_text(payload.get("raw_snippet")))
    title = normalize_text(mapped.get("title")) or parsed.get("title", "")
    closing_date = normalize_text(mapped.get("closing_date")) or parsed.get("authority_response_date", "")
    description = normalize_text(mapped.get("description")) or parsed.get("notice_description", "") or title
    awarded_currency = normalize_text(mapped.get("awarded_currency")) or normalize_text(mapped.get("currency"))
    awarded_value = normalize_text(mapped.get("awarded_value")) or parsed.get("direct_purchase_value", "") or normalize_text(
        mapped.get("amount")
    )
    item_no = parsed.get("item_reference", "") or normalize_text(mapped.get("item_no"))
    contract_period = normalize_text(mapped.get("contract_period")) or parsed.get("delivery_window", "")
    row = OutputRow(
        source=CONFIG.source,
        country=CONFIG.country,
        country_cc=CONFIG.country_cc,
        publication_date=normalize_text(mapped.get("publication_date")),
        closing_date=closing_date,
        title=title,
        description=description,
        buyer=normalize_text(mapped.get("buyer")),
        classification=normalize_text(mapped.get("classification")),
        status="Awarded",
        currency=normalize_text(mapped.get("currency")),
        amount=normalize_text(mapped.get("amount")),
        awarding_supplier_name=normalize_text(mapped.get("awarding_supplier_name")),
        awarded_currency=awarded_currency,
        awarded_value=awarded_value,
        contract_period=contract_period,
        item_no=item_no,
        item_desc=normalize_text(mapped.get("item_desc")),
        item_uom=normalize_text(mapped.get("item_uom")),
        item_quantity=normalize_text(mapped.get("item_quantity")),
        item_unit_price=normalize_text(mapped.get("item_unit_price")),
        item_award=normalize_text(mapped.get("item_award")),
        notice_id=normalize_text(payload.get("notice_id")),
        notice_url=normalize_text(payload.get("notice_url")),
        query_text=query_text,
        scraped_at=utc_now_iso(),
        dedup_key=f"{CONFIG.key}|{normalize_text(payload.get('notice_id'))}|{item_no}",
    )
    return row.to_dict()


def map_notice_to_rows(query_text: str = "") -> list[dict[str, str]]:
    payload = _load_fixture()
    return [_map_payload_to_row(payload, query_text=query_text)]


def seed_rows(query_text: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for payload in _load_seed_fixtures():
        rows.append(_map_payload_to_row(payload, query_text=query_text))
    return rows


def smoke_probe() -> SmokeProbeResult:
    rows = map_notice_to_rows(query_text="fixture:official-public-snippet")
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=bool(rows)
        and all(
            [
                rows[0]["notice_id"],
                rows[0]["closing_date"],
                rows[0]["title"],
                rows[0]["status"],
                rows[0]["currency"],
                rows[0]["amount"],
                rows[0]["awarded_currency"],
                rows[0]["awarded_value"],
                rows[0]["item_no"],
                rows[0]["classification"],
                rows[0]["item_desc"],
                rows[0]["item_uom"],
                rows[0]["item_quantity"],
                rows[0]["item_unit_price"],
                rows[0]["item_award"],
                rows[0]["notice_url"],
            ]
        ),
        mode="official-public-snippet-fixture",
        detail="Mapped one official public SICAP direct-acquisition snippet into a normalized medical item row after repeated direct page timeouts.",
        sample_rows=rows,
    )


def live_window_rows(date_from: str, date_to: str, page_size: int = 50) -> list[dict[str, str]]:
    del page_size
    rows = []
    for row in seed_rows(query_text=f"seed-public-direct-acquisition:{date_from}..{date_to}"):
        publication_date = _coerce_to_iso_date(row.get("publication_date") or "")
        closing_date = _coerce_to_iso_date(row.get("closing_date") or "")
        effective_date = publication_date or closing_date
        if effective_date and date_from <= effective_date <= date_to:
            rows.append(row)
    return rows


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 50) -> list[dict[str, str]]:
    """Use TED as the broad live Romania award source; SICAP remains the richer fallback evidence path."""
    limit = max(1, min(page_size, 100))
    return collect_rows(
        "ROU",
        date_from,
        date_to,
        limit=limit,
        pages=1,
        cpvs=list(DEFAULT_MEDICAL_CPVS),
    )
