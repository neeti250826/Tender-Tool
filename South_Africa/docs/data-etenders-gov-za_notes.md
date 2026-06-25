# South Africa - data.etenders.gov.za

- Portal: `https://data.etenders.gov.za/`
- Access: Public site, bulk-download area, and OCDS API are reachable without VPN or login.
- Public granularity: Strong public tender-level OCDS data is available, including tender status, documents, awards, and contracts. Clean line-item structures were not confirmed in this pass.
- 2024+ awarded/complete/published count: Exact `2024-01-01` onward aggregate was not fully materialized in this pass, but the site provides the public API and monthly bulk files needed to derive it programmatically. Current all-time public inventory shown on the homepage as of `2026-06-03` is `150,518` tenders published, `62,201` awards, and `4,907` contracts.
- Tender-item extraction feasibility: `High` for tender-level extraction and `Low to Medium` for item-level unless item lines exist only inside attached documents.
- Notes: Best source in this set for systematic API-based collection.
