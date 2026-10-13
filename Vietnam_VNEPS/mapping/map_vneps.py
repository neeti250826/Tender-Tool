# -*- coding: utf-8 -*-
"""Map the VNEPS awarded-device CSV to the Clearstate taxonomy and add English columns.

Company  <- manufacturer + brand (already English)
Product/OU/Sub-OU/Family <- Vietnamese name + English gloss (bilingual + taxonomy matcher)
                            + a keyword-based OU/Sub-OU anchor (the search term per row).
Output: VNEPS_Awarded_Medtech_Mapped.xlsx  (Mapped / Unmapped / Summary)
"""
from __future__ import annotations
import sys, time, datetime
from collections import Counter
import pandas as pd
import openpyxl
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, PatternFill
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

sys.path.insert(0, r"<WORKSPACE>/mapping")
from taxonomy import load_taxonomy
from matcher import match_row
from enrich import bilingual_matches
from translate_vn import name_en_gloss, unit_en, origin_en, year_en, bid_form_en, entity_en

SRC = r"<DOWNLOADS>/vneps_awarded_medtech.csv"
TAXO = r"<DOWNLOADS>/Mapping_Taxonomy.xlsx"
OUT = r"<WORKSPACE>/VNEPS_Awarded_Medtech_Mapped.xlsx"
TRANS_DIRS = [r"<WORKSPACE>/mapping/name_trans",
              r"<WORKSPACE>/mapping/name_trans_v2"]
DIMS_ORDER = ["ou", "sub_ou", "product_category", "company", "family"]


def _wsnorm(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def load_translations():
    """Merge all name_trans/*.tsv into a {vietnamese_name: english} dict (LLM output).
    Adds a whitespace-normalised key alias so trailing/double-space variants still match."""
    import glob, os
    d = {}
    files = [f for dpath in TRANS_DIRS for f in sorted(glob.glob(os.path.join(dpath, "*.tsv")))]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if "\t" in line:
                    vi, en = line.split("\t", 1)
                    if vi.strip() and en.strip():
                        d[vi.strip()] = en.strip()
                        d.setdefault(_wsnorm(vi), en.strip())
    return d


def lookup_trans(trans, name):
    return trans.get(name.strip()) or trans.get(_wsnorm(name))


# Vascular device keywords whose OU depends on the anatomical bed in the name.
VASCULAR_KWS = {"stent", "bóng nong", "nút mạch", "guide wire",
                "dây dẫn can thiệp", "coil nút mạch", "vòng xoắn"}
# (marker list, (ou, sub_ou)) — checked in order; first hit wins.
ANATOMY_OU = [
    (["mạch vành", "động mạch vành", "coronary"], ("Coronary and Renal Denervation (CRDN)", "")),
    (["động mạch thận", " renal", "renal artery"], ("Coronary and Renal Denervation (CRDN)", "")),
    (["nội sọ", "mạch máu não", "mạch não", "cerebral", "intracranial", "túi phình",
      "aneurysm", "thần kinh", "neurovascular"], ("Neurovascular (NV)", "")),
    (["động mạch cảnh", "mạch cảnh", "carotid"], ("Peripheral & Endovenous", "Peripheral Vascular")),
    (["động mạch chủ", "aorta", "aortic"], ("Structural Heart and Aortic (SH&A)", "Aortic")),
    (["ngoại vi", "ngoại biên", "đùi", "khoeo", "chi dưới", "peripheral", "femoral",
      "iliac", "popliteal"], ("Peripheral & Endovenous", "Peripheral Vascular")),
    (["tĩnh mạch", "venous"], ("Peripheral & Endovenous", "Peripheral Vascular")),
    (["đường mật", "biliary", "đường tụy", "pancreatic"], ("Endoscopy", "")),
]

def anatomy_ou(text_lower: str):
    for markers, target in ANATOMY_OU:
        if any(m in text_lower for m in markers):
            return target
    return None

# search-keyword -> fallback (ou, sub_ou) when the name doesn't resolve them itself
KW_ANCHOR = {
    "van tim": ("Structural Heart and Aortic (SH&A)", "Aortic"),
    "vòng van": ("Structural Heart and Aortic (SH&A)", "Aortic"),
    "van động mạch chủ": ("Structural Heart and Aortic (SH&A)", "Aortic"),
    "máy tạo nhịp": ("Cardiac Rhythm Management (CRM)", "Cardiac Pacing Therapies"),
    "máy phá rung": ("Cardiac Rhythm Management (CRM)", "Defibrillation Solutions"),
    # NOTE: "điện cực" (electrode) intentionally omitted — VNEPS returns IVD/analyzer
    # ISE electrodes under it, which must NOT be forced into CRM.
    "catheter đốt": ("Cardiac Ablation Solutions", "Cardiac Ablation Solutions (CAS)"),
    "ống thông đốt": ("Cardiac Ablation Solutions", "Cardiac Ablation Solutions (CAS)"),
    "lưới thoát vị": ("Surgical Innovations (SI)", "Hernia"),
    "nội khí quản": ("Acute Care & Monitoring (ACM)", "Airway Management"),
    "mở khí quản": ("Acute Care & Monitoring (ACM)", "Airway Management"),
    "trocar": ("Surgical Innovations (SI)", ""),
    "oxygenator": ("Cardiac Surgery (CS)", ""),
    "màng trao đổi oxy": ("Cardiac Surgery (CS)", ""),
    "nút mạch": ("Neurovascular (NV)", ""),
    "vòng xoắn": ("Neurovascular (NV)", ""),
    "coil nút mạch": ("Neurovascular (NV)", ""),
    "ghim khâu": ("Surgical Innovations (SI)", "Stapling"),
    "máy khâu nối": ("Surgical Innovations (SI)", "Stapling"),
    "dao siêu âm": ("Surgical Innovations (SI)", "Electrosurgery"),
    "ống nội soi": ("Endoscopy", ""),
    # Orthopedics: taxonomy has no clean general-ortho OU, so use the user-approved
    # neutral custom label "Orthopedics" (Sub-OU = Trauma for plates/nails).
    "nẹp khóa": ("Orthopedics", "Trauma"),
    "đinh nội tủy": ("Orthopedics", "Trauma"),
    "khớp háng": ("Orthopedics", ""),
    "khớp gối": ("Orthopedics", ""),

    # ===== v2 keyword anchors (new keywords) =====
    "ống thông dẫn đường": ("Coronary and Renal Denervation (CRDN)", "PCI Non Stents"),
    "ống thông chẩn đoán": ("Coronary and Renal Denervation (CRDN)", "PCI Non Stents"),
    "bóng phủ thuốc": ("Coronary and Renal Denervation (CRDN)", "PCI Non Stents"),
    "dây dẫn áp lực": ("Coronary and Renal Denervation (CRDN)", "PCI Non Stents"),
    "siêu âm nội mạch": ("Coronary and Renal Denervation (CRDN)", "PCI Non Stents"),
    "khoan cắt mảng xơ vữa": ("Peripheral & Endovenous", "Peripheral Vascular"),
    "khoan xơ vữa": ("Peripheral & Endovenous", "Peripheral Vascular"),
    "ống ghép mạch máu": ("Peripheral & Endovenous", "Peripheral Vascular"),
    "lọc tĩnh mạch chủ": ("Peripheral & Endovenous", "Peripheral Vascular"),
    "điện cực tạo nhịp": ("Cardiac Rhythm Management (CRM)", "Cardiac Pacing Therapies"),
    "máy khử rung": ("Cardiac Rhythm Management (CRM)", "Defibrillation Solutions"),
    "máy ghi điện tim cấy": ("Cardiac Rhythm Management (CRM)", "Cardiovascular Diagnostics and Services (CVDS)"),
    "dù bít": ("Structural Heart and Aortic (SH&A)", "Catheter Based Therapy"),
    "van động mạch phổi": ("Structural Heart and Aortic (SH&A)", "Aortic"),
    "ống ghép nội mạch": ("Structural Heart and Aortic (SH&A)", "Aortic"),
    "laser nội tĩnh mạch": ("Peripheral Vascular Health (PVH)", "EndoVenous"),
    "suy giãn tĩnh mạch": ("Peripheral Vascular Health (PVH)", "EndoVenous"),
    "sóng cao tần tĩnh mạch": ("Peripheral Vascular Health (PVH)", "EndoVenous"),
    "nút mạch ngoại vi": ("Peripheral Vascular Health (PVH)", "EndoVenous"),
    "stent chuyển dòng": ("Neurovascular (NV)", "Hemorrhagic Stroke"),
    "ống hút huyết khối": ("Neurovascular (NV)", "Acute Ischemic Stroke"),
    "dụng cụ lấy huyết khối": ("Neurovascular (NV)", "Acute Ischemic Stroke"),
    "keo nút mạch": ("Neurovascular (NV)", "Hemorrhagic Stroke"),
    "bóng chẹn": ("Neurovascular (NV)", "Hemorrhagic Stroke"),
    "chỉ khâu": ("Surgical Innovations (SI)", "Wound Management"),
    "dao điện": ("Surgical Innovations (SI)", "Electrosurgery"),
    "dao hàn mạch": ("Surgical Innovations (SI)", "Vessel Sealing"),
    "clip phẫu thuật": ("Surgical Innovations (SI)", "Instruments and Access"),
    "vật liệu cầm máu": ("Surgical Innovations (SI)", "Wound Management"),
    "máy cắt nối": ("Surgical Innovations (SI)", "Stapling"),
    "viên nang nội soi": ("Endoscopy", "GI - Chronic and Colorectal"),
    "clip cầm máu": ("Endoscopy", "GI - Chronic and Colorectal"),
    "thòng lọng": ("Endoscopy", "GI - Chronic and Colorectal"),
    "kim tiêm cầm máu": ("Endoscopy", "GI - Chronic and Colorectal"),
    "ống nong đường mật": ("Endoscopy", "GI - Hepatopancreatobiliary (HPB)"),
    "nội soi tai mũi họng": ("Ear Nose Throat (ENT)", "Ear Nose Throat (ENT)"),
    "bóng nong xoang": ("Ear Nose Throat (ENT)", "Ear Nose Throat (ENT)"),
    "dao bào": ("Ear Nose Throat (ENT)", "Ear Nose Throat (ENT)"),
    "cảm biến spo2": ("Acute Care & Monitoring (ACM)", "Respiratory Compromise"),
    "chăn sưởi": ("Acute Care & Monitoring (ACM)", "Temperature"),
    "vít cột sống": ("Cranial & Spinal Technologies (CST)", "Total Spinal"),
    "lồng liên thân đốt": ("Cranial & Spinal Technologies (CST)", "Total Spinal"),
    "nẹp cột sống": ("Cranial & Spinal Technologies (CST)", "Total Spinal"),
    "van dẫn lưu não thất": ("Cranial & Spinal Technologies (CST)", "CSF&CC"),
    "dẫn lưu não thất": ("Cranial & Spinal Technologies (CST)", "CSF&CC"),
    "nẹp sọ": ("Cranial & Spinal Technologies (CST)", "CSF&CC"),
    "kích thích tủy sống": ("Neuromodulation (NM)", "Neuromodulation - Pain"),
    "kích thích não sâu": ("Neuromodulation (NM)", "Neuromodulation - Brain Modulation"),
    "kích thích thần kinh cùng": ("Neuromodulation (NM)", "Sacral Neuromodulation (SNM)"),
    "bơm insulin": ("Diabetes", "Pump"),
    "cảm biến đường huyết": ("Diabetes", "Pump"),
    "robot phẫu thuật": ("Surgical Robotics", "Robotic Surgical Technologies"),
    "ống thông JJ": ("Urology", "Urology"),
    "máy tán sỏi": ("Urology", "Urology"),
}

# Product-category -> (OU, Sub-OU) fallback, applied when OU is still empty.
CAT_OU = {
    "diagnostic catheter": ("Cardiac Ablation Solutions", "Cardiac Ablation Solutions (CAS)"),
    "diagnostic catheters": ("Cardiac Ablation Solutions", "Cardiac Ablation Solutions (CAS)"),
    "electrosurgical accessories": ("Surgical Innovations (SI)", "Electrosurgery"),
    "flow diverters": ("Neurovascular (NV)", ""),
}
# Product categories that are orthopedic -> OU "Orthopedics" (user-approved label).
ORTHO_CATS = {"plates & screws", "intramedullary nails", "cannulated screws",
              "hip replacement", "knee replacement", "cannulae - femoral", "bone cement"}
# Interventional guidewire/balloon keywords default to Coronary when no vessel named.
DEFAULT_CORONARY_KWS = {"guide wire", "dây dẫn can thiệp", "bóng nong", "vi ống thông"}

# Keyword -> (default Sub-OU, default Product Category), applied as a fallback when the
# matcher left them blank. Grounded in real taxonomy values. "" = do not set.
KW_DEFAULTS = {
    "van tim": ("Aortic", ""), "vòng van": ("Aortic", ""), "van động mạch chủ": ("Aortic", ""),
    "máy tạo nhịp": ("Cardiac Pacing Therapies", "Pacemakers"),
    "máy phá rung": ("Defibrillation Solutions", ""),
    "catheter đốt": ("Cardiac Ablation Solutions (CAS)", "Ablation Catheter"),
    "ống thông đốt": ("Cardiac Ablation Solutions (CAS)", "Ablation Catheter"),
    "lưới thoát vị": ("Hernia", "Mesh"),
    "nẹp khóa": ("Trauma", "Plates & Screws"),
    "đinh nội tủy": ("Trauma", "Intramedullary Nails"),
    "khớp háng": ("Hip Replacement", "Hip Replacement"),
    "khớp gối": ("Joint Replacement", ""),
    "nội khí quản": ("Airway Management", "Endotracheal Tubes"),
    "mở khí quản": ("Airway Management", "Tracheostomy Tubes"),
    "trocar": ("Instruments and Access", "Trocars"),
    "oxygenator": ("", "Cardiopulmonary/Oxygenators"),
    "màng trao đổi oxy": ("", "Cardiopulmonary/Oxygenators"),
    "ghim khâu": ("Stapling", ""), "máy khâu nối": ("Stapling", ""),
    "dao siêu âm": ("Vessel Sealing", "Vessel Sealing Devices - Ultrasonic Energy"),
    "nút mạch": ("Hemorrhagic Stroke", ""),
    "vòng xoắn": ("Hemorrhagic Stroke", "Embolic Coils - Detachable"),
    "coil nút mạch": ("Hemorrhagic Stroke", "Embolic Coils - Detachable"),
    "guide wire": ("PCI Non Stents", "Guidewire"),
    "dây dẫn can thiệp": ("PCI Non Stents", "Guidewire"),
    "bóng nong": ("PCI Non Stents", ""),

    # ===== v2 product-category defaults (new keywords) =====
    "ống thông dẫn đường": ("", "Guiding Catheters"),
    "vi ống thông": ("", "Microcatheters"),
    "ống thông chẩn đoán": ("", "Diagnostic Catheters"),
    "bóng phủ thuốc": ("", "Drug Coated Balloons"),
    "siêu âm nội mạch": ("", "Intravascular Ultrasound (IVUS) - Catheter"),
    "khoan cắt mảng xơ vữa": ("", "Atherectomy"),
    "khoan xơ vữa": ("", "Atherectomy"),
    "điện cực tạo nhịp": ("", "Leads"),
    "ống ghép mạch máu": ("", "Peripheral Vascular Grafts"),
    "lọc tĩnh mạch chủ": ("", "Vena Cava Filters"),
    "laser nội tĩnh mạch": ("", "Superficial Venous - EVLA"),
    "sóng cao tần tĩnh mạch": ("", "Superficial Venous - RFA Catheter"),
    "stent chuyển dòng": ("", "Flow Diverters"),
    "ống hút huyết khối": ("", "Aspiration Catheters"),
    "dụng cụ lấy huyết khối": ("", "Stent Retrievers"),
    "keo nút mạch": ("", "Liquid Embolics"),
    "bóng chẹn": ("", "Accessory Products - Occlusion Balloon Systems"),
    "dao điện": ("", "Electrosurgical Devices"),
    "dao hàn mạch": ("", "Vessel Sealing Devices"),
    "vật liệu cầm máu": ("", "Hemostat"),
    "viên nang nội soi": ("", "Capsule"),
    "bóng nong xoang": ("", "Balloon Sinus Dilation"),
    "dao bào": ("", "ENT Microdebriders"),
    "van dẫn lưu não thất": ("", "Hydrocephalus"),
    "dẫn lưu não thất": ("", "EDMS"),
    "kích thích tủy sống": ("", "SCS Leads"),
    "kích thích não sâu": ("", "DBS Leads"),
    "kích thích thần kinh cùng": ("", "Sacral Neuromodulation (SNM) - Implants"),
    "bơm insulin": ("", "Pumps"),
    "cảm biến đường huyết": ("", "Pump Sensors"),
    "máy tán sỏi": ("", "Lithotripters (exclude laser)"),
}
# For stents, the Sub-OU follows the OU (vascular bed) the anatomy inference assigned.
STENT_OU_SUBOU = {
    "Coronary and Renal Denervation (CRDN)": "PCI Stents",
    "Peripheral & Endovenous": "Peripheral Vascular",
    "Neurovascular (NV)": "Hemorrhagic Stroke",
    "Structural Heart and Aortic (SH&A)": "Aortic",
    "Structural Heart & Aortic": "Aortic",
}

# IVD / lab markers — if present in the name, do NOT apply a device keyword anchor
# (guards against analyzer reagents/electrodes pulled in by ambiguous searches).
IVD_MARKERS = ["xét nghiệm", "điện giải", "miễn dịch", "sinh hóa", "hóa chất",
               "dung dịch rửa", "dung dịch vệ sinh", "thuốc thử", "hiệu chuẩn",
               "định lượng", "huyết học", "đông máu", "reagent", "calibrat"]

def _is_ivd(nm: str) -> bool:
    nl = (nm or "").lower()
    return any(m in nl for m in IVD_MARKERS)


def sanitize(v):
    if v is None:
        return None
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return str(v)
    s = str(v)
    s = ILLEGAL_CHARACTERS_RE.sub("", s)
    return s[:32000] if len(s) > 32000 else s


def main():
    t0 = time.time()
    dims = load_taxonomy(TAXO)
    df = pd.read_csv(SRC, dtype=str, keep_default_na=False)
    n = len(df)
    print("rows:", n)

    # English columns — prefer LLM translation, fall back to the device gloss
    trans = load_translations()
    print("loaded LLM translations:", len(trans))
    df["name_en"] = df["name"].map(lambda x: lookup_trans(trans, x) or name_en_gloss(x))
    df["name_en_source"] = df["name"].map(lambda x: "llm" if lookup_trans(trans, x) else "gloss")
    df["unit_en"] = df["unit"].map(unit_en)
    df["origin_en"] = df["origin"].map(origin_en)
    df["year_en"] = df["year"].map(year_en)
    df["bid_form_en"] = df["bid_form"].map(bid_form_en)
    df["buyer_en"] = df["buyer"].map(entity_en)
    df["supplier_en"] = df["supplier"].map(entity_en)

    map_cols = {d: [] for d in DIMS_ORDER}
    map_term = {d: [] for d in DIMS_ORDER}
    map_meth = {d: [] for d in DIMS_ORDER}
    status_col, fields_col, ndim_col, famcat_col = [], [], [], []
    stats = Counter(); dim_vals = {d: Counter() for d in DIMS_ORDER}; meth = Counter()

    names = df["name"].tolist(); names_en = df["name_en"].tolist()
    manuf = df["manufacturer"].tolist(); brand = df["brand"].tolist(); kws = df["keyword"].tolist()

    for i in range(n):
        item_text = names[i] + " " + names_en[i]
        company_text = (manuf[i] or "") + " " + (brand[i] or "")
        res = match_row(dims, item_text, item_text, company_text)
        for d, m in bilingual_matches(names[i] + " " + names_en[i]).items():
            if not res.get(d):
                res[d] = m
        ivd = _is_ivd(names[i])
        # keyword anchor fills OU / Sub-OU if still empty (skip for IVD/lab items)
        anc = KW_ANCHOR.get(kws[i])
        if anc and not ivd:
            if not res.get("ou") and anc[0]:
                res["ou"] = (anc[0], "keyword:" + kws[i], "keyword_anchor", 1.0, "medium", {})
            if not res.get("sub_ou") and anc[1]:
                res["sub_ou"] = (anc[1], "keyword:" + kws[i], "keyword_anchor", 1.0, "medium", {})
        # anatomy-based OU for vascular device rows (stents, balloons, coils, guidewires)
        if not res.get("ou") and kws[i] in VASCULAR_KWS and not ivd:
            hit = anatomy_ou((names[i] + " " + names_en[i]).lower())
            if hit:
                res["ou"] = (hit[0], "anatomy", "anatomy_ou", 1.0, "medium", {})
                if hit[1] and not res.get("sub_ou"):
                    res["sub_ou"] = (hit[1], "anatomy", "anatomy_ou", 1.0, "medium", {})
        # product-category -> OU fallback (EP catheters, electrosurgical, flow diverters, ortho)
        if not res.get("ou") and res.get("product_category"):
            pc = res["product_category"][0].lower()
            if pc in CAT_OU and not ivd:
                ou_v, sub_v = CAT_OU[pc]
                res["ou"] = (ou_v, "category:" + pc, "category_ou", 1.0, "medium", {})
                if sub_v and not res.get("sub_ou"):
                    res["sub_ou"] = (sub_v, "category:" + pc, "category_ou", 1.0, "medium", {})
            elif pc in ORTHO_CATS:
                res["ou"] = ("Orthopedics", "category:" + pc, "ortho_ou", 1.0, "medium", {})
                if not res.get("sub_ou") and pc in ("plates & screws", "intramedullary nails",
                                                     "cannulated screws", "cannulae - femoral"):
                    res["sub_ou"] = ("Trauma", "category:" + pc, "ortho_ou", 1.0, "medium", {})
        # interventional guidewire/balloon default to Coronary when no vessel named
        if not res.get("ou") and kws[i] in DEFAULT_CORONARY_KWS and not ivd:
            res["ou"] = ("Coronary and Renal Denervation (CRDN)", "default", "default_coronary", 1.0, "low", {})
        # keyword-level Sub-OU / Product-Category defaults (fill blanks only)
        kd = KW_DEFAULTS.get(kws[i])
        if kd and not ivd:
            if kd[0] and not res.get("sub_ou"):
                res["sub_ou"] = (kd[0], "keyword:" + kws[i], "keyword_default", 1.0, "medium", {})
            if kd[1] and not res.get("product_category"):
                res["product_category"] = (kd[1], "keyword:" + kws[i], "keyword_default", 1.0, "medium", {})
        # stent Sub-OU follows its (anatomy-derived) OU
        if kws[i] == "stent" and not res.get("sub_ou") and res.get("ou") and not ivd:
            sv = STENT_OU_SUBOU.get(res["ou"][0])
            if sv:
                res["sub_ou"] = (sv, "stent_ou", "keyword_default", 1.0, "medium", {})

        matched = [d for d in DIMS_ORDER if res.get(d)]
        status = "Mapped" if matched else "Unmapped"
        stats[status] += 1
        for d in matched:
            dim_vals[d][res[d][0]] += 1
            meth[res[d][2]] += 1
        status_col.append(status)
        fields_col.append(",".join(matched))
        ndim_col.append(len(matched))
        famcat_col.append(res["family"][5].get("category", "") if res.get("family") else "")
        for d in DIMS_ORDER:
            r = res.get(d)
            map_cols[d].append(r[0] if r else "")
            map_term[d].append(str(r[1]) if r else "")
            map_meth[d].append(r[2] if r else "")

    df["mapping_status"] = status_col
    df["mapped_fields"] = fields_col
    df["n_mapped_dims"] = ndim_col
    for d in DIMS_ORDER:
        df["map_" + d] = map_cols[d]
        df["map_%s_term" % d] = map_term[d]
        df["map_%s_method" % d] = map_meth[d]
    df["map_family_category"] = famcat_col

    # explicit column layout: mapping block, then data with each English column
    # placed next to its original, and supplier/buyer grouped by manufacturer.
    order = ["mapping_status", "mapped_fields", "n_mapped_dims"]
    for d in DIMS_ORDER:
        order += ["map_" + d, "map_%s_term" % d, "map_%s_method" % d]
    order += [
        "map_family_category",
        "keyword",
        "name", "name_en", "name_en_source",
        "unit", "unit_en",
        "quantity",
        "origin", "origin_en",
        "hs_code", "product_code", "brand",
        "manufacturer",
        "supplier", "supplier_en",
        "buyer", "buyer_en",
        "model", "license_no",
        "year", "year_en",
        "unit_price",
        "notice_no",
        "bid_form", "bid_form_en",
        "result_date", "decision_no", "decision_date",
        "num_contractors",
        "location",
    ]
    order = [c for c in order if c in df.columns] + [c for c in df.columns if c not in order]
    df = df[order]

    mapped_df = df[df["mapping_status"] == "Mapped"].copy()
    unmapped_df = df[df["mapping_status"] == "Unmapped"].copy()

    wb = openpyxl.Workbook(write_only=True)
    from openpyxl.cell import WriteOnlyCell
    # Summary
    s = wb.create_sheet("Summary")
    s.column_dimensions["A"].width = 40; s.column_dimensions["B"].width = 95
    tc = WriteOnlyCell(s, value="VNEPS Awarded Medtech — Taxonomy Mapping"); tc.font = Font(bold=True, size=14)
    s.append([tc])
    lines = [
        ["Generated", time.strftime("%Y-%m-%d %H:%M")],
        ["Source", "vneps_awarded_medtech.csv (VNEPS winning-bid unit-price DB, Medical Equipment)"],
        ["Total awarded items", n],
        ["Mapped (>=1 dimension)", stats["Mapped"]],
        ["Unmapped", stats["Unmapped"]],
        ["Mapped %", round(100 * stats["Mapped"] / n, 2)],
        ["", ""],
        ["English columns added", "name_en (device-glossary gloss), unit_en, origin_en, year_en, bid_form_en"],
        ["Mapping method", "manufacturer/brand -> Company; Vietnamese name + English gloss -> Product/OU/Sub-OU/Family (bilingual keyword + taxonomy match); keyword anchor for OU/Sub-OU"],
        ["", ""],
        ["Coverage by dimension", ""],
    ]
    for d in DIMS_ORDER:
        c = sum(1 for x in map_cols[d] if x)
        lines.append([d, f"{c}  ({round(100*c/n,1)}%)"])
    lines.append(["", ""]); lines.append(["Matches by method", ""])
    for m, c in meth.most_common():
        lines.append([m, c])
    lines.append(["", ""]); lines.append(["Top mapped values", ""])
    for d in DIMS_ORDER:
        lines.append([d, "; ".join(f"{v} ({c})" for v, c in dim_vals[d].most_common(10))])
    for ln in lines:
        s.append(ln)

    def write_df(title, d):
        ws = wb.create_sheet(title); ws.freeze_panes = "A2"
        header = list(d.columns)
        hc = []
        for h in header:
            c = WriteOnlyCell(ws, value=h); c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F4E78")
            hc.append(c)
        ws.append(hc)
        for row in d.itertuples(index=False, name=None):
            ws.append([sanitize(x) for x in row])

    write_df("Mapped", mapped_df)
    write_df("Unmapped", unmapped_df)
    wb.save(OUT)
    print(f"DONE {time.time()-t0:.1f}s -> {OUT}")
    print(f"Total {n} | Mapped {stats['Mapped']} ({100*stats['Mapped']/n:.1f}%) | Unmapped {stats['Unmapped']}")
    for d in DIMS_ORDER:
        c = sum(1 for x in map_cols[d] if x); print(f"  {d}: {c} ({100*c/n:.1f}%)")


if __name__ == "__main__":
    main()
