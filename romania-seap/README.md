# Romania SEAP / SICAP (RO_SEAP)

Official portal: https://www.e-licitatie.ro/

## What this tool does

This folder currently contains a **discovery-only scaffold** for Romania’s SEAP/SICAP portal.

In this environment, `e-licitatie.ro` was not reliably reachable, so the scraper cannot yet be converted into a stable requests-based implementation.

## Website: where the filters are

On the SEAP/SICAP website, tender search is performed through the portal UI (including advanced filters such as keywords, buyer, CPV, dates, notice type/status).

Because the portal is not consistently reachable here, the tool focuses on capturing **network endpoints and payload structure** when you run it from a reachable network.

## Tool usage

### List available filters / current status

```bash
python "Romania SEAP/ro_seap_scraper.py" --list-advanced-filters
```

### Discovery-only run (Playwright)

This writes a JSONL artifact with observed responses under `.../web/`.

```bash
python "Romania SEAP/ro_seap_scraper.py" --discover-only \
  --date-from 2026-03-01 \
  --date-to 2026-03-14 \
  --query "hospital" \
  --output-target "./_local_outputs" \
  --region "EMEA" \
  --website-id "RO_SEAP"
```

Artifacts are written under:

`<output-target>/Tender/<REGION>/<WEBSITE_ID>/web/`

## Limitations / next step needed

To finish a requests-based, fully filterable scraper, we need **one confirmed public/internal API call** from the SEAP advanced search results page.

If you can provide either:
- a reachable network environment for endpoint discovery, or
- a single “Copy as cURL” request from your browser DevTools (Network → XHR/fetch) for the tender search results,

then we can:
1) translate that request into a requests/curl-based implementation, and
2) expose only user-meaningful filters (keywords, CPV, buyer, dates, status) in the CLI + notebook.
