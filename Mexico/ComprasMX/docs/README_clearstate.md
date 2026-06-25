# Compras MX Scraper – POC

This folder contains a Proof of Concept (POC) Playwright-based scraper
that extracts tender, contract, and financial line-item data from
Compras MX (Mexico public procurement portal).

## Project Structure

- data/
  - Tender List.xlsx         Input tender URLs
- src/
  - scrape_step2.py          URL preparation
  - scrape_step3.py          Core scraper (SPA + dialogs)
  - step4_merge.py           Merge + final output
- output/
  - raw_jsonl/               Canonical scraped data
  - *.csv                    Derived outputs
  - Tender List__with_step3.xlsx
- notebooks/
  - scrape.ipynb             Exploration
  - data_eda.ipynb           Validation

## How to Run (Minimal)

1. Create virtual environment
   python -m venv .venv
   .venv\Scripts\activate

2. Install dependencies
   pip install -r requirements.txt
   playwright install chromium

3. Run scraper
   python src/scrape_step3.py --excel "expedientes_comprasmx_2026.xlsx"

4. Merge results
   ## Step 1: Convert all `.json` files into a single `combined.jsonl`

```bash
python -c "from pathlib import Path; import json; out=Path('combined.jsonl'); n=0
    with out.open('w', encoding='utf-8') as w:
    for p in Path('output/by_url/New_Tenders').rglob('*.json'):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data=json.load(f)
            if isinstance(data, list):
                for obj in data:
                    w.write(json.dumps(obj, ensure_ascii=False) + '\n')
                    n += 1
            else:
                w.write(json.dumps(data, ensure_ascii=False) + '\n')
                n += 1
        except Exception as e:
            print('Skipped', p, e)
print(f'Wrote {n} records to {out}')"

## Last Step
- python src/step5_excel_export.py --jsonl combined.jsonl

## Notes

- Scraping is slow (~30–45s per URL) due to SPA behavior.
- JSONL files are the source of truth.
- Step 4 can be rerun without scraping again.