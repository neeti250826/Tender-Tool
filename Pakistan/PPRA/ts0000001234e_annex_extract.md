# TS0000001234E Annex Extract

Date checked: 2026-05-31

## Source

- Public PPRA tender detail: `https://epms.ppra.gov.pk/public/tenders/tender-details/TS0000001234E`
- Official tender document download path from the tender detail page:
  - `https://epms.ppra.gov.pk/pdf?file=dGVuZGVyX2F0dGFjaG1lbnRzLzE3NzE0MDI1MTZfNjk5NTc1MTQzMDQ5ZC5wZGY%3D`

## Verified high-level facts

- The document is a `41`-page PPRA PDF.
- The title is `LAB TESTS (REAGENT RENTAL CONTRACT)`.
- The `DP-2` section states:
  - `Category of items: LAB TESTS (Reagent Rental) (226 x Items)`
  - `List of items and quantities: As per Annex A`
- Browser-side PDF text inspection also confirms that Annex A contains individual test rows with two-year test volumes.

## Why this has not been materialized yet

- Direct shell-side fetch of the official attachment still times out from this environment.
- Browser-side PDF access is strong enough to prove that the annex exists and that it contains many item rows, but not yet strong enough to justify a complete 226-row materialization into the saved PPRA output without a reliable workspace-side extraction path.

## Browser-visible sample rows

These samples were read directly from the official PPRA PDF text in browser context and are sufficient to prove that the single saved package row has major item-level expansion upside.

### SHF section examples

- `1` `LAB URINARY ALBUMIN` `Chemical Pathology Test` `15,158`
- `2` `LAB SERUM ALBUMIN` `Chemical Pathology Test` `14,120`
- `3` `LAB ALKALINE PHOSPHATASE` `Chemical Pathology Test` `267,300`
- `4` `LAB SERUM ALT` `Chemical Pathology Test` `294,440`
- `5` `LAB SERUM AMYLASE` `Chemical Pathology Test` `16,576`
- `6` `LAB SERUM AST` `Chemical Pathology Test` `880`
- `7` `LAB SERUM BILIRUBIN - DIRECT` `Chemical Pathology Test` `4,318`
- `8` `LAB SERUM BILIRUBIN TOTAL` `Chemical Pathology Test` `264,000`
- `9` `LAB SERUM CALCIUM` `Chemical Pathology Test` `35,200`
- `20` `LAB SERUM IRON` `Chemical Pathology Test` `19,800`
- `21` `LAB SERUM LACTATE` `Chemical Pathology Test` `1,540`
- `22` `LAB SERUM LDH` `Chemical Pathology Test` `17,600`
- `23` `LAB SERUM LDL` `Chemical Pathology Test` `52,800`
- `24` `LAB SERUM LIPASE` `Chemical Pathology Test` `13,200`
- `25` `LAB SERUM MAGNESIUM` `Chemical Pathology Test` `24,640`
- `26` `LAB SERUM AMMONIA` `Chemical Pathology Test` `1,100`
- `27` `LAB SERUM OPIATES` `Chemical Pathology Test` `6,160`
- `28` `LAB SERUM PHOSPHORUS` `Chemical Pathology Test` `22,000`
- `29` `LAB URINE THC` `Chemical Pathology Test` `6,160`
- `30` `LAB SERUM TOTAL PROTEIN` `Chemical Pathology Test` `1,320`
- `31` `LAB URINARY PROTEIN` `Chemical Pathology Test` `3,080`
- `32` `LAB SERUM TG` `Chemical Pathology Test` `52,800`
- `33` `LAB SERUM URIC ACID` `Chemical Pathology Test` `41,360`
- `34` `LAB SERUM UIBC` `Chemical Pathology Test` `10,104`
- `35` `LAB SERUM UREA` `Chemical Pathology Test` `281,600`
- `36` `LAB SERUM AFP` `Chemical Pathology Test` `2,200`
- `37` `LAB SERUM CA 125` `Chemical Pathology Test` `1,540`
- `38` `LAB SERUM CEA` `Chemical Pathology Test` `1,540`
- `39` `LAB SERUM CORTISOL` `Chemical Pathology Test` `2,200`
- `41` `LAB SERUM FERRITINE` `Chemical Pathology Test` `19,150`
- `42` `LAB SERUM FOLATE` `Chemical Pathology Test` `11,248`
- `43` `LAB SERUM FSH` `Chemical Pathology Test` `9,482`
- `44` `LAB SERUM FT3` `Chemical Pathology Test` `15,362`
- `45` `LAB SERUM FT4` `Chemical Pathology Test` `43,548`
- `46` `LAB SERUM BETA HCG` `Chemical Pathology Test` `14,960`
- `47` `LAB SERUM IGE LEVEL` `Chemical Pathology Test` `4,202`
- `48` `LAB SERUM INSULINE` `Chemical Pathology Test` `880`
- `49` `LAB SERUM LH` `Chemical Pathology Test` `8,998`
- `50` `LAB SERUM PCT` `Chemical Pathology Test` `2,200`
- `51` `LAB SERUM PROBNP` `Chemical Pathology Test` `9,680`
- `52` `LAB SERUM PROGESTRONE` `Chemical Pathology Test` `2,200`
- `53` `LAB SERUM PROLACTIN` `Chemical Pathology Test` `8,800`
- `54` `LAB SERUM PTH` `Chemical Pathology Test` `1,320`
- `55` `LAB SERUM TESTOSTERONE` `Chemical Pathology Test` `2,860`
- `56` `LAB SERUM TOTAL PSA` `Chemical Pathology Test` `2,948`
- `57` `LAB SERUM TROP I STAT` `Chemical Pathology Test` `33,440`
- `58` `LAB SERUM TSH` `Chemical Pathology Test` `68,200`
- `59` `LAB SERUM VIT B-12` `Chemical Pathology Test` `27,048`
- `60` `LAB SERUM VIT D TOTAL` `Chemical Pathology Test` `27,720`
- `61` `LAB SERUM POTASSIUM` `Chemical Pathology Test` `295,038`
- `62` `LAB SERUM SODIUM` `Chemical Pathology Test` `284,386`
- `63` `LAB SERUM CHORIDE` `Chemical Pathology Test` `638`
- `64` `LAB HBSAG CLIA` `Virology Test` `72,000`
- `65` `LAB ANTI HCV CLIA` `Virology Test` `72,000`
- `66` `LAB ANTI HIV CLIVA` `Virology Test` `32,000`
- `67` `LAB CBC` `CBC Test` `734,632`
- `68` `LAB ESR` `Haematology Test` `80,000`
- `69` `LAB RETIC COUNT` `CBC Test` `12,200`
- `70` `LAB PT` `Haematology Test` `112,560`
- `71` `LAB APTT` `Haematology Test` `104,468`
- `72` `LAB FIBRINOGEN` `Haematology Test` `9,000`
- `73` `LAB D-DIMER QUALITATIVE` `Haematology Test` `2,000`
- `74` `LAB D-DIMER QUANTITATIVE` `Haematology Test` `8,800`
- `75` `LAB PROTIEN C` `Haematology Test` `360`
- `76` `LAB PROTIEN S` `Haematology Test` `360`
- `77` `LAB ANTI THROMBIN III` `Haematology Test` `360`
- `78` `LAB APCR (FACTOR V LEIDEN)` `Haematology Test` `360`
- `79` `LAB FACTOR IX` `Haematology Test` `240`
- `80` `LAB FACTOR X` `Haematology Test` `240`
- `81` `LAB FACTOR V` `Haematology Test` `240`
- `82` `LAB FACTOR VII` `Haematology Test` `240`
- `83` `LAB FACTOR VIII` `Haematology Test` `360`
- `84` `LAB G6PD QUANTITATIVE` `Haematology Test` `2,800`
- `85` `LAB THROMBIN TIME` `Haematology Test` `240`
- `86` `LAB ACTH` `Chemical Pathology Test` `4,000`
- `87` `LAB GROWTH HARMONE` `Chemical Pathology Test` `4,000`
- `88` `LAB ABGS` `Chemical Pathology Test` `40,000`
- `89` `LAB DHEA-S` `Chemical Pathology Test` `400`
- `90` `LAB ANTI CCP` `Chemical Pathology Test` `400`
- `91` `LAB ANTI TTG` `Chemical Pathology Test` `400`
- `92` `LAB ANTI TPO` `Chemical Pathology Test` `400`
- `93` `LAB TRAB` `Chemical Pathology Test` `400`
- `94` `LAB IGA` `Chemical Pathology Test` `400`
- `95` `LAB IGM` `Chemical Pathology Test` `400`
- `96` `LAB KAPPA LIGHT CHAIN` `Chemical Pathology Test` `800`
- `97` `LAB LAMBDA LIGHT CHAIN` `Chemical Pathology Test` `800`
- `98` `LAB FDP QUANTITATIVE` `Haematology Test` `5,000`
- `99` `LAB SEMEN ANALYSIS` `Haematology Test` `8,000`
- `100` `LAB VON WILLEBRAND FACTOR` `Haematology Test` `320`
- `101` `LAB LUPUS ANTI COAGULANT` `Haematology Test` `340`
- `102` `LAB URINE RE (AUTOMATED)` `Clinical Pathology Test` `90,000`
- `103` `LAB TPHA QUANTITATIVE` `Microbiology Test` `30,000`

### RHT section examples

- `104` `LAB CBC` `CBC Test` `210,000`
- `105` `LAB GLUCOSE` `Chemical Pathology Test` `48,000`
- `106` `LAB SERUM UREA` `Chemical Pathology Test` `50,000`
- `107` `LAB SERUM CREATININE` `Chemical Pathology Test` `54,000`
- `108` `LAB SERUM SODIUM` `Chemical Pathology Test` `15,600`
- `109` `LAB SERUM POTASSIUM` `Chemical Pathology Test` `15,600`
- `110` `LAB SERUM CHOLESTROL TOTAL` `Chemical Pathology Test` `26,000`
- `111` `LAB SERUM TRIGLYCRIDE` `Chemical Pathology Test` `19,000`
- `112` `LAB SERUM LDL` `Chemical Pathology Test` `2,000`
- `113` `LAB SERUM HDL` `Chemical Pathology Test` `2,000`
- `114` `LAB CRP QUANTITATIVE` `Chemical Pathology Test` `41,000`
- `115` `LAB SERUM AMYLASE` `Chemical Pathology Test` `6,400`
- `116` `LAB SERUM LIPASE` `Chemical Pathology Test` `6,200`
- `117` `LAB SERUM CALCIUM` `Chemical Pathology Test` `3,000`
- `118` `LAB SERUM MG` `Chemical Pathology Test` `1,600`
- `130` `LAB HBA1C` `Chemical Pathology Test` `30,000`
- `131` `LAB TSH` `Chemical Pathology Test` `12,000`
- `132` `LAB FT3` `Chemical Pathology Test` `8,400`
- `133` `LAB FT4` `Chemical Pathology Test` `8,400`
- `134` `LAB VITD` `Chemical Pathology Test` `8,000`
- `135` `LAB FERRITIN` `Chemical Pathology Test` `3,000`
- `136` `LAB IRON` `Chemical Pathology Test` `2,000`
- `137` `LAB UIBC / TIBC` `Chemical Pathology Test` `2,000`
- `138` `LAB TROP I` `Chemical Pathology Test` `4,400`
- `139` `LAB BETA BHCG` `Chemical Pathology Test` `2,400`
- `140` `LAB SERUM B12` `Chemical Pathology Test` `2,400`
- `141` `LAB ANTI HCV` `VIROLOGY Test` `16,000`
- `142` `LAB HBsAG` `VIROLOGY Test` `16,000`
- `143` `LAB HIV` `VIROLOGY Test` `7,000`
- `144` `LAB PT` `Haematology Test` `8,400`
- `145` `LAB APTT` `Haematology Test` `8,400`
- `146` `LAB SERUM CHLORIDE` `Chemical Pathology Test` `9,600`
- `147` `LAB SERUM FSH` `Chemical Pathology Test` `2,000`
- `148` `LAB SERUM LH` `Chemical Pathology Test` `2,000`
- `149` `LAB SERUM PROLECTIN` `Chemical Pathology Test` `2,000`

### HFZ section examples

- `150` `LAB ALBUMIN (BCG)` `Chemical Pathology Test` `88,000`
- `151` `LAB ALKALINE PHOSPHATASE` `Chemical Pathology Test` `88,000`
- `152` `LAB ALT/SGPT` `Chemical Pathology Test` `98,000`
- `153` `LAB AMYLASE` `Chemical Pathology Test` `9,800`
- `154` `LAB AST/SGOT` `Chemical Pathology Test` `2,400`
- `155` `LAB BIL-T` `Chemical Pathology Test` `106,000`
- `156` `LAB CALCIUM` `Chemical Pathology Test` `8,400`
- `157` `LAB CHOLESTEROL` `Chemical Pathology Test` `24,000`
- `158` `LAB CK-MB` `Chemical Pathology Test` `9,600`
- `159` `LAB CK` `Chemical Pathology Test` `9,600`
- `160` `LAB CREATININE` `Chemical Pathology Test` `84,000`
- `161` `LAB GGT` `Chemical Pathology Test` `200`
- `162` `LAB GLUCOSE` `Chemical Pathology Test` `44,000`
- `163` `LAB HDL-C` `Chemical Pathology Test` `24,200`
- `164` `LAB IRON` `Chemical Pathology Test` `8,000`
- `165` `LAB LACTATE` `Chemical Pathology Test` `400`
- `166` `LAB LDH` `Chemical Pathology Test` `4,000`
- `176` `LAB FERRITIN` `Chemical Pathology Test` `16,000`
- `177` `LAB RF-II` `Chemical Pathology Test` `6,200`
- `178` `LAB TP UR/CSF PROTEIN` `Chemical Pathology Test` `2,200`
- `179` `LAB TSH` `Chemical Pathology Test` `42,000`
- `180` `LAB FT3` `Chemical Pathology Test` `28,200`
- `181` `LAB FT4` `Chemical Pathology Test` `24,000`
- `182` `LAB ANTI-TPO` `Chemical Pathology Test` `400`
- `183` `LAB TRIG` `Chemical Pathology Test` `30,200`
- `184` `LAB FSH` `Chemical Pathology Test` `4,200`
- `185` `LAB LH` `Chemical Pathology Test` `3,800`
- `186` `LAB BETA-HCG` `Chemical Pathology Test` `7,600`
- `187` `LAB PROLACTIN` `Chemical Pathology Test` `4,200`
- `188` `LAB ESTRADIOL` `Chemical Pathology Test` `400`
- `189` `LAB PROGESTERONE` `Chemical Pathology Test` `400`
- `190` `LAB TESTOSTERONE` `Chemical Pathology Test` `400`
- `191` `LAB DHEAS` `Chemical Pathology Test` `800`
- `192` `LAB TROPONIN-I` `Chemical Pathology Test` `9,600`
- `193` `LAB PRO BNP` `Chemical Pathology Test` `4,400`
- `194` `LAB AFP` `Chemical Pathology Test` `1,000`
- `199` `LAB HBSAG` `VIROLOGY Test` `26,000`
- `200` `LAB ANTI-HAV` `VIROLOGY Test` `1,080`
- `201` `LAB ANTI-HAV IGM` `VIROLOGY Test` `1,134`
- `202` `LAB HIV COMBI PT` `VIROLOGY Test` `6,800`
- `203` `LAB ANTI-HCV II` `VIROLOGY Test` `27,000`
- `204` `LAB B12` `Chemical Pathology Test` `6,600`
- `205` `LAB FOLATE` `Chemical Pathology Test` `3,400`
- `206` `LAB ANTI-CCP` `Chemical Pathology Test` `2,800`
- `216` `LAB HbA1c` `Chemical Pathology Test` `36,000`
- `217` `LAB CBC` `CBC Test` `184,000`
- `218` `LAB D DIMER` `Haematology Test` `3,000`
- `219` `LAB ESR` `Haematology Test` `26,000`
- `220` `LAB APTT` `Haematology Test` `20,000`
- `221` `LAB PT` `Haematology Test` `20,000`
- `222` `LAB FIBRINOGIN` `Haematology Test` `3,000`
- `223` `LAB RETIC COUNT` `CBC Test` `3,000`
- `224` `LAB DIRECT BILURUBIN` `Chemical Pathology Test` `1,000`
- `225` `LAB SYPHILIS` `Chemical Pathology Test` `3,000`
- `226` `LAB URINE MICROALBUMIN` `Chemical Pathology Test` `3,000`
- `227` `LAB ANTI MULLERIAN HORMONE` `Chemical Pathology Test` `600`

## Practical next step

- If a reliable workspace-side fetch path becomes available, this note can be converted into a much larger `items` list for `TS0000001234E`.
- Until then, the saved PPRA output should keep `TS0000001234E` as a package row rather than pretending the full annex has been captured end to end.
