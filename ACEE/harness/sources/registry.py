from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SourceConfig:
    key: str
    source: str
    country: str
    country_cc: str
    feasible: bool
    extraction_mode: str
    medical_strategy: str
    item_strategy: str
    output_dir: str
    smoke_filename: str = "smoke_sample_rows.csv"
    evidence_urls: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)


SOURCES: Dict[str, SourceConfig] = {
    "egypt_gcs": SourceConfig(
        key="egypt_gcs",
        source="gcs.digitalegypt.gov.eg",
        country="Egypt",
        country_cc="EG",
        feasible=True,
        output_dir="Egypt/gcs-digitalegypt-gov-eg",
        extraction_mode="public_html_with_session_behavior",
        medical_strategy="filter by healthcare-related entities or categories",
        item_strategy="extract item name, unit, and quantity from tender detail pages",
        evidence_urls=["https://gcs.digitalegypt.gov.eg/"],
    ),
    "czechia_nen": SourceConfig(
        key="czechia_nen",
        source="nen.nipez.cz",
        country="Czechia",
        country_cc="CZ",
        feasible=True,
        output_dir="Czechia/nen-nipez-cz",
        extraction_mode="public_html",
        medical_strategy="filter by item text, codes, and authority",
        item_strategy="extract public subject-matter item details and lot signals",
        evidence_urls=["https://nen.nipez.cz/en/verejne-zakazky"],
    ),
    "hungary_ekr": SourceConfig(
        key="hungary_ekr",
        source="ekr.gov.hu",
        country="Hungary",
        country_cc="HU",
        feasible=True,
        output_dir="Hungary/ekr-gov-hu",
        extraction_mode="public_notice_api_plus_document_parsing",
        medical_strategy="filter notices by buyer, title, notice text, and documents",
        item_strategy="recover item detail from PDFs or TED-linked documents when public fields are sparse",
        evidence_urls=["https://ekr.gov.hu/portal/kozbeszerzes/hirdetmenyek"],
    ),
    "poland_ezamowienia": SourceConfig(
        key="poland_ezamowienia",
        source="ezamowienia.gov.pl",
        country="Poland",
        country_cc="PL",
        feasible=True,
        output_dir="Poland/ezamowienia-gov-pl",
        extraction_mode="public_html_plus_public_api",
        medical_strategy="filter by title, lot text, and notice content",
        item_strategy="extract item details from public HTML or lot text even when not normalized",
        evidence_urls=["https://ezamowienia.gov.pl/en/"],
    ),
    "romania_sicap": SourceConfig(
        key="romania_sicap",
        source="e-licitatie.ro",
        country="Romania",
        country_cc="RO",
        feasible=True,
        output_dir="Romania/seap-sicap",
        extraction_mode="public_html_plus_public_documents",
        medical_strategy="filter by healthcare CPV codes and medical titles",
        item_strategy="extract item rows or lot text including item, quantity, and unit",
        evidence_urls=["https://e-licitatie.ro/"],
    ),
    "south_africa_etenders": SourceConfig(
        key="south_africa_etenders",
        source="data.etenders.gov.za",
        country="South Africa",
        country_cc="ZA",
        feasible=True,
        output_dir="South Africa/data-etenders-gov-za",
        extraction_mode="public_ocds_api_plus_attachment_parsing",
        medical_strategy="filter by title, description, buyer, and healthcare attachments",
        item_strategy="extract item details from official attachments when API items are sparse",
        evidence_urls=[
            "https://data.etenders.gov.za/",
            "https://ocds-api.etenders.gov.za/swagger/index.html",
        ],
    ),
    "south_africa_echealth": SourceConfig(
        key="south_africa_echealth",
        source="echealth.gov.za",
        country="South Africa",
        country_cc="ZA",
        feasible=True,
        output_dir="South Africa/echealth-gov-za",
        extraction_mode="public_award_listing_plus_ocr_of_scanned_award_pdfs",
        medical_strategy="filter Eastern Cape award listings and OCR rows for pharmaceutical, surgical, and medical item relevance",
        item_strategy="recover awarded contract rows from scanned PE Pharmaceutical Depot award notices via OCR and map item text from contract descriptions",
        evidence_urls=[
            "https://www.echealth.gov.za/index.php/tenders/tender-award-s",
        ],
    ),
    "south_africa_ndoh": SourceConfig(
        key="south_africa_ndoh",
        source="health.gov.za",
        country="South Africa",
        country_cc="ZA",
        feasible=True,
        output_dir="South Africa/health-gov-za",
        extraction_mode="public_html_plus_award_notice_documents",
        medical_strategy="filter NDoH tender rows by medical or healthcare relevance before parsing award notices",
        item_strategy="recover item detail from award notice PDFs when an item-awarded column is present, otherwise fall back to the tender description",
        evidence_urls=[
            "https://www.health.gov.za/tenders/",
        ],
    ),
    "south_africa_nwpg_premier": SourceConfig(
        key="south_africa_nwpg_premier",
        source="premier.nwpg.gov.za",
        country="South Africa",
        country_cc="ZA",
        feasible=True,
        output_dir="South Africa/premier-nwpg-gov-za",
        extraction_mode="public_tender_bulletin_pdf",
        medical_strategy="parse North West Premier tender bulletin sections labeled Department of Health term contract awards",
        item_strategy="map each published health award row from the bulletin table as a contract-level item description",
        evidence_urls=[
            "https://premier.nwpg.gov.za/tenders/",
            "https://premier.nwpg.gov.za/wp-content/uploads/2025/11/NUMBER-34-0F-2025-and-2026.pdf",
        ],
    ),
    "south_africa_ldoh": SourceConfig(
        key="south_africa_ldoh",
        source="ldoh.gov.za",
        country="South Africa",
        country_cc="ZA",
        feasible=True,
        output_dir="South Africa/ldoh-gov-za",
        extraction_mode="public_awarded_tenders_page_plus_public_pdf_notices",
        medical_strategy="filter Limpopo awarded-tenders notice titles and parse only medical or healthcare award PDFs from the public listing",
        item_strategy="recover contract-level item descriptions, suppliers, award dates, and visible award amounts or rate-based award signals from public notice PDFs",
        evidence_urls=[
            "https://www.ldoh.gov.za/?q=node/12",
            "https://www.ldoh.gov.za/ldoh-admin/documents/latestnews/documents/",
        ],
    ),
    "south_africa_kznhealth": SourceConfig(
        key="south_africa_kznhealth",
        source="kznhealth.gov.za",
        country="South Africa",
        country_cc="ZA",
        feasible=True,
        output_dir="South Africa/kznhealth-gov-za",
        extraction_mode="public_awarded_pages_plus_public_pdf_notices",
        medical_strategy="filter KZN awarded tender PDFs by direct healthcare, clinical-equipment, medical-service, and health-facility description text",
        item_strategy="recover notice-level or institution-level awarded rows from public KZN award PDFs and preserve item-level descriptions when exposed on the first pages",
        evidence_urls=[
            "https://www2.kznhealth.gov.za/Tenders/Awarded/awarded-tenders2024.htm",
            "https://www.kznhealth.gov.za/scm/tender-awards-2025/",
            "https://www.kznhealth.gov.za/scm/tender-awards-2026/",
        ],
    ),
    "south_africa_kznhealth_quotations": SourceConfig(
        key="south_africa_kznhealth_quotations",
        source="kznhealth.gov.za",
        country="South Africa",
        country_cc="ZA",
        feasible=True,
        output_dir="South Africa/kznhealth-gov-za-quotations",
        extraction_mode="public_quotation_awards_pages_plus_public_pdf_notice_ocr",
        medical_strategy="filter KZN quotation-awards HTML rows by strong medical and healthcare item or service terms before OCRing award PDFs",
        item_strategy="recover quote description, supplier, award amount, and publication date from public quotation-award PDFs and keep the HTML description as the item detail",
        evidence_urls=[
            "https://www.kznhealth.gov.za/scm/quotation-awards/",
            "https://www.kznhealth.gov.za/scm/awards-april-2026/",
        ],
    ),
    "egypt_etenders": SourceConfig(
        key="egypt_etenders",
        source="etenders.gov.eg",
        country="Egypt",
        country_cc="EG",
        feasible=False,
        output_dir="Egypt/etenders-gov-eg",
        extraction_mode="blocked_http_timeout",
        medical_strategy="unknown",
        item_strategy="unknown",
        blockers=["HTTP and HTTPS timed out during verification."],
        evidence_urls=["https://etenders.gov.eg/"],
    ),
    "egypt_upa": SourceConfig(
        key="egypt_upa",
        source="upa.gov.eg",
        country="Egypt",
        country_cc="EG",
        feasible=False,
        output_dir="Egypt/upa-gov-eg",
        extraction_mode="public_summary_plus_captcha_gated_booklet",
        medical_strategy="medical tender discovery from public listing pages",
        item_strategy="blocked by CAPTCHA-gated technical-specification booklet",
        blockers=["Item rows remain inside booklet downloads gated behind CAPTCHA."],
        evidence_urls=["https://upa.gov.eg/tenders/"],
    ),
}


def feasible_sources() -> List[SourceConfig]:
    return [config for config in SOURCES.values() if config.feasible]
