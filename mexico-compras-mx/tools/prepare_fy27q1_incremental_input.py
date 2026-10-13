"""Prepare a non-overlapping CompraMX FY27 Q1 scraper input workbook.

The input CSV is filtered to publication dates from 1 May through 31 July
2026. URLs in the supplied prior JSONL files are removed before scraping, and
the selected URL list plus its audit summary are written atomically.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple

import pandas as pd


WINDOW_START = pd.Timestamp("2026-05-01")
WINDOW_END_EXCLUSIVE = pd.Timestamp("2026-08-01")
DATE_COLUMN = "Fecha publicación"
URL_COLUMN = "Dirección del anuncio"
SCRAPER_URL_COLUMN = "URL"


def read_csv_with_fallbacks(path: Path) -> Tuple[pd.DataFrame, str]:
    """Read legacy source files without changing their source values."""
    errors = []
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return (
                pd.read_csv(path, dtype=str, encoding=encoding, low_memory=False),
                encoding,
            )
        except UnicodeDecodeError as error:
            errors.append(f"{encoding}: {error}")
    raise ValueError(f"Unable to decode {path}. Attempts: {' | '.join(errors)}")


def load_prior_urls(paths: Iterable[Path]) -> Tuple[Set[str], Dict[str, int]]:
    urls: Set[str] = set()
    stats = {"records": 0, "ok_records": 0, "invalid_json_lines": 0}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Prior JSONL not found: {path}")
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    stats["invalid_json_lines"] += 1
                    continue
                stats["records"] += 1
                if payload.get("ok") is True:
                    stats["ok_records"] += 1
                url = str(payload.get("url") or "").strip()
                if url:
                    urls.add(url)
    return urls, stats


def month_counts(values: pd.Series) -> Dict[str, int]:
    return {
        str(month): int(count)
        for month, count in values.dt.to_period("M").value_counts().sort_index().items()
    }


def write_json_atomic(path: Path, payload: Dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", type=Path, required=True)
    parser.add_argument("--previous-jsonl", type=Path, action="append", required=True)
    parser.add_argument("--output-xlsx", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--sheet", default="FY27Q1_New")
    args = parser.parse_args()

    source_csv = args.source_csv.resolve()
    output_xlsx = args.output_xlsx.resolve()
    audit_json = args.audit_json.resolve()
    prior_paths = [path.resolve() for path in args.previous_jsonl]
    output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    audit_json.parent.mkdir(parents=True, exist_ok=True)

    source, encoding = read_csv_with_fallbacks(source_csv)
    missing = [column for column in (DATE_COLUMN, URL_COLUMN) if column not in source.columns]
    if missing:
        raise ValueError(f"Source CSV is missing required column(s): {', '.join(missing)}")

    published = pd.to_datetime(source[DATE_COLUMN], errors="coerce")
    date_window = (published >= WINDOW_START) & (published < WINDOW_END_EXCLUSIVE)
    in_window = source.loc[date_window].copy()
    in_window_urls = in_window[URL_COLUMN].fillna("").astype(str).str.strip()
    in_window = in_window.assign(_normalized_url=in_window_urls)
    nonblank = in_window[in_window["_normalized_url"].ne("")].copy()
    unique_window = nonblank.drop_duplicates("_normalized_url", keep="first")

    prior_urls, prior_stats = load_prior_urls(prior_paths)
    selected = unique_window[~unique_window["_normalized_url"].isin(prior_urls)].copy()
    selected.drop(columns="_normalized_url", inplace=True)
    # Use an ASCII-only input column so PowerShell-to-Python argument encoding
    # cannot corrupt the URL-column name before the scraper starts.
    selected[SCRAPER_URL_COLUMN] = selected[URL_COLUMN].fillna("").astype(str).str.strip()

    temporary_xlsx = output_xlsx.with_suffix(".tmp.xlsx")
    with pd.ExcelWriter(temporary_xlsx, engine="openpyxl") as writer:
        selected.to_excel(writer, sheet_name=args.sheet, index=False)
        worksheet = writer.book[args.sheet]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
    os.replace(temporary_xlsx, output_xlsx)

    selected_published = pd.to_datetime(selected[DATE_COLUMN], errors="coerce")
    audit = {
        "scope": {
            "publication_date_start": WINDOW_START.date().isoformat(),
            "publication_date_end": date(2026, 7, 31).isoformat(),
            "source_date_column": DATE_COLUMN,
            "source_url_column": URL_COLUMN,
            "scraper_url_column": SCRAPER_URL_COLUMN,
            "output_sheet": args.sheet,
        },
        "source": {
            "path": str(source_csv),
            "encoding": encoding,
            "rows": int(len(source)),
            "invalid_publication_dates": int(published.isna().sum()),
        },
        "prior_extraction": {
            "jsonl_paths": [str(path) for path in prior_paths],
            "unique_urls": len(prior_urls),
            **prior_stats,
        },
        "selection": {
            "publication_window_rows": int(len(in_window)),
            "blank_url_rows": int(len(in_window) - len(nonblank)),
            "duplicate_url_rows": int(len(nonblank) - len(unique_window)),
            "unique_urls_in_window": int(len(unique_window)),
            "excluded_previously_extracted_urls": int(unique_window["_normalized_url"].isin(prior_urls).sum()),
            "new_urls_to_scrape": int(len(selected)),
            "all_window_urls_by_month": month_counts(published.loc[date_window]),
            "selected_urls_by_month": month_counts(selected_published),
        },
        "output": {"input_xlsx": str(output_xlsx)},
    }
    write_json_atomic(audit_json, audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
