"""
Prepare the write-back to the working Google Sheet after the category audit:
  <tab>__cat.tsv     OU | Sub-OU | Device Category        (data rows, sheet order)
  <tab>__incl.tsv    Included/Review/Excluded | Exclusion Reason
  (company / family / new columns come from refine_mapping.py)
  Summary_top.tsv    Summary A1:S8 recomputed without excluded rows
  Summary_ou.tsv     Summary A10:C.. OU table, padded with blanks to clear the old, longer table
Usage: python prepare_writeback.py <sheet_fixed.xlsx>
"""
import json, os, re, sys
from collections import Counter
import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1]
TABS = ["KSA - NUPCO", "Turkey - EKAP", "Pakistan - KP MCC", "Pakistan - KP DGHS", "Pakistan - Federal EPMS", "Kuwait - CAPT", "UAE - Dubai eSupply"]
PFX = ("SA-", "TR-", "PK-", "AE-", "KW-")
NOTE = {  # carried over from the existing Summary block
    "KSA - NUPCO": "Framework term not published: Active = final result in 2025; no pro-rating possible",
    "Turkey - EKAP": "Day-based pro-rating on EKAP contract dates; value only for single-lot contracts",
    "Pakistan - KP MCC": "Financial-year rate contracts (Jul-Jun) ~6 months in 2025; no quantities/totals published",
    "Pakistan - KP DGHS": "Financial-year rate contracts (Jul-Jun) ~6 months in 2025; no quantities/totals published",
    "Pakistan - Federal EPMS": "Contract period not stated; evaluations published 2026",
    "Kuwait - CAPT": "No mapped rows",
    "UAE - Dubai eSupply": "One-off RFQs: full requested quantity in the publication year; no value published",
}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def tsv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        for r in rows:
            f.write("\t".join("" if x is None else (str(int(x)) if isinstance(x, float) and x.is_integer() else str(x)).replace("\t", " ").replace("\n", " ") for x in r) + "\n")


wb = openpyxl.load_workbook(SRC, read_only=True)
top = [["Tab", "Country", "Portal(s)", "Mapped rows", "Included", "2024", "2025", "2026", "Rows with Value USD", "Rows with Est. Value USD",
        "Distinct Device Categories", "Medtronic rows", "Active in 2025: Yes", "Active in 2025: No", "Active in 2025: Unknown",
        "Rows with 2025 share", "2025 Applicable Volume (sum)", "2025 Applicable Value USD (sum)", "CY2025 coverage note"]]
ou_rows = [["Tab", "OU", "Mapped rows"]]
for tab in TABS:
    rows = list(wb[tab].iter_rows(values_only=True))
    h = {c: i for i, c in enumerate(rows[0]) if c}
    data = [r for r in rows[1:] if r and str(r[0] or "")[:3] in PFX]
    name = re.sub(r"[^\w-]+", "_", tab)
    if data:
        tsv(os.path.join(HERE, f"{name}__cat.tsv"), [[r[h["OU"]], r[h["Sub-OU"]], r[h["Device Category"]]] for r in data])
        tsv(os.path.join(HERE, f"{name}__incl.tsv"), [[r[h["Included/Review/Excluded"]], r[h["Exclusion Reason"]]] for r in data])
    cofile = os.path.join(HERE, f"{name}__company.tsv")
    cos = [l.rstrip("\n") for l in open(cofile, encoding="utf-8")][1:] if os.path.exists(cofile) else [""] * len(data)
    keep = [(r, c) for r, c in zip(data, cos) if r[h["Device Category"]]]
    ys = Counter(str(r[h["Award Year"]])[:4] for r, _ in keep)
    act = Counter(r[h["Active in 2025?"]] for r, _ in keep) if "Active in 2025?" in h else Counter()
    top.append([tab, tab.split(" - ")[0], ", ".join(sorted({str(r[h["Portal"]]) for r, _ in keep})), len(keep),
                sum(1 for r, _ in keep if r[h["Included/Review/Excluded"]] == "Included"), ys.get("2024", 0), ys.get("2025", 0), ys.get("2026", 0),
                sum(1 for r, _ in keep if num(r[h["Value USD"]])), sum(1 for r, _ in keep if num(r[h["Est. Value USD (ref-price based)"]])),
                len({r[h["Device Category"]] for r, _ in keep}), sum(1 for _, c in keep if c == "Medtronic"),
                act.get("Yes", 0), act.get("No", 0), act.get("Unknown", 0),
                sum(1 for r, _ in keep if "2025 Applicable Share" in h and r[h["2025 Applicable Share"]] not in (None, "")),
                round(sum(num(r[h["2025 Applicable Volume"]]) for r, _ in keep), 2) if "2025 Applicable Volume" in h else 0,
                round(sum(num(r[h["2025 Applicable Value USD"]]) for r, _ in keep), 2) if "2025 Applicable Value USD" in h else 0,
                NOTE[tab] + (f"; excludes {len(data) - len(keep)} out-of-scope rows (category audit 2026-10-08)" if len(data) > len(keep) else "")])
    for k, n in Counter(r[h["OU"]] for r, _ in keep).most_common():
        ou_rows.append([tab, k, n])
while len(ou_rows) < 45:                      # old table ran to row 49 (A10:C49 = 40 rows); pad to clear leftovers
    ou_rows.append(["", "", ""])
tsv(os.path.join(HERE, "Summary_top.tsv"), top)
tsv(os.path.join(HERE, "Summary_ou.tsv"), ou_rows)
for r in top:
    print(r[:5], r[12:18])
print("OU table rows:", sum(1 for r in ou_rows if r[0]) - 1)
