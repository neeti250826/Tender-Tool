#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: playwright") from exc

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from procurement_utils import (  # noqa: E402
    OptionalTranslator,
    add_translation_columns,
    clean_text,
    in_date_window,
    parse_date_to_iso,
    serialize_rows,
    split_amount_and_currency,
    stable_key,
    utc_now_iso,
)

BASE_URL = "https://capt.gov.kw/en/tenders/winning-bids/"
DEFAULT_START_DATE = "2024-01-01"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape CAPT awarded tenders from the public winning-bids listing.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Award lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Award upper bound in YYYY-MM-DD format.")
    parser.add_argument("--max-pages", type=int, default=250, help="Safety cap for pagination.")
    parser.add_argument("--headless", action="store_true", help="Run Chromium in headless mode.")
    parser.add_argument("--translate", action="store_true", help="Attempt English translation columns when needed.")
    parser.add_argument("--output-jsonl", default="Kuwait/CAPT/output/capt_awarded_2024_to_recent.jsonl")
    parser.add_argument("--output-csv", default="Kuwait/CAPT/output/capt_awarded_2024_to_recent.csv")
    return parser.parse_args()


def build_page_url(page_number: int, date_from: str, date_to: str) -> str:
    params = {
        "meeting_date_from": date_from,
        "meeting_date_to": date_to,
        "form": "date",
        "page": str(page_number),
    }
    return f"{BASE_URL}?{urlencode(params)}"


def wait_for_awards_table(page) -> None:
    selectors = [
        "table",
        "tbody tr",
        "text=Winning Bids",
        "text=Tender No.",
        "text=Meeting Date",
    ]
    last_error: Optional[Exception] = None
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=20000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
    if last_error:
        raise last_error


def detect_awards_table(soup: BeautifulSoup):
    expected_tokens = {
        "sr no",
        "meeting date",
        "tender no.",
        "tender no",
        "tender subject",
        "organisation",
        "organization",
        "winner",
        "total",
        "notes",
    }
    best_table = None
    best_score = -1
    for table in soup.find_all("table"):
        headers = [clean_text(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
        score = sum(1 for header in headers if header in expected_tokens)
        if score > best_score:
            best_table = table
            best_score = score
    return best_table


def discover_last_page_number(html: str) -> int:
    page_numbers = {1}
    for match in re.finditer(r"[?&]page=(\d+)", html):
        page_numbers.add(int(match.group(1)))
    return max(page_numbers)


def parse_award_rows(html: str, page_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = detect_awards_table(soup)
    if table is None:
        return []

    headers = [clean_text(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
    header_map = {name: idx for idx, name in enumerate(headers)}

    def cell_value(cells: List[str], *keys: str) -> str:
        for key in keys:
            index = header_map.get(key)
            if index is not None and index < len(cells):
                return cells[index]
        return ""

    rows: List[Dict[str, str]] = []
    for tr in table.find_all("tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(cells) < 5:
            continue
        meeting_date = cell_value(cells, "meeting date")
        tender_no = cell_value(cells, "tender no.", "tender no")
        subject = cell_value(cells, "tender subject")
        organisation = cell_value(cells, "organisation", "organization")
        winner = cell_value(cells, "winner")
        total = cell_value(cells, "total")
        notes = cell_value(cells, "notes")
        item_no = cell_value(cells, "sr no")
        if not tender_no and not subject:
            continue
        rows.append(
            {
                "meeting_date": parse_date_to_iso(meeting_date),
                "tender_no": tender_no,
                "subject": subject,
                "organisation": organisation,
                "winner": winner,
                "total": total,
                "notes": notes,
                "item_no": item_no,
                "notice_url": page_url,
            }
        )
    return rows


def scrape_capt(date_from: str, date_to: str, max_pages: int, headless: bool, translate: bool) -> List[Dict[str, str]]:
    translator = OptionalTranslator(enabled=translate)
    scraped_at = utc_now_iso()
    source_rows: List[Dict[str, str]] = []
    seen = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        discovered_last_page = 1

        for page_number in range(1, max_pages + 1):
            page_url = build_page_url(page_number, date_from, date_to)
            page.goto(page_url, wait_until="domcontentloaded", timeout=120000)
            wait_for_awards_table(page)
            page.wait_for_timeout(1500)
            html = page.content()
            discovered_last_page = max(discovered_last_page, discover_last_page_number(html))
            parsed_rows = parse_award_rows(html, page_url)
            if not parsed_rows and page_number >= discovered_last_page:
                break
            for row in parsed_rows:
                key = stable_key(row["tender_no"], row["meeting_date"], row["winner"], row["subject"])
                if key in seen:
                    continue
                seen.add(key)
                source_rows.append(row)
            if page_number >= discovered_last_page:
                break

        context.close()
        browser.close()

    output_rows: List[Dict[str, str]] = []
    for row in source_rows:
        awarded_date = row["meeting_date"]
        if not in_date_window(awarded_date, date_from, date_to):
            continue
        amount, currency = split_amount_and_currency(row["total"], default_currency="KWD")
        base_row = {
            "source": "CAPT Winning Bids",
            "country": "Kuwait",
            "country_code": "KW",
            "publication_date": awarded_date,
            "closing_date": "",
            "title": row["subject"],
            "description": row["notes"] or row["subject"],
            "buyer": row["organisation"],
            "classification": "winning bid",
            "status": "awarded",
            "currency": currency,
            "amount": amount,
            "awarding_agency_name": row["organisation"],
            "supplier_name": row["winner"],
            "awarded_date": awarded_date,
            "awarded_value_detail": row["total"],
            "contract_period": "",
            "item_no": row["item_no"],
            "item_description": row["subject"],
            "item_uom": "",
            "item_quantity": "",
            "item_unit_price": "",
            "item_awarded_value": amount,
            "notice_id": row["tender_no"],
            "notice_url": row["notice_url"],
            "query_text": f"meeting_date_from={date_from}&meeting_date_to={date_to}",
            "scraped_at_utc": scraped_at,
            "dedup_key": stable_key(row["tender_no"], awarded_date, row["winner"], row["subject"]),
        }
        output_rows.append(add_translation_columns(base_row, translator))
    return output_rows


def main() -> None:
    args = parse_args()
    rows = scrape_capt(
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
        headless=args.headless,
        translate=args.translate,
    )
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(
        json.dumps(
            {
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
