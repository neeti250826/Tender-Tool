# Hungary EKR (HU_EKR) — Public procurement notices

## Website
- Procurement notices page: https://ekr.gov.hu/portal/kozbeszerzes/hirdetmenyek

This portal provides a filterable notices list (Hungarian UI).

## What this tool does
This tool uses the **public EKR API** behind the notices page to retrieve results via **requests** and export them to the standard folder layout:

`<output-target>/Tender/<REGION>/<WEBSITE_ID>/...`

## Filters (what end users should care about)
The CLI intentionally exposes only user-meaningful filters (it does **not** require you to know internal parameter names):

- Keyword filters (content search)
  - `--any-words "..."`
  - `--all-words "..."`
  - `--exclude-words "..."`
- CPV filtering
  - `--cpv-codes <CODE>` (repeatable)
- Winner / supplier name
  - `--winner-name "..."`
- Dates
  - Publication date range: `--published-from YYYY-MM-DD` / `--published-to YYYY-MM-DD`
  - Submission deadline range: `--deadline-from YYYY-MM-DD` / `--deadline-to YYYY-MM-DD`
- Paging + sorting
  - `--page N` (1-based)
  - `--page-size N`
  - `--sort-by ...` (advanced; default matches the website)
  - `--sort-direction asc|desc`

## Examples

Fetch notices published in a date range:
```bat
python "Hungary EKR\ekr_scraper.py" --output-target "./_local_outputs" --region EMEA --website-id HU_EKR \
  --published-from 2026-03-01 --published-to 2026-03-14 --page-size 20
```

Search by keywords + CPV:
```bat
python "Hungary EKR\ekr_scraper.py" --output-target "./_local_outputs" --region EMEA --website-id HU_EKR \
  --any-words "hospital" --cpv-codes 33100000 --page-size 20
```

## Notes
- The EKR portal pages are JS-rendered, so the easiest authoritative way to confirm filter-to-parameter mappings is to watch the network calls made by the notices page.
- This tool implements those mappings and keeps them internal.
