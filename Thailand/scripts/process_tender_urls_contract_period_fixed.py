#!/usr/bin/env python3
"""
process_tender_urls.py
Phase 2: read tender_urls.csv, open each saved detail_url, extract tender + contract/item data.
Skips processed_tenders.txt. If saved URL fails, searches exact project_no.
"""

import asyncio
import csv
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright, Page

try:
    from deep_translator import GoogleTranslator
except ModuleNotFoundError:
    GoogleTranslator = None

BASE_URL = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement"
CDP_URL = "http://127.0.0.1:9222"
BE_OFFSET = 543
URL_QUEUE_FILE = "tender_urls.csv"
PROCESSED_FILE = "processed_tenders.txt"
FAILED_FILE = "failed_tenders.txt"

CONTRACT_MATERIAL_LABELS = ["ข้อมูลสาระสำคัญในสัญญา", "Contract Material Information", "contract material information"]
SYSTEM_ERROR_MARKERS = ["เกิดข้อผิดพลาด", "ระบบเกิดข้อผิดพลาด", "มีข้อผิดพลาดในระบบ", "กรุณาตรวจสอบ", "error in the system", "please check", "ไม่ผ่านการตรวจสอบของ Cloudflare"]

OUTPUT_COLUMNS = [
    "source", "country", "country_code", "publication_date", "closing_date", "title", "title_en", "buyer", "buyer_en",
    "classification", "classification_en", "status", "status_en", "currency", "amount",
    "awarding_agency_name", "awarding_agency_name_en", "supplier_name", "supplier_name_en",
    "awarded_date", "awarded_value_detail", "contract_period", "bid_number", "item_no",
    "item_description", "item_description_en", "item_unit_price", "item_awarded_value",
    "notice_id", "notice_url", "scraped_at_utc", "dedup_key",
]

SAFE_BROWSER_HEADERS = {
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)
translator = GoogleTranslator(source="th", target="en") if GoogleTranslator else None
_translate_cache = {}

async def extract_contract_period_from_contract_tab(page: Page) -> str:
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(1000)

    before_body = await page_body_text(page)

    clicked = await click_contract_information_tab(page)

    if not clicked:
        log.warning("Contract Information tab not found or did not load")
        return ""

    # Important: Angular changes content in the SAME tab/page.
    # Wait until old contract-material body disappears OR contract-info fields appear.
    try:
        await page.wait_for_function(
            """
            () => {
                const body = document.body.innerText || '';
                return (
                    body.includes('ข้อมูลสาระสำคัญในสัญญา') &&
                    body.includes('เลขคุมสัญญาในระบบ e-GP') &&
                    body.includes('วันที่ทำสัญญา/ใบสั่งซื้อ')
                );
            }
            """,
            timeout=20000,
        )
    except Exception:
        log.warning("Contract tab click happened but contract table did not load within timeout")

    await page.wait_for_timeout(5000)

    body = await page_body_text(page)
    log.info("Contract tab FULL body after wait:\n%s", body)

    # Prefer explicit contract date range first
    date_range = re.search(
        r"(\d{1,2}/\d{1,2}/\d{4})\s*(?:ถึง|-|–)\s*(\d{1,2}/\d{1,2}/\d{4})",
        body
    )
    if date_range:
        start_iso = thai_date_to_iso(date_range.group(1))
        end_iso = thai_date_to_iso(date_range.group(2))
        if start_iso and end_iso:
            from datetime import datetime
            d1 = datetime.strptime(start_iso, "%Y-%m-%d")
            d2 = datetime.strptime(end_iso, "%Y-%m-%d")
            days = (d2 - d1).days
            if days > 0:
                return f"{days} days"

    patterns = [
        r"(?:ระยะเวลาสัญญา|ระยะเวลาดำเนินการ|กำหนดส่งมอบ|ระยะเวลา)[^\n\r:：]*[:：]?\s*([1-9]\d*\s*(?:วัน|เดือน|ปี|days?|months?|years?))",
        r"\(([1-9]\d*\s*(?:days?|วัน|เดือน|months?|ปี|years?))\)",
    ]

    for p in patterns:
        m = re.search(p, body, re.I)
        if m:
            val = re.sub(r"\s+", " ", m.group(1)).strip()
            if not val.startswith("0 "):
                return val

    return ""


def extract_date_range_contract_period(body: str) -> str:
    match = re.search(
        r"(\d{1,2}/\d{1,2}/\d{4})\s*(?:ถึง|-|–)\s*(\d{1,2}/\d{1,2}/\d{4})(?:\s*\((\d+)\s*วัน\))?",
        body,
    )
    if not match:
        return ""
    if match.group(3):
        return f"{match.group(3)} days"

    start_iso = thai_date_to_iso(match.group(1))
    end_iso = thai_date_to_iso(match.group(2))
    if not start_iso or not end_iso:
        return ""

    d1 = datetime.strptime(start_iso, "%Y-%m-%d")
    d2 = datetime.strptime(end_iso, "%Y-%m-%d")
    days = (d2 - d1).days
    return f"{days} days" if days > 0 else ""


def extract_contract_tab_dates(body: str) -> dict:
    info = {"publication_date": "", "closing_date": "", "contract_period": ""}

    match = re.search(r"(?:วันที่ประกาศ|วันประกาศ|ประกาศ ณ วันที่|Announced Date)[^\d]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})", body, re.I)
    if match:
        info["publication_date"] = thai_date_to_iso(match.group(1))

    match = re.search(r"(?:วันที่สิ้นสุด|วันสิ้นสุด|Closing Date|End Date)[^\d]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})", body, re.I)
    if match:
        info["closing_date"] = thai_date_to_iso(match.group(1))

    if not info["publication_date"] or not info["closing_date"]:
        all_dates = [thai_date_to_iso(value) for value in re.findall(r"\d{1,2}/\d{1,2}/\d{4}", body)]
        all_dates = [value for value in all_dates if value]
        unique_dates = list(dict.fromkeys(all_dates))
        if not info["publication_date"] and unique_dates:
            info["publication_date"] = unique_dates[0]
        if not info["closing_date"] and len(unique_dates) > 1:
            info["closing_date"] = unique_dates[1]

    section_match = re.search(
        r"(?:วันที่เริ่มต้น-สิ้นสุดสัญญา|ระยะเวลาสัญญา|ระยะเวลาดำเนินการ)[\s\S]{0,120}?(\d{1,2}/\d{1,2}/\d{4}\s*(?:ถึง|-|–)\s*\d{1,2}/\d{1,2}/\d{4}(?:\s*\(\d+\s*วัน\))?)",
        body,
        re.I,
    )
    if section_match:
        info["contract_period"] = extract_date_range_contract_period(section_match.group(1))

    if not info["contract_period"]:
        info["contract_period"] = extract_date_range_contract_period(body)

    if not info["contract_period"]:
        for pattern in [
            r"(?:ระยะเวลาสัญญา|ระยะเวลาดำเนินการ|กำหนดส่งมอบ|ระยะเวลา)[^\n\r:：]*[:：]?\s*([1-9]\d*\s*(?:วัน|เดือน|ปี|days?|months?|years?))",
            r"\(([1-9]\d*\s*(?:days?|วัน|เดือน|months?|ปี|years?))\)",
        ]:
            match = re.search(pattern, body, re.I)
            if match:
                info["contract_period"] = re.sub(r"\s+", " ", match.group(1)).strip()
                break

    return info


async def extract_contract_info_from_contract_tab(page: Page) -> dict:
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(1000)

    clicked = await click_contract_information_tab(page)
    if not clicked:
        log.warning("Contract Information tab not found or did not load")
        return {"publication_date": "", "closing_date": "", "contract_period": ""}

    body = await page_body_text(page)
    if any(
        marker in body
        for marker in [
            "ข้อมูลสัญญาและการบริหารสัญญา",
            "วันที่เริ่มต้น-สิ้นสุดสัญญา",
            "วันที่ประกาศ",
            "วันที่สิ้นสุด",
        ]
    ):
        log.info("Contract tab content detected immediately after click")
        info = extract_contract_tab_dates(body)
        if info["contract_period"] and (info["publication_date"] or info["closing_date"]):
            return info

    try:
        await page.wait_for_function(
            """
            () => {
                const body = document.body.innerText || '';
                return (
                    body.includes('ข้อมูลสาระสำคัญในสัญญา') &&
                    body.includes('เลขคุมสัญญาในระบบ e-GP') &&
                    body.includes('วันที่ทำสัญญา/ใบสั่งซื้อ')
                );
            }
            """,
            timeout=20000,
        )
    except Exception:
        log.warning("Contract tab click happened but contract table did not load within timeout")

    await page.wait_for_timeout(5000)
    body = await page_body_text(page)
    log.info("Contract tab FULL body after wait:\n%s", body)
    return extract_contract_tab_dates(body)

def translate_th_to_en(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    if translator is None:
        return ""
    if text in _translate_cache:
        return _translate_cache[text]
    try:
        out = translator.translate(text)
    except Exception as e:
        log.warning("Translation failed for %r: %s", text[:80], e)
        out = ""
    _translate_cache[text] = out
    return out


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


def make_dedup_key(*parts) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(str(p) for p in parts if p)))


def empty_row() -> dict:
    return {col: "" for col in OUTPUT_COLUMNS}


async def page_body_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


async def wait_for_page_settle(page: Page, ms: int = 2000):
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(ms)


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


async def is_bad_page(page: Page) -> bool:
    body = await page_body_text(page)
    low = body.lower()
    return any(m.lower() in low for m in SYSTEM_ERROR_MARKERS)


async def wait_or_raise_bad_page(page: Page, project_no: str = ""):
    if not await is_bad_page(page):
        return
    log.warning("Portal/Cloudflare error detected for %s. Cooling down without refresh.", project_no)
    for seconds in [60, 120, 180]:
        log.info("Cooling down for %s seconds...", seconds)
        await page.wait_for_timeout(seconds * 1000)
        if not await is_bad_page(page):
            log.info("Portal/Cloudflare error cleared.")
            return
    raise RuntimeError(f"Portal/Cloudflare error still active for {project_no}. Clear manually in Edge, then rerun.")


def load_queue(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_processed(path: str = PROCESSED_FILE) -> set[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


def mark_processed(project_no: str):
    with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
        f.write(project_no + "\n")


def mark_failed(project_no: str, reason: str):
    with open(FAILED_FILE, "a", encoding="utf-8") as f:
        f.write(f"{project_no}\t{reason}\n")


def append_output_rows(csv_path: str, json_path: str, rows: list[dict]):
    if not rows:
        return
    csv_exists = Path(csv_path).exists()
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        if not csv_exists:
            writer.writeheader()
        for r in rows:
            full = empty_row(); full.update(r)
            writer.writerow(full)
    with open(json_path, "a", encoding="utf-8") as f:
        for r in rows:
            full = empty_row(); full.update(r)
            f.write(json.dumps(full, ensure_ascii=False) + "\n")


def find_value_from_body(body: str, labels: list[str]) -> str:
    for label in labels:
        m = re.search(re.escape(label) + r"\s*[:：]?\s*([^\n\r]+)", body)
        if m:
            val = re.sub(r"\s+", " ", m.group(1)).strip()
            if val and len(val) < 300:
                return val
    return ""


def clean_extracted_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    bad = {"วงเงินงบประมาณ", "ราคากลาง", "วันที่ประกาศ", "วันที่สิ้นสุด", "เลขที่โครงการ", "สถานะโครงการ", "ข้อมูลสาระสำคัญในสัญญา", "ดูข้อมูล", "ออก", "ค้นหา"}
    return "" if not value or value in bad else value


def looks_like_contract_ref(value: str) -> bool:
    value = (value or "").strip()
    return bool(re.search(r"^(PO|PM|MPO)[A-Z0-9\-]+$", value, re.I) or re.search(r"^\d+/\d{2,4}$", value) or re.search(r"^[ก-๙]{1,5}\.?\d", value))


def extract_contract_period_from_contract_body(body: str) -> str:
    patterns = [
        r"(?:ระยะเวลาสัญญา|ระยะเวลาดำเนินการ|กำหนดส่งมอบ|ระยะเวลา)[^\n\r:：]*[:：]?\s*([^\n\r]+)",
        r"(\d{1,2}/\d{1,2}/\d{4}\s*(?:ถึง|-|–)\s*\d{1,2}/\d{1,2}/\d{4})",
        r"(\d+\s*(?:วัน|เดือน|ปี))",
    ]
    for p in patterns:
        m = re.search(p, body)
        if m:
            val = clean_extracted_value(m.group(1))
            if val and not looks_like_contract_ref(val):
                return val
    return ""


def extract_publication_date_from_contract_body(body: str) -> str:
    m = re.search(r"(?:วันที่ประกาศ|วันประกาศ|ประกาศ ณ วันที่|Announced Date)[^\d]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})", body, re.I)
    if m:
        return thai_date_to_iso(m.group(1))
    dates = re.findall(r"\d{1,2}[/\-]\d{1,2}[/\-]25\d{2}", body)
    return thai_date_to_iso(dates[0]) if dates else ""


def _row_contains_contract_label(row_text: str) -> bool:
    low = row_text.lower()
    return any(label.lower() in low for label in CONTRACT_MATERIAL_LABELS)


async def return_from_contract_page(page: Page):
    exit_btn = page.get_by_text("ออก", exact=True)
    if await exit_btn.count() == 0:
        exit_btn = page.locator("button:has-text('ออก'), a:has-text('ออก')")
    if await exit_btn.count() == 0:
        raise RuntimeError("ออก button not found")
    await exit_btn.last.evaluate("(el) => el.click()")
    await wait_for_page_settle(page, 5000)
    await wait_or_raise_bad_page(page)

async def click_contract_information_tab(page: Page) -> bool:
    # Text exists in body, but may not be a normal button/tab element.
    label = page.get_by_text("ข้อมูลสัญญา", exact=True)

    if await label.count() == 0:
        log.warning("ข้อมูลสัญญา text not found")
        return False

    # There may be multiple matches; use the first visible one near the top menu.
    for i in range(await label.count()):
        el = label.nth(i)
        try:
            box = await el.bounding_box()
            if not box:
                continue

            # Ignore body/content matches too far down
            if box["y"] > 300:
                continue

            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2

            await page.mouse.move(x, y)
            await page.wait_for_timeout(300)
            await page.mouse.down()
            await page.wait_for_timeout(150)
            await page.mouse.up()

            await page.wait_for_timeout(8000)

            body = await page_body_text(page)
            if not any(
                marker in body
                for marker in [
                    "à¸‚à¹‰à¸­à¸¡à¸¹à¸¥à¸ªà¸±à¸à¸à¸²à¹à¸¥à¸°à¸à¸²à¸£à¸šà¸£à¸´à¸«à¸²à¸£à¸ªà¸±à¸à¸à¸²",
                    "à¸§à¸±à¸™à¸—à¸µà¹ˆà¹€à¸£à¸´à¹ˆà¸¡à¸•à¹‰à¸™-à¸ªà¸´à¹‰à¸™à¸ªà¸¸à¸”à¸ªà¸±à¸à¸à¸²",
                    "à¸§à¸±à¸™à¸—à¸µà¹ˆà¹€à¸£à¸´à¹ˆà¸¡à¸•à¹‰à¸™à¸ªà¸±à¸à¸à¸²",
                ]
            ):
                continue
            if any(
                marker in body
                for marker in [
                    "ข้อมูลสัญญาและการบริหารสัญญา",
                    "วันที่เริ่มต้น-สิ้นสุดสัญญา",
                    "วันที่ประกาศ",
                    "วันที่สิ้นสุด",
                ]
            ):
                return True
            if (
                "ข้อมูลสาระสำคัญในสัญญา" in body
                and "เลขคุมสัญญาในระบบ e-GP" in body
            ):
                return True

        except Exception as e:
            log.warning("Contract tab coordinate click failed: %s", e)

    return False

async def click_contract_material_information(page: Page, project_no: str):
    for _ in range(30):
        body = await page_body_text(page)
        if any(label in body for label in CONTRACT_MATERIAL_LABELS):
            break
        await page.evaluate("window.scrollBy(0, 700)")
        await page.wait_for_timeout(700)
    else:
        log.warning("Contract Material section not found for %s", project_no)
        return None

    tables = page.locator("table")
    contract_row = None
    for t in range(await tables.count()):
        rows = tables.nth(t).locator("tr")
        for r in range(await rows.count()):
            row = rows.nth(r)
            txt = ""
            try:
                txt = (await row.inner_text()).strip()
            except Exception:
                pass
            if _row_contains_contract_label(txt):
                contract_row = row
                log.info("Found Contract Material row table=%d row=%d for %s", t, r, project_no)
                break
        if contract_row is not None:
            break
    if contract_row is None:
        return None

    try:
        await contract_row.evaluate("(el) => el.scrollIntoView({block: 'center'})")
    except Exception:
        pass
    await page.wait_for_timeout(700)

    cells = contract_row.locator("td, [role='cell']")
    count = await cells.count()
    targets = []
    if count:
        last_cell = cells.nth(count - 1)
        clickables = last_cell.locator("button, a, mat-icon, .mat-icon, i.pi, i[class*='icon'], svg, img, [role='button']")
        for i in range(await clickables.count()):
            targets.append(clickables.nth(i))
    if not targets:
        clickables = contract_row.locator("button, a, mat-icon, .mat-icon, i.pi, i[class*='icon'], svg, img, [role='button']")
        for i in range(await clickables.count()):
            targets.append(clickables.nth(i))
    if not targets:
        targets = [contract_row]

    await targets[-1].evaluate("(el) => el.click()")
    await wait_for_page_settle(page, 5000)
    await wait_or_raise_bad_page(page, project_no)
    body = await page_body_text(page)
    if "รายชื่อผู้เสนอราคา" in body or "ราคาที่เสนอ" in body or "สถานะสัญญา" in body:
        return page
    return None


async def extract_detail_base(page: Page, queue_row: dict) -> dict:
    body = await page_body_text(page)
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    buyer = find_value_from_body(body, ["ชื่อหน่วยงาน", "Name of Agency", "หน่วยงาน"])
    classification = find_value_from_body(body, ["พัสดุที่จัดหา", "Packages supplied"])
    status = find_value_from_body(body, ["สถานะโครงการ", "Project Status"]) or queue_row.get("status", "")
    base = empty_row()
    base.update({
        "source": BASE_URL, "country": "Thailand", "country_code": "TH",
        "publication_date": queue_row.get("publication_date", ""),
        "closing_date": "",
        "title": queue_row.get("title", ""), "buyer": buyer, "classification": classification,
        "status": status, "currency": "THB", "amount": queue_row.get("amount", ""),
        "awarding_agency_name": buyer, "bid_number": queue_row.get("project_no", ""),
        "notice_id": queue_row.get("project_no", ""), "notice_url": page.url,
        "scraped_at_utc": scraped_at,
    })
    base["title_en"] = translate_th_to_en(base["title"])
    base["buyer_en"] = translate_th_to_en(base["buyer"])
    base["classification_en"] = translate_th_to_en(base["classification"])
    base["status_en"] = translate_th_to_en(base["status"])
    base["awarding_agency_name_en"] = translate_th_to_en(base["awarding_agency_name"])
    return base


async def click_contract_information_tab(page: Page) -> bool:
    body_before = await page_body_text(page)
    candidates = [
        page.get_by_text("ข้อมูลสัญญา", exact=True),
        page.get_by_text("ข้อมูลสัญญา"),
        page.locator("div, span, a, button").filter(has_text="ข้อมูลสัญญา"),
    ]

    found = False
    for locator in candidates:
        try:
            count = await locator.count()
        except Exception:
            count = 0
        for i in range(count):
            found = True
            el = locator.nth(i)
            try:
                box = await el.bounding_box()
                if not box or box["y"] > 320:
                    continue

                try:
                    await el.evaluate("(node) => node.click()")
                except Exception:
                    x = box["x"] + box["width"] / 2
                    y = box["y"] + box["height"] / 2
                    await page.mouse.click(x, y)

                for _ in range(6):
                    await page.wait_for_timeout(1000)
                    body_after = await page_body_text(page)
                    if body_after != body_before:
                        return True
                    if any(
                        marker in body_after
                        for marker in [
                            "ข้อมูลสัญญาและการบริหารสัญญา",
                            "วันที่เริ่มต้น-สิ้นสุดสัญญา",
                            "วันที่เริ่มต้นสัญญา",
                            "วันที่สิ้นสุด",
                        ]
                    ):
                        return True
            except Exception as e:
                log.warning("Contract tab click failed: %s", e)

    if not found:
        log.warning("ข้อมูลสัญญา text not found")
    return False


async def extract_contract_info_from_contract_tab(page: Page) -> dict:
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(1000)

    clicked = await click_contract_information_tab(page)
    if not clicked:
        log.warning("Contract Information tab not found or did not load")
        return {"publication_date": "", "closing_date": "", "contract_period": ""}

    last_info = {"publication_date": "", "closing_date": "", "contract_period": ""}
    last_body = ""

    for attempt in range(8):
        if attempt:
            await page.wait_for_timeout(1500)

        body = await page_body_text(page)
        last_body = body
        info = extract_contract_tab_dates(body)

        if any(info.values()):
            log.info("Contract tab content detected on attempt %d: %r", attempt + 1, info)
            return info

        last_info = info

    log.warning("Contract tab content did not yield dates after polling")
    log.info("Contract tab FULL body after polling:\n%s", last_body)
    return last_info


async def parse_contract_material_page(page: Page, base: dict) -> list[dict]:
    tables = page.locator("table")
    rows_out = []

    for t in range(await tables.count()):
        table = tables.nth(t)
        table_text = re.sub(r"\s+", " ", (await table.inner_text()).strip())
        if "เลขคุมสัญญา" not in table_text and "สถานะสัญญา" not in table_text:
            continue
        trs = table.locator("tbody tr, tr")
        for i in range(await trs.count()):
            cells = await trs.nth(i).locator("td, [role='cell']").all()
            cell_texts = [re.sub(r"\s+", " ", (await c.inner_text()).strip()) for c in cells]
            if not cell_texts or not re.match(r"^\d+$", cell_texts[0].strip()):
                continue
            n = len(cell_texts)
            if n > 2:
                supp = clean_extracted_value(cell_texts[2])
                if supp and not re.match(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{4}$", supp):
                    base["supplier_name"] = supp
                    base["supplier_name_en"] = translate_th_to_en(supp)
            if n > 5 and re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{4}", cell_texts[5]):
                base["awarded_date"] = thai_date_to_iso(cell_texts[5])
            for ct in reversed(cell_texts):
                if re.search(r"[\d,]+\.\d{2}", ct):
                    base["awarded_value_detail"] = re.sub(r"[^\d.]", "", ct)
                    break
            break

    for t in range(await tables.count()):
        table = tables.nth(t)
        table_text = re.sub(r"\s+", " ", (await table.inner_text()).strip())
        if not any(k in table_text for k in ["รายการพิจารณา", "รายชื่อผู้เสนอราคา", "ราคาที่เสนอ"]):
            continue
        trs = table.locator("tbody tr, tr")
        for i in range(await trs.count()):
            cells = await trs.nth(i).locator("td, [role='cell']").all()
            cell_texts = [re.sub(r"\s+", " ", (await c.inner_text()).strip()) for c in cells]
            if len(cell_texts) < 5 or not re.match(r"^\d+$", cell_texts[0].strip()):
                continue
            row = dict(base)
            row["item_no"] = cell_texts[0].strip()
            row["item_description"] = cell_texts[1].strip()
            row["supplier_name"] = cell_texts[3].strip()
            row["supplier_name_en"] = translate_th_to_en(row["supplier_name"])
            row["item_awarded_value"] = re.sub(r"[^\d.]", "", cell_texts[4])
            row["item_unit_price"] = row["item_awarded_value"]
            row["item_description_en"] = translate_th_to_en(row["item_description"])
            row["dedup_key"] = make_dedup_key(base.get("bid_number"), row["item_no"], row["item_description"], row.get("supplier_name", ""))
            rows_out.append(row)
    return rows_out


async def search_exact_project(page: Page, project_no: str) -> bool:
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    await wait_for_page_settle(page, 4000)
    await wait_or_raise_bad_page(page, project_no)
    box = page.locator("input[placeholder*='ระบุ ชื่อโครงการ'], input[placeholder*='project']").first
    if await box.count() == 0:
        return False
    await box.fill(project_no)
    btn = page.locator("button:has-text('ค้นหา'), button:has-text('Search')").first
    await btn.click(force=True)
    await wait_for_page_settle(page, 5000)
    await wait_or_raise_bad_page(page, project_no)
    row = page.locator(f"tr:has-text('{project_no}'), [role='row']:has-text('{project_no}')").first
    if await row.count() == 0:
        return False
    cells = row.locator("td, [role='cell']")
    last_cell = cells.nth((await cells.count()) - 1) if await cells.count() else row
    target = last_cell.locator("button, a, [role='button'], mat-icon, .mat-icon, i, svg, img, .pi, [class*='icon']").last
    if await target.count() == 0:
        return False
    await target.evaluate("(el) => el.click()")
    await wait_for_page_settle(page, 6000)
    await wait_or_raise_bad_page(page, project_no)
    return True


async def process_one(page: Page, queue_row: dict) -> list[dict]:
    url = queue_row.get("detail_url", "").strip()
    project_no = queue_row.get("project_no", "").strip()

    if not project_no:
        m = re.search(r"/procurement/([^/?#]+)", url)
        project_no = m.group(1) if m else url[-40:]

    if not url:
        raise RuntimeError("Missing detail_url")
    if url:
        log.info("Opening saved URL for %s", project_no)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await wait_for_page_settle(page, 6000)
        await wait_or_raise_bad_page(page, project_no)
    else:
        raise RuntimeError("Missing detail_url")

    body = await page_body_text(page)
    markers = ["เอกสาร/ประกาศที่เกี่ยวข้อง", "ข้อมูลโครงการ", "ข้อมูลประกาศ", "ข้อมูลสาระสำคัญในสัญญา"]
    if not any(m in body for m in markers):
        log.warning("Saved URL failed for %s; trying exact search", project_no)
        if not await search_exact_project(page, project_no):
            raise RuntimeError("Detail URL failed and exact search failed")

    base = await extract_detail_base(page, queue_row)
    contract_page = await click_contract_material_information(page, project_no)
    if contract_page is None:
        contract_info = await extract_contract_info_from_contract_tab(page)
        for key in ["publication_date", "closing_date", "contract_period"]:
            if contract_info.get(key):
                base[key] = contract_info[key]
        base["dedup_key"] = make_dedup_key(base.get("notice_url"), project_no)
        return [base]
    try:
        base["notice_url"] = contract_page.url
        rows = await parse_contract_material_page(contract_page, base)

        # Leave item details page first
        try:
            await return_from_contract_page(page)
            await wait_for_page_settle(page, 5000)
        except Exception as e:
            log.warning("Could not return before Contract Information tab: %s", e)

        # Now we are back on main project detail page, so third-tab extraction can work
        contract_info = await extract_contract_info_from_contract_tab(page)
        log.info("Contract tab info for %s: %r", project_no, contract_info)
        for key in ["publication_date", "closing_date", "contract_period"]:
            value = contract_info.get(key, "")
            if not value:
                continue
            base[key] = value
            for row in rows:
                row[key] = value

    finally:
        pass

    if rows:
        return rows

    base["dedup_key"] = make_dedup_key(base.get("notice_url"), project_no)
    return [base]


async def process_tender_urls(queue_csv: str, output_csv: str, output_json: str, delay_ms: int, max_rows: int | None = None):
    queue = load_queue(queue_csv)
    if max_rows is not None and max_rows > 0:
        queue = queue[:max_rows]
    processed = load_processed()
    log.info("Loaded %d queued tenders; %d already processed", len(queue), len(processed))
    async with async_playwright() as pw:
        browser, context = await create_context(pw)
        page = await get_existing_or_new_page(context)
        for idx, row in enumerate(queue, 1):
            project_no = row.get("project_no", "").strip()
            if not project_no:
                continue
            if project_no in processed:
                log.info("[%d/%d] Skipping processed %s", idx, len(queue), project_no)
                continue
            try:
                log.info("[%d/%d] Processing %s", idx, len(queue), project_no)
                rows = await process_one(page, row)
                append_output_rows(output_csv, output_json, rows)
                mark_processed(project_no)
                processed.add(project_no)
                log.info("Processed %s -> %d rows", project_no, len(rows))
                await page.wait_for_timeout(delay_ms)
                if idx % 5 == 0:
                    log.info("Cooling down after 5 queued tenders...")
                    await page.wait_for_timeout(60000)
            except Exception as e:
                log.error("Failed %s: %s", project_no, e)
                mark_failed(project_no, str(e))
                raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Process saved Thailand GProcurement tender URLs")
    parser.add_argument("--queue-csv", default=URL_QUEUE_FILE)
    parser.add_argument("--output-csv", default="gprocurement_output.csv")
    parser.add_argument("--output-json", default="gprocurement_output.jsonl")
    parser.add_argument("--delay-ms", type=int, default=12000)
    parser.add_argument("--max-rows", type=int, default=None, help="Only process the first N queued URLs")
    args = parser.parse_args()
    asyncio.run(process_tender_urls(args.queue_csv, args.output_csv, args.output_json, args.delay_ms, args.max_rows))
