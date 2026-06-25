# Singapore Tender Scripts

Singapore contains GeBIZ tender scrapers and MDT export helpers.

## Setup

```powershell
pip install -r requirements.txt
pip install -r Singapore/scripts/requirements.txt
python -m playwright install chromium
```

For the Selenium fallback, install a compatible Chrome/ChromeDriver setup.

## Scripts

- `scripts/gebiz_scraper.py` - Playwright-based GeBIZ scraper.
- `scripts/gebiz_scraper_selenium.py` - Selenium fallback scraper.
- `scripts/gebiz_scraper_notebook.ipynb` - notebook wrapper or exploratory run.
- `scripts/latam_spec_defaults.py`, `scripts/mdt_export.py`, `scripts/mdt_schema.py` - export and schema helpers.

## Run Commands

```powershell
python Singapore/scripts/gebiz_scraper.py --date-from 2026-01-01 --date-to 2026-03-31 --query "medical" --max-pages 10 --output-target Singapore/output
python Singapore/scripts/gebiz_scraper_selenium.py --date-from 2026-01-01 --date-to 2026-03-31 --query "medical" --max-pages 10 --output-target Singapore/output
```

## AI Prompt

```text
Run the Singapore GeBIZ scraper from Tender-Tool for the requested date range and medical keywords. Save outputs to Singapore/output, compare Playwright and Selenium if needed, then summarize row count, pagination coverage, buyers, tender titles, and failures.
```

## Documentation

- `docs/singapore_gebiz_documentation.html`

