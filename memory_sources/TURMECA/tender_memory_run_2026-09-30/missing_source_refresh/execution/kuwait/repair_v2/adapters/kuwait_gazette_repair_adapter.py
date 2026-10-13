"""Repair Kuwait Al-Youm coverage accounting without overwriting v1.

This script (1) audits/deduplicates the frozen v1 offset-pagination output and
(2) runs non-overlapping calendar-month windows, each fetched in one bounded
request.  The monthly sweep avoids cross-page drift when every window fits in
the requested length. It still does not turn index metadata into award facts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = "https://kuwaitalyawm.media.gov.kw/search/Get"
FIELDS = [
    "EditionID_FK", "Ads_ID", "AdsTitle", "EditionsType", "Agent",
    "AdsCategory", "EditionNo", "EditionDate", "HijriDate", "FromPage",
    "ToPage", "ToPageNew", "viewer_url", "index_evidence_url",
    "award_evidence_status",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def month_windows(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        next_month = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
        last = min(end, date.fromordinal(next_month.toordinal() - 1))
        yield max(start, cursor), last
        cursor = next_month


def fetch(params: dict[str, str]) -> tuple[bytes, dict]:
    url = ENDPOINT + "?" + urlencode(params)
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; TenderEvidenceRepair/1.0)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://kuwaitalyawm.media.gov.kw/search/customindex",
    })
    with urlopen(req, timeout=90) as response:
        body = response.read()
    return body, json.loads(body)


def add_derived(row: dict, query_url: str) -> dict:
    copy = dict(row)
    copy["viewer_url"] = f"https://kuwaitalyawm.media.gov.kw/flip/index/{row['EditionID_FK']}?no={row['FromPage']}"
    copy["index_evidence_url"] = query_url
    copy["award_evidence_status"] = "index_only_not_award_evidence"
    return copy


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1-manifest", required=True, type=Path)
    parser.add_argument("--v1-metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    raw_dir = args.output / "raw_monthly"
    raw_dir.mkdir()

    with args.v1_manifest.open(encoding="utf-8-sig", newline="") as handle:
        v1_rows = list(csv.DictReader(handle))
    v1_meta = json.loads(args.v1_metadata.read_text(encoding="utf-8"))
    source_by_id: dict[str, list[str]] = defaultdict(list)
    for request in v1_meta["requests"]:
        raw_path = Path(request["raw_file"])
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        for row in payload["data"]:
            source_by_id[str(row["Ads_ID"])].append(raw_path.name)
    counts = Counter(str(row["Ads_ID"]) for row in v1_rows)
    duplicate_ids = sorted(identifier for identifier, count in counts.items() if count > 1)
    dedup = {}
    for row in v1_rows:
        dedup.setdefault(str(row["Ads_ID"]), row)
    dedup_rows = sorted(dedup.values(), key=lambda row: int(row["Ads_ID"]))
    write_csv(args.output / "gazette_v1_deduplicated_ads_id_manifest.csv", dedup_rows, FIELDS)
    duplicate_rows = [
        {
            "Ads_ID": identifier,
            "occurrences": counts[identifier],
            "raw_files": "|".join(source_by_id[identifier]),
            "crosses_adjacent_pages": str(len(set(source_by_id[identifier])) > 1).lower(),
        }
        for identifier in duplicate_ids
    ]
    write_csv(
        args.output / "gazette_v1_duplicate_ads_ids.csv",
        duplicate_rows,
        ["Ads_ID", "occurrences", "raw_files", "crosses_adjacent_pages"],
    )

    monthly_rows: list[dict] = []
    windows: list[dict] = []
    for index, (start, end) in enumerate(month_windows(date(2024, 1, 1), date(2026, 9, 30)), start=1):
        params = {
            "draw": str(index), "start": "0", "length": "1000",
            "search[value]": "", "search[regex]": "false", "AgentsID": "1",
            "fromDate": start.strftime("%Y/%m/%d"), "toDate": end.strftime("%Y/%m/%d"),
        }
        query_url = ENDPOINT + "?" + urlencode(params)
        body, payload = fetch(params)
        expected = int(payload["recordsFiltered"])
        rows = payload["data"]
        raw_path = raw_dir / f"gazette_{start:%Y%m}.json"
        raw_path.write_bytes(body)
        if expected > int(params["length"]):
            raise RuntimeError(f"Monthly window exceeds bounded length: {start} {expected}")
        if len(rows) != expected:
            raise RuntimeError(f"Monthly window incomplete: {start} fetched {len(rows)} of {expected}")
        monthly_rows.extend(add_derived(row, query_url) for row in rows)
        windows.append({
            "from": start.isoformat(), "to": end.isoformat(), "records_filtered": expected,
            "rows_returned": len(rows), "unique_ads_ids": len({str(row['Ads_ID']) for row in rows}),
            "raw_file": str(raw_path.resolve()), "sha256": sha256(raw_path),
        })

    monthly_counts = Counter(str(row["Ads_ID"]) for row in monthly_rows)
    monthly_unique = {}
    for row in monthly_rows:
        monthly_unique.setdefault(str(row["Ads_ID"]), row)
    monthly_dedup = sorted(monthly_unique.values(), key=lambda row: int(row["Ads_ID"]))
    write_csv(args.output / "gazette_monthly_sweep_manifest.csv", monthly_rows, FIELDS)
    write_csv(args.output / "gazette_monthly_sweep_deduplicated_ads_id_manifest.csv", monthly_dedup, FIELDS)

    v1_set, monthly_set = set(dedup), set(monthly_unique)
    comparison_rows = (
        [{"Ads_ID": value, "set_status": "monthly_only"} for value in sorted(monthly_set - v1_set)]
        + [{"Ads_ID": value, "set_status": "v1_only"} for value in sorted(v1_set - monthly_set)]
    )
    write_csv(args.output / "gazette_sweep_set_differences.csv", comparison_rows, ["Ads_ID", "set_status"])

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "v1_manifest_path": str(args.v1_manifest.resolve()),
        "v1_manifest_sha256": sha256(args.v1_manifest),
        "v1_rows_returned": len(v1_rows),
        "v1_unique_ads_ids": len(dedup),
        "v1_duplicate_ads_id_groups": len(duplicate_ids),
        "v1_repeated_rows": len(v1_rows) - len(dedup),
        "v1_stable_sort_proven": False,
        "v1_unique_completeness_claim": False,
        "monthly_windows": len(windows),
        "monthly_rows_returned": len(monthly_rows),
        "monthly_unique_ads_ids": len(monthly_unique),
        "monthly_duplicate_ads_id_groups": sum(1 for count in monthly_counts.values() if count > 1),
        "monthly_repeated_rows": len(monthly_rows) - len(monthly_unique),
        "monthly_max_window_rows": max(window["rows_returned"] for window in windows),
        "monthly_all_windows_single_request_complete": all(
            window["rows_returned"] == window["records_filtered"] for window in windows
        ),
        "v1_only_ids": len(v1_set - monthly_set),
        "monthly_only_ids": len(monthly_set - v1_set),
        "set_equal": v1_set == monthly_set,
        "award_rows_emitted": 0,
        "coverage_conclusion": "V1 has 1,983 returned rows but only 1,938 unique Ads_ID values; unique completeness is not claimed. The non-overlapping monthly sweep is a bounded verification independent of offset page boundaries.",
        "windows": windows,
    }
    (args.output / "gazette_repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in (
        "v1_rows_returned", "v1_unique_ads_ids", "v1_repeated_rows",
        "monthly_rows_returned", "monthly_unique_ads_ids", "monthly_repeated_rows",
        "v1_only_ids", "monthly_only_ids", "set_equal",
    )}))


if __name__ == "__main__":
    main()
