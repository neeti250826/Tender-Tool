# Saudi Arabia - NUPCO (nupco.com)

NUPCO lists ~119 tenders at `nupco.com/tenders/tenders-list/{1..5}/`; each tender page links PDFs: Item List (requested qty), Preliminary Result, Final Result. Final results give item code, description, UOM, vendor, manufacturer, model, country. **No prices anywhere.** Frameworks are multi-award.

Order of work:
1. `pw_nupco.js` - visit every tender page (Playwright, headed Chrome), capture text + PDF links -> `nupco_pages.json` (feeds `nupco_manifest.json`).
2. `dl_itemlists.js` - download the item lists in `itemlist_targets.json` -> `items/`.
3. `parse_nupco_itemlists.py` - item lists (pdf/xlsx) -> `nupco_itemlist_qty.csv` (tender, NUPCO code, description, UOM, qty).
4. `parse_nupco_finals.py` - final-result PDFs -> award rows, aligning cells by each header's raw column span (merged cells shift columns).
5. `parse_nupco_0033_25.py` - NPT0033/25 has overlapping text layers; line-regex parser that replaces that tender's rows.
6. `build_ksa.py` - map each NUPCO code once from its description (vocab layer), Company from the manufacturer column, weight 1/n per winner, value = qty x UOM factor x reference price from `Shared_TURMECA_Pipeline/ref_prices.csv` when a category is priced. Award year from `final_result_dates.json`. Output `KSA_NUPCO_Awards_Mapped.xlsx`.

Etimad (tenders.etimad.sa) was probed but not built: the visitor list JSON works, award details trip anti-bot and redirect to login.
