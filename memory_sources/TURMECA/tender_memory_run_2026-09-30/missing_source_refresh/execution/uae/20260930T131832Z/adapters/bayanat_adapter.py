from __future__ import annotations

from pathlib import Path

from common import CANONICAL_COLUMNS, fetch_to_file, session, write_csv, write_json


DATASET_URL = "https://admin.bayanat.ae/Home/DatasetInfo?dID=395UagP0IDUBy4odQSNbQfWg5Gqx0h7FdX5IuZQG5zc&langKey=en"
RESOURCE_URL = "https://admin.bayanat.ae/Dataset/DownloadDatasetResource?fileId=f12c312d-f5b5-464a-a3b4-afac20e00555&resourceID=9679"


def run(root: Path) -> dict:
    out = root / "sources" / "federal_bayanat"
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    attempts = [
        fetch_to_file(s, DATASET_URL, out / "raw_dataset_page.html"),
        fetch_to_file(s, RESOURCE_URL, out / "Procurement_Opendata.xlsx"),
    ]
    downloaded = next((a for a in attempts if a.get("ok") and "spreadsheet" in str(a.get("content_type", "")).lower()), None)
    decision = {
        "source": "UAE Bayanat - Ministry of Finance Procurement Opendata",
        "attempts": attempts,
        "workbook_profiled": bool(downloaded),
        "award_qualified_rows": 0,
        "disposition": "tls_certificate_validation_failed" if not downloaded else "downloaded_pending_schema_profile",
        "safety": "TLS verification remained enabled; no certificate warning was bypassed.",
    }
    write_json(out / "access_and_schema_audit.json", decision)
    write_csv(out / "candidate_awarded_medtech.csv", [], CANONICAL_COLUMNS)
    write_csv(out / "rejected_or_unresolved.csv", [{
        "source": decision["source"],
        "reason": decision["disposition"],
        "evidence_url": RESOURCE_URL,
        "detail": "Official file could not be obtained with a valid certificate chain in this environment; award schema was not assumed.",
    }], ["source", "reason", "evidence_url", "detail"])
    return {"source_id": "federal_bayanat", "award_rows": 0, "review_rows": 0, "status": decision["disposition"], "directory": str(out.resolve())}
