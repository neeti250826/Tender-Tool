from pathlib import Path
from simple_probe import run_probe

def run(root: Path) -> dict:
    return run_probe(root, "ssmc_public", "Sheikh Shakhbout Medical City tender/RFQ public layer", [
        "https://ssmc.ae/tenders/", "https://ssmc.ae/tender-rfq/",
    ], "Public RFQ leads are not awards. Scripted REST/AJAX is bounded by Cloudflare; no CAPTCHA or access-control bypass was attempted.")
