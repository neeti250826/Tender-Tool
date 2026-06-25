# Kuwait Tender Scripts

Kuwait contains CAPT winning-bids scraping and PDF inspection support.

## Setup

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Scripts

- `CAPT/capt_awarded_scraper.py` - scrapes CAPT winning bids and keeps medical or healthcare rows.
- `CAPT/capt_pdf_helper.py` - renders and inspects local CAPT PDFs.
- `CAPT/capt_verified_seeds.py` - verified seed rows and exclusions used by the scraper.

## Run Commands

```powershell
python Kuwait/CAPT/capt_awarded_scraper.py --date-from 2024-01-01 --date-to 2026-06-25 --max-pages 250 --headless --translate
python Kuwait/CAPT/capt_pdf_helper.py path\to\capt.pdf --pages 1-3 --ocr
```

## AI Prompt

```text
Run the Kuwait CAPT awarded scraper from the Tender-Tool repository for 2024-01-01 through 2026-06-25. Save CSV and JSONL outputs, summarize winning bids in medical scope, explain excluded notices, and identify any CAPT PDF/manual-review gaps.
```

## Documentation

- `docs/kuwait_capt_documentation.html`
- `CAPT/capt_exclusion_notes.md`
- `../docs/procurement_scraper_documentation.html`

