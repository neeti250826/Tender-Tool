"""Minimal exporter for MDT outputs (csv/xlsx)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict


logger = logging.getLogger("mdt_export")


def save_mdt_outputs(df, prefix_path: Path) -> Dict[str, str]:
    """Write MDT outputs to `<prefix_path>.csv` and `<prefix_path>.xlsx`.

    Always attempts to write CSV; XLSX is best-effort.
    """

    import pandas as pd

    if df is None:
        df = pd.DataFrame()

    prefix = Path(prefix_path)
    prefix.parent.mkdir(parents=True, exist_ok=True)

    csv_path = prefix.with_suffix(".csv")
    xlsx_path = prefix.with_suffix(".xlsx")

    df.to_csv(csv_path, index=False, encoding="utf-8")
    try:
        df.to_excel(xlsx_path, index=False)
    except Exception as exc:
        logger.warning("Failed to write MDT XLSX (%s): %s", xlsx_path, exc)

    return {
        "csv_path": str(csv_path),
        "xlsx_path": str(xlsx_path),
    }
