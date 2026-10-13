#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
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
        r"^(closing date|closing date & time|closing/opening date|published)\s*[:\-]?\s*",
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


def _build_chrome_driver(headless: bool = True, timeout_seconds: int = 30):
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,3000")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    )

    for candidate in ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]:
        if Path(candidate).exists():
            chrome_options.binary_location = candidate
            break

    try:
        driver = webdriver(options=chrome_options)
    except Exception:
        webdriver_manager = importlib.import_module("webdriver_manager.chrome")
        ChromeDriverManager = getattr(webdriver_manager, "ChromeDriverManager")
        driver = webdriver(service=Service(ChromeDriverManager().install()), options=chrome_options)

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


def _click_page_number(driver, target_page: int, timeout_seconds: int = 15) -> bool:
    target_text = str(target_page)
    _scroll_to_bottom(driver)
    before_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()

    selectors = [
        f".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input[id$='_{target_page}_{target_page}']",
        ".formRepeatPagination2_NAVIGATION-BUTTONS-DIV input",
    ]

    for selector in selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue

        for item in items:
            try:
                item_value = (item.get_attribute("value") or "").strip()
                item_id = item.get_attribute("id") or ""
            except Exception:
                continue

            if not (
                item_value == target_text
                or item_id.endswith(f"_{target_page}_{target_page}")
                or f"_{target_page}_{target_page}" in item_id
            ):
                continue

            logger.info("Clicking page %s using id=%s value=%s", target_page, item_id, item_value)

            if not _click_element(driver, item):
                continue

            time.sleep(3)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(2)

            after_html_sig = hashlib.sha1(_driver_page_html(driver)[:50000].encode("utf-8")).hexdigest()
            if before_html_sig != after_html_sig:
                return True

    return False


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

    # exact green hidden-label blocks
    green_nodes = soup.select(
        "div.formOutputText_HIDDEN-LABEL.outputText_DATE-GREEN, "
        "span.formOutputText_HIDDEN-LABEL.outputText_DATE-GREEN"
    )

    for node in green_nodes:
        txt = _normalize_ws(node.get_text(" ", strip=True))
        iso = _parse_any_date_to_iso(txt)
        if iso:
            return iso

    # look around each col-md-12 section
    for container in soup.select("div.col-md-12"):
        container_text = _normalize_ws(container.get_text(" ", strip=True))
        if "CLOSING DATE" in container_text.upper():
            # first try the green value block inside this section
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

            # fallback to whole container text
            iso = _parse_any_date_to_iso(container_text)
            if iso:
                return iso

    # looser fallback: any green date block
    for node in soup.find_all(["div", "span"]):
        classes = " ".join(node.get("class", []))
        if "outputText_DATE-GREEN" in classes:
            txt = _normalize_ws(node.get_text(" ", strip=True))
            iso = _parse_any_date_to_iso(txt)
            if iso:
                return iso

    return ""


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
            if "CLOSED" in value:
                return "CLOSED"
            if "OPEN" in value:
                return "OPEN"

    if "CANCELLED" in text.upper():
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
    currency = ""
    amount = ""

    if raw_value:
        m = re.search(r"\b([A-Z]{3})\b", raw_value)
        if m:
            currency = m.group(1)
        amt = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", raw_value)
        if amt:
            amount = amt.group(1).replace(",", "")

    if not currency:
        for cur in ["SGD", "USD", "EUR", "GBP", "AUD", "JPY"]:
            if re.search(rf"\b{cur}\b", text, flags=re.IGNORECASE):
                currency = cur
                break

    return {"currency": currency, "amount": amount}


def parse_bolisting_html(html: str) -> List[Dict[str, str]]:
    text = str(html or "")
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

        # NEW: closing date from main listing block
        closing_date = _extract_listing_closing_date_bs4(block)

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
                    "status": "",
                    "description": "",
                    "currency": "",
                    "amount": "",
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


def parse_detail_html(html: str) -> Dict[str, str]:
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
        description = _extract_detail_value(text, label)
        if description:
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

    amount_parts = _extract_amount_and_currency(text)

    return {
        "closing_date": closing_date,
        "status": status,
        "description": description,
        "classification": classification,
        "buyer": buyer,
        "currency": amount_parts.get("currency", ""),
        "amount": amount_parts.get("amount", ""),
    }


def enrich_rows_from_detail_pages(
    driver,
    rows: List[Dict[str, str]],
    timeout_seconds: int = 30,
    detail_limit: Optional[int] = None,
    sleep_seconds: float = 1.5,
) -> List[Dict[str, str]]:
    enriched: List[Dict[str, str]] = []

    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        if detail_limit is not None and idx > detail_limit:
            enriched.append(row)
            continue

        url = str(row.get("notice_url", "")).strip()
        if not url:
            enriched.append(row)
            continue

        try:
            logger.info("Opening detail %s/%s: %s", idx, total, url)
            driver.get(url)
            _wait_for_dom_ready(driver, timeout_seconds)
            time.sleep(sleep_seconds)

            html = _driver_page_html(driver)
            details = parse_detail_html(html)

            logger.info(
                "DETAIL PARSED notice_id=%s closing_date=%r status=%r currency=%r amount=%r",
                row.get("notice_id", ""),
                details.get("closing_date", ""),
                details.get("status", ""),
                details.get("currency", ""),
                details.get("amount", ""),
            )

            merged = dict(row)
            for key in ["closing_date", "status", "description", "classification", "buyer", "currency", "amount"]:
                if details.get(key):
                    merged[key] = details[key]
            enriched.append(merged)
        except Exception as exc:
            logger.warning("Failed detail parse for %s: %s", url, exc)
            enriched.append(row)

    return enriched


def _rows_to_normalized_df(rows: List[Dict[str, str]], query_text: str):
    scraped_at_utc = _utc_now_iso()
    out_rows = []

    for row in rows:
        notice_id = str(row.get("notice_id", "")).strip()
        notice_url = str(row.get("notice_url", "")).strip()

        out_rows.append(
            {
                "source": "SG_GEBIZ",
                "country": "Singapore",
                "country_code": "SG",
                "publication_date": str(row.get("publication_date", "")).strip(),
                "closing_date": str(row.get("closing_date", "")).strip(),
                "title": _normalize_ws(row.get("title", "")),
                "description": _normalize_ws(row.get("description", "")),
                "buyer": _normalize_ws(row.get("buyer", "")),
                "classification": _normalize_ws(row.get("classification", "")),
                "status": _normalize_ws(row.get("status", "")).upper(),
                "currency": _normalize_ws(row.get("currency", "")).upper(),
                "amount": _normalize_ws(row.get("amount", "")),
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("SG_GEBIZ", notice_id, notice_url),
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
    max_pages: int = 3,
    timeout_seconds: int = 30,
    headless: bool = True,
    detail_limit: Optional[int] = None,
    status_filter: str = "",
):
    all_rows: List[Dict[str, str]] = []
    driver = _build_chrome_driver(headless=headless, timeout_seconds=timeout_seconds)

    try:
        logger.info("Opening BOListing page: %s", LISTING_URL)
        driver.get(LISTING_URL)
        _wait_for_dom_ready(driver, timeout_seconds)
        time.sleep(4)

        _click_main_status_tab(driver, status_filter=status_filter, timeout_seconds=timeout_seconds)
        _wait_for_dom_ready(driver, timeout_seconds)
        time.sleep(3)

        _click_closed_subtab(driver, status_filter=status_filter, timeout_seconds=timeout_seconds)
        _wait_for_dom_ready(driver, timeout_seconds)
        time.sleep(3)

        for page_num in range(1, max_pages + 1):
            html = _driver_page_html(driver)
            page_rows = parse_bolisting_html(html)
            logger.info("PAGE %s listing rows=%s", page_num, len(page_rows))

            seen = {str(r.get("notice_id", "")).strip() for r in all_rows}
            for row in page_rows:
                nid = str(row.get("notice_id", "")).strip()
                if nid and nid not in seen:
                    all_rows.append(row)
                    seen.add(nid)

            logger.info("TOTAL LISTING ROWS SO FAR=%s", len(all_rows))

            if page_num < max_pages:
                moved = _click_page_number(driver, page_num + 1, timeout_seconds=timeout_seconds)
                if not moved:
                    logger.info("Could not move to page %s", page_num + 1)
                    break
                time.sleep(4)

        logger.info("FINAL LISTING RAW ROW COUNT=%s", len(all_rows))
        if all_rows:
            logger.info("LISTING SAMPLE=%s", json.dumps(all_rows[:3], ensure_ascii=False))

        if all_rows:
            all_rows = enrich_rows_from_detail_pages(
                driver,
                all_rows,
                timeout_seconds=timeout_seconds,
                detail_limit=detail_limit,
                sleep_seconds=1.5,
            )

        logger.info("DETAIL ENRICHMENT COMPLETE. ROW COUNT=%s", len(all_rows))
        if all_rows:
            logger.info("ENRICHED SAMPLE=%s", json.dumps(all_rows[:3], ensure_ascii=False))

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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-target", default=".")
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--detail-limit", type=int, default=0, help="0 means scrape all detail pages")
    parser.add_argument("--query", default="")
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--date-field", default="publication_date", choices=["publication_date", "closing_date"])
    parser.add_argument("--status-filter", default="", choices=["", "OPEN", "CLOSED"])
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
        max_pages=args.max_pages,
        timeout_seconds=30,
        headless=not bool(args.headful),
        detail_limit=detail_limit,
        status_filter=args.status_filter,
    )

    logger.info("NORMALIZED ROWS BEFORE FILTERS=%s", len(df))
    if len(df):
        for col in ["notice_id", "title", "publication_date", "closing_date", "status", "currency", "amount"]:
            non_empty = df[col].fillna("").astype(str).str.strip().ne("").sum()
            logger.info("COLUMN %s NON EMPTY=%s/%s", col, non_empty, len(df))
        logger.info(
            "DF HEAD BEFORE FILTERS\n%s",
            df[
                ["notice_id", "title", "publication_date", "closing_date", "status", "currency", "amount", "notice_url"]
            ].head(10).to_string(index=False),
        )

    filtered_df = apply_filters(
        df,
        date_from=args.date_from,
        date_to=args.date_to,
        date_field=args.date_field,
        status_filter=args.status_filter,
    )

    logger.info("ROWS AFTER FILTERS=%s", len(filtered_df))

    dedup_before = len(filtered_df)
    if not args.disable_deduplication and "dedup_key" in filtered_df.columns:
        filtered_df = filtered_df.drop_duplicates(subset=["dedup_key"]).copy()
    dedup_after = len(filtered_df)

    output_dir = Path(args.output_target)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "run_output.csv"
    json_path = output_dir / "run_output.json"
    filtered_csv_path = output_dir / "gebiz_filtered.csv"
    filtered_json_path = output_dir / "gebiz_filtered.json"

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