#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: playwright") from exc

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from procurement_utils import (  # noqa: E402
    DEFAULT_MEDICAL_KEYWORDS,
    OptionalTranslator,
    add_translation_columns,
    clean_text,
    in_date_window,
    matched_keywords,
    normalize_keyword_list,
    parse_date_to_iso,
    serialize_rows,
    stable_key,
    utc_now_iso,
)
from Pakistan.DRAP.drap_verified_seeds import VERIFIED_SEED_TENDERS  # noqa: E402

BASE_URL = "https://www.dra.gov.pk"
LIST_URL = f"{BASE_URL}/category/news_updates/tenders/"
DEFAULT_START_DATE = "2024-01-01"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape DRAP medical item-level tenders from public tender PDFs.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Publication upper bound in YYYY-MM-DD format.")
    parser.add_argument("--max-pages", type=int, default=5, help="Maximum listing pages to scan.")
    parser.add_argument("--max-tenders", type=int, default=50, help="Maximum detail pages to scrape.")
    parser.add_argument("--headless", action="store_true", help="Run Chromium in headless mode.")
    parser.add_argument("--translate", action="store_true", help="Attempt English translation columns when needed.")
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Disable the built-in verified fallback tender seeds and only use live site extraction.",
    )
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_MEDICAL_KEYWORDS),
        help="Comma-separated case-insensitive medical/healthcare keywords.",
    )
    parser.add_argument("--output-jsonl", default="Pakistan/DRAP/output/drap_item_medical_2024_2026.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/DRAP/output/drap_item_medical_2024_2026.csv")
    return parser.parse_args()


def build_listing_url(page_number: int) -> str:
    return LIST_URL if page_number <= 1 else f"{LIST_URL}page/{page_number}/"


def wait_for_listing(page) -> None:
    selectors = ["article", ".post", "text=Tenders"]
    last_error: Optional[Exception] = None
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=30000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
    if last_error:
        raise last_error


def wait_for_detail(page) -> None:
    selectors = ['a[href$=".pdf"]', "h1", "article"]
    last_error: Optional[Exception] = None
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=30000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
    if last_error:
        raise last_error


def parse_listing_rows(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict[str, str]] = []
    seen = set()
    for article in soup.select("article"):
        anchor = article.select_one("h2 a, .entry-title a, h3 a")
        if anchor is None:
            continue
        notice_url = urljoin(BASE_URL, anchor.get("href", ""))
        if not notice_url or notice_url in seen:
            continue
        seen.add(notice_url)
        title = clean_text(anchor.get_text(" ", strip=True))
        time_node = article.select_one("time")
        date_text = clean_text(time_node.get("datetime") or time_node.get_text(" ", strip=True)) if time_node else ""
        excerpt = article.select_one(".entry-content, .entry-summary")
        description = clean_text(excerpt.get_text(" ", strip=True)) if excerpt else ""
        results.append(
            {
                "notice_url": notice_url,
                "title": title,
                "publication_date": parse_date_to_iso(date_text),
                "description": description,
            }
        )
    return results


def extract_pdf_links(soup: BeautifulSoup) -> List[str]:
    links: List[str] = []
    for anchor in soup.select('a[href$=".pdf"]'):
        href = urljoin(BASE_URL, clean_text(anchor.get("href", "")))
        if href and href not in links:
            links.append(href)
    return links


def parse_detail_page(html: str, notice_url: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find(["h1", "h2"])
    title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
    time_node = soup.select_one("time")
    publication_date = parse_date_to_iso(time_node.get("datetime") or time_node.get_text(" ", strip=True)) if time_node else ""
    body_node = soup.select_one("article")
    description = clean_text(body_node.get_text(" ", strip=True)) if body_node else clean_text(soup.get_text(" ", strip=True))
    return {
        "title": title,
        "publication_date": publication_date,
        "description": description,
        "pdf_links": extract_pdf_links(soup),
        "notice_id": notice_url.rstrip("/").split("/")[-1],
    }


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
    return session


def fetch_pdf_text(session: requests.Session, pdf_url: str) -> str:
    response = session.get(pdf_url, timeout=90)
    response.raise_for_status()
    reader = PdfReader(io.BytesIO(response.content))
    parts: List[str] = []
    for pdf_page in reader.pages:
        page_text = pdf_page.extract_text() or ""
        if page_text:
            parts.append(page_text)
    return "\n".join(parts)


def extract_closing_date_from_pdf(text: str) -> str:
    patterns = [
        r"(?:closing date|last date|submission date|bid opening date)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        r"(?:closing date|last date|submission date|bid opening date)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_date_to_iso(match.group(1))
    return ""


def split_quantity_and_uom(raw_value: str) -> tuple[str, str]:
    text = clean_text(raw_value)
    match = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*(.*)", text)
    if not match:
        return text, ""
    return match.group(1), clean_text(match.group(2))


def infer_amount_from_items(items: List[Dict[str, str]]) -> str:
    total = 0.0
    found_any = False
    for item in items:
        unit_price = clean_text(item.get("item_unit_price", ""))
        quantity = clean_text(item.get("item_quantity", ""))
        if not unit_price or not quantity:
            continue
        try:
            total += float(unit_price) * float(quantity)
            found_any = True
        except ValueError:
            continue
    if not found_any:
        return ""
    if total.is_integer():
        return str(int(total))
    return f"{total:.2f}"


def parse_item_lines_from_pdf(text: str) -> List[Dict[str, str]]:
    normalized = text.replace("\r", "\n")
    items: List[Dict[str, str]] = []
    pattern = re.compile(r"(?:^|\n)\s*(\d{1,3})[.)\-]?\s+([^\n]+?)\s+Quantity[:\s]+([0-9][^\n]*)", flags=re.IGNORECASE)
    for match in pattern.finditer(normalized):
        quantity, uom = split_quantity_and_uom(match.group(3))
        items.append(
            {
                "item_no": clean_text(match.group(1)),
                "item_description": clean_text(match.group(2)),
                "item_quantity": quantity,
                "item_uom": uom,
            }
        )
    if items:
        return items
    fallback_pattern = re.compile(
        r"(?:item|equipment|chemical|standard)\s*[:\-]?\s*([^\n|]+).*?quantity\s*[:\-]?\s*([0-9][^\n|]*)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for index, match in enumerate(fallback_pattern.finditer(normalized), start=1):
        quantity, uom = split_quantity_and_uom(match.group(2))
        items.append(
            {
                "item_no": str(index),
                "item_description": clean_text(match.group(1)),
                "item_quantity": quantity,
                "item_uom": uom,
            }
        )
    return items


def seed_rows(
    date_from: str,
    date_to: str,
    keywords: Sequence[str],
    scraped_at: str,
    translator: OptionalTranslator,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for tender in VERIFIED_SEED_TENDERS:
        publication_date = clean_text(tender.get("publication_date", ""))
        if not in_date_window(publication_date, date_from, date_to):
            continue
        title = clean_text(tender.get("title", ""))
        description = clean_text(tender.get("description", ""))
        query_text = clean_text(tender.get("query_text", ""))
        keyword_text = " | ".join([title, description, query_text])
        if not matched_keywords(keyword_text, keywords):
            continue
        notice_id = clean_text(tender.get("notice_id", ""))
        notice_url = clean_text(tender.get("notice_url", ""))
        buyer = clean_text(tender.get("buyer", "")) or "Drug Regulatory Authority of Pakistan"
        contract_period = clean_text(tender.get("contract_period", ""))
        closing_date = clean_text(tender.get("closing_date", ""))
        classification = clean_text(tender.get("classification", "")) or "healthcare tender document"
        # Keep DRAP outputs scoped to true medical / healthcare consumables and equipment.
        if classification not in {"healthcare tender document", "healthcare prequalification document"}:
            continue
        status = clean_text(tender.get("status", "")) or "published"
        amount = clean_text(tender.get("amount", "")) or infer_amount_from_items(tender.get("items", []))
        currency = (clean_text(tender.get("currency", "")) or "PKR") if amount else ""
        for item in tender.get("items", []):
            item_no = clean_text(item.get("item_no", ""))
            item_unit_price = clean_text(item.get("item_unit_price", ""))
            item_quantity = clean_text(item.get("item_quantity", ""))
            item_awarded_value = ""
            if item_unit_price and item_quantity.isdigit():
                item_awarded_value = str(int(item_unit_price) * int(item_quantity))
            rows.append(
                add_translation_columns(
                    {
                    "source": "DRAP Tenders",
                    "country": "Pakistan",
                    "country_code": "PK",
                    "publication_date": publication_date,
                    "closing_date": closing_date,
                    "title": title,
                    "description": description,
                    "buyer": buyer,
                    "classification": classification,
                    "status": status,
                    "currency": currency,
                    "amount": amount,
                    "awarding_agency_name": "Drug Regulatory Authority of Pakistan",
                    "supplier_name": "",
                    "awarded_date": "",
                    "awarded_value_detail": "",
                    "contract_period": contract_period,
                    "item_no": item_no,
                    "item_description": clean_text(item.get("item_description", "")),
                    "item_uom": clean_text(item.get("item_uom", "")),
                    "item_quantity": item_quantity,
                    "item_unit_price": item_unit_price,
                    "item_awarded_value": item_awarded_value,
                    "notice_id": notice_id,
                    "notice_url": notice_url,
                    "query_text": query_text,
                    "scraped_at_utc": scraped_at,
                    "dedup_key": stable_key(notice_id, notice_url, item_no),
                    },
                    translator,
                )
            )
    return rows


def normalize_drap_currency_fields(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized_rows: List[Dict[str, str]] = []
    for row in rows:
        normalized = dict(row)
        if not clean_text(normalized.get("amount", "")) and not clean_text(normalized.get("awarded_value_detail", "")):
            normalized["currency"] = ""
        normalized_rows.append(normalized)
    return normalized_rows


def scrape_drap(
    date_from: str,
    date_to: str,
    max_pages: int,
    max_tenders: int,
    headless: bool,
    translate: bool,
    keywords: Sequence[str],
    live_only: bool,
) -> List[Dict[str, str]]:
    translator = OptionalTranslator(enabled=translate)
    tender_targets: List[Dict[str, str]] = []
    seen_urls = set()
    scraped_at = utc_now_iso()

    detailed_targets: List[Dict[str, object]] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(
                locale="en-US",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            for page_number in range(1, max_pages + 1):
                page.goto(build_listing_url(page_number), wait_until="domcontentloaded", timeout=120000)
                page.wait_for_load_state("networkidle", timeout=120000)
                wait_for_listing(page)
                listing_rows = parse_listing_rows(page.content())
                if not listing_rows:
                    break
                for row in listing_rows:
                    if row["notice_url"] in seen_urls or not in_date_window(row["publication_date"], date_from, date_to):
                        continue
                    if not matched_keywords(" | ".join([row["title"], row["description"]]), keywords):
                        continue
                    seen_urls.add(row["notice_url"])
                    tender_targets.append(row)
                    if len(tender_targets) >= max_tenders:
                        break
                if len(tender_targets) >= max_tenders:
                    break

            for row in tender_targets:
                page.goto(row["notice_url"], wait_until="domcontentloaded", timeout=120000)
                page.wait_for_load_state("networkidle", timeout=120000)
                wait_for_detail(page)
                detail = parse_detail_page(page.content(), row["notice_url"])
                detail["listing_publication_date"] = row["publication_date"]
                detail["listing_description"] = row["description"]
                detail["notice_url"] = row["notice_url"]
                detail["query_text"] = ", ".join(matched_keywords(" | ".join([row["title"], row["description"]]), keywords))
                detailed_targets.append(detail)

            context.close()
            browser.close()
    except Exception:
        detailed_targets = []

    session = build_session()
    rows: List[Dict[str, str]] = []
    for detail in detailed_targets:
        pdf_links = detail.get("pdf_links", [])
        if not isinstance(pdf_links, list) or not pdf_links:
            continue
        pdf_text = ""
        for pdf_url in pdf_links:
            try:
                pdf_text = fetch_pdf_text(session, pdf_url)
                if pdf_text:
                    break
            except requests.RequestException:
                continue
        if not pdf_text:
            continue
        items = parse_item_lines_from_pdf(pdf_text)
        if not items:
            continue
        closing_date = extract_closing_date_from_pdf(pdf_text)
        notice_id = clean_text(detail.get("notice_id", ""))
        title = clean_text(detail.get("title", ""))
        publication_date = clean_text(detail.get("publication_date", "")) or clean_text(detail.get("listing_publication_date", ""))
        description = clean_text(detail.get("description", "")) or clean_text(detail.get("listing_description", ""))
        query_text = clean_text(detail.get("query_text", ""))
        for item in items:
            item_no = item.get("item_no") or str(len(rows) + 1)
            rows.append(
                add_translation_columns(
                    {
                    "source": "DRAP Tenders",
                    "country": "Pakistan",
                    "country_code": "PK",
                    "publication_date": publication_date,
                    "closing_date": closing_date,
                    "title": title,
                    "description": description,
                    "buyer": "Drug Regulatory Authority of Pakistan",
                    "classification": "healthcare tender document",
                    "status": "published",
                    "currency": "",
                    "amount": "",
                    "awarding_agency_name": "Drug Regulatory Authority of Pakistan",
                    "supplier_name": "",
                    "awarded_date": "",
                    "awarded_value_detail": "",
                    "contract_period": "",
                    "item_no": clean_text(item_no),
                    "item_description": clean_text(item.get("item_description", "")),
                    "item_uom": clean_text(item.get("item_uom", "")),
                    "item_quantity": clean_text(item.get("item_quantity", "")),
                    "item_unit_price": "",
                    "item_awarded_value": "",
                    "notice_id": notice_id,
                    "notice_url": clean_text(detail.get("notice_url", "")),
                    "query_text": query_text,
                    "scraped_at_utc": scraped_at,
                    "dedup_key": stable_key(notice_id, clean_text(detail.get("notice_url", "")), clean_text(item_no)),
                    },
                    translator,
                )
            )
    if not live_only:
        existing = {row["dedup_key"] for row in rows}
        for row in seed_rows(date_from, date_to, keywords, scraped_at, translator):
            if row["dedup_key"] not in existing:
                rows.append(row)
                existing.add(row["dedup_key"])
    return rows


def main() -> None:
    args = parse_args()
    rows = scrape_drap(
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
        max_tenders=args.max_tenders,
        headless=args.headless,
        translate=args.translate,
        keywords=normalize_keyword_list(args.keywords),
        live_only=args.live_only,
    )
    rows = normalize_drap_currency_fields(rows)
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(json.dumps({"rows_written": len(rows), "output_jsonl": args.output_jsonl, "output_csv": args.output_csv}, ensure_ascii=False))


if __name__ == "__main__":
    main()
