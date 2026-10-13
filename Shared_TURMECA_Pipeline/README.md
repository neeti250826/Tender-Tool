# Shared TURMECA pipeline (Turkey, Middle East, Central Asia)

Common code behind `Turkey_EKAP`, `SaudiArabia_NUPCO`, `Kuwait_CAPT`, `UAE_Dubai_eSupply` and the `Pakistan_*` folders. In the original tree this was `turmeca/` and the country folders were its sub-folders, so the country builders import from here via `sys.path.insert(0, parent_dir)`.

## Mapping and translation
* `vocab_rules.py` - EN / TR / AR vocabulary layer in front of the keyword/fuzzy matcher. Product Category / Sub-OU / OU from the line text only; Company from manufacturer text only (alias table, exact, strict fuzzy); Family from model / catalogue tokens.
* `translate.py` - cached batch translation via translate.googleapis.com (`translation_cache.sqlite`, not committed).
* `refine_mapping.py`, `category_fixes.py`, `apply_category_fixes.py` - Company / Family refinement and the hand-audited category corrections.
* `tr_glossary_fix.py`, `fix_translations_from_cache.py` - offline fixes for Turkish `(EN)` columns when Google Translate is rate-limited.

## Workbook builders
* `build_turmeca_master.py` - `TURMECA_Tender_Master.xlsx` (master table schema, code lists per area, NUPCO families, CPV 331xx, EKAP OKAS classes) + refreshed `Mapping_Taxonomy.xlsx`. Inputs in `sources/`.
* `build_master_mapped.py` - `TURMECA_Master_Mapped_Data.xlsx`, one tab per country x website in the common schema. FX from `fx_annual_usd.json`, KSA value from `ref_prices.csv`.
* `add_gap_notes.py`, `add_translations.py` - post-processing of the mapped master.
* `build_raw_exports.py` - raw (unmapped) per-country workbooks, one tab per source table.
* `build_ref_prices.py` - reference unit prices per Device Category from the KP bid evaluation reports (feeds the KSA valuation). Only categories with a mapped KP item get a price; nothing is guessed.
* `add_cy2025_columns.py` - CY2025 applicable-period columns (contract start/end, months active, 2025 share).
* `build_mapping_prompt_docx.py` + `docs/TURMECA_Mapping_Prompt_as_built.md` - the mapping prompt as a Word document.
* `docs/TURMECA_Tender_Data_SOP.html` - the SOP.

## sources/
* `pw_src.js` - CPV 331 codes from the EU Publications Office SPARQL endpoint (`cpv331.csv`); `pw_sheet2.js` - export the taxonomy Google Sheet as xlsx through a signed-in Playwright profile.
* `okas_tr.json` - OKAS code -> Turkish name from 9,551 EKAP detail JSONs; `nupco_parsed.json` - all 119 NUPCO tenders.

## gsheet_writeback/
Clipboard-paste writers for the live Google Sheets (headed Chrome, signed-in profile): `cy2025/paste_to_gsheet.js`, `refine/paste_refined.js`, `refine/paste_audit.js`, plus `refine/prepare_writeback.py` and `cy2025/readme_fix.js`, `summary_fix.js`. Insert columns first; the name-box jump raises a blocking modal otherwise.
