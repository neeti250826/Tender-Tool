"""Evidence-safe exact-key reconciliation across Kuwait source layers."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u0600-\u06ff]+", "", (value or "")).casefold()


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--gazette", required=True, type=Path)
    parser.add_argument("--live-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    baseline = read(args.baseline)
    gazette = read(args.gazette)
    live = read(args.live_audit)
    baseline_by_key = {key(row.get("notice_id", "")): row for row in baseline if key(row.get("notice_id", ""))}
    joins: list[dict[str, str]] = []
    for row in gazette:
        match = baseline_by_key.get(key(row.get("AdsTitle", "")))
        if match:
            joins.append({
                "source_layer": "gazette_index",
                "source_notice": row.get("AdsTitle", ""),
                "baseline_notice_id": match.get("notice_id", ""),
                "baseline_title": match.get("title", ""),
                "evidence_url": row.get("viewer_url", ""),
            })
    for row in live:
        match = baseline_by_key.get(key(row.get("tender_no", "")))
        if match:
            joins.append({
                "source_layer": "capt_live_rolling",
                "source_notice": row.get("tender_no", ""),
                "baseline_notice_id": match.get("notice_id", ""),
                "baseline_title": match.get("title", ""),
                "evidence_url": row.get("page_url", ""),
            })
    fields = ["source_layer", "source_notice", "baseline_notice_id", "baseline_title", "evidence_url"]
    with (args.output / "exact_notice_reconciliation.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(joins)
    summary = {
        "baseline_rows": len(baseline),
        "gazette_rows": len(gazette),
        "capt_live_rows": len(live),
        "exact_notice_joins": len(joins),
        "join_rule": "normalized exact identifier only; no fuzzy or substring joins",
    }
    (args.output / "reconciliation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
