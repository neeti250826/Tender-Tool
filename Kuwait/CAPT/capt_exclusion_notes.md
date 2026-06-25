# CAPT exclusion notes

This note records health-related CAPT PDF findings that were reviewed and intentionally not added to the awarded output because they are not award outcomes.

## Meeting 2024/73

Source PDF:

- `https://files.capt.gov.kw/media/dfa92963-8390-410b-bdd1-6dc4f5894df9.pdf`

Reviewed pages:

- `32` to `40`

Findings:

- Page `32`, decision `53`: Ministry of Health request to publish a tender for transport of radioactive materials and radioactive waste. This is a tender-publication approval, not an award.
- Page `32`, decision `54`: cancellation request for practice `261ON3` to purchase `OXALIPLATIN / ELOXATIN` for cancer patients at Hassan Makki Juma Center and Kuwait Cancer Control Center. This is an approved cancellation, not an award.
- Pages `33` to `40`, decisions `55` to `78`: repeated approvals for Ministry of Health article `17` procurement-initiation actions covering medicines, dialysis consumables, lab reagents, nutrition products, and oncology drugs. These are approvals to let the procuring entity proceed with procurement procedures, not awarded-result rows.
- Page `44`, decisions `88` to `90`: article `17` procurement-initiation approvals for practice `389TB4` (`METOPROLOL SUCCINATE 95MG`), practice `393TB4` (`SUMATRIPTAN SUCCINATE MG50`), and practice `ه.ط 11/2024-2025` for `AUTOMATED PROTECTOR STERILE SLUSH`. These are requests to start procurement procedures, not awarded-result rows.
- Page `45`, decision `91`: article `17` procurement-initiation approval for practice `ه.ط 4180/2024-2025` covering supply, installation, operation, maintenance, and training for `INSULIN PUMP` devices and accessories for home-care patient-device stores. This is still a procurement-initiation record, not an awarded-result row.

Reason excluded:

- The CAPT output in `capt_awarded_medical_2024_2026.csv` is being kept as an awarded or post-award approval dataset: winning bids, direct-contract approvals, change-order approvals, amount adjustments, and contract-extension approvals.
- The reviewed `2024/73` health entries above do not expose a selected supplier, awarded amount, or final award decision. Including them would mix procurement-initiation records into the awarded dataset.

Tooling used:

- `capt_pdf_helper.py`
- `PyMuPDF`
- local `tesseract.exe` with `eng` OCR for embedded English drug names and notice identifiers

## Meeting 2026/5

Source PDF:

- `https://files.capt.gov.kw/media/649bebdf-2723-44f1-b4b4-bf82625db633.pdf`

Reviewed pages:

- `53` to `68`
- focused recheck of `60` to `65`

Findings:

- Page `62`, decision `104`: this page was originally a candidate and is no longer an exclusion. It has now been materialized into the saved CAPT output as notice `033AK5`, a Ministry of Health direct-contract approval for `STAY-SAFE CAPD 1.5% 2L` peritoneal dialysis solution from `Mohammad Naser Al Hajri & Sons / Fresenius Medical Care` with total amount `95,580 KWD`.

- Page `13`, decisions `14` and `15`: these are for Kuwait Integrated Petroleum Industries Company, not Ministry of Health. One item concerns initial-security-deposit extension for specialized laboratory services and the other is only a recommendation follow-up. Neither belongs in the medical awarded dataset.
- Page `23`, decision `30`: Kuwait National Petroleum Company direct-order page with a large value, but the board explicitly deferred the decision to a later meeting. It is not a final approved award row and it is not a Ministry of Health healthcare procurement.
- Page `53`, decisions `83` to `85`: Ministry of Health tender-publication and administrative postponement items for design/supervision works and transport vehicles. These are procurement-initiation or scheduling records, not awards.
- Page `56`, decisions `92` and `93`: article `17` initiation items for `251SP5` dermatology-treatment medicines and `313SP5` racecadotril granules. Decision `92` only obliges the entity to complete model-contract procedures, and decision `93` is explicit `non-approval`. These are not awarded-result rows.
- Page `57`, decisions `94` and `95`: article `17` initiation items for `357TB5` treatment medicine used in epilepsy/convulsions and `001CS6` absorbent cotton balls. Both decisions are explicit `non-approval`, so they are not award rows.
- Page `58`, decisions `96` and `97`: article `17` initiation items for `205TB5` multiple-sclerosis medicine and `266TB5` medicines for hospitals and health centers. Both decisions are explicit `non-approval`.
- Page `59`, decisions `98` to `100`: article `17` initiation items for `269TB5` psychiatric-treatment medicine, `0112` blood-bank equipment and operation, and `172/2025/2026` computed-tomography scanner support. Decision `98` is explicit `non-approval`, decision `99` only instructs the authority to respond to an earlier board decision, and decision `100` defers the CT-scanner item for more study. None is an awarded-result row.
- Page `60`, decisions `101` and `102`: article `17` initiation items for `WASHER DISINFECTOR` and `DENTAL SUCTION SYSTEM`. Decision `101` only postpones the matter pending renewal of bid security, and decision `102` is explicit `non-approval`.
- Page `61`, decision `103`: article `17` initiation item for medical training `MANIKINS TRAINING 2025/2024/241` for life-support and trauma-support training. The board only approved proceeding with a public practice under article `17`; it is not an award-result row.
- Pages `54`, `59`, and `60`, decisions `86` to `102`: repeated Ministry of Health article `17` procurement-initiation approvals for medical supplies, blood-bank equipment, CT scanner support, washer disinfectors, dental suction units, and other hospital items. These are approvals to proceed with procurement, not awarded-result rows.
- Page `63`, decisions `105` and `106`: publication and annex items, including a pre-bid meeting notice and an ambulance annex. These are notice-publication records, not awards.
- Page `64`, decisions `107` and `108`: bid-bond extension and recommendation items tied to a maintenance tender for Ministry of Health buildings and centers. These are not award-result rows.
- Page `65`, decision `109`: Ministry of Health recommendation to award a dental-health services system project in centers and clinics, but the board explicitly decided `non-approval` of the entity recommendation. This is not an awarded-result row.
- Pages `66` and `67`, decisions `110` to `114`: complaints and procedural holds relating to Ministry of Health maintenance tender groups. These are protest/complaint records, not awards.

Reason excluded:

- Aside from the now-materialized `033AK5` direct-contract row on page `62`, the reviewed `2026/5` Ministry of Health pages contain healthcare-relevant activity that is still procurement-initiation, complaint, recommendation, publication, bid-security, or procedural-hold material rather than a selected supplier and final awarded decision.
- Including those remaining rows in `capt_awarded_medical_2024_2026.csv` would mix non-award workflow records into the awarded dataset.

## Meeting 2025/39

Source PDF:

- local cache under `Kuwait/CAPT/pdf_scan_2025_39/`

Reviewed pages:

- `21`
- `22`

Findings:

- Page `21`, decision `24`: Public Authority for Persons with Disabilities item about the sixth extension of resident service contract tender `H A Sh D I (1) 2019/2018` with `Al Eissa Medical and Scientific Devices Company`. Despite the supplier name, the page is a resident-service contract extension record rather than a procurement row for medical devices, equipment, or consumables.
- Page `20`, decision `23`: security/safety works for the same authority. This is not medical equipment procurement for the dataset, and it is also only an initial-bond extension item.
- Page `22`, decision `25`: Public Authority for Palaces request to launch a tender for technical support and Oracle licenses for `EXADATA` and `EXALOGIC`. This is an approval to proceed, not a healthcare award row.
- Page `22`, decision `26`: palace-building cleaning tender bond extension. This is not healthcare procurement and not an award row.

Reason excluded:

- The page `21` disability-authority entry is tied to a company with a medical-devices name, but the underlying subject is still a resident-service contract extension rather than a medical equipment or consumables procurement row.
- The other reviewed `2025/39` entries above are either non-healthcare or pre-award procedural items, so including them would weaken the CAPT output's scope and award-result integrity.

## Meeting 2025/55

Source PDF:

- `https://files.capt.gov.kw/media/cd36c257-13e1-4143-8911-c7bcb759b220.pdf`

Reviewed pages:

- `64`
- `70`

Findings:

- Page `64`, decisions `89` and `90`: Ministry of Health direct-contract section labeled `الإحاطة والعلم` rather than approval. The items only record that the board was informed about adding one manufacturer name to direct contract file `G23/0007` linked to Gulf Tender `11` with `Al-Ameen Medical Company`, and adding one manufacturer name to direct contract file `G22/1475` linked to Gulf Tender `2019/36` for hospital equipment with `Central Circle Company`. These are acknowledgment/information records, not awarded-result rows with a new award decision.
- Page `70`, decision `98`: cancellation of practice `4IN307` for `XULYOPHY` diabetes-treatment injection for hospitals due to State Audit Bureau non-approval. This is an approved cancellation, not an award.
- Page `70`, decisions `99` and `100`: complaint/appeal awareness items, including complaint `2025/40` related to direct contract `314IN4` for anesthesia injections. These are grievance records, not award-result rows.

Reason excluded:

- The `2025/55` page `64` items do concern healthcare procurement, but they only acknowledge manufacturer-name additions and do not publish a fresh supplier-selection or award-value decision.
- The `2025/55` page `70` medical item is a cancellation, not an awarded-result row.

## Meeting 2025/40

Source PDF:

- `https://files.capt.gov.kw/media/62143405-06f1-4202-97ca-ec50d07f97ca.pdf`

Reviewed pages:

- `54`
- `55`
- `56`
- `57`
- `58`
- `60`
- `61`

Findings:

- Page `54`, decisions `86` to `88`: direct contracts `4AK042`, `4AK048`, and `4AK055` are approved Ministry of Health rows for dialysis/organ-preservation solutions. They are not exclusions anymore in practice because they are already materialized in the saved CAPT output; this page is recorded here only so it is not re-triaged later as an unmined local lead.
- Page `55`, decision `89`: direct contract `4AK056` for `STAY-SAFE CAPD 1.5% 2L` is an explicit `non-approval` because of high value. It must not be in the awarded dataset.
- Page `55`, decision `90`: direct contract `057AK4` for `HAEMOSOL BO` bags used with `PRISMAFLEX` continuous renal dialysis is an approved row and is now materialized in the saved CAPT output with amount `840,000 KWD`.
- Page `55`, decision `91`: direct contract `060AK4` for low-calcium CAPD solution is an explicit `non-approval` because of high value.
- Page `56`, decisions `92` and `93`: direct contracts `064AK4` and `066AK4` are approved rows already materialized in the saved output.
- Page `56`, decision `94`: direct contract `46AKD4` for `PRISMAFLEX PLASMA/PRISMAFLEX 2000 FILTRATION TPE` is an explicit `non-approval` because of high value.
- Page `57`, decisions `95` to `97`: direct contracts `51AKD4`, `4IN499`, and `4IN508` are approved rows already materialized in the saved output.
- Page `58`, decisions `98` to `100`: direct contracts `204ON4`, `4TB408`, and `4TB494` are approved rows already materialized in the saved output.
- Page `60`, decisions `104` to `106`: direct contracts `4TB522`, `5EY009`, and `5IN026` are approved rows. These rows are now materialized in the saved CAPT output with the corrected notice IDs and amounts from the page images.
- Page `61`, decision `107`: direct contract `5TB006` is an approved row already materialized in the saved output.
- Page `61`, decision `108`: publication of a preparatory-meeting record for a practice covering buildings, warehouses, medicines, and medical equipment. This is a publication record, not an award row.

Reason excluded:

- The non-approved `2025/40` rows above, especially `4AK056`, `060AK4`, and `46AKD4`, are healthcare-relevant but are still not award outcomes.
- The publication item on page `61` is a procedural record, not a supplier-selection or award decision.

## Meeting 2025/50

Source PDF:

- `https://files.capt.gov.kw/media/d18391ff-8b4c-47b3-94ae-b5e4b90a95ca.pdf`

Reviewed pages:

- `42` to `47`

Findings:

- Page `42`, decisions `70` to `72`: Kuwait University initial-bond extension items for user-protection licensing, security works, and telescope supply. These are bond-extension records, not award rows.
- Page `43`, decisions `73` and `74`: Kuwait University initial-bond extension items for scientific/laboratory devices. These are still only bond-extension records, not awards.
- Page `44`, decision `75`: Kuwait University extension/change-order approval for servers and storage systems. This is IT infrastructure, not medical procurement for the dataset.
- Page `45`, decision `76`: Kuwait University medical-waste-disposal device recommendation for the Medical Sciences Center. The board explicitly did not approve the entity recommendation and instead allowed the entity to continue under article `40`. This is not an award-result row.
- Page `46`, decision `77`: Kuwait University cancellation of line items for laboratory equipment. This is an approved cancellation, not an award.
- Page `46`, decision `78`: complaint regarding nursing and technical staffing for Dentistry clinics, not a procurement award row.
- Page `47`, decisions `79` and `80`: Kuwait Oil and Ministry of Oil publication/extension items for non-healthcare projects, not relevant medical award rows.

Reason excluded:

- The reviewed `2025/50` healthcare-adjacent entries are still cancellations, complaints, bond extensions, non-healthcare service/infrastructure items, or explicit non-approvals rather than awarded or post-award medical-only rows.

## Meeting 2024/21

Source PDF:

- `https://files.capt.gov.kw/media/08d1ba98-1af5-49dd-b286-255b47e81dc0.pdf`

Reviewed pages:

- OCR scan of `1` to `55`
- focused read of `17`, `29`, and `50`

Findings:

- The scanned file contains no `Ministry of Health` award cluster and no `وزارة الصحة` hits in the OCR output.
- Page `17`, decision `21`: Ministry of Finance direct-contract agreement for government electronic payment channels with no healthcare scope.
- Page `29`, decision `41`: Public Fire Force award recommendations for firefighting devices and equipment. This is equipment procurement, but it is not medical or healthcare equipment.
- Page `50`, decision `77`: Public Works change/extension order for road and square maintenance. This is infrastructure work, not healthcare procurement.
- The other OCR matches in this file are false positives from generic words such as `الصحيحة`, `تطبيق`, or `دم` embedded in unrelated text rather than true medical/laboratory tenders.

Reason excluded:

- This `2024/21` board-minutes PDF is a valid CAPT source, but the reviewed candidate pages do not expose any strict medical-only awarded or post-award row for the dataset.
- Adding rows from this file would either introduce non-healthcare procurement or procedural records outside the project scope.

## Search-result false leads

Source PDFs:

- `https://files.capt.gov.kw/media/a946f099-6715-4024-b5ea-07bc50b2b62a.pdf`
- `https://files.capt.gov.kw/media/77bf21cd-97f4-40f8-8639-e7ba90002efd.pdf`
- `https://files.capt.gov.kw/media/b1e3ac1b-011d-4b32-a047-67b2e27c9631.pdf`

Reviewed findings:

- The `a946f099-6715-4024-b5ea-07bc50b2b62a.pdf` candidate looked like a new `2025/41` lead from search context, but the downloaded file resolves to the same `2025/50` CAPT meeting content already reviewed under pages `42` to `47`. It does not add a new awarded/post-award medical-only row.
- The `77bf21cd-97f4-40f8-8639-e7ba90002efd.pdf` candidate looked promising from a search snippet mentioning `Ministry of Health` and direct contracts, but OCR review shows it is meeting `2021/94` with publication text `2021/12/12`, outside the target window. The medical-looking pages are old direct-contract and extension/change-order material that cannot be added under the current date filter.
- The `b1e3ac1b-011d-4b32-a047-67b2e27c9631.pdf` candidate resolves to meeting `2020/81` with publication text `2021/01/03`, outside the target window. It contains old medical rows such as drug purchases, ROTEM blood-clotting-test consumables, and lab-culture materials, but they are not in-window CAPT publication records for this dataset.

Reason excluded:

- These PDFs are useful for understanding CAPT source behavior, but they do not justify new saved rows because they are either duplicates of already reviewed meeting content or clearly outside the `2024-01-01` to `2026-05-28` publication-date window.
- This also shows that search-engine recency snippets for `files.capt.gov.kw` cannot be treated as authoritative publication-date evidence without checking the actual page text inside the PDF.
