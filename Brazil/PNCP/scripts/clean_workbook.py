from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ALWAYS_DROP_IF_ALL_MISSING = [
    "Brand_Name",
    "Manufacturer_Name",
    "Brand_Manufacturer_Name",
]

TENDER_LEVEL_COLUMNS = [
    "Buying_Entity",
    "State",
    "State_Name",
    "City_Municipality",
    "IBGE_Code",
    "Publication_Date",
    "Opening_Date",
    "Closing_Date",
    "Status",
    "Status_Original",
    "Status_English",
    "Tender_Type",
    "Tender_Type_English",
    "Modalidade_Original",
    "Tender_Object",
    "Tender_Object_English",
]

FALLBACK_TEXT_COLUMNS = {
    "Product_Description_English": "Product_Description",
    "Tender_Object_English": "Tender_Object",
    "Status_English": "Status",
    "Tender_Type_English": "Tender_Type",
}

REQUIRED_COLUMNS = [
    "Unique_Tender_Contract_ID",
    "Matched_Keyword",
    "Buying_Entity",
    "State",
    "City_Municipality",
    "Product_Description",
    "Quantity_Ordered",
    "Unit",
    "Unit_Price_BRL",
    "Item_Total_BRL",
    "Publication_Date",
    "Opening_Date",
    "Closing_Date",
    "Status",
    "Tender_Type",
    "Tender_Detail_URL",
]


def is_missing(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def first_non_missing(series: pd.Series):
    for value in series:
        if pd.notna(value) and str(value).strip() != "":
            return value
    return pd.NA


def clean_main_sheet(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    stats: dict[str, int] = {"input_rows": len(df)}

    # Drop columns that are completely empty.
    drop_cols = [c for c in ALWAYS_DROP_IF_ALL_MISSING if c in df.columns and is_missing(df[c]).all()]
    if drop_cols:
        df = df.drop(columns=drop_cols)
    stats["dropped_columns"] = len(drop_cols)

    # Propagate tender-level fields inside the same tender.
    for column in TENDER_LEVEL_COLUMNS:
        if column not in df.columns:
            continue
        df[column] = df[column].astype("object")
        fill_values = df.groupby("Unique_Tender_Contract_ID")[column].transform(first_non_missing)
        mask = is_missing(df[column]) & ~is_missing(fill_values)
        df.loc[mask, column] = fill_values[mask]

    # Backfill English mirror columns from the original text where translation is blank.
    for target, source in FALLBACK_TEXT_COLUMNS.items():
        if target in df.columns and source in df.columns:
            df[target] = df[target].astype("object")
            mask = is_missing(df[target]) & ~is_missing(df[source])
            df.loc[mask, target] = df.loc[mask, source]

    # Remove rows with remaining unrecoverable blanks in required columns.
    present_required = [c for c in REQUIRED_COLUMNS if c in df.columns]
    bad_mask = df[present_required].apply(is_missing).any(axis=1)
    stats["removed_rows"] = int(bad_mask.sum())
    cleaned = df.loc[~bad_mask].copy()
    stats["output_rows"] = len(cleaned)
    return cleaned, stats


def autosize(writer: pd.ExcelWriter) -> None:
    for worksheet in writer.sheets.values():
        for column_cells in worksheet.columns:
            width = max((len(str(cell.value or "")) for cell in column_cells), default=8)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(width + 2, 60)


def build_summary_sheets(df: pd.DataFrame, writer: pd.ExcelWriter) -> None:
    df.to_excel(writer, sheet_name="PNCP_Items", index=False)

    if {"State", "Unique_Tender_Contract_ID", "Item_Number"}.issubset(df.columns):
        (
            df.groupby("State", dropna=False)
            .agg(
                Unique_Tenders=("Unique_Tender_Contract_ID", "nunique"),
                Item_Rows=("Item_Number", "count"),
            )
            .reset_index()
            .sort_values(["Unique_Tenders", "Item_Rows"], ascending=False)
            .to_excel(writer, sheet_name="By_State", index=False)
        )

    if {"Matched_Keyword", "Unique_Tender_Contract_ID", "Item_Number"}.issubset(df.columns):
        (
            df.groupby("Matched_Keyword", dropna=False)
            .agg(
                Unique_Tenders=("Unique_Tender_Contract_ID", "nunique"),
                Item_Rows=("Item_Number", "count"),
            )
            .reset_index()
            .sort_values(["Unique_Tenders", "Item_Rows"], ascending=False)
            .to_excel(writer, sheet_name="By_Keyword", index=False)
        )

    autosize(writer)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: clean_workbook.py <input.xlsx> <output.xlsx>")

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    df = pd.read_excel(input_path, sheet_name="PNCP_Items")
    cleaned, stats = clean_main_sheet(df)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        build_summary_sheets(cleaned, writer)

    print(
        f"CLEANED rows_in={stats['input_rows']} rows_out={stats['output_rows']} "
        f"rows_removed={stats['removed_rows']} dropped_columns={stats['dropped_columns']}"
    )


if __name__ == "__main__":
    main()
