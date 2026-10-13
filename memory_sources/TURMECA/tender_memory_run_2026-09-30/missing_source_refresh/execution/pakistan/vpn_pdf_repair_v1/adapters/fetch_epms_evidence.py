#!/usr/bin/env python3
"""Fetch and freeze official Pakistan EPMS final-evaluation evidence.

The adapter is deliberately evidence-first: it stores the exact public detail-page
HTML and the linked official report response before attempting text extraction.
It does not infer contract award, value, quantity, or item attribution.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://epms.ppra.gov.pk"
DETAIL_URL = BASE_URL + "/public/evaluations/evaluation-details/{notice_id}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TenderEvidenceRepair/1.0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_pdf_text(pdf_path: Path) -> tuple[str, int, str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append(f"\n--- PAGE {index} ---\n{page.extract_text() or ''}")
        return "".join(pages).strip(), len(reader.pages), "pypdf"
    except Exception as exc:  # evidence remains usable even if extraction fails
        return "", 0, f"pypdf_error:{type(exc).__name__}:{exc}"


def parse_detail(html: bytes, page_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = clean((soup.find("h1") or soup.title).get_text(" ", strip=True))
    details: dict[str, str] = {}
    for node in soup.select(".list-group-item"):
        label_node = node.select_one(".detail-label")
        if not label_node:
            continue
        label = clean(label_node.get_text(" ", strip=True))
        label_node.extract()
        details[label] = clean(node.get_text(" ", strip=True))
    page_text = clean(soup.get_text(" ", strip=True))
    ev_match = re.search(r"Evaluation No:\s*(EVL\d+)", page_text, re.I)
    tender_match = re.search(r"Tender No:\s*(TS\d+E?)", page_text, re.I)
    report_url = ""
    for anchor in soup.find_all("a", href=True):
        if "Download Evaluation Report" in clean(anchor.get_text(" ", strip=True)):
            report_url = urljoin(page_url, anchor["href"])
            break
    return {
        "title": title,
        "evaluation_no": ev_match.group(1) if ev_match else "",
        "tender_no": tender_match.group(1) if tender_match else "",
        "report_url": report_url,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    raw_html = args.run_root / "raw" / "html"
    raw_pdf = args.run_root / "raw" / "pdf"
    raw_text = args.run_root / "raw" / "pdf_text"
    audit_dir = args.run_root / "audit"
    for path in (raw_html, raw_pdf, raw_text, audit_dir):
        path.mkdir(parents=True, exist_ok=True)

    with args.input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"})
    records = []
    evidence = []
    for source_row in rows:
        notice_id = source_row["notice_id"].strip()
        page_url = DETAIL_URL.format(notice_id=notice_id)
        rec = {
            "notice_id": notice_id,
            "detail_url": page_url,
            "detail_status": "",
            "html_path": "",
            "html_sha256": "",
            "html_bytes": 0,
            "report_url": "",
            "pdf_status": "not_linked",
            "pdf_path": "",
            "pdf_sha256": "",
            "pdf_bytes": 0,
            "pdf_pages": 0,
            "pdf_text_path": "",
            "pdf_text_sha256": "",
            "pdf_text_chars": 0,
            "pdf_text_method": "",
            "page_fields": {},
            "error": "",
        }
        try:
            response = session.get(page_url, timeout=60)
            rec["detail_status"] = str(response.status_code)
            response.raise_for_status()
            html_path = raw_html / f"{notice_id}.html"
            html_path.write_bytes(response.content)
            rec["html_path"] = html_path.relative_to(args.run_root).as_posix()
            rec["html_sha256"] = sha256_bytes(response.content)
            rec["html_bytes"] = len(response.content)
            parsed = parse_detail(response.content, page_url)
            rec["report_url"] = parsed["report_url"]
            rec["page_fields"] = parsed
            evidence.append({
                "notice_id": notice_id,
                "evidence_type": "official_epms_detail_html",
                "source_url": page_url,
                "path": rec["html_path"],
                "sha256": rec["html_sha256"],
                "bytes": rec["html_bytes"],
                "http_status": response.status_code,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            })
            if parsed["report_url"]:
                report = session.get(parsed["report_url"], timeout=120)
                rec["pdf_status"] = str(report.status_code)
                report.raise_for_status()
                content_type = report.headers.get("Content-Type", "")
                if not report.content.startswith(b"%PDF"):
                    raise ValueError(
                        f"report response is not PDF: {content_type}; {report.content[:80]!r}"
                    )
                pdf_path = raw_pdf / f"{notice_id}.pdf"
                pdf_path.write_bytes(report.content)
                rec["pdf_path"] = pdf_path.relative_to(args.run_root).as_posix()
                rec["pdf_sha256"] = sha256_bytes(report.content)
                rec["pdf_bytes"] = len(report.content)
                text, pages, method = extract_pdf_text(pdf_path)
                rec["pdf_pages"] = pages
                rec["pdf_text_method"] = method
                text_path = raw_text / f"{notice_id}.txt"
                text_path.write_text(text, encoding="utf-8")
                text_bytes = text.encode("utf-8")
                rec["pdf_text_path"] = text_path.relative_to(args.run_root).as_posix()
                rec["pdf_text_sha256"] = sha256_bytes(text_bytes)
                rec["pdf_text_chars"] = len(text)
                retrieved_at = datetime.now(timezone.utc).isoformat()
                evidence.extend([
                    {
                        "notice_id": notice_id,
                        "evidence_type": "official_evaluation_report_pdf",
                        "source_url": parsed["report_url"],
                        "path": rec["pdf_path"],
                        "sha256": rec["pdf_sha256"],
                        "bytes": rec["pdf_bytes"],
                        "http_status": report.status_code,
                        "retrieved_at_utc": retrieved_at,
                    },
                    {
                        "notice_id": notice_id,
                        "evidence_type": "derived_pdf_text",
                        "source_url": parsed["report_url"],
                        "path": rec["pdf_text_path"],
                        "sha256": rec["pdf_text_sha256"],
                        "bytes": len(text_bytes),
                        "http_status": report.status_code,
                        "retrieved_at_utc": retrieved_at,
                    },
                ])
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        records.append(rec)
        time.sleep(args.delay)

    payload = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_csv": str(args.input_csv.resolve()),
        "run_root": str(args.run_root.resolve()),
        "record_count": len(records),
        "records": records,
    }
    (audit_dir / "fetch_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.run_root / "evidence_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "entries": evidence,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "notices": len(records),
        "html_downloaded": sum(bool(r["html_path"]) for r in records),
        "pdf_downloaded": sum(bool(r["pdf_path"]) for r in records),
        "errors": [{"notice_id": r["notice_id"], "error": r["error"]} for r in records if r["error"]],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
