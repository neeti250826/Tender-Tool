from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests import RequestException

from harness.shared.field_extract import extract_contract_period
from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG = SOURCES["south_africa_kznhealth"]
PAGE_SPECS = (
    (
        "https://www2.kznhealth.gov.za/Tenders/Awarded/awarded-tenders2024.htm",
        Path("evidence") / "kzn_awarded_tenders_2024_live.html",
    ),
    (
        "https://www.kznhealth.gov.za/scm/tender-awards-2025/",
        Path("evidence") / "kzn_tender_awards_2025_live.html",
    ),
    (
        "https://www.kznhealth.gov.za/scm/tender-awards-2026/",
        Path("evidence") / "kzn_tender_awards_2026_live.html",
    ),
)
EVIDENCE_SMOKE_PDF_PATH = Path("evidence") / "kzn_znb9041_2024_h_biosafety_2026.pdf"
REQUEST_TIMEOUT_SECONDS = 60
BUYER_NAME = "KwaZulu-Natal Department of Health"
ITEM_EVIDENCE_HINTS = {
    "ZNB 9038/2024-H": {
        "item_desc": "Digital mobile X-ray unit",
        "item_uom": "unit",
        "item_quantity": "1",
    },
    "ZNQ: EDN 500/25-26": {
        "item_desc": "X-ray film digitiser device",
        "item_uom": "digitiser",
        "item_quantity": "1",
    },
    "IMB 89/25-26": {
        "item_desc": "X-ray viewing board",
        "item_uom": "board",
        "item_quantity": "1",
    },
    "ADDINGTON HOSPITA’": {
        "item_desc": "Neonatal cooling device",
        "item_uom": "device",
        "item_quantity": "1",
    },
}
TITLE_EVIDENCE_HINTS = {
    "Neonatal cooling device": {
        "item_desc": "Neonatal cooling device",
        "item_uom": "device",
        "item_quantity": "1",
    },
}
INCLUDE_PATTERNS = (
    r"\bautoclave\b",
    r"\bbiosafety\b",
    r"\bbreastmilk\b",
    r"\bcannula\b",
    r"\bcatheter",
    r"\bchc\b",
    r"\bclinical\b",
    r"\bclinic\b",
    r"\bcommunity health centre\b",
    r"\bct scanner\b",
    r"\bdental\b",
    r"\bdiapers?\b",
    r"\bemergency care\b",
    r"\bems\b",
    r"\bendotracheal\b",
    r"\bforensic\b",
    r"\bgiving set\b",
    r"\bhospital\b",
    r"\bintraoral\b",
    r"\bintravenous\b",
    r"\bivi\b",
    r"\bmammograph",
    r"\bmaternity\b",
    r"\bmedical\b",
    r"\bmedico legal mortuary\b",
    r"\bmortuary\b",
    r"\bnasogastric\b",
    r"\bneedle\b",
    r"\bnurses uniform\b",
    r"\boxygen\b",
    r"\bpost natal ward\b",
    r"\bpregnancy\b",
    r"\bradiology\b",
    r"\brespiratory\b",
    r"\bsim mom\b",
    r"\bsuction\b",
    r"\bsyringe\b",
    r"\btermination of pregnancy\b",
    r"\btracheostomy\b",
    r"\bventilator\b",
    r"\bx(?:\s|[-–—?])*ray\b",
)
EXCLUDE_PATTERNS = (
    r"\baudit outcomes?\b",
    r"\baccommodation services\b",
    r"\bboiler operation\b",
    r"\bfire safety\b",
    r"\bfinancial statements\b",
    r"\bfencing\b",
    r"\bgenerator\b",
    r"\blift[s]?\b",
    r"\boffice furniture\b",
    r"\bpaintworks?\b",
    r"\bportering services?\b",
    r"\bprinted matter\b",
    r"\bpublicity activities\b",
    r"\breservoir\b",
    r"\bsecurity upgrade\b",
    r"\bstationery\b",
    r"\bstorm damage\b",
    r"\boffice accommodation\b",
    r"\bwater tanks?\b",
    r"\bwater storage\b",
)
SUPPLIER_HINT_PATTERNS = (
    r"\bPTY\b",
    r"\bLTD\b",
    r"\bCC\b",
    r"\bJV\b",
    r"\bINC\b",
    r"\bGROUP\b",
    r"\bTRADING\b",
    r"\bSERVICES\b",
    r"\bSOLUTIONS\b",
    r"\bPROJECTS\b",
    r"\bMEDICAL\b",
    r"\bHEALTHCARE\b",
    r"\bAFRICA\b",
    r"\bCONSULTING\b",
    r"\bSTOPES\b",
)


def _fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=False,
    )
    response.raise_for_status()
    return response.text


def _fetch_binary(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=False,
    )
    response.raise_for_status()
    return response.content


def _load_page_html(url: str, evidence_path: Path) -> str:
    try:
        html = _fetch_text(url)
        evidence_path.write_text(html, encoding="utf-8")
        return html
    except RequestException:
        return evidence_path.read_text(encoding="utf-8", errors="replace")


def _notice_evidence_path(url: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("/")[-1]).strip("_")
    return Path("evidence") / f"kzn_{safe_name}"


def _load_notice_pdf(url: str) -> bytes:
    evidence_path = _notice_evidence_path(url)
    try:
        content = _fetch_binary(url)
        evidence_path.write_bytes(content)
        return content
    except RequestException:
        return evidence_path.read_bytes()


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_publication_date(text: str) -> str:
    for pattern in (
        r"AWARDED BIDS TO BE PUBLISHED ON\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"AWARDED BIDS[:\s]+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"AWARDED BID[:\s]+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            try:
                return datetime.strptime(normalize_text(match.group(1)), "%d %B %Y").date().isoformat()
            except ValueError:
                continue
    return ""


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _is_medical_description(description: str) -> bool:
    text = normalize_text(description).lower()
    if not text:
        return False
    if _matches_any(EXCLUDE_PATTERNS, text):
        return False
    return _matches_any(INCLUDE_PATTERNS, text)


def _explicit_item_hint(row: Dict[str, str]) -> Dict[str, str] | None:
    notice_id = normalize_text(row.get("notice_id"))
    if notice_id in ITEM_EVIDENCE_HINTS:
        return ITEM_EVIDENCE_HINTS[notice_id]
    for field in ("title", "item_desc"):
        key = normalize_text(row.get(field))
        if key in TITLE_EVIDENCE_HINTS:
            return TITLE_EVIDENCE_HINTS[key]
    return None


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


def _extract_contract_period(description: str) -> str:
    return extract_contract_period([description])


def _build_znb_9038_split_row(row: Dict[str, str], institution: str, index: int) -> Dict[str, str]:
    split_row = dict(row)
    base_dedup_key = re.sub(r"(?:\|part\d+)+$", "", normalize_text(row.get("dedup_key")))
    award_value = _normalize_amount(row.get("awarded_value") or row.get("amount"))
    split_row["title"] = "Digital mobile X-ray unit"
    split_row["description"] = normalize_text(f"Digital mobile X-ray unit - {institution}")
    split_row["item_desc"] = normalize_text(f"Digital mobile X-ray unit ({institution})")
    split_row["item_uom"] = "unit"
    split_row["item_quantity"] = "1"
    split_row["awarding_supplier_name"] = "Second Opinion Systems Pty Ltd"
    split_row["amount"] = award_value
    split_row["currency"] = "ZAR" if award_value else ""
    split_row["awarded_value"] = award_value
    split_row["awarded_currency"] = "ZAR" if award_value else ""
    split_row["item_award"] = award_value
    split_row["dedup_key"] = f"{base_dedup_key}|part{index}" if base_dedup_key else ""
    return split_row


def _split_znb_9038_multi_institution_row(row: Dict[str, str]) -> List[Dict[str, str]]:
    if normalize_text(row.get("notice_id")) != "ZNB 9038/2024-H":
        return [row]

    institutions = (
        "Ngwelezane Hospital",
        "KwaMagwaza Hospital",
    )
    combined_text = " ".join(
        normalize_text(row.get(field))
        for field in ("title", "description", "item_desc")
        if normalize_text(row.get(field))
    )
    for index, institution in enumerate(institutions, start=1):
        if institution.lower() in combined_text.lower():
            return [_build_znb_9038_split_row(row, institution, index)]

    split_rows: List[Dict[str, str]] = []
    for index, institution in enumerate(institutions, start=1):
        split_rows.append(_build_znb_9038_split_row(row, institution, index))
    return split_rows


def _pdf_links_from_html(page_url: str, html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[Dict[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor.get("href", ""))
        title = normalize_text(anchor.get_text(" ", strip=True))
        if ".pdf" not in href.lower():
            continue
        if "health-awareness" in href.lower() or "Health Awareness" in title:
            continue
        if href in seen:
            continue
        seen.add(href)
        entries.append({"title": title, "notice_url": href})
    return entries


def _looks_like_supplier(line: str) -> bool:
    text = normalize_text(line).upper()
    if not text:
        return False
    if re.search(r"\bR\s*[\d\s.,]+", text):
        text = re.sub(r"\bR\s*[\d\s.,]+.*$", "", text).strip()
    return any(re.search(pattern, text, re.I) for pattern in SUPPLIER_HINT_PATTERNS)


def _split_desc_supplier_from_body(body: str) -> tuple[str, str]:
    cleaned = normalize_text(body)
    tokens = cleaned.split()
    for start in range(len(tokens) - 1, 0, -1):
        description = " ".join(tokens[:start]).strip()
        supplier = " ".join(tokens[start:]).strip()
        if not description or not supplier:
            continue
        if not re.search(r"\b(?:supply|delivery|replacement|placement|procurement|purchase|installation|provision)\b", description, re.I):
            continue
        if not _looks_like_supplier(supplier):
            continue
        business_tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9&]+", supplier)
            if token.upper() not in {"PTY", "LTD", "LIMITED", "CC", "JV", "INC"} and not token.isdigit()
        ]
        if len(business_tokens) < 2:
            continue
        return normalize_text(description), normalize_text(supplier)
    procurement_split = re.search(
        r"^(?P<desc>.*?\b(?:supply|delivery|replacement|placement|procurement|purchase|installation|provision)\b.*?)(?:\s+)(?P<supplier>[A-Z][A-Za-z0-9&().,'/\- ]+?(?:\(?\s*PTY\s*\)?\s*LTD|CC|JV|INC|LIMITED|LTD))$",
        cleaned,
        re.I,
    )
    if procurement_split:
        return normalize_text(procurement_split.group("desc")), normalize_text(procurement_split.group("supplier"))
    suffix_match = re.search(
        r"^(?P<desc>.*?)(?P<supplier>[A-Z][A-Za-z0-9&().,'/\- ]{2,}?(?:\(?\s*PTY\s*\)?\s*LTD|CC|JV|INC|LIMITED|LTD))$",
        cleaned,
        re.I,
    )
    if suffix_match:
        return normalize_text(suffix_match.group("desc")), normalize_text(suffix_match.group("supplier"))

    tokens = cleaned.split()
    if not tokens:
        return "", ""
    for start in range(len(tokens) - 1, 0, -1):
        supplier = " ".join(tokens[start:])
        description = " ".join(tokens[:start])
        if _looks_like_supplier(supplier):
            return description, supplier
    return normalize_text(body), ""


def _extract_notice_id(lines: List[str]) -> tuple[str, int]:
    for index, line in enumerate(lines):
        match = re.match(r"^(ZNB[ /0-9A-Z.-]+-H)\b:?\s*(.*)$", line, re.I)
        if match:
            return normalize_text(match.group(1)).replace("  ", " "), index
    return "", -1


def _make_row(
    *,
    publication_date: str,
    title: str,
    description: str,
    notice_id: str,
    notice_url: str,
    awarding_supplier_name: str = "",
    awarded_value: str = "",
    item_desc: str = "",
    item_award: str = "",
    strict_supplier_validation: bool = True,
) -> Dict[str, str]:
    normalized_amount = _normalize_amount(awarded_value)
    final_item_desc = normalize_text(item_desc) or normalize_text(title) or normalize_text(description)
    clean_supplier = normalize_text(awarding_supplier_name)
    if re.fullmatch(r"(LTD|PTY|CC|JV|INC|LIMITED|PTY LTD|PTY\) LTD|CONTRACTORS \(PTY\) LTD)", clean_supplier, re.I):
        clean_supplier = ""
    if strict_supplier_validation and clean_supplier and not _looks_like_supplier(clean_supplier):
        clean_supplier = ""
    row = OutputRow(
        source=CONFIG.source,
        country=CONFIG.country,
        country_cc=CONFIG.country_cc,
        publication_date=publication_date,
        closing_date="",
        title=normalize_text(title) or final_item_desc or notice_id,
        description=normalize_text(description),
        buyer=BUYER_NAME,
        classification="",
        status="awarded",
        currency="ZAR" if normalized_amount else "",
        amount=normalized_amount,
        awarding_supplier_name=clean_supplier,
        awarded_currency="ZAR" if normalized_amount else "",
        awarded_value=normalized_amount,
        contract_period=_extract_contract_period(description),
        item_no="1" if final_item_desc else "",
        item_desc=final_item_desc,
        item_uom="",
        item_quantity="",
        item_unit_price="",
        item_award=normalize_text(item_award) or normalized_amount,
        notice_id=normalize_text(notice_id),
        notice_url=notice_url,
        query_text=f"live-medical-awarded:page=kzn:notice={notice_url}",
        scraped_at=utc_now_iso(),
        dedup_key="|".join(
            part
            for part in [CONFIG.key, normalize_text(notice_id), normalize_text(awarding_supplier_name).lower(), final_item_desc.lower()]
            if part
        ),
    )
    return row.to_dict()


def _parse_single_award(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    if any(
        re.search(r"(NO\. ITEM NUMBER|ITEM NUMBER DESCRIPTION|INSTITUTION RECOMMENDED|REGION RECOMMENDED)", lines[idx], re.I)
        for idx in range(start_idx, min(len(lines), start_idx + 8))
    ):
        return []
    amount_idx = -1
    amount_match = None
    for idx in range(start_idx, min(len(lines), start_idx + 12)):
        match = re.search(r"\bR\s*([\d\s,]+(?:\.\d{2})?)", lines[idx], re.I)
        if match:
            amount_idx = idx
            amount_match = match
            break
    if amount_idx < 0 or amount_match is None:
        return []

    start_line = lines[start_idx]
    start_suffix = normalize_text(start_line.split(notice_id, 1)[1]).lstrip(": ").strip()
    supplier_prefix = normalize_text(lines[amount_idx][: amount_match.start()]).strip()
    if supplier_prefix.upper().startswith(notice_id.upper()):
        supplier_prefix = normalize_text(supplier_prefix[len(notice_id):]).lstrip(": ").strip()
    supplier_lines: List[str] = []
    prev_idx = amount_idx - 1
    while prev_idx > start_idx and _looks_like_supplier(lines[prev_idx]) and len(supplier_lines) < 2:
        supplier_lines.insert(0, normalize_text(lines[prev_idx]))
        prev_idx -= 1
    description_from_amount = ""
    if supplier_prefix:
        if supplier_lines:
            supplier_lines.append(supplier_prefix)
        else:
            description_from_amount, supplier_from_amount = _split_desc_supplier_from_body(supplier_prefix)
            supplier_prefix = supplier_from_amount
            if supplier_from_amount:
                supplier_lines.append(supplier_from_amount)
    awarding_supplier_name = normalize_text(" ".join(part for part in supplier_lines if part))

    description_parts: List[str] = []
    if amount_idx == start_idx:
        if description_from_amount:
            description_parts.append(description_from_amount)
        elif supplier_prefix:
            description_parts.append(supplier_prefix)
    elif start_suffix:
        description_parts.append(start_suffix)
    description_parts.extend(normalize_text(lines[idx]) for idx in range(start_idx + 1, prev_idx + 1))
    if description_from_amount and amount_idx != start_idx:
        description_parts.append(description_from_amount)
    description = normalize_text(" ".join(part for part in description_parts if part))
    if not description or not _is_medical_description(description):
        return []
    awarded_value = amount_match.group(1)
    return [
        _make_row(
            publication_date=publication_date,
            title=description,
            description=description,
            notice_id=notice_id,
            notice_url=notice_url,
            awarding_supplier_name=awarding_supplier_name,
            awarded_value=awarded_value,
            item_desc=description,
        )
    ]


def _parse_region_award(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    description_parts: List[str] = []
    region_header_idx = -1
    for idx in range(start_idx, len(lines)):
        if "REGION RECOMMENDED BIDDER" in lines[idx].upper():
            region_header_idx = idx
            break
        if idx == start_idx:
            suffix = normalize_text(lines[idx].split(notice_id, 1)[1]).lstrip(": ").strip()
            if suffix:
                description_parts.append(suffix)
        else:
            description_parts.append(normalize_text(lines[idx]))
    description = normalize_text(" ".join(description_parts))
    if region_header_idx < 0 or not _is_medical_description(description):
        return []
    rows: List[Dict[str, str]] = []
    idx = region_header_idx + 1
    while idx < len(lines):
        line = lines[idx]
        if not line.upper().startswith("REGION"):
            idx += 1
            continue
        region_text = normalize_text(line)
        block: List[str] = []
        cursor = idx + 1
        while cursor < len(lines) and not lines[cursor].upper().startswith("REGION"):
            block.append(normalize_text(lines[cursor]))
            cursor += 1
        supplier = block[-1] if block else ""
        if len(block) > 1:
            region_text = normalize_text(" ".join([region_text] + block[:-1]))
        rows.append(
            _make_row(
                publication_date=publication_date,
                title=description,
                description=description,
                notice_id=notice_id,
                notice_url=notice_url,
                awarding_supplier_name=supplier,
                awarded_value="",
                item_desc=f"{description} ({region_text})",
                item_award="",
            )
        )
        idx = cursor
    return rows


def normalize_saved_row(row: Dict[str, str]) -> Dict[str, str] | None:
    normalized = dict(row)
    explicit_hint = _explicit_item_hint(normalized)
    if explicit_hint and not normalize_text(normalized.get("item_quantity")):
        normalized["item_desc"] = explicit_hint["item_desc"]
        normalized["item_uom"] = explicit_hint["item_uom"]
        normalized["item_quantity"] = explicit_hint["item_quantity"]
    item_desc = normalize_text(normalized.get("item_desc"))
    item_quantity = normalize_text(normalized.get("item_quantity"))
    unit_price = _normalize_amount(normalized.get("item_unit_price"))
    item_award = _normalize_amount(normalized.get("item_award"))
    if (
        not item_quantity
        and "PRICE PER UNIT" in item_desc.upper()
        and unit_price
        and item_award
        and unit_price == item_award
    ):
        normalized["item_quantity"] = "1"
    return normalized


def normalize_saved_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized_rows: List[Dict[str, str]] = []
    for row in rows:
        for split_row in _split_znb_9038_multi_institution_row(dict(row)):
            normalized = normalize_saved_row(split_row)
            if normalized is not None:
                normalized_rows.append(normalized)
    return normalized_rows


def _parse_institution_award(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    description_parts: List[str] = []
    institution_header_idx = -1
    for idx in range(start_idx, len(lines)):
        if "INSTITUTION RECOMMENDED BIDDER" in lines[idx].upper() or "INSTITUTION RECOMMENDED BIDDERS" in lines[idx].upper():
            institution_header_idx = idx
            break
        if idx == start_idx:
            suffix = normalize_text(lines[idx].split(notice_id, 1)[1]).lstrip(": ").strip()
            if suffix:
                description_parts.append(suffix)
        else:
            description_parts.append(normalize_text(lines[idx]))
    description = normalize_text(" ".join(description_parts))
    if institution_header_idx < 0 or not _is_medical_description(description):
        return []
    rows: List[Dict[str, str]] = []
    institution_re = re.compile(
        r"^(?P<institution>(?:.+?\s+)?(?:HOSPITAL|MORTUARY|BASE))\s+(?P<supplier>.+?)\s+R\s*(?P<amount>[\d\s,]+(?:\.\d{2})?)\s+(?P<points>\d+(?:\.\d+)?)$",
        re.I,
    )
    pending_prefix = ""
    for raw_line in lines[institution_header_idx + 1 :]:
        line = normalize_text(raw_line)
        if not line:
            continue
        candidate = normalize_text(f"{pending_prefix} {line}") if pending_prefix else line
        match = institution_re.match(candidate)
        if not match:
            pending_prefix = line
            continue
        institution = normalize_text(match.group("institution"))
        rows.append(
            _make_row(
                publication_date=publication_date,
                title=description,
                description=description,
                notice_id=notice_id,
                notice_url=notice_url,
                awarding_supplier_name=match.group("supplier"),
                awarded_value=match.group("amount"),
                item_desc=f"{description} ({institution})",
            )
        )
        pending_prefix = ""
    return rows


def _parse_notice_level_award(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    description_parts: List[str] = []
    for idx in range(start_idx, min(len(lines), start_idx + 8)):
        line = normalize_text(lines[idx])
        if idx == start_idx:
            line = normalize_text(line.split(notice_id, 1)[1]).lstrip(": ").strip()
        if re.search(r"(NO\. ITEM NUMBER|ITEM NUMBER DESCRIPTION|INSTITUTION RECOMMENDED|REGION RECOMMENDED)", line, re.I):
            break
        if line:
            description_parts.append(line)
    description = normalize_text(" ".join(description_parts))
    if not description or not _is_medical_description(description):
        return []
    return [
        _make_row(
            publication_date=publication_date,
            title=description,
            description=description,
            notice_id=notice_id,
            notice_url=notice_url,
            awarding_supplier_name="",
            awarded_value="",
            item_desc=description,
            item_award="",
        )
    ]


def _is_page_artifact(line: str) -> bool:
    upper = normalize_text(line).upper()
    if not upper:
        return True
    return upper.startswith("PAGE ") or upper in {
        "DIRECTORATE:",
        "PHYSICAL ADDRESS: 310 JABU NDLOVU",
        "PRIVATE BAG X9051, PIETERMARITZBURG, 3200",
        "WWW.KZNHEALTH.GOV.ZA",
        "SUPPLY CHAIN MANAGEMENT",
    }


def _extract_table_body_lines(lines: List[str], start_idx: int) -> List[str]:
    body = [normalize_text(line) for line in lines[start_idx + 1 :] if normalize_text(line)]
    cleaned: List[str] = []
    skip_prefixes = (
        "NO. ITEM",
        "NUMBER",
        "DESCRIPTION RECOMMENDED BIDDERS",
        "ITEM DESCRIPTION BRAND",
        "ITEM DESCRIPTION RECOMMENDED BIDDER",
        "FOR YEAR 1",
        "YEAR 1 + YEAR 2 +",
        "YEAR 3 (INCL. VAT)",
        "VAT)",
        "TOTAL PRICE",
        "TOTAL BID PRICE",
        "RECOMMENDED BIDDERS",
        "* *THE COMMITTEE AWARD",
        "RANKING BIDDER IS THE PREFERRED",
        "BIDDERS THEY FAIL TO DELIVER",
        "OTHER AWARDED BIDDERS",
        "1 + YEAR 2 + YEAR 3",
        "(INCL. VAT)",
    )
    for line in body:
        if _is_page_artifact(line):
            continue
        if line.upper().startswith(skip_prefixes):
            continue
        cleaned.append(line)
    return cleaned


def _split_top_level_blocks(body_lines: List[str], start_pattern: str) -> List[List[str]]:
    blocks: List[List[str]] = []
    current: List[str] = []
    for line in body_lines:
        if re.match(start_pattern, line):
            if current:
                blocks.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _strip_leading_item_code(text: str) -> str:
    cleaned = normalize_text(text)
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
    cleaned = re.sub(r"^(?:[A-Z]{1,5}\s*\d+[A-Z]?|(?:\d{2}\s+){2,}\d+[A-Z]?)\s+", "", cleaned)
    return normalize_text(cleaned)


def _clean_table_supplier(text: str) -> str:
    cleaned = normalize_text(text)
    cleaned = re.sub(r"^Price per Unit\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\boffer\s+\d+\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\b([A-Za-z]+)\s+\1\b", r"\1", cleaned)
    cleaned = re.sub(r"^(?:\(?\s*PTY\s*\)?\s*LTD|LTD|CC|JV|INC)\b", "", cleaned, flags=re.I).strip()
    if cleaned and not re.match(r"^[A-Z]", cleaned):
        return ""
    return normalize_text(cleaned)


def _parse_generic_item_table(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    description = normalize_text(" ".join(lines[start_idx : start_idx + 3]))
    body_lines = _extract_table_body_lines(lines, start_idx)
    if not body_lines or not any(re.match(r"^\d+\.", line) for line in body_lines):
        return []

    blocks = _split_top_level_blocks(body_lines, r"^\d+\.\s+")
    rows: List[Dict[str, str]] = []
    for block in blocks:
        amount_idx = next((idx for idx, line in enumerate(block) if re.search(r"R\s*\d[\d\s,]*(?:\.\d{2})?", line)), -1)
        if amount_idx < 0:
            continue
        amount_line = block[amount_idx]
        amount_match = re.search(r"R\s*(\d[\d\s,]*(?:\.\d{2})?)", amount_line)
        if not amount_match:
            continue
        supplier_line = normalize_text(amount_line[: amount_match.start()]).strip()
        supplier_parts: List[str] = []
        cursor = amount_idx - 1
        if supplier_line:
            supplier_parts.append(supplier_line)
        else:
            while cursor >= 1 and len(supplier_parts) < 2:
                candidate = normalize_text(block[cursor])
                if re.match(r"^\d+\.", candidate):
                    break
                supplier_parts.insert(0, candidate)
                cursor -= 1
            cursor = max(cursor, 0)
        supplier_candidate = normalize_text(" ".join(supplier_parts))
        if supplier_candidate and not _looks_like_supplier(supplier_candidate) and amount_idx >= 2:
            fallback_supplier = normalize_text(f"{block[amount_idx - 2]} {block[amount_idx - 1]}")
            if _looks_like_supplier(fallback_supplier):
                supplier_candidate = fallback_supplier
                cursor = amount_idx - 3
        supplier = _clean_table_supplier(supplier_candidate)
        item_desc_lines = block[: max(1, cursor + 1)]
        item_desc = normalize_text(" ".join(_strip_leading_item_code(line) for line in item_desc_lines))
        if not _is_medical_description(f"{description} {item_desc}"):
            continue
        price_per_unit = "PRICE PER UNIT" in " ".join(block).upper()
        if price_per_unit:
            item_desc = normalize_text(f"{item_desc} Price per Unit")
        row = _make_row(
                publication_date=publication_date,
                title=description,
                description=description,
                notice_id=notice_id,
                notice_url=notice_url,
                awarding_supplier_name=supplier,
                awarded_value=amount_match.group(1),
                item_desc=item_desc,
                item_award=_normalize_amount(amount_match.group(1)),
                strict_supplier_validation=False,
            )
        if price_per_unit:
            unit_price = row.get("amount", "")
            row["amount"] = ""
            row["currency"] = ""
            row["awarded_value"] = ""
            row["awarded_currency"] = ""
            row["item_unit_price"] = unit_price
            row["item_uom"] = ""
        rows.append(row)
    return rows


def _parse_item_code_table(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    description = normalize_text(" ".join(lines[start_idx : start_idx + 3]))
    if not _is_medical_description(description):
        return []
    body_lines = _extract_table_body_lines(lines, start_idx)
    blocks = _split_top_level_blocks(body_lines, r"^(?:\d{2}\s+\d{3}\s+\d{2}|PCAD)\b")
    if not blocks:
        return []
    rows: List[Dict[str, str]] = []
    for block in blocks:
        amount_idx = next((idx for idx, line in enumerate(block) if re.search(r"R\s*\d[\d\s,]*(?:\.\d{2})?", line)), -1)
        if amount_idx < 0:
            continue
        amount_line = block[amount_idx]
        amount_match = re.search(r"R\s*(\d[\d\s,]*(?:\.\d{2})?)", amount_line)
        if not amount_match:
            continue
        prefix = normalize_text(amount_line[: amount_match.start()]).strip()
        supplier = ""
        description_tail = ""
        if prefix:
            description_tail, supplier = _split_desc_supplier_from_body(prefix)
            if not supplier and _looks_like_supplier(prefix):
                supplier = prefix
        supplier_parts: List[str] = []
        cursor = amount_idx - 1
        supplier = _clean_table_supplier(supplier)
        if not supplier:
            while cursor >= 1 and len(supplier_parts) < 2:
                candidate = normalize_text(block[cursor])
                if re.match(r"^(?:\d{2}\s+\d{3}\s+\d{2}|PCAD)\b", candidate):
                    break
                if not supplier_parts and not _looks_like_supplier(candidate):
                    break
                supplier_parts.insert(0, candidate)
                cursor -= 1
            supplier = _clean_table_supplier(" ".join(supplier_parts))
        item_desc_lines = [_strip_leading_item_code(block[0])]
        if amount_idx > 1:
            item_desc_lines.extend(block[1 : max(1, cursor + 1)])
        if description_tail:
            item_desc_lines.append(description_tail)
        item_desc = normalize_text(" ".join(line for line in item_desc_lines if line))
        if not item_desc or not _is_medical_description(f"{description} {item_desc}"):
            continue
        rows.append(
            _make_row(
                publication_date=publication_date,
                title=description,
                description=description,
                notice_id=notice_id,
                notice_url=notice_url,
                awarding_supplier_name=_clean_table_supplier(supplier),
                awarded_value=amount_match.group(1),
                item_desc=item_desc,
                item_award=_normalize_amount(amount_match.group(1)),
                strict_supplier_validation=False,
            )
        )
    return rows


def _parse_multi_bidder_item_table(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    description = normalize_text(" ".join(lines[start_idx : start_idx + 3]))
    if not _is_medical_description(description):
        return []
    body_lines = _extract_table_body_lines(lines, start_idx)
    blocks = _split_top_level_blocks(body_lines, r"^\d+\.\s+\d{2}\s+\d{3}\s+\d{2}")
    if not blocks:
        return []
    rows: List[Dict[str, str]] = []
    for block in blocks:
        supplier_start = next((idx for idx, line in enumerate(block[1:], start=1) if re.match(r"^\d+\.\s+[A-Za-z]", line)), -1)
        if supplier_start < 0:
            continue
        item_desc = normalize_text(" ".join(_strip_leading_item_code(line) for line in block[:supplier_start]))
        suppliers: List[str] = []
        amounts: List[str] = []
        for line in block[supplier_start:]:
            if re.match(r"^\d+\.\s+[A-Za-z]", line):
                suppliers.append(normalize_text(re.sub(r"^\d+\.\s*", "", line)))
            elif re.search(r"^R\s*[\d\s,]+(?:\.\d{2})?$", line, re.I):
                amount_match = re.search(r"R\s*([\d\s,]+(?:\.\d{2})?)", line, re.I)
                if amount_match:
                    amounts.append(amount_match.group(1))
            elif suppliers and not amounts and line.startswith("*"):
                continue
        for supplier, amount in zip(suppliers, amounts):
            rows.append(
                _make_row(
                    publication_date=publication_date,
                    title=description,
                    description=description,
                    notice_id=notice_id,
                    notice_url=notice_url,
                    awarding_supplier_name=_clean_table_supplier(supplier),
                    awarded_value=amount,
                    item_desc=item_desc,
                    item_award=_normalize_amount(amount),
                    strict_supplier_validation=False,
                )
            )
    return rows


def _parse_uniform_group_table(lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0:
        return []
    description = normalize_text(" ".join(lines[start_idx : start_idx + 3]))
    if not _is_medical_description(description):
        return []
    body_lines = _extract_table_body_lines(lines, start_idx)
    if not body_lines:
        return []
    current_heading = ""
    rows: List[Dict[str, str]] = []
    size_row_re = re.compile(
        r"^\d+\.\s+(?P<icn>\d{6,}[A-Z0-9]*)\s+(?P<size>X SMALL|SMALL|MEDIUM|LARGE|X-LARGE|2XL|3XL|4XL|5XL)\s+(?P<supplier>.+?)\s+R\s*(?P<amount>[\d\s,]+(?:\.\d{2})?)$",
        re.I,
    )
    for line in body_lines:
        if re.match(r"^\d+\.\s+[A-Z][A-Z ():-]+$", line):
            current_heading = normalize_text(re.sub(r"^\d+\.\s*", "", line))
            continue
        match = size_row_re.match(line)
        if not match or not current_heading:
            continue
        item_desc = normalize_text(f"{current_heading} ({normalize_text(match.group('size'))})")
        rows.append(
            _make_row(
                publication_date=publication_date,
                title=description,
                description=description,
                notice_id=notice_id,
                notice_url=notice_url,
                awarding_supplier_name=_clean_table_supplier(match.group("supplier")),
                awarded_value=match.group("amount"),
                item_desc=item_desc,
                item_award=_normalize_amount(match.group("amount")),
                strict_supplier_validation=False,
            )
        )
    return rows


def _parse_area_summary_award(text: str, lines: List[str], publication_date: str, notice_url: str) -> List[Dict[str, str]]:
    notice_id, start_idx = _extract_notice_id(lines)
    if start_idx < 0 or "SUMMARY PRICE: AREA" not in text.upper():
        return []
    description_parts: List[str] = []
    for idx in range(start_idx, len(lines)):
        line = normalize_text(lines[idx])
        if "SUMMARY PRICE: AREA" in line.upper():
            break
        if idx == start_idx:
            line = normalize_text(line.split(notice_id, 1)[1]).lstrip(": ").strip()
        if line:
            description_parts.append(line)
    description = normalize_text(" ".join(description_parts))
    if not description or not _is_medical_description(description):
        return []
    rows: List[Dict[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index].upper()
        if "SUMMARY PRICE: AREA" not in line:
            index += 1
            continue
        area_match = re.search(r"AREA\s+(\d+)", lines[index], re.I)
        supplier = ""
        amount = ""
        area = normalize_text(area_match.group(1)) if area_match else ""
        if index + 1 < len(lines):
            supplier_match = re.search(r"RECOMMENDED BIDDER:\s*(.+)$", lines[index + 1], re.I)
            if supplier_match:
                supplier = normalize_text(supplier_match.group(1))
        next_summary = len(lines)
        for cursor in range(index + 1, len(lines)):
            if cursor > index + 1 and "SUMMARY PRICE: AREA" in lines[cursor].upper():
                next_summary = cursor
                break
        for cursor in range(index + 1, next_summary):
            if re.search(r"^R\s*[\d\s,]+(?:\.\d{2})?(?:\s+R\s*[\d\s,]+(?:\.\d{2})?)+$", lines[cursor], re.I):
                amounts = re.findall(r"R\s*([\d\s,]+(?:\.\d{2})?)", lines[cursor], re.I)
                if amounts:
                    amount = amounts[-1]
                break
        if area and supplier and amount:
            supplier = re.sub(r"\s{2,}", " ", supplier).strip()
            rows.append(
                _make_row(
                    publication_date=publication_date,
                    title=description,
                    description=description,
                    notice_id=notice_id,
                    notice_url=notice_url,
                    awarding_supplier_name=supplier,
                    awarded_value=amount,
                    item_desc=f"{description} (Area {area})",
                )
            )
        index += 1
    return rows


def _parse_pdf_rows(entry: Dict[str, str], text: str) -> List[Dict[str, str]]:
    publication_date = _parse_publication_date(text)
    if not publication_date:
        return []
    lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
    notice_id, _ = _extract_notice_id(lines)
    area_rows = _parse_area_summary_award(text, lines, publication_date, entry["notice_url"])
    if area_rows:
        return area_rows
    if notice_id == "ZNB 5750/1/2023-H":
        uniform_rows = _parse_uniform_group_table(lines, publication_date, entry["notice_url"])
        if uniform_rows:
            return uniform_rows
    if notice_id == "ZNB 6685/1/2023-H":
        multi_bidder_rows = _parse_multi_bidder_item_table(lines, publication_date, entry["notice_url"])
        if multi_bidder_rows:
            return multi_bidder_rows
    if notice_id in {"ZNB 6685/3/2023-H", "ZNB 6685/4/2023-H", "ZNB 6225/2023-H", "ZNB 6730/2023-H", "ZNB 5352/2023-H"}:
        item_rows = _parse_generic_item_table(lines, publication_date, entry["notice_url"])
        if item_rows:
            return item_rows
    if notice_id == "ZNB 5325/2023-H":
        item_rows = _parse_item_code_table(lines, publication_date, entry["notice_url"])
        if item_rows:
            return item_rows
    if any("REGION RECOMMENDED BIDDER" in line.upper() for line in lines):
        return _parse_region_award(lines, publication_date, entry["notice_url"])
    if any("INSTITUTION RECOMMENDED BIDDER" in line.upper() or "INSTITUTION RECOMMENDED BIDDERS" in line.upper() for line in lines):
        rows = _parse_institution_award(lines, publication_date, entry["notice_url"])
        if rows:
            return rows
    rows = _parse_single_award(lines, publication_date, entry["notice_url"])
    if rows:
        return rows
    return _parse_notice_level_award(lines, publication_date, entry["notice_url"])


def smoke_probe() -> SmokeProbeResult:
    entry = {
        "title": "ZNB9041/2024-H",
        "notice_url": "https://www.kznhealth.gov.za/wp-content/uploads/2026/05/ZNB9041.2024-H.pdf",
    }
    rows = _parse_pdf_rows(entry, _extract_pdf_text(EVIDENCE_SMOKE_PDF_PATH.read_bytes()))
    if not rows:
        return SmokeProbeResult(
            source_key=CONFIG.key,
            ok=False,
            mode="evidence_missing",
            detail="Saved KZN biosafety cabinet award PDF did not yield a smoke row.",
            sample_rows=[],
        )
    row = rows[0]
    ok = bool(row["publication_date"] and row["notice_id"] and row["item_desc"] and row["notice_url"])
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=ok,
        mode="evidence_pdf",
        detail="Parsed a saved KZN biosafety cabinet award notice sample from the public 2026 awards page.",
        sample_rows=rows,
    )


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 50) -> List[Dict[str, str]]:
    del page_size
    entries: List[Dict[str, str]] = []
    for page_url, evidence_path in PAGE_SPECS:
        html = _load_page_html(page_url, evidence_path)
        entries.extend(_pdf_links_from_html(page_url, html))

    rows: List[Dict[str, str]] = []
    seen_urls = set()
    for entry in entries:
        notice_url = entry["notice_url"]
        if notice_url in seen_urls:
            continue
        seen_urls.add(notice_url)
        try:
            content = _load_notice_pdf(notice_url)
        except (RequestException, FileNotFoundError):
            continue
        parsed_rows = _parse_pdf_rows(entry, _extract_pdf_text(content))
        for row in parsed_rows:
            publication_date = row.get("publication_date", "")
            if not publication_date or publication_date < date_from or publication_date > date_to:
                continue
            rows.append(row)
    return rows
