#!/usr/bin/env python3
"""
G2B (나라장터) completed tender scraper.

Flow:
  1. Open https://www.g2b.go.kr/
  2. Dismiss notice / warning popups
  3. Navigate 입찰 → 입찰공고목록 using robust hover/submenu logic
  4. Set 게시일 date range from command-line args
  5. Fill 공고명 with query text
  6. Click 검색
  7. Scroll results and process only rows containing 진행완료
  8. Click 진행완료 in the same row to open detail page
  9. Extract tender fields into the requested CSV schema

Example:
  python g2b_production_scraper.py --start-date 2024/01/01 --end-date 2024/12/31 --query-text 의학 --output g2b_results.csv --headed
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

warnings.filterwarnings('ignore', category=Warning, module='requests')

from playwright.sync_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
HOME_URLS = [
    "https://www.g2b.go.kr/",
    "https://www.g2b.go.kr/index.jsp",
]
MAX_HOME_ATTEMPTS = 4
BASE_BACKOFF_MS = 3_000

NOTICE_ID_PATTERN = re.compile(r"R\d{2}[A-Z]{2}[A-Z0-9]+")
ITEM_TABLE_HEADER_PATTERN = re.compile(
    r"품명|세부품명|물품|수량|단위|규격|모델|납품|품목|목록", re.I
)
RUN_LOG_PATH: Path | None = None

OUTPUT_COLUMNS = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "closing_date",
    "title",
    "title_en",
    "buyer",
    "buyer_en",
    "classification",
    "classification_en",
    "status",
    "status_en",
    "currency",
    "amount",
    "awarding_agency_name",
    "awarding_agency_name_en",
    "supplier_name",
    "supplier_name_en",
    "awarded_date",
    "awarded_value_detail",
    "contract_period",
    "item_no",
    "item_description",
    "item_description_en",
    "item_uom",
    "item_quantity",
    "item_unit_price",
    "item_awarded_value",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]


# ──────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────
@dataclass
class TenderRow:
    title: str
    row_text: str
    href: str


@dataclass
class TenderDetail:
    source: str
    country: str
    country_code: str
    publication_date: str
    closing_date: str
    title: str
    title_en: str
    buyer: str
    buyer_en: str
    classification: str
    classification_en: str
    status: str
    status_en: str
    currency: str
    amount: str
    awarding_agency_name: str
    awarding_agency_name_en: str
    supplier_name: str
    supplier_name_en: str
    awarded_date: str
    awarded_value_detail: str
    contract_period: str
    item_no: str
    item_description: str
    item_description_en: str
    item_uom: str
    item_quantity: str
    item_unit_price: str
    item_awarded_value: str
    notice_id: str
    notice_url: str
    query_text: str
    scraped_at_utc: str
    dedup_key: str



# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="G2B completed tender scraper")
    parser.add_argument("--output", default="g2b_results.csv")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--slow-mo", type=int, default=0)
    parser.add_argument("--timeout-ms", type=int, default=90_000)
    parser.add_argument("--row-limit", type=int, default=None, help="Optional max number of tender rows to process; omit to scrape all available rows")
    parser.add_argument("--max-scrolls", type=int, default=120)
    parser.add_argument(
        "--stagnant-scroll-limit",
        type=int,
        default=8,
        help="Stop after this many scroll rounds with no new 진행완료 rows",
    )
    parser.add_argument("--start-date", default="2024/01/01", help="게시일 start date, format YYYY/MM/DD")
    parser.add_argument("--end-date", default="2024/12/31", help="게시일 end date, format YYYY/MM/DD")
    parser.add_argument("--query-text", default="", help="Optional 공고명 text; default empty because 업종 filter is used")
    parser.add_argument("--industry-code", default="5309", help="업종코드 to select in 상세조건 popup")
    parser.add_argument("--industry-name", default="의료기기제조업", help="Expected 업종명 for debug/logging")
    parser.add_argument("--translate-en", action="store_true", help="Try to populate *_en columns using deep-translator if installed; otherwise use simple dictionary fallback")
    parser.add_argument("--debug", action="store_true", help="Print detailed click/extraction debug logs")
    parser.add_argument("--debug-dir", default="g2b_debug", help="Folder for debug screenshots when failures occur")
    parser.add_argument("--fast", action="store_true", help="Use shorter waits for navigation/filtering")
    parser.add_argument("--scroll-only", action="store_true", help="After applying filters and searching, test only result-grid scrolling without opening detail rows")
    parser.add_argument("--state-file", default="", help="Optional JSON progress file path; default is based on --output")
    parser.add_argument("--log-file", default="", help="Optional log file path; default is based on --output")
    parser.add_argument("--fresh-start", action="store_true", help="Ignore any saved progress and start a brand-new run")
    return parser.parse_args()


# ──────────────────────────────────────────────
# Basic helpers
# ──────────────────────────────────────────────
def log(message: str) -> None:
    line = f"[G2B] {message}"
    print(line, flush=True)
    if RUN_LOG_PATH is not None:
        try:
            RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with RUN_LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(f"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} {line}\n")
        except Exception:
            pass


def debug_log(args: argparse.Namespace, message: str) -> None:
    if getattr(args, "debug", False):
        line = f"[G2B][DEBUG] {message}"
        print(line, flush=True)
        if RUN_LOG_PATH is not None:
            try:
                RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with RUN_LOG_PATH.open("a", encoding="utf-8") as fp:
                    fp.write(f"{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')} {line}\n")
            except Exception:
                pass


def save_debug_screenshot(page: Page, args: argparse.Namespace, name: str) -> None:
    if not getattr(args, "debug", False):
        return
    try:
        from pathlib import Path
        debug_dir = Path(getattr(args, "debug_dir", "g2b_debug"))
        debug_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:120]
        out = debug_dir / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe}.png"
        page.screenshot(path=str(out), full_page=True)
        debug_log(args, f"Saved screenshot: {out}")
    except Exception as exc:
        debug_log(args, f"Could not save screenshot {name}: {exc}")



def pause(page: Page, args: argparse.Namespace | None, normal_ms: int, fast_ms: int) -> None:
    """Use shorter waits when --fast is enabled."""
    page.wait_for_timeout(fast_ms if args is not None and getattr(args, "fast", False) else normal_ms)


def utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def first_match(patterns: Iterable[str], text: str, default: str = "") -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return compact(match.group(1))
    return default


def write_csv(path: str, rows: Iterable[dict]) -> None:
    rows = list(rows)
    with open(path, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_csv_rows(path: str, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = out_path.exists() and out_path.stat().st_size > 0
    with out_path.open("a", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def count_csv_rows(path: str) -> int:
    out_path = Path(path)
    if not out_path.exists() or out_path.stat().st_size == 0:
        return 0
    with out_path.open("r", newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        return sum(1 for _ in reader)


def default_state_file(output_path: str) -> str:
    out = Path(output_path)
    return str(out.with_name(f"{out.stem}_progress.json"))


def default_log_file(output_path: str) -> str:
    out = Path(output_path)
    return str(out.with_name(f"{out.stem}.log"))


def load_json_file(path: str) -> dict:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def last_detail_index_from_log(path: str) -> int:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return 0
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    matches = re.findall(r"→\s*Detail\s+(\d+)", text)
    if not matches:
        return 0
    try:
        return int(matches[-1])
    except Exception:
        return 0


def last_notice_id_from_log(path: str) -> str:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    patterns = [
        r'"noticeNo"\s*:\s*"(\d{11}-\d{3})"',
        r'"notice_id"\s*:\s*"(\d{11}-\d{3})"',
        r"\b(\d{11}-\d{3})\b",
        r'"noticeNo"\s*:\s*"([A-Z][A-Z0-9-]{7,})"',
        r'"notice_id"\s*:\s*"([A-Z][A-Z0-9-]{7,})"',
        r"\b([A-Z][A-Z0-9-]{7,})\b",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            return matches[-1]
    return ""


def save_progress_state(args: argparse.Namespace, status: str, seen_keys: set[str], last_notice_id: str = "", last_row_title: str = "") -> None:
    state_path = Path(args.state_file)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "status": status,
        "output": str(Path(args.output).resolve()),
        "processed_row_keys": sorted(seen_keys),
        "processed_row_count": len(seen_keys),
        "records_written": getattr(args, "_records_written", 0),
        "last_notice_id": last_notice_id,
        "last_row_title": last_row_title,
        "updated_at_utc": utc_now(),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "query_text": args.query_text,
        "industry_code": args.industry_code,
    }
    if not getattr(args, "_started_at_utc", ""):
        args._started_at_utc = utc_now()
    state["started_at_utc"] = args._started_at_utc
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def initialize_progress(args: argparse.Namespace) -> None:
    global RUN_LOG_PATH
    args.output = str(Path(args.output).resolve())
    args.state_file = args.state_file or default_state_file(args.output)
    args.log_file = args.log_file or default_log_file(args.output)
    RUN_LOG_PATH = Path(args.log_file)
    args._resume_skip_count = 0
    args._resume_target_notice_id = ""

    existing_state = {} if args.fresh_start else load_json_file(args.state_file)
    has_saved_rows = bool(existing_state.get("processed_row_keys", []) or [])
    can_resume = (
        bool(existing_state)
        and (
            existing_state.get("status") in {"running", "interrupted", "failed"}
            or has_saved_rows
        )
        and existing_state.get("output") == args.output
        and Path(args.output).exists()
    )

    if can_resume:
        args._resume_seen = set(existing_state.get("processed_row_keys", []) or [])
        args._records_written = int(existing_state.get("records_written", 0) or 0)
        args._started_at_utc = existing_state.get("started_at_utc") or utc_now()

        log_detail_index = last_detail_index_from_log(args.log_file)
        if not args._resume_seen and args._records_written <= 0 and log_detail_index > 0:
            # A previous failed resume may have written a tiny partial seen-set
            # before any real output rows were saved. In that case, trust the
            # logged resume row instead of the weak JSON seen-state.
            args._resume_seen = set()
        args._resume_target_notice_id = ""
        if log_detail_index > 0 and not args._resume_seen:
            args._resume_skip_count = max(0, log_detail_index - 1)
        else:
            args._resume_skip_count = 0

        resume_row_display = (
            len(args._resume_seen) + 1
            if args._resume_seen
            else (
                log_detail_index
                if log_detail_index > 0
                else (args._resume_skip_count + 1 if args._resume_skip_count else 1)
            )
        )
        resume_source = "json" if args._resume_seen else "log"
        log(
            f"Resuming previous run: processed_rows={len(args._resume_seen)}, "
            f"records_written={args._records_written}, resume_row={resume_row_display}, resume_source={resume_source}"
        )
        save_progress_state(args, "running", args._resume_seen, existing_state.get("last_notice_id", ""), existing_state.get("last_row_title", ""))
        return

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, [])
    args._resume_seen = set()
    args._records_written = 0
    args._started_at_utc = utc_now()
    args._resume_skip_count = 0
    args._resume_target_notice_id = ""
    save_progress_state(args, "running", set())
    log("Started fresh run with empty output/state files.")


def make_dedup_key(notice_id: str, title: str, item_no: str = "") -> str:
    raw = "|".join([notice_id or "", compact(title or ""), item_no or ""])
    return re.sub(r"[^A-Za-z0-9가-힣|_-]+", "_", raw).strip("_")[:500]


def normalize_notice_id(value: str) -> str:
    value = compact(value or "")
    if not value:
        return ""

    numeric = re.search(r"\b(\d{11})\s*-\s*(\d{3})\b", value)
    if numeric:
        return f"{numeric.group(1)}-{numeric.group(2)}"

    # Newer result sets use alphanumeric notice ids such as R25BK012552...
    # Keep only tokens that contain both letters and digits to avoid matching plain words.
    for token in re.findall(r"\b[A-Z0-9-]{8,}\b", value, flags=re.I):
        token_clean = token.strip("-").upper()
        if not token_clean:
            continue
        if not re.search(r"[A-Z]", token_clean):
            continue
        if not re.search(r"\d", token_clean):
            continue
        return token_clean

    return ""


def listing_dates(row_text: str) -> tuple[str, str]:
    dates = re.findall(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}(?::\d{2})?", row_text or "")
    pub = dates[0] if dates else ""
    close = dates[1] if len(dates) > 1 else ""
    return pub, close


def listing_classification(row_text: str) -> str:
    for token in ["물품", "일반용역", "기술용역", "공사", "외자", "내자"]:
        if token in (row_text or ""):
            return token
    return ""


def listing_buyer(row_text: str, title: str) -> str:
    """
    Best-effort buyer extraction from result row text:
    notice_id title 공고기관 수요기관 dates...
    When 공고기관 and 수요기관 are same, the text often repeats the same agency twice.
    """
    notice_id = normalize_notice_id(row_text)
    if not notice_id or not title or title not in row_text:
        return ""

    tail = row_text.split(title, 1)[1]
    first_date = re.search(r"\d{4}/\d{2}/\d{2}", tail)
    if first_date:
        org_text = compact(tail[:first_date.start()])
    else:
        org_text = compact(tail)

    if not org_text:
        return ""

    # If repeated exactly twice, use one half.
    half = len(org_text) // 2
    if len(org_text) > 4 and org_text[:half].strip() == org_text[half:].strip():
        return org_text[:half].strip()

    # Common case: agency repeated as two identical Korean organization names.
    parts = org_text.split()
    if len(parts) >= 2 and len(parts) % 2 == 0:
        left = " ".join(parts[: len(parts)//2])
        right = " ".join(parts[len(parts)//2 :])
        if left == right:
            return left

    return org_text


def detail_label_value(text: str, label: str, stop_labels: Iterable[str]) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    stop = "|".join(map(re.escape, stop_labels))
    pattern = rf"{re.escape(label)}\s*[:：]?\s*(.*?)(?=\s+(?:{stop})\s*[:：]?|$)"
    match = re.search(pattern, clean, re.I)
    if not match:
        return ""
    value = compact(match.group(1))
    # Remove Grid artifacts.
    value = re.sub(r"\bGrid start\b.*", "", value).strip()
    return value[:1000]


DETAIL_STOP_LABELS = [
    "공고일반", "공고종류", "게시일시", "입찰공고번호", "참조번호", "공고명",
    "입찰방식", "낙찰방법", "낙찰하한율", "계약방법", "계약구분", "국제입찰구분",
    "채권자명", "공동수급협정서", "국내/국제입찰사유", "재입찰여부", "동가입찰",
    "낙찰자", "자동추첨프로그램", "연구개발물품여부", "입찰자격", "제조여부",
    "투찰제한", "지역제한", "업종제한", "물품분류제한여부", "물품등록구분",
    "입찰진행정보", "가격", "예가방법", "사업금액", "배정예산", "추정가격",
    "기초금액공개", "기관담당자정보", "공고기관", "공고담당자", "집행관",
    "수요기관담당자정보", "수요기관", "연관정보", "구매대상물품",
    "입찰진행현황", "파일첨부", "목록",
]


def detail_value(text: str, labels: Iterable[str]) -> str:
    for label in labels:
        val = detail_label_value(text, label, DETAIL_STOP_LABELS)
        if val:
            return val
    return ""


def extract_description(detail_text: str) -> str:
    """
    Keep description useful and short, not the entire page/nav/footer.
    Prefer the 공고일반-to-입찰자격 section.
    """
    clean = compact(detail_text)
    start = clean.find("공고일반")
    if start == -1:
        start = clean.find("입찰공고상세")
    end_candidates = [clean.find(x, start) for x in ["입찰진행정보", "가격", "구매대상물품"] if clean.find(x, start) != -1]
    end = min(end_candidates) if end_candidates else min(len(clean), start + 2500)
    if start != -1:
        return clean[start:end][:2500]
    return clean[:2500]


BASIC_KO_EN = {
    "진행완료": "Completed",
    "물품": "Goods",
    "내자": "Domestic procurement",
    "일반용역": "General services",
    "기술용역": "Technical services",
    "공사": "Construction",
    "긴급공고": "Urgent notice",
    "등록공고": "Registered notice",
    "변경공고": "Amended notice",
    "재공고": "Re-announcement",
    "입찰": "Bid",
    "공고": "Notice",
    "구매": "Purchase",
    "용역": "Service",
    "진료재료": "Medical treatment materials",
    "진단검사의학": "Laboratory medicine",
    "검사시약": "test reagents",
    "검체검사": "specimen testing",
    "병리검사": "pathology testing",
    "위탁": "outsourcing",
    "자기공명영상장치": "MRI system",
    "의료원": "Medical Center",
    "병원": "Hospital",
    "원자력의학원": "Radiological and Medical Sciences Institute",
    "충청남도": "Chungcheongnam-do",
    "대구": "Daegu",
    "서울": "Seoul",
    "한국": "Korea",
}


def simple_translate_ko_to_en(text: str) -> str:
    value = compact(text)
    if not value:
        return ""

    # Dictionary phrase replacement. This is intentionally conservative.
    out = value
    for ko, en in sorted(BASIC_KO_EN.items(), key=lambda kv: len(kv[0]), reverse=True):
        out = out.replace(ko, en)

    return out


_TRANSLATOR = None
_TRANSLATOR_READY = False


def translate_to_en(text: str, enabled: bool = False) -> str:
    """
    If --translate-en is used and deep-translator is installed, use GoogleTranslator.
    Otherwise use a lightweight dictionary fallback so *_en columns are still populated.
    """
    global _TRANSLATOR, _TRANSLATOR_READY

    value = compact(text)
    if not value:
        return ""

    if enabled:
        try:
            if not _TRANSLATOR_READY:
                from deep_translator import GoogleTranslator  # type: ignore
                _TRANSLATOR = GoogleTranslator(source="ko", target="en")
                _TRANSLATOR_READY = True

            if _TRANSLATOR is not None:
                return compact(_TRANSLATOR.translate(value[:4500]))
        except Exception:
            # Fall through to dictionary fallback.
            pass

    return simple_translate_ko_to_en(value)


def extract_item_rows_from_tables(tables: list[dict]) -> list[dict]:
    """
    Extract only genuine item/product rows.
    Avoid unrelated tables such as eligible 업종, bid process, files, etc.
    """
    item_rows: list[dict] = []

    for table in tables or []:
        headers = [compact(h) for h in table.get("headers", [])]
        rows = table.get("rows", []) or []
        table_text = json.dumps(rows, ensure_ascii=False)

        header_text = " ".join(headers)
        is_item_table = (
            ("구매대상물품" in table_text or "구매대상물품" in header_text) or
            ("세부품명" in header_text or "물품식별번호" in header_text or "납품장소" in header_text)
        ) and (
            "수량" in header_text or "단위" in header_text or "세부품명번호" in header_text
        )

        if not is_item_table:
            continue

        # If headers are empty or too short, try the first row as headers.
        data_rows = rows
        local_headers = headers
        if (not local_headers or len(local_headers) < 3) and rows:
            maybe_header = [compact(c) for c in rows[0]]
            if any(h in " ".join(maybe_header) for h in ["세부품명", "수량", "단위", "규격"]):
                local_headers = maybe_header
                data_rows = rows[1:]

        for idx, cells in enumerate(data_rows, start=1):
            cells = [compact(c) for c in cells]
            joined = " ".join(cells)

            if not joined:
                continue
            if any(x in joined for x in ["Grid start", "Grid end", "전체선택"]):
                continue
            if re.search(r"세부품명|수량|단위|규격|납품장소", joined) and len(cells) <= 12:
                # header-like row
                continue

            mapped = {}
            if local_headers and len(local_headers) == len(cells):
                mapped = {local_headers[i]: cells[i] for i in range(len(cells))}

            def by_header(*names: str) -> str:
                for name in names:
                    for key, val in mapped.items():
                        if name in key and val:
                            return val
                return ""

            item_no = by_header("No", "순번", "번호") or (cells[0] if cells else str(idx))
            item_desc = by_header("세부품명", "품명", "규격") or ""
            if not item_desc:
                # Heuristic: prefer a Korean text cell not numeric and not an agency.
                for c in cells:
                    if c and not re.fullmatch(r"[\d,./:-]+", c) and c not in ["-", "종", "개", "식"]:
                        if "기관" not in c and "의료원" not in c:
                            item_desc = c
                            break

            item_rows.append({
                "item_no": item_no,
                "item_description": item_desc,
                "item_uom": by_header("단위", "Units", "Unit"),
                "item_quantity": by_header("수량", "Quantity"),
                "item_unit_price": by_header("추정단가", "예정단가", "Estimated", "단가"),
                "item_awarded_value": by_header("금액", "낙찰금액", "계약금액"),
            })

    # Dedupe
    deduped = []
    seen = set()
    for item in item_rows:
        key = (item.get("item_no", ""), item.get("item_description", ""), item.get("item_quantity", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def table_key_values(tables: list[dict]) -> dict[str, str]:
    """
    Extract structured label/value pairs from visible detail tables.
    G2B detail pages usually use rows like:
      [label, value, label, value]
      [label, value]
    This avoids greedy parsing from whole page text.
    """
    kv: dict[str, str] = {}

    def add_pair(label: str, value: str) -> None:
        label = compact(label).replace(" ", "")
        value = compact(value)
        if not label or not value:
            return
        if len(label) > 40:
            return
        if label in {"No", "순번", "진행상태", "진행절차", "시작일시", "종료일시"}:
            return
        # Keep first meaningful value.
        if label not in kv or not kv[label]:
            kv[label] = value

    for table in tables or []:
        for row in table.get("rows", []) or []:
            cells = [compact(c) for c in row if compact(c)]
            if len(cells) < 2:
                continue

            # rows can be [label, value, label, value]
            if len(cells) >= 4:
                add_pair(cells[0], cells[1])
                add_pair(cells[2], cells[3])
            else:
                add_pair(cells[0], cells[1])

    return kv


def kv_get(kv: dict[str, str], *labels: str) -> str:
    for label in labels:
        key = label.replace(" ", "")
        if key in kv and kv[key]:
            return kv[key]
    # fallback contains match
    for label in labels:
        key = label.replace(" ", "")
        for k, v in kv.items():
            if key in k and v:
                return v
    return ""


def clean_bad_value(value: str, bad_tokens: Iterable[str]) -> str:
    value = compact(value)
    if not value:
        return ""
    if any(token in value for token in bad_tokens):
        return ""
    return value


def extract_money(text: str) -> tuple[str, str]:
    clean = compact(text)
    patterns = [
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(원|KRW|₩)",
        r"(원|KRW|₩)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if not match:
            continue
        a, b = match.group(1), match.group(2)
        if re.search(r"\d", a):
            return ("KRW" if b in ["원", "₩"] else b.upper(), a)
        return ("KRW" if a in ["원", "₩"] else a.upper(), b)
    return "", ""


def pick_labeled_value(text: str, labels: Iterable[str]) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ""

    stop_labels = [
        "공고명", "입찰공고명", "건명", "공고번호", "입찰공고번호", "공고관리번호",
        "공고기관", "수요기관", "게시일자", "공고일자", "입력일시",
        "입찰마감일시", "마감일시", "개찰일시", "투찰마감일시",
        "추정가격", "배정예산", "기초금액", "예정가격", "계약방법",
        "업무구분", "입찰방식", "공고종류", "업종", "낙찰자",
        "계약상대자", "업체명", "공급업체", "낙찰일자", "계약일자",
        "선정일자", "낙찰금액", "계약금액", "낙찰가", "계약기간",
        "납품기한", "이행기간", "품명", "세부품명", "수량", "단위",
    ]
    stop = "|".join(map(re.escape, stop_labels))

    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]?\s*(.*?)(?=\s+(?:{stop})\s*[:：]?|$)"
        match = re.search(pattern, clean, re.I)
        if match:
            value = compact(match.group(1))
            if value and value != label:
                return value[:1000]
    return ""


# ──────────────────────────────────────────────
# Popup handling
# ──────────────────────────────────────────────
_CLOSE_ONE_POPUP_JS = r"""
() => {
  const isVis = el => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' &&
           s.visibility !== 'hidden' &&
           r.width > 0 &&
           r.height > 0;
  };

  const norm = v => (v || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

  const popups = Array.from(document.querySelectorAll('div, section, article'))
    .filter(el => {
      if (!isVis(el)) return false;
      const r = el.getBoundingClientRect();
      const txt = norm(el.innerText || '');
      const meta = `${el.id || ''} ${el.className || ''}`;
      return r.width >= 280 &&
             r.height >= 140 &&
             r.width <= window.innerWidth * 0.92 &&
             r.height <= window.innerHeight * 0.95 &&
             r.x <= window.innerWidth * 0.4 &&
             r.y <= Math.max(420, window.innerHeight * 0.55) &&
             (
               /popup|layer|dialog|modal|notice|alert/i.test(meta) ||
               /공지|안내|사기|피해|알림|유의|DDoS|DDos|보안|서비스/.test(txt)
             );
    })
    .sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.y - br.y || (br.width * br.height) - (ar.width * ar.height);
    });

  if (!popups.length) return false;

  const popup = popups[0];
  const pr = popup.getBoundingClientRect();

  const candidates = Array.from(
    popup.querySelectorAll('button,a,input[type=button],input[type=image],img,span')
  ).filter(el => {
    if (!isVis(el) || el === popup) return false;
    const r = el.getBoundingClientRect();
    const txt = norm(el.innerText || el.value || el.title || '');
    const meta = `${el.id || ''} ${el.className || ''} ${el.title || ''}`;
    const href = norm(el.getAttribute('href') || '');

    if (
      /twitter|x\.com|t\.co|facebook|instagram|youtube|blog|cafe|naver\.me/i.test(href + ' ' + meta + ' ' + txt) ||
      (/^https?:/i.test(href) && !/g2b\.go\.kr/i.test(href))
    ) {
      return false;
    }

    const topRight =
      r.x >= pr.right - 120 &&
      r.x <= pr.right + 10 &&
      r.y >= pr.y - 10 &&
      r.y <= pr.y + 110 &&
      r.width <= 80 &&
      r.height <= 80;

    const closeText =
      txt === '닫기' ||
      txt === '오늘 하루 이 창을 열지 않음' ||
      txt === '일주일간 이 창을 열지 않음' ||
      txt === '×' ||
      txt === 'X' ||
      txt === '✕' ||
      /닫기|close|today|week/i.test(txt + ' ' + meta);

    const topRightClose =
      topRight &&
      (
        txt === '' ||
        txt === '×' ||
        txt === 'X' ||
        txt === '✕' ||
        /close|btn.*close|popup.*close|layer.*close|dialog.*close|notice.*close/i.test(meta)
      );

    const dismissButton =
      closeText &&
      r.x >= pr.x - 10 &&
      r.x <= pr.right + 10 &&
      r.y >= pr.y - 10 &&
      r.y <= pr.bottom + 10 &&
      r.width <= 280 &&
      r.height <= 100;

    return topRightClose || dismissButton;
  });

  if (!candidates.length) return false;

  candidates.sort((a, b) => {
    const ar = a.getBoundingClientRect();
    const br = b.getBoundingClientRect();
    return br.x - ar.x || ar.y - br.y;
  })[0].click();

  return true;
}
"""

_HAS_NOTICE_POPUP_JS = r"""
() => {
  const isVis = el => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const norm = v => (v || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

  return Array.from(document.querySelectorAll('div, section, article')).some(el => {
    if (!isVis(el)) return false;
    const r = el.getBoundingClientRect();
    const txt = norm(el.innerText || '');
    const meta = `${el.id || ''} ${el.className || ''}`;
    return r.width >= 280 &&
           r.height >= 140 &&
           r.y <= Math.max(420, window.innerHeight * 0.55) &&
           (
             /popup|layer|dialog|modal|notice|alert/i.test(meta) ||
             /공지|안내|사기|피해|알림|유의|DDoS|DDos|보안|서비스/.test(txt)
           );
  });
}
"""

_CLOSE_CODE0_WARNING_JS = r"""
() => {
  const isVis = el => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const norm = v => (v || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

  const dialogs = Array.from(document.querySelectorAll('div, section, article'))
    .filter(el => {
      if (!isVis(el)) return false;
      const txt = norm(el.innerText || '');
      const r = el.getBoundingClientRect();
      return r.width >= 240 &&
             r.height >= 120 &&
             r.width <= window.innerWidth * 0.95 &&
             r.height <= window.innerHeight * 0.95 &&
             (
               /code\s*:\s*0/i.test(txt) ||
               /서버\s*오류/.test(txt) ||
               /서버를\s*확인/i.test(txt) ||
               /관리자에게\s*문의/i.test(txt)
             );
    })
    .sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return (br.width * br.height) - (ar.width * ar.height);
    });

  if (!dialogs.length) return false;
  const popup = dialogs[0];
  const pr = popup.getBoundingClientRect();

  const xCandidates = Array.from(popup.querySelectorAll('button,a,input[type=button],input[type=image],img,span,div'))
    .filter(el => {
      if (!isVis(el) || el === popup) return false;
      const r = el.getBoundingClientRect();
      const txt = norm(el.innerText || el.value || el.title || el.getAttribute('aria-label') || '');
      const meta = `${el.id || ''} ${el.className || ''} ${el.title || ''} ${el.getAttribute('aria-label') || ''}`;
      const topRight =
        r.x >= pr.right - 120 &&
        r.x <= pr.right + 10 &&
        r.y >= pr.y - 10 &&
        r.y <= pr.y + 100 &&
        r.width <= 90 &&
        r.height <= 90;
      return topRight && (
        txt === '' ||
        txt === '×' ||
        txt === 'X' ||
        txt === '✕' ||
        /close|btn.*close|popup.*close|layer.*close|dialog.*close|modal.*close/i.test(meta)
      );
    })
    .sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return br.x - ar.x || ar.y - br.y;
    });

  const fireClick = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const opts = { bubbles: true, cancelable: true, composed: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
    el.dispatchEvent(new MouseEvent('mouseover', opts));
    el.dispatchEvent(new MouseEvent('mousedown', opts));
    el.dispatchEvent(new MouseEvent('mouseup', opts));
    el.dispatchEvent(new MouseEvent('click', opts));
    if (typeof el.click === 'function') el.click();
    return true;
  };

  if (xCandidates.length) {
    return fireClick(xCandidates[0]);
  }

  const okCandidates = Array.from(popup.querySelectorAll('button,a,input[type=button],span,div'))
    .filter(el => isVis(el) && /^(확인|닫기)$/i.test(norm(el.innerText || el.value || '')))
    .sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.y - br.y || br.x - ar.x;
    });

  if (okCandidates.length) {
    return fireClick(okCandidates[0]);
  }

  return false;
}
"""


def dismiss_code0_warning(page: Page, pause_ms: int = 1200) -> bool:
    clicked = bool(page.evaluate(_CLOSE_CODE0_WARNING_JS))
    if clicked:
        log("Dismissed code:0/server warning via X/close control")
        page.wait_for_timeout(pause_ms)
    return clicked


def dismiss_transient_warning_pass(page: Page, rounds: int = 2, pause_ms: int = 900) -> int:
    """
    Light-touch warning dismissal used after click actions once filters are active.
    Tries only the code:0/server modal close path, preferring the X button.
    """
    closed = 0
    for _ in range(max(1, rounds)):
        try:
            if dismiss_code0_warning(page, pause_ms=pause_ms):
                closed += 1
                continue
        except Exception:
            break
        break
    return closed


def dismiss_all_popups(page: Page, max_rounds: int = 20, pause_ms: int = 1_400) -> int:
    closed = 0
    stagnant = 0

    for _ in range(max_rounds):
        if dismiss_code0_warning(page, pause_ms=max(900, pause_ms)):
            closed += 1
            stagnant = 0
            continue

        clicked = bool(page.evaluate(_CLOSE_ONE_POPUP_JS))
        if clicked:
            closed += 1
            stagnant = 0
            log(f"Dismissed popup #{closed}")
            page.wait_for_timeout(pause_ms)
            continue

        has_more = bool(page.evaluate(_HAS_NOTICE_POPUP_JS))
        stagnant += 1
        if not has_more and stagnant >= 3:
            break
        page.wait_for_timeout(1200 if has_more else 500)

    log(f"Total popups dismissed: {closed}")
    return closed


def dismiss_all_popups_until_clear(page: Page) -> int:
    total = 0
    for _ in range(3):
        total += dismiss_all_popups(page, max_rounds=12, pause_ms=1600)
        page.wait_for_timeout(1200)
        if not page.evaluate(_HAS_NOTICE_POPUP_JS):
            break
    log(f"Popup drain pass finished: {total} total dismissals")
    return total


# ──────────────────────────────────────────────
# Page readiness and state
# ──────────────────────────────────────────────
_PORTAL_READY_JS = r"""
() => {
  const txt = (document.body && document.body.innerText || '').trim();
  const hasUI =
    txt.includes('입찰') ||
    txt.includes('나라장터') ||
    txt.includes('공고명') ||
    txt.includes('검색');
  const noLoader = !document.querySelector('#___processbar2');
  return hasUI && noLoader;
}
"""


def wait_ready(page: Page, timeout_ms: int = 60_000) -> None:
    try:
        page.wait_for_function(_PORTAL_READY_JS, timeout=timeout_ms)
    except Exception:
        pass



def wait_for_loading_clear(page: Page, timeout_ms: int = 60_000) -> None:
    """
    Wait until G2B/WebSquare loading overlays disappear.
    This prevents clicks while the gray modal/loading spinner blocks the grid.
    """
    try:
        page.wait_for_function("""
        () => {
          const txt = (document.body?.innerText || '').replace(/\\u00a0/g, ' ');
          const hasLoadingText = /Loading|로딩|처리중|조회중/.test(txt);

          const visibleOverlay = Array.from(document.querySelectorAll('div, span'))
            .some(el => {
              const s = getComputedStyle(el);
              const r = el.getBoundingClientRect();
              if (s.display === 'none' || s.visibility === 'hidden' || r.width <= 0 || r.height <= 0) return false;

              const t = (el.innerText || '').trim();
              const cls = String(el.className || '');
              const id = String(el.id || '');

              const looksLikeLoading =
                /loading|process|progress|spinner|w2modal|w2popup/i.test(cls + ' ' + id) ||
                /Loading|로딩|처리중|조회중/.test(t);

              const coversScreen =
                r.width > window.innerWidth * 0.35 &&
                r.height > window.innerHeight * 0.25;

              return looksLikeLoading && coversScreen;
            });

          return !visibleOverlay && !hasLoadingText;
        }
        """, timeout=timeout_ms)
    except Exception:
        # Do not hard fail; just give the page a small extra settle time.
        page.wait_for_timeout(1500)

def is_bid_list_open(page: Page) -> bool:
    return bool(page.evaluate("""
    () => {
      const txt = (document.body?.innerText || '').replace(/\u00a0/g,' ');

      const pageTitleOk = txt.includes('입찰공고목록');

      const searchPanelOk =
        txt.includes('검색유형') &&
        txt.includes('입찰공고') &&
        txt.includes('개찰결과') &&
        txt.includes('최종낙찰자') &&
        txt.includes('공고명') &&
        (txt.includes('게시일자') || txt.includes('공고/개찰일자')) &&
        txt.includes('검색');

      const resultGridOk =
        txt.includes('입찰공고번호') &&
        txt.includes('공고기관') &&
        txt.includes('수요기관') &&
        txt.includes('입찰진행');

      return pageTitleOk && (searchPanelOk || resultGridOk);
    }
    """))


# ──────────────────────────────────────────────
# JS click helpers
# ──────────────────────────────────────────────
def _js_click_id(page: Page, element_id: str) -> bool:
    return bool(page.evaluate(
        "(id) => { const el = document.getElementById(id); if (!el) return false; el.click(); return true; }",
        element_id,
    ))


def _js_click_text(page: Page, text: str, y_limit: int = 9999) -> bool:
    return bool(page.evaluate("""
    ([text, yLimit]) => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };
      const norm = v => (v || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

      const nodes = Array.from(document.querySelectorAll('button,a,label,input,span,div,li'))
        .filter(el => {
          if (!isVis(el)) return false;
          const r = el.getBoundingClientRect();
          return r.y <= yLimit && norm(el.innerText || el.value || '') === text;
        })
        .sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);

      if (!nodes.length) return false;
      nodes[0].click();
      return true;
    }
    """, [text, y_limit]))


def _js_click_gnb(page: Page, text: str) -> bool:
    return bool(page.evaluate("""
    (targetText) => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };
      const norm = v => (v || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

      const selectors = [
        'nav', 'header nav', '[role=navigation]',
        '[class*=gnb]', '[id*=gnb]', '[class*=GNB]', '[id*=GNB]',
        '[class*=topMenu]', '[class*=top_menu]', '[class*=mainMenu]',
        '[class*=lnb]', '[class*=navMenu]', '[class*=nav-menu]'
      ];

      let gnb = null;
      for (const sel of selectors) {
        const hits = Array.from(document.querySelectorAll(sel)).filter(el => {
          if (!isVis(el)) return false;
          const r = el.getBoundingClientRect();
          return r.width >= window.innerWidth * 0.35 && r.height <= 130 && r.y <= 220;
        });
        if (hits.length) { gnb = hits[0]; break; }
      }

      if (gnb) {
        const hit = Array.from(gnb.querySelectorAll('a,button,span,li,div'))
          .filter(el => isVis(el) && norm(el.innerText || el.value || '') === targetText)
          .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x)[0];
        if (hit) { hit.click(); return true; }
      }

      const hit = Array.from(document.querySelectorAll('a,button,span,div,li'))
        .filter(el => {
          if (!isVis(el)) return false;
          const r = el.getBoundingClientRect();
          return r.y <= 160 && norm(el.innerText || el.value || '') === targetText;
        })
        .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x)[0];

      if (hit) { hit.click(); return true; }
      return false;
    }
    """, text))


def _js_hover_gnb(page: Page, text: str) -> bool:
    return bool(page.evaluate("""
    (targetText) => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };
      const norm = v => (v || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();

      const fireHover = el => {
        const opts = { bubbles: true, cancelable: true, view: window };
        el.dispatchEvent(new MouseEvent('mouseover', opts));
        el.dispatchEvent(new MouseEvent('mouseenter', opts));
        el.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, cancelable: true, pointerType: 'mouse' }));
        el.dispatchEvent(new PointerEvent('pointerenter', { bubbles: true, cancelable: true, pointerType: 'mouse' }));
        return true;
      };

      const selectors = [
        'nav', 'header nav', '[role=navigation]',
        '[class*=gnb]', '[id*=gnb]', '[class*=GNB]', '[id*=GNB]',
        '[class*=topMenu]', '[class*=top_menu]', '[class*=mainMenu]',
        '[class*=lnb]', '[class*=navMenu]', '[class*=nav-menu]'
      ];

      let gnb = null;
      for (const sel of selectors) {
        const hits = Array.from(document.querySelectorAll(sel)).filter(el => {
          if (!isVis(el)) return false;
          const r = el.getBoundingClientRect();
          return r.width >= window.innerWidth * 0.35 && r.height <= 130 && r.y <= 220;
        });
        if (hits.length) { gnb = hits[0]; break; }
      }

      if (gnb) {
        const hit = Array.from(gnb.querySelectorAll('a,button,span,li,div'))
          .filter(el => isVis(el) && norm(el.innerText || el.value || '') === targetText)
          .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x)[0];
        if (hit) return fireHover(hit);
      }

      const hit = Array.from(document.querySelectorAll('a,button,span,div,li'))
        .filter(el => {
          if (!isVis(el)) return false;
          const r = el.getBoundingClientRect();
          return r.y <= 160 && norm(el.innerText || el.value || '') === targetText;
        })
        .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x)[0];

      if (hit) return fireHover(hit);
      return false;
    }
    """, text))


def _js_click_submenu(page: Page, text: str) -> bool:
    return bool(page.evaluate("""
    (targetText) => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const norm = v => (v || '')
        .replace(/\u00a0/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();

      const candidates = Array.from(document.querySelectorAll('li, a, button, span, div'))
        .filter(el => {
          if (!isVis(el)) return false;
          const r = el.getBoundingClientRect();
          return r.y <= 520 && norm(el.innerText || el.value || '') === targetText;
        })
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return ar.y - br.y || ar.x - br.x;
        });

      if (!candidates.length) return false;

      const target = candidates[0];
      const clickable =
        target.closest('a,button') ||
        target.querySelector('a,button') ||
        target.closest('li')?.querySelector('a,button') ||
        target.closest('li') ||
        target;

      const r = clickable.getBoundingClientRect();
      clickable.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
      clickable.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true,
        clientX: r.left + 8,
        clientY: r.top + r.height / 2
      }));
      clickable.dispatchEvent(new MouseEvent('mouseup', {
        bubbles: true,
        clientX: r.left + 8,
        clientY: r.top + r.height / 2
      }));
      clickable.click();

      return true;
    }
    """, text))


# ──────────────────────────────────────────────
# Homepage + navigation
# ──────────────────────────────────────────────
def open_homepage(page: Page, timeout_ms: int) -> None:
    nav_timeout = max(timeout_ms, 120_000)
    ready_timeout = max(30_000, min(timeout_ms, 60_000))
    last_error: Exception | None = None

    for url in HOME_URLS:
        for attempt in range(1, MAX_HOME_ATTEMPTS + 1):
            backoff_ms = BASE_BACKOFF_MS * (2 ** (attempt - 1))
            log(f"Homepage attempt {attempt}/{MAX_HOME_ATTEMPTS}: {url}")

            navigation_success = False
            for wait_until in ("domcontentloaded", "commit"):
                try:
                    page.goto(url, wait_until=wait_until, timeout=nav_timeout)
                    navigation_success = True
                    log(f"  Navigation succeeded with '{wait_until}'")
                    break
                except Exception as exc:
                    last_error = exc
                    err = str(exc)

                    if "ERR_CONNECTION_RESET" in err or "ERR_CONNECTION_REFUSED" in err:
                        log(f"  Connection reset on '{wait_until}' — retrying after {backoff_ms} ms")
                        page.wait_for_timeout(backoff_ms)
                        continue

                    if "Timeout" in err and wait_until == "domcontentloaded":
                        log("  domcontentloaded timed out — trying 'commit'")
                        continue

                    log(f"  Navigation error ({wait_until}): {exc}")
                    page.wait_for_timeout(backoff_ms)

            if not navigation_success:
                continue

            log("  Waiting for page to settle …")
            page.wait_for_timeout(10_000)
            wait_ready(page, ready_timeout)

            body = page.evaluate("() => (document.body?.innerText || '').trim()")
            if body and len(body) > 50:
                log(f"  Page content confirmed ({len(body)} chars) — proceeding")
                page.wait_for_timeout(4_000)
                return

            log(f"  Page body too short ({len(body)} chars) — retrying after {backoff_ms} ms")
            page.wait_for_timeout(backoff_ms)

    raise RuntimeError(
        f"Could not load G2B homepage after {MAX_HOME_ATTEMPTS * len(HOME_URLS)} attempts. "
        f"Last error: {last_error}"
    )


def navigate_to_bid_list(page: Page, timeout_ms: int, args: argparse.Namespace | None = None) -> None:
    """
    Fast robust navigation:
      - dismiss popups once
      - hover 입찰
      - click 입찰공고목록
      - wait until the form is detected
    """
    dismiss_all_popups_until_clear(page)
    pause(page, args, 1500, 500)

    if is_bid_list_open(page):
        log("Already on 입찰공고목록")
        return

    for nav_round in range(1, 3 if args is not None and getattr(args, "fast", False) else 4):
        log(f"Navigation round {nav_round} …")

        hovered = False
        for attempt in range(3 if args is not None and getattr(args, "fast", False) else 5):
            hovered = (
                _js_hover_gnb(page, "입찰")
                or _js_click_gnb(page, "입찰")
                or _js_click_text(page, "입찰", y_limit=160)
            )
            if hovered:
                log("  Hovered '입찰' in GNB bar")
                break

            log(f"  GNB '입찰' not found (attempt {attempt + 1})")
            # Only drain popups again if a popup is actually present.
            try:
                if page.evaluate(_HAS_NOTICE_POPUP_JS):
                    dismiss_all_popups_until_clear(page)
            except Exception:
                pass
            pause(page, args, 1200 * (attempt + 1), 350 * (attempt + 1))

        if not hovered:
            continue

        pause(page, args, 2000, 450)

        submenu_clicked = False
        for attempt in range(3 if args is not None and getattr(args, "fast", False) else 5):
            _js_hover_gnb(page, "입찰") or _js_click_gnb(page, "입찰") or _js_click_text(page, "입찰", y_limit=160)
            pause(page, args, 900, 250)

            submenu_clicked = (
                _js_click_submenu(page, "입찰공고목록")
                or _js_click_text(page, "입찰공고목록", y_limit=520)
            )

            if submenu_clicked:
                log("  Clicked '입찰공고목록' in submenu")
                break

            pause(page, args, 1200 * (attempt + 1), 300 * (attempt + 1))

        if submenu_clicked:
            # Avoid waiting 30 seconds every time. Check frequently and move on.
            for _ in range(14 if args is not None and getattr(args, "fast", False) else 30):
                pause(page, args, 1000, 350)
                wait_ready(page, 10_000 if args is not None and getattr(args, "fast", False) else 60_000)
                if is_bid_list_open(page):
                    log("Successfully reached 입찰공고목록 ✓")
                    return

            log("  Page after click did not match detector")

        if is_bid_list_open(page):
            log("Successfully reached 입찰공고목록 ✓")
            return

        log(f"  Target not reached after round {nav_round} — retrying …")
        pause(page, args, 2000, 500)

    raise RuntimeError("Did not reach 입찰공고목록 after navigation retries.")


# ──────────────────────────────────────────────
# Search filters
# ──────────────────────────────────────────────
def click_advanced_conditions(page: Page, args: argparse.Namespace | None = None) -> None:
    """Click 상세조건 dark blue button and wait briefly for advanced section."""
    log("Opening 상세조건 …")

    clicked = bool(page.evaluate("""
    () => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };
      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

      const candidates = Array.from(document.querySelectorAll('button, a, input[type=button], span, div'))
        .filter(el => {
          if (!isVis(el)) return false;
          const txt = norm(el.innerText || el.value || '');
          const r = el.getBoundingClientRect();
          return txt === '상세조건' &&
                 r.width >= 60 &&
                 r.width <= 180 &&
                 r.height >= 25 &&
                 r.height <= 80;
        })
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return ar.y - br.y || ar.x - br.x;
        });

      if (!candidates.length) return false;
      candidates[0].click();
      return true;
    }
    """))

    if not clicked:
        raise RuntimeError("Could not click 상세조건 button.")

    dismiss_transient_warning_pass(page, rounds=2, pause_ms=900)

    for _ in range(20):
        page.wait_for_timeout(300)
        opened = bool(page.evaluate("""
        () => {
          const txt = (document.body?.innerText || '').replace(/\\u00a0/g, ' ');
          return txt.includes('업종') || txt.includes('세부품명') || txt.includes('계약방법');
        }
        """))
        if opened:
            log("상세조건 opened.")
            return

    log("상세조건 clicked; advanced section not strongly confirmed.")


def click_main_industry_magnifier(page: Page, args: argparse.Namespace | None = None) -> bool:
    """
    Click the magnifier/search button next to 업종 in 상세조건.

    This version is intentionally broad because G2B/WebSquare changes wrappers:
      - first find visible labels exactly/near 업종
      - find text input on same row
      - click the small button/icon immediately to the right of that input
      - fallback to metadata/id patterns containing 업종 + search
    """
    result = page.evaluate("""
    () => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

      const clickIt = (el, method) => {
        if (!el) return {clicked:false, method, reason:'no element'};
        el.scrollIntoView({ block: 'center', inline: 'center' });

        const r = el.getBoundingClientRect();
        const opts = {
          bubbles: true,
          cancelable: true,
          view: window,
          clientX: r.left + r.width / 2,
          clientY: r.top + r.height / 2
        };

        el.dispatchEvent(new MouseEvent('mouseover', opts));
        el.dispatchEvent(new MouseEvent('mouseenter', opts));
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));

        if (typeof el.click === 'function') el.click();

        return {
          clicked: true,
          method,
          tag: el.tagName,
          text: norm(el.innerText || el.value || el.title || el.alt || ''),
          id: el.id || '',
          cls: String(el.className || '').slice(0, 120),
          x: Math.round(r.x),
          y: Math.round(r.y),
          w: Math.round(r.width),
          h: Math.round(r.height)
        };
      };

      const labels = Array.from(document.querySelectorAll('th, td, label, span, div'))
        .filter(el => {
          if (!isVis(el)) return false;
          const t = norm(el.innerText);
          const r = el.getBoundingClientRect();

          // Avoid popup result labels if already present, but allow advanced area.
          const areaText = norm(el.closest('div, section, article, form, table')?.innerText || '');
          const inPopup = areaText.includes('업종 목록') && areaText.includes('업종코드');

          return !inPopup &&
                 r.y > 250 &&
                 (
                   t === '업종' ||
                   t === '업종코드' ||
                   t.includes('업종')
                 );
        })
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return ar.y - br.y || ar.x - br.x;
        });

      const inspected = [];

      for (const label of labels) {
        const lr = label.getBoundingClientRect();
        inspected.push({
          label: norm(label.innerText).slice(0, 50),
          x: Math.round(lr.x),
          y: Math.round(lr.y)
        });

        // Walk upward through likely row/container wrappers.
        let box = label.closest('tr, li, div, td, table');
        for (let depth = 0; depth < 12 && box; depth++) {
          const inputs = Array.from(box.querySelectorAll('input'))
            .filter(el => {
              if (!isVis(el)) return false;
              const r = el.getBoundingClientRect();
              const typeOk = !/button|checkbox|radio|hidden/i.test(el.type || '');
              const sameBand = Math.abs((r.y + r.height / 2) - (lr.y + lr.height / 2)) < 120;
              return typeOk && sameBand;
            })
            .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);

          for (const input of inputs) {
            const ir = input.getBoundingClientRect();

            // Candidate buttons/icons near the input.
            const btns = Array.from(box.querySelectorAll(
              'button, a, input[type=button], input[type=image], span, img, div'
            ))
              .filter(el => {
                if (!isVis(el) || el === input) return false;

                const r = el.getBoundingClientRect();
                const txt = norm(el.innerText || el.value || el.title || el.alt || '');
                const meta = `${el.id || ''} ${el.className || ''} ${el.title || ''} ${el.alt || ''} ${el.name || ''}`;

                const sameRow = Math.abs((r.y + r.height / 2) - (ir.y + ir.height / 2)) <= 45;
                const rightSide = r.x >= ir.right - 20 && r.x <= ir.right + 160;
                const small = r.width <= 160 && r.height <= 90;
                const searchish = (
                  txt === '검색' ||
                  /검색|search|srch|magn|돋보기|trigger|icon|btn|w2trigger/i.test(txt + ' ' + meta)
                );

                return sameRow && rightSide && small && searchish;
              })
              .sort((a, b) => {
                const ar = a.getBoundingClientRect();
                const br = b.getBoundingClientRect();
                return ar.x - br.x || ar.y - br.y;
              });

            if (btns.length) {
              return clickIt(btns[0], 'near_industry_input');
            }
          }

          box = box.parentElement?.closest('tr, li, div, td, table') || null;
        }
      }

      // Fallback: look for inputs/buttons with 업종 in id/name/title.
      const allInputs = Array.from(document.querySelectorAll('input'))
        .filter(el => {
          if (!isVis(el)) return false;
          const meta = `${el.id || ''} ${el.name || ''} ${el.title || ''} ${el.placeholder || ''} ${el.getAttribute('aria-label') || ''}`;
          return /업종|ind|biz|bsns/i.test(meta) &&
                 !/button|checkbox|radio|hidden/i.test(el.type || '');
        });

      for (const input of allInputs) {
        const ir = input.getBoundingClientRect();
        const btns = Array.from(document.querySelectorAll('button, a, input[type=button], input[type=image], span, img, div'))
          .filter(el => {
            if (!isVis(el)) return false;
            const r = el.getBoundingClientRect();
            const txt = norm(el.innerText || el.value || el.title || el.alt || '');
            const meta = `${el.id || ''} ${el.className || ''} ${el.title || ''} ${el.alt || ''} ${el.name || ''}`;
            return Math.abs((r.y + r.height / 2) - (ir.y + ir.height / 2)) <= 45 &&
                   r.x >= ir.right - 20 &&
                   r.x <= ir.right + 160 &&
                   r.width <= 160 &&
                   r.height <= 90 &&
                   (txt === '검색' || /검색|search|srch|magn|돋보기|trigger|icon|btn|w2trigger/i.test(txt + ' ' + meta));
          })
          .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);

        if (btns.length) return clickIt(btns[0], 'metadata_input_fallback');
      }

      return {clicked:false, reason:'no industry magnifier found', inspected};
    }
    """)

    if args is not None:
        debug_log(args, f"industry magnifier click result: {json.dumps(result, ensure_ascii=False)}")
        if not result.get("clicked"):
            save_debug_screenshot(page, args, "industry_magnifier_not_found")

    return bool(result.get("clicked"))


def fill_industry_popup_code(page: Page, industry_code: str, args: argparse.Namespace | None = None) -> None:
    """Fill 업종코드 in popup, click 검색, wait for result grid, then select code."""
    log(f"Selecting 업종코드 {industry_code} …")

    if not click_main_industry_magnifier(page, args):
        raise RuntimeError("Could not click 업종 magnifier button in 상세조건.")

    page.wait_for_timeout(1200)

    filled = bool(page.evaluate("""
    (code) => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

      // Scope to the popup/search area. Do not require "업종 목록" yet,
      // because the list may not be loaded before search.
      const popup = Array.from(document.querySelectorAll('div, section, article, form'))
        .filter(el => {
          if (!isVis(el)) return false;
          const txt = norm(el.innerText);
          const r = el.getBoundingClientRect();
          return r.width >= 300 &&
                 r.height >= 100 &&
                 txt.includes('업종코드') &&
                 txt.includes('업종명');
        })
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return (br.width * br.height) - (ar.width * ar.height);
        })[0];

      if (!popup) return false;

      const labels = Array.from(popup.querySelectorAll('th, td, label, span, div'))
        .filter(el => isVis(el) && norm(el.innerText).includes('업종코드'));

      for (const label of labels) {
        const lr = label.getBoundingClientRect();
        let box = label.closest('tr, div, td');

        for (let i = 0; i < 10 && box; i++) {
          const inputs = Array.from(box.querySelectorAll('input'))
            .filter(el => {
              if (!isVis(el)) return false;
              const r = el.getBoundingClientRect();
              return !/button|checkbox|radio|hidden/i.test(el.type || '') &&
                     Math.abs((r.y + r.height / 2) - (lr.y + lr.height / 2)) < 80;
            })
            .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);

          if (inputs.length) {
            const input = inputs[0];
            input.removeAttribute('readonly');
            input.focus();

            const proto = Object.getPrototypeOf(input);
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) desc.set.call(input, code);
            else input.value = code;

            input.setAttribute('value', code);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: code.slice(-1) }));
            input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: code.slice(-1) }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.dispatchEvent(new Event('blur', { bubbles: true }));
            return true;
          }

          box = box.parentElement?.closest('tr, div, td') || null;
        }
      }

      return false;
    }
    """, industry_code))

    if not filled:
        if args is not None:
            save_debug_screenshot(page, args, "industry_popup_code_not_filled")
        raise RuntimeError("Could not fill 업종코드 in popup.")

    page.wait_for_timeout(400)

    # Click the popup 검색 button. Scope to the popup and prefer the button on the same row as 업종코드.
    searched = bool(page.evaluate("""
    () => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

      const popup = Array.from(document.querySelectorAll('div, section, article, form'))
        .filter(el => {
          if (!isVis(el)) return false;
          const txt = norm(el.innerText);
          const r = el.getBoundingClientRect();
          return r.width >= 300 &&
                 r.height >= 100 &&
                 txt.includes('업종코드') &&
                 txt.includes('업종명');
        })
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return (br.width * br.height) - (ar.width * ar.height);
        })[0];

      if (!popup) return false;

      const codeLabel = Array.from(popup.querySelectorAll('th, td, label, span, div'))
        .find(el => isVis(el) && norm(el.innerText).includes('업종코드'));
      const labelY = codeLabel ? (codeLabel.getBoundingClientRect().y + codeLabel.getBoundingClientRect().height / 2) : null;

      const btns = Array.from(popup.querySelectorAll('button, a, input[type=button], input[type=image], span, img'))
        .filter(el => {
          if (!isVis(el)) return false;
          const txt = norm(el.innerText || el.value || el.title || el.alt || '');
          const meta = `${el.id || ''} ${el.className || ''} ${el.title || ''} ${el.alt || ''} ${el.name || ''}`;
          const r = el.getBoundingClientRect();
          const sameBand = labelY === null || Math.abs((r.y + r.height / 2) - labelY) < 120;
          return sameBand &&
                 (txt === '검색' || /검색|search|srch|magn|돋보기|btn.*search/i.test(txt + ' ' + meta));
        })
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return ar.y - br.y || ar.x - br.x;
        });

      if (!btns.length) return false;

      const btn = btns[0];
      btn.scrollIntoView({ block: 'center', inline: 'center' });
      const r = btn.getBoundingClientRect();
      const opts = {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: r.left + r.width / 2,
        clientY: r.top + r.height / 2
      };
      btn.dispatchEvent(new MouseEvent('mouseover', opts));
      btn.dispatchEvent(new MouseEvent('mousedown', opts));
      btn.dispatchEvent(new MouseEvent('mouseup', opts));
      btn.dispatchEvent(new MouseEvent('click', opts));
      if (typeof btn.click === 'function') btn.click();

      return true;
    }
    """))

    if not searched:
        if args is not None:
            save_debug_screenshot(page, args, "industry_popup_search_not_clicked")
        raise RuntimeError("Could not click 검색 in 업종 popup.")

    log("업종 popup search clicked; waiting for results …")

    # Wait for result to appear. The popup may not literally contain "업종 목록" in its visible text,
    # so detect by exact visible code cell or code + expected industry text.
    row_loaded = False
    for i in range(60):
        page.wait_for_timeout(500)
        row_loaded = bool(page.evaluate("""
        (code) => {
          const isVis = el => {
            if (!el) return false;
            const s = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' &&
                   s.visibility !== 'hidden' &&
                   r.width > 0 &&
                   r.height > 0;
          };
          const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

          const exactCells = Array.from(document.querySelectorAll('td, [role=gridcell], div, span'))
            .filter(el => isVis(el) && norm(el.innerText || el.value || '') === code);

          if (exactCells.length) return true;

          const body = norm(document.body?.innerText || '');
          return body.includes(code) && (body.includes('의료기기제조업') || body.includes('업종명'));
        }
        """, industry_code))
        if row_loaded:
            log(f"업종 popup result appeared after {(i + 1) * 0.5:.1f}s")
            break

    if not row_loaded:
        if args is not None:
            try:
                txt = page.locator("body").inner_text(timeout=3000)[:2000]
                debug_log(args, f"Industry popup text when result missing: {txt}")
            except Exception:
                pass
            save_debug_screenshot(page, args, "industry_result_not_loaded")
        raise RuntimeError(f"Industry code {industry_code} did not appear in popup result list.")

    selected = bool(page.evaluate("""
    (code) => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

      const cells = Array.from(document.querySelectorAll('td, [role=gridcell], div, span'))
        .filter(el => isVis(el) && norm(el.innerText || el.value || '') === code)
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return ar.y - br.y || ar.x - br.x;
        });

      if (!cells.length) return false;

      const cell = cells[0];
      const row = cell.closest('tr, [role=row], .w2grid_row, .w2grid_body_row, .w2tb_tr') ||
                  cell.parentElement ||
                  cell;

      row.scrollIntoView({ block: 'center', inline: 'center' });

      const r = cell.getBoundingClientRect();
      const opts = {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: r.left + r.width / 2,
        clientY: r.top + r.height / 2
      };

      // Some WebSquare grids select on dblclick, some on click.
      for (const el of [cell, row]) {
        el.dispatchEvent(new MouseEvent('mouseover', opts));
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));
        el.dispatchEvent(new MouseEvent('dblclick', opts));
      }

      return true;
    }
    """, industry_code))

    if not selected:
        if args is not None:
            save_debug_screenshot(page, args, "industry_result_not_selected")
        raise RuntimeError(f"Industry code {industry_code} appeared but could not be selected.")

    page.wait_for_timeout(1200)
    dismiss_transient_warning_pass(page, rounds=2, pause_ms=900)
    log(f"업종코드 {industry_code} selected.")


def apply_filters(
    page: Page,
    timeout_ms: int,
    start_date: str,
    end_date: str,
    query_text: str,
    args: argparse.Namespace | None = None,
) -> None:
    if not is_bid_list_open(page):
        raise RuntimeError("입찰공고목록 form is not open.")

    industry_code = getattr(args, "industry_code", "5309")
    log(f"Applying filters: date={start_date} ~ {end_date}, 업종코드={industry_code} …")
    wait_ready(page, 15_000 if args is not None and getattr(args, "fast", False) else 30_000)

    ok = bool(page.evaluate("""
    ([startDate, endDate, queryText]) => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const setVal = (input, value) => {
        input.removeAttribute('readonly');
        input.focus();
        const proto = Object.getPrototypeOf(input);
        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
        if (desc && desc.set) desc.set.call(input, value);
        else input.value = value;
        input.setAttribute('value', value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: value.slice(-1) }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.dispatchEvent(new Event('blur', { bubbles: true }));
      };

      const inputs = Array.from(document.querySelectorAll('input'))
        .filter(el => isVis(el) && !/button|checkbox|radio|hidden/i.test(el.type || ''));

      const dateInputs = inputs
        .filter(el => /\\d{4}\\/\\d{2}\\/\\d{2}/.test(el.value || ''))
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return ar.y - br.y || ar.x - br.x;
        });

      if (dateInputs.length < 2) return false;

      setVal(dateInputs[0], startDate);
      setVal(dateInputs[1], endDate);

      // Optional: keep 공고명 blank unless queryText explicitly provided.
      if (queryText) {
        const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
        const labels = Array.from(document.querySelectorAll('th, td, label, span, div'))
          .filter(el => isVis(el) && norm(el.innerText) === '공고명');

        for (const label of labels) {
          const lr = label.getBoundingClientRect();
          const candidates = inputs
            .filter(inp => {
              const r = inp.getBoundingClientRect();
              const sameRow = Math.abs((r.y + r.height / 2) - (lr.y + lr.height / 2)) < 30;
              const right = r.x > lr.x;
              const wide = r.width >= 120 && r.height >= 15;
              const isDate = /\\d{4}\\/\\d{2}\\/\\d{2}/.test(inp.value || '');
              return sameRow && right && wide && !isDate;
            })
            .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);

          if (candidates.length) setVal(candidates[0], queryText);
        }
      }

      return true;
    }
    """, [start_date, end_date, query_text]))

    if not ok:
        raise RuntimeError("Could not apply date filters.")

    log("Date filters applied.")
    pause(page, args, 300, 100)

    if compact(str(industry_code or "")):
        click_advanced_conditions(page, args)
        fill_industry_popup_code(page, industry_code, args)
        pause(page, args, 300, 150)
        log("Industry filter applied.")
    else:
        log("Industry filter skipped.")


def trigger_search(page: Page, timeout_ms: int, args: argparse.Namespace | None = None) -> None:
    log("Clicking search button …")

    search_button_ids = [
        "mf_wfm_container_wq_uuid_928_wq_uuid_937_btnBidPbancDtlSrch",
        "mf_wfm_container_wq_uuid_925_wq_uuid_934_btnBidPbancDtlSrch",
    ]

    clicked = any(_js_click_id(page, element_id) for element_id in search_button_ids)
    if not clicked:
        clicked = _js_click_text(page, "검색하기") or _js_click_text(page, "검색")

    if not clicked:
        raise RuntimeError("Could not click the search button.")

    dismiss_transient_warning_pass(page, rounds=2, pause_ms=900)
    pause(page, args, 3_000, 800)
    dismiss_transient_warning_pass(page, rounds=2, pause_ms=900)
    wait_ready(page, timeout_ms)
    wait_for_loading_clear(page, timeout_ms)
    log("Search triggered — results loaded/settled …")

    result_state = wait_for_result_rows_or_empty_state(page, timeout_ms, args)
    if args is not None:
        args._search_result_state = result_state
    if result_state == "rows":
        log("Initial tender rows are visible.")
    elif result_state == "empty":
        log("Search returned an empty result set for the current filters.")
    else:
        log("Search finished but visible rows were not confirmed yet.")


def wait_for_result_rows_or_empty_state(
    page: Page,
    timeout_ms: int,
    args: argparse.Namespace | None = None,
    max_wait_ms: int = 25_000,
) -> str:
    """
    After search, wait for either:
    - visible tender rows
    - an explicit empty/no-data result state
    Returns: "rows", "empty", or "timeout".
    """
    elapsed = 0
    while elapsed < max_wait_ms:
        try:
            wait_for_loading_clear(page, min(timeout_ms, 10_000))
        except Exception:
            pass

        try:
            rows = extract_rows(page)
            if rows:
                return "rows"
        except Exception:
            pass

        try:
            result_state = page.evaluate("""
            () => {
              const txt = (document.body?.innerText || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
              if (
                txt.includes('데이터가 없음') ||
                txt.includes('데이터가 없습니다') ||
                txt.includes('조회된 데이터가 없습니다') ||
                txt.includes('검색 결과가 없습니다') ||
                txt.includes('전체 0건')
              ) {
                return 'empty';
              }
              return '';
            }
            """)
            if result_state == "empty":
                return "empty"
        except Exception:
            pass

        page.wait_for_timeout(800)
        elapsed += 800

    return "timeout"


# ──────────────────────────────────────────────
# Result scraping
# ──────────────────────────────────────────────
def extract_rows(page: Page) -> List[TenderRow]:
    """
    Extract every visible tender row from the result grid.
    Do not filter by status; consider every row.
    """
    raw = page.evaluate("""
    () => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
      const noticeRe = /\\b\\d{11}\\s*-\\s*\\d{3}\\b/;
      const alphaNoticeRe = /\\b[A-Z]\\w{6,}\\b/i;
      const hasDate = txt => /\\d{4}\\/\\d{2}\\/\\d{2}/.test(txt || '');
      const isTenderishRow = (row, rowText) => {
        if (!rowText) return false;
        if (rowText.includes('공고일반') || rowText.includes('구매대상물품')) return false;
        if (/^(No|순번|번호)\\b/.test(rowText)) return false;

        const links = Array.from(row.querySelectorAll('a'))
          .filter(isVis)
          .map(a => norm(a.innerText || ''))
          .filter(Boolean);

        const hasTitleLink = links.some(t =>
          t.length >= 6 &&
          !['입찰진행', '진행완료', '개찰완료', '모의점검', '상세', '보기'].includes(t)
        );

        const looksLikeGridRow =
          (noticeRe.test(rowText) || alphaNoticeRe.test(rowText) || hasTitleLink) &&
          hasDate(rowText);

        return looksLikeGridRow;
      };

      const results = [];
      const seen = new Set();

      const rowSelectors = [
        'table tbody tr',
        '[role=row]',
        '.w2grid_row',
        '.w2grid_body_row',
        '.w2repeat tr'
      ];

      for (const sel of rowSelectors) {
        for (const row of document.querySelectorAll(sel)) {
          if (!isVis(row)) continue;

          const rowText = norm(row.innerText || '');
          if (!rowText) continue;
          if (!isTenderishRow(row, rowText)) continue;

          const candidates = Array.from(row.querySelectorAll('a, button, span, div, td'))
            .filter(isVis)
            .map(el => ({
              text: norm(el.innerText || el.value || el.title || ''),
              href: el.href || el.getAttribute('href') || ''
            }))
            .filter(x => x.text && x.text.length >= 2)
            .filter(x => {
              const t = x.text;
              if (noticeRe.test(t)) return false;
              if (alphaNoticeRe.test(t) && t.length <= 20) return false;
              if (/^\\d+$/.test(t)) return false;
              if (/^\\d{4}\\/\\d{2}\\/\\d{2}/.test(t)) return false;
              if (['입찰진행','진행완료','개찰완료','모의점검','-'].includes(t)) return false;
              return t.length >= 4;
            })
            .sort((a, b) => b.text.length - a.text.length);

          const best = candidates[0];
          const title = best ? best.text : rowText;
          const href = best ? best.href : '';

          const key = rowText;
          if (seen.has(key)) continue;
          seen.add(key);

          results.push({ title, rowText, href });
        }
      }

      return results;
    }
    """)

    out: List[TenderRow] = []
    for r in raw:
        title = compact(r.get("title", ""))
        row_text = compact(r.get("rowText", ""))
        href = compact(r.get("href", ""))

        if title and row_text:
            out.append(TenderRow(title=title, row_text=row_text, href=href))

    return out


def _result_row_signature(page: Page) -> str:
    try:
        state = save_scroll(page) or {}
        top = int(state.get("top", 0) or 0) if isinstance(state, dict) else 0
        rows = extract_rows(page)
        row_sig = "|".join((normalize_notice_id(r.row_text) or r.row_text[:80]) for r in rows)
        return f"{top}::{row_sig}"
    except Exception:
        return ""


def scroll_once(page: Page) -> bool:
    """
    Scroll the internal result grid/table body, not just the window.

    WebSquare may lazy-load rows after the scroll action, so this returns True when
    a plausible scroll action was attempted. scrape_results waits for row changes.
    """
    attempted = page.evaluate("""
    () => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };
      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
      const noticeRe = /\\b\\d{11}\\s*-\\s*\\d{3}\\b/;
      const alphaNoticeRe = /\\b[A-Z]\\w{6,}\\b/i;
      const rowLike = txt => (noticeRe.test(txt) || alphaNoticeRe.test(txt) || txt.includes('입찰진행')) && /\\d{4}\\/\\d{2}\\/\\d{2}/.test(txt);
      const isScrollable = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const overflowY = `${s.overflowY || ''} ${s.overflow || ''}`;
        return /(auto|scroll|overlay)/i.test(overflowY) && el.scrollHeight > el.clientHeight + 20;
      };
      const scoreScroller = (el, row) => {
        if (!el) return -1;
        const txt = norm(el.innerText || '');
        const meta = `${el.id || ''} ${el.className || ''}`;
        let score = 0;
        if (row && el.contains(row)) score += 120;
        if (rowLike(txt)) score += 80;
        if (txt.includes('공고명')) score += 30;
        if (txt.includes('입찰공고번호')) score += 30;
        if (/w2grid|grid|scroll|body|contents/i.test(meta)) score += 40;
        score += Math.min(40, Math.floor((el.clientHeight || 0) / 12));
        return score;
      };
      const tryScroll = (el, delta) => {
        if (!el) return false;
        const beforeTop = el.scrollTop || 0;
        el.focus?.();
        el.scrollTop = Math.min(beforeTop + delta, el.scrollHeight);
        if ((el.scrollTop || 0) === beforeTop) {
          el.scrollTop = Math.min(beforeTop + Math.max(delta, 700), el.scrollHeight);
        }
        el.dispatchEvent(new Event('scroll', { bubbles: true }));
        return (el.scrollTop || 0) !== beforeTop;
      };

      const rows = Array.from(document.querySelectorAll('tr, div, li'))
        .filter(el => isVis(el) && rowLike(norm(el.innerText || '')));

      const candidates = [];
      for (const row of rows) {
        let cur = row;
        for (let depth = 0; cur && depth < 10; depth += 1, cur = cur.parentElement) {
          if (!isVis(cur) || !isScrollable(cur)) continue;
          candidates.push({ el: cur, score: scoreScroller(cur, row) });
        }
      }

      const unique = [];
      const seen = new Set();
      for (const c of candidates.sort((a, b) => b.score - a.score)) {
        if (!c.el) continue;
        if (seen.has(c.el)) continue;
        seen.add(c.el);
        unique.push(c);
      }

      let scroller = null;
      const preferred = document.querySelector('[data-g2b-scroll-key="result-grid-scroller"]');
      const ordered = preferred ? [{ el: preferred, score: 9999 }, ...unique] : unique;

      for (const candidate of ordered) {
        const el = candidate.el;
        const step = Math.max(420, Math.floor((el.clientHeight || 0) * 0.95));
        if (tryScroll(el, step)) {
          scroller = el;
          break;
        }
      }

      if (!scroller) {
        const fallback = Array.from(document.querySelectorAll('div, section, article, tbody, table'))
          .filter(el => isVis(el) && isScrollable(el))
          .map(el => ({ el, score: scoreScroller(el, null) }))
          .sort((a, b) => b.score - a.score);
        for (const candidate of fallback) {
          const el = candidate.el;
          const step = Math.max(420, Math.floor((el.clientHeight || 0) * 0.95));
          if (tryScroll(el, step)) {
            scroller = el;
            break;
          }
        }
      }

      if (scroller) {
        scroller.setAttribute('data-g2b-scroll-key', 'result-grid-scroller');
        const r = scroller.getBoundingClientRect();
        return {
          ok: true,
          x: Math.floor(r.left + Math.max(40, Math.min(r.width - 24, r.width * 0.65))),
          y: Math.floor(r.top + Math.max(30, Math.min(r.height - 24, r.height * 0.55))),
          delta: Math.max(420, Math.floor((scroller.clientHeight || 0) * 0.95)),
        };
      }

      window.scrollBy(0, Math.max(500, Math.floor(window.innerHeight * 0.8)));
      return {
        ok: true,
        x: Math.floor(window.innerWidth / 2),
        y: Math.floor(window.innerHeight / 2),
        delta: Math.max(500, Math.floor(window.innerHeight * 0.8)),
      };
    }
    """)

    try:
        if isinstance(attempted, dict) and attempted.get("ok"):
            x = int(attempted.get("x", 0) or 0)
            y = int(attempted.get("y", 0) or 0)
            delta = int(attempted.get("delta", 600) or 600)
            page.mouse.move(x, y)
            page.wait_for_timeout(80)
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(140)
            page.mouse.wheel(0, max(240, delta // 2))
        page.wait_for_timeout(300)
    except Exception:
        pass

    return bool(attempted)


def save_scroll(page: Page) -> dict:
    return page.evaluate("""
    () => {
      const noticeRe = /\\b\\d{11}\\s*-\\s*\\d{3}\\b/;
      const alphaNoticeRe = /\\b[A-Z]\\w{6,}\\b/i;
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
      };
      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
      const rowLike = txt => (noticeRe.test(txt) || alphaNoticeRe.test(txt) || txt.includes('입찰진행')) && /\\d{4}\\/\\d{2}\\/\\d{2}/.test(txt);
      const isScrollable = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const overflowY = `${s.overflowY || ''} ${s.overflow || ''}`;
        return /(auto|scroll|overlay)/i.test(overflowY) && el.scrollHeight > el.clientHeight + 20;
      };
      const scoreScroller = (el, row) => {
        if (!el) return -1;
        const meta = `${el.id || ''} ${el.className || ''}`;
        let score = 0;
        if (row && el.contains(row)) score += 120;
        if (rowLike(norm(el.innerText || ''))) score += 80;
        if (/w2grid|grid|scroll|body|contents/i.test(meta)) score += 40;
        score += Math.min(40, Math.floor((el.clientHeight || 0) / 12));
        return score;
      };
      const tagged = document.querySelector('[data-g2b-scroll-key="result-grid-scroller"]');
      if (tagged && isVis(tagged)) {
        return {type:'element', key:'result-grid-scroller', top:tagged.scrollTop || 0};
      }
      const rows = Array.from(document.querySelectorAll('tr, div, li'))
        .filter(el => isVis(el) && rowLike(norm(el.innerText || '')));
      let scroller = null;
      let bestScore = -1;
      for (const row of rows) {
        let cur = row;
        for (let depth = 0; cur && depth < 10; depth += 1, cur = cur.parentElement) {
          if (!isVis(cur) || !isScrollable(cur)) continue;
          const score = scoreScroller(cur, row);
          if (score > bestScore) {
            bestScore = score;
            scroller = cur;
          }
        }
      }
      if (scroller) {
        scroller.setAttribute('data-g2b-scroll-key', 'result-grid-scroller');
        return {type:'element', key:'result-grid-scroller', top:scroller.scrollTop || 0};
      }
      return {type:'window', top:window.scrollY || 0};
    }
    """)
def restore_scroll(page: Page, state: dict) -> None:
    page.evaluate("""
    (state) => {
      if (!state) return;
      if (state.type === 'element' && state.key) {
        const el = document.querySelector(`[data-g2b-scroll-key="${state.key}"]`);
        if (el) {
          el.scrollTop = state.top || 0;
          el.dispatchEvent(new Event('scroll', { bubbles: true }));
          return;
        }
      }
      window.scrollTo(0, state.top || 0);
    }
    """, state)
    page.wait_for_timeout(800)


def scroll_to_row(page: Page, state: dict) -> None:
    restore_scroll(page, state)


def click_row(page: Page, row: TenderRow, args: argparse.Namespace | None = None) -> bool:
    """
    Open the individual tender page.

    진행완료 is only the row status filter.
    The actual navigation target is the 공고명 blue title link in that row.
    Match the row by notice number when possible; otherwise by title.
    """
    result = page.evaluate("""
    ([title, rowText]) => {
      const bodyText = (document.body?.innerText || '').replace(/\\u00a0/g, ' ');
      if (/Loading|로딩|처리중|조회중/.test(bodyText)) {
        return {clicked:false, reason:'loading overlay/text still visible'};
      }

      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

      const noticeMatch = rowText.match(/\\b(\\d{11})\\s*-\\s*(\\d{3})\\b/);
      const noticeNo = noticeMatch ? `${noticeMatch[1]}-${noticeMatch[2]}` : '';

      const fireClick = el => {
        if (!el) return {clicked:false, reason:'no element'};
        el.scrollIntoView({ block: 'center', inline: 'center' });

        const r = el.getBoundingClientRect();
        const opts = {
          bubbles: true,
          cancelable: true,
          view: window,
          clientX: r.left + r.width / 2,
          clientY: r.top + r.height / 2
        };

        el.dispatchEvent(new MouseEvent('mouseover', opts));
        el.dispatchEvent(new MouseEvent('mouseenter', opts));
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));

        if (typeof el.click === 'function') {
          el.click();
        }

        return {
          clicked: true,
          tag: el.tagName,
          text: norm(el.innerText || el.value || ''),
          href: el.href || el.getAttribute('href') || '',
          onclick: el.getAttribute('onclick') || '',
          x: Math.round(r.x),
          y: Math.round(r.y),
          w: Math.round(r.width),
          h: Math.round(r.height)
        };
      };

      const rows = Array.from(document.querySelectorAll(
        'table tbody tr, [role=row], .w2grid_row, .w2grid_body_row'
      ));

      for (const row of rows) {
        if (!isVis(row)) continue;

        const rt = norm(row.innerText || '');
        const rowMatches =
          (noticeNo && rt.includes(noticeNo)) ||
          rt.includes(title) ||
          title.includes(rt);

        if (!rowMatches) continue;

        const anchors = Array.from(row.querySelectorAll('a'))
          .filter(a => isVis(a) && norm(a.innerText || '').length >= 2);

        // Prefer the visible blue title link in the 공고명 column.
        let titleAnchor =
          anchors.find(a => norm(a.innerText || '') === title) ||
          anchors.find(a => {
            const t = norm(a.innerText || '');
            return title.includes(t) || t.includes(title);
          }) ||
          anchors.find(a => {
            const t = norm(a.innerText || '');
            const r = a.getBoundingClientRect();
            return !['진행완료', '상세', '보기', '공고서', '규격서', '모의점검', '입찰진행'].includes(t) &&
                   t.length >= 6 &&
                   r.x < 900;
          });

        if (titleAnchor) {
          const clickResult = fireClick(titleAnchor);
          clickResult.method = 'title_anchor_preferred';
          clickResult.noticeNo = noticeNo;
          clickResult.rowText = rt.slice(0, 500);
          return clickResult;
        }

        return {
          clicked: false,
          reason: 'matched tender row but no title anchor found',
          noticeNo,
          anchors: anchors.map(a => norm(a.innerText || '')).slice(0, 10),
          rowText: rt.slice(0, 500)
        };
      }

      return {clicked:false, reason:'no matching tender row found', noticeNo};
    }
    """, [row.title, row.row_text])

    if args is not None:
        debug_log(args, f"click_row result: {json.dumps(result, ensure_ascii=False)}")

    if result.get("clicked"):
        try:
            dismiss_transient_warning_pass(page, rounds=2, pause_ms=900)
        except Exception:
            pass

    return bool(result.get("clicked"))

def full_scroll_detail(page: Page, rounds: int = 30) -> None:
    last_height = 0
    stagnant = 0

    for _ in range(rounds):
        height = int(page.evaluate(
            "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        ))

        if height == last_height:
            stagnant += 1
        else:
            stagnant = 0

        if stagnant >= 3:
            break

        last_height = height
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(900)

    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(400)


def extract_detail(page: Page) -> dict:
    return page.evaluate("""
    () => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };

      const body = (document.body?.innerText || '').replace(/\u00a0/g, ' ').trim();

      const titles = Array.from(document.querySelectorAll('h1,h2,h3,strong,th,caption'))
        .filter(isVis)
        .map(el => (el.innerText || '').replace(/\u00a0/g, ' ').trim())
        .filter(Boolean);

      const tables = Array.from(document.querySelectorAll('table'))
        .filter(isVis)
        .map((table, index) => ({
          index,
          caption: (table.caption?.innerText || '').replace(/\u00a0/g, ' ').trim(),
          headers: Array.from(table.querySelectorAll('th'))
            .map(el => (el.innerText || '').replace(/\u00a0/g, ' ').trim())
            .filter(Boolean),
          rows: Array.from(table.querySelectorAll('tr'))
            .map(tr => Array.from(tr.children)
              .map(el => (el.innerText || '').replace(/\u00a0/g, ' ').trim())
              .filter(Boolean))
            .filter(row => row.length),
        }))
        .filter(table => table.rows.length);

      return {
        url: location.href,
        bodyText: body.slice(0, 30000),
        titleCandidates: titles,
        tables
      };
    }
    """)



def clean_cell(value: str) -> str:
    value = compact(value)
    value = value.replace("Grid start", "").replace("Grid end", "")
    return re.sub(r"\s+", " ", value).strip()


def detail_tables_to_kv(tables: list[dict]) -> dict[str, str]:
    kv: dict[str, str] = {}
    bad_labels = {
        "No", "번호", "순번", "진행상태", "진행절차", "시작일시", "종료일시",
        "장소", "상세보기", "문서구분", "파일명", "파일크기", "다운로드",
    }

    def add(label: str, value: str) -> None:
        label = clean_cell(label).replace(" ", "")
        value = clean_cell(value)
        if not label or not value or label in bad_labels or value in bad_labels:
            return
        if len(label) > 40:
            return
        if label not in kv:
            kv[label] = value

    for table in tables or []:
        for row in table.get("rows", []) or []:
            cells = [clean_cell(c) for c in row if clean_cell(c)]
            if len(cells) < 2:
                continue
            if len(cells) >= 4:
                add(cells[0], cells[1])
                add(cells[2], cells[3])
            else:
                add(cells[0], cells[1])
    return kv


def kv_pick(kv: dict[str, str], *labels: str) -> str:
    for label in labels:
        key = label.replace(" ", "")
        if kv.get(key):
            return kv[key]
    for label in labels:
        key = label.replace(" ", "")
        for k, v in kv.items():
            if key in k and v:
                return v
    return ""


def extract_bid_process_dates(tables: list[dict]) -> tuple[str, str, str]:
    publication = ""
    closing = ""
    opening = ""
    for table in tables or []:
        rows = table.get("rows", []) or []
        caption = str(table.get("caption", "") or "")
        headers = " ".join(map(str, table.get("headers", []) or []))
        text = f"{caption} {headers} " + " ".join(" ".join(map(str, r)) for r in rows)
        if not any(x in text for x in ["입찰진행정보", "입찰진행현황", "공고게시", "입찰서제출", "개찰", "개찰일시"]):
            continue
        for row in rows:
            cells = [clean_cell(c) for c in row if clean_cell(c)]
            joined = " ".join(cells)
            dates = re.findall(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}(?::\d{2})?", joined)
            if "공고게시" in joined and dates:
                publication = dates[0]
            if "입찰서제출" in joined and dates:
                closing = dates[-1]
            if ("개찰" in joined or "개찰일시" in joined) and dates:
                opening = dates[-1]
    return publication, closing, opening



def extract_allowed_industries(tables: list[dict]) -> str:
    """
    Extract classification from the 투찰가능한업종 table/section.
    Example: 의료기기판매업(5312)
    """
    values: list[str] = []
    seen: set[str] = set()

    for table in tables or []:
        rows = table.get("rows", []) or []
        table_text = " ".join(" ".join(map(str, r)) for r in rows)

        if "투찰가능한업종" not in table_text and "허용업종" not in table_text:
            continue

        for row in rows:
            cells = [clean_cell(c) for c in row if clean_cell(c)]
            joined = " ".join(cells)

            if not cells:
                continue
            if "투찰가능한업종" in joined or "허용업종" in joined or joined == "No":
                continue

            for c in cells:
                if re.search(r"\(\d{4}\)", c) and c not in seen:
                    seen.add(c)
                    values.append(c)

    return " | ".join(values)


def extract_amounts_from_kv(kv: dict[str, str]) -> tuple[str, str]:
    for label in ["사업금액", "배정예산", "추정가격", "기초금액", "예정가격"]:
        val = kv_pick(kv, label)
        if val:
            cur, amt = extract_money(val)
            if amt:
                return cur, amt
    return "", ""


def extract_purchase_items(tables: list[dict]) -> list[dict]:
    """
    Extract item rows from the 구매대상물품 table.

    Screenshot layout is a 2-level header:
      No | 분류 | 수요기관 | 세부품명 | 납품일수 | 납품장소
           수량 | 단위 | 추정단가(원) | 세부품명번호 | 물품식별번호 | 규격 | 납품기한 | 인도조건

    Data appears over two visual rows, so we map by position:
      item_no            = first column No
      item_description   = 세부품명, e.g. 교육훈련장비
      item_quantity      = 수량, e.g. 10
      item_uom           = 단위, e.g. set
      item_unit_price    = 추정단가(원)
      item_awarded_value = blank unless a real amount exists
    """
    items: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for table in tables or []:
        rows = table.get("rows", []) or []
        table_text = " ".join(" ".join(map(str, r)) for r in rows)

        if "구매대상물품" not in table_text and not ("세부품명번호" in table_text and "납품장소" in table_text):
            continue

        # Flatten rows and keep only meaningful non-header rows.
        cleaned_rows = []
        for row in rows:
            cells = [clean_cell(c) for c in row if clean_cell(c)]
            joined = " ".join(cells)
            if not cells:
                continue
            if any(h in joined for h in ["수요기관 세부품명", "세부품명번호", "물품식별번호", "납품장소", "납품기한", "인도조건"]):
                continue
            if "구매대상물품" in joined or "전체" in joined:
                continue
            cleaned_rows.append(cells)

        # The actual data can be split across two rows:
        # Row A: [1, 1, 경남대학교, 교육훈련장비, 0, 학내 지정장소]
        # Row B: [10, set, '', 6010999901, '', 규격서 참고, 2025/02/20, 현장설치도]
        i = 0
        while i < len(cleaned_rows):
            row1 = cleaned_rows[i]
            row2 = cleaned_rows[i + 1] if i + 1 < len(cleaned_rows) else []
            if row2 and re.fullmatch(r"\d+", clean_cell(row2[0] or "")) and len(row2) >= 4 and re.fullmatch(r"\d{8,12}", clean_cell(row2[3] or "").replace(",", "")):
                # Detail row: [qty, uom, est_unit_price, item_code, ...]
                pass
            elif row2 and re.fullmatch(r"\d+", clean_cell(row2[0] or "")):
                row2 = []

            joined1 = " ".join(row1)
            joined2 = " ".join(row2)

            # Detect a top item row with No/classification/procuring institution/item name.
            looks_top = (
                len(row1) >= 4 and
                re.fullmatch(r"\d+", row1[0] or "") and
                any(not re.fullmatch(r"[\d,./:-]+", c or "") for c in row1[2:4])
            )

            if looks_top:
                item_no = row1[0]
                item_desc = row1[3] if len(row1) > 3 else ""
                # If row1[3] not useful, use the best Korean text after buyer.
                if not item_desc or item_desc in {"-", "0"}:
                    for c in row1[2:]:
                        if c and not re.fullmatch(r"[\d,./:-]+", c):
                            item_desc = c
                            break

                qty = ""
                uom = ""
                unit_price = ""
                item_value = ""

                if row2:
                    # In screenshot row2 starts: quantity, uom, unit price, item code...
                    if len(row2) >= 1:
                        qty = row2[0]
                    if len(row2) >= 2:
                        c2 = clean_cell(row2[1])
                        if c2 and not re.fullmatch(r"[\d,./:-]+", c2):
                            uom = c2
                    if len(row2) >= 3:
                        c3 = clean_cell(row2[2])
                        if c3 not in {"-", ""} and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", c3):
                            unit_price = c3

                    # If quantity/uom not mapped, search.
                    if not qty:
                        for c in row2:
                            if re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", c):
                                qty = c
                                break
                    if not uom:
                        for c in row2:
                            c_clean = clean_cell(c)
                            if c_clean and not re.fullmatch(r"[\d,./:-]+", c_clean) and not re.fullmatch(r"\d{8,12}", c_clean.replace(",", "")):
                                uom = c
                                break
                    if not unit_price:
                        for c in row2:
                            c_clean = clean_cell(c)
                            if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", c_clean):
                                unit_price = c_clean
                                break

                key = (item_no, item_desc, qty, unit_price)
                if key not in seen:
                    seen.add(key)
                    items.append({
                        "item_no": item_no,
                        "item_description": item_desc,
                        "item_uom": uom,
                        "item_quantity": qty,
                        "item_unit_price": unit_price,
                        "item_awarded_value": item_value,
                    })

                i += 2 if row2 else 1
                continue

            # Fallback for single-row normal tables.
            cells = row1
            if len(cells) >= 4:
                item_no = cells[0]
                if len(cells) >= 3 and re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", clean_cell(cells[0])) and not re.fullmatch(r"\d{1,2}", clean_cell(cells[0])):
                    i += 1
                    continue
                qty = ""
                uom = ""
                item_desc = ""
                unit_price = ""

                for c in cells:
                    if not qty and re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", c):
                        qty = c
                for c in cells:
                    c_clean = clean_cell(c)
                    if not uom and c_clean and not re.fullmatch(r"[\d,./:-]+", c_clean) and c_clean not in {"-", "0"} and not re.fullmatch(r"\d{8,12}", c_clean.replace(",", "")):
                        if "기관" not in c_clean and "대학교" not in c_clean and "의료원" not in c_clean:
                            uom = c_clean
                            break
                for c in cells:
                    c_clean = clean_cell(c)
                    if not unit_price and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", c_clean):
                        unit_price = c_clean

                candidates = [
                    c for c in cells
                    if c not in {item_no, qty, uom, "-", "0"}
                    and not re.fullmatch(r"[\d,./:-]+", c)
                    and not re.fullmatch(r"\d{8,12}", c)
                    and "기관" not in c
                    and "대학교" not in c
                    and "의료원" not in c
                ]
                item_desc = candidates[0] if candidates else ""

                key = (item_no, item_desc, qty, unit_price)
                if item_desc and key not in seen:
                    seen.add(key)
                    items.append({
                        "item_no": item_no,
                        "item_description": item_desc,
                        "item_uom": uom,
                        "item_quantity": qty,
                        "item_unit_price": unit_price,
                        "item_awarded_value": "",
                    })

            i += 1

    cleaned_items: list[dict] = []
    for item in items:
        desc = clean_cell(item.get("item_description", ""))
        qty = clean_cell(item.get("item_quantity", ""))
        uom = clean_cell(item.get("item_uom", ""))
        if (
            not qty
            and not uom
            and re.search(r"규격서\s*(참고|참조)|첨부파일\s*참조", desc)
        ):
            continue
        cleaned_items.append(item)

    return cleaned_items


def make_english_columns(record: dict, translate_en: bool) -> dict:
    record["title_en"] = translate_to_en(record.get("title", ""), translate_en)
    record["buyer_en"] = translate_to_en(record.get("buyer", ""), translate_en)
    record["classification_en"] = translate_to_en(record.get("classification", ""), translate_en)
    record["status_en"] = "Completed" if record.get("status") == "진행완료" else translate_to_en(record.get("status", ""), translate_en)
    record["awarding_agency_name_en"] = translate_to_en(record.get("awarding_agency_name", ""), translate_en)
    record["supplier_name_en"] = translate_to_en(record.get("supplier_name", ""), translate_en)
    record["item_description_en"] = translate_to_en(record.get("item_description", ""), translate_en)
    return record



def make_notice_url(notice_id: str, raw_url: str = "") -> str:
    """
    G2B is a WebSquare SPA, so browser location often remains https://www.g2b.go.kr/.
    Store a useful lookup URL with the notice number encoded as the query parameter.
    """
    notice_id = compact(notice_id)
    raw_url = compact(raw_url)

    if raw_url and raw_url.rstrip("/") not in {"https://www.g2b.go.kr", "https://www.g2b.go.kr/"}:
        return raw_url

    if notice_id:
        return f"https://www.g2b.go.kr/?searchText={notice_id}"

    return raw_url or "https://www.g2b.go.kr/"


def normalize_money_from_budget(value: str) -> tuple[str, str]:
    """
    Extract money ONLY from a value that contains 원/KRW/₩.
    This prevents dates like 2024/12/30 from becoming amount=2024.
    """
    value = compact(value)
    if not value:
        return "", ""
    if not any(marker in value for marker in ["원", "KRW", "₩"]):
        return "", ""
    return extract_money(value)


def find_budget_amount(kv: dict[str, str], detail_text: str) -> tuple[str, str]:
    """
    amount must come from 배정예산 only.
    """
    budget_text = kv_pick(kv, "배정예산")
    cur, amt = normalize_money_from_budget(budget_text)
    if amt:
        return cur, amt

    m = re.search(r"배정예산\s*[:：]?\s*([0-9][0-9,]*(?:\.\d+)?\s*(?:원|KRW|₩))", detail_text)
    if m:
        return normalize_money_from_budget(m.group(1))

    return "", ""


def find_supplier_from_notice_agency(kv: dict[str, str], detail_text: str) -> str:
    """
    supplier_name must come from 공고기관.
    """
    supplier = kv_pick(kv, "공고기관")
    if supplier:
        return clean_cell(supplier)

    m = re.search(
        r"공고기관\s*[:：]?\s*(.*?)(?=\s+(?:공고담당자|수요기관|입찰공고번호|공고명|게시일시|참조번호)\s*[:：]?|$)",
        detail_text,
        re.S,
    )
    if m:
        return clean_cell(m.group(1))

    return ""




def section_table_rows(tables: list[dict], section_keywords: list[str]) -> list[list[str]]:
    """
    Return rows from tables whose text contains one of the section keywords.
    """
    out: list[list[str]] = []
    for table in tables or []:
        rows = table.get("rows", []) or []
        caption = str(table.get("caption", "") or "")
        headers = " ".join(map(str, table.get("headers", []) or []))
        row_text = " ".join(" ".join(map(str, r)) for r in rows)
        table_text = f"{caption} {headers} {row_text}".strip()
        if any(k in table_text for k in section_keywords):
            for row in rows:
                cells = [clean_cell(c) for c in row if clean_cell(c)]
                if cells:
                    out.append(cells)
    return out


def extract_buyer_from_demand_org_table(tables: list[dict], fallback: str = "") -> str:
    """
    Buyer must come from 수요기관담당자정보 목록 -> 수요기관 column.
    Screenshot row:
      No | 수요기관 | 부서명 | 담당자 | 팩스번호 | 전화번호
      1  | 경남대학교 | 구매관재팀 | 심** | ...
    """
    rows = section_table_rows(tables, ["수요기관담당자정보", "수요기관담당자정보 목록"])
    for row in rows:
        joined = " ".join(row)
        if "수요기관" in joined and "부서명" in joined:
            continue
        if row and row[0] == "No":
            continue

        # Usually [1, 경남대학교, 구매관재팀, 담당자, 팩스, 전화]
        if len(row) >= 2 and re.fullmatch(r"\d+", row[0]):
            buyer = row[1]
            if buyer and buyer not in {"수요기관", "부서명"}:
                return buyer

    return fallback


def buyer_from_purchase_items_table(tables: list[dict]) -> str:
    rows = section_table_rows(tables, ["구매대상물품", "세부품명번호", "납품장소"])
    header: list[str] = []
    for row in rows:
        cells = [clean_cell(c) for c in row if clean_cell(c)]
        if not cells:
            continue
        joined = " ".join(cells)
        if "수요기관" in joined and ("세부품명" in joined or "납품장소" in joined):
            header = cells
            continue
        if header and cells and re.fullmatch(r"\d+", cells[0] or ""):
            for idx, h in enumerate(header):
                if "수요기관" in h and idx < len(cells):
                    val = clean_cell(cells[idx])
                    if val and val not in {"수요기관", "세부품명", "단위", "수량"} and not re.fullmatch(r"\d+", val):
                        return val
            if len(cells) >= 3:
                val = clean_cell(cells[2])
                if val and val not in {"수요기관", "세부품명", "단위", "수량"} and not re.fullmatch(r"\d+", val):
                    return val
    return ""


def extract_classification_from_allowed_industry_table(tables: list[dict]) -> str:
    """
    Classification must come from 투찰가능한업종.
    Screenshot:
      투찰가능한업종
      의료기기판매업(5312)
      의료기기판매업(5312)
    """
    values: list[str] = []
    seen: set[str] = set()

    rows = section_table_rows(tables, ["투찰가능한업종", "허용업종"])
    for row in rows:
        joined = " ".join(row)
        if "투찰가능한업종" in joined or "허용업종" in joined or joined == "No":
            continue

        for cell in row:
            cell = clean_cell(cell)
            if re.search(r"\(\d{4}\)", cell) and cell not in seen:
                seen.add(cell)
                values.append(cell)

    return " | ".join(values)


def extract_budget_only(kv: dict[str, str], detail_text: str) -> tuple[str, str]:
    """
    Amount must come from 배정예산 only.
    Handles table form:
      배정예산 | 198,100,000 원
    """
    val = kv_pick(kv, "배정예산")
    if val and "원" in val:
        cur, amt = extract_money(val)
        if amt:
            return cur, amt

    m = re.search(r"배정예산\s*([0-9][0-9,]*(?:\.\d+)?)\s*원", detail_text)
    if m:
        return "KRW", m.group(1)

    return "", ""


def extract_items_from_purchase_section(tables: list[dict]) -> list[dict]:
    """
    Extract item data from 구매대상물품 only.

    The G2B WebSquare grid often exports rows like:
    header row 1: No | 분류 | 수요기관 | 세부품명 | 납품일수 | 납품장소
    header row 2:    |    | 수량 | 단위 | 추정단가(원) | 세부품명번호 | 물품식별번호 | 규격 | 납품기한 | 인도조건
    data row 1:   1 | 1 | 경남대학교 | 교육훈련장비 | 0 | 학내 지정장소
    data row 2:        10 | set | [unit price] | 6010999901 | ... | 규격서 참고 | 2025/02/20 | 현장설치도
    """
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    rows = section_table_rows(tables, ["구매대상물품", "세부품명번호", "납품장소"])
    cleaned = []
    for row in rows:
        cells = [clean_cell(c) for c in row if clean_cell(c)]
        joined = " ".join(cells)
        if not cells:
            continue
        if any(x in joined for x in [
            "구매대상물품", "수요기관 세부품명", "세부품명번호",
            "물품식별번호", "납품일수", "납품장소", "인도조건",
            "전체", "Grid start", "Grid end"
        ]):
            continue
        cleaned.append(cells)

    i = 0
    while i < len(cleaned):
        row1 = cleaned[i]
        row2 = cleaned[i + 1] if i + 1 < len(cleaned) else []

        # Top data row usually starts with item no and classification no.
        if len(row1) >= 4 and re.fullmatch(r"\d+", row1[0] or ""):
            item_no = row1[0]

            # row1 has: No, 분류, 수요기관, 세부품명, 납품일수, 납품장소
            item_description = row1[3] if len(row1) > 3 else ""
            if item_description in {"", "-", "0"}:
                item_description = ""

            item_quantity = ""
            item_uom = ""
            item_unit_price = ""
            item_awarded_value = ""

            if row2:
                # row2 has: 수량, 단위, 추정단가(원), 세부품명번호, 물품식별번호, 규격, 납품기한, 인도조건
                if len(row2) >= 1:
                    item_quantity = row2[0]
                if len(row2) >= 2:
                    item_uom = row2[1]
                if len(row2) >= 3:
                    item_unit_price = row2[2]
                    if item_unit_price in {"-", "0"}:
                        item_unit_price = ""

            # If WebSquare extraction shifts columns, fallback search.
            if not item_quantity:
                for c in row2:
                    if re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", c):
                        item_quantity = c
                        break
            if not item_uom:
                for c in row2:
                    if c.lower() in {"set", "ea", "개", "식", "대", "건"}:
                        item_uom = c
                        break

            key = (item_no, item_description, item_quantity)
            if key not in seen:
                seen.add(key)
                items.append({
                    "item_no": item_no,
                    "item_description": item_description,
                    "item_uom": item_uom,
                    "item_quantity": item_quantity,
                    "item_unit_price": item_unit_price,
                    "item_awarded_value": item_awarded_value,
                })

            i += 2 if row2 else 1
            continue

        i += 1

    return items



def get_section_rows_v20(tables: list[dict], keyword: str) -> list[list[str]]:
    out = []
    for table in tables or []:
        rows = table.get("rows", []) or []
        caption = str(table.get("caption", "") or "")
        headers = " ".join(map(str, table.get("headers", []) or []))
        row_text = " ".join(" ".join(map(str, r)) for r in rows)
        t = f"{caption} {headers} {row_text}".strip()
        if keyword in t:
            for row in rows:
                cells = [clean_cell(c) for c in row if clean_cell(c)]
                if cells:
                    out.append(cells)
    return out


def kv_section_v20(tables: list[dict], keyword: str) -> dict[str, str]:
    kv = {}
    for row in get_section_rows_v20(tables, keyword):
        joined = " ".join(row)
        if keyword in joined and len(row) <= 2:
            continue
        if len(row) >= 4:
            pairs = [(row[0], row[1]), (row[2], row[3])]
        elif len(row) >= 2:
            pairs = [(row[0], row[1])]
        else:
            pairs = []
        for k, v in pairs:
            k = clean_cell(k).replace(" ", "")
            v = clean_cell(v)
            if k and v and len(k) <= 45 and k not in {"No", "순번", "번호", "전체"}:
                kv.setdefault(k, v)
    return kv


def contact_value_v20(tables: list[dict], section: str, col: str) -> str:
    rows = get_section_rows_v20(tables, section)
    header = []
    for row in rows:
        if col in " ".join(row):
            header = row
            continue
        if header and row and re.fullmatch(r"\d+", row[0] or ""):
            for i, h in enumerate(header):
                if col in h and i < len(row):
                    return clean_cell(row[i])
            if len(row) >= 2:
                return clean_cell(row[1])
    return ""


def process_date_v20(tables: list[dict], name: str, last: bool = True) -> str:
    rows = get_section_rows_v20(tables, "입찰진행정보")
    for row in rows:
        joined = " ".join(row)
        if name not in joined:
            continue
        dates = re.findall(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}(?::\d{2})?", joined)
        if dates:
            return dates[-1] if last else dates[0]
    return ""


def awarded_date_from_opening_datetime(tables: list[dict]) -> str:
    rows = get_section_rows_v20(tables, "입찰진행현황")
    header: list[str] = []
    for row in rows:
        cells = [clean_cell(c) for c in row if clean_cell(c)]
        joined = " ".join(cells)
        if not cells:
            continue
        if "개찰일시" in joined and ("공고명" in joined or "진행현황" in joined or "순번" in joined):
            header = cells
            continue
        if header and cells and re.fullmatch(r"\d+", cells[0] or ""):
            for idx, h in enumerate(header):
                if "개찰일시" in h and idx < len(cells):
                    val = clean_cell(cells[idx])
                    if re.search(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}(?::\d{2})?", val):
                        return val
            for cell in cells:
                cell = clean_cell(cell)
                if re.search(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}(?::\d{2})?", cell):
                    return cell
    return ""


def allowed_industries_v20(tables: list[dict]) -> str:
    """
    Classification = 투찰가능한업종 values only.
    """
    vals, seen = [], set()

    for table in tables or []:
        rows = table.get("rows", []) or []
        table_text = " ".join(" ".join(map(str, r)) for r in rows)

        if "투찰가능한업종" not in table_text:
            continue

        for row in rows:
            cells = [clean_cell(c) for c in row if clean_cell(c)]
            joined = " ".join(cells)

            if not cells:
                continue

            if (
                "투찰가능한업종" in joined
                or "허용업종" in joined
                or "업종제한사항" in joined
                or "업종제한" in joined
                or "지역제한" in joined
                or "안내" in joined
                or joined == "No"
            ):
                continue

            for c in cells:
                c = clean_cell(c)
                if re.search(r"\(\d{4}\)", c) and c not in seen:
                    seen.add(c)
                    vals.append(c)

    return " | ".join(vals)



def all_detail_kv_v21(tables: list[dict]) -> dict[str, str]:
    """
    Build label/value pairs across all visible detail tables.

    Needed by:
      - budget_amount_v21()
      - agency_supplier_v21()
      - buyer_v21()

    Handles rows like:
      [label, value]
      [label, value, label, value]
    """
    kv: dict[str, str] = {}

    bad_labels = {
        "No", "번호", "순번", "전체",
        "문서구분", "파일명", "파일크기",
        "진행명", "진행방법", "시작일시", "종료일시", "장소",
        "수량", "단위", "추정단가(원)", "세부품명번호",
        "물품식별번호", "규격", "납품기한", "인도조건",
    }

    def add(k: str, v: str) -> None:
        k = clean_cell(k).replace(" ", "")
        v = clean_cell(v)

        if not k or not v:
            return
        if len(k) > 45:
            return
        if k in bad_labels:
            return
        if k not in kv:
            kv[k] = v

    for table in tables or []:
        for row in table.get("rows", []) or []:
            cells = [clean_cell(c) for c in row if clean_cell(c)]

            if len(cells) >= 4:
                add(cells[0], cells[1])
                add(cells[2], cells[3])
            elif len(cells) >= 2:
                add(cells[0], cells[1])

    return kv


def budget_amount_v21(tables: list[dict], detail_text: str) -> tuple[str, str]:
    """
    Extract amount from 배정예산.

    G2B/WebSquare sometimes extracts the 가격 table in odd shapes:
      [배정예산, 198,100,000 원]
      [추정가격, 180,090,909 원, 배정예산, 198,100,000 원]
      or the label/value appears only in bodyText.

    This function is anchored to 배정예산 so it will not accidentally capture dates.
    """
    def clean_money(raw: str) -> tuple[str, str]:
        raw = compact(raw)
        if not raw:
            return "", ""

        # Normalize Korean Won formats.
        # Examples: "198,100,000 원", "198,100,000원", "₩198,100,000"
        patterns = [
            r"([0-9][0-9,]*(?:\.\d+)?)\s*(?:원|KRW|₩)",
            r"(?:원|KRW|₩)\s*([0-9][0-9,]*(?:\.\d+)?)",
        ]
        for pat in patterns:
            m = re.search(pat, raw, re.I)
            if m:
                return "KRW", m.group(1)
        return "", ""

    # 1) Direct KV extraction across all tables.
    kv_all = all_detail_kv_v21(tables)
    for key in ["배정예산", "배정 예산"]:
        budget = kv_pick(kv_all, key)
        cur, amt = clean_money(budget)
        if amt:
            return cur, amt

    # 2) Scan every row/cell. If a cell contains 배정예산, check following cells and row text.
    for table in tables or []:
        for row in table.get("rows", []) or []:
            cells = [clean_cell(c) for c in row if clean_cell(c)]
            if not cells:
                continue

            joined = " ".join(cells)

            if "배정예산" not in joined:
                continue

            # 2a) If same row text has the money after 배정예산.
            tail = joined.split("배정예산", 1)[1]
            cur, amt = clean_money(tail)
            if amt:
                return cur, amt

            # 2b) If label and value are separate cells.
            for i, cell in enumerate(cells):
                if "배정예산" not in cell:
                    continue

                # Usually the next visible cell is the value.
                for nxt in cells[i + 1:i + 5]:
                    cur, amt = clean_money(nxt)
                    if amt:
                        return cur, amt

    # 3) Body text fallback, still anchored to 배정예산.
    clean_text = compact(detail_text)

    patterns = [
        r"배정예산\s*[:：]?\s*([0-9][0-9,]*(?:\.\d+)?)\s*원",
        r"배정예산\s+([0-9][0-9,]*(?:\.\d+)?)\s*원",
        r"배정\s*예산\s*[:：]?\s*([0-9][0-9,]*(?:\.\d+)?)\s*원",
    ]

    for pat in patterns:
        m = re.search(pat, clean_text)
        if m:
            return "KRW", m.group(1)

    # 4) Last anchored fallback: take the first Won amount within 80 chars after 배정예산.
    idx = clean_text.find("배정예산")
    if idx != -1:
        window = clean_text[idx:idx + 120]
        cur, amt = clean_money(window)
        if amt:
            return cur, amt

    return "", ""


def agency_supplier_v21(tables: list[dict], detail_text: str) -> str:
    kv_all = all_detail_kv_v21(tables)
    supplier = kv_pick(kv_all, "공고기관")
    if supplier:
        return supplier

    m = re.search(
        r"공고기관\s*[:：]?\s*([^\n\r]+?)(?=\s+(?:공고담당자|집행관|수요기관|입찰공고번호|공고명|게시일시|참조번호)|$)",
        detail_text,
    )
    if m:
        return clean_cell(m.group(1))

    return ""


def section_label_value_v33(tables: list[dict], section: str, label: str) -> str:
    """
    Read a label/value from a named tender-detail section.

    Handles these G2B/WebSquare extraction shapes:
      [공고기관, 충북대학교병원, 공고담당자, 홍**]
      [No, 공고기관, 공고담당자, 집행관, ...] then [1, 충북대학교병원, 홍**, ...]
      [기관담당자정보, No, 공고기관, 공고담당자, ..., 1, 충북대학교병원, 홍**, ...]
    """
    rows = get_section_rows_v20(tables, section)
    if not rows:
        return ""

    label_norm = label.replace(" ", "")
    section_norm = section.replace(" ", "")
    stop_labels = {
        "공고기관", "공고담당자", "집행관", "수요기관", "부서명",
        "담당자", "전화번호", "팩스번호", "입찰공고번호", "공고명", "게시일시",
        "No", "번호", "순번", "기관담당자정보", "기관담당자정보목록",
    }
    stop_norm = {x.replace(" ", "") for x in stop_labels}

    def good_value(value: str) -> str:
        value = clean_cell(value)
        if not value:
            return ""
        if value.replace(" ", "") in stop_norm:
            return ""
        if "담당자" in value or value in {"-", "*", "**"}:
            return ""
        return value

    header: list[str] = []

    for row in rows:
        cells = [clean_cell(c) for c in row if clean_cell(c)]
        if not cells:
            continue

        # Shape: one flattened row contains section name + headers + data.
        # Example: [기관담당자정보, No, 공고기관, 공고담당자, 집행관, 팩스번호, 전화번호, 1, 충북대학교병원, 윤**, ...]
        label_indexes = [i for i, c in enumerate(cells) if c.replace(" ", "") == label_norm]
        for label_idx in label_indexes:
            data_start = None
            for j in range(label_idx + 1, len(cells)):
                if re.fullmatch(r"\d+", cells[j]):
                    data_start = j
                    break
            if data_start is not None:
                header_start = 0
                for j in range(label_idx - 1, -1, -1):
                    c_norm = cells[j].replace(" ", "")
                    if c_norm == "No" or c_norm == section_norm or c_norm.endswith("목록"):
                        header_start = j
                        break
                local_header = cells[header_start:data_start]
                local_data = cells[data_start:data_start + len(local_header)]
                for idx, h in enumerate(local_header):
                    if h.replace(" ", "") == label_norm and idx < len(local_data):
                        value = good_value(local_data[idx])
                        if value:
                            return value

        # Pair layout: [label, value, label, value]. Only accept if the next cell is not another header label.
        for i, cell in enumerate(cells[:-1]):
            if cell.replace(" ", "") == label_norm:
                value = good_value(cells[i + 1])
                if value:
                    return value

        # Header + next-row data layout.
        if any(label_norm == c.replace(" ", "") for c in cells):
            header = cells
            continue

        if header:
            for idx, h in enumerate(header):
                if label_norm == h.replace(" ", "") and idx < len(cells):
                    value = good_value(cells[idx])
                    if value:
                        return value

    return ""


def buyer_from_tender_notice_agency(tables: list[dict], detail_text: str) -> str:
    """
    Buyer must be the value of the tender detail page column/label:
      기관담당자정보 > 공고기관

    Example: 공고기관 = 충북대학교병원.
    Never return 공고담당자 for buyer and do not use listing-page fallback.
    """
    # Best source: exact label/value in 기관담당자정보. This prevents returning 공고담당자.
    buyer = section_label_value_v33(tables, "기관담당자정보", "공고기관")
    if buyer:
        return buyer

    # Secondary structured section fallback.
    buyer = contact_value_v20(tables, "기관담당자정보", "공고기관")
    if buyer and "담당자" not in buyer:
        return clean_cell(buyer)

    # Fallback within tender detail page only.
    general_kv = kv_section_v20(tables, "공고일반")
    buyer = kv_pick(general_kv, "공고기관")
    if buyer and "담당자" not in buyer:
        return clean_cell(buyer)

    kv_all = all_detail_kv_v21(tables)
    buyer = kv_pick(kv_all, "공고기관")
    if buyer and "담당자" not in buyer:
        return clean_cell(buyer)

    # Detail text table fallback for flattened text.
    # Example text: 기관담당자정보 목록 No 공고기관 공고담당자 집행관 팩스번호 전화번호 1 충북대학교병원 윤** ...
    clean_text = compact(detail_text)
    m = re.search(
        r"기관담당자정보(?:\s*목록)?\s+No\s+공고기관\s+공고담당자(?:\s+집행관)?(?:\s+팩스번호)?(?:\s+전화번호)?\s+\d+\s+(.+?)(?=\s+[^\s]*\*{1,}|\s+\d{2,4}[-) ]|\s+\d{2,3}-\d{3,4}-\d{4}|$)",
        clean_text,
        re.S,
    )
    if m:
        value = clean_cell(m.group(1))
        if value and "담당자" not in value and len(value) <= 120:
            return value

    # Last generic detail-text fallback anchored to 공고기관 and stopped before 공고담당자.
    m = re.search(
        r"공고기관\s*[:：]?\s*(.*?)(?=\s+(?:공고담당자|집행관|수요기관|입찰공고번호|공고명|게시일시|참조번호)\s*[:：]?|$)",
        clean_text,
        re.S,
    )
    if m:
        value = clean_cell(m.group(1))
        if value and "담당자" not in value and value.replace(" ", "") != "공고담당자" and len(value) <= 120:
            return value

    return ""


def buyer_v21(tables: list[dict], detail_text: str, fallback: str = "") -> str:
    buyer = contact_value_v20(tables, "수요기관담당자정보", "수요기관")
    if buyer:
        return buyer

    kv_all = all_detail_kv_v21(tables)
    buyer = kv_pick(kv_all, "수요기관")
    if buyer:
        return buyer

    return fallback


def purchase_items_v21(tables: list[dict]) -> list[dict]:
    """
    Extract 구매대상물품 correctly.

    item_quantity = 수량
    item_uom = 단위
    item_unit_price = 추정단가(원), blank when empty
    contract period support = 납품일수 / 납품기한
    """
    def clean_row_keep_positions(row: list) -> list[str]:
        return [clean_cell(c) for c in (row or [])]

    def row_join(row: list[str]) -> str:
        return " ".join(c for c in row if c)

    def looks_like_number(v: str) -> bool:
        return bool(re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", clean_cell(v)))

    def looks_like_unit(v: str) -> bool:
        v = clean_cell(v).lower()
        return v in {
            "set", "ea", "box", "lot", "unit", "pack",
            "개", "식", "대", "건", "조", "매", "병", "통", "박스", "세트",
            "ceremony"
        }

    def column_index(header: list[str], *needles: str) -> int:
        for idx, cell in enumerate(header):
            text = clean_cell(cell)
            if any(needle in text for needle in needles):
                return idx
        return -1

    items: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for table in tables or []:
        raw_rows = table.get("rows", []) or []
        caption = clean_cell(str(table.get("caption", "") or ""))
        headers = [clean_cell(h) for h in (table.get("headers", []) or [])]
        table_text = " ".join(
            [caption, " ".join(headers)]
            + [row_join(clean_row_keep_positions(r)) for r in raw_rows]
        )
        if "구매대상물품" not in table_text and not ("세부품명번호" in table_text and "수량" in table_text and "단위" in table_text):
            continue

        rows = [clean_row_keep_positions(r) for r in raw_rows]
        top_header_idx = -1
        sub_header_idx = -1
        for idx, row in enumerate(rows):
            joined = row_join(row)
            if "세부품명" in joined and "수요기관" in joined and "No" in joined:
                top_header_idx = idx
            if "수량" in joined and "단위" in joined and ("추정단가" in joined or "Estimated" in joined):
                sub_header_idx = idx
                break

        if top_header_idx == -1 or sub_header_idx == -1:
            continue

        top_header = rows[top_header_idx]
        sub_header = rows[sub_header_idx]

        desc_idx = column_index(top_header, "세부품명")
        delivery_days_idx = column_index(top_header, "납품일수")
        qty_idx = column_index(sub_header, "수량")
        uom_idx = column_index(sub_header, "단위")
        unit_price_idx = column_index(sub_header, "추정단가", "예정단가", "Estimated")
        deadline_idx = column_index(sub_header, "납품기한")

        i = sub_header_idx + 1
        while i < len(rows):
            row1 = rows[i]
            row1_joined = row_join(row1)
            if not row1_joined:
                i += 1
                continue
            if any(x in row1_joined for x in ["전체", "데이터 없음", "구매대상물품"]):
                i += 1
                continue
            if "입찰진행현황" in row1_joined or "파일첨부" in row1_joined:
                break
            if not row1 or not re.fullmatch(r"\d+", clean_cell(row1[0] if len(row1) > 0 else "")):
                i += 1
                continue

            row2 = rows[i + 1] if i + 1 < len(rows) else []
            if row2 and row_join(row2):
                next_first = clean_cell(row2[0] if len(row2) > 0 else "")
                next_joined = row_join(row2)
                next_desc = clean_cell(row2[desc_idx]) if desc_idx >= 0 and desc_idx < len(row2) else ""
                next_uom = clean_cell(row2[uom_idx]) if uom_idx >= 0 and uom_idx < len(row2) else ""
                next_has_unit = bool(next_uom and looks_like_unit(next_uom)) or any(looks_like_unit(c) for c in row2)
                next_has_money = any(
                    re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:,\d+)*(?:\.\d+)?", clean_cell(c))
                    and not re.fullmatch(r"\d{8,12}", clean_cell(c).replace(",", ""))
                    for c in row2
                )
                next_looks_detail = bool(re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", next_first)) and (next_has_unit or next_has_money)
                next_looks_new_item = bool(re.fullmatch(r"\d+", next_first)) and bool(next_desc) and not looks_like_number(next_desc)
                if next_looks_new_item and not next_looks_detail:
                    row2 = []

            item_no = clean_cell(row1[0] if len(row1) > 0 else "")
            item_description = clean_cell(row1[desc_idx]) if desc_idx >= 0 and desc_idx < len(row1) else ""
            delivery_days = clean_cell(row1[delivery_days_idx]) if delivery_days_idx >= 0 and delivery_days_idx < len(row1) else ""
            if delivery_days and not looks_like_number(delivery_days):
                delivery_days = ""

            item_quantity = ""
            item_uom = ""
            item_unit_price = ""
            delivery_deadline = ""

            if row2:
                if qty_idx >= 0 and qty_idx < len(row2):
                    candidate = clean_cell(row2[qty_idx])
                    if candidate and looks_like_number(candidate) and not re.fullmatch(r"\d{8,12}", candidate.replace(",", "")):
                        item_quantity = candidate

                if uom_idx >= 0 and uom_idx < len(row2):
                    candidate = clean_cell(row2[uom_idx])
                    if candidate and not looks_like_number(candidate) and not re.fullmatch(r"\d{8,12}", candidate.replace(",", "")):
                        item_uom = candidate

                if unit_price_idx >= 0 and unit_price_idx < len(row2):
                    candidate = clean_cell(row2[unit_price_idx])
                    if candidate not in {"", "-", "0"} and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:,\d+)*(?:\.\d+)?", candidate):
                        if not re.fullmatch(r"\d{8,12}", candidate.replace(",", "")):
                            item_unit_price = candidate

                if deadline_idx >= 0 and deadline_idx < len(row2):
                    candidate = clean_cell(row2[deadline_idx])
                    if re.search(r"\d{4}/\d{2}/\d{2}", candidate):
                        delivery_deadline = candidate

                if not item_quantity:
                    for c in row2:
                        c_clean = clean_cell(c)
                        if looks_like_number(c_clean) and not re.fullmatch(r"\d{8,12}", c_clean.replace(",", "")):
                            item_quantity = c_clean
                            break

                if not item_uom:
                    for c in row2:
                        c_clean = clean_cell(c)
                        if looks_like_unit(c_clean):
                            item_uom = c_clean
                            break

                if not item_unit_price:
                    for c in row2:
                        c_clean = clean_cell(c)
                        if c_clean in {"", "-", "0", item_quantity, item_uom}:
                            continue
                        if re.fullmatch(r"\d{8,12}", c_clean.replace(",", "")):
                            continue
                        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:,\d+)*(?:\.\d+)?", c_clean):
                            item_unit_price = c_clean
                            break

            key = (item_no, item_description, item_quantity, item_uom)
            if item_no and key not in seen:
                seen.add(key)
                items.append({
                    "item_no": item_no,
                    "item_description": item_description,
                    "item_uom": item_uom,
                    "item_quantity": item_quantity,
                    "item_unit_price": item_unit_price,
                    "item_awarded_value": "",
                    "_delivery_days": delivery_days,
                    "_delivery_deadline": delivery_deadline,
                })

            i += 2 if row2 else 1

    return items


def enrich_items_from_fallback(primary_items: list[dict], fallback_items: list[dict]) -> list[dict]:
    if not primary_items:
        return fallback_items or []
    if not fallback_items:
        return primary_items

    by_no: dict[str, dict] = {}
    for item in fallback_items:
        item_no = clean_cell(item.get("item_no", ""))
        if item_no and item_no not in by_no:
            by_no[item_no] = item

    merged: list[dict] = []
    for item in primary_items:
        item_no = clean_cell(item.get("item_no", ""))
        fb = by_no.get(item_no, {})
        merged.append({
            **item,
            "item_description": item.get("item_description") or fb.get("item_description", ""),
            "item_uom": item.get("item_uom") or fb.get("item_uom", ""),
            "item_quantity": item.get("item_quantity") or fb.get("item_quantity", ""),
            "item_unit_price": item.get("item_unit_price") or fb.get("item_unit_price", ""),
            "item_awarded_value": item.get("item_awarded_value") or fb.get("item_awarded_value", ""),
            "_delivery_days": item.get("_delivery_days") or fb.get("_delivery_days", ""),
            "_delivery_deadline": item.get("_delivery_deadline") or fb.get("_delivery_deadline", ""),
        })
    return merged


def last_resort_fill_item_qty_uom(items: list[dict], tables: list[dict]) -> list[dict]:
    if not items:
        return items

    purchase_rows = get_section_rows_v20(tables, "구매대상물품")
    cleaned_rows = []
    for row in purchase_rows:
        cells = [clean_cell(c) for c in row if clean_cell(c)]
        joined = " ".join(cells)
        if not cells:
            continue
        if any(x in joined for x in ["구매대상물품", "세부품명번호", "물품식별번호", "납품장소", "인도조건", "전체", "Grid"]):
            continue
        cleaned_rows.append(cells)

    row_map: dict[str, list[str]] = {}
    for row in cleaned_rows:
        if row and re.fullmatch(r"\d+", row[0] or ""):
            row_map[clean_cell(row[0])] = row

    def looks_like_unit(v: str) -> bool:
        v = clean_cell(v).lower()
        return v in {"set", "ea", "box", "lot", "unit", "pack", "개", "식", "대", "건", "조", "매", "병", "통", "박스", "세트"}

    def looks_like_number(v: str) -> bool:
        return bool(re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", clean_cell(v)))

    out: list[dict] = []
    for item in items:
        if item.get("item_quantity") and item.get("item_uom"):
            out.append(item)
            continue

        row = row_map.get(clean_cell(item.get("item_no", "")), [])
        qty = item.get("item_quantity", "")
        uom = item.get("item_uom", "")

        if row and not qty:
            for c in row[1:]:
                c_clean = clean_cell(c)
                if looks_like_number(c_clean) and not re.fullmatch(r"\d{8,12}", c_clean.replace(",", "")):
                    qty = c_clean
                    break

        if row and not uom:
            for c in row[1:]:
                if looks_like_unit(c):
                    uom = clean_cell(c)
                    break

        out.append({
            **item,
            "item_quantity": qty,
            "item_uom": uom,
        })

    return out


def contract_period_from_items_v21(items: list[dict]) -> str:
    """
    Contract period = 납품일수 where available; otherwise 납품기한.
    """
    if not items:
        return ""

    first = items[0]
    days = compact(str(first.get("_delivery_days", "")))
    deadline = compact(str(first.get("_delivery_deadline", "")))

    if days:
        return f"{days} days"
    if deadline:
        return deadline
    return ""


def notice_url_v21(notice_id: str, row_href: str = "") -> str:
    row_href = compact(row_href)
    notice_id = compact(notice_id)

    if row_href and row_href not in {"#", "javascript:void(0)", "javascript:;"}:
        return row_href

    if notice_id:
        return f"https://www.g2b.go.kr/?searchText={notice_id}"

    return "https://www.g2b.go.kr/"



def buyer_from_detail_v32(tables: list[dict], detail_text: str, row_text: str = "", title: str = "") -> str:
    """
    Buyer extraction priority:
      1. 수요기관담당자정보 table -> 수요기관 column
      2. 구매대상물품 table -> 수요기관 column
      3. Any detail table label/value -> 수요기관
      4. Regex from body text near 수요기관
      5. Listing row fallback
    """
    # 1) Dedicated 담당자정보 grid/table.
    try:
        rows = section_table_rows(tables, ["수요기관담당자정보", "수요기관담당자정보 목록"])
        header = []
        for row in rows:
            cells = [clean_cell(c) for c in row if clean_cell(c)]
            joined = " ".join(cells)
            if not cells:
                continue

            if "수요기관" in joined and ("부서명" in joined or "담당자" in joined):
                header = cells
                continue

            if header and cells and re.fullmatch(r"\d+", cells[0] or ""):
                for idx, h in enumerate(header):
                    if "수요기관" in h and idx < len(cells):
                        val = clean_cell(cells[idx])
                        if val and val not in {"수요기관", "부서명", "담당자"}:
                            return val

                if len(cells) >= 2:
                    val = clean_cell(cells[1])
                    if val and val not in {"수요기관", "부서명", "담당자"}:
                        return val
    except Exception:
        pass

    # 2) Purchase-items table fallback.
    try:
        val = buyer_from_purchase_items_table(tables)
        if val:
            return val
    except Exception:
        pass

    # 3) Generic key/value extraction from all detail tables.
    try:
        kv_all = all_detail_kv_v21(tables)
        val = kv_pick(kv_all, "수요기관")
        if val:
            val = clean_cell(val)
            if val not in {"세부품명", "수량", "단위", "납품장소", "납품일수"} and not re.fullmatch(r"\d+", val):
                return val
    except Exception:
        pass

    # 4) Body text fallback anchored around label.
    try:
        clean = compact(detail_text)
        m = re.search(
            r"수요기관\s*[:：]?\s*(.*?)(?=\s+(?:부서명|담당자|전화번호|팩스번호|공고기관|공고담당자|입찰공고번호|공고명|게시일시)\s*[:：]?|$)",
            clean,
            re.S,
        )
        if m:
            val = clean_cell(m.group(1))
            val = re.split(r"\s{2,}| 담당자 | 부서명 ", val)[0].strip()
            if val and val not in {"세부품명", "수량", "단위"} and len(val) <= 80:
                return val
    except Exception:
        pass

    # 5) Listing row fallback.
    return listing_buyer(row_text, title)


def listing_notice_agency(row_text: str, title: str) -> str:
    """
    Extract buyer from listing page column 공고기관 for the corresponding row.

    Listing row layout is usually:
      No | 업무 | 구분 | 공고번호 | 공고명 | 공고기관 | 수요기관 | 게시일시 | ...
    We need 공고기관, which is the organization immediately after 공고명.
    """
    row_text = compact(row_text)
    title = compact(title)

    if not row_text or not title or title not in row_text:
        return ""

    after_title = compact(row_text.split(title, 1)[1])

    # Stop before first date; agency columns appear before dates.
    m_date = re.search(r"\d{4}/\d{2}/\d{2}", after_title)
    if m_date:
        org_part = compact(after_title[:m_date.start()])
    else:
        org_part = after_title

    if not org_part:
        return ""

    tokens = org_part.split()

    # Common case: 공고기관 and 수요기관 are same and therefore duplicated.
    # Example: "경남대학교 경남대학교"
    if len(tokens) >= 2 and len(tokens) % 2 == 0:
        left = " ".join(tokens[: len(tokens) // 2])
        right = " ".join(tokens[len(tokens) // 2 :])
        if left == right:
            return left

    # If different, 공고기관 is first org/name segment.
    return tokens[0] if tokens else org_part


def build_records(row: TenderRow, payload: dict, query_text: str, translate_en: bool = False, supplier_override: str = '', amount_override: str = '') -> List[TenderDetail]:
    detail_text = compact(str(payload.get("bodyText", "")))
    tables = payload.get("tables", []) or []

    general_kv = kv_section_v20(tables, "공고일반")
    row_pub, row_close = listing_dates(row.row_text)
    row_notice_id = normalize_notice_id(row.row_text)

    notice_id = normalize_notice_id(kv_pick(general_kv, "입찰공고번호", "공고번호")) or row_notice_id
    notice_url = notice_url_v21(notice_id, row.href)

    title = kv_pick(general_kv, "공고명") or row.title
    publication_date = kv_pick(general_kv, "게시일시", "게시일자") or process_date_v20(tables, "공고게시", False) or row_pub
    closing_date = process_date_v20(tables, "입찰서제출", True) or row_close

    buyer = buyer_from_detail_v32(tables, detail_text, row.row_text, title)
    if not buyer:
        buyer = buyer_from_tender_notice_agency(tables, detail_text)
    supplier_name = compact(supplier_override)
    awarding_agency_name = buyer
    classification = allowed_industries_v20(tables)

    # Amount priority:
    # 1. supplier page 입찰금액(원), if supplier page exists and amount was extracted
    # 2. tender page 가격 > 배정예산
    if amount_override:
        m = re.search(r"([0-9][0-9,]*(?:\.\d+)?)", compact(amount_override))
        currency, amount = "KRW", m.group(1) if m else compact(amount_override)
    else:
        currency, amount = budget_amount_v21(tables, detail_text)

    awarded_value_detail = amount
    _, _, opening_date = extract_bid_process_dates(tables)
    awarded_date = (
        awarded_date_from_opening_datetime(tables)
        or opening_date
        or process_date_v20(tables, "개찰", True)
    )

    item_rows = purchase_items_v21(tables)
    item_rows = enrich_items_from_fallback(item_rows, extract_purchase_items(tables))
    item_rows = last_resort_fill_item_qty_uom(item_rows, tables)
    if not item_rows:
        item_rows = [{"item_no": "", "item_description": "", "item_uom": "", "item_quantity": "", "item_unit_price": "", "item_awarded_value": ""}]

    contract_period = contract_period_from_items_v21(item_rows) or kv_pick(general_kv, "계약기간", "납품기한", "이행기간")

    records: List[TenderDetail] = []
    seen_items = set()

    for item in item_rows:
        item_key = (clean_cell(item.get("item_no", "")), clean_cell(item.get("item_description", "")), clean_cell(item.get("item_quantity", "")))
        if item_key in seen_items:
            continue
        seen_items.add(item_key)

        base = {
            "source": "G2B",
            "country": "South Korea",
            "country_code": "KR",
            "publication_date": publication_date,
            "closing_date": closing_date,
            "title": title,
            "buyer": buyer,
            "classification": classification,
            "status": "진행완료",
            "currency": currency,
            "amount": amount,
            "awarding_agency_name": awarding_agency_name,
            "supplier_name": supplier_name,
            "awarded_date": awarded_date,
            "awarded_value_detail": awarded_value_detail,
            "contract_period": contract_period,
            "item_no": item.get("item_no", ""),
            "item_description": item.get("item_description", ""),
            "item_uom": item.get("item_uom", ""),
            "item_quantity": item.get("item_quantity", ""),
            "item_unit_price": item.get("item_unit_price", ""),
            "item_awarded_value": item.get("item_awarded_value", ""),
            "notice_id": notice_id,
            "notice_url": notice_url,
            "query_text": query_text,
            "scraped_at_utc": utc_now(),
            "dedup_key": make_dedup_key(notice_id, title, item.get("item_no", "")),
        }

        base = make_english_columns(base, translate_en)

        records.append(TenderDetail(
            source=base["source"],
            country=base["country"],
            country_code=base["country_code"],
            publication_date=base["publication_date"],
            closing_date=base["closing_date"],
            title=base["title"],
            title_en=base["title_en"],
            buyer=base["buyer"],
            buyer_en=base["buyer_en"],
            classification=base["classification"],
            classification_en=base["classification_en"],
            status=base["status"],
            status_en=base["status_en"],
            currency=base["currency"],
            amount=base["amount"],
            awarding_agency_name=base["awarding_agency_name"],
            awarding_agency_name_en=base["awarding_agency_name_en"],
            supplier_name=base["supplier_name"],
            supplier_name_en=base["supplier_name_en"],
            awarded_date=base["awarded_date"],
            awarded_value_detail=base["awarded_value_detail"],
            contract_period=base["contract_period"],
            item_no=base["item_no"],
            item_description=base["item_description"],
            item_description_en=base["item_description_en"],
            item_uom=base["item_uom"],
            item_quantity=base["item_quantity"],
            item_unit_price=base["item_unit_price"],
            item_awarded_value=base["item_awarded_value"],
            notice_id=base["notice_id"],
            notice_url=base["notice_url"],
            query_text=base["query_text"],
            scraped_at_utc=base["scraped_at_utc"],
            dedup_key=base["dedup_key"],
        ))

    return records


def extract_supplier_from_opening_result(page: Page, timeout_ms: int, args: argparse.Namespace | None = None) -> dict:
    """
    Supplier extraction:
      1. Click 개찰완료 in 입찰진행현황.
      2. Wait for 업체명 bidder result table.
      3. Extract 업체명.
      4. Return to tender detail page.
    """
    log("Extracting supplier via 개찰완료 …")

    try:
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(700)
    except Exception:
        pass

    clicked = bool(page.evaluate("""
    () => {
      const isVis = el => {
        if (!el) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' &&
               s.visibility !== 'hidden' &&
               r.width > 0 &&
               r.height > 0;
      };
      const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

      const clickEl = el => {
        el.scrollIntoView({block:'center', inline:'center'});
        const r = el.getBoundingClientRect();
        const opts = {bubbles:true, cancelable:true, view:window, clientX:r.left+r.width/2, clientY:r.top+r.height/2};
        el.dispatchEvent(new MouseEvent('mouseover', opts));
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));
        if (typeof el.click === 'function') el.click();
        return true;
      };

      const targets = Array.from(document.querySelectorAll('button,a,input[type=button],input[type=submit],span,div,td'))
        .filter(el => isVis(el) && norm(el.innerText || el.value || el.title || '') === '개찰완료')
        .sort((a,b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return br.y - ar.y || ar.x - br.x;
        });

      if (!targets.length) return false;
      const target = targets[0].closest('button,a,input[type=button],input[type=submit]') || targets[0];
      return clickEl(target);
    }
    """))

    if not clicked:
        if args is not None:
            debug_log(args, "개찰완료 not found.")
        return {"supplier_name": "", "bid_amount": ""}

    # Wait for bidder/result table to load.
    wait_for_loading_clear(page, timeout_ms)
    supplier_loaded = False
    for _ in range(90):
        page.wait_for_timeout(500)
        try:
            supplier_loaded = bool(page.evaluate("""
            () => {
              const txt = (document.body?.innerText || '').replace(/\\u00a0/g, ' ');
              return txt.includes('업체명') &&
                     (txt.includes('사업자등록번호') || txt.includes('입찰금액') || txt.includes('투찰률'));
            }
            """))
            if supplier_loaded:
                break
        except Exception:
            pass

    supplier = ""
    bid_amount = ""
    if supplier_loaded:
        try:
            supplier_payload = page.evaluate("""
            () => {
              const isVis = el => {
                if (!el) return false;
                const s = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' &&
                       s.visibility !== 'hidden' &&
                       r.width > 0 &&
                       r.height > 0;
              };
              const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

              const rows = Array.from(document.querySelectorAll('tr,[role=row],.w2grid_row,.w2grid_body_row')).filter(isVis);
              for (const row of rows) {
                const cells = Array.from(row.querySelectorAll('td,[role=gridcell],span,div'))
                  .filter(isVis)
                  .map(el => norm(el.innerText || el.value || ''))
                  .filter(Boolean);

                const joined = cells.join(' ');
                if (!joined) continue;
                if (joined.includes('업체명') && joined.includes('대표자명')) continue;

                for (let i = 0; i < cells.length - 1; i++) {
                  if (/\\d{3}-\\d{2}-\\d{5}/.test(cells[i])) {
                    const supplierName = cells[i + 1] || '';

                    let bidAmount = '';
                    for (let j = i + 2; j < cells.length; j++) {
                      const raw = cells[j] || '';
                      const normalized = raw.replace(/,/g, '').trim();

                      // 입찰금액(원): usually a comma-formatted large number like 34,888,000.
                      // Do not accept dates, percentages, or 추첨번호 values.
                      if (/^\\d{4,}$/.test(normalized) && raw.includes(',')) {
                        bidAmount = raw;
                        break;
                      }
                    }

                    return { supplier_name: supplierName, bid_amount: bidAmount };
                  }
                }
              }

              const txt = norm(document.body?.innerText || '');
              const m = txt.match(/\\d{3}-\\d{2}-\\d{5}\\s+(.+?)\\s+[^\\s]+\\s+([0-9][0-9,]*)/);
              return m ? { supplier_name: m[1], bid_amount: m[2] } : { supplier_name: '', bid_amount: '' };
            }
            """)
            supplier = compact((supplier_payload or {}).get("supplier_name", ""))
            bid_amount = compact((supplier_payload or {}).get("bid_amount", ""))
        except Exception as exc:
            if args is not None:
                debug_log(args, f"Supplier parse failed: {exc}")

    if supplier:
        log(f"Supplier extracted: {supplier}")
    if bid_amount:
        log(f"Supplier page bid amount extracted: {bid_amount}")
    else:
        log("Supplier not found from 개찰완료 result.")
        if args is not None:
            save_debug_screenshot(page, args, "supplier_not_found_after_opening_result")

    # Close supplier result popup/page and return to tender detail page.
    try:
        current_txt = page.locator("body").inner_text(timeout=3000)
    except Exception:
        current_txt = ""

    if "업체명" in current_txt and ("사업자등록번호" in current_txt or "입찰금액" in current_txt):
        close_supplier_popup(page, timeout_ms, args)

    return {"supplier_name": supplier, "bid_amount": bid_amount}

def close_supplier_popup(page, timeout_ms, args=None):
    """
    Close supplier/opening popup via 닫기 button.
    Returns True when the tender detail page is visible again.
    """

    print("[G2B] Closing supplier popup via 닫기 …")
    try:
        dismiss_code0_warning(page, pause_ms=1000)
    except Exception:
        pass

    try:
        page.evaluate("""
        () => {
            window.scrollTo(0, 0);
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollHeight > el.clientHeight) {
                    el.scrollTop = 0;
                }
            });
        }
        """)
        page.wait_for_timeout(500)
    except Exception:
        pass

    clicked = page.evaluate("""
    () => {
        const isVisible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        };

        const norm = v => (v || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();

        const fireClick = el => {
            el.scrollIntoView({ block: "center", inline: "center" });
            const r = el.getBoundingClientRect();
            const opts = {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: r.left + r.width / 2,
                clientY: r.top + r.height / 2
            };
            el.dispatchEvent(new MouseEvent('mouseover', opts));
            el.dispatchEvent(new MouseEvent('mousedown', opts));
            el.dispatchEvent(new MouseEvent('mouseup', opts));
            el.dispatchEvent(new MouseEvent('click', opts));
            if (typeof el.click === 'function') el.click();
            return true;
        };

        const elements = Array.from(document.querySelectorAll(
            "button, a, span, div, input[type=button], input[type=submit]"
        ));

        const matches = elements
            .filter(el => norm(el.innerText || el.value || "") === "닫기" && isVisible(el))
            .sort((a, b) => {
                const ar = a.getBoundingClientRect();
                const br = b.getBoundingClientRect();
                return br.y - ar.y || br.x - ar.x;
            });

        if (!matches.length) return false;
        return fireClick(matches[0]);
    }
    """)

    if not clicked:
        print("[G2B] 닫기 button not found — fallback to ESC")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(1500)
    else:
        page.wait_for_timeout(2000)

    try:
        dismiss_code0_warning(page, pause_ms=1000)
    except Exception:
        pass

    wait_for_loading_clear(page, timeout_ms)

    for _ in range(30):
        try:
            body = page.locator("body").inner_text(timeout=3000)
            if "공고일반" in body and "구매대상물품" in body and "입찰진행정보" in body:
                print("[G2B] Returned to tender detail page ✓")
                return True
        except Exception:
            pass
        page.wait_for_timeout(500)

    print("[G2B] Could not verify popup close")
    if args is not None:
        save_debug_screenshot(page, args, "supplier_popup_close_not_verified")
    return False


def click_detail_list_button(page, timeout_ms, args=None):
    """
    Click the '목록' button on detail page to return to list.
    """
    print("[G2B] Returning to result list via 목록 button …")
    try:
        dismiss_code0_warning(page, pause_ms=1000)
    except Exception:
        pass

    # Scroll to bottom (important for G2B)
    for _ in range(8):
        page.evaluate("""
        () => {
            window.scrollTo(0, document.body.scrollHeight);
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollHeight > el.clientHeight) {
                    el.scrollTop = el.scrollHeight;
                }
            });
        }
        """)
        page.wait_for_timeout(200)

    # Click 목록
    clicked = page.evaluate("""
    () => {
        const isVisible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };

        const elements = Array.from(document.querySelectorAll(
            "button, a, input[type=button], span, div"
        ));

        for (const el of elements) {
            const txt = (el.innerText || el.value || "").trim();
            if (txt === "목록" && isVisible(el)) {
                el.click();
                return true;
            }
        }
        return false;
    }
    """)

    try:
        dismiss_code0_warning(page, pause_ms=1000)
    except Exception:
        pass

    if not clicked:
        print("[G2B] 목록 button not found, using browser back")
        page.go_back()
        page.wait_for_timeout(1500)
        return True

    page.wait_for_timeout(1500)
    return True

def scrape_one(
    context: BrowserContext,
    page: Page,
    row: TenderRow,
    timeout_ms: int,
    query_text: str,
    args: argparse.Namespace,
) -> List[TenderDetail]:
    before_pages = set(context.pages)
    try:
        prev_text = page.locator("body").inner_text(timeout=float(timeout_ms))[:3000]
    except Exception:
        prev_text = ""
    before_url = page.url

    debug_log(args, f"Preparing to click tender row title={row.title!r}")
    debug_log(args, f"Row text sample={row.row_text[:500]!r}")

    if not click_row(page, row, args):
        log(f"Could not click 진행완료 for row: {row.title}")
        save_debug_screenshot(page, args, "click_row_failed")
        return []

    page.wait_for_timeout(2_000)
    new_pages = [candidate for candidate in context.pages if candidate not in before_pages]
    detail_page = new_pages[0] if new_pages else page

    wait_ready(detail_page, timeout_ms)

    debug_log(args, f"After click: before_url={before_url}")
    debug_log(args, f"After click: detail_url={detail_page.url}")

    try:
        current_text_sample = detail_page.locator("body").inner_text(timeout=5000)[:1200]
        debug_log(args, f"Detail/body text sample after click: {current_text_sample}")
    except Exception as exc:
        current_text_sample = ""
        debug_log(args, f"Could not read detail text sample after click: {exc}")

    # G2B is a WebSquare SPA: URL often stays https://www.g2b.go.kr/.
    # Do NOT use URL equality to decide failure.
    # Detail page is confirmed by content such as 입찰공고상세 / 공고일반 / 입찰공고번호.
    detail_confirmed = False
    try:
        for _ in range(20):
            detail_confirmed = bool(detail_page.evaluate("""
            () => {
              const txt = (document.body?.innerText || '').replace(/\\u00a0/g, ' ');
              return (
                txt.includes('입찰공고상세') ||
                (
                  txt.includes('공고일반') &&
                  txt.includes('입찰공고번호') &&
                  txt.includes('게시일시')
                )
              );
            }
            """))
            if detail_confirmed:
                break
            detail_page.wait_for_timeout(500)
    except Exception:
        detail_confirmed = False

    if detail_confirmed:
        debug_log(args, "Tender detail page confirmed by page content.")
    else:
        # Do not abort immediately; save screenshot and still try extraction,
        # because some G2B detail layouts have different labels.
        debug_log(args, "Tender detail page not strongly confirmed; continuing extraction anyway.")
        save_debug_screenshot(detail_page, args, "detail_not_strongly_confirmed")

    if detail_page is page:
        try:
            page.wait_for_function(
                "(prev) => { const t = (document.body?.innerText || '').slice(0, 3000); return t && t !== prev; }",
                arg=prev_text,
                timeout=timeout_ms,
            )
        except PlaywrightTimeoutError:
            pass

    dismiss_all_popups(detail_page, max_rounds=6)

    detail_page.wait_for_timeout(1_000)

    supplier_result = extract_supplier_from_opening_result(detail_page, timeout_ms, args)
    supplier_override = supplier_result.get('supplier_name', '') if isinstance(supplier_result, dict) else compact(str(supplier_result or ''))
    amount_override = supplier_result.get('bid_amount', '') if isinstance(supplier_result, dict) else ''

    full_scroll_detail(detail_page)
    payload = extract_detail(detail_page)
    debug_log(args, f"Extracted detail URL: {payload.get('url', '')}")
    debug_log(args, f"Extracted detail text length: {len(payload.get('bodyText', '') or '')}")
    debug_log(args, f"Extracted visible table count: {len(payload.get('tables', []) or [])}")

    records = build_records(row, payload, query_text, getattr(args, 'translate_en', False), supplier_override, amount_override)

    if records:
        sample = asdict(records[0])
        debug_fields = {
            "notice_id": sample.get("notice_id", ""),
            "title": sample.get("title", "")[:160],
            "title_en": sample.get("title_en", "")[:160],
            "publication_date": sample.get("publication_date", ""),
            "closing_date": sample.get("closing_date", ""),
            "buyer": sample.get("buyer", ""),
            "amount": sample.get("amount", ""),
            "supplier_name": sample.get("supplier_name", ""),
            "notice_url": sample.get("notice_url", ""),
        }
        debug_log(args, f"Sample extracted fields: {json.dumps(debug_fields, ensure_ascii=False)}")
    else:
        debug_log(args, "No records built from detail payload.")

    if detail_page is page:
        if not click_detail_list_button(page, timeout_ms, args):
            # Last-resort fallback only. Browser history can return to homepage,
            # so immediately verify and recover if needed.
            log("Falling back to browser back because 목록 failed …")
            try:
                page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                page.go_back(timeout=timeout_ms)

            page.wait_for_timeout(1_500)
            wait_ready(page, timeout_ms)

        if not is_bid_list_open(page):
            log("Not on bid list after returning; attempting navigation recovery …")
            navigate_to_bid_list(page, timeout_ms, args)
            wait_ready(page, timeout_ms)
    else:
        # If the detail opened in a new popup/tab, close it and return focus to the list tab.
        detail_page.close()
        page.bring_to_front()
        page.wait_for_timeout(800)
        wait_ready(page, timeout_ms)

    return records


def dedupe_records(records: List[TenderDetail]) -> List[TenderDetail]:
    deduped: List[TenderDetail] = []
    seen_keys: set[str] = set()

    for rec in records:
        key = rec.dedup_key or f"{rec.notice_id}|{rec.item_no}|{rec.item_description}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(rec)

    return deduped



def wait_for_grid_rows_after_scroll(page: Page, before_sig: str, args: argparse.Namespace, max_wait_ms: int = 15_000) -> bool:
    """
    G2B/WebSquare lazy-loads result rows after the internal grid scrolls.
    Wait until visible row signature changes before deciding there are no more rows.
    """
    elapsed = 0
    while elapsed < max_wait_ms:
        page.wait_for_timeout(500)
        elapsed += 500

        try:
            wait_for_loading_clear(page, min(args.timeout_ms, 10_000))
        except Exception:
            pass

        try:
            after_sig = _result_row_signature(page)
            if after_sig and after_sig != before_sig:
                return True
        except Exception:
            pass

    return False


def row_limit_reached(seen_count: int, args: argparse.Namespace) -> bool:
    limit = getattr(args, "row_limit", None)
    return bool(limit is not None and seen_count >= limit)


def detail_progress_label(seen_count: int, args: argparse.Namespace) -> str:
    limit = getattr(args, "row_limit", None)
    if limit is None:
        return f"{seen_count + 1}"
    return f"{seen_count + 1}/{limit}"


def resume_listing_position(page: Page, args: argparse.Namespace) -> None:
    """
    After a restart, advance the listing grid until at least one currently visible row
    is not already listed in the saved progress file.
    """
    seen = set(getattr(args, "_resume_seen", set()) or set())
    if not seen:
        return

    log(f"Resume state found for {len(seen)} processed rows — advancing listing to first unseen row …")
    stagnant_rounds = 0

    for round_no in range(1, args.max_scrolls + 1):
        wait_for_loading_clear(page, args.timeout_ms)
        rows = extract_rows(page)
        visible_keys = []
        for row in rows:
            notice = normalize_notice_id(row.row_text)
            key = notice or f"{row.title}|{row.row_text}"
            visible_keys.append(key)

        if visible_keys and any(key not in seen for key in visible_keys):
            log("Reached a listing position with unseen rows visible.")
            return

        before_sig = _result_row_signature(page)
        scrolled = scroll_once(page)
        if not scrolled:
            log("Resume scroll action could not be performed.")
            return

        changed = wait_for_grid_rows_after_scroll(page, before_sig, args, max_wait_ms=15_000)
        if not changed:
            stagnant_rounds += 1
            if stagnant_rounds >= args.stagnant_scroll_limit:
                log("Resume listing advance stalled before unseen rows appeared.")
                return
        else:
            stagnant_rounds = 0


def skip_rows_by_log_position(page: Page, args: argparse.Namespace) -> None:
    """
    If the JSON state is incomplete but the log knows the last row number,
    advance through the listing by counting unique rows until we reach that
    resume position. The target row itself is left unseen so scraping restarts
    from that row.
    """
    target_before_count = int(getattr(args, "_resume_skip_count", 0) or 0)
    if target_before_count <= 0:
        return

    log(f"Using log-based resume: skipping {target_before_count} row(s) to restart from the last logged detail position …")
    stagnant_rounds = 0
    discovered: list[str] = []
    discovered_set: set[str] = set()

    for _ in range(1, args.max_scrolls + 1):
        wait_for_loading_clear(page, args.timeout_ms)
        rows = extract_rows(page)
        if rows:
            for row in rows:
                notice = normalize_notice_id(row.row_text)
                key = notice or f"{row.title}|{row.row_text}"
                if key in discovered_set:
                    continue
                discovered.append(key)
                discovered_set.add(key)
                if len(discovered) >= target_before_count:
                    args._resume_seen = set(discovered[:target_before_count])
                    args._resume_skip_count = 0
                    log("Reached log-based resume row on the listing page.")
                    return

        before_sig = _result_row_signature(page)
        scrolled = scroll_once(page)
        if not scrolled:
            log("Log-based resume could not scroll further.")
            break

        changed = wait_for_grid_rows_after_scroll(page, before_sig, args, max_wait_ms=15_000)
        if not changed:
            stagnant_rounds += 1
            if stagnant_rounds >= args.stagnant_scroll_limit:
                log("Log-based resume stalled before reaching the saved row number.")
                break
        else:
            stagnant_rounds = 0

    args._resume_seen = set(discovered[: min(len(discovered), target_before_count)])
    args._resume_skip_count = max(0, target_before_count - len(discovered))


def resume_to_notice_id(page: Page, args: argparse.Namespace) -> None:
    """
    Resume by the actual logged notice id, not by a blind visible-row count.
    Once the target notice becomes visible, mark only the rows before that notice as seen
    so scraping restarts from the logged row itself.
    """
    target_notice = normalize_notice_id(getattr(args, "_resume_target_notice_id", ""))
    if not target_notice:
        return

    seen = set(getattr(args, "_resume_seen", set()) or set())
    if target_notice in seen:
        args._resume_target_notice_id = ""
        return

    log(f"Using notice-based resume: advancing listing until notice {target_notice} becomes visible …")
    stagnant_rounds = 0

    for _ in range(1, args.max_scrolls + 1):
        wait_for_loading_clear(page, args.timeout_ms)
        rows = extract_rows(page)

        if rows:
            target_index = -1
            for idx, row in enumerate(rows):
                notice = normalize_notice_id(row.row_text)
                if notice == target_notice:
                    target_index = idx
                    break

            if target_index >= 0:
                for idx, row in enumerate(rows[:target_index]):
                    notice = normalize_notice_id(row.row_text)
                    key = notice or f"{row.title}|{row.row_text}"
                    seen.add(key)

                args._resume_seen = seen
                args._resume_target_notice_id = ""
                args._resume_skip_count = 0
                target_row = rows[target_index]
                resume_index = last_detail_index_from_log(args.log_file)
                if resume_index > 0:
                    log(f"Reached resume row {resume_index} on the listing page.")
                else:
                    log(f"Reached resume notice {target_notice} on the listing page.")
                save_progress_state(args, "running", seen, target_notice, target_row.title)
                return

        before_sig = _result_row_signature(page)
        scrolled = scroll_once(page)
        if not scrolled:
            log(f"Notice-based resume could not scroll further before reaching {target_notice}.")
            break

        changed = wait_for_grid_rows_after_scroll(page, before_sig, args, max_wait_ms=15_000)
        if not changed:
            stagnant_rounds += 1
            if stagnant_rounds >= args.stagnant_scroll_limit:
                log(f"Notice-based resume stalled before reaching {target_notice}.")
                break
        else:
            stagnant_rounds = 0



def probe_result_grid_scrolling(page: Page, args: argparse.Namespace) -> None:
    """
    Debug helper: verify only listing-page scrolling after filters/search.
    No detail rows are opened in this mode.
    """
    stagnant_rounds = 0

    for round_no in range(1, args.max_scrolls + 1):
        wait_for_loading_clear(page, args.timeout_ms)
        rows = extract_rows(page)
        log(
            f"Scroll {round_no}: {len(rows)} visible tender rows, "
            f"stagnant={stagnant_rounds}/{args.stagnant_scroll_limit}"
        )

        if stagnant_rounds >= args.stagnant_scroll_limit:
            log("No new rows after multiple grid scrolls — stopping.")
            return

        before_sig = _result_row_signature(page)
        scrolled = scroll_once(page)
        if not scrolled:
            log("Result grid scroll action could not be performed — waiting once before stopping.")
            page.wait_for_timeout(3000)

        changed = wait_for_grid_rows_after_scroll(page, before_sig, args, max_wait_ms=15_000)
        if not changed:
            stagnant_rounds += 1
            log(f"Grid rows did not change after scroll wait; stagnant={stagnant_rounds}/{args.stagnant_scroll_limit}")
            page.wait_for_timeout(2500)
        else:
            stagnant_rounds = 0


def scrape_results(page: Page, context: BrowserContext, args: argparse.Namespace) -> List[TenderDetail]:
    """
    Scrape result grid rows.

    Important:
    - G2B/WebSquare scrolls the internal result grid/list, not always the full page.
    - We consider every visible tender row, not only rows with a specific status.
    - We stop only after row_limit records/tenders or after stagnant scroll rounds.
    """
    records: List[TenderDetail] = []
    seen: set[str] = set(getattr(args, "_resume_seen", set()))
    stagnant_rounds = 0

    if getattr(args, "_search_result_state", "") == "empty":
        log("No tender rows are available for the current filters.")
        return []

    for round_no in range(1, args.max_scrolls + 1):
        wait_for_loading_clear(page, args.timeout_ms)
        rows = extract_rows(page)

        if round_no == 1 and not rows:
            state = wait_for_result_rows_or_empty_state(page, args.timeout_ms, args, max_wait_ms=15_000)
            if state == "empty":
                log("No tender rows are available for the current filters.")
                return []
            if state == "rows":
                rows = extract_rows(page)

        new_rows: list[tuple[str, TenderRow]] = []
        for row in rows:
            notice = normalize_notice_id(row.row_text)
            key = notice or f"{row.title}|{row.row_text}"
            if key not in seen:
                new_rows.append((key, row))

        log(
            f"Scroll {round_no}: {len(rows)} visible tender rows, "
            f"{len(new_rows)} new, stagnant={stagnant_rounds}/{args.stagnant_scroll_limit}"
        )

        for key, row in new_rows:
            if row_limit_reached(len(seen), args):
                return dedupe_records(records)

            scroll_state = save_scroll(page)
            log(f"  → Detail {detail_progress_label(len(seen), args)}: {row.title[:80]}")

            try:
                row_records = scrape_one(
                    context,
                    page,
                    row,
                    args.timeout_ms,
                    args.query_text or getattr(args, "industry_code", ""),
                    args,
                )
            except Exception as exc:
                log(f"Error scraping row {row.title[:80]}: {exc}")
                save_debug_screenshot(page, args, "scrape_one_exception")
                row_records = []

                # Try to recover to listing if row/detail failed mid-navigation.
                try:
                    if not is_bid_list_open(page):
                        click_detail_list_button(page, args.timeout_ms, args)
                    if not is_bid_list_open(page):
                        navigate_to_bid_list(page, args.timeout_ms, args)
                        apply_filters(page, args.timeout_ms, args.start_date, args.end_date, args.query_text, args)
                        trigger_search(page, args.timeout_ms, args)
                except Exception as recovery_exc:
                    log(f"Recovery after row error failed: {recovery_exc}")

            seen.add(key)
            args._resume_seen = seen

            # Restore result grid/list scroll position after returning from detail.
            try:
                restore_scroll(page, scroll_state)
                wait_for_loading_clear(page, args.timeout_ms)
            except Exception:
                pass

            if row_records:
                row_records = dedupe_records(row_records)
                records.extend(row_records)
                args._records_written = getattr(args, "_records_written", 0) + append_csv_rows(
                    args.output,
                    (asdict(record) for record in row_records),
                )

            save_progress_state(
                args,
                "running",
                seen,
                normalize_notice_id(row.row_text),
                row.title,
            )

        if row_limit_reached(len(seen), args):
            break

        if stagnant_rounds >= args.stagnant_scroll_limit:
            log("No new rows after multiple grid scrolls — stopping.")
            break

        before_sig = _result_row_signature(page)

        scrolled = scroll_once(page)
        if not scrolled:
            log("Result grid scroll action could not be performed — waiting once before stopping.")
            page.wait_for_timeout(3000)

        changed = wait_for_grid_rows_after_scroll(page, before_sig, args, max_wait_ms=15_000)

        if not changed:
            stagnant_rounds += 1
            log(f"Grid rows did not change after scroll wait; stagnant={stagnant_rounds}/{args.stagnant_scroll_limit}")
            page.wait_for_timeout(2500)
        else:
            stagnant_rounds = 0

    return dedupe_records(records)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main() -> None:
    args = parse_args()
    initialize_progress(args)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            slow_mo=args.slow_mo,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1600, "height": 1000},
        )

        page = context.new_page()
        page.set_default_timeout(args.timeout_ms)

        try:
            open_homepage(page, args.timeout_ms)
            navigate_to_bid_list(page, args.timeout_ms, args)

            pause(page, args, 3_000, 500)
            wait_ready(page, args.timeout_ms)

            if not is_bid_list_open(page):
                raise RuntimeError("Failed to reach 입찰공고목록 after navigation.")

            apply_filters(page, args.timeout_ms, args.start_date, args.end_date, args.query_text, args)
            trigger_search(page, args.timeout_ms, args)
            resume_listing_position(page, args)
            skip_rows_by_log_position(page, args)

            if args.scroll_only:
                probe_result_grid_scrolling(page, args)
                save_progress_state(args, "completed", getattr(args, "_resume_seen", set()))
                return

            records = scrape_results(page, context, args)
            records = dedupe_records(records)

            save_progress_state(args, "completed", getattr(args, "_resume_seen", set()))
            total_rows = count_csv_rows(args.output)

            if total_rows:
                print(f"\nSaved {total_rows} records → {args.output}", flush=True)
            else:
                print(f"No records captured. Empty CSV written → {args.output}", flush=True)

        except KeyboardInterrupt:
            save_progress_state(args, "interrupted", getattr(args, "_resume_seen", set()))
            log("Run interrupted. Progress saved for resume.")
            raise
        except Exception:
            save_progress_state(args, "failed", getattr(args, "_resume_seen", set()))
            log("Run failed. Progress saved for resume.")
            raise

        finally:
            browser.close()


if __name__ == "__main__":
    main()


