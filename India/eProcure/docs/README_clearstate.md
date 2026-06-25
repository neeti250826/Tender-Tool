# eProcurement India Tender Status Scraper

This scraper now uses a real Chromium browser through Playwright for the live search step at:

`https://eprocure.gov.in/eprocure/app?page=WebTenderStatusLists&service=page`

That change matters because the Tender Status page is a stateful Tapestry form with:

- per-request hidden tokens
- an inline base64 captcha
- session-bound result/detail links

The old `requests` post to the advanced-search endpoint was not aligned with that flow, so the online scraper has been switched to:

1. Open the Tender Status page in Playwright
2. Select the Tender Status code and fill the keyword
3. Read and solve the embedded captcha with EasyOCR
4. Submit the real browser form
5. Parse result pages
6. Reuse the authenticated browser cookies for detail/PDF requests
7. OCR award PDFs and export CSV/JSON

## Files

- `scraper.py`: live browser-backed pipeline
- `extract_pdfs.py`: offline PDF-only pipeline
- `common.py`: shared OCR, PDF, and item parsing helpers
- `captcha_solver.py`: captcha OCR helper

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

If you do not already have the OCR dependencies in your active Python environment, `opencv-python-headless`, `easyocr`, and the PDF packages must also be installed from `requirements.txt`.

## Usage

Default AOC search:

```bash
python scraper.py --keyword "reagents"
```

Search more result pages:

```bash
python scraper.py --keyword "clinical chemistry reagents" --max-pages 5
```

Run with a visible Chromium window for debugging:

```bash
python scraper.py --keyword "reagents" --headful --verbose
```

Choose a different Tender Status code from the live page:

```bash
python scraper.py --keyword "reagents" --tender-status 9
```

Status codes:

- `1`: To Be Opened Tenders
- `2`: Technical Bid Opening
- `3`: Technical Evaluation
- `4`: Financial Bid Opening
- `5`: Financial Evaluation
- `6`: AOC
- `7`: Retender
- `8`: Cancelled
- `9`: Concluded

Save downloaded PDFs too:

```bash
python scraper.py --keyword "reagents" --save-pdfs --pdf-dir pdfs
```

## Notes

- Pagination handling is browser-driven and stops when no next-page control is found.
- Detail/AOC links on this site are often session-bound, so the scraper copies cookies out of the Playwright browser context before downloading PDFs.
- `extract_pdfs.py` remains useful when you already have the award PDFs locally and only need the OCR extraction stage.
