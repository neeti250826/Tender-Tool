"""
scraper.py - eProcurement India full pipeline
=============================================
Tender Status search in a real browser with Playwright -> captcha solve (EasyOCR)
-> scrape notices -> fetch award PDFs -> OCR line items -> CSV + JSON export
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from tqdm import tqdm

from captcha_solver import solve_captcha
from common import (
    BASE_URL,
    COLUMNS,
    _looks_like_table_page,
    ocr_image_bytes,
    parse_items_from_ocr_text,
    pdf_bytes_to_images,
    pdf_bytes_to_text_pages,
)

TENDER_STATUS_URL = f"{BASE_URL}?page=WebTenderStatusLists&service=page"
DEFAULT_TENDER_STATUS = "6"
DEFAULT_FROM_DATE = "01/01/2024"
TENDER_STATUS_LABELS = {
    "1": "To Be Opened Tenders",
    "2": "Technical Bid Opening",
    "3": "Technical Evaluation",
    "4": "Financial Bid Opening",
    "5": "Financial Evaluation",
    "6": "AOC",
    "7": "Retender",
    "8": "Cancelled",
    "9": "Concluded",
}


def _default_to_date() -> str:
    return date.today().strftime("%d/%m/%Y")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": BASE_URL,
        }
    )
    return s


def _normalise_href(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("/"):
        return f"https://eprocure.gov.in{href}"
    sep = "" if href.startswith("?") else "?"
    return BASE_URL + sep + href.lstrip("?")


def _copy_context_cookies_to_session(context, session: requests.Session) -> requests.Session:
    session.cookies.clear()
    for cookie in context.cookies():
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return session


def _page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)
    except PlaywrightError:
        return ""


def _page_has_captcha_error(page) -> bool:
    text = _page_text(page).lower()
    bad_markers = [
        "invalid captcha",
        "captcha is invalid",
        "wrong captcha",
    ]
    return any(x in text for x in bad_markers)


def _is_search_form_visible(page) -> bool:
    try:
        return (
            page.locator("#frmSearchFilter").count() > 0
            and page.locator("#Search").count() > 0
            and page.locator("#captchaText").count() > 0
        )
    except PlaywrightError:
        return False


def _solve_page_captcha(page, max_attempts: int = 10) -> Optional[str]:
    if page.locator("#captchaImage").count() == 0:
        logging.warning("  Captcha image element not found.")
        return None

    img_bytes = page.locator("#captchaImage").screenshot(type="png", timeout=10000)
    if not img_bytes:
        logging.warning("  Captcha image screenshot could not be captured.")
        return None

    try:
        return solve_captcha(img_bytes, max_attempts=max_attempts, exact_length=6)
    except TypeError:
        return solve_captcha(img_bytes, max_attempts=max_attempts)


def _refresh_captcha(page) -> None:
    if page.locator("#captcha").count() > 0:
        page.locator("#captcha").click(timeout=10000)
        page.wait_for_timeout(1500)
    elif page.locator("#captchaImage").count() > 0:
        page.locator("#captchaImage").click(timeout=10000)
        page.wait_for_timeout(1500)


def _set_form_value(page, selector: str, value: str) -> None:
    page.evaluate(
        """([sel, val]) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            el.removeAttribute('readonly');
            el.removeAttribute('disabled');
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        [selector, value],
    )


def _select_dropdown_by_label(page, selectors: list[str], label_text: str) -> bool:
    target = _clean_notice_value(label_text)
    if not target:
        return False

    for selector in selectors:
        try:
            if page.locator(selector).count() == 0:
                continue
            page.select_option(selector, label=target)
            return True
        except Exception:
            continue

    for selector in selectors:
        try:
            if page.locator(selector).count() == 0:
                continue
            matched = page.evaluate(
                """([sel, targetText]) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    const wanted = targetText.trim().toLowerCase();
                    const options = Array.from(el.options || []);
                    const match = options.find(opt => (opt.textContent || '').trim().toLowerCase() === wanted);
                    if (!match) return false;
                    el.value = match.value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }""",
                [selector, target],
            )
            if matched:
                return True
        except Exception:
            continue
    return False


def _prepare_tender_status_form(
    page,
    keyword: str,
    tender_status: str,
    product_category: str = "",
    from_date: str = DEFAULT_FROM_DATE,
    to_date: Optional[str] = None,
) -> None:
    to_date = to_date or _default_to_date()

    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1000)

    if page.locator("#tenderStatus").count() == 0:
        raise RuntimeError("Tender status dropdown not found on the page.")

    page.select_option("#tenderStatus", tender_status)
    if page.locator("#KeyWord").count() > 0:
        _set_form_value(page, "#KeyWord", keyword or "")
    _set_form_value(page, "#fromDate", from_date)
    _set_form_value(page, "#toDate", to_date)
    if product_category:
        selected = _select_dropdown_by_label(
            page,
            [
                "#productCategory",
                "select[name='productCategory']",
                "select[id*='productCategory']",
                "select[name*='productCategory']",
            ],
            product_category,
        )
        if not selected:
            raise RuntimeError(f"Product Category dropdown option not found: {product_category!r}")

    logging.info(f"  Search dates set in browser: {from_date} -> {to_date}")


def _extract_detail_link_notices(soup: BeautifulSoup) -> list[dict]:
    notices = []
    seen_links: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = _normalise_href(a["href"])
        href_lower = href.lower()

        if "component=view&page=webtenderstatuslists" not in href_lower:
            continue

        anchor_text = " ".join(a.get_text(" ", strip=True).split())
        row = a.find_parent("tr")
        row_text = " ".join(row.get_text(" ", strip=True).split()) if row else ""
        combined = f"{anchor_text} {row_text} {href}"

        if not re.search(r"\b20\d{2}_[A-Z]+_\d+_\d+\b", combined):
            continue

        if href in seen_links:
            continue
        seen_links.add(href)

        title = ""
        ref_no = ""
        date_value = ""
        org = ""

        if row:
            cells = row.find_all("td")
            if len(cells) >= 1:
                title = cells[0].get_text(" ", strip=True)[:250]
            if len(cells) >= 2:
                ref_no = cells[1].get_text(" ", strip=True)
            if len(cells) >= 3:
                date_value = _normalize_notice_date(cells[2].get_text(" ", strip=True))
            if len(cells) >= 4:
                org = cells[3].get_text(" ", strip=True)
            if not date_value:
                date_value = _normalize_notice_date(row_text)

        notices.append(
            {
                "title": title,
                "refNo": ref_no,
                "date": date_value,
                "org": org,
                "link": href,
                "aocUrl": None,
                "query_text": "",
            }
        )

    logging.info(f"Parsed {len(notices)} detail-link notice(s) from page.")
    return notices


def _page_has_detail_urls(page) -> bool:
    try:
        soup = BeautifulSoup(page.content(), "lxml")
    except Exception:
        return False
    return bool(_extract_detail_link_notices(soup))


def _manual_captcha_submit(
    page,
    keyword: str,
    tender_status: str,
    product_category: str = "",
    attempt_no: int = 1,
    from_date: str = DEFAULT_FROM_DATE,
    to_date: Optional[str] = None,
) -> bool:
    """
    Manual fallback:
    - refresh captcha first
    - save current captcha image
    - let user type in terminal
    - submit and verify
    """
    try:
        to_date = to_date or _default_to_date()

        _prepare_tender_status_form(
            page,
            keyword=keyword,
            tender_status=tender_status,
            product_category=product_category,
            from_date=from_date,
            to_date=to_date,
        )

        _refresh_captcha(page)

        captcha_bytes = page.locator("#captchaImage").screenshot(type="png", timeout=10000)
        debug_name = f"manual_captcha_attempt_{attempt_no}.png"
        with open(debug_name, "wb") as f:
            f.write(captcha_bytes)

        print("\n================ CAPTCHA REQUIRED ================")
        print(f"Open this image if needed: {debug_name}")
        print("Enter the captcha exactly as shown in the browser/image.")
        print("==================================================\n")

        manual_text = input("Enter Captcha: ").strip()
        if not manual_text:
            logging.warning("No captcha entered.")
            return False

        page.fill("#captchaText", "")
        page.fill("#captchaText", manual_text)

        before_url = page.url
        before_text = _page_text(page)

        page.locator("#Search").click(timeout=10000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2500)

        after_url = page.url
        after_text = _page_text(page)

        if _page_has_captcha_error(page):
            logging.warning("Captcha incorrect ❌")
            return False

        if _page_has_detail_urls(page):
            logging.info("Captcha accepted ✅ (detail urls found)")
            return True

        if after_url != before_url and not _is_search_form_visible(page):
            logging.info("Captcha accepted ✅ (navigated away from form)")
            return True

        if after_text != before_text and not _is_search_form_visible(page):
            logging.info("Captcha accepted ✅ (page content changed)")
            return True

        logging.warning("Submission completed but success could not be confirmed.")
        return False

    except Exception as e:
        logging.warning(f"Manual captcha flow failed: {e}")
        return False


def _submit_tender_status_search(
    page,
    keyword: str,
    tender_status: str,
    product_category: str = "",
    max_captcha_rounds: int = 5,
    manual_captcha: bool = False,
    from_date: str = DEFAULT_FROM_DATE,
    to_date: Optional[str] = None,
) -> None:
    to_date = to_date or _default_to_date()

    page.goto(TENDER_STATUS_URL, wait_until="domcontentloaded", timeout=60000)
    _prepare_tender_status_form(
        page,
        keyword=keyword,
        tender_status=tender_status,
        product_category=product_category,
        from_date=from_date,
        to_date=to_date,
    )

    for rnd in range(1, max_captcha_rounds + 1):
        logging.info(f"=== Browser captcha round {rnd}/{max_captcha_rounds} ===")

        captcha_text = _solve_page_captcha(page, max_attempts=10)
        if not captcha_text:
            logging.warning("  Captcha solver returned nothing; refreshing challenge.")
            _prepare_tender_status_form(
                page,
                keyword=keyword,
                tender_status=tender_status,
                product_category=product_category,
                from_date=from_date,
                to_date=to_date,
            )
            _refresh_captcha(page)
            continue

        logging.info(f"  Submitting Tender Status search with captcha='{captcha_text}'...")
        page.fill("#captchaText", "")
        page.fill("#captchaText", captcha_text)
        page.locator("#Search").click(timeout=10000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        if _page_has_captcha_error(page):
            logging.warning("  eProcure rejected captcha; retrying with a fresh challenge.")
            if not _is_search_form_visible(page):
                page.goto(TENDER_STATUS_URL, wait_until="domcontentloaded", timeout=60000)
            _prepare_tender_status_form(
                page,
                keyword=keyword,
                tender_status=tender_status,
                product_category=product_category,
                from_date=from_date,
                to_date=to_date,
            )
            _refresh_captcha(page)
            continue

        if _page_has_detail_urls(page):
            logging.info("  Captcha accepted; detail urls found on the same page.")
            return

        if _is_search_form_visible(page):
            logging.info("  Search remained on the form page and no detail urls were found; retrying captcha.")
            _prepare_tender_status_form(
                page,
                keyword=keyword,
                tender_status=tender_status,
                product_category=product_category,
                from_date=from_date,
                to_date=to_date,
            )
            _refresh_captcha(page)
            continue

        logging.info("  Captcha accepted in browser flow.")
        return

    logging.warning("All automatic captcha attempts failed.")

    if manual_captcha:
        for attempt in range(1, 4):
            success = _manual_captcha_submit(
                page,
                keyword=keyword,
                tender_status=tender_status,
                product_category=product_category,
                attempt_no=attempt,
                from_date=from_date,
                to_date=to_date,
            )
            if success:
                logging.info("Manual captcha accepted. Continuing...")
                return
            logging.warning(f"Manual captcha attempt {attempt} failed. Try again.")

        raise RuntimeError("Manual captcha failed after multiple attempts.")

    raise RuntimeError(
        "All captcha attempts failed. Run with --manual-captcha to solve manually."
    )


def _extract_pagination_label(page) -> str:
    for line in _page_text(page).splitlines():
        line = " ".join(line.split())
        if "page" in line.lower() and any(ch.isdigit() for ch in line):
            return line
    return ""


def _results_page_signature(page) -> str:
    """
    Build a lightweight fingerprint from the visible results so we can detect
    in-place pagination even when the URL and the "Next" link stay the same.
    """
    try:
        soup = BeautifulSoup(page.content(), "lxml")
        notices = parse_notices(soup)
        if notices:
            parts = []
            for notice in notices[:5]:
                parts.append(
                    "|".join(
                        [
                            _clean_notice_value(notice.get("notice_id")),
                            _clean_notice_value(notice.get("refNo")),
                            _clean_notice_value(notice.get("title")),
                            _clean_notice_value(notice.get("link")),
                        ]
                    )
                )
            return " || ".join(parts)
    except Exception:
        pass
    return _extract_pagination_label(page) or _page_text(page)[:500]


def _click_next_results_page(page) -> bool:
    candidates = [
        page.locator("a[title='Next']"),
        page.locator("a:has-text('Next')"),
        page.locator("input[value='Next']"),
        page.locator("a:has-text('>>')"),
    ]

    before_url = page.url
    before_pager = _extract_pagination_label(page)
    before_signature = _results_page_signature(page)

    for locator in candidates:
        try:
            if locator.count() == 0:
                continue
            locator.first.click(timeout=5000)
            page.wait_for_load_state("domcontentloaded")
            changed = False
            for _ in range(8):
                page.wait_for_timeout(500)
                after_pager = _extract_pagination_label(page)
                after_signature = _results_page_signature(page)
                if (
                    page.url != before_url
                    or after_pager != before_pager
                    or after_signature != before_signature
                ):
                    changed = True
                    break
            if changed:
                return True
        except PlaywrightError:
            continue

    return False


def _scroll_results_page(page, rounds: int = 6, pause_ms: int = 700) -> None:
    last_height = -1
    for _ in range(rounds):
        try:
            current_height = page.evaluate("() => document.body.scrollHeight")
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(pause_ms)
            new_height = page.evaluate("() => document.body.scrollHeight")
            if new_height == last_height == current_height:
                break
            last_height = new_height
        except PlaywrightError:
            break


def parse_notices(soup: BeautifulSoup) -> list[dict]:
    notices = []

    table = (
        soup.find("table", {"id": "table"})
        or soup.find("table", class_=lambda c: c and "list" in c.lower())
        or soup.find("table", class_=lambda c: c and "tender" in c.lower())
    )

    if not table:
        all_tables = soup.find_all("table")
        table = max(all_tables, key=lambda t: len(t.find_all("tr")), default=None)

    if table:
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            link_tag = row.find("a", href=True)
            if len(cells) < 2 or not link_tag:
                continue

            href = _normalise_href(link_tag["href"])
            if "component=view&page=webtenderstatuslists" not in href.lower():
                continue

            title = cells[0].get_text(" ", strip=True)[:250] if len(cells) > 0 else ""
            ref_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
            date_value = _normalize_notice_date(cells[2].get_text(" ", strip=True)) if len(cells) > 2 else ""
            org = cells[3].get_text(" ", strip=True) if len(cells) > 3 else ""

            row_text = " ".join(row.get_text(" ", strip=True).split())
            if not date_value:
                date_value = _normalize_notice_date(row_text)
            if not re.search(r"\b20\d{2}_[A-Z]+_\d+_\d+\b", row_text + " " + href):
                continue

            notices.append(
                {
                    "title": title,
                    "refNo": ref_no,
                    "date": date_value,
                    "org": org,
                    "link": href,
                    "source_notice_url": href,
                    "aocUrl": None,
                    "query_text": "",
                }
            )

    if notices:
        logging.info(f"Parsed {len(notices)} notice(s) from table.")
        return notices

    detail_link_notices = _extract_detail_link_notices(soup)
    if detail_link_notices:
        return detail_link_notices

    logging.warning("No results table found; page layout may have changed.")
    return []


def _harvest_current_page_notices(page, keyword: str, seen_links: set[str]) -> list[dict]:
    _scroll_results_page(page)
    soup = BeautifulSoup(page.content(), "lxml")
    page_notices = parse_notices(soup)

    new_notices = []
    for notice in page_notices:
        notice["query_text"] = keyword
        link = notice.get("link", "").strip()

        if not link or link in seen_links:
            continue

        title = (notice.get("title") or "").strip().lower()
        if title.startswith("mis reports tenders by location"):
            continue

        seen_links.add(link)
        new_notices.append(notice)

    return new_notices


def _extract_labeled_value_from_table(soup: BeautifulSoup, label: str) -> str:
    label_norm = " ".join(label.lower().split())

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        left = " ".join(cells[0].get_text(" ", strip=True).replace(":", " ").split()).lower()
        right = cells[1].get_text(" ", strip=True)

        if label_norm in left:
            return right.strip()

    return ""


def _extract_labeled_value_from_text(text: str, label: str) -> str:
    escaped = re.escape(label).replace(r"\ ", r"\s+")
    patterns = [
        rf"{escaped}\s*:\s*(.+)",
        rf"{escaped}\s+(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = " ".join(match.group(1).split())
            if value:
                return value
    return ""


def _extract_labeled_value_from_lines(lines: list[str], label: str) -> str:
    label_norm = " ".join(label.lower().replace(":", " ").split())

    for idx, raw_line in enumerate(lines):
        line = " ".join(raw_line.replace(":", " : ").split())
        line_norm = " ".join(line.lower().replace(":", " ").split())
        if label_norm not in line_norm:
            continue

        for sep in (":", "-", "  "):
            if sep in raw_line:
                left, right = raw_line.split(sep, 1)
                left_norm = " ".join(left.lower().replace(":", " ").split())
                if label_norm in left_norm:
                    value = " ".join(right.split())
                    if value:
                        return value

        suffix = raw_line.lower().find(label.lower())
        if suffix >= 0:
            tail = " ".join(raw_line[suffix + len(label):].lstrip(" :-").split())
            if tail:
                return tail

        if idx + 1 < len(lines):
            next_line = " ".join(lines[idx + 1].split())
            if next_line and len(next_line) < 260:
                return next_line

    return ""


def _is_valid_notice_value(value: str) -> bool:
    value = " ".join((value or "").split())
    if not value:
        return False
    if "MIS Reports Tenders by Location" in value:
        return False
    if len(value) > 260:
        return False
    return True



def _normalize_notice_date(raw: str) -> str:
    raw = " ".join((raw or "").split()).strip()
    if not raw:
        return ""

    raw_slash = raw.replace(".", "/")

    patterns = [
        r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b",
        r"\b(20\d{2})/(\d{1,2})/(\d{1,2})\b",
        r"\b(\d{1,2})[- /.]([A-Za-z]{3,9})[- /.](20\d{2})\b",
        r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})\b",
        r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s*(20\d{2})\b",
    ]

    m = re.search(patterns[0], raw_slash)
    if m:
        d, mth, y = m.groups()
        return f"{int(d):02d}/{int(mth):02d}/{y}"

    m = re.search(patterns[1], raw_slash)
    if m:
        y, mth, d = m.groups()
        return f"{int(d):02d}/{int(mth):02d}/{y}"

    month_lookup = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    m = re.search(patterns[2], raw)
    if m:
        d, month_text, y = m.groups()
        month_no = month_lookup.get(month_text.lower())
        if month_no:
            return f"{int(d):02d}/{int(month_no):02d}/{y}"

    m = re.search(patterns[3], raw)
    if m:
        d, month_text, y = m.groups()
        month_no = month_lookup.get(month_text.lower())
        if month_no:
            return f"{int(d):02d}/{int(month_no):02d}/{y}"

    m = re.search(patterns[4], raw)
    if m:
        month_text, d, y = m.groups()
        month_no = month_lookup.get(month_text.lower())
        if month_no:
            return f"{int(d):02d}/{int(month_no):02d}/{y}"

    return ""


def _clean_bracketed_notice_title(value: str) -> str:
    value = _clean_notice_value(value)
    if not value:
        return ""

    m = re.match(r"^\[(.*?)\]\[(.*?)\]$", value)
    if m:
        return _clean_notice_value(m.group(1))

    if value.startswith("[") and "][" in value and value.endswith("]"):
        return _clean_notice_value(value.split("][", 1)[0].strip("[]"))

    return value


def _resolve_notice_description(description: str, title: str = "") -> str:
    description = _clean_notice_value(description)
    if description:
        return description[:1000]

    title = _clean_bracketed_notice_title(title)
    return title[:1000] if _is_valid_notice_value(title) else ""


def _extract_notice_date_candidates(lines: list[str], body_text: str, soup: BeautifulSoup) -> list[str]:
    labels = [
        "Publication Date",
        "Published Date",
        "Published On",
        "Date of Publication",
        "Publishing Date",
    ]
    candidates: list[str] = []
    for label in labels:
        candidates.extend(
            [
                _extract_labeled_value_from_lines(lines, label),
                _extract_labeled_value_from_text(body_text, label),
                _extract_labeled_value_from_table(soup, label),
            ]
        )
    return [c for c in candidates if _clean_notice_value(c)]


def _extract_notice_date(lines: list[str], body_text: str, soup: BeautifulSoup) -> str:
    for candidate in _extract_notice_date_candidates(lines, body_text, soup):
        normalized = _normalize_notice_date(candidate)
        if normalized:
            return normalized
    return ""


def _extract_best_supplier_from_popup(soup: BeautifulSoup, lines: list[str], body_text: str) -> str:
    direct = (
        _extract_labeled_value_from_lines(lines, "Name of Bidder")
        or _extract_labeled_value_from_lines(lines, "Bidder Name")
        or _extract_labeled_value_from_lines(lines, "Supplier Name")
        or _extract_labeled_value_from_lines(lines, "Vendor Name")
        or _extract_labeled_value_from_text(body_text, "Name of Bidder")
        or _extract_labeled_value_from_text(body_text, "Bidder Name")
        or _extract_labeled_value_from_text(body_text, "Supplier Name")
        or _extract_labeled_value_from_text(body_text, "Vendor Name")
        or _extract_labeled_value_from_table(soup, "Name of Bidder")
        or _extract_labeled_value_from_table(soup, "Bidder Name")
        or _extract_labeled_value_from_table(soup, "Supplier Name")
        or _extract_labeled_value_from_table(soup, "Vendor Name")
    )
    if _is_valid_notice_value(direct):
        return direct

    best = ""
    best_score = -1
    keywords = ["awarded bids list", "financial bid", "financial bid opening", "aoc", "bid summary"]
    bad_terms = ["admitted", "rejected", "responsive", "non responsive", "quoted"]

    for table in soup.find_all("table"):
        table_text = " ".join(table.get_text(" ", strip=True).split()).lower()
        score = sum(3 for k in keywords if k in table_text)
        if score == 0:
            continue

        rows = table.find_all("tr")
        if not rows:
            continue

        header_cells = [" ".join(c.get_text(" ", strip=True).split()).lower() for c in rows[0].find_all(["th", "td"])]
        bidder_idx = None
        for idx, header in enumerate(header_cells):
            if any(x in header for x in ["bidder name", "name of bidder", "supplier name", "vendor name", "firm name"]):
                bidder_idx = idx
                score += 5
                break

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            candidate = ""
            if bidder_idx is not None and bidder_idx < len(cells):
                candidate = " ".join(cells[bidder_idx].get_text(" ", strip=True).split())
            else:
                texts = [" ".join(c.get_text(" ", strip=True).split()) for c in cells]
                filtered = [t for t in texts if _is_valid_notice_value(t) and not re.search(r"^[\d.,/%-]+$", t)]
                for t in filtered:
                    tl = t.lower()
                    if any(bt in tl for bt in bad_terms):
                        continue
                    if len(t.split()) >= 2:
                        candidate = t
                        break

            if _is_valid_notice_value(candidate):
                cscore = score + min(len(candidate.split()), 6)
                if cscore > best_score:
                    best = candidate
                    best_score = cscore

    return best


def _extract_popup_dates(lines: list[str], body_text: str, soup: BeautifulSoup) -> tuple[str, str]:
    publication_date = _extract_notice_date(lines, body_text, soup)
    if not publication_date:
        updated_on = (
            _extract_labeled_value_from_lines(lines, "Updated On")
            or _extract_labeled_value_from_text(body_text, "Updated On")
            or _extract_labeled_value_from_table(soup, "Updated On")
        )
        publication_date = _normalize_notice_date(updated_on)

    closing_candidates = [
        "Closing Date",
        "Bid Opening Date",
        "Bid Opening Date/Time",
        "Bid Submission End Date",
        "Bid Submission Closing Date",
        "Document Download / Sale End Date",
        "Document Download/Sale End Date",
    ]
    closing_date = ""
    for label in closing_candidates:
        candidate = (
            _extract_labeled_value_from_lines(lines, label)
            or _extract_labeled_value_from_text(body_text, label)
            or _extract_labeled_value_from_table(soup, label)
        )
        closing_date = _normalize_notice_date(candidate)
        if closing_date:
            break

    return publication_date, closing_date


def parse_notice_detail_page(soup: BeautifulSoup, notice_url: str) -> dict:
    lines = [
        " ".join(s.split())
        for s in soup.stripped_strings
        if s and " ".join(s.split())
    ]
    body_text = "\n".join(lines)

    org_chain = (
        _extract_labeled_value_from_lines(lines, "Organisation Chain")
        or _extract_labeled_value_from_lines(lines, "Organization Chain")
        or _extract_labeled_value_from_text(body_text, "Organisation Chain")
        or _extract_labeled_value_from_text(body_text, "Organization Chain")
        or _extract_labeled_value_from_table(soup, "Organisation Chain")
        or _extract_labeled_value_from_table(soup, "Organization Chain")
    )
    title = (
        _extract_labeled_value_from_lines(lines, "Tender Title")
        or _extract_labeled_value_from_text(body_text, "Tender Title")
        or _extract_labeled_value_from_table(soup, "Tender Title")
    )
    ref_no = (
        _extract_labeled_value_from_lines(lines, "Tender Ref No")
        or _extract_labeled_value_from_text(body_text, "Tender Ref No")
        or _extract_labeled_value_from_table(soup, "Tender Ref No")
    )
    tender_id = (
        _extract_labeled_value_from_lines(lines, "Tender ID")
        or _extract_labeled_value_from_text(body_text, "Tender ID")
        or _extract_labeled_value_from_table(soup, "Tender ID")
    )
    description = (
        _extract_labeled_value_from_lines(lines, "Tender Description")
        or _extract_labeled_value_from_lines(lines, "Work Description")
        or _extract_labeled_value_from_lines(lines, "Item Description")
        or _extract_labeled_value_from_text(body_text, "Tender Description")
        or _extract_labeled_value_from_text(body_text, "Work Description")
        or _extract_labeled_value_from_text(body_text, "Item Description")
        or _extract_labeled_value_from_table(soup, "Tender Description")
        or _extract_labeled_value_from_table(soup, "Work Description")
        or _extract_labeled_value_from_table(soup, "Item Description")
    )

    amount = (
        _extract_labeled_value_from_lines(lines, "Tender Value")
        or _extract_labeled_value_from_lines(lines, "Estimated Value")
        or _extract_labeled_value_from_lines(lines, "Tender Fee")
        or _extract_labeled_value_from_text(body_text, "Tender Value")
        or _extract_labeled_value_from_text(body_text, "Estimated Value")
        or _extract_labeled_value_from_table(soup, "Tender Value")
        or _extract_labeled_value_from_table(soup, "Estimated Value")
    )

    date_value = _extract_notice_date(lines, body_text, soup)
    description = _resolve_notice_description(description, title)

    return {
        "title": _clean_bracketed_notice_title(title)[:250] if _is_valid_notice_value(title) else "",
        "refNo": ref_no if _is_valid_notice_value(ref_no) else "",
        "notice_id": tender_id if _is_valid_notice_value(tender_id) else "",
        "org": org_chain if _is_valid_notice_value(org_chain) else "",
        "description": description,
        "closing_date": "",
        "amount": amount if _is_valid_notice_value(amount) else "",
        "date": date_value,
        "publication_date": date_value,
        "link": notice_url,
        "source_notice_url": notice_url,
        "aocUrl": None,
        "query_text": "",
    }


def _merge_notice_core_fields(notice: dict, detail_meta: dict) -> None:
    for key in ("title", "refNo", "notice_id", "org", "description", "closing_date", "amount", "publication_date"):
        value = _clean_notice_value(detail_meta.get(key))
        if value:
            notice[key] = value

    detail_date = _normalize_notice_date(detail_meta.get("publication_date") or detail_meta.get("date") or "")
    current_date = _normalize_notice_date(notice.get("publication_date") or notice.get("date") or "")
    resolved_date = detail_date or current_date
    notice["date"] = resolved_date
    notice["publication_date"] = resolved_date
    notice["closing_date"] = _normalize_notice_date(notice.get("closing_date") or detail_meta.get("closing_date") or "")

    notice["title"] = _clean_bracketed_notice_title(notice.get("title"))
    notice["description"] = _resolve_notice_description(
        notice.get("description", ""),
        notice.get("title", ""),
    )


def _parse_popup_notice_meta(soup: BeautifulSoup, notice_url: str) -> dict:
    lines = [
        " ".join(s.split())
        for s in soup.stripped_strings
        if s and " ".join(s.split())
    ]
    body_text = "\n".join(lines)

    title_value = (
        _extract_labeled_value_from_lines(lines, "Tender Title")
        or _extract_labeled_value_from_text(body_text, "Tender Title")
        or _extract_labeled_value_from_table(soup, "Tender Title")
    )
    ref_no = (
        _extract_labeled_value_from_lines(lines, "Tender Ref No")
        or _extract_labeled_value_from_text(body_text, "Tender Ref No")
        or _extract_labeled_value_from_table(soup, "Tender Ref No")
    )
    tender_id = (
        _extract_labeled_value_from_lines(lines, "Tender ID")
        or _extract_labeled_value_from_text(body_text, "Tender ID")
        or _extract_labeled_value_from_table(soup, "Tender ID")
    )
    org_chain = (
        _extract_labeled_value_from_lines(lines, "Organisation Chain")
        or _extract_labeled_value_from_lines(lines, "Organization Chain")
        or _extract_labeled_value_from_text(body_text, "Organisation Chain")
        or _extract_labeled_value_from_text(body_text, "Organization Chain")
        or _extract_labeled_value_from_table(soup, "Organisation Chain")
        or _extract_labeled_value_from_table(soup, "Organization Chain")
    )
    description = (
        _extract_labeled_value_from_lines(lines, "Tender Description")
        or _extract_labeled_value_from_lines(lines, "Work Description")
        or _extract_labeled_value_from_lines(lines, "Item Description")
        or _extract_labeled_value_from_text(body_text, "Tender Description")
        or _extract_labeled_value_from_text(body_text, "Work Description")
        or _extract_labeled_value_from_text(body_text, "Item Description")
        or _extract_labeled_value_from_table(soup, "Tender Description")
        or _extract_labeled_value_from_table(soup, "Work Description")
        or _extract_labeled_value_from_table(soup, "Item Description")
    )

    publication_date, closing_date = _extract_popup_dates(lines, body_text, soup)
    amount = (
        _extract_labeled_value_from_lines(lines, "Tender Value")
        or _extract_labeled_value_from_lines(lines, "Estimated Value")
        or _extract_labeled_value_from_lines(lines, "Total Contract Value")
        or _extract_labeled_value_from_text(body_text, "Tender Value")
        or _extract_labeled_value_from_text(body_text, "Estimated Value")
        or _extract_labeled_value_from_text(body_text, "Total Contract Value")
        or _extract_labeled_value_from_table(soup, "Tender Value")
        or _extract_labeled_value_from_table(soup, "Estimated Value")
        or _extract_labeled_value_from_table(soup, "Total Contract Value")
    )
    bids_meta = _extract_bids_list_meta(soup)
    aoc_meta = _extract_aoc_table_meta(soup)
    aoc_description = _clean_notice_value(aoc_meta.get("aoc_description"))
    supplier_name = (
        bids_meta.get("supplier_name")
        or _extract_best_supplier_from_popup(soup, lines, body_text)
    )
    publication_date = bids_meta.get("publication_date") or publication_date
    amount = aoc_meta.get("awarded_value_detail") or amount

    meta = {
        "title": _clean_bracketed_notice_title(title_value)[:250] if _is_valid_notice_value(title_value) else "",
        "refNo": ref_no if _is_valid_notice_value(ref_no) else "",
        "notice_id": tender_id if _is_valid_notice_value(tender_id) else "",
        "org": org_chain if _is_valid_notice_value(org_chain) else "",
        "description": _resolve_notice_description(aoc_description or description, title_value),
        "closing_date": closing_date,
        "amount": amount if _is_valid_notice_value(amount) else "",
        "link": notice_url,
        "source_notice_url": notice_url,
        "aocUrl": None,
        "query_text": "",
        "date": publication_date,
        "publication_date": publication_date,
        "supplier_name": supplier_name if _is_valid_notice_value(supplier_name) else "",
        "bid_number": _clean_notice_value(bids_meta.get("bid_number")),
        "awarded_date": _clean_notice_value(aoc_meta.get("awarded_date")),
        "awarded_value_detail": _clean_notice_value(aoc_meta.get("awarded_value_detail")),
        "contract_period": _clean_notice_value(aoc_meta.get("contract_period")),
        "aoc_description": _clean_notice_value(aoc_meta.get("aoc_description")),
    }

    return meta


def _extract_bids_list_meta(soup: BeautifulSoup) -> dict:
    meta = {"bid_number": "", "supplier_name": "", "publication_date": ""}
    preferred_tables = []
    exact_table = soup.find("table", {"id": "bidValidTableView"})
    if exact_table is not None:
        preferred_tables.append(exact_table)
    preferred_tables.extend(t for t in soup.find_all("table") if t is not exact_table)

    for table in preferred_tables:
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        heading_text = " ".join(rows[0].get_text(" ", strip=True).split()).lower()
        header_cells = [
            " ".join(cell.get_text(" ", strip=True).split()).lower()
            for cell in rows[1].find_all(["td", "th"])
        ]
        header_text = " | ".join(header_cells)

        is_exact_bids_list = table.get("id") == "bidValidTableView" or heading_text == "bids list"
        if not is_exact_bids_list:
            continue
        if "submitted date" not in header_text or "bidder name" not in header_text or "bid number" not in header_text:
            continue

        bid_number_idx = next((i for i, h in enumerate(header_cells) if "bid number" in h), None)
        bidder_name_idx = next((i for i, h in enumerate(header_cells) if "bidder name" in h), None)
        submitted_date_idx = next((i for i, h in enumerate(header_cells) if "submitted date" in h), None)
        status_idx = next((i for i, h in enumerate(header_cells) if h == "status" or h.endswith(" status")), None)
        remarks_idx = next((i for i, h in enumerate(header_cells) if "remarks" in h), None)

        if bid_number_idx is None or bidder_name_idx is None or submitted_date_idx is None:
            continue

        for row in rows[2:]:
            if row.find("td") is None:
                continue
            cells = row.find_all("td", recursive=False)
            if not cells:
                cells = row.find_all(["td", "th"])
            if len(cells) <= max(bid_number_idx, bidder_name_idx, submitted_date_idx):
                continue

            bid_number_cell = cells[bid_number_idx]
            bid_anchor = bid_number_cell.find("a")
            bid_number_text = _clean_notice_value(
                bid_anchor.get_text(" ", strip=True) if bid_anchor else bid_number_cell.get_text(" ", strip=True)
            )
            supplier_name = _clean_notice_value(cells[bidder_name_idx].get_text(" ", strip=True))
            submitted_date_text = _clean_notice_value(cells[submitted_date_idx].get_text(" ", strip=True))
            row_text = _clean_notice_value(row.get_text(" ", strip=True))
            status_text = ""
            if status_idx is not None and len(cells) > status_idx:
                status_text = _clean_notice_value(cells[status_idx].get_text(" ", strip=True))
            remarks_text = ""
            if remarks_idx is not None and len(cells) > remarks_idx:
                remarks_text = _clean_notice_value(cells[remarks_idx].get_text(" ", strip=True))

            bid_number = bid_number_text.strip()
            publication_date = _normalize_notice_date(submitted_date_text)
            if not publication_date:
                submitted_match = re.search(
                    r"\b\d{1,2}-[A-Za-z]{3}-20\d{2}\b(?:\s+\d{1,2}:\d{2}\s*[AP]M)?",
                    row_text,
                    flags=re.IGNORECASE,
                )
                if submitted_match:
                    publication_date = _normalize_notice_date(submitted_match.group(0))

            if bid_number:
                meta["bid_number"] = bid_number
            if supplier_name:
                meta["supplier_name"] = supplier_name
            if publication_date:
                meta["publication_date"] = publication_date

            if "awarded" in remarks_text.lower():
                return meta

            if "accepted-aoc" in status_text.lower() or "awarded" in status_text.lower():
                return meta

        if meta["bid_number"] or meta["supplier_name"] or meta["publication_date"]:
            return meta
    return meta


def _extract_aoc_table_meta(soup: BeautifulSoup) -> dict:
    meta = {
        "awarded_date": "",
        "awarded_value_detail": "",
        "contract_period": "",
        "aoc_description": "",
        "aoc_href": "",
        "aoc_url": "",
    }
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        heading = " ".join(rows[0].get_text(" ", strip=True).split()).lower()
        table_text = " ".join(table.get_text(" ", strip=True).split()).lower()
        if "aoc" not in heading and "aoc document" not in table_text:
            continue

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            label = _clean_notice_value(cells[0].get_text(" ", strip=True)).lower().rstrip(":")
            value = _clean_notice_value(cells[-1].get_text(" ", strip=True))

            if "contract date" in label:
                meta["awarded_date"] = value
            elif "total contract value" in label:
                meta["awarded_value_detail"] = value
            elif "work completion period" in label:
                meta["contract_period"] = value
            elif "aoc description" in label:
                meta["aoc_description"] = value
            elif "aoc document" in label:
                anchor = row.find("a", href=True)
                if anchor:
                    meta["aoc_href"] = (anchor.get("href") or "").strip()
                    meta["aoc_url"] = _normalise_href(meta["aoc_href"])

        if any(meta.values()):
            return meta
    return meta


def _extract_aoc_document_from_popup_soup(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], dict]:
    extra = _extract_aoc_table_meta(soup)
    aoc_url = extra.get("aoc_url") or ""
    aoc_href = extra.get("aoc_href") or ""
    if aoc_url:
        return aoc_url, aoc_href, extra
    return None, None, extra


def _enrich_notice_via_browser(context, notice: dict) -> dict:
    detail_page = context.new_page()
    popup = None

    try:
        detail_page.goto(notice["link"], wait_until="domcontentloaded", timeout=60000)
        detail_page.wait_for_timeout(1500)

        summary_link = detail_page.locator("a:has-text('all stage summary details')")
        if summary_link.count() == 0:
            summary_link = detail_page.locator("a", has_text="all stage summary")
        if summary_link.count() == 0:
            logging.warning("  Stage summary link not found on detail page.")
            return notice

        with detail_page.expect_popup(timeout=15000) as popup_info:
            summary_link.first.click()

        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded")
        popup.wait_for_timeout(2000)

        popup.evaluate(
            """
            () => {
                window.scrollTo(0, document.body.scrollHeight);
            }
            """
        )
        popup.wait_for_timeout(1500)

        popup.evaluate(
            """
            () => {
                window.scrollTo(0, 0);
            }
            """
        )
        popup.wait_for_timeout(1000)

        popup.evaluate(
            """
            () => {
                return new Promise((resolve) => {
                    let y = 0;
                    const step = 300;
                    const timer = setInterval(() => {
                        window.scrollTo(0, y);
                        y += step;
                        if (y >= document.body.scrollHeight) {
                            clearInterval(timer);
                            resolve(true);
                        }
                    }, 200);
                });
            }
            """
        )
        popup.wait_for_timeout(3000)

        html = popup.content()
        popup_soup = BeautifulSoup(html, "lxml")

        popup_meta = _parse_popup_notice_meta(popup_soup, notice["link"])
        _merge_notice_core_fields(notice, popup_meta)
        for key, value in popup_meta.items():
            if key in {"title", "refNo", "notice_id", "org", "date", "description", "closing_date", "amount"}:
                continue
            if value:
                notice[key] = value

        aoc_url, _aoc_href, extra = _extract_aoc_document_from_popup_soup(popup_soup)
        if not aoc_url:
            with open("debug_popup.html", "w", encoding="utf-8") as f:
                f.write(html)
            logging.warning("  No PDF found in popup HTML. Saved debug_popup.html")
        else:
            logging.info(f"  Found PDF/document URL: {aoc_url}")
            notice["aocUrl"] = aoc_url

        for key, value in extra.items():
            if value and not notice.get(key):
                notice[key] = value

        return notice

    finally:
        if popup is not None:
            try:
                popup.close()
            except Exception:
                pass
        try:
            detail_page.close()
        except Exception:
            pass


def _download_pdf_via_browser(context, pdf_url: str) -> bytes:
    """
    Download PDF through the browser context so eProcure session/cookies are preserved.
    Handles download-triggered navigations correctly.
    """
    page = context.new_page()
    try:
        logging.info(f"  Downloading PDF via browser: {pdf_url}")

        with page.expect_download(timeout=30000) as download_info:
            try:
                page.goto(pdf_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                if "Download is starting" not in str(e):
                    raise

        download = download_info.value
        path = download.path()

        if not path or not os.path.exists(path):
            raise RuntimeError("Playwright download completed but file path was unavailable.")

        with open(path, "rb") as f:
            return f.read()

    finally:
        try:
            page.close()
        except Exception:
            pass


def _download_aoc_pdf_from_notice(context, notice: dict) -> bytes:
    detail_page = context.new_page()
    popup = None
    try:
        notice_url = notice.get("link", "")
        if not notice_url:
            raise RuntimeError("Notice had no detail URL.")

        detail_page.goto(notice_url, wait_until="domcontentloaded", timeout=60000)
        detail_page.wait_for_timeout(1500)

        summary_link = detail_page.locator("a:has-text('all stage summary details')")
        if summary_link.count() == 0:
            summary_link = detail_page.locator("a", has_text="all stage summary")
        if summary_link.count() == 0:
            raise RuntimeError("Stage summary link was not found on the detail page.")

        with detail_page.expect_popup(timeout=15000) as popup_info:
            summary_link.first.click()

        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded")
        popup.wait_for_timeout(1500)

        popup_html = popup.content()
        popup_soup = BeautifulSoup(popup_html, "lxml")
        _aoc_url, aoc_href, _extra = _extract_aoc_document_from_popup_soup(popup_soup)
        if not aoc_href:
            raise RuntimeError("AOC document link was not found in the popup.")

        logging.info(f"  Downloading PDF via popup click: {aoc_href}")

        aoc_link = popup.locator(f'a[href="{aoc_href}"]')
        if aoc_link.count() == 0:
            raise RuntimeError("Exact AOC document anchor could not be found in the popup DOM.")

        with popup.expect_download(timeout=60000) as download_info:
            aoc_link.first.click()

        download = download_info.value
        path = download.path()

        if not path or not os.path.exists(path):
            raise RuntimeError("Playwright download completed but file path was unavailable.")

        with open(path, "rb") as f:
            return f.read()

    finally:
        if popup is not None:
            try:
                popup.close()
            except Exception:
                pass
        try:
            detail_page.close()
        except Exception:
            pass


def collect_notices_with_playwright(
    keyword: str,
    max_pages: Optional[int],
    tender_status: str,
    product_category: str = "",
    limit: Optional[int] = None,
    headful: bool = False,
    manual_captcha: bool = False,
    notice_url: Optional[str] = None,
):
    session = make_session()

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=not headful)
    context = browser.new_context(
        user_agent=session.headers["User-Agent"],
        locale="en-IN",
        ignore_https_errors=True,
        accept_downloads=True,
    )
    page = context.new_page()

    all_notices: list[dict] = []
    seen_links: set[str] = set()

    try:
        if notice_url:
            single_notice = {
                "title": "",
                "refNo": "",
                "notice_id": "",
                "org": "",
                "description": "",
                "closing_date": "",
                "amount": "",
                "date": "",
                "publication_date": "",
                "link": notice_url,
                "source_notice_url": notice_url,
                "aocUrl": None,
                "query_text": keyword or "",
                "bid_number": "",
            }
            logging.info(f"Opening single notice URL for targeted test: {notice_url}")
            _enrich_notice_via_browser(context, single_notice)
            _copy_context_cookies_to_session(context, session)
            return playwright, browser, context, session, [single_notice]

        logging.info(
            "Opening Tender Status page with Playwright "
            f"(status={tender_status} / {TENDER_STATUS_LABELS.get(tender_status, 'Unknown')})."
        )
        _submit_tender_status_search(
            page,
            keyword=keyword,
            tender_status=tender_status,
            product_category=product_category,
            manual_captcha=manual_captcha,
        )
        _copy_context_cookies_to_session(context, session)

        page_idx = 1
        while max_pages is None or page_idx <= max_pages:
            if max_pages is None:
                logging.info(f"\n--- Results page {page_idx} ---")
            else:
                logging.info(f"\n--- Results page {page_idx}/{max_pages} ---")
            new_notices = _harvest_current_page_notices(page, keyword=keyword, seen_links=seen_links)

            if new_notices:
                all_notices.extend(new_notices)
                if limit is not None and len(all_notices) >= limit:
                    all_notices = all_notices[:limit]
                logging.info(
                    f"  Page {page_idx}: +{len(new_notices)} new detail url(s) "
                    f"(total {len(all_notices)})"
                )
            else:
                logging.info("  No new detail urls found on the current results page.")

            _copy_context_cookies_to_session(context, session)

            if limit is not None and len(all_notices) >= limit:
                logging.info(f"  Reached notice limit ({limit}); stopping collection before further pagination.")
                break

            if max_pages is not None and page_idx >= max_pages:
                break

            moved = _click_next_results_page(page)
            if not moved:
                logging.info("  No next-page control found; stopping after exhausting current session results.")
                break

            page_idx += 1

        for idx, notice in enumerate(all_notices, start=1):
            logging.info(f"  Enriching detail/popup metadata {idx}/{len(all_notices)}...")
            try:
                _enrich_notice_via_browser(context, notice)
            except Exception as e:
                logging.warning(f"  Browser detail extraction failed: {e}")

        _copy_context_cookies_to_session(context, session)
        return playwright, browser, context, session, all_notices

    except Exception:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass
        raise


def process_pdf(
    pdf_bytes: bytes,
    notice_meta: dict,
    dpi: int = 450,
    stop_after_first_item_section: bool = True,
    max_consecutive_non_item_pages: int = 2,
    min_pages_after_first_item: int = 2,
) -> list[dict]:
    text_pages = pdf_bytes_to_text_pages(pdf_bytes)
    pages = pdf_bytes_to_images(pdf_bytes, dpi=dpi)
    if not pages:
        logging.error("  PDF rasterisation produced no pages.")
        return []

    all_records = []
    first_item_page = None
    consecutive_non_item_pages = 0

    for i, jpeg_bytes in enumerate(pages, start=1):
        logging.info(f"  Page {i}/{len(pages)}...")

        try:
            page_text = text_pages[i - 1] if i - 1 < len(text_pages) else ""
            if page_text and _looks_like_table_page(page_text):
                logging.info("  Using embedded PDF text for item parsing on this page.")
                records = parse_items_from_ocr_text(page_text, notice_meta, page_num=i)
            elif page_text:
                logging.info("  Skipping OCR for this page because it has embedded text but no item table/list.")
                records = []
            else:
                logging.info("  EasyOCR on scanned/image page.")
                ocr_text = ocr_image_bytes(jpeg_bytes, page_num=i, total_pages=len(pages))
                if not ocr_text.strip() or not _looks_like_table_page(ocr_text):
                    records = []
                else:
                    records = parse_items_from_ocr_text(ocr_text, notice_meta, page_num=i)
        except Exception as e:
            logging.error(f"  EasyOCR failed on page {i}: {e}")
            records = []

        if records:
            all_records.extend(records)
            consecutive_non_item_pages = 0
            if first_item_page is None:
                first_item_page = i
        else:
            if first_item_page is not None:
                consecutive_non_item_pages += 1

        if stop_after_first_item_section and first_item_page is not None:
            pages_checked_after_first_item = i - first_item_page

            if (
                pages_checked_after_first_item >= min_pages_after_first_item
                and consecutive_non_item_pages >= max_consecutive_non_item_pages
            ):
                logging.info(
                    "  Item section already extracted; "
                    f"stopping after {consecutive_non_item_pages} consecutive non-item page(s)."
                )
                break

    return all_records


def _clean_notice_value(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _extract_currency_and_amount(raw_value: str) -> tuple[str, str]:
    raw = _clean_notice_value(raw_value)
    if not raw:
        return "INR", ""

    raw_lower = raw.lower()
    currency = "INR"
    if "usd" in raw_lower:
        currency = "USD"
    elif "eur" in raw_lower:
        currency = "EUR"
    elif "inr" in raw_lower or "rs" in raw_lower or "₹" in raw:
        currency = "INR"

    nums = re.findall(r"\d[\d,]*(?:\.\d+)?", raw)
    amount = nums[-1].replace(",", "") if nums else ""
    return currency, amount


def _merge_notice_fields_into_item_records(records: list[dict], notice: dict) -> list[dict]:
    """
    Keep item fields from PDF rows, but force all non-item fields from notice/detail metadata.
    """
    currency, amount = _extract_currency_and_amount(
        notice.get("amount") or notice.get("awarded_value_detail") or ""
    )

    merged = []
    for row in records:
        out = dict(row)

        out["source"] = "eprocure_india"
        out["country"] = "India"
        out["country_code"] = "IN"
        out["publication_date"] = _normalize_notice_date(notice.get("publication_date") or notice.get("date"))
        out["closing_date"] = _normalize_notice_date(notice.get("closing_date"))
        out["title"] = _clean_notice_value(notice.get("title"))
        out["description"] = _clean_notice_value(notice.get("description"))
        out["buyer"] = _clean_notice_value(notice.get("org"))
        out["status"] = "awarded" if notice.get("aocUrl") else _clean_notice_value(out.get("status", ""))
        out["currency"] = currency
        out["amount"] = amount
        out["awarding_agency_name"] = _clean_notice_value(notice.get("org"))
        out["supplier_name"] = _clean_notice_value(notice.get("supplier_name"))
        out["awarded_date"] = _clean_notice_value(notice.get("awarded_date"))
        out["awarded_value_detail"] = _clean_notice_value(notice.get("awarded_value_detail"))
        out["contract_period"] = _clean_notice_value(notice.get("contract_period"))
        out["bid_number"] = _clean_notice_value(notice.get("bid_number"))
        out["notice_id"] = _clean_notice_value(notice.get("notice_id") or notice.get("refNo"))
        out["notice_url"] = _clean_notice_value(notice.get("source_notice_url") or notice.get("link"))
        out["query_text"] = _clean_notice_value(notice.get("query_text"))

        merged.append(out)

    return merged


def _fallback_record_from_notice(notice: dict) -> list[dict]:
    """
    If PDF OCR yields no rows, still create one notice-level row from detail/popup metadata.
    Item fields remain blank.
    """
    currency, amount = _extract_currency_and_amount(
        notice.get("amount") or notice.get("awarded_value_detail") or ""
    )

    row = {
        "source": "eprocure_india",
        "country": "India",
        "country_code": "IN",
        "publication_date": _normalize_notice_date(notice.get("publication_date") or notice.get("date")),
        "closing_date": "",
        "title": _clean_notice_value(notice.get("title")),
        "description": _clean_notice_value(notice.get("description")),
        "buyer": _clean_notice_value(notice.get("org")),
        "classification": "",
        "status": "awarded" if notice.get("aocUrl") else "",
        "currency": currency,
        "amount": amount,
        "awarding_agency_name": _clean_notice_value(notice.get("org")),
        "supplier_name": _clean_notice_value(notice.get("supplier_name")),
        "awarded_date": _clean_notice_value(notice.get("awarded_date")),
        "awarded_value_detail": _clean_notice_value(notice.get("awarded_value_detail")),
        "contract_period": _clean_notice_value(notice.get("contract_period")),
        "bid_number": _clean_notice_value(notice.get("bid_number")),
        "item_no": "",
        "item_description": "",
        "item_uom": "",
        "item_quantity": "",
        "item_unit_price": "",
        "item_awarded_value": "",
        "notice_id": _clean_notice_value(notice.get("notice_id") or notice.get("refNo")),
        "notice_url": _clean_notice_value(notice.get("source_notice_url") or notice.get("link")),
        "query_text": _clean_notice_value(notice.get("query_text")),
        "scraped_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dedup_key": "",
    }

    row["dedup_key"] = " | ".join(
        x for x in [
            row["source"],
            row["notice_id"],
            row["title"],
            row["supplier_name"],
            row["awarded_date"],
            row["amount"],
        ] if x
    )

    meaningful = any([
        row["title"],
        row["description"],
        row["buyer"],
        row["supplier_name"],
        row["awarded_date"],
        row["awarded_value_detail"],
        row["amount"],
        row["notice_id"],
    ])
    return [row] if meaningful else []


def save_csv(records: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    logging.info(f"CSV  saved -> {path}  ({len(records)} rows)")


def save_json(records: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    logging.info(f"JSON saved -> {path}  ({len(records)} records)")


def maybe_save_pdf(pdf_bytes: bytes, notice: dict, idx: int, out_dir: str):
    safe = (notice.get("refNo") or f"notice_{idx}").replace("/", "_").replace(" ", "_")
    dest = os.path.join(out_dir, f"{safe}.pdf")
    with open(dest, "wb") as f:
        f.write(pdf_bytes)
    logging.info(f"  PDF saved -> {dest}")


def run(args):
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("scraper.log", encoding="utf-8"),
        ],
    )

    playwright = None
    browser = None
    context = None

    if not args.notice_url and not args.keyword and not args.product_category:
        logging.error("Provide either --notice-url or at least one search filter such as --keyword or --product-category.")
        sys.exit(1)

    try:
        playwright, browser, context, session, all_notices = collect_notices_with_playwright(
            keyword=args.keyword,
            max_pages=args.max_pages,
            tender_status=args.tender_status,
            product_category=args.product_category,
            limit=args.limit,
            headful=args.headful,
            manual_captcha=args.manual_captcha,
            notice_url=args.notice_url,
        )
    except Exception as e:
        logging.error(f"Playwright search failed: {e}")
        sys.exit(1)

    try:
        for idx, n in enumerate(all_notices, start=1):
            logging.info(
                f"NOTICE {idx}: notice_id={n.get('notice_id')!r} "
                f"title={n.get('title')!r} refNo={n.get('refNo')!r} "
                f"aocUrl={n.get('aocUrl')!r}"
            )

        if not all_notices:
            logging.error("No notices found. Check keyword or network.")
            sys.exit(0)

        if args.limit is not None:
            all_notices = all_notices[:args.limit]
            logging.info(f"Limiting to first {len(all_notices)} notice(s) for testing.")

        logging.info(f"\nTotal notices to process: {len(all_notices)}")

        all_records = []
        os.makedirs(args.output_dir, exist_ok=True)
        if args.save_pdfs:
            os.makedirs(args.pdf_dir, exist_ok=True)

        for idx, notice in enumerate(tqdm(all_notices, desc="Notices"), start=1):
            ref = notice.get("refNo") or notice.get("title", "")[:50]
            logging.info(f"\n--- [{idx}/{len(all_notices)}] {ref} ---")

            if not notice.get("link"):
                logging.warning("  No detail URL found - skipping.")
                continue

            try:
                pdf_bytes = _download_aoc_pdf_from_notice(context, notice)
                if not pdf_bytes:
                    raise RuntimeError("Downloaded PDF was empty.")
            except Exception as e:
                logging.error(f"  Browser PDF download failed: {e}")
                fallback_records = _fallback_record_from_notice(notice)
                logging.info(f"  -> {len(fallback_records)} fallback record(s) built from notice details")
                all_records.extend(fallback_records)
                continue

            if args.save_pdfs:
                maybe_save_pdf(pdf_bytes, notice, idx, args.pdf_dir)

            try:
                records = process_pdf(
                    pdf_bytes,
                    notice,
                    dpi=args.dpi,
                    stop_after_first_item_section=not args.no_early_stop,
                    max_consecutive_non_item_pages=2,
                    min_pages_after_first_item=2,
                )

                if records:
                    records = _merge_notice_fields_into_item_records(records, notice)
                    logging.info(f"  -> {len(records)} item(s) extracted from PDF")
                    all_records.extend(records)
                else:
                    logging.warning("  No item rows extracted from PDF; building fallback notice-level row.")
                    fallback_records = _fallback_record_from_notice(notice)
                    logging.info(f"  -> {len(fallback_records)} fallback record(s) built from notice details")
                    all_records.extend(fallback_records)

            except Exception as e:
                logging.error(f"  Processing failed: {e}")
                logging.warning("  Falling back to notice/detail metadata after PDF processing failure.")
                fallback_records = _fallback_record_from_notice(notice)
                logging.info(f"  -> {len(fallback_records)} fallback record(s) built from notice details")
                all_records.extend(fallback_records)

            time.sleep(args.delay)

        csv_path = os.path.join(args.output_dir, "eprocure_tenders.csv")
        json_path = os.path.join(args.output_dir, "eprocure_tenders.json")
        save_csv(all_records, csv_path)
        save_json(all_records, json_path)

        print(f"\nDone - {len(all_records)} total line items saved to '{args.output_dir}/'")

    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="eProcurement India scraper with Playwright-backed Tender Status search.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--keyword", default="", help="Search keyword")
    p.add_argument("--product-category", default="", help="Product Category dropdown label, e.g. 'Consumables (Hospital / Lab)'")
    p.add_argument("--notice-url", default="", help="Test a single tender detail URL directly")
    p.add_argument("--max-pages", type=int, default=None, help="Max search result pages; omit to keep going until Next is unavailable")
    p.add_argument(
        "--tender-status",
        default=DEFAULT_TENDER_STATUS,
        choices=sorted(TENDER_STATUS_LABELS),
        help="Tender Status code from the WebTenderStatusLists page",
    )
    p.add_argument("--dpi", type=int, default=450, help="PDF rasterisation DPI")
    p.add_argument("--delay", type=float, default=2.0, help="Seconds between requests")
    p.add_argument("--output-dir", default="output", help="Output folder for CSV + JSON")
    p.add_argument("--save-pdfs", action="store_true", help="Also save PDFs to --pdf-dir")
    p.add_argument("--pdf-dir", default="pdfs", help="Folder for saved PDFs")
    p.add_argument("--limit", type=int, default=None, help="Limit number of collected notices to process")
    p.add_argument("--no-early-stop", action="store_true", help="Scan all pages even after item pages are extracted")
    p.add_argument("--headful", action="store_true", help="Launch Chromium with a visible window for debugging")
    p.add_argument(
        "--manual-captcha",
        action="store_true",
        help="After OCR retries fail, prompt for manual captcha entry in the terminal",
    )
    p.add_argument("--verbose", action="store_true", help="DEBUG logging")
    return p


if __name__ == "__main__":
    run(build_parser().parse_args())
