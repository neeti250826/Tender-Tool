from __future__ import annotations

from pathlib import Path

from harness.shared.schema import OUTPUT_COLUMNS
from harness.shared.serialize import write_header_only_csv
from harness.sources.loader import load_source_module
from harness.sources.registry import feasible_sources


def main() -> int:
    feasible = feasible_sources()
    assert feasible, "Expected at least one feasible source."
    assert "source" in OUTPUT_COLUMNS and "dedup_key" in OUTPUT_COLUMNS

    out_path = Path("outputs") / "smoke_header.csv"
    write_header_only_csv(out_path)
    text = out_path.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("source,country,country_cc,publication_date")

    czechia_probe = load_source_module("czechia_nen").smoke_probe()
    egypt_probe = load_source_module("egypt_gcs").smoke_probe()
    hungary_probe = load_source_module("hungary_ekr").smoke_probe()
    poland_probe = load_source_module("poland_ezamowienia").smoke_probe()
    romania_probe = load_source_module("romania_sicap").smoke_probe()
    sa_probe = load_source_module("south_africa_etenders").smoke_probe()
    sa_echealth_probe = load_source_module("south_africa_echealth").smoke_probe()
    sa_kzn_probe = load_source_module("south_africa_kznhealth").smoke_probe()
    sa_kzn_quote_probe = load_source_module("south_africa_kznhealth_quotations").smoke_probe()
    sa_ldoh_probe = load_source_module("south_africa_ldoh").smoke_probe()
    sa_ndoh_probe = load_source_module("south_africa_ndoh").smoke_probe()
    sa_nwpg_probe = load_source_module("south_africa_nwpg_premier").smoke_probe()
    assert czechia_probe.ok, "Expected Czechia source smoke probe to pass."
    assert egypt_probe.ok, "Expected Egypt GCS source smoke probe to pass."
    assert hungary_probe.ok, "Expected Hungary EKR source smoke probe to pass."
    assert poland_probe.ok, "Expected Poland source smoke probe to pass."
    assert romania_probe.ok, "Expected Romania SICAP source smoke probe to pass."
    assert sa_probe.ok, "Expected South Africa source smoke probe to pass."
    assert sa_echealth_probe.ok, "Expected South Africa Eastern Cape source smoke probe to pass."
    assert sa_kzn_probe.ok, "Expected South Africa KZN source smoke probe to pass."
    assert sa_kzn_quote_probe.ok, "Expected South Africa KZN quotation source smoke probe to pass."
    assert sa_ldoh_probe.ok, "Expected South Africa Limpopo source smoke probe to pass."
    assert sa_ndoh_probe.ok, "Expected South Africa NDoH source smoke probe to pass."
    assert sa_nwpg_probe.ok, "Expected South Africa North West Premier source smoke probe to pass."

    print("feasible_sources=", len(feasible))
    print("smoke_output=", str(out_path.resolve()))
    print("czechia_probe=", czechia_probe.ok)
    print("egypt_probe=", egypt_probe.ok)
    print("hungary_probe=", hungary_probe.ok)
    print("poland_probe=", poland_probe.ok)
    print("romania_probe=", romania_probe.ok)
    print("south_africa_probe=", sa_probe.ok)
    print("south_africa_echealth_probe=", sa_echealth_probe.ok)
    print("south_africa_kznhealth_probe=", sa_kzn_probe.ok)
    print("south_africa_kznhealth_quotations_probe=", sa_kzn_quote_probe.ok)
    print("south_africa_ldoh_probe=", sa_ldoh_probe.ok)
    print("south_africa_ndoh_probe=", sa_ndoh_probe.ok)
    print("south_africa_nwpg_premier_probe=", sa_nwpg_probe.ok)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
