# Hungary NEAK (HU_NEAK) - Scaffold Tool

This folder contains a scaffold (placeholder) scraper for Hungary NEAK.

Current status: placeholder only. The fetch/parse logic is not implemented yet.

## Quick start (local)

From the `Tender Automation/` folder:

```bash
python "Hungary NEAK/neak_scraper.py" \
  --date-from 2026-01-01 \
  --date-to 2026-01-31 \
  --query "ivd" \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "HU_NEAK" \
  --source-label "Hungary NEAK" \
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

To discover downloadable datasets/links published on the NEAK page:

```bash
python "Hungary NEAK/neak_scraper.py" \
  --discover-only \
  --query "gyse" \
  --output-target "./_local_outputs" \
  --region "EMEA" \
  --website-id "HU_NEAK"
```

Artifacts are written under:

`<output-target>/Tender/<REGION>/<WEBSITE_ID>/web/`

## Notes

- Translation args are wired via `add_standard_colab_args`, but translation requires Google Cloud dependencies and credentials; the scaffold does not include those packages by default.
- `--discover-only` is best-effort; if the page is unreachable, the tool still writes an artifact containing an error string.
