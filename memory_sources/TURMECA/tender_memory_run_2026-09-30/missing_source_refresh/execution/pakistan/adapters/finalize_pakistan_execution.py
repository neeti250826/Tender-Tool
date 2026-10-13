#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "raw" / "epms" / "official_evaluation_evidence_2026-09-30.json"
CANDIDATES = ROOT / "candidates" / "pk_federal_epms_awards_candidates.csv"
DISCOVERY = ROOT.parents[1] / "pakistan_source_candidates.json"


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


packet = json.loads(EVIDENCE.read_text(encoding="utf-8"))
candidate_registry = json.loads(DISCOVERY.read_text(encoding="utf-8"))
candidate_rows = list(csv.DictReader(CANDIDATES.open(encoding="utf-8-sig", newline="")))

rejection_rows = []
for row in packet["quarantined"]:
    rejection_rows.append(
        {
            "source_id": "pk-federal-epms-awards",
            "notice_id": row["evaluation_no"],
            "publication_date": row["publication_date"],
            "title": row["title"],
            "notice_url": row["url"],
            "disposition": "quarantined_not_awarded_candidate",
            "reason": row["reason"],
        }
    )

write_csv(
    ROOT / "audit" / "rejection_audit.csv",
    ["source_id", "notice_id", "publication_date", "title", "notice_url", "disposition", "reason"],
    rejection_rows,
)

status_overrides = {
    "pk-federal-epms-awards": ("partial_success", "12 final medical evaluations frozen; direct HTTP/browser timed out; contracts produced no verified medical hit through indexed search"),
    "pk-federal-old-ppra": ("blocked", "official shell indexed but document/organization crawl unavailable from direct network path"),
    "pk-federal-epads-loa": ("blocked_increment", "direct HTTP and Playwright timed out; historical 17,623-row/7,414-notice input remains frozen through 2026-07-02"),
    "pk-punjab-ppra-eproc": ("blocked", "official directory resolved; contract/final-evaluation ASP.NET endpoints timed out"),
    "pk-punjab-central-health": ("not_completed", "no final-result item matrix obtained within execution window"),
    "pk-sindh-sppra": ("blocked", "BER route failed robots/access checks; no official attachment retrieved"),
    "pk-kp-health-dghs": ("partial_discovery_only", "official archive confirms final 2026-27 medical-equipment BER; attachment URL timed out, so no item rows accepted"),
    "pk-kp-kppra-epads": ("not_completed", "no public award payload verified"),
    "pk-balochistan-bppra": ("blocked", "authoritative award route not resolved"),
    "pk-balochistan-health": ("notice_only", "official page exposes medical procurement notices, not final supplier/value outcomes"),
    "pk-balochistan-pphi": ("not_completed", "no final-result crosswalk obtained"),
}

ledger = []
for candidate in candidate_registry["candidates"]:
    source_id = candidate["source_id"]
    status, note = status_overrides.get(source_id, ("not_executed_after_higher_priority_barriers", "No accepted public final-result evidence frozen in this pass"))
    ledger.append(
        {
            "source_id": source_id,
            "rank": candidate["rank"],
            "priority": candidate["priority"],
            "name": candidate["name"],
            "official_urls": candidate.get("official_urls", []),
            "status": status,
            "accepted_candidate_rows": 12 if source_id == "pk-federal-epms-awards" else 0,
            "note": note,
        }
    )

write_json(
    ROOT / "audit" / "source_ledger.json",
    {
        "country": "Pakistan",
        "executed_on": "2026-09-30",
        "date_scope": ["2024-01-01", "2026-09-30"],
        "merge_status": "not_merged",
        "review_status": "candidate_frozen_pending_independent_review",
        "sources": ledger,
    },
)

access_gaps = [
    {
        "route": "Federal PPRA EPMS direct HTTP",
        "method": "PowerShell/curl and Playwright",
        "result": "connection timeout",
        "impact": "full 14-page contract and 73-page evaluation sweep could not be executed locally",
        "fallback_used": "indexed official-page retrieval and direct official detail URLs",
    },
    {
        "route": "EPADS system-issued LoA increment",
        "method": "requests scraper and Playwright",
        "result": "connection timeout before first listing page",
        "impact": "2026-07-03 through 2026-09-30 LoA increment not refreshed",
        "fallback_used": "none; historical input kept immutable",
    },
    {
        "route": "Punjab eProc contract/final evaluation",
        "method": "official directory then ASP.NET result endpoints",
        "result": "target endpoints timed out",
        "impact": "no Punjab-specific contract rows accepted",
        "fallback_used": "federal EPMS evaluation records for IDAP only, kept in federal source stream",
    },
    {
        "route": "Sindh SPPRA BER",
        "method": "official BER route",
        "result": "robots/access check failure",
        "impact": "no Sindh award matrix retrieved",
        "fallback_used": "none",
    },
    {
        "route": "KP Health final medical-equipment BER",
        "method": "official archive and direct PDF",
        "result": "archive verified; PDF download timed out",
        "impact": "winner/item/rate rows could not be safely normalized",
        "fallback_used": "discovery evidence retained; candidate inclusion withheld",
    },
    {
        "route": "Balochistan Health/BPPRA",
        "method": "official health tender page and regulator search",
        "result": "health page is notice-only; final regulator route unresolved",
        "impact": "no Balochistan awarded rows accepted",
        "fallback_used": "none",
    },
]
write_csv(ROOT / "audit" / "access_gap_ledger.csv", list(access_gaps[0]), access_gaps)

navigation = {
    "source_id": "pk-federal-epms-awards",
    "executed_on": "2026-09-30",
    "steps": [
        {
            "step": 1,
            "action": "Attempt direct public PPRA contracts and evaluations pages",
            "url": "https://epms.ppra.gov.pk/public/evaluations",
            "result": "Direct HTTP and Playwright timed out",
        },
        {
            "step": 2,
            "action": "Retrieve indexed official evaluation pages for explicit medical-equipment final evaluations",
            "url": "https://epms.ppra.gov.pk/public/evaluations/evaluation-details/EVL00000003772",
            "result": "Official detail exposed Final Evaluation, dates, title and Lowest Bidder",
        },
        {
            "step": 3,
            "action": "Apply fail-closed acceptance rules and freeze one row per unambiguous evaluation/item/supplier",
            "result": "12 accepted; 6 quarantined",
        },
        {
            "step": 4,
            "action": "Retain prior same-day EPADS navigation screenshots as route references only",
            "screenshots": [
                "epads_loi_listing_retained_reference.png",
                "epads_health_award_row_retained_reference.png",
            ],
            "result": "Not treated as proof of a successful new EPADS increment",
        },
    ],
    "screenshot_limitation": "No new readable EPMS screenshot could be captured because both Playwright and the in-app browser timed out. Official detail URLs and frozen facts are retained instead.",
}
write_json(ROOT / "navigation" / "navigation.json", navigation)

missing_counts = {}
for field in ["currency", "amount", "contract_period", "mapped_oem"]:
    missing_counts[field] = sum(1 for row in candidate_rows if not row[field].strip())

summary = {
    "country": "Pakistan",
    "status": "source_limited_candidate_run_pending_independent_review",
    "date_scope": ["2024-01-01", "2026-09-30"],
    "accepted_rows": len(candidate_rows),
    "accepted_notices": len({row["notice_id"] for row in candidate_rows}),
    "quarantined_records": len(rejection_rows),
    "new_vs_prior_112_row_run": len(candidate_rows),
    "candidate_date_min": min(row["publication_date"] for row in candidate_rows),
    "candidate_date_max": max(row["publication_date"] for row in candidate_rows),
    "missing_fields": missing_counts,
    "amount_total": None,
    "manufacturer_mapping": "not_attempted; supplier is not OEM",
    "merge_status": "not_merged",
    "delivery_ready": False,
}
write_json(ROOT / "audit" / "execution_summary.json", summary)

handoff = f"""# Pakistan missing-source refresh — Tender Agent handoff

Executed on 2026-09-30 for award/final-result medical, surgical, medtech and IVD goods published 2024-01-01 through 2026-09-30.

## Frozen candidate result

- 12 candidate rows across 12 PPRA EPMS final evaluations.
- All 12 are new relative to the prior 112-row normalized Pakistan run.
- Candidate publication dates: 2026-07-14 through 2026-09-25.
- Every accepted row has an official EPMS detail URL, explicit `Final Evaluation`, a medtech item in the title, and a named lowest bidder.
- Amount, currency, contract period and OEM mapping remain blank for all 12 rows because the official indexed detail did not expose those facts.
- The evaluation publication date is used as the awarded-date proxy under the controlled best-available rule.

## Quarantine and scope controls

- 6 records were quarantined: technical-only evaluations, ambiguous multi-bidder summaries, or no identifiable winner.
- Supplier names were not mapped to OEMs.
- No provincial or federal streams were merged, no aliases were approved, and no prior file was overwritten.
- The candidate is pending independent review and is not delivery-ready.

## Access outcomes

- Direct EPMS HTTP, Playwright and in-app browser navigation timed out. Indexed official PPRA detail pages were used as the fallback evidence path.
- EPADS increment failed before the first listing page; the historical 17,623-row input remains unchanged through 2026-07-02.
- Punjab result endpoints timed out; Sindh BER failed the access/robots route; KP Health exposed the final BER listing but its attachment timed out; Balochistan Health exposed notices without final supplier/value outcomes.

See `audit/source_ledger.json`, `audit/access_gap_ledger.csv`, `audit/rejection_audit.csv`, `navigation/navigation.json`, and the raw evidence packet for full detail.
"""
(ROOT / "handoff.md").write_text(handoff, encoding="utf-8")

manifest_paths = [path for path in ROOT.rglob("*") if path.is_file() and path.name != "deliverables_manifest.json"]
manifest = {
    "created_on": "2026-09-30",
    "immutable_run_root": str(ROOT.resolve()),
    "files": [
        {"path": str(path.relative_to(ROOT)), "size": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(manifest_paths)
    ],
}
write_json(ROOT / "deliverables_manifest.json", manifest)

print(json.dumps(summary, ensure_ascii=False))
