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


logger = logging.getLogger("ekr_scraper")

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
            "Hungary EKR (HU_EKR) public procurement notices filters:",
            "- Website: https://ekr.gov.hu/portal/kozbeszerzes/hirdetmenyek",
            "- This tool calls the public API: https://ekr.gov.hu/api/publikus/kozbeszerzesi-hirdetmenyek",
            "",
            "User-facing filters:",
            "  --any-words / --all-words / --exclude-words (content keywords)",
            "  --cpv-codes (repeatable; CPV codes)",
            "  --winner-name (winner supplier name)",
            "  --published-from / --published-to (YYYY-MM-DD)",
            "  --deadline-from / --deadline-to (YYYY-MM-DD)",
            "  --page / --page-size",
            "  --sort-by / --sort-direction",
        ]
    ) + "\n"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(p or "").strip() for p in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _date_to_api_range(value_ymd: str, *, is_end: bool) -> str:
    """Format date for EKR API.

    Observed format on the website: YYYY-MM-DDT00:00:00.000+0800 / ...T23:59:59.999+0800
    We send UTC (+0000) which the backend accepts in practice.
    """

    text = str(value_ymd or "").strip()
    if not text:
        return ""
    # Accept YYYY-MM-DD; do not parse locale formats.
    if is_end:
        return f"{text}T23:59:59.999+0000"
    return f"{text}T00:00:00.000+0000"


def fetch_ekr_notices_requests(
    *,
    page: int,
    page_size: int,
    sort_by: str,
    sort_direction: str,
    any_words: str,
    all_words: str,
    exclude_words: str,
    cpv_codes: Sequence[str],
    winner_name: str,
    published_from: str,
    published_to: str,
    deadline_from: str,
    deadline_to: str,
) -> dict:
    url = "https://ekr.gov.hu/api/publikus/kozbeszerzesi-hirdetmenyek"
    params: Dict[str, object] = {
        "oldal": int(max(1, page)),
        "elemszam": int(max(1, page_size)),
        "rendezes": str(sort_by or "ajanlatkeroNeve"),
        "novekvo": str(sort_direction or "asc").strip().lower() == "asc",
        "tartalombanSzereploSzavak": str(any_words or ""),
        "tartalombanMindSzereploSzavak": str(all_words or ""),
        "tartalombanNemSzereploSzavak": str(exclude_words or ""),
    }

    # Optional advanced filters discovered via Playwright.
    if cpv_codes:
        params["eljarasCPVkodok"] = ",".join([str(c).strip() for c in cpv_codes if str(c).strip()])
    if winner_name:
        params["eljarasNyertesAjanlattevoNeve"] = str(winner_name)
    if deadline_from:
        params["eljarasAjanlatteteliHataridoKezdet"] = _date_to_api_range(deadline_from, is_end=False)
    if deadline_to:
        params["eljarasAjanlatteteliHataridoVeg"] = _date_to_api_range(deadline_to, is_end=True)
    if published_from:
        params["hirdetmenyKozzetetelDatumaKezdet"] = _date_to_api_range(published_from, is_end=False)
    if published_to:
        params["hirdetmenyKozzetetelDatumaVeg"] = _date_to_api_range(published_to, is_end=True)

    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _to_ymd(value: str) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def ekr_payload_to_normalized_df(payload: dict, *, query_text: str):
    import pandas as pd

    items = []
    if isinstance(payload, dict):
        items = payload.get("lista") or []

    scraped_at_utc = _utc_now_iso()
    rows: List[Dict[str, str]] = []
    for it in list(items or []):
        notice_id = str(it.get("hirdetmenyEKRazonosito") or it.get("id") or "").strip()
        buyer = str(it.get("ajanlatkeroNeve") or "").strip()
        title = str(it.get("eljarasTargya") or "").strip()
        published = _to_ymd(str(it.get("hirdetmenyKozzetetelDatuma") or ""))
        deadline = _to_ymd(str(it.get("eljarasAjanlatteteliHatarido") or ""))
        notice_url = "https://ekr.gov.hu/portal/kozbeszerzes/hirdetmenyek"
        # Many items include a tedAzonosito; link to the portal listing as a stable public URL.
        rows.append(
            {
                "source": "HU_EKR",
                "country": "Hungary",
                "country_code": "HU",
                "publication_date": published,
                "title": title,
                "description": "",
                "buyer": buyer,
                "classification": "",
                "tender_status": "",
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("HU_EKR", notice_id, notice_url),
                "deadline": deadline,
            }
        )

    df = pd.DataFrame(rows)
    # Keep schema stable; ignore extra fields not in NORMALIZED_COLUMNS.
    return df.reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


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
    artifact_path = web_dir / f"ekr_discovery_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"

    records: List[dict] = []
    error_message = ""

    def should_capture(response) -> bool:
        try:
            req = response.request
            if getattr(req, "resource_type", "") in {"xhr", "fetch"}:
                return True
            headers = getattr(response, "headers", {}) or {}
            ct = str(headers.get("content-type", "") or "").lower()
            return ("json" in ct) or ct.startswith("text/")
        except Exception:
            return False

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

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
            # Go directly to public procurement notices search.
            page.goto(
                "https://ekr.gov.hu/portal/kozbeszerzes/hirdetmenyek",
                wait_until="domcontentloaded",
                timeout=timeout_seconds * 1000,
            )
            # Wait for the app to load and trigger initial list requests.
            page.wait_for_timeout(12000)
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
    parser = argparse.ArgumentParser(description="Hungary EKR scaffold (HU_EKR)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword token.")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Use Playwright to discover endpoints then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="HU_EKR", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Hungary EKR", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    # User-facing filters (do not expose internal param names)
    parser.add_argument("--any-words", default="", help="Any of these words (free text).")
    parser.add_argument("--all-words", default="", help="All of these words (free text).")
    parser.add_argument("--exclude-words", default="", help="Exclude these words (free text).")
    parser.add_argument("--cpv-codes", action="append", default=[], help="CPV code (repeatable).")
    parser.add_argument("--winner-name", default="", help="Winner supplier name (text).")
    parser.add_argument("--published-from", default="", help="Publication date from (YYYY-MM-DD).")
    parser.add_argument("--published-to", default="", help="Publication date to (YYYY-MM-DD).")
    parser.add_argument("--deadline-from", default="", help="Submission deadline from (YYYY-MM-DD).")
    parser.add_argument("--deadline-to", default="", help="Submission deadline to (YYYY-MM-DD).")
    parser.add_argument("--page", type=int, default=1, help="Results page (1-based).")
    parser.add_argument("--page-size", type=int, default=10, help="Results per page.")
    parser.add_argument(
        "--sort-by",
        default="ajanlatkeroNeve",
        help="Sort field (advanced). Default matches the website behaviour.",
    )
    parser.add_argument("--sort-direction", default="asc", choices=["asc", "desc"], help="Sort direction.")

    add_standard_colab_args(parser, default_country="HU")
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

    normalized_df = pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    if not bool(getattr(args, "discover_only", False)):
        # Map notebook/query into the site's native filter buckets.
        q = str(query_text or "").strip()
        any_words = str(getattr(args, "any_words", "") or "").strip() or q
        all_words = str(getattr(args, "all_words", "") or "").strip()
        exclude_words = str(getattr(args, "exclude_words", "") or "").strip()
        payload = fetch_ekr_notices_requests(
            page=int(args.page),
            page_size=int(args.page_size),
            sort_by=str(args.sort_by),
            sort_direction=str(args.sort_direction),
            any_words=any_words,
            all_words=all_words,
            exclude_words=exclude_words,
            cpv_codes=list(getattr(args, "cpv_codes", []) or []),
            winner_name=str(getattr(args, "winner_name", "") or "").strip(),
            published_from=str(getattr(args, "published_from", "") or "").strip(),
            published_to=str(getattr(args, "published_to", "") or "").strip(),
            deadline_from=str(getattr(args, "deadline_from", "") or "").strip(),
            deadline_to=str(getattr(args, "deadline_to", "") or "").strip(),
        )
        normalized_df = ekr_payload_to_normalized_df(payload, query_text=query_text)

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
