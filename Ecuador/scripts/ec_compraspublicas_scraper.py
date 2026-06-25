from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from playwright.sync_api import BrowserContext, Page, sync_playwright


SEARCH_URL = "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/buscarProceso.cpe"
DEFAULT_KEYWORDS = [
    "Roche",
    "Mindray",
    "Siemens",
    "Abbott",
    "bioMerieux",
    "Danaher - Cepheid",
    "QuidelOrtho",
    "Werfen",
    "Bio-Rad",
    "Snibe",
    "Wondfo",
    "Illumina",
    "Danaher - Beckman Coulter",
    "Wiener",
    "Sysmex",
    "Qiagen",
    "Thermo Fisher Scientific",
]
DEFAULT_STATES = ["Adjudicada", "En Curso"]
DEFAULT_PROCEDURE = "Licitacion"
DEFAULT_DATE_FROM = "2024-01-01"
DEFAULT_DATE_TO = "2025-12-31"
MAX_WINDOW_DAYS = 180
OUTPUT_COLUMNS = [
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
    "awarding_supplier_name",
    "awarded_date",
    "contract_number",
    "item_no",
    "item_desc",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_award_amount",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at",
    "dedup_key",
]


@dataclass
class QueryWindow:
    keyword: str
    state: str
    date_from: str
    date_to: str


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def normalize_key(value: str | None) -> str:
    text = normalize_text(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.lower()


def slugify(value: str) -> str:
    return re.sub(r"(^_+|_+$)", "", re.sub(r"[^a-z0-9]+", "_", normalize_key(value)))


def parse_money(value: str | None) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned:
        return ""
    if "," in cleaned and "." in cleaned:
        return cleaned.replace(".", "").replace(",", ".")
    if "," in cleaned and "." not in cleaned:
        return cleaned.replace(",", ".")
    return cleaned


def split_date_range(date_from: str, date_to: str, max_days: int = MAX_WINDOW_DAYS) -> Iterable[tuple[str, str]]:
    cursor = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    while cursor <= end:
        window_end = min(cursor + timedelta(days=max_days), end)
        yield cursor.isoformat(), window_end.isoformat()
        cursor = window_end + timedelta(days=1)


def lookup_field(detail_fields: dict[str, str], candidates: list[str]) -> str:
    normalized_candidates = [normalize_key(candidate) for candidate in candidates]
    for label, value in detail_fields.items():
        if normalize_key(label) in normalized_candidates:
            return value
    for label, value in detail_fields.items():
        normalized_label = normalize_key(label)
        if any(candidate in normalized_label for candidate in normalized_candidates):
            return value
    return ""


def map_item_rows(item_tables: list[dict]) -> list[dict[str, str]]:
    if not item_tables:
        return []

    first_table = item_tables[0]
    headers = [normalize_key(header) for header in first_table.get("headers", [])]
    rows: list[dict[str, str]] = []

    for raw_row in first_table.get("rows", []):
        row = {
            "item_no": "",
            "item_desc": "",
            "item_uom": "",
            "item_quantity": "",
            "item_unit_price": "",
            "item_award_amount": "",
        }
        for index, value in enumerate(raw_row):
            header = headers[index] if index < len(headers) else ""
            if not row["item_no"] and re.search(r"(item|numero|no\.)", header):
                row["item_no"] = value
            elif not row["item_desc"] and re.search(r"(descripcion|detalle|producto|objeto)", header):
                row["item_desc"] = value
            elif not row["item_uom"] and re.search(r"(unidad|uom|medida)", header):
                row["item_uom"] = value
            elif not row["item_quantity"] and re.search(r"(cantidad|qty)", header):
                row["item_quantity"] = value
            elif not row["item_unit_price"] and re.search(r"(precio unitario|valor unitario|unitario)", header):
                row["item_unit_price"] = parse_money(value)
            elif not row["item_award_amount"] and re.search(r"(subtotal|total|monto|valor total)", header):
                row["item_award_amount"] = parse_money(value)
        if any(row.values()):
            rows.append(row)
    return rows


def build_output_rows(summary: dict, detail: dict | None, query_text: str, procedure: str) -> list[dict[str, str]]:
    detail_fields = (detail or {}).get("fields", {})
    item_rows = map_item_rows((detail or {}).get("itemTables", []))
    amount = parse_money(
        summary.get("budget")
        or lookup_field(
            detail_fields,
            ["presupuesto referencial total(sin iva)", "presupuesto referencial", "monto referencial"],
        )
    )

    base = {
        "source": "compraspublicas.gob.ec",
        "country": "Ecuador",
        "country_code": "EC",
        "publication_date": summary.get("publicationDate", ""),
        "closing_date": lookup_field(
            detail_fields,
            [
                "fecha limite de propuestas",
                "fecha limite",
                "fecha cierre",
                "fecha de cierre",
                "fecha maxima de entrega",
            ],
        ),
        "title": summary.get("title")
        or lookup_field(detail_fields, ["objeto del proceso", "descripcion", "descripcion del proceso"]),
        "description": lookup_field(detail_fields, ["descripcion", "descripcion del proceso", "objeto del proceso"])
        or summary.get("title", ""),
        "buyer": summary.get("buyer")
        or lookup_field(detail_fields, ["entidad contratante", "razon social", "comprador"]),
        "classification": lookup_field(detail_fields, ["tipo de contratacion", "tipo de proceso", "procedimiento"])
        or procedure,
        "status": summary.get("status", ""),
        "currency": lookup_field(detail_fields, ["moneda"]) or ("USD" if amount else ""),
        "amount": amount,
        "awarding_supplier_name": lookup_field(
            detail_fields,
            ["proveedor adjudicado", "adjudicatario", "nombre del adjudicatario", "contratista"],
        ),
        "awarded_date": lookup_field(
            detail_fields,
            ["fecha de adjudicacion", "fecha adjudicacion", "fecha de formalizacion"],
        ),
        "contract_number": lookup_field(
            detail_fields,
            ["codigo del proceso", "codigo de proceso", "numero de contrato", "codigo"],
        )
        or summary.get("noticeId", ""),
        "notice_id": summary.get("noticeId", ""),
        "notice_url": summary.get("noticeUrl", ""),
        "query_text": query_text,
        "scraped_at": datetime.utcnow().isoformat(),
    }

    expanded = item_rows or [{}]
    output_rows: list[dict[str, str]] = []
    for index, item_row in enumerate(expanded, start=1):
        output_rows.append(
            {
                **base,
                "item_no": item_row.get("item_no", "") or str(index),
                "item_desc": item_row.get("item_desc", ""),
                "item_uom": item_row.get("item_uom", ""),
                "item_quantity": item_row.get("item_quantity", ""),
                "item_unit_price": item_row.get("item_unit_price", ""),
                "item_award_amount": item_row.get("item_award_amount", ""),
                "dedup_key": slugify(
                    "|".join(
                        [
                            query_text,
                            summary.get("noticeId", ""),
                            summary.get("noticeUrl", ""),
                            item_row.get("item_no", "") or str(index),
                            summary.get("status", ""),
                        ]
                    )
                ),
            }
        )
    return output_rows


def accept_cookies(page: Page) -> None:
    button = page.get_by_role("button", name=re.compile(r"aceptar|dismiss cookie message", re.I))
    if button.count():
        try:
            button.first.click()
        except Exception:
            pass


def select_option_by_loose_label(page: Page, selector: str, desired_label: str) -> None:
    value = page.locator(selector).evaluate(
        """
        (element, rawLabel) => {
          const normalize = (input) =>
            (input ?? "")
              .normalize("NFD")
              .replace(/[\\u0300-\\u036f]/g, "")
              .replace(/\\s+/g, " ")
              .trim()
              .toLowerCase();
          const wanted = normalize(rawLabel);
          const match = Array.from(element.options).find((option) => normalize(option.label) === wanted);
          return match ? match.value : null;
        }
        """,
        desired_label,
    )
    if not value:
        raise RuntimeError(f'Could not find option "{desired_label}" for {selector}')
    page.locator(selector).select_option(value=value)


def fill_search_form(page: Page, query: QueryWindow, procedure: str) -> None:
    page.goto(SEARCH_URL, wait_until="domcontentloaded")
    accept_cookies(page)
    page.locator("#txtPalabrasClaves").fill(query.keyword)
    select_option_by_loose_label(page, "#txtCodigoTipoCompra", procedure)
    page.wait_for_timeout(1500)
    if query.state:
        page.wait_for_selector("#cmbEstado", timeout=10000)
        select_option_by_loose_label(page, "#cmbEstado", query.state)
    page.locator("#f_inicio").fill(query.date_from)
    page.locator("#f_fin").fill(query.date_to)


def wait_for_manual_captcha(page: Page, query: QueryWindow) -> None:
    print("")
    print(
        f'Captcha required for keyword="{query.keyword}", state="{query.state}", '
        f"range={query.date_from}..{query.date_to}."
    )
    input("Type the captcha in the browser, click Buscar if you want, then press Enter here to continue. ")
    captcha_value = ""
    try:
        captcha_value = page.locator("#image").input_value()
    except Exception:
        pass
    has_results = page.locator("text=Procesos del").count() > 0
    if not captcha_value and not has_results:
        raise RuntimeError("Captcha input is empty. Solve the captcha in the browser before continuing.")


def submit_search(page: Page) -> None:
    if page.locator("text=Procesos del").count():
        return
    page.locator("a.toolbarbotones", has_text="Buscar").last.click()
    try:
        page.wait_for_load_state("networkidle")
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if page.locator("text=Captcha Incorrecto").count():
        raise RuntimeError("The site rejected the captcha. Re-run that query and enter the captcha again.")


def extract_rows_on_current_page(page: Page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const text = (value) => (value ?? "").replace(/\\u00a0/g, " ").replace(/\\s+/g, " ").trim();
          const resultContainer = document.querySelector("#divProcesos");
          if (!resultContainer) return [];
          const table = resultContainer.querySelector("table");
          if (!table) return [];
          return Array.from(table.querySelectorAll("tr"))
            .slice(1)
            .map((row) => {
              const cells = Array.from(row.querySelectorAll("td"));
              if (cells.length < 7) return null;
              const noticeLink = cells[0].querySelector("a");
              return {
                noticeId: text(cells[0].innerText),
                noticeUrl: noticeLink ? new URL(noticeLink.getAttribute("href"), location.href).href : "",
                buyer: text(cells[1].innerText),
                title: text(cells[2].innerText),
                status: text(cells[3].innerText),
                purchaseType: cells.length === 8 ? "" : text(cells[4].innerText),
                province: text(cells[cells.length === 8 ? 4 : 5].innerText),
                budget: text(cells[cells.length === 8 ? 5 : 6].innerText),
                publicationDate: text(cells[cells.length === 8 ? 6 : 7].innerText),
                optionsText: text((cells[cells.length === 8 ? 7 : 8] || {}).innerText || "")
              };
            })
            .filter(Boolean);
        }
        """
    )


def go_to_next_page(page: Page) -> bool:
    next_link = page.locator("a", has_text="Siguiente")
    if not next_link.count():
        return False
    next_link.first.click()
    page.wait_for_timeout(2000)
    return True


def collect_summary_rows(page: Page) -> list[dict]:
    all_rows: list[dict] = []
    page_index = 1
    while True:
        rows = extract_rows_on_current_page(page)
        for row in rows:
            row["resultPage"] = page_index
            all_rows.append(row)
        if not go_to_next_page(page):
            break
        page_index += 1
    return all_rows


def extract_detail_payload(detail_page: Page) -> dict:
    return detail_page.evaluate(
        """
        () => {
          const text = (value) => (value ?? "").replace(/\\u00a0/g, " ").replace(/\\s+/g, " ").trim();
          const normalize = (value) =>
            text(value).normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
          const fieldMap = {};
          for (const table of document.querySelectorAll("table")) {
            for (const row of table.querySelectorAll("tr")) {
              const cells = Array.from(row.querySelectorAll("td, th"));
              if (cells.length === 2) {
                const label = text(cells[0].innerText).replace(/:$/, "");
                const value = text(cells[1].innerText);
                if (label && value && !fieldMap[label]) fieldMap[label] = value;
              }
            }
          }
          const itemTables = [];
          for (const table of document.querySelectorAll("table")) {
            const headers = Array.from(table.querySelectorAll("tr"))
              .slice(0, 2)
              .flatMap((row) => Array.from(row.querySelectorAll("th, td")).map((cell) => text(cell.innerText)))
              .filter(Boolean);
            const normalizedHeaders = headers.map(normalize);
            const looksLikeItems = normalizedHeaders.some((header) =>
              ["descripcion", "cantidad", "unidad", "precio unitario", "item", "producto"].some((token) =>
                header.includes(token)
              )
            );
            if (!looksLikeItems) continue;
            const rows = Array.from(table.querySelectorAll("tr"))
              .map((row) => Array.from(row.querySelectorAll("td")).map((cell) => text(cell.innerText)))
              .filter((cells) => cells.length >= 2);
            if (rows.length) itemTables.push({ headers, rows });
          }
          return {
            title: text(document.title),
            pageText: text(document.body.innerText).slice(0, 5000),
            fields: fieldMap,
            itemTables
          };
        }
        """
    )


def scrape_detail_page(context: BrowserContext, summary: dict, query_text: str, procedure: str) -> list[dict[str, str]]:
    page = context.new_page()
    try:
        page.goto(summary["noticeUrl"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)
        detail = extract_detail_payload(page)
        return build_output_rows(summary, detail, query_text, procedure)
    except Exception as exc:
        return [
            {
                **row,
                "description": row["description"] or f"Detail page unavailable: {exc}",
            }
            for row in build_output_rows(summary, None, query_text, procedure)
        ]
    finally:
        page.close()


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--keywords", default="|".join(DEFAULT_KEYWORDS))
    parser.add_argument("--states", default="|".join(DEFAULT_STATES))
    parser.add_argument("--procedure", default=DEFAULT_PROCEDURE)
    parser.add_argument("--date-from", default=DEFAULT_DATE_FROM)
    parser.add_argument("--date-to", default=DEFAULT_DATE_TO)
    parser.add_argument("--output", default="output/ecuador_tenders.csv")
    parser.add_argument("--slow-mo", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    keywords = [value.strip() for value in args.keywords.split("|") if value.strip()]
    states = [value.strip() for value in args.states.split("|") if value.strip()]
    date_windows = list(split_date_range(args.date_from, args.date_to))
    output_rows: list[dict[str, str]] = []

    print(f"Prepared {len(date_windows)} date window(s) for {args.date_from}..{args.date_to}.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless, slow_mo=args.slow_mo)
        context = browser.new_context()
        page = context.new_page()

        try:
            for keyword in keywords:
                for state in states:
                    for date_from, date_to in date_windows:
                        query = QueryWindow(keyword=keyword, state=state, date_from=date_from, date_to=date_to)
                        print(
                            f'Running search for keyword="{query.keyword}", state="{query.state}", '
                            f"date={query.date_from}..{query.date_to}"
                        )
                        fill_search_form(page, query, args.procedure)
                        wait_for_manual_captcha(page, query)
                        submit_search(page)

                        if page.locator("text=No existen procesos para la consulta ingresada").count():
                            print("No results returned for this query window.")
                            continue

                        summaries = collect_summary_rows(page)
                        print(f"Collected {len(summaries)} summary row(s).")
                        for summary in summaries:
                            output_rows.extend(scrape_detail_page(context, summary, keyword, args.procedure))
        finally:
            browser.close()

    write_csv(output_rows, Path(args.output).resolve())
    print(f"Saved {len(output_rows)} row(s) to {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
