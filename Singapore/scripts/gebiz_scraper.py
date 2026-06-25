#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
from html import unescape
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple
import re

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
    playwright_sync = importlib.import_module("playwright.sync_api")
    sync_playwright = getattr(playwright_sync, "sync_playwright")
except Exception:
    sync_playwright = None


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
    """Parse GeBIZ BOListing HTML into minimal row dicts."""

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
    """Legacy first-page-only requests fetch. Kept for fallback/debug."""

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

    rows = _enrich_rows_from_detail_pages(rows, timeout_seconds=30)
    return _rows_to_normalized_df(rows=rows, query_text=query_text)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(part or "").strip() for part in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _merge_rows_by_notice_id(
    existing: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    seen = {str(row.get("notice_id", "")).strip() for row in existing}
    for row in new_rows:
        notice_id = str(row.get("notice_id", "")).strip()
        if not notice_id or notice_id in seen:
            continue
        existing.append(row)
        seen.add(notice_id)
    return existing


def _extract_detail_field(html: str, label: str) -> str:
    patterns = [
        rf"<span>\s*{re.escape(label)}\s*:?\s*</span>.*?formOutputText_VALUE-DIV[^>]*>(.*?)</div>",
        rf"{re.escape(label)}\s*:?\s*</[^>]+>\s*<[^>]+>(.*?)</",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _strip_tags(match.group(1))
    return ""


def _extract_first_detail_field(html: str, labels: Sequence[str]) -> str:
    for label in labels:
        value = _extract_detail_field(html, label)
        if value:
            return value
    return ""


def _parse_currency_amount(raw_value: str) -> Tuple[str, str]:
    text = re.sub(r"\s+", " ", _strip_tags(raw_value or "")).strip()
    if not text:
        return "", ""

    currency_patterns = [
        (r"\bSGD\b", "SGD"),
        (r"\bUSD\b", "USD"),
        (r"\bEUR\b", "EUR"),
        (r"\bGBP\b", "GBP"),
        (r"\bJPY\b", "JPY"),
        (r"\bAUD\b", "AUD"),
        (r"\bCAD\b", "CAD"),
        (r"\bCHF\b", "CHF"),
        (r"\bCNY\b", "CNY"),
        (r"\bHKD\b", "HKD"),
        (r"\bNZD\b", "NZD"),
        (r"\bINR\b", "INR"),
        (r"S\$", "SGD"),
        (r"US\$", "USD"),
        (r"HK\$", "HKD"),
        (r"€", "EUR"),
        (r"£", "GBP"),
        (r"¥", "JPY"),
    ]

    currency = ""
    for pattern, code in currency_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            currency = code
            break

    amount_match = re.search(
        r"(?<!\d)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d)",
        text,
    )
    amount = amount_match.group(1).replace(",", "") if amount_match else ""
    return currency, amount


def _parse_detail_page(session, url: str, timeout_seconds: int) -> Dict[str, str]:
    if not url:
        return {}

    try:
        response = session.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        html = response.text
    except Exception:
        return {}

    title_match = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, flags=re.IGNORECASE | re.DOTALL)
    title = _strip_tags(title_match.group(1)) if title_match else ""
    description = _extract_first_detail_field(html, ["Description", "Requirement Specifications"])
    agency = _extract_detail_field(html, "Agency")
    procurement_category = _extract_detail_field(html, "Procurement Category")

    value_text = _extract_first_detail_field(
        html,
        [
            "Award Value",
            "Awarded Value",
            "Total Award Value",
            "Estimated Value",
            "Estimated Total Value",
            "Tender Value",
            "Contract Value",
            "Value",
            "Budget",
        ],
    )
    currency, amount = _parse_currency_amount(value_text)

    if not amount:
        money_context_match = re.search(
            r"(award(?:ed)?|estimated|contract|tender|budget)[^<]{0,120}"
            r"((?:S\$|US\$|HK\$|SGD|USD|EUR|GBP|JPY)?\s*\d[\d,]*(?:\.\d+)?)",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if money_context_match:
            currency, amount = _parse_currency_amount(money_context_match.group(2))

    return {
        "detail_title": title,
        "detail_description": description,
        "detail_agency": agency,
        "detail_procurement_category": procurement_category,
        "detail_currency": currency,
        "detail_amount": amount,
    }


def _enrich_rows_from_detail_pages(
    rows: List[Dict[str, str]],
    *,
    timeout_seconds: int,
) -> List[Dict[str, str]]:
    if not rows:
        return []

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )

    enriched_rows: List[Dict[str, str]] = []
    for row in rows:
        merged = dict(row)
        merged.update(_parse_detail_page(session, str(row.get("notice_url", "")).strip(), timeout_seconds))
        if merged.get("detail_title"):
            merged["title"] = str(merged.get("detail_title", "")).strip()
        if merged.get("detail_agency"):
            merged["buyer"] = str(merged.get("detail_agency", "")).strip()
        if merged.get("detail_procurement_category"):
            merged["classification"] = str(merged.get("detail_procurement_category", "")).strip()
        if merged.get("detail_description"):
            merged["description"] = str(merged.get("detail_description", "")).strip()
        if merged.get("detail_currency"):
            merged["currency"] = str(merged.get("detail_currency", "")).strip()
        if merged.get("detail_amount"):
            merged["amount"] = str(merged.get("detail_amount", "")).strip()
        enriched_rows.append(merged)
    return enriched_rows


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
        description = str(row.get("description", "")).strip()
        currency = str(row.get("currency", "")).strip()
        amount = str(row.get("amount", "")).strip()

        out_rows.append(
            {
                "source": "SG_GEBIZ",
                "country": "Singapore",
                "country_code": "SG",
                "publication_date": publication_date,
                "title": title,
                "description": description,
                "buyer": buyer,
                "classification": classification,
                "currency": currency,
                "amount": amount,
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


def _get_current_page_number(page) -> str:
    selectors = [
        ".ui-paginator-page.ui-state-active",
        ".ui-paginator-page.ui-state-highlight",
        ".ui-state-active",
        "[aria-current='page']",
        ".p-paginator-page.p-highlight",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                text = loc.inner_text().strip()
                if text.isdigit():
                    return text
        except Exception:
            pass
    return ""


def _scroll_to_bottom(page) -> None:
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
    except Exception:
        pass


def _debug_paginator(page) -> None:
    selectors = [
        ".ui-paginator-page",
        ".p-paginator-page",
        "a[href='#']",
        "button",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            total = loc.count()
            count = min(total, 30)
            logger.info("Paginator debug selector=%s count=%s", selector, total)
            for i in range(count):
                item = loc.nth(i)
                try:
                    txt = item.inner_text().strip()
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


def _click_page_number(page, target_page: int, timeout_ms: int = 15000) -> bool:
    target_text = str(target_page)

    _scroll_to_bottom(page)

    selectors = [
        ".ui-paginator-page",
        ".p-paginator-page",
        "a",
        "button",
        "span",
    ]

    before_active = _get_current_page_number(page)
    before_html_sig = hashlib.sha1(page.content()[:50000].encode("utf-8")).hexdigest()

    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = loc.count()

            for i in range(count):
                item = loc.nth(i)

                try:
                    text = item.inner_text().strip()
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

                try:
                    item.scroll_into_view_if_needed(timeout=timeout_ms)
                except Exception:
                    pass

                try:
                    item.click(timeout=timeout_ms)
                except Exception:
                    try:
                        item.evaluate("(el) => el.click()")
                    except Exception:
                        continue

                page.wait_for_timeout(3000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass
                page.wait_for_timeout(2000)

                after_active = _get_current_page_number(page)
                after_html_sig = hashlib.sha1(page.content()[:50000].encode("utf-8")).hexdigest()

                if after_active == target_text:
                    return True
                if before_active != after_active and after_active:
                    return True
                if before_html_sig != after_html_sig:
                    return True

        except Exception:
            continue

    return False


def _click_next_page(page, current_loop_page: int, timeout_ms: int = 15000) -> bool:
    next_selectors = [
        ".ui-paginator-next",
        ".p-paginator-next",
        "a[aria-label='Next Page']",
        "button[aria-label='Next Page']",
        "a[title='Next']",
        "button[title='Next']",
    ]

    for selector in next_selectors:
        try:
            next_btn = page.locator(selector).first
            if next_btn.count() == 0:
                continue

            cls = (next_btn.get_attribute("class") or "").lower()
            aria_disabled = (next_btn.get_attribute("aria-disabled") or "").lower()

            if "disabled" in cls or aria_disabled == "true":
                break

            _scroll_to_bottom(page)

            before_html_sig = hashlib.sha1(page.content()[:50000].encode("utf-8")).hexdigest()

            try:
                next_btn.scroll_into_view_if_needed(timeout=timeout_ms)
            except Exception:
                pass

            next_btn.click(timeout=timeout_ms)
            page.wait_for_timeout(3000)

            try:
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass

            page.wait_for_timeout(2000)
            after_html_sig = hashlib.sha1(page.content()[:50000].encode("utf-8")).hexdigest()
            if before_html_sig != after_html_sig:
                return True

        except Exception:
            continue

    return _click_page_number(page, current_loop_page + 1, timeout_ms=timeout_ms)


def _apply_query_if_present(page, query_text: str) -> None:
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
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.fill(q)
            page.keyboard.press("Enter")
            page.wait_for_timeout(4000)
            return
        except Exception:
            continue


def fetch_bolisting_playwright(
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
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        logger.info("Opening BOListing page: %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        page.wait_for_timeout(4000)

        _apply_query_if_present(page, query_text)

        _scroll_to_bottom(page)
        _debug_paginator(page)

        page_num = 1
        seen_page_signatures = set()

        while page_num <= max_pages:
            html = page.content()

            if debug_dir is not None:
                (debug_dir / f"page_{page_num:03d}.html").write_text(html, encoding="utf-8")

            page_rows = parse_bolisting_html(html)
            before_count = len(all_rows)
            all_rows = _merge_rows_by_notice_id(all_rows, page_rows)
            added_count = len(all_rows) - before_count

            current_page_label = _get_current_page_number(page)
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

            _scroll_to_bottom(page)
            current_page_label = _get_current_page_number(page)
            logger.info("Current paginator page label before move: %s", current_page_label or "?")

            target_next_page = page_num + 1
            moved = _click_page_number(
                page,
                target_page=target_next_page,
                timeout_ms=timeout_seconds * 1000,
            )

            if not moved:
                logger.info("Could not click page number %s. Trying next-button fallback.", target_next_page)
                moved = _click_next_page(
                    page,
                    current_loop_page=page_num,
                    timeout_ms=timeout_seconds * 1000,
                )

            if not moved:
                logger.info("No next page available. Pagination finished.")
                break

            page.wait_for_timeout(4000)
            page_num += 1

        browser.close()

    tokens = [t.lower() for t in re.split(r"\s+", str(query_text or "").strip()) if t]
    if tokens:
        all_rows = [
            row for row in all_rows
            if any(t in str(row.get("title", "")).lower() for t in tokens)
        ]

    allowed_years = {int(y) for y in years if str(y).isdigit() or isinstance(y, int)}
    if allowed_years:
        filtered: List[Dict[str, str]] = []
        for row in all_rows:
            pub = str(row.get("publication_date", ""))
            year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else None
            if year is None or year in allowed_years:
                filtered.append(row)
        all_rows = filtered

    all_rows = _enrich_rows_from_detail_pages(all_rows, timeout_seconds=timeout_seconds)
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
    parser = argparse.ArgumentParser(description="Scaffold scraper for Singapore GeBIZ (SG_GEBIZ)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword search.")
    parser.add_argument("--output-target", default="", help="Google Drive URL or local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Use Playwright to discover data endpoints and write web artifacts, then exit.",
    )
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum BOListing pages to paginate.")
    parser.add_argument("--headful", action="store_true", help="Run Playwright with visible browser for debugging.")
    parser.add_argument(
        "--save-debug-pages",
        action="store_true",
        help="Save paginated listing HTML pages into the web output folder.",
    )
    parser.add_argument(
        "--use-requests-fallback",
        action="store_true",
        help="Use old first-page-only requests fetch instead of Playwright pagination.",
    )

    parser.add_argument(
        "--project-name",
        default="MDT_2026",
        help="Project name token in outputs (PROJECT_NAME_YEAR).",
    )
    parser.add_argument("--website-id", default="SG_GEBIZ", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Singapore GeBIZ", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    add_standard_colab_args(parser, default_country="SG")
    return parser.parse_args(list(argv) if argv is not None else None)


def discover_endpoints_playwright(
    *,
    query_text: str,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, int, str]:
    """Attempt to discover GeBIZ data endpoints via Playwright."""

    if sync_playwright is None:
        logger.warning("Playwright not available. Install 'playwright' to enable --discover-only.")
        return "", 0, "playwright_not_installed"

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

    def should_capture(response) -> bool:
        try:
            request = response.request
            if getattr(request, "resource_type", "") in {"xhr", "fetch"}:
                return True
            headers = getattr(response, "headers", {}) or {}
            content_type = str(headers.get("content-type", "") or "").lower()
            return ("application/json" in content_type) or ("text/" in content_type)
        except Exception:
            return False

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            def on_response(response):
                if len(records) >= 200:
                    return
                if not should_capture(response):
                    return
                try:
                    request = response.request
                    headers = getattr(response, "headers", {}) or {}
                    content_type = str(headers.get("content-type", "") or "")
                    body_preview = ""
                    if "json" in content_type.lower() or content_type.lower().startswith("text/"):
                        try:
                            body_preview = str(response.text() or "")[:500]
                        except Exception:
                            body_preview = ""
                    records.append(
                        {
                            "ts_utc": _utc_now_iso(),
                            "url": str(getattr(response, "url", "") or ""),
                            "method": str(getattr(request, "method", "") or ""),
                            "status": int(getattr(response, "status", 0) or 0),
                            "resource_type": str(getattr(request, "resource_type", "") or ""),
                            "content_type": content_type,
                            "body_preview": body_preview,
                        }
                    )
                except Exception:
                    return

            page.on("response", on_response)

            url = "https://www.gebiz.gov.sg/ptn/opportunity/BOAdvancedSearch.xhtml?origin=advanced"
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(5000)

            q = str(query_text or "").strip()
            if q:
                try:
                    page.locator("input[type='text']").first.fill(q)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
                except Exception:
                    pass

            browser.close()
        except Exception as exc:
            error_message = f"playwright_error: {exc}"

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
        artifact_path, record_count, error = discover_endpoints_playwright(
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
                normalized_df = fetch_bolisting_playwright(
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
