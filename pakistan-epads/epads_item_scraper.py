#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: playwright") from exc


BASE_URL = "https://epads.gov.pk"
LIST_URL = f"{BASE_URL}/open-procurements"
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
DEFAULT_QUERY_TEXT = "item-level public procurement"


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
        description="Scrape EPADS open procurements with public item rows from HTML detail pages."
    )
    parser.add_argument("--max-pages", type=int, default=2, help="Maximum listing pages to scan.")
    parser.add_argument("--max-tenders", type=int, default=10, help="Maximum number of tender detail pages to scrape.")
    parser.add_argument("--headless", action="store_true", help="Run Chromium in headless mode.")
    parser.add_argument("--query-text", default=DEFAULT_QUERY_TEXT, help="Value written to query_text.")
    parser.add_argument("--output-jsonl", default="Pakistan/EPADS/epads_item_tenders.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/EPADS/epads_item_tenders.csv")
    return parser.parse_args()


def listing_page_url(page_number: int) -> str:
    return LIST_URL if page_number <= 1 else f"{LIST_URL}?page={page_number}"


def wait_for_listing(page) -> None:
    selectors = [
        "table tbody tr",
        'a[href^="/opportunities/federal/procurements/"]',
        "text=Open Procurements",
    ]
    last_error: Optional[Exception] = None
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=10000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
    if last_error:
        raise last_error


def wait_for_detail(page) -> None:
    selectors = [
        "text=Items Without Lots",
        "h1",
        "button.show-specs",
    ]
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=8000)
            return
        except PlaywrightTimeoutError:
            continue


def extract_first_date(text: str) -> str:
    cleaned = clean_text(text)
    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
        r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
    return ""


def split_quantity_and_uom(raw_value: str) -> Tuple[str, str]:
    text = clean_text(raw_value)
    if not text:
        return "", ""
    match = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*(.*)", text)
    if not match:
        return text, ""
    return match.group(1), clean_text(match.group(2))


def parse_label_value_lines(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    patterns = {
        "quantity": r"Quantity:\s*([^\n\r]+)",
        "schedule": r"Schedule:\s*([^\n\r]+)",
        "address": r"Address:\s*([^\n\r]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        result[key] = clean_text(match.group(1)) if match else ""
    return result


def parse_listing_rows(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    seen_urls = set()
    for tr in soup.select("table tbody tr"):
        detail_anchor = tr.select_one('a[href^="/opportunities/federal/procurements/"]')
        if detail_anchor is None:
            continue
        notice_url = urljoin(BASE_URL, detail_anchor.get("href", ""))
        if not notice_url or notice_url in seen_urls:
            continue
        seen_urls.add(notice_url)
        row_text = clean_text(tr.get_text(" ", strip=True))
        badges = [clean_text(node.get_text(" ", strip=True)) for node in tr.select(".badge, .rounded-pill, .tender-badge")]
        notice_id_match = re.search(r"\bP\d+\b", row_text)
        notice_id = notice_id_match.group(0) if notice_id_match else notice_url.rstrip("/").split("/")[-1]
        title = clean_text(detail_anchor.get_text(" ", strip=True))
        buyer = ""
        for node in tr.select("[title]"):
            title_attr = clean_text(node.get("title", ""))
            if title_attr and title_attr != title:
                buyer = title_attr
                break
        if not buyer:
            small_texts = [clean_text(node.get_text(" ", strip=True)) for node in tr.select("small, span")]
            for candidate in small_texts:
                if candidate and candidate != title and len(candidate) > 6 and not re.search(r"\d{4}", candidate):
                    buyer = candidate
                    break
        closing_date = extract_first_date(row_text)
        status = ""
        for badge in badges:
            lowered = badge.lower()
            if lowered in {"open", "closed", "active", "cancelled"}:
                status = badge
                break
        classification = " | ".join([badge for badge in badges if badge and badge != notice_id and badge != status])
        rows.append(
            {
                "notice_id": notice_id,
                "notice_url": notice_url,
                "title": title,
                "buyer": buyer,
                "classification": classification,
                "status": status,
                "closing_date": closing_date,
                "listing_text": row_text,
            }
        )
    return rows


def parse_notice_id_from_url(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    if tail.isdigit():
        return f"P{tail}"
    return tail


def extract_heading_text(soup: BeautifulSoup) -> str:
    heading = soup.find(["h1", "h2"])
    return clean_text(heading.get_text(" ", strip=True)) if heading else ""


def find_detail_value(soup: BeautifulSoup, label: str) -> str:
    label_pattern = re.compile(rf"^{re.escape(label)}\s*$", flags=re.IGNORECASE)
    for node in soup.find_all(["dt", "strong", "span", "div", "p", "li"]):
        text = clean_text(node.get_text(" ", strip=True))
        if not label_pattern.match(text):
            continue
        sibling = node.find_next_sibling()
        if sibling:
            sibling_text = clean_text(sibling.get_text(" ", strip=True))
            if sibling_text and sibling_text != text:
                return sibling_text
    page_text = clean_text(soup.get_text("\n", strip=True))
    match = re.search(rf"{re.escape(label)}\s*:?\s*([^\n]+)", page_text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def parse_item_cards(soup: BeautifulSoup) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    title_nodes = soup.select(".listing-style li h6, .listing-style li h5, li h6, li h5")
    for title_node in title_nodes:
        container = title_node.find_parent("li") or title_node.parent
        if container is None:
            continue
        text = clean_text(container.get_text("\n", strip=True))
        if "Quantity:" not in text:
            continue
        item_title = clean_text(title_node.get_text(" ", strip=True))
        values = parse_label_value_lines(text)
        specs_button = container.select_one("button.show-specs")
        specs_text = ""
        if specs_button is not None:
            specs_text = clean_text(specs_button.get("data-specs", ""))
        quantity, uom = split_quantity_and_uom(values.get("quantity", ""))
        item_description = item_title
        if specs_text:
            item_description = f"{item_description} | Specs: {specs_text}" if item_description else specs_text
        if values.get("address"):
            item_description = f"{item_description} | Address: {values['address']}" if item_description else values["address"]
        if not item_description and not quantity:
            continue
        items.append(
            {
                "item_description": item_description,
                "item_quantity": quantity,
                "item_uom": uom,
                "contract_period": values.get("schedule", ""),
            }
        )
    return items


def parse_detail_page(html: str, notice_url: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text("\n", strip=True))
    publication_date = extract_first_date(find_detail_value(soup, "Published Date")) or extract_first_date(page_text)
    closing_date = extract_first_date(find_detail_value(soup, "Closing Date"))
    notice_title = extract_heading_text(soup)
    items = parse_item_cards(soup)
    return {
        "publication_date": publication_date,
        "closing_date": closing_date,
        "buyer": "",
        "classification": "",
        "description": notice_title,
        "items": items,
        "status": "open" if "open procurement" in page_text.lower() or "closing" in page_text.lower() else "",
        "notice_id": parse_notice_id_from_url(notice_url),
    }


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


def scrape_epads(max_pages: int, max_tenders: int, headless: bool, query_text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
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
        detail_targets: List[Dict[str, str]] = []
        seen_notice_urls = set()

        for page_number in range(1, max_pages + 1):
            page.goto(listing_page_url(page_number), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(2000)
            wait_for_listing(page)
            listing_rows = parse_listing_rows(page.content())
            if not listing_rows:
                break
            for listing_row in listing_rows:
                notice_url = listing_row["notice_url"]
                if notice_url in seen_notice_urls:
                    continue
                seen_notice_urls.add(notice_url)
                detail_targets.append(listing_row)
                if len(detail_targets) >= max_tenders:
                    break
            if len(detail_targets) >= max_tenders:
                break

        for listing_row in detail_targets:
            page.goto(listing_row["notice_url"], wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(2000)
            wait_for_detail(page)
            detail = parse_detail_page(page.content(), listing_row["notice_url"])
            item_rows = detail["items"] if isinstance(detail["items"], list) else []
            if not item_rows:
                item_rows = [{"item_description": listing_row["title"], "item_quantity": "", "item_uom": "", "contract_period": ""}]
            for index, item in enumerate(item_rows, start=1):
                notice_id = listing_row["notice_id"] or str(detail.get("notice_id", ""))
                title = listing_row["title"] or clean_text(detail.get("description", ""))
                description = clean_text(detail.get("description", "")) or title
                buyer = listing_row["buyer"]
                classification = listing_row["classification"]
                closing_date = clean_text(detail.get("closing_date", "")) or listing_row["closing_date"]
                status = clean_text(detail.get("status", "")) or listing_row["status"] or "open"
                dedup_key = stable_key(notice_id, listing_row["notice_url"], str(index), item.get("item_description", ""))
                rows.append(
                    {
                        "source": "EPADS Open Procurements",
                        "country": "Pakistan",
                        "country_code": "PK",
                        "publication_date": clean_text(detail.get("publication_date", "")),
                        "closing_date": closing_date,
                        "title": title,
                        "description": description,
                        "buyer": buyer,
                        "classification": classification,
                        "status": status,
                        "currency": "",
                        "amount": "",
                        "awarding_agency_name": buyer,
                        "supplier_name": "",
                        "awarded_date": "",
                        "awarded_value_detail": "",
                        "contract_period": clean_text(item.get("contract_period", "")),
                        "item_no": str(index),
                        "item_description": clean_text(item.get("item_description", "")),
                        "item_uom": clean_text(item.get("item_uom", "")),
                        "item_quantity": clean_text(item.get("item_quantity", "")),
                        "item_unit_price": "",
                        "item_awarded_value": "",
                        "notice_id": notice_id,
                        "notice_url": listing_row["notice_url"],
                        "query_text": query_text,
                        "scraped_at_utc": scraped_at,
                        "dedup_key": dedup_key,
                    }
                )

        context.close()
        browser.close()
    return rows


def main() -> None:
    args = parse_args()
    rows = scrape_epads(
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
