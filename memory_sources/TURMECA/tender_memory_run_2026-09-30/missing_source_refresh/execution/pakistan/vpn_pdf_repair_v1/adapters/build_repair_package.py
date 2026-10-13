#!/usr/bin/env python3
"""Build the immutable VPN/PDF repair package from frozen evidence.

The evaluated costs below were visually transcribed from the retained one-page
official scans and are intentionally typed as final-evaluation result amounts,
not executed-contract values or realized spend.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]
INPUT = RUN.parent / "repair_v2" / "candidates" / "pk_federal_epms_package_level_candidates.csv"
RULES = RUN.parents[4] / ".tender-memory" / "business_rules.json"
FETCH = RUN / "audit" / "fetch_audit.json"

RESULTS = {
    "EVL00000003772": ("Medequips SMC (Pvt.) Limited", "23526701.83"),
    "EVL00000003683": ("The Lab Concern - Cosmos Science Corporation (JV)", "9476456.76"),
    "EVL00000003675": ("Hoora Pharma (Pvt.) Limited", "22243800.00"),
    "EVL00000003611": ("KASBN International", "15622693.01"),
    "EVL00000003097": ("Advance Western", "19705897.49"),
    "EVL00000003096": ("Electromed Corporation - United Medical JV", "2753523.07"),
    "EVL00000003094": ("SU Enterprises", "35260714.17"),
    "EVL00000003093": ("Ferozsons Laboratories Limited", "163575977.60"),
    "EVL00000002836": ("Vertex Medical (Pvt.) Limited", "77239137.83"),
    "EVL00000002535": ("Total Technologies (Pvt.) Limited", "95041897.48"),
    "EVL00000002138": ("M/s Matora Digionics (Pvt.) Limited", "20592118.78"),
    "EVL00000002017": ("M/s Sigma International", "9330000.00"),
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    fetch = json.loads(FETCH.read_text(encoding="utf-8"))
    fetch_by_id = {r["notice_id"]: r for r in fetch["records"]}
    assert len(headers) == 41 and len(rows) == 12 and set(RESULTS) == {r["notice_id"] for r in rows}

    rules_dst = RUN / "inputs" / "business_rules.snapshot.json"
    rules_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RULES, rules_dst)

    candidates, incomplete, audits = [], [], []
    for old in rows:
        notice = old["notice_id"]
        official_supplier, evaluated_cost = RESULTS[notice]
        assert old["supplier_name"] == official_supplier
        f = fetch_by_id[notice]
        page = f["page_fields"]
        details = page.get("details", {})
        row = dict(old)
        row.update({
            "source": "Federal PPRA EPMS — official final evaluation detail and report PDF",
            "status": "result - final evaluation - lowest bidder",
            "currency": "PKR",
            "amount": evaluated_cost,
            "supplier_name": official_supplier,
            "supplier_name_english": official_supplier,
            "item_no": "",
            "item_description": "",
            "item_description_english": "",
            "item_uom": "",
            "item_uom_english": "",
            "quantity": "",
            "contract_period": "",
            "contract_period_english": "",
            "_source_workbook": str((RUN / f["pdf_path"]).resolve()),
            "medtech_filter_basis": (
                "Official PPRA Final Evaluation detail and report; report explicitly names the Most "
                "Advantageous Bidder and its PKR Evaluated Cost. Amount is a final-evaluation "
                "result amount (evaluated_cost_not_executed_contract_value); package-level only."
            ),
        })
        candidates.append(row)
        missing = [
            name for name in (
                "item_no", "item_description", "item_uom", "quantity", "contract_period"
            ) if not row[name]
        ]
        incomplete.append({
            "notice_id": notice,
            "candidate_dedupe_key": row["_dedupe_key"],
            "disposition": "best_available_incomplete_replacement_candidate",
            "missing_tender_detail_fields": "|".join(missing),
            "amount_semantics": "evaluated_cost_not_executed_contract_value",
            "awarded_date_derivation": "official_evaluation_publication_date_proxy",
            "replacement_scope": "replace_same_notice_package_level_row_only",
            "delivery_ready": "false",
            "review_required": "independent_tender_reviewer",
        })
        audits.append({
            "notice_id": notice,
            "detail_url": f["detail_url"],
            "detail_http_status": f["detail_status"],
            "html_path": f["html_path"],
            "html_sha256": f["html_sha256"],
            "report_url": f["report_url"],
            "pdf_http_status": f["pdf_status"],
            "pdf_path": f["pdf_path"],
            "pdf_sha256": f["pdf_sha256"],
            "pdf_pages": f["pdf_pages"],
            "visual_review": "completed_one_page_scan",
            "evaluation_type": details.get("Evaluation Type", "Final Evaluation"),
            "tender_reference": page.get("tender_no", ""),
            "tender_inquiry_number": details.get("Tender Inquiry Number", ""),
            "bid_count": details.get("Number of Bids Received", ""),
            "official_page_lowest_bidder": details.get("Lowest Bidder", ""),
            "report_most_advantageous_bidder": official_supplier,
            "report_winning_evaluated_cost": evaluated_cost,
            "report_currency": "PKR",
            "amount_semantics": "evaluated_cost_not_executed_contract_value",
            "canonical_amount_populated": "true",
            "canonical_currency_populated": "true",
            "item_or_lot_matrix_supported": "false",
            "quantity_supported": "false",
            "uom_supported": "false",
            "contract_period_supported": "false",
            "executed_contract_supported": "false",
            "awarded_date_derivation": "official_evaluation_publication_date_proxy",
            "package_level_only": "true",
            "replacement_eligible": "true_pending_independent_review",
        })

    candidate_path = RUN / "candidates" / "candidate_replacements.csv"
    write_csv(candidate_path, headers, candidates)
    write_csv(RUN / "rejected_incomplete_rows.csv", list(incomplete[0]), incomplete)
    write_csv(RUN / "audit" / "per_notice_extraction_audit.csv", list(audits[0]), audits)
    write_json(RUN / "audit" / "per_notice_extraction_audit.json", {
        "created_at_utc": now,
        "records": audits,
    })
    write_json(RUN / "repair_targets.json", {
        "created_at_utc": now,
        "immutable_parent_candidate": str(INPUT.resolve()),
        "target_count": 12,
        "notice_ids": list(RESULTS),
        "requested_action": "replace same-notice package-level rows with stronger official PDF-backed candidates",
        "not_authorized": ["merge", "self_approve", "oem_approval", "edit_prior_run"],
    })
    write_json(RUN / "repair_log.json", {
        "created_at_utc": now,
        "actions": [
            "Downloaded 12 official EPMS detail pages and 12 linked evaluation-report PDFs.",
            "Rendered and visually reviewed all 12 scanned one-page reports.",
            "Confirmed one Most Advantageous Bidder and unambiguous PKR Evaluated Cost per report.",
            "Populated amount only as final-evaluation result amount; did not treat as executed contract value.",
            "Kept one package-level row per notice and left unsupported item, quantity, UOM and period fields blank.",
            "Frozen current business-rules snapshot; did not modify rules or prior runs.",
        ],
        "counts": {"targets": 12, "html_downloaded": 12, "pdf_downloaded": 12, "visually_reviewed": 12, "candidate_rows": 12},
    })
    write_json(RUN / "qc_findings.json", {
        "created_at_utc": now,
        "delivery_ready": False,
        "candidate_rows": 12,
        "column_count": len(headers),
        "unique_notice_ids": len({r["notice_id"] for r in candidates}),
        "pdfs_downloaded": sum(bool(r["pdf_path"]) for r in fetch["records"]),
        "notices_gaining_supported_fields": 12,
        "gained_fields": ["amount", "currency"],
        "total_evaluated_cost_pkr": "494368918.02",
        "blank_unsupported_fields": ["item_no", "item_description", "item_uom", "quantity", "contract_period"],
        "status_values": sorted({r["status"] for r in candidates}),
        "amount_semantics": "evaluated_cost_not_executed_contract_value",
        "executed_contract_claims": 0,
        "approved_oem_mappings": 0,
        "replacement_eligible_rows": 12,
        "replacement_constraint": "same notice/package row only; independent review required before merge",
        "issues": [],
    })

    # Preserve a readable browser capture in the declared navigation folder.
    nav_dir = RUN / "navigation"
    nav_dir.mkdir(parents=True, exist_ok=True)
    screenshots = sorted((RUN / "output" / "playwright" / ".playwright-cli").glob("*.png"))
    snapshots = sorted((RUN / "output" / "playwright" / ".playwright-cli").glob("*.yml"))
    shot_rel = ""
    snapshot_rel = ""
    if screenshots:
        dest = nav_dir / "EVL00000003772_official_detail.png"
        shutil.copy2(screenshots[-1], dest)
        shot_rel = dest.relative_to(RUN).as_posix()
    if snapshots:
        dest = nav_dir / "EVL00000003772_official_detail_snapshot.yml"
        shutil.copy2(snapshots[-1], dest)
        snapshot_rel = dest.relative_to(RUN).as_posix()
    navigation_payload = {
        "created_at_utc": now,
        "tool": "playwright-cli",
        "url": fetch_by_id["EVL00000003772"]["detail_url"],
        "page_title": fetch_by_id["EVL00000003772"]["page_fields"]["title"],
        "screenshot": shot_rel,
        "snapshot": snapshot_rel,
        "observed_controls": ["Download Evaluation Report", "Evaluation Type: Final Evaluation", "Lowest Bidder", "Evaluation Published Date"],
        "note": "Representative readable official detail page; every notice also has frozen HTML and linked PDF evidence.",
    }
    write_json(nav_dir / "navigation.json", navigation_payload)
    write_json(RUN / "navigation.json", navigation_payload)

    handoff = f"""# Pakistan EPMS VPN/PDF repair — Tender Agent handoff

Created {now}. This is an immutable repair candidate package; no merge or approval was performed.

## Outcome

- Official detail HTML downloaded: **12/12**.
- Official evaluation-report PDFs downloaded: **12/12**.
- Scanned reports visually inspected: **12/12**.
- Notices gaining source-supported canonical fields: **12/12** (`amount`, `currency`).
- Total final-evaluation result amount: **PKR 494,368,918.02**.
- Replacement candidates: **12** package-level rows, each eligible to replace only the same notice's prior package-level row, pending independent Tender Reviewer approval.
- Delivery ready: **false** until independent review and controlled merge.

Each report explicitly names a Most Advantageous Bidder and its PKR Evaluated Cost. `amount` therefore records a final-evaluation result amount with the mandatory semantic `evaluated_cost_not_executed_contract_value`. It is not an executed contract value or realized spend. Status is `result - final evaluation - lowest bidder`.

No report supplies an item/lot award matrix, awarded quantity, UOM, or contract period. Those fields remain blank and every candidate appears in `rejected_incomplete_rows.csv` as best-available incomplete.

## Reviewer action

Verify the 12 visually transcribed bidder/cost pairs against `raw/pdf/*.pdf` or `raw/pdf_render/*`, confirm exact 41-column schema and same-notice replacement keys, then approve or reject. Do not use these rows for item-level analytics or realized-spend reporting.
"""
    (RUN / "tender_agent_handoff.md").write_text(handoff, encoding="utf-8")

    # Add generated render hashes to the evidence manifest.
    manifest_path = RUN / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    known = {e["path"] for e in manifest["entries"]}
    for path in sorted((RUN / "raw" / "pdf_render").glob("*")):
        rel = path.relative_to(RUN).as_posix()
        if path.is_file() and path.stat().st_size and rel not in known:
            manifest["entries"].append({
                "notice_id": path.stem,
                "evidence_type": "derived_pdf_visual_render",
                "source_url": fetch_by_id.get(path.stem, {}).get("report_url", ""),
                "path": rel,
                "sha256": sha(path),
                "bytes": path.stat().st_size,
                "derived": True,
            })
    if shot_rel and shot_rel not in known:
        p = RUN / shot_rel
        manifest["entries"].append({"notice_id": "EVL00000003772", "evidence_type": "browser_screenshot", "source_url": fetch_by_id["EVL00000003772"]["detail_url"], "path": shot_rel, "sha256": sha(p), "bytes": p.stat().st_size, "derived": True})
    manifest["updated_at_utc"] = now
    write_json(manifest_path, manifest)

    # Manifest excludes itself and volatile Playwright working files.
    deliverables = []
    excluded = {"deliverables_manifest.json"}
    for path in sorted(RUN.rglob("*")):
        if not path.is_file() or path.name in excluded or "output/playwright/.playwright-cli" in path.as_posix():
            continue
        deliverables.append({"path": path.relative_to(RUN).as_posix(), "sha256": sha(path), "bytes": path.stat().st_size})
    write_json(RUN / "deliverables_manifest.json", {"created_at_utc": now, "entries": deliverables})
    print(json.dumps({"candidate_rows": len(candidates), "columns": len(headers), "pdfs": 12, "gained": 12, "eligible": 12}, indent=2))


if __name__ == "__main__":
    main()
