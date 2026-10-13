# Honduras - ONCAE open data (datosabiertos.oncae.gob.hn) and HonduCompras SICC

ONCAE publishes OCDS yearly workbooks `HC1_datos_YYYY.xlsx` (+ `CE_`, `DDC_`), 2005-2026, refreshed weekly, with line-level awards (description, UNSPSC, qty, unit price, supplier). curl needs `--ssl-no-revoke`. `buyer/name` is the purchasing unit; the institution (IHSS, SESAL ...) is in `parties` / `par_memberOf`.

* `hn_load.py` - load the yearly xlsx into per-year pickles of the needed sheets.
* `hn_member.py` - stream only `par_memberOf` (unit -> institution).
* `hn_extract.py` - tag IVD / diabetes lines with `Shared_ES_HN_Pipeline/tagger.py` (HC1 awards + open tenders, CE orders).
* `sicc_search.py` - HonduCompras SICC historical process search (ASP.NET WebForms postback).

Pipeline continues in `Shared_ES_HN_Pipeline` (`build_rows.py` -> `write_workbook.py`).
