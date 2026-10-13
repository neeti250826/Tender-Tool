from __future__ import annotations

from importlib import import_module


MODULE_PATHS = {
    "czechia_nen": "harness.sources.czechia_nen",
    "egypt_gcs": "harness.sources.egypt_gcs",
    "hungary_ekr": "harness.sources.hungary_ekr",
    "poland_ezamowienia": "harness.sources.poland_ezamowienia",
    "romania_sicap": "harness.sources.romania_sicap",
    "south_africa_echealth": "harness.sources.south_africa_echealth",
    "south_africa_etenders": "harness.sources.south_africa_etenders",
    "south_africa_kznhealth": "harness.sources.south_africa_kznhealth",
    "south_africa_kznhealth_quotations": "harness.sources.south_africa_kznhealth_quotations",
    "south_africa_ldoh": "harness.sources.south_africa_ldoh",
    "south_africa_ndoh": "harness.sources.south_africa_ndoh",
    "south_africa_nwpg_premier": "harness.sources.south_africa_nwpg_premier",
}


def load_source_module(source_key: str):
    if source_key not in MODULE_PATHS:
        raise KeyError(f"No loadable source module registered for {source_key}")
    return import_module(MODULE_PATHS[source_key])
