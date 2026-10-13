# El Salvador – legacy (pre-new-COMPRASAL) IVD / diabetes-monitoring procurement – source notes

Output: `es_legacy_raw.csv` (7,453 rows, UTF-8, exact RAW_SCHEMA columns). Work folder also holds every award/contract PDF used
(`pdf/cs/` = 2,188 COMPRASAL documents, `pdf/minsal/` = 38 MINSAL resolutions from Wayback, `pdf/conv/` = Word contracts converted to PDF,
`ocr/` = Tesseract output + page images) and the scripts (`py/`).

## Headline
* **Main find: the legacy COMPRASAL II back-end API is still live and public from this PC** –
  `https://unacv2.mh.gob.sv/comprasalmicro/...` (no login, no captcha). It holds every process published 2019 → mid-2023 with
  supplier-level award amounts and the uploaded documents (bases, award resolutions, contracts, purchase orders).
  This is the backbone of the file (5,604 rows + it cross-references the MINSAL rows).
* transparencia.gob.sv and salud.gob.sv are **Cloudflare-blocked ("Sorry, you have been blocked", HTTP 403)** from this PC *and* from WebFetch.
  I did not try to get around the block; only existing Wayback Machine captures were used.
* ISSS website has **no procurement section** any more (2019–2026). Nothing usable there.

## Row counts (year = award_date, else publication_date)
| source_portal | 2018* | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2026 | total |
|---|---|---|---|---|---|---|---|---|---|
| COMPRASAL (legacy) public API – line rows (parsed from award resolutions / contracts) | 0 | 511 | 527 | 856 | 609 | 438 | 0 | 0 | 2,941 |
| COMPRASAL – supplier-level award rows (montoAdjudicado) | 1 | 689 | 652 | 447 | 519 | 410 | 1 | 0 | 2,719 |
| COMPRASAL – computed residual rows (supplier total minus itemised OCR lines) | 0 | 1 | 4 | 5 | 12 | 5 | 0 | 0 | 27 |
| COMPRASAL – tender-only rows (no award registered: "Gestion de la Compra", desierto, sin efecto) | 1 | 268 | 266 | 489 | 297 | 49 | 0 | 0 | 1,370 |
| Wayback – salud.gob.sv UACI resoluciones (MINSAL central), line level | 0 | 25 | 0 | 8 | 195 | 0 | 0 | 0 | 228 |
| Wayback – salud.gob.sv UCP/UGPPI resoluciones (World Bank project), line level | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 8 | 16 |
| Portal de Transparencia (Wayback CSV exports) – contract/OC level | 0 | 114 | 11 | 18 | 9 | 0 | 0 | 0 | 152 |
| **Total** | 2 | 1,608 | 1,460 | 1,823 | 1,641 | 902 | 9 | 8 | **7,453** |

*2018 = processes published late 2018/early 2019 that the date filter picked up.
Awarded value in file ≈ USD 117 M (2019 21.2 M; 2020 14.8 M; 2021 22.6 M; 2022 29.6 M; 2023 26.2 M; 2024–26 2.8 M) – **this is gross, before
dedupe and before removing non-IVD lines** (see caveats). By buyer: MINSAL hospitals 37.4 M, ISSS 41.7 M (incl. 6.8 M transparencia rows that
overlap COMPRASAL), MINSAL central 30.1 M, IML/Órgano Judicial 3.6 M, ISBM 1.7 M, MDN/Hospital Militar 1.6 M, FOSALUD 0.6 M.
Line-level value ≈ 30 M of the 117 M; the rest is supplier-level.

## 1. Legacy COMPRASAL (COMPRASAL II, 2019–mid-2023) – REACHABLE, primary source
How found: Wayback capture of `https://www.comprasal.gob.sv/comprasalweb/main.*.js` (Angular SPA) → API base `https://unacv2.mh.gob.sv/comprasalmicro`.
Endpoints that worked (plain GET/POST, JSON):
* Search: `POST /portalpublico/api/v1/procesos` body `{"nombreProceso":"","fechaInicio":"2019-01-01","fechaFinal":"2019-06-30","tiposProceso":["LIC","CDI","CLG","CEM","OTR"],"obsProcesos":[],"instituciones":["3201"],"estadosProceso":[],"tipoFecha":"fechaPublicacion","columna":"fechaPublicacion","orden":"DESC","page":1,"size":1000}`
* Institutions: `GET /comprasalii/api/v1/instituciones/vigentes?page=1&size=400&criteria=` (428 institutions; health codes 3200–3237, ISSS 3303, ISBM 3107, MDN 0900, CEFAFA 0902, Órgano Judicial 1600)
* Process detail: `GET /portalpublico/api/v1/procesos/procesos/{idProceso}` (dates, fuente de financiamiento, resultado)
* Awards: `GET /portalpublico/api/v1/adjudicaciones/{idProceso}` (supplier + montoAdjudicado; `/adjudicaciones/cem/{id}` for emergency buys)
* Documents: LIC/CDI/OTR `GET /licitaciones/api/v1/documentos/instituciones/{inst}?codProceso={cod}`; CLG `GET /libregestion/api/v1/documentos/instituciones/{inst}/procesos/{cod}`; download `GET /moddiv/api/v1/documentos/download/{idDocumento}`
* Contract/OC per supplier: `GET /moddiv/api/v1/documentos/proveedores/{codProveedor}/instituciones/{inst}?codProceso={cod}` and download `.../moddiv/api/v1/documentos/download/proveedores/{codProveedor}/instituciones/{inst}?codProceso={cod}&nomDocumento={name}`
Coverage: data ends ~mid-2023 (2023 has only 2,083 processes for these buyers; 2024+ = 0) – i.e. it hands over exactly where the new COMPRASAL starts.
Process: enumerated **42,923 processes 2019-01-01→2023-12-31 for 45 health buyers** → keyword filter (reagents, pruebas, laboratorio, banco de sangre,
patología, PCR, VIH, glucosa/tiras/lancetas, comodato, etc. with exclusions for construction, A/C, oxygen, water/soil analysis, vehicles, drugs,
neonatal incubators, surgical microscopes) → **2,596 candidate processes** (DNM 3236 and CEFAFA 0902 excluded: pharmaceutical QC/manufacturing labs).
For each: awards + documents. 2,189 award/contract/OC documents downloaded (2,188 OK). Parsing: 1,015 text PDFs (PyMuPDF table extraction),
85 Word contracts (converted via Word → PDF), 61 ISSS scanned contracts with OCR text layer (word-position parser), 845 image-only scans (not parsed).
Line rows are kept only when they reconcile with COMPRASAL's award amount (resolution total ±2%, or per-supplier contract ±5%); otherwise the
supplier-level amount is kept (and, for ISSS OCR contracts, the consistent lines + a clearly labelled computed residual).
Fields provided: buyer, process code/type, title, publication date, result date, status, funding source, supplier, awarded amount; line rows
add item text (verbatim, includes "Se adjudica/ofrece" text), brand/model, qty, U/M, unit price, line total, MINSAL code (in comments).
Best line-level coverage: Hospital Rosales (resoluciones de adjudicación are text PDFs that reconcile to the cent), Nueva Concepción,
Sonsonate, Cojutepeque (Word contracts), Ilobasco, San Miguel, IML, Gotera, ISSS (partial, OCR).

## 2. MINSAL salud.gob.sv – BLOCKED live (403 Cloudflare, curl and WebFetch); Wayback works
* Pages: `https://www.salud.gob.sv/adjudicaciones-2019/`, `-2020/`, `-2021/`, `-2022/`, `/adjudicaciones-ucpcsj/` (captures 2019–2026; `adjudicaciones-2023` capture is empty).
  238 resolutions listed, 47 lab-related. PDFs under `/archivos/pdf/uaciYYYY/resoluciones/res_adjudNNYYYY/res_adjudNNYYYY-sig.pdf`.
  2019, 2021, 2022 and UCPCSJ PDFs are archived; **2020 PDFs are not archived** (only res_adjud162020).
* PDFs are scans → Tesseract (eng) OCR + visual check of page images. Transcribed to line level (all totals checked against the published totals):
  22/2019 (HIV viral load Abbott m2000 + Seegene Allplex STI/HPV), 53/2019 (HBV/HCV viral load), 17/2019 (rapid tests HIV/syphilis/HBV/HCV),
  16/2019 (BD CD4, Roche HIV combi/HBsAg/HCV/syphilis/toxo with comodato), 66/2021 (viral load + CD4), 129/2021 (Abbott Architect HIV/syphilis/toxo),
  71/2022 (Determine HIV, Abbott syphilis rapid), 75/2022 (LNSP reagents, 193 lines from the one text PDF), and 2024–2026 World-Bank (BIRF 9065-SV)
  awards 02/2024 & 29/2024 (HemoCue anemia screening), 14/2024 (Revvity hemoglobinopathy screening + lab equipment), 016/2026 (Revvity neonatal
  screening, Beckman Access thyroid, ELITech sweat chloride). These replace the matching COMPRASAL supplier rows (no double counting).
* Not transcribed (OCR consumables lists, mostly PPE/plastics; COMPRASAL supplier rows cover them): 09/2019, 48/2019, 41/2019 (72 pp), 25/2019 (255 pp),
  02/2021, 05/2021, 170/2021, 38/2022 (666 pp), 39/2022 (218 pp), 65/2022, 84/2022, 54/2022, 89/2022.

## 3. Portal de Transparencia – BLOCKED live (Cloudflare 403; WebFetch 403); Wayback CSV exports used
* `https://web.archive.org/web/20220829215052/https://www.transparencia.gob.sv/institutions/minsal/contracts.csv?&institution_id=minsal`
  (3,646 MINSAL central contracts 2012→Aug-2022; contract-level: objeto, código, monto, contraparte, fecha, forma, nº contrato/OC; no item lines, no doc URLs) → 91 rows.
* `https://web.archive.org/web/20190722144703/https://www.transparencia.gob.sv/institutions/isss/contracts.csv?doc=&institution_id=isss`
  (truncated by Wayback at 1 MB: Jun-2018→Jun-2019; ISSS libre-gestión rows are item-level) → 61 rows (2019 only).
* Hospital institution pages (h-rosales, h-bloom, …) have no contracts.csv captures; contract-detail pages captured only sporadically.
* `en_covid19` page/CSV captures are mostly normative documents; the MINSAL COVID purchase list captured (May 2020, 30 OCs) has only two small lab items.
* These rows can duplicate COMPRASAL rows for the same procurement (flagged in comments: dedupe on procedure_no + supplier).

## 4. ISSS website (www.isss.gob.sv) – REACHABLE, nothing usable
WordPress; REST API returns 401 (auth required). Sitemaps: 959 downloads (forms, fichas técnicas de medicamentos, manuals) – no UACI/compras,
no award resolutions, no listings 2019–2026. Old `/uaci/*.asp` + `uploaded/LPG….pdf` exist on Wayback only for 2005–2007. 0 rows.
(ISSS awards are covered via COMPRASAL: 194 candidate processes; contracts are scanned+OCR, 2022–2023 mostly.)

## 5. Other
* `www.datosabiertos.gob.sv` – no connection. No national open-data procurement dataset found.
* Old COMPRASAL module (`/comprasal_web/`, `/moddiv/HTML/…`) Wayback captures are 2007–2014 only.
* COVID 2020–21: covered through COMPRASAL CEM (compras de emergencia) and RES-COVID (World Bank) processes, e.g. MINSAL CEM-CDEEM 28-2020
  "insumos de laboratorio" (USD 3.54 M, supplier level), viral transport media/swabs, LPI-RES-COVID-43 PCR tests (USD 678 k), ISSS CD-004/2021-G COVID
  testing service (USD 3.76 M). Regional civil-society report (revistazo.com "Compras de COVID-19 TNCA") has no El Salvador line data. Corte de Cuentas
  reports not retrieved (cortedecuentas.gob.sv not tried in depth).
* Open tenders: none – the legacy system closed mid-2023; nothing "vigente" remains.

## Caveats for the consolidator
* Mixed tenders: hospital "insumos médicos y de laboratorio" tenders include non-IVD lines (catheters, gauze, PPE). 1,154 line rows carry
  "SCOPE FLAG: this line looks non-IVD" in comments (≈ USD 5.0 M) – filter before sizing. Also lab-equipment maintenance services, LNSP food/water/drug-QC
  reagents, blood-bank bags/apheresis kits and outsourced lab-test services are kept and labelled by their own text.
* 1,370 tender-only rows have no supplier/amount (no award registered in COMPRASAL – mostly Hospital Bloom libre gestión).
* ISSS OCR lines: text has OCR errors; qty/unit price blanked when inconsistent with the line total; 27 rows are COMPUTED residuals (labelled).
* award_date = COMPRASAL "fecha de resultado" (or resolution date / contract-OC date for Wayback/transparencia rows) – stated per row.
* Amounts are as published (some MINSAL Global Fund lines are VAT-exempt while Fondo General lines include IVA – noted per row).
* Biggest gaps: (a) line detail for ISSS 2019–2021 (no contract documents uploaded) and for the 845 image-only PDFs (OCR possible but not done);
  (b) MINSAL 2020 resolution PDFs (not archived); (c) transparencia.gob.sv hospital-level contract listings (blocked, not archived);
  (d) ISSS/MINSAL glucose strips & glucometers – mostly bought inside generic "insumos médicos" tenders that the keyword filter does not catch
  (only hospital-level strip/lancet purchases appear).
