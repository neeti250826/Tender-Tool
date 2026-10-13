from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from harness.shared.schema import OUTPUT_COLUMNS


@dataclass(frozen=True)
class AuditTarget:
    label: str
    path: Path


DEFAULT_TARGETS = [
    AuditTarget(
        label="Poland broad enriched",
        path=Path(r"Poland/ezamowienia-gov-pl/medical_awarded_rows_2024_recent_enriched.csv"),
    ),
    AuditTarget(
        label="Czechia broad live",
        path=Path(r"Czechia/nen-nipez-cz/medical_awarded_rows_2024_recent_live.csv"),
    ),
    AuditTarget(
        label="Czechia cached luzko page1",
        path=Path(r"Czechia/nen-nipez-cz/medical_awarded_rows_live_luzko_page1_cached.csv"),
    ),
    AuditTarget(
        label="Czechia cached keyword combo",
        path=Path(r"Czechia/nen-nipez-cz/medical_awarded_rows_2024_recent_cached_combo.csv"),
    ),
    AuditTarget(
        label="South Africa strict recent",
        path=Path(r"South Africa/data-etenders-gov-za/medical_awarded_rows_2024_recent_strict.csv"),
    ),
    AuditTarget(
        label="South Africa award-backed recent",
        path=Path(r"South Africa/data-etenders-gov-za/medical_awarded_rows_2024_recent_award_backed.csv"),
    ),
    AuditTarget(
        label="Egypt GCS smoke",
        path=Path(r"Egypt/gcs-digitalegypt-gov-eg/smoke_sample_rows.csv"),
    ),
    AuditTarget(
        label="Egypt GCS home snapshot",
        path=Path(r"Egypt/gcs-digitalegypt-gov-eg/home_snapshot_rows.csv"),
    ),
    AuditTarget(
        label="Egypt GCS medical home snapshot",
        path=Path(r"Egypt/gcs-digitalegypt-gov-eg/medical_home_snapshot_rows.csv"),
    ),
    AuditTarget(
        label="Egypt GCS live tenders snapshot",
        path=Path(r"Egypt/gcs-digitalegypt-gov-eg/tenders_live_snapshot_2026_06_06.csv"),
    ),
    AuditTarget(
        label="Egypt GCS live healthcare snapshot",
        path=Path(r"Egypt/gcs-digitalegypt-gov-eg/medical_tenders_live_snapshot_2026_06_06.csv"),
    ),
    AuditTarget(
        label="Hungary smoke",
        path=Path(r"Hungary/ekr-gov-hu/smoke_sample_rows.csv"),
    ),
    AuditTarget(
        label="Hungary live 2025-01-05",
        path=Path(r"Hungary/ekr-gov-hu/medical_awarded_rows_live_2025_01_05.csv"),
    ),
    AuditTarget(
        label="Romania smoke",
        path=Path(r"Romania/seap-sicap/smoke_sample_rows.csv"),
    ),
    AuditTarget(
        label="Romania seed 2025",
        path=Path(r"Romania/seap-sicap/medical_awarded_rows_seed_2025.csv"),
    ),
    AuditTarget(
        label="Romania seed 2025-2026",
        path=Path(r"Romania/seap-sicap/medical_awarded_rows_seed_2025_2026.csv"),
    ),
    AuditTarget(
        label="Romania TED 33100000 2024-recent",
        path=Path(r"Romania/seap-sicap/medical_awarded_rows_ted_33100000_2024_recent.csv"),
    ),
    AuditTarget(
        label="Romania TED search full 2024-2026-06-12",
        path=Path(r"Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12.csv"),
    ),
    AuditTarget(
        label="Romania TED search full 2024-2026-06-12 enriched",
        path=Path(r"Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12_enriched.csv"),
    ),
    AuditTarget(
        label="Romania TED search full 2024-2026-06-12 v2 enriched",
        path=Path(r"Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12_v2_enriched.csv"),
    ),
]


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _coverage_count(rows: list[dict[str, str]], column: str) -> int:
    return sum(1 for row in rows if (row.get(column) or "").strip())


def _summarize_target(target: AuditTarget) -> list[dict[str, str]]:
    if not target.path.exists():
        return [
            {
                "label": target.label,
                "path": str(target.path),
                "rows": "0",
                "column": "__missing__",
                "non_empty_count": "0",
                "coverage_pct": "0.00",
            }
        ]

    rows = _read_rows(target.path)
    row_count = len(rows)
    summary_rows: list[dict[str, str]] = []
    for column in OUTPUT_COLUMNS:
        if column in {"source", "country", "country_cc", "scraped_at", "dedup_key"}:
            continue
        non_empty_count = _coverage_count(rows, column)
        coverage_pct = (100.0 * non_empty_count / row_count) if row_count else 0.0
        summary_rows.append(
            {
                "label": target.label,
                "path": str(target.path),
                "rows": str(row_count),
                "column": column,
                "non_empty_count": str(non_empty_count),
                "coverage_pct": f"{coverage_pct:.2f}",
            }
        )
    return summary_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit coverage across current source output CSVs.")
    parser.add_argument(
        "--output",
        default=r"outputs/output_coverage_summary.csv",
        help="Path to write the CSV summary (default: outputs/output_coverage_summary.csv)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, str]] = []
    for target in DEFAULT_TARGETS:
        all_rows.extend(_summarize_target(target))

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["label", "path", "rows", "column", "non_empty_count", "coverage_pct"],
        )
        writer.writeheader()
        writer.writerows(all_rows)

    print(output_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
