"""
PNCP Portal Browser Scraper  —  pncp_browser_scraper.py
========================================================
Opens https://pncp.gov.br/app/editais in a real browser,
types each keyword into "Palavra-chave", sets the date filter,
then visits EVERY notice URL, reads the tender detail page,
and pages through ALL item rows (including Página: arrows).

This script mimics a real user exactly — it is the safest approach
when the raw API is slow or returns incomplete item-level data.

REQUIRES
--------
    pip install playwright pandas openpyxl tqdm
    playwright install chromium

USAGE
-----
    python pncp_browser_scraper.py               # headless (default)
    python pncp_browser_scraper.py --visible     # watch the browser

OUTPUT
------
    pncp_browser_results_<timestamp>.xlsx
    pncp_browser_checkpoint.json   (deleted on success; resume on crash)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path
import re
import pandas as pd
from tqdm import tqdm

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DATE_START = date(2024, 1, 1)
DATE_END   = date.today()

KEYWORDS: list[str] = [
    "reagente química clínica",
    "reagente hematologia",
    "reagente imunológico",
    "diagnóstico molecular",
    "PCR",
    "reagente microbiologia",
    "reagente laboratório",
    "banco de sangue",
    "equipamento laboratório",
    "hematologia",
    "imunologia",
    "química clínica",
    "reagente químico",
    "diagnóstico",
]

PORTAL_URL       = "https://pncp.gov.br/app/editais"
CONSULTA_BASE    = "https://pncp.gov.br/api/consulta/v1"
CHECKPOINT_FILE  = Path("pncp_browser_checkpoint.json")
PAGE_TIMEOUT     = 90_000     # ms
WAIT_NETWORK     = 8_000      # ms to wait for network idle after actions
ITEM_PAGE_SIZE   = 20         # how many items to request per API call

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# LOOKUP TABLES
# ─────────────────────────────────────────────────────────────────────────────

MODALIDADE_MAP = {
    1: "Leilão - Eletrônico",      2: "Diálogo Competitivo",
    3: "Concurso",                  4: "Concorrência - Eletrônica",
    5: "Concorrência - Presencial", 6: "Pregão - Eletrônico",
    7: "Pregão - Presencial",       8: "Dispensa de Licitação",
    9: "Inexigibilidade",          10: "Manifestação de Interesse",
    11: "Pré-qualificação",        12: "Credenciamento",
    13: "Leilão - Presencial",
}

SITUACAO_MAP = {
    1: "Divulgada no PNCP", 2: "Revogada",  3: "Anulada",
    4: "Suspensa",          5: "Encerrada", 6: "Deserta",
    7: "Fracassada",
}

# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINT
# ─────────────────────────────────────────────────────────────────────────────

def load_checkpoint() -> tuple[set[str], list[dict]]:
    if CHECKPOINT_FILE.exists():
        try:
            cp = json.loads(CHECKPOINT_FILE.read_text())
            return set(cp.get("done_kw", [])), cp.get("rows", [])
        except Exception:
            pass
    return set(), []


def save_checkpoint(done: set[str], rows: list[dict]) -> None:
    CHECKPOINT_FILE.write_text(json.dumps({"done_kw": sorted(done), "rows": rows}))

# ─────────────────────────────────────────────────────────────────────────────
# FLATTEN
# ─────────────────────────────────────────────────────────────────────────────

def build_row(tender: dict, item: dict, resultado: dict | None, kw: str) -> dict:
    orgao   = tender.get("orgaoEntidade", {}) or {}
    unidade = tender.get("unidadeOrgao",  {}) or {}
    amparo  = tender.get("amparoLegal",   {}) or {}

    cnpj    = orgao.get("cnpj", "")
    ano     = tender.get("anoCompra", "")
    seq     = tender.get("sequencialCompra", "")
    sit_id  = tender.get("situacaoCompraId") or tender.get("situacaoId")
    status  = SITUACAO_MAP.get(sit_id, tender.get("situacaoCompraNome", ""))
    mod_id  = tender.get("modalidadeId")
    mod_lbl = MODALIDADE_MAP.get(mod_id, tender.get("modalidadeNome", ""))
    srp     = tender.get("srp", False)
    if srp and mod_lbl:
        mod_lbl += " / Ata SRP"
    url_str = (f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"
               if cnpj and ano and seq else "")

    row = {
        "Tender_ID":           f"{cnpj}-{ano}-{seq}",
        "Buying_Entity":       orgao.get("razaoSocial", ""),
        "Buyer_CNPJ":          cnpj,
        "State_UF":            unidade.get("ufSigla", ""),
        "State_Name":          unidade.get("ufNome", ""),
        "City":                unidade.get("municipioNome", ""),
        "IBGE_Code":           unidade.get("codigoIbge", ""),
        "Tender_Object":       tender.get("objetoCompra", ""),
        "Total_Value_BRL":     (tender.get("valorTotalEstimado")
                                or tender.get("valorTotalHomologado")),
        "Publication_Date":    tender.get("dataPublicacaoPncp", ""),
        "Opening_Date":        tender.get("dataAberturaProposta", ""),
        "Closing_Date":        tender.get("dataEncerramentoProposta", ""),
        "Status":              status,
        "Tender_Type":         mod_lbl,
        "Ata_SRP":             srp,
        "Amparo_Legal_Code":   amparo.get("codigo", ""),
        "Amparo_Legal_Desc":   amparo.get("descricao", ""),
        "Tender_URL":          url_str,
        "Item_Number":         item.get("numeroItem", ""),
        "Product_Description": item.get("descricao") or item.get("descricaoItem", ""),
        "Brand":               item.get("marca", ""),
        "Manufacturer":        item.get("fabricante") or item.get("nomeFabricante", ""),
        "Catalog_Code_CATMAT": item.get("codigoCatalogoItem") or item.get("catalogoItemId", ""),
        "Quantity":            item.get("quantidade", ""),
        "Unit":                item.get("unidadeMedida") or item.get("unidade", ""),
        "Unit_Price_BRL":      item.get("valorUnitarioEstimado") or item.get("valorUnitario", ""),
        "Item_Total_BRL":      item.get("valorTotal", ""),
        "Supplier_Name":       "",
        "Supplier_CNPJ":       "",
        "Supplier_Brand":      "",
        "Matched_Keyword":     kw,
    }
    if resultado:
        row["Supplier_Name"]  = resultado.get("nomeRazaoSocialFornecedor", "")
        row["Supplier_CNPJ"]  = resultado.get("niFornecedor") or resultado.get("cnpjFornecedor", "")
        row["Supplier_Brand"] = resultado.get("marca", "")
        if resultado.get("valorUnitario"):
            row["Unit_Price_BRL"] = resultado["valorUnitario"]
    return row

# ─────────────────────────────────────────────────────────────────────────────
# PLAYWRIGHT SCRAPER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class PNCPBrowserScraper:
    """
    Opens a single browser session and reuses it across all keyword searches.
    For each keyword:
      1. Goes to PORTAL_URL
      2. Types keyword into Palavra-chave input
      3. Sets date range
      4. Submits and waits for results
      5. Intercepts the XHR to get the tender list JSON
      6. For each tender URL: opens detail page, intercepts item JSON,
         pages through all item pages
      7. For each item: calls API directly for resultado (supplier winner)
    """

    def __init__(self, headless: bool = True):
        from playwright.sync_api import sync_playwright
        self._pw_cm   = sync_playwright()
        self._pw      = self._pw_cm.__enter__()
        self.browser  = self._pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        self.context  = self.browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
        )
        self.page     = self.context.new_page()

        # Intercept ALL API responses
        self._xhr_responses: list[dict] = []
        self.page.on("response", self._on_response)

        # requests session for direct API calls (items / resultado)
        import requests as rq
        self._s = rq.Session()
        self._s.headers.update({
            "User-Agent":  "Mozilla/5.0",
            "Accept":      "application/json",
            "Referer":     "https://pncp.gov.br/",
        })

    # ── internal helpers ──────────────────────────────────────────

    def _on_response(self, response):
        if ("api/consulta" in response.url and
                response.status == 200 and
                response.request.resource_type in ("fetch", "xhr", "other")):
            try:
                self._xhr_responses.append({
                    "url":  response.url,
                    "body": response.json(),
                })
            except Exception:
                pass

    def _clear_xhr(self):
        self._xhr_responses.clear()

    def _api(self, url: str, params: dict | None = None, retries: int = 4):
        import requests as rq
        for attempt in range(1, retries + 1):
            try:
                r = self._s.get(url, params=params, timeout=(10, 40))
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (204, 404):
                    return None
                if r.status_code in (429,) or r.status_code >= 500:
                    wait = 12 * attempt
                    log.warning("HTTP %s → retry %d in %ds",
                                r.status_code, attempt, wait)
                    time.sleep(wait)
                    continue
                return None
            except rq.Timeout:
                time.sleep(12 * attempt)
            except rq.RequestException as e:
                log.warning("API error: %s", e)
                return None
        return None

    def _wait_idle(self, ms: int = WAIT_NETWORK):
        try:
            self.page.wait_for_load_state("networkidle", timeout=ms)
        except Exception:
            self.page.wait_for_timeout(2_000)

    # ── search for one keyword ────────────────────────────────────

    def search(self, keyword: str) -> list[dict]:
        """
        Navigate to the portal, fill in keyword + status + dates, submit.
        Returns list of tender dicts (from intercepted XHR).
        """
        from playwright.sync_api import TimeoutError as PWTimeout

        log.info("  Navigating portal for '%s' …", keyword)
        self._clear_xhr()

        try:
            self.page.goto(PORTAL_URL, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            self._wait_idle()
            self.page.wait_for_timeout(1500)
        except Exception as e:
            log.warning("  Page load error: %s", e)
            return []

        # ── Palavra-chave ───────────────────────────────────────────
        kw_filled = False
        kw_locators = [
            self.page.get_by_label("Palavra-chave"),
            self.page.locator("input[placeholder*='Palavra-chave']"),
            self.page.locator("input[placeholder*='palavra']"),
            self.page.locator("input[name='q']"),
            self.page.locator("input[id='q']"),
            self.page.locator("input[type='search']"),
        ]

        for loc in kw_locators:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    loc.first.fill("")
                    loc.first.fill(keyword)
                    kw_filled = True
                    break
            except Exception:
                continue

        if not kw_filled:
            try:
                inputs = self.page.query_selector_all("input[type='text']")
                for inp in inputs:
                    if inp.is_visible():
                        inp.click()
                        inp.fill("")
                        inp.fill(keyword)
                        kw_filled = True
                        break
            except Exception:
                pass

        if not kw_filled:
            log.warning("  Could not find keyword input for '%s'", keyword)

        self.page.wait_for_timeout(400)

        # ── Status = Todos ──────────────────────────────────────────
        status_set = False
        try:
            self.page.get_by_label("Todos").check()
            status_set = True
        except Exception:
            pass

        if not status_set:
            try:
                self.page.locator("label:has-text('Todos')").click()
                status_set = True
            except Exception:
                pass

        if not status_set:
            try:
                self.page.get_by_text("Todos", exact=True).click()
                status_set = True
            except Exception:
                pass

        if status_set:
            log.info("  Status set to 'Todos'")
        else:
            log.warning("  Could not explicitly set Status='Todos'")

        self.page.wait_for_timeout(400)

        # ── Date inputs ─────────────────────────────────────────────
        d_start_str = DATE_START.strftime("%d/%m/%Y")
        d_end_str = DATE_END.strftime("%d/%m/%Y")

        start_filled = False
        end_filled = False

        start_locators = [
            self.page.get_by_label("Data inicial"),
            self.page.locator("input[placeholder*='Data inicial']"),
            self.page.locator("input[placeholder*='Período inicial']"),
            self.page.locator("input[id*='dataInicial']"),
            self.page.locator("input[name*='dataInicial']"),
            self.page.locator("input[id*='inicio']"),
        ]
        end_locators = [
            self.page.get_by_label("Data final"),
            self.page.locator("input[placeholder*='Data final']"),
            self.page.locator("input[placeholder*='Período final']"),
            self.page.locator("input[id*='dataFinal']"),
            self.page.locator("input[name*='dataFinal']"),
            self.page.locator("input[id*='fim']"),
        ]

        for loc in start_locators:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    loc.first.fill("")
                    loc.first.fill(d_start_str)
                    start_filled = True
                    break
            except Exception:
                continue

        for loc in end_locators:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    loc.first.fill("")
                    loc.first.fill(d_end_str)
                    end_filled = True
                    break
            except Exception:
                continue

        # fallback: first two visible text/date inputs that look like date filters
        if not (start_filled and end_filled):
            try:
                candidates = self.page.query_selector_all("input")
                visible = []
                for el in candidates:
                    try:
                        typ = (el.get_attribute("type") or "").lower()
                        ph = (el.get_attribute("placeholder") or "").lower()
                        idv = (el.get_attribute("id") or "").lower()
                        name = (el.get_attribute("name") or "").lower()
                        if el.is_visible() and (
                                typ in ("text", "date") or
                                "data" in ph or "data" in idv or "data" in name or
                                "inicio" in idv or "fim" in idv
                        ):
                            visible.append(el)
                    except Exception:
                        continue

                if len(visible) >= 3:
                    # usually: keyword + start + end
                    visible[1].fill(d_start_str)
                    visible[2].fill(d_end_str)
            except Exception:
                pass

        self.page.wait_for_timeout(400)

        # ── Pesquisar ───────────────────────────────────────────────
        submitted = False
        submit_locators = [
            self.page.get_by_role("button", name="Pesquisar"),
            self.page.get_by_role("button", name="Buscar"),
            self.page.get_by_role("button", name="Filtrar"),
            self.page.locator("button[type='submit']"),
            self.page.locator("input[type='submit']"),
        ]

        for loc in submit_locators:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            try:
                self.page.keyboard.press("Enter")
                submitted = True
            except Exception:
                pass

        self._wait_idle(WAIT_NETWORK)
        self.page.wait_for_timeout(2000)

        # ── Collect tenders from XHR ────────────────────────────────
        tenders: list[dict] = []
        seen_ids: set[str] = set()

        for xhr in self._xhr_responses:
            body = xhr["body"]
            chunk = []
            if isinstance(body, dict):
                chunk = body.get("data", [])
            elif isinstance(body, list):
                chunk = body

            for t in chunk:
                ncp = (
                        t.get("numeroControlePNCP")
                        or f"{t.get('anoCompra')}-{t.get('sequencialCompra')}"
                )
                if ncp and ncp not in seen_ids:
                    seen_ids.add(ncp)
                    tenders.append(t)

        # ── Paginate through all result pages ───────────────────────
        total_pages = 1
        for xhr in self._xhr_responses:
            body = xhr["body"]
            if isinstance(body, dict) and "totalPaginas" in body:
                total_pages = max(total_pages, body["totalPaginas"])

        if total_pages > 1:
            log.info("  %d pages of results for '%s' — paginating …", total_pages, keyword)
            for pg in range(2, total_pages + 1):
                self._clear_xhr()
                next_clicked = False

                for sel in [
                    "button[aria-label='Próximo']",
                    "button[aria-label='next']",
                    f"button:has-text('{pg}')",
                    "li.page-item:last-child button",
                    "button.page-next",
                    "[class*='next'] button",
                ]:
                    try:
                        self.page.click(sel, timeout=3000)
                        next_clicked = True
                        break
                    except Exception:
                        continue

                if not next_clicked:
                    cur_url = self.page.url
                    if "pagina=" in cur_url:
                        new_url = re.sub(r"pagina=\d+", f"pagina={pg}", cur_url)
                    else:
                        sep = "&" if "?" in cur_url else "?"
                        new_url = f"{cur_url}{sep}pagina={pg}"
                    try:
                        self.page.goto(new_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
                    except Exception:
                        break

                self._wait_idle(WAIT_NETWORK)
                self.page.wait_for_timeout(1500)

                for xhr in self._xhr_responses:
                    body = xhr["body"]
                    chunk = []
                    if isinstance(body, dict):
                        chunk = body.get("data", [])
                    elif isinstance(body, list):
                        chunk = body
                    for t in chunk:
                        ncp = (
                                t.get("numeroControlePNCP")
                                or f"{t.get('anoCompra')}-{t.get('sequencialCompra')}"
                        )
                        if ncp and ncp not in seen_ids:
                            seen_ids.add(ncp)
                            tenders.append(t)

        log.info("  Total tenders collected for '%s': %d", keyword, len(tenders))
        return tenders

    # ── fetch items + resultado via direct API ────────────────────

    def get_items(self, cnpj: str, ano, seq) -> list[dict]:
        url   = f"{CONSULTA_BASE}/contratacoes/{cnpj}/{ano}/{seq}/itens"
        items: list[dict] = []
        page  = 1
        while True:
            data = self._api(url, {"pagina": page, "tamanhoPagina": ITEM_PAGE_SIZE})
            time.sleep(0.35)
            if not data:
                break
            chunk = data if isinstance(data, list) else data.get("data", [])
            if not chunk:
                break
            items.extend(chunk)
            if isinstance(data, list):
                break
            if page >= data.get("totalPaginas", 1):
                break
            page += 1
        return items

    def get_resultado(self, cnpj: str, ano, seq, item_no) -> dict | None:
        url  = (f"{CONSULTA_BASE}/contratacoes/{cnpj}/{ano}/{seq}"
                f"/itens/{item_no}/resultados")
        data = self._api(url)
        time.sleep(0.3)
        if not data:
            return None
        lst = data if isinstance(data, list) else data.get("data", [])
        return lst[0] if lst else None

    def get_tender_detail(self, cnpj: str, ano, seq) -> dict:
        data = self._api(f"{CONSULTA_BASE}/contratacoes/{cnpj}/{ano}/{seq}") or {}
        time.sleep(0.3)
        return data

    # ── cleanup ───────────────────────────────────────────────────

    def close(self):
        try:
            self.browser.close()
            self._pw_cm.__exit__(None, None, None)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main(headless: bool = True) -> None:
    import re as _re
    global re
    re = _re

    log.info("PNCP Browser Scraper  —  portal-first approach")
    log.info("Date range  : %s → %s", DATE_START, DATE_END)
    log.info("Keywords    : %d", len(KEYWORDS))
    log.info("Headless    : %s", headless)

    done_kw, all_rows = load_checkpoint()
    seen: set[str] = {
        f"{r.get('Buyer_CNPJ','')}-{r.get('Tender_ID','')}-{r.get('Item_Number','')}"
        for r in all_rows
    }

    scraper = PNCPBrowserScraper(headless=headless)

    try:
        for kw in tqdm(KEYWORDS, desc="Keywords"):
            if kw in done_kw:
                log.info("Skipping '%s' (checkpoint)", kw)
                continue

            # Step 1 — get tender list via portal browser
            tenders = scraper.search(kw)

            # Step 2 — for each tender: get full detail + all items
            for tender_raw in tqdm(tenders, desc=f"  {kw[:22]}", leave=False):
                cnpj = (tender_raw.get("orgaoEntidade", {}) or {}).get("cnpj", "")
                ano  = tender_raw.get("anoCompra", "")
                seq  = tender_raw.get("sequencialCompra", "")

                if not (cnpj and ano and seq):
                    continue

                tender = scraper.get_tender_detail(cnpj, ano, seq) or tender_raw
                items  = scraper.get_items(cnpj, ano, seq)

                if not items:
                    dup = f"{cnpj}-{cnpj}-{ano}-{seq}-"
                    if dup not in seen:
                        seen.add(dup)
                        all_rows.append(build_row(tender, {}, None, kw))
                    continue

                for item in items:
                    item_no = item.get("numeroItem", "")
                    dup_key = f"{cnpj}-{ano}-{seq}-{item_no}"
                    if dup_key in seen:
                        continue
                    seen.add(dup_key)

                    resultado = None
                    if item_no:
                        resultado = scraper.get_resultado(cnpj, ano, seq, item_no)

                    all_rows.append(build_row(tender, item, resultado, kw))

            done_kw.add(kw)
            save_checkpoint(done_kw, all_rows)
            log.info("Checkpoint saved — %d total rows", len(all_rows))

    finally:
        scraper.close()

    if not all_rows:
        log.warning("No data collected.")
        return

    # ── Build & save Excel ────────────────────────────────────────
    df = pd.DataFrame(all_rows)

    for col in ["Publication_Date", "Opening_Date", "Closing_Date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["Total_Value_BRL", "Unit_Price_BRL", "Item_Total_BRL", "Quantity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    COLS = [
        "Tender_ID",      "Buying_Entity",    "Buyer_CNPJ",
        "State_UF",       "State_Name",       "City",            "IBGE_Code",
        "Product_Description","Brand",        "Manufacturer",
        "Catalog_Code_CATMAT","Quantity",     "Unit",
        "Unit_Price_BRL", "Item_Total_BRL",
        "Supplier_Name",  "Supplier_CNPJ",    "Supplier_Brand",
        "Publication_Date","Opening_Date",    "Closing_Date",
        "Status",         "Tender_Type",      "Ata_SRP",
        "Total_Value_BRL","Tender_Object",
        "Amparo_Legal_Code","Amparo_Legal_Desc",
        "Tender_URL",     "Item_Number",      "Matched_Keyword",
    ]
    df = df[[c for c in COLS if c in df.columns]]

    ts  = datetime.now().strftime("%Y%m%d_%H%M")
    out = Path(f"pncp_browser_results_{ts}.xlsx")

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="IVD_Items", index=False)
        (
            df.groupby("State_UF", dropna=False)
              .agg(Unique_Tenders=("Tender_ID","nunique"),
                   Item_Rows=("Item_Number","count"),
                   Total_Value_BRL=("Total_Value_BRL","sum"))
              .reset_index()
              .sort_values("Total_Value_BRL", ascending=False)
              .to_excel(writer, sheet_name="By_State", index=False)
        )
        pd.DataFrame([
            {"Keyword": kw,
             "Row_Count": (df["Matched_Keyword"]==kw).sum(),
             "Unique_Tenders": df.loc[df["Matched_Keyword"]==kw,"Tender_ID"].nunique()}
            for kw in KEYWORDS
        ]).to_excel(writer, sheet_name="By_Keyword", index=False)

        for ws in writer.sheets.values():
            for col_cells in ws.columns:
                w = max((len(str(c.value or "")) for c in col_cells), default=8)
                ws.column_dimensions[col_cells[0].column_letter].width = min(w+2,60)

    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()

    log.info("Saved %d rows → %s", len(df), out.resolve())
    print(f"\n✓  Done!  {len(df):,} rows  →  {out.resolve()}")
    print(f"   Unique tenders : {df['Tender_ID'].nunique():,}")
    print(f"   States covered : {df['State_UF'].nunique()}")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--visible", action="store_true",
                        help="Show browser window (disable headless)")
    args = parser.parse_args()
    main(headless=not args.visible)