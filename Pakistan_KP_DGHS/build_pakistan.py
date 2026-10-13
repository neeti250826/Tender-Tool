"""
Pakistan (Khyber Pakhtunkhwa) mapped bid/award table from the KP bid evaluation reports.

Sources: Govt. MCC BERs (pakistan/kp_mcc_bids.csv) and DGHS equipment rate-contract BERs (pakistan/kp_ber_bids.csv).
One row per bid; Winner = the bid with the highest total score on the item. BERs give unit prices but no quantities,
so this is a line-price / winner-share dataset, not a volume dataset.
  * Category from the item text only (vocab layer). Company from the published make / brand text only.
  * Tender Stage: approved BER -> Awarded; FY2025-26 MCC "draft comparative statement" -> Pipeline (not final).
Output: pakistan/PK_KP_BER_Mapped.xlsx
"""
import csv, os, sys
from collections import Counter, defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from vocab_rules import Vocab  # noqa: E402
from build_ref_prices import PKR_PER_USD, FX_NOTE  # noqa: E402


def read(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    v = Vocab()
    out = []
    for r in read(os.path.join(HERE, "kp_mcc_bids.csv")):
        pm = v.product(r["text"]) or {}
        cm = v.company(r["text"] + " " + r["detail"]) or {}
        draft = "DRAFT" in r["source"].upper()
        out.append({"Source": "KP Govt MCC BER", "Document": r["source"], "Page": r["page"], "FY": r["fy"], "Item Ref": r["mcc_ref"],
                    "Item Description": r["text"], "Bidder (supplier/distributor)": r["firm"], "Make / Brand text": r["detail"],
                    "Unit Price PKR": float(r["rate_pkr"]) if r["rate_pkr"] else None, "Winner": r["winner"], "Bids on Item": r["bids_on_item"],
                    "OU": pm.get("ou"), "Sub-OU": pm.get("sub_ou"), "Device Category": pm.get("product_category"), "Company": cm.get("company"),
                    "Tender Stage": "Pipeline" if draft else "Awarded", "Price Evidence": "Line price",
                    "Manufacturer Evidence": "Explicit" if cm else "None"})
    for r in read(os.path.join(HERE, "kp_ber_bids.csv")):
        pm = v.product(r["item"] or r["item_raw"]) or {}
        cm = v.company(r["make"]) or {}
        out.append({"Source": "KP DGHS equipment BER", "Document": r["source"], "Page": r["page"], "FY": r["fy"], "Item Ref": r["block"],
                    "Item Description": r["item_raw"], "Bidder (supplier/distributor)": r["firm"], "Make / Brand text": r["make"],
                    "Unit Price PKR": float(r["quoted_pkr"]) if r["quoted_pkr"] else None, "Winner": r["winner"], "Bids on Item": r["bids_on_item"],
                    "OU": pm.get("ou"), "Sub-OU": pm.get("sub_ou"), "Device Category": pm.get("product_category"), "Company": cm.get("company"),
                    "Tender Stage": "Awarded", "Price Evidence": "Line price", "Manufacturer Evidence": "Explicit" if r["make"] else "None"})
    for o in out:
        o["Unit Price USD"] = round(o["Unit Price PKR"] / PKR_PER_USD, 4) if o["Unit Price PKR"] else None
        o["Included/Review/Excluded"] = "Included" if o["Device Category"] and o["Winner"] else ("Review" if o["Device Category"] else "Excluded")

    win = [o for o in out if o["Device Category"] and o["Winner"]]
    agg = defaultdict(lambda: {"items": 0, "prices": [], "co": Counter(), "fy": Counter()})
    for o in win:
        a = agg[(o["OU"], o["Sub-OU"], o["Device Category"])]
        a["items"] += 1
        a["fy"][o["FY"]] += 1
        if o["Unit Price USD"]:
            a["prices"].append(o["Unit Price USD"])
        a["co"][o["Company"] or "(not an OEM in taxonomy: " + (o["Make / Brand text"] or o["Bidder (supplier/distributor)"])[:25] + ")"] += 1
    cat_rows = []
    for k, a in sorted(agg.items(), key=lambda x: (x[0][0] or "", -x[1]["items"])):
        p = sorted(a["prices"])
        cat_rows.append([*k, a["items"], ", ".join(f"{f}: {n}" for f, n in sorted(a["fy"].items())),
                         p[len(p) // 2] if p else None, p[0] if p else None, p[-1] if p else None,
                         "; ".join(f"{c} ({n})" for c, n in a["co"].most_common(5))])

    cols = list(out[0].keys())
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    hdr = PatternFill("solid", fgColor="1F4E78")

    def sheet(title, header, data, widths):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), hdr, Alignment(wrap_text=True)
        for r in data:
            ws.append(r)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{len(data)+1}"
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    ws = wb.create_sheet("README")
    for line in [
        "Pakistan - Khyber Pakhtunkhwa bid evaluation reports, mapped to Mapping_Taxonomy.xlsx",
        f"Bids: {len(out)}; mapped bids: {sum(1 for o in out if o['Device Category'])}; mapped winning items: {len(win)}.",
        "Sources: KP Govt MCC BERs FY2023-24 (dghskp.gov.pk), 2024-25 and 2026-27 (healthkp.gov.pk, approved) and FY2025-26 draft comparative statement; "
        "DGHS rate-contracting BERs for medical equipment, furniture, instruments FY2024-25..2026-27.",
        "BERs publish unit prices but no quantities: use for winner share and reference prices, not market volume.",
        "Company comes only from the published make/brand text; most MCC suture/consumable winners are local or Chinese brands not in the taxonomy.",
        f"FX: {FX_NOTE}.",
        "Not reachable even via the VPN's 'Pakistan' exit (physically Singapore): Sindh PPRA, Punjab DGHS. KPPRA has only 54 health-entity evaluations, "
        "none with prices for devices (MTI Ayub 2025 evaluation is technical-only).",
    ]:
        ws.append([line])
    ws.column_dimensions["A"].width = 160
    sheet("Bids", cols, [[o[c] for c in cols] for o in out], [18, 40, 6, 9, 10, 60, 30, 30, 12, 7, 6, 26, 30, 36, 18, 10, 10, 12, 12, 12])
    sheet("By_Category", ["OU", "Sub-OU", "Device Category", "Winning items", "By FY", "Median unit USD", "Min USD", "Max USD", "Winning makes (items)"],
          cat_rows, [28, 35, 40, 10, 30, 12, 10, 10, 90])
    wb.save(os.path.join(HERE, "PK_KP_BER_Mapped.xlsx"))
    print(f"bids {len(out)}; mapped {sum(1 for o in out if o['Device Category'])}; winning mapped items {len(win)}; categories {len(cat_rows)}")


if __name__ == "__main__":
    main()
