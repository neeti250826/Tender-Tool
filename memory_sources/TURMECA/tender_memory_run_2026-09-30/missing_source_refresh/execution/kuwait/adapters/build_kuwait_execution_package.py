"""Build combined audit files and immutable hashes for the Kuwait refresh."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[3]
CANONICAL = [
    "source", "country", "country_code", "publication_date", "title",
    "title_english", "description", "description_english", "buyer",
    "buyer_english", "classification", "status", "currency", "amount",
    "awarding_agency_name", "awarding_agency_name_english", "supplier_name",
    "supplier_name_english", "awarded_date", "contract_period",
    "contract_period_english", "item_no", "item_description",
    "item_description_english", "item_uom", "item_uom_english", "quantity",
    "notice_id", "notice_url", "_source_workbook",
    "_duplicate_rows_removed", "_dedupe_key", "medtech_filter_basis",
    "mapped_oem", "mapped_oem_basis", "mapped_oem_match_term", "likely_oem",
    "likely_oem_score", "oem_match_terms", "oem_match_basis",
    "medtech_confidence",
]
REJECT = [
    "source", "publication_date", "page", "notice_id", "title_or_subject",
    "buyer", "supplier", "amount", "currency", "outcome", "reason",
    "evidence_url", "evidence_file", "evidence_sha256",
]


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    combined = ROOT / "candidate_awards_combined.csv"
    with combined.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=CANONICAL).writeheader()

    rejections: list[dict[str, str]] = []
    winning = ROOT / "sources" / "capt_winning_bids" / "rejection_audit.csv"
    for row in read(winning):
        rejections.append({
            "source": "CAPT Winning Bids - live rolling window",
            "publication_date": row["meeting_date"],
            "page": row["page"],
            "notice_id": row["tender_no"],
            "title_or_subject": row["subject"],
            "buyer": row["organisation"],
            "supplier": row["winner"],
            "amount": row["total"],
            "currency": "",
            "outcome": row["decision"],
            "reason": row["reason"],
            "evidence_url": row["page_url"],
            "evidence_file": str(winning.resolve()),
            "evidence_sha256": digest(winning),
        })
    board = ROOT / "sources" / "capt_board_minutes" / "rejection_audit.csv"
    for row in read(board):
        rejections.append({
            "source": "CAPT board minutes",
            "publication_date": row["publication_date"],
            "page": row["page"],
            "notice_id": row["notice_id"],
            "title_or_subject": row["subject_english"],
            "buyer": "Ministry of Health",
            "supplier": row["supplier"],
            "amount": row["amount"],
            "currency": row["currency"],
            "outcome": row["outcome"],
            "reason": row["reason"],
            "evidence_url": row["evidence_url"],
            "evidence_file": row["local_file"],
            "evidence_sha256": row["pdf_sha256"],
        })
    rejected = ROOT / "rejection_audit_combined.csv"
    with rejected.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REJECT)
        writer.writeheader()
        writer.writerows(rejections)

    screenshots = [
        WORKSPACE / "output/playwright/kuwait_missing_source_refresh/01_gazette_moh_search.png",
        WORKSPACE / "output/playwright/kuwait_missing_source_refresh/02_gazette_viewer_subscription_required.png",
        WORKSPACE / "output/playwright/kuwait_missing_source_refresh/03_capt_winning_bids_live.png",
        WORKSPACE / "output/playwright/kuwait_missing_source_refresh/04_capt_2026_meeting5_page65_nonapproval.png",
        WORKSPACE / "output/playwright/kuwait_missing_source_refresh/05_capt_2026_meeting5_page59_pipeline.png",
    ]
    files = [p for p in ROOT.rglob("*") if p.is_file() and p.name not in {"evidence_manifest.json", "deliverables_manifest.json"}]
    files.extend(path for path in screenshots if path.exists())
    evidence = []
    for path in sorted(set(files), key=lambda value: str(value).casefold()):
        evidence.append({
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        })
    evidence_path = ROOT / "evidence_manifest.json"
    evidence_path.write_text(
        json.dumps({"generated_at_utc": datetime.now(timezone.utc).isoformat(), "files": evidence}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    required = [
        combined, rejected, ROOT / "source_ledger.csv", ROOT / "access_gaps.json",
        ROOT / "navigation.json", ROOT / "handoff.md", evidence_path,
        ROOT / "reconciliation/exact_notice_reconciliation.csv",
        ROOT / "reconciliation/reconciliation_summary.json",
    ]
    delivery = {
        "country": "Kuwait",
        "scope": "2024-01-01 through 2026-09-30; awarded/final-result medtech only",
        "new_candidate_rows": 0,
        "combined_rejected_rows": len(rejections),
        "gazette_index_rows": 1983,
        "delivery_ready": False,
        "source_limited": True,
        "baseline_changed": False,
        "manufacturer_aliases_approved": 0,
        "files": [
            {"path": str(path.resolve()), "sha256": digest(path), "bytes": path.stat().st_size}
            for path in required
        ],
    }
    (ROOT / "deliverables_manifest.json").write_text(
        json.dumps(delivery, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"candidate_rows": 0, "rejected_rows": len(rejections), "hashed_files": len(evidence)}))


if __name__ == "__main__":
    main()
