from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from harness.shared.field_extract import enrich_row_fields
from harness.shared.serialize import read_rows_csv, write_header_only_csv, write_rows_csv
from harness.sources.loader import load_source_module
from harness.sources.registry import SOURCES, feasible_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ACEE tender harness runner")
    parser.add_argument("--list-sources", action="store_true", help="List all configured sources")
    parser.add_argument(
        "--write-header-only",
        metavar="PATH",
        help="Write a header-only CSV using the target output schema",
    )
    parser.add_argument(
        "--smoke-source",
        metavar="SOURCE_KEY",
        help="Run a source-specific smoke probe when that source module is implemented",
    )
    parser.add_argument(
        "--write-smoke-sample-source",
        nargs=2,
        metavar=("SOURCE_KEY", "PATH"),
        help="Write normalized sample rows from a source smoke probe to CSV",
    )
    parser.add_argument(
        "--write-feasible-smoke-samples",
        metavar="PATH",
        help="Write one combined CSV using the normalized sample rows from all feasible source smoke probes",
    )
    parser.add_argument(
        "--write-feasible-smoke-samples-by-folder",
        action="store_true",
        help="Write each feasible source's smoke sample to a CSV in that source's configured folder",
    )
    parser.add_argument(
        "--smoke-filename",
        metavar="FILENAME",
        default="smoke_sample_rows.csv",
        help="Filename to use for --write-feasible-smoke-samples-by-folder (default: smoke_sample_rows.csv)",
    )
    parser.add_argument(
        "--write-live-window-source",
        nargs=2,
        metavar=("SOURCE_KEY", "PATH"),
        help="Write normalized rows from a live date-window source query when that source implements live_window_rows()",
    )
    parser.add_argument(
        "--write-live-medical-awarded-source",
        nargs=2,
        metavar=("SOURCE_KEY", "PATH"),
        help="Write normalized awarded medical or healthcare rows when the source implements live_medical_awarded_rows()",
    )
    parser.add_argument(
        "--write-live-medical-awarded-source-checkpointed",
        nargs=3,
        metavar=("SOURCE_KEY", "PATH", "CHUNK_DIR"),
        help="Write chunked awarded medical or healthcare rows to a chunk directory, then combine and deduplicate them",
    )
    parser.add_argument(
        "--combine-csv-dir",
        nargs=2,
        metavar=("DIR", "PATH"),
        help="Combine and deduplicate all CSV files in a directory into one output CSV",
    )
    parser.add_argument("--date-from", metavar="YYYY-MM-DD", help="Start date for live window queries")
    parser.add_argument("--date-to", metavar="YYYY-MM-DD", help="End date for live window queries")
    parser.add_argument(
        "--chunk-months",
        metavar="N",
        type=int,
        default=0,
        help="Split live medical or healthcare exports into month chunks before combining and deduplicating",
    )
    parser.add_argument(
        "--page-size",
        metavar="N",
        type=int,
        default=50,
        help="Page size for live window queries where supported",
    )
    return parser


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1).fromordinal(date(year, month + 1, 1).toordinal() - 1)


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, _month_end(year, month).day)
    return date(year, month, day)


def _iter_month_chunks(date_from: str, date_to: str, chunk_months: int) -> list[tuple[str, str]]:
    if chunk_months <= 0:
        return [(date_from, date_to)]
    start = _parse_iso_date(date_from)
    end = _parse_iso_date(date_to)
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        next_start = _add_months(cursor.replace(day=1), chunk_months)
        window_end = min(end, next_start.fromordinal(next_start.toordinal() - 1))
        windows.append((cursor.isoformat(), window_end.isoformat()))
        cursor = window_end.fromordinal(window_end.toordinal() + 1)
    return windows


def _dedup_rows(rows):
    deduped = []
    seen = set()
    for row in rows:
        key = row.get("dedup_key") or row.get("notice_id") or json.dumps(row, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _enrich_rows(rows):
    return [enrich_row_fields(row) for row in rows]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_sources:
        payload = {
            "all_sources": [config.__dict__ for config in SOURCES.values()],
            "feasible_sources": [config.key for config in feasible_sources()],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.write_header_only:
        path = Path(args.write_header_only)
        write_header_only_csv(path)
        print(str(path.resolve()))
        return 0

    if args.smoke_source:
        module = load_source_module(args.smoke_source)
        result = module.smoke_probe()
        print(
            json.dumps(
                {
                    "source_key": result.source_key,
                    "ok": result.ok,
                    "mode": result.mode,
                    "detail": result.detail,
                    "sample_rows": result.sample_rows,
                },
                indent=2,
            )
        )
        return 0

    if args.write_smoke_sample_source:
        source_key, raw_path = args.write_smoke_sample_source
        module = load_source_module(source_key)
        result = module.smoke_probe()
        if not result.ok:
            raise SystemExit(f"Smoke probe for {source_key} did not pass: {result.detail}")
        path = Path(raw_path)
        write_rows_csv(path, _enrich_rows(result.sample_rows))
        print(str(path.resolve()))
        return 0

    if args.write_feasible_smoke_samples:
        rows = []
        for config in feasible_sources():
            module = load_source_module(config.key)
            result = module.smoke_probe()
            if not result.ok:
                raise SystemExit(f"Smoke probe for {config.key} did not pass: {result.detail}")
            rows.extend(result.sample_rows)
        path = Path(args.write_feasible_smoke_samples)
        write_rows_csv(path, _enrich_rows(rows))
        print(str(path.resolve()))
        return 0

    if args.write_feasible_smoke_samples_by_folder:
        emitted_paths = {}
        for config in feasible_sources():
            module = load_source_module(config.key)
            result = module.smoke_probe()
            if not result.ok:
                raise SystemExit(f"Smoke probe for {config.key} did not pass: {result.detail}")
            out_dir = Path(config.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / args.smoke_filename
            write_rows_csv(out_path, _enrich_rows(result.sample_rows))
            emitted_paths[config.key] = str(out_path.resolve())
        print(json.dumps(emitted_paths, indent=2))
        return 0

    if args.write_live_window_source:
        source_key, raw_path = args.write_live_window_source
        if not args.date_from or not args.date_to:
            raise SystemExit("--date-from and --date-to are required with --write-live-window-source")
        module = load_source_module(source_key)
        if not hasattr(module, "live_window_rows"):
            raise SystemExit(f"Source {source_key} does not implement live_window_rows()")
        rows = module.live_window_rows(args.date_from, args.date_to, page_size=args.page_size)
        path = Path(raw_path)
        write_rows_csv(path, _enrich_rows(rows))
        print(str(path.resolve()))
        return 0

    if args.write_live_medical_awarded_source:
        source_key, raw_path = args.write_live_medical_awarded_source
        if not args.date_from or not args.date_to:
            raise SystemExit("--date-from and --date-to are required with --write-live-medical-awarded-source")
        module = load_source_module(source_key)
        if not hasattr(module, "live_medical_awarded_rows"):
            raise SystemExit(f"Source {source_key} does not implement live_medical_awarded_rows()")
        rows = []
        for window_from, window_to in _iter_month_chunks(args.date_from, args.date_to, args.chunk_months):
            rows.extend(module.live_medical_awarded_rows(window_from, window_to, page_size=args.page_size))
        rows = _dedup_rows(_enrich_rows(rows))
        path = Path(raw_path)
        write_rows_csv(path, rows)
        print(str(path.resolve()))
        return 0

    if args.write_live_medical_awarded_source_checkpointed:
        source_key, raw_path, raw_chunk_dir = args.write_live_medical_awarded_source_checkpointed
        if not args.date_from or not args.date_to:
            raise SystemExit(
                "--date-from and --date-to are required with --write-live-medical-awarded-source-checkpointed"
            )
        if args.chunk_months <= 0:
            raise SystemExit("--chunk-months must be greater than 0 with checkpointed exports")
        module = load_source_module(source_key)
        if not hasattr(module, "live_medical_awarded_rows"):
            raise SystemExit(f"Source {source_key} does not implement live_medical_awarded_rows()")

        chunk_dir = Path(raw_chunk_dir)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_paths = []
        for window_from, window_to in _iter_month_chunks(args.date_from, args.date_to, args.chunk_months):
            chunk_name = f"{window_from}_to_{window_to}.csv"
            chunk_path = chunk_dir / chunk_name
            rows = module.live_medical_awarded_rows(window_from, window_to, page_size=args.page_size)
            write_rows_csv(chunk_path, _enrich_rows(rows))
            chunk_paths.append(chunk_path)

        combined_rows = []
        for chunk_path in chunk_paths:
            combined_rows.extend(read_rows_csv(chunk_path))
        combined_rows = _dedup_rows(_enrich_rows(combined_rows))
        path = Path(raw_path)
        write_rows_csv(path, combined_rows)
        print(str(path.resolve()))
        return 0

    if args.combine_csv_dir:
        raw_dir, raw_path = args.combine_csv_dir
        source_dir = Path(raw_dir)
        if not source_dir.exists():
            raise SystemExit(f"CSV directory does not exist: {source_dir}")
        combined_rows = []
        for chunk_path in sorted(source_dir.glob("*.csv")):
            combined_rows.extend(read_rows_csv(chunk_path))
        combined_rows = _dedup_rows(_enrich_rows(combined_rows))
        path = Path(raw_path)
        write_rows_csv(path, combined_rows)
        print(str(path.resolve()))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
