from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.shared.schema import OUTPUT_COLUMNS
from harness.shared.serialize import write_rows_csv


def read_rows(path: Path) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                return [{column: row.get(column, "") for column in OUTPUT_COLUMNS} for row in reader]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"Failed to read {path}: {last_error}")


def dedup_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        key = row.get("dedup_key") or json.dumps(row, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the best available Hungary TED medical awarded export from saved probe files."
    )
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--summary", required=True, help="Output JSON summary path")
    args = parser.parse_args()

    inputs = [
        ROOT / "Hungary/ekr-gov-hu/ted_hungary_medical_awards_broader_probe.csv",
        ROOT / "Hungary/ekr-gov-hu/ted_hungary_medical_awards_high_yield_cpvs.csv",
        ROOT / "Hungary/ekr-gov-hu/ted_probe_medical_awards_2024_recent.csv",
    ]

    raw_rows: list[dict[str, str]] = []
    input_stats: dict[str, dict[str, int]] = {}
    for path in inputs:
        rows = read_rows(path)
        raw_rows.extend(rows)
        input_stats[str(path.resolve())] = {
            "rows": len(rows),
            "item_quantity_nonblank": sum(1 for row in rows if (row.get("item_quantity") or "").strip()),
            "item_uom_nonblank": sum(1 for row in rows if (row.get("item_uom") or "").strip()),
        }

    deduped_rows = dedup_rows(raw_rows)
    output_path = ROOT / args.output
    summary_path = ROOT / args.summary
    write_rows_csv(output_path, deduped_rows)

    payload = {
        "inputs": input_stats,
        "raw_rows": len(raw_rows),
        "raw_item_quantity_nonblank": sum(1 for row in raw_rows if (row.get("item_quantity") or "").strip()),
        "deduped_rows": len(deduped_rows),
        "deduped_item_quantity_nonblank": sum(1 for row in deduped_rows if (row.get("item_quantity") or "").strip()),
        "deduped_item_uom_nonblank": sum(1 for row in deduped_rows if (row.get("item_uom") or "").strip()),
        "output_path": str(output_path.resolve()),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(str(output_path.resolve()))
    print(str(summary_path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
