from __future__ import annotations

import argparse
import importlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import requests


logger = logging.getLogger("vneps_scraper")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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


def list_advanced_filters() -> str:
    return "\n".join(
        [
            "Vietnam VNEPS (muasamcong.mpi.gov.vn) advanced search:",
            "- Listings are fetched via: /o/egp-portal-contractor-selection-v2/services/smart/search (JSON)",
            "- The endpoint requires an ephemeral token; the tool can discover it with Playwright.",
            "- User-facing flags:",
            "  - --query",
            "  - --date-from / --date-to (publication date)",
            "  - --tender-status (all/open/closed)",
            "  - --page-size (10/20/50)",
            "  - --max-pages (safety cap)",
        ]
    ) + "\n"


def _stable_dedup_key(*parts: str) -> str:
    import hashlib

    payload = "|".join([str(part or "").strip() for part in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


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


def fetch_vneps_smart_search(
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
) -> "object":
    """Requests-based listing via Muasamcong smart/search.

    Playwright is used only to discover an ephemeral token when needed.
    """

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

    import pandas as pd

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

        pub = str(item.get("publicDate") or "")
        publication_date = pub.split("T")[0] if "T" in pub else pub

        amount = ""
        bid_price = item.get("bidPrice")
        if isinstance(bid_price, list) and bid_price:
            amount = str(bid_price[0])

        classification = ""
        inv = item.get("investField")
        if isinstance(inv, list) and inv:
            classification = ",".join([str(x) for x in inv if str(x).strip()])

        notice_url = ""
        try:
            notice_url = str(build_detail_url(item) or "")
        except Exception:
            notice_url = ""

        rows.append(
            {
                "source": "VN_VNEPS",
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
                "dedup_key": _stable_dedup_key("VN_VNEPS", notice_id, str(query_text or "").strip()),
            }
        )

    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def discover_endpoints_playwright(
    *,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, int, str]:
    """Discover VNEPS endpoints via Playwright (best-effort)."""
    try:
        playwright_sync = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(playwright_sync, "sync_playwright")
    except Exception:
        logger.warning("Playwright not available")
        return "", 0, "playwright_not_installed"

    base_dir = resolve_output_base_dir(output_target=output_target, region=region, website_id=website_id)
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    artifact_path = web_dir / f"vneps_discovery_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"

    records: List[dict] = []
    error_message = ""

    def should_capture(response) -> bool:
        try:
            req = response.request
            rtype = str(getattr(req, "resource_type", "") or "")
            url = str(getattr(response, "url", "") or "")
            if rtype in {"xhr", "fetch"}:
                return True
            # Also capture any portal endpoints even if Playwright classifies them oddly.
            if any(token in url for token in ("/services/", "/o/", "/api/")):
                return True
            headers = getattr(response, "headers", {}) or {}
            ct = str(headers.get("content-type", "") or "").lower()
            return ("json" in ct) or ct.startswith("text/")
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

            def on_response(resp):
                if len(records) >= 200:
                    return
                if not should_capture(resp):
                    return
                try:
                    records.append(
                        {
                            "ts_utc": _utc_now_iso(),
                            "url": str(getattr(resp, "url", "") or ""),
                            "status": int(getattr(resp, "status", 0) or 0),
                            "content_type": str((getattr(resp, "headers", {}) or {}).get("content-type", "") or ""),
                        }
                    )
                except Exception:
                    return

            page.on("response", on_response)
            page.goto(
                "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?render=search",
                wait_until="domcontentloaded",
                timeout=timeout_seconds * 1000,
            )
            page.wait_for_timeout(8000)

            # Best-effort: trigger a search.
            try:
                # Fill any obvious free-text input.
                page.locator("input").first.fill(str(""))
            except Exception:
                pass
            try:
                # Click a button containing "Tìm kiếm".
                page.get_by_role("button", name=re.compile(r"t\u00ecm\s+ki\u1ebfm", re.IGNORECASE)).first.click(timeout=3000)
            except Exception:
                pass
            page.wait_for_timeout(8000)
            browser.close()
        except Exception as exc:
            error_message = f"playwright_error: {exc}"

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("w", encoding="utf-8") as h:
        h.write(json.dumps({"type": "summary", "ts_utc": _utc_now_iso(), "record_count": len(records), "error": error_message}) + "\n")
        for r in records:
            h.write(json.dumps({"type": "response", **r}, ensure_ascii=True) + "\n")

    return str(artifact_path), len(records), error_message


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vietnam VNEPS scaffold (VN_VNEPS)")
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
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Use Playwright to discover endpoints then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="VN_VNEPS", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Vietnam VNEPS", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    add_standard_colab_args(parser, default_country="VN")
    return parser.parse_args(list(argv) if argv is not None else None)


def run(args: argparse.Namespace) -> Dict[str, object]:
    date_from, date_to, normalized_years = resolve_date_range(
        date_from=args.date_from,
        date_to=args.date_to,
        years=args.years,
    )
    query_text = build_query_text(args.query, args.keywords)
    keywords = build_run_keywords(keywords=args.keywords, query_text=query_text)

    if bool(getattr(args, "list_advanced_filters", False)):
        print(list_advanced_filters())
        return {"date_from": date_from, "date_to": date_to, "query_text": query_text, "keywords": keywords}

    discover_summary: Dict[str, object] = {}
    if bool(getattr(args, "discover_only", False)):
        artifact, count, err = discover_endpoints_playwright(
            output_target=args.output_target,
            region=args.region,
            website_id=args.website_id,
        )
        discover_summary = {"artifact": artifact, "record_count": count, "error": err}

    import pandas as pd

    normalized_df = None
    if not bool(getattr(args, "discover_only", False)):
        try:
            normalized_df = fetch_vneps_smart_search(
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
            logger.warning("Smart search fetch failed; writing empty outputs. error=%s", exc)

    if normalized_df is None:
        normalized_df = pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
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

    base_dir = resolve_output_base_dir(output_target=args.output_target, region=args.region, website_id=args.website_id)
    layout = ensure_spec_folder_layout(base_dir)
    run_stem = build_run_output_stem(project_name=args.project_name, years=list(normalized_years), keywords=list(keywords))
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
    logger.info("Run output: %s", spec.get("run_csv"))
    logger.info("Consolidated output: %s", spec.get("consolidated_csv"))


if __name__ == "__main__":
    main()
