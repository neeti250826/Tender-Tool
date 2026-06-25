import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright

from award_io import append_jsonl, ensure_parent_dir, load_jsonl, validate_rows, write_csv, write_jsonl


BASE_LISTING_URL = (
    "https://tenders.etimad.sa/Tender/AllTendersForVisitor?"
    "&MultipleSearch=&TenderCategory=6&TenderActivityId=11&ReferenceNumber=&TenderNumber=&agency="
    "&ConditionaBookletRange=&PublishDateId=1&cb_LastOfferPresentationDate=gregorian"
    "&LastOfferPresentationDate=01%252F01%252F2024&LastOfferPresentationDate=19%252F05%252F2026"
    "&TenderAreasIdString=&TenderTypeId=&TenderActivityId=11&TenderSubActivityId=1101&AgencyCode="
    "&FromLastOfferPresentationDateString=01/01/2024&ToLastOfferPresentationDateString=19/05/2026"
    "&SortDirection=DESC&Sort=SubmitionDate&PageSize=6&IsSearch=true&ConditionaBookletRange="
    "&PublishDateId=5&TenderCategory=&PageNumber=1"
)
DEFAULT_CURRENCY = "SAR"
WINDOW_START = date(2024, 1, 1)
WINDOW_END = date(2026, 5, 19)
DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM))?\b|\b\d{4}-\d{2}-\d{2}\b", re.I)
AMOUNT_RE = re.compile(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)")
CHECKPOINT_VERSION = 1


@dataclass
class AwardRow:
    source: str
    country: str
    country_code: str
    publication_date: Optional[str]
    closing_date: Optional[str]
    title: Optional[str]
    description: Optional[str]
    buyer: Optional[str]
    classification: Optional[str]
    status: Optional[str]
    currency: Optional[str]
    amount: Optional[str]
    awarding_agency_name: Optional[str]
    supplier_name: Optional[str]
    awarded_date: Optional[str]
    awarded_value_detail: Optional[str]
    contract_period: Optional[str]
    item_no: Optional[str]
    item_description: Optional[str]
    item_uom: Optional[str]
    item_quantity: Optional[str]
    item_unit_price: Optional[str]
    item_awarded_value: Optional[str]
    notice_id: Optional[str]
    notice_url: str
    query_text: str
    scraped_at_utc: str
    dedup_key: str


def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def normalize_amount(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    match = AMOUNT_RE.search(raw.replace(",", ""))
    return match.group(1) if match else clean_text(raw)


def normalize_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = clean_text(raw)
    for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S") if " %I:%M %p" in fmt else dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    match = DATE_RE.search(raw)
    return normalize_date(match.group(0)) if match else raw


def parse_iso_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    normalized = clean_text(raw)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def is_within_window(raw: Optional[str]) -> bool:
    parsed = parse_iso_date(raw)
    return parsed is not None and WINDOW_START <= parsed <= WINDOW_END


def log_debug(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[etimad {timestamp}] {message}", flush=True)


def build_default_checkpoint_path(output_path: str) -> str:
    return f"{output_path}.checkpoint.json"


def load_checkpoint(path: str) -> Optional[Dict[str, Any]]:
    checkpoint_file = Path(path)
    if not checkpoint_file.exists():
        return None
    return json.loads(checkpoint_file.read_text(encoding="utf-8"))


def save_checkpoint(path: str, state: Dict[str, Any]) -> None:
    ensure_parent_dir(path)
    checkpoint_file = Path(path)
    checkpoint_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def initialize_checkpoint_state(output_path: str) -> Dict[str, Any]:
    return {
        "version": CHECKPOINT_VERSION,
        "output_path": output_path,
        "phase": "listing",
        "completed": False,
        "next_page_number": 1,
        "listing_rows": [],
        "seen_urls": [],
        "next_detail_index": 0,
    }


def reset_resume_artifacts(output_path: str, checkpoint_path: str) -> None:
    output_file = Path(output_path)
    checkpoint_file = Path(checkpoint_path)
    if output_file.exists():
        output_file.unlink()
    if checkpoint_file.exists():
        checkpoint_file.unlink()


def build_page_url(page_number: int) -> str:
    parsed = urlparse(BASE_LISTING_URL)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["PageNumber"] = [str(page_number)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def get_active_pager_page(page) -> int:
    active = page.locator("li.page-item.active a.page-link")
    if active.count():
        text = clean_text(active.first.inner_text())
        if text and text.isdigit():
            return int(text)
    return 1


def next_page_available(page) -> bool:
    next_button = page.locator("li.page-item button.page-link[aria-label='Next']")
    return next_button.count() > 0 and next_button.first.is_enabled()


def advance_to_listing_page(page, target_page_number: int) -> int:
    current_page_number = get_active_pager_page(page)
    while current_page_number < target_page_number and next_page_available(page):
        next_button = page.locator("li.page-item button.page-link[aria-label='Next']").first
        log_debug(f"Advancing paginator from page {current_page_number} to page {current_page_number + 1}")
        next_button.click()
        page.wait_for_timeout(2500)
        current_page_number = get_active_pager_page(page)
    return current_page_number


def get_stender_id(notice_url: str) -> Optional[str]:
    parsed = urlparse(notice_url)
    values = parse_qs(parsed.query).get("STenderId")
    return values[0] if values else None


def build_component_url(component: str, stender_id: str) -> str:
    return f"https://tenders.etimad.sa/Tender/{component}?tenderIdStr={stender_id}"


def extract_label_map(soup: BeautifulSoup, root_selector: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in soup.select(f"{root_selector} li.list-group-item"):
        title_el = item.select_one(".etd-item-title")
        info_el = item.select_one(".etd-item-info")
        if not title_el or not info_el:
            continue
        key = clean_text(title_el.get_text(" ", strip=True))
        value = clean_text(info_el.get_text(" ", strip=True))
        if key and value:
            mapping[key] = value
    return mapping


def extract_contract_period_from_basic_info_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping = extract_label_map(soup, "#basicDetials")
    return mapping.get("Contract Duration") or mapping.get("Contract duration")


def parse_listing_page(html: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    rows = []
    for anchor in soup.select("a[href*='DetailsForVisitor?STenderId=']"):
        href = anchor.get("href")
        if not href:
            continue
        url = urljoin("https://tenders.etimad.sa/", href)
        if url in seen:
            continue
        seen.add(url)

        card = anchor.find_parent("div", class_="tender-card")
        if card is None:
            card = anchor
            while isinstance(card.parent, Tag):
                card = card.parent
                classes = " ".join(card.get("class", []))
                if "tender-card" in classes:
                    break

        card_text = clean_text(card.get_text(" ", strip=True)) or ""
        publication_date = None
        date_match = re.search(r"تاريخ النشر\s*:?\s*(\d{4}-\d{2}-\d{2})", card_text)
        if date_match:
            publication_date = normalize_date(date_match.group(1))
        else:
            fallback_dates = DATE_RE.findall(card_text)
            if fallback_dates:
                publication_date = normalize_date(fallback_dates[0])

        buyer = None
        buyer_p = card.find("p", class_="pb-2")
        if buyer_p:
            buyer = clean_text(buyer_p.get_text(" ", strip=True))
            if buyer:
                buyer = buyer.replace("التفاصيل", "").strip()
                if " - " in buyer:
                    buyer = buyer.split(" - ", 1)[0].strip()

        rows.append(
            {
                "notice_url": url,
                "title": clean_text(anchor.get_text(" ", strip=True)),
                "publication_date": publication_date,
                "buyer": buyer,
                "raw_text": card_text,
            }
        )
    return rows


def parse_detail_page(html: str, listing_row: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    mapping = extract_label_map(soup, "#basicDetials")
    purpose_full = soup.select_one("#purposeSpan")
    purpose_short = soup.select_one("#subPurposSapn")
    if purpose_full:
        for tag in purpose_full.select("i"):
            tag.decompose()
    if purpose_short:
        for tag in purpose_short.select("i"):
            tag.decompose()
    description = clean_text(purpose_full.get_text(" ", strip=True)) if purpose_full else None
    if not description and purpose_short:
        description = clean_text(purpose_short.get_text(" ", strip=True))
    return {
        "title": mapping.get("اسم المنافسة") or listing_row.get("title"),
        "description": description or mapping.get("الغرض من المنافسة"),
        "status": mapping.get("حالة المنافسة"),
        "buyer": clean_text((listing_row.get("buyer") or "").split(" - ")[0]) or mapping.get("الجهة الحكومية"),
        "reference_number": mapping.get("الرقم المرجعي"),
        "tender_number": mapping.get("رقم المنافسة"),
        "contract_period": mapping.get("مدة العقد"),
        "classification": mapping.get("نوع المنافسة"),
    }


def extract_closing_date_from_dates_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select("li.list-group-item"):
        title_el = item.select_one(".etd-item-title")
        if not title_el:
            continue
        title = clean_text(title_el.get_text(" ", strip=True))
        if not title or "آخر موعد لتقديم العروض" not in title:
            continue
        spans = [clean_text(span.get_text(" ", strip=True)) for span in item.select(".etd-item-info span")]
        spans = [text for text in spans if text]
        gregorian = next((text for text in spans if re.match(r"\d{1,2}/\d{1,2}/\d{4}$", text)), None)
        meridiem = next((text for text in spans if re.match(r"\d{1,2}:\d{2}\s*(?:AM|PM)$", text, re.I)), None)
        if gregorian and meridiem:
            return normalize_date(f"{gregorian} {meridiem}")
        if gregorian:
            return normalize_date(gregorian)
    return None


def extract_award_date_from_dates_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select("li.list-group-item"):
        title_el = item.select_one(".etd-item-title")
        if not title_el:
            continue
        title = clean_text(title_el.get_text(" ", strip=True))
        if not title:
            continue
        if "المتوقع للترسية" not in title and "تاريخ الترسية" not in title:
            continue
        spans = [clean_text(span.get_text(" ", strip=True)) for span in item.select(".etd-item-info span")]
        spans = [text for text in spans if text and re.match(r"\d{1,2}/\d{1,2}/\d{4}$", text)]
        if spans:
            return normalize_date(spans[0])
    return None


def extract_classification_from_relations_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping = extract_label_map(soup, "#ActivityDetials")
    return mapping.get("نشاط المنافسة") or mapping.get("التفاصيل")


def parse_award_component(html: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for table in soup.find_all("table"):
        headers = [clean_text(th.get_text(" ", strip=True)) or "" for th in table.select("th")]
        header_text = " | ".join(headers)
        if "إسم المورد" not in header_text and "اسم المورد" not in header_text:
            continue
        for row in table.select("tbody tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in row.select("td")]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            supplier_name = cells[0]
            numeric_values = [normalize_amount(cell) for cell in cells[1:] if AMOUNT_RE.search(cell or "")]
            amount = numeric_values[-1] if numeric_values else None
            key = (supplier_name, amount)
            if key in seen:
                continue
            seen.add(key)
            results.append({"supplier_name": supplier_name, "amount": amount})
    return results


def extract_item_details_from_html(html_blocks: List[str]) -> List[Dict[str, Optional[str]]]:
    items = []
    for html in html_blocks:
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            headers = [clean_text(th.get_text(" ", strip=True)) or "" for th in table.select("th")]
            header_text = " | ".join(headers)
            if not any(token in header_text for token in ("Item", "الصنف", "الكمية", "Quantity")):
                continue
            for row in table.select("tbody tr"):
                cells = [clean_text(td.get_text(" ", strip=True)) for td in row.select("td")]
                cells = [cell for cell in cells if cell]
                if not cells:
                    continue
                items.append(
                    {
                        "item_no": cells[0] if len(cells) > 0 else None,
                        "item_description": cells[1] if len(cells) > 1 else None,
                        "item_uom": cells[2] if len(cells) > 2 else None,
                        "item_quantity": normalize_amount(cells[3]) if len(cells) > 3 else None,
                        "item_unit_price": normalize_amount(cells[4]) if len(cells) > 4 else None,
                        "item_awarded_value": normalize_amount(cells[5]) if len(cells) > 5 else None,
                    }
                )
    return items

def scrape(
    max_pages: Optional[int],
    sleep_seconds: float,
    output_path: str,
    checkpoint_path: str,
    resume: bool,
) -> List[AwardRow]:
    ensure_parent_dir(output_path)
    ensure_parent_dir(checkpoint_path)
    if resume:
        state = load_checkpoint(checkpoint_path) or initialize_checkpoint_state(output_path)
        existing_rows = load_jsonl(output_path) if Path(output_path).exists() else []
        output_rows = [AwardRow(**row) for row in existing_rows]
        log_debug(
            f"Resuming run: phase={state.get('phase')} next_page={state.get('next_page_number')} "
            f"next_detail_index={state.get('next_detail_index')} existing_rows={len(output_rows)}"
        )
        if state.get("completed"):
            log_debug("Checkpoint already marked complete; returning existing rows.")
            return output_rows
    else:
        reset_resume_artifacts(output_path, checkpoint_path)
        state = initialize_checkpoint_state(output_path)
        output_rows = []
        log_debug("Starting fresh run and cleared previous checkpoint/output artifacts.")

    listing_rows: List[Dict[str, Optional[str]]] = list(state.get("listing_rows", []))
    seen_urls = set(state.get("seen_urls", []))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        if state.get("phase") == "listing":
            requested_page_number = int(state.get("next_page_number", 1))
            page.goto(build_page_url(1), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(4000)
            current_page_number = advance_to_listing_page(page, requested_page_number)
            log_debug(
                f"Listing phase initialized at visible pager page {current_page_number} "
                f"(requested start page {requested_page_number})"
            )
            while True:
                if max_pages and current_page_number > max_pages:
                    log_debug(f"Reached max_pages={max_pages}; stopping listing pagination.")
                    break
                log_debug(f"Reading visible listing pager page {current_page_number}")
                parsed_page_rows = parse_listing_page(page.content())
                log_debug(f"Page {current_page_number} visible tender rows: {len(parsed_page_rows)}")
                if not parsed_page_rows:
                    log_debug(f"Stopping pagination at page {current_page_number} because no tender rows were visible.")
                    break
                page_rows = [row for row in parsed_page_rows if row["notice_url"] not in seen_urls]
                for row in page_rows:
                    seen_urls.add(row["notice_url"])
                listing_rows.extend(page_rows)
                log_debug(
                    f"Page {current_page_number} added {len(page_rows)} new tenders; "
                    f"running unique total={len(listing_rows)}"
                )
                state.update(
                    {
                        "phase": "listing",
                        "next_page_number": current_page_number + 1,
                        "listing_rows": listing_rows,
                        "seen_urls": sorted(seen_urls),
                    }
                )
                save_checkpoint(checkpoint_path, state)
                if not next_page_available(page):
                    log_debug(f"Stopping pagination at page {current_page_number} because the Next pager button is disabled.")
                    break
                next_button = page.locator("li.page-item button.page-link[aria-label='Next']").first
                log_debug(f"Clicking pager Next from page {current_page_number}")
                next_button.click()
                page.wait_for_timeout(4000)
                new_page_number = get_active_pager_page(page)
                if new_page_number == current_page_number:
                    log_debug(f"Stopping pagination because the active page did not change from {current_page_number}.")
                    break
                current_page_number = new_page_number
                time.sleep(sleep_seconds)

            state.update(
                {
                    "phase": "details",
                    "next_page_number": current_page_number,
                    "listing_rows": listing_rows,
                    "seen_urls": sorted(seen_urls),
                    "next_detail_index": int(state.get("next_detail_index", 0)),
                }
            )
            save_checkpoint(checkpoint_path, state)
            log_debug(f"Listing phase complete with {len(listing_rows)} unique tenders queued for detail scraping.")

        next_detail_index = int(state.get("next_detail_index", 0))
        for index in range(next_detail_index, len(listing_rows)):
            listing_row = listing_rows[index]
            notice_url = listing_row["notice_url"]
            stender_id = get_stender_id(notice_url)
            log_debug(f"Processing tender {index + 1}/{len(listing_rows)}: {notice_url}")
            if not stender_id:
                log_debug(f"Skipping tender at index {index} because STenderId could not be parsed.")
                state["next_detail_index"] = index + 1
                save_checkpoint(checkpoint_path, state)
                continue

            page.goto(notice_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(2500)
            detail_html = page.content()

            page.goto(build_component_url("GetTenderDatesViewComponenet", stender_id), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(1200)
            dates_html = page.content()

            page.goto(build_component_url("GetRelationsDetailsViewComponenet", stender_id), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(1200)
            relations_html = page.content()

            page.goto(build_component_url("GetAwardingResultsForVisitorViewComponenet", stender_id), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(1200)
            awards_html = page.content()

            detail = parse_detail_page(detail_html, listing_row)
            closing_date = extract_closing_date_from_dates_html(dates_html)
            if closing_date:
                closing_date = closing_date.split("T", 1)[0]
            detail["contract_period"] = extract_contract_period_from_basic_info_html(detail_html) or detail.get("contract_period")
            awarded_date = extract_award_date_from_dates_html(dates_html)
            classification = extract_classification_from_relations_html(relations_html) or detail.get("classification")
            award_rows = parse_award_component(awards_html)
            item_details = extract_item_details_from_html([detail_html, relations_html, awards_html, dates_html])

            if not award_rows:
                log_debug(f"Skipping tender {notice_url} because no award rows were found.")
                state["next_detail_index"] = index + 1
                save_checkpoint(checkpoint_path, state)
                continue
            if not item_details:
                item_details = [
                    {
                        "item_no": None,
                        "item_description": None,
                        "item_uom": None,
                        "item_quantity": None,
                        "item_unit_price": None,
                        "item_awarded_value": None,
                    }
                ]

            scraped_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            notice_id = detail.get("reference_number") or detail.get("tender_number")
            tender_rows: List[AwardRow] = []
            for award in award_rows:
                for item in item_details:
                    amount = award.get("amount")
                    tender_rows.append(
                        AwardRow(
                            source="tenders.etimad.sa",
                            country="Saudi Arabia",
                            country_code="SA",
                            publication_date=listing_row.get("publication_date"),
                            closing_date=closing_date,
                            title=detail.get("title"),
                            description=detail.get("description") or item.get("item_description"),
                            buyer=detail.get("buyer"),
                            classification=classification,
                            status=detail.get("status"),
                            currency=DEFAULT_CURRENCY,
                            amount=amount,
                            awarding_agency_name=detail.get("buyer"),
                            supplier_name=award.get("supplier_name"),
                            awarded_date=awarded_date,
                            awarded_value_detail=amount,
                            contract_period=detail.get("contract_period"),
                            item_no=item.get("item_no"),
                            item_description=item.get("item_description"),
                            item_uom=item.get("item_uom"),
                            item_quantity=item.get("item_quantity"),
                            item_unit_price=item.get("item_unit_price"),
                            item_awarded_value=item.get("item_awarded_value"),
                            notice_id=notice_id,
                            notice_url=notice_url,
                            query_text="TenderActivityId=11; TenderSubActivityId=1101; paginated listing",
                            scraped_at_utc=scraped_at_utc,
                            dedup_key=f"tenders.etimad.sa|{notice_id or ''}|{award.get('supplier_name') or ''}|{amount or ''}",
                        )
                    )

            tender_rows = [row for row in tender_rows if is_within_window(row.closing_date)]
            if not tender_rows:
                log_debug(f"Skipping tender {notice_url} because all rows fell outside the closing_date window.")
                state["next_detail_index"] = index + 1
                save_checkpoint(checkpoint_path, state)
                continue

            append_jsonl(output_path, tender_rows)
            output_rows.extend(tender_rows)
            log_debug(
                f"Wrote {len(tender_rows)} rows for tender {notice_url}; "
                f"running stored row total={len(output_rows)}"
            )

            state["next_detail_index"] = index + 1
            save_checkpoint(checkpoint_path, state)
            time.sleep(sleep_seconds)

        browser.close()

    state["completed"] = True
    state["phase"] = "done"
    save_checkpoint(checkpoint_path, state)
    log_debug(f"Run complete. Final stored row count={len(output_rows)}")
    return output_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape awarded tender data from Etimad.")
    parser.add_argument("--output", default="etimad_awards.jsonl", help="Output JSONL path")
    parser.add_argument("--csv-output", default=None, help="Optional CSV output path")
    parser.add_argument("--checkpoint-path", default=None, help="Optional checkpoint JSON path for resume support")
    parser.add_argument("--max-pages", type=int, default=None, help="Limit number of listing pages to process")
    parser.add_argument("--resume", action="store_true", help="Resume from the checkpoint and existing JSONL output")
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="Delay between requests")
    parser.add_argument("--validate", action="store_true", help="Validate rows against the normalized schema")
    args = parser.parse_args()
    checkpoint_path = args.checkpoint_path or build_default_checkpoint_path(args.output)
    rows = scrape(
        max_pages=args.max_pages,
        sleep_seconds=args.sleep_seconds,
        output_path=args.output,
        checkpoint_path=checkpoint_path,
        resume=args.resume,
    )
    ensure_parent_dir(args.output)
    if args.csv_output:
        ensure_parent_dir(args.csv_output)
        write_csv(args.csv_output, rows)
    if args.validate:
        errors, count = validate_rows([row.__dict__ for row in rows])
        if errors:
            raise SystemExit("Validation failed:\n" + "\n".join(errors[:50]))
        print(f"Validated {count} rows")
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
