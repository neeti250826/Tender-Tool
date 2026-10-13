# Claude Mapping tender extraction scripts

Scripts from the local Claude Mapping workspace (Claude Code sessions, Jul-Oct 2026), organised one folder per **Country_Website**. Shared pipeline code that several countries import sits in the `Shared_*` folders.

Only code, small config inputs and notes are included. Raw downloads (PDFs, JSON caches, HTML snapshots), pickles, translation caches and the generated xlsx deliverables stay outside GitHub.

| Folder | Country | Website / source | What the scripts do |
|---|---|---|---|
| `Vietnam_VNEPS/` | Vietnam | muasamcong.mpi.gov.vn (VNEPS winning-bid unit-price DB) | Browser-console extractor for awarded medtech lines + the taxonomy mapping / merge / market-sizing pipeline |
| `Turkey_EKAP/` | Turkey | ekapv2.kik.gov.tr (EKAP v2) | In-page API extractor run over CDP in the user's verified browser tab, lot-level build, IVD supplier brand assignment |
| `SaudiArabia_NUPCO/` | Saudi Arabia | nupco.com tenders + Final Result / Item List PDFs | Harvest tender pages, download item lists, parse final-result PDFs, build mapped award table |
| `Kuwait_CAPT/` | Kuwait | capt.gov.kw winning bids | Month-by-month crawl of award list + item popups, mapped volume table |
| `UAE_Dubai_eSupply/` | UAE | esupply.dubai.gov.ae past opportunities (JAGGAER) | Per-day xls exports for Health buyers, item-line parse, volume table |
| `Pakistan_KP_DGHS/` | Pakistan (KP) | dghskp.gov.pk / healthkp.gov.pk bid evaluation reports | Parse Govt. MCC and DGHS BER PDFs to bid rows, winners, mapped table |
| `Pakistan_PPRA_EPMS/` | Pakistan (federal) | epms.ppra.gov.pk contracts + evaluations | Scrape registers, download medical BER PDFs, OCR, parse to mapped table |
| `Pakistan_KPPRA/` | Pakistan (KP) | kppra.gov.pk evaluated tenders | List health-entity evaluations, OCR sample reports |
| `Pakistan_Sindh_PPRA/` | Pakistan (Sindh) | pprasindh.gov.pk | Reachability / link probe only (portal needs a Pakistan IP) |
| `Honduras_ONCAE/` | Honduras | datosabiertos.oncae.gob.hn OCDS yearly xlsx, sicc.honducompras.gob.hn | Load OCDS files, extract tagged IVD / diabetes lines, SICC historical search |
| `ElSalvador_COMPRASAL/` | El Salvador | comprasal.gob.sv API + legacy unacv2.mh.gob.sv | Fetch process detail + award reports, re-tag, legacy source notes |
| `Shared_ES_HN_Pipeline/` | ES + HN | - | Keyword-map tagger, buyer segments, row assembly, workbook writer, donor-source notes |
| `Shared_TURMECA_Pipeline/` | TR, KSA, KW, UAE, PK | - | Vocabulary layer (EN/TR/AR), cached translation, master / raw / CY2025 workbook builders, Google Sheet write-back |
| `Shared_Taxonomy_Mapping/` | all | - | Clearstate taxonomy loader + keyword/fuzzy matcher used by every mapping step |

## Original layout and imports

The scripts are copied verbatim, so their relative imports still describe the original tree:

```
Claude Mapping/
  vneps_console_extractor.js
  mapping/            -> Shared_Taxonomy_Mapping + Vietnam_VNEPS/mapping + Turkey_EKAP/supplier_brand_assignment
  es_hn_tenders/      -> Shared_ES_HN_Pipeline + Honduras_ONCAE + ElSalvador_COMPRASAL
  turmeca/            -> Shared_TURMECA_Pipeline
    ekap/ ksa/ kuwait/ uae/ pakistan/   -> the Country_Website folders
```

* TURMECA country builders do `sys.path.insert(0, parent_dir)` and import `vocab_rules` / `translate`. Run them with `PYTHONPATH` pointing at `Shared_TURMECA_Pipeline`, or recreate the tree above.
* ES/HN scripts import `tagger`, `buyers`, `notes_base` from their own folder. Put `Shared_ES_HN_Pipeline` on `PYTHONPATH`.
* `Vietnam_VNEPS/mapping/*.py` add `<WORKSPACE>/mapping` to `sys.path`; point that at `Shared_Taxonomy_Mapping`.
* Node scripts `require('playwright-core')`; run `npm i playwright-core` next to them (they were originally required from an absolute workspace path).
* Local machine paths and Google Sheet / Doc IDs were replaced with placeholders before publishing: `<WORKSPACE>` (the Claude Mapping folder), `<DOWNLOADS>`, `<HOME>`, `<LOCAL_APPDATA>`, `<TURKEY_IVD_PROJECT>` (the earlier EKAP IVD pull), `<TAXONOMY_SHEET_ID>`, `<MASTER_SHEET_ID>`, `<WORKING_SHEET_ID>`, `<TENDERS_DOC_ID>`, `<SOP_DOC_ID>`. Fill them in before running.

## Python / Node dependencies

```
pip install openpyxl pandas numpy rapidfuzz pdfplumber PyMuPDF python-docx requests
npm install playwright-core
```

OCR steps (`ocr_bers.py`, `ocr_ayub.py`) need a local Tesseract install.
