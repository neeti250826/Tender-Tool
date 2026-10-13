# Task: assign IVD player/brand to Turkish EKAP tender suppliers

## Objective
For each supplier in Turkey's EKAP public-tender award data, determine which **IVD
(in-vitro diagnostics) manufacturer brands** that company distributes or represents in
Turkey, and write the result into the `All` sheet of the supplier workbook.

## Files (Windows paths, all exist)

**Target workbook — this is what you must update:**
`<DOWNLOADS>\Turkey EKAP Supplier Names (2).xlsx`
- Sheet `All` — 63,936 rows incl. header. Col A `supplier_name` (Turkish legal name),
  col B `supplier_name_en` (machine translation). One row per tender line item, so
  suppliers repeat.
- Sheet `Mapped` — 8,875 rows, same two columns; a previously filtered IVD-relevant
  subset (860 unique suppliers). Leave it alone unless asked.

**Source tender data — richer context, same rows:**
`<DOWNLOADS>\Turkey_EKAP_Final_updated_with_estimates_FIXED.xlsx`
- Sheet `Target Schema Rows` — 63,935 data rows, **verified row-for-row aligned with
  the `All` sheet** (zero mismatches on `supplier_name`, index i in `All` == index i
  here). Useful columns: `supplier_name`, `supplier_name_en`, `item_description`,
  `item_description_en`, `title_en`, `awarding_agency_name_en` (the buying hospital),
  `Approximation cost`, `amount`, `notice_url`, `source_cpv_code`,
  `source_ivd_segment`, `Segment` (Roche segment, formula — read with
  `data_only=True`), `Level3_Roche`.
- Sheet `Supplier to Brand - ChatGPT` — 789 rows, a **prior attempt that mostly failed**
  (returned "Unidentified" for almost everything). Use only as a seed list to verify;
  do not trust or copy its values.

**Working directory for scripts/intermediates:** `<WORKSPACE>\mapping\`

## Facts already verified — do not re-derive, and do not chase the dead ends

- 2,172 raw distinct `supplier_name` values; 2,158 after trivial whitespace/case
  normalization. At least one name has a **leading space**.
- Supplier concentration by line-item count: top 200 = 62% of rows, top 500 = 83%,
  top 800 = 92%.
- **Only 18 of 2,158 suppliers have an OEM brand inside their legal name**
  (Roche Diagnostics Türkiye, Beckman Coulter, Sysmex, EUROIMMUN, PerkinElmer,
  Gen Era, Dirui, Anatolia, Trivitron, plus non-IVD ones like Medtronic, J&J, Baxter).
- **Item descriptions carry almost no brand signal.** Scanning 63,935 rows for ~60 brand
  tokens found only: Mindray 285, Nihon Kohden 196, Thermo 75, Dimension 10, Illumina 9,
  Erba 8, Horiba 5, everything else ≤2.
- **DEAD END:** brand hits in `description_en` (365 "THERMO", 169 "ORTHO") are false
  positives — they are CPV code list text ("38412000 - THERMOMETERS",
  orthopedic/hematology CPV strings), not brands. `title`/`description`: 1 hit total.
- **DEAD END:** `<DOWNLOADS>\LabPro Instrument Manufacturers & Install Base
  (CDx + MDx).xlsx` has 69,922 install-base rows but **zero Turkey rows**. Cannot help.
- The Roche `Segment` column resolves for only 287 of the suppliers.
- Beware false-friend names: `BIORAD MEDİKAL VE LABORATUVAR KİMYASALLARI` is a Turkish
  SME, **not** Bio-Rad Laboratories. Same risk for BIOGEN, DIMENSION, MEDISON. Also
  generic Turkish words that collide with brands (ANATOLIA, GENERA, ERBA, INOVA, MAST,
  ATLAS) — only treat as a brand when the name also carries diagnostics/lab context.

## Method — follow this order

### Step 1 — Normalize supplier identity
Collapse `supplier_name` to a canonical entity key: strip legal forms (LİMİTED ŞİRKETİ,
ANONİM ŞİRKETİ, SAN., TİC., LTD., A.Ş.), branch suffixes (ŞUBESİ), punctuation and
duplicate whitespace; fold Turkish characters (İ/I/ı, Ş, Ğ, Ü, Ö, Ç) consistently.
Emit a mapping raw_name → entity_key and work at entity level from here on, so one
research result covers every row of that company.

### Step 2 — Brand → distributor sweep (PRIMARY METHOD, needs web access)
Do **not** research 2,000 companies one at a time — that is the mistake that made the
previous attempt fail. Invert the direction:

For each of ~60–80 IVD manufacturers, find their **authorized Turkish distributors /
partners** (OEM "distributor locator", "partners", "bayilerimiz", Türkiye office pages,
EXPOMED/Medlab exhibitor lists). Manufacturers to cover: Roche, Abbott, Siemens
Healthineers, Beckman Coulter, Sysmex, bioMérieux, Bio-Rad, Thermo Fisher, DiaSorin,
Werfen/Instrumentation Laboratory, Ortho Clinical/QuidelOrtho, Mindray, Snibe/Maglumi,
Getein, Randox, Erba Mannheim, Horiba, Tosoh, Diatron, Stago, Sebia, EUROIMMUN, Agappe,
Dirui, Maccura, Autobio, Wondfo, URIT, Rayto, Nova Biomedical, Radiometer, Cepheid,
QIAGEN, Illumina, Hologic, Sakura, Leica Biosystems, Dako/Agilent, Ventana, Greiner
Bio-One, Sarstedt, BD, Copan, Liofilchem, Oxoid, Arkray, Trivitron, ELITech, DIALAB,
Vircell, plus Turkish makers: Gen Era, Anatolia Geneworks, Bioeksen, RTA Laboratuvarları,
DIAGEN, Vitrosens, Archem, Mikrogen.

Build a brand → Turkish-distributor table, then fuzzy-join those distributor names back
onto the normalized supplier entities. This yields far more coverage per query than
per-company searching, and every hit has a citable source.

### Step 3 — Name-embedded OEM detection
Apply a brand-token rule over both the Turkish and English names, on word boundaries,
with the false-friend and generic-token guards described above. Expect ~18 hits.

### Step 4 — Targeted per-company research for the remaining high-value gaps
Only for entities still unresolved, ordered by **award value** (`Approximation cost`)
rather than row count. Search the Turkish name: `"<name>" distribütör marka`,
`<name> yetkili distribütör`, `<name> markalarımız`, and the likely site
`<firstword>medikal.com.tr`. Cross-check plausibility against what the company actually
sold (`item_description_en` for its rows).

### Step 5 — Optional, high value if it pans out: EKAP notice probe
`notice_url` is populated for every row (`https://ekapv2.kik.gov.tr/ekap/search/<hash>`).
Fetch ~50 notices and check whether the tender/technical specification names a brand
("marka", "veya muadili"). If it does, this becomes **row-level** brand evidence rather
than company-level inference — report back before scaling it up.

## Evidence discipline (most important instruction)
- Only record a brand you found **actual evidence** for. Never infer a plausible brand
  because a company "looks like a lab distributor".
- A previous run returned "Unidentified" for nearly everything. The fix is better
  method, **not** more confident guessing. A fabricated brand is far worse than an
  honest "Unidentified".
- Always store the URL you relied on. Never invent a URL.
- Most of these firms are **multi-brand jobbers** — record all brands found, plus a
  single primary. Where a company clearly sells different brands in different segments,
  note that in `product_areas` rather than forcing one brand.

## Output

**1. Update the `All` sheet in place**, preserving cols A and B byte-for-byte and the
existing row order (row alignment with the tender file must survive). Append:
- C `IVD Player/Brand(s)` — semicolon-separated, or `Unidentified`, or blank if not IVD
- D `Primary Brand`
- E `Own Brand` (if they manufacture their own)
- F `IVD Relevance` — `Yes` / `Partial` / `No`
- G `Product Areas` — e.g. clinical chemistry, hematology, histopathology
- H `Confidence` — `High` / `Medium` / `Low`
- I `Evidence` — one short sentence naming the source
- J `Source URL`

**2. Add a `Supplier Brand Map` sheet** — one row per normalized entity with the same
fields plus raw-name variants, line-item count and total award value. This is the
reusable artifact.

**3. Write a short `README` sheet or markdown note** stating: method used, how many
entities were resolved with a named brand, how many are Unidentified, and what share of
line items and award value the resolved set covers.

## Constraints & QC
- Use `openpyxl` in Python. The target workbook has only two plain data sheets, so a
  read-modify-write round trip is safe. Do **not** round-trip the
  `..._FIXED.xlsx` source file — it contains formulas and pivots; open it read-only.
- Every one of the 63,935 data rows must end up with a value in col F (even if `No`).
- Re-verify after writing: `All` still has 63,935 data rows; cols A/B unchanged; the
  count of distinct suppliers is unchanged.
- Print a summary table of the top 30 brands by number of line items attributed, and
  by award value — this is a sanity check. If Roche/Abbott/Siemens do not appear near
  the top, something is wrong with the mapping.
- Keep intermediate JSON in `<WORKSPACE>\mapping\` so the run is
  resumable; do not delete it at the end.
