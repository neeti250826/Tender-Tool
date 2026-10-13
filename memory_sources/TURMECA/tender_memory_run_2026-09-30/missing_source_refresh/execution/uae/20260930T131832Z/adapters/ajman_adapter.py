from pathlib import Path
from simple_probe import run_probe

def run(root: Path) -> dict:
    return run_probe(root, "ajman_tawreed_public", "Ajman Tawreed / Department of Finance public layer", [
        "https://ajman.ae/en/node/343", "https://www.ajmandof.ae/",
    ], "Full results require registered Tawreed/ERP access or an official award/PO export; the public registry is an entry point.")
