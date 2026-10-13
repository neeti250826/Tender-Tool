"""Name-based IVD brand detection for Turkish EKAP suppliers.

Layer A of the assignment: where a supplier's registered name embeds an IVD
manufacturer's brand, the supplier is that manufacturer's Turkish affiliate (or a
named-brand distributor) and can be assigned without external research.

Tokens are matched on word boundaries against the Turkish name and the English
translation, both ASCII-folded, to survive the transliteration in the source file.
"""
import json, re, unicodedata
from pathlib import Path

BASE = Path(r"<WORKSPACE>")

TR_MAP = str.maketrans("İIıŞşĞğÜüÖöÇçÂâÎî", "IIISSGGUUOOCCAAII")


def fold(s):
    s = (s or "").translate(TR_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).upper()


# brand token -> (canonical player, parent group, ivd?)
# ivd False = the brand is a medtech/pharma player with no meaningful IVD line, so
# the supplier is flagged Not IVD rather than given an IVD brand.
IVD_OEM = {
    "ROCHE": ("Roche Diagnostics", "Roche", True),
    "ABBOTT": ("Abbott Diagnostics", "Abbott", True),
    "SIEMENS HEALTHCARE": ("Siemens Healthineers", "Siemens Healthineers", True),
    "SIEMENS HEALTHINEERS": ("Siemens Healthineers", "Siemens Healthineers", True),
    "BECKMAN": ("Beckman Coulter", "Danaher", True),
    "COULTER": ("Beckman Coulter", "Danaher", True),
    "BIOMERIEUX": ("bioMerieux", "bioMerieux", True),
    "BIO MERIEUX": ("bioMerieux", "bioMerieux", True),
    "SYSMEX": ("Sysmex", "Sysmex", True),
    "ORTHO CLINICAL": ("Ortho Clinical Diagnostics", "QuidelOrtho", True),
    "QUIDEL": ("QuidelOrtho", "QuidelOrtho", True),
    "DIASORIN": ("DiaSorin", "DiaSorin", True),
    "WERFEN": ("Werfen", "Werfen", True),
    "INSTRUMENTATION LABORATORY": ("Werfen (Instrumentation Laboratory)", "Werfen", True),
    "MINDRAY": ("Mindray", "Mindray", True),
    "SNIBE": ("Snibe Diagnostics", "Snibe", True),
    "MAGLUMI": ("Snibe Diagnostics", "Snibe", True),
    "GETEIN": ("Getein Biotech", "Getein", True),
    "THERMO FISHER": ("Thermo Fisher Scientific", "Thermo Fisher", True),
    "THERMO ELECTRON": ("Thermo Fisher Scientific", "Thermo Fisher", True),
    "QIAGEN": ("QIAGEN", "QIAGEN", True),
    "ILLUMINA": ("Illumina", "Illumina", True),
    "HOLOGIC": ("Hologic", "Hologic", True),
    "CEPHEID": ("Cepheid", "Danaher", True),
    "RADIOMETER": ("Radiometer", "Danaher", True),
    "STAGO": ("Diagnostica Stago", "Stago", True),
    "SEBIA": ("Sebia", "Sebia", True),
    "EUROIMMUN": ("EUROIMMUN", "Revvity", True),
    "PERKINELMER": ("PerkinElmer / Revvity", "Revvity", True),
    "REVVITY": ("Revvity", "Revvity", True),
    "RANDOX": ("Randox Laboratories", "Randox", True),
    "HORIBA": ("Horiba Medical", "Horiba", True),
    "TOSOH": ("Tosoh Bioscience", "Tosoh", True),
    "DIATRON": ("Diatron", "Stratec", True),
    "ERBA": ("ERBA Mannheim", "Transasia/ERBA", True),
    "NIHON KOHDEN": ("Nihon Kohden", "Nihon Kohden", True),
    "SARSTEDT": ("Sarstedt", "Sarstedt", True),
    "GREINER": ("Greiner Bio-One", "Greiner", True),
    "BECTON": ("BD (Becton Dickinson)", "BD", True),
    "DICKINSON": ("BD (Becton Dickinson)", "BD", True),
    "AGAPPE": ("Agappe Diagnostics", "Agappe", True),
    "TRIVITRON": ("Trivitron Healthcare", "Trivitron", True),
    "ELITECH": ("ELITechGroup", "ELITech", True),
    "BIOSYSTEMS": ("BioSystems", "BioSystems", True),
    "DIALAB": ("DIALAB", "DIALAB", True),
    "FUJIFILM": ("Fujifilm", "Fujifilm", True),
    "SIEMENS": ("Siemens Healthineers", "Siemens Healthineers", True),
    "MERCK": ("Merck / MilliporeSigma", "Merck KGaA", True),
    "SIGMA ALDRICH": ("Merck / MilliporeSigma", "Merck KGaA", True),
    "BRUKER": ("Bruker", "Bruker", True),
    "SHIMADZU": ("Shimadzu", "Shimadzu", True),
    "AGILENT": ("Agilent Technologies", "Agilent", True),
    "LEICA": ("Leica Biosystems", "Danaher", True),
    "SAKURA": ("Sakura Finetek", "Sakura", True),
    "VENTANA": ("Roche Tissue Diagnostics (Ventana)", "Roche", True),
    "DAKO": ("Agilent Dako", "Agilent", True),
    "MILTENYI": ("Miltenyi Biotec", "Miltenyi", True),
    "IMMUCOR": ("Immucor", "Werfen", True),
    "GRIFOLS": ("Grifols", "Grifols", True),
    "MACOPHARMA": ("Macopharma", "Macopharma", True),
    "TERUMO": ("Terumo BCT", "Terumo", True),
    "WONDFO": ("Guangzhou Wondfo", "Wondfo", True),
    "AUTOBIO": ("Autobio Diagnostics", "Autobio", True),
    "MACCURA": ("Maccura Biotechnology", "Maccura", True),
    "DIRUI": ("Dirui Industrial", "Dirui", True),
    "URIT": ("URIT Medical", "URIT", True),
    "RAYTO": ("Rayto Life & Analytical Sciences", "Rayto", True),
    "GENERAL BIOLOGIC": ("General Biologicals", "GBC", True),
    "VIRCELL": ("Vircell", "Vircell", True),
    "VIRCLIA": ("Vircell", "Vircell", True),
    "ORGENTEC": ("ORGENTEC Diagnostika", "Sebia", True),
    "INOVA": ("Inova Diagnostics", "Werfen", True),
    "BINDING SITE": ("The Binding Site", "Thermo Fisher", True),
    "OXOID": ("Oxoid", "Thermo Fisher", True),
    "REMEL": ("Remel", "Thermo Fisher", True),
    "COPAN": ("Copan Diagnostics", "Copan", True),
    "BIOLOG": ("Biolog", "Biolog", True),
    "LIOFILCHEM": ("Liofilchem", "Liofilchem", True),
    "MAST": ("Mast Group", "Mast", True),
    "SSI DIAGNOSTICA": ("SSI Diagnostica", "SSI", True),
    "VIRCO": ("Virco", "Janssen", True),
    "SIEMENS DIAGNOSTICS": ("Siemens Healthineers", "Siemens Healthineers", True),
    "BIOTECON": ("BIOTECON Diagnostics", "BIOTECON", True),
    "R-BIOPHARM": ("R-Biopharm", "R-Biopharm", True),
    "RIDASCREEN": ("R-Biopharm", "R-Biopharm", True),
    "NOVA BIOMEDICAL": ("Nova Biomedical", "Nova Biomedical", True),
    "ARKRAY": ("ARKRAY", "ARKRAY", True),
    "LIFESCAN": ("LifeScan", "LifeScan", True),
    "ASCENSIA": ("Ascensia Diabetes Care", "PHC Holdings", True),
    "TRIDENT": ("Trident Diagnostics", "Trident", True),
    "BIOHIT": ("Biohit", "Biohit", True),
    "EPPENDORF": ("Eppendorf", "Eppendorf", True),
    "HAMILTON": ("Hamilton", "Hamilton", True),
    "TECAN": ("Tecan", "Tecan", True),
    # --- Turkish / regional IVD manufacturers and own-brand players ---
    "GEN ERA": ("Gen Era Diagnostik (Genera)", "Gen Era", True),
    "GENERA": ("Gen Era Diagnostik (Genera)", "Gen Era", True),
    "ANATOLIA": ("Anatolia Geneworks (Bosphore)", "Anatolia Geneworks", True),
    "GENEWORKS": ("Anatolia Geneworks (Bosphore)", "Anatolia Geneworks", True),
    "BIOEKSEN": ("Bioeksen R&D", "Bioeksen", True),
    "RTA LABORATU": ("RTA Laboratuvarlari", "RTA", True),
    "VITROSENS": ("Vitrosens Biotechnology", "Vitrosens", True),
    "DIAGEN": ("DIAGEN Biotechnology", "DIAGEN", True),
    "NANOSENS": ("Nanosens", "Nanosens", True),
    "ARTRON": ("Artron Laboratories", "Artron", True),
    "MONOBIND": ("Monobind", "Monobind", True),
    "ATLAS MEDICAL": ("Atlas Medical", "Atlas Medical", True),
    "ARCHEM": ("Archem Saglik", "Archem", True),
    "BIOSPEEDY": ("Bioeksen (Bio-Speedy)", "Bioeksen", True),
    "MIKROGEN": ("Mikrogen", "Mikrogen", True),
    # --- named players present in EKAP that are NOT IVD ---
    "MEDTRONIC": ("Medtronic", "Medtronic", False),
    "JOHNSON": ("Johnson & Johnson", "J&J", False),
    "BOSTON SCIENTIFIC": ("Boston Scientific", "Boston Scientific", False),
    "STRYKER": ("Stryker", "Stryker", False),
    "ZIMMER": ("Zimmer Biomet", "Zimmer Biomet", False),
    "SMITH NEPHEW": ("Smith+Nephew", "Smith+Nephew", False),
    "BRAUN": ("B. Braun", "B. Braun", False),
    "FRESENIUS": ("Fresenius", "Fresenius", False),
    "BAXTER": ("Baxter", "Baxter", False),
    "PHILIPS": ("Philips", "Philips", False),
    "DRAGER": ("Draeger", "Draeger", False),
    "GENERAL ELECTRIC": ("GE HealthCare", "GE HealthCare", False),
    "MERIL": ("Meril Life Sciences", "Meril", False),
    "IMICRYL": ("Imicryl (dental)", "Imicryl", False),
}

# Names that merely *look* like an OEM brand. Turkish SMEs frequently register a
# trade name colliding with a global brand, so these are never auto-assigned; they
# are routed to research with the collision called out.
FALSE_FRIENDS = {
    "BIORAD": "Bio-Rad Laboratories",
    "BIO-RAD": "Bio-Rad Laboratories",
    "BIOGEN": "Biogen (pharma)",
    "DIMENSION": "Siemens Dimension analyser line",
    "BIOMED": "generic",
    "MEDISON": "Samsung Medison",
    "ALKIM": "generic",
}

# Tokens that are also ordinary Turkish trade-name words. They only count as an OEM
# hit when the name also carries diagnostics/lab context, otherwise "ANATOLIA MEDICAL
# CAR RENTAL" would be read as Anatolia Geneworks.
RISKY = {
    "ANATOLIA", "GENERA", "GEN ERA", "MAST", "INOVA", "TRIDENT", "BIOLOG", "DIAGEN",
    "ARCHEM", "URIT", "ERBA", "SIEMENS", "BRAUN", "SAKURA", "DAKO", "COPAN", "HAMILTON",
    "ATLAS MEDICAL", "MERCK", "LEICA", "REMEL", "VIRCO", "NANOSENS", "ARTRON", "RAYTO",
}
CONTEXT = re.compile(
    r"DIAGNOST|DIYAGNOST|TANI |BIYOTEK|BIOTECH|BIOTEKNOLOJ|LABORATU|LABORATORY|"
    r"REAKTIF|REAGENT|IN VITRO|MOLEKUL|MOLECULAR|GENETIK|GENETIC|PATOLOJ|PATHOLOG|"
    r"MIKROBIYOLOJ|MICROBIOLOG|HEALTHCARE|HEALTHINEERS|MEDICAL LABORATOR"
)

TOKEN_RE = {}


def _pat(tok):
    if tok not in TOKEN_RE:
        TOKEN_RE[tok] = re.compile(r"(?<![A-Z0-9])" + re.escape(tok) + r"(?![A-Z0-9])")
    return TOKEN_RE[tok]


def detect(name_tr, name_en):
    """Return (player, group, is_ivd, basis) or None."""
    hay = fold(name_tr) + " || " + fold(name_en)
    has_ctx = bool(CONTEXT.search(hay))

    for tok, why in FALSE_FRIENDS.items():
        if _pat(tok).search(hay):
            return None, None, None, f"name collides with {why} - verify"

    hits = []
    for tok, (player, group, is_ivd) in IVD_OEM.items():
        if tok in RISKY and not has_ctx:
            continue
        if _pat(tok).search(hay):
            hits.append((len(tok), tok, player, group, is_ivd))
    if not hits:
        return None
    hits.sort(reverse=True)
    _, tok, player, group, is_ivd = hits[0]
    return player, group, is_ivd, f"OEM name in supplier legal name ('{tok}')"


if __name__ == "__main__":
    prof = json.loads((BASE / "mapping" / "tr_supplier_profile.json").read_text(encoding="utf-8"))
    hit = flagged = 0
    for p in prof:
        d = detect(p["supplier_name"], p["supplier_name_en"])
        if d and d[0]:
            hit += 1
            if hit <= 40:
                print("%-38s | %-30s | %s" % (d[0][:38], d[3][:30], p["supplier_name_en"][:50]))
        elif d:
            flagged += 1
    print("\nname-rule assigned:", hit, "| false-friend flagged:", flagged, "| total:", len(prof))
