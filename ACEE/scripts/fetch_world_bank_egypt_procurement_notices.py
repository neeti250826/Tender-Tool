from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import requests


WB_PROCUREMENT_NOTICE_API = (
    "https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice"
    "?datasetId=DS00979&resourceId=RS00909&type=json"
)

PROJECT_IDS = ("P167000", "P172548", "P172426")
EGYPT_HEALTH_CONTRACT_AWARD_RE = re.compile(
    r"health|medical|hospital|clinic|laborator|blood|diagnostic|pharma|"
    r"surgical|dialysis|syringe|suture|oxygenator|hemodialysis|"
    r"sterilization|vaccine|medicine|drug|equipment|consumables|waste",
    re.I,
)
FIELDS = (
    "bid_description",
    "country_code",
    "country_name",
    "deadline_date",
    "id",
    "notice_type",
    "procurement_category",
    "procurement_method",
    "project_id",
    "publication_date",
    "region",
    "sector",
    "url",
)


def _matches_project_filter(row: dict[str, object], project_ids: set[str]) -> bool:
    return row.get("country_code") == "EG" and row.get("project_id") in project_ids


def _matches_health_contract_award_filter(row: dict[str, object]) -> bool:
    if row.get("country_code") != "EG" or row.get("notice_type") != "Contract Award":
        return False
    haystack = " ".join(
        str(row.get(field) or "")
        for field in ("bid_description", "sector", "procurement_category", "project_id")
    )
    return row.get("project_id") in PROJECT_IDS or bool(EGYPT_HEALTH_CONTRACT_AWARD_RE.search(haystack))


def fetch_rows(
    *,
    start_skip: int,
    top: int,
    timeout: int,
    health_contract_awards_only: bool,
    scan_to_end: bool,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    skip = start_skip
    projects = set(PROJECT_IDS)
    while True:
        url = f"{WB_PROCUREMENT_NOTICE_API}&top={top}&skip={skip}"
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            break
        for row in data:
            if health_contract_awards_only:
                keep = _matches_health_contract_award_filter(row)
            else:
                keep = _matches_project_filter(row, projects)
            if keep:
                rows.append({field: row.get(field, "") for field in FIELDS})
        print(f"skip={skip} page_rows={len(data)} matches={len(rows)}", flush=True)
        skip += top
        if len(data) < top or not scan_to_end:
            break
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch recent World Bank Egypt procurement notices for evidence.")
    parser.add_argument("--start-skip", type=int, default=250000)
    parser.add_argument("--top", type=int, default=5000)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument(
        "--health-contract-awards-only",
        action="store_true",
        help="Keep Egypt Contract Award notices for health projects or health/medical keyword matches.",
    )
    parser.add_argument(
        "--scan-to-end",
        action="store_true",
        help="Continue from start-skip until the API returns a short final page.",
    )
    parser.add_argument(
        "--output",
        default="evidence/egypt_extended_award_probe_2026_06_24/world_bank_egypt_recent_procurement_notices_2024_2026.csv",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = fetch_rows(
        start_skip=args.start_skip,
        top=args.top,
        timeout=args.timeout,
        health_contract_awards_only=args.health_contract_awards_only,
        scan_to_end=args.scan_to_end,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "rows": len(rows),
        "output": str(output_path),
        "projects": list(PROJECT_IDS),
        "health_contract_awards_only": args.health_contract_awards_only,
        "scan_to_end": args.scan_to_end,
        "note": "API filtering was not honored by the endpoint in this run, so this scans recent ordered pages from start_skip.",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
