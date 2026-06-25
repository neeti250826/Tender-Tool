#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parent

OUTPUTS = {
    "dubai_esupply": ROOT / "UAE" / "Dubai_eSupply" / "output" / "dubai_esupply_medical_2024_2026.csv",
    "capt": ROOT / "Kuwait" / "CAPT" / "output" / "capt_awarded_medical_2024_2026.csv",
    "drap": ROOT / "Pakistan" / "DRAP" / "output" / "drap_item_medical_2024_2026.csv",
    "ppra": ROOT / "Pakistan" / "PPRA" / "output" / "ppra_awarded_medical_2024_2026.csv",
    "epads": ROOT / "Pakistan" / "EPADS" / "output" / "epads_item_medical_2024_2026.csv",
}


def load_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def count_non_empty(rows: Iterable[Dict[str, str]], column: str) -> int:
    return sum(1 for row in rows if (row.get(column) or "").strip())


def sample_blank_amount_rows(rows: List[Dict[str, str]], limit: int = 5) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for row in rows:
        if (row.get("amount") or "").strip():
            continue
        result.append(
            {
                "notice_id": (row.get("notice_id") or "").strip(),
                "publication_date": (row.get("publication_date") or "").strip(),
                "title": (row.get("title") or "").strip(),
                "buyer": (row.get("buyer") or "").strip(),
                "item_description": (row.get("item_description") or "").strip(),
            }
        )
        if len(result) >= limit:
            break
    return result


def report_for_source(name: str, path: Path) -> Dict[str, object]:
    rows = load_rows(path)
    return {
        "csv": str(path),
        "rows": len(rows),
        "amount_filled": count_non_empty(rows, "amount"),
        "awarded_value_detail_filled": count_non_empty(rows, "awarded_value_detail"),
        "currency_filled": count_non_empty(rows, "currency"),
        "supplier_name_filled": count_non_empty(rows, "supplier_name"),
        "awarded_date_filled": count_non_empty(rows, "awarded_date"),
        "contract_period_filled": count_non_empty(rows, "contract_period"),
        "blank_amount_with_currency": sum(
            1 for row in rows if not (row.get("amount") or "").strip() and (row.get("currency") or "").strip()
        ),
        "missing_supplier_with_amount": sum(
            1 for row in rows if (row.get("amount") or "").strip() and not (row.get("supplier_name") or "").strip()
        ),
        "missing_supplier_with_awarded_value_detail": sum(
            1
            for row in rows
            if (row.get("awarded_value_detail") or "").strip() and not (row.get("supplier_name") or "").strip()
        ),
        "sample_rows_missing_amount": sample_blank_amount_rows(rows),
    }


def main() -> None:
    report = {name: report_for_source(name, path) for name, path in OUTPUTS.items()}
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
