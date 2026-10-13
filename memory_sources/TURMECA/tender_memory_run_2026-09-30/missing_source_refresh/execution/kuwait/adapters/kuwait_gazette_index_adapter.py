"""Kuwait Al-Youm MOH index extractor.

The public index is an official discovery manifest only.  It does not itself
prove that a procurement was awarded, so this adapter deliberately emits no
canonical award rows until retained page evidence contains an explicit result.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = "https://kuwaitalyawm.media.gov.kw/search/Get"
SEARCH_URL = "https://kuwaitalyawm.media.gov.kw/search/customindex"
VIEWER = "https://kuwaitalyawm.media.gov.kw/flip/index/{edition}?no={page}"
EXPECTED = {
    "EditionID_FK",
    "Ads_ID",
    "AdsTitle",
    "EditionsType",
    "Agent",
    "AdsCategory",
    "EditionNo",
    "EditionDate",
    "FromPage",
    "ToPageNew",
}
INDEX_COLUMNS = [
    "EditionID_FK",
    "Ads_ID",
    "AdsTitle",
    "EditionsType",
    "Agent",
    "AdsCategory",
    "EditionNo",
    "EditionDate",
    "HijriDate",
    "FromPage",
    "ToPage",
    "ToPageNew",
    "viewer_url",
    "index_evidence_url",
    "award_evidence_status",
]
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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class Adapter:
    url: str = SEARCH_URL
    date_from: str = "2024/01/01"
    date_to: str = "2026/09/30"
    page_size: int = 100
    delay_seconds: float = 0.15

    def extract(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        """Return no award rows: an index record is not award evidence."""
        return []

    def fetch_index(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = output_dir / "raw"
        raw_dir.mkdir(exist_ok=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TenderEvidence/1.0)",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": (
                f"{SEARCH_URL}?AjentID=1&_startdate={self.date_from}"
                f"&_enddate={self.date_to}"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }

        all_rows: list[dict[str, Any]] = []
        request_log: list[dict[str, Any]] = []
        expected_total: int | None = None
        start = 0
        draw = 1
        while expected_total is None or start < expected_total:
            params = {
                "draw": draw,
                "start": start,
                "length": self.page_size,
                "search[value]": "",
                "search[regex]": "false",
                "AgentsID": "1",
                "fromDate": self.date_from,
                "toDate": self.date_to,
            }
            request_url = ENDPOINT + "?" + urlencode(params)
            request = Request(request_url, headers=headers)
            with urlopen(request, timeout=90) as response:
                response_body = response.read()
                status_code = response.status
            page_path = raw_dir / f"gazette_index_{start:04d}.json"
            page_path.write_bytes(response_body)
            payload = json.loads(response_body)
            if not {"data", "recordsFiltered"}.issubset(payload):
                raise RuntimeError(f"Unexpected endpoint schema at offset {start}")
            page_rows = payload["data"]
            if page_rows:
                missing = EXPECTED - set(page_rows[0])
                if missing:
                    raise RuntimeError(f"Gazette schema changed; missing {sorted(missing)}")
            total = int(payload["recordsFiltered"])
            if expected_total is None:
                expected_total = total
            elif expected_total != total:
                raise RuntimeError(
                    f"recordsFiltered changed during run: {expected_total} -> {total}"
                )
            request_log.append({
                "offset": start,
                "rows": len(page_rows),
                "records_filtered": total,
                "request_url": request_url,
                "status_code": status_code,
                "raw_file": str(page_path.resolve()),
                "sha256": sha256(page_path),
            })
            all_rows.extend(page_rows)
            if not page_rows:
                break
            start += len(page_rows)
            draw += 1
            time.sleep(self.delay_seconds)

        if expected_total is None or len(all_rows) != expected_total:
            raise RuntimeError(
                f"Incomplete gazette index: fetched {len(all_rows)} of {expected_total}"
            )

        enriched = []
        for row in all_rows:
            copy = dict(row)
            copy["viewer_url"] = VIEWER.format(
                edition=row["EditionID_FK"], page=row["FromPage"]
            )
            copy["index_evidence_url"] = ENDPOINT + "?" + urlencode({
                "AgentsID": 1,
                "fromDate": self.date_from,
                "toDate": self.date_to,
                "start": 0,
                "length": self.page_size,
            })
            copy["award_evidence_status"] = "index_only_not_award_evidence"
            enriched.append(copy)

        manifest_csv = output_dir / "gazette_moh_index_manifest.csv"
        with manifest_csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=INDEX_COLUMNS)
            writer.writeheader()
            writer.writerows({key: row.get(key, "") for key in INDEX_COLUMNS} for row in enriched)

        category_counts: dict[str, int] = {}
        for row in enriched:
            key = str(row.get("AdsCategory") or "")
            category_counts[key] = category_counts.get(key, 0) + 1

        meta = {
            "source": "Kuwait Al-Youm official gazette search",
            "authority": "Kuwait Ministry of Information / Official Gazette",
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "date_from": self.date_from,
            "date_to": self.date_to,
            "agent_id": 1,
            "records_filtered": expected_total,
            "records_fetched": len(enriched),
            "category_counts": dict(sorted(category_counts.items())),
            "award_rows_emitted": 0,
            "reason": "Index metadata has no supplier, value, or explicit award outcome.",
            "manifest_csv": str(manifest_csv.resolve()),
            "manifest_sha256": sha256(manifest_csv),
            "requests": request_log,
        }
        metadata_path = output_dir / "gazette_index_run_metadata.json"
        metadata_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        canonical_path = output_dir / "candidate_awards.csv"
        with canonical_path.open("w", newline="", encoding="utf-8-sig") as handle:
            csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS).writeheader()

        return meta


def create_adapter(url: str) -> Adapter:
    return Adapter(url=url)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--from-date", default="2024/01/01")
    parser.add_argument("--to-date", default="2026/09/30")
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()
    adapter = Adapter(
        date_from=args.from_date,
        date_to=args.to_date,
        page_size=args.page_size,
    )
    print(json.dumps(adapter.fetch_index(args.output), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
