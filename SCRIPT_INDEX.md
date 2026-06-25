# Script Index

Run commands assume you are in the repository root.

## Shared Runners And Verification Scripts

### `run_awarded_scrapers.py`

Runs the awarded-stage medical scrapers that have compatible command-line interfaces.

```powershell
python run_awarded_scrapers.py --date-from 2024-01-01 --date-to 2026-06-25 --headless --translate
```

AI prompt:

```text
Run the shared awarded-scrapers runner, then summarize which source scripts completed, which failed, row counts by source, and fields that need manual review.
```

### `run_item_level_scrapers.py`

Runs item-level public medical scrapers for Pakistan DRAP and EPADS.

```powershell
python run_item_level_scrapers.py --date-from 2024-01-01 --date-to 2026-06-25 --headless
```

AI prompt:

```text
Run the shared item-level scraper runner, then summarize DRAP and EPADS output counts, item-level completeness, and source access problems.
```

### `combine_pakistan_awards.py`

Combines Pakistan award-stage rows from the configured Pakistan sources.

```powershell
python combine_pakistan_awards.py --date-from 2024-01-01 --date-to 2026-06-25
```

AI prompt:

```text
Run the Pakistan award combiner after source scrapers finish, then summarize deduplication, final row counts, and any sources missing from the combined output.
```

### `verify_capt_drap_coverage.py`

Checks selected Kuwait CAPT and Pakistan DRAP coverage assumptions.

```powershell
python verify_capt_drap_coverage.py
```

AI prompt:

```text
Run verify_capt_drap_coverage.py and summarize whether CAPT and DRAP coverage assumptions are met, including any gaps that need source inspection.
```

### `verify_output_diagnostics.py`

Runs lightweight output diagnostics after scraper outputs exist.

```powershell
python verify_output_diagnostics.py
```

AI prompt:

```text
Run verify_output_diagnostics.py after scraper outputs are generated, then summarize missing files, row-count anomalies, and recommended reruns.
```

### `procurement_utils.py`

Shared utility module imported by country scripts. Do not run directly.

AI prompt:

```text
Inspect procurement_utils.py only if a country scraper fails. Explain which helper function is involved and patch the smallest safe fix.
```

## Singapore

### `Singapore/scripts/gebiz_scraper.py`

Primary Playwright scraper for Singapore GeBIZ.

```powershell
python Singapore/scripts/gebiz_scraper.py --date-from 2026-01-01 --date-to 2026-03-31 --query "medical" --max-pages 10 --output-target Singapore/output
```

AI prompt:

```text
Run the Singapore GeBIZ Playwright scraper for medical tenders from 2026-01-01 to 2026-03-31, save outputs under Singapore/output, then summarize row count, date coverage, key buyers, and any failures.
```

### `Singapore/scripts/gebiz_scraper_selenium.py`

Selenium fallback for Singapore GeBIZ when Playwright navigation is not enough.

```powershell
python Singapore/scripts/gebiz_scraper_selenium.py --date-from 2026-01-01 --date-to 2026-03-31 --query "medical" --max-pages 10 --output-target Singapore/output
```

AI prompt:

```text
Run the Singapore GeBIZ Selenium fallback for the same date range and compare its output with the Playwright scraper. Report which one captured more complete pagination.
```

### Singapore helper scripts

- `Singapore/scripts/latam_spec_defaults.py` - default export/filter helper.
- `Singapore/scripts/mdt_export.py` - MDT flat-file export helper.
- `Singapore/scripts/mdt_schema.py` - MDT output schema helper.

These are support modules. Import them from the main Singapore scraper flow rather than running them alone.

### Singapore Drive extracts

Google Drive source copies are preserved under `Singapore/drive_extracts/Singapore_GeBIZ/`:

- `README.md`
- `requirements.txt`
- `gebiz_scraper.py`
- `gebiz_scraper_notebook.ipynb`

Use these for provenance or comparison before replacing the active scripts in `Singapore/scripts/`.

## Malaysia

### `Malaysia/scripts/moh_scraper.py`

Malaysia MOH tender result scraper scaffold extracted from Google Drive.

```powershell
python Malaysia/scripts/moh_scraper.py --date-from 2026-03-01 --date-to 2026-03-14 --query "digital" --filter-match any --start 0 --output-target Malaysia/output --project-name MDT_2026 --website-id MY_MOH --source-label "Malaysia MOH" --region EMEA
```

AI prompt:

```text
Run the Malaysia MOH scraper for the requested date range and medical or IVD keywords. Save outputs to Malaysia/output, then summarize row count, source-page coverage, output files, missing fields, and PDF extraction gaps.
```

### Malaysia notebook and helpers

- `Malaysia/scripts/moh_scraper_notebook.ipynb` - Drive extracted notebook wrapper.
- `Malaysia/scripts/moh_scraper_notebook_commands.py` - extracted notebook commands.
- `Malaysia/latam_spec_defaults.py`, `Malaysia/mdt_export.py`, `Malaysia/mdt_schema.py` - helper modules.

## Vietnam

### `Vietnam/scripts/vietnam_tender_scraper_from_notebook.py`

Notebook-derived Selenium scraper extracted from Google Drive. It uses the hard-coded `TENDER_INPUTS` list in the script and writes `vietnam_tenders.csv`.

```powershell
python Vietnam/scripts/vietnam_tender_scraper_from_notebook.py
```

AI prompt:

```text
Run or adapt the Vietnam tender scraper for the requested tender inputs. Save outputs under Vietnam/output when possible, then summarize row count, successful bidder coverage, translation/manual-review needs, and any Selenium or portal-access failures.
```

### Vietnam notebook

- `Vietnam/scripts/vietnam_tender_scraper_colab.ipynb` - Drive extracted Colab notebook.

## Brazil

```powershell
python Brazil/Compras/scripts/comprasnet_api_test.py
python Brazil/PNCP/scripts/pncp_scraper.py
python Brazil/Saude/scripts/scrape_dispensa_saude.py
```

AI prompt:

```text
Run the relevant Brazil scraper, save outputs under Brazil/output, and summarize row counts, source coverage, filtering assumptions, and portal issues.
```

## India

```powershell
python India/eProcure/scripts/scraper_updated.py --keyword "reagents"
python India/eProcure/scripts/extract_pdfs.py
```

AI prompt:

```text
Run the India eProcure scraper for the requested keyword or process local award PDFs, then summarize captured tenders, item extraction, captcha/PDF issues, and output files.
```

## KSA

```powershell
python KSA/scripts/nupco_awards_scraper.py
python KSA/scripts/etimad_awards_scraper.py
python KSA/scripts/validate_award_jsonl.py path\to\awards.jsonl
```

AI prompt:

```text
Run the KSA NUPCO or Etimad awarded tender scraper, then summarize awarded rows, supplier/amount coverage, attachment parsing gaps, and validation results.
```

## Mexico

```powershell
python Mexico/ComprasMX/scripts/src/scrape_step3.py --excel "expedientes_comprasmx_2026.xlsx"
python Mexico/ComprasMX/scripts/src/step5_excel_export.py --jsonl combined.jsonl
```

AI prompt:

```text
Run the Mexico ComprasMX scraper or merge/export helpers, then summarize tender counts, JSONL completeness, contract/item extraction, and slow or failed URLs.
```

## Peru

```powershell
python Peru/scripts/scrape.py
```

AI prompt:

```text
Run or inspect the Peru scraper, save outputs under Peru/output, and summarize award coverage, fields captured, and any missing data.
```

## South Korea

```powershell
python South_Korea/South_Korea_2026/g2b_production_scraper_buyer_final.py
```

AI prompt:

```text
Run the South Korea G2B scraper for the requested year/date range, then summarize tender rows, item-level extraction, buyer/supplier coverage, popup failures, and resume state.
```

## Spain

`Spain/drive_extracts/Spain_Tender/` preserves a Clearstate source folder named `Spain_Tender`, but the included README identifies the scripts as Ecuador ComprasPublicas tooling. Treat this as provenance unless the user confirms it is intended for Spain.

## Thailand

```powershell
python Thailand/scripts/Collect_urls.py
python Thailand/scripts/process_tender_urls_contract_period_fixed.py
```

AI prompt:

```text
Run the Thailand GProcurement workflow after Edge is opened in remote-debugging mode and Cloudflare is solved. Summarize URL count, detail rows, contract item extraction, and session/browser issues.
```

## ACEE Countries

### Czechia

```powershell
python Czechia/scripts/czechia_nen_awarded_healthcare_scraper.py
```

### Poland

```powershell
python Poland/scripts/poland_ezamowienia_medical_scraper_itemdetails_v4.py
```

Egypt, Hungary, Romania, and South Africa currently include ACEE notes/reports only; no runnable source scraper was found in the curated scan.

## Pakistan

### `Pakistan/PPRA/ppra_awarded_scraper.py`

```powershell
python Pakistan/PPRA/ppra_awarded_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 100 --translate
```

AI prompt:

```text
Run the Pakistan PPRA awarded-contract scraper for medical rows, then summarize output volume, award dates, buyers, suppliers, and rows with missing award values.
```

### `Pakistan/DRAP/drap_item_scraper.py`

```powershell
python Pakistan/DRAP/drap_item_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 5 --max-tenders 50 --headless --translate
```

AI prompt:

```text
Run the Pakistan DRAP item-level scraper, save CSV and JSONL outputs, then summarize item descriptions, quantities, suppliers, and extraction gaps.
```

### `Pakistan/EPADS/epads_item_scraper.py`

```powershell
python Pakistan/EPADS/epads_item_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 5 --max-tenders 50 --headless --translate
```

AI prompt:

```text
Run the Pakistan EPADS LOI-issued medical scraper and report output count, source coverage, item-level fields captured, and portal access issues.
```

### `Pakistan/ADB/adb_health_awards_scraper.py`

```powershell
python Pakistan/ADB/adb_health_awards_scraper.py --input Pakistan/ADB/adb_procurement_by_nationality_2016_2026.xlsx --date-from 2024-01-01 --date-to 2026-06-25
```

AI prompt:

```text
Run the Pakistan ADB health awards extraction from the included workbook and summarize high-confidence medical rows and filtering assumptions.
```

### `Pakistan/WorldBank/worldbank_health_awards_scraper.py`

```powershell
python Pakistan/WorldBank/worldbank_health_awards_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --top 1000
```

AI prompt:

```text
Run the Pakistan World Bank healthcare awards scraper, then summarize award counts, top suppliers, top buyers, and any API or source filtering caveats.
```

### Pakistan runners and helpers

```powershell
python run_item_level_scrapers.py --date-from 2024-01-01 --date-to 2026-06-25 --headless
python run_awarded_scrapers.py --date-from 2024-01-01 --date-to 2026-06-25 --headless --translate
python combine_pakistan_awards.py --date-from 2024-01-01 --date-to 2026-06-25
```

Seed/helper files such as `*_verified_seeds.py`, `procurement_utils.py`, and `verify_*.py` support the main runs and are not normally run first.

## Kuwait

### `Kuwait/CAPT/capt_awarded_scraper.py`

```powershell
python Kuwait/CAPT/capt_awarded_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 250 --headless --translate
```

AI prompt:

```text
Run the Kuwait CAPT winning-bids scraper for medical rows, then summarize captured awards, excluded notices, source-page coverage, and any PDF/manual-review gaps.
```

### `Kuwait/CAPT/capt_pdf_helper.py`

Use this for local CAPT PDF inspection:

```powershell
python Kuwait/CAPT/capt_pdf_helper.py path\to\capt.pdf --pages 1-3 --ocr
```

AI prompt:

```text
Inspect the supplied CAPT PDF with capt_pdf_helper.py, extract likely award rows, and explain which rows should be included or excluded for the medical scope.
```

## UAE

### `UAE/Dubai_eSupply/dubai_esupply_scraper.py`

```powershell
python UAE/Dubai_eSupply/dubai_esupply_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 25 --translate
```

AI prompt:

```text
Run the UAE Dubai eSupply scraper for medical opportunities and awards, then summarize records captured, source tabs covered, detail-page access issues, and missing fields.
```

## Ecuador

### `Ecuador/scripts/ec_compraspublicas_scraper.py`

```powershell
python Ecuador/scripts/ec_compraspublicas_scraper.py --date-from 2024-01-01 --date-to 2025-12-31 --keywords "Roche|Abbott|diagnostico" --output Ecuador/output/ecuador_tenders.csv
```

AI prompt:

```text
Run the Ecuador ComprasPublicas scraper for diagnostic and medical keywords. If the portal asks for captcha, pause for manual entry, then summarize output rows, date-window splits, and missing detail fields.
```
