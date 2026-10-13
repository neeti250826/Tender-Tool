from pathlib import Path
from simple_probe import run_probe

def run(root: Path) -> dict:
    return run_probe(root, "northern_emirates_ehs_public", "Emirates Health Services public/federal entry layer", [
        "https://www.ehs.gov.ae/", "https://procurement.gov.ae/page.aspx/en/usr/login",
    ], "EHS award/PO/contract results require the federal DPP or an official EHS export; public facility pages are not award evidence.")
