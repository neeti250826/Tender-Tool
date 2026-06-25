"""
common.py  —  shared constants, EasyOCR OCR, PDF rasterisation, rule-based table parsing
=========================================================================================
Imported by scraper.py, extract_pdfs.py, and captcha_solver.py.
"""

import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

# ── Output column schema ─────────────────────────────────────────────────────
COLUMNS = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "closing_date",
    "title",
    "description",
    "buyer",
    "classification",
    "status",
    "currency",
    "amount",
    "awarding_agency_name",
    "supplier_name",
    "awarded_date",
    "awarded_value_detail",
    "contract_period",
    "bid_number",
    "item_no",
    "item_description",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_awarded_value",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]

# ── eProcure URLs ─────────────────────────────────────────────────────────────
BASE_URL = "https://eprocure.gov.in/eprocure/app"
CAPTCHA_URL = "https://eprocure.gov.in/eprocure/app?page=checkCaptchaImage&service=page"

# ── EasyOCR lazy loader ───────────────────────────────────────────────────────
_easyocr_reader = None


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _easyocr_reader


# ── Helpers ──────────────────────────────────────────────────────────────────
def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    s = s.replace("|", " ")
    s = s.replace('"', "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _is_valid_quantity(qty: str) -> bool:
    qty = _digits_only(qty)
    if not qty:
        return False
    if re.fullmatch(r"0+", qty):
        return False
    try:
        return float(qty) > 0
    except ValueError:
        return False

def _digits_only(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().replace(",", "")
    s = re.sub(r"[^\d.]", "", s)
    if s.count(".") > 1:
        first = s.find(".")
        s = s[: first + 1] + s[first + 1 :].replace(".", "")
    return s.strip(".")


def _safe_float(value: Any) -> float:
    s = _digits_only(value)
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _format_money(value: float) -> str:
    if value <= 0:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _money_tokens(text: str) -> list[str]:
    return re.findall(r"\b\d[\d,]*(?:\.\d{2,4})?\b", text)


def _normalise_name(name: str) -> str:
    name = _clean_text(name)
    name = re.sub(r"\bCREACTIVE\b", "C REACTIVE", name, flags=re.IGNORECASE)
    name = re.sub(r"\bphosphorou\s*s\b", "phosphorous", name, flags=re.IGNORECASE)
    name = re.sub(r"\bUrinary/\s*CSF\b", "Urinary/CSF", name, flags=re.IGNORECASE)
    name = re.sub(r"\bUrine/\s*CSF\b", "Urine/CSF", name, flags=re.IGNORECASE)
    name = re.sub(r"\bLDL-\s*Cholesterol\b", "LDL-Cholesterol", name, flags=re.IGNORECASE)
    name = re.sub(r"\bDehydrogen\b", "Dehydrogenase", name, flags=re.IGNORECASE)
    return _clean_text(name)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _month_diff(start_dt: datetime, end_dt: datetime) -> str:
    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    return str(max(months, 0))


def _format_contract_duration(start_dt: datetime, end_dt: datetime) -> str:
    return f"{start_dt.strftime('%b %y')} to {end_dt.strftime('%b %y')}"


def _extract_dates(text: str) -> list[datetime]:
    matches = re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text)
    dates = []
    for d, m, y in matches:
        try:
            dates.append(datetime(int(y), int(m), int(d)))
        except ValueError:
            pass
    return dates


def _split_quantity_uom(pack_size: str) -> tuple[str, str]:
    s = _clean_text(pack_size)
    if not s:
        return "", ""

    s = re.sub(r"\bnoS\b", "nos", s, flags=re.IGNORECASE)
    s = re.sub(r"\bno\b", "nos", s, flags=re.IGNORECASE)

    m = re.match(
        r"^\s*(\d+(?:\.\d+)?)\s+(tests?|kits?|nos?|numbers?|boxes?|packs?|units?)\s*$",
        s,
        flags=re.IGNORECASE,
    )
    if not m:
        return "", ""

    qty = _digits_only(m.group(1))
    uom = _clean_text(m.group(2))

    # reject garbage OCR quantities like 0, 00, 000, 0000
    if not qty or re.fullmatch(r"0+", qty):
        return "", ""

    return qty, uom


def _make_dedup_key(row: dict) -> str:
    parts = [
        row.get("notice_id", ""),
        row.get("item_no", ""),
        row.get("item_description", ""),
        row.get("item_quantity", ""),
        row.get("item_unit_price", ""),
        row.get("item_awarded_value", ""),
    ]
    return " | ".join(_clean_text(x).lower() for x in parts if _clean_text(x))


def _extract_metadata_from_text(text: str, notice_meta: dict) -> dict:
    text_clean = _clean_text(text)

    title = notice_meta.get("title", "") or ""
    ou = notice_meta.get("org", "") or ""
    sub_ou = ""
    device_category = "Clinical Chemistry Reagents"
    manufacturer = ""
    award_year = ""
    contract_duration = ""
    duration_months = ""

    if not ou:
        if re.search(r"\bAIIMS\b", text_clean, re.IGNORECASE) and re.search(r"\bBhopal\b", text_clean, re.IGNORECASE):
            ou = "AIIMS Bhopal"
        elif re.search(r"\bVALLABHBHAI PATEL CHEST INSTITUTE\b", text_clean, re.IGNORECASE):
            ou = "Vallabhbhai Patel Chest Institute"

    m = re.search(r"Department of ([A-Za-z &/-]+)", text_clean, flags=re.IGNORECASE)
    if m:
        sub_ou = _clean_text("Department of " + m.group(1))

    if re.search(r"immunoassay", text_clean, re.IGNORECASE):
        device_category = "Clinical Chemistry and Immunoassay Reagents"
    elif re.search(r"reagents|consumables", text_clean, re.IGNORECASE):
        device_category = "Consumables/Reagents"

    m = re.search(r"\bM/s\.?\s+([A-Za-z0-9 ,.&()/-]+)", text_clean)
    if m:
        manufacturer = _clean_text(m.group(1))

    dates = _extract_dates(text_clean)
    if len(dates) >= 2:
        dates_sorted = sorted(dates)
        start_dt = dates_sorted[0]
        end_dt = dates_sorted[-1]
        award_year = str(start_dt.year)
        contract_duration = _format_contract_duration(start_dt, end_dt)
        duration_months = _month_diff(start_dt, end_dt)
    elif len(dates) == 1:
        award_year = str(dates[0].year)

    if notice_meta.get("date") and not award_year:
        m = re.search(r"(20\d{2})", str(notice_meta["date"]))
        if m:
            award_year = m.group(1)

    return {
        "title": _clean_text(title),
        "ou": _clean_text(ou),
        "sub_ou": _clean_text(sub_ou),
        "device_category": _clean_text(device_category),
        "manufacturer": _clean_text(manufacturer),
        "award_year": _clean_text(award_year),
        "contract_duration": _clean_text(contract_duration),
        "duration_months": _clean_text(duration_months),
    }


def _notice_title(notice_meta: dict, metadata: dict) -> str:
    return _clean_text(notice_meta.get("title")) or _clean_text(metadata.get("title"))


def _notice_description(notice_meta: dict, row: Optional[dict] = None) -> str:
    aoc_desc = _clean_text(notice_meta.get("aoc_description"))
    if aoc_desc:
        return aoc_desc
    desc = _clean_text(notice_meta.get("description"))
    if desc:
        return desc
    if row:
        return _clean_text(row.get("test_name"))
    return ""


def _notice_amount(notice_meta: dict, row: Optional[dict] = None) -> str:
    direct = _clean_text(notice_meta.get("amount"))
    if direct:
        return direct
    awarded = _clean_text(notice_meta.get("awarded_value_detail"))
    if awarded:
        return awarded
    if row:
        return _clean_text(row.get("total_amount_rs"))
    return ""


# ── EasyOCR on page image ─────────────────────────────────────────────────────
def ocr_image_bytes(jpeg_bytes: bytes, page_num: Optional[int] = None, total_pages: Optional[int] = None) -> str:
    """
    OCR a JPEG/PNG image using EasyOCR and return reconstructed text lines.
    """
    import cv2
    import numpy as np

    reader = _get_easyocr_reader()

    nparr = np.frombuffer(jpeg_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return ""

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    height, width = gray.shape[:2]
    max_dim = max(height, width)
    scale = 1.0

    if max_dim > 5000:
        scale = 5000.0 / max_dim
    elif max_dim < 2200:
        scale = 1.4

    if scale != 1.0:
        new_w = max(1, int(width * scale))
        new_h = max(1, int(height * scale))
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
        logging.debug(f"OCR image resized from {width}x{height} to {new_w}x{new_h} (scale={scale:.3f})")

    def _results_to_text(results) -> str:
        if not results:
            return ""

        rows = []
        for box, text, conf in results:
            if not text or conf < 0.15:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x = min(xs)
            y = sum(ys) / len(ys)
            rows.append((y, x, _clean_text(text)))

        rows.sort(key=lambda r: (r[0], r[1]))

        merged_lines = []
        current = []
        current_y = None
        y_tol = 18

        for y, x, text in rows:
            if current_y is None:
                current_y = y
                current.append((x, text))
                continue

            if abs(y - current_y) <= y_tol:
                current.append((x, text))
            else:
                current.sort(key=lambda t: t[0])
                merged_lines.append(" ".join(t[1] for t in current))
                current = [(x, text)]
                current_y = y

        if current:
            current.sort(key=lambda t: t[0])
            merged_lines.append(" ".join(t[1] for t in current))

        return "\n".join(_clean_text(line) for line in merged_lines if _clean_text(line))

    def _score_text(text: str) -> tuple[int, int, int]:
        cleaned = text.strip()
        if not cleaned:
            return (0, 0, 0)
        lines = [ln for ln in cleaned.splitlines() if ln.strip()]
        alpha = len(re.findall(r"[A-Za-z]", cleaned))
        numeric = len(re.findall(r"\d", cleaned))
        return (len(lines), alpha, numeric)

    best_text = ""
    for label, candidate in (("0deg", gray), ("180deg", cv2.rotate(gray, cv2.ROTATE_180))):
        results = reader.readtext(
            candidate,
            detail=1,
            paragraph=False,
            width_ths=0.7,
            height_ths=0.8,
            ycenter_ths=0.5,
            mag_ratio=1.0,
            text_threshold=0.6,
            low_text=0.3,
            link_threshold=0.3,
        )
        text = _results_to_text(results)
        if _score_text(text) > _score_text(best_text):
            best_text = text

    return best_text


# ── OCR item parser ───────────────────────────────────────────────────────────
# ── OCR item parser ───────────────────────────────────────────────────────────
def _looks_like_table_page(text: str) -> bool:
    """
    Detect:
    1. header pages with words like 'catalogue', 'pack size', etc.
    2. continuation pages with repeated row patterns
    3. PO-style pages with qty/unit-rate/amount columns
    """
    t = text.lower()

    header_keywords = [
        "catalogue",
        "pack size",
        "unit rate",
        "total amount",
        "qty",
        "quantity",
        "qty reqd",
        "description",
        "test",
        "awarded value",
        "bidder name",
        "awarded bids list",
        "contract value",
        "aoc document",
    ]
    header_hits = sum(1 for k in header_keywords if k in t)

    table_header_hits = sum(
        1 for k in [
            "sr.no",
            "sr no",
            "s. no",
            "s.no",
            "item description",
            "description of items",
            "description specification",
            "specification qty",
            "unit rate",
            "offer rate",
            "pack rate",
            "amount",
            "qty",
            "uom",
        ] if k in t
    )
    narrative_markers = [
        "you are requested",
        "this issues with",
        "competent authority",
        "acknowledge receipt",
        "strictly as per",
        "including all taxes",
        "rupees one lakh",
        "total amount:",
    ]
    narrative_hits = sum(1 for k in narrative_markers if k in t)
    row_start_hits = len(re.findall(r"(?m)^\s*[/\\(|\[\]Il]*\s*\d{1,3}\s*[.)-]?\s+\S", text))
    test_hits = len(re.findall(r"\b\d+\s*Test\b", text, flags=re.IGNORECASE))
    cat_hits = len(re.findall(r"\b\d{10}\b", text))
    money_hits = len(_money_tokens(text))
    qty_nos_hits = len(re.findall(r"\b\d+\s+(?:nos?|tests?|kits?|boxes?|packs?)\b", text, flags=re.IGNORECASE))
    bidder_hits = len(re.findall(r"\b(?:bidder|awarded|contract|catalogue)\b", text, flags=re.IGNORECASE))

    if narrative_hits >= 2 and table_header_hits < 2 and row_start_hits < 3:
        return False

    if table_header_hits >= 2:
        return True

    if header_hits >= 3 and row_start_hits >= 2:
        return True

    if row_start_hits >= 3 and (test_hits >= 2 or cat_hits >= 2):
        return True

    if row_start_hits >= 3 and qty_nos_hits >= 2 and money_hits >= 4:
        return True

    if cat_hits >= 4 and money_hits >= 10:
        return True

    if row_start_hits >= 1 and bidder_hits >= 2 and money_hits >= 2:
        return True

    if bidder_hits >= 3 and money_hits >= 3:
        return True

    return False


def _is_noise_line(line: str) -> bool:
    line_l = line.lower()
    bad = [
        "identified by me",
        "signature",
        "assistant registrar",
        "payment terms",
        "delivery period",
        "terms & conditions",
        "purchase file",
        "mastercopy",
        "pto",
        "fax :",
        "telephone :",
    ]
    return any(b in line_l for b in bad)


def _match_row_prefix(line: str) -> Optional[tuple[str, str]]:
    """
    OCR often mangles row starts as /10, (11, I2, l3, etc.
    Accept those variants and return (sl_no, rest_of_line).
    """
    m = re.match(r"^\s*[/\\(|\[\]Il]*\s*(\d{1,3})\s*[.)-]?\s*(.*)$", line)
    if not m:
        return None
    sl_no = _clean_text(m.group(1))
    rest = _clean_text(m.group(2))
    return sl_no, rest


def _is_standalone_row_number(line: str) -> bool:
    matched = _match_row_prefix(line)
    return bool(matched and not matched[1])


def _looks_like_item_line_without_row_number(line: str) -> bool:
    text = _clean_text(line)
    lower = text.lower()
    if not text:
        return False
    if any(k in lower for k in ["sr_no", "item description", "specification", "unit rate", "amount"]):
        return False
    if re.match(r"^\s*(print|organisation chain|tender id|tender ref no|tender title)\b", lower):
        return False
    money_hits = len(_money_tokens(text))
    alpha_hits = len(re.findall(r"[A-Za-z]", text))
    return money_hits >= 1 and alpha_hits >= 3


def _merge_split_row_number_lines(lines: list[str]) -> list[str]:
    merged = []
    i = 0
    while i < len(lines):
        line = _clean_text(lines[i])
        if _is_standalone_row_number(line) and i + 1 < len(lines):
            next_line = _clean_text(lines[i + 1])
            if next_line:
                merged.append(f"{line} {next_line}")
                i += 2
                continue
        merged.append(line)
        i += 1
    return merged


def _extract_row_blocks(lines: list[str]) -> list[str]:
    """
    Group OCR lines into item-sized blocks.
    """
    blocks = []
    current = []

    footer_noise = re.compile(
        r"(valid|notary|gopal|krishna|bajpai|govt|of mp|assistant registrar|purchase file|mastercopy|pto)",
        flags=re.IGNORECASE,
    )

    for line in lines:
        line = _clean_text(line)
        if not line:
            continue

        if footer_noise.search(line):
            if current:
                blocks.append(" ".join(current))
                current = []
            break

        if _match_row_prefix(line):
            if current:
                blocks.append(" ".join(current))
            current = [line]
        elif _looks_like_item_line_without_row_number(line):
            if current:
                blocks.append(" ".join(current))
            current = [line]
        else:
            if current:
                current.append(line)

    if current:
        blocks.append(" ".join(current))

    return blocks


def _extract_row_from_block_rcnoa(block: str) -> Optional[dict]:
    """
    RCNOA-style rows, e.g.
      5. Amylase 12 2.5200 23.52 8056811190 21.00 15750 750 Test
    """
    text = _clean_text(block)
    if len(text) < 15:
        return None

    pack_match = re.search(r"(\d+\s*Test)\b", text, flags=re.IGNORECASE)
    cat_match = re.search(r"\b(\d{10})\b", text)
    row_match = re.match(r"^\s*(\d{1,3})[.)]?\s+(.*)$", text)

    if not pack_match or not cat_match or not row_match:
        return None

    pack_size = _clean_text(pack_match.group(1))
    catalogue_no = cat_match.group(1)
    sl_no = row_match.group(1)
    after_sl = row_match.group(2)

    work = after_sl.replace(pack_size, " ").replace(catalogue_no, " ")
    work = _clean_text(work)

    test_name = re.sub(r"\b\d+(?:\.\d+)?\b", " ", work)
    test_name = _normalise_name(test_name)
    test_name = _clean_text(test_name)
    if not test_name:
        return None

    nums = re.findall(r"\d+(?:\.\d+)?", text)

    pack_num_match = re.search(r"(\d+)\s*Test", pack_size, flags=re.IGNORECASE)
    pack_num = pack_num_match.group(1) if pack_num_match else ""

    filtered = []
    for n in nums:
        if n == sl_no:
            continue
        if n == catalogue_no:
            continue
        if pack_num and n == pack_num:
            continue
        filtered.append(n)

    if len(filtered) < 5:
        return None

    tail = filtered[-5:]

    gst_percent = tail[0]
    taxes_rs = tail[1]
    total_amount_ocr = tail[2]
    unit_rate = tail[3]
    price_of_pack = tail[4]

    qty, _ = _split_quantity_uom(pack_size)
    calculated_value = _safe_float(qty) * _safe_float(unit_rate)

    return {
        "sl_no": sl_no,
        "test_name": test_name,
        "pack_size": pack_size,
        "price_of_pack": _digits_only(price_of_pack),
        "gst_percent": _digits_only(gst_percent),
        "catalogue_no": catalogue_no,
        "unit_rate": _digits_only(unit_rate),
        "taxes_rs": _digits_only(taxes_rs),
        "total_amount_rs": _format_money(calculated_value if calculated_value > 0 else _safe_float(total_amount_ocr)),
    }


def _extract_row_from_block_p636(block: str) -> Optional[dict]:
    """
    Purchase-order style rows, e.g.
      1. M-MuLv Reverse Transcriptase-10,000 units cat no: M0253S 6 nos 19,418.89 1,16,513.34

    OCR may distort:
      - 6 nos -> noS
      - quantity may be dropped
      - semicolons/colons may vary
    """
    text = _clean_text(block)
    if len(text) < 10:
        return None

    row_match = _match_row_prefix(text)
    if not row_match:
        return None

    sl_no, rest = row_match

    # normalize common OCR issues
    rest = re.sub(r"\bnoS\b", "nos", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\bno\b", "nos", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\bcat\s*no[:.]?\b", "cat no ", rest, flags=re.IGNORECASE)

    # pull trailing money values
    money_vals = _money_tokens(rest)
    if len(money_vals) < 2:
        return None

    unit_rate = _digits_only(money_vals[-2])
    total_ocr = _digits_only(money_vals[-1])

    # try explicit quantity + uom
    qty = ""
    uom = ""

    qty_uom_patterns = [
        r"\b(\d+(?:\.\d+)?)\s*(nos?|tests?|kits?|boxes?|packs?|units?)\b",
        r"\b(\d+(?:\.\d+)?)\s*(Test)\b",
    ]

    for pat in qty_uom_patterns:
        m = re.search(pat, rest, flags=re.IGNORECASE)
        if m:
            qty = _digits_only(m.group(1))
            uom = _clean_text(m.group(2))
            break

    # fallback: derive quantity from total / unit_rate if explicit qty missing
    if not qty and unit_rate and total_ocr:
        ur = _safe_float(unit_rate)
        tv = _safe_float(total_ocr)
        if ur > 0 and tv > 0:
            guessed_qty = tv / ur
            rounded = round(guessed_qty)
            if abs(guessed_qty - rounded) < 0.05:
                qty = str(int(rounded))
                uom = "nos"

    pack_size = f"{qty} {uom}".strip() if qty and uom else ""

    # remove qty/uom and money from description
    description = rest

    if qty and uom:
        description = re.sub(
            rf"\b{re.escape(qty)}\s*{re.escape(uom)}\b",
            " ",
            description,
            flags=re.IGNORECASE,
        )

    for mv in money_vals:
        description = description.replace(mv, " ")

    description = _normalise_name(description)
    description = _clean_text(description)

    if not description:
        return None

    calculated_value = _safe_float(qty) * _safe_float(unit_rate) if qty and unit_rate else _safe_float(total_ocr)

    return {
        "sl_no": sl_no,
        "test_name": description,
        "pack_size": pack_size,
        "price_of_pack": "",
        "gst_percent": "",
        "catalogue_no": "",
        "unit_rate": unit_rate,
        "taxes_rs": "",
        "total_amount_rs": _format_money(calculated_value),
    }


def _extract_row_from_block_loose(block: str) -> Optional[dict]:
    """
    Very loose fallback:
    - line starts with row number
    - contains quantity+uom OR pack size
    - contains at least one money value
    """
    text = _clean_text(block)

    m = _match_row_prefix(text)
    if not m:
        return None

    sl_no, rest = m

    # quantity + uom fallback
    qty_uom_match = re.search(r"\b(\d+(?:\.\d+)?)\s+(nos?|tests?|kits?|boxes?|packs?)\b", rest, flags=re.IGNORECASE)
    pack_match = re.search(r"\b(\d+(?:\.\d+)?)\s+Test\b", rest, flags=re.IGNORECASE)

    pack_size = ""
    qty = ""
    uom = ""

    if qty_uom_match:
        qty = _digits_only(qty_uom_match.group(1))
        uom = _clean_text(qty_uom_match.group(2))
        pack_size = f"{qty} {uom}"
    elif pack_match:
        qty = _digits_only(pack_match.group(1))
        uom = "Test"
        pack_size = f"{qty} Test"

    money_vals = _money_tokens(rest)
    if not money_vals:
        return None

    unit_rate = _digits_only(money_vals[-2]) if len(money_vals) >= 2 else _digits_only(money_vals[-1])
    total_ocr = _digits_only(money_vals[-1])

    test_name = rest
    test_name = re.sub(r"\b\d+(?:\.\d+)?\s+(?:nos?|tests?|kits?|boxes?|packs?)\b", " ", test_name, flags=re.IGNORECASE)
    test_name = re.sub(r"\b\d[\d,]*(?:\.\d{2,4})?\b", " ", test_name)
    test_name = _normalise_name(test_name)
    test_name = _clean_text(test_name)

    if not test_name:
        return None

    calculated_value = _safe_float(qty) * _safe_float(unit_rate)

    return {
        "sl_no": sl_no,
        "test_name": test_name,
        "pack_size": pack_size,
        "price_of_pack": "",
        "gst_percent": "",
        "catalogue_no": "",
        "unit_rate": unit_rate,
        "taxes_rs": "",
        "total_amount_rs": _format_money(calculated_value if calculated_value > 0 else _safe_float(total_ocr)),
    }


def _extract_row_from_block_tabular(block: str) -> Optional[dict]:
    """
    Generic fallback for scanned table rows such as:
      1 Albumin 5000 Transasia ML 5x50 237.5 0.95 4,750.00
      26 Blood Agar 1000 Plates 50 3500 70.00 70,000.00
      17 Kit Preventive Maintenance Nos 123,600 123,600
    Strategy:
    - use the last money token as row total
    - use the previous money token as unit price when present
    - find a likely UOM token and treat the nearest numeric token before it as quantity
    - keep the text before quantity as the item description
    """
    text = _clean_text(block)
    row_match = _match_row_prefix(text)
    if not row_match:
        return None

    sl_no, rest = row_match
    if not rest:
        return None

    rest = re.sub(r"\bnoS\b", "nos", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\bpcs\.\b", "pcs", rest, flags=re.IGNORECASE)

    money_matches = list(re.finditer(r"\b\d[\d,]*(?:\.\d{1,4})?\b", rest))
    if not money_matches:
        return None

    total_ocr = _digits_only(money_matches[-1].group(0))
    unit_rate = _digits_only(money_matches[-2].group(0)) if len(money_matches) >= 2 else ""

    uom_match = re.search(r"\b(ml|nos?|pcs?|plates?|kits?|tests?|boxes?|packs?|vials?)\b", rest, flags=re.IGNORECASE)
    qty = ""
    uom = ""
    description = rest

    if uom_match:
        uom = _clean_text(uom_match.group(1))
        before_uom = rest[:uom_match.start()]
        qty_matches = list(re.finditer(r"\b\d[\d,]*(?:\.\d+)?\b", before_uom))
        if qty_matches:
            qty = _digits_only(qty_matches[-1].group(0))
            description = before_uom[:qty_matches[-1].start()]
        else:
            description = before_uom
    else:
        # fallback: use all text before the last two money values as the description
        cutoff = money_matches[-2].start() if len(money_matches) >= 2 else money_matches[-1].start()
        description = rest[:cutoff]

    description = _normalise_name(description)
    description = _clean_text(description)
    if not description:
        return None

    if qty and not _is_valid_quantity(qty):
        qty = ""
        uom = ""

    pack_size = f"{qty} {uom}".strip() if qty and uom else ""
    calculated_value = _safe_float(qty) * _safe_float(unit_rate) if qty and unit_rate else _safe_float(total_ocr)

    return {
        "sl_no": sl_no,
        "test_name": description,
        "pack_size": pack_size,
        "price_of_pack": "",
        "gst_percent": "",
        "catalogue_no": "",
        "unit_rate": unit_rate,
        "taxes_rs": "",
        "total_amount_rs": _format_money(calculated_value if calculated_value > 0 else _safe_float(total_ocr)),
    }


def _extract_row_from_block_unnumbered(block: str) -> Optional[dict]:
    """
    Fallback for OCR rows where the serial number is missing or detached,
    but the item description and money columns are still visible.
    """
    text = _clean_text(block)
    if not text or _match_row_prefix(text):
        return None
    if not _looks_like_item_line_without_row_number(text):
        return None

    money_vals = _money_tokens(text)
    if not money_vals:
        return None

    unit_rate = _digits_only(money_vals[-2]) if len(money_vals) >= 2 else _digits_only(money_vals[-1])
    total_ocr = _digits_only(money_vals[-1])

    qty = ""
    uom = ""
    qty_uom_match = re.search(r"\b(\d+(?:\.\d+)?)\s+(nos?|tests?|kits?|boxes?|packs?|units?)\b", text, flags=re.IGNORECASE)
    if qty_uom_match:
        qty = _digits_only(qty_uom_match.group(1))
        uom = _clean_text(qty_uom_match.group(2))

    pack_size = f"{qty} {uom}".strip() if qty and uom else ""

    description = text
    if qty and uom:
        description = re.sub(
            rf"\b{re.escape(qty)}\s*{re.escape(uom)}\b",
            " ",
            description,
            flags=re.IGNORECASE,
        )
    for mv in money_vals:
        description = description.replace(mv, " ")
    description = _normalise_name(description)
    description = _clean_text(description)
    if not description:
        return None

    calculated_value = _safe_float(qty) * _safe_float(unit_rate) if qty and unit_rate else _safe_float(total_ocr)
    return {
        "sl_no": "",
        "test_name": description,
        "pack_size": pack_size,
        "price_of_pack": "",
        "gst_percent": "",
        "catalogue_no": "",
        "unit_rate": unit_rate,
        "taxes_rs": "",
        "total_amount_rs": _format_money(calculated_value if calculated_value > 0 else _safe_float(total_ocr)),
    }


def _extract_row_from_single_line(line: str) -> Optional[dict]:
    """
    Fallback for PDFs where OCR merges an entire row into one line.
    """
    line = _clean_text(line)
    if not (_match_row_prefix(line) or _looks_like_item_line_without_row_number(line)):
        return None

    for fn in (
        _extract_row_from_block_p636,
        _extract_row_from_block_rcnoa,
        _extract_row_from_block_tabular,
        _extract_row_from_block_loose,
        _extract_row_from_block_unnumbered,
    ):
        row = fn(line)
        if row:
            return row
    return None


def _extract_row_from_block(block: str) -> Optional[dict]:
    """
    Ordered fallback parser chain.
    """
    for fn in (
        _extract_row_from_block_p636,
        _extract_row_from_block_rcnoa,
        _extract_row_from_block_tabular,
        _extract_row_from_block_loose,
        _extract_row_from_block_unnumbered,
    ):
        row = fn(block)
        if row:
            return row
    return None


def _extract_bidder_summary_rows(lines: list[str]) -> list[dict]:
    rows = []
    seen_names = set()
    in_qualified_section = False

    for line in lines:
        text = _clean_text(line)
        lower = text.lower()

        if "following technically qualified firms" in lower or "technically qualified firms" in lower:
            in_qualified_section = True
            continue

        if in_qualified_section and any(
            marker in lower for marker in ("declaration", "signature", "approved", "recommendation", "committee")
        ):
            break

        patterns = []
        if in_qualified_section:
            patterns.append(r"^\s*(\d{1,2})[.)]?\s+(.+)$")

        patterns.extend(
            [
                r"^\s*bidder\s*(\d{1,2})\s*[-:]\s*(.+)$",
                r"^\s*(\d{1,2})[.)]?\s+(m/?s\.?\s+.+)$",
                r"^\s*(\d{1,2})[.)]?\s+(ms\s+.+)$",
            ]
        )

        match = None
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if match:
                break

        if not match:
            continue

        sl_no = _clean_text(match.group(1))
        supplier_name = _clean_text(match.group(2))
        supplier_name = re.sub(r"\b(?:the firm|firm)\b", " ", supplier_name, flags=re.IGNORECASE)
        supplier_name = _clean_text(supplier_name.strip(" -:;,."))

        if not supplier_name:
            continue

        if len(supplier_name) < 4:
            continue

        if len(supplier_name.split()) > 12:
            continue

        supplier_key = supplier_name.lower()
        if supplier_key in seen_names:
            continue
        seen_names.add(supplier_key)

        rows.append(
            {
                "sl_no": sl_no,
                "test_name": "Technically qualified bidder",
                "pack_size": "",
                "price_of_pack": "",
                "gst_percent": "",
                "catalogue_no": "",
                "unit_rate": "",
                "taxes_rs": "",
                "total_amount_rs": "",
                "supplier_name": supplier_name,
            }
        )

    return rows


def _is_probable_item_description(value: str) -> bool:
    desc = _clean_text(value)
    if not desc:
        return False

    lower = desc.lower()
    bad_markers = [
        "organisation chain",
        "tender id",
        "tender ref no",
        "tender title",
        "dear sir",
        "sir/madam",
        "please refer",
        "ref your quotation",
        "quotation no",
        "quotation/bid no",
        "you are requested",
        "terms and conditions",
        "all terms and condition",
        "grand total",
        "total amount",
        "total only",
        "gst @",
        "gst %",
        "cgst",
        "sgst",
        "igst",
        "delivery by",
        "delivery within",
        "delivery place",
        "force majeure",
        "arbitration",
        "yours faithfully",
        "acknowledge receipt",
        "accounts officer",
        "bill section",
        "budget section",
        "party bill section",
        "central public procurement portal",
        "president of india",
        "competent authority",
        "bank details",
        "account details",
        "freight charges",
        "payment against delivery",
        "payment terms",
        "proforma invoice",
        "indentor",
        "post box no",
        "plot no",
        "pin -",
        "station,",
        "store (on working days",
        "office copy",
        "copy to",
        "r/o indentor",
        "dated:",
        "to, m/s",
        "gst %",
        "purity :",
        "appearance :",
        "termsand conditions",
        "contd__",
    ]
    if any(marker in lower for marker in bad_markers):
        return False

    if re.fullmatch(r"[*./\-,:;%()\d\s]+", desc):
        return False

    if re.fullmatch(r"(?:total|gst|amount|rate|qty|uom|nos?)", lower):
        return False

    if len(desc) <= 3:
        return False

    if len(desc.split()) > 18 and ":" in desc:
        return False

    return True


def _trim_to_item_section(lines: list[str]) -> list[str]:
    if not lines:
        return []

    start_idx = 0
    header_patterns = [
        r"sr\s*\.?\s*no",
        r"s\s*\.?\s*no",
        r"lot\s*no",
        r"item description",
        r"description of items",
        r"description",
        r"specification",
        r"qty",
        r"uom",
        r"unit rate",
        r"amount",
        r"offer rate",
        r"pack rate",
    ]

    for idx, line in enumerate(lines):
        ll = line.lower()
        hits = sum(1 for pat in header_patterns if re.search(pat, ll))
        if hits >= 2:
            start_idx = idx + 1
            break
    else:
        for idx, line in enumerate(lines):
            if not _match_row_prefix(line):
                continue
            nearby_rows = 0
            for probe in lines[idx : idx + 6]:
                if _match_row_prefix(probe) or _looks_like_item_line_without_row_number(probe):
                    nearby_rows += 1
            if nearby_rows >= 2:
                start_idx = idx
                break

    end_markers = [
        "grand total",
        "total amount",
        "total value",
        "including all taxes",
        "delivery within",
        "delivery place",
        "payment against delivery",
        "payment terms",
        "freight charges",
        "acknowledge receipt",
        "you are requested",
        "this issues with",
        "competent authority",
        "yours faithfully",
        "bank details",
        "account details",
        "r/o indentor",
        "indentor",
        "office copy",
        "copy to",
    ]

    trimmed = []
    for line in lines[start_idx:]:
        ll = line.lower()
        if any(marker in ll for marker in end_markers):
            break
        trimmed.append(line)
    return trimmed


def _row_has_item_signal(row: dict) -> bool:
    desc = _clean_text(row.get("item_description"))
    qty = _clean_text(row.get("item_quantity"))
    uom = _clean_text(row.get("item_uom")).lower()
    unit_price = _clean_text(row.get("item_unit_price"))
    total_value = _clean_text(row.get("item_awarded_value"))

    if not desc:
        return False

    allowed_uoms = {"ml", "nos", "no", "pcs", "pc", "plates", "kits", "kit", "tests", "test", "boxes", "box", "packs", "pack", "vials", "vial", "units", "unit"}

    money_count = int(bool(unit_price)) + int(bool(total_value))
    qty_ok = _is_valid_quantity(qty)
    uom_ok = uom in allowed_uoms if uom else False

    if qty_ok and money_count >= 1:
        return True
    if qty_ok and uom_ok:
        return True
    if money_count >= 2 and len(desc.split()) <= 14:
        return True
    return False


def _looks_like_equipment_notice(notice_meta: dict) -> bool:
    text = " ".join(
        _clean_text(notice_meta.get(k))
        for k in ("title", "description", "aoc_description")
    ).lower()
    keywords = [
        "equipment",
        "system",
        "scope",
        "analyzer",
        "monitor",
        "manometry",
        "videoscope",
        "robotic",
        "imaging",
        "detector",
        "cart",
        "unit",
        "hplc",
        "pcr",
        "bronchoscope",
        "sputtering",
        "vapor deposition",
        "cystoscopy",
        "ergometer",
        "nephroscope",
    ]
    return any(keyword in text for keyword in keywords)


def _significant_tokens(value: str) -> set[str]:
    text = _clean_text(value).lower()
    tokens = re.findall(r"[a-z0-9]{4,}", text)
    stop = {
        "supply", "procurement", "purchase", "make", "with", "from", "under",
        "years", "year", "hospital", "lab", "system", "equipment", "award",
        "awarded", "installation", "commissioning", "document", "tender",
    }
    return {t for t in tokens if t not in stop}


def _looks_like_equipment_item_description(desc: str, title: str) -> bool:
    text = _clean_text(desc)
    lower = text.lower()
    if not text:
        return False

    bad = [
        "warranty",
        "cmc",
        "camc",
        "amc",
        "installation and commissioning",
        "installation",
        "commissioning",
        "special instructions",
        "consignee name",
        "consignee address",
        "name & address",
        "dr.",
        "mumbai",
        "bhopal",
        "delhi",
        "karnataka",
        "security by the purchaser",
        "performance security",
        "payment",
        "downtime",
        "liquidated",
        "months after installation",
        "the committee",
        "quoted price",
        "negotiated price",
        "l- bidder",
        "bidder",
        "submitted by",
        "page of",
    ]
    if any(marker in lower for marker in bad):
        return False

    title_tokens = _significant_tokens(title)
    desc_tokens = _significant_tokens(text)
    overlap = len(title_tokens & desc_tokens)

    equipment_words = [
        "system", "scope", "analyzer", "monitor", "videoscope", "cart", "unit",
        "detector", "bronchoscope", "manometry", "hplc", "pcr", "imaging",
        "nephroscope", "ergometer", "cystoscopy", "deposition", "sputtering",
    ]
    has_equipment_word = any(word in lower for word in equipment_words)
    has_make_model = any(word in lower for word in ["model", "make", "fujifilm", "olympus", "becton", "bruker", "thermo"])

    return overlap >= 1 or has_equipment_word or has_make_model


def _equipment_fallback_record(notice_meta: dict) -> Optional[dict]:
    title = _clean_text(notice_meta.get("title"))
    if not title:
        return None

    notice_id = _clean_text(notice_meta.get("notice_id")) or _clean_text(notice_meta.get("refNo")) or title
    amount = _notice_amount(notice_meta)
    unit_price = _clean_text(amount)
    item_value = _clean_text(amount)

    row = {
        "source": "eprocure_india",
        "country": "India",
        "country_code": "IN",
        "publication_date": _clean_text(notice_meta.get("date")),
        "closing_date": _clean_text(notice_meta.get("closing_date")),
        "title": title,
        "description": _notice_description(notice_meta),
        "buyer": _clean_text(notice_meta.get("org")),
        "classification": "",
        "status": "awarded",
        "currency": "INR",
        "amount": amount,
        "awarding_agency_name": _clean_text(notice_meta.get("org")),
        "supplier_name": _clean_text(notice_meta.get("supplier_name")),
        "awarded_date": "",
        "awarded_value_detail": _clean_text(notice_meta.get("awarded_value_detail")),
        "contract_period": "",
        "bid_number": _clean_text(notice_meta.get("bid_number")),
        "item_no": "1",
        "item_description": title,
        "item_uom": "nos",
        "item_quantity": "1",
        "item_unit_price": unit_price,
        "item_awarded_value": item_value,
        "notice_id": notice_id,
        "notice_url": _clean_text(notice_meta.get("link")),
        "query_text": _clean_text(notice_meta.get("query_text")),
        "scraped_at_utc": _utc_now_iso(),
        "dedup_key": "",
    }
    row["dedup_key"] = _make_dedup_key(row)
    return {col: _clean_text(row.get(col, "")) for col in COLUMNS}


def _postprocess_equipment_records(records: list[dict], notice_meta: dict) -> list[dict]:
    if not records or not _looks_like_equipment_notice(notice_meta):
        return records

    title = _clean_text(notice_meta.get("title"))
    filtered = []
    for row in records:
        desc = _clean_text(row.get("item_description"))
        if _looks_like_equipment_item_description(desc, title):
            filtered.append(row)

    if filtered:
        return filtered

    fallback = _equipment_fallback_record(notice_meta)
    return [fallback] if fallback else []


def _finalize_item_records(records: list[dict]) -> list[dict]:
    if not records:
        return []

    numbered_count = sum(1 for row in records if _clean_text(row.get("item_no")).isdigit())
    finalized = []

    for row in records:
        desc = _clean_text(row.get("item_description"))
        qty = _clean_text(row.get("item_quantity"))
        unit_price = _clean_text(row.get("item_unit_price"))
        total_value = _clean_text(row.get("item_awarded_value"))
        item_no = _clean_text(row.get("item_no"))

        if not _is_probable_item_description(desc):
            continue

        if not _row_has_item_signal(row):
            continue

        if numbered_count >= 2 and not item_no:
            compact_table_like = len(desc.split()) <= 10 and any([qty, unit_price, total_value])
            if not compact_table_like:
                continue

        finalized.append(dict(row))

    next_item_no = 1
    for row in finalized:
        item_no = _clean_text(row.get("item_no"))
        if item_no.isdigit():
            next_item_no = int(item_no) + 1
        elif numbered_count >= 2:
            row["item_no"] = str(next_item_no)
            next_item_no += 1

        row["item_description"] = _clean_text(row.get("item_description"))
        row["dedup_key"] = _make_dedup_key(row)

    return finalized


def parse_items_from_ocr_text(
    ocr_text: str,
    notice_meta: dict,
    page_num: int,
) -> list[dict]:
    """
    Rule-based table parser from EasyOCR text only.
    Uses multiple fallback parsers and preserves partial rows when possible.
    """
    if not ocr_text.strip():
        logging.info(f"    Page {page_num}: OCR text empty.")
        return []

    loose_signal = bool(re.search(r"\b(?:awarded|bidder|contract|catalogue|unit rate|amount|qty)\b", ocr_text, flags=re.IGNORECASE))

    if not _looks_like_table_page(ocr_text) and not loose_signal:
        logging.info(f"    Page {page_num}: no item-table pattern detected.")
        return []

    metadata = _extract_metadata_from_text(ocr_text, notice_meta)

    raw_lines = [_clean_text(x) for x in ocr_text.splitlines()]
    lines = [x for x in raw_lines if x and not _is_noise_line(x)]
    lines = _trim_to_item_section(lines)

    cleaned = []
    for line in lines:
        ll = line.lower()
        if any(k in ll for k in [
            "si.no",
            "name of",
            "pack size",
            "catalogue no",
            "unit rate",
            "reportable",
            "taxes in rs",
            "cost per",
            "amount",
            "qty. reqd",
            "qty reqd",
            "grand total",
            "total value",
            "gst 5%",
            "gst @",
            "total 3,",
        ]):
            continue
        cleaned.append(line)
    cleaned = _merge_split_row_number_lines(cleaned)

    records = []
    seen = set()

    # Pass 1: multi-line blocks
    blocks = _extract_row_blocks(cleaned)
    parsed_any = False

    for block in blocks:
        row = _extract_row_from_block(block)
        if not row:
            continue
        parsed_any = True

        item_quantity, item_uom = _split_quantity_uom(row["pack_size"])
        # fallback: recover quantity/uom from description or row totals
        if not _is_valid_quantity(item_quantity) or not item_uom:
            desc = _clean_text(row.get("test_name", ""))

            m = re.search(
                r"\b(\d+(?:\.\d+)?)\s*(tests?|kits?|nos?|boxes?|packs?|units?)\b",
                desc,
                flags=re.IGNORECASE,
            )
            if m:
                candidate_qty = _digits_only(m.group(1))
                candidate_uom = _clean_text(m.group(2))

                if _is_valid_quantity(candidate_qty):
                    item_quantity = candidate_qty
                    if not item_uom:
                        item_uom = candidate_uom

        # derive quantity only if still missing or invalid
        if not _is_valid_quantity(item_quantity) and row.get("unit_rate") and row.get("total_amount_rs"):
            ur = _safe_float(row["unit_rate"])
            tv = _safe_float(row["total_amount_rs"])
            if ur > 0 and tv > 0:
                guessed_qty = tv / ur
                rounded = round(guessed_qty)

                # only accept near-integer, non-zero quantities
                if rounded > 0 and abs(guessed_qty - rounded) < 0.05:
                    item_quantity = str(int(rounded))

        # final cleanup
        if not _is_valid_quantity(item_quantity):
            item_quantity = ""

        if not item_uom and item_quantity:
            item_uom = "nos"
        notice_id = _clean_text(notice_meta.get("notice_id")) or _clean_text(notice_meta.get("refNo")) or _clean_text(notice_meta.get("title"))
        buyer = _clean_text(notice_meta.get("org")) or metadata["ou"]
        publication_date = _clean_text(notice_meta.get("date"))
        awarded_date = metadata["award_year"]

        if _is_valid_quantity(item_quantity):
            item_awarded_value = _format_money(_safe_float(item_quantity) * _safe_float(row["unit_rate"]))
        else:
            item_awarded_value = ""
        if not _is_valid_quantity(item_quantity):
            item_quantity = ""
            item_uom = ""
        final_row = {
            "source": "eprocure_india",
            "country": "India",
            "country_code": "IN",
            "publication_date": publication_date,
            "closing_date": _clean_text(notice_meta.get("closing_date")),
            "title": _notice_title(notice_meta, metadata),
            "description": _notice_description(notice_meta, row),
            "buyer": buyer,
            "classification": metadata["device_category"],
            "status": "awarded",
            "currency": "INR",
            "amount": _notice_amount(notice_meta, row),
            "awarding_agency_name": buyer,
            "supplier_name": metadata["manufacturer"],
            "awarded_date": awarded_date,
            "awarded_value_detail": _clean_text(notice_meta.get("awarded_value_detail")),
            "contract_period": metadata["contract_duration"],
            "bid_number": _clean_text(notice_meta.get("bid_number")),
            "item_no": row["sl_no"],
            "item_description": row["test_name"],
            "item_uom": item_uom,
            "item_quantity": item_quantity,
            "item_unit_price": row["unit_rate"],
            "item_awarded_value": item_awarded_value,
            "notice_id": notice_id,
            "notice_url": _clean_text(notice_meta.get("link")),
            "query_text": _clean_text(notice_meta.get("query_text")),
            "scraped_at_utc": _utc_now_iso(),
            "dedup_key": "",
        }

        final_row["dedup_key"] = _make_dedup_key(final_row)
        dedupe_key = final_row["dedup_key"]
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        records.append({col: _clean_text(final_row.get(col, "")) for col in COLUMNS})

    # Pass 2: single-line fallback if block parsing found nothing
    if not parsed_any:
        for line in cleaned:
            row = _extract_row_from_single_line(line)
            if not row:
                continue

            item_quantity, item_uom = _split_quantity_uom(row["pack_size"])
            notice_id = _clean_text(notice_meta.get("notice_id")) or _clean_text(notice_meta.get("refNo")) or _clean_text(notice_meta.get("title"))
            buyer = _clean_text(notice_meta.get("org")) or metadata["ou"]
            publication_date = _clean_text(notice_meta.get("date"))
            awarded_date = metadata["award_year"]

            if _is_valid_quantity(item_quantity):
                item_awarded_value = _format_money(_safe_float(item_quantity) * _safe_float(row["unit_rate"]))
            else:
                item_awarded_value = ""

            final_row = {
                "source": "eprocure_india",
                "country": "India",
                "country_code": "IN",
                "publication_date": publication_date,
                "closing_date": _clean_text(notice_meta.get("closing_date")),
                "title": _notice_title(notice_meta, metadata),
                "description": _notice_description(notice_meta, row),
                "buyer": buyer,
                "classification": metadata["device_category"],
                "status": "awarded",
                "currency": "INR",
                "amount": _notice_amount(notice_meta, row),
                "awarding_agency_name": buyer,
                "supplier_name": metadata["manufacturer"],
                "awarded_date": awarded_date,
                "awarded_value_detail": _clean_text(notice_meta.get("awarded_value_detail")),
                "contract_period": metadata["contract_duration"],
                "item_no": row["sl_no"],
                "item_description": row["test_name"],
                "item_uom": item_uom,
                "item_quantity": item_quantity,
                "item_unit_price": row["unit_rate"],
                "item_awarded_value": item_awarded_value,
                "notice_id": notice_id,
                "notice_url": _clean_text(notice_meta.get("link")),
                "query_text": _clean_text(notice_meta.get("query_text")),
                "scraped_at_utc": _utc_now_iso(),
                "dedup_key": "",
            }

            final_row["dedup_key"] = _make_dedup_key(final_row)
            dedupe_key = final_row["dedup_key"]
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            records.append({col: _clean_text(final_row.get(col, "")) for col in COLUMNS})

    # Pass 3: bidder-summary fallback for technical observation pages
    if not records:
        bidder_rows = _extract_bidder_summary_rows(cleaned)
        for row in bidder_rows:
            notice_id = _clean_text(notice_meta.get("notice_id")) or _clean_text(notice_meta.get("refNo")) or _clean_text(notice_meta.get("title"))
            buyer = _clean_text(notice_meta.get("org")) or metadata["ou"]
            publication_date = _clean_text(notice_meta.get("date"))
            awarded_date = _clean_text(notice_meta.get("awarded_date")) or metadata["award_year"]

            final_row = {
                "source": "eprocure_india",
                "country": "India",
                "country_code": "IN",
                "publication_date": publication_date,
                "closing_date": _clean_text(notice_meta.get("closing_date")),
                "title": _notice_title(notice_meta, metadata),
                "description": _notice_description(notice_meta) or "Bidder summary extracted from technical evaluation/AOC summary PDF",
                "buyer": buyer,
                "classification": metadata["device_category"],
                "status": "awarded",
                "currency": "INR",
                "amount": _notice_amount(notice_meta),
                "awarding_agency_name": buyer,
                "supplier_name": _clean_text(row.get("supplier_name")),
                "awarded_date": awarded_date,
                "awarded_value_detail": _clean_text(notice_meta.get("awarded_value_detail")),
                "contract_period": _clean_text(notice_meta.get("contract_period")) or metadata["contract_duration"],
                "bid_number": _clean_text(notice_meta.get("bid_number")),
                "item_no": row["sl_no"],
                "item_description": row["test_name"],
                "item_uom": "",
                "item_quantity": "",
                "item_unit_price": "",
                "item_awarded_value": "",
                "notice_id": notice_id,
                "notice_url": _clean_text(notice_meta.get("link")),
                "query_text": _clean_text(notice_meta.get("query_text")),
                "scraped_at_utc": _utc_now_iso(),
                "dedup_key": "",
            }

            final_row["dedup_key"] = _make_dedup_key(final_row)
            dedupe_key = final_row["dedup_key"]
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            records.append({col: _clean_text(final_row.get(col, "")) for col in COLUMNS})

    records = _finalize_item_records(records)
    records = _postprocess_equipment_records(records, notice_meta)
    logging.info(f"    Page {page_num}: EasyOCR parser extracted {len(records)} item(s).")
    return records

# ── PDF → page images ─────────────────────────────────────────────────────────
def pdf_bytes_to_images(pdf_bytes: bytes, dpi: int = 350) -> list[bytes]:
    """
    Rasterise every page of a PDF (as raw bytes) to JPEG bytes.
    Uses pypdfium2 first because it works directly from in-memory bytes,
    then falls back to pdf2image if needed.
    """
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(pdf_bytes)
        scale = dpi / 72.0
        pages = []

        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="JPEG", quality=92)
            pages.append(buf.getvalue())
            page.close()

        pdf.close()
        logging.info(f"  Rasterised {len(pages)} page(s) via pypdfium2 at {dpi} DPI.")
        return pages

    except ImportError:
        pass
    except Exception as e:
        logging.warning(f"  pypdfium2 failed: {e}")

    try:
        from pdf2image import convert_from_bytes

        pages_pil = convert_from_bytes(pdf_bytes, dpi=dpi, fmt="jpeg")
        pages = []
        for p in pages_pil:
            buf = io.BytesIO()
            p.save(buf, format="JPEG", quality=92)
            pages.append(buf.getvalue())

        logging.info(f"  Rasterised {len(pages)} page(s) via pdf2image at {dpi} DPI.")
        return pages

    except ImportError:
        pass
    except Exception as e:
        logging.warning(f"  pdf2image failed: {e}")

    raise RuntimeError(
        "Cannot rasterise PDF bytes. Install one of these:\n"
        "  pip install pypdfium2\n"
        "Or pdf2image + poppler:\n"
        "  pip install pdf2image\n"
        "  brew install poppler  /  sudo apt install poppler-utils"
    )


def pdf_bytes_to_text_pages(pdf_bytes: bytes) -> list[str]:
    """
    Extract machine-readable text page-by-page when the PDF already contains text.
    Returns an empty string for pages with no useful embedded text.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(_clean_text(text))
        return pages
    except Exception:
        return []


def pdf_path_to_images(pdf_path: str, dpi: int = 350) -> list[bytes]:
    with open(pdf_path, "rb") as f:
        return pdf_bytes_to_images(f.read(), dpi=dpi)
