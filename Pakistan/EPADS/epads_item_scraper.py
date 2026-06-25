#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
    serialize_rows,
    split_amount_and_currency,
    stable_key,
    utc_now_iso,
)
from Pakistan.EPADS.epads_verified_seeds import VERIFIED_SEED_TENDERS  # noqa: E402

BASE_URL = "https://www.epads.gov.pk"
LIST_URL = f"{BASE_URL}/loi-issued"
FALLBACK_LIST_URL = f"{BASE_URL}/open-procurements"
DEFAULT_START_DATE = "2024-01-01"

EPADS_GENERIC_KEYWORDS = {
    "consumable",
    "consumables",
    "equipment",
    "equipments",
    "items",
    "goods",
    "supplies",
    "accessories",
    "kit",
    "kits",
    "machinery",
    "furniture",
    "fixture",
    "fixtures",
}

EPADS_ALT_PUBLIC_NOTICE_URLS = {
    # Public annual-plan surface verified on 2026-06-01 via search-index evidence.
    "P41081": "https://epads.gov.pk/federal/annual-plan/procurement/1135/8839/2025-26?page=1",
}


def epads_product_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    return any(
        token in text
        for token in (
            "medical",
            "medicine",
            "drug",
            "pharma",
            "pharmaceutical",
            "hospital",
            "clinic",
            "clinical",
            "diagnostic",
            "laboratory",
            "lab ",
            "reagent",
            "reagents",
            "ivd",
            "test kit",
            "surgical",
            "medical equipment",
            "medical device",
            "hospital equipment",
            "first aid",
            "dental",
            "ophthalmic",
            "dialysis",
            "blood bag",
            "catheter",
            "cannula",
            "syringe",
            "glove",
            "mask",
            "implant",
            "injectable",
            "electro-medical",
            "consumables for mrna",
        )
    )


def epads_health_buyer_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    return any(
        token in text
        for token in (
            "health",
            "hospital",
            "medical",
            "clinic",
            "polyclinic",
            "dental",
            "pharmacy",
            "pharmaceutical",
            "nih",
            "nursing",
            "pathology",
            "laboratory",
            "lab ",
            "diagnostic",
        )
    )


def epads_healthcare_item_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    if not text:
        return False
    return any(
        token in text
        for token in (
            "medicine",
            "medicines",
            "drug",
            "drugs",
            "pharma",
            "pharmaceutical",
            "lab consumable",
            "lab consumables",
            "laboratory consumable",
            "laboratory consumables",
            "medical equipment",
            "medical equipments",
            "medical first aid",
            "first aid medicine",
            "first aid medicines",
            "first aid kit",
            "first aid kits",
            "operation theatre",
            "ot items",
            "specific consumables",
            "radiology",
            "ultrasound",
            "x-ray",
            "x ray",
        )
    )


def epads_scope_exclusion_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    return any(
        token in text
        for token in (
            "printing of medical treatment books",
            "medical treatment books",
            "treatment books",
            "year book printing",
            "yearbook",
            "health, safety",
            "hse (health",
            "electrical & mechanical consumables",
            "consumable items for electric",
            "hardware lab",
            "omr scanners",
            "omr software",
            "fire electric panel",
            "sewerage line",
            "janitorial items",
            "electronic communication device",
            "laboratory management system",
            "uncertainty of the measurement",
            "hand bag",
            "security protection gloves",
            "panaflex",
            "standee",
            "cctv cameras",
            "computers",
            "paper shredder",
            "keyboard",
            "keyboards",
            "wireless mouse",
            "standard mouse",
            "vga cable",
            "vga cables",
            "led tv",
            "glass partition",
            "wall glass",
            "biometric attendance",
            "facial attendance",
            "elevator maintenance",
            "green (lp) books",
            "printing of medical card",
            "acr papers",
            "x-ray envelops",
            "tonner cartridge",
            "toner cartridge",
            "laser jet",
            "metal detector",
            "walk-through metal detector",
            "walk through metal detector",
            "kitchen cabinets",
            "scanner repair",
            "crockery",
            "cutlery",
            "stationary items",
            "repair/maintenance of furniture",
            "repair and maintenance of washroom",
            "dry chemical powder",
            "repair/maintenance of vehicle",
            "lasser jet",
            "teltonika",
            "civil work",
            "vehicle scanner",
            "led monitor",
            "color printer",
            "national textile university",
            "national institute of oceanography",
            "pak - korea pv modules",
            "pv modules testing",
            "pakistan institute of fashion and design",
            "geological field survey",
            "gmo lab",
            "ym lab machines",
            "knitting lab machines",
            "sample spinner",
            "biosciences depart",
            "window bliends",
            "under table storage",
            "different types of 10 chemicals",
            "different types of 08 chemicals",
            "different types of 13 chemicals",
            "chemical (solvent) items",
        )
    )


def keep_epads_medical_row(matched: Sequence[str], *context_values: str) -> bool:
    normalized_matches = {clean_text(value).lower() for value in matched if clean_text(value)}
    if not normalized_matches:
        return False
    if epads_scope_exclusion_signal(*context_values):
        return False
    product_values = [value for index, value in enumerate(context_values) if index != 1]
    if epads_healthcare_item_signal(*product_values):
        return True
    non_generic_matches = normalized_matches - EPADS_GENERIC_KEYWORDS
    if non_generic_matches and not normalized_matches <= {"medical", "health", "hospital"} and epads_product_signal(*product_values):
        return True
    return False


def normalize_epads_saved_row(row: Dict[str, str], today: Optional[date] = None) -> Dict[str, str]:
    normalized = dict(row)
    today = today or date.today()
    notice_id = clean_text(normalized.get("notice_id", ""))
    notice_url = clean_text(normalized.get("notice_url", ""))
    alt_notice_url = EPADS_ALT_PUBLIC_NOTICE_URLS.get(notice_id, "")
    if alt_notice_url and "/opportunities/federal/procurements/" in notice_url:
        normalized["notice_url"] = alt_notice_url

    status = clean_text(normalized.get("status", "")).lower()
    closing_date = clean_text(normalized.get("closing_date", ""))
    if status == "open" and closing_date:
        try:
            if date.fromisoformat(closing_date) < today:
                normalized["status"] = "closed"
        except ValueError:
            pass
    if not clean_text(normalized.get("amount", "")) and not clean_text(normalized.get("awarded_value_detail", "")):
        normalized["currency"] = ""
    return normalized


def normalize_epads_currency_fields(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [normalize_epads_saved_row(row) for row in rows]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape EPADS medical public procurements from the LOI-issued listing.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Publication upper bound in YYYY-MM-DD format.")
    parser.add_argument("--max-pages", type=int, default=25, help="Maximum listing pages to scan.")
    parser.add_argument("--max-tenders", type=int, default=250, help="Maximum detail pages to scrape.")
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
    parser.add_argument("--output-jsonl", default="Pakistan/EPADS/output/epads_item_medical_2024_2026.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/EPADS/output/epads_item_medical_2024_2026.csv")
    return parser.parse_args()


def listing_page_url(base_url: str, page_number: int) -> str:
    return base_url if page_number <= 1 else f"{base_url}?page={page_number}"


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


def wait_for_listing(page) -> None:
    selectors = [
        "table tbody tr",
        "table",
        'a[href*="/procurements/"]',
        "text=System Issued LOI",
        "text=LOI",
        "text=Procurement Status",
    ]
    last_error: Optional[Exception] = None
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=15000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
    if last_error:
        raise last_error


def wait_for_detail(page) -> None:
    for selector in ["text=Items Without Lots", "text=Published Date", "h1", "button.show-specs"]:
        try:
            page.wait_for_selector(selector, timeout=10000)
            return
        except PlaywrightTimeoutError:
            continue


def extract_first_date(text: str) -> str:
    cleaned = clean_text(text)
    for pattern in [r"(\d{4}-\d{2}-\d{2})", r"(\d{1,2}/\d{1,2}/\d{4})", r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})"]:
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
    match = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*(.*)", text)
    if not match:
        return text, ""
    return match.group(1), clean_text(match.group(2))


def clean_schedule_text(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = re.split(r"\b(?:quantity|qty|address|specs?)\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return clean_text(text)


def parse_label_value_lines(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    patterns = {
        "quantity": r"Quantity:\s*(.*?)(?=\s+(?:Schedule:|Address:|Specs?:|Qty:)|$)",
        "schedule": r"Schedule:\s*(.*?)(?=\s+(?:Quantity:|Address:|Specs?:|Qty:)|$)",
        "address": r"Address:\s*(.*?)(?=\s+(?:Quantity:|Schedule:|Specs?:|Qty:)|$)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        result[key] = clean_text(match.group(1)) if match else ""
    result["schedule"] = clean_schedule_text(result.get("schedule", ""))
    return result


def parse_loi_listing_rows(soup: BeautifulSoup) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen_urls = set()
    for tr in soup.select("table tbody tr"):
        cells = tr.select("td")
        if len(cells) < 6:
            continue
        detail_anchor = tr.select_one('a[href*="/procurements/"]')
        notice_id = clean_text(cells[1].get_text(" ", strip=True))
        notice_number = notice_id[1:] if re.fullmatch(r"P\d+", notice_id, flags=re.IGNORECASE) else ""
        if detail_anchor is not None:
            notice_url = urljoin(BASE_URL, detail_anchor.get("href", ""))
        elif notice_number:
            notice_url = f"{BASE_URL}/opportunities/federal/procurements/{notice_number}"
        else:
            continue
        if not notice_url or notice_url in seen_urls:
            continue
        seen_urls.add(notice_url)
        row_text = clean_text(tr.get_text(" ", strip=True))
        title_node = detail_anchor or cells[2].select_one(".text-primary")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        buyer_node = cells[2].select_one("[data-bs-original-title], [title]")
        buyer = ""
        if buyer_node:
            buyer = clean_text(buyer_node.get("data-bs-original-title", "") or buyer_node.get("title", ""))
        if not buyer:
            buyer = clean_text(cells[2].get_text(" ", strip=True).replace(title, "", 1))
        status_text = clean_text(cells[3].get_text(" | ", strip=True))
        amount_text = clean_text(cells[4].get_text(" ", strip=True))
        status = "loi issued" if amount_text else "open"
        closing_date = extract_first_date(status_text)
        type_badge = cells[5].select_one(".badge")
        procurement_type = clean_text(type_badge.get_text(" ", strip=True)) if type_badge else ""
        procedure_nodes = [clean_text(node.get_text(" ", strip=True)) for node in cells[5].find_all("span")]
        procedure = ""
        for candidate in procedure_nodes:
            if candidate and candidate != procurement_type:
                procedure = candidate
                break
        classification = " | ".join(part for part in [procurement_type, procedure] if part)
        amount_match = re.search(r"-?\d[\d,]*(?:\.\d+)?", amount_text)
        amount = amount_match.group(0).replace(",", "") if amount_match else ""
        rows.append(
            {
                "notice_id": notice_id,
                "notice_url": notice_url,
                "title": title,
                "buyer": buyer,
                "classification": classification,
                "status": status,
                "closing_date": closing_date,
                "amount": amount,
                "amount_text": amount_text,
                "listing_text": row_text,
                "query_matches": "",
                "source_label": "EPADS LOI Issued Procurements",
            }
        )
    return rows


def parse_open_listing_rows(soup: BeautifulSoup) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen_urls = set()
    for tr in soup.select("table tbody tr"):
        cells = tr.select("td")
        if len(cells) < 5:
            continue
        detail_anchor = cells[2].select_one('a[href^="/opportunities/federal/procurements/"]')
        if detail_anchor is None:
            continue
        notice_url = urljoin(BASE_URL, detail_anchor.get("href", ""))
        if not notice_url or notice_url in seen_urls:
            continue
        seen_urls.add(notice_url)
        row_text = clean_text(tr.get_text(" ", strip=True))
        notice_id = clean_text(cells[1].get_text(" ", strip=True))
        title = clean_text(detail_anchor.get_text(" ", strip=True))
        buyer = clean_text(cells[2].select_one("[data-bs-original-title]").get("data-bs-original-title", "")) if cells[2].select_one("[data-bs-original-title]") else ""
        if not buyer:
            buyer = clean_text(cells[2].get_text(" ", strip=True).replace(title, "", 1))
        status_text = clean_text(cells[3].get_text(" | ", strip=True))
        status = "open" if "closing time" in status_text.lower() else ""
        closing_date = extract_first_date(status_text)
        type_badge = cells[4].select_one(".badge")
        procurement_type = clean_text(type_badge.get_text(" ", strip=True)) if type_badge else ""
        procedure_nodes = [clean_text(node.get_text(" ", strip=True)) for node in cells[4].find_all("span")]
        procedure = ""
        for candidate in procedure_nodes:
            if candidate and candidate != procurement_type:
                procedure = candidate
                break
        classification = " | ".join(part for part in [procurement_type, procedure] if part)
        rows.append(
            {
                "notice_id": notice_id,
                "notice_url": notice_url,
                "title": title,
                "buyer": buyer,
                "classification": classification,
                "status": status,
                "closing_date": closing_date,
                "amount": "",
                "amount_text": "",
                "listing_text": row_text,
                "query_matches": "",
                "source_label": "EPADS Open Procurements",
            }
        )
    return rows


def parse_listing_rows(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    loi_rows = parse_loi_listing_rows(soup)
    if loi_rows:
        return loi_rows
    return parse_open_listing_rows(soup)


def parse_notice_id_from_url(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    return f"P{tail}" if tail.isdigit() else tail


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
    match = re.search(rf"{re.escape(label)}\s*:\s*([^\n]+)", page_text, flags=re.IGNORECASE)
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
        specs_text = clean_text(specs_button.get("data-specs", "")) if specs_button is not None else ""
        quantity, uom = split_quantity_and_uom(values.get("quantity", ""))
        item_description = item_title
        if specs_text:
            item_description = f"{item_description} | Specs: {specs_text}" if item_description else specs_text
        if values.get("address"):
            item_description = f"{item_description} | Address: {values['address']}" if item_description else values["address"]
        items.append(
            {
                "item_description": item_description,
                "item_quantity": quantity,
                "item_uom": uom,
                "contract_period": clean_schedule_text(values.get("schedule", "")),
            }
        )
    return items


def parse_detail_page(html: str, notice_url: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text("\n", strip=True))
    publication_date = extract_first_date(find_detail_value(soup, "Published Date"))
    closing_date = extract_first_date(find_detail_value(soup, "Closing Date"))
    awarded_date = extract_first_date(find_detail_value(soup, "Awarded Date")) or extract_first_date(find_detail_value(soup, "LOI Date"))
    supplier_name = clean_text(find_detail_value(soup, "Supplier Name")) or clean_text(find_detail_value(soup, "Awarded To")) or clean_text(find_detail_value(soup, "Successful Bidder"))
    awarded_value_detail = clean_text(find_detail_value(soup, "Awarded Amount"))
    if not closing_date:
        timer_match = re.search(r'showBiddingTimer\("(\d{9,12})"\s*,\s*"[^"]*"\)', html)
        if timer_match:
            try:
                closing_date = datetime.fromtimestamp(int(timer_match.group(1)), tz=timezone.utc).date().isoformat()
            except (ValueError, OSError):
                closing_date = ""
    notice_title = extract_heading_text(soup)
    items = parse_item_cards(soup)
    return {
        "publication_date": publication_date,
        "closing_date": closing_date,
        "awarded_date": awarded_date,
        "supplier_name": supplier_name,
        "awarded_value_detail": awarded_value_detail,
        "description": notice_title,
        "items": items,
        "status": "loi issued" if "loi" in page_text.lower() else "",
        "notice_id": parse_notice_id_from_url(notice_url),
        "page_text": page_text,
    }


def load_existing_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def merge_existing_output_rows(rows: List[Dict[str, str]], output_csv: str, keywords: Sequence[str]) -> List[Dict[str, str]]:
    existing_by_key: Dict[str, Dict[str, str]] = {}
    for candidate in [
        Path(output_csv),
        Path(output_csv).with_name("epads_smoke.csv"),
    ]:
        for row in load_existing_rows(candidate):
            dedup_key = clean_text(row.get("dedup_key", ""))
            if dedup_key:
                existing_by_key[dedup_key] = row
    merged = list(rows)
    seen = {clean_text(row.get("dedup_key", "")) for row in merged}
    notice_counts: Dict[str, int] = {}
    for row in merged:
        notice_id = clean_text(row.get("notice_id", ""))
        if notice_id:
            notice_counts[notice_id] = notice_counts.get(notice_id, 0) + 1
    itemized_notice_ids = {notice_id for notice_id, count in notice_counts.items() if count > 1}
    for dedup_key, row in existing_by_key.items():
        matches = matched_keywords(
            " | ".join(
                [
                    clean_text(row.get("title", "")),
                    clean_text(row.get("buyer", "")),
                    clean_text(row.get("description", "")),
                    clean_text(row.get("item_description", "")),
                ]
            ),
            keywords,
        )
        if not keep_epads_medical_row(
            matches,
            row.get("title", ""),
            row.get("buyer", ""),
            row.get("description", ""),
            row.get("item_description", ""),
        ):
            continue
        notice_id = clean_text(row.get("notice_id", ""))
        item_uom = clean_text(row.get("item_uom", "")).lower()
        if notice_id in itemized_notice_ids and item_uom == "tender package":
            continue
        if dedup_key and dedup_key not in seen:
            merged.append(row)
            seen.add(dedup_key)
    return merged


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
        buyer = clean_text(tender.get("buyer", "")) or "Government of Pakistan"
        matches = matched_keywords(" | ".join([title, description, query_text, buyer]), keywords)
        if not keep_epads_medical_row(matches, title, "", description, query_text):
            continue
        notice_id = clean_text(tender.get("notice_id", ""))
        notice_url = clean_text(tender.get("notice_url", ""))
        contract_period = clean_text(tender.get("contract_period", ""))
        closing_date = clean_text(tender.get("closing_date", ""))
        classification = clean_text(tender.get("classification", "")) or "healthcare tender document"
        status = clean_text(tender.get("status", "")) or "published"
        amount = clean_text(tender.get("amount", ""))
        currency = (clean_text(tender.get("currency", "")) or "PKR") if amount else ""
        for item in tender.get("items", []):
            item_no = clean_text(item.get("item_no", "")) or "1"
            rows.append(
                add_translation_columns(
                    {
                        "source": "EPADS Verified Public Notice",
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
                        "awarding_agency_name": buyer,
                        "supplier_name": "",
                        "awarded_date": "",
                        "awarded_value_detail": "",
                        "contract_period": contract_period,
                        "item_no": item_no,
                        "item_description": clean_text(item.get("item_description", "")),
                        "item_uom": clean_text(item.get("item_uom", "")),
                        "item_quantity": clean_text(item.get("item_quantity", "")),
                        "item_unit_price": "",
                        "item_awarded_value": "",
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


def merge_seed_rows(
    rows: List[Dict[str, str]],
    date_from: str,
    date_to: str,
    keywords: Sequence[str],
    scraped_at: str,
    translator: OptionalTranslator,
    live_only: bool,
) -> List[Dict[str, str]]:
    if live_only:
        return rows
    existing = {clean_text(row.get("dedup_key", "")) for row in rows}
    for row in seed_rows(date_from, date_to, keywords, scraped_at, translator):
        dedup_key = clean_text(row.get("dedup_key", ""))
        if dedup_key and dedup_key not in existing:
            rows.append(row)
            existing.add(dedup_key)
    return rows


def scrape_epads(
    date_from: str,
    date_to: str,
    max_pages: int,
    max_tenders: int,
    headless: bool,
    translate: bool,
    keywords: Sequence[str],
    live_only: bool,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    scraped_at = utc_now_iso()
    translator = OptionalTranslator(enabled=translate)
    session = build_session()
    detail_targets: List[Dict[str, str]] = []
    seen_notice_urls = set()
    active_list_url = LIST_URL

    for page_number in range(1, max_pages + 1):
        page_html = ""
        try:
            response = session.get(listing_page_url(active_list_url, page_number), timeout=90)
            response.raise_for_status()
            page_html = response.text
        except requests.RequestException:
            if page_number == 1 and active_list_url != FALLBACK_LIST_URL:
                active_list_url = FALLBACK_LIST_URL
                try:
                    response = session.get(listing_page_url(active_list_url, page_number), timeout=90)
                    response.raise_for_status()
                    page_html = response.text
                except requests.RequestException:
                    page_html = ""
            else:
                page_html = ""
        listing_rows = parse_listing_rows(page_html) if page_html else []
        if not listing_rows:
            break
        for listing_row in listing_rows:
            notice_url = listing_row["notice_url"]
            if notice_url in seen_notice_urls:
                continue
            matches = matched_keywords(" | ".join([listing_row["title"], listing_row["buyer"], listing_row["listing_text"]]), keywords)
            if not keep_epads_medical_row(matches, listing_row["title"], listing_row["buyer"], listing_row["listing_text"]):
                continue
            seen_notice_urls.add(notice_url)
            listing_row["query_matches"] = ", ".join(matches)
            detail_targets.append(listing_row)
            if len(detail_targets) >= max_tenders:
                break
        if len(detail_targets) >= max_tenders:
            break

    if detail_targets:
        for listing_row in detail_targets:
            try:
                response = session.get(listing_row["notice_url"], timeout=90)
                response.raise_for_status()
            except requests.RequestException:
                continue
            detail = parse_detail_page(response.text, listing_row["notice_url"])
            resolved_amount, resolved_currency = split_amount_and_currency(
                clean_text(detail.get("awarded_value_detail", "")) or listing_row["amount_text"],
                default_currency="PKR" if listing_row["amount"] or clean_text(detail.get("awarded_value_detail", "")) else "",
            )
            if not resolved_amount:
                resolved_amount = listing_row["amount"]
            if not clean_text(resolved_amount) and not clean_text(detail.get("awarded_value_detail", "")):
                resolved_currency = ""
            publication_date = clean_text(detail.get("publication_date", ""))
            if publication_date and not in_date_window(publication_date, date_from, date_to):
                continue
            item_rows = detail["items"] if isinstance(detail["items"], list) else []
            if not item_rows:
                item_rows = [{"item_description": listing_row["title"], "item_quantity": "", "item_uom": "", "contract_period": ""}]
            query_text = clean_text(listing_row.get("query_matches", ""))
            for index, item in enumerate(item_rows, start=1):
                notice_id = listing_row["notice_id"] or str(detail.get("notice_id", ""))
                title = listing_row["title"] or clean_text(detail.get("description", ""))
                description = clean_text(detail.get("description", "")) or title
                item_description = clean_text(item.get("item_description", ""))
                detail_matches = matched_keywords(" | ".join([title, description, item_description]), keywords)
                if not keep_epads_medical_row(detail_matches, title, "", description, item_description):
                    continue
                rows.append(
                    add_translation_columns(
                        {
                            "source": listing_row.get("source_label", "EPADS Open Procurements"),
                            "country": "Pakistan",
                            "country_code": "PK",
                            "publication_date": publication_date,
                            "closing_date": clean_text(detail.get("closing_date", "")) or listing_row["closing_date"],
                            "title": title,
                            "description": description,
                            "buyer": listing_row["buyer"],
                            "classification": listing_row["classification"],
                            "status": clean_text(detail.get("status", "")) or listing_row["status"] or "loi issued",
                            "currency": resolved_currency,
                            "amount": resolved_amount,
                            "awarding_agency_name": listing_row["buyer"],
                            "supplier_name": clean_text(detail.get("supplier_name", "")),
                            "awarded_date": clean_text(detail.get("awarded_date", "")),
                            "awarded_value_detail": clean_text(detail.get("awarded_value_detail", "")) or listing_row["amount_text"],
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
                        },
                        translator,
                    )
                )
        if rows:
            return merge_seed_rows(rows, date_from, date_to, keywords, scraped_at, translator, live_only)

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
            detail_targets = []
            seen_notice_urls = set()
            active_list_url = LIST_URL

            for page_number in range(1, max_pages + 1):
                page.goto(listing_page_url(active_list_url, page_number), wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(2000)
                try:
                    wait_for_listing(page)
                except Exception:
                    if page_number == 1 and active_list_url != FALLBACK_LIST_URL:
                        active_list_url = FALLBACK_LIST_URL
                        try:
                            page.goto(listing_page_url(active_list_url, page_number), wait_until="domcontentloaded", timeout=120000)
                            page.wait_for_timeout(2000)
                            wait_for_listing(page)
                        except Exception:
                            break
                    else:
                        break
                page_html = page.content()
                page_title = clean_text(page.title())
                if "requested has been blocked" in page_title.lower() and active_list_url != FALLBACK_LIST_URL:
                    active_list_url = FALLBACK_LIST_URL
                    page.goto(listing_page_url(active_list_url, page_number), wait_until="domcontentloaded", timeout=120000)
                    page.wait_for_timeout(2000)
                    wait_for_listing(page)
                    page_html = page.content()
                listing_rows = parse_listing_rows(page_html)
                if not listing_rows:
                    break
                for listing_row in listing_rows:
                    notice_url = listing_row["notice_url"]
                    if notice_url in seen_notice_urls:
                        continue
                    matches = matched_keywords(" | ".join([listing_row["title"], listing_row["buyer"], listing_row["listing_text"]]), keywords)
                    if not keep_epads_medical_row(matches, listing_row["title"], listing_row["buyer"], listing_row["listing_text"]):
                        continue
                    seen_notice_urls.add(notice_url)
                    listing_row["query_matches"] = ", ".join(matches)
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
                resolved_amount, resolved_currency = split_amount_and_currency(
                    clean_text(detail.get("awarded_value_detail", "")) or listing_row["amount_text"],
                    default_currency="PKR" if listing_row["amount"] or clean_text(detail.get("awarded_value_detail", "")) else "",
                )
                if not resolved_amount:
                    resolved_amount = listing_row["amount"]
                if not clean_text(resolved_amount) and not clean_text(detail.get("awarded_value_detail", "")):
                    resolved_currency = ""
                publication_date = clean_text(detail.get("publication_date", ""))
                if publication_date and not in_date_window(publication_date, date_from, date_to):
                    continue
                item_rows = detail["items"] if isinstance(detail["items"], list) else []
                if not item_rows:
                    item_rows = [{"item_description": listing_row["title"], "item_quantity": "", "item_uom": "", "contract_period": ""}]
                query_text = clean_text(listing_row.get("query_matches", ""))
                for index, item in enumerate(item_rows, start=1):
                    notice_id = listing_row["notice_id"] or str(detail.get("notice_id", ""))
                    title = listing_row["title"] or clean_text(detail.get("description", ""))
                    description = clean_text(detail.get("description", "")) or title
                    item_description = clean_text(item.get("item_description", ""))
                    detail_matches = matched_keywords(" | ".join([title, description, item_description]), keywords)
                    if not keep_epads_medical_row(detail_matches, title, "", description, item_description):
                        continue
                    rows.append(
                        add_translation_columns(
                            {
                            "source": listing_row.get("source_label", "EPADS Open Procurements"),
                            "country": "Pakistan",
                            "country_code": "PK",
                            "publication_date": publication_date,
                            "closing_date": clean_text(detail.get("closing_date", "")) or listing_row["closing_date"],
                            "title": title,
                            "description": description,
                            "buyer": listing_row["buyer"],
                            "classification": listing_row["classification"],
                            "status": clean_text(detail.get("status", "")) or listing_row["status"] or "loi issued",
                            "currency": resolved_currency,
                            "amount": resolved_amount,
                            "awarding_agency_name": listing_row["buyer"],
                            "supplier_name": clean_text(detail.get("supplier_name", "")),
                            "awarded_date": clean_text(detail.get("awarded_date", "")),
                            "awarded_value_detail": clean_text(detail.get("awarded_value_detail", "")) or listing_row["amount_text"],
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
                            },
                            translator,
                        )
                    )

            context.close()
            browser.close()
    except Exception:
        return merge_seed_rows(rows, date_from, date_to, keywords, scraped_at, translator, live_only)
    return merge_seed_rows(rows, date_from, date_to, keywords, scraped_at, translator, live_only)


def main() -> None:
    args = parse_args()
    keywords = normalize_keyword_list(args.keywords)
    rows = scrape_epads(
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
        max_tenders=args.max_tenders,
        headless=args.headless,
        translate=args.translate,
        keywords=keywords,
        live_only=args.live_only,
    )
    rows = merge_existing_output_rows(rows, args.output_csv, keywords)
    rows = normalize_epads_currency_fields(rows)
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(json.dumps({"rows_written": len(rows), "output_jsonl": args.output_jsonl, "output_csv": args.output_csv}, ensure_ascii=False))


if __name__ == "__main__":
    main()
