# CAPT / DRAP Gap Audit

This file records the remaining known evidence gaps for the two target sources after the latest source-backed review pass.

Date checked: `2026-05-31`

## CAPT

Current saved output:

- `Kuwait/CAPT/output/capt_awarded_medical_2024_2026.csv`
- strict medical-only rows: `42`

What was rechecked:

- local `2024/73` page images `44` to `47`
- local `2024/21` OCR scan across pages `1` to `55`, with focused read of pages `17`, `29`, and `50`
- local `2025/39` page images including `21` and `22`
- local `2025/41` downloaded candidate PDF, which resolved to the same `2025/50` meeting content already reviewed
- local `2025/50` page images including `42` to `47`
- local `2025/40` page images including `24` to `26`, `36` to `39`, `55` to `61`
- local `2025/40` OCR page `54` direct-contract block
- local `2026/5` page images including `60` to `65`
- local `2026/5` page images including `56` to `61`
- newly downloaded official CAPT PDFs `77bf21cd-97f4-40f8-8639-e7ba90002efd.pdf` and `b1e3ac1b-011d-4b32-a047-67b2e27c9631.pdf`

What was newly materialized:

- `2026/5` page `62` was promoted from candidate to saved output as notice `033AK5`, a Ministry of Health direct-contract approval for `STAY-SAFE CAPD 1.5% 2L` peritoneal dialysis solution from `Mohammad Naser Al Hajri & Sons / Fresenius Medical Care`, amount `95,580 KWD`, published `2026-01-25`.
- `2025/40` page `55` clarified that `4AK056` is a non-approval, while `057AK4` is the approved dialysis row that belongs in the saved output.
- `2025/40` page `60` clarified the corrected approved notice IDs and values `4TB522`, `5EY009`, and `5IN026`.
- `2025/40` OCR page `54` was rechecked and confirmed to be a documentation gap rather than a data gap: its approved Ministry of Health direct-contract rows `4AK042`, `4AK048`, and `4AK055` are already present in `Kuwait/CAPT/capt_verified_seeds.py` and already represented in the saved CSV.

What remains blocked:

- The live winning-bids page is still anti-bot constrained from this environment.
- Browser-side retesting on `2026-06-01` confirmed that the CAPT summary winning-bids table is still reachable in browser context, but popup-level item requests are still blocked: `GET /en/tenders/winning-bids-popup/1/2024/2025--112 => 403`.
- The CAPT scraper now treats summary-table rows as package rows rather than reusing the visible summary serial number as a true `item_no`, so future live fallback rows will not silently imply mixed item numbering while popup item detail remains blocked.
- The extra medically relevant CAPT pages reviewed after the current corrected `42` rows were materialized are still not new award-result rows.
- The newly discovered cached `preprod.capt.gov.kw` winning-bids path cannot currently be fetched directly from this environment because `preprod.capt.gov.kw` does not resolve over direct network fetch here.
- The newly downloaded official `2024/21` board-minutes PDF is a real CAPT source, but the reviewed candidate pages do not contain a Ministry of Health awarded/post-award cluster.
- The newly downloaded official June 22, 2025 CAPT PDF resolves to meeting `2025/50`, and its reviewed healthcare-adjacent pages still do not contain a new awarded/post-award medical-only row.
- Two additional `files.capt.gov.kw` PDFs surfaced by web search looked promising from search-result snippets, but one resolved to meeting `2021/94` with publication date `2021-12-12` and the other resolved to meeting `2020/81` with publication date `2021-01-03`, both outside the target window. Their medical-looking content consists of old direct-contract approvals, amount adjustments, extensions, and non-approvals that do not satisfy the `2024-01-01` to `2026-05-28` publication-date requirement.

Specific reviewed non-award examples still excluded:

- `2024/73` page `44`: article `17` initiation items for `METOPROLOL SUCCINATE 95MG`, `SUMATRIPTAN SUCCINATE MG50`, and `AUTOMATED PROTECTOR STERILE SLUSH`
- `2024/73` page `45`: article `17` initiation item for `INSULIN PUMP`
- `2024/21` page `17`: Ministry of Finance electronic-payment direct contract, not healthcare procurement
- `2024/21` page `29`: Public Fire Force firefighting devices/equipment award recommendation, not medical equipment
- `2024/21` page `50`: Public Works road-maintenance change/extension order, not healthcare procurement
- `2025/39` page `21`: disability-authority resident-service contract extension with `Al Eissa Medical and Scientific Devices Company`, but still a service-contract extension rather than a medical equipment/consumables procurement row
- `2025/39` page `22`: Oracle / `EXADATA` / `EXALOGIC` launch page, not a healthcare award row
- `2025/50` page `42`: Kuwait University initial-bond extension items for licensing/security/telescope supply, not award rows
- `2025/50` page `43`: Kuwait University initial-bond extension items for laboratory/scientific devices, not award rows
- `2025/50` page `44`: Kuwait University server/storage extension approval, but non-healthcare IT infrastructure
- `2025/50` page `45`: Kuwait University medical-waste-disposal-device recommendation, but the board explicitly did not approve the entity recommendation
- `2025/50` page `46`: Kuwait University cancellation of laboratory-equipment line items plus complaint about nursing/technical staffing, not award rows
- `2025/50` page `47`: Ministry of Oil / Kuwait Oil publication and extension items, not healthcare award rows
- `2025/40` page `55`: direct contract `4AK056` for `STAY-SAFE CAPD 1.5% 2L`, but explicit non-approval because of high value
- `2025/40` page `55`: direct contract `060AK4` for low-calcium CAPD solution, but explicit non-approval because of high value
- `2025/40` page `56`: direct contract `46AKD4` for `PRISMAFLEX PLASMA / FILTRATION TPE`, but explicit non-approval because of high value
- `2026/5` page `56`: article `17` dermatology / racecadotril items, but only model-contract follow-up plus explicit non-approval
- `2026/5` page `57`: article `17` epilepsy-treatment medicine and absorbent-cotton items, both explicit non-approvals
- `2026/5` page `58`: article `17` multiple-sclerosis and hospital-medicine items, both explicit non-approvals
- `2026/5` page `59`: article `17` psychiatric-treatment medicine, blood-bank equipment, and CT-scanner-support items; decisions are non-approval, response-follow-up, and deferral
- `2026/5` page `60`: article `17` washer-disinfector and dental-suction items; decisions are postponement pending bid-security renewal and explicit non-approval
- `2026/5` page `61`: life-support / trauma-training manikins page, but still only an approval to proceed with a public practice under article `17`
- `2026/5` page `63`: publication/appendix decisions, not award rows
- `2026/5` page `64`: insurance-extension and cancellation/recommendation items, not award rows
- `2026/5` page `65`: dental-health-system recommendation with explicit non-approval
- `2025/40` pages `24` to `26` and `36` to `39`: non-healthcare or non-award entities/pages

Specific live/cached-source observations:

- Web search cache exposes `https://preprod.capt.gov.kw/en/tenders/winning-bids/?page=2` as a valid CAPT winning-bids page with rows `11` to `20`, including non-healthcare entities such as Ministry of Electricity & Water, Kuwait Oil Company, Public Authority for Civil Information, Civil Aviation, and Public Authority for Industry.
- A direct fetch attempt for `https://preprod.capt.gov.kw/en/tenders/winning-bids/?page=1` from this environment failed with `Could not resolve host: preprod.capt.gov.kw`, so the cached preprod path is a promising next lead but could not be expanded into page `1` or later pages today.
- Direct fetch of the current public winning-bids page still returns a Cloudflare `Just a moment...` challenge from this environment.
- Search-engine result recency on `files.capt.gov.kw` is not reliable evidence of in-window CAPT publication date. Two result snippets appeared as recent, but the underlying PDFs were old `2020/81` meeting pages posted on the CAPT site with `2021-01-03` publication text.

Practical conclusion:

- The newly surfaced `2026/5` dialysis direct-contract row has been materialized, and the `2025/40` medical block has now been corrected against the page images so the saved CAPT output carries the right approved rows and values (`057AK4`, `4TB522`, `5EY009`, `5IN026`) while excluding the nearby non-approved rows (`4AK056`, `060AK4`, `46AKD4`). The additional `2024/21`, `2025/41`/`2025/50`, and old-`2020/81` CAPT candidates were reviewed and ruled out as non-healthcare, non-award, explicit non-approval, or out-of-window material. No additional reviewed CAPT local/live evidence row is currently strong enough to add honestly as another awarded or post-award medical-only record.
- The saved-browser fallback now makes the CAPT summary table reusable in the repo, but the user-reported mixed-item concern remains open because popup-level item content is still externally blocked rather than parsable from the current browser session.

## DRAP

Current saved output:

- `Pakistan/DRAP/output/drap_item_medical_2024_2026.csv`
- medical/lab-only item rows: `371`

What was rechecked:

- current seed inventory in `Pakistan/DRAP/drap_verified_seeds.py`
- current output grouping by `notice_id`
- official public DRAP surface already used for the existing seven medical/lab seed sources
- live DRAP tender index pages `1` to `3`

What remains blocked:

- The current remaining low-count DRAP notices are low-detail source pages, not parser misses.
- The `2026-03-25` invitation is a one-page invitation without an attached item schedule in the public source currently available here, so it remains correctly materialized as one package row.
- The `2024-05-31` FTIR notice is a one-equipment tender and is already fully materialized as one row.

Specific live-source observations:

- DRAP tenders page `1` currently lists the already-materialized `2026-03-25` chemicals/glassware/reference-standards invitation and the already-materialized `2025-09-05` chemicals/reagents/reference-standard/glassware/kits invitation, alongside out-of-scope services such as record management, shipping containers, pricing survey, and support staff.
- DRAP tenders page `2` currently lists the already-materialized `2025-01-16` lab-equipment post plus out-of-scope items such as machinery & IT equipment, tax consultant, repair & maintenance, janitorial, security, and internet.
- DRAP tenders page `3` currently lists the already-materialized `2024-05-31` FTIR post, the already-materialized `2024-02-23` chemicals/glassware prequalification post, the already-materialized `2024-02-14` retender, and the already-materialized `2024-01-10` NCLB chemicals/glassware/equipment/reference-standards tender.
- Direct fetch of DRAP tenders page `4` timed out from this environment on `2026-05-29`, but page chronology still shows no missing in-window medical/lab tender pages beyond page `3`: page `3` already reaches `2024-01-10`, while page `5` is down in `2021`, so page `4` falls outside the current `2024-01-01` to `2026-05-28` target window.

Practical conclusion:

- There is no currently verified additional DRAP item schedule in the reviewed evidence pool that can be expanded into more rows without inventing details not exposed by the public source.
