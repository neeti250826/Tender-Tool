# src/scrape_step3.py
"""
Step 3 scraper for Compras MX (SPA) - robust version (with dialog pagination).

ENHANCED FOR OVERNIGHT RUNS / FLAKY NETWORK
=========================================
This version adds:
1) Hard network/DNS resilience:
   - Retries with exponential backoff + jitter for navigation/reload errors
   - Detects net::ERR_NAME_NOT_RESOLVED and other transient errors
   - Rebuilds page/context/browser on repeated failures (fresh DNS / fresh session)

2) Resume support:
   - --resume: skip URLs already present in existing JSONL (ok or not; configurable)
   - --resume-ok-only: only skip URLs where ok=true in JSONL
   - Useful for restarting after crash or network issues.

3) Periodic "fresh start":
   - --restart-every N (default 50): closes and recreates context/page to avoid SPA memory leaks

4) Better diagnostics:
   - Records attempt count in payload
   - Adds short "error_kind" classification for easier triage

Outputs remain the same:
- output/raw_jsonl/step3_<label>.jsonl
- output/step3_<label>_flat.csv
- output/step3_contracts_<label>.csv
- output/step3_dialog_items_<label>.csv
"""

import argparse
import hashlib
import json
import logging
import time
import re
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from time import perf_counter

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


# -----------------------------
# Timing helper
# -----------------------------
class PhaseTimer:
    def __init__(self, label: str):
        self.label = label
        self.t0 = perf_counter()

    def done(self, extra: str = ""):
        dt = perf_counter() - self.t0
        msg = f"[TIMING] {self.label}: {dt:.2f}s"
        if extra:
            msg += f" | {extra}"
        print(msg)
        return dt


# -----------------------------
# Defaults / selectors
# -----------------------------
DEFAULT_SHEET = "New Tenders"
DEFAULT_URL_COL = "Dirección del anuncio"
DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_RESTART_EVERY = 50
DEFAULT_FAST_WAIT_MS = 35_000
DEFAULT_SKIP_EXISTING = True
DEFAULT_OVERWRITE_EXISTING = False
DEFAULT_REBUILD_OUTPUTS = False

BASE_BOOTSTRAP = "https://comprasmx.buengobierno.gob.mx/sitiopublico/"

TABLE_SEL = "table[role='table']"
CONTRACT_CELL_SEL = "td.p-link2"
CONTRACT_TABLE_SEL = f"{TABLE_SEL}:has({CONTRACT_CELL_SEL})"

DIALOG_SEL = "div[role='dialog']"
DIALOG_CLOSE_SEL = (
    f"{DIALOG_SEL} button.p-dialog-header-close, "
    f"{DIALOG_SEL} button:has-text('Cerrar'), "
    f"{DIALOG_SEL} button:has-text('Close')"
)

# PrimeNG hidden columns
H_TH = "thead tr th:not(.ocultar):not(.oculto-impresion)"
H_TD = "tbody tr td:not(.ocultar):not(.oculto-impresion)"

# PrimeNG paginator
PAGINATOR_SEL = ".p-paginator"
PAG_NEXT_SEL = "button.p-paginator-next"
PAG_FIRST_SEL = "button.p-paginator-first"
PAG_RPP_DROPDOWN_SEL = ".p-paginator-rpp-options"
PAG_RPP_PANEL_ITEM_SEL = "li[role='option'], .p-dropdown-item"
PAG_CURRENT_REPORT_SEL = ".p-paginator-current"
PAG_DISABLED_CLASS = "p-disabled"

_ws = re.compile(r"\s+")


# -----------------------------
# Small utils
# -----------------------------
def norm(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).replace("\u00a0", " ").strip()
    s = _ws.sub(" ", s)
    return s


def safe_text_list(texts: List[str]) -> List[str]:
    return [norm(t) for t in texts if norm(t)]


def money_to_float(s: Any) -> Optional[float]:
    s = norm(s)
    if not s:
        return None
    s = s.replace(",", "").replace("$", "")
    s2 = re.sub(r"[^\d\.\-]", "", s)
    try:
        return float(s2) if s2 else None
    except ValueError:
        return None


def num_to_float(s: Any) -> Optional[float]:
    s = norm(s).replace(",", "")
    if not s:
        return None
    s2 = re.sub(r"[^\d\.\-]", "", s)
    try:
        return float(s2) if s2 else None
    except ValueError:
        return None


def is_disabled(locator) -> bool:
    try:
        if locator.count() == 0:
            return True
        disabled_attr = locator.get_attribute("disabled")
        if disabled_attr is not None:
            return True
        cls = locator.get_attribute("class") or ""
        return PAG_DISABLED_CLASS in cls.split()
    except Exception:
        return False


def classify_error(e: Exception) -> str:
    """
    Coarse buckets for flaky overnight runs.
    """
    msg = str(e) or ""
    msg_l = msg.lower()

    if isinstance(e, PWTimeout):
        return "timeout"

    # Playwright wraps many as generic Exception with message containing net::...
    if "err_name_not_resolved" in msg_l:
        return "dns"
    if "err_internet_disconnected" in msg_l:
        return "offline"
    if "err_connection_closed" in msg_l or "err_connection_reset" in msg_l:
        return "conn_reset"
    if "err_connection_timed_out" in msg_l or "timed out" in msg_l:
        return "conn_timeout"
    if "err_too_many_redirects" in msg_l:
        return "redirects"
    if "navigation" in msg_l and "failed" in msg_l:
        return "nav_failed"

    return "other"


def backoff_sleep(attempt: int, base: float = 3.0, cap: float = 90.0) -> None:
    """
    Exponential backoff with jitter.
    attempt is 1-based.
    """
    exp = min(cap, base * (2 ** (attempt - 1)))
    jitter = random.uniform(0.0, exp * 0.25)
    time.sleep(exp + jitter)


def _to_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in {"1", "true", "yes", "y", "on"}:
            return True
        if v in {"0", "false", "no", "n", "off"}:
            return False
    return default


def load_config(path: str) -> Dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise SystemExit(f"Config file not found: {cfg_path}")
    try:
        import yaml
    except Exception:
        raise SystemExit("PyYAML is required for --config. Install with: pip install pyyaml")

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit("Config must be a YAML mapping (key: value pairs).")
    return data


def url_to_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def store_path_for_url(store_dir: Path, url: str) -> Path:
    return store_dir / f"{url_to_key(url)}.json"


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def load_store_payloads(store_dir: Path) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    if not store_dir.exists():
        return payloads
    for p in sorted(store_dir.glob("*.json")):
        try:
            payloads.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return payloads


def load_store_ok_keys(store_dir: Path) -> Set[str]:
    ok_keys: Set[str] = set()
    if not store_dir.exists():
        return ok_keys
    for p in store_dir.glob("*.json"):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            if payload.get("ok") is True:
                ok_keys.add(p.stem)
        except Exception:
            continue
    return ok_keys


class _WorkerFilter(logging.Filter):
    def __init__(self, worker_tag: str):
        super().__init__()
        self.worker_tag = worker_tag

    def filter(self, record: logging.LogRecord) -> bool:
        record.worker = self.worker_tag
        return True


def setup_logger(log_path: Path, worker_tag: str, to_console: bool = True) -> logging.Logger:
    logger = logging.getLogger(f"step3_{worker_tag}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = "%(asctime)s [%(worker)s] %(levelname)s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
    worker_filter = _WorkerFilter(worker_tag)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(worker_filter)
    logger.addHandler(file_handler)

    if to_console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(worker_filter)
        logger.addHandler(stream_handler)

    return logger


def install_print_tee(log_path: Path, prefix: str):
    import builtins

    log_file = log_path.open("a", encoding="utf-8")
    orig_print = builtins.print

    def _print(*args, **kwargs):
        sep = kwargs.get("sep", " ")
        msg = sep.join(str(a) for a in args)
        orig_print(prefix + msg)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file.write(f"{ts} {prefix}{msg}\n")
        log_file.flush()

    builtins.print = _print
    return orig_print, log_file


# -----------------------------
# Pagination helpers
# -----------------------------
def parse_paginator_total(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\bde\s+(\d+)\b|\bof\s+(\d+)\b", text)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


# -----------------------------
# SPA bootstrap + readiness
# -----------------------------
def bootstrap_spa(page) -> None:
    page.goto(BASE_BOOTSTRAP, wait_until="domcontentloaded", timeout=240_000)
    page.locator("app-root").first.wait_for(state="attached", timeout=90_000)
    page.wait_for_timeout(1200)


def auto_scroll(page, max_steps: int = 18, step_px: int = 1100) -> None:
    last_height = 0
    stable = 0
    for _ in range(max_steps):
        height = page.evaluate("() => document.body.scrollHeight")
        stable = stable + 1 if height == last_height else 0
        last_height = height

        page.evaluate("(y) => window.scrollBy(0, y)", step_px)
        page.wait_for_timeout(250)
        page.wait_for_timeout(250)

        if stable >= 2:
            break

    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(200)


EXPEDIENTE_PAT = re.compile(r"\bE-\d{4}-\d{5,}\b", re.IGNORECASE)


def find_expediente_code(text: Any) -> str:
    text = norm(text)
    if not text:
        return ""
    m = EXPEDIENTE_PAT.search(text)
    return m.group(0).upper() if m else ""


def _expediente_label_candidates(page):
    return page.locator(
        "label.font-bold, label, span.font-bold, span, div.font-bold, strong"
    ).filter(
        has_text=re.compile(r"(c[oó]digo\s+del\s+expediente|expediente)", re.IGNORECASE)
    )


def read_expediente_value(page) -> str:
    try:
        lbl = page.locator("label.font-bold:has-text('Código del expediente')").first
        if lbl.count() == 0:
            return ""

        container = lbl.locator(
            "xpath=ancestor::div[contains(@class,'col-') or contains(@class,'p-col-')][1]"
        )
        if container.count() == 0:
            container = lbl.locator("xpath=ancestor::div[1]")

        vals = container.locator("span, label").all_inner_texts()
        vals = [norm(v) for v in vals if norm(v)]
        vals = [v for v in vals if "Código del expediente" not in v]
        return vals[-1] if vals else ""
    except Exception:
        return ""


def read_expediente_value(page) -> str:
    try:
        labels = _expediente_label_candidates(page)
        n = labels.count()
        for i in range(n):
            lbl = labels.nth(i)
            container = lbl.locator(
                "xpath=ancestor::div[contains(@class,'col-') or contains(@class,'p-col-')][1]"
            )
            if container.count() == 0:
                container = lbl.locator("xpath=ancestor::div[1]")

            vals = container.locator("span, label, div, strong").all_inner_texts()
            vals = [norm(v) for v in vals if norm(v)]
            vals = [
                v for v in vals
                if not re.search(r"(c[oÃ³]digo\s+del\s+expediente|expediente)", v, re.IGNORECASE)
            ]
            for value in reversed(vals):
                exp = find_expediente_code(value)
                if exp:
                    return exp

        body_text = page.locator("body").inner_text(timeout=2_000)
        return find_expediente_code(body_text)
    except Exception:
        return ""


def url_route_key(url: str) -> str:
    u = url or ""
    if "#/" not in u:
        return ""
    frag = u.split("#/", 1)[1]
    m = re.search(r"/detalle/([^/]+)/", frag)
    return m.group(1) if m else frag


def wait_for_route_hash(page, target_url: str, timeout_ms: int = 60_000) -> None:
    key = url_route_key(target_url)
    if not key:
        return

    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        cur = page.url or ""
        if key in cur:
            return
        page.wait_for_timeout(200)

    raise PWTimeout(f"Route did not update to include key='{key}'. cur_url='{page.url}'")


def wait_for_real_content(page, prev_expediente: str = "", timeout_ms: int = 120_000) -> str:
    lbl = page.locator("label.font-bold:has-text('Código del expediente')").first
    lbl.wait_for(state="visible", timeout=timeout_ms)

    deadline = time.time() + timeout_ms / 1000.0
    last_seen = ""

    while time.time() < deadline:
        exp = read_expediente_value(page)
        if exp:
            last_seen = exp
            if prev_expediente:
                if exp != prev_expediente:
                    return exp
            else:
                return exp
        page.wait_for_timeout(250)

    raise PWTimeout(
        f"Expediente not ready/unique within timeout. prev='{prev_expediente}' last_seen='{last_seen}'"
    )


def wait_for_real_content(page, prev_expediente: str = "", timeout_ms: int = 120_000) -> str:
    deadline = time.time() + timeout_ms / 1000.0
    last_seen = ""
    saw_page_content = False

    while time.time() < deadline:
        if not saw_page_content:
            try:
                titles = safe_text_list(page.locator("h1.tituloHome").all_inner_texts())
                saw_page_content = bool(titles) or page.locator(TABLE_SEL).count() > 0
            except Exception:
                pass

        exp = read_expediente_value(page)
        if exp:
            last_seen = exp
            if prev_expediente:
                if exp != prev_expediente:
                    return exp
            else:
                return exp
        page.wait_for_timeout(250)

    raise PWTimeout(
        f"Expediente not ready/unique within timeout. prev='{prev_expediente}' "
        f"last_seen='{last_seen}' saw_page_content={saw_page_content}"
    )


def _label_candidates(page, pattern: str):
    return page.locator(
        "label.font-bold, label, span.font-bold, span, div.font-bold, strong"
    ).filter(has_text=re.compile(pattern, re.IGNORECASE))


def _container_texts_for_label(label_locator) -> List[str]:
    container = label_locator.locator(
        "xpath=ancestor::div[contains(@class,'col-') or contains(@class,'p-col-')][1]"
    )
    if container.count() == 0:
        container = label_locator.locator("xpath=ancestor::div[1]")

    vals = container.locator("span, label, div, strong").all_inner_texts()
    return [norm(v) for v in vals if norm(v)]


def read_labeled_value(page, label_pattern: str, exclude_pattern: Optional[str] = None) -> str:
    try:
        labels = _label_candidates(page, label_pattern)
        n = labels.count()
        for i in range(n):
            vals = _container_texts_for_label(labels.nth(i))
            out: List[str] = []
            for value in vals:
                if exclude_pattern and re.search(exclude_pattern, value, re.IGNORECASE):
                    continue
                out.append(value)
            if out:
                return out[-1]
    except Exception:
        return ""
    return ""


def read_expediente_value(page) -> str:
    try:
        labels = _label_candidates(page, r"(c[oÃ³]digo\s+del\s+expediente|expediente)")
        n = labels.count()
        for i in range(n):
            vals = _container_texts_for_label(labels.nth(i))
            vals = [
                v for v in vals
                if not re.search(r"(c[oÃ³]digo\s+del\s+expediente|expediente)", v, re.IGNORECASE)
            ]
            for value in reversed(vals):
                exp = find_expediente_code(value)
                if exp:
                    return exp

        body_text = page.locator("body").inner_text(timeout=2_000)
        return find_expediente_code(body_text)
    except Exception:
        return ""


def read_procedure_number(page) -> str:
    return norm(
        read_labeled_value(
            page,
            r"n[uÃº]mero\s+de\s+procedimiento\s+de\s+contrataci[oÃ³]n",
            exclude_pattern=r"n[uÃº]mero\s+de\s+procedimiento\s+de\s+contrataci[oÃ³]n",
        )
    )


def read_page_identity(page) -> Tuple[str, str]:
    exp = read_expediente_value(page)
    if exp:
        return "expediente", exp

    proc = read_procedure_number(page)
    if proc:
        return "procedure", proc

    try:
        titles = safe_text_list(page.locator("h1.tituloHome").all_inner_texts())
        if titles:
            return "title", " | ".join(titles)
    except Exception:
        pass

    return "", ""


def wait_for_real_content(page, prev_expediente: str = "", timeout_ms: int = 120_000) -> str:
    deadline = time.time() + timeout_ms / 1000.0
    last_seen = ""
    last_kind = ""
    saw_page_content = False

    while time.time() < deadline:
        if not saw_page_content:
            try:
                titles = safe_text_list(page.locator("h1.tituloHome").all_inner_texts())
                saw_page_content = bool(titles) or page.locator(TABLE_SEL).count() > 0
            except Exception:
                pass

        kind, identity = read_page_identity(page)
        if identity:
            last_kind = kind
            last_seen = identity
            if kind == "expediente":
                if prev_expediente:
                    if identity != prev_expediente:
                        return identity
                else:
                    return identity
            elif saw_page_content:
                return f"{kind}:{identity}"
        page.wait_for_timeout(250)

    raise PWTimeout(
        f"Page identity not ready within timeout. prev='{prev_expediente}' "
        f"last_kind='{last_kind}' last_seen='{last_seen}' saw_page_content={saw_page_content}"
    )


def navigate_to_tender(page, url: str, prev_exp: str, fast_timeout_ms: int = 35_000) -> str:
    """
    Fast SPA navigation:
      - Prefer hash-router navigation (window.location.hash)
      - Validate route + expediente changes
      - Reload only as fallback
    """
    target_hash = url.split("#", 1)[1] if "#" in url else ""

    # Ensure we are on the right origin
    cur = page.url or ""
    if "comprasmx.buengobierno.gob.mx" not in cur:
        page.goto(BASE_BOOTSTRAP, wait_until="domcontentloaded", timeout=150_000)

    # Attempt 1: hash navigation
    if target_hash:
        page.evaluate(
            """(h) => {
                const newHash = h.startsWith('#') ? h : ('#' + h);
                if (window.location.hash !== newHash) {
                  window.location.hash = newHash;
                  window.dispatchEvent(new HashChangeEvent('hashchange'));
                }
            }""",
            target_hash,
        )
    else:
        page.goto(url, wait_until="domcontentloaded", timeout=150_000)

    wait_for_route_hash(page, url, timeout_ms=30_000)

    # Short wait for new content on fast path
    try:
        return wait_for_real_content(page, prev_expediente=prev_exp, timeout_ms=fast_timeout_ms)
    except PWTimeout:
        # Attempt 2: reload (hard refresh) fallback
        page.reload(wait_until="domcontentloaded", timeout=150_000)
        wait_for_route_hash(page, url, timeout_ms=60_000)
        return wait_for_real_content(page, prev_expediente=prev_exp, timeout_ms=120_000)


# -----------------------------
# Main page extraction
# -----------------------------
def extract_kv_fields(page) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    titles = safe_text_list(page.locator("h1.tituloHome").all_inner_texts())
    if titles:
        data["page_titles"] = titles

    bold_labels = page.locator("label.font-bold")
    n = bold_labels.count()

    for i in range(n):
        lbl = bold_labels.nth(i)
        key = norm(lbl.inner_text())
        if not key:
            continue
        key2 = key[:-1].strip() if key.endswith(":") else key.strip()

        container = lbl.locator(
            "xpath=ancestor::div[contains(@class,'col-') or contains(@class,'p-col-')][1]"
        )
        if container.count() == 0:
            container = lbl.locator("xpath=ancestor::div[1]")

        vals = container.locator("span, label").all_inner_texts()
        vals = [norm(v) for v in vals if norm(v)]
        vals = [v for v in vals if v != key and v != key2]
        if not vals:
            continue

        value = vals[-1]
        if key2 in data:
            if isinstance(data[key2], list):
                data[key2].append(value)
            else:
                data[key2] = [data[key2], value]
        else:
            data[key2] = value

    return data


def extract_html_table(table_locator) -> Dict[str, Any]:
    try:
        table_locator.scroll_into_view_if_needed()
    except Exception:
        pass

    headers = safe_text_list(table_locator.locator(H_TH).all_inner_texts())

    try:
        table_locator.locator("tbody").first.wait_for(state="attached", timeout=20_000)
    except Exception:
        return {"headers": headers, "rows": [], "row_count": 0}

    # Wait for tbody to populate (best-effort)
    for _ in range(20):
        bt = norm(table_locator.locator("tbody").inner_text())
        if bt:
            break
        time.sleep(0.25)

    rows_data = table_locator.evaluate(
        """
        (table) => {
          const isHidden = (el) =>
            el.classList.contains("ocultar") || el.classList.contains("oculto-impresion");
          const rows = Array.from(table.querySelectorAll("tbody tr"));
          return rows.map(tr => {
            const tds = Array.from(tr.querySelectorAll("td")).filter(td => !isHidden(td));
            return tds.map(td => (td.innerText || "").trim());
          });
        }
        """
    )

    rows: List[Dict[str, str]] = []
    for values in rows_data:
        values = [v.replace("\\u00a0", " ").strip() for v in values]

        if headers:
            row = {h: (values[i] if i < len(values) else "") for i, h in enumerate(headers)}
            if len(values) > len(headers):
                row["_extra_values"] = values[len(headers):]
        else:
            if len(values) == 1:
                row = {"value": values[0]}
            else:
                row = {f"col_{i+1}": v for i, v in enumerate(values)}

        rows.append(row)

    return {"headers": headers, "rows": rows, "row_count": len(rows)}


def extract_all_tables(page, max_tables: int = 0) -> List[Dict[str, Any]]:
    tables = page.locator(TABLE_SEL)
    out: List[Dict[str, Any]] = []
    total = tables.count()
    limit = total if max_tables <= 0 else min(total, max_tables)
    for i in range(limit):
        t = tables.nth(i)
        try:
            t.scroll_into_view_if_needed()
            t.wait_for(state="visible", timeout=5_000)
        except Exception:
            continue

        ctx = ""
        try:
            ctx = norm(
                t.locator(
                    "xpath=preceding::div[contains(@class,'titulo-seccion')][1] | "
                    "xpath=preceding::h1[contains(@class,'tituloHome')][1]"
                ).first.inner_text()
            )
        except Exception:
            ctx = ""

        out.append({"index": i, "context": ctx, "table": extract_html_table(t)})

    return out


def find_contracts_table(page):
    return page.locator(CONTRACT_TABLE_SEL).first


# -----------------------------
# Dialog handling + pagination
# -----------------------------
def wait_dialog_painted(page, timeout_ms: int = 45_000) -> None:
    deadline = time.time() + timeout_ms / 1000.0
    dlg = page.locator(DIALOG_SEL).first
    while time.time() < deadline:
        if dlg.count() == 0:
            page.wait_for_timeout(200)
            continue
        if dlg.locator(TABLE_SEL).count() > 0:
            return
        if len(norm(dlg.inner_text())) > 120:
            return
        page.wait_for_timeout(250)


def open_dialog_for_contract_cell(page, cell_locator) -> None:
    cell_locator.scroll_into_view_if_needed()
    cell_locator.click()
    page.locator(DIALOG_SEL).first.wait_for(state="visible", timeout=30_000)
    wait_dialog_painted(page)


def close_dialog(page) -> None:
    btn = page.locator(DIALOG_CLOSE_SEL).first
    if btn.count() > 0:
        btn.click()
    else:
        page.keyboard.press("Escape")
    try:
        page.locator(DIALOG_SEL).first.wait_for(state="hidden", timeout=12_000)
    except Exception:
        pass


def dialog_set_rows_per_page_max(dialog) -> None:
    try:
        rpp = dialog.locator(PAG_RPP_DROPDOWN_SEL).first
        if rpp.count() == 0:
            return

        rpp.scroll_into_view_if_needed()
        rpp.click()
        dialog.page.wait_for_timeout(300)

        opts = dialog.page.locator(PAG_RPP_PANEL_ITEM_SEL)
        if opts.count() == 0:
            dialog.page.keyboard.press("Escape")
            return

        best_text = None
        best_val = -1
        for i in range(opts.count()):
            t = norm(opts.nth(i).inner_text())
            m = re.search(r"(\d+)", t)
            if not m:
                continue
            v = int(m.group(1))
            if v > best_val:
                best_val = v
                best_text = t

        if best_text is None:
            dialog.page.keyboard.press("Escape")
            return

        opts.filter(has_text=best_text).first.click()
        dialog.page.wait_for_timeout(500)
    except Exception:
        try:
            dialog.page.keyboard.press("Escape")
        except Exception:
            pass


def table_fingerprint_first_row(table_locator) -> str:
    try:
        r0 = table_locator.locator("tbody tr").first
        if r0.count() == 0:
            return ""
        return norm(r0.inner_text())
    except Exception:
        return ""


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for r in rows:
        key = json.dumps(r, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def extract_dialog_tables_with_pagination(page) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    dlg = page.locator(DIALOG_SEL).first
    dialog_set_rows_per_page_max(dlg)

    tables = dlg.locator(TABLE_SEL)
    dialog_tables: List[Dict[str, Any]] = []
    dialog_items: List[Dict[str, Any]] = []

    def get_paginator_text_fast() -> str:
        try:
            loc = dlg.locator(PAG_CURRENT_REPORT_SEL).first
            if loc.count() == 0:
                return ""
            return norm(loc.inner_text(timeout=500))
        except Exception:
            return ""

    for ti in range(tables.count()):
        t = tables.nth(ti)
        try:
            t.scroll_into_view_if_needed()
            t.wait_for(state="visible", timeout=10_000)
        except Exception:
            pass

        paginator = dlg.locator(PAGINATOR_SEL).first
        next_btn = dlg.locator(PAG_NEXT_SEL).first

        had_pagination = paginator.count() > 0
        can_advance = next_btn.count() > 0 and not is_disabled(next_btn)

        paginator_text = ""
        expected_total_rows = None
        if had_pagination:
            paginator_text = get_paginator_text_fast()
            expected_total_rows = parse_paginator_total(paginator_text) if paginator_text else None

        rows_all: List[Dict[str, Any]] = []
        pages_visited = 0

        def capture_current_page():
            tbl = extract_html_table(t)
            rows_all.extend(tbl["rows"])

        capture_current_page()
        pages_visited += 1

        if can_advance:
            safety = 0
            while next_btn.count() > 0 and not is_disabled(next_btn) and safety < 200:
                safety += 1
                fp_before = table_fingerprint_first_row(t)

                next_btn.click()

                deadline = time.time() + 20.0
                while time.time() < deadline:
                    fp_after = table_fingerprint_first_row(t)
                    if fp_after and fp_after != fp_before:
                        break
                    page.wait_for_timeout(200)

                page.wait_for_timeout(250)
                capture_current_page()
                pages_visited += 1

            try:
                first_btn = dlg.locator(PAG_FIRST_SEL).first
                if first_btn.count() > 0 and not is_disabled(first_btn):
                    first_btn.click()
                    page.wait_for_timeout(250)
            except Exception:
                pass

        rows_all = dedupe_rows(rows_all)

        tbl_final = extract_html_table(t)
        headers = tbl_final["headers"]

        if headers:
            rows_normed: List[Dict[str, Any]] = []
            for r in rows_all:
                rr = {h: r.get(h, "") for h in headers}
                for k, v in r.items():
                    if k not in rr:
                        rr[k] = v
                rows_normed.append(rr)
            rows_all = rows_normed

        extracted_count = len(rows_all)

        pagination_warning = None
        if expected_total_rows is not None and expected_total_rows != extracted_count:
            pagination_warning = f"Paginator expected {expected_total_rows} rows, but extracted {extracted_count}"
            print(
                f"WARNING [dialog_table_index={ti}]: {pagination_warning} | paginator_text='{paginator_text}'"
            )

        table_payload = {"headers": headers, "rows": rows_all, "row_count": extracted_count}

        dialog_tables.append(
            {
                "dialog_table_index": ti,
                "table": table_payload,
                "had_pagination": had_pagination,
                "pages_visited": pages_visited,
                "paginator_text": paginator_text,
                "expected_total_rows": expected_total_rows,
                "pagination_warning": pagination_warning,
            }
        )

        for r in rows_all:
            dialog_items.append({"dialog_table_index": ti, "row": r})

    return dialog_tables, dialog_items


# -----------------------------
# Result types
# -----------------------------
@dataclass
class ScrapeResult:
    url: str
    ok: bool
    error: Optional[str]
    error_kind: Optional[str]
    attempts: int
    page_kv: Dict[str, Any]
    all_tables: List[Dict[str, Any]]
    contracts: List[Dict[str, Any]]


# -----------------------------
# Core scrape per URL
# -----------------------------
def scrape_one(
    page,
    url: str,
    fast_timeout_ms: int = 35_000,
    max_tables: int = 0,
    extract_all: bool = True,
) -> ScrapeResult:
    """
    One attempt (no retry loop here). Retry is handled by scrape_one_with_retries.
    """
    print(f"\n--- SCRAPING --- {url}")
    t_total = PhaseTimer("TOTAL")

    t = PhaseTimer("read prev expediente")
    prev_exp = read_expediente_value(page)
    t.done(f"prev_exp='{prev_exp}'")

    t = PhaseTimer("navigate_to_tender")
    new_exp = navigate_to_tender(page, url, prev_exp, fast_timeout_ms=fast_timeout_ms)
    t.done(f"new_exp='{new_exp}'")

    t = PhaseTimer("auto_scroll")
    auto_scroll(page, max_steps=18, step_px=1100)
    t.done()

    t = PhaseTimer("extract_kv + all_tables")
    page_kv = extract_kv_fields(page)
    if new_exp and page_kv.get("Código del expediente") and page_kv["Código del expediente"] != new_exp:
        print(f"[WARN] mismatch: wait saw '{new_exp}', but kv extracted '{page_kv['Código del expediente']}'")
    if extract_all:
        all_tables = extract_all_tables(page, max_tables=max_tables)
        t.done(f"tables={len(all_tables)}")
    else:
        all_tables = []
        t.done("tables=0 (skipped)")

    contracts_out: List[Dict[str, Any]] = []
    contract_table = find_contracts_table(page)

    if contract_table.count() > 0:
        t_contracts = PhaseTimer("contracts_total")

        contract_table.scroll_into_view_if_needed()
        contract_table.wait_for(state="visible", timeout=30_000)

        contract_rows = extract_html_table(contract_table)["rows"]
        contract_trs = contract_table.locator("tbody tr")
        tr_count = contract_trs.count()

        for idx in range(tr_count):
            t_c = PhaseTimer(f"contract[{idx}]")

            tr = contract_trs.nth(idx)
            cell = tr.locator(CONTRACT_CELL_SEL).first
            if cell.count() == 0:
                t_c.done("no clickable cell")
                continue

            contract_number_clicked = norm(cell.inner_text())
            contract_row = contract_rows[idx] if idx < len(contract_rows) else {}

            t = PhaseTimer(f"contract[{idx}] open_dialog")
            open_dialog_for_contract_cell(page, cell)
            t.done()

            t = PhaseTimer(f"contract[{idx}] extract_dialog")
            dialog_tables, dialog_items = extract_dialog_tables_with_pagination(page)
            t.done(f"tables={len(dialog_tables)} items={len(dialog_items)}")

            close_dialog(page)
            page.wait_for_timeout(150)

            contracts_out.append(
                {
                    "contract_index": idx,
                    "contract_number_clicked": contract_number_clicked,
                    "contract_row": contract_row,
                    "dialog_tables": dialog_tables,
                    "dialog_items_count": len(dialog_items),
                    "dialog_items": dialog_items,
                }
            )

            t_c.done(f"items={len(dialog_items)}")

        t_contracts.done(f"contracts={len(contracts_out)}")

    t_total.done()

    return ScrapeResult(
        url=url,
        ok=True,
        error=None,
        error_kind=None,
        attempts=1,
        page_kv=page_kv,
        all_tables=all_tables,
        contracts=contracts_out,
    )


def _new_context_page(browser, block_resources: bool, block_service_workers: bool):
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900},
        service_workers="block" if block_service_workers else "allow",
    )
    if block_resources:
        _setup_resource_blocking(ctx)
    page = ctx.new_page()
    page.set_default_timeout(120_000)
    return ctx, page


def rebuild_context(browser, block_resources: bool, block_service_workers: bool):
    """
    Close & recreate context/page to recover from broken state / DNS / SPA memory leaks.
    """
    ctx, page = _new_context_page(browser, block_resources, block_service_workers)
    bootstrap_spa(page)
    return ctx, page


def scrape_one_with_retries(
    browser,
    ctx,
    page,
    url: str,
    max_attempts: int = 6,
    rebuild_on_attempt: int = 3,
    fast_timeout_ms: int = 35_000,
    block_resources: bool = False,
    block_service_workers: bool = False,
    max_tables: int = 0,
    extract_all: bool = True,
) -> Tuple[ScrapeResult, Any, Any, bool]:
    """
    Returns (result, ctx, page, did_rebuild)
    """
    last_err: Optional[Exception] = None
    did_rebuild = False

    for attempt in range(1, max_attempts + 1):
        try:
            res = scrape_one(
                page,
                url,
                fast_timeout_ms=fast_timeout_ms,
                max_tables=max_tables,
                extract_all=extract_all,
            )
            res.attempts = attempt
            return res, ctx, page, did_rebuild

        except Exception as e:
            last_err = e
            kind = classify_error(e)
            print(f"[ERROR] attempt={attempt}/{max_attempts} kind={kind} {type(e).__name__}: {e}")

            # Rebuild context/page if:
            # - we hit repeated attempts, or
            # - strong network/DNS indicators, or
            # - playwright page got into bad state
            if kind in {"dns", "offline", "conn_reset", "nav_failed"} or attempt >= rebuild_on_attempt:
                try:
                    try:
                        # Best effort close current context
                        ctx.close()
                    except Exception:
                        pass
                    ctx, page = rebuild_context(
                        browser,
                        block_resources=block_resources,
                        block_service_workers=block_service_workers,
                    )
                    did_rebuild = True
                except Exception as rebuild_err:
                    print(f"[WARN] rebuild failed: {type(rebuild_err).__name__}: {rebuild_err}")

            # Sleep before next attempt (unless last attempt)
            if attempt < max_attempts:
                backoff_sleep(attempt, base=3.0, cap=90.0)

    # If we are here: all attempts failed
    err_kind = classify_error(last_err) if last_err else "other"
    return (
        ScrapeResult(
            url=url,
            ok=False,
            error=f"{type(last_err).__name__}: {last_err}" if last_err else "Unknown error",
            error_kind=err_kind,
            attempts=max_attempts,
            page_kv={},
            all_tables=[],
            contracts=[],
        ),
        ctx,
        page,
        did_rebuild,
    )


# -----------------------------
# CSV flattening / normalization
# -----------------------------
def flatten_for_csv(payload: Dict[str, Any]) -> Dict[str, Any]:
    kv = payload.get("page_kv") or {}
    contracts = payload.get("contracts") or []
    dialog_items_count = sum(int(c.get("dialog_items_count", 0)) for c in contracts)

    titles_val = kv.get("page_titles", [])
    if isinstance(titles_val, list):
        titles_str = " | ".join([norm(x) for x in titles_val if norm(x)])
    else:
        titles_str = norm(titles_val)

    return {
        "URL": payload.get("url"),
        "ok": payload.get("ok"),
        "error_kind": payload.get("error_kind"),
        "attempts": payload.get("attempts"),
        "error": payload.get("error"),
        "page_titles": titles_str,
        "Código del expediente": kv.get("Código del expediente"),
        "Número de procedimiento de contratación": kv.get("Número de procedimiento de contratación"),
        "Estatus del procedimiento de contratación": kv.get("Estatus del procedimiento de contratación"),
        "contracts_count": len(contracts),
        "dialog_items_count": dialog_items_count,
        "all_tables_count": len(payload.get("all_tables") or []),
    }


def normalize_contract_csv_rows(res: ScrapeResult) -> List[Dict[str, Any]]:
    base = {
        "URL": res.url,
        "Código del expediente": res.page_kv.get("Código del expediente"),
        "Número de procedimiento de contratación": res.page_kv.get("Número de procedimiento de contratación"),
        "Estatus del procedimiento de contratación": res.page_kv.get("Estatus del procedimiento de contratación"),
        "Tipo de procedimiento de contratación": res.page_kv.get("Tipo de procedimiento de contratación"),
        "Dependencia o Entidad": res.page_kv.get("Dependencia o Entidad"),
        "Unidad compradora": res.page_kv.get("Unidad compradora"),
    }
    rows: List[Dict[str, Any]] = []
    for c in res.contracts:
        cr = c.get("contract_row") or {}
        rows.append(
            {
                **base,
                "contract_index": c.get("contract_index"),
                "Número de contrato": cr.get("Número de contrato") or c.get("contract_number_clicked"),
                "Licitante": cr.get("Licitante"),
                "Titulo contrato": cr.get("Titulo contrato") or cr.get("Título contrato"),
                "Estatus contrato": cr.get("Estatus contrato"),
                "Fecha inicio": cr.get("Fecha inicio"),
                "Fecha fin": cr.get("Fecha fin"),
                "Importe total sin impuestos": cr.get("Importe total sin impuestos"),
                "Importe total sin impuestos (num)": money_to_float(cr.get("Importe total sin impuestos")),
                "Moneda": cr.get("Moneda"),
                "dialog_items_count": c.get("dialog_items_count", 0),
            }
        )
    return rows


def normalize_dialog_items_csv_rows(res: ScrapeResult) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for c in res.contracts:
        cr = c.get("contract_row") or {}
        contract_number = cr.get("Número de contrato") or c.get("contract_number_clicked")

        for item in c.get("dialog_items") or []:
            r = item.get("row") or {}
            out = {
                "URL": res.url,
                "contract_index": c.get("contract_index"),
                "Número de contrato": contract_number,
                "Licitante": cr.get("Licitante"),
                "dialog_table_index": item.get("dialog_table_index"),
            }
            for k, v in r.items():
                out[f"col__{k}"] = v

            out["Cantidad solicitada (num)"] = num_to_float(r.get("Cantidad solicitada"))
            out["Precio unitario sin impuestos (num)"] = money_to_float(r.get("Precio unitario sin impuestos"))
            out["Subtotal (num)"] = money_to_float(r.get("Subtotal"))
            out["IVA (num)"] = money_to_float(r.get("IVA"))
            out["Otros impuestos (num)"] = money_to_float(r.get("Otros impuestos"))
            out["Total (num)"] = money_to_float(r.get("Total"))

            rows.append(out)
    return rows


# -----------------------------
# Resume helpers
# -----------------------------
def load_done_urls(jsonl_path: Path, ok_only: bool) -> Set[str]:
    done: Set[str] = set()
    if not jsonl_path.exists():
        return done

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                u = obj.get("url")
                if not u:
                    continue
                if ok_only:
                    if obj.get("ok") is True:
                        done.add(u)
                else:
                    done.add(u)
            except Exception:
                continue
    return done


# -----------------------------
# Worker / parallel helpers
# -----------------------------
def _split_round_robin(urls: List[str], n: int) -> List[List[str]]:
    buckets: List[List[str]] = [[] for _ in range(n)]
    for i, u in enumerate(urls):
        buckets[i % n].append(u)
    return buckets


def _merge_jsonl_parts(final_path: Path, part_paths: List[Path], append: bool) -> None:
    mode = "a" if append else "w"
    with final_path.open(mode, encoding="utf-8") as out:
        for pp in part_paths:
            if not pp.exists():
                continue
            with pp.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    out.write(line + "\n")


def _setup_resource_blocking(ctx) -> None:
    def handler(route, request):
        rtype = request.resource_type
        url = request.url.lower()
        if rtype in {"image", "media", "font"}:
            return route.abort()
        if any(x in url for x in ["google-analytics", "googletagmanager", "doubleclick", "facebook"]):
            return route.abort()
        return route.continue_()

    ctx.route("**/*", handler)


def _worker_run(
    worker_id: int,
    urls: List[str],
    args_dict: Dict[str, Any],
    outdir: str,
    run_label: str,
) -> Dict[str, Any]:
    import builtins

    logs_dir = Path(args_dict["log_dir"])
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"step3_{run_label}__{args_dict['run_id']}__w{worker_id}.log"
    prefix = f"[W{worker_id}] "
    orig_print = None
    log_file = None
    try:
        orig_print, log_file = install_print_tee(log_path, prefix)
    except Exception:
        orig_print = builtins.print

    outdir_path = Path(outdir)
    (outdir_path / "raw_jsonl").mkdir(parents=True, exist_ok=True)
    store_dir = Path(args_dict["store_dir"])
    store_dir.mkdir(parents=True, exist_ok=True)

    jsonl_part_path = outdir_path / "raw_jsonl" / f"step3_{run_label}__part{worker_id}.jsonl"

    flat_rows: List[Dict[str, Any]] = []
    contract_rows_all: List[Dict[str, Any]] = []
    item_rows_all: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=args_dict["headless"])
            ctx, page = _new_context_page(
                browser,
                block_resources=args_dict.get("block_resources", False),
                block_service_workers=args_dict.get("block_service_workers", False),
            )

            if args_dict.get("log_xhr"):
                def _on_response(resp):
                    try:
                        req = resp.request
                        if req.resource_type not in {"xhr", "fetch"}:
                            return
                        url = resp.url
                        if "comprasmx" not in url:
                            return
                        ctype = (resp.headers or {}).get("content-type", "")
                        print(f"[XHR] {resp.status} {url}")
                        if "application/json" in ctype:
                            try:
                                body = resp.json()
                                if isinstance(body, dict):
                                    keys = list(body.keys())[:12]
                                    print(f"[XHR] json keys: {keys}")
                                elif isinstance(body, list):
                                    print(f"[XHR] json list len: {len(body)}")
                            except Exception:
                                pass
                    except Exception:
                        pass

                page.on("response", _on_response)

            bootstrap_spa(page)

            with jsonl_part_path.open("w", encoding="utf-8") as f:
                processed = 0
                for i, url in enumerate(urls, start=1):
                    if args_dict.get("skip_existing") and not args_dict.get("overwrite_existing"):
                        sp = store_path_for_url(store_dir, url)
                        if sp.exists():
                            try:
                                payload = json.loads(sp.read_text(encoding="utf-8"))
                                if payload.get("ok") is True:
                                    print(f"[{i}/{len(urls)}] SKIP (stored ok) {url}")
                                    continue
                            except Exception:
                                pass
                    print(f"[{i}/{len(urls)}] {url}")

                    if (
                        args_dict["restart_every"]
                        and args_dict["restart_every"] > 0
                        and processed > 0
                        and (processed % args_dict["restart_every"] == 0)
                    ):
                        print(f"[INFO] periodic restart at processed={processed}")
                        try:
                            ctx.close()
                        except Exception:
                            pass
                        ctx, page = _new_context_page(
                            browser,
                            block_resources=args_dict.get("block_resources", False),
                            block_service_workers=args_dict.get("block_service_workers", False),
                        )
                        bootstrap_spa(page)

                    res, ctx, page, _ = scrape_one_with_retries(
                        browser=browser,
                        ctx=ctx,
                        page=page,
                        url=url,
                        max_attempts=args_dict["max_attempts"],
                        rebuild_on_attempt=3,
                        fast_timeout_ms=args_dict["fast_wait_ms"],
                        block_resources=args_dict.get("block_resources", False),
                        block_service_workers=args_dict.get("block_service_workers", False),
                        max_tables=args_dict.get("max_tables", 0),
                        extract_all=not args_dict.get("no_all_tables", False),
                    )

                    payload = {
                        "url": res.url,
                        "ok": res.ok,
                        "attempts": res.attempts,
                        "error_kind": res.error_kind,
                        "error": res.error,
                        "page_kv": res.page_kv,
                        "all_tables": res.all_tables,
                        "contracts": res.contracts,
                    }

                    try:
                        write_json_atomic(store_path_for_url(store_dir, res.url), payload)
                    except Exception as e:
                        print(f"[WARN] store write failed: {type(e).__name__}: {e}")

                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    f.flush()

                    flat_rows.append(flatten_for_csv(payload))

                    if res.ok:
                        contract_rows_all.extend(normalize_contract_csv_rows(res))
                        item_rows_all.extend(normalize_dialog_items_csv_rows(res))

                    processed += 1
                    page.wait_for_timeout(250)

            try:
                ctx.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
    finally:
        builtins.print = orig_print
        try:
            log_file.close()
        except Exception:
            pass

    return {
        "flat_rows": flat_rows,
        "contract_rows": contract_rows_all,
        "item_rows": item_rows_all,
        "jsonl_part": str(jsonl_part_path),
    }


# -----------------------------
# Main runner
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="", help="Path to YAML config file with defaults")
    ap.add_argument("--url", default=None, help="Single URL to scrape (test mode). If set, excel args are optional.")
    ap.add_argument("--excel", default=None, help="Path to Excel file, e.g. data/Tender List.xlsx")
    ap.add_argument("--sheet", default=None, help=f"Sheet name (default: {DEFAULT_SHEET})")
    ap.add_argument("--url-col", default=None, help=f"URL column (default: {DEFAULT_URL_COL})")
    ap.add_argument("--limit", type=int, default=None, help="Limit number of URLs for batch mode (0 = no limit)")
    ap.add_argument("--headless", action="store_true", default=None, help="Run headless (default is headful)")
    ap.add_argument("--outdir", default=None, help="Output directory")
    ap.add_argument(
        "--log-xhr",
        action="store_true",
        default=None,
        help="Log XHR/fetch responses to discover underlying API endpoints",
    )
    ap.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: 1)")
    ap.add_argument(
        "--block-resources",
        action="store_true",
        default=None,
        help="Block images/fonts/media/analytics to speed up SPA loads",
    )
    ap.add_argument(
        "--block-service-workers",
        action="store_true",
        default=None,
        help="Block service worker registration in the browser context",
    )
    ap.add_argument(
        "--fast-wait-ms",
        type=int,
        default=None,
        help=f"Fast-path wait (ms) for expediente change before forcing reload (default: {DEFAULT_FAST_WAIT_MS})",
    )
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        default=None,
        help="Skip scraping URLs that already exist in the per-URL store with ok=true",
    )
    ap.add_argument(
        "--overwrite-existing",
        action="store_true",
        default=None,
        help="Overwrite stored data for URLs (re-scrape even if stored)",
    )
    ap.add_argument(
        "--rebuild-outputs",
        action="store_true",
        default=None,
        help="Rebuild JSONL/CSVs from the per-URL store without scraping",
    )
    ap.add_argument(
        "--no-all-tables",
        action="store_true",
        default=None,
        help="Skip extract_all_tables (faster; tables omitted from output)",
    )
    ap.add_argument(
        "--max-tables",
        type=int,
        default=None,
        help="Cap number of tables extracted (0 = no cap)",
    )

    # NEW: resilience knobs
    ap.add_argument("--max-attempts", type=int, default=None, help="Max attempts per URL on transient failures")
    ap.add_argument("--restart-every", type=int, default=None, help="Recreate context/page every N URLs (0 disables)")
    ap.add_argument("--resume", action="store_true", default=None, help="Resume from existing JSONL (skip URLs already present)")
    ap.add_argument("--resume-ok-only", action="store_true", default=None, help="With --resume: only skip URLs where ok=true")
    args = ap.parse_args()

    cfg = load_config(args.config) if args.config else {}
    if args.url is None:
        args.url = cfg.get("url", "")
    if args.excel is None:
        args.excel = cfg.get("excel", "")
    if args.sheet is None:
        args.sheet = cfg.get("sheet", DEFAULT_SHEET)
    if args.url_col is None:
        args.url_col = cfg.get("url_col", DEFAULT_URL_COL)
    if args.limit is None:
        args.limit = int(cfg.get("limit", 0))
    if args.headless is None:
        args.headless = _to_bool(cfg.get("headless"), default=False)
    if args.outdir is None:
        args.outdir = cfg.get("outdir", "output")
    if args.log_xhr is None:
        args.log_xhr = _to_bool(cfg.get("log_xhr"), default=False)
    if args.workers is None:
        args.workers = int(cfg.get("workers", 1))
    if args.block_resources is None:
        args.block_resources = _to_bool(cfg.get("block_resources"), default=False)
    if args.block_service_workers is None:
        args.block_service_workers = _to_bool(cfg.get("block_service_workers"), default=False)
    if args.fast_wait_ms is None:
        args.fast_wait_ms = int(cfg.get("fast_wait_ms", DEFAULT_FAST_WAIT_MS))
    if args.max_attempts is None:
        args.max_attempts = int(cfg.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
    if args.restart_every is None:
        args.restart_every = int(cfg.get("restart_every", DEFAULT_RESTART_EVERY))
    if args.resume is None:
        args.resume = _to_bool(cfg.get("resume"), default=False)
    if args.resume_ok_only is None:
        args.resume_ok_only = _to_bool(cfg.get("resume_ok_only"), default=False)
    if args.skip_existing is None:
        args.skip_existing = _to_bool(cfg.get("skip_existing"), default=DEFAULT_SKIP_EXISTING)
    if args.overwrite_existing is None:
        args.overwrite_existing = _to_bool(cfg.get("overwrite_existing"), default=DEFAULT_OVERWRITE_EXISTING)
    if args.rebuild_outputs is None:
        args.rebuild_outputs = _to_bool(cfg.get("rebuild_outputs"), default=DEFAULT_REBUILD_OUTPUTS)
    if args.no_all_tables is None:
        args.no_all_tables = _to_bool(cfg.get("no_all_tables"), default=False)
    if args.max_tables is None:
        args.max_tables = int(cfg.get("max_tables", 0))

    if args.overwrite_existing:
        args.skip_existing = False

    outdir = Path(args.outdir)
    (outdir / "raw_jsonl").mkdir(parents=True, exist_ok=True)

    urls: List[str] = []
    run_label = ""

    if args.url and args.url.strip():
        urls = [args.url.strip()]
        run_label = "single"
    else:
        if not args.excel:
            raise SystemExit("Provide either --url for single test mode OR --excel for batch mode.")
        excel_path = Path(args.excel)
        df = pd.read_excel(excel_path, sheet_name=args.sheet)
        if args.url_col not in df.columns:
            raise SystemExit(f"URL column '{args.url_col}' not found. Columns: {list(df.columns)}")
        urls = df[args.url_col].dropna().astype(str).tolist()
        if args.limit and args.limit > 0:
            urls = urls[: args.limit]
        run_label = args.sheet.replace(" ", "_")

    jsonl_path = outdir / "raw_jsonl" / f"step3_{run_label}.jsonl"
    flat_csv_path = outdir / f"step3_{run_label}_flat.csv"
    contracts_csv_path = outdir / f"step3_contracts_{run_label}.csv"
    items_csv_path = outdir / f"step3_dialog_items_{run_label}.csv"
    store_dir = outdir / "by_url" / run_label
    store_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = outdir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_log_path = logs_dir / f"step3_{run_label}__{run_id}.log"
    logger = setup_logger(main_log_path, worker_tag="M", to_console=True)
    logger.info("run_id=%s label=%s urls=%s workers=%s", run_id, run_label, len(urls), args.workers)
    logger.info(
        "flags: headless=%s block_resources=%s block_service_workers=%s fast_wait_ms=%s",
        args.headless,
        args.block_resources,
        args.block_service_workers,
        args.fast_wait_ms,
    )
    logger.info(
        "store: skip_existing=%s overwrite_existing=%s rebuild_outputs=%s store_dir=%s",
        args.skip_existing,
        args.overwrite_existing,
        args.rebuild_outputs,
        store_dir,
    )

    done_url_keys: Set[str] = set()
    done_urls: Set[str] = set()
    if args.skip_existing and not args.overwrite_existing:
        done_url_keys = load_store_ok_keys(store_dir)
        if done_url_keys:
            logger.info("[STORE] loaded %s ok URLs from %s", len(done_url_keys), store_dir)
        elif args.resume:
            done_urls = load_done_urls(jsonl_path, ok_only=args.resume_ok_only)
            logger.info("[RESUME] loaded %s already-scraped URLs from %s", len(done_urls), jsonl_path.name)
    elif args.resume:
        done_urls = load_done_urls(jsonl_path, ok_only=args.resume_ok_only)
        logger.info("[RESUME] loaded %s already-scraped URLs from %s", len(done_urls), jsonl_path.name)

    todo_urls = urls
    if done_url_keys:
        todo_urls = [u for u in todo_urls if url_to_key(u) not in done_url_keys]
    if done_urls:
        todo_urls = [u for u in todo_urls if u not in done_urls]

    if run_label == "single":
        args.workers = 1

    workers = max(1, int(args.workers))
    if workers > len(todo_urls) and len(todo_urls) > 0:
        workers = len(todo_urls)

    flat_rows: List[Dict[str, Any]] = []
    contract_rows_all: List[Dict[str, Any]] = []
    item_rows_all: List[Dict[str, Any]] = []

    if args.rebuild_outputs:
        todo_urls = []

    if todo_urls:
        args_dict = {
            "headless": args.headless,
            "max_attempts": args.max_attempts,
            "restart_every": args.restart_every,
            "log_xhr": args.log_xhr,
            "block_resources": args.block_resources,
            "block_service_workers": args.block_service_workers,
            "fast_wait_ms": args.fast_wait_ms,
            "skip_existing": args.skip_existing,
            "overwrite_existing": args.overwrite_existing,
            "store_dir": str(store_dir),
            "log_dir": str(logs_dir),
            "run_id": run_id,
            "max_tables": args.max_tables,
            "no_all_tables": args.no_all_tables,
        }

        if workers == 1:
            result = _worker_run(1, todo_urls, args_dict, str(outdir), run_label)
            flat_rows.extend(result["flat_rows"])
            contract_rows_all.extend(result["contract_rows"])
            item_rows_all.extend(result["item_rows"])
            part_paths = [Path(result["jsonl_part"])]
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed

            url_chunks = _split_round_robin(todo_urls, workers)
            part_paths: List[Path] = []
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futures = []
                for wid, chunk in enumerate(url_chunks, start=1):
                    if not chunk:
                        continue
                    futures.append(ex.submit(_worker_run, wid, chunk, args_dict, str(outdir), run_label))

                for fut in as_completed(futures):
                    res = fut.result()
                    flat_rows.extend(res["flat_rows"])
                    contract_rows_all.extend(res["contract_rows"])
                    item_rows_all.extend(res["item_rows"])
                    part_paths.append(Path(res["jsonl_part"]))

    elif args.rebuild_outputs:
        logger.info("[INFO] Rebuild outputs from per-URL store only.")
    else:
        logger.info("[INFO] No URLs to process after resume/store filtering.")

    # Always write outputs from the per-URL store (latest per URL).
    payloads = load_store_payloads(store_dir)
    flat_rows = [flatten_for_csv(p) for p in payloads]
    contract_rows_all = []
    item_rows_all = []
    for p in payloads:
        if p.get("ok"):
            res = ScrapeResult(
                url=p.get("url", ""),
                ok=True,
                error=p.get("error"),
                error_kind=p.get("error_kind"),
                attempts=int(p.get("attempts", 1)),
                page_kv=p.get("page_kv") or {},
                all_tables=p.get("all_tables") or [],
                contracts=p.get("contracts") or [],
            )
            contract_rows_all.extend(normalize_contract_csv_rows(res))
            item_rows_all.extend(normalize_dialog_items_csv_rows(res))

    with jsonl_path.open("w", encoding="utf-8") as f:
        for p in payloads:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    pd.DataFrame(flat_rows).to_csv(flat_csv_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(contract_rows_all).to_csv(contracts_csv_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(item_rows_all).to_csv(items_csv_path, index=False, encoding="utf-8-sig")

    logger.info("Saved:")
    logger.info("  JSONL:         %s", jsonl_path)
    logger.info("  Flat CSV:      %s", flat_csv_path)
    logger.info("  Contracts CSV: %s", contracts_csv_path)
    logger.info("  Items CSV:     %s", items_csv_path)

    if run_label == "single" and flat_rows:
        r0 = flat_rows[0]
        logger.info("=== SUMMARY (single URL) ===")
        logger.info(
            "ok: %s  contracts: %s  dialog_items: %s",
            r0.get("ok"),
            r0.get("contracts_count"),
            r0.get("dialog_items_count"),
        )
        logger.info("expediente: %s", r0.get("Código del expediente"))
        logger.info("proc: %s", r0.get("Número de procedimiento de contratación"))


if __name__ == "__main__":
    main()
