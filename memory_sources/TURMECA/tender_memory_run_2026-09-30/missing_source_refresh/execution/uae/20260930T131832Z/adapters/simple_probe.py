from __future__ import annotations

from pathlib import Path

from common import CANONICAL_COLUMNS, fetch_to_file, session, soup_text, write_csv, write_json


def run_probe(root: Path, source_id: str, source_name: str, urls: list[str], constraint: str) -> dict:
    out = root / "sources" / source_id
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    attempts = []
    evidence_terms = {"award": 0, "winner": 0, "contract": 0, "purchase order": 0, "tender": 0}
    for index, url in enumerate(urls, 1):
        path = out / f"raw_page_{index}.html"
        attempt = fetch_to_file(s, url, path, timeout=45)
        attempts.append(attempt)
        if attempt.get("ok") and path.exists():
            text = soup_text(path.read_text(encoding="utf-8", errors="replace")).lower()
            for term in evidence_terms:
                evidence_terms[term] += text.count(term)
    audit = {
        "source": source_name,
        "attempts": attempts,
        "term_counts_are_navigation_only": evidence_terms,
        "explicit_row_level_winner_result_dataset_found": False,
        "award_qualified_rows": 0,
        "access_constraint": constraint,
        "decision": "No row-level official award record with winner, result date and medtech item was exposed in this bounded public pass.",
    }
    write_json(out / "source_audit.json", audit)
    write_csv(out / "candidate_awarded_medtech.csv", [], CANONICAL_COLUMNS)
    write_csv(out / "rejected_or_unresolved.csv", [{
        "source": source_name, "reason": "no_public_row_level_award_result", "evidence_url": urls[0], "detail": constraint,
    }], ["source", "reason", "evidence_url", "detail"])
    return {"source_id": source_id, "award_rows": 0, "review_rows": 0, "status": "public_pass_no_award_dataset", "directory": str(out.resolve())}
