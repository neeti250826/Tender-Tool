# India Tender Scripts

India contains the Clearstate eProcure Playwright scraper and PDF extraction helpers.

## Setup

```powershell
pip install -r India/eProcure/requirements.txt
python -m playwright install chromium
```

## Scripts

- `eProcure/scripts/scraper_updated.py` - browser-backed eProcure tender status scraper.
- `eProcure/scripts/extract_pdfs.py` - offline PDF extraction path.
- `eProcure/scripts/common.py` - shared OCR, PDF, and item parsing helpers.
- `eProcure/scripts/captcha_solver.py` - captcha OCR helper.

## Run Commands

```powershell
python India/eProcure/scripts/scraper_updated.py --keyword "reagents"
python India/eProcure/scripts/extract_pdfs.py
```

## Notes

The live scraper uses Playwright because eProcure has stateful form tokens, captcha, and session-bound detail links.

## Documentation

- `eProcure/docs/README_clearstate.md`
- `eProcure/docs/India_Tender_Website_Guide.docx`
