# Tender Tool

Country-level tender and awarded-contract scrapers collected from local Codex work.

## Current Source Audit

The [2026-10-13 country/website audit](docs/country_website_audit_2026-10-13.md) is the current inventory for both `neeti250826/Tender-Tool` and `Clearstate-SG/Tender-Tools`. It distinguishes extractors, browser workflows, evidence adapters, access probes, and missing code. Updating scripts does not refresh the tender datasets.

Use [country_website_catalog.json](docs/country_website_catalog.json) for exact paths and limitations, [source_sync_manifest.json](docs/source_sync_manifest.json) for version hashes, and [validation_results.json](docs/validation_results.json) for checks performed.

## Repository Layout

- `Singapore/` - GeBIZ scraper scripts and documentation.
- `Pakistan/` - PPRA, DRAP, EPADS, ADB, World Bank scrapers plus shared Pakistan run/combine commands.
- `Kuwait/` - CAPT winning-bids scraper, PDF helper, verified seed rows, and exclusion notes.
- `UAE/` - Dubai eSupply scraper.
- `Ecuador/` - ComprasPublicas scraper.
- `Malaysia/`, `Vietnam/`, `Colombia/` - country documentation; runnable sources are also indexed under `malaysia-moh/`, `malaysia-eperolehan/`, `Vietnam_VNEPS/`, and `colombia-secop/`.
- Lowercase portal packages such as `canada-canadabuys/`, `costa-rica-sicop/`, `hungary-ekr/`, and `united-states-fpds/` preserve the organization repository's source layout.
- `ACEE/` - shared Egypt, Czechia, Hungary, Poland, Romania, and seven South African source modules.
- `memory_sources/` - later Codex extraction/repair code; see its README for required external evidence and limitations.
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

For a full script-by-script command list, see `SCRIPT_INDEX.md`.

## Data Policy

Generated CSV/JSONL/XLSX outputs are ignored by git under `output/` folders. This keeps the repository focused on scripts, important documentation, and reproducible instructions.

## Claude Mapping scripts (added 2026-10-13)

Country tender extraction and mapping scripts from the local `Claude Mapping` workspace, one folder per `Country_Website`:
`Vietnam_VNEPS/`, `Turkey_EKAP/`, `SaudiArabia_NUPCO/`, `Kuwait_CAPT/`, `UAE_Dubai_eSupply/`, `Pakistan_KP_DGHS/`, `Pakistan_PPRA_EPMS/`, `Pakistan_KPPRA/`, `Pakistan_Sindh_PPRA/`, `Honduras_ONCAE/`, `ElSalvador_COMPRASAL/`, plus the shared `Shared_TURMECA_Pipeline/`, `Shared_ES_HN_Pipeline/` and `Shared_Taxonomy_Mapping/` code they import.
See `CLAUDE_MAPPING_INDEX.md` for the folder table, original layout, import notes and dependencies.
