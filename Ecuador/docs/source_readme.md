# Ecuador ComprasPublicas Playwright Scraper

This script automates the search form at:

`https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/buscarProceso.cpe`

It uses Playwright to:

- fill keyword, procedure type, state, and publication dates
- wait for manual captcha entry in the browser
- scrape all summary result pages
- open each tender detail page
- export normalized rows to CSV

## Important constraint

The site does not allow the full `2024-01-01` to `2025-12-31` range in a single request. Its client-side validation only allows roughly 200 days per search window, so the script automatically splits the full period into smaller windows.

## What was confirmed from the live page

- keyword field: `#txtPalabrasClaves`
- procedure select: `#txtCodigoTipoCompra`
- state select is injected after choosing procedure: `#cmbEstado`
- date fields: `#f_inicio`, `#f_fin`
- captcha input: `#image`
- search button calls the page JS function `botonBuscar()`

## Install

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```powershell
python Ecuador/scripts/ec_compraspublicas_scraper.py --date-from 2024-01-01 --date-to 2025-12-31 --output Ecuador/output/ecuador_tenders.csv
```

You can also override filters:

```powershell
python Ecuador/scripts/ec_compraspublicas_scraper.py --keywords "Roche|Abbott" --states "Adjudicada|En Curso" --date-from 2024-01-01 --date-to 2025-12-31 --output Ecuador/output/ecuador_tenders.csv
```

## Captcha handling

The script does not solve the captcha automatically. It opens the live browser, waits for you to type the captcha, and then resumes scraping after you press Enter in the terminal.

## Output columns

The CSV contains:

`source,country,country_code,publication_date,closing_date,title,description,buyer,classification,status,currency,amount,awarding_supplier_name,awarded_date,contract_number,item_no,item_desc,item_uom,item_quantity,item_unit_price,item_award_amount,notice_id,notice_url,query_text,scraped_at,dedup_key`

Some fields depend on what is available on each tender detail page. When line-item tables are present, the script expands one notice into multiple CSV rows.
