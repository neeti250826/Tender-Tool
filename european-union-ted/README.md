# TED (Tenders Electronic Daily) - EU (TED_EUROPA)

Website: https://ted.europa.eu/

## Website: Advanced Search

On the TED website, go to **Search → Advanced search** to build a query with filters such as:

- keywords (title/description)
- CPV (business sector)
- place of performance
- buyer
- publication date range
- notice type

## Tools in this folder

- `ted_scraper_notebook.ipynb` — Colab notebook intended for interactive use.
- `ted_colab_scraper.py` — supporting script used by the notebook.

## Notes / limitations

- TED coverage depends on notice type and thresholds; national portals may contain additional below-threshold notices.
- The notebook includes Google Drive/Sheets integration for downstream workflows; if you only need local exports, you can adapt the notebook to skip the Sheets sync step.
