# Independent review — KSA repair v2

Reviewed: 2026-09-30 20:34 IST  
Role: independent Reviewer  
Scope: superseding frozen artifacts under `agent_work/ksa_repair_v2` only  
Candidate, adapter, rules, evidence and country outputs modified: **No**

## Release verdict

**DELIVERY READY: NO**

**Release verdict: DO NOT RELEASE AS A COMPLETENESS-CERTIFIED KSA DELIVERABLE.**

The superseding 41,741-row NPT candidate passes structural, group, sequence, cancellation and evidence-integrity checks. Delivery still fails because 19 of 43 current NPT Final Result notices remain unresolved, the 32-page NDP inventory exposes no official Final Result attachment, and every candidate row lacks amount, currency, awarded quantity and contract period under the approved non-fabrication policy.

## What passed

| Area | Result | Independent result |
|---|---|---|
| Canonical schema | PASS | NPT and header-only NDP outputs have the exact 41 canonical columns in order. |
| Candidate freeze | PASS | 41,741 rows across 24 unique complete NPT groups. |
| Critical fields | PASS | Zero blanks across reviewed identity, status, supplier, date, item-description, notice and evidence-key fields. |
| Dedupe | PASS | Zero blank or duplicate `_dedupe_key` values; every candidate key has exact row-level evidence. |
| Item numbering | PASS | Superseding freeze uses consecutive `1..N` item numbers within every notice; zero sequence or duplicate failures. |
| Status and dates | PASS | All rows are `Final Result`; all dates parse and are within 2024-01-01 through 2026-09-30; `awarded_date` equals the supported publication-date proxy. |
| Complete groups | PASS | All 24 replacement-ledger slices reconcile to candidate and evidence rows; zero unresolved in-scope rows occur inside emitted groups. |
| Cancellation segregation | PASS | 3,299 cancellation/not-awarded rows are separate; zero candidate overlap. |
| Commercial-field exclusion | PASS | Booklet price, generic QTY and generic period text do not contaminate canonical award fields. |
| Evidence hashes | PASS | All 385 manifest entries exist and match SHA-256. |
| Navigation | PASS | Five documented steps resolve to existing screenshots; visual checks corroborate the Final Results listing, booklet-price exclusion and row-level PDF tables. |

The final candidate SHA-256 is `59c5e31804c53bc2dfac7449b1e689b6ea27a08ebec9919184bc03a692587ec7`.

## Complete-group and cancellation accounting

The 24 replacement groups sum exactly to 41,741 candidate rows. Their ledger slices, notice IDs and row-level evidence all reconcile without mismatch. The complete groups include 2,403 segregated cancellation rows.

Across the full target population, `npt_cancelled_rows.csv` contains 3,299 rows:

- 3,060 explicit `CANCELLED`, `NO ACCEPTED OFFER`, `NO BID`, `NO QUOTE` or `HOLD` dispositions.
- 239 fail-closed `not_awarded_blank_supplier` rows.
- Zero rows overlap awarded candidates.

## Fourteen formerly failed PDFs

All 14 PDFs are machine-readable; OCR was correctly not invoked. Thirteen structured layouts were extracted. `NPT0048/24` remains unresolved because the one-page official announcement contains manufacturer names but no item/supplier award table.

Six of the 14 now support complete replacement groups: `NPT0008/25`, `NPT0021/24`, `NPT0033/24`, `NPT0038/25`, `NPT0047/24`, and `NPT0064/25`.

Eight remain explicitly unresolved: `NPT0015/25`, `NPT0018/25`, `NPT0020/25`, `NPT0027/25`, `NPT0028/25`, `NPT0043/25`, `NPT0046/24`, and `NPT0048/24`. Four have no medtech rows after the 41/42-code scope rule, three lack an explicit PDF-printed result date, and the last is non-tabular.

## NDP layer

The official sitemap snapshot contains 32 unique NDP detail pages. All 32 report no Final Result attachment; `official_ndp_final_results.json` and `ndp_candidate_rows.csv` therefore contain zero data rows. This is correct fail-closed behavior. It means **zero evidenced NDP award candidates in the captured source**, not “no NDP awards exist.”

## Commercial-field policy

Twenty notices and 40 downloaded attachments were checked. No explicit award-labelled amount, ISO currency, awarded quantity or numeric contract period was found.

- Nineteen tender booklet prices were observed and excluded. The NPT0056/24 screenshot confirms `9200 SAR` is labeled **Tender Booklet Price**, not award amount.
- NPT0043/25 contains 1,083 generic `QTY` evidence rows; none was mapped to awarded `quantity`.
- Ten generic agreement/contract-period clause mentions were found; none supplied an explicit award duration, so no period was accepted.
- Candidate contamination: zero amount, quantity, currency or period values derived from these fields.

This is source-correct but incomplete: all 41,741 rows have blank amount, currency, quantity and contract period; 37,510 also have blank UOM. The data cannot support award-value totals, awarded-quantity analysis or contract-duration analysis.

## Deterministic spot checks

- Candidate row 2 — `NPT0002/25`, item 1: ALRAMLY MEDICAL COMPANY / NIMASO GROUP / TEOS-30 matches official PDF page 1 and its recorded hash.
- Candidate row 20,872 — `NPT0021/24`, item 1,843: DRAEGER ARABIA CO LTD / DRAEGER MEDICAL / model 6870279 matches official PDF page 58 and its recorded hash.
- Candidate row 41,742 — `NPT0064/25`, item 328: LAB TECHNOLOGIES TRADING COMPANY / DUCHEFA BIOCHEMIE / model F3001 matches official PDF page 17 and its recorded hash.
- Visual evidence for NPT0056/24 distinguishes awarded supplier rows from `NO ACCEPTED OFFER` rows and separately labels the tender booklet price.
- Visual evidence for NPT0044/25 shows supplier, manufacturer, country, catalog and item fields in the official result table, consistent with the retained row-level evidence model.

## Blocking findings

1. **Unresolved NPT coverage:** 19 of the 43 current official NPT Final Result notices are unresolved. The 24 complete groups and 19 unresolved groups reconcile exactly to the current 43-notice inventory.
2. **No supported NDP award rows:** none of the 32 captured NDP detail pages exposes a Final Result attachment.
3. **Tender-detail incompleteness:** every candidate row lacks amount, currency, awarded quantity and contract period; most lack UOM.

Manufacturer text is present as advisory `likely_oem` on 37,626 rows, but `mapped_oem` is blank throughout because no canonical alias approval was performed. Also, evidence CSV paths are absolute references to the existing `agent_work/ksa` evidence tree; they resolve and hash correctly in this workspace, while portable consumers should use the v2 copies and manifest-relative paths.

## Permitted use

`npt_candidate_rows.csv` may be used as a best-available, evidence-backed replacement candidate for **exactly the 24 complete NPT notice groups**. It supports supplier, item and source-observed manufacturer analysis, subject to the advisory OEM limitation. It must not be used for award-value, awarded-quantity, contract-period or national-completeness claims.

`npt_candidate_evidence_rows.csv` is permitted for traceability. `npt_cancelled_rows.csv` is an audit only and must never be merged into awarded rows. The empty NDP candidate correctly records the lack of supported Final Result attachments; it must not be interpreted as proof of market absence.

## Final conclusion

The superseding freeze’s **candidate integrity passes**, but **delivery readiness fails**. Keep `delivery_ready=false` unless the 19 unresolved NPT groups are closed or formally dispositioned, NDP award evidence is located and independently reviewed, and the missing commercial/tender-detail fields are either sourced explicitly or the final use is formally narrowed to a clearly labeled best-available supplier/item evidence dataset.
