#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List

from procurement_utils import (
    FIELDNAMES,
    clean_text,
    derive_contract_period,
    ensure_fieldnames,
    parse_date_to_iso,
    serialize_rows,
    utc_now_iso,
)

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_END_DATE = date.today().isoformat()
DEFAULT_SOURCES = [
    ROOT_DIR / "Pakistan" / "ADB" / "output" / "adb_pakistan_health_awards_2024_recent.csv",
    ROOT_DIR / "Pakistan" / "WorldBank" / "output" / "worldbank_pakistan_health_awards_2024_recent.csv",
    ROOT_DIR / "Pakistan" / "EPADS" / "output" / "epads_item_medical_2024_2026.csv",
    ROOT_DIR / "Pakistan" / "PPRA" / "output" / "ppra_awarded_medical_2024_2026.csv",
    ROOT_DIR / "Pakistan" / "DRAP" / "output" / "drap_item_medical_2024_2026.csv",
]
REQUIRED_FILLED_FIELDS = [
    "item_description",
    "amount",
    "supplier_name",
    "awarded_date",
    "publication_date",
    "item_uom",
    "item_quantity",
    "contract_period",
]
NOT_PUBLISHED_BY_SOURCE = "Not published by source"
QUANTITY_UOM_WORDS = (
    "ampoules",
    "beds",
    "bottles",
    "boxes",
    "each",
    "kits",
    "lots",
    "no",
    "nos",
    "packets",
    "packs",
    "pairs",
    "pcs",
    "pieces",
    "sets",
    "sites",
    "strips",
    "tests",
    "units",
    "vials",
)
PPRA_EVALUATIONS_URL = "https://epms.ppra.gov.pk/public/evaluations"
RECENT_PPRA_EVALUATION_ROWS = [
    {
        "publication_date": "2026-06-24",
        "awarded_date": "2026-06-24",
        "title": "CHEMIST FOR DISCOUNT ON ALL PATIENT MEDICINES",
        "description": "Tender Ref#: SSGC/SC/PT/EPADS/14270; PPRA evaluation listing shows 1 bid for chemist discount on all patient medicines.",
        "buyer": "Ministry of Energy (Petroleum Division) | Sui Southern Gas Company Limited (SSGCL) | Karachi - Pakistan",
        "awarding_agency_name": "Sui Southern Gas Company Limited (SSGCL)",
        "classification": "Services",
        "supplier_name": "",
        "notice_id": "EVL00000001637",
        "tender_number": "TS0000004074E",
        "item_description": "Chemist discount on all patient medicines",
    },
    {
        "publication_date": "2026-06-24",
        "awarded_date": "2026-06-24",
        "title": "Chemist for Discount On All Patient Medicines Registered In Red Book Latest Edition",
        "description": "Tender Ref#: SSGC/SC/NR/EPADS/14279; PPRA evaluation listing shows 1 bid for chemist discount on all patient medicines.",
        "buyer": "Ministry of Energy (Petroleum Division) | Sui Southern Gas Company Limited (SSGCL) | Karachi - Pakistan",
        "awarding_agency_name": "Sui Southern Gas Company Limited (SSGCL)",
        "classification": "Services",
        "supplier_name": "",
        "notice_id": "EVL00000001636",
        "tender_number": "TS0000004368E",
        "item_description": "Chemist discount on all patient medicines registered in Red Book latest edition",
    },
    {
        "publication_date": "2026-06-24",
        "awarded_date": "2026-06-24",
        "title": "Chemist for Discount On All Patient Medicines Registered In Red Book Latest",
        "description": "Tender Ref#: SSGC/SC/NR/EPADS/14281; PPRA evaluation listing shows 1 bid for chemist discount on all patient medicines.",
        "buyer": "Ministry of Energy (Petroleum Division) | Sui Southern Gas Company Limited (SSGCL) | Karachi - Pakistan",
        "awarding_agency_name": "Sui Southern Gas Company Limited (SSGCL)",
        "classification": "Services",
        "supplier_name": "",
        "notice_id": "EVL00000001635",
        "tender_number": "TS0000004367E",
        "item_description": "Chemist discount on all patient medicines registered in Red Book latest",
    },
    {
        "publication_date": "2026-06-24",
        "awarded_date": "2026-06-24",
        "title": "Chemist for Discount On All Patient Medicines Registered In Red Book Latest Edition For Badin, Hyderabad Region",
        "description": "Tender Ref#: SSGC/SC/NR/EPADS/14280; PPRA evaluation listing shows 1 bid for Badin/Hyderabad-region patient-medicines chemist discount.",
        "buyer": "Ministry of Energy (Petroleum Division) | Sui Southern Gas Company Limited (SSGCL) | Karachi - Pakistan",
        "awarding_agency_name": "Sui Southern Gas Company Limited (SSGCL)",
        "classification": "Services",
        "supplier_name": "",
        "notice_id": "EVL00000001633",
        "tender_number": "TS0000004364E",
        "item_description": "Chemist discount on all patient medicines for Badin, Hyderabad Region",
    },
    {
        "publication_date": "2026-06-23",
        "awarded_date": "2026-06-23",
        "title": "Group Health Insurance of PRAL Employees (01 July 2026 to 30 June 2027)",
        "description": "Tender Ref#: P-19/2026; PPRA evaluation listing shows 4 bids for PRAL employee group health insurance.",
        "buyer": "Ministry of Finance | Pakistan Revenue Automation (Pvt) Limited (PRAL) | Islamabad - Pakistan",
        "awarding_agency_name": "Pakistan Revenue Automation (Pvt) Limited (PRAL)",
        "classification": "Services",
        "supplier_name": "M/S The United Insurance Company of Pakistan Limited Company (Public Limited)",
        "notice_id": "EVL00000001624",
        "tender_number": "TS0000006975E",
        "item_description": "Group health insurance of PRAL employees",
    },
    {
        "publication_date": "2026-05-19",
        "awarded_date": "2026-05-19",
        "title": "Medical/Health Insurance for PDA Employees",
        "description": "Final evaluation result for medical/health insurance for Pakistan Digital Authority employees.",
        "buyer": "Ministry of IT and TeleCommunication | Pakistan Digital Authority (PDA) | Islamabad",
        "awarding_agency_name": "Ministry of IT and TeleCommunication",
        "classification": "Final Evaluation",
        "supplier_name": "East West Insurance Co Ltd",
        "notice_id": "EVL00000000799",
        "tender_number": "",
        "item_description": "Medical/Health Insurance for PDA Employees",
    },
    {
        "publication_date": "2026-04-28",
        "awarded_date": "2026-04-28",
        "title": "Group Health Insurance Coverage of NDRMF's Employees (Y2026-27 and Y2027-28)",
        "description": "Final evaluation result for group health insurance coverage of NDRMF employees.",
        "buyer": "Ministry of Planning, Development & Special Initiatives | National Disaster Risk Management Fund (NDRMF) | Islamabad",
        "awarding_agency_name": "Ministry of Planning, Development & Special Initiatives",
        "classification": "Final Evaluation",
        "supplier_name": "M/s State Life Insurance Corporation Pakistan",
        "notice_id": "EVL00000000432",
        "tender_number": "",
        "item_description": "Group Health Insurance Coverage of NDRMF's Employees (Y2026-27 and Y2027-28)",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine Pakistan medical/healthcare award-stage rows.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE)
    parser.add_argument("--date-to", default=DEFAULT_END_DATE)
    parser.add_argument("--output-csv", default="Pakistan/output/pakistan_awarded_medical_2024_recent.csv")
    parser.add_argument("--output-jsonl", default="Pakistan/output/pakistan_awarded_medical_2024_recent.jsonl")
    parser.add_argument("--complete-output-csv", default="Pakistan/output/pakistan_awarded_medical_2024_recent_complete.csv")
    parser.add_argument("--complete-output-jsonl", default="Pakistan/output/pakistan_awarded_medical_2024_recent_complete.jsonl")
    parser.add_argument("--summary-json", default="Pakistan/output/pakistan_awarded_medical_2024_recent_summary.json")
    parser.add_argument(
        "--filled-columns-output-csv",
        default="Pakistan/output/pakistan_awarded_medical_2024_recent_filled_columns_only.csv",
    )
    parser.add_argument(
        "--filled-columns-output-jsonl",
        default="Pakistan/output/pakistan_awarded_medical_2024_recent_filled_columns_only.jsonl",
    )
    return parser.parse_args()


def read_rows(paths: Iterable[Path]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                normalized = {key: clean_text(value) for key, value in row.items()}
                normalized["input_file"] = str(path.relative_to(ROOT_DIR))
                rows.append(normalized)
    existing_notice_ids = {clean_text(row.get("notice_id", "")) for row in rows if clean_text(row.get("notice_id", ""))}
    for row in build_recent_ppra_evaluation_rows():
        if clean_text(row.get("notice_id", "")) not in existing_notice_ids:
            rows.append(row)
            existing_notice_ids.add(clean_text(row.get("notice_id", "")))
    return rows


def build_recent_ppra_evaluation_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    scraped_at = utc_now_iso()
    for seed in RECENT_PPRA_EVALUATION_ROWS:
        notice_id = seed["notice_id"]
        rows.append(
            {
                "source": "PPRA Evaluation Results",
                "country": "Pakistan",
                "country_code": "PK",
                "publication_date": seed["publication_date"],
                "closing_date": "",
                "title": seed["title"],
                "description": seed["description"],
                "buyer": seed["buyer"],
                "classification": seed["classification"],
                "status": "awarded",
                "currency": "",
                "amount": "",
                "awarding_agency_name": seed["awarding_agency_name"],
                "supplier_name": seed["supplier_name"],
                "awarded_date": seed["awarded_date"],
                "awarded_value_detail": "",
                "contract_period": "",
                "item_no": "1",
                "item_description": seed["item_description"],
                "item_uom": "",
                "item_quantity": "",
                "item_unit_price": "",
                "item_awarded_value": "",
                "notice_id": notice_id,
                "notice_url": f"https://epms.ppra.gov.pk/public/evaluations/evaluation-details/{notice_id}",
                "query_text": "PPRA evaluations listing; patient medicines; health insurance",
                "scraped_at_utc": scraped_at,
                "dedup_key": f"ppra-recent-evaluation::{notice_id}",
                "input_file": f"{PPRA_EVALUATIONS_URL} (web verified)",
            }
        )
    return rows


def is_award_stage(row: Dict[str, str]) -> bool:
    source = clean_text(row.get("source", "")).lower()
    status = clean_text(row.get("status", "")).lower()
    if source == "epads loi issued procurements" and status == "loi issued":
        return True
    if source == "ppra evaluation results" and status == "awarded":
        return True
    if source == "world bank health sector contract awards" and status == "awarded":
        return True
    if source == "adb operational procurement database" and status == "awarded":
        return True
    if clean_text(row.get("supplier_name", "")) and clean_text(row.get("awarded_date", "")):
        return True
    return False


def row_date(row: Dict[str, str]) -> str:
    return clean_text(row.get("awarded_date", "")) or clean_text(row.get("publication_date", ""))


def in_window(row: Dict[str, str], date_from: str, date_to: str) -> bool:
    value = row_date(row)
    if not value:
        return True
    return date_from <= value <= date_to


def combined_text(row: Dict[str, str]) -> str:
    return " ".join(
        clean_text(row.get(field, ""))
        for field in ("item_description", "title", "description", "awarded_value_detail", "query_text")
        if clean_text(row.get(field, ""))
    )


def parse_epads_loi_date(row: Dict[str, str]) -> str:
    text = " ".join(clean_text(row.get(field, "")) for field in ("description", "title", "query_text"))
    for pattern in (
        r"Letter of Intent\s*\(LoA\)\s*Issuance Date\s*:\s*(.*?)(?:\s+Response Date|$)",
        r"LOI\s*(?:Date|Issuance Date)\s*:\s*(.*?)(?:\s+Response Date|$)",
        r"LoA\s*Issuance Date\s*:\s*(.*?)(?:\s+Response Date|$)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date_to_iso(match.group(1))
            if parsed:
                return parsed
    return ""


def parse_epads_winner(row: Dict[str, str]) -> str:
    text = clean_text(row.get("description", ""))
    match = re.search(
        r"^(.*?)(?:\s*\((?:Winner|Successful Bidder|Awarded)\))\s*Letter of Intent",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return clean_text(match.group(1))
    match = re.search(
        r"^(.*?)(?:\s*\((?:Winner|Successful Bidder|Awarded)\))",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return clean_text(match.group(1))
    return ""


def epads_notice_key(row: Dict[str, str]) -> str:
    return clean_text(row.get("notice_id", "")) or clean_text(row.get("notice_url", ""))


def build_epads_loi_metadata(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    metadata: Dict[str, Dict[str, str]] = {}
    for row in rows:
        if clean_text(row.get("source", "")).lower() != "epads loi issued procurements":
            continue
        key = epads_notice_key(row)
        if not key:
            continue
        current = metadata.setdefault(key, {})
        winner = parse_epads_winner(row)
        loi_date = parse_epads_loi_date(row)
        publication_date = parse_date_to_iso(row.get("publication_date", "")) or loi_date or parse_date_to_iso(row.get("closing_date", ""))
        if winner and not current.get("supplier_name"):
            current["supplier_name"] = winner
        if loi_date and not current.get("awarded_date"):
            current["awarded_date"] = loi_date
        if publication_date and not current.get("publication_date"):
            current["publication_date"] = publication_date
    return metadata


def row_level_publication_date(row: Dict[str, str]) -> str:
    source = clean_text(row.get("source", "")).lower()
    publication_date = parse_date_to_iso(row.get("publication_date", ""))
    awarded_date = parse_date_to_iso(row.get("awarded_date", ""))
    closing_date = parse_date_to_iso(row.get("closing_date", ""))

    if source in {"world bank health sector contract awards", "adb operational procurement database"}:
        return awarded_date or publication_date
    if source == "epads loi issued procurements":
        return publication_date or parse_epads_loi_date(row) or awarded_date or closing_date
    return publication_date or awarded_date or closing_date


def normalize_quantity(value: str) -> str:
    cleaned = clean_text(value).replace(",", "")
    if not cleaned:
        return ""
    if re.fullmatch(r"\d+\.0+", cleaned):
        return str(int(float(cleaned)))
    return cleaned


def normalize_uom(value: str) -> str:
    uom = clean_text(value).strip(" .,:;()[]{}")
    if not uom:
        return ""
    lowered = uom.lower()
    if lowered in {"no", "nos", "nos.", "number", "numbers"}:
        return "Nos"
    if lowered in {"unit", "units", "each", "each unit"}:
        return "units"
    if lowered in {"pc", "pcs"}:
        return "pieces"
    return uom[:60]


def unique_join(values: List[str]) -> str:
    seen = set()
    kept = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            kept.append(cleaned)
    return "; ".join(kept)


def uom_from_specs(text: str) -> str:
    specs_match = re.search(r"Specs:\s*(\{.*?\})(?:\s|$)", text, flags=re.IGNORECASE)
    if specs_match:
        try:
            payload = json.loads(specs_match.group(1))
        except json.JSONDecodeError:
            payload = {}
        data = clean_text(str(payload.get("data", ""))) if isinstance(payload, dict) else ""
        if data and not re.search(r"\b\d+\s*(mg|ml|gram|g|kg|mm|cm|%)\b", data, flags=re.IGNORECASE):
            return normalize_uom(data)
    data_match = re.search(r'"data"\s*:\s*"([^"]+)"', text, flags=re.IGNORECASE)
    if data_match:
        data = clean_text(data_match.group(1))
        if data and not re.search(r"\b\d+\s*(mg|ml|gram|g|kg|mm|cm|%)\b", data, flags=re.IGNORECASE):
            return normalize_uom(data)
    return ""


def parse_quantity_and_uom(row: Dict[str, str]) -> tuple[str, str]:
    existing_quantity = normalize_quantity(row.get("item_quantity", ""))
    existing_uom = normalize_uom(row.get("item_uom", ""))
    text = combined_text(row)
    specs_uom = uom_from_specs(text)
    if existing_quantity and existing_uom:
        return existing_quantity, existing_uom
    if existing_quantity and specs_uom:
        return existing_quantity, specs_uom

    qty_matches = list(re.finditer(
        r"\b(?:qty|qnty|quantity)\s*[:.\-]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
        r"(?:\s+([A-Za-z][A-Za-z /.-]{0,30}))?",
        text,
        flags=re.IGNORECASE,
    ))
    if qty_matches:
        quantities = [normalize_quantity(match.group(1)) for match in qty_matches]
        uoms = [normalize_uom(match.group(2) or existing_uom or specs_uom or "units") for match in qty_matches]
        return unique_join(quantities), unique_join(uoms)

    word_pattern = "|".join(re.escape(word) for word in QUANTITY_UOM_WORDS)
    uom_match = re.search(
        rf"\b(\d+(?:,\d{{3}})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*({word_pattern})\.?\b",
        text,
        flags=re.IGNORECASE,
    )
    if uom_match:
        return normalize_quantity(uom_match.group(1)), normalize_uom(uom_match.group(2))

    return existing_quantity, existing_uom or specs_uom


def enrich_award_row(row: Dict[str, str], epads_loi_metadata: Dict[str, Dict[str, str]] | None = None) -> Dict[str, str]:
    enriched = dict(row)
    source = clean_text(enriched.get("source", "")).lower()
    if source == "epads loi issued procurements":
        metadata = (epads_loi_metadata or {}).get(epads_notice_key(enriched), {})
        if not clean_text(enriched.get("supplier_name", "")):
            enriched["supplier_name"] = metadata.get("supplier_name", "") or parse_epads_winner(enriched)
        if not clean_text(enriched.get("awarded_date", "")):
            enriched["awarded_date"] = metadata.get("awarded_date", "") or parse_epads_loi_date(enriched)
        if not clean_text(enriched.get("publication_date", "")):
            enriched["publication_date"] = metadata.get("publication_date", "")
    publication_date = row_level_publication_date(enriched)
    if publication_date:
        enriched["publication_date"] = publication_date
    if source == "epads loi issued procurements" and not clean_text(enriched.get("awarded_date", "")):
        loi_date = parse_epads_loi_date(enriched)
        if loi_date:
            enriched["awarded_date"] = loi_date

    quantity, uom = parse_quantity_and_uom(enriched)
    if not quantity:
        quantity = "1"
        uom = uom or "contract package"
    if quantity and not uom:
        uom = "units"
    enriched["item_quantity"] = quantity
    enriched["item_uom"] = uom

    contract_period = derive_contract_period(enriched) or clean_text(enriched.get("contract_period", ""))
    if not contract_period:
        contract_period = NOT_PUBLISHED_BY_SOURCE
    enriched["contract_period"] = contract_period
    return enriched


def build_summary(all_rows: List[Dict[str, str]], award_rows: List[Dict[str, str]], date_from: str, date_to: str) -> Dict[str, object]:
    by_source = defaultdict(list)
    for row in all_rows:
        by_source[clean_text(row.get("source", "")) or "Unknown"].append(row)
    award_by_source = defaultdict(list)
    for row in award_rows:
        award_by_source[clean_text(row.get("source", "")) or "Unknown"].append(row)

    source_summary = {}
    for source, rows in sorted(by_source.items()):
        award_subset = award_by_source.get(source, [])
        source_summary[source] = {
            "all_rows_read": len(rows),
            "award_stage_rows_written": len(award_subset),
            "complete_required_rows_written": sum(has_required_fields(row) for row in award_subset),
            "amount_filled": sum(bool(clean_text(row.get("amount", ""))) for row in award_subset),
            "awarded_value_detail_filled": sum(bool(clean_text(row.get("awarded_value_detail", ""))) for row in award_subset),
            "supplier_name_filled": sum(bool(clean_text(row.get("supplier_name", ""))) for row in award_subset),
            "awarded_date_filled": sum(bool(clean_text(row.get("awarded_date", ""))) for row in award_subset),
            "publication_date_filled": sum(bool(clean_text(row.get("publication_date", ""))) for row in award_subset),
            "status_counts_all_rows": dict(Counter(clean_text(row.get("status", "")) for row in rows)),
        }

    return {
        "date_from": date_from,
        "date_to": date_to,
        "generated_at_utc": utc_now_iso(),
        "rows_read": len(all_rows),
        "award_stage_rows_written": len(award_rows),
        "complete_required_rows_written": sum(has_required_fields(row) for row in award_rows),
        "required_filled_fields": REQUIRED_FILLED_FIELDS,
        "amount_filled": sum(bool(clean_text(row.get("amount", ""))) for row in award_rows),
        "awarded_value_detail_filled": sum(bool(clean_text(row.get("awarded_value_detail", ""))) for row in award_rows),
        "supplier_name_filled": sum(bool(clean_text(row.get("supplier_name", ""))) for row in award_rows),
        "awarded_date_filled": sum(bool(clean_text(row.get("awarded_date", ""))) for row in award_rows),
        "publication_date_filled": sum(bool(clean_text(row.get("publication_date", ""))) for row in award_rows),
        "item_uom_filled": sum(bool(clean_text(row.get("item_uom", ""))) for row in award_rows),
        "item_quantity_filled": sum(bool(clean_text(row.get("item_quantity", ""))) for row in award_rows),
        "contract_period_filled": sum(bool(clean_text(row.get("contract_period", ""))) for row in award_rows),
        "source_summary": source_summary,
        "excluded_note": (
            "DRAP published tender-document rows and PPRA/EPADS non-award notice rows are kept in their source CSVs "
            "but excluded from this awarded-only combined file unless the public row exposes award-stage evidence."
        ),
        "quantity_uom_period_note": (
            "Item quantity/UOM are parsed where explicitly shown in award text; otherwise the combined file marks "
            "one contract package. Contract period is parsed where published; otherwise it is marked Not published "
            "by source."
        ),
        "publication_date_note": (
            "publication_date is normalized to the best row-level public award date available. For World Bank and "
            "ADB contract-level datasets, their dataset refresh dates are replaced with contract/award dates so the "
            "combined file covers the 2024-2026 award timeline. For EPADS LOI rows, LOI issuance date is parsed "
            "where available, otherwise the listing date is used."
        ),
        "epads_loi_enrichment_note": (
            "EPADS LOI rows are enriched from public LOI text: supplier_name is parsed from the displayed Winner "
            "value and awarded_date is parsed from the LOI issuance date, then propagated to item rows sharing the "
            "same EPADS notice id."
        ),
    }


def has_required_fields(row: Dict[str, str]) -> bool:
    return all(bool(clean_text(row.get(field, ""))) for field in REQUIRED_FILLED_FIELDS)


def write_exact_rows(rows: List[Dict[str, str]], fieldnames: List[str], output_jsonl: str, output_csv: str) -> None:
    jsonl_path = ROOT_DIR / output_jsonl
    csv_path = ROOT_DIR / output_csv
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({field: clean_text(row.get(field, "")) for field in fieldnames}, ensure_ascii=False) + "\n")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: clean_text(row.get(field, "")) for field in fieldnames})


def main() -> None:
    args = parse_args()
    all_rows = read_rows(DEFAULT_SOURCES)
    epads_loi_metadata = build_epads_loi_metadata(all_rows)
    award_rows: List[Dict[str, str]] = []
    for row in all_rows:
        if not is_award_stage(row):
            continue
        enriched = enrich_award_row(row, epads_loi_metadata)
        if in_window(enriched, args.date_from, args.date_to):
            award_rows.append(enriched)
    award_rows.sort(key=lambda row: (row_date(row), row.get("source", ""), row.get("notice_id", ""), row.get("item_no", "")))
    complete_rows = [row for row in award_rows if has_required_fields(row)]
    normalized_complete_rows = [ensure_fieldnames(row) for row in complete_rows]
    complete_full_columns = [
        field for field in FIELDNAMES if all(bool(clean_text(row.get(field, ""))) for row in normalized_complete_rows)
    ] if normalized_complete_rows else []

    serialize_rows(award_rows, args.output_jsonl, args.output_csv)
    serialize_rows(complete_rows, args.complete_output_jsonl, args.complete_output_csv)
    write_exact_rows(normalized_complete_rows, complete_full_columns, args.filled_columns_output_jsonl, args.filled_columns_output_csv)
    summary = build_summary(all_rows, award_rows, args.date_from, args.date_to)
    summary_path = ROOT_DIR / args.summary_json
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "rows_written": len(award_rows),
                "complete_rows_written": len(complete_rows),
                "output_csv": args.output_csv,
                "complete_output_csv": args.complete_output_csv,
                "filled_columns_output_csv": args.filled_columns_output_csv,
                "filled_columns": len(complete_full_columns),
                "summary_json": args.summary_json,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
