# Recovered Codex Source Packages

Code recovered from September TURMECA and October LATAM work. Original relative layouts are retained so sibling imports and evidence paths remain understandable. This is a source archive, not a complete extraction release.

## TURMECA

- `agent_work/turkey_repair_v2/adapter/turkey_ekap_adapter_v2.py`: official KIK/e-Devlet repair for known notice IDs, Turkish amount parsing, and complete notice-group preservation.
- `agent_work/ksa_repair_v2/nupco_adapter_v2.py`: live NUPCO inventory discovery; its extraction contract consumes `npt_candidate_rows.csv` from the reviewed evidence run.
- `agent_work/ksa_repair_v2/custom_layout_parser_v2.py`: specialized PDF layouts from the September repair. It expects the retained v1 PDF/notices bundle.
- `tender_memory_run_2026-09-30/missing_source_refresh/execution/`: Kuwait Gazette/CAPT, Pakistan EPMS, and UAE source adapters. Several UAE files are access probes only.

Use the [country/source catalog](../docs/country_website_catalog.json) to distinguish extraction from a probe. Review reports are historical evidence of code behavior and remaining gaps. They are not a new delivery approval.

## LATAM

COMPRASAL recovery, El Salvador transparency crawlers, Honduras bulk/document extraction, and UNGM/World Bank supplemental sources are preserved under `LATAM/research/`.

The corrected COMPRASAL adapter is `comprasal_vpn_recovery/revision_001/adapter.py`; it deliberately marks whole-procedure commitments as ineligible for item or supplier sizing. Its revision manifests, rows, and correction ledger are required inputs. The transparency adapter also verifies frozen manifest hashes before returning reviewed rows.

Raw PDFs/HTML/JSON, source workbooks, approved row bundles, taxonomy workbooks, cookies, and private browser sessions are not part of this source import. Configure or restore the required inputs before running a snapshot adapter. A missing input is not evidence of zero awards.

Existing historical scripts can contain fixed extraction windows or workspace-specific artifact paths. Do not use a historical snapshot builder as a current live crawler. No source completeness or current-date data refresh is implied.
