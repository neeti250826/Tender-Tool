# Malaysia Ministry of Health (MY_MOH)

Website tender listing (English): https://www.moh.gov.my/en/tender/list-of-tenders

## Website: Advanced Search / filters

The MOH tender listing page supports searching and filtering via **GET query parameters** (the website UI maps to these).

Common parameters:

- `filter-search` — free-text search
- `filter-match` — match mode (`any`, `all`, `exact`)\
  (UI concept: Any words / All words / Exact phrase)
- `start` — pagination offset

Additional parameters appear on the page (but are often left empty):

- `category`, `tag`, `author`, `alias`, `period`, `stage`
- `filter_order`, `filter_order_Dir`

Example (as on the website):

`https://www.moh.gov.my/en/tender/list-of-tenders?filter-search=digital&filter-match=any`

## Tool: user-facing filters

This tool exposes only the filters that are typically meaningful to end users:

- `--query` → `filter-search`
- `--filter-match` → `filter-match` (`any|all|exact`)
- `--start` → `start` (offset)

## Quick start

```bash
python "Malaysia MOH/moh_scraper.py" \
  --date-from 2026-03-01 \
  --date-to 2026-03-14 \
  --query "digital" \
  --filter-match any \
  --start 0 \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "MY_MOH" \
  --source-label "Malaysia MOH" \
  --region "EMEA"
```

## Notes / limitations

- The current implementation performs a lightweight HTML parse of listing headings; publication dates and structured tender fields are not consistently extracted from the listing page.
- If you need deeper fields (closing date, tender number, downloadable docs), the scraper should be extended to parse each tender detail page.
