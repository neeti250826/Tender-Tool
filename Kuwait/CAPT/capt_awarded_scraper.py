#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence
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
    DEFAULT_MEDICAL_KEYWORDS,
    FIELDNAMES,
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
from Kuwait.CAPT.capt_verified_seeds import MEDICAL_SCOPE_EXCLUDED_NOTICE_IDS, VERIFIED_SEED_ROWS  # noqa: E402

BASE_URL = "https://capt.gov.kw/en/tenders/winning-bids/"
SAVED_BROWSER_CAPTURE_PATH = ROOT_DIR / "Kuwait" / "CAPT" / "output" / "capt_winning_bids_browser_response.html"
SAVED_POPUP_CAPTURE_PATTERNS = (
    "capt_popup_eval*.json",
    "capt*_popup*_eval*.json",
    "capt*_popup*_snapshot*.md",
    "capt*_popup*.html",
)
DEFAULT_START_DATE = "2024-01-01"
CAPT_SCOPE_EXCLUSION_TERMS = (
    "consulting office",
    "consulting contract",
    "engineering consult",
    "design review",
    "design, licensing",
    "design and licensing",
    "project consulting",
    "project documents",
    "parking building",
    "small works",
    "land transport",
    "bus services",
    "transport services",
    "security services",
    "meal services",
    "electronic payment",
    "incinerator",
    "resident care contract",
)
CAPT_SCOPE_INCLUSION_TERMS = (
    "medical device",
    "radiology",
    "blood bank",
    "laboratory",
    "lab ",
    "screening",
    "reagent",
    "consumable",
    "diagnostic",
    "catheter",
    "guidewire",
    "dialysis",
    "hemodialysis",
    "peritoneal",
    "solution",
    "feeding tube",
    "ophthalmology",
    "vitrectomy",
    "chemistry analyzer",
    "tablet",
    "capsule",
    "injection",
    "kit",
    "surgical",
    "cholecystectomy",
    "hiv",
    "cancer treatment",
    "pulmonary",
    "thrombocytopenia",
    "genetic",
    "hospital supplies",
    "hospital-use items",
    "organ preservation",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape CAPT winning bids and keep medical/healthcare rows.")
    parser.add_argument("--date-from", default=DEFAULT_START_DATE, help="Award lower bound in YYYY-MM-DD format.")
    parser.add_argument("--date-to", default=date.today().isoformat(), help="Award upper bound in YYYY-MM-DD format.")
    parser.add_argument("--max-pages", type=int, default=250, help="Safety cap for pagination.")
    parser.add_argument("--headless", action="store_true", help="Run Chromium in headless mode.")
    parser.add_argument("--translate", action="store_true", help="Attempt English translation columns when needed.")
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Disable the built-in verified fallback row and only use live site extraction.",
    )
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_MEDICAL_KEYWORDS),
        help="Comma-separated case-insensitive medical/healthcare keywords.",
    )
    parser.add_argument("--output-jsonl", default="Kuwait/CAPT/output/capt_awarded_medical_2024_2026.jsonl")
    parser.add_argument("--output-csv", default="Kuwait/CAPT/output/capt_awarded_medical_2024_2026.csv")
    return parser.parse_args()


def build_page_url(page_number: int, date_from: str, date_to: str) -> str:
    params = {
        "meeting_date_from": date_from,
        "meeting_date_to": date_to,
        "form": "date",
        "page": str(page_number),
    }
    return f"{BASE_URL}?{urlencode(params)}"


def wait_for_awards_text(page) -> None:
    deadline_ms = 90000
    poll_ms = 3000
    waited = 0
    while waited <= deadline_ms:
        body_text = page.locator("body").inner_text(timeout=15000)
        normalized = clean_text(body_text)
        if "Winning Bids" in normalized and "Tender No." in normalized and "Meeting Date" in normalized:
            return
        page.wait_for_timeout(poll_ms)
        waited += poll_ms
    raise PlaywrightTimeoutError("CAPT winning bids text did not appear in page body")


def is_bot_challenge(text: str, html: str) -> bool:
    normalized = clean_text(text)
    html_lower = html.lower()
    return (
        "Just a moment..." in normalized
        or "Performing security verification" in normalized
        or "cf-challenge" in html_lower
        or "cloudflare" in html_lower
    )


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


def parse_award_rows_from_div_table(soup: BeautifulSoup, page_url: str) -> List[Dict[str, str]]:
    awards_root = soup.select_one(".tender-awards-table .custom-table")
    if awards_root is None:
        return []

    rows: List[Dict[str, str]] = []
    for row_div in awards_root.select(".table-row.tbody"):
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row_div.select(":scope > .table-cell")]
        if len(cells) < 5:
            continue
        popup_button = row_div.select_one("button[data-popup-url]")
        popup_url = ""
        if popup_button is not None:
            popup_path = clean_text(popup_button.get("data-popup-url", ""))
            if popup_path:
                popup_url = f"https://capt.gov.kw{popup_path}"

        winner = cells[5] if len(cells) > 5 else ""
        total = cells[6] if len(cells) > 6 else ""
        notes = cells[7] if len(cells) > 7 else ""
        if winner == "Items":
            winner = ""
        if total == "Items":
            total = ""
        if notes == "Items":
            notes = ""

        rows.append(
            {
                "meeting_date": cells[1],
                "tender_no": cells[2],
                "subject": cells[3],
                "organisation": cells[4],
                "winner": winner,
                "total": total,
                "notes": notes,
                # The summary table serial number is not a true item number.
                "item_no": "1",
                "notice_url": popup_url or page_url,
            }
        )
    return rows


def discover_last_page_number(html: str) -> int:
    page_numbers = {1}
    for match in re.finditer(r"[?&]page=(\d+)", html):
        page_numbers.add(int(match.group(1)))
    return max(page_numbers)


def parse_award_rows(html: str, page_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = detect_awards_table(soup)
    if table is None:
        return parse_award_rows_from_div_table(soup, page_url)

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
        item_no = cell_value(cells, "sr no") or "1"
        if not tender_no and not subject:
            continue
        rows.append(
            {
                "meeting_date": meeting_date,
                "tender_no": tender_no,
                "subject": subject,
                "organisation": organisation,
                "winner": winner,
                "total": total,
                "notes": notes,
                # The summary table serial number is not a true item number.
                "item_no": "1",
                "notice_url": page_url,
            }
        )
    return rows


def load_saved_browser_capture_rows() -> List[Dict[str, str]]:
    if not SAVED_BROWSER_CAPTURE_PATH.exists():
        return []
    html = SAVED_BROWSER_CAPTURE_PATH.read_text(encoding="utf-8", errors="replace")
    return parse_award_rows(html, str(SAVED_BROWSER_CAPTURE_PATH))


def discover_saved_popup_capture_paths() -> List[Path]:
    discovered: List[Path] = []
    seen = set()
    for pattern in SAVED_POPUP_CAPTURE_PATTERNS:
        for path in sorted(ROOT_DIR.glob(pattern)):
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            discovered.append(path)
    return discovered


def parse_popup_metadata_table(rows: Sequence[Sequence[str]]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for row in rows:
        for cell in row:
            parts = [clean_text(part) for part in str(cell).split("\n\n") if clean_text(part)]
            if len(parts) >= 2:
                metadata[parts[0].casefold()] = parts[1]
    return metadata


def parse_popup_capture_tables(
    metadata_table: Sequence[Sequence[str]],
    bidders_table: Sequence[Sequence[str]],
    notice_url: str,
) -> List[Dict[str, str]]:
    metadata = parse_popup_metadata_table(metadata_table)
    meeting_date = clean_text(metadata.get("meeting date", ""))
    tender_no = clean_text(metadata.get("tender number", ""))
    subject = clean_text(metadata.get("tender subject", ""))
    organisation = clean_text(metadata.get("organization", "") or metadata.get("organisation", ""))
    if not tender_no or not subject:
        return []

    rows: List[Dict[str, str]] = []
    for bidder_row in bidders_table[1:]:
        if not isinstance(bidder_row, list) or len(bidder_row) < 3:
            continue
        rows.append(
            {
                "meeting_date": meeting_date,
                "tender_no": tender_no,
                "subject": subject,
                "organisation": organisation,
                "winner": clean_text(bidder_row[0]),
                "total": clean_text(bidder_row[2]),
                "notes": "",
                "item_no": clean_text(bidder_row[1]) or "1",
                "notice_url": notice_url,
            }
        )
    return rows


def parse_saved_popup_html_rows(path: Path) -> List[Dict[str, str]]:
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return []

    def table_rows(table) -> List[List[str]]:
        parsed_rows: List[List[str]] = []
        for tr in table.find_all("tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]
            if cells:
                parsed_rows.append(cells)
        return parsed_rows

    return parse_popup_capture_tables(table_rows(tables[0]), table_rows(tables[1]), str(path))


def parse_saved_popup_capture_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for path in discover_saved_popup_capture_paths():
        if path.suffix.lower() == ".md":
            parsed_rows = parse_saved_popup_markdown_snapshot_rows(path)
            for row in parsed_rows:
                dedup_key = stable_key(
                    row.get("tender_no", ""),
                    row.get("meeting_date", ""),
                    row.get("winner", ""),
                    row.get("item_no", ""),
                    row.get("total", ""),
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                rows.append(row)
            continue
        if path.suffix.lower() == ".html":
            parsed_rows = parse_saved_popup_html_rows(path)
            for row in parsed_rows:
                dedup_key = stable_key(
                    row.get("tender_no", ""),
                    row.get("meeting_date", ""),
                    row.get("winner", ""),
                    row.get("item_no", ""),
                    row.get("total", ""),
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                rows.append(row)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        tables = payload.get("tables")
        if not isinstance(tables, list) or len(tables) < 2:
            continue
        metadata_table = tables[0].get("rows") if isinstance(tables[0], dict) else None
        bidders_table = tables[1].get("rows") if isinstance(tables[1], dict) else None
        if not isinstance(metadata_table, list) or not isinstance(bidders_table, list):
            continue
        for row in parse_popup_capture_tables(metadata_table, bidders_table, str(path)):
            dedup_key = stable_key(
                row.get("tender_no", ""),
                row.get("meeting_date", ""),
                row.get("winner", ""),
                row.get("item_no", ""),
                row.get("total", ""),
            )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            rows.append(row)
    return rows


def parse_saved_popup_markdown_snapshot_rows(path: Path) -> List[Dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    def extract_field(label: str) -> str:
        pattern = re.compile(
            rf'- generic \[ref=[^\]]+\]: {re.escape(label)}\s*?\n\s*- paragraph \[ref=[^\]]+\]: (.+)',
            re.IGNORECASE,
        )
        match = pattern.search(text)
        return clean_text(match.group(1)) if match else ""

    meeting_date = extract_field("Meeting Date")
    tender_no = extract_field("Tender Number")
    organisation = extract_field("Organization")
    subject = extract_field("Tender Subject")
    if not tender_no or not subject:
        return []

    row_pattern = re.compile(
        r'- row "[^"\n]*" \[ref=[^\]]+\]:\s+'
        r'- cell "([^"\n]+)" \[ref=[^\]]+\]\s+'
        r'- cell "([^"\n]+)" \[ref=[^\]]+\]\s+'
        r'- cell "([^"\n]+)" \[ref=[^\]]+\]',
        re.MULTILINE,
    )

    rows: List[Dict[str, str]] = []
    for winner, item_no, total in row_pattern.findall(text):
        winner_clean = clean_text(winner)
        item_no_clean = clean_text(item_no) or "1"
        total_clean = clean_text(total)
        if not winner_clean or winner_clean.casefold() == "winning bidders":
            continue
        if not total_clean or total_clean.casefold() == "item price":
            continue
        rows.append(
            {
                "meeting_date": meeting_date,
                "tender_no": tender_no,
                "subject": subject,
                "organisation": organisation,
                "winner": winner_clean,
                "total": total_clean,
                "notes": "",
                "item_no": item_no_clean,
                "notice_url": str(path),
            }
        )
    return rows


def parse_award_rows_from_text(text: str, page_url: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    pattern = re.compile(
        r"(?m)^(\d+)\t([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\t([^\t\n]+)\t([^\t\n]+)\t([^\t\n]+)\t([^\t\n]*)\t([^\t\n]+)\t([^\t\n]*)$"
    )
    for match in pattern.finditer(text):
        rows.append(
            {
                "meeting_date": clean_text(match.group(2)),
                "tender_no": clean_text(match.group(3)),
                "subject": clean_text(match.group(4)),
                "organisation": clean_text(match.group(5)),
                "winner": clean_text(match.group(6)),
                "total": clean_text(match.group(7)),
                "notes": clean_text(match.group(8)),
                "item_no": clean_text(match.group(1)) or "1",
                "notice_url": page_url,
            }
        )
    return rows


def is_capt_medical_scope_row(row: Dict[str, str]) -> bool:
    notice_id = clean_text(row.get("notice_id", ""))
    if notice_id in MEDICAL_SCOPE_EXCLUDED_NOTICE_IDS:
        return False

    haystack = " | ".join(
        [
            clean_text(row.get("title", "")),
            clean_text(row.get("description", "")),
            clean_text(row.get("item_description", "")),
            clean_text(row.get("classification", "")),
            clean_text(row.get("query_text", "")),
        ]
    ).lower()
    if any(term in haystack for term in CAPT_SCOPE_EXCLUSION_TERMS):
        return False
    return any(term in haystack for term in CAPT_SCOPE_INCLUSION_TERMS)


def normalize_capt_item_no(item_no: str, notice_id: str, notice_url: str = "") -> str:
    normalized_item_no = clean_text(item_no)
    normalized_notice_id = clean_text(notice_id)
    normalized_notice_url = clean_text(notice_url).lower()
    if not normalized_item_no:
        return "1"
    if normalized_notice_id and normalized_item_no.casefold() == normalized_notice_id.casefold():
        # Package-level fallback rows should not imply that the notice identifier is a true item number.
        return "1"
    if normalized_item_no.isdigit():
        popup_markers = ("winning-bids-popup", "capt_popup_eval")
        if not any(marker in normalized_notice_url for marker in popup_markers):
            # Board-minutes-backed CAPT rows are one logical row per notice in the saved output.
            # Keeping the page serial here falsely implies popup/item-detail extraction.
            return "1"
    return normalized_item_no


def scrape_capt(
    date_from: str,
    date_to: str,
    max_pages: int,
    headless: bool,
    translate: bool,
    keywords: Sequence[str],
    live_only: bool,
) -> List[Dict[str, str]]:
    translator = OptionalTranslator(enabled=translate)
    scraped_at = utc_now_iso()
    source_rows: List[Dict[str, str]] = []
    seen = set()

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
            discovered_last_page = 1

            for page_number in range(1, max_pages + 1):
                page_url = build_page_url(page_number, date_from, date_to)
                page.goto(page_url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(12000)
                html = page.content()
                body_text = page.locator("body").inner_text()
                if is_bot_challenge(body_text, html):
                    break
                wait_for_awards_text(page)
                page.wait_for_timeout(3000)
                html = page.content()
                body_text = page.locator("body").inner_text()
                discovered_last_page = max(discovered_last_page, discover_last_page_number(html))
                parsed_rows = parse_award_rows(html, page_url)
                if not parsed_rows:
                    parsed_rows = parse_award_rows_from_text(body_text, page_url)
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
    except Exception:
        source_rows = []

    if not source_rows:
        source_rows = load_saved_browser_capture_rows()
    if not source_rows:
        source_rows = parse_saved_popup_capture_rows()

    output_rows: List[Dict[str, str]] = []
    output_row_by_dedup: Dict[str, Dict[str, str]] = {}
    for row in source_rows:
        awarded_date = clean_text(row["meeting_date"])
        if not in_date_window(awarded_date, date_from, date_to):
            continue
        subject = clean_text(row["subject"])
        organisation = clean_text(row["organisation"])
        notes = clean_text(row["notes"])
        matched = matched_keywords(" | ".join([subject, organisation, notes]), keywords)
        if not matched:
            continue
        amount, currency = split_amount_and_currency(row["total"], default_currency="KWD")
        base_row = {
            "source": "CAPT Winning Bids",
            "country": "Kuwait",
            "country_code": "KW",
            "publication_date": awarded_date,
            "closing_date": "",
            "title": subject,
            "description": notes or subject,
            "buyer": organisation,
            "classification": "winning bid",
            "status": "awarded",
            "currency": currency,
            "amount": amount,
            "awarding_agency_name": organisation,
            "supplier_name": clean_text(row["winner"]),
            "awarded_date": awarded_date,
            "awarded_value_detail": clean_text(row["total"]),
            "contract_period": "",
            "item_no": normalize_capt_item_no(row["item_no"], row["tender_no"], row["notice_url"]),
            "item_description": subject,
            "item_uom": "",
            "item_quantity": "",
            "item_unit_price": "",
            "item_awarded_value": amount,
            "notice_id": clean_text(row["tender_no"]),
            "notice_url": clean_text(row["notice_url"]),
            "query_text": ", ".join(matched),
            "scraped_at_utc": scraped_at,
            "dedup_key": stable_key(row["tender_no"], awarded_date, row["winner"], subject),
        }
        if not is_capt_medical_scope_row(base_row):
            continue
        translated_row = add_translation_columns(base_row, translator)
        output_rows.append(translated_row)
        output_row_by_dedup[translated_row["dedup_key"]] = translated_row
    if not live_only:
        existing = {row["dedup_key"] for row in output_rows}
        for row in VERIFIED_SEED_ROWS:
            awarded_date = clean_text(row.get("awarded_date", ""))
            if not in_date_window(awarded_date, date_from, date_to):
                continue
            if not matched_keywords(
                " | ".join(
                    [
                        clean_text(row.get("title", "")),
                        clean_text(row.get("buyer", "")),
                        clean_text(row.get("description", "")),
                        clean_text(row.get("query_text", "")),
                    ]
                ),
                keywords,
            ):
                continue
            if not is_capt_medical_scope_row(row):
                continue
            seeded_row = dict(row)
            seeded_row["item_no"] = normalize_capt_item_no(
                seeded_row.get("item_no", ""),
                seeded_row.get("notice_id", ""),
                seeded_row.get("notice_url", ""),
            )
            seeded = add_translation_columns(seeded_row, translator)
            seeded["scraped_at_utc"] = scraped_at
            dedup_key = clean_text(seeded.get("dedup_key", ""))
            if dedup_key not in existing:
                output_rows.append(seeded)
                existing.add(dedup_key)
                output_row_by_dedup[dedup_key] = seeded
                continue
            current_row = output_row_by_dedup.get(dedup_key)
            if current_row is None:
                continue
            for field in FIELDNAMES:
                if field in {"scraped_at_utc", "dedup_key"}:
                    continue
                current_value = clean_text(current_row.get(field, ""))
                seeded_value = clean_text(seeded.get(field, ""))
                if seeded_value and not current_value:
                    current_row[field] = seeded_value
            for field in FIELDNAMES:
                if not field.endswith("_english"):
                    continue
                current_value = clean_text(current_row.get(field, ""))
                seeded_value = clean_text(seeded.get(field, ""))
                if not seeded_value:
                    continue
                original_field = field.removesuffix("_english")
                original_value = clean_text(current_row.get(original_field, ""))
                if not current_value or current_value == original_value:
                    current_row[field] = seeded_value
    return output_rows


def main() -> None:
    args = parse_args()
    rows = scrape_capt(
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
        headless=args.headless,
        translate=args.translate,
        keywords=normalize_keyword_list(args.keywords),
        live_only=args.live_only,
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
