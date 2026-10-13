# Vietnam - VNEPS (muasamcong.mpi.gov.vn)

Source: VNEPS winning-bid unit-price database ("Co so du lieu ve don gia trung thau"), tab *Medical equipment and supplies*.
Guest API `POST /o/egp-portal-winning-bid-data/services/smart/search_prc` (no login; the Excel export does need login).

## extractor/
* `vneps_console_extractor.js` - paste into the browser console (F12) on `/en/web/guest/winning-bid-data`. Runs the keyword list (Vietnamese + English device terms grouped by Medtronic OU), de-duplicates by record id and downloads `vneps_awarded_medtech.csv`. Must run in a real browser: the server uses weak-DH TLS plus a WAF that rejects non-browser clients.

## mapping/
* `map_vneps.py` - map the CSV to the Clearstate taxonomy (OU / Sub-OU / Product Category / Company / Family), add English gloss columns -> `VNEPS_Awarded_Medtech_Mapped.xlsx`.
* `translate_vn.py` - Vietnamese -> English closed-set dictionaries and a longest-match device glossary.
* `run_mapping.py` - map the plugin-enriched VN tenders file (`VN_Medtech_Player_Mapped_Enriched.xlsx`) -> Mapped / Unmapped / Summary workbook.
* `merge_combined.py` - union of both mapped sources -> `VN_Medtech_Mapped_Combined.xlsx`.
* `build_analysis.py` - value/volume DB, aggregates and market sizing vs the MDT Eurasia reference -> `VN_Medtech_Market_Sizing.xlsx`.
* `parse_mdt.py` - parse the MDT Eurasia reference sheet into a long CSV.

Depends on `../Shared_Taxonomy_Mapping` (taxonomy.py, matcher.py, enrich.py) and `Mapping_Taxonomy.xlsx`.

## Data notes
* `hangSanXuat` / `nhanHieu` (manufacturer / brand) are only populated from mid-2024 onward (0% of 2023 lines, 44% of 2024, ~100% of 2025-26). Year-on-year OEM totals need the coverage adjustment described in `map_vneps.py`.
* `year` is year of manufacture, not award year: use `result_date`. `Amount` is the awarded unit price, so line value = Amount x quantity.
