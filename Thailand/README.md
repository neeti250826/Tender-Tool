# Thailand Tender Scripts

Thailand contains the Clearstate GProcurement scraper workflow.

## Setup

```powershell
pip install -r Thailand/requirements.txt
python -m playwright install
```

## Scripts

- `scripts/Collect_urls.py` - collects tender URLs from Thailand GProcurement.
- `scripts/process_tender_urls_contract_period_fixed.py` - processes tender URLs and extracts detail/item data.

## Run Commands

Start Microsoft Edge manually in remote debugging mode first, then run:

```powershell
python Thailand/scripts/Collect_urls.py
python Thailand/scripts/process_tender_urls_contract_period_fixed.py
```

## Notes

The Clearstate instructions require solving Cloudflare manually in the debug Edge session before running the scraper.

## Documentation

- `docs/README_clearstate.md`
