# South Africa eTenders Status (2026-06-18)

- Source URL: `https://ocds-api.etenders.gov.za/api/OCDSReleases`
- Extractor file: `harness/sources/south_africa_etenders.py`
- Output file: `South Africa/data-etenders-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18_live_detail_ps2000.csv`
- Source mode: Live OCDS release API in the extractor, with full-scrape fallback reuse when a refreshed run produces no rows.
- Verified row count: `120`
- Publication-date coverage: `2024-01-27` to `2026-05-28`
- Fill counts:
  - `awarding_supplier_name`: `120/120`
  - `awarded_value`: `120/120`
  - `item_desc`: `120/120`
  - `item_uom`: `86/120`
  - `item_quantity`: `7/120`
  - `item_unit_price`: `7/120`
  - `item_award`: `7/120`
  - `contract_period`: `65/120`
- Strong data: award-backed supplier names, awarded values, and item descriptions are complete in the current CSV; item UOM is present for most rows and contract period is present for over half.
- Caveat: the `2026-06-18` full-scrape run did not keep new live rows. The chunk directory `South Africa/data-etenders-gov-za/chunks_2024_01_01_to_2026_06_18_live_detail_ps2000` currently has `30` CSV files with `0` total rows, so the wrapper reused fallback evidence from `South Africa/data-etenders-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_16_live_detail_ps2000.csv`, which also has `120` rows.
