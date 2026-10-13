# Kuwait - CAPT winning bids (capt.gov.kw)

`/en/tenders/winning-bids/?meeting_date_from=YYYY-MM-DD&meeting_date_to=...&form=date&page=N` with `X-Requested-With`, 10 rows per page, all ministries, back to 2022. Tender-level only (subject, organisation, winner, total KWD); item popups exist for some rows but carry price without description. Behind Cloudflare since Oct 2026 plus a terms popup, so the crawl runs inside the user's debug Edge tab over CDP.

* `open_capt_tab.js`, `capt_agree.js` - open the site in the debug browser and accept the terms popup (user-approved).
* `capt_probe.js`, `capt_get.js`, `capt_search.js` - endpoint / filter discovery; `capt_search.js` writes `capt_ministries.json`.
* `capt_crawl.js` - month by month 2024-01 .. 2026-10 -> `capt_awards.json`, health-award popups -> `capt_popups/`.
* `build_kuwait.py` - translate Arabic subjects (cached), map AR-first then EN through the vocab layer, flag health awards -> `KW_CAPT_Awards.xlsx`. Volume signals only.

Finding: Ministry of Health awards listed here are services / maintenance, not devices.
