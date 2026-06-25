# Pakistan Output Gap Audit

Date checked: 2026-06-01

## Current Output State

- `DRAP`: `371` rows in `Pakistan/DRAP/output/drap_item_medical_2024_2026.csv`
  - `amount` filled on `8/371`
  - `currency` filled on `8/371`
  - `awarded_value_detail` filled on `0/371`
  - `supplier_name` filled on `0/371`
  - `awarded_date` filled on `0/371`
  - `publication_date` filled on `371/371`
  - `closing_date` filled on `371/371`
- `EPADS`: `802` rows in `Pakistan/EPADS/output/epads_item_medical_2024_2026.csv`
  - `amount` filled on `680/802`
  - `currency` filled on `680/802`
  - `awarded_value_detail` filled on `680/802`
  - `supplier_name` filled on `0/802`
  - `awarded_date` filled on `0/802`
  - `publication_date` filled on `112/802`
  - `closing_date` filled on `802/802`
- `PPRA`: `390` rows in `Pakistan/PPRA/output/ppra_awarded_medical_2024_2026.csv`
  - `amount` filled on `0/390`
  - `currency` filled on `0/390`
  - `awarded_value_detail` filled on `0/390`
  - `supplier_name` filled on `2/390`
  - `awarded_date` filled on `2/390`
  - `publication_date` filled on `390/390`
  - `closing_date` filled on `390/390`

## VPN Access Update

- `probe_source_access.py` now proves Pakistan access is improved through the VPN path:
  - `PPRA contracts`: HTTP `200`
  - `PPRA tender detail`: HTTP `200`
  - `EPADS LOI`: HTTP `200`
  - `EPADS detail`: HTTP `200`
  - `EPADS annual plan`: HTTP `200`
- `DRAP` public tender evidence remains useful, but public DRAP tender PDFs still do not expose award-result supplier/date/value fields beyond the existing tender-price rows.

## EPADS Findings

- The live `https://www.epads.gov.pk/loi-issued` page now exposes a public `Awarded Amount` column.
- `Pakistan/EPADS/epads_item_scraper.py` now parses the current non-linked LOI rows, derives detail URLs from `P#####` notice IDs, and carries live LOI amounts into `amount`, `currency`, and `awarded_value_detail`.
- The saved EPADS output increased from notice-only coverage to `802` strict medical/healthcare rows after detail-level false-positive pruning, with `680` rows carrying real public LOI amounts.
- Public EPADS LOI/detail/annual-plan pages sampled in this pass still do not expose `supplier_name` or `awarded_date`, so those remain blank honestly.
- The EPADS filter was tightened during the live recovery pass to remove obvious healthcare-adjacent administration and maintenance false positives such as yearbooks, sewerage repair, janitorial supplies, IT/scanner hardware, paper shredders, keyboard/mouse rows, HSE supplies, non-health textile/oceanography lab rows, kitchen cabinets, and similar operational rows.

## PPRA Findings

- `https://epms.ppra.gov.pk/public/contracts` and tender-detail pages are reachable again.
- `Pakistan/PPRA/ppra_awarded_scraper.py` now includes live `/public/evaluations` parsing and supports PPRA's current detail-card markup.
- The main PPRA output now has two live healthcare evaluation rows:
  - `EVL00000000799`
  - title: `Medical/Health Insurance for PDA Employees`
  - supplier: `East West Insurance Co Ltd`
  - awarded/evaluation date: `2026-05-19`
  - URL: `https://epms.ppra.gov.pk/public/evaluations/evaluation-details/EVL00000000799`
  - `EVL00000000432`
  - title: `Group Health Insurance Coverage of NDRMF's Employees (Y2026-27 and Y2027-28)`
  - supplier: `M/s State Life Insurance Corporation Pakistan`
  - awarded/evaluation date: `2026-04-28`
  - URL: `https://epms.ppra.gov.pk/public/evaluations/evaluation-details/EVL00000000432`
- PPRA contract keyword searches for medical, health, hospital, medicine, pharma, drug, laboratory, reagent, dental, and equipment returned `0` medical contract rows in the current public contracts surface, so PPRA still does not improve `amount` coverage in the main output.
- The existing `388` PPRA fallback rows remain tender-notice / tender-document evidence, not awarded-contract evidence.

## DRAP Findings

- The DRAP agent rechecked public DRAP pages and PDFs for the 2024-to-2026 medical/lab scope.
- No public DRAP award-result evidence with supplier, award date, and award value was found beyond the existing published tender-price rows.
- The `8` priced DRAP rows remain tender-price evidence from the official `2025-01-16` lab-equipment source, not awarded-result evidence.

## Remaining Gaps

1. `EPADS` now supplies many real awarded amounts, but the public pages still do not expose supplier names or awarded dates.
2. `PPRA` now supplies two live supplier/date healthcare evaluation rows, but the public contracts surface did not expose medical awarded-contract amount rows in this pass.
3. `DRAP` still needs an award-result source, not just tender PDFs, to fill supplier and awarded-date fields.
