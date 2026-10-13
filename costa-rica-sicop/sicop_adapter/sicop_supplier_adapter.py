"""Evidence-backed SICOP awarded-contract adapter.

Adapter version: 0.1.0

The public SICOP host returns a support/error page to direct HTTP clients in this
environment.  Official pages were therefore captured through the visible browser
and stored as raw evidence.  This adapter deterministically normalizes the
browser-extracted JSON evidence; it does not make live HTTP requests and it does
not contain credentials, cookies, session tokens, or CAPTCHA workarounds.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ADAPTER_VERSION = "0.1.0"
SUPPORTED_URL = "https://www.sicop.go.cr/app/module/pcont/public/ce-contracts-report"

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

_PROCEDURE_META: dict[str, dict[str, Any]] = {
    "2024LY-000001-0001102205": {
        "contract_detail_url": "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_no=CE202407004171&contract_mod_seq=00&typeExp=Y",
        "according_to_demand": True,
        "brand": "Stago",
        "models": {1: "00665", 2: "00595", 3: "00662", 4: "00673"},
        "extensions": "1 year; 3 possible one-year extensions; renewals notified 2025-10-10 and 2026-09-10",
    },
    "2024XE-000001-0001102501": {
        "contract_detail_url": "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_no=CE202402000158&contract_mod_seq=00&typeExp=Y",
        "according_to_demand": "Contract header flag is blank; delivery terms state según demanda; explicit awarded quantities and totals retained",
        "brand": "Abbott",
        "default_model": "ARCHITECT",
        "extensions": "8 months; no extension stated",
    },
    "2025XE-000003-0001102103": {
        "contract_detail_url": "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_no=CE202601000245&contract_mod_seq=00&typeExp=Y",
        "according_to_demand": True,
        "brand_lines": {17: "Abbott"},
        "models": {17: "ARCHITECT"},
        "extensions": "6 months",
    },
    "2025LD-000018-0001102207": {
        "contract_detail_url": "https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_COJ_COQ038_O.jsp?contract_no=CE202601000805&contract_mod_seq=00&typeExp=Y",
        "according_to_demand": True,
        "brand_lines": {31: "Roche"},
        "models": {31: "cobas"},
        "extensions": "3 months; final act describes approximately 2 months or until threshold",
    },
}


def _number(value: Any) -> float | int | None:
    """Parse SICOP Spanish-formatted numeric text without conflating decimals."""
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        return None
    if "," in text:
        normalized = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        normalized = text.replace(".", "")
    elif "." in text and len(text.rsplit(".", 1)[1]) == 3:
        normalized = text.replace(".", "")
    else:
        normalized = text
    number = float(normalized)
    return int(number) if number.is_integer() else number


def _iso_date(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unsupported SICOP date format: {value!r}")


def _iter_evidence(source: Any, default_dir: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    path = Path(source) if isinstance(source, (str, Path)) and not str(source).startswith("http") else default_dir
    if path.is_file():
        paths = [path]
    elif path.is_dir():
        paths = sorted(path.glob("*_extracted.json"))
    else:
        raise FileNotFoundError(f"SICOP evidence source not found: {path}")
    if not paths:
        raise FileNotFoundError(f"No *_extracted.json evidence files found in {path}")
    for evidence_path in paths:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        required = {"notice_id", "notice_url", "supplier_name", "items"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"{evidence_path.name}: missing required keys {sorted(missing)}")
        yield evidence_path, payload


class Adapter:
    """Trusted normalizer for the SICOP evidence captured in this project."""

    version = ADAPTER_VERSION

    def __init__(self, url: str = SUPPORTED_URL) -> None:
        if "sicop.go.cr" not in url:
            raise ValueError(f"Unsupported SICOP adapter URL: {url}")
        self.url = url
        workspace = Path(__file__).resolve().parent.parent
        self.default_evidence_dir = workspace / "outputs" / "sicop_supplier_pull" / "agent_work" / "raw"

    def extract(self, source: Any = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for evidence_path, record in _iter_evidence(source, self.default_evidence_dir):
            award_date = _iso_date(record.get("award_date_raw"))
            for seq, item in enumerate(record["items"], start=1):
                line = int(item.get("line_no") or seq)
                row = {
                    "source": "SICOP Costa Rica",
                    "country": "Costa Rica",
                    "country_code": "CR",
                    "publication_date": award_date,
                    "title": record.get("title", ""),
                    "title_english": "",
                    "description": record.get("title", ""),
                    "description_english": "",
                    "buyer": record.get("buyer", ""),
                    "buyer_english": "",
                    "classification": "IVD laboratory reagent/test",
                    "status": "Awarded / contracted",
                    "currency": record.get("currency", ""),
                    "amount": _number(item.get("price_total_raw")),
                    "awarding_agency_name": "Caja Costarricense de Seguro Social",
                    "awarding_agency_name_english": "Costa Rican Social Security Fund",
                    "supplier_name": record.get("supplier_name", ""),
                    "supplier_name_english": record.get("supplier_name", ""),
                    "awarded_date": award_date,
                    "contract_period": record.get("contract_period", ""),
                    "contract_period_english": "",
                    "item_no": seq,
                    "item_description": item.get("description", ""),
                    "item_description_english": "",
                    "item_uom": item.get("uom", ""),
                    "item_uom_english": "",
                    "quantity": _number(item.get("quantity_raw")),
                    "notice_id": record["notice_id"],
                    "notice_url": record["notice_url"],
                    "_source_workbook": evidence_path.name,
                    "_duplicate_rows_removed": 0,
                    "_dedupe_key": f"{record['notice_id']}|{record.get('supplier_name', '')}|{line}",
                    "medtech_filter_basis": "Official award item is an IVD laboratory reagent or diagnostic test",
                    "mapped_oem": "",
                    "mapped_oem_basis": "",
                    "mapped_oem_match_term": "",
                    "likely_oem": "",
                    "likely_oem_score": "",
                    "oem_match_terms": "",
                    "oem_match_basis": "",
                    "medtech_confidence": 1.0,
                }
                if list(row) != CANONICAL_COLUMNS:
                    raise RuntimeError("Canonical SICOP row column order drifted")
                rows.append(row)
        return rows

    def extract_extended(self, source: Any = None) -> list[dict[str, Any]]:
        """Return canonical rows plus contract, price, brand, and evidence fields."""
        canonical = self.extract(source)
        source_records = {
            rec["notice_id"]: rec for _, rec in _iter_evidence(source, self.default_evidence_dir)
        }
        extended: list[dict[str, Any]] = []
        for row in canonical:
            record = source_records[row["notice_id"]]
            item = record["items"][int(row["item_no"]) - 1]
            line = int(item.get("line_no") or row["item_no"])
            meta = _PROCEDURE_META.get(row["notice_id"], {})
            brand = meta.get("brand", meta.get("brand_lines", {}).get(line, ""))
            model = meta.get("models", {}).get(line, meta.get("default_model", ""))
            ext = dict(row)
            ext.update({
                "procedure_no": record.get("procedure_no", row["notice_id"]),
                "hospital_buying_unit": record.get("buyer", ""),
                "contract_no": record.get("contract_no", ""),
                "contract_notification_date": _iso_date(record.get("contract_date_raw")),
                "brand": brand,
                "analyzer_model": model,
                "test_or_segment": item.get("description", ""),
                "awarded_quantity": _number(item.get("quantity_raw")),
                "unit_price": _number(item.get("unit_price_raw")),
                "total_awarded": _number(item.get("price_total_raw")),
                "duration_and_extensions": meta.get("extensions", record.get("contract_period", "")),
                "according_to_demand": meta.get("according_to_demand", ""),
                "estimated_annual_consumption": _number(record.get("estimated_annual_consumption_raw")),
                "estimated_annual_consumption_currency": record.get("estimated_annual_consumption_currency", ""),
                "contract_detail_url": meta.get("contract_detail_url", ""),
                "supplier_product_code": item.get("supplier_product_code", ""),
                "unit_price_source_text": item.get("unit_price_raw", ""),
                "total_source_text": item.get("price_total_raw", ""),
            })
            extended.append(ext)
        return extended

    def extract_targets(self, source: Any, targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        rows = self.extract(source)
        by_notice: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_notice.setdefault(row["notice_id"], []).append(row)
        return {
            target["target_key"]: by_notice[target.get("notice_id", "")]
            for target in targets
            if target.get("notice_id") in by_notice
        }


def create_adapter(url: str = SUPPORTED_URL) -> Adapter:
    return Adapter(url)

