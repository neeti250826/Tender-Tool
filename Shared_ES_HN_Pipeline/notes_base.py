"""Static parts of the Sources & notes tab; build_notes() merges in agent notes and live counts."""

METHOD = [
    ("Scope", "Core Lab (CDx), POC, MDx, TDx, NGS, Diabetes Care (BGM, CGM) – every line of the keyword map. Period 2019–2026 (to 7 Oct 2026). "
              "Exclusions applied as in the brief (construction, building maintenance, medical gases/oxygen, water/soil/food/veterinary testing, "
              "psychology, school/computer labs), plus: medicines and IV fluids, customs/freight services, generic lab equipment (autoclaves, "
              "microscopes, centrifuges unless blood-bank), blood-collection tubes/needles/gloves, printed forms, waste disposal, outsourced "
              "lab-testing services for employees, electrosurgery 'coagulación' electrodes, blood bags / apheresis kits / leucoreduction filters, "
        "reagent-grade lab chemicals (except histology fixatives and clearing agents for pathology, coded TDPRE), and general lab "
        "equipment (freezers, cabinets, water baths). Analyser lent on comodato inside a reagent line is not coded as an instrument purchase."),
    ("Indicator code", "Most specific code the text supports. If a line names products from several segments, it gets their nearest common "
                       "parent (e.g. haematology + chemistry reagents -> CDXZZ) and every specific code is listed in 'All matched codes'. "
                       "If the products span top-level segments with no common parent, the most specific code is used and confidence is 'Low'."),
    ("Watch-outs handled", "'PCR': molecular unless the text says proteína C reactiva / látex / cuantitativa / ultrasensible (then IACRP, or PCCRP if rapid). "
                           "'Tiras reactivas': urine (URQUA) if orina/parámetros/nitrito, glucose otherwise. Rapid version beats lab version of the same "
                           "analyte; molecular beats both. Blood-bank context turns HIV/HBV/HCV/syphilis/Chagas serology into IABSC. Xpert/GeneXpert "
                           "cartridges -> POC molecular codes (per the map's POC rule)."),
    ("Glucose strips (BGM vs hospital POC)", "Map notes conflict (HGNZZ 'hospital use in wards' vs DBSPU 'public tenders = this line'). Rule used: strips/meters "
                                             "bought by a hospital (non-social-security) -> HGNZZ; bought by ministries, regions, primary care, FOSALUD or "
                                             "social security, or with patient-dispensing wording -> DBSPU. Lancets -> DBLPU. CGM -> DICPU. Retail, "
                                             "e-commerce and private lines left blank as instructed."),
    ("COVID rapid tests", "PCOVH / PCOVC / PCOVN assigned by buyer type (hospitals / primary care & regions / non-health bodies). PCOVR not used."),
    ("Tag confidence", "High = one specific code from explicit wording. Medium = common parent of several codes, or a parent-level code. "
                       "Low = products span segments with no common parent – check before slotting."),
    ("Buyer segment", "Derived from the buyer name. Non-health buyers and non-clinical labs (environment, energy, food, regulators) keep only "
                      "point-of-care tests and diabetes supplies (e.g. COVID tests for staff); their lab reagents are excluded. Academic / research "
                      "buyers are kept but labelled so they can be filtered out."),
    ("Currency", "Values are as published: Honduras national sources in HNL (lempiras), El Salvador and donor sources in USD (one IDB Honduras "
                 "lot in HNL). No FX conversion applied."),
    ("Values", "Honduras: Total = quantity × unit price unless a CHECK / 'derived' comment says otherwise (published unit prices that were really "
               "line totals were corrected against the contract value). El Salvador new COMPRASAL: sum of the supplier's awarded lines in the process. "
               "Legacy El Salvador and donor rows: published totals."),
    ("Not in scope", "BGM/CGM retail pharmacy, e-commerce and private-hospital lines are left blank as instructed (they are not tendered)."),
]

HONDURAS = [
    ("HonduCompras 1 – ONCAE open data (OCDS)", "https://oncae.gob.hn/datos-abiertos/ – yearly files HC1_datos_2019…2026 (traditional procedures: licitaciones, "
        "concursos, compras menores, contratación directa; last refreshed 6 Oct 2026). Line-level: item description, UNSPSC class, quantity, unit price, "
        "supplier, contract value and signing date. One row per awarded item line. The buyer field is 'Institution – purchasing unit'."),
    ("HonduCompras Catálogo Electrónico", "Same portal, CE_datos files (framework-agreement purchase orders). In-scope items appear only in 2020–2021 "
        "orders, mostly from the COVID-19 emergency catalogue (rapid tests, glucose strips). The buyer is the institution from the parties table."),
    ("Difusión Directa de Contratos", "DDC_datos_2019 – 22 contracts from one hospital whose titles are only contract numbers (no product text), so "
        "they cannot be classified and are not included. The dataset stops in 2019."),
    ("Open / in-process tenders", "Tenders in the same files with status 'active'/'planned' and no award, published in 2026 or closing from Sep 2026, "
        "listed on the 'Open tenders' tab with their tender item lines."),
    ("HonduCompras 2 (h2.honducompras.gob.hn)", "The host no longer exists (DNS: non-existent domain, checked against Google and Cloudflare DNS). ONCAE's "
        "site now links the SICC historical search (sicc.honducompras.gob.hn) – it was used only to confirm "
        "that IHSS processes exist – they are in the open data, listed under IHSS's purchasing units (Unidad Central, Hospital de Especialidades…)."),
    ("datosabiertos.oncae.gob.hn / contratacionesabiertas.gob.hn", "The data portal root is a login page; the yearly files above are public. "
        "contratacionesabiertas.gob.hn (OCDS portal) times out from outside Honduras – not needed because the same OCDS data is in the yearly files."),
    ("Coverage caveats", "IHSS appears mainly through small direct purchases (glucose/urine strips, culture discs, formalin); its large reagent-rental "
        "licitaciones are not itemised in the open data. Many hospital purchases arrive as one 'item' listing a whole lab order – these are flagged "
        "'Multi-product line' and their quantity/price is for the lot. 2023 has far fewer item lines than other years in the source data itself."),
    ("Portal Único IAIP, SESAL, IHSS websites", "portalunico.iaip.gob.hn returns HTTP 403 (bot protection) to this connection; ihss.hn and salud.gob.hn load "
        "but publish no award data beyond what is in HonduCompras."),
]

EL_SALVADOR = [
    ("COMPRASAL – public awards API", "https://www.comprasal.gob.sv/api/v1/publico/obtener/procesos/publicos – all 133,729 published award lines (Oct 2024 – "
        "5 Oct 2026, the new system under the Ley de Compras Públicas). Gives process title, codes, method, award date, supplier and amount per awarded line, "
        "plus process detail (publication date, total awarded) and award report (contract term, planned budget, bidders)."),
    ("What COMPRASAL does NOT publish", "Item names, quantities and unit prices – these sit behind a supplier/institution login, so El Salvador rows are one per "
        "process × supplier, coded from the tender title (Tagged from = 'title'). Most hospital lab tenders are titled generically "
        "('reactivos e insumos de laboratorio clínico') and therefore carry the parent code CDXZZ."),
    ("Open tenders", "https://www.comprasal.gob.sv/api/v1/publico/obtener/procesos/disponibles – processes currently in progress (491 on 7 Oct 2026)."),
    ("2019 – Sep 2024 (old COMPRASAL / LACAP era)", "Not in the new system's public API – see the El Salvador legacy section below."),
    ("COVERAGE GAP: May 2023 – Oct 2024", "Neither system publishes awards for this window: the legacy COMPRASAL API ends around mid-2023 (only a "
        "dozen awards a month after April 2023) and the new COMPRASAL's first award is dated 30 Oct 2024. El Salvador 2023 and 2024 are therefore "
        "incomplete (2024 has ~12 award rows) – do not read them as a demand drop."),
    ("salud.gob.sv, asp.salud.gob.sv, transparencia.gob.sv", "HTTP 403 to this connection (bot protection) – see the legacy section for what could be "
        "recovered through other routes."),
]
