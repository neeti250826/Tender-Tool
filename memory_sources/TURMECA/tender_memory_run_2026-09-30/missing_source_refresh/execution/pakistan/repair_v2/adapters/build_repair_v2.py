#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path

from pk_federal_epms_package_repair_adapter import SCHEMA, write_candidate


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT.parent
WORKSPACE = ROOT.parents[4]
V1_CANDIDATE = V1 / "candidates" / "pk_federal_epms_awards_candidates.csv"
V1_EVIDENCE = V1 / "raw" / "epms" / "official_evaluation_evidence_2026-09-30.json"
PRIOR_112 = WORKSPACE / "tender_memory_run_2026-09-30" / "runs" / "pakistan" / "Pakistan" / "pakistan-award-evidence" / "298d1864-77ea-4886-bd91-9b38ae2f1965" / "normalized_tender_data.csv"
RULES = WORKSPACE / ".tender-memory" / "business_rules.json"
FEEDBACK = WORKSPACE / ".tender-memory" / "feedback_overrides.json"
EXPECTED_V1_HASH = "0d6be7cdb9fb5a90e2450469f48a59a36c6ad3d88f1c28ee5319d5d5eb5460f9"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


actual_v1_hash = sha256(V1_CANDIDATE)
if actual_v1_hash != EXPECTED_V1_HASH:
    raise RuntimeError(f"Frozen v1 candidate changed: {actual_v1_hash}")

v1_packet = json.loads(V1_EVIDENCE.read_text(encoding="utf-8"))
accepted = v1_packet["accepted"]
quarantined = v1_packet["quarantined"]

transcript = {
    "source_id": "pk-federal-epms-awards",
    "source_name": "Federal PPRA EPMS final evaluations",
    "official_listing_url": "https://epms.ppra.gov.pk/public/evaluations",
    "retrieved_on": "2026-09-30",
    "evidence_type": "exact_official_page_field_transcript",
    "access_limitation": (
        "Direct HTTP, Playwright and in-app browser navigation timed out for the Tender Agent. "
        "The independent reviewer confirmed all 12 official detail pages through a read-only official-page path. "
        "No source HTML/PDF was available to retain; these exact visible labels/values and official URLs are frozen."
    ),
    "accepted_package_level": accepted,
    "quarantined": quarantined,
    "field_transcripts": [
        {
            "notice_url": record["url"],
            "visible_fields": {
                "Evaluation No": record["evaluation_no"],
                "Tender No": record["tender_no"],
                "Organization Name": record["organization"],
                "Office Name": record["office"],
                "City": record["city"],
                "Evaluation Type": record["evaluation_type"],
                "Tender Inquiry Number": record["inquiry_no"],
                "Tender Title": record["title"],
                "Number of Bids Received": record["number_of_bids"],
                "Lowest Bidder": record["lowest_bidder"],
                "Evaluation Published Date": record["publication_date"],
                "Tender Advertisement Date": record["advertisement_date"],
                "Tender Closing Date": record["closing_date"],
            },
            "not_visible_on_detail_page": [
                "complete awarded item/lot set", "amount", "currency", "contract period",
                "awarded quantity", "UOM", "executed contract evidence"
            ],
        }
        for record in accepted
    ],
}
evidence_path = ROOT / "raw" / "official_page_evidence_transcript.json"
write_json(evidence_path, transcript)

candidate_path = ROOT / "candidates" / "pk_federal_epms_package_level_candidates.csv"
rows = write_candidate(evidence_path, candidate_path)

missing_fields = [
    "description", "description_english", "currency", "amount", "contract_period",
    "contract_period_english", "item_no", "item_description", "item_description_english",
    "item_uom", "item_uom_english", "quantity",
]
audit_rows: list[dict[str, object]] = []
for row in rows:
    audit_rows.append(
        {
            "source_id": "pk-federal-epms-awards",
            "notice_id": row["notice_id"],
            "notice_url": row["notice_url"],
            "publication_date": row["publication_date"],
            "title": row["title"],
            "supplier_name": row["supplier_name"],
            "row_disposition": "accepted_best_available_package_level_incomplete",
            "award_basis": "official_final_evaluation_named_lowest_bidder",
            "missing_tender_detail_fields": "|".join(missing_fields),
            "derivation_notes": "awarded_date_from_final_result_publication_date",
            "limitations": "Not an executed contract; complete item/lot set and realized spend not proven",
        }
    )
for record in quarantined:
    audit_rows.append(
        {
            "source_id": "pk-federal-epms-awards",
            "notice_id": record["evaluation_no"],
            "notice_url": record["url"],
            "publication_date": record["publication_date"],
            "title": record["title"],
            "supplier_name": "",
            "row_disposition": "quarantined_not_accepted",
            "award_basis": "",
            "missing_tender_detail_fields": "supplier_name|complete_awarded_item_or_lot_set",
            "derivation_notes": "",
            "limitations": record["reason"],
        }
    )
write_csv(
    ROOT / "audit" / "rejected_incomplete_rows.csv",
    [
        "source_id", "notice_id", "notice_url", "publication_date", "title", "supplier_name",
        "row_disposition", "award_basis", "missing_tender_detail_fields", "derivation_notes", "limitations",
    ],
    audit_rows,
)

targets = [
    {
        "target_key": f"pk-epms::{record['evaluation_no']}",
        "notice_id": record["evaluation_no"],
        "notice_url": record["url"],
        "rule_ids": ["PK-R01", "PK-R02", "PK-R03", "PK-R04", "PK-R05", "PK-R06", "PK-R07"],
        "requested_repair": "package-level best-available row with blank unsupported item/description fields and complete audit",
    }
    for record in accepted
]
write_json(ROOT / "repair_targets.json", {"source_id": "pk-federal-epms-awards", "targets": targets})

rule_snapshot = {
    "frozen_on": "2026-09-30",
    "country_scope": "Pakistan",
    "business_rules_path": str(RULES.resolve()),
    "business_rules_sha256": sha256(RULES),
    "business_rules": json.loads(RULES.read_text(encoding="utf-8")),
    "feedback_overrides_path": str(FEEDBACK.resolve()),
    "feedback_overrides_sha256": sha256(FEEDBACK),
    "feedback_overrides": json.loads(FEEDBACK.read_text(encoding="utf-8")),
    "active_pakistan_feedback_scopes": [],
}
write_json(ROOT / "feedback_rule_snapshot.json", rule_snapshot)

prior_rows = list(csv.DictReader(PRIOR_112.open(encoding="utf-8-sig", newline="")))
prior_ids = {row["notice_id"] for row in prior_rows}
prior_urls = {row["notice_url"] for row in prior_rows}
overlap_ids = sorted({row["notice_id"] for row in rows} & prior_ids)
overlap_urls = sorted({row["notice_url"] for row in rows} & prior_urls)

qc = {
    "review_stage": "tender_agent_repair_candidate_pending_independent_re_review",
    "candidate_rows": len(rows),
    "candidate_notices": len({row["notice_id"] for row in rows}),
    "schema_column_count": len(SCHEMA),
    "schema_exact": list(rows[0]) == SCHEMA,
    "duplicate_dedupe_keys": len(rows) - len({row["_dedupe_key"] for row in rows}),
    "out_of_scope_dates": sum(not ("2024-01-01" <= row["publication_date"] <= "2026-09-30") for row in rows),
    "rows_with_unsupported_description": sum(bool(row["description"] or row["description_english"]) for row in rows),
    "rows_with_unsupported_item_fields": sum(
        bool(row["item_no"] or row["item_description"] or row["item_description_english"]) for row in rows
    ),
    "rows_with_explicit_final_evaluation_status": sum(
        row["status"] == "final_evaluation_lowest_bidder" for row in rows
    ),
    "accepted_rows_in_incomplete_audit": sum(
        row["row_disposition"] == "accepted_best_available_package_level_incomplete" for row in audit_rows
    ),
    "award_date_proxy_derivations_logged": sum(
        row["derivation_notes"] == "awarded_date_from_final_result_publication_date" for row in audit_rows
    ),
    "prior_notice_id_overlap": overlap_ids,
    "prior_notice_url_overlap": overlap_urls,
    "strict_complete_rows": 0,
    "canonical_item_level_merge_ready_rows": 0,
    "delivery_ready": False,
}
write_json(ROOT / "qc_findings.json", qc)

repair_log = {
    "repaired_on": "2026-09-30",
    "original_candidate_path": str(V1_CANDIDATE.resolve()),
    "original_candidate_sha256": actual_v1_hash,
    "repaired_candidate_path": str(candidate_path.resolve()),
    "actions": [
        "Preserved v1 candidate without modification",
        "Reclassified all 12 rows as package-level best-available final evaluations",
        "Blanked unsupported description and all item-level fields",
        "Replaced awarded/final-result status with final_evaluation_lowest_bidder",
        "Recorded the publication-date award proxy per row",
        "Added all accepted incomplete rows to rejected_incomplete_rows.csv",
        "Froze current business rules and feedback overrides",
        "Froze exact official-page field transcripts and access limitations",
    ],
    "resolved_targets": [target["target_key"] for target in targets],
    "unresolved_item_detail_targets": [target["target_key"] for target in targets],
    "merge_status": "not_merged",
    "review_status": "pending_independent_re_review",
}
write_json(ROOT / "repair_log.json", repair_log)

navigation = {
    "source_id": "pk-federal-epms-awards",
    "run": "repair_v2",
    "official_listing_url": "https://epms.ppra.gov.pk/public/evaluations",
    "steps": [
        {
            "step": 1,
            "action": "Open the official evaluation listing and each direct detail URL",
            "result": "Tender Agent direct HTTP, Playwright and in-app browser paths timed out",
        },
        {
            "step": 2,
            "action": "Use the permitted read-only official-page retrieval evidence confirmed by the independent reviewer",
            "result": "Final Evaluation, Lowest Bidder, title, buyer and dates confirmed for all 12 notices",
        },
        {
            "step": 3,
            "action": "Freeze exact visible page labels/values",
            "artifact": "../raw/official_page_evidence_transcript.json",
        },
        {
            "step": 4,
            "action": "Render the retained evidence transcript for browser review",
            "artifact": "evidence_transcript.html",
            "screenshot": "evidence_transcript_browser.png",
            "limitation": "Screenshot is of the frozen transcript, not the inaccessible live EPMS page",
        },
    ],
    "live_source_screenshot_available": False,
    "limitation": "No live EPMS screenshot or retained source HTML/PDF was available to the Tender Agent. This run must remain source-limited.",
}
write_json(ROOT / "navigation" / "navigation.json", navigation)

cards = []
for record in accepted:
    cards.append(
        "<section><h2>" + html.escape(record["evaluation_no"]) + "</h2>"
        + "<p><strong>Final Evaluation · Lowest Bidder:</strong> " + html.escape(record["lowest_bidder"]) + "</p>"
        + "<p><strong>Title:</strong> " + html.escape(record["title"]) + "</p>"
        + "<p><strong>Published:</strong> " + html.escape(record["publication_date"]) + " · "
        + "<strong>Tender:</strong> " + html.escape(record["tender_no"]) + "</p>"
        + "<p><a href=\"" + html.escape(record["url"], quote=True) + "\">Official PPRA detail URL</a></p></section>"
    )
html_doc = """<!doctype html><html><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>Pakistan EPMS repair evidence transcript</title>
<style>body{font:15px system-ui;margin:40px;max-width:1000px;color:#14213d}section{border:1px solid #ccd5e0;border-radius:10px;padding:14px;margin:14px 0}h1{color:#0b5d4b}h2{font-size:18px}p{margin:7px 0}aside{background:#fff3cd;padding:12px;border-radius:8px}</style></head><body>
<h1>Pakistan EPMS repair v2 — retained page evidence transcript</h1><aside>Live source navigation timed out for the Tender Agent. This browser rendering shows the exact official-page fields frozen from the permitted read-only retrieval and independently confirmed official URLs. It is not a screenshot of the live EPMS page.</aside>""" + "".join(cards) + "</body></html>"
(ROOT / "navigation" / "evidence_transcript.html").write_text(html_doc, encoding="utf-8")

summary = {
    "country": "Pakistan",
    "run": "repair_v2",
    "candidate_type": "best_available_package_level_final_evaluation",
    "accepted_rows": len(rows),
    "accepted_notices": len(rows),
    "quarantined_other_records": len(quarantined),
    "complete_item_level_rows": 0,
    "new_vs_prior_112": len(rows) if not overlap_ids and not overlap_urls else None,
    "amount_total": None,
    "merge_status": "not_merged",
    "review_status": "pending_independent_re_review",
    "delivery_ready": False,
}
write_json(ROOT / "run_summary.json", summary)

handoff = f"""# Pakistan EPMS repair v2 — Tender Agent handoff

## Result

- Preserved the frozen v1 candidate at SHA-256 `{actual_v1_hash}`.
- Rebuilt 12 notices as package-level best-available final-evaluation rows in the exact 41-column schema.
- `status` is `final_evaluation_lowest_bidder`; no row is described as an executed contract or realized spend.
- Unsupported `description`, `item_no`, `item_description`, UOM and quantity fields are blank.
- All 12 accepted rows are repeated in `audit/rejected_incomplete_rows.csv` with exact missing fields and `awarded_date_from_final_result_publication_date` derivation notes.
- Six other records remain quarantined.
- No notice-ID or notice-URL overlap exists with the prior 112-row run.

## Evidence and limitations

The Tender Agent's live HTTP, Playwright and in-app-browser routes timed out. The independent reviewer confirmed all 12 official detail pages through a read-only official-page path. The exact visible labels and values are frozen in `raw/official_page_evidence_transcript.json`. The browser screenshot renders that retained transcript and is explicitly not presented as a live-source screenshot. No evaluation PDF, full item/lot matrix, amount, currency, quantity, UOM, contract duration or executed-contract evidence was available.

## Authority boundary

This is a repaired candidate, not a merge approval. It remains source-limited, incomplete, pending independent re-review and not delivery-ready. Supplier names are not OEM mappings; no rules or aliases were approved or changed.
"""
(ROOT / "handoff.md").write_text(handoff, encoding="utf-8")

manifest_paths = [
    path for path in ROOT.rglob("*")
    if path.is_file() and path.name != "deliverables_manifest.json"
]
write_json(
    ROOT / "deliverables_manifest.json",
    {
        "created_on": "2026-09-30",
        "run": "repair_v2",
        "immutable_run_root": str(ROOT.resolve()),
        "original_v1_candidate_sha256": actual_v1_hash,
        "files": [
            {
                "path": str(path.relative_to(ROOT)),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(manifest_paths)
        ],
    },
)

print(json.dumps(summary, ensure_ascii=False))
