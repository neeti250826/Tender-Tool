#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List

from Kuwait.CAPT.capt_verified_seeds import MEDICAL_SCOPE_EXCLUDED_NOTICE_IDS, VERIFIED_SEED_ROWS
from Pakistan.DRAP.drap_verified_seeds import VERIFIED_SEED_TENDERS

ROOT = Path(__file__).resolve().parent
CAPT_CSV = ROOT / "Kuwait" / "CAPT" / "output" / "capt_awarded_medical_2024_2026.csv"
DRAP_CSV = ROOT / "Pakistan" / "DRAP" / "output" / "drap_item_medical_2024_2026.csv"
DRAP_MEDICAL_CLASSIFICATIONS = {
    "healthcare tender document",
    "healthcare prequalification document",
}
RAW_DATE_RANGE_RE = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}|\d{4}/\d{1,2}/\d{1,2})\s+to\s+"
    r"(?:\d{4}-\d{2}-\d{2}|\d{4}/\d{1,2}/\d{1,2})\s*$"
)


def load_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def count_non_empty(rows: Iterable[Dict[str, str]], column: str) -> int:
    return sum(1 for row in rows if (row.get(column) or "").strip())


def build_capt_seed_counts() -> Counter:
    return Counter(
        (row.get("notice_id") or "").strip()
        for row in VERIFIED_SEED_ROWS
        if (row.get("notice_id") or "").strip()
        and (row.get("notice_id") or "").strip() not in MEDICAL_SCOPE_EXCLUDED_NOTICE_IDS
    )


def build_drap_seed_counts() -> Counter:
    counts: Counter = Counter()
    for tender in VERIFIED_SEED_TENDERS:
        classification = (tender.get("classification") or "healthcare tender document").strip()
        if classification not in DRAP_MEDICAL_CLASSIFICATIONS:
            continue
        notice_id = (tender.get("notice_id") or "").strip()
        items = tender.get("items") or []
        if notice_id:
            counts[notice_id] += len(items)
    return counts


def build_drap_notice_classifications() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for tender in VERIFIED_SEED_TENDERS:
        notice_id = (tender.get("notice_id") or "").strip()
        if not notice_id:
            continue
        mapping[notice_id] = (tender.get("classification") or "healthcare tender document").strip()
    return mapping


def build_output_counts(rows: Iterable[Dict[str, str]]) -> Counter:
    return Counter((row.get("notice_id") or "").strip() for row in rows if (row.get("notice_id") or "").strip())


def diff_counts(expected: Counter, actual: Counter) -> Dict[str, Dict[str, int]]:
    keys = sorted(set(expected) | set(actual))
    mismatches: Dict[str, Dict[str, int]] = {}
    for key in keys:
        if expected.get(key, 0) != actual.get(key, 0):
            mismatches[key] = {"expected": expected.get(key, 0), "actual": actual.get(key, 0)}
    return mismatches


def raw_contract_period_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {
            "notice_id": (row.get("notice_id") or "").strip(),
            "title": (row.get("title") or "").strip(),
            "contract_period": (row.get("contract_period") or "").strip(),
        }
        for row in rows
        if RAW_DATE_RANGE_RE.match((row.get("contract_period") or "").strip())
    ]


def main() -> None:
    capt_rows = load_csv_rows(CAPT_CSV)
    drap_rows = load_csv_rows(DRAP_CSV)

    capt_seed_counts = build_capt_seed_counts()
    drap_seed_counts = build_drap_seed_counts()
    drap_notice_classifications = build_drap_notice_classifications()
    capt_output_counts = build_output_counts(capt_rows)
    drap_output_counts = build_output_counts(drap_rows)

    report = {
        "capt": {
            "csv": str(CAPT_CSV),
            "rows": len(capt_rows),
            "seed_rows": sum(capt_seed_counts.values()),
            "publication_date_filled": count_non_empty(capt_rows, "publication_date"),
            "supplier_name_filled": count_non_empty(capt_rows, "supplier_name"),
            "awarded_date_filled": count_non_empty(capt_rows, "awarded_date"),
            "rows_missing_supplier_name": [
                {
                    "notice_id": (row.get("notice_id") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                }
                for row in capt_rows
                if not (row.get("supplier_name") or "").strip()
            ],
            "rows_with_raw_contract_period_dates": raw_contract_period_rows(capt_rows),
            "out_of_scope_notice_ids_present": sorted(
                {
                    notice_id
                    for notice_id in capt_output_counts
                    if notice_id in MEDICAL_SCOPE_EXCLUDED_NOTICE_IDS
                }
            ),
            "count_mismatches": diff_counts(capt_seed_counts, capt_output_counts),
        },
        "drap": {
            "csv": str(DRAP_CSV),
            "rows": len(drap_rows),
            "seed_rows": sum(drap_seed_counts.values()),
            "publication_date_filled": count_non_empty(drap_rows, "publication_date"),
            "closing_date_filled": count_non_empty(drap_rows, "closing_date"),
            "rows_with_raw_contract_period_dates": raw_contract_period_rows(drap_rows),
            "out_of_scope_notice_ids_present": sorted(
                {
                    notice_id
                    for notice_id in drap_output_counts
                    if drap_notice_classifications.get(notice_id, "healthcare tender document")
                    not in DRAP_MEDICAL_CLASSIFICATIONS
                }
            ),
            "count_mismatches": diff_counts(drap_seed_counts, drap_output_counts),
        },
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
