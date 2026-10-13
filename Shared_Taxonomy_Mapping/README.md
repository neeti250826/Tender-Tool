# Shared taxonomy mapping (Clearstate OU / Sub-OU / Product Category / Company / Family)

Originally `Claude Mapping/mapping/`. Used by `Vietnam_VNEPS/mapping` directly and by `Shared_TURMECA_Pipeline/vocab_rules.py` as the matching core.

* `taxonomy.py` - loads `Mapping_Taxonomy.xlsx` (dim_overview -> OU, dim_subview -> Sub-OU, dim_product -> Product Category, dim_company -> Company, dim_procedure -> Family), normalises text and builds an inverted token index.
* `matcher.py` - keyword (distinctive tokens, locality-checked) first, then advisory fuzzy word-similarity with rapidfuzz. No embeddings.
* `enrich.py` - additive recall boosters applied only where the precise matcher left a dimension blank: bilingual EN/VN keyword layer and multi-token supplier match, each tagged with its method for audit.

Philosophy: precision first. A small clean mapped set beats a large polluted one; recall is tuned afterwards.
