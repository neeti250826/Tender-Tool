from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import pandas as pd
import os


@dataclass
class TranslationConfig:
    enabled: bool = False
    project_id: str = ""
    target_language: str = "en"
    columns: list | None = None


def add_standard_colab_args(parser, default_country="SG"):
    parser.add_argument("--years", nargs="*", type=int, default=[])
    parser.add_argument("--keywords", nargs="*", default=[])
    parser.add_argument("--enable-google-translation", action="store_true")
    parser.add_argument("--google-project-id", default="")
    parser.add_argument("--translation-target-language", default="en")
    parser.add_argument("--translate-columns", nargs="*", default=["title", "description"])
    parser.add_argument("--translate-all", action="store_true")
    return parser


def build_query_text(query, keywords):
    if query:
        return query
    if keywords:
        return " ".join(keywords)
    return ""


def build_run_keywords(keywords, query_text):
    if keywords:
        return keywords
    if query_text:
        return query_text.split()
    return []


def build_run_output_stem(project_name, years, keywords):
    year_token = "_".join(map(str, years)) if years else "all"
    kw_token = "_".join(keywords) if keywords else "all"
    return f"{project_name}_{year_token}_{kw_token}"


def resolve_date_range(date_from=None, date_to=None, years=None):
    return date_from, date_to, years or []


def resolve_output_base_dir(output_target, region, website_id):
    base = Path(output_target or "./output")
    base.mkdir(parents=True, exist_ok=True)
    return base


def ensure_spec_folder_layout(base_dir):
    base_dir = Path(base_dir)
    layout = {
        "run": base_dir / "run",
        "web": base_dir / "web",
        "tender_data_tool": base_dir / "mdt"
    }

    for p in layout.values():
        p.mkdir(parents=True, exist_ok=True)

    return layout


def translate_dataframe_to_english(df, config, only_when_missing=True):
    return df


def save_spec_outputs(df, output_target, region, website_id, source_label,
                      project_name, years, keywords, deduplicate_results=True):

    base = Path(output_target or "./output")
    base.mkdir(exist_ok=True)

    run_csv = base / "run_output.csv"
    df.to_csv(run_csv, index=False)

    return {
        "run_csv": str(run_csv),
        "consolidated_csv": str(run_csv),
        "dedup_before": len(df),
        "dedup_after": len(df),
        "dedup_removed": 0
    }