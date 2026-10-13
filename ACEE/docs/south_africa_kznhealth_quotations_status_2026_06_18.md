## South Africa KZN Department of Health quotation-awards status as of 2026-06-18

- Source URL:
  - `https://www.kznhealth.gov.za/scm/quotation-awards/`
- Extractor file: `harness/sources/south_africa_kznhealth_quotations.py`
- Output file: `South Africa/kznhealth-gov-za-quotations/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
- Run shape: live-first with saved-evidence fallback and cached OCR text under `evidence/`. The extractor discovers linked month pages from the quotation-awards landing page, parses the HTML tables, filters medical or healthcare descriptions before OCR, then OCRs the public quotation-award PDFs to recover supplier, amount, and notice id.

Playwright verification:

- The live quotation-awards landing page does not expose pagination or infinite scroll controls.
- The landing page links directly to month pages for `August 2025` through `June 2026`.
- The month pages render award rows directly in HTML tables with four visible columns: PDF, institution, description, and date.

Verified output:

- Row count: `670`
- Publication date coverage: `2024-05-28` to `2026-06-17`
- `awarding_supplier_name` filled: `642/670`
- `awarded_value` filled: `636/670`
- `item_desc` filled: `670/670`
- `contract_period` filled: `48/670`
- `notice_url` filled: `670/670`

Saved evidence:

- `evidence/kzn_quotation_awards_landing_live.html`
- `evidence/kzn_quotation_awards_april_2026_live.html`
- `evidence/kzn_quote_MSH12-26-27H.pdf`
- `evidence/kzn_quote_MSH12-26-27H.txt`

Broader medical or healthcare quotation families now captured:

- surgical items and surgical gowns
- masks, gloves, gauze, syringes, needles, and catheters
- neonatal, paediatric, respiratory, and ventilator consumables
- maternity sanitary pads and maternity-related supplies
- radiology, physiotherapy, audiology, occupational therapy, and speech-therapy needs
- oxygen plants, medical gas plants, vacuum plants, and suction systems
- mortuary-related repair or service work
- dialysis water treatment, medical waste handling, and other directly healthcare-operational services

Caveat:

- A minority of scanned quotation PDFs still have weak OCR around the supplier or amount lines, so `28` rows remain blank on supplier and `34` remain blank on awarded value even though the notice URLs and item descriptions were recovered.
