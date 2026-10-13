# UAE - Dubai eSupply past opportunities (esupply.dubai.gov.ae)

JAGGAER portal, no login. Past opportunities (~185k) publish requested item lines + quantities but no award, winner or price. Export via `list.si?export=xls` is capped at 2,000 rows and the list is sorted by closing date, so exports are taken per publication **day** with operator EQUAL.

* `esupply_probe.js` - page structure / filter field discovery.
* `esupply_export.js` - filter by buyer text with the page's own `setListUserAct` / `xhrPostListForm`, then export.
* `esupply_crawl.js` - walk backwards in time ("Publication Date BEFORE d") for buyers containing a term (default `Health`).
* `esupply_daily.js` - one export per publication day between two dates, resumable -> `daily/<yyyy-mm-dd>.xlsx`.
* `oldest_date.py` - print row count and oldest publication date of an export.
* `build_uae.py` - parse item lines from Description (`n: [code] ITEM - qty UOM`), map category from item text, year = publication year -> `UAE_Dubai_eSupply_Volume.xlsx`. Volume signals only.

openpyxl `read_only=True` sees one row in these exports; load them normally.
