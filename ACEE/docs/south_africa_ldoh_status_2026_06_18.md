## South Africa Limpopo Department of Health status as of 2026-06-18

- Source URL: `https://www.ldoh.gov.za/?q=node/12`
- Supporting public document index: `https://www.ldoh.gov.za/ldoh-admin/documents/latestnews/documents/`
- Extractor file: `harness/sources/south_africa_ldoh.py`
- Output file: `South Africa/ldoh-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
- Run shape: mixed live-first plus saved-evidence fallback. The extractor fetches the awarded-tenders page, the public Apache documents index, and the linked PDF award notices when reachable, then falls back to saved evidence files under `evidence/`.

Verified output:

- Row count: `36`
- Publication date coverage: `2024-04-22` to `2026-05-08`
- `awarding_supplier_name` filled: `36/36`
- `awarded_value` filled: `3/36`
- `item_desc` filled: `36/36`
- `contract_period` filled: `13/36`
- `notice_url` filled: `36/36`

Current notice mix:

- `SURGICAL AWARD - BID (Bulk-Awards-Template)`: `23` supplier rows
- `HEDP 023/24/25`: `4` supplier rows
- `HEDP 011/24/25`: `5` supplier rows
- `HEDP 022/24/25`: `1` row
- `HEDP 005/24/25`: `1` row
- `HEDP 012/24/25`: `1` row
- `HEDP 018/22/23`: `1` row

Strong data:

- Supplier names, item descriptions, and notice URLs are complete for every current row.
- Publication dates are evidence-backed from the public `Last modified` timestamps in the documents index.
- The source adds meaningful 2024-to-recent healthcare coverage from MMC packs, aeromedical and ambulance services, specialised clinical and histopathology services, donor breastmilk banks, and a large 2026 surgical award panel.

Caveat:

- Numeric award values are sparse because several Limpopo notices expose only `Rates` or `On Rate` panel outcomes rather than a single total awarded amount.
