#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

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

BASE_URL = "https://esupply.dubai.gov.ae"
HOME_URL = f"{BASE_URL}/esupply/web/index.html"
CURRENT_LIST_URL = f"{BASE_URL}/esop/toolkit/opportunity/current/list.si?reset=true&resetstored=true"
PAST_LIST_URL = f"{BASE_URL}/esop/toolkit/opportunity/past/list.si?reset=true&resetstored=true"
CURRENT_CAPTURE_PATH = ROOT_DIR / "UAE" / "Dubai_eSupply" / "output" / "current_opportunities_body.html"
PAST_CAPTURE_PATH = ROOT_DIR / "UAE" / "Dubai_eSupply" / "output" / "past_opportunities_body.html"
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_TIMEOUT = 90
CURRENT_CAPTURE_PATTERNS = (
    "uae_current_page*.html",
    "uae_current_*list*.html",
    "dubai_current_*list*.html",
    "uae_live_current_snapshot.md",
    "uae_current_*eval.json",
    "uae_live_eval.json",
    "uae_tab1*_snapshot.md",
)
PAST_CAPTURE_PATTERNS = (
    "uae_past_page*.html",
    "uae_past_*list*.html",
    "dubai_past_*list*.html",
    "uae_filtered_past*.html",
    "uae_*tab*_eval.json",
    "uae_live_eval.json",
    "uae_current_tab_eval.json",
    "uae_page*_postdialog_snapshot.md",
    "uae_past_live_page*_snapshot.md",
    "uae_tab4*_snapshot.md",
)
DETAIL_CAPTURE_PATTERNS = (
    "uae_detail_*.html",
)
DUBAI_GENERIC_MATCHES = {"health", "rehabilitation"}
DUBAI_STRONG_PRODUCT_TERMS = (
    "medical",
    "طبية",
    "med.equip",
    "med.eqpt",
    "med equip",
    "medicine",
    "medication",
    "drug",
    "pharma",
    "pharmaceutical",
    "hospital",
    "clinic",
    "clinical",
    "consumable",
    "comsumable",
    "test kit",
    "influenza",
    "cvc",
    "ctg",
    "stainer",
    "cardiology",
    "neonatology",
    "disposable",
    "lab",
    "laboratory",
    "diagnostic",
    "dental",
    "implant",
    "surgical",
    "cath lab",
    "iv",
    "reagent",
    "triglyceride",
    "triglycerides",
    "equipment",
    "device",
)
DUBAI_EXPLICIT_MEDICAL_TITLE_TERMS = (
    "مراتب طبية",
    "calcium&triglycerides",
    "triglycerides",
    "facio maxillary",
)
STATUS_PRIORITY = {
    "awarded": 5,
    "completed": 4,
    "closed": 3,
    "published": 2,
    "open": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape public Dubai eSupply opportunity pages for medical rows when the site exposes them."
    )
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Publication lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Publication upper bound in YYYY-MM-DD format.")
    parser.add_argument("--max-pages", type=int, default=25, help="Safety cap if a public paginated listing is exposed.")
    parser.add_argument("--translate", action="store_true", help="Attempt English translation columns when needed.")
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_MEDICAL_KEYWORDS),
        help="Comma-separated case-insensitive medical/healthcare keywords.",
    )
    parser.add_argument("--output-jsonl", default="UAE/Dubai_eSupply/output/dubai_esupply_medical_2024_2026.jsonl")
    parser.add_argument("--output-csv", default="UAE/Dubai_eSupply/output/dubai_esupply_medical_2024_2026.csv")
    parser.add_argument(
        "--output-metadata-json",
        default="UAE/Dubai_eSupply/output/dubai_esupply_medical_2024_2026_metadata.json",
    )
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


def fetch_html(session: requests.Session, url: str) -> tuple[int, str]:
    response = session.get(url, timeout=DEFAULT_TIMEOUT)
    return response.status_code, response.text


def load_saved_html(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_saved_html_pages(path: Path) -> List[tuple[str, str]]:
    pages: List[tuple[str, str]] = []
    seen_paths = set()
    for candidate in [path, *sorted(path.parent.glob(f"{path.stem}*.html"))]:
        resolved = candidate.resolve()
        if resolved in seen_paths or not candidate.exists():
            continue
        seen_paths.add(resolved)
        html = candidate.read_text(encoding="utf-8", errors="replace")
        if html.strip():
            pages.append((candidate.name, html))
    return pages


def extend_saved_pages(pages: List[tuple[str, str]], extra_paths: Sequence[Path]) -> List[tuple[str, str]]:
    seen_names = {name for name, _ in pages}
    seen_contents = {html for _, html in pages}
    combined = list(pages)
    for candidate in extra_paths:
        if not candidate.exists():
            continue
        html = candidate.read_text(encoding="utf-8", errors="replace")
        if not html.strip():
            continue
        if candidate.name in seen_names or html in seen_contents:
            continue
        combined.append((candidate.name, html))
        seen_names.add(candidate.name)
        seen_contents.add(html)
    return combined


def discover_root_capture_paths(prefix: str) -> List[Path]:
    return sorted(ROOT_DIR.glob(f"{prefix}*.html"))


def discover_capture_paths(patterns: Sequence[str]) -> List[Path]:
    seen = set()
    captures: List[Path] = []
    for pattern in patterns:
        for candidate in sorted(ROOT_DIR.glob(pattern)):
            resolved = candidate.resolve()
            if resolved in seen or not candidate.exists():
                continue
            seen.add(resolved)
            captures.append(candidate)
    return captures


def parse_homepage(html: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    body_text = clean_text(soup.get_text("\n", strip=True))
    counts: Dict[str, int] = {}
    for label in (
        "Active Suppliers",
        "Current Opportunities",
        "Running RFIs",
        "Running RFQs",
        "Active Contracts",
    ):
        match = re.search(rf"{re.escape(label)}\s+(\d+)", body_text, flags=re.IGNORECASE)
        counts[label] = int(match.group(1)) if match else 0

    opportunities_url = ""
    for anchor in soup.select("a[href]"):
        anchor_text = clean_text(anchor.get_text(" ", strip=True)).lower()
        href = clean_text(anchor.get("href", ""))
        if "search now" in anchor_text or "current opportunities" in anchor_text:
            opportunities_url = urljoin(HOME_URL, href)
            break

    return {
        "counts": counts,
        "opportunities_url": opportunities_url,
        "public_entities_present": "Dubai Health Authority" in body_text or "Dubai Corporation for Ambulance Services" in body_text,
    }


def is_same_page_opportunities_link(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == urlparse(HOME_URL).netloc
        and parsed.path == urlparse(HOME_URL).path
        and parsed.fragment.lower() == "opportunities"
    )


def parse_candidate_rows(html: str, page_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []

    for row in soup.select("table tbody tr"):
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.select("td")]
        if len(cells) < 2:
            continue
        row_text = " | ".join(cells)
        links = [urljoin(page_url, clean_text(anchor.get("href", ""))) for anchor in row.select("a[href]")]
        notice_url = links[0] if links else page_url
        rows.append(
            {
                "title": cells[0],
                "description": row_text,
                "buyer": "",
                "classification": "public opportunity",
                "status": "open",
                "publication_date": "",
                "closing_date": "",
                "notice_id": stable_key(page_url, row_text),
                "notice_url": notice_url,
            }
        )

    for card in soup.select(".opportunity, .opportunity-card, .listing-item, .result-item"):
        text = clean_text(card.get_text("\n", strip=True))
        if not text:
            continue
        notice_url = page_url
        anchor = card.select_one("a[href]")
        if anchor is not None:
            notice_url = urljoin(page_url, clean_text(anchor.get("href", "")))
        rows.append(
            {
                "title": clean_text(card.select_one("h1, h2, h3, h4").get_text(" ", strip=True)) if card.select_one("h1, h2, h3, h4") else text,
                "description": text,
                "buyer": "",
                "classification": "public opportunity",
                "status": "open",
                "publication_date": "",
                "closing_date": "",
                "notice_id": stable_key(page_url, text),
                "notice_url": notice_url,
            }
        )
    return rows


def extract_first_date(text: str) -> str:
    match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
    if not match:
        return ""
    return parse_date_to_iso(match.group(0)) or ""


def extract_listing_total(html: str) -> int:
    text = clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    match = re.search(r"Showing Result\s*\d+\s*-\s*\d+\s*of\s*(\d+)", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def parse_esupply_listing_rows(html: str, page_url: str, status: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    detail_base = "/esop/toolkit/opportunity/current/{}/detail.si"
    if "opportunity/past/" in page_url:
        detail_base = "/esop/toolkit/opportunity/past/{}/detail.si"
    for tr in soup.select("table.list-table tbody tr"):
        cells = tr.select("td")
        if len(cells) < 6:
            continue
        currency = clean_text(cells[0].get_text(" ", strip=True))
        buyer = clean_text(cells[1].get_text(" ", strip=True))
        title_cell = cells[2]
        publication_date = extract_first_date(cells[3].get_text(" ", strip=True))
        classification = clean_text(cells[4].get_text(" ", strip=True))
        closing_date = extract_first_date(cells[5].get_text(" ", strip=True))
        detail_link = title_cell.select_one("a.detailLink")
        title = ""
        notice_id = ""
        notice_url = page_url
        if detail_link is not None:
            title = clean_text(detail_link.get("title", "")).removeprefix("View Details:").strip()
            onclick = clean_text(detail_link.get("onclick", ""))
            match = re.search(r"goToDetail\('(\d+)'", onclick)
            if match:
                notice_id = match.group(1)
                notice_url = urljoin(BASE_URL, detail_base.format(notice_id))
        title = title or clean_text(title_cell.get_text(" ", strip=True))
        description = " | ".join(part for part in [title, buyer, classification] if part)
        rows.append(
            {
                "title": title,
                "description": description,
                "buyer": buyer,
                "classification": classification or "public opportunity",
                "status": status,
                "publication_date": publication_date,
                "closing_date": closing_date,
                "notice_id": notice_id or stable_key(page_url, title, buyer, publication_date, closing_date),
                "notice_url": notice_url,
                "currency": currency,
                "amount_text": "",
            }
        )
    return rows


def parse_esupply_snapshot_rows(snapshot_text: str, page_url: str, status: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    row_start_pattern = re.compile(r'^[ \t]*- row ".*?" \[ref=[^\]]+\]:', flags=re.MULTILINE)
    cell_pattern = re.compile(r'^[ \t]*- cell "(?P<value>[^"]*)"', flags=re.MULTILINE)
    matches = list(row_start_pattern.finditer(snapshot_text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(snapshot_text)
        body = snapshot_text[start:end]
        cells = [clean_text(cell_match.group("value")) for cell_match in cell_pattern.finditer(body)]
        if len(cells) < 6:
            continue
        currency, buyer, title, publication_raw, classification, closing_raw = cells[:6]
        publication_date = parse_date_to_iso(publication_raw.split()[0]) or parse_date_to_iso(publication_raw) or ""
        closing_date = parse_date_to_iso(closing_raw.split()[0]) or parse_date_to_iso(closing_raw) or ""
        rows.append(
            {
                "title": title,
                "description": " | ".join(part for part in [title, buyer, classification] if part),
                "buyer": buyer,
                "classification": classification or "public opportunity",
                "status": status,
                "publication_date": publication_date,
                "closing_date": closing_date,
                "notice_id": stable_key(title, buyer, publication_date, closing_date),
                "notice_url": page_url,
                "currency": currency or "AED",
                "amount_text": "",
            }
        )
    return rows


def parse_esupply_eval_rows(json_text: str, page_url: str, status: str) -> List[Dict[str, str]]:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return []
    sample_rows = payload.get("sampleRows")
    if not isinstance(sample_rows, list):
        return []

    rows: List[Dict[str, str]] = []
    for item in sample_rows:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title", ""))
        buyer = clean_text(item.get("buyer", ""))
        publication_raw = clean_text(item.get("publication", ""))
        closing_raw = clean_text(item.get("closing", ""))
        publication_date = parse_date_to_iso(publication_raw.split()[0]) or parse_date_to_iso(publication_raw) or ""
        closing_date = parse_date_to_iso(closing_raw.split()[0]) or parse_date_to_iso(closing_raw) or ""
        classification = clean_text(item.get("category", "")) or "public opportunity"
        currency = clean_text(item.get("currency", ""))
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "description": " | ".join(part for part in [title, buyer, classification] if part),
                "buyer": buyer,
                "classification": classification,
                "status": status,
                "publication_date": publication_date,
                "closing_date": closing_date,
                "notice_id": stable_key(title, buyer, publication_date, closing_date),
                "notice_url": page_url,
                "currency": currency,
                "amount_text": "",
            }
        )
    return rows


def parse_saved_listing_rows(page_text: str, page_url: str, status: str) -> List[Dict[str, str]]:
    stripped = page_text.lstrip()
    if stripped.startswith("{") and '"sampleRows"' in stripped:
        return parse_esupply_eval_rows(page_text, page_url, status)
    if '- row "' in page_text and "<table" not in page_text.lower():
        return parse_esupply_snapshot_rows(page_text, page_url, status)
    return parse_esupply_listing_rows(page_text, page_url, status)


def dubai_product_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    return any(token in text for token in DUBAI_STRONG_PRODUCT_TERMS)


def dubai_explicit_medical_title_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    return any(token in text for token in DUBAI_EXPLICIT_MEDICAL_TITLE_TERMS)


def dubai_health_buyer_signal(*values: str) -> bool:
    text = " | ".join(clean_text(value).lower() for value in values if clean_text(value))
    return any(
        token in text
        for token in (
            "health authority",
            "health corporation",
            "hospital",
            "clinic",
            "medical",
            "ambulance",
        )
    )


def keep_dubai_medical_row(matched: Sequence[str], title: str, description: str, buyer: str) -> bool:
    normalized_matches = {clean_text(value).lower() for value in matched if clean_text(value)}
    if not normalized_matches:
        return False
    product_text = " | ".join(part for part in [title, description] if clean_text(part))
    if dubai_explicit_medical_title_signal(product_text):
        return True
    if dubai_product_signal(product_text):
        return True
    non_generic = normalized_matches - DUBAI_GENERIC_MATCHES
    return bool(non_generic) and dubai_health_buyer_signal(buyer)


def parse_dates_from_text(text: str) -> tuple[str, str]:
    publication_date = ""
    closing_date = ""
    iso_candidates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    slash_candidates = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", text)
    text_candidates = re.findall(r"[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}", text)
    for candidate in [*iso_candidates, *slash_candidates, *text_candidates]:
        parsed = parse_date_to_iso(candidate)
        if not parsed:
            continue
        if not publication_date:
            publication_date = parsed
        elif not closing_date and parsed != publication_date:
            closing_date = parsed
    return publication_date, closing_date


def is_expired_session_text(text: str) -> bool:
    normalized = clean_text(text).lower()
    return "your session is invalid or expired" in normalized or "please log in to access the functionality on this page" in normalized


def find_detail_label_value(text: str, labels: Sequence[str]) -> str:
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*:?\s*(.+?)(?=(?:\s+[A-Z][A-Za-z ]{{2,30}}\s*:)|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            value = clean_text(match.group(1))
            if value:
                return value
    return ""


def parse_saved_detail_page(path: Path) -> Dict[str, str]:
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text("\n", strip=True))
    if not page_text or is_expired_session_text(page_text):
        return {"notice_id": re.search(r"(\d+)", path.stem).group(1) if re.search(r"(\d+)", path.stem) else "", "expired": "true"}

    publication_detail = find_detail_label_value(page_text, ("Published Date", "Publication Date", "Published on"))
    closing_detail = find_detail_label_value(page_text, ("Closing Date", "Closing Time", "Bid Closing Date"))
    status_detail = find_detail_label_value(page_text, ("Status", "Opportunity Status", "Procurement Status"))
    buyer_detail = find_detail_label_value(page_text, ("Buyer", "Purchasing Organization", "Procuring Entity", "Agency"))
    amount_detail = find_detail_label_value(page_text, ("Awarded Amount", "Contract Amount", "Amount", "Estimated Cost", "Budget"))
    supplier_detail = find_detail_label_value(page_text, ("Awarded To", "Supplier", "Vendor", "Successful Bidder"))
    title = clean_text(soup.find(["h1", "h2", "h3"]).get_text(" ", strip=True)) if soup.find(["h1", "h2", "h3"]) else ""

    publication_date = parse_date_to_iso(publication_detail) or extract_first_date(publication_detail)
    closing_date = parse_date_to_iso(closing_detail) or extract_first_date(closing_detail)
    notice_match = re.search(r"(\d+)", path.stem)
    return {
        "notice_id": notice_match.group(1) if notice_match else "",
        "title": title,
        "publication_date": publication_date,
        "closing_date": closing_date,
        "status": clean_text(status_detail).lower(),
        "buyer": clean_text(buyer_detail),
        "amount_text": clean_text(amount_detail),
        "supplier_name": clean_text(supplier_detail),
        "expired": "false",
    }


def build_output_rows(
    candidate_rows: Iterable[Dict[str, str]],
    translator: OptionalTranslator,
    date_from: str,
    date_to: str,
    keywords: Sequence[str],
) -> List[Dict[str, str]]:
    scraped_at = utc_now_iso()
    selected_rows: Dict[str, Dict[str, str]] = {}
    for row in candidate_rows:
        title = clean_text(row.get("title", ""))
        description = clean_text(row.get("description", ""))
        buyer = clean_text(row.get("buyer", ""))
        classification = clean_text(row.get("classification", ""))
        searchable_text = " | ".join(
            [
                title,
                description,
                buyer,
                classification,
            ]
        )
        matched = matched_keywords(searchable_text, keywords)
        explicit_medical = dubai_explicit_medical_title_signal(title, description)
        inferred_medical = dubai_product_signal(title, description, buyer, classification) and dubai_health_buyer_signal(buyer)
        if not matched and not inferred_medical and not explicit_medical:
            continue
        if not keep_dubai_medical_row(
            matched,
            title,
            description,
            buyer,
        ):
            if not inferred_medical and not explicit_medical:
                continue
        if not matched and explicit_medical:
            matched = ["dubai_explicit_medical_signal"]
        if not matched and inferred_medical:
            matched = ["dubai_healthcare_inferred"]
        publication_date = clean_text(row.get("publication_date", ""))
        closing_date = clean_text(row.get("closing_date", ""))
        if not publication_date or not closing_date:
            inferred_publication, inferred_closing = parse_dates_from_text(searchable_text)
            publication_date = publication_date or inferred_publication
            closing_date = closing_date or inferred_closing
        if publication_date and not in_date_window(publication_date, date_from, date_to):
            continue
        dedup_key = stable_key(
            row.get("title", ""),
            row.get("buyer", ""),
            row.get("publication_date", "") or publication_date,
            row.get("closing_date", "") or closing_date,
        )
        source_currency = clean_text(row.get("currency", ""))
        parsed_amount, parsed_currency = split_amount_and_currency(
            clean_text(row.get("amount_text", "")),
            default_currency=source_currency or "AED",
        )
        currency = parsed_currency or source_currency
        amount = parsed_amount
        if not clean_text(amount) and not clean_text(row.get("amount_text", "")):
            currency = ""
        base_row = {
            "source": "Dubai eSupply Public Opportunities",
            "country": "United Arab Emirates",
            "country_code": "AE",
            "publication_date": publication_date,
            "closing_date": closing_date,
            "title": clean_text(row.get("title", "")),
            "description": clean_text(row.get("description", "")),
            "buyer": clean_text(row.get("buyer", "")),
            "classification": clean_text(row.get("classification", "")) or "public opportunity",
            "status": clean_text(row.get("status", "")) or "open",
            "currency": currency,
            "amount": amount,
            "awarding_agency_name": clean_text(row.get("buyer", "")),
            "supplier_name": clean_text(row.get("supplier_name", "")),
            "awarded_date": "",
            "awarded_value_detail": clean_text(row.get("amount_text", "")),
            "contract_period": "",
            "item_no": "1",
            "item_description": clean_text(row.get("title", "")) or clean_text(row.get("description", "")),
            "item_uom": "",
            "item_quantity": "",
            "item_unit_price": "",
            "item_awarded_value": "",
            "notice_id": clean_text(row.get("notice_id", "")),
            "notice_url": clean_text(row.get("notice_url", "")),
            "query_text": ", ".join(matched),
            "scraped_at_utc": scraped_at,
            "dedup_key": dedup_key,
        }
        candidate_output = add_translation_columns(base_row, translator)
        existing = selected_rows.get(dedup_key)
        if not existing:
            selected_rows[dedup_key] = candidate_output
            continue
        existing_priority = STATUS_PRIORITY.get(clean_text(existing.get("status", "")).lower(), 0)
        candidate_priority = STATUS_PRIORITY.get(clean_text(candidate_output.get("status", "")).lower(), 0)
        if candidate_priority > existing_priority:
            selected_rows[dedup_key] = candidate_output
    return list(selected_rows.values())


def write_metadata(metadata: Dict[str, object], output_path: str) -> None:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)


def scrape_dubai_esupply(
    date_from: str,
    date_to: str,
    max_pages: int,
    translate: bool,
    keywords: Sequence[str],
) -> tuple[List[Dict[str, str]], Dict[str, object]]:
    translator = OptionalTranslator(enabled=translate)
    session = build_session()
    metadata: Dict[str, object] = {
        "source": "Dubai eSupply Public Opportunities",
        "home_url": HOME_URL,
        "date_from": date_from,
        "date_to": date_to,
        "public_counts": {},
        "opportunities_url": "",
        "opportunities_status_code": None,
        "current_list_url": CURRENT_LIST_URL,
        "past_list_url": PAST_LIST_URL,
        "access_state": "unknown",
        "notes": [],
    }

    homepage = {"counts": {}, "opportunities_url": "", "public_entities_present": False}
    try:
        home_status, home_html = fetch_html(session, HOME_URL)
        metadata["home_status_code"] = home_status
        if home_status < 400:
            homepage = parse_homepage(home_html)
            metadata["public_counts"] = homepage["counts"]
            metadata["opportunities_url"] = homepage["opportunities_url"]
            if homepage["public_entities_present"]:
                metadata["notes"].append("Homepage confirms healthcare-relevant Dubai government entities such as Dubai Health Authority.")
            if int(homepage["counts"].get("Current Opportunities", 0)) == 0:
                metadata["notes"].append("Homepage counter currently reports 0 Current Opportunities, but the public listing pages are reachable and expose rows.")
        else:
            metadata["notes"].append(f"Homepage returned HTTP {home_status}, continuing with direct public listing URLs.")
    except requests.RequestException as exc:
        metadata["home_status_code"] = None
        metadata["notes"].append(f"Homepage request failed: {exc.__class__.__name__}, continuing with direct public listing URLs.")

    candidate_rows: List[Dict[str, str]] = []
    current_source = "live"
    past_source = "live"
    current_saved_capture_names: List[str] = []
    past_saved_capture_names: List[str] = []

    current_html = ""
    current_status = None
    current_pages: List[tuple[str, str]] = []
    try:
        current_status, current_html = fetch_html(session, CURRENT_LIST_URL)
    except requests.RequestException:
        current_pages = load_saved_html_pages(CURRENT_CAPTURE_PATH)
        current_pages = extend_saved_pages(current_pages, discover_capture_paths(CURRENT_CAPTURE_PATTERNS))
        current_pages = [
            (page_name, page_html)
            for page_name, page_html in current_pages
            if parse_saved_listing_rows(page_html, f"{CURRENT_LIST_URL}#saved-{page_name}", "published")
        ]
        current_html = current_pages[0][1] if current_pages else ""
        current_source = "saved_browser_capture" if current_html else "unavailable"
    else:
        current_pages = load_saved_html_pages(CURRENT_CAPTURE_PATH)
        current_pages = extend_saved_pages(current_pages, discover_capture_paths(CURRENT_CAPTURE_PATTERNS))
        current_pages = [
            (page_name, page_html)
            for page_name, page_html in current_pages
            if parse_saved_listing_rows(page_html, f"{CURRENT_LIST_URL}#saved-{page_name}", "published")
        ]
        if current_pages:
            current_source = "live_plus_saved_capture"
    current_saved_capture_names = [page_name for page_name, _ in current_pages]
    if current_status is not None:
        metadata["current_opportunities_status_code"] = current_status
    if current_status == 200 and current_html:
        candidate_rows.extend(parse_esupply_listing_rows(current_html, CURRENT_LIST_URL, "published"))
    if current_pages:
        for page_name, page_html in current_pages:
            candidate_rows.extend(parse_saved_listing_rows(page_html, f"{CURRENT_LIST_URL}#saved-{page_name}", "published"))
    elif current_html:
        candidate_rows.extend(parse_esupply_listing_rows(current_html, CURRENT_LIST_URL, "published"))
    metadata["current_source"] = current_source
    metadata["current_saved_page_count"] = len(current_pages)
    metadata["current_saved_capture_names"] = current_saved_capture_names
    metadata["current_candidate_row_count"] = (
        sum(len(parse_saved_listing_rows(page_html, f"{CURRENT_LIST_URL}#saved-{page_name}", "published")) for page_name, page_html in current_pages)
        if current_pages
        else len(parse_esupply_listing_rows(current_html, CURRENT_LIST_URL, "published")) if current_html else 0
    )
    metadata["current_total_listed"] = extract_listing_total(current_html) if current_html else 0

    past_html = ""
    past_status = None
    past_pages: List[tuple[str, str]] = []
    try:
        past_status, past_html = fetch_html(session, PAST_LIST_URL)
    except requests.RequestException:
        past_pages = load_saved_html_pages(PAST_CAPTURE_PATH)
        past_pages = extend_saved_pages(past_pages, discover_capture_paths(PAST_CAPTURE_PATTERNS))
        past_pages = [
            (page_name, page_html)
            for page_name, page_html in past_pages
            if parse_saved_listing_rows(page_html, f"{PAST_LIST_URL}#saved-{page_name}", "closed")
        ]
        past_html = past_pages[0][1] if past_pages else ""
        past_source = "saved_browser_capture" if past_html else "unavailable"
    else:
        past_pages = load_saved_html_pages(PAST_CAPTURE_PATH)
        past_pages = extend_saved_pages(past_pages, discover_capture_paths(PAST_CAPTURE_PATTERNS))
        past_pages = [
            (page_name, page_html)
            for page_name, page_html in past_pages
            if parse_saved_listing_rows(page_html, f"{PAST_LIST_URL}#saved-{page_name}", "closed")
        ]
        if past_pages:
            past_source = "live_plus_saved_capture"
    past_saved_capture_names = [page_name for page_name, _ in past_pages]
    if past_status is not None:
        metadata["past_opportunities_status_code"] = past_status
    if past_status == 200 and past_html:
        candidate_rows.extend(parse_esupply_listing_rows(past_html, PAST_LIST_URL, "closed"))
    if past_pages:
        for page_name, page_html in past_pages:
            candidate_rows.extend(parse_saved_listing_rows(page_html, f"{PAST_LIST_URL}#saved-{page_name}", "closed"))
    elif past_html:
        candidate_rows.extend(parse_esupply_listing_rows(past_html, PAST_LIST_URL, "closed"))
    metadata["past_source"] = past_source
    metadata["past_saved_page_count"] = len(past_pages)
    metadata["past_saved_capture_names"] = past_saved_capture_names
    metadata["past_candidate_row_count"] = (
        sum(len(parse_saved_listing_rows(page_html, f"{PAST_LIST_URL}#saved-{page_name}", "closed")) for page_name, page_html in past_pages)
        if past_pages
        else len(parse_esupply_listing_rows(past_html, PAST_LIST_URL, "closed")) if past_html else 0
    )
    metadata["past_total_listed"] = extract_listing_total(past_html) if past_html else 0

    if not candidate_rows:
        metadata["access_state"] = "public_listing_unavailable"
        metadata["notes"].append("Public current/past listing pages were not fetchable from shell and no saved browser capture was available.")
        return [], metadata

    detail_paths = discover_capture_paths(DETAIL_CAPTURE_PATTERNS)
    detail_capture_names = [path.name for path in detail_paths]
    detail_pages = [parse_saved_detail_page(path) for path in detail_paths]
    detail_by_notice_id = {
        clean_text(detail.get("notice_id", "")): detail
        for detail in detail_pages
        if clean_text(detail.get("notice_id", "")) and clean_text(detail.get("expired", "")) != "true"
    }
    expired_detail_count = sum(1 for detail in detail_pages if clean_text(detail.get("expired", "")) == "true")
    metadata["detail_saved_page_count"] = len(detail_paths)
    metadata["detail_saved_capture_names"] = detail_capture_names
    metadata["detail_expired_page_count"] = expired_detail_count
    if expired_detail_count:
        metadata["notes"].append("Saved UAE detail-page artifacts currently on disk are expired-session shells rather than usable detail pages.")

    merged_candidate_rows: List[Dict[str, str]] = []
    for row in candidate_rows:
        merged = dict(row)
        notice_id = clean_text(row.get("notice_id", ""))
        detail = detail_by_notice_id.get(notice_id)
        if detail:
            for field in ("title", "buyer", "publication_date", "closing_date", "status", "amount_text", "supplier_name"):
                value = clean_text(detail.get(field, ""))
                if value:
                    merged[field] = value
        merged_candidate_rows.append(merged)

    metadata["candidate_row_count"] = len(candidate_rows)
    output_rows = build_output_rows(merged_candidate_rows, translator, date_from, date_to, keywords)
    metadata["rows_written"] = len(output_rows)
    if output_rows:
        metadata["access_state"] = "public_rows_extracted"
    else:
        metadata["access_state"] = "public_listing_no_matching_rows"
    return output_rows, metadata


def main() -> None:
    args = parse_args()
    rows, metadata = scrape_dubai_esupply(
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
        translate=args.translate,
        keywords=normalize_keyword_list(args.keywords),
    )
    serialize_rows(rows, args.output_jsonl, args.output_csv)
    write_metadata(metadata, args.output_metadata_json)
    print(
        json.dumps(
            {
                "rows_written": len(rows),
                "output_jsonl": args.output_jsonl,
                "output_csv": args.output_csv,
                "output_metadata_json": args.output_metadata_json,
                "date_from": args.date_from,
                "date_to": args.date_to,
                "access_state": metadata.get("access_state", ""),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
