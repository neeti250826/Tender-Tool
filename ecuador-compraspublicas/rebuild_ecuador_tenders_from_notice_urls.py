from __future__ import annotations

import argparse
import csv
from datetime import datetime
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import easyocr
import numpy as np
import pypdfium2 as pdfium
from deep_translator import GoogleTranslator
from playwright.sync_api import Page, sync_playwright


DEFAULT_INPUT = r"C:\Users\Neeti\PycharmProjects\Clearstate\Spain_Tender\output\ecuador_tenders.csv"
DEFAULT_OUTPUT = r"C:\Users\Neeti\PycharmProjects\Clearstate\Spain_Tender\output\ecuador_tenders_rebuilt.csv"
CSV_COLUMNS = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "closing_date",
    "title",
    "title_en",
    "description",
    "description_en",
    "buyer",
    "buyer_en",
    "classification",
    "classification_en",
    "status",
    "status_en",
    "currency",
    "amount",
    "awarding_supplier_name",
    "awarding_supplier_name_en",
    "awarded_date",
    "contract_period",
    "item_no",
    "item_desc",
    "item_desc_en",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_award_amount",
    "notice_id",
    "notice_link",
    "notice_url",
    "query_text",
    "scraped_at",
    "dedup_key",
]

PRINT_FIELD_ALIASES = {
    "entidad": "buyer",
    "objeto de proceso": "title",
    "descripcion": "description",
    "codigo": "notice_id",
    "tipo de contratacion": "classification",
    "presupuesto referencial total sin iva": "amount",
    "fecha de publicacion": "publication_date",
    "fecha limite de propuestas": "closing_date",
    "estado del proceso": "status",
    "vigencia de oferta": "contract_period",
}

UOM_PATTERN = (
    r"unidad(?:es)?|unid(?:ad)?|u|kg|gr|g|l|lt|ml|m|m2|m3|cm|mm|"
    r"hora(?:s)?|dia(?:s)?|mes(?:es)?|ano(?:s)?|anio(?:s)?|lote|global|servicio"
)


@dataclass
class ScrapedTender:
    publication_date: str
    closing_date: str
    title: str
    description: str
    buyer: str
    classification: str
    status: str
    currency: str
    amount: str
    awarding_supplier_name: str
    awarded_date: str
    contract_period: str
    notice_id: str
    notice_url: str
    items: list[dict[str, str]]
    suppliers: list[dict[str, str]]


TRANSLATOR = GoogleTranslator(source="auto", target="en")
TRANSLATION_CACHE: dict[str, str] = {}
OCR_READER: easyocr.Reader | None = None
PDF_DPI = 450


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def normalize_notice_url(value: str | None) -> str:
    url = normalize_text(value)
    if not url:
        return ""
    if "idSoliCompra=" in url and not url.endswith(","):
        return f"{url},"
    return url


def log_info(message: str) -> None:
    print(f"{datetime.now().strftime('%H:%M:%S')} [INFO] {message}")


def ascii_label(value: str | None) -> str:
    text = normalize_text(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def slugify(value: str) -> str:
    cleaned = ascii_label(value)
    return re.sub(r"(^_+|_+$)", "", re.sub(r"[^a-z0-9]+", "_", cleaned))


def parse_money(value: str | None) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned:
        return ""
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            return cleaned.replace(".", "").replace(",", ".")
        return cleaned.replace(",", "")
    if "," in cleaned:
        return cleaned.replace(".", "").replace(",", ".")
    return cleaned


def format_datetime(value: str | None) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    match = re.search(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2})(?::\d{2})?)?", text)
    if match:
        if match.group(2):
            return f"{match.group(1)} {match.group(2)}"
        return match.group(1)
    return text


def normalize_status(value: str | None) -> str:
    text = normalize_text(value)
    lowered = ascii_label(text)
    if lowered in {"finalizada", "finalizado", "completed"}:
        return "Completed"
    return text


def translate_text(value: str) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if text in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[text]
    try:
        translated = normalize_text(TRANSLATOR.translate(text))
    except Exception:
        translated = ""
    TRANSLATION_CACHE[text] = translated
    return translated


def click_tab(page: Page, tab_id: str) -> None:
    page.evaluate(
        """targetId => {
            const el = document.getElementById(targetId);
            if (!el) throw new Error(`Missing tab ${targetId}`);
            el.click();
        }""",
        tab_id,
    )
    page.wait_for_function(
        """targetId => {
            const el = document.getElementById(targetId);
            return !!el && (el.className || "").includes("active");
        }""",
        arg=tab_id,
        timeout=15000,
    )
    page.wait_for_timeout(1200)


def has_tab(page: Page, tab_id: str) -> bool:
    return bool(
        page.evaluate(
            """targetId => !!document.getElementById(targetId)""",
            tab_id,
        )
    )


def get_print_page_url(page: Page) -> str:
    onclick = page.evaluate(
        """() => {
            const link = Array.from(document.querySelectorAll("a")).find(
              el => (el.innerText || "").includes("Imprimir")
            );
            return link ? (link.getAttribute("onclick") || "") : "";
        }"""
    )
    match = re.search(r"window\.open\('([^']+)'\s*\+\s*'([^']+)'\)", onclick or "")
    if not match:
        return ""
    relative = f"{match.group(1)}{match.group(2)}"
    if relative.startswith("../"):
        return "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/" + relative[3:]
    return relative


def get_contract_summary_url(page: Page) -> str:
    href = page.evaluate(
        """() => {
            const link = Array.from(document.querySelectorAll("a")).find(
              el => (el.innerText || "").includes("Resumen de Contrato")
            );
            return link ? link.href : "";
        }"""
    )
    return normalize_text(href)


def scrape_print_fields(print_page: Page) -> dict[str, str]:
    rows = print_page.evaluate(
        """
        () => Array.from(document.querySelectorAll("tr"))
          .map(tr => Array.from(tr.querySelectorAll("th,td"))
            .map(td => (td.innerText || "").replace(/\\s+/g, " ").trim())
            .filter(Boolean))
          .filter(cells => cells.length >= 2)
        """
    )
    fields: dict[str, str] = {}
    for cells in rows:
        key = ascii_label(cells[0].rstrip(":"))
        if not key:
            continue
        if key in PRINT_FIELD_ALIASES and PRINT_FIELD_ALIASES[key] not in fields:
            fields[PRINT_FIELD_ALIASES[key]] = normalize_text(cells[1])
    return fields


def scrape_award_info(contract_page: Page) -> dict[str, str]:
    rows = contract_page.evaluate(
        """
        () => Array.from(document.querySelectorAll("tr"))
          .map(tr => Array.from(tr.querySelectorAll("th,td"))
            .map(td => (td.innerText || "").replace(/\\s+/g, " ").trim())
            .filter(Boolean))
          .filter(cells => cells.length)
        """
    )
    for cells in rows:
        joined = " ".join(cells)
        if "Nombre del Adjudicatario" in joined and "Fecha de Adjudicación" in joined:
            continue
        if len(cells) >= 5 and re.fullmatch(r"\d+", cells[0]) and re.fullmatch(r"\d{10,13}", cells[1]):
            return {
                "awarding_supplier_name": normalize_text(cells[2]),
                "awarded_date": format_datetime(cells[3]),
            }
    return {"awarding_supplier_name": "", "awarded_date": ""}


def scrape_publication_results_summary(results_page: Page) -> list[dict[str, str]]:
    rows = results_page.evaluate(
        """
        () => Array.from(document.querySelectorAll("tr"))
          .map(tr => Array.from(tr.querySelectorAll("th,td"))
            .map(td => (td.innerText || "").replace(/\\s+/g, " ").trim())
            .filter(Boolean))
          .filter(cells => cells.length >= 2)
        """
    )
    supplier_name = ""
    for cells in rows:
        label = ascii_label(cells[0].rstrip(":"))
        if label == "razon social":
            supplier_name = normalize_text(cells[1])
            break
    if supplier_name:
        return [{"supplier_no": "1", "supplier_name": supplier_name, "supplier_amount": ""}]
    return []


def get_publication_results_url(page: Page) -> str:
    href = page.evaluate(
        """() => {
            const link = Array.from(document.querySelectorAll("a, input[type='button'], button"))
              .find(el => ((el.innerText || el.value || "").replace(/\\s+/g, " ").trim()).includes("Ver Resultados de Publicación"));
            if (!link) return "";
            if (link.tagName === "A") return link.href || link.getAttribute("href") || "";
            return "";
        }"""
    )
    return normalize_text(href)


def get_first_pdf_url(page: Page) -> str:
    href = page.evaluate(
        """() => {
            const text = value => (value || "").replace(/\\s+/g, " ").trim();
            const allLinks = Array.from(document.querySelectorAll("a"));

            const archiveLink = allLinks.find(el => {
              const row = el.closest("tr");
              if (!row) return false;
              const rowText = text(row.innerText).toLowerCase();
              const href = el.getAttribute("href") || "";
              const label = text(el.innerText);
              return rowText.includes("descargar archivo") &&
                (/bajarArchivo\\.cpe/i.test(href) || /\\.pdf(?:$|\\?)/i.test(href) || /\\.pdf$/i.test(label));
            });
            if (archiveLink) return new URL(archiveLink.getAttribute("href"), location.href).href;

            const sameSitePdf = allLinks.find(el => {
              const href = el.getAttribute("href") || "";
              const label = text(el.innerText);
              const absolute = href ? new URL(href, location.href).href : "";
              return absolute.includes("compraspublicas.gob.ec") &&
                !absolute.includes("gobiernoelectronico.gob.ec") &&
                !absolute.includes("/sercop/") &&
                (/bajarArchivo\\.cpe/i.test(absolute) || /\\.pdf(?:$|\\?)/i.test(absolute) || /\\.pdf$/i.test(label));
            });
            return sameSitePdf || "";
        }"""
    )
    return normalize_text(href)


def get_publication_results_pdf_url(page: Page) -> str:
    href = page.evaluate(
        """() => {
            const text = value => (value || "").replace(/\\s+/g, " ").trim();
            for (const tr of document.querySelectorAll("tr")) {
              const cells = Array.from(tr.querySelectorAll("td"));
              if (cells.length < 3) continue;
              const rowText = text(tr.innerText).toLowerCase();
              if (!rowText.includes("resolucion de adjudicacion")) continue;
              const link = tr.querySelector("a");
              if (!link) continue;
              const href = link.getAttribute("href") || "";
              return new URL(href, location.href).href;
            }
            return "";
        }"""
    )
    return normalize_text(href)


def scrape_products_tab(page: Page) -> list[dict[str, str]]:
    if not has_tab(page, "tab3"):
        return []
    click_tab(page, "tab3")
    rows = page.evaluate(
        """
        () => {
          const text = value => (value ?? "").replace(/\\u00a0/g, " ").replace(/\\s+/g, " ").trim();
          const out = [];
          const isQty = value => /^\\d+(?:[.,]\\d+)?$/.test(value);
          const isMoney = value => /(?:^|\\s)(?:USD\\s*)?[0-9][0-9.,]*$/.test(value) && /[0-9]/.test(value);
          for (const tr of document.querySelectorAll("tr")) {
            const cells = Array.from(tr.querySelectorAll(":scope > td")).map(td => text(td.innerText)).filter(Boolean);
            if (cells.length < 5) continue;
            if (!/^\\d{5,}$/.test(cells[0])) continue;
            const qtyIndex = cells.findIndex((cell, index) => index > 0 && isQty(cell));
            if (qtyIndex < 2 || qtyIndex >= cells.length - 2) continue;
            const moneyIndexes = cells
              .map((cell, index) => ({ cell, index }))
              .filter(entry => entry.index > qtyIndex && isMoney(entry.cell))
              .map(entry => entry.index);
            if (moneyIndexes.length < 2) continue;
            const unitPriceIndex = moneyIndexes[moneyIndexes.length - 2];
            const subtotalIndex = moneyIndexes[moneyIndexes.length - 1];
            const uomIndex = qtyIndex + 1;
            if (uomIndex >= unitPriceIndex) continue;
            out.push({
              item_no: cells[0],
              item_desc: cells.slice(1, qtyIndex).join(" "),
              item_quantity: cells[qtyIndex],
              item_uom: cells[uomIndex],
              item_unit_price: cells[unitPriceIndex],
              item_award_amount: cells[subtotalIndex],
            });
          }
          return out;
        }
        """
    )
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        item_no = str(index)
        item_desc = normalize_text(row.get("item_desc", ""))
        item_quantity = normalize_text(row.get("item_quantity", ""))
        item_uom = normalize_text(row.get("item_uom", ""))
        item_unit_price = parse_money(row.get("item_unit_price", ""))
        item_award_amount = parse_money(row.get("item_award_amount", ""))
        dedup_key = "|".join([item_no, item_desc.lower(), item_quantity, item_uom, item_award_amount])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        if item_desc or item_quantity or item_uom:
            items.append(
                {
                    "item_no": item_no,
                    "item_desc": item_desc,
                    "item_uom": item_uom,
                    "item_quantity": item_quantity,
                    "item_unit_price": item_unit_price,
                    "item_award_amount": item_award_amount,
                }
            )
    return items


def list_archive_pdfs(page: Page) -> list[dict[str, str]]:
    if not has_tab(page, "tab5"):
        return []
    click_tab(page, "tab5")
    return page.evaluate(
        """
        () => {
          const text = value => (value ?? "").replace(/\\u00a0/g, " ").replace(/\\s+/g, " ").trim();
          const out = [];
          for (const tr of document.querySelectorAll("table tr")) {
            const link = tr.querySelector('a[href*="bajarArchivo.cpe"]');
            if (!link) continue;
            const cells = Array.from(tr.querySelectorAll("td")).map(td => text(td.innerText)).filter(Boolean);
            out.push({
              file_name: cells.find(value => value && value !== "Descargar Archivo") || "",
              file_url: new URL(link.getAttribute("href"), location.href).href,
            });
          }
          return out;
        }
        """
    )


def choose_pdf_for_items(archive_rows: list[dict[str, str]]) -> dict[str, str] | None:
    normalized = [(ascii_label(row.get("file_name", "")).upper(), row) for row in archive_rows]
    for preferred in ["PLIEGO Y CONVOCATORIA", "PLIEGOS LEGALIZADOS"]:
        for name, row in normalized:
            if preferred in name:
                return row
    return None


def rank_archive_pdfs(archive_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected = choose_pdf_for_items(archive_rows)
    return [selected] if selected else []


def click_archive_link_and_capture_url(page: Page, file_url: str) -> str:
    popup_url = ""
    try:
        with page.expect_popup(timeout=5000) as popup_info:
            page.evaluate(
                """targetUrl => {
                    const link = Array.from(document.querySelectorAll('a[href*="bajarArchivo.cpe"]'))
                      .find(el => new URL(el.href, location.href).href === targetUrl);
                    if (!link) throw new Error(`Missing archive link for ${targetUrl}`);
                    link.click();
                }""",
                file_url,
            )
        popup = popup_info.value
        try:
            popup.wait_for_load_state("domcontentloaded", timeout=15000)
            popup_url = normalize_text(popup.url)
        finally:
            popup.close()
    except Exception:
        popup_url = ""
    return popup_url


def fetch_pdf_bytes(page: Page, file_url: str) -> bytes:
    popup_url = click_archive_link_and_capture_url(page, file_url)
    request_url = popup_url or file_url
    log_info(f"Downloading PDF via popup click: {request_url}")
    response = page.context.request.get(request_url, fail_on_status_code=False)
    if not response.ok:
        raise RuntimeError(f"Direct fetch failed with status {response.status}")
    pdf_bytes = response.body()
    if not pdf_bytes:
        raise RuntimeError("Direct fetch returned empty body")
    return pdf_bytes


def fetch_pdf_bytes_direct(page: Page, file_url: str) -> bytes:
    response = page.context.request.get(file_url, fail_on_status_code=False)
    if not response.ok:
        raise RuntimeError(f"Direct fetch failed with status {response.status}")
    pdf_bytes = response.body()
    if not pdf_bytes:
        raise RuntimeError("Direct fetch returned empty body")
    return pdf_bytes


def looks_like_pdf(pdf_bytes: bytes) -> bool:
    return pdf_bytes[:5].startswith(b"%PDF")


def get_ocr_reader() -> easyocr.Reader:
    global OCR_READER
    if OCR_READER is None:
        OCR_READER = easyocr.Reader(["es", "en"], gpu=False)
    return OCR_READER


def extract_text_from_rendered_page(pdf_page: pdfium.PdfPage) -> str:
    log_info("EasyOCR on scanned/image page.")
    bitmap = pdf_page.render(scale=PDF_DPI / 72)
    try:
        pil_image = bitmap.to_pil()
        image_array = np.array(pil_image.convert("RGB"))
        lines = get_ocr_reader().readtext(image_array, detail=0, paragraph=True)
        return "\n".join(normalize_text(line) for line in lines if normalize_text(line))
    finally:
        bitmap.close()


def extract_pdf_text(pdf_bytes: bytes) -> str:
    document = pdfium.PdfDocument(pdf_bytes)
    pages_text: list[str] = []
    try:
        log_info(f"Rasterised {len(document)} page(s) via pypdfium2 at {PDF_DPI} DPI.")
        for index in range(len(document)):
            page = document[index]
            text_page = page.get_textpage()
            try:
                log_info(f"Page {index + 1}/{len(document)}...")
                page_text = text_page.get_text_bounded()
                if len(re.sub(r"\s+", "", page_text or "")) < 40:
                    page_text = extract_text_from_rendered_page(page)
            finally:
                text_page.close()
                page.close()
            pages_text.append(page_text or "")
    finally:
        document.close()
    return "\n".join(pages_text)


def parse_items_from_pdf_text(pdf_text: str) -> list[dict[str, str]]:
    lines = [normalize_text(line) for line in pdf_text.splitlines() if normalize_text(line)]
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    patterns = [
        re.compile(
            rf"^(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+(?P<uom>{UOM_PATTERN})\s+"
            rf"(?P<unit>[0-9][0-9.,]*)\s+(?P<total>[0-9][0-9.,]*)$",
            re.IGNORECASE,
        ),
        re.compile(
            rf"^(?P<code>\d{{4,}})\s+(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+(?P<uom>{UOM_PATTERN})\s+"
            rf"(?P<unit>[0-9][0-9.,]*)\s+(?P<total>[0-9][0-9.,]*)$",
            re.IGNORECASE,
        ),
    ]
    for line in lines:
        for pattern in patterns:
            match = pattern.match(line)
            if not match:
                continue
            groups = match.groupdict()
            item_desc = normalize_text(groups.get("desc", ""))
            key = "|".join(
                [
                    item_desc.lower(),
                    normalize_text(groups.get("qty", "")),
                    ascii_label(groups.get("uom", "")),
                    parse_money(groups.get("total", "")),
                ]
            )
            if key in seen:
                break
            seen.add(key)
            items.append(
                {
                    "item_no": str(len(items) + 1),
                    "item_desc": item_desc,
                    "item_uom": normalize_text(groups.get("uom", "")),
                    "item_quantity": normalize_text(groups.get("qty", "")),
                    "item_unit_price": parse_money(groups.get("unit", "")),
                    "item_award_amount": parse_money(groups.get("total", "")),
                }
            )
            break
    return items


def parse_suppliers_from_pdf_text(pdf_text: str) -> list[dict[str, str]]:
    lines = [normalize_text(line) for line in pdf_text.splitlines() if normalize_text(line)]
    suppliers: list[dict[str, str]] = []
    seen: set[str] = set()
    index = 0
    amount_pattern = re.compile(r"\$?\s*([0-9][0-9.,]*)\s*$")
    while index < len(lines):
        current = lines[index]
        if "proveedor" in ascii_label(current) and "monto" in ascii_label(current):
            index += 1
            continue
        match = re.match(r"^(?P<row>\d+)\s+(?P<rest>.+)$", current)
        if not match:
            index += 1
            continue

        supplier_no = normalize_text(match.group("row"))
        remaining = normalize_text(match.group("rest"))
        name_parts: list[str] = []
        amount = ""

        same_line_amount = amount_pattern.search(remaining)
        if same_line_amount:
            amount = parse_money(same_line_amount.group(1))
            name_part = normalize_text(remaining[: same_line_amount.start()])
            if name_part:
                name_parts.append(name_part)
            index += 1
        else:
            if remaining:
                name_parts.append(remaining)
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if re.match(r"^\d+\s+", candidate):
                    break
                amount_match = amount_pattern.search(candidate)
                if amount_match:
                    amount = parse_money(amount_match.group(1))
                    name_part = normalize_text(candidate[: amount_match.start()])
                    if name_part:
                        name_parts.append(name_part)
                    index += 1
                    break
                if ascii_label(candidate) not in {"proveedor", "monto sin incluir iva"}:
                    name_parts.append(candidate)
                index += 1

        name = normalize_text(" ".join(name_parts))
        if not name or not amount:
            continue
        key = f"{name.lower()}|{amount}"
        if key in seen:
            continue
        seen.add(key)
        suppliers.append(
            {
                "supplier_no": supplier_no,
                "supplier_name": name,
                "supplier_amount": amount,
            }
        )
    return suppliers


def scrape_items_from_pdf(page: Page) -> list[dict[str, str]]:
    archive_rows = list_archive_pdfs(page)
    if not archive_rows:
        return []
    for selected_pdf in rank_archive_pdfs(archive_rows):
        try:
            pdf_bytes = fetch_pdf_bytes(page, selected_pdf["file_url"])
            if not looks_like_pdf(pdf_bytes):
                continue
            pdf_text = extract_pdf_text(pdf_bytes)
            items = parse_items_from_pdf_text(pdf_text)
            if items:
                return items
        except Exception:
            continue
    return []


def scrape_suppliers_from_results_pdf(page: Page) -> list[dict[str, str]]:
    publication_results_url = get_publication_results_url(page)
    if not publication_results_url:
        return []

    results_page = page.context.new_page()
    try:
        results_page.goto(publication_results_url, wait_until="domcontentloaded", timeout=60000)
        results_page.wait_for_timeout(1200)
        summary_suppliers = scrape_publication_results_summary(results_page)
        pdf_url = get_publication_results_pdf_url(results_page) or get_first_pdf_url(results_page)
        if not pdf_url:
            return summary_suppliers
        log_info(f"Downloading supplier PDF: {pdf_url}")
        pdf_bytes = fetch_pdf_bytes_direct(results_page, pdf_url)
        if not looks_like_pdf(pdf_bytes):
            return summary_suppliers
        pdf_text = extract_pdf_text(pdf_bytes)
        parsed_suppliers = parse_suppliers_from_pdf_text(pdf_text)
        return parsed_suppliers or summary_suppliers
    except Exception:
        return []
    finally:
        results_page.close()


def scrape_items(page: Page) -> list[dict[str, str]]:
    pdf_items = scrape_items_from_pdf(page)
    if pdf_items:
        return pdf_items
    return scrape_products_tab(page)


def scrape_tender(page: Page, url: str) -> ScrapedTender:
    log_info("Opening tender page")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)

    print_fields: dict[str, str] = {}
    print_url = get_print_page_url(page)
    if print_url:
        log_info("Opening print view for tender details")
        print_page = page.context.new_page()
        try:
            print_page.goto(print_url, wait_until="domcontentloaded", timeout=60000)
            print_page.wait_for_timeout(1200)
            print_fields = scrape_print_fields(print_page)
        finally:
            print_page.close()

    award_info = {"awarding_supplier_name": "", "awarded_date": ""}
    contract_url = get_contract_summary_url(page)
    if contract_url:
        log_info("Opening contract summary for supplier lookup")
        contract_page = page.context.new_page()
        try:
            contract_page.goto(contract_url, wait_until="domcontentloaded", timeout=60000)
            contract_page.wait_for_timeout(1200)
            award_info = scrape_award_info(contract_page)
        finally:
            contract_page.close()
    if not award_info.get("awarding_supplier_name"):
        log_info("Primary supplier lookup empty, trying publication-results fallback")
        supplier_rows = scrape_suppliers_from_results_pdf(page)
    else:
        supplier_rows = [
            {
                "supplier_no": "1",
                "supplier_name": award_info.get("awarding_supplier_name", ""),
                "supplier_amount": "",
            }
        ]

    log_info("Extracting item details")
    items = scrape_items(page)

    raw_status = print_fields.get("status", "")
    return ScrapedTender(
        publication_date=format_datetime(print_fields.get("publication_date", "")),
        closing_date=format_datetime(print_fields.get("closing_date", "")),
        title=print_fields.get("title", ""),
        description=print_fields.get("description", "") or print_fields.get("title", ""),
        buyer=print_fields.get("buyer", ""),
        classification=normalize_text(print_fields.get("classification", "")).rstrip("-").strip(),
        status=normalize_status(raw_status),
        currency="USD" if print_fields.get("amount") else "",
        amount=parse_money(print_fields.get("amount", "")),
        awarding_supplier_name=award_info.get("awarding_supplier_name", ""),
        awarded_date=award_info.get("awarded_date", ""),
        contract_period=print_fields.get("contract_period", ""),
        notice_id=print_fields.get("notice_id", ""),
        notice_url=url,
        items=items,
        suppliers=supplier_rows,
    )


def build_rows(scraped: ScrapedTender) -> list[dict[str, str]]:
    items = scraped.items or [
        {
            "item_no": "1",
            "item_desc": "",
            "item_uom": "",
            "item_quantity": "",
            "item_unit_price": "",
            "item_award_amount": "",
        }
    ]

    suppliers = scraped.suppliers or [
        {
            "supplier_no": "1",
            "supplier_name": scraped.awarding_supplier_name,
            "supplier_amount": "",
        }
    ]

    title_en = translate_text(scraped.title)
    description_en = translate_text(scraped.description)
    buyer_en = translate_text(scraped.buyer)
    classification_en = translate_text(scraped.classification)
    status_en = translate_text(scraped.status)

    rows: list[dict[str, str]] = []
    for supplier in suppliers:
        supplier_name = normalize_text(supplier.get("supplier_name", "")) or scraped.awarding_supplier_name
        supplier_en = translate_text(supplier_name)
        supplier_amount = normalize_text(supplier.get("supplier_amount", ""))
        for item_index, item in enumerate(items, start=1):
            item_desc = item.get("item_desc", "")
            rows.append(
                {
                    "source": "compraspublicas.gob.ec",
                    "country": "Ecuador",
                    "country_code": "EC",
                    "publication_date": scraped.publication_date,
                    "closing_date": scraped.closing_date,
                    "title": scraped.title,
                    "title_en": title_en,
                    "description": scraped.description,
                    "description_en": description_en,
                    "buyer": scraped.buyer,
                    "buyer_en": buyer_en,
                    "classification": scraped.classification,
                    "classification_en": classification_en,
                    "status": scraped.status,
                    "status_en": status_en,
                    "currency": scraped.currency,
                    "amount": scraped.amount,
                    "awarding_supplier_name": supplier_name,
                    "awarding_supplier_name_en": supplier_en,
                    "awarded_date": scraped.awarded_date,
                    "contract_period": scraped.contract_period,
                    "item_no": str(item_index),
                    "item_desc": item_desc,
                    "item_desc_en": translate_text(item_desc),
                    "item_uom": item.get("item_uom", ""),
                    "item_quantity": item.get("item_quantity", ""),
                    "item_unit_price": item.get("item_unit_price", ""),
                    "item_award_amount": supplier_amount or item.get("item_award_amount", ""),
                    "notice_id": scraped.notice_id,
                    "notice_link": f'=HYPERLINK("{scraped.notice_url}","{scraped.notice_id}")' if scraped.notice_id else "",
                    "notice_url": scraped.notice_url,
                    "query_text": "",
                    "scraped_at": "",
                    "dedup_key": slugify(
                        "|".join(
                            [
                                scraped.notice_id,
                                scraped.notice_url,
                                supplier_name,
                                str(item_index),
                                supplier_amount or item.get("item_award_amount", ""),
                            ]
                        )
                    ),
                }
            )
    return rows


def read_notice_urls(csv_path: Path) -> list[str]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    urls: list[str] = []
    seen: set[str] = set()
    for row in rows:
        url = normalize_notice_url(row.get("notice_url", ""))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def read_existing_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {column: row.get(column, "") for column in CSV_COLUMNS}
            for row in csv.DictReader(handle)
        ]


def merge_rows(existing_rows: list[dict[str, str]], new_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    ordered_keys: list[str] = []
    for row in existing_rows + new_rows:
        dedup_key = normalize_text(row.get("dedup_key", ""))
        fallback_key = slugify(
            "|".join(
                [
                    row.get("notice_url", ""),
                    row.get("notice_id", ""),
                    row.get("awarding_supplier_name", ""),
                    row.get("item_no", ""),
                    row.get("item_award_amount", ""),
                ]
            )
        )
        key = dedup_key or fallback_key
        if key not in merged:
            ordered_keys.append(key)
        merged[key] = {column: row.get(column, "") for column in CSV_COLUMNS}
    return [merged[key] for key in ordered_keys]


def get_progress_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_progress.json")


def get_failed_urls_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_failed_urls.csv")


def read_progress(progress_path: Path) -> set[str]:
    if not progress_path.exists():
        return set()
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    completed = payload.get("completed_urls", [])
    return {value for value in completed if isinstance(value, str)}


def write_progress(progress_path: Path, completed_urls: set[str]) -> None:
    progress_path.write_text(
        json.dumps({"completed_urls": sorted(completed_urls)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_failed_urls(failed_urls_path: Path) -> set[str]:
    if not failed_urls_path.exists():
        return set()
    with failed_urls_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {normalize_notice_url(row.get("notice_url", "")) for row in csv.DictReader(handle) if row.get("notice_url")}


def append_failed_url(failed_urls_path: Path, url: str, error_message: str) -> None:
    failed_urls_path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_failed_urls(failed_urls_path)
    if url in existing:
        return
    write_header = not failed_urls_path.exists()
    with failed_urls_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["notice_url", "error_message", "failed_at"])
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "notice_url": url,
                "error_message": error_message,
                "failed_at": datetime.utcnow().isoformat(),
            }
        )


def write_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--show-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    progress_path = get_progress_path(output_path)
    failed_urls_path = get_failed_urls_path(output_path)
    urls = read_notice_urls(input_path)
    if args.limit is not None:
        urls = urls[: args.limit]
    completed_urls = read_progress(progress_path)
    merged_rows = read_existing_rows(output_path)
    total_urls = len(urls)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.show_browser)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            for index, url in enumerate(urls, start=1):
                if url in completed_urls:
                    log_info(f"Skipping completed URL {index}/{total_urls}: [{url}]")
                    continue
                log_info(f"Starting URL {index}/{total_urls}: [{url}]")
                try:
                    scraped = scrape_tender(page, url)
                    new_rows = build_rows(scraped)
                    merged_rows = merge_rows(merged_rows, new_rows)
                    write_rows(output_path, merged_rows)
                    completed_urls.add(url)
                    write_progress(progress_path, completed_urls)
                    log_info(f"Finished URL {index}/{total_urls}; merged rows now {len(merged_rows)}")
                except Exception as error:
                    write_rows(output_path, merged_rows)
                    write_progress(progress_path, completed_urls)
                    append_failed_url(failed_urls_path, url, str(error))
                    log_info(f'Failed URL {index}/{total_urls}; saved to failed file and continuing: [{url}]')
                    continue
        finally:
            context.close()
            browser.close()

    write_rows(output_path, merged_rows)
    write_progress(progress_path, completed_urls)
    print(f"Created file: {output_path}")
    print(f"Failed URLs file: {failed_urls_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
