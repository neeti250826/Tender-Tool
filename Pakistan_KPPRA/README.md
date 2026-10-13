# Pakistan (KP) - KPPRA evaluated tenders (kppra.gov.pk)

`evaluated_tenders.php` filters only when **all** form parameters are sent (tender_ref, fromDate, toDate, dpart_id, tender_type_id, sort_field, sort_order, search, p). Only ~54 health-entity evaluations exist, mostly technical-only.

* `kppra_lists.py` - page through evaluations for selected health entities -> `kppra_evaluated.csv`. The entity id list was built from the portal's department dropdown (the referenced scratchpad JSON is that list; `ENT_OLD` inline is a usable subset).
* `ocr_ayub.py` - OCR of the sample reports downloaded under `docs/`.
