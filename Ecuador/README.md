# Ecuador Tender Scripts

Ecuador contains a ComprasPublicas Playwright scraper.

## Setup

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Script

- `scripts/ec_compraspublicas_scraper.py` - fills the ComprasPublicas search form, handles date-window splitting, waits for manual captcha entry, and exports normalized rows.

## Run Command

```powershell
python Ecuador/scripts/ec_compraspublicas_scraper.py --date-from 2024-01-01 --date-to 2025-12-31 --keywords "Roche|Abbott|diagnostico" --output Ecuador/output/ecuador_tenders.csv
```

## AI Prompt

```text
Run the Ecuador ComprasPublicas scraper from Tender-Tool. If captcha appears, pause for manual entry. Save output to Ecuador/output, then summarize date windows searched, row count, buyers, statuses, and missing fields.
```

## Documentation

- `docs/ecuador_compraspublicas_documentation.html`
- `docs/source_readme.md`

