"""Manifest-driven CAPT board-minutes evidence adapter."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


CANONICAL_COLUMNS = [
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
AUDIT_COLUMNS = [
    "meeting", "publication_date", "page", "decision_no", "notice_id",
    "subject_english", "supplier", "amount", "currency", "outcome",
    "reason", "evidence_url", "local_file", "pdf_sha256",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Adapter:
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path

    def extract(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        rows: list[dict[str, Any]] = []
        for doc in payload["documents"]:
            for decision in doc["medical_decisions"]:
                if decision.get("award_eligible"):
                    raise RuntimeError(
                        "Award-eligible manifest entries require a separately reviewed canonical mapper"
                    )
        return rows


def create_adapter(url: str) -> Adapter:
    return Adapter(Path(url))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    audit: list[dict[str, Any]] = []
    for document in payload["documents"]:
        local_file = (args.manifest.parent / document["local_file"]).resolve()
        actual = digest(local_file)
        if actual.casefold() != document["sha256"].casefold():
            raise RuntimeError(f"PDF hash mismatch: {local_file}")
        for decision in document["medical_decisions"]:
            if decision.get("award_eligible"):
                raise RuntimeError("This run expected only non-award/pipeline medical decisions")
            audit.append({
                "meeting": document["meeting"],
                "publication_date": document["publication_date"],
                "page": decision["page"],
                "decision_no": decision["decision_no"],
                "notice_id": decision["notice_id"],
                "subject_english": decision["subject_english"],
                "supplier": decision.get("supplier", ""),
                "amount": decision.get("amount", ""),
                "currency": decision.get("currency", ""),
                "outcome": decision["outcome"],
                "reason": decision["reason"],
                "evidence_url": document["url"] + f"#page={decision['page']}",
                "local_file": str(local_file),
                "pdf_sha256": actual,
            })
    with (args.output / "candidate_awards.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS).writeheader()
    with (args.output / "rejection_audit.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(audit)
    meta = {
        "documents_verified": len(payload["documents"]),
        "medical_decisions_reviewed": len(audit),
        "accepted_awards": 0,
        "rejected_or_pipeline": len(audit),
    }
    (args.output / "run_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
