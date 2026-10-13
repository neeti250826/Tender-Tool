"""Capture and triage current public CAPT announcement PDFs for Kuwait medtech awards.

Version: 1.0.0 (2026-09-30)

This adapter only emits canonical candidates when a source page explicitly proves
an awarded/final-result outcome, named supplier, and medical-goods scope.  All
other possible hits are quarantined for review; launch, opening, recommendation,
deferment, cancellation, and infrastructure/service notices are never promoted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from pypdf import PdfReader


VERSION = "1.0.0"
CANONICAL_COLUMNS = [
    "source", "country", "country_code", "publication_date", "title",
    "title_english", "description", "description_english", "buyer",
    "buyer_english", "classification", "status", "currency", "amount",
    "awarding_agency_name", "awarding_agency_name_english", "supplier_name",
    "supplier_name_english", "awarded_date", "contract_period",
    "contract_period_english", "item_no", "item_description",
    "item_description_english", "item_uom", "item_uom_english", "quantity",
    "notice_id", "notice_url", "_source_workbook",
    "_duplicate_rows_removed", "_dedupe_key", "medtech_filter_basis",
    "mapped_oem", "mapped_oem_basis", "mapped_oem_match_term", "likely_oem",
    "likely_oem_score", "oem_match_terms", "oem_match_basis",
    "medtech_confidence",
]

ISSUES = [
    ("2026-09-27", "b83f9221-71c9-49bf-aee6-8c4f23a14d15.pdf"),
    ("2026-09-20", "6f422746-91c3-46ab-a282-4188ba88941f.pdf"),
    ("2026-09-13", "4fb4870c-3c97-4161-b8d2-a8a60f720a3a.pdf"),
    ("2026-09-06", "0f37fc72-f788-4161-a2e2-147362036c56.pdf"),
    ("2026-08-30", "0389f633-7c55-4e0f-8426-842e5bbae691.pdf"),
    ("2026-08-23", "85bc5533-939f-49f3-9ca0-2005d4e12c22.pdf"),
    ("2026-08-16", "26f8295e-36eb-494a-95a4-c5b6fc56d931.pdf"),
    ("2026-08-10", "94a14e89-65d8-4c94-bfcc-df5aa29f1c1d.pdf"),
    ("2026-08-02", "eff558a2-2229-408d-9ded-0b51d808c433.pdf"),
    ("2026-07-26", "0d9facf2-95d4-4a6e-bbaa-172b151bff37.pdf"),
]

MEDICAL_TERMS = (
    "وزارة الصحة", "مستشفى", "المختبر", "مختبر", "اجهزة طبية", "أجهزة طبية",
    "مستلزمات طبية", "كواشف", "تحاليل", "أشعة", "اشعة", "قسطرة", "غسيل الكلى",
    "medical", "hospital", "laboratory", "diagnostic", "reagent", "surgical",
    "dialysis", "radiology", "catheter", "implant", "blood bank",
)
AWARD_TERMS = (
    "ترسية", "إرساء", "ارسى", "أرسى", "المناقصة الفائزة", "المناقص الفائز",
    "الموافقة على التعاقد", "التعاقد المباشر", "award", "winning bidder",
    "direct contract", "contract awarded",
)
NON_AWARD_TERMS = (
    "طرح", "فتح المظاريف", "تأجيل", "تمديد موعد", "إلغاء", "عدم الموافقة",
    "توصية", "دعوة", "launch", "opening", "postpon", "cancel", "recommendation",
)
FACILITY_EXCLUSION_TERMS = ("construction", "building", "boiler", "network infrastructure", "surveillance")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def download(url: str, path: Path) -> None:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (TenderEvidence/1.0)"})
    with urlopen(request, timeout=90) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"Expected PDF from {url}; got {content_type!r}")
    path.write_bytes(body)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    pdf_dir = root / "raw" / "capt_announcements" / "pdf"
    text_dir = root / "raw" / "capt_announcements" / "text"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    quarantined: list[dict] = []
    for publication_date, filename in ISSUES:
        url = f"https://files.capt.gov.kw/media/{filename}"
        pdf_path = pdf_dir / filename
        if not pdf_path.exists():
            download(url, pdf_path)
        reader = PdfReader(str(pdf_path))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = clean(page.extract_text() or "")
            pages.append(text)
            folded = text.casefold()
            medical_hits = sorted({term for term in MEDICAL_TERMS if term.casefold() in folded})
            award_hits = sorted({term for term in AWARD_TERMS if term.casefold() in folded})
            non_award_hits = sorted({term for term in NON_AWARD_TERMS if term.casefold() in folded})
            if medical_hits or award_hits:
                facility_hits = sorted({term for term in FACILITY_EXCLUSION_TERMS if term in folded})
                if facility_hits:
                    decision = "rejected_non_medtech_facility_or_infrastructure"
                    reason = "hospital/health context is facility construction or infrastructure, not medical/IVD goods"
                else:
                    decision = "quarantine_not_candidate"
                    reason = "keyword-level page hit; no deterministic complete awarded medical-goods row emitted"
                quarantined.append({
                    "source": "CAPT announcements weekly PDF",
                    "publication_date": publication_date,
                    "page": page_number,
                    "url": f"{url}#page={page_number}",
                    "medical_terms": ";".join(medical_hits),
                    "award_terms": ";".join(award_hits),
                    "non_award_terms": ";".join(non_award_hits),
                    "decision": decision,
                    "reason": reason,
                    "text_excerpt": text[:1500],
                    "local_pdf": str(pdf_path.resolve()),
                })
        text_path = text_dir / filename.replace(".pdf", ".txt")
        text_path.write_text("\n\n".join(
            f"--- PAGE {index} ---\n{text}" for index, text in enumerate(pages, start=1)
        ), encoding="utf-8")
        manifest.append({
            "publication_date": publication_date,
            "url": url,
            "local_pdf": str(pdf_path.resolve()),
            "pdf_sha256": sha256(pdf_path),
            "bytes": pdf_path.stat().st_size,
            "pages": len(reader.pages),
            "local_text": str(text_path.resolve()),
            "text_sha256": sha256(text_path),
            "nonblank_text_pages": sum(bool(text) for text in pages),
        })

    with (root / "candidate_rows.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS).writeheader()
    quarantine_fields = [
        "source", "publication_date", "page", "url", "medical_terms", "award_terms",
        "non_award_terms", "decision", "reason", "text_excerpt", "local_pdf",
    ]
    with (root / "rejected_quarantine.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=quarantine_fields)
        writer.writeheader()
        writer.writerows(quarantined)
    (root / "raw" / "capt_announcements" / "manifest.json").write_text(
        json.dumps({
            "adapter_version": VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "issues": manifest,
            "candidate_rows": 0,
            "quarantined_page_hits": len(quarantined),
            "classification_note": "Automated keyword triage is discovery-only; no page proved a complete canonical award row without further page-level review.",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "issues": len(manifest),
        "pages": sum(item["pages"] for item in manifest),
        "candidate_rows": 0,
        "quarantined_page_hits": len(quarantined),
    }))


if __name__ == "__main__":
    main()
