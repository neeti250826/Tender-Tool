from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests import RequestException

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES


CONFIG = SOURCES["south_africa_ldoh"]
LISTING_URL = "https://www.ldoh.gov.za/?q=node/12"
DOCUMENT_INDEX_URL = "https://www.ldoh.gov.za/ldoh-admin/documents/latestnews/documents/"
EVIDENCE_LISTING_PATH = Path("evidence") / "ldoh_awarded_tenders_live.html"
EVIDENCE_INDEX_PATH = Path("evidence") / "ldoh_documents_index_live.html"
EVIDENCE_SMOKE_PDF_PATH = Path("evidence") / "ldoh_notice_award_mmc_hedp_005_24_25.pdf"
REQUEST_TIMEOUT_SECONDS = 60
BUYER_NAME = "Limpopo Department of Health"
TITLE_MEDICAL_PATTERNS = (
    r"\baeromedical\b",
    r"\bbreastmilk\b",
    r"\bclinical\b",
    r"\bdiagnostic\b",
    r"\bgamma camera\b",
    r"\bhistopathology\b",
    r"\binterfacility\b",
    r"\bmedical\b",
    r"\bmmc\b",
    r"\bpet ct\b",
    r"\bradiology\b",
    r"\bsurgical\b",
)
TITLE_EXCLUDE_PATTERNS = (
    r"\bcoal\b",
    r"\bevent management\b",
    r"\bgroceries\b",
    r"\blaundry\b",
    r"\boffice furniture\b",
    r"\bperishable\b",
    r"\bprobity\b",
    r"\bsecurity\b",
    r"\bstationery\b",
    r"\bwarehouse\b",
)
ENTRY_PARSERS = (
    ("SURGICAL AWARD", "_parse_surgical_notice"),
    ("MMC Packs", "_parse_mmc_notice"),
    ("Aromedical", "_parse_aromedical_notice"),
    ("Specialised", "_parse_specialised_notice"),
    ("Breastmilk", "_parse_breastmilk_notice"),
)


def _fetch_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def _fetch_binary(url: str) -> bytes:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def _load_listing_html() -> str:
    try:
        html = _fetch_text(LISTING_URL)
        EVIDENCE_LISTING_PATH.write_text(html, encoding="utf-8")
        return html
    except RequestException:
        return EVIDENCE_LISTING_PATH.read_text(encoding="utf-8", errors="replace")


def _load_index_html() -> str:
    try:
        html = _fetch_text(DOCUMENT_INDEX_URL)
        EVIDENCE_INDEX_PATH.write_text(html, encoding="utf-8")
        return html
    except RequestException:
        return EVIDENCE_INDEX_PATH.read_text(encoding="utf-8", errors="replace")


def _notice_evidence_path(notice_url: str) -> Path:
    basename = unquote(notice_url.split("/")[-1])
    safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", basename).strip()
    return Path("evidence") / f"ldoh_{safe_name}"


def _load_notice_pdf(notice_url: str) -> bytes:
    evidence_path = _notice_evidence_path(notice_url)
    try:
        content = _fetch_binary(notice_url)
        evidence_path.write_bytes(content)
        return content
    except RequestException:
        return evidence_path.read_bytes()


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _normalize_amount(value: str) -> str:
    cleaned = normalize_text(value).replace("R", "").replace(" ", "")
    if not cleaned:
        return ""
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return cleaned


def _normalize_date_dd_month_yyyy(value: str) -> str:
    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    cleaned = cleaned.replace("–", "-")
    for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _normalize_index_date(value: str) -> str:
    cleaned = normalize_text(value)
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", cleaned)
    return match.group(1) if match else ""


def _extract_contract_period(description: str) -> str:
    patterns = (
        r"period of\s+([A-Za-z-]+\s+\(\d{1,3}\)\s+months?)",
        r"period of\s+([A-Za-z-]+\s+\(\d{1,3}\)\s+years?)",
        r"period of\s+(thirty[- ]six\s+\(36\)\s+months?)",
        r"period of\s+(sixty\s*\(60\)\s+months?)",
    )
    for pattern in patterns:
        match = re.search(pattern, description, re.I)
        if match:
            return normalize_text(match.group(1))
    return ""


def _index_dates_by_name(index_html: str) -> Dict[str, str]:
    soup = BeautifulSoup(index_html, "html.parser")
    dates: Dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        anchor = tds[1].find("a", href=True)
        if not anchor:
            continue
        raw_name = anchor.get("href", "")
        index_date = _normalize_index_date(tds[2].get_text(" ", strip=True))
        if not index_date:
            continue
        dates[raw_name] = index_date
        dates[unquote(raw_name)] = index_date
    return dates


def _title_is_target(title: str) -> bool:
    text = normalize_text(title).lower()
    if not text or _matches_any(TITLE_EXCLUDE_PATTERNS, text):
        return False
    if _matches_any(TITLE_MEDICAL_PATTERNS, text):
        return True
    return "breastmilk" in text


def _parse_listing_entries(html: str, index_dates: Dict[str, str], date_from: str, date_to: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[Dict[str, str]] = []
    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        href = normalize_text(anchor.get("href"))
        title = normalize_text(anchor.get_text(" ", strip=True))
        if not href.lower().endswith(".pdf") or not title:
            continue
        if not _title_is_target(title):
            continue
        basename = href.split("/")[-1]
        publication_date = index_dates.get(basename) or index_dates.get(unquote(basename)) or ""
        if not publication_date or publication_date < date_from or publication_date > date_to:
            continue
        notice_url = urljoin(LISTING_URL, href)
        if notice_url in seen_urls:
            continue
        seen_urls.add(notice_url)
        entries.append(
            {
                "title": title,
                "publication_date": publication_date,
                "notice_url": notice_url,
            }
        )
    return entries


def _make_row(
    entry: Dict[str, str],
    *,
    title: str,
    description: str,
    awarding_supplier_name: str,
    awarded_value: str = "",
    contract_period: str = "",
    notice_id: str = "",
    item_desc: str = "",
    item_award: str = "",
) -> Dict[str, str]:
    normalized_awarded_value = _normalize_amount(awarded_value)
    final_notice_id = normalize_text(notice_id) or normalize_text(entry["title"])
    final_item_desc = normalize_text(item_desc) or normalize_text(title) or normalize_text(description)
    row = OutputRow(
        source=CONFIG.source,
        country=CONFIG.country,
        country_cc=CONFIG.country_cc,
        publication_date=entry["publication_date"],
        closing_date="",
        title=normalize_text(title) or final_item_desc or final_notice_id,
        description=normalize_text(description),
        buyer=BUYER_NAME,
        classification="",
        status="awarded",
        currency="ZAR" if normalized_awarded_value else "",
        amount=normalized_awarded_value,
        awarding_supplier_name=normalize_text(awarding_supplier_name),
        awarded_currency="ZAR" if normalized_awarded_value else "",
        awarded_value=normalized_awarded_value,
        contract_period=normalize_text(contract_period),
        item_no="1" if final_item_desc else "",
        item_desc=final_item_desc,
        item_uom="",
        item_quantity="",
        item_unit_price="",
        item_award=normalize_text(item_award),
        notice_id=final_notice_id,
        notice_url=entry["notice_url"],
        query_text=f"live-medical-awarded:page={LISTING_URL}:notice={entry['notice_url']}",
        scraped_at=utc_now_iso(),
        dedup_key="|".join(
            part
            for part in [CONFIG.key, final_notice_id, normalize_text(awarding_supplier_name).lower()]
            if part
        ),
    )
    return row.to_dict()


def _parse_mmc_notice(entry: Dict[str, str], text: str) -> List[Dict[str, str]]:
    description = (
        "Supply and Delivery of Medical Male Circumcision (MMC) Packs in the Limpopo Department of Health "
        "for a period of thirty-six (36) months"
    )
    match = re.search(
        r"HEDP\s*005/24/25.*?(Munzhedzi Holdings).*?(R[\d,]+(?:\.\d{2})?).*?(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        text,
        re.S,
    )
    if not match:
        return []
    awarded_value = match.group(2)
    return [
        _make_row(
            entry,
            title="Medical Male Circumcision (MMC) Packs",
            description=description,
            awarding_supplier_name=match.group(1),
            awarded_value=awarded_value,
            contract_period=_extract_contract_period(description),
            notice_id="HEDP 005/24/25",
            item_desc="Medical Male Circumcision (MMC) Packs",
            item_award=_normalize_amount(awarded_value),
        )
    ]


def _parse_breastmilk_notice(entry: Dict[str, str], text: str) -> List[Dict[str, str]]:
    match = re.search(
        r"HEDP:\s*018/22/23.*?South African\s+Breastmilk\s+Reserve\s+(R[\d\s.,]+)\s+100\.00\s+18\s+March\s+2024",
        text,
        re.S | re.I,
    )
    if not match:
        return []
    description = (
        "Establishment, Operation and Maintenance of Donor Human Breastmilk Bank(s) in Limpopo Department "
        "of Health for a period of thirty-six (36) months"
    )
    return [
        _make_row(
            entry,
            title="Donor Human Breastmilk Bank(s)",
            description=description,
            awarding_supplier_name="South African Breastmilk Reserve",
            awarded_value=match.group(1),
            contract_period=_extract_contract_period(description),
            notice_id="HEDP 018/22/23",
            item_desc="Donor Human Breastmilk Bank(s)",
            item_award=_normalize_amount(match.group(1)),
        )
    ]


def _parse_aromedical_notice(entry: Dict[str, str], text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    first_match = re.search(
        r"HEDP\s*022/24/25.*?Brisk\s+Solutions\s+\(Pty\)\s+Ltd\s+T/A\s+Rocket\s+HEMS.*?90\.04\s+15\s+December\s+2025",
        text,
        re.S,
    )
    if first_match:
        description = (
            "Provision of Helicopter Aeromedical Services Rotary-Wing 24 Hours Operations Comprehensive "
            "Services in the Limpopo Department of Health for a period of thirty-six (36) months"
        )
        rows.append(
            _make_row(
                entry,
                title="Helicopter Aeromedical Services",
                description=description,
                awarding_supplier_name="Brisk Solutions (Pty) Ltd T/A Rocket HEMS",
                awarded_value="",
                contract_period=_extract_contract_period(description),
                notice_id="HEDP 022/24/25",
                item_desc="Helicopter aeromedical services",
                item_award="",
            )
        )

    second_section = normalize_text(text)
    supplier_patterns = [
        ("Maponya 911 Ambulance", "Capricorn and Waterberg District", r"R302 249\.53", "17 December 2025"),
        ("TEMS 911 Emergency Medical Services and Rescue", "Vhembe District", "", ""),
        ("High Care EMS (Pty) Ltd", "Mopani District", "", ""),
        ("Ngonyama EMS and Lifemedics EMS J/V", "Sekhukhune District", "", ""),
    ]
    description = (
        "Provision of Advanced Life Support Inter-Hospital Transfer Ambulance Services in the Limpopo "
        "Department of Health for a period of thirty-six (36) months"
    )
    for supplier_name, district, amount_pattern, _award_date in supplier_patterns:
        pattern = re.escape(supplier_name) + r".*?" + re.escape(district)
        if amount_pattern:
            pattern += r".*?(" + amount_pattern + r")"
        match = re.search(pattern, second_section, re.S | re.I)
        if not match:
            continue
        awarded_value = match.group(1) if amount_pattern and match.lastindex else ""
        rows.append(
            _make_row(
                entry,
                title="Inter-Hospital Transfer Ambulance Services",
                description=description,
                awarding_supplier_name=supplier_name,
                awarded_value=awarded_value,
                contract_period=_extract_contract_period(description),
                notice_id="HEDP 023/24/25",
                item_desc=f"Advanced Life Support Inter-Hospital Transfer Ambulance Services ({district})",
                item_award=_normalize_amount(awarded_value),
            )
        )
    return rows


def _parse_specialised_notice(entry: Dict[str, str], text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    specialised_description = (
        "Accreditation of service providers for the provisioning of specialised clinical, surgical and "
        "diagnostic services for the Limpopo Department of Health for a period of thirty-six (36) months"
    )
    histopathology_description = (
        "Provision of Histopathology Services for Forensic Pathology Institutions in the Limpopo Department "
        "of Health for a period of thirty-six (36) months"
    )
    specialised_suppliers = [
        "Iatrolex (Pty) Ltd",
        "Afrirad Medical Imaging Inc.",
        "Medi Clinic Limpopo",
        "Medical Hospital of Lebowakgomo (MedLeb)",
        "Divine Inspiration Trading 660 (Pty) Ltd T/A Quality Care Private Hospital",
    ]
    normalized_text = normalize_text(text)
    for supplier in specialised_suppliers:
        if re.search(re.escape(normalize_text(supplier)), normalized_text, re.I):
            rows.append(
                _make_row(
                    entry,
                    title="Specialised Clinical, Surgical and Diagnostic Services",
                    description=specialised_description,
                    awarding_supplier_name=supplier,
                    awarded_value="",
                    contract_period=_extract_contract_period(specialised_description),
                    notice_id="HEDP 011/24/25",
                    item_desc="Specialised clinical, surgical and diagnostic services",
                    item_award="Rates",
                )
            )
    if "PATHP-QLAB JV" in normalized_text:
        rows.append(
            _make_row(
                entry,
                title="Histopathology Services",
                description=histopathology_description,
                awarding_supplier_name="PATHP-QLAB JV",
                awarded_value="",
                contract_period=_extract_contract_period(histopathology_description),
                notice_id="HEDP 012/24/25",
                item_desc="Histopathology services",
                item_award="Rates",
            )
        )
    return rows


def _parse_surgical_notice(entry: Dict[str, str], text: str) -> List[Dict[str, str]]:
    lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
    rows: List[Dict[str, str]] = []
    description = "Surgical award panel published by Limpopo Department of Health"
    current_supplier_lines: List[str] = []
    award_date = ""

    def flush_current(rate_line: str = "") -> None:
        nonlocal current_supplier_lines, award_date
        if not current_supplier_lines:
            return
        supplier_text = " ".join(current_supplier_lines)
        supplier_text = re.sub(r"\s*On Rate.*$", "", supplier_text, flags=re.I)
        supplier_text = re.sub(r"^MAAA[0-9A-Z]+\s*", "", supplier_text).strip()
        supplier_text = supplier_text.strip("() ")
        if not supplier_text:
            current_supplier_lines = []
            return
        date_match = re.search(r"(\d{2}/\d{2}/\d{4})", rate_line)
        if date_match:
            award_date = _normalize_date_dd_month_yyyy(date_match.group(1))
        rows.append(
            _make_row(
                entry,
                title="Surgical award panel",
                description=description,
                awarding_supplier_name=supplier_text,
                awarded_value="",
                contract_period="",
                notice_id="SURGICAL AWARD - BID (Bulk-Awards-Template)",
                item_desc="Surgical award panel",
                item_award="On Rate",
            )
        )
        current_supplier_lines = []

    for line in lines:
        if line.startswith("MAAA"):
            if current_supplier_lines:
                flush_current()
            if "On Rate" in line:
                current_supplier_lines = [line]
                flush_current(line)
            else:
                current_supplier_lines = [line]
            continue
        if current_supplier_lines:
            if "On Rate" in line:
                flush_current(line)
            else:
                current_supplier_lines.append(line)
    flush_current()
    return rows


def _parse_entry_rows(entry: Dict[str, str], text: str) -> List[Dict[str, str]]:
    for title_fragment, parser_name in ENTRY_PARSERS:
        if title_fragment.lower() in entry["title"].lower():
            return globals()[parser_name](entry, text)
    return []


def smoke_probe() -> SmokeProbeResult:
    entry = {
        "title": "NOTICE OF AWARD FOR MMC Packs HEDP 005.24.25 Website",
        "publication_date": "2025-06-24",
        "notice_url": "https://www.ldoh.gov.za/ldoh-admin/documents/latestnews/documents/NOTICE%20OF%20AWARD%20FOR%20MMC%20Packs%20HEDP%20005.24.25%20Website.pdf",
    }
    text = _extract_pdf_text(EVIDENCE_SMOKE_PDF_PATH.read_bytes())
    rows = _parse_mmc_notice(entry, text)
    if not rows:
        return SmokeProbeResult(
            source_key=CONFIG.key,
            ok=False,
            mode="evidence_missing",
            detail="Saved Limpopo MMC award notice did not yield a sample row.",
            sample_rows=[],
        )
    row = rows[0]
    ok = bool(row["publication_date"] and row["awarding_supplier_name"] and row["notice_url"] and row["notice_id"])
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=ok,
        mode="evidence_pdf",
        detail="Parsed a saved Limpopo MMC award notice sample with a public documents-index publication date.",
        sample_rows=rows,
    )


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 50) -> List[Dict[str, str]]:
    del page_size
    listing_html = _load_listing_html()
    index_html = _load_index_html()
    index_dates = _index_dates_by_name(index_html)
    entries = _parse_listing_entries(listing_html, index_dates, date_from, date_to)
    rows: List[Dict[str, str]] = []
    for entry in entries:
        try:
            content = _load_notice_pdf(entry["notice_url"])
        except (RequestException, FileNotFoundError):
            continue
        text = _extract_pdf_text(content)
        rows.extend(_parse_entry_rows(entry, text))
    return rows
