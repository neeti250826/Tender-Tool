# Malaysia ePerolehan

- Country: Malaysia (MY)
- Portal: https://www.eperolehan.gov.my/quotation-tender-notice
- Status: scraper source included

Browser-based extractor for ePerolehan quotation and tender notices.

The previously missing source was recovered on 2026-10-13 as `eperolehan_scraper.py` (original local filename `Debug_2.py`).

```powershell
pip install -r malaysia-eperolehan/requirements.txt
python -m playwright install chromium
python malaysia-eperolehan/eperolehan_scraper.py --date-from 01/01/2024 --date-to 13/10/2026 --max-pages 1
```

Dates use DD/MM/YYYY; the end date defaults to today. Keep the browser visible for any required user interaction. Saved progress can be resumed with `--resume`; use a separate progress/output filename when changing scope.
