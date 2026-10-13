## South Africa North West Premier status as of 2026-06-18

- Source URL: `https://premier.nwpg.gov.za/tenders/`
- Extractor file: `harness/sources/south_africa_nwpg_premier.py`
- Output file: `South Africa/premier-nwpg-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
- Run shape: mixed live-first plus saved evidence fallback. The extractor fetches the live tender index when reachable, falls back to `evidence/nwpg_premier_tenders_live.html` on request failure, and downloads bulletin PDFs with per-PDF evidence fallback.
- PDF dependency: yes. Award rows are parsed from tender bulletin PDFs with `fitz`.

Verified output:

- Row count: `7`
- Publication date coverage: `2025-11-25` to `2025-11-25`
- `awarding_supplier_name` filled: `7/7`
- `awarded_value` filled: `3/7`
- `item_desc` filled: `7/7`
- `contract_period` filled: `5/7`
- `notice_url` filled: `7/7`

Strong data:

- Supplier names, item descriptions, and notice URLs are complete for all rows.
- The buyer is consistently the North West Department of Health.
- Numeric awarded values are present where the bulletin exposes them as parseable amounts.

Caveat:

- Coverage currently comes from one health term contract award bulletin dated `2025-11-25`, so the South Africa 2024-to-recent window is sparse for this source. Several rows have blank `awarded_value`, consistent with bulletin entries that are not exposed as parseable numeric totals.
