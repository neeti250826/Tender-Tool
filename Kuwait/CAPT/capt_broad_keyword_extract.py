#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from openpyxl import Workbook

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from build_country_schema_exports import REQUESTED_COLUMNS, style_sheet  # noqa: E402
from Kuwait.CAPT.capt_awarded_scraper import normalize_capt_item_no, parse_award_rows  # noqa: E402
from procurement_utils import split_amount_and_currency, utc_now_iso  # noqa: E402

CAPTURE_FILES = [
    "capt_winning_bids_browser_response.html",
    "capt_winning_bids_browser_response_page2.html",
    "capt_winning_bids_browser_response_page3.html",
]
OUTPUT_DIR = ROOT_DIR / "normalized_country_exports"
CAPT_OUTPUT_DIR = ROOT_DIR / "Kuwait" / "CAPT" / "output"
CSV_OUTPUT = OUTPUT_DIR / "kuwait_capt_broad_keyword_awards_normalized.csv"
XLSX_OUTPUT = OUTPUT_DIR / "kuwait_capt_broad_keyword_awards_normalized.xlsx"
JSONL_OUTPUT = CAPT_OUTPUT_DIR / "capt_broad_keyword_awards.jsonl"

BROAD_TERMS = {
    "ministry of health": "health buyer",
    "health insurance": "health insurance",
    "health": "health keyword",
    "treatment": "treatment",
    "vaccine": "vaccine",
    "vaccines": "vaccines",
    "medicine": "medicine",
    "medicines": "medicines",
    "drug": "drug",
    "drugs": "drugs",
    "hospital": "hospital",
    "medical": "medical",
    "التأمين الصحي": "health insurance ar",
    "الصحي": "health ar",
    "صحي": "health ar",
    "علاج": "treatment ar",
    "لقاحات": "vaccines ar",
    "لقاح": "vaccine ar",
    "ادوية": "medicines ar",
    "أدوية": "medicines ar",
    "ادويه": "medicines ar",
    "أدويه": "medicines ar",
    "دواء": "medicine ar",
    "بيطرية": "veterinary ar",
    "طبية": "medical ar",
    "طبي": "medical ar",
    "مستشفى": "hospital ar",
    "مستشفيات": "hospitals ar",
    "عيادة": "clinic ar",
    "عيادات": "clinics ar",
}


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def iso_date(value: str) -> str:
    value = plain(value)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def broad_matches(row: Dict[str, str]) -> List[str]:
    haystack = plain(" | ".join([row.get("subject", ""), row.get("organisation", ""), row.get("notes", "")]))
    haystack_folded = haystack.casefold()
    return sorted({label for term, label in BROAD_TERMS.items() if term.casefold() in haystack_folded})


def dedup_key(row: Dict[str, str]) -> str:
    raw = "|".join(
        [
            plain(row.get("meeting_date", "")),
            plain(row.get("tender_no", "")),
            plain(row.get("subject", "")),
            plain(row.get("winner", "")),
        ]
    )
    return "capt-broad-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_rows() -> List[Dict[str, str]]:
    scraped_at = utc_now_iso()
    output_rows: List[Dict[str, str]] = []
    seen = set()
    for name in CAPTURE_FILES:
        path = CAPT_OUTPUT_DIR / name
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        for row in parse_award_rows(html, str(path)):
            matches = broad_matches(row)
            if not matches:
                continue
            key = dedup_key(row)
            if key in seen:
                continue
            seen.add(key)
            amount, currency = split_amount_and_currency(plain(row.get("total", "")), default_currency="KWD")
            awarded_date = iso_date(row.get("meeting_date", ""))
            subject = plain(row.get("subject", ""))
            organisation = plain(row.get("organisation", ""))
            output_rows.append(
                {
                    "source": "CAPT Winning Bids - broad keywords",
                    "country": "Kuwait",
                    "country_code": "KW",
                    "publication_date": awarded_date,
                    "closing_date": "",
                    "title": subject,
                    "description": plain(row.get("notes", "")) or subject,
                    "buyer": organisation,
                    "classification": "winning bid",
                    "status": "awarded",
                    "currency": currency,
                    "amount": amount,
                    "awarding_agency_name": organisation,
                    "supplier_name": plain(row.get("winner", "")),
                    "awarded_date": awarded_date,
                    "awarded_value_detail": plain(row.get("total", "")),
                    "contract_period": "",
                    "item_no": normalize_capt_item_no(
                        plain(row.get("item_no", "")),
                        plain(row.get("tender_no", "")),
                        plain(row.get("notice_url", "")),
                    ),
                    "item_description": subject,
                    "item_uom": "",
                    "item_quantity": "",
                    "notice_id": plain(row.get("tender_no", "")),
                    "notice_url": plain(row.get("notice_url", "")),
                    "query_text": ", ".join(matches),
                    "query_text_english": ", ".join(matches),
                    "scraped_at_utc": scraped_at,
                    "dedup_key": key,
                    "target_category_matches": ", ".join(matches),
                }
            )
    return output_rows


def write_outputs(rows: List[Dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CAPT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUESTED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Kuwait_CAPT_broad"
    worksheet.append(REQUESTED_COLUMNS)
    for row in rows:
        worksheet.append([row.get(column, "") for column in REQUESTED_COLUMNS])
    style_sheet(worksheet)
    workbook.save(XLSX_OUTPUT)
    with JSONL_OUTPUT.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    rows = load_rows()
    write_outputs(rows)
    print(json.dumps({"rows_written": len(rows), "csv": str(CSV_OUTPUT), "xlsx": str(XLSX_OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
