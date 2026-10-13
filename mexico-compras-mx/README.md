# Mexico Compras MX

Recovered from `Clearstate/Mexico_Compras/compras-mx-scraper` on 2026-10-13. This package includes the existing `src/` pipeline and October `tools/` for incremental extraction, supervision, mapping, and validation.

```powershell
pip install -r mexico-compras-mx/requirements.txt
python -m playwright install chromium
python mexico-compras-mx/src/scrape_step3.py --help
```

Supply the expediente input workbook before extraction. Raw inputs, outputs, and taxonomy workbooks are not bundled. October tools retain project-specific input assumptions; inspect their arguments before running. Earlier source copies remain under `Mexico/ComprasMX/`.
