# TURMECA mapping prompt

```
Map the attached tender data to the approved Clearstate taxonomy.

INPUTS
- Tender data: [FILE / SHEET LINK], one row per awarded line, lot or bid.
- Taxonomy (use this for all taxonomy mapping):
  https://docs.google.com/spreadsheets/d/<TAXONOMY_SHEET_ID>/edit?gid=1456151223#gid=1456151223
  Tab "Combined Manufacturer List_Late" (columns: OU, Sub-OU, Product Category, Company, Family).
- Countries / portals: [KSA NUPCO / Turkey EKAP / Pakistan KP & Federal / Kuwait CAPT / UAE eSupply].

OUTPUT COLUMNS
Fill: OU | Sub-OU | Device Category | Company | Family Name | Manufacturer Evidence | Tender Stage | Price Evidence |
Included/Review/Excluded
Add: Expected Company | Expected Family Name | Confidence Level | Mapping Status | Mapping Note

GENERAL RULES
- Use only exact names that exist in the taxonomy sheet linked above. Never invent or rename a category,
  company or family.
- Never leave Company or Family Name blank. Either fill a taxonomy name, or write one of the markers in
  Step 2 / Step 3 and explain the reason in Mapping Note.
- Keep every original column unchanged. Keep the original-language text next to the English text.

STEP 1 - DEVICE CATEGORY, SUB-OU, OU
- Decide the Device Category from the line item or lot description only. Do not use the tender title,
  because multi-lot tenders repeat unrelated product words across every row.
- Read both the original language (Turkish, Arabic, etc.) and the English translation.
- Map a row only when the description clearly names a product in a taxonomy category. Words can appear
  in any order (e.g. "PULSE GENERATOR, RECHARGEABLE, DBS" = DBS rechargeable neurostimulator).
- For lines written "<item> RELATED TO <parent equipment>", classify the item, not the parent equipment.
- Do not map service, repair, maintenance, rental, training, drugs, lab reagents, or dental products.
  Watch for false matches, e.g. "rod" inside "introducer", "EUS" inside "reusable", brand names that are
  also drug or pharma companies.
- Take Sub-OU and OU from the taxonomy row of the chosen Device Category.
- If no category fits, leave all three blank and set Included/Review/Excluded = Excluded, with the reason in
  Exclusion Reason, Company / Family = "Not related" and Mapping Status = "Excluded - not a taxonomy device".
- Keep OU, Sub-OU and Device Category filled when only Company or Family is Undefined: the category says what
  was bought (item text); the company needs separate manufacturer evidence.
- Known traps (all seen in TURMECA data):
  "NON- ABSORBABLE" (space after the hyphen) is non-absorbable; Turkish "ILAC SALINIMLI" balloon = Drug Coated
  Balloon, "STENT ... ILAC SALINIMLI" = DES; peripheral stents are not PTA balloons; "YUKLEMESIZ / unloaded"
  haemoclips are endoscopic haemostasis, not stapler reloads; open linear / curved cutter cartridges are
  Open - Reload; PFA-100 (platelet analyser) items, laboratory pH-meter probes, RVG sleeves, staining systems,
  dental burs ("FREZ", "AEROTOR", "PIYASEMEN"), K-wires / Steinmann pins with a trocar tip, suction-unit / IV /
  water filters, hair-clipper and razor blades, alligator-clip cables, suture anchors and passers, ETT holders,
  software / service / training lines and veterinary items are not taxonomy devices.
- Older extracts that glue the next item onto a description ("... ITMZ 1500 1909 <next item>"): classify only
  the text before the first ITMZ / ITEMIZED marker.

STEP 2 - COMPANY (manufacturer, never the distributor)
- Search in this order and stop at the first match:
  1. the published manufacturer (e.g. NUPCO "Manufacturer" column);
  2. the make / brand text (e.g. Pakistan BER "Make"), only when no manufacturer is published, and only
     when it is a real name, not a remark such as "Market Survey is required" or "Offered price higher";
  3. the supplier name, only when the supplier is the manufacturer itself or its local affiliate
     (e.g. "Medtronic Medikal Teknoloji" -> Medtronic). A distributor's name is never the manufacturer.
- Match each name against the taxonomy companies in this order:
  a. acquired brands / parent roll-ups: Covidien, Nellcor, Kyphon, Mazor, Given Imaging, Oridion,
     Puritan Bennett, ev3, Xomed, Barrx, INVOS -> Medtronic; Ethicon, DePuy Synthes, Biosense Webster,
     Cerenovus, Acclarent, Abiomed, Shockwave -> Johnson & Johnson; St Jude, Thoratec -> Abbott;
     Bard, CareFusion -> BD; Maquet -> Getinge; Welch Allyn, Hill-Rom -> Baxter; Meril -> Meril Life Sciences;
  b. exact taxonomy name;
  c. same name after dropping legal and generic words (Ltd, GmbH, AG, Co, Medical, Dental, Healthcare,
     Pvt, SP ...) and spaces/hyphens: BIEN AIR = Bien-Air, NSK DENTAL = NSK, SMI AG = Smi, EMED SP = EMED;
  d. near-identical spelling only (fuzzy match >= 95%, names of 5+ characters).
- If no taxonomy company is found, write one marker in Company:
  "Not in taxonomy" = a manufacturer is published but it is not a taxonomy company (keep its name in the
                      Manufacturer column);
  "Undefined"       = only a distributor, or nothing, is published;
  "Not related"     = the manufacturer cell holds status text (HOLD, CANCELLED, N/A), not a company.
- If the Company is a taxonomy company but is NOT listed for that Device Category, keep it, set
  Mapping Status = "Company not listed for this category" and Confidence Level = Low.
- Manufacturer Evidence: Explicit (printed on the line) / Inferred from distributor (supplier is the OEM or
  its affiliate) / None.

STEP 3 - FAMILY
- Only when the Company is a taxonomy company listed for that Device Category.
- Fill the family listed in the taxonomy for that Company + Device Category whose distinctive name words
  all appear in the model, catalogue, brand or description text (e.g. Shiley, Vicryl, Capiox, LigaSure).
- Never match on generic product words, even if the taxonomy uses them as a family name: Suture,
  Blades, Plate, Arterial, PTCA Balloon, Sampling Line, Polypropylene, Tracheostomy Tube, Drill, etc.
  A word used in family names of 5 or more different companies counts as generic.
- Never fill a catch-all family ("<Company> - Others") from text; suggest it in Expected Family Name.
- Match whole words only ("Titan" must not match "titanium").
- If no family is evidenced, write one marker in Family Name:
  "Undefined"   = families are listed for this company + category, but none is named in the text;
  "Not related" = no family is listed for this company + category, or the company is not mapped.

STEP 4 - EXPECTED COMPANY AND EXPECTED FAMILY (leads, not confirmed mappings)
- Expected Company: only for rows whose Company is "Undefined". Use a company listed for the row's
  Device Category whose brand or family name appears in the line text (e.g. "CAPIOX" -> Terumo,
  "SHILEY" -> Medtronic). Never use text that says "compatible with", "for use with", "uyumlu".
  Flag brand words that tenders often use generically (PROLEN / PROLENE, VICRIL / VICRYL, SURGICEL,
  FOLEY) with "verify" in Mapping Note. Never suggest one when a manufacturer is published.
- Expected Family Name, when Family Name is "Undefined": the best partial family-name match; else the
  only family listed for that company + category; else the taxonomy catch-all family; else
  "Undefined - n candidates: <first 5 families>".

STEP 4B - IDENTIFY THE MANUFACTURER BEYOND THE TAXONOMY
- Add: Identified Manufacturer (incl. outside taxonomy) | Identified Brand / Model | Identification Source.
- Fill, in this order: the taxonomy Company; else the published manufacturer even if it is not a taxonomy
  company (e.g. TRACOE, Spacelabs, ResMed); else the published make text; else a manufacturer or brand named
  in the item text (mark "unconfirmed"; count a brand only in lines of its own category; ignore
  "compatible with / uyumlu" wording; flag probe / cable / filter lines because the name may be the host
  equipment; if a maker and a generic brand word both appear, e.g. "WEGO PROLEN", the maker wins).
- Never use a distributor as the manufacturer. Legal-name words such as IMALAT / URETIM do not prove an
  own-brand maker. Otherwise write "Not identified - only the distributor is published".

STEP 5 - CONFIDENCE LEVEL AND MAPPING STATUS
- Confidence Level (for the whole OU -> Sub-OU -> Category -> Company -> Family chain):
  High   = Company from the published manufacturer (roll-up or exact name), listed for the category,
           and Family identified.
  Medium = Company resolved and listed for the category but Family not identified; or Company found by
           normalised / fuzzy name or from an OEM-affiliate supplier.
  Low    = Company not listed for the category, "Not in taxonomy", "Undefined" or "Not related"
           (category-only mapping).
- Mapping Status (one value): Mapped to family / Mapped to company - family not identified /
  Company not listed for this category / Manufacturer not in taxonomy /
  Distributor only - manufacturer not published / No manufacturer or supplier published /
  Not related - status text in manufacturer field.
- Mapping Note: the specific reason, e.g. "Published manufacturer 'TRACOE' is not a taxonomy company",
  "Only the distributor 'MEDSET ...' is published", "Model/description names none of the listed families".

STEP 6 - EVIDENCE AND STATUS
- Tender Stage: Pipeline (open RFQ, draft or preliminary evaluation) / Awarded (final result, approved
  evaluation report, award list) / Contracted (signed contract).
- Price Evidence: Line price (value belongs to this line or a single-lot contract) / Contract-level only
  (one contract value covers several lots) / None (no price published).
- Included/Review/Excluded:
  Included = category mapped + final award or contract + winning row + award year in [2024-2026] +
             not cancelled or terminated.
  Review   = category mapped but draft/preliminary, losing bid, no award published, or outside the years.
  Excluded = no category mapped.
- For multi-award frameworks (e.g. NUPCO), give each winner of the same item an Award Weight of 1/n.

QUALITY CHECKS BEFORE RETURNING
- Every filled Company + Device Category + Family combination exists in the taxonomy sheet linked above.
- No blank Company or Family Name cells: each is a taxonomy name or a marker with a Mapping Note.
- No distributor name appears in the Company column.
- No family is matched on a generic product word or on the company name alone.
- No row is mapped on the tender title alone.
- Report counts per source of Included / Review / Excluded, of each Mapping Status and Confidence Level,
  and list the "Not in taxonomy" manufacturers and "Company not listed for this category" combinations
  as proposed taxonomy additions.
```
