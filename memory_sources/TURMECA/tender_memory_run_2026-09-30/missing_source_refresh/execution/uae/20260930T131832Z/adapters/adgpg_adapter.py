from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

from common import (
    CANONICAL_COLUMNS,
    DATE_FROM,
    DATE_TO,
    base_row,
    clean,
    redact_contact_text,
    session,
    stable_key,
    write_csv,
    write_json,
)


LIST_URL = "https://www.adgpg.gov.ae/SCAPI/ADGEs/AlMaqtaa/Tender/List"
DETAIL_URL = "https://www.adgpg.gov.ae/SCAPI/ADGEs/AlMaqtaa/Tender/Details/{tender_id}?recommendedLimit=3"
DETAIL_PAGE = "https://supplier.adgpg.gov.ae/pages/tender-detail.html?tenderid={tender_id}"
CATEGORIES = {
    "41000000": "Laboratory and Measuring and Observing and Testing Equipment",
    "42000000": "Medical Equipment and Accessories and Supplies",
    "51000000": "Drugs and Pharmaceutical Products",
    "85000000": "Healthcare Services",
}
MEDTECH_TERMS = re.compile(
    r"\b(medical|medtech|surgical|surgery|ivd|diagnostic|diagnostics|laborator(?:y|ies)|reagent|"
    r"test kit|blood|patholog|radiolog|clinical|patient monitor|dental|endoscop|implant|catheter|"
    r"ultrasound|x[- ]?ray|mri|ct scan|nursing|hospital equipment|pharmacy equipment)\b",
    re.I,
)


def parse_json_response(response: requests.Response) -> dict[str, Any]:
    value: Any = response.json()
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def in_review_scope(item: dict[str, Any], category: str) -> bool:
    if category == "42000000":
        return True
    text = " | ".join(clean(item.get(key)) for key in ("TenderName", "TenderDetails", "EntityName"))
    return bool(MEDTECH_TERMS.search(text))


def list_category(s: requests.Session, category: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    offset = 0
    limit = 1000
    all_rows: list[dict[str, Any]] = []
    first_payload: dict[str, Any] = {}
    while True:
        payload = {
            "status": "COMPL", "offset": str(offset), "limit": str(limit),
            "Category": category, "Entity": "", "Sorting": "LAST_CREATED",
            "DueDate": "", "Name": "",
        }
        response = s.post(LIST_URL, data=payload, timeout=90)
        response.raise_for_status()
        data = parse_json_response(response)
        if not first_payload:
            first_payload = data
        rows = data.get("TenderList", []) or []
        all_rows.extend(rows)
        total = int(data.get("TenderCount") or len(all_rows))
        offset += len(rows)
        if not rows or offset >= total:
            break
        if offset > 10000:
            raise RuntimeError(f"Pagination safety cap exceeded for category {category}")
    return {"TenderCount": first_payload.get("TenderCount"), "pages_complete": True}, all_rows


def fetch_detail(tender_id: str) -> dict[str, Any]:
    last_error = ""
    for attempt in range(3):
        try:
            response = requests.get(DETAIL_URL.format(tender_id=tender_id), headers={"User-Agent": session().headers["User-Agent"]}, timeout=60)
            response.raise_for_status()
            payload = parse_json_response(response)
            detail = payload.get("TenderDetails", payload)
            return {"tender_id": tender_id, "ok": True, "detail": detail}
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            time.sleep(0.5 * (attempt + 1))
    return {"tender_id": tender_id, "ok": False, "error": last_error, "detail": {}}


def first_value(detail: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = detail.get(key)
        if value not in (None, "", [], {}):
            return clean(value)
    return ""


def iso_date(value: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", clean(value))
    return match.group(1) if match else ""


def run(root: Path) -> dict:
    out = root / "sources" / "abu_dhabi_adgpg_public"
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    listing_meta: dict[str, Any] = {}
    selected_by_id: dict[str, dict[str, Any]] = {}
    category_memberships: dict[str, set[str]] = {}

    for category, label in CATEGORIES.items():
        summary, rows = list_category(s, category)
        write_json(out / f"raw_list_{category}.json", {"category": category, "label": label, "summary": summary, "TenderList": rows})
        listing_meta[category] = {"label": label, "reported_total": summary.get("TenderCount"), "retrieved": len(rows)}
        for item in rows:
            if not in_review_scope(item, category):
                continue
            tender_id = clean(item.get("TenderID"))
            if not tender_id:
                continue
            selected_by_id.setdefault(tender_id, item)
            category_memberships.setdefault(tender_id, set()).add(category)

    details: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_detail, tender_id): tender_id for tender_id in sorted(selected_by_id)}
        for future in as_completed(futures):
            details.append(future.result())
    details.sort(key=lambda item: item["tender_id"])
    with (out / "raw_details.jsonl").open("w", encoding="utf-8") as handle:
        for item in details:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    review_rows: list[dict[str, str]] = []
    award_rows: list[dict[str, str]] = []
    join_rows: list[dict[str, str]] = []
    rejects: list[dict[str, str]] = []
    status_counts: dict[str, int] = {}

    for result in details:
        tender_id = result["tender_id"]
        listing = selected_by_id[tender_id]
        detail = result.get("detail", {}) or {}
        title = first_value(detail, ("TenderName",)) or clean(listing.get("TenderName"))
        buyer = first_value(detail, ("EntityName",)) or clean(listing.get("EntityName"))
        portal_status = first_value(detail, ("TenderStatus", "Status"))
        internal_status = first_value(detail, ("InternalStatus",)) or clean(listing.get("InternalStatus"))
        status = " / ".join(value for value in ("Completed Tenders" if internal_status == "COMPL" else internal_status, portal_status) if value)
        status_counts[status or "blank"] = status_counts.get(status or "blank", 0) + 1
        event_id = first_value(detail, ("EventId", "EventID", "AuctionHeaderId"))
        discovery_url = first_value(detail, ("DiscoveryUrl", "DiscoveryURL"))
        supplier = first_value(detail, ("WinningSupplier", "AwardedSupplier", "SupplierName"))
        award_date = iso_date(first_value(detail, ("AwardDate", "ResultDate", "PublicationDate")))
        amount = first_value(detail, ("AwardAmount", "FinalValue", "ContractValue"))
        currency = first_value(detail, ("Currency", "CurrencyCode"))
        category_set = sorted(category_memberships.get(tender_id, set()))
        classification = "; ".join(f"UNSPSC {cat} - {CATEGORIES[cat]}" for cat in category_set)
        medtech_basis = "official category 42000000" if "42000000" in category_set else "medical keyword within official category " + ",".join(category_set)

        row = base_row("Abu Dhabi Government Procurement Gate - public API")
        row.update({
            "publication_date": award_date,
            "title": title,
            "title_english": title,
            "description": redact_contact_text(detail.get("TenderDetails") or listing.get("TenderDetails")),
            "description_english": redact_contact_text(detail.get("TenderDetails") or listing.get("TenderDetails")),
            "buyer": buyer,
            "buyer_english": buyer,
            "classification": classification,
            "status": status,
            "currency": currency,
            "amount": amount,
            "awarding_agency_name": buyer,
            "awarding_agency_name_english": buyer,
            "supplier_name": supplier,
            "supplier_name_english": supplier,
            "awarded_date": award_date,
            "item_no": "1",
            "item_description": title,
            "item_description_english": title,
            "notice_id": first_value(detail, ("TenderNumber",)) or clean(listing.get("TenderNumber")) or tender_id,
            "notice_url": DETAIL_PAGE.format(tender_id=tender_id),
            "_source_workbook": "ADGPG public API refresh 2026-09-30",
            "_duplicate_rows_removed": "0",
            "_dedupe_key": stable_key("adgpg", tender_id, event_id),
            "medtech_filter_basis": medtech_basis,
            "medtech_confidence": "high-category" if "42000000" in category_set else "medium-keyword",
        })
        review_rows.append(row)
        join_rows.append({
            "tender_id": tender_id,
            "notice_id": row["notice_id"],
            "event_id": event_id,
            "discovery_url": discovery_url,
            "portal_status": portal_status,
            "internal_status": internal_status,
            "bidding_open_date": iso_date(first_value(detail, ("BiddingOpenDate",))),
            "due_date": iso_date(first_value(detail, ("DueDate",))),
            "categories": ";".join(category_set),
            "detail_url": row["notice_url"],
        })

        awarded_status = bool(re.search(r"\b(awarded|contracted|purchase order issued)\b", status, re.I))
        date_ok = bool(award_date and DATE_FROM <= award_date <= DATE_TO)
        if awarded_status and supplier and date_ok:
            award_rows.append(row)
        else:
            reasons = []
            if not awarded_status:
                reasons.append("no_explicit_awarded_or_contracted_status")
            if not supplier:
                reasons.append("winning_supplier_missing")
            if not award_date:
                reasons.append("award_or_result_publication_date_missing")
            elif not date_ok:
                reasons.append("award_date_outside_scope")
            rejects.append({
                "tender_id": tender_id,
                "notice_id": row["notice_id"],
                "title": title,
                "status": status,
                "reason": ";".join(reasons),
                "evidence_url": row["notice_url"],
                "event_id": event_id,
                "discovery_url": discovery_url,
            })

    write_csv(out / "review_candidates.csv", review_rows, CANONICAL_COLUMNS)
    write_csv(out / "candidate_awarded_medtech.csv", award_rows, CANONICAL_COLUMNS)
    write_csv(out / "adgpg_event_join_keys.csv", join_rows, [
        "tender_id", "notice_id", "event_id", "discovery_url", "portal_status", "internal_status",
        "bidding_open_date", "due_date", "categories", "detail_url",
    ])
    write_csv(out / "rejected_or_unresolved.csv", rejects, [
        "tender_id", "notice_id", "title", "status", "reason", "evidence_url", "event_id", "discovery_url",
    ])
    audit = {
        "source": "Abu Dhabi Government Procurement Gate - public API",
        "listing_meta": listing_meta,
        "unique_medtech_review_candidates": len(review_rows),
        "detail_success": sum(1 for item in details if item.get("ok")),
        "detail_failure": sum(1 for item in details if not item.get("ok")),
        "status_counts": status_counts,
        "event_id_filled": sum(1 for row in join_rows if row["event_id"]),
        "discovery_url_filled": sum(1 for row in join_rows if row["discovery_url"]),
        "award_qualified_rows": len(award_rows),
        "decision": "Public COMPL is not treated as awarded. Only explicit awarded/contracted rows with winner and in-scope result date qualify.",
    }
    write_json(out / "source_audit.json", audit)
    return {"source_id": "abu_dhabi_adgpg_public", "award_rows": len(award_rows), "review_rows": len(review_rows), "status": "completed_public_refresh", "directory": str(out.resolve())}
