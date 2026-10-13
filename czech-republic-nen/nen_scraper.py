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

logger = logging.getLogger("nen_scraper")

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
            "Czech NEN (CZ_NEN) public procurements advanced filters:",
            "- Website listing: https://nen.nipez.cz/en/verejne-zakazky/p:vz:page=1",
            "- This tool calls the public API used by the website:",
            "    https://nen.nipez.cz/api/datarows/datawithcount?className=Zadavaci_postup_hist",
            "",
            "User-facing filters:",
            "  --keywords (same as the page's search box)",
            "  --contracting-authority-name",
            "  --procedure-name",
            "  --nen-code (NEN system number)",
            "  --estimated-value-min / --estimated-value-max (CZK)",
            "  --deadline-from / --deadline-to (YYYY-MM-DD)",
            "  --page / --page-size",
        ]
    ) + "\n"


def discover_only(*, output_target: str, region: str, website_id: str) -> Dict[str, str]:
    base_dir = resolve_output_base_dir(output_target=output_target, region=region, website_id=website_id)
    layout = ensure_spec_folder_layout(base_dir)
    web_dir = Path(layout["web"])
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifacts: Dict[str, str] = {}

    listing = "https://nen.nipez.cz/en/verejne-zakazky/p:vz:page=1"
    html = requests.get(listing, timeout=30).text
    (web_dir / f"nen_listing_{ts}.html").write_text(html, encoding="utf-8")
    artifacts["listing_html"] = str(web_dir / f"nen_listing_{ts}.html")

    # NOTE: The main JS bundle name changes over time; we do not hardcode it here.
    # Keep the listing HTML which contains references if needed.

    return artifacts


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Czech NEN scaffold (CZ_NEN)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword search.")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--discover-only", action="store_true", help="Write discovery artifacts then exit.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="CZ_NEN", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Czech NEN", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    # User-facing filters (do not expose internal API field names)
    parser.add_argument("--contracting-authority-name", default="", help="Contracting authority name.")
    parser.add_argument("--procedure-name", default="", help="Procurement procedure name.")
    parser.add_argument("--nen-code", default="", help="NEN system number / procedure code.")
    parser.add_argument("--estimated-value-min", type=int, default=None, help="Estimated value min (CZK).")
    parser.add_argument("--estimated-value-max", type=int, default=None, help="Estimated value max (CZK).")
    parser.add_argument("--deadline-from", default="", help="Deadline from (YYYY-MM-DD).")
    parser.add_argument("--deadline-to", default="", help="Deadline to (YYYY-MM-DD).")
    parser.add_argument("--page", type=int, default=1, help="Page number (1-based).")
    parser.add_argument("--page-size", type=int, default=50, help="Results per page.")

    add_standard_colab_args(parser, default_country="CZ")
    return parser.parse_args(list(argv) if argv is not None else None)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_dedup_key(*parts: str) -> str:
    payload = "|".join([str(p or "").strip() for p in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _nen_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "language": "EN",
        }
    )
    # bootstrap cookies + XSRF tokens
    s.get("https://nen.nipez.cz/en/verejne-zakazky/p:vz:page=1", timeout=60)
    xsrf = s.cookies.get("XSRF-TOKEN-Client") or s.cookies.get("XSRF-TOKEN")
    if xsrf:
        s.headers.update({"x-xsrf-token": xsrf})
    return s


def _like_condition(server_field: str, *, param_index: int) -> Tuple[str, str]:
    # Uses the same pattern as the UI: :Linguistic.LIKE(field, @N) with %value%
    return f"(((((:Linguistic.LIKE({server_field}, @{param_index})))))", "like"


def _fulltext_condition(*, param_index: int) -> str:
    # Uses the same pattern as the UI.
    return f"(((((:DBNEN.FiltrovatZPNaLW(Fulltext_filtr, @{param_index}))))))"


def _date_range_condition(server_field: str, date_from: str, date_to: str) -> str:
    parts: List[str] = []
    if date_from:
        parts.append(f"({server_field} >= '{date_from}')")
    if date_to:
        parts.append(f"({server_field} <= '{date_to}')")
    if not parts:
        return ""
    if len(parts) == 1:
        return f"({parts[0]})"
    return f"(({parts[0]}) AND ({parts[1]}))"


def _numeric_range_condition(server_field: str, min_value: Optional[int], max_value: Optional[int]) -> str:
    parts: List[str] = []
    if min_value is not None:
        parts.append(f"({server_field} >= {int(min_value)})")
    if max_value is not None:
        parts.append(f"({server_field} <= {int(max_value)})")
    if not parts:
        return ""
    if len(parts) == 1:
        return f"({parts[0]})"
    return f"(({parts[0]}) AND ({parts[1]}))"


def fetch_procurements_requests(
    *,
    keywords: str,
    contracting_authority_name: str,
    procedure_name: str,
    nen_code: str,
    estimated_value_min: Optional[int],
    estimated_value_max: Optional[int],
    deadline_from: str,
    deadline_to: str,
    page: int,
    page_size: int,
) -> dict:
    s = _nen_session()

    attributes = [
        {"clientName": "id", "serverName": "ID"},
        {"clientName": "kod", "serverName": "Kod"},
        {"clientName": "nazev", "serverName": "Nazev"},
        {"clientName": "stavZP", "serverName": "Stav_ZP"},
        {"clientName": "zadavatelNazev", "serverName": "Zadavatel.Nazev"},
        {"clientName": "podaniLhuta", "serverName": "Podani_nabidka.Lhuta"},
        {"clientName": "predpokladHodnotaCZK", "serverName": "Predpokl_hodnota_CZK"},
        {"clientName": "cpvPredmetuKod", "serverName": "CPV_predmetu.Kod"},
    ]

    # Build UI-equivalent condition.
    base = "(Hierarchie = null and Posledni_uverejneni = true)"

    cond_parts: List[str] = []
    params: List[str] = []
    like_count = 0

    def add_like(server_field: str, value: str) -> None:
        nonlocal like_count
        v = str(value or "").strip()
        if not v:
            return
        idx = like_count
        like_count += 1
        cond_parts.append(f"(((((:Linguistic.LIKE({server_field}, @{idx})))))")
        params.append(f"%{v}%")

    add_like("Zadavatel.Nazev", contracting_authority_name)
    add_like("Nazev", procedure_name)
    add_like("Kod", nen_code)

    # Fulltext uses param index (like_count + 1), matching UI behavior.
    kw = str(keywords or "").strip()
    if kw:
        kw_idx = like_count + 1
        cond_parts.append(_fulltext_condition(param_index=kw_idx))
        params.append(kw)

    # Numeric/date ranges are inlined (no params), matching UI behavior.
    num_cond = _numeric_range_condition("Predpokl_hodnota_CZK", estimated_value_min, estimated_value_max)
    if num_cond:
        cond_parts.append(f"({num_cond})")

    date_cond = _date_range_condition("Podani_nabidka.Lhuta", deadline_from, deadline_to)
    if date_cond:
        cond_parts.append(f"({date_cond})")

    # Combine.
    if cond_parts:
        condition = " AND ".join(cond_parts + [base])
    else:
        condition = base

    payload = {
        "className": "Zadavaci_postup_hist",
        "attributes": attributes,
        "condition": condition,
        "conditionParams": params,
        "count": int(max(1, page_size)),
        "startIndex": int(max(0, (max(1, page) - 1) * int(max(1, page_size)))),
        "orderBy": ["DESC create_cas"],
        "abortSignal": {},
    }

    url = "https://nen.nipez.cz/api/datarows/datawithcount?className=Zadavaci_postup_hist"
    r = s.post(url, data=json.dumps(payload), timeout=60)
    r.raise_for_status()
    return json.loads(r.text)


def nen_payload_to_normalized_df(payload: dict, *, query_text: str):
    import pandas as pd

    items = (payload or {}).get("collection") or []
    scraped_at_utc = _utc_now_iso()
    rows: List[Dict[str, str]] = []
    for it in list(items or []):
        notice_id = str(it.get("kod") or it.get("id") or "").strip()
        title = str(it.get("nazev") or "").strip()
        buyer = str(it.get("zadavatelNazev") or "").strip()
        status = str(it.get("stavZP") or "").strip()
        deadline = str(it.get("podaniLhuta") or "").strip()[:10]
        notice_url = "https://nen.nipez.cz/en/verejne-zakazky/p:vz:page=1"
        rows.append(
            {
                "source": "CZ_NEN",
                "country": "Czech Republic",
                "country_code": "CZ",
                "publication_date": "",
                "title": title,
                "description": "",
                "buyer": buyer,
                "classification": str(it.get("cpvPredmetuKod") or ""),
                "tender_status": status,
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("CZ_NEN", notice_id, notice_url),
            }
        )

    if not rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


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
        discover_summary = discover_only(output_target=args.output_target, region=args.region, website_id=args.website_id)

    import pandas as pd

    normalized_df = pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    if not bool(getattr(args, "discover_only", False)):
        kw = str(query_text or "").strip()
        payload = fetch_procurements_requests(
            keywords=kw,
            contracting_authority_name=str(getattr(args, "contracting_authority_name", "") or "").strip(),
            procedure_name=str(getattr(args, "procedure_name", "") or "").strip(),
            nen_code=str(getattr(args, "nen_code", "") or "").strip(),
            estimated_value_min=getattr(args, "estimated_value_min", None),
            estimated_value_max=getattr(args, "estimated_value_max", None),
            deadline_from=str(getattr(args, "deadline_from", "") or "").strip(),
            deadline_to=str(getattr(args, "deadline_to", "") or "").strip(),
            page=int(getattr(args, "page", 1) or 1),
            page_size=int(getattr(args, "page_size", 50) or 50),
        )
        normalized_df = nen_payload_to_normalized_df(payload, query_text=query_text)
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
