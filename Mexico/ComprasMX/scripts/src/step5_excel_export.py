import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


# Schema mapping (JSONL -> Excel columns)
# Bidder                         := contracts[].contract_row["Licitante"]
# Type of Bidder                 := (blank)
# Institution                    := page_kv["Dependencia o Entidad"]
# Contract number                := contracts[].contract_row["Número de contrato"] (fallback: contract_number_clicked)
# URL                            := url
# Núm.                           := contracts[].contract_row["Núm."]
# Clave CUCoP+                   := dialog_item.row["Clave CUCoP+"]
# Detailed description (ESP)     := dialog_item.row["Descripción detallada"]
# English                        := (blank)
# Irrelevant/Relevant            := (blank)
# Unit of measure - EN           := (blank)
# Volume                         := dialog_item.row["Cantidad solicitada"]
# Unit price without taxes (MXN) := dialog_item.row["Precio unitario sin impuestos"]
# Unit price without taxes (MXN) := (blank, editable)
# IVA                            := dialog_item.row["IVA"]
# Other taxes                    := dialog_item.row["Otros impuestos"]
# Total                          := dialog_item.row["Total"] (fallback: "Monto total de la oferta")
# Grupo                          := (blank)
# Minimum quantity               := dialog_item.row["Cantidad mínima"]
# Maximum quantity               := dialog_item.row["Cantidad máxima"]
# Total amount minimum quantity  := dialog_item.row["Monto total cantidad mínima"]
# Total amount maximum amount    := dialog_item.row["Monto total cantidad máxima"]
# Offer Amount (MXN)             := dialog_item.row["Monto de la Oferta"]
# Total bid amount (MXN)         := dialog_item.row["Monto total de la oferta"]
# Start Date                     := contracts[].contract_row["Fecha inicio"]
# End Date                       := contracts[].contract_row["Fecha fin"]


COLUMNS = [
    "Bidder",
    "Type of Bidder (Distributor/Integrator/Hospital/Manufacturer)",
    "Institution",
    "Contract number",
    "URL",
    "Núm.",
    "Clave CUCoP+",
    "Detailed description (ESP)",
    "English",
    "Irrelevant/Relevant",
    "Unit of measure - EN",
    "Volume",
    "Unit price without taxes (MXN)",
    "Unit price without taxes (MXN) (editable)",
    "IVA",
    "Other taxes",
    "Total",
    "Grupo",
    "Minimum quantity",
    "Maximum quantity",
    "Total amount minimum quantity (MXN)",
    "Total amount maximum amount (MXN)",
    "Offer Amount (MXN)",
    "Total bid amount (MXN)",
    "Start Date",
    "End Date",
]


def _safe_get(d: Dict, key: str) -> Optional[str]:
    if not isinstance(d, dict):
        return None
    return d.get(key)


def _row_key(row: Dict[str, str]) -> str:
    parts = [
        row.get("URL", ""),
        row.get("Contract number", ""),
        row.get("Clave CUCoP+", ""),
        row.get("Detailed description (ESP)", ""),
        row.get("Volume", ""),
        row.get("Unit price without taxes (MXN)", ""),
    ]
    return "||".join(str(p or "").strip() for p in parts)


def iter_jsonl_rows(paths: Iterable[Path]) -> Iterable[Dict]:
    for path in paths:
        if not path.exists():
            raise SystemExit(f"JSONL not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue


def build_rows(payloads: Iterable[Dict]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for p in payloads:
        url = p.get("url", "")
        page_kv = p.get("page_kv") or {}
        institution = _safe_get(page_kv, "Dependencia o Entidad") or ""

        for c in p.get("contracts") or []:
            contract_row = c.get("contract_row") or {}
            bidder = _safe_get(contract_row, "Licitante") or ""
            contract_number = _safe_get(contract_row, "Número de contrato") or c.get(
                "contract_number_clicked", ""
            )
            num = _safe_get(contract_row, "Núm.") or ""
            start_date = _safe_get(contract_row, "Fecha inicio") or ""
            end_date = _safe_get(contract_row, "Fecha fin") or ""

            for item in c.get("dialog_items") or []:
                r = item.get("row") or {}

                row = {
                    "Bidder": bidder,
                    "Type of Bidder (Distributor/Integrator/Hospital/Manufacturer)": "",
                    "Institution": institution,
                    "Contract number": contract_number,
                    "URL": url,
                    "Núm.": num,
                    "Clave CUCoP+": _safe_get(r, "Clave CUCoP+") or "",
                    "Detailed description (ESP)": _safe_get(r, "Descripción detallada") or "",
                    "English": "",
                    "Irrelevant/Relevant": "",
                    "Unit of measure - EN": "",
                    "Volume": _safe_get(r, "Cantidad solicitada") or "",
                    "Unit price without taxes (MXN)": _safe_get(r, "Precio unitario sin impuestos") or "",
                    "Unit price without taxes (MXN) (editable)": "",
                    "IVA": _safe_get(r, "IVA") or "",
                    "Other taxes": _safe_get(r, "Otros impuestos") or "",
                    "Total": _safe_get(r, "Total") or _safe_get(r, "Monto total de la oferta") or "",
                    "Grupo": "",
                    "Minimum quantity": _safe_get(r, "Cantidad mínima") or "",
                    "Maximum quantity": _safe_get(r, "Cantidad máxima") or "",
                    "Total amount minimum quantity (MXN)": _safe_get(r, "Monto total cantidad mínima") or "",
                    "Total amount maximum amount (MXN)": _safe_get(r, "Monto total cantidad máxima") or "",
                    "Offer Amount (MXN)": _safe_get(r, "Monto de la Oferta") or "",
                    "Total bid amount (MXN)": _safe_get(r, "Monto total de la oferta") or "",
                    "Start Date": start_date,
                    "End Date": end_date,
                }

                rows.append(row)

    return rows


def dedupe_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for r in rows:
        k = _row_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--jsonl",
        action="append",
        required=True,
        help="Path to a step3 JSONL file. Use multiple --jsonl for multiple batches.",
    )
    ap.add_argument(
        "--outdir",
        default="excel_exports",
        help="Output directory for the Excel export (default: excel_exports)",
    )
    ap.add_argument(
        "--dedupe",
        action="store_true",
        default=True,
        help="Deduplicate identical rows (default: on).",
    )
    ap.add_argument(
        "--no-dedupe",
        dest="dedupe",
        action="store_false",
        help="Disable deduplication.",
    )
    args = ap.parse_args()

    jsonl_paths = [Path(p) for p in args.jsonl]
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    payloads = iter_jsonl_rows(jsonl_paths)
    rows = build_rows(payloads)

    if args.dedupe:
        rows = dedupe_rows(rows)

    df = pd.DataFrame(rows, columns=COLUMNS)
    date_str = datetime.now().strftime("%d%m%Y")
    out_path = outdir / f"CompraMX Tender Extract_{date_str}.xlsx"
    df.to_excel(out_path, index=False)

    print("Wrote:", out_path)
    print("Rows:", len(df))


if __name__ == "__main__":
    main()
