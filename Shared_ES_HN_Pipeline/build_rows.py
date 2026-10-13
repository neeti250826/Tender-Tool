"""Assemble capture-template rows from every source into eshn_rows.pkl (awarded + open)."""
import glob
import json
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from buyers import in_scope, segment  # noqa: E402
from tagger import NAME, norm, tag  # noqa: E402

TEMPLATE = ["Country", "Source portal", "Buying institution / hospital", "Tender / procedure no.", "Procedure type",
            "Tender title / description", "Indicator code", "Segment name", "Product / test", "Brand / analyser",
            "Awarded supplier (distributor)", "Quantity", "Unit", "Unit price", "Total awarded", "Currency",
            "Contract type (comodato, por prueba, según demanda…)", "Contract duration & extensions",
            "Publication date", "Award date", "Status", "Funding (national / World Bank / IDB / Global Fund / PAHO)",
            "Source link", "Comments"]
EXTRA = ["Tag confidence", "All matched codes", "Tagged from", "Buyer segment", "Award year", "Multi-product line", "UNSPSC"]

BRANDS = [
    ("Roche", r"\broche\b|cobas|elecsys|accu-?chek|coaguchek"), ("Abbott", r"abbott|architect|alinity|i-?stat|determine\b|panbio|bioline|afinion|freestyle"),
    ("Siemens", r"siemens|atellica|dimension|advia|clinitek|multistix|rapidpoint|epoc"), ("Beckman Coulter", r"beckman|dxh\b|\bau ?\d{3,4}\b|unicel"),
    ("Sysmex", r"sysmex|\bxn-|\bxs-|\bkx-?21|cellpack|stromatolyser|sulfolyser"), ("Mindray", r"mindray|\bbs-?\d{3}\b|\bbc-?\d{4}"),
    ("Wiener lab", r"wiener"), ("HUMAN", r"\bhuman\b(?! ?(immuno|papilom|inmunodef))|humastar|humacount"), ("Spinreact", r"spinreact"),
    ("BioSystems", r"biosystems"), ("Linear", r"\blinear\b"), ("Randox", r"randox"), ("Bio-Rad", r"bio-?rad|diamed|\bd-?10\b"),
    ("Grifols", r"grifols|dg gel|erytra|wadiana"), ("Ortho / QuidelOrtho", r"\bortho\b|vitros|biovue"), ("bioMérieux", r"biomerieux|vitek|bact/?alert|\bapi ?20|mini ?vidas|\bvidas\b"),
    ("BD", r"\bbd\b|becton|bactec|phoenix|facs"), ("Cepheid", r"cepheid|xpert|genexpert"), ("Werfen / IL", r"werfen|gem premier|\bacl\b|hemosil"),
    ("Radiometer", r"radiometer|\babl ?\d"), ("Stago", r"stago"), ("Snibe", r"snibe|maglumi"), ("DiaSorin", r"diasorin|liaison"),
    ("SD Biosensor", r"sd biosensor|standard q|\bsd bioline"), ("Prodigy", r"prodigy"), ("HiMedia", r"himedia"), ("Oxoid", r"oxoid"),
    ("Merck", r"\bmerck\b"), ("Leica", r"\bleica\b"), ("Dako / Agilent", r"\bdako\b"), ("Ventana", r"ventana"), ("Qiagen", r"qiagen|qiaamp"),
    ("Thermo Fisher", r"thermo|applied biosystems|taqman|invitrogen"), ("Promega", r"promega|go ?taq"), ("Illumina", r"illumina|miseq|nextseq"),
    ("Hemocue", r"hemocue"), ("Accu-Chek", r"accu-?chek"), ("Arkray", r"arkray|aution"), ("Diagnostic Products", r"\bdpc\b"),
]
BRANDS = [(b, re.compile(p)) for b, p in BRANDS]


def brand(*texts):
    t = norm(" ".join(str(x) for x in texts if x))
    out = [b for b, rx in BRANDS if rx.search(t)]
    return "; ".join(dict.fromkeys(out))


def multi_product(desc, codes):
    d = str(desc or "")
    n_lines = len([x for x in re.split(r"[\r\n]+|\*{3}|pda ?\d+:", d, flags=re.I) if x.strip()])
    n_qty = len(re.findall(r"(?:^|[\s,;/\-])\d[\d,.]*\s*(?:c/u|unidad|und|uds|frasco|fco|caja|set|kit|galon|gln|paquete|pza|pbs|pruebas|cajas|frascos|sets|kits)",
                           norm(d)))
    return "Yes" if (len(str(codes).split(";")) >= 3 or n_lines >= 4 or n_qty >= 3) else ""


def check_value(qty, up, contract):
    """Return (unit_price, total, note). Fixes a published 'unit price' that is really the line total."""
    if qty is None or up is None:
        return up, None, ""
    calc = qty * up
    if contract and calc > 1.5 * contract and up <= 1.05 * contract and qty > 1:
        return up / qty, up, "Published unit price equals the line total (checked against contract value); unit price derived = total ÷ quantity"
    if not contract and qty >= 100 and up >= 10000 and calc > 5e6:
        return up / qty, up, "Published unit price looks like the line total (qty × price implausible); unit price derived = total ÷ quantity – check source"
    if contract and calc > 1.5 * contract:
        return up, contract, "CHECK: published quantity × unit price is inconsistent with the contract value; total set to the contract value"
    if calc > 1e6 and qty > 1 and not contract:
        return up, calc, "CHECK: quantity × unit price is unusually high and not corroborated by a contract value"
    return up, calc, "Total = quantity × unit price (computed)"


def year_of(d):
    return str(d)[:4] if d and str(d)[:4].isdigit() else ""


def tag_cols(t):
    return {"Indicator code": t["code"], "Segment name": NAME[t["code"]], "Tag confidence": t["confidence"],
            "All matched codes": t["codes"], "Tagged from": t["basis"]}


# ------------------------------------------------------------------ Honduras (ONCAE OCDS)
def honduras():
    aw, op = [], []
    for f in sorted(glob.glob(os.path.join(HERE, "hn_out_*.pkl"))):
        d = pd.read_pickle(f)
        for r in d["awarded"] + d["ce"]:
            seg = segment(r["buyer"])
            if not in_scope(seg, r["tag_code"]):
                continue
            t = {"code": r["tag_code"], "codes": r["tag_codes"], "confidence": r["tag_confidence"], "basis": r["tag_basis"]}
            mp = multi_product(r["item_description"], r["tag_codes"])
            up, tot, vnote = check_value(r.get("quantity"), r.get("unit_price"), r.get("contract_value"))
            if mp and r.get("contract_value") and tot and tot > 1.5 * r["contract_value"]:
                tot, vnote = r["contract_value"], "Total = contract value (the lot line's quantity × price exceeds it)"
            com = [vnote] if vnote else []
            if r["source_portal"].startswith("HonduCompras Cat") and norm(r["item_description"]).find("ocr") >= 0:
                com.append("Emergency (COVID-19) electronic catalogue item; product not specified beyond 'prueba rápida OCR'")
            if mp:
                com.append("Multi-product line: quantity/price cover a whole lot, not one product")
            if r.get("contract_value"):
                com.append(f"Contract value {r['contract_value']:,.2f}")
            if r.get("award_date_basis"):
                com.append(f"Award date = {r['award_date_basis']}")
            aw.append({
                "Country": "Honduras", "Source portal": r["source_portal"], "Buying institution / hospital": r["buyer"],
                "Tender / procedure no.": r["procedure_no"], "Procedure type": r["procedure_type"],
                "Tender title / description": r["tender_title"], **tag_cols(t),
                "Product / test": re.sub(r"\s+", " ", str(r["item_description"] or "")).strip()[:1000],
                "Brand / analyser": brand(r["item_description"]), "Awarded supplier (distributor)": r["supplier"],
                "Quantity": r["quantity"], "Unit": r["unit"], "Unit price": up, "Total awarded": tot,
                "Currency": r["currency"], "Contract type (comodato, por prueba, según demanda…)": r.get("tag_contract_type", ""),
                "Contract duration & extensions": "", "Publication date": r.get("publication_date", ""), "Award date": r["award_date"],
                "Status": r["status"], "Funding (national / World Bank / IDB / Global Fund / PAHO)": r["funding"],
                "Source link": r["source_link"], "Comments": "; ".join(com),
                "Buyer segment": seg, "Award year": year_of(r["award_date"]) or r["year_file"], "Multi-product line": mp,
                "UNSPSC": f"{r.get('unspsc', '')} {r.get('unspsc_desc', '') or ''}".strip()})
        for r in d["open"]:
            pub = str(r.get("publication_date") or "")
            if pub[:4] < "2026" and str(r.get("closing_date") or "")[:7] < "2026-09":
                continue  # stale "active" records from earlier years
            seg = segment(r["buyer"])
            if not in_scope(seg, r["tag_code"]):
                continue
            t = {"code": r["tag_code"], "codes": r["tag_codes"], "confidence": r["tag_confidence"], "basis": r["tag_basis"]}
            op.append({
                "Country": "Honduras", "Source portal": r["source_portal"], "Buying institution / hospital": r["buyer"],
                "Tender / procedure no.": r["procedure_no"], "Procedure type": r["procedure_type"],
                "Tender title / description": r["tender_title"], **tag_cols(t),
                "Product / test": re.sub(r"\s+", " ", str(r["item_description"] or "")).strip()[:1000],
                "Quantity": r["quantity"], "Unit": r["unit"], "Publication date": pub, "Closing date": r.get("closing_date", ""),
                "Status": r["status"], "Source link": r["source_link"], "Buyer segment": seg})
    return aw, op


# ------------------------------------------------------------------ El Salvador (COMPRASAL public API)
def el_salvador():
    m = pd.read_pickle(os.path.join(HERE, "es_tagged.pkl"))
    det_dir = os.path.join(HERE, "es_details")
    aw = []
    first_award = m.sort_values("award_id").drop_duplicates("proc_id").set_index("proc_id")["award_id"].to_dict()
    for (pid, prov), g in m.groupby(["proc_id", "prov"], dropna=False):
        r = g.iloc[0]
        seg = segment(r.inst)
        if not in_scope(seg, r.code):
            continue
        det, inf = {}, {}
        pp = os.path.join(det_dir, f"proc_{pid}.json")
        if os.path.exists(pp):
            det = (json.load(open(pp, encoding="utf-8")) or {}).get("data") or {}
        ip = os.path.join(det_dir, f"inf_{first_award.get(pid)}.json")
        if os.path.exists(ip):
            inf = ((json.load(open(ip, encoding="utf-8")) or {}).get("data") or {}).get("adjudicacion") or {}
        t = {"code": r.code, "codes": r.codes, "confidence": r.confidence, "basis": "title"}
        com = [f"{len(g)} awarded line(s) to this supplier; item names are not published in COMPRASAL's public API"]
        if det.get("monto_adjudicado"):
            com.append(f"Process total awarded (all suppliers) {float(det['monto_adjudicado']):,.2f}")
        if inf.get("monto_planificado"):
            com.append(f"Planned budget {float(inf['monto_planificado']):,.2f}")
        dur = f"{inf['plazo_contractual']} days (contract term)" if inf.get("plazo_contractual") else ""
        aw.append({
            "Country": "El Salvador", "Source portal": "COMPRASAL (DINAC) – public awards API",
            "Buying institution / hospital": r.inst,
            "Tender / procedure no.": " / ".join(x for x in [r.codigo, det.get("codigo_interno")] if x),
            "Procedure type": r.modalidad, "Tender title / description": r.nombre, **tag_cols(t),
            "Product / test": "", "Brand / analyser": brand(r.nombre), "Awarded supplier (distributor)": r.prov_com or r.prov,
            "Quantity": None, "Unit": "", "Unit price": None, "Total awarded": round(float(g.monto.sum()), 2), "Currency": "USD",
            "Contract type (comodato, por prueba, según demanda…)": r.contract_type,
            "Contract duration & extensions": dur, "Publication date": str(det.get("fecha_publicacion") or "")[:10],
            "Award date": r.fecha_adj, "Status": f"Adjudicado ({r.estado})" if r.estado else "Adjudicado",
            "Funding (national / World Bank / IDB / Global Fund / PAHO)": "National",
            "Source link": f"https://www.comprasal.gob.sv/procesos-publicos/{first_award.get(pid)}",
            "Comments": "; ".join(com), "Buyer segment": seg, "Award year": year_of(r.fecha_adj), "Multi-product line": "",
            "UNSPSC": ""})
    op = []
    if os.path.exists(os.path.join(HERE, "es_open_tagged.pkl")):
        o = pd.read_pickle(os.path.join(HERE, "es_open_tagged.pkl"))
        for r in o.itertuples():
            t = tag(title=r.nombre, buyer=r.inst)
            if not t or not in_scope(r.seg, t["code"]):
                continue
            op.append({
                "Country": "El Salvador", "Source portal": "COMPRASAL (DINAC) – public processes API", "Buying institution / hospital": r.inst,
                "Tender / procedure no.": r.codigo, "Procedure type": r.forma, "Tender title / description": r.nombre, **tag_cols(t),
                "Product / test": "", "Quantity": None, "Unit": "", "Publication date": str(r.pub or "")[:10],
                "Closing date": str(r.cierre or "")[:10], "Status": f"{r.estado} – {r.etapa_actual}",
                "Source link": f"https://www.comprasal.gob.sv/procesos-oportunidades", "Buyer segment": r.seg})
    return aw, op


# ------------------------------------------------------------------ agent CSVs (donor + ES legacy)
EN2ES = [
    (r"\b(rdt|rapid (diagnostic |antibody )?tests?|card tests?|test cards?|test device|self-?tests?|stat-?pak|tri-?line|cassette)\b", " prueba rapida "),
    (r"\bsyphilis\b", " sifilis "), (r"\bviral load\b", " carga viral "), (r"\bflow cytometer\b", " citometro de flujo "),
    (r"\bconfirmatory\b", " confirmatorio "), (r"\bassays?\b", " ensayo "), (r"\breagents?\b", " reactivos "), (r"\btests?\b", " prueba "),
    (r"\bblood glucose\b", " glucosa "), (r"\bstrips?\b", " tiras "), (r"\bhaematology|hematology\b", " hematologia "),
    (r"\bchemistry\b", " quimica clinica "), (r"\bmicrobiology\b", " microbiologia "), (r"\bpathology\b", " patologia "),
]


def en2es(s):
    s = re.sub(r"(?<=[a-z])(hiv|vih)", r" \1", str(s or ""), flags=re.I)
    for p, rep in EN2ES:
        s = re.sub(p, rep, s, flags=re.I)
    return s


AWARDED = re.compile(r"adjudic|contrat|orden de compra|purchase order|award|signed|firmado|finaliz|complet|deliver|entreg")


def agent_csv(path, default_portal, prescreened=True):
    aw, op = [], []
    if not os.path.exists(path):
        return aw, op
    df = pd.read_csv(path, dtype=str).fillna("")
    if "comments" in df:
        df = df[~df.comments.str.contains("SCOPE FLAG", na=False)]  # agent-flagged non-IVD lines from mixed tenders
    tr = df.source_portal.str.contains("Transparencia", na=False)
    if tr.any():
        # Transparency-portal contract rows can repeat COMPRASAL awards: drop those matching supplier + amount (±1%)
        def key(s):
            return re.sub(r"[^a-z0-9]", "", norm(s))[:18]
        cs = df[~tr & df.total_awarded.ne("")]
        seen = {}
        for s, v in zip(cs.supplier, cs.total_awarded):
            try:
                seen.setdefault(key(s), []).append(float(v))
            except ValueError:
                pass
        def dup(r):
            try:
                v = float(r.total_awarded)
            except ValueError:
                return False
            return any(abs(v - x) <= 0.01 * max(v, 1) for x in seen.get(key(r.supplier), []))
        drop = df[tr].apply(dup, axis=1)
        df = df.drop(drop[drop].index)
        print(f"  transparency rows dropped as COMPRASAL duplicates: {int(drop.sum())} of {int(tr.sum())}")
    for r in df.to_dict("records"):
        st = norm(r.get("status", ""))
        if "cancel" in st or "desiert" in st or "fracas" in st:
            continue
        if "borderline" in norm(r.get("comments", "")):
            continue  # general lab equipment (freezers, cabinets, water baths): excluded by the brief's scope
        item, title = en2es(r.get("item_description", "")), en2es(r.get("tender_title", ""))
        # Agent rows are already screened as diagnostics: treat them as a diagnostic class for gating
        if not AWARDED.search(st) and not re.search(r"open|planned|abiert|en ejecucion|recepcion|en proceso", st) \
                and str(r.get("publication_date", ""))[:4] < "2026":
            continue  # old processes with no registered award (e.g. legacy 'Gestión de la Compra'): neither awarded nor open
        lab_tender = prescreened is True or (prescreened == "title" and tag(title=title, buyer=r.get("buyer", "")) is not None)
        t = tag(item=item, title=title, buyer=r.get("buyer", ""), unspsc="41116010" if prescreened is True else "", lab_context=lab_tender)
        if not t and prescreened is True:
            t = tag(title=item + " " + title, buyer=r.get("buyer", ""))
        if not t:
            continue
        seg = segment(r.get("buyer", ""))
        if not in_scope(seg, t["code"]) and "fund" not in norm(r.get("funding", "")):
            continue

        def f(x):
            try:
                return float(str(x).replace(",", ""))
            except ValueError:
                return None
        row = {
            "Country": r.get("country", ""), "Source portal": r.get("source_portal") or default_portal,
            "Buying institution / hospital": r.get("buyer", ""), "Tender / procedure no.": r.get("procedure_no", ""),
            "Procedure type": r.get("procedure_type", ""), "Tender title / description": r.get("tender_title", ""), **tag_cols(t),
            "Product / test": r.get("item_description", ""), "Brand / analyser": r.get("brand_model", "") or r.get("manufacturer", "") or brand(r.get("item_description", "")),
            "Awarded supplier (distributor)": r.get("supplier", ""), "Quantity": f(r.get("quantity")), "Unit": r.get("unit", ""),
            "Unit price": f(r.get("unit_price")), "Total awarded": f(r.get("total_awarded")), "Currency": r.get("currency", ""),
            "Contract type (comodato, por prueba, según demanda…)": r.get("contract_type", "") or t["contract_type"],
            "Contract duration & extensions": r.get("duration", ""), "Publication date": r.get("publication_date", ""),
            "Award date": r.get("award_date", ""), "Status": r.get("status", ""),
            "Funding (national / World Bank / IDB / Global Fund / PAHO)": r.get("funding", ""), "Source link": r.get("source_link", ""),
            "Comments": "; ".join(x for x in [r.get("comments", ""), ("Manufacturer: " + r["manufacturer"]) if r.get("manufacturer") else ""] if x),
            "Buyer segment": seg, "Award year": year_of(r.get("award_date", "")) or year_of(r.get("publication_date", "")),
            "Multi-product line": "", "UNSPSC": ""}
        if not year_of(r.get("award_date", "")) and year_of(r.get("publication_date", "")):
            row["Comments"] = (row["Comments"] + "; " if row["Comments"] else "") + "Award year = publication year (no award date published)"
        fund = row["Funding (national / World Bank / IDB / Global Fund / PAHO)"]
        if not fund.strip() and not str(row["Source portal"]).startswith(("Global Fund", "World Bank", "IDB", "UNGM")):
            row["Funding (national / World Bank / IDB / Global Fund / PAHO)"] = "National"
            row["Comments"] = (row["Comments"] + "; " if row["Comments"] else "") + "Funding source not stated in the portal (assumed national)"
        if AWARDED.search(st):
            aw.append(row)
        else:  # open, planned, in process
            row["Closing date"] = ""
            op.append(row)
    return aw, op


if __name__ == "__main__":
    A, O = [], []
    for fn in (honduras, el_salvador):
        a, o = fn()
        A += a
        O += o
        print(fn.__name__, len(a), "awarded rows,", len(o), "open rows")
    for path, portal, pre in [(os.path.join(HERE, "agents", "donor", "donor_raw.csv"), "Donor / international", True),
                              (os.path.join(HERE, "agents", "es_legacy", "es_legacy_raw.csv"), "El Salvador institutional sites", "title"),
                              (os.path.join(HERE, "agents", "manual", "manual_raw.csv"), "World Bank", True)]:
        a, o = agent_csv(path, portal, pre)
        A += a
        O += o
        print(os.path.basename(path), len(a), "awarded rows,", len(o), "open rows")
    # Lines that are mostly a list of medicines with one diagnostic item: the total is not diagnostics spend
    drug = re.compile(r"\b\d+(\.\d+)? ?(mg|mcg|ui)\b|tabletas?|capsulas?|unguentos?|jarabe|ampollas?|inyectable")
    nmed = 0
    for r in A:
        n = len(drug.findall(norm(r.get("Product / test", ""))))
        if n >= 3 and r.get("Total awarded"):
            r["Comments"] = (f"Line is mostly a list of medicines that includes this diagnostic item; the published total "
                             f"({r['Total awarded']:,.2f} {r.get('Currency', '')}) covers the whole list, so Total awarded and Unit price are left blank"
                             + ("; " + r["Comments"] if r["Comments"] else ""))
            r["Total awarded"], r["Unit price"], r["Multi-product line"] = None, None, "Yes"
            nmed += 1
    print("medicine-list lines with value moved to comments:", nmed)
    # Donor rows that repeat a national-portal award (same supplier, amount within 1%): keep, but flag
    def skey(s):
        return re.sub(r"[^a-z0-9]", "", norm(s))[:14]
    nat = {}
    for r in A:
        if not str(r["Source portal"]).startswith(("Global Fund", "World Bank", "IDB", "UNGM")) and r.get("Total awarded"):
            nat.setdefault((r["Country"], skey(r["Awarded supplier (distributor)"])), []).append((r["Total awarded"], r["Tender / procedure no."]))
    flagged = 0
    for r in A:
        if str(r["Source portal"]).startswith(("World Bank", "IDB", "UNGM")) and r.get("Total awarded"):
            for v, pno in nat.get((r["Country"], skey(r["Awarded supplier (distributor)"])), []):
                if abs(v - r["Total awarded"]) <= 0.01 * max(v, 1):
                    r["Comments"] = (r["Comments"] + "; " if r["Comments"] else "") + f"Same supplier and amount as national-portal row {pno} – do not add both"
                    flagged += 1
                    break
    print("donor rows flagged as also in national portals:", flagged)
    pd.to_pickle({"awarded": A, "open": O}, os.path.join(HERE, "eshn_rows.pkl"))
    print("total", len(A), "awarded,", len(O), "open")
