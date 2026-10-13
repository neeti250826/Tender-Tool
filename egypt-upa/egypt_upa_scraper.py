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

logger = logging.getLogger("egypt_upa_scraper")

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
            "Egypt UPA tenders (WordPress) filters:",
            "- listing: https://upa.gov.eg/tenders/ (public)",
            "- WordPress REST search: https://upa.gov.eg/wp-json/wp/v2/search?search=<text>",
            "- UI filters: site search box on /tenders/ (exact params not extracted; use --discover-only to capture HTML)",
        ]
    ) + "\n"


def _fetch(url: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return str(r.text or "")


def _parse_tender_cards(html: str) -> List[Dict[str, str]]:
    text = str(html or "")
    # Look for /download/<slug>/ links.
    link_re = re.compile(r'href="(?P<href>https://upa\.gov\.eg/download/[^\"]+/)"', flags=re.IGNORECASE)
    links = []
    for m in link_re.finditer(text):
        href = m.group("href")
        if href and href not in links:
            links.append(href)
    out: List[Dict[str, str]] = []
    for href in links[:50]:
        out.append({"notice_url": href})
    return out


def fetch_records_requests(*, query_text: str) -> "pd_types.DataFrame":
    import pandas as pd

    base = "https://upa.gov.eg/tenders/"
    html = _fetch(base)
    cards = _parse_tender_cards(html)
    scraped_at_utc = _utc_now_iso()
    rows: List[Dict[str, str]] = []
    for c in cards:
        url = str(c.get("notice_url", ""))
        notice_id = url.rstrip("/").split("/")[-1] if url else ""
        rows.append(
            {
                "source": "EG_UPA",
                "country": "Egypt",
                "country_code": "EG",
                "publication_date": "",
                "title": notice_id,
                "description": "",
                "buyer": "UPA Egypt",
                "classification": "",
                "tender_status": "",
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("EG_UPA", notice_id, url),
            }
        )
    if query_text:
        tokens = [t.lower() for t in re.split(r"\s+", query_text.strip()) if t]
        rows = [r for r in rows if any(t in str(r.get("title", "")).lower() for t in tokens)]

    if not rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Egypt UPA tenders scaffold (EG_UPA)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword search.")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Write discovery artifact then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="EG_UPA", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Egypt UPA", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    add_standard_colab_args(parser, default_country="EG")
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
        artifact = web_dir / f"eg_upa_discovery_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        artifact.write_text(
            json.dumps(
                {
                    "ts_utc": _utc_now_iso(),
                    "listing_url": "https://upa.gov.eg/tenders/",
                    "wp_search": "https://upa.gov.eg/wp-json/wp/v2/search?search=<text>",
                    "robots": "https://upa.gov.eg/robots.txt",
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
            normalized_df = fetch_records_requests(query_text=query_text)
        except Exception as exc:
            logger.warning("UPA fetch failed: %s", exc)
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
