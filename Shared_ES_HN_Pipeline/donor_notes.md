# Donor / international sources – IVD & diabetes monitoring, El Salvador + Honduras, 2019–2026

Run date: 2026-10-07 (from a PC in India, plain HTTP via curl/python; no logins, no CAPTCHAs, no browser).
Output: `donor_raw.csv` (schema = `RAW_SCHEMA.md`). Row counts per source/country are at the end of this file.
All money as published (USD unless noted; Honduras IDB lot 2 is in HNL).

General conventions used in the CSV
- One row per product line where the source publishes lines (Global Fund PQR, IDB Honduras PCR tender, IDB SV article prices).
  Where the source only publishes a lot/contract amount (World Bank, most IDB), one row per contract/lot; the tendered items and
  tendered quantities (taken from the invitation-for-bids notice) are listed verbatim inside `item_description`, and `quantity`
  is filled only when the lot is a single item (comment says "quantity = tendered quantity").
- No unit prices were computed. `total_awarded` is always a published figure (contract amount, evaluated lot/article price, or PQR line total).
- `status`: Contratado / Adjudicado / Orden de compra for awards; `Open` for published tenders with no award yet;
  `Planned (not yet tendered)` for lines that exist only in a World Bank STEP procurement plan; `Cancelled`.
- Rows flagged **BORDERLINE** in `comments` are general lab equipment (water baths, biosafety/PCR cabinets, lab freezers,
  laminar-flow cabinet) bought for diagnostic labs; drop them if the market definition excludes non-analyser lab equipment.
- Excluded on purpose: PPE/masks (even on Global Fund diagnostic POs), vaccines, medicines, imaging, sterilisers/autoclaves,
  water/food/soil/environmental labs, sample-collection furniture, HPV *treatment* supplies, specimen-transport boxes.

---------------------------------------------------------------------------------------------------

## 1. Global Fund – Price & Quality Reporting (PQR)

**Reachable: YES (via the public Tableau "Transaction Summary" viz, not via an API).**

- The OData API `fetch.theglobalfund.org/v3.x/odata/*` (where PQR used to live) now answers "The request is blocked" for every
  v3 version; `fetch.theglobalfund.org/v4/odata/` works but has **no PQR entity** (only grants, financials, documents…).
  `data.theglobalfund.org` explorer API (`data.api.theglobalfund.org/...`) has no procurement endpoints. `data-service.theglobalfund.org/downloads`
  no longer offers a PQR file.
- What worked: the PQR page (https://www.theglobalfund.org/en/sourcing-management/price-quality-reporting/) embeds
  `https://insights.theglobalfund.org/t/Public/views/PriceQualityReportingTransactionSummary/TransactionSummary` (guest Tableau Server 2024.2).
  Scripted the same calls the browser makes:
  1. `POST /vizql/t/Public/w/PriceQualityReportingTransactionSummary/v/TransactionSummary/startSession/viewing` (header `Tableau-Viz-Path`)
  2. `POST .../bootstrapSession/sessions/{X-Session-Id}`
  3. `POST .../sessions/{id}/commands/tabdoc/categorical-filter` on
     `[PQR_ExternalReportingView (2) (local copy)].[none:Geography Name (copy):nk]` = Honduras / El Salvador and
     `[...].[none:Product Category:nk]` = "Diagnostic, PPE and Medical Device"
  4. decoded the returned presentation model (dataDictionary + paneColumns) into rows. Scripts: `tab_client.py`, `tab_parse.py`, `gf_pqr_pull.py`.
  (`.csv` export of the view and `get-underlying-data` both time out / return 500 – do not bother.)
- Fields provided per transaction: country, grant, PO number, PO date, scheduled & actual delivery dates, product group, product description
  (verbatim incl. catalogue code), pack size, number of packs, pack price USD, total product cost USD, supplier/agent
  (PFSCM, IDA, i+ Solutions, "Direct from Mfg"), manufacturer, invoice currency, freight flag, PQR primary key. No buyer name (only grant/PR code).
- Check: Honduras diagnostics sum of lines USD 1,726,506 = viz grand total 1,726,500 → no truncation.
- Rows: Honduras 110 diagnostic-category transactions 2008–2025, of which **36 in 2019–2025** kept (3 mask/respirator lines dropped);
  El Salvador 58 transactions 2009–2025, **27 in 2019–2025** kept (5 mask/N95 lines dropped).
  Content: HIV RDTs (Determine, OraQuick incl. self-test, Stat-Pak, Bioline, Geenius, First Response, Kehua, InTec, ABON), syphilis &
  HIV/syphilis duo RDTs, HBsAg & HCV RDTs, PIMA CD4 cartridges, Xpert HIV-1 VL, BD FACSCalibur, malaria Pf/Pv RDTs.
  No GeneXpert MTB cartridges or COVID-19 tests are reported for HN/SV in PQR.
- Also checked geographies "Central America" (0 diagnostic rows) and "Americas" (31 rows – all ORAS Andean TB grant / old regional HIV grants,
  not HN/SV → excluded).

## 2. World Bank

**Reachable: YES (all three channels).**

(a) Contract awards in IPF – the Socrata URL `finances.worldbank.org/resource/kdui-wcs3.json` now 302-redirects to FinancesOne (Next.js, no JSON).
Working API: `https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice?datasetId=DS00005&resourceId=RS00005&type=json&top=1000&skip=0&filter=borrower_country='Honduras'`
(filter syntax is SQL-like `field='value'`; OData `eq` fails). Pulled all 2,788 HN + 1,403 SV awards.
Fields: project, WB contract no., borrower reference no., description (often just "contract N/2019" or lot numbers), procurement method/category,
supplier, supplier country, signed amount USD, signing date, review type. No items, quantities or unit prices.
(DS01142 "Health sector procurement contracts for LAC" exists on FinancesOne but its API resource id could not be resolved; it is a subset of DS00005.)

(b) Procurement notices: `https://search.worldbank.org/api/v2/procnotices?format=json&project_ctry_name_exact=Honduras&rows=500&os=0`
(note: `countryshortname_exact` is ignored by this endpoint – use `project_ctry_name_exact` or `project_id=`). 3,630 HN + 2,005 SV notices.
`notice_text` (HTML) contains: for IFBs the item tables (product code, description, unit, quantity); for awards the bidders,
bid prices at opening/evaluated, signed price, award/signature date, duration. Notice page = `https://projects.worldbank.org/en/projects-operations/procurement-detail/<id>`.

(c) STEP procurement plans: projects list `https://search.worldbank.org/api/v2/projects?format=json&countryshortname_exact=El Salvador&rows=500`;
plans `https://search.worldbank.org/api/v3/wds?format=json&projectid=<P>&docty_exact=Procurement%20Plan` (latest PDF parsed with PyMuPDF).
Plans parsed: P173861 (HN COVID-19), P173872 (SV COVID-19), P169677 (SV Crecer Juntos / Growing up Healthy Together), P164356 (SV NCDs, PHRD grant),
P506486 (SV PROMAS – Improving Health Care). P176015 and P180475 (HN AFs) have no plan in WDS. P176532 skipped as instructed
(already known: "Compra de Equipo Médico para tres (3) laboratorios de Biología Molecular", US$95,000, En ejecución – NOT repeated in the CSV).

Findings:
- **Honduras: no World Bank-financed IVD goods found** outside P176532. The HN COVID-19 project (P173861) bought PPE, Siemens imaging, hospital
  equipment and paid vaccinators; its lab support appears to have gone through a UNOPS output agreement (USD 4,037,731, HN-INVEST-H-210143-CS-UN)
  whose sub-purchases are not itemised in WB data. Lab items in other HN projects are food/water/environment labs (excluded).
- **El Salvador: 26 rows** – NCD project (HPV screening tests USD 611k; lab reagents FARLAB/NIPRO; NCD lab tests FARLAB USD 411,675);
  COVID-19 project (RT-PCR extraction/amplification kits USD 1.04M + 1.69M, VTM swabs, molecular-biology lab equipment incl. sequencer
  USD 998k, cold storage, cabinets; one cancelled tender); Crecer Juntos (HemoCue anaemia screening, hemoglobinopathy tests 49,890,
  neonatal screening/thyroid tests USD 1.79M comodato, sweat-chloride, chromosomal microarray 2,590 tests USD 1.33M, cytogenetics reagents,
  75 portable gas analysers USD 1.14M); PROMAS (open tender incl. 100 glucometers with strips; planned NCD lab tests USD 105,760 and basic
  clinical lab equipment USD 671,826).
- Caveats: lot amounts only; several contract descriptions are bare ("FARLAB … LOTES 1 y 4") – content inferred only from the tender title.
  ANCDP-35 (USD 411,675) is in the notices but missing from the contract-awards dataset. CSJ-227 "Suministro de equipo médico para diagnóstico"
  (USD 1.86M, en ejecución) and CSJ-132/152 (cancelled, USD 4.7M) could contain lab analysers but no item list is public – not in CSV.

## 3. IDB / BID

**Reachable: PARTLY.**
- Procurement notices dataset (CSV, 34,792 notices, through 2025-10-03): `https://data.iadb.org/files/download/9cc29cd0-c487-42e9-ad49-9971b4125066`
  (package `project-procurement-bidding-notices-and-notification-of-contract-awards`). Each row links a PDF on `idbdocs.iadb.org` with the full
  notice; award PDFs list awardees, evaluated prices per lot/article, signed amounts and dates; the Honduras PCR "Resultados de la licitación"
  lists every line with quantity, unit price and line total.
- Contract awards dataset: CSV download (`data.iadb.org/dataset/download/dd09c605-.../csv`) is behind an AWS-WAF JavaScript challenge (not bypassed),
  BUT the CKAN datastore API works: `https://data.iadb.org/api/3/action/datastore_search?resource_id=dd09c605-9cd8-49c5-92dc-191ff6ecdd58&filters={"operation_country_name":"HONDURAS"}&limit=5000`
  (18,964 HN + 5,047 SV contracts). Fields: contract id, project, operation no., contract type, method, firm, amount, signature date – **no description**.
- `projectprocurement.iadb.org/en/awarded-contracts` returned HTTP 526 (origin down) – not used.
- Rows: **Honduras 13** (HO-L1199 loan 4713/BL-HO, LPI-002-2023 "Adquisición de reactivos PCR-RT para COVID-19": Bioneer ExiPrep, Zybio T-200
  extraction kits, tubes, Invitrogen PureLink, AgPath-ID, MicroAmp, QuantStudio calibration plates; DIMEX/DIPRODI/PROMED; line prices published).
  **El Salvador 16** (ES-L1144 COVID loan 5043/OC-ES: molecular COVID test USD 678k, sequencer USD 851,637 + workstation, 7 variant-reagent
  articles with prices but no descriptions; ES-G1003 Salud Mesoamérica hemostasis & chemistry reagents FARLAB/Diagnostika Capris;
  ES-L1095 Nejapa hospital portable gas analyser; ES-L1160 NCD-survey/biorepository lab equipment (2 small contracts, items not identified) and
  an open pathology-equipment tender).
- Caveats: the 2022 direct purchase of PCR reagents under HO-L1199 (referenced as price benchmark in the 2023 evaluation) is not published.
  ES-L1160 contracts P00092 (C.O.R.E.S.A. 48,024; EQUILAB 32,632) and P00096 (EQUIPOS PARA LABORATORIOS 30,130; COMERCIO Y REPRESENTACIONES 53,912),
  Oct-2025, and HO-L1199 HOA1099 IMLAB 356,266 / HOA1098 INEQ MÉDICA 197,192 (2024) are with lab/medical distributors but have no public
  description – NOT in CSV; worth a look in COMPRASAL / HonduCompras. ES-L1144 article descriptions (RES-COVID-40) are only in the bidding document.

## 4. UNGM / UNOPS / UNDP / UNICEF

- **UNGM contract awards: reachable** (no login) via the page's own AJAX endpoint `POST https://www.ungm.org/Public/ContractAward/PublicSearch`
  (JSON body with `Countries:[2382]` Honduras / `[2354]` El Salvador, `Title`, `AwardFrom`, `PageIndex`; header `RequestVerificationToken` from the page).
  Detail page `https://www.ungm.org/Public/ContractAward/<id>` gives organisation, reference, award date, **contract value USD**, short description.
  Limits: max 24 pages × 15 rows per query; the country filter also returns "Multiple destinations" global LTAs; the server returns HTTP 429
  when hit hard, so a full month-by-month crawl was abandoned after 2019–mid-2021 (HN) / Jan–Apr 2019 (SV) and replaced by title-keyword
  searches (≈40 Spanish/English keywords per country, 2019→). UNOPS publishes its awards here (it ran large SESAL/IHSS purchasing in Honduras).
  Keyword list (title "contains"): reactiv, prueba(s), laborator(y), diagn, glucosa, glucómetro, tiras, VIH/HIV, PCR, COVID, test, reagent,
  hemat, química, microscop, malaria, dengue, tuberculosis, Xpert, cartucho, insumos (médicos), material médico, equipo médico,
  dispositivos médicos, medical, hospital, IHSS, ISSS, Secretaría de Salud, SESAL, MINSAL, sangre, banco de sangre, lanceta, analizador,
  In Vitro, determinación, kit, carga viral, genotip, citometr, hepatitis, sífilis, molecular, biología, VPH/papiloma, influenza, tamizaje,
  ITS, glicada/HbA1c, insulina. Then fetched 546 award detail pages (all country-specific medical/lab hits) to read lot descriptions/values.
  **UNGM results (5 rows)**: El Salvador – UNDP-SLV-00248 molecular CT/NG/HSV tests (Scientific Instruments, USD 988,269, Aug-2024) and
  UNDP-SLV-00246 CD4/CD8/CD3/CD45 flow-cytometry tests (Diagnostika Capris, USD 198,000, Nov-2024); Honduras – UNOPS for IHSS glucose test
  strips lot (Nipro, USD 24,128, Apr-2019), UNOPS hematology analyser (UNFPA funds, USD 6,747, Aug-2025), UNOPS BPA lot "Cintas Reactivas
  para Orina" (Nipro, nominal USD 10, Jul-2025).
  Not in CSV: ~500 UNOPS-for-IHSS "Material Médico Quirúrgico"/medicines/equipment-LTA award lots (2019–2026) – lot descriptions read,
  none are IVD (endotracheal tubes, X-ray film, urine *collection* bags, cautery etc.); UNOPS 2019 equipment purchases for the UCSF-E
  Soyapango and ISSS San Miguel hospital (El Salvador) – some awarded to "EQUIPOS PARA LABORATORIOS, S.A." but award pages only say
  "Contratación por Excepción N para el Suministro de Equipo Médico Hospitalario" (USD 1k–15k each) – could hide small lab equipment.
  Open notices: UNGM active-notice search (`POST /Public/Notice/Search`) shows a UNOPS LTA "Adquisición de Dispositivos Médicos y Dispositivos
  Médicos para Diagnóstico In Vitro a través de Acuerdos a Largo Plazo (LTA)" (notice 315716, Oct-2026) tagged to Honduras, but its detail
  page returned HTTP 429 at the time of the run – destination/country and items NOT verified, so not in CSV (worth a manual look:
  https://www.ungm.org/Public/Notice/315716).
  Caveat: UNGM only shows awards the agency chose to publish (UNOPS mostly ≥ USD 30k or all eSourcing lots; UNDP selectively); values are
  per-lot contract values, no quantities/unit prices.
- **UNOPS open data portal** (`data.unops.org`, API `api.data.unops.org/api/v1/...`): reachable but only has project/delivery data – **no procurement or contract-award data**.
- **UNICEF Supply**: annual-report annex PDFs are behind a Cloudflare challenge (not bypassed); they only give country totals anyway, not products.
- UNDP: awards appear in UNGM (few lab items for HN/SV found).

## 5. PAHO Strategic Fund

**No public per-country purchase data found.** PAHO publishes product lists/price catalogues and success stories, not country-level award data.
PAHO awards on UNGM are global LTAs (not country specific). Nothing added to the CSV.

## 6. Other

- BCIE (Central American Bank for Economic Integration) donated PowerChek 2019-nCoV real-time PCR kits in April 2020 (search snippets of the BCIE press
  release say 182,000 tests for the SICA countries, ~26,000 per country, plus extraction kits worth USD 148,500 region-wide). bcie.org was "en
  mantenimiento" and the CSUCA report URL timed out, so the figures could not be verified at source – **not put in the CSV** (lead only).
- USAID/GHSC-PSM shipment data and PEPFAR/CDC lab procurement: no current public line-level source reachable (data.usaid.gov offline) – nothing added.
- Global Fund PR tender pages (CHF/Global Communities in Honduras, Plan International / MINSAL in El Salvador): no public tender listings found;
  their purchases are captured by PQR above.

---------------------------------------------------------------------------------------------------

## Row counts in donor_raw.csv (123 rows)

| Source | Honduras | El Salvador | Notes |
|---|---|---|---|
| Global Fund PQR | 36 | 27 | line level (qty, pack price, total, supplier, manufacturer, PO date); 2019-2025 |
| World Bank (contract awards + notices + STEP plans) | 0 | 26 | 20 awarded contracts/lots, 1 cancelled, 1 open, 4 planned |
| IDB (notices + awards datastore) | 13 | 16 | HN = line level with unit prices; SV = contract/article level; 1 open |
| UNGM (UNOPS / UNDP awards) | 3 | 2 | contract value + one-line description |
| PAHO / UNICEF / other | 0 | 0 | not reachable / no country-level data |

Status mix: Orden de compra 64 (all PQR + 1 WB PO), Contratado 45, Adjudicado 7 (incl. 1 BPA), Open 2, Planned 4, Cancelled 1.
Published totals summed (mixed award levels, do NOT treat as market size): El Salvador ≈ USD 14.4 M; Honduras ≈ USD 1.27 M + HNL 14.0 M.

## Biggest caveats
1. Honduras has very little donor-financed IVD visible: no WB lab goods (outside the already-known P176532 line), one IDB PCR-reagent
   tender (2023), Global Fund RDT/CD4 purchases (USD 0.27 M 2019-2025; El Salvador USD 0.82 M), and a few UNOPS items. The large UNOPS/UNDP programmes for
   SESAL/IHSS/Hospital Escuela publish lot titles only; no IVD lots were identified among ~500 award pages.
2. World Bank and most IDB data are lot/contract level – item lists come from the tender notice (tendered quantities, not delivered),
   and per-item prices are not published. Several contracts (FARLAB/NIPRO "lotes", RES-COVID-40 articles, ES-G1003 items) have no
   product description at all.
3. Global Fund PQR values are the formatted display values of the public viz (totals rounded to USD 1). PQR covers only what PRs report
   (diagnostics bought nationally with co-financing are not there).
4. The El Salvador anaemia (HemoCue) and gas-analyser rows are partly inferred from tender item lists (analyte type of the "Analizador
   de gases, portátil" is not stated; CSJ-107 contract may include non-IVD lot 2 consumables).
5. Rows marked BORDERLINE (lab cold storage, biosafety/PCR cabinets, water baths, laminar flow, molecular workstation) are general lab
   equipment – keep or drop according to the market definition.
6. Not reached: IDB contract-awards CSV (AWS WAF challenge – datastore API used instead), projectprocurement.iadb.org (HTTP 526),
   UNICEF supply annexes (Cloudflare), bcie.org (maintenance), Global Fund v3 OData (blocked), PAHO SF country data (not published).

## Files in this folder
- donor_raw.csv – deliverable; donor_notes.md – this file
- build_gf.py / build_wb.py / build_idb.py / build_ungm.py / merge.py – row builders (re-runnable)
- gf_pqr_rows.json – all PQR diagnostic-category transactions HN+SV 2008-2025 (incl. pre-2019 and PPE lines not in CSV)
- wb_contract_awards_hn_sv.json, wb_procnotices_hn_sv.json, wbnotices/*.txt, pp/*.pdf|txt – World Bank raw pulls
- idb_notices.csv, idb_awards_hn_sv.json, idbdocs/* – IDB raw pulls
- ungm_kw.json, ungm_details.json, ungm_awards_all.json – UNGM raw pulls
