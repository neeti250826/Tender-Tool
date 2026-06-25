# Extracted from vietnam_tender_scraper_colab.ipynb. Review notebook shell commands before running locally.

# Notebook shell command cell:
# !pip install selenium pandas webdriver-manager

# Notebook shell command cell:
# !pip install -q selenium pandas
# !apt-get update -y
# !apt-get install -y wget unzip
# !wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
# !dpkg -i google-chrome-stable_current_amd64.deb || apt-get -fy install -y

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, SessionNotCreatedException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options


BASE_URL = "https://muasamcong.mpi.gov.vn"


# ---------------------------------
# INPUT:
# Add tender codes or full URLs here
# ---------------------------------

TENDER_INPUTS = [
    # You can put a code like:
    # "IB2600018767",

    # Or a full detail/redirect URL like:
    "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?code=IB2600018767&render=url-redirect&type=tbmt",
    "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render=detail-v2&bidForm=CHCT&bidMode=1_MTHS&bidOpenId=undefined&bidPreNotifyResultId=undefined&bidPreOpenId=undefined&caseKHKQ=undefined&id=a490f606-329a-4f67-bd7a-76d722c96fcc&inputResultId=undefined&isInternet=1&notifyId=a490f606-329a-4f67-bd7a-76d722c96fcc&notifyNo=IB2500507160&planNo=PL2500286219&pno=undefined&processApply=LDT&step=tbmt&stepCode=notify-contractor-step-1-tbmt&techReqId=undefined&type=es-notify-contractor",
]

OUTPUT_FILE = "vietnam_tenders.csv"
HEADLESS = True


# ---------------------------------
# DATA MODEL
# ---------------------------------

@dataclass
class TenderRecord:
    source_input: str = ""
    source_url: str = ""
    final_url: str = ""
    notify_no: str = ""
    plan_no: str = ""
    tender_title: str = ""
    project_name: str = ""
    investor_name: str = ""
    procuring_entity_name: str = ""
    capital_detail: str = ""
    field: str = ""
    bid_form: str = ""
    contract_type: str = ""
    bid_mode: str = ""
    contract_period: str = ""
    issue_location: str = ""
    receive_location: str = ""
    performance_location: str = ""
    bid_close_date: str = ""
    bid_open_date: str = ""
    bid_open_location: str = ""
    bid_validity_period: str = ""
    guarantee_value: str = ""
    published_date: str = ""
    page_title: str = ""
    raw_text: str = ""


LABEL_MAP: Dict[str, str] = {
    "Mã TBMT": "notify_no",
    "Notice No": "notify_no",
    "Ngày đăng tải": "published_date",
    "Published date": "published_date",
    "Mã KHLCNT": "plan_no",
    "Plan No": "plan_no",
    "Tên gói thầu": "tender_title",
    "Package name": "tender_title",
    "Tên dự án": "project_name",
    "Project name": "project_name",
    "Chủ đầu tư": "investor_name",
    "Investor": "investor_name",
    "Bên mời thầu": "procuring_entity_name",
    "Procuring entity": "procuring_entity_name",
    "Chi tiết nguồn vốn": "capital_detail",
    "Capital detail": "capital_detail",
    "Lĩnh vực": "field",
    "Field": "field",
    "Hình thức lựa chọn nhà thầu": "bid_form",
    "Bid form": "bid_form",
    "Loại hợp đồng": "contract_type",
    "Contract type": "contract_type",
    "Phương thức lựa chọn nhà thầu": "bid_mode",
    "Bid mode": "bid_mode",
    "Thời gian thực hiện hợp đồng": "contract_period",
    "Contract period": "contract_period",
    "Thời gian thực hiện gói thầu": "contract_period",
    "Địa điểm phát hành HSMT": "issue_location",
    "Issue location": "issue_location",
    "Địa điểm nhận HSDT": "receive_location",
    "Receive location": "receive_location",
    "Địa điểm nhận e-HSDT": "receive_location",
    "Địa điểm thực hiện gói thầu": "performance_location",
    "Performance location": "performance_location",
    "Thời điểm đóng thầu": "bid_close_date",
    "Bid close date": "bid_close_date",
    "Thời điểm mở thầu": "bid_open_date",
    "Bid open date": "bid_open_date",
    "Địa điểm mở thầu": "bid_open_location",
    "Bid open location": "bid_open_location",
    "Hiệu lực hồ sơ dự thầu": "bid_validity_period",
    "Bid validity period": "bid_validity_period",
    "Số tiền bảo đảm dự thầu": "guarantee_value",
    "Bid guarantee value": "guarantee_value",
}


# ---------------------------------
# HELPERS
# ---------------------------------

def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def build_detail_url(item: str) -> str:
    item = clean_text(item)
    if item.startswith("http://") or item.startswith("https://"):
        return item

    # assume tender code like IB2600018767
    return f"{BASE_URL}/web/guest/contractor-selection?code={item}&render=url-redirect&type=tbmt"


def first_non_empty(*values: str) -> str:
    for v in values:
        v = clean_text(v)
        if v:
            return v
    return ""


def get_query_params(url: str) -> Dict[str, str]:
    try:
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        return {k: v[0] for k, v in q.items() if v}
    except Exception:
        return {}


def build_driver(headless: bool = True) -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.binary_location = "/usr/bin/google-chrome"

    if headless:
        chrome_options.add_argument("--headless=new")

    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1600,2200")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver


def wait_for_page(driver, timeout: int = 30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if driver.execute_script("return document.readyState") == "complete":
                return
        except Exception:
            pass
        time.sleep(0.5)


def dismiss_popups(driver):
    selectors = [
        "//*[contains(text(),'Skip')]",
        "//*[contains(text(),'Bỏ qua')]",
        "//*[contains(text(),'Đóng')]",
        "//*[contains(text(),'Close')]",
        "//*[contains(text(),'ĐỂ SAU')]",
        "//button[contains(.,'Skip')]",
        "//button[contains(.,'Bỏ qua')]",
        "//button[contains(.,'Close')]",
        "//button[contains(.,'ĐỂ SAU')]",
    ]
    for xpath in selectors:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed():
                    try:
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.5)
                        return
                    except Exception:
                        pass
        except Exception:
            pass


def get_page_text(driver) -> str:
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        return clean_text(body.text)
    except Exception:
        return ""


def get_page_title(driver) -> str:
    try:
        return clean_text(driver.title)
    except Exception:
        return ""


def extract_pairs_from_text(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}

    labels = sorted(LABEL_MAP.keys(), key=len, reverse=True)
    label_group = "|".join(re.escape(x) for x in labels)

    pattern = re.compile(
        rf"(?P<label>{label_group})\s+(?P<value>.*?)(?=(?:{label_group})\s+|$)",
        re.IGNORECASE | re.DOTALL,
    )

    for m in pattern.finditer(text):
        label = clean_text(m.group("label"))
        value = clean_text(m.group("value"))
        key = LABEL_MAP.get(label)

        if key and value and key not in result:
            value = re.sub(
                r"\s+(Thông tin cơ bản|Thông tin chung|Cách thức dự thầu|Thông tin dự thầu)\b.*$",
                "",
                value,
                flags=re.IGNORECASE,
            )
            result[key] = value[:2000]

    return result


def best_heading(driver) -> str:
    for tag in ["h1", "h2", "h3"]:
        try:
            elements = driver.find_elements(By.TAG_NAME, tag)
            for el in elements[:5]:
                txt = clean_text(el.text)
                if txt and txt.lower() not in {
                    "lựa chọn nhà thầu - egp_v2.0",
                    "thông tin lựa chọn nhà thầu",
                }:
                    return txt
        except Exception:
            pass
    return ""


# ---------------------------------
# SCRAPE ONE DETAIL PAGE
# ---------------------------------

def scrape_detail_page(driver, item: str) -> TenderRecord:
    url = build_detail_url(item)
    rec = TenderRecord(source_input=item, source_url=url)

    driver.get(url)
    wait_for_page(driver, 30)
    time.sleep(3)
    dismiss_popups(driver)

    rec.final_url = driver.current_url
    rec.page_title = get_page_title(driver)
    rec.raw_text = get_page_text(driver)

    params = get_query_params(rec.final_url)
    rec.notify_no = first_non_empty(params.get("notifyNo", ""), params.get("code", ""), rec.notify_no)
    rec.plan_no = first_non_empty(params.get("planNo", ""), rec.plan_no)

    parsed = extract_pairs_from_text(rec.raw_text)
    for key, value in parsed.items():
        if hasattr(rec, key):
            setattr(rec, key, value)

    if not rec.tender_title:
        rec.tender_title = best_heading(driver)

    return rec


# ---------------------------------
# SAVE OUTPUT
# ---------------------------------

def save_csv(records: List[TenderRecord], path: str):
    if not records:
        return
    fieldnames = list(asdict(records[0]).keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(asdict(rec))


def save_json(records: List[TenderRecord], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, ensure_ascii=False, indent=2)


# ---------------------------------
# MAIN
# ---------------------------------

def main():
    try:
        driver = build_driver(headless=HEADLESS)
    except SessionNotCreatedException as e:
        print("Chrome could not start.", file=sys.stderr)
        print(str(e), file=sys.stderr)
        return 1

    records: List[TenderRecord] = []

    try:
        for idx, item in enumerate(TENDER_INPUTS, start=1):
            try:
                rec = scrape_detail_page(driver, item)
                records.append(rec)
                print(
                    f"[{idx}/{len(TENDER_INPUTS)}] "
                    f"{rec.notify_no or rec.tender_title or rec.final_url}",
                    file=sys.stderr,
                )
            except TimeoutException:
                print(f"[WARN] Timeout while scraping: {item}", file=sys.stderr)
            except Exception as exc:
                print(f"[WARN] Failed: {item} :: {exc}", file=sys.stderr)

    finally:
        driver.quit()

    if not records:
        print("No records extracted.", file=sys.stderr)
        return 2

    if OUTPUT_FILE.lower().endswith(".json"):
        save_json(records, OUTPUT_FILE)
    else:
        save_csv(records, OUTPUT_FILE)

    print(f"Saved {len(records)} records to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    main()

