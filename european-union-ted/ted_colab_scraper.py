#!/usr/bin/env python3
"""
TED Europa tender scraper (Google Colab ready).

Uses the official TED Search API:
POST https://api.ted.europa.eu/v3/notices/search

High-level flow:
1) Build one or more TED expert queries from user inputs.
2) Scrape and normalize records into a stable output schema.
3) Save per-run and consolidated Excel outputs for downstream ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import zipfile
import requests


API_URL = "https://api.ted.europa.eu/v3/notices/search"
DEFAULT_TENDER_MASTER_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1ozkdrx67lcrkP4ssbhpf5VpFauHZ71GQ_8Az8q2oHyk/edit?gid=0#gid=0"
)
SINGAPORE_TZ = timezone(timedelta(hours=8), name="Asia/Singapore")
DEFAULT_MASTER_WORKSHEET = "Tender Data Master"


RAW_FIELDS: List[str] = [
    "publication-number",
    "publication-date",
    "classification-cpv",
    "main-classification-proc",
    "main-classification-lot",
    "main-classification-part",
    "contract-nature-main-proc",
    "contract-nature-main-lot",
    "contract-nature",
    "place-of-performance",
    "place-of-performance-city-proc",
    "place-of-performance-country-proc",
    "place-of-performance-subdiv-proc",
    "place-of-performance-add-proc",
    "buyer-name",
    "buyer-country",
    "winner-name",
    "winner-selection-status",
    "value-prize-lot",
    "value-prize-cur-lot",
    "tender-value",
    "tender-value-cur",
    "result-value-lot",
    "result-value-cur-lot",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "total-value",
    "description-proc",
    "description-lot",
    "description-glo",
    "title-proc",
    "title-lot",
    "tendering-party-name",
    "participant-name-lot",
]


# Final row shape produced by scraper pages.
# This keeps native TED fields and adds standardized helper fields used downstream.
OUTPUT_COLUMNS: List[str] = RAW_FIELDS + [
    "Notice publication number",
    "source_url",
    "CPV",
    "Currency",
    "Main classification",
    "Main nature of the contract",
    "Place of performance",
    "Buyer name",
    "Country",
    "Winner name",
    "Value of the prize",
    "Value of the tender",
    "Year",
    "Publication Date",
    "Description",
    "Description_en",
    "Description_translated",
    "Winner selection status",
    "Players",
]

RAW_EXTRACT_COLUMNS: List[str] = OUTPUT_COLUMNS + [
    "source_website",
    "project",
    "query_text",
    "record_key",
    "run_extract",
    "project_extract",
    "ingested_at",
]

# Columns expected by the Tender Data Master sheet sync step.
MASTER_COLUMNS: List[str] = [
    "project",
    "source_website",
    "source_url",
    "Google Drive Url",
    "source_record_id",
    "record_key",
    "ingested_at",
    "title",
    "Value_Amonunt",
    "value_currency",
    "granting_authority",
    "awardee",
    "closing_date",
    "status",
    "description",
    "country",
    "country_code",
    "quantity",
    "buying_organization",
    "contracting_organization",
    "Start Date",
    "End Date",
    "specialty_area",
    "device_category",
    "therapeutic_area",
    "change_type",
    "updated_at",
]

DEFAULT_HEADERS = {
    "User-Agent": "ted-colab-scraper/1.0 (+https://ted.europa.eu/)",
    "Accept": "application/json",
}

COUNTRY_ALPHA3_TO_NAME: Dict[str, str] = {
    "AUT": "Austria",
    "BEL": "Belgium",
    "BGR": "Bulgaria",
    "CHE": "Switzerland",
    "CYP": "Cyprus",
    "CZE": "Czechia",
    "DEU": "Germany",
    "DNK": "Denmark",
    "ESP": "Spain",
    "EST": "Estonia",
    "FIN": "Finland",
    "FRA": "France",
    "GBR": "United Kingdom",
    "GRC": "Greece",
    "HRV": "Croatia",
    "HUN": "Hungary",
    "IRL": "Ireland",
    "ISR": "Israel",
    "ISL": "Iceland",
    "ITA": "Italy",
    "LIE": "Liechtenstein",
    "LTU": "Lithuania",
    "LUX": "Luxembourg",
    "LVA": "Latvia",
    "MLT": "Malta",
    "NLD": "Netherlands",
    "NOR": "Norway",
    "POL": "Poland",
    "PRT": "Portugal",
    "ROU": "Romania",
    "RUS": "Russia",
    "SVK": "Slovakia",
    "SVN": "Slovenia",
    "SWE": "Sweden",
    "TUR": "Turkey",
    "UKR": "Ukraine",
}

COUNTRY_NAME_ALIASES: Dict[str, str] = {
    "eu7": "FRA DEU ITA ESP GBR IRL AUT",
    "se": "RUS POL UKR GRC ROU CZE TUR",
    "nw": "NLD CHE FIN PRT ISR BEL",
    "czech republic": "CZE",
    "great britain": "GBR",
    "uk": "GBR",
    "u.k.": "GBR",
    "the netherlands": "NLD",
    "england": "GBR",
}

COUNTRY_NAME_TO_ALPHA3: Dict[str, str] = {
    **{name.lower(): code for code, name in COUNTRY_ALPHA3_TO_NAME.items()},
    **COUNTRY_NAME_ALIASES,
}

_MACHINE_TRANSLATOR: Any = None
_MACHINE_TRANSLATOR_READY = False
_TRANSLATION_CACHE: Dict[str, str] = {}
_TRANSLATION_CACHE_ORDER: List[str] = []


@dataclass
class ScrapeConfig:
    limit: int = 100
    scope: str = "ALL"
    only_latest_versions: bool = True
    pagination_mode: str = "ITERATION"
    request_timeout_seconds: int = 60
    pause_seconds: float = 1.25
    pause_every_pages: int = 0
    auto_pause_seconds: float = 0.0
    max_retries: int = 7
    checkpoint_path: Optional[Path] = None
    stream_csv_path: Optional[Path] = None
    verbose_progress: bool = True
    translation_pause_seconds: float = 0.35
    translation_max_retries: int = 3
    translation_skip_before_year: Optional[int] = None
    translation_cache_size: int = 10000


def _dedupe_preserve(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _flatten_to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            out.extend(_flatten_to_list(item))
        return out
    if isinstance(value, dict):
        out = []
        for nested in value.values():
            out.extend(_flatten_to_list(nested))
        return out
    return [str(value)]


def _join_value(value: Any) -> str:
    return ", ".join(_dedupe_preserve(_flatten_to_list(value)))


def _extract_i18n(value: Any, preferred_lang: str = "eng") -> str:
    if not isinstance(value, dict):
        return _join_value(value)

    for key, lang_value in value.items():
        if key.lower() == preferred_lang.lower():
            return _join_value(lang_value)

    return _join_value(value)


def _extract_i18n_with_flag(value: Any, preferred_lang: str = "eng") -> tuple[str, bool]:
    if not isinstance(value, dict):
        return (_join_value(value), False)

    for key, lang_value in value.items():
        if key.lower() == preferred_lang.lower():
            extracted = _join_value(lang_value)
            if extracted:
                return (extracted, True)

    return (_join_value(value), False)


def _split_for_translation(text: str, max_chunk_len: int = 4200) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chunk_len:
        return [cleaned]

    chunks: List[str] = []
    current = []
    current_len = 0
    for token in cleaned.split():
        token_len = len(token) + (1 if current else 0)
        if current_len + token_len > max_chunk_len:
            chunks.append(" ".join(current))
            current = [token]
            current_len = len(token)
        else:
            current.append(token)
            current_len += token_len

    if current:
        chunks.append(" ".join(current))
    return chunks


def _get_machine_translator() -> Any:
    global _MACHINE_TRANSLATOR, _MACHINE_TRANSLATOR_READY

    if _MACHINE_TRANSLATOR_READY:
        return _MACHINE_TRANSLATOR

    _MACHINE_TRANSLATOR_READY = True
    try:
        from deep_translator import GoogleTranslator  # type: ignore

        _MACHINE_TRANSLATOR = GoogleTranslator(source="auto", target="en")
    except Exception:
        _MACHINE_TRANSLATOR = None
    return _MACHINE_TRANSLATOR


def _translate_to_english(text: str) -> tuple[str, bool]:
    source = str(text or "").strip()
    if not source:
        return ("", False)

    translator = _get_machine_translator()
    if translator is None:
        return (source, False)

    chunks = _split_for_translation(source)
    translated_parts: List[str] = []
    try:
        for chunk in chunks:
            translated_parts.append(str(translator.translate(chunk) or "").strip())
    except Exception:
        return (source, False)

    merged = " ".join([part for part in translated_parts if part]).strip()
    return (merged or source, True)


def _cache_get_translation(source_text: str) -> Optional[str]:
    key = str(source_text or "").strip()
    if not key:
        return None
    return _TRANSLATION_CACHE.get(key)


def _cache_set_translation(source_text: str, translated_text: str, *, max_size: int) -> None:
    key = str(source_text or "").strip()
    if not key:
        return

    if key in _TRANSLATION_CACHE:
        _TRANSLATION_CACHE[key] = translated_text
        return

    _TRANSLATION_CACHE[key] = translated_text
    _TRANSLATION_CACHE_ORDER.append(key)

    while len(_TRANSLATION_CACHE_ORDER) > max(1, int(max_size)):
        oldest = _TRANSLATION_CACHE_ORDER.pop(0)
        _TRANSLATION_CACHE.pop(oldest, None)


def _pick_first_non_empty(*candidates: Any) -> str:
    for candidate in candidates:
        value = _join_value(candidate)
        if value:
            return value
    return ""


def _year_from_date(value: Any) -> str:
    text = _join_value(value)
    if not text:
        return ""
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else ""


def _normalize_key_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _to_text_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def _is_operation_not_supported(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    if getattr(exc, "errno", None) == 95:
        return True
    message = str(exc).lower()
    return "operation not supported" in message


def _is_drive_shortcut_projection(path: Path) -> bool:
    return "/.shortcut-targets-by-id/" in path.as_posix()


def write_excel_with_fallback(df: pd.DataFrame, output_path: Path, *, index: bool = False) -> Path:
    if _is_drive_shortcut_projection(output_path):
        fallback_name = f"ted_output_{output_path.stem}_{os.getpid()}.xlsx"
        fallback_path = Path(tempfile.gettempdir()) / fallback_name
        df.to_excel(fallback_path, index=index)
        print(
            "[INFO] Drive shortcut path detected; writing XLSX to local temp file: "
            f"{_safe_display_path(fallback_path)}"
        )
        return fallback_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_excel(output_path, index=index)
        return output_path
    except OSError as first_exc:
        temp_path: Optional[Path] = None
        keep_temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(prefix="ted_tmp_", suffix=".xlsx", delete=False) as tmp:
                temp_path = Path(tmp.name)
            df.to_excel(temp_path, index=index)
            try:
                shutil.copyfile(temp_path, output_path)
                if temp_path.exists():
                    temp_path.unlink()
                return output_path
            except OSError as copy_exc:
                if _is_operation_not_supported(copy_exc):
                    fallback_name = f"ted_output_{output_path.stem}_{os.getpid()}.xlsx"
                    fallback_path = Path(tempfile.gettempdir()) / fallback_name
                    if temp_path != fallback_path:
                        shutil.copyfile(temp_path, fallback_path)
                        keep_temp_path = fallback_path
                    else:
                        keep_temp_path = temp_path
                    print(
                        "[WARN] XLSX destination does not support direct writes; "
                        f"using local temp file instead: {keep_temp_path}"
                    )
                    if temp_path.exists() and temp_path != keep_temp_path:
                        temp_path.unlink()
                    return keep_temp_path
                raise first_exc from copy_exc
        except Exception:
            raise first_exc
        finally:
            if temp_path and temp_path.exists() and temp_path != keep_temp_path:
                temp_path.unlink()


def _safe_write_excel(df: pd.DataFrame, output_path: Path, *, index: bool = False) -> Path:
    writer = globals().get("write_excel_with_fallback")
    if callable(writer):
        return writer(df, output_path, index=index)
    print(
        "[WARN] write_excel_with_fallback is missing; falling back to pandas.to_excel()."
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=index)
    return output_path


def _build_record_key_column(df: pd.DataFrame) -> pd.Series:
    """Build record key in format <source-abbrev>-<surrogate-key>."""
    if df.empty:
        return pd.Series(dtype=str)

    cpv = _to_text_series(df, "CPV")
    if cpv.str.strip().eq("").all() and "specialty_area" in df.columns:
        cpv = _to_text_series(df, "specialty_area")
    cpv = cpv.map(_normalize_key_text)

    buyer = _to_text_series(df, "Buyer name")
    if buyer.str.strip().eq("").all() and "granting_authority" in df.columns:
        buyer = _to_text_series(df, "granting_authority")
    buyer = buyer.map(_normalize_key_text)

    country = _to_text_series(df, "Country")
    if country.str.strip().eq("").all() and "country_code" in df.columns:
        country = _to_text_series(df, "country_code")
    country = country.map(_normalize_key_text)

    year = _to_text_series(df, "Year")
    if year.str.strip().eq("").all() and "Start Date" in df.columns:
        year = _to_text_series(df, "Start Date")
    year = year.map(_normalize_key_text)

    source_site = _to_text_series(df, "source_website")
    if source_site.str.strip().eq("").all() and "Source" in df.columns:
        source_site = _to_text_series(df, "Source")

    def _source_abbrev(raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return "TED"
        first_token = re.split(r"\s+", text)[0]
        caps = "".join(ch for ch in first_token if ch.isupper())
        if len(caps) >= 2:
            return caps[:6]
        token = re.sub(r"[^A-Za-z0-9]", "", first_token).upper()
        return token[:6] if token else "TED"

    source_prefix = source_site.map(_source_abbrev)

    fallback_seed = cpv + "|" + buyer + "|" + country + "|" + year
    surrogate_key = fallback_seed.map(
        lambda value: hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    )
    return source_prefix + "-" + surrogate_key


def _ensure_text_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.fillna("").astype(str)


def _ensure_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in OUTPUT_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out = out.reindex(columns=OUTPUT_COLUMNS)
    return _ensure_text_df(out)


def _ensure_master_columns(
    df: pd.DataFrame,
    *,
    default_source: str,
    default_project: str,
) -> pd.DataFrame:
    out = df.copy()
    for column in MASTER_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out = out.reindex(columns=MASTER_COLUMNS)
    out = _ensure_text_df(out)

    if default_source:
        source_empty = out["source_website"].map(lambda value: not str(value).strip())
        out.loc[source_empty, "source_website"] = default_source
    if default_project:
        project_empty = out["project"].map(lambda value: not str(value).strip())
        out.loc[project_empty, "project"] = default_project

    # Always normalize record_key to current format for both old and new rows.
    out["record_key"] = _build_record_key_column(out)
    return out


def _ensure_raw_extract_columns(
    df: pd.DataFrame,
    *,
    default_source: str,
    default_project: str,
) -> pd.DataFrame:
    out = df.copy()
    for column in RAW_EXTRACT_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out = out.reindex(columns=RAW_EXTRACT_COLUMNS)
    out = _ensure_text_df(out)

    if default_source:
        source_empty = out["source_website"].map(lambda value: not str(value).strip())
        out.loc[source_empty, "source_website"] = default_source
    if default_project:
        project_empty = out["project"].map(lambda value: not str(value).strip())
        out.loc[project_empty, "project"] = default_project

    out["record_key"] = _build_record_key_column(out)
    return out


def _partition_identity_series(
    df: pd.DataFrame,
    partition_columns: Optional[List[str]] = None,
) -> pd.Series:
    parts = partition_columns or ["Source", "Project"]
    normalized_parts = [
        _to_text_series(df, column).map(_normalize_key_text)
        for column in parts
    ]
    dedup_key = _to_text_series(df, "Dedup key").map(_normalize_key_text)

    if not normalized_parts:
        return dedup_key

    partition_key = normalized_parts[0]
    for part in normalized_parts[1:]:
        partition_key = partition_key + "\x1f" + part
    return partition_key + "\x1f" + dedup_key


def deduplicate_output_rows(df: pd.DataFrame) -> pd.DataFrame:
    out = _ensure_output_columns(df)
    dedup_key = _build_record_key_column(out)
    keep_mask = ~dedup_key.duplicated(keep="last")
    return out.loc[keep_mask].reset_index(drop=True)


def prepare_master_rows(
    df: pd.DataFrame,
    *,
    source: str,
    project: str,
    query_text: str,
    google_drive_url: str = "",
    run_id: Optional[str] = None,
    ingested_at_utc: Optional[str] = None,
) -> pd.DataFrame:
    out = _ensure_output_columns(df)
    now = datetime.now(SINGAPORE_TZ)
    run_id_value = run_id or now.strftime("%Y%m%d")
    ingested_value = ingested_at_utc or now.strftime("%m/%d/%Y")
    dedup_key = _build_record_key_column(out)

    master = pd.DataFrame(index=out.index, columns=MASTER_COLUMNS).fillna("")

    master["project"] = project.strip() if project else ""
    master["source_website"] = source.strip() if source else "TED Europa API"
    master["source_url"] = out["Notice publication number"].apply(
        lambda x: f"https://ted.europa.eu/en/notice/-/detail/{x}" if str(x).strip() else ""
    )
    raw_file_url = str(google_drive_url or "").strip()
    master["Google Drive Url"] = raw_file_url

    master["source_record_id"] = out["Notice publication number"]
    master["record_key"] = dedup_key
    master["ingested_at"] = now.strftime("%m/%d/%Y") # Just the date
    master["title"] = out["Description_en"].replace("", pd.NA).fillna(out["Description"]).fillna("")  # TED doesn't always have a strict title, description captures it best
    # Fill Values - Prefer tender value over prize
    master["Value_Amonunt"] = out["Value of the tender"].replace("", pd.NA).fillna(out["Value of the prize"]).fillna("")
    master["value_currency"] = out["Currency"]
    master["granting_authority"] = out["Buyer name"]
    master["awardee"] = out["Winner name"]
    master["closing_date"] = ""  # Not consistently available in basic search response
    master["status"] = out["Winner selection status"]
    master["description"] = out["Description_en"].replace("", pd.NA).fillna(out["Description"]).fillna("")
    # Country requirements:
    # - country: full country name
    # - country_code: ISO alpha-2 code
    country_alpha3_to_alpha2 = {
        "AUT": "AT", "BEL": "BE", "BGR": "BG", "HRV": "HR", "CYP": "CY",
        "CZE": "CZ", "DNK": "DK", "EST": "EE", "FIN": "FI", "FRA": "FR",
        "DEU": "DE", "GRC": "GR", "HUN": "HU", "IRL": "IE", "ITA": "IT",
        "LVA": "LV", "LTU": "LT", "LUX": "LU", "MLT": "MT", "NLD": "NL",
        "POL": "PL", "PRT": "PT", "ROU": "RO", "SVK": "SK", "SVN": "SI",
        "ESP": "ES", "SWE": "SE", "GBR": "GB", "NOR": "NO", "CHE": "CH",
        "ISL": "IS", "LIE": "LI"
    }
    country_alpha3_to_name = COUNTRY_ALPHA3_TO_NAME
    
    master["country_code"] = out["Country"].map(lambda x: country_alpha3_to_alpha2.get(str(x).strip().upper(), str(x).strip()[:2]))
    master["country"] = out["Country"].map(lambda x: country_alpha3_to_name.get(str(x).strip().upper(), str(x).strip()))
    master["quantity"] = ""
    master["buying_organization"] = out["Buyer name"]
    master["contracting_organization"] = out["Buyer name"]
    master["Start Date"] = out["Publication Date"]
    master["End Date"] = ""
    master["specialty_area"] = out["Main classification"].replace("", pd.NA).fillna(out["CPV"]).fillna("")
    master["device_category"] = ""
    master["therapeutic_area"] = ""
    master["change_type"] = out["Main nature of the contract"]
    master["updated_at"] = now.strftime("%m/%d/%Y")
    # Verify all columns strictly match MASTER_COLUMNS exactly
    return master.reindex(columns=MASTER_COLUMNS).fillna("").astype(str)


def prepare_raw_extract_rows(
    df: pd.DataFrame,
    *,
    source: str,
    project: str,
    query_text: str,
    google_drive_url: str = "",
    ingested_at_utc: Optional[str] = None,
) -> pd.DataFrame:
    out = _ensure_output_columns(df)
    now = datetime.now(SINGAPORE_TZ)
    ingested_value = ingested_at_utc or now.strftime("%m/%d/%Y")

    raw = pd.DataFrame(index=out.index, columns=RAW_EXTRACT_COLUMNS).fillna("")
    for column in OUTPUT_COLUMNS:
        raw[column] = out[column]

    raw["source_website"] = source.strip() if source else "TED Europa API"
    raw["project"] = project.strip() if project else "Tender Data Master"
    raw["query_text"] = query_text.strip() if query_text else ""
    raw["record_key"] = _build_record_key_column(out)
    
    raw_file_url = str(google_drive_url or "").strip()
    raw["run_extract"] = raw_file_url
        
    raw["project_extract"] = _sanitize_name_token(project, fallback="TED_EUROPA")
    raw["ingested_at"] = ingested_value
    return raw.reindex(columns=RAW_EXTRACT_COLUMNS).fillna("").astype(str)


def deduplicate_master_rows(
    df: pd.DataFrame,
    *,
    partition_columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    identity = _partition_identity_series(df, partition_columns=partition_columns)
    keep_mask = ~identity.duplicated(keep="last")
    return df.loc[keep_mask].reset_index(drop=True)


def _authenticate_colab_user_if_available() -> None:
    try:
        from google.colab import auth as colab_auth  # type: ignore
    except ImportError:
        return
    colab_auth.authenticate_user()


def _build_gspread_client(
    *,
    google_credentials_file: Optional[Path] = None,
) -> Any:
    try:
        import gspread  # type: ignore
        from google.auth import default as google_auth_default  # type: ignore
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Google Sheets dependencies are missing. Install requirements.txt first."
        ) from exc

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if google_credentials_file:
        creds = ServiceAccountCredentials.from_service_account_file(
            str(google_credentials_file),
            scopes=scopes,
        )
    else:
        creds, _ = google_auth_default(scopes=scopes)
    return gspread.authorize(creds)


def _open_or_create_worksheet(
    spreadsheet: Any,
    worksheet_name: Optional[str],
    *,
    create_if_missing: bool = False,
) -> Any:
    if not worksheet_name:
        return spreadsheet.sheet1

    try:
        return spreadsheet.worksheet(worksheet_name)
    except Exception:
        if create_if_missing:
            return spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=40)
        raise RuntimeError(
            f"Worksheet '{worksheet_name}' was not found in the target spreadsheet. "
            "Sync requires updating an existing tab and will not create a new tab."
        )


def _worksheet_to_df(worksheet: Any) -> pd.DataFrame:
    values = worksheet.get_all_values()
    if not values:
        return pd.DataFrame(columns=MASTER_COLUMNS)
    headers = values[0]
    rows = values[1:]
    if not headers:
        return pd.DataFrame(columns=MASTER_COLUMNS)
    return pd.DataFrame(rows, columns=headers).fillna("")


def _worksheet_to_df_with_columns(worksheet: Any, columns: List[str]) -> pd.DataFrame:
    values = worksheet.get_all_values()
    if not values:
        return pd.DataFrame(columns=columns)
    headers = values[0]
    rows = values[1:]
    if not headers:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=headers).fillna("")



def _truncate_for_gsheets(val: Any, max_len: int = 49000) -> str:
    """Truncate a value to fit within Google Sheets' 50k character limit."""
    text = str(val)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text

def _write_full_sheet_with_columns(worksheet: Any, df: pd.DataFrame, columns: List[str]) -> None:
    # Truncate strings to fit Google Sheets 50k cell limit
    df_safe = df.reindex(columns=columns).fillna("").map(_truncate_for_gsheets) if hasattr(df, 'map') else df.reindex(columns=columns).fillna("").applymap(_truncate_for_gsheets)
    payload = [columns] + df_safe.values.tolist()
    worksheet.clear()

    current_rows = worksheet.row_count
    needed_rows = len(payload)
    if needed_rows > current_rows:
        worksheet.add_rows(needed_rows - current_rows + 500)

    worksheet.update(payload, value_input_option="USER_ENTERED")


def _write_full_sheet(worksheet: Any, df: pd.DataFrame) -> None:
    df_safe = df.fillna("").map(_truncate_for_gsheets) if hasattr(df, 'map') else df.fillna("").applymap(_truncate_for_gsheets)
    payload = [df_safe.columns.tolist()] + df_safe.values.tolist()
    worksheet.clear()
    
    # Ensure worksheet is large enough for the payload
    current_rows = worksheet.row_count
    needed_rows = len(payload)
    if needed_rows > current_rows:
        worksheet.add_rows(needed_rows - current_rows + 500)
        
    worksheet.update(payload, value_input_option="USER_ENTERED")


def sync_master_sheet(
    *,
    df: pd.DataFrame,
    sheet_url: str,
    worksheet_name: str,
    source: str,
    project: str,
    query_text: str,
    google_drive_url: str = "",
    google_credentials_file: Optional[Path] = None,
    partition_columns: Optional[List[str]] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Append new rows to the master Google Sheet with global deduplication.

    Dedup strategy:
      - Primary key: ``Notice publication number`` (stored in the Dedup key column
        as ``notice:<pub_number>``).
      - Fallback key: SHA-1 hash of CPV + Buyer name + Country + Year.
      - Dedup is GLOBAL across the entire sheet — Source/Project are metadata
        columns for tracking, NOT part of the uniqueness identity.  The same
        tender will not be inserted twice regardless of which project or query
        found it.

    Large-sheet optimisation:
      Instead of downloading all 22 columns, we first read ONLY the header row
      and the Dedup key column.  A full sheet read is performed only when the
      header schema needs repair.
    """
    if not sheet_url.strip():
        raise ValueError("Google Sheet URL is required.")
    _authenticate_colab_user_if_available()
    client = _build_gspread_client(google_credentials_file=google_credentials_file)
    spreadsheet = client.open_by_url(sheet_url.strip())
    worksheet = _open_or_create_worksheet(
        spreadsheet,
        worksheet_name,
        create_if_missing=False,
    )
    # --- Prepare incoming rows with master schema + dedup keys ---
    incoming = prepare_master_rows(
        df,
        source=source,
        project=project,
        query_text=query_text,
        google_drive_url=google_drive_url,
    )
    # Deduplicate within the incoming batch itself (on dedup key only).
    incoming_keys = _to_text_series(incoming, "record_key").map(_normalize_key_text)
    incoming = incoming.loc[~incoming_keys.duplicated(keep="last")].reset_index(drop=True)
    incoming_keys = _to_text_series(incoming, "record_key").map(_normalize_key_text)
    # --- Read existing sheet (optimised: header + dedup key column only) ---
    header_row = worksheet.row_values(1)
    sheet_is_empty = not header_row or all(not str(h).strip() for h in header_row)
    if sheet_is_empty:
        # Brand-new sheet — write everything.
        _write_full_sheet(worksheet, incoming)
        if verbose:
            print(
                f"Google Sheets sync complete: +{len(incoming)} new rows "
                f"(sheet total={len(incoming)}) in tab '{worksheet.title}'."
            )
        return incoming
    # Check whether the existing header matches the expected master schema.
    header_mismatch = header_row != MASTER_COLUMNS
    incoming_new = pd.DataFrame(columns=MASTER_COLUMNS)  # default empty
    overwritten_count = 0
    if header_mismatch:
        # Merge: concat existing + ALL incoming, then dedup keeping latest (incoming wins).
        existing_raw = _worksheet_to_df(worksheet)
        existing = _ensure_master_columns(
            existing_raw, default_source=source, default_project=project,
        )
        existing_dk = _to_text_series(existing, "record_key").map(_normalize_key_text)
        existing = existing.loc[~existing_dk.duplicated(keep="last")].reset_index(drop=True)
        combined = pd.concat([existing, incoming], ignore_index=True)
        combined_keys = _to_text_series(combined, "record_key").map(_normalize_key_text)
        combined = combined.loc[~combined_keys.duplicated(keep="last")].reset_index(drop=True)

        # Calculate stats for logging
        existing_key_set = set(
            _to_text_series(existing, "record_key").map(_normalize_key_text).tolist()
        )
        is_new = ~incoming_keys.isin(existing_key_set)
        incoming_new = incoming.loc[is_new].reset_index(drop=True)
        overwritten_count = len(incoming) - len(incoming_new)

        _write_full_sheet(worksheet, combined)
        final_count = len(combined)
        final_df = combined
    else:
        # Header is correct — optimised path: only fetch the record_key column.
        dedup_col_index = MASTER_COLUMNS.index("record_key") + 1  # 1-based
        existing_dedup_values = worksheet.col_values(dedup_col_index)
        # Skip header row (first element).
        existing_key_set = set(
            _normalize_key_text(v) for v in existing_dedup_values[1:] if str(v).strip()
        )

        is_new = ~incoming_keys.isin(existing_key_set)
        incoming_new = incoming.loc[is_new].reset_index(drop=True)

        # Check if any incoming rows would OVERWRITE existing rows
        has_duplicates = incoming_keys.isin(existing_key_set).any()

        if has_duplicates:
            # Must do full read + merge + rewrite to replace old rows
            existing_raw = _worksheet_to_df(worksheet)
            existing = _ensure_master_columns(
                existing_raw, default_source=source, default_project=project,
            )
            combined = pd.concat([existing, incoming], ignore_index=True)
            combined_keys = _to_text_series(combined, "record_key").map(_normalize_key_text)
            combined = combined.loc[~combined_keys.duplicated(keep="last")].reset_index(drop=True)
            _write_full_sheet(worksheet, combined)
            final_count = len(combined)
            overwritten_count = len(incoming) - len(incoming_new)
            final_df = combined
        else:
            # No duplicates — keep efficient append-only path
            overwritten_count = 0
            if not incoming_new.empty:
                current_rows = worksheet.row_count
                used_rows = len(existing_dedup_values)
                needed_rows = used_rows + len(incoming_new)
                if needed_rows > current_rows:
                    worksheet.add_rows(needed_rows - current_rows + 500)

                df_safe = incoming_new.fillna("").map(_truncate_for_gsheets) if hasattr(incoming_new, 'map') else incoming_new.fillna("").applymap(_truncate_for_gsheets)
                worksheet.append_rows(df_safe.values.tolist(), value_input_option="USER_ENTERED")

            existing_count = max(len(existing_dedup_values) - 1, 0)
            final_count = existing_count + len(incoming_new)
            final_df = incoming_new
    if verbose:
        overwrite_msg = f", {overwritten_count} overwritten" if overwritten_count > 0 else ""
        print(
            f"Google Sheets sync complete: +{len(incoming_new)} new rows{overwrite_msg} "
            f"(sheet total={final_count}) in tab '{worksheet.title}'."
        )
    return final_df


def sync_raw_extract_sheet(
    *,
    df: pd.DataFrame,
    sheet_url: str,
    worksheet_name: str,
    source: str,
    project: str,
    query_text: str,
    google_drive_url: str = "",
    google_credentials_file: Optional[Path] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    if not sheet_url.strip():
        raise ValueError("Google Sheet URL is required.")

    _authenticate_colab_user_if_available()
    client = _build_gspread_client(google_credentials_file=google_credentials_file)
    spreadsheet = client.open_by_url(sheet_url.strip())
    worksheet = _open_or_create_worksheet(
        spreadsheet,
        worksheet_name,
        create_if_missing=False,
    )

    incoming = prepare_raw_extract_rows(
        df,
        source=source,
        project=project,
        query_text=query_text,
        google_drive_url=google_drive_url,
    )
    incoming_keys = _to_text_series(incoming, "record_key").map(_normalize_key_text)
    incoming = incoming.loc[~incoming_keys.duplicated(keep="last")].reset_index(drop=True)
    incoming_keys = _to_text_series(incoming, "record_key").map(_normalize_key_text)
    overwritten_count = 0
    header_row = worksheet.row_values(1)

    sheet_is_empty = not header_row or all(not str(h).strip() for h in header_row)

    if sheet_is_empty:
        _write_full_sheet_with_columns(worksheet, incoming, RAW_EXTRACT_COLUMNS)
        final_count = len(incoming)
        new_rows = incoming
    else:
        header_mismatch = header_row != RAW_EXTRACT_COLUMNS
        if header_mismatch:
            existing_raw = _worksheet_to_df_with_columns(worksheet, RAW_EXTRACT_COLUMNS)
            existing = _ensure_raw_extract_columns(
                existing_raw,
                default_source=source,
                default_project=project,
            )
            existing_keys = _to_text_series(existing, "record_key").map(_normalize_key_text)
            existing = existing.loc[~existing_keys.duplicated(keep="last")].reset_index(drop=True)
            existing_key_set = set(
                _to_text_series(existing, "record_key").map(_normalize_key_text).tolist()
            )

            # Merge: concat existing + ALL incoming, dedup keeping latest
            combined = pd.concat([existing, incoming], ignore_index=True)
            combined_keys = _to_text_series(combined, "record_key").map(_normalize_key_text)
            combined = combined.loc[~combined_keys.duplicated(keep="last")].reset_index(drop=True)

            is_new = ~incoming_keys.isin(existing_key_set)
            new_rows = incoming.loc[is_new].reset_index(drop=True)
            overwritten_count = len(incoming) - len(new_rows)

            _write_full_sheet_with_columns(worksheet, combined, RAW_EXTRACT_COLUMNS)
            final_count = len(combined)
        else:
            dedup_col_index = RAW_EXTRACT_COLUMNS.index("record_key") + 1
            existing_dedup_values = worksheet.col_values(dedup_col_index)
            existing_key_set = set(
                _normalize_key_text(v) for v in existing_dedup_values[1:] if str(v).strip()
            )
            is_new = ~incoming_keys.isin(existing_key_set)
            new_rows = incoming.loc[is_new].reset_index(drop=True)

            has_duplicates = incoming_keys.isin(existing_key_set).any()

            if has_duplicates:
                existing_raw = _worksheet_to_df_with_columns(worksheet, RAW_EXTRACT_COLUMNS)
                existing = _ensure_raw_extract_columns(
                    existing_raw, default_source=source, default_project=project,
                )
                combined = pd.concat([existing, incoming], ignore_index=True)
                combined_keys = _to_text_series(combined, "record_key").map(_normalize_key_text)
                combined = combined.loc[~combined_keys.duplicated(keep="last")].reset_index(drop=True)
                _write_full_sheet_with_columns(worksheet, combined, RAW_EXTRACT_COLUMNS)
                final_count = len(combined)
                overwritten_count = len(incoming) - len(new_rows)
            else:
                overwritten_count = 0
                if not new_rows.empty:
                    current_rows = worksheet.row_count
                    used_rows = len(existing_dedup_values)
                    needed_rows = used_rows + len(new_rows)
                    if needed_rows > current_rows:
                        worksheet.add_rows(needed_rows - current_rows + 500)
                    df_safe = new_rows.fillna("").map(_truncate_for_gsheets) if hasattr(new_rows, 'map') else new_rows.fillna("").applymap(_truncate_for_gsheets)
                    worksheet.append_rows(df_safe.values.tolist(), value_input_option="USER_ENTERED")

                existing_count = max(len(existing_dedup_values) - 1, 0)
                final_count = existing_count + len(new_rows)

    worksheet_url = f"{spreadsheet.url.split('#')[0]}#gid={worksheet.id}"

    if verbose:
        overwrite_msg = f", {overwritten_count} overwritten" if overwritten_count > 0 else ""
        print(
            f"Raw extract sync complete: +{len(new_rows)} new rows{overwrite_msg} "
            f"(sheet total={final_count}) in tab '{worksheet.title}'."
        )

    return {
        "new_rows": new_rows,
        "new_rows_count": len(new_rows),
        "total_rows": final_count,
        "worksheet_name": worksheet.title,
        "worksheet_url": worksheet_url,
    }


def build_expert_query_from_keywords(keywords: List[str]) -> str:
    cleaned = [kw.strip() for kw in keywords if kw and kw.strip()]
    if not cleaned:
        raise ValueError("At least one non-empty keyword is required.")

    escaped = [kw.replace('"', '\\"') for kw in cleaned]
    if len(escaped) == 1:
        return f'FT~"{escaped[0]}"'
    return " OR ".join([f'FT~"{kw}"' for kw in escaped])


def parse_country_filter(country_names_text: str) -> tuple[List[str], List[str]]:
    tokens = [part.strip() for part in str(country_names_text or "").split(",") if part.strip()]
    country_codes: List[str] = []
    unknown_names: List[str] = []

    for token in tokens:
        key = token.lower()
        if key in COUNTRY_NAME_TO_ALPHA3:
            mapped = COUNTRY_NAME_TO_ALPHA3[key]
            country_codes.extend(mapped.split())
            continue
        upper = token.upper()
        if upper in COUNTRY_ALPHA3_TO_NAME:
            country_codes.append(upper)
            continue
        unknown_names.append(token)

    return (_dedupe_preserve(country_codes), unknown_names)


def parse_year_filter(years_text: str, default_years: Optional[List[int]] = None) -> List[int]:
    defaults = default_years or [2024, 2025]
    text = str(years_text or "").strip()
    if not text:
        return defaults

    years: List[int] = []
    for part in re.split(r"[;,]+", text):
        token = part.strip()
        if not token:
            continue
        if not re.fullmatch(r"\d{4}", token):
            raise ValueError(f"Invalid year token: '{token}'. Use 4-digit years, comma-separated.")
        years.append(int(token))

    if not years:
        return defaults
    if any(year < 1900 or year > 2100 for year in years):
        raise ValueError("Year values must be between 1900 and 2100.")
    return [int(y) for y in _dedupe_preserve([str(y) for y in years])]


def parse_cpv_filter(cpv_text: str, default_cpv_codes: Optional[List[str]] = None) -> List[str]:
    defaults = default_cpv_codes or ["33*", "38*"]
    text = str(cpv_text or "").strip()
    if not text:
        return defaults

    values: List[str] = []
    for part in re.split(r"[;,]+", text):
        token = part.strip().replace(" ", "")
        if not token:
            continue
        if not re.fullmatch(r"\d{2,8}\*?", token):
            raise ValueError(
                f"Invalid CPV token: '{token}'. Use values like 33*, 33000000, 33696500."
            )
        values.append(token)

    if not values:
        return defaults
    return _dedupe_preserve(values)


def sanitize_filename_part(value: Any, *, fallback: str = "na") -> str:
    # Keep run filenames cross-platform safe and predictable.
    text = str(value or "").strip()
    if not text:
        return fallback
    normalized = re.sub(r"[\s,;]+", "-", text)
    normalized = re.sub(r"[^A-Za-z0-9._-]", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized or fallback


def _normalize_run_date_token(value: Any) -> str:
    """
    Extract a YYYYMMDD token from flexible timestamp inputs.

    This keeps naming stable even if a caller still passes older
    date-time style values.
    """
    text = str(value or "").strip()
    match = re.search(r"(19|20)\d{6}", text)
    if match:
        return match.group(0)
    return datetime.now(SINGAPORE_TZ).strftime("%Y%m%d")


def build_run_filename(
    *,
    country_filter: str,
    keywords_filter: str,
    years_filter: str,
    run_timestamp: str,
    extension: str = ".xlsx",
) -> str:
    # Date-only naming convention: <...>_<YYYYMMDD>.xlsx
    country_part = sanitize_filename_part(country_filter)
    keyword_part = sanitize_filename_part(keywords_filter)
    years_part = sanitize_filename_part(years_filter)
    ts_part = sanitize_filename_part(_normalize_run_date_token(run_timestamp))
    ext = extension if str(extension).startswith(".") else f".{extension}"
    return f"{country_part}_{keyword_part}_{years_part}_{ts_part}{ext}"


def _normalize_year_values(years: Optional[List[str]]) -> List[str]:
    if not years:
        return []
    out: List[str] = []
    seen = set()
    for raw in years:
        year = str(raw or "").strip()
        if not re.fullmatch(r"(19|20)\d{2}", year):
            continue
        if year in seen:
            continue
        seen.add(year)
        out.append(year)
    return out


def _sanitize_name_token(value: str, *, fallback: str = "NA") -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip().upper())
    token = re.sub(r"_+", "_", token).strip("_")
    return token or fallback


def _as_hyperlink(url: str, *, link_text: str = "Raw Output File") -> str:
    safe_url = str(url or "").strip().replace('"', '""')
    if not safe_url:
        return ""
    safe_text = str(link_text or "Raw Output File").replace('"', '""')
    return f'=HYPERLINK("{safe_url}", "{safe_text}")'


def _safe_display_path(value: Path) -> str:
    return value.name


def _build_search_year_range_token(years: Optional[List[str]]) -> str:
    year_values = _normalize_year_values(years)
    if not year_values:
        return "ALL_YEARS"
    year_numbers = sorted({int(item) for item in year_values})
    if len(year_numbers) == 1:
        return f"{year_numbers[0] % 100:02d}"
    return f"{year_numbers[0] % 100:02d}-{year_numbers[-1] % 100:02d}"


def _build_keywords_token(
    keywords: Optional[List[str]],
    *,
    fallback_query: Optional[str] = None,
    max_len: int = 10,
) -> str:
    keyword_tokens: List[str] = []
    if keywords:
        for raw in keywords:
            normalized = re.sub(r"[^A-Za-z0-9]+", "-", str(raw or "").strip())
            normalized = re.sub(r"-+", "-", normalized).strip("-")
            if normalized:
                keyword_tokens.append(normalized)
    token = "-".join(_dedupe_preserve(keyword_tokens))

    if not token and fallback_query:
        query_stub = re.sub(r"[^A-Za-z0-9]+", "-", str(fallback_query or "").strip())
        query_stub = re.sub(r"-+", "-", query_stub).strip("-")
        if query_stub:
            token = f"QUERY-{query_stub}"

    if not token:
        token = "NO-KEYWORD"

    if len(token) <= max_len:
        return token
    return token[:max_len].rstrip("-") or "NO-KEYWORD"


def build_run_output_stem(
    *,
    project_name: str,
    years: Optional[List[str]],
    keywords: Optional[List[str]],
    expert_query: Optional[str],
    run_timestamp: str,
) -> str:
    # Canonical stem used by run outputs:
    # <PROJECT_NAME>_<YEAR_RANGE_SHORT>_<KEYWORDS_COMBO>_<YYYYMMDD>
    project_token = _sanitize_name_token(project_name, fallback="PROJECT")
    year_token = _build_search_year_range_token(years)
    keyword_token = _build_keywords_token(keywords, fallback_query=expert_query)
    run_date = _normalize_run_date_token(run_timestamp)
    return f"{project_token}_{year_token}_{keyword_token}_{run_date}"


def build_filtered_query(
    base_query: str,
    *,
    years: Optional[List[int]] = None,
    country_codes: Optional[List[str]] = None,
    cpv_codes: Optional[List[str]] = None,
) -> str:
    query = str(base_query or "").strip()
    if not query:
        raise ValueError("Base expert query cannot be empty.")

    clauses: List[str] = []

    cleaned_countries = [code.strip().upper() for code in (country_codes or []) if str(code).strip()]
    if cleaned_countries:
        clauses.append(f"buyer-country IN ({' '.join(_dedupe_preserve(cleaned_countries))})")

    cleaned_years = [int(y) for y in (years or [])]
    if cleaned_years:
        year_start = min(cleaned_years)
        year_end = max(cleaned_years)
        clauses.append(f"publication-date = ({year_start}0101 <> {year_end}1231)")

    cleaned_cpv = [code.strip() for code in (cpv_codes or []) if str(code).strip()]
    if cleaned_cpv:
        if len(cleaned_cpv) == 1 and "*" not in cleaned_cpv[0]:
            clauses.append(f"classification-cpv = {cleaned_cpv[0]}")
        elif len(cleaned_cpv) == 1 and "*" in cleaned_cpv[0]:
            clauses.append(f"classification-cpv = {cleaned_cpv[0]}")
        elif any("*" in code for code in cleaned_cpv):
            cpv_parts = [f"classification-cpv = {code}" for code in cleaned_cpv]
            clauses.append(f"({' OR '.join(cpv_parts)})")
        else:
            clauses.append(f"classification-cpv IN ({' '.join(_dedupe_preserve(cleaned_cpv))})")

    if not clauses:
        return query
    return f"({query}) AND {' AND '.join(clauses)}"


class TEDEuropaScraper:
    def __init__(self, config: ScrapeConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.non_english_count = 0
        self.translated_count = 0

    def _should_translate_for_year(self, year_text: str) -> bool:
        cutoff = self.config.translation_skip_before_year
        if cutoff is None:
            return True
        if not str(year_text or "").isdigit():
            return True
        return int(year_text) >= int(cutoff)

    def _translate_with_controls(self, text: str) -> tuple[str, bool]:
        source = str(text or "").strip()
        if not source:
            return ("", False)

        cached = _cache_get_translation(source)
        if cached is not None:
            return (cached, True)

        if _get_machine_translator() is None:
            return (source, False)

        max_retries = max(1, int(self.config.translation_max_retries))
        for attempt in range(max_retries):
            translated, ok = _translate_to_english(source)
            if ok:
                _cache_set_translation(
                    source,
                    translated,
                    max_size=max(1, int(self.config.translation_cache_size)),
                )
                pause = float(self.config.translation_pause_seconds)
                if pause > 0:
                    time.sleep(pause)
                return (translated, True)

            if attempt < max_retries - 1:
                pause = max(float(self.config.translation_pause_seconds), 0.0) + (2 ** attempt) * 0.5
                time.sleep(pause)

        return (source, False)

    def _append_rows_to_csv(self, rows: List[Dict[str, str]], write_header: bool) -> bool:
        if not self.config.stream_csv_path or not rows:
            return write_header
        self.config.stream_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=OUTPUT_COLUMNS).to_csv(
            self.config.stream_csv_path,
            mode="a",
            header=write_header,
            index=False,
            encoding="utf-8-sig",
        )
        return False

    def _request_with_backoff(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        for attempt in range(self.config.max_retries):
            try:
                response = self.session.post(
                    API_URL,
                    json=payload,
                    timeout=self.config.request_timeout_seconds,
                )

                if response.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(
                        f"Retryable HTTP {response.status_code}", response=response
                    )

                if response.status_code >= 400:
                    try:
                        error_payload = response.json()
                    except ValueError:
                        response.raise_for_status()
                    raise RuntimeError(
                        f"TED API error {response.status_code}: {json.dumps(error_payload, ensure_ascii=False)}"
                    )

                return response.json()

            except (requests.RequestException, RuntimeError) as exc:
                if attempt >= self.config.max_retries - 1:
                    raise RuntimeError(f"Request failed after retries: {exc}") from exc
                base_delay = min(2 ** attempt, 30)
                jitter = random.uniform(0.0, 0.75)
                time.sleep(base_delay + jitter)

        raise RuntimeError("Unexpected request loop termination")

    def _save_checkpoint(
        self,
        *,
        query: str,
        token: Optional[str],
        pages_scraped: int,
        records_scraped: int,
    ) -> None:
        if not self.config.checkpoint_path:
            return
        self.config.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "query": query,
            "iterationNextToken": token,
            "pages_scraped": pages_scraped,
            "records_scraped": records_scraped,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.config.checkpoint_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _load_checkpoint(self, query: str) -> Optional[str]:
        if not self.config.checkpoint_path or not self.config.checkpoint_path.exists():
            return None

        payload = json.loads(self.config.checkpoint_path.read_text(encoding="utf-8"))
        if payload.get("query") != query:
            return None
        return payload.get("iterationNextToken")

    def _normalize_notice(self, notice: Dict[str, Any]) -> Dict[str, str]:
        """
        Maps the raw JSON response from TED API to the intermediate raw schema.
        (Note: The final mapping to the Google Sheet 27-column schema is done
        in prepare_master_rows, which pulls from these extracted fields).

        --- RAW SCHEMA EXTRACTION HIERARCHY ---
        Notice publication number   <- publication-number
        CPV                         <- classification-cpv
        Currency                    <- [1] tender-value-cur | [2] result-value-cur-lot | [3] estimated-value-cur-proc | [4] value-prize-cur-lot
        Main classification         <- [1] main-classification-proc | [2] main-classification-lot | [3] main-classification-part | [4] classification-cpv
        Main nature of the contract <- [1] contract-nature-main-proc | [2] contract-nature-main-lot | [3] contract-nature
        Place of performance        <- [1] place-of-performance | [2] place-of-performance-city-proc | [3] ...country-proc | [4] ...subdiv-proc | [5] ...add-proc
        Buyer name                  <- buyer-name (localized extraction)
        Country                     <- buyer-country
        Winner name                 <- winner-name
        Value of the prize          <- value-prize-lot
        Value of the tender         <- [1] tender-value | [2] result-value-lot | [3] estimated-value-proc | [4] total-value
        Year                        <- publication-date (extracted YYYY)
        Description                 <- First valid from: description-proc | description-lot | description-glo | title-proc | title-lot
        Description_en              <- English extraction of the same fallback sequence as Description
        Winner selection status     <- winner-selection-status
        Players                     <- Joined: tendering-party-name, participant-name-lot, winner-name
        ----------------------
        """
        cpv = _join_value(notice.get("classification-cpv"))
        currency = _pick_first_non_empty(
            notice.get("tender-value-cur"),
            notice.get("result-value-cur-lot"),
            notice.get("estimated-value-cur-proc"),
            notice.get("value-prize-cur-lot"),
        )
        main_classification = _pick_first_non_empty(
            notice.get("main-classification-proc"),
            notice.get("main-classification-lot"),
            notice.get("main-classification-part"),
            notice.get("classification-cpv"),
        )
        main_nature = _pick_first_non_empty(
            notice.get("contract-nature-main-proc"),
            notice.get("contract-nature-main-lot"),
            notice.get("contract-nature"),
        )
        place = _pick_first_non_empty(
            notice.get("place-of-performance"),
            notice.get("place-of-performance-city-proc"),
            notice.get("place-of-performance-country-proc"),
            notice.get("place-of-performance-subdiv-proc"),
            notice.get("place-of-performance-add-proc"),
        )
        notice_year = _year_from_date(notice.get("publication-date"))
        should_translate = self._should_translate_for_year(notice_year)
        buyer_name_raw, buyer_has_native_english = _extract_i18n_with_flag(
            notice.get("buyer-name"), preferred_lang="eng"
        )
        buyer_name = buyer_name_raw
        if buyer_name and not buyer_has_native_english and should_translate:
            buyer_name, _ = self._translate_with_controls(buyer_name_raw)
        country = _pick_first_non_empty(notice.get("buyer-country"))
        winner_name_raw, winner_has_native_english = _extract_i18n_with_flag(
            notice.get("winner-name"), preferred_lang="eng"
        )
        winner_name = winner_name_raw
        if winner_name and not winner_has_native_english and should_translate:
            winner_name, _ = self._translate_with_controls(winner_name_raw)
        value_prize = _join_value(notice.get("value-prize-lot"))
        value_tender = _pick_first_non_empty(
            notice.get("tender-value"),
            notice.get("result-value-lot"),
            notice.get("estimated-value-proc"),
            notice.get("total-value"),
        )

        description_sources = [
            notice.get("description-proc"),
            notice.get("description-lot"),
            notice.get("description-glo"),
            notice.get("title-proc"),
            notice.get("title-lot"),
        ]
        description = ""
        description_en_raw = ""
        description_is_native_english = False
        
        # 1. Extract the native Description and the English Description (if available natively)
        for source in description_sources:
            if not description:
                description = _join_value(source)
            if not description_en_raw:
                description_en_raw, description_is_native_english = _extract_i18n_with_flag(
                    source, preferred_lang="eng"
                )
            if description and description_en_raw:
                break

        # 2. Translate if not native English
        description_en = description_en_raw if description_is_native_english else description
        description_translated = ""
        
        if description_is_native_english:
            description_translated = "native"
        elif description and should_translate:
            self.non_english_count += 1
            description_en, translated_ok = self._translate_with_controls(description)
            if translated_ok:
                description_translated = "machine"
                self.translated_count += 1
            else:
                description_translated = "failed_machine"
                description_en = description  # Fallback to native text if translation fails
        elif not should_translate:
            description_translated = "skipped_historical"

        players = _join_value(
            [
                notice.get("tendering-party-name"),
                notice.get("participant-name-lot"),
                notice.get("winner-name"),
            ]
        )

        native_data = {field: _join_value(notice.get(field)) for field in RAW_FIELDS}

        notice_pub_num = _join_value(notice.get("publication-number"))
        computed_data = {
            "Notice publication number": notice_pub_num,
            "source_url": f"https://ted.europa.eu/en/notice/-/detail/{notice_pub_num}" if notice_pub_num else "",
            "CPV": cpv,
            "Currency": currency,
            "Main classification": main_classification,
            "Main nature of the contract": main_nature,
            "Place of performance": place,
            "Buyer name": buyer_name,
            "Country": country,
            "Winner name": winner_name,
            "Value of the prize": value_prize,
            "Value of the tender": value_tender,
            "Year": notice_year,
            "Publication Date": _join_value(notice.get("publication-date"))[:10],
            "Description": description,
            "Description_en": description_en,
            "Description_translated": description_translated,
            "Winner selection status": _join_value(notice.get("winner-selection-status")),
            "Players": players,
        }
        
        return {**native_data, **computed_data}

    def scrape(
        self,
        *,
        keywords: Optional[List[str]] = None,
        expert_query: Optional[str] = None,
        max_pages: Optional[int] = None,
        max_rows: Optional[int] = None,
        resume_from_checkpoint: bool = True,
    ) -> pd.DataFrame:
        if not expert_query:
            if not keywords:
                raise ValueError("Provide either expert_query or at least one keyword.")
            expert_query = build_expert_query_from_keywords(keywords)

        query = expert_query
        rows: List[Dict[str, str]] = []
        pages_scraped = 0
        iteration_token: Optional[str] = None
        write_header = True

        if resume_from_checkpoint:
            iteration_token = self._load_checkpoint(query)
            if self.config.stream_csv_path:
                csv_exists = self.config.stream_csv_path.exists()
                if iteration_token and not csv_exists:
                    # Prevent silent partial data when token exists but prior output is missing.
                    iteration_token = None
                elif iteration_token and csv_exists:
                    write_header = False

        while True:
            payload: Dict[str, Any] = {
                "query": query,
                "fields": RAW_FIELDS,
                "limit": self.config.limit,
                "scope": self.config.scope,
                "paginationMode": self.config.pagination_mode,
                "onlyLatestVersions": self.config.only_latest_versions,
            }
            if iteration_token:
                payload["iterationNextToken"] = iteration_token

            response = self._request_with_backoff(payload)
            notices = response.get("notices", [])
            page_rows: List[Dict[str, str]] = []

            for notice in notices:
                normalized = self._normalize_notice(notice)
                rows.append(normalized)
                page_rows.append(normalized)

                if max_rows is not None and len(rows) >= max_rows:
                    break

            write_header = self._append_rows_to_csv(page_rows, write_header)

            pages_scraped += 1
            next_token = response.get("iterationNextToken")
            self._save_checkpoint(
                query=query,
                token=next_token,
                pages_scraped=pages_scraped,
                records_scraped=len(rows),
            )

            if self.config.verbose_progress:
                msg = f"Page {pages_scraped}: +{len(page_rows)} rows (total={len(rows)})"
                if self.non_english_count > 0:
                    msg += f" | [Translate] Detected {self.non_english_count} non-English, {self.translated_count} successfully translated"
                print(msg)
                # Reset counters for the next page
                self.non_english_count = 0
                self.translated_count = 0

            if max_rows is not None and len(rows) >= max_rows:
                break

            if max_pages is not None and pages_scraped >= max_pages:
                break

            if not notices or not next_token:
                break

            iteration_token = next_token

            if self.config.pause_seconds > 0:
                time.sleep(self.config.pause_seconds)
            if (
                self.config.pause_every_pages > 0
                and self.config.auto_pause_seconds > 0
                and pages_scraped % self.config.pause_every_pages == 0
            ):
                time.sleep(self.config.auto_pause_seconds)

        df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        return df


def save_run_extract(
    df: pd.DataFrame,
    *,
    source: str,
    project: str,
    query_text: str,
    runs_dir: Path,
    run_timestamp: str,
    run_filename: Optional[str] = None,
    raw_data_url: str = "",
) -> tuple[pd.DataFrame, Path]:
    """
    Save per-run extract to runs/ directory with Excel format.
    
    Transforms OUTPUT_COLUMNS -> RAW_EXTRACT_COLUMNS, sets run_extract path,
    and saves Excel format.
    
    Args:
        df: DataFrame with OUTPUT_COLUMNS schema
        source: Source label (e.g., 'TED Europa API')
        project: Project label (e.g., 'Tender Data Master')
        query_text: Query text used for scraping
        runs_dir: Directory to save run files
        run_timestamp: Run date/time token; normalized to YYYYMMDD for file naming.
    
    Returns:
        Tuple of (transformed DataFrame, Excel path)
    """
    raw_df = prepare_raw_extract_rows(
        df,
        source=source,
        project=project,
        query_text=query_text,
        google_drive_url=raw_data_url,
    )
    
    resolved_runs_dir = runs_dir
    if _is_drive_shortcut_projection(resolved_runs_dir):
        resolved_runs_dir = Path(tempfile.gettempdir()) / "ted_runs"
        resolved_runs_dir.mkdir(parents=True, exist_ok=True)
        print(
            "[INFO] Drive shortcut runs path detected; using local temp directory: "
            f"{_safe_display_path(resolved_runs_dir)}"
        )

    try:
        resolved_runs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if _is_operation_not_supported(exc):
            resolved_runs_dir = Path(tempfile.gettempdir()) / "ted_runs"
            resolved_runs_dir.mkdir(parents=True, exist_ok=True)
            print(
                "[WARN] Runs directory does not support mkdir; "
                f"using temp directory name instead: {_safe_display_path(resolved_runs_dir)}"
            )
        else:
            raise

    default_keyword = _build_keywords_token(None, fallback_query=query_text)
    run_date = _normalize_run_date_token(run_timestamp)
    filename = (
        str(run_filename or "").strip()
        or f"TED_EUROPA_ALL_YEARS_{default_keyword}_{run_date}.xlsx"
    )
    xlsx_path = resolved_runs_dir / filename

    saved_xlsx_path = _safe_write_excel(raw_df, xlsx_path, index=False)
    if saved_xlsx_path != xlsx_path:
        _safe_write_excel(raw_df, saved_xlsx_path, index=False)

    return (raw_df, saved_xlsx_path)


def append_to_consolidated(
    run_df: pd.DataFrame,
    *,
    consolidated_prefix: Path,
) -> None:
    """
    Append run extract to consolidated file with deduplication on record_key.
    
    If consolidated file exists, reads it, concatenates with run_df,
    deduplicates on record_key (keeping last), and saves back.
    If not, saves run_df as the new consolidated file.
    
    Args:
        run_df: DataFrame with RAW_EXTRACT_COLUMNS schema (from save_run_extract)
        consolidated_prefix: Path prefix for consolidated files (without extension)
    """
    if run_df.empty:
        print("[INFO] No new records to append to consolidated file.")
        return
        
    consolidated_xlsx = consolidated_prefix.with_suffix(".xlsx")
    
    if consolidated_xlsx.exists():
        try:
            existing = pd.read_excel(consolidated_xlsx, dtype=str).fillna("")
            combined = pd.concat([existing, run_df], ignore_index=True)
            
            keys = _to_text_series(combined, "record_key").map(_normalize_key_text)
            combined = combined.loc[~keys.duplicated(keep="last")].reset_index(drop=True)
            
            new_count = len(run_df) - (len(existing) + len(run_df) - len(combined))
        except (zipfile.BadZipFile, ValueError) as e:
            print(f"[WARN] Consolidated file {consolidated_xlsx.name} is corrupted. Backing it up and creating a new one.")
            corrupted_path = consolidated_xlsx.with_name(f"{consolidated_xlsx.stem}_corrupted{consolidated_xlsx.suffix}")
            try:
                consolidated_xlsx.rename(corrupted_path)
            except Exception as e:
                print(f"[ERROR] Could not rename corrupted file: {e}")
            combined = run_df
            new_count = len(run_df)
    else:
        combined = run_df
        new_count = len(run_df)
    
    _safe_write_excel(combined, consolidated_xlsx, index=False)
    print(f"[SAVE] Appended {new_count} new records to {consolidated_xlsx.name}")
    
    print(
        f"Consolidated: +{new_count} rows (total={len(combined)}) -> "
        f"{_safe_display_path(consolidated_xlsx)}"
    )


def run_scrape(
    *,
    keywords: Optional[List[str]],
    expert_query: Optional[str],
    output_prefix: Path,
    checkpoint_path: Optional[Path],
    limit: int,
    scope: str,
    max_pages: Optional[int],
    max_rows: Optional[int],
    pause_seconds: float,
    pause_every_pages: int,
    auto_pause_seconds: float,
    only_latest_versions: bool,
    resume_from_checkpoint: bool,
    verbose_progress: bool,
    source: str = "TED Europa API",
    project: str = "Tender Data Master",
    query_text: str = "",
    search_years: Optional[List[str]] = None,
    project_name: str = "TED_EUROPA",
    runs_dir: Optional[Path] = None,
    consolidated_prefix: Optional[Path] = None,
    translation_skip_before_year: Optional[int] = None,
    deduplicate_output: bool = True,
    run_filename: Optional[str] = None,
    raw_data_url: str = "",
) -> pd.DataFrame:
    if limit < 1 or limit > 250:
        raise ValueError("--limit must be between 1 and 250.")
    if len(RAW_FIELDS) * limit > 10000:
        raise ValueError(
            f"Invalid field/page size combination: len(fields) * limit = "
            f"{len(RAW_FIELDS) * limit} > 10000 (TED API limit)."
        )

    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    xlsx_path = output_prefix.with_suffix(".xlsx")

    config = ScrapeConfig(
        limit=limit,
        scope=scope,
        only_latest_versions=only_latest_versions,
        pause_seconds=pause_seconds,
        pause_every_pages=pause_every_pages,
        auto_pause_seconds=auto_pause_seconds,
        checkpoint_path=checkpoint_path,
        stream_csv_path=None,
        verbose_progress=verbose_progress,
        translation_skip_before_year=translation_skip_before_year,
    )
    resolved_expert_query = (expert_query or "").strip()
    if not resolved_expert_query:
        if not keywords:
            raise ValueError("Provide either expert_query or at least one keyword.")
        resolved_expert_query = build_expert_query_from_keywords(keywords)

    year_values = [int(item) for item in _normalize_year_values(search_years)]
    if year_values:
        resolved_expert_query = build_filtered_query(
            resolved_expert_query,
            years=year_values,
        )

    scraper = TEDEuropaScraper(config)
    df_session = scraper.scrape(
        keywords=None,
        expert_query=resolved_expert_query,
        max_pages=max_pages,
        max_rows=max_rows,
        resume_from_checkpoint=resume_from_checkpoint,
    )

    df = deduplicate_output_rows(df_session) if deduplicate_output else df_session.reset_index(drop=True)
    _safe_write_excel(df, xlsx_path, index=False)
    
    # Date-only run token for stable naming across script and notebook usage.
    run_timestamp = datetime.now(SINGAPORE_TZ).strftime("%Y%m%d")
    run_output_stem = build_run_output_stem(
        project_name=project_name,
        years=search_years,
        keywords=keywords,
        expert_query=resolved_expert_query,
        run_timestamp=run_timestamp,
    )
    
    if runs_dir is not None:
        run_raw_df, run_path = save_run_extract(
            df,
            source=source,
            project=project,
            query_text=query_text,
            runs_dir=runs_dir,
            run_timestamp=run_timestamp,
            run_filename=run_filename or f"{run_output_stem}.xlsx",
            raw_data_url=raw_data_url,
        )
        print(f"Run extract saved: {_safe_display_path(run_path)}")
        
        if consolidated_prefix is not None:
            append_to_consolidated(run_raw_df, consolidated_prefix=consolidated_prefix)
    
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape TED Europa tenders into a normalized schema. "
            "Run naming uses <PROJECT_NAME>_<YEAR_RANGE_SHORT>_<KEYWORDS_COMBO>_<YYYYMMDD>."
        )
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help=(
            'Keyword list (converted to expert query as FT~"keyword"). '
            "For run naming, keywords are joined with '-' and capped at 10 characters."
        ),
    )
    parser.add_argument(
        "--expert-query",
        default=None,
        help="Raw TED expert query. If set, --keywords is ignored.",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        default=None,
        help="Filter years in TED query (default: 2024 2025; run name uses short range like 24-25).",
    )
    parser.add_argument(
        "--disable-default-years",
        action="store_true",
        help="Disable default years when no --years are provided.",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("ted_tenders"),
        help="Output path prefix (without extension).",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        default=Path("ted_scrape_checkpoint.json"),
        help="JSON checkpoint path for auto-resume token.",
    )
    parser.add_argument("--limit", type=int, default=100, help="Notices per request (max 250).")
    parser.add_argument(
        "--scope",
        default="LATEST",
        choices=["LATEST", "ACTIVE", "ALL"],
        help="TED scope.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional hard stop for page count.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=2000,
        help="Optional hard stop for total rows.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=1.25,
        help="Small pause between requests.",
    )
    parser.add_argument(
        "--pause-every-pages",
        type=int,
        default=5,
        help="If > 0, add an extra auto-pause every N pages.",
    )
    parser.add_argument(
        "--auto-pause-seconds",
        type=float,
        default=10.0,
        help="Extra pause duration used with --pause-every-pages.",
    )
    parser.add_argument(
        "--only-latest-versions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include only latest notice versions.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable checkpoint resume.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable per-page progress logs.",
    )
    parser.add_argument(
        "--google-sheet-url",
        default=DEFAULT_TENDER_MASTER_SHEET_URL,
        help="Google Sheet URL to upsert results into.",
    )
    parser.add_argument(
        "--google-worksheet",
        default=DEFAULT_MASTER_WORKSHEET,
        help="Google Sheet worksheet/tab name.",
    )
    parser.add_argument(
        "--raw-data-url",
        default="",
        help=(
            "Shareable URL for raw data location (stored in run_extract/Google Drive Url). "
            "Use URL only; mounted drive directories are not shown."
        ),
    )
    parser.add_argument(
        "--google-credentials-file",
        type=Path,
        default=None,
        help="Optional service account JSON file for Google Sheets access.",
    )
    parser.add_argument(
        "--source",
        default="TED Europa API",
        help="Source partition label used for deduplication.",
    )
    parser.add_argument(
        "--project",
        default="Tender Data Master",
        help="Project partition label used for deduplication.",
    )
    parser.add_argument(
        "--dedupe-partitions",
        default="Source,Project",
        help="Comma-separated partition columns for deduplication.",
    )
    parser.add_argument(
        "--disable-google-sync",
        action="store_true",
        help="Disable Google Sheets sync.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="Directory for per-run output files.",
    )
    parser.add_argument(
        "--consolidated-prefix",
        type=Path,
        default=Path("ted_consolidated_raw"),
        help="Prefix for consolidated output files (without extension).",
    )
    parser.add_argument(
        "--disable-run-outputs",
        action="store_true",
        help="Disable both per-run and consolidated outputs.",
    )
    parser.add_argument(
        "--translation-skip-before-year",
        type=int,
        default=None,
        help="Skip machine translation for records published before this year.",
    )
    parser.add_argument(
        "--deduplicate-output",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable output deduplication before saving run outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    runs_dir = script_dir / args.runs_dir
    consolidated_prefix = script_dir / args.consolidated_prefix

    if not args.keywords and not args.expert_query:
        print("=== TED Europa Tender Scraper ===")
        user_input = input("Enter search keywords or an expert query (e.g. FT~\"solar\" AND CY=PT): ").strip()
        if not user_input:
            print("No search criteria provided. Exiting.")
            return
        
        if any(op in user_input.upper() for op in ["=", "~", " AND ", " OR "]):
            args.expert_query = user_input
        else:
            try:
                args.keywords = shlex.split(user_input)
            except ValueError:
                args.keywords = user_input.split()

    if args.expert_query:
        query_text = args.expert_query.strip()
    elif args.keywords:
        query_text = build_expert_query_from_keywords(args.keywords)
    else:
        query_text = ""

    if args.years:
        selected_years = _normalize_year_values(args.years)
    elif args.disable_default_years:
        selected_years = []
    else:
        selected_years = ["2024", "2025"]

    effective_query_text = query_text
    if selected_years:
        effective_query_text = build_filtered_query(
            query_text,
            years=[int(item) for item in selected_years],
        )
    df = run_scrape(
        keywords=args.keywords,
        expert_query=args.expert_query,
        output_prefix=args.output_prefix,
        checkpoint_path=args.checkpoint_path,
        limit=args.limit,
        scope=args.scope,
        max_pages=args.max_pages,
        max_rows=args.max_rows,
        pause_seconds=args.pause_seconds,
        pause_every_pages=args.pause_every_pages,
        auto_pause_seconds=args.auto_pause_seconds,
        only_latest_versions=args.only_latest_versions,
        resume_from_checkpoint=not args.no_resume,
        verbose_progress=not args.quiet,
        source=args.source,
        project=args.project,
        query_text=effective_query_text,
        search_years=selected_years,
        project_name="TED_EUROPA",
        runs_dir=None if args.disable_run_outputs else runs_dir,
        consolidated_prefix=None if args.disable_run_outputs else consolidated_prefix,
        translation_skip_before_year=args.translation_skip_before_year,
        deduplicate_output=args.deduplicate_output,
        raw_data_url=args.raw_data_url,
    )
    print(f"Rows scraped: {len(df)}")
    print(f"Columns: {', '.join(df.columns)}")
    print(f"Saved XLSX: {args.output_prefix.with_suffix('.xlsx').name}")
    if not args.disable_run_outputs:
        print("Run outputs generated for this run.")
        if consolidated_prefix:
            print(f"Consolidated file: {consolidated_prefix.with_suffix('.xlsx').name}")
    if args.raw_data_url.strip():
        print(f"Raw data URL: {args.raw_data_url.strip()}")

    partition_columns = [
        item.strip() for item in args.dedupe_partitions.split(",") if item.strip()
    ]
    if not partition_columns:
        partition_columns = ["Source", "Project"]

    query_text = effective_query_text

    if not args.disable_google_sync and args.google_sheet_url.strip():
        try:
            sync_master_sheet(
                df=df,
                sheet_url=args.google_sheet_url,
                worksheet_name=args.google_worksheet,
                source=args.source,
                project=args.project,
                query_text=query_text,
                google_drive_url=args.raw_data_url,
                google_credentials_file=args.google_credentials_file,
                partition_columns=partition_columns,
                verbose=not args.quiet,
            )
        except Exception as exc:
            message = str(exc) or repr(exc)
            print(f"Google Sheets sync failed ({type(exc).__name__}): {message}")


if __name__ == "__main__":
    main()
