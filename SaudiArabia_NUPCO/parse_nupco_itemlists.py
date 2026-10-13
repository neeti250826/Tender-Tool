"""
Parse NUPCO tender item lists (ksa/items/*.pdf|xlsx) -> ksa/nupco_itemlist_qty.csv
One row per (tender, NUPCO code): description, UOM, requested (initial) quantity.
"""
import csv, glob, os, re
import pdfplumber, openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = re.compile(r"\b(\d{13})\b")
MAP = [("code", r"nupco ?code|srm code"), ("item_no", r"^item no"), ("uom", r"^(srm )?uo?m$|^oum$|^unit$"),
       ("qty", r"qty|quantity"), ("description", r"description|specification|item name")]


def canon(h):
    h = re.sub(r"\s+", " ", (h or "").replace("\n", " ")).strip().lower()
    for c, rx in MAP:
        if re.search(rx, h):
            return c
    return None


def num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def rows_from_table(tb, state):
    out = []
    for raw in tb:
        cells = [c for c in raw if c is not None]
        hdr = [canon(c) for c in cells]
        if "code" in hdr and "qty" in hdr:
            state["hdr"] = hdr
            continue
        h = state.get("hdr")
        if not h:
            continue
        if len(cells) != len(h):
            # fall back: locate code + last numeric cell
            code = next((CODE.search(c or "").group(1) for c in cells if CODE.search(c or "")), None)
            nums = [num(c) for c in cells if num(c) is not None and not CODE.search(c or "")]
            if code and nums:
                out.append({"code": code, "qty": nums[-1], "uom": "", "description": "", "how": "fallback"})
            continue
        rec = dict(zip(h, cells))
        m = CODE.search((rec.get("code") or "").replace(" ", ""))
        if not m:
            continue
        out.append({"code": m.group(1), "qty": num(rec.get("qty")), "uom": (rec.get("uom") or "").strip(),
                    "description": re.sub(r"\s+", " ", rec.get("description") or "").strip(), "how": "table"})
    return out


TAIL = re.compile(r"\s*(\b(?:itemized|group\s*\d*|\d+)\b\s+)?(each|ea|kit|set|pair|pc|pcs|box|piece|items \(pieces\)|items|pack|roll|bottle|tube|unit|pk|paa)\s+([\d,]+)\s*$", re.I)


def parse_text_lines(pdf):
    """Layouts without ruled tables. The code row reads '<sn> <code> <desc part> <group> <UOM> <qty>', and long
    descriptions wrap onto text lines above and below the code row. Each non-code line is attached to the
    nearest code row by vertical distance, then the pieces are joined top-to-bottom."""
    out = []
    for page in pdf.pages:
        lines = page.extract_text_lines()
        codes = [(i, ln) for i, ln in enumerate(lines) if CODE.search(ln["text"])]
        if not codes:
            continue
        parts = {i: [] for i, _ in codes}
        first_top = codes[0][1]["top"] - 40
        last_bottom = codes[-1][1]["bottom"] + 40
        for j, ln in enumerate(lines):
            if CODE.search(ln["text"]) or ln["top"] < first_top or ln["bottom"] > last_bottom:
                continue
            if re.search(r"tender (name|number|no)|^sn\b|nupco code|initial quantity|page \d", ln["text"], re.I):
                continue
            mid = (ln["top"] + ln["bottom"]) / 2
            i = min(codes, key=lambda c: abs((c[1]["top"] + c[1]["bottom"]) / 2 - mid))[0]
            parts[i].append((ln["top"], ln["text"]))
        for i, ln in codes:
            m = re.search(r"(\d{13})\s*(.*)$", ln["text"])
            tail = m.group(2)
            q = re.findall(r"(?<![\w.])(\d[\d,]*)(?![\w.])", tail)
            t = TAIL.search(tail)
            uom = t.group(2) if t else ""
            core = tail[:t.start()] if t else tail
            pieces = sorted(parts[i] + [(ln["top"], core)])
            desc = re.sub(r"\s+", " ", " ".join(p for _, p in pieces)).strip()
            desc = re.sub(r"(EA|PC|PCS|SET|EACH|KIT|PAA|BOX)\s+(ITEMIZED|GROUP\s*\d+)\s+[\d,]+", " ", desc, flags=re.I)
            desc = re.sub(r"\s+", " ", desc).strip(' "')
            out.append({"code": m.group(1), "qty": num(t.group(3)) if t else (num(q[-1]) if q else None), "uom": uom,
                        "description": desc[:300], "how": "text"})
    return out


def parse(path):
    tender = os.path.basename(path).rsplit(".", 1)[0].replace("_", "/")
    recs = []
    if path.endswith(".xlsx"):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb:
            st = {}
            recs += rows_from_table([[None if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)], st)
    else:
        with pdfplumber.open(path) as pdf:
            st = {}
            for page in pdf.pages:
                for tb in page.extract_tables():
                    recs += rows_from_table(tb, st)
            if not recs:
                recs = parse_text_lines(pdf)
    for r in recs:
        r["tender_id"] = tender
    return recs


if __name__ == "__main__":
    allr = []
    for f in sorted(glob.glob(os.path.join(HERE, "items", "*.*"))):
        r = parse(f)
        hows = {h: sum(1 for x in r if x["how"] == h) for h in ("table", "fallback", "text")}
        noqty = sum(1 for x in r if x["qty"] is None)
        print(f"{os.path.basename(f):<18} rows={len(r):<6} {hows} no_qty={noqty}", flush=True)
        allr += r
    # one row per tender+code. Table rows win over fallback/text rows (the fallback re-reads wrapped
    # rows and would double-count). Distinct table lines for the same code (e.g. two groups) are summed;
    # identical (qty, description) repeats are page-break duplicates and counted once.
    by = {}
    for r in allr:
        by.setdefault((r["tender_id"], r["code"]), []).append(r)
    agg = {}
    for (t, code), rs in by.items():
        tab = [r for r in rs if r["how"] == "table"]
        use = tab or rs
        seen, qty = set(), None
        for r in use:
            key = (r["qty"], r["description"])
            if key in seen or r["qty"] is None:
                continue
            seen.add(key)
            qty = (qty or 0) + r["qty"] if tab else max(qty or 0, r["qty"])
        agg[(t, code)] = {"tender_id": t, "nupco_code": code, "qty_requested": qty,
                          "uom": next((r["uom"] for r in use if r["uom"]), ""),
                          "il_description": next((r["description"] for r in use if r["description"]), ""),
                          "lines": len(seen), "how": use[0]["how"]}
    with open(os.path.join(HERE, "nupco_itemlist_qty.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(next(iter(agg.values())).keys()))
        w.writeheader()
        w.writerows(agg.values())
    print("TOTAL item-code rows", len(agg))
