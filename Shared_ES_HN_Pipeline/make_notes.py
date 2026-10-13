"""Build notes.json (Sources & notes tab) from static text + live counts in eshn_rows.pkl."""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from notes_base import EL_SALVADOR, HONDURAS, METHOD  # noqa: E402

d = pd.read_pickle(os.path.join(HERE, "eshn_rows.pkl"))
aw, op = pd.DataFrame(d["awarded"]), pd.DataFrame(d["open"])


def src_group(s):
    s = str(s)
    for k, v in [("HonduCompras Cat", "HonduCompras – Catálogo Electrónico"), ("HonduCompras", "HonduCompras 1 (OCDS)"),
                 ("COMPRASAL (DINAC)", "COMPRASAL (new, Oct 2024 →)"), ("COMPRASAL (legacy)", "COMPRASAL legacy API (2019 – mid-2023)"),
                 ("salud.gob.sv", "MINSAL resolutions (Wayback)"), ("Transparencia", "Portal de Transparencia (Wayback)"),
                 ("Global Fund", "Global Fund PQR"), ("World Bank", "World Bank"), ("IDB", "IDB / BID"), ("UNGM", "UNGM (UNOPS / UNDP)")]:
        if k in s:
            return v
    return s


aw["grp"] = aw["Source portal"].map(src_group)
op["grp"] = op["Source portal"].map(src_group)
counts = []
for (c, g), x in aw.groupby(["Country", "grp"]):
    yrs = x["Award year"].replace("", pd.NA).dropna()
    rng = f"{yrs.min()}–{yrs.max()}" if len(yrs) else "n/a"
    item = (x["Product / test"].astype(str).str.len() > 0).mean()
    counts.append((f"{c} – {g}", f"{len(x):,} awarded rows ({rng}); {item:.0%} with product-level text; "
                                 f"open/planned rows: {int(((op.Country == c) & (op.grp == g)).sum())}"))
counts.append(("Open tenders tab", f"{len(op):,} rows (tenders without an award: published in 2026 / still in process, plus donor-plan lines)"))
conf = aw["Tag confidence"].value_counts()
counts.append(("Tag confidence (awarded)", ", ".join(f"{k}: {v:,}" for k, v in conf.items())))
counts.append(("Multi-product lot lines", f"{int((aw['Multi-product line'] == 'Yes').sum()):,} (quantity/price refer to a whole lot)"))
counts.append(("Rows with a value CHECK note", f"{int(aw['Comments'].astype(str).str.contains('CHECK').sum()):,} – the published quantity × unit price did not reconcile"))

ES_LEGACY = [
    ("Legacy COMPRASAL back-end API (2019 – mid-2023)", "https://unacv2.mh.gob.sv/comprasalmicro/... – still public (no login). 42,923 processes of 45 health "
        "buyers were screened; 2,596 candidate processes; award resolutions / contracts / purchase orders downloaded (2,188 documents) and parsed into "
        "item lines where they reconcile with the published award amount (resolution ±2%, per-supplier contract ±5%); otherwise the supplier-level amount "
        "is kept (Product / test blank). Best line coverage: Hospital Rosales, Nueva Concepción, Sonsonate, Cojutepeque, Ilobasco, San Miguel, Gotera, "
        "Instituto de Medicina Legal; ISSS partly (OCR of scanned contracts)."),
    ("MINSAL resolutions (salud.gob.sv via Wayback)", "Live site is Cloudflare-blocked (403); archived resolutions 2019, 2021, 2022 and 2024–2026 World Bank "
        "project awards transcribed to line level (HIV/HBV/HCV viral load, CD4, serology, rapid tests, STI/HPV PCR, HemoCue, neonatal screening, thyroid). "
        "These replace the matching COMPRASAL supplier rows (no double counting). MINSAL 2020 resolutions were never archived."),
    ("Portal de Transparencia (via Wayback)", "Live site blocked (403). MINSAL central contracts (capture Aug-2022) and ISSS contracts (capture Jul-2019, "
        "truncated) used at contract level; rows matching a COMPRASAL award on supplier + amount (±1%) were removed as duplicates."),
    ("Filtering applied", "Dropped: 1,154 lines flagged non-IVD inside mixed tenders (syringes, sutures, PPE…), 1,370 tender-only rows with no award "
        "registered ('Gestión de la Compra' / desierto / sin efecto), and lines the tagger does not recognise as diagnostics."),
    ("Known gaps", "No line detail for the largest ISSS contracts (e.g. LP-050/2023-G Roche chemistry, USD 5.17M) and ISSS 2019–2021 (no documents "
        "uploaded); 845 image-only PDFs not OCR'd (those processes stay at supplier level); glucose strips/meters bought by ISSS and MINSAL inside "
        "generic 'insumos médicos' tenders are mostly not visible."),
]

DONOR = [
    ("Global Fund – Price & Quality Reporting", "Public Tableau 'Transaction Summary' (insights.theglobalfund.org) – the old PQR data API is blocked. "
        "Line level: product, pack size, packs, pack price, total, supplier/agent, manufacturer, PO date (2019–2025). HIV / syphilis / HBV / HCV / "
        "malaria RDTs, PIMA CD4, Xpert HIV-1 VL, BD FACSCalibur. Values are the viz display values (rounded)."),
    ("World Bank", "Contract awards (FinancesOne DS00005), procurement notices API and STEP procurement plans (P173861, P173872, P169677, P164356, "
        "P506486; P176532 checked separately). Honduras: no WB-financed IVD goods except P176532's molecular-lab equipment line (open). "
        "El Salvador: NCD, COVID-19, Crecer Juntos and PROMAS projects – lot/contract level; item lists come from the tender notices."),
    ("IDB / BID", "Procurement-notices dataset + linked PDFs; contract-awards datastore API (the CSV download is behind a bot check). Honduras 2023 PCR-RT "
        "reagent tender at line level; El Salvador COVID molecular tests, sequencer, Salud Mesoamérica reagents, open pathology-equipment tender."),
    ("UNGM (UNOPS / UNDP)", "Public award search (rate-limited): 5 lab awards found (El Salvador molecular CT/NG/HSV tests and CD4/CD8 flow reagents; "
        "Honduras IHSS glucose strips, haematology analyser, urine strips). ~500 UNOPS-for-IHSS award pages read – no further IVD lots."),
    ("Not reachable / no data", "PAHO Strategic Fund country purchases (not published); UNICEF supply annexes (bot check, country totals only); "
        "projectprocurement.iadb.org (HTTP 526); bcie.org (maintenance – lead: April 2020 donation of PowerChek SARS-CoV-2 PCR kits, ~26,000 per country, "
        "unverified, not in the data)."),
    ("Leads worth a manual check", "UNGM notice 315716 – UNOPS long-term agreements for medical devices and IVDs tagged to Honduras (Oct 2026, not "
        "verified – page rate-limited). IDB contracts with lab distributors but no public description: ES-L1160 P00092/P00096 (C.O.R.E.S.A., EQUILAB, "
        "Equipos para Laboratorios, Comercio y Representaciones; Oct 2025) and HO-L1199 IMLAB USD 356,266 / INEQ USD 197,192 (2024). World Bank "
        "El Salvador CSJ-227 'equipo médico para diagnóstico' (USD 1.86M, item list not public)."),
    ("Excluded on purpose", "General lab equipment bought for diagnostic labs (freezers, biosafety/PCR cabinets, water baths, laminar flow, PCR "
        "workstations), PPE on Global Fund diagnostic orders, one cancelled World Bank tender."),
]

notes = [["Row counts by source", counts], ["Method", METHOD], ["Honduras sources", HONDURAS], ["El Salvador sources (new COMPRASAL)", EL_SALVADOR],
         ["El Salvador 2019 – mid-2023 (legacy systems)", ES_LEGACY], ["Donor / international sources", DONOR]]
json.dump(notes, open(os.path.join(HERE, "notes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("notes.json written;", len(counts), "count lines")
