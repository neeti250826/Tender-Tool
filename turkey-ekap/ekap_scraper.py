from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence


logger = logging.getLogger("ekap_scraper")

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


def _curl_json(url: str, *, method: str = "GET", payload: Optional[dict] = None) -> object:
    cmd = [
        "curl",
        "-s",
        "-H",
        "Accept: application/json",
    ]
    if method.upper() == "POST":
        cmd += ["-H", "Content-Type: application/json", "-X", "POST", "--data", json.dumps(payload or {}, ensure_ascii=True)]
    cmd.append(url)
    out = subprocess.check_output(cmd).decode("utf-8", errors="ignore")
    return json.loads(out) if out.strip() else None


def _ekap_lookup(lookup_type: str) -> List[dict]:
    url = "https://ekapv2.kik.gov.tr/b_ihalearama/api/Lookup/GetListByType"
    data = _curl_json(url, method="POST", payload={"lookupType": lookup_type})
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return list(data.get("list") or [])
    return []


def list_advanced_filters() -> str:
    statuses = _ekap_lookup("TenderStatusCombo")
    status_labels = ", ".join(sorted({str(it.get("name") or "") for it in statuses if str(it.get("name") or "").strip()}))
    return "\n".join(
        [
            "Turkey EKAP (TR_EKAP) — tender search filters:",
            "- Website: https://ekapv2.kik.gov.tr/ekap/search",
            "- API (used by website): https://ekapv2.kik.gov.tr/b_ihalearama/api/Ihale/GetListByParameters",
            "",
            "User-facing filters:",
            "  --search-text (keywords or IKN fragments)",
            "  --search-in (ikn|title|both)",
            "  --ikn (e.g. 2026/271215) OR --ikn-year + --ikn-number",
            "  --tender-type (Goods|Services|Works|Consultancy; repeatable)",
            "  --tender-status (by label; one of: " + (status_labels or "(unavailable)") + ")",
            "  --province (e.g. Ankara)",
            "  --page / --page-size",
        ]
    ) + "\n"


def _resolve_status_value(label: str) -> str:
    want = str(label or "").strip().lower()
    if not want:
        return ""
    items = _ekap_lookup("TenderStatusCombo")
    for it in items:
        nm = str(it.get("name") or "").strip().lower()
        if nm == want:
            return str(it.get("value") or "").strip()
    for it in items:
        nm = str(it.get("name") or "").strip().lower()
        if want in nm and nm:
            return str(it.get("value") or "").strip()
    raise ValueError(f"Unknown tender status: {label}")


def _resolve_province_ids(name: str) -> List[int]:
    want = str(name or "").strip().lower()
    if not want:
        return []
    url = "https://ekapv2.kik.gov.tr/b_ihalearama/api/Il/GetAllIl"
    data = _curl_json(url)
    if not isinstance(data, list):
        return []
    matches: List[int] = []
    for it in data:
        nm = str((it or {}).get("name") or "").strip().lower()
        if nm == want or (want in nm and nm):
            try:
                matches.append(int((it or {}).get("id")))
            except Exception:
                continue
    return sorted({m for m in matches})


def _resolve_tender_type_ids(types: Sequence[str]) -> List[int]:
    mapping = {
        "goods": 1,
        "mal": 1,
        "services": 3,
        "hizmet": 3,
        "works": 2,
        "yapim": 2,
        "consultancy": 4,
        "danismanlik": 4,
    }
    out: List[int] = []
    for t in list(types or []):
        key = str(t or "").strip().lower()
        if not key:
            continue
        if key in mapping:
            out.append(mapping[key])
            continue
        raise ValueError(f"Unknown tender type: {t}. Use Goods/Services/Works/Consultancy")
    return sorted({x for x in out})


def fetch_tenders_requests(
    *,
    search_text: str,
    search_in: str,
    ikn: str,
    ikn_year: Optional[int],
    ikn_number: Optional[int],
    tender_types: Sequence[str],
    tender_status: str,
    province: str,
    page: int,
    page_size: int,
) -> dict:
    url = "https://ekapv2.kik.gov.tr/b_ihalearama/api/Ihale/GetListByParameters"

    # Defaults observed from the UI request.
    payload: Dict[str, object] = {
        "searchText": str(search_text or ""),
        "filterType": None,
        "ikNdeAra": search_in in {"ikn", "both"},
        "ihaleAdindaAra": search_in in {"title", "both"},
        "searchType": "GirdigimGibi",
        "iknYili": None,
        "iknSayi": None,
        "ihaleTarihSaatBaslangic": None,
        "ihaleTarihSaatBitis": None,
        "ilanTarihSaatBaslangic": None,
        "ilanTarihSaatBitis": None,
        "yasaKapsami4734List": [1],
        "ihaleTuruIdList": _resolve_tender_type_ids(tender_types) or [1, 2, 3, 4],
        "ihaleUsulIdList": [],
        "ihaleUsulAltIdList": [],
        "ihaleIlIdList": _resolve_province_ids(province),
        "ihaleDurumIdList": [],
        "ihaleIlanTuruIdList": [],
        "teklifTuruIdList": [],
        "asiriDusukTeklifIdList": [],
        "istisnaMaddeIdList": [],
        "okasBransKodList": [],
        "okasBransAdiList": [],
        "titubbKodList": [],
        "gmdnKodList": [],
        "eIhale": None,
        "eEksiltmeYapilacakMi": None,
        "ortakAlimMi": None,
        "kismiTeklifMi": None,
        "fiyatDisiUnsurVarmi": None,
        "ekonomikVeMaliYeterlilikBelgeleriIsteniyorMu": None,
        "meslekiTeknikYeterlilikBelgeleriIsteniyorMu": None,
        "isDeneyimiGosterenBelgelerIsteniyorMu": None,
        "yerliIstekliyeFiyatAvantajiUgulaniyorMu": None,
        "yabanciIsteklilereIzinVeriliyorMu": None,
        "alternatifTeklifVerilebilirMi": None,
        "konsorsiyumKatilabilirMi": None,
        "altYukleniciCalistirilabilirMi": None,
        "fiyatFarkiVerilecekMi": None,
        "avansVerilecekMi": None,
        "cerceveAnlasmaMi": None,
        "personelCalistirilmasinaDayaliMi": None,
        "orderBy": "ihaleTarihi",
        "siralamaTipi": "desc",
        "paginationSkip": int(max(0, (max(1, page) - 1) * int(max(1, page_size)))),
        "paginationTake": int(max(1, page_size)),
    }

    if ikn:
        # Prefer full IKN.
        payload["searchText"] = str(ikn)
        payload["ikNdeAra"] = True
        payload["ihaleAdindaAra"] = False
    if ikn_year is not None:
        payload["iknYili"] = int(ikn_year)
    if ikn_number is not None:
        payload["iknSayi"] = int(ikn_number)

    if tender_status:
        payload["ihaleDurumIdList"] = [str(_resolve_status_value(tender_status))]

    data = _curl_json(url, method="POST", payload=payload)
    return data if isinstance(data, dict) else {"list": []}


def ekap_payload_to_normalized_df(payload: dict, *, query_text: str):
    import pandas as pd

    items = payload.get("list") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []
    scraped_at_utc = _utc_now_iso()
    rows: List[Dict[str, str]] = []
    for it in list(items or []):
        notice_id = str(it.get("ikn") or it.get("id") or "").strip()
        title = str(it.get("ihaleAdi") or "").strip()
        status = str(it.get("ihaleDurumAciklama") or it.get("ihaleDurum") or "").strip()
        notice_url = "https://ekapv2.kik.gov.tr/ekap/search"
        rows.append(
            {
                "source": "TR_EKAP",
                "country": "Turkey",
                "country_code": "TR",
                "publication_date": "",
                "title": title,
                "description": "",
                "buyer": "",
                "classification": str(it.get("ihaleTipAciklama") or "").strip(),
                "tender_status": status,
                "currency": "",
                "amount": "",
                "notice_id": notice_id,
                "notice_url": notice_url,
                "query_text": str(query_text or "").strip(),
                "scraped_at_utc": scraped_at_utc,
                "dedup_key": _stable_dedup_key("TR_EKAP", notice_id, notice_url),
            }
        )
    if not rows:
        return pd.DataFrame([]).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")
    return pd.DataFrame(rows).reindex(columns=list(NORMALIZED_COLUMNS)).fillna("")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Turkey EKAP tender search (TR_EKAP)")
    parser.add_argument("--date-from", default=None, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--date-to", default=None, help="End date (YYYY-MM-DD).")
    parser.add_argument("--query", default="", help="Optional keyword token.")
    parser.add_argument("--output-target", default="", help="Local output folder.")
    parser.add_argument("--disable-deduplication", action="store_true", help="Disable default deduplication.")
    parser.add_argument("--list-advanced-filters", action="store_true", help="Print available filters and exit.")
    parser.add_argument("--project-name", default="MDT_2026", help="Project name token in outputs.")
    parser.add_argument("--website-id", default="TR_EKAP", help="Website ID (uppercase underscore).")
    parser.add_argument("--source-label", default="Turkey EKAP", help="Human readable source label.")
    parser.add_argument("--region", default="EMEA", choices=["EMEA", "LATAM"], help="Regional output routing.")

    parser.add_argument("--search-text", default="", help="Search text.")
    parser.add_argument("--search-in", default="both", choices=["ikn", "title", "both"], help="Where to apply search text.")
    parser.add_argument("--ikn", default="", help="IKN (e.g., 2026/271215).")
    parser.add_argument("--ikn-year", type=int, default=None, help="IKN year (optional).")
    parser.add_argument("--ikn-number", type=int, default=None, help="IKN number (optional).")
    parser.add_argument("--tender-status", default="", help="Tender status label (e.g., Cancelled).")
    parser.add_argument("--tender-type", action="append", default=[], help="Tender type (Goods/Services/Works/Consultancy). Repeatable.")
    parser.add_argument("--province", default="", help="Province name (e.g., Ankara).")
    parser.add_argument("--page", type=int, default=1, help="Page (1-based).")
    parser.add_argument("--page-size", type=int, default=10, help="Results per page.")

    add_standard_colab_args(parser, default_country="TR")
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

    import pandas as pd

    # Build defaults: if user didn't supply --search-text, use combined query_text.
    search_text = str(getattr(args, "search_text", "") or "").strip() or str(query_text or "").strip()
    payload = fetch_tenders_requests(
        search_text=search_text,
        search_in=str(getattr(args, "search_in", "both")),
        ikn=str(getattr(args, "ikn", "") or "").strip(),
        ikn_year=getattr(args, "ikn_year", None),
        ikn_number=getattr(args, "ikn_number", None),
        tender_types=list(getattr(args, "tender_type", []) or []),
        tender_status=str(getattr(args, "tender_status", "") or "").strip(),
        province=str(getattr(args, "province", "") or "").strip(),
        page=int(getattr(args, "page", 1) or 1),
        page_size=int(getattr(args, "page_size", 10) or 10),
    )
    normalized_df = ekap_payload_to_normalized_df(payload, query_text=query_text)
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
