#!/usr/bin/env python3
"""Reproducible adapter for the frozen, official PPRA EPMS evidence packet.

This adapter intentionally performs no network request. The official-page facts were
frozen after the public HTTP/browser paths timed out and an indexed official-page
retrieval path succeeded. It emits best-available rows with honest blanks.
"""

from __future__ import annotations

import argparse
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
    value = "|".join((part or "").strip().lower() for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Adapter:
    def __init__(self, url: str, evidence_path: str | Path):
        self.url = url
        self.evidence_path = Path(evidence_path)

    def extract(self, source: dict | None = None) -> list[dict[str, str]]:
        packet = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        rows: list[dict[str, str]] = []
        for record in packet["accepted"]:
            buyer = " | ".join(
                value for value in [record["organization"], record["office"], record["city"]] if value
            )
            title = record["title"]
            row = {column: "" for column in SCHEMA}
            row.update(
                {
                    "source": "Federal PPRA EPMS Final Evaluations",
                    "country": "Pakistan",
                    "country_code": "PK",
                    "publication_date": record["publication_date"],
                    "title": title,
                    "title_english": title,
                    "description": title,
                    "description_english": title,
                    "buyer": buyer,
                    "buyer_english": buyer,
                    "classification": "final_evaluation",
                    "status": "awarded/final-result",
                    "awarding_agency_name": record["office"],
                    "awarding_agency_name_english": record["office"],
                    "supplier_name": record["lowest_bidder"],
                    "supplier_name_english": record["lowest_bidder"],
                    "awarded_date": record["publication_date"],
                    "item_no": "1",
                    "item_description": title,
                    "item_description_english": title,
                    "notice_id": record["evaluation_no"],
                    "notice_url": record["url"],
                    "_source_workbook": str(self.evidence_path.resolve()),
                    "_duplicate_rows_removed": "0",
                    "medtech_filter_basis": "Official Final Evaluation; explicit medical-equipment item; named lowest bidder",
                    "medtech_confidence": "high",
                }
            )
            row["_dedupe_key"] = stable_key(
                record["evaluation_no"], record["tender_no"], "1", record["lowest_bidder"], title
            )
            rows.append(row)
        return rows


def create_adapter(url: str, evidence_path: str | Path | None = None) -> Adapter:
    if evidence_path is None:
        evidence_path = Path(__file__).resolve().parents[1] / "raw" / "epms" / "official_evaluation_evidence_2026-09-30.json"
    return Adapter(url, evidence_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    adapter = create_adapter("https://epms.ppra.gov.pk/public/evaluations", args.evidence)
    rows = adapter.extract({"source_id": "pk-federal-epms-awards"})
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEMA)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"rows_written": len(rows), "output": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
