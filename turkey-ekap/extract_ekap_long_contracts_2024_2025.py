"""Resumable official-EKAP scan for long-duration 2024/2025 contract starts.

Scope
-----
Retain a contract only where an official EKAP result notice linked to that exact
contract exposes a label-bound execution period with:

* start_date in calendar year 2024 or 2025; and
* end_date on or after 2027-01-01.

EKAP's search endpoint cannot filter on execution dates. This script therefore
reuses the complete CPV/tender index from the previous 2024-2026 extraction,
retrieves official tender detail, and fails closed unless the contract-linked
result notice (ilanTip 4) contains one unambiguous source-observed date pair.

It deliberately writes a fresh run directory and does not modify the earlier
2024-2026 extraction or its evidence.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ekap_extract as ekap
from extract_ekap_contract_end_2024 import (
    build_tender_associations,
    matched_notice_periods,
    read_jsonl,
)


DEFAULT_SOURCE_INDEX = Path("outputs/ekap_contract_end_2025_2026_source/tender_index.jsonl")
DEFAULT_OUT_DIR = Path("outputs/ekap_long_contracts_start_2024_2025_end_2027_plus_source")
DEFAULT_START_YEARS = (2024, 2025)
DEFAULT_MIN_END_DATE = "2027-01-01"
TERMINAL_MANIFEST_STATUSES = {
    "matched",
    "unmatched",
    # Written only by the controlled source-limit disposition step. It does
    # not assert that the tender failed the period predicate: the execution
    # period is unverified and the completed run remains source-limited.
    "excluded_unverifiable_execution_period",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def append_jsonl(handle: Any, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
    handle.flush()


def make_layout(run_dir: Path) -> dict[str, Path]:
    raw_details = run_dir / "raw" / "matched_details"
    paths = {
        "run_dir": run_dir,
        "raw_details": raw_details,
        "manifest": run_dir / "detail_manifest.jsonl",
        "candidates": run_dir / "candidate_contracts.jsonl",
        "summary": run_dir / "run_summary.json",
        "state": run_dir / "state.json",
        "audit": run_dir / "period_audit.json",
    }
    raw_details.mkdir(parents=True, exist_ok=True)
    return paths


def terminal_ids(manifest_path: Path) -> set[str]:
    latest: dict[str, str] = {}
    for record in read_jsonl(manifest_path):
        tender_id = str(record.get("tender_id") or "")
        status = str(record.get("status") or "")
        if tender_id:
            latest[tender_id] = status
    return {tender_id for tender_id, status in latest.items() if status in TERMINAL_MANIFEST_STATUSES}


def latest_statuses(manifest_path: Path) -> dict[str, str]:
    latest: dict[str, str] = {}
    for record in read_jsonl(manifest_path):
        tender_id = str(record.get("tender_id") or "")
        status = str(record.get("status") or "")
        if tender_id:
            latest[tender_id] = status
    return latest


def long_period_candidates(
    detail: dict[str, Any], start_years: set[int], min_end_date: str
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Return exact-contract records meeting the requested start/end predicate."""
    contracts = detail.get("sozlesmeBilgiList") or []
    if not isinstance(contracts, list) or not contracts:
        return [], Counter({"no_contract_record": 1})

    candidates: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for contract_index, raw_contract in enumerate(contracts, start=1):
        contract = raw_contract if isinstance(raw_contract, dict) else {}
        periods, reason = matched_notice_periods(detail, contract)
        if reason:
            reasons[reason] += 1
            continue
        period = periods[0]
        start_date = str(period["start_date"])
        end_date = str(period["end_date"])
        start_year = int(start_date[:4])
        if start_year not in start_years:
            reasons["source_period_starts_outside_requested_years"] += 1
            continue
        if end_date < min_end_date:
            reasons["source_period_ends_before_requested_minimum"] += 1
            continue
        candidates.append(
            {
                "contract_index": contract_index,
                "contract_id": str(contract.get("id") or ""),
                "contract": contract,
                "period": period,
                "cohort_start_year": start_year,
                "cohort_min_end_date": min_end_date,
            }
        )
    return candidates, reasons


def write_state(
    paths: dict[str, Path], source_index: Path, source_sha256: str, start_years: list[int], min_end_date: str
) -> None:
    state = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_index": str(source_index.resolve()),
        "source_index_sha256": source_sha256,
        "start_years": start_years,
        "minimum_end_date": min_end_date,
        "scope_rule": (
            "Official result-notice execution period starts in one requested calendar year "
            "and ends on or after the requested minimum date."
        ),
    }
    if paths["state"].exists():
        prior = json.loads(paths["state"].read_text(encoding="utf-8"))
        invariants = ("source_index_sha256", "start_years", "minimum_end_date")
        for key in invariants:
            if prior.get(key) != state.get(key):
                raise ValueError(
                    f"Run directory has incompatible {key}: {prior.get(key)!r}; use a separate --out-dir."
                )
        return
    atomic_json(paths["state"], state)


def scan_details(
    paths: dict[str, Path], associations: dict[str, list[dict[str, Any]]], start_years: set[int],
    min_end_date: str, detail_workers: int, sleep_seconds: float, limit: int
) -> None:
    done = terminal_ids(paths["manifest"])
    all_ids = sorted(associations)
    pending = [tender_id for tender_id in all_ids if tender_id not in done]
    if limit:
        pending = pending[:limit]
    headers = ekap.auth_headers()
    audit = Counter()
    progress_lock = threading.Lock()
    completed = 0

    def worker(tender_id: str) -> tuple[str, dict[str, Any], list[dict[str, Any]], Counter[str], str]:
        if sleep_seconds:
            time.sleep(sleep_seconds)
        try:
            detail = ekap.fetch_detail(headers, tender_id)
            matches, reasons = long_period_candidates(detail, start_years, min_end_date)
            return tender_id, detail, matches, reasons, ""
        except Exception as error:  # errors are written and retried on a later invocation
            return tender_id, {}, [], Counter({"detail_fetch_error": 1}), str(error)

    with paths["manifest"].open("a", encoding="utf-8") as manifest_handle, paths["candidates"].open(
        "a", encoding="utf-8"
    ) as candidate_handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=detail_workers) as executor:
            futures = {executor.submit(worker, tender_id): tender_id for tender_id in pending}
            for future in concurrent.futures.as_completed(futures):
                tender_id, detail, matches, reasons, error = future.result()
                audit.update(reasons)
                timestamp = datetime.now(timezone.utc).isoformat()
                if error:
                    append_jsonl(
                        manifest_handle,
                        {"tender_id": tender_id, "status": "error", "error": error, "checked_at_utc": timestamp},
                    )
                elif not matches:
                    append_jsonl(
                        manifest_handle,
                        {
                            "tender_id": tender_id,
                            "status": "unmatched",
                            "reason_counts": dict(reasons),
                            "checked_at_utc": timestamp,
                        },
                    )
                else:
                    raw_path = paths["raw_details"] / f"{tender_id}.json"
                    serialized = json.dumps(detail, ensure_ascii=False, indent=2, default=str)
                    # Write/hash exactly the same bytes.  On Windows write_text may
                    # newline-translate LF to CRLF, so hashing the Python string
                    # before writing does not prove the retained raw evidence.
                    raw_bytes = serialized.encode("utf-8")
                    raw_path.write_bytes(raw_bytes)
                    raw_hash = sha256_file(raw_path)
                    for match in matches:
                        append_jsonl(
                            candidate_handle,
                            {
                                "tender_id": tender_id,
                                "source_url": f"https://ekapv2.kik.gov.tr/ekap/search/{tender_id}",
                                "associations": associations[tender_id],
                                "contract_index": match["contract_index"],
                                "contract_id": match["contract_id"],
                                "contract": match["contract"],
                                "start_date": match["period"]["start_date"],
                                "end_date": match["period"]["end_date"],
                                "cohort_start_year": match["cohort_start_year"],
                                "cohort_min_end_date": match["cohort_min_end_date"],
                                "period_evidence": match["period"],
                                "raw_detail_path": str(raw_path.resolve()),
                                "raw_detail_sha256": raw_hash,
                            },
                        )
                    append_jsonl(
                        manifest_handle,
                        {
                            "tender_id": tender_id,
                            "status": "matched",
                            "matched_contracts": len(matches),
                            "raw_detail_path": str(raw_path.resolve()),
                            "raw_detail_sha256": raw_hash,
                            "checked_at_utc": timestamp,
                        },
                    )
                with progress_lock:
                    completed += 1
                    if completed % 100 == 0 or completed == len(pending):
                        print(f"DETAIL_PROGRESS reviewed={completed} pending_total={len(pending)}", flush=True)

    prior = Counter()
    if paths["audit"].exists():
        prior.update(json.loads(paths["audit"].read_text(encoding="utf-8")))
    prior.update(audit)
    atomic_json(paths["audit"], dict(prior))


def write_summary(
    paths: dict[str, Path], associations: dict[str, list[dict[str, Any]]], start_years: list[int], min_end_date: str
) -> None:
    status_records: dict[str, dict[str, Any]] = {}
    for record in read_jsonl(paths["manifest"]):
        tender_id = str(record.get("tender_id") or "")
        if tender_id:
            status_records[tender_id] = record
    statuses = {tender_id: str(record.get("status") or "") for tender_id, record in status_records.items()}
    status_counts = Counter(statuses.values())
    candidates = read_jsonl(paths["candidates"])
    all_ids = set(associations)
    exclusions = [
        {
            "tender_id": tender_id,
            "disposition": str(record.get("disposition") or "excluded_unverifiable_execution_period"),
            "reason": str(record.get("reason") or ""),
            "exception_file": str(record.get("exception_file") or ""),
        }
        for tender_id, record in sorted(status_records.items())
        if str(record.get("status") or "") == "excluded_unverifiable_execution_period"
    ]
    source_scan_complete = len(all_ids - set(statuses)) == 0 and status_counts.get("error", 0) == 0
    evidence_hashes = sorted(
        {
            (str(record.get("raw_detail_path") or ""), str(record.get("raw_detail_sha256") or ""))
            for record in candidates
        }
    )
    atomic_json(
        paths["summary"],
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "EKAP official public tender search API",
            "scope": {
                "start_years": start_years,
                "minimum_end_date": min_end_date,
                "rule": "start_date is in requested start_years and end_date >= minimum_end_date",
            },
            "unique_tenders_indexed": len(all_ids),
            "detail_review_status_counts": dict(status_counts),
            "unreviewed_detail_count": len(all_ids - set(statuses)),
            "source_scan_complete": source_scan_complete,
            "source_limited": bool(status_counts.get("error", 0) or exclusions),
            "source_unavailable_exclusion_count": len(exclusions),
            "source_unavailable_exclusions": exclusions,
            "candidate_contract_records": len(candidates),
            "candidate_start_years": dict(Counter(str(row.get("start_date") or "")[:4] for row in candidates)),
            "candidate_end_years": dict(Counter(str(row.get("end_date") or "")[:4] for row in candidates)),
            "raw_evidence_hashes": [{"path": path, "sha256": digest} for path, digest in evidence_hashes],
            "limitations": [
                "Only label-bound, source-observed start/end pairs are retained.",
                "A retained period must come from an exact contract-linked result notice (ilanTip 4).",
                "Tender dates, contract-signing dates, and duration-only text are not substituted for missing end dates.",
                "The official API has no contract-period filter; every indexed tender detail is reviewed.",
            ],
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, default=DEFAULT_SOURCE_INDEX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--start-years", nargs="+", type=int, default=list(DEFAULT_START_YEARS))
    parser.add_argument("--minimum-end-date", default=DEFAULT_MIN_END_DATE)
    parser.add_argument("--detail-workers", type=int, default=6)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--limit", type=int, default=0, help="Bound one resumable test pass to N not-yet-reviewed tenders.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_years = sorted(set(args.start_years))
    if not start_years or any(year < 2010 or year > datetime.now().year for year in start_years):
        raise SystemExit("start-years must be valid historical calendar years.")
    if len(args.minimum_end_date) != 10 or args.minimum_end_date < "2010-01-01":
        raise SystemExit("minimum-end-date must be a YYYY-MM-DD date.")
    if not args.source_index.exists():
        raise SystemExit(f"Missing source index: {args.source_index}")
    if args.detail_workers < 1:
        raise SystemExit("detail-workers must be at least 1.")

    paths = make_layout(args.out_dir)
    source_index = args.source_index.resolve()
    write_state(paths, source_index, sha256_file(source_index), start_years, args.minimum_end_date)
    associations = build_tender_associations(source_index)
    scan_details(
        paths,
        associations,
        set(start_years),
        args.minimum_end_date,
        args.detail_workers,
        args.sleep,
        args.limit,
    )
    write_summary(paths, associations, start_years, args.minimum_end_date)
    print(f"Run artifacts: {paths['run_dir'].resolve()}")


if __name__ == "__main__":
    main()
