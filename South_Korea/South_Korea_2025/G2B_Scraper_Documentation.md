# G2B Scraper Technical Documentation

## Overview

This document describes the structure of the G2B procurement website as encountered during scraper development, the key technical issues that affected extraction reliability, and the solutions implemented in `g2b_production_scraper_buyer_final.py`.

The scraper is designed to:

- open the G2B tender listing page
- apply date and industry filters
- iterate through result rows
- open each tender detail page
- extract tender-level and item-level fields
- optionally extract supplier information from result popups
- save progress incrementally and resume after interruption

---

## Website Structure

### 1. Homepage and Navigation

The portal uses a dynamic menu system and WebSquare-style components.

Observed navigation flow:

1. Open `https://www.g2b.go.kr/`
2. Dismiss homepage warnings/popups
3. Hover `입찰`
4. Click `입찰공고목록`
5. Wait for the bid listing form to load

Important characteristics:

- the site may partially load before the usable UI is ready
- menu behavior is dynamic and sometimes requires hover before click
- warning popups can block navigation immediately after page load

### 2. Listing Page

The listing page is not a plain HTML table. It behaves like an internal grid with lazy loading and internal scroll state.

Observed elements on the listing page:

- date filter inputs
- `상세조건`
- industry filter popup trigger
- search button
- an internal result grid showing tender rows
- a page-size selector such as `10`
- row actions and tender title links

Important characteristics:

- rows are loaded inside an internal scrollable grid, not necessarily by window scroll
- the visible row set may update only after internal grid scrolling
- some result sets use traditional numeric notice IDs, while others use alphanumeric IDs such as `R25BK...`
- rows can be visibly present while a narrow row detector still returns `0`

### 3. Tender Detail Page

Each tender detail page is a long structured view composed of multiple sections and tables.

Common sections:

- `공고일반`
- `입찰자격`
- `투찰제한-일반`
- `입찰진행현황`
- `가격`
- `기관담당자정보`
- `수요기관담당자정보 목록`
- `구매대상물품`
- `파일첨부`

Important characteristics:

- data is spread across multiple independent tables
- section identity may be stored in table body text, caption, or header labels
- some tables use two-row headers and split one logical item across two visual rows
- browser URL often remains `https://www.g2b.go.kr/` because the site behaves like a SPA

### 4. Supplier / Opening Result Popup

For some tenders, supplier name and bid amount are obtained from the `개찰완료` result popup.

Important characteristics:

- this is not always a full page transition
- sometimes it is a popup/layer
- sometimes closing it returns to the tender detail page
- sometimes a blocking warning modal appears on top of it

### 5. Warning / Error Popups

Several popup types interfere with normal automation:

- homepage informational warnings
- transient server warning modals
- `안내 메시지`
- `서버 오류입니다`
- `code : 0`

Important characteristics:

- some popups include top-right `X` buttons
- some include `확인`
- generic popup closers can accidentally click external social links if not constrained
- these warnings may appear after search, row click, popup close, or list return

---

## Key Data Structures on the Site

### Result Row Structure

A result row typically contains:

- row number
- work type / classification
- notice identifier
- tender title
- notice agency
- demand agency
- publication/opening dates
- progress/status fields

The title is usually the actionable link used to open the tender detail.

### Buyer Data Structure

Buyer extraction was aligned to demand-agency semantics rather than notice-agency semantics.

Current priority:

1. `수요기관담당자정보 -> 수요기관`
2. `구매대상물품 -> 수요기관`
3. generic `수요기관` label/value fallback
4. body-text fallback near `수요기관`
5. listing-row fallback

### Item Table Structure

The `구매대상물품` table frequently uses a two-row logical layout:

Top row example:

- `No`
- `분류`
- `수요기관`
- `세부품명`
- `납품일수`
- `납품장소`

Second row example:

- `수량`
- `단위`
- `추정단가(원)`
- `세부품명번호`
- `물품식별번호`
- `규격`
- `납품기한`
- `인도조건`

Real tender data often appears as:

- row 1: item identity and description
- row 2: quantity, unit, unit price, codes, delivery fields

This was one of the hardest parts of the scraper.

### Amount Structure

Amount extraction follows this business rule:

1. use supplier popup bid amount if available
2. otherwise use tender-page `가격 -> 배정예산`

Stored output format:

- `currency = KRW`
- `amount = numeric value only`

Example:

- source text: `1 원`
- saved amount: `1`

---

## Main Problems Encountered

### 1. Popups Blocking Navigation and Extraction

Symptoms:

- homepage actions interrupted
- row return blocked
- supplier popup close blocked
- random modals appear after search or after clicking a row
- external Twitter/X pages opened accidentally

Root causes:

- generic popup closing logic was too broad
- close candidates could include external links
- `code : 0` warning modal appeared on top of other content

Solution:

- restricted popup closure to real dismiss controls
- explicitly rejected social and external links
- added dedicated handling for `서버 오류`, `code : 0`, and related warning text
- preferred top-right `X` for those modals
- added lightweight warning-dismiss passes after major clicks

### 2. Internal Grid Scrolling Was Not the Same as Window Scrolling

Symptoms:

- only the first visible rows were processed
- repeated logs showed visible rows not changing
- the page visually scrolled but the tender rows did not advance

Root causes:

- result rows live inside an internal WebSquare grid
- scrolling the page is not enough
- not every scrollable ancestor actually changes grid position

Solution:

- `scroll_once()` targets the result grid’s real scrollable ancestor
- `save_scroll()` and `restore_scroll()` preserve the same grid body
- row signature includes grid scroll position
- scrolling logic validates real scroll movement instead of assuming success

### 3. Visible Rows Were Not Recognized as Tender Rows

Symptoms:

- search finished successfully
- rows were visible on screen
- scraper still reported `0 visible tender rows`

Root causes:

- initial row detection expected only numeric G2B notice patterns
- newer result sets used alphanumeric IDs such as `R25BK...`
- some notice numbers also appeared with spaces around the hyphen

Solution:

- widened notice normalization to accept spaced numeric IDs
- broadened row detection to include alphanumeric tender IDs and title-link-based grid rows
- updated scroll-target detection to use the same broader row identification logic

### 4. Buyer Was Being Taken from the Wrong Agency

Symptoms:

- buyer column reflected `공고기관`
- demand agency was present on the page but not captured

Root causes:

- some section matchers only looked at row body text
- relevant tables were identifiable through captions and headers
- buyer logic was too dependent on notice-agency paths

Solution:

- updated `section_table_rows()` and `get_section_rows_v20()` to match on `caption + headers + rows`
- moved buyer logic to demand-agency-first extraction
- added `구매대상물품 -> 수요기관` fallback

### 5. Item Details Were Frequently Misparsed

Symptoms:

- `item_no` and `item_description` present, but `item_quantity` and `item_uom` blank
- fake item numbers like `10`, `14`, `37`
- rows like `규격서 참고` treated as actual items
- only alternating item rows appeared in some tenders

Root causes:

- blank cells were dropped too early, shifting column positions
- second detail row was sometimes treated as a new item
- parser relied too much on loose heuristics instead of stable column positions

Solution:

- item parsing now preserves row positions
- parser identifies the two-row header structure directly
- `수량`, `단위`, and `추정단가(원)` are mapped from header positions
- second row is treated as a detail row when it looks like `quantity + unit + money`
- cleanup removes artifact rows like `규격서 참고` when they lack real quantity and unit

### 6. Awarded Date Was Not Consistent

Symptoms:

- awarded date missing or coming from the wrong process row

Root causes:

- generic process-date logic was too broad
- actual required value was the `개찰일시` column in `입찰진행현황`

Solution:

- added extraction logic that prefers `입찰진행현황 -> 개찰일시`
- broader fallback remains for edge cases

### 7. Amount Fallback Failed When Supplier Data Was Missing

Symptoms:

- supplier popup absent
- amount remained blank even though `배정예산` was clearly visible

Root causes:

- budget parsing needed to be anchored more safely to `배정예산`
- different table shapes exposed budget as KV pairs, row text, or body text

Solution:

- `budget_amount_v21()` now scans:
  - structured KV pairs
  - row-level label/value patterns
  - body-text fallback anchored to `배정예산`
- amount is normalized to value-only output

### 8. Supplier Name Needed Different Business Logic

Symptoms:

- supplier field could be populated with non-supplier agency data

Root causes:

- generic fallback logic filled supplier from tender-side agency fields

Solution:

- supplier name is now blank unless the supplier/opening popup actually returns supplier data
- tender page still provides `배정예산` fallback for amount when supplier data is absent

### 9. Resume Was Unreliable After Failure

Symptoms:

- restart behaved like a fresh run
- row-based resume drifted
- partial progress could be lost after exceptions

Root causes:

- output was not always persisted incrementally
- progress and logs were not used consistently
- weak partial state could override a better resume source

Solution:

- incremental CSV append after each processed tender
- progress JSON stored in `g2b_results_progress.json`
- log file stored in `g2b_results.log`
- resume logic now prefers JSON state when valid
- fallback resume options were added for interrupted runs

### 10. Search Completion Was Assumed Too Early

Symptoms:

- after search, scraper immediately entered the scroll loop
- row extraction started before the grid state was fully resolved

Root causes:

- page readiness does not mean result-grid readiness

Solution:

- added post-search wait for either:
  - visible tender rows
  - explicit empty-result state
- prevents premature scrolling when the result state is still unstable

---

## Implemented Extraction Rules

### Tender-Level Fields

- `notice_id`: derived from tender detail or listing row
- `notice_url`: lookup URL based on notice identifier when SPA URL is not useful
- `title`: `공고명`
- `publication_date`: `게시일시`
- `closing_date`: tender process section or listing row fallback
- `buyer`: demand-agency-first logic
- `amount`: supplier popup amount first, else `배정예산`
- `currency`: always `KRW`
- `supplier_name`: only from supplier popup, otherwise blank
- `awarded_date`: `입찰진행현황 -> 개찰일시`

### Item-Level Fields

- `item_no`: first item-row identifier
- `item_description`: `세부품명`
- `item_quantity`: `수량`
- `item_uom`: `단위`
- `item_unit_price`: `추정단가(원)`
- `contract_period`: delivery-related fields when available

---

## Resume and Output Files

### Output Files

- CSV: `g2b_results.csv`
- progress state: `g2b_results_progress.json`
- runtime log: `g2b_results.log`

### Resume Logic

The scraper now supports:

- incremental save after each processed tender
- JSON-based resume from saved row keys
- fallback row-based resume in edge cases
- preserved logs for manual investigation

Recommended operational behavior:

- use normal run to resume from progress JSON
- use `--fresh-start` only when intentionally restarting from scratch

---

## Remaining Risks and Notes

1. G2B is a dynamic WebSquare-based site, so small DOM changes can still break selectors.
2. Popups and warning modals may appear at unpredictable times.
3. Listing formats may differ by date range or procurement type.
4. Item tables can still vary slightly across tenders, especially when attachments or specifications replace direct values.
5. Some supplier data is only available through the opening/result popup, so popup stability remains important.

---

## Recommended Maintenance Approach

1. Keep debug screenshots enabled during troubleshooting.
2. Review `g2b_results.log` after failed runs.
3. Validate one or two tenders manually whenever a new row format appears.
4. Prefer section-aware extraction over whole-page regex where possible.
5. When a new issue appears, capture:
   - screenshot
   - log block
   - affected notice ID
   - resulting CSV row

This combination has been the most effective for diagnosing failures quickly.

