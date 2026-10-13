# Ecuador ComprasPublicas Python Scraper

This project uses Python + Playwright to automate:

`https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/buscarProceso.cpe`

The scraper now uses a broad website search and applies the company list locally after extraction.

The scraper:

- searches the website with `Licitacion`, `Adjudicada`, and the selected publication dates
- leaves the website keyword field blank
- waits for manual captcha entry in the browser
- scrapes all summary result pages
- opens each tender detail page
- filters records locally against the company keyword list
- exports normalized rows to CSV

## Important constraint

The site does not allow the full `2024-01-01` to `2025-12-31` range in a single request. Its client-side validation only allows roughly 200 days per search window, so the script automatically splits the full period into smaller windows.

## Confirmed live selectors

- keyword field: `#txtPalabrasClaves`
- procedure select: `#txtCodigoTipoCompra`
- state select: `#cmbEstado`
- date fields: `#f_inicio`, `#f_fin`
- captcha input: `#image`

## Files

- scraper: `ec_compraspublicas_scraper.py`
- dependency list: `requirements.txt`
- default output: `output/ecuador_tenders.csv`

## Python setup

Install the dependency:

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' -m pip install -r .\requirements.txt
```

Install the Playwright browser if needed:

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\Scripts\playwright.exe' install chromium
```

## Run

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' .\ec_compraspublicas_scraper.py
```

Example:

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' .\ec_compraspublicas_scraper.py --keywords "Roche|Abbott" --states "Adjudicada" --date-from 2024-01-01 --date-to 2025-12-31 --output .\output\ecuador_tenders.csv
```

## Captcha handling

The script does not solve the captcha automatically. It opens the live browser, waits for you to type the captcha, and then continues automatically after the captcha field is filled.

## Output columns

`source,country,country_code,publication_date,closing_date,title,description,buyer,classification,status,currency,amount,awarding_supplier_name,awarded_date,contract_number,item_no,item_desc,item_uom,item_quantity,item_unit_price,item_award_amount,notice_id,notice_url,query_text,scraped_at,dedup_key`
