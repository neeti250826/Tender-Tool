from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


logger = logging.getLogger("ro_seap_scraper")

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


TED_API_URL = "https://api.ted.europa.eu/v3/notices/search"


def list_advanced_filters() -> str:
    return "\n".join(
        [
            "Romania SEAP / SICAP advanced search:",
            "- NOTE: e-licitatie.ro is not reliably reachable from this environment.",
            "- This tool therefore provides a requests-based fallback using the public TED (EU) Search API, filtered to place-of-performance in Romania.",
            "- TED Search API: POST https://api.ted.europa.eu/v3/notices/search",
            "- User-facing filters in this tool:",
            "    --published-from / --published-to (maps to TED 'publication-date>=YYYYMMDD' / '<=')",
            "    --buyer-name (maps to 'buyer-name~\"...\"')",
            "    --cpv (repeatable; maps to 'classification-cpv=...')",
            "    --query (maps to '(title-proc~\"...\" OR description-proc~\"...\")')",
            "    --page / --page-size",
            "- Discovery-only mode remains available for future SEAP/SICAP endpoint capture.",
        ]
    ) + "\n"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def discover_endpoints_playwright(
    *,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, int, str]:
    try:
        playwright_sync = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(playwright_sync, "sync_playwright")
    except Exception:
        logger.warning("Playwright not available")
        return "", 0, "playwright_not_installed"

    base_dir = resolve_output_base_dir(output_target=output_target, region=region, website_id=website_id)
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    artifact_path = web_dir / f"ro_seap_discovery_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"

    records: List[dict] = []
    error_message = ""

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on(
                "response",
                lambda resp: records.append(
                    {
                        "ts_utc": _utc_now_iso(),
                        "url": str(getattr(resp, "url", "") or ""),
                        "status": int(getattr(resp, "status", 0) or 0),
                    }
                )
                if len(records) < 200
                else None,
            )
            page.goto("https://www.e-licitatie.ro/", wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
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
def _yyyymmdd(date_yyyy_mm_dd: str) -> str:
    """Convert YYYY-MM-DD -> YYYYMMDD for TED expert queries."""
    raw = str(date_yyyy_mm_dd or "").strip()
    if not raw:
        return ""
    parts = raw.split("-")
    if len(parts) != 3:
        return ""
    y, m, d = parts
    if len(y) != 4:
        return ""
    return f"{y}{m.zfill(2)}{d.zfill(2)}"


def _pick_i18n_text(value) -> str:
    """Pick a readable string from TED i18n fields.

    TED commonly returns either:
    - a string
    - a dict like {"eng": "...", "ita": "..."}
    - a dict like {"eng": ["..."]}
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        # Prefer English if present.
        for k in ("eng", "en", "ENG"):
            if k in value:
                v = value.get(k)
                if isinstance(v, list):
                    return str(v[0]).strip() if v else ""
                return str(v).strip()
        # Fallback to first available.
        for v in value.values():
            if isinstance(v, list):
                return str(v[0]).strip() if v else ""
            return str(v).strip()
    return str(value).strip()


def _build_ted_query(
    *,
    published_from: str,
    published_to: str,
    query_text: str,
    buyer_name: str,
    cpv_codes: Sequence[str],
) -> str:
    clauses: List[str] = []

    # Romania filter (place of performance). This is the closest stable proxy for "Romania tenders" on TED.
    clauses.append("place-of-performance-country-proc=ROU")

    df = _yyyymmdd(published_from)
    if df:
        clauses.append(f"publication-date>={df}")
    dt = _yyyymmdd(published_to)
    if dt:
        clauses.append(f"publication-date<={dt}")

    buyer = str(buyer_name or "").strip()
    if buyer:
        buyer_safe = buyer.replace('"', "'")
        clauses.append(f"buyer-name~\"{buyer_safe}\"")

    q = str(query_text or "").strip()
    if q:
        q_safe = q.replace('"', "'")
        clauses.append(f"(title-proc~\"{q_safe}\" OR description-proc~\"{q_safe}\")")

    cpvs = [str(c or "").strip() for c in (cpv_codes or []) if str(c or "").strip()]
    if cpvs:
        safe_cpvs = [c.replace('"', "'") for c in cpvs]
        inner = " OR ".join(f"classification-cpv={c}" for c in safe_cpvs)
        clauses.append(f"({inner})")

    return " AND ".join([c for c in clauses if c])


def _fetch_ted_page(*, expert_query: str, page: int, page_size: int) -> dict:
    payload = {
        "query": str(expert_query),
        "fields": [
            "publication-number",
            "publication-date",
            "title-proc",
            "description-proc",
            "buyer-name",
            "buyer-country",
            "place-of-performance-country-proc",
            "classification-cpv",
            "links",
        ],
        "page": int(page),
        "limit": int(page_size),
    }
    import requests

    r = requests.post(TED_API_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def _ted_to_normalized_df(payload: dict, *, query_text: str):
    import pandas as pd

    notices = payload.get("notices") if isinstance(payload, dict) else None
    if not isinstance(notices, list):
        notices = []

    scraped_at_utc = _utc_now_iso()
    rows: List[Dict[str, str]] = []
    for n in notices:
        if not isinstance(n, dict):
            continue
        pub_no = str(n.get("publication-number", "") or "").strip()
        pub_date_raw = str(n.get("publication-date", "") or "").strip()
        pub_date = pub_date_raw[:10] if pub_date_raw else ""

        title = _pick_i18n_text(n.get("title-proc"))
        desc = _pick_i18n_text(n.get("description-proc"))

        buyer_name = _pick_i18n_text(n.get("buyer-name"))
        cpvs = n.get("classification-cpv")
        classification = ""
        if isinstance(cpvs, list):
            classification = ",".join([str(c).strip() for c in cpvs if str(c).strip()])

        links = n.get("links") if isinstance(n.get("links"), dict) else {}
        notice_url = ""
        try:
            html_links = links.get("html") if isinstance(links.get("html"), dict) else {}
            notice_url = str(html_links.get("ENG") or "").strip()
        except Exception:
            notice_url = ""
        if not notice_url and pub_no:
            notice_url = f"https://ted.europa.eu/en/notice/-/detail/{pub_no}"

        rows.append(
            {
                "source": "RO_SEAP",
                "country": "Romania",
                "country_code": "RO",
                "publication_date": pub_date,
                "title": title,
                "description": desc,
                "buyer": buyer_name,
                "classification": classification,
                "tender_status": "",
                "currency": "",
                "amount": "",
                "notice_id": pub_no,
                "notice_url": notice_url,
                "query_text": str(query_text or ""),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": f"RO_SEAP|{pub_no}|{notice_url}",
            }
        )

    if not rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Romania SEAP scaffold (RO_SEAP)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword token.")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Use Playwright to discover endpoints then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="RO_SEAP", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Romania SEAP", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    # TED fallback filters (requests-based)
    parser.add_argument("--published-from", default=None, help="TED publication date from (YYYY-MM-DD).")
    parser.add_argument("--published-to", default=None, help="TED publication date to (YYYY-MM-DD).")
    parser.add_argument("--buyer-name", default="", help="Buyer name contains (TED).")
    parser.add_argument("--cpv", action="append", default=[], help="CPV code (repeatable; TED).")
    parser.add_argument("--page", type=int, default=1, help="TED page number (1..).")
    parser.add_argument("--page-size", type=int, default=50, help="TED page size.")

    add_standard_colab_args(parser, default_country="RO")
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

    # Requests-based TED fallback (default behavior).
    published_from = args.published_from or date_from
    published_to = args.published_to or date_to
    expert_query = _build_ted_query(
        published_from=str(published_from or ""),
        published_to=str(published_to or ""),
        query_text=query_text,
        buyer_name=str(args.buyer_name or ""),
        cpv_codes=list(getattr(args, "cpv", []) or []),
    )
    ted_payload = _fetch_ted_page(expert_query=expert_query, page=int(args.page), page_size=int(args.page_size))
    normalized_df = _ted_to_normalized_df(ted_payload, query_text=query_text)
    normalized_df["date_from"] = str(date_from or "")
    normalized_df["date_to"] = str(date_to or "")

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
        "ted": {
            "expert_query": expert_query,
            "page": int(args.page),
            "page_size": int(args.page_size),
            "totalNoticeCount": int(ted_payload.get("totalNoticeCount") or 0) if isinstance(ted_payload, dict) else 0,
        },
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
