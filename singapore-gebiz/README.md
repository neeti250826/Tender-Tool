# Singapore GeBIZ (SG_GEBIZ) - Scaffold Tool

This folder contains a requests-based scraper for Singapore GeBIZ.

Current status:
- **BOListing (Opportunities listing)**: implemented via `requests` + HTML parsing (best-effort).
- **Advanced Search UI**: filter discovery + payload mapping is implemented, but GeBIZ may return a **"Session Expired"** page for requests-only submissions in some environments. When this happens, the tool retries with Playwright-acquired cookies and/or falls back to BOListing.

## Quick start (local)

From the `Tender Automation/` folder:

```bash
python "Singapore GeBIZ/gebiz_scraper.py" \
  --date-from 2026-01-01 \
  --date-to 2026-01-31 \
  --query "ivd" \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "SG_GEBIZ" \
  --source-label "Singapore GeBIZ" \
  --region "EMEA"
```

## Outputs

The tool uses the standard spec folder layout and routing from `latam_spec_defaults.save_spec_outputs`.

When `--output-target` is a local directory path, outputs are written under:

`<output-target>/Tender/<REGION>/<WEBSITE_ID>/`

Key folders:
- `scraping_tool/runs/` - normalized run extracts (csv/xlsx)
- `scraping_tool/<consolidated>.csv` - consolidated outputs
- `tender_data_tool/` - MDT outputs (csv/xlsx)

When `--output-target` is a Google Drive folder URL, the tool preserves the same expected suffix pathing.

## Discovery mode

To help identify GeBIZ's underlying data endpoints, you can run Playwright discovery:

```bash
python "Singapore GeBIZ/gebiz_scraper.py" \
  --discover-only \
  --query "ivd" \
  --output-target "./_local_outputs" \
  --region "EMEA" \
  --website-id "SG_GEBIZ"
```

Artifacts are written under:

`<output-target>/Tender/<REGION>/<WEBSITE_ID>/web/`

## Notes

- Translation args are wired via `add_standard_colab_args`, but translation requires Google Cloud dependencies and credentials; the scaffold does not include those packages by default.
- `--discover-only` is best-effort; if Playwright is not installed, the tool logs a warning and continues.
- To list all Advanced Search filters that the tool can map to form fields, run:

```bash
python "Singapore GeBIZ/gebiz_scraper.py" --list-advanced-filters
```
