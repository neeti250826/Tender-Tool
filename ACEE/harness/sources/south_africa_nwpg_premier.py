from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import fitz
import requests
from bs4 import BeautifulSoup
from requests import RequestException

from harness.shared.normalize import normalize_text, utc_now_iso
from harness.shared.schema import OutputRow
from harness.sources.base import SmokeProbeResult
from harness.sources.registry import SOURCES


CONFIG = SOURCES["south_africa_nwpg_premier"]
INDEX_URL = "https://premier.nwpg.gov.za/tenders/"
EVIDENCE_INDEX_PATH = Path("evidence") / "nwpg_premier_tenders_live.html"
EVIDENCE_SAMPLE_PDF_PATH = Path("evidence") / "nwpg_premier_number_34_2025_2026.pdf"
REQUEST_TIMEOUT_SECONDS = 60
HEALTH_AWARDS_HEADING = "DEPARTMENT OF HEALTH TERM CONTRACT AWARDS"
SAMPLE_BULLETIN_TITLE = "NUMBER 34 0F 2025 and 2026"
SAMPLE_BULLETIN_DATE = "2025-11-25"


def _fetch_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def _fetch_binary(url: str) -> bytes:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def _load_index_html() -> str:
    try:
        html = _fetch_text(INDEX_URL)
        EVIDENCE_INDEX_PATH.write_text(html, encoding="utf-8")
        return html
    except RequestException:
        return EVIDENCE_INDEX_PATH.read_text(encoding="utf-8", errors="replace")


def _parse_index_entries(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    entries: List[Dict[str, str]] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        anchor = tds[0].find("a", href=True)
        if not anchor:
            continue
        title = normalize_text(anchor.get_text(" ", strip=True))
        href = urljoin(INDEX_URL, anchor.get("href", ""))
        date_text = normalize_text(tds[1].get_text(" ", strip=True))
        try:
            publication_date = datetime.strptime(date_text, "%d.%m.%Y").date().isoformat()
        except ValueError:
            continue
        entries.append(
            {
                "title": title,
                "notice_url": href,
                "publication_date": publication_date,
            }
        )
    return entries


def _candidate_entries(entries: List[Dict[str, str]], date_from: str, date_to: str) -> List[Dict[str, str]]:
    candidates = []
    for entry in entries:
        publication_date = entry["publication_date"]
        if publication_date < date_from or publication_date > date_to:
            continue
        if not entry["title"].upper().startswith("NUMBER "):
            continue
        if not entry["notice_url"].lower().endswith(".pdf"):
            continue
        candidates.append(entry)
    return candidates


def _pdf_evidence_path(entry: Dict[str, str]) -> Path:
    safe_title = re.sub(r"[^A-Za-z0-9]+", "_", entry["title"]).strip("_").lower()
    return Path("evidence") / f"nwpg_premier_{safe_title}.pdf"


def _load_pdf(entry: Dict[str, str]) -> bytes:
    evidence_path = _pdf_evidence_path(entry)
    try:
        content = _fetch_binary(entry["notice_url"])
        evidence_path.write_bytes(content)
        return content
    except RequestException:
        return evidence_path.read_bytes()


def _join_column_words(words: List[tuple], dehyphenate: bool = True) -> str:
    if not words:
        return ""
    rows: Dict[int, List[tuple]] = {}
    for word in words:
        key = int(round(word[1] * 2))
        rows.setdefault(key, []).append(word)
    line_texts: List[str] = []
    for key in sorted(rows):
        parts = [w[4] for w in sorted(rows[key], key=lambda item: item[0])]
        line_texts.append(" ".join(parts))
    text = " ".join(line_texts)
    if dehyphenate:
        text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    return normalize_text(text)


def _normalize_amount(value: str) -> str:
    normalized = normalize_text(value)
    if not normalized or normalized.lower().startswith("rates"):
        return ""
    cleaned = normalized.replace("R", "").replace(" ", "")
    if cleaned.lower().startswith("rates"):
        return ""
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return cleaned


def _extract_contract_period(description: str) -> str:
    match = re.search(
        r"period of\s+(.+?)(?:\.|$)",
        description,
        re.I,
    )
    if not match:
        return ""
    period = normalize_text(match.group(1)).rstrip(" .")
    period = period.replace(" Months", " months")
    period = period.replace("(24 Months", "(24 months)")
    period = period.replace(" years (24 months", " years (24 months)")
    return period


def _page_health_award_rows(page: fitz.Page, entry: Dict[str, str]) -> List[Dict[str, str]]:
    page_text = page.get_text("text")
    if HEALTH_AWARDS_HEADING not in page_text:
        return []

    words = sorted(page.get_text("words"), key=lambda item: (item[1], item[0]))
    cancellation_markers = [word[1] for word in words if word[4].upper() == "CANCELLATION" and word[1] > 350]
    section_end_y = min(cancellation_markers) if cancellation_markers else max(word[1] for word in words) + 20
    row_starts = [
        (int(word[4].rstrip(".")), word[1])
        for word in words
        if word[0] < 60 and re.fullmatch(r"\d+\.", word[4]) and 120 < word[1] < section_end_y
    ]
    rows: List[Dict[str, str]] = []
    for index, (row_number, start_y) in enumerate(row_starts):
        end_y = row_starts[index + 1][1] if index + 1 < len(row_starts) else section_end_y
        row_words = [word for word in words if start_y - 1 <= word[1] < end_y]
        ref_words = [word for word in row_words if 70 <= word[0] < 170]
        desc_words = [word for word in row_words if 170 <= word[0] < 340]
        bidder_words = [word for word in row_words if 340 <= word[0] < 480]
        amount_words = [word for word in row_words if word[0] >= 480]

        notice_id = _join_column_words(ref_words, dehyphenate=False).rstrip(":")
        notice_id = re.sub(r"-\s+(\d+:?)$", r"-\1", notice_id)
        notice_id = re.sub(r"(/13/21)-?(\d+)$", r"\1-\2", notice_id)
        description = _join_column_words(desc_words)
        bidder = _join_column_words(bidder_words)
        raw_amount = _join_column_words(amount_words)
        awarded_value = _normalize_amount(raw_amount)
        if not notice_id or not description:
            continue

        row = OutputRow(
            source=CONFIG.source,
            country=CONFIG.country,
            country_cc=CONFIG.country_cc,
            publication_date=entry["publication_date"],
            title=description,
            description=description,
            buyer="North West Department of Health",
            status="awarded",
            currency="ZAR",
            amount=awarded_value,
            awarding_supplier_name=bidder,
            awarded_currency="ZAR" if awarded_value else "",
            awarded_value=awarded_value,
            contract_period=_extract_contract_period(description),
            item_no=str(row_number),
            item_desc=description,
            item_award=raw_amount if raw_amount and not awarded_value else "",
            notice_id=notice_id,
            notice_url=entry["notice_url"],
            query_text=entry["title"],
            scraped_at=utc_now_iso(),
            dedup_key=f"{CONFIG.source}|{entry['publication_date']}|{notice_id}|{normalize_text(bidder).lower()}",
        ).to_dict()
        rows.append(row)
    return rows


def _bulletin_rows(entry: Dict[str, str], content: bytes) -> List[Dict[str, str]]:
    doc = fitz.open(stream=content, filetype="pdf")
    rows: List[Dict[str, str]] = []
    for page in doc:
        rows.extend(_page_health_award_rows(page, entry))
    return rows


def smoke_probe() -> SmokeProbeResult:
    entry = {
        "title": SAMPLE_BULLETIN_TITLE,
        "publication_date": SAMPLE_BULLETIN_DATE,
        "notice_url": "https://premier.nwpg.gov.za/wp-content/uploads/2025/11/NUMBER-34-0F-2025-and-2026.pdf",
    }
    rows = _bulletin_rows(entry, EVIDENCE_SAMPLE_PDF_PATH.read_bytes())
    return SmokeProbeResult(
        source_key=CONFIG.key,
        ok=bool(rows),
        mode="evidence_pdf",
        detail="Parsed North West Premier tender bulletin health term contract awards from saved evidence PDF.",
        sample_rows=rows[:2],
    )


def live_medical_awarded_rows(date_from: str, date_to: str, page_size: int = 50) -> List[Dict[str, str]]:
    del page_size
    entries = _candidate_entries(_parse_index_entries(_load_index_html()), date_from, date_to)
    rows: List[Dict[str, str]] = []
    for entry in entries:
        try:
            rows.extend(_bulletin_rows(entry, _load_pdf(entry)))
        except (RequestException, FileNotFoundError):
            continue
    return rows
