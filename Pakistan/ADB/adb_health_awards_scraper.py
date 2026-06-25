#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from procurement_utils import clean_text, serialize_rows, stable_key, utc_now_iso  # noqa: E402

SOURCE_URL = "https://data.adb.org/dataset/operational-procurement-database"
DEFAULT_INPUT = "Pakistan/ADB/adb_procurement_by_nationality_2016_2026.xlsx"
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_END_DATE = date.today().isoformat()
ADB_PUBLICATION_DATE = "2026-05-08"

HIGH_CONFIDENCE_HEALTH_PATTERNS = re.compile(
    r"("
    r"emergency rescue services|fighting the covid-19 pandemic|covid-19|"
    r"regional blood center|regional blood centre|contracting out regional blood"
    r")",
    flags=re.IGNORECASE,
)
GENERIC_SUPPLIER_PATTERN = re.compile(r"^\s*(various|individual consultant|trta|ksta|nan)\s*$", flags=re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract high-confidence Pakistan health awards from the ADB procurement workbook.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--date-from", default=DEFAULT_START_DATE)
    parser.add_argument("--date-to", default=DEFAULT_END_DATE)
    parser.add_argument("--output-jsonl", default="Pakistan/ADB/output/adb_pakistan_health_awards_2024_recent.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/ADB/output/adb_pakistan_health_awards_2024_recent.csv")
    return parser.parse_args()


def iso_date(value: object) -> str:
    if pd.isna(value):
        return ""
    try:
        return pd.to_datetime(value).date().isoformat()
    except Exception:
        return clean_text(str(value)).split(" ", 1)[0]


def keep_row(row: Dict[str, object], date_from: str, date_to: str) -> bool:
    if clean_text(str(row.get("BORROWING COUNTRY", ""))).lower() != "pakistan":
        return False
    contract_date = iso_date(row.get("CONTRACT DATE"))
    if not contract_date or contract_date < date_from or contract_date > date_to:
        return False
    supplier = clean_text(str(row.get("CONTRACTOR NAME", "")))
    amount = clean_text(str(row.get("ADB-FINANCED AMOUNT", "")))
    description = clean_text(str(row.get("CONTRACT DESCRIPTION", "")))
    if GENERIC_SUPPLIER_PATTERN.match(description):
        return False
    if not supplier or not amount or not description:
        return False
    if GENERIC_SUPPLIER_PATTERN.match(supplier):
        return False
    text = " | ".join(
        clean_text(str(row.get(field, "")))
        for field in ("SECTOR", "SUBSECTOR", "PROJECT TITLE", "CONTRACT DESCRIPTION", "EXECUTING AGENCY")
    )
    return bool(HIGH_CONFIDENCE_HEALTH_PATTERNS.search(text))


def normalize_amount(value: object) -> str:
    if pd.isna(value):
        return ""
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except Exception:
        return clean_text(str(value))


def normalize_row(row: Dict[str, object], scraped_at: str) -> Dict[str, str]:
    contract_year = clean_text(str(row.get("CONTRACT YEAR", ""))).replace(".0", "")
    approval_number = clean_text(str(row.get("APPROVAL NUMBER", ""))).replace(".0", "")
    contract_date = iso_date(row.get("CONTRACT DATE"))
    amount = normalize_amount(row.get("ADB-FINANCED AMOUNT"))
    description = clean_text(str(row.get("CONTRACT DESCRIPTION", "")))
    project_title = clean_text(str(row.get("PROJECT TITLE", "")))
    executing_agency = clean_text(str(row.get("EXECUTING AGENCY", "")))
    notice_id = stable_key("adb", approval_number, contract_year, contract_date, description)[:24]
    return {
        "source": "ADB Operational Procurement Database",
        "country": "Pakistan",
        "country_code": "PK",
        "publication_date": ADB_PUBLICATION_DATE,
        "closing_date": "",
        "title": description,
        "title_english": "",
        "description": f"{project_title}: {description}" if project_title else description,
        "description_english": "",
        "buyer": executing_agency or "Pakistan",
        "buyer_english": "",
        "classification": " | ".join(
            part
            for part in [
                clean_text(str(row.get("NATURE OF PROCUREMENT", ""))),
                clean_text(str(row.get("SECTOR", ""))),
                clean_text(str(row.get("SUBSECTOR", ""))),
            ]
            if part and part.lower() != "nan"
        ),
        "classification_english": "",
        "status": "awarded",
        "status_english": "",
        "currency": "USD",
        "amount": amount,
        "awarding_agency_name": executing_agency or project_title,
        "awarding_agency_name_english": "",
        "supplier_name": clean_text(str(row.get("CONTRACTOR NAME", ""))),
        "supplier_name_english": "",
        "awarded_date": contract_date,
        "awarded_value_detail": f"{amount} USD",
        "contract_period": "",
        "contract_period_english": "",
        "item_no": "1",
        "item_description": description,
        "item_description_english": "",
        "item_uom": "",
        "item_quantity": "",
        "item_unit_price": "",
        "item_awarded_value": amount,
        "notice_id": notice_id,
        "notice_url": SOURCE_URL,
        "query_text": "ADB operational procurement database; Pakistan; high-confidence health contract pattern",
        "query_text_english": "",
        "scraped_at_utc": scraped_at,
        "dedup_key": stable_key("adb", approval_number, contract_year, contract_date, description, row.get("CONTRACTOR NAME", "")),
        "source_publication_note": "publication_date is the ADB Data Library last-updated date for the Operational Procurement Database.",
        "project_title": project_title,
        "approval_number": approval_number,
        "contract_year": contract_year,
    }


def main() -> None:
    args = parse_args()
    df = pd.read_excel(args.input, header=1)
    scraped_at = utc_now_iso()
    rows: List[Dict[str, str]] = []
    for raw in df.to_dict(orient="records"):
        if keep_row(raw, args.date_from, args.date_to):
            rows.append(normalize_row(raw, scraped_at))
    rows.sort(key=lambda row: (row["awarded_date"], row["notice_id"], row["supplier_name"]))
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(
        json.dumps(
            {
                "input": args.input,
                "rows_read": len(df),
                "rows_written": len(rows),
                "output_jsonl": args.output_jsonl,
                "output_csv": args.output_csv,
                "date_from": args.date_from,
                "date_to": args.date_to,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
