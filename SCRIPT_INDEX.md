# Script Index

Run commands assume you are in the repository root.

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

