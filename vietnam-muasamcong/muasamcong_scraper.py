#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import requests

if TYPE_CHECKING:
    import pandas as pd_types


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


pd = importlib.import_module("pandas")

latam_defaults = importlib.import_module("latam_spec_defaults")
TranslationConfig = getattr(latam_defaults, "TranslationConfig")
add_standard_colab_args = getattr(latam_defaults, "add_standard_colab_args")
build_query_text = getattr(latam_defaults, "build_query_text")
build_run_keywords = getattr(latam_defaults, "build_run_keywords")
build_run_output_stem = getattr(latam_defaults, "build_run_output_stem")
ensure_spec_folder_layout = getattr(latam_defaults, "ensure_spec_folder_layout")
resolve_date_range = getattr(latam_defaults, "resolve_date_range")
resolve_output_base_dir = getattr(latam_defaults, "resolve_output_base_dir")
save_spec_outputs = getattr(latam_defaults, "save_spec_outputs")
translate_dataframe_to_english = getattr(latam_defaults, "translate_dataframe_to_english")

mdt_schema = importlib.import_module("mdt_schema")
to_mdt_schema = getattr(mdt_schema, "to_mdt_schema")

mdt_export = importlib.import_module("mdt_export")
save_mdt_outputs = getattr(mdt_export, "save_mdt_outputs")


logger = logging.getLogger("muasamcong_scraper")


NORMALIZED_COLUMNS: List[str] = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "title",
    "description",
    "buyer",
    "classification",
    "tender_status",
    "currency",
    "amount",
    "notice_id",
    "notice_url",
    "query_text",
    "scraped_at_utc",
    "dedup_key",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(part or "").strip() for part in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_placeholder_normalized_df(*, query_text: str) -> "pd_types.DataFrame":
    scraped_at_utc = _utc_now_iso()
    notice_id = "MUASAMCONG_PLACEHOLDER"
    notice_url = ""
    title = "Muasamcong scaffold placeholder"
    description = "Not implemented: VN_MUASAMCONG fetch/normalize pipeline is scaffolded only."

    row = {
        "source": "VN_MUASAMCONG",
        "country": "Vietnam",
        "country_code": "VN",
        "publication_date": "",
        "title": title,
        "description": description,
        "buyer": "",
        "classification": "",
        "tender_status": "",
        "currency": "",
        "amount": "",
        "notice_id": notice_id,
        "notice_url": notice_url,
        "query_text": str(query_text or "").strip(),
        "scraped_at_utc": scraped_at_utc,
        "dedup_key": _stable_dedup_key("VN_MUASAMCONG", notice_id, str(query_text or "").strip()),
    }

    return pd.DataFrame([row]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scaffold scraper for Vietnam Muasamcong (VN_MUASAMCONG)"
    )
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword search.")

    parser.add_argument(
        "--tender-status",
        default="all",
        choices=["all", "open", "closed"],
        help="Filter by tender status tab (all/open/closed).",
    )
    parser.add_argument(
        "--page-size",
        default=10,
        type=int,
        choices=[10, 20, 50],
        help="Records per page (as on the website).",
    )
    parser.add_argument(
        "--max-pages",
        default=3,
        type=int,
        help="Max pages to fetch (safety; set 0 for unlimited).",
    )
    parser.add_argument(
        "--record-type",
        action="append",
        default=["es-notify-contractor"],
        help="Record type(s) to include (repeatable).",
    )
    parser.add_argument(
        "--include-case-khkq",
        action="store_true",
        help="Include records normally excluded by the website default 'caseKHKQ != 1' filter.",
    )
    parser.add_argument(
        "--smart-token",
        default="",
        help="Optional pre-discovered smart search token. If omitted, the tool will try to discover it via Playwright.",
    )
    parser.add_argument("--output-target", default="", help="Google Drive URL or local output folder.")
    parser.add_argument(
        "--disable-deduplication", action="store_true", help="Disable default deduplication."
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Use Playwright to discover data endpoints and write web artifacts, then exit.",
    )

    parser.add_argument(
        "--project-name",
        default="MDT_2026",
        help="Project name token in outputs (PROJECT_NAME_YEAR).",
    )
    parser.add_argument("--website-id", default="VN_MUASAMCONG", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Vietnam Muasamcong", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    add_standard_colab_args(parser, default_country="VN")
    return parser.parse_args(list(argv) if argv is not None else None)


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def discover_endpoints_playwright(
    *,
    query_text: str,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, int, str]:
    """Attempt to discover Muasamcong data endpoints via Playwright.

    Returns (artifact_path, record_count, error_message).
    - If Playwright is unavailable, returns ("", 0, "playwright_not_installed").
    - Always best-effort; does not raise.
    """

    try:
        playwright_sync = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(playwright_sync, "sync_playwright")
    except Exception:
        logger.warning(
            "Playwright not available. Install 'playwright' to enable --discover-only."
        )
        return "", 0, "playwright_not_installed"

    base_dir = resolve_output_base_dir(
        output_target=output_target,
        region=region,
        website_id=website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    artifact_path = web_dir / f"muasamcong_discovery_{_timestamp_token()}.jsonl"

    records: List[dict] = []
    error_message = ""

    def should_capture(response) -> bool:
        try:
            request = response.request
            if getattr(request, "resource_type", "") in {"xhr", "fetch"}:
                return True
            headers = getattr(response, "headers", {}) or {}
            content_type = str(headers.get("content-type", "") or "").lower()
            return ("application/json" in content_type) or ("text/" in content_type)
        except Exception:
            return False

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            def on_response(response):
                if len(records) >= 200:
                    return
                if not should_capture(response):
                    return
                try:
                    request = response.request
                    headers = getattr(response, "headers", {}) or {}
                    content_type = str(headers.get("content-type", "") or "")
                    body_preview = ""
                    if "json" in content_type.lower() or content_type.lower().startswith("text/"):
                        try:
                            body_preview = str(response.text() or "")[:500]
                        except Exception:
                            body_preview = ""
                    records.append(
                        {
                            "ts_utc": _utc_now_iso(),
                            "url": str(getattr(response, "url", "") or ""),
                            "method": str(getattr(request, "method", "") or ""),
                            "status": int(getattr(response, "status", 0) or 0),
                            "resource_type": str(getattr(request, "resource_type", "") or ""),
                            "content_type": content_type,
                            "body_preview": body_preview,
                        }
                    )
                except Exception:
                    return

            page.on("response", on_response)

            url = "https://muasamcong.mpi.gov.vn/en/web/guest"
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(5000)

            q = str(query_text or "").strip()
            if q:
                try:
                    page.locator("input[type='text']").first.fill(q)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
                except Exception:
                    pass

            browser.close()
        except Exception as exc:
            error_message = f"playwright_error: {exc}"

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "summary",
                    "ts_utc": _utc_now_iso(),
                    "source": "VN_MUASAMCONG",
                    "query_text": str(query_text or ""),
                    "record_count": len(records),
                    "error": error_message,
                },
                ensure_ascii=True,
            )
            + "\n"
        )
        for record in records:
            handle.write(json.dumps({"type": "response", **record}, ensure_ascii=True) + "\n")

    return str(artifact_path), len(records), error_message


def fetch_records_requests(*, endpoint_hint: str = "") -> "pd_types.DataFrame":
    """Requests-based fetch stub.

    Once a stable Muasamcong JSON endpoint is confirmed, implement requests-first paging here.
    """

    _ = endpoint_hint
    return pd.DataFrame([])


def _parse_dt_iso(value: str) -> Optional[datetime]:
    v = str(value or "").strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return None


def _derive_tender_status(item: Dict[str, object]) -> str:
    close_dt = _parse_dt_iso(str(item.get("bidCloseDate") or ""))
    if not close_dt:
        return ""
    now = datetime.now()
    try:
        return "open" if close_dt >= now else "closed"
    except Exception:
        return ""


def fetch_records_smart_search(
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    query_text: str,
    tender_status: str,
    page_size: int,
    max_pages: int,
    record_types: Sequence[str],
    include_case_khkq: bool,
    smart_token: str,
) -> "pd_types.DataFrame":
    helper = importlib.import_module("vn_muasamcong_smart_search")
    discover_auth = getattr(helper, "discover_smart_search_auth_playwright")
    iter_records = getattr(helper, "iter_smart_search_records")
    build_detail_url = getattr(helper, "build_detail_v2_url")

    token = str(smart_token or "").strip()
    cookies = []
    if not token:
        auth = discover_auth()
        token = auth.token
        cookies = auth.cookies

    max_pages_opt: Optional[int] = None
    if int(max_pages) > 0:
        max_pages_opt = int(max_pages)

    rows: List[Dict[str, object]] = []
    scraped_at_utc = _utc_now_iso()

    for item in iter_records(
        token=token,
        cookies=cookies,
        keyword=query_text,
        page_size=int(page_size),
        max_pages=max_pages_opt,
        record_types=list(record_types or []),
        include_case_khkq=bool(include_case_khkq),
        public_date_from=str(date_from or "").strip() or None,
        public_date_to=str(date_to or "").strip() or None,
        tender_status=str(tender_status or "all"),
    ):
        notice_id = (
            str(item.get("notifyNoStand") or "").strip()
            or f"{item.get('notifyNo', '')}-{item.get('notifyVersion', '')}".strip("-")
            or str(item.get("id") or "").strip()
        )

        title = ""
        bid_name = item.get("bidName")
        if isinstance(bid_name, list) and bid_name:
            title = str(bid_name[0] or "").strip()
        if not title:
            title = str(item.get("name") or "").strip()

        amount = ""
        bid_price = item.get("bidPrice")
        if isinstance(bid_price, list) and bid_price:
            amount = str(bid_price[0])

        classification = ""
        inv = item.get("investField")
        if isinstance(inv, list) and inv:
            classification = ",".join([str(x) for x in inv if str(x).strip()])

        pub = str(item.get("publicDate") or "")
        publication_date = pub.split("T")[0] if "T" in pub else pub

        notice_url = ""
        try:
            notice_url = str(build_detail_url(item) or "")
        except Exception:
            notice_url = ""

        rows.append(
            {
                "source": "VN_MUASAMCONG",
                "country": "Vietnam",
                "country_code": "VN",
                "publication_date": publication_date,
                "title": title,
                "description": "",
                "buyer": str(item.get("investorName") or "").strip(),
                "classification": classification,
                "tender_status": _derive_tender_status(item),
                "currency": "VND",
                "amount": amount,
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key(
                    "VN_MUASAMCONG", notice_id, str(query_text or "").strip()
                ),
            }
        )

    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def run(args: argparse.Namespace) -> Dict[str, object]:
    date_from, date_to, normalized_years = resolve_date_range(
        date_from=args.date_from,
        date_to=args.date_to,
        years=args.years,
    )
    query_text = build_query_text(args.query, args.keywords)
    keywords = build_run_keywords(keywords=args.keywords, query_text=query_text)

    discover_summary: Dict[str, object] = {}
    if bool(getattr(args, "discover_only", False)):
        artifact_path, record_count, error = discover_endpoints_playwright(
            query_text=query_text,
            output_target=args.output_target,
            region=args.region,
            website_id=args.website_id,
        )
        discover_summary = {
            "artifact_path": artifact_path,
            "record_count": record_count,
            "error": error,
        }

    normalized_df = None
    if not bool(getattr(args, "discover_only", False)):
        try:
            normalized_df = fetch_records_smart_search(
                date_from=date_from,
                date_to=date_to,
                query_text=query_text,
                tender_status=str(getattr(args, "tender_status", "all")),
                page_size=int(getattr(args, "page_size", 10)),
                max_pages=int(getattr(args, "max_pages", 3)),
                record_types=list(getattr(args, "record_type", []) or []),
                include_case_khkq=bool(getattr(args, "include_case_khkq", False)),
                smart_token=str(getattr(args, "smart_token", "") or ""),
            )
        except Exception as exc:
            logger.warning(
                "Smart search fetch failed; falling back to placeholder. error=%s", exc
            )

    if normalized_df is None:
        normalized_df = build_placeholder_normalized_df(query_text=query_text)
    normalized_df = normalized_df.copy()
    normalized_df["date_from"] = date_from
    normalized_df["date_to"] = date_to

    translated_df = translate_dataframe_to_english(
        normalized_df,
        TranslationConfig(
            enabled=bool(args.enable_google_translation),
            project_id=args.google_project_id,
            target_language=args.translation_target_language,
            columns=args.translate_columns,
        ),
        only_when_missing=not args.translate_all,
    )

    spec_summary = save_spec_outputs(
        translated_df,
        output_target=args.output_target,
        region=args.region,
        website_id=args.website_id,
        source_label=args.source_label,
        project_name=args.project_name,
        years=normalized_years,
        keywords=keywords,
        deduplicate_results=not args.disable_deduplication,
    )

    base_dir = resolve_output_base_dir(
        output_target=args.output_target,
        region=args.region,
        website_id=args.website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    run_stem = build_run_output_stem(
        project_name=args.project_name,
        years=list(normalized_years),
        keywords=list(keywords),
    )

    mdt_df = to_mdt_schema(translated_df)
    mdt_prefix = Path(layout["tender_data_tool"]) / run_stem
    mdt_paths = save_mdt_outputs(mdt_df, mdt_prefix)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "query_text": query_text,
        "keywords": keywords,
        "normalized_rows": len(translated_df),
        "discover": discover_summary,
        "spec": spec_summary,
        "mdt": mdt_paths,
    }


def main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args(argv)
    result = run(args)

    spec = result.get("spec")
    if not isinstance(spec, dict):
        spec = {}
    mdt = result.get("mdt")
    if not isinstance(mdt, dict):
        mdt = {}

    logger.info(
        "Dedup before/after: %s -> %s (removed=%s)",
        spec.get("dedup_before"),
        spec.get("dedup_after"),
        spec.get("dedup_removed"),
    )
    logger.info("Run output: %s", spec.get("run_csv"))
    logger.info("Consolidated output: %s", spec.get("consolidated_csv"))
    logger.info("MDT CSV: %s", mdt.get("csv_path"))

    discover = result.get("discover")
    if isinstance(discover, dict) and discover.get("artifact_path"):
        logger.info("Discovery artifact: %s", discover.get("artifact_path"))


if __name__ == "__main__":
    main()
