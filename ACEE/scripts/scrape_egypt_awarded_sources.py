from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OUTPUT_COLUMNS, OutputRow
from harness.shared.serialize import write_rows_csv


GCS_BASE = "https://gcs.digitalegypt.gov.eg"
GCS_FIND_TENDERS = f"{GCS_BASE}/Landing/FindTenders"
GCS_TENDERS = f"{GCS_BASE}/Landing/Tenders"
WB_HEALTH_AWARDS_CSV = (
    "https://financesonefiles.worldbank.org/f-one/DS01119/"
    "Project_Procurement_Contract_Awards_in_Health_sector.csv"
)
WB_PROCUREMENT_PLAN_TXT_LATEST = (
    "https://documents1.worldbank.org/curated/en/099121825104032603/txt/"
    "P167000-9299ce8c-d0fa-4fa4-bdf8-aa6950a178e8.txt"
)
WB_PROCUREMENT_PLAN_TXT = (
    "https://documents1.worldbank.org/curated/en/099032525055019759/txt/"
    "P167000-fed2f1c7-2e4b-4893-aefe-9094aa77971d.txt"
)
WB_PROCUREMENT_PLAN_TXT_RECENT = (
    "https://documents1.worldbank.org/curated/en/099012925071024570/txt/"
    "P167000-4d0e7eb3-391f-49d2-82e7-5d4d8c8ba15c.txt"
)

AWARDED_STATUS_VALUE = "858870005"
GCS_STATUS_MAP = {
    "مرحلة النشر": "Published",
    "مرحلة التوريد": "Complete",
    "مرحلة الترسية": "Awarded",
}

GCS_FIELD_LABELS = {
    "اسم العملية": "title",
    "اسم الجهه": "buyer",
    "رقم العملية": "notice_id",
    "طريقة التعاقد": "procurement_method",
    "طبيعة العملية": "classification",
    "العملة": "currency",
    "مدة التوريد / التنفيذ": "contract_period",
    "الأنشطة": "classification",
    "الوصف باللغة العربية": "description",
    "تاريخ الإعلان / الدعوة": "publication_date",
    "تاريخ فتح المظاريف الفنية": "closing_date",
    "تاريخ الترسية": "award_date",
}

GCS_ITEM_LABELS = {
    "البند": "item_desc",
    "الوحدة": "item_uom",
    "الكمية المطلوبة": "item_quantity",
}

ARABIC_MEDICAL_TERMS = (
    "صحي",
    "صحية",
    "طبي",
    "طبية",
    "مستشفى",
    "مستشفيات",
    "دواء",
    "دوائية",
    "صيد",
    "لقاح",
    "معمل",
    "تحاليل",
    "قسطرة",
)

ENGLISH_MEDICAL_TERMS = (
    "suture",
    "glove",
    "gown",
    "vial",
    "syringe",
    "catheter",
    "hospital",
    "health",
    "medical",
    "pharma",
    "ivig",
    "nucleic acid",
)

REQUIRED_USER_FIELD_GROUPS = {
    "publication_date": ("publication_date",),
    "amount_or_awarded_value": ("amount", "awarded_value"),
    "contract_period": ("contract_period",),
    "awarding_supplier_name": ("awarding_supplier_name",),
    "awarded_date_schema_gap_item_award": ("item_award",),
    "item_uom": ("item_uom",),
    "item_quantity": ("item_quantity",),
    "item_no": ("item_no",),
    "item_desc": ("item_desc",),
}


def _clean(value: str | None) -> str:
    text = normalize_text(value or "")
    return "" if text in {"لا يوجد", "-"} else text


def _date_only(value: str) -> str:
    match = re.search(r"\d{4}/\d{2}/\d{2}|\d{4}-\d{2}-\d{2}", value or "")
    return match.group(0).replace("/", "-") if match else _clean(value)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en;q=0.9",
        }
    )
    return session


def _post_gcs_awarded_page(session: requests.Session, page: int, timeout: int) -> str:
    response = session.post(
        GCS_FIND_TENDERS,
        data={
            "GovEntity": "",
            "TenderName": "",
            "TenderNumber": "",
            "ProcessStatus": AWARDED_STATUS_VALUE,
            "tenderkind": "",
            "tendermethod": "",
            "TenderDate": "",
            "Page": str(page),
        },
        headers={
            "Referer": GCS_TENDERS,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def _parse_gcs_listing(html: str) -> tuple[list[dict[str, str]], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    for tr in soup.find_all("tr"):
        cells = [_clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        href = _clean((tr.find("a") or {}).get("href") if tr.find("a") else "")
        if len(cells) < 6 or not href.startswith("/Landing/TenderDetails/"):
            continue
        rows.append(
            {
                "notice_number": cells[0],
                "title": cells[1],
                "buyer": cells[2],
                "publication_date": _date_only(cells[3]),
                "closing_date": _date_only(cells[4]),
                "status": GCS_STATUS_MAP.get(cells[5], cells[5]),
                "href": href,
                "notice_url": f"{GCS_BASE}{href}",
                "notice_id": href.rstrip("/").split("/")[-1],
            }
        )

    page_count: int | None = None
    page_text = soup.get_text(" ", strip=True)
    match = re.search(r"عرض صفحة\s+\d+\s+من\s+(\d+)", page_text)
    if match:
        page_count = int(match.group(1))
    return rows, page_count


def _extract_gcs_fields(detail_html: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    soup = BeautifulSoup(detail_html, "html.parser")
    fields: dict[str, str] = {}
    for block in soup.select("div.p-3.d-flex.flex-column"):
        label = _clean(block.find("label").get_text(" ", strip=True) if block.find("label") else "")
        value = _clean(block.find("p", class_="m-0").get_text(" ", strip=True) if block.find("p", class_="m-0") else "")
        target = GCS_FIELD_LABELS.get(label)
        if target and value:
            fields[target] = value

    items: list[dict[str, str]] = []
    for block in soup.select("div.row.py-3.px-2.m-0.bg-gray.info"):
        item: dict[str, str] = {}
        for cell in block.select("div.col-md-4"):
            label = _clean(cell.find("label").get_text(" ", strip=True) if cell.find("label") else "")
            value = _clean(cell.find("p", class_="m-0").get_text(" ", strip=True) if cell.find("p", class_="m-0") else "")
            target = GCS_ITEM_LABELS.get(label)
            if target and value:
                item[target] = value
        if item:
            items.append(item)
    return fields, items or [{}]


def _is_medical(row: dict[str, str]) -> bool:
    haystack = " ".join(row.get(key, "") for key in ("title", "description", "buyer", "classification", "item_desc")).lower()
    arabic_letter = r"\u0600-\u06FF"
    for term in ARABIC_MEDICAL_TERMS:
        if term in {"طبي", "صحي", "صيد"}:
            if re.search(rf"(^|[^{arabic_letter}])(?:ال)?{re.escape(term)}($|[^{arabic_letter}])", haystack):
                return True
            continue
        if term in haystack:
            return True
    return any(term.lower() in haystack for term in ENGLISH_MEDICAL_TERMS)


def scrape_gcs_awarded(
    *,
    evidence_dir: Path,
    timeout: int,
    max_pages: int | None,
    query_text: str,
) -> list[dict[str, str]]:
    session = _session()
    session.get(GCS_TENDERS, timeout=timeout).raise_for_status()
    scraped_at = utc_now_iso()
    evidence_dir.mkdir(parents=True, exist_ok=True)

    page = 0
    total_pages: int | None = None
    listing_rows: list[dict[str, str]] = []
    while True:
        html = _post_gcs_awarded_page(session, page, timeout)
        (evidence_dir / f"egypt_gcs_awarded_list_page_{page + 1}.html").write_text(html, encoding="utf-8")
        rows, parsed_total_pages = _parse_gcs_listing(html)
        if parsed_total_pages:
            total_pages = parsed_total_pages
        listing_rows.extend(rows)
        page += 1
        if not rows:
            break
        if max_pages is not None and page >= max_pages:
            break
        if total_pages is not None and page >= total_pages:
            break

    output_rows: list[dict[str, str]] = []
    seen_detail_ids: set[str] = set()
    for listing in listing_rows:
        detail_id = listing["notice_id"]
        if detail_id in seen_detail_ids:
            continue
        seen_detail_ids.add(detail_id)
        response = session.get(listing["notice_url"], timeout=timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        detail_html = response.text
        safe_id = detail_id.replace("-", "_")
        (evidence_dir / f"egypt_gcs_awarded_detail_{safe_id}.html").write_text(detail_html, encoding="utf-8")
        fields, items = _extract_gcs_fields(detail_html)
        for index, item in enumerate(items, start=1):
            row = OutputRow(
                source="gcs.digitalegypt.gov.eg",
                country="Egypt",
                country_cc="EG",
                publication_date=_date_only(fields.get("publication_date", "")) or listing.get("publication_date", ""),
                closing_date=_date_only(fields.get("closing_date", "")) or listing.get("closing_date", ""),
                title=fields.get("title", "") or listing.get("title", ""),
                description=fields.get("description", "") or item.get("item_desc", "") or listing.get("title", ""),
                buyer=fields.get("buyer", "") or listing.get("buyer", ""),
                classification=fields.get("classification", ""),
                status="Awarded",
                currency=fields.get("currency", ""),
                contract_period=fields.get("contract_period", ""),
                item_no=str(index),
                item_desc=item.get("item_desc", ""),
                item_uom=item.get("item_uom", ""),
                item_quantity=item.get("item_quantity", ""),
                item_award=_date_only(fields.get("award_date", "")),
                notice_id=fields.get("notice_id", "") or listing.get("notice_number", "") or detail_id,
                notice_url=listing["notice_url"],
                query_text=query_text,
                scraped_at=scraped_at,
                dedup_key=f"egypt_gcs|awarded|{detail_id}|{index}",
            ).to_dict()
            output_rows.append(row)
    return output_rows


def _iter_wb_awards(timeout: int) -> Iterable[dict[str, str]]:
    response = requests.get(WB_HEALTH_AWARDS_CSV, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8-sig"
    yield from csv.DictReader(response.text.splitlines())


def _world_bank_plan_text(*, evidence_dir: Path, timeout: int) -> str:
    texts: list[str] = []
    for url, name in (
        (WB_PROCUREMENT_PLAN_TXT_LATEST, "world_bank_p167000_procurement_plan_2025_12_18.txt"),
        (WB_PROCUREMENT_PLAN_TXT, "world_bank_p167000_procurement_plan_2025_03_25.txt"),
        (WB_PROCUREMENT_PLAN_TXT_RECENT, "world_bank_p167000_procurement_plan_2025_01_29.txt"),
    ):
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        text = response.text
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / name).write_text(text, encoding="utf-8")
        texts.append(text)
    return "\n\n".join(texts)


def _world_bank_plan_block(plan_text: str, borrower_reference: str) -> str:
    reference = _clean(borrower_reference)
    if not reference:
        return ""
    start = plan_text.find(reference)
    if start < 0:
        return ""
    next_match = re.search(
        r"\n\s*(?:EG-UPA|EG-MOHP|CERC-UPA|CERC-UPAQ|AFD-UPA)-[A-Z0-9-]+",
        plan_text[start + len(reference) :],
    )
    end = start + len(reference) + next_match.start() if next_match else len(plan_text)
    return plan_text[start:end]


def _world_bank_split_plan_dates(block: str) -> list[str]:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        months = re.findall(r"(20\d{2})-(\d{2})-", line)
        if not months:
            continue
        for candidate in lines[index + 1 : index + 6]:
            days = [
                day
                for day in re.findall(r"\b(\d{2})\b", candidate)
                if 1 <= int(day) <= 31
            ]
            if len(days) >= len(months):
                return [f"{year}-{month}-{day}" for (year, month), day in zip(months, days)]
    return []


def _world_bank_plan_dates(block: str) -> list[str]:
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", block)
    return dates or _world_bank_split_plan_dates(block)


def _world_bank_publication_date(plan_text: str, borrower_reference: str) -> str:
    block = _world_bank_plan_block(plan_text, borrower_reference)
    dates = _world_bank_plan_dates(block)
    if len(dates) >= 8:
        return dates[3]
    if len(dates) >= 2:
        return dates[1]
    return dates[0] if dates else ""


def _world_bank_contract_period(plan_text: str, borrower_reference: str, signing_date: str = "") -> str:
    block = _world_bank_plan_block(plan_text, borrower_reference)
    if not block:
        return ""
    dates = _world_bank_plan_dates(block)
    if dates:
        contract_completion = dates[-1]
        if signing_date:
            return f"Signed contract {signing_date}; planned contract completion {contract_completion}"
        if len(dates) >= 2:
            return f"Signed contract {dates[-2]}; planned contract completion {contract_completion}"
    return ""


def _world_bank_item_measure(description: str) -> tuple[str, str]:
    text = _clean(description)
    lot_words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}
    lot_match = re.search(r"\b(one|two|three|four|five|\d+)\s+lots?\b", text, re.I)
    if lot_match:
        quantity = lot_words.get(lot_match.group(1).lower(), lot_match.group(1))
        return "lot", quantity
    quantity_match = re.search(r"\bQuantity\s*:\s*([0-9,]+)\s*([A-Za-z][A-Za-z /-]*)?", text, re.I)
    if quantity_match:
        quantity = quantity_match.group(1).replace(",", "")
        unit = _clean(quantity_match.group(2) or "")
        return unit, quantity
    return "", ""


def _world_bank_item_no(description: str) -> tuple[str, str]:
    text = _clean(description)
    lot_match = re.search(r"\bLOT\s*([0-9A-Za-z.-]+)\b", text, re.I)
    if lot_match:
        return f"Lot {lot_match.group(1)}", "World Bank award description LOT marker"
    suffix_match = re.search(
        r"\b(Sutures|Vascular\s+Consumables|Vascular\s+Ball?o?n,?\s+Stents)\s+([0-9A-Za-z.-]+)\b",
        text,
        re.I,
    )
    if suffix_match:
        return suffix_match.group(2), "World Bank award description item suffix"
    return "1", "default single-row item"


def scrape_world_bank_health_awards(
    *,
    start_date: str,
    end_date: str,
    timeout: int,
    query_text: str,
    procurement_plan_text: str = "",
) -> list[dict[str, str]]:
    scraped_at = utc_now_iso()
    rows: list[dict[str, str]] = []
    for source_row in _iter_wb_awards(timeout):
        signing_date = source_row.get("contract_signing_date", "")
        if source_row.get("borrower_country_code") != "EG":
            continue
        if not (start_date <= signing_date <= end_date):
            continue
        if source_row.get("procurement_category") != "Goods":
            continue
        description = _clean(source_row.get("contract_description", ""))
        project = _clean(source_row.get("project_name", ""))
        if not _is_medical({"title": description, "description": project}):
            continue
        contract_number = _clean(source_row.get("wb_contract_number", ""))
        reference = _clean(source_row.get("borrower_contract_reference_number", ""))
        amount = _clean(source_row.get("supplier_contract_amount_usd", ""))
        plan_block = _world_bank_plan_block(procurement_plan_text, reference) if procurement_plan_text else ""
        step_publication_date = (
            _world_bank_publication_date(procurement_plan_text, reference)
            if procurement_plan_text
            else ""
        )
        publication_date = step_publication_date or _clean(source_row.get("as_of_date", ""))
        publication_note = (
            "publication_date_source=World Bank STEP invitation date"
            if step_publication_date
            else "publication_date_source=World Bank dataset as_of_date"
        )
        contract_period = (
            _world_bank_contract_period(procurement_plan_text, reference, signing_date)
            if procurement_plan_text
            else ""
        )
        item_uom, item_quantity = _world_bank_item_measure(description)
        item_measure_note = (
            "item_measure_source=award_description"
            if item_uom and item_quantity
            else "item_measure_source=not_exposed"
        )
        if (not item_uom or not item_quantity) and plan_block:
            item_uom, item_quantity = _world_bank_item_measure(plan_block)
            item_measure_note = (
                "item_measure_source=World Bank STEP description"
                if item_uom and item_quantity
                else "item_measure_source=not_exposed"
            )
        item_no, item_no_source = _world_bank_item_no(description)
        row = OutputRow(
            source="World Bank Project Procurement Contract Awards in Health sector",
            country="Egypt",
            country_cc="EG",
            publication_date=publication_date,
            closing_date="",
            title=description,
            description=project,
            buyer="",
            classification=source_row.get("procurement_method", ""),
            status="Awarded",
            currency="USD" if amount else "",
            amount=amount,
            awarding_supplier_name=_clean(source_row.get("supplier", "")),
            awarded_currency="USD" if amount else "",
            awarded_value=amount,
            contract_period=contract_period,
            item_no=item_no,
            item_desc=description,
            item_uom=item_uom,
            item_quantity=item_quantity,
            item_award=signing_date,
            notice_id=contract_number or reference,
            notice_url=WB_HEALTH_AWARDS_CSV,
            query_text=(
                f"{query_text}; borrower_reference={reference}; {publication_note}; {item_measure_note}; "
                f"item_no_source={item_no_source}"
                if reference
                else f"{query_text}; {publication_note}; {item_measure_note}; item_no_source={item_no_source}"
            ),
            scraped_at=scraped_at,
            dedup_key=f"world_bank_health_awards|EG|{contract_number or reference}",
        ).to_dict()
        rows.append(row)
    return rows


def _coverage(rows: list[dict[str, str]]) -> dict[str, object]:
    return {
        "rows": len(rows),
        "nonblank_by_required_user_field": {
            label: sum(1 for row in rows if any(row.get(field) for field in fields))
            for label, fields in REQUIRED_USER_FIELD_GROUPS.items()
        },
        "rows_with_all_required_user_fields": sum(
            1
            for row in rows
            if all(any(row.get(field) for field in fields) for fields in REQUIRED_USER_FIELD_GROUPS.values())
        ),
    }


def _write_rows_csv_with_lock_fallback(path: Path, rows: list[dict[str, str]]) -> Path:
    try:
        return write_rows_csv(path, rows)
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_refreshed{path.suffix}")
        return write_rows_csv(fallback, rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape best available Egypt awarded medical procurement sources.")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--output-dir", default="Egypt")
    parser.add_argument("--evidence-dir", default="evidence/egypt_awarded_probe_2026_06_24")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-gcs-pages", type=int, default=None)
    parser.add_argument("--skip-live-gcs", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_root = Path(args.output_dir)
    evidence_dir = Path(args.evidence_dir)
    stamp = args.end_date.replace("-", "_")

    gcs_rows: list[dict[str, str]] = []
    if not args.skip_live_gcs:
        gcs_rows = scrape_gcs_awarded(
            evidence_dir=evidence_dir,
            timeout=args.timeout,
            max_pages=args.max_gcs_pages,
            query_text=f"live:gcs-awarded-status:{args.start_date}_to_{args.end_date}",
        )

    gcs_medical_rows = [row for row in gcs_rows if _is_medical(row)]
    wb_procurement_plan_text = _world_bank_plan_text(evidence_dir=evidence_dir, timeout=args.timeout)
    wb_rows = scrape_world_bank_health_awards(
        start_date=args.start_date,
        end_date=args.end_date,
        timeout=args.timeout,
        query_text=f"live:world-bank-health-awards:EG:{args.start_date}_to_{args.end_date}",
        procurement_plan_text=wb_procurement_plan_text,
    )
    wb_publication_window_rows = [
        row for row in wb_rows if args.start_date <= row.get("publication_date", "") <= args.end_date
    ]

    gcs_dir = output_root / "gcs-digitalegypt-gov-eg"
    wb_dir = output_root / "world-bank-health-awards"
    gcs_path = _write_rows_csv_with_lock_fallback(gcs_dir / f"awarded_rows_{args.start_date}_to_{stamp}.csv", gcs_rows)
    gcs_medical_path = _write_rows_csv_with_lock_fallback(
        gcs_dir / f"medical_awarded_rows_{args.start_date}_to_{stamp}.csv",
        gcs_medical_rows,
    )
    wb_path = _write_rows_csv_with_lock_fallback(
        wb_dir / f"medical_awarded_contracts_{args.start_date}_to_{stamp}.csv",
        wb_rows,
    )
    wb_publication_window_path = _write_rows_csv_with_lock_fallback(
        wb_dir / f"medical_awarded_contracts_publication_window_{args.start_date}_to_{stamp}.csv",
        wb_publication_window_rows,
    )
    gcs_latest_path = _write_rows_csv_with_lock_fallback(gcs_dir / "awarded_rows_latest.csv", gcs_rows)
    gcs_medical_latest_path = _write_rows_csv_with_lock_fallback(
        gcs_dir / "medical_awarded_rows_latest.csv",
        gcs_medical_rows,
    )
    wb_latest_path = _write_rows_csv_with_lock_fallback(
        wb_dir / "medical_awarded_contracts_latest.csv",
        wb_rows,
    )
    wb_publication_window_latest_path = _write_rows_csv_with_lock_fallback(
        wb_dir / "medical_awarded_contracts_publication_window_latest.csv",
        wb_publication_window_rows,
    )

    summary = {
        "run_date": args.end_date,
        "start_date": args.start_date,
        "evidence_dir": str(evidence_dir),
        "outputs": {
            "gcs_awarded_rows": str(gcs_path),
            "gcs_medical_awarded_rows": str(gcs_medical_path),
            "world_bank_medical_awarded_contracts": str(wb_path),
            "world_bank_medical_awarded_contracts_publication_window": str(wb_publication_window_path),
            "latest_gcs_awarded_rows": str(gcs_latest_path),
            "latest_gcs_medical_awarded_rows": str(gcs_medical_latest_path),
            "latest_world_bank_medical_awarded_contracts": str(wb_latest_path),
            "latest_world_bank_medical_awarded_contracts_publication_window": str(
                wb_publication_window_latest_path
            ),
        },
        "coverage": {
            "gcs_awarded_rows": _coverage(gcs_rows),
            "gcs_medical_awarded_rows": _coverage(gcs_medical_rows),
            "world_bank_medical_awarded_contracts": _coverage(wb_rows),
            "world_bank_medical_awarded_contracts_publication_window": _coverage(wb_publication_window_rows),
        },
        "source_findings": {
            "gcs": "Public award-stage rows expose award date, contract period, item description, UOM, and quantity, but not winning supplier or awarded value.",
            "upa": "Live recheck returned HTTP 500 WordPress critical error at /tenders/; prior public pages had CAPTCHA-gated item booklets.",
            "world_bank": (
                "Official health-sector contract awards expose Egypt supplier, USD awarded value, and contract signing date. "
                "The World Bank STEP procurement plan can enrich many rows with signed-contract and completion dates. "
                "Descriptions that state a measurable lot, such as '( one lot )', can also populate item UOM and quantity from official award text."
            ),
        },
    }
    summary_path = output_root / f"egypt_awarded_medical_probe_summary_{stamp}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
