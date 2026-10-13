# Pakistan (Khyber Pakhtunkhwa) - DGHS / Health Dept bid evaluation reports

Sources: dghskp.gov.pk and healthkp.gov.pk (reachable only from a Pakistan-side egress; from this PC via VPN, plain http). BER PDFs list bids with item, make/model, origin and **unit price** but no quantity. `kp_targets.json` lists the PDFs pulled.

* `parse_kp_mcc.py` - Govt. MCC (Medicines Coordination Cell) BERs FY2023-24 .. 2026-27 (drugs + surgical disposables) -> `kp_mcc_bids.csv`, `kp_mcc_items.csv`. Numeric cells read from the right; winner = highest final total. FY2025-26 uses the text Draft Comparative Statement because the approved BER is a scan.
* `parse_kp_ber.py` - DGHS "Selection and Rate Contracting of Medical Equipment ..." BERs -> `kp_ber_bids.csv`. Winner = highest total marks.
* `build_pakistan.py` - one row per bid, Winner flag, category from item text, Company from make/brand text -> `PK_KP_BER_Mapped.xlsx`.

These winning unit rates also feed `Shared_TURMECA_Pipeline/build_ref_prices.py` (reference prices for the KSA valuation). MCC item numbers are reused for different items across years, so never join across years by MCC number.
