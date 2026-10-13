# Vietnam Muasamcong (VN_MUASAMCONG)

This folder contains a requests-based scraper for Vietnam Muasamcong / National e-GP portal.

The portal is a JS app. Listings are retrieved via a JSON endpoint (`smart/search`).
The tool uses **Playwright only to obtain an ephemeral `token=` parameter**, then uses
**requests** for paging and data retrieval.

## Quick start (local)

From the `Tender Automation/` folder:

```bash
python "Vietnam Muasamcong/muasamcong_scraper.py" \
  --date-from 2026-01-01 \
  --date-to 2026-01-31 \
  --query "ivd" \
  --tender-status open \
  --page-size 10 \
  --max-pages 3 \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "VN_MUASAMCONG" \
  --source-label "Vietnam Muasamcong" \
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

To capture raw network artifacts (XHR/fetch) for debugging, you can run Playwright discovery:

```bash
python "Vietnam Muasamcong/muasamcong_scraper.py" \
  --discover-only \
  --query "ivd" \
  --output-target "./_local_outputs" \
  --region "EMEA" \
  --website-id "VN_MUASAMCONG"
```

Artifacts are written under:

`<output-target>/Tender/<REGION>/<WEBSITE_ID>/web/`

## Notes

- Translation args are wired via `add_standard_colab_args`, but translation requires Google Cloud dependencies and credentials; the scaffold does not include those packages by default.
- `--discover-only` is best-effort; if Playwright is not installed, the tool logs a warning and continues with placeholder exports.

## Supported user-facing filters (current)

- `--query`: keyword search (matches notice ID and package name)
- `--date-from` / `--date-to`: publication date range (best-effort server-side filter)
- `--tender-status`: `all|open|closed` (matches the website tabs)
- `--page-size`: `10|20|50`
- `--max-pages`: safety cap on paging (set `0` for unlimited)

Advanced/internal:
- `--record-type`: repeatable, defaults to `es-notify-contractor`
- `--smart-token`: supply a pre-discovered token (otherwise auto-discovered)
