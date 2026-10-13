# Shared El Salvador / Honduras IVD + diabetes pipeline

Built Oct 2026 for `ES_HN_IVD_Diabetes_Tenders_2019-2026.xlsx` (249 indicator codes from the ES/HN keyword map).

* `tagger.py` + `keyword_map.json` - `tag(item, title, buyer, unspsc)` returns the most specific indicator code; ancestors of other hits are dropped, sibling leaves collapse to their parent.
* `buyers.py` - buyer segment (clinical vs non-clinical lab, etc.) and in-scope test per buyer.
* `build_rows.py` - assemble capture-template rows from every source (ONCAE, COMPRASAL new + legacy, donors) -> `eshn_rows.pkl`.
* `write_workbook.py` - the deliverable workbook; `make_notes.py` + `notes_base.py` - the Sources & notes tab.
* `test_tagger.py` - regression cases for the tagger.
* `RAW_SCHEMA.md` - the raw row schema every source is normalised to.
* `donor_notes.md` - Global Fund PQR, World Bank, IDB sources and conventions.
* `translation/BRIEF.md` - the Spanish -> English translation brief and glossary used for the English columns.

Tagging lessons: Spanish 'PCR' (CRP vs molecular), 'tiras reactivas' (urine vs glucose), analyte words that are also medicines, comodato analysers inside reagent lines, multi-product lot lines.
