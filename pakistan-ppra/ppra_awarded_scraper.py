#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

BASE_URL = "https://epms.ppra.gov.pk"
LIST_URL = f"{BASE_URL}/public/contracts"
DEFAULT_START_DATE = "2024-01-01"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape public PPRA awarded contract pages.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Publication upper bound in YYYY-MM-DD format.")
    parser.add_argument("--max-pages", type=int, default=100, help="Safety cap for paginated contract pages.")
    parser.add_argument("--translate", action="store_true", help="Attempt English translation columns when needed.")
    parser.add_argument("--output-jsonl", default="Pakistan/PPRA/output/ppra_awarded_2024_to_recent.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/PPRA/output/ppra_awarded_2024_to_recent.csv")
    return parser.parse_args()


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )
    retry = Retry(
        total=5,
        read=5,
        connect=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def build_page_url(page_number: int) -> str:
    return LIST_URL if page_number <= 1 else f"{LIST_URL}?page={page_number}"


def extract_line_value(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*[:\-]?\s*(.+)", text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def extract_notice_id(text: str) -> str:
    match = re.search(r"(PCN-[A-Z0-9\-]+|PCN-\d+)", text)
    return clean_text(match.group(1)) if match else ""


def parse_listing_rows(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    for tr in soup.select("table tbody tr"):
        cells = tr.select("td")
        if len(cells) < 8:
            continue
        contract_cell = clean_text(cells[1].get_text("\n", strip=True))
        details_cell = clean_text(cells[2].get_text("\n", strip=True))
        org_cell = clean_text(cells[3].get_text("\n", strip=True))
        value_cell = clean_text(cells[4].get_text("\n", strip=True))
        advertise_date = parse_date_to_iso(clean_text(cells[5].get_text(" ", strip=True)))
        links = tr.select("a[href]")
        detail_url = ""
        pdf_url = ""
        for anchor in links:
            href = urljoin(BASE_URL, clean_text(anchor.get("href", "")))
            if "/public/contracts/contract-details/" in href:
                detail_url = href
            elif "/pdf?file=" in href:
                pdf_url = href
        rows.append(
            {
                "contract_no": extract_notice_id(contract_cell),
                "detail_url": detail_url,
                "pdf_url": pdf_url,
                "listing_text": details_cell,
                "advertise_date": advertise_date,
                "contract_value_text": value_cell,
                "organization_card": org_cell,
            }
        )
    return rows


def extract_detail_value(page_text: str, label: str) -> str:
    patterns = [
        rf"{re.escape(label)}\s*:\s*([^\n]+)",
        rf"{re.escape(label)}\s+([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return ""


def parse_contract_detail(html: str, detail_url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text("\n", strip=True))
    title = extract_detail_value(page_text, "Contract Title")
    buyer_org = extract_detail_value(page_text, "Organization Name")
    buyer_office = extract_detail_value(page_text, "Office Name")
    buyer_address = extract_detail_value(page_text, "Office Address")
    city = extract_detail_value(page_text, "City/Location")
    nature_of_purchase = extract_detail_value(page_text, "Nature of Purchase")
    contract_signing_date = parse_date_to_iso(extract_detail_value(page_text, "Contract Signing Date"))
    awarded_amount_text = extract_detail_value(page_text, "Contract Price (Awarded Amount)")
    tender_value_text = extract_detail_value(page_text, "Tender Value")
    successful_bidder = extract_detail_value(page_text, "Bidder Name")
    tender_number = extract_detail_value(page_text, "Tender Number")
    tender_title = extract_detail_value(page_text, "Tender Title")
    published_on = parse_date_to_iso(extract_detail_value(page_text, "Published On"))
    return {
        "title": title or tender_title,
        "description": tender_title or title,
        "buyer_org": buyer_org,
        "buyer_office": buyer_office,
        "buyer_address": buyer_address,
        "city": city,
        "classification": nature_of_purchase,
        "awarded_date": contract_signing_date,
        "awarded_amount_text": awarded_amount_text or tender_value_text,
        "supplier_name": successful_bidder,
        "tender_number": tender_number,
        "publication_date": published_on,
        "detail_url": detail_url,
    }


def scrape_ppra(date_from: str, date_to: str, max_pages: int, translate: bool) -> List[Dict[str, str]]:
    translator = OptionalTranslator(enabled=translate)
    session = build_session()
    seen_contracts = set()
    scraped_at = utc_now_iso()
    output_rows: List[Dict[str, str]] = []

    for page_number in range(1, max_pages + 1):
        response = session.get(build_page_url(page_number), timeout=90)
        response.raise_for_status()
        listing_rows = parse_listing_rows(response.text)
        if not listing_rows:
            break
        rows_kept = 0
        for listing_row in listing_rows:
            contract_no = listing_row["contract_no"]
            detail_url = listing_row["detail_url"]
            if not contract_no or not detail_url or contract_no in seen_contracts:
                continue
            seen_contracts.add(contract_no)
            detail_response = session.get(detail_url, timeout=90)
            detail_response.raise_for_status()
            detail = parse_contract_detail(detail_response.text, detail_url)
            publication_date = detail["publication_date"] or listing_row["advertise_date"]
            if not in_date_window(publication_date, date_from, date_to):
                continue
            rows_kept += 1
            buyer = " | ".join(
                part for part in [detail["buyer_org"], detail["buyer_office"], detail["city"]] if clean_text(part)
            )
            description = detail["description"] or listing_row["listing_text"]
            amount, currency = split_amount_and_currency(detail["awarded_amount_text"], default_currency="PKR")
            notice_id = contract_no or detail["tender_number"]
            base_row = {
                "source": "PPRA Awarded Contracts",
                "country": "Pakistan",
                "country_code": "PK",
                "publication_date": publication_date,
                "closing_date": "",
                "title": detail["title"] or description,
                "description": description,
                "buyer": buyer,
                "classification": detail["classification"] or "awarded contract",
                "status": "awarded",
                "currency": currency,
                "amount": amount,
                "awarding_agency_name": detail["buyer_org"] or detail["buyer_office"],
                "supplier_name": detail["supplier_name"],
                "awarded_date": detail["awarded_date"],
                "awarded_value_detail": detail["awarded_amount_text"],
                "contract_period": "",
                "item_no": "1",
                "item_description": detail["title"] or description,
                "item_uom": "",
                "item_quantity": "",
                "item_unit_price": "",
                "item_awarded_value": amount,
                "notice_id": notice_id,
                "notice_url": detail_url,
                "query_text": "public awarded contracts",
                "scraped_at_utc": scraped_at,
                "dedup_key": stable_key(notice_id, detail_url, detail["supplier_name"], amount),
            }
            output_rows.append(add_translation_columns(base_row, translator))
        if rows_kept == 0 and listing_rows[-1]["advertise_date"] and listing_rows[-1]["advertise_date"] < date_from:
            break
    return output_rows


def main() -> None:
    args = parse_args()
    rows = scrape_ppra(
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
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
