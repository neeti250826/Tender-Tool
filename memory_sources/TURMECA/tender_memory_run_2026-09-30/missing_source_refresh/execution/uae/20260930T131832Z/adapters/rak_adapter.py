from pathlib import Path
from simple_probe import run_probe

def run(root: Path) -> dict:
    return run_probe(root, "rak_supply_public", "RAK Supply / Coupa public layer", [
        "https://supply.rak.ae/", "https://finance.rak.ae/services",
    ], "Awarded sourcing events and POs require legitimate Coupa supplier access; public opportunities are not final results.")
