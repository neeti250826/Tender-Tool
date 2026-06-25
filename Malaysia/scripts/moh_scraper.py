from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger("moh_scraper")

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(p or "").strip() for p in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def list_advanced_filters() -> str:
    return "\n".join(
        [
            "Malaysia MOH (www.moh.gov.my) tender list filters:",
            "- base listing (preferred, public): https://www.moh.gov.my/en/tender/list-of-tenders",
            "- advanced/search query parameters (GET):",
            "    filter-search: free-text",
            "    filter-match: any | all | exact (UI: Any words / All words / Exact phrase)",
            "    category, tag, author, alias, period, stage",
            "    filter_order, filter_order_Dir",
            "    start: pagination offset",
            "- examples:",
            "    https://www.moh.gov.my/en/tender/list-of-tenders?filter-search=digital&filter-match=any",
        ]
    ) + "\n"


def _fetch_listing_html(
    *,
    filter_search: str = "",
    filter_match: str = "any",
    start: int = 0,
    timeout_seconds: int = 30,
) -> str:
    # Use English listing which is stable in this environment.
    base = "https://www.moh.gov.my/en/tender/list-of-tenders"
    params = {
        "category": "",
        "tag": "",
        "author": "",
        "alias": "",
        "period": "",
        "stage": "",
        "filter_order": "",
        "filter_order_Dir": "ASC",
        "filter-search": str(filter_search or ""),
        "filter-match": str(filter_match or "any"),
        "start": int(start),
    }
    r = requests.get(base, params=params, timeout=max(5, int(timeout_seconds)))
    r.raise_for_status()
    return str(r.text or "")


def _parse_titles(html: str) -> List[Dict[str, str]]:
    # Very lightweight extraction: headings are rendered as <h4> / <h3> blocks.
    text = str(html or "")
    # Match "Tender No." headings (English page) and capture title.
    blocks = re.findall(r"<h[34][^>]*>(.*?)</h[34]>", text, flags=re.IGNORECASE | re.DOTALL)
    out: List[Dict[str, str]] = []
    for b in blocks:
        title = re.sub(r"<[^>]+>", "", b).strip()
        if not title:
            continue
        if "tender" in title.lower():
            out.append({"title": title})
    return out


def fetch_records_requests(*, query_text: str, filter_match: str, page_start: int) -> "pd_types.DataFrame":
    import pandas as pd

    html = _fetch_listing_html(filter_search=query_text, filter_match=filter_match, start=page_start)
    items = _parse_titles(html)
    scraped_at_utc = _utc_now_iso()
    rows: List[Dict[str, str]] = []
    for idx, item in enumerate(items):
        title = str(item.get("title", "")).strip()
        notice_id = f"MOH_{page_start}_{idx}"
        rows.append(
            {
                "source": "MY_MOH",
                "country": "Malaysia",
                "country_code": "MY",
                "publication_date": "",
                "title": title,
                "description": "",
                "buyer": "Ministry of Health Malaysia",
                "classification": "",
                "tender_status": "",
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": "https://www.moh.gov.my/tender/senarai-tender",
                "query_text": str(query_text or ""),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("MY_MOH", notice_id, title),
            }
        )
    if not rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Malaysia MOH tender list scaffold (MY_MOH)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Free-text tender search.")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Write discovery artifact then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="MY_MOH", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Malaysia MOH", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    parser.add_argument("--filter-match", default="any", choices=["any", "all", "exact"], help="Match mode")
    parser.add_argument("--start", type=int, default=0, help="Pagination start offset")

    add_standard_colab_args(parser, default_country="MY")
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
        base_dir = resolve_output_base_dir(output_target=args.output_target, region=args.region, website_id=args.website_id)
        layout = ensure_spec_folder_layout(base_dir)
        web_dir = Path(layout["web"])
        artifact = web_dir / f"my_moh_discovery_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        artifact.write_text(
            json.dumps(
                {
                    "ts_utc": _utc_now_iso(),
                    "listing_url": "https://www.moh.gov.my/tender/senarai-tender",
                    "filters": {
                        "filter-search": "text",
                        "filter-match": ["any", "all", "exact"],
                        "start": "pagination offset",
                    },
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        discover_summary = {"artifact": str(artifact)}

    import pandas as pd

    normalized_df = pd.DataFrame()
    if not bool(getattr(args, "discover_only", False)):
        try:
            normalized_df = fetch_records_requests(
                query_text=query_text,
                filter_match=str(args.filter_match),
                page_start=int(args.start),
            )
        except Exception as exc:
            logger.warning("MOH fetch failed: %s", exc)
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
