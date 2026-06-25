# Brazil Tender Scripts

Brazil contains three Clearstate-extracted scraper tracks: ComprasNet, PNCP, and Saude.

## Scripts

- `Compras/scripts/comprasnet_api_test.py` - ComprasNet API scraper/prototype.
- `PNCP/scripts/pncp_scraper.py` - PNCP tender scraper.
- `PNCP/scripts/json_to_csv.py` and `PNCP/scripts/clean_workbook.py` - PNCP output helpers.
- `Saude/scripts/scrape_dispensa_saude.py` - Brazil Saude/dispensa procurement scraper.

## Run Commands

```powershell
python Brazil/Compras/scripts/comprasnet_api_test.py
python Brazil/PNCP/scripts/pncp_scraper.py
python Brazil/Saude/scripts/scrape_dispensa_saude.py
```

## AI Prompt

```text
Run the relevant Brazil scraper for the requested source. Save outputs under Brazil/output, then summarize row counts, source coverage, filtering assumptions, and any portal or workbook cleanup issues.
```
