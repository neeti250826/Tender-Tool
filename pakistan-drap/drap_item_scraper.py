#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: playwright") from exc


BASE_URL = "https://www.dra.gov.pk"
LIST_URL = f"{BASE_URL}/category/news_updates/tenders/"
FIELDNAMES = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "closing_date",
    "title",
    "description",
    "buyer",
    "classification",
    "status",
    "currency",
    "amount",
    "awarding_agency_name",
    "supplier_name",
    "awarded_date",
    "awarded_value_detail",
    "contract_period",
    "item_no",
    "item_description",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_awarded_value",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]
DEFAULT_QUERY_TEXT = "drap tenders item-level"


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    raw = str(value)
    if "<" in raw and ">" in raw:
        text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    else:
        text = raw
    return re.sub(r"\s+", " ", text).strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_key(*parts: str) -> str:
    joined = "|".join(clean_text(part) for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape DRAP tender pages and parse item-level rows from linked tender PDFs."
    )
    parser.add_argument("--max-pages", type=int, default=2, help="Maximum listing pages to scan.")
    parser.add_argument("--max-tenders", type=int, default=10, help="Maximum detail pages to scrape.")
    parser.add_argument("--headless", action="store_true", help="Run Chromium in headless mode.")
    parser.add_argument("--query-text", default=DEFAULT_QUERY_TEXT, help="Value written to query_text.")
    parser.add_argument("--output-jsonl", default="Pakistan/DRAP/drap_item_tenders.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/DRAP/drap_item_tenders.csv")
    return parser.parse_args()


def build_listing_url(page_number: int) -> str:
    return LIST_URL if page_number <= 1 else f"{LIST_URL}page/{page_number}/"


def parse_date_to_iso(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    patterns = [
        ("%B %d, %Y", r"[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"),
        ("%b %d, %Y", r"[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"),
        ("%Y-%m-%d", r"\d{4}-\d{2}-\d{2}"),
        ("%d/%m/%Y", r"\d{1,2}/\d{1,2}/\d{4}"),
    ]
    for fmt, pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(0), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def wait_for_listing(page) -> None:
    selectors = [
        "article",
        ".post",
        "text=Tenders",
    ]
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
    selectors = [
        'a[href$=".pdf"]',
        "h1",
        "article",
    ]
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
        date_text = ""
        time_node = article.select_one("time")
        if time_node is not None:
            date_text = clean_text(time_node.get("datetime") or time_node.get_text(" ", strip=True))
        else:
            meta = article.select_one(".entry-meta, .posted-on")
            date_text = clean_text(meta.get_text(" ", strip=True)) if meta else ""
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
    publication_date = ""
    if time_node is not None:
        publication_date = parse_date_to_iso(time_node.get("datetime") or time_node.get_text(" ", strip=True))
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
    for page in reader.pages:
        page_text = page.extract_text() or ""
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
    if not text:
        return "", ""
    match = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*(.*)", text)
    if not match:
        return text, ""
    return match.group(1), clean_text(match.group(2))


def parse_item_lines_from_pdf(text: str) -> List[Dict[str, str]]:
    normalized = text.replace("\r", "\n")
    items: List[Dict[str, str]] = []

    pattern = re.compile(
        r"(?:^|\n)\s*(\d{1,3})[.)\-]?\s+([^\n]+?)\s+Quantity[:\s]+([0-9][^\n]*)",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(normalized):
        quantity, uom = split_quantity_and_uom(match.group(3))
        items.append(
            {
                "item_no": clean_text(match.group(1)),
                "item_description": clean_text(match.group(2)),
                "item_quantity": quantity,
                "item_uom": uom,
                "item_unit_price": "",
                "item_awarded_value": "",
            }
        )

    if items:
        return items

    # Fallback for schedule-style sections seen in EPADS/DRAP-like tender PDFs.
    fallback_pattern = re.compile(
        r"(?:item|equipment)\s*[:\-]?\s*([^\n|]+).*?quantity\s*[:\-]?\s*([0-9][^\n|]*)",
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
                "item_unit_price": "",
                "item_awarded_value": "",
            }
        )
    return items


def serialize_rows(rows: Iterable[Dict[str, str]], output_jsonl: str, output_csv: str) -> None:
    jsonl_path = Path(output_jsonl)
    csv_path = Path(output_csv)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in materialized:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)


def scrape_drap(max_pages: int, max_tenders: int, headless: bool, query_text: str) -> List[Dict[str, str]]:
    tender_targets: List[Dict[str, str]] = []
    seen_urls = set()
    scraped_at = utc_now_iso()

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
                if row["notice_url"] in seen_urls:
                    continue
                seen_urls.add(row["notice_url"])
                tender_targets.append(row)
                if len(tender_targets) >= max_tenders:
                    break
            if len(tender_targets) >= max_tenders:
                break

        detailed_targets: List[Dict[str, object]] = []
        for row in tender_targets:
            page.goto(row["notice_url"], wait_until="domcontentloaded", timeout=120000)
            page.wait_for_load_state("networkidle", timeout=120000)
            wait_for_detail(page)
            detail = parse_detail_page(page.content(), row["notice_url"])
            detail["listing_publication_date"] = row["publication_date"]
            detail["listing_description"] = row["description"]
            detail["notice_url"] = row["notice_url"]
            detailed_targets.append(detail)

        context.close()
        browser.close()

    session = build_session()
    rows: List[Dict[str, str]] = []
    for detail in detailed_targets:
        pdf_links = detail.get("pdf_links", [])
        if not isinstance(pdf_links, list) or not pdf_links:
            continue
        pdf_text = ""
        chosen_pdf = ""
        for pdf_url in pdf_links:
            try:
                pdf_text = fetch_pdf_text(session, pdf_url)
                chosen_pdf = pdf_url
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
        for item in items:
            item_index = item.get("item_no") or str(len(rows) + 1)
            dedup_key = stable_key(notice_id, clean_text(detail.get("notice_url", "")), item_index, item.get("item_description", ""))
            rows.append(
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
                    "item_no": clean_text(item.get("item_no", "")),
                    "item_description": clean_text(item.get("item_description", "")),
                    "item_uom": clean_text(item.get("item_uom", "")),
                    "item_quantity": clean_text(item.get("item_quantity", "")),
                    "item_unit_price": clean_text(item.get("item_unit_price", "")),
                    "item_awarded_value": clean_text(item.get("item_awarded_value", "")),
                    "notice_id": notice_id,
                    "notice_url": clean_text(detail.get("notice_url", "")),
                    "query_text": query_text,
                    "scraped_at_utc": scraped_at,
                    "dedup_key": dedup_key,
                }
            )
    return rows


def main() -> None:
    args = parse_args()
    rows = scrape_drap(
        max_pages=args.max_pages,
        max_tenders=args.max_tenders,
        headless=args.headless,
        query_text=args.query_text,
    )
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(
        json.dumps(
            {
                "rows_written": len(rows),
                "output_jsonl": args.output_jsonl,
                "output_csv": args.output_csv,
                "max_pages": args.max_pages,
                "max_tenders": args.max_tenders,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
