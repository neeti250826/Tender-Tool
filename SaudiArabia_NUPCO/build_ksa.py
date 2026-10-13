"""
KSA / NUPCO phase-1 build.

  awards  = parse_nupco_finals.py output (+ NPT0033/25 line parser, which replaces that tender's rows)
  qty     = item-list requested (initial) quantity, joined on tender + NUPCO code
  mapping = each unique NUPCO code mapped ONCE from its line description (vocab layer), then joined back;
            Company from the manufacturer column only; Family from company + category + model/description.
  share   = NUPCO frameworks are multi-award, so each award row gets weight 1/n (n = winners of that item);
            company share of a category = sum of weights. Volume/value are NOT split by real allocation.
  value   = requested qty x reference unit price (USD) per product category from ref_prices.csv when present
            (built from EKAP single-item lots / Pakistan BERs). Allocated to winners by the same 1/n weight.

Output: turmeca/ksa/KSA_NUPCO_Awards_Mapped.xlsx
"""
import csv, json, os, sys
from collections import Counter, defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from vocab_rules import Vocab  # noqa: E402

OUT = os.path.join(HERE, "KSA_NUPCO_Awards_Mapped.xlsx")
REF = os.path.join(os.path.dirname(HERE), "ref_prices.csv")
TITLES = {  # final-result tenders (English titles from NUPCO_Tender_Families)
    "NPT0002/25": "Mortuary & morgue refrigerators", "NPT0004/23": "Medical devices framework - addendum",
    "NPT0008/25": "Chemicals & pharmaceutical preparations", "NPT0009/25": "Laser devices & accessories",
    "NPT0010/23": "Medical imaging devices", "NPT0013/23": "Specialty laboratory devices", "NPT0014/23": "Medical rehabilitation devices",
    "NPT0015/25": "Vitamins & minerals", "NPT0016/25": "Radioisotopes & contrast media", "NPT0017/25": "Hormones & GI drugs",
    "NPT0018/25": "Blood products & derivatives", "NPT0019/23": "Medical devices framework - addendum 2", "NPT0019/25": "Dental department",
    "NPT0020/23": "General laboratory devices", "NPT0020/25": "Neuroscience supplies", "NPT0021/24": "ICU & monitoring department",
    "NPT0022/24": "General departments, calibration & simulation", "NPT0022/25": "Respiratory & sensory health (drugs)",
    "NPT0023/25": "Refrigerators & freezers", "NPT0024/25": "ENT department", "NPT0026/24": "Operating rooms & surgical drills",
    "NPT0027/24": "Medical furniture", "NPT0027/25": "Internal medicine & chronic disease (drugs)", "NPT0028/25": "Sera & vaccines",
    "NPT0029/25": "Sterilisation & infection control", "NPT0030/25": "Ophthalmology department", "NPT0033/24": "Ambulance outfitting",
    "NPT0033/25": "ENT supplies", "NPT0034/24": "Home care department", "NPT0037/24": "Drugs addendum",
    "NPT0037/25": "General surgical supplies (urology & surgery)", "NPT0038/25": "Interventional radiology & cardiac cath supplies",
    "NPT0043/25": "Dental supplies (lab, implant, maxillofacial)", "NPT0044/25": "General supplies (sutures, GI endoscopy, robotics)",
    "NPT0046/24": "Infusion pumps & consumables", "NPT0047/24": "Diabetes department & consumables", "NPT0048/24": "Manufacturer pre-qualification (VBA)",
    "NPT0049/25": "Ophthalmology supplies", "NPT0050/25": "Wasfaty drugs addendum", "NPT0052/24": "Medical devices addendum 1",
    "NPT0056/24": "Medical devices addendum 2", "NPT0064/25": "Doping-detection laboratory",
}
# NUPCO item-list UOM -> pieces (reference prices are per piece). Unknown pack sizes -> no value.
UOM_FACTOR = {"EACH": 1, "EA": 1, "PIECE": 1, "PC": 1, "PCS": 1, "ITEMS (PIECES)": 1, "ITEMS": 1, "UNIT": 1, "SET": 1,
              "KIT": 1, "TUBE": 1, "BOTTLE": 1, "ROLL": 1, "DOZEN": 12, "DZ": 12, "PAIR": 2}
MDT_HEAVY = {"NPT0026/24", "NPT0033/25", "NPT0038/25", "NPT0052/24", "NPT0021/24", "NPT0044/25", "NPT0020/25"}


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    v = Vocab()
    awards = [r for r in read_csv(os.path.join(HERE, "nupco_awards_raw.csv")) if r["tender_id"] != "NPT0033/25"]
    awards += read_csv(os.path.join(HERE, "nupco_awards_0033_25.csv"))
    qty = {(r["tender_id"], r["nupco_code"]): r for r in read_csv(os.path.join(HERE, "nupco_itemlist_qty.csv"))}
    dates = json.load(open(os.path.join(HERE, "final_result_dates.json")))
    ref = {}
    if os.path.exists(REF):
        for r in read_csv(REF):
            ref[r["product_category"]] = r

    # de-duplicate exact repeats (page-break duplicates)
    seen, rows = set(), []
    for r in awards:
        k = (r["tender_id"], r["nupco_code"], r.get("vendor_no") or r.get("vendor_name"), r.get("model"), r.get("manufacturer"))
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)

    # ---- map each unique NUPCO code once (description from awards, else item list)
    desc = {}
    for r in rows:
        d = r.get("description") or ""
        q = qty.get((r["tender_id"], r["nupco_code"]))
        if not d and q:
            d = q["il_description"]
        if len(d) > len(desc.get(r["nupco_code"], "")):
            desc[r["nupco_code"]] = d
    code_map = {c: v.product(d) for c, d in desc.items()}

    winners = Counter((r["tender_id"], r["nupco_code"]) for r in rows)
    out = []
    for r in rows:
        t, c = r["tender_id"], r["nupco_code"]
        pm = code_map.get(c) or {}
        cm = v.company(r.get("manufacturer")) or {}
        fam = v.family(cm.get("company"), pm.get("product_category"), r.get("model"), desc.get(c)) if cm and pm else None
        q = qty.get((t, c)) or {}
        n = winners[(t, c)]
        w = 1 / n
        rp = ref.get(pm.get("product_category") or "")
        q_req = float(q["qty_requested"]) if q.get("qty_requested") not in (None, "") else None
        uom = (q.get("uom") or r.get("uom") or "").strip().upper()
        factor = UOM_FACTOR.get(uom)
        pieces = q_req * factor if (q_req and factor) else None
        val = pieces * float(rp["unit_price_usd"]) * w if (pieces and rp) else None
        basis = ("qty x ref price" if val else
                 "no reference price - volume/share only" if pm and not rp else
                 f"UOM '{uom}' not convertible to pieces - volume/share only" if pm and rp and not factor else
                 "no requested qty" if pm else "")
        d = dates.get(t, {})
        year = int(d["date"][:4]) if d.get("date") else None
        out.append({
            "Country": "KSA", "Portal": "NUPCO", "Source Type": "Final result", "Tender ID": t, "Tender Title": TITLES.get(t, ""),
            "Medtronic-heavy tender": "Yes" if t in MDT_HEAVY else "", "Result Date": d.get("date"), "Award Year": year,
            "In 2024-26 window": "Yes" if year and 2024 <= year <= 2026 else "No",
            "NUPCO Code": c, "Item No": r.get("item_no"), "Description": desc.get(c), "UOM": q.get("uom") or r.get("uom"),
            "Group": r.get("group"), "Supplier/Distributor": r.get("vendor_name"), "Vendor No": r.get("vendor_no"),
            "Manufacturer (as published)": r.get("manufacturer"), "Country of Origin": r.get("country"), "Model / Catalog": r.get("model"),
            "OU": pm.get("ou"), "Sub-OU": pm.get("sub_ou"), "Device Category": pm.get("product_category"),
            "Company": cm.get("company"), "Company Method": cm.get("method"), "Family Name": fam,
            "Requested Qty (item list)": q_req, "Winners on item": n, "Award Weight (1/n)": round(w, 4),
            "Pieces (qty x UOM factor)": pieces,
            "Ref Unit Price USD": float(rp["unit_price_usd"]) if rp else None, "Ref Price n": int(rp["n_obs"]) if rp else None,
            "Ref Price Source": rp.get("source") if rp else None,
            "Est. Value USD (pieces x ref x 1/n)": round(val, 2) if val else None, "Value Basis": basis,
            "Tender Stage": "Awarded", "Price Evidence": "None", "Manufacturer Evidence": "Explicit" if r.get("manufacturer") else "None",
            "Included/Review/Excluded": ("Included" if pm and year and 2024 <= year <= 2026 else ("Review" if pm else "Excluded")),
            "Caveat": "Framework multi-award: requested qty not split by real allocation" + ("; " + r["remarks"] if r.get("remarks") else ""),
            "Page": r.get("page"),
        })

    # ---- shares (award count weight always; value only where a reference price exists)
    share = defaultdict(lambda: defaultdict(float))
    vshare = defaultdict(lambda: defaultdict(float))
    items = defaultdict(set)
    for o in out:
        if o["Included/Review/Excluded"] != "Included":
            continue
        k = (o["OU"], o["Sub-OU"], o["Device Category"])
        co = o["Company"] or "(unmapped: " + (o["Manufacturer (as published)"] or "?")[:30] + ")"
        share[k][co] += o["Award Weight (1/n)"]
        vshare[k][co] += o["Est. Value USD (pieces x ref x 1/n)"] or 0
        items[k].add((o["Tender ID"], o["NUPCO Code"]))
    share_rows = []
    for k, cos in share.items():
        tot = sum(cos.values())
        vtot = sum(vshare[k].values())
        mdt = cos.get("Medtronic", 0)
        for co, wv in sorted(cos.items(), key=lambda x: -x[1]):
            vv = vshare[k][co]
            share_rows.append([*k, co, round(wv, 2), round(wv / tot, 4), len(items[k]), round(mdt / tot, 4),
                               round(vv, 2) if vtot else None, round(vv / vtot, 4) if vtot else None,
                               "qty x ref price" if vtot else "volume/share only (no reference price)"])
    share_rows.sort(key=lambda r: (r[0] or "", r[1] or "", r[2] or "", -r[4]))

    # ---- code map sheet
    cm_rows = []
    for c, d in sorted(desc.items()):
        pm = code_map[c] or {}
        tenders = sorted({o["Tender ID"] for o in out if o["NUPCO Code"] == c})
        cm_rows.append([c, d, pm.get("ou"), pm.get("sub_ou"), pm.get("product_category"), ", ".join(tenders)])

    # ---- write
    wb = openpyxl.Workbook()
    hdr = PatternFill("solid", fgColor="1F4E78")

    def sheet(title, header, data, widths=None):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), hdr, Alignment(wrap_text=True)
        for r in data:
            ws.append(r)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{len(data)+1}"
        for i, w in enumerate(widths or [], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        return ws

    wb.remove(wb.active)
    n_map = sum(1 for o in out if o["Device Category"])
    n_inc = sum(1 for o in out if o["Included/Review/Excluded"] == "Included")
    readme = [
        ["KSA NUPCO final-result awards, mapped to Mapping_Taxonomy.xlsx"],
        [f"Award rows: {len(out)} from {len({o['Tender ID'] for o in out})} tenders; unique NUPCO codes: {len(desc)}; "
         f"codes mapped: {sum(1 for x in code_map.values() if x)}; award rows mapped: {n_map}; included (mapped + 2024-26): {n_inc}."],
        ["Category/Sub-OU/OU from the line description only (vocab_rules.py); Company from the published manufacturer only, never the supplier."],
        ["Frameworks are multi-award: each winner of an item gets weight 1/n. Share = sum of weights. NUPCO publishes no prices."],
        ["Value = requested qty x UOM factor (DOZEN=12) x reference unit price (USD, median winning KP Pakistan BER rate for the Device Category) x 1/n. "
         "Where no reference price exists the row has no value (Value Basis says why): volume and share only, nothing guessed."],
        ["Reference prices are Pakistani public-tender prices (KP Govt MCC + DGHS BERs, FY2024-25..2026-27) used as a proxy for KSA; "
         "KSA prices are typically higher, so treat values as a floor. FX: PKR/USD 276.98 (2026-10-01)."],
        ["Award Year = year the final result was published (printed date on the PDF, else PDF creation date). NPT0004/23 (2023) is outside 2024-26."],
    ]
    ws = wb.create_sheet("README")
    for r in readme:
        ws.append(r)
    ws.column_dimensions["A"].width = 150
    cols = list(out[0].keys())
    sheet("Awards", cols, [[o[c] for c in cols] for o in out], [12, 8, 12, 12, 30, 8, 11, 8, 8, 15, 12, 60, 8, 10, 30, 9, 30, 12, 20, 25, 30, 35, 20, 9, 25, 10, 8, 8, 10, 14, 12, 10, 10, 10, 10, 40, 6])
    sheet("Share_by_Category", ["OU", "Sub-OU", "Device Category", "Company", "Award weight", "Share of awards", "Items awarded",
                                "Medtronic share (awards)", "Est. Value USD", "Share of value", "Value basis"],
          share_rows, [28, 35, 40, 30, 12, 12, 10, 12, 14, 12, 34])
    if ref:
        sheet("Ref_Prices_Used", list(next(iter(ref.values())).keys()), [list(r.values()) for r in ref.values()], [40, 30, 28, 12, 10, 10, 6, 20, 35, 22, 45])
    sheet("Code_Map", ["NUPCO Code", "Description", "OU", "Sub-OU", "Device Category", "Tenders"], cm_rows, [15, 90, 28, 35, 40, 30])
    unm = Counter((o["Description"] or "")[:120] for o in out if not o["Device Category"] and o["Tender ID"] in MDT_HEAVY)
    sheet("Unmapped_MDT_Tenders", ["Description (unmapped, Medtronic-heavy tenders)", "Award rows"], unm.most_common(), [120, 10])
    log = read_csv(os.path.join(HERE, "nupco_parse_log.csv"))
    sheet("Parse_Log", list(log[0].keys()), [list(r.values()) for r in log], [12, 7, 7, 10, 9, 100])
    wb.save(OUT)
    print(readme[1][0])
    mdt = sum(o["Award Weight (1/n)"] for o in out if o["Company"] == "Medtronic" and o["Included/Review/Excluded"] == "Included")
    print("Medtronic weighted awards (included):", round(mdt, 1))


if __name__ == "__main__":
    main()
