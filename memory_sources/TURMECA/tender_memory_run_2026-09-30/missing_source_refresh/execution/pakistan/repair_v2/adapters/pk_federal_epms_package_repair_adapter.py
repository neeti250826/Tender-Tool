#!/usr/bin/env python3
"""Immutable v2 repair adapter for PPRA EPMS package-level final evaluations."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


SCHEMA = [
    "source", "country", "country_code", "publication_date", "title", "title_english",
    "description", "description_english", "buyer", "buyer_english", "classification",
    "status", "currency", "amount", "awarding_agency_name", "awarding_agency_name_english",
    "supplier_name", "supplier_name_english", "awarded_date", "contract_period",
    "contract_period_english", "item_no", "item_description", "item_description_english",
    "item_uom", "item_uom_english", "quantity", "notice_id", "notice_url",
    "_source_workbook", "_duplicate_rows_removed", "_dedupe_key", "medtech_filter_basis",
    "mapped_oem", "mapped_oem_basis", "mapped_oem_match_term", "likely_oem",
    "likely_oem_score", "oem_match_terms", "oem_match_basis", "medtech_confidence",
]


def stable_key(*parts: str) -> str:
    text = "|".join((part or "").strip().lower() for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Adapter:
    def __init__(self, url: str, evidence_path: str | Path | None = None):
        self.url = url
        self.evidence_path = Path(evidence_path) if evidence_path else (
            Path(__file__).resolve().parents[1] / "raw" / "official_page_evidence_transcript.json"
        )

    def _build_row(self, record: dict[str, str]) -> dict[str, str]:
        row = {column: "" for column in SCHEMA}
        buyer = " | ".join(
            value for value in [record["organization"], record["office"], record["city"]] if value
        )
        row.update(
            {
                "source": "Federal PPRA EPMS Final Evaluations — package-level best available",
                "country": "Pakistan",
                "country_code": "PK",
                "publication_date": record["publication_date"],
                "title": record["title"],
                "title_english": record["title"],
                "buyer": buyer,
                "buyer_english": buyer,
                "classification": "final_evaluation_package_level",
                "status": "final_evaluation_lowest_bidder",
                "awarding_agency_name": record["office"],
                "awarding_agency_name_english": record["office"],
                "supplier_name": record["lowest_bidder"],
                "supplier_name_english": record["lowest_bidder"],
                "awarded_date": record["publication_date"],
                "notice_id": record["evaluation_no"],
                "notice_url": record["url"],
                "_source_workbook": str(self.evidence_path.resolve()),
                "_duplicate_rows_removed": "0",
                "medtech_filter_basis": (
                    "Official Final Evaluation page; package title is medtech; named Lowest Bidder; "
                    "package-level only, not an executed contract or complete item set"
                ),
                "medtech_confidence": "high",
            }
        )
        row["_dedupe_key"] = stable_key(
            record["evaluation_no"], record["tender_no"], record["lowest_bidder"], "package_level"
        )
        return row

    def extract(self, source: dict | None = None) -> list[dict[str, str]]:
        packet = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        return [self._build_row(record) for record in packet["accepted_package_level"]]

    def extract_targets(self, source: dict, targets: list[dict]) -> dict[str, list[dict[str, str]]]:
        rows = {row["notice_id"]: row for row in self.extract(source)}
        output: dict[str, list[dict[str, str]]] = {}
        for target in targets:
            notice_id = target.get("notice_id", "")
            target_key = target.get("target_key", "")
            if target_key and notice_id in rows:
                output[target_key] = [rows[notice_id]]
        return output


def create_adapter(url: str) -> Adapter:
    return Adapter(url)


def write_candidate(evidence_path: Path, output_path: Path) -> list[dict[str, str]]:
    rows = Adapter("https://epms.ppra.gov.pk/public/evaluations", evidence_path).extract({})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(rows)
    return rows
