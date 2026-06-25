# Romania - e-licitatie.ro / SEAP / SICAP

- Portal: `https://www.e-licitatie.ro/pub`
- Access: Public notice pages are available without VPN or login.
- Public granularity: Public pages expose tender/award notices, and public snippets show sections for lot information and contract-object details.
- 2024+ awarded/complete/published count: Exact aggregate was not publicly exposed in a simple official summary endpoint during this pass.
- Tender-item extraction feasibility: `Medium to High` because public award/tender pages appear to include lot/object sections; operationally this likely requires endpoint discovery plus crawl logic.
- Notes: Promising public source, but counting from `2024-01-01` onward needs a dedicated crawl/API mapping step.

## 2026-06-10 TED-backed scrape update

- Added a TED-backed Romania live awarded medical path through `scripts/probe_ted_medical_awards.py` and `harness.sources.romania_sicap.live_medical_awarded_rows()`.
- Completed a full-window broad medical-equipment scrape for `main-classification-proc = 33100000`, `2024-01-01` through `2026-06-10`.
- Output: `Romania/seap-sicap/medical_awarded_rows_ted_33100000_2024_recent.csv`.
- Rows: `19`.
- Strong fields: source, country, publication date, title, description, buyer, classification, status, awardee when exposed, item/lot description, notice id, notice URL, query text, scraped timestamp, and dedup key.
- Known limitation: TED XML downloads were rate-limited during the run, so XML-throttled notices used TED search-result fallback fields. Fallback rows preserve public evidence but leave values such as quantity, unit, unit price, awarded value, currency, and contract period blank when not exposed by the search response.
- SICAP direct-acquisition evidence remains the stronger path for item quantity/unit/unit-price where page IDs are known, but broad SICAP discovery is still not production-ready.

## 2026-06-12 full TED search scrape

- Ran `scripts/run_romania_ted_full_scrape.py` for `2024-01-01` through `2026-06-12`.
- Output: `Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12.csv`.
- Audit: `Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12_audit.json`.
- Combined rows: `898641`.
- Checkpoint chunks:
  - `2024-01-01_to_2024-03-31.csv`: `96203`
  - `2024-04-01_to_2024-06-30.csv`: `81471`
  - `2024-07-01_to_2024-09-30.csv`: `70012`
  - `2024-10-01_to_2024-12-31.csv`: `78878`
  - `2025-01-01_to_2025-03-31.csv`: `92776`
  - `2025-04-01_to_2025-06-30.csv`: `100741`
  - `2025-07-01_to_2025-09-30.csv`: `100455`
  - `2025-10-01_to_2025-12-31.csv`: `89425`
  - `2026-01-01_to_2026-03-31.csv`: `110849`
  - `2026-04-01_to_2026-06-12.csv`: `77831`
- Fully populated columns across all `898641` rows: source, country, country code, publication date, title, description, buyer, classification, status, awardee, item number, item description, notice id, notice URL, query text, scraped timestamp, and dedup key.
- Mostly populated award-value columns: currency and awarded currency are populated on `898639` rows; amount, awarded value, and item award are populated on `613265` rows.
- TED search does not expose closing date, contract period, item unit, item quantity, or item unit price for these rows. Those fields remain blank under the proof standard rather than being invented.

## 2026-06-12 text enrichment pass

- Ran `scripts/enrich_romania_ted_rows.py` over the full TED search scrape.
- Output: `Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12_enriched.csv`.
- Audit: `Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12_enriched_audit.json`.
- Rows preserved: `898641`.
- Evidence-backed fields recovered from visible row text:
  - item quantity: `14560`
  - item unit: `14560`
  - item unit price: `9857`
  - contract period/delivery-duration text: `187880`
- Remaining blanks are source-limited under the proof standard; no placeholders were invented.

## 2026-06-12 v2 TED field expansion

- Added TED search fields for contract duration and attempted tender deadline/quantity/unit fields.
- Reran the full `2024-01-01` through `2026-06-12` scrape without removing rows.
- Output: `Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12_v2_enriched.csv`.
- Audit: `Romania/seap-sicap/medical_awarded_rows_ted_search_full_2024_2026-06-12_v2_enriched_audit.json`.
- Rows preserved: `898641`.
- Final v2 coverage highlights:
  - contract period: `898538`
  - item quantity: `14565`
  - item unit: `14562`
  - item unit price: `9860`
  - amount/awarded value/item award: `613265`
  - closing date: `0`
- TED award search results did not expose closing dates for these award rows. Under the proof standard, closing dates remain blank rather than being inferred or fabricated.
