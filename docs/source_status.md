# Procurement Source Status

Checked against the assessment scope for the date window `2024-01-01` to `2026-06-01`.

## United Arab Emirates

### Dubai eSupply

- Script: `UAE/Dubai_eSupply/dubai_esupply_scraper.py`
- Output:
  - `UAE/Dubai_eSupply/output/dubai_esupply_medical_2024_2026.csv`
  - `UAE/Dubai_eSupply/output/dubai_esupply_medical_2024_2026.jsonl`
  - `UAE/Dubai_eSupply/output/dubai_esupply_medical_2024_2026_metadata.json`
- Proven:
  - The source is now wired into the awarded-source runner and can be launched in parallel with the existing awarded scrapers.
  - The scraper was live-tested for `2024-01-01` through `2026-06-01`.
  - The public homepage is reachable and currently reports `0 Current Opportunities`.
  - The homepage confirms healthcare-relevant Dubai entities such as `Dubai Health Authority`.
  - Browser-side inspection now proves separate public `Current Opportunities` and `Past Opportunities` listing pages beyond the homepage path.
  - Saved browser-captured public listing HTML now lets the scraper materialize strict medical listing rows even when shell-side fetches fail.
  - `audit_uae_saved_coverage.py` now proves that across the exact saved UAE listing pages the scraper actually uses, there are `152` logical unique candidate rows from the usable saved captures and `0` remaining obvious healthcare misses left in that saved capture pool.
  - `audit_uae_filter_fields.py` now proves the exact saved UAE past-opportunity filter field names and operators for a browser-backed healthcare extraction: buyer organisation, opportunity publication date, supply category, project categories, the search action, and the pager field.
- Limitation:
  - The current saved UAE output is still only a partial slice of the public listing surface rather than a full paginated `2024` to recent crawl.
  - Browser-driven navigation to the public past-opportunities `page=2` path on `2026-06-01` did produce additional verified saved result sets, and the scraper now ingests them, but end-to-end pagination is still not fully proved.
  - A direct unrestricted fetch attempt for UAE past-opportunities `page=3` on `2026-06-01` still returned only an `invalid or expired session` page, so the remaining UAE pagination gap is now clearly a sessioned-pagination problem rather than a missing saved-page ingestion path.
  - The saved file `uae_past_page1_live.html` is now also confirmed to be only an expired-session page, not a usable listing capture.
  - A browser-backed retest on `2026-06-01` showed that an already-loaded past-opportunities session can still display the real table, but the in-session async search call itself currently fails with `Unable to load .../past/list-async.si status: 401`, and the saved `uae_past_page3_response.html` plus `uae_past_page3_async_response.html` files are still only expired-session shells rather than real listing pages.
  - `uae_page4_session_expiry_note.md` now adds a stronger live repro: clicking the visible `Go to page 4` button from a real `Showing Result 1 - 100 of 180894` past-opportunities session immediately triggered `Your session is invalid or has expired`, so the remaining UAE pagination gap is now directly proven as a session-expiry problem during deeper paging.
  - A deeper live browser page was also observed with `Showing Result 301 - 400 of 180849`, including Dubai Academic Health Corporation healthcare titles such as `Tube Sealer`, `Facio Maxillary`, and `Voyager Implants`. Those deeper browser-verified titles are now materialized in the saved UAE CSV through `uae_past_live_page4_snapshot.md`, which raised the current UAE output to `66` rows. That proves the remaining UAE gap is still real pagination coverage loss beyond the currently captured pages rather than only a filter issue. See `uae_live_session_gap_note.md`.
  - The saved metadata now records `access_state` `public_rows_extracted`, `current_saved_page_count` `3`, `past_saved_page_count` `8`, `current_saved_capture_names` `["current_opportunities_body.html", "uae_current_tab_eval.json", "uae_live_eval.json"]`, `past_saved_capture_names` `["past_opportunities_body.html", "uae_past_page2_async_response.html", "uae_past_page2_response.html", "uae_current_tab_eval.json", "uae_live_eval.json", "uae_page2_postdialog_snapshot.md", "uae_past_live_page2_snapshot.md", "uae_past_live_page4_snapshot.md"]`, `current_total_listed` `324`, `past_total_listed` `180849`, `candidate_row_count` `679`, and `rows_written` `66`.
  - The current filter now recovers the earlier four evidence-backed healthcare rows from the saved UAE captures: `241003` (`TEST KIT; TYPE: INFLUENZA A DUPLEX -BLANKET`), `240359` (`COMSUMABLE ITEM (FILTERS)`), `241143` (Arabic-title medical mattresses), and `241004` (`Calcium&Triglycerides-BLANKET`), plus the deeper page-4 Dubai Academic Health rows `Tube Sealer`, `Facio Maxillary`, and `Voyager Implants`, while deduplicating repeated notice IDs that appeared across current/past captures.
  - The scraper can now also consume saved browser snapshot markdown such as `uae_past_live_page2_snapshot.md`, `uae_page2_postdialog_snapshot.md`, and `uae_past_live_page4_snapshot.md`, and now also saved live-eval JSON artifacts such as `uae_current_tab_eval.json` and `uae_live_eval.json`. The postdialog snapshot and eval JSON captures are valid saved evidence and are now auto-discoverable, but because they are content-equivalent to rows already represented in the deduplicated output they do not change the stable `66`-row UAE result. The newly discovered `uae_tab4_page1_snapshot.md` artifact is only a truncated shell around the table region and does not parse into usable listing rows, while `uae_tab4_snapshot.md` is an expired-session shell. The scraper still keeps only the strongest lifecycle status per logical notice so the same opportunity is not counted twice when both current and past captures are present.
  - The scraper now also inventories saved UAE detail-page captures such as `uae_detail_240780.html` and `uae_detail_241068.html`. The current metadata proves both saved detail pages are expired-session shells rather than usable detail pages, so they do not currently unlock awarded amount, supplier, or stronger status recovery.
  - A later surviving UAE browser tab now also proves a stronger failure mode than the expired-body shells: selecting it raised the alert dialog `Your session is invalid or has expired / Please log in to access the functionality on this page`, which blocked further Playwright snapshot/evaluate actions on that tab. That means the remaining UAE gap is not just missing HTML capture but active session invalidation during live browsing.

## Kuwait

### CAPT

- Script: `Kuwait/CAPT/capt_awarded_scraper.py`
- Local inspection helper: `Kuwait/CAPT/capt_pdf_helper.py`
- Local OCR language data: `Kuwait/CAPT/tessdata/ara.traineddata`
- Verified fallback seed: `Kuwait/CAPT/capt_verified_seeds.py`
- Exclusion note: `Kuwait/CAPT/capt_exclusion_notes.md`
- Output:
  - `Kuwait/CAPT/output/capt_awarded_medical_2024_2026.csv`
  - `Kuwait/CAPT/output/capt_awarded_medical_2024_2026.jsonl`
- Proven:
  - Public winning-bids rows are visible on the live site in browser context.
  - The saved browser response `Kuwait/CAPT/output/capt_winning_bids_browser_response.html` is now parseable by the CAPT scraper, so the repo has a working fallback for the current div-based winning-bids layout when shell-side live fetches are challenged.
  - A medical award row for `Ministry of Health` was verified and saved.
  - Official CAPT board-minutes PDFs on `files.capt.gov.kw` are directly accessible and now backfill additional Ministry of Health awarded/direct-contract rows inside the requested window.
  - The scraper now detects the current anti-bot challenge quickly and falls back to the verified public row instead of hanging on the challenge page.
  - The local helper `capt_pdf_helper.py` now supports OCR with workspace-local Arabic language data, and it now skips out-of-range requested pages with a warning instead of aborting the whole scan.
  - The helper was used to review `2024/73` Ministry of Health pages `32` to `45`, the newly downloaded official `2024/21` CAPT PDF candidate, the already-seeded `2025/39` disability-authority extension page `21` plus the nearby non-healthcare page `22`, the `2025/40` medical direct-contract block, the newly downloaded official `2025/50` CAPT candidate, the `2026/5` page cluster, and additional `files.capt.gov.kw` search-result candidates. That review confirmed most extra health-related entries there are tender-publication approvals, cancellations, article `17` procurement-initiation approvals, complaints, recommendations, deferrals, or bid-security/procedural records rather than awarded rows, ruled out the `2024/21` and `2025/50` candidates as non-healthcare, non-award, or explicit non-approval material, showed that one supposed `2025/41` candidate was just another copy of the already-reviewed `2025/50` meeting, showed that two apparently recent search-result PDFs actually resolve to old `2020/81` meeting pages outside the target window, corrected the `2025/40` medical block to the actual approved rows and values from the page images, and surfaced one new direct-contract dialysis row on `2026/5` page `62`.
- Limitation:
  - Shell-side Playwright automation is still blocked by the site's current anti-bot behavior, so a reproducible full winning-bids batch run from this environment is not yet proven.
  - Browser-side retesting on `2026-06-01` confirmed that popup-level item requests are still blocked even when the CAPT summary winning-bids table is visible: `GET /en/tenders/winning-bids-popup/1/2024/2025--112 => 403`.
  - `capt_popup_live_note.md` now refines that browser finding: an already-open popup tab can still render a real winner/item/price table in-session even though fresh popup requests are often blocked. The captured popup in this session belonged to a non-medical Abdullah Al Salem University cleaning-services tender, so it does not change the strict medical output.
  - A follow-up browser retest on `2026-06-01` also showed that direct navigation from an already-loaded CAPT summary page to `?page=1` through `?page=5` collapses back into `Just a moment...`, so broader CAPT pagination still trips Cloudflare even though one loaded summary page can remain readable in-session.
  - Submitting the official CAPT date-search form with `meeting_date_from=2024-01-01` and `meeting_date_to=2026-06-01` also falls straight into `Just a moment...`, so even the built-in date filter currently trips the Cloudflare challenge in browser automation.
  - Clicking the already-selected `Ministry of Health` organization search button on the loaded summary page also did not apply a reliable Ministry-of-Health-only filter: non-MOH rows remained visible after the click, so the loaded summary page cannot currently be trusted as a live medical-only filter surface.
  - The CAPT scraper now treats live summary-table rows as package rows instead of reusing the summary serial number as a true `item_no`, which avoids misleading mixed item numbering while popup item detail remains blocked.
  - The CAPT scraper now also normalizes package-level rows where `item_no == notice_id` to `item_no = 1`, and now also collapses numeric board-minutes serial values to `item_no = 1` for non-popup rows, which reduces misleading package-row numbering in the saved CSV without implying that popup item detail has been recovered.
  - The CAPT scraper can now ingest saved popup JSON eval captures such as `capt_popup_eval.json` and `capt_popup_tab8_eval.json`, saved popup markdown snapshots such as `capt_live_popup_snapshot.md`, and saved raw popup HTML such as `capt_popup_1_2024_2025_112.html`, so a future in-session medical popup capture can be fed into the scraper even if the summary-page flow degrades again or the popup was captured in a different browser artifact format.
  - The current non-medical popup snapshot `capt_live_popup_snapshot.md` was verified on `2026-06-01` to parse into `2` structured winner/item/price rows for tender `1/2024/2025`, which proves the markdown popup-capture path is working.
  - The popup-capture loader now also deduplicates identical rows across multiple saved popup artifacts and across JSON/markdown/HTML popup variants, so repeated captures of the same popup do not inflate future CAPT enrichment when a real medical popup is saved more than once. A direct parser check now reduces the currently saved non-medical popup artifacts to the true `2` unique winner/item/price rows.
  - Follow-up DOM exports from the still-readable CAPT summary tabs now live in `capt_live_date_rows.json` and `capt_live_page5_rows.json`. They confirm that the current visible `Ministry of Health` row is a dental-center consulting/design appointment rather than an itemized medical supply/equipment popup row, while the visible popup-bearing row in the same session belongs to `Public Authority for Agriculture Affairs and Fish Resources`, not an in-scope medical buyer.
  - A fresh saved-output audit on `2026-06-01` did not reproduce a new row-mixing defect in the current CAPT CSV: the saved file still has `42` unique `notice_id` values, no duplicate notice IDs, and no rows with empty `item_description`.
  - Current CAPT coverage is now 42 verified strict medical-only CAPT board-minutes drug, device, laboratory-material, diagnostic-supply, dialysis, ophthalmology-consumable, and related clinical-procurement approval or change rows.
  - The CAPT output is now intentionally narrowed to strict clinical procurement only. Design, consulting, small-works, transport, security, meals, payment, incinerator, and other healthcare-adjacent service contracts are excluded even when the buyer is the Ministry of Health.
  - After verified seed backfill plus OCR-assisted review of pages `46` and `47` from the official `2024/73` CAPT board-minutes PDF, pages `55` to `61` from the official `2025/40` CAPT board-minutes PDF, and page `62` from the official `2026/5` CAPT board-minutes PDF, `amount`, `currency`, and `awarded_value_detail` are now filled on all 42 CAPT rows, including `4GR030-change-principal1` with `271,670 KWD`, the Gulf Tender `38` value-adjustment row with revised amount `282,627 KWD`, the `451LB3` genetic-screening laboratory-materials value-adjustment row with revised amount `209,084.150 KWD`, the added contract `970` medical-devices maintenance change-notification row with revised amount `239,760.918 KWD`, the added `033AK5` dialysis direct-contract row with `95,580 KWD`, and the corrected `2025/40` rows `057AK4`, `4TB522`, `5EY009`, and `5IN026` while excluding the nearby non-approved `4AK056`, `060AK4`, and `46AKD4` rows.

## Pakistan

### PPRA

- Script: `Pakistan/PPRA/ppra_awarded_scraper.py`
- Output:
  - `Pakistan/PPRA/output/ppra_awarded_medical_2024_2026.csv`
  - `Pakistan/PPRA/output/ppra_awarded_medical_2024_2026.jsonl`
- Proven:
  - Award columns are populated where the source exposes them.
  - The medical filter is now tightened so generic `consumable` rows from non-health buyers do not survive as false positives.
  - A verified fallback notice layer now preserves strict medical coverage even when the live contracts host times out, using official public PPRA tender-detail pages for medical notices such as reagent-rental, electro-medical equipment, medicines, lab kits, implants, and MR-LINAC procurement.
- The PPRA scraper now uses a configurable live request timeout before falling back, via `--live-timeout` or `PPRA_LIVE_TIMEOUT`, with a current default of `900` seconds so slow host behavior is less likely to collapse the run prematurely.
- The top-level awarded runner now also defaults `--ppra-live-timeout` to `900`, and an earlier smoke run confirmed that the runner forwards the timeout override correctly into the PPRA scraper.
- Limitation:
- The live public contracts, tender-detail, and evaluation pages are now reachable through the VPN path.
- The saved output is now `390` rows, with the strongest official PPRA fallback notices expanded into item-level schedules from public tender-document evidence for Surgery, Dental, Physiotherapy, Diabetic/Endocrine, Gynecology/Obstetrics, Ophthalmology, Cardiology, Anesthesia, Orthopedic, Urology, Paeds, and Medicine, plus additional official CMH, PAC Hospital, Pakistan Navy Medical Store Depot, Pakistan Rangers, Army Cardiac Hospital Lahore, PAEC medical-notice coverage, the five-lot `TS0000002479E` PAC Hospital Kamra electro-medical equipment notice, `183` reagent-rental test rows from the verified local `TS0000001234E` annex extract, the four-component `TS0000006378E` MR-LINAC split, broader category-level rows for official PPRA notices whose titles explicitly enumerate medicines, disposables, lab kits, implants, appliances, electro-medical equipment, injectable items, surgical disposables, lab reagents, medical consumables, medical equipment, furniture and fixtures, and medical gases, and two live healthcare evaluation rows.
- Several PPRA fallback identities were also corrected against exact public notice evidence rather than left as loose placeholders, including `TS0000001234E` as a Pakistan Navy medical reagent / lab-chemical notice, `TS0000002479E` as `PAC Hospital Kamra`, `TS0000003271E` as `CMH Malir Cantt Karachi`, `TS0000005222E` as the `CMH Pano Aqil` bulk medical purchase notice, `TS0000002406E` as `CMH Multan`, and `TS0000002427E` as `Army Cardiac Hospital Lahore`.
- The live evaluation rows are `EVL00000000799`, `Medical/Health Insurance for PDA Employees`, with supplier `East West Insurance Co Ltd` and awarded/evaluation date `2026-05-19`, plus `EVL00000000432`, `Group Health Insurance Coverage of NDRMF's Employees (Y2026-27 and Y2027-28)`, with supplier `M/s State Life Insurance Corporation Pakistan` and awarded/evaluation date `2026-04-28`. They do not publish amounts, and current public contracts keyword searches did not surface medical awarded-contract rows with published amounts.

### DRAP

- Script: `Pakistan/DRAP/drap_item_scraper.py`
- Verified fallback seeds: `Pakistan/DRAP/drap_verified_seeds.py`
- Output:
  - `Pakistan/DRAP/output/drap_item_medical_2024_2026.csv`
  - `Pakistan/DRAP/output/drap_item_medical_2024_2026.jsonl`
- Proven:
  - Public archive pages and linked tender PDFs exist in the target window.
  - A February 14, 2024 NCLB retender for chemicals, glassware, equipment, and reference standards was verified from the official DRAP page and official revised PDF, then added with 67 item rows.
  - A February 23, 2024 prequalification schedule for chemicals and glassware at CDL Karachi was verified from the official prequalification PDF.
  - A January 10, 2024 NCLB Islamabad tender for lab chemicals, glassware, equipment, and reference standards was verified from the official tender PDF.
  - A January 16, 2025 laboratory equipment tender was verified from the public tender PDF and saved as item-level output.
  - A May 31, 2024 FTIR laboratory tender was verified from the official DRAP page and official PDF, then added as an item-level row.
  - A September 5, 2025 chemicals, reagents, reference standards, glassware, and kits tender was verified from the official DRAP tender page and official PDF, then added as a fallback seed path because the host remains unstable from this environment.
  - A March 25, 2026 chemicals, glassware, USP standards, CRMs, and columns invitation was verified from the official invitation PDF.
  - The saved DRAP output is now intentionally narrowed to medical and laboratory consumables/equipment only; non-medical operational tenders such as surveys, security, housekeeping, repair-and-maintenance, EPG, storage, and generic IT or office infrastructure were removed from the main DRAP output and also removed from the primary verified seed inventory.
  - The verified DRAP output now covers 371 item rows across seven official DRAP document sources, including FTIR equipment, laboratory equipment, chemicals, reagents, endotoxin supplies, reference standards, USP standards, CRMs, kits, and glassware lines.
  - Live DRAP tender index page chronology now also supports the current seven-source cap: page `3` already reaches `2024-01-10`, while page `5` is down in `2021`, so there is no unreviewed in-window 2024-to-2026 medical/lab tender page hiding beyond the already-checked page `3`.
  - The current CAPT/DRAP coverage audit now also confirms that no raw date-range `contract_period` values remain in either saved CSV, that no out-of-scope CAPT service/facility notice IDs are present in the strict medical-only CAPT output, and that no out-of-scope DRAP notice IDs are present in the medical-only DRAP output.
  - The broader output diagnostics now confirm that `amount` is filled on only `8/371` DRAP rows because only the `2025-01-16` lab-equipment source exposes pricing.
- Limitation:
  - The host has been unstable from this environment, so a full scripted live batch run is still not yet proven here.
  - Public awarded fields are not exposed on most of the tender pages or PDFs used here, so supplier, awarded date, and awarded value detail remain blank for DRAP even though `currency`, `contract_period`, and limited pricing figures are now present where the public source exposes them.

### EPADS

- Script: `Pakistan/EPADS/epads_item_scraper.py`
- Verified fallback seeds: `Pakistan/EPADS/epads_verified_seeds.py`
- Output:
  - `Pakistan/EPADS/output/epads_item_medical_2024_2026.csv`
  - `Pakistan/EPADS/output/epads_item_medical_2024_2026.jsonl`
- Proven:
  - Public medical item rows are reachable beyond page 1.
  - Examples include medical treatment books and medical first aid kit line items.
  - The listing parser now extracts cleaner `buyer` and `classification` fields.
  - The detail page embeds a bidding timer timestamp, and the scraper now converts that to `closing_date`.
- The scraper now also parses `amount` and `currency` from detail-page `Awarded Amount` text when that public field is available.
- A verified fallback notice layer now preserves the stronger previously saved EPADS rows and adds public medical notices such as `P9695` and the `2026-04-20` Federal Government Polyclinic electro-medical equipment notices `P22430`, `P22431`, `P22432`, `P22433`, `P22436`, `P22439`, `P22442`, `P22451`, `P22454`, `P22457`, `P22460`, and `P22463`.
- The strongest fallback notices now expand into item-level schedules, including NIH `P9695` and the Federal Government Polyclinic Surgery, Physiotherapy, Diabetic/Endocrine, Ophthalmology, and Cardiology notices.
- The EPADS filter is now tightened so generic non-medical carryover rows like NUTECH course consumables, unrelated IT-equipment notices, medical-treatment-book printing, paper shredders, keyboard/mouse rows, and non-health textile/oceanography lab rows do not survive in the saved medical-only output.
- Limitation:
  - Public EPADS detail pages expose item rows and timing fields but not a confirmed publication date field.
- Because of that, `publication_date` cannot currently be proven for this source from the public detail page, and award-specific columns remain blank.
- The public LOI/open/detail/annual-plan pages are now reachable through the VPN path.
- The live `loi-issued` page exposes a public `Awarded Amount` column. The scraper now parses current non-linked LOI rows by deriving detail URLs from `P#####` notice IDs and writes those live amounts into `amount`, `currency`, and `awarded_value_detail`.
- The saved output is now `802` strict medical/healthcare rows with `amount` on `680/802`, `publication_date` on `112/802`, and `closing_date` on `802/802`.
- Public EPADS detail/annual-plan/public-notification pages sampled in this pass still do not expose `supplier_name` or `awarded_date`.

## Remaining expansion shortlist

- `identify_expansion_candidates.py` now reports `8` remaining single-row `PPRA` rows, including the live evaluation rows, and `35` single-row `EPADS` rows after detail-level EPADS scope pruning.
- The strongest next `PPRA` package-level candidates are currently `TS0000005255E`, `TS0000002590E`, `TS0000002213E`, `TS0000002924E`, `TS0000001459E`, and `TS0000004946E`.
- A fresh audit of those `6` PPRA candidates on `2026-06-01` confirmed they are not currently safe title-only split targets: each surviving notice still exposes only one package-level category in its public title or item text, so more PPRA row growth there needs live tender-detail access or richer tender-document evidence.
- The strongest completed PPRA attachment-first fallback is now `TS0000001234E`: its official attachment resolves to a large Pakistan Navy reagent-rental tender document, and the scraper now materializes the `183` item rows that were explicitly captured in the verified local annex extract.
- Browser-side inspection still confirms additional upside beyond those `183` rows: the official `TS0000001234E` PDF is a `41`-page `LAB TESTS (REAGENT RENTAL CONTRACT)` document whose `DP-2` section explicitly says `Category of items: LAB TESTS (Reagent Rental) (226 x Items)` and points to Annex A for the item list. Sample Annex A rows visible there include tests such as `LAB HBA1C`, `LAB TSH`, `LAB CBC`, `LAB D DIMER`, and `LAB URINE MICROALBUMIN`, so the remaining gap is now the missing uncaptured annex rows rather than whether the source exists.

## Runners

- Awarded sources: `run_awarded_scrapers.py`
- Item-level sources: `run_item_level_scrapers.py`
- Live source access probe: `probe_source_access.py`
- Combined output/source gap report: `explain_output_gaps.py`
- Live access audit: `live_access_audit.md`
- Expansion-candidate report: `identify_expansion_candidates.py`
- Chrome/browser access audit: `chrome_access_audit.md`

## Practical completion state

- Best strict medical awarded source with complete financial fields in this environment: `CAPT`
- New UAE awarded-source path implemented with public listing extraction and multi-capture browser fallback, but still not fully paginated end to end: `Dubai eSupply`
- Best browser-verified awarded source with automation limitation: `CAPT`
- Best item-level source from public tender documents: `DRAP`
- Current reproducible access status from `probe_source_access.py`: `PPRA` contracts and tender-detail URLs are reachable through the VPN path, and `EPADS` LOI/detail/annual-plan URLs are also reachable. `CAPT` winning-bids still hits Cloudflare from the current shell probe.
- Current direct machine-level access status from `live_access_audit.md`: `PPRA` contracts, tender detail, and evaluation pages are reachable after VPN access; `EPADS` LOI/detail/annual-plan pages are reachable after VPN access; `CAPT` still returns `403` with `Cf-Mitigated: challenge`; and bare-shell `Dubai eSupply` past-opportunities requests return `401 Unauthorized`, which confirms that UAE still needs browser/session-backed capture rather than plain shell requests.
- Direct PPRA and EPADS shell probes on `2026-06-01` now return `HTTP 200` for the tested public routes, replacing the earlier timeout/block-page finding.
- Current Chrome-plugin status from `chrome_access_audit.md`: the native-host manifest file exists with the expected origin, but the Windows Chrome NativeMessagingHosts registry key is missing, direct Chrome profile enumeration is blocked by `Access denied` from this execution context, and browser-bridge bootstrap still fails with `windows sandbox failed: spawn setup refresh`, so the Chrome route was not usable in this session.
- Shared field normalization is now stricter too: `PPRA`, `EPADS`, `DRAP`, and `Dubai eSupply` no longer carry default currency values on non-award rows with blank `amount` and blank `awarded_value_detail`. `EPADS` now has substantial live amount coverage, while `CAPT` remains the only source with full current `amount` and `supplier_name` coverage in the saved outputs.
- The serializer now also stops synthesizing `awarded_value_detail` from generic tender `amount` on non-award statuses. That especially matters for the `8` priced `DRAP` lab-equipment rows, which now keep their real public tender amount without pretending that an awarded-value field was published.
- Best item-level source from public HTML detail pages: `EPADS`
- Current CAPT/DRAP remaining-gap audit: `capt_drap_gap_audit.md`
