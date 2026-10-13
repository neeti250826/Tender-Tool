## South Africa KZN Department of Health status as of 2026-06-18

This note covers the KZN tender-awards pages only. The adjacent quotation-awards expansion is documented separately in `docs/south_africa_kznhealth_quotations_status_2026_06_18.md`.

- Source URLs:
  - `https://www2.kznhealth.gov.za/Tenders/Awarded/awarded-tenders2024.htm`
  - `https://www.kznhealth.gov.za/scm/tender-awards-2025/`
  - `https://www.kznhealth.gov.za/scm/tender-awards-2026/`
- Extractor file: `harness/sources/south_africa_kznhealth.py`
- Output file: `South Africa/kznhealth-gov-za/medical_awarded_rows_2024_01_01_to_2026_06_18.csv`
- Run shape: mixed live-first plus saved-evidence fallback. The extractor fetches the public 2024, 2025, and 2026 KZN award pages and linked PDF notices when reachable, then falls back to saved evidence under `evidence/`.

Playwright verification:

- The live 2024 KZN awarded page renders `56` PDF links in the DOM and does not expose pagination or infinite scroll controls.
- The live 2025 KZN awards page renders `27` PDF links in the DOM and does not expose pagination or infinite scroll controls.
- The live 2026 KZN awards page renders `10` PDF links in the DOM and does not expose pagination or infinite scroll controls.

Verified output:

- Row count: `50`
- Publication date coverage: `2024-01-19` to `2026-05-06`
- `awarding_supplier_name` filled: `33/50`
- `awarded_value` filled: `36/50`
- `item_desc` filled: `50/50`
- `contract_period` filled: `15/50`
- `notice_url` filled: `50/50`

Broader medical or healthcare notice families now captured:

- respiratory aids and oxygen delivery devices
- tracheostomy and ventilator accessories
- termination of pregnancy clinical services
- autoclaves
- automated simulation training equipment
- digital x-ray and mammography systems
- needles, syringes, and invasive access lines
- filters and liners
- biosafety cabinets
- CT scanners and digital radiology equipment
- clinic and community health centre build or upgrade notices that are still healthcare-facility awards

Caveat:

- Several KZN PDFs are multi-award or item-table notices, so some rows are preserved at notice level with blank supplier or blank awarded value where the first publicly extracted pages do not expose a clean one-row award pair.
