# Poland - ezamowienia.gov.pl

- Portal: `https://ezamowienia.gov.pl/en/`
- Access: Public pages and public API/statistics endpoints load normally without VPN or login.
- Public granularity: Public search pages are mainly tender/procedure-level. Lot-level detail exists in public notice bodies, but it is embedded in HTML rather than a clean `lots[]` or `items[]` structure.
- 2024+ awarded/complete/published count as of `2026-06-03`:
  - Published: `322,142` `ContractNotice` only, or `332,927` including `SmallContractNotice`
  - Awarded: `337,962` `TenderResultNotice`
  - Completed: `591,101` `ContractPerformingNotice`
- Tender-item extraction feasibility: `High` for tender-level and `Medium` for lot-level with HTML parsing.
- Notes: Counts are notice counts, not deduplicated unique tenders.
