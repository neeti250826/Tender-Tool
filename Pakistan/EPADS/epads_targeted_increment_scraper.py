#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from procurement_utils import (
    OptionalTranslator,
    add_translation_columns,
    clean_text,
    matched_keywords,
    normalize_keyword_list,
    serialize_rows,
    split_amount_and_currency,
    stable_key,
    utc_now_iso,
)
from Pakistan.EPADS.epads_item_scraper import (
    LIST_URL,
    build_session,
    keep_epads_medical_row,
    listing_page_url,
    parse_detail_page,
    parse_listing_rows,
    wait_for_detail,
    wait_for_listing,
)
from playwright.sync_api import sync_playwright

DEFAULT_KEYWORDS = ",".join(
    [
        "medical device",
        "medical devices",
        "medical equipment",
        "medical consumable",
        "medical consumables",
        "healthcare device",
        "healthcare devices",
        "healthcare equipment",
        "healthcare consumable",
        "healthcare consumables",
        "hospital equipment",
        "hospital consumable",
        "hospital consumables",
        "surgical equipment",
        "surgical instruments",
        "surgical disposable",
        "surgical disposables",
        "diagnostic equipment",
        "diagnostic consumables",
        "lab equipment",
        "laboratory equipment",
        "lab consumables",
        "laboratory consumables",
        "biomedical equipment",
        "biomedical devices",
        "medical supplies",
        "medical items",
        "medical store items",
        "consumable",
        "consumables",
        "equipment",
        "devices",
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch a bounded EPADS LOI increment for targeted medical categories.")
    parser.add_argument("--page-from", type=int, default=26)
    parser.add_argument("--page-to", type=int, default=80)
    parser.add_argument("--max-details", type=int, default=150)
    parser.add_argument("--keywords", default=DEFAULT_KEYWORDS)
    parser.add_argument("--existing-csv", default="Pakistan/EPADS/output/epads_item_medical_2024_2026.csv")
    parser.add_argument("--output-csv", default="Pakistan/EPADS/output/epads_targeted_increment.csv")
    parser.add_argument("--output-jsonl", default="Pakistan/EPADS/output/epads_targeted_increment.jsonl")
    parser.add_argument("--browser", action="store_true", help="Use headless Chromium instead of requests.")
    return parser.parse_args()


def load_existing_notice_ids(path: Path) -> set[str]:
    notice_ids: set[str] = set()
    if not path.exists():
        return notice_ids
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            notice_id = clean_text(row.get("notice_id", ""))
            if notice_id:
                notice_ids.add(notice_id)
    return notice_ids


def build_rows_for_listing(
    listing_row: Dict[str, str],
    detail: Dict[str, object],
    keywords: Sequence[str],
    scraped_at: str,
    translator: OptionalTranslator,
) -> List[Dict[str, str]]:
    resolved_amount, resolved_currency = split_amount_and_currency(
        clean_text(str(detail.get("awarded_value_detail", ""))) or listing_row["amount_text"],
        default_currency="PKR" if listing_row["amount"] or clean_text(str(detail.get("awarded_value_detail", ""))) else "",
    )
    if not resolved_amount:
        resolved_amount = listing_row["amount"]
    if not clean_text(resolved_amount) and not clean_text(str(detail.get("awarded_value_detail", ""))):
        resolved_currency = ""

    item_rows = detail["items"] if isinstance(detail.get("items"), list) else []
    if not item_rows:
        item_rows = [{"item_description": listing_row["title"], "item_quantity": "", "item_uom": "", "contract_period": ""}]

    output_rows: List[Dict[str, str]] = []
    query_text = clean_text(listing_row.get("query_matches", ""))
    for index, item in enumerate(item_rows, start=1):
        if not isinstance(item, dict):
            continue
        notice_id = listing_row["notice_id"] or str(detail.get("notice_id", ""))
        title = listing_row["title"] or clean_text(str(detail.get("description", "")))
        description = clean_text(str(detail.get("description", ""))) or title
        item_description = clean_text(item.get("item_description", ""))
        detail_matches = matched_keywords(" | ".join([title, description, item_description]), keywords)
        if not keep_epads_medical_row(detail_matches, title, "", description, item_description):
            continue
        row = {
            "source": listing_row.get("source_label", "EPADS LOI Issued Procurements"),
            "country": "Pakistan",
            "country_code": "PK",
            "publication_date": clean_text(str(detail.get("publication_date", ""))) or listing_row["closing_date"],
            "closing_date": clean_text(str(detail.get("closing_date", ""))) or listing_row["closing_date"],
            "title": title,
            "description": description,
            "buyer": listing_row["buyer"],
            "classification": listing_row["classification"],
            "status": clean_text(str(detail.get("status", ""))) or listing_row["status"] or "loi issued",
            "currency": resolved_currency,
            "amount": resolved_amount,
            "awarding_agency_name": listing_row["buyer"],
            "supplier_name": clean_text(str(detail.get("supplier_name", ""))),
            "awarded_date": clean_text(str(detail.get("awarded_date", ""))),
            "awarded_value_detail": clean_text(str(detail.get("awarded_value_detail", ""))) or listing_row["amount_text"],
            "contract_period": clean_text(item.get("contract_period", "")),
            "item_no": str(index),
            "item_description": item_description,
            "item_uom": clean_text(item.get("item_uom", "")),
            "item_quantity": clean_text(item.get("item_quantity", "")),
            "item_unit_price": "",
            "item_awarded_value": "",
            "notice_id": notice_id,
            "notice_url": listing_row["notice_url"],
            "query_text": query_text,
            "scraped_at_utc": scraped_at,
            "dedup_key": stable_key(notice_id, listing_row["notice_url"], str(index), item_description),
        }
        output_rows.append(add_translation_columns(row, translator))
    return output_rows


def main() -> None:
    args = parse_args()
    keywords = normalize_keyword_list(args.keywords)
    existing_notice_ids = load_existing_notice_ids(Path(args.existing_csv))
    scraped_at = utc_now_iso()
    translator = OptionalTranslator(enabled=False)
    session = build_session()
    candidates: List[Dict[str, str]] = []
    seen_notice_ids = set(existing_notice_ids)

    rows: List[Dict[str, str]] = []

    def collect_from_listing_html(html: str) -> bool:
        listing_rows = parse_listing_rows(html)
        if not listing_rows:
            return False
        for listing_row in listing_rows:
            notice_id = clean_text(listing_row.get("notice_id", ""))
            if not notice_id or notice_id in seen_notice_ids:
                continue
            matches = matched_keywords(
                " | ".join([listing_row["title"], listing_row["buyer"], listing_row["listing_text"]]),
                keywords,
            )
            if not keep_epads_medical_row(matches, listing_row["title"], listing_row["buyer"], listing_row["listing_text"]):
                continue
            listing_row["query_matches"] = ", ".join(matches)
            candidates.append(listing_row)
            seen_notice_ids.add(notice_id)
            if len(candidates) >= args.max_details:
                break
        return True

    if args.browser:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            for page_number in range(args.page_from, args.page_to + 1):
                page.goto(listing_page_url(LIST_URL, page_number), wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(1500)
                wait_for_listing(page)
                if not collect_from_listing_html(page.content()):
                    break
                if len(candidates) >= args.max_details:
                    break
            for listing_row in candidates:
                page.goto(listing_row["notice_url"], wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(1200)
                wait_for_detail(page)
                detail = parse_detail_page(page.content(), listing_row["notice_url"])
                rows.extend(build_rows_for_listing(listing_row, detail, keywords, scraped_at, translator))
            browser.close()
    else:
        for page_number in range(args.page_from, args.page_to + 1):
            response = session.get(listing_page_url(LIST_URL, page_number), timeout=45)
            response.raise_for_status()
            if not collect_from_listing_html(response.text):
                break
            if len(candidates) >= args.max_details:
                break

        for listing_row in candidates:
            response = session.get(listing_row["notice_url"], timeout=45)
            response.raise_for_status()
            detail = parse_detail_page(response.text, listing_row["notice_url"])
            rows.extend(build_rows_for_listing(listing_row, detail, keywords, scraped_at, translator))

    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(
        json.dumps(
            {
                "pages_scanned": [args.page_from, args.page_to],
                "candidate_notices": len(candidates),
                "rows_written": len(rows),
                "output_csv": args.output_csv,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
