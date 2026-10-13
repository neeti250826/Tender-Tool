"""Build a per-supplier profile for the Turkey EKAP supplier list.

Aggregates row counts, award value, IVD-relevance signals and representative item
descriptions for each unique supplier, so brand assignment can be prioritised.
"""
import csv, json, re, collections, sys
from pathlib import Path

BASE = Path(r"<WORKSPACE>")
SEG_CSV = BASE / "scratch_ekap_seg.csv"
OUT = BASE / "mapping" / "tr_supplier_profile.json"

# Item-description vocabulary that indicates in-vitro diagnostics work.
IVD_TERMS = [
    "test", "kit", "reagent", "reaktif", "assay", "elisa", "pcr", "rt-pcr", "dna", "rna",
    "antibody", "antikor", "antigen", "serum", "plasma", "biochemistry", "biyokimya",
    "hemogram", "hematology", "hematoloji", "immunoassay", "hormone", "hormon",
    "hba1c", "glucose strip", "glukoz", "blood gas", "kan gazi", "coagulation",
    "koagulasyon", "urine", "idrar", "culture medium", "besiyeri", "microbiology",
    "mikrobiyoloji", "pathology", "patoloji", "histopathology", "immunohistochemistry",
    "immunohistokimya", "stain", "boya", "cassette", "kaset", "slide", "lam",
    "blood collection tube", "kan alma tup", "vacutainer", "cuvette", "kuvet",
    "calibrator", "kalibrator", "control serum", "kontrol serum", "analyzer", "analizor",
    "autoanalyzer", "otoanalizor", "sequencing", "dizileme", "extraction", "ekstraksiyon",
    "rapid test", "hizli test", "cartridge", "kartus", "panel", "marker", "esr",
    "sedimentation", "sedimantasyon", "crp", "troponin", "d-dimer", "vitamin d",
    "tsh", "psa", "hbsag", "anti-hcv", "hiv", "syphilis", "brucella", "elisa plate",
    "swab", "eküvyon", "transport medium", "tissue processing", "doku takip",
    "paraffin", "parafin", "microscope slide", "petri",
]

# Descriptions that clearly belong to other device categories (used to damp the score).
NON_IVD_TERMS = [
    "dental", "implant", "prosthes", "protez", "orthop", "ortoped", "catheter", "kateter",
    "stent", "syringe", "enjektor", "suture", "sutur", "gauze", "gazli bez", "bandage",
    "bandaj", "glove", "eldiven", "mask", "maske", "wheelchair", "tekerlekli",
    "ambulance", "ambulans", "furniture", "mobilya", "textile", "tekstil", "gown",
    "food", "gida", "cleaning", "temizlik", "stationery", "kirtasiye", "fuel", "yakit",
    "ultrasound", "ultrason", "x-ray", "rontgen", "tomography", "tomografi", "mri",
    "ventilator", "defibrillator", "pacemaker", "kalp pili", "endoscop", "endoskop",
    "laser", "lazer", "surgical", "cerrahi", "scalpel", "bistur",
]

MAPPED_SEGMENTS_BAD = {"#N/A", "0", "#VALUE!", "", None}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def main():
    rows = list(csv.DictReader(SEG_CSV.open(encoding="utf-8")))
    prof = collections.defaultdict(lambda: {
        "supplier_name": "", "supplier_name_en": "", "rows": 0, "value": 0.0,
        "seg_rows": 0, "segments": collections.Counter(),
        "ivd_hits": 0, "non_ivd_hits": 0, "items": collections.Counter(),
        "ivd_segments": collections.Counter(),
    })

    for r in rows:
        key = norm(r["supplier_name"])
        if not key:
            continue
        p = prof[key]
        p["supplier_name"] = p["supplier_name"] or r["supplier_name"]
        p["supplier_name_en"] = p["supplier_name_en"] or r["supplier_name_en"]
        p["rows"] += 1
        try:
            p["value"] += float(r["Approximation cost"] or 0)
        except ValueError:
            pass

        seg = r["Segment"]
        if seg not in MAPPED_SEGMENTS_BAD:
            p["seg_rows"] += 1
            p["segments"][seg] += 1

        isg = r["source_ivd_segment"]
        if isg and isg != "Cross-cutting":
            p["ivd_segments"][isg] += 1

        desc = (r["item_description_en"] or "").lower()
        if desc:
            p["items"][desc[:90]] += 1
            if any(t in desc for t in IVD_TERMS):
                p["ivd_hits"] += 1
            if any(t in desc for t in NON_IVD_TERMS):
                p["non_ivd_hits"] += 1

    out = []
    for key, p in prof.items():
        n = max(p["rows"], 1)
        ivd_ratio = p["ivd_hits"] / n
        non_ratio = p["non_ivd_hits"] / n
        seg_ratio = p["seg_rows"] / n
        # IVD relevance: segment mapping is the strongest signal, then description terms.
        score = (2.5 * seg_ratio) + ivd_ratio + (0.8 * (len(p["ivd_segments"]) > 0)) - (0.6 * non_ratio)
        out.append({
            "supplier_name": p["supplier_name"],
            "supplier_name_en": p["supplier_name_en"],
            "rows": p["rows"],
            "value": round(p["value"], 2),
            "seg_rows": p["seg_rows"],
            "ivd_ratio": round(ivd_ratio, 3),
            "non_ivd_ratio": round(non_ratio, 3),
            "ivd_score": round(score, 3),
            "segments": dict(p["segments"].most_common(5)),
            "ivd_segments": dict(p["ivd_segments"].most_common(5)),
            "top_items": [i for i, _ in p["items"].most_common(8)],
        })

    out.sort(key=lambda x: -x["rows"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("suppliers:", len(out))
    print("ivd_score>=0.5:", sum(1 for x in out if x["ivd_score"] >= 0.5))
    print("ivd_score>=0.25:", sum(1 for x in out if x["ivd_score"] >= 0.25))
    print("seg_rows>0:", sum(1 for x in out if x["seg_rows"] > 0))


if __name__ == "__main__":
    main()
