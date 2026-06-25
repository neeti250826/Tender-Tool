# UAE Tender Scripts

UAE contains the Dubai eSupply scraper.

## Setup

```powershell
pip install -r requirements.txt
```

## Script

- `Dubai_eSupply/dubai_esupply_scraper.py` - scrapes Dubai eSupply current and past opportunities where accessible and filters medical rows.

## Run Command

```powershell
python UAE/Dubai_eSupply/dubai_esupply_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 25 --translate
```

## AI Prompt

```text
Run the UAE Dubai eSupply scraper from Tender-Tool for 2024-01-01 through 2026-06-25. Summarize row count, source tabs covered, detail-page access limitations, medical filtering assumptions, and fields that need manual follow-up.
```

## Documentation

- `docs/uae_dubai_esupply_documentation.html`
- `../docs/procurement_scraper_documentation.html`

