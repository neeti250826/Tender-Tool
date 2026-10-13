# South Africa NDoH Status (2026-06-18)

- Source URL: `https://www.health.gov.za/tenders/`
- Extractor file: `harness/sources/south_africa_ndoh.py`
- Output file: `South Africa/health-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
- Source mode: Mixed. The extractor fetches the live tenders page and live award notice files first, then falls back to saved evidence under `evidence/` when a request fails.
- Verified row count: `17`
- Publication-date coverage: `2024-01-19` to `2025-09-12`
- Fill counts:
  - `awarding_supplier_name`: `16/17`
  - `awarded_value`: `11/17`
  - `item_desc`: `17/17`
  - `contract_period`: `17/17`
  - `notice_url`: `17/17`
- Strong data: notice URLs, item descriptions, and contract periods are complete in the current CSV; supplier names are present for all but one row.
- Caveat: awarded values are missing for `6` rows, so award-value coverage is partial even though the rows are present and the publication-date coverage starts in 2024.
