"""
KP Govt. MCC (Medicines Coordination Cell) bid evaluation reports -> one row per bid, winners flagged.
These cover drugs AND medical devices / surgical disposables (sutures, ET tubes, cannulae, catheters, mesh...).

Row layout (cells shift in the text part, so numbers are read from the right):
  firm | MCC ref no | generic name / strength / size (spread over several cells) | trade name |
  tech score | MRP | trade price | RATE OFFERED PER UNIT (PKR) | lowest quoted | price-adj score | max | FINAL TOTAL | ...
=> numeric cells after the text: rate = [-5], lowest = [-4], final = [-1].
Item = MCC ref no within a report; description = union of text across that item's bid rows.
Winner = highest final total (ties -> lowest rate). FY 2025-26 approved BER is a CamScanner scan, so the
text "Draft Comparative Statement FY 2025-26" is used for that year.
Output: pakistan/kp_mcc_bids.csv, pakistan/kp_mcc_items.csv
"""
import csv, glob, os, re
from collections import defaultdict
import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [("Approved Bid Evaluation Report (Technical+Financial) Govt.MCC FY 2024-25", "2024-25"),
         ("GOVT. MCC DRAFT COMPARATIVE STATEMENT FOR FY 2025-26", "2025-26"),
         ("Approved Bid Evaluation Report (Technical+Financial) Govt. MCC FY 2026-27", "2026-27")]
NUM = re.compile(r"^-?[\d,]*\.?\d+$")


def num(s):
    s = (s or "").replace(",", "").replace(" ", "").strip()
    return float(s) if NUM.match(s) else None


def main():
    bids = []
    for prefix, fy in FILES:
        f = next((p for p in glob.glob(os.path.join(HERE, "kp", "*.pdf")) if os.path.basename(p).startswith(prefix)), None)
        if not f:
            print("missing", prefix)
            continue
        n0 = len(bids)
        with pdfplumber.open(f) as pdf:
            for pno, page in enumerate(pdf.pages, 1):
                for tb in page.extract_tables():
                    for raw in tb:
                        c = [re.sub(r"\s+", " ", (x or "")).strip() for x in raw]
                        if len(c) < 12 or not c[0]:
                            continue
                        ref = c[1] if re.fullmatch(r"\d{1,5}", c[1] or "") else None
                        if not ref:
                            continue
                        idx = [i for i in range(3, len(c)) if num(c[i]) is not None]
                        if len(idx) < 6:
                            continue
                        vals = [num(c[i]) for i in idx]
                        text_end = idx[-8] if len(idx) >= 8 else idx[0]
                        text = " ".join(x for x in c[2:text_end] if x and num(x) is None)
                        bids.append({"fy": fy, "source": os.path.basename(f), "page": pno, "firm": c[0], "mcc_ref": ref,
                                     "item_key": f"{fy}|{ref}", "text": text, "rate_pkr": vals[-5], "lowest_pkr": vals[-4],
                                     "final_score": vals[-1], "detail": c[-1][:150]})
        print(fy, os.path.basename(f)[:70], "bids", len(bids) - n0)

    # FY 2023-24 final BER (KP DGHS site): MCC# | item name | size | firm / brand | tech | RATE | lowest | fin | TOTAL | remarks;
    # follow-on bidders leave MCC# and the name blank.
    f = os.path.join(HERE, "kp_dghs", "final BER of Government MCC 2023-24.pdf")
    if os.path.exists(f):
        n0, ref, name = len(bids), None, ""
        with pdfplumber.open(f) as pdf:
            for pno, page in enumerate(pdf.pages, 1):
                for tb in page.extract_tables():
                    for raw in tb:
                        c = [re.sub(r"\s+", " ", (x or "")).strip() for x in raw]
                        if len(c) < 9 or "score" in " ".join(c).lower() and not num(c[5] if len(c) > 5 else ""):
                            continue
                        if re.fullmatch(r"\d{1,5}", c[0]):
                            ref, name = c[0], " ".join(x for x in c[1:3] if x)
                        if not ref or num(c[5]) is None:
                            continue
                        firm = c[3].split("/")[0].strip()
                        bids.append({"fy": "2023-24", "source": os.path.basename(f), "page": pno, "firm": firm, "mcc_ref": ref,
                                     "item_key": f"2023-24|{ref}", "text": f"{name} {c[3]}", "rate_pkr": num(c[5]), "lowest_pkr": num(c[6]),
                                     "final_score": num(c[8]), "detail": c[3][:150]})
        print("2023-24", os.path.basename(f)[:70], "bids", len(bids) - n0)

    items = defaultdict(list)
    for b in bids:
        items[b["item_key"]].append(b)
    out_items = []
    for k, rs in items.items():
        win = max(rs, key=lambda r: ((r["final_score"] or 0), -(r["rate_pkr"] or 9e18)))
        for r in rs:
            r["winner"] = "Yes" if r is win else ""
            r["bids_on_item"] = len(rs)
        words, seen = [], set()
        for r in sorted(rs, key=lambda r: -len(r["text"])):
            for w in r["text"].split():
                if w.lower() not in seen:
                    seen.add(w.lower())
                    words.append(w)
        out_items.append({"fy": rs[0]["fy"], "mcc_ref": rs[0]["mcc_ref"], "description": " ".join(words)[:300],
                          "winner_firm": win["firm"], "winner_rate_pkr": win["rate_pkr"], "lowest_pkr": min((r["rate_pkr"] for r in rs if r["rate_pkr"]), default=None),
                          "bids": len(rs), "source": rs[0]["source"], "page": rs[0]["page"]})
    # NOTE: MCC formulary numbers are NOT stable across years (e.g. 1272 = tracheostomy tube in FY24-25, X-ray film later),
    # so "description_enriched" is informational only and must not be used for mapping.
    best = {}
    for it in out_items:
        if len(it["description"]) > len(best.get(it["mcc_ref"], "")):
            best[it["mcc_ref"]] = it["description"]
    for it in out_items:
        other = best.get(it["mcc_ref"], "")
        it["description_enriched"] = it["description"] if other == it["description"] else f"{it['description']} [same MCC# other year: {other}]"
    with open(os.path.join(HERE, "kp_mcc_bids.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(bids[0].keys()))
        w.writeheader()
        w.writerows(bids)
    with open(os.path.join(HERE, "kp_mcc_items.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_items[0].keys()))
        w.writeheader()
        w.writerows(out_items)
    print("bids", len(bids), "items", len(out_items))


if __name__ == "__main__":
    main()
