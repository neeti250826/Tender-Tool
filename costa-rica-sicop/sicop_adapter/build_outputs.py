"""Build deterministic candidate artifacts from the captured SICOP evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sicop_supplier_adapter import CANONICAL_COLUMNS, create_adapter


def main() -> None:
    workspace = Path(__file__).resolve().parent.parent
    evidence = workspace / "outputs" / "sicop_supplier_pull" / "agent_work" / "raw"
    output = evidence.parent
    adapter = create_adapter()
    canonical = adapter.extract(evidence)
    extended = adapter.extract_extended(evidence)

    (output / "candidate_rows.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "candidate_rows.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(canonical)

    extended_columns = list(extended[0]) if extended else CANONICAL_COLUMNS
    (output / "candidate_rows_extended.json").write_text(
        json.dumps(extended, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "candidate_rows_extended.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=extended_columns)
        writer.writeheader()
        writer.writerows(extended)

    summary = {
        "adapter_version": adapter.version,
        "row_count": len(canonical),
        "canonical_column_count": len(CANONICAL_COLUMNS),
        "notice_counts": {},
        "supplier_counts": {},
        "sum_item_totals_by_notice": {},
        "delivery_status": "candidate_best_available_not_approved",
    }
    for row in canonical:
        notice = row["notice_id"]
        supplier = row["supplier_name"]
        summary["notice_counts"][notice] = summary["notice_counts"].get(notice, 0) + 1
        summary["supplier_counts"][supplier] = summary["supplier_counts"].get(supplier, 0) + 1
        summary["sum_item_totals_by_notice"][notice] = round(
            summary["sum_item_totals_by_notice"].get(notice, 0) + float(row["amount"] or 0), 8
        )
    (output / "candidate_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
