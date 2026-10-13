"""Resumable official-EKAP extraction for contracts with requested observed end years.

The EKAP search API cannot filter on contract execution dates.  This runner therefore
indexes the official CPV/tender search results, fetches each tender detail, reads the
contract-linked result-notice HTML, and retains only explicit start/end date pairs
whose end date is in calendar year 2024.  It intentionally does not infer a date
from the tender date, contract-signing date, or an undated duration.

All output lives in a new run directory.  The JSONL state makes the long historical
search resumable: completed CPV/year list groups and already-reviewed tender details
are never re-requested on the next run.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import json
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import ekap_extract as ekap


DEFAULT_YEARS = list(range(2010, datetime.now().year + 1))
DEFAULT_TARGET_END_YEARS = [2024]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def append_jsonl(handle: Any, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
    handle.flush()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def normalize_cpvs(cpvs: list[ekap.CpvRecord]) -> dict[str, dict[str, str]]:
    return {
        item.code: {
            "source_cpv_code": item.code,
            "source_cpv_description": item.description,
            "source_cpv_status": item.status,
            "source_ivd_segment": item.segment,
            "source_procurement_item_type": item.item_type,
        }
        for item in cpvs
    }


def make_source_url(tender_id: str) -> str:
    return f"https://ekapv2.kik.gov.tr/ekap/search/{tender_id}"


def item_tender_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("ihaleId") or "").strip()


def first_present(data: dict[str, Any], candidates: list[str]) -> Any:
    return ekap.first_present(data, candidates)


def iso_date(value: Any) -> str:
    """Return an ISO yyyy-mm-dd date only when the source exposes one."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return ""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            return ""
    return ""


def decode_mojibake(value: str) -> str:
    """Repair the common UTF-8-as-Latin-1 display artefact only when it is evident."""
    if "Ã" not in value and "Å" not in value:
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def html_to_text(value: Any) -> str:
    raw = decode_mojibake(str(value or ""))
    raw = re.sub(r"<(?:br|/tr|/p|/div|/li)\b[^>]*>", "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<(?:td|th)\b[^>]*>", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


# This is deliberately label-bound.  A bare date pair elsewhere in a notice is not
# treated as an execution period.
PERIOD_RE = re.compile(
    r"(?:İşin\s+|Sözleşme(?:nin)?\s+|İhale(?:nin)?\s+)?Süresi(?:\s*/\s*teslim\s+tarihi)?"
    r"\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*(?:-|–|—)\s*(\d{1,2}\.\d{1,2}\.\d{4})",
    flags=re.IGNORECASE,
)


def extract_period_pairs(notice: dict[str, Any]) -> list[dict[str, str]]:
    raw_html = str(notice.get("veriHtml") or "")
    text = html_to_text(raw_html)
    output: list[dict[str, str]] = []
    for match in PERIOD_RE.finditer(text):
        start_date = iso_date(match.group(1))
        end_date = iso_date(match.group(2))
        if not start_date or not end_date or start_date > end_date:
            continue
        snippet_start = max(0, match.start() - 70)
        snippet_end = min(len(text), match.end() + 120)
        output.append(
            {
                "start_date": start_date,
                "end_date": end_date,
                "evidence_excerpt": text[snippet_start:snippet_end],
                "notice_type": str(notice.get("ilanTip") or notice.get("ilanTipAciklama") or ""),
                "notice_date": iso_date(notice.get("ilanTarihi")),
                "notice_contract_id": str(notice.get("sozlesmeId") or ""),
                "notice_html_sha256": sha256_text(raw_html),
            }
        )
    return output


def matched_notice_periods(detail: dict[str, Any], contract: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    """Return only a contract-linked result-notice period, failing closed otherwise."""
    notices = [item for item in (detail.get("ilanList") or []) if isinstance(item, dict)]
    contract_id = str(contract.get("id") or "").strip()
    if not contract_id:
        return [], "missing_contract_id"
    linked = [
        notice
        for notice in notices
        if str(notice.get("sozlesmeId") or "").strip() == contract_id
    ]
    relevant = [notice for notice in linked if str(notice.get("ilanTip") or "").strip() == "4"]
    if not relevant:
        return [], "no_contract_linked_result_notice" if linked else "no_contract_linked_notice"
    pairs: list[dict[str, str]] = []
    for notice in relevant:
        pairs.extend(extract_period_pairs(notice))
    if not pairs:
        return [], "no_label_bound_source_period"
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for pair in pairs:
        key = (pair["start_date"], pair["end_date"])
        unique.setdefault(key, pair)
    values = list(unique.values())
    if len(values) > 1:
        return values, "ambiguous_multiple_source_periods"
    return values, ""


def period_candidates(detail: dict[str, Any], target_end_years: set[int]) -> tuple[list[dict[str, Any]], Counter[str]]:
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
        end_year = int(period["end_date"][:4])
        if end_year not in target_end_years:
            reasons["source_period_ends_outside_requested_years"] += 1
            continue
        candidates.append(
            {
                "contract_index": contract_index,
                "contract_id": str(contract.get("id") or ""),
                "contract": contract,
                "period": period,
                "target_end_year": end_year,
            }
        )
    return candidates, reasons


def make_run_layout(run_dir: Path) -> dict[str, Path]:
    raw_dir = run_dir / "raw"
    paths = {
        "run_dir": run_dir,
        "raw_lists": raw_dir / "list_pages",
        "raw_details": raw_dir / "matched_details",
        "state": run_dir / "state.json",
        "index": run_dir / "tender_index.jsonl",
        "manifest": run_dir / "detail_manifest.jsonl",
        "candidates": run_dir / "candidate_contracts.jsonl",
        "summary": run_dir / "run_summary.json",
        "navigation": run_dir / "navigation.json",
        "audit": run_dir / "period_audit.json",
    }
    for key in ("run_dir", "raw_lists", "raw_details"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def load_state(path: Path, years: list[int], cpv_codes: list[str], target_end_years: list[int]) -> dict[str, Any]:
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            prior_years = state.get("target_end_years") or [state.get("target_end_year")]
            prior_years = sorted({int(value) for value in prior_years if value not in (None, "")})
            if prior_years and prior_years != target_end_years:
                raise ValueError(
                    f"Run directory is configured for target end years {prior_years}, not {target_end_years}. "
                    "Use a separate --out-dir for a different cohort."
                )
            prior_search_years = sorted(
                {int(value) for value in state.get("search_years", []) if value not in (None, "")}
            )
            requested_search_years = sorted(set(years))
            if prior_search_years and prior_search_years != requested_search_years:
                raise ValueError(
                    f"Run directory is configured for tender search years {prior_search_years}, "
                    f"not {requested_search_years}. Use a separate --out-dir for a different source scope."
                )
            prior_cpv_codes = sorted({str(value).strip() for value in state.get("cpv_codes", []) if str(value).strip()})
            requested_cpv_codes = sorted({str(value).strip() for value in cpv_codes if str(value).strip()})
            if requested_cpv_codes and prior_cpv_codes and prior_cpv_codes != requested_cpv_codes:
                raise ValueError(
                    "Run directory is configured for a different CPV scope. "
                    "Use a separate --out-dir for a different source scope."
                )
            return state
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_end_years": target_end_years,
        "search_years": years,
        "cpv_codes": cpv_codes,
        "completed_list_groups": {},
    }


def write_navigation(paths: dict[str, Path], target_end_years: list[int]) -> None:
    if paths["navigation"].exists():
        return
    atomic_json(
        paths["navigation"],
        {
            "source": "EKAP official public tender search",
            "entry_url": "https://ekapv2.kik.gov.tr/ekap/search",
            "list_endpoint": ekap.LIST_ENDPOINT,
            "detail_endpoint": ekap.DETAIL_ENDPOINT,
            "method": "POST JSON with site-observed encrypted request headers",
            "filter_logic": (
                "Search CPV/year candidates, then retain only source-observed contract notice periods "
                f"whose end_date falls in {', '.join(str(year) for year in target_end_years)}."
            ),
        },
    )


def index_groups(
    paths: dict[str, Path],
    cpvs: list[ekap.CpvRecord],
    years: list[int],
    target_end_years: list[int],
    page_size: int,
    sleep_seconds: float,
    list_workers: int,
) -> None:
    state = load_state(paths["state"], years, [item.code for item in cpvs], target_end_years)
    headers = ekap.auth_headers()
    pending = [
        (cpv, year)
        for cpv in cpvs
        for year in years
        if state["completed_list_groups"].get(f"{cpv.code}:{year}", {}).get("status") != "complete"
    ]

    def fetch_group(cpv: ekap.CpvRecord, year: int) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        group_key = f"{cpv.code}:{year}"
        skip = 0
        pages = 0
        items_seen = 0
        records: list[dict[str, Any]] = []
        try:
            while True:
                payload = ekap.list_payload(cpv, year, skip, page_size, "tender")
                data = ekap.post_json(headers, ekap.LIST_ENDPOINT, payload)
                items = data.get("list") or data.get("items") or []
                if not isinstance(items, list):
                    items = []
                total = int(data.get("totalCount") or len(items) or 0)
                page_path = paths["raw_lists"] / f"{cpv.code}_{year}_{pages + 1:04d}.json.gz"
                serialized = compact_json({"request": payload, "response": data})
                with gzip.open(page_path, "wt", encoding="utf-8") as raw_page:
                    raw_page.write(serialized)
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    tender_id = item_tender_id(item)
                    if not tender_id:
                        continue
                    records.append(
                        {
                            "tender_id": tender_id,
                            "search_year": year,
                            "source_cpv_code": cpv.code,
                            "source_cpv_description": cpv.description,
                            "source_cpv_status": cpv.status,
                            "source_ivd_segment": cpv.segment,
                            "source_procurement_item_type": cpv.item_type,
                            "list_item": item,
                            "source_url": make_source_url(tender_id),
                            "raw_page_path": str(page_path.resolve()),
                            "raw_page_sha256": sha256_text(serialized),
                        }
                    )
                    items_seen += 1
                pages += 1
                if not items or items_seen >= total:
                    break
                skip += page_size
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            return group_key, records, {
                "status": "complete",
                "pages": pages,
                "list_item_count": items_seen,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as error:
            return group_key, records, {
                "status": "error",
                "error": str(error),
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            }

    with paths["index"].open("a", encoding="utf-8") as index_handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=list_workers) as executor:
            futures = [executor.submit(fetch_group, cpv, year) for cpv, year in pending]
            for future in concurrent.futures.as_completed(futures):
                group_key, records, group_state = future.result()
                for record in records:
                    append_jsonl(index_handle, record)
                state["completed_list_groups"][group_key] = group_state
                atomic_json(paths["state"], state)
                print(
                    f"INDEX_PROGRESS complete_groups={sum(1 for value in state['completed_list_groups'].values() if value.get('status') == 'complete')} total_pending={len(pending)}",
                    flush=True,
                )


def build_tender_associations(index_path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, int, str]] = set()
    for record in read_jsonl(index_path):
        tender_id = str(record.get("tender_id") or "")
        association_key = (tender_id, int(record.get("search_year") or 0), str(record.get("source_cpv_code") or ""))
        if not tender_id or association_key in seen:
            continue
        seen.add(association_key)
        grouped[tender_id].append(record)
    return dict(grouped)


def reviewed_detail_ids(manifest_path: Path) -> set[str]:
    return {
        str(record.get("tender_id") or "")
        for record in read_jsonl(manifest_path)
        if record.get("status") in {"matched", "unmatched"}
    }


def fetch_and_parse_detail(
    headers: dict[str, str], tender_id: str, target_end_years: set[int]
) -> tuple[dict[str, Any], list[dict[str, Any]], Counter[str]]:
    detail = ekap.fetch_detail(headers, tender_id)
    matches, reasons = period_candidates(detail, target_end_years)
    return detail, matches, reasons


def fetch_details(
    paths: dict[str, Path],
    detail_workers: int,
    sleep_seconds: float,
    target_end_years: set[int],
) -> None:
    associations = build_tender_associations(paths["index"])
    done = reviewed_detail_ids(paths["manifest"])
    pending = [tender_id for tender_id in sorted(associations) if tender_id not in done]
    headers = ekap.auth_headers()
    audit: Counter[str] = Counter()
    progress_lock = threading.Lock()
    completed = 0

    def worker(tender_id: str) -> tuple[str, dict[str, Any], list[dict[str, Any]], Counter[str], str]:
        if sleep_seconds:
            time.sleep(sleep_seconds)
        try:
            detail, matches, reasons = fetch_and_parse_detail(headers, tender_id, target_end_years)
            return tender_id, detail, matches, reasons, ""
        except Exception as error:
            return tender_id, {}, [], Counter({"detail_fetch_error": 1}), str(error)

    with paths["manifest"].open("a", encoding="utf-8") as manifest_handle, paths["candidates"].open("a", encoding="utf-8") as candidate_handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=detail_workers) as executor:
            futures = {executor.submit(worker, tender_id): tender_id for tender_id in pending}
            for future in concurrent.futures.as_completed(futures):
                tender_id, detail, matches, reasons, error = future.result()
                audit.update(reasons)
                if error:
                    append_jsonl(
                        manifest_handle,
                        {
                            "tender_id": tender_id,
                            "status": "error",
                            "error": error,
                            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    continue
                if not matches:
                    append_jsonl(
                        manifest_handle,
                        {
                            "tender_id": tender_id,
                            "status": "unmatched",
                            "reason_counts": dict(reasons),
                            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                else:
                    raw_path = paths["raw_details"] / f"{tender_id}.json"
                    serialized = json.dumps(detail, ensure_ascii=False, indent=2, default=str)
                    raw_path.write_text(serialized, encoding="utf-8")
                    raw_hash = sha256_text(serialized)
                    for match in matches:
                        append_jsonl(
                            candidate_handle,
                            {
                                "tender_id": tender_id,
                                "source_url": make_source_url(tender_id),
                                "associations": associations[tender_id],
                                "contract_index": match["contract_index"],
                                "contract_id": match["contract_id"],
                                "contract": match["contract"],
                                "start_date": match["period"]["start_date"],
                                "end_date": match["period"]["end_date"],
                                "target_end_year": match["target_end_year"],
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
                            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                with progress_lock:
                    completed += 1
                    if completed % 100 == 0 or completed == len(pending):
                        print(f"DETAIL_PROGRESS reviewed={completed} pending_total={len(pending)}", flush=True)
    prior_audit: Counter[str] = Counter()
    if paths["audit"].exists():
        try:
            prior_audit.update(json.loads(paths["audit"].read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    prior_audit.update(audit)
    atomic_json(paths["audit"], dict(prior_audit))


def write_summary(paths: dict[str, Path], years: list[int], target_end_years: list[int]) -> None:
    state = load_state(paths["state"], years, [], target_end_years)
    associations = build_tender_associations(paths["index"])
    manifest = read_jsonl(paths["manifest"])
    candidates = read_jsonl(paths["candidates"])
    # A transient detail error may be retried by a later --stage details invocation.
    # Count the final state per tender, not every historical attempt, in the run summary.
    latest_status_by_tender: dict[str, str] = {}
    for record in manifest:
        tender_id = str(record.get("tender_id") or "")
        status = str(record.get("status") or "")
        if tender_id:
            latest_status_by_tender[tender_id] = status
    status_counts = Counter(latest_status_by_tender.values())
    list_group_status_counts = Counter(
        str(value.get("status") or "unknown")
        for value in state.get("completed_list_groups", {}).values()
        if isinstance(value, dict)
    )
    expected_list_groups = len(state.get("search_years", [])) * len(state.get("cpv_codes", []))
    completed_list_groups = list_group_status_counts.get("complete", 0)
    list_error_count = list_group_status_counts.get("error", 0)
    unreviewed_detail_count = len(set(associations) - set(latest_status_by_tender))
    list_groups_complete = bool(expected_list_groups) and completed_list_groups == expected_list_groups and not list_error_count
    source_scan_complete = list_groups_complete and unreviewed_detail_count == 0
    source_limited = bool(list_error_count or status_counts.get("error", 0))
    candidate_periods = Counter((record.get("start_date"), record.get("end_date")) for record in candidates)
    raw_hashes = []
    for record in candidates:
        raw_hashes.append({"path": record.get("raw_detail_path"), "sha256": record.get("raw_detail_sha256")})
    atomic_json(
        paths["summary"],
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "EKAP official public tender search API",
            "target_end_years": target_end_years,
            "search_years": years,
            "completed_list_groups": completed_list_groups,
            "total_list_groups": expected_list_groups,
            "list_group_status_counts": dict(list_group_status_counts),
            "list_groups_complete": list_groups_complete,
            "unique_tenders_indexed": len(associations),
            "detail_review_status_counts": dict(status_counts),
            "unreviewed_detail_count": unreviewed_detail_count,
            "source_scan_complete": source_scan_complete,
            "source_limited": source_limited,
            "candidate_contract_records": len(candidates),
            "unique_source_observed_periods": len(candidate_periods),
            "candidate_start_years": dict(Counter(str(record.get("start_date") or "")[:4] for record in candidates)),
            "candidate_end_years": dict(Counter(str(record.get("end_date") or "")[:4] for record in candidates)),
            "raw_evidence_hashes": raw_hashes,
            "limitations": [
                "Only label-bound, source-observed start/end pairs are retained.",
                "A retained period must come from an exact contract-linked result notice (ilanTip 4).",
                "Tender dates, contract-signing dates, and duration-only text are not substituted for missing end dates.",
                "The official API has no contract-end filter; coverage is governed by the completed CPV/year search groups.",
            ],
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/ekap_contract_end_2024"))
    parser.add_argument("--years", nargs="+", type=int, default=DEFAULT_YEARS)
    parser.add_argument(
        "--target-end-years",
        nargs="+",
        type=int,
        default=DEFAULT_TARGET_END_YEARS,
        help="One or more calendar years required for source-observed end_date values.",
    )
    parser.add_argument("--statuses", nargs="+", default=["Include", "Optional"])
    parser.add_argument("--limit-cpvs", type=int, default=0, help="Use only the first N CPVs for a bounded smoke test.")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--list-workers", type=int, default=4)
    parser.add_argument("--detail-workers", type=int, default=6)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--stage", choices=["index", "details", "all"], default="all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    current_year = datetime.now().year
    if any(year < 2010 or year > current_year for year in args.years):
        raise SystemExit(f"Tender search years must be within 2010 through {current_year}.")
    target_end_years = sorted(set(args.target_end_years))
    if any(year < 2010 or year > current_year for year in target_end_years):
        raise SystemExit(f"Target end years must be within 2010 through {current_year}.")
    years = sorted(set(args.years))
    cpvs = ekap.load_cpvs(Path("Turkey_IVD_CPV_Master_Codebook.xlsx"), set(args.statuses))
    if args.limit_cpvs:
        cpvs = cpvs[: args.limit_cpvs]
    paths = make_run_layout(args.out_dir)
    write_navigation(paths, target_end_years)
    if args.stage in {"index", "all"}:
        index_groups(paths, cpvs, years, target_end_years, args.page_size, args.sleep, args.list_workers)
    if args.stage in {"details", "all"}:
        fetch_details(paths, args.detail_workers, args.sleep, set(target_end_years))
    write_summary(paths, years, target_end_years)
    print(f"Run artifacts: {paths['run_dir'].resolve()}")


if __name__ == "__main__":
    main()
