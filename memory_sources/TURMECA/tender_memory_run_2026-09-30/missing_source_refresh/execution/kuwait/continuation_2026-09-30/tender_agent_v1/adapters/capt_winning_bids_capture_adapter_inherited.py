"""Parse a challenge-cleared CAPT Winning Bids browser capture.

The browser capture is produced by Playwright CLI from the public rolling list.
This adapter is intentionally offline: it does not persist cookies or attempt to
bypass Cloudflare. It fails loudly if the capture envelope or row shape changes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime
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
    "page", "meeting_date", "tender_no", "subject", "organisation",
    "winner", "total", "page_url", "popup_url", "decision", "reason",
]
MEDTECH_TERMS = (
    "medical device", "medical devices", "medical equipment", "laboratory",
    "diagnostic", "reagent", "ivd", "surgical", "catheter", "radiology",
    "dialysis", "endoscope", "implant", "sterilizer", "medical oxygen",
    "أجهزة طبية", "اجهزة طبية", "جهاز طبي", "مختبر", "مختبرات", "تحاليل",
    "تحليل", "كواشف", "أشعة", "اشعة", "جراحي", "جراحية", "قسطرة",
    "غسيل كلى", "مناظير", "منظار", "تعقيم", "أكسجين طبي", "مستلزمات طبية",
)
EXCLUSION_TERMS = (
    "وجبات", "غذائية", "تنظيف", "حراسة", "شبك", "كاميرات مراقبة",
    "غلاية", "مبادل حراري", "maintenance of gardens", "landscap",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_capture(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    try:
        result_index = lines.index("### Result")
    except ValueError as exc:
        raise RuntimeError("Missing Playwright CLI Result envelope") from exc
    if result_index + 1 >= len(lines):
        raise RuntimeError("Empty Playwright CLI result")
    encoded = lines[result_index + 1]
    data = json.loads(json.loads(encoded))
    if not isinstance(data, list):
        raise RuntimeError("Capture result is not a list")
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("cells"), list):
            raise RuntimeError(f"Unexpected row at {index}")
        if len(row["cells"]) not in (6, 7, 8):
            raise RuntimeError(f"Unexpected CAPT cell count at row {index}: {len(row['cells'])}")
    return data


def parse_date(value: str) -> str:
    value = clean(value).replace("Sept.", "Sep.")
    for fmt in ("%b. %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized meeting date: {value}")


def parse_total(value: str) -> tuple[str, str]:
    text = clean(value)
    if not text or text.startswith("-") or "%" in text:
        return "", ""
    match = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:KD|KWD)\b", text, re.I)
    return ((match.group(1).replace(",", ""), "KWD") if match else ("", ""))


class Adapter:
    def __init__(self, url: str):
        self.url = url

    def extract(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        capture = Path(source["capture_path"])
        rows = parse_capture(capture)
        candidates, _ = classify(rows, capture)
        return candidates


def create_adapter(url: str) -> Adapter:
    return Adapter(url)


def classify(
    rows: list[dict[str, Any]], capture: Path
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates: list[dict[str, Any]] = []
    audit: list[dict[str, str]] = []
    for raw in rows:
        cells = [clean(value) for value in raw["cells"]]
        meeting_date, tender_no, subject, organisation = cells[1:5]
        winner = cells[5] if len(cells) > 5 else ""
        total = cells[6] if len(cells) > 6 else ""
        popup = clean(raw.get("popup"))
        popup_url = "https://capt.gov.kw" + popup if popup else ""
        haystack = f"{subject} {organisation}".casefold()
        matched = sorted({term for term in MEDTECH_TERMS if term.casefold() in haystack})
        excluded = sorted({term for term in EXCLUSION_TERMS if term.casefold() in haystack})
        reason = ""
        if winner.casefold() == "items":
            reason = "item_popup_parent_row_not_supplier_award"
        elif excluded:
            reason = "non_medtech_exclusion:" + ";".join(excluded)
        elif not matched:
            reason = "no_medtech_product_or_service_evidence"
        elif not winner:
            reason = "missing_named_winner"

        if reason:
            audit.append({
                "page": str(raw.get("page", "")),
                "meeting_date": meeting_date,
                "tender_no": tender_no,
                "subject": subject,
                "organisation": organisation,
                "winner": winner,
                "total": total,
                "page_url": clean(raw.get("page_url")),
                "popup_url": popup_url,
                "decision": "rejected",
                "reason": reason,
            })
            continue

        iso_date = parse_date(meeting_date)
        amount, currency = parse_total(total)
        key_input = "|".join([iso_date, tender_no, organisation, winner, amount])
        candidates.append({
            "source": "CAPT Winning Bids - live rolling window",
            "country": "Kuwait",
            "country_code": "KW",
            "publication_date": iso_date,
            "title": subject,
            "title_english": "",
            "description": subject,
            "description_english": "",
            "buyer": organisation,
            "buyer_english": organisation,
            "classification": "winning bid",
            "status": "awarded",
            "currency": currency,
            "amount": amount,
            "awarding_agency_name": organisation,
            "awarding_agency_name_english": organisation,
            "supplier_name": winner,
            "supplier_name_english": "",
            "awarded_date": iso_date,
            "contract_period": "",
            "contract_period_english": "",
            "item_no": "1",
            "item_description": subject,
            "item_description_english": "",
            "item_uom": "",
            "item_uom_english": "",
            "quantity": "",
            "notice_id": tender_no,
            "notice_url": clean(raw.get("page_url")),
            "_source_workbook": str(capture.resolve()),
            "_duplicate_rows_removed": "0",
            "_dedupe_key": "capt-live-" + sha256_text(key_input)[:20],
            "medtech_filter_basis": "; ".join(matched),
            "mapped_oem": "",
            "mapped_oem_basis": "",
            "mapped_oem_match_term": "",
            "likely_oem": "",
            "likely_oem_score": "",
            "oem_match_terms": "",
            "oem_match_basis": "",
            "medtech_confidence": "high",
        })
    return candidates, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = parse_capture(args.capture)
    candidates, audit = classify(rows, args.capture)
    candidate_path = args.output / "candidate_awards.csv"
    with candidate_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(candidates)
    audit_path = args.output / "rejection_audit.csv"
    with audit_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(audit)
    meta = {
        "rows_observed": len(rows),
        "accepted_medtech_awards": len(candidates),
        "rejected_rows": len(audit),
        "pages_observed": sorted({row.get("page") for row in rows}),
        "coverage_note": "CAPT returned a current rolling window, not a full date archive.",
        "direct_http_status": 403,
        "browser_session_required": True,
        "capture_path": str(args.capture.resolve()),
        "capture_sha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
    }
    (args.output / "run_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=True))


if __name__ == "__main__":
    main()
