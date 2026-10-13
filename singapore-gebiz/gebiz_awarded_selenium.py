#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

pd = importlib.import_module("pandas")

logger = logging.getLogger("gebiz_scraper")

selenium_webdriver = importlib.import_module("selenium.webdriver")
selenium_by = importlib.import_module("selenium.webdriver.common.by")
selenium_options = importlib.import_module("selenium.webdriver.chrome.options")
selenium_service = importlib.import_module("selenium.webdriver.chrome.service")
selenium_wait = importlib.import_module("selenium.webdriver.support.ui")

webdriver = getattr(selenium_webdriver, "Chrome")
By = getattr(selenium_by, "By")
Options = getattr(selenium_options, "Options")
Service = getattr(selenium_service, "Service")
WebDriverWait = getattr(selenium_wait, "WebDriverWait")

NORMALIZED_COLUMNS = [
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

LISTING_URL = "https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml?origin=menu"


def _strip_tags(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_text_value(value: str) -> str:
    text = _normalize_ws(_strip_tags(value))
    if not text:
        return ""

    bad_patterns = [
        "dialogBoxCustom_HandleBrowserScrollBars",
        "javascript:",
        "function(",
        "onclick",
        "onload",
    ]
    if any(bad in text for bad in bad_patterns):
        return ""
    return text


def _parse_gebiz_datetime_to_date(value: str) -> str:
    text = _strip_tags(value)
    if not text:
        return ""
    for fmt in [
        "%d %b %Y %I:%M %p",
        "%d %b %Y %I:%M%p",
        "%d %b %Y",
        "%d %B %Y %I:%M %p",
        "%d %B %Y",
    ]:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            continue
    return ""


def _parse_any_date_to_iso(value: str) -> str:
    text = _normalize_ws(_strip_tags(value))
    if not text:
        return ""

    text = re.sub(
        r"^(closing date|closing date & time|closing/opening date|published|awarded date)\s*[:\-]?\s*",
        "",
        text,
        flags=re.I,
    ).strip()

    direct = _parse_gebiz_datetime_to_date(text)
    if direct:
        return direct

    try:
        dt = date_parser.parse(text, dayfirst=True, fuzzy=True)
        return dt.date().isoformat()
    except Exception:
        return ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(part or "").strip() for part in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _iso_to_ts(value: str):
    text = str(value or "").strip()
    if not text:
        return pd.NaT
    return pd.to_datetime(text, errors="coerce")


def _date_in_range(iso_date: str, date_from: str = "", date_to: str = "") -> bool:
    dt = _iso_to_ts(iso_date)
    if pd.isna(dt):
        return False

    if str(date_from).strip():
        start_dt = pd.to_datetime(str(date_from).strip(), errors="coerce")
        if not pd.isna(start_dt) and dt < start_dt:
            return False

    if str(date_to).strip():
        end_dt = pd.to_datetime(str(date_to).strip(), errors="coerce")
        if not pd.isna(end_dt) and dt > end_dt:
            return False

    return True


def _all_rows_older_than_date_from(rows: List[Dict[str, str]], date_from: str) -> bool:
    if not str(date_from).strip():
        return False
    if not rows:
        return False

    start_dt = pd.to_datetime(str(date_from).strip(), errors="coerce")
    if pd.isna(start_dt):
        return False

    usable_dates = []
    for row in rows:
        dt = _iso_to_ts(row.get("publication_date", ""))
        if not pd.isna(dt):
            usable_dates.append(dt)

    if not usable_dates:
        return False

    return all(dt < start_dt for dt in usable_dates)


def _build_chrome_driver(headless: bool = True, timeout_seconds: int = 30):
    chrome_options = Options()

    if headless:
        chrome_options.add_argument("--headless")

    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,3000")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-setuid-sandbox")

    chrome_options.binary_location = "/usr/bin/google-chrome"

    service = Service(log_output="/content/chromedriver.log")
    driver = webdriver(service=service, options=chrome_options)
    driver.set_page_load_timeout(timeout_seconds)
    return driver


def _wait_for_dom_ready(driver, timeout_seconds: int) -> None:
    try:
        WebDriverWait(driver, timeout_seconds).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
    except Exception:
        pass


def _driver_page_html(driver) -> str:
    try:
        return str(driver.page_source or "")
    except Exception:
        return ""


def _scroll_to_bottom(driver) -> None:
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
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


def _wait_for_html_change(driver, before_html_sig: str, timeout_seconds: int = 15) -> bool:
    end_time = time.time() + timeout_seconds
    while time.time() < end_time:
        time.sleep(1)
        _wait_for_dom_ready(driver, 3)
        after_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()
        if after_html_sig != before_html_sig:
            return True
    return False


def _text_or_value(element) -> str:
    try:
        txt = _normalize_ws(element.text)
        if txt:
            return txt
    except Exception:
        pass

    for attr in ["value", "title", "aria-label", "alt"]:
        try:
            val = _normalize_ws(element.get_attribute(attr) or "")
            if val:
                return val
        except Exception:
            pass
    return ""


def _extract_currency_from_text(value: str) -> str:
    text = _normalize_ws(_strip_tags(value))
    if not text:
        return ""

    m = re.search(r"\(([A-Z]{3})\)", text)
    if m:
        return m.group(1).upper()

    m = re.search(r"\b([A-Z]{3})\b", text)
    if m:
        return m.group(1).upper()

    return ""


def _extract_amount_from_text(value: str) -> str:
    text = _normalize_ws(_strip_tags(value))
    if not text:
        return ""

    matches = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)", text)
    if not matches:
        return ""

    return matches[-1].replace(",", "")


def _remove_currency_suffix(value: str) -> str:
    text = _normalize_ws(_strip_tags(value))
    text = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", text)
    return _normalize_ws(text)


def _click_target_by_candidates(driver, candidates, label: str, timeout_seconds: int = 20) -> bool:
    before_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

    logger.info("Found %s %s candidates", len(candidates), label)

    for idx, item in enumerate(candidates, start=1):
        try:
            txt = _text_or_value(item).upper()
            item_id = item.get_attribute("id") or ""
            item_name = item.get_attribute("name") or ""
            item_class = item.get_attribute("class") or ""
            item_value = item.get_attribute("value") or ""
            outer_html = (item.get_attribute("outerHTML") or "")[:500]
            logger.info(
                "Trying %s candidate %s text=%r id=%r name=%r class=%r value=%r html=%r",
                label,
                idx,
                txt,
                item_id,
                item_name,
                item_class,
                item_value,
                outer_html,
            )
        except Exception:
            pass

        if not _click_element(driver, item):
            continue

        time.sleep(2)
        _wait_for_dom_ready(driver, timeout_seconds)
        time.sleep(2)

        if _wait_for_html_change(driver, before_html_sig, timeout_seconds=8):
            logger.info("Successfully clicked %s", label)
            return True

    logger.warning("Could not click %s", label)
    return False


def _find_tab_candidates(driver, target_text: str, selectors: List[str]):
    target = str(target_text or "").strip().upper()
    found = []
    seen_keys = set()

    for selector in selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                text = _text_or_value(item).upper()
                if target not in text:
                    continue

                key = (
                    item.get_attribute("id") or "",
                    item.get_attribute("name") or "",
                    item.get_attribute("class") or "",
                    item.get_attribute("value") or "",
                    text,
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                found.append(item)
            except Exception:
                continue

    return found


def _click_main_status_tab(driver, status_filter: str, timeout_seconds: int = 20) -> bool:
    status = str(status_filter or "").strip().upper()

    if status == "AWARDED":
        status = "CLOSED"

    if status not in {"OPEN", "CLOSED"}:
        return False

    selectors = [
        "div[class*='formTabBar_TAB-BAR-DIV'] input",
        "div[id*='formTabBar_TAB-BAR-DIV'] input",
        "div[class*='formTabBar_TAB-BAR-DIV'] button",
        "div[id*='formTabBar_TAB-BAR-DIV'] button",
        "div[class*='formTabBar_TAB-BAR-DIV'] a",
        "div[id*='formTabBar_TAB-BAR-DIV'] a",
        "div[class*='formTabBar_TAB-BAR-DIV'] *",
        "div[id*='formTabBar_TAB-BAR-DIV'] *",
        "div[class*='formTabBar_TAB-BAR'] *",
        "div[id*='formTabBar_TAB-BAR'] *",
    ]
    candidates = _find_tab_candidates(driver, status, selectors)
    return _click_target_by_candidates(driver, candidates, f"main-{status}", timeout_seconds=timeout_seconds)


def _click_closed_subtab(driver, status_filter: str, timeout_seconds: int = 20) -> bool:
    status = str(status_filter or "").strip().upper()
    if status != "CLOSED":
        return False

    selectors = [
        "span[id='contentForm:j_idt895_commandLink-SPAN']",
        "span[id*='contentForm:j_idt895_commandLink-SPAN']",
        "span[id$='_commandLink-SPAN']",
        "span[id*='_commandLink-SPAN']",
        "a[id*='_commandLink']",
        "input",
        "button",
        "span",
        "a",
    ]
    candidates = _find_tab_candidates(driver, "CLOSED", selectors)
    return _click_target_by_candidates(driver, candidates, "inner-CLOSED", timeout_seconds=timeout_seconds)


def _click_awarded_subtab(driver, status_filter: str, timeout_seconds: int = 20) -> bool:
    status = str(status_filter or "").strip().upper()
    if status != "AWARDED":
        return False

    before_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

    exact_selectors = [
        "span#contentForm\\:j_idt899_commandLink-SPAN",
        "[id='contentForm:j_idt899_commandLink-SPAN']",
        "span[id='contentForm:j_idt899_commandLink-SPAN']",
    ]

    for selector in exact_selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            items = []

        for item in items:
            if not _click_element(driver, item):
                continue

            time.sleep(2)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(2)

            if _wait_for_html_change(driver, before_html_sig, timeout_seconds=8):
                logger.info("Successfully clicked AWARDED subtab by exact id")
                return True

    selectors = [
        "span[id$='_commandLink-SPAN']",
        "span[id*='_commandLink-SPAN']",
        "a[id*='_commandLink']",
        "input",
        "button",
        "span",
        "a",
        "div",
    ]
    candidates = _find_tab_candidates(driver, "AWARDED", selectors)
    return _click_target_by_candidates(driver, candidates, "inner-AWARDED", timeout_seconds=timeout_seconds)


def _click_award_details_tab_in_detail_page(driver, timeout_seconds: int = 20) -> bool:
    before_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

    selectors = [
        "div.formTabBar_TAB-BAR-DIV input",
        "div.formTabBar_TAB-BAR-DIV button",
        "div.formTabBar_TAB-BAR-DIV a",
        "div.formTabBar_TAB-BAR-DIV span",
        "div.formTabBar_TAB-BAR-DIV *",
        "div[id*='formTabBar_TAB-BAR-DIV'] input",
        "div[id*='formTabBar_TAB-BAR-DIV'] button",
        "div[id*='formTabBar_TAB-BAR-DIV'] a",
        "div[id*='formTabBar_TAB-BAR-DIV'] span",
        "div[id*='formTabBar_TAB-BAR-DIV'] *",
    ]

    target_texts = [
        "AWARD",
        "AWARD DETAILS",
        "AWARDED",
        "CONTRACT",
        "ITEMS AWARDED",
        "AWARD INFORMATION",
        "SUPPLIER",
    ]

    candidates = []
    seen = set()

    for selector in selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                txt = _text_or_value(item).upper()
                item_id = item.get_attribute("id") or ""
                item_class = item.get_attribute("class") or ""
                outer = (item.get_attribute("outerHTML") or "")[:500].upper()
                haystack = " ".join([txt, item_id.upper(), item_class.upper(), outer])

                if not any(t in haystack for t in target_texts):
                    continue

                key = (item_id, item_class, txt)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(item)
            except Exception:
                continue

    clicked = _click_target_by_candidates(driver, candidates, "detail-award-tab", timeout_seconds=timeout_seconds)

    time.sleep(2)
    _wait_for_dom_ready(driver, timeout_seconds)
    return clicked


def _click_page_number(driver, target_page: int, timeout_seconds: int = 15) -> bool:
    target_text = str(target_page)
    _scroll_to_bottom(driver)
    before_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

    selectors = [
        f".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[id$='_{target_page}_{target_page}']",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV a",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV button",
    ]

    for selector in selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                item_value = (item.get_attribute("value") or "").strip()
                item_text = _text_or_value(item).strip()
                item_id = item.get_attribute("id") or ""
            except Exception:
                continue

            if not (
                item_value == target_text
                or item_text == target_text
                or item_id.endswith(f"_{target_page}_{target_page}")
                or f"_{target_page}_{target_page}" in item_id
            ):
                continue

            if not _click_element(driver, item):
                continue

            time.sleep(3)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(2)

            after_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()
            if before_html_sig != after_html_sig:
                return True

    return False


def _find_next_page_number(driver, current_page: int) -> Optional[int]:
    target_page = current_page + 1
    target_text = str(target_page)

    selectors = [
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV a",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV button",
    ]

    for selector in selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                value = (item.get_attribute("value") or "").strip()
                text = _text_or_value(item).strip()
                item_id = item.get_attribute("id") or ""
                disabled = (item.get_attribute("disabled") or "").strip().lower()
                cls = (item.get_attribute("class") or "").lower()
            except Exception:
                continue

            if disabled in {"true", "disabled"}:
                continue
            if "disabled" in cls:
                continue

            if (
                value == target_text
                or text == target_text
                or item_id.endswith(f"_{target_page}_{target_page}")
                or f"_{target_page}_{target_page}" in item_id
            ):
                return target_page

    return None


def _extract_block_value(block: str, label: str) -> str:
    patterns = [
        rf"<span>\s*{re.escape(label)}\s*</span>.*?formOutputText_VALUE-DIV[^>]*>(.*?)</div>",
        rf"<label[^>]*>\s*{re.escape(label)}\s*</label>.*?(?:formOutputText_VALUE-DIV|div)[^>]*>(.*?)</div>",
        rf">{re.escape(label)}<.*?(?:formOutputText_VALUE-DIV|div)[^>]*>(.*?)</div>",
        rf"{re.escape(label)}.*?(?:formOutputText_VALUE-DIV|div)[^>]*>(.*?)</div>",
    ]
    for pattern in patterns:
        m = re.search(pattern, block, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return _normalize_ws(_strip_tags(m.group(1)))
    return ""


def _extract_listing_closing_date_bs4(block_html: str) -> str:
    soup = BeautifulSoup(block_html or "", "html.parser")

    green_nodes = soup.select(
        "div.formOutputText_HIDDEN-LABEL.outputText_DATE-GREEN, "
        "span.formOutputText_HIDDEN-LABEL.outputText_DATE-GREEN"
    )

    for node in green_nodes:
        txt = _normalize_ws(node.get_text(" ", strip=True))
        iso = _parse_any_date_to_iso(txt)
        if iso:
            return iso

    for container in soup.select("div.col-md-12"):
        container_text = _normalize_ws(container.get_text(" ", strip=True))
        if "CLOSING DATE" in container_text.upper():
            for node in container.select(
                "div.formOutputText_HIDDEN-LABEL.outputText_DATE-GREEN, "
                "span.formOutputText_HIDDEN-LABEL.outputText_DATE-GREEN, "
                "div.formOutputText_MAIN.shaded_BLUE, "
                "span.formOutputText_MAIN.shaded_BLUE"
            ):
                txt = _normalize_ws(node.get_text(" ", strip=True))
                iso = _parse_any_date_to_iso(txt)
                if iso:
                    return iso

            iso = _parse_any_date_to_iso(container_text)
            if iso:
                return iso

    for node in soup.find_all(["div", "span"]):
        classes = " ".join(node.get("class", []))
        if "outputText_DATE-GREEN" in classes:
            txt = _normalize_ws(node.get_text(" ", strip=True))
            iso = _parse_any_date_to_iso(txt)
            if iso:
                return iso

    return ""


def _extract_listing_description_bs4(block_html: str) -> str:
    soup = BeautifulSoup(block_html or "", "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates = []

    for row in soup.select("div.form2_ROW"):
        row_copy = BeautifulSoup(str(row), "html.parser")

        for tag in row_copy(["script", "style", "noscript"]):
            tag.decompose()

        txt = _normalize_ws(row_copy.get_text(" ", strip=True))
        if not txt:
            continue

        upper_txt = txt.upper()

        if any(
            bad in txt
            for bad in [
                "dialogBoxCustom_HandleBrowserScrollBars",
                "javascript:",
                "function(",
                "onclick",
                "onload",
                "{",
                "}",
            ]
        ):
            continue

        if "PUBLISHED" in upper_txt and "AGENCY" in upper_txt:
            continue
        if "PROCUREMENT CATEGORY" in upper_txt and "REFERENCE NO." in upper_txt:
            continue
        if "CLOSING DATE" in upper_txt and "PUBLISHED" in upper_txt:
            continue
        if len(txt) < 20:
            continue

        candidates.append(txt)

    if candidates:
        candidates = sorted(candidates, key=len, reverse=True)
        return candidates[0]

    return ""


def _extract_listing_awarded_amount_currency_bs4(block_html: str) -> Dict[str, str]:
    soup = BeautifulSoup(block_html or "", "html.parser")

    candidates = []
    for node in soup.select("div.formOutputText_MAIN"):
        txt = _normalize_ws(node.get_text(" ", strip=True))
        if txt:
            candidates.append(txt)

    for txt in candidates:
        upper_txt = txt.upper()
        if any(token in upper_txt for token in ["SGD", "USD", "EUR", "GBP", "AUD", "JPY"]) or re.search(r"\([A-Z]{3}\)", txt):
            amount = _extract_amount_from_text(txt)
            currency = _extract_currency_from_text(txt)
            if amount or currency:
                return {"amount": amount, "currency": currency}

    return {"amount": "", "currency": ""}


def _extract_detail_value(text: str, label: str) -> str:
    patterns = [
        rf"<span>\s*{re.escape(label)}\s*</span>.*?formOutputText_VALUE-DIV[^>]*>(.*?)</div>",
        rf"<label[^>]*>\s*{re.escape(label)}\s*</label>.*?(?:formOutputText_VALUE-DIV|div)[^>]*>(.*?)</div>",
        rf"{re.escape(label)}\s*</span>.*?(?:formOutputText_VALUE-DIV|div)[^>]*>(.*?)</div>",
        rf">{re.escape(label)}<.*?(?:formOutputText_VALUE-DIV|div)[^>]*>(.*?)</div>",
        rf"{re.escape(label)}.*?(?:formOutputText_VALUE-DIV|div)[^>]*>(.*?)</div>",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return _normalize_ws(_strip_tags(m.group(1)))
    return ""


def _extract_status_from_label_divs(text: str) -> str:
    patterns = [
        r'<div[^>]*class="[^"]*\blabel_MAIN\b[^"]*\blabel_WHITE-ON-GRAY\b[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*\blabel_MAIN\b[^"]*\blabel_WHITE-ON-LIGHT-GRAY\b[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*id="[^"]*label_MAIN[^"]*"[^>]*class="[^"]*\blabel_WHITE-ON-GRAY\b[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*id="[^"]*label_MAIN[^"]*"[^>]*class="[^"]*\blabel_WHITE-ON-LIGHT-GRAY\b[^"]*"[^>]*>(.*?)</div>',
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            value = _normalize_ws(_strip_tags(m.group(1))).upper()
            if "AWARDED" in value:
                return "AWARDED"
            if "CLOSED" in value:
                return "CLOSED"
            if "OPEN" in value:
                return "OPEN"

    upper_text = text.upper()
    if "AWARDED" in upper_text:
        return "AWARDED"
    if "CANCELLED" in upper_text:
        return "CANCELLED"

    return ""


def _extract_amount_and_currency(text: str) -> Dict[str, str]:
    candidates = [
        "Award Amount",
        "Estimated Award Value",
        "Estimated Procurement Value",
        "Value of Award",
        "Amount",
        "Tender Value",
        "Contract Value",
        "Total Awarded Amount",
    ]

    raw_value = ""
    for label in candidates:
        raw_value = _extract_detail_value(text, label)
        if raw_value:
            break

    raw_value = _normalize_ws(raw_value)
    currency = _extract_currency_from_text(raw_value)
    amount = _extract_amount_from_text(raw_value)

    if not currency:
        for cur in ["SGD", "USD", "EUR", "GBP", "AUD", "JPY"]:
            if re.search(rf"\b{cur}\b", text, flags=re.IGNORECASE):
                currency = cur
                break

    return {"currency": currency, "amount": amount}


def _extract_supplier_name_from_detail_bs4(html: str, selected_status_filter: str = "") -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    status = str(selected_status_filter or "").strip().upper()

    if status == "OPEN":
        node = soup.select_one("div[id='contentForm:j_idt489:j_id31:j_idt491'] div.formOutputText_VALUE-DIV")
        if node:
            txt = _normalize_ws(node.get_text(" ", strip=True))
            if txt:
                return txt

    if status == "AWARDED":
        node = soup.select_one("div[id='contentForm:j_idt930:j_id382:j_idt933']")
        if node:
            txt = _normalize_ws(node.get_text(" ", strip=True))
            if txt:
                return txt

    fallback_selectors = [
        "div[id='contentForm:j_idt489:j_id31:j_idt491'] div.formOutputText_VALUE-DIV",
        "div[id='contentForm:j_idt489:j_id31:j_idt491']",
        "div[id='contentForm:j_idt930:j_id382:j_idt933']",
        "div[id*='j_idt491'] div.formOutputText_VALUE-DIV",
        "div[id*='j_idt491']",
        "div[id*='j_idt933']",
    ]
    for selector in fallback_selectors:
        node = soup.select_one(selector)
        if node:
            txt = _normalize_ws(node.get_text(" ", strip=True))
            if txt:
                return txt

    return ""


def _extract_awarded_specific_fields_bs4(html: str, fallback_amount: str = "") -> Dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")

    awarding_agency_name = ""
    node = soup.select_one("div[id='contentForm:j_idt809']")
    if node:
        awarding_agency_name = _normalize_ws(node.get_text(" ", strip=True))

    supplier_name = _extract_supplier_name_from_detail_bs4(html, selected_status_filter="AWARDED")

    awarded_date = ""
    node = soup.select_one("div[id='contentForm:j_idt814'] div.formOutputText_VALUE-DIV")
    if node:
        awarded_date = _parse_any_date_to_iso(node.get_text(" ", strip=True))
    else:
        node = soup.select_one("div[id='contentForm:j_idt814']")
        if node:
            awarded_date = _parse_any_date_to_iso(node.get_text(" ", strip=True))

    awarded_value_detail = fallback_amount or ""

    return {
        "awarding_agency_name": awarding_agency_name,
        "supplier_name": supplier_name,
        "awarded_date": awarded_date,
        "awarded_value_detail": awarded_value_detail,
    }


def _extract_awarded_extra_fields(html: str, fallback_amount: str = "") -> Dict[str, str]:
    specific = _extract_awarded_specific_fields_bs4(html, fallback_amount=fallback_amount)
    return {
        "awarding_agency_name": specific.get("awarding_agency_name", ""),
        "supplier_name": specific.get("supplier_name", ""),
        "awarded_date": specific.get("awarded_date", ""),
        "awarded_value_detail": specific.get("awarded_value_detail", ""),
    }


def _extract_contract_period_bs4(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    selectors = [
        "div[id='contentForm:j_idt254'] div.formOutputText_VALUE-DIV",
        "div[id='contentForm:j_idt254']",
        "div[id*='j_idt254'] div.formOutputText_VALUE-DIV",
        "div[id*='j_idt254']",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            txt = _normalize_ws(node.get_text(" ", strip=True))
            if txt:
                return txt

    return ""


def _extract_awarded_items_bs4(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text("\n", strip=True)
    text = _normalize_ws(text)

    item_splits = re.split(r"(Item No\.\s*\d+)", text, flags=re.I)
    items = []

    if len(item_splits) < 3:
        return items

    for i in range(1, len(item_splits), 2):
        item_label = item_splits[i]
        item_block = item_splits[i + 1] if i + 1 < len(item_splits) else ""

        item_no_match = re.search(r"Item No\.\s*(\d+)", item_label, flags=re.I)
        item_no = item_no_match.group(1) if item_no_match else ""

        item_description = ""
        m = re.search(r"^\s*(.*?)\s+Unit of Measurement", item_block, flags=re.I | re.S)
        if m:
            item_description = _normalize_ws(m.group(1))

        item_uom = ""
        m = re.search(r"Unit of Measurement\s+(.*?)\s+Quantity", item_block, flags=re.I | re.S)
        if m:
            item_uom = _normalize_ws(m.group(1))

        item_quantity = ""
        m = re.search(r"Quantity\s+([0-9][0-9,]*(?:\.[0-9]+)?)", item_block, flags=re.I)
        if m:
            item_quantity = m.group(1).replace(",", "")

        item_unit_price = ""
        m = re.search(r"Unit Price\s+([0-9][0-9,]*(?:\.[0-9]+)?(?:\s*\([A-Z]{3}\))?)", item_block, flags=re.I)
        if m:
            item_unit_price = _normalize_ws(m.group(1))

        item_awarded_value = ""
        m = re.search(r"Awarded Value\s+([0-9][0-9,]*(?:\.[0-9]+)?(?:\s*\([A-Z]{3}\))?)", item_block, flags=re.I)
        if m:
            item_awarded_value = _remove_currency_suffix(m.group(1))

        if any([item_no, item_description, item_uom, item_quantity, item_unit_price, item_awarded_value]):
            items.append(
                {
                    "item_no": item_no,
                    "item_description": item_description,
                    "item_uom": item_uom,
                    "item_quantity": item_quantity,
                    "item_unit_price": item_unit_price,
                    "item_awarded_value": item_awarded_value,
                }
            )

    return items


def parse_bolisting_html(html: str, selected_status: str = "") -> List[Dict[str, str]]:
    text = str(html or "")
    selected_status = str(selected_status or "").strip().upper()

    anchor_re = re.compile(
        r'href="(?P<href>/ptn/opportunity/directlink\.xhtml\?docCode=(?P<code>[^&"]+)[^"]*)"[^>]*>(?P<title>[^<]+)</a>',
        flags=re.IGNORECASE,
    )
    matches = list(anchor_re.finditer(text))
    rows: List[Dict[str, str]] = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(text), start + 25000)
        block = text[start:end]

        code = str(match.group("code") or "").strip()
        href = str(match.group("href") or "").strip()
        title = _normalize_ws(_strip_tags(match.group("title") or ""))

        buyer = _extract_block_value(block, "Agency")
        publication_date = _parse_gebiz_datetime_to_date(_extract_block_value(block, "Published"))
        classification = _extract_block_value(block, "Procurement Category")
        closing_date = _extract_listing_closing_date_bs4(block)

        description = _extract_listing_description_bs4(block)
        if "dialogBoxCustom_HandleBrowserScrollBars" in description:
            description = ""

        amount = ""
        currency = ""
        if selected_status == "AWARDED":
            listing_amount_currency = _extract_listing_awarded_amount_currency_bs4(block)
            amount = listing_amount_currency.get("amount", "")
            currency = listing_amount_currency.get("currency", "")

        if code:
            rows.append(
                {
                    "notice_id": code,
                    "notice_url": f"https://www.gebiz.gov.sg{href}",
                    "title": title,
                    "buyer": buyer,
                    "publication_date": publication_date,
                    "closing_date": closing_date,
                    "classification": classification,
                    "status": selected_status,
                    "description": description,
                    "currency": currency,
                    "amount": amount,
                    "awarding_agency_name": "",
                    "supplier_name": "",
                    "awarded_date": "",
                    "awarded_value_detail": amount,
                    "contract_period": "",
                    "item_no": "",
                    "item_description": "",
                    "item_uom": "",
                    "item_quantity": "",
                    "item_unit_price": "",
                    "item_awarded_value": "",
                }
            )
    return rows


def _extract_detail_closing_date_bs4(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for node in soup.select(
        "div.formOutputText_MAIN.shaded_BLUE, span.formOutputText_MAIN.shaded_BLUE, "
        "div.formOutputText_HIDDEN-LABEL.outputText_NAME-BLACK, span.formOutputText_HIDDEN-LABEL.outputText_NAME-BLACK"
    ):
        txt = _normalize_ws(node.get_text(" ", strip=True))
        if not txt:
            continue

        parent_text = ""
        if node.parent is not None:
            parent_text = _normalize_ws(node.parent.get_text(" ", strip=True)).upper()

        if "CLOSING DATE" in txt.upper() or "CLOSING DATE" in parent_text:
            iso = _parse_any_date_to_iso(txt if "CLOSING DATE" not in txt.upper() else parent_text)
            if iso:
                return iso

    for tag in soup.find_all(["div", "span", "tr", "section"]):
        group_text = _normalize_ws(tag.get_text(" ", strip=True))
        if "CLOSING DATE" not in group_text.upper():
            continue
        iso = _parse_any_date_to_iso(group_text)
        if iso:
            return iso

    return ""


def parse_detail_html(html: str, selected_status_filter: str = "") -> Dict[str, str]:
    text = str(html or "")

    status = _extract_status_from_label_divs(text)
    if not status:
        for label in ["Status", "Notice Status", "Opportunity Status"]:
            status = _extract_detail_value(text, label)
            if status:
                status = _normalize_ws(status).upper()
                break

    closing_date = _extract_detail_closing_date_bs4(text)
    if not closing_date:
        for label in ["Closing Date", "Closing Date & Time", "Closing/Opening Date"]:
            raw = _extract_detail_value(text, label)
            closing_date = _parse_any_date_to_iso(raw)
            if closing_date:
                break

    description = ""
    for label in ["Description", "Procurement Description", "Tender Description", "Requirement Specifications"]:
        raw_description = _extract_detail_value(text, label)
        cleaned_description = _clean_text_value(raw_description)
        if cleaned_description:
            description = cleaned_description
            break

    classification = ""
    for label in ["Procurement Category", "Category", "Notice Type"]:
        classification = _extract_detail_value(text, label)
        if classification:
            break

    buyer = ""
    for label in ["Agency", "Buyer", "Procuring Entity"]:
        buyer = _extract_detail_value(text, label)
        if buyer:
            break

    contract_period = _extract_contract_period_bs4(html)
    if not contract_period:
        for label in ["Offer Validity Duration", "Contract Period", "Offer Validity"]:
            contract_period = _extract_detail_value(text, label)
            if contract_period:
                contract_period = _normalize_ws(contract_period)
                break

    amount_parts = _extract_amount_and_currency(text)
    supplier_name = _extract_supplier_name_from_detail_bs4(html, selected_status_filter=selected_status_filter)

    return {
        "closing_date": closing_date,
        "status": status,
        "description": description,
        "classification": classification,
        "buyer": buyer,
        "currency": amount_parts.get("currency", ""),
        "amount": amount_parts.get("amount", ""),
        "supplier_name": supplier_name,
        "contract_period": contract_period,
    }


def enrich_rows_from_detail_pages(
    driver,
    rows: List[Dict[str, str]],
    timeout_seconds: int = 30,
    detail_limit: Optional[int] = None,
    sleep_seconds: float = 1.5,
    selected_status_filter: str = "",
) -> List[Dict[str, str]]:
    enriched: List[Dict[str, str]] = []
    selected_status_filter = str(selected_status_filter or "").strip().upper()

    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        if detail_limit is not None and idx > detail_limit:
            merged = dict(row)
            if not merged.get("status") and selected_status_filter:
                merged["status"] = selected_status_filter
            if not merged.get("awarded_value_detail"):
                merged["awarded_value_detail"] = merged.get("amount", "")
            if merged.get("awarding_agency_name"):
                merged["buyer"] = merged["awarding_agency_name"]
            enriched.append(merged)
            continue

        url = str(row.get("notice_url", "")).strip()
        if not url:
            merged = dict(row)
            if not merged.get("status") and selected_status_filter:
                merged["status"] = selected_status_filter
            if not merged.get("awarded_value_detail"):
                merged["awarded_value_detail"] = merged.get("amount", "")
            if merged.get("awarding_agency_name"):
                merged["buyer"] = merged["awarding_agency_name"]
            enriched.append(merged)
            continue

        try:
            logger.info("Opening detail %s/%s: %s", idx, total, url)
            driver.get(url)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(sleep_seconds)

            html = _driver_page_html(driver)
            overview_details = parse_detail_html(html, selected_status_filter=selected_status_filter)
            details = dict(overview_details)

            extra_award_fields = {}
            award_items_for_notice = []

            if selected_status_filter == "AWARDED":
                clicked = _click_award_details_tab_in_detail_page(driver, timeout_seconds=timeout_seconds)
                if clicked:
                    _wait_for_dom_ready(driver, timeout_seconds)
                    time.sleep(2)

                    award_html = _driver_page_html(driver)
                    award_details = parse_detail_html(award_html, selected_status_filter=selected_status_filter)

                    for key, value in award_details.items():
                        if value:
                            details[key] = value

                    award_items_for_notice = _extract_awarded_items_bs4(award_html)

                    fallback_amount = (
                        award_details.get("amount")
                        or overview_details.get("amount")
                        or row.get("amount", "")
                    )
                    extra_award_fields = _extract_awarded_extra_fields(
                        award_html,
                        fallback_amount=fallback_amount,
                    )
                else:
                    fallback_amount = overview_details.get("amount") or row.get("amount", "")
                    extra_award_fields = {
                        "awarding_agency_name": "",
                        "supplier_name": "",
                        "awarded_date": "",
                        "awarded_value_detail": fallback_amount,
                    }

            merged = dict(row)

            for key in [
                "closing_date",
                "status",
                "description",
                "classification",
                "buyer",
                "currency",
                "amount",
                "supplier_name",
                "contract_period",
            ]:
                if details.get(key):
                    merged[key] = details[key]

            for key in ["awarding_agency_name", "supplier_name", "awarded_date", "awarded_value_detail"]:
                if extra_award_fields.get(key):
                    merged[key] = extra_award_fields[key]

            if not merged.get("status") and selected_status_filter:
                merged["status"] = selected_status_filter

            if not merged.get("awarded_value_detail"):
                merged["awarded_value_detail"] = merged.get("amount", "")

            if merged.get("awarding_agency_name"):
                merged["buyer"] = merged["awarding_agency_name"]

            if selected_status_filter == "AWARDED" and award_items_for_notice:
                for item in award_items_for_notice:
                    item_row = dict(merged)
                    item_row.update(
                        {
                            "item_no": item.get("item_no", ""),
                            "item_description": item.get("item_description", ""),
                            "item_uom": item.get("item_uom", ""),
                            "item_quantity": item.get("item_quantity", ""),
                            "item_unit_price": item.get("item_unit_price", ""),
                            "item_awarded_value": item.get("item_awarded_value", ""),
                        }
                    )
                    enriched.append(item_row)
            else:
                merged.update(
                    {
                        "item_no": "",
                        "item_description": "",
                        "item_uom": "",
                        "item_quantity": "",
                        "item_unit_price": "",
                        "item_awarded_value": "",
                    }
                )
                enriched.append(merged)

        except Exception as exc:
            logger.warning("Failed detail parse for %s: %s", url, exc)
            merged = dict(row)
            if not merged.get("status") and selected_status_filter:
                merged["status"] = selected_status_filter
            if not merged.get("awarded_value_detail"):
                merged["awarded_value_detail"] = merged.get("amount", "")
            if merged.get("awarding_agency_name"):
                merged["buyer"] = merged["awarding_agency_name"]
            merged.update(
                {
                    "item_no": "",
                    "item_description": "",
                    "item_uom": "",
                    "item_quantity": "",
                    "item_unit_price": "",
                    "item_awarded_value": "",
                }
            )
            enriched.append(merged)

    return enriched


def _rows_to_normalized_df(rows: List[Dict[str, str]], query_text: str):
    scraped_at_utc = _utc_now_iso()
    out_rows = []

    for row in rows:
        notice_id = str(row.get("notice_id", "")).strip()
        notice_url = str(row.get("notice_url", "")).strip()

        item_no = _normalize_ws(row.get("item_no", ""))
        dedup_key = _stable_dedup_key("SG_GEBIZ", notice_id, notice_url, item_no)

        out_rows.append(
            {
                "source": "SG_GEBIZ",
                "country": "Singapore",
                "country_code": "SG",
                "publication_date": str(row.get("publication_date", "")).strip(),
                "closing_date": str(row.get("closing_date", "")).strip(),
                "title": _normalize_ws(row.get("title", "")),
                "description": _normalize_ws(row.get("description", "")),
                "buyer": _normalize_ws(row.get("awarding_agency_name", "") or row.get("buyer", "")),
                "classification": _normalize_ws(row.get("classification", "")),
                "status": _normalize_ws(row.get("status", "")).upper(),
                "currency": _normalize_ws(row.get("currency", "")).upper(),
                "amount": _normalize_ws(row.get("amount", "")),
                "awarding_agency_name": _normalize_ws(row.get("awarding_agency_name", "")),
                "supplier_name": _normalize_ws(row.get("supplier_name", "")),
                "awarded_date": _normalize_ws(row.get("awarded_date", "")),
                "awarded_value_detail": _normalize_ws(row.get("awarded_value_detail", "")),
                "contract_period": _normalize_ws(row.get("contract_period", "")),
                "item_no": item_no,
                "item_description": _normalize_ws(row.get("item_description", "")),
                "item_uom": _normalize_ws(row.get("item_uom", "")),
                "item_quantity": _normalize_ws(row.get("item_quantity", "")),
                "item_unit_price": _normalize_ws(row.get("item_unit_price", "")),
                "item_awarded_value": _normalize_ws(row.get("item_awarded_value", "")),
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": dedup_key,
            }
        )

    df = pd.DataFrame(out_rows)
    if df.empty:
        df = pd.DataFrame(columns=NORMALIZED_COLUMNS)
    else:
        df = df.reindex(columns=NORMALIZED_COLUMNS).fillna("")
    return df


def fetch_bolisting_selenium(
    query_text: str,
    page_from: int = 1,
    page_to: Optional[int] = None,
    timeout_seconds: int = 30,
    headless: bool = True,
    detail_limit: Optional[int] = None,
    status_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    date_field: str = "publication_date",
):
    all_rows: List[Dict[str, str]] = []
    driver = _build_chrome_driver(headless=headless, timeout_seconds=timeout_seconds)

    if page_from < 1:
        page_from = 1
    if page_to is not None and page_to < page_from:
        page_to = page_from

    prefilter_publication = str(date_field or "").strip() == "publication_date"

    try:
        logger.info("Opening BOListing page: %s", LISTING_URL)
        driver.get(LISTING_URL)
        _wait_for_dom_ready(driver, timeout_seconds)
        time.sleep(4)

        normalized_status = str(status_filter or "").strip().upper()

        if normalized_status in {"OPEN", "CLOSED", "AWARDED"}:
            _click_main_status_tab(driver, status_filter=normalized_status, timeout_seconds=timeout_seconds)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(3)

            if normalized_status == "CLOSED":
                _click_closed_subtab(driver, status_filter=normalized_status, timeout_seconds=timeout_seconds)
                _wait_for_dom_ready(driver, timeout_seconds)
                time.sleep(3)
            elif normalized_status == "AWARDED":
                _click_awarded_subtab(driver, status_filter=normalized_status, timeout_seconds=timeout_seconds)
                _wait_for_dom_ready(driver, timeout_seconds)
                time.sleep(3)

        current_page = 1
        stop_due_to_old_dates = False

        while current_page < page_from:
            next_page = _find_next_page_number(driver, current_page)
            if next_page is None:
                logger.info("Could not reach requested page_from=%s. Stopped at page %s", page_from, current_page)
                break

            moved = _click_page_number(driver, next_page, timeout_seconds=timeout_seconds)
            if not moved:
                logger.info("Could not move to page %s", next_page)
                break

            current_page = next_page
            time.sleep(4)

        while True:
            if current_page >= page_from:
                html = _driver_page_html(driver)
                page_rows_all = parse_bolisting_html(html, selected_status=normalized_status)
                logger.info("PAGE %s listing rows before prefilter=%s", current_page, len(page_rows_all))

                page_rows = page_rows_all
                if prefilter_publication:
                    before_count = len(page_rows)
                    page_rows = [
                        row for row in page_rows
                        if _date_in_range(
                            row.get("publication_date", ""),
                            date_from=date_from,
                            date_to=date_to,
                        )
                    ]
                    logger.info(
                        "PAGE %s listing rows after publication_date prefilter=%s (before=%s)",
                        current_page,
                        len(page_rows),
                        before_count,
                    )

                seen = {str(r.get("notice_id", "")).strip() + "|" + str(r.get("item_no", "")).strip() for r in all_rows}
                for row in page_rows:
                    key = str(row.get("notice_id", "")).strip() + "|" + str(row.get("item_no", "")).strip()
                    if row.get("notice_id") and key not in seen:
                        if normalized_status and not row.get("status"):
                            row["status"] = normalized_status
                        all_rows.append(row)
                        seen.add(key)

                if prefilter_publication and _all_rows_older_than_date_from(page_rows_all, date_from=date_from):
                    logger.info(
                        "Stopping pagination early at page %s because all listing publication_date values are older than date_from=%s",
                        current_page,
                        date_from,
                    )
                    stop_due_to_old_dates = True

            if page_to is not None and current_page >= page_to:
                break

            if stop_due_to_old_dates:
                break

            next_page = _find_next_page_number(driver, current_page)
            if next_page is None:
                break

            moved = _click_page_number(driver, next_page, timeout_seconds=timeout_seconds)
            if not moved:
                break

            current_page = next_page
            time.sleep(4)

        if all_rows:
            all_rows = enrich_rows_from_detail_pages(
                driver,
                all_rows,
                timeout_seconds=timeout_seconds,
                detail_limit=detail_limit,
                sleep_seconds=1.5,
                selected_status_filter=normalized_status,
            )

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if query_text.strip():
        tokens = [t.lower() for t in re.split(r"\s+", query_text.strip()) if t]
        if tokens:
            all_rows = [
                row
                for row in all_rows
                if any(tok in str(row.get("title", "")).lower() for tok in tokens)
                or any(tok in str(row.get("description", "")).lower() for tok in tokens)
            ]

    return _rows_to_normalized_df(all_rows, query_text=query_text)


def apply_filters(
    df,
    date_from: str = "",
    date_to: str = "",
    date_field: str = "publication_date",
    status_filter: str = "",
):
    out = df.copy()

    if status_filter.strip():
        sf = status_filter.strip().upper()
        out["status"] = out["status"].fillna("").astype(str).str.upper().str.strip()
        out = out[out["status"] == sf].copy()

    if date_field not in out.columns:
        out[date_field] = ""

    out[date_field] = pd.to_datetime(out[date_field], errors="coerce")

    if str(date_from).strip():
        out = out[out[date_field] >= pd.to_datetime(date_from)].copy()

    if str(date_to).strip():
        out = out[out[date_field] <= pd.to_datetime(date_to)].copy()

    out[date_field] = out[date_field].dt.strftime("%Y-%m-%d").fillna("")
    return out


def _status_suffix(status_filter: str) -> str:
    sf = str(status_filter or "").strip().upper()
    if sf in {"OPEN", "CLOSED", "AWARDED"}:
        return sf.lower()
    return "all"


def _page_suffix(page_from: int, page_to: Optional[int]) -> str:
    if page_to is None:
        return f"p{page_from}_to_end"
    if page_from == page_to:
        return f"p{page_from}"
    return f"p{page_from}_to_{page_to}"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-target", default=".")
    parser.add_argument("--page-from", type=int, default=1)
    parser.add_argument("--page-to", type=int, default=None)
    parser.add_argument("--detail-limit", type=int, default=0, help="0 means scrape all detail pages")
    parser.add_argument("--query", default="")
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--date-field", default="publication_date", choices=["publication_date", "closing_date"])
    parser.add_argument("--status-filter", default="", choices=["", "OPEN", "CLOSED", "AWARDED"])
    parser.add_argument("--project-name", default="MDT_2026")
    parser.add_argument("--website-id", default="SG_GEBIZ")
    parser.add_argument("--source-label", default="Singapore GeBIZ")
    parser.add_argument("--region", default="EMEA")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--disable-deduplication", action="store_true")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args()

    print("RUNNING SCRIPT FILE:", __file__)

    detail_limit = None if int(args.detail_limit or 0) <= 0 else int(args.detail_limit)

    df = fetch_bolisting_selenium(
        query_text=args.query,
        page_from=args.page_from,
        page_to=args.page_to,
        timeout_seconds=30,
        headless=not bool(args.headful),
        detail_limit=detail_limit,
        status_filter=args.status_filter,
        date_from=args.date_from,
        date_to=args.date_to,
        date_field=args.date_field,
    )

    filtered_df = apply_filters(
        df,
        date_from=args.date_from,
        date_to=args.date_to,
        date_field=args.date_field,
        status_filter=args.status_filter,
    )

    dedup_before = len(filtered_df)
    if not args.disable_deduplication and "dedup_key" in filtered_df.columns:
        filtered_df = filtered_df.drop_duplicates(subset=["dedup_key"]).copy()
    dedup_after = len(filtered_df)

    output_dir = Path(args.output_target)
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = _status_suffix(args.status_filter)
    page_suffix = _page_suffix(args.page_from, args.page_to)

    csv_path = output_dir / f"run_output_{suffix}_{page_suffix}.csv"
    json_path = output_dir / f"run_output_{suffix}_{page_suffix}.json"
    filtered_csv_path = output_dir / f"gebiz_filtered_{suffix}_{page_suffix}.csv"
    filtered_json_path = output_dir / f"gebiz_filtered_{suffix}_{page_suffix}.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_json(json_path, orient="records", force_ascii=False, indent=2)

    filtered_df.to_csv(filtered_csv_path, index=False, encoding="utf-8")
    filtered_df.to_json(filtered_json_path, orient="records", force_ascii=False, indent=2)

    print("SAVED RAW CSV:", csv_path)
    print("SAVED RAW JSON:", json_path)
    print("SAVED FILTERED CSV:", filtered_csv_path)
    print("SAVED FILTERED JSON:", filtered_json_path)
    print("RAW ROWS:", len(df))
    print("FILTERED ROWS:", len(filtered_df))
    print("DEDUP BEFORE:", dedup_before)
    print("DEDUP AFTER:", dedup_after)


if __name__ == "__main__":
    main()