# Egypt - gcs.digitalegypt.gov.eg

- Portal: `https://gcs.digitalegypt.gov.eg/`
- Access: Not reachable from the current normal connection on `2026-06-05`; hostname resolution failed with `curl: (6) Could not resolve host: gcs.digitalegypt.gov.eg`. VPN need is not proven, but a different resolver or Egypt-based network should be tested.
- Public granularity: Saved direct HTML evidence in this repo proves public tender-detail fields plus item-level fields for at least one tender, including item name, unit, quantity, publication timestamp, and award-stage signal.
- 2024+ awarded/complete/published count: Not publicly verifiable from this pass because the official portal was unreachable live from this environment.
- Tender-item extraction feasibility: `Medium` for tender metadata and `Medium` for item-level extraction once the portal is reachable again; the saved fixture proves the portal shape, but not a full live crawl from this machine.
- Notes: The current saved sample row is now `Awarded`, with `closing_date=2025-11-10` taken from the matching homepage card’s `اخر تاريخ لتلقى الطلبات`, while the detail page continues to provide `publication_date`, `item_desc`, `item_uom`, and `item_quantity`.
