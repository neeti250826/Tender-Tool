#!/usr/bin/env python3
"""
collect_tender_urls_final.py

Connects to an already-open Edge browser via CDP, runs advanced search, and collects
project_no + encrypted detail_url records from the listing pages.

Start Edge first:
"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" ^
--remote-debugging-port=9222 ^
--user-data-dir="C:\\gproc-clean-profile" ^
--disable-extensions
"""

import asyncio
import csv
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Page

BASE_URL = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement"
CDP_URL = "http://127.0.0.1:9222"
BE_OFFSET = 543
STATE_FILE = "collector_state.json"
OUTPUT_COLUMNS = [
    "project_no",
    "detail_url",
    "title",
    "amount",
    "status",
    "publication_date",
    "raw_text",
    "collected_at",
]

SAFE_BROWSER_HEADERS = {
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    ),
}

FIELD_VALUE_ALIASES = {
    "packages_supplied": {
        "scientific & medical supplies": [
            "วัสดุครุภัณฑ์วิทยาศาสตร์และการแพทย์",
            "วิทยาศาสตร์และการแพทย์",
            "Scientific & Medical Supplies",
        ]
    }
}

CLOUDFLARE_FAIL_MARKERS = [
    "Cloudflare : ไม่ผ่านการตรวจสอบของ Cloudflare",
    "ไม่ผ่านการตรวจสอบของ Cloudflare",
]

SYSTEM_ERROR_MARKERS = [
    "เกิดข้อผิดพลาด",
    "ระบบเกิดข้อผิดพลาด",
    "มีข้อผิดพลาดในระบบ",
    "กรุณาตรวจสอบ",
    "error in the system",
    "please check",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_completed_cycle": 0}


def save_state(last_completed_cycle: int) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "last_completed_cycle": last_completed_cycle,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

async def click_next_for_skip(page: Page) -> bool:
    """
    Bare-minimum Next click for resume skipping only.
    Does NOT check project numbers — just clicks Next and waits briefly.
    Returns False only if the button is missing or disabled.
    """
    try:
        next_btn = page.locator(
            ".p-paginator-next, "
            "button:has-text('ถัดไป'), "
            "a:has-text('ถัดไป'), "
            "button:has-text('Next'), "
            "a:has-text('Next')"
        ).last

        if await next_btn.count() == 0:
            log.warning("Skip-mode: Next button not found.")
            return False

        disabled = await next_btn.evaluate(
            "el => el.disabled || el.getAttribute('disabled') !== null || "
            "el.getAttribute('aria-disabled') === 'true' || "
            "el.classList.contains('disabled') || el.classList.contains('p-disabled')"
        )
        if disabled:
            log.warning("Skip-mode: Next button is disabled.")
            return False

        await next_btn.scroll_into_view_if_needed()
        await next_btn.click(force=True)
        await page.wait_for_timeout(3000)
        return True

    except Exception as e:
        log.warning("Skip-mode next click failed: %s", e)
        return False


async def advance_to_cycle(page: Page, target_cycle: int, delay_ms: int) -> int:
    """
    Resume navigation: click Next (target_cycle - 1) times as fast as possible.
    Uses a bare-minimum clicker that skips all content validation.
    """
    if target_cycle <= 1:
        return 1

    log.info("Resume: fast-skipping to page %d (clicking Next %d times)...",
             target_cycle, target_cycle - 1)

    current_cycle = 1
    consecutive_failures = 0

    while current_cycle < target_cycle:
        log.info("Resume skip: window %d / %d", current_cycle, target_cycle - 1)
        moved = await go_to_next_page(page)
        if moved:
            current_cycle += 1
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                log.warning(
                    "Next button failed 3 times in a row at page %d. "
                    "Collecting from here instead.", current_cycle
                )
                break
            await page.wait_for_timeout(3000)

    log.info("Resume complete. Now at window %d", current_cycle)
    return current_cycle

def thai_date_to_iso(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text)
    if not m:
        return ""
    day, month, year = map(int, m.groups())
    if year > 2400:
        year -= BE_OFFSET
    return f"{year:04d}-{month:02d}-{day:02d}"


def expand_value_candidates(field_name: str, value: str) -> list[str]:
    aliases = FIELD_VALUE_ALIASES.get(field_name, {}).get(value.strip().casefold(), [])
    candidates = [value, *aliases]
    seen = set()
    out = []
    for candidate in candidates:
        key = candidate.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


async def page_body_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


async def wait_for_page_settle(page: Page, ms: int = 2000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(ms)


async def first_visible(locator):
    for idx in range(await locator.count()):
        item = locator.nth(idx)
        try:
            if await item.is_visible():
                return item
        except Exception:
            pass
    return None


async def is_cloudflare_failed(page: Page) -> bool:
    body = await page_body_text(page)
    return any(marker in body for marker in CLOUDFLARE_FAIL_MARKERS)


async def is_system_error_page(page: Page) -> bool:
    body = await page_body_text(page)
    lower = body.lower()
    return any(marker.lower() in lower for marker in SYSTEM_ERROR_MARKERS)


async def check_portal_health(page: Page, context: str = "") -> None:
    if await is_cloudflare_failed(page):
        raise RuntimeError(
            f"Cloudflare verification failed {context}. "
            "Keep Edge open, solve/clear Cloudflare manually, then rerun."
        )

    if await is_system_error_page(page):
        raise RuntimeError(
            f"Portal system error detected {context}."
        )


async def create_context(pw):
    log.info("Connecting to existing Edge browser on CDP port 9222")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    if not browser.contexts:
        raise RuntimeError("No browser context found. Start Edge with --remote-debugging-port=9222 first.")
    context = browser.contexts[0]
    await context.set_extra_http_headers(SAFE_BROWSER_HEADERS)
    return browser, context


async def get_existing_or_new_page(context):
    for p in context.pages:
        try:
            if "gprocurement.go.th" in p.url:
                return p
        except Exception:
            pass
    return context.pages[0] if context.pages else await context.new_page()


async def wait_for_cloudflare(page: Page, timeout: int = 180):
    log.info("Checking for Cloudflare/search readiness...")
    start = datetime.now().timestamp()
    while datetime.now().timestamp() - start < timeout:
        await check_portal_health(page, "while waiting for search page")
        search_ready = False
        try:
            btn = page.locator("button:has-text('ค้นหา')").first
            search_ready = await btn.count() > 0 and await btn.is_visible() and await btn.is_enabled()
        except Exception:
            pass
        if search_ready:
            log.info("Search page ready.")
            return
        await page.wait_for_timeout(3000)
    raise TimeoutError("Search page not ready within timeout.")


async def fill_date_input(locator, value: str):
    await locator.scroll_into_view_if_needed()
    await locator.click(force=True)
    await locator.fill("")
    await locator.type(value, delay=40)
    await locator.press("Tab")


async def find_advanced_modal(page: Page):
    modal = page.locator("[role='dialog'][aria-hidden='false'], .modal.show").first
    if await modal.count() > 0:
        return modal
    return page


async def select_dropdown(page: Page, scope, labels: list[str], value: str) -> None:
    try:
        select = None
        for label in labels:
            candidate = scope.locator(
                "xpath=("
                f"//*[contains(normalize-space(.), {json.dumps(label)})]"
                "/following::*[self::ng-select or contains(@class,'ng-select')][1]"
                ")[1]"
            ).first
            if await candidate.count() > 0:
                select = candidate
                break
        if select is None:
            raise RuntimeError(f"dropdown not found for labels={labels}")
        await select.click(force=True)
        await page.wait_for_timeout(700)
        option = page.locator(f".ng-dropdown-panel .ng-option:has-text('{value}'), text='{value}'").first
        await option.click(force=True)
        await page.wait_for_timeout(700)
    except Exception as e:
        log.warning("Dropdown %s -> %r failed: %s", labels, value, e)


async def apply_filters(page: Page, filters: dict):
    if not filters:
        return
    scope = page
    adv_btn = page.locator("button:has-text('ค้นหาขั้นสูง'), button:has-text('Advanced')")
    visible_adv = await first_visible(adv_btn) if await adv_btn.count() else None
    if visible_adv:
        await visible_adv.click(force=True)
        await page.wait_for_timeout(1500)
        scope = await find_advanced_modal(page)

    if filters.get("packages_supplied"):
        try:
            pkg_values = expand_value_candidates("packages_supplied", filters["packages_supplied"])
            pkg_select = scope.locator(
                "xpath=(//*[contains(normalize-space(.), 'พัสดุที่จัดหา') or "
                "contains(normalize-space(.), 'Packages supplied')]"
                "/following::*[self::ng-select or contains(@class,'ng-select')][1])[1]"
            ).first
            if await pkg_select.count() == 0:
                pkg_select = scope.locator("ng-select").nth(4)
            await pkg_select.click(force=True)
            await page.wait_for_timeout(700)
            pkg_input = pkg_select.locator("input").first
            chosen = False
            for candidate in pkg_values:
                if await pkg_input.count() > 0:
                    await pkg_input.fill(candidate)
                else:
                    await page.keyboard.type(candidate)
                await page.wait_for_timeout(1000)
                option = page.locator(
                    f".ng-dropdown-panel .ng-option:has-text('{candidate}'), .ng-option:has-text('{candidate}')"
                ).first
                if await option.count() > 0:
                    await option.click(force=True)
                    chosen = True
                    await page.wait_for_timeout(700)
                    break
            if not chosen:
                raise RuntimeError("Packages supplied option not found")
        except Exception as e:
            log.warning("packages_supplied filter failed: %s", e)

    if filters.get("project_type"):
        await select_dropdown(page, scope, ["ประเภทโครงการ", "Project Type", "project type"], filters["project_type"])
    if filters.get("announcement_type"):
        await select_dropdown(page, scope, ["ประเภทประกาศ", "Announcement Type", "listing type"], filters["announcement_type"])
    if filters.get("project_status"):
        await select_dropdown(page, scope, ["สถานะโครงการ", "Project Status", "project status"], filters["project_status"])

    if filters.get("date_from") or filters.get("date_to"):
        date_inputs = scope.locator(
            "input[placeholder*='วว/ดด/ปปปป'], input[placeholder*='dd/mm'], input[placeholder*='DD/MM']"
        )
        visible = []
        for i in range(await date_inputs.count()):
            item = date_inputs.nth(i)
            try:
                if await item.is_visible():
                    visible.append(item)
            except Exception:
                pass
        if filters.get("date_from") and visible:
            await fill_date_input(visible[0], filters["date_from"])
        if filters.get("date_to") and len(visible) > 1:
            await fill_date_input(visible[1], filters["date_to"])


async def wait_for_result_rows(page: Page, timeout: int = 45000):
    log.info("Waiting for result rows...")
    await page.wait_for_timeout(4000)
    row_locator = page.locator(
        "tr:has-text('เลขที่โครงการ'), [role='row']:has-text('เลขที่โครงการ'), tr:has-text('ไม่พบข้อมูล')"
    ).first
    await row_locator.wait_for(state="visible", timeout=timeout)
    for _ in range(6):
        await page.mouse.wheel(0, 700)
        await page.wait_for_timeout(700)
    await page.mouse.wheel(0, -4000)
    await page.wait_for_timeout(1500)
    await check_portal_health(page, "after result rows loaded")


async def run_search(page: Page, query_text: str, filters: dict):
    if BASE_URL not in page.url:
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_page_settle(page, 3000)
    await wait_for_cloudflare(page)
    search_input = page.locator("input[placeholder*='ระบุ ชื่อโครงการ'], input[placeholder*='project']").first
    if await search_input.count() > 0:
        await search_input.fill(query_text or "")
    await apply_filters(page, filters)
    try:
        await page.mouse.wheel(0, -5000)
        await page.wait_for_timeout(1000)
    except Exception:
        pass
    scope = await find_advanced_modal(page)
    search_btn = None
    for _ in range(30):
        for loc in [
            scope.locator("button:has-text('ค้นหา')"),
            page.locator("button:has-text('ค้นหา')"),
            scope.locator("button:has-text('Search')"),
            page.locator("button:has-text('Search')"),
        ]:
            btn = await first_visible(loc)
            if btn and await btn.is_enabled():
                search_btn = btn
                break
        if search_btn:
            break
        await page.wait_for_timeout(500)
    if not search_btn:
        raise RuntimeError("Search button not available.")
    await search_btn.scroll_into_view_if_needed()
    await search_btn.click(force=True)
    log.info("Search submitted.")
    await wait_for_result_rows(page)


async def get_total_results(page: Page) -> int:
    body = await page_body_text(page)
    m = re.search(r"จำนวนโครงการที่พบ\s*:\s*(?:มากกว่า\s*)?([\d,]+)\s*โครงการ", body)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"(?:มากกว่า\s*)?([\d,]+)\s*โครงการ", body)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0


async def parse_listing_row_text(txt: str) -> dict | None:
    m = re.search(r"เลขที่โครงการ\s*:\s*(\d+)", txt)
    if not m:
        return None
    project_no = m.group(1)
    amount_match = re.search(r"([\d,]+\.\d{2})", txt)
    amount = amount_match.group(1).replace(",", "") if amount_match else ""
    status = txt[amount_match.end():].replace("article", "").strip() if amount_match else ""
    title = re.sub(r"^\s*\d+\s+", "", txt)
    title = re.sub(r"\(เลขที่โครงการ\s*:\s*\d+\)", "", title)
    title = re.sub(r"[\d,]+\.\d{2}", "", title).replace("article", "")
    if status:
        title = title.replace(status, "")
    title = re.sub(r"\s+", " ", title).strip()
    date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", txt)
    return {
        "project_no": project_no,
        "title": title,
        "amount": amount,
        "status": status,
        "publication_date": thai_date_to_iso(date_match.group(1)) if date_match else "",
        "raw_text": txt,
    }


async def get_visible_listing_rows(page: Page) -> list[dict]:
    for _ in range(10):
        await page.mouse.wheel(0, 700)
        await page.wait_for_timeout(500)
    await page.mouse.wheel(0, -6000)
    await page.wait_for_timeout(1500)
    row_locator = page.locator("table tbody tr")
    row_infos = []
    for i in range(await row_locator.count()):
        row = row_locator.nth(i)
        try:
            txt = (await row.inner_text()).strip()
            if "เลขที่โครงการ" not in txt:
                continue
            parsed = await parse_listing_row_text(txt)
            if parsed:
                row_infos.append(parsed)
        except Exception:
            pass
    return row_infos


async def capture_detail_url_from_listing_new_tab(page: Page, project_no: str) -> str:
    context = page.context
    detail_url = ""
    row = page.locator(f"table tbody tr:has-text('{project_no}'), [role='row']:has-text('{project_no}')").first
    await row.wait_for(state="visible", timeout=15000)
    await row.evaluate("(el) => el.scrollIntoView({block: 'center'})")
    await page.wait_for_timeout(700)
    cells = row.locator("td, [role='cell']")
    cell_count = await cells.count()
    last_cell = cells.nth(cell_count - 1) if cell_count else row
    target = last_cell.locator(
        "a[href], button, [role='button'], mat-icon, .mat-icon, i, svg, img, .pi, [class*='icon']"
    ).last
    if await target.count() == 0:
        return ""
    await page.evaluate("""
        () => {
            window.__capturedTenderUrls = [];
            if (!window.__origPushState) window.__origPushState = history.pushState;
            if (!window.__origReplaceState) window.__origReplaceState = history.replaceState;
            history.pushState = function(state, title, url) {
                if (url) {
                    const full = new URL(url, location.href).href;
                    if (full.includes('/announcement/procurement/')) {
                        window.__capturedTenderUrls.push(full);
                        window.open(full, '_blank');
                        throw new Error('__OPENED_TENDER_IN_NEW_TAB__');
                    }
                }
                return window.__origPushState.apply(this, arguments);
            };
            history.replaceState = function(state, title, url) {
                if (url) {
                    const full = new URL(url, location.href).href;
                    if (full.includes('/announcement/procurement/')) {
                        window.__capturedTenderUrls.push(full);
                        window.open(full, '_blank');
                        throw new Error('__OPENED_TENDER_IN_NEW_TAB__');
                    }
                }
                return window.__origReplaceState.apply(this, arguments);
            };
        }
    """)
    new_page = None
    try:
        try:
            async with context.expect_page(timeout=5000) as popup_info:
                try:
                    await target.evaluate("(el) => el.click()")
                except Exception:
                    pass
            new_page = await popup_info.value
            await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
            await new_page.wait_for_timeout(1500)
            if "/announcement/procurement/" in new_page.url:
                detail_url = new_page.url
        except Exception:
            urls = await page.evaluate("() => window.__capturedTenderUrls || []")
            valid_urls = [u for u in urls if "/announcement/procurement/" in u]
            if valid_urls:
                detail_url = valid_urls[-1]
    finally:
        try:
            await page.evaluate("""
                () => {
                    if (window.__origPushState) history.pushState = window.__origPushState;
                    if (window.__origReplaceState) history.replaceState = window.__origReplaceState;
                }
            """)
        except Exception:
            pass
        if new_page:
            try:
                await new_page.close()
            except Exception:
                pass
    return detail_url


async def capture_with_retry(page: Page, parsed: dict, retries: int = 3) -> dict:
    project_no = parsed["project_no"]
    for attempt in range(1, retries + 1):
        try:
            url = await capture_detail_url_from_listing_new_tab(page, project_no)
            if url and "/announcement/procurement/" in url:
                parsed["detail_url"] = url
                parsed["collected_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                log.info("Collected %s -> %s", project_no, url)
                return parsed
            log.warning("No URL for %s on attempt %d/%d", project_no, attempt, retries)
        except Exception as e:
            log.warning("URL capture failed for %s attempt %d/%d: %s", project_no, attempt, retries, e)
        await page.wait_for_timeout(2000 * attempt)
    parsed["detail_url"] = ""
    parsed["collected_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.warning("Collected %s -> NO_URL", project_no)
    return parsed


async def collect_urls_for_new_rows(page: Page, new_candidates: list[dict], parallelism: int = 1) -> list[dict]:
    # Safe default: 1. This portal is unstable if multiple workers mutate the same listing tab.
    if parallelism <= 1:
        out = []
        for parsed in new_candidates:
            out.append(await capture_with_retry(page, parsed))
            await page.wait_for_timeout(1200)
        return out
    sem = asyncio.Semaphore(parallelism)
    async def worker(item):
        async with sem:
            return await capture_with_retry(page, item)
    return await asyncio.gather(*[worker(item) for item in new_candidates])

async def cooldown_until_portal_recovers(page: Page, context: str = "") -> bool:
    if await is_cloudflare_failed(page):
        raise RuntimeError(
            f"Cloudflare verification failed {context}. "
            "Clear it manually in Edge, then rerun."
        )

    if not await is_system_error_page(page):
        return True

    log.warning("Portal system error detected %s. Cooling down without refresh.", context)

    for sec in [60, 120, 180, 300]:
        log.info("Cooling down for %s seconds...", sec)
        await page.wait_for_timeout(sec * 1000)

        if await is_cloudflare_failed(page):
            raise RuntimeError(
                f"Cloudflare verification failed {context}. "
                "Clear it manually in Edge, then rerun."
            )

        if not await is_system_error_page(page):
            log.info("Portal recovered after cooldown.")
            return True

    log.warning("Portal did not recover after cooldown.")
    return False

async def go_to_next_page(page: Page, allow_cooldown: bool = True) -> bool:
    try:
        before_body = await page_body_text(page)
        before_projects = set(re.findall(r"เลขที่โครงการ\s*:\s*(\d+)", before_body))

        next_btn = page.locator(
            "button:has-text('ถัดไป'), "
            "a:has-text('ถัดไป'), "
            "button:has-text('Next'), "
            "a:has-text('Next'), "
            "button[aria-label*='next'], "
            "button[aria-label*='Next'], "
            ".p-paginator-next, "
            ".pagination .next:not(.disabled)"
        ).last

        if await next_btn.count() == 0:
            log.info("Next button not found.")
            return False

        disabled = await next_btn.evaluate("""
            el => el.disabled ||
                  el.getAttribute('disabled') !== null ||
                  el.getAttribute('aria-disabled') === 'true' ||
                  el.classList.contains('disabled') ||
                  el.classList.contains('p-disabled')
        """)

        if disabled:
            log.info("Next button disabled. Finished pagination.")
            return False

        await next_btn.scroll_into_view_if_needed()
        await page.wait_for_timeout(2500)

        log.info("Clicking next page...")
        await next_btn.click(force=True)

        # Wait for same Angular page to update.
        try:
            await page.wait_for_function(
                """
                (oldProjects) => {
                    const body = document.body.innerText || '';
                    const matches = [...body.matchAll(/เลขที่โครงการ\\s*:\\s*(\\d+)/g)].map(m => m[1]);

                    if (matches.length === 0) return false;

                    const oldSet = new Set(oldProjects);
                    const changed = matches.some(x => !oldSet.has(x)) || matches.length !== oldProjects.length;

                    return changed;
                }
                """,
                list(before_projects),
                timeout=30000,
            )
        except Exception:
            log.warning("Next clicked, but listing rows did not visibly change within timeout.")

        # Extra wait for Angular to finish rendering the new page rows
        await page.wait_for_timeout(12000)
        # Wait until body has actual project content or known empty marker
        try:
            await page.wait_for_function(
                """() => {
                    const t = document.body.innerText || '';
                    return t.includes('เลขที่โครงการ') || t.includes('ไม่พบข้อมูล');
                }""",
                timeout=20000,
            )
        except Exception:
            pass

        if await is_cloudflare_failed(page):
            raise RuntimeError(
                "Cloudflare verification failed after next-page click. "
                "Clear it manually in Edge, then rerun."
            )

        if await is_system_error_page(page):
            if not allow_cooldown:
                return False

            recovered = await cooldown_until_portal_recovers(page, "after next-page click")
            if not recovered:
                return False

        try:
            await wait_for_result_rows(page, timeout=60000)
        except Exception as e:
            log.warning("Rows not ready after next-page click: %s", e)
            return False

        after_body = await page_body_text(page)
        after_projects = set(re.findall(r"เลขที่โครงการ\s*:\s*(\d+)", after_body))

        # Only block if projects are identical AND the page indicator hasn't moved.
        # When all rows are already-seen we still want to advance — the content
        # may legitimately look the same from a project_no perspective if the
        # site reuses numbers across filter sets, but the paginator position
        # will have changed. We check the active page button to confirm movement.
        if before_projects and after_projects and before_projects == after_projects:
            # Double-check: did the active page number actually change?
            try:
                active_page = await page.evaluate("""
                    () => {
                        const active = document.querySelector(
                            '.p-paginator-page.p-highlight, '
                            '.p-paginator-page[aria-current="page"], '
                            'li.page-item.active a.page-link'
                        );
                        return active ? parseInt(active.innerText.trim(), 10) : null;
                    }
                """)
                log.info("Active paginator page after next click: %s", active_page)
            except Exception:
                active_page = None

            if active_page is None:
                # Can't confirm — assume we advanced
                log.info("Could not read active page number; assuming advance succeeded.")
            else:
                log.warning("Next page still shows same project numbers (active page=%s). Not advancing.", active_page)
                return False

        log.info("After next click body preview: %s", after_body[:500])
        return True

    except Exception as e:
        log.warning("Next page failed: %s", e)
        return False


def load_existing(path: str) -> set[str]:
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return {r["project_no"] for r in csv.DictReader(f) if r.get("project_no")}
    except FileNotFoundError:
        return set()


def append_rows(path: str, rows: list[dict]) -> list[dict]:
    existing = load_existing(path)
    new_rows = [r for r in rows if r.get("project_no") and r["project_no"] not in existing]
    log.info("Rows received for writing: %d", len(rows))
    log.info("Existing project_nos in file: %d", len(existing))
    log.info("New project_nos to write: %d", len(new_rows))
    log.info("New project_nos: %s", [r["project_no"] for r in new_rows])
    if not new_rows:
        return []
    file_exists = Path(path).exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for row in new_rows:
            writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})
    return new_rows


async def soft_session_cooldown(page: Page, collected_count: int):
    # Do not clear cookies or rotate UA; that can make Cloudflare worse.
    if collected_count > 0 and collected_count % 30 == 0:
        log.info("Soft cooldown after %d collected tenders...", collected_count)
        await page.wait_for_timeout(60000)


async def collect_tender_urls(
    query_text: str,
    filters: dict,
    output_csv: str,
    delay_ms: int,
    max_cycles: int,
    no_new_limit: int,
    parallelism: int,
    start_page: int = 0,
):
    async with async_playwright() as pw:
        browser, context = await create_context(pw)
        page = await get_existing_or_new_page(context)
        await wait_for_cloudflare(page)
        await run_search(page, query_text, filters)

        if start_page > 0:
            # Manual override: ignore state file entirely, go straight to requested page
            log.info("--start-page=%d specified: ignoring state file, navigating directly to page %d",
                     start_page, start_page)
            resume_cycle = start_page
        else:
            state = load_state()
            resume_cycle = state.get("last_completed_cycle", 0) + 1
            log.info("Resume state: last_completed_cycle=%s, starting at window=%s",
                     state.get("last_completed_cycle", 0), resume_cycle)

        cycle = await advance_to_cycle(page, resume_cycle, delay_ms)
        total = await get_total_results(page)
        log.info("Total results detected: %s", total or "unknown")

        seen_projects = set(load_existing(output_csv))
        log.info("Loaded %d already-collected project_nos from CSV.", len(seen_projects))
        no_new_count = 0

        while cycle <= max_cycles:
            log.info("-- Collect cycle/window %d --", cycle)
            await wait_for_result_rows(page)
            row_infos = await get_visible_listing_rows(page)
            log.info("Visible listing rows: %d", len(row_infos))
            if not row_infos:
                body = await page_body_text(page)
                log.warning("No visible rows. Body preview: %s", body[:1000])
                break
            log.info("Visible project_nos on page %d: %s", cycle, [r["project_no"] for r in row_infos])
            log.info("Already in CSV on this page: %s",
                     [r["project_no"] for r in row_infos if r["project_no"] in seen_projects])
            new_candidates = [row for row in row_infos if row["project_no"] not in seen_projects]

            if not new_candidates:
                log.info("Page %d fully collected (%d rows), moving to next verified page...", cycle, len(row_infos))
                no_new_count += 1

                save_state(cycle)

                if no_new_count >= no_new_limit:
                    log.info("No new tenders for %d consecutive windows. Stopping.", no_new_limit)
                    break

                moved = await go_to_next_page(page)
                if not moved:
                    log.info("No more pages.")
                    break

                cycle += 1
                continue

            no_new_count = 0
            log.info("Page %d has %d new rows — collecting...", cycle, len(new_candidates))
            for row in new_candidates:
                seen_projects.add(row["project_no"])
            captured_rows = await collect_urls_for_new_rows(page, new_candidates, parallelism=parallelism)
            new_written = append_rows(output_csv, captured_rows)
            log.info("Written new rows this cycle: %d", len(new_written))
            save_state(cycle)
            log.info("Saved resume state: completed window %d", cycle)
            await soft_session_cooldown(page, len(seen_projects))
            await page.wait_for_timeout(delay_ms)
            moved = await go_to_next_page(page)
            if not moved:
                log.info("No more pages/windows or navigation stopped.")
                break
            cycle += 1
            await page.wait_for_timeout(delay_ms)
        log.info("Collection finished. Unique seen/file total: %d", len(seen_projects))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Collect Thailand GProcurement tender detail URLs")
    parser.add_argument("--query", default="")
    parser.add_argument("--packages-supplied", default="Scientific & Medical Supplies")
    parser.add_argument("--date-from", default="01/01/2567")
    parser.add_argument("--date-to", default="27/04/2569")
    parser.add_argument("--project-type", default="")
    parser.add_argument("--announcement-type", default="")
    parser.add_argument("--project-status", default="")
    parser.add_argument("--output-csv", default="tender_urls.csv")
    parser.add_argument("--delay-ms", type=int, default=20000)
    parser.add_argument("--max-cycles", type=int, default=20)
    parser.add_argument("--no-new-limit", type=int, default=3)
    parser.add_argument("--start-page", type=int, default=0,
                        help="Skip state file and start scraping from this page number directly. "
                             "0 means use state file as normal.")
    parser.add_argument("--parallelism", type=int, default=1)
    args = parser.parse_args()
    filters = {
        "packages_supplied": args.packages_supplied,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "project_type": args.project_type,
        "announcement_type": args.announcement_type,
        "project_status": args.project_status,
    }
    filters = {k: v for k, v in filters.items() if v}
    asyncio.run(
        collect_tender_urls(
            query_text=args.query,
            filters=filters,
            output_csv=args.output_csv,
            delay_ms=args.delay_ms,
            max_cycles=args.max_cycles,
            no_new_limit=args.no_new_limit,
            parallelism=args.parallelism,
            start_page=args.start_page,
        )
    )