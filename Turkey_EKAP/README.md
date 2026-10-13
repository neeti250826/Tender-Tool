# Turkey - EKAP v2 (ekapv2.kik.gov.tr)

EKAP's list and detail APIs sit behind Cloudflare Turnstile (`HTTP 428 HUMAN_VERIFICATION_REQUIRED`). The user passes the verification in their own Edge/Chrome started with `--remote-debugging-port=9222`; the scripts attach over CDP and call the API from inside that verified tab. Rate limit is about one call per 30 s for both list and detail. Never call `browser.close()` over CDP.

## extractor/ (Node, playwright-core)
* `ekap_lib.js` - attach to the EKAP tab, build the `X-Custom-Request-*` AES headers, `post()` helper.
* `ekap_extract_medtech.js` - stage 1: tender lists per in-scope OKAS (CPV) code x year 2024-2026 -> `lists/`; stage 2: one detail per tender id -> `details/`. Resumable. Inputs `code_counts.json`, `code_relevance.json`.
* `ekap_count.js`, `ekap_hdrs.js`, `ekap_probe.js`, `ekap_session.js`, `ekap_why.js`, `ekap_ratetest*.js`, `cdp_snap.js`, `reload.js` - probes used to find the headers, session behaviour and rate limit.

## build_turkey.py
One row per contract x lot from every detail JSON. Award year = contract date. Line value only when a contract has exactly one lot. Category from the lot name (Turkish rules first, then translated English) through `Shared_TURMECA_Pipeline/vocab_rules.py`; Company only when the supplier is an OEM affiliate. Output `TR_EKAP_MedTech_Mapped.xlsx`, `tr_ekap_lots_all.csv`.

## supplier_brand_assignment/
IVD brand assignment for EKAP suppliers (earlier IVD-scoped pull): `tr_brand_rules.py` (name-based brand detection), `tr_supplier_profile.py`, `tr_make_batches.py`, `tr_rule_assigned.json`, and the `CODEX_PROMPT_turkey_ivd_brands.md` research brief.

The earlier Python extractor (`ekap_extract.py`, runbook, IVD CPV codebook) lives in a separate local project and is mirrored in Clearstate-SG/Tender-Tools under `turkey-ekap/`.
