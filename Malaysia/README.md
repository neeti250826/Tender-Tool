# Malaysia Tender Scripts

Malaysia contains a Google Drive extracted MOH tender scraper, notebook wrapper, SOP, and shared MDT export helpers.

## Setup

```powershell
pip install pandas openpyxl requests beautifulsoup4
```

## Scripts

- `scripts/moh_scraper.py` - Malaysia MOH tender result scraper scaffold.
- `scripts/moh_scraper_notebook.ipynb` - Drive extracted notebook wrapper.
- `scripts/moh_scraper_notebook_commands.py` - code cells extracted from the notebook.
- `latam_spec_defaults.py`, `mdt_export.py`, `mdt_schema.py` - output and schema helpers used by the scraper.

## Run Command

```powershell
python Malaysia/scripts/moh_scraper.py --date-from 2026-03-01 --date-to 2026-03-14 --query "digital" --filter-match any --start 0 --output-target Malaysia/output --project-name MDT_2026 --website-id MY_MOH --source-label "Malaysia MOH" --region EMEA
```

## AI Prompt

```text
Run the Malaysia MOH scraper from Tender-Tool for the requested date range and medical or IVD keywords. Save outputs to Malaysia/output, then summarize row count, source-page coverage, output files, missing fields, and PDF extraction gaps.
```

## Documentation

- `docs/malaysia_moh_documentation.html`
- `docs/MOH_Tender_SOP.docx`
