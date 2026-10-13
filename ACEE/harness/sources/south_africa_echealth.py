from __future__ import annotations

import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import fitz
import requests
from bs4 import BeautifulSoup
from PIL import Image
from requests import RequestException

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.shared.serialize import read_rows_csv
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES


CONFIG = SOURCES["south_africa_echealth"]
LISTING_URL = "https://www.echealth.gov.za/index.php/tenders/tender-award-s"
DOWNLOAD_URL_TEMPLATE = "https://www.echealth.gov.za/index.php/tenders/tender-awards?task=download.send&id={id}&catid=19&m=0"
EVIDENCE_LISTING_PATH = Path("evidence") / "echealth_tender_awards_live.html"
EVIDENCE_SAMPLE_PDF_PATH = Path("evidence") / "echealth_4265_bid_awards_notice_2024_06_14.pdf"
PROBE_BACKFILL_PATH = Path("South Africa") / "echealth-gov-za" / "probe_medical_awarded_2024_01_01_to_2024_12_31.csv"
REQUEST_TIMEOUT_SECONDS = 25
TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
ENTRY_MEDICAL_PATTERNS = (
    r"\bpharmaceutical\b",
    r"\bpe pharmaceutical depot\b",
)
ROW_MEDICAL_PATTERNS = (
    r"\bpharmaceutical\b",
    r"\bmedical\b",
    r"\bsurgical\b",
    r"\banti-?infective\b",
    r"\bazithromycin\b",
    r"\bvalproate\b",
    r"\bwound\b",
    r"\bwater for injection\b",
    r"\binsulin\b",
    r"\bostomy\b",
    r"\bgauze\b",
    r"\bchlorhexidine\b",
    r"\binjection\b",
    r"\bsyringe\b",
    r"\bneedle\b",
)
ENTRY_EXCLUDE_PATTERNS = (
    r"\bclosing register\b",
    r"\bclosed bid\b",
    r"\bhygiene services\b",
    r"\blifting and handling equipment\b",
    r"\bpallets?\b",
)
CONTRACT_NUMBER_RE = re.compile(r"\bSCMU3-[A-Z0-9/]+-\d{4}-[A-Z]+\b", re.I)
CONTRACT_PREFIX_RE = re.compile(r"(SCMU3-[A-Z0-9/]+-)", re.I)
CONTRACT_SUFFIX_RE = re.compile(r"^(\d{4}-[A-Z]+):?\b", re.I)
DATE_RE = re.compile(r"\b\d{1,2}-[A-Za-z]{3}-\d{2}\b")
_PROBE_BACKFILL_INDEX: Dict[tuple[str, str], Dict[str, str]] | None = None


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


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


def _parse_listing_entries(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[Dict[str, str]] = []
    for title_div in soup.select("div.jd_download_title"):
        title_link = title_div.find("a", href=True)
        if not title_link:
            continue
        summary_url = urljoin(LISTING_URL, title_link.get("href", ""))
        match = re.search(r"/summary/\d+-tender-awards/(\d+)-", summary_url)
        if not match:
            continue

        wrapper_clear = title_div.find_next_sibling("div", class_="jd_clear")
        wrapper = wrapper_clear.find_next_sibling("div", class_="jd_download_wrapper") if wrapper_clear else None
        created = ""
        if wrapper:
            wrapper_text = normalize_text(wrapper.get_text(" ", strip=True))
            created_match = re.search(r"Created:\s*(\d{4}-\d{2}-\d{2})", wrapper_text)
            if created_match:
                created = created_match.group(1)

        title = normalize_text(re.sub(r"\bHOT\b", "", title_div.get_text(" ", strip=True), flags=re.I))
        download_id = match.group(1)
        entries.append(
            {
                "download_id": download_id,
                "title": title,
                "publication_date": created,
                "summary_url": summary_url,
                "notice_url": DOWNLOAD_URL_TEMPLATE.format(id=download_id),
            }
        )
    return entries


def _entry_is_target(entry: Dict[str, str], date_from: str, date_to: str) -> bool:
    publication_date = entry.get("publication_date", "")
    title = entry.get("title", "")
    title_text = title.lower()
    if not publication_date or publication_date < date_from or publication_date > date_to:
        return False
    if not re.search(r"\bawards?\b|\bawarded\b|\bresponses\b", title_text, re.I):
        return False
    if _matches_any(ENTRY_EXCLUDE_PATTERNS, title_text):
        return False
    return _matches_any(ENTRY_MEDICAL_PATTERNS, title_text)


def _load_notice_pdf(download_id: str) -> bytes | None:
    evidence_path = Path("evidence") / f"echealth_{download_id}.pdf"
    try:
        content = _fetch_binary(DOWNLOAD_URL_TEMPLATE.format(id=download_id))
        evidence_path.write_bytes(content)
        return content
    except RequestException:
        if evidence_path.exists():
            return evidence_path.read_bytes()
        return None


def _ocr_pdf_text(content: bytes) -> str:
    if not TESSERACT_EXE.exists():
        raise FileNotFoundError(f"Tesseract not found at {TESSERACT_EXE}")

    text_chunks: List[str] = []
    with tempfile.TemporaryDirectory(prefix="echealth_ocr_") as tmpdir:
        doc = fitz.open(stream=content, filetype="pdf")
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            image_path = Path(tmpdir) / f"page_{page_index + 1}.png"
            rotated_path = Path(tmpdir) / f"page_{page_index + 1}_rotcw.png"
            out_base = Path(tmpdir) / f"page_{page_index + 1}_ocr"

            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pix.save(image_path)
            Image.open(image_path).rotate(-90, expand=True).save(rotated_path)

            subprocess.run(
                [str(TESSERACT_EXE), str(rotated_path), str(out_base), "--psm", "6"],
                check=True,
                capture_output=True,
            )
            text_chunks.append(out_base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace"))
    return "\n".join(text_chunks)


def _normalize_notice_text(text: str) -> str:
    normalized = text.replace("â€œ", '"').replace("â€", '"').replace("Â«", "").replace("Â»", "")
    normalized = normalized.replace("P_E.", "P.E.")
    return normalized


def _extract_contract_period(description: str) -> str:
    match = re.search(
        r"(?:For A Period Of|Period Of)\s+(.+?)\s+Months?",
        description,
        re.I,
    )
    if not match:
        return ""
    phrase = normalize_text(match.group(1))
    phrase = phrase.replace("Twenty -Four", "Twenty-Four")
    phrase = phrase.replace("(S)", "(5)")
    return normalize_text(f"{phrase} months")


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


def _extract_amount_hint_from_description(description: str) -> str:
    match = re.search(
        r"will\s+not\s+exceed\s+the\s+value\s+of\s+R\s*([\d\s.,]+)",
        description,
        re.I,
    )
    if not match:
        return ""
    return _normalize_amount(match.group(1))


def _probe_backfill_index() -> Dict[tuple[str, str], Dict[str, str]]:
    global _PROBE_BACKFILL_INDEX
    if _PROBE_BACKFILL_INDEX is not None:
        return _PROBE_BACKFILL_INDEX
    index: Dict[tuple[str, str], Dict[str, str]] = {}
    if PROBE_BACKFILL_PATH.exists():
        for row in read_rows_csv(PROBE_BACKFILL_PATH):
            key = (
                normalize_text(row.get("notice_id")).upper(),
                normalize_text(row.get("awarding_supplier_name")).lower(),
            )
            if all(key):
                index[key] = row
    _PROBE_BACKFILL_INDEX = index
    return index


def _extract_item_desc(description: str) -> str:
    paren_match = re.search(r"\(([^()]{3,200})\)", description)
    if paren_match:
        return _clean_item_desc(paren_match.group(1))
    item_text = re.sub(r"\bFor A Period Of\b.*$", "", description, flags=re.I)
    item_text = re.sub(r"^Procurement Of\s+", "", item_text, flags=re.I)
    return _clean_item_desc(item_text.strip(" ."))


def _is_medical_description(description: str, title: str) -> bool:
    if _matches_any(ENTRY_EXCLUDE_PATTERNS, description.lower()):
        return False
    return _matches_any(ROW_MEDICAL_PATTERNS, description.lower())


def _parse_bidder_fields(tail: str) -> tuple[str, str, str, str]:
    cleaned = normalize_text(tail.replace("|", " "))
    amount = ""
    amount_match = re.search(r"R\s*[\d\s.,]+$", cleaned)
    if amount_match:
        amount = _normalize_amount(amount_match.group(0))
        cleaned = normalize_text(cleaned[: amount_match.start()])

    bidder = cleaned
    points = ""
    contract_type = ""
    match = re.search(
        r"^(?P<bidder>.+?)\s+(?P<points>\d{1,3}[.,]\d{2})\s+(?P<ctype>Rate(?:\s+Based)?|based|Rate)$",
        cleaned,
        re.I,
    )
    if match:
        bidder = normalize_text(match.group("bidder"))
        points = normalize_text(match.group("points"))
        contract_type = normalize_text(match.group("ctype"))
    else:
        match = re.search(r"^(?P<bidder>.+?)\s+(?P<ctype>Rate(?:\s+Based)?|based|Rate)$", cleaned, re.I)
        if match:
            bidder = normalize_text(match.group("bidder"))
            contract_type = normalize_text(match.group("ctype"))
        else:
            bidder = normalize_text(cleaned)

    if contract_type.lower() == "based":
        contract_type = "Rate Based"
    elif contract_type.lower() == "rate":
        contract_type = "Rate"
    return bidder, points, contract_type, amount


def _repair_description_and_bidder(description: str, bidder: str) -> tuple[str, str]:
    description = normalize_text(re.split(r"rate base means", description, flags=re.I)[0])
    description = description.replace("{", "(").replace("}", ")")
    description = re.sub(r"\bos\b", "", description, flags=re.I)
    match = re.search(
        r"\bPort Elizabeth\s+(?P<extra>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\s+Pharmaceutical Depot\b",
        description,
    )
    if match and bidder.lower().endswith(" and"):
        bidder = normalize_text(f"{bidder} {match.group('extra')}")
        description = normalize_text(description.replace(match.group(0), "Port Elizabeth Pharmaceutical Depot"))
    if bidder.lower().endswith(" and") and "Distributors SA" in description:
        bidder = normalize_text(f"{bidder} Distributors SA")
        description = normalize_text(description.replace("Distributors SA ", "", 1))
    bidder = normalize_text(bidder.replace("tmporters", "Importers"))
    description = normalize_text(description.replace("tmporters", "Importers"))
    return description, bidder


def _clean_item_desc(value: str) -> str:
    cleaned = normalize_text(value)
    cleaned = cleaned.replace("tmporters", "Importers")
    cleaned = cleaned.replace("Based Needle", "Needle")
    cleaned = cleaned.replace("Anti- Infective", "Anti-Infective")
    cleaned = re.sub(r"^Non-Contracted Surgical Supplies\)?\s+Of\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^Non-Contracted Pharmaceutical\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^Non-Contracted Non Pharmaceutical Items\.?\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.replace("( ", "(").replace(" )", ")")
    return normalize_text(cleaned.strip(" ."))


def _extract_row_blocks(text: str) -> List[Dict[str, List[str]]]:
    lines = [normalize_text(line) for line in _normalize_notice_text(text).splitlines()]
    lines = [line for line in lines if line]
    blocks: List[Dict[str, List[str]]] = []
    carry_desc: List[str] = []
    in_table = False
    index = 0
    while index < len(lines):
        line = lines[index]
        lower_line = line.lower()
        if "contract description" in lower_line and "bidder" in lower_line:
            in_table = True
            carry_desc = []
            index += 1
            continue
        if not in_table:
            index += 1
            continue
        if lower_line.startswith("rate base means") or lower_line.startswith("mr ") or "chairperson" in lower_line:
            break
        if "scmu3-" in lower_line:
            row_lines = [line]
            saw_suffix_line = False
            index += 1
            while index < len(lines):
                next_line = lines[index]
                next_lower = next_line.lower()
                if "scmu3-" in next_lower or "rate base means" in next_lower or next_lower.startswith("mr "):
                    break
                if saw_suffix_line and re.match(r"^(procurement of|supply and|appointment of)", next_lower):
                    break
                row_lines.append(next_line)
                if CONTRACT_SUFFIX_RE.match(next_line):
                    saw_suffix_line = True
                index += 1
            blocks.append({"pre_lines": carry_desc, "row_lines": row_lines})
            carry_desc = []
            continue
        if lower_line == "period award claimed":
            index += 1
            continue
        carry_desc.append(line)
        index += 1
    return blocks


def _parse_notice_rows(entry: Dict[str, str], notice_text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for block in _extract_row_blocks(notice_text):
        description_parts = list(block["pre_lines"])
        tail_parts: List[str] = []
        notice_id = ""
        row_lines = block["row_lines"]
        prefix_match = CONTRACT_PREFIX_RE.search(row_lines[0])
        if not prefix_match:
            continue
        contract_prefix = normalize_text(prefix_match.group(1))

        first_line = normalize_text(row_lines[0].replace(prefix_match.group(1), "", 1))
        first_date_match = DATE_RE.search(first_line)
        if first_date_match:
            description_parts.append(first_line[: first_date_match.start()])
            tail_parts.append(first_line[first_date_match.end() :])
        else:
            description_parts.append(first_line)

        for line in row_lines[1:]:
            suffix_match = CONTRACT_SUFFIX_RE.match(line)
            working_line = line
            if suffix_match and not notice_id:
                notice_id = normalize_text(f"{contract_prefix}{suffix_match.group(1)}")
                working_line = normalize_text(line[suffix_match.end() :])
            date_match = DATE_RE.search(working_line)
            if date_match:
                description_parts.append(working_line[: date_match.start()])
                tail_parts.append(working_line[date_match.end() :])
            else:
                description_parts.append(working_line)

        if not notice_id:
            full_id_match = CONTRACT_NUMBER_RE.search(" ".join(row_lines))
            if full_id_match:
                notice_id = normalize_text(full_id_match.group(0))
        if not notice_id:
            continue

        description = normalize_text(" ".join(description_parts))
        description = re.sub(r"\b\d{1,2}\s*$", "", description).strip()
        tail = normalize_text(" ".join(tail_parts).strip(" |"))
        bidder, _points, contract_type, raw_amount = _parse_bidder_fields(tail)
        description, bidder = _repair_description_and_bidder(description, bidder)
        contract_period = _extract_contract_period(description)
        item_desc = _extract_item_desc(description)
        if not bidder or not description or not _is_medical_description(description, entry["title"]):
            continue

        amount_value = raw_amount or _extract_amount_hint_from_description(description)
        awarded_value = amount_value
        if amount_value == "999999.99":
            awarded_value = ""

        row = OutputRow(
            source=CONFIG.source,
            country=CONFIG.country,
            country_cc=CONFIG.country_cc,
            publication_date=entry["publication_date"],
            title=item_desc or description,
            description=description,
            buyer="Eastern Cape Department of Health / PE Pharmaceutical Depot",
            status="awarded",
            currency="ZAR",
            amount=amount_value,
            awarding_supplier_name=bidder,
            awarded_currency="ZAR" if awarded_value else "",
            awarded_value=awarded_value,
            contract_period=contract_period,
            item_desc=item_desc or description,
            notice_id=notice_id,
            notice_url=entry["notice_url"],
            query_text=entry["title"],
            scraped_at=utc_now_iso(),
            dedup_key="|".join(
                [
                    CONFIG.source,
                    notice_id,
                    normalize_text(item_desc or description).lower(),
                    normalize_text(bidder).lower(),
                ]
            ),
        ).to_dict()
        rows.append(row)
    return rows


def _sample_rows_from_evidence() -> List[Dict[str, str]]:
    content = EVIDENCE_SAMPLE_PDF_PATH.read_bytes()
    entry = {
        "download_id": "4265",
        "title": "PE PHARMACEUTICAL DEPOT AWARDED BIDS",
        "publication_date": "2024-06-19",
        "notice_url": DOWNLOAD_URL_TEMPLATE.format(id="4265"),
    }
    return _parse_notice_rows(entry, _ocr_pdf_text(content))


def normalize_saved_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    backfill = _probe_backfill_index()
    normalized_rows: List[Dict[str, str]] = []
    for row in rows:
        normalized = dict(row)
        if not normalize_text(normalized.get("amount")):
            key = (
                normalize_text(normalized.get("notice_id")).upper(),
                normalize_text(normalized.get("awarding_supplier_name")).lower(),
            )
            evidence_row = backfill.get(key)
            if evidence_row:
                evidence_amount = normalize_text(evidence_row.get("amount")) or normalize_text(evidence_row.get("awarded_value"))
                if not evidence_amount:
                    evidence_amount = _extract_amount_hint_from_description(normalize_text(evidence_row.get("description")))
                if evidence_amount:
                    normalized["amount"] = _normalize_amount(evidence_amount)
                    if not normalize_text(normalized.get("currency")):
                        normalized["currency"] = "ZAR"
        normalized_rows.append(normalized)
    return normalized_rows


def smoke_probe() -> SmokeProbeResult:
    try:
        sample_rows = _sample_rows_from_evidence()
    except FileNotFoundError as exc:
        return SmokeProbeResult(
            source_key=CONFIG.key,
            ok=False,
            mode="evidence_missing",
            detail=str(exc),
            sample_rows=[],
        )

    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=bool(sample_rows),
        mode="evidence_pdf_ocr",
        detail="Parsed saved Eastern Cape pharmaceutical award notice OCR sample.",
        sample_rows=sample_rows[:2],
    )


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 50) -> List[Dict[str, str]]:
    del page_size
    html = _load_listing_html()
    rows: List[Dict[str, str]] = []
    for entry in _parse_listing_entries(html):
        if not _entry_is_target(entry, date_from, date_to):
            continue
        content = _load_notice_pdf(entry["download_id"])
        if not content:
            continue
        notice_text = _ocr_pdf_text(content)
        rows.extend(_parse_notice_rows(entry, notice_text))
    return rows
