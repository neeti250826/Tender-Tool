from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from harness.shared.schema import OUTPUT_COLUMNS


def write_rows_csv(path: Path, rows: Iterable[Mapping[str, str]], columns: Sequence[str] | None = None) -> Path:
    fieldnames = list(columns or OUTPUT_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in fieldnames})
    return path


def write_header_only_csv(path: Path) -> Path:
    return write_rows_csv(path, [])


def read_rows_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{column: row.get(column, "") for column in OUTPUT_COLUMNS} for row in reader]
