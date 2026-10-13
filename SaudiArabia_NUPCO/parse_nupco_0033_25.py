"""
NPT0033/25 (ENT) final result: the description column is printed as overlapping text layers, so
pdfplumber tables are unusable. Each award line still reads cleanly as
    <SN> <NUPCO code> <garbled description> <qty/group> <uom> <vendor no 40xxxx> <vendor name> -Orig- <manufacturer> <country> <catalog>
Description is left blank here and taken from the item list (join on NUPCO code) downstream.
Output: ksa/nupco_awards_0033_25.csv (same columns as nupco_awards_raw.csv)
"""
import csv, os, re
import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))
COUNTRIES = ["United States of America", "United States", "United Kingdom", "Saudi Arabia", "South Korea", "Korea", "USA", "UK",
             "Germany", "China", "Switzerland", "France", "Italy", "Japan", "Ireland", "Belgium", "Netherlands", "Austria", "Spain",
             "Sweden", "Denmark", "Israel", "India", "Turkey", "Taiwan", "Australia", "Canada", "Mexico", "Malaysia", "Pakistan",
             "Czech Republic", "Poland", "Finland", "Brazil", "Singapore", "Hungary", "Portugal", "Norway", "Thailand", "Egypt",
             "Jordan", "Indonesia", "Costa Rica", "Puerto Rico", "Dominican Republic", "Vietnam", "UAE", "United Arab Emirates"]
CTRY = "|".join(re.escape(c) for c in sorted(COUNTRIES, key=len, reverse=True))
LINE = re.compile(r"^(?:(\d+)\s+)?(\d{13})?\s*(.*?)\s(40\d{4})\s+(.+?)\s*-Orig-\s*(.+?)\s+(" + CTRY + r")\s*(.*)$", re.I)


def main():
    rows, last_code, last_sn = [], None, None
    with pdfplumber.open(os.path.join(HERE, "final", "NPT0033_25.pdf")) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            for line in (page.extract_text() or "").split("\n"):
                m = LINE.match(line.strip())
                if not m:
                    continue
                sn, code, mid, vno, vname, mfr, country, cat = m.groups()
                code = code or last_code
                if not code:
                    continue
                last_code, last_sn = code, sn or last_sn
                rows.append({"tender_id": "NPT0033/25", "page": pno, "sn": sn or last_sn, "nupco_code": code, "description": "",
                             "vendor_no": vno, "vendor_name": vname.strip(), "manufacturer": mfr.strip(), "country": country,
                             "model": cat.strip(), "remarks": "description garbled in PDF; from item list"})
    with open(os.path.join(HERE, "nupco_awards_0033_25.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("rows", len(rows), "codes", len({r["nupco_code"] for r in rows}))


if __name__ == "__main__":
    main()
