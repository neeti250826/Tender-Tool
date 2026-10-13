# El Salvador - COMPRASAL (comprasal.gob.sv) and legacy COMPRASAL II (unacv2.mh.gob.sv)

* New COMPRASAL (Oct 2024 ->): public API `/api/v1/publico/obtener/procesos/publicos?page=&per_page=1000`, `/obtener/detalle/procesos/publicos/{procId}`, `/obtener/informe-adjudicacion/{awardId}`. Award lines carry supplier + amount but no item names.
* Legacy COMPRASAL II (2019 - mid 2023): `unacv2.mh.gob.sv/comprasalmicro/...` still public; award PDFs parse to line level. Endpoints and parsing notes in `es_legacy_notes.md`.
* Gap: awards May 2023 -> Oct 2024 are in neither system; transparencia.gob.sv and salud.gob.sv are Cloudflare-blocked (use Wayback).

Scripts:
* `es_fetch_details.py` - process detail + award report for every tagged process, cached to `es_details/`.
* `retag_es.py` - re-tag COMPRASAL award rows with the current tagger -> `es_tagged.pkl`.

Pipeline continues in `Shared_ES_HN_Pipeline`.
