from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from playwright.sync_api import BrowserContext, Page, sync_playwright


SEARCH_URL = "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/buscarProceso.cpe"
DEFAULT_KEYWORDS = [
    "reactivos",
    "insumos",
    "kits",
    "pruebas",
    "determinaciones",
    "cartuchos",
    "consumibles",
    "calibradores",
    "controles",
    "material de control",
    "equipo",
    "analizador",
    "sistema automatizado",
    "plataforma",
    "instrumento",
    "módulo",
    "lector",
    "termociclador",
    "laboratorio clínico",
    "servicio de laboratorio",
    "microbiología",
    "banco de sangre",
    "IESS",
    "MSP",
    "centro de salud",
]
DEFAULT_STATES = [""]
DEFAULT_PROCEDURE = "TODOS"
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
    "notice_link",
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


def normalize_match_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_key(value))


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


def build_output_rows(summary: dict, query_text: str, procedure: str) -> list[dict[str, str]]:
    amount = parse_money(
        summary.get("budget")
    )

    base = {
        "source": "compraspublicas.gob.ec",
        "country": "Ecuador",
        "country_code": "EC",
        "publication_date": summary.get("publicationDate", ""),
        "closing_date": "",
        "title": summary.get("title", ""),
        "description": summary.get("title", ""),
        "buyer": summary.get("buyer", ""),
        "classification": procedure,
        "status": summary.get("status", ""),
        "currency": "USD" if amount else "",
        "amount": amount,
        "awarding_supplier_name": "",
        "awarded_date": "",
        "contract_number": summary.get("noticeId", ""),
        "notice_id": summary.get("noticeId", ""),
        "notice_link": f'=HYPERLINK("{summary.get("noticeUrl", "")}","{summary.get("noticeId", "")}")'
        if summary.get("noticeUrl") and summary.get("noticeId")
        else "",
        "notice_url": summary.get("noticeUrl", ""),
        "query_text": query_text,
        "scraped_at": datetime.utcnow().isoformat(),
    }

    return [
        {
            **base,
            "item_no": "1",
            "item_desc": "",
            "item_uom": "",
            "item_quantity": "",
            "item_unit_price": "",
            "item_award_amount": "",
            "dedup_key": slugify(
                "|".join(
                    [
                        query_text,
                        summary.get("noticeId", ""),
                        summary.get("noticeUrl", ""),
                        summary.get("status", ""),
                    ]
                )
            ),
        }
    ]


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
    if procedure and normalize_key(procedure) not in {"todos", "todas", "all"}:
        select_option_by_loose_label(page, "#txtCodigoTipoCompra", procedure)
    page.wait_for_timeout(1500)
    if query.state:
        page.wait_for_selector("#cmbEstado", timeout=10000)
        select_option_by_loose_label(page, "#cmbEstado", query.state)
    page.locator("#f_inicio").evaluate("(element, value) => { element.value = value; }", query.date_from)
    page.locator("#f_fin").evaluate("(element, value) => { element.value = value; }", query.date_to)


def wait_for_manual_captcha(page: Page, query: QueryWindow, captcha_image_path: Path) -> None:
    print("")
    print(f'Captcha required for state="{query.state}", range={query.date_from}..{query.date_to}.')
    captcha_image_path.parent.mkdir(parents=True, exist_ok=True)
    page.locator("#captcha_img").screenshot(path=str(captcha_image_path))
    print(f"Captcha image saved to: {captcha_image_path}")
    captcha_value = normalize_text(input("Type the captcha from the saved image and press Enter: "))
    if not captcha_value:
        raise RuntimeError("Captcha input is empty.")
    page.locator("#image").fill(captcha_value)


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
    current_page_text = normalize_text(page.locator("text=Procesos del").first.text_content()) if page.locator("text=Procesos del").count() else ""
    next_link = page.locator("a", has_text="Siguiente")
    if not next_link.count():
        return False
    next_link.first.click()
    try:
        page.wait_for_function(
            """previousText => {
                const node = Array.from(document.querySelectorAll("*"))
                  .find(el => (el.innerText || "").includes("Procesos del"));
                const currentText = node ? (node.innerText || "").replace(/\\s+/g, " ").trim() : "";
                return currentText && currentText !== previousText;
            }""",
            current_page_text,
            timeout=10000,
        )
    except Exception:
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


def merge_rows(existing_rows: list[dict[str, str]], new_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str], dict[str, str]] = {}
    ordered_keys: list[tuple[str, str]] = []

    for row in existing_rows + new_rows:
        key = (
            normalize_text(row.get("notice_url", "")),
            normalize_text(row.get("notice_id", "")),
        )
        if key not in merged:
            ordered_keys.append(key)
        merged[key] = {column: row.get(column, "") for column in OUTPUT_COLUMNS}

    return [merged[key] for key in ordered_keys]


def read_existing_rows(output_path: Path) -> list[dict[str, str]]:
    if not output_path.exists():
        return []
    with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {column: row.get(column, "") for column in OUTPUT_COLUMNS}
            for row in csv.DictReader(handle)
        ]


def get_progress_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_progress.json")


def query_progress_key(query: QueryWindow) -> str:
    return json.dumps(
        {
            "keyword": query.keyword,
            "state": query.state,
            "date_from": query.date_from,
            "date_to": query.date_to,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def read_progress(progress_path: Path) -> set[str]:
    if not progress_path.exists():
        return set()
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    completed = payload.get("completed", [])
    return {value for value in completed if isinstance(value, str)}


def write_progress(progress_path: Path, completed: set[str]) -> None:
    progress_path.write_text(
        json.dumps({"completed": sorted(completed)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--output", default="output/ecuador_tenders.csv")
    parser.add_argument("--slow-mo", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    keywords = [value.strip() for value in args.keywords.split("|") if value.strip()]
    states = [value.strip() for value in args.states.split("|") if value.strip()]
    if not states:
        states = [""]
    date_windows = list(split_date_range(args.date_from, args.date_to))
    output_path = Path(args.output).resolve()
    captcha_image_path = output_path.parent / "captcha.png"
    progress_path = get_progress_path(output_path)
    completed_queries = read_progress(progress_path)
    merged_rows = read_existing_rows(output_path)

    print(f"Prepared {len(date_windows)} date window(s) for {args.date_from}..{args.date_to}.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless, slow_mo=args.slow_mo)
        page = browser.new_context().new_page()

        try:
            for keyword in keywords:
                for state in states:
                    for date_from, date_to in date_windows:
                        query = QueryWindow(keyword=keyword, state=state, date_from=date_from, date_to=date_to)
                        progress_key = query_progress_key(query)
                        if progress_key in completed_queries:
                            print(
                                f'Skipping completed query keyword="{query.keyword}", '
                                f'state="{query.state}", date={query.date_from}..{query.date_to}'
                            )
                            continue
                        print(
                            f'Running search for keyword="{query.keyword}", '
                            f'state="{query.state}", date={query.date_from}..{query.date_to}'
                        )
                        fill_search_form(page, query, args.procedure)
                        try:
                            wait_for_manual_captcha(page, query, captcha_image_path)
                            submit_search(page)
                        except RuntimeError as error:
                            write_csv(merged_rows, output_path)
                            write_progress(progress_path, completed_queries)
                            raise RuntimeError(
                                f"{error} Resume by re-running the script; it will continue from "
                                f'keyword="{query.keyword}" date={query.date_from}..{query.date_to}.'
                            ) from error

                        if page.locator("text=No existen procesos para la consulta ingresada").count():
                            print("No results returned for this query window.")
                            completed_queries.add(progress_key)
                            write_progress(progress_path, completed_queries)
                            continue

                        summaries = collect_summary_rows(page)
                        print(f"Collected {len(summaries)} summary row(s).")
                        new_rows: list[dict[str, str]] = []
                        for summary in summaries:
                            new_rows.extend(build_output_rows(summary, query.keyword, args.procedure))
                        merged_rows = merge_rows(merged_rows, new_rows)
                        write_csv(merged_rows, output_path)
                        completed_queries.add(progress_key)
                        write_progress(progress_path, completed_queries)
        finally:
            browser.close()

    write_csv(merged_rows, output_path)
    write_progress(progress_path, completed_queries)
    print(f"Saved {len(merged_rows)} merged row(s) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
