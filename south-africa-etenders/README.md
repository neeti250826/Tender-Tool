# South Africa eTenders / Transparency Portal (ZA_ETENDERS)

Website:

- Portal UI: https://www.etenders.gov.za/
- Data portal: https://data.etenders.gov.za/

## Website: Advanced Search / filters

South Africa’s procurement data is published in OCDS (Open Contracting Data Standard) and can be consumed via a public REST API.

The data portal provides an OpenAPI / Swagger spec:

- Swagger: https://ocds-api.etenders.gov.za/swagger/
- OpenAPI JSON: https://ocds-api.etenders.gov.za/swagger/v1/swagger.json

The scraper uses the releases endpoint:

- `GET https://ocds-api.etenders.gov.za/api/OCDSReleases`

Supported query parameters are discovered directly from the Swagger spec via `--list-advanced-filters`.

## Tool: user-facing filters

The tool exposes a small set of user-meaningful filters:

- `--date-from`, `--date-to` (maps to API date filtering)
- `--page-number`, `--page-size`
- Optional post-filters:
  - `--tender-status`
  - `--category`
  - `--province`

## Quick start

```bash
python "South Africa eTenders/sa_etenders_scraper.py" \
  --date-from 2026-03-01 \
  --date-to 2026-03-14 \
  --page-number 1 \
  --page-size 50 \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "ZA_ETENDERS" \
  --source-label "South Africa eTenders" \
  --region "EMEA"
```

## Discover supported API parameters

```bash
python "South Africa eTenders/sa_etenders_scraper.py" --list-advanced-filters
```

This prints the API endpoint + parameters as defined in the portal’s Swagger spec.
