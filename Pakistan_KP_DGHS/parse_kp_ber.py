"""
Khyber Pakhtunkhwa DGHS bid evaluation reports (BER) for "Selection and Rate Contracting of Medical Equipment,
Medical Furniture, Instruments and Other Hospital Supplies" (FY 2024-25, 2025-26, 2026-27) -> one row per bid.

Table columns: S.No | Name of Firm | Name of Item (with Model:/Make:) | Technical score | Quoted Price |
Lowest Price | Total Financial Marks | Financial Marks | Total Marks. Blank rows separate items.
Winner of an item block = highest Total Marks (ties -> lowest quoted price).
Output: pakistan/kp_ber_bids.csv
"""
import csv, glob, os, re
import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    "Bid Evaluation Report 2024-25.pdf": "2024-25",
    "BID EVALUATION REPORT FOR SELECTION AND RATE CONTRACTING OF MEDICAL EQUIPMENT, MEDICAL FUR": "2025-26",
    "BID EVALUATION REPORT FOR SELECTION AND RATE CONTRACTING OF MEDICAL EQUIPMENT.pdf": "2026-27",
    "BID EVALUATION REPORT(BER)  for the Purchase of Medical Equipment": "2025-26 (PHC reforms)",
}


def num(s):
    s = re.sub(r"[^\d.]", "", (s or "").replace(" ", ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def split_item(t):
    t = re.sub(r"\s+", " ", (t or "").replace("\n", " ")).strip()
    model = re.search(r"model\s*[:\-]\s*(.+?)(?=\s*(make|brand|origin|country|manufacturer)|$)", t, re.I)
    make = re.search(r"(?:make|brand|manufacturer)\s*[:\-]\s*(.+?)(?=\s*(model|origin|country)|$)", t, re.I)
    origin = re.search(r"(?:origin|country of origin|country)\s*[:\-]\s*(.+?)(?=\s*(model|make|brand)\s*[:\-]|$)", t, re.I)
    item = re.split(r"\s*(model|make|brand|origin)\s*[:\-]", t, flags=re.I)[0].strip(" ,;")
    return item, (model.group(1).strip(" ,;") if model else ""), (make.group(1).strip(" ,;") if make else ""), (origin.group(1).strip(" ,;") if origin else "")


def main():
    rows = []
    for pat, fy in FILES.items():
        f = next((p for p in glob.glob(os.path.join(HERE, "kp", "*.pdf")) if os.path.basename(p).startswith(pat.replace(".pdf", ""))), None)
        if not f:
            print("missing", pat)
            continue
        block, section = 0, ""
        with pdfplumber.open(f) as pdf:
            for pno, page in enumerate(pdf.pages, 1):
                for tb in page.extract_tables():
                    for raw in tb:
                        c = [(x or "").strip() for x in raw]
                        if len(c) < 9:
                            continue
                        if c[0] and not c[0].isdigit() and not any(c[1:]):
                            section = c[0][:120]
                            continue
                        if not any(c):
                            block += 1
                            continue
                        wide = len(c) > 12      # FY 2026-27 layout: ~20 technical-criteria columns before the prices
                        if not c[1] or not c[2]:
                            continue            # wrapped-text fragment / orphan score row
                        if wide and c[0].isdigit():
                            block += 1          # wide layout numbers items; narrow layouts number bidders and use blank rows
                        item, model, make, origin = split_item(c[2])
                        qp, lp, tm = (c[-4], c[-3], c[-1]) if wide else (c[4], c[5], c[8])
                        rows.append({"fy": fy, "source": os.path.basename(f), "page": pno, "section": section, "block": f"{fy}-{block}",
                                     "sn": c[0], "firm": re.sub(r"\s+", " ", c[1]), "item_raw": re.sub(r"\s+", " ", c[2]), "item": item,
                                     "model": model, "make": make, "origin": origin, "tech_score": num(c[-5] if wide else c[3]), "quoted_pkr": num(qp),
                                     "lowest_pkr": num(lp), "total_marks": num(tm)})
        print(fy, os.path.basename(f)[:60], "bids so far", len(rows))
    # winners per block
    by = {}
    for r in rows:
        by.setdefault(r["block"], []).append(r)
    for b, rs in by.items():
        best = max(rs, key=lambda r: ((r["total_marks"] or 0), -(r["quoted_pkr"] or 9e18)))
        for r in rs:
            r["bids_on_item"] = len(rs)
            r["winner"] = "Yes" if r is best else ""
    with open(os.path.join(HERE, "kp_ber_bids.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("bids", len(rows), "items", len(by), "winners", sum(1 for r in rows if r["winner"]))


if __name__ == "__main__":
    main()
