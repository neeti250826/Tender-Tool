# -*- coding: utf-8 -*-
"""Parse the MDT Eurasia reference sheet (Drive text rep) long-format market table
into a clean CSV: region, country, ou, sub_ou, product_type, product_category,
procedure, company, family, metric, value."""
import json, re, sys
from collections import Counter
import pandas as pd

F = r"<MDT_REFERENCE_SHEET_TEXT_DUMP>.txt"
OUT = r"<WORKSPACE>/mdt_market_data.csv"


def clean(c):
    return c.strip().replace("\\_", "_").replace("\\&", "&").replace("\\", "").strip()


def main():
    d = json.load(open(F, encoding="utf-8"))
    lines = d["fileContent"].split("\n")
    hdr_i = None
    for i, l in enumerate(lines):
        low = l.lower()
        if "sub_ou" in low.replace("\\", "") and "product_category" in low.replace("\\", "") \
           and "metric" in low and "value" in low:
            hdr_i = i
            break
    if hdr_i is None:
        print("header not found")
        return
    hdr = [clean(c) for c in lines[hdr_i].strip().strip("|").split("|")]
    ncol = len(hdr)
    print("header idx", hdr_i, "columns:", hdr)

    rows = []
    for l in lines[hdr_i + 1:]:
        s = l.strip()
        if not s.startswith("|"):
            continue
        cells = [clean(c) for c in s.strip("|").split("|")]
        if len(cells) >= 12:
            # pad/trim to header length
            cells = (cells + [""] * ncol)[:ncol]
            rows.append(cells)
    print("parsed data rows:", len(rows))
    df = pd.DataFrame(rows, columns=hdr)
    # keep the key analytic columns if present
    keep = [c for c in ["project", "region", "country", "ou", "sub_ou", "product_type",
                        "product_category", "procedure", "company", "family", "metric", "value"] if c in df.columns]
    df = df[keep]
    df.to_csv(OUT, index=False, encoding="utf-8")
    print("saved", OUT)
    print("\nmetric values:", Counter(df["metric"]).most_common(25))
    print("\nregions:", Counter(df["region"]).most_common(20))
    print("\ncountry sample:", Counter(df["country"]).most_common(20))
    # value format sample for numeric metrics
    nonempty = df[df["value"].str.strip() != ""]
    print("\nrows with non-empty value:", len(nonempty))
    print("value samples:", nonempty["value"].head(10).tolist())


if __name__ == "__main__":
    main()
