#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    import pandas as pd_types


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


pd = importlib.import_module("pandas")
requests = importlib.import_module("requests")

latam_defaults = importlib.import_module("latam_spec_defaults")
TranslationConfig = getattr(latam_defaults, "TranslationConfig")
add_standard_colab_args = getattr(latam_defaults, "add_standard_colab_args")
build_query_text = getattr(latam_defaults, "build_query_text")
build_run_keywords = getattr(latam_defaults, "build_run_keywords")
build_run_output_stem = getattr(latam_defaults, "build_run_output_stem")
ensure_spec_folder_layout = getattr(latam_defaults, "ensure_spec_folder_layout")
resolve_date_range = getattr(latam_defaults, "resolve_date_range")
resolve_output_base_dir = getattr(latam_defaults, "resolve_output_base_dir")
save_spec_outputs = getattr(latam_defaults, "save_spec_outputs")
translate_dataframe_to_english = getattr(latam_defaults, "translate_dataframe_to_english")

mdt_schema = importlib.import_module("mdt_schema")
to_mdt_schema = getattr(mdt_schema, "to_mdt_schema")

mdt_export = importlib.import_module("mdt_export")
save_mdt_outputs = getattr(mdt_export, "save_mdt_outputs")

logger = logging.getLogger("gebiz_scraper")

try:
    selenium_webdriver = importlib.import_module("selenium.webdriver")
    selenium_by = importlib.import_module("selenium.webdriver.common.by")
    selenium_options = importlib.import_module("selenium.webdriver.chrome.options")
    selenium_service = importlib.import_module("selenium.webdriver.chrome.service")
    selenium_wait = importlib.import_module("selenium.webdriver.support.ui")
    selenium_ec = importlib.import_module("selenium.webdriver.support.expected_conditions")
    selenium_exceptions = importlib.import_module("selenium.common.exceptions")

    webdriver = getattr(selenium_webdriver, "Chrome")
    By = getattr(selenium_by, "By")
    Options = getattr(selenium_options, "Options")
    Service = getattr(selenium_service, "Service")
    WebDriverWait = getattr(selenium_wait, "WebDriverWait")
    EC = getattr(selenium_ec, "expected_conditions", selenium_ec)
    TimeoutException = getattr(selenium_exceptions, "TimeoutException")
    WebDriverException = getattr(selenium_exceptions, "WebDriverException")
except Exception:
    webdriver = None
    By = None
    Options = None
    Service = None
    WebDriverWait = None
    EC = None
    TimeoutException = Exception
    WebDriverException = Exception


NORMALIZED_COLUMNS: List[str] = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "title",
    "description",
    "buyer",
    "classification",
    "currency",
    "amount",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]


def _strip_tags(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _parse_gebiz_datetime_to_date(value: str) -> str:
    text = _strip_tags(value)
    if not text:
        return ""
    for fmt in ["%d %b %Y %I:%M %p", "%d %b %Y %I:%M%p"]:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            continue
    return ""


def parse_bolisting_html(html: str) -> List[Dict[str, str]]:
    text = str(html or "")
    anchor_re = re.compile(
        r'href="(?P<href>/ptn/opportunity/directlink\.xhtml\?docCode=(?P<code>[^&\"]+)[^\"]*)"[^>]*>(?P<title>[^<]+)</a>',
        flags=re.IGNORECASE,
    )
    matches = list(anchor_re.finditer(text))
    rows: List[Dict[str, str]] = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(text), start + 20000)
        block = text[start:end]

        code = str(match.group("code") or "").strip()
        href = str(match.group("href") or "").strip()
        title = _strip_tags(match.group("title") or "")

        def extract(label: str) -> str:
            m = re.search(
                rf"<span>\s*{re.escape(label)}\s*</span>.*?formOutputText_VALUE-DIV[^>]*>(.*?)</div>",
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            return _strip_tags(m.group(1)) if m else ""

        buyer = extract("Agency")
        published_raw = extract("Published")
        publication_date = _parse_gebiz_datetime_to_date(published_raw)
        classification = extract("Procurement Category")

        if not code:
            continue

        rows.append(
            {
                "notice_id": code,
                "notice_url": f"https://www.gebiz.gov.sg{href}",
                "title": title,
                "buyer": buyer,
                "publication_date": publication_date,
                "classification": classification,
            }
        )
    return rows


def fetch_bolisting_requests(*, query_text: str, years: Sequence[int]) -> "pd_types.DataFrame":
    url = "https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml?origin=menu"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    rows = parse_bolisting_html(response.text)

    tokens = [t.lower() for t in re.split(r"\s+", str(query_text or "").strip()) if t]
    if tokens:
        rows = [row for row in rows if any(t in str(row.get("title", "")).lower() for t in tokens)]

    allowed_years = {int(y) for y in years if str(y).isdigit() or isinstance(y, int)}
    if allowed_years:
        filtered: List[Dict[str, str]] = []
        for row in rows:
            pub = str(row.get("publication_date", ""))
            year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else None
            if year is None or year in allowed_years:
                filtered.append(row)
        rows = filtered

    return _rows_to_normalized_df(rows=rows, query_text=query_text)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(part or "").strip() for part in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _merge_rows_by_notice_id(existing: List[Dict[str, str]], new_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = {str(row.get("notice_id", "")).strip() for row in existing}
    for row in new_rows:
        notice_id = str(row.get("notice_id", "")).strip()
        if not notice_id or notice_id in seen:
            continue
        existing.append(row)
        seen.add(notice_id)
    return existing


def _driver_page_html(driver) -> str:
    try:
        return str(driver.page_source or "")
    except Exception:
        return ""


def _wait_for_dom_ready(driver, timeout_seconds: int) -> None:
    try:
        WebDriverWait(driver, timeout_seconds).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
    except Exception:
        pass


def _find_first_displayed(driver, css_selector: str):
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
    except Exception:
        return None
    for element in elements:
        try:
            if element.is_displayed():
                return element
        except Exception:
            continue
    return None


def _get_current_page_number(driver) -> str:
    selectors = [
        ".ui-paginator-page.ui-state-active",
        ".ui-paginator-page.ui-state-highlight",
        ".ui-state-active",
        "[aria-current='page']",
        ".p-paginator-page.p-highlight",
    ]
    for selector in selectors:
        try:
            element = _find_first_displayed(driver, selector)
            if element is None:
                continue
            text = (element.text or "").strip()
            if text.isdigit():
                return text
        except Exception:
            pass
    return ""


def _scroll_to_bottom(driver) -> None:
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
    except Exception:
        pass


def _debug_paginator(driver) -> None:
    selectors = [
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV *",
        ".ui-paginator-page",
        ".p-paginator-page",
        "a[href='#']",
        "button",
    ]
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            total = len(elements)
            logger.info("Paginator debug selector=%s count=%s", selector, total)
            for i, item in enumerate(elements[:30]):
                try:
                    txt = (item.text or "").strip()
                except Exception:
                    txt = ""
                try:
                    cls = item.get_attribute("class") or ""
                except Exception:
                    cls = ""
                if txt:
                    logger.info("  [%s] text=%r class=%r", i, txt, cls)
        except Exception:
            pass


def _click_element(driver, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    except Exception:
        pass

    try:
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def _click_page_number(driver, target_page: int, timeout_seconds: int = 15) -> bool:
    target_text = str(target_page)
    _scroll_to_bottom(driver)

    selectors = [
        ".ui-paginator-page",
        ".p-paginator-page",
        "a",
        "button",
        "span",
    ]

    before_active = _get_current_page_number(driver)
    before_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

    scoped_selectors = [
        f".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[id$='_First_{target_page}']",
        f".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[id*='_First_{target_page}']",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[onclick]",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input",
    ]

    for selector in scoped_selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                item_id = item.get_attribute("id") or ""
            except Exception:
                item_id = ""
            try:
                item_name = item.get_attribute("name") or ""
            except Exception:
                item_name = ""
            try:
                item_value = (item.get_attribute("value") or "").strip()
            except Exception:
                item_value = ""
            try:
                item_onclick = item.get_attribute("onclick") or ""
            except Exception:
                item_onclick = ""
            try:
                item_class = (item.get_attribute("class") or "").lower()
            except Exception:
                item_class = ""

            matches_target = (
                item_value == target_text
                or item_id.endswith(f"_First_{target_page}")
                or f"_First_{target_page}" in item_id
                or item_name.endswith(f"_First_{target_page}")
                or f"_First_{target_page}" in item_name
                or re.search(rf"(?:^|[^0-9]){re.escape(target_text)}(?:[^0-9]|$)", item_onclick) is not None
            )
            if not matches_target:
                continue
            if "disabled" in item_class:
                continue

            logger.info(
                "Clicking paginator input id=%r name=%r value=%r onclick=%r",
                item_id,
                item_name,
                item_value,
                item_onclick[:200],
            )

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", item)
            except Exception:
                pass

            clicked = _click_element(driver, item)
            if not clicked and item_onclick:
                try:
                    driver.execute_script(item_onclick)
                    clicked = True
                except Exception:
                    clicked = False
            if not clicked:
                continue

            time.sleep(3)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(2)

            after_active = _get_current_page_number(driver)
            after_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()
            if after_active == target_text:
                return True
            if before_active != after_active and after_active:
                return True
            if before_html_sig != after_html_sig:
                return True

    input_selectors = [
        f"input[id$='_First_{target_page}']",
        f"input[id*='_First_{target_page}']",
        "input[onclick]",
        "input[type='submit']",
        "input[type='button']",
    ]

    for selector in input_selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                item_id = item.get_attribute("id") or ""
            except Exception:
                item_id = ""
            try:
                item_value = (item.get_attribute("value") or "").strip()
            except Exception:
                item_value = ""
            try:
                item_onclick = item.get_attribute("onclick") or ""
            except Exception:
                item_onclick = ""
            try:
                item_class = (item.get_attribute("class") or "").lower()
            except Exception:
                item_class = ""

            matches_target = (
                item_value == target_text
                or item_id.endswith(f"_First_{target_page}")
                or f"_First_{target_page}" in item_id
                or re.search(rf"\b{re.escape(target_text)}\b", item_onclick) is not None
            )
            if not matches_target:
                continue
            if "disabled" in item_class:
                continue

            if not _click_element(driver, item):
                continue

            time.sleep(3)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(2)

            after_active = _get_current_page_number(driver)
            after_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()
            if after_active == target_text:
                return True
            if before_active != after_active and after_active:
                return True
            if before_html_sig != after_html_sig:
                return True

    for selector in selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                text = (item.text or "").strip()
            except Exception:
                text = ""
            if text != target_text:
                continue

            try:
                cls = (item.get_attribute("class") or "").lower()
            except Exception:
                cls = ""
            if "disabled" in cls:
                continue

            if not _click_element(driver, item):
                continue

            time.sleep(3)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(2)

            after_active = _get_current_page_number(driver)
            after_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

            if after_active == target_text:
                return True
            if before_active != after_active and after_active:
                return True
            if before_html_sig != after_html_sig:
                return True

    return False


def _click_next_page(driver, current_loop_page: int, timeout_seconds: int = 15) -> bool:
    next_selectors = [
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[id*='Next']",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[title='Next']",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[onclick]",
        ".ui-paginator-next",
        ".p-paginator-next",
        "a[aria-label='Next Page']",
        "button[aria-label='Next Page']",
        "a[title='Next']",
        "button[title='Next']",
    ]

    for selector in next_selectors:
        try:
            next_btn = _find_first_displayed(driver, selector)
            if next_btn is None:
                continue

            cls = (next_btn.get_attribute("class") or "").lower()
            aria_disabled = (next_btn.get_attribute("aria-disabled") or "").lower()
            title = (next_btn.get_attribute("title") or "").lower()
            value = (next_btn.get_attribute("value") or "").lower()
            onclick = (next_btn.get_attribute("onclick") or "").lower()
            if selector.endswith("input[onclick]") and "next" not in title and "next" not in value and "next" not in onclick:
                continue
            if "disabled" in cls or aria_disabled == "true":
                break

            _scroll_to_bottom(driver)
            before_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

            if not _click_element(driver, next_btn):
                continue

            time.sleep(3)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(2)

            after_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()
            if before_html_sig != after_html_sig:
                return True
        except Exception:
            continue

    return _click_page_number(driver, current_loop_page + 1, timeout_seconds=timeout_seconds)


def _apply_query_if_present(driver, query_text: str) -> None:
    q = str(query_text or "").strip()
    if not q:
        return

    input_selectors = [
        "input[type='text']",
        "input[placeholder*='Search']",
        "input[placeholder*='search']",
    ]
    for selector in input_selectors:
        try:
            element = _find_first_displayed(driver, selector)
            if element is None:
                continue
            element.clear()
            element.send_keys(q)
            element.submit()
            time.sleep(4)
            return
        except Exception:
            continue


def _build_chrome_driver(*, headless: bool, timeout_seconds: int):
    if webdriver is None:
        raise RuntimeError("Selenium is not installed. Run: pip install selenium webdriver-manager")

    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1600,2200")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        webdriver_manager = importlib.import_module("webdriver_manager.chrome")
        ChromeDriverManager = getattr(webdriver_manager, "ChromeDriverManager")
        service = Service(ChromeDriverManager().install())
        driver = webdriver(service=service, options=chrome_options)
    except Exception:
        driver = webdriver(options=chrome_options)

    driver.set_page_load_timeout(timeout_seconds)
    return driver


def _rows_to_normalized_df(*, rows: List[Dict[str, str]], query_text: str) -> "pd_types.DataFrame":
    scraped_at_utc = _utc_now_iso()
    out_rows: List[Dict[str, str]] = []
    for row in rows:
        notice_id = str(row.get("notice_id", "")).strip()
        notice_url = str(row.get("notice_url", "")).strip()
        title = str(row.get("title", "")).strip()
        buyer = str(row.get("buyer", "")).strip()
        publication_date = str(row.get("publication_date", "")).strip()
        classification = str(row.get("classification", "")).strip()
        out_rows.append(
            {
                "source": "SG_GEBIZ",
                "country": "Singapore",
                "country_code": "SG",
                "publication_date": publication_date,
                "title": title,
                "description": "",
                "buyer": buyer,
                "classification": classification,
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("SG_GEBIZ", notice_id, notice_url),
            }
        )

    if not out_rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(out_rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def fetch_bolisting_selenium(
    *,
    query_text: str,
    years: Sequence[int],
    max_pages: int = 100,
    timeout_seconds: int = 30,
    headless: bool = True,
    save_debug_pages: bool = False,
    output_target: str = "",
    region: str = "EMEA",
    website_id: str = "SG_GEBIZ",
) -> "pd_types.DataFrame":
    url = "https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml?origin=menu"
    all_rows: List[Dict[str, str]] = []
    debug_dir: Optional[Path] = None

    if save_debug_pages:
        base_dir = resolve_output_base_dir(
            output_target=output_target,
            region=region,
            website_id=website_id,
        )
        layout = ensure_spec_folder_layout(base_dir)
        debug_dir = Path(layout["web"]) / "pagination_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

    driver = _build_chrome_driver(headless=headless, timeout_seconds=timeout_seconds)
    try:
        logger.info("Opening BOListing page: %s", url)
        driver.get(url)
        _wait_for_dom_ready(driver, timeout_seconds)
        time.sleep(4)

        _apply_query_if_present(driver, query_text)

        _scroll_to_bottom(driver)
        _debug_paginator(driver)

        page_num = 1
        seen_page_signatures = set()

        while page_num <= max_pages:
            html = _driver_page_html(driver)

            if debug_dir is not None:
                (debug_dir / f"page_{page_num:03d}.html").write_text(html, encoding="utf-8")

            page_rows = parse_bolisting_html(html)
            before_count = len(all_rows)
            all_rows = _merge_rows_by_notice_id(all_rows, page_rows)
            added_count = len(all_rows) - before_count

            current_page_label = _get_current_page_number(driver)
            logger.info(
                "Parsed page loop=%s paginator_label=%s rows_on_page=%s newly_added=%s total=%s",
                page_num,
                current_page_label or "?",
                len(page_rows),
                added_count,
                len(all_rows),
            )

            signature = hashlib.sha1(html[:50000].encode("utf-8")).hexdigest()
            if signature in seen_page_signatures:
                logger.info("Detected repeated page content. Stopping pagination.")
                break
            seen_page_signatures.add(signature)

            _scroll_to_bottom(driver)
            current_page_label = _get_current_page_number(driver)
            logger.info("Current paginator page label before move: %s", current_page_label or "?")

            target_next_page = page_num + 1
            moved = _click_page_number(
                driver,
                target_page=target_next_page,
                timeout_seconds=timeout_seconds,
            )

            if not moved:
                logger.info("Could not click page number %s. Trying next-button fallback.", target_next_page)
                moved = _click_next_page(
                    driver,
                    current_loop_page=page_num,
                    timeout_seconds=timeout_seconds,
                )

            if not moved:
                logger.info("No next page available. Pagination finished.")
                break

            time.sleep(4)
            page_num += 1
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    tokens = [t.lower() for t in re.split(r"\s+", str(query_text or "").strip()) if t]
    if tokens:
        all_rows = [row for row in all_rows if any(t in str(row.get("title", "")).lower() for t in tokens)]

    allowed_years = {int(y) for y in years if str(y).isdigit() or isinstance(y, int)}
    if allowed_years:
        filtered: List[Dict[str, str]] = []
        for row in all_rows:
            pub = str(row.get("publication_date", ""))
            year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else None
            if year is None or year in allowed_years:
                filtered.append(row)
        all_rows = filtered

    return _rows_to_normalized_df(rows=all_rows, query_text=query_text)


def build_placeholder_normalized_df(*, query_text: str) -> "pd_types.DataFrame":
    scraped_at_utc = _utc_now_iso()
    notice_id = "GEBIZ_PLACEHOLDER"
    notice_url = ""
    title = "GeBIZ scaffold placeholder"
    description = "Not implemented: SG_GEBIZ fetch/normalize pipeline is scaffolded only."

    row = {
        "source": "SG_GEBIZ",
        "country": "Singapore",
        "country_code": "SG",
        "publication_date": "",
        "title": title,
        "description": description,
        "buyer": "",
        "classification": "",
        "currency": "",
        "amount": "",
        "notice_id": notice_id,
        "notice_url": notice_url,
        "query_text": str(query_text or "").strip(),
        "scraped_at_utc": scraped_at_utc,
        "dedup_key": _stable_dedup_key("SG_GEBIZ", notice_id, str(query_text or "").strip()),
    }
    return pd.DataFrame([row]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Selenium scraper for Singapore GeBIZ (SG_GEBIZ)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword search.")
    parser.add_argument("--output-target", default="", help="Google Drive URL or local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Open the page and write discovery artifacts, then exit.")
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum BOListing pages to paginate.")
    parser.add_argument("--headful", action="store_true", help="Run Selenium with visible browser for debugging.")
    parser.add_argument("--save-debug-pages", action="store_true", help="Save paginated listing HTML pages into the web output folder.")
    parser.add_argument("--use-requests-fallback", action="store_true", help="Use old first-page-only requests fetch instead of Selenium pagination.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs (PROJECT_NAME_YEAR).")
    parser.add_argument("--website-id", default="SG_GEBIZ", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Singapore GeBIZ", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")
    add_standard_colab_args(parser, default_country="SG")
    return parser.parse_args(list(argv) if argv is not None else None)


def discover_endpoints_selenium(
    *,
    query_text: str,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, int, str]:
    base_dir = resolve_output_base_dir(
        output_target=output_target,
        region=region,
        website_id=website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    artifact_path = web_dir / f"gebiz_discovery_{_timestamp_token()}.jsonl"

    records: List[dict] = []
    error_message = ""
    url = "https://www.gebiz.gov.sg/ptn/opportunity/BOAdvancedSearch.xhtml?origin=advanced"

    try:
        driver = _build_chrome_driver(headless=True, timeout_seconds=timeout_seconds)
        try:
            driver.get(url)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(5)

            q = str(query_text or "").strip()
            if q:
                _apply_query_if_present(driver, q)

            records.append(
                {
                    "ts_utc": _utc_now_iso(),
                    "url": driver.current_url,
                    "title": driver.title,
                    "html_preview": _driver_page_html(driver)[:1000],
                }
            )
        finally:
            driver.quit()
    except Exception as exc:
        error_message = f"selenium_error: {exc}"

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("w", encoding="utf-8") as handle:
        header = {
            "ts_utc": _utc_now_iso(),
            "source": "SG_GEBIZ",
            "query_text": str(query_text or ""),
            "record_count": len(records),
            "error": error_message,
        }
        handle.write(json.dumps({"type": "summary", **header}, ensure_ascii=True) + "\n")
        for record in records:
            handle.write(json.dumps({"type": "response", **record}, ensure_ascii=True) + "\n")

    return str(artifact_path), len(records), error_message


def fetch_records_requests(*, endpoint_hint: str = "") -> "pd_types.DataFrame":
    _ = endpoint_hint
    return pd.DataFrame([])


def run(args: argparse.Namespace) -> Dict[str, object]:
    date_from, date_to, normalized_years = resolve_date_range(
        date_from=args.date_from,
        date_to=args.date_to,
        years=args.years,
    )
    query_text = build_query_text(args.query, args.keywords)
    keywords = build_run_keywords(keywords=args.keywords, query_text=query_text)

    discover_summary: Dict[str, object] = {}
    if bool(getattr(args, "discover_only", False)):
        artifact_path, record_count, error = discover_endpoints_selenium(
            query_text=query_text,
            output_target=args.output_target,
            region=args.region,
            website_id=args.website_id,
        )
        discover_summary = {
            "artifact_path": artifact_path,
            "record_count": record_count,
            "error": error,
        }

    normalized_df = pd.DataFrame()
    if not bool(getattr(args, "discover_only", False)):
        try:
            if bool(getattr(args, "use_requests_fallback", False)):
                normalized_df = fetch_bolisting_requests(
                    query_text=query_text,
                    years=normalized_years,
                )
            else:
                normalized_df = fetch_bolisting_selenium(
                    query_text=query_text,
                    years=normalized_years,
                    max_pages=args.max_pages,
                    timeout_seconds=30,
                    headless=not bool(args.headful),
                    save_debug_pages=bool(args.save_debug_pages),
                    output_target=args.output_target,
                    region=args.region,
                    website_id=args.website_id,
                )
        except Exception as exc:
            logger.warning("GeBIZ BOListing fetch failed: %s", exc)
            normalized_df = pd.DataFrame()

    if normalized_df is None or len(getattr(normalized_df, "index", [])) == 0:
        normalized_df = build_placeholder_normalized_df(query_text=query_text)

    normalized_df = normalized_df.copy()
    normalized_df["date_from"] = date_from
    normalized_df["date_to"] = date_to

    translated_df = translate_dataframe_to_english(
        normalized_df,
        TranslationConfig(
            enabled=bool(args.enable_google_translation),
            project_id=args.google_project_id,
            target_language=args.translation_target_language,
            columns=args.translate_columns,
        ),
        only_when_missing=not args.translate_all,
    )

    spec_summary = save_spec_outputs(
        translated_df,
        output_target=args.output_target,
        region=args.region,
        website_id=args.website_id,
        source_label=args.source_label,
        project_name=args.project_name,
        years=normalized_years,
        keywords=keywords,
        deduplicate_results=not args.disable_deduplication,
    )

    base_dir = resolve_output_base_dir(
        output_target=args.output_target,
        region=args.region,
        website_id=args.website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    run_stem = build_run_output_stem(
        project_name=args.project_name,
        years=list(normalized_years),
        keywords=list(keywords),
    )

    mdt_df = to_mdt_schema(translated_df)
    mdt_prefix = Path(layout["tender_data_tool"]) / run_stem
    mdt_paths = save_mdt_outputs(mdt_df, mdt_prefix)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "query_text": query_text,
        "keywords": keywords,
        "normalized_rows": len(translated_df),
        "discover": discover_summary,
        "spec": spec_summary,
        "mdt": mdt_paths,
    }


def main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args(argv)
    result = run(args)

    spec = result.get("spec")
    if not isinstance(spec, dict):
        spec = {}
    mdt = result.get("mdt")
    if not isinstance(mdt, dict):
        mdt = {}
    logger.info(
        "Dedup before/after: %s -> %s (removed=%s)",
        spec.get("dedup_before"),
        spec.get("dedup_after"),
        spec.get("dedup_removed"),
    )
    logger.info("Run output: %s", spec.get("run_csv"))
    logger.info("Consolidated output: %s", spec.get("consolidated_csv"))
    logger.info("MDT CSV: %s", mdt.get("csv_path"))

    discover = result.get("discover")
    if isinstance(discover, dict) and discover.get("artifact_path"):
        logger.info("Discovery artifact: %s", discover.get("artifact_path"))


if __name__ == "__main__":
    main()
