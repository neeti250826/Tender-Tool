"""Validate and hash the immutable Kuwait repair_v2 package."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INPUT_HASHES = {
    "baseline_normalized_tender_data.csv": "d0df7b742e25f6a4796c95f53ae388316c5b155601e861e0888cade00977e32f",
    "business_rules.json": "794c507a7ee92d9b7aac71ddb900da8d5a1a8a382b2fc656904bab36afcfcdd7",
    "feedback_overrides.json": "fec0addc96df24d137152647a1aa30f35aec855e863d4c07ae9d4bdaea93f10d",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def csv_count(path: Path) -> tuple[int, list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = sum(1 for _ in reader)
        return rows, list(reader.fieldnames or [])


def main() -> None:
    candidate_rows, candidate_fields = csv_count(ROOT / "candidate_awards_combined.csv")
    rejection_rows, _ = csv_count(ROOT / "rejection_audit_combined.csv")
    if candidate_rows != 0 or len(candidate_fields) != 41:
        raise RuntimeError("Candidate output must remain 0 rows with 41 canonical columns")
    if rejection_rows != 41:
        raise RuntimeError("Combined v1 rejection audit must remain 41 rows")

    frozen_dir = ROOT / "inputs" / "frozen_inputs"
    frozen_results = {}
    for name, expected in EXPECTED_INPUT_HASHES.items():
        actual = digest(frozen_dir / name)
        if actual != expected:
            raise RuntimeError(f"Frozen input hash mismatch: {name}")
        frozen_results[name] = actual

    gazette = json.loads(
        (ROOT / "sources" / "gazette_repair" / "gazette_repair_summary.json").read_text(encoding="utf-8")
    )
    exact = {
        "v1_rows_returned": 1983,
        "v1_unique_ads_ids": 1938,
        "v1_repeated_rows": 45,
        "monthly_rows_returned": 1983,
        "monthly_unique_ads_ids": 1983,
        "monthly_repeated_rows": 0,
        "v1_only_ids": 0,
        "monthly_only_ids": 45,
    }
    for key, expected in exact.items():
        if gazette.get(key) != expected:
            raise RuntimeError(f"Gazette repair count mismatch: {key}")
    if gazette.get("v1_stable_sort_proven") is not False:
        raise RuntimeError("V1 stable-sort limitation must remain explicit")

    excluded = {"evidence_manifest.json", "deliverables_manifest.json"}
    files = [path for path in ROOT.rglob("*") if path.is_file() and path.name not in excluded]
    evidence = [
        {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(files, key=lambda value: str(value).casefold())
    ]
    evidence_path = ROOT / "evidence_manifest.json"
    evidence_path.write_text(
        json.dumps({
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "parent_run_preserved": True,
            "file_count": len(evidence),
            "files": evidence,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    required_names = [
        "candidate_awards_combined.csv", "rejection_audit_combined.csv",
        "repair_targets.json", "repair_log.json", "frozen_inputs_manifest.json",
        "source_access_summary.json", "source_ledger.csv", "access_gaps.json",
        "qc_findings.json", "handoff.md", "evidence_manifest.json",
        "reconciliation/reconciliation_summary.json",
        "reconciliation/exact_notice_reconciliation.csv",
        "sources/gazette_repair/gazette_repair_summary.json",
        "sources/gazette_repair/gazette_v1_deduplicated_ads_id_manifest.csv",
        "sources/gazette_repair/gazette_v1_duplicate_ads_ids.csv",
        "sources/gazette_repair/gazette_monthly_sweep_deduplicated_ads_id_manifest.csv",
        "sources/gazette_repair/gazette_sweep_set_differences.csv",
    ]
    required = [ROOT / name for name in required_names]
    for path in required:
        if not path.exists():
            raise RuntimeError(f"Missing required artifact: {path}")
    delivery = {
        "country": "Kuwait",
        "run": "repair_v2",
        "parent_run_preserved": True,
        "reviewer_findings_addressed": ["RV-KW-001", "RV-KW-002"],
        "candidate_rows": candidate_rows,
        "rejection_rows": rejection_rows,
        "gazette_v1_rows_returned": 1983,
        "gazette_v1_unique_ads_ids": 1938,
        "gazette_v1_repeated_rows": 45,
        "gazette_monthly_rows_returned": 1983,
        "gazette_monthly_unique_ads_ids": 1983,
        "gazette_monthly_repeated_rows": 0,
        "baseline_rows": 19,
        "baseline_changed": False,
        "frozen_input_hashes": frozen_results,
        "delivery_ready": False,
        "source_limited": True,
        "merge_performed": False,
        "independent_re_review_required": True,
        "files": [
            {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in required
        ],
    }
    (ROOT / "deliverables_manifest.json").write_text(
        json.dumps(delivery, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "candidate_rows": candidate_rows,
        "rejection_rows": rejection_rows,
        "evidence_files": len(evidence),
        "frozen_inputs_verified": len(frozen_results),
    }))


if __name__ == "__main__":
    main()
