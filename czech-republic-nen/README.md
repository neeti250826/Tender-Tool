# Czech NEN (CZ_NEN) — Public procurements advanced search

## Website
- Public procurements list: https://nen.nipez.cz/en/verejne-zakazky/p:vz:page=1

On that page you can click **ADVANCED SEARCH** and set filters.

## What this tool does
This tool replicates the website’s advanced-search calls using **requests** (no browser at runtime) and exports results to the standard layout:

`<output-target>/Tender/<REGION>/<WEBSITE_ID>/...`

## Filters (user-facing)
These match the advanced search experience on the website, without exposing internal API field names:

- `--keywords` — same as the page’s search box
- `--contracting-authority-name`
- `--procedure-name`
- `--nen-code`
- `--estimated-value-min` / `--estimated-value-max` (CZK)
- `--deadline-from` / `--deadline-to` (YYYY-MM-DD)
- `--page` / `--page-size`

## Examples

Keyword search:
```bat
python "Czech NEN\nen_scraper.py" --output-target "./_local_outputs" --region EMEA --website-id CZ_NEN \
  --keywords "hospital" --page 1 --page-size 50
```

Contracting authority + deadline range:
```bat
python "Czech NEN\nen_scraper.py" --output-target "./_local_outputs" --region EMEA --website-id CZ_NEN \
  --contracting-authority-name "Ministry" --deadline-from 2026-03-01 --deadline-to 2026-03-31
```

Estimated value range:
```bat
python "Czech NEN\nen_scraper.py" --output-target "./_local_outputs" --region EMEA --website-id CZ_NEN \
  --estimated-value-min 1000000 --estimated-value-max 5000000
```

## Notes
- The NEN API requires an XSRF token (the website uses `XSRF-TOKEN-Client`); the tool fetches it automatically.
- Some advanced filters in the UI (e.g., CPV selection widgets and enums) are not yet exposed as CLI flags; they can be added by capturing the resulting request payload from the website and mapping it to a user-facing flag.
