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
from typing import Dict, List, Optional, Sequence

import requests

logger = logging.getLogger("ezamowienia_scraper")

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
            "Poland e-Zamowienia (BZP board API) advanced filters:",
            "- search endpoint (public): https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search",
            "- confirmed query params:",
            "    noticeType (e.g. ContractNotice)",
            "    isTenderAmountBelowEU (true/false)",
            "    SortingColumnName (e.g. PublicationDate)",
            "    SortingDirection (ASC/DESC)",
            "    PageNumber (1..)",
            "    PageSize (frontend uses it; support may exist)",
            "- get PDF by id: https://ezamowienia.gov.pl/mo-board/api/v1/Board/GetNoticePdfById?noticeId=<GUID>",
            "- NOTE: UI advanced filter labels are JS-rendered; use --discover-only + Playwright for full UI mapping.",
        ]
    ) + "\n"


def fetch_board_search(
    *,
    notice_type: str,
    below_eu: bool,
    page_number: int,
    page_size: int,
    sorting_column: str,
    sorting_direction: str,
) -> dict:
    url = "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"
    params = {
        "noticeType": str(notice_type),
        "isTenderAmountBelowEU": str(bool(below_eu)).lower(),
        "SortingColumnName": str(sorting_column),
        "SortingDirection": str(sorting_direction),
        "PageNumber": int(page_number),
    }
    # PageSize is supported by frontend; pass it if >0.
    if int(page_size) > 0:
        params["PageSize"] = int(page_size)
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def board_to_normalized_df(payload: dict, *, query_text: str):
    import pandas as pd

    scraped_at_utc = _utc_now_iso()
    items = payload.get("items") if isinstance(payload, dict) else None
    if items is None:
        # some versions might return a top-level list
        items = payload if isinstance(payload, list) else []

    rows: List[Dict[str, str]] = []
    for it in list(items or []):
        notice_id = str(it.get("objectId", "") or "").strip()
        title = str(it.get("orderObject", "") or "").strip()
        buyer = str(it.get("organizationName", "") or "").strip()
        pub = str(it.get("publicationDate", "") or "").strip()[:10]
        notice_url = ""
        if notice_id:
            notice_url = f"https://ezamowienia.gov.pl/mo-board/api/v1/Board/GetNoticePdfById?noticeId={notice_id}"
        rows.append(
            {
                "source": "PL_EZAMOWIENIA",
                "country": "Poland",
                "country_code": "PL",
                "publication_date": pub,
                "title": title,
                "description": "",
                "buyer": buyer,
                "classification": "",
                "tender_status": "",
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or ""),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("PL_EZAMOWIENIA", notice_id, notice_url),
            }
        )
    if not rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poland e-Zamowienia scaffold (PL_EZAMOWIENIA)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword token (stored only; API is param-based).")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Write discovery artifacts then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="PL_EZAMOWIENIA", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Poland e-Zamowienia", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    parser.add_argument("--notice-type", default="ContractNotice", help="noticeType")
    parser.add_argument("--below-eu", action="store_true", help="isTenderAmountBelowEU=true")
    parser.add_argument("--page-number", type=int, default=1, help="PageNumber")
    parser.add_argument("--page-size", type=int, default=0, help="PageSize (optional)")
    parser.add_argument("--sorting-column", default="PublicationDate", help="SortingColumnName")
    parser.add_argument("--sorting-direction", default="DESC", choices=["ASC", "DESC"], help="SortingDirection")

    add_standard_colab_args(parser, default_country="PL")
    return parser.parse_args(list(argv) if argv is not None else None)


def run(args: argparse.Namespace) -> Dict[str, object]:
    date_from, date_to, normalized_years = resolve_date_range(
        date_from=args.date_from,
        date_to=args.date_to,
        years=args.years,
    )
    query_text = build_query_text(args.query, args.keywords)
    keywords = build_run_keywords(keywords=args.keywords, query_text=query_text)

    discover_summary: Dict[str, object] = {}
    if bool(getattr(args, "list_advanced_filters", False)):
        print(list_advanced_filters())
        return {"date_from": date_from, "date_to": date_to, "query_text": query_text, "keywords": keywords}

    if bool(getattr(args, "discover_only", False)):
        base_dir = resolve_output_base_dir(output_target=args.output_target, region=args.region, website_id=args.website_id)
        layout = ensure_spec_folder_layout(base_dir)
        web_dir = Path(layout["web"])
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact = web_dir / f"pl_ezamowienia_config_{ts}.json"
        cfg = requests.get("https://ezamowienia.gov.pl/mo-board/api/v1/Config", timeout=30).json()
        artifact.write_text(json.dumps(cfg, ensure_ascii=True, indent=2), encoding="utf-8")
        discover_summary = {"config_artifact": str(artifact)}

    import pandas as pd

    normalized_df = pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    if not bool(getattr(args, "discover_only", False)):
        payload = fetch_board_search(
            notice_type=str(args.notice_type),
            below_eu=bool(args.below_eu),
            page_number=int(args.page_number),
            page_size=int(args.page_size),
            sorting_column=str(args.sorting_column),
            sorting_direction=str(args.sorting_direction),
        )
        normalized_df = board_to_normalized_df(payload, query_text=query_text)

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
