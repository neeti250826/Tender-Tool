"""Additive recall boosters, applied ONLY to dimensions the precise English
matcher left blank, each tagged with its own method for auditability:

  * bilingual keyword layer  -> method "bilingual"   (English + Vietnamese device
    terms grounded in real taxonomy values, run over EN + Vietnamese line-item text)
  * multi-token supplier match-> method "supplier_name" (Company from the awarded
    supplier only when the supplier literally contains a >=2-word OEM name)

Vietnamese keys are written WITHOUT diacritics because taxonomy.norm() strips them
(NFKD -> ascii). Keys are matched as whole bounded phrases on normalised text.
"""
from __future__ import annotations
import re
from taxonomy import norm

# Each rule: patterns (normalised, ascii, no diacritics) -> dimension values to set.
# Only high-confidence, unambiguous device terms. Multi-syllable VN phrases are used
# to avoid single-syllable false positives.
BILINGUAL = [
    # --- Respiratory / Acute Care & Monitoring ---
    {"pats": ["endotracheal", "noi khi quan", "ong noi khi quan"],
     "set": {"product_category": "Endotracheal Tubes", "sub_ou": "Airway Management", "ou": "Acute Care & Monitoring (ACM)"}},
    {"pats": ["tracheostomy", "canuyn mo khi quan", "ong mo khi quan"],
     "set": {"product_category": "Tracheostomy Tubes", "sub_ou": "Airway Management", "ou": "Acute Care & Monitoring (ACM)"}},
    {"pats": ["breathing circuit", "day may tho", "he thong day tho", "bo day tho"],
     "set": {"product_category": "Breathing Circuits", "sub_ou": "Breathing Systems", "ou": "Acute Care & Monitoring (ACM)"}},
    # --- Cardiac Surgery: perfusion ---
    {"pats": ["oxygenator", "mang trao doi oxy", "phoi nhan tao", "mang oxy hoa"],
     "set": {"product_category": "Cardiopulmonary/Oxygenators", "ou": "Cardiac Surgery (CS)"}},
    # --- Cardiac Rhythm Management ---
    {"pats": ["pacemaker", "may tao nhip"],
     "set": {"product_category": "Pacemakers", "sub_ou": "Cardiac Pacing Therapies", "ou": "Cardiac Rhythm Management (CRM)"}},
    {"pats": ["defibrillator", "may khu rung tim", "may soc dien tim"],
     "set": {"sub_ou": "Defibrillation Solutions", "ou": "Cardiac Rhythm Management (CRM)"}},
    # --- Coronary ---
    {"pats": ["coronary stent", "stent dong mach vanh", "stent mach vanh"],
     "set": {"sub_ou": "PCI Stents", "ou": "Coronary and Renal Denervation (CRDN)"}},
    {"pats": ["bong nong mach vanh", "coronary balloon"],
     "set": {"sub_ou": "PCI Non Stents", "ou": "Coronary and Renal Denervation (CRDN)"}},
    # --- Structural Heart ---
    {"pats": ["heart valve", "van tim", "van dong mach chu", "van hai la", "van ba la"],
     "set": {"ou": "Structural Heart and Aortic (SH&A)"}},
    # --- Cardiac Ablation ---
    {"pats": ["ablation catheter", "catheter dot", "dot song cao tan", "cath dot"],
     "set": {"product_category": "Ablation Catheter", "sub_ou": "Cardiac Ablation Solutions (CAS)", "ou": "Cardiac Ablation Solutions"}},
    # --- Surgical Innovations ---
    {"pats": ["hernia mesh", "surgical mesh", "luoi thoat vi", "luoi phau thuat", "tam luoi"],
     "set": {"product_category": "Mesh", "sub_ou": "Hernia", "ou": "Surgical Innovations (SI)"}},
    {"pats": ["surgical stapler", "ghim khau noi", "may khau noi", "ghim phau thuat", "may cat noi"],
     "set": {"sub_ou": "Stapling", "ou": "Surgical Innovations (SI)"}},
    {"pats": ["trocar", "trycar"],
     "set": {"product_category": "Trocars", "ou": "Surgical Innovations (SI)"}},
    # --- Orthopedics / Trauma (product only; OU ambiguous across CST/China Ortho) ---
    {"pats": ["intramedullary nail", "dinh noi tuy"],
     "set": {"product_category": "Intramedullary Nails"}},
    {"pats": ["plate and screw", "plates and screws", "bone plate", "nep vit", "nep khoa"],
     "set": {"product_category": "Plates & Screws"}},
    {"pats": ["cannulated screw", "vit xop", "vit rong"],
     "set": {"product_category": "Cannulated Screws"}},
    {"pats": ["hip replacement", "khop hang nhan tao", "thay khop hang", "chom khop hang"],
     "set": {"product_category": "Hip Replacement"}},
    # --- Neurovascular ---
    {"pats": ["embolic coil", "coil nut mach", "vong xoan kim loai", "coil dien tu"],
     "set": {"ou": "Neurovascular (NV)"}},
    # --- Endoscopy ---
    {"pats": ["colonoscope", "gastroscope", "duodenoscope", "day soi mem"],
     "set": {"ou": "Endoscopy"}},
    {"pats": ["esd knife", "dao cat hot niem mac", "dao cam mau cat hot niem mac"],
     "set": {"ou": "Endoscopy"}},
    # --- Guidewire ---
    {"pats": ["guidewire", "guide wire", "day dan huong"],
     "set": {"product_category": "Guidewire"}},
]

# Precompile bounded-phrase regexes on normalised text.
for r in BILINGUAL:
    r["res"] = [re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])") for p in r["pats"]]

DIMS = ("ou", "sub_ou", "product_category", "company", "family")


def bilingual_matches(all_text: str) -> dict:
    """Return {dim: (value, matched_pattern, 'bilingual', score, 'medium', extra)}.
    Tuple shape matches matcher payloads: (value, term, method, score, conf, extra)."""
    t = norm(all_text)
    if not t:
        return {}
    out = {}
    for r in BILINGUAL:
        hit = None
        for pat, rx in zip(r["pats"], r["res"]):
            if rx.search(t):
                hit = pat
                break
        if hit:
            for dim, val in r["set"].items():
                if dim not in out:  # first rule wins per dimension
                    out[dim] = (val, hit, "bilingual", 1.0, "medium", {})
    return out
