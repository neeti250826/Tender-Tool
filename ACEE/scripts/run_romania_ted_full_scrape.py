from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.shared.schema import OUTPUT_COLUMNS
from harness.shared.serialize import read_rows_csv, write_rows_csv
from scripts.probe_ted_medical_awards import collect_rows


ROMANIA_HIGH_LEVEL_MEDICAL_CPVS = (
    "33100000",  # medical equipments, pharmaceuticals and personal care products subtree in TED search
    "33600000",  # pharmaceutical products subtree
    "33700000",  # personal care products subtree; includes some healthcare consumables
    "50421000",  # repair and maintenance services of medical equipment
)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _iter_month_chunks(date_from: str, date_to: str, chunk_months: int) -> list[tuple[str, str]]:
    start = _parse_date(date_from).replace(day=1)
    requested_start = _parse_date(date_from)
    end = _parse_date(date_to)
    chunks: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        next_start = _add_months(cursor, chunk_months)
        chunk_start = max(cursor, requested_start)
        chunk_end = min(end, date.fromordinal(next_start.toordinal() - 1))
        chunks.append((chunk_start.isoformat(), chunk_end.isoformat()))
        cursor = next_start
    return chunks


def _dedup_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        key = row.get("dedup_key") or row.get("notice_id") or repr(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _write_progress(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["chunk", "rows"])
        if handle.tell() == 0:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a checkpointed Romania TED medical/healthcare scrape.")
    parser.add_argument("--date-from", default="2024-01-01")
    parser.add_argument("--date-to", default=date.today().isoformat())
    parser.add_argument("--output", required=True)
    parser.add_argument("--chunk-dir", required=True)
    parser.add_argument("--chunk-months", type=int, default=3)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--pages", type=int, default=200)
    parser.add_argument("--cpv", action="append", dest="cpvs")
    parser.add_argument("--resume", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cpvs = args.cpvs or list(ROMANIA_HIGH_LEVEL_MEDICAL_CPVS)
    chunk_dir = Path(args.chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    progress_rows: list[dict[str, str]] = []

    for chunk_from, chunk_to in _iter_month_chunks(args.date_from, args.date_to, args.chunk_months):
        chunk_path = chunk_dir / f"{chunk_from}_to_{chunk_to}.csv"
        if args.resume and chunk_path.exists():
            progress_rows.append({"chunk": chunk_path.name, "rows": "existing"})
            continue
        rows = collect_rows(
            "ROU",
            chunk_from,
            chunk_to,
            limit=args.limit,
            pages=args.pages,
            cpvs=cpvs,
            prefer_xml=False,
        )
        write_rows_csv(chunk_path, rows)
        progress_rows.append({"chunk": chunk_path.name, "rows": str(len(rows))})
        _write_progress(chunk_dir / "progress.csv", [progress_rows[-1]])
        print(f"{chunk_path} rows={len(rows)}", flush=True)

    combined_rows: list[dict[str, str]] = []
    for chunk_path in sorted(chunk_dir.glob("*.csv")):
        if chunk_path.name == "progress.csv":
            continue
        combined_rows.extend(read_rows_csv(chunk_path))
    combined_rows = _dedup_rows(combined_rows)
    output_path = Path(args.output)
    write_rows_csv(output_path, combined_rows)
    print(output_path.resolve())
    print(f"rows={len(combined_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
