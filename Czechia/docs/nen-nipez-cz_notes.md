# Czechia - nen.nipez.cz

- Portal: `https://nen.nipez.cz/en/verejne-zakazky`
- Access: Public listing and detail pages load normally without VPN or login.
- Public granularity: Public tender-level data is available, and the public UI also references lots and subject-matter items.
- 2024+ awarded/complete/published count: Exact count was not publicly exposed in a simple summary endpoint during this pass. The public list is chronologically ordered and shows statuses such as `Awarded` and `Termination of performance`, but a defensible 2024+ aggregate would require controlled pagination/filter crawling or a separate official reporting endpoint.
- Tender-item extraction feasibility: `Medium to High` because public details appear to include lots and item sections.
- Notes: Good candidate for extraction, but counting methodology needs a dedicated crawl/reporting step.
