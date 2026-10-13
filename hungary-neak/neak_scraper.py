#!/usr/bin/env python3
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
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

if TYPE_CHECKING:
    import pandas as pd_types


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


pd = importlib.import_module("pandas")
requests = importlib.import_module("requests")

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


logger = logging.getLogger("neak_scraper")


NORMALIZED_COLUMNS: List[str] = [
    "source",
    "country",
    "country_code",
    "publication_date",
    "title",
    "description",
    "buyer",
    "classification",
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
    notice_id = "NEAK_PLACEHOLDER"
    notice_url = ""
    title = "NEAK scaffold placeholder"
    description = "Not implemented: HU_NEAK fetch/normalize pipeline is scaffolded only."

    row = {
        "source": "HU_NEAK",
        "country": "Hungary",
        "country_code": "HU",
        "publication_date": "",
        "title": title,
        "description": description,
        "buyer": "",
        "classification": "",
        "currency": "",
        "amount": "",
        "notice_id": notice_id,
        "notice_url": notice_url,
        "query_text": str(query_text or "").strip(),
        "scraped_at_utc": scraped_at_utc,
        "dedup_key": _stable_dedup_key("HU_NEAK", notice_id, str(query_text or "").strip()),
    }

    return pd.DataFrame([row]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def build_normalized_rows_from_links(links: Sequence[str], *, query_text: str) -> "pd_types.DataFrame":
    scraped_at_utc = _utc_now_iso()
    out_rows: List[Dict[str, str]] = []
    for link in list(links or []):
        url = str(link or "").strip()
        if not url:
            continue
        token_match = re.search(r"(\d{6}|\d{4})", url)
        token = token_match.group(1) if token_match else "NEAK"
        notice_id = f"NEAK_{token}"
        title = f"NEAK GYSE traffic data download ({token})"
        out_rows.append(
            {
                "source": "HU_NEAK",
                "country": "Hungary",
                "country_code": "HU",
                "publication_date": "",
                "title": title,
                "description": "",
                "buyer": "",
                "classification": "GYSE traffic data",
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("HU_NEAK", notice_id, url),
            }
        )
    if not out_rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(out_rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scaffold scraper for Hungary NEAK (HU_NEAK)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword search.")
    parser.add_argument("--output-target", default="", help="Google Drive URL or local output folder.")
    parser.add_argument(
        "--disable-deduplication", action="store_true", help="Disable default deduplication."
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Discover downloadable datasets/links and write web artifacts, then exit.",
    )

    parser.add_argument(
        "--project-name",
        default="MDT_2026",
        help="Project name token in outputs (PROJECT_NAME_YEAR).",
    )
    parser.add_argument("--website-id", default="HU_NEAK", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Hungary NEAK", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    add_standard_colab_args(parser, default_country="HU")
    return parser.parse_args(list(argv) if argv is not None else None)


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def extract_download_links(html: str, *, base_url: str) -> List[str]:
    """Extract likely dataset download links from NEAK HTML."""

    text = str(html or "")
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', text, flags=re.IGNORECASE)
    links: List[str] = []
    for href in hrefs:
        if not isinstance(href, str):
            continue
        lowered = href.lower()
        if any(token in lowered for token in [".zip", ".csv", ".xlsx", ".xls"]):
            links.append(urljoin(base_url, href))
    # Stable order and de-dupe
    seen = set()
    ordered: List[str] = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        ordered.append(link)
    return ordered


def discover_download_links_requests(
    *,
    query_text: str,
    output_target: str,
    region: str,
    website_id: str,
    timeout_seconds: int = 30,
) -> Tuple[str, List[str], str]:
    """Discover downloadable datasets on the NEAK page.

    Returns (artifact_path, links, error_message). Always best-effort.
    """

    base_dir = resolve_output_base_dir(
        output_target=output_target,
        region=region,
        website_id=website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    artifact_path = web_dir / f"neak_discovery_{_timestamp_token()}.json"

    url = "https://neak.gov.hu/felso_menu/szakmai_oldalak/publikus_forgalmi_adatok/gyse_forgalmi_adatok"
    links: List[str] = []
    error_message = ""
    try:
        response = requests.get(url, timeout=max(5, int(timeout_seconds)))
        response.raise_for_status()
        html = str(getattr(response, "text", "") or "")
        links = extract_download_links(html, base_url=url)
    except Exception as exc:
        error_message = f"requests_error: {exc}"

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts_utc": _utc_now_iso(),
        "source": "HU_NEAK",
        "query_text": str(query_text or ""),
        "page_url": url,
        "link_count": len(links),
        "links": links,
        "error": error_message,
    }
    artifact_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    return str(artifact_path), links, error_message


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
        artifact_path, links, error = discover_download_links_requests(
            query_text=query_text,
            output_target=args.output_target,
            region=args.region,
            website_id=args.website_id,
        )
        discover_summary = {
            "artifact_path": artifact_path,
            "link_count": len(links),
            "links": links,
            "error": error,
        }

    normalized_df = pd.DataFrame()
    raw_links = discover_summary.get("links")
    links: List[str] = raw_links if isinstance(raw_links, list) else []
    if links:
        normalized_df = build_normalized_rows_from_links(links, query_text=query_text)
    if normalized_df is None or len(getattr(normalized_df, "index", [])) == 0:
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
