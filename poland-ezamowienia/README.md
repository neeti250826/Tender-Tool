# Poland e-Zamówienia (PL_EZAMOWIENIA)

Website: https://ezamowienia.gov.pl/en/

## Website: Advanced Search

On the e‑Zamówienia website, users can browse procurement procedures and use **advanced search** from the public UI (e.g., “Wyszukiwanie zaawansowane”).

This tool uses the **public BZP board API** used by the “BZP” board listing.

## Tool: what you can filter

The tool currently supports the following request-based filters (as used by the board API):

- `--notice-type` → `noticeType` (e.g. `ContractNotice`)
- `--below-eu` → `isTenderAmountBelowEU=true`
- `--page-number` → `PageNumber`
- `--page-size` → `PageSize` (optional)
- `--sorting-column` → `SortingColumnName` (e.g. `PublicationDate`)
- `--sorting-direction` → `SortingDirection` (`ASC`/`DESC`)

Reference endpoints (public):

- Search: `GET https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search`
- Notice PDF: `GET https://ezamowienia.gov.pl/mo-board/api/v1/Board/GetNoticePdfById?noticeId=<GUID>`

Note: UI “advanced search” labels beyond these board parameters are JS-rendered; if you need full UI mapping, run discovery.

## Quick start

```bash
python "Poland e-Zamowienia/ezamowienia_scraper.py" \
  --date-from 2026-03-01 \
  --date-to 2026-03-14 \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "PL_EZAMOWIENIA" \
  --source-label "Poland e-Zamowienia" \
  --region "EMEA" \
  --notice-type "ContractNotice" \
  --below-eu \
  --page-number 1 \
  --sorting-column "PublicationDate" \
  --sorting-direction "DESC"
```

## Discovery mode (optional)

```bash
python "Poland e-Zamowienia/ezamowienia_scraper.py" --discover-only \
  --output-target "./_local_outputs" \
  --region "EMEA" \
  --website-id "PL_EZAMOWIENIA"
```
