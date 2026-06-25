#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Sequence
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
    split_amount_and_currency,
    stable_key,
    utc_now_iso,
)
from Pakistan.PPRA.ppra_verified_seeds import VERIFIED_SEED_ROWS  # noqa: E402

BASE_URL = "https://epms.ppra.gov.pk"
LIST_URL = f"{BASE_URL}/public/contracts"
EVALUATIONS_URL = f"{BASE_URL}/public/evaluations"
DEFAULT_START_DATE = "2024-01-01"
REQUEST_TIMEOUT = 180
DEFAULT_LIVE_TIMEOUT = int(os.getenv("PPRA_LIVE_TIMEOUT", "900"))
ATTACHMENT_EXTRACT_FILES = {
    "TS0000001234E": ROOT_DIR / "Pakistan" / "PPRA" / "ts0000001234e_annex_extract.md",
}

GENERIC_PPRA_KEYWORDS = {
    "consumable",
    "consumables",
    "consumable item",
    "consumable items",
    "miscellaneous consumable item",
    "miscellaneous consumable items",
    "equipment",
    "devices",
    "items",
    "kit",
    "kits",
    "goods",
    "supplies",
    "accessories",
}


def ppra_product_signal(*values: str) -> bool:
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
            "reagent",
            "reagents",
            "ivd",
            "test kit",
            "surgical",
            "medical equipment",
            "medical device",
            "hospital equipment",
            "first aid kit",
            "dental",
            "ophthalmic",
            "dialysis",
            "blood bag",
            "catheter",
            "cannula",
            "syringe",
            "glove",
            "mask",
        )
    )


def ppra_health_buyer_signal(*values: str) -> bool:
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


def ppra_healthcare_item_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    if not text:
        return False
    return any(
        token in text
        for token in (
            "medical/health insurance",
            "health insurance",
            "medical insurance",
            "medicine",
            "medicines",
            "drug",
            "drugs",
            "pharma",
            "pharmaceutical",
            "medical reagent",
            "lab reagent",
            "laboratory reagent",
            "reagents",
            "medical equipment",
            "electro medical",
            "electro-medical",
            "medical device",
            "surgical",
            "dental",
            "ophthalmic",
            "dialysis",
            "diagnostic",
            "clinical",
            "hospital equipment",
            "medical store",
            "medical stores",
            "disposable",
            "disposables",
            "implant",
            "implants",
            "lab kit",
            "lab kits",
            "medical gases",
            "injectable",
        )
    )


def ppra_scope_exclusion_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    return any(
        token in text
        for token in (
            "laying of ht/lt cables",
            "underground cables",
            "rubber insulating gloves",
            "leather protective gloves",
            "tree and shrubs",
            "transplantation of big trees",
            "office building",
            "bunglow",
            "water resources",
            "research in water resources",
            "underpasses under construction",
            "gate crossing",
        )
    )


def keep_ppra_medical_row(matched: Sequence[str], *context_values: str) -> bool:
    normalized_matches = {clean_text(value).lower() for value in matched if clean_text(value)}
    if not normalized_matches:
        return False
    if ppra_scope_exclusion_signal(*context_values):
        return False
    if ppra_healthcare_item_signal(*context_values):
        return True
    non_generic_matches = normalized_matches - GENERIC_PPRA_KEYWORDS
    if non_generic_matches and ppra_product_signal(*context_values):
        return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape public PPRA awarded contract pages for medical rows.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Publication upper bound in YYYY-MM-DD format.")
    parser.add_argument("--max-pages", type=int, default=100, help="Safety cap for paginated contract pages.")
    parser.add_argument(
        "--live-timeout",
        type=int,
        default=DEFAULT_LIVE_TIMEOUT,
        help="Timeout in seconds for live PPRA listing/detail requests before fallback rows take over.",
    )
    parser.add_argument("--translate", action="store_true", help="Attempt English translation columns when needed.")
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Disable the built-in verified PPRA medical notice fallback rows and only use live contract extraction.",
    )
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_MEDICAL_KEYWORDS),
        help="Comma-separated case-insensitive medical/healthcare keywords.",
    )
    parser.add_argument("--output-jsonl", default="Pakistan/PPRA/output/ppra_awarded_medical_2024_2026.jsonl")
    parser.add_argument("--output-csv", default="Pakistan/PPRA/output/ppra_awarded_medical_2024_2026.csv")
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


def build_evaluation_page_url(page_number: int) -> str:
    return EVALUATIONS_URL if page_number <= 1 else f"{EVALUATIONS_URL}?page={page_number}"


def ppra_clean(value: str) -> str:
    return clean_text(html_lib.unescape(clean_text(value)))


def extract_notice_id(text: str) -> str:
    match = re.search(r"(PCN-[A-Z0-9\-]+|PCN-\d+|EVL\d+)", text)
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


def parse_evaluation_rows(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    for tr in soup.select("table tbody tr"):
        cells = tr.select("td")
        if len(cells) < 6:
            continue
        evaluation_cell = ppra_clean(cells[1].get_text("\n", strip=True))
        details_cell = ppra_clean(cells[2].get_text("\n", strip=True))
        org_cell = ppra_clean(cells[3].get_text("\n", strip=True))
        advertise_date = parse_date_to_iso(ppra_clean(cells[4].get_text(" ", strip=True)))
        detail_url = ""
        report_url = ""
        for anchor in tr.select("a[href]"):
            href = urljoin(BASE_URL, ppra_clean(anchor.get("href", "")))
            if "/public/evaluations/evaluation-details/" in href:
                detail_url = href
            elif "/public/evaluations/invoice/" in href:
                report_url = href
        tender_match = re.search(r"\b(TS\d+E)\b", evaluation_cell)
        rows.append(
            {
                "evaluation_no": extract_notice_id(evaluation_cell),
                "tender_number": ppra_clean(tender_match.group(1)) if tender_match else "",
                "detail_url": detail_url,
                "report_url": report_url,
                "listing_text": details_cell,
                "advertise_date": advertise_date,
                "organization_card": org_cell,
            }
        )
    return rows


def extract_detail_value(page_text: str, label: str) -> str:
    patterns = [rf"{re.escape(label)}\s*:\s*([^\n]+)", rf"{re.escape(label)}\s+([^\n]+)"]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return ""


def extract_section_rows(soup: BeautifulSoup, section_title: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for card in soup.select(".detail-card"):
        heading = card.select_one(".section-title")
        if clean_text(heading.get_text(" ", strip=True)) != section_title if heading else True:
            continue
        for row in card.select(".detail-row"):
            label_node = row.select_one(".detail-label")
            value_node = row.select_one(".detail-value")
            if label_node is None or value_node is None:
                continue
            label = ppra_clean(label_node.get_text(" ", strip=True)).rstrip(":")
            value = ppra_clean(value_node.get_text(" ", strip=True))
            if label:
                result[label] = value
        for row in card.select(".list-group-item"):
            label_node = row.select_one(".detail-label")
            if label_node is None:
                continue
            value_node = row.select_one(".flex-grow-1")
            if value_node is None:
                continue
            label = ppra_clean(label_node.get_text(" ", strip=True)).rstrip(":")
            value = ppra_clean(value_node.get_text(" ", strip=True))
            if label:
                result[label] = value
        break
    return result


def parse_remark_items(remarks: str, fallback_title: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    pattern = re.compile(r"^\s*(\d+)\s*[-.)]\s*(.*?)\s+Rs\.\s*([0-9,]+(?:\.\d+)?)\s*(?:/[-])?\s*$", flags=re.IGNORECASE)
    for raw_line in remarks.splitlines():
        line = clean_text(raw_line)
        if not line:
            continue
        match = pattern.match(line)
        if not match:
            continue
        item_no = clean_text(match.group(1))
        item_description = clean_text(match.group(2)) or fallback_title
        amount_text = f"Rs. {clean_text(match.group(3))}"
        item_amount, _ = split_amount_and_currency(amount_text, default_currency="PKR")
        items.append(
            {
                "item_no": item_no,
                "item_description": item_description,
                "item_awarded_value": item_amount,
            }
        )
    return items


def parse_contract_detail(html: str, detail_url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text("\n", strip=True))
    org_rows = extract_section_rows(soup, "Procuring Organization")
    contract_rows = extract_section_rows(soup, "Contract Information")
    financial_rows = extract_section_rows(soup, "Financial Information")
    bidder_rows = extract_section_rows(soup, "Successful Bidder")
    related_rows = extract_section_rows(soup, "Related Tender")
    publication_rows = extract_section_rows(soup, "Publication Information")
    title = contract_rows.get("Contract Title", "") or extract_detail_value(page_text, "Contract Title")
    buyer_org = org_rows.get("Organization Name", "")
    buyer_office = org_rows.get("Office Name", "")
    city = org_rows.get("City/Location", "")
    nature_of_purchase = contract_rows.get("Nature of Purchase", "")
    contract_signing_date = parse_date_to_iso(contract_rows.get("Contract Signing Date", ""))
    awarded_amount_text = financial_rows.get("Contract Price (Awarded Amount)", "")
    tender_value_text = financial_rows.get("Tender Value", "")
    successful_bidder = bidder_rows.get("Bidder Name", "")
    tender_number = related_rows.get("Tender Number", "")
    tender_title = related_rows.get("Tender Title", "")
    published_on = parse_date_to_iso(publication_rows.get("Published Date", "") or publication_rows.get("Published On", ""))
    description = contract_rows.get("Description", "") or tender_title or title
    remarks_node = None
    for card in soup.select(".detail-card"):
        heading = card.select_one(".section-title")
        if heading and clean_text(heading.get_text(" ", strip=True)) == "Remarks":
            remarks_node = card
            break
    remarks = clean_text(remarks_node.get_text("\n", strip=True).replace("Remarks", "", 1)) if remarks_node else ""
    return {
        "title": title or tender_title,
        "description": description,
        "buyer_org": buyer_org,
        "buyer_office": buyer_office,
        "city": city,
        "classification": nature_of_purchase,
        "awarded_date": contract_signing_date,
        "awarded_amount_text": awarded_amount_text or tender_value_text,
        "supplier_name": successful_bidder,
        "tender_number": tender_number,
        "publication_date": published_on,
        "detail_url": detail_url,
        "page_text": page_text,
        "remarks": remarks,
    }


def first_detail_value(rows: Dict[str, str], *labels: str) -> str:
    for label in labels:
        value = ppra_clean(rows.get(label, ""))
        if value:
            return value
    return ""


def parse_evaluation_detail(html: str, detail_url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = ppra_clean(soup.get_text("\n", strip=True))
    org_rows = extract_section_rows(soup, "Organization/Office Details")
    evaluation_rows = extract_section_rows(soup, "Evaluation Information")
    date_rows = extract_section_rows(soup, "Important Dates")
    related_rows = extract_section_rows(soup, "Related Tender")
    title = first_detail_value(evaluation_rows, "Tender Title") or first_detail_value(related_rows, "Tender Title")
    amount_text = first_detail_value(
        evaluation_rows,
        "Lowest Evaluated Bid",
        "Lowest Evaluated Cost",
        "Evaluated Amount",
        "Evaluated Price",
        "Bid Amount",
        "Quoted Price",
        "Contract Price",
    )
    if not amount_text:
        amount_text = extract_detail_value(page_text, "Lowest Evaluated Bid") or extract_detail_value(page_text, "Bid Amount")
    return {
        "title": title,
        "description": title,
        "buyer_org": first_detail_value(org_rows, "Organization Name"),
        "buyer_office": first_detail_value(org_rows, "Office Name"),
        "city": first_detail_value(org_rows, "City", "City/Location"),
        "classification": first_detail_value(evaluation_rows, "Evaluation Type") or "evaluation result",
        "awarded_date": parse_date_to_iso(first_detail_value(date_rows, "Evaluation Published Date")),
        "awarded_amount_text": amount_text,
        "supplier_name": first_detail_value(evaluation_rows, "Lowest Bidder", "Successful Bidder", "Winning Bidder"),
        "tender_number": first_detail_value(related_rows, "Tender Number") or extract_detail_value(page_text, "Tender No"),
        "publication_date": parse_date_to_iso(first_detail_value(date_rows, "Evaluation Published Date")),
        "closing_date": parse_date_to_iso(first_detail_value(date_rows, "Tender Closing Date")),
        "advertisement_date": parse_date_to_iso(first_detail_value(date_rows, "Tender Advertisement Date")),
        "detail_url": detail_url,
        "page_text": page_text,
        "remarks": "",
    }


def load_attachment_extract_items(notice_id: str) -> List[Dict[str, str]]:
    extract_path = ATTACHMENT_EXTRACT_FILES.get(clean_text(notice_id))
    if extract_path is None or not extract_path.exists():
        return []
    text = extract_path.read_text(encoding="utf-8")
    items: List[Dict[str, str]] = []
    seen = set()
    line_pattern = re.compile(r"^-\s+`(\d+)`\s+`([^`]+)`\s+`([^`]+)`\s+`([0-9,]+)`\s*$")
    for raw_line in text.splitlines():
        match = line_pattern.match(raw_line.strip())
        if not match:
            continue
        item_no = clean_text(match.group(1))
        item_description = clean_text(match.group(2))
        item_category = clean_text(match.group(3))
        item_quantity = clean_text(match.group(4)).replace(",", "")
        dedup_key = stable_key(item_no, item_description, item_category, item_quantity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        full_description = item_description
        if item_category:
            full_description = f"{item_description} ({item_category})"
        items.append(
            {
                "item_no": item_no,
                "item_description": full_description,
                "item_quantity": item_quantity,
                "item_uom": "tests",
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
    for row in VERIFIED_SEED_ROWS:
        publication_date = clean_text(row.get("publication_date", ""))
        if not in_date_window(publication_date, date_from, date_to):
            continue
        title = clean_text(row.get("title", ""))
        description = clean_text(row.get("description", ""))
        buyer = clean_text(row.get("buyer", ""))
        query_text = clean_text(row.get("query_text", ""))
        matched = matched_keywords(" | ".join([title, description, buyer, query_text]), keywords)
        if not matched or not keep_ppra_medical_row(matched, title, description, buyer, query_text):
            continue
        items = row.get("items", [])
        if not isinstance(items, list) or not items:
            items = load_attachment_extract_items(clean_text(row.get("notice_id", "")))
        if not isinstance(items, list) or not items:
            items = [
                {
                    "item_no": clean_text(row.get("item_no", "")) or "1",
                    "item_description": clean_text(row.get("item_description", "")) or title,
                    "item_uom": clean_text(row.get("item_uom", "")),
                    "item_quantity": clean_text(row.get("item_quantity", "")),
                }
            ]
        for item in items:
            seeded = dict(row)
            seeded["item_no"] = clean_text(item.get("item_no", "")) or clean_text(seeded.get("item_no", "")) or "1"
            seeded["item_description"] = clean_text(item.get("item_description", "")) or clean_text(seeded.get("item_description", "")) or title
            seeded["item_uom"] = clean_text(item.get("item_uom", "")) or clean_text(seeded.get("item_uom", ""))
            seeded["item_quantity"] = clean_text(item.get("item_quantity", "")) or clean_text(seeded.get("item_quantity", ""))
            if not clean_text(seeded.get("amount", "")) and not clean_text(seeded.get("awarded_value_detail", "")):
                seeded["currency"] = ""
            seeded = add_translation_columns(seeded, translator)
            seeded["query_text"] = ", ".join(matched)
            seeded["scraped_at_utc"] = scraped_at
            seeded["dedup_key"] = stable_key(
                seeded.get("notice_id", ""),
                seeded.get("notice_url", ""),
                seeded.get("item_no", ""),
                seeded.get("item_description", ""),
            )
            rows.append(seeded)
    return rows


def scrape_ppra(
    date_from: str,
    date_to: str,
    max_pages: int,
    translate: bool,
    keywords: Sequence[str],
    live_only: bool,
    live_timeout: int,
) -> List[Dict[str, str]]:
    translator = OptionalTranslator(enabled=translate)
    session = build_session()
    seen_contracts = set()
    scraped_at = utc_now_iso()
    output_rows: List[Dict[str, str]] = []

    try:
        for page_number in range(1, max_pages + 1):
            response = session.get(build_page_url(page_number), timeout=live_timeout)
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
                detail_response = session.get(detail_url, timeout=live_timeout)
                detail_response.raise_for_status()
                detail = parse_contract_detail(detail_response.text, detail_url)
                publication_date = detail["publication_date"] or listing_row["advertise_date"]
                if not in_date_window(publication_date, date_from, date_to):
                    continue
                searchable_text = " | ".join(
                    [
                        detail["title"],
                        detail["description"],
                        detail["classification"],
                        listing_row["listing_text"],
                        detail["buyer_org"],
                        detail["buyer_office"],
                        detail["page_text"],
                    ]
                )
                matched = matched_keywords(searchable_text, keywords)
                if not matched:
                    continue
                product_text = " | ".join(
                    [
                        detail["title"],
                        detail["description"],
                        detail["classification"],
                        listing_row["listing_text"],
                        detail.get("remarks", ""),
                    ]
                )
                if not keep_ppra_medical_row(
                    matched,
                    product_text,
                    detail["buyer_org"],
                    detail["buyer_office"],
                    detail["city"],
                ):
                    continue
                if not ppra_product_signal(product_text):
                    continue
                rows_kept += 1
                buyer = " | ".join(
                    part for part in [detail["buyer_org"], detail["buyer_office"], detail["city"]] if clean_text(part)
                )
                description = detail["description"] or listing_row["listing_text"]
                amount, currency = split_amount_and_currency(detail["awarded_amount_text"], default_currency="PKR")
                if not clean_text(amount) and not clean_text(detail["awarded_amount_text"]):
                    currency = ""
                notice_id = contract_no or detail["tender_number"]
                item_rows = parse_remark_items(detail.get("remarks", ""), detail["title"] or description)
                if not item_rows:
                    item_rows = [
                        {
                            "item_no": "1",
                            "item_description": detail["title"] or description,
                            "item_awarded_value": amount,
                        }
                    ]
                for item in item_rows:
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
                        "item_no": item["item_no"],
                        "item_description": item["item_description"],
                        "item_uom": "",
                        "item_quantity": "",
                        "item_unit_price": "",
                        "item_awarded_value": item["item_awarded_value"] or amount,
                        "notice_id": notice_id,
                        "notice_url": detail_url,
                        "query_text": ", ".join(matched),
                        "scraped_at_utc": scraped_at,
                        "dedup_key": stable_key(notice_id, detail_url, item["item_no"], item["item_description"]),
                    }
                    output_rows.append(add_translation_columns(base_row, translator))
            if rows_kept == 0 and listing_rows[-1]["advertise_date"] and listing_rows[-1]["advertise_date"] < date_from:
                break
        for page_number in range(1, max_pages + 1):
            response = session.get(build_evaluation_page_url(page_number), timeout=live_timeout)
            response.raise_for_status()
            listing_rows = parse_evaluation_rows(response.text)
            if not listing_rows:
                break
            rows_kept = 0
            for listing_row in listing_rows:
                evaluation_no = listing_row["evaluation_no"]
                detail_url = listing_row["detail_url"]
                if not evaluation_no or not detail_url or evaluation_no in seen_contracts:
                    continue
                seen_contracts.add(evaluation_no)
                detail_response = session.get(detail_url, timeout=live_timeout)
                detail_response.raise_for_status()
                detail = parse_evaluation_detail(detail_response.text, detail_url)
                if "final" not in clean_text(detail["classification"]).lower() or not clean_text(detail["supplier_name"]):
                    continue
                publication_date = detail["publication_date"] or listing_row["advertise_date"]
                if not in_date_window(publication_date, date_from, date_to):
                    continue
                searchable_text = " | ".join(
                    [
                        detail["title"],
                        detail["description"],
                        detail["classification"],
                        listing_row["listing_text"],
                        detail["buyer_org"],
                        detail["buyer_office"],
                        detail["page_text"],
                    ]
                )
                matched = matched_keywords(searchable_text, keywords)
                if not matched:
                    continue
                product_text = " | ".join(
                    [
                        detail["title"],
                        detail["description"],
                        detail["classification"],
                        listing_row["listing_text"],
                    ]
                )
                if not keep_ppra_medical_row(
                    matched,
                    product_text,
                    detail["buyer_org"],
                    detail["buyer_office"],
                    detail["city"],
                ):
                    continue
                if not ppra_product_signal(product_text):
                    continue
                rows_kept += 1
                buyer = " | ".join(
                    part for part in [detail["buyer_org"], detail["buyer_office"], detail["city"]] if clean_text(part)
                )
                amount, currency = split_amount_and_currency(detail["awarded_amount_text"], default_currency="PKR")
                if not clean_text(amount) and not clean_text(detail["awarded_amount_text"]):
                    currency = ""
                notice_id = evaluation_no or detail["tender_number"]
                base_row = {
                    "source": "PPRA Evaluation Results",
                    "country": "Pakistan",
                    "country_code": "PK",
                    "publication_date": publication_date,
                    "closing_date": detail["closing_date"],
                    "title": detail["title"],
                    "description": detail["description"],
                    "buyer": buyer,
                    "classification": detail["classification"],
                    "status": "awarded",
                    "currency": currency,
                    "amount": amount,
                    "awarding_agency_name": detail["buyer_org"] or detail["buyer_office"],
                    "supplier_name": detail["supplier_name"],
                    "awarded_date": detail["awarded_date"],
                    "awarded_value_detail": detail["awarded_amount_text"],
                    "contract_period": "",
                    "item_no": "1",
                    "item_description": detail["title"] or detail["description"],
                    "item_uom": "",
                    "item_quantity": "",
                    "item_unit_price": "",
                    "item_awarded_value": amount,
                    "notice_id": notice_id,
                    "notice_url": detail_url,
                    "query_text": ", ".join(matched),
                    "scraped_at_utc": scraped_at,
                    "dedup_key": stable_key(notice_id, detail_url, "1", detail["title"]),
                }
                output_rows.append(add_translation_columns(base_row, translator))
            if rows_kept == 0 and listing_rows[-1]["advertise_date"] and listing_rows[-1]["advertise_date"] < date_from:
                break
    except requests.RequestException as exc:
        print(f"PPRA live scrape request failed: {exc}", file=sys.stderr)
    if not live_only:
        existing = {clean_text(row.get("dedup_key", "")) for row in output_rows}
        for row in seed_rows(date_from, date_to, keywords, scraped_at, translator):
            dedup_key = clean_text(row.get("dedup_key", ""))
            if dedup_key and dedup_key not in existing:
                output_rows.append(row)
                existing.add(dedup_key)
    return output_rows


def normalize_currency_fields(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized_rows: List[Dict[str, str]] = []
    for row in rows:
        normalized = dict(row)
        if not clean_text(normalized.get("amount", "")) and not clean_text(normalized.get("awarded_value_detail", "")):
            normalized["currency"] = ""
        normalized_rows.append(normalized)
    return normalized_rows


def main() -> None:
    args = parse_args()
    rows = scrape_ppra(
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
        translate=args.translate,
        keywords=normalize_keyword_list(args.keywords),
        live_only=args.live_only,
        live_timeout=max(30, int(args.live_timeout)),
    )
    rows = normalize_currency_fields(rows)
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    print(
        json.dumps(
            {
                "rows_written": len(rows),
                "output_jsonl": args.output_jsonl,
                "output_csv": args.output_csv,
                "date_from": args.date_from,
                "date_to": args.date_to,
                "live_timeout": max(30, int(args.live_timeout)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
