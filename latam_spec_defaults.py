"""Shared scaffold defaults for tender scraper tools.

This repository contains multiple country/website scraper CLIs that share:
- output routing conventions
- run/consolidated exports (csv/xlsx)
- (optional) translation plumbing

The original project this scaffold was copied from includes a richer implementation
covering Google Drive routing and Google Cloud Translation.

For this Scripts workspace we keep the implementation **local-filesystem-first**
and make all optional functionality best-effort.
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


logger = logging.getLogger("latam_spec_defaults")


@dataclass(frozen=True)
class TranslationConfig:
    """Translation configuration.

    The scaffold tools wire translation args for parity with the upstream project.
    This local implementation does not provide Google Cloud Translation; when
    enabled, we log a warning and return inputs unchanged.
    """

    enabled: bool = False
    project_id: str = ""
    target_language: str = "en"
    columns: Sequence[str] = ("title", "description")


def add_standard_colab_args(parser: argparse.ArgumentParser, *, default_country: str = "") -> None:
    """Add shared args used by scaffold scrapers.

    NOTE: `default_country` is preserved for signature compatibility with the
    upstream project, but currently not used.
    """

    _ = default_country

    parser.add_argument(
        "--keywords",
        nargs="*",
        default=[],
        help="Additional keywords (space-separated).",
    )
    parser.add_argument(
        "--years",
        nargs="*",
        default=[],
        type=int,
        help="Years to include in the run stem / filters (e.g. --years 2025 2026).",
    )

    # Translation switches (best-effort; no external dependencies included here).
    parser.add_argument(
        "--enable-google-translation",
        action="store_true",
        help="Enable translation step (best-effort; requires external deps/creds in upstream project).",
    )
    parser.add_argument(
        "--google-project-id",
        default="",
        help="Google Cloud project id (used only if translation is enabled and deps exist).",
    )
    parser.add_argument(
        "--translation-target-language",
        default="en",
        help="Target language code for translation (default: en).",
    )
    parser.add_argument(
        "--translate-columns",
        nargs="*",
        default=["title", "description"],
        help="Columns to translate (best-effort).",
    )
    parser.add_argument(
        "--translate-all",
        action="store_true",
        help="Translate even when a value is already present (best-effort).",
    )


def build_query_text(query: str, keywords: Sequence[str]) -> str:
    parts: List[str] = []
    q = str(query or "").strip()
    if q:
        parts.append(q)
    for kw in list(keywords or []):
        token = str(kw or "").strip()
        if token:
            parts.append(token)
    return " ".join(parts).strip()


def build_run_keywords(*, keywords: Sequence[str], query_text: str) -> List[str]:
    tokens: List[str] = []
    for kw in list(keywords or []):
        t = str(kw or "").strip()
        if t:
            tokens.append(t)
    for t in re.split(r"\s+", str(query_text or "").strip()):
        if t:
            tokens.append(t)
    # stable de-dupe
    seen: Set[str] = set()
    out: List[str] = []
    for t in tokens:
        norm = t.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_token(value: str, *, max_len: int = 60) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _SAFE_TOKEN_RE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if len(text) > max_len:
        text = text[:max_len].rstrip("_")
    return text


def _utc_now_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_run_output_stem(*, project_name: str, years: Sequence[int], keywords: Sequence[str]) -> str:
    project = _safe_token(project_name) or "RUN"
    years_clean = sorted({int(y) for y in list(years or []) if str(y).isdigit() or isinstance(y, int)})
    year_token = "-".join(str(y) for y in years_clean) if years_clean else "all_years"

    kws = [k for k in (str(k or "").strip() for k in list(keywords or [])) if k]
    kw_token = _safe_token("-".join(kws).lower(), max_len=80) or "all_keywords"
    return f"{project}_{year_token}_{kw_token}_{_utc_now_token()}"


def _parse_ymd(value: Optional[str]) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def resolve_date_range(
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    years: Sequence[int],
) -> Tuple[str, str, Set[int]]:
    """Normalize date range inputs.

    Returns: (date_from_iso, date_to_iso, normalized_years)
    """

    years_clean: Set[int] = {int(y) for y in list(years or []) if str(y).isdigit() or isinstance(y, int)}
    df = _parse_ymd(date_from)
    dt = _parse_ymd(date_to)

    if not years_clean and (df or dt):
        # Derive years from explicit dates.
        if df and dt:
            lo, hi = sorted([df, dt])
            years_clean = set(range(lo.year, hi.year + 1))
        else:
            only = (df or dt)
            years_clean = {only.year} if only else set()

    if not years_clean:
        years_clean = {datetime.now(timezone.utc).year}

    min_year, max_year = min(years_clean), max(years_clean)
    if df is None:
        df = date(min_year, 1, 1)
    if dt is None:
        dt = date(max_year, 12, 31)

    if df > dt:
        df, dt = dt, df

    return df.isoformat(), dt.isoformat(), years_clean


def resolve_output_base_dir(*, output_target: str, region: str, website_id: str) -> Path:
    """Resolve local output base directory.

    If output_target is empty or looks like a URL, fall back to `./_local_outputs`.
    """

    target = str(output_target or "").strip()
    if (not target) or target.lower().startswith(("http://", "https://")):
        root = Path.cwd() / "_local_outputs"
    else:
        root = Path(target)
    return root / "Tender" / str(region) / str(website_id)


def ensure_spec_folder_layout(base_dir: Path) -> Dict[str, str]:
    """Create standard folder layout and return a mapping of paths."""

    base = Path(base_dir)
    scraping_tool = base / "scraping_tool"
    runs = scraping_tool / "runs"
    tender_data_tool = base / "tender_data_tool"
    web = base / "web"

    for p in [base, scraping_tool, runs, tender_data_tool, web]:
        p.mkdir(parents=True, exist_ok=True)

    return {
        "base": str(base),
        "scraping_tool": str(scraping_tool),
        "runs": str(runs),
        "tender_data_tool": str(tender_data_tool),
        "web": str(web),
    }


def translate_dataframe_to_english(
    df,
    config: TranslationConfig,
    *,
    only_when_missing: bool = True,
):
    """Best-effort translation.

    This workspace version does not implement actual translation.
    """

    _ = only_when_missing
    if not getattr(config, "enabled", False):
        return df

    logger.warning(
        "Translation enabled but not implemented in this workspace. "
        "Returning input dataframe unchanged. (project_id=%s target_language=%s)",
        getattr(config, "project_id", ""),
        getattr(config, "target_language", "en"),
    )
    return df


def _deduplicate_df(df, *, deduplicate_results: bool) -> Tuple[object, int, int, int]:
    """Return (deduped_df, before, after, removed)."""

    try:
        before = int(len(df))
    except Exception:
        before = 0

    if not deduplicate_results:
        return df, before, before, 0

    # Prefer dedup_key if present.
    try:
        cols = list(getattr(df, "columns", []))
    except Exception:
        cols = []
    if "dedup_key" in cols:
        deduped = df.drop_duplicates(subset=["dedup_key"], keep="first")
    else:
        deduped = df.drop_duplicates(keep="first")
    after = int(len(deduped))
    return deduped, before, after, max(0, before - after)


def save_spec_outputs(
    df,
    *,
    output_target: str,
    region: str,
    website_id: str,
    source_label: str,
    project_name: str,
    years: Iterable[int],
    keywords: Iterable[str],
    deduplicate_results: bool = True,
) -> Dict[str, object]:
    """Save standard spec outputs for a run + consolidated file."""

    import pandas as pd  # local import to keep module import cheap

    base_dir = resolve_output_base_dir(
        output_target=output_target,
        region=region,
        website_id=website_id,
    )
    layout = ensure_spec_folder_layout(base_dir)

    # Defensive copy and normalize a few standard fields.
    if df is None:
        df = pd.DataFrame()
    run_df = df.copy()
    if "source_label" not in list(getattr(run_df, "columns", [])):
        run_df["source_label"] = str(source_label or "")

    run_stem = build_run_output_stem(
        project_name=str(project_name or "RUN"),
        years=list(years or []),
        keywords=list(keywords or []),
    )

    runs_dir = Path(layout["runs"])
    scraping_dir = Path(layout["scraping_tool"])

    # Dedup for run output.
    run_df, dedup_before, dedup_after, dedup_removed = _deduplicate_df(
        run_df, deduplicate_results=deduplicate_results
    )

    run_csv = runs_dir / f"{run_stem}.csv"
    run_xlsx = runs_dir / f"{run_stem}.xlsx"
    run_df.to_csv(run_csv, index=False, encoding="utf-8")
    try:
        run_df.to_excel(run_xlsx, index=False)
    except Exception as exc:
        logger.warning("Failed to write run XLSX (%s): %s", run_xlsx, exc)

    # Consolidated output (stable name per website).
    consolidated_csv = scraping_dir / f"{_safe_token(website_id)}_consolidated.csv"
    consolidated_xlsx = scraping_dir / f"{_safe_token(website_id)}_consolidated.xlsx"

    consolidated_df = run_df
    if consolidated_csv.exists():
        try:
            existing = pd.read_csv(consolidated_csv)
            consolidated_df = pd.concat([existing, run_df], ignore_index=True)
            consolidated_df, _, _, _ = _deduplicate_df(
                consolidated_df, deduplicate_results=deduplicate_results
            )
        except Exception as exc:
            logger.warning("Failed to read/append consolidated CSV (%s): %s", consolidated_csv, exc)
            consolidated_df = run_df

    consolidated_df.to_csv(consolidated_csv, index=False, encoding="utf-8")
    try:
        consolidated_df.to_excel(consolidated_xlsx, index=False)
    except Exception as exc:
        logger.warning("Failed to write consolidated XLSX (%s): %s", consolidated_xlsx, exc)

    return {
        "base_dir": str(base_dir),
        "layout": layout,
        "run_stem": run_stem,
        "run_csv": str(run_csv),
        "run_xlsx": str(run_xlsx),
        "consolidated_csv": str(consolidated_csv),
        "consolidated_xlsx": str(consolidated_xlsx),
        "dedup_before": dedup_before,
        "dedup_after": dedup_after,
        "dedup_removed": dedup_removed,
    }
