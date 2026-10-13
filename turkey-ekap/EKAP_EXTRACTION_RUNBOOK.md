# EKAP Tender Extraction Runbook

This folder contains a repeatable EKAP extraction pipeline for Turkey IVD CPV codes in
`Turkey_IVD_CPV_Master_Codebook.xlsx`.

## What the pipeline extracts

- Source CPV code and workbook metadata
- Search year
- Tender/list notice fields such as IKN, tender name, authority, city, tender type, procedure, status, and tender date
- Detail-page item/OKAS summary
- Final contract/award rows from EKAP tender detail responses, one row per award/contract when available
- Winner/company and contract price fields when EKAP returns them
- Raw full CSV with API JSON trace columns for auditability
- Compact Excel/CSV outputs with structured fields suitable for review and downstream mapping
- Target-schema Excel/CSV outputs with one row per contract lot/item where EKAP exposes nested `kisimList` records

The first compact workbook is modeled as one bid/award row per output row. The target-schema workbook expands
each contract's nested lots/items, repeating the tender-level details across each lot/item row.

## EKAP API workaround

The public EKAP page calls protected JSON endpoints and adds encrypted request headers:

- `X-Custom-Request-Ts`
- `X-Custom-Request-Siv`
- `X-Custom-Request-R8id`
- `X-Custom-Request-Guid`

`ekap_extract.py` reproduces these headers using the same AES-CBC scheme observed in the loaded EKAP browser bundle, so an OAuth token is not required for the public tender search/detail endpoints used here.

## Run extraction

Default run: 2024 and 2025, CPVs marked `Include` or `Optional`, filtered by tender date.

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' -u resume_ekap_extract_append.py `
  --years 2024 2025 `
  --statuses Include Optional `
  --page-size 100 `
  --out-dir outputs\ekap_extract `
  --sleep 0.05 `
  --detail-workers 6
```

The resume script appends missing CPV/year groups to:

`outputs\ekap_extract\ekap_tender_extract_rows.csv`

It skips CPV/year groups already present in the CSV, so it is safe to rerun after an interruption.

Small smoke test:

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' -u ekap_extract.py `
  --years 2024 `
  --statuses Include `
  --limit-cpvs 1 `
  --page-size 1 `
  --max-pages 1 `
  --out-dir outputs\ekap_smoke `
  --sleep 0
```

## Build workbook

The raw trace CSV is too large for a normal Excel workbook because it preserves full JSON payloads.
Build the review workbook from structured columns with:

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' build_ekap_final_workbook.py
```

Final outputs:

- `outputs\ekap_extract\Turkey_EKAP_Tender_Extract_2024_2025.xlsx`
- `outputs\ekap_extract\Turkey_EKAP_Tender_Extract_2024_2025_compact.csv`
- `outputs\ekap_extract\ekap_tender_extract_rows.csv` raw full trace CSV

## Build target-schema workbook

Use this when the downstream table needs the requested columns:

`source, country, country_code, publication_date, closing_date, title, title_en, description,
description_en, buyer, status_en, currency, amount, awarding_agency_name,
awarding_agency_name_en, supplier_name, supplier_name_en, awarded_value_detail,
contract_period, item_no, item_description, item_description_en, item_uom, item_quantity,
notice_id, notice_url, query_text, dedup_key, source_cpv_code, source_cpv_description,
source_cpv_status, source_ivd_segment`.

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' build_ekap_target_schema.py
```

Target-schema outputs:

- `outputs\ekap_extract\Turkey_EKAP_Tender_TargetSchema_2024_2025.xlsx`
- `outputs\ekap_extract\Turkey_EKAP_Tender_TargetSchema_2024_2025.csv`

Note: EKAP's public JSON did not expose structured item UOM or item quantity fields in the extracted lot records.
The target builder checks the EKAP notice/result text for quantity/unit patterns such as
`1 Adet`, `1000 ML`, `5 Kutu`, etc., and backfills `item_quantity` / `item_uom` where those values are present
on the notice page content. Remaining lot-level rows are represented as `item_quantity = 1` and `item_uom = Lot`.

After building, run the correction pass to renumber `item_no` consecutively within each `notice_id`
and normalize the English columns:

```powershell
& 'C:\Users\Neeti\AppData\Local\Programs\Python\Python312\python.exe' correct_target_schema_itemno_translation.py
```
