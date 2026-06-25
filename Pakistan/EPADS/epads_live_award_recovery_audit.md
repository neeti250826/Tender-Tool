# EPADS live award recovery audit - 2026-06-01

Scope: Pakistan EPADS public list/detail/LOI/annual-plan/public-notification pages for the 2024-01-01 to 2026-06-01 medical/healthcare recovery pass.

## Live access evidence

- `https://www.epads.gov.pk/loi-issued` returned HTTP 200 with title `System Issued LOIs | e-Pak Acquisition and Disposal System (EPADS)` and no block-page text. The page exposes an `Awarded Amount` column but no `Supplier Name`, `Successful Bidder`, `Awarded To`, `Awarded Date`, or `LOI Date` labels in the public HTML sampled on 2026-06-01.
- `https://www.epads.gov.pk/open-procurements` returned HTTP 200 with title `Open Opportunities (Procurements) | e-Pak Acquisition and Disposal System (EPADS)` and no block-page text. It did not expose award amount, supplier, or awarded-date labels.
- `https://epads.gov.pk/opportunities/federal/procurements/10754` returned HTTP 200 for a medicine detail page and exposed item/quantity/schedule content, but no award amount, supplier, or awarded-date labels.
- `https://epads.gov.pk/opportunities/federal/procurements/34763` returned HTTP 200 for a dental material/medicine detail page and exposed item/quantity/schedule content, but no award amount, supplier, or awarded-date labels.
- `https://epads.gov.pk/federal/annual-plan/procurement/1135/8839/2025-26?page=1` returned HTTP 200 and no block-page text. It did not expose award amount, supplier, or awarded-date labels.
- `https://pa.epads.gov.pk/procurement/goods/13075/sbd` returned HTTP 200 with title `Public Notification | e-Pak Acquisition and Disposal System (EPADS)`, but the public response still says `You do not have permission to view this page!` and did not expose award amount, supplier, or awarded-date labels.

## Scraper result

- Patched `epads_item_scraper.py` to parse the current non-linked `loi-issued` table rows. EPADS no longer provides detail anchors in those rows, so the scraper now derives `https://www.epads.gov.pk/opportunities/federal/procurements/<id>` from `P#####` references.
- The scraper now recovers real LOI listing amounts into `amount`, `currency`, and `awarded_value_detail`.
- Tightened label fallback extraction so generic prose such as `awarded to Supplier shall...` is not misread as a `supplier_name`.
- Public EPADS pages still do not expose reliable supplier names or awarded dates in the sampled LOI/detail/annual-plan/public-notification surfaces.

## Current output counts

- `Pakistan/EPADS/output/epads_item_medical_2024_2026.csv`: 1,117 rows, 38 fields.
- `amount`: 995/1,117 rows.
- `awarded_value_detail`: 995/1,117 rows.
- `supplier_name`: 0/1,117 rows.
- `awarded_date`: 0/1,117 rows.
- `notice_url`: 1,117/1,117 rows.
- Source split: 995 `EPADS LOI Issued Procurements`, 10 `EPADS Open Procurements`, 112 `EPADS Verified Public Notice`.

Focused live-only verification output:

- `Pakistan/EPADS/output/epads_live_verify.csv`: 226 rows, 38 fields.
- `amount`: 216/226 rows.
- `awarded_value_detail`: 216/226 rows.
- `supplier_name`: 0/226 rows.
- `awarded_date`: 0/226 rows.
