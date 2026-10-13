"""Extract tagged IVD / diabetes lines from ONCAE OCDS pickles (HC1 awards + open tenders, CE orders)."""
import glob
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tagger import tag, norm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PK = os.path.join(HERE, "hn_pkl")


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def first_url(df, key_cols, url_col):
    if df is None or df.empty:
        return {}
    d = df.dropna(subset=[url_col]).drop_duplicates(key_cols)
    return {tuple(r[k] for k in key_cols) if len(key_cols) > 1 else r[key_cols[0]]: r[url_col] for _, r in d.iterrows()}


def institutions(S, year):
    """ocid -> institution name (the buyer field holds the purchasing unit)."""
    inst = {}
    mp = os.path.join(PK, f"HC1_datos_{year}_member.pkl")
    if os.path.exists(mp):
        m = pd.read_pickle(mp).dropna(subset=["parties/0/memberOf/0/name"])
        inst = m.drop_duplicates("ocid").set_index("ocid")["parties/0/memberOf/0/name"].to_dict()
    p = S.get("parties")
    if p is not None and len(p):
        b = p[p["parties/0/roles"].fillna("").str.contains("buyer")]
        for ocid, names in b.groupby("ocid")["parties/0/name"]:
            if ocid not in inst and len(names):
                inst[ocid] = names.iloc[0]
    return inst


def buyer_label(inst, unit):
    inst, unit = (inst or "").strip(), (unit or "").strip()
    if not inst or norm(inst) == norm(unit):
        return unit
    return f"{inst} – {unit}" if unit else inst


def hc1(year):
    S = pd.read_pickle(os.path.join(PK, f"HC1_datos_{year}.pkl"))
    INST = institutions(S, year)
    rel = S["releases"].set_index("ocid")
    out, opn = [], []
    # ---------------- awarded lines
    ai = S["awa_items"].copy()
    ai.columns = [c.replace("awards/0/items/0/", "it_").replace("awards/0/", "aw_").replace("/", "_") for c in ai.columns]
    sup = S["awa_suppliers"].copy()
    sup.columns = [c.replace("awards/0/suppliers/0/", "sup_").replace("awards/0/", "aw_") for c in sup.columns]
    sup = sup.groupby(["ocid", "aw_id"])["sup_name"].apply(lambda s: "; ".join(dict.fromkeys(x for x in s if isinstance(x, str)))).to_dict()
    con = S["contracts"].copy()
    con.columns = [c.replace("contracts/0/", "c_").replace("/", "_") for c in con.columns]
    con_by_award = {(r.ocid, r.c_awardID): r for r in con.itertuples()}
    adoc = first_url(S.get("awa_documents"), ["ocid", "awards/0/id"], "awards/0/documents/0/url")
    cdoc = first_url(S.get("con_documents"), ["ocid"], "contracts/0/documents/0/url")
    tdoc = first_url(S.get("ten_documents"), ["ocid"], "tender/documents/0/url")
    for r in ai.itertuples():
        R = rel.loc[r.ocid] if r.ocid in rel.index else None
        if R is None:
            continue
        title = R.get("tender/title") or ""
        buyer = buyer_label(INST.get(r.ocid), R.get("buyer/name"))
        t = tag(item=r.it_description, title=title, buyer=buyer, unspsc=str(r.it_classification_id or ""))
        if not t:
            continue
        c = con_by_award.get((r.ocid, r.aw_id))
        qty, up = num(r.it_quantity), num(r.it_unit_value_amount) if hasattr(r, "it_unit_value_amount") else None
        out.append(dict(
            country="Honduras", source_portal="HonduCompras 1 (ONCAE OCDS open data)", buyer=buyer,
            procedure_no=r.ocid.replace("ocds-lcuori-", ""), procedure_type=R.get("tender/procurementMethodDetails"),
            tender_title=title, item_description=r.it_description, unspsc=r.it_classification_id,
            unspsc_desc=r.it_classification_description, supplier=sup.get((r.ocid, r.aw_id), ""),
            quantity=qty, unit=r.it_unit_name, unit_price=up,
            total_awarded=(qty * up) if (qty is not None and up is not None) else None,
            currency=(c.c_value_currency if c is not None and isinstance(c.c_value_currency, str) else "HNL"),
            contract_value=num(c.c_value_amount) if c is not None else None,
            publication_date=str(R.get("tender/datePublished") or "")[:10],
            award_date=str((c.c_dateSigned if c is not None and isinstance(c.c_dateSigned, str) else R.get("date")) or "")[:10],
            award_date_basis="contract signed" if c is not None and isinstance(c.c_dateSigned, str) else "award release date",
            status=R.get("tender/statusDetails"), funding="National",
            source_link=adoc.get((r.ocid, r.aw_id)) or cdoc.get(r.ocid) or tdoc.get(r.ocid) or "http://h1.honducompras.gob.hn/",
            ocid=r.ocid, year_file=year, **{f"tag_{k}": v for k, v in t.items()}))
    # ---------------- open / in-process tenders (no award yet)
    ti = S["ten_items"].copy()
    ti.columns = [c.replace("tender/items/0/", "it_").replace("tender/", "t_").replace("/", "_") for c in ti.columns]
    awarded = set(ai.ocid)
    for r in ti.itertuples():
        if r.ocid in awarded or r.ocid not in rel.index:
            continue
        R = rel.loc[r.ocid]
        st = str(R.get("tender/status") or "")
        if st not in ("active", "planned"):
            continue
        title = R.get("tender/title") or ""
        buyer = buyer_label(INST.get(r.ocid), R.get("buyer/name"))
        t = tag(item=r.it_description, title=title, buyer=buyer, unspsc=str(r.it_classification_id or ""))
        if not t:
            continue
        opn.append(dict(
            country="Honduras", source_portal="HonduCompras 1 (ONCAE OCDS open data)", buyer=buyer,
            procedure_no=r.ocid.replace("ocds-lcuori-", ""), procedure_type=R.get("tender/procurementMethodDetails"),
            tender_title=title, item_description=r.it_description, unspsc=r.it_classification_id,
            quantity=num(r.it_quantity), unit=r.it_unit_name,
            publication_date=str(R.get("tender/datePublished") or "")[:10],
            closing_date=str(R.get("tender/tenderPeriod/endDate") or "")[:10],
            status=R.get("tender/statusDetails"), source_link=tdoc.get(r.ocid) or "http://h1.honducompras.gob.hn/",
            ocid=r.ocid, year_file=year, **{f"tag_{k}": v for k, v in t.items()}))
    return out, opn


def ce(year):
    S = pd.read_pickle(os.path.join(PK, f"CE_datos_{year}.pkl"))
    if "con_items" not in S:
        return []
    rel = S["releases"].drop_duplicates("ocid").set_index("ocid")
    mem = S.get("par_memberOf")
    inst = {}
    if mem is not None and len(mem):
        inst = mem.dropna(subset=["parties/0/memberOf/0/name"]).drop_duplicates("ocid").set_index("ocid")["parties/0/memberOf/0/name"].to_dict()
    ci = S["con_items"].copy()
    ci.columns = [c.replace("contracts/0/items/0/", "it_").replace("contracts/0/", "c_").replace("/", "_") for c in ci.columns]
    con = S["contracts"].copy()
    con.columns = [c.replace("contracts/0/", "c_") for c in con.columns]
    con = con.drop_duplicates("ocid").set_index("ocid")
    sup = S["con_suppliers"].groupby("ocid")["contracts/0/suppliers/0/name"].apply(lambda s: "; ".join(dict.fromkeys(x for x in s if isinstance(x, str)))).to_dict()
    att = S.get("con_ite_attributes")
    cat = {}
    if att is not None and len(att):
        cat = att.drop_duplicates("ocid").set_index("ocid")["contracts/0/items/0/attributes/0/value"].to_dict()
    out = []
    for r in ci.itertuples():
        R = rel.loc[r.ocid] if r.ocid in rel.index else None
        C = con.loc[r.ocid] if r.ocid in con.index else None
        unit_buyer = (R.get("buyer/name") if R is not None else "") or ""
        buyer = inst.get(r.ocid) or unit_buyer
        t = tag(item=r.it_description, title=str(cat.get(r.ocid, "")), buyer=buyer, unspsc=str(r.it_classification_id or ""))
        if not t:
            continue
        qty, up = num(r.it_quantity), num(r.it_unit_value_amount)
        out.append(dict(
            country="Honduras", source_portal="HonduCompras Catálogo Electrónico (ONCAE OCDS open data)",
            buyer=buyer if buyer == unit_buyer else f"{buyer} – {unit_buyer}",
            procedure_no=r.ocid.replace("ocds-lcuori-", "OC "), procedure_type="Catálogo Electrónico (Convenio Marco)",
            tender_title=f"Orden de compra – {cat.get(r.ocid, '')}", item_description=r.it_description,
            unspsc=r.it_classification_id, unspsc_desc=r.it_classification_description,
            supplier=sup.get(r.ocid, ""), quantity=qty, unit=r.it_unit_name, unit_price=up,
            total_awarded=(qty * up) if (qty is not None and up is not None) else None,
            currency=r.it_unit_value_currency if isinstance(r.it_unit_value_currency, str) else "HNL",
            contract_value=num(C.get("c_value/amount")) if C is not None else None,
            publication_date="", award_date=str((C.get("c_period/startDate") if C is not None else "") or (R.get("date") if R is not None else ""))[:10],
            award_date_basis="purchase order date", status=(C.get("c_statusDetails") if C is not None else "") or "Orden de compra",
            funding="National", source_link="https://catalogo.honducompras.gob.hn/",
            ocid=r.ocid, year_file=year, **{f"tag_{k}": v for k, v in t.items()}))
    return out


if __name__ == "__main__":
    years = sys.argv[1:] or [str(y) for y in range(2019, 2027)]
    for y in years:
        aw, op, cr = [], [], []
        if os.path.exists(os.path.join(PK, f"HC1_datos_{y}.pkl")):
            aw, op = hc1(y)
        if os.path.exists(os.path.join(PK, f"CE_datos_{y}.pkl")):
            cr = ce(y)
        pd.to_pickle({"awarded": aw, "open": op, "ce": cr}, os.path.join(HERE, f"hn_out_{y}.pkl"))
        print(y, "awarded lines", len(aw), "| open lines", len(op), "| CE lines", len(cr), flush=True)
