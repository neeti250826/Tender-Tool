"""Load ONCAE OCDS yearly xlsx (HC1 / CE) into per-year pickles of the sheets we need."""
import os
import sys
import time

import pandas as pd

RAW = os.path.join(os.path.dirname(__file__), "hn_raw")
OUT = os.path.join(os.path.dirname(__file__), "hn_pkl")
os.makedirs(OUT, exist_ok=True)

WANT = ["releases", "awa_items", "awa_suppliers", "awards", "contracts", "con_suppliers",
        "ten_items", "sources", "awa_documents", "con_documents", "ten_documents",
        "parties"]


def load(fname):
    out = os.path.join(OUT, fname.replace(".xlsx", ".pkl"))
    if os.path.exists(out):
        return
    t = time.time()
    xl = pd.ExcelFile(os.path.join(RAW, fname), engine="openpyxl")
    sheets = {}
    for s in xl.sheet_names:
        if s in WANT or fname.startswith("CE") or fname.startswith("DDC"):
            sheets[s] = xl.parse(s, dtype=str)
    pd.to_pickle(sheets, out)
    print(fname, {k: len(v) for k, v in sheets.items()}, f"{time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    for f in sorted(os.listdir(RAW)):
        if f.endswith(".xlsx") and (len(sys.argv) == 1 or any(a in f for a in sys.argv[1:])):
            try:
                load(f)
            except Exception as e:  # partial download etc.
                print("FAIL", f, e, flush=True)
