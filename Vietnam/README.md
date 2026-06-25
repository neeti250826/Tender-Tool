# Vietnam Tender Scripts

Vietnam contains a Google Drive extracted procurement notebook, the extracted Python code cells, and the tender website SOP.

## Setup

```powershell
pip install pandas openpyxl selenium webdriver-manager
```

Install Chrome before running the Selenium workflow.

## Scripts

- `scripts/vietnam_tender_scraper_colab.ipynb` - Drive extracted Colab notebook.
- `scripts/vietnam_tender_scraper_from_notebook.py` - Python code cells extracted from the notebook.

The extracted Python script uses the notebook's hard-coded `TENDER_INPUTS` list and writes `vietnam_tenders.csv`. Edit `TENDER_INPUTS` in the script before running a new date or tender set.

## Run Command

```powershell
python Vietnam/scripts/vietnam_tender_scraper_from_notebook.py
```

## AI Prompt

```text
Run or adapt the Vietnam tender scraper from Tender-Tool for the requested tender inputs. Save outputs under Vietnam/output when possible, then summarize row count, successful bidder coverage, translation/manual-review needs, and any Selenium or portal-access failures.
```

## Documentation

- `docs/vietnam_tenders_documentation.html`
- `docs/Vietnam_Tender_SOP.docx`
