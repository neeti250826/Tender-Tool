"""
TURMECA master file of MAPPED data: one tab per country x website, all in the common master-table schema
(same columns as Master_Table in TURMECA_Tender_Master.xlsx), plus README and Summary tabs.

Sources (each rebuilt by its own script first):
  KSA      NUPCO final results         ksa/KSA_NUPCO_Awards_Mapped.xlsx            (Awards)
  Turkey   EKAP v2 contracts           ekap/tr_ekap_lots_all.csv
  Pakistan KP Govt MCC BERs + KP DGHS  pakistan/PK_KP_BER_Mapped.xlsx              (Bids) -> two tabs by source
  Pakistan Federal PPRA EPMS           pakistan/federal/PK_Federal_Evaluations_Mapped.xlsx (Item_Bids)
  Kuwait   CAPT winning bids           kuwait/KW_CAPT_Awards.xlsx                  (All_Awards)
  UAE      Dubai eSupply               uae/UAE_Dubai_eSupply_Volume.xlsx           (Mapped_Items)
Only rows with a taxonomy Device Category are written. FX: fx_annual_usd.json (TRY = ECB annual average by award year).
Output: turmeca/TURMECA_Master_Mapped_Data.xlsx
"""
import csv, json, os, re
from collections import Counter, defaultdict
from datetime import datetime, date

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "TURMECA_Master_Mapped_Data.xlsx")
FX = json.load(open(os.path.join(HERE, "fx_annual_usd.json")))
FIX = FX["fixed"]

COLS = ["Row ID", "Country", "Portal", "Source Type", "Source URL", "Tender ID", "Tender Title", "Tender Type", "Procurement Authority",
        "Hospital/Buyer", "Publication Date", "Opening Date", "Award/Contract Date", "Result Date", "Award Year",
        "Original-language Description", "English Description", "Lot/Item No.", "CPV/OKAS/NUPCO Code", "OU", "Sub-OU", "Device Category",
        "Company", "Family Name", "Disclosed Brand", "Supplier/Distributor", "Manufacturer", "Volume", "UOM", "Currency",
        "Unit Award Price", "Total Award Value", "FX Date", "LCY per USD", "Value USD", "HBP USD", "Tender Stage", "Price Evidence",
        "Manufacturer Evidence", "Winner Disclosed?", "Manufacturer Explicit?", "Model Explicit?", "Award vs Budget?", "Confidence",
        "Included/Review/Excluded", "Exclusion Reason", "Duplicate/Retender Flag", "Caveat",
        # source-specific extras kept so nothing is lost
        "Winner (this row)", "Award Weight (1/n)", "Est. Value USD (ref-price based)", "Ref Unit Price USD", "Value Basis", "Data Source"]

PREV_KSA = r"<DOWNLOADS>/KSA_tender_awards_final.xlsx"
PREV_TR = r"<DOWNLOADS>/Turkey_EKAP_Contracts_Ending_2024_2026_EN_Corrected.xlsx"
THIS = "This project (NUPCO PDFs / EKAP API, 2026-10)"
UOM_FACTOR = {"EACH": 1, "EA": 1, "PIECE": 1, "PC": 1, "PCS": 1, "ITEMS (PIECES)": 1, "ITEMS": 1, "UNIT": 1, "SET": 1, "KIT": 1,
              "TUBE": 1, "BOTTLE": 1, "ROLL": 1, "DOZEN": 12, "DZ": 12, "PAIR": 2}

_V = None


def vocab():
    global _V
    if _V is None:
        import sys
        sys.path.insert(0, HERE)
        from vocab_rules import Vocab
        _V = Vocab()
    return _V


def ref_prices():
    with open(os.path.join(HERE, "ref_prices.csv"), encoding="utf-8-sig") as f:
        return {r["product_category"]: r for r in csv.DictReader(f)}


def xl_rows(path, sheet):
    ws = openpyxl.load_workbook(path, read_only=True)[sheet]
    it = ws.iter_rows(values_only=True)
    h = next(it)
    return [dict(zip(h, r)) for r in it if r and any(x is not None for x in r)]


def try_fx(year):
    y = str(year) if year else None
    return FX.get(y, {}).get("TRY") if y else None


def yr(v):
    if isinstance(v, (datetime, date)):
        return v.year
    m = re.search(r"(20\d\d)", str(v or ""))
    return int(m.group(1)) if m else None


def base(country, portal, **kw):
    r = {c: None for c in COLS}
    r.update(Country=country, Portal=portal)
    r.update(kw)
    return r


def ksa():
    out = []
    for i, a in enumerate(xl_rows(os.path.join(HERE, "ksa", "KSA_NUPCO_Awards_Mapped.xlsx"), "Awards")):
        if not a.get("Device Category"):
            continue
        man = a.get("Manufacturer (as published)")
        out.append(base("KSA", "NUPCO", **{
            "Row ID": f"SA-NUPCO-{a['Tender ID']}-{a['NUPCO Code']}-{i}", "Source Type": "Final result", "Tender ID": a["Tender ID"],
            "Tender Title": a["Tender Title"], "Tender Type": "Open framework agreement", "Procurement Authority": "NUPCO",
            "Result Date": a["Result Date"], "Award Year": a["Award Year"], "English Description": a["Description"],
            "Lot/Item No.": a.get("Item No"), "CPV/OKAS/NUPCO Code": a["NUPCO Code"], "OU": a["OU"], "Sub-OU": a["Sub-OU"],
            "Device Category": a["Device Category"], "Company": a["Company"], "Family Name": a["Family Name"],
            "Disclosed Brand": a.get("Model / Catalog"), "Supplier/Distributor": a["Supplier/Distributor"], "Manufacturer": man,
            "Volume": a.get("Requested Qty (item list)"), "UOM": a.get("UOM"), "Currency": "SAR", "LCY per USD": FIX["SAR"],
            "Tender Stage": a["Tender Stage"], "Price Evidence": a["Price Evidence"], "Manufacturer Evidence": a["Manufacturer Evidence"],
            "Winner Disclosed?": "Yes", "Manufacturer Explicit?": "Yes" if man else "No", "Model Explicit?": "Yes" if a.get("Model / Catalog") else "No",
            "Award vs Budget?": "No", "Confidence": "High" if a.get("Company") else "Medium",
            "Included/Review/Excluded": a["Included/Review/Excluded"], "Caveat": a.get("Caveat"),
            "Winner (this row)": "Yes", "Award Weight (1/n)": a.get("Award Weight (1/n)"),
            "Est. Value USD (ref-price based)": a.get("Est. Value USD (pieces x ref x 1/n)"), "Ref Unit Price USD": a.get("Ref Unit Price USD"),
            "Value Basis": a.get("Value Basis")}))
    return out


def ksa_previous(have_tenders):
    """Previous NUPCO extraction (KSA_tender_awards_final.xlsx): add only tenders not parsed in this project.
    Its 'amount' is one figure repeated on every row of a tender (not a price) - kept only in Caveat."""
    if not os.path.exists(PREV_KSA):
        return [], {}
    v, ref = vocab(), ref_prices()
    rows = [r for r in xl_rows(PREV_KSA, "nupco_awards_final") if r.get("notice_id") not in have_tenders]
    winners = Counter((r["notice_id"], r["item_no"]) for r in rows)
    out, stats = [], Counter()
    for i, a in enumerate(rows):
        stats["rows"] += 1
        pm = v.product(a.get("item_description_en") or a.get("item_description")) or {}
        if not pm:
            continue
        cm = v.company(a.get("supplier_name_en") or a.get("supplier_name")) or {}
        n = winners[(a["notice_id"], a["item_no"])]
        qty = a.get("item_quantity")
        factor = UOM_FACTOR.get(str(a.get("item_uom") or "").strip().upper())
        rp = ref.get(pm["product_category"])
        est = qty * factor * float(rp["unit_price_usd"]) / n if (qty and factor and rp) else None
        y = yr(a.get("publication_date"))
        stats["mapped"] += 1
        out.append(base("KSA", "NUPCO", **{
            "Row ID": f"SA-NUPCO-PREV-{a['notice_id']}-{a['item_no']}-{i}", "Source Type": a.get("status_en") or "Final result",
            "Source URL": a.get("notice_url"), "Tender ID": a["notice_id"], "Tender Title": a.get("title_en"), "Tender Type": "Open framework agreement",
            "Procurement Authority": "NUPCO", "Result Date": a.get("publication_date"), "Award Year": y,
            "Original-language Description": a.get("item_description"), "English Description": a.get("item_description_en"),
            "Lot/Item No.": a.get("item_no"), "OU": pm["ou"], "Sub-OU": pm["sub_ou"], "Device Category": pm["product_category"],
            "Company": cm.get("company"), "Supplier/Distributor": a.get("supplier_name_en") or a.get("supplier_name"),
            "Volume": qty, "UOM": a.get("item_uom"), "Currency": "SAR", "LCY per USD": FIX["SAR"],
            "Tender Stage": "Awarded" if "final" in str(a.get("status_en")).lower() else "Pipeline", "Price Evidence": "None",
            "Manufacturer Evidence": "Inferred from distributor" if cm else "None", "Winner Disclosed?": "Yes",
            "Manufacturer Explicit?": "No", "Model Explicit?": "No", "Award vs Budget?": "No", "Confidence": "Medium",
            "Included/Review/Excluded": "Included" if (y in (2024, 2025, 2026) and "final" in str(a.get("status_en")).lower()) else "Review",
            "Caveat": f"Previous extraction; manufacturer not captured; source 'amount' {a.get('amount')} SAR is tender-level, not a price",
            "Winner (this row)": "Yes", "Award Weight (1/n)": round(1 / n, 4), "Est. Value USD (ref-price based)": round(est, 2) if est else None,
            "Ref Unit Price USD": float(rp["unit_price_usd"]) if rp else None,
            "Value Basis": "qty x ref price" if est else ("no reference price - volume/share only" if not rp else "UOM not convertible / no qty"),
            "Data Source": "Previous extraction: KSA_tender_awards_final.xlsx"}))
    stats["tenders"] = len({r["notice_id"] for r in rows})
    return out, stats


def turkey_previous_index():
    """QC-corrected previous EKAP extraction -> {(ikn, lot TR, supplier): row}."""
    if not os.path.exists(PREV_TR):
        return {}
    idx = {}
    for sh in ("2024 Data", "2025 Data", "2026 Data"):
        for r in xl_rows(PREV_TR, sh):
            k = (str(r.get("notice_id")), str(r.get("item_description") or "").strip().upper(), str(r.get("supplier_name") or "").strip().upper())
            idx[k] = r
    return idx


def turkey():
    """EKAP rows from this project, enriched with the QC-corrected previous extraction (corrected English, backfilled
    quantity/UOM, low/high bid). Lots unmapped on the TR/machine-EN text are re-tried on the corrected English.
    Previous-extraction rows absent from this project's data are added as well."""
    v, prev = vocab(), turkey_previous_index()
    used, out, stats, _cache = set(), [], Counter(), {}
    print("turkey: previous index", len(prev), flush=True)
    with open(os.path.join(HERE, "ekap", "tr_ekap_lots_all.csv"), encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for i, a in enumerate(rows):
        k = (a["Tender ID"], a["Lot Name (TR)"].strip().upper(), a["Supplier/Distributor"].strip().upper())
        p = prev.get(k)
        if p:
            used.add(k)
            stats["enriched"] += 1
        en_corr = (p or {}).get("item_description_en")
        cat = {"ou": a["OU"], "sub_ou": a["Sub-OU"], "product_category": a["Device Category"]} if a["Device Category"] else None
        method = a["Mapping Method"]
        if not cat and en_corr and en_corr.strip().upper() != a["Lot Name (EN)"].strip().upper():
            key = en_corr.strip().upper()
            if key not in _cache:
                _cache[key] = v.product(en_corr)
            cat = _cache[key]
            if cat:
                method = "en_corrected_rule"
                stats["newly_mapped_via_corrected_en"] += 1
        if not cat:
            continue
        y = int(a["Award Year"]) if a["Award Year"].isdigit() else None
        fx = try_fx(y)
        line = float(a["Line Value TRY"]) if a["Line Value TRY"] else None
        cval = float(a["Contract Value TRY"]) if a["Contract Value TRY"] else None
        uom = str((p or {}).get("item_uom") or "").strip()
        try:
            pq = float(str((p or {}).get("item_quantity") or "").replace(",", "."))
        except ValueError:
            pq = None
        qty = pq if (pq and uom and uom.lower() not in ("lot", "kalem")) else (float(a["Qty in Lot Name"]) if a["Qty in Lot Name"] else None)
        unit = (line / qty) if (line and qty and qty > 1) else (float(a["Unit Price TRY"]) if a["Unit Price TRY"] else None)
        if pq and uom and uom.lower() not in ("lot", "kalem"):
            stats["qty_from_previous"] += 1
        incl = "Included" if (y in (2024, 2025, 2026) and a["Terminated"] in ("", "Yok")) else "Review"
        out.append(base("Turkey", "EKAP v2", **{
            "Row ID": f"TR-EKAP-{a['Tender ID']}-{i}", "Source Type": "Contract", "Source URL": a["Source URL"], "Tender ID": a["Tender ID"],
            "Tender Title": a["Tender Title"], "Procurement Authority": a["Procurement Authority"], "Hospital/Buyer": a["City"],
            "Opening Date": a["Tender Date"], "Award/Contract Date": a["Award/Contract Date"], "Award Year": y,
            "Original-language Description": a["Lot Name (TR)"], "English Description": en_corr or a["Lot Name (EN)"],
            "Lot/Item No.": (p or {}).get("item_no"), "CPV/OKAS/NUPCO Code": a["CPV/OKAS Codes"], "OU": cat["ou"], "Sub-OU": cat["sub_ou"],
            "Device Category": cat["product_category"], "Company": a["Company"] or None, "Family Name": a["Family Name"] or None,
            "Supplier/Distributor": a["Supplier/Distributor"], "Manufacturer": a["Company"] or None, "Volume": qty, "UOM": uom or None,
            "Currency": "TRY", "Unit Award Price": round(unit, 4) if unit else None, "Total Award Value": line if line else cval,
            "FX Date": f"{y} average (ECB)" if fx else None, "LCY per USD": fx, "Value USD": round(line / fx, 2) if (line and fx) else None,
            "HBP USD": round(unit / fx, 4) if (unit and fx) else None,
            "Tender Stage": a["Tender Stage"], "Price Evidence": a["Price Evidence"], "Manufacturer Evidence": a["Manufacturer Evidence"],
            "Winner Disclosed?": "Yes", "Manufacturer Explicit?": "No", "Model Explicit?": "No",
            "Award vs Budget?": "Yes" if a["Approx. Cost TRY (tender/lot)"] or (p or {}).get("Approximation cost") else "No",
            "Confidence": "High" if method == "tr_rule" else "Medium", "Included/Review/Excluded": incl,
            "Caveat": "; ".join(x for x in [None if line else f"Contract value covers {a['Lots in Contract']} lots - do not sum across lots",
                                             f"low/high bid TRY {p.get('Lower_Estimation')} / {p.get('Highest_Estimation')}" if p and p.get("Lower_Estimation") else None,
                                             "mapped on QC-corrected English" if method == "en_corrected_rule" else None] if x) or None,
            "Winner (this row)": "Yes", "Value Basis": "single-lot contract value" if line else "contract-level only",
            "Data Source": THIS + ("; enriched from Turkey_EKAP_Contracts_Ending_2024_2026_EN_Corrected.xlsx" if p else "")}))
    # previous-extraction rows not present in this project's EKAP data
    for k, p in prev.items():
        if k in used:
            continue
        stats["prev_only_rows"] += 1
        key = (str(p.get("item_description")).upper(), str(p.get("item_description_en")).upper())
        if key not in _cache:
            _cache[key] = v.product(p.get("item_description")) or v.product(p.get("item_description_en"))
        cat = _cache[key]
        if not cat:
            continue
        stats["prev_only_mapped"] += 1
        y = yr(p.get("start_date"))
        fx = try_fx(y)
        val = p.get("contract_fee") if isinstance(p.get("contract_fee"), (int, float)) else p.get("Lower_Estimation")
        out.append(base("Turkey", "EKAP v2", **{
            "Row ID": f"TR-EKAP-PREV-{p.get('notice_id')}-{p.get('item_no')}", "Source Type": "Contract", "Source URL": p.get("notice_url"),
            "Tender ID": p.get("notice_id"), "Tender Title": p.get("title_en"), "Procurement Authority": p.get("awarding_agency_name_en"),
            "Publication Date": p.get("publication_date"), "Award/Contract Date": p.get("start_date"), "Award Year": y,
            "Original-language Description": p.get("item_description"), "English Description": p.get("item_description_en"),
            "Lot/Item No.": p.get("item_no"), "CPV/OKAS/NUPCO Code": p.get("source_cpv_code"), "OU": cat["ou"], "Sub-OU": cat["sub_ou"],
            "Device Category": cat["product_category"], "Supplier/Distributor": p.get("supplier_name"), "Volume": p.get("item_quantity"),
            "UOM": p.get("item_uom"), "Currency": "TRY", "Total Award Value": val, "FX Date": f"{y} average (ECB)" if fx else None, "LCY per USD": fx,
            "Tender Stage": "Contracted", "Price Evidence": "Contract-level only", "Manufacturer Evidence": "None", "Winner Disclosed?": "Yes",
            "Confidence": "Medium", "Included/Review/Excluded": "Included" if y in (2024, 2025, 2026) else "Review",
            "Caveat": "Previous extraction only (not in this project's EKAP pull); contract value may cover several lots",
            "Winner (this row)": "Yes", "Value Basis": "contract-level only",
            "Data Source": "Previous extraction: Turkey_EKAP_Contracts_Ending_2024_2026_EN_Corrected.xlsx"}))
    return out, stats


def pk_kp():
    rows = xl_rows(os.path.join(HERE, "pakistan", "PK_KP_BER_Mapped.xlsx"), "Bids")
    mcc, dghs = [], []
    for i, a in enumerate(rows):
        if not a.get("Device Category"):
            continue
        is_mcc = a["Source"].startswith("KP Govt MCC")
        r = base("Pakistan", "KP Govt MCC (dghskp / healthkp)" if is_mcc else "KP DGHS rate contract (healthkp)", **{
            "Row ID": f"PK-KP-{'MCC' if is_mcc else 'DGHS'}-{a['FY']}-{a['Item Ref']}-{i}", "Source Type": "BER", "Source URL": a["Document"],
            "Tender ID": f"{a['Source']} FY{a['FY']}", "Tender Title": a["Source"], "Tender Type": "Rate contract / framework",
            "Procurement Authority": "Directorate General Health Services, Khyber Pakhtunkhwa", "Award Year": a["FY"],
            "English Description": a["Item Description"], "Lot/Item No.": a["Item Ref"], "OU": a["OU"], "Sub-OU": a["Sub-OU"],
            "Device Category": a["Device Category"], "Company": a["Company"], "Disclosed Brand": a["Make / Brand text"],
            "Supplier/Distributor": a["Bidder (supplier/distributor)"], "Manufacturer": a["Company"], "Currency": "PKR",
            "Unit Award Price": a["Unit Price PKR"], "FX Date": "2026-10-01 spot", "LCY per USD": FIX["PKR"], "HBP USD": a["Unit Price USD"],
            "Tender Stage": a["Tender Stage"], "Price Evidence": a["Price Evidence"], "Manufacturer Evidence": a["Manufacturer Evidence"],
            "Winner Disclosed?": "Yes", "Manufacturer Explicit?": "Yes" if a["Manufacturer Evidence"] == "Explicit" else "No",
            "Model Explicit?": "Yes" if a.get("Make / Brand text") else "No", "Award vs Budget?": "No", "Confidence": "Medium",
            "Included/Review/Excluded": a["Included/Review/Excluded"], "Caveat": "BER: unit price per bid; no quantity published",
            "Winner (this row)": a["Winner"] or "No"})
        (mcc if is_mcc else dghs).append(r)
    return mcc, dghs


def pk_federal():
    out = []
    for i, a in enumerate(xl_rows(os.path.join(HERE, "pakistan", "federal", "PK_Federal_Evaluations_Mapped.xlsx"), "Item_Bids")):
        if not a.get("Device Category"):
            continue
        out.append(base("Pakistan", "Federal PPRA EPMS / EPADS", **{
            "Row ID": f"PK-FED-{a['Evaluation No']}-{i}", "Source Type": "Evaluation report",
            "Source URL": f"https://epms.ppra.gov.pk/public/evaluations/evaluation-details/{a['Evaluation No']}", "Tender ID": a["Evaluation No"],
            "Tender Title": a["Procurement"], "Procurement Authority": a["Buyer"], "Result Date": a["Published"], "Award Year": yr(a["Published"]),
            "English Description": a["Item"], "CPV/OKAS/NUPCO Code": f"UNSPSC: {a['UNSPSC']}", "OU": a["OU"], "Sub-OU": a["Sub-OU"],
            "Device Category": a["Device Category"], "Supplier/Distributor": a["Bidder (distributor)"], "Currency": "PKR",
            "Total Award Value": a["Offer PKR (line total)"], "FX Date": "2026-10-01 spot", "LCY per USD": FIX["PKR"], "Value USD": a["Offer USD"],
            "Tender Stage": a["Tender Stage"], "Price Evidence": a["Price Evidence"], "Manufacturer Evidence": "None",
            "Winner Disclosed?": "Yes", "Manufacturer Explicit?": "No", "Model Explicit?": "No", "Award vs Budget?": "No", "Confidence": "Medium",
            "Included/Review/Excluded": "Included" if a["Winner"] == "Yes" else "Review", "Caveat": "Offer is a line total; quantity not published",
            "Winner (this row)": a["Winner"] or "No"}))
    return out


def kuwait():
    out = []
    for i, a in enumerate(xl_rows(os.path.join(HERE, "kuwait", "KW_CAPT_Awards.xlsx"), "All_Awards")):
        if not a.get("Device Category"):
            continue
        out.append(base("Kuwait", "CAPT", **{
            "Row ID": f"KW-CAPT-{a['Tender No']}-{i}", "Source Type": "Award list", "Tender ID": a["Tender No"],
            "Tender Title": a["Subject (EN, machine)"], "Procurement Authority": a["Organisation"], "Award/Contract Date": a["Meeting Date"],
            "Award Year": yr(a["Meeting Date"]), "Original-language Description": a["Subject (AR)"], "English Description": a["Subject (EN, machine)"],
            "OU": a["OU"], "Sub-OU": a["Sub-OU"], "Device Category": a["Device Category"], "Supplier/Distributor": a["Winner"], "Currency": "KWD",
            "Total Award Value": a["Total KD"], "LCY per USD": FIX["KWD"], "Value USD": a["Total USD (approx)"], "Tender Stage": "Awarded",
            "Price Evidence": "Contract-level only", "Manufacturer Evidence": "None", "Winner Disclosed?": "Yes",
            "Included/Review/Excluded": "Included", "Caveat": "Volume signal only (Phase 4)"}))
    return out


def uae():
    out = []
    for i, a in enumerate(xl_rows(os.path.join(HERE, "uae", "UAE_Dubai_eSupply_Volume.xlsx"), "Mapped_Items")):
        out.append(base("UAE", "Dubai eSupply", **{
            "Row ID": f"AE-ESUP-{a['Project Code']}-{a['Line']}", "Source Type": "RFQ (past opportunity)", "Tender ID": a["Project Code"],
            "Tender Title": a["Project Title"], "Procurement Authority": a["Buyer"], "Hospital/Buyer": a["Buyer"], "Publication Date": a["Publication Date"],
            "Award Year": a["Year"], "English Description": a["Item"], "Lot/Item No.": a["Line"], "CPV/OKAS/NUPCO Code": a["Item Code"],
            "OU": a["OU"], "Sub-OU": a["Sub-OU"], "Device Category": a["Device Category"], "Volume": a["Qty"], "UOM": a["UOM"], "Currency": "AED",
            "LCY per USD": FIX["AED"], "Tender Stage": "Pipeline", "Price Evidence": "None", "Manufacturer Evidence": "None", "Winner Disclosed?": "No",
            "Manufacturer Explicit?": "No", "Model Explicit?": "No", "Award vs Budget?": "No", "Confidence": "Medium",
            "Included/Review/Excluded": "Review", "Exclusion Reason": "No award published - volume signal only",
            "Caveat": "Requested quantity; UOM as written by buyer; re-issued RFQs may double-count"}))
    return out


def main():
    mcc, dghs = pk_kp()
    ksa_rows = ksa()
    have = {os.path.basename(p)[:-4].replace("_", "/") for p in __import__("glob").glob(os.path.join(HERE, "ksa", "final", "*.pdf"))}
    ksa_prev, ksa_st = ksa_previous(have)
    print("ksa previous done", dict(ksa_st), flush=True)
    tr_rows, tr_st = turkey()
    others = {"Pakistan - KP MCC": mcc, "Pakistan - KP DGHS": dghs, "Pakistan - Federal EPMS": pk_federal(), "Kuwait - CAPT": kuwait(),
              "UAE - Dubai eSupply": uae()}
    for name, rows in list(others.items()) + [("KSA", ksa_rows)]:
        for r in rows:
            r["Data Source"] = r["Data Source"] or THIS.replace("NUPCO PDFs / EKAP API", r["Portal"])
    tabs = [("KSA - NUPCO", ksa_rows + ksa_prev), ("Turkey - EKAP", tr_rows)] + list(others.items())
    print("KSA previous extraction:", dict(ksa_st), "| Turkey:", dict(tr_st))
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    hdr = PatternFill("solid", fgColor="1F4E78")
    extra = PatternFill("solid", fgColor="7F7F7F")

    rd = wb.create_sheet("README")
    notes = [
        ("TURMECA master - mapped data", "One tab per country x website. Only rows mapped to a Mapping_Taxonomy.xlsx Device Category are included. "
         "Columns = the common master-table schema (TURMECA_Tender_Master.xlsx > Master_Table) + 5 grey source-specific columns at the right."),
        ("Mapping", "Device Category / Sub-OU / OU from the line text only (vocab_rules.py: EN + TR + AR rules). Company from the published "
                    "manufacturer only (KSA), or the supplier's own name when it is the OEM/affiliate (Turkey), else blank."),
        ("Value", "KSA: no prices published - 'Est. Value USD (ref-price based)' = requested qty x Pakistan KP reference unit price x 1/n (13 categories); "
                  "Turkey: Value USD only for single-lot contracts (contract value / ECB annual USD-TRY); Pakistan: KP unit prices (HBP USD), federal line totals; "
                  "Kuwait/UAE: volume signals only, no value built (Phase 4)."),
        ("FX", f"TRY per USD (ECB annual avg): 2024 {FX['2024']['TRY']}, 2025 {FX['2025']['TRY']}, 2026 {FX['2026']['TRY']}; {FIX['note']}."),
        ("Kuwait", "CAPT awards 2024-26 contain no device purchases (MOH awards there are services/maintenance), so the Kuwait tab has no mapped rows."),
        ("Turkey", "EKAP pull stopped by the user mid-way (core tier complete, partial tier in progress); plus details cached from the earlier IVD pull."),
        ("Previous extractions", f"KSA_tender_awards_final.xlsx: {ksa_st['rows']} award rows from {ksa_st['tenders']} NUPCO tenders NOT in this project's "
                                 f"41 final-result PDFs were added ({ksa_st['mapped']} mapped). Tenders present in both keep this project's rows "
                                 "(they carry the manufacturer). Its 'amount' is a tender-level figure repeated per row, not a price - not used for value. "
                                 f"Turkey_EKAP_Contracts_Ending_2024_2026_EN_Corrected.xlsx: same EKAP contracts as this project ({tr_st['enriched']} rows matched); "
                                 f"used to enrich them (corrected English, backfilled qty/UOM on {tr_st['qty_from_previous']} mapped rows -> unit price, low/high bids); "
                                 f"{tr_st['newly_mapped_via_corrected_en']} extra lots mapped on the corrected English; {tr_st['prev_only_rows']} rows only in the previous file "
                                 f"({tr_st['prev_only_mapped']} mapped) added. See the 'Data Source' column."),
    ]
    for a, b in notes:
        rd.append([a, b])
        rd.cell(rd.max_row, 1).font = Font(bold=True)
        rd.cell(rd.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
    rd.column_dimensions["A"].width = 26
    rd.column_dimensions["B"].width = 150

    sm = wb.create_sheet("Summary")
    sm.append(["Tab", "Country", "Portal(s)", "Mapped rows", "Included", "2024", "2025", "2026", "Rows with Value USD", "Rows with Est. Value USD",
               "Distinct Device Categories", "Medtronic rows"])
    for c in sm[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), hdr
    ou_rows = []
    for name, rows in tabs:
        ys = Counter(str(r["Award Year"])[:4] for r in rows)
        sm.append([name, rows[0]["Country"] if rows else name.split(" - ")[0], ", ".join(sorted({r["Portal"] for r in rows})) if rows else "",
                   len(rows), sum(1 for r in rows if r["Included/Review/Excluded"] == "Included"),
                   ys.get("2024", 0), ys.get("2025", 0), ys.get("2026", 0),
                   sum(1 for r in rows if r["Value USD"]), sum(1 for r in rows if r["Est. Value USD (ref-price based)"]),
                   len({r["Device Category"] for r in rows}), sum(1 for r in rows if r["Company"] == "Medtronic")])
        ou = Counter(r["OU"] for r in rows)
        for k, n in ou.most_common():
            ou_rows.append([name, k, n])
    sm.append([])
    sm.append(["Tab", "OU", "Mapped rows"])
    for c in sm[sm.max_row]:
        c.font = Font(bold=True)
    for r in ou_rows:
        sm.append(r)
    for i, w in enumerate([26, 10, 45, 12, 10, 8, 8, 8, 14, 16, 14, 12], 1):
        sm.column_dimensions[get_column_letter(i)].width = w

    for name, rows in tabs:
        ws = wb.create_sheet(name[:31])
        ws.append(COLS)
        for i, c in enumerate(ws[1], 1):
            c.font, c.alignment = Font(bold=True, color="FFFFFF"), Alignment(wrap_text=True, vertical="center")
            c.fill = extra if i > COLS.index("Caveat") + 1 else hdr
        if not rows:
            ws.append(["(no rows mapped to a taxonomy Device Category for this source - see README)"])
        for r in rows:
            ws.append([r[c] for c in COLS])
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(COLS))}{max(2, len(rows)+1)}"
        for i, c in enumerate(COLS, 1):
            ws.column_dimensions[get_column_letter(i)].width = 45 if "Description" in c or c == "Tender Title" else (28 if c in ("Device Category", "Sub-OU", "OU", "Supplier/Distributor", "Procurement Authority") else 13)
        for col in ("Publication Date", "Result Date", "Award/Contract Date"):
            j = COLS.index(col) + 1
            for row in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                if isinstance(row[0].value, (datetime, date)):
                    row[0].number_format = "yyyy-mm-dd"
    wb.save(OUT)
    for name, rows in tabs:
        print(f"{name:26} {len(rows):6} rows")


if __name__ == "__main__":
    main()
