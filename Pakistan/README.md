# Pakistan Tender Scripts

Pakistan contains public procurement and award-stage scrapers for PPRA, DRAP, EPADS, ADB, and World Bank sources.

## Setup

Run from the repository root:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Scripts

- `PPRA/ppra_awarded_scraper.py` - awarded-contract pages, medical rows.
- `DRAP/drap_item_scraper.py` - public tender PDFs and item-level medical rows.
- `EPADS/epads_item_scraper.py` - LOI-issued procurement listings.
- `ADB/adb_health_awards_scraper.py` - extracts Pakistan health awards from the included ADB workbook.
- `WorldBank/worldbank_health_awards_scraper.py` - fetches World Bank health-sector goods awards.
- `*_verified_seeds.py` files - verified reference rows used by the scrapers.

## Run Commands

```powershell
python Pakistan/PPRA/ppra_awarded_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 100 --translate
python Pakistan/DRAP/drap_item_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 5 --max-tenders 50 --headless --translate
python Pakistan/EPADS/epads_item_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 5 --max-tenders 50 --headless --translate
python Pakistan/ADB/adb_health_awards_scraper.py --input Pakistan/ADB/adb_procurement_by_nationality_2016_2026.xlsx --date-from 2024-01-01 --date-to 2026-06-25
python Pakistan/WorldBank/worldbank_health_awards_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --top 1000
python combine_pakistan_awards.py --date-from 2024-01-01 --date-to 2026-06-25
```

## AI Prompt

```text
Run the Pakistan tender scripts from the Tender-Tool repository for 2024-01-01 through 2026-06-25. Use PPRA, DRAP, EPADS, ADB, and World Bank sources, then combine the outputs. Summarize source coverage, row counts, top buyers/suppliers, medical-scope filtering assumptions, and any failed or incomplete fields.
```

## Documentation

- `docs/pakistan_tender_scrapers.html`
- `docs/pakistan_output_gap_audit.md`
- `docs/capt_drap_gap_audit.md`
- `../docs/procurement_scraper_documentation.html`

