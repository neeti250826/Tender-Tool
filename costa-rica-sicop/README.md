# Costa Rica SICOP

The missing Codex source package was recovered on 2026-10-13 under `sicop_adapter/`.

- `fetch_sicop_report_slice.js`, `fetch_sicop_all_slices.js`, `fetch_sicop_2026_page2.js`: browser callbacks for the public contracts report API, not standalone Node commands.
- `sicop_supplier_adapter.py`: normalizes captured official supplier/contract evidence.
- `sicop_tracker_delivery2_adapter.py`: later evidence-backed 0.2.0 candidate builder.
- `build_sicop_ccss_all.py`: CCSS report processing from saved browser responses.

Official report: https://www.sicop.go.cr/app/module/pcont/public/ce-contracts-report

The adapters require retained official HTML/JSON and prior reviewed outputs. Historical callbacks retain their CCSS institution and date slices; set scope explicitly for a new extraction. CCSS or selected-supplier coverage does not establish complete national coverage. Earlier data links remain in `SOURCE_DATA.md`; this audit does not refresh those datasets.
