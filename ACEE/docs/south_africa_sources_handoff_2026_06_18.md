## South Africa Extractable Sources Handoff

Date: 2026-06-18

This repository currently has seven runnable South Africa extractor modules across six public source domains that can produce awarded medical or healthcare rows for the publication window starting `2024-01-01`.

### Extractable local sources

1. `data.etenders.gov.za`
   - Source module: `harness/sources/south_africa_etenders.py`
   - Output file: `South Africa/data-etenders-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18_live_detail_ps2000.csv`
   - Extraction mode: public OCDS API plus attachment parsing
   - Verified rows: `120`

2. `health.gov.za`
   - Source module: `harness/sources/south_africa_ndoh.py`
   - Output file: `South Africa/health-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
   - Extraction mode: public HTML plus award notice documents
   - Verified rows: `17`

3. `echealth.gov.za`
   - Source module: `harness/sources/south_africa_echealth.py`
   - Output file: `South Africa/echealth-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
   - Extraction mode: public award listing plus OCR of scanned award PDFs
   - Verified rows: `11`

4. `premier.nwpg.gov.za`
   - Source module: `harness/sources/south_africa_nwpg_premier.py`
   - Output file: `South Africa/premier-nwpg-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
   - Extraction mode: public tender bulletin PDF parsing
   - Verified rows: `7`

5. `ldoh.gov.za`
   - Source module: `harness/sources/south_africa_ldoh.py`
   - Output file: `South Africa/ldoh-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
   - Extraction mode: public awarded-tenders page plus public PDF award notices
   - Verified rows: `36`

6. `kznhealth.gov.za` tender-awards pages
   - Source module: `harness/sources/south_africa_kznhealth.py`
   - Output file: `South Africa/kznhealth-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
   - Extraction mode: public awarded pages plus public PDF award notices
   - Verified rows: `50`

7. `kznhealth.gov.za` quotation-awards pages
   - Source module: `harness/sources/south_africa_kznhealth_quotations.py`
   - Output file: `South Africa/kznhealth-gov-za-quotations/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
   - Extraction mode: public quotation-awards month pages plus OCR of public quotation-award PDFs
   - Verified rows: `670`

### Combined output

- Combined file: `South Africa/medical_awarded_rows_2024_01_01_to_2026_06_18_all_sources.csv`
- Total rows: `911`
- Publication date coverage: `2024-01-19` through `2026-06-17`
- Domain-level source breakdown:
  - `data.etenders.gov.za`: `120`
  - `health.gov.za`: `17`
  - `echealth.gov.za`: `11`
  - `premier.nwpg.gov.za`: `7`
  - `ldoh.gov.za`: `36`
  - `kznhealth.gov.za`: `720`

### Field coverage in the combined file

- `awarding_supplier_name`: `859` rows filled
- `awarded_value`: `808` rows filled
- `item_desc`: `911` rows filled
- `item_uom`: `86` rows filled
- `item_quantity`: `7` rows filled
- `item_unit_price`: `7` rows filled
- `item_award`: `723` rows filled
- `contract_period`: `174` rows filled
- `notice_url`: `911` rows filled

### Current caveat

The current authoritative combined file was rebuilt by reusing the already-verified `data.etenders.gov.za` export together with fresh or already-verified simple-source outputs, including the new KZN quotation-awards module. A live Playwright check on the KZN tender-awards pages and the KZN quotation-awards landing page found no hidden pagination or infinite scroll. The quotation-awards source is now the largest South Africa uplift, but a minority of scanned PDFs still leave supplier or value partially blank when the OCR line break quality is weak.
