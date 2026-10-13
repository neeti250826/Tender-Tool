# Country and Website Source Audit

As of **2026-10-13**.

Compared both GitHub default branches, 29 countries plus TED, and 65 country/source entries against available Codex work.

This is a **source-code and saved-evidence audit**, not a fresh tender-data extraction. A script being present does not prove current portal access, award status, complete national coverage, or data refreshed through today.

## Evidence and Version Decisions

- Baselines: personal `0ec484f`; organization `7fcaa85`. Existing October mapping packages were preserved.
- Read the Codex session index and relevant September 30 / October 6 completion records, local source registries, ACEE status notes, and independent Turkey/KSA reviews.
- Compared source content with Clearstate, TURMECA, LATAM, and Costa Rica workspaces. Timestamp or filename alone was not used to replace a different implementation.
- Both repositories now contain the same reviewed source set. Country-folder, portal-package, and mapping variants are retained with their original layouts.
- `source_sync_manifest.json` records original/final content hashes and import decisions. `country_website_catalog.json` is the machine-readable source inventory.

## Missing or Limited Coverage

| Country / site | Remaining gap |
|---|---|
| Egypt / UPA | Public listing code exists. Saved June research found item booklets CAPTCHA-gated; complete awarded items are not established. |
| Egypt / eTenders | No implemented extractor found; June research records HTTP timeouts. Reachability was not re-certified today. |
| Kuwait / Central Bank of Kuwait | Documentation-only package; no reviewed medical award scraper found. |
| Pakistan / Sindh PPRA | Reachability/link probe only, not an awarded-data extractor; historical notes report geographic access constraints. |
| Panama / PanamaCompra | Output datasets are referenced, but no portal scraper was found in the audited repositories/local sources. CANLAT record extraction is downstream workbook processing. |
| Spain / National procurement portal | Spain/drive_extracts/Spain_Tender contains Ecuador ComprasPublicas code, not Spanish procurement. No Spain implementation found. |
| United Arab Emirates / SSMC | Public tender/RFQ listings and access checks do not establish published awards. |
| United Arab Emirates / Abu Dhabi GPG | September continuation found all 294 examined details Pending Award; no new confirmed awards were added. |
| United Arab Emirates / Federal DPP | September source-discovery/access code only; no complete awarded item dataset established. Use URLs inside the adapter for exact probed routes. |
| United Arab Emirates / Rafed | September source-discovery/access code only; no complete awarded item dataset established. Use URLs inside the adapter for exact probed routes. |
| United Arab Emirates / Bayanat | September source-discovery/access code only; no complete awarded item dataset established. Use URLs inside the adapter for exact probed routes. |
| United Arab Emirates / Emirates Health Services | September source-discovery/access code only; no complete awarded item dataset established. Use URLs inside the adapter for exact probed routes. |
| United Arab Emirates / Ajman Tawreed | September source-discovery/access code only; no complete awarded item dataset established. Use URLs inside the adapter for exact probed routes. |
| United Arab Emirates / Sharjah Finance | September source-discovery/access code only; no complete awarded item dataset established. Use URLs inside the adapter for exact probed routes. |
| United Arab Emirates / Ras Al Khaimah | September source-discovery/access code only; no complete awarded item dataset established. Use URLs inside the adapter for exact probed routes. |

Costa Rica is no longer data-links-only: the missing SICOP browser/evidence adapters were recovered. The Spain provenance folder remains Ecuador code and is explicitly not counted as Spanish coverage.

## Corrections

- Restored missing country packages and shared imports across the two repositories; added ACEE source modules, Mexico incremental tools, ePerolehan, SICOP, and later Codex source/repair adapters.
- Updated CAPT multi-page saved capture handling, shared target-category metadata, Singapore Selenium source, and EKAP Python header generation.
- Fixed malformed Poland notebook JSON, a Romania CPV f-string incompatible with Python 3.11, and IPython shell syntax in the Malaysia Python command export.
- Added explicit date arguments and current-date defaults for active Colombia/ePerolehan entrypoints. Historical snapshots and year-specific extraction modes keep their original windows.
- Corrected READMEs that described existing code as missing or claimed a scraper existed in an empty package.

## Country / Website Inventory

`Missing` below refers to source code in the cataloged repository paths, not proof that no tender data exists anywhere. Paths link to the preferred implementation; JSON lists alternate implementations.

| Country | Website | Personal before | Organization before | Available now | Primary source |
|---|---|---|---|---|---|
| Brazil | ComprasNet | Partial | Partial | extractor | [Api_test.py](../brazil-comprasnet/Api_test.py) |
| Brazil | PNCP | Partial | Partial | extractor | [Scraper.py](../brazil-pncp/Scraper.py) |
| Brazil | Ministry of Health | Missing | Present | extractor | [scrape_dispensa_saude.py](../brazil-ministry-health/scrape_dispensa_saude.py) |
| Canada | CanadaBuys | Missing | Present | notebook | [CanadaBuysScraper_Colab.ipynb](../canada-canadabuys/CanadaBuysScraper_Colab.ipynb) |
| Colombia | SECOP | Missing | Updated | extractor | [extract.py](../colombia-secop/extract.py) |
| Costa Rica | SICOP | Missing | Missing | browser and evidence adapter | [fetch_sicop_all_slices.js](../costa-rica-sicop/sicop_adapter/fetch_sicop_all_slices.js) |
| Czechia | NEN | Partial | Partial | extractor | [czechia_nen.py](../ACEE/harness/sources/czechia_nen.py) |
| Ecuador | ComprasPublicas | Partial | Partial | extractor | [ec_compraspublicas_collected.py](../ecuador-compraspublicas/ec_compraspublicas_collected.py) |
| Egypt | GCS | Missing | Missing | extractor | [scrape_egypt_awarded_sources.py](../ACEE/scripts/scrape_egypt_awarded_sources.py) |
| Egypt | UPA | Missing | Present | listing only | [egypt_upa_scraper.py](../egypt-upa/egypt_upa_scraper.py) |
| Egypt | eTenders | Missing | Missing | research only | No scraper found |
| Egypt | World Bank awards | Missing | Missing | supplemental extractor | [scrape_egypt_world_bank_country_awards.py](../ACEE/scripts/scrape_egypt_world_bank_country_awards.py) |
| El Salvador | COMPRASAL | Partial | Partial | extractor with reviewed inventory | [es_fetch_details.py](../ElSalvador_COMPRASAL/es_fetch_details.py) |
| El Salvador | Transparency: ISSS/MINSAL | Missing | Missing | extractor and evidence adapter | [crawl.py](../memory_sources/LATAM/research/transparencia_vpn_recovery/scripts/crawl.py) |
| Honduras | ONCAE/HonduCompras/SICC | Partial | Partial | extractor | [hn_extract.py](../Honduras_ONCAE/hn_extract.py) |
| El Salvador and Honduras | UNGM | Missing | Missing | supplemental extractor | [crawl.py](../memory_sources/LATAM/research/donors/ungm_es_all_awards/crawl.py) |
| El Salvador and Honduras | World Bank | Missing | Missing | supplemental extractor | [worldbank_extract.py](../memory_sources/LATAM/research/worldbank_extract.py) |
| Hungary | EKR | Missing | Partial | extractor | [ekr_scraper.py](../hungary-ekr/ekr_scraper.py) |
| Hungary | NEAK | Missing | Present | extractor | [neak_scraper.py](../hungary-neak/neak_scraper.py) |
| India | eProcure | Partial | Partial | browser extractor | [scraper_updated.py](../india-eprocure/scraper_updated.py) |
| Kuwait | CAPT | Updated | Partial | browser and evidence extractor | [capt_awarded_scraper.py](../Kuwait/CAPT/capt_awarded_scraper.py) |
| Kuwait | Central Bank of Kuwait | Missing | Missing | research only | No scraper found |
| Kuwait | Official Gazette | Missing | Missing | evidence adapter | [kuwait_gazette_repair_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/kuwait/repair_v2/adapters/kuwait_gazette_repair_adapter.py) |
| Malaysia | MOH | Partial | Partial | extractor | [moh_scraper.py](../malaysia-moh/moh_scraper.py) |
| Malaysia | ePerolehan | Missing | Missing | browser extractor | [eperolehan_scraper.py](../malaysia-eperolehan/eperolehan_scraper.py) |
| Mexico | Compras MX | Partial | Missing | browser extractor | [scrape_step2.py](../mexico-compras-mx/src/scrape_step2.py) |
| Pakistan | PPRA/EPMS | Partial | Partial | extractor and evidence adapter | [ppra_awarded_scraper.py](../Pakistan/PPRA/ppra_awarded_scraper.py) |
| Pakistan | ePADS | Partial | Missing | extractor | [epads_item_scraper.py](../Pakistan/EPADS/epads_item_scraper.py) |
| Pakistan | DRAP | Present | Missing | extractor | [drap_item_scraper.py](../Pakistan/DRAP/drap_item_scraper.py) |
| Pakistan | KP health/DGHS | Present | Present | PDF extractor | [parse_kp_ber.py](../Pakistan_KP_DGHS/parse_kp_ber.py) |
| Pakistan | KPPRA | Present | Present | listing and PDF extractor | [kppra_lists.py](../Pakistan_KPPRA/kppra_lists.py) |
| Pakistan | Sindh PPRA | Present | Present | access probe only | [probe.js](../Pakistan_Sindh_PPRA/probe.js) |
| Pakistan | ADB | Present | Missing | supplemental extractor | [adb_health_awards_scraper.py](../Pakistan/ADB/adb_health_awards_scraper.py) |
| Pakistan | World Bank | Partial | Missing | supplemental extractor | [worldbank_health_awards_scraper.py](../Pakistan/WorldBank/worldbank_health_awards_scraper.py) |
| Panama | PanamaCompra | Missing | Missing | output links only | No scraper found |
| Peru | OECE/SEACE | Partial | Partial | extractor | [Scrape.py](../peru-oece/Scrape.py) |
| Poland | e-Zamowienia | Partial | Partial | extractor | [poland_ezamowienia.py](../ACEE/harness/sources/poland_ezamowienia.py) |
| Romania | SEAP/SICAP and TED fallback | Missing | Updated | extractor | [ro_seap_scraper.py](../romania-seap/ro_seap_scraper.py) |
| Saudi Arabia | NUPCO | Partial | Partial | extractor and repair adapter | [nupco_tender_memory_adapter.py](../saudi-arabia-nupco/nupco_tender_memory_adapter.py) |
| Saudi Arabia | Etimad | Partial | Partial | extractor | [etimad_awards_scraper.py](../saudi-arabia-etimad/etimad_awards_scraper.py) |
| Singapore | GeBIZ | Updated | Missing | browser extractor | [gebiz_awarded_selenium.py](../singapore-gebiz/gebiz_awarded_selenium.py) |
| South Korea | G2B | Missing | Present | browser extractor | [g2b_production_scraper_buyer_final.py](../south-korea-g2b/g2b_production_scraper_buyer_final.py) |
| South Africa | eTenders | Missing | Partial | extractor | [south_africa_etenders.py](../ACEE/harness/sources/south_africa_etenders.py) |
| South Africa | National Department of Health | Missing | Missing | extractor | [south_africa_ndoh.py](../ACEE/harness/sources/south_africa_ndoh.py) |
| South Africa | Eastern Cape Health | Missing | Missing | extractor | [south_africa_echealth.py](../ACEE/harness/sources/south_africa_echealth.py) |
| South Africa | North West Premier | Missing | Missing | extractor | [south_africa_nwpg_premier.py](../ACEE/harness/sources/south_africa_nwpg_premier.py) |
| South Africa | Limpopo Health | Missing | Missing | extractor | [south_africa_ldoh.py](../ACEE/harness/sources/south_africa_ldoh.py) |
| South Africa | KZN tender awards | Missing | Missing | extractor | [south_africa_kznhealth.py](../ACEE/harness/sources/south_africa_kznhealth.py) |
| South Africa | KZN quotation awards | Missing | Missing | extractor | [south_africa_kznhealth_quotations.py](../ACEE/harness/sources/south_africa_kznhealth_quotations.py) |
| Spain | National procurement portal | Missing | Missing | missing scraper | No scraper found |
| Thailand | e-GP | Missing | Present | browser extractor | [Collect_urls.py](../thailand-gprocurement/Collect_urls.py) |
| Turkey | EKAP/KIK e-Devlet | Partial | Updated | browser and repair extractor | [ekap_extract.py](../turkey-ekap/ekap_extract.py) |
| United Arab Emirates | Dubai eSupply | Partial | Partial | browser extractor | [dubai_esupply_scraper.py](../UAE/Dubai_eSupply/dubai_esupply_scraper.py) |
| United Arab Emirates | SSMC | Missing | Partial | listing only | [ssmc_tenders_scraper.py](../uae-ssmc/ssmc_tenders_scraper.py) |
| United Arab Emirates | Abu Dhabi GPG | Missing | Missing | listing and audit adapter | [adgpg_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/adgpg_adapter.py) |
| United Arab Emirates | Federal DPP | Missing | Missing | access probe only | [federal_dpp_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/federal_dpp_adapter.py) |
| United Arab Emirates | Rafed | Missing | Missing | access probe only | [rafed_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/rafed_adapter.py) |
| United Arab Emirates | Bayanat | Missing | Missing | access probe only | [bayanat_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/bayanat_adapter.py) |
| United Arab Emirates | Emirates Health Services | Missing | Missing | access probe only | [ehs_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/ehs_adapter.py) |
| United Arab Emirates | Ajman Tawreed | Missing | Missing | access probe only | [ajman_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/ajman_adapter.py) |
| United Arab Emirates | Sharjah Finance | Missing | Missing | access probe only | [sharjah_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/sharjah_adapter.py) |
| United Arab Emirates | Ras Al Khaimah | Missing | Missing | access probe only | [rak_adapter.py](../memory_sources/TURMECA/tender_memory_run_2026-09-30/missing_source_refresh/execution/uae/20260930T131832Z/adapters/rak_adapter.py) |
| United States | FPDS | Missing | Present | notebook | [FPDS_Awards_Scraper.ipynb](../united-states-fpds/FPDS_Awards_Scraper.ipynb) |
| Vietnam | VNEPS / muasamcong | Partial | Partial | browser extractor | [vneps_console_extractor.js](../Vietnam_VNEPS/extractor/vneps_console_extractor.js) |
| European Union | TED | Missing | Present | extractor | [ted_colab_scraper.py](../european-union-ted/ted_colab_scraper.py) |

## Validation and Limits

- Run `python tools/validate_sources.py` for Python compilation, notebook JSON, catalog paths, and recorded file hashes.
- Run `python -m unittest discover -s tests -p "test_source_audit.py"` for targeted parser/import/date regressions.
- CLI checks and offline parser tests do not establish that all external websites are currently available. See `validation_results.json` for the checks actually completed.
- ACEE full smoke probes expect retained source fixtures under `ACEE/evidence`; these raw captures are not uploaded. Source-registry/module loading and representative parser logic are tested separately.
- Memory adapters often consume frozen CSV/JSON/PDF evidence and review manifests. These inputs are intentionally outside GitHub. Their missing inputs must not be interpreted as a successful zero-row crawl.
- September independent reviews still report Turkey and KSA as source-limited. No new complete tender datasets or national completeness claims are made by this sync.
