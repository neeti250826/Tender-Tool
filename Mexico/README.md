# Mexico Tender Scripts

Mexico contains the Clearstate ComprasMX scraper project.

## Setup

```powershell
pip install -r Mexico/ComprasMX/requirements.txt
python -m playwright install chromium
```

## Scripts

- `ComprasMX/scripts/src/scrape_step2.py` - URL preparation.
- `ComprasMX/scripts/src/scrape_step3.py` - core Playwright scraper.
- `ComprasMX/scripts/src/step4_merge.py` - JSON merge helper.
- `ComprasMX/scripts/src/step5_excel_export.py` - Excel export helper.
- `ComprasMX/scripts/smoke_test.py` - smoke test helper.

## Run Commands

```powershell
python Mexico/ComprasMX/scripts/src/scrape_step3.py --excel "expedientes_comprasmx_2026.xlsx"
python Mexico/ComprasMX/scripts/src/step5_excel_export.py --jsonl combined.jsonl
```

## Documentation

- `ComprasMX/docs/README_clearstate.md`
- `ComprasMX/docs/IMPORTANT_README.txt`
- `ComprasMX/notebooks/scrape.ipynb`
- `ComprasMX/notebooks/data_eda.ipynb`
