# South Korea Tender Scripts

South Korea contains Clearstate G2B scraper versions for 2024, 2025, and 2026.

## Scripts

- `South_Korea_2024/g2b_production_scraper_buyer_final.py`
- `South_Korea_2025/g2b_production_scraper_buyer_final.py`
- `South_Korea_2026/g2b_production_scraper_buyer_final.py`

Each year folder also includes `G2B_Scraper_Documentation.md` and `Korea_Tender_Website_Guide.docx`.

## Run Commands

```powershell
python South_Korea/South_Korea_2026/g2b_production_scraper_buyer_final.py
```

## Notes

The G2B portal is a dynamic WebSquare-style site. The scraper includes popup handling, internal grid scrolling, resume logic, supplier popup parsing, and item-level extraction rules.
