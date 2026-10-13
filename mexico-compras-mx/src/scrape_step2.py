import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


# -----------------------------
# Config
# -----------------------------
DEFAULT_SHEET = "New Tenders"
DEFAULT_URL_COL = "Dirección del anuncio"

MAIN_TABLE_SEL = "table[role='table']"
DIALOG_SEL = "div[role='dialog']"
DIALOG_TABLE_SEL = f"{DIALOG_SEL} table[role='table']"
DIALOG_OPEN_SEL = "td.p-link2"  # clickable contract number cell
DIALOG_CLOSE_SEL = f"{DIALOG_SEL} button.p-dialog-header-close, {DIALOG_SEL} button:has-text('Cerrar')"

# For PrimeNG hidden columns
H_TH = "thead tr th:not(.ocultar)"
H_TD = "tbody tr td:not(.ocultar)"

BASE_BOOTSTRAP = "https://comprasmx.buengobierno.gob.mx/sitiopublico/"


# -----------------------------
# SPA bootstrap + navigation
# -----------------------------
def bootstrap_spa(page) -> None:
    for attempt in range(2):
        try:
            page.goto(BASE_BOOTSTRAP, wait_until="domcontentloaded", timeout=180_000)
            page.locator("app-root").first.wait_for(state="attached", timeout=60_000)
            page.locator("router-outlet").first.wait_for(state="attached", timeout=60_000)
            page.wait_for_timeout(1500)
            return
        except Exception:
            if attempt == 1:
                raise
            page.wait_for_timeout(2000)


def go_to_contracts_section_if_present(page) -> None:
    """
    Some pages land on "Documentos" by default. If a tab for contracts exists,
    click it. This is best-effort and safe (no-op if not found).
    """
    candidates = ["Contratos", "Contrato", "Adjudicaciones", "Resultados"]
    # Try ARIA tabs first
    for name in candidates:
        loc = page.get_by_role("tab", name=name)
        if loc.count() > 0:
            try:
                loc.first.click()
                page.wait_for_timeout(1500)
                return
            except Exception:
                pass

    # Fallback: plain text click
    for name in candidates:
        loc = page.locator(f"text={name}").first
        if loc.count() > 0:
            try:
                loc.click()
                page.wait_for_timeout(1500)
                return
            except Exception:
                pass


def goto_tender_with_retry(page, url: str) -> None:
    """
    Hash-route navigation after bootstrap.
    If the table doesn't render, re-bootstrap and retry once.
    """
    def _goto_and_wait():
        page.goto(url, wait_until="commit", timeout=180_000)
        # SPA mount signals
        page.locator("app-root").first.wait_for(state="attached", timeout=60_000)
        page.locator("router-outlet").first.wait_for(state="attached", timeout=60_000)

        page.wait_for_timeout(2500)
        go_to_contracts_section_if_present(page)

        # Wait for at least one table on the page
        page.locator(MAIN_TABLE_SEL).first.wait_for(state="visible", timeout=60_000)

    try:
        _goto_and_wait()
    except Exception:
        # Re-bootstrap and retry once
        bootstrap_spa(page)
        _goto_and_wait()


# -----------------------------
# Helpers
# -----------------------------
def safe_text_list(texts: List[str]) -> List[str]:
    return [t.strip().replace("\u00a0", " ") for t in texts if t and t.strip()]


def table_headers(table_locator) -> List[str]:
    return safe_text_list(table_locator.locator("thead tr th").all_inner_texts())


def pick_contracts_table(page):
    """
    Choose the contracts table by header keywords.
    Avoid selecting attachments/documents tables.
    """
    tables = page.locator(MAIN_TABLE_SEL)
    count = tables.count()

    # Keywords that uniquely identify the contracts table
    keywords = [
        "Número de contrato",
        "Importe total sin impuestos",
        "Licitante",
        "Titulo contrato",
        "Título contrato",
        "Estatus contrato",
        "Moneda",
    ]

    # First pass: header match
    for i in range(count):
        t = tables.nth(i)
        try:
            hs = table_headers(t)
        except Exception:
            continue
        joined = " | ".join(hs)
        if any(k in joined for k in keywords):
            return t

    # Second pass: table that contains the dialog link cell
    t_with_link = page.locator(f"{MAIN_TABLE_SEL}:has({DIALOG_OPEN_SEL})").first
    if t_with_link.count() > 0:
        return t_with_link

    # Fallback: first table
    return tables.first


def extract_html_table(table_locator) -> List[Dict[str, str]]:
    """
    Robust extraction for PrimeNG/Angular tables.
    - Waits for table body to have non-empty text
    - Extracts text via JS innerText from visible cells
    - Filters .ocultar columns
    """
    # headers
    headers = safe_text_list(table_locator.locator(H_TH).all_inner_texts())

    # Wait for at least one non-empty cell in tbody (PrimeNG often renders empty first)
    try:
        table_locator.locator("tbody tr td").first.wait_for(state="attached", timeout=30_000)
    except Exception:
        return []

    # Wait until tbody contains some text (best-effort)
    for _ in range(20):
        body_text = (table_locator.locator("tbody").inner_text() or "").strip()
        if body_text:
            break
        time.sleep(0.25)

    # Extract rows via JS for stability
    rows_data = table_locator.evaluate(
        """
        (table) => {
          const rows = Array.from(table.querySelectorAll("tbody tr"));
          return rows.map(tr => {
            const cells = Array.from(tr.querySelectorAll("td")).filter(td => !td.classList.contains("ocultar"));
            return cells.map(td => (td.innerText || "").trim());
          });
        }
        """
    )

    rows: List[Dict[str, str]] = []
    for values in rows_data:
        values = [v.replace("\\u00a0", " ").strip() for v in values]

        row = {h: (values[i] if i < len(values) else "") for i, h in enumerate(headers)}
        if len(values) > len(headers):
            row["_extra_values"] = values[len(headers):]
        rows.append(row)

    return rows

def open_dialog_if_present(page) -> bool:
    link = page.locator(DIALOG_OPEN_SEL).first
    if link.count() == 0:
        return False
    link.click()
    page.locator(DIALOG_SEL).first.wait_for(state="visible", timeout=30_000)
    return True


def close_dialog_if_present(page) -> None:
    btn = page.locator(DIALOG_CLOSE_SEL).first
    if btn.count() > 0:
        btn.click()


@dataclass
class ScrapeResult:
    url: str
    ok: bool
    error: Optional[str]
    main_rows: List[Dict[str, str]]
    dialog_rows: List[Dict[str, str]]
    has_dialog: bool


# -----------------------------
# Core scraping per URL
# -----------------------------
def scrape_one(page, url: str) -> ScrapeResult:
    try:
        goto_tender_with_retry(page, url)

        # MAIN TABLE: contracts table
        main_table = pick_contracts_table(page)
        main_table.wait_for(state="visible", timeout=30_000)
        main_rows = extract_html_table(main_table)

        # DIALOG TABLE (optional)
        dialog_rows: List[Dict[str, str]] = []
        has_dialog = False

        if page.locator(DIALOG_OPEN_SEL).count() > 0:
            has_dialog = open_dialog_if_present(page)
            page.wait_for_timeout(800)  # let dialog table render
            dialog_table = page.locator(DIALOG_TABLE_SEL).first
            dialog_table.wait_for(state="visible", timeout=30_000)
            dialog_rows = extract_html_table(dialog_table)
            close_dialog_if_present(page)


        return ScrapeResult(
            url=url,
            ok=True,
            error=None,
            main_rows=main_rows,
            dialog_rows=dialog_rows,
            has_dialog=has_dialog,
        )

    except PWTimeout as e:
        return ScrapeResult(url=url, ok=False, error=f"Timeout: {e}", main_rows=[], dialog_rows=[], has_dialog=False)
    except Exception as e:
        return ScrapeResult(url=url, ok=False, error=f"{type(e).__name__}: {e}", main_rows=[], dialog_rows=[], has_dialog=False)


# -----------------------------
# Output flattening
# -----------------------------
def flatten_for_csv(res: ScrapeResult) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "URL": res.url,
        "ok": res.ok,
        "error": res.error,
        "has_dialog": res.has_dialog,
        "main_row_count": len(res.main_rows),
        "dialog_row_count": len(res.dialog_rows),
    }

    if res.main_rows:
        for k, v in res.main_rows[0].items():
            row[f"main__{k}"] = v

    if res.dialog_rows:
        for k, v in res.dialog_rows[0].items():
            row[f"dialog__{k}"] = v

    return row


# -----------------------------
# Main runner
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True, help="Path to Excel file, e.g. data/Tender List.xlsx")
    ap.add_argument("--sheet", default=DEFAULT_SHEET)
    ap.add_argument("--url-col", default=DEFAULT_URL_COL)
    ap.add_argument("--limit", type=int, default=0, help="Limit number of URLs for testing (0 = no limit)")
    ap.add_argument("--headless", action="store_true", help="Run headless (default headful)")
    ap.add_argument("--outdir", default="output", help="Output directory")
    args = ap.parse_args()

    excel_path = Path(args.excel)
    outdir = Path(args.outdir)
    (outdir / "raw_jsonl").mkdir(parents=True, exist_ok=True)

    df = pd.read_excel(excel_path, sheet_name=args.sheet)
    if args.url_col not in df.columns:
        raise SystemExit(f"URL column '{args.url_col}' not found. Available columns: {list(df.columns)}")

    urls = df[args.url_col].dropna().astype(str).tolist()
    if args.limit and args.limit > 0:
        urls = urls[: args.limit]

    jsonl_path = outdir / "raw_jsonl" / f"step2_{args.sheet.replace(' ', '_')}.jsonl"
    csv_path = outdir / f"step2_{args.sheet.replace(' ', '_')}_flat.csv"

    flat_rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        # Use real Chrome (more reliable for this site than bundled Chromium)
        browser = p.chromium.launch(
            headless=args.headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )

        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, locale="es-MX")
        page = ctx.new_page()
        page.set_default_timeout(60_000)

        # Critical: bootstrap SPA once before the loop
        bootstrap_spa(page)

        with jsonl_path.open("w", encoding="utf-8") as f:
            for i, url in enumerate(urls, start=1):
                print(f"[{i}/{len(urls)}] {url}")

                res = scrape_one(page, url)

                payload = {
                    "url": res.url,
                    "ok": res.ok,
                    "error": res.error,
                    "has_dialog": res.has_dialog,
                    "main_table": res.main_rows,
                    "dialog_table": res.dialog_rows,
                }
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
                f.flush()

                flat_rows.append(flatten_for_csv(res))

                # light pacing
                time.sleep(0.25)

        ctx.close()
        browser.close()

    pd.DataFrame(flat_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved:")
    print(f"  JSONL: {jsonl_path}")
    print(f"  CSV:   {csv_path}")


if __name__ == "__main__":
    main()
