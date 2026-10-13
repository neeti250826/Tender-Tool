from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import CANONICAL_COLUMNS, base_row, clean, session, stable_key, write_csv, write_json


BASE = "https://esupply.dubai.gov.ae"
HOME = f"{BASE}/esupply/web/index.html"
GUEST_CURRENT = f"{BASE}/esop/guest/go/public/opportunity/current?locale=en_GB&customLoginPage=/esupply/web/index.html"
CURRENT = f"{BASE}/esop/toolkit/opportunity/current/list.si?reset=true&resetstored=true"
PAST = f"{BASE}/esop/toolkit/opportunity/past/list.si?reset=true&resetstored=true"


def fetch_step(s, url: str, path: Path, referer: str = "") -> dict:
    headers = {"Referer": referer} if referer else {}
    meta = {"url": url, "tls_verify": True}
    try:
        response = s.get(url, headers=headers, timeout=90, allow_redirects=True)
        path.write_bytes(response.content)
        meta.update({
            "ok": response.ok,
            "status_code": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
            "content_type": response.headers.get("Content-Type", ""),
            "expired_session": "session is invalid or expired" in response.text.lower(),
            "unsupported_browser": "unsupported browser" in response.text.lower(),
        })
    except Exception as exc:
        meta.update({"ok": False, "error_type": exc.__class__.__name__, "error": str(exc)})
    return meta


def parse_date(text: str) -> str:
    match = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", text)
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def parse_rows(html: str, page_url: str, status: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    past = "/past/" in page_url
    for tr in soup.select("table.list-table tbody tr"):
        cells = tr.select("td")
        if len(cells) < 6:
            continue
        buyer = clean(cells[1].get_text(" ", strip=True))
        link = cells[2].select_one("a.detailLink")
        title = clean((link.get("title", "") if link else cells[2].get_text(" ", strip=True))).removeprefix("View Details:").strip()
        publication_date = parse_date(cells[3].get_text(" ", strip=True))
        classification = clean(cells[4].get_text(" ", strip=True))
        onclick = clean(link.get("onclick", "")) if link else ""
        match = re.search(r"goToDetail\('([^']+)'", onclick)
        notice_id = match.group(1) if match else stable_key(title, buyer, publication_date)
        detail_kind = "past" if past else "current"
        detail_url = f"{BASE}/esop/toolkit/opportunity/{detail_kind}/{notice_id}/detail.si"
        row = base_row("Dubai eSupply public opportunities")
        row.update({
            "publication_date": publication_date,
            "title": title,
            "title_english": title,
            "description": " | ".join(value for value in (title, buyer, classification) if value),
            "description_english": " | ".join(value for value in (title, buyer, classification) if value),
            "buyer": buyer,
            "buyer_english": buyer,
            "classification": classification,
            "status": status,
            "awarding_agency_name": buyer,
            "awarding_agency_name_english": buyer,
            "item_no": "1",
            "item_description": title,
            "item_description_english": title,
            "notice_id": notice_id,
            "notice_url": detail_url,
            "_source_workbook": "Dubai eSupply public live session refresh 2026-09-30",
            "_duplicate_rows_removed": "0",
            "_dedupe_key": stable_key("dubai-esupply", notice_id),
            "medtech_filter_basis": "public title/buyer/category keyword review",
            "medtech_confidence": "review-required",
        })
        rows.append(row)
    return rows


def medical_signal(row: dict[str, str]) -> bool:
    text = " | ".join(row.get(key, "") for key in ("title", "description", "buyer", "classification")).lower()
    return any(term in text for term in (
        "medical", "surgical", "laboratory", "diagnostic", "reagent", "hospital", "clinic", "ambulance",
        "pharma", "drug", "medicine", "dental", "implant", "catheter", "test kit", "consumable",
    ))


def read_prior_canonical(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [{column: row.get(column, "") for column in CANONICAL_COLUMNS} for row in csv.DictReader(handle)]


def run(root: Path) -> dict:
    out = root / "sources" / "dubai_esupply_public"
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    steps = []
    sequence = [
        ("home", HOME, ""),
        ("guest_current", GUEST_CURRENT, HOME),
        ("current_list", CURRENT, GUEST_CURRENT),
        ("past_list", PAST, CURRENT),
    ]
    for name, url, referer in sequence:
        steps.append({"name": name, **fetch_step(s, url, out / f"raw_{name}.html", referer)})

    live_rows = []
    current_path = out / "raw_current_list.html"
    past_path = out / "raw_past_list.html"
    if current_path.exists() and next((x for x in steps if x["name"] == "current_list"), {}).get("status_code") == 200:
        live_rows.extend(parse_rows(current_path.read_text(encoding="utf-8", errors="replace"), CURRENT, "published"))
    if past_path.exists() and next((x for x in steps if x["name"] == "past_list"), {}).get("status_code") == 200:
        live_rows.extend(parse_rows(past_path.read_text(encoding="utf-8", errors="replace"), PAST, "closed"))
    live_medical = [row for row in live_rows if medical_signal(row)]

    workspace = root.parents[4]
    prior_path = workspace / "tender_memory_run_2026-09-30" / "agent_handoffs" / "uae" / "candidate_dubai_esupply_closed_medical_2026-06-01.csv"
    prior_rows = read_prior_canonical(prior_path)
    write_csv(out / "review_candidates_live.csv", live_medical, CANONICAL_COLUMNS)
    write_csv(out / "review_candidates_prior_frozen_baseline.csv", prior_rows, CANONICAL_COLUMNS)
    write_csv(out / "candidate_awarded_medtech.csv", [], CANONICAL_COLUMNS)
    rejects = []
    for row in live_medical:
        rejects.append({
            "notice_id": row["notice_id"], "title": row["title"], "status": row["status"],
            "reason": "public_past_or_published_is_not_awarded;winner_missing;final_value_missing;award_date_missing",
            "evidence_url": row["notice_url"], "evidence_generation": "live_2026-09-30",
        })
    for row in prior_rows:
        rejects.append({
            "notice_id": row["notice_id"], "title": row["title"], "status": row["status"],
            "reason": "prior_frozen_review_candidate_not_refreshed;winner_missing;final_value_missing;award_date_missing",
            "evidence_url": row["notice_url"], "evidence_generation": "prior_frozen_baseline",
        })
    write_csv(out / "rejected_or_unresolved.csv", rejects, [
        "notice_id", "title", "status", "reason", "evidence_url", "evidence_generation",
    ])
    audit = {
        "source": "Dubai eSupply public opportunity layer",
        "session_sequence": steps,
        "live_listing_rows_parsed": len(live_rows),
        "live_medical_review_candidates": len(live_medical),
        "prior_frozen_baseline_rows": len(prior_rows),
        "award_qualified_rows": 0,
        "browser_note": "A fresh Edge tab reached the eSupply homepage, but subagent browser binding timed out; no browser state or credentials were reused.",
        "authenticated_result_access": "blocked_without_user-authorized eSupply/iSupplier export",
        "decision": "Past/closed/published rows are review candidates only. No winner/final-value evidence was exposed publicly.",
    }
    write_json(out / "source_audit.json", audit)
    status = "live_lists_extracted" if live_medical else "homepage_reachable_guest_and_list_routes_failed"
    return {"source_id": "dubai_esupply_public", "award_rows": 0, "review_rows": len(live_medical), "prior_baseline_rows": len(prior_rows), "status": status, "directory": str(out.resolve())}
