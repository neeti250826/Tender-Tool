# Tender Tool

Country-level tender and awarded-contract scrapers collected from local Codex work.

## Repository Layout

- `Singapore/` - GeBIZ scraper scripts and documentation.
- `Pakistan/` - PPRA, DRAP, EPADS, ADB, World Bank scrapers plus shared Pakistan run/combine commands.
- `Kuwait/` - CAPT winning-bids scraper, PDF helper, verified seed rows, and exclusion notes.
- `UAE/` - Dubai eSupply scraper.
- `Ecuador/` - ComprasPublicas scraper.
- `Malaysia/`, `Vietnam/`, `Colombia/` - country documentation and recovered output inventory. No source scraper was found locally for these countries yet.
- `docs/` - shared TURMECA documentation and source-status notes.
- `procurement_utils.py` - shared utility functions used by Pakistan, Kuwait, and UAE scripts.
- `run_awarded_scrapers.py`, `run_item_level_scrapers.py`, `combine_pakistan_awards.py` - cross-country or Pakistan consolidation runners.

## Setup

Run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Some scripts use live public procurement portals. Captchas, session expiry, portal outages, and date-window restrictions can require manual retries.

## Country READMEs

Each country folder has a `README.md` with:

- the scripts in that country folder
- setup notes
- exact run commands
- an AI prompt you can give Codex or another AI assistant to run the script and summarize the output
- documentation links, including generated HTML documentation where the source did not already have one

## Data Policy

Generated CSV/JSONL/XLSX outputs are ignored by git under `output/` folders. This keeps the repository focused on scripts, important documentation, and reproducible instructions.

