from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.runner import _dedup_rows, _iter_month_chunks
from harness.shared.field_extract import (
    enrich_row_fields,
    filter_medical_goods_rows,
    filter_medical_healthcare_rows,
)
from harness.shared.schema import OUTPUT_COLUMNS
from harness.shared.serialize import read_rows_csv, write_rows_csv
from harness.sources.loader import load_source_module


SOUTH_AFRICA_FINAL_COLUMNS = list(OUTPUT_COLUMNS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the South Africa awarded medical/healthcare full scrape.")
    parser.add_argument("--date-from", default="2024-01-01")
    parser.add_argument("--date-to", default=date.today().isoformat())
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--refresh-etenders", action="store_true")
    parser.add_argument("--refresh-simple-sources", action="store_true")
    return parser


def _fallback_date_score(path: Path) -> date:
    match = re.search(r"_to_(\d{4}_\d{2}_\d{2})", path.name)
    if not match:
        return date.min
    return datetime.strptime(match.group(1), "%Y_%m_%d").date()


def _best_non_empty_csv(output_dir: Path, pattern: str, exclude: Path) -> tuple[Path, list[dict[str, str]]] | None:
    best_candidate: tuple[Path, list[dict[str, str]]] | None = None
    best_score: tuple[date, int] = (date.min, 0)
    candidates = sorted(output_dir.glob(pattern), reverse=True)
    for candidate in candidates:
        if candidate == exclude or not candidate.exists():
            continue
        try:
            rows = read_rows_csv(candidate)
        except FileNotFoundError:
            continue
        row_count = len(rows)
        if row_count == 0:
            continue
        score = (_fallback_date_score(candidate), row_count)
        if best_candidate is None or score > best_score:
            best_candidate = (candidate, rows)
            best_score = score
    return best_candidate


def _enrich_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [enrich_row_fields(row) for row in rows]


def _apply_source_normalizers(rows: list[dict[str, str]], source_keys: tuple[str, ...]) -> list[dict[str, str]]:
    normalized_rows: list[dict[str, str]] = []
    modules = [load_source_module(source_key) for source_key in source_keys]
    source_to_modules: dict[str, list[object]] = {}
    for module in modules:
        source_name = getattr(getattr(module, "CONFIG", None), "source", "")
        if not source_name:
            continue
        source_to_modules.setdefault(source_name, []).append(module)
    rows_by_source: dict[str, list[dict[str, str]]] = {}
    passthrough_rows: list[dict[str, str]] = []

    for row in rows:
        source_name = row.get("source", "")
        if source_name not in source_to_modules:
            passthrough_rows.append(dict(row))
            continue
        rows_by_source.setdefault(source_name, []).append(dict(row))

    normalized_rows.extend(passthrough_rows)
    for source_name, source_rows in rows_by_source.items():
        normalized_candidates = source_rows
        for module in source_to_modules[source_name]:
            if hasattr(module, "normalize_saved_rows"):
                normalized_candidates = module.normalize_saved_rows(normalized_candidates)
        for normalized in normalized_candidates:
            if normalized:
                normalized_rows.append(normalized)
    return normalized_rows


def _rewrite_enriched_output(path: Path, source_key: str) -> Path:
    rows = read_rows_csv(path)
    module = load_source_module(source_key)
    if hasattr(module, "normalize_saved_rows"):
        rows = module.normalize_saved_rows(rows)
    enriched_rows = _dedup_rows(_enrich_rows(rows))
    if hasattr(module, "normalize_saved_rows"):
        enriched_rows = _dedup_rows(module.normalize_saved_rows(enriched_rows))
    write_rows_csv(path, enriched_rows)
    return path


def _run_etenders(date_from: str, date_to: str, page_size: int, refresh: bool) -> Path:
    output_dir = ROOT / "South Africa" / "data-etenders-gov-za"
    output_path = (
        output_dir
        / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}_live_detail_ps2000.csv"
    )
    if output_path.exists() and not refresh:
        print(f"reusing {output_path}")
        return output_path

    chunk_dir = (
        output_dir
        / f"chunks_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}_live_detail_ps2000"
    )
    chunk_dir.mkdir(parents=True, exist_ok=True)
    module = load_source_module("south_africa_etenders")
    chunk_paths: list[Path] = []
    for window_from, window_to in _iter_month_chunks(date_from, date_to, 1):
        chunk_path = chunk_dir / f"{window_from}_to_{window_to}.csv"
        rows = module.live_medical_awarded_rows(window_from, window_to, page_size=page_size)
        write_rows_csv(chunk_path, rows)
        chunk_paths.append(chunk_path)
        print(f"{chunk_path} rows={len(rows)}", flush=True)

    combined_rows: list[dict[str, str]] = []
    for chunk_path in chunk_paths:
        combined_rows.extend(read_rows_csv(chunk_path))
    combined_rows = _dedup_rows(combined_rows)
    if not combined_rows:
        fallback = _best_non_empty_csv(
            output_dir,
            f"medical_awarded_rows_{date_from.replace('-', '_')}_to_*_live_detail_ps2000.csv",
            output_path,
        )
        if fallback is not None:
            fallback_path, fallback_rows = fallback
            combined_rows = fallback_rows
            print(f"reusing fallback {fallback_path}")
    combined_rows = _dedup_rows(module.normalize_saved_rows(combined_rows))
    combined_rows = _dedup_rows(_enrich_rows(combined_rows))
    write_rows_csv(output_path, combined_rows)
    print(f"wrote {output_path}")
    return output_path


def _run_simple_source(
    source_key: str,
    output_path: Path,
    date_from: str,
    date_to: str,
    page_size: int,
    refresh: bool,
) -> Path:
    output_dir = output_path.parent
    if not refresh:
        current_candidate: tuple[Path, list[dict[str, str]]] | None = None
        if output_path.exists():
            current_rows = read_rows_csv(output_path)
            if current_rows:
                current_candidate = (output_path, current_rows)
        fallback = _best_non_empty_csv(
            output_dir,
            f"medical_awarded_rows_{date_from.replace('-', '_')}_to_*.csv",
            output_path,
        )
        best_candidate = current_candidate
        if fallback is not None:
            if best_candidate is None or len(fallback[1]) > len(best_candidate[1]):
                best_candidate = fallback
        if best_candidate is not None:
            source_path, source_rows = best_candidate
            if source_path == output_path:
                print(f"reusing {output_path}")
                return output_path
            write_rows_csv(output_path, _dedup_rows(_enrich_rows(source_rows)))
            print(f"reusing fallback {source_path}")
            print(f"wrote {output_path} rows={len(source_rows)}")
            return output_path
    module = load_source_module(source_key)
    rows = module.live_medical_awarded_rows(date_from, date_to, page_size=page_size)
    rows = _dedup_rows(rows)
    if not rows:
        fallback = _best_non_empty_csv(
            output_dir,
            f"medical_awarded_rows_{date_from.replace('-', '_')}_to_*.csv",
            output_path,
        )
        if fallback is not None:
            fallback_path, fallback_rows = fallback
            rows = fallback_rows
            print(f"reusing fallback {fallback_path}")
    rows = _dedup_rows(_enrich_rows(rows))
    write_rows_csv(output_path, rows)
    print(f"wrote {output_path} rows={len(rows)}")
    return output_path


def main() -> int:
    args = build_parser().parse_args()
    date_from = args.date_from
    date_to = args.date_to

    etenders_path = _run_etenders(date_from, date_to, args.page_size, args.refresh_etenders)
    _rewrite_enriched_output(etenders_path, "south_africa_etenders")
    ndoh_path = _run_simple_source(
        "south_africa_ndoh",
        ROOT / "South Africa" / "health-gov-za" / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}.csv",
        date_from,
        date_to,
        args.page_size,
        args.refresh_simple_sources,
    )
    _rewrite_enriched_output(ndoh_path, "south_africa_ndoh")
    echealth_path = _run_simple_source(
        "south_africa_echealth",
        ROOT / "South Africa" / "echealth-gov-za" / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}.csv",
        date_from,
        date_to,
        args.page_size,
        args.refresh_simple_sources,
    )
    _rewrite_enriched_output(echealth_path, "south_africa_echealth")
    nwpg_path = _run_simple_source(
        "south_africa_nwpg_premier",
        ROOT / "South Africa" / "premier-nwpg-gov-za" / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}.csv",
        date_from,
        date_to,
        args.page_size,
        args.refresh_simple_sources,
    )
    _rewrite_enriched_output(nwpg_path, "south_africa_nwpg_premier")
    ldoh_path = _run_simple_source(
        "south_africa_ldoh",
        ROOT / "South Africa" / "ldoh-gov-za" / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}.csv",
        date_from,
        date_to,
        args.page_size,
        args.refresh_simple_sources,
    )
    _rewrite_enriched_output(ldoh_path, "south_africa_ldoh")
    kznhealth_path = _run_simple_source(
        "south_africa_kznhealth",
        ROOT / "South Africa" / "kznhealth-gov-za" / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}.csv",
        date_from,
        date_to,
        args.page_size,
        args.refresh_simple_sources,
    )
    _rewrite_enriched_output(kznhealth_path, "south_africa_kznhealth")
    kznhealth_quotations_path = _run_simple_source(
        "south_africa_kznhealth_quotations",
        ROOT / "South Africa" / "kznhealth-gov-za-quotations" / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}.csv",
        date_from,
        date_to,
        args.page_size,
        args.refresh_simple_sources,
    )
    _rewrite_enriched_output(kznhealth_quotations_path, "south_africa_kznhealth_quotations")

    combined_rows: list[dict[str, str]] = []
    combined_source_keys = (
        "south_africa_etenders",
        "south_africa_ndoh",
        "south_africa_echealth",
        "south_africa_nwpg_premier",
        "south_africa_ldoh",
        "south_africa_kznhealth",
        "south_africa_kznhealth_quotations",
    )
    for path in (
        etenders_path,
        ndoh_path,
        echealth_path,
        nwpg_path,
        ldoh_path,
        kznhealth_path,
        kznhealth_quotations_path,
    ):
        combined_rows.extend(read_rows_csv(path))
    combined_rows = _dedup_rows(_enrich_rows(combined_rows))
    combined_rows = _dedup_rows(_apply_source_normalizers(combined_rows, combined_source_keys))
    combined_raw_path = (
        ROOT
        / "South Africa"
        / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}_all_sources_raw.csv"
    )
    write_rows_csv(combined_raw_path, combined_rows, columns=SOUTH_AFRICA_FINAL_COLUMNS)
    print(f"wrote {combined_raw_path}")

    healthcare_rows = _dedup_rows(filter_medical_healthcare_rows(combined_rows))
    healthcare_path = (
        ROOT
        / "South Africa"
        / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}_all_sources_healthcare.csv"
    )
    write_rows_csv(healthcare_path, healthcare_rows, columns=SOUTH_AFRICA_FINAL_COLUMNS)
    print(f"wrote {healthcare_path}")

    strict_goods_rows = _dedup_rows(filter_medical_goods_rows(healthcare_rows))
    strict_goods_path = (
        ROOT
        / "South Africa"
        / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}_all_sources_goods.csv"
    )
    write_rows_csv(strict_goods_path, strict_goods_rows, columns=SOUTH_AFRICA_FINAL_COLUMNS)
    print(f"wrote {strict_goods_path}")

    combined_path = (
        ROOT
        / "South Africa"
        / f"medical_awarded_rows_{date_from.replace('-', '_')}_to_{date_to.replace('-', '_')}_all_sources.csv"
    )
    write_rows_csv(combined_path, healthcare_rows, columns=SOUTH_AFRICA_FINAL_COLUMNS)
    print(f"wrote {combined_path}")
    print(f"healthcare_rows={len(healthcare_rows)}")
    print(f"strict_goods_rows={len(strict_goods_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
