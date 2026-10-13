from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT.parent / "ksa" / "raw_evidence" / "final_results"
NOTICE_SOURCE = ROOT.parent / "ksa" / "official_final_result_notices.json"

TARGETS = [
    "NPT0008/25", "NPT0015/25", "NPT0018/25", "NPT0020/25",
    "NPT0021/24", "NPT0027/25", "NPT0028/25", "NPT0033/24",
    "NPT0038/25", "NPT0043/25", "NPT0046/24", "NPT0047/24",
    "NPT0048/24", "NPT0064/25",
]

# Absolute x-coordinate bands derived from the visible official PDF table headers.
# These profiles are deliberately notice-bounded; unknown layouts are not guessed.
PROFILES = {
    "NPT0008/25": {"sn": (110, 145), "nupco_code": (145, 240), "item_description": (240, 390), "supplier_name": (390, 510), "manufacturer": (510, 620), "model_or_catalog_no": (620, 840)},
    "NPT0015/25": {"sn": (15, 45), "nupco_code": (45, 145), "item_description": (145, 440), "supplier_name": (440, 580), "manufacturer": (580, 690), "model_or_catalog_no": (690, 842)},
    "NPT0018/25": {"sn": (45, 70), "nupco_code": (80, 175), "item_description": (175, 360), "supplier_name": (360, 510), "manufacturer": (510, 660), "model_or_catalog_no": (660, 842)},
    "NPT0027/25": {"sn": (45, 70), "nupco_code": (75, 160), "item_description": (160, 345), "supplier_name": (345, 480), "manufacturer": (480, 630), "model_or_catalog_no": (630, 842)},
    "NPT0028/25": {"sn": (110, 145), "nupco_code": (145, 240), "item_description": (240, 390), "supplier_name": (390, 510), "manufacturer": (510, 620), "model_or_catalog_no": (620, 840)},
    "NPT0020/25": {"sn": (20, 45), "nupco_code": (45, 95), "item_description": (95, 270), "group": (270, 305), "supplier_code": (305, 345), "supplier_name": (345, 425), "model_or_catalog_no": (425, 585), "manufacturer": (585, 645), "country_of_origin": (645, 695), "remarks": (695, 792)},
    "NPT0021/24": {"sn": (15, 55), "nupco_code": (55, 140), "item_reference": (140, 215), "item_description": (215, 460), "supplier_code": (460, 520), "supplier_name": (520, 700), "model_or_catalog_no": (700, 810), "manufacturer": (810, 920), "country_of_origin": (920, 1000), "remarks": (1000, 1095), "group": (1095, 1191)},
    "NPT0033/24": {"sn": (15, 50), "nupco_code": (50, 125), "item_reference": (125, 205), "item_description": (205, 350), "supplier_code": (350, 405), "supplier_name": (405, 520), "model_or_catalog_no": (520, 600), "country_of_origin": (600, 660), "manufacturer": (660, 750), "group": (750, 842)},
    "NPT0038/25": {"sn": (15, 50), "nupco_code": (50, 120), "item_description": (120, 450), "uom": (450, 485), "group": (485, 545), "supplier_code": (545, 595), "supplier_name": (595, 695), "manufacturer": (695, 765), "country_of_origin": (765, 825), "model_or_catalog_no": (825, 1090), "remarks": (1090, 1191)},
    "NPT0043/25": {"sn": (50, 68), "nupco_code": (68, 102), "document_qty": (102, 120), "item_description": (120, 255), "uom": (255, 282), "group": (282, 315), "supplier_code": (315, 343), "supplier_name": (343, 383), "manufacturer": (383, 418), "country_of_origin": (418, 442), "model_or_catalog_no": (442, 477), "remarks": (477, 595)},
    "NPT0046/24": {"sn": (15, 50), "item_folder": (50, 125), "nupco_code": (125, 205), "item_reference": (205, 270), "item_description": (270, 480), "supplier_code": (480, 525), "supplier_name": (525, 630), "model_or_catalog_no": (630, 690), "manufacturer": (690, 765), "country_of_origin": (765, 842)},
    "NPT0047/24": {"sn": (15, 50), "group": (50, 160), "nupco_code": (160, 225), "item_reference": (225, 285), "item_description": (285, 425), "supplier_code": (425, 475), "supplier_name": (475, 590), "model_or_catalog_no": (590, 660), "manufacturer": (660, 750), "country_of_origin": (750, 842)},
    "NPT0064/25": {"sn": (15, 45), "nupco_code": (45, 110), "item_reference": (110, 165), "item_description": (165, 295), "supplier_code": (295, 335), "supplier_name": (335, 460), "model_or_catalog_no": (460, 530), "manufacturer": (530, 625), "country_of_origin": (625, 690), "remarks": (690, 755), "group": (755, 842)},
}

FIELDS = [
    "notice_id", "pdf_page", "sn", "nupco_code", "item_reference", "item_description",
    "group", "uom", "document_qty", "supplier_code", "supplier_name",
    "model_or_catalog_no", "manufacturer", "country_of_origin", "remarks", "row_disposition",
    "publication_date", "publication_date_basis", "quantity_mapping_decision", "notice_url",
    "official_final_result_url", "evidence_pdf", "evidence_sha256", "extraction_method",
]


def clean(value: str) -> str:
    return " ".join((value or "").replace("\ufffd", " ").split())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def join_words(words: list[dict], low: float, high: float) -> str:
    chosen = [w for w in words if low <= (w["x0"] + w["x1"]) / 2 < high]
    chosen.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
    return clean(" ".join(w["text"] for w in chosen))


def printed_result_date(pdf: Path) -> tuple[str, str]:
    reader = PdfReader(pdf)
    samples = []
    for index in sorted(set([0, len(reader.pages) - 1])):
        if 0 <= index < len(reader.pages):
            samples.append(reader.pages[index].extract_text() or "")
    text = "\n".join(samples)
    month = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b", text, re.I)
    if month:
        parsed = datetime.strptime(month.group(0).title(), "%B %d, %Y").date().isoformat()
        return parsed, f"printed_in_final_result_pdf:{month.group(0)}"
    return "", "no explicit result-publication date visible in first/last PDF page"


def detect_disposition(values: dict[str, str]) -> str:
    combined = " ".join(values.values()).upper()
    if any(term in combined for term in ("CANCELLED", "CANCELED", "NO BID ACCEPTED", "NO ACCEPTED OFFER", "NO QUOTE", "HOLD")):
        return "cancelled_or_not_awarded"
    if values.get("supplier_name"):
        return "awarded_candidate"
    return "unresolved_no_supplier"


def row_starts(words: list[dict], profile: dict[str, tuple[float, float]]) -> list[tuple[float, str, str]]:
    starts = []
    code_low, code_high = profile["nupco_code"]
    sn_low, sn_high = profile["sn"]
    for code in words:
        center = (code["x0"] + code["x1"]) / 2
        if not (code_low <= center < code_high and re.fullmatch(r"\d{11,14}", code["text"])):
            continue
        sn_matches = [w for w in words if sn_low <= (w["x0"] + w["x1"]) / 2 < sn_high and re.fullmatch(r"\d{1,5}", w["text"]) and abs(w["top"] - code["top"]) <= 3]
        if sn_matches:
            starts.append((code["top"], sn_matches[0]["text"], code["text"]))
    unique = {}
    for start in starts:
        unique[(round(start[0], 1), start[2])] = start
    return sorted(unique.values())


def extract_notice(notice_id: str, pdf: Path, meta: dict) -> tuple[list[dict[str, str]], dict]:
    profile = PROFILES.get(notice_id)
    publication_date, publication_basis = printed_result_date(pdf)
    if profile is None:
        return [], {
            "status": "unresolved_non_tabular_announcement",
            "reason": "official PDF publishes manufacturer names only; no item/supplier award table",
            "pages": len(PdfReader(pdf).pages),
            "publication_date": publication_date,
            "publication_date_basis": publication_basis,
        }
    output = []
    with pdfplumber.open(pdf) as doc:
        for page_no, page in enumerate(doc.pages, start=1):
            words = page.extract_words(x_tolerance=1, y_tolerance=2, keep_blank_chars=False)
            starts = row_starts(words, profile)
            for index, (anchor_top, sn, code) in enumerate(starts):
                previous = starts[index - 1][0] if index else None
                following = starts[index + 1][0] if index + 1 < len(starts) else None
                top = (previous + anchor_top) / 2 if previous is not None else max(0, anchor_top - 18)
                bottom = (anchor_top + following) / 2 if following is not None else min(page.height, anchor_top + 35)
                block = [w for w in words if top <= w["top"] < bottom]
                values = {name: join_words(block, *bounds) for name, bounds in profile.items()}
                values["sn"] = sn
                values["nupco_code"] = code
                disposition = detect_disposition(values)
                output.append({
                    "notice_id": notice_id,
                    "pdf_page": str(page_no),
                    "sn": sn,
                    "nupco_code": code,
                    "item_reference": values.get("item_reference", ""),
                    "item_description": values.get("item_description", ""),
                    "group": values.get("group", ""),
                    "uom": values.get("uom", ""),
                    "document_qty": values.get("document_qty", ""),
                    "supplier_code": values.get("supplier_code", ""),
                    "supplier_name": values.get("supplier_name", ""),
                    "model_or_catalog_no": values.get("model_or_catalog_no", ""),
                    "manufacturer": values.get("manufacturer", ""),
                    "country_of_origin": values.get("country_of_origin", ""),
                    "remarks": values.get("remarks", ""),
                    "row_disposition": disposition,
                    "publication_date": publication_date,
                    "publication_date_basis": publication_basis,
                    "quantity_mapping_decision": "not mapped: generic QTY is not explicitly labeled awarded quantity" if values.get("document_qty") else "no explicit awarded-quantity column",
                    "notice_url": meta.get("notice_url", ""),
                    "official_final_result_url": meta.get("final_result_url", ""),
                    "evidence_pdf": str(pdf.resolve()),
                    "evidence_sha256": sha256(pdf),
                    "extraction_method": "bounded_pdfplumber_coordinate_profile_v2",
                })
    summary = {
        "status": "extracted" if output else "unresolved_no_rows",
        "pages": len(PdfReader(pdf).pages),
        "rows_extracted": len(output),
        "awarded_candidates": sum(row["row_disposition"] == "awarded_candidate" for row in output),
        "cancelled_or_not_awarded": sum(row["row_disposition"] == "cancelled_or_not_awarded" for row in output),
        "unresolved_no_supplier": sum(row["row_disposition"] == "unresolved_no_supplier" for row in output),
        "publication_date": publication_date,
        "publication_date_basis": publication_basis,
        "pdf": str(pdf.resolve()),
        "pdf_sha256": sha256(pdf),
        "parser_profile": notice_id,
    }
    return output, summary


def main() -> None:
    notices = {row["notice_id"]: row for row in json.loads(NOTICE_SOURCE.read_text(encoding="utf-8"))}
    all_rows = []
    log = {}
    for notice_id in TARGETS:
        pdf = SOURCE_ROOT / f"{notice_id.replace('/', '_')}-final-result.pdf"
        if not pdf.exists():
            log[notice_id] = {"status": "missing_pdf"}
            continue
        rows, summary = extract_notice(notice_id, pdf, notices.get(notice_id, {}))
        all_rows.extend(rows)
        log[notice_id] = summary
    with (ROOT / "custom_parser_rows.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    (ROOT / "custom_parser_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "ocr_log.json").write_text(json.dumps({
        "attempted": False,
        "reason": "All 14 prior parser failures contain machine-readable text; deterministic coordinate parsing was used. NPT0048/24 is non-tabular, not image-only.",
        "targets_reviewed": TARGETS,
    }, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(all_rows), "log": log}, ensure_ascii=False))


if __name__ == "__main__":
    main()
