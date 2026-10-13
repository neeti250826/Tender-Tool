from __future__ import annotations

from pathlib import Path

from common import CANONICAL_COLUMNS, fetch_to_file, session, soup_text, write_csv, write_json


URLS = {
    "overview": "https://mof.gov.ae/en/public-finance/government-procurement/digital-procurement-platform/",
    "public_opportunities": "https://mof.gov.ae/en/public-finance/government-procurement/current-business-opportunities/",
    "supplier_register": "https://mof.gov.ae/en/services/register-suppliers-in-the-federal-supplier-register/",
    "authenticated_portal": "https://procurement.gov.ae/page.aspx/en/usr/login",
}


def run(root: Path) -> dict:
    out = root / "sources" / "federal_dpp_public"
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    attempts = []
    page_text = ""
    for name, url in URLS.items():
        ext = ".html"
        attempt = fetch_to_file(s, url, out / f"raw_{name}{ext}")
        attempts.append({"name": name, **attempt})
        if name == "public_opportunities" and attempt.get("ok"):
            page_text = soup_text((out / f"raw_{name}{ext}").read_text(encoding="utf-8", errors="replace"))

    component_error = "Something went wrong" in page_text and "error loading the data" in page_text
    analysis = {
        "source": "UAE Ministry of Finance Digital Procurement Platform - public layer",
        "attempts": attempts,
        "public_surface": "open tenders/current opportunities",
        "public_component_error_observed": component_error,
        "winner_fields_observed": False,
        "final_value_fields_observed": False,
        "award_qualified_rows": 0,
        "authenticated_result_access": "blocked_without_user-authorized UAE PASS/supplier session or native export",
        "decision": "No public row can qualify as an award; public opportunity and login evidence are retained only.",
    }
    write_json(out / "access_and_award_audit.json", analysis)
    write_csv(out / "candidate_awarded_medtech.csv", [], CANONICAL_COLUMNS)
    write_csv(out / "rejected_or_unresolved.csv", [{
        "source": analysis["source"],
        "reason": "public_surface_is_open_opportunities_not_awards",
        "evidence_url": URLS["public_opportunities"],
        "detail": "The public page explicitly labels the list Open tenders and did not expose winner/final-value evidence; its data component also rendered an error during refresh.",
    }, {
        "source": analysis["source"],
        "reason": "authenticated_award_export_required",
        "evidence_url": URLS["authenticated_portal"],
        "detail": "A legitimate UAE PASS/supplier session or official native export is required. No authentication or MFA bypass was attempted.",
    }], ["source", "reason", "evidence_url", "detail"])
    return {"source_id": "federal_dpp_public", "award_rows": 0, "review_rows": 0, "status": "public_open_only_and_component_error", "directory": str(out.resolve())}
