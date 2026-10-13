#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LIST_URL = "https://ssmc.ae/wp-json/wp/v2/tender"
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_KEYWORDS = [
    "medical",
    "medicine",
    "medic",
    "pharma",
    "pharmaceutical",
    "hospital",
    "clinic",
    "device",
    "devices",
    "equipment",
    "supply",
    "supplies",
    "consumable",
    "consumables",
    "surgical",
    "diagnostic",
    "imaging",
    "laboratory",
    "lab",
    "drug",
    "drugs",
    "implant",
    "icu",
    "ventilator",
    "monitor",
    "scanner",
    "ultrasound",
    "radiology",
]
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


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_key(*parts: str) -> str:
    joined = "|".join(clean_text(part) for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


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
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape SSMC tender notices exposed by the public WordPress API and keep likely medical/equipment notices."
    )
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication date lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Publication date upper bound in YYYY-MM-DD format.")
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated case-insensitive keywords used to keep likely medical/equipment tenders.",
    )
    parser.add_argument("--output-jsonl", default="UAE/ssmc_medical_tenders_2024_to_recent.jsonl")
    parser.add_argument("--output-csv", default="UAE/ssmc_medical_tenders_2024_to_recent.csv")
    return parser.parse_args()


def normalize_keyword_list(raw_keywords: str) -> List[str]:
    parts = [clean_text(part).lower() for part in raw_keywords.split(",")]
    return [part for part in parts if part]


def parse_iso_date(value: str) -> Optional[date]:
    text = clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def in_window(value: str, date_from: str, date_to: str) -> bool:
    current = parse_iso_date(value)
    if not current:
        return False
    start = parse_iso_date(date_from)
    end = parse_iso_date(date_to)
    if start and current < start:
        return False
    if end and current > end:
        return False
    return True


def fetch_posts(session: requests.Session, date_from: str, date_to: str) -> List[Dict]:
    page_number = 1
    total_pages = 1
    posts: List[Dict] = []
    while page_number <= total_pages:
        response = session.get(
            LIST_URL,
            params={
                "per_page": 100,
                "page": page_number,
                "_fields": "id,date,modified,slug,link,title,excerpt,content",
            },
            timeout=60,
        )
        response.raise_for_status()
        total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
        page_posts = response.json()
        if not page_posts:
            break
        for post in page_posts:
            if in_window(post.get("date", ""), date_from, date_to):
                posts.append(post)
        page_number += 1
    return posts


def extract_detail_field(html: str, label: str) -> str:
    pattern = rf"{re.escape(label)}\s*</label>\s*<span>\s*([^<]+)"
    match = re.search(pattern, html, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def extract_attachments(soup: BeautifulSoup) -> List[str]:
    attachments: List[str] = []
    attachments_heading = soup.find(lambda tag: tag.name in {"h3", "h4"} and clean_text(tag.get_text()) == "Attachments")
    if attachments_heading is None:
        return attachments
    parent = attachments_heading.parent
    if parent is None:
        return attachments
    for anchor in parent.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        if href:
            attachments.append(href)
    return attachments


def fetch_notice_details(session: requests.Session, notice_url: str) -> Dict[str, str]:
    response = session.get(notice_url, timeout=60)
    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True)).lower()
    availability_note = "This tender is no longer available" if "no longer available" in page_text else ""
    status = "closed" if availability_note else "published"
    last_purchase_date = extract_detail_field(html, "Last Purchase Date")
    closing_date = extract_detail_field(html, "Closing Date")
    attachments = extract_attachments(soup)
    return {
        "closing_date": parse_iso_date(closing_date).isoformat() if parse_iso_date(closing_date) else closing_date,
        "last_purchase_date": parse_iso_date(last_purchase_date).isoformat() if parse_iso_date(last_purchase_date) else last_purchase_date,
        "attachment_urls": " | ".join(attachments),
        "availability_note": availability_note,
        "status": status,
    }


def matched_keywords(text: str, keywords: Sequence[str]) -> List[str]:
    lowered = clean_text(text).lower()
    return [keyword for keyword in keywords if keyword in lowered]


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


def scrape_tenders(date_from: str, date_to: str, keywords: Sequence[str]) -> List[Dict[str, str]]:
    session = build_session()
    posts = fetch_posts(session, date_from=date_from, date_to=date_to)
    rows: List[Dict[str, str]] = []
    for post in posts:
        title = clean_text(post.get("title", {}).get("rendered"))
        body = clean_text(post.get("content", {}).get("rendered"))
        matched = matched_keywords(f"{title} {body}", keywords)
        if not matched:
            continue
        details = fetch_notice_details(session, post.get("link", ""))
        publication_date = parse_iso_date(post.get("date", ""))
        dedup_key = stable_key(post.get("id", ""), post.get("link", ""), post.get("date", ""))
        rows.append(
            {
                "source": "SSMC Tenders",
                "country": "United Arab Emirates",
                "country_code": "AE",
                "publication_date": publication_date.isoformat() if publication_date else "",
                "closing_date": details["closing_date"],
                "title": title,
                "description": body,
                "buyer": "Sheikh Shakhbout Medical City",
                "classification": "medical supplies or equipment (keyword matched notice)",
                "status": details["status"],
                "currency": "",
                "amount": "",
                "awarding_agency_name": "",
                "supplier_name": "",
                "awarded_date": "",
                "awarded_value_detail": "",
                "contract_period": "",
                "item_no": "",
                "item_description": title,
                "item_uom": "",
                "item_quantity": "",
                "item_unit_price": "",
                "item_awarded_value": "",
                "notice_id": str(post.get("id", "")),
                "notice_url": post.get("link", ""),
                "query_text": ", ".join(matched),
                "scraped_at_utc": utc_now_iso(),
                "dedup_key": dedup_key,
            }
        )
    return rows


def main() -> None:
    args = parse_args()
    keywords = normalize_keyword_list(args.keywords)
    rows = scrape_tenders(date_from=args.date_from, date_to=args.date_to, keywords=keywords)
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(
        json.dumps(
            {
                "rows_written": len(rows),
                "output_jsonl": args.output_jsonl,
                "output_csv": args.output_csv,
                "date_from": args.date_from,
                "date_to": args.date_to,
                "keywords": keywords,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
