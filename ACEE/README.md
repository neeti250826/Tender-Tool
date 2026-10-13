# ACEE Source Harness

Recovered from the local Clearstate ACEE project on 2026-10-13. Keep the package intact: source modules import `harness.shared` and each other.

From this directory:

```powershell
pip install -r requirements.txt
python -m harness.runner --list-sources
python -m harness.runner --help
python scripts/run_south_africa_full_scrape.py --help
python scripts/run_romania_ted_full_scrape.py --help
python scripts/scrape_egypt_awarded_sources.py --help
```

Run a bounded date window before a long extraction. Source-specific flags and access limitations are exposed by the individual runners.

`harness.smoke_test` uses original source captures under `evidence/`. Those captures, PDFs, cookies, and output datasets remain outside GitHub. This audit validates registry/module loading and parser behavior separately; it does not claim the fixture-based full smoke suite passed.

The dated notes in `docs/` record historical live checks, not current availability. Egypt UPA booklet access and Egypt eTenders remain limited; listing rows must not be reclassified as awards without evidence.
