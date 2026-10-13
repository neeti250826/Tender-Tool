# Pakistan (federal) - PPRA EPMS (epms.ppra.gov.pk)

`ppra.org.pk/contract_org` now redirects to EPMS. `/public/contracts` holds ~694 contracts (almost no medical); `/public/evaluations` holds ~3,676 bid evaluation reports, ~99 medical, each with a `/pdf?file=` report. Needs a Pakistan-side egress.

* `epms_contracts.py` - all pages of the contracts register -> `epms_contracts.csv`.
* `epms_evaluations.py` - evaluations register -> `epms_evaluations.csv`.
* `dl_bers.py` - download the medical-keyword evaluations' PDFs -> `ber/`.
* `ocr_bers.py` - OCR the scanned reports (Tesseract; package reports need OSD rotation) -> `ber_text.json`.
* `parse_federal.py` - two formats: EPADS item reports (item / UNSPSC / bidder / marks / offer, offers are line totals) and package reports (evaluated cost, Most Advantageous Bidder) -> `PK_Federal_Evaluations_Mapped.xlsx`.
