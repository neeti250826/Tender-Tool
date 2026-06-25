# src/step4_merge.py
import argparse
from pathlib import Path
import pandas as pd

DEFAULT_SHEET = "New Tenders"
DEFAULT_URL_COL = "Dirección del anuncio"

def norm_url(s):
    if pd.isna(s):
        return ""
    return str(s).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True, help="Path to Tender List.xlsx")
    ap.add_argument("--sheet", default=DEFAULT_SHEET)
    ap.add_argument("--url-col", default=DEFAULT_URL_COL)
    ap.add_argument("--contracts-csv", required=True, help="output/step3_contracts_<sheet>.csv")
    ap.add_argument("--items-csv", required=True, help="output/step3_dialog_items_<sheet>.csv")
    ap.add_argument("--flat-csv", default="", help="optional: output/step3_<sheet>_flat.csv")
    ap.add_argument("--out", default="output/Tender List__with_step3.xlsx")
    args = ap.parse_args()

    excel_path = Path(args.excel)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Load base sheet
    base = pd.read_excel(excel_path, sheet_name=args.sheet)
    if args.url_col not in base.columns:
        raise SystemExit(f"URL column '{args.url_col}' not found in sheet '{args.sheet}'.")

    base["_url_norm"] = base[args.url_col].map(norm_url)

    # --- Load step3 outputs
    contracts = pd.read_csv(args.contracts_csv, encoding="utf-8-sig")
    items = pd.read_csv(args.items_csv, encoding="utf-8-sig")

    contracts["URL"] = contracts["URL"].map(norm_url)
    items["URL"] = items["URL"].map(norm_url)

    # Optional flat (health)
    flat = None
    if args.flat_csv:
        flat = pd.read_csv(args.flat_csv, encoding="utf-8-sig")
        flat["URL"] = flat["URL"].map(norm_url)

    # --- URL-level aggregates from contracts
    # Sum of Importe total sin impuestos across contracts
    if "Importe total sin impuestos (num)" in contracts.columns:
        contracts["Importe total sin impuestos (num)"] = pd.to_numeric(
            contracts["Importe total sin impuestos (num)"], errors="coerce"
        )

    contracts_agg = contracts.groupby("URL", as_index=False).agg(
        step3_contracts_count=("contract_index", "count"),
        step3_contract_amount_no_tax_sum=("Importe total sin impuestos (num)", "sum"),
    )

    # --- URL-level aggregates from items
    for c in ["Subtotal (num)", "IVA (num)", "Otros impuestos (num)", "Total (num)"]:
        if c in items.columns:
            items[c] = pd.to_numeric(items[c], errors="coerce")

    items_agg = items.groupby("URL", as_index=False).agg(
        step3_dialog_items_count=("URL", "count"),
        step3_items_subtotal_sum=("Subtotal (num)", "sum"),
        step3_items_iva_sum=("IVA (num)", "sum"),
        step3_items_otros_sum=("Otros impuestos (num)", "sum"),
        step3_items_total_sum=("Total (num)", "sum"),
    )

    # --- If flat is present: ok/error + expediente
    flat_agg = None
    if flat is not None:
        # Keep only the most relevant columns
        cols = ["URL", "ok", "error", "Código del expediente", "contracts_count", "dialog_items_count"]
        cols = [c for c in cols if c in flat.columns]
        flat_agg = flat[cols].copy()
        flat_agg = flat_agg.rename(columns={
            "ok": "step3_ok",
            "error": "step3_error",
            "Código del expediente": "step3_expediente",
            "contracts_count": "step3_contracts_count_flat",
            "dialog_items_count": "step3_dialog_items_count_flat",
        })

    # --- Merge into base
    merged = base.merge(contracts_agg, how="left", left_on="_url_norm", right_on="URL")
    merged = merged.drop(columns=["URL"], errors="ignore")

    merged = merged.merge(items_agg, how="left", left_on="_url_norm", right_on="URL")
    merged = merged.drop(columns=["URL"], errors="ignore")

    if flat_agg is not None:
        merged = merged.merge(flat_agg, how="left", left_on="_url_norm", right_on="URL")
        merged = merged.drop(columns=["URL"], errors="ignore")

    # Clean helper
    merged = merged.drop(columns=["_url_norm"], errors="ignore")

    # --- Write output workbook (preserve other sheets too)
    # Read all sheets, replace the target sheet, and add new ones
    xls = pd.ExcelFile(excel_path)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sh in xls.sheet_names:
            if sh == args.sheet:
                merged.to_excel(writer, sheet_name=sh, index=False)
            else:
                pd.read_excel(excel_path, sheet_name=sh).to_excel(writer, sheet_name=sh, index=False)

        # Add detail sheets
        contracts.to_excel(writer, sheet_name="Step3_Contracts", index=False)
        items.to_excel(writer, sheet_name="Step3_Items", index=False)

    print("Wrote:", out_path)
    print("Rows base:", len(base), "merged:", len(merged))
    print("Contracts:", len(contracts), "Items:", len(items))

if __name__ == "__main__":
    main()
