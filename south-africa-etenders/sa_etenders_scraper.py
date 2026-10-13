from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import requests


logger = logging.getLogger("sa_etenders_scraper")

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


def _fetch_swagger_params() -> Dict[str, object]:
    url = "https://ocds-api.etenders.gov.za/swagger/v1/swagger.json"
    spec = requests.get(url, timeout=30).json()
    op = spec.get("paths", {}).get("/api/OCDSReleases", {}).get("get", {})
    params = op.get("parameters", [])
    return {
        "swagger_url": url,
        "endpoint": "https://ocds-api.etenders.gov.za/api/OCDSReleases",
        "parameters": [
            {
                "name": p.get("name"),
                "in": p.get("in"),
                "required": bool(p.get("required")) if p.get("required") is not None else False,
                "type": (p.get("schema", {}) or {}).get("type"),
                "format": (p.get("schema", {}) or {}).get("format"),
                "description": p.get("description", ""),
            }
            for p in params
        ],
    }


def list_advanced_filters() -> str:
    swagger = _fetch_swagger_params()
    lines = [
        "SA eTenders (OCDS API) filters:",
        f"- endpoint: {swagger.get('endpoint')}",
        f"- swagger: {swagger.get('swagger_url')}",
        "- query params:",
    ]
    for p in swagger.get("parameters", []):
        lines.append(
            f"    {p.get('name')} ({p.get('type')}{'/' + str(p.get('format')) if p.get('format') else ''}) in={p.get('in')}"
        )
    lines.extend(
        [
            "- additional post-filters supported by this tool:",
            "    --tender-status (e.g. active / cancelled / complete)",
            "    --category (matches tender.category)",
            "    --province (matches tender.province)",
        ]
    )
    return "\n".join(lines) + "\n"


def fetch_ocds_releases(
    *,
    date_from: str,
    date_to: str,
    page_number: int = 1,
    page_size: int = 50,
    tender_status: str = "",
    category: str = "",
    province: str = "",
) -> List[dict]:
    url = "https://ocds-api.etenders.gov.za/api/OCDSReleases"
    params = {
        "PageNumber": int(page_number),
        "PageSize": int(page_size),
        "dateFrom": str(date_from),
        "dateTo": str(date_to),
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    payload = r.json()
    releases = payload.get("releases", [])

    status_norm = str(tender_status or "").strip().lower()
    category_norm = str(category or "").strip().lower()
    province_norm = str(province or "").strip().lower()

    out: List[dict] = []
    for rel in releases:
        tender = (rel or {}).get("tender", {}) or {}
        st = str(tender.get("status", "") or "")
        cat = str(tender.get("category", "") or "")
        prov = str(tender.get("province", "") or "")
        if status_norm and st.strip().lower() != status_norm:
            continue
        if category_norm and cat.strip().lower() != category_norm:
            continue
        if province_norm and prov.strip().lower() != province_norm:
            continue
        out.append(rel)
    return out


def releases_to_normalized_df(releases: List[dict], *, query_text: str):
    import pandas as pd

    scraped_at_utc = _utc_now_iso()
    rows: List[Dict[str, str]] = []
    for rel in list(releases or []):
        tender = (rel or {}).get("tender", {}) or {}
        notice_id = str(tender.get("id", "") or rel.get("ocid", "") or "").strip()
        title = str(tender.get("title", "") or "").strip()
        status = str(tender.get("status", "") or "").strip()
        classification = str(tender.get("category", "") or "").strip()
        pub_date = str(rel.get("date", "") or "").strip()[:10]
        notice_url = ""
        if rel.get("ocid"):
            notice_url = f"https://ocds-api.etenders.gov.za/api/OCDSReleases/release/{rel.get('ocid')}"
        rows.append(
            {
                "source": "ZA_ETENDERS",
                "country": "South Africa",
                "country_code": "ZA",
                "publication_date": pub_date,
                "title": title,
                "description": "",
                "buyer": "",
                "classification": classification,
                "tender_status": status,
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("ZA_ETENDERS", notice_id, notice_url),
            }
        )
    if not rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="South Africa eTenders OCDS API scaffold (ZA_ETENDERS)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword token (stored only; API is date-based).")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Write filter discovery artifacts then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")

    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="ZA_ETENDERS", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="South Africa eTenders", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    parser.add_argument("--page-number", type=int, default=1, help="API PageNumber")
    parser.add_argument("--page-size", type=int, default=50, help="API PageSize")
    parser.add_argument("--tender-status", default="", help="Post-filter: tender.status")
    parser.add_argument("--category", default="", help="Post-filter: tender.category")
    parser.add_argument("--province", default="", help="Post-filter: tender.province")

    add_standard_colab_args(parser, default_country="ZA")
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
        artifact = web_dir / f"za_etenders_swagger_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        artifact.write_text(json.dumps(_fetch_swagger_params(), ensure_ascii=True, indent=2), encoding="utf-8")
        discover_summary = {"swagger_artifact": str(artifact)}

    releases = []
    if not bool(getattr(args, "discover_only", False)):
        releases = fetch_ocds_releases(
            date_from=date_from,
            date_to=date_to,
            page_number=int(args.page_number),
            page_size=int(args.page_size),
            tender_status=str(args.tender_status or ""),
            category=str(args.category or ""),
            province=str(args.province or ""),
        )

    import pandas as pd

    normalized_df = releases_to_normalized_df(releases, query_text=query_text)
    if normalized_df is None or len(getattr(normalized_df, "index", [])) == 0:
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
    mdt = result.get("mdt")
    if not isinstance(mdt, dict):
        mdt = {}
    logger.info("Run output: %s", spec.get("run_csv"))
    logger.info("Consolidated output: %s", spec.get("consolidated_csv"))
    logger.info("MDT CSV: %s", mdt.get("csv_path"))


if __name__ == "__main__":
    main()
