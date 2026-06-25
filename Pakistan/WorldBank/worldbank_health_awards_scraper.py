#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from procurement_utils import clean_text, serialize_rows, stable_key, utc_now_iso  # noqa: E402

DATASET_ID = "DS01045"
DATASET_URL = "https://financesone.worldbank.org/goods-procurement-contract-awards-in-health-sector/DS01045"
API_URL = "https://datacatalogapi.worldbank.org/dexapps/fone/api/view"
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_END_DATE = date.today().isoformat()

STRICT_MEDICAL_PATTERNS = re.compile(
    r"\b("
    r"medical|health|hospital|clinic|rhc|bhcu?|epi|vaccine|vaccination|immuni[sz]ation|"
    r"ambulance|incubator|infant warmer|phototherapy|pulse oximeter|oximeter|delivery table|"
    r"medicine|medicines|drug|pharma|pharmaceutical|contraceptive|nutrition supplement|"
    r"lab|laboratory|diagnostic|reagent|test kit|equipment|ultrasound|x-?ray|radiology|"
    r"surgical|operation theatre|ot\b|dental|ophthalm|dialysis|blood|oxygen|"
    r"breast feeding|breastfeeding|medical device|biomedical"
    r")\b",
    flags=re.IGNORECASE,
)

EXCLUSION_PATTERNS = re.compile(
    r"\b("
    r"printing|stationary|stationery|activity book|lesson plan|training manual|manuals|"
    r"tablet|thermal printer|power bank|vehicle|motorcycle|office equipment|office furniture|"
    r"photocopier|it equipment|android developer|database administrator|consultant|"
    r"procurement management specialist|social mobilization|safeguard specialist|mis room"
    r")\b",
    flags=re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Pakistan medical/healthcare awards from World Bank health-sector goods awards.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE)
    parser.add_argument("--date-to", default=DEFAULT_END_DATE)
    parser.add_argument("--output-jsonl", default="Pakistan/WorldBank/output/worldbank_pakistan_health_awards_2024_recent.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/WorldBank/output/worldbank_pakistan_health_awards_2024_recent.csv")
    parser.add_argument("--top", type=int, default=1000)
    return parser.parse_args()


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    retry = Retry(
        total=4,
        read=4,
        connect=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_all_rows(top: int) -> List[Dict[str, object]]:
    session = build_session()
    rows: List[Dict[str, object]] = []
    skip = 0
    while True:
        response = session.get(
            API_URL,
            params={"viewId": DATASET_ID, "type": "json", "top": top, "skip": skip},
            timeout=90,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            break
        rows.extend(data)
        if len(data) < top:
            break
        skip += top
    return rows


def iso_date(value: object) -> str:
    text = clean_text(str(value or ""))
    if not text:
        return ""
    return text.split("T", 1)[0]


def keep_medical_award(raw: Dict[str, object], date_from: str, date_to: str) -> bool:
    if clean_text(str(raw.get("borrower_country", ""))).lower() != "pakistan":
        return False
    signing_date = iso_date(raw.get("contract_signing_date"))
    if not signing_date or signing_date < date_from or signing_date > date_to:
        return False
    description = clean_text(str(raw.get("contract_description", "")))
    project_name = clean_text(str(raw.get("project_name", "")))
    practice = clean_text(str(raw.get("project_global_practice", "")))
    text = " | ".join([description, project_name, practice])
    if not STRICT_MEDICAL_PATTERNS.search(text):
        return False
    if EXCLUSION_PATTERNS.search(description) and not re.search(
        r"\b(medical equipment|medical device|hospital equipment|ambulance|contraceptive|nutrition supplement|medicine|incubator|oximeter|delivery table|epi)\b",
        description,
        flags=re.IGNORECASE,
    ):
        return False
    return all(
        clean_text(str(raw.get(field, "")))
        for field in ("contract_description", "contract_signing_date", "supplier", "supplier_contract_amount_usd", "as_of_date")
    )


def normalize_row(raw: Dict[str, object], scraped_at: str) -> Dict[str, str]:
    notice_id = clean_text(str(raw.get("wb_contract_number", "")))
    description = clean_text(str(raw.get("contract_description", "")))
    project_name = clean_text(str(raw.get("project_name", "")))
    signing_date = iso_date(raw.get("contract_signing_date"))
    publication_date = iso_date(raw.get("as_of_date"))
    amount = clean_text(str(raw.get("supplier_contract_amount_usd", "")))
    reference = clean_text(str(raw.get("borrower_contract_reference_number", "")))
    return {
        "source": "World Bank Health Sector Contract Awards",
        "country": "Pakistan",
        "country_code": "PK",
        "publication_date": publication_date,
        "closing_date": "",
        "title": description,
        "title_english": "",
        "description": f"{project_name}: {description}" if project_name else description,
        "description_english": "",
        "buyer": clean_text(str(raw.get("borrower_country", ""))),
        "buyer_english": "",
        "classification": " | ".join(
            part
            for part in [
                clean_text(str(raw.get("procurement_category", ""))),
                clean_text(str(raw.get("procurement_method", ""))),
                clean_text(str(raw.get("project_global_practice", ""))),
            ]
            if part
        ),
        "classification_english": "",
        "status": "awarded",
        "status_english": "",
        "currency": "USD",
        "amount": amount,
        "awarding_agency_name": project_name,
        "awarding_agency_name_english": "",
        "supplier_name": clean_text(str(raw.get("supplier", ""))),
        "supplier_name_english": "",
        "awarded_date": signing_date,
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
        "notice_url": DATASET_URL,
        "query_text": "World Bank health-sector goods awards; Pakistan; medical/healthcare strict keyword filter",
        "query_text_english": "",
        "scraped_at_utc": scraped_at,
        "dedup_key": stable_key("worldbank", notice_id, reference, description, signing_date),
        "source_publication_note": "publication_date is the World Bank Finances One as_of_date for the published dataset snapshot.",
        "borrower_contract_reference_number": reference,
        "project_id": clean_text(str(raw.get("project_id", ""))),
        "supplier_country": clean_text(str(raw.get("supplier_country", ""))),
    }


def main() -> None:
    args = parse_args()
    raw_rows = fetch_all_rows(args.top)
    scraped_at = utc_now_iso()
    rows = [
        normalize_row(raw, scraped_at)
        for raw in raw_rows
        if keep_medical_award(raw, args.date_from, args.date_to)
    ]
    rows.sort(key=lambda row: (row["awarded_date"], row["notice_id"], row["item_description"]))
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(
        json.dumps(
            {
                "raw_rows_read": len(raw_rows),
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
