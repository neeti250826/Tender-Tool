## South Africa Eastern Cape Health status as of 2026-06-18

- Source URL: `https://www.echealth.gov.za/index.php/tenders/tender-award-s`
- Extractor file: `harness/sources/south_africa_echealth.py`
- Output file: `South Africa/echealth-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`

Verified current output:
- Row count: `11`
- Publication date coverage: `2024-06-19` to `2025-05-20`
- `awarding_supplier_name` filled: `11/11`
- `awarded_value` filled: `2/11`
- `item_desc` filled: `11/11`
- `contract_period` filled: `11/11`
- `notice_url` filled: `11/11`

Extractor status:
- OCR-dependent: yes. The module renders/downloads PDF award notices and runs Tesseract via `C:\Program Files\Tesseract-OCR\tesseract.exe`.
- Fetch mode: mixed, live-first with saved-evidence fallback. The listing HTML is fetched live when possible and falls back to `evidence/echealth_tender_awards_live.html`; notice PDFs are fetched live when possible and otherwise read from saved evidence files when present.

What is strong in the current output:
- Supplier names, item descriptions, contract periods, and notice URLs are present for every row in the current CSV.
- Publication dates are populated for every current row and come from the listing metadata parsed by the extractor.

Caveat:
- `awarded_value` is sparse in the current output (`2/11`), and extraction quality depends on OCR readability of the source PDFs.
