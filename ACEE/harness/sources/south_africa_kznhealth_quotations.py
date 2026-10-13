from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import re
import subprocess
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin, urlparse

import fitz
import requests
import urllib3
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader
from requests import RequestException

from harness.shared.field_extract import extract_contract_period, extract_explicit_supply_quantity_uom
from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG = SOURCES["south_africa_kznhealth_quotations"]
LISTING_URL = "https://www.kznhealth.gov.za/scm/quotation-awards/"
EVIDENCE_LISTING_PATH = Path("evidence") / "kzn_quotation_awards_landing_live.html"
EVIDENCE_SAMPLE_MONTH_PATH = Path("evidence") / "kzn_quotation_awards_april_2026_live.html"
EVIDENCE_SAMPLE_PDF_PATH = Path("evidence") / "kzn_quote_MSH12-26-27H.pdf"
EVIDENCE_SAMPLE_TXT_PATH = Path("evidence") / "kzn_quote_MSH12-26-27H.txt"
REQUEST_TIMEOUT_SECONDS = 60
BUYER_NAME = "KwaZulu-Natal Department of Health"
TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
MAX_WORKERS = 6
INCLUDE_PATTERNS = (
    r"\baudiology\b",
    r"\bbreathing\b",
    r"\bc-?pap\b",
    r"\bcannula\b",
    r"\bcatheter\b",
    r"\bcentral venous\b",
    r"\bclub foot\b",
    r"\bct injection\b",
    r"\bdental\b",
    r"\bdialysis\b",
    r"\bendotracheal\b",
    r"\bgastrostomy\b",
    r"\bgauze\b",
    r"\bgloves?\b",
    r"\bhigh risk gloves?\b",
    r"\bhumidifier\b",
    r"\bintravenous\b",
    r"\biv\b",
    r"\blaryngeal\b",
    r"\blow vision\b",
    r"\bmask\b",
    r"\bmaternity\b",
    r"\bmedical\b",
    r"\bmedical gas\b",
    r"\bmortuary\b",
    r"\bnebuli[sz]ing\b",
    r"\bneonatal\b",
    r"\boccupational therapy\b",
    r"\boxygen\b",
    r"\bpaediatric\b",
    r"\bpediatric\b",
    r"\bparticle count\b",
    r"\bperitoneal dialysis\b",
    r"\bphysiotherapy\b",
    r"\bradiology\b",
    r"\bremote radiology\b",
    r"\brespirator\b",
    r"\brespiratory\b",
    r"\bsanitary maternity\b",
    r"\bspectacles?\b",
    r"\bspinal needle\b",
    r"\bsuction\b",
    r"\bsurgical\b",
    r"\bsyringe\b",
    r"\btheatre\b",
    r"\bvacuum plant\b",
    r"\bventilator\b",
    r"\bvision devices?\b",
    r"\bwaste handlers?\b",
    r"\bx[\s-]?ray\b",
)
EXCLUDE_PATTERNS = (
    r"\bboiler\b",
    r"\bcleaning material\b",
    r"\bcupboard\b",
    r"\bdiesel\b",
    r"\bfresh water\b",
    r"\bfurniture\b",
    r"\bgarden\b",
    r"\bgenerator\b",
    r"\bhardware\b",
    r"\bpainting\b",
    r"\bphotocopy paper\b",
    r"\brepair underground water supply\b",
    r"\bstationery\b",
    r"\btyres?\b",
    r"\bwater supply\b",
)
ITEM_EVIDENCE_HINTS = {
    "ZNQ: EDN 500/25-26": {
        "item_desc": "X-Ray film digitiser device",
        "item_uom": "digitiser",
        "item_quantity": "1",
    },
    "IMB 89/25-26": {
        "item_desc": "SUPPLY AND DELIVER X-RAY VIEWING BOARD",
        "item_uom": "board",
        "item_quantity": "1",
    },
}
TITLE_EVIDENCE_HINTS = {
    "NEONATAL COOLING DEVICE": {
        "item_desc": "NEONATAL COOLING DEVICE",
        "item_uom": "device",
        "item_quantity": "1",
    },
}


def _canonical_notice_id(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_text(value).upper())


def _canonical_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_text(value).upper())


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


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


def _load_text(url: str, evidence_path: Path) -> str:
    try:
        text = _fetch_text(url)
        evidence_path.write_text(text, encoding="utf-8")
        return text
    except RequestException:
        return evidence_path.read_text(encoding="utf-8", errors="replace")


def _month_evidence_path(month_url: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", month_url.rstrip("/").split("/")[-1]).strip("_")
    return Path("evidence") / f"kzn_quotation_{slug}.html"


def _pdf_evidence_path(notice_url: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", notice_url.rstrip("/").split("/")[-1]).strip("_")
    return Path("evidence") / f"kzn_quote_{slug}"


def _extract_month_pages(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[Dict[str, str]] = []
    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(LISTING_URL, anchor.get("href", ""))
        parsed = urlparse(href)
        path = parsed.path.lower()
        if ".pdf" in path or "tender-awards" in path or "/awards-" not in path or not href.endswith("/"):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        entries.append(
            {
                "month_label": normalize_text(anchor.get_text(" ", strip=True)) or parsed.path.rstrip("/").split("/")[-1],
                "month_url": href,
            }
        )
    return entries


def _parse_html_date(value: str) -> str:
    cleaned = normalize_text(value)
    for fmt in ("%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _is_medical_description(description: str) -> bool:
    text = normalize_text(description).lower()
    if not text:
        return False
    if _matches_any(EXCLUDE_PATTERNS, text):
        return False
    return _matches_any(INCLUDE_PATTERNS, text)


@lru_cache(maxsize=1)
def _advert_quantity_hints() -> Dict[str, Dict[str, str]]:
    hints: Dict[str, Dict[str, str]] = {}
    for path in Path("evidence").glob("kzn_quote_*.txt"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Quotation Advert" not in text:
            continue
        notice_match = re.search(
            r"(?:Quotation|Quote)\s+number\s*[:;]?\s*(.+?)\s*(?:Quote Description|GuoteDeseripion|GuoteDescription|QuoteDeseripion|Quotation Award|Date of award publication|Date of Award Publication|Item Description|Item Category|Results of award|$)",
            text,
            re.I | re.S,
        )
        quantity_match = re.search(r"Quantity\s*\(if supplies\)\s*[:;|]?\s*([^\n\r]+)", text, re.I)
        if not notice_match or not quantity_match:
            continue
        quantity, item_uom = extract_explicit_supply_quantity_uom([quantity_match.group(0), quantity_match.group(1)])
        if not quantity:
            bare_quantity_match = re.search(r"\b(\d[\d\s,]*)\b", quantity_match.group(1))
            if bare_quantity_match:
                quantity = normalize_text(bare_quantity_match.group(1)).replace(" ", "").replace(",", "")
        if not quantity:
            continue
        description_match = re.search(
            r"(?:Quote|Item)\s+Description\s*[:;|]?\s*(.+?)(?=\s*(?:Date of award publication|Date of Award Publication|Quote Advert Details|Institution Name|Quantity \(if supplies\))\b)",
            text,
            re.I | re.S,
        )
        notice_id = normalize_text(notice_match.group(1).strip(" |"))
        hints[_canonical_notice_id(notice_id)] = {
            "notice_id": notice_id,
            "description": normalize_text(description_match.group(1).strip(" |")) if description_match else "",
            "item_quantity": quantity,
            "item_uom": item_uom,
            "evidence_file": path.name,
        }
    return hints


def _advert_quantity_hint(row: Dict[str, str]) -> Dict[str, str] | None:
    canonical_notice_id = _canonical_notice_id(row.get("notice_id", ""))
    if not canonical_notice_id:
        return None
    hint = _advert_quantity_hints().get(canonical_notice_id)
    if not hint:
        return None
    row_desc = normalize_text(row.get("item_desc") or row.get("title") or row.get("description"))
    hint_desc = hint.get("description", "")
    if row_desc and hint_desc:
        canonical_row_desc = _canonical_text(row_desc)
        canonical_hint_desc = _canonical_text(hint_desc)
        if canonical_row_desc and canonical_hint_desc:
            if canonical_row_desc not in canonical_hint_desc and canonical_hint_desc not in canonical_row_desc:
                return None
    return hint


def _explicit_item_hint(row: Dict[str, str]) -> Dict[str, str] | None:
    notice_id = normalize_text(row.get("notice_id"))
    if notice_id in ITEM_EVIDENCE_HINTS:
        return ITEM_EVIDENCE_HINTS[notice_id]
    for field in ("title", "item_desc"):
        key = normalize_text(row.get(field))
        if key in TITLE_EVIDENCE_HINTS:
            return TITLE_EVIDENCE_HINTS[key]
    return None


def _parse_month_rows(month_label: str, month_url: str, html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    for tr in soup.find_all("tr"):
        cols = [normalize_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        if len(cols) != 4:
            continue
        pdf_link = ""
        for anchor in tr.find_all("a", href=True):
            href = urljoin(month_url, anchor.get("href", ""))
            if ".pdf" in href.lower():
                pdf_link = href
                break
        if not pdf_link:
            continue
        pdf_name, institution, description, date_text = cols
        if not pdf_name.lower().endswith(".pdf"):
            continue
        publication_date = _parse_html_date(date_text)
        rows.append(
            {
                "month_label": month_label,
                "month_url": month_url,
                "pdf_name": pdf_name,
                "institution": institution,
                "description": description,
                "publication_date": publication_date,
                "notice_url": pdf_link,
            }
        )
    return rows


def _normalize_amount(value: str) -> str:
    cleaned = normalize_text(value).replace("R", "").replace(" ", "")
    if not cleaned:
        return ""
    cleaned = cleaned.rstrip(".,;:|")
    cleaned = re.sub(r"(?<=\d)-(?=\d{3}(?:[.,]\d{2})?$)", "", cleaned)
    cleaned = re.sub(r"(\.\d{2})\.00$", r"\1", cleaned)
    cleaned = re.sub(r"-(\d{2})$", r".\1", cleaned)
    cleaned = re.sub(r",(\d)\b", lambda match: f".{match.group(1)}0", cleaned)
    if re.search(r"[.,-]", cleaned) and re.search(r"[.,]\d{2}$", cleaned):
        integer_part, decimal_part = re.split(r"[.,](?=\d{2}$)", cleaned, maxsplit=1)
        integer_digits = re.sub(r"\D", "", integer_part)
        if integer_digits:
            return f"{integer_digits}.{decimal_part}"
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "." not in cleaned and re.fullmatch(r"\d+", cleaned):
        return cleaned
    return cleaned


def _extract_ial_1419_variants(text: str) -> List[tuple[str, str]]:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return []

    if " - " in normalized_text:
        normalized_text = normalize_text(normalized_text.rsplit(" - ", 1)[0])

    parts = re.split(r",\s*Size:\s*", normalized_text)
    if len(parts) != 3:
        return []

    variants: List[tuple[str, str]] = []
    quantity_pattern = re.compile(r"(?P<qty>\d[\d\s,]*)\s*(?:\W+\s*)?Units\b", re.I)
    for index, part in enumerate(parts, start=1):
        match = quantity_pattern.search(part)
        if not match:
            return []
        item_desc = normalize_text(part[: match.start()])
        item_desc = re.sub(r"[^\w)]+$", "", item_desc)
        if index > 1:
            item_desc = normalize_text(f"Central venous catheter set: Size: {item_desc}")
        variants.append((item_desc, normalize_text(match.group("qty")).replace(" ", "")))
    return variants


def _build_ial_1419_split_row(
    row: Dict[str, str],
    index: int,
    item_desc: str,
    item_quantity: str,
    institution_suffix: str,
) -> Dict[str, str]:
    split_row = dict(row)
    base_dedup_key = re.sub(r"(?:\|part\d+)+$", "", normalize_text(row.get("dedup_key")))
    split_row["title"] = item_desc
    split_row["description"] = normalize_text(f"{item_desc} - {institution_suffix}") if institution_suffix else item_desc
    split_row["item_desc"] = item_desc
    split_row["item_no"] = str(index)
    split_row["item_uom"] = normalize_text(row.get("item_uom")) or "set"
    split_row["item_quantity"] = item_quantity
    split_row["dedup_key"] = f"{base_dedup_key}|part{index}"
    if index > 1:
        split_row["currency"] = ""
        split_row["amount"] = ""
        split_row["awarded_currency"] = ""
        split_row["awarded_value"] = ""
        split_row["item_award"] = ""
    return split_row


def _split_explicit_multi_quantity_row(row: Dict[str, str]) -> List[Dict[str, str]]:
    if normalize_text(row.get("notice_id")) != "ZNQ: IAL/1419/25/26":
        return [row]

    description_text = normalize_text(row.get("description"))
    item_no = normalize_text(row.get("item_no"))
    if item_no in {"1", "2", "3"}:
        canonical_row = dict(row)
        canonical_base_dedup_key = re.sub(r"(?:\|part\d+)+$", "", normalize_text(row.get("dedup_key")))
        canonical_row["dedup_key"] = f"{canonical_base_dedup_key}|part{item_no}"
        variants = _extract_ial_1419_variants(description_text)
        if len(variants) == 3:
            institution_suffix = ""
            if " - " in description_text:
                institution_suffix = normalize_text(description_text.rsplit(" - ", 1)[-1])
            if item_no == "1" and ", Size:" in description_text:
                return [
                    _build_ial_1419_split_row(row, index, item_desc, item_quantity, institution_suffix)
                    for index, (item_desc, item_quantity) in enumerate(variants, start=1)
                ]
            index = int(item_no)
            item_desc, item_quantity = variants[index - 1]
            return [_build_ial_1419_split_row(row, index, item_desc, item_quantity, institution_suffix)]
        return [canonical_row]

    base_text = normalize_text(row.get("item_desc") or row.get("title") or row.get("description"))
    if not base_text:
        return [row]

    parts = re.split(r",\s*Size:\s*", base_text)
    if len(parts) != 3:
        return [row]

    split_rows: List[Dict[str, str]] = []
    base_uom = normalize_text(row.get("item_uom")) or "set"
    institution_suffix = ""
    description_text = normalize_text(row.get("description"))
    if " - " in description_text:
        institution_suffix = normalize_text(description_text.rsplit(" - ", 1)[-1])
    for index, part in enumerate(parts, start=1):
        match = re.search(
            r"(?P<desc>.+?)\s*(?:[-–—]|â€”)?\s*(?P<qty>\d[\d\s,]*)\s*(?:[-–—]|â€”)?\s*Units\b",
            part,
            re.I,
        )
        if not match:
            return [row]

        item_desc = normalize_text(match.group("desc"))
        if index > 1:
            item_desc = normalize_text(f"Central venous catheter set: Size: {item_desc}")

        split_row = dict(row)
        split_row["title"] = item_desc
        split_row["description"] = normalize_text(f"{item_desc} - {institution_suffix}") if institution_suffix else item_desc
        split_row["item_desc"] = item_desc
        split_row["item_no"] = str(index)
        split_row["item_uom"] = base_uom
        split_row["item_quantity"] = normalize_text(match.group("qty")).replace(" ", "")
        split_row["dedup_key"] = f"{normalize_text(row.get('dedup_key'))}|part{index}"
        if index > 1:
            split_row["currency"] = ""
            split_row["amount"] = ""
            split_row["awarded_currency"] = ""
            split_row["awarded_value"] = ""
            split_row["item_award"] = ""
        split_rows.append(split_row)

    return split_rows


def normalize_saved_row(row: Dict[str, str]) -> Dict[str, str] | None:
    updated = dict(row)
    for field in ("amount", "awarded_value", "item_award"):
        updated[field] = _normalize_amount(updated.get(field, ""))
    if updated.get("amount") or updated.get("awarded_value"):
        updated["currency"] = "ZAR"
        updated["awarded_currency"] = "ZAR"
    explicit_hint = _explicit_item_hint(updated)
    if explicit_hint and not normalize_text(updated.get("item_quantity")):
        updated["item_desc"] = explicit_hint["item_desc"]
        updated["item_uom"] = explicit_hint["item_uom"]
        updated["item_quantity"] = explicit_hint["item_quantity"]
    advert_hint = _advert_quantity_hint(updated)
    if advert_hint and not normalize_text(updated.get("item_quantity")):
        updated["item_quantity"] = advert_hint["item_quantity"]
        if not normalize_text(updated.get("item_uom")) and advert_hint.get("item_uom"):
            updated["item_uom"] = advert_hint["item_uom"]
    return updated


def normalize_saved_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized_rows: List[Dict[str, str]] = []
    for row in rows:
        normalized = normalize_saved_row(row)
        if normalized is None:
            continue
        normalized_rows.extend(_split_explicit_multi_quantity_row(normalized))
    return normalized_rows


def _extract_contract_period(description: str) -> str:
    return extract_contract_period([description])


def _load_notice_pdf(notice_url: str) -> bytes:
    evidence_path = _pdf_evidence_path(notice_url).with_suffix(".pdf")
    try:
        content = _fetch_binary(notice_url)
        evidence_path.write_bytes(content)
        return content
    except RequestException:
        return evidence_path.read_bytes()


def _extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
    except Exception:
        return ""
    return "\n".join(page.extract_text() or "" for page in reader.pages[:1])


def _score_notice_text(text: str) -> int:
    normalized = normalize_text(text).lower()
    score = 0
    for token in (
        "quotation award",
        "quote description",
        "quotation number",
        "quote number",
        "date of award publication",
        "quote awarded to",
        "amount",
        "results of award",
        "quantity (if supplies)",
    ):
        if token in normalized:
            score += 3
    if "department of health" in normalized:
        score += 2
    return score


def _is_award_notice_text(text: str) -> bool:
    normalized = normalize_text(text).lower()
    if not normalized:
        return False
    if "quotation advert" in normalized and "quotation award" not in normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "quotation award",
            "results of award",
            "quote awarded to",
            "date of award publication",
        )
    )


def _ocr_pdf_text(content: bytes, notice_url: str) -> str:
    evidence_txt_path = _pdf_evidence_path(notice_url).with_suffix(".txt")
    if evidence_txt_path.exists():
        cached = evidence_txt_path.read_text(encoding="utf-8", errors="replace")
        if normalize_text(cached) and _score_notice_text(cached) >= 8:
            return cached
    if not TESSERACT_EXE.exists():
        raise FileNotFoundError(f"Tesseract not found at {TESSERACT_EXE}")

    with tempfile.TemporaryDirectory(prefix="kzn_quote_ocr_") as tmpdir:
        doc = fitz.open(stream=content, filetype="pdf")
        page = doc.load_page(0)
        base_image_path = Path(tmpdir) / "page_1.png"
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pix.save(base_image_path)
        doc.close()
        best_text = ""
        best_score = -1
        for angle in (0, 90, -90, 180):
            image_path = Path(tmpdir) / f"page_1_{angle}.png"
            if angle == 0:
                image_path.write_bytes(base_image_path.read_bytes())
            else:
                Image.open(base_image_path).rotate(angle, expand=True).save(image_path)
            out_base = Path(tmpdir) / f"page_1_{angle}_ocr"
            subprocess.run(
                [str(TESSERACT_EXE), str(image_path), str(out_base), "--psm", "6"],
                check=True,
                capture_output=True,
            )
            text = out_base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
            score = _score_notice_text(text)
            if score > best_score:
                best_score = score
                best_text = text
        text = best_text
    evidence_txt_path.write_text(text, encoding="utf-8")
    return text


def _extract_field(text: str, label: str, stop_patterns: tuple[str, ...]) -> str:
    stop = "|".join(stop_patterns)
    pattern = rf"{re.escape(label)}\s*[:;]?\s*(.+?)(?=\s*(?:{stop})\s*[:;]|$)"
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return ""
    return normalize_text(match.group(1))


def _parse_notice_id(text: str, notice_url: str) -> str:
    match = re.search(
        r"(?:Quotation|Quote)\s+number\s*[:;]?\s*(.+?)\s*(?:Quote Description|GuoteDeseripion|GuoteDescription|QuoteDeseripion|Quotation Award|Date of award publication|Date of Award Publication|Item Description|Item Category|Results of award|$)",
        text,
        re.I | re.S,
    )
    if match:
        return normalize_text(match.group(1).strip(" |"))
    return Path(urlparse(notice_url).path).stem


def _parse_publication_date_from_text(text: str) -> str:
    match = re.search(r"Date of award publication\s*[:;|]?\s*([0-3]?\d\s*[/-]\s*[01]?\d\s*[/-]\s*\d{4}|[0-3]?\d\s+[A-Za-z]+\s+\d{4})", text, re.I)
    if not match:
        return ""
    raw = normalize_text(match.group(1)).replace(" - ", "/").replace("-", "/")
    for fmt in ("%d/%m/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _extract_amount_value(text: str) -> str:
    segment_match = re.search(
        r"Amount\s*[:;|]?\s*(.+?)(?=\s*(?:B-BBEE status|B-BBEE Status|Total points|Total Points|Finance Manager Name|SCM Manager Name|Finance Manager Signature)\b|$)",
        text,
        re.I | re.S,
    )
    segments = [segment_match.group(1)] if segment_match else []
    segments.append(text)
    for segment in segments:
        candidates = re.findall(r"R?\s*(\d[\d\s,.-]*(?:[.,-]\s*\d{2})?)", segment, re.I)
        if not candidates:
            continue
        for candidate in reversed(candidates):
            normalized = _normalize_amount(candidate)
            if re.search(r"\d", normalized) and len(re.sub(r"\D", "", normalized)) >= 4:
                return normalized
    return ""


def _parse_notice_fields(entry: Dict[str, str], notice_text: str) -> Dict[str, str]:
    description_match = re.search(
        r"(?:Quote|Item)\s+Description\s*[:;|]?\s*(.+?)(?=\s*(?:Date of award publication|Date of Award Publication|Quote Advert Details|Institution Name|Quantity \(if supplies\))\b)",
        notice_text,
        re.I | re.S,
    )
    description = normalize_text(description_match.group(1).strip(" |")) if description_match else ""
    supplier_match = re.search(
        r"Quote\s+awarded\s*:?\s*to\s*[:;|]?\s*(.+?)(?=\s*(?:Amount|B-BBEE status|B-BBEE Status|Total points|Total Points|Finance Manager Name|SCM Manager Name)\b)",
        notice_text,
        re.I | re.S,
    )
    supplier = normalize_text(supplier_match.group(1).strip(" |")) if supplier_match else ""
    institution_match = re.search(
        r"Institution\s+Name\s*[:;|]?\s*(.+?)(?=\s*(?:Province|Department of entity|Department or Entity|Division or section|Place where goods/|Date quote was advertised)\b)",
        notice_text,
        re.I | re.S,
    )
    institution = normalize_text(institution_match.group(1).strip(" |")) if institution_match else ""
    supplier = re.sub(
        r"\b(Amount|Points for specific Goals|Total Price and points|Total Points|B-BBEE status|Finance Manager Name|Finance Manager Signature)\b.*$",
        "",
        supplier,
        flags=re.I,
    )
    supplier = normalize_text(re.sub(r"\b[iIl1]\b$", "", supplier).strip(" |:;,-"))
    if description and supplier.upper().endswith(description.upper()) and supplier.upper() != description.upper():
        supplier = normalize_text(supplier[: -len(description)]).strip(" |:;,-")
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", supplier):
        supplier = ""
    quantity, uom = extract_explicit_supply_quantity_uom(
        [
            notice_text,
            description,
            entry.get("description", ""),
        ]
    )
    contract_period = extract_contract_period(
        [
            notice_text,
            description,
            entry.get("description", ""),
        ]
    )
    return {
        "notice_id": _parse_notice_id(notice_text, entry["notice_url"]),
        "publication_date": _parse_publication_date_from_text(notice_text),
        "description": description,
        "institution": institution,
        "awarding_supplier_name": supplier,
        "awarded_value": _extract_amount_value(notice_text),
        "contract_period": contract_period,
        "item_quantity": quantity,
        "item_uom": uom,
    }


def _make_row(entry: Dict[str, str], parsed: Dict[str, str]) -> Dict[str, str]:
    base_description = normalize_text(parsed.get("description") or entry.get("description"))
    institution = normalize_text(parsed.get("institution") or entry.get("institution"))
    publication_date = parsed.get("publication_date") or entry.get("publication_date", "")
    description = base_description
    if institution and institution.lower() not in description.lower():
        description = normalize_text(f"{description} - {institution}")
    awarded_value = parsed.get("awarded_value", "")
    notice_id = normalize_text(parsed.get("notice_id") or Path(urlparse(entry["notice_url"]).path).stem)
    item_quantity = normalize_text(parsed.get("item_quantity"))
    item_uom = normalize_text(parsed.get("item_uom"))
    row = OutputRow(
        source=CONFIG.source,
        country=CONFIG.country,
        country_cc=CONFIG.country_cc,
        publication_date=publication_date,
        closing_date="",
        title=base_description or notice_id,
        description=description,
        buyer=BUYER_NAME,
        classification="",
        status="awarded",
        currency="ZAR" if awarded_value else "",
        amount=awarded_value,
        awarding_supplier_name=normalize_text(parsed.get("awarding_supplier_name")),
        awarded_currency="ZAR" if awarded_value else "",
        awarded_value=awarded_value,
        contract_period=normalize_text(parsed.get("contract_period"))
        or extract_contract_period([base_description, description, entry.get("description", "")]),
        item_no="1" if (base_description or item_quantity) else "",
        item_desc=base_description,
        item_uom=item_uom,
        item_quantity=item_quantity,
        item_unit_price="",
        item_award=awarded_value,
        notice_id=notice_id,
        notice_url=entry["notice_url"],
        query_text=f"live-medical-awarded:kzn-quotation:month={entry['month_label']}:notice={entry['notice_url']}",
        scraped_at=utc_now_iso(),
        dedup_key="|".join(
            part
            for part in (
                CONFIG.key,
                notice_id.lower(),
                institution.lower(),
                base_description.lower(),
            )
            if part
        ),
    )
    return row.to_dict()


def _parse_notice_row(entry: Dict[str, str]) -> Dict[str, str] | None:
    try:
        content = _load_notice_pdf(entry["notice_url"])
    except (RequestException, FileNotFoundError):
        return None
    notice_text = _extract_pdf_text(content)
    if "Quote Description" not in notice_text and "Quotation number" not in notice_text:
        try:
            notice_text = _ocr_pdf_text(content, entry["notice_url"])
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None
    if not _is_award_notice_text(notice_text):
        return None
    parsed = _parse_notice_fields(entry, notice_text)
    description = parsed.get("description") or entry.get("description", "")
    if not _is_medical_description(description):
        return None
    row = _make_row(entry, parsed)
    if not row["publication_date"] or not row["notice_id"] or not row["item_desc"]:
        return None
    return row


def smoke_probe() -> SmokeProbeResult:
    if not EVIDENCE_SAMPLE_MONTH_PATH.exists() or not EVIDENCE_SAMPLE_TXT_PATH.exists():
        return SmokeProbeResult(
            source_key=CONFIG.key,
            ok=False,
            mode="evidence_missing",
            detail="Saved KZN quotation-awards evidence files are missing.",
            sample_rows=[],
        )
    entry = {
        "month_label": "April 2026",
        "month_url": "https://www.kznhealth.gov.za/scm/awards-april-2026/",
        "pdf_name": "MSH12-26-27H.pdf",
        "institution": "Mseleni Hospital",
        "description": "Surgical items",
        "publication_date": "2026-04-30",
        "notice_url": "https://www.kznhealth.gov.za/wp-content/uploads/2026/05/MSH12-26-27H.pdf",
    }
    parsed = _parse_notice_fields(entry, EVIDENCE_SAMPLE_TXT_PATH.read_text(encoding="utf-8", errors="replace"))
    row = _make_row(entry, parsed)
    ok = bool(row["publication_date"] and row["notice_id"] and row["awarding_supplier_name"] and row["awarded_value"])
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=ok,
        mode="evidence_pdf_ocr",
        detail="Parsed saved KZN quotation-award OCR evidence for a surgical items award.",
        sample_rows=[row],
    )


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 50) -> List[Dict[str, str]]:
    del page_size
    listing_html = _load_text(LISTING_URL, EVIDENCE_LISTING_PATH)
    month_pages = _extract_month_pages(listing_html)
    entries: List[Dict[str, str]] = []
    for month in month_pages:
        month_html = _load_text(month["month_url"], _month_evidence_path(month["month_url"]))
        for entry in _parse_month_rows(month["month_label"], month["month_url"], month_html):
            publication_date = entry.get("publication_date", "")
            if not publication_date or publication_date < date_from or publication_date > date_to:
                continue
            if not _is_medical_description(entry.get("description", "")):
                continue
            entries.append(entry)

    unique_entries: List[Dict[str, str]] = []
    seen_urls = set()
    for entry in entries:
        notice_url = entry["notice_url"]
        if notice_url in seen_urls:
            continue
        seen_urls.add(notice_url)
        unique_entries.append(entry)

    indexed_rows: List[tuple[int, Dict[str, str]]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(_parse_notice_row, entry): index
            for index, entry in enumerate(unique_entries)
        }
        for future in as_completed(future_map):
            row = future.result()
            if row is not None:
                indexed_rows.append((future_map[future], row))

    indexed_rows.sort(key=lambda item: item[0])
    return [row for _, row in indexed_rows]
