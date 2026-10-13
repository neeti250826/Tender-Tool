# Independent review — Turkey repair v2

Reviewed: 2026-09-30 20:14 IST  
Role: independent Reviewer  
Scope: frozen artifacts under `agent_work/turkey_repair_v2` only  
Candidate, adapter, rules, evidence and country outputs modified: **No**

## Release verdict

**DELIVERY READY: NO**

**Release verdict: DO NOT RELEASE AS A COMPLETE TURKEY DELIVERABLE.**

The frozen 75,415-row repair candidate is internally consistent and its evidence chain passes integrity checks. Release still fails because 8,732 rows across 173 notices remain unresolved, EKAP national enumeration remains source-limited, and the 30 recovered exemplar rows contain contract-level results without item descriptions, UOMs or awarded quantities.

## What passed

| Area | Result | Independent result |
|---|---|---|
| Canonical schema | PASS | Both candidate CSVs have the exact canonical 41 columns in order. |
| Candidate counts | PASS | 75,415 rows; 3,149 notices; Turkey/TR only. |
| Status/date scope | PASS | 74,988 `Result Announcement Published` rows and 427 `Contract Signed` rows; zero unparseable or out-of-scope publication dates; zero dates before the matching source closing date. |
| Amount semantics | PASS | All 75,415 `amount` values are numeric and exactly equal the Turkish-locale parse of the corresponding explicit source `contract_fee`. |
| Complete notice groups | PASS | Zero source/candidate group-count mismatches; zero item-sequence, item-description or quantity alignment failures. |
| Dedupe | PASS | Zero blank keys, duplicates or deterministic formula mismatches. |
| Repair accounting | PASS | 75,415 resolved + 12,250 out of scope + 8,732 unresolved = 96,397 source rows; 3,149 + 694 + 173 = 4,016 source notices. |
| Evidence hashes | PASS | All 12,702 raw-evidence entries and all 12,761 artifact-manifest entries exist and match SHA-256. |
| Navigation evidence | PASS | All four referenced screenshots exist; visual checks corroborate the EKAP Turnstile constraint, official e-Devlet result fields and official bulletin provenance. |

The immutable workbook and diagnostic CSV also match their recorded SHA-256 values. The adapter hash is `0363cf14f62dc930a0dcee3f544693822feb60a8e439ee4291791cf9eff8bf71` and matches the artifact manifest.

## Coverage-gap recovery

The 30-row exemplar file is accurate **as contract-level evidence**:

| IKN | Rows | Official result-page match | Bulletin provenance | Item completeness |
|---|---:|---|---|---|
| 2025/204462 | 9 | PASS | PASS | FAIL — no item description, UOM or quantity |
| 2025/144491 | 3 | PASS | PASS | FAIL — no item description, UOM or quantity |
| 2025/243166 | 1 | PASS | PASS | FAIL — no item description, UOM or quantity |
| 2024/1804770 | 17 | PASS | PASS | FAIL — no item description, UOM or quantity |

All 30 rows re-parse exactly from the stored official e-Devlet result pages on publication date, supplier and contract amount. Each IKN also appears in its recorded dated official goods-result bulletin PDF, and each PDF hash matches. The recovery is therefore 30 contract records, not 30 awarded item records.

## Deterministic spot checks

- Candidate row 2 — IKN `2018/106435`, publication `2025-02-04`, TRY 6,150: exact official result-detail match and exact source `contract_fee` match.
- Candidate row 37,709 — IKN `2024/807977`, publication `2024-11-11`, TRY 797,500: official notice has the unique result date and matching HC Group contract; source `contract_fee` matches.
- Candidate row 75,416 — IKN `2026/99834`, publication `2026-03-05`, TRY 1,995,962.60: official notice has the unique result date and matching Şekeroğlu contract; source `contract_fee` matches.
- Exemplar `2025/204462`: nine result pages and bulletin pages 189–197 support nine contract rows; item-level detail remains absent.
- Exemplar `2025/243166`: the official result page and 10 June 2025 bulletin support the TRY 2,882,200 contract; item-level detail remains absent.

## Blocking findings

1. **Unresolved target population:** 8,732 rows across 173 notices remain unresolved. Sixty-two notices are not in an awarded/completed status; 111 do not have a resolved final-result publication date.
2. **National enumeration is incomplete:** EKAP v2 remains Turnstile-gated, the e-Devlet route verifies known IKNs but does not enumerate unknown IKNs, and this repair run did not enumerate the full daily 2024–2026 bulletin archive.
3. **The exemplar supplement is not line-item data:** all 30 rows lack item description, UOM, awarded quantity, buyer and awarding agency.

Residual warnings that do not alter the binary verdict: nine repaired rows have blank `supplier_name`, 106 have blank `supplier_name_english`, all `item_uom_english` values are blank, and OEM/manufacturer fields were intentionally not populated in this repair pass.

## Permitted use

`frozen_candidate_data.csv` may be used as an evidence-backed **candidate** for the 3,149 resolved source notice groups, subject to downstream approval. The amount is contract-level and may repeat on multiple item rows, so it must not be summed naively.

`coverage_gap_candidates.csv` may be used only as a contract-level lead/evidence supplement for the four named exemplars. It must not be represented or merged as complete awarded item coverage.

Do not claim national Turkey completeness, all-award enumeration, item completeness for the 30 exemplar rows, or OEM/manufacturer attribution from blank OEM fields.

## Final conclusion

The repair’s **frozen candidate integrity passes**, but **delivery readiness fails**. Keep `delivery_ready=false` until unresolved targets are closed or explicitly dispositioned, national coverage is enumerated through an approved official route, and contract-level exemplar leads are either enriched to verified item detail or kept visibly separate from item-level output.
