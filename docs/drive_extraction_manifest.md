# Google Drive Extraction Manifest

Extraction date: 2026-06-25

This manifest records the Google Drive sources used to populate the Singapore, Malaysia, and Vietnam tender folders.

## Singapore

Source folder: `Singapore GeBIZ`
Drive folder: `https://drive.google.com/drive/folders/1AdVWRmwt7I_sBA1BJ9wte_60KCJtqXxm`

Extracted to `Singapore/drive_extracts/Singapore_GeBIZ/`:

- `README.md` from Drive file `1Q3QNvdl4WZGJMRsUzatvPfEP-KXcAu9l`
- `requirements.txt` from Drive file `1UWabbMHHE02ZKND1KPNkrNwPrfTU3XUU`
- `gebiz_scraper.py` from Drive file `1mVgGVeHYYlnRch0eRyrHsY3VmH84EODx`
- `gebiz_scraper_notebook.ipynb` from Drive file `1iEoBDnDO6wK2v7Tlq-iaKEyhNvMpsgS2`

The active Singapore scripts remain in `Singapore/scripts/`.

## Malaysia

Source folder: `Malaysia MOH`
Drive folder: `https://drive.google.com/drive/folders/1nr5Hb5AfKGJU0eCPy7vdc2hWyiJtttrp`

Extracted:

- `Malaysia/scripts/moh_scraper.py` from Drive file `1ZS-AgUyjbQ2IeMpdznJx9X_THZngFZgY`
- `Malaysia/scripts/moh_scraper_notebook.ipynb` from Drive file `1myh0oRchL6OUEhOqF_C_ueyTgVmUCJtI`
- `Malaysia/scripts/moh_scraper_notebook_commands.py` from parsed notebook code cells
- `Malaysia/docs/MOH_Tender_SOP.docx` from Drive file `11QriMVHShy_kRfDSel6ft8UHbszzPzPF`
- `Malaysia/latam_spec_defaults.py`, `Malaysia/mdt_export.py`, `Malaysia/mdt_schema.py` copied from the matching local helper modules used by the scraper pattern

Related Drive output folder also found: `MOH_Malaysia` at `https://drive.google.com/drive/folders/1pIp_s5g9HBz-1elUfcJAzXOjplBsWG4f`.

## Vietnam

Source folder: `Vietnam`
Drive folder: `https://drive.google.com/drive/folders/1L3fjSMBLWjF8A6H27PB8fOb8yKtA8NrP`

Extracted:

- `Vietnam/scripts/vietnam_tender_scraper_colab.ipynb` from Drive file `1KywiQvf7cs9R5btLOuy9bigQ3ZPx5VTQ`
- `Vietnam/scripts/vietnam_tender_scraper_from_notebook.py` from parsed notebook code cells
- `Vietnam/docs/Vietnam_Tender_SOP.docx` from Drive file `1Dd-p_kmYWaEja7k21SYkmjHiyqZoAyZW`

Related Drive output files found in the Vietnam folder include `awarded_tenders.xlsx`, `awarded_tenders` Google Sheet, and `awarded_tenders.csv`.
