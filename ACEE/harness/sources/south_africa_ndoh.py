from __future__ import annotations

import re
import subprocess
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests import RequestException

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES


CONFIG = SOURCES["south_africa_ndoh"]
TENDERS_URL = "https://www.health.gov.za/tenders/"
EVIDENCE_HTML_PATH = Path("evidence") / "ndoh_tenders_page_live.html"
EVIDENCE_AWARD_NOTICE_PATH = Path("evidence") / "NDOH_03_2024_2025.pdf"
REQUEST_TIMEOUT_SECONDS = 60
MEDICAL_PATTERNS = (
    r"\bmedical\b",
    r"\bhealth\b",
    r"\bclinic\b",
    r"\bhospital\b",
    r"\bdiagnostic\b",
    r"\bmalaria\b",
    r"\bopioid\b",
    r"\bost\b",
    r"\bhiv\b",
    r"\btb\b",
    r"\btuberculosis\b",
    r"\bmedicine\b",
    r"\bdrug\b",
    r"\bconsumables\b",
    r"\btesting devices?\b",
    r"\bpoint of care\b",
    r"\bcommunity health\b",
    r"\bhealth workers?\b",
    r"\borthotic\b",
    r"\bprosthetic\b",
)
NON_MEDICAL_PATTERNS = (
    r"\bcleaning and hygiene services at the national department of health, pretoria head office\b",
    r"\bplacement of advertisements\b",
    r"\bstorage and electronic retrieval\b",
)
DESCRIPTION_CUTOFF_PATTERNS = (
    r"\bcompulsory briefing session\b",
    r"\bcompulsory virtual briefing session\b",
    r"\bcompulsory briefing\b",
    r"\bpricing schedule\b",
    r"\blink to join\b",
)


def _fetch_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def _fetch_binary(url: str) -> bytes:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def _award_notice_evidence_path(award_notice_url: str) -> Path:
    match = re.search(r"NDOH-(\d+)-(\d{4})-(\d{4})", award_notice_url, re.I)
    suffix = Path(award_notice_url).suffix.lower()
    if match:
        return Path("evidence") / f"NDOH_{match.group(1)}_{match.group(2)}_{match.group(3)}{suffix}"
    return Path("evidence") / Path(award_notice_url).name


def _load_tenders_html() -> str:
    try:
        html = _fetch_text(TENDERS_URL)
        EVIDENCE_HTML_PATH.write_text(html, encoding="utf-8")
        return html
    except RequestException:
        return EVIDENCE_HTML_PATH.read_text(encoding="utf-8", errors="replace")


def _parse_date(value: str) -> str:
    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    match = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", cleaned)
    if not match:
        return ""
    return datetime.strptime(match.group(1), "%d %B %Y").date().isoformat()


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _is_medical_row(description: str) -> bool:
    text = normalize_text(description).lower()
    if _matches_any(NON_MEDICAL_PATTERNS, text):
        return False
    return _matches_any(MEDICAL_PATTERNS, text)


def _clean_tender_description(description: str) -> str:
    cleaned = normalize_text(description)
    for pattern in DESCRIPTION_CUTOFF_PATTERNS:
        match = re.search(pattern, cleaned, re.I)
        if match:
            cleaned = normalize_text(cleaned[: match.start()])
            break
    return cleaned.rstrip(" .;:-")


def _fallback_item_desc(description: str) -> str:
    cleaned = _clean_tender_description(description)
    cleaned = re.sub(r"^(appointment of (?:an?|the)\s+service provider\s+(?:for|to)\s+)", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^(request for interested\s+)", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^the\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bfor the national department of health\b.*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bover a period of\b.*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bfor a period of\b.*$", "", cleaned, flags=re.I)
    return normalize_text(cleaned.rstrip(" .;:-"))


def _parse_tender_rows(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        columns = [" ".join(td.get_text(" ", strip=True).split()) for td in tds[:5]]
        award_links = [
            urljoin(TENDERS_URL, a.get("href", ""))
            for a in tds[4].find_all("a", href=True)
            if "award notice" in " ".join(a.get_text(" ", strip=True).split()).lower()
        ]
        if not award_links:
            continue
        rows.append(
            {
                "notice_id": normalize_text(columns[0]),
                "description": normalize_text(columns[1]),
                "publication_date": _parse_date(columns[2]),
                "closing_date": _parse_date(columns[3]),
                "award_notice_url": award_links[0],
            }
        )
    return rows


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_doc_text(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)

    script = (
        "$ErrorActionPreference='Stop';"
        "$word=New-Object -ComObject Word.Application;"
        "$word.Visible=$false;"
        f"$doc=$word.Documents.Open('{tmp_path.as_posix()}', $false, $true);"
        "$text=$doc.Content.Text;"
        "$doc.Close();"
        "$word.Quit();"
        "Write-Output $text"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return result.stdout
    finally:
        tmp_path.unlink(missing_ok=True)


def _normalize_currency_amount(value: str) -> str:
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


def _split_supplier_and_item(leading: str) -> tuple[str, str]:
    suffix_pattern = re.compile(r"(\(PTY\)\s+LTD\.?|PTY\s+LTD\.?|SOC\s+LTD\.?|LTD\.?|LIMITED)", re.I)
    matches = list(suffix_pattern.finditer(leading))
    if not matches:
        return normalize_text(leading), ""
    split_index = matches[-1].end()
    supplier = normalize_text(leading[:split_index])
    item = normalize_text(leading[split_index:])
    return supplier, item


def _extract_contract_phrase(text: str) -> str:
    match = re.search(
        r"(?:\bof\s+)?([A-Za-z-]+(?:\s+[A-Za-z-]+)?(?:\s+\(\d{1,2}\))?\s+(?:months?|years?))",
        text,
        re.I,
    )
    return normalize_text(match.group(1)) if match else ""


def _parse_award_notice_records(text: str) -> List[Dict[str, str]]:
    lines = []
    for raw_line in text.splitlines():
        cleaned_line = re.sub(r"[\x00-\x1f]+", " ", raw_line)
        normalized_line = normalize_text(cleaned_line)
        if normalized_line:
            lines.append(normalized_line)
    start_index = 0
    for index, line in enumerate(lines):
        if "contract period" in line.lower():
            start_index = index + 1
            break
    data_lines = []
    for line in lines[start_index:]:
        if line.lower().startswith("reference no"):
            break
        data_lines.append(line)

    merged_rows: List[str] = []
    buffer: List[str] = []
    for line in data_lines:
        if re.search(r"\bR\s*[\d\s.,]+", line) or re.search(r"\bN/?A\b\s+\bN/?A\b", line, re.I):
            if buffer:
                buffer.append(line)
                merged_rows.append(" ".join(buffer))
                buffer = []
            else:
                merged_rows.append(line)
            continue
        if merged_rows and re.fullmatch(r"[\d\s.,]+", line):
            merged_rows[-1] = f"{merged_rows[-1]} {line}"
            continue
        if merged_rows and _extract_contract_phrase(line):
            merged_rows[-1] = f"{merged_rows[-1]} {line}"
            continue
        buffer.append(line)
    if buffer and merged_rows:
        merged_rows[-1] = f"{merged_rows[-1]} {' '.join(buffer)}"
    elif buffer:
        merged_rows.append(" ".join(buffer))

    records: List[Dict[str, str]] = []
    row_pattern = re.compile(
        r"^(?P<leading>.+?)\s+(?:(?:R\s*(?P<value>[\d\s.,]+))|(?P<value_na>N/?A))\s+(?P<points>N/?A|\d[\d.,]*)\s+(?P<period>.+)$",
        re.I,
    )
    for row_text in merged_rows:
        match = row_pattern.search(row_text)
        if not match:
            continue
        supplier, item = _split_supplier_and_item(match.group("leading"))
        raw_value = match.group("value") or ""
        records.append(
            {
                "awarding_supplier_name": supplier,
                "awarded_value": _normalize_currency_amount(raw_value) if raw_value else "",
                "contract_period": _extract_contract_phrase(match.group("period")),
                "item_desc": item,
            }
        )
    return records


def _award_notice_records(award_notice_url: str) -> List[Dict[str, str]]:
    evidence_path = _award_notice_evidence_path(award_notice_url)
    try:
        content = _fetch_binary(award_notice_url)
        evidence_path.write_bytes(content)
    except RequestException:
        content = evidence_path.read_bytes()
    if award_notice_url.lower().endswith(".pdf"):
        text = _extract_pdf_text(content)
        return _parse_award_notice_records(text)
    if award_notice_url.lower().endswith(".doc"):
        try:
            text = _extract_doc_text(content)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        return _parse_award_notice_records(text)
    return []


def _row_to_output_rows(tender_row: Dict[str, str], award_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    output_rows: List[Dict[str, str]] = []
    cleaned_description = _clean_tender_description(tender_row["description"])
    fallback_item_desc = _fallback_item_desc(tender_row["description"])
    description_contract_period = _extract_contract_phrase(cleaned_description or tender_row["description"])
    if not award_rows:
        award_rows = [
            {
                "awarding_supplier_name": "",
                "awarded_value": "",
                "contract_period": description_contract_period,
                "item_desc": "",
            }
        ]
    for index, award in enumerate(award_rows, start=1):
        item_desc = award["item_desc"] or fallback_item_desc or cleaned_description
        row = OutputRow(
            source=CONFIG.source,
            country=CONFIG.country,
            country_cc=CONFIG.country_cc,
            publication_date=tender_row["publication_date"],
            closing_date=tender_row["closing_date"],
            title=item_desc or tender_row["notice_id"],
            description=cleaned_description or tender_row["description"],
            buyer="National Department of Health",
            classification="",
            status="Award Notice",
            currency="",
            amount=award["awarded_value"],
            awarding_supplier_name=award["awarding_supplier_name"],
            awarded_currency="ZAR" if award["awarded_value"] else "",
            awarded_value=award["awarded_value"],
            contract_period=award["contract_period"] or description_contract_period,
            item_no=str(index) if item_desc else "",
            item_desc=item_desc,
            item_uom="",
            item_quantity="",
            item_unit_price="",
            item_award=award["awarded_value"],
            notice_id=tender_row["notice_id"],
            notice_url=tender_row["award_notice_url"],
            query_text="",
            scraped_at=utc_now_iso(),
            dedup_key=f"{CONFIG.key}|{tender_row['notice_id']}|{index}",
        )
        output_rows.append(row.to_dict())
    return output_rows


def smoke_probe() -> SmokeProbeResult:
    html = EVIDENCE_HTML_PATH.read_text(encoding="utf-8", errors="replace")
    tender_rows = _parse_tender_rows(html)
    sample = next(row for row in tender_rows if row["notice_id"] == "NDOH 03-2024/2025")
    text = _extract_pdf_text(EVIDENCE_AWARD_NOTICE_PATH.read_bytes())
    award_rows = _parse_award_notice_records(text)
    rows = _row_to_output_rows(sample, award_rows)
    row = rows[0]
    ok = bool(row["notice_id"] and row["publication_date"] and row["awarding_supplier_name"] and row["awarded_value"])
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=ok,
        mode="fixture",
        detail="Mapped one saved NDoH award notice PDF and tender-row metadata from the public tenders page.",
        sample_rows=rows,
    )


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 50) -> List[Dict[str, str]]:
    del page_size
    html = _load_tenders_html()
    tender_rows = _parse_tender_rows(html)
    rows: List[Dict[str, str]] = []
    for tender_row in tender_rows:
        publication_date = tender_row["publication_date"]
        if not publication_date or publication_date < date_from or publication_date > date_to:
            continue
        if not _is_medical_row(tender_row["description"]):
            continue
        try:
            award_rows = _award_notice_records(tender_row["award_notice_url"])
        except RequestException:
            award_rows = []
        mapped_rows = _row_to_output_rows(tender_row, award_rows)
        query_text = f"live-medical-awarded:page={TENDERS_URL}:award={tender_row['award_notice_url']}"
        for mapped_row in mapped_rows:
            mapped_row["query_text"] = query_text
        rows.extend(mapped_rows)
    return rows
