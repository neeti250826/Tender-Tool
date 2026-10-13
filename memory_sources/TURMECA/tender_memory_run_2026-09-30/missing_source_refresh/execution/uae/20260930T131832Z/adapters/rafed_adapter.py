from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import CANONICAL_COLUMNS, fetch_to_file, session, write_csv, write_json


HOME = "https://www.rafeduae.ae/"


def run(root: Path) -> dict:
    out = root / "sources" / "abu_dhabi_rafed_public"
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    attempts = [fetch_to_file(s, HOME, out / "raw_home.html")]
    procurement_links = []
    if attempts[0].get("ok"):
        soup = BeautifulSoup((out / "raw_home.html").read_text(encoding="utf-8", errors="replace"), "html.parser")
        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.get_text(" ", strip=True).split())
            href = urljoin(HOME, anchor["href"])
            if any(term in (text + " " + href).lower() for term in ("tender", "auction", "vendor", "supplier", "oracle", "fusion", "procure")):
                procurement_links.append({"text": text, "url": href})
    unique_links = []
    seen = set()
    for item in procurement_links:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique_links.append(item)
    analysis = {
        "source": "Rafed healthcare procurement public layer",
        "attempts": attempts,
        "procurement_links": unique_links,
        "public_award_archive_found": False,
        "award_qualified_rows": 0,
        "authenticated_result_access": "Oracle Fusion vendor login/native export required",
        "decision": "Public corporate pages provide entry links only; no winner/final-value result dataset was exposed.",
    }
    write_json(out / "access_and_award_audit.json", analysis)
    write_csv(out / "candidate_awarded_medtech.csv", [], CANONICAL_COLUMNS)
    write_csv(out / "rejected_or_unresolved.csv", [{
        "source": analysis["source"],
        "reason": "authenticated_oracle_fusion_export_required",
        "evidence_url": HOME,
        "detail": "No public award archive found. A user-authorized native award/PO/contract export is required; no login or access-control bypass was attempted.",
    }], ["source", "reason", "evidence_url", "detail"])
    return {"source_id": "abu_dhabi_rafed_public", "award_rows": 0, "review_rows": 0, "status": "public_entry_only", "directory": str(out.resolve())}
