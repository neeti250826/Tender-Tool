"""Minimal MDT schema adapter.

Upstream projects may map normalized scraper outputs into a strict MDT schema.
For this Scripts workspace, we keep a very light adapter that:
- returns a DataFrame
- ensures values are string-compatible

This keeps scaffold scrapers runnable end-to-end.
"""

from __future__ import annotations

from typing import Optional


def to_mdt_schema(df):
    """Convert a normalized dataframe into an MDT-ready dataframe.

    Current behavior: preserve columns and coerce values to strings.
    """

    import pandas as pd

    if df is None:
        return pd.DataFrame()

    out = df.copy()
    # Coerce object-like columns to strings safely.
    for col in list(getattr(out, "columns", [])):
        try:
            out[col] = out[col].astype(str)
        except Exception:
            # Leave as-is if coercion fails.
            pass
    return out
