# Egypt UPA Tenders (EG_UPA)

Website: https://upa.gov.eg/tenders/

## Website: search & filters

The UPA tenders page is a public listing of tender posts/download pages. The visible filter is primarily the **site search** on the tenders page.

In addition, the site exposes a WordPress REST search endpoint:

- `https://upa.gov.eg/wp-json/wp/v2/search?search=<text>`

## Tool: what it does

This tool is a requests-based scraper that:

1) fetches the public tenders listing page,
2) extracts tender download links (e.g., `/download/<slug>/`),
3) applies an optional keyword filter locally.

## Quick start

```bash
python "Egypt Procurement/egypt_upa_scraper.py" \
  --date-from 2026-03-01 \
  --date-to 2026-03-14 \
  --query "pharmaceutical" \
  --output-target "./_local_outputs" \
  --project-name "MDT_2026" \
  --website-id "EG_UPA" \
  --source-label "Egypt UPA" \
  --region "EMEA"
```

## Notes / limitations

- Publication dates and structured fields are not consistently available on the listing page; the tool captures URLs and uses lightweight normalization.
- If you need richer metadata (dates, buyer, value), the scraper needs per-tender page parsing (or a stable API that provides structured tender records).
