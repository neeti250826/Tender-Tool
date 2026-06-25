from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin

import fitz  # PyMuPDF
import pandas as pd
import pytesseract
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from PIL import Image
from playwright.async_api import Browser, Page, async_playwright
from pytesseract import Output

logging.getLogger("pdfminer").setLevel(logging.ERROR)

# Windows only. Comment out on Linux/macOS if not needed.
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _tess_lang() -> str:
    try:
        langs = pytesseract.get_languages()
        return "por" if "por" in langs else "eng"
    except Exception:
        return "eng"


TESS_LANG: str = _tess_lang()

BASE_URL = (
    "https://www.gov.br/saude/pt-br/acesso-a-informacao/"
    "licitacoes-e-contratos/dispensa-de-licitacao"
)
DEFAULT_YEARS = [2024, 2025, 2026]
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
OUTPUT_COLUMNS = [
    "process_number",
    "buying_entity",
    "buying_entity_en",
    "state_uf",
    "city",
    "city_en",
    "product_description",
    "product_description_en",
    "quantity",
    "unit",
    "unit_en",
    "unit_price_brl",
    "total_value_brl",
    "total_amount",
    "winning_supplier_cnpj",
    "publication_date",
    "status",
    "status_en",
    "tender_type",
    "tender_type_en",
    "entry_url",
]


def cw(v: str) -> str:
    return re.sub(r"\s+", " ", v or "").strip()


def normalize_text(v: str) -> str:
    v = unicodedata.normalize("NFKD", v or "")
    v = "".join(c for c in v if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", v.lower())).strip()


def parse_brl(v: str) -> Decimal | None:
    v = cw(v).replace("R$", "").replace("RS", "").replace(" ", "")
    v = re.sub(r"[^\d,.\-]", "", v)

    if not v:
        return None

    if v.count(".") > 1 and "," not in v:
        parts = v.split(".")
        v = "".join(parts[:-1]) + "." + parts[-1]
    elif "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".")
    elif "," in v:
        v = v.replace(".", "").replace(",", ".")

    try:
        return Decimal(v)
    except InvalidOperation:
        return None


def fmt(v: Decimal | None, dec: int | None = None) -> str:
    if v is None:
        return ""
    if dec is not None:
        q = Decimal("1") if dec == 0 else Decimal("1." + "0" * dec)
        v = v.quantize(q)
    return format(v, "f")


def norm_qty(v: str) -> str:
    n = parse_brl(v)
    if n is None:
        return cw(v)
    return fmt(n, 0) if n == n.to_integral_value() else fmt(n)


def norm_money(v: str) -> str:
    n = parse_brl(v)
    return fmt(n, 2) if n is not None else cw(v)


def norm_date(v: str) -> str:
    v = cw(v)
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", v)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else v


def compute_total(qty: str, up: str) -> str:
    q, p = parse_brl(qty), parse_brl(up)
    return fmt(q * p, 2) if (q is not None and p is not None) else ""


def merge_supplier(name: str, cnpj: str) -> str:
    name, cnpj = cw(name), cw(cnpj)
    if name and cnpj:
        return f"{name} | CNPJ: {cnpj}"
    return name or cnpj


_translator: GoogleTranslator | None = None
_translation_cache: dict[tuple[str, str], str] = {}

UNIT_FALLBACK_TRANSLATIONS = {
    "cápsula": "capsule",
    "capsula": "capsule",
    "comprimido": "tablet",
    "frasco": "vial",
    "frasco 4 ml": "4 ml vial",
    "frasco-ampola": "vial ampoule",
    "frasco ampola": "vial ampoule",
    "seringa": "syringe",
    "seringa preenchida": "prefilled syringe",
    "seringa 2 ml": "2 ml syringe",
    "seringa 3 ml": "3 ml syringe",
    "seringa 5 ml": "5 ml syringe",
}

STATUS_FALLBACK_TRANSLATIONS = {
    "homologado": "awarded",
    "informado": "reported",
    "concluída": "completed",
    "concluida": "completed",
    "cancelada": "cancelled",
    "fracassada": "failed",
    "deserta": "no bids received",
    "revogada": "revoked",
    "anulada": "voided",
}

TENDER_TYPE_FALLBACK_TRANSLATIONS = {
    "dispensa": "direct award",
    "dispensa de licitação": "procurement waiver",
    "dispensa de licitacao": "procurement waiver",
    "inexigibilidade": "single-source procurement",
    "pregão": "auction",
    "pregao": "auction",
}


def get_translator() -> GoogleTranslator:
    global _translator
    if _translator is None:
        _translator = GoogleTranslator(source="pt", target="en")
    return _translator


def translate_text(v: str, fallback: str = "") -> str:
    raw = cw(v)
    if not raw:
        return ""

    cache_key = ("pt-en", raw)
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    try:
        translated = cw(get_translator().translate(raw))
        if translated:
            _translation_cache[cache_key] = translated
            return translated
    except Exception:
        pass

    result = fallback or raw
    _translation_cache[cache_key] = result
    return result


def translate_unit(v: str) -> str:
    raw = cw(v)
    if not raw:
        return ""
    key = normalize_text(raw)
    fallback = UNIT_FALLBACK_TRANSLATIONS.get(key, raw)
    return translate_text(raw, fallback=fallback)


def translate_status(v: str) -> str:
    raw = cw(v)
    if not raw:
        return ""
    key = normalize_text(raw)
    fallback = STATUS_FALLBACK_TRANSLATIONS.get(key, raw)
    return translate_text(raw, fallback=fallback)


def translate_tender_type(v: str) -> str:
    raw = cw(v)
    if not raw:
        return ""
    key = normalize_text(raw)
    fallback = TENDER_TYPE_FALLBACK_TRANSLATIONS.get(key, raw)
    return translate_text(raw, fallback=fallback)


def translate_buying_entity(v: str) -> str:
    raw = cw(v)
    if not raw:
        return ""
    return translate_text(raw, fallback=raw)


def translate_product_description(v: str) -> str:
    raw = cw(v)
    if not raw:
        return ""
    return translate_text(raw, fallback=raw)


def translate_city(v: str) -> str:
    raw = cw(v)
    if not raw:
        return ""
    return translate_text(raw, fallback=raw)


def looks_like_good_text(text: str) -> bool:
    text = text or ""
    cleaned = cw(text)
    if len(cleaned) < 40:
        return False

    good_markers = [
        "descrição",
        "descricao",
        "quantidade",
        "unidade de medida",
        "valor unitário homologado",
        "valor unitario homologado",
        "valor total homologado",
        "cnpj/cpf",
        "nome ou razão social do fornecedor",
        "resultado",
        "situação",
        "situacao",
        "número",
        "numero",
    ]
    lowered = cleaned.lower()
    hits = sum(1 for m in good_markers if m in lowered)
    weird_ratio = sum(
        1 for c in cleaned if ord(c) < 32 and c not in "\n\t\r"
    ) / max(len(cleaned), 1)
    return hits >= 2 and weird_ratio < 0.02


def render_page_with_pymupdf(page: fitz.Page, dpi: int = 300) -> Image.Image:
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    mode = "RGB" if pix.n < 4 else "RGBA"
    return Image.frombytes(mode, [pix.width, pix.height], pix.samples).convert("RGB")


def ocr_image(img: Image.Image, psm: int = 6) -> str:
    gray = img.convert("L")

    try:
        osd = pytesseract.image_to_osd(gray)
        angle = int(re.search(r"Rotate: (\d+)", osd).group(1))

        if angle != 0:
            gray = gray.rotate(-angle, expand=True)

    except Exception:
        pass  # if detection fails, continue

    return pytesseract.image_to_string(
        gray,
        lang=TESS_LANG,
        config=f"--psm {psm}"
    ) or ""


def ocr_image_data(img: Image.Image, psm: int = 6) -> list[dict]:
    gray = img.convert("L")

    try:
        osd = pytesseract.image_to_osd(gray)
        angle = int(re.search(r"Rotate: (\d+)", osd).group(1))

        if angle != 0:
            gray = gray.rotate(-angle, expand=True)

    except Exception:
        pass

    data = pytesseract.image_to_data(
        gray,
        lang=TESS_LANG,
        config=f"--psm {psm}",
        output_type=Output.DICT,
    )

    rows = []
    for i in range(len(data["text"])):
        txt = cw(str(data["text"][i]))
        if not txt:
            continue

        rows.append({
            "text": txt,
            "left": int(data["left"][i]),
            "top": int(data["top"][i]),
            "width": int(data["width"][i]),
            "height": int(data["height"][i]),
        })

    return rows


def pdf_to_page_texts_with_pymupdf_first(raw: bytes, dpi: int = 300) -> list[str]:
    page_texts: list[str] = []
    doc = fitz.open(stream=raw, filetype="pdf")
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]

            native_text = page.get_text("text") or ""
            native_text = native_text.replace("\x00", " ")
            native_text = re.sub(r"[ \t]+", " ", native_text)
            native_text = re.sub(r"\n{2,}", "\n", native_text).strip()

            if looks_like_good_text(native_text):
                page_texts.append(native_text)
                continue

            img = render_page_with_pymupdf(page, dpi=dpi)
            ocr_text = ocr_image(img, psm=6)
            ocr_text = re.sub(r"[ \t]+", " ", ocr_text)
            ocr_text = re.sub(r"\n{2,}", "\n", ocr_text).strip()

            if len(ocr_text) > len(native_text):
                page_texts.append(ocr_text)
            else:
                page_texts.append(native_text or ocr_text)
    finally:
        doc.close()

    return page_texts


def extract_total_amount_from_text(text: str) -> str:
    patterns = [
        r"VALOR\s+TOTAL\s+HOMOLOGADO\s+DA\s+COMPRA\s*[:\-]?\s*R\$?\s*([\d.,]+)",
        r"VALOR\s+TOTAL\s+HOMOLOGAD[OA]\s+DA\s+COMPRA\s*[:\-]?\s*R\$?\s*([\d.,]+)",
        r"TOTAL\s+HOMOLOGAD[OA]\s+DA\s+COMPRA\s*[:\-]?\s*R\$?\s*([\d.,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return norm_money(m.group(1))
    return ""


def extract_item_number_from_text(text: str) -> str:
    text = cw(text)
    patterns = [
        r"Item\s*n\s*[°ºo]?\s*(\d+)",
        r"Item\s*n[°ºo]\s*(\d+)",
        r"Item\s*[°ºo]?\s*(\d+)",
        r"\bItem\s*[:\-]?\s*(\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def extract_detail_metadata(
    html: str,
    entry_url: str,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    soup = BeautifulSoup(html, "lxml")
    title = cw(
        (soup.select_one("h1.documentFirstHeading") or soup.new_tag("x")).get_text(
            " ", strip=True
        )
    )
    description = cw(
        (soup.select_one("div.documentDescription") or soup.new_tag("x")).get_text(
            " ", strip=True
        )
    )
    body_text = cw(
        (soup.select_one("#parent-fieldname-text") or soup.new_tag("x")).get_text(
            " ", strip=True
        )
    )
    pub_date = cw(
        (soup.select_one(".documentPublished .value") or soup.new_tag("x")).get_text(
            " ", strip=True
        )
    )

    proc_m = re.search(
        r"Processo\s*n[ºo°]?\s*([\d./-]+)",
        f"{title} {description} {body_text}",
        re.IGNORECASE,
    )

    buying_entity = ""
    winning_supplier = ""
    sup_m = re.search(
        r"por interm[eé]dio do\s+(.*?)\s+e\s+"
        r"(?:a\(s\)\s+empresa\(s\)|as\s+empresas?|a\s+empresa)\s+(.*)",
        description,
        re.IGNORECASE,
    )
    if sup_m:
        buying_entity = cw(sup_m.group(1))
        winning_supplier = cw(sup_m.group(2).rstrip("."))

    attachments: list[dict[str, str]] = []
    for a in soup.select("#parent-fieldname-text a[href]"):
        href = a.get("href", "").strip()
        name = cw(a.get_text(" ", strip=True))
        if not href:
            continue
        is_ato = bool(
            re.search(r"ato\s+de\s+contrata[cç][aã]o\s+direta", name, re.IGNORECASE)
        )
        attachments.append(
            {"url": urljoin(entry_url, href), "name": name, "is_ato": is_ato}
        )

    return (
        {
            "entry_url": entry_url,
            "title": title,
            "process_number": proc_m.group(1) if proc_m else "",
            "buying_entity": buying_entity or "Ministério da Saúde",
            "winning_supplier": winning_supplier,
            "publication_date": pub_date,
        },
        attachments,
    )


def extract_header_from_page1(text: str, meta: dict[str, str]) -> dict[str, str]:
    clean_text = cw(text)

    loc = re.search(
        r"Local:\s*([^/\n,]+?)\s*/\s*([A-Z]{2})\b",
        clean_text,
        re.IGNORECASE,
    )

    proc = re.search(
        r"Id\s+contrata[cç][aã]o\s+PNCP:\s*([\w\-./]+)",
        clean_text,
        re.IGNORECASE,
    )

    pub = re.search(
        r"Data\s+de\s+divulga[cç][aã]o\s+no\s+PNCP:\s*(\d{2}/\d{2}/\d{4})",
        clean_text,
        re.IGNORECASE,
    )

    sit = re.search(
        r"Situa[cç][aã]o:\s*(.*?)(?:\s+Modalidade da contrata[cç][aã]o:|\s+Tipo:|\s+Crit[eé]rio:|\s+Fonte:|\s+Id\s+contrata[cç][aã]o|\Z)",
        clean_text,
        re.IGNORECASE | re.DOTALL,
    )

    mod = re.search(
        r"Modalidade da contrata[cç][aã]o:\s*(.*?)(?:\s+Amparo legal:|\s+Modo de disputa:|\s+Situa[cç][aã]o:|\Z)",
        clean_text,
        re.IGNORECASE | re.DOTALL,
    )

    buying_entity = ""
    for pat in [
        r"Unidade compradora:\s*(.*?)(?:Modalidade da contrata[cç][aã]o:|\n|$)",
        r"Unidade compradora:\s*(.*?)$",
    ]:
        m = re.search(pat, clean_text, re.IGNORECASE | re.DOTALL)
        if m:
            buying_entity = cw(m.group(1))
            break

    total_amount = extract_total_amount_from_text(clean_text)

    return {
        "city": cw(loc.group(1)) if loc else "",
        "state_uf": loc.group(2) if loc else "",
        "process_number": cw(proc.group(1)) if proc else meta.get("process_number", ""),
        "publication_date": pub.group(1) if pub else meta.get("publication_date", ""),
        "status": cw(sit.group(1)) if sit else "",
        "tender_type": cw(mod.group(1)) if mod else "Dispensa",
        "buying_entity": buying_entity or meta.get("buying_entity", ""),
        "total_amount": total_amount,
    }


def parse_item_detail_page(text: str) -> dict[str, str] | None:
    if not text:
        return None

    clean_text = re.sub(r"\s+", " ", text or "").strip()

    if not re.search(
        r"(Item\s*n|Descri[cç][aã]o|Descricao|Quantidade|Unidade de medida|Valor unit|Valor total|RESULTADO)",
        clean_text,
        re.IGNORECASE,
    ):
        return None

    item_number = extract_item_number_from_text(clean_text)

    desc = ""
    desc_patterns = [
        r"Descri[cç][aã]o\s*:\s*(.+?)(?=\s+Crit[eé]rio de julgamento\s*:)",
        r"Descri[cç][aã]o\s*:\s*(.+?)(?=\s+Situa[cç][aã]o\s*:)",
        r"Descri[cç][aã]o\s*:\s*(.+?)(?=\s+Tipo\s*:)",
        r"Descri[cç][aã]o\s*:\s*(.+?)(?=\s+Categoria do item)",
        r"Descri[cç][aã]o\s*:\s*(.+?)(?=\s+Quantidade\s*:)",
    ]
    for pat in desc_patterns:
        m = re.search(pat, clean_text, re.IGNORECASE | re.DOTALL)
        if m:
            desc = cw(m.group(1))
            break

    quantity = ""
    m = re.search(r"Quantidade\s*:\s*([\d.,]+)", clean_text, re.IGNORECASE)
    if m:
        quantity = cw(m.group(1))

    unit = ""
    m = re.search(
        r"Unidade de medida\s*:\s*(.+?)(?=\s+Valor unit[áa]rio estimado\s*:|\s+Valor unit[áa]rio homologado\s*:|\s+RESULTADO|\s+Valor total)",
        clean_text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        unit = cw(m.group(1))

    up_hom_m = re.search(
        r"Valor unit[áa]rio homologado\s*:\s*R?\$?\s*([\d.,]+)",
        clean_text,
        re.IGNORECASE,
    )
    tv_hom_m = re.search(
        r"Valor total homologado\s*:\s*R?\$?\s*([\d.,]+)",
        clean_text,
        re.IGNORECASE,
    )
    up_est_m = re.search(
        r"Valor unit[áa]rio estimado\s*:\s*R?\$?\s*([\d.,]+)",
        clean_text,
        re.IGNORECASE,
    )
    tv_est_m = re.search(
        r"Valor total estimado\s*:\s*R?\$?\s*([\d.,]+)",
        clean_text,
        re.IGNORECASE,
    )

    cnpj_m = re.search(
        r"CNPJ/CPF.*?:\s*([\d./-]+)",
        clean_text,
        re.IGNORECASE,
    )
    supplier_cnpj = cw(cnpj_m.group(1)) if cnpj_m else ""

    supplier_name = ""
    m = re.search(
        r"Nome ou raz[aã]o social do fornecedor\s*:\s*(.+?)(?=\s+Indicador de subcontrata[cç][aã]o\s*:|\s+Porte da empresa\s*:|\s+C[oó]digo do pa[ií]s\s*:|\s+Uso da margem)",
        clean_text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        supplier_name = cw(m.group(1))

    unit_price_homologado = cw(up_hom_m.group(1)) if up_hom_m else ""
    total_value_homologado = cw(tv_hom_m.group(1)) if tv_hom_m else ""
    unit_price_estimado = cw(up_est_m.group(1)) if up_est_m else ""
    total_value_estimado = cw(tv_est_m.group(1)) if tv_est_m else ""

    if not any([
        item_number,
        desc,
        quantity,
        unit,
        unit_price_homologado,
        total_value_homologado,
        unit_price_estimado,
        total_value_estimado,
        supplier_name,
        supplier_cnpj,
    ]):
        return None

    return {
        "item_number": item_number,
        "product_description": desc,
        "quantity": quantity,
        "unit": unit,
        "unit_price_homologado": unit_price_homologado,
        "total_value_homologado": total_value_homologado,
        "unit_price_estimado": unit_price_estimado,
        "total_value_estimado": total_value_estimado,
        "supplier_name": supplier_name,
        "supplier_cnpj": supplier_cnpj,
    }


def parse_items_table_from_first_page_ocr(raw_pdf: bytes, dpi: int = 300) -> list[dict[str, str]]:
    doc = fitz.open(stream=raw_pdf, filetype="pdf")
    try:
        if len(doc) == 0:
            return []

        page = doc[0]
        img = render_page_with_pymupdf(page, dpi=dpi)
        words = ocr_image_data(img, psm=6)
        if not words:
            return []

        words = sorted(words, key=lambda w: (w["top"], w["left"]))

        row_bands: list[list[dict]] = []
        tol = 18
        for w in words:
            placed = False
            for band in row_bands:
                avg_top = sum(x["top"] for x in band) / len(band)
                if abs(w["top"] - avg_top) <= tol:
                    band.append(w)
                    placed = True
                    break
            if not placed:
                row_bands.append([w])

        rows = [sorted(band, key=lambda x: x["left"]) for band in row_bands]

        header_idx = -1
        for i, row in enumerate(rows):
            line = cw(" ".join(w["text"] for w in row)).lower()
            if (
                ("número" in line or "numero" in line)
                and ("descrição" in line or "descricao" in line)
                and "quantidade" in line
            ):
                header_idx = i
                break

        if header_idx == -1:
            return []

        header_row = rows[header_idx]

        def find_col_center(keywords: list[str]) -> int | None:
            for w in header_row:
                t = normalize_text(w["text"])
                if any(k in t for k in keywords):
                    return w["left"] + w["width"] // 2
            return None

        num_x = find_col_center(["numero"])
        desc_x = find_col_center(["descricao"])
        qty_x = find_col_center(["quantidade"])
        price_x = find_col_center(["valor", "unitario"])

        if desc_x is None:
            return []

        extracted = []
        for row in rows[header_idx + 1:]:
            line = cw(" ".join(w["text"] for w in row))
            if not line:
                continue

            norm_line = normalize_text(line)
            if any(stop in norm_line for stop in ["arquivos", "historico", "resultado", "valor total"]):
                break

            item_number = ""
            for w in row:
                if re.fullmatch(r"\d+", w["text"]):
                    cx = w["left"] + w["width"] // 2
                    if num_x is None or abs(cx - num_x) < 100:
                        item_number = w["text"]
                        break

            if not item_number:
                continue

            desc_parts = []
            qty_val = ""
            price_parts = []

            for w in row:
                cx = w["left"] + w["width"] // 2
                txt = w["text"]

                if qty_x is not None and abs(cx - qty_x) < 110 and re.fullmatch(r"[\d.,]+", txt):
                    qty_val = txt
                    continue

                if price_x is not None and abs(cx - price_x) < 220 and re.search(r"[\d.,]+", txt):
                    price_parts.append(txt.replace("R$", "").strip())
                    continue

                if desc_x is not None and cx > (num_x or 0) + 40 and (qty_x is None or cx < qty_x - 40):
                    if not re.fullmatch(r"\d+", txt):
                        desc_parts.append(txt)

            product_description = cw(" ".join(desc_parts))
            unit_price_estimado = cw(" ".join(price_parts))

            if product_description or qty_val or unit_price_estimado:
                extracted.append(
                    {
                        "item_number": item_number,
                        "product_description": product_description,
                        "quantity": qty_val,
                        "unit_price_estimado": unit_price_estimado,
                    }
                )

        return extracted
    finally:
        doc.close()


@dataclass
class DetailData:
    entry_url: str
    process_number: str = ""
    buying_entity: str = ""
    buying_entity_en: str = ""
    state_uf: str = ""
    city: str = ""
    city_en: str = ""
    product_description: str = ""
    product_description_en: str = ""
    quantity: str = ""
    unit: str = ""
    unit_en: str = ""
    unit_price_brl: str = ""
    total_value_brl: str = ""
    total_amount: str = ""
    winning_supplier_cnpj: str = ""
    publication_date: str = ""
    status: str = ""
    status_en: str = ""
    tender_type: str = ""
    tender_type_en: str = ""


@dataclass
class AttachmentData:
    url: str
    name: str = ""
    pdf_bytes: bytes = field(default_factory=bytes)
    is_pdf: bool = False
    is_ato: bool = False


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def fetch_attachment(session: requests.Session, att: dict, timeout: int) -> AttachmentData:
    resp = session.get(att["url"], timeout=timeout)
    resp.raise_for_status()
    ct = resp.headers.get("Content-Type", "").lower()

    def _as_pdf(raw: bytes, url: str) -> AttachmentData:
        return AttachmentData(
            url=url,
            name=att.get("name", ""),
            pdf_bytes=raw,
            is_pdf=True,
            is_ato=att.get("is_ato", False),
        )

    if "pdf" in ct or resp.content[:4] == b"%PDF":
        return _as_pdf(resp.content, resp.url)

    soup = BeautifulSoup(resp.text, "lxml")
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if ".pdf" in href.lower() or "@@download" in href.lower():
            pr = session.get(urljoin(att["url"], href), timeout=timeout)
            pr.raise_for_status()
            return _as_pdf(pr.content, pr.url)

    return AttachmentData(
        url=att["url"],
        name=att.get("name", ""),
        is_ato=att.get("is_ato", False),
    )


def build_rows_from_pdf(
    meta: dict[str, str],
    attachments: list[AttachmentData],
    ocr_dpi: int = 300,
) -> list[DetailData]:
    ato = [a for a in attachments if a.is_ato and a.is_pdf]
    all_ = [a for a in attachments if a.is_pdf]
    targets = ato if ato else all_

    for att in targets:
        print(f"[info]   processing PDF: {att.name}")
        try:
            page_texts = pdf_to_page_texts_with_pymupdf_first(att.pdf_bytes, dpi=ocr_dpi)
        except Exception as exc:
            print(f"[warn]   PDF extraction failed: {exc}")
            continue

        print(f"[info]   extracted pages: {len(page_texts)}")

        hdr = extract_header_from_page1(page_texts[0] if page_texts else "", meta)
        process_number = hdr["process_number"] or meta.get("process_number", "")
        buying_entity = hdr["buying_entity"] or meta.get("buying_entity", "")
        city = hdr["city"]
        state_uf = hdr["state_uf"]
        publication_date = norm_date(hdr["publication_date"] or meta.get("publication_date", ""))
        status = hdr["status"]
        tender_type = hdr["tender_type"]
        total_amount = hdr["total_amount"]

        if not total_amount:
            for page_text in page_texts[1:]:
                total_amount = extract_total_amount_from_text(page_text)
                if total_amount:
                    break

        first_page_items = parse_items_table_from_first_page_ocr(att.pdf_bytes, dpi=ocr_dpi)
        print("[debug] first_page_items:", first_page_items[:3])

        detail_by_item: dict[str, dict[str, str]] = {}
        detail_no_num: list[dict[str, str]] = []

        for page_text in page_texts[1:]:
            detail = parse_item_detail_page(page_text)
            if not detail:
                continue
            item_no = detail.get("item_number", "")
            if item_no and item_no not in detail_by_item:
                detail_by_item[item_no] = detail
            else:
                detail_no_num.append(detail)

        rows: list[DetailData] = []

        if first_page_items:
            for idx, item in enumerate(first_page_items, start=1):
                item_no = item.get("item_number", "") or str(idx)
                detail = detail_by_item.get(item_no, {})

                if not detail and idx - 1 < len(detail_no_num):
                    detail = detail_no_num[idx - 1]

                desc = cw(item.get("product_description", "")) or cw(detail.get("product_description", ""))
                qty = norm_qty(item.get("quantity", "") or detail.get("quantity", ""))
                unit = cw(detail.get("unit", ""))

                up = norm_money(detail.get("unit_price_homologado", ""))
                if not up:
                    up = norm_money(detail.get("unit_price_estimado", ""))
                if not up:
                    up = norm_money(item.get("unit_price_estimado", ""))

                tv = norm_money(detail.get("total_value_homologado", ""))
                if not tv:
                    tv = norm_money(detail.get("total_value_estimado", ""))
                if not tv and qty and up:
                    tv = compute_total(qty, up)

                supplier = merge_supplier(
                    detail.get("supplier_name", "") or meta.get("winning_supplier", ""),
                    detail.get("supplier_cnpj", ""),
                )

                rows.append(
                    DetailData(
                        entry_url=meta["entry_url"],
                        process_number=process_number,
                        buying_entity=buying_entity,
                        buying_entity_en=translate_buying_entity(buying_entity),
                        state_uf=state_uf,
                        city=city,
                        city_en=translate_city(city),
                        product_description=desc,
                        product_description_en=translate_product_description(desc),
                        quantity=qty,
                        unit=unit,
                        unit_en=translate_unit(unit),
                        unit_price_brl=up,
                        total_value_brl=tv,
                        total_amount=total_amount,
                        winning_supplier_cnpj=supplier,
                        publication_date=publication_date,
                        status=status,
                        status_en=translate_status(status),
                        tender_type=tender_type,
                        tender_type_en=translate_tender_type(tender_type),
                    )
                )

            if rows:
                return rows

        # fallback: build directly from detail pages if first-page OCR table failed
        for detail in list(detail_by_item.values()) + detail_no_num:
            desc = cw(detail.get("product_description", ""))
            qty = norm_qty(detail.get("quantity", ""))
            unit = cw(detail.get("unit", ""))

            up = norm_money(detail.get("unit_price_homologado", ""))
            if not up:
                up = norm_money(detail.get("unit_price_estimado", ""))

            tv = norm_money(detail.get("total_value_homologado", ""))
            if not tv:
                tv = norm_money(detail.get("total_value_estimado", ""))

            if not tv and qty and up:
                tv = compute_total(qty, up)

            supplier = merge_supplier(
                detail.get("supplier_name", "") or meta.get("winning_supplier", ""),
                detail.get("supplier_cnpj", ""),
            )

            rows.append(
                DetailData(
                    entry_url=meta["entry_url"],
                    process_number=process_number,
                    buying_entity=buying_entity,
                    buying_entity_en=translate_buying_entity(buying_entity),
                    state_uf=state_uf,
                    city=city,
                    city_en=translate_city(city),
                    product_description=desc,
                    product_description_en=translate_product_description(desc),
                    quantity=qty,
                    unit=unit,
                    unit_en=translate_unit(unit),
                    unit_price_brl=up,
                    total_value_brl=tv,
                    total_amount=total_amount,
                    winning_supplier_cnpj=supplier,
                    publication_date=publication_date,
                    status=status,
                    status_en=translate_status(status),
                    tender_type=tender_type,
                    tender_type_en=translate_tender_type(tender_type),
                )
            )

        if rows:
            return rows

    return []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape gov.br dispensa de licitação (2024-2026).")
    p.add_argument("--years", nargs="+", type=int, default=DEFAULT_YEARS)
    p.add_argument("--output-dir", default="output")
    p.add_argument("--timeout-ms", type=int, default=90_000)
    p.add_argument("--headful", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="Stop after N entries (0=unlimited)")
    p.add_argument("--entry-url", action="append", default=[], help="Scrape specific URL(s)")
    p.add_argument("--ocr-dpi", type=int, default=300, help="DPI for PDF rasterisation")
    return p.parse_args()


def ensure_playwright_env() -> None:
    import os

    bp = Path(".playwright-browsers").resolve()
    if bp.exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bp))


async def fetch_page_html(page: Page, url: str, timeout_ms: int) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    return await page.content()


def extract_year_links(html: str, year: int) -> tuple[list[str], str | None]:
    soup = BeautifulSoup(html, "lxml")
    links, seen = [], set()
    frag = f"dispensa-de-licitacao/{year}"

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if frag in href:
            if href.startswith("/"):
                href = "https://www.gov.br" + href
            if href not in seen:
                seen.add(href)
                links.append(href)

    next_link = None
    for sel in (
        "a[title='Próxima página']",
        "a[title='Proxima pagina']",
        "a[rel='next']",
        "a.next",
        "li.next > a",
    ):
        el = soup.select_one(sel)
        if el and el.get("href"):
            raw = el["href"].strip()
            next_link = ("https://www.gov.br" + raw) if raw.startswith("/") else raw
            break

    return links, next_link


async def collect_year_entry_urls(page: Page, year: int, timeout_ms: int) -> list[str]:
    urls, seen_e, seen_p = [], set(), set()
    nxt: str | None = f"{BASE_URL}/{year}"

    while nxt and nxt not in seen_p:
        seen_p.add(nxt)
        html = await fetch_page_html(page, nxt, timeout_ms)
        page_urls, nxt = extract_year_links(html, year)
        for u in page_urls:
            if u not in seen_e:
                seen_e.add(u)
                urls.append(u)

    return urls


async def scrape(args: argparse.Namespace) -> list[DetailData]:
    ensure_playwright_env()
    session = build_session()
    rows: list[DetailData] = []
    processed = 0

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(headless=not args.headful)
        page = await browser.new_page()
        try:
            explicit = [u.strip() for u in args.entry_url if u.strip()]
            buckets: list[tuple[str, list[str]]] = []

            if explicit:
                buckets.append(("explicit", explicit))
            else:
                for year in args.years:
                    print(f"[info] collecting URLs for {year} …")
                    urls = await collect_year_entry_urls(page, year, args.timeout_ms)
                    print(f"[info] {len(urls)} entries found for {year}")
                    buckets.append((str(year), urls))

            for bucket, urls in buckets:
                if bucket == "explicit":
                    print(f"[info] scraping {len(urls)} explicit URL(s)")
                for entry_url in urls:
                    if args.limit and processed >= args.limit:
                        return rows

                    processed += 1
                    print(f"[info] [{processed}] {entry_url}")
                    try:
                        html = await fetch_page_html(page, entry_url, args.timeout_ms)
                        meta, att_defs = extract_detail_metadata(html, entry_url)

                        ato_defs = [a for a in att_defs if a["is_ato"]]
                        target_defs = ato_defs if ato_defs else att_defs

                        downloaded: list[AttachmentData] = []
                        for adef in target_defs:
                            try:
                                downloaded.append(
                                    fetch_attachment(
                                        session,
                                        adef,
                                        timeout=max(30, args.timeout_ms // 1000),
                                    )
                                )
                            except Exception as exc:
                                print(f"[warn]   attachment failed: {exc}")

                        entry_rows = build_rows_from_pdf(meta, downloaded, ocr_dpi=args.ocr_dpi)

                        if entry_rows:
                            print(f"[info]   → {len(entry_rows)} row(s)")
                            rows.extend(entry_rows)
                        else:
                            print("[warn]   → no rows extracted")

                    except Exception as exc:
                        print(f"[warn] entry failed: {exc}")
        finally:
            await page.close()
            await browser.close()

    return rows


def save_outputs(rows: list[DetailData], output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [{col: getattr(r, col) for col in OUTPUT_COLUMNS} for r in rows]
    df = pd.DataFrame(records, columns=OUTPUT_COLUMNS)

    csv_path = output_dir / "procurement_items_test(2025).csv"
    xlsx_path = output_dir / "procurement_items_test(2025).xlsx"
    json_path = output_dir / "procurement_items_test(2025).json"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(xlsx_path, index=False)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, xlsx_path, json_path


def main() -> None:
    args = parse_args()
    rows = asyncio.run(scrape(args))
    csv_path, xlsx_path, json_path = save_outputs(rows, Path(args.output_dir))
    print(f"\n[done] rows written : {len(rows)}")
    print(f"[done] csv          : {csv_path.resolve()}")
    print(f"[done] xlsx         : {xlsx_path.resolve()}")
    print(f"[done] json         : {json_path.resolve()}")


if __name__ == "__main__":
    main()