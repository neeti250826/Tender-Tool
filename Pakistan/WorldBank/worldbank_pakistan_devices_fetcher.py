"""
World Bank — Pakistan medical-device award fetcher (complete pull).

Why this exists:
  The Cowork session could only page the DS01045 health-sector goods dataset
  through a web tool that truncates each response at ~80 KB, so only a partial
  Pakistan sample could be gathered in-session. This script runs on a machine
  with direct internet (e.g. the analyst's Windows box) and pulls the COMPLETE
  Pakistan set with no truncation, then filters to genuine medical devices /
  diagnostics and writes CSV + XLSX.

Source:
  https://financesone.worldbank.org/goods-procurement-contract-awards-in-health-sector/DS01045
  API: https://datacatalogapi.worldbank.org/dexapps/fone/api/view (viewId=DS01045)
  The API does NOT support server-side country filtering, so we page the full
  dataset and filter client-side (same approach as worldbank_health_awards_scraper.py).

Usage:
  python worldbank_pakistan_devices_fetcher.py
  python worldbank_pakistan_devices_fetcher.py --all-health-goods   # skip device filter
"""
from __future__ import annotations
import argparse, csv, json, re, sys, time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://datacatalogapi.worldbank.org/dexapps/fone/api/view"
DATASET_ID = "DS01045"
DATASET_URL = ("https://financesone.worldbank.org/"
               "goods-procurement-contract-awards-in-health-sector/DS01045")
PAGE = 1000
OUT_DIR = Path(__file__).resolve().parent / "output"

# Genuine medical device / diagnostic / consumable signal. Deliberately EXCLUDES
# IT equipment, office equipment, furniture, vehicles and generic "equipment"
# that appear under health-project PMU procurement but are not medical devices.
DEVICE_RE = re.compile(
    r"\b(diagnostic|test(?:ing)?\s*(?:kit|strip)|reagent|rapid\s*test|hepatitis|hbsag|"
    r"hiv|malaria|dengue|pregnan|glucomet|glucose\s*strip|ultrasound|x-?ray|ct\s*scan|"
    r"mri|ventilator|oxygen\s*(?:concentrat|cylinder|plant)|incubator|dialysis|"
    r"an(?:a)?esthesia|ecg|ekg|defibrillat|patient\s*monitor|suction|autoclave|"
    r"steriliz|sterilis|endoscop|laparoscop|operating\s*table|surgical\s*(?:light|"
    r"instrument|equipment)|nebuli|oximeter|laryngoscop|electrosurg|diathermy|c-?arm|"
    r"analy[sz]er|centrifuge|microscope|spectrophotometer|h(?:a)?ematology|biochemistry|"
    r"ppe\b|face\s*mask|surgical\s*mask|glove|syringe|catheter|cannula|thermometer|"
    r"bp\s*(?:apparatus|monitor)|stethoscop|examination\s*(?:couch|table)|hospital\s*bed|"
    r"delivery\s*(?:table|set|kit)|biomedical|medical\s*equipment|hospital\s*equipment|"
    r"medical\s*device|lab(?:oratory)?\s*equipment)\b",
    re.IGNORECASE,
)
# Exclude obvious non-medical "equipment" noise.
EXCLUDE_RE = re.compile(
    r"\b(it\s*equipment|office\s*equipment|server|laptop|computer|photocopier|printer|"
    r"led\s*tv|software|nas\b|hard\s*drive|furniture|vehicle|generator|air\s*condition)\b",
    re.IGNORECASE,
)


def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1.0,
                  status_forcelist=[429, 500, 502, 503, 504])
    a = HTTPAdapter(max_retries=retry)
    s.mount("https://", a)
    s.mount("http://", a)
    s.headers.update({"User-Agent": "clearstate-research/1.0"})
    return s


def fetch_all(s: requests.Session) -> list[dict]:
    rows, skip = [], 0
    while True:
        r = s.get(API_URL, params={"viewId": DATASET_ID, "type": "json",
                                   "top": PAGE, "skip": skip}, timeout=120)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            break
        rows.extend(data)
        total = r.json().get("count", 0)
        print(f"  fetched {len(rows)}/{total}", file=sys.stderr)
        skip += PAGE
        if skip >= total:
            break
        time.sleep(0.3)
    return rows


def is_device(desc: str) -> bool:
    return bool(DEVICE_RE.search(desc) and not EXCLUDE_RE.search(desc))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-health-goods", action="store_true",
                    help="Keep all Pakistan health-goods awards, skip device filter.")
    args = ap.parse_args()

    s = session()
    print("Paging full DS01045 health-sector goods dataset ...", file=sys.stderr)
    allrows = fetch_all(s)

    pk = [r for r in allrows
          if r.get("borrower_country") == "Pakistan"
          or r.get("borrower_country_code") == "PK"]
    print(f"Pakistan health-goods awards: {len(pk)}", file=sys.stderr)

    if not args.all_health_goods:
        pk = [r for r in pk if is_device(r.get("contract_description") or "")]
        print(f"After medical-device filter: {len(pk)}", file=sys.stderr)

    pk.sort(key=lambda r: (r.get("contract_signing_date") or ""))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "all_health_goods" if args.all_health_goods else "medical_devices"
    csv_path = OUT_DIR / f"worldbank_pakistan_{tag}_full.csv"
    cols = ["fiscal_year", "contract_signing_date", "project_id", "project_name",
            "procurement_category", "procurement_method", "project_global_practice",
            "wb_contract_number", "contract_description", "supplier", "supplier_country",
            "supplier_contract_amount_usd", "borrower_contract_reference_number",
            "as_of_date"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(pk)
    print(f"Wrote {len(pk)} rows -> {csv_path}")

    try:
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.title = "PK_devices"
        ws.append(cols)
        for r in pk:
            ws.append([r.get(c, "") for c in cols])
        xlsx_path = OUT_DIR / f"worldbank_pakistan_{tag}_full.xlsx"
        wb.save(xlsx_path)
        print(f"Wrote {len(pk)} rows -> {xlsx_path}")
    except ImportError:
        print("openpyxl not installed; CSV only.", file=sys.stderr)


if __name__ == "__main__":
    main()
