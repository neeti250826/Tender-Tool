"""
Parse NUPCO final-result PDFs (turmeca/ksa/final/*.pdf) into one award table.

Layouts differ per tender, so every table header is normalised to a canonical
schema via HEADER_MAP; merged-cell None columns are dropped before aligning
data rows to the header. Rows that cannot be aligned go to the anomaly log.

Output: ksa/nupco_awards_raw.csv, ksa/nupco_parse_log.csv
"""
import csv, glob, os, re, sys
import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = re.compile(r"^\d{13}$")

HEADER_MAP = [  # (canonical, regex on normalised header text) — first match wins
    ("sn", r"^(srm )?s\.?n$|^sn$"),
    ("nupco_code", r"nupco.*code|^srm code$"),
    ("item_no", r"^item no"),
    ("description", r"item (name|description|specification)|generic item description|^description$"),
    ("group", r"group"),
    ("uom", r"^uom$"),
    ("qty", r"^qty$"),
    ("vendor_no", r"supplier code|vendor (no|number)|vemdor number|^vendor$"),
    ("vendor_name", r"(supplier|vendor) name|^supplier$"),
    ("model", r"^model|catalog|trade description|^pn$|model pn"),
    ("manufacturer", r"manufactur"),
    ("country", r"country"),
    ("remarks", r"remark|comment|technical reason|column1"),
    ("item_folder", r"item folder"),
]


def norm_h(s):
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip().lower()


def canon(h):
    h = norm_h(h)
    for c, rx in HEADER_MAP:
        if re.search(rx, h):
            return c
    return "x_" + h[:20] if h else None


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


KNOWN_HDR = ["SN", "NUPCO Code", "QTY", "Item Description", "UOM", "GROUP", "Vendor No", "Vendor Name", "Manufacturer",
             "Country", "Catalog No", "REMARKS"]


def split_collapsed_header(cell, width):
    """Some PDFs put the whole header in one cell ('SN NUPCO Code QTY Item Description ...')."""
    txt = norm_h(cell)
    names = [h for h in KNOWN_HDR if h.lower() in txt]
    names.sort(key=lambda h: txt.index(h.lower()))
    return names if len(names) == width else None


def is_header(cells):
    joined = norm_h(" ".join(c or "" for c in cells if c))
    return (("nupco" in joined or "srm code" in joined) and ("vendor" in joined or "supplier" in joined)
            and not re.search(r"\d{13}", joined))


def build_header(raw):
    """-> list of (canonical, start_idx, end_idx) spans over the raw row width."""
    nonnull = [(i, c) for i, c in enumerate(raw) if c not in (None, "") and norm_h(c)]
    if len(nonnull) == 1 and len(raw) > 4:
        names = split_collapsed_header(nonnull[0][1], len(raw))
        if names:
            return [(canon(n), i, i + 1) for i, n in enumerate(names)]
    spans = []
    for k, (i, c) in enumerate(nonnull):
        j = nonnull[k + 1][0] if k + 1 < len(nonnull) else len(raw)
        spans.append((canon(c), i, j))
    return spans


def pick(raw, i, j):
    for v in raw[i:j]:
        if v not in (None, ""):
            return v
    return ""


def parse_pdf(path):
    tender = os.path.basename(path)[:-4].replace("_", "/")
    rows, log = [], {"tender": tender, "pages": 0, "rows": 0, "unaligned": 0, "no_code": 0, "layout": ""}
    spans, width = None, None
    with pdfplumber.open(path) as pdf:
        log["pages"] = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, 1):
            for tb in page.extract_tables():
                for raw in tb:
                    if is_header(raw) or (raw and raw[0] and "nupco" in norm_h(raw[0]) and all(c is None for c in raw[1:])):
                        spans, width = build_header(raw), len(raw)
                        log["layout"] = "|".join(s[0] or "" for s in spans)
                        continue
                    if not spans:
                        continue
                    if len(raw) == width:
                        rec = {h: clean(pick(raw, i, j)) for h, i, j in spans if h}
                    else:
                        cells = [c for c in raw if c not in (None,)]
                        hs = [s[0] for s in spans]
                        if len(cells) != len(hs):
                            log["unaligned"] += 1
                            continue
                        rec = {h: clean(v) for h, v in zip(hs, cells) if h}
                    code = re.sub(r"\s", "", rec.get("nupco_code", ""))
                    if not CODE.match(code):
                        log["no_code"] += 1
                        continue
                    rec["nupco_code"] = code
                    rec["tender_id"] = tender
                    rec["page"] = pno
                    rows.append(rec)
    log["rows"] = len(rows)
    return rows, log


FIELDS = ["tender_id", "page", "sn", "nupco_code", "item_no", "description", "group", "uom", "qty", "vendor_no", "vendor_name",
          "model", "manufacturer", "country", "remarks", "item_folder"]

if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(HERE, "final", "*.pdf")))
    if len(sys.argv) > 1:
        files = [f for f in files if any(a in f for a in sys.argv[1:])]
    allrows, logs = [], []
    for f in files:
        r, l = parse_pdf(f)
        allrows += r
        logs.append(l)
        print(f"{l['tender']:<12} pages={l['pages']:<4} rows={l['rows']:<6} unaligned={l['unaligned']:<5} no_code={l['no_code']:<5} {l['layout'][:110]}", flush=True)
    out = "nupco_awards_raw.csv" if len(sys.argv) == 1 else "nupco_awards_raw_partial.csv"
    with open(os.path.join(HERE, out), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(allrows)
    with open(os.path.join(HERE, "nupco_parse_log.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(logs[0].keys()))
        w.writeheader()
        w.writerows(logs)
    print("TOTAL rows", len(allrows))
