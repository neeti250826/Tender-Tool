from pathlib import Path
from simple_probe import run_probe

def run(root: Path) -> dict:
    return run_probe(root, "sharjah_finance_public", "Sharjah Finance eProcurement public layer", [
        "https://www.sfd.gov.ae/En/Services/Pages/VendorsRegistration.aspx",
        "https://www.eprocurement.sfd.gov.ae/",
        "https://www.sfd.gov.ae/Ar/Services/Pages/VendorsPortal.aspx",
    ], "Approved quotations, POs and payments are registered-supplier/Tahseel surfaces; submitted quotations are not awards.")
